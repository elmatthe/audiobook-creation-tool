"""MP3 Tool — v0.8.2 Checkpoint 1, independent review remediation R1.

The independent review of CP1 (``files/dev-work/v0.8.2-large-job-investigation/CP1-INDEPENDENT-REVIEW.md``) kept the
large-job fix and found five defects around it. Each is reproduced here through the real panel, the real Tk widgets
and the real planner, on synthetic placeholders under ``tmp_path`` only:

1. **Chapter Titles lost to a redraw.** A paste (Tk's own ``<<Paste>>`` binding) reaches the box without a key
   release; editing a Shared field redrew the box from the old model and the plan froze the old titles. Every action
   that can redraw the editor now commits the pending text to the Book it was typed for first.
2. **Adoption failure stranded the panel.** A failure installing the new job area left it busy with no worker. Setup
   is now transactional: nothing changes hands until the new job area is up; a later failure settles the attempt.
3. **Two output configurations in one plan.** The capture recorded the panel's construction-time configuration while
   the reservation used the one at the press. One snapshot, read at the press, now governs both.
4. **A stale same-Book capture was accepted.** ``plan_run`` checked only Book ids; it now refuses a capture whose
   Shared settings, Books, tracks, order or options differ from the workspace it is planned against.
5. **Cancel/Close after offer waited on the filesystem on Tk.** The withdrawn plan's empty run is now released by a
   short-lived worker; Cancel and Close return at once.

The system clipboard is never read or written: the paste's clipboard read is answered inside this test's own Tcl
interpreter.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import config, job_control, job_ui, output_paths  # noqa: E402
from shared.book_workspace import SharedMetadata, add_book, select_book, set_shared_metadata  # noqa: E402
from shared.importing import IdFactory, ImportOptions  # noqa: E402
from shared.job_control import JobAction, JobState  # noqa: E402

from mp3 import mp3_plan, mp3_tool, mp3_workflow as wf  # noqa: E402

import test_import_coordination as tic  # noqa: E402
from test_import_coordination import RealThreads, RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_mp3_preparation import (  # noqa: E402
    EngineSpy,
    PreparationGate,
    import_and_settle,
    join_all,
    library,
    needs_ffmpeg,
    no_tags,
    pump_until,
)
from test_mp3_tool_ui import (  # noqa: E402,F401  (fixtures are collected by name)
    conversion_workers,
    import_folder,
    make_panel,
    reservations_under,
    tk_root,
    windows_theme,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def native_paste(panel, text: str) -> str:
    """Paste *text* over the whole Chapter Titles box through Tk's own ``<<Paste>>`` class binding.

    Exactly what a Ctrl+V or a context-menu paste runs (``tk_textPaste``), with no ``<KeyRelease>``. Only the
    clipboard read (``::tk::GetSelection``) is answered by this interpreter for the duration of the call; the system
    clipboard is never touched. Returns what the box then shows.
    """
    box = panel.chapter_text
    tcl = box.tk
    # Tk delivers no event to a widget whose native window it has not created yet (a panel no test has shown or
    # updated); asking for the window id creates it, as showing the window does for a person. No event is processed.
    box.winfo_id()
    tcl.call("set", "::act_r1_paste", text)
    tcl.eval("rename ::tk::GetSelection ::tk::act_r1_GetSelection")
    tcl.eval("proc ::tk::GetSelection {w {type PRIMARY}} {return $::act_r1_paste}")
    try:
        box.tag_add("sel", "1.0", "end-1c")
        box.mark_set("insert", "1.0")
        box.event_generate("<<Paste>>")
    finally:
        tcl.eval("rename ::tk::GetSelection {}; rename ::tk::act_r1_GetSelection ::tk::GetSelection")
    return panel.chapter_titles_text()


def book_by_id(panel, book_id: str):
    return next(book for book in panel.workspace.books if book.book_id == book_id)


def png(path: Path) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (24, 16), (200, 30, 30)).save(path, format="PNG")
    return path


def config_at(base: Path) -> config.EffectiveConfig:
    """A real captured configuration whose output base is *base*."""
    return dataclasses.replace(make_config(), output=config.OutputConfig(base_directory=base, is_default=False))


def snapshot_bytes(root: Path) -> dict:
    return {path: path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


PASTED = "Pasted chapter one\nPasted chapter two"


# --------------------------------------------------------------------------- #
# R1-1  A pending Chapter Titles edit survives every action that redraws the editor
# --------------------------------------------------------------------------- #


def _shared_artist(panel, ctx):
    panel.surface._row("artist").shared_entry.insert(0, "Typed after paste")


def _shared_album_artist(panel, ctx):
    panel.surface._row("album_artist").shared_entry.insert(0, "Shared House")


def _book_album(panel, ctx):
    panel.surface._row("album").book_entry.insert(0, "Book Album")


def _choose_shared_artwork(panel, ctx):
    panel._choose_artwork = lambda: str(ctx["art"])
    panel.choose_shared_artwork()


def _clear_shared_artwork(panel, ctx):
    panel._choose_artwork = lambda: str(ctx["art"])
    panel.choose_shared_artwork()
    panel.clear_shared_artwork()


def _choose_book_artwork(panel, ctx):
    panel._choose_artwork = lambda: str(ctx["art"])
    panel.choose_book_artwork()


def _clear_book_artwork(panel, ctx):
    panel._choose_artwork = lambda: str(ctx["art"])
    panel.choose_book_artwork()
    panel.clear_book_artwork()


def _auto_number(panel, ctx):
    panel.check_auto_number.invoke()


def _start_number(panel, ctx):
    panel.entry_start_number.delete(0, "end")
    panel.entry_start_number.insert(0, "5")


def _move_track(panel, ctx):
    panel.select_tracks(1)
    panel.move_up()


def _remove_track(panel, ctx):
    panel.select_tracks(1)
    panel.remove_selected_tracks()


def _next_and_back(panel, ctx):
    panel.on_next()
    panel.on_previous()


def _select_away_and_back(panel, ctx):
    panel.on_select(panel.workspace.books[3].book_id)
    panel.on_select(ctx["first"])


def _add_book_and_back(panel, ctx):
    panel.on_add()
    panel.on_select(ctx["first"])


def _duplicate(panel, ctx):
    panel.on_duplicate()


ACTIONS = {
    "shared-artist": _shared_artist,
    "shared-album-artist": _shared_album_artist,
    "book-album": _book_album,
    "choose-shared-artwork": _choose_shared_artwork,
    "clear-shared-artwork": _clear_shared_artwork,
    "choose-book-artwork": _choose_book_artwork,
    "clear-book-artwork": _clear_book_artwork,
    "auto-number-toggle": _auto_number,
    "start-number": _start_number,
    "move-track": _move_track,
    "remove-track": _remove_track,
    "next-then-previous": _next_and_back,
    "select-away-and-back": _select_away_and_back,
    "add-book-and-back": _add_book_and_back,
    "duplicate-book": _duplicate,
}


@pytest.mark.parametrize("action", list(ACTIONS))
def test_a_native_paste_survives_an_action_that_redraws_the_editor_and_reaches_the_plan(
        make_panel, tmp_path, monkeypatch, action):
    """CP1 review finding 1: on b1fbb49 the Shared, per-Book, artwork, numbering and track actions redrew the box
    from the old model and the pasted titles vanished from the box, the model and the plan."""
    reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    first = panel.workspace.current.book_id
    shown = native_paste(panel, PASTED)
    assert shown == PASTED, "Tk's own paste binding replaced the selection"
    assert "chapter_titles" not in panel.workspace.current.configuration, "no key release reported it"

    ACTIONS[action](panel, {"art": png(tmp_path / "art" / "cover.png"), "first": first})

    assert book_by_id(panel, first).configuration["chapter_titles"] == PASTED
    assert panel.chapter_titles_text() == PASTED, "the box still shows what was pasted"
    if action == "duplicate-book":
        copy = panel.workspace.current
        assert copy.book_id != first and copy.configuration["chapter_titles"] == PASTED, "the copy has it too"
        panel.on_select(first)
    assert panel.write_id3_tags() is True
    pump_until(panel, lambda: not panel.is_running)
    planned = next(book for book in engine.plans[0].books if book.book_id == first)
    assert [track.title for track in planned.tracks] == PASTED.split("\n")[:len(planned.tracks)]
    assert planned.snapshot.tool_options["chapter_titles"] == PASTED


@pytest.mark.parametrize("operation", ["write_id3_tags", "combine_mp3s"])
def test_paste_then_shared_artist_then_start_plans_the_pasted_titles(make_panel, tmp_path, monkeypatch, operation):
    """The exact sequence the review reproduced, through both production buttons."""
    reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    native_paste(panel, PASTED)
    panel.surface._row("artist").shared_entry.insert(0, "Typed after paste")
    assert panel.chapter_titles_text() == PASTED
    assert getattr(panel, operation)() is True
    pump_until(panel, lambda: not panel.is_running)
    first = engine.plans[0].books[0]
    assert [track.title for track in first.tracks] == PASTED.split("\n")
    assert first.artist == "Typed after paste"


def test_distinct_edits_in_several_books_each_stay_with_their_own_book(make_panel, tmp_path, monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 21))  # seven Books of three tracks
    ids = [book.book_id for book in panel.workspace.books]
    defaults = {book_id: list(wf.default_titles(book_by_id(panel, book_id), panel.store)) for book_id in ids}
    unicode_text = "Ünïcødé — 第一章\n😀 Two\n"
    native_paste(panel, "Book one A\nBook one B\nBook one C")
    panel.on_next()
    native_paste(panel, unicode_text)
    panel.surface._row("album_artist").shared_entry.insert(0, "House")  # redraws Book 2's box
    panel.on_next()
    panel.chapter_text.delete("1.0", "end")  # cleared, no key release: an empty list is a stored choice
    panel.on_select(ids[0])
    panel.surface._row("album").book_entry.insert(0, "First")  # per-Book edit on Book 1 after returning

    assert book_by_id(panel, ids[0]).configuration["chapter_titles"] == "Book one A\nBook one B\nBook one C"
    assert book_by_id(panel, ids[1]).configuration["chapter_titles"] == unicode_text
    assert book_by_id(panel, ids[2]).configuration["chapter_titles"] == ""
    for untouched in ids[3:]:
        assert "chapter_titles" not in book_by_id(panel, untouched).configuration, "never edited, nothing stored"
    assert panel.combine_mp3s() is True
    pump_until(panel, lambda: not panel.is_running)
    plans = {book.book_id: book for book in engine.plans[0].books}
    assert [t.title for t in plans[ids[0]].tracks] == ["Book one A", "Book one B", "Book one C"]
    assert [t.title for t in plans[ids[1]].tracks][:2] == ["Ünïcødé — 第一章", "😀 Two"]
    for untouched in ids[3:]:
        assert [t.title for t in plans[untouched].tracks] == defaults[untouched]


def test_untouched_default_titles_follow_reordered_tracks_and_store_nothing(make_panel, tmp_path, tk_root):
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    before = panel.chapter_titles_text().split("\n")
    panel.surface._row("artist").shared_entry.insert(0, "Narrator")
    panel.select_tracks(1)
    panel.move_up()
    tk_root.update()  # deliver every queued <<Modified>> the panel's own repaints raised
    panel.on_next()
    panel.on_previous()
    tk_root.update()
    assert "chapter_titles" not in panel.workspace.current.configuration, "a repaint is not an edit"
    assert panel.chapter_titles_text().split("\n") == [before[1], before[0]], "the defaults follow the order"
    assert all("chapter_titles" not in book.configuration for book in panel.workspace.books)


def test_the_modified_flag_commits_a_paste_on_the_next_event_loop_turn(make_panel, tmp_path, tk_root):
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    native_paste(panel, PASTED)
    tk_root.update()
    assert panel.workspace.current.configuration["chapter_titles"] == PASTED
    tk_root.update()  # clearing the flag reports once more; it finds nothing new and nothing loops
    assert panel.workspace.current.configuration["chapter_titles"] == PASTED


def test_the_caret_and_selection_survive_a_commit(make_panel, tmp_path):
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    native_paste(panel, PASTED)
    panel.chapter_text.mark_set("insert", "2.3")
    panel.chapter_text.tag_add("sel", "1.0", "1.6")
    panel.surface._row("artist").shared_entry.insert(0, "X")
    assert panel.chapter_text.index("insert") == "2.3"
    assert panel.chapter_text.tag_ranges("sel") and str(panel.chapter_text.tag_ranges("sel")[1]) == "1.6"


@pytest.mark.parametrize("answer", [False, True], ids=["keep", "remove"])
def test_removing_a_book_with_only_a_pasted_edit_asks_first(make_panel, tmp_path, answer):
    asked: list = []
    panel = make_panel(reader=no_tags, confirm=lambda title, message: asked.append(title) or answer)
    import_folder(panel, library(tmp_path / "Library", 14))
    panel.on_add()  # an empty Book: nothing meaningful until the paste
    added = panel.workspace.current.book_id
    native_paste(panel, "Only a paste")
    panel.on_remove(False)  # the navigator could not know of the paste yet
    assert asked == ["Remove this Book?"]
    assert (added in panel.workspace.book_ids) is (not answer)
    if not answer:
        assert book_by_id(panel, added).configuration["chapter_titles"] == "Only a paste"


def test_adding_files_keeps_a_pasted_edit_and_only_the_new_track_takes_its_default(make_panel, tmp_path, monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    native_paste(panel, PASTED)
    extra = tmp_path / "Extra" / "9999 Late Chapter.mp3"
    extra.parent.mkdir()
    extra.write_bytes(b"not audio")
    panel._choose_files = lambda: (str(extra),)
    panel.add_files()
    assert panel.workspace.current.file_count == 3
    assert panel.workspace.current.configuration["chapter_titles"] == PASTED and panel.chapter_titles_text() == PASTED
    assert panel.write_id3_tags() is True
    pump_until(panel, lambda: not panel.is_running)
    titles = [track.title for track in engine.plans[0].books[0].tracks]
    assert titles[:2] == PASTED.split("\n") and titles[2] not in PASTED.split("\n")


def test_import_folder_asks_before_replacing_a_book_whose_only_work_is_a_pasted_edit(make_panel, tmp_path):
    asked: list = []
    panel = make_panel(reader=no_tags, confirm=lambda title, message: asked.append(title) or False)
    native_paste(panel, "Only a paste")  # the pristine startup Book: nothing meaningful but this
    panel._choose_folder = lambda: (str(library(tmp_path / "Library", 14)),)
    panel.import_folder()
    assert asked == ["Replace the current Books?"]
    assert panel.workspace.count == 1 and panel.workspace.current.configuration["chapter_titles"] == "Only a paste"
    assert panel.chapter_titles_text() == "Only a paste"


def test_a_late_modified_event_after_a_book_switch_stores_nothing_on_the_new_book(make_panel, tmp_path, tk_root):
    """Event ordering: the paste's queued ``<<Modified>>`` is delivered only after the selection has moved."""
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    first, second = panel.workspace.books[0].book_id, panel.workspace.books[1].book_id
    native_paste(panel, PASTED)
    panel.on_next()  # commits to Book 1 and repaints for Book 2 before Tk has delivered the paste's <<Modified>>
    tk_root.update()
    tk_root.update()
    assert book_by_id(panel, first).configuration["chapter_titles"] == PASTED
    assert "chapter_titles" not in book_by_id(panel, second).configuration, "the late event found nothing new"


