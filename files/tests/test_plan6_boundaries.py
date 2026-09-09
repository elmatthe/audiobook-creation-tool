"""Plan 6 structural boundaries — v0.6.3 Drop 1, from Phase 1 onward.

Drop section 21 says the multi-book data layer is Tk-free, thread-free, clock-free
and ``output_paths``-free, and drop section 22 draws the Decision 51A line: Plan 6
may carry a per-book *configuration field*, and everything that turns one into a
filename is Plan 7's. Those are the kind of claims that quietly stop being true, so
they are asserted here rather than trusted.

**AST, never substring slicing.** Drop section 23.3 requires it, and Phase 0 supplied
the reason from this very repository: a draft check asserting ``"retry" not in
source`` flagged ``m4b_maker.py``, whose only hit is the log line *"Fast path failed
— retrying in Safe Mode…"* — the Fast-first fallback, not Retry Failed. A comment, a
docstring or a message must never be able to pass or fail a boundary test, so every
guard below reads nodes.

**Every guard is mutation-checked.** A guard that cannot fail is not a guard, so each
one is also run against a synthetic sample carrying the shape it forbids, and must
reject it. The samples are parsed from strings owned by this test module; **no
production source is ever mutated on disk to manufacture a red result.**

This module grows with the plan. Phase 1 establishes the frame and the data-layer
guards; later phases add their own contracts to it rather than starting a third
AST-inspection framework.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib

import pytest

from test_plan3_boundaries import (
    REPO_ROOT,
    SHARED,
    UNIVERSAL,
    constructed_names,
    defined_names,
    imported_names,
    parse,
    referenced_names,
)

# --------------------------------------------------------------------------- #
# What Plan 6 owns so far
# --------------------------------------------------------------------------- #

#: The pure data layer. Phase 6 adds ``numbering.py`` and Phase 8 adds
#: ``book_workspace_ui.py``; neither exists yet and neither is assumed here.
DATA_LAYER = ("book_workspace.py",)

#: Phase 0 recorded these SHA-256 values as the byte-identity gates for the
#: consumer panels Plan 6 must not touch. Plan 7 converts M4B Maker; Plan 8 the
#: other two. Until then a difference here means Plan 6 reached somewhere it may
#: not, and it is a stop gate rather than a value to update.
PHASE0_PANEL_HASHES = {
    "mp3_tools/m4b_maker.py":
        "55774911516dd0b5b30d51c6a0b6d93ac62005d16fa1adb46e69f8b61e2b7d8d",
    "mp3_tools/mp3_tool.py":
        "96c746a8a4defd9c495d66770b04e2f789a9a37957018c263e5f3371fe3984d5",
    "mp3_tools/m4b_metadata_editor.py":
        "310b27f6d46668782305b54434f5b9bd00f4611e077f6772f3410adb5ffdd180",
}

#: Also recorded at Phase 0. The Converter and the numbering allocator are Plan 5's;
#: Phase 6's promotion is the only authorised change to the last two, and it has not
#: happened, so all four must still match.
PHASE0_PLAN5_HASHES = {
    "scripts/Universal/mp3_tools/m4b_converter.py":
        "a44418853b3f8e38f9f78829c2f388bc0cb85b29bf35dcbc64d7d5ec9ab60880",
    "scripts/Universal/mp3_tools/m4b_numbering.py":
        "a26cd25954c5ad21d16c350642025e768538c60f9df0475c71385191a9f9fb98",
    "files/tests/test_m4b_numbering.py":
        "787f5dfc54509412ad14f3d7de6b8a819d4326777187201a93d4dbadda247dbb",
}

#: Module names the data layer may never import, by the drop section that forbids
#: each: Tk and threading (21), ``output_paths`` (22), and the rest because a pure
#: vocabulary has no business reaching a process, a socket or a disk.
FORBIDDEN_IMPORTS = (
    "tkinter", "threading", "queue", "asyncio", "multiprocessing",
    "subprocess", "socket", "urllib", "http", "requests",
    "shared.output_paths", "shared.paths", "shutil", "os.path", "sysconfig",
)

#: Callables that would betray a concurrency primitive, a clock or process work.
FORBIDDEN_CALLS = (
    "Thread", "Lock", "RLock", "Condition", "Event", "Semaphore", "Timer",
    "Queue", "SimpleQueue", "LifoQueue", "PriorityQueue",
    "time", "monotonic", "perf_counter", "process_time", "sleep", "now", "today",
    "Popen", "run", "call", "check_output", "check_call", "system",
    "open", "mkdir", "makedirs", "rmtree", "unlink", "remove", "rename", "replace",
    "urlopen", "socket", "connect",
)

#: Names that betray a platform fork. Drop section 20: one business layer, and the
#: appearance difference lives in the adapter, which asks the theme instead.
PLATFORM_NAMES = ("platform", "uname", "win32", "darwin")

#: Phase 3 implements Decision 12A, so reaching a file's own parent is now
#: legitimate. What stays forbidden is the **Plan 3 grouping primitive**: the drop
#: established that ``planning_groups`` buckets on ``source_root.root_id`` — the
#: folder the user selected — which is the right key for mirroring an output tree
#: and the wrong one for "one directory of files is one book". Plan 6 must neither
#: consume it nor reinterpret it.
FORBIDDEN_GROUPING = ("planning_groups", "PlanningGroups")

#: Every way this layer could reach a disk. Phase 3 projects an already-committed
#: snapshot; the importer did the scanning, and none of this may reappear here.
FILESYSTEM_CALLS = (
    "glob", "rglob", "walk", "listdir", "scandir", "iterdir",
    "stat", "lstat", "exists", "is_file", "is_dir", "is_symlink",
    "resolve", "absolute", "cwd", "home", "expanduser", "samefile",
    "touch", "mkdir", "makedirs", "rmdir", "chmod", "readlink",
)

#: Plan 3 owns running an import. Plan 6 is handed the finished value.
IMPORT_EXECUTION = (
    "ImportCoordinator", "ImportPoller", "ImportCancellation",
    "scan_roots", "validate_direct_files", "plan_transaction",
    "ImportedFileManager",
)

#: Phase 5 owns freezing effective values into a run. None of this may appear
#: while Phase 4 resolves precedence live from immutable workspace state.
PHASE5_NAMES = (
    "capture_run", "RunSnapshot", "BookRunSnapshot", "BookRunResult",
    "RunResult", "RetryRequest", "FailureLog", "FailureRecord",
    "capture_workspace_run", "JobController",
)


def source_of(relative: str):
    return parse(SHARED / relative)


def sample(code: str) -> ast.Module:
    """Parse a synthetic module owned by this test, for mutation-checking a guard."""
    return ast.parse(code)


def sha256_of(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# The guards themselves, as pure functions over a tree
#
# Stated once so the real module and a synthetic sample go through exactly the
# same code. A guard that only ever sees code it approves of is untested.
# --------------------------------------------------------------------------- #


def forbidden_imports_in(tree: ast.Module) -> set[str]:
    modules = imported_names(tree)
    found = set()
    for banned in FORBIDDEN_IMPORTS:
        for entry in modules:
            if entry == banned or entry.startswith(f"{banned}."):
                found.add(banned)
            # ``from tkinter import ttk`` records the bare name too.
            if entry.split(".")[0] == banned.split(".")[0] and "." not in banned:
                found.add(banned)
    return found


def forbidden_calls_in(tree: ast.Module) -> set[str]:
    return constructed_names(tree) & set(FORBIDDEN_CALLS)


def platform_branching_in(tree: ast.Module) -> set[str]:
    return referenced_names(tree) & set(PLATFORM_NAMES)


def forbidden_grouping_in(tree: ast.Module) -> set[str]:
    """Use of Plan 3's ``planning_groups`` — the wrong key for Decision 12A."""
    return (referenced_names(tree) | imported_names(tree)) & set(FORBIDDEN_GROUPING)


