"""The cooperative run controller — v0.6.0 Drop 3 (Plan 3), Phase 5.

**No test sleeps, and none waits on a wall clock.** Every race here is *arranged*:
a stand-in worker is parked at a checkpoint, a barrier releases two threads at the
same instant, and the controller's own listener seam tells the test when a state has
actually been reached. Every wait carries a short explanatory timeout, so a deadlock
fails the test loudly instead of hanging the suite.

Nothing here reads a disk, starts a subprocess, opens a display, or converts
anything. The controller has no filesystem to touch; these tests give it none.

Two private members are used deliberately. ``_set_locked`` is the authority under
test in the exhaustive transition proof, and driving a controller into a state
through it — only ever by legal moves — is how the setup avoids needing a thread per
state. ``_condition`` is wrapped in one test to prove the pause wait is a real
condition wait and not a poll. Both are called out where they appear.
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

from shared import cancellation, import_coordination, job_control
from shared.cancellation import ConversionCancelled, is_cancelled, raise_if_cancelled
from shared.import_coordination import ImportCancellation
from shared.job_control import (
    INPUT_LOCKED_STATES,
    LEGAL_TRANSITIONS,
    MAX_FAILURE_DETAIL,
    TERMINAL_STATES,
    IllegalJobTransition,
    JobContractError,
    JobController,
    JobSnapshot,
    JobState,
)

#: Every wait in this file is bounded so a deadlock fails rather than hangs. It is
#: never used to *create* a race, only to refuse to wait forever for one.
WAIT = 5.0

SHARED = Path(__file__).resolve().parent.parent.parent / "scripts" / "Universal" / "shared"


# --------------------------------------------------------------------------- #
# Deterministic helpers
# --------------------------------------------------------------------------- #


class StateWatcher:
    """Records every snapshot the controller dispatches and lets a test await one.

    This is the controller's own listener seam, which is what makes "wait until the
    worker has actually acknowledged the pause" expressible without polling. The
    history check and the event registration happen in one critical section, so a
    state reached just before a test asks about it cannot be missed.
    """

    def __init__(self) -> None:
        self.snapshots: list[JobSnapshot] = []
        self._lock = threading.Lock()
        self._events: dict[JobState, threading.Event] = {}
        self.reentrant_reads: list[JobState] = []
        self.reenter = False

    def __call__(self, snapshot: JobSnapshot) -> None:
        if self.reenter:
            # Proves the listener is not called while the controller's lock is held:
            # a non-reentrant lock would deadlock here rather than answer.
            self.reentrant_reads.append(snapshot.state)
        with self._lock:
            self.snapshots.append(snapshot)
            event = self._events.get(snapshot.state)
        if event is not None:
            event.set()

    def wait_for(self, state: JobState, timeout: float = WAIT) -> bool:
        with self._lock:
            if any(entry.state is state for entry in self.snapshots):
                return True
            event = self._events.setdefault(state, threading.Event())
        return event.wait(timeout)

    def forget(self, state: JobState) -> None:
        """Re-arm for a state that has already been seen once."""
        with self._lock:
            self.snapshots = [
                entry for entry in self.snapshots if entry.state is not state]
            self._events.pop(state, None)

    @property
    def states(self) -> list[JobState]:
        return [entry.state for entry in self.snapshots]


class Worker:
    """A stand-in conversion worker: it calls a checkpoint and records what happened.

    Deliberately minimal. It converts nothing, writes nothing and sleeps never; the
    only thing under test is what the controller does when a worker arrives at its
    cooperative boundary.
    """

    def __init__(
        self,
        controller: JobController,
        *,
        checkpoints: int = 1,
        gates: list[threading.Event] | None = None,
    ) -> None:
        self.controller = controller
        self.checkpoints = checkpoints
        #: One optional gate per checkpoint. A closed gate holds the worker *before*
        #: it reaches that checkpoint, which is how a test arranges "the command
        #: landed first" without guessing at timing.
        self.gates = gates or []
        self.entered = threading.Event()
        self.returned = threading.Event()
        self.cancelled = threading.Event()
        self.passes = 0
        self.error: BaseException | None = None
        self.thread: threading.Thread | None = None

    def _body(self) -> None:
        self.entered.set()
        try:
            for index in range(self.checkpoints):
                if index < len(self.gates):
                    assert self.gates[index].wait(WAIT), "the test never opened the gate"
                self.controller.checkpoint()
                self.passes += 1
            self.returned.set()
        except ConversionCancelled:
            self.cancelled.set()
        except BaseException as exc:  # noqa: BLE001 - recorded so the test can assert
            self.error = exc

    def start(self) -> "Worker":
        self.thread = threading.Thread(target=self._body, name="job-worker", daemon=False)
        self.thread.start()
        assert self.entered.wait(WAIT), "the worker thread never ran"
        return self

    def join(self, timeout: float = WAIT) -> "Worker":
        assert self.thread is not None
        self.thread.join(timeout)
        assert not self.thread.is_alive(), "the worker did not finish"
        if self.error is not None:
            raise self.error
        return self

    @property
    def alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


def controller(run_id: str = "run-1", *, listener=None) -> JobController:
    return JobController(run_id, listener=listener)


def watched(run_id: str = "run-1") -> tuple[JobController, StateWatcher]:
    watcher = StateWatcher()
    return JobController(run_id, listener=watcher), watcher


def force(target: JobController, *states: JobState) -> JobController:
    """Drive a controller into a state through the authority itself.

    Only legal moves are ever passed here — the point is to set up a state without
    needing a live worker for it, not to bypass the table. ``_set_locked`` requires
    the lock, exactly as every real caller does.

    The companion flags are set alongside, because the controller's own snapshot
    invariants refuse an inconsistent run: ``CANCEL_REQUESTED`` without the request
    flag, ``CANCELLED`` without an acknowledgement, or ``FAILED`` without a reason
    are all states the real API can never produce, so the setup must not either.
    """
    for state in states:
        with target._condition:
            if state in (JobState.CANCEL_REQUESTED, JobState.CANCELLED):
                target._cancel_requested = True
            if state is JobState.CANCELLED:
                target._cancel_acknowledged = True
            if state is JobState.FAILED:
                target._failure_message = "It failed."
            target._set_locked(state)
    return target


def paused_worker(
    run_id: str = "run-1") -> tuple[JobController, StateWatcher, Worker]:
    """A controller whose worker has genuinely acknowledged a pause.

    The pause is requested *before* the worker is released to its checkpoint, which
    is the real sequence — a UI asks, and the worker acknowledges when it next
    arrives — and is the only version of it that is deterministic. Starting the
    worker first would race: a checkpoint reached before the request simply returns.
    """
    job, watcher = watched(run_id)
    job.start()
    job.request_pause()
    worker = Worker(job).start()
    assert watcher.wait_for(JobState.PAUSED), "the worker never acknowledged the pause"
    return job, watcher, worker


# --------------------------------------------------------------------------- #
# The snapshot
# --------------------------------------------------------------------------- #


def test_a_fresh_controller_is_idle_and_describes_itself_honestly():
    job = controller()
    snapshot = job.snapshot()
    assert snapshot.run_id == "run-1"
    assert snapshot.state is JobState.IDLE
    assert snapshot.revision == 0
    assert not snapshot.pause_requested
    assert not snapshot.cancel_requested
    assert not snapshot.cancel_acknowledged
    assert snapshot.failure_message == "" and snapshot.failure_detail == ""
    assert not snapshot.is_terminal and not snapshot.is_running
    assert not snapshot.inputs_locked


def test_a_snapshot_is_immutable_and_slotted():
    snapshot = controller().snapshot()
    with pytest.raises(Exception):
        snapshot.state = JobState.RUNNING
    with pytest.raises(Exception):
        snapshot.invented = True
    assert not hasattr(snapshot, "__dict__"), "slots, so no attribute can be added"
    assert snapshot.state is JobState.IDLE


def test_a_snapshot_exposes_no_lock_condition_event_or_callback():
    job, _watcher = watched()
    job.start()
    snapshot = job.snapshot()
    for value in (
        snapshot.run_id, snapshot.state, snapshot.revision, snapshot.pause_requested,
        snapshot.cancel_requested, snapshot.cancel_acknowledged,
        snapshot.failure_message, snapshot.failure_detail,
    ):
        assert isinstance(value, (str, bool, int, JobState)), value
    for forbidden in ("_lock", "_condition", "_listener", "_controller"):
        assert not hasattr(snapshot, forbidden), forbidden


@pytest.mark.parametrize(
    "state", [JobState.PAUSE_REQUESTED, JobState.PAUSED])
def test_pause_requested_must_match_the_state(state):
    with pytest.raises(JobContractError, match="pause_requested must be True"):
        JobSnapshot(run_id="r", state=state, pause_requested=False)


def test_pause_requested_may_not_be_claimed_in_another_state():
    with pytest.raises(JobContractError, match="pause_requested must be False"):
        JobSnapshot(run_id="r", state=JobState.RUNNING, pause_requested=True)


def test_an_acknowledgement_without_a_request_is_impossible():
    with pytest.raises(JobContractError, match="without having been requested"):
        JobSnapshot(run_id="r", state=JobState.RUNNING, cancel_acknowledged=True)


def test_cancelled_requires_a_real_acknowledgement():
    with pytest.raises(JobContractError, match="requesting cancellation is not"):
        JobSnapshot(
            run_id="r", state=JobState.CANCELLED, cancel_requested=True,
            cancel_acknowledged=False)


def test_cancel_requested_state_requires_the_flag():
    with pytest.raises(JobContractError, match="cancel_requested must be set"):
        JobSnapshot(run_id="r", state=JobState.CANCEL_REQUESTED)


def test_a_failed_run_must_say_why_and_others_may_not():
    with pytest.raises(JobContractError, match="must say why"):
        JobSnapshot(run_id="r", state=JobState.FAILED)
    with pytest.raises(JobContractError, match="carries no failure information"):
        JobSnapshot(run_id="r", state=JobState.SUCCEEDED, failure_message="broke")


def test_a_failure_message_stays_display_safe():
    for bad in ("broke\nbadly", "Traceback (most recent call last) boom"):
        with pytest.raises(JobContractError):
            JobSnapshot(run_id="r", state=JobState.FAILED, failure_message=bad)


def test_a_snapshot_refuses_a_blank_run_id_or_a_foreign_state():
    with pytest.raises(JobContractError, match="run_id"):
        JobSnapshot(run_id="  ", state=JobState.IDLE)
    with pytest.raises(JobContractError, match="must be a JobState"):
        JobSnapshot(run_id="r", state="running")
    with pytest.raises(JobContractError, match="revision"):
        JobSnapshot(run_id="r", state=JobState.IDLE, revision=-1)


def test_the_snapshot_properties_agree_with_the_frozen_vocabulary():
    for state in JobState:
        snapshot = JobSnapshot(
            run_id="r",
            state=state,
            pause_requested=state in (JobState.PAUSE_REQUESTED, JobState.PAUSED),
            cancel_requested=state in (JobState.CANCEL_REQUESTED, JobState.CANCELLED),
            cancel_acknowledged=state is JobState.CANCELLED,
            failure_message="It failed." if state is JobState.FAILED else "",
        )
        assert snapshot.is_terminal is (state in TERMINAL_STATES)
        assert snapshot.inputs_locked is (state in INPUT_LOCKED_STATES)
        assert snapshot.is_running is (state is JobState.RUNNING)
        assert snapshot.is_paused is (state is JobState.PAUSED)
        assert snapshot.pause_pending is (state is JobState.PAUSE_REQUESTED)
        assert snapshot.cancelled is (state is JobState.CANCELLED)
        assert snapshot.failed is (state is JobState.FAILED)
        assert snapshot.succeeded is (
            state in (JobState.SUCCEEDED, JobState.COMPLETED_WITH_FAILURES))


# --------------------------------------------------------------------------- #
# The state model
# --------------------------------------------------------------------------- #


def test_starting_moves_to_running_and_advances_the_revision():
    job = controller()
    snapshot = job.start()
    assert snapshot.state is JobState.RUNNING
    assert snapshot.revision == 1
    assert job.is_running


def test_starting_twice_is_refused_rather_than_ignored():
    job = controller()
    job.start()
    with pytest.raises(IllegalJobTransition, match="running -> running"):
        job.start()
    assert job.state is JobState.RUNNING


def test_a_terminal_run_can_never_be_started_again():
    job = controller()
    job.start()
    job.succeed()
    with pytest.raises(IllegalJobTransition):
        job.start()
    assert job.state is JobState.SUCCEEDED


@pytest.mark.parametrize("current", list(JobState), ids=lambda s: s.value)
@pytest.mark.parametrize("proposed", list(JobState), ids=lambda s: s.value)
def test_the_controller_never_bypasses_the_frozen_transition_table(current, proposed):
    """Exhaustive over all eighty-one pairs, through the controller's own authority.

    Phase 1 proved the *table* is right. This proves the controller cannot get
    around it: the one method that assigns the state consults the table first, so a
    move that is not in it raises no matter which command asked for it.
    """
    job = controller()
    reachable = {
        JobState.IDLE: (),
        JobState.RUNNING: (JobState.RUNNING,),
        JobState.PAUSE_REQUESTED: (JobState.RUNNING, JobState.PAUSE_REQUESTED),
        JobState.PAUSED: (JobState.RUNNING, JobState.PAUSE_REQUESTED, JobState.PAUSED),
        JobState.CANCEL_REQUESTED: (JobState.RUNNING, JobState.CANCEL_REQUESTED),
        JobState.CANCELLED: (
            JobState.RUNNING, JobState.CANCEL_REQUESTED, JobState.CANCELLED),
        JobState.SUCCEEDED: (JobState.RUNNING, JobState.SUCCEEDED),
        JobState.COMPLETED_WITH_FAILURES: (
            JobState.RUNNING, JobState.COMPLETED_WITH_FAILURES),
        JobState.FAILED: (JobState.RUNNING, JobState.FAILED),
    }[current]
    force(job, *reachable)
    assert job.state is current

    legal = proposed in LEGAL_TRANSITIONS[current]
    if legal:
        with job._condition:
            job._set_locked(proposed)
        assert job.state is proposed
    else:
        with pytest.raises(IllegalJobTransition):
            with job._condition:
                job._set_locked(proposed)
        assert job.state is current, "a refused move changes nothing"


def test_only_one_method_in_the_module_assigns_the_state():
    """Structural: an illegal change cannot reach the attribute by a side door."""
    tree = ast.parse((SHARED / "job_control.py").read_text(encoding="utf-8"))
    assigning: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            targets = (
                inner.targets if isinstance(inner, ast.Assign)
                else [inner.target] if isinstance(inner, (ast.AnnAssign, ast.AugAssign))
                else []
            )
            for target in targets:
                if (isinstance(target, ast.Attribute) and target.attr == "_state"
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"):
                    assigning.add(node.name)
    assert assigning == {"__init__", "_set_locked"}, assigning

    setter = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_set_locked")
    called = {
        inner.func.id for inner in ast.walk(setter)
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
    }
    assert "require_legal_transition" in called


def test_a_no_op_command_leaves_the_revision_alone():
    job = controller()
    job.start()
    job.request_pause()
    settled = job.revision

    for _ in range(3):
        job.request_pause()
    assert job.revision == settled, "asking twice for the same pause changes nothing"

    job.resume()
    running = job.revision
    for _ in range(3):
        job.resume()
    assert job.revision == running


def test_reading_a_snapshot_never_changes_anything():
    job = controller()
    job.start()
    before = job.snapshot()
    for _ in range(5):
        job.snapshot()
        job.state
        job.cancel_check()
    assert job.snapshot() == before
    assert job.revision == before.revision


def test_an_old_snapshot_keeps_describing_the_moment_it_was_taken():
    job = controller()
    job.start()
    running = job.snapshot()
    job.request_pause()
    job.request_cancel()

    assert running.state is JobState.RUNNING
    assert not running.cancel_requested
    assert running.revision == 1
    assert job.snapshot().state is JobState.CANCEL_REQUESTED


# --------------------------------------------------------------------------- #
# Pause and resume
# --------------------------------------------------------------------------- #


def test_a_pause_request_is_not_a_pause():
    """§6.10: `Pause requested` stays truthful until a worker acknowledges it."""
    job, watcher = watched()
    job.start()
    snapshot = job.request_pause()

    assert snapshot.state is JobState.PAUSE_REQUESTED
    assert snapshot.pause_pending and not snapshot.is_paused
    assert JobState.PAUSED not in watcher.states, "nobody has reached a checkpoint yet"


def test_a_pause_requested_during_an_indivisible_stage_stays_requested():
    """The stage runs to its end; only the next checkpoint may acknowledge."""
    job, watcher = watched()
    job.start()
    inside_stage = threading.Event()
    stage_may_finish = threading.Event()

    def body():
        inside_stage.set()
        assert stage_may_finish.wait(WAIT)   # the indivisible stage, arranged not timed
        job.checkpoint()

    thread = threading.Thread(target=body, name="indivisible", daemon=False)
    thread.start()
    assert inside_stage.wait(WAIT)

    job.request_pause()
    assert job.state is JobState.PAUSE_REQUESTED
    assert JobState.PAUSED not in watcher.states

    stage_may_finish.set()
    assert watcher.wait_for(JobState.PAUSED)
    assert job.state is JobState.PAUSED

    job.resume()
    thread.join(WAIT)
    assert not thread.is_alive()


def test_a_worker_acknowledges_the_pause_and_blocks_there():
    job, _watcher, worker = paused_worker()
    assert job.state is JobState.PAUSED
    assert job.snapshot().is_paused
    assert worker.alive, "the checkpoint is holding the worker"
    assert not worker.returned.is_set()

    job.resume()
    worker.join()
    assert worker.returned.is_set()
    assert worker.passes == 1
    assert job.state is JobState.RUNNING


def test_the_pause_wait_is_a_condition_wait_and_never_a_poll():
    """No busy-spin, proved rather than asserted: one wait, and no timeout on it."""
    job, watcher = watched()
    job.start()
    original = job._condition.wait
    waits: list = []

    def counting_wait(timeout=None):
        waits.append(timeout)
        return original()

    job._condition.wait = counting_wait      # the second deliberate private reach
    job.request_pause()
    worker = Worker(job).start()
    assert watcher.wait_for(JobState.PAUSED)
    job.resume()
    worker.join()

    assert waits == [None], (
        "the worker waited exactly once, with no timeout — it was woken, not polled")


def test_the_lock_is_released_while_a_worker_waits():
    """Every command and every read still works while the worker sleeps."""
    job, _watcher, worker = paused_worker()

    assert job.snapshot().state is JobState.PAUSED
    assert job.state is JobState.PAUSED
    assert job.revision >= 3
    assert job.cancel_check() is False
    assert job.request_pause().state is JobState.PAUSED   # idempotent, not blocked

    job.resume()
    worker.join()


def test_a_spurious_wake_up_leaves_the_worker_paused():
    job, watcher, worker = paused_worker()

    for _ in range(3):
        with job._condition:
            job._condition.notify_all()      # nothing changed; a bare wake-up
    assert job.state is JobState.PAUSED
    assert worker.alive, "re-checking found it still paused, so it waited again"
    assert not worker.returned.is_set()

    job.resume()
    worker.join()
    assert worker.returned.is_set()


def test_resume_before_acknowledgement_means_the_worker_never_pauses():
    job, watcher = watched()
    job.start()
    job.request_pause()
    job.resume()
    assert job.state is JobState.RUNNING

    worker = Worker(job).start()
    worker.join()
    assert worker.returned.is_set()
    assert JobState.PAUSED not in watcher.states


def test_several_checkpoints_pause_and_release_deterministically():
    """Three pauses in a row, each one arranged rather than raced for."""
    job, watcher = watched()
    job.start()
    gates = [threading.Event() for _ in range(3)]
    worker = Worker(job, checkpoints=3, gates=gates).start()

    for gate in gates:
        job.request_pause()
        assert job.state is JobState.PAUSE_REQUESTED
        gate.set()                           # release the worker to this checkpoint
        assert watcher.wait_for(JobState.PAUSED)
        assert job.state is JobState.PAUSED
        job.resume()
        # Re-arm the watcher so the next pause is awaited afresh rather than
        # satisfied by the one that just happened.
        watcher.forget(JobState.PAUSED)

    worker.join()
    assert worker.passes == 3
    assert job.state is JobState.RUNNING


@pytest.mark.parametrize(
    "setup, expected",
    [
        ((), JobState.IDLE),
        ((JobState.RUNNING, JobState.SUCCEEDED), JobState.SUCCEEDED),
        ((JobState.RUNNING, JobState.FAILED), JobState.FAILED),
        ((JobState.RUNNING, JobState.CANCEL_REQUESTED), JobState.CANCEL_REQUESTED),
    ],
)
def test_pausing_where_pause_means_nothing_is_inert(setup, expected):
    """A disabled button should do nothing, not raise in a user's face."""
    job = force(controller(), *setup)
    before = job.revision
    snapshot = job.request_pause()
    assert snapshot.state is expected
    assert job.revision == before