def test_undo_cannot_bring_another_books_titles_into_this_book(make_panel, tmp_path):
    """On v0.8.1 and b1fbb49 the repaint was on the undo stack: Ctrl+Z after a Book switch blanked the box, and a
    second one restored the previous Book's titles for the next key release to store on this Book."""
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    second = panel.workspace.books[1].book_id
    panel.on_next()
    shown = panel.chapter_titles_text()
    for _ in range(3):
        try:
            panel.chapter_text.edit_undo()  # what Ctrl+Z asks the Text widget for
        except tk.TclError:
            pass  # "nothing to undo"
        panel.on_chapter_edit()  # and the key release that follows it
    assert panel.chapter_titles_text() == shown, "the repaint is not something undo can take back"
    assert "chapter_titles" not in book_by_id(panel, second).configuration
    # The user's own edits in this Book are still undoable.
    panel.chapter_text.insert("1.0", "Typed ")
    panel.chapter_text.edit_separator()
    panel.on_chapter_edit()
    assert book_by_id(panel, second).configuration["chapter_titles"] == "Typed " + shown
    panel.chapter_text.edit_undo()
    panel.on_chapter_edit()
    assert panel.chapter_titles_text() == shown and book_by_id(panel, second).configuration["chapter_titles"] == shown


def test_clear_all_imports_asks_when_the_only_work_is_a_pasted_edit(make_panel, tmp_path):
    asked: list = []
    panel = make_panel(reader=no_tags, confirm=lambda title, message: asked.append(title) or False)
    native_paste(panel, "Only a paste")  # a pristine workspace otherwise: nothing else to lose
    assert panel.clear_all_imports() is False
    assert asked == ["Clear all imports?"]
    assert panel.workspace.current.configuration["chapter_titles"] == "Only a paste"
    assert panel.chapter_titles_text() == "Only a paste"


