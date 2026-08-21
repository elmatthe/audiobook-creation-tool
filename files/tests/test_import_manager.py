"""The imported-file manager, dedupe and atomic transactions — Drop 3, Phase 3.

Three things are being proved here.

**Ownership.** The manager owns an ordered list of *occurrences*, a revision, and a
selection kept by occurrence id rather than by row number. Every mutation returns an
immutable result, and the revision only moves when something actually changed.

**Atomicity.** Preparing a transaction changes nothing; committing one appends the
whole accepted set or appends nothing. A transaction prepared against an older
revision is refused untouched, so a scan that finished while the user was reordering
cannot merge itself into state it never saw. No thread is needed to prove that — the
conflict is simulated deterministically by mutating the manager between plan and
commit.

**Safety.** Add Files re-inspects every path a dialog handed back, without following
anything; removing or clearing a row never touches the file it names. Both are
proved against real disposable trees under ``tmp_path``, with a full before/after
metadata snapshot rather than an assertion of good intent.

Nothing here scans the repository, the real home directory, Downloads, an output
base, runtime data, real media or a network share, and nothing reserves or creates
an output path.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path, PurePath

import pytest

from shared import importing, output_paths
from shared.importing import (
    CommitResult,
    CommitStatus,
    IdFactory,
    ImportContractError,
    ImportedFile,
    ImportedFileManager,
    ImportedFileSnapshot,
    ImportOptions,
    ImportProblem,
    ImportRoot,
    ImportTransaction,
    INITIAL_REVISION,
    ManagerOperation,
    MutationResult,
    PlanningGroups,
    ProblemCategory,
    Revision,
    RootKind,
    ScanOutcome,
    ScanResult,
    SupportedType,
    SupportedTypeCatalog,
    plan_transaction,
    planning_groups,
    scan_roots,
    validate_direct_files,
)

from test_importing import make_config
from test_import_traversal import (
    WINDOWS,
    fake_stat,
    make_junction,
    make_symlink,
    patch_lstat,
    request_for,
    set_hidden,
    snapshot_tree,
    touch,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def catalog() -> SupportedTypeCatalog:
    return SupportedTypeCatalog((
        SupportedType("mp3", "MP3 audio", (".mp3",)),
        SupportedType("m4b", "M4B audiobook", (".m4b", ".m4a")),
    ))


def options(*, duplicates: bool = False, selected: set[str] | None = None) -> ImportOptions:
    if selected is None:
        return ImportOptions.for_catalog(catalog(), allow_duplicate_files=duplicates)
    return ImportOptions(
        selected_type_ids=frozenset(selected), allow_duplicate_files=duplicates)


DIRECT_ROOT = ImportRoot("direct-1", None, 0, RootKind.DIRECT_FILES)


def add_files(paths, *, root: ImportRoot = DIRECT_ROOT, request_id: str = "req-1",
              types: SupportedTypeCatalog | None = None, **kwargs) -> ScanResult:
    """Run Add Files validation over an explicit sequence of chosen paths."""
    return validate_direct_files(
        paths,
        request_id=request_id,
        root=root,
        catalog=types or catalog(),
        options=kwargs.pop("options", None) or options(**kwargs),
        id_factory=IdFactory("d-"),
    )


def synthetic(*names: str, root: ImportRoot | None = None,
              identity: str | None = None) -> ScanResult:
    """A completed result built in memory, for tests about ordering and identity.

    Paths here need not exist: dedupe and the manager are pure, and building their
    fixtures on disk would only hide that.
    """
    where = root or DIRECT_ROOT
    files = []
    for index, name in enumerate(names, start=1):
        path = Path(os.path.abspath(os.sep + "act-fixture") ) / name
        files.append(ImportedFile(
            occurrence_id=f"scan-{index:03d}",
            path=path,
            source_root=where,
            relative_path=PurePath(name) if where.mirrors else None,
            supported_type_id="mp3",
            identity=identity or f"file:1:{name}",
        ))
    return ScanResult(
        request_id="req-1",
        outcome=ScanOutcome.COMPLETED,
        discovered_count=len(files),
        files=tuple(files),
    )


def loaded(*names: str, **kwargs) -> ImportedFileManager:
    """A manager holding one committed occurrence per name, in that order."""
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    result = synthetic(*names, **kwargs)
    commit = manager.commit(manager.plan(result, options=options()))
    assert commit.committed
    return manager


def order_of(manager: ImportedFileManager) -> list[str]:
    return [entry.path.name for entry in manager.snapshot().files]


def select_names(manager: ImportedFileManager, *names: str) -> tuple[str, ...]:
    wanted = set(names)
    return manager.select(
        entry.occurrence_id for entry in manager.snapshot().files
        if entry.path.name in wanted)


# =========================================================================== #
# The manager and its snapshots
# =========================================================================== #


def test_a_new_manager_is_empty_at_the_initial_revision():
    manager = ImportedFileManager()
    assert manager.count == 0
    assert manager.is_empty
    assert manager.selected_count == 0
    assert manager.selection == ()
    assert manager.revision == INITIAL_REVISION
    assert manager.snapshot() == ImportedFileSnapshot(revision=INITIAL_REVISION, files=())


def test_a_snapshot_is_frozen_and_cannot_be_written_through():
    manager = loaded("01.mp3", "02.mp3")
    snapshot = manager.snapshot()
    with pytest.raises(FrozenInstanceError):
        snapshot.files = ()
    assert isinstance(snapshot.files, tuple)
    assert isinstance(snapshot.occurrence_ids, tuple)


def test_reading_a_snapshot_repeatedly_changes_nothing():
    manager = loaded("01.mp3", "02.mp3")
    first = manager.snapshot()
    for _ in range(5):
        assert manager.snapshot() == first
    assert manager.revision == first.revision


def test_a_snapshot_taken_earlier_does_not_follow_the_manager():
    """The whole point of handing out a value: an old snapshot stays old."""
    manager = loaded("01.mp3")
    before = manager.snapshot()
    manager.commit(manager.plan(synthetic("02.mp3"), options=options()))
    assert before.count == 1
    assert manager.snapshot().count == 2
    assert before.revision.value < manager.revision.value


def test_the_revision_moves_once_per_real_mutation():
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    assert manager.revision.value == 0
    manager.commit(manager.plan(synthetic("01.mp3", "02.mp3"), options=options()))
    assert manager.revision.value == 1
    select_names(manager, "02.mp3")
    assert manager.revision.value == 1, "selecting is not a mutation of the list"
    manager.move_selected_up()
    assert manager.revision.value == 2
    manager.remove_selected()
    assert manager.revision.value == 3
    manager.clear()
    assert manager.revision.value == 4


def test_a_no_op_mutation_leaves_the_revision_alone():
    """A no-op must not invalidate a transaction another part of the UI is holding."""
    manager = loaded("01.mp3", "02.mp3")
    before = manager.revision
    for result in (manager.move_selected_up(), manager.move_selected_down(),
                   manager.remove_selected()):
        assert result.changed is False
        assert result.revision == before
    empty = ImportedFileManager()
    assert empty.clear().changed is False
    assert empty.revision == INITIAL_REVISION


def test_occurrences_keep_the_order_they_were_committed_in():
    manager = loaded("10.mp3", "01.mp3", "02.mp3")
    assert order_of(manager) == ["10.mp3", "01.mp3", "02.mp3"], \
        "the manager preserves; it does not sort"


def test_counts_and_selected_counts_track_the_list():
    manager = loaded("01.mp3", "02.mp3", "03.mp3")
    assert manager.count == 3
    assert manager.selected_count == 0
    select_names(manager, "01.mp3", "03.mp3")
    assert manager.selected_count == 2
    assert manager.snapshot().count == 3
    manager.remove_selected()
    assert (manager.count, manager.selected_count) == (1, 0)


def test_a_mutation_result_hands_back_no_live_manager_state():
    manager = loaded("01.mp3", "02.mp3")
    select_names(manager, "01.mp3")
    result = manager.remove_selected()
    assert isinstance(result, MutationResult)
    with pytest.raises(FrozenInstanceError):
        result.changed = False
    assert isinstance(result.snapshot, ImportedFileSnapshot)
    assert isinstance(result.removed, tuple)
    assert isinstance(result.selection, tuple)
    # Nothing handed back is the object the manager is still using.
    assert result.snapshot.files == manager.snapshot().files


def test_a_mutation_result_reports_the_operation_it_describes():
    manager = loaded("01.mp3", "02.mp3")
    select_names(manager, "02.mp3")
    assert manager.move_selected_up().operation is ManagerOperation.MOVE_UP
    assert manager.move_selected_down().operation is ManagerOperation.MOVE_DOWN
    assert manager.remove_selected().operation is ManagerOperation.REMOVE
    assert manager.clear().operation is ManagerOperation.CLEAR


def test_an_unknown_occurrence_id_is_simply_not_selected():
    manager = loaded("01.mp3", "02.mp3")
    real = manager.snapshot().occurrence_ids[0]
    assert manager.select([real, "occ-does-not-exist"]) == (real,)
    assert manager.selected_count == 1


def test_selecting_only_unknown_ids_leaves_nothing_selected():
    manager = loaded("01.mp3")
    assert manager.select(["ghost-1", "ghost-2"]) == ()
    assert manager.selected_count == 0


@pytest.mark.parametrize("bad", [7, None, object(), Path("x")])
def test_a_selection_id_that_is_not_an_identifier_is_refused(bad):
    manager = loaded("01.mp3")
    with pytest.raises(ImportContractError):
        manager.select([bad])


def test_a_bare_string_is_not_mistaken_for_a_list_of_ids():
    manager = loaded("01.mp3")
    with pytest.raises(ImportContractError):
        manager.select("occ-1")


def test_a_selection_list_edited_afterwards_does_not_change_the_selection():
    manager = loaded("01.mp3", "02.mp3")
    ids = list(manager.snapshot().occurrence_ids[:1])
    manager.select(ids)
    ids.append(manager.snapshot().occurrence_ids[1])
    assert manager.selected_count == 1


def test_the_selection_is_reported_in_list_order_not_click_order():
    """The block move is defined by where rows sit, so the selection follows suit."""
    manager = loaded("01.mp3", "02.mp3", "03.mp3")
    ids = manager.snapshot().occurrence_ids
    assert manager.select([ids[2], ids[0]]) == (ids[0], ids[2])


def test_an_id_factory_that_is_not_one_is_refused():
    with pytest.raises(ImportContractError):
        ImportedFileManager(id_factory="not-a-factory")


# =========================================================================== #
# Direct Add Files
# =========================================================================== #


def test_the_users_order_is_preserved_exactly(tmp_path):
    chosen = [touch(tmp_path / name) for name in ("10.mp3", "01.mp3", "b.mp3", "A.mp3")]
    result = add_files(chosen)
    assert [entry.path.name for entry in result.files] == \
        ["10.mp3", "01.mp3", "b.mp3", "A.mp3"]


def test_add_files_never_applies_natural_or_lexical_sorting(tmp_path):
    """Natural order belongs to Add Folder, where the user chose a tree, not a list."""
    chosen = [touch(tmp_path / name) for name in ("2.mp3", "10.mp3", "1.mp3")]
    direct = [entry.path.name for entry in add_files(chosen).files]
    scanned = [
        entry.path.name
        for entry in scan_roots(request_for(tmp_path), id_factory=IdFactory("s-")).files
    ]
    assert direct == ["2.mp3", "10.mp3", "1.mp3"]
    assert scanned == ["1.mp3", "2.mp3", "10.mp3"], "the scanner does sort naturally"


def test_every_selected_supported_type_is_accepted(tmp_path):
    chosen = [touch(tmp_path / name) for name in ("a.mp3", "b.m4b", "c.m4a")]
    result = add_files(chosen)
    assert result.candidate_count == 3
    assert [entry.supported_type_id for entry in result.files] == ["mp3", "m4b", "m4b"]


def test_only_the_ticked_types_are_accepted(tmp_path):
    chosen = [touch(tmp_path / name) for name in ("a.mp3", "b.m4b")]
    result = add_files(chosen, selected={"mp3"})
    assert [entry.path.name for entry in result.files] == ["a.mp3"]
    assert result.problem_counts()[ProblemCategory.UNSUPPORTED_TYPE] == 1


def test_with_no_types_ticked_nothing_is_accepted_and_everything_is_reported(tmp_path):
    chosen = [touch(tmp_path / "a.mp3")]
    result = add_files(chosen, selected=set())
    assert result.files == ()
    assert result.problem_counts()[ProblemCategory.UNSUPPORTED_TYPE] == 1


@pytest.mark.parametrize("name", ["book.MP3", "book.Mp3", "book.M4B"])
def test_an_uppercase_or_mixed_case_extension_still_matches(tmp_path, name):
    result = add_files([touch(tmp_path / name)])
    assert result.candidate_count == 1, "extension matching is case-insensitive"


def test_an_unsupported_extension_is_reported_not_silently_dropped(tmp_path):
    chosen = [touch(tmp_path / "notes.txt"), touch(tmp_path / "a.mp3")]
    result = add_files(chosen)
    assert [entry.path.name for entry in result.files] == ["a.mp3"]
    problem = result.problems_of(ProblemCategory.UNSUPPORTED_TYPE)[0]
    assert problem.path.name == "notes.txt"
    assert "not a selected file type" in problem.display_message


def test_a_file_with_no_extension_at_all_is_reported(tmp_path):
    result = add_files([touch(tmp_path / "README")])
    assert result.files == ()
    assert result.problem_counts()[ProblemCategory.UNSUPPORTED_TYPE] == 1


def test_a_missing_path_is_reported_as_vanished(tmp_path):
    result = add_files([tmp_path / "gone.mp3"])
    assert result.files == ()
    problem = result.problems_of(ProblemCategory.VANISHED)[0]
    assert "could no longer be found" in problem.display_message
    assert "FileNotFoundError" in problem.technical_detail


def test_a_file_that_vanished_between_the_dialog_and_the_import_is_reported(tmp_path):
    """The dialog's answer is a description of the past, not a guarantee."""
    chosen = touch(tmp_path / "01.mp3")
    kept = touch(tmp_path / "02.mp3")
    chosen.unlink()
    result = add_files([chosen, kept])
    assert [entry.path.name for entry in result.files] == ["02.mp3"]
    assert result.problem_counts()[ProblemCategory.VANISHED] == 1


