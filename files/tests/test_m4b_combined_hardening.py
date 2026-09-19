"""v0.6.4 Phase 11 — the combined M4B Maker + Metadata Editor hardening matrix.

Both tools are production adopters of the shared multi-Book workspace, the
Plan 3 importer/job architecture and the shared output service. Phases 1–10
proved each layer on its own; this file adds only what a **combined system**
still lacked proof of — the cross-layer, race-sensitive and end-to-end cases
of the plan's Phase 11 matrix — and deliberately does not repeat a unit fact a
Phase suite already pins:

- the two product projections (one directory = one Maker Book; one occurrence
  = one Editor Book) coexist in one process through one workspace/import
  architecture, differing only in the projection function;
- after Start, every kind of later live mutation — Shared, Book, artwork,
  chapters, Book order/set, imported files, run options — reaches neither the
  active run nor Retry Failed, for both tools, through the production panels;
- race boundaries on real worker threads: the settled result exists before
  the terminal event; a retry attempt starts only after the prior attempt is
  terminal and gets its own controller/adapter while a stale run's events
  stay inert; Cancel arriving during publication keeps that Book and stops at
  the boundary; a Pause requested at a Book boundary is acknowledged before
  the next Book; synchronised with ``threading.Event``, never a sleep;
- output naming under Unicode, long and awkward names for both tools;
- the common artwork architecture through both consumers, HEIC included
  where the machine can decode it;
- the Maker's A succeeds / B fails / C succeeds numbering and Retry Failed
  through the production panel, and the Editor's full processing chain.
"""

from __future__ import annotations

import ast
import hashlib
import threading
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

import tk_gate  # noqa: E402

from shared import image_capabilities, metadata, output_paths, ui_theme  # noqa: E402
from shared.book_workspace import BookDisposition  # noqa: E402
from shared.book_workspace_ui import BookNavigator  # noqa: E402
from shared.job_control import JobController, JobEventKind, JobReporter, JobState  # noqa: E402

from mp3_tools import m4b_artwork, m4b_maker, m4b_metadata_editor as editor  # noqa: E402
from mp3_tools import m4b_maker_batch, m4b_maker_plan, m4b_maker_processing  # noqa: E402
from mp3_tools import m4b_maker_workflow as maker_wf  # noqa: E402
from mp3_tools import m4b_metadata_batch, m4b_metadata_processing  # noqa: E402
from mp3_tools import m4b_metadata_workflow as editor_wf  # noqa: E402
from mp3_tools.m4b_metadata_plan import EditorAction  # noqa: E402

from test_import_coordination import RecordingThreads  # noqa: E402
from test_import_traversal import touch  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_artwork import heic, jpg  # noqa: E402
from test_m4b_maker_batch import (  # noqa: E402,F401 - fixtures by import, aliased
    make_run as maker_run, reserve as maker_reserve, three_books as maker_three, tone,
)
from test_m4b_metadata_batch import (  # noqa: E402,F401
    make_run as editor_run, reserve as editor_reserve, three_books as editor_three,
)
from test_m4b_metadata_processing import audio_md5, container, png  # noqa: E402,F401
from test_m4b_metadata_workflow import m4b  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"


# --------------------------------------------------------------------------- #
# Fixtures: both production panels on one root, deterministic seams
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def windows_theme(tk_root):
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style, platform="win32")
    yield theme
    restore = ttk.Style(tk_root)
    if "vista" in restore.theme_names():
        restore.theme_use("vista")


@pytest.fixture
def output_base(tmp_path, monkeypatch):
    base = tmp_path / "Outputs"
    monkeypatch.setattr(output_paths, "resolve_output_base", lambda effective=None: base)
    return base


def _seams(**overrides):
    seams = dict(effective_config=make_config(), clock=lambda: 0.0, home=None,
                 thread_factory=RecordingThreads(), choose_files=lambda: (),
                 choose_folder=lambda: (), choose_artwork=lambda: "",
                 confirm_broad_root=lambda roots: False,
                 confirm_large_result=lambda outcome: True,
                 confirm=lambda title, message: True)
    seams.update(overrides)
    return seams


@pytest.fixture
def panels(tk_root, windows_theme, monkeypatch, output_base):
    """Build either or both production panels with deterministic seams."""
    made = []
    dialogs: list[tuple[str, str, str]] = []
    for module, tag in ((m4b_maker, "maker"), (editor, "editor")):
        monkeypatch.setattr(module.messagebox, "showerror",
                            lambda title, message, _t=tag, **kw: dialogs.append((_t, "error", message)))
        monkeypatch.setattr(module.messagebox, "showwarning",
                            lambda title, message, _t=tag, **kw: dialogs.append((_t, "warning", message)))

    def maker(**overrides):
        panel = m4b_maker.M4BMakerUI(tk_root, theme=windows_theme,
                                     choose_destination=lambda: "", **_seams(**overrides))
        made.append(panel)
        return panel

    def make_editor(**overrides):
        panel = editor.M4BMetadataEditorUI(tk_root, theme=windows_theme, **_seams(**overrides))
        made.append(panel)
        return panel

    maker.editor = make_editor  # type: ignore[attr-defined]
    maker.dialogs = dialogs  # type: ignore[attr-defined]
    yield maker
    for panel in made:
        panel.close()
        try:
            panel.destroy()
        except tk.TclError:
            pass


