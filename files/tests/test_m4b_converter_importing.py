"""The M4B Converter's adoption of the shared importer — v0.6.2 Plan 5, Phase 7B.

**What was replaced.** The Converter owned a second input system: a
``list[Path]``, its own ``Listbox``, its own three buttons and a count label, all
mutated by *list index*. The visible rows and the queue were two separate things
kept in step by hand, and ``start_convert`` froze the list rather than a
committed snapshot. Phase 7B retires all of it: the shared
``ImportedFileManager`` is now the only authority, and the shared list is a view
of it.

The load-bearing tests here are the ones about **authority**, not about buttons —
``test_no_shadow_path_queue_survives_on_the_panel`` and the Start-snapshot group.
A second list that merely *looks* right is exactly the failure this phase exists
to remove, so those are asserted structurally rather than by observing agreement.

Determinism
-----------
No test sleeps. Scans run inline through the shared recording thread factory and
the pump is ticked by hand. Nothing opens a dialog — every chooser is injected.

Safety
------
Every fixture is generated under ``tmp_path``: placeholder ``.m4b`` files, never
real media, because importer validation is extension- and filesystem-based.
Nothing scans the repository, a home directory or an output base, and no test
converts anything or starts a real ffmpeg process.

Scope
-----
Phase 7B changed **input** only, and these tests still prove exactly that.
Two later sections were added deliberately as their phases landed: Phase 8's
output planning at Start, and -- from Phase 9 -- the two guards below that had
to move forward when the panel adopted shared job control. The Phase 9 run
itself is proved in ``test_m4b_converter_jobs.py``; what is asserted here is
only that the importer half is unchanged by it.
"""

from __future__ import annotations

import ast
import threading
import unittest.mock as mock
from pathlib import Path

import pytest

# Imported outright rather than through ``importorskip``: Plan 5 is fail-loud, and
# on every platform this tool supports a missing tkinter is a broken environment,
# not a fact to tolerate. The live-root question is separate and belongs to
# ``tk_gate``, which is what the fixture below uses.
import tkinter as tk

from shared.import_coordination import OutcomeStatus  # noqa: E402
from shared.importing import ImportOptions  # noqa: E402
from shared.job_control import JobAction  # noqa: E402

from shared import output_paths  # noqa: E402

from mp3_tools import m4b_converter  # noqa: E402

from test_import_coordination import RecordingThreads  # noqa: E402
from test_import_traversal import touch  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_conversion_plan import (  # noqa: E402
    StubThread,
    _reservation,
    install_conversion_stubs,
)
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PANEL_SOURCE = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_converter.py"


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture()
def make_panel(tk_root):
    """A real ``M4BConverterUI`` with deterministic seams, closed afterwards."""
    made: list[m4b_converter.M4BConverterUI] = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        panel = m4b_converter.M4BConverterUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


def books(folder: Path, *names: str) -> tuple[Path, ...]:
    """Generated placeholder audiobooks. Never real media."""
    return tuple(touch(folder / name, "not an audiobook") for name in names)


def add_files(panel, *paths: Path):
    panel.importer._choose_files = lambda: tuple(str(p) for p in paths)
    return panel.importer.add_files()


def add_folder(panel, root: Path):
    """Run one folder import to completion through the real coordinator."""
    panel.importer._choose_folder = lambda: (str(root),)
    panel.importer.add_folder()
    panel._pump.tick()
    return panel.imported_files()


def names(panel) -> list[str]:
    return [p.name for p in panel.imported_files()]


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #


def test_the_panel_composes_the_shared_foundation(make_panel):
    panel = make_panel()
    from shared import job_ui
    from shared.import_coordination import ImportCoordinator
    from shared.importing import ImportedFileManager

    assert isinstance(panel.importer, job_ui.ImportAdapter)
    assert isinstance(panel.manager, ImportedFileManager)
    assert isinstance(panel._coordinator, ImportCoordinator)
    assert isinstance(panel._pump, job_ui.MainThreadPump)
    assert panel.importer.manager is panel.manager


