"""The integrated MP3 Tool — v0.6.3 focused MP3 plan, Phase 9.

Phase 9 wires the two processing buttons to the Phase 7 and Phase 8 engines
through **one** Plan 3 ``JobController`` per operation: validate, reserve one
run, freeze one Phase 5 plan, start one worker, project the engine's events
into the shared job-event architecture, settle the Plan 6
``WorkspaceRunResult`` on the main thread, and offer the exact failed-item
Retry Failed against the original frozen state. Pause / Resume / Cancel reach
the engines only through the controller's checkpoint. The panel has exactly
one log region — Summary | Detailed — whose history survives across runs and
whose Clear Log clears visible text only.

Real media, deliberately, wherever a run is asserted: one-second tones made by
the pinned FFmpeg under ``tmp_path``. Runs are deterministic: the worker is
handed to the panel's thread-factory seam, which runs it inline unless a test
is *about* threads, and the one pump is ticked by hand.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

from shared import ffmpeg_utils, job_control, job_ui  # noqa: E402
from shared.book_workspace import (  # noqa: E402
    BookDisposition,
    WorkspaceRunResult,
    retry_failed_books,
)
from shared.job_control import (  # noqa: E402
    ControlKind,
    JobAction,
    JobEventKind,
    JobState,
    is_available,
    is_locked,
)

from mp3_tools import mp3_plan, mp3_processing as proc, mp3_tool  # noqa: E402

from test_import_coordination import RealThreads  # noqa: E402
from test_mp3_tool_ui import (  # noqa: E402,F401  (fixtures are collected by name)
    import_folder,
    make_panel,
    reservations_under,
    tk_root,
    widgets_of,
    windows_theme,
)
from test_mp3_write_id3 import junk_tag, sha, texts, tone  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ffmpeg_utils.have_ffmpeg(), reason="ffmpeg/ffprobe not available in this environment")

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
PANEL_SOURCE = UNIVERSAL / "mp3_tools" / "mp3_tool.py"
ENGINE_SOURCE = UNIVERSAL / "mp3_tools" / "mp3_processing.py"
JOB_UI_SOURCE = UNIVERSAL / "shared" / "job_ui.py"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def library(root: Path, layout: dict[str, tuple[str, ...]]) -> Path:
    """Real tones, junk-tagged, one folder per Book."""
    for folder, names in layout.items():
        for index, name in enumerate(names):
            junk_tag(tone(root / folder / name, freq=330 + 55 * index))
    return root


def corrupt(path: Path) -> Path:
    path.write_bytes(b"this is not an mp3 at all")
    return path


def settle(panel, limit: int = 200) -> None:
    """Tick the one pump until the run has settled (inline workers only)."""
    for _ in range(limit):
        panel._pump.tick()
        if not panel.is_running:
            return
    raise AssertionError("the run did not settle within the tick budget")


def wait_for(panel, predicate, timeout: float = 20.0) -> None:
    """Pump on the main thread until *predicate* holds. Real workers only."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        panel._pump.tick()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for the run")


def three_books(panel, tmp_path: Path, monkeypatch, *, broken: str | None = "B"):
    """A / B / C imported into the panel; B's second track is broken by default."""
    made = reservations_under(tmp_path, monkeypatch)
    root = library(tmp_path / "Library", {
        "A": ("01 One.mp3", "02 Two.mp3"),
        "B": ("01 One.mp3", "02 Two.mp3", "03 Three.mp3"),
        "C": ("01 One.mp3",),
    })
    if broken:
        corrupt(root / broken / "02 Two.mp3")
    import_folder(panel, root)
    wait_for(panel, lambda: panel.workspace.count == 3)
    return made, root


def statuses(panel) -> list[str]:
    return [panel.book_status_for(book.book_id) for book in panel.workspace.books]


def events_of(panel, kind: JobEventKind):
    return [e for e in panel.jobs.stream.events if e.kind is kind]


# --------------------------------------------------------------------------- #
# One JobController per operation, through the real engines
# --------------------------------------------------------------------------- #


