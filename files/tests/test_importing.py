"""The importing vocabulary — v0.6.0 Drop 3 (Plan 3), Phase 1.

Every value in ``shared.importing`` is a frozen dataclass validated on
construction, so these tests are mostly about what *cannot* be built. Nothing here
touches a real folder: paths are strings that need not exist, which is itself one
of the contracts — Phase 1 must be provably filesystem-free, and Phase 2 owns the
first line of code allowed to look at a disk.

The ``EffectiveConfig`` used below is assembled in memory rather than loaded, so
not even the committed ``config.toml`` is read.
"""

from __future__ import annotations

import os
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path, PurePath
from types import MappingProxyType

import pytest

from shared import config, importing
from shared.importing import (
    IdFactory,
    ImportContractError,
    ImportedFile,
    ImportedFileSnapshot,
    ImportOptions,
    ImportProblem,
    ImportRoot,
    INITIAL_REVISION,
    ProblemCategory,
    Revision,
    RootKind,
    ScanOutcome,
    ScanRequest,
    ScanResult,
    SupportedType,
    SupportedTypeCatalog,
    ensure_display_safe,
    normalize_extension,
)

# Absolute paths that deliberately do not exist. Constructing a value from one
# proves the contracts never consult the filesystem.
ROOT_PATH = Path(os.path.abspath(os.sep + "act-fixture-root"))
OTHER_ROOT = Path(os.path.abspath(os.sep + "act-other-root"))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def make_config(threshold: int = 1000) -> config.EffectiveConfig:
    """An in-memory EffectiveConfig. No file is read and nothing is cached."""
    return config.EffectiveConfig(
        project=config.ProjectConfig(
            name="Audiobook Creation Tool",
            version="0.5.1",
            python_min="3.11",
            entry_point="scripts/Universal/launcher.py",
            platforms=("Windows", "MacOS"),
        ),
        output=config.OutputConfig(base_directory=ROOT_PATH / "out", is_default=True),
        logging=config.LoggingConfig(max_sessions=30),
        importing=config.ImportingConfig(large_result_warning_threshold=threshold),
        sources=MappingProxyType({}),
        diagnostics=(),
    )


def catalog() -> SupportedTypeCatalog:
    return SupportedTypeCatalog((
        SupportedType("mp3", "MP3 audio", (".mp3",)),
        SupportedType("m4b", "M4B audiobook", (".m4b", ".m4a")),
    ))


def folder_root(order: int = 0, path: Path = ROOT_PATH, root_id: str = "root-1") -> ImportRoot:
    return ImportRoot(root_id, path, order)


def direct_root(order: int = 1, root_id: str = "direct-1") -> ImportRoot:
    return ImportRoot(root_id, None, order, RootKind.DIRECT_FILES)


def imported(
    occurrence_id: str = "occ-1",
    relative: str = "Book/01.mp3",
    root: ImportRoot | None = None,
    identity: str = "id-1",
) -> ImportedFile:
    root = folder_root() if root is None else root
    return ImportedFile(
        occurrence_id=occurrence_id,
        path=root.path / relative,
        source_root=root,
        relative_path=PurePath(relative),
        supported_type_id="mp3",
        identity=identity,
    )


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw", ["mp3", ".mp3", ".MP3", "MP3", "  .Mp3  "])
def test_every_spelling_of_an_extension_normalises_to_one_value(raw):
    assert normalize_extension(raw) == ".mp3"


@pytest.mark.parametrize(
    "raw",
    ["", "   ", ".", "..mp3", "tar.gz", "mp 3", "*.mp3", "?mp3", "a/b", "a\\b", 3, None],
)
def test_an_unusable_extension_is_refused(raw):
    with pytest.raises(ImportContractError):
        normalize_extension(raw)


def test_extension_normalisation_is_unicode_aware():
    """NFD and NFC spellings of the same suffix must not become two types."""
    composed = normalize_extension(".Ré")
    decomposed = normalize_extension(".Re\u0301")
    assert composed == decomposed


def test_display_text_must_stay_one_line_without_a_traceback():
    assert ensure_display_safe("m", "  Could not read the folder.  ") == "Could not read the folder."
    with pytest.raises(ImportContractError):
        ensure_display_safe("m", "line one\nline two")
    with pytest.raises(ImportContractError):
        ensure_display_safe("m", "Traceback (most recent call last): boom")
    with pytest.raises(ImportContractError):
        ensure_display_safe("m", "   ")
    assert ensure_display_safe("m", "", allow_blank=True) == ""


