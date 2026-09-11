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

#: The pure data layer. Phase 8 adds ``book_workspace_ui.py``; it does not exist yet
#: and is not assumed here.
DATA_LAYER = ("book_workspace.py",)

#: Phase 6's promoted allocator. It is deliberately **not** in ``DATA_LAYER``: the
#: guard it answers to (``test_the_promoted_allocator_is_pure``) is stricter than
#: every DATA_LAYER guard combined — an import allowlist of exactly two stdlib names
#: forbids Tk, threading, subprocess, the filesystem and a clock by construction,
#: rather than one forbidden name at a time.
ALLOCATOR = "numbering.py"

#: The original Plan 5 allowlist, moved here with the implementation at Phase 6.
#: ``files/tests/test_m4b_numbering.py`` asserted exactly this against
#: ``mp3_tools/m4b_numbering.py`` while that file *was* the allocator.
ALLOCATOR_IMPORTS = {"__future__", "dataclasses"}

#: Also moved unchanged from the Plan 5 guard: vocabulary that would mean the
#: allocator had learned about the UI, the filesystem, a subprocess or the
#: Converter's plan objects. A counter that knows what a book is is not a counter.
ALLOCATOR_FORBIDDEN = (
    "Tk", "StringVar", "Path", "open", "run", "popen",
    "ConversionPlan", "SegmentPlan", "ItemPlan",
    "whole_book_tags", "segment_tags", "ffmpeg_cmd",
)

#: Phase 0 recorded these SHA-256 values as the byte-identity gates for the
#: consumer panels Plan 6 must not touch. A difference here means Plan 6 reached
#: somewhere it may not, and it is a stop gate rather than a value to update.
#:
#: **The MP3 Tool left this gate at the focused MP3 plan's Phase 4** — the one
#: supersession that plan records (its section 4: the protection is superseded
#: "for ``mp3_tool.py`` only"). Its Phase 0 digest is kept below as
#: :data:`MP3_TOOL_PHASE0_HASH` so the retirement is proved to be real rather
#: than assumed, and the two M4B panels stay exactly as protected as before.
PHASE0_PANEL_HASHES = {
    "mp3_tools/m4b_maker.py":
        "55774911516dd0b5b30d51c6a0b6d93ac62005d16fa1adb46e69f8b61e2b7d8d",
    "mp3_tools/m4b_metadata_editor.py":
        "310b27f6d46668782305b54434f5b9bd00f4611e077f6772f3410adb5ffdd180",
}

#: The MP3 Tool as Plan 6 Phase 0 found it, before the focused MP3 redesign
#: converted it. Evidence, not a gate: the panel is *required* to differ now.
MP3_TOOL_PHASE0_HASH = \
    "96c746a8a4defd9c495d66770b04e2f789a9a37957018c263e5f3371fe3984d5"

#: Recorded at Phase 0 and **still enforced**. The Converter is Plan 5's, it is the
#: consumer the promotion had to leave alone, and Phase 6 did not touch one byte of
#: it. A difference here is a stop gate, not a value to update.
PHASE0_PLAN5_HASHES = {
    "scripts/Universal/mp3_tools/m4b_converter.py":
        "a44418853b3f8e38f9f78829c2f388bc0cb85b29bf35dcbc64d7d5ec9ab60880",
}

#: Phase 0's hash of ``mp3_tools/m4b_numbering.py`` **while it was the allocator**.
#: Kept as the evidence that the file genuinely changed at Phase 6 rather than as a
#: gate: the promotion is the one authorised change to it, and it has now happened.
PHASE0_ALLOCATOR_HASH = \
    "a26cd25954c5ad21d16c350642025e768538c60f9df0475c71385191a9f9fb98"

#: NOTE. The four hashes above are **raw-byte** digests of files as git checks them
#: out in this repository (``core.autocrlf = true``, so CRLF on disk), and they are
#: the maintainer-supplied stop-gate values. They are deliberately left exactly as
#: recorded. The Phase 6 pins below are content digests instead — Phase 7's red proof
#: found them tripping on a fresh checkout's line endings alone, with identical
#: content, which is a gate failing for the wrong reason.
#:
#: The state the authorised Phase 6 promotion left behind, pinned so that any
#: *later* change to the shim, the promoted allocator or the Plan 5 regression suite
#: has to be a deliberate act rather than a quiet one. The maintainer's Phase 6
#: ruling authorised exactly one narrowly scoped edit to ``test_m4b_numbering.py``
#: (its obsolete standalone-module purity assertion, replaced by a stricter one);
#: these values close that authorisation again behind it.
PHASE6_PROMOTION_HASHES = {
    "scripts/Universal/shared/numbering.py":
        "a959b6d7892f4b79f404fad4cc2f0dd6cec19ade493eb3eb2002c9d7c907a59b",
    "scripts/Universal/mp3_tools/m4b_numbering.py":
        "628183f668cc0501a62a759659d11708ecc3933a4b433dacfe6a0f7cd088b7f9",
    "files/tests/test_m4b_numbering.py":
        "cf9f48a0d8d25e922921138e82ca0783c67eed74b0e47f266f80171f1c46069f",
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

#: Phase 6 delivered numbering — in ``shared/numbering.py``, and nowhere else. The
#: success counter is deliberately NOT part of the frozen data layer: a counter is a
#: fact about one attempt's execution, and a plan is the opposite, which is what
#: keeps the snapshot retry-stable. Phase 6 *shipping* the allocator did not relax
#: that; it is the reason the list below still has a job.
PHASE6_NAMES = (
    "SuccessNumbers", "Tentative", "NumberingError", "m4b_numbering",
    "propose", "next_number", "consumed", "START_NUMBER", "start_number",
)

#: The five book-level answers Phase 7 delivered, in declaration order. Stated here
#: so the guard and the enum cannot drift; a sixth would need this line changed
#: deliberately, which is the point.
BOOK_DISPOSITIONS = (
    "SUCCEEDED", "FAILED", "SKIPPED_EMPTY", "SKIPPED_INVALID", "NOT_ATTEMPTED",
)

#: Phase 8 owns the Tk adapter and the manual harness. The data layer stays Tk-free,
#: thread-free and theme-free until then, and it is proved rather than assumed. This
#: replaces the Phase-7-absence list Phase 7 itself made obsolete.
PHASE8_NAMES = (
    "tkinter", "tk", "ttk", "Tk", "Toplevel", "Frame", "Widget", "StringVar",
    "MainThreadGuard", "MainThreadPump", "LockGroup", "style_name",
    "style_tk_widget", "ui_theme", "job_ui", "BookNavigator",
    "SharedMetadataSurface", "book_workspace_ui", "manual_plan6_harness",
)


def source_of(relative: str):
    return parse(SHARED / relative)


def sample(code: str) -> ast.Module:
    """Parse a synthetic module owned by this test, for mutation-checking a guard."""
    return ast.parse(code)


#: Line-ending constants, spelled once so the guard below never has to embed a
#: literal carriage return in its own source.
CRLF = bytes((13, 10))
LF = bytes((10,))


def sha256_of(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_normalised(path) -> str:
    """Content hash with line endings normalised to LF.

    ``core.autocrlf`` is ``true`` in this repository, so a file's bytes on disk
    depend on whether git checked it out (CRLF) or a tool wrote it (LF). Phase 7's
    red proof caught the Phase 6 pins failing in a fresh worktree for exactly that
    reason and nothing else — the content was identical. A gate that fires on a
    checkout convention is a gate nobody can trust, so the promoted-state pins
    compare content. They still detect any real change; the recorded digests did
    not need to move, because the files they name are LF in this tree already.
    """
    raw = path.read_bytes()
    return hashlib.sha256(raw.replace(CRLF, LF)).hexdigest()


def one_declaration(tree: ast.Module, name: str):
    """The single class or function of that name, at any depth. Never two.

    Two declarations sharing a name is itself worth failing on: a guard that
    silently inspected the first would be inspecting the wrong one.
    """
    found = [node for node in ast.walk(tree)
             if isinstance(node, (ast.ClassDef, ast.FunctionDef,
                                  ast.AsyncFunctionDef)) and node.name == name]
    assert len(found) == 1, f"expected exactly one {name!r}, found {len(found)}"
    return found[0]


def one_function(tree: ast.Module, name: str):
    """As above, but it must be a function or method rather than a class."""
    node = one_declaration(tree, name)
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)), name
    return node


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