@pytest.fixture
def maker_sources(tmp_path: Path) -> Path:
    root = tmp_path / "MakerSources"
    root.mkdir()
    return root


@pytest.fixture
def editor_sources(tmp_path: Path) -> Path:
    root = tmp_path / "EditorSources"
    root.mkdir()
    return root


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(path: Path) -> tuple[str, int]:
    return sha(path), path.stat().st_mtime_ns


def import_folder(panel, root: Path):
    panel._choose_folder = lambda: (str(root),)
    panel.import_folder()
    panel._pump.tick()
    return panel.workspace


def add_files(panel, *paths: Path):
    panel._choose_files = lambda: tuple(str(p) for p in paths)
    panel.add_files()
    return panel.workspace


def parked_threads():
    import test_import_coordination as tic

    class Parked(tic.InlineThread):
        def start(self):
            pass

    return RecordingThreads(kind=Parked)


def editor_library(container: Path, root: Path) -> Path:
    m4b(container, root / "Alpha.m4b", title="Alpha", artist="Ann", series="Saga",
        series_part="1", genre="Old")
    m4b(container, root / "Beta.m4b", title="Beta", artist="Ann", series="Saga",
        series_part="2", genre="Old")
    m4b(container, root / "More" / "Gamma.m4a", title="Gamma", artist="Ann")
    return root


def maker_library(root: Path) -> Path:
    tone(root / "A" / "01.mp3")
    tone(root / "B" / "01.mp3")
    tone(root / "C" / "01.mp3")
    return root


def covr_of(path: Path) -> list:
    from mutagen.mp4 import MP4

    tags = MP4(str(path)).tags
    return list(tags.get("covr", [])) if tags else []


def break_editor_book(monkeypatch, panel, index: int):
    """Make one Editor Book's tag write fail at its frozen staged path."""
    real = metadata.write_m4b_tags
    target = {"path": None}

    def broken(path, tags, total=None):
        if target.get("armed", True) and target["path"] is not None                 and Path(path) == target["path"]:
            raise RuntimeError("tag write refused")
        return real(path, tags, total=total)

    monkeypatch.setattr(metadata, "write_m4b_tags", broken)
    original = panel._start_attempt

    def start_and_break(begin, label):
        if target["path"] is None and target.get("armed", True):
            target["path"] = panel.last_plan.books[index].staged
        original(begin, label)

    panel._start_attempt = start_and_break
    return target


# --------------------------------------------------------------------------- #
# 1. Shared workspace: two projections, one architecture, one process
# --------------------------------------------------------------------------- #


def test_the_two_projections_coexist_in_one_process_through_one_architecture(
        panels, container, tmp_path):
    maker = panels()
    ed = panels.editor()
    maker_root = tmp_path / "MakerLib"
    touch(maker_root / "Vol 1" / "01.mp3", "not audio")
    touch(maker_root / "Vol 1" / "02.mp3", "not audio")
    touch(maker_root / "Vol 2" / "01.mp3", "not audio")
    import_folder(maker, maker_root)
    import_folder(ed, editor_library(container, tmp_path / "EditorLib"))
    # One directory = one Maker Book; one file = one Editor Book, even side by side.
    assert [book.file_count for book in maker.workspace.books] == [2, 1]
    assert [book.file_count for book in ed.workspace.books] == [1, 1, 1]
    assert ed.workspace.count == 3 and maker.workspace.count == 2
    maker_ids = {book.book_id for book in maker.workspace.books}
    editor_ids = {book.book_id for book in ed.workspace.books}
    assert maker_ids.isdisjoint(editor_ids), "two workspaces, one id vocabulary, no sharing"
    # Both navigators are the one shared adapter, differing only in the action subset.
    assert type(maker.navigator) is type(ed.navigator) is BookNavigator
    assert maker.navigator.actions == BookNavigator.BOOK_ACTIONS
    assert ed.navigator.actions == (BookNavigator.REMOVE,)
    # Maker Duplicate copies configuration and starts with no inputs; the Editor offers none.
    maker.set_book_field("title", "Copied Title")
    maker.on_duplicate()
    copied = maker.workspace.current
    assert copied.configuration.get("title") == "Copied Title" and copied.files.is_empty
    assert not hasattr(ed, "on_duplicate")
    # Selector identity after removal, on both: the rows resolve to the surviving ids.
    ed.on_select(ed.workspace.books[1].book_id)
    ed.on_remove(True)
    survivors = [book.book_id for book in ed.workspace.books]
    assert len(survivors) == 2 and ed.navigator.selector_ids == tuple(survivors)
    maker.on_previous()
    maker.on_remove(True)
    assert maker.navigator.selector_ids == tuple(b.book_id for b in maker.workspace.books)
    # Shared override → clear → restore, independently per tool.
    ed.surface.set_shared_text("genre", "G")
    assert ed.book_field_enabled("genre") is False and maker.book_field_enabled("album") is True
    ed.surface.set_shared_text("genre", "")
    own = editor_wf.prefill_values(ed.store.for_book(ed.workspace.current))["genre"]
    assert ed.book_field_enabled("genre") is True and ed.book_value("genre") == own
    # The other workspace was never touched by any of it.
    assert maker.workspace.shared.values == {}


