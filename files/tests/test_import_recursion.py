"""``Include subfolders`` — v0.6.2 Plan 5, Phase 7A (Decision 7A / D7A).

One frozen per-import option, gated at the scanner's **single** descent point, plus
the `Clear All` label correction.

**What this had to protect.** TTS and Cover already depend on Add Folder recursing,
so the whole extension rests on the default being ``True`` and the recursive path
being byte-for-byte the behaviour that shipped. The interesting tests here are
therefore not the shallow ones — they are the ones proving nothing moved when the
option is left alone, and the one that proves a skipped child directory is never
*read* rather than merely never reported.

Everything is built under ``tmp_path``. Nothing touches the repository, real media,
a home directory or a network share.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared import importing
from shared.importing import (
    IdFactory,
    ImportContractError,
    ImportOptions,
    ImportRoot,
    RootKind,
    ScanOutcome,
    ScanRequest,
    SupportedType,
    SupportedTypeCatalog,
    scan_roots,
    validate_direct_files,
)

from test_importing import make_config


def catalog() -> SupportedTypeCatalog:
    return SupportedTypeCatalog((
        SupportedType("mp3", "MP3 audio", (".mp3",)),
        SupportedType("m4b", "M4B audiobook", (".m4b",)),
    ))


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def request_for(*roots: Path, subfolders: bool = True, hidden: bool = False) -> ScanRequest:
    book = catalog()
    return ScanRequest(
        request_id="req-1",
        roots=tuple(ImportRoot(f"root-{i}", path, i) for i, path in enumerate(roots)),
        catalog=book,
        options=ImportOptions.for_catalog(
            book, include_hidden_folders=hidden, include_subfolders=subfolders),
        effective_config=make_config(),
        created_at=1.0,
    )


def scan(*roots: Path, subfolders: bool = True, hidden: bool = False, **kwargs):
    result = scan_roots(request_for(*roots, subfolders=subfolders, hidden=hidden),
                        id_factory=IdFactory("t-"), **kwargs)
    return result, [str(entry.relative_path) for entry in result.files]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """root/root1.m4b, root/child/child1.m4b, root/child/deeper/deep1.m4b."""
    root = tmp_path / "root"
    touch(root / "root1.m4b")
    touch(root / "child" / "child1.m4b")
    touch(root / "child" / "deeper" / "deep1.m4b")
    return root


# --------------------------------------------------------------------------- #
# The frozen contract
# --------------------------------------------------------------------------- #


def test_the_default_is_recursive():
    """The whole compatibility story rests on this one value."""
    assert ImportOptions().include_subfolders is True
    assert ImportOptions.for_catalog(catalog()).include_subfolders is True


def test_explicit_values_are_accepted():
    assert ImportOptions(include_subfolders=True).include_subfolders is True
    assert ImportOptions(include_subfolders=False).include_subfolders is False


@pytest.mark.parametrize("bad", [1, 0, "yes", "", None, [], "True"])
def test_a_truthy_stand_in_is_refused_exactly_like_the_other_booleans(bad):
    """Same strictness as ``include_hidden_folders``: ``1`` is not ``True`` here."""
    with pytest.raises(ImportContractError):
        ImportOptions(include_subfolders=bad)
    with pytest.raises(ImportContractError):
        ImportOptions(include_hidden_folders=bad)


def test_for_catalog_freezes_an_explicit_false():
    assert ImportOptions.for_catalog(
        catalog(), include_subfolders=False).include_subfolders is False


def test_for_catalog_leaves_the_other_defaults_alone():
    options = ImportOptions.for_catalog(catalog(), include_subfolders=False)
    assert options.include_hidden_folders is False
    assert options.allow_duplicate_files is False
    assert options.selected_type_ids == catalog().default_selection()


def test_the_option_is_part_of_equality_and_stays_frozen():
    book = catalog()
    recursive = ImportOptions.for_catalog(book)
    shallow = ImportOptions.for_catalog(book, include_subfolders=False)
    assert recursive != shallow
    assert recursive == ImportOptions.for_catalog(book)
    with pytest.raises(Exception):
        shallow.include_subfolders = True  # type: ignore[misc]


def test_positional_construction_of_the_original_fields_is_unaffected():
    """The field was appended, so existing positional callers cannot shift."""
    options = ImportOptions(frozenset({"mp3"}), True, True)
    assert options.include_hidden_folders is True
    assert options.allow_duplicate_files is True
    assert options.include_subfolders is True


# --------------------------------------------------------------------------- #
# Recursive — today's behaviour, unchanged
# --------------------------------------------------------------------------- #


def test_the_default_still_finds_every_nested_file(tree):
    _result, relatives = scan(tree)
    assert relatives == [
        "root1.m4b",
        str(Path("child/child1.m4b")),
        str(Path("child/deeper/deep1.m4b")),
    ]


def test_explicit_true_matches_the_default_exactly(tree):
    _r1, default = scan(tree)
    _r2, explicit = scan(tree, subfolders=True)
    assert default == explicit


def test_direct_files_are_still_emitted_before_descendants(tree):
    _result, relatives = scan(tree)
    assert relatives[0] == "root1.m4b"


# --------------------------------------------------------------------------- #
# Shallow
# --------------------------------------------------------------------------- #


def test_shallow_imports_only_the_root_level_files(tree):
    _result, relatives = scan(tree, subfolders=False)
    assert relatives == ["root1.m4b"]


def test_shallow_still_completes_successfully(tree):
    result, _relatives = scan(tree, subfolders=False)
    assert result.outcome is ScanOutcome.COMPLETED


def test_shallow_never_reads_the_child_directory(tree, monkeypatch):
    """Not merely "no nested file appeared" — the child is never *opened*.

    A scanner that walked the subtree and filtered the results afterwards would
    pass a file-list assertion while still paying the cost and still touching
    directories the user excluded. This watches ``os.scandir`` itself.
    """
    seen: list[Path] = []
    real = os.scandir

    def watched(path=".", *args, **kwargs):
        seen.append(Path(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(importing.os, "scandir", watched)
    scan(tree, subfolders=False)

    assert tree in seen, "the selected root itself must still be enumerated"
    assert (tree / "child") not in seen
    assert (tree / "child" / "deeper") not in seen


def test_recursive_does_read_the_child_directory(tree, monkeypatch):
    """The counterpart, so the instrumentation above is proved to be watching."""
    seen: list[Path] = []
    real = os.scandir

    def watched(path=".", *args, **kwargs):
        seen.append(Path(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(importing.os, "scandir", watched)
    scan(tree, subfolders=True)

    assert (tree / "child") in seen
    assert (tree / "child" / "deeper") in seen


def test_shallow_reports_no_problem_for_the_folders_it_did_not_enter(tree):
    """Not descending is not an error; a skipped child must raise nothing."""
    result, _relatives = scan(tree, subfolders=False)
    assert result.problems == ()


def test_shallow_root_level_files_keep_their_natural_order(tmp_path):
    root = tmp_path / "root"
    for name in ("Book 10.m4b", "Book 2.m4b", "Book 1.m4b"):
        touch(root / name)
    touch(root / "nested" / "Book 3.m4b")
    _result, relatives = scan(root, subfolders=False)
    assert relatives == ["Book 1.m4b", "Book 2.m4b", "Book 10.m4b"]


def test_shallow_keeps_root_relative_provenance(tmp_path):
    root = tmp_path / "root"
    touch(root / "only.m4b")
    touch(root / "nested" / "hidden-away.m4b")
    result, _relatives = scan(root, subfolders=False)
    entry = result.files[0]
    assert str(entry.relative_path) == "only.m4b"
    assert entry.source_root.path == root
    assert entry.path == root / "only.m4b"


def test_shallow_preserves_the_user_root_order(tmp_path):
    second = tmp_path / "zzz"
    first = tmp_path / "aaa"
    touch(second / "s.m4b")
    touch(second / "deep" / "s2.m4b")
    touch(first / "f.m4b")
    result, _relatives = scan(second, first, subfolders=False)
    assert [entry.source_root.path for entry in result.files] == [second, first]
    assert [str(entry.relative_path) for entry in result.files] == ["s.m4b", "f.m4b"]


def test_shallow_counts_only_what_it_imported(tree):
    result, relatives = scan(tree, subfolders=False)
    assert result.discovered_count == len(relatives) == 1


def test_a_root_holding_only_subfolders_is_empty_but_successful(tmp_path):
    root = tmp_path / "root"
    touch(root / "sub" / "a.m4b")
    result, relatives = scan(root, subfolders=False)
    assert relatives == []
    assert result.outcome is ScanOutcome.COMPLETED


# --------------------------------------------------------------------------- #
# Independence from the other options
# --------------------------------------------------------------------------- #


def test_hidden_folders_are_still_governed_only_by_their_own_option(tmp_path):
    root = tmp_path / "root"
    touch(root / "top.m4b")
    touch(root / ".secret" / "inside.m4b")

    _r, without = scan(root, subfolders=True, hidden=False)
    _r, with_hidden = scan(root, subfolders=True, hidden=True)
    assert without == ["top.m4b"]
    assert str(Path(".secret/inside.m4b")) in with_hidden


def test_hidden_true_cannot_override_shallow(tmp_path):
    """The two options answer different questions and must not bleed together."""
    root = tmp_path / "root"
    touch(root / "top.m4b")
    touch(root / ".secret" / "inside.m4b")
    touch(root / "plain" / "inside.m4b")
    _result, relatives = scan(root, subfolders=False, hidden=True)
    assert relatives == ["top.m4b"]


def test_both_facts_survive_in_the_frozen_options():
    options = ImportOptions.for_catalog(
        catalog(), include_hidden_folders=True, include_subfolders=False)
    assert options.include_hidden_folders is True
    assert options.include_subfolders is False


@pytest.mark.parametrize("subfolders", [True, False])
def test_add_files_is_untouched_by_the_option(tmp_path, subfolders):
    """Direct Add Files never recursed and must not start."""
    chosen = touch(tmp_path / "picked.m4b")
    touch(tmp_path / "folder" / "nested.m4b")
    book = catalog()
    options = ImportOptions.for_catalog(book, include_subfolders=subfolders)
    result = validate_direct_files(
        [str(chosen), str(tmp_path / "folder")],
        request_id="req-1",
        root=ImportRoot("direct", None, 0, kind=RootKind.DIRECT_FILES),
        catalog=book, options=options, id_factory=IdFactory("d-"))
    # Only the chosen file is accepted; the folder is refused and never walked,
    # so the nested file inside it cannot appear under either option value.
    assert [entry.path for entry in result.files] == [chosen]


@pytest.mark.parametrize("subfolders", [True, False])
def test_cancellation_semantics_are_unchanged(tree, subfolders):
    result = scan_roots(request_for(tree, subfolders=subfolders),
                        id_factory=IdFactory("t-"), cancel_check=lambda: True)
    assert result.outcome is ScanOutcome.CANCELLED
    assert result.files == ()


# --------------------------------------------------------------------------- #
# The choice belongs to the import that was started
# --------------------------------------------------------------------------- #


def test_the_scanner_reads_the_option_from_the_frozen_request(tree):
    request = request_for(tree, subfolders=False)
    assert request.options.include_subfolders is False
    result = scan_roots(request, id_factory=IdFactory("t-"))
    assert [str(f.relative_path) for f in result.files] == ["root1.m4b"]


def test_a_later_ui_change_cannot_reach_a_request_already_made(tree):
    """``ImportOptions`` is frozen, so a toggle after the scan starts is inert."""
    request = request_for(tree, subfolders=False)
    with pytest.raises(Exception):
        request.options.include_subfolders = True  # type: ignore[misc]
    result = scan_roots(request, id_factory=IdFactory("t-"))
    assert len(result.files) == 1


def test_no_second_scanner_was_introduced():
    """One traversal authority, gated — not a shallow fork of the algorithm."""
    scanners = {
        name for name in dir(importing)
        if "scan" in name.lower() and callable(getattr(importing, name))
        and not isinstance(getattr(importing, name), type)
    }
    assert scanners == {"scan_roots"}, scanners
    for banned in ("scan_roots_shallow", "shallow_scan", "recursive_scan",
                   "walk_shallow", "_scan_shallow"):
        assert not hasattr(importing, banned), banned


# --------------------------------------------------------------------------- #
# Propagation — the frozen request is the only authority
# --------------------------------------------------------------------------- #

from test_import_coordination import (  # noqa: E402
    coordinator_for,
    folder_request,
    names_in,
    run_to_completion,
)
from shared.import_coordination import OutcomeStatus  # noqa: E402
from shared.importing import ImportedFileManager  # noqa: E402


def coordinated(root: Path, *, subfolders: bool):
    """Drive one real import through the coordinator and return the manager names."""
    request = folder_request(root)
    request = ScanRequest(
        request_id=request.request_id,
        roots=request.roots,
        catalog=request.catalog,
        options=ImportOptions(
            selected_type_ids=request.options.selected_type_ids,
            include_hidden_folders=request.options.include_hidden_folders,
            allow_duplicate_files=request.options.allow_duplicate_files,
            include_subfolders=subfolders,
        ),
        effective_config=request.effective_config,
        created_at=request.created_at,
    )
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    outcome = run_to_completion(coordinator, request)
    assert outcome.status is OutcomeStatus.COMMITTED, outcome
    return sorted(names_in(manager))


@pytest.fixture
def coordination_tree(tmp_path: Path) -> Path:
    root = tmp_path / "Books"
    touch(root / "top.mp3")
    touch(root / "nested" / "deep.mp3")
    return root


def test_true_survives_the_worker_boundary(coordination_tree):
    assert coordinated(coordination_tree, subfolders=True) == ["deep.mp3", "top.mp3"]


def test_false_survives_the_worker_boundary(coordination_tree):
    """The choice made at start is the choice the worker scanned with."""
    assert coordinated(coordination_tree, subfolders=False) == ["top.mp3"]


def test_the_coordinator_holds_no_recursion_state_of_its_own():
    """``ScanRequest.options`` is the single authority — nothing shadows it."""
    coordinator = coordinator_for()
    for banned in ("include_subfolders", "_include_subfolders", "recursive",
                   "_recursive", "shallow", "_shallow"):
        assert not hasattr(coordinator, banned), banned


def test_no_module_level_recursion_flag_exists():
    for module in (importing, __import__("shared.import_coordination",
                                         fromlist=["x"])):
        for banned in ("INCLUDE_SUBFOLDERS", "RECURSIVE", "SHALLOW",
                       "_include_subfolders"):
            assert not hasattr(module, banned), (module.__name__, banned)