# --------------------------------------------------------------------------- #
# Stable identifiers and revisions
# --------------------------------------------------------------------------- #


def test_identifiers_are_unique_monotonic_and_predictable():
    factory = IdFactory("run7-")
    produced = [factory.next_id("file") for _ in range(3)]
    assert produced == ["run7-file-000001", "run7-file-000002", "run7-file-000003"]
    assert len(set(produced)) == 3


def test_two_factories_do_not_share_a_counter():
    a, b = IdFactory("a-"), IdFactory("b-")
    assert a.next_id("x") != b.next_id("x")


def test_identifier_allocation_is_thread_safe_and_starts_no_thread():
    """A lock, not a worker. The count of live threads must not move."""
    factory = IdFactory()
    before = threading.active_count()
    produced: list[str] = []
    lock = threading.Lock()

    def take() -> None:
        mine = [factory.next_id("occ") for _ in range(200)]
        with lock:
            produced.extend(mine)

    workers = [threading.Thread(target=take) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive(), "id allocation should never block"

    assert len(produced) == 800
    assert len(set(produced)) == 800, "a duplicate id would break occurrence identity"
    assert threading.active_count() == before


def test_a_factory_refuses_an_unusable_kind_or_prefix():
    with pytest.raises(ImportContractError):
        IdFactory().next_id("")
    with pytest.raises(ImportContractError):
        IdFactory().next_id("two words")
    with pytest.raises(ImportContractError):
        IdFactory("has space")


def test_revisions_advance_compare_and_start_at_zero():
    assert INITIAL_REVISION == Revision(0)
    assert INITIAL_REVISION.advance() == Revision(1)
    assert INITIAL_REVISION.advance().advance() == Revision(2)
    assert Revision(1) < Revision(2)
    assert sorted([Revision(2), Revision(0), Revision(1)]) == [
        Revision(0), Revision(1), Revision(2)]
    with pytest.raises(ImportContractError):
        Revision(-1)
    with pytest.raises(ImportContractError):
        Revision(True)


def test_a_revision_is_immutable():
    revision = Revision(3)
    with pytest.raises(FrozenInstanceError):
        revision.value = 4
    assert revision.advance() is not revision


# --------------------------------------------------------------------------- #
# Supported types and catalogs
# --------------------------------------------------------------------------- #


def test_a_supported_type_normalises_and_deduplicates_its_extensions():
    entry = SupportedType("mp3", "MP3 audio", ["MP3", ".mp3", " .Mp3 "])
    assert entry.extensions == (".mp3",)


def test_a_supported_type_matches_by_name_without_touching_a_disk():
    entry = SupportedType("mp3", "MP3 audio", (".mp3",))
    assert entry.matches("Chapter 01.MP3")
    assert entry.matches(Path("/nowhere/at/all/x.mp3"))
    assert not entry.matches("cover.jpg")
    assert not entry.matches("no-suffix")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"type_id": "", "label": "L", "extensions": (".a",)},
        {"type_id": "two words", "label": "L", "extensions": (".a",)},
        {"type_id": "a/b", "label": "L", "extensions": (".a",)},
        {"type_id": "t", "label": "", "extensions": (".a",)},
        {"type_id": "t", "label": "one\ntwo", "extensions": (".a",)},
        {"type_id": "t", "label": "L", "extensions": ()},
        {"type_id": "t", "label": "L", "extensions": ".a"},
        {"type_id": "t", "label": "L", "extensions": (".a", "bad ext")},
    ],
)
def test_an_invalid_supported_type_cannot_be_constructed(kwargs):
    with pytest.raises(ImportContractError):
        SupportedType(**kwargs)


def test_a_catalog_reports_its_ids_extensions_and_owner():
    book = catalog()
    assert book.type_ids == ("mp3", "m4b")
    assert book.extensions == (".mp3", ".m4b", ".m4a")
    assert book.default_selection() == frozenset({"mp3", "m4b"})
    assert book.type_id_for_name("x.M4A") == "m4b"
    assert book.type_id_for_name("x.txt") is None
    assert book.type_for("m4b").label == "M4B audiobook"
    with pytest.raises(ImportContractError):
        book.type_for("nope")