@pytest.mark.parametrize(
    "setup, expected",
    [
        ((), JobState.IDLE),
        ((JobState.RUNNING,), JobState.RUNNING),
        ((JobState.RUNNING, JobState.CANCEL_REQUESTED), JobState.CANCEL_REQUESTED),
        ((JobState.RUNNING, JobState.SUCCEEDED), JobState.SUCCEEDED),
        ((JobState.RUNNING, JobState.CANCEL_REQUESTED, JobState.CANCELLED),
         JobState.CANCELLED),
        ((JobState.RUNNING, JobState.FAILED), JobState.FAILED),
    ],
)
def test_resume_never_resurrects_work_that_is_not_paused(setup, expected):
    job = force(controller(), *setup)
    before = job.revision
    snapshot = job.resume()
    assert snapshot.state is expected
    assert job.revision == before


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #


def test_cancel_from_running_records_the_request_without_claiming_it_stopped():
    job = controller()
    job.start()
    snapshot = job.request_cancel()

    assert snapshot.state is JobState.CANCEL_REQUESTED
    assert snapshot.cancel_requested
    assert not snapshot.cancel_acknowledged, "nobody has observed it yet"
    assert job.cancel_check() is True


def test_a_checkpoint_raises_the_existing_conversion_exception():
    job = controller()
    job.start()
    job.request_cancel()

    with pytest.raises(ConversionCancelled) as excinfo:
        job.checkpoint()
    assert type(excinfo.value) is cancellation.ConversionCancelled
    assert str(excinfo.value) == "Cancelled."
    assert job.cancel_acknowledged


