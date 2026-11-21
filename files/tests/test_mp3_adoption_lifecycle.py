"""MP3 Tool — the job-area swap when a prepared run is adopted (v0.8.2 Checkpoint 1, review R1 second pass).

The second independent review (``files/dev-work/v0.8.2-large-job-investigation/CP1-R1-INDEPENDENT-REVIEW.md``) found
that the first R1 correction of the adoption failure was incomplete at two seams inside the same swap:

* a one-time Tk error **destroying the previous adapter's frame** left the panel reporting idle while the navigator
  stayed locked and both Start buttons stayed disabled, because the previous adapter had already been closed and was
  then treated as still being the job area;
* a one-time error in **the new adapter's first render** left an extra frame and an extra pump drain behind.

Everything here goes through the real panel, the real Tk widgets, the real ``JobAdapter`` and pump, and the two real
Start buttons, with one-shot (and, where it matters, persistent) faults injected at the exact calls the review named.
Each case asserts what a person at the window would see -- the buttons, the navigator, the job area -- next to who
owns the run, the reservation and the previous run's staging, and ends by starting another operation through the real
button. Synthetic placeholders under ``tmp_path`` only.
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

tk = pytest.importorskip("tkinter")

from shared import job_ui, output_paths  # noqa: E402
from shared.job_control import JobAction, JobState  # noqa: E402

from mp3 import mp3_plan, mp3_tool  # noqa: E402

from test_import_coordination import RealThreads  # noqa: E402
from test_mp3_cp1_remediation import PASTED, SlowRelease, native_paste, snapshot_bytes  # noqa: E402
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

OPERATIONS = {
    "write": ("btn_write_id3", "write_id3_tags", "Write ID3 Tags", mp3_plan.MP3Operation.WRITE_ID3),
    "combine": ("btn_combine", "combine_mp3s", "Combine MP3s → One MP3", mp3_plan.MP3Operation.COMBINE),
}
OPS = list(OPERATIONS)


def press(panel, operation: str) -> None:
    """Click the real Start button. A disabled button does nothing, exactly as for a person."""
    getattr(panel, OPERATIONS[operation][0]).invoke()


def start_buttons(panel) -> tuple[str, str]:
    return str(panel.btn_write_id3.cget("state")), str(panel.btn_combine.cget("state"))


def prepare_threads(panel) -> list:
    return [made for made in panel._thread_factory.made if made.name.startswith("mp3-prepare-")]


def assert_usable(panel) -> None:
    """What a person needs to carry on: nothing running, navigation and both Start buttons enabled, pump alive."""
    assert not panel.is_running and not panel.is_preparing and not panel._busy
    assert panel.navigator.locked is False
    assert start_buttons(panel) == ("normal", "normal")
    assert panel._pump.running
    assert not panel.jobs.closed, "the installed job area is a live one"
    assert panel.jobs.frame.winfo_exists() and panel.jobs.frame.winfo_manager() == "grid"
    assert panel.controls is panel.jobs.controls and panel.lock_group is panel.jobs.locks


def a_further_start_works(panel, engine, made, operation: str) -> None:
    """The acceptance that matters after any failure: the next press, through the real button, runs."""
    plans, reservations = len(engine.plans), len(made)
    press(panel, operation)
    assert panel.is_preparing, "the press was accepted"
    pump_until(panel, lambda: not panel.is_running)
    assert len(engine.plans) == plans + 1 and len(made) == reservations + 1
    assert engine.plans[-1].operation is OPERATIONS[operation][3]
    assert engine.plans[-1].run_directory == made[-1].run_directory
    assert_usable(panel)


def offered(make_panel, tmp_path, monkeypatch, operation: str, *, paste: bool = False):
    """A panel whose preparation has finished and offered its plan, which the pump has not adopted yet."""
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    panel = make_panel(reader=no_tags)  # inline workers: the preparation runs inside the press
    import_folder(panel, library(tmp_path / "Library", 14))
    if paste:
        native_paste(panel, PASTED)
        panel.surface._row("artist").shared_entry.insert(0, "Kept Narrator")
    press(panel, operation)
    assert panel.is_preparing and panel._preparing._offered is not None
    assert start_buttons(panel) == ("disabled", "disabled") and panel.navigator.locked is True
    return panel, engine, made


def fail_frame_destroy(panel, monkeypatch, *, times: int) -> dict:
    """Raise from the previous adapter's ``frame.destroy()`` -- the review's first seam."""
    frame = panel.jobs.frame
    real = frame.destroy
    state = {"left": times, "raised": 0}

    def destroy():
        if state["left"]:
            state["left"] -= 1
            state["raised"] += 1
            raise tk.TclError("fixture: the retired frame could not be destroyed")
        return real()

    monkeypatch.setattr(frame, "destroy", destroy)
    return state


def fail_inside_close(panel, monkeypatch) -> dict:
    """Raise once from inside the previous adapter's ``close()``: its control bar's own ``close`` fails, after the
    adapter has marked itself closed and dropped its pump drain (the realistic place for a Tk error there)."""
    bar = panel.jobs.controls
    real = job_ui.JobControlBar.close
    state = {"raised": 0}

    def close(self):
        if self is bar and not state["raised"]:
            state["raised"] += 1
            raise tk.TclError("fixture: the retired control bar could not be closed")
        return real(self)

    monkeypatch.setattr(job_ui.JobControlBar, "close", close)
    return state


def let_tk_turn(tk_root, seconds: float = 0.2) -> None:
    """Run the real event loop for a moment, so every timer that is due fires (and a dead widget's is dropped)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.005)


def progress_timers(tk_root) -> list[str]:
    """Tk timers of an indeterminate progress bar that are still being re-armed after the event loop has turned:
    one per bar still spinning. (A destroyed bar's last timer is dropped the first time it fires.)"""
    let_tk_turn(tk_root)
    return [str(tk_root.tk.call("after", "info", entry)) for entry in tk_root.tk.call("after", "info")
            if "progressbar" in str(tk_root.tk.call("after", "info", entry))]


def fail_adapter_method(monkeypatch, name: str, *, when, error: str) -> dict:
    """Raise once from ``JobAdapter.<name>`` on the call *when(adapter, calls so far for it)* selects."""
    real = getattr(job_ui.JobAdapter, name)
    state = {"raised": 0, "calls": {}}

    def method(self, *args, **kwargs):
        count = state["calls"].get(id(self), 0) + 1
        state["calls"][id(self)] = count
        if not state["raised"] and when(self, count):
            state["raised"] += 1
            raise tk.TclError(error)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(job_ui.JobAdapter, name, method)
    return state


# --------------------------------------------------------------------------- #
# 1. The review's blocker: an error retiring the previous adapter
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("operation", OPS)
@pytest.mark.parametrize("seam", ["frame-destroy-once", "frame-destroy-always", "adapter-close-once",
                                  "adapter-close-entry-once"])
def test_an_error_retiring_the_previous_job_area_never_strands_the_panel(make_panel, tmp_path, monkeypatch, tk_root,
                                                                         operation, seam):
    """Second review, blocker: on the first R1 candidate a one-time ``TclError`` from the previous frame's
    ``destroy()`` left ``is_running`` False with the navigator locked and both Start buttons disabled for good.

    Retiring the previous adapter happens after the new one owns the job area, so it is cleanup: the accepted run
    starts, the retired adapter is closed and its frame is out of the layout, and the problem is reported once.
    """
    panel, engine, made = offered(make_panel, tmp_path, monkeypatch, operation)
    previous = panel.jobs
    drains = panel._pump.drain_count
    if seam == "adapter-close-once":
        state = fail_inside_close(panel, monkeypatch)
    elif seam == "adapter-close-entry-once":
        state = fail_adapter_method(monkeypatch, "close", when=lambda adapter, count: adapter is previous,
                                    error="fixture: the retired adapter could not be closed")
    else:
        state = fail_frame_destroy(panel, monkeypatch, times=1 if seam == "frame-destroy-once" else 10 ** 6)

    pump_until(panel, lambda: not panel.is_running)

    assert state["raised"] >= 1, "the injected fault was actually reached"
    # Ownership transferred: the new job area is the panel's, and the accepted run really ran.
    assert panel.jobs is not previous
    assert previous.closed or seam == "adapter-close-entry-once", "retired, unless its close() never began"
    assert previous.drain not in panel._pump._drains, "the retired adapter drains nothing, whatever close() did"
    assert len(engine.plans) == 1 and engine.plans[0].run_directory == made[0].run_directory
    assert len(conversion_workers(panel)) == 1, "exactly one processing worker"
    assert panel.last_plan is engine.plans[0] and panel.job_controller.state is JobState.FAILED  # the spy's fault
    assert made[0].run_directory.is_dir(), "the adopted run keeps its folder"
    # The retired frame is gone or out of the layout; the pump has one job drain, as before.
    assert not previous.frame.winfo_exists() or previous.frame.winfo_manager() == ""
    assert panel._pump.drain_count == drains
    assert sum("fixture:" in line for line in panel.log.details) == 1, "reported once, in the Detailed log"
    assert make_panel.dialogs == [], "cleanup of the old job area is not the user's problem"
    assert progress_timers(tk_root) == [], "a job area that could not be destroyed is not left animating"
    assert_usable(panel)
    a_further_start_works(panel, engine, made, operation)
    a_further_start_works(panel, engine, made, "combine" if operation == "write" else "write")


@pytest.mark.parametrize("operation", OPS)
def test_a_job_area_that_can_be_neither_closed_nor_destroyed_is_hidden_stopped_and_reported(
        make_panel, tmp_path, monkeypatch, tk_root, operation):
    """The worst retirement: ``close()`` fails before it reaches anything and the frame can never be destroyed.

    The new run still owns the job area and runs; the dead frame is out of the layout, drains nothing, and its
    "Preparing job…" bar is stopped so it does not re-arm a Tk timer for as long as the panel lives. Each failed
    step is reported once; nothing is retried.
    """
    panel, engine, made = offered(make_panel, tmp_path, monkeypatch, operation)
    previous = panel.jobs
    drains = panel._pump.drain_count
    closing = fail_adapter_method(monkeypatch, "close", when=lambda adapter, count: adapter is previous,
                                  error="fixture: the retired adapter could not be closed")
    destroying = fail_frame_destroy(panel, monkeypatch, times=10 ** 6)

    pump_until(panel, lambda: not panel.is_running)

    assert closing["raised"] == 1 and destroying["raised"] == 1, "each step was tried once, not looped"
    assert panel.jobs is not previous and len(engine.plans) == 1 and len(conversion_workers(panel)) == 1
    assert previous.drain not in panel._pump._drains and panel._pump.drain_count == drains
    assert previous.frame.winfo_exists() and previous.frame.winfo_manager() == "", "alive, but out of the layout"
    assert sum("fixture:" in line for line in panel.log.details) == 2
    assert progress_timers(tk_root) == [], "the dead job area is not left animating"
    assert_usable(panel)
    a_further_start_works(panel, engine, made, operation)


# --------------------------------------------------------------------------- #
# 2. Before ownership transfers: nothing is left behind and nothing is lost
# --------------------------------------------------------------------------- #


def _new_adapter_first_render(panel, monkeypatch):
    previous = panel.jobs
    return fail_adapter_method(monkeypatch, "render", when=lambda adapter, count: adapter is not previous,
                               error="fixture: the new job area's first render failed")


def _new_adapter_grid(panel, monkeypatch):
    previous = panel.jobs
    real = mp3_tool.MP3ToolUI._arrange_status
    state = {"raised": 0}

    def arrange(self, *args, **kwargs):
        if not state["raised"] and (args or kwargs) and (args or list(kwargs.values()))[0] is not previous:
            state["raised"] += 1
            raise tk.TclError("fixture: the new job area could not be laid out")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(mp3_tool.MP3ToolUI, "_arrange_status", arrange)
    return state


def _install_entry(panel, monkeypatch):
    real = panel._install_jobs
    state = {"raised": 0}

    def install(run_id, item_ids):
        if not state["raised"]:
            state["raised"] += 1
            raise tk.TclError("fixture: adapter installation failed")
        return real(run_id, item_ids)

    monkeypatch.setattr(panel, "_install_jobs", install)
    return state


BEFORE_OWNERSHIP = {"install-entry": _install_entry, "new-adapter-first-render": _new_adapter_first_render,
                    "new-adapter-layout": _new_adapter_grid}


@pytest.mark.parametrize("operation", OPS)
@pytest.mark.parametrize("seam", list(BEFORE_OWNERSHIP))
def test_an_error_before_ownership_transfers_leaves_nothing_behind_and_loses_nothing(make_panel, tmp_path,
                                                                                     monkeypatch, operation, seam):
    """Second review, second case: an error in the new adapter's first render left one extra frame and one extra
    pump drain. Before the swap the previous job area must stay the live one, and what the user entered must stay."""
    panel, engine, made = offered(make_panel, tmp_path, monkeypatch, operation, paste=True)
    previous, workspace = panel.jobs, panel.workspace
    drains, children = panel._pump.drain_count, len(panel.actions.winfo_children())
    state = BEFORE_OWNERSHIP[seam](panel, monkeypatch)

    pump_until(panel, lambda: not panel.is_running)

    assert state["raised"] == 1
    assert panel.jobs is previous and not previous.closed, "the previous job area is still the live one"
    assert panel._pump.drain_count == drains, "no extra pump drain"
    assert len(panel.actions.winfo_children()) == children, "no extra frame"
    assert engine.plans == [] and conversion_workers(panel) == [], "nothing started"
    assert panel.job_controller is None and panel.last_plan is None and panel.last_result is None
    assert len(made) == 1 and not made[0].run_directory.exists(), "the unused empty run was released"
    label = OPERATIONS[operation][2]
    assert make_panel.dialogs[-1] == ("error", f"{label}: the job could not be started, and nothing was started.")
    assert panel.status.status_text == mp3_tool.STATUS_PREPARATION_FAILED
    assert any("fixture:" in line for line in panel.log.details)
    # Nothing the user entered went with the failed adoption.
    assert panel.workspace is workspace
    assert panel.workspace.current.configuration["chapter_titles"] == PASTED
    assert panel.chapter_titles_text() == PASTED
    assert panel.workspace.shared.values["artist"] == "Kept Narrator"
    assert_usable(panel)

    a_further_start_works(panel, engine, made, operation)
    first = engine.plans[-1].books[0]
    assert [track.title for track in first.tracks] == PASTED.split("\n") and first.artist == "Kept Narrator"


# --------------------------------------------------------------------------- #
# 3. After ownership transfers: the accepted run settles; it is never "running" with no worker
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("operation", OPS)
def test_an_error_after_the_swap_settles_the_accepted_run_as_failed(make_panel, tmp_path, monkeypatch, operation):
    panel, engine, made = offered(make_panel, tmp_path, monkeypatch, operation)
    previous = panel.jobs
    drains = panel._pump.drain_count
    # The new adapter's second render is the one after the swap (its first is its constructor's).
    state = fail_adapter_method(monkeypatch, "render", when=lambda adapter, count: adapter is not previous
                                and count == 2, error="fixture: the installed job area could not be rendered")

    pump_until(panel, lambda: not panel.is_running)

    assert state["raised"] == 1
    assert panel.jobs is not previous and previous.closed and not previous.frame.winfo_exists()
    assert panel._pump.drain_count == drains
    assert engine.plans == [] and conversion_workers(panel) == [], "no processing was started"
    assert panel.job_controller.state is JobState.FAILED and panel.last_result.state is JobState.FAILED
    assert panel.last_plan.run_directory == made[0].run_directory and made[0].run_directory.is_dir()
    assert any("fixture:" in line for line in panel.log.details)
    assert_usable(panel)
    a_further_start_works(panel, engine, made, operation)


# --------------------------------------------------------------------------- #
# 4. The previous run's Retry Failed and kept staging
# --------------------------------------------------------------------------- #


@needs_ffmpeg
@pytest.mark.parametrize("operation", OPS)
@pytest.mark.parametrize("seam", list(BEFORE_OWNERSHIP))
def test_a_failed_swap_before_ownership_keeps_the_previous_retry_and_staging(make_panel, tmp_path, monkeypatch,
                                                                              operation, seam):
    from test_mp3_orchestration import settle, three_books

    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch)  # Book B's second track is broken
    sources = snapshot_bytes(root)
    panel.write_id3_tags()
    settle(panel)
    first_plan, first_result, jobs = panel.last_plan, panel.last_result, panel.jobs
    assert first_result.state is JobState.COMPLETED_WITH_FAILURES
    kept = first_plan.books[1].tracks[0].staged
    assert kept.is_file() and panel.controls.availability()[JobAction.RETRY_FAILED] is True

    press(panel, operation)
    assert panel.is_preparing
    BEFORE_OWNERSHIP[seam](panel, monkeypatch)
    settle(panel)

    assert panel.jobs is jobs and not jobs.closed
    assert panel.last_plan is first_plan and panel.last_result is first_result
    assert not panel._attempt.abandoned, "the previous run is still the one Retry Failed reaches"
    assert len(made) == 2 and not made[1].run_directory.exists()
    assert kept.is_file(), "the previous run's kept staging was not discarded"
    assert panel.controls.availability()[JobAction.RETRY_FAILED] is True
    assert snapshot_bytes(root) == sources, "no source was touched"
    assert_usable(panel)

    assert panel.retry_failed() is True
    settle(panel)
    assert panel.last_plan is first_plan, "the retry re-ran the original frozen plan"
    assert_usable(panel)