def test_a_pending_edit_never_lands_on_a_book_it_was_not_typed_for(make_panel, tmp_path):
    """The bound Book identity: even if the selection had already moved, the edit goes to its own Book."""
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    first, second = panel.workspace.books[0].book_id, panel.workspace.books[1].book_id
    native_paste(panel, PASTED)
    # A model change that moved the selection before anything flushed (what an unforeseen callback would do).
    panel.workspace = select_book(panel.workspace, second).workspace
    panel.render()
    assert book_by_id(panel, first).configuration["chapter_titles"] == PASTED
    assert "chapter_titles" not in book_by_id(panel, second).configuration
    assert panel.chapter_titles_text() != PASTED, "Book 2's own titles are shown"


# --------------------------------------------------------------------------- #
# R1-2  A failure while the new run is set up never strands the panel
# --------------------------------------------------------------------------- #


def _fail_install(panel, monkeypatch):
    real = panel._install_jobs
    state = {"left": 1}

    def install(run_id, item_ids):
        if state["left"]:
            state["left"] -= 1
            raise tk.TclError("fixture: adapter installation failed")
        return real(run_id, item_ids)

    monkeypatch.setattr(panel, "_install_jobs", install)


def _fail_adapter(panel, monkeypatch):
    real = job_ui.JobAdapter
    state = {"left": 1}

    def adapter(*args, **kwargs):
        if state["left"]:
            state["left"] -= 1
            raise tk.TclError("fixture: the job area could not be built")
        return real(*args, **kwargs)

    monkeypatch.setattr(mp3_tool.job_ui, "JobAdapter", adapter)