def test_cancel_wakes_a_paused_worker():
    job, watcher, worker = paused_worker()
    assert worker.alive

    job.request_cancel()
    worker.join()

    assert worker.cancelled.is_set(), "the paused worker woke, saw the cancel, and raised"
    assert not worker.returned.is_set()
    assert job.cancel_acknowledged
    assert job.state is JobState.CANCEL_REQUESTED


def test_cancel_outranks_a_pending_pause():
    job, watcher = watched()
    job.start()
    job.request_pause()
    job.request_cancel()
    assert job.state is JobState.CANCEL_REQUESTED

    worker = Worker(job).start()
    worker.join()
    assert worker.cancelled.is_set()
    assert JobState.PAUSED not in watcher.states, "it never paused; cancel came first"


def test_cancel_before_the_run_starts_is_remembered_not_lost():
    job = controller()
    snapshot = job.request_cancel()

    assert snapshot.state is JobState.IDLE, "there is nothing running to cancel yet"
    assert snapshot.cancel_requested
    assert job.cancel_check() is True

    job.start()
    worker = Worker(job).start()
    worker.join()
    assert worker.cancelled.is_set(), "the first checkpoint honoured it"
    assert job.state is JobState.CANCEL_REQUESTED
    assert job.cancel_acknowledged


def test_repeated_cancel_requests_change_nothing_after_the_first():
    job = controller()
    job.start()
    job.request_cancel()
    settled = job.revision

    for _ in range(3):
        job.request_cancel()
    assert job.revision == settled
    assert job.state is JobState.CANCEL_REQUESTED