def test_a_catalog_refuses_an_extension_claimed_by_two_types():
    """Otherwise ``supported_type_id`` would be ambiguous for that file."""
    with pytest.raises(ImportContractError) as excinfo:
        SupportedTypeCatalog((
            SupportedType("a", "A", (".mp3",)),
            SupportedType("b", "B", (".mp3",)),
        ))
    assert ".mp3" in str(excinfo.value)


def test_a_catalog_refuses_duplicate_ids_and_emptiness():
    with pytest.raises(ImportContractError):
        SupportedTypeCatalog((
            SupportedType("a", "A", (".x",)),
            SupportedType("a", "A again", (".y",)),
        ))
    with pytest.raises(ImportContractError):
        SupportedTypeCatalog(())


def test_the_shared_layer_hard_codes_no_media_list():
    """Each adopting tool supplies its own catalog; there is no global default."""
    source = Path(importing.__file__).read_text(encoding="utf-8")
    for extension in (".mp3", ".m4b", ".epub", ".pdf", ".jpg", ".png", ".heic"):
        assert f'"{extension}"' not in source, f"{extension} must not be baked into the shared layer"
    assert not [name for name in dir(importing)
                if name.isupper() and name.endswith(("_EXTENSIONS", "_TYPES", "_FORMATS"))]


# --------------------------------------------------------------------------- #
# Import options
# --------------------------------------------------------------------------- #


def test_all_supported_types_are_selected_by_default():
    options = ImportOptions.for_catalog(catalog())
    assert options.selected_type_ids == frozenset({"mp3", "m4b"})
    assert options.include_hidden_folders is False
    assert options.allow_duplicate_files is False
    assert options.has_selection


def test_selecting_nothing_is_representable_and_not_an_error():
    """The "you have not ticked anything" message belongs to the UI, not here."""
    options = ImportOptions()
    assert options.selected_type_ids == frozenset()
    assert options.has_selection is False


def test_options_reject_a_truthy_stand_in_for_a_bool():
    with pytest.raises(ImportContractError):
        ImportOptions(include_hidden_folders=1)
    with pytest.raises(ImportContractError):
        ImportOptions(allow_duplicate_files="yes")


def test_options_copy_their_selection_rather_than_aliasing_it():
    live = {"mp3"}
    options = ImportOptions(selected_type_ids=live)
    live.add("m4b")
    assert options.selected_type_ids == frozenset({"mp3"})


# --------------------------------------------------------------------------- #
# Roots
# --------------------------------------------------------------------------- #


def test_a_folder_root_records_the_users_own_order_and_mirrors():
    root = ImportRoot("r", ROOT_PATH, 2)
    assert root.kind is RootKind.FOLDER
    assert root.mirrors is True
    assert root.order == 2


def test_a_direct_files_root_has_no_mirroring_path():
    root = direct_root()
    assert root.path is None
    assert root.mirrors is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"root_id": "", "path": ROOT_PATH, "order": 0},
        {"root_id": "r", "path": None, "order": 0},
        {"root_id": "r", "path": Path("relative/dir"), "order": 0},
        {"root_id": "r", "path": ROOT_PATH / ".." / "x", "order": 0},
        {"root_id": "r", "path": ROOT_PATH, "order": -1},
        {"root_id": "r", "path": ROOT_PATH, "order": True},
        {"root_id": "r", "path": ROOT_PATH, "order": 0, "kind": "folder"},
    ],
)
def test_an_invalid_root_cannot_be_constructed(kwargs):
    with pytest.raises(ImportContractError):
        ImportRoot(**kwargs)


def test_a_direct_files_root_refuses_a_path():
    with pytest.raises(ImportContractError):
        ImportRoot("d", ROOT_PATH, 0, RootKind.DIRECT_FILES)


# --------------------------------------------------------------------------- #
# Imported files
# --------------------------------------------------------------------------- #


def test_an_imported_file_keeps_what_plan_two_planning_will_need():
    entry = imported(relative="Book One/Disc 1/03 - Chapter.mp3")
    assert entry.mirroring_root == ROOT_PATH
    assert entry.relative_parent == PurePath("Book One/Disc 1")
    assert entry.name == "03 - Chapter.mp3"
    assert entry.relative_path == PurePath("Book One/Disc 1/03 - Chapter.mp3")


def test_a_file_directly_under_its_root_has_no_relative_parent():
    entry = imported(relative="01.mp3")
    assert entry.relative_parent is None
    assert entry.mirroring_root == ROOT_PATH