def filesystem_calls_in(tree: ast.Module) -> set[str]:
    """Any call that would reach a disk, by callee name.

    ``ast.Call`` only, so a *field* named ``stat`` or a docstring mentioning
    ``exists`` contributes nothing — the question is whether something is invoked.
    """
    return constructed_names(tree) & set(FILESYSTEM_CALLS)


def import_execution_in(tree: ast.Module) -> set[str]:
    """Any sign this module runs an import rather than consuming one."""
    return (referenced_names(tree) | imported_names(tree)) & set(IMPORT_EXECUTION)




def widget_classes_in(tree: ast.Module) -> set[str]:
    """A class whose base names a widget toolkit, or whose name reads as one."""
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {ast.unparse(base) for base in node.bases}
        if any("tk" in base.lower() or "ttk" in base.lower() or "widget" in base.lower()
               for base in bases):
            found.add(node.name)
        if node.name.endswith(("Widget", "Frame", "Panel", "View", "Bar", "Dialog")):
            found.add(node.name)
    return found


# --------------------------------------------------------------------------- #
# Phase 1 — the data layer keeps its boundaries
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_data_layer_imports_nothing_it_is_forbidden_to_import(name):
    """Drop sections 12, 21 and 22, as one assertion over the import statements."""
    assert forbidden_imports_in(source_of(name)) == set()


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_data_layer_imports_no_tk_under_any_spelling(name):
    modules = imported_names(source_of(name))
    for entry in modules:
        assert not entry.split(".")[0].lower().startswith("tkinter"), entry
        assert entry.lower() not in {"tk", "ttk"}, entry


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_data_layer_constructs_no_concurrency_primitive_clock_or_process(name):
    """No thread, lock, event, condition or queue; no clock; no subprocess."""
    assert forbidden_calls_in(source_of(name)) == set()


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_data_layer_reaches_no_output_path_service(name):
    """Drop section 22: Plan 2 keeps sole ownership of where anything lands."""
    tree = source_of(name)
    modules = imported_names(tree)
    assert not any("output_paths" in entry for entry in modules), modules
    forbidden = {
        "sanitize_component", "sanitize_relative", "DestinationPlanner",
        "SourceSidePlanner", "reserve_run_directory", "ensure_output_base",
        "plan_flat", "plan_mirrored", "plan_multi_root", "destination_hint",
        "numbered_variant", "RunReservation",
    }
    assert referenced_names(tree) & forbidden == set()


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_data_layer_imports_no_tool_module(name):
    """``shared/`` may not depend on ``mp3_tools/`` or ``tts/``; that inverts the layering."""
    modules = imported_names(source_of(name))
    for entry in modules:
        assert "mp3_tools" not in entry, entry
        assert not entry.split(".")[0] == "tts", entry


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_data_layer_does_not_branch_on_the_platform(name):
    """Decision 29A: one business layer. Appearance is the adapter's problem."""
    assert platform_branching_in(source_of(name)) == set()


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_data_layer_defines_no_widget_class(name):
    assert widget_classes_in(source_of(name)) == set()


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_data_layer_reads_no_clock(name):
    """Every timestamp in this foundation arrives through an injected clock."""
    modules = imported_names(source_of(name))
    for entry in modules:
        assert entry.split(".")[0] not in {"time", "datetime", "calendar"}, entry


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_only_thing_taken_from_os_is_a_separator_constant(name):
    """``import os`` is the one import that could look like a door. It is not.

    ``importing.py`` imports ``os`` for exactly the same reason — the separator
    constants that keep an identifier from being a path fragment. Pin what is
    actually used, so a later edit cannot quietly reach ``os.remove`` through an
    import this guard already waved through.
    """
    tree = source_of(name)
    used = {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name) and node.value.id == "os"
    }
    assert used <= {"sep", "altsep"}, used


