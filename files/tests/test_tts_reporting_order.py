"""TTS job reporting is deterministically ordered — v0.6.1 Plan 4, Phase 7 remediation.

The defect
----------
``JobReporter`` allocates an event's ``sequence`` under its own lock and then calls
the publisher with that lock **released**, because §5.4 of the shared contract
forbids holding a lock across caller code. Its own docstring states the rule that
follows: *one run reports from one producer*.

Phase 7's TTS panel had several. The Tk thread reports while a button moves the
controller; the conversion worker reports item progress, failures, the cancellation
acknowledgement and the terminal settlement; and every thread in the folder pool can
reach a checkpoint and dispatch a state change. So this schedule was possible::

    thread A   allocates sequence N     ... descheduled before publishing
    thread B   allocates sequence N + 1 ... publishes N + 1
    thread A                            ... publishes N

``JobEventStream`` accepts N + 1 and then refuses N as ``OUT_OF_ORDER`` rather than
filing it in the wrong place — so a legitimate state, progress, failure or terminal
report could become inert.

What these tests are about
--------------------------
* **One publication authority.** Every reporting call this panel makes goes through
  a single TTS-owned producer, and the authority is held across the *whole* of
  minting and publishing — so the order events enter the adapter's queue is the
  order their numbers were allocated.
* **The shared foundation is consumed, never re-implemented.** No second job state
  machine, no second event vocabulary, no re-sorting of accepted events, and
  ``OUT_OF_ORDER`` is left exactly as strict as it was.
* **A retired attempt cannot contaminate a retry.** A retry re-uses the original
  ``RunSnapshot`` and therefore the original run id, so a late report from the
  attempt being retried would otherwise be indistinguishable from a live one.

Determinism
-----------
**No test sleeps, and no test tunes a probability.** A producer is held at the real
queue boundary with a :class:`threading.Event`; exclusion is then proved by asking
the authority itself whether a publication is in flight, which needs no timing at
all. The one bounded window below is the opportunity a second producer is *given*
— never a wait for a race to happen — and the verdict comes from the recorded
arrival order either way.

Safety
------
Every fixture is generated under ``tmp_path`` and every engine entry point is
stubbed: no synthesis runs, nothing reaches the network, no model loads, and no
real audio is written.
"""

from __future__ import annotations

import ast
import threading

import pytest

tk = pytest.importorskip("tkinter")

from shared import job_control  # noqa: E402
from shared.job_control import EventVerdict, JobState  # noqa: E402

from tts import epub2tts_gui as panel_module  # noqa: E402

# The Phase 6 module owns "a TtsPanel built safely"; the Phase 7 module owns
# "a run accepted without starting a real thread". Reusing both keeps one
# description of each rather than three that drift.
from test_tts_importing import (  # noqa: E402,F401
    PANEL_SOURCE,
    WAIT,
    make_panel,
    output_base,
    panel_tree,
    sources,
    stubs,
    tk_root,
)
from test_tts_jobs import (  # noqa: E402,F401
    accept,
    direct_panel,
    failing_stubs,
    run_attempt,
    wait_for,
)

#: The opportunity a second producer is *given* while the first is held at the
#: queue. It is not a wait for a race to happen and it does not tune a
#: probability: before the remediation the second producer finishes inside it in
#: microseconds, after the remediation it cannot finish at all, and either way the
#: assertion is made against the arrival order that was actually recorded.
RACE_WINDOW = 0.25


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class QueueGate:
    """Holds the first event on its way into the adapter's queue.

    The seam is the queue's own ``put`` — the exact boundary the remediation is
    about, "enter the JobAdapter event queue" — so nothing here depends on how the
    panel arranges its producers, and the same test judges the code before and
    after the change.
    """

    def __init__(self, panel):
        self.queue = panel._event_q
        self._real = self.queue.put
        self.holding = threading.Event()
        self.release = threading.Event()
        self.second_arrived = threading.Event()
        self.arrivals: list[int] = []
        self.overlapped = False
        self._inside = 0
        self._lock = threading.Lock()
        self._first = True
        self.queue.put = self._put

    def _put(self, entry, *args, **kwargs):
        with self._lock:
            self._inside += 1
            if self._inside > 1:
                self.overlapped = True
            first, self._first = self._first, False
            if not first:
                self.second_arrived.set()
        try:
            if first:
                self.holding.set()
                assert self.release.wait(WAIT), "the queue gate was never released"
            with self._lock:
                self.arrivals.append(entry.sequence)
            return self._real(entry, *args, **kwargs)
        finally:
            with self._lock:
                self._inside -= 1

    def open(self) -> None:
        self.release.set()

    def restore(self) -> None:
        self.queue.put = self._real
        self.release.set()