def _fail_dressing(panel, monkeypatch):
    real = job_ui.JobAdapter.register_options
    state = {"left": 1}

    def register(self, *args, **kwargs):
        if state["left"]:
            state["left"] -= 1
            raise tk.TclError("fixture: the job area could not be dressed")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(job_ui.JobAdapter, "register_options", register)


BEFORE_HANDOVER = {"install-jobs": _fail_install, "adapter-constructor": _fail_adapter,
                   "adapter-dressing": _fail_dressing}


@pytest.mark.parametrize("boundary", list(BEFORE_HANDOVER))
def test_a_setup_failure_before_handover_ends_like_a_refused_preparation(make_panel, tmp_path, monkeypatch, boundary):
    """CP1 review finding 2: on b1fbb49 the panel stayed busy with an IDLE controller, no worker and the run kept."""
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    drains = list(panel._pump._drains)
    jobs = panel.jobs
    BEFORE_HANDOVER[boundary](panel, monkeypatch)

    assert panel.write_id3_tags() is True
    pump_until(panel, lambda: not panel.is_running)
    assert not panel.is_preparing and not panel._busy
    assert panel.job_controller is None and panel.last_plan is None and panel.last_result is None
    assert panel.jobs is jobs and panel._pump._drains == drains, "the previous job area, and one job drain"
    assert engine.plans == [] and conversion_workers(panel) == []
    assert len(made) == 1 and not made[0].run_directory.exists(), "the unused empty run was released"
    assert make_panel.dialogs[-1] == ("error", "Write ID3 Tags: the job could not be started, and nothing was started.")
    assert panel.status.status_text == mp3_tool.STATUS_PREPARATION_FAILED
    assert any("fixture:" in line for line in panel.log.details)
    assert panel._pump.running and panel.navigator.locked is False
    assert str(panel.btn_write_id3.cget("state")) == "normal"

    assert panel.write_id3_tags() is True, "the next press works"
    pump_until(panel, lambda: not panel.is_running)
    assert len(engine.plans) == 1 and engine.plans[0].run_directory == made[1].run_directory