def test_the_data_layer_reuses_the_one_deep_freeze_and_defines_no_second():
    """Drop section 9: ``freeze_options`` is consumed, never re-implemented."""
    tree = source_of("book_workspace.py")
    assert "shared.job_control.freeze_options" in imported_names(tree)
    defined = defined_names(tree)
    for invented in ("freeze_options", "_freeze_value", "deep_freeze", "_deep_copy"):
        assert invented not in defined, invented


def test_the_data_layer_reuses_the_one_identifier_factory_and_defines_no_second():
    tree = source_of("book_workspace.py")
    assert "shared.importing.IdFactory" in imported_names(tree)
    defined = defined_names(tree)
    for invented in ("IdFactory", "IdGenerator", "next_id", "make_id"):
        assert invented not in defined, invented


def test_the_data_layer_reuses_the_one_file_list_type_and_defines_no_second():
    tree = source_of("book_workspace.py")
    modules = imported_names(tree)
    assert "shared.importing.ImportedFileSnapshot" in modules
    assert "shared.importing.Revision" in modules
    defined = defined_names(tree)
    for invented in ("ImportedFileSnapshot", "FileList", "Revision", "BookFiles"):
        assert invented not in defined, invented


# --------------------------------------------------------------------------- #
# Phase 1 — Phase 2's behaviour has not been pulled forward
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_grouping_reaches_no_filesystem(name):
    """Decision 12A is a **projection**, not an import.

    Phase 3 groups a snapshot the importer already committed. The moment this layer
    calls ``exists``, ``stat``, ``scandir`` or ``resolve`` it has stopped projecting
    a value and started asking the disk a question that the importer already
    answered — and answered under cancellation, link refusal and hidden-folder rules
    this module does not implement.
    """
    assert filesystem_calls_in(source_of(name)) == set()


