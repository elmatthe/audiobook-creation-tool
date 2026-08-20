"""TTS panel restructure and importer adoption — v0.6.1 Plan 4, Phase 6.

Phase 2 made the Cover panel the first production adopter of the Plan 3
importing foundation. This is the second, and it is a bigger change: the TTS
panel was a closure-based ``build_ui(parent)`` function with ~30 ``tk.*Var``s
captured in scope, and it had two *input models* — a Single-file browse box and
a Batch-folder browse box, chosen with a mode radio. Phase 6 replaces both with
**one unified PDF/TXT queue** (drop §4.5, decisions 1A and 2A) hosted on a
state-owning frame class.

What these tests are about
--------------------------
* **Composition, not reimplementation.** The panel reaches for the shared
  manager, coordinator, adapter and pump; it grows no second copy of any of
  them, no local scanner, no local dedup and no local natural sort.
* **The hoisted-copy boundary.** The old worker already read plain copies
  gathered on the main thread. That property is the reason a Phase 4 crash
  earlier in this project's history is not a recurring one, so it is measured
  here as an AST whitelist rather than promised in a comment.
* **Provenance still selects the processing path.** The retired radio said
  "single file" or "batch folder"; the queue now says "directly added" or
  "found under a folder", which is the same distinction carried by the shared
  importer itself. Directly added files keep the rich chapter/pause engine and
  flat placement (Decision 31A); folder-derived files keep the chunked batch
  worker and mirrored placement (Decision 7A).
* **EPUB stays retired.** Phase 5 closed it; nothing here may reopen it.

Determinism
-----------
**No test sleeps.** Scans run inline through the approved Phase 4 thread
factory and the pump is ticked by hand. The tests that are genuinely about
threads gate on :class:`threading.Event` and join within a bounded timeout, so
a deadlock fails loudly instead of hanging the suite.

Safety
------
Every fixture is generated under ``tmp_path``. Nothing scans the repository,
the real home directory, Downloads, an output base, runtime data or real media.
No dialog opens — the panel takes its dialogs as callbacks. **No synthesis ever
runs**: every engine entry point is replaced with a stub, so nothing reaches
Edge TTS over the network, loads a Kokoro model, or writes audio.

Scope
-----
Phase 6 changes importing and the panel's shape. Job control is Phase 7 and is
asserted *absent* below, along with every other later-phase vocabulary.
"""

from __future__ import annotations

import ast
import queue
import sys
import threading
from pathlib import Path, PurePath

import pytest

tk = pytest.importorskip("tkinter")

from shared import config as shared_config  # noqa: E402
from shared import output_paths as op  # noqa: E402
from shared import settings as app_settings  # noqa: E402
from shared.import_coordination import ImportCoordinator, OutcomeStatus  # noqa: E402
from shared.importing import (  # noqa: E402
    ImportedFile,
    ProblemCategory,
    ScanOutcome,
    ScanResult,
    planning_groups,
    scan_roots,
)

from tts import epub2tts_gui as panel_module  # noqa: E402

from test_import_coordination import (  # noqa: E402
    ControlledScanner,
    RecordingThreads,
    cancelled_result,
)
from test_import_traversal import touch  # noqa: E402
from test_importing import make_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PANEL_SOURCE = REPO_ROOT / "scripts" / "Universal" / "tts" / "epub2tts_gui.py"