@pytest.mark.parametrize(
    "ending", [JobState.SUCCEEDED, JobState.COMPLETED_WITH_FAILURES, JobState.FAILED])
def test_cancel_after_a_run_ended_does_nothing_at_all(ending):
    """A finished run must not start describing itself as cancelled."""
    job = force(controller(), JobState.RUNNING, ending)
    before = job.revision

    snapshot = job.request_cancel()

    assert snapshot.state is ending
    assert not snapshot.cancel_requested
    assert job.cancel_check() is False
    assert job.revision == before


def test_cancel_after_a_cancelled_run_is_inert():
    job = controller()
    job.start()
    job.request_cancel()
    with pytest.raises(ConversionCancelled):
        job.checkpoint()
    job.finish_cancelled()
    before = job.revision

    job.request_cancel()
    assert job.state is JobState.CANCELLED
    assert job.revision == before


def test_cancel_after_a_resume_still_works():
    job, watcher, worker = paused_worker()
    job.resume()
    worker.join()
    assert worker.returned.is_set()

    job.request_cancel()
    second = Worker(job).start()
    second.join()
    assert second.cancelled.is_set()


def test_a_checkpoint_after_a_terminal_state_is_not_an_error():
    for ending in (JobState.SUCCEEDED, JobState.COMPLETED_WITH_FAILURES, JobState.FAILED):
        job = force(controller(), JobState.RUNNING, ending)
        job.checkpoint()          # the run is over; asking again is harmless
        assert job.state is ending


