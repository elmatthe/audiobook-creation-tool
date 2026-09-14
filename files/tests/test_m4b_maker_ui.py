"""The M4B Maker production panel — v0.6.4 Phase 6.

``mp3_tools/m4b_maker.py`` is now a thin Tk composition/orchestration adapter
over the completed Maker layers: the shared Plan 6 workspace and its adapters
(``BookNavigator``, ``SharedMetadataSurface``), the Plan 3 importer and job
adapters, the Phase 1 artwork control, the Phase 2 model, the Phase 3 planner
and the Phase 5 ``MakerRun``. No business rule lives in a widget: every edit
asks a model operation and renders the result; Build freezes one plan and
hands it to one ``MakerRun``; Retry Failed re-runs that frozen run.

Import and processing here use placeholder MP3s and the panel's injection
seams (dialogs, scanner, thread factory) exactly as the MP3 Tool's tests do; the
real FFmpeg build path is proved by the Phase 4/5 suites and one end-to-end
case below.
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

from shared import book_workspace, ffmpeg_utils, job_ui, metadata, output_paths, ui_theme  # noqa: E402
from shared import subprocess_utils as sp  # noqa: E402
from shared.book_workspace import BookDisposition, has_meaningful_work  # noqa: E402
from shared.book_workspace_ui import BookNavigator, SharedMetadataSurface  # noqa: E402
from shared.job_control import JobState  # noqa: E402
from shared.job_ui import MainThreadError  # noqa: E402

from mp3_tools import m4b_artwork_ui, m4b_maker, m4b_maker_batch as batch  # noqa: E402
from mp3_tools import m4b_maker_plan as mp, m4b_maker_workflow as wf  # noqa: E402

from test_import_coordination import RecordingThreads  # noqa: E402
from test_import_traversal import touch  # noqa: E402
from test_importing import make_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_maker.py"


# --------------------------------------------------------------------------- #
# Fixtures
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


@pytest.fixture
def make_panel(tk_root, windows_theme, monkeypatch, output_base):
    """A real ``M4BMakerUI`` on the Windows bundle with deterministic seams."""
    made: list[m4b_maker.M4BMakerUI] = []
    dialogs: list[tuple[str, str]] = []

    def build(**kwargs):
        kwargs.setdefault("theme", windows_theme)
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("choose_artwork", lambda: "")
        kwargs.setdefault("choose_destination", lambda: "")
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        kwargs.setdefault("confirm", lambda title, message: True)
        monkeypatch.setattr(m4b_maker.messagebox, "showerror",
                            lambda title, message, **kw: dialogs.append(("error", message)))
        monkeypatch.setattr(m4b_maker.messagebox, "showwarning",
                            lambda title, message, **kw: dialogs.append(("warning", message)))
        panel = m4b_maker.M4BMakerUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    build.dialogs = dialogs  # type: ignore[attr-defined]
    yield build
    for panel in made:
        panel.close()
        try:
            panel.destroy()
        except tk.TclError:
            pass


def tracks(folder: Path, *names: str) -> tuple[Path, ...]:
    """Placeholder MP3s. Never real audio."""
    return tuple(touch(folder / name, "not audio") for name in names)


def tone(path: Path, seconds: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sp.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "64k", str(path)],
           check=True)
    return path


def import_folder(panel, root: Path):
    panel._choose_folder = lambda: (str(root),)
    panel.import_folder()
    panel._pump.tick()
    return panel.workspace


def add_files(panel, *paths: Path):
    panel._choose_files = lambda: tuple(str(p) for p in paths)
    panel.add_files()
    return panel.workspace


def track_names(panel) -> list[str]:
    return [entry.name for entry in panel.workspace.current.files.files]


def widgets_of(widget, kind) -> list:
    found = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found += widgets_of(child, kind)
    return found


def png(path: Path, size=(24, 16)) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 30, 30)).save(path, format="PNG")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def library(root: Path) -> Path:
    tracks(root / "Vol 1", "01.mp3", "02.mp3")
    tracks(root / "Vol 2", "1.mp3", "2.mp3", "10.mp3")
    return root


# --------------------------------------------------------------------------- #
# The workspace replaces the raw file list
# --------------------------------------------------------------------------- #


def test_the_panel_starts_with_one_empty_book_and_no_raw_file_list(make_panel):
    panel = make_panel()
    assert panel.workspace.count == 1
    assert panel.workspace.current.is_empty
    assert not hasattr(panel, "files"), "the raw list is gone; the Books are the list"
    assert isinstance(panel.navigator, BookNavigator)
    assert isinstance(panel.surface, SharedMetadataSurface)
    assert panel.navigator.position_text == "Book 1 of 1"
    assert panel.navigator.actions == BookNavigator.BOOK_ACTIONS


def test_import_folder_makes_one_book_per_directory_in_natural_order(make_panel, tmp_path):
    panel = make_panel()
    space = import_folder(panel, library(tmp_path / "Library"))
    assert space.count == 2
    assert [[f.name for f in book.files.files] for book in space.books] == [
        ["01.mp3", "02.mp3"], ["1.mp3", "2.mp3", "10.mp3"]]
    assert panel.navigator.position_text == "Book 1 of 2"
    assert panel.track_list.size() == 2


def test_add_files_targets_only_the_current_book(make_panel, tmp_path):
    panel = make_panel()
    import_folder(panel, library(tmp_path / "Library"))
    panel.on_next()
    extra = tracks(tmp_path / "Loose", "05.mp3", "03.mp3")
    space = add_files(panel, *extra)
    assert [f.name for f in space.books[0].files.files] == ["01.mp3", "02.mp3"]
    assert [f.name for f in space.books[1].files.files] == [
        "1.mp3", "2.mp3", "10.mp3", "03.mp3", "05.mp3"], "natural order within the addition"


def test_add_duplicate_remove_and_navigation_are_the_shared_operations(make_panel, tmp_path):
    panel = make_panel()
    import_folder(panel, library(tmp_path / "Library"))
    panel.set_book_field("title", "First")
    first_id = panel.workspace.current.book_id
    second_id = panel.workspace.books[1].book_id
    panel.on_duplicate()
    copy = panel.workspace.current
    assert copy.book_id != first_id and copy.is_empty
    assert copy.configuration["title"] == "First"
    assert [b.book_id for b in panel.workspace.books] == [first_id, copy.book_id, second_id]
    panel.on_add()
    assert panel.workspace.count == 4 and panel.workspace.current.is_empty
    panel.on_previous()
    assert panel.workspace.current.book_id == second_id
    panel.on_select(copy.book_id)
    assert panel.workspace.current is copy
    panel.on_select(first_id)
    assert panel.workspace.current.book_id == first_id
    panel.on_remove(has_meaningful_work(panel.workspace.current))
    assert panel.workspace.count == 3
    assert first_id not in {book.book_id for book in panel.workspace.books}


def test_removing_a_meaningful_book_asks_and_a_refusal_keeps_it(make_panel, tmp_path):
    asked: list[str] = []
    panel = make_panel(confirm=lambda title, message: asked.append(title) or False)
    import_folder(panel, library(tmp_path / "Library"))
    panel.navigator.invoke(BookNavigator.REMOVE)
    assert asked and "Remove" in asked[0]
    assert panel.workspace.count == 2


def test_book_values_files_and_chapters_survive_navigation(make_panel, tmp_path):
    panel = make_panel()
    import_folder(panel, library(tmp_path / "Library"))
    panel.set_book_field("title", "One")
    panel.set_book_field("series_part", "1")
    panel.set_book_field("output_filename", "first")
    panel.type_chapter_titles("Alpha\nBeta")
    panel.on_next()
    assert panel.chapter_titles_text() == "1\n2\n10", "defaults from the Phase 2 rule"
    panel.set_book_field("title", "Two")
    panel.on_previous()
    book = panel.workspace.current
    assert (book.configuration["title"], book.configuration["series_part"],
            book.configuration["output_filename"]) == ("One", "1", "first")
    assert panel.chapter_titles_text() == "Alpha\nBeta"
    assert track_names(panel) == ["01.mp3", "02.mp3"]
    assert panel.book_title_text() == "One"


def test_track_move_and_remove_are_per_book_and_reorder_default_chapters(make_panel, tmp_path):
    panel = make_panel()
    import_folder(panel, library(tmp_path / "Library"))
    panel.on_next()
    panel.select_tracks(2)
    panel.move_up()
    assert track_names(panel) == ["1.mp3", "10.mp3", "2.mp3"]
    assert panel.chapter_titles_text() == "1\n10\n2"
    panel.select_tracks(0)
    panel.remove_selected_tracks()
    assert track_names(panel) == ["10.mp3", "2.mp3"]
    panel.on_previous()
    assert track_names(panel) == ["01.mp3", "02.mp3"]


# --------------------------------------------------------------------------- #
# Shared and Book fields
# --------------------------------------------------------------------------- #


def test_the_shared_surface_is_exactly_the_maker_vocabulary(make_panel):
    panel = make_panel()
    assert panel.surface.fields == tuple(k for k in wf.SHARED_FIELDS if k != "artwork")
    assert set(panel.shared_field_keys()) == set(wf.SHARED_FIELDS)
    for foreign in ("time_delta", "title", "series_part", "output_filename",
                    "chapter_titles", "year", "genre", "comment"):
        assert foreign not in panel.surface.fields
    assert set(panel.book_field_keys()) == set(wf.SHARED_FIELDS) | set(wf.BOOK_ONLY_FIELDS)


def test_a_populated_shared_value_overrides_and_disables_the_book_control(make_panel, tmp_path):
    panel = make_panel()
    import_folder(panel, library(tmp_path / "Library"))
    panel.set_book_field("artist", "Book Artist")
    panel.on_shared_change("artist", "Shared Artist")
    assert panel.workspace.shared.values["artist"] == "Shared Artist"
    assert panel.book_field_enabled("artist") is False
    assert panel.workspace.current.configuration["artist"] == "Book Artist"
    assert wf.effective_values(panel.workspace.shared, panel.workspace.current)["artist"] == (
        "Shared Artist")
    panel.on_shared_change("artist", "")
    assert panel.book_field_enabled("artist") is True
    assert panel.surface.book_value("artist") == "Book Artist"


def test_shared_silence_and_artwork_override_their_book_controls(make_panel, tmp_path):
    art = png(tmp_path / "shared.png")
    panel = make_panel(choose_artwork=lambda: str(art))
    panel.set_book_field("silence", "1")
    panel.set_book_field("artwork", str(png(tmp_path / "book.png")))
    panel.on_shared_change("silence", "0.5")
    assert panel.book_field_enabled("silence") is False
    assert panel.book_artwork.enabled
    panel.choose_shared_artwork()
    assert panel.workspace.shared.values["artwork"] == str(art)
    assert not panel.book_artwork.enabled
    assert panel.shared_artwork.has_preview
    panel.clear_shared_artwork()
    assert panel.book_artwork.enabled
    assert panel.workspace.current.configuration["artwork"].endswith("book.png")


def test_the_artwork_controls_are_the_common_m4b_adapter(make_panel, tmp_path):
    panel = make_panel()
    assert isinstance(panel.shared_artwork, m4b_artwork_ui.ArtworkControl)
    assert isinstance(panel.book_artwork, m4b_artwork_ui.ArtworkControl)
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    panel._choose_artwork = lambda: str(bad)
    panel.choose_book_artwork()
    assert panel.workspace.current.configuration.get("artwork", "") == ""
    assert make_panel.dialogs and make_panel.dialogs[-1][0] == "error"


def test_auto_number_disables_the_manual_series_part_control(make_panel, tmp_path):
    panel = make_panel()
    import_folder(panel, library(tmp_path / "Library"))
    panel.set_book_field("series_part", "4")
    assert panel.book_field_enabled("series_part") is True
    panel.var_auto_number.set(True)
    panel.on_auto_number()
    assert panel.book_field_enabled("series_part") is False
    assert panel.workspace.current.configuration["series_part"] == "4", "the value survives"
    panel.var_auto_number.set(False)
    panel.on_auto_number()
    assert panel.book_field_enabled("series_part") is True


# --------------------------------------------------------------------------- #
# Output controls
# --------------------------------------------------------------------------- #


def test_the_custom_destination_toggle_is_off_hidden_and_never_persisted(make_panel, tmp_path):
    from shared import settings as app_settings

    panel = make_panel()
    assert panel.chk_custom_dest.cget("text") == m4b_maker.CUSTOM_DEST_LABEL
    assert panel.var_custom_dest.get() is False and panel.custom_destination() is None
    panel.update_idletasks()
    assert not panel.customrow.winfo_manager()
    panel.var_custom_dest.set(True)
    panel._on_custom_dest_change()
    panel.var_custom_path.set(str(tmp_path / "Chosen"))
    panel.update_idletasks()
    assert panel.customrow.winfo_manager()
    assert not any("custom" in str(k).lower() for k in app_settings.all_settings())
    panel.var_custom_dest.set(False)
    assert panel.custom_destination() is None


# --------------------------------------------------------------------------- #
# Build: one frozen plan, one MakerRun, one worker
# --------------------------------------------------------------------------- #


def test_build_refuses_an_empty_workspace_and_a_bad_silence_before_reserving(make_panel,
                                                                              output_base):
    panel = make_panel()
    assert panel.build() is False
    assert make_panel.dialogs[-1][0] == "warning"
    assert not output_base.exists()


def test_build_freezes_one_plan_reserves_one_run_and_runs_every_book(make_panel, tmp_path,
                                                                     output_base):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    tone(root / "B" / "01.mp3")
    panel = make_panel()
    import_folder(panel, root)
    panel.set_book_field("title", "Alpha")
    panel.on_next()
    panel.set_book_field("title", "Beta")
    assert panel.build() is True
    plan = panel.last_plan
    assert isinstance(plan, mp.RunPlan) and plan.mode is mp.DestinationMode.STANDARD
    assert plan.root == output_base / "M4B-Maker-Outputs" / "M4B-Maker-1"
    assert [entry.title for entry in plan.books] == ["Alpha", "Beta"]
    assert isinstance(panel.run, batch.MakerRun) and len(panel.run.attempts) == 1
    # The worker body ran inline through the thread factory: one worker body
    # per attempt (the import scan has its own thread before it).
    workers = [b for b in panel._thread_factory.bodies if getattr(b, "__name__", "") == "run"]
    assert len(workers) == 1
    # Editing after Start reaches nothing the run reads.
    panel.set_book_field("title", "Changed")
    panel.on_shared_change("artist", "Late")
    assert [entry.title for entry in plan.books] == ["Alpha", "Beta"]
    panel._pump.tick()
    result = panel.last_result
    assert result is not None and result.state is JobState.SUCCEEDED
    assert sorted(p.name for p in plan.root.iterdir() if p.is_file()) == ["Alpha.m4b", "Beta.m4b"]
    assert panel.book_status_for(plan.books[0].book_id) == m4b_maker.STATUS_COMPLETED
    assert not panel.is_running
    assert len(list((output_base / "M4B-Maker-Outputs").iterdir())) == 1, "one reservation"


def test_custom_destination_builds_directly_into_the_chosen_folder(make_panel, tmp_path,
                                                                    output_base):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    chosen = tmp_path / "Chosen"
    chosen.mkdir()
    panel = make_panel(choose_destination=lambda: str(chosen))
    import_folder(panel, root)
    panel.set_book_field("title", "Direct")
    panel.var_custom_dest.set(True)
    panel._on_custom_dest_change()
    panel.choose_custom_dest()
    assert panel.build() is True
    plan = panel.last_plan
    assert plan.mode is mp.DestinationMode.CUSTOM and plan.root == chosen
    with pytest.raises(output_paths.UnsafePathError):
        output_paths.assert_contained(chosen, plan.work_root)
    panel._pump.tick()
    assert (chosen / "Direct.m4b").is_file()
    assert not (chosen / "M4B-Maker-1").exists()
    assert not output_base.exists(), "no standard run was reserved"
    assert not plan.work_root.exists(), "the operation-owned staging is gone"


def test_an_invalid_custom_destination_reserves_nothing(make_panel, tmp_path, output_base):
    root = tmp_path / "Library"
    tracks(root / "A", "01.mp3")
    panel = make_panel()
    import_folder(panel, root)
    panel.var_custom_dest.set(True)
    panel.var_custom_path.set(str(tmp_path / "missing"))
    assert panel.build() is False
    assert make_panel.dialogs[-1][0] == "error"
    assert not output_base.exists() and panel.run is None


def test_one_failed_book_does_not_stop_the_next_and_statuses_come_from_the_result(
        make_panel, tmp_path, output_base):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    touch(root / "B" / "01.mp3", "not audio")
    tone(root / "C" / "01.mp3")
    panel = make_panel()
    import_folder(panel, root)
    assert panel.build() is True
    panel._pump.tick()
    result = panel.last_result
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    ids = [book.book_id for book in panel.workspace.books]
    assert [panel.book_status_for(i) for i in ids] == [
        m4b_maker.STATUS_COMPLETED, m4b_maker.STATUS_FAILED, m4b_maker.STATUS_COMPLETED]
    assert [d for _i, d in result.dispositions] == [
        BookDisposition.SUCCEEDED, BookDisposition.FAILED, BookDisposition.SUCCEEDED]
    from shared.job_control import JobAction

    assert panel.jobs.controls.availability()[JobAction.RETRY_FAILED] is True


def test_retry_failed_reruns_only_the_failed_book_from_the_frozen_run(make_panel, tmp_path,
                                                                       output_base):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    bad = touch(root / "B" / "01.mp3", "not audio")
    panel = make_panel()
    import_folder(panel, root)
    panel.build()
    panel._pump.tick()
    plan = panel.last_plan
    published_a = plan.books[0].published
    before = (sha(published_a), published_a.stat().st_mtime_ns)
    # Repair the source in place and edit the workspace every way there is.
    tone(bad)
    panel.set_book_field("title", "Renamed")
    panel.on_remove(True)
    assert panel.retry_failed() is True
    assert panel.last_plan is plan and len(panel.run.attempts) == 2
    assert [b.book_id for b in panel.run.attempts[1].books] == [plan.books[1].book_id]
    panel._pump.tick()
    result = panel.last_result
    assert result.state is JobState.SUCCEEDED
    assert plan.books[1].published.is_file()
    assert (sha(published_a), published_a.stat().st_mtime_ns) == before
    assert len(list((output_base / "M4B-Maker-Outputs").iterdir())) == 1, "no new run"


def test_pause_resume_and_cancel_reach_the_shared_controller(make_panel, tmp_path, output_base):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    tone(root / "B" / "01.mp3")
    calls: list[str] = []

    class Recording(batch.MakerRun):
        def pause(self):
            calls.append("pause")
            super().pause()

        def resume(self):
            calls.append("resume")
            super().resume()

        def cancel(self):
            calls.append("cancel")
            super().cancel()

    threads = RecordingThreads()
    panel = make_panel(thread_factory=threads, run_factory=Recording)
    import_folder(panel, root)
    # A thread factory that does not start: the run stays RUNNING for inspection.
    import test_import_coordination as tic

    class Parked(tic.InlineThread):
        def start(self):
            pass

    panel._thread_factory = RecordingThreads(kind=Parked)
    assert panel.build() is True
    assert panel.is_running
    controller = panel.job_controller
    panel.pause()
    assert controller.state is JobState.PAUSE_REQUESTED
    panel.resume()
    assert controller.state is JobState.RUNNING
    panel.cancel()
    assert controller.state is JobState.CANCEL_REQUESTED
    assert calls == ["pause", "resume", "cancel"]
    # Now the worker runs and honours the cancel at its first checkpoint.
    panel._thread_factory.bodies[0]()
    panel._pump.tick()
    result = panel.last_result
    assert result.state is JobState.CANCELLED
    assert [d for _i, d in result.dispositions] == [BookDisposition.NOT_ATTEMPTED] * 2
    assert panel.book_status_for(panel.workspace.books[0].book_id) == m4b_maker.STATUS_NOT_ATTEMPTED


def test_the_ui_locks_through_the_shared_matrix_while_running(make_panel, tmp_path, output_base):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    import test_import_coordination as tic

    class Parked(tic.InlineThread):
        def start(self):
            pass

    panel = make_panel()
    import_folder(panel, root)
    panel._thread_factory = RecordingThreads(kind=Parked)
    assert panel.build() is True
    assert panel.lock_group.last_applied
    assert "disabled" in panel.btn_build.state()
    assert "disabled" in panel.btn_import_folder.state()
    assert "disabled" in panel.btn_add_files.state()
    assert "disabled" in panel.navigator.buttons[BookNavigator.ADD].state()
    assert panel.book_field_enabled("title") is False
    assert not panel.book_artwork.enabled
    panel._thread_factory.bodies[0]()
    panel._pump.tick()
    assert "disabled" not in panel.btn_build.state()
    assert "disabled" not in panel.btn_import_folder.state()


def test_the_worker_body_reaches_no_tk(make_panel, tmp_path, output_base):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    import test_import_coordination as tic

    class Parked(tic.InlineThread):
        def start(self):
            pass

    panel = make_panel()
    import_folder(panel, root)
    panel._thread_factory = RecordingThreads(kind=Parked)
    assert panel.build() is True
    body = panel._thread_factory.bodies[0]
    raised: list[BaseException] = []

    def run():
        try:
            body()
        except BaseException as exc:  # noqa: BLE001
            raised.append(exc)

    worker = threading.Thread(target=run, name="maker-ui-test")
    worker.start()
    worker.join(timeout=60)
    assert not worker.is_alive() and not raised
    panel._pump.tick()
    assert panel.last_result is not None and panel.last_result.state is JobState.SUCCEEDED


# --------------------------------------------------------------------------- #
# Log, layout and presentation
# --------------------------------------------------------------------------- #


def test_one_summary_detailed_region_and_no_whole_form_scrollbar(make_panel):
    panel = make_panel()
    assert isinstance(panel.log, job_ui.SummaryDetailsView)
    assert len(widgets_of(panel, tk.Text)) == 3, "chapter box, Summary, Detailed"
    canvases = widgets_of(panel, tk.Canvas)
    assert canvases == [], "no whole-tool canvas scroller"
    scrollbars = widgets_of(panel, ttk.Scrollbar)
    assert len(scrollbars) == 4, "track list, chapter titles, Summary, Detailed"


def test_the_windows_minimum_geometry_keeps_every_region_reachable(tk_root, make_panel):
    """Deiconified: ``winfo_ismapped`` on a withdrawn toplevel says nothing."""
    panel = make_panel()
    tk_root.deiconify()
    try:
        panel.pack(fill="both", expand=True)
        tk_root.geometry("920x600")
        for _ in range(6):
            tk_root.update_idletasks()
            tk_root.update()
        height, width = tk_root.winfo_height(), tk_root.winfo_width()
        top, left = tk_root.winfo_rooty(), tk_root.winfo_rootx()
        assert width >= 920 and height >= 600
        for widget in (panel.btn_build, panel.jobs.controls.frame, panel.log.frame,
                       panel.navigator.frame, panel.btn_import_folder, panel.chk_custom_dest,
                       panel.check_fast_first, panel.track_list, panel.chapter_text,
                       panel.book_artwork.btn_choose, panel.book_entries["output_filename"],
                       panel.navigator.buttons[BookNavigator.REMOVE]):
            assert widget.winfo_ismapped(), widget
            bottom = widget.winfo_rooty() - top + widget.winfo_height()
            right = widget.winfo_rootx() - left + widget.winfo_width()
            assert bottom <= height + 1, (widget, bottom, height)
            assert right <= width + 1, (widget, right, width)
        # The Shared/Book band is the row this panel widened (five text fields
        # against the MP3 Tool's four); it must fit inside the padded 920.
        assert panel.surface.frame.winfo_reqwidth() <= 900, panel.surface.frame.winfo_reqwidth()
    finally:
        panel.pack_forget()
        tk_root.withdraw()


def test_aqua_uses_the_stacked_hints_through_the_existing_seam(tk_root):
    aqua = {"mode": "aqua", "geometry": ui_theme.DEFAULT_GEOMETRY,
            "min_size": ui_theme.AQUA_MIN_SIZE,
            "metrics": {"navigator_layout": "stacked", "actions_layout": "stacked",
                        "artwork_buttons": "natural", "content_pad": 12}}
    panel = m4b_maker.M4BMakerUI(tk_root, theme=aqua, effective_config=make_config(),
                                 thread_factory=RecordingThreads(),
                                 choose_files=lambda: (), choose_folder=lambda: ())
    try:
        assert panel.navigator.layout == "stacked"
        assert str(panel.btn_build.cget("style")) == ""
        assert str(panel.book_artwork.btn_choose.cget("width")) in ("", "0")
    finally:
        panel.close()
        panel.destroy()


def test_the_panel_asks_for_act_styles_and_declares_no_colour_or_platform_branch(
        make_panel):
    panel = make_panel()
    assert str(panel.btn_build.cget("style")).startswith("ACT.")
    assert str(panel.navigator.frame.cget("style")).startswith("ACT.")
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for hexish in literals:
        assert not (hexish.startswith("#") and len(hexish) in (4, 7)), hexish
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "platform" not in names and "sys.platform" not in literals
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not any(c.endswith("theme_use") or c.endswith("Style().configure") for c in calls)


# --------------------------------------------------------------------------- #
# Structure: thin adapter, the four layers, one framework
# --------------------------------------------------------------------------- #


def test_the_panel_composes_the_four_layers_and_defines_no_business_rule():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    for required in ("shared.book_workspace", "shared.book_workspace_ui", "shared.job_ui",
                     "shared.job_control", "shared.import_coordination", "shared.importing",
                     "mp3_tools.m4b_maker_workflow", "mp3_tools.m4b_maker_plan",
                     "mp3_tools.m4b_maker_batch", "mp3_tools.m4b_artwork_ui"):
        assert required in modules, required
    for banned in ("wave", "json", "shared.ffmpeg_utils",
                   "shared.metadata", "mutagen", "mp3_tools.mp3_workflow",
                   "mp3_tools.mp3_plan", "mp3_tools.mp3_processing", "mp3_tools.mp3_tool",
                   "mp3_tools.m4b_metadata_editor"):
        assert banned not in modules, banned
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for gone in ("_build_worker", "_pump_queue", "run_fast_concat", "run_safe_concat",
                 "normalize_to_wav", "create_silence_wav", "compute_starts_total_fast",
                 "compute_audio_starts_with_silence", "ffprobe_duration_ms", "compute_titles",
                 "normalize_title", "strip_leading_numbers", "build_ffmetadata_from_starts",
                 "write_concat_list", "wav_duration_ms", "natural_key", "disable_inputs"):
        assert gone not in declared, gone
    for owned_elsewhere in ("BookNavigator", "SharedMetadataSurface", "ArtworkControl",
                            "JobController", "JobAdapter", "MakerRun", "Attempt",
                            "ImportedFileManager", "ImportCoordinator", "plan_run",
                            "DestinationPlanner", "SuccessNumbers"):
        assert owned_elsewhere not in declared, owned_elsewhere
    calls = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for write in ("rmtree", "replace", "unlink", "write_bytes", "Popen", "run"):
        assert write not in calls, write
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for private in ("_busy", "_cancel_event", "_log_q"):
        assert private not in names, private
    # Exactly one MakerRun construction, one thread start per attempt, no Thread here.
    built = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and ast.unparse(node.func).endswith(("MakerRun", "_run_factory"))]
    assert len(built) == 1, "one MakerRun construction site, through the injectable seam"


def test_the_public_surface_the_launcher_expects_is_intact(tk_root):
    from shared import paths

    assert callable(m4b_maker.build_ui) and callable(m4b_maker.main)
    assert m4b_maker.TOOL_KEY == "m4b_maker" and m4b_maker.SLUG == paths.TOOL_SLUGS["m4b_maker"]
    ui = m4b_maker.build_ui(ttk.Frame(tk_root))
    try:
        assert isinstance(ui, m4b_maker.M4BMakerUI)
    finally:
        ui.close()
        ui.master.destroy()