def test_the_panel_reimplements_none_of_the_foundation():
    """Adoption means composing the shared services, not copying them."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for banned in ("scan_roots", "ImportedFileManager", "ImportCoordinator",
                   "ImportAdapter", "MainThreadPump", "ImportedFileList",
                   "ImportOptionsBar", "natural_key", "capture_identity",
                   "validate_direct_files"):
        assert banned not in defined, banned


def test_only_one_scheduled_callback_chain_exists():
    """The pump owns scheduling; a second ``after`` loop would race it."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "self.after(" not in source


# --------------------------------------------------------------------------- #
# Decision 16A — the one supported type
# --------------------------------------------------------------------------- #


def test_the_catalog_offers_exactly_one_type():
    catalog = m4b_converter.build_catalog()
    assert [(t.type_id, t.label) for t in catalog.types] == [("m4b", "M4B audiobook")]
    assert catalog.types[0].extensions == (".m4b",)


@pytest.mark.parametrize("banned", [".mp3", ".m4a", ".aac", ".mp4", ".flac", ".wav"])
def test_no_other_audio_type_crept_in(banned):
    """Widening the catalog would widen the whole tool: it is what the dialog
    offers *and* what the shared validator accepts."""
    catalog = m4b_converter.build_catalog()
    for supported in catalog.types:
        assert banned not in supported.extensions


def test_the_type_is_enabled_by_default(make_panel):
    panel = make_panel()
    assert panel.importer.options.selected_type_ids() == frozenset({"m4b"})
    assert panel.importer.options.options().has_selection is True


def test_add_files_declines_when_no_type_is_enabled(make_panel, tmp_path):
    """One type means unchecking it leaves none — and that must be truthful."""
    panel = make_panel()
    book, = books(tmp_path, "Book.m4b")
    panel.importer.options.set_types(())
    outcome = add_files(panel, book)
    assert outcome.status is OutcomeStatus.NO_TYPES_SELECTED
    assert panel.imported_files() == []


def test_add_folder_declines_without_starting_a_scanner(make_panel, tmp_path):
    threads = RecordingThreads()
    panel = make_panel(thread_factory=threads)
    books(tmp_path / "Library", "Book.m4b")
    panel.importer.options.set_types(())
    panel.importer._choose_folder = lambda: (str(tmp_path / "Library"),)
    panel.importer.add_folder()
    assert panel.imported_files() == []
    assert threads.made == [], "no worker may start for a declined import"


def test_re_enabling_the_type_restores_normal_importing(make_panel, tmp_path):
    panel = make_panel()
    book, = books(tmp_path, "Book.m4b")
    panel.importer.options.set_types(())
    add_files(panel, book)
    assert panel.imported_files() == []

    panel.importer.options.set_types(("m4b",))
    add_files(panel, book)
    assert names(panel) == ["Book.m4b"]


# --------------------------------------------------------------------------- #
# The manager is the only queue
# --------------------------------------------------------------------------- #


def test_no_shadow_path_queue_survives_on_the_panel(make_panel, tmp_path):
    """The central Phase 7B invariant, asserted against the live object.

    A second list that merely happens to agree today is the failure this phase
    removed, so this looks for *any* panel attribute that is a list or set of
    paths rather than trusting a name.
    """
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b", "B.m4b"))

    for name, value in vars(panel).items():
        if isinstance(value, (list, set)) and value:
            assert not all(isinstance(item, Path) for item in value), (
                f"{name} is a second live path queue")
    assert not hasattr(panel, "files")
    assert not hasattr(panel, "listbox")


def test_the_visible_rows_are_a_view_of_the_manager(make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b", "B.m4b", "C.m4b"))
    assert panel.importer.list.count == panel.manager.count == 3
    assert panel.importer.list.order == panel.manager.snapshot().occurrence_ids


def test_imported_files_is_derived_not_stored(make_panel, tmp_path):
    """``imported_files()`` recomputes; mutating what it returns changes nothing."""
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b"))
    first = panel.imported_files()
    first.append(Path("ghost.m4b"))
    assert len(panel.imported_files()) == 1


# --------------------------------------------------------------------------- #
# Add Files
# --------------------------------------------------------------------------- #


def test_add_files_imports_m4b(make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "Book.m4b"))
    assert names(panel) == ["Book.m4b"]


def test_add_files_refuses_an_unsupported_extension(make_panel, tmp_path):
    """The dialog filter is a convenience; the shared validator is the boundary."""
    panel = make_panel()
    good, bad = books(tmp_path, "Book.m4b", "Song.mp3")
    add_files(panel, good, bad)
    assert names(panel) == ["Book.m4b"]


def test_add_files_keeps_the_dialog_order(make_panel, tmp_path):
    panel = make_panel()
    chosen = books(tmp_path, "Zebra.m4b", "Apple.m4b", "Mango.m4b")
    add_files(panel, *chosen)
    assert names(panel) == ["Zebra.m4b", "Apple.m4b", "Mango.m4b"]


def test_add_files_records_direct_provenance(make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "Book.m4b"))
    entry = panel.manager.snapshot().files[0]
    from shared.importing import RootKind
    assert entry.source_root.kind is RootKind.DIRECT_FILES
    assert entry.source_root.path is None