def test_write_id3_runs_every_book_through_one_controller(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    controllers: list[job_control.JobController] = []
    real = job_control.JobController.__init__

    def spy(self, run_id, *, listener=None):
        controllers.append(self)
        real(self, run_id, listener=listener)

    monkeypatch.setattr(mp3_tool.job_control.JobController, "__init__", spy)
    assert panel.write_id3_tags() is True
    settle(panel)

    assert len(controllers) == 1, "one controller for the whole operation"
    assert controllers[0].state is JobState.SUCCEEDED
    assert len(made) == 1, "one reservation for three Books"
    result = panel.last_result
    assert isinstance(result, WorkspaceRunResult)
    assert result.state is JobState.SUCCEEDED
    assert result.snapshot is panel.last_plan.capture
    assert [result.disposition_for(b.book_id) for b in panel.workspace.books] == [
        BookDisposition.SUCCEEDED] * 3
    for entry in panel.last_plan.books:
        assert entry.published_dir.is_dir()
        for track in entry.tracks:
            assert track.published.is_file()
            assert texts(track.published)["TIT2"] == track.title
    assert not panel.last_plan.work_root.exists()
    assert statuses(panel) == ["Completed"] * 3
    assert panel.jobs.state is JobState.SUCCEEDED
    assert panel.is_running is False


def test_combine_runs_through_the_same_orchestration(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    assert panel.combine_mp3s() is True
    settle(panel)
    result = panel.last_result
    assert result.state is JobState.SUCCEEDED
    assert panel.last_plan.operation is mp3_plan.MP3Operation.COMBINE
    for entry in panel.last_plan.books:
        assert entry.combined_published.is_file()
        assert entry.timestamps_published.is_file()
    assert statuses(panel) == ["Completed"] * 3
    assert any(e.location == panel.last_plan.books[0].published_dir
               for e in events_of(panel, JobEventKind.OUTPUT_LOCATION))


def test_a_second_operation_is_refused_while_one_runs(make_panel, tmp_path, monkeypatch):
    panel = make_panel(thread_factory=RealThreads())
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    gate = threading.Event()
    real_book = proc.write_id3_book

    def slow(book, **kwargs):
        gate.wait(10.0)
        return real_book(book, **kwargs)

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_book", slow)
    assert panel.write_id3_tags() is True
    assert panel.is_running is True
    assert panel.write_id3_tags() is False
    assert panel.combine_mp3s() is False
    assert len(made) == 1, "the refused presses reserved nothing"
    gate.set()
    wait_for(panel, lambda: not panel.is_running)
    assert panel.last_result.state is JobState.SUCCEEDED


def test_the_process_buttons_lock_through_the_shared_matrix(make_panel, tmp_path, monkeypatch):
    panel = make_panel(thread_factory=RealThreads())
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    gate = threading.Event()
    real_book = proc.write_id3_book

    def slow(book, **kwargs):
        gate.wait(10.0)
        return real_book(book, **kwargs)

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_book", slow)
    panel.write_id3_tags()
    wait_for(panel, lambda: panel.jobs.state is JobState.RUNNING)
    assert is_locked(ControlKind.IMPORTED_INPUT, JobState.RUNNING)
    assert panel.navigator.locked is True
    assert str(panel.btn_write_id3.cget("state")) == "disabled"
    assert str(panel.btn_combine.cget("state")) == "disabled"
    assert str(panel.btn_import_folder.cget("state")) == "disabled"
    assert panel.surface.book_field_enabled("artist") is False
    availability = panel.controls.availability()
    for action in availability:
        assert availability[action] == is_available(action, JobState.RUNNING), action
    gate.set()
    wait_for(panel, lambda: not panel.is_running)
    assert panel.navigator.locked is False
    assert str(panel.btn_write_id3.cget("state")) == "normal"
    availability = panel.controls.availability()
    for action in availability:
        assert availability[action] == is_available(
            action, JobState.SUCCEEDED, has_retryable=False), action


# --------------------------------------------------------------------------- #
# Pause / Resume / Cancel through the checkpoint seam
# --------------------------------------------------------------------------- #


def test_pause_is_shown_only_once_the_worker_acknowledged_it(make_panel, tmp_path, monkeypatch):
    panel = make_panel(thread_factory=RealThreads())
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    started = threading.Event()
    real_book = proc.write_id3_book

    def slow(book, *, checkpoint=None, on_event=None, **kwargs):
        started.set()
        return real_book(book, checkpoint=checkpoint, on_event=on_event, **kwargs)

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_book", slow)
    panel.write_id3_tags()
    controller = panel.job_controller
    assert isinstance(controller, job_control.JobController)
    started.wait(10.0)
    panel.pause()
    assert controller.state in (JobState.PAUSE_REQUESTED, JobState.PAUSED)
    wait_for(panel, lambda: panel.jobs.state is JobState.PAUSED)
    assert controller.state is JobState.PAUSED
    assert panel.status.status_text == "Paused."
    availability = panel.controls.availability()
    assert availability[JobAction.RESUME] is True
    assert availability[JobAction.PAUSE] is False
    panel.resume()
    wait_for(panel, lambda: not panel.is_running)
    assert panel.last_result.state is JobState.SUCCEEDED
    states = [e.state for e in events_of(panel, JobEventKind.STATE_CHANGED)]
    assert JobState.PAUSED in states and states.index(JobState.PAUSED) < states.index(
        JobState.SUCCEEDED)


def test_cancel_stops_at_the_next_checkpoint_and_leaves_later_books_not_attempted(
        make_panel, tmp_path, monkeypatch):
    panel = make_panel(thread_factory=RealThreads())
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    first_done = threading.Event()
    proceed = threading.Event()
    real_book = proc.write_id3_book
    count = {"n": 0}

    def counting(book, **kwargs):
        report = real_book(book, **kwargs)
        count["n"] += 1
        first_done.set()
        proceed.wait(10.0)
        return report

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_book", counting)
    panel.write_id3_tags()
    first_done.wait(10.0)
    panel.cancel()
    assert panel.job_controller.state is JobState.CANCEL_REQUESTED
    proceed.set()
    wait_for(panel, lambda: not panel.is_running)
    result = panel.last_result
    assert result.state is JobState.CANCELLED
    assert panel.job_controller.state is JobState.CANCELLED
    books = panel.workspace.books
    assert result.disposition_for(books[0].book_id) is BookDisposition.SUCCEEDED
    assert result.disposition_for(books[2].book_id) is BookDisposition.NOT_ATTEMPTED
    assert not hasattr(BookDisposition, "CANCELLED")
    assert count["n"] == 1, "cancel stopped at the checkpoint before Book 2"
    assert result.disposition_for(books[1].book_id) is BookDisposition.NOT_ATTEMPTED
    assert panel.jobs.stream.terminal.kind is JobEventKind.CANCELLED
    assert statuses(panel)[0] == "Completed" and statuses(panel)[2] == "Ready"
    assert panel.controls.availability()[JobAction.RETRY_FAILED] is False


# --------------------------------------------------------------------------- #
# A succeeds / B fails / C succeeds, then Retry Failed against the frozen state
# --------------------------------------------------------------------------- #


def test_a_succeeds_b_fails_c_succeeds_settles_completed_with_failures(
        make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch)
    panel.write_id3_tags()
    settle(panel)
    result = panel.last_result
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    a, b, c = panel.workspace.books
    assert result.disposition_for(a.book_id) is BookDisposition.SUCCEEDED
    assert result.disposition_for(b.book_id) is BookDisposition.FAILED
    assert result.disposition_for(c.book_id) is BookDisposition.SUCCEEDED
    assert result.retryable_book_ids == (b.book_id,)
    assert result.can_retry_failed is True
    assert statuses(panel) == ["Completed", "Failed", "Completed"]
    assert panel.controls.availability()[JobAction.RETRY_FAILED] is True
    plan_b = panel.last_plan.book_for(b.book_id)
    assert not plan_b.published_dir.exists()
    survivors = [t for t in plan_b.tracks if t.source.name != "02 Two.mp3"]
    assert all(t.staged.is_file() for t in survivors), "retained for the retry"
    failures = events_of(panel, JobEventKind.FAILURE)
    assert len(failures) == 1
    assert failures[0].item_id == plan_b.track_for(failures[0].item_id).occurrence_id
    assert "02 Two.mp3" in failures[0].message


def test_retry_failed_reruns_only_b_against_the_original_frozen_state(
        make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch)
    panel.surface.set_shared_text("album", "Frozen Album")
    panel.write_id3_tags()
    settle(panel)
    first = panel.last_result
    plan = panel.last_plan
    a, b, c = panel.workspace.books
    snapshot_b = plan.book_for(b.book_id).snapshot
    published_a = {t.published: sha(t.published) for t in plan.book_for(a.book_id).tracks}
    published_c = {t.published: sha(t.published) for t in plan.book_for(c.book_id).tracks}
    mtimes = {p: p.stat().st_mtime_ns for p in list(published_a) + list(published_c)}
    kept = [t for t in plan.book_for(b.book_id).tracks if t.source.name != "02 Two.mp3"]
    kept_mtimes = {t.staged: t.staged.stat().st_mtime_ns for t in kept}

    # Edit the live GUI every way there is: nothing may reach the retry.
    panel.surface.set_shared_text("album", "Edited Later")
    panel.surface.set_shared_text("time_delta", "2")
    panel.navigator.invoke(panel.navigator.NEXT)
    panel.type_chapter_titles("Renamed\nTitles\nHere")
    panel.set_book_field("artist", "Someone Else")
    panel.type_start_number("7")
    panel.navigator.invoke(panel.navigator.ADD)
    assert panel.workspace.count == 4

    # Repair the source the plan froze, then retry.
    junk_tag(tone(root / "B" / "02 Two.mp3", freq=500))
    requests = retry_failed_books(first)
    assert len(requests) == 1 and requests[0].snapshot is snapshot_b
    engine_calls: list[tuple] = []
    real_run = proc.write_id3_run

    def spy(plan_arg, **kwargs):
        engine_calls.append((plan_arg, kwargs))
        return real_run(plan_arg, **kwargs)

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_run", spy)
    assert panel.controls.availability()[JobAction.RETRY_FAILED] is True
    panel.retry_failed()
    settle(panel)

    assert len(made) == 1, "a retry reserves nothing"
    assert panel.last_plan is plan, "the same frozen plan"
    assert len(engine_calls) == 1
    retried_plan, kwargs = engine_calls[0]
    assert retried_plan is plan
    assert dict(kwargs["retry_items"]) == {b.book_id: requests[0].item_ids}
    second = panel.last_result
    assert second is not first
    assert second.snapshot is first.snapshot is plan.capture, "same RunSnapshot identity"
    assert second.state is JobState.SUCCEEDED
    assert second.result_for(b.book_id).snapshot is snapshot_b
    assert second.result_for(a.book_id) is first.result_for(a.book_id), "A was not rerun"
    assert second.result_for(c.book_id) is first.result_for(c.book_id), "C was not rerun"
    assert [second.disposition_for(x.book_id) for x in (a, b, c)] == [
        BookDisposition.SUCCEEDED] * 3
    plan_b = plan.book_for(b.book_id)
    assert plan_b.published_dir.is_dir()
    for track in plan_b.tracks:
        assert texts(track.published)["TALB"] == "Frozen Album", "the original shared value"
        assert texts(track.published)["TIT2"] == track.title
    assert {p: sha(p) for p in published_a} == published_a
    assert {p: sha(p) for p in published_c} == published_c
    assert {p: p.stat().st_mtime_ns for p in mtimes} == mtimes, "A and C untouched"
    # Retained staged pieces were reused, not re-made: the published copy of a
    # kept track is the retained staged file, moved, so its mtime survives.
    for track in kept:
        assert track.published.stat().st_mtime_ns == kept_mtimes[track.staged]
    assert not plan.work_root.exists()
    assert panel.controls.availability()[JobAction.RETRY_FAILED] is False
    # The live workspace is what the user made of it, untouched by the retry.
    assert panel.workspace.count == 4
    assert panel.workspace.shared.values["album"] == "Edited Later"
    assert panel.book_status_for(b.book_id) == "Completed"
    assert panel.book_status_for(panel.workspace.books[3].book_id) == "Ready"


def test_combine_retry_redoes_finalisation_from_the_same_book_plan(
        make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch)
    panel.combine_mp3s()
    settle(panel)
    first = panel.last_result
    plan = panel.last_plan
    a, b, c = panel.workspace.books
    assert first.state is JobState.COMPLETED_WITH_FAILURES
    plan_b = plan.book_for(b.book_id)
    assert not plan_b.combined_published.exists()
    junk_tag(tone(root / "B" / "02 Two.mp3", freq=500))
    panel.retry_failed()
    settle(panel)
    second = panel.last_result
    assert second.state is JobState.SUCCEEDED
    assert plan_b.combined_published.is_file()
    assert plan_b.timestamps_published.is_file()
    assert len(plan_b.timestamps_published.read_text(encoding="utf-8").splitlines()) == 3
    assert second.result_for(a.book_id) is first.result_for(a.book_id)
    assert not plan.work_root.exists()


def test_an_item_less_failure_is_not_retryable(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    panel.surface.set_shared_text("artist", "X")
    panel.on_shared_change("artwork", str(bad))
    panel.write_id3_tags()
    settle(panel)
    result = panel.last_result
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert all(result.disposition_for(b.book_id) is BookDisposition.FAILED
               for b in panel.workspace.books)
    assert result.has_retryable is False
    assert result.can_retry_failed is False
    assert panel.controls.availability()[JobAction.RETRY_FAILED] is False
    assert panel.retry_failed() is False
    failures = events_of(panel, JobEventKind.FAILURE)
    assert failures and all(e.item_id is None for e in failures)
    assert statuses(panel) == ["Failed"] * 3


def test_source_hashes_survive_a_run_and_a_retry(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch)
    before = {p: sha(p) for p in root.rglob("*.mp3")}
    panel.write_id3_tags()
    settle(panel)
    assert {p: sha(p) for p in before} == before
    fixed = junk_tag(tone(root / "B" / "02 Two.mp3", freq=500))
    before[fixed] = sha(fixed)
    panel.retry_failed()
    settle(panel)
    assert {p: sha(p) for p in before} == before
    assert [p for p in root.rglob("*") if p.is_file() and p.suffix != ".mp3"] == []


# --------------------------------------------------------------------------- #
# Progress and status projection
# --------------------------------------------------------------------------- #


def test_one_progress_region_carries_book_and_track_context(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    seen: list[str] = []
    real_apply = panel.status.__class__.apply

    def spy(self, view, *, stage=None, item_id=None):
        seen.append(str(self.stage_text))
        result = real_apply(self, view, stage=stage, item_id=item_id)
        seen.append(str(self.stage_text))
        return result

    monkeypatch.setattr(job_ui.JobStatusView, "apply", spy)
    panel.write_id3_tags()
    # Drain one event at a time so every intermediate projection is observed.
    panel.jobs._limit = 1
    while panel.is_running:
        panel._pump.tick()
    assert any(text == "Book 2 of 3 — Track 2 of 3" for text in seen), seen
    assert any(text == "Book 1 of 3 — Track 1 of 2" for text in seen), seen
    progress = events_of(panel, JobEventKind.PROGRESS)
    assert progress[-1].completed == progress[-1].total == 3 + 4 + 2
    assert panel.status.view.completed == panel.status.view.total
    assert len(widgets_of(panel, ttk.Progressbar)) == 1, "one progress bar"


def test_book_statuses_follow_the_run_and_the_dispositions(make_panel, tmp_path, monkeypatch):
    panel = make_panel(thread_factory=RealThreads())
    made, root = three_books(panel, tmp_path, monkeypatch)
    panel.navigator.invoke(panel.navigator.ADD)          # an empty fourth Book
    assert statuses(panel) == ["Ready"] * 4
    release = threading.Event()
    real_stage = proc._stage_clean_copy

    def gated(book, track):
        release.wait(10.0)
        return real_stage(book, track)

    monkeypatch.setattr(mp3_tool.mp3_processing, "_stage_clean_copy", gated)
    panel.navigator.choose(panel.workspace.books[0].book_id)
    panel.write_id3_tags()
    wait_for(panel, lambda: statuses(panel)[0] == "Processing")
    assert statuses(panel) == ["Processing", "Queued", "Queued", "Skipped"]
    assert panel.book_status_text() == "Processing", "the current Book's label"
    release.set()
    wait_for(panel, lambda: not panel.is_running)
    assert statuses(panel) == ["Completed", "Failed", "Completed", "Skipped"]
    a = panel.workspace.books[0]
    panel.navigator.choose(a.book_id)
    assert panel.book_status_text() == "Completed"
    panel.navigator.invoke(panel.navigator.ADD)
    assert panel.book_status_text() == "Ready"


# --------------------------------------------------------------------------- #
# The one log region
# --------------------------------------------------------------------------- #


def test_the_log_is_one_notebook_with_summary_and_detailed_tabs(make_panel):
    panel = make_panel()
    notebooks = widgets_of(panel, ttk.Notebook)
    assert len(notebooks) == 1 and notebooks[0] is panel.log.frame
    tabs = [notebooks[0].tab(tab_id, "text") for tab_id in notebooks[0].tabs()]
    assert tabs == ["Summary", "Detailed"]
    assert len(widgets_of(panel, tk.Text)) == 3, "chapter titles + the two log panes"
    texts_seen = {str(b.cget("text")) for b in widgets_of(panel, ttk.Button)}
    assert "Clear Log" in texts_seen
    assert not any("Copy" in text for text in texts_seen)
    for gone in ("Debug", "Info", "Warn", "Verbose"):
        assert not any(gone in str(w.cget("text")) for w in widgets_of(panel, ttk.Label)
                       if "text" in w.keys()), gone
    assert widgets_of(panel, ttk.Combobox) == [panel.navigator.selector], "no level selector"
    assert widgets_of(panel, ttk.Radiobutton) == []


def test_history_survives_across_runs_with_a_divider_per_run_and_retry(
        make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch)
    import_line = next(line for line in panel.log.summary if "Import Folder" in line)
    panel.write_id3_tags()
    settle(panel)
    summary = list(panel.log.summary)
    assert summary[0] == import_line, "pre-run lines stay"
    dividers = [line for line in summary if mp3_tool.DIVIDER_MARK in line]
    assert len(dividers) == 1 and "Write ID3 Tags" in dividers[0]
    assert summary.index(dividers[0]) > summary.index(import_line)
    ended = [line for line in summary if "with failures" in line.lower()]
    assert ended, summary
    junk_tag(tone(root / "B" / "02 Two.mp3", freq=500))
    panel.retry_failed()
    settle(panel)
    summary = list(panel.log.summary)
    dividers = [line for line in summary if mp3_tool.DIVIDER_MARK in line]
    assert len(dividers) == 2 and "Retry" in dividers[1]
    assert summary.index(dividers[1]) > summary.index(ended[0])
    assert summary.index(import_line) == 0
    panel.combine_mp3s()
    settle(panel)
    summary = list(panel.log.summary)
    dividers = [line for line in summary if mp3_tool.DIVIDER_MARK in line]
    assert len(dividers) == 3 and "Combine" in dividers[2]
    rendered = panel.log.rendered(panel.log.summary_text)
    assert rendered == "\n".join(summary)
    assert import_line in rendered
    detailed = panel.log.rendered(panel.log.details_text)
    assert detailed.count(mp3_tool.DIVIDER_MARK) == 3
    assert "technical_detail" in detailed or "failure" in detailed


def test_clear_log_clears_visible_text_only_and_nothing_repopulates(
        make_panel, tmp_path, monkeypatch, caplog):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch)
    panel.write_id3_tags()
    settle(panel)
    events_before = panel.jobs.stream.events
    result_before = panel.last_result
    assert panel.log.rendered(panel.log.summary_text)
    panel.btn_clear_log.invoke()
    assert panel.log.rendered(panel.log.summary_text) == ""
    assert panel.log.rendered(panel.log.details_text) == ""
    assert panel.log.summary == () and panel.log.details == ()
    assert panel.jobs.stream.events == events_before, "the event history is untouched"
    assert panel.last_result is result_before and panel.last_plan is not None
    assert panel.controls.availability()[JobAction.RETRY_FAILED] is True
    # A re-render of the same run must not bring the cleared lines back.
    panel.jobs.render()
    panel._pump.tick()
    panel.render()
    assert panel.log.rendered(panel.log.summary_text) == ""
    # Later lines still appear, after the cleared point only.
    junk_tag(tone(root / "B" / "02 Two.mp3", freq=500))
    panel.retry_failed()
    settle(panel)
    rendered = panel.log.rendered(panel.log.summary_text)
    assert rendered.startswith(mp3_tool.DIVIDER_MARK) or rendered.split("\n")[0].startswith(
        mp3_tool.DIVIDER_MARK)
    assert "Import Folder" not in rendered
    assert len(panel.jobs.stream.events) > 0


def test_the_log_is_selectable_with_the_keyboard(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    panel.write_id3_tags()
    settle(panel)
    text = panel.log.summary_text
    assert str(text.cget("state")) == "disabled", "read-only, still selectable"
    # A synthetic keystroke is dropped by Tk unless the window really has
    # focus, which a test host cannot promise; the binding is asserted and the
    # virtual event Tk itself maps Ctrl+A to on Windows is fired instead.
    for pane in (text, panel.log.details_text):
        assert pane.bind("<Control-a>"), "Select All is bound on every platform"
    text.focus_set()
    text.update()
    text.event_generate("<<SelectAll>>")
    text.update()
    selected = text.get("sel.first", "sel.last")
    assert selected.rstrip("\n") == panel.log.rendered(text)
    text.event_generate("<<Copy>>")
    text.update()
    try:
        clipboard = text.clipboard_get()
    except tk.TclError:  # pragma: no cover - a host without a clipboard
        clipboard = selected
    assert clipboard.strip() == selected.strip()


def test_detailed_events_reach_the_session_log_through_the_one_bridge(
        make_panel, tmp_path, monkeypatch):
    records: list[tuple[str, str]] = []

    class Recorder:
        def debug(self, fmt, *args):
            records.append(("debug", fmt % args))

        def warning(self, fmt, *args):
            records.append(("warning", fmt % args))

        def error(self, fmt, *args):
            records.append(("error", fmt % args))

        info = debug

    bridge = job_control.LoggerBridge(Recorder())
    panel = make_panel(bridge=bridge)
    made, root = three_books(panel, tmp_path, monkeypatch)
    panel.write_id3_tags()
    settle(panel)
    errors = [body for level, body in records if level == "error"]
    assert any("02 Two.mp3" in body for body in errors)
    assert all(body.startswith(f"[{panel.jobs.run_id}]") for _l, body in records)
    assert panel.jobs.stream.run_id == panel.jobs.run_id
    # The bridge is the one the panel was built with: no second logger, no new file.
    outputs = {p.name for p in tmp_path.rglob("*") if p.is_file()}
    assert not any(name.endswith(".log") or name == "ffmpeg_log.txt" for name in outputs), outputs


def test_no_ffmpeg_log_dependency_and_no_copy_button_in_the_source():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "ffmpeg_log" not in source
    assert "Copy Log" not in source and "copy_log" not in source
    tree = ast.parse(source)
    strings = {node.value for node in ast.walk(tree)
               if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert "Clear Log" in strings
    assert not any(s in strings for s in ("Debug", "Info", "Warn", "Copy"))
    assert "Detailed" in strings
    engine = ENGINE_SOURCE.read_text(encoding="utf-8")
    assert "tkinter" not in engine and "job_ui" not in engine
    assert "JobReporter" not in engine, "the engine never reports; the panel translates"


# --------------------------------------------------------------------------- #
# Thread and teardown safety
# --------------------------------------------------------------------------- #


def test_the_worker_touches_no_widget_and_events_cross_only_the_queue(
        make_panel, tmp_path, monkeypatch):
    panel = make_panel(thread_factory=RealThreads())
    made, root = three_books(panel, tmp_path, monkeypatch)
    calls: list[str] = []

    class TkSpy:
        """The interpreter handle, recording any call made off the main thread."""

        def __init__(self, real) -> None:
            self._real = real

        def call(self, *args):
            if threading.current_thread() is not threading.main_thread():
                calls.append(str(args[:2]))
            return self._real.call(*args)

        def __getattr__(self, name):
            return getattr(self._real, name)

    spy = TkSpy(panel.tk)
    for widget in [panel] + widgets_of(panel, tk.Misc):
        monkeypatch.setattr(widget, "tk", spy)
    panel.write_id3_tags()
    wait_for(panel, lambda: not panel.is_running)
    assert calls == [], f"Tk was reached from the worker: {calls[:3]}"
    assert panel.last_result.state is JobState.COMPLETED_WITH_FAILURES
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    worker = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "_worker")
    attributes = {node.attr for node in ast.walk(worker) if isinstance(node, ast.Attribute)}
    for widget in ("configure", "insert", "delete", "set_summary", "render", "log",
                   "status_label", "track_list", "chapter_text", "after"):
        assert widget not in attributes, widget


def test_closing_mid_run_is_safe_and_cancels_the_worker(make_panel, tmp_path, monkeypatch, tk_root):
    panel = make_panel(thread_factory=RealThreads())
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    started = threading.Event()

    def blocking(plan, *, checkpoint=None, on_event=None, **kwargs):
        started.set()
        while True:
            checkpoint()
            time.sleep(0.005)

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_run", blocking)
    panel.write_id3_tags()
    started.wait(10.0)
    controller = panel.job_controller
    thread = panel._thread_factory.made[-1]
    panel.close()
    panel.close()
    thread.join(10.0)
    assert not thread.is_alive()
    assert controller.state is JobState.CANCELLED
    panel.destroy()
    assert not [entry for entry in tk_root.tk.call("after", "info")]


def test_an_unexpected_worker_fault_settles_the_run_as_failed(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)

    def boom(plan, **kwargs):
        raise RuntimeError("disk vanished")

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_run", boom)
    panel.write_id3_tags()
    settle(panel)
    assert panel.job_controller.state is JobState.FAILED
    assert panel.last_result.state is JobState.FAILED
    assert panel.is_running is False
    assert str(panel.btn_write_id3.cget("state")) == "normal"
    assert any("disk vanished" in line for line in panel.log.details)
    assert not any("disk vanished" in line for line in panel.log.summary), "Summary never shows detail"
    assert not any("Traceback" in line for line in panel.log.summary)


def test_a_cancelled_retry_keeps_the_prior_results(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch)
    panel.write_id3_tags()
    settle(panel)
    first = panel.last_result

    def cancelled(plan, *, checkpoint=None, **kwargs):
        panel.job_controller.request_cancel()
        checkpoint()
        raise AssertionError("checkpoint must raise")

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_run", cancelled)
    panel.retry_failed()
    settle(panel)
    second = panel.last_result
    assert second.state is JobState.CANCELLED
    a, b, c = panel.workspace.books
    assert second.result_for(a.book_id) is first.result_for(a.book_id)
    assert second.disposition_for(b.book_id) is BookDisposition.FAILED
    assert second.can_retry_failed is False, "Plan 3 offers no retry from cancelled"


# --------------------------------------------------------------------------- #
# Boundaries: no second framework, no duplicated tables
# --------------------------------------------------------------------------- #


def test_the_panel_owns_no_second_state_machine_or_retry_framework():
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for forbidden in ("JobController", "JobEventStream", "JobReporter", "RetryRequest",
                      "is_available", "is_locked", "retry_failed_books", "RunResult",
                      "WorkspaceRunResult", "disposition_for", "BookDisposition",
                      "LockGroup", "SummaryDetailsView", "JobAdapter"):
        assert forbidden not in declared, forbidden
    panel = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.ClassDef) and node.name == "MP3ToolUI")
    constructed = {node.func.id for node in ast.walk(panel)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    constructed |= {node.func.attr for node in ast.walk(panel)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "JobController" in constructed and "JobReporter" in constructed
    assert "JobAdapter" in constructed and "WorkspaceRunResult" in constructed
    assert "retry_failed_books" in constructed
    assert "JobEventStream" not in constructed, "the adapter owns the stream"
    assert "Event" not in constructed and "Condition" not in constructed, "no second signal"
    # No per-Book controller: exactly one construction site, outside any loop.
    sites = [node for node in ast.walk(panel)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "JobController"]
    assert len(sites) == 1
    loops = [node for node in ast.walk(panel) if isinstance(node, (ast.For, ast.While))]
    for loop in loops:
        assert not any(node is sites[0] for node in ast.walk(loop)), "one per operation"
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert "CANCELLED" not in literals, "no invented disposition"


def test_the_engine_seams_stay_tk_free_and_report_nothing_themselves():
    tree = ast.parse(ENGINE_SOURCE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
        elif isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
    assert not any(m.startswith("tkinter") or m == "shared.job_ui" for m in modules)
    assert "threading" not in modules and "queue" not in modules
    event = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.ClassDef) and node.name == "ProcessingEvent")
    fields = {node.target.id for node in event.body if isinstance(node, ast.AnnAssign)}
    assert fields >= {"book_id", "occurrence_id", "stage", "message", "detail", "kind"}
    for name in ("write_id3_run", "combine_run"):
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == name)
        kwonly = {arg.arg for arg in function.args.kwonlyargs}
        assert {"checkpoint", "on_event", "on_book", "retry_items"} <= kwonly, name