def run_thread(call) -> threading.Thread:
    """Start one daemon thread that makes one reporting call."""
    thread = threading.Thread(target=call, daemon=True)
    thread.start()
    return thread


def join_all(*threads) -> None:
    for thread in threads:
        thread.join(WAIT)
        assert not thread.is_alive(), "a producer never finished"


def started_run(make_panel, tmp_path, *names):
    """A panel with one run accepted, its worker never started."""
    panel, _chosen = direct_panel(make_panel, tmp_path, *names)
    captured = accept(panel)
    assert captured, "the run was declined"
    return panel, captured["params"]


def publisher_of(params):
    """The one publication authority the worker was handed."""
    return params["publisher"]


def verdicts_of(panel) -> tuple:
    return tuple(panel.jobs.stream.rejected)


def sequences_of(panel) -> list[int]:
    return [entry.sequence for entry in panel.jobs.stream.events]


def class_named(name: str) -> ast.ClassDef:
    for node in panel_tree().body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in epub2tts_gui.py")


def code_of(name: str) -> str:
    """One class as source, with every docstring removed.

    A guard that reads prose is a guard that fails when the prose explains it.
    """
    node = class_named(name)
    stripped = ast.parse(ast.unparse(node)).body[0]
    for scope in [stripped, *(n for n in ast.walk(stripped)
                              if isinstance(n, (ast.FunctionDef, ast.ClassDef)))]:
        body = getattr(scope, "body", [])
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            if len(body) == 1:
                body[0] = ast.Pass()
            else:
                del body[0]
    return ast.unparse(ast.fix_missing_locations(stripped))


# --------------------------------------------------------------------------- #
# A. One publication authority, and the race it removes
# --------------------------------------------------------------------------- #


def test_the_run_hands_the_worker_one_publication_authority(
    make_panel, output_base, tmp_path, stubs
):
    """The worker reports through the panel's authority, not through a bare reporter."""
    panel, params = started_run(make_panel, tmp_path, "one.txt")

    publisher = publisher_of(params)
    assert isinstance(publisher, panel_module.RunPublisher)
    assert publisher is panel._publisher
    assert publisher.run_id == params["snapshot"].snapshot_id
    # The reporter itself is unreachable from the worker: there is no second way
    # to publish, so there is nothing for a producer to bypass the authority with.
    for key, value in params.items():
        assert not isinstance(value, job_control.JobReporter), key


def test_a_publication_in_flight_excludes_every_other_producer(
    make_panel, output_base, tmp_path, stubs
):
    """Minting and publishing are one indivisible step, not two.

    This needs no timing at all: while a producer is held *inside* the queue's
    ``put``, the authority is asked directly whether it is free. Before the
    remediation the reporter's lock covered the counter and nothing else, so it
    was; after it, it is not.
    """
    panel, params = started_run(make_panel, tmp_path, "one.txt")
    publisher = publisher_of(params)
    item = params["items"][0]["item_id"]
    gate = QueueGate(panel)
    try:
        worker = run_thread(
            lambda: publisher.progress(1, 2, item_id=item, stage="converting"))
        assert gate.holding.wait(WAIT), "no producer reached the queue"

        acquired = publisher.lock.acquire(blocking=False)
        if acquired:  # pragma: no cover - only on the pre-remediation code
            publisher.lock.release()
        assert not acquired, (
            "another producer could enter the reporter while an event of this run "
            "was still on its way to the queue")
    finally:
        gate.open()
        gate.restore()
    join_all(worker)