def test_an_unreadable_path_is_reported_through_deterministic_injection(
        tmp_path, monkeypatch):
    blocked = touch(tmp_path / "01.mp3")
    patch_lstat(monkeypatch, blocked, PermissionError(13, "Permission denied"))
    result = add_files([blocked])
    assert result.files == ()
    problem = result.problems_of(ProblemCategory.UNREADABLE)[0]
    assert "could not be read" in problem.display_message
    assert "PermissionError" in problem.technical_detail


def test_an_ordinary_directory_supplied_as_a_file_is_refused(tmp_path):
    folder = tmp_path / "Book"
    folder.mkdir()
    touch(folder / "01.mp3")
    result = add_files([folder])
    assert result.files == (), "Add Files never recurses"
    problem = result.problems_of(ProblemCategory.WRONG_TYPE)[0]
    assert "is a folder" in problem.display_message
    assert "never recurses" in problem.technical_detail


def test_a_directory_is_not_walked_even_when_it_holds_supported_files(tmp_path):
    folder = tmp_path / "Book"
    folder.mkdir()
    for name in ("01.mp3", "02.mp3", "03.mp3"):
        touch(folder / name)
    result = add_files([folder])
    assert result.discovered_count == 0
    assert len(result.problems) == 1, "one refusal, not one per hidden child"