#: Every wait here is bounded so a deadlock fails rather than hangs.
WAIT = 5.0


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # headless box with no display
        pytest.skip(f"Tk cannot open a display here: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture()
def output_base(tmp_path, monkeypatch):
    """A throwaway output base, so no test can reach the maintainer's real one."""
    base = tmp_path / "outputs"
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    shared_config.invalidate()
    monkeypatch.setattr(op, "resolve_output_base", lambda effective=None: base)
    try:
        yield base
    finally:
        app_settings.use_path(None)
        shared_config.invalidate()


@pytest.fixture()
def make_panel(tk_root):
    """Build a real ``TtsPanel`` with deterministic seams, and close it."""
    made: list[panel_module.TtsPanel] = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: False)
        panel = panel_module.TtsPanel(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


def sources(folder: Path, *names: str) -> tuple[Path, ...]:
    """Generated placeholder files. Never real media, never repository content."""
    return tuple(touch(folder / name, "Chapter One\n\nBody text.\n") for name in names)


class RecordingScanner:
    """Delegates to the real scanner and keeps every request and result."""

    def __init__(self):
        self.requests = []
        self.results = []

    def __call__(self, request, **kwargs):
        self.requests.append(request)
        result = scan_roots(request, **kwargs)
        self.results.append(result)
        return result


def synthetic_result(request, count: int) -> ScanResult:
    """A completed result of *count* files, built without touching a disk."""
    root = request.roots[0]
    base = root.path
    files = tuple(
        ImportedFile(
            occurrence_id=f"occ-{index}",
            path=base / f"{index:05d}.pdf",
            source_root=root,
            relative_path=PurePath(f"{index:05d}.pdf"),
            supported_type_id="pdf",
            identity=f"identity-{index}",
        )
        for index in range(count)
    )
    return ScanResult(
        request_id=request.request_id,
        outcome=ScanOutcome.COMPLETED,
        discovered_count=count,
        files=files,
        problems=(),
        completed_at=0.0,
    )


def drain_until(panel, predicate, message: str) -> None:
    """Tick the pump until *predicate* holds, or fail inside ``WAIT``.

    A released scanner runs on a real thread, so the outcome it publishes may not
    have arrived by the time the next tick does. This waits for it in bounded
    steps rather than sleeping a guessed amount: a scan that never publishes fails
    loudly at the deadline instead of hanging the suite or passing by luck.
    """
    import time as _time

    deadline = _time.monotonic() + WAIT
    gate = threading.Event()
    while _time.monotonic() < deadline:
        panel._pump.tick()
        if predicate():
            return
        gate.wait(0.01)
    panel._pump.tick()
    assert predicate(), message


def panel_tree() -> ast.Module:
    return ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"), filename=str(PANEL_SOURCE))


def method_named(name: str, *, owner: str = "TtsPanel") -> ast.AST:
    """One method of *owner*, by name. Nested helpers elsewhere cannot match."""
    for node in panel_tree().body:
        if isinstance(node, ast.ClassDef) and node.name == owner:
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == name:
                    return member
    raise AssertionError(f"{owner}.{name} is not defined in epub2tts_gui.py")


def imported_modules() -> set[str]:
    names: set[str] = set()
    for node in ast.walk(panel_tree()):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            for alias in node.names:
                names.add(f"{module}.{alias.name}" if module else alias.name)
    return names


# --------------------------------------------------------------------------- #
# A. The panel is a state-owning host with a real lifetime
# --------------------------------------------------------------------------- #


def test_the_panel_is_a_state_owning_frame_class():
    """The adapters need an object with a lifetime; a closure has none."""
    from tkinter import ttk

    assert issubclass(panel_module.TtsPanel, ttk.Frame)
    tree = panel_tree()
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "TtsPanel" in classes


def test_build_ui_still_honours_the_launcher_integration_contract(tk_root):
    """The launcher calls ``module.build_ui(container)`` and nothing else."""
    from tkinter import ttk

    container = ttk.Frame(tk_root)
    built = panel_module.build_ui(container)
    try:
        assert isinstance(built, panel_module.TtsPanel)
        assert built.winfo_parent() == str(container)
        assert built.winfo_manager(), "the panel packed itself into the container"
    finally:
        built.close()
        container.destroy()


def test_closing_the_panel_closes_the_importer_and_stops_the_pump(make_panel):
    panel = make_panel()
    assert panel._pump.running is True
    panel.close()
    assert panel.importer.closed is True
    assert panel._pump.closed is True
    assert panel._pump.pending is None, "no callback survived the close"
    panel.close()  # idempotent


def test_exactly_one_pump_owns_the_panels_scheduled_callbacks(make_panel):
    """One ``after`` chain: the import poller rides it and so do the two drains.

    Phase 7 added the shared job adapter, which registers its own drain on this
    same pump rather than starting a second one — so the count is two drains and
    still exactly one scheduled Tk callback.
    """
    panel = make_panel()
    registered = list(panel._pump._drains)
    assert panel._drain_worker_queue in registered
    assert panel.jobs.drain in registered
    assert len(registered) == 2, registered
    assert panel.importer.poller is not None

    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert source.count("MainThreadPump(") == 1


def test_the_old_recurring_after_loop_is_gone_from_the_source():
    """``pump_queue`` rescheduled itself with ``root.after(200, …)``; its
    replacement is a drain that never reschedules anything."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "pump_queue" not in source
    assert "root.after(" not in source
    drain = method_named("_drain_worker_queue")
    calls = {
        node.func.attr for node in ast.walk(drain)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "after" not in calls, "a drain must never reschedule itself"


def test_the_drain_still_delivers_the_engine_transcript_and_the_ending(make_panel):
    """The drain carries the transcript and the ending; it makes no state claim.

    Phase 7 moved progress and failure reporting onto the shared event stream, so
    the ``progress`` and ``err`` messages this drain used to carry are gone — a
    state a controller did not reach can no longer be drawn from this queue at all.
    """
    panel = make_panel()

    panel._busy.set()
    panel._log_q.put(("log", "hello\n"))
    panel._log_q.put(("done", "Conversion finished."))
    panel._pump.tick()
    assert "hello" in panel.log.get("1.0", "end")
    assert "Conversion finished." in panel.log.get("1.0", "end")
    assert panel._busy.is_set() is False

    drain = ast.unparse(method_named("_drain_worker_queue"))
    assert "'progress'" not in drain and '"progress"' not in drain
    assert "showerror" not in drain


def test_the_panel_registers_exactly_one_destination_display(make_panel):
    panel = make_panel()
    assert panel.var_outdir.get()
    assert PANEL_SOURCE.read_text(encoding="utf-8").count(
        "register_destination_hint") == 1


# --------------------------------------------------------------------------- #
# B. Main-thread safety
# --------------------------------------------------------------------------- #


def test_the_conversion_worker_reads_no_tk_variable_and_no_widget():
    """The Phase 4 crash class this project already paid for once.

    Measured as a whitelist of what the worker reaches for *on the panel*,
    which is strictly stronger than a blacklist of known-bad names.

    Phase 6 allowed ``_log_q`` and ``_cancel_event``. Phase 7 retired the second
    one — the run's controller is the only processing-cancel authority now — so the
    whitelist is one attribute narrower than it was.
    """
    worker = method_named("conversion_worker")
    reached = {
        node.attr for node in ast.walk(worker)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name) and node.value.id == "self"
    }
    assert reached == {"_log_q"}, reached


def test_no_worker_body_calls_get_on_a_tk_variable():
    """No ``.get()`` on a Tk variable anywhere below a worker entry point."""
    for name in ("conversion_worker",):
        body = ast.unparse(method_named(name))
        for forbidden in ("_var.get()", "var_outdir", "messagebox.", "ttk.",
                          "self.log", "self.progress", "self.importer",
                          "self._manager", "self.importer"):
            assert forbidden not in body, (name, forbidden)


def test_the_worker_is_handed_no_tk_object_and_no_live_import_state(
    make_panel, output_base, tmp_path, monkeypatch
):
    """Nothing the worker receives is a widget, a variable or the live queue.

    Phase 6 could state this as "plain built-ins only". Phase 7 hands the worker
    the run's controller, reporter and frozen snapshot as well, so the property is
    stated as what it always meant: no Tk object and no live import state crosses
    the thread boundary.
    """
    from shared import importing as shared_importing
    from shared import job_ui

    chosen = sources(tmp_path / "books", "one.txt")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()

    captured: dict = {}
    monkeypatch.setattr(panel_module.threading, "Thread",
                        lambda **kw: _FakeThread(kw, captured))
    panel.run_job()

    params = captured["params"]
    assert isinstance(params, dict)
    forbidden = (tk.Variable, tk.Misc, shared_importing.ImportedFileManager,
                 job_ui.ImportAdapter, job_ui.JobAdapter, job_ui.MainThreadPump)
    for key, value in params.items():
        assert not isinstance(value, forbidden), (key, type(value))
    for item in params["items"]:
        assert isinstance(item, dict)
        assert isinstance(item["source"], Path)
        assert isinstance(item["destination"], Path)
        assert isinstance(item["direct"], bool)
        assert isinstance(item["item_id"], str)


class _FakeThread:
    """Captures the worker's arguments instead of starting a thread."""

    def __init__(self, kwargs, sink):
        sink["params"] = kwargs["args"][0]
        sink["target"] = kwargs["target"]
        self.daemon = kwargs.get("daemon", False)

    def start(self):
        return None

    def join(self, timeout=None):
        return None


def test_the_manager_snapshot_is_captured_before_the_worker_starts(
    make_panel, output_base, tmp_path, monkeypatch
):
    """A later import cannot mutate a run that already started."""
    first = sources(tmp_path / "a", "one.txt")
    second = sources(tmp_path / "b", "two.txt")
    panel = make_panel(choose_files=lambda: first)
    panel.importer.add_files()

    captured: dict = {}
    monkeypatch.setattr(panel_module.threading, "Thread",
                        lambda **kw: _FakeThread(kw, captured))
    panel.run_job()
    frozen = [item["source"] for item in captured["params"]["items"]]

    panel.importer._choose_files = lambda: second
    panel.importer.add_files()

    assert frozen == list(first), "the captured list is a copy, not a live view"
    assert len(panel.imported_files()) == 2, "the manager did move on"


def test_every_import_entry_point_is_fenced_to_the_owner_thread(make_panel):
    from shared import job_ui

    panel = make_panel()
    failures: list[Exception] = []

    def offend():
        for action in (panel.importer.add_files, panel.importer.add_folder,
                       panel.importer.cancel_import):
            try:
                action()
            except Exception as exc:  # noqa: BLE001 - the point of the test
                failures.append(exc)

    worker = threading.Thread(target=offend, name="offending-worker")
    worker.start()
    worker.join(WAIT)
    assert not worker.is_alive()
    assert len(failures) == 3
    assert all(isinstance(exc, job_ui.MainThreadError) for exc in failures)


# --------------------------------------------------------------------------- #
# C. The catalog is exactly PDF and TXT
# --------------------------------------------------------------------------- #


def test_the_catalog_offers_exactly_pdf_and_txt():
    catalog = panel_module.build_catalog()
    assert catalog.type_ids == ("pdf", "txt")
    by_id = {entry.type_id: entry for entry in catalog.types}
    assert by_id["pdf"].extensions == (".pdf",)
    assert by_id["txt"].extensions == (".txt",)
    assert catalog.extensions == (".pdf", ".txt")


def test_the_catalog_carries_no_epub_entry():
    catalog = panel_module.build_catalog()
    assert ".epub" not in catalog.extensions
    assert "epub" not in catalog.type_ids


def test_every_offered_type_is_selected_by_default(make_panel):
    """Decision 16A: one control per type, all enabled."""
    panel = make_panel()
    assert set(panel.importer.options.selected_type_ids()) == set(
        panel.import_catalog.type_ids)
    assert panel.importer.options.options().has_selection is True


def test_hidden_folders_are_off_by_default(make_panel):
    panel = make_panel()
    assert panel.importer.options.options().include_hidden_folders is False


def test_duplicates_are_refused_by_default(make_panel):
    panel = make_panel()
    assert panel.importer.options.options().allow_duplicate_files is False


# --------------------------------------------------------------------------- #
# D. Add Files — the shared direct-file path
# --------------------------------------------------------------------------- #


def test_add_files_imports_several_pdf_and_txt_files(make_panel, tmp_path):
    chosen = sources(tmp_path / "books", "a.pdf", "b.txt", "c.pdf")
    panel = make_panel(choose_files=lambda: chosen)
    outcome = panel.importer.add_files()
    assert outcome.status is OutcomeStatus.COMMITTED
    assert panel.imported_files() == list(chosen)


def test_add_files_preserves_the_order_the_dialog_returned(make_panel, tmp_path):
    chosen = sources(tmp_path / "books", "10.pdf", "01.txt", "02.pdf")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    assert [p.name for p in panel.imported_files()] == ["10.pdf", "01.txt", "02.pdf"]


def test_add_files_goes_through_the_shared_direct_file_validation(
    make_panel, tmp_path, monkeypatch
):
    """TTS must not grow its own copy of ``validate_direct_files``."""
    import shared.import_coordination as coordination

    seen: list[tuple] = []
    real = coordination.validate_direct_files

    def spy(paths, **kwargs):
        seen.append(tuple(paths))
        return real(paths, **kwargs)

    monkeypatch.setattr(coordination, "validate_direct_files", spy)
    chosen = sources(tmp_path / "books", "a.pdf")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()

    assert seen == [chosen]
    assert "validate_direct_files" not in PANEL_SOURCE.read_text(encoding="utf-8")


def test_a_directly_added_occurrence_carries_direct_provenance(make_panel, tmp_path):
    chosen = sources(tmp_path / "books", "a.pdf")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    entry = panel.manager.snapshot().files[0]
    assert entry.mirroring_root is None
    assert planning_groups(panel.manager.snapshot()).direct == chosen


def test_a_cancelled_file_dialog_imports_nothing(make_panel):
    panel = make_panel(choose_files=lambda: ())
    assert panel.importer.add_files() is None
    assert panel.manager.count == 0


def test_the_add_files_button_is_wired_to_the_shared_action(make_panel, tmp_path):
    chosen = sources(tmp_path / "books", "a.pdf")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.list.buttons["add_files"].invoke()
    assert panel.manager.count == 1


# --------------------------------------------------------------------------- #
# E. Add Folder — the coordinator and the shared scanner
# --------------------------------------------------------------------------- #


def test_add_folder_runs_through_the_coordinator_and_the_shared_scanner(
    make_panel, tmp_path
):
    root = tmp_path / "Library"
    sources(root, "01.pdf", "02.txt")
    scanner = RecordingScanner()
    threads = RecordingThreads()
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner,
                       thread_factory=threads)

    panel.importer.list.buttons["add_folder"].invoke()
    panel._pump.tick()

    assert isinstance(panel.importer.coordinator, ImportCoordinator)
    assert len(scanner.requests) == 1
    assert scanner.requests[0].roots[0].path == root
    assert len(threads.made) == 1, "the coordinator owns the worker, not the panel"
    assert sorted(p.name for p in panel.imported_files()) == ["01.pdf", "02.txt"]