def test_a_controller_that_cannot_start_frees_the_panel_without_reporting_a_run(make_panel, tmp_path, monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 7))

    def refuse(self):
        raise job_control.JobContractError("fixture: the controller cannot start")

    monkeypatch.setattr(job_control.JobController, "start", refuse)
    assert panel.write_id3_tags() is True
    pump_until(panel, lambda: not panel.is_running)
    assert panel.job_controller.state is JobState.IDLE, "never reported as running"
    assert not panel.is_running and panel.last_result is None
    assert engine.plans == [] and conversion_workers(panel) == []
    assert any("fixture: the controller cannot start" in line for line in panel.log.details)
    assert panel._pump.running and str(panel.btn_write_id3.cget("state")) == "normal"
    assert made[0].run_directory.is_dir(), "a failed run keeps its folder, as a worker fault does"


def test_a_failure_after_handover_settles_the_run_as_failed(make_panel, tmp_path, monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 7))
    real = job_control.JobReporter.stage_changed
    state = {"left": 1}

    def stage(self, *args, **kwargs):
        if state["left"]:
            state["left"] -= 1
            raise RuntimeError("fixture: the first report failed")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(job_control.JobReporter, "stage_changed", stage)
    assert panel.write_id3_tags() is True
    pump_until(panel, lambda: not panel.is_running)
    assert panel.job_controller.state is JobState.FAILED and panel.last_result.state is JobState.FAILED
    assert engine.plans == [] and conversion_workers(panel) == []
    assert panel._pump.running and str(panel.btn_write_id3.cget("state")) == "normal"
    assert made[0].run_directory.is_dir()


@needs_ffmpeg
def test_a_setup_failure_keeps_the_previous_runs_retry_and_its_staging(make_panel, tmp_path, monkeypatch):
    from test_mp3_orchestration import settle, three_books

    panel = make_panel()
    made, _root = three_books(panel, tmp_path, monkeypatch)  # Book B's second track is broken
    panel.write_id3_tags()
    settle(panel)
    first_plan, first_result, jobs = panel.last_plan, panel.last_result, panel.jobs
    assert first_result.state is JobState.COMPLETED_WITH_FAILURES
    kept = first_plan.books[1].tracks[0].staged
    assert kept.is_file() and panel.controls.availability()[JobAction.RETRY_FAILED] is True

    _fail_install(panel, monkeypatch)
    assert panel.write_id3_tags() is True
    settle(panel)
    assert panel.last_plan is first_plan and panel.last_result is first_result and panel.jobs is jobs
    assert not panel._attempt.abandoned, "the previous run is still the one Retry Failed reaches"
    assert len(made) == 2 and not made[1].run_directory.exists()
    assert kept.is_file(), "the previous run's kept staging was not discarded"
    assert panel.controls.availability()[JobAction.RETRY_FAILED] is True

    _fail_install(panel, monkeypatch)
    assert panel.retry_failed() is False, "a retry whose setup fails changes nothing"
    assert make_panel.dialogs[-1] == ("error", "Retry Failed: the retry could not be started; nothing was changed.")
    assert kept.is_file() and panel.controls.availability()[JobAction.RETRY_FAILED] is True

    assert panel.retry_failed() is True
    settle(panel)
    assert panel.last_plan is first_plan, "the retry re-ran the original frozen plan"