@needs_ffmpeg
@pytest.mark.parametrize("operation", OPS)
def test_an_error_retiring_a_retryable_runs_job_area_still_hands_its_staging_to_the_new_run(
        make_panel, tmp_path, monkeypatch, operation):
    """After ownership transferred the new run legitimately replaces the old one: its kept staging goes with the new
    worker (off Tk), exactly as in an undisturbed adoption, and the old Retry Failed is not offered for the new run."""
    from test_mp3_orchestration import settle, three_books

    panel = make_panel()
    made, _root = three_books(panel, tmp_path, monkeypatch)
    panel.write_id3_tags()
    settle(panel)
    first_plan = panel.last_plan
    kept = first_plan.books[1].tracks[0].staged
    assert kept.is_file()

    press(panel, operation)
    state = fail_frame_destroy(panel, monkeypatch, times=1)
    settle(panel)

    assert state["raised"] == 1 and panel.last_plan is not first_plan
    assert panel.last_plan.run_directory == made[1].run_directory
    assert not kept.exists(), "the superseded run's kept staging was removed by the new run's worker"
    assert panel.last_result is not None and panel.last_result.state is JobState.COMPLETED_WITH_FAILURES
    assert_usable(panel)


@needs_ffmpeg
@pytest.mark.parametrize("operation", OPS)
def test_a_run_that_fails_after_the_swap_hands_the_old_staging_to_a_release_worker(make_panel, tmp_path,
                                                                                   monkeypatch, operation):
    """Ownership transferred, then the accepted run could not start: it settles as failed, and the replaced run's
    kept staging -- which nothing can retry any more -- is removed by a release worker, not on the Tk thread."""
    from test_mp3_orchestration import settle, three_books

    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch)
    sources = snapshot_bytes(root)
    panel.write_id3_tags()
    settle(panel)
    first_plan, previous = panel.last_plan, panel.jobs
    kept = first_plan.books[1].tracks[0].staged
    assert kept.is_file()

    press(panel, operation)
    removers: list[str] = []
    real = mp3_plan.release_staging

    def release_staging(plan, **kwargs):
        if plan is first_plan:
            removers.append(next((made_thread.name for made_thread in reversed(panel._thread_factory.made)), ""))
        return real(plan, **kwargs)

    monkeypatch.setattr(mp3_tool.mp3_plan, "release_staging", release_staging)
    state = fail_adapter_method(monkeypatch, "render", when=lambda adapter, count: adapter is not previous
                                and count == 2, error="fixture: the installed job area could not be rendered")
    settle(panel)

    assert state["raised"] == 1 and panel.jobs is not previous
    assert panel.last_plan is not first_plan and panel.last_result.state is JobState.FAILED
    assert len(conversion_workers(panel)) == 1, "only the first run ever had a processing worker"
    assert len(removers) == 1 and removers[0].startswith("mp3-release-"), removers
    assert not kept.exists(), "the replaced run's kept staging is gone"
    assert snapshot_bytes(root) == sources
    assert_usable(panel)