def test_folder_import_recurses_and_filters_to_pdf_and_txt(make_panel, tmp_path):
    root = tmp_path / "Library"
    sources(root, "top.pdf", "cover.jpg", "notes.md")
    sources(root / "Book 1", "inner.txt")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()
    assert sorted(p.name for p in panel.imported_files()) == ["inner.txt", "top.pdf"]


def test_folder_traversal_is_natural_order_with_files_before_child_directories(
    make_panel, tmp_path
):
    root = tmp_path / "Library"
    sources(root, "10.pdf", "2.pdf", "1.pdf")
    sources(root / "Extras", "bonus.txt")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()
    relatives = [
        str(entry.relative_path).replace("\\", "/")
        for entry in panel.manager.snapshot().files
    ]
    assert relatives == ["1.pdf", "2.pdf", "10.pdf", "Extras/bonus.txt"]


def test_a_hidden_folder_is_skipped_unless_the_shared_option_is_enabled(
    make_panel, tmp_path
):
    root = tmp_path / "Library"
    sources(root, "visible.pdf")
    sources(root / ".hidden", "secret.pdf")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()
    assert [p.name for p in panel.imported_files()] == ["visible.pdf"]


def _make_link(link: Path, target: Path) -> bool:
    if sys.platform == "win32":
        try:
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
            return True
        except (ImportError, OSError):
            return False
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        return False