def test_two_controllers_never_touch_each_other():
    first, second = controller("run-a"), controller("run-b")
    first.start()
    second.start()

    first.request_cancel()

    assert first.cancel_check() is True
    assert second.cancel_check() is False
    assert second.state is JobState.RUNNING
    second.checkpoint()           # returns immediately; it was never cancelled
    assert first.run_id != second.run_id


def test_cancellation_is_visible_immediately_to_another_thread():
    job = controller()
    job.start()
    seen: list[bool] = []
    ready = threading.Barrier(2, timeout=WAIT)

    def reader():
        ready.wait()
        seen.append(job.cancel_check())

    thread = threading.Thread(target=reader, name="reader", daemon=False)
    thread.start()
    job.request_cancel()
    ready.wait()
    thread.join(WAIT)

    assert not thread.is_alive()
    assert seen == [True], "the request was published before the barrier released"


# --------------------------------------------------------------------------- #
# Acknowledgement
# --------------------------------------------------------------------------- #


def test_requesting_a_cancel_never_fabricates_an_acknowledgement():
    job = controller()
    job.start()
    job.request_cancel()
    assert not job.cancel_acknowledged
    assert not job.snapshot().cancel_acknowledged


def test_the_acknowledgement_happens_where_the_worker_observes_it():
    job, watcher = watched()
    job.start()
    job.request_cancel()
    assert not job.cancel_acknowledged

    worker = Worker(job).start()
    worker.join()

    assert job.cancel_acknowledged
    acknowledged = [entry for entry in watcher.snapshots if entry.cancel_acknowledged]
    assert acknowledged, "the acknowledgement was published"
    assert acknowledged[0].run_id == "run-1"