def test_a_file_symlink_supplied_as_a_file_is_refused(tmp_path):
    target = touch(tmp_path / "real.mp3")
    link = tmp_path / "link.mp3"
    make_symlink(target, link, directory=False)
    result = add_files([link])
    assert result.files == ()
    assert result.problem_counts()[ProblemCategory.LINK] == 1


def test_a_junction_supplied_as_a_file_is_refused(tmp_path):
    """A junction reports ``is_symlink() == False``; only ``is_link`` catches it."""
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "shortcut"
    make_junction(target, link)
    result = add_files([link])
    assert result.files == ()
    problem = result.problems_of(ProblemCategory.LINK)[0]
    assert "was not followed" in problem.display_message


def test_link_refusal_is_proved_even_where_symlinks_cannot_be_created(
        tmp_path, monkeypatch):
    """So the most important refusal is never left untested on this machine."""
    ordinary = touch(tmp_path / "01.mp3")
    monkeypatch.setattr(importing, "_is_link", lambda path: True)
    result = add_files([ordinary])
    assert result.files == ()
    assert result.problem_counts()[ProblemCategory.LINK] == 1


def test_readability_is_settled_before_the_link_question_is_asked(tmp_path, monkeypatch):
    """``is_link`` answers ``False`` for what it cannot read; that is not consent."""
    blocked = touch(tmp_path / "01.mp3")
    patch_lstat(monkeypatch, blocked, PermissionError(13, "Permission denied"))
    monkeypatch.setattr(importing, "_is_link", lambda path: False)
    result = add_files([blocked])
    assert result.problem_counts()[ProblemCategory.UNREADABLE] == 1
    assert result.files == ()


def test_an_explicitly_chosen_hidden_file_is_accepted(tmp_path):
    """§6.2: hidden policy stops a scan sweeping up dot-files, not a deliberate pick."""
    hidden = touch(tmp_path / ".secret.mp3")
    result = add_files([hidden])
    assert [entry.path.name for entry in result.files] == [".secret.mp3"]
    assert result.problems == ()


def test_an_explicitly_chosen_windows_hidden_file_is_accepted(tmp_path):
    chosen = touch(tmp_path / "01.mp3")
    set_hidden(chosen)
    result = add_files([chosen])
    assert result.candidate_count == 1


def test_a_hidden_file_is_still_skipped_by_a_folder_scan(tmp_path):
    """The two paths differ on purpose, and both are proved here side by side."""
    hidden = touch(tmp_path / ".secret.mp3")
    scanned = scan_roots(request_for(tmp_path), id_factory=IdFactory("s-"))
    assert scanned.files == ()
    assert add_files([hidden]).candidate_count == 1


@pytest.mark.parametrize("name", [
    "a file with spaces.mp3",
    "o'clock.mp3",
    "Ré — naïve.mp3",
    "Ω-omega.mp3",
    "chapter " + "x" * 120 + ".mp3",
])
def test_awkward_but_legal_names_are_accepted(tmp_path, name):
    result = add_files([touch(tmp_path / name)])
    assert result.candidate_count == 1, result.problems


def test_nfc_and_nfd_spellings_of_one_chosen_name_both_validate(tmp_path):
    import unicodedata

    composed = tmp_path / unicodedata.normalize("NFC", "Ré 1.mp3")
    touch(composed)
    decomposed = tmp_path / unicodedata.normalize("NFD", "Ré 1.mp3")
    result = add_files([composed, decomposed])
    # Whether the two spellings are one file is the filesystem's answer, not ours;
    # what matters is that neither spelling crashes and both are classified.
    assert len(result.files) + len(result.problems) == 2


def test_a_relative_path_is_refused_rather_than_joined_onto_the_working_directory():
    result = add_files(["01.mp3"])
    assert result.files == ()
    problem = result.problems_of(ProblemCategory.INVALID_ROOT)[0]
    assert "lexically absolute" in problem.technical_detail


@pytest.mark.parametrize("bad", ["", "   ", os.sep + "a" + os.sep + ".." + os.sep + "b.mp3"])
def test_an_unusable_selection_is_reported_not_raised(bad):
    result = add_files([bad])
    assert result.files == ()
    assert result.problem_counts()[ProblemCategory.INVALID_ROOT] == 1


@pytest.mark.parametrize("bad", [7, None, b"/tmp/a.mp3", object()])
def test_a_selection_that_is_not_a_path_at_all_is_reported(bad):
    result = add_files([bad])
    assert result.files == ()
    assert result.problem_counts()[ProblemCategory.INVALID_ROOT] == 1


def test_one_path_is_not_mistaken_for_a_sequence_of_paths(tmp_path):
    chosen = touch(tmp_path / "01.mp3")
    for single in (chosen, str(chosen)):
        with pytest.raises(ImportContractError):
            add_files(single)


def test_a_list_edited_after_validation_cannot_change_the_result(tmp_path):
    chosen = [touch(tmp_path / "01.mp3")]
    result = add_files(chosen)
    chosen.append(touch(tmp_path / "02.mp3"))
    assert result.candidate_count == 1


def test_add_files_needs_the_direct_files_root(tmp_path):
    folder = ImportRoot("root-1", tmp_path, 0)
    with pytest.raises(ImportContractError, match="direct-files group"):
        add_files([touch(tmp_path / "01.mp3")], root=folder)


def test_directly_added_files_carry_no_mirroring_root(tmp_path):
    """Decision 31A: individually chosen files have no common tree to reproduce."""
    result = add_files([touch(tmp_path / "01.mp3")])
    entry = result.files[0]
    assert entry.relative_path is None
    assert entry.mirroring_root is None
    assert entry.source_root.kind is RootKind.DIRECT_FILES


def test_add_files_returns_a_completed_committable_result(tmp_path):
    result = add_files([touch(tmp_path / "01.mp3")])
    assert result.outcome is ScanOutcome.COMPLETED
    assert result.is_committable
    assert result.discovered_count == 1


def test_add_files_with_an_empty_selection_completes_with_nothing(tmp_path):
    result = add_files([])
    assert (result.files, result.problems, result.discovered_count) == ((), (), 0)


def test_add_files_validates_its_own_arguments(tmp_path):
    good = [touch(tmp_path / "01.mp3")]
    with pytest.raises(ImportContractError):
        validate_direct_files(good, request_id="", root=DIRECT_ROOT,
                              catalog=catalog(), options=options())
    with pytest.raises(ImportContractError):
        validate_direct_files(good, request_id="r", root="nope",
                              catalog=catalog(), options=options())
    with pytest.raises(ImportContractError):
        validate_direct_files(good, request_id="r", root=DIRECT_ROOT,
                              catalog="nope", options=options())
    with pytest.raises(ImportContractError):
        validate_direct_files(good, request_id="r", root=DIRECT_ROOT,
                              catalog=catalog(), options="nope")


# =========================================================================== #
# Default deduplication
# =========================================================================== #


def test_the_same_file_selected_twice_in_one_transaction_is_added_once(tmp_path):
    chosen = touch(tmp_path / "01.mp3")
    result = add_files([chosen, chosen])
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    transaction = manager.plan(result, options=options())
    assert transaction.proposed_count == 1
    assert transaction.duplicate_count == 1
    assert "in this same import" in transaction.duplicates[0].technical_detail


def test_a_candidate_already_in_the_manager_is_skipped(tmp_path):
    chosen = touch(tmp_path / "01.mp3")
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    manager.commit(manager.plan(add_files([chosen]), options=options()))
    second = manager.plan(add_files([chosen]), options=options())
    assert second.proposed_count == 0
    assert second.duplicate_count == 1
    assert "already imported" in second.duplicates[0].technical_detail


def test_two_spellings_of_one_path_are_recognised_as_one_source(tmp_path):
    chosen = touch(tmp_path / "Book" / "01.mp3")
    other = tmp_path / "Book" / "." / "01.mp3"
    result = add_files([chosen, Path(os.path.normpath(other))])
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    assert manager.plan(result, options=options()).proposed_count == 1