def test_a_directory_link_is_never_followed(make_panel, tmp_path):
    root = tmp_path / "Library"
    real = root / "Real"
    sources(real, "01.pdf")
    if not _make_link(root / "Link", real):
        pytest.skip("this environment cannot create a directory link or junction")

    scanner = RecordingScanner()
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner)
    panel.importer.add_folder()
    panel._pump.tick()

    assert [p.name for p in panel.imported_files()] == ["01.pdf"], "imported once"
    assert scanner.results[0].problems_of(ProblemCategory.LINK), "the link is reported"


def test_the_broad_root_warning_is_answered_before_any_worker_starts(
    make_panel, tmp_path
):
    asked: list[tuple] = []
    threads = RecordingThreads()
    sources(tmp_path, "01.pdf")
    panel = make_panel(
        home=tmp_path, choose_folder=lambda: (tmp_path,), thread_factory=threads,
        confirm_broad_root=lambda roots: bool(asked.append(roots)))

    panel.importer.add_folder()

    assert asked == [(tmp_path,)], "asked exactly once, on this thread"
    assert threads.made == [], "declining creates no scan worker at all"
    assert panel.manager.count == 0


def test_the_configured_large_result_threshold_is_captured_onto_the_request(
    make_panel, tmp_path
):
    root = tmp_path / "Library"
    sources(root, "01.pdf")
    scanner = RecordingScanner()
    panel = make_panel(effective_config=make_config(7), choose_folder=lambda: (root,),
                       scanner=scanner)
    panel.importer.add_folder()
    panel._pump.tick()
    assert scanner.requests[0].large_result_warning_threshold == 7


def test_a_large_result_confirmation_commits_the_whole_transaction_at_once(
    make_panel, tmp_path
):
    root = tmp_path / "Library"
    sources(root, *[f"{index:02d}.pdf" for index in range(5)])
    panel = make_panel(effective_config=make_config(3), choose_folder=lambda: (root,),
                       confirm_large_result=lambda outcome: True)
    panel.importer.add_folder()
    panel._pump.tick()

    assert panel.manager.count == 5, "all five, or none — never a partial commit"
    panel._pump.tick()
    assert panel.manager.count == 5, "draining again must not commit a second time"


def test_a_declined_large_result_leaves_the_previous_queue_unchanged(
    make_panel, tmp_path
):
    already = sources(tmp_path / "Existing", "keep.pdf")
    root = tmp_path / "Library"
    sources(root, *[f"{index:02d}.pdf" for index in range(5)])
    panel = make_panel(effective_config=make_config(3), choose_files=lambda: already,
                       choose_folder=lambda: (root,),
                       confirm_large_result=lambda outcome: False)
    panel.importer.add_files()
    revision = panel.manager.revision
    panel.importer.add_folder()
    panel._pump.tick()

    assert panel.imported_files() == list(already)
    assert panel.manager.revision == revision


def test_a_cancelled_scan_leaves_no_partial_commit(make_panel, tmp_path):
    already = sources(tmp_path / "Existing", "keep.pdf")
    root = tmp_path / "Library"
    sources(root, "01.pdf")
    panel = make_panel(choose_files=lambda: already, choose_folder=lambda: (root,),
                       scanner=lambda request, **kw: cancelled_result(request, 1))
    panel.importer.add_files()
    revision = panel.manager.revision
    panel.importer.add_folder()
    panel._pump.tick()

    assert panel.imported_files() == list(already)
    assert panel.manager.revision == revision


def test_the_import_cancel_never_touches_the_processing_run(make_panel, tmp_path):
    """The two cancellation domains stay separate (drop §5.3).

    Phase 7 replaced the panel's processing ``threading.Event`` with the run's own
    :class:`~shared.job_control.JobController`, so "the conversion cancel is
    untouched" is now stated against that controller instead.
    """
    root = tmp_path / "Library"
    sources(root, "01.pdf")
    started, release = threading.Event(), threading.Event()
    scanner = ControlledScanner(counts=(1,), started=started, release=release)
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner,
                       thread_factory=None)

    panel.importer.add_folder()
    assert started.wait(WAIT), "the scanner never started"
    assert panel.importer.cancel_import() is True
    assert panel.importer.coordinator.cancel_requested is True
    release.set()
    panel._pump.tick()

    assert panel._controller is None, "no processing run was ever created"
    assert panel._busy.is_set() is False


def test_the_processing_cancel_never_touches_the_import(make_panel, tmp_path):
    root = tmp_path / "Library"
    sources(root, "01.pdf")
    started, release = threading.Event(), threading.Event()
    scanner = ControlledScanner(counts=(1,), started=started, release=release)
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner,
                       thread_factory=None)

    panel.importer.add_folder()
    assert started.wait(WAIT)
    # A processing cancel with a run under way reaches the controller and stops
    # exactly there; the coordinator running the scan never hears about it.
    panel._busy.set()
    panel.cancel_job()
    assert panel.importer.coordinator.cancel_requested is False

    release.set()
    drain_until(panel, lambda: panel.manager.count == 1,
                "the import completed on its own terms")
    panel._busy.clear()


def test_the_two_cancellations_are_different_authorities(make_panel):
    panel = make_panel()
    body = ast.unparse(method_named("cancel_job"))
    assert "request_cancel" in body, "processing cancel goes to the controller"
    assert "importer" not in body and "coordinator" not in body
    cancel_import = ast.unparse(method_named("close"))
    assert "request_cancel" in cancel_import


def test_closing_the_panel_mid_import_commits_nothing(make_panel, tmp_path):
    root = tmp_path / "Library"
    sources(root, "01.pdf")
    already = sources(tmp_path / "Existing", "keep.pdf")
    started, release = threading.Event(), threading.Event()
    scanner = ControlledScanner(counts=(1,), started=started, release=release)
    panel = make_panel(choose_files=lambda: already, choose_folder=lambda: (root,),
                       scanner=scanner, thread_factory=None)
    panel.importer.add_files()
    revision = panel.manager.revision

    panel.importer.add_folder()
    assert started.wait(WAIT), "the scanner never started"
    panel.close()
    release.set()
    panel._pump.tick()

    assert panel.imported_files() == list(already)
    assert panel.manager.revision == revision
    assert panel.importer.closed and panel._pump.closed