def test_an_individually_added_file_routes_flat():
    """Decision 31A: no common tree, so nothing to mirror."""
    entry = ImportedFile("occ", OTHER_ROOT / "a.mp3", direct_root(), None, "mp3", "id")
    assert entry.mirroring_root is None
    assert entry.relative_parent is None
    assert entry.relative_path is None


def test_construction_never_consults_the_filesystem(tmp_path):
    """The paths above do not exist, and building values creates nothing."""
    before = sorted(os.listdir(tmp_path))
    entry = ImportedFile(
        "occ", tmp_path / "missing" / "deep" / "x.mp3",
        ImportRoot("r", tmp_path, 0), PurePath("missing/deep/x.mp3"), "mp3", "id")
    assert not entry.path.exists()
    assert sorted(os.listdir(tmp_path)) == before


def test_a_file_must_actually_sit_at_its_relative_path_under_its_root():
    root = folder_root()
    with pytest.raises(ImportContractError):
        ImportedFile("occ", OTHER_ROOT / "Book" / "01.mp3", root,
                     PurePath("Book/01.mp3"), "mp3", "id")


def test_a_relative_path_must_end_in_the_files_own_name():
    root = folder_root()
    with pytest.raises(ImportContractError):
        ImportedFile("occ", root.path / "Book" / "01.mp3", root,
                     PurePath("Book/02.mp3"), "mp3", "id")


@pytest.mark.parametrize(
    "relative",
    [PurePath("../escape.mp3"), ".", "", Path("/absolute/01.mp3"), PurePath("a/../b.mp3")],
)
def test_a_traversing_empty_or_absolute_relative_path_is_refused(relative):
    root = folder_root()
    with pytest.raises(ImportContractError):
        ImportedFile("occ", root.path / "01.mp3", root, relative, "mp3", "id")


def test_a_leading_dot_slash_is_normalised_away_by_pathlib_itself():
    """Recorded so the guard above is not mistaken for the thing that handles it."""
    assert PurePath("./01.mp3") == PurePath("01.mp3")
    entry = ImportedFile("occ", ROOT_PATH / "01.mp3", folder_root(), "./01.mp3", "mp3", "id")
    assert entry.relative_path == PurePath("01.mp3")


def test_a_folder_file_needs_a_relative_path_and_a_direct_file_must_not_have_one():
    root = folder_root()
    with pytest.raises(ImportContractError):
        ImportedFile("occ", root.path / "01.mp3", root, None, "mp3", "id")
    with pytest.raises(ImportContractError):
        ImportedFile("occ", OTHER_ROOT / "01.mp3", direct_root(),
                     PurePath("01.mp3"), "mp3", "id")


@pytest.mark.parametrize("blank_field", ["occurrence_id", "supported_type_id", "identity"])
def test_an_imported_file_refuses_a_blank_identifier(blank_field):
    root = folder_root()
    kwargs = dict(
        occurrence_id="occ", path=root.path / "01.mp3", source_root=root,
        relative_path=PurePath("01.mp3"), supported_type_id="mp3", identity="id")
    kwargs[blank_field] = "   "
    with pytest.raises(ImportContractError):
        ImportedFile(**kwargs)


def test_a_relative_path_may_be_given_as_a_string():
    entry = ImportedFile("occ", ROOT_PATH / "a" / "b.mp3", folder_root(), "a/b.mp3", "mp3", "id")
    assert entry.relative_path == PurePath("a/b.mp3")


# --------------------------------------------------------------------------- #
# Occurrence identity vs source identity
# --------------------------------------------------------------------------- #


def test_two_occurrences_of_one_source_stay_visibly_the_same_source():
    """Decision 35A: a deliberate duplicate is never disguised as a different file."""
    first = imported("occ-1", identity="same-source")
    second = imported("occ-2", identity="same-source")
    assert first != second, "they are distinct occurrences"
    assert first.identity == second.identity, "but the same source"
    assert first.path == second.path


def test_value_equality_and_hashing_hold_for_the_plain_values():
    assert imported() == imported()
    assert hash(imported()) == hash(imported())
    assert len({imported(), imported()}) == 1
    assert SupportedType("a", "A", (".x",)) == SupportedType("a", "A", ("X",))
    assert ImportRoot("r", ROOT_PATH, 0) == ImportRoot("r", ROOT_PATH, 0)
    assert ImportRoot("r", ROOT_PATH, 0) != ImportRoot("r", ROOT_PATH, 1)


