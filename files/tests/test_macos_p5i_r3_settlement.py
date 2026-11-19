"""v0.8.x P5-I-R3: a run's settlement -- ``subprocess_utils.containment_problem`` and the unresolved registry.

Real processes under a real owner (no FFmpeg needed: a stand-in shell program named ``ffmpeg`` that ignores SIGTERM).
The owner's signals are refused through its ``_deliver`` seam, the only fault injected:

* a run that left nothing settles clean; one whose contained child cannot be confirmed ended gets a problem naming it,
  within the bound measured from the Cancel click -- never a clean Cancel;
* ``run_supervised`` raises ``ChildNotStopped`` (a failure), never ``ConversionCancelled``, for a child it could not
  confirm stopped; with signals allowed the same Cancel is clean (control);
* the unresolved registry keeps a recorded worker while it runs, drops it once it is gone, and never mistakes a
  process whose start time differs (a reused pid) for it.
macOS only.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from shared import child_ownership
from shared import subprocess_utils as sp
from shared.cancellation import ConversionCancelled
from shared.job_control import JobController

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="POSIX containment is the Mac's")


@pytest.fixture()
def owner(monkeypatch):
    made = child_ownership.Owner(lifeline=False)
    monkeypatch.setattr(sp, "_owner", made)
    yield made
    monkeypatch.undo()
    made.shutdown()


@pytest.fixture()
def stubborn(tmp_path) -> Path:
    """A stand-in ``ffmpeg`` that ignores SIGTERM and runs for a minute (SIGKILL still ends it)."""
    folder = tmp_path / "bin"
    folder.mkdir()
    path = folder / "ffmpeg"
    path.write_text("#!/bin/sh\ntrap '' TERM\nsleep 60 &\nwait\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _running(controller: JobController) -> JobController:
    controller.start()
    return controller


def _until(predicate, seconds: float = 10.0) -> bool:
    stop = time.monotonic() + seconds
    while time.monotonic() < stop:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


# =========================================================================== settle_bound

def test_the_settlement_bound_is_measured_from_the_cancel_click():
    quiet = _running(JobController("r3-bound-quiet", cancel_clock=time.monotonic))
    assert sp.settle_bound(quiet.cancel_check) == 1.0, "a run nobody cancelled gets one second"
    clicked = _running(JobController("r3-bound-now", cancel_clock=time.monotonic))
    clicked.request_cancel()
    assert 3.5 < sp.settle_bound(clicked.cancel_check, 4.0) <= 4.0
    late = _running(JobController("r3-bound-late", cancel_clock=time.monotonic))
    late.request_cancel()
    assert sp.settle_bound(late.cancel_check, 0.0) == 0.2, "past the bound: one short look, never nothing"



def test_the_controller_reads_no_clock_of_its_own():
    """``job_control`` reads no clock (test_plan3_boundaries): the click instant comes from the injected clock only."""
    ticks = iter([41.5, 99.0])
    stamped = _running(JobController("r3-clock", cancel_clock=lambda: next(ticks)))
    stamped.request_cancel()
    stamped.request_cancel()  # only the first Cancel is the click
    assert stamped.cancel_clicked_at == 41.5
    bare = _running(JobController("r3-no-clock"))
    bare.request_cancel()
    assert bare.cancel_clicked_at is None and sp.settle_bound(bare.cancel_check) == 1.0

# =========================================================================== containment_problem

def test_a_run_that_left_nothing_settles_clean(owner, stubborn):
    controller = _running(JobController("r3-clean"))
    with sp.run_context(controller.cancel_check):
        child = sp.popen([str(stubborn)], stdin=subprocess.DEVNULL)
    assert owner.child(child) is not None, "started contained, as the run's"
    assert sp.stop_child(child, 0.2), "SIGTERM ignored, SIGKILL ends it"
    assert sp.containment_problem(controller.cancel_check) is None


def test_a_cancelled_run_whose_child_cannot_be_confirmed_ended_has_a_problem_inside_its_bound(owner, stubborn,
                                                                                            monkeypatch):
    controller = _running(JobController("r3-unconfirmed"))
    with sp.run_context(controller.cancel_check):
        child = sp.popen([str(stubborn)], stdin=subprocess.DEVNULL)
    monkeypatch.setattr(owner, "_deliver", lambda entry, sig: False)  # every signal the owner sends is refused
    controller.request_cancel()
    began = time.monotonic()
    problem = sp.containment_problem(controller.cancel_check, stop_s=1.0)
    took = time.monotonic() - began
    assert problem is not None and f"pid {child.pid}" in problem, problem
    assert took < 1.0 + 0.5, f"settlement took {took:.2f} s past a 1 s bound from the click"
    assert child.poll() is None, "it really is still running: the problem is the truth, not a guess"
    # The owner still has it, and ends it once signals work again.
    monkeypatch.setattr(owner, "_deliver", type(owner)._deliver.__get__(owner))
    assert sp.stop_child(child, 0.2) and child.returncode is not None
    assert sp.containment_problem(controller.cancel_check) is None


def test_a_problem_for_one_run_is_not_another_runs(owner, stubborn, monkeypatch):
    first = _running(JobController("r3-first"))
    other = _running(JobController("r3-other"))
    with sp.run_context(first.cancel_check):
        child = sp.popen([str(stubborn)], stdin=subprocess.DEVNULL)
    monkeypatch.setattr(owner, "_deliver", lambda entry, sig: False)
    assert sp.containment_problem(other.cancel_check) is None
    assert sp.containment_problem(first.cancel_check, stop_s=0.3) is not None
    monkeypatch.setattr(owner, "_deliver", type(owner)._deliver.__get__(owner))
    assert sp.stop_child(child, 0.2)


# =========================================================================== run_supervised

def _supervised_in_thread(controller, argv):
    box: dict = {}

    def body():
        try:
            with sp.cancellable(controller.cancel_check):
                box["value"] = sp.run_supervised(argv, grace_seconds=0.3)
        except BaseException as exc:  # noqa: BLE001 - the outcome is the assertion
            box["error"] = exc

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread, box


def test_run_supervised_never_reports_a_clean_cancel_for_a_child_it_could_not_stop(owner, stubborn, monkeypatch):
    controller = _running(JobController("r3-supervised-refused"))
    thread, box = _supervised_in_thread(controller, [str(stubborn)])
    assert _until(lambda: any(e.state == child_ownership.LIVE for e in owner.outstanding(controller.cancel_check)))
    monkeypatch.setattr(owner, "_deliver", lambda entry, sig: False)
    controller.request_cancel()
    thread.join(15)
    assert not thread.is_alive()
    assert isinstance(box.get("error"), sp.ChildNotStopped), box
    assert not isinstance(box.get("error"), ConversionCancelled)
    assert sp.containment_problem(controller.cancel_check, stop_s=0.3) is not None
    monkeypatch.setattr(owner, "_deliver", type(owner)._deliver.__get__(owner))
    assert _until(lambda: sp.containment_problem(controller.cancel_check, stop_s=0.3) is None, 15), \
        "the owner kept ending it once signals worked"


def test_run_supervised_cancel_with_signals_working_is_clean(owner, stubborn):
    """Control for the test above: the same child and Cancel, nothing refused."""
    controller = _running(JobController("r3-supervised-clean"))
    thread, box = _supervised_in_thread(controller, [str(stubborn)])
    assert _until(lambda: any(e.state == child_ownership.LIVE for e in owner.outstanding(controller.cancel_check)))
    clicked = time.monotonic()
    controller.request_cancel()
    thread.join(15)
    assert isinstance(box.get("error"), ConversionCancelled), box
    assert time.monotonic() - clicked < sp.FFMPEG_STOP_S
    assert sp.containment_problem(controller.cancel_check) is None


# =========================================================================== the unresolved registry

def test_an_unresolved_worker_blocks_every_clean_end_until_it_is_gone(owner):
    worker = subprocess.Popen(["/bin/sleep", "60"])
    try:
        start = child_ownership.process_start_time(worker.pid)
        assert start is not None
        sp.note_unresolved(worker.pid, start, "a voice-engine worker")
        assert worker.pid in sp.unresolved_children()
        controller = _running(JobController("r3-unresolved"))
        problem = sp.containment_problem(controller.cancel_check)
        assert problem is not None and f"pid {worker.pid}" in problem
    finally:
        worker.kill()
        worker.wait(5)
    assert worker.pid not in sp.unresolved_children(), "seen gone: dropped"
    assert sp.containment_problem(_running(JobController("r3-unresolved-after")).cancel_check) is None


def test_a_reused_pid_is_never_taken_for_the_recorded_worker():
    other = subprocess.Popen(["/bin/sleep", "60"])
    try:
        sec, usec = child_ownership.process_start_time(other.pid)
        sp.note_unresolved(other.pid, (sec - 100, usec), "a worker that ended long ago")
        assert other.pid not in sp.unresolved_children(), "a different start time is a different process"
    finally:
        other.kill()
        other.wait(5)


def test_note_unresolved_ignores_no_pid():
    before = set(sp.unresolved_children())
    sp.note_unresolved(0, None, "nothing")
    sp.note_unresolved(-1, None, "nothing")
    assert set(sp.unresolved_children()) == before


# =========================================================================== the orderly end's one deadline

def test_the_orderly_end_is_one_deadline_however_long_the_panels_take(owner, stubborn, monkeypatch):
    """Close with a contained child that ignores SIGTERM and two panels whose workers never finish: every panel join
    draws on the one deadline started at the close request, and the containment's own end still finishes inside it
    (the child confirmed ended). Before P5-I-R3: 5 s per panel join, then the media stop, then a fresh 5 s shutdown."""
    monkeypatch.setattr(sp, "_closing_deadline", None)
    controller = _running(JobController("r3-orderly", cancel_clock=time.monotonic))
    with sp.run_context(controller.cancel_check):
        child = sp.popen([str(stubborn)], stdin=subprocess.DEVNULL)
    never = threading.Event()
    panels = [threading.Thread(target=never.wait, daemon=True) for _ in range(2)]
    for panel in panels:
        panel.start()
    began = time.monotonic()
    sp.begin_closing()  # the window's close request
    for panel in panels:  # each panel's close(): a bounded join, as the TTS, Converter and Cover panels do
        panel.join(sp.close_budget(5.0))
    joined = time.monotonic() - began
    assert sp.stop_media_children() == [], "while closing, the shutdown below retires them in its one batch"
    sp.shutdown_containment()
    took = time.monotonic() - began
    never.set()
    assert joined <= sp.ORDERLY_END_S - sp.CONTAINMENT_RESERVE_S + 0.2, f"the panel joins took {joined:.2f} s"
    assert took <= sp.ORDERLY_END_S + 0.3, f"the orderly end took {took:.2f} s"
    assert child.returncode is not None, "the child was confirmed ended inside the deadline"


def test_close_budget_is_the_timeout_unchanged_when_not_closing(monkeypatch):
    monkeypatch.setattr(sp, "_closing_deadline", None)
    assert sp.close_budget(5.0) == 5.0


def test_a_closing_deadline_belongs_to_the_owner_that_began_closing(owner, monkeypatch):
    """A test (or any code) that began closing one owner never shortens another owner's panel joins later."""
    monkeypatch.setattr(sp, "_closing_deadline", None)
    sp.begin_closing()
    assert sp.close_budget(5.0) <= sp.ORDERLY_END_S - sp.CONTAINMENT_RESERVE_S
    other = child_ownership.Owner(lifeline=False)
    try:
        monkeypatch.setattr(sp, "_owner", other)
        assert sp.close_budget(5.0) == 5.0, "a stale deadline of another owner is ignored"
        monkeypatch.setattr(sp, "_owner", None)
        assert sp.close_budget(5.0) == 5.0
    finally:
        other.shutdown()