def import_roots_in(tree: ast.Module) -> set[str]:
    """Every top-level package this module depends on.

    The Plan 5 purity guard's own shape, moved here with the allocator. Relative
    imports are rejected outright rather than counted: ``from ..shared import x``
    has no root to compare, and would hide the dependency from this allowlist.
    """
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "absolute imports only"
            roots.add((node.module or "").split(".")[0])
    return roots


def import_sources_in(tree: ast.Module) -> dict[str, set[str]]:
    """Dotted module path -> the names taken from it. Full path, not just the root.

    ``{"shared"}`` would license a dependency on any shared module; the shim is
    allowed exactly ``shared.numbering``, so the guard has to see the whole path.
    """
    sources: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                sources.setdefault(alias.name, set())
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "absolute imports only"
            sources.setdefault(node.module or "", set()).update(
                alias.name for alias in node.names)
    return sources


def top_level_declarations_in(tree: ast.Module) -> set[str]:
    """Only the module's own classes and functions, not their methods.

    ``defined_names`` walks the whole tree — which is what the re-export guard
    wants, because a class hidden inside a factory is still a second
    implementation. This is the other question: what does this module *offer*.
    """
    return {node.name for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef))}


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
def test_capture_goes_through_the_existing_plan3_capture_run(name):
    """Phase 5 composes Plan 3 snapshots; it does not build them.

    Constructing a ``RunSnapshot`` directly would look shorter and would quietly
    bypass the one place a live payload can be turned away, because ``capture_run``
    is what deep-freezes ``tool_options`` and duck-types the imported list.
    """
    tree = source_of(name)
    assert "shared.job_control.capture_run" in imported_names(tree)
    assert "capture_run" in constructed_names(tree)
    # The type is named for annotations and isinstance checks, never instantiated.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "RunSnapshot", "RunSnapshot is composed, not built"


@pytest.mark.parametrize("name", DATA_LAYER)
def test_no_second_run_snapshot_or_freeze_is_defined(name):
    """One snapshot type, one freeze, one id scheme."""
    defined = defined_names(source_of(name))
    for invented in ("RunSnapshot", "capture_run", "freeze_options", "_freeze_value",
                     "RunOptions", "FrozenRun", "WorkspaceRunSnapshot"):
        assert invented not in defined, invented


@pytest.mark.parametrize("name", DATA_LAYER)
def test_phase_five_builds_no_controller_and_no_event_stream(name):
    """Drop section 16: one JobController per run, and the consumer owns it."""
    tree = source_of(name)
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    for owned_elsewhere in ("JobController", "JobReporter", "JobEventStream",
                            "JobEvent", "LoggerBridge", "EtaEstimator",
                            "ProgressTracker", "JobAdapter", "MainThreadPump"):
        assert owned_elsewhere not in seen, owned_elsewhere


@pytest.mark.parametrize("name", DATA_LAYER)
def test_the_frozen_data_layer_still_holds_no_success_counter(name):
    """Phase 6 shipped the allocator; the data layer still must not name it.

    Before Phase 6 this was an absence guard — numbering did not exist yet. It is
    now the opposite kind of claim and a stronger one: the allocator *does* exist,
    one import away, and ``book_workspace.py`` still refuses it. A success counter
    is a fact about one attempt's execution; a frozen plan is the opposite, and
    keeping the counter out is what lets a snapshot stay retry-stable.
    """
    tree = source_of(name)
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    present = sorted(entry for entry in PHASE6_NAMES if entry in seen)
    assert present == [], present


# --------------------------------------------------------------------------- #
# Phase 6 — the promotion (drop section 17.1)
#
# The allocator that was ``mp3_tools/m4b_numbering.py`` is now
# ``shared/numbering.py``, with the old path left as a compatibility re-export so
# the M4B Converter's import keeps working. The contract is that this is a MOVE:
# one implementation with two spellings, never two implementations.
# --------------------------------------------------------------------------- #


def test_the_promoted_allocator_is_pure():
    """The original Plan 5 purity property, moved here with the implementation.

    ``files/tests/test_m4b_numbering.py`` asserted exactly this — import roots
    within ``{"__future__", "dataclasses"}``, and none of the forbidden
    integration vocabulary — for as long as ``mp3_tools/m4b_numbering.py`` was the
    allocator. Phase 6 moved the allocator, so the property moved with it. It was
    **not** retired, and it was not weakened: the same allowlist and the same
    forbidden list, now pointed at the file that actually implements the counter.
    """
    tree = parse(SHARED / ALLOCATOR)

    assert import_roots_in(tree) <= ALLOCATOR_IMPORTS, import_roots_in(tree)

    named = referenced_names(tree)
    for forbidden in ALLOCATOR_FORBIDDEN:
        assert forbidden not in named, forbidden


def test_the_promoted_allocator_knows_nothing_about_plan6():
    """It is handed an integer. Numbering must not learn what a book is."""
    tree = parse(SHARED / ALLOCATOR)
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    for owned in ("BookJob", "WorkspaceSnapshot", "BookRunSnapshot", "book_workspace",
                  "SharedMetadata", "RunSnapshot", "capture_run", "book_id"):
        assert owned not in seen, owned


def test_the_allocator_declares_exactly_the_three_promoted_names():
    """Three declarations moved, and nothing was invented on the way across.

    ``shared/numbering.py`` has no ``__all__`` because the file it was moved from
    had none: the promotion changed the module docstring and nothing else. The
    shim, which is a new file, does declare one.
    """
    from mp3_tools import m4b_numbering

    promoted = {"NumberingError", "Tentative", "SuccessNumbers"}
    assert top_level_declarations_in(parse(SHARED / ALLOCATOR)) == promoted
    assert list(m4b_numbering.__all__) == ["NumberingError", "Tentative",
                                           "SuccessNumbers"]


def test_the_legacy_path_is_a_re_export_and_not_a_second_implementation():
    """A wrapper or a subclass would be a fork with a shared docstring."""
    tree = parse(UNIVERSAL / "mp3_tools/m4b_numbering.py")

    assert defined_names(tree) == set(), defined_names(tree)
    sources = import_sources_in(tree)

    # Exactly ``shared.numbering`` — the module, not merely the ``shared`` root,
    # which would have licensed a dependency on any shared module at all.
    assert set(sources) == {"__future__", "shared.numbering"}, sources
    assert sources["shared.numbering"] == {
        "NumberingError", "Tentative", "SuccessNumbers"}, sources


def test_both_import_paths_reach_the_very_same_objects():
    from mp3_tools import m4b_numbering
    from shared import numbering

    for name in ("NumberingError", "Tentative", "SuccessNumbers"):
        assert getattr(m4b_numbering, name) is getattr(numbering, name), name


def test_the_promotion_changed_the_legacy_file_and_left_the_converter_alone():
    """The move happened, and it stopped exactly where it was authorised to stop."""
    legacy = sha256_normalised(UNIVERSAL / "mp3_tools/m4b_numbering.py")
    assert legacy != PHASE0_ALLOCATOR_HASH, "the promotion did not happen"
    assert (sha256_of(UNIVERSAL / "mp3_tools/m4b_converter.py")
            == PHASE0_PLAN5_HASHES["scripts/Universal/mp3_tools/m4b_converter.py"])


@pytest.mark.parametrize("relative", sorted(PHASE6_PROMOTION_HASHES))
def test_the_promoted_state_is_pinned_where_the_promotion_left_it(relative):
    """Re-closes the maintainer's one-time authorisation behind the change.

    Content, not raw bytes — see :func:`sha256_normalised`.
    """
    assert sha256_normalised(REPO_ROOT / relative) == PHASE6_PROMOTION_HASHES[relative]


# --------------------------------------------------------------------------- #
# Phase 7 — dispositions, result composition and retry (drop section 18)
#
# The Phase-7-absence guard that stood here has been replaced by the contracts
# that phase actually has to keep. The absence it protected has moved forward to
# Phase 8 below; it was not deleted.
# --------------------------------------------------------------------------- #