@pytest.mark.parametrize(
    "value",
    [
        SupportedType("a", "A", (".x",)),
        ImportRoot("r", ROOT_PATH, 0),
        ImportOptions(),
        Revision(1),
        ImportedFileSnapshot(),
    ],
)
def test_every_plain_value_is_frozen_and_slotted(value):
    with pytest.raises(FrozenInstanceError):
        setattr(value, next(iter(type(value).__dataclass_fields__)), None)
    assert not hasattr(value, "__dict__"), "slots keep an accidental attribute impossible"


# --------------------------------------------------------------------------- #
# Problems
# --------------------------------------------------------------------------- #


def test_a_problem_separates_the_sentence_from_the_diagnostics():
    problem = ImportProblem(
        ProblemCategory.UNREADABLE,
        "One folder could not be read and was skipped.",
        technical_detail="PermissionError: [WinError 5] Access is denied: 'C:\\\\x'",
        path=ROOT_PATH / "x",
    )
    assert "\n" not in problem.display_message
    assert "WinError" in problem.technical_detail


def test_every_refusal_category_exists():
    assert {category.value for category in ProblemCategory} == {
        "unsupported_type", "duplicate", "hidden", "link", "unreadable",
        "vanished", "wrong_type", "cancelled", "invalid_root",
    }


def test_a_problem_refuses_a_multiline_or_traceback_message():
    with pytest.raises(ImportContractError):
        ImportProblem(ProblemCategory.LINK, "refused\nbecause")
    with pytest.raises(ImportContractError):
        ImportProblem(ProblemCategory.LINK, "Traceback (most recent call last): x")
    with pytest.raises(ImportContractError):
        ImportProblem("link", "refused")


# --------------------------------------------------------------------------- #
# Snapshots
# --------------------------------------------------------------------------- #


def test_a_snapshot_carries_its_order_ids_and_revision():
    snapshot = ImportedFileSnapshot(Revision(4), (imported("occ-1"), imported("occ-2")))
    assert snapshot.count == 2
    assert snapshot.occurrence_ids == ("occ-1", "occ-2")
    assert snapshot.revision == Revision(4)
    assert snapshot.is_empty is False


def test_an_empty_snapshot_is_the_starting_state():
    snapshot = ImportedFileSnapshot()
    assert snapshot.is_empty and snapshot.count == 0
    assert snapshot.revision == INITIAL_REVISION


def test_a_snapshot_refuses_a_repeated_occurrence_id():
    with pytest.raises(ImportContractError):
        ImportedFileSnapshot(INITIAL_REVISION, (imported("occ-1"), imported("occ-1")))


def test_a_snapshot_copies_the_sequence_it_was_given():
    live = [imported("occ-1")]
    snapshot = ImportedFileSnapshot(INITIAL_REVISION, live)
    live.append(imported("occ-2"))
    assert snapshot.count == 1


# --------------------------------------------------------------------------- #
# Scan request
# --------------------------------------------------------------------------- #


def test_a_request_captures_the_threshold_so_it_cannot_move_mid_scan():
    request = ScanRequest("req", (folder_root(),), catalog(),
                          ImportOptions.for_catalog(catalog()), make_config(2500), 12.0)
    assert request.large_result_warning_threshold == 2500


def test_a_request_keeps_the_users_root_order_and_separates_the_two_kinds():
    request = ScanRequest(
        "req",
        (folder_root(0, ROOT_PATH, "a"), folder_root(1, OTHER_ROOT, "b"), direct_root(2)),
        catalog(), ImportOptions.for_catalog(catalog()), make_config())
    assert [root.root_id for root in request.roots] == ["a", "b", "direct-1"]
    assert [root.root_id for root in request.folder_roots] == ["a", "b"]
    assert [root.root_id for root in request.direct_roots] == ["direct-1"]


def test_roots_out_of_order_are_refused_rather_than_silently_sorted():
    with pytest.raises(ImportContractError):
        ScanRequest("req", (folder_root(1, ROOT_PATH, "a"), folder_root(0, OTHER_ROOT, "b")),
                    catalog(), ImportOptions.for_catalog(catalog()), make_config())


def test_a_request_refuses_duplicate_roots_orders_and_an_empty_list():
    with pytest.raises(ImportContractError):
        ScanRequest("req", (), catalog(), ImportOptions(), make_config())
    with pytest.raises(ImportContractError):
        ScanRequest("req", (folder_root(0, ROOT_PATH, "a"), folder_root(1, OTHER_ROOT, "a")),
                    catalog(), ImportOptions(), make_config())
    with pytest.raises(ImportContractError):
        ScanRequest("req", (folder_root(0, ROOT_PATH, "a"), folder_root(0, OTHER_ROOT, "b")),
                    catalog(), ImportOptions(), make_config())