# --------------------------------------------------------------------------- #
# F. One unified queue — direct and folder-derived, together
# --------------------------------------------------------------------------- #


def _mixed_panel(make_panel, tmp_path, roots=1):
    """A queue holding two direct files and one or two folder roots."""
    direct = sources(tmp_path / "Loose", "solo.pdf", "notes.txt")
    folders = []
    for index in range(roots):
        root = tmp_path / f"Library {index + 1}"
        sources(root, "01.pdf")
        sources(root / "Book A", "02.txt")
        folders.append(root)

    chosen_folders = list(folders)

    def choose_folder():
        return (chosen_folders.pop(0),) if chosen_folders else ()

    panel = make_panel(choose_files=lambda: direct, choose_folder=choose_folder)
    panel.importer.add_files()
    for _ in folders:
        panel.importer.add_folder()
        panel._pump.tick()
    return panel, direct, tuple(folders)


def test_direct_files_and_folder_occurrences_coexist_in_one_manager(
    make_panel, tmp_path
):
    panel, direct, folders = _mixed_panel(make_panel, tmp_path)
    names = [p.name for p in panel.imported_files()]
    assert names == ["solo.pdf", "notes.txt", "01.pdf", "02.txt"]
    assert panel.manager.count == 4
    assert len(folders) == 1
    assert len(direct) == 2


def test_planning_groups_yields_both_direct_and_grouped_for_a_mixed_queue(
    make_panel, tmp_path
):
    panel, direct, folders = _mixed_panel(make_panel, tmp_path)
    groups = planning_groups(panel.manager.snapshot())
    assert groups.direct == direct
    assert groups.root_count == 1
    assert groups.grouped[0][0] == folders[0]
    assert groups.total == 4
    assert groups.needs_multi_root is False


def test_several_folder_roots_keep_their_identity_and_their_order(
    make_panel, tmp_path
):
    panel, _direct, folders = _mixed_panel(make_panel, tmp_path, roots=2)
    groups = planning_groups(panel.manager.snapshot())
    assert groups.root_count == 2
    assert [root for root, _sources in groups.grouped] == list(folders)
    assert groups.needs_multi_root is True, "Decision 41A applies to this snapshot"


def test_the_manager_snapshot_is_the_only_authority(make_panel, tmp_path):
    """Removing a row removes it from the run; nothing rediscovers it."""
    panel, _direct, _folders = _mixed_panel(make_panel, tmp_path)
    listing = panel.importer.list
    order = panel.manager.snapshot().occurrence_ids

    listing.select((order[2],))
    listing.buttons["remove"].invoke()
    assert [p.name for p in panel.imported_files()] == [
        "solo.pdf", "notes.txt", "02.txt"]
    assert planning_groups(panel.manager.snapshot()).grouped[0][1] == (
        panel.manager.snapshot().files[2].path,)


def test_move_and_clear_go_through_the_shared_manager(make_panel, tmp_path):
    chosen = sources(tmp_path / "books", "1.pdf", "2.pdf", "3.pdf")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    listing = panel.importer.list
    order = panel.manager.snapshot().occurrence_ids

    listing.select((order[2],))
    listing.buttons["move_up"].invoke()
    assert [p.name for p in panel.imported_files()] == ["1.pdf", "3.pdf", "2.pdf"]
    assert listing.selection == (order[2],), "selection is kept by occurrence id"

    listing.select((panel.manager.snapshot().occurrence_ids[0],))
    listing.buttons["move_down"].invoke()
    assert [p.name for p in panel.imported_files()] == ["3.pdf", "1.pdf", "2.pdf"]

    listing.buttons["clear"].invoke()
    assert panel.manager.count == 0
    assert all(path.exists() for path in chosen), "clearing the queue is not a delete"


def test_the_same_file_added_twice_is_refused_by_default(make_panel, tmp_path):
    chosen = sources(tmp_path / "books", "a.pdf")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    outcome = panel.importer.add_files()
    assert panel.manager.count == 1
    assert outcome.added_count == 0
    assert any(problem.category is ProblemCategory.DUPLICATE
               for problem in outcome.problems)


def test_a_deliberate_duplicate_stays_a_separate_occurrence(make_panel, tmp_path):
    chosen = sources(tmp_path / "books", "a.pdf")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    panel.importer.options.set_allow_duplicates(True)
    panel.importer.add_files()

    snapshot = panel.manager.snapshot()
    assert snapshot.count == 2
    first, second = snapshot.occurrence_ids
    assert first != second
    assert snapshot.identities[0] == snapshot.identities[1]
    assert panel.imported_files() == [chosen[0], chosen[0]]


# --------------------------------------------------------------------------- #
# G. The temporary Single/Batch workflow is gone
# --------------------------------------------------------------------------- #


def test_no_single_or_batch_mode_selector_remains():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    for retired in ("mode_var", "Radiobutton", '"single"', '"batch"',
                    "Single file (PDF / TXT)", "Batch folder"):
        assert retired not in source, retired


def test_no_legacy_input_path_state_survives():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    # ``askdirectory``/``askopenfilenames`` survive on purpose: they are the two
    # dialog *seams* the shared adapter calls on the main thread. What is gone is
    # the entry box, the variable behind it and the browse helper that wrote to it.
    for retired in ("input_var", "_browse_input", "Browse…"):
        assert retired not in source, retired
    assigned = {
        target.attr
        for node in ast.walk(panel_tree())
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
    }
    for retired in ("input", "input_path", "mode"):
        assert retired not in assigned, retired