@pytest.mark.parametrize("subfolders", [True, False])
def test_include_subfolders_never_affects_add_files(make_panel, tmp_path, subfolders):
    panel = make_panel()
    panel.importer.options.set_include_subfolders(subfolders)
    books(tmp_path / "nested", "Deep.m4b")
    add_files(panel, *books(tmp_path, "Top.m4b"))
    assert names(panel) == ["Top.m4b"]


def test_the_remembered_input_directory_survives_adoption(make_panel, tmp_path, monkeypatch):
    """The panel's own chooser still reads and writes its setting."""
    from shared import settings
    recorded: dict[str, str] = {}
    monkeypatch.setattr(settings, "set", lambda key, value: recorded.update({key: value}))
    monkeypatch.setattr(settings, "get", lambda key, default=None: None)

    book, = books(tmp_path / "Library", "Book.m4b")
    panel = make_panel(choose_files=None)
    monkeypatch.setattr(
        m4b_converter.filedialog, "askopenfilenames", lambda **kw: (str(book),))
    panel.importer.add_files()

    assert recorded.get(m4b_converter.KEY_INPUT_DIR) == str(book.parent)
    assert names(panel) == ["Book.m4b"]


# --------------------------------------------------------------------------- #
# Add Folder
# --------------------------------------------------------------------------- #


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    root = tmp_path / "Library"
    books(root, "Top.m4b")
    books(root / "Series", "Nested.m4b")
    books(root / "Series" / "Part A", "Deep.m4b")
    books(root, "Notes.txt")
    return root


def test_add_folder_recurses_by_default(make_panel, library):
    panel = make_panel()
    add_folder(panel, library)
    assert sorted(names(panel)) == ["Deep.m4b", "Nested.m4b", "Top.m4b"]


def test_add_folder_shallow_takes_only_the_root(make_panel, library):
    panel = make_panel()
    panel.importer.options.set_include_subfolders(False)
    add_folder(panel, library)
    assert names(panel) == ["Top.m4b"]


def test_add_folder_filters_by_the_catalog(make_panel, library):
    panel = make_panel()
    add_folder(panel, library)
    assert "Notes.txt" not in names(panel)


def test_add_folder_keeps_root_relative_provenance(make_panel, library):
    panel = make_panel()
    add_folder(panel, library)
    entries = {e.path.name: e for e in panel.manager.snapshot().files}
    nested = entries["Nested.m4b"]
    assert nested.source_root.path == library
    assert str(nested.relative_path).replace("\\", "/") == "Series/Nested.m4b"


def test_a_declined_broad_root_starts_no_worker(make_panel, library):
    threads = RecordingThreads()
    panel = make_panel(thread_factory=threads, confirm_broad_root=lambda roots: False,
                       home=library)
    panel.importer._choose_folder = lambda: (str(library),)
    panel.importer.add_folder()
    assert panel.imported_files() == []
    assert threads.made == []


def test_a_declined_large_result_commits_nothing(make_panel, library):
    panel = make_panel(effective_config=make_config(1),
                       confirm_large_result=lambda outcome: False)
    add_folder(panel, library)
    assert panel.imported_files() == []