def test_no_event_reaches_the_queue_before_the_one_numbered_before_it(
    make_panel, output_base, tmp_path, stubs
):
    """The race, reproduced at the real delivery boundary.

    One producer is held on its way into the queue. A second is then given its
    chance. Before the remediation it takes the next number and overtakes, and the
    recorded arrival order is descending; after it, it cannot start at all until
    the first has finished, so the arrival order is the numbering order.
    """
    panel, params = started_run(make_panel, tmp_path, "one.txt", "two.txt")
    publisher = publisher_of(params)
    first_item = params["items"][0]["item_id"]
    second_item = params["items"][1]["item_id"]
    gate = QueueGate(panel)
    try:
        held = run_thread(
            lambda: publisher.progress(1, 2, item_id=first_item, stage="converting"))
        assert gate.holding.wait(WAIT), "no producer reached the queue"
        overtaker = run_thread(
            lambda: publisher.current_item(second_item, "Converting two.txt"))
        gate.second_arrived.wait(RACE_WINDOW)
        assert not gate.overlapped, (
            "two producers were inside the queue boundary at once")
        assert not gate.second_arrived.is_set(), (
            "a later-numbered event reached the queue while an earlier one was "
            f"still on its way: arrivals so far {gate.arrivals}")
    finally:
        gate.open()
        gate.restore()
    join_all(held, overtaker)

    assert gate.arrivals == sorted(gate.arrivals), (
        f"events reached the queue out of their numbered order: {gate.arrivals}")
    panel._pump.tick()
    assert sequences_of(panel) == sorted(sequences_of(panel))
    assert not verdicts_of(panel), "an event of this run was refused"