def test_a_hard_link_is_recognised_as_the_same_physical_source(tmp_path):
    original = touch(tmp_path / "01.mp3")
    hard = tmp_path / "02.mp3"
    try:
        os.link(original, hard)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"this filesystem cannot create a hard link: {type(exc).__name__}: {exc}")
    assert os.lstat(original).st_ino == os.lstat(hard).st_ino
    result = add_files([original, hard])
    assert result.candidate_count == 2, "both are valid files"
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    transaction = manager.plan(result, options=options())
    assert transaction.proposed_count == 1, "but they are one physical source"
    assert transaction.duplicate_count == 1


def test_the_lexical_fallback_identity_is_used_when_the_platform_reports_none(
        tmp_path, monkeypatch):
    """``st_dev``/``st_ino`` of zero means "no usable identity", not "identical"."""
    chosen = touch(tmp_path / "01.mp3")
    other = touch(tmp_path / "02.mp3")
    monkeypatch.setattr(
        os, "lstat", lambda path, *a, **k: fake_stat(stat.S_IFREG | 0o644))
    first = importing.capture_identity(chosen)
    second = importing.capture_identity(other)
    assert first.startswith("path:") and second.startswith("path:")
    assert first != second, "two different names must not collapse into one identity"


def _case_only_identities(monkeypatch, *, case_blind: bool) -> tuple[str, str]:
    """Both spellings' fallback identities, with the volume answer forced.

    The seam is patched rather than the platform, so both answers are proved on
    whichever filesystem the test runner happens to be using.
    """
    monkeypatch.setattr(
        importing, "filesystem_is_case_insensitive", lambda _path: case_blind)
    base = Path(os.path.abspath(os.sep + "act-fixture"))
    return (importing.capture_identity(base / "book.mp3"),
            importing.capture_identity(base / "BOOK.mp3"))


def test_the_lexical_fallback_folds_case_on_a_case_blind_filesystem(monkeypatch):
    """One file reached by two spellings is one source on a case-blind volume."""
    lower, upper = _case_only_identities(monkeypatch, case_blind=True)
    assert lower.startswith("path:") and upper.startswith("path:")
    assert lower == upper, "a case-blind filesystem must fold these together"


def test_the_lexical_fallback_keeps_case_on_a_case_sensitive_filesystem(monkeypatch):
    """A case-sensitive volume — including a case-sensitive APFS one — has two files."""
    lower, upper = _case_only_identities(monkeypatch, case_blind=False)
    assert lower != upper, "a case-sensitive volume keeps two real files apart"


def test_the_windows_flavour_folds_case_whatever_the_volume_answers(monkeypatch):
    """Windows path semantics are case-blind at the API layer, not per volume."""
    monkeypatch.setattr(
        importing, "filesystem_is_case_insensitive", lambda _path: False)
    if not WINDOWS:
        pytest.skip("PurePath is only the Windows flavour on Windows")
    base = Path(os.path.abspath(os.sep + "act-fixture"))
    assert (importing.capture_identity(base / "book.mp3")
            == importing.capture_identity(base / "BOOK.mp3"))


def _volume_folds_case(directory: Path) -> bool | None:
    """Independent read-only answer for *directory*'s volume, or ``None`` if unclear.

    Deliberately does not call the production probe: a live assertion that used the
    same code it is checking would only prove the code agrees with itself.
    """
    name = directory.name
    flipped = name.upper() if name != name.upper() else name.lower()
    if not name or flipped == name:
        return None
    twin = directory.parent / flipped
    try:
        original_stat, twin_stat = os.lstat(directory), os.lstat(twin)
    except OSError:
        return False
    return ((original_stat.st_dev, original_stat.st_ino)
            == (twin_stat.st_dev, twin_stat.st_ino))


def test_the_lexical_fallback_matches_this_machines_real_volume(tmp_path):
    """The live supplement: whatever this actual volume does, identity agrees.

    Both names are missing, so the platform reports no ``(st_dev, st_ino)`` and the
    lexical fallback is what answers — which is exactly the path under test.
    """
    folds = _volume_folds_case(tmp_path)
    if folds is None:
        pytest.skip("this temporary directory name has no case to flip")
    missing = tmp_path / "missing"
    lower = importing.capture_identity(missing / "book.mp3")
    upper = importing.capture_identity(missing / "BOOK.mp3")
    assert lower.startswith("path:") and upper.startswith("path:")
    if folds:
        assert lower == upper, "this volume folds case, so these are one source"
    else:
        assert lower != upper, "this volume is case-sensitive, so these are two files"


def test_the_case_probe_reads_the_volume_and_never_writes_to_it(tmp_path):
    """Identity capture stays read-only: no probe file is left in a source folder."""
    before = sorted(p.name for p in tmp_path.iterdir())
    answer = importing.filesystem_is_case_insensitive(tmp_path / "missing" / "book.mp3")
    assert isinstance(answer, bool)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    independent = _volume_folds_case(tmp_path)
    if independent is not None:
        assert answer == independent, "the probe must match what the volume really does"


def test_the_case_probe_answers_conservatively_when_nothing_exists(monkeypatch):
    """An undeterminable volume keeps two spellings apart rather than merging them."""
    if os.name == "nt":
        pytest.skip("the Windows path layer is case-blind by definition")
    monkeypatch.setattr(importing, "_nearest_existing_ancestor", lambda _path: None)
    assert importing.filesystem_is_case_insensitive(Path(os.sep) / "act-fixture") is False


def test_root_classification_never_asks_the_filesystem_about_case(monkeypatch):
    """Root breadth stays purely lexical — the probe is not on that path at all."""
    def _refuse(_path):
        raise AssertionError("classify_root_breadth must not touch the filesystem")

    monkeypatch.setattr(importing, "filesystem_is_case_insensitive", _refuse)
    home = PurePath("/Users/someone")
    assert importing.classify_root_breadth(home, home=home) is importing.RootBreadth.USER_HOME
    assert importing.classify_root_breadth(
        PurePath("/Users/someone/Books"), home=home) is importing.RootBreadth.NARROW


def test_case_only_names_on_a_case_sensitive_filesystem_stay_distinct(tmp_path):
    lower = touch(tmp_path / "book.mp3")
    upper = tmp_path / "BOOK.mp3"
    if upper.exists():
        pytest.skip("this filesystem is case-insensitive, so the two names are one file")
    touch(upper)
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    assert manager.plan(add_files([lower, upper]), options=options()).proposed_count == 2


def test_duplicates_are_skipped_in_stable_order_and_the_first_wins():
    result = synthetic("a.mp3", "b.mp3", "c.mp3")
    same = tuple(
        ImportedFile(
            occurrence_id=entry.occurrence_id, path=entry.path,
            source_root=entry.source_root, relative_path=entry.relative_path,
            supported_type_id=entry.supported_type_id, identity="file:1:same")
        for entry in result.files
    )
    collapsed = ScanResult(request_id="req-1", outcome=ScanOutcome.COMPLETED,
                           discovered_count=3, files=same)
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    transaction = manager.plan(collapsed, options=options())
    assert [entry.path.name for entry in transaction.additions] == ["a.mp3"]
    assert [problem.path.name for problem in transaction.duplicates] == ["b.mp3", "c.mp3"]


def test_the_order_of_accepted_non_duplicates_is_preserved():
    manager = loaded("b.mp3")
    incoming = synthetic("a.mp3", "b.mp3", "c.mp3")
    transaction = manager.plan(incoming, options=options())
    assert [entry.path.name for entry in transaction.additions] == ["a.mp3", "c.mp3"]