def test_a_request_refuses_a_selection_the_catalog_does_not_know():
    with pytest.raises(ImportContractError):
        ScanRequest("req", (folder_root(),), catalog(),
                    ImportOptions(selected_type_ids={"epub"}), make_config())


def test_a_request_refuses_anything_that_is_not_a_captured_config():
    for bad in ({"importing": {"large_result_warning_threshold": 10}}, None, config, 1000):
        with pytest.raises(ImportContractError):
            ScanRequest("req", (folder_root(),), catalog(), ImportOptions(), bad)


@pytest.mark.parametrize("stamp", [-1.0, float("nan"), float("inf"), "12", True])
def test_a_request_refuses_an_unusable_timestamp(stamp):
    with pytest.raises(ImportContractError):
        ScanRequest("req", (folder_root(),), catalog(), ImportOptions(), make_config(), stamp)


# --------------------------------------------------------------------------- #
# Scan result
# --------------------------------------------------------------------------- #


def test_only_a_completed_scan_may_be_committed():
    completed = ScanResult("req", ScanOutcome.COMPLETED, 2, (imported(),))
    assert completed.is_committable and completed.candidate_count == 1


@pytest.mark.parametrize("outcome", [ScanOutcome.CANCELLED, ScanOutcome.FAILED])
def test_a_scan_that_did_not_complete_can_carry_no_files_at_all(outcome):
    """Structural, not remembered: there is nothing in the value to commit."""
    with pytest.raises(ImportContractError):
        ScanResult("req", outcome, 5, (imported(),),
                   (ImportProblem(ProblemCategory.CANCELLED, "Import cancelled."),))


def test_a_cancelled_scan_still_reports_what_it_had_discovered():
    result = ScanResult("req", ScanOutcome.CANCELLED, 41, (),
                        (ImportProblem(ProblemCategory.CANCELLED, "Import cancelled."),))
    assert result.discovered_count == 41
    assert result.is_committable is False


def test_a_failed_scan_must_say_why():
    with pytest.raises(ImportContractError):
        ScanResult("req", ScanOutcome.FAILED, 0)


def test_problem_counts_are_derived_and_read_only():
    result = ScanResult(
        "req", ScanOutcome.COMPLETED, 3, (),
        (
            ImportProblem(ProblemCategory.HIDDEN, "One hidden folder was skipped."),
            ImportProblem(ProblemCategory.LINK, "One shortcut was not followed."),
            ImportProblem(ProblemCategory.LINK, "Another shortcut was not followed."),
        ),
    )
    counts = result.problem_counts()
    assert counts[ProblemCategory.LINK] == 2
    assert counts[ProblemCategory.HIDDEN] == 1
    assert len(result.problems_of(ProblemCategory.LINK)) == 2
    with pytest.raises(TypeError):
        counts[ProblemCategory.DUPLICATE] = 9


def test_a_result_refuses_a_repeated_occurrence_id():
    with pytest.raises(ImportContractError):
        ScanResult("req", ScanOutcome.COMPLETED, 2, (imported("occ"), imported("occ")))


# --------------------------------------------------------------------------- #
# No side effects
# --------------------------------------------------------------------------- #


def test_building_the_whole_vocabulary_starts_no_thread_and_writes_nothing(tmp_path):
    threads_before = threading.active_count()
    entries_before = sorted(os.listdir(tmp_path))

    book = catalog()
    root = ImportRoot("r", tmp_path, 0)
    files = (
        ImportedFile("o1", tmp_path / "a.mp3", root, "a.mp3", "mp3", "i1"),
        ImportedFile("o2", tmp_path / "b" / "c.m4b", root, "b/c.m4b", "m4b", "i2"),
    )
    snapshot = ImportedFileSnapshot(INITIAL_REVISION.advance(), files)
    request = ScanRequest("req", (root,), book, ImportOptions.for_catalog(book), make_config(), 1.0)
    ScanResult(request.request_id, ScanOutcome.COMPLETED, 2, files, (), 2.0)

    assert snapshot.count == 2
    assert threading.active_count() == threads_before
    assert sorted(os.listdir(tmp_path)) == entries_before
    assert not (tmp_path / "a.mp3").exists()