def test_the_book_disposition_is_the_one_book_level_vocabulary():
    from shared.book_workspace import BookDisposition

    assert [member.name for member in BookDisposition] == list(BOOK_DISPOSITIONS)
    tree = source_of("book_workspace.py")
    enums = {node.name for node in ast.walk(tree)
             if isinstance(node, ast.ClassDef)
             and any(ast.unparse(base) == "Enum" for base in node.bases)}
    # WorkspaceOperation is Phase 2's, and BookDisposition is Phase 7's. A third
    # book-outcome enum would be a second answer to the same question.
    assert enums == {"WorkspaceOperation", "BookDisposition"}, enums


def test_plan3_item_status_was_not_widened_or_reused_as_a_book_vocabulary():
    """Plan 3's three answers stay three; a BookJob is not a Plan 3 item."""
    from shared.job_control import ItemStatus

    assert [member.name for member in ItemStatus] == [
        "SUCCEEDED", "FAILED", "NOT_ATTEMPTED"]
    assert not hasattr(ItemStatus, "SKIPPED")

    tree = source_of("book_workspace.py")
    seen = referenced_names(tree) | imported_names(tree)
    assert "ItemStatus" not in seen, "the book layer must not lean on the item one"
    assert "ItemOutcome" not in seen


def test_the_skip_reason_is_frozen_at_capture_and_never_re_derived():
    """Section 16: after capture the run never consults the workspace again."""
    tree = source_of("book_workspace.py")
    capture = one_function(tree, "capture_workspace_run")

    # It names the two skip reasons itself, at the moment it classifies.
    named = referenced_names(capture)
    assert "SKIPPED_EMPTY" in named and "SKIPPED_INVALID" in named

    # And the derivation that reads them never goes back to a WorkspaceSnapshot.
    for owner in ("disposition_for", "dispositions", "retryable_book_ids"):
        node = one_function(tree, owner)
        live = referenced_names(node) | constructed_names(node)
        for forbidden in ("WorkspaceSnapshot", "books", "is_empty", "is_valid",
                          "capture_workspace_run", "capture_run"):
            assert forbidden not in live, (owner, forbidden)


def test_there_is_one_stored_truth_about_the_skipped_books():
    from shared.book_workspace import BookRunSnapshot

    stored = {entry.name for entry in dataclasses.fields(BookRunSnapshot)}
    assert stored == {"runs", "skipped", "shared"}
    assert "skipped_book_ids" not in stored, "a second stored truth"
    assert isinstance(BookRunSnapshot.__dict__["skipped_book_ids"], property)
    assert isinstance(BookRunSnapshot.__dict__["skipped_count"], property)


def test_the_result_composes_plan3_values_rather_than_replacing_them():
    from shared import book_workspace
    from shared import job_control
    from shared.book_workspace import WorkspaceRunResult

    assert book_workspace.RunResult is job_control.RunResult
    assert book_workspace.RetryRequest is job_control.RetryRequest
    assert book_workspace.JobState is job_control.JobState

    stored = {entry.name for entry in dataclasses.fields(WorkspaceRunResult)}
    assert stored == {"snapshot", "results", "state"}

    tree = source_of("book_workspace.py")
    declared = defined_names(tree)
    for invented in ("BookRunResult", "BookItemResult", "BookFailureLog",
                     "BookFailureRecord", "WorkspaceFailureRecord", "WorkspaceState",
                     "BookRetryRequest", "WorkspaceRetryRequest", "RetryManager",
                     "RetryController", "ResultRegistry", "FailureRegistry"):
        assert invented not in declared, invented


def test_the_result_layer_constructs_no_plan3_value_it_should_be_handed():
    """Settling and retrying are Plan 3's; Plan 6 receives what they produce."""
    tree = source_of("book_workspace.py")
    for owner in ("WorkspaceRunResult", "retry_failed_books"):
        node = one_declaration(tree, owner)
        built = constructed_names(node)
        for plan3 in ("RunResult", "RetryRequest", "FailureLog", "FailureRecord",
                      "RunSnapshot", "settle", "from_failures"):
            assert plan3 not in built, (owner, plan3)


def test_retry_delegates_to_run_result_retry():
    tree = source_of("book_workspace.py")
    node = one_function(tree, "retry_failed_books")
    assert "retry" in constructed_names(node), "it must call the Plan 3 method"


def test_retry_availability_delegates_to_plan3_is_available():
    tree = source_of("book_workspace.py")
    node = one_function(tree, "can_retry_failed")
    assert "is_available" in constructed_names(node)
    assert "shared.job_control.is_available" in imported_names(tree)
    # The action/state table itself is never restated here.
    assert "_ACTION_STATES" not in referenced_names(tree)


def test_retry_reads_nothing_live_and_captures_nothing():
    tree = source_of("book_workspace.py")
    node = one_function(tree, "retry_failed_books")

    parameters = {arg.arg for arg in node.args.args} | {
        arg.arg for arg in node.args.kwonlyargs}
    assert parameters == {"result"}, parameters

    called = constructed_names(node)
    for forbidden in ("capture_run", "capture_workspace_run", "SuccessNumbers",
                      "JobController", "Thread", "Popen", "open", "mkdir",
                      "propose", "commit", "next_id"):
        assert forbidden not in called, forbidden

    named = referenced_names(node)
    for live in ("WorkspaceSnapshot", "IdFactory", "books", "is_valid"):
        assert live not in named, live


def test_the_retry_path_never_reaches_the_allocator():
    """Phase 6 put the counter in the consumer's execution state. It stays there."""
    tree = source_of("book_workspace.py")
    modules = imported_names(tree)
    assert "shared.numbering" not in modules
    assert not any(entry.split(".")[-1] == "numbering" for entry in modules), modules
    seen = referenced_names(tree) | defined_names(tree) | modules
    for allocator in ("SuccessNumbers", "Tentative", "NumberingError", "propose",
                      "next_number", "consumed"):
        assert allocator not in seen, allocator


def test_no_controller_or_event_stream_is_built_here():
    tree = source_of("book_workspace.py")
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    for owned_elsewhere in ("JobController", "JobReporter", "JobEventStream",
                            "JobEvent", "LoggerBridge", "EtaEstimator",
                            "ProgressTracker", "JobAdapter", "MainThreadPump"):
        assert owned_elsewhere not in seen, owned_elsewhere


def test_the_counts_are_derived_and_stored_nowhere():
    from shared.book_workspace import WorkspaceRunResult

    stored = {entry.name for entry in dataclasses.fields(WorkspaceRunResult)}
    for derived in ("counts", "dispositions", "succeeded_count", "failed_count",
                    "skipped_empty_count", "skipped_invalid_count",
                    "not_attempted_count", "retryable_book_ids", "has_retryable",
                    "can_retry_failed"):
        assert derived not in stored, derived
        assert isinstance(WorkspaceRunResult.__dict__[derived], property), derived


# --------------------------------------------------------------------------- #
# Phase 8 — the one Tk adapter, and the harness (drop section 19)
#
# Where the Phase-8-absence guard stood. The absence became a presence, so the
# guard became an ownership contract rather than being deleted: the data layer's
# Tk-freedom is now the *stronger* claim, because the adapter exists one import
# away and book_workspace.py still refuses it.
# --------------------------------------------------------------------------- #

#: The one Plan 6 Tk adapter. There is no second, and Phase 9 adds none.
ADAPTER = "book_workspace_ui.py"

#: The developer-only harness. Production must not be able to reach it.
HARNESS = "manual_plan6_harness.py"


def adapter_tree() -> ast.Module:
    return parse(SHARED / ADAPTER)


@pytest.mark.parametrize("name", DATA_LAYER + (ALLOCATOR,))
def test_the_model_layer_still_names_no_adapter_vocabulary(name):
    """Now the stronger claim: the adapter EXISTS, and the model still refuses it."""
    tree = parse(SHARED / name)
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    present = sorted(entry for entry in PHASE8_NAMES if entry in seen)
    assert present == [], (name, present)


@pytest.mark.parametrize("name", DATA_LAYER + (ALLOCATOR,))
def test_no_model_module_imports_the_adapter(name):
    """The dependency runs one way. A model that imported its own UI is a cycle."""
    modules = imported_names(parse(SHARED / name))
    assert "shared.book_workspace_ui" not in modules, name
    assert not any(entry.split(".")[-1] == "book_workspace_ui" for entry in modules)