# --------------------------------------------------------------------------- #
# 5. Genuine preparation: refusal, Cancel, Close -- through both buttons
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("operation", OPS)
def test_presses_are_refused_while_a_preparation_is_genuinely_active(make_panel, tmp_path, monkeypatch, operation):
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    gate = PreparationGate(monkeypatch)
    panel = make_panel(thread_factory=RealThreads(), reader=no_tags)
    import_and_settle(panel, library(tmp_path / "Library", 14))
    press(panel, operation)
    assert gate.entered.wait(20.0) and panel.is_preparing
    assert start_buttons(panel) == ("disabled", "disabled") and panel.navigator.locked is True
    for other in OPS:
        press(panel, other)  # a disabled button
        assert getattr(panel, OPERATIONS[other][1])() is False  # and the entry point behind it
    assert panel.retry_failed() is False and panel.clear_all_imports() is False
    assert len(prepare_threads(panel)) == 1 and len(made) == 1
    gate.release.set()
    pump_until(panel, lambda: not panel.is_running)
    join_all(panel)
    assert len(engine.plans) == 1 and engine.plans[0].operation is OPERATIONS[operation][3]
    assert len(conversion_workers(panel)) == 1 and len(made) == 1
    assert_usable(panel)


@pytest.mark.parametrize("operation", OPS)
@pytest.mark.parametrize("moment", ["while-preparing", "after-offer"])
def test_cancel_before_adoption_starts_nothing_and_the_next_start_works(make_panel, tmp_path, monkeypatch,
                                                                        operation, moment):
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    gate = PreparationGate(monkeypatch)
    panel = make_panel(thread_factory=RealThreads(), reader=no_tags)
    import_and_settle(panel, library(tmp_path / "Library", 14))
    native_paste(panel, PASTED)
    before = None
    press(panel, operation)
    assert gate.entered.wait(20.0)
    before = panel.workspace
    preparation = panel._preparing
    if moment == "after-offer":
        gate.release.set()
        deadline = time.monotonic() + 20.0
        while not preparation._handed_over:  # no pump tick: offered, not adopted
            assert time.monotonic() < deadline
            time.sleep(0.005)
    panel.controls.buttons[JobAction.CANCEL].invoke()  # the real Cancel button
    assert panel.status.status_text == mp3_tool.STATUS_CANCELLING_PREPARATION
    gate.release.set()
    pump_until(panel, lambda: not panel.is_running)
    join_all(panel)

    assert engine.plans == [] and conversion_workers(panel) == []
    assert len(made) == 1 and not made[0].run_directory.exists(), "only the empty run of that press, released"
    assert panel.status.status_text == mp3_tool.STATUS_PREPARATION_CANCELLED
    assert panel.workspace is before and panel.workspace.current.configuration["chapter_titles"] == PASTED
    assert panel.job_controller is None and panel.last_plan is None
    assert_usable(panel)
    a_further_start_works(panel, engine, made, operation)
    join_all(panel)