def test_both_workflow_models_project_through_the_shared_workspace_not_a_second_one():
    """Structural: the projections differ in one function each; the rest is shared."""
    shared_ops = {"replace_book", "new_book_id", "WorkspaceSnapshot", "BookJob", "BookMutation",
                  "SharedMetadata", "effective_metadata"}
    for module, name in ((maker_wf, "maker"), (editor_wf, "editor")):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                    and node.module == "shared.book_workspace" for alias in node.names}
        assert shared_ops <= imported, (name, shared_ops - imported)
        declared = {node.name for node in ast.walk(tree)
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
        for owned_by_shared in ("WorkspaceSnapshot", "BookJob", "select_book", "next_book",
                                "previous_book", "remove_book", "duplicate_book",
                                "capture_workspace_run", "retry_failed_books"):
            assert owned_by_shared not in declared, (name, owned_by_shared)
    maker_tree = ast.parse(Path(maker_wf.__file__).read_text(encoding="utf-8"))
    maker_calls = {ast.unparse(n.func) for n in ast.walk(maker_tree) if isinstance(n, ast.Call)}
    assert "replace_workspace_from_import" in maker_calls, (
        "the Maker's directory grouping is the shared projection, called, not restated")
    editor_tree = ast.parse(Path(editor_wf.__file__).read_text(encoding="utf-8"))
    editor_calls = {ast.unparse(n.func) for n in ast.walk(editor_tree) if isinstance(n, ast.Call)}
    assert "replace_workspace_from_import" not in editor_calls, (
        "the Editor never groups by directory: one occurrence is one Book")
    assert "planning_groups" not in ast.unparse(editor_tree)


# --------------------------------------------------------------------------- #
# 2. Frozen state: every later live mutation, both tools, through the panels
# --------------------------------------------------------------------------- #


def test_maker_run_and_retry_ignore_every_later_live_mutation(panels, tmp_path, output_base):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    bad = touch(root / "B" / "01.mp3", "not audio")
    art, late_art = png(tmp_path / "art.png"), png(tmp_path / "late.png")
    maker = panels()
    import_folder(maker, root)
    maker.on_shared_change("album", "Frozen Album")
    maker.set_book_field("title", "Alpha")
    maker.type_chapter_titles("One")
    maker._choose_artwork = lambda: str(art)
    maker.choose_book_artwork()
    maker._thread_factory = parked_threads()
    assert maker.build() is True
    plan = maker.last_plan
    # Every kind of later mutation the plan names, while the run is parked.
    maker.on_shared_change("album", "Late Album")
    maker.on_shared_change("artist", "Late Artist")
    maker._choose_artwork = lambda: str(late_art)
    maker.choose_shared_artwork()
    maker.set_book_field("title", "Changed")
    maker.type_chapter_titles("Late")
    add_files(maker, tone(tmp_path / "extra" / "99.mp3"))
    maker.on_duplicate()
    maker.on_remove(True)
    maker.var_auto_number.set(True)
    maker.var_start_part.set("9")
    maker.var_fast_first.set(False)
    maker.var_custom_dest.set(True)
    maker.var_custom_path.set(str(tmp_path / "custom"))
    maker._thread_factory.bodies[0]()
    maker._pump.tick()
    assert maker.last_result.state is JobState.COMPLETED_WITH_FAILURES
    alpha = plan.books[0]
    tags = metadata.read_m4b_tags(alpha.published)
    assert tags["title"] == "Alpha" and tags["album"] == "Frozen Album"
    assert not tags.get("artist") and not tags.get("series_part")
    assert metadata.read_chapter_titles(alpha.published) == ["One"]
    assert bytes(covr_of(alpha.published)[0]) == art.read_bytes()
    assert alpha.published.parent == output_base / "M4B-Maker-Outputs" / "M4B-Maker-1"
    before = stamp(alpha.published)
    # Retry, after yet more mutation: the same frozen plan, the same run, no reservation.
    tone(bad)
    maker.on_shared_change("album", "Later Still")
    assert maker.retry_failed() is True
    maker._thread_factory.bodies[1]()
    maker._pump.tick()
    assert maker.last_plan is plan and maker.last_result.state is JobState.SUCCEEDED
    beta = metadata.read_m4b_tags(plan.books[1].published)
    assert beta["album"] == "Frozen Album" and beta["title"] == plan.books[1].title
    assert plan.books[1].title == "Frozen Album", "the frozen Decision 51A fallback, not 'Changed'"
    assert stamp(alpha.published) == before
    assert len(list((output_base / "M4B-Maker-Outputs").iterdir())) == 1
    assert not (tmp_path / "custom").exists()


def test_editor_run_and_retry_ignore_every_later_live_mutation(panels, container, tmp_path,
                                                                output_base, monkeypatch):
    root = editor_library(container, tmp_path / "Library")
    art, late_art = png(tmp_path / "art.png"), png(tmp_path / "late.png")
    ed = panels.editor()
    import_folder(ed, root)
    ed.surface.set_shared_text("genre", "Frozen G")
    ed.set_book_field("title", "Alpha Edited")
    ed.type_chapter_titles("\nThe End")
    ed._choose_artwork = lambda: str(art)
    ed.choose_book_artwork()
    target = break_editor_book(monkeypatch, ed, 1)
    ed._thread_factory = parked_threads()
    assert ed.save() is True
    plan = ed.last_plan
    # Every later mutation, while parked.
    ed.surface.set_shared_text("genre", "Late G")
    ed.surface.set_shared_text("artist", "Late Artist")
    ed._choose_artwork = lambda: str(late_art)
    ed.choose_shared_artwork()
    ed.set_book_field("title", "Changed")
    ed.type_chapter_titles("Late\nLate")
    add_files(ed, m4b(container, tmp_path / "extra" / "Delta.m4b", title="Delta"))
    ed.on_select(ed.workspace.books[2].book_id)
    ed.on_remove(True)
    ed.var_auto_number.set(True)
    ed.var_start_part.set("9")
    ed._thread_factory.bodies[0]()
    ed._pump.tick()
    assert ed.last_result.state is JobState.COMPLETED_WITH_FAILURES
    alpha = metadata.read_m4b_tags(plan.books[0].published)
    assert alpha["title"] == "Alpha Edited" and alpha["genre"] == "Frozen G"
    assert alpha["artist"] == "Ann" and alpha["series_part"] == "1"
    assert metadata.read_chapter_titles(plan.books[0].published) == ["Opening", "The End"]
    assert bytes(covr_of(plan.books[0].published)[0]) == art.read_bytes()
    gamma = metadata.read_m4b_tags(plan.books[2].published)
    assert gamma["genre"] == "Frozen G" and gamma["title"] == "Gamma"
    assert covr_of(gamma_path := plan.books[2].published) == covr_of(plan.books[2].source)
    before = {entry.published: stamp(entry.published) for entry in (plan.books[0], plan.books[2])}
    # Retry after yet more mutation; the broken write is repaired.
    target["armed"] = False
    ed.surface.set_shared_text("genre", "Later Still")
    assert ed.retry_failed() is True
    ed._thread_factory.bodies[1]()
    ed._pump.tick()
    assert ed.last_plan is plan and ed.last_result.state is JobState.SUCCEEDED
    beta = metadata.read_m4b_tags(plan.books[1].published)
    assert beta["genre"] == "Frozen G" and beta["title"] == "Beta" and beta["series_part"] == "2"
    assert {p: stamp(p) for p in before} == before
    assert len(list((output_base / "M4B-Metadata-Outputs").iterdir())) == 1
    assert gamma_path.is_file()


# --------------------------------------------------------------------------- #
# 3. Job control on real threads: the race boundaries
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tool", ["maker", "editor"])
def test_the_settled_result_exists_before_the_terminal_event(tool, request, maker_sources,
                                                             maker_reserve, container,
                                                             editor_sources, editor_reserve):
    if tool == "maker":
        made, _ = maker_three(maker_sources, maker_reserve)
        run, events = maker_run(made)
    else:
        made, _, _ = editor_three(container, editor_sources, editor_reserve)
        run, events = editor_run(made)
    seen: list[bool] = []
    run.add_listener(lambda e: seen.append(run.result is not None)
                     if e.kind in (JobEventKind.COMPLETED, JobEventKind.CANCELLED) else None)
    attempt = run.start()
    worker = threading.Thread(target=attempt.run, name=f"{tool}-terminal-race")
    worker.start()
    worker.join(timeout=60)
    assert not worker.is_alive()
    assert seen == [True], "a consumer draining the terminal event always finds the result"
    assert run.result.state is JobState.SUCCEEDED


@pytest.mark.parametrize("tool", ["maker", "editor"])
def test_cancel_arriving_during_publication_keeps_that_book_and_stops_at_the_boundary(
        tool, monkeypatch, maker_sources, maker_reserve, container, editor_sources,
        editor_reserve):
    if tool == "maker":
        made, _ = maker_three(maker_sources, maker_reserve)
        run, events = maker_run(made)
        engine = m4b_maker_processing
    else:
        made, _, _ = editor_three(container, editor_sources, editor_reserve)
        run, events = editor_run(made)
        engine = m4b_metadata_processing
    real = engine.publish_book

    def cancel_then_publish(entry, *, work_root):
        # Past the last checkpoint: the user's Cancel lands while Book 1 publishes.
        if entry.book_id == made.books[0].book_id:
            run.cancel()
        return real(entry, work_root=work_root)

    monkeypatch.setattr(engine, "publish_book", cancel_then_publish)
    result = run.start().run()
    assert result.state is JobState.CANCELLED
    assert [d for _i, d in result.dispositions] == [
        BookDisposition.SUCCEEDED, BookDisposition.NOT_ATTEMPTED, BookDisposition.NOT_ATTEMPTED]
    assert made.books[0].published.is_file()
    assert not made.books[1].published.exists() and not made.books[1].staging_dir.exists()
    assert len(events.of(JobEventKind.CANCELLED)) == 1 and not events.of(JobEventKind.COMPLETED)
    assert not made.work_root.exists() or not any(made.work_root.iterdir())


@pytest.mark.parametrize("tool", ["maker", "editor"])
def test_a_pause_at_a_book_boundary_is_acknowledged_before_the_next_book(
        tool, maker_sources, maker_reserve, container, editor_sources, editor_reserve):
    if tool == "maker":
        made, _ = maker_three(maker_sources, maker_reserve)
        run, events = maker_run(made)
    else:
        made, _, _ = editor_three(container, editor_sources, editor_reserve)
        run, events = editor_run(made)
    paused = threading.Event()
    published: list[str] = []

    def on_event(event):
        if event.kind is JobEventKind.OUTPUT_LOCATION and str(event.message).startswith("✓"):
            published.append(event.message)
            if len(published) == 1:
                run.pause()
        if event.kind is JobEventKind.STATE_CHANGED and event.state is JobState.PAUSED:
            paused.set()

    run.add_listener(on_event)
    attempt = run.start()
    worker = threading.Thread(target=attempt.run, name=f"{tool}-pause-boundary")
    worker.start()
    assert paused.wait(timeout=60), "the worker never acknowledged the pause"
    assert attempt.controller.state is JobState.PAUSED
    assert made.books[0].published.is_file() and not made.books[1].published.exists()
    assert worker.is_alive(), "paused, not finished"
    run.resume()
    worker.join(timeout=60)
    assert not worker.is_alive()
    assert run.result.state is JobState.SUCCEEDED
    states = [e.state for e in events.of(JobEventKind.STATE_CHANGED)]
    assert states.index(JobState.PAUSE_REQUESTED) < states.index(JobState.PAUSED)
    assert states[-1] is JobState.SUCCEEDED


def test_a_retry_starts_only_after_the_prior_attempt_is_terminal_and_gets_its_own_adapter(
        panels, container, tmp_path, output_base, monkeypatch):
    """Real worker thread, gated by an Event; the panel's retry is refused while it runs."""
    root = editor_library(container, tmp_path / "Library")
    ed = panels.editor()
    import_folder(ed, root)
    ed.surface.set_shared_text("genre", "G")
    target = break_editor_book(monkeypatch, ed, 1)
    gate = threading.Event()
    real = m4b_metadata_processing.publish_book

    def gated_publish(entry, *, work_root):
        gate.wait(timeout=60)
        return real(entry, work_root=work_root)

    monkeypatch.setattr(m4b_metadata_processing, "publish_book", gated_publish)
    ed._thread_factory = parked_threads()
    assert ed.save() is True
    first_adapter, first_controller = ed.jobs, ed.job_controller
    body = ed._thread_factory.bodies[0]
    worker = threading.Thread(target=body, name="editor-retry-gate")
    worker.start()
    assert ed.is_running
    assert ed.retry_failed() is False, "refused while the attempt runs"
    with pytest.raises(m4b_metadata_batch.BatchError):
        ed.run.retry_failed()
    assert ed.save() is False
    gate.set()
    worker.join(timeout=60)
    assert not worker.is_alive()
    ed._pump.tick()
    assert not ed.is_running and ed.last_result.state is JobState.COMPLETED_WITH_FAILURES
    first_stream = first_adapter.stream
    assert len([e for e in first_stream.events if e.kind is JobEventKind.COMPLETED]) == 1
    target["armed"] = False
    assert ed.retry_failed() is True
    assert ed.jobs is not first_adapter and ed.job_controller is not first_controller
    assert ed.jobs.run_id == first_adapter.run_id, "a retry is the same run"
    retry_body = ed._thread_factory.bodies[1]
    worker = threading.Thread(target=retry_body, name="editor-retry-gate-2")
    worker.start()
    worker.join(timeout=60)
    ed._pump.tick()
    assert ed.last_result.state is JobState.SUCCEEDED
    second = ed.jobs.stream.events
    assert len([e for e in second if e.kind is JobEventKind.COMPLETED]) == 1
    assert len([e for e in first_stream.events if e.kind is JobEventKind.COMPLETED]) == 1, \
        "the first adapter saw nothing of the retry"
    assert all(e.run_id == first_adapter.run_id for e in second)


@pytest.mark.parametrize("tool", ["maker", "editor"])
def test_a_stale_runs_event_is_rejected_by_the_panels_adapter_and_never_rendered(
        tool, panels, container, tmp_path, output_base):
    if tool == "maker":
        panel = panels()
        root = tmp_path / "Library"
        tone(root / "A" / "01.mp3")
        import_folder(panel, root)
        assert panel.build() is True
    else:
        panel = panels.editor()
        import_folder(panel, editor_library(container, tmp_path / "Library"))
        assert panel.save() is True
    panel._pump.tick()
    assert panel.last_result.state is JobState.SUCCEEDED
    summary_before = tuple(panel.log.summary)
    stale = JobReporter("some-other-run", clock=lambda: 0.0, publish=panel._publish,
                        item_ids=())
    stale.technical("a line from a run that is not this one")
    stale.stage_changed("book-1", "Book 1 of a stale run")
    panel._pump.tick()
    from shared.job_control import EventVerdict

    verdicts = panel.jobs.last_verdicts
    assert verdicts and all(v is EventVerdict.STALE_RUN for v in verdicts), verdicts
    assert tuple(panel.log.summary) == summary_before
    assert all(e.run_id == panel.jobs.run_id for e in panel.jobs.stream.events)


# --------------------------------------------------------------------------- #
# 4. Output naming: Unicode, long and awkward names, both tools
# --------------------------------------------------------------------------- #


def test_editor_outputs_survive_unicode_long_and_same_named_sources(panels, container, tmp_path,
                                                                    output_base):
    long_stem = "L" * 180
    sources = [
        m4b(container, tmp_path / "one" / "Ünïcödé — 日本語 (Book 1).m4b", title="U"),
        m4b(container, tmp_path / "two" / f"{long_stem}.m4b", title="Long"),
        m4b(container, tmp_path / "three" / "Book.m4b", title="One"),
        m4b(container, tmp_path / "four" / "Book.m4b", title="Two"),
    ]
    before = [sha(p) for p in sources]
    ed = panels.editor()
    add_files(ed, *sources)
    ed.surface.set_shared_text("comment", "named")
    assert ed.save() is True
    ed._pump.tick()
    plan = ed.last_plan
    assert ed.last_result.state is JobState.SUCCEEDED
    names = [entry.filename for entry in plan.books]
    assert names[0] == "Ünïcödé — 日本語 (Book 1).m4b", "Unicode survives intact"
    assert names[1] == f"{long_stem}.m4b" or names[1].endswith(".m4b") and len(names[1]) <= 255
    assert names[2:] == ["Book.m4b", "Book-1.m4b"]
    for entry in plan.books:
        assert entry.published.is_file() and entry.published.parent == plan.run_directory
        assert metadata.read_m4b_tags(entry.published)["comment"] == "named"
    assert [sha(p) for p in sources] == before


def test_maker_output_names_survive_forbidden_reserved_unicode_and_long_titles(
        panels, tmp_path, output_base):
    root = tmp_path / "Library"
    for folder in ("A", "B", "C", "D"):
        tone(root / folder / "01.mp3")
    maker = panels()
    import_folder(maker, root)
    titles = ['Bad<>:"/\\|?* Title', "CON", "Ünïcödé — 日本語", "T" * 300]
    for title in titles:
        maker.set_book_field("title", title)
        maker.on_next()
    assert maker.build() is True
    plan = maker.last_plan
    names = [entry.filename for entry in plan.books]
    for name in names:
        assert name.endswith(".m4b") and len(name) <= 255
        assert not any(ch in name for ch in '<>:"/\\|?*')
        assert name.split(".")[0].upper() != "CON"
    assert names[2] == "Ünïcödé — 日本語.m4b"
    assert len(set(names)) == 4
    maker._pump.tick()
    assert maker.last_result.state is JobState.SUCCEEDED
    assert sorted(p.name for p in plan.root.iterdir() if p.is_file()) == sorted(names)
    assert metadata.read_m4b_tags(plan.books[2].published)["title"] == "Ünïcödé — 日本語"


def test_maker_tags_and_chapter_titles_survive_ffmetadata_special_characters(
        panels, tmp_path, output_base):
    """``=``, ``;``, ``#``, a backslash and a newline are ffmetadata syntax; a Title
    like "Harry Potter #1" or a chapter "Part #2" must come back exactly
    (v0.6.4 Phase 11 finding)."""
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    tone(root / "A" / "02.mp3")
    maker = panels()
    import_folder(maker, root)
    backslash = chr(92)
    title = f"Harry Potter #1; a=b {backslash} back"
    album = f"Series = One {backslash} Two"
    chapter_two = f"Key=Value; semi {backslash} slash"
    maker.set_book_field("title", title)
    maker.on_shared_change("artist", "Rowling; J.K. #7")
    maker.on_shared_change("album", album)
    maker.type_chapter_titles("Part #1" + chr(10) + chapter_two)
    assert maker.build() is True
    maker._pump.tick()
    assert maker.last_result.state is JobState.SUCCEEDED, [
        line for line in maker.log.details if "failed" in line]
    published = maker.last_plan.books[0].published
    tags = metadata.read_m4b_tags(published)
    assert tags["title"] == title
    assert tags["artist"] == "Rowling; J.K. #7" and tags["album"] == album
    assert metadata.read_chapter_titles(published) == ["Part #1", chapter_two]


# --------------------------------------------------------------------------- #
# 5. The common artwork architecture through both consumers
# --------------------------------------------------------------------------- #


def test_editor_artwork_preserve_replace_clear_and_remove_through_the_panel(
        panels, container, tmp_path, output_base):
    root = editor_library(container, tmp_path / "Library")
    photo, poster = jpg(tmp_path / "photo.jpg"), png(tmp_path / "poster.png")
    image_hashes = (sha(photo), sha(poster))
    source_audio = {p.name: audio_md5(p) for p in root.rglob("*.m4*")}
    ed = panels.editor()
    import_folder(ed, root)
    # Save: Book 1 replaced with the JPEG, the others preserve their source cover.
    ed._choose_artwork = lambda: str(photo)
    ed.choose_book_artwork()
    assert ed.save() is True
    ed._pump.tick()
    saved = ed.last_plan
    assert bytes(covr_of(saved.books[0].published)[0]) == photo.read_bytes()
    assert covr_of(saved.books[1].published) == covr_of(saved.books[1].source)
    # Clear All with a Shared PNG: every output carries the PNG after the clear.
    ed.clear_book_artwork()
    ed._choose_artwork = lambda: str(poster)
    ed.choose_shared_artwork()
    assert ed.on_clear_all_tags() is True
    ed._pump.tick()
    cleared = ed.last_plan
    assert all(bytes(covr_of(e.published)[0]) == poster.read_bytes() for e in cleared.books)
    assert all(not metadata.read_m4b_tags(e.published).get("title") for e in cleared.books)
    # Clear All with no replacement: the cover stays removed.
    ed.clear_shared_artwork()
    assert ed.on_clear_all_tags() is True
    ed._pump.tick()
    bare = ed.last_plan
    assert all(covr_of(e.published) == [] for e in bare.books)
    # Remove Series Numbering with a pending replacement: artwork untouched.
    ed._choose_artwork = lambda: str(photo)
    ed.choose_book_artwork()
    assert ed.on_remove_series_numbering() is True
    ed._pump.tick()
    kept = ed.last_plan
    assert covr_of(kept.books[0].published) == covr_of(kept.books[0].source)
    assert (sha(photo), sha(poster)) == image_hashes, "source images never written"
    for plan in (saved, cleared, bare, kept):
        for entry in plan.books:
            assert audio_md5(entry.published) == source_audio[entry.source.name]
    assert len(list((output_base / "M4B-Metadata-Outputs").iterdir())) == 4, "one run each"


def test_a_heic_replacement_is_converted_in_memory_for_the_editor_too(panels, container,
                                                                      tmp_path, output_base):
    cover = heic(tmp_path / "Art" / "cover.heic", size=(40, 28))   # skips where undecodable
    before = sha(cover)
    ed = panels.editor()
    add_files(ed, m4b(container, tmp_path / "Src" / "Book.m4b", title="B"))
    ed._choose_artwork = lambda: str(cover)
    ed.choose_book_artwork()
    assert ed.book_artwork.has_preview
    assert ed.save() is True
    ed._pump.tick()
    assert ed.last_result.state is JobState.SUCCEEDED
    covr = covr_of(ed.last_plan.books[0].published)
    assert len(covr) == 1 and bytes(covr[0])[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    import io

    assert Image.open(io.BytesIO(bytes(covr[0]))).size == (40, 28)
    assert sha(cover) == before
    assert sorted(p.name for p in cover.parent.iterdir()) == ["cover.heic"], "no sidecar"


def test_an_unavailable_heic_capability_is_a_visible_refusal_in_both_panels(
        panels, container, tmp_path, output_base, monkeypatch):
    unavailable = image_capabilities.FormatCapability(
        name="heif", suffixes=(), decode=False, encode=False, detail="no pillow-heif here")
    monkeypatch.setattr(image_capabilities, "heif_capability", lambda: unavailable)
    fake = tmp_path / "cover.heic"
    fake.write_bytes(b"not decodable anyway")
    refusals: list[str] = []
    for panel in (panels(), panels.editor()):
        panel._artwork_error = refusals.append
        panel._choose_artwork = lambda: str(fake)
        panel.choose_shared_artwork()
        assert panel.workspace.shared.values.get("artwork", "") == ""
    assert len(refusals) == 2 and all("HEIC" in r or ".heic" in r for r in refusals)
    # The chooser filter is the shared probe's answer: no HEIC pattern is offered.
    offered = " ".join(pattern for _label, pattern in m4b_artwork.artwork_filetypes())
    assert ".heic" not in offered.lower() and ".png" in offered.lower()
    assert fake.read_bytes() == b"not decodable anyway"


# --------------------------------------------------------------------------- #
# 6. Maker end to end: A succeeds / B fails / C succeeds, numbering, Retry Failed
# --------------------------------------------------------------------------- #


def test_maker_a_b_c_success_numbering_and_retry_through_the_panel(panels, tmp_path, output_base):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    bad = touch(root / "B" / "01.mp3", "not audio")
    tone(root / "C" / "01.mp3")
    tone(root / "C" / "02.mp3")
    maker = panels()
    import_folder(maker, root)
    maker.on_shared_change("series", "Saga")
    maker.var_auto_number.set(True)
    maker.var_start_part.set("1")
    # Book C also takes the forced-Safe path (silence) so both workflows run in one batch.
    maker.on_select(maker.workspace.books[2].book_id)
    maker.set_book_field("silence", "0.2")
    assert maker.build() is True
    maker._pump.tick()
    plan = maker.last_plan
    result = maker.last_result
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    ids = [book.book_id for book in maker.workspace.books]
    assert [maker.book_status_for(i) for i in ids] == [
        m4b_maker.STATUS_COMPLETED, m4b_maker.STATUS_FAILED, m4b_maker.STATUS_COMPLETED]
    a_tags = metadata.read_m4b_tags(plan.books[0].published)
    c_tags = metadata.read_m4b_tags(plan.books[2].published)
    assert (a_tags["series"], a_tags["series_part"]) == ("Saga", "1")
    assert (c_tags["series"], c_tags["series_part"]) == ("Saga", "2"), "no gap after B"
    assert len(metadata.read_chapter_titles(plan.books[2].published)) == 2
    assert maker.run.numbers.consumed == 2
    c_before = stamp(plan.books[2].published)
    # Repair B; mutate the live workspace every way; retry takes the next success number.
    tone(bad)
    maker.on_shared_change("series", "Other Saga")
    maker.set_book_field("title", "Renamed")
    maker.var_start_part.set("7")
    assert maker.retry_failed() is True
    maker._pump.tick()
    assert maker.last_result.state is JobState.SUCCEEDED and maker.last_plan is plan
    b_tags = metadata.read_m4b_tags(plan.books[1].published)
    assert (b_tags["series"], b_tags["series_part"], b_tags["title"]) == ("Saga", "3", "B")
    assert stamp(plan.books[2].published) == c_before, "C untouched by B's retry"
    assert len(list((output_base / "M4B-Maker-Outputs").iterdir())) == 1, "no new reservation"
    assert [maker.book_status_for(i) for i in ids] == [m4b_maker.STATUS_COMPLETED] * 3
    assert any("Series Part 3" in line for line in maker.log.details)


# --------------------------------------------------------------------------- #
# 7. Editor end to end: the whole chain, in order, through the panel
# --------------------------------------------------------------------------- #


def test_editor_chain_runs_in_order_from_panel_to_publication(panels, container, tmp_path,
                                                              output_base):
    root = editor_library(container, tmp_path / "Library")
    ed = panels.editor()
    import_folder(ed, root)
    ed.set_book_field("title", "Alpha Edited")
    ed.type_chapter_titles("\nThe End")
    ed._choose_artwork = lambda: str(png(tmp_path / "art.png"))
    ed.choose_book_artwork()
    before = sha(root / "Alpha.m4b")
    assert ed.save() is True
    ed._pump.tick()
    assert ed.last_result.state is JobState.SUCCEEDED
    details = list(ed.log.details)
    stages = ["[artwork]", "[copy]", "[tags]", "[cover]", "[chapters]", "[validate]"]
    positions = [next(i for i, line in enumerate(details) if tag in line) for tag in stages]
    assert positions == sorted(positions), "the chain runs in its frozen order"
    assert any("Alpha.m4b" in line and chr(0x2713) in line for line in ed.log.summary), (
        "publication is the runner's output-location milestone")
    plan = ed.last_plan
    assert plan.books[0].published.is_file() and not plan.books[0].staging_dir.exists()
    assert sha(root / "Alpha.m4b") == before
    assert ed.book_status_for(plan.books[0].book_id) == editor.STATUS_COMPLETED