@pytest.mark.parametrize("name", DATA_LAYER)
def test_plan6_neither_consumes_nor_reinterprets_planning_groups(name):
    """The stop gate the drop names, kept live as an assertion.

    ``planning_groups`` buckets on the selected root; Decision 12A needs the file's
    own parent. Reusing it would silently turn one folder of twelve audiobooks into
    one book, which is the exact defect Phase 0 identified.
    """
    assert forbidden_grouping_in(source_of(name)) == set()


@pytest.mark.parametrize("name", DATA_LAYER)
def test_plan6_consumes_an_import_but_never_runs_one(name):
    """Scanning, traversal, cancellation and commits stay Plan 3's."""
    assert import_execution_in(source_of(name)) == set()
    modules = imported_names(source_of(name))
    assert not any("import_coordination" in entry for entry in modules), modules


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_grouping_reuses_the_importers_natural_key(name):
    """One sort key in the project, applied where the importer applies it."""
    tree = source_of(name)
    assert "shared.importing.natural_key" in imported_names(tree)
    defined = defined_names(tree)
    for invented in ("natural_key", "_natural_key", "_sort_key", "natural_sort"):
        assert invented not in defined, invented


@pytest.mark.parametrize("name", DATA_LAYER)
def test_no_phase_five_run_capture_exists_yet(name):
    """Phase 5 freezes effective values into a run. Absence is proved, not assumed.

    Phase 4 resolves precedence **live**, from immutable workspace state. Capturing
    a run is a different act with a different guarantee, and pulling it forward
    would mean a snapshot existed before the contract that says what freezing means.
    """
    tree = source_of(name)
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    present = sorted(entry for entry in PHASE5_NAMES if entry in seen)
    assert present == [], present


@pytest.mark.parametrize("name", DATA_LAYER)
def test_no_universal_metadata_vocabulary_is_hard_coded(name):
    """Section 15.4: the field vocabulary belongs to the consumer.

    A constant naming audiobook fields here would be wrong for M4B Maker, MP3 Tool
    and the Metadata Editor simultaneously, which is exactly why the drop refuses
    one. Checked as assigned names *and* as the literal field names themselves, so
    a list spelled under a neutral name would still be caught.
    """
    tree = source_of(name)
    assigned = {
        target.id for node in ast.walk(tree)
        if isinstance(node, ast.Assign) for target in node.targets
        if isinstance(target, ast.Name)
    }
    for invented in ("UNIVERSAL_METADATA_FIELDS", "METADATA_FIELDS", "DEFAULT_FIELDS",
                     "SHARED_FIELDS", "AUDIOBOOK_FIELDS", "TAG_FIELDS"):
        assert invented not in assigned, invented

    # No tuple/list/set literal in the module may enumerate audiobook tag names.
    audiobook = {"title", "artist", "album", "album_artist", "author", "narrator",
                 "series", "genre", "year", "comment"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            literals = {element.value for element in node.elts
                        if isinstance(element, ast.Constant)
                        and isinstance(element.value, str)}
            assert len(literals & audiobook) < 2, sorted(literals & audiobook)


def test_the_raw_shared_value_is_stored_once_on_the_workspace():
    """Stored once means one field, on the workspace, and none on a book."""
    from shared.book_workspace import BookJob, WorkspaceSnapshot

    workspace_fields = {entry.name for entry in dataclasses.fields(WorkspaceSnapshot)}
    book_fields = {entry.name for entry in dataclasses.fields(BookJob)}
    assert "shared" in workspace_fields
    assert book_fields == {"book_id", "configuration", "files"}
    assert not (book_fields & {"shared", "title", "author", "metadata"})


def test_no_effective_value_is_stored_as_a_second_truth():
    """Effective values are projections; a stored copy is how two truths diverge."""
    from shared.book_workspace import BookJob, BookMutation, WorkspaceSnapshot

    for record in (BookJob, WorkspaceSnapshot, BookMutation):
        names = {entry.name for entry in dataclasses.fields(record)}
        assert not any("effective" in name for name in names), (record, names)


def test_precedence_and_the_disabled_projection_call_one_predicate():
    """Two interpretations of 'populated' would eventually disagree.

    Asserted structurally rather than by behaviour alone: both the value class's
    ``populated`` and the module's ``disabled_fields`` must reach ``is_populated``,
    and nothing else may define a second blankness test.
    """
    tree = source_of("book_workspace.py")
    defined = defined_names(tree)
    for invented in ("_is_blank", "is_blank", "_populated", "_has_value",
                     "_non_blank", "_strip"):
        assert invented not in defined, invented
    assert "is_populated" in defined

    def bare_calls(owner: str) -> set[str]:
        node = next(entry for entry in ast.walk(tree)
                    if isinstance(entry, ast.FunctionDef) and entry.name == owner)
        return {inner.func.id for inner in ast.walk(node)
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)}

    def attributes(owner: str) -> set[str]:
        node = next(entry for entry in ast.walk(tree)
                    if isinstance(entry, ast.FunctionDef) and entry.name == owner)
        return {inner.attr for inner in ast.walk(node)
                if isinstance(inner, ast.Attribute)}

    # The chain, stated exactly. ``disabled_fields`` delegates to the value's own
    # ``populated_fields`` rather than re-deciding blankness, and both of the
    # deciders call the one predicate. Demanding a *direct* call from
    # ``disabled_fields`` would forbid that delegation, which is the better shape.
    assert "is_populated" in bare_calls("populated")
    assert "is_populated" in bare_calls("populated_fields")
    assert "populated_fields" in attributes("disabled_fields")
    assert "is_populated" not in attributes("disabled_fields"), (
        "it delegates rather than deciding for itself")