@pytest.mark.parametrize("operation", OPS)
@pytest.mark.parametrize("moment", ["while-preparing", "during-cleanup"])
def test_closing_the_window_before_adoption_starts_nothing_and_leaves_no_run(make_panel, tmp_path, monkeypatch,
                                                                             tk_root, operation, moment):
    made = reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    slow = SlowRelease(monkeypatch, delay=0.3)
    gate = PreparationGate(monkeypatch)
    panel = make_panel(thread_factory=RealThreads(), reader=no_tags)
    root = library(tmp_path / "Library", 14)
    import_and_settle(panel, root)
    sources = snapshot_bytes(root)
    press(panel, operation)
    assert gate.entered.wait(20.0)
    preparation = panel._preparing
    if moment == "during-cleanup":
        gate.release.set()
        deadline = time.monotonic() + 20.0
        while not preparation._handed_over:
            assert time.monotonic() < deadline
            time.sleep(0.005)
        panel.cancel()  # the release worker is now inside the slow storage call
        assert slow.calls == 1 or not slow.done.is_set()
    began = time.perf_counter()
    panel.close()
    assert time.perf_counter() - began < 0.2, "Close did not wait on the worker or the storage"
    gate.release.set()
    join_all(panel)
    assert slow.done.wait(10.0)
    assert slow.calls == 1, "the empty run is released exactly once, by exactly one owner"
    assert engine.plans == [] and conversion_workers(panel) == []
    assert not made[0].run_directory.exists()
    assert snapshot_bytes(root) == sources
    panel.destroy()
    let_tk_turn(tk_root)  # earlier panels' destroyed progress bars drop their last timer when it fires
    assert not [entry for entry in tk_root.tk.call("after", "info")], "no Tk callback outlives the panel"