def test_direct_files_and_folder_files_share_one_queue(make_panel, tmp_path, library):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "picked", "Chosen.m4b"))
    add_folder(panel, library)
    assert names(panel)[0] == "Chosen.m4b"
    assert set(names(panel)) == {"Chosen.m4b", "Top.m4b", "Nested.m4b", "Deep.m4b"}


# --------------------------------------------------------------------------- #
# Decision 14A — the control surface
# --------------------------------------------------------------------------- #


def test_every_decision_14a_control_is_present(make_panel):
    panel = make_panel()
    labels = {key: str(panel.importer.list.buttons[key].cget("text"))
              for key, _text in panel.importer.list.ACTIONS}
    assert labels == {
        "add_files": "Add Files…",
        "add_folder": "Add Folder…",
        "move_up": "Move Up",
        "move_down": "Move Down",
        "remove": "Remove",
        "clear": "Clear All",
    }


def test_every_import_option_is_present(make_panel):
    panel = make_panel()
    options = panel.importer.options
    assert str(options.type_buttons["m4b"].cget("text")) == "M4B audiobook"
    assert str(options.check_subfolders.cget("text")) == "Include subfolders"
    assert str(options.check_hidden.cget("text")) == "Include hidden folders"
    assert str(options.check_duplicates.cget("text")) == "Allow duplicate files"


def test_the_import_status_and_cancel_import_surface_exists(make_panel):
    panel = make_panel()
    assert panel.importer.status is not None
    assert hasattr(panel.importer, "cancel_import")


def test_extended_selection_comes_from_the_shared_list(make_panel):
    panel = make_panel()
    assert str(panel.importer.list.listbox.cget("selectmode")) == "extended"