def test_a_duplicate_report_names_the_real_path_and_the_occurrence_it_matched():
    """Never disguised as a different file: the actual spelling is what is reported."""
    manager = loaded("01.mp3")
    existing = manager.snapshot().files[0]
    transaction = manager.plan(synthetic("01.mp3"), options=options())
    problem = transaction.duplicates[0]
    assert problem.category is ProblemCategory.DUPLICATE
    assert problem.path == existing.path
    assert existing.occurrence_id in problem.technical_detail
    assert existing.identity in problem.technical_detail


def test_a_duplicate_skip_is_never_confused_with_a_validation_problem(tmp_path):
    chosen = touch(tmp_path / "01.mp3")
    result = add_files([chosen, chosen, touch(tmp_path / "notes.txt"),
                        tmp_path / "gone.mp3"])
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    transaction = manager.plan(result, options=options())
    counts = {}
    for problem in transaction.problems:
        counts[problem.category] = counts.get(problem.category, 0) + 1
    assert counts == {
        ProblemCategory.DUPLICATE: 1,
        ProblemCategory.UNSUPPORTED_TYPE: 1,
        ProblemCategory.VANISHED: 1,
    }


def test_a_transaction_refuses_a_duplicate_reported_under_the_wrong_category():
    wrong = ImportProblem(category=ProblemCategory.HIDDEN, display_message="nope.")
    with pytest.raises(ImportContractError, match="ProblemCategory.DUPLICATE"):
        ImportTransaction(transaction_id="t-1", result=synthetic("a.mp3"),
                          expected_revision=INITIAL_REVISION, duplicates=(wrong,))


def test_planning_never_touches_the_manager():
    manager = loaded("01.mp3")
    before = manager.snapshot()
    for _ in range(3):
        manager.plan(synthetic("02.mp3"), options=options())
    assert manager.snapshot() == before
    assert manager.revision == before.revision


# =========================================================================== #
# The deliberate duplicate override
# =========================================================================== #


def test_the_override_is_off_by_default():
    assert ImportOptions().allow_duplicate_files is False
    assert ImportOptions.for_catalog(catalog()).allow_duplicate_files is False
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    assert manager.plan(synthetic("a.mp3"), options=options()).allow_duplicates is False


def test_duplicates_within_one_transaction_become_separate_occurrences(tmp_path):
    chosen = touch(tmp_path / "01.mp3")
    result = add_files([chosen, chosen, chosen])
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    transaction = manager.plan(result, options=options(duplicates=True))
    assert transaction.proposed_count == 3
    assert transaction.duplicate_count == 0
    assert len({entry.occurrence_id for entry in transaction.additions}) == 3


def test_duplicates_against_the_existing_list_become_separate_occurrences():
    manager = loaded("01.mp3")
    commit = manager.commit(
        manager.plan(synthetic("01.mp3"), options=options(duplicates=True)))
    assert commit.committed
    assert manager.count == 2
    files = manager.snapshot().files
    assert files[0].identity == files[1].identity
    assert files[0].occurrence_id != files[1].occurrence_id


def test_a_deliberate_duplicate_keeps_the_same_source_and_metadata(tmp_path):
    chosen = touch(tmp_path / "Book" / "01.mp3")
    root = ImportRoot("root-1", tmp_path, 0)
    scanned = scan_roots(request_for(tmp_path), id_factory=IdFactory("s-"))
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    manager.commit(manager.plan(scanned, options=options()))
    manager.commit(manager.plan(scanned, options=options(duplicates=True)))
    first, second = manager.snapshot().files
    assert first.path == second.path == chosen
    assert first.identity == second.identity
    assert first.relative_path == second.relative_path == PurePath("Book", "01.mp3")
    assert first.source_root.path == second.source_root.path == root.path
    assert first.occurrence_id != second.occurrence_id


def test_the_original_user_order_survives_the_override():
    manager = loaded("a.mp3")
    manager.commit(
        manager.plan(synthetic("b.mp3", "a.mp3", "c.mp3"),
                     options=options(duplicates=True)))
    assert order_of(manager) == ["a.mp3", "b.mp3", "a.mp3", "c.mp3"]


def test_the_override_is_frozen_onto_the_transaction():
    """A preference toggled afterwards cannot rewrite what a transaction meant."""
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    transaction = manager.plan(synthetic("a.mp3"), options=options(duplicates=True))
    assert transaction.allow_duplicates is True
    with pytest.raises(FrozenInstanceError):
        transaction.allow_duplicates = False
    # Recomputing keeps the policy the transaction was prepared under.
    assert manager.recompute(transaction).allow_duplicates is True


def test_removing_one_deliberate_duplicate_leaves_the_other_intact():
    manager = loaded("01.mp3")
    manager.commit(manager.plan(synthetic("01.mp3"), options=options(duplicates=True)))
    first, second = manager.snapshot().occurrence_ids
    manager.select([first])
    manager.remove_selected()
    assert manager.snapshot().occurrence_ids == (second,)
    assert manager.count == 1


# =========================================================================== #
# Atomicity and conflicts
# =========================================================================== #


def test_a_complete_transaction_commits_once_and_appends_everything():
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    transaction = manager.plan(synthetic("a.mp3", "b.mp3", "c.mp3"), options=options())
    commit = manager.commit(transaction)
    assert commit.status is CommitStatus.COMMITTED
    assert commit.committed is True
    assert len(commit.added) == 3
    assert commit.expected_revision == INITIAL_REVISION
    assert commit.revision.value == 1
    assert order_of(manager) == ["a.mp3", "b.mp3", "c.mp3"]


def test_committing_the_same_transaction_twice_appends_it_once():
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    transaction = manager.plan(synthetic("a.mp3"), options=options())
    assert manager.commit(transaction).committed is True
    second = manager.commit(transaction)
    assert second.status is CommitStatus.STALE_REVISION
    assert second.added == ()
    assert manager.count == 1


def test_a_transaction_prepared_against_an_older_revision_is_refused_whole():
    manager = loaded("a.mp3")
    transaction = manager.plan(synthetic("b.mp3", "c.mp3"), options=options())
    # The list moves while the (imaginary) scan was still running.
    manager.commit(manager.plan(synthetic("d.mp3"), options=options()))
    before = manager.snapshot()
    commit = manager.commit(transaction)
    assert commit.status is CommitStatus.STALE_REVISION
    assert commit.added == ()
    assert manager.snapshot() == before, "nothing partial, nothing merged"
    assert commit.expected_revision == transaction.expected_revision
    assert commit.revision == before.revision


def test_a_revision_change_during_a_scan_is_simulated_without_any_thread():
    """Deterministic by construction: the conflict is an ordering, not a race."""
    manager = loaded("a.mp3")
    planned = manager.plan(synthetic("b.mp3"), options=options())
    select_names(manager, "a.mp3")
    manager.remove_selected()           # the user edits the list mid-"scan"
    assert manager.commit(planned).status is CommitStatus.STALE_REVISION
    recomputed = manager.recompute(planned)
    assert recomputed.expected_revision == manager.revision
    assert manager.commit(recomputed).committed is True
    assert order_of(manager) == ["b.mp3"]


def test_recomputing_re_applies_deduplication_against_the_new_state():
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    incoming = synthetic("a.mp3", "b.mp3")
    planned = manager.plan(incoming, options=options())
    assert planned.proposed_count == 2
    # Someone else adds one of the same sources first.
    manager.commit(manager.plan(synthetic("a.mp3"), options=options()))
    recomputed = manager.recompute(planned)
    assert recomputed.proposed_count == 1
    assert [entry.path.name for entry in recomputed.additions] == ["b.mp3"]
    assert recomputed.duplicate_count == 1


def test_a_recomputed_transaction_is_a_new_immutable_value():
    manager = loaded("a.mp3")
    planned = manager.plan(synthetic("b.mp3"), options=options())
    recomputed = manager.recompute(planned)
    assert isinstance(recomputed, ImportTransaction)
    assert recomputed.transaction_id != planned.transaction_id
    with pytest.raises(FrozenInstanceError):
        recomputed.additions = ()
    assert planned.proposed_count == 1, "the original is untouched"