def test_the_panel_writes_no_scanner_dedup_or_sort_of_its_own():
    """Every one of these already belongs to Plans 2 and 3."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    for retired in ("rglob(", "_natural_sort_key", "glob(", "is_hidden",
                    "os.walk", "iterdir("):
        assert retired not in source, retired


# --------------------------------------------------------------------------- #
# H. Output materialization
# --------------------------------------------------------------------------- #


def test_building_the_panel_reserves_nothing(make_panel, output_base):
    make_panel()
    assert not output_base.exists()


def test_importing_reserves_nothing(make_panel, output_base, tmp_path):
    panel, _direct, _folders = _mixed_panel(make_panel, tmp_path)
    assert panel.manager.count == 4
    assert not output_base.exists()


def test_starting_with_an_empty_queue_warns_and_reserves_nothing(
    make_panel, output_base, monkeypatch
):
    from tkinter import messagebox

    warned: list[tuple] = []
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: warned.append(a))
    panel = make_panel()
    panel.run_job()
    assert warned, "the empty-queue warning fires"
    assert panel._busy.is_set() is False
    assert not output_base.exists()


def test_a_mixed_queue_produces_exactly_one_run_directory(
    make_panel, output_base, tmp_path, monkeypatch
):
    panel, _direct, _folders = _mixed_panel(make_panel, tmp_path, roots=2)
    captured: dict = {}
    monkeypatch.setattr(panel_module.threading, "Thread",
                        lambda **kw: _FakeThread(kw, captured))
    panel.run_job()

    runs = sorted((output_base / "TTS-Audiobook-Outputs").iterdir())
    assert len(runs) == 1, runs
    assert captured["params"]["run_directory"] == runs[0]


def test_direct_files_land_flat_and_folder_files_mirror(
    make_panel, output_base, tmp_path, monkeypatch
):
    panel, _direct, folders = _mixed_panel(make_panel, tmp_path)
    captured: dict = {}
    monkeypatch.setattr(panel_module.threading, "Thread",
                        lambda **kw: _FakeThread(kw, captured))
    panel.run_job()

    run = captured["params"]["run_directory"]
    relatives = [
        str(item["destination"].relative_to(run)).replace("\\", "/")
        for item in captured["params"]["items"]
    ]
    speaker = captured["params"]["speaker"]
    assert relatives == [
        f"solo ({speaker}).mp3",       # direct, flat (Decision 31A)
        f"notes ({speaker}).mp3",      # direct, flat
        "01.mp3",                      # folder root, flat inside the root
        "Book A/02.mp3",               # folder root, mirrored (Decision 7A)
    ]
    assert len(folders) == 1


def test_two_folder_roots_each_get_their_own_container(
    make_panel, output_base, tmp_path, monkeypatch
):
    panel, _direct, _folders = _mixed_panel(make_panel, tmp_path, roots=2)
    captured: dict = {}
    monkeypatch.setattr(panel_module.threading, "Thread",
                        lambda **kw: _FakeThread(kw, captured))
    panel.run_job()

    run = captured["params"]["run_directory"]
    relatives = [
        str(item["destination"].relative_to(run)).replace("\\", "/")
        for item in captured["params"]["items"] if not item["direct"]
    ]
    assert relatives == [
        "Library 1/01.mp3", "Library 1/Book A/02.mp3",
        "Library 2/01.mp3", "Library 2/Book A/02.mp3",
    ]


def test_two_direct_files_with_the_same_stem_never_share_a_destination(
    make_panel, output_base, tmp_path, monkeypatch
):
    first = sources(tmp_path / "A", "Book.pdf")
    second = sources(tmp_path / "B", "Book.pdf")
    chosen = first + second
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()

    captured: dict = {}
    monkeypatch.setattr(panel_module.threading, "Thread",
                        lambda **kw: _FakeThread(kw, captured))
    panel.run_job()

    planned = [item["destination"] for item in captured["params"]["items"]]
    assert len(set(planned)) == 2, planned


def test_no_planned_destination_is_ever_one_of_the_inputs(
    make_panel, output_base, tmp_path, monkeypatch
):
    panel, _direct, _folders = _mixed_panel(make_panel, tmp_path)
    captured: dict = {}
    monkeypatch.setattr(panel_module.threading, "Thread",
                        lambda **kw: _FakeThread(kw, captured))
    panel.run_job()

    inputs = [item["source"] for item in captured["params"]["items"]]
    for item in captured["params"]["items"]:
        op.assert_not_input(item["destination"], inputs)
        assert op.assert_contained(captured["params"]["run_directory"],
                                   item["destination"])


def test_the_run_directory_is_reserved_only_after_validation():
    body = ast.unparse(method_named("run_job"))
    assert body.index("Missing input") < body.index("reserve_run_directory")
    assert "reserve_run_directory" not in ast.unparse(method_named("__init__"))


# --------------------------------------------------------------------------- #
# I. EPUB stays closed
# --------------------------------------------------------------------------- #


def test_an_epub_selected_directly_never_enters_the_queue(make_panel, tmp_path):
    chosen = sources(tmp_path / "books", "novel.epub", "real.pdf")
    panel = make_panel(choose_files=lambda: chosen)
    outcome = panel.importer.add_files()
    assert [p.name for p in panel.imported_files()] == ["real.pdf"]
    assert any(problem.category is ProblemCategory.UNSUPPORTED_TYPE
               for problem in outcome.problems)


def test_an_epub_found_by_a_folder_scan_never_enters_the_queue(make_panel, tmp_path):
    root = tmp_path / "Library"
    sources(root, "novel.epub", "real.txt")
    scanner = RecordingScanner()
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner)
    panel.importer.add_folder()
    panel._pump.tick()

    assert [p.name for p in panel.imported_files()] == ["real.txt"]
    unsupported = scanner.results[0].problems_of(ProblemCategory.UNSUPPORTED_TYPE)
    assert {Path(problem.path).name for problem in unsupported} == {"novel.epub"}


def test_no_epub_type_can_be_selected_in_the_shared_options(make_panel):
    """There is no EPUB control to tick, so asking for one selects nothing."""
    panel = make_panel()
    remaining = panel.importer.options.set_types({"epub"})
    assert remaining == frozenset()
    assert "epub" not in panel.importer.options.type_vars
    assert panel.importer.options.options().has_selection is False


def test_the_internal_dispatch_boundary_still_refuses_an_epub(tmp_path):
    """Phase 5's engine gate, unchanged and not re-guarded here."""
    from tts.epub2tts_edge.runner import run_conversion_job

    book = tmp_path / "novel.epub"
    book.write_bytes(b"PK\x03\x04not-really-an-epub")
    with pytest.raises(ValueError):
        run_conversion_job(str(book), output_dir=str(tmp_path / "out"))


# --------------------------------------------------------------------------- #
# J. The engines and their semantics are unchanged
# --------------------------------------------------------------------------- #