def test_the_acknowledgement_happens_at_most_once_per_run():
    job, watcher = watched()
    job.start()
    job.request_cancel()

    for _ in range(4):
        with pytest.raises(ConversionCancelled):
            job.checkpoint()

    first_ack = min(
        index for index, entry in enumerate(watcher.snapshots)
        if entry.cancel_acknowledged)
    revisions = {
        entry.revision for entry in watcher.snapshots[first_ack:]}
    assert len(revisions) == 1, (
        "repeated checkpoints re-raise but never re-acknowledge, so nothing moved")
    assert job.cancel_acknowledged


def test_a_run_may_not_be_reported_cancelled_without_acknowledgement():
    job = controller()
    job.start()
    job.request_cancel()

    with pytest.raises(JobContractError, match="has not acknowledged cancellation"):
        job.finish_cancelled()
    assert job.state is JobState.CANCEL_REQUESTED, "the refused settle changed nothing"


def test_settling_cancelled_after_acknowledgement_and_cleanup():
    job = controller()
    job.start()
    job.request_cancel()
    cleanup_ran = []
    try:
        job.checkpoint()
    except ConversionCancelled:
        cleanup_ran.append("worker cleanup")
        snapshot = job.finish_cancelled()

    assert cleanup_ran == ["worker cleanup"]
    assert snapshot.state is JobState.CANCELLED
    assert snapshot.cancelled and snapshot.is_terminal
    assert snapshot.cancel_acknowledged


def test_completion_cannot_overwrite_an_acknowledged_cancellation():
    job = controller()
    job.start()
    job.request_cancel()
    with pytest.raises(ConversionCancelled):
        job.checkpoint()
    job.finish_cancelled()

    for settle in (job.succeed, job.complete_with_failures, job.finish_cancelled):
        with pytest.raises(IllegalJobTransition):
            settle()
    with pytest.raises(IllegalJobTransition):
        job.fail("Too late.")
    assert job.state is JobState.CANCELLED


def test_a_run_that_finished_before_the_checkpoint_reports_the_truth():
    """§6.10 and the Phase 1 table: cancel is a request, not a rewrite of history."""
    job = controller()
    job.start()
    job.request_cancel()
    snapshot = job.succeed()      # the work genuinely completed first

    assert snapshot.state is JobState.SUCCEEDED
    assert snapshot.cancel_requested
    assert not snapshot.cancel_acknowledged


# --------------------------------------------------------------------------- #
# Failure and completion
# --------------------------------------------------------------------------- #


def test_a_successful_run_settles_once():
    job = controller()
    job.start()
    snapshot = job.succeed()
    assert snapshot.state is JobState.SUCCEEDED
    assert snapshot.succeeded and snapshot.is_terminal
    with pytest.raises(IllegalJobTransition):
        job.succeed()


def test_completed_with_failures_is_a_distinct_ending():
    job = controller()
    job.start()
    snapshot = job.complete_with_failures()
    assert snapshot.state is JobState.COMPLETED_WITH_FAILURES
    assert snapshot.succeeded, "it finished; some items did not"
    assert snapshot.is_terminal


def test_a_failure_keeps_the_sentence_and_the_diagnostics_apart():
    job = controller()
    job.start()
    snapshot = job.fail("The conversion failed.", "RuntimeError: ffmpeg exited 1")

    assert snapshot.state is JobState.FAILED
    assert snapshot.failure_message == "The conversion failed."
    assert snapshot.failure_detail == "RuntimeError: ffmpeg exited 1"
    assert snapshot.failed and snapshot.is_terminal


def test_a_failure_refuses_the_exception_object_itself():
    job = controller()
    job.start()
    with pytest.raises(JobContractError, match="not the exception object"):
        job.fail("It broke.", RuntimeError("boom"))
    assert job.state is JobState.RUNNING, "a refused failure leaves the run alone"


def test_a_failure_message_is_validated_before_the_state_moves():
    job = controller()
    job.start()
    for bad in ("", "two\nlines", "Traceback (most recent call last) x"):
        with pytest.raises(JobContractError):
            job.fail(bad, "detail")
        assert job.state is JobState.RUNNING
    assert job.revision == 1


def test_an_over_long_detail_is_bounded_rather_than_refused():
    job = controller()
    job.start()
    snapshot = job.fail("It broke.", "x" * (MAX_FAILURE_DETAIL * 3))
    assert len(snapshot.failure_detail) == MAX_FAILURE_DETAIL
    assert snapshot.failure_detail.endswith("…")


def test_a_detail_must_be_text():
    job = controller()
    job.start()
    with pytest.raises(JobContractError, match="must be a string"):
        job.fail("It broke.", 42)


@pytest.mark.parametrize(
    "first, second",
    [
        ("succeed", "fail"),
        ("fail", "succeed"),
        ("succeed", "complete_with_failures"),
        ("complete_with_failures", "fail"),
        ("fail", "fail"),
    ],
)
def test_one_terminal_result_wins_and_the_second_is_refused(first, second):
    job = controller()
    job.start()
    call = {
        "succeed": job.succeed,
        "complete_with_failures": job.complete_with_failures,
        "fail": lambda: job.fail("It broke."),
    }
    settled = call[first]().state
    with pytest.raises(IllegalJobTransition):
        call[second]()
    assert job.state is settled


def test_a_terminal_run_stops_accepting_commands_but_never_raises_on_a_button():
    job = controller()
    job.start()
    job.succeed()
    assert job.request_pause().state is JobState.SUCCEEDED
    assert job.resume().state is JobState.SUCCEEDED
    assert job.request_cancel().state is JobState.SUCCEEDED
    assert job.revision == 2