# --------------------------------------------------------------------------- #
# R1-3  One configuration snapshot governs the whole operation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("paused", ["before-reserving", "while-planning"])
def test_the_press_configuration_is_the_capture_the_reservation_and_the_plan(make_panel, tmp_path, monkeypatch,
                                                                            paused):
    """CP1 review finding 3: on b1fbb49 every Book snapshot recorded A (construction) while the run went to B."""
    engine = EngineSpy(monkeypatch)
    a, b, c = (config_at(tmp_path / name) for name in ("A", "B", "C"))
    monkeypatch.setattr(mp3_tool.shared_config, "get_effective", lambda: a)
    seen: list = []
    real_reserve = output_paths.reserve_run_directory

    def reserve(tool_key, *, effective=None, **kwargs):
        seen.append(effective)
        return real_reserve(tool_key, effective=effective, **kwargs)

    monkeypatch.setattr(output_paths, "reserve_run_directory", reserve)

    if paused == "before-reserving":
        class Parked(tic.InlineThread):
            def start(self):
                if not self.name.startswith("mp3-prepare-"):
                    return super().start()
                self.starts += 1  # run later, by the test

        panel = make_panel(effective_config=a, reader=no_tags, thread_factory=RecordingThreads(kind=Parked))
        import_folder(panel, library(tmp_path / "Library", 14))
        monkeypatch.setattr(mp3_tool.shared_config, "get_effective", lambda: b)  # Preferences saved before Start
        assert panel.write_id3_tags() is True
        monkeypatch.setattr(mp3_tool.shared_config, "get_effective", lambda: c)  # and again while it waits
        next(t for t in panel._thread_factory.made if t.name.startswith("mp3-prepare-")).target()
    else:
        gate = PreparationGate(monkeypatch)
        panel = make_panel(effective_config=a, reader=no_tags, thread_factory=RealThreads())
        import_and_settle(panel, library(tmp_path / "Library", 14))
        monkeypatch.setattr(mp3_tool.shared_config, "get_effective", lambda: b)
        assert panel.write_id3_tags() is True
        assert gate.entered.wait(20.0)
        monkeypatch.setattr(mp3_tool.shared_config, "get_effective", lambda: c)  # while the worker is held
        gate.release.set()
    pump_until(panel, lambda: not panel.is_running)
    if paused == "while-planning":
        join_all(panel)

    plan = engine.plans[0]
    assert seen == [b], "the reservation used the configuration of the press, once"
    assert all(book.snapshot.effective_config is b for book in plan.books), "every snapshot records the same one"
    assert plan.reservation.base_directory == output_paths.resolve_output_base(b)
    assert plan.run_directory.is_relative_to(tmp_path / "B")
    assert all(track.published.is_relative_to(tmp_path / "B") for book in plan.books for track in book.tracks)
    assert not (tmp_path / "A").exists() and not (tmp_path / "C").exists()


# --------------------------------------------------------------------------- #
# R1-4  A supplied capture must be a capture of the workspace it is planned against
# --------------------------------------------------------------------------- #


def _space(tmp_path: Path):
    from test_mp3_plan import book, observe, workspace

    root = tmp_path / "src"
    root.mkdir()
    books = (book(root, "A", ["1.mp3", "2.mp3", "3.mp3"], album="Alpha"),
             book(root, "B", ["4.mp3", "5.mp3"], album="Beta"))
    return workspace(*books), observe(*books)


def _capture(space):
    return mp3_plan.capture_for_run(space, catalog=wf.MP3_CATALOG,
                                    import_options=ImportOptions.for_catalog(wf.MP3_CATALOG),
                                    effective_config=make_config(), id_factory=IdFactory("r1-"))


def _reservation(tmp_path: Path, name: str = "run"):
    directory = tmp_path / "Outputs" / name
    directory.mkdir(parents=True)
    return output_paths.RunReservation(tool_key="mp3_tool", base_directory=tmp_path / "Outputs",
                                       tool_directory=tmp_path / "Outputs", run_directory=directory, run_number=1)


def _plan(space, store, capture, reservation):
    return mp3_plan.plan_run(space, store, operation=mp3_plan.MP3Operation.WRITE_ID3,
                             reservation=reservation, capture=capture)


def _reorder(space):
    first = space.current.files.files[1].occurrence_id
    return wf.move_tracks(space, (first,), wf.UP).workspace


def _remove_track(space):
    return wf.remove_tracks(space, (space.current.files.files[0].occurrence_id,)).workspace