def test_the_authority_is_the_only_publisher_and_it_is_never_bypassed(
    make_panel, output_base, tmp_path, stubs
):
    """Structural: the panel keeps no second route from a producer to the queue."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    body = code_of("RunPublisher")

    # Everything that reaches the queue does so from inside the guarded region.
    assert "_event_q.put" not in code_of("TtsPanel"), (
        "the panel still puts events on the queue outside the authority")
    assert "with self._lock" in body
    # Nothing in the guarded region can be waiting on a lock that is waiting on it:
    # it calls one reporter and one queue, and never the controller or Tk.
    assert "controller" not in body.lower()
    assert "tk." not in body and "after(" not in body
    # No probability tuning, anywhere in the panel.
    assert "sleep(" not in source


# --------------------------------------------------------------------------- #
# B. A controller state racing a worker report
# --------------------------------------------------------------------------- #


def test_a_controller_state_and_a_worker_report_never_reorder(
    make_panel, output_base, tmp_path, stubs
):
    """The main thread moves the run while the worker reports. Both survive."""
    panel, params = started_run(make_panel, tmp_path, "one.txt")
    publisher = publisher_of(params)
    item = params["items"][0]["item_id"]
    gate = QueueGate(panel)
    try:
        held = run_thread(
            lambda: publisher.progress(1, 1, item_id=item, stage="converting"))
        assert gate.holding.wait(WAIT), "no producer reached the queue"
        # Exactly what a Pause press does on the Tk thread: the controller moves
        # and dispatches its listener, which reports the new state.
        mover = run_thread(panel.pause)
        gate.second_arrived.wait(RACE_WINDOW)
        assert not gate.second_arrived.is_set(), (
            f"the state report overtook the worker's: {gate.arrivals}")
    finally:
        gate.open()
        gate.restore()
    join_all(held, mover)

    panel._pump.tick()
    assert gate.arrivals == sorted(gate.arrivals)
    assert not verdicts_of(panel), "an event of this run was refused"
    states = [entry.state for entry in panel.jobs.stream.events
              if entry.state is not None]
    assert JobState.PAUSE_REQUESTED in states, "the pause the run really reached"


# --------------------------------------------------------------------------- #
# C. The terminal event
# --------------------------------------------------------------------------- #


def test_the_terminal_report_survives_a_racing_worker_report(
    make_panel, output_base, tmp_path, stubs
):
    """A run ends once, and a later-numbered event cannot make the ending inert."""
    panel, params = started_run(make_panel, tmp_path, "one.txt")
    publisher = publisher_of(params)
    controller = params["controller"]
    item = params["items"][0]["item_id"]
    gate = QueueGate(panel)
    try:
        held = run_thread(
            lambda: publisher.progress(1, 1, item_id=item, stage="converting"))
        assert gate.holding.wait(WAIT), "no producer reached the queue"
        ender = run_thread(lambda: publisher.completed(controller.succeed()))
        gate.second_arrived.wait(RACE_WINDOW)
        assert not gate.second_arrived.is_set(), (
            f"the ending overtook the report before it: {gate.arrivals}")
    finally:
        gate.open()
        gate.restore()
    join_all(held, ender)

    panel._pump.tick()
    stream = panel.jobs.stream
    assert gate.arrivals == sorted(gate.arrivals)
    assert stream.is_closed, "the run's one ending never reached the stream"
    assert stream.terminal.state is JobState.SUCCEEDED
    endings = [entry for entry in stream.events if entry.is_terminal]
    assert len(endings) == 1
    assert not [verdict for _entry, verdict in stream.rejected
                if verdict is EventVerdict.OUT_OF_ORDER]


# --------------------------------------------------------------------------- #
# D. Concurrent item reporting
# --------------------------------------------------------------------------- #


def test_every_concurrent_item_report_arrives_exactly_once(
    make_panel, output_base, tmp_path, stubs
):
    """What the folder pool does: several completions reporting at the same time."""
    panel, params = started_run(
        make_panel, tmp_path, "a.txt", "b.txt", "c.txt", "d.txt")
    publisher = publisher_of(params)
    items = [entry["item_id"] for entry in params["items"]]
    start = threading.Barrier(len(items))

    def report(index: int, item_id: str):
        def call():
            start.wait(WAIT)
            publisher.failure(f"{item_id} could not be converted.", "engine refused",
                              item_id=item_id, stage="converting")
            publisher.progress(index + 1, len(items), item_id=item_id,
                               stage="converting")
        return call

    threads = [run_thread(report(index, item_id))
               for index, item_id in enumerate(items)]
    join_all(*threads)

    panel._pump.tick()
    stream = panel.jobs.stream
    assert not stream.rejected, f"an event of this run was refused: {stream.rejected}"
    assert sequences_of(panel) == sorted(sequences_of(panel))
    reported = [entry.item_id for entry in stream.events
                if entry.kind is job_control.JobEventKind.FAILURE]
    assert sorted(reported) == sorted(items), "every failure arrived exactly once"


# --------------------------------------------------------------------------- #
# E. Pause and resume
# --------------------------------------------------------------------------- #


def test_a_report_racing_pause_and_resume_leaves_every_state_truthful(
    make_panel, output_base, tmp_path, stubs
):
    """Real transitions, raced against a worker report. No invented state."""
    panel, params = started_run(make_panel, tmp_path, "one.txt")
    publisher = publisher_of(params)
    controller = params["controller"]
    item = params["items"][0]["item_id"]
    start = threading.Barrier(2)

    def work():
        start.wait(WAIT)
        # Genuinely concurrent with the Pause press below.
        for done in range(1, 4):
            publisher.progress(done, 3, item_id=item, stage="converting")
        # Acknowledging the pause. This blocks in the controller until the resume
        # below wakes it — which is exactly what a paused worker does.
        controller.checkpoint()
        publisher.progress(3, 3, item_id=item, stage="converting")

    worker = run_thread(work)
    start.wait(WAIT)
    # Both presses stay on the Tk thread, because that is where they happen.
    panel.pause()
    wait_for(lambda: controller.state is JobState.PAUSED,
             "the worker never acknowledged the pause", panel=panel)
    panel.resume()
    join_all(worker)
    panel._pump.tick()

    stream = panel.jobs.stream
    assert not [verdict for _entry, verdict in stream.rejected
                if verdict is EventVerdict.OUT_OF_ORDER]
    assert sequences_of(panel) == sorted(sequences_of(panel))
    reachable = {JobState.RUNNING, JobState.PAUSE_REQUESTED, JobState.PAUSED}
    states = [entry.state for entry in stream.events if entry.state is not None]
    assert states, "the run's states were never reported"
    assert set(states) <= reachable, f"a state the run never reached: {states}"
    # What is drawn is where the controller actually is, never a state it left.
    assert panel.jobs.state is controller.state


def test_a_superseded_controller_state_is_never_drawn_as_the_current_one(
    make_panel, output_base, tmp_path, stubs
):
    """The controller dispatches with its lock released, so listeners can invert.

    A snapshot's revision is the controller's own monotonic counter. One older
    than the last already reported is dropped — not re-sorted, not re-timed, and
    nothing is invented in its place.
    """
    panel, params = started_run(make_panel, tmp_path, "one.txt")
    controller = params["controller"]
    running = controller.snapshot()
    assert running.state is JobState.RUNNING

    panel.pause()
    panel._pump.tick()
    assert panel.jobs.state is JobState.PAUSE_REQUESTED

    before = len(panel.jobs.stream.events)
    assert panel._on_state(running) is None, "a stale snapshot was reported"
    panel._pump.tick()
    assert len(panel.jobs.stream.events) == before
    assert panel.jobs.state is JobState.PAUSE_REQUESTED


# --------------------------------------------------------------------------- #
# F. Cancellation
# --------------------------------------------------------------------------- #


def test_a_report_racing_cancellation_keeps_the_truthful_ending(
    make_panel, output_base, tmp_path, stubs
):
    """CANCELLED is reported once the worker acknowledged, and it is never refused."""
    panel, params = started_run(make_panel, tmp_path, "one.txt")
    publisher = publisher_of(params)
    controller = params["controller"]
    item = params["items"][0]["item_id"]
    start = threading.Barrier(2)
    pressed = threading.Event()

    def work():
        start.wait(WAIT)
        # These are genuinely concurrent with the Cancel press below.
        for done in range(1, 6):
            publisher.progress(done, 5, item_id=item, stage="converting")
        assert pressed.wait(WAIT), "Cancel was never pressed"
        try:
            controller.checkpoint()   # the acknowledgement, at a real checkpoint
        except panel_module.ConversionCancelled:
            pass
        publisher.cancelled(controller.finish_cancelled())

    worker = run_thread(work)
    start.wait(WAIT)
    # The Cancel press stays on the Tk thread, because that is where it happens.
    panel.cancel_job()
    pressed.set()
    join_all(worker)
    panel._pump.tick()

    stream = panel.jobs.stream
    assert sequences_of(panel) == sorted(sequences_of(panel))
    assert not [verdict for _entry, verdict in stream.rejected
                if verdict is EventVerdict.OUT_OF_ORDER]
    assert stream.is_closed and stream.terminal.state is JobState.CANCELLED
    assert panel.jobs.state is JobState.CANCELLED
    assert controller.cancel_acknowledged


# --------------------------------------------------------------------------- #
# G. A retried attempt
# --------------------------------------------------------------------------- #


def test_a_retired_attempts_delayed_report_cannot_reach_the_retry(
    make_panel, output_base, tmp_path, failing_stubs
):
    """A retry re-uses the run id, so lineage cannot come from the id alone."""
    root = tmp_path / "Library"
    sources(root, "bad book.pdf")
    sources(root / "Book A", "fine.pdf")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()

    first = run_attempt(panel)
    assert panel._result is not None and panel._result.has_retryable
    retired = panel._publisher
    retired_queue = panel._event_q

    retry = accept(panel, panel.retry_failed)
    assert retry, "the retry was declined"
    assert retry["params"]["snapshot"] is first["snapshot"], "the same frozen run"
    assert panel._publisher is not retired, "the retry re-used a retired authority"
    assert panel._event_q is not retired_queue, "the retry re-used a retired queue"

    # Let the retry's own opening events land first, so what is counted below is
    # only what arrives *after* the retired attempt speaks.
    panel._pump.tick()
    live = panel.jobs.stream
    before = len(live.events)
    assert before, "the retry reported nothing of its own"
    item = first["items"][0]["item_id"]
    # Exactly what a straggler from the attempt being retried would do.
    assert retired.closed, "the retired authority was never closed"
    assert retired.progress(9, 9, item_id=item, stage="converting") is None
    assert retired.state_changed(retry["params"]["controller"].snapshot()) is None
    panel._pump.tick()

    assert len(live.events) == before, "a retired attempt's report reached the retry"
    assert not live.rejected, "a retired attempt's report was even offered"
    assert retired_queue.empty(), "the retired authority published after retirement"


def test_each_attempt_publishes_into_its_own_queue(
    make_panel, output_base, tmp_path, stubs
):
    """The authority binds its sink when it is built, so it cannot follow the panel."""
    panel, params = started_run(make_panel, tmp_path, "one.txt")
    first = publisher_of(params)
    assert first.sink is panel._event_q

    # Installing the next run's controls is the one point an attempt is retired.
    panel._install_jobs(panel_module.IDLE_RUN_ID, ())
    assert first.closed, "the retired authority was left open"
    assert first.sink is not panel._event_q, "it would publish into the live queue"
    assert panel._publisher is None, "a retired authority was left installed"


# --------------------------------------------------------------------------- #
# H. Teardown with a report in flight
# --------------------------------------------------------------------------- #


def test_closing_the_panel_with_a_report_in_flight_is_quiet_and_bounded(
    make_panel, output_base, tmp_path, stubs
):
    """Closing must not deadlock behind a held producer, and must draw nothing."""
    panel, params = started_run(make_panel, tmp_path, "one.txt")
    publisher = publisher_of(params)
    item = params["items"][0]["item_id"]
    gate = QueueGate(panel)
    failures: list[BaseException] = []

    def report():
        try:
            publisher.progress(1, 1, item_id=item, stage="converting")
            # Released after the close: this one must go nowhere at all.
            publisher.current_item(item, "Converting one.txt")
        except BaseException as exc:  # noqa: BLE001 - the test is what may not raise
            failures.append(exc)

    try:
        held = run_thread(report)
        assert gate.holding.wait(WAIT), "no producer reached the queue"
        # Retirement takes nothing the held producer owns, so it cannot block
        # behind one. This is the whole reason closing is not lock-guarded: a
        # window that will not close is worse than a report that goes nowhere.
        panel.close()
        assert publisher.closed, "closing left the authority open"
        assert panel.jobs.closed, "the adapter was left open"
    finally:
        gate.open()
        gate.restore()
    join_all(held)

    assert not failures, f"a released producer raised: {failures}"
    assert panel._pump.tick() == 0, "a closed panel still drained something"
    assert panel.jobs.stream.events == (), "a closed adapter rendered a late report"


# --------------------------------------------------------------------------- #
# I. The shared foundation is consumed, not re-implemented
# --------------------------------------------------------------------------- #


def test_the_panel_reimplements_no_part_of_the_shared_job_foundation(make_panel):
    """One state machine, one event vocabulary, one ordering rule — all shared."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    tree = panel_tree()
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "RunPublisher" in classes
    # No local copy of anything the shared module already decides: not the
    # verdicts, not the event vocabulary, not the state machine, and no
    # re-ordering of events that were already judged.
    for banned in ("OUT_OF_ORDER", "EventVerdict", "JobEventKind", "JobEvent(",
                   "class JobState", "class JobEventStream", "sorted("):
        assert banned not in source, f"the panel re-implements {banned!r}"
    publisher = ast.unparse(class_named("RunPublisher"))
    assert "JobReporter" in publisher, "the authority delegates to the shared reporter"