def test_there_is_exactly_one_plan6_tk_adapter():
    """One module may touch Tk, and a second would be a second place to fix a bug."""
    touching = sorted(
        path.name for path in SHARED.glob("*.py")
        if any(entry.split(".")[0] == "tkinter"
               for entry in imported_names(parse(path))))
    assert ADAPTER in touching
    plan6 = {ADAPTER, *DATA_LAYER, ALLOCATOR}
    assert [name for name in touching if name in plan6] == [ADAPTER], touching


def test_the_adapter_reaches_no_disk_process_network_or_output_service():
    tree = adapter_tree()
    modules = imported_names(tree)
    for banned in ("os", "os.path", "pathlib", "subprocess", "shutil", "socket",
                   "urllib", "http", "requests", "threading", "queue", "asyncio",
                   "multiprocessing", "time", "datetime",
                   "shared.output_paths", "shared.paths"):
        assert banned not in modules, banned
    forbidden = {
        "sanitize_component", "sanitize_relative", "DestinationPlanner",
        "reserve_run_directory", "ensure_output_base", "plan_flat", "plan_mirrored",
        "RunReservation", "numbered_variant",
    }
    assert referenced_names(tree) & forbidden == set()


def test_the_adapter_opens_no_second_after_chain_and_starts_no_thread():
    tree = adapter_tree()
    called = constructed_names(tree)
    for scheduled in ("after", "after_idle", "after_cancel", "update",
                      "update_idletasks", "mainloop", "sleep", "Thread", "Timer",
                      "Queue", "Event", "monotonic", "perf_counter"):
        assert scheduled not in called, scheduled
    seen = referenced_names(tree) | imported_names(tree)
    assert "MainThreadPump" not in seen, "Plan 3 owns the one callback chain"


def test_the_adapter_contains_no_platform_branch():
    tree = adapter_tree()
    assert platform_branching_in(tree) - {"name"} == set(), platform_branching_in(tree)
    modules = imported_names(tree)
    assert "sys" not in modules and "platform" not in modules


def test_the_adapter_declares_no_theme_literal_or_token():
    """Drop section 19: no new colour, metric or font. Not even a hex literal."""
    tree = adapter_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not node.value.startswith("#"), node.value
    seen = referenced_names(tree)
    for token in ("colors", "fonts", "metrics", "palette", "shared_bg"):
        assert token not in seen, token
    # And no Windows-only bundle key is subscripted, which is what KeyErrors on aqua.
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            spelled = ast.unparse(node)
            for windows_only in ("metrics", "styles", "fonts", "colors"):
                assert windows_only not in spelled, spelled


def test_the_adapter_runs_nothing_the_later_phases_own():
    """It renders the finished model. It captures, numbers and retries nothing."""
    tree = adapter_tree()
    seen = referenced_names(tree) | imported_names(tree) | defined_names(tree)
    for owned_elsewhere in ("capture_workspace_run", "capture_run", "RunSnapshot",
                            "BookRunSnapshot", "WorkspaceRunResult", "RunResult",
                            "RetryRequest", "retry_failed_books", "BookDisposition",
                            "SuccessNumbers", "Tentative", "NumberingError",
                            "JobController", "JobState", "is_locked"):
        assert owned_elsewhere not in seen, owned_elsewhere


def test_the_adapter_reimplements_no_model_projection():
    """It may call a pure projection. It may not grow its own copy of one."""
    tree = adapter_tree()
    declared = defined_names(tree)
    for model_owned in ("has_meaningful_work", "disabled_fields", "effective_value",
                        "effective_metadata", "is_populated", "add_book",
                        "duplicate_book", "remove_book", "previous_book",
                        "next_book", "select_book", "replace_book",
                        "set_shared_metadata", "book_groups", "new_book_id"):
        assert model_owned not in declared, model_owned
    called = constructed_names(tree)
    assert "has_meaningful_work" in called, "Decision 50A is asked, not re-decided"
    assert "disabled_fields" in called, "Decision 20B is asked, not re-decided"


def test_the_adapter_mutates_nothing_and_mints_no_identity():
    tree = adapter_tree()
    built = constructed_names(tree)
    for owned_by_the_model in ("BookMutation", "WorkspaceSnapshot", "BookJob",
                               "SharedMetadata", "IdFactory", "new_book_id",
                               "next_id", "add_book", "duplicate_book",
                               "remove_book", "previous_book", "next_book",
                               "select_book", "replace_book", "set_shared_metadata"):
        assert owned_by_the_model not in built, owned_by_the_model


def test_the_adapter_hard_codes_no_universal_metadata_vocabulary():
    tree = adapter_tree()
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for universal in ("title", "author", "narrator", "series", "album", "genre",
                      "album_artist", "year", "comment", "series_index"):
        assert universal not in literals, universal


def test_the_adapter_recreates_no_plan3_widget():
    tree = adapter_tree()
    seen = defined_names(tree) | referenced_names(tree)
    for plan3 in ("ImportedFileList", "ImportOptionsBar", "ImportStatusBar",
                  "ImportAdapter", "JobControlBar", "JobStatusView",
                  "SummaryDetailsView", "JobAdapter", "ProgressIndicator",
                  "JobEventStream", "JobReporter", "EtaEstimator", "LoggerBridge"):
        assert plan3 not in seen, plan3


def test_no_component_subclasses_a_widget_or_a_universal_base_panel():
    tree = adapter_tree()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            spelled = ast.unparse(base)
            for widget in ("Frame", "Labelframe", "Widget", "Panel", "Toplevel"):
                assert widget not in spelled, (node.name, spelled)


def test_phases_one_to_eight_delivered_their_own_names_and_no_more():
    """Phase 8 added a module, and nothing at all to the model's surface."""
    from shared import book_workspace, book_workspace_ui

    assert len(book_workspace.__all__) == 45, "Phase 8 adds no model name"
    assert book_workspace_ui.__all__ == [
        "BookWorkspaceUiError", "BookNavigator", "SharedMetadataSurface"]
    tree = adapter_tree()
    public = {node.name for node in tree.body
              if isinstance(node, ast.ClassDef) and not node.name.startswith("_")}
    assert public == set(book_workspace_ui.__all__), public


# --------------------------------------------------------------------------- #
# The harness is a developer tool, and provably out of the product
# --------------------------------------------------------------------------- #


def test_the_manual_harness_exists_and_is_directly_runnable():
    path = REPO_ROOT / "files" / "tests" / HARNESS
    assert path.is_file()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    guards = [node for node in tree.body
              if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test)]
    assert guards, "a manual harness needs a real entry point"
    assert "main" in {node.name for node in tree.body
                      if isinstance(node, ast.FunctionDef)}


def test_nothing_under_scripts_imports_the_manual_harness():
    stem = HARNESS.removesuffix(".py")
    for path in UNIVERSAL.rglob("*.py"):
        modules = imported_names(parse(path))
        assert not any(entry.split(".")[-1] == stem for entry in modules), path


def test_the_launcher_does_not_reference_the_harness_or_the_adapter():
    tree = parse(UNIVERSAL / "launcher.py")
    seen = referenced_names(tree) | imported_names(tree)
    for name in (HARNESS.removesuffix(".py"), "book_workspace_ui", "BookNavigator",
                 "SharedMetadataSurface"):
        assert not any(name == entry.split(".")[-1] for entry in seen), name


def test_the_launcher_tool_registry_is_still_exactly_six():
    tree = parse(UNIVERSAL / "launcher.py")
    for node in ast.walk(tree):
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        if any(isinstance(target, ast.Name) and target.id == "TOOLS"
               for target in targets):
            assert isinstance(node.value, (ast.List, ast.Tuple))
            assert len(node.value.elts) == 6, "Plan 6 adds no tool"