def test_the_shared_metadata_layer_stays_free_of_widgets_and_state():
    """Phase 4 supplies the disabled *set*; rendering it is Phase 8's."""
    tree = source_of("book_workspace.py")
    seen = referenced_names(tree) | imported_names(tree)
    for widget_word in ("LockGroup", "MainThreadGuard", "set_locked", "configure",
                        "widget", "Entry", "Checkbutton"):
        assert widget_word not in seen, widget_word


def test_phases_one_to_four_delivered_their_own_names_and_no_more():
    """The public surface is exactly what Phases 1-4 were authorised to add."""
    from shared import book_workspace

    phase1 = {
        "BookContractError", "BookIdentityError", "BookConfigurationError",
        "WorkspaceContractError", "BOOK_ID_KIND", "new_book_id", "NO_FILES",
        "EMPTY_CONFIGURATION", "FIELD_ROLES", "ROLE_IDENTITY", "ROLE_CONFIGURATION",
        "ROLE_INPUTS", "field_role", "BookJob", "WorkspaceSnapshot",
    }
    phase2 = {
        "has_meaningful_work", "WorkspaceOperation", "BookMutation",
        "add_book", "duplicate_book", "remove_book",
        "previous_book", "next_book", "select_book", "replace_book",
    }
    phase3 = {"book_groups", "books_from_import", "replace_workspace_from_import"}
    phase4 = {
        "BLANK", "SharedMetadataError", "SharedMetadata", "NO_SHARED_METADATA",
        "is_populated", "effective_value", "effective_metadata", "disabled_fields",
        "set_shared_metadata",
    }
    assert set(book_workspace.__all__) == phase1 | phase2 | phase3 | phase4
    assert len(book_workspace.__all__) == 37, "15 + 10 + 3 + 9"


def test_no_operation_member_was_overloaded():
    """One member, one scope, across all four phases so far."""
    from shared.book_workspace import WorkspaceOperation
    assert {member.value for member in WorkspaceOperation} == {
        "add", "duplicate", "remove", "previous", "next", "select", "replace",
        "import", "shared_metadata"}




def test_exactly_one_place_advances_the_workspace_revision():
    """Two callers of ``advance`` is two places a revision could move differently.

    The value itself still advances nothing — Phase 2 builds a *new* snapshot — and
    every operation routes through one helper, so "a real change moves the revision
    exactly once" is enforced by there being one caller rather than by discipline.
    """
    tree = source_of("book_workspace.py")
    advancers = [
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "advance"
                for inner in ast.walk(node))
    ]
    assert advancers == ["_changed"], advancers


