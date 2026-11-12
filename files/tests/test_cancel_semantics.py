"""Cancel stops active work promptly, everywhere, and nothing unfinished is published (v0.7.2 Phase 1).

The owner's revised contract (plan §3.1 / §11.1): Cancel latches at once and stops dispatch, synthesis, memory waits,
assembly and encoding for every active file; it never starts a disk fallback, a retry or another Edge request; a file
whose publication already won stays; a file whose cancellation won leaves nothing under its final name. Pause is
unchanged: active files finish, nothing new starts, and a paused queue is cancellable immediately. The old deliberate
"finish a narration for up to 30 s idle / 600 s after Cancel" allowance is gone, and these tests hold the door shut.

Independent review of 112d8a0 (P1-R01, P1-R02) added the contracts of two sections below: Cancel and a commit are ordered on
one lock, each knowing the outcome, with that lock never held across the rename; and a cancelled request, whatever it does
with the cancellation, costs a bounded time and leaves nothing running.

Barriers, never sleeps, decide the order of events wherever two threads race.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import contextvars
import gc
import logging
import os
import random
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from shared.cancellation import ConversionCancelled
from shared.job_control import JobContractError, JobController, JobState
from tts import edge_requests, ffmpeg_watch, publication
from tts import worker_limits as wl

GB = 1024 ** 3
MB = 1024 ** 2

#: A bound on how long a test waits for something that must happen, never a delay: it only runs out when the code is wrong.
WAIT = 15


def _python(code: str) -> list[str]:
    return [sys.executable, "-I", "-c", code]


def Machine(available_gb, total_gb=32):
    reading = wl.MemoryInfo(int(available_gb * GB), int(total_gb * GB), None, None, None)
    return lambda: reading


# --------------------------------------------------------------------------- the primitives


def test_waiting_unless_cancelled_returns_as_soon_as_cancel_is_latched():
    cancelled = threading.Event()
    threading.Timer(0.1, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        edge_requests.wait_unless_cancelled(30, cancelled.is_set, step=0.02)
    assert time.monotonic() - started < 2


def test_waiting_unless_cancelled_waits_the_whole_time_when_nobody_cancels():
    started = time.monotonic()
    edge_requests.wait_unless_cancelled(0.2, lambda: False, step=0.05)
    assert 0.18 <= time.monotonic() - started < 2


def test_an_awaited_request_is_abandoned_as_soon_as_cancel_is_latched():
    """An in-flight Edge request (a coroutine) ends with the Cancel, not with the service."""
    cancelled = threading.Event()
    abandoned = {"value": False}

    async def long_request():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            abandoned["value"] = True
            raise

    threading.Timer(0.1, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        asyncio.run(edge_requests.await_unless_cancelled(long_request(), cancelled.is_set, poll=0.02))
    assert time.monotonic() - started < 2 and abandoned["value"] is True


def test_an_awaited_request_that_finishes_returns_its_result():
    async def quick():
        return 42

    assert asyncio.run(edge_requests.await_unless_cancelled(quick(), lambda: False, poll=0.02)) == 42


# --------------------------------------------------------------------------- ffmpeg_watch: Cancel always kills


def test_the_finish_after_cancel_allowance_no_longer_exists():
    for name in ("CANCEL_STALL_SECONDS", "CANCEL_FINISH_SECONDS", "abort_on_cancel"):
        assert not hasattr(ffmpeg_watch, name), name
    assert not hasattr(wl, "CANCEL_FINISH_WAIT_SECONDS")


def test_a_cancelled_child_is_killed_within_one_look_even_while_it_progresses():
    """The exact scenario the old policy let run to completion: steady progress, Cancel asserted from the start."""
    code = "import sys,time;\nfor _ in range(40):\n  sys.stdout.buffer.write(b'x'*(1<<20));sys.stdout.buffer.flush();time.sleep(0.1)"
    with ffmpeg_watch.controlled(lambda: True):
        child = ffmpeg_watch.Supervised(_python(code), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        child.communicate()
    assert time.monotonic() - started < 3
    assert child.process.poll() is not None and child._item not in ffmpeg_watch._watched


def test_a_cancelled_child_that_has_stalled_is_killed_within_one_look_not_at_a_deadline():
    with ffmpeg_watch.controlled(lambda: True):
        child = ffmpeg_watch.Supervised(_python("import time;time.sleep(60)"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        child.communicate()
    assert time.monotonic() - started < 3


def test_waking_the_watchdog_ends_a_cancelled_child_before_its_next_look(monkeypatch):
    """The panel's Cancel wakes the watchdog, so the kill does not wait for the next poll."""
    monkeypatch.setattr(ffmpeg_watch, "WATCH_SECONDS", 5.0)
    cancelled = threading.Event()
    with ffmpeg_watch.controlled(cancelled.is_set):
        child = ffmpeg_watch.Supervised(_python("import time;time.sleep(60)"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
    time.sleep(0.3)  # past the watchdog's first look at this child, so it is asleep for WATCH_SECONDS
    started = time.monotonic()
    cancelled.set()
    ffmpeg_watch.wake()
    with pytest.raises(ConversionCancelled):
        child.communicate()
    assert time.monotonic() - started < 2.5, "it waited for the next look instead of being woken"


def test_controlled_no_longer_takes_a_finish_flag():
    with pytest.raises(TypeError):
        with ffmpeg_watch.controlled(lambda: False, abort_on_cancel=True):  # noqa: the old keyword
            pass


# --------------------------------------------------------------------------- the gate and assemble: no fallback, no retry, no wait after Cancel


@pytest.fixture
def quick_gate(monkeypatch):
    gate = wl.AssemblyGate(Machine(16), poll_seconds=0.01, wait_seconds=1)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    return gate


def test_a_cancel_latched_before_assembly_runs_neither_route(quick_gate):
    calls = []
    with pytest.raises(ConversionCancelled):
        wl.assemble(48_000 * 3600, lambda: calls.append("memory"), lambda: calls.append("disk"), cancel_check=lambda: True)
    assert calls == [] and quick_gate._in_use == 0


def test_a_cancel_during_the_in_memory_route_starts_no_disk_fallback(quick_gate):
    cancelled = threading.Event()
    calls, notes = [], []

    def in_memory():
        calls.append("memory")
        cancelled.set()           # the person presses Cancel while the join runs...
        raise MemoryError()       # ...and memory runs out: the old code fell back to disk here

    with pytest.raises(ConversionCancelled):
        wl.assemble(48_000 * 3600, in_memory, lambda: calls.append("disk"), cancel_check=cancelled.is_set, note=notes.append)
    assert calls == ["memory"] and quick_gate._in_use == 0
    assert not any("on disk" in note for note in notes), f"a fall back was announced that must not happen: {notes}"


def test_a_cancel_after_a_failed_disk_attempt_makes_no_second_attempt(quick_gate, monkeypatch):
    monkeypatch.setattr(wl, "DISK_RETRY_PAUSE_SECONDS", 30)
    cancelled = threading.Event()
    calls = []

    def on_disk():
        calls.append("disk")
        cancelled.set()
        raise MemoryError()

    gate = wl.AssemblyGate(Machine(0.1), poll_seconds=0.01, wait_seconds=1)  # too little for memory: straight to disk
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        wl.assemble(48_000 * 3600, lambda: calls.append("memory"), on_disk, cancel_check=cancelled.is_set)
    assert calls == ["disk"] and time.monotonic() - started < 5 and gate._in_use == 0


def test_a_finished_narration_waiting_for_memory_is_cancelled_within_the_poll_and_goes_nowhere():
    """Yesterday a finished narration was sent to disk by a Cancel; today it stops like everything else."""
    gate = wl.AssemblyGate(Machine(4, 4), poll_seconds=0.01)
    holding, done, cancelled = threading.Event(), threading.Event(), threading.Event()
    outcome = []

    def holder():
        with gate.reserve(GB):
            holding.set()
            done.wait(10)

    def finished_narration():
        try:
            with gate.reserve(3 * GB, cancel_check=cancelled.is_set) as in_memory:
                outcome.append(in_memory)
        except ConversionCancelled:
            outcome.append("cancelled")

    first = threading.Thread(target=holder)
    first.start()
    holding.wait(5)
    second = threading.Thread(target=finished_narration)
    second.start()
    deadline = time.monotonic() + 5
    while not gate._queue and time.monotonic() < deadline:
        time.sleep(0.005)
    assert gate._queue, "it never reached the gate"
    started = time.monotonic()
    cancelled.set()
    second.join(5)
    assert outcome == ["cancelled"] and time.monotonic() - started < 1
    done.set()
    first.join(5)
    assert gate._in_use == 0 and not gate._queue


def test_waking_the_gate_ends_a_cancelled_wait_before_its_next_poll():
    gate = wl.AssemblyGate(Machine(4, 4), poll_seconds=10)
    holding, done, cancelled = threading.Event(), threading.Event(), threading.Event()
    outcome = []

    def holder():
        with gate.reserve(GB):
            holding.set()
            done.wait(30)

    def waiter():
        try:
            with gate.reserve(3 * GB, cancel_check=cancelled.is_set):
                outcome.append("entered")
        except ConversionCancelled:
            outcome.append("cancelled")

    first = threading.Thread(target=holder)
    first.start()
    holding.wait(5)
    second = threading.Thread(target=waiter)
    second.start()
    deadline = time.monotonic() + 5
    while not gate._queue and time.monotonic() < deadline:
        time.sleep(0.005)
    time.sleep(0.2)  # into the 10 s poll
    started = time.monotonic()
    cancelled.set()
    gate.wake()
    second.join(5)
    assert outcome == ["cancelled"] and time.monotonic() - started < 2
    done.set()
    first.join(5)
    assert gate._in_use == 0


def test_the_gate_no_longer_knows_a_finishing_narration(quick_gate):
    with pytest.raises(TypeError):
        with quick_gate.reserve(GB, finishing_check=lambda: True):
            pass
    with pytest.raises(TypeError):
        wl.assemble(1, lambda: None, lambda: None, finishing_check=lambda: True)


def test_waiting_for_room_without_a_gate_stops_when_cancelled(monkeypatch):
    monkeypatch.setattr(wl, "DISK_RETRY_PAUSE_SECONDS", 30)
    cancelled = threading.Event()
    threading.Timer(0.1, cancelled.set).start()
    started = time.monotonic()
    wl.AssemblyPlace(None, True, 0).wait_for_room(cancelled.is_set)
    assert time.monotonic() - started < 2


# --------------------------------------------------------------------------- publication: the commit boundary


def _finished(tmp_path: Path) -> Path:
    finished = tmp_path / "finished.bin"
    finished.write_bytes(b"MP3" * 1000)
    return finished


def test_a_cancel_before_the_commit_publishes_nothing_and_leaves_no_staging(tmp_path):
    destination = tmp_path / "out" / "book.mp3"
    with pytest.raises(ConversionCancelled):
        publication.publish_file(_finished(tmp_path), destination, cancel_check=lambda: True)
    assert not destination.exists()
    assert [p.name for p in destination.parent.iterdir()] == []


def test_a_cancel_that_lands_during_the_final_flush_is_still_seen_before_the_commit(tmp_path, monkeypatch):
    """Between publish()'s first look and the rename sits the fsync of the staged file; a Cancel latched there must be
    seen immediately before the one operation that commits the name. A bare predicate, so this is also the compatibility
    path: the ordering proofs against a real latch are in the next section."""
    destination = tmp_path / "out" / "book.mp3"
    cancelled = threading.Event()
    real_flush = publication.Stage._flush_staged

    def flush(self):
        real_flush(self)
        cancelled.set()  # pressed while the staged file is being flushed, after the first look

    monkeypatch.setattr(publication.Stage, "_flush_staged", flush)
    with pytest.raises(ConversionCancelled):
        publication.publish_file(_finished(tmp_path), destination, cancel_check=cancelled.is_set)
    assert cancelled.is_set() and not destination.exists()
    assert [p.name for p in destination.parent.iterdir()] == []


def test_a_cancel_during_the_copy_into_staging_publishes_nothing(tmp_path, monkeypatch):
    destination = tmp_path / "out" / "book.mp3"
    cancelled = threading.Event()
    real = publication._copy_chunk

    def copy(reader, writer):
        cancelled.set()
        return real(reader, writer)

    monkeypatch.setattr(publication, "_copy_chunk", copy)
    with pytest.raises(ConversionCancelled):
        publication.publish_file(_finished(tmp_path), destination, cancel_check=cancelled.is_set)
    assert not destination.exists() and [p.name for p in destination.parent.iterdir()] == []


def test_an_existing_destination_is_never_touched_by_a_cancelled_publication(tmp_path):
    destination = tmp_path / "out" / "book.mp3"
    destination.parent.mkdir()
    destination.write_bytes(b"earlier")
    with pytest.raises(ConversionCancelled):
        publication.publish_file(_finished(tmp_path), destination, overwrite=True, cancel_check=lambda: True)
    assert destination.read_bytes() == b"earlier"


def test_publication_without_a_cancel_check_behaves_as_before(tmp_path):
    destination = tmp_path / "out" / "book.mp3"
    assert publication.publish_file(_finished(tmp_path), destination) == destination
    assert destination.read_bytes() == b"MP3" * 1000


# --------------------------------------------------------------------------- publication: Cancel and the commit are ordered on one lock (P1-R01)


def _running_controller(run_id: str = "run") -> JobController:
    controller = JobController(run_id)
    controller.start()
    return controller


#: Both publishing operations, and what each must do to what was at the destination.
BOTH_COMMITS = [
    pytest.param(False, None, "_publish_no_clobber", id="no-clobber"),
    pytest.param(True, b"earlier output", "_publish_replacing", id="overwrite"),
]


class _Publishing(threading.Thread):
    """``publish_file`` on its own thread, its result or exception kept for the test to judge."""

    def __init__(self, finished, destination, cancel_check, **options):
        super().__init__(daemon=True)
        self.arguments = (finished, destination)
        self.options = {"cancel_check": cancel_check, **options}
        self.outcome: object = "never finished"

    def run(self) -> None:
        try:
            self.outcome = publication.publish_file(*self.arguments, **self.options)
        except BaseException as exc:  # noqa: BLE001 - recorded, then judged
            self.outcome = exc


class _ParkedCommit:
    """Stands inside the one operation that gives a file its name until released, so events decide who is where."""

    def __init__(self, monkeypatch, seam: str = "_publish_no_clobber", only: str | None = None):
        self.reached, self.release = threading.Event(), threading.Event()
        self.names: list[str] = []
        real = getattr(publication, seam)

        def commit(staged, final):
            self.names.append(Path(final).name)
            if only is None or only in Path(final).name:
                self.reached.set()
                assert self.release.wait(WAIT), "the commit was never released"
            return real(staged, final)

        monkeypatch.setattr(publication, seam, commit)


def _in_flight(controller: JobController) -> int:
    """``commits_in_flight`` read from inside a commit. On another thread and bounded: were the latch's lock held across the
    commit, this must fail the test, not deadlock it on that non-reentrant lock."""
    ended, value, _seconds = _bounded(lambda: controller.commits_in_flight, 3)
    assert ended, "the latch's lock is held across the commit: Cancel would freeze the GUI thread"
    return value


def _destination(tmp_path: Path, earlier: bytes | None) -> Path:
    destination = tmp_path / "out" / "book.mp3"
    destination.parent.mkdir(exist_ok=True)
    if earlier is not None:
        destination.write_bytes(earlier)
    return destination


@pytest.mark.parametrize("overwrite, earlier, seam", BOTH_COMMITS)
def test_a_cancel_that_takes_the_latch_first_denies_the_commit(tmp_path, monkeypatch, overwrite, earlier, seam):
    """First ordering. The file is staged and flushed and the worker has not yet asked; Cancel latches. Nothing is published,
    whatever was at the destination is untouched, the staging file is gone, the source is still there."""
    destination = _destination(tmp_path, earlier)
    controller = _running_controller()
    at_the_boundary, latched = threading.Event(), threading.Event()
    real_flush = publication.Stage._flush_staged

    def flush(stage):
        real_flush(stage)
        at_the_boundary.set()  # all that is left is to ask for authorization
        assert latched.wait(WAIT), "the Cancel never latched"

    renamed: list[Path] = []
    monkeypatch.setattr(publication.Stage, "_flush_staged", flush)
    monkeypatch.setattr(publication, seam, lambda staged, final: renamed.append(final))
    finished = _finished(tmp_path)
    worker = _Publishing(finished, destination, controller.cancel_check, overwrite=overwrite)
    worker.start()
    assert at_the_boundary.wait(WAIT)
    controller.request_cancel()
    assert controller.commits_in_flight == 0, "nothing has been authorized, and now nothing can be"
    latched.set()
    worker.join(WAIT)
    assert isinstance(worker.outcome, ConversionCancelled), worker.outcome
    assert renamed == [], "denied: the operation that names the file never ran"
    assert controller.commits_in_flight == 0
    assert [p.name for p in destination.parent.iterdir()] == ([] if earlier is None else [destination.name]), "no staging leak"
    assert earlier is None or destination.read_bytes() == earlier, "a previously committed output is untouched"
    assert finished.read_bytes() == b"MP3" * 1000, "the source is never moved or consumed"


@pytest.mark.parametrize("overwrite, earlier, seam", BOTH_COMMITS)
def test_a_commit_authorized_first_finishes_whole_and_the_cancel_is_told_it_lost(tmp_path, monkeypatch, overwrite, earlier, seam):
    """Second ordering, and the regression test for P1-R01. The publication has won and is parked inside the rename; Cancel
    is pressed. Cancel must return at once (the lock it needs is not held across the rename), and its answer must already
    name the commit it cannot stop, *before* the file appears. The old check-then-rename recorded nothing, so Cancel answered
    "nothing can still land" and then a file landed. The published file is whole and stays."""
    destination = _destination(tmp_path, earlier)
    controller = _running_controller()
    parked = _ParkedCommit(monkeypatch, seam)
    finished = _finished(tmp_path)
    worker = _Publishing(finished, destination, controller.cancel_check, overwrite=overwrite)
    worker.start()
    try:
        assert parked.reached.wait(WAIT), worker.outcome
        answer: dict[str, int] = {}

        def press_cancel() -> None:
            controller.request_cancel()
            answer["may_still_land"] = controller.commits_in_flight

        pressing = threading.Thread(target=press_cancel, daemon=True)
        pressing.start()
        pressing.join(WAIT)
        assert not pressing.is_alive(), "Cancel was held up behind a rename in progress: the GUI thread would freeze"
        assert controller.cancel_check() is True
        if earlier is None:
            assert not destination.exists(), "the rename has not happened yet: this is the window under test"
        else:
            assert destination.read_bytes() == earlier, "the rename has not happened yet: this is the window under test"
        assert answer["may_still_land"] == 1, (
            "a file is about to appear after Cancel returned and Cancel's answer does not name it: the commit was never "
            "ordered against the latch")
    finally:
        parked.release.set()
    worker.join(WAIT)
    assert worker.outcome == destination, worker.outcome
    assert destination.read_bytes() == b"MP3" * 1000, "whole, and from this attempt"
    assert [p.name for p in destination.parent.iterdir()] == [destination.name], "no staging leak"
    assert controller.commits_in_flight == 0, "the commit is over, so Cancel can no longer be told one may land"
    assert finished.read_bytes() == b"MP3" * 1000, "the source is never moved or consumed"


def test_every_publication_after_the_latch_is_denied_while_the_winner_finishes(tmp_path, monkeypatch):
    """Eight files, one parked inside its rename when Cancel latches: that one lands and only that one, and the file already
    published before the Cancel is untouched. The set of published files is exactly what the ordering says it is."""
    out = tmp_path / "out"
    out.mkdir()
    controller = _running_controller()
    finished = _finished(tmp_path)
    parked = _ParkedCommit(monkeypatch, only="winner")
    earlier = out / "earlier.mp3"
    assert publication.publish_file(finished, earlier, cancel_check=controller.cancel_check) == earlier
    winner = _Publishing(finished, out / "winner.mp3", controller.cancel_check)
    winner.start()
    try:
        assert parked.reached.wait(WAIT)
        controller.request_cancel()
        assert controller.commits_in_flight == 1
        losers = [_Publishing(finished, out / f"loser-{n}.mp3", controller.cancel_check) for n in range(7)]
        for loser in losers:
            loser.start()
        for loser in losers:
            loser.join(WAIT)
            assert isinstance(loser.outcome, ConversionCancelled), loser.outcome
    finally:
        parked.release.set()
    winner.join(WAIT)
    assert winner.outcome == out / "winner.mp3"
    assert sorted(p.name for p in out.iterdir()) == ["earlier.mp3", "winner.mp3"], "nothing else, and no staging"
    assert earlier.read_bytes() == b"MP3" * 1000 and (out / "winner.mp3").read_bytes() == b"MP3" * 1000
    assert parked.names == ["earlier.mp3", "winner.mp3"], "a loser never reached the rename"


def test_cancel_and_authorization_are_decided_on_one_lock():
    """The latch is mid-way through, holding the lock. A publication asking now waits for it and is denied: there is no
    instant at which it could read the old answer, and no second lock for the two to disagree on."""

    class SlowLatch(JobController):
        __slots__ = ("inside", "finish")

        def __init__(self, run_id):
            super().__init__(run_id)
            self.inside, self.finish = threading.Event(), threading.Event()

        def _set_locked(self, proposed):
            if proposed is JobState.CANCEL_REQUESTED:
                self.inside.set()
                assert self.finish.wait(WAIT)
            super()._set_locked(proposed)

    controller = SlowLatch("run")
    controller.start()
    pressing = threading.Thread(target=controller.request_cancel, daemon=True)
    pressing.start()
    assert controller.inside.wait(WAIT)
    answered: list[bool] = []
    asking = threading.Thread(target=lambda: answered.append(controller.authorize_commit()), daemon=True)
    asking.start()
    asking.join(0.1)
    assert asking.is_alive() and answered == [], "it answered while the latch held the lock"
    controller.finish.set()
    asking.join(WAIT)
    pressing.join(WAIT)
    assert answered == [False] and controller.commits_in_flight == 0


def test_a_retry_after_a_locked_destination_asks_again_and_a_cancel_in_the_back_off_wins(tmp_path, monkeypatch):
    """An attempt the OS refused published nothing, so its authorization is spent: Cancel during the back-off stops the retry.
    The wait for a scanner to let go of a file cannot carry a cancelled file over the line."""
    destination = _destination(tmp_path, None)
    controller = _running_controller()
    attempts: list[int] = []

    def locked(staged, final):
        attempts.append(_in_flight(controller))
        raise PermissionError("held by a scanner")

    monkeypatch.setattr(publication, "_publish_no_clobber", locked)
    pressed: list[float] = []

    def sleep(delay):
        pressed.append(delay)
        controller.request_cancel()

    with pytest.raises(ConversionCancelled):
        with publication.Stage(destination, sleep=sleep) as stage:
            stage.receive(_finished(tmp_path), controller.cancel_check)
            stage.publish(controller.cancel_check)
    assert attempts == [1], "one attempt, authorized; none after the Cancel"
    assert len(pressed) == 1 and controller.commits_in_flight == 0
    assert not destination.exists() and list(destination.parent.iterdir()) == []


def test_a_retry_with_no_cancel_is_authorized_each_time_and_publishes(tmp_path, monkeypatch):
    destination = _destination(tmp_path, None)
    controller = _running_controller()
    real = publication._publish_no_clobber
    in_flight: list[int] = []

    def locked_once(staged, final):
        in_flight.append(_in_flight(controller))
        if len(in_flight) == 1:
            raise PermissionError("held by a scanner")
        return real(staged, final)

    monkeypatch.setattr(publication, "_publish_no_clobber", locked_once)
    with publication.Stage(destination, sleep=lambda _delay: None) as stage:
        stage.receive(_finished(tmp_path), controller.cancel_check)
        assert stage.publish(controller.cancel_check) == destination
    assert in_flight == [1, 1], "each attempt holds its own authorization and gives it back"
    assert controller.commits_in_flight == 0 and destination.read_bytes() == b"MP3" * 1000


def test_an_authorized_commit_that_finds_the_name_taken_gives_it_back_and_clobbers_nothing(tmp_path, monkeypatch):
    """No-clobber is still the operation's own guarantee: winning authorization does not win the name."""
    destination = _destination(tmp_path, None)
    controller = _running_controller()
    real = publication._publish_no_clobber

    def another_program_gets_there_first(staged, final):
        Path(final).write_bytes(b"another program's file")
        return real(staged, final)

    monkeypatch.setattr(publication, "_publish_no_clobber", another_program_gets_there_first)
    with pytest.raises(publication.DestinationExists):
        publication.publish_file(_finished(tmp_path), destination, cancel_check=controller.cancel_check)
    assert destination.read_bytes() == b"another program's file"
    assert controller.commits_in_flight == 0
    assert [p.name for p in destination.parent.iterdir()] == [destination.name]


def test_cancel_and_a_commit_racing_for_real_always_agree(tmp_path):
    """Forty unscripted races from a shared start. Which side wins is the scheduler's business and is not asserted. What holds
    every round: published whole or nothing at all, no staging file, and no file that Cancel's answer said could not land."""
    finished = _finished(tmp_path)
    for round_ in range(40):
        out = tmp_path / f"round-{round_}"
        out.mkdir()
        destination = out / "book.mp3"
        controller = _running_controller()
        start = threading.Barrier(2)
        answer: dict[str, object] = {}

        class Racing(_Publishing):
            def run(self):
                start.wait(WAIT)
                super().run()

        def press() -> None:
            start.wait(WAIT)
            controller.request_cancel()
            answer["may_still_land"] = controller.commits_in_flight
            answer["already_there"] = destination.exists()

        publishing = Racing(finished, destination, controller.cancel_check)
        pressing = threading.Thread(target=press, daemon=True)
        publishing.start()
        pressing.start()
        publishing.join(WAIT)
        pressing.join(WAIT)
        if isinstance(publishing.outcome, ConversionCancelled):
            assert list(out.iterdir()) == [], f"round {round_}: denied, yet something is there"
        else:
            assert publishing.outcome == destination, f"round {round_}: {publishing.outcome}"
            assert destination.read_bytes() == b"MP3" * 1000 and [p.name for p in out.iterdir()] == ["book.mp3"]
        if answer["may_still_land"] == 0 and not answer["already_there"]:
            assert not destination.exists(), f"round {round_}: Cancel said nothing could still land, and a file landed"
        assert controller.commits_in_flight == 0


def test_the_controller_counts_commits_in_flight_and_refuses_after_the_latch():
    controller = _running_controller()
    assert controller.commits_in_flight == 0
    assert controller.authorize_commit() is True and controller.authorize_commit() is True
    assert controller.commits_in_flight == 2
    controller.commit_finished()
    assert controller.commits_in_flight == 1
    revision = controller.revision
    controller.request_cancel()
    assert controller.revision == revision + 1, "the latch is still one observable change"
    assert controller.authorize_commit() is False, "the Cancel has it now"
    assert controller.commits_in_flight == 1, "a refused authorization is not recorded"
    controller.commit_finished()
    with pytest.raises(JobContractError):
        controller.commit_finished()


def test_a_cancel_recorded_before_the_run_starts_denies_a_commit():
    controller = JobController("run")
    controller.request_cancel()
    assert controller.authorize_commit() is False


def test_a_run_is_not_reported_cancelled_while_a_commit_may_still_land():
    """CANCELLED means it has actually stopped. A file appearing after that would make the terminal state a lie."""
    controller = _running_controller()
    assert controller.authorize_commit() is True
    controller.request_cancel()
    with pytest.raises(ConversionCancelled):
        controller.checkpoint()
    with pytest.raises(JobContractError):
        controller.finish_cancelled()
    assert controller.state is JobState.CANCEL_REQUESTED, "refused, and nothing moved"
    controller.commit_finished()
    assert controller.finish_cancelled().state is JobState.CANCELLED


def test_authorized_commit_needs_the_latch_owner_only_when_there_is_one():
    """The compatibility path. ``None`` and a bare predicate keep working and get what they can: a bare predicate has no
    latch this code could order itself against, so it gets a last look. Every Cancel button passes a controller's check."""
    with publication.authorized_commit(None):
        pass
    with publication.authorized_commit(threading.Event().is_set):
        pass
    with pytest.raises(ConversionCancelled):
        with publication.authorized_commit(lambda: True):
            pytest.fail("a bare predicate that says cancelled must not reach the commit")
    controller = _running_controller()
    with publication.authorized_commit(controller.cancel_check):
        assert _in_flight(controller) == 1
    assert controller.commits_in_flight == 0
    with pytest.raises(RuntimeError):
        with publication.authorized_commit(controller.cancel_check):
            raise RuntimeError("the commit failed")
    assert controller.commits_in_flight == 0, "a failed commit gives its authorization back"


def test_the_panel_hands_every_route_a_check_the_latch_can_be_found_from():
    """The whole boundary hangs on the routes receiving the controller's own bound check, unwrapped: a lambda around it would
    silently fall back to a last look. Pinned at the one place the run takes it, and at every publication call."""
    import source_probe

    taken = [node for node in ast.walk(source_probe.module("tts/epub2tts_gui.py"))
             if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "self.cancel_check"]
    assert [ast.unparse(node.value) for node in taken] == ["self.controller.cancel_check"]
    routes = {"convert_with_kokoro", "convert_with_chatterbox", "convert_with_qwen3", "convert_with_edge_engine",
              "batch_convert.convert_single_pdf"}
    dispatched = {ast.unparse(node.func): [ast.unparse(argument) for argument in node.args]
                  for node in ast.walk(source_probe.module("tts/epub2tts_gui.py"))
                  if isinstance(node, ast.Call) and ast.unparse(node.func) in routes}
    assert set(dispatched) == routes
    for route, arguments in dispatched.items():
        assert "self.cancel_check" in arguments, f"{route} is not handed the run's own check: {arguments}"
    published = 0
    local_routes = 0
    for relative in ("tts/epub2tts_gui.py", "tts/batch_convert.py", "tts/epub2tts_edge/runner.py"):
        for node in ast.walk(source_probe.module(relative)):
            if not isinstance(node, ast.Call):
                continue
            callee = ast.unparse(node.func)
            if callee == "publication.publish_file":
                published += 1
                passed = {keyword.arg: ast.unparse(keyword.value) for keyword in node.keywords}
                assert passed.get("cancel_check") == "cancel_check", f"{relative}:{node.lineno}"
            elif callee == "stage.publish":
                published += 1
                assert [ast.unparse(argument) for argument in node.args] == ["cancel_check"], f"{relative}:{node.lineno}"
            elif callee == "_convert_with_local_engine":
                local_routes += 1
                assert ast.unparse(node.args[-1]) == "cancel_check", f"{relative}:{node.lineno}: publishes without the boundary"
    assert (published, local_routes) == (4, 3), "a publication call was added or lost: decide what it does on Cancel"


# --------------------------------------------------------------------------- the Edge request loop


def test_the_direct_request_loop_makes_no_further_attempt_after_cancel(monkeypatch, tmp_path):
    from tts.epub2tts_edge import epub2tts_edge as engine

    cancelled = threading.Event()
    attempts = []

    class FailingCommunicate:
        def __init__(self, sentence, speaker):
            attempts.append(sentence)

        async def save(self, filename):
            Path(filename).write_bytes(b"partial")
            cancelled.set()  # Cancel lands while the first attempt is failing
            raise ConnectionResetError("transient")

    monkeypatch.setattr(engine.edge_tts, "Communicate", FailingCommunicate)
    monkeypatch.setattr(engine, "RETRY_BASE_DELAY_SEC", 30.0)
    target = tmp_path / "clip.mp3"
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        engine.run_edgespeak("Hello there.", "v", str(target), cancel_check=cancelled.is_set)
    assert len(attempts) == 1 and time.monotonic() - started < 3
    assert not target.exists(), "the failed attempt's partial audio is not left behind"


def test_a_cancel_latched_before_the_first_request_makes_none(monkeypatch, tmp_path):
    from tts.epub2tts_edge import epub2tts_edge as engine

    constructed = []

    class Communicate:
        def __init__(self, sentence, speaker):
            constructed.append(sentence)

        async def save(self, filename):
            Path(filename).write_bytes(b"audio")

    monkeypatch.setattr(engine.edge_tts, "Communicate", Communicate)
    target = tmp_path / "clip.mp3"
    with pytest.raises(ConversionCancelled):
        engine.run_edgespeak("Hello there.", "v", str(target), cancel_check=lambda: True)
    assert constructed == [] and not target.exists()


def test_the_direct_request_loop_does_not_sit_out_a_back_off_after_cancel(monkeypatch, tmp_path):
    from tts.epub2tts_edge import epub2tts_edge as engine

    cancelled = threading.Event()
    attempts = []

    class FailingCommunicate:
        def __init__(self, sentence, speaker):
            attempts.append(sentence)

        async def save(self, filename):
            raise ConnectionResetError("transient")

    monkeypatch.setattr(engine.edge_tts, "Communicate", FailingCommunicate)
    monkeypatch.setattr(engine, "RETRY_BASE_DELAY_SEC", 30.0)
    threading.Timer(0.2, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        engine.run_edgespeak("Hello there.", "v", str(tmp_path / "clip.mp3"), cancel_check=cancelled.is_set)
    assert len(attempts) == 1 and time.monotonic() - started < 3


def test_an_in_flight_direct_request_is_abandoned_on_cancel(monkeypatch, tmp_path):
    from tts.epub2tts_edge import epub2tts_edge as engine

    cancelled = threading.Event()
    abandoned = []

    class SlowCommunicate:
        def __init__(self, sentence, speaker):
            pass

        async def save(self, filename):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                abandoned.append(True)
                raise

    monkeypatch.setattr(engine.edge_tts, "Communicate", SlowCommunicate)
    threading.Timer(0.2, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        engine.run_edgespeak("Hello there.", "v", str(tmp_path / "clip.mp3"), cancel_check=cancelled.is_set)
    assert abandoned == [True] and time.monotonic() - started < 3


def test_eight_workers_make_no_request_after_the_latch(monkeypatch, tmp_path):
    """Eight conversions, each parked inside its first request at a barrier; Cancel is pressed while all eight are there;
    every request then fails as a transient would. Not one of them makes a second request, every conversion ends as a
    Cancel, and nothing is published. Deterministic: the barrier, not timing, decides who is where when Cancel lands."""
    from tts.epub2tts_edge import epub2tts_edge as engine
    from tts.epub2tts_edge import runner

    workers = 8
    cancelled = threading.Event()
    all_parked = threading.Barrier(workers + 1)
    constructed = []
    lock = threading.Lock()

    class ParkedCommunicate:
        def __init__(self, sentence, speaker):
            with lock:
                constructed.append(threading.get_ident())

        async def save(self, filename):
            await asyncio.get_running_loop().run_in_executor(None, all_parked.wait)
            raise ConnectionResetError("transient")

    monkeypatch.setattr(engine.edge_tts, "Communicate", ParkedCommunicate)
    monkeypatch.setattr(engine, "RETRY_BASE_DELAY_SEC", 30.0)
    monkeypatch.setattr(engine, "ensure_punkt", lambda: None, raising=False)
    sources = []
    for n in range(workers):
        folder = tmp_path / "in" / str(n)
        folder.mkdir(parents=True)
        source = folder / "book.txt"
        source.write_text("# One\n\nA sentence to read.\n", encoding="utf-8")
        sources.append(source)
    outcomes: dict[int, object] = {}

    def convert(n: int) -> None:
        try:
            outcomes[n] = runner.run_conversion_job(str(sources[n]), output_dir=str(tmp_path / "out" / str(n)),
                                                    audio_format="mp3", cancel_check=cancelled.is_set)
        except BaseException as exc:  # noqa: BLE001 - recorded, then judged
            outcomes[n] = exc

    threads = [threading.Thread(target=convert, args=(n,), daemon=True) for n in range(workers)]
    for thread in threads:
        thread.start()
    all_parked.wait(timeout=30)  # every worker is inside its first request
    cancelled.set()
    deadline = time.monotonic() + 30
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    still_going = [t for t in threads if t.is_alive()]
    all_parked.abort()  # a request made after the latch would wait at this barrier for ever: a finding, not a stuck suite
    assert not still_going, f"{len(still_going)} conversions did not stop"
    assert all(isinstance(outcomes[n], ConversionCancelled) for n in range(workers)), outcomes
    assert len(constructed) == workers, "exactly one request per worker: none after the latch"
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").rglob("*.mp3"))


# --------------------------------------------------------------------------- a cancelled request costs a bounded time (P1-R02)

#: Every limit below is what the contract allows at the production bound plus scheduling room; the test bounds its own wait
#: with ``_bounded`` so the old unbounded waits fail instead of hanging the suite.
REQUEST_LIMIT = edge_requests.CANCEL_POLL_SECONDS + 2 * edge_requests.REQUEST_STOP_SECONDS + 1.5


def _bounded(body, limit: float = WAIT) -> tuple[bool, object, float]:
    """Run ``body`` on a daemon thread: (it ended, its result or exception, seconds). A hang is a finding, not a stuck suite."""
    out: dict[str, object] = {}

    def run() -> None:
        started = time.monotonic()
        try:
            out["end"] = body()
        except BaseException as exc:  # noqa: BLE001 - recorded, then judged
            out["end"] = exc
        out["seconds"] = time.monotonic() - started

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(limit)
    return not thread.is_alive(), out.get("end"), float(out.get("seconds", limit))


class _Refusing:
    """A request that swallows every cancellation until the test lets it go, counting how long it stays alive."""

    def __init__(self):
        self.ticks = 0
        self.cancels = 0
        self.released = threading.Event()

    async def request(self):
        while not self.released.is_set():
            self.ticks += 1
            try:
                await asyncio.sleep(0.005)
            except asyncio.CancelledError:
                self.cancels += 1


def test_awaiting_a_request_that_refuses_cancellation_ends_within_the_bound():
    """The helper itself: it used to ``await`` the cancelled task for as long as the task liked, which is for ever here."""
    refusing = _Refusing()

    def body():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                edge_requests.await_unless_cancelled(refusing.request(), lambda: True, poll=0.01, stop_seconds=0.05))
        finally:
            refusing.released.set()
            loop.run_until_complete(asyncio.sleep(0.02))
            loop.close()

    ended, end, seconds = _bounded(body, 3)
    refusing.released.set()
    assert ended, "the helper is still waiting for a task that will never end"
    assert isinstance(end, ConversionCancelled) and seconds < 2


def test_the_old_driver_hangs_at_loop_shutdown_even_when_the_helper_returns():
    """Negative control: why ``asyncio.run`` cannot stay under a request. Its shutdown cancels what is left and waits with no
    limit. If this ever stops hanging, ``run_request`` has lost its reason to exist and should be reconsidered."""
    refusing = _Refusing()
    ended, _end, _seconds = _bounded(
        lambda: asyncio.run(edge_requests.await_unless_cancelled(refusing.request(), lambda: True, poll=0.01, stop_seconds=0.05)),
        1.0)
    refusing.released.set()
    assert not ended, "asyncio.run returned with a task refusing to stop"


def test_a_request_that_refuses_is_dropped_within_the_bound_stops_running_and_says_so():
    refusing = _Refusing()
    notes: list[str] = []
    ended, end, seconds = _bounded(lambda: edge_requests.run_request(
        edge_requests.await_unless_cancelled(refusing.request(), lambda: True, poll=0.01, stop_seconds=0.1),
        stop_seconds=0.1, note=notes.append))
    refusing.released.set()
    assert ended, "the driver is still waiting"
    assert isinstance(end, ConversionCancelled), end
    assert seconds < 2
    assert refusing.cancels >= 1
    assert len(notes) == 1 and "did not stop" in notes[0], "a request that was not stopped is reported as exactly that"
    ticks = refusing.ticks
    time.sleep(0.15)
    assert refusing.ticks == ticks, "the abandoned request is still running somewhere"


def test_the_production_bound_holds_with_the_production_constants():
    refusing = _Refusing()
    armed = threading.Event()
    threading.Timer(0.05, armed.set).start()
    ended, end, seconds = _bounded(lambda: edge_requests.run_request(
        edge_requests.await_unless_cancelled(refusing.request(), armed.is_set), note=lambda _note: None))
    refusing.released.set()
    assert ended and isinstance(end, ConversionCancelled), end
    assert seconds < REQUEST_LIMIT, f"{seconds:.2f} s"


def test_a_request_with_slow_cleanup_gets_the_time_and_is_not_called_abandoned():
    finished: list[bool] = []
    notes: list[str] = []

    async def request():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)  # closing its connection, as a well-behaved request does
            finished.append(True)
            raise

    with pytest.raises(ConversionCancelled):
        edge_requests.run_request(edge_requests.await_unless_cancelled(request(), lambda: True, poll=0.01, stop_seconds=2),
                                 stop_seconds=2, note=notes.append)
    assert finished == [True], "its cleanup was cut short"
    assert notes == [], "nothing was abandoned, so nothing may say so"


def test_a_request_stuck_in_cleanup_is_asked_a_second_time():
    """aiohttp's own shape: the first cancellation starts a polite close that waits for the peer, the second aborts it."""
    asked: list[str] = []
    notes: list[str] = []

    async def request():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            asked.append("first")
            try:
                await asyncio.sleep(3600)  # the peer never answers the close
            except asyncio.CancelledError:
                asked.append("second")
                raise

    ended, end, _seconds = _bounded(lambda: edge_requests.run_request(
        edge_requests.await_unless_cancelled(request(), lambda: True, poll=0.01, stop_seconds=0.1),
        stop_seconds=0.5, note=notes.append), 5)
    assert ended, "the first cancellation's cleanup is being waited for with no limit"
    assert isinstance(end, ConversionCancelled), end
    assert asked == ["first", "second"] and notes == []


def test_an_honest_task_left_on_the_loop_is_cancelled_at_shutdown_and_cleans_up():
    """What the shutdown's own cancellation is for: not the awaited request, whose helper has already asked, but anything else
    left on the loop. It gets the chance ``asyncio.run`` would give it and, having taken it, is not called abandoned."""
    cleaned: list[bool] = []
    notes: list[str] = []

    async def left_behind():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cleaned.append(True)
            raise

    async def request():
        asyncio.ensure_future(left_behind())
        await asyncio.sleep(0)
        return "finished"

    assert edge_requests.run_request(request(), stop_seconds=2, note=notes.append) == "finished"
    assert cleaned == [True], "it was never cancelled"
    assert notes == []


def test_another_task_refusing_at_loop_shutdown_is_bounded_and_reported():
    refusing = _Refusing()
    notes: list[str] = []

    async def request():
        asyncio.ensure_future(refusing.request())
        await asyncio.sleep(3600)

    ended, end, seconds = _bounded(lambda: edge_requests.run_request(
        edge_requests.await_unless_cancelled(request(), lambda: True, poll=0.01, stop_seconds=0.1),
        stop_seconds=0.1, note=notes.append))
    refusing.released.set()
    assert ended and isinstance(end, ConversionCancelled) and seconds < 2, end
    assert len(notes) == 1 and "did not stop" in notes[0]


def test_a_blocked_executor_call_cannot_hold_the_shutdown_and_is_reported():
    """What a name lookup is: a blocking call on the loop's default executor. ``asyncio.run`` waits up to 300 s for it."""
    release = threading.Event()
    notes: list[str] = []

    async def request():
        await asyncio.get_running_loop().run_in_executor(None, release.wait)

    before = set(threading.enumerate())
    ended, end, seconds = _bounded(lambda: edge_requests.run_request(
        edge_requests.await_unless_cancelled(request(), lambda: True, poll=0.01, stop_seconds=0.1),
        stop_seconds=0.1, note=notes.append))
    try:
        assert ended and isinstance(end, ConversionCancelled) and seconds < 2, end
        assert len(notes) == 1 and "still waiting" in notes[0], notes
    finally:
        release.set()
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline and [t for t in threading.enumerate() if t not in before and t.name.startswith("act-request")]:
        time.sleep(0.01)
    assert not [t for t in threading.enumerate() if t not in before and t.name.startswith("act-request")], "the lookup's thread outlived it"


# ---- a generator left open: the loop's shutdown has to close it, and its cleanup can outlast the deadline too


def _complaints(caplog) -> list[str]:
    """What asyncio itself said at warning level or above: "Task was destroyed but it is pending!" and the like."""
    return [record.getMessage() for record in caplog.records if record.name == "asyncio" and record.levelno >= logging.WARNING]


def _leave_open(generator_function, caplog, monkeypatch, *, then=None):
    """Drive a request that leaves a generator suspended and still referenced, so only ``shutdown_asyncgens`` can close it, then
    collect, which is when asyncio complains about anything left pending. (ended, end, seconds, notes, unraisable)."""
    held: list[object] = []
    notes: list[str] = []
    unraisable: list[str] = []
    monkeypatch.setattr(sys, "unraisablehook", lambda report: unraisable.append(repr(report.exc_value)))

    async def request():
        generator = generator_function()
        held.append(generator)
        await generator.__anext__()
        if then is not None:
            await then()
        return "finished"

    with caplog.at_level(logging.WARNING, logger="asyncio"):
        ended, end, seconds = _bounded(lambda: edge_requests.run_request(request(), stop_seconds=0.1, note=notes.append))
        held.clear()
        gc.collect()
    return ended, end, seconds, notes, unraisable


def test_a_generator_whose_cleanup_outlasts_the_deadline_is_cancelled_and_said_so(caplog, monkeypatch):
    seen: list[str] = []

    async def generator():
        try:
            yield "open"
        finally:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                seen.append("cancelled")
                raise

    ended, end, seconds, notes, unraisable = _leave_open(generator, caplog, monkeypatch)
    assert ended and seconds < 2, "the shutdown is waiting for the generator's cleanup"
    assert end == "finished", "the request's own answer is unchanged"
    assert seen == ["cancelled"], "the closing task was left pending instead of being stopped"
    assert len(notes) == 1 and "cut short" in notes[0], notes
    assert _complaints(caplog) == [] and unraisable == []


def test_a_generator_whose_cleanup_refuses_cancellation_is_dropped_stops_running_and_is_said_so(caplog, monkeypatch):
    refusing = _Refusing()

    async def generator():
        try:
            yield "open"
        finally:
            await refusing.request()

    try:
        ended, end, seconds, notes, unraisable = _leave_open(generator, caplog, monkeypatch)
        assert ended and seconds < 2, "the shutdown is waiting for the generator's cleanup"
        assert end == "finished"
        assert refusing.cancels >= 1, "its cleanup was never asked to stop"
        assert len(notes) == 1 and "cut short" in notes[0], notes
        assert _complaints(caplog) == [] and unraisable == []
        ticks = refusing.ticks
        time.sleep(0.15)
        assert refusing.ticks == ticks, "the abandoned cleanup is still running somewhere"
    finally:
        refusing.released.set()


def test_a_generator_left_open_cannot_replace_the_requests_own_failure(caplog, monkeypatch):
    async def generator():
        try:
            yield "open"
        finally:
            await asyncio.sleep(3600)

    async def fails():
        raise ConnectionResetError("transient")

    ended, end, seconds, notes, unraisable = _leave_open(generator, caplog, monkeypatch, then=fails)
    assert ended and seconds < 2
    assert isinstance(end, ConnectionResetError), end
    assert len(notes) == 1 and "cut short" in notes[0], notes
    assert _complaints(caplog) == [] and unraisable == []


def test_a_refused_request_and_a_refused_cleanup_share_one_deadline_and_are_each_said(caplog, monkeypatch):
    request_refusing, cleanup_refusing = _Refusing(), _Refusing()

    async def generator():
        try:
            yield "open"
        finally:
            await cleanup_refusing.request()

    def then():
        return edge_requests.await_unless_cancelled(request_refusing.request(), lambda: True, poll=0.01, stop_seconds=0.05)

    try:
        ended, end, seconds, notes, unraisable = _leave_open(generator, caplog, monkeypatch, then=then)
        assert ended and seconds < 2
        assert isinstance(end, ConversionCancelled), end
        assert len(notes) == 2 and "did not stop" in notes[0] and "cut short" in notes[1], notes
        assert _complaints(caplog) == [] and unraisable == []
    finally:
        request_refusing.released.set()
        cleanup_refusing.released.set()


def test_a_generator_whose_cleanup_finishes_in_time_is_not_called_cut_short(caplog, monkeypatch):
    """Negative control: the note must mean something."""
    seen: list[str] = []

    async def generator():
        try:
            yield "open"
        finally:
            await asyncio.sleep(0.01)
            seen.append("closed")

    ended, end, _seconds, notes, unraisable = _leave_open(generator, caplog, monkeypatch)
    assert ended and end == "finished"
    assert seen == ["closed"], "its cleanup was cut short for no reason"
    assert notes == [] and _complaints(caplog) == [] and unraisable == []


def test_a_dropped_generator_cleanup_does_not_keep_a_connection_open():
    """What the collection after a dropped cleanup is for, seen from the far end of a real socket held in a reference cycle."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(WAIT)
    port = listener.getsockname()[1]
    kept: list[object] = []
    notes: list[str] = []
    outcome: list[object] = []

    async def generator():
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"hello")
        await writer.drain()
        held = {"writer": writer}
        held["self"] = held
        del held, writer, _reader
        try:
            yield "open"
        finally:
            while True:
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    pass

    async def request():
        kept.append(generator())
        await kept[0].__anext__()
        return "finished"

    def drive():
        outcome.append(edge_requests.run_request(request(), stop_seconds=0.1, note=notes.append))

    driver = threading.Thread(target=drive, daemon=True)
    driver.start()
    peer, _address = listener.accept()
    try:
        peer.settimeout(WAIT)
        assert peer.recv(5) == b"hello"
        driver.join(WAIT)
        assert outcome == ["finished"]
        assert len(notes) == 1 and "cut short" in notes[0], notes
        assert peer.recv(1) == b"", "the connection of the dropped cleanup is still open"
    finally:
        peer.close()
        listener.close()
        kept.clear()


@pytest.mark.parametrize("in_a_cycle", [False, True], ids=["plain", "in-a-reference-cycle"])
def test_a_refused_request_does_not_keep_its_connection_open(in_a_cycle):
    """Evidence, not a claim: a real socket on the real event loop, held by a request that refuses to stop. Once the driver
    has dropped the request the far end sees the connection close. The second form holds it the way a real client's objects
    do (a session and its connector, a response and its connection refer to each other), which reference counting alone
    never releases: this is what the driver's collection is for."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(WAIT)
    port = listener.getsockname()[1]
    connected = threading.Event()
    notes: list[str] = []

    async def request():
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"hello")
        await writer.drain()
        if in_a_cycle:
            held = {"writer": writer}
            held["self"] = held
            del held, writer, _reader
        connected.set()
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass

    armed = threading.Event()
    outcome: list[object] = []

    def drive():
        try:
            edge_requests.run_request(edge_requests.await_unless_cancelled(request(), armed.is_set, poll=0.01, stop_seconds=0.1),
                                     stop_seconds=0.1, note=notes.append)
        except BaseException as exc:  # noqa: BLE001 - judged below
            outcome.append(exc)

    driver = threading.Thread(target=drive, daemon=True)
    driver.start()
    peer, _address = listener.accept()
    try:
        assert connected.wait(WAIT)
        peer.settimeout(WAIT)
        assert peer.recv(5) == b"hello"
        armed.set()
        driver.join(WAIT)
        assert not driver.is_alive() and isinstance(outcome[0], ConversionCancelled), outcome
        assert len(notes) == 1
        assert peer.recv(1) == b"", "the connection of the dropped request is still open"
    finally:
        peer.close()
        listener.close()


def test_a_finished_request_is_unchanged_by_the_driver():
    marker = contextvars.ContextVar("marker", default="unset")
    marker.set("visible")

    async def request():
        await asyncio.sleep(0)
        answer = await asyncio.get_running_loop().run_in_executor(None, lambda: 41)
        return marker.get(), answer + 1

    notes: list[str] = []
    assert edge_requests.run_request(edge_requests.await_unless_cancelled(request(), lambda: False, poll=0.01),
                                    note=notes.append) == ("visible", 42)
    assert edge_requests.run_request(request(), note=notes.append) == ("visible", 42), "no check: a plain request"
    assert notes == []

    async def failing():
        raise ConnectionResetError("transient")

    with pytest.raises(ConnectionResetError):
        edge_requests.run_request(edge_requests.await_unless_cancelled(failing(), lambda: False, poll=0.01), note=notes.append)
    assert notes == [], "a failure is reported by being raised"
    assert not [t for t in threading.enumerate() if t.name.startswith("act-request")], "no thread outlives a finished request"


class _RefusingCommunicate:
    """The Edge client's seam, standing in for a request that writes part of a file and then will not stop."""

    made: list[str] = []
    live: list["_Refusing"] = []

    def __init__(self, *arguments, **options):
        type(self).made.append("request")

    async def save(self, filename):
        refusing = _Refusing()
        type(self).live.append(refusing)
        with open(filename, "wb") as partial:
            partial.write(b"partial audio")
            partial.flush()
            await refusing.request()


@pytest.fixture
def refusing_client(monkeypatch):
    _RefusingCommunicate.made, _RefusingCommunicate.live = [], []
    yield _RefusingCommunicate
    for refusing in _RefusingCommunicate.live:
        refusing.released.set()


def test_the_direct_route_ends_on_a_refusing_request_makes_no_other_and_removes_its_partial(monkeypatch, tmp_path, capsys, refusing_client):
    from tts.epub2tts_edge import epub2tts_edge as engine

    monkeypatch.setattr(engine.edge_tts, "Communicate", refusing_client)
    target = tmp_path / "clip.mp3"
    armed = threading.Event()
    threading.Timer(0.1, armed.set).start()
    ended, end, seconds = _bounded(lambda: engine.run_edgespeak("Hello there.", "v", str(target), cancel_check=armed.is_set))
    assert ended, "Cancel is still waiting for the request"
    assert isinstance(end, ConversionCancelled), end
    assert seconds < REQUEST_LIMIT + 0.1, f"{seconds:.2f} s"
    assert len(refusing_client.made) == 1, "no further request after Cancel"
    assert not target.exists(), "the abandoned request's partial audio is gone"
    assert "did not stop" in capsys.readouterr().out, "the log says what happened to that request"


def test_the_folder_route_ends_on_a_refusing_request_and_does_not_turn_it_into_a_file_error(monkeypatch, tmp_path, capsys, refusing_client):
    """The partial chunk is still held open when the coroutine tries to remove it, which on Windows raises. A locked file must
    not replace the Cancel: a PermissionError here would be classified and retried as a local failure."""
    from tts import batch_convert

    monkeypatch.setattr(batch_convert.edge_tts, "Communicate", refusing_client)
    target = tmp_path / "chunk.mp3"
    armed = threading.Event()
    threading.Timer(0.1, armed.set).start()
    ended, end, seconds = _bounded(lambda: batch_convert.synthesize_chunk_mp3("Hello.", str(target), "v", "+0%", cancel_check=armed.is_set))
    assert ended, "Cancel is still waiting for the request"
    assert isinstance(end, ConversionCancelled), end
    assert seconds < REQUEST_LIMIT + 0.1, f"{seconds:.2f} s"
    assert len(refusing_client.made) == 1
    assert "did not stop" in capsys.readouterr().out
    target.unlink(missing_ok=True)  # raises on Windows if the dropped request still held it: the route's folder removal needs this


def test_a_chapter_titles_request_answers_to_the_same_cancel(monkeypatch, tmp_path, capsys, refusing_client):
    """The one request still started under ``asyncio.run``: ``parallel_edgespeak`` makes it on a thread of its own, where its
    driver is ``run_request`` and only the context copied there connects it to this conversion's Cancel."""
    from tts.epub2tts_edge import epub2tts_edge as engine

    monkeypatch.setattr(engine.edge_tts, "Communicate", refusing_client)
    target = tmp_path / "sntnc0.mp3"
    armed = threading.Event()
    threading.Timer(0.1, armed.set).start()

    def title():
        with ffmpeg_watch.controlled(armed.is_set):
            asyncio.run(engine.parallel_edgespeak(["Chapter One"], ["v"], [str(target)]))

    ended, end, seconds = _bounded(title)
    assert ended, "Cancel is still waiting for the title's request"
    assert isinstance(end, ConversionCancelled), end
    assert seconds < REQUEST_LIMIT + 0.1, f"{seconds:.2f} s"
    assert len(refusing_client.made) == 1, "no further request after Cancel"
    assert not target.exists(), "the abandoned request's partial audio is gone"
    assert "did not stop" in capsys.readouterr().out


def test_eight_workers_whose_requests_refuse_all_end_within_the_bound(monkeypatch, tmp_path, refusing_client):
    """Eight conversions, each inside a request that will not stop, Cancel pressed: every one ends as a Cancel, none makes a
    second request, nothing is published, and the wait is one request's bound, not eight of them in a row."""
    from tts.epub2tts_edge import epub2tts_edge as engine
    from tts.epub2tts_edge import runner

    workers = 8
    cancelled = threading.Event()
    monkeypatch.setattr(engine.edge_tts, "Communicate", refusing_client)
    monkeypatch.setattr(engine, "ensure_punkt", lambda: None, raising=False)
    sources = []
    for n in range(workers):
        folder = tmp_path / "in" / str(n)
        folder.mkdir(parents=True)
        source = folder / "book.txt"
        source.write_text("# One\n\nA sentence to read.\n", encoding="utf-8")
        sources.append(source)
    outcomes: dict[int, object] = {}

    def convert(n: int) -> None:
        try:
            outcomes[n] = runner.run_conversion_job(str(sources[n]), output_dir=str(tmp_path / "out" / str(n)),
                                                    audio_format="mp3", cancel_check=cancelled.is_set)
        except BaseException as exc:  # noqa: BLE001 - recorded, then judged
            outcomes[n] = exc

    threads = [threading.Thread(target=convert, args=(n,), daemon=True) for n in range(workers)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + WAIT
    while len(refusing_client.live) < workers and time.monotonic() < deadline:
        time.sleep(0.005)
    assert len(refusing_client.live) == workers, "every worker is inside its request"
    started = time.monotonic()
    cancelled.set()
    for thread in threads:
        thread.join(WAIT)
    seconds = time.monotonic() - started
    assert all(not t.is_alive() for t in threads), "a worker is still waiting for its request"
    assert all(isinstance(outcomes[n], ConversionCancelled) for n in range(workers)), outcomes
    assert len(refusing_client.made) == workers, "exactly one request per worker: none after the latch"
    assert seconds < REQUEST_LIMIT + 1.5, f"{seconds:.2f} s: the bound was multiplied"
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").rglob("*.mp3"))


def test_neither_edge_request_is_driven_by_asyncio_run_any_more():
    import source_probe

    for relative, name in (("tts/epub2tts_edge/epub2tts_edge.py", "run_save"), ("tts/batch_convert.py", "synthesize_chunk_mp3")):
        called = source_probe.calls(source_probe.function(relative, name))
        assert "run_request" in called and "run" not in called, f"{name}: {called}"


# ---- what a dropped request's connection waits for: one full collection that began after the drop, and it is shared
#
# The full gate failed the eight workers above at 5.27 s against 5.25 s: each dropped request ran a full collection of its own,
# a collection holds every other thread up, and on the heap a full run builds one costs 0.33-0.45 s. Removing the collection is
# not the answer, because a connection held in a reference cycle is released by nothing else (the tests above). And a
# ``gc.collect()`` made while another is under way does nothing at all, so a request dropped during one was simply left open.

COLLECTOR_THREAD = "act-dropped-requests-collector"


class _Collections:
    """Every full collection that really ran, as the interpreter reports them: a ``gc.collect()`` that found another under way
    never appears. Automatic collection is off inside, so only what was asked for is counted and nothing is closed by luck."""

    def __enter__(self):
        self.began = 0
        self.seconds: list[float] = []
        self._enabled = gc.isenabled()
        gc.disable()
        gc.callbacks.append(self._saw)
        return self

    def __exit__(self, *_exception):
        gc.callbacks.remove(self._saw)
        if self._enabled:
            gc.enable()

    def _saw(self, phase, info):
        if info["generation"] == 2 and phase == "start":
            self.began += 1
            self._started = time.perf_counter()
        elif info["generation"] == 2:
            self.seconds.append(time.perf_counter() - self._started)


class _Stuck:
    """Garbage whose finalizer holds the collection that found it until the test lets go: a long collection, made deterministic.
    A finalizer runs after the collection has chosen what is garbage, so whatever is dropped from then on is not among it."""

    def __init__(self, reached: threading.Event, release: threading.Event):
        self.reached, self.release, self.myself = reached, release, self

    def __del__(self):
        self.reached.set()
        self.release.wait(WAIT)


@contextlib.contextmanager
def _a_collection_under_way():
    """A real full collection that is nobody's request, held until the block ends. The first of the block's collections."""
    reached, release = threading.Event(), threading.Event()
    _Stuck(reached, release)
    collecting = threading.Thread(target=gc.collect, daemon=True)
    collecting.start()
    assert reached.wait(WAIT)
    try:
        yield
    finally:
        release.set()
        collecting.join(WAIT)


class _RefusedConnection:
    """A real request on the real driver: it connects to this test, keeps the connection only through a reference cycle, the way
    a client's session and connector do, and refuses to stop. ``holding`` makes something else that only the cycle keeps."""

    def __init__(self, holding=None):
        self.holding = holding
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(WAIT)
        self.armed = threading.Event()
        self.notes: list[str] = []
        self.outcome: list[object] = []
        self.driver = threading.Thread(target=self._drive, daemon=True)
        self.driver.start()
        self.peer, _address = self.listener.accept()
        self.peer.settimeout(WAIT)
        assert self.peer.recv(5) == b"hello"

    async def _request(self):
        _reader, writer = await asyncio.open_connection("127.0.0.1", self.listener.getsockname()[1])
        writer.write(b"hello")
        await writer.drain()
        held = {"writer": writer, "also": self.holding() if self.holding else None}
        held["self"] = held
        del writer, _reader  # ``held`` stays: garbage from the moment this frame goes, and not before
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass

    def _drive(self):
        try:
            edge_requests.run_request(edge_requests.await_unless_cancelled(self._request(), self.armed.is_set, poll=0.01, stop_seconds=0.05),
                                      stop_seconds=0.05, note=self.notes.append)
        except BaseException as exc:  # noqa: BLE001 - judged by the test
            self.outcome.append(exc)

    def driver_ended_as_a_cancel(self) -> bool:
        self.driver.join(WAIT)
        return not self.driver.is_alive() and isinstance(self.outcome[0], ConversionCancelled)

    def far_end_sees_it_closed(self) -> bool:
        return self.peer.recv(1) == b""

    def close(self) -> None:
        self.peer.close()
        self.listener.close()


def _collector_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == COLLECTOR_THREAD]


def _wait_for_the_collector_to_end() -> None:
    deadline = time.monotonic() + WAIT
    while _collector_threads() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert not _collector_threads(), "a collector thread is still running with nothing owed"


@pytest.fixture(autouse=True)
def _no_collection_outlives_its_test():
    """A dropped request's collection may outlast its request. It may not run on into the next test, and it may not stay."""
    yield
    _wait_for_the_collector_to_end()


def test_a_request_dropped_during_a_collection_is_not_forgotten():
    """A ``gc.collect()`` made while another is under way returns at once having done nothing, and that one chose its garbage
    before this request was dropped. Left at that, nothing would ever close this connection."""
    connection = _RefusedConnection()
    try:
        with _Collections() as collections:
            with _a_collection_under_way():
                connection.armed.set()
                assert connection.driver_ended_as_a_cancel()
            assert connection.far_end_sees_it_closed(), "the connection of the dropped request is still open"
            _wait_for_the_collector_to_end()
        assert collections.began == 2, "the one under way, and one that began after the drop"
    finally:
        connection.close()


def test_a_request_dropped_during_another_requests_collection_is_not_forgotten():
    """The same, between two requests: the first one's collection is the one under way when the second is dropped."""
    reached, release = threading.Event(), threading.Event()
    first = _RefusedConnection(holding=lambda: _Stuck(reached, release))
    second = _RefusedConnection()
    try:
        with _Collections() as collections:
            first.armed.set()
            assert reached.wait(WAIT), "the first drop's collection never began"
            second.armed.set()
            second.driver.join(WAIT)
            release.set()
            assert first.driver_ended_as_a_cancel() and second.driver_ended_as_a_cancel()
            assert first.far_end_sees_it_closed()
            assert second.far_end_sees_it_closed(), "the second connection was left to a collection that began before its drop"
            _wait_for_the_collector_to_end()
        assert collections.began == 2
    finally:
        release.set()
        first.close()
        second.close()


def test_eight_requests_dropped_during_one_collection_share_a_single_further_one():
    """The sharing, with its order fixed by a barrier: all eight real connections close, on one collection between them."""
    connections = [_RefusedConnection() for _ in range(8)]
    try:
        with _Collections() as collections:
            with _a_collection_under_way():
                for connection in connections:
                    connection.armed.set()
                assert all(connection.driver_ended_as_a_cancel() for connection in connections), \
                    "a driver is waiting for a collection, and the wait has no end while this one is held"
            assert all(connection.far_end_sees_it_closed() for connection in connections), "a dropped request's connection is still open"
            _wait_for_the_collector_to_end()
        assert collections.began == 2, f"{collections.began} collections: the one under way and exactly one more"
    finally:
        for connection in connections:
            connection.close()


def test_a_finalizer_that_blocks_cannot_hold_the_cancel():
    """Whatever the dropped objects' finalizers do, the driver's wait has an end, and the collection finishes when they do."""
    reached, release = threading.Event(), threading.Event()
    connection = _RefusedConnection(holding=lambda: _Stuck(reached, release))
    try:
        started = time.monotonic()
        connection.armed.set()
        assert reached.wait(WAIT), "the collection never began"
        connection.driver.join(2)
        assert not connection.driver.is_alive(), "Cancel is waiting for a finalizer"
        assert isinstance(connection.outcome[0], ConversionCancelled), connection.outcome
        assert time.monotonic() - started < 2
        assert len(_collector_threads()) == 1, "the collection is under way, on its own thread"
        release.set()
        assert connection.far_end_sees_it_closed()
    finally:
        release.set()
        connection.close()


def test_the_collector_goes_when_nothing_is_owed_and_a_later_drop_starts_another():
    """No thread stays behind, nothing is left on the interpreter's list of callbacks, and a request dropped later still counts."""
    callbacks = list(gc.callbacks)
    for _round in range(2):
        connection = _RefusedConnection()
        try:
            connection.armed.set()
            assert connection.driver_ended_as_a_cancel()
            assert connection.far_end_sees_it_closed()
            _wait_for_the_collector_to_end()
            assert gc.callbacks == callbacks
        finally:
            connection.close()


def test_a_request_that_needs_no_collection_gets_none():
    """Sockets are only ever at stake for what was dropped: a request that finishes, or stops when asked, costs nothing."""
    async def finishes():
        await asyncio.sleep(0)
        return "finished"

    async def stops():
        await asyncio.sleep(3600)

    before = set(threading.enumerate())
    notes: list[str] = []
    with _Collections() as collections:
        assert edge_requests.run_request(finishes(), note=notes.append) == "finished"
        with pytest.raises(ConversionCancelled):
            edge_requests.run_request(edge_requests.await_unless_cancelled(stops(), lambda: True, poll=0.01), note=notes.append)
    assert collections.began == 0 and notes == []
    assert set(threading.enumerate()) <= before, "a thread was started for nothing"


@pytest.mark.parametrize("refusal", [RuntimeError("can't start new thread"), MemoryError()], ids=["no-thread", "no-memory"])
def test_no_thread_for_the_collector_costs_the_connection_and_never_the_cancel(monkeypatch, refusal):
    """Memory or the interpreter's own shutdown can refuse a thread. A collection has no deadline and cannot be stopped, so one on
    the cancelling thread could hold the Cancel for as long as a finalizer liked. The connection waits instead, the log says so,
    and the next drop that gets a thread pays for it. ``run_request`` ends in a ``finally``, so the refusal must not get out either."""
    real_start = threading.Thread.start

    def start(thread):
        if thread.name == COLLECTOR_THREAD:
            raise refusal
        real_start(thread)

    reached, release = threading.Event(), threading.Event()
    earlier = _RefusedConnection(holding=lambda: _Stuck(reached, release))
    later = _RefusedConnection()
    try:
        with _Collections() as collections:
            with monkeypatch.context() as refused:
                refused.setattr(threading.Thread, "start", start)
                earlier.armed.set()
                earlier.driver.join(2)
                assert not earlier.driver.is_alive(), "Cancel is waiting for a collection on its own thread"
                assert isinstance(earlier.outcome[0], ConversionCancelled), earlier.outcome
            assert not reached.is_set() and collections.began == 0, "a collection ran with no thread of its own"
            assert any("connection open" in note for note in earlier.notes), earlier.notes
            earlier.peer.settimeout(0.1)
            with pytest.raises(TimeoutError):
                earlier.far_end_sees_it_closed()
            earlier.peer.settimeout(WAIT)
            release.set()
            later.armed.set()
            assert later.driver_ended_as_a_cancel()
            assert later.far_end_sees_it_closed()
            assert earlier.far_end_sees_it_closed(), "the debt was forgotten"
            assert not any("connection open" in note for note in later.notes), later.notes
            _wait_for_the_collector_to_end()
        assert collections.began == 1
    finally:
        release.set()
        earlier.close()
        later.close()


def test_a_wait_that_cannot_be_set_up_does_not_replace_the_cancel_or_cost_the_collection(monkeypatch):
    """A condition's wait allocates a lock, so memory can refuse the wait too. The wait is worth having, and not worth the outcome."""
    def refused(*_arguments, **_keywords):
        raise MemoryError

    connection = _RefusedConnection()
    try:
        monkeypatch.setattr(edge_requests._collections, "wait_for", refused)
        connection.armed.set()
        assert connection.driver_ended_as_a_cancel(), connection.outcome
        assert connection.far_end_sees_it_closed(), "the collection depended on somebody waiting for it"
    finally:
        connection.close()


def test_a_collection_held_by_a_finalizer_cannot_stop_the_application_closing():
    """In a child with a hard timeout, because this ends with a thread stuck for good: Cancel returns, and the process still exits."""
    scripts = str(Path(edge_requests.__file__).resolve().parents[1])
    code = f"""
import asyncio, sys, threading
sys.path.insert(0, {scripts!r})
from shared.cancellation import ConversionCancelled
from tts import edge_requests

reached = threading.Event()

class Stuck:
    def __del__(self):
        reached.set()
        threading.Event().wait()

async def refuses():
    held = {{"stuck": Stuck()}}
    held["self"] = held
    while True:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass

try:
    edge_requests.run_request(edge_requests.await_unless_cancelled(refuses(), lambda: True, poll=0.01, stop_seconds=0.05),
                              stop_seconds=0.05, note=lambda _note: None)
except ConversionCancelled:
    print("cancelled", reached.wait(10))
"""
    finished = subprocess.run(_python(code), capture_output=True, text=True, timeout=WAIT)
    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.strip() == "cancelled True", finished.stdout + finished.stderr


def test_a_collector_that_could_not_get_a_turn_leaves_its_debt_to_the_next_drop(monkeypatch):
    """Its looks are bounded so that it can never stay for good. What it could not collect stays owed, and is not forgotten."""
    monkeypatch.setattr(edge_requests, "_COLLECTION_LOOKS", 2)
    monkeypatch.setattr(edge_requests, "_COLLECTION_LOOK_SECONDS", 0.001)
    earlier, later = _RefusedConnection(), _RefusedConnection()
    try:
        with _Collections() as collections:
            with _a_collection_under_way():
                earlier.armed.set()
                assert earlier.driver_ended_as_a_cancel()
                _wait_for_the_collector_to_end()
            assert collections.began == 1, "it gave up without a turn"
            earlier.peer.settimeout(0.1)
            with pytest.raises(TimeoutError):
                earlier.far_end_sees_it_closed()
            earlier.peer.settimeout(WAIT)
            later.armed.set()
            assert later.driver_ended_as_a_cancel()
            assert later.far_end_sees_it_closed()
            assert earlier.far_end_sees_it_closed(), "the debt was forgotten"
            _wait_for_the_collector_to_end()
        assert collections.began == 2
    finally:
        earlier.close()
        later.close()


@pytest.mark.parametrize("step", ["in-the-collection", "after-the-collection"])
def test_a_collector_that_fails_does_not_keep_its_place_and_does_not_hide_it(monkeypatch, step):
    """Short of memory above all, and at any step. If it died still counted as running, no later drop would start another and
    nothing would be collected again. What it could not collect stays owed, and the failure reaches ``threading.excepthook``."""
    def fails():
        raise MemoryError

    reported: list[object] = []
    earlier, later = _RefusedConnection(), _RefusedConnection()
    try:
        with _Collections() as collections:
            with monkeypatch.context() as failing:
                failing.setattr(threading, "excepthook", reported.append)
                if step == "in-the-collection":
                    failing.setattr(edge_requests, "_a_full_collection_began", fails)
                else:
                    failing.setattr(edge_requests, "_COLLECTION_GATHER_SECONDS", "not a length of time")
                earlier.armed.set()
                assert earlier.driver_ended_as_a_cancel()
                _wait_for_the_collector_to_end()
            assert [report.exc_type for report in reported] == [MemoryError if step == "in-the-collection" else TypeError], reported
            later.armed.set()
            assert later.driver_ended_as_a_cancel()
            assert later.far_end_sees_it_closed()
            assert earlier.far_end_sees_it_closed(), "the debt was forgotten"
            _wait_for_the_collector_to_end()
        assert collections.began == (1 if step == "in-the-collection" else 2)
    finally:
        earlier.close()
        later.close()


def test_the_collector_stands_aside_after_a_collection_so_that_those_it_held_up_share_the_next(monkeypatch):
    """A collection holds every other thread up, so at its end they have not yet said they were dropped. Started at once, the next
    collection covers few of them: on the loaded heap below, three collections and 3.6-3.7 s where two and 2.7-2.8 s will do
    (measured). That test's limits allow for it, so a window opened wide shows it every time: two drops in it, one further collection."""
    monkeypatch.setattr(edge_requests, "_COLLECTION_GATHER_SECONDS", 2.0)
    first, second, third = _RefusedConnection(), _RefusedConnection(), _RefusedConnection()
    try:
        with _Collections() as collections:
            first.armed.set()
            assert first.far_end_sees_it_closed(), "the first collection never ran"
            assert collections.began == 1
            second.armed.set()
            assert second.driver_ended_as_a_cancel()
            third.armed.set()
            assert third.driver_ended_as_a_cancel()
            assert collections.began == 1, "the next collection did not wait for those it had held up"
            assert second.far_end_sees_it_closed() and third.far_end_sees_it_closed()
            _wait_for_the_collector_to_end()
        assert collections.began == 2
    finally:
        for connection in (first, second, third):
            connection.close()


#: Filler for the heap below: 1.0 M dicts, about 220 MB, cost about 0.42 s a collection, every collection (measured), where the full
#: suite's own heap costs 0.33-0.45 s. Neither a count nor a plain build will do. 1.5 M empty lists cost 0.02 s. And a collection
#: leaves its objects in the order it reached them: reached in memory order, as an unshuffled list would be, 0.3 s falls to 0.06 s.
LOADED_HEAP_DICTS = 1_000_000


@pytest.fixture
def loaded_heap():
    """A heap whose full collection costs what a full run's does: the gate's failure, without the gate."""
    filler = [{"number": number, "link": None} for number in range(LOADED_HEAP_DICTS)]
    previous = filler[0]
    random.Random(7).shuffle(filler)
    for item in filler:
        item["link"], previous = previous, item
    del previous, item
    yield
    filler.clear()
    gc.collect()  # the links close a cycle, so that clearing alone would leave about 720,000 of them for some later test (measured)


def _cancel_workers_inside_refusing_requests(workers: int, monkeypatch, tmp_path, refusing_client) -> float:
    """The failing test's scenario, for any number of workers: how long from Cancel until the last of them has ended as one."""
    from tts.epub2tts_edge import epub2tts_edge as engine
    from tts.epub2tts_edge import runner

    refusing_client.made, refusing_client.live = [], []
    cancelled = threading.Event()
    monkeypatch.setattr(engine.edge_tts, "Communicate", refusing_client)
    monkeypatch.setattr(engine, "ensure_punkt", lambda: None, raising=False)
    outcomes: dict[int, object] = {}

    def convert(n: int, source: Path) -> None:
        try:
            outcomes[n] = runner.run_conversion_job(str(source), output_dir=str(tmp_path / f"out{workers}" / str(n)),
                                                    audio_format="mp3", cancel_check=cancelled.is_set)
        except BaseException as exc:  # noqa: BLE001 - recorded, then judged
            outcomes[n] = exc

    threads = []
    for n in range(workers):
        folder = tmp_path / f"in{workers}" / str(n)
        folder.mkdir(parents=True)
        source = folder / "book.txt"
        source.write_text("# One\n\nA sentence to read.\n", encoding="utf-8")
        threads.append(threading.Thread(target=convert, args=(n, source), daemon=True))
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + WAIT
    while len(refusing_client.live) < workers and time.monotonic() < deadline:
        time.sleep(0.005)
    assert len(refusing_client.live) == workers, "every worker is inside its request"
    started = time.monotonic()
    cancelled.set()
    for thread in threads:
        thread.join(WAIT)
    seconds = time.monotonic() - started
    assert all(not thread.is_alive() for thread in threads), "a worker is still waiting for its request"
    assert all(isinstance(outcomes[n], ConversionCancelled) for n in range(workers)), outcomes
    assert len(refusing_client.made) == workers, "exactly one request per worker: none after the latch"
    assert not list((tmp_path / f"out{workers}").rglob("*.mp3"))
    return seconds


def test_on_a_loaded_heap_eight_workers_share_their_collections_and_their_wait_does_not_grow_with_them(monkeypatch, tmp_path, refusing_client, loaded_heap, request):
    """The gate's failure, seen directly. A collection each made Cancel's wait grow by a full collection for every worker. Eight
    workers now cost what one does, plus at most the collection under way when the first arrives and the one after it. Three are
    allowed because the workers' looks at Cancel, up to 0.25 s apart, can straddle two collections; two is what is measured. What
    was asked for is counted as well as what ran: a request's own ``gc.collect()`` during another's ran nothing and said nothing."""
    real_collect = gc.collect
    asked: list[int] = []

    def counted_collect(*arguments):
        asked.append(1)
        return real_collect(*arguments)

    with _Collections() as one_worker:
        alone = _cancel_workers_inside_refusing_requests(1, monkeypatch, tmp_path, refusing_client)
        _wait_for_the_collector_to_end()
    monkeypatch.setattr(gc, "collect", counted_collect)
    with _Collections() as eight_workers:
        together = _cancel_workers_inside_refusing_requests(8, monkeypatch, tmp_path, refusing_client)
        _wait_for_the_collector_to_end()
    cost = min(one_worker.seconds)
    measured = (f"{alone:.2f} s alone, {together:.2f} s together; collections cost {[round(s, 2) for s in one_worker.seconds]} alone and "
                f"{[round(s, 2) for s in eight_workers.seconds]} together, {len(asked)} asked for")
    request.node.user_properties.append(("loaded_heap", measured))
    assert one_worker.began == 1, measured
    assert len(asked) <= 3 and eight_workers.began <= 3, measured
    assert together - alone < 2 * cost + edge_requests.CANCEL_POLL_SECONDS, f"seven more workers added collections' worth of waiting: {measured}"
    assert together < REQUEST_LIMIT + 1.5, measured


# ---- the real client, with no network: edge_tts + aiohttp against a WebSocket on this machine that never answers


@pytest.fixture
def silent_edge_service(monkeypatch):
    """A loopback server that accepts the Edge client's WebSocket, reads everything and answers nothing, not even a close: it
    holds the connection until the client itself drops it, which is what ``ended`` records. An ``async for`` alone would stop at
    the client's close frame and let the connection end, and the client's slow path would never be reached."""
    import edge_tts.communicate as client_module
    from aiohttp import web

    state = {"connections": 0, "ended": threading.Event()}
    ready, stop = threading.Event(), threading.Event()
    port: dict[str, int] = {}

    async def handler(request):
        state["connections"] += 1
        socket_ = web.WebSocketResponse(autoclose=False, autoping=False)
        await socket_.prepare(request)
        try:
            async for _message in socket_:
                pass
            while request.transport is not None and not request.transport.is_closing():
                await asyncio.sleep(0.01)
        finally:
            state["ended"].set()
        return socket_

    async def serve():
        application = web.Application()
        application.router.add_get("/{tail:.*}", handler)
        server = web.AppRunner(application)
        await server.setup()
        site = web.TCPSite(server, "127.0.0.1", 0)
        await site.start()
        port["number"] = site._server.sockets[0].getsockname()[1]
        ready.set()
        while not stop.is_set():
            await asyncio.sleep(0.01)
        await server.cleanup()

    thread = threading.Thread(target=lambda: asyncio.run(serve()), daemon=True)
    thread.start()
    assert ready.wait(WAIT)
    monkeypatch.setattr(client_module, "WSS_URL", f"ws://127.0.0.1:{port['number']}/edge?x=1")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    yield state
    stop.set()
    thread.join(WAIT)


def _real_request(tmp_path, cancel_after: float = 0.3):
    from tts.epub2tts_edge import epub2tts_edge as engine

    target = tmp_path / "clip.mp3"
    armed = threading.Event()
    threading.Timer(cancel_after, armed.set).start()
    ended, end, seconds = _bounded(lambda: engine.run_edgespeak("Hello there.", "en-US-AvaNeural", str(target), cancel_check=armed.is_set),
                                   30)
    return ended, end, seconds - cancel_after, target


def test_the_real_client_cancelled_while_receiving_stops_at_once(tmp_path, silent_edge_service):
    ended, end, after_cancel, target = _real_request(tmp_path)
    assert ended and isinstance(end, ConversionCancelled), end
    assert after_cancel < 1.0, f"{after_cancel:.2f} s"
    assert silent_edge_service["connections"] == 1, "no second request"
    assert silent_edge_service["ended"].wait(5), "the service still sees the connection open"
    assert not target.exists()


def test_the_real_client_cancelled_while_sending_does_not_sit_out_its_close_timeout(tmp_path, monkeypatch, capsys, silent_edge_service):
    """aiohttp's slow path: cancelled before it starts receiving, its close waits 10 s (``ws_close``) for a peer that never
    answers. Measured at 10.04 s under the old driver. The second cancellation aborts that wait, the connection really ends,
    and the request is stopped rather than abandoned, so the log has nothing to report."""
    import aiohttp

    async def parked(self, *_arguments, **_options):
        await asyncio.sleep(3600)

    monkeypatch.setattr(aiohttp.ClientWebSocketResponse, "send_str", parked)
    ended, end, after_cancel, target = _real_request(tmp_path)
    assert ended and isinstance(end, ConversionCancelled), end
    assert after_cancel < REQUEST_LIMIT, f"{after_cancel:.2f} s"
    assert silent_edge_service["connections"] == 1, "no second request"
    assert silent_edge_service["ended"].wait(5), "the service still sees the connection open"
    assert not target.exists()
    assert "did not stop" not in capsys.readouterr().out, "the real client stops when asked twice; it is not abandoned"


def test_the_real_client_cancelled_during_a_name_lookup_does_not_wait_for_it(tmp_path, monkeypatch, capsys):
    """aiohttp's resolver is a blocking ``getaddrinfo`` on the loop's executor, and no Python can interrupt it. Cancel does not
    wait for it, the log says it is still out there, and its thread ends when the lookup does."""
    import edge_tts.communicate as client_module

    release = threading.Event()
    entered = threading.Event()

    def blocked_lookup(*_arguments, **_options):
        entered.set()
        release.wait(WAIT)
        raise socket.gaierror("released by the test")

    monkeypatch.setattr(client_module, "WSS_URL", "ws://act-test.invalid/edge?x=1")
    monkeypatch.setattr(socket, "getaddrinfo", blocked_lookup)
    try:
        ended, end, after_cancel, target = _real_request(tmp_path)
        assert entered.is_set(), "the client never reached the lookup"
        assert ended and isinstance(end, ConversionCancelled), end
        assert after_cancel < REQUEST_LIMIT, f"{after_cancel:.2f} s"
        assert not target.exists()
        assert "still waiting" in capsys.readouterr().out
    finally:
        release.set()


# --------------------------------------------------------------------------- the local engines and the panel


@pytest.fixture
def fake_kokoro(monkeypatch):
    import numpy as np
    import tts.kokoro_synth as ks

    calls: list[str] = []

    class Pipeline:
        def __call__(self, text, voice=None, speed=1.0, split_pattern=None):
            calls.append(text)
            yield ("graphemes", "phonemes", (0.3 * np.sin(2 * np.pi * 220 * np.arange(6000) / 24000)).astype(np.float32))

    monkeypatch.setattr(ks, "_get_pipeline", lambda lang_code: Pipeline())
    return calls


def test_kokoro_stops_before_its_one_encode_when_cancelled_after_the_last_chunk(tmp_path, fake_kokoro):
    """The model has rendered everything; the Cancel lands before the encode: nothing is written."""
    import tts.kokoro_synth as ks

    source = tmp_path / "k.txt"
    source.write_text("Words to read aloud.", encoding="utf-8")
    out = tmp_path / "k.mp3"
    with pytest.raises(ConversionCancelled):
        ks.kokoro_file_to_mp3(str(source), str(out), voice_id="af_heart", log=lambda s: None,
                              cancel_check=lambda: bool(fake_kokoro))  # latched once the model has been asked
    assert fake_kokoro and not out.exists()


def test_the_local_engine_routes_run_under_the_runs_cancel_control(monkeypatch):
    """Kokoro and Chatterbox encode through pydub; inside the control block that encode answers to the run's Cancel."""
    from tts import epub2tts_gui as panel_module

    seen: dict = {}

    def fake_local(item, params, log, synthesize, cancel_check=None):
        seen["control"] = ffmpeg_watch.current_cancel_check()
        seen["passed"] = cancel_check

    monkeypatch.setattr(panel_module, "_convert_with_local_engine", fake_local)

    def check() -> bool:
        return False

    params = {"voice_id": "v", "kokoro_speed": 1.0, "end_pause": 0, "paragraph_pause": 50, "bitrate": "192k"}
    item = {"source": Path("x.txt"), "destination": Path("y.mp3")}
    for convert in (panel_module.convert_with_kokoro, panel_module.convert_with_chatterbox):
        seen.clear()
        convert(item, params, None, lambda s: None, check)
        assert seen["control"] is check and seen["passed"] is check, convert.__name__
    assert ffmpeg_watch.current_cancel_check() is None, "the control is released with the block"


def test_the_qwen3_route_hands_its_cancel_check_to_publication(monkeypatch):
    """Qwen3 stops its own worker and encoder; the shared publication step at the end still has to answer to Cancel. The review
    candidate called it without the check, so a Cancel after the encode could not stop that file being published at all."""
    from tts import epub2tts_gui as panel_module

    seen: dict = {}

    def fake_local(item, params, log, synthesize, cancel_check=None):
        seen["passed"] = cancel_check

    monkeypatch.setattr(panel_module, "_convert_with_local_engine", fake_local)

    def check() -> bool:
        return False

    panel_module.convert_with_qwen3({"source": Path("x.txt"), "destination": Path("y.mp3"), "item_id": "i"},
                                    {"voice_id": "v", "end_pause": 0, "paragraph_pause": 50, "bitrate": "192k"},
                                    None, lambda s: None, check)
    assert seen["passed"] is check


def test_the_panels_cancel_wakes_the_watchdog_and_the_gate():
    """Pressing Cancel does not wait for anybody's next poll: the panel wakes the FFmpeg watchdog and the memory gate."""
    import source_probe

    cancel_job = source_probe.function("tts/epub2tts_gui.py", "cancel_job")
    called = source_probe.calls(cancel_job)
    assert {"request_cancel", "wake"} <= called
    assert source_probe.call_order(cancel_job, {"request_cancel", "wake"}) == ["request_cancel", "wake", "wake"], \
        "the latch first, then both wakes"


def test_the_folder_request_is_abandoned_on_cancel_too(monkeypatch, tmp_path):
    from tts import batch_convert

    cancelled = threading.Event()
    abandoned = []

    class SlowCommunicate:
        def __init__(self, text, voice, rate):
            pass

        async def save(self, path):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                abandoned.append(True)
                raise

    monkeypatch.setattr(batch_convert.edge_tts, "Communicate", SlowCommunicate)
    threading.Timer(0.2, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        batch_convert.synthesize_chunk_mp3("Hello.", str(tmp_path / "c.mp3"), "v", "+0%", cancel_check=cancelled.is_set)
    assert abandoned == [True] and time.monotonic() - started < 3
