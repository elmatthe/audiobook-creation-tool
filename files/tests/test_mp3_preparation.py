"""The MP3 Tool's preparation phase — v0.8.2 Checkpoint 1 (large-job responsiveness).

v0.8.1 reserved the run and planned every track inside the Write ID3 Tags / Combine button's own Tk callback. The plan
checked every destination against every source, resolving each source again each time, so a 2,341-track, seven-Book
workspace froze the window for about 20 minutes with "Ready" still painted. v0.8.2 plans from an input index built once
(``shared.output_paths.InputIndex``; counted in ``test_mp3_plan.py``) and moves reserving and planning to a preparation
worker: the press validates and freezes its inputs on Tk, says "Preparing job…" with Cancel, and the run starts when the
pump adopts the finished plan.

What this module proves, through the real panel:

- the press returns at once and a real Tk event loop keeps its heartbeat while a large job is prepared;
- Cancel during preparation starts nothing, releases only the empty run it reserved, and leaves the workspace and
  the previous run as they were; a plan offered just before Cancel or Close is never adopted;
- repeated presses make exactly one run; a refused or faulted preparation keeps the previous Retry Failed and its
  staging; a stale preparation ending is never acted on;
- what the user typed (Chapter Titles not yet reported by a key release, Shared and per-Book metadata, order and
  Book numbers) is exactly what the plan freezes; the output preferences are the ones in force at the press;
- a processing worker that cannot be started fails the run and frees the panel instead of stopping the pump.

Synthetic placeholders and pinned-FFmpeg tones under ``tmp_path`` only; no real library is read.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import ffmpeg_utils, job_control, output_paths  # noqa: E402
from shared.book_workspace import SharedMetadata, set_shared_metadata  # noqa: E402
from shared.job_control import JobAction, JobState  # noqa: E402

from mp3 import mp3_plan, mp3_tool, mp3_workflow as wf  # noqa: E402

import test_import_coordination as tic  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_import_coordination import RealThreads, RecordingThreads  # noqa: E402
from test_mp3_tool_ui import (  # noqa: E402,F401  (fixtures are collected by name)
    conversion_workers,
    import_folder,
    make_panel,
    reservations_under,
    tk_root,
    tracks,
    wait_until_prepared,
    windows_theme,
)

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(),
                                  reason="ffmpeg/ffprobe not available in this environment")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def no_tags(_path):
    """The tag reader for placeholders: nothing to read, as fast as a stub can be."""
    return wf.SourceTags()


def library(root: Path, tracks_total: int) -> Path:
    """*tracks_total* placeholder MP3s in seven Book folders, numbered across the whole series."""
    per_book = [tracks_total // 7 + (1 if n < tracks_total % 7 else 0) for n in range(7)]
    number = 0
    for index, count in enumerate(per_book, start=1):
        folder = root / f"Book {index}"
        folder.mkdir(parents=True)
        for _ in range(count):
            number += 1
            (folder / f"{number:04d} Chapter {number}.mp3").write_bytes(b"not audio")
    return root


def pump_until(panel, predicate, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        panel._pump.tick()
        time.sleep(0.005)


def import_and_settle(panel, root: Path) -> None:
    panel._choose_folder = lambda: (str(root),)
    panel.import_folder()
    # v0.8.2 Checkpoint 6: the import ends when its files' tags are read (on a worker), not when the scan commits.
    pump_until(panel, lambda: not panel._coordinator.is_active and not panel.is_reading_tags)


def join_all(panel) -> None:
    for thread in panel._thread_factory.made:
        if isinstance(thread, threading.Thread):
            thread.join(20.0)
            assert not thread.is_alive(), thread.name


class PreparationGate:
    """Holds the preparation worker at its first checkpoint inside planning until released."""

    def __init__(self, monkeypatch) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        real = mp3_plan.plan_run

        def gated(*args, checkpoint, **kwargs):
            def held():
                if not self.entered.is_set():
                    self.entered.set()
                    self.release.wait(20.0)
                checkpoint()
            return real(*args, checkpoint=held, **kwargs)

        monkeypatch.setattr(mp3_tool.mp3_plan, "plan_run", gated)


class EngineSpy:
    """Stands in for both engines: records each plan it is handed, then either holds (honouring Cancel at its
    checkpoint, as the real engines do) or fails at once, so the run settles without media."""

    def __init__(self, monkeypatch, *, hold: bool = False) -> None:
        self.plans: list = []
        self.started = threading.Event()
        self.hold = hold

        def engine(plan, *, checkpoint, cancel_check=None, **kwargs):
            self.plans.append(plan)
            self.started.set()
            while self.hold:
                checkpoint()  # raises ConversionCancelled once Cancel was requested
                time.sleep(0.005)
            raise RuntimeError("the test engine processes nothing")

        monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_run", engine)
        monkeypatch.setattr(mp3_tool.mp3_processing, "combine_run", engine)


def run_dirs(tmp_path: Path) -> list[Path]:
    outputs = tmp_path / "Outputs"
    return sorted(outputs.iterdir()) if outputs.exists() else []


# --------------------------------------------------------------------------- #
# Responsiveness through a real Tk event loop
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tracks_total", [300, 2341], ids=["300-tracks", "2341-tracks-seven-books"])
def test_the_press_returns_at_once_and_tk_keeps_its_heartbeat_while_the_job_is_prepared(
        make_panel, tmp_path, monkeypatch, tk_root, tracks_total):
    """v0.8.1 at 2,341 tracks: the press took 1,190 s and so did the largest heartbeat gap (Codex, 2026-11-21).

    The heartbeat is a real ``after`` chain on the real interpreter, and the panel's own pump (also ``after``) adopts
    the plan, so everything here is driven by Tk's event loop, not by hand-ticking. The bounds are generous on
    purpose: the work itself is pinned by counts in ``test_mp3_plan.py``; this proves only where it runs.
    """
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch, hold=True)
    panel = make_panel(thread_factory=RealThreads(), reader=no_tags)
    import_and_settle(panel, library(tmp_path / "Library", tracks_total))
    assert panel.workspace.count == 7

    gaps: list[float] = []
    press: dict[str, object] = {}
    state = {"last": time.perf_counter(), "beating": True}

    def beat():
        now = time.perf_counter()
        gaps.append(now - state["last"])
        state["last"] = now
        if state["beating"]:
            state["after"] = tk_root.after(20, beat)

    def press_start():
        began = time.perf_counter()
        press["accepted"] = panel.write_id3_tags()
        press["seconds"] = time.perf_counter() - began
        press["status"] = panel.status.status_text
        press["cancel"] = panel.controls.availability()[JobAction.CANCEL]
        state["preparing_from"] = len(gaps)

    state["after"] = tk_root.after(20, beat)
    tk_root.after(60, press_start)
    deadline = time.monotonic() + 120.0
    while not engine.started.is_set():
        assert time.monotonic() < deadline, "the prepared plan was never adopted"
        tk_root.update()
        time.sleep(0.002)
    state["beating"] = False
    tk_root.after_cancel(state["after"])  # leave no callback behind on the shared root
    preparing = gaps[state.get("preparing_from", 0):]

    assert press["accepted"] is True
    assert press["seconds"] < 0.5, press
    assert press["status"] == mp3_tool.STATUS_PREPARING and press["cancel"] is True
    assert preparing and max(preparing) < 1.0, max(preparing)
    plan = engine.plans[0]
    assert sum(len(book.tracks) for book in plan.books) == tracks_total
    assert len(made) == 1 and plan.run_directory == made[0].run_directory
    names = [thread.name for thread in panel._thread_factory.made]
    assert [name for name in names if name.startswith("mp3-prepare-")] == ["mp3-prepare-1"]
    assert len(conversion_workers(panel)) == 1, "one processing worker"
    panel.cancel()
    pump_until(panel, lambda: not panel.is_running)
    engine.hold = False
    join_all(panel)
    assert panel.last_result.state is JobState.CANCELLED


# --------------------------------------------------------------------------- #
# Cancel, Close and stale endings
# --------------------------------------------------------------------------- #


def test_cancel_during_preparation_starts_nothing_and_keeps_the_workspace(make_panel, tmp_path, monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    gate = PreparationGate(monkeypatch)
    panel = make_panel(thread_factory=RealThreads(), reader=no_tags)
    import_and_settle(panel, library(tmp_path / "Library", 70))
    panel.surface.set_shared_text("artist", "Shared Narrator")
    panel.book_field_value = None
    panel.set_book_field("album", "Book One Album")
    panel.type_chapter_titles("Prologue\nThe Road")
    before = panel.workspace
    numbers = dict(panel.book_numbers)

    assert panel.write_id3_tags() is True
    assert gate.entered.wait(20.0)
    assert panel.is_running and panel.is_preparing
    assert panel.navigator.locked is True and str(panel.btn_write_id3.cget("state")) == "disabled"
    assert panel.controls.availability()[JobAction.CANCEL] is True
    assert str(panel.controls.buttons[JobAction.PAUSE].cget("state")) == "disabled", "Pause has no meaning yet"
    panel.cancel()
    assert panel.status.status_text == mp3_tool.STATUS_CANCELLING_PREPARATION
    assert panel.controls.availability()[JobAction.CANCEL] is False
    panel.cancel()  # a second press changes nothing
    gate.release.set()
    pump_until(panel, lambda: not panel.is_running)
    join_all(panel)

    assert engine.plans == [], "no media was started"
    assert conversion_workers(panel) == [], "no processing worker was made"
    assert panel.job_controller is None and panel.last_plan is None and panel.last_result is None
    assert len(made) == 1 and not made[0].run_directory.exists(), "the empty run it reserved is released"
    assert panel.workspace is before and panel.book_numbers == numbers, "the workspace is untouched"
    assert panel.workspace.shared.values["artist"] == "Shared Narrator"
    assert panel.workspace.current.configuration["album"] == "Book One Album"
    assert panel.workspace.current.configuration["chapter_titles"] == "Prologue\nThe Road"
    assert panel.status.status_text == mp3_tool.STATUS_PREPARATION_CANCELLED
    assert panel.log.summary[-1].endswith("cancelled before anything was started; the workspace is unchanged.")
    assert panel.navigator.locked is False and str(panel.btn_write_id3.cget("state")) == "normal"
    assert panel.controls.availability()[JobAction.CANCEL] is False


def test_a_plan_offered_just_before_cancel_is_never_adopted(make_panel, tmp_path, monkeypatch):
    """The worker finished and offered its plan; Cancel lands before the pump reads it. Nothing may start."""
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags)  # inline: the whole preparation runs inside the press
    import_folder(panel, library(tmp_path / "Library", 14))
    assert panel.write_id3_tags() is True
    assert panel.is_preparing and len(made) == 1 and made[0].run_directory.exists()
    panel.cancel()
    assert not made[0].run_directory.exists(), "taken back and released at Cancel"
    pump_until(panel, lambda: not panel.is_running)
    assert engine.plans == [] and panel.last_plan is None and panel.job_controller is None
    assert panel.status.status_text == mp3_tool.STATUS_PREPARATION_CANCELLED


def test_closing_during_preparation_starts_nothing_and_releases_the_run(make_panel, tmp_path, monkeypatch, tk_root):
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    gate = PreparationGate(monkeypatch)
    panel = make_panel(thread_factory=RealThreads(), reader=no_tags)
    import_and_settle(panel, library(tmp_path / "Library", 21))
    assert panel.write_id3_tags() is True
    assert gate.entered.wait(20.0)
    panel.close()
    gate.release.set()
    join_all(panel)
    assert engine.plans == [] and len(made) == 1 and not made[0].run_directory.exists()
    panel.destroy()
    assert not [entry for entry in tk_root.tk.call("after", "info")]


def test_closing_after_the_plan_was_offered_releases_it_unadopted(make_panel, tmp_path, monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    assert panel.write_id3_tags() is True
    assert made[0].run_directory.exists()
    panel.close()
    assert engine.plans == [] and not made[0].run_directory.exists()


class _PrepareTwice:
    """Starts every preparation worker twice (a replayed ending); every other worker once, inline."""

    def __init__(self) -> None:
        self.made: list = []

    def __call__(self, target, name):
        thread = tic.InlineThread(target, name)
        if name.startswith("mp3-prepare-"):
            def twice():
                target()
                target()
            thread = tic.InlineThread(twice, name)
        self.made.append(thread)
        return thread


def test_a_stale_preparation_ending_is_never_acted_on(make_panel, tmp_path, monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags, thread_factory=_PrepareTwice())
    import_folder(panel, library(tmp_path / "Library", 14))
    assert panel.write_id3_tags() is True
    assert len(made) == 2, "the replayed body reserved a second run"
    assert not made[1].run_directory.exists(), "a second offer is refused, so its own worker released its run"
    pump_until(panel, lambda: not panel.is_running)
    assert len(engine.plans) == 1 and engine.plans[0].run_directory == made[0].run_directory
    assert not made[1].run_directory.exists(), "the stale plan's empty run was released, never run"
    assert len(conversion_workers(panel)) == 1


# --------------------------------------------------------------------------- #
# One run per press; a refused preparation keeps the previous run
# --------------------------------------------------------------------------- #


@needs_ffmpeg
def test_repeated_presses_while_preparing_make_exactly_one_run(make_panel, tmp_path, monkeypatch):
    from test_mp3_orchestration import three_books

    gate = PreparationGate(monkeypatch)
    panel = make_panel(thread_factory=RealThreads())
    made, _root = three_books(panel, tmp_path, monkeypatch, broken=None)
    assert panel.write_id3_tags() is True
    assert gate.entered.wait(20.0)
    assert panel.write_id3_tags() is False
    assert panel.combine_mp3s() is False
    assert panel.retry_failed() is False
    assert panel.clear_all_imports() is False
    gate.release.set()
    pump_until(panel, lambda: not panel.is_running, timeout=60.0)
    join_all(panel)
    assert len(made) == 1, "one reservation"
    assert [t.name for t in panel._thread_factory.made if t.name.startswith("mp3-prepare-")] == ["mp3-prepare-1"]
    assert len(conversion_workers(panel)) == 1
    assert panel.last_result.state is JobState.SUCCEEDED
    assert panel.last_plan.run_directory == made[0].run_directory


@needs_ffmpeg
@pytest.mark.parametrize("failure", ["refused", "fault"])
def test_a_failed_preparation_keeps_the_previous_runs_retry_and_its_staging(make_panel, tmp_path, monkeypatch,
                                                                          failure):
    from test_mp3_orchestration import settle, three_books

    panel = make_panel()
    made, _root = three_books(panel, tmp_path, monkeypatch)  # Book B's second track is broken
    panel.write_id3_tags()
    settle(panel)
    first_plan, first_result = panel.last_plan, panel.last_result
    assert first_result.state is JobState.COMPLETED_WITH_FAILURES
    kept = first_plan.books[1].tracks[0].staged
    assert kept.is_file() and panel.controls.availability()[JobAction.RETRY_FAILED] is True

    def broken(*args, **kwargs):
        if failure == "refused":
            raise mp3_plan.PlanError("two Books would write the same file")
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(mp3_tool.mp3_plan, "plan_run", broken)
    assert panel.write_id3_tags() is True
    assert panel.controls.availability()[JobAction.RETRY_FAILED] is False, "nothing else runs while preparing"
    settle(panel)
    expected = ("Write ID3 Tags: two Books would write the same file" if failure == "refused"
                else "Write ID3 Tags: the job could not be prepared, and nothing was started.")
    assert make_panel.dialogs[-1] == ("error", expected)
    assert len(made) == 2 and not made[1].run_directory.exists(), "the refused run was released"
    assert panel.last_plan is first_plan and panel.last_result is first_result
    assert kept.is_file(), "the previous run's kept staging survives a failed preparation"
    assert panel.controls.availability()[JobAction.RETRY_FAILED] is True, "Retry Failed is offered again"
    if failure == "fault":
        assert any("RuntimeError: the disk went away" in line for line in panel.log.details)
    assert panel.retry_failed() is True
    settle(panel)
    assert panel.last_plan is first_plan, "the retry re-ran the original frozen plan"


# --------------------------------------------------------------------------- #
# What the user entered is what the plan freezes
# --------------------------------------------------------------------------- #


def test_a_chapter_titles_edit_no_key_release_reported_reaches_the_plan(make_panel, tmp_path, monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    space = set_shared_metadata(panel.workspace, SharedMetadata(
        wf.SHARED_FIELDS, {**panel.workspace.shared.values, "artist": "Shared Narrator",
                           "album_artist": "Shared House"})).workspace
    panel.workspace = space
    panel.render()
    panel.set_book_field("album", "First Album")
    # A mouse paste: the box changes, and no <KeyRelease> reports it.
    panel.chapter_text.delete("1.0", "end")
    panel.chapter_text.insert("1.0", "Pasted One\nPasted Two")
    assert "chapter_titles" not in panel.workspace.current.configuration
    order = [entry.occurrence_id for book in panel.workspace.books for entry in book.files.files]
    numbers = dict(panel.book_numbers)
    assert panel.combine_mp3s() is True
    pump_until(panel, lambda: not panel.is_running)
    plan = engine.plans[0]
    first = plan.books[0]
    assert [track.title for track in first.tracks[:2]] == ["Pasted One", "Pasted Two"]
    assert panel.workspace.current.configuration["chapter_titles"] == "Pasted One\nPasted Two"
    assert first.album == "First Album" and first.artist == "Shared Narrator"
    assert all(book.album_artist == "Shared House" for book in plan.books)
    assert [track.occurrence_id for book in plan.books for track in book.tracks] == order
    assert [book.number for book in plan.books] == [numbers[book.book_id] for book in plan.books]
    assert plan.operation is mp3_plan.MP3Operation.COMBINE


def test_moving_to_another_book_keeps_a_pasted_chapter_titles_edit(make_panel, tmp_path):
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    first = panel.workspace.current.book_id
    panel.chapter_text.delete("1.0", "end")
    panel.chapter_text.insert("1.0", "Kept Title")
    panel.on_next()
    assert panel.workspace.current.book_id != first
    kept = next(book for book in panel.workspace.books if book.book_id == first)
    assert kept.configuration["chapter_titles"] == "Kept Title"


def test_the_run_uses_the_output_preferences_in_force_at_the_press(make_panel, tmp_path, monkeypatch):
    seen: list = []

    def reserve(tool_key, *, effective=None, **kwargs):
        seen.append(effective)
        directory = tmp_path / "Outputs" / f"MP3-Tool-{len(seen)}"
        directory.mkdir(parents=True)
        return output_paths.RunReservation(tool_key=tool_key, base_directory=tmp_path / "Outputs",
                                           tool_directory=tmp_path / "Outputs", run_directory=directory,
                                           run_number=len(seen))

    monkeypatch.setattr(output_paths, "reserve_run_directory", reserve)
    EngineSpy(monkeypatch)

    class Parked(tic.InlineThread):
        def start(self):
            if not self.name.startswith("mp3-prepare-"):
                return super().start()
            self.starts += 1  # the preparation runs later, by the test

    panel = make_panel(reader=no_tags, thread_factory=RecordingThreads(kind=Parked))
    import_folder(panel, library(tmp_path / "Library", 7))
    # Real configurations (v0.8.2 R1): the same snapshot is now also what every Book's run snapshot records.
    at_press, later = make_config(), make_config()
    monkeypatch.setattr(mp3_tool.shared_config, "get_effective", lambda: at_press)
    assert panel.write_id3_tags() is True
    monkeypatch.setattr(mp3_tool.shared_config, "get_effective", lambda: later)  # Preferences saved meanwhile
    preparation = next(t for t in panel._thread_factory.made if t.name.startswith("mp3-prepare-"))
    preparation.target()
    assert len(seen) == 1 and seen[0] is at_press


def test_a_preparation_worker_that_cannot_start_reserves_nothing_and_frees_the_panel(make_panel, tmp_path,
                                                                                     monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)

    class NoPreparationThread(RecordingThreads):
        def __call__(self, target, name):
            if name.startswith("mp3-prepare-"):
                raise RuntimeError("can't start new thread")
            return super().__call__(target, name)

    panel = make_panel(reader=no_tags, thread_factory=NoPreparationThread())
    import_folder(panel, library(tmp_path / "Library", 7))
    assert panel.write_id3_tags() is False
    assert not panel.is_running and made == [] and engine.plans == []
    assert make_panel.dialogs[-1] == ("error", "Write ID3 Tags: the job could not be prepared, and nothing was started.")
    assert panel.status.status_text == mp3_tool.STATUS_PREPARATION_FAILED
    assert str(panel.btn_write_id3.cget("state")) == "normal" and panel.navigator.locked is False


def test_a_processing_worker_that_cannot_start_fails_the_run_and_frees_the_panel(make_panel, tmp_path, monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    EngineSpy(monkeypatch)

    class NoProcessingThread(RecordingThreads):
        def __call__(self, target, name):
            if name.startswith("mp3-") and not name.startswith("mp3-prepare-"):
                raise RuntimeError("can't start new thread")
            return super().__call__(target, name)

    panel = make_panel(reader=no_tags, thread_factory=NoProcessingThread())
    import_folder(panel, library(tmp_path / "Library", 7))
    assert panel.write_id3_tags() is True
    pump_until(panel, lambda: not panel.is_running)
    assert panel.job_controller.state is JobState.FAILED
    assert panel.last_result.state is JobState.FAILED
    assert any("can't start new thread" in line for line in panel.log.details)
    assert str(panel.btn_write_id3.cget("state")) == "normal"
    assert panel._pump.running, "the pump that frees the panel kept going"
    assert made[0].run_directory.is_dir(), "a failed run keeps its folder, as a worker fault always did"
    assert isinstance(panel.job_controller, job_control.JobController)