# --------------------------------------------------------------------------- #
# Concurrency
# --------------------------------------------------------------------------- #


def test_a_listener_is_never_called_while_the_lock_is_held():
    """The controller's lock is non-reentrant, so this would deadlock if it were."""
    watcher = StateWatcher()
    watcher.reenter = True
    job = JobController("run-1", listener=lambda snapshot: (
        watcher(snapshot), job.snapshot(), job.state, job.cancel_check()))
    job.start()
    job.request_pause()
    job.resume()

    assert watcher.reentrant_reads == [
        JobState.RUNNING, JobState.PAUSE_REQUESTED, JobState.RUNNING]


def test_a_listener_sees_every_state_change_in_order():
    job, watcher = watched()
    job.start()
    job.request_pause()
    worker = Worker(job).start()
    assert watcher.wait_for(JobState.PAUSED)
    job.request_cancel()
    worker.join()
    job.finish_cancelled()

    assert watcher.states == [
        JobState.RUNNING,
        JobState.PAUSE_REQUESTED,
        JobState.PAUSED,
        JobState.CANCEL_REQUESTED,   # the request
        JobState.CANCEL_REQUESTED,   # the worker's acknowledgement
        JobState.CANCELLED,
    ]


def test_a_pause_and_a_resume_racing_leave_a_consistent_state():
    job, watcher = watched()
    job.start()
    gate = threading.Event()
    worker = Worker(job, gates=[gate]).start()
    ready = threading.Barrier(3, timeout=WAIT)

    def pause():
        ready.wait()
        job.request_pause()

    def resume():
        ready.wait()
        job.resume()

    threads = [
        threading.Thread(target=pause, name="pause", daemon=False),
        threading.Thread(target=resume, name="resume", daemon=False),
    ]
    for thread in threads:
        thread.start()
    ready.wait()
    for thread in threads:
        thread.join(WAIT)
        assert not thread.is_alive()

    assert job.state in (JobState.RUNNING, JobState.PAUSE_REQUESTED)
    job.resume()                       # whichever won, this settles it
    assert job.state is JobState.RUNNING
    gate.set()
    worker.join()
    assert worker.returned.is_set()
    assert job.state is JobState.RUNNING


def test_a_pause_and_a_cancel_racing_never_lose_the_cancel():
    job, watcher = watched()
    job.start()
    gate = threading.Event()
    worker = Worker(job, gates=[gate]).start()
    ready = threading.Barrier(3, timeout=WAIT)

    def pause():
        ready.wait()
        job.request_pause()

    def cancel():
        ready.wait()
        job.request_cancel()

    threads = [
        threading.Thread(target=pause, name="pause", daemon=False),
        threading.Thread(target=cancel, name="cancel", daemon=False),
    ]
    for thread in threads:
        thread.start()
    ready.wait()
    for thread in threads:
        thread.join(WAIT)
        assert not thread.is_alive()

    assert job.cancel_check() is True, "a cancel request is never dropped by a pause"
    gate.set()                          # only now does the worker reach its checkpoint
    worker.join()
    assert worker.cancelled.is_set(), "and the worker always ends up seeing it"


def test_a_resume_and_a_cancel_racing_still_stop_the_worker():
    job, watcher, worker = paused_worker()
    ready = threading.Barrier(3, timeout=WAIT)

    def resume():
        ready.wait()
        job.resume()

    def cancel():
        ready.wait()
        job.request_cancel()

    threads = [
        threading.Thread(target=resume, name="resume", daemon=False),
        threading.Thread(target=cancel, name="cancel", daemon=False),
    ]
    for thread in threads:
        thread.start()
    ready.wait()
    for thread in threads:
        thread.join(WAIT)

    worker.join()
    assert job.cancel_check() is True
    # Whether the worker woke before or after the cancel landed, it either raised or
    # returned once — never both, and never neither.
    assert worker.cancelled.is_set() != worker.returned.is_set()


def test_a_cancel_and_a_completion_racing_produce_exactly_one_winner():
    job = controller()
    job.start()
    job.request_cancel()
    with pytest.raises(ConversionCancelled):
        job.checkpoint()

    outcomes: list = []
    errors: list = []
    ready = threading.Barrier(3, timeout=WAIT)

    def settle(call):
        def body():
            ready.wait()
            try:
                outcomes.append(call().state)
            except IllegalJobTransition as exc:
                errors.append(exc)
        return body

    threads = [
        threading.Thread(target=settle(job.succeed), name="succeed", daemon=False),
        threading.Thread(target=settle(job.finish_cancelled), name="cancel", daemon=False),
    ]
    for thread in threads:
        thread.start()
    ready.wait()
    for thread in threads:
        thread.join(WAIT)
        assert not thread.is_alive()

    assert len(outcomes) == 1, outcomes
    assert len(errors) == 1
    assert job.state is outcomes[0]
    assert job.state in (JobState.SUCCEEDED, JobState.CANCELLED)


def test_snapshots_stay_readable_in_every_state():
    job, watcher, worker = paused_worker()
    assert job.snapshot().is_paused
    job.request_cancel()
    worker.join()
    assert job.snapshot().cancel_acknowledged
    job.finish_cancelled()
    assert job.snapshot().cancelled
    for entry in watcher.snapshots:
        assert isinstance(entry, JobSnapshot)