def _book_setting(space):
    return wf.set_book_field(space, "album", "Changed").workspace


def _chapter_titles(space):
    return wf.set_book_field(space, "chapter_titles", "New\nTitles").workspace


def _shared_setting(space):
    return set_shared_metadata(space, SharedMetadata(
        wf.SHARED_FIELDS, {**space.shared.values, "artist": "Someone Else"})).workspace


def _empty_book_added(space):
    return add_book(space, id_factory=IdFactory("r1-add-")).workspace


STALE = {"same-book-reordered": (_reorder, "track order"),
         "same-book-track-removed": (_remove_track, "track order"),
         "same-book-setting-changed": (_book_setting, "different settings"),
         "same-book-titles-changed": (_chapter_titles, "different settings"),
         "shared-setting-changed": (_shared_setting, "Shared settings"),
         "book-added": (_empty_book_added, "their order")}


@pytest.mark.parametrize("change", list(STALE))
def test_a_stale_capture_of_the_same_books_is_refused(tmp_path, change):
    """CP1 review finding 4: on b1fbb49 a capture of the same Book ids planned a hybrid of old and new contents."""
    space, store = _space(tmp_path)
    capture = _capture(space)
    edit, words = STALE[change]
    changed = edit(space)
    assert set(capture.attempted_book_ids) <= set(changed.book_ids), "every captured Book id still exists"
    with pytest.raises(mp3_plan.PlanError, match=words):
        _plan(changed, store, capture, _reservation(tmp_path))


def test_a_matching_capture_plans_exactly_what_it_captured(tmp_path):
    space, store = _space(tmp_path)
    capture = _capture(space)
    made = _plan(space, store, capture, _reservation(tmp_path, "one"))
    for book in made.books:
        assert book.snapshot is capture.snapshot_for(book.book_id)
        assert tuple(t.occurrence_id for t in book.tracks) == book.snapshot.item_ids
    # Equal but separately built values are the same workspace: a reorder and its undo plan cleanly.
    undone = _reorder(_reorder(space))
    assert [e.occurrence_id for e in undone.current.files.files] == [e.occurrence_id
                                                                     for e in space.current.files.files]
    _plan(space, store, _capture(space), _reservation(tmp_path, "two"))


def test_validating_a_capture_is_linear_in_the_tracks(tmp_path):
    """The check is one pass per Book: 5,000 tracks validate in well under the time planning them takes."""
    from test_mp3_plan import book, observe, workspace

    root = tmp_path / "src"
    root.mkdir()
    books = tuple(book(root, f"B{n}", [f"{n:02d}-{i:04d}.mp3" for i in range(715)]) for n in range(7))
    space = workspace(*books)
    capture = _capture(space)
    began = time.perf_counter()
    mp3_plan._require_capture_matches(capture, space)
    assert time.perf_counter() - began < 1.0


# --------------------------------------------------------------------------- #
# R1-5  Cancel and Close after the plan was offered never wait on the filesystem on Tk
# --------------------------------------------------------------------------- #


class SlowRelease:
    """``release_if_empty`` behind injected storage latency; records the thread it ran on."""

    def __init__(self, monkeypatch, *, delay: float = 0.6, outcome: str = "release") -> None:
        self.threads: list = []
        self.calls = 0
        self.done = threading.Event()
        real = output_paths.release_if_empty

        def slow(reservation):
            self.threads.append(threading.current_thread())
            self.calls += 1
            try:
                time.sleep(delay)
                if outcome == "raise":
                    raise OSError("fixture: the storage went away")
                if outcome == "refuse":
                    return False
                return real(reservation)
            finally:
                self.done.set()

        monkeypatch.setattr(output_paths, "release_if_empty", slow)


def _offered(panel, tmp_path, monkeypatch, tracks: int = 14):
    """A real preparation worker that has finished and offered its plan, which the pump has not yet seen."""
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    import_and_settle(panel, library(tmp_path / "Library", tracks))
    sources = snapshot_bytes(tmp_path / "Library")
    assert panel.write_id3_tags() is True
    preparation = panel._preparing
    deadline = time.monotonic() + 20.0
    while not preparation._handed_over:  # no pump tick here: the plan stays offered, unadopted
        assert time.monotonic() < deadline
        time.sleep(0.005)
    return made, engine, sources