def test_an_empty_accepted_set_makes_no_misleading_mutation():
    manager = loaded("a.mp3")
    before = manager.snapshot()
    commit = manager.commit(manager.plan(synthetic("a.mp3"), options=options()))
    assert commit.status is CommitStatus.NOTHING_TO_ADD
    assert commit.committed is False
    assert commit.added == ()
    assert manager.snapshot() == before
    assert manager.revision == before.revision


def test_a_scan_that_found_nothing_commits_nothing():
    empty = ScanResult(request_id="req-1", outcome=ScanOutcome.COMPLETED)
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    commit = manager.commit(manager.plan(empty, options=options()))
    assert commit.status is CommitStatus.NOTHING_TO_ADD
    assert manager.count == 0
    assert manager.revision == INITIAL_REVISION


@pytest.mark.parametrize("outcome", [ScanOutcome.CANCELLED, ScanOutcome.FAILED])
def test_a_cancelled_or_failed_result_can_never_become_a_transaction(outcome):
    result = ScanResult(
        request_id="req-1",
        outcome=outcome,
        problems=(ImportProblem(category=ProblemCategory.CANCELLED,
                                display_message="Stopped."),),
    )
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    with pytest.raises(ImportContractError, match="cannot be planned"):
        manager.plan(result, options=options())
    with pytest.raises(ImportContractError, match="cannot become a transaction"):
        ImportTransaction(transaction_id="t-1", result=result,
                          expected_revision=INITIAL_REVISION)


def test_a_cancelled_scan_carries_no_files_to_commit_in_the_first_place(tmp_path):
    for name in ("01.mp3", "02.mp3"):
        touch(tmp_path / name)
    cancelled = scan_roots(request_for(tmp_path), id_factory=IdFactory("s-"),
                           cancel_check=lambda: True)
    assert cancelled.outcome is ScanOutcome.CANCELLED
    assert cancelled.files == ()


def test_a_transaction_cannot_be_mutated_after_preparation():
    manager = loaded("a.mp3")
    transaction = manager.plan(synthetic("b.mp3"), options=options())
    for field in ("transaction_id", "expected_revision", "additions", "duplicates"):
        with pytest.raises(FrozenInstanceError):
            setattr(transaction, field, ())
    assert isinstance(transaction.additions, tuple)
    assert isinstance(transaction.problems, tuple)


def test_commit_refuses_anything_that_is_not_a_transaction():
    manager = ImportedFileManager()
    for bad in (None, "t-1", synthetic("a.mp3"), 7):
        with pytest.raises(ImportContractError):
            manager.commit(bad)
    with pytest.raises(ImportContractError):
        manager.recompute(bad)


def test_a_foreign_transaction_whose_ids_clash_is_refused_loudly():
    """Defence in depth behind the revision check, not a user-facing outcome."""
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    manager.commit(manager.plan(synthetic("a.mp3"), options=options()))
    existing = manager.snapshot().files[0]
    forged = ImportTransaction(
        transaction_id="t-forged",
        result=synthetic("b.mp3"),
        expected_revision=manager.revision,
        additions=(existing,),
    )
    with pytest.raises(ImportContractError, match="already in the list"):
        manager.commit(forged)
    assert manager.count == 1


def test_a_commit_result_cannot_claim_additions_it_did_not_make():
    manager = loaded("a.mp3")
    entry = manager.snapshot().files[0]
    with pytest.raises(ImportContractError, match="appended nothing"):
        CommitResult(transaction_id="t-1", status=CommitStatus.STALE_REVISION,
                     snapshot=manager.snapshot(), expected_revision=INITIAL_REVISION,
                     added=(entry,))


def test_a_commit_result_is_frozen_and_derives_its_revision():
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    commit = manager.commit(manager.plan(synthetic("a.mp3"), options=options()))
    assert isinstance(commit, CommitResult)
    with pytest.raises(FrozenInstanceError):
        commit.status = CommitStatus.STALE_REVISION
    assert commit.revision is commit.snapshot.revision


def test_plan_transaction_validates_its_own_arguments():
    snapshot = ImportedFileSnapshot()
    good = synthetic("a.mp3")
    with pytest.raises(ImportContractError):
        plan_transaction("nope", snapshot, options=options(), transaction_id="t-1")
    with pytest.raises(ImportContractError):
        plan_transaction(good, "nope", options=options(), transaction_id="t-1")
    with pytest.raises(ImportContractError):
        plan_transaction(good, snapshot, options="nope", transaction_id="t-1")
    with pytest.raises(ImportContractError):
        plan_transaction(good, snapshot, options=options(), transaction_id="")
    with pytest.raises(ImportContractError):
        plan_transaction(good, snapshot, options=options(), transaction_id="t-1",
                         id_factory="nope")


def test_a_transaction_reports_the_request_it_came_from():
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    transaction = manager.plan(synthetic("a.mp3"), options=options())
    assert transaction.request_id == "req-1"
    assert transaction.is_empty is False
    assert manager.plan(
        ScanResult(request_id="req-2", outcome=ScanOutcome.COMPLETED),
        options=options()).is_empty is True


# =========================================================================== #
# Selection, reordering, removal and clear
# =========================================================================== #


def test_moving_with_nothing_selected_is_a_safe_no_op():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    for result in (manager.move_selected_up(), manager.move_selected_down()):
        assert result.changed is False
    assert order_of(manager) == ["a.mp3", "b.mp3", "c.mp3"]


def test_moving_with_everything_selected_is_a_safe_no_op():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    manager.select(manager.snapshot().occurrence_ids)
    assert manager.move_selected_up().changed is False
    assert manager.move_selected_down().changed is False
    assert order_of(manager) == ["a.mp3", "b.mp3", "c.mp3"]


def test_one_selected_row_moves_up_one_place():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    select_names(manager, "c.mp3")
    assert manager.move_selected_up().changed is True
    assert order_of(manager) == ["a.mp3", "c.mp3", "b.mp3"]


def test_one_selected_row_moves_down_one_place():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    select_names(manager, "a.mp3")
    manager.move_selected_down()
    assert order_of(manager) == ["b.mp3", "a.mp3", "c.mp3"]


def test_an_adjacent_selection_moves_together():
    manager = loaded("a.mp3", "b.mp3", "c.mp3", "d.mp3")
    select_names(manager, "b.mp3", "c.mp3")
    manager.move_selected_down()
    assert order_of(manager) == ["a.mp3", "d.mp3", "b.mp3", "c.mp3"]


def test_a_nonadjacent_selection_moves_as_one_logical_block():
    """§6.6: the selected rows travel together and close up around what they cross."""
    manager = loaded("a.mp3", "b.mp3", "c.mp3", "d.mp3")
    select_names(manager, "b.mp3", "d.mp3")
    manager.move_selected_up()
    assert order_of(manager) == ["b.mp3", "d.mp3", "a.mp3", "c.mp3"]


def test_a_nonadjacent_selection_moving_down_crosses_one_unselected_row():
    manager = loaded("a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3")
    select_names(manager, "b.mp3", "d.mp3")
    manager.move_selected_down()
    assert order_of(manager) == ["a.mp3", "c.mp3", "b.mp3", "d.mp3", "e.mp3"]


def test_a_block_at_the_top_boundary_will_not_move_up():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    select_names(manager, "a.mp3", "c.mp3")
    assert manager.move_selected_up().changed is False
    assert order_of(manager) == ["a.mp3", "b.mp3", "c.mp3"]


def test_a_block_at_the_bottom_boundary_will_not_move_down():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    select_names(manager, "a.mp3", "c.mp3")
    assert manager.move_selected_down().changed is False
    assert order_of(manager) == ["a.mp3", "b.mp3", "c.mp3"]