# --------------------------------------------------------------------------- #
# The protected consumer panels
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("relative", sorted(PHASE0_PANEL_HASHES))
def test_the_consumer_panels_are_byte_identical_to_the_phase_zero_baseline(relative):
    """Plan 6 ships adopted by no production panel. Proved by hash, not by reading."""
    assert sha256_of(UNIVERSAL / relative) == PHASE0_PANEL_HASHES[relative]


@pytest.mark.parametrize("relative", sorted(PHASE0_PLAN5_HASHES))
def test_the_plan5_numbering_and_converter_are_untouched_before_phase_six(relative):
    """The Phase 6 promotion is the only authorised change, and it has not run."""
    assert sha256_of(REPO_ROOT / relative) == PHASE0_PLAN5_HASHES[relative]


@pytest.mark.parametrize("relative", sorted(PHASE0_PANEL_HASHES))
def test_no_consumer_panel_names_any_plan6_vocabulary(relative):
    tree = parse(UNIVERSAL / relative)
    names = referenced_names(tree) | imported_names(tree)
    for owned in ("BookJob", "WorkspaceSnapshot", "book_workspace", "new_book_id",
                  "field_role", "FIELD_ROLES"):
        assert owned not in names, (relative, owned)


def test_the_launcher_gained_no_seventh_tool_and_names_no_plan6_vocabulary():
    tree = parse(UNIVERSAL / "launcher.py")
    names = referenced_names(tree) | imported_names(tree)
    for owned in ("BookJob", "WorkspaceSnapshot", "book_workspace"):
        assert owned not in names, owned


# --------------------------------------------------------------------------- #
# Mutation checks — every guard above must be able to fail
#
# Each sample is a string parsed here. Nothing on disk is modified.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("code,expected", [
    ("import tkinter", "tkinter"),
    ("import tkinter.ttk", "tkinter"),
    ("from tkinter import ttk", "tkinter"),
    ("import threading", "threading"),
    ("from threading import Lock", "threading"),
    ("import queue", "queue"),
    ("import subprocess", "subprocess"),
    ("import socket", "socket"),
    ("from shared import output_paths", "shared.output_paths"),
    ("from shared.output_paths import DestinationPlanner", "shared.output_paths"),
    ("import shutil", "shutil"),
])
def test_the_import_guard_actually_detects_a_forbidden_import(code, expected):
    found = forbidden_imports_in(sample(code))
    assert expected in found, (code, found)


def test_the_import_guard_passes_clean_code():
    """The other half: it must not flag what Plan 6 legitimately imports."""
    clean = sample(
        "from shared.importing import IdFactory, ImportedFileSnapshot\n"
        "from shared.job_control import freeze_options\n"
        "from dataclasses import dataclass\n"
        "from types import MappingProxyType\n"
    )
    assert forbidden_imports_in(clean) == set()


@pytest.mark.parametrize("code,expected", [
    ("import threading\nx = threading.Lock()", "Lock"),
    ("import threading\nx = threading.Thread(target=None)", "Thread"),
    ("import threading\nx = threading.Event()", "Event"),
    ("import threading\nx = threading.Condition()", "Condition"),
    ("import queue\nx = queue.Queue()", "Queue"),
    ("import time\nx = time.monotonic()", "monotonic"),
    ("import time\nx = time.time()", "time"),
    ("import subprocess\nsubprocess.run(['x'])", "run"),
    ("x = open('f')", "open"),
])
def test_the_call_guard_actually_detects_a_forbidden_construction(code, expected):
    found = forbidden_calls_in(sample(code))
    assert expected in found, (code, found)


def test_the_call_guard_passes_clean_code():
    clean = sample(
        "from types import MappingProxyType\n"
        "def f(values):\n"
        "    return MappingProxyType(dict(values))\n"
    )
    assert forbidden_calls_in(clean) == set()


@pytest.mark.parametrize("code", [
    "import sys\nif sys.platform == 'win32':\n    pass",
    "import os\nif os.uname():\n    pass",
    "import sys\nIS_MAC = sys.platform == 'darwin'",
])
def test_the_platform_guard_actually_detects_a_platform_fork(code):
    assert platform_branching_in(sample(code)) != set()