# --------------------------------------------------------------------------- #
# 6. The preparation worker never touches Tk
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("operation", OPS)
def test_the_preparation_worker_makes_no_tk_call(make_panel, tmp_path, monkeypatch, operation):
    """Profiled on the real preparation thread: no Python frame from ``tkinter`` and no C call into ``_tkinter``."""
    reservations_under(tmp_path, monkeypatch)
    engine = EngineSpy(monkeypatch)
    hits: list[str] = []
    profiled: list[str] = []

    def profile(frame, event, arg):
        if event == "call":
            filename = frame.f_code.co_filename.replace("\\", "/")
            if "/tkinter/" in filename:
                hits.append(f"{filename}:{frame.f_code.co_name}")
        elif event == "c_call":
            owner = getattr(arg, "__self__", None)
            module = getattr(arg, "__module__", None) or type(owner).__module__
            if module == "_tkinter" or type(owner).__module__ == "_tkinter":
                hits.append(f"c:{getattr(arg, '__name__', arg)}")

    class Profiled(RealThreads):
        def __call__(self, target, name):
            if not name.startswith("mp3-prepare-"):
                return super().__call__(target, name)

            def body():
                profiled.append(name)
                sys.setprofile(profile)
                try:
                    target()
                finally:
                    sys.setprofile(None)

            return super().__call__(body, name)

    panel = make_panel(thread_factory=Profiled(), reader=no_tags)
    import_and_settle(panel, library(tmp_path / "Library", 70))
    press(panel, operation)
    pump_until(panel, lambda: not panel.is_running)
    join_all(panel)
    assert profiled == ["mp3-prepare-1"] and len(engine.plans) == 1
    assert hits == [], hits[:5]
    assert threading.current_thread() is threading.main_thread()