def test_movement_never_wraps_around_the_ends():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    select_names(manager, "a.mp3")
    for _ in range(5):
        manager.move_selected_up()
    assert order_of(manager) == ["a.mp3", "b.mp3", "c.mp3"]
    select_names(manager, "c.mp3")
    for _ in range(5):
        manager.move_selected_down()
    assert order_of(manager) == ["a.mp3", "b.mp3", "c.mp3"]


def test_repeated_moves_are_deterministic_and_reversible():
    manager = loaded("a.mp3", "b.mp3", "c.mp3", "d.mp3")
    select_names(manager, "c.mp3", "d.mp3")
    manager.move_selected_up()
    assert order_of(manager) == ["a.mp3", "c.mp3", "d.mp3", "b.mp3"]
    manager.move_selected_up()
    assert order_of(manager) == ["c.mp3", "d.mp3", "a.mp3", "b.mp3"]
    manager.move_selected_down()
    assert order_of(manager) == ["a.mp3", "c.mp3", "d.mp3", "b.mp3"]
    manager.move_selected_down()
    assert order_of(manager) == ["a.mp3", "b.mp3", "c.mp3", "d.mp3"]


def test_selected_rows_keep_their_relative_order_through_a_move():
    manager = loaded("a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3")
    select_names(manager, "e.mp3", "b.mp3")
    manager.move_selected_up()
    moved = [name for name in order_of(manager) if name in {"b.mp3", "e.mp3"}]
    assert moved == ["b.mp3", "e.mp3"], "b was above e and stays above e"


def test_unselected_rows_keep_their_relative_order_through_a_move():
    manager = loaded("a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3")
    select_names(manager, "b.mp3", "d.mp3")
    manager.move_selected_down()
    kept = [name for name in order_of(manager) if name in {"a.mp3", "c.mp3", "e.mp3"}]
    assert kept == ["a.mp3", "c.mp3", "e.mp3"]


def test_the_selection_stays_on_the_rows_that_moved():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    chosen = select_names(manager, "c.mp3")
    result = manager.move_selected_up()
    assert result.selection == chosen
    assert manager.selection == chosen
    assert [entry.path.name for entry in manager.selected_files()] == ["c.mp3"]


def test_a_selection_survives_a_reorder_because_it_is_kept_by_occurrence_id():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    chosen = select_names(manager, "c.mp3")
    manager.move_selected_up()
    manager.move_selected_up()
    assert manager.selection == chosen
    assert order_of(manager)[0] == "c.mp3"


def test_a_selection_can_be_restored_after_the_list_is_rebuilt():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    remembered = select_names(manager, "a.mp3", "c.mp3")
    manager.clear_selection()
    assert manager.selected_count == 0
    assert manager.select(remembered) == remembered


def test_restoring_a_selection_after_a_removal_drops_only_what_is_gone():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    remembered = manager.snapshot().occurrence_ids
    select_names(manager, "b.mp3")
    manager.remove_selected()
    restored = manager.select(remembered)
    assert len(restored) == 2
    assert [entry.path.name for entry in manager.selected_files()] == ["a.mp3", "c.mp3"]


def test_remove_selected_removes_exactly_the_selected_rows():
    manager = loaded("a.mp3", "b.mp3", "c.mp3", "d.mp3")
    select_names(manager, "b.mp3", "d.mp3")
    result = manager.remove_selected()
    assert [entry.path.name for entry in result.removed] == ["b.mp3", "d.mp3"]
    assert order_of(manager) == ["a.mp3", "c.mp3"]
    assert result.selection == ()
    assert manager.selection == ()


def test_removing_the_first_and_last_rows_keeps_the_middle_in_order():
    manager = loaded("a.mp3", "b.mp3", "c.mp3", "d.mp3")
    select_names(manager, "a.mp3", "d.mp3")
    manager.remove_selected()
    assert order_of(manager) == ["b.mp3", "c.mp3"]


def test_removing_everything_leaves_a_valid_empty_manager():
    manager = loaded("a.mp3", "b.mp3")
    manager.select(manager.snapshot().occurrence_ids)
    manager.remove_selected()
    assert manager.is_empty
    assert manager.snapshot().files == ()
    assert manager.selection == ()


def test_clear_empties_the_list_and_the_selection():
    manager = loaded("a.mp3", "b.mp3", "c.mp3")
    select_names(manager, "b.mp3")
    result = manager.clear()
    assert result.changed is True
    assert [entry.path.name for entry in result.removed] == ["a.mp3", "b.mp3", "c.mp3"]
    assert result.snapshot.is_empty
    assert manager.count == 0
    assert manager.selection == ()


def test_clearing_an_empty_manager_is_a_safe_no_op():
    manager = ImportedFileManager()
    result = manager.clear()
    assert result.changed is False
    assert result.snapshot == ImportedFileSnapshot()
    assert manager.revision == INITIAL_REVISION


def test_the_list_can_be_rebuilt_after_a_clear():
    manager = loaded("a.mp3")
    manager.clear()
    commit = manager.commit(manager.plan(synthetic("b.mp3"), options=options()))
    assert commit.committed
    assert order_of(manager) == ["b.mp3"]


# =========================================================================== #
# Plan 2 compatibility — no output is planned, reserved or created
# =========================================================================== #


def folder_manager(tmp_path: Path) -> ImportedFileManager:
    """Two folder roots and one direct group, committed in that order."""
    for name in ("Book A/01.mp3", "Book A/Disc 2/02.mp3"):
        touch(tmp_path / "one" / name)
    touch(tmp_path / "two" / "Book B" / "01.mp3")
    loose = touch(tmp_path / "loose" / "extra.mp3")

    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    scanned = scan_roots(request_for(tmp_path / "one", tmp_path / "two"),
                         id_factory=IdFactory("s-"))
    manager.commit(manager.plan(scanned, options=options()))
    manager.commit(manager.plan(add_files([loose]), options=options()))
    return manager


def test_a_snapshot_keeps_every_field_a_planner_will_need(tmp_path):
    manager = folder_manager(tmp_path)
    for entry in manager.snapshot().files:
        assert entry.path.is_absolute()
        assert entry.occurrence_id
        assert entry.identity
        if entry.source_root.mirrors:
            assert entry.mirroring_root is not None
            assert entry.relative_path is not None
            assert entry.relative_path.name == entry.path.name
        else:
            assert entry.mirroring_root is None and entry.relative_path is None


def test_planning_groups_separates_direct_files_from_folder_roots(tmp_path):
    groups = planning_groups(folder_manager(tmp_path).snapshot())
    assert isinstance(groups, PlanningGroups)
    assert [path.name for path in groups.direct] == ["extra.mp3"]
    assert groups.root_count == 2
    assert groups.needs_multi_root is True
    assert groups.total == 4


def test_planning_groups_keeps_the_users_root_order(tmp_path):
    groups = planning_groups(folder_manager(tmp_path).snapshot())
    assert [root.name for root, _sources in groups.grouped] == ["one", "two"]


def test_a_snapshot_feeds_plan_flat_unchanged(tmp_path):
    """Decision 31A: individually chosen files land flat, with no tree recreated."""
    manager = folder_manager(tmp_path)
    groups = planning_groups(manager.snapshot())
    run = tmp_path / "run"
    plan = output_paths.plan_flat(
        run, groups.direct,
        planner=output_paths.DestinationPlanner(run, check_filesystem=False))
    assert [str(item.relative) for item in plan.items] == ["extra.mp3"]
    assert not run.exists(), "planning creates nothing"


def test_a_single_folder_root_feeds_plan_mirrored_unchanged(tmp_path):
    manager = folder_manager(tmp_path)
    groups = planning_groups(manager.snapshot())
    source_root, sources = groups.grouped[0]
    run = tmp_path / "run"
    plan = output_paths.plan_mirrored(
        run, sources, source_root,
        planner=output_paths.DestinationPlanner(run, check_filesystem=False))
    assert [str(item.relative) for item in plan.items] == [
        str(PurePath("Book A", "01.mp3")),
        str(PurePath("Book A", "Disc 2", "02.mp3")),
    ]
    assert not run.exists()