def test_the_harness_is_not_collected_by_pytest():
    """Its name is not ``test_*`` and it declares no test function."""
    assert not HARNESS.startswith("test_")
    tree = ast.parse(
        (REPO_ROOT / "files" / "tests" / HARNESS).read_text(encoding="utf-8"))
    named = {node.name for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    assert not any(name.startswith(("test_", "Test")) for name in named), named


def test_the_harness_lives_outside_the_shipped_tree():
    """The release archives are built from ``scripts/``; this is under ``files/``."""
    path = REPO_ROOT / "files" / "tests" / HARNESS
    assert (REPO_ROOT / "files") in path.parents
    assert UNIVERSAL not in path.parents
    assert not (UNIVERSAL / HARNESS).exists()


def test_the_harness_touches_no_disk_or_process():
    tree = ast.parse(
        (REPO_ROOT / "files" / "tests" / HARNESS).read_text(encoding="utf-8"))
    called = constructed_names(tree)
    for forbidden in ("Popen", "run", "check_output", "system", "mkdir", "makedirs",
                      "rmtree", "unlink", "touch", "write_text", "write_bytes",
                      "urlopen", "socket", "sleep", "Thread"):
        assert forbidden not in called, forbidden
    modules = imported_names(tree)
    for banned in ("subprocess", "shutil", "socket", "urllib", "requests",
                   "threading", "time", "tempfile"):
        assert banned not in modules, banned


def test_the_harness_drives_the_production_model_and_adapter():
    """It demonstrates the real thing; a harness over a stub proves nothing."""
    tree = ast.parse(
        (REPO_ROOT / "files" / "tests" / HARNESS).read_text(encoding="utf-8"))
    modules = imported_names(tree)
    assert "shared.book_workspace_ui" in modules
    assert "shared.book_workspace" in modules
    seen = referenced_names(tree)
    for real in ("BookNavigator", "SharedMetadataSurface", "add_book",
                 "duplicate_book", "remove_book", "previous_book", "next_book",
                 "select_book", "set_shared_metadata", "has_meaningful_work",
                 "ask_confirm"):
        assert real in seen, real


def test_the_harness_owns_its_own_field_vocabulary():
    """Example field names live in the consumer, never in the adapter."""
    harness = ast.parse(
        (REPO_ROOT / "files" / "tests" / HARNESS).read_text(encoding="utf-8"))
    literals = {node.value for node in ast.walk(harness)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert {"title", "author"} <= literals, "the consumer declares them"
    adapter = {node.value for node in ast.walk(adapter_tree())
               if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not ({"title", "author", "narrator"} & adapter), "and the adapter does not"


def test_the_confirmation_policy_lives_in_the_harness_not_the_adapter():
    """Decision 50A, split: the model answers, the consumer decides, the UI routes."""
    harness = ast.parse(
        (REPO_ROOT / "files" / "tests" / HARNESS).read_text(encoding="utf-8"))
    assert "ask_confirm" in constructed_names(harness)
    assert "ask_confirm" not in referenced_names(adapter_tree())


# --- mutation checks for the Phase 8 guards -------------------------------- #


@pytest.mark.parametrize("code,expected", [
    ("import tkinter as tk\ndef f():\n    return tk.Tk()", "tkinter"),
    ("from shared.job_ui import MainThreadGuard\n"
     "class P:\n    guard = MainThreadGuard", "MainThreadGuard"),
    ("from shared import ui_theme\ndef f():\n    return ui_theme", "ui_theme"),
    ("class BookNavigator:\n    pass", "BookNavigator"),
])
def test_the_model_purity_guard_actually_detects_adapter_vocabulary(code, expected):
    tree = sample(code)
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    assert expected in {entry for entry in PHASE8_NAMES if entry in seen}


def test_the_model_purity_guard_passes_a_pure_value_layer():
    clean = sample(
        "from shared.job_control import freeze_options\n"
        "def options(book, shared):\n"
        "    return freeze_options(dict(book.configuration))\n")
    seen = defined_names(clean) | referenced_names(clean) | imported_names(clean)
    assert {entry for entry in PHASE8_NAMES if entry in seen} == set()


@pytest.mark.parametrize("code", [
    'STYLE = "#1e1e1e"\n',
    'def f(theme):\n    return theme["metrics"]["gap_md"]\n',
    'def f(theme):\n    return theme["styles"]["shared_label"]\n',
])
def test_the_theme_literal_guard_actually_detects_a_new_token(code):
    tree = sample(code)
    hexes = [node.value for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and node.value.startswith("#")]
    subscripts = [ast.unparse(node) for node in ast.walk(tree)
                  if isinstance(node, ast.Subscript)
                  and any(key in ast.unparse(node)
                          for key in ("metrics", "styles", "fonts", "colors"))]
    assert hexes or subscripts, code


def test_the_theme_literal_guard_passes_the_sanctioned_lookup():
    clean = sample(
        "from shared.job_ui import style_name\n"
        "def f(theme):\n    return style_name(theme, 'shared_label')\n")
    hexes = [node.value for node in ast.walk(clean)
             if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and node.value.startswith("#")]
    assert hexes == []
    assert [node for node in ast.walk(clean) if isinstance(node, ast.Subscript)] == []


@pytest.mark.parametrize("code,expected", [
    ("class Navigator(ttk.Frame):\n    pass", "Frame"),
    ("class Surface(ttk.Labelframe):\n    pass", "Labelframe"),
    ("class Panel(BasePanel):\n    pass", "Panel"),
])
def test_the_composition_guard_actually_detects_a_subclass(code, expected):
    tree = sample(code)
    found = [ast.unparse(base) for node in ast.walk(tree)
             if isinstance(node, ast.ClassDef) for base in node.bases]
    assert any(expected in spelled for spelled in found), found


def test_the_composition_guard_passes_a_component_that_owns_a_frame():
    clean = sample(
        "class Navigator:\n"
        "    def __init__(self, parent):\n"
        "        self.frame = ttk.Frame(parent)\n")
    found = [ast.unparse(base) for node in ast.walk(clean)
             if isinstance(node, ast.ClassDef) for base in node.bases]
    assert found == []


@pytest.mark.parametrize("code,expected", [
    ("def f(v):\n    return bool(v.strip())", "strip"),
    ("def disabled_fields(shared):\n    return frozenset()", "disabled_fields"),
    ("def has_meaningful_work(book):\n    return True", "has_meaningful_work"),
])
def test_the_reimplementation_guard_actually_detects_a_copied_projection(
        code, expected):
    tree = sample(code)
    declared = defined_names(tree)
    attrs = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert expected in (declared | attrs), (declared, attrs)


def test_the_reimplementation_guard_passes_a_call_to_the_model():
    clean = sample(
        "from shared.book_workspace import disabled_fields\n"
        "def render(shared):\n    return disabled_fields(shared)\n")
    assert "disabled_fields" not in defined_names(clean)
    assert "disabled_fields" in constructed_names(clean)


@pytest.mark.parametrize("code,expected", [
    ("def f(w):\n    w.after(100, f)", "after"),
    ("def f(w):\n    w.after_idle(f)", "after_idle"),
    ("import threading\ndef f():\n    return threading.Thread()", "Thread"),
])
def test_the_after_chain_guard_actually_detects_a_second_chain(code, expected):
    assert expected in constructed_names(sample(code))


def test_the_after_chain_guard_passes_a_push_driven_render():
    clean = sample(
        "def render(self, workspace):\n"
        "    self._workspace = workspace\n"
        "    self.label.configure(text='Book 1 of 1')\n")
    called = constructed_names(clean)
    for scheduled in ("after", "after_idle", "Thread", "sleep"):
        assert scheduled not in called


def test_no_plan6_model_module_has_grown_a_widget_or_a_theme_dependency():
    """The adapter is deliberately not in this list — owning widgets is its job."""
    for name in DATA_LAYER + (ALLOCATOR,):
        tree = parse(SHARED / name)
        modules = imported_names(tree)
        for entry in modules:
            assert not entry.split(".")[0].lower().startswith("tkinter"), (name, entry)
            assert entry.split(".")[-1] not in {"ui_theme", "job_ui"}, (name, entry)


def test_the_composition_stores_no_later_phase_state():
    """Still three fields, and none of them is a result.

    Phase 7 renamed one: ``skipped`` now carries the reason beside each id, because
    the reason has to be frozen at capture. ``skipped_book_ids`` survives as a
    derived property, so the outward Phase 5 contract is unchanged.
    """
    from shared.book_workspace import BookRunSnapshot

    stored = {entry.name for entry in dataclasses.fields(BookRunSnapshot)}
    assert stored == {"runs", "skipped", "shared"}


def test_the_validity_seam_is_asked_and_never_stored():
    """A predicate in run state would be a live object a worker could be handed."""
    from shared import book_workspace
    import inspect

    source = inspect.getsource(book_workspace.capture_workspace_run)
    assert "is_valid" in source, "the seam exists"
    stored = {entry.name for entry in dataclasses.fields(book_workspace.BookRunSnapshot)}
    assert "is_valid" not in stored


def test_phases_one_to_seven_delivered_their_own_names_and_no_more():
    """The public surface is exactly what Phases 1-7 were authorised to add.

    **Phase 6 added nothing to it**, and that is the assertion, not an omission: the
    allocator is its own module because numbering is not part of the workspace
    vocabulary. A ``SuccessNumbers`` re-exported from here would have made it one.
    Phase 7 added four names and no more.
    """
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
    phase5 = {"RUN_ID_KIND", "effective_run_options", "BookRunSnapshot",
              "capture_workspace_run"}
    phase6: set[str] = set()          # numbering lives in its own module, by design
    phase7 = {"BookDisposition", "SKIP_DISPOSITIONS", "WorkspaceRunResult",
              "retry_failed_books"}
    assert (set(book_workspace.__all__)
            == phase1 | phase2 | phase3 | phase4 | phase5 | phase6 | phase7)
    assert len(book_workspace.__all__) == 45, "15 + 10 + 3 + 9 + 4 + 0 + 4"
    assert len(set(book_workspace.__all__)) == 45, "no name listed twice"


def test_capture_is_not_a_workspace_operation():
    """Capturing observes; it does not mutate, so it gains no operation member."""
    from shared.book_workspace import WorkspaceOperation
    values = {member.value for member in WorkspaceOperation}
    assert values == {"add", "duplicate", "remove", "previous", "next", "select",
                      "replace", "import", "shared_metadata"}
    for capture_word in ("capture", "run", "freeze"):
        assert capture_word not in values




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
    """The two M4B panels are still adopted by nothing. Proved by hash, not by reading."""
    assert sha256_of(UNIVERSAL / relative) == PHASE0_PANEL_HASHES[relative]


def test_the_mp3_tool_left_the_hash_gate_by_a_real_conversion():
    """The focused MP3 plan's one supersession, proved rather than assumed.

    The panel must differ from its Phase 0 bytes *and* must now be the adopter
    the focused plan makes it: it names the workspace vocabulary the other two
    panels are still forbidden to name. A panel that merely changed a comment
    would pass the first half and fail the second.
    """
    assert sha256_of(UNIVERSAL / "mp3_tools/mp3_tool.py") != MP3_TOOL_PHASE0_HASH
    tree = parse(UNIVERSAL / "mp3_tools/mp3_tool.py")
    names = referenced_names(tree) | imported_names(tree)
    assert "shared.book_workspace" in imported_names(tree)
    assert "WorkspaceSnapshot" in names
    assert "shared.book_workspace_ui" in imported_names(tree)
    assert "mp3_tools.mp3_workflow" in imported_names(tree)
    assert set(PHASE0_PANEL_HASHES) == {
        "mp3_tools/m4b_maker.py", "mp3_tools/m4b_metadata_editor.py"}


@pytest.mark.parametrize("relative", sorted(PHASE0_PLAN5_HASHES))
def test_the_plan5_converter_is_byte_identical_to_the_phase_zero_baseline(relative):
    """The consumer the promotion existed to leave alone. Still not one byte moved."""
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


@pytest.mark.parametrize("code,expected", [
    ("from mp3_tools import m4b_numbering\n"
     "def f():\n    return m4b_numbering", "m4b_numbering"),
    ("from shared.numbering import SuccessNumbers\n"
     "def f(n):\n    return SuccessNumbers(n)", "SuccessNumbers"),
    ("class Tentative:\n    number: int", "Tentative"),
    ("def f(counter):\n    return counter.propose()", "propose"),
    ("START_NUMBER = 1\ndef f():\n    return START_NUMBER", "START_NUMBER"),
])
def test_the_phase_six_guard_actually_detects_numbering(code, expected):
    tree = sample(code)
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    assert expected in {entry for entry in PHASE6_NAMES if entry in seen}


def test_the_phase_six_guard_passes_a_capture_that_allocates_nothing():
    clean = sample(
        "def capture(space, *, id_factory):\n"
        "    return tuple((b.book_id, capture_run(snapshot_id=id_factory.next_id('run')))\n"
        "                 for b in space.books)\n"
    )
    seen = defined_names(clean) | referenced_names(clean) | imported_names(clean)
    assert {entry for entry in PHASE6_NAMES if entry in seen} == set()


# --- the promoted-allocator purity guard ---------------------------------- #


@pytest.mark.parametrize("code", [
    "import threading\n",
    "from pathlib import Path\n",
    "import subprocess\n",
    "from shared.book_workspace import BookJob\n",
    "import dataclasses\nimport time\n",
    "from __future__ import annotations\nimport tkinter as tk\n",
])
def test_the_allocator_purity_guard_actually_detects_a_widened_dependency(code):
    assert not import_roots_in(sample(code)) <= ALLOCATOR_IMPORTS


def test_the_allocator_purity_guard_passes_the_real_allowlist():
    clean = sample("from __future__ import annotations\n"
                   "from dataclasses import dataclass\n"
                   "import dataclasses\n")
    assert import_roots_in(clean) <= ALLOCATOR_IMPORTS


def test_the_allocator_purity_guard_refuses_a_relative_import_outright():
    """A relative spelling has no root to compare, so it must not slip through."""
    with pytest.raises(AssertionError):
        import_roots_in(sample("from ..shared.numbering import SuccessNumbers\n"))


def test_the_allocator_purity_guard_is_not_fooled_by_a_docstring():
    """Prose about a Path or a subprocess is not a dependency on one."""
    clean = sample('"""Numbers only. It never opens a Path or runs a subprocess."""\n'
                   "from dataclasses import dataclass\n")
    assert import_roots_in(clean) <= ALLOCATOR_IMPORTS
    assert not set(ALLOCATOR_FORBIDDEN) & referenced_names(clean)


@pytest.mark.parametrize("code,expected", [
    ("import tkinter as tk\ndef f():\n    return tk.Tk()", "Tk"),
    ("def f(p):\n    return Path(p)", "Path"),
    ("def f(name):\n    return open(name)", "open"),
    ("def f(plan):\n    return ConversionPlan(plan)", "ConversionPlan"),
    ("def f(t):\n    return ffmpeg_cmd(t)", "ffmpeg_cmd"),
])
def test_the_allocator_vocabulary_guard_actually_detects_integration_code(
        code, expected):
    assert expected in referenced_names(sample(code)) & set(ALLOCATOR_FORBIDDEN)


# --- the re-export guard --------------------------------------------------- #


@pytest.mark.parametrize("code,expected", [
    ("from shared.numbering import SuccessNumbers as _S\n"
     "class SuccessNumbers(_S):\n    pass\n", "SuccessNumbers"),
    ("class SuccessNumbers:\n"
     "    def propose(self):\n        return 1\n", "SuccessNumbers"),
    ("def make():\n"
     "    class SuccessNumbers:\n        pass\n"
     "    return SuccessNumbers\n", "SuccessNumbers"),
    ("def propose(counter):\n    return counter.propose()\n", "propose"),
])
def test_the_re_export_guard_actually_detects_a_second_implementation(
        code, expected):
    """A subclass, a rewrite, a wrapper, even one hidden inside a factory."""
    assert expected in defined_names(sample(code))


def test_the_re_export_guard_passes_a_genuine_re_export():
    clean = sample("from __future__ import annotations\n"
                   "from shared.numbering import NumberingError, SuccessNumbers, "
                   "Tentative\n"
                   '__all__ = ["NumberingError", "Tentative", "SuccessNumbers"]\n')
    assert defined_names(clean) == set()
    assert set(import_sources_in(clean)) == {"__future__", "shared.numbering"}


@pytest.mark.parametrize("code", [
    "from shared import numbering\n",
    "import shared.numbering\nimport shared.book_workspace\n",
    "from shared.numbering import SuccessNumbers\n"
    "from shared.metadata import something\n",
])
def test_the_re_export_guard_rejects_anything_broader_than_the_one_module(code):
    """``shared`` is not the allowed dependency; ``shared.numbering`` is."""
    assert set(import_sources_in(sample(code))) != {"__future__", "shared.numbering"}


def test_the_re_export_guard_sees_the_full_dotted_path_not_just_the_root():
    """The distinction the whole guard rests on, asserted directly."""
    broad = import_sources_in(sample("from shared import numbering\n"))
    assert set(broad) == {"shared"}, "the root, which is exactly what is NOT allowed"


@pytest.mark.parametrize("code,expected", [
    ("from shared.numbering import SuccessNumbers\n", {"SuccessNumbers"}),
    ("from shared.numbering import NumberingError, SuccessNumbers, Tentative\n",
     {"NumberingError", "SuccessNumbers", "Tentative"}),
])
def test_the_re_export_guard_records_which_names_were_taken(code, expected):
    assert import_sources_in(sample(code))["shared.numbering"] == expected


@pytest.mark.parametrize("code,expected", [
    ("import tkinter as tk\ndef f():\n    return tk.Tk()", "tkinter"),
    ("from tkinter import ttk\ndef f():\n    return ttk", "ttk"),
    ("from shared.job_ui import MainThreadGuard\n"
     "class P:\n    guard = MainThreadGuard", "MainThreadGuard"),
    ("from shared.job_ui import LockGroup\ndef f():\n    return LockGroup", "LockGroup"),
    ("from shared.ui_theme import style_tk_widget\n"
     "def f(w):\n    return style_tk_widget(w)", "style_tk_widget"),
    ("class BookNavigator:\n    pass", "BookNavigator"),
    ("from shared import book_workspace_ui\n"
     "def f():\n    return book_workspace_ui", "book_workspace_ui"),
])
def test_the_phase_eight_guard_actually_detects_an_adapter(code, expected):
    tree = sample(code)
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    assert expected in {entry for entry in PHASE8_NAMES if entry in seen}


def test_the_phase_eight_guard_passes_a_pure_value_layer():
    """Composing a result and describing a retry must not trip the adapter guard."""
    clean = sample(
        "from shared.job_control import JobAction, JobState, is_available\n"
        "def can_retry(state, has_retryable):\n"
        "    return is_available(JobAction.RETRY_FAILED, state,\n"
        "                        has_retryable=has_retryable)\n"
        "def requests(results):\n"
        "    return tuple(result.retry() for _book_id, result in results)\n"
    )
    seen = defined_names(clean) | referenced_names(clean) | imported_names(clean)
    assert {entry for entry in PHASE8_NAMES if entry in seen} == set()


def test_the_phase_eight_guard_is_not_fooled_by_prose_about_a_panel():
    """A docstring may say "panel" and "Tk"; only nodes count."""
    clean = sample(
        '"""The panel that adopts this, in Phase 8, will read Tk vars on the main\n'
        'thread through MainThreadGuard. Nothing here does."""\n'
        "def f(result):\n    return result.dispositions\n"
    )
    seen = defined_names(clean) | referenced_names(clean) | imported_names(clean)
    assert {entry for entry in PHASE8_NAMES if entry in seen} == set()


@pytest.mark.parametrize("code,expected", [
    ("class BookDisposition:\n"
     "    CANCELLED = 'cancelled'\n", "CANCELLED"),
    ("class BookDisposition:\n"
     "    SKIPPED = 'skipped'\n", "SKIPPED"),
])
def test_a_sixth_book_disposition_would_be_visible(code, expected):
    """Mutation-check for the five-member pin: a new member is a new assignment."""
    tree = sample(code)
    members = {node.targets[0].id for node in ast.walk(tree)
               if isinstance(node, ast.Assign)
               and isinstance(node.targets[0], ast.Name)}
    assert expected in members
    assert expected not in BOOK_DISPOSITIONS


def test_the_declaration_helper_refuses_an_ambiguous_name():
    """Two things sharing a name would make every guard below inspect the wrong one."""
    twice = sample("def f():\n    pass\ndef f():\n    pass\n")
    with pytest.raises(AssertionError):
        one_declaration(twice, "f")
    with pytest.raises(AssertionError):
        one_declaration(twice, "absent")


def test_the_declaration_helper_finds_a_method_inside_a_class():
    nested = sample("class A:\n    def m(self):\n        return 1\n")
    assert one_function(nested, "m").name == "m"
    with pytest.raises(AssertionError):
        one_function(nested, "A"), "a class is not a function"


@pytest.mark.parametrize("code", [
    "from shared.job_control import RunSnapshot\n"
    "def f(**kw):\n    return RunSnapshot(**kw)",
    "def build(**kw):\n    return RunSnapshot(snapshot_id='x', **kw)",
])
def test_the_direct_construction_guard_detects_a_bypassed_capture_run(code):
    """Building a RunSnapshot by hand skips the one place a payload is refused."""
    tree = sample(code)
    built = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "RunSnapshot"]
    assert built, "the guard would fire on this"


def test_the_direct_construction_guard_passes_composition_by_delegation():
    clean = sample(
        "from shared.job_control import RunSnapshot, capture_run\n"
        "def f(book, **kw):\n"
        "    snapshot = capture_run(files=book.files, **kw)\n"
        "    return isinstance(snapshot, RunSnapshot)\n"
    )
    built = [node for node in ast.walk(clean)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "RunSnapshot"]
    assert built == []
    assert "capture_run" in constructed_names(clean)


@pytest.mark.parametrize("code,expected", [
    ("from shared.job_control import JobController\n"
     "def f(r):\n    return JobController(r)", "JobController"),
    ("from shared.job_control import JobEventStream\n"
     "def f():\n    return JobEventStream", "JobEventStream"),
    ("from shared.job_control import EtaEstimator\n"
     "def f():\n    return EtaEstimator", "EtaEstimator"),
])
def test_the_controller_guard_actually_detects_run_machinery(code, expected):
    tree = sample(code)
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    assert expected in seen


# --------------------------------------------------------------------------- #
# The Plan 6 suite protects itself
#
# Added at Phase 7, from a defect this suite actually had for a few minutes: two
# functions in this module were given the same name while a guard was being moved
# forward, so Python silently kept the second and the first vanished. It was
# green. A test that quietly stops existing is worse than one that fails.
# --------------------------------------------------------------------------- #

#: Every test module Plan 6 owns.
PLAN6_TEST_MODULES = (
    "test_book_workspace.py", "test_book_grouping.py", "test_shared_metadata.py",
    "test_book_run_snapshot.py", "test_book_numbering.py", "test_book_retry.py",
    "test_book_workspace_ui.py", "test_plan6_boundaries.py",
)


@pytest.mark.parametrize("name", PLAN6_TEST_MODULES)
def test_no_plan6_test_is_shadowed_by_a_later_one_of_the_same_name(name):
    tree = parse(REPO_ROOT / "files" / "tests" / name)
    declared = [node.name for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name.startswith("test_")]
    repeated = sorted({entry for entry in declared if declared.count(entry) > 1})
    assert repeated == [], (name, repeated)


def test_that_shadowing_guard_actually_detects_a_shadowed_test():
    duplicated = sample(
        "def test_a():\n    assert True\n"
        "def test_b():\n    assert True\n"
        "def test_a():\n    assert True\n"
    )
    declared = [node.name for node in duplicated.body
                if isinstance(node, ast.FunctionDef)
                and node.name.startswith("test_")]
    assert sorted({e for e in declared if declared.count(e) > 1}) == ["test_a"]


def test_that_shadowing_guard_passes_distinct_tests():
    fine = sample("def test_a():\n    assert True\ndef test_b():\n    assert True\n")
    declared = [node.name for node in fine.body
                if isinstance(node, ast.FunctionDef)
                and node.name.startswith("test_")]
    assert sorted({e for e in declared if declared.count(e) > 1}) == []


@pytest.mark.parametrize("name", PLAN6_TEST_MODULES)
def test_every_plan6_test_module_exists_and_is_collected(name):
    """The list above must not quietly name a module that has been renamed away."""
    assert (REPO_ROOT / "files" / "tests" / name).is_file(), name


# --------------------------------------------------------------------------- #
# The harness is out of both release archives — proved, not assumed
#
# Read-only. Nothing here runs release.py, and nothing here changes packaging:
# the point is that the harness is ALREADY excluded by the existing explicit
# scope, so Phase 8 needed no packaging change at all.
# --------------------------------------------------------------------------- #


def release_tree() -> ast.Module:
    return parse(SHARED / "release.py")


def test_the_packager_walks_exactly_one_tree_and_it_is_not_files():
    """``scripts/`` is walked; ``files/`` is never named as a source at all."""
    tree = release_tree()
    walked = {ast.unparse(node.func.value) for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in {"rglob", "glob", "walk", "iterdir"}}
    assert walked == {"SCRIPTS_DIR"}, walked

    assigned = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            assigned[node.targets[0].id] = ast.unparse(node.value)
    assert "SCRIPTS_DIR" in assigned
    assert "FILES_DIR" not in assigned, "the dev tree is not a packaging source"


def test_no_release_root_file_is_the_harness_or_lives_under_files():
    tree = release_tree()
    root_files = [node for node in tree.body
                  if isinstance(node, ast.Assign)
                  and any(getattr(target, "id", "") == "ROOT_FILES"
                          for target in node.targets)]
    assert len(root_files) == 1, "ROOT_FILES is the explicit root scope"
    named = {node.value for node in ast.walk(root_files[0])
             if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert HARNESS not in named
    for entry in named:
        assert not entry.startswith("files/"), entry


def test_the_harness_would_not_be_reached_by_the_packagers_scope():
    """Mechanically: the harness path is not under the one tree that is walked."""
    harness = REPO_ROOT / "files" / "tests" / HARNESS
    scripts_dir = REPO_ROOT / "scripts"
    assert scripts_dir not in harness.parents, harness
    assert harness not in set(scripts_dir.rglob("*"))


def test_the_plan3_harness_is_excluded_the_same_way_and_always_was():
    """The precedent this relies on. If it ever changed, this fails too."""
    plan3 = REPO_ROOT / "files" / "tests" / "manual_plan3_harness.py"
    assert plan3.is_file(), "the Plan 3 harness is the precedent"
    assert (REPO_ROOT / "scripts") not in plan3.parents


def test_the_adapter_by_contrast_does_ship():
    """It is production, so it must be inside the packaged tree."""
    adapter = SHARED / ADAPTER
    assert (REPO_ROOT / "scripts") in adapter.parents
    assert adapter in set((REPO_ROOT / "scripts").rglob("*.py"))


# --------------------------------------------------------------------------- #
# The harness after the Phase 8 manual gate
#
# Three corrections the maintainer asked for on inspection: narrator gone, every
# entry labelled on its own side, and a per-book Chapter Titles section. These
# are structural checks over the harness source; the live behaviour of the
# chapter editor is exercised in ``test_book_workspace_ui.py``.
# --------------------------------------------------------------------------- #


def harness_tree() -> ast.Module:
    return parse(REPO_ROOT / "files" / "tests" / HARNESS)


def harness_literals() -> set[str]:
    return {node.value for node in ast.walk(harness_tree())
            if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def test_the_harness_declares_no_narrator_field():
    """The maintainer does not use narrator metadata and does not want the space."""
    declared = [node for node in harness_tree().body
                if isinstance(node, ast.Assign)
                and any(getattr(target, "id", "") == "FIELDS"
                        for target in node.targets)]
    assert len(declared) == 1, "one vocabulary declaration"
    spelled = ast.unparse(declared[0])
    assert "narrator" not in spelled.lower(), spelled
    assert "title" in spelled and "author" in spelled


def test_the_harness_vocabulary_is_key_and_label_pairs():
    declared = next(node for node in harness_tree().body
                    if isinstance(node, ast.Assign)
                    and any(getattr(target, "id", "") == "FIELDS"
                            for target in node.targets))
    assert isinstance(declared.value, ast.Tuple)
    for element in declared.value.elts:
        assert isinstance(element, ast.Tuple), ast.unparse(element)
        assert len(element.elts) == 2, ast.unparse(element)


def test_the_adapter_still_hard_codes_no_field_key_or_label():
    """Removing narrator from a consumer must not have taught the adapter anything."""
    adapter = {node.value for node in ast.walk(adapter_tree())
               if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for concrete in ("title", "Title", "author", "Author", "narrator", "Narrator"):
        assert concrete not in adapter, concrete


# --- the chapter-titles section -------------------------------------------- #


def test_the_harness_shows_a_chapter_titles_section_with_its_help_text():
    literals = harness_literals()
    assert "Chapter Titles" in literals, "the section caption"
    assert "One chapter title per line." in literals, "the help text"
    # "Chapters" alone would suggest file or duration editing, which this is not.
    assert "Chapters" not in literals


def test_the_chapter_key_is_the_harnesss_own_and_reaches_no_shared_layer():
    tree = harness_tree()
    declared = [node for node in tree.body
                if isinstance(node, ast.Assign)
                and any(getattr(target, "id", "") == "CHAPTER_FIELD"
                        for target in node.targets)]
    assert len(declared) == 1
    assert ast.unparse(declared[0].value) == "'chapter_titles'"

    # It is ordinary BookJob configuration, so it must appear nowhere else.
    assert "chapter_titles" not in {
        node.value for node in ast.walk(adapter_tree())
        if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for name in DATA_LAYER + (ALLOCATOR,):
        assert "chapter_titles" not in {
            node.value for node in ast.walk(parse(SHARED / name))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)}, name


def test_the_chapter_editor_writes_through_the_existing_immutable_flow():
    """``replace_book`` and a fresh ``BookJob`` — no new mutation path."""
    tree = harness_tree()
    editor = one_function(tree, "on_chapter_edit")
    called = constructed_names(editor)
    assert "replace_book" in called, "the model applies the change"
    assert "BookJob" in called, "a new immutable value, not an edit in place"


def test_the_harness_adds_no_m4b_or_chapter_writing_behaviour():
    """Plan 6 demonstrates the configuration surface. It writes nothing."""
    tree = harness_tree()
    called = constructed_names(tree)
    for owned_elsewhere in ("ffmpeg_cmd", "write_chapters", "ffmetadata",
                            "build_chapters", "chapter_times", "duration",
                            "probe", "convert", "export", "run", "Popen"):
        assert owned_elsewhere not in called, owned_elsewhere
    modules = imported_names(tree)
    for banned in ("subprocess", "shared.metadata", "mp3_tools.m4b_maker",
                   "mp3_tools.m4b_converter", "pydub", "mutagen"):
        assert banned not in modules, banned
    declared = defined_names(tree)
    for invented in ("Chapter", "ChapterModel", "ChapterList", "ChapterPlan"):
        assert invented not in declared, invented


def test_the_chapter_box_is_themed_through_the_sanctioned_helper():
    """A classic ``Text`` needs ``style_tk_widget``; it must not be hand-coloured."""
    tree = harness_tree()
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and node.func.attr == "style_tk_widget"]
    roles = {keyword.value.value for node in calls for keyword in node.keywords
             if keyword.arg == "role"}
    assert "text" in roles, "an editable per-book field takes the field colours"
    assert "shared" not in roles, (
        "the Shared role would falsely say this is global")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not node.value.startswith("#"), node.value


def test_the_chapter_section_is_never_part_of_shared_metadata():
    tree = harness_tree()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        spelled = ast.unparse(node.func)
        if spelled.endswith("SharedMetadata") or spelled.endswith(
                "SharedMetadata.for_fields"):
            assert "CHAPTER_FIELD" not in ast.unparse(node), ast.unparse(node)
    # And the chapter widget is built outside both metadata groups.
    assert "self.chapters" in ast.unparse(tree)


def test_the_harness_adds_no_second_imported_file_list():
    """Chapter titles are not audio files, and Plan 3 still owns the file list."""
    tree = harness_tree()
    seen = defined_names(tree) | referenced_names(tree) | imported_names(tree)
    for plan3 in ("ImportedFileList", "ImportAdapter", "ImportOptionsBar",
                  "ImportedFileManager", "ask_files", "ask_folder"):
        assert plan3 not in seen, plan3


def test_the_harness_opens_no_after_chain():
    tree = harness_tree()
    called = constructed_names(tree)
    for scheduled in ("after", "after_idle", "after_cancel", "sleep"):
        assert scheduled not in called, scheduled


def test_only_the_diagnostic_log_expands():
    """At 920x600 the form keeps its size and the log gives up the space."""
    tree = harness_tree()
    weighted = [ast.unparse(node) for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "rowconfigure"
                and ast.unparse(node.func.value) == "container"
                and any(keyword.arg == "weight" and keyword.value.value
                        for keyword in node.keywords)]
    # Exactly one row of the FORM expands. (The log frame separately lets its own
    # text box fill the space the form gave up, which is the point of giving it up.)
    assert len(weighted) == 1, weighted
    assert "container.rowconfigure(4" in weighted[0], weighted[0]