def _with_heartbeat(tk_root, action, until, timeout: float = 20.0):
    """Run *action* on the Tk thread with a 20 ms ``after`` heartbeat armed; return (action seconds, gaps).

    The action runs before the event loop is entered, so the panel's pump cannot adopt the offered plan first (an
    overdue pump tick would otherwise win the race on a large job). The first gap includes the action's own time;
    the heartbeat then keeps beating through the loop until *until* holds.
    """
    gaps: list[float] = []
    state = {"last": time.perf_counter(), "beating": True, "seconds": None}

    def beat():
        now = time.perf_counter()
        gaps.append(now - state["last"])
        state["last"] = now
        if state["beating"]:
            state["after"] = tk_root.after(20, beat)

    state["after"] = tk_root.after(20, beat)
    began = time.perf_counter()
    action()
    state["seconds"] = time.perf_counter() - began
    deadline = time.monotonic() + timeout
    while state["seconds"] is None or not until():
        assert time.monotonic() < deadline, "timed out"
        tk_root.update()
        time.sleep(0.002)
    state["beating"] = False
    tk_root.after_cancel(state["after"])
    return state["seconds"], gaps


@pytest.mark.parametrize("ending", ["cancel", "close"])
def test_cancel_or_close_after_offer_returns_at_once_while_slow_cleanup_runs_off_tk(
        make_panel, tmp_path, monkeypatch, tk_root, ending):
    """CP1 review finding 5: on b1fbb49 Cancel took as long as the storage (240 ms for 240 ms of latency)."""
    slow = SlowRelease(monkeypatch, delay=0.6)
    panel = make_panel(thread_factory=RealThreads(), reader=no_tags)
    made, engine, sources = _offered(panel, tmp_path, monkeypatch)
    action = panel.cancel if ending == "cancel" else panel.close
    settled = ((lambda: slow.done.is_set() and not panel.is_running) if ending == "cancel"
               else slow.done.is_set)
    seconds, gaps = _with_heartbeat(tk_root, action, settled)
    join_all(panel)

    assert seconds < 0.1, f"{ending} waited on the storage: {seconds:.3f} s"
    assert max(gaps) < 0.3, f"largest heartbeat gap {max(gaps):.3f} s"
    assert slow.calls == 1 and slow.threads[0] is not threading.main_thread()
    assert slow.threads[0].name.startswith("mp3-release-")
    assert not made[0].run_directory.exists(), "the empty run was still released"
    assert engine.plans == [] and conversion_workers(panel) == [], "an offered plan never starts"
    assert snapshot_bytes(tmp_path / "Library") == sources, "no source was touched"
    if ending == "cancel":
        assert panel.status.status_text == mp3_tool.STATUS_PREPARATION_CANCELLED
        assert panel.last_plan is None and panel.job_controller is None


@pytest.mark.parametrize("outcome", ["raise", "refuse"])
def test_a_failing_cleanup_never_reaches_tk_and_leaves_only_the_empty_run(make_panel, tmp_path, monkeypatch, tk_root,
                                                                           outcome):
    slow = SlowRelease(monkeypatch, delay=0.2, outcome=outcome)
    escaped: list = []
    monkeypatch.setattr(threading, "excepthook", lambda args: escaped.append(args))
    panel = make_panel(thread_factory=RealThreads(), reader=no_tags)
    made, engine, sources = _offered(panel, tmp_path, monkeypatch)
    seconds, _gaps = _with_heartbeat(tk_root, panel.cancel, lambda: slow.done.is_set() and not panel.is_running)
    join_all(panel)
    assert seconds < 0.1 and escaped == []
    assert made[0].run_directory.is_dir() and not any(made[0].run_directory.iterdir()), "left in place, empty"
    assert panel.status.status_text == mp3_tool.STATUS_PREPARATION_CANCELLED and not panel.is_running
    assert engine.plans == [] and snapshot_bytes(tmp_path / "Library") == sources


def test_repeated_cancel_after_offer_releases_the_run_exactly_once(make_panel, tmp_path, monkeypatch):
    slow = SlowRelease(monkeypatch, delay=0.1)
    panel = make_panel(thread_factory=RealThreads(), reader=no_tags)
    made, engine, _sources = _offered(panel, tmp_path, monkeypatch)
    panel.cancel()
    panel.cancel()
    panel.close()
    assert slow.done.wait(10.0)
    join_all(panel)
    assert slow.calls == 1 and not made[0].run_directory.exists() and engine.plans == []


def test_when_no_cleanup_worker_can_start_the_empty_run_is_left_and_named(make_panel, tmp_path, monkeypatch):
    class NoReleaseThread(RealThreads):
        def __call__(self, target, name):
            if name.startswith("mp3-release-"):
                raise RuntimeError("can't start new thread")
            return super().__call__(target, name)

    panel = make_panel(thread_factory=NoReleaseThread(), reader=no_tags)
    made, engine, _sources = _offered(panel, tmp_path, monkeypatch)
    began = time.perf_counter()
    panel.cancel()
    assert time.perf_counter() - began < 0.1
    pump_until(panel, lambda: not panel.is_running)
    join_all(panel)
    assert made[0].run_directory.is_dir() and engine.plans == []
    assert any("Unused run left in place" in line for line in panel.log.details)
    assert panel.status.status_text == mp3_tool.STATUS_PREPARATION_CANCELLED