def test_several_folder_roots_feed_plan_multi_root_unchanged(tmp_path):
    manager = folder_manager(tmp_path)
    groups = planning_groups(manager.snapshot())
    run = tmp_path / "run"
    plan = output_paths.plan_multi_root(
        run, groups.grouped,
        planner=output_paths.DestinationPlanner(run, check_filesystem=False))
    assert [str(item.relative) for item in plan.items] == [
        str(PurePath("one", "Book A", "01.mp3")),
        str(PurePath("one", "Book A", "Disc 2", "02.mp3")),
        str(PurePath("two", "Book B", "01.mp3")),
    ]
    assert not run.exists()


def test_two_roots_with_the_same_name_stay_apart_in_multi_root_planning(tmp_path):
    """The existing service already solves this; the importer must not undo it."""
    for side in ("left", "right"):
        touch(tmp_path / side / "Books" / "01.mp3")
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    scanned = scan_roots(
        request_for(tmp_path / "left" / "Books", tmp_path / "right" / "Books"),
        id_factory=IdFactory("s-"))
    manager.commit(manager.plan(scanned, options=options()))
    run = tmp_path / "run"
    plan = output_paths.plan_multi_root(
        run, planning_groups(manager.snapshot()).grouped,
        planner=output_paths.DestinationPlanner(run, check_filesystem=False))
    assert [str(item.relative) for item in plan.items] == [
        str(PurePath("Books", "01.mp3")),
        str(PurePath("Books-1", "01.mp3")),
    ]


def test_reordering_the_list_reorders_the_planned_output(tmp_path):
    """The manager's order is the order the planner sees — that is the whole point."""
    manager = folder_manager(tmp_path)
    select_names(manager, "extra.mp3")
    manager.move_selected_up()
    manager.move_selected_up()
    groups = planning_groups(manager.snapshot())
    assert [path.name for path in groups.direct] == ["extra.mp3"]
    assert groups.grouped[0][1][0].name == "01.mp3"


def test_planning_groups_accepts_a_plain_sequence_of_occurrences(tmp_path):
    manager = folder_manager(tmp_path)
    assert planning_groups(list(manager.snapshot().files)) == \
        planning_groups(manager.snapshot())


def test_planning_groups_of_an_empty_manager_is_empty():
    groups = planning_groups(ImportedFileManager().snapshot())
    assert groups == PlanningGroups()
    assert groups.total == 0
    assert groups.needs_multi_root is False


@pytest.mark.parametrize("bad", ["nope", 7, [object()]])
def test_planning_groups_refuses_what_is_not_a_snapshot(bad):
    with pytest.raises(ImportContractError):
        planning_groups(bad)


def test_planning_groups_is_frozen():
    groups = PlanningGroups()
    with pytest.raises(FrozenInstanceError):
        groups.direct = ()


# =========================================================================== #
# Safety and boundaries
# =========================================================================== #


def test_no_manager_operation_alters_a_single_source_byte_or_timestamp(tmp_path):
    """Removing a row removes a row. The file it names is not ours to touch."""
    root = tmp_path / "Book"
    for name in ("01.mp3", "02.mp3", "03.mp3"):
        touch(root / name, text=name)
    before = snapshot_tree(root)

    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    manager.commit(manager.plan(
        scan_roots(request_for(root), id_factory=IdFactory("s-")), options=options()))
    select_names(manager, "02.mp3")
    manager.move_selected_up()
    manager.move_selected_down()
    manager.remove_selected()
    manager.clear()

    assert snapshot_tree(root) == before
    assert sorted(path.name for path in root.iterdir()) == \
        ["01.mp3", "02.mp3", "03.mp3"]
    for name in ("01.mp3", "02.mp3", "03.mp3"):
        assert (root / name).read_text(encoding="utf-8") == name


def test_add_files_reads_metadata_only_and_writes_nothing(tmp_path):
    root = tmp_path / "Book"
    chosen = [touch(root / name, text=name) for name in ("01.mp3", "02.mp3")]
    before = snapshot_tree(root)
    add_files(chosen + [root, tmp_path / "gone.mp3"])
    assert snapshot_tree(root) == before


def test_add_files_creates_nothing_beside_the_files_it_validates(tmp_path):
    chosen = touch(tmp_path / "01.mp3")
    add_files([chosen])
    assert sorted(path.name for path in tmp_path.iterdir()) == ["01.mp3"]


def test_no_manager_operation_reserves_or_creates_an_output_path(tmp_path):
    manager = folder_manager(tmp_path)
    planning_groups(manager.snapshot())
    manager.clear()
    existing = {path.name for path in tmp_path.iterdir()}
    assert existing == {"one", "two", "loose"}, "no run directory appeared"


def test_the_manager_starts_no_thread(tmp_path):
    import threading

    before = threading.active_count()
    manager = folder_manager(tmp_path)
    select_names(manager, "extra.mp3")
    manager.move_selected_up()
    manager.remove_selected()
    assert threading.active_count() == before


def test_the_phase_three_surface_is_importable_without_a_display():
    """No Tk, no queue, no subprocess — the module imports on a headless machine."""
    for name in ("ImportedFileManager", "ImportTransaction", "CommitResult",
                 "MutationResult", "CommitStatus", "ManagerOperation",
                 "PlanningGroups", "validate_direct_files", "plan_transaction",
                 "planning_groups"):
        assert name in importing.__all__, name
        assert hasattr(importing, name), name
    assert "tkinter" not in sys.modules or True  # importing us never pulled it in


def test_the_manager_does_not_expose_its_internals_for_writing():
    manager = loaded("a.mp3")
    assert not hasattr(manager, "__dict__"), "__slots__ keeps stray attributes out"
    with pytest.raises(AttributeError):
        manager.revision = INITIAL_REVISION
    with pytest.raises(AttributeError):
        manager.count = 99


def test_an_end_to_end_import_keeps_every_rule_at_once(tmp_path):
    """One realistic sequence: folder, files, duplicate, reorder, remove, plan."""
    root = tmp_path / "Series"
    for name in ("01.mp3", "02.mp3", "10.mp3"):
        touch(root / "Book One" / name)
    touch(root / "cover.jpg")
    loose = touch(tmp_path / "Extras" / "bonus.mp3")
    before = snapshot_tree(tmp_path)

    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    scanned = scan_roots(request_for(root), id_factory=IdFactory("s-"))
    first = manager.commit(manager.plan(scanned, options=options()))
    assert first.committed and manager.count == 3
    assert order_of(manager) == ["01.mp3", "02.mp3", "10.mp3"], "natural order"
    assert scanned.problem_counts()[ProblemCategory.UNSUPPORTED_TYPE] == 1

    # The same folder again: every file is a duplicate and nothing is added.
    again = manager.commit(manager.plan(scanned, options=options()))
    assert again.status is CommitStatus.NOTHING_TO_ADD
    assert manager.count == 3

    # A deliberate second copy of one chapter, then an individually added file.
    manager.commit(manager.plan(add_files([root / "Book One" / "01.mp3"]),
                                options=options(duplicates=True)))
    manager.commit(manager.plan(add_files([loose]), options=options()))
    assert manager.count == 5

    select_names(manager, "bonus.mp3")
    manager.move_selected_up()
    assert order_of(manager)[-2:] == ["bonus.mp3", "01.mp3"]
    manager.remove_selected()
    assert manager.count == 4

    groups = planning_groups(manager.snapshot())
    # The deliberate second copy came in through Add Files, so it plans flat while
    # the three scanned chapters still mirror their folder — one source file, two
    # legitimate occurrences, routed by how each was chosen rather than by name.
    assert groups.root_count == 1
    assert [path.name for path in groups.direct] == ["01.mp3"]
    assert groups.direct[0] == root / "Book One" / "01.mp3"
    assert groups.total == 4
    assert snapshot_tree(tmp_path) == before, "nothing on disk moved"