class _Stubs:
    """Replaces every engine entry point. Nothing synthesises, nothing downloads."""

    def __init__(self):
        self.conversion_jobs: list[dict] = []
        self.batch_items: list[dict] = []
        self.kokoro_calls: list[dict] = []
        self.extracted: list[tuple[str, str]] = []

    def install(self, monkeypatch):
        from tts import batch_convert
        from tts import pdf_extractor
        from tts.epub2tts_edge import runner

        def run_conversion_job(sourcefile, **kwargs):
            self.conversion_jobs.append({"source": sourcefile, **kwargs})
            produced = Path(kwargs["output_dir"]) / (
                f"{Path(sourcefile).stem} ({kwargs['speaker']}).mp3")
            produced.parent.mkdir(parents=True, exist_ok=True)
            produced.write_bytes(b"audio")
            return str(produced)

        def convert_single_pdf(path, output_dir, speaker, rate, log=print,
                               progress_report=None, cancel_check=None, out_mp3=None,
                               bitrate=None):
            self.batch_items.append({
                "source": path, "output_dir": output_dir, "speaker": speaker,
                "rate": rate, "out_mp3": out_mp3, "bitrate": bitrate})
            Path(out_mp3).parent.mkdir(parents=True, exist_ok=True)
            Path(out_mp3).write_bytes(b"audio")
            if progress_report is not None:
                progress_report(Path(path).stem, "completed")
            return "success", Path(path), None

        def pdf_to_txt(source_path, target):
            self.extracted.append((str(source_path), str(target)))
            Path(target).write_text("Body text.\n", encoding="utf-8")
            return target

        monkeypatch.setattr(runner, "run_conversion_job", run_conversion_job)
        monkeypatch.setattr(batch_convert, "convert_single_pdf", convert_single_pdf)
        monkeypatch.setattr(pdf_extractor, "pdf_to_txt", pdf_to_txt)
        return self

    def install_kokoro(self, monkeypatch):
        import types

        module = types.ModuleType("tts.kokoro_synth")

        def kokoro_file_to_mp3(source_path, output_mp3_path, voice_id, **kwargs):
            self.kokoro_calls.append({
                "source": source_path, "output": output_mp3_path,
                "voice_id": voice_id, **kwargs})
            Path(output_mp3_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_mp3_path).write_bytes(b"audio")

        module.kokoro_file_to_mp3 = kokoro_file_to_mp3
        monkeypatch.setitem(sys.modules, "tts.kokoro_synth", module)
        return self


@pytest.fixture()
def stubs(monkeypatch):
    from tts.epub2tts_edge import epub2tts_edge as engine

    monkeypatch.setattr(engine, "ensure_punkt", lambda: None)
    monkeypatch.setattr(panel_module, "ensure_punkt", lambda: None)
    return _Stubs().install(monkeypatch)


def _run_to_completion(panel, before_worker=None):
    """Run the worker body inline on this thread, then drain the queue.

    ``before_worker`` runs after ``run_job`` has frozen the queue and reserved the
    run, and before the worker body executes — which is the only moment a test can
    arm the conversion cancel, since ``run_job`` clears it on the way in.
    """
    captured: dict = {}
    real_thread = panel_module.threading.Thread
    try:
        panel_module.threading.Thread = lambda **kw: _FakeThread(kw, captured)
        panel.run_job()
    finally:
        panel_module.threading.Thread = real_thread
    if before_worker is not None:
        before_worker()
    if "target" in captured:
        captured["target"](captured["params"])
    panel._pump.tick()
    return captured.get("params", {})


def test_a_directly_added_file_still_reaches_the_rich_edge_engine(
    make_panel, output_base, tmp_path, stubs
):
    """Today's single-file path, with its pause and trim settings, is preserved."""
    chosen = sources(tmp_path / "books", "solo.txt")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    params = _run_to_completion(panel)

    assert len(stubs.conversion_jobs) == 1
    job = stubs.conversion_jobs[0]
    assert job["source"] == str(chosen[0])
    assert job["audio_format"] == "mp3"
    assert job["mp3_bitrate"] == "192k"
    assert job["sentencepause"] == 800
    assert job["paragraphpause"] == 850
    assert job["title_trailing_pause"] == 1200
    assert job["chapter_trailing_pause"] == 2000
    assert job["end_of_book_pause"] == 3000
    assert job["trim_tts_padding"] is True
    assert job["trim_silence_db"] == -58.0
    assert stubs.batch_items == [], "a direct file never takes the batch worker"
    assert params["items"][0]["destination"].exists()


def test_a_folder_derived_file_still_reaches_the_batch_worker_with_its_target(
    make_panel, output_base, tmp_path, stubs
):
    root = tmp_path / "Library"
    sources(root, "01.pdf")
    sources(root / "Book A", "02.pdf")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()
    params = _run_to_completion(panel)

    assert len(stubs.batch_items) == 2
    run = params["run_directory"]
    targets = sorted(
        str(Path(item["out_mp3"]).relative_to(run)).replace("\\", "/")
        for item in stubs.batch_items)
    assert targets == ["01.mp3", "Book A/02.mp3"]
    for item in stubs.batch_items:
        assert Path(item["output_dir"]) == run, (
            "the batch worker still keys its temp-chunk dir on the run root")
        assert item["speaker"] == "en-US-SteffanNeural"
        assert item["rate"] == "+0%"
    assert stubs.conversion_jobs == [], "a folder file never takes the single path"


def test_a_mixed_queue_runs_both_paths_in_one_run(
    make_panel, output_base, tmp_path, stubs
):
    panel, _direct, _folders = _mixed_panel(make_panel, tmp_path)
    params = _run_to_completion(panel)

    assert len(stubs.conversion_jobs) == 2, "the two directly added files"
    assert len(stubs.batch_items) == 2, "the two folder-derived files"
    run = params["run_directory"]
    for item in params["items"]:
        assert item["destination"].exists(), item["destination"]
        assert item["destination"].is_relative_to(run)