def test_a_whole_cooperative_run_neither_deadlocks_nor_leaks_a_thread():
    baseline = threading.active_count()
    job, watcher = watched("run-full")
    job.start()
    gates = [threading.Event(), threading.Event()]
    worker = Worker(job, checkpoints=2, gates=gates).start()

    job.request_pause()
    gates[0].set()
    assert watcher.wait_for(JobState.PAUSED)
    job.resume()
    job.request_cancel()
    gates[1].set()
    worker.join()
    job.finish_cancelled()

    assert job.state is JobState.CANCELLED
    assert threading.active_count() == baseline


# --------------------------------------------------------------------------- #
# Compatibility with the existing cancellation primitive
# --------------------------------------------------------------------------- #


def test_the_pre_existing_cancellation_api_behaves_exactly_as_before():
    assert issubclass(cancellation.ConversionCancelled, Exception)
    assert cancellation.raise_if_cancelled(None) is None
    assert cancellation.raise_if_cancelled(lambda: False) is None
    with pytest.raises(cancellation.ConversionCancelled) as excinfo:
        cancellation.raise_if_cancelled(lambda: True)
    assert str(excinfo.value) == "Cancelled."
    with pytest.raises(cancellation.ConversionCancelled) as excinfo:
        cancellation.raise_if_cancelled(lambda: True, "Stopped.")
    assert str(excinfo.value) == "Stopped."


def test_the_added_predicate_follows_the_same_none_convention():
    assert is_cancelled(None) is False
    assert is_cancelled(lambda: False) is False
    assert is_cancelled(lambda: True) is True
    assert is_cancelled(lambda: 1) is True, "the answer is always a real bool"
    assert isinstance(is_cancelled(lambda: 1), bool)


def test_a_worker_written_against_the_old_helper_works_with_a_controller():
    """The whole point of extending rather than replacing: no worker is rewritten."""
    job = controller()
    job.start()
    stages: list[str] = []

    def legacy_worker(cancel_check):
        for stage in ("probe", "convert", "tag"):
            raise_if_cancelled(cancel_check)
            stages.append(stage)
            if stage == "probe":
                job.request_cancel()

    with pytest.raises(ConversionCancelled):
        legacy_worker(job.cancel_check)
    assert stages == ["probe"]
    assert is_cancelled(job.cancel_check) is True


def test_a_bare_event_still_works_where_a_controller_would():
    """The old wiring — an Event's ``is_set`` — is still a valid cancel check."""
    event = threading.Event()
    assert is_cancelled(event.is_set) is False
    raise_if_cancelled(event.is_set)
    event.set()
    with pytest.raises(ConversionCancelled):
        raise_if_cancelled(event.is_set)


def test_cancelling_a_processing_job_leaves_an_import_untouched():
    """Phase 4's isolation, checked from the other side."""
    import_cancel = ImportCancellation()
    job = controller()
    job.start()

    job.request_cancel()
    with pytest.raises(ConversionCancelled):
        job.checkpoint()

    assert import_cancel.requested is False
    assert import_cancel() is False


def test_cancelling_an_import_leaves_a_processing_job_untouched():
    import_cancel = ImportCancellation()
    job = controller()
    job.start()

    import_cancel.request()

    assert job.cancel_check() is False
    assert job.state is JobState.RUNNING
    job.checkpoint()                    # returns; it was never cancelled
    assert job.succeed().state is JobState.SUCCEEDED


def test_pausing_a_processing_job_does_not_touch_an_import_flag():
    import_cancel = ImportCancellation()
    job, watcher, worker = paused_worker()

    assert import_cancel.requested is False
    job.resume()
    worker.join()
    assert import_cancel.requested is False


def test_the_two_cancellations_are_different_kinds_of_thing():
    import_cancel = ImportCancellation()
    job = controller()
    assert not isinstance(import_cancel, JobController)
    assert not hasattr(import_cancel, "checkpoint")
    assert not hasattr(import_cancel, "request_pause")
    assert not hasattr(job, "request")
    # The import module never learned about the processing primitive.
    assert not hasattr(import_coordination, "ConversionCancelled")
    assert not hasattr(import_coordination, "raise_if_cancelled")


def test_the_controller_neither_sleeps_nor_spins():
    text = (SHARED / "job_control.py").read_text(encoding="utf-8")
    for forbidden in ("time.sleep", "sleep(", "busy", "while True: pass"):
        assert forbidden not in text, forbidden
    assert "self._condition.wait()" in text, "the pause is a real condition wait"
    assert "notify_all()" in text


def test_the_controller_starts_no_thread_and_owns_no_queue():
    tree = ast.parse((SHARED / "job_control.py").read_text(encoding="utf-8"))
    constructed = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for primitive in ("Thread", "Timer", "Queue", "SimpleQueue", "ThreadPoolExecutor",
                      "ProcessPoolExecutor", "Pool", "Process", "Semaphore", "Barrier"):
        assert primitive not in constructed, primitive
    assert "Condition" in constructed and "Lock" in constructed


def test_the_run_identity_travels_with_every_snapshot():
    job, watcher = watched("run-xyz")
    job.start()
    job.request_cancel()
    with pytest.raises(ConversionCancelled):
        job.checkpoint()
    job.finish_cancelled()
    assert {entry.run_id for entry in watcher.snapshots} == {"run-xyz"}
    assert job.snapshot().run_id == "run-xyz"


def test_a_controller_needs_a_usable_run_id_and_a_callable_listener():
    with pytest.raises(JobContractError, match="run_id"):
        JobController("")
    with pytest.raises(JobContractError, match="run_id"):
        JobController("two words")
    with pytest.raises(JobContractError, match="listener must be callable"):
        JobController("run-1", listener="not callable")