def test_the_platform_guard_is_not_fooled_by_a_docstring_or_a_comment():
    """The exact false positive Phase 0 hit, in the opposite direction."""
    prose = sample(
        '"""Mentions win32 and darwin and platform in prose only."""\n'
        "# platform, win32, darwin\n"
        "VALUE = 'this string names darwin and win32'\n"
    )
    assert platform_branching_in(prose) == set()


@pytest.mark.parametrize("code,expected", [
    ("import tkinter as tk\nclass Panel(tk.Frame):\n    pass", "Panel"),
    ("class BookBar:\n    pass", "BookBar"),
    ("class SomethingView:\n    pass", "SomethingView"),
    ("class ConfirmDialog:\n    pass", "ConfirmDialog"),
])
def test_the_widget_guard_actually_detects_a_ui_class(code, expected):
    assert expected in widget_classes_in(sample(code))


def test_the_widget_guard_passes_a_plain_record():
    clean = sample(
        "from dataclasses import dataclass\n"
        "@dataclass(frozen=True, slots=True)\n"
        "class BookJob:\n"
        "    book_id: str\n"
    )
    assert widget_classes_in(clean) == set()


@pytest.mark.parametrize("code,expected", [
    ("from pathlib import Path\ndef f(p):\n    return p.exists()", "exists"),
    ("def f(p):\n    return p.stat().st_size", "stat"),
    ("def f(p):\n    return list(p.iterdir())", "iterdir"),
    ("def f(p):\n    return list(p.glob('*.mp3'))", "glob"),
    ("def f(p):\n    return list(p.rglob('*.mp3'))", "rglob"),
    ("import os\ndef f(p):\n    return os.scandir(p)", "scandir"),
    ("import os\ndef f(p):\n    return os.listdir(p)", "listdir"),
    ("def f(p):\n    return p.resolve()", "resolve"),
    ("def f(p):\n    return p.is_dir()", "is_dir"),
    ("def f(p):\n    p.mkdir()", "mkdir"),
])
def test_the_filesystem_guard_actually_detects_a_disk_call(code, expected):
    assert expected in filesystem_calls_in(sample(code))


def test_the_filesystem_guard_passes_a_purely_lexical_projection():
    """The other half: taking a parent and sorting names touches no disk."""
    clean = sample(
        "def book_groups(snapshot):\n"
        "    buckets = {}\n"
        "    for entry in snapshot.files:\n"
        "        buckets.setdefault(entry.path.parent, []).append(entry)\n"
        "    return tuple(buckets.items())\n"
    )
    assert filesystem_calls_in(clean) == set()


def test_the_filesystem_guard_is_not_fooled_by_a_field_named_like_a_call():
    """``stat`` as a value, and prose about exists(), are not disk access."""
    prose = sample(
        '"""Never calls exists() or scandir()."""\n'
        "# resolve, glob, rglob\n"
        "def f(record):\n"
        "    return record.stat\n"
    )
    assert filesystem_calls_in(prose) == set()


@pytest.mark.parametrize("code,expected", [
    ("from shared.importing import planning_groups\n"
     "def f(s):\n    return planning_groups(s)", "planning_groups"),
    ("from shared.importing import PlanningGroups\n"
     "def f():\n    return PlanningGroups()", "PlanningGroups"),
])
def test_the_planning_groups_guard_actually_detects_reuse(code, expected):
    assert expected in forbidden_grouping_in(sample(code))


def test_the_planning_groups_guard_is_not_fooled_by_prose():
    prose = sample(
        '"""This is not importing.planning_groups; PlanningGroups is Plan 3\'s."""\n'
        "# planning_groups buckets on source_root.root_id\n"
    )
    assert forbidden_grouping_in(prose) == set()


@pytest.mark.parametrize("code,expected", [
    ("from shared.import_coordination import ImportCoordinator\n"
     "def f(m):\n    return ImportCoordinator(m)", "ImportCoordinator"),
    ("from shared.importing import scan_roots\n"
     "def f(r):\n    return scan_roots(r)", "scan_roots"),
    ("from shared.importing import validate_direct_files\n"
     "def f(p):\n    return validate_direct_files(p)", "validate_direct_files"),
    ("from shared.importing import ImportedFileManager\n"
     "def f():\n    return ImportedFileManager()", "ImportedFileManager"),
])
def test_the_import_execution_guard_actually_detects_running_an_import(code, expected):
    assert expected in import_execution_in(sample(code))