def test_a_kokoro_voice_still_takes_the_kokoro_engine_for_both_provenances(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    from tts import voice_registry as vr

    stubs.install_kokoro(monkeypatch)
    kokoro = next(voice for voice in vr.VOICES if voice.backend == "kokoro")
    panel, _direct, _folders = _mixed_panel(make_panel, tmp_path)
    panel.selected_voice_label.set(kokoro.display_label)
    panel._on_voice_selected()
    params = _run_to_completion(panel)

    assert len(stubs.kokoro_calls) == 4
    assert {call["voice_id"] for call in stubs.kokoro_calls} == {kokoro.voice_id}
    assert stubs.conversion_jobs == [] and stubs.batch_items == []
    run = params["run_directory"]
    relatives = sorted(
        str(Path(call["output"]).relative_to(run)).replace("\\", "/")
        for call in stubs.kokoro_calls)
    assert relatives == ["01.mp3", "Book A/02.mp3", "notes.mp3", "solo.mp3"]


def test_a_kokoro_pdf_still_goes_through_the_extractor_first(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    from tts import voice_registry as vr

    stubs.install_kokoro(monkeypatch)
    kokoro = next(voice for voice in vr.VOICES if voice.backend == "kokoro")
    chosen = sources(tmp_path / "books", "solo.pdf")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    panel.selected_voice_label.set(kokoro.display_label)
    panel._on_voice_selected()
    _run_to_completion(panel)

    assert [source for source, _target in stubs.extracted] == [str(chosen[0])]
    assert len(stubs.kokoro_calls) == 1
    assert stubs.kokoro_calls[0]["source"] != str(chosen[0]), "a temp .txt is used"


def test_the_worker_stops_at_the_existing_cancellation_checkpoint(
    make_panel, output_base, tmp_path, stubs
):
    """Cancelled before the first file: the run converts nothing and says so.

    Phase 7 arms this through the run's controller rather than the panel's retired
    ``threading.Event`` — the controller is the only processing-cancel authority.
    """
    chosen = sources(tmp_path / "books", "a.txt", "b.txt", "c.txt")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    _run_to_completion(panel, before_worker=lambda: panel._controller.request_cancel())

    assert stubs.conversion_jobs == [], "a cancelled run converts nothing"
    assert "Cancelled." in panel.log.get("1.0", "end")
    assert panel._controller.state.value == "cancelled"


def test_the_panel_reimplements_no_engine_and_changes_no_timing_default():
    """The engines are consumed, never copied, and their constants are untouched."""
    from tts import batch_convert
    from tts import voice_registry as vr
    from tts.epub2tts_edge import epub2tts_edge as engine

    defined = {
        node.name for node in ast.walk(panel_tree())
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for engine_symbol in ("read_book", "run_edgespeak", "make_mp3", "make_m4b",
                          "convert_single_pdf", "run_batch_convert",
                          "kokoro_file_to_mp3", "pdf_to_txt", "split_into_chunks"):
        assert engine_symbol not in defined, engine_symbol

    assert engine.DEFAULT_SPEAKER == "en-US-SteffanNeural"
    assert engine.DEFAULT_SENTENCE_PAUSE_MS == 800
    assert engine.DEFAULT_PARAGRAPH_PAUSE_MS == 850
    assert engine.DEFAULT_TITLE_PAUSE_MS == 1200
    assert engine.DEFAULT_CHAPTER_PAUSE_MS == 2000
    assert engine.DEFAULT_END_OF_BOOK_PAUSE_MS == 3000
    assert engine.DEFAULT_TRIM_SILENCE_DB == -58.0
    assert batch_convert.PDF_MAX_RETRIES == 2
    assert batch_convert.CHUNK_MAX_RETRIES == 5
    assert batch_convert.INTER_CHUNK_DELAY_SEC == 0.8
    assert len(vr.VOICES) == 16
    assert vr.DEFAULT_VOICE_LABEL == vr.display_labels()[0]


def test_the_voice_dropdown_still_applies_a_timing_preset(make_panel):
    from tts import voice_registry as vr

    panel = make_panel()
    kokoro = next(voice for voice in vr.VOICES if voice.backend == "kokoro")
    panel.selected_voice_label.set(kokoro.display_label)
    panel._on_voice_selected()
    assert panel.voice_var.get() == kokoro.voice_id
    assert panel.sentence_ms_var.get() == kokoro.timing_preset["sentencepause"]
    assert panel.trim_edge_chunks_var.get() is False


# --------------------------------------------------------------------------- #
# K. The phase boundary — nothing from Phase 7 or later arrived
# --------------------------------------------------------------------------- #


def test_the_panel_composes_the_importer_and_the_pump():
    modules = imported_modules()
    assert "shared.importing" in modules
    assert "shared.import_coordination" in modules
    assert "shared.job_ui" in modules


def test_the_panel_reimplements_none_of_the_shared_foundation():
    forbidden = {
        "ImportedFileManager", "ImportCoordinator", "ImportPoller", "ImportAdapter",
        "MainThreadPump", "ImportedFileList", "ImportOptionsBar", "ImportStatusBar",
        "JobController", "JobAdapter",
    }
    defined = {
        node.name for node in ast.walk(panel_tree())
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not (defined & forbidden), defined & forbidden


def test_the_job_control_vocabulary_is_consumed_and_never_reimplemented():
    """Phase 7 adopted all of this. It is imported, and none of it is redefined.

    This test was written in Phase 6 to assert the *absence* of job control, which
    was correct while Phase 7 was unauthorized. Phase 7 delivered it, so the guard
    is inverted rather than dropped: the panel must reach for the shared symbols and
    must define none of them itself.
    """
    assert "shared.job_control" in imported_modules()
    defined = {
        node.name for node in ast.walk(panel_tree())
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for shared_symbol in ("JobController", "JobAdapter", "JobControlBar",
                          "JobStatusView", "SummaryDetailsView", "capture_run",
                          "JobReporter", "JobEventStream", "RunResult",
                          "RetryRequest", "EtaEstimator", "ProgressTracker"):
        assert shared_symbol not in defined, shared_symbol
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "LOCK_MATRIX = " not in source, "the lock matrix is consulted, not restated"


def test_no_chatterbox_or_later_phase_vocabulary_arrived():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    # Retargeted at Phase 10: the panel may name the local cloning engine, which
    # is what Phase 10 was authorized to integrate. The model stack itself must
    # still never be imported here — see test_chatterbox_integration.py.
    for later in ("torch", "pillow_heif", "resemble_perth", "librosa"):
        assert later not in source, later
    # The panel may import this project's engine wrapper; it may never import the
    # third-party model package, which is what would drag torch into a GUI build.
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots = {(node.module or "").split(".")[0]}
        else:
            continue
        assert "chatterbox" not in roots, ast.dump(node)
    # ``archived-code`` is excluded from the substring sweep on purpose: Phase 5's
    # module header cites the archive manifest, which is prose. That the path is
    # never an *executable* string is the property that matters, and it is proved
    # here the same way ``test_epub_retirement`` proves it — by AST.
    tree = panel_tree()
    prose = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef))
        and getattr(node, "body", None)
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in prose:
                continue
            assert "archived-code" not in node.value, node.value


def test_the_panel_still_imports_nothing_from_the_archive():
    assert not [name for name in imported_modules() if "archived" in name]