# --------------------------------------------------------------------------- #
# 7. The same swap at Clear All Imports
# --------------------------------------------------------------------------- #


def test_clear_all_imports_changes_nothing_when_the_fresh_job_area_cannot_be_built(make_panel, tmp_path, monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    native_paste(panel, PASTED)
    previous = panel.jobs
    drains, children = panel._pump.drain_count, len(panel.actions.winfo_children())
    state = _new_adapter_first_render(panel, monkeypatch)

    assert panel.clear_all_imports() is False
    assert state["raised"] == 1
    assert panel.workspace.count == 7 and panel.workspace.current.configuration["chapter_titles"] == PASTED
    assert panel.jobs is previous and not previous.closed
    assert panel._pump.drain_count == drains and len(panel.actions.winfo_children()) == children
    assert make_panel.dialogs[-1] == ("error", "Clear All Imports: the tool could not be reset; nothing was cleared.")
    assert_usable(panel)

    assert panel.clear_all_imports() is True, "the next attempt works"
    assert panel.workspace.count == 1 and panel.workspace.current.files.is_empty
    assert_usable(panel)


def test_clear_all_imports_survives_an_error_retiring_the_previous_job_area(make_panel, tmp_path, monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    previous = panel.jobs
    drains = panel._pump.drain_count
    state = fail_frame_destroy(panel, monkeypatch, times=1)
    assert panel.clear_all_imports() is True
    assert state["raised"] == 1 and panel.jobs is not previous and previous.closed
    assert panel._pump.drain_count == drains
    assert panel.workspace.count == 1
    assert_usable(panel)


def test_clear_all_imports_goes_on_when_only_the_fresh_job_areas_last_repaint_failed(make_panel, tmp_path,
                                                                                     monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    panel = make_panel(reader=no_tags)
    import_folder(panel, library(tmp_path / "Library", 14))
    previous = panel.jobs
    state = fail_adapter_method(monkeypatch, "render", when=lambda adapter, count: adapter is not previous
                                and count == 2, error="fixture: the installed job area could not be rendered")
    assert panel.clear_all_imports() is True
    assert state["raised"] == 1 and panel.jobs is not previous and previous.closed
    assert panel.workspace.count == 1 and panel.status.status_text == mp3_tool.STATUS_READY
    assert_usable(panel)