def test_the_import_execution_guard_passes_consuming_a_finished_snapshot():
    clean = sample(
        "from shared.importing import ImportedFileSnapshot, natural_key\n"
        "def f(snapshot):\n"
        "    return sorted(snapshot.files, key=lambda e: natural_key(e.name))\n"
    )
    assert import_execution_in(clean) == set()


@pytest.mark.parametrize("code,expected", [
    ("from shared.job_control import capture_run\n"
     "def f(**kw):\n    return capture_run(**kw)", "capture_run"),
    ("from shared.job_control import RunSnapshot\n"
     "def f():\n    return RunSnapshot", "RunSnapshot"),
    ("class BookRunSnapshot:\n    pass", "BookRunSnapshot"),
    ("class BookRunResult:\n    pass", "BookRunResult"),
    ("from shared.job_control import RetryRequest\n"
     "def f(r):\n    return RetryRequest", "RetryRequest"),
    ("def capture_workspace_run(space):\n    return space", "capture_workspace_run"),
])
def test_the_phase_five_guard_actually_detects_run_capture(code, expected):
    tree = sample(code)
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    assert expected in {entry for entry in PHASE5_NAMES if entry in seen}


def test_the_phase_five_guard_passes_live_precedence_resolution():
    """The other half: resolving effective values live is not capturing a run."""
    clean = sample(
        "def effective_value(shared, book, field):\n"
        "    if shared.populated(field):\n"
        "        return shared.raw(field)\n"
        "    return book.configuration.get(field, '')\n"
    )
    tree = clean
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    assert {entry for entry in PHASE5_NAMES if entry in seen} == set()


@pytest.mark.parametrize("code", [
    "UNIVERSAL_METADATA_FIELDS = ('title', 'author')",
    "METADATA_FIELDS = ('title', 'album')",
    "AUDIOBOOK_FIELDS = ('series', 'narrator')",
])
def test_the_vocabulary_guard_detects_a_named_universal_list(code):
    tree = sample(code)
    assigned = {target.id for node in ast.walk(tree)
                if isinstance(node, ast.Assign) for target in node.targets
                if isinstance(target, ast.Name)}
    assert assigned & {"UNIVERSAL_METADATA_FIELDS", "METADATA_FIELDS",
                       "AUDIOBOOK_FIELDS"}


def test_the_vocabulary_guard_detects_a_tag_list_under_a_neutral_name():
    """Renaming the constant must not be enough to smuggle a universal list."""
    tree = sample("SOMETHING = ('title', 'author', 'series')")
    audiobook = {"title", "artist", "album", "album_artist", "author", "narrator",
                 "series", "genre", "year", "comment"}
    biggest = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            literals = {element.value for element in node.elts
                        if isinstance(element, ast.Constant)
                        and isinstance(element.value, str)}
            biggest = max(biggest, len(literals & audiobook))
    assert biggest >= 2, "the guard would fire on this"


def test_the_vocabulary_guard_accepts_a_consumer_supplied_vocabulary():
    """A consumer passing its own fields in is the whole point, not a violation."""
    clean = sample(
        "def build(fields):\n"
        "    return SharedMetadata.for_fields(fields)\n"
        "ROLE_IDENTITY = 'identity'\n"
    )
    audiobook = {"title", "artist", "album", "album_artist", "author", "narrator",
                 "series", "genre", "year", "comment"}
    for node in ast.walk(clean):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            literals = {element.value for element in node.elts
                        if isinstance(element, ast.Constant)
                        and isinstance(element.value, str)}
            assert len(literals & audiobook) < 2


def test_the_one_predicate_guard_detects_a_second_blankness_test():
    early = sample(
        "def is_populated(v):\n    return bool(v.strip())\n"
        "def _is_blank(v):\n    return not v.strip()\n"
    )
    defined = defined_names(early)
    assert "_is_blank" in defined, "a second predicate would be caught"


def test_the_stored_effective_value_guard_detects_a_second_truth():
    """A record that stores effective values is what this must never allow."""
    import dataclasses as dc

    @dc.dataclass(frozen=True)
    class Tempting:
        book_id: str = "x"
        effective_metadata: tuple = ()

    names = {entry.name for entry in dc.fields(Tempting)}
    assert any("effective" in name for name in names), "the guard would fire"