def test_move_up_preserves_occurrence_identity_and_selection(make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b", "B.m4b", "C.m4b"))
    listing = panel.importer.list
    _a, b, _c = listing.order

    listing.select((b,))
    listing.move_up()
    assert names(panel) == ["B.m4b", "A.m4b", "C.m4b"]
    assert listing.order[0] == b, "the moved row keeps its occurrence id"
    assert listing.selection == (b,)

    listing.move_down()
    assert names(panel) == ["A.m4b", "B.m4b", "C.m4b"]
    assert listing.selection == (b,)


def test_button_enablement_is_derived_at_the_list_edges(make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b", "B.m4b"))
    listing = panel.importer.list
    first, last = listing.order

    listing.select((first,))
    assert listing.button_states()["move_up"] is False
    assert listing.button_states()["move_down"] is True

    listing.select((last,))
    assert listing.button_states()["move_up"] is True
    assert listing.button_states()["move_down"] is False


def test_remove_takes_only_the_selected_row(make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b", "B.m4b", "C.m4b"))
    listing = panel.importer.list
    _a, b, _c = listing.order
    listing.select((b,))
    listing.remove_selected()
    assert names(panel) == ["A.m4b", "C.m4b"]


def test_clear_all_empties_the_manager(make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b", "B.m4b"))
    listing = panel.importer.list
    assert str(listing.buttons["clear"].cget("text")) == "Clear All"

    listing.buttons["clear"].invoke()
    assert panel.manager.count == 0
    assert panel.imported_files() == []
    assert listing.count == 0
    assert listing.button_states()["clear"] is False


# --------------------------------------------------------------------------- #
# Deliberate duplicates
# --------------------------------------------------------------------------- #


def test_the_same_book_is_refused_twice_by_default(make_panel, tmp_path):
    panel = make_panel()
    book, = books(tmp_path, "Book.m4b")
    add_files(panel, book)
    add_files(panel, book)
    assert names(panel) == ["Book.m4b"]


def test_a_deliberate_duplicate_is_two_occurrences(make_panel, tmp_path):
    panel = make_panel()
    book, = books(tmp_path, "Book.m4b")
    panel.importer.options.set_allow_duplicates(True)
    add_files(panel, book)
    add_files(panel, book)

    entries = panel.manager.snapshot().files
    assert [e.path for e in entries] == [book, book]
    assert entries[0].identity == entries[1].identity, "same physical file"
    assert entries[0].occurrence_id != entries[1].occurrence_id, "distinct occurrences"


def test_removing_one_duplicate_leaves_the_other(make_panel, tmp_path):
    panel = make_panel()
    book, = books(tmp_path, "Book.m4b")
    panel.importer.options.set_allow_duplicates(True)
    add_files(panel, book)
    add_files(panel, book)

    listing = panel.importer.list
    first, second = listing.order
    listing.select((first,))
    listing.remove_selected()

    assert panel.manager.count == 1
    assert panel.manager.snapshot().occurrence_ids == (second,)


# --------------------------------------------------------------------------- #
# Start freezes one snapshot
# --------------------------------------------------------------------------- #


@pytest.fixture()
def captured_run(monkeypatch):
    """Start a conversion but capture the worker instead of running it.

    The stubs come from the Phase 10 module so all three panel test modules
    drive the production worker through exactly the same seams.
    """
    return install_conversion_stubs(monkeypatch, {})


def start_run(panel, tmp_path, captured_run):
    """Press Convert; return the params the worker would have been handed."""
    panel.start_convert()
    assert StubThread.started, "the worker was never handed a run"
    return StubThread.started[-1].args[0]


def planned_run(panel, tmp_path, captured_run):
    """Run the whole production path and return the immutable plan it produced.

    v0.6.2 Plan 5 Phase 10 moved destination planning off the main thread: the
    run directory is reserved only after every source has been read, so the
    destinations exist in the plan rather than in the worker's parameters.
    """
    params = start_run(panel, tmp_path, captured_run)
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()
    return panel.run_plan


def test_start_freezes_the_manager_order(make_panel, tmp_path, captured_run):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    params = start_run(panel, tmp_path, captured_run)
    assert [e.path.name for e in params["imported_files"]] == ["A.m4b", "B.m4b", "C.m4b"]


def test_a_later_manager_change_cannot_alter_a_running_run(make_panel, tmp_path, captured_run):
    """The captured sequence is immutable, so the run is not a live view."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    params = start_run(panel, tmp_path, captured_run)
    captured = params["imported_files"]
    assert isinstance(captured, tuple)

    panel.manager.clear()
    assert panel.manager.count == 0
    assert [e.path.name for e in captured] == ["A.m4b", "B.m4b", "C.m4b"]



def test_the_run_carries_occurrences_not_bare_paths(make_panel, tmp_path, captured_run):
    """Provenance is what the plan's destination routing needs."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    params = start_run(panel, tmp_path, captured_run)
    entry = params["imported_files"][0]
    assert hasattr(entry, "occurrence_id") and hasattr(entry, "source_root")
    assert "files" not in params, "the legacy path list must not come back"

def test_start_refuses_an_empty_manager(make_panel, tmp_path, captured_run, monkeypatch):
    panel = make_panel()
    warned: list = []
    monkeypatch.setattr(m4b_converter.messagebox, "showwarning",
                        lambda *a, **k: warned.append(a))
    panel.start_convert()
    assert warned and not StubThread.started


# --------------------------------------------------------------------------- #
# Locking and cancellation
# --------------------------------------------------------------------------- #


def test_processing_locks_the_importer_and_finishing_unlocks_it(make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b"))
    listing, options = panel.importer.list, panel.importer.options

    panel.disable_inputs(True)
    assert listing.locked is True and options.locked is True
    assert str(listing.buttons["add_files"].cget("state")) == "disabled"
    assert str(options.check_subfolders.cget("state")) == "disabled"

    panel._finish_idle()
    assert listing.locked is False and options.locked is False


def test_cancel_import_does_not_touch_the_conversion_cancel(make_panel, library):
    """Two different cancellations live in this panel and must stay apart."""
    panel = make_panel()
    assert not panel._cancel_event.is_set()
    panel.importer.cancel_import()
    assert not panel._cancel_event.is_set(), "import cancel must not stop a conversion"


def test_the_conversion_cancel_does_not_touch_the_importer(make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b"))
    panel._busy.set()
    panel.cancel()
    assert panel._cancel_event.is_set()
    assert panel.manager.count == 1, "cancelling a conversion imports nothing away"
    panel._busy.clear()
    panel._cancel_event.clear()


def test_a_cancelled_scan_commits_nothing(make_panel, library):
    """Cancel has to arrive while the scan is still running, so the scanner is
    held at an explicit gate rather than raced against an inline thread."""
    from test_import_coordination import ControlledScanner, RealThreads

    started, release = threading.Event(), threading.Event()
    threads = RealThreads()
    panel = make_panel(
        scanner=ControlledScanner(started=started, release=release),
        thread_factory=threads)
    panel.importer._choose_folder = lambda: (str(library),)
    panel.importer.add_folder()   # the coordinator starts the real thread itself

    assert started.wait(5.0), "the scanner never ran"
    panel.importer.cancel_import()
    release.set()
    for thread in threads.made:
        thread.join(5.0)
        assert not thread.is_alive()
    panel._pump.tick()

    assert panel.imported_files() == []
    assert panel.manager.count == 0


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #


def test_close_is_idempotent_and_leaves_nothing_scheduled(make_panel):
    panel = make_panel()
    panel.close()
    panel.close()
    assert panel._pump.closed is True
    assert panel.importer.closed is True
    assert panel._pump.scheduled_count == 0


def test_close_joins_a_conversion_worker(make_panel):
    panel = make_panel()
    released = threading.Event()

    class _Slow:
        def __init__(self):
            self.joined = False

        def join(self, timeout=None):
            self.joined = True
            released.set()

    panel._worker = _Slow()
    panel._busy.set()
    panel.close()
    assert released.is_set()
    assert panel._cancel_event.is_set(), "a running conversion is asked to stop first"


# --------------------------------------------------------------------------- #
# Phase boundaries
# --------------------------------------------------------------------------- #


def test_no_phase_eight_output_planning_arrived():
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    called |= {node.func.id for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    for banned in ("planning_groups", "plan_flat", "plan_mirrored", "plan_multi_root"):
        assert banned not in called, banned


def test_phase_nine_job_control_arrived_and_is_the_shared_foundation():
    """**A deliberate progression, not a weakening.**

    Through Phase 8 this guard asserted the opposite: that no job-control
    vocabulary had reached the panel yet. Phase 9 is the phase authorized to
    bring it in, so the guard is turned around rather than deleted -- it now
    requires the panel to name the shared foundation, and
    ``test_m4b_converter_jobs.py`` proves it *composes* rather than
    reimplements it. The boundary that has not moved is asserted below and in
    that module: Phases 10 to 13 are still absent.
    """
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    named |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for required in ("JobController", "JobReporter", "JobAdapter", "EtaEstimator",
                     "capture_run", "RunResult", "checkpoint", "request_pause",
                     "request_cancel"):
        assert required in named, required

    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for owned_elsewhere in ("JobController", "JobReporter", "JobAdapter",
                            "EtaEstimator", "LockGroup", "JobEventStream",
                            "RunResult", "JobState"):
        assert owned_elsewhere not in defined, owned_elsewhere



def test_phase_ten_arrived_and_phase_eleven_did_not():
    """**A deliberate progression, not a weakening.**

    Through Phase 9 this asserted that no chapter, command or plan vocabulary
    had reached the panel. Phase 10 is the phase authorized to bring the
    preflight and the immutable plan in, so the guard now requires them -- while
    still refusing everything the execution engine owns. The panel delegates:
    it names the two Converter-local modules and none of the media logic itself.
    """
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    named |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    assert "assemble_plan" in named and "probe_source" in named
    for banned in ("plan_timeline", "validate_chapters", "segment_filename",
                   "flatten_title", "ChapterProbe", "select_attached_picture",
                   "segment_argv", "attach_artwork_argv", "segment_commands"):
        assert banned not in named, banned

    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for owned_elsewhere in ("ConversionPlan", "ItemPlan", "SegmentPlan",
                            "assemble_plan", "probe_source"):
        assert owned_elsewhere not in defined, owned_elsewhere

def test_the_panel_stays_classic_with_no_namespaced_styles():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "ACT." not in source


# --------------------------------------------------------------------------- #
# 920x600 reachability (Decision D1)
# --------------------------------------------------------------------------- #


def test_every_new_control_is_reachable_at_the_minimum_window(tk_root):
    """Actual mapped geometry at 920x600, not a requested-size estimate.

    The plan already accepts pre-existing clipping elsewhere and defers broad
    visual repair to Plan 9. The question each phase has to answer is
    narrower: are the controls **it adds** actually on screen and clickable.

    ``winfo_ismapped`` plus a real bounding box is the evidence, because a
    widget can be laid out, sized and still never mapped when the geometry
    manager runs out of room.

    **Phase 9 widened this list and did not relax it.** The panel's own
    ``Cancel`` button was retired into the shared control bar, so the four
    shared run controls, the progress bar and the three status labels are
    checked here in its place -- eight controls where there was one. The 16 px
    floor is unchanged.
    """
    from shared import ui_theme
    assert ui_theme.MIN_SIZE == (920, 600)

    host = tk.Toplevel(tk_root)
    try:
        host.geometry("920x600")
        panel = m4b_converter.M4BConverterUI(
            host, effective_config=make_config(), clock=lambda: 0.0, home=None,
            thread_factory=RecordingThreads(),
            choose_files=lambda: (), choose_folder=lambda: ())
        panel.pack(fill="both", expand=True)
        host.update_idletasks()
        host.update()

        listing, options = panel.importer.list, panel.importer.options
        required = {
            "Add Files…": listing.buttons["add_files"],
            "Add Folder…": listing.buttons["add_folder"],
            "Move Up": listing.buttons["move_up"],
            "Move Down": listing.buttons["move_down"],
            "Remove": listing.buttons["remove"],
            "Clear All": listing.buttons["clear"],
            "M4B audiobook": options.type_buttons["m4b"],
            "Include subfolders": options.check_subfolders,
            "Include hidden folders": options.check_hidden,
            "Allow duplicate files": options.check_duplicates,
            "Cancel Import": panel.importer.status.frame,
            "MP3 Quality": panel.entry_quality,
            "Metadata: Preserve": panel.rb_preserve,
            "Metadata: Replace": panel.rb_replace,
            "Metadata: Write none": panel.rb_strip,
            "Title": panel.title_entry,
            "Auto-number tracks": panel.chk_auto_num,
            "Start #": panel.entry_start_num,
            "Output folder": panel.entry_outdir,
            "Convert": panel.btn_convert,
            "Open Output Folder": panel.btn_open_out,
            # Phase 9's own controls, in the shared bar the panel now hosts.
            "Pause": panel.jobs.controls.buttons[JobAction.PAUSE],
            "Resume": panel.jobs.controls.buttons[JobAction.RESUME],
            "Cancel": panel.jobs.controls.buttons[JobAction.CANCEL],
            "Retry Failed": panel.jobs.controls.buttons[JobAction.RETRY_FAILED],
            "Progress bar": panel.jobs.status.indicator.bar,
            "Progress count": panel.jobs.status.indicator.label,
            "ETA": panel.jobs.status.label_eta,
        }

        unreachable = {}
        for label, widget in required.items():
            mapped = bool(widget.winfo_ismapped())
            width, height = widget.winfo_width(), widget.winfo_height()
            top = widget.winfo_rooty() - host.winfo_rooty()
            bottom = top + height
            # 16 px is the smallest thing worth calling a click target. The first
            # Phase 7B layout squeezed `Convert` to 8 px — mapped, inside the
            # window, and effectively unusable — so height is checked as a real
            # target rather than merely as non-zero.
            if not mapped or width <= 1 or height < 16 or bottom > 600:
                unreachable[label] = (mapped, width, height, top, bottom)

        assert not unreachable, unreachable

        # The measured trade-off, recorded rather than hidden. At the 920x600
        # minimum this panel's content genuinely exceeds the window -- it did
        # before Phase 9 too, which is why the panel's own progress indicator
        # was never mapped there *or* at the 1024x720 default. Phase 9 makes
        # the progress bar visible for the first time; what it costs is that
        # the three scrollable views are squeezed at the minimum. They stay
        # mapped and scrollable, and every control above is a real target.
        assert panel.jobs.status.indicator.bar.winfo_ismapped()
        assert panel.jobs.views.summary_text.winfo_height() >= 16, (
            "the Summary keeps at least one line at the minimum window")

        panel.close()
        panel.destroy()
    finally:
        host.destroy()


# --------------------------------------------------------------------------- #
# Phase 8 — the run's destinations are planned from provenance, at Start
# --------------------------------------------------------------------------- #


def planned_of(plan, name):
    """Every destination the plan gave the book called *name*."""
    for item in plan.items:
        if item.source.name == name:
            return [segment.destination for segment in item.segments]
    raise AssertionError(f"{name} is not in the plan")


def test_the_plan_holds_a_destination_for_every_usable_occurrence(
        make_panel, tmp_path, captured_run):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    plan = planned_run(panel, tmp_path, captured_run)

    assert {item.occurrence_id for item in plan.items} == set(
        panel.run_snapshot.item_ids)
    assert all(len(item.segments) == 1 for item in plan.items), "whole book: one each"


def test_the_worker_receives_no_planner_and_no_destination_map(
        make_panel, tmp_path, captured_run):
    """Placement is decided by the plan, so it cannot depend on execution order."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    params = start_run(panel, tmp_path, captured_run)
    assert "planner" not in params
    assert "destinations" not in params
    assert isinstance(params["options"], m4b_converter.PlanOptions)


def test_direct_imports_stay_flat_in_the_run_root(make_panel, tmp_path, captured_run):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    plan = planned_run(panel, tmp_path, captured_run)
    for item in plan.items:
        assert item.segments[0].destination.parent == plan.run_directory


def test_a_folder_import_mirrors_its_source_hierarchy(make_panel, tmp_path, captured_run):
    """The Phase 8 behavioural change, still true through the Phase 10 plan."""
    root = tmp_path / "Library"
    books(root, "Top.m4b")
    books(root / "Series", "Nested.m4b")
    panel = make_panel()
    add_folder(panel, root)
    plan = planned_run(panel, tmp_path, captured_run)

    run = plan.run_directory
    assert planned_of(plan, "Top.m4b") == [run / "Top.mp3"]
    assert planned_of(plan, "Nested.m4b") == [run / "Series" / "Nested.mp3"]


def test_a_mixed_run_shares_one_collision_domain(make_panel, tmp_path, captured_run):
    """A direct book and a folder book both wanting ``Book.mp3`` must not collide."""
    root = tmp_path / "Library"
    books(root, "Book.m4b")
    panel = make_panel()
    add_files(panel, *books(tmp_path / "picked", "Book.m4b"))
    add_folder(panel, root)
    plan = planned_run(panel, tmp_path, captured_run)

    destinations = [item.segments[0].destination for item in plan.items]
    assert len(set(destinations)) == 2, destinations
    assert sorted(path.name for path in destinations) == ["Book-1.mp3", "Book.mp3"]


def test_duplicate_occurrences_receive_distinct_destinations(
        make_panel, tmp_path, captured_run):
    panel = make_panel()
    book, = books(tmp_path / "src", "Book.m4b")
    panel.importer.options.set_allow_duplicates(True)
    add_files(panel, book)
    add_files(panel, book)
    plan = planned_run(panel, tmp_path, captured_run)

    assert len(plan.items) == 2
    first, second = (item.segments[0].destination for item in plan.items)
    assert first != second
    assert sorted((first.name, second.name)) == ["Book-1.mp3", "Book.mp3"]


def test_no_destination_equals_an_input(make_panel, tmp_path, captured_run):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    plan = planned_run(panel, tmp_path, captured_run)
    sources = {item.source for item in plan.items}
    for item in plan.items:
        for segment in item.segments:
            assert segment.destination not in sources


def test_the_panel_defines_no_planning_of_its_own():
    """Phase 8 planning lives in the Converter-local bridge, not in the panel."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for banned in ("plan_outputs", "plan_flat", "plan_mirrored", "plan_multi_root",
                   "planning_groups", "DestinationPlanner"):
        assert banned not in defined, banned
