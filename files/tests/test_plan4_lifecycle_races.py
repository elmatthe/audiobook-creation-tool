"""Deterministic lifecycle and race proofs — v0.6.1 Plan 4, Phase 11.

Plans 3 and 4 built two cooperative subsystems and adopted them into two panels.
Each subsystem already has its own thorough test module. What did **not** exist
was one place that pins the six interleavings where the two subsystems, the two
panels and the run lifecycle can collide, with the ordering *chosen by the test*
rather than by the scheduler.

The six, in the order the phase contract states them:

1. cancel racing a completing item;
2. ``Cancel Import`` racing a processing run;
3. pause racing a terminal transition;
4. close racing an in-flight scan;
5. stale-revision recomputation on commit;
6. duplicate and post-terminal events.

Determinism — the rule this whole module exists to keep
------------------------------------------------------
**Nothing here sleeps, polls, retries, or runs a body many times hoping to catch
an interleaving.** Every ordering is *arranged*: a worker is parked on an
explicit :class:`threading.Event` latch at the exact instant the race is about,
the test then does the thing it wants to interleave, and only then is the worker
released. Cross-thread events that must be genuinely concurrent are pinned with
a :class:`threading.Barrier`.

Waits carry a bounded timeout. **A timeout is never the race mechanism** — it
exists so a broken test fails loudly at the deadline instead of hanging the
suite. If a timeout is what makes a test pass, the test is wrong.

Safety
------
Every fixture is generated under ``tmp_path``. Nothing scans the repository, the
real home directory, Downloads, a real output base, runtime data, model data or
real media. No image is resized, no audio is synthesised, no engine is loaded,
no dialog opens, no subprocess starts and no setting outside a throwaway file is
written. The panels take their dialogs, thread factories, scanners and job
runners as injected seams, and every one of them is a fake here.

Scope
-----
Phase 11 is structural and behavioural proof. It adds no feature to either
panel, changes no engine, and touches no reporting order — the TTS
``RunPublisher`` approved in Phase 7 is read by these tests and written by none
of them.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import config as shared_config  # noqa: E402
from shared import image_capabilities as caps  # noqa: E402
from shared import job_control as jc  # noqa: E402
from shared import output_paths as op  # noqa: E402
from shared import settings as app_settings  # noqa: E402
from shared.cancellation import ConversionCancelled  # noqa: E402
from shared.import_coordination import (  # noqa: E402
    ImportCancellation,
    ImportCoordinator,
    ImportPhase,
    OutcomeStatus,
)
from shared.importing import (  # noqa: E402
    CommitStatus,
    ImportedFileManager,
    validate_direct_files,
)
from shared.job_control import (  # noqa: E402
    EventVerdict,
    IllegalJobTransition,
    JobContractError,
    JobEventStream,
    JobReporter,
    JobState,
    ProgressTracker,
    project_summary,
)

from mp3_tools import cover_resizer as cr  # noqa: E402
from tts import epub2tts_gui as tts_module  # noqa: E402

from test_import_coordination import (  # noqa: E402
    ControlledScanner,
    RealThreads,
    RecordingThreads,
    book,
    direct_request,
    folder_request,
)
from test_import_traversal import touch  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_tts_importing import _Stubs  # noqa: E402

#: Every wait in this module is bounded, so a deadlock fails the test instead of
#: stalling the suite. It never *creates* an ordering — the latches do that.
WAIT = 5.0


# --------------------------------------------------------------------------- #
# Shared fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # headless box with no display
        pytest.skip(f"Tk cannot open a display here: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture(autouse=True)
def _clean_capability_cache():
    """Cover builds its catalog from the probe, so no test inherits a cached one."""
    caps.reset_cache()
    yield
    caps.reset_cache()


@pytest.fixture()
def output_base(tmp_path, monkeypatch):
    """A throwaway output base. No test can reach the maintainer's real one."""
    base = tmp_path / "outputs"
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    shared_config.invalidate()
    monkeypatch.setattr(op, "resolve_output_base", lambda effective=None: base)
    try:
        yield base
    finally:
        app_settings.use_path(None)
        shared_config.invalidate()


@pytest.fixture()
def stubs(monkeypatch):
    """Every TTS engine entry point replaced. Nothing synthesises or downloads."""
    from tts.epub2tts_edge import epub2tts_edge as engine

    monkeypatch.setattr(engine, "ensure_punkt", lambda: None)
    monkeypatch.setattr(tts_module, "ensure_punkt", lambda: None)
    return _Stubs().install(monkeypatch)


class DeferredRunner:
    """The panels' job-runner seam, holding the worker instead of starting it.

    A run therefore becomes *live* — controller started, inputs locked, state
    ``RUNNING`` — while no image is ever opened and no thread ever exists. That
    is exactly the state the isolation and close races need to stand in, and it
    is reached with no timing assumption at all.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, panel, params):
        self.calls.append(params)
        return None


class CapturedThread:
    """``threading.Thread``'s shape, capturing the body instead of running it.

    The TTS panel starts its worker with ``threading.Thread(...)`` directly, so
    this is how a test gets a started run without a running worker.
    """

    def __init__(self, kwargs, sink) -> None:
        sink["target"] = kwargs["target"]
        sink["params"] = kwargs["args"][0]
        self.daemon = kwargs.get("daemon", False)

    def start(self) -> None:
        return None

    def is_alive(self) -> bool:
        return False

    def join(self, timeout=None) -> None:
        return None


@pytest.fixture()
def cover_panel(tk_root, output_base):
    """A real ``CoverResizerUI`` whose every concurrency seam is injectable."""
    made: list[cr.CoverResizerUI] = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        kwargs.setdefault("preview_runner", lambda requests, publish: None)
        kwargs.setdefault("job_runner", DeferredRunner())
        panel = cr.CoverResizerUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


@pytest.fixture()
def tts_panel(tk_root, output_base, stubs):
    """A real ``TtsPanel`` with every engine stubbed and every seam injectable."""
    made: list[tts_module.TtsPanel] = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        panel = tts_module.TtsPanel(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


def add_files(panel, *paths: Path) -> tuple[str, ...]:
    """Queue files through the real shared direct-file path, never past it."""
    panel.importer._choose_files = lambda: tuple(str(entry) for entry in paths)
    panel.importer.add_files()
    return panel.manager.snapshot().occurrence_ids


class ParkedScan:
    """A folder scan held open inside the scanner, on a real thread.

    Built *through the panel's own constructor seams* — no attribute is reached
    into after the fact. When :meth:`arrive` returns, the worker is provably
    inside the scan, because the scanner itself set the latch.
    """

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.threads = RealThreads()
        self.scanner = ControlledScanner(started=self.started, release=self.release)

    def seams(self) -> dict:
        return {"scanner": self.scanner, "thread_factory": self.threads}

    def arrive(self, panel, root: Path) -> "ParkedScan":
        panel.importer._choose_folder = lambda: (str(root),)
        panel.importer.add_folder()
        assert self.started.wait(WAIT), "the scan never reached the scanner"
        return self

    def let_finish(self) -> None:
        self.release.set()
        for thread in self.threads.made:
            thread.join(WAIT)
            assert not thread.is_alive(), "an import worker outlived its bounded join"

    @property
    def worker_count(self) -> int:
        return len(self.threads.made)


def start_cover_run(panel, size: int = 64):
    """Accept one Cover run without touching a single image."""
    panel.var_size.set(size)
    panel.start_resize()
    return panel.job_controller


def start_tts_run(panel):
    """Accept one TTS run without starting its worker thread."""
    captured: dict = {}
    real_thread = tts_module.threading.Thread
    try:
        tts_module.threading.Thread = lambda **kw: CapturedThread(kw, captured)
        panel.run_job()
    finally:
        tts_module.threading.Thread = real_thread
    assert captured, "the panel declined to start a run"
    return panel._controller


# --------------------------------------------------------------------------- #
# Race 1 — a cancel racing an item that is completing
# --------------------------------------------------------------------------- #
#
# The dangerous window is not "cancel during work"; that one is easy and already
# covered. It is the few instructions between a worker's *last* checkpoint and
# its terminal settlement, where a cancel can land after the run can no longer
# honour it. Three orderings are forced, one at a time, by parking the worker on
# a latch at exactly the instruction the race is about.


class SettlingWorker:
    """A real worker parked at one explicit handoff point, chosen by the test.

    ``checkpoint_before_settle`` decides *which* instruction it is parked at:

    * ``True`` — parked **before** its last checkpoint, so a cancel that lands
      while it waits is one the worker will still observe;
    * ``False`` — parked **after** its last checkpoint, so a cancel that lands
      while it waits can never be acknowledged by this run.

    Either way the ordering is settled by ``release``, never by the scheduler.
    """

    def __init__(self, controller, *, checkpoint_before_settle: bool = True,
                 settle=None) -> None:
        self.controller = controller
        self.checkpoint_before_settle = checkpoint_before_settle
        self._settle = settle or controller.succeed
        self.arrived = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.outcome: JobState | None = None
        self.raised: BaseException | None = None
        self.thread = threading.Thread(
            target=self._body, name="settling-worker", daemon=False)

    def start(self) -> "SettlingWorker":
        self.thread.start()
        assert self.arrived.wait(WAIT), "the worker never reached its handoff point"
        return self

    def _body(self) -> None:
        try:
            self.controller.checkpoint()          # the item's own boundary
            if not self.checkpoint_before_settle:
                self.controller.checkpoint()      # its *last* one, taken early
            self.arrived.set()
            assert self.release.wait(WAIT), "the test never released the worker"
            if self.checkpoint_before_settle:
                self.controller.checkpoint()      # its last one, taken late
            self.outcome = self._settle().state
        except ConversionCancelled:
            self.outcome = self.controller.finish_cancelled().state
        except BaseException as exc:  # noqa: BLE001 - reported, never swallowed
            self.raised = exc
        finally:
            self.arrived.set()
            self.finished.set()

    def let_finish(self) -> None:
        self.release.set()
        assert self.finished.wait(WAIT), "the worker never finished"
        self.thread.join(WAIT)
        assert not self.thread.is_alive(), "the worker outlived its bounded join"
        assert self.raised is None, self.raised


class TerminalWatcher:
    """Records every snapshot the controller published, on whatever thread."""

    def __init__(self) -> None:
        self.snapshots: list = []

    def __call__(self, snapshot) -> None:
        self.snapshots.append(snapshot)

    @property
    def terminal_states(self) -> list[JobState]:
        return [entry.state for entry in self.snapshots
                if entry.state in jc.TERMINAL_STATES]


def cancel_from_another_thread(controller) -> None:
    """Press Cancel on a second thread, released in lockstep with this one.

    The :class:`threading.Barrier` makes the cancel genuinely concurrent rather
    than a method call in disguise; the parked worker makes *where* it lands
    deterministic. Both properties are needed, and neither is a sleep.
    """
    ready = threading.Barrier(2, timeout=WAIT)

    def press() -> None:
        ready.wait()
        controller.request_cancel()

    presser = threading.Thread(target=press, name="cancel-press", daemon=False)
    presser.start()
    ready.wait()
    presser.join(WAIT)
    assert not presser.is_alive(), "the cancel press outlived its bounded join"


def started_controller():
    watcher = TerminalWatcher()
    controller = jc.JobController("run-race", listener=watcher)
    controller.start()
    return controller, watcher


def test_a_completion_that_wins_the_race_is_not_undone_by_a_late_cancel():
    """Ordering A: the item settles, *then* the cancel arrives.

    A finished run must not start describing itself as cancelled, and the late
    request must change nothing observable — not the state, not the revision,
    not the acknowledgement.
    """
    controller, watcher = started_controller()
    worker = SettlingWorker(controller).start()

    worker.let_finish()                       # completion first, provably
    assert controller.state is JobState.SUCCEEDED
    settled_revision = controller.revision

    cancel_from_another_thread(controller)    # and only then, the cancel

    assert controller.state is JobState.SUCCEEDED
    assert controller.revision == settled_revision, "a late cancel moved a settled run"
    assert controller.cancel_check() is False
    assert controller.cancel_acknowledged is False
    assert worker.outcome is JobState.SUCCEEDED
    assert watcher.terminal_states == [JobState.SUCCEEDED], watcher.terminal_states


def test_a_cancel_acknowledged_first_settles_cancelled_and_cannot_be_overwritten():
    """Ordering B: the cancel is acknowledged, *then* completion is attempted.

    The worker is parked before its last checkpoint, so the cancel it meets
    there is one it must honour. Once ``CANCELLED`` is settled, a success can
    never replace it.
    """
    controller, watcher = started_controller()
    worker = SettlingWorker(controller).start()

    cancel_from_another_thread(controller)    # cancel first, provably
    assert controller.cancel_check() is True
    assert controller.state is JobState.CANCEL_REQUESTED

    worker.let_finish()                       # and only then, the completion attempt

    assert worker.outcome is JobState.CANCELLED
    assert controller.state is JobState.CANCELLED
    assert controller.cancel_acknowledged is True
    with pytest.raises(IllegalJobTransition):
        controller.succeed()
    assert controller.state is JobState.CANCELLED, "a settled cancellation was overwritten"
    assert watcher.terminal_states == [JobState.CANCELLED], watcher.terminal_states


def test_a_cancel_that_lands_after_the_last_checkpoint_never_fakes_a_cancellation():
    """The genuinely dangerous ordering, and the one that must stay truthful.

    The worker is parked *after* its last checkpoint, so this cancel can never
    be observed by this run. The run really did finish, so it says ``SUCCEEDED``
    — and because no checkpoint acknowledged anything, ``finish_cancelled``
    refuses outright rather than inventing an acknowledgement. That refusal is
    the property that makes "cancelled" mean "it actually stopped".
    """
    controller, watcher = started_controller()
    worker = SettlingWorker(controller, checkpoint_before_settle=False).start()

    cancel_from_another_thread(controller)
    assert controller.cancel_check() is True
    assert controller.cancel_acknowledged is False

    worker.let_finish()

    assert worker.outcome is JobState.SUCCEEDED
    assert controller.state is JobState.SUCCEEDED
    assert controller.cancel_acknowledged is False, "an acknowledgement was fabricated"
    with pytest.raises(JobContractError):
        controller.finish_cancelled()
    assert controller.state is JobState.SUCCEEDED
    assert watcher.terminal_states == [JobState.SUCCEEDED], watcher.terminal_states


@pytest.mark.parametrize("checkpoint_before_settle", [True, False])
def test_exactly_one_terminal_transition_happens_whichever_side_wins(
        checkpoint_before_settle):
    """The invariant both orderings share: one run, one ending, one revision bump.

    Whatever the interleaving, the impossible combinations must stay impossible:
    two terminal states, a terminal state that moves again, or a run that ends
    without any terminal state at all.
    """
    controller, watcher = started_controller()
    worker = SettlingWorker(
        controller, checkpoint_before_settle=checkpoint_before_settle).start()
    cancel_from_another_thread(controller)
    worker.let_finish()

    assert len(watcher.terminal_states) == 1, watcher.terminal_states
    assert controller.is_terminal
    frozen = (controller.state, controller.revision)
    controller.request_cancel()
    controller.request_pause()
    controller.resume()
    assert (controller.state, controller.revision) == frozen, "a terminal run moved"


# --------------------------------------------------------------------------- #
# Race 2 — `Cancel Import` racing a processing run
# --------------------------------------------------------------------------- #
#
# Two cancellations exist and they are different things. Import cancellation
# stops a scan; processing cancellation stops a conversion or a resize. Pressing
# either while the other is live must leave the other alone.


def test_the_two_cancellations_are_not_the_same_primitive():
    """They are different types, and neither can stand in for the other."""
    importer_cancel = ImportCancellation()
    controller = jc.JobController("run-primitive")
    controller.start()

    assert not isinstance(importer_cancel, threading.Event)
    assert not isinstance(importer_cancel, jc.JobController)
    importer_cancel.request()
    assert importer_cancel.requested is True
    assert controller.cancel_check() is False
    assert controller.state is JobState.RUNNING

    controller.request_cancel()
    assert importer_cancel.requested is True, "unchanged, and never reset for reuse"
    assert controller.cancel_check() is True


def test_a_coordinator_cancel_cannot_reach_a_controller_it_has_no_reference_to(tmp_path):
    """The foundation-level half, with a scan genuinely in flight."""
    release = threading.Event()
    threads = RealThreads()
    started = threading.Event()
    coordinator = ImportCoordinator(
        ImportedFileManager(),
        scanner=ControlledScanner(started=started, release=release),
        thread_factory=threads,
        home=None,
    )
    controller = jc.JobController("run-isolated")
    controller.start()
    coordinator.start(folder_request(book(tmp_path)))
    assert started.wait(WAIT), "the scan never started"

    coordinator.request_cancel()
    assert coordinator.cancel_requested is True
    assert controller.cancel_check() is False
    assert controller.state is JobState.RUNNING

    controller.request_cancel()
    assert controller.cancel_check() is True

    release.set()
    threads.made[0].join(WAIT)
    assert not threads.made[0].is_alive()
    coordinator.close()


def test_cover_cancel_import_leaves_the_running_resize_alone(cover_panel, tmp_path):
    """Cover: `Cancel Import` while a resize is running touches the scan only."""
    scan = ParkedScan()
    panel = cover_panel(**scan.seams())
    add_files(panel, *[touch(tmp_path / "Loose" / name, "x")
                       for name in ("a.jpg", "b.jpg")])
    scan.arrive(panel, book(tmp_path, "Folder", "c.jpg"))
    controller = start_cover_run(panel)
    assert controller.state is JobState.RUNNING

    assert panel.importer.cancel_import() is True

    assert panel.importer.coordinator.cancel_requested is True
    assert controller.cancel_check() is False, "an import cancel reached the run"
    assert controller.state is JobState.RUNNING
    assert panel._cancel_event.is_set() is False, (
        "an import cancel reached the panel's processing cancel event")
    scan.let_finish()


def test_cover_cancelling_the_resize_leaves_the_running_import_alone(
        cover_panel, tmp_path):
    """Cover, the other direction: pressing Cancel does not cancel the scan."""
    scan = ParkedScan()
    panel = cover_panel(**scan.seams())
    add_files(panel, touch(tmp_path / "Loose" / "a.jpg", "x"))
    scan.arrive(panel, book(tmp_path, "Folder", "c.jpg"))
    controller = start_cover_run(panel)

    panel.cancel()

    assert controller.cancel_check() is True
    assert panel._cancel_event.is_set() is True
    assert panel.importer.coordinator.cancel_requested is False, (
        "a processing cancel reached the import coordinator")
    assert panel.importer.coordinator.phase is ImportPhase.SCANNING
    scan.let_finish()


def test_tts_cancel_import_leaves_the_running_conversion_alone(tts_panel, tmp_path):
    """TTS: the controller is the only processing authority, and it is untouched."""
    scan = ParkedScan()
    panel = tts_panel(**scan.seams())
    add_files(panel, *[touch(tmp_path / "Loose" / name, "Body text.\n")
                       for name in ("a.pdf", "b.txt")])
    scan.arrive(panel, book(tmp_path, "Folder", "c.pdf"))
    controller = start_tts_run(panel)
    assert controller.state is JobState.RUNNING

    assert panel.importer.cancel_import() is True

    assert panel.importer.coordinator.cancel_requested is True
    assert controller.cancel_check() is False, "an import cancel reached the run"
    assert controller.state is JobState.RUNNING
    scan.let_finish()


def test_tts_cancelling_the_conversion_leaves_the_running_import_alone(
        tts_panel, tmp_path):
    """TTS, the other direction, through the panel's own Cancel."""
    scan = ParkedScan()
    panel = tts_panel(**scan.seams())
    add_files(panel, touch(tmp_path / "Loose" / "a.pdf", "Body text.\n"))
    scan.arrive(panel, book(tmp_path, "Folder", "c.pdf"))
    controller = start_tts_run(panel)

    panel.cancel_job()

    assert controller.cancel_check() is True
    assert panel.importer.coordinator.cancel_requested is False, (
        "a processing cancel reached the import coordinator")
    assert panel.importer.coordinator.phase is ImportPhase.SCANNING
    scan.let_finish()


# --------------------------------------------------------------------------- #
# Race 3 — pause racing a terminal transition
# --------------------------------------------------------------------------- #


TERMINAL_SETTLEMENTS = {
    "succeeded": (JobState.SUCCEEDED, lambda job: job.succeed),
    "completed_with_failures": (
        JobState.COMPLETED_WITH_FAILURES, lambda job: job.complete_with_failures),
    "failed": (JobState.FAILED, lambda job: (lambda: job.fail("It did not finish."))),
}


@pytest.mark.parametrize("name", sorted(TERMINAL_SETTLEMENTS))
def test_a_pause_requested_around_the_ending_never_produces_a_paused_terminal(name):
    """Pause lands while the worker is parked one instruction from settling.

    ``PAUSE_REQUESTED`` is a truthful state — the pause was asked for and the
    indivisible stage kept running — and that stage turned out to be the last
    one. The run must end in its real terminal state, and nothing may afterwards
    turn a terminal run back into ``PAUSED``.
    """
    expected, settle_for = TERMINAL_SETTLEMENTS[name]
    watcher = TerminalWatcher()
    controller = jc.JobController(f"run-pause-{name}", listener=watcher)
    controller.start()
    worker = SettlingWorker(
        controller, checkpoint_before_settle=False,
        settle=lambda: settle_for(controller)()).start()

    controller.request_pause()
    assert controller.state is JobState.PAUSE_REQUESTED
    assert controller.pause_requested is True

    worker.let_finish()

    assert controller.state is expected
    assert controller.is_terminal
    assert controller.snapshot().is_paused is False
    assert watcher.terminal_states == [expected], watcher.terminal_states

    frozen = controller.revision
    controller.request_pause()
    assert controller.state is expected, "a terminal run became pause-requested"
    assert controller.revision == frozen


@pytest.mark.parametrize("name", sorted(TERMINAL_SETTLEMENTS))
def test_no_resume_is_needed_to_release_a_run_that_ended_while_pausing(name):
    """A checkpoint reached after the ending returns; it does not wait forever.

    This is the deadlock the ordering could otherwise cause: a worker that
    arrives at a checkpoint just after the run went terminal must not park on
    the condition waiting for a resume that will never come.
    """
    expected, settle_for = TERMINAL_SETTLEMENTS[name]
    controller = jc.JobController(f"run-late-checkpoint-{name}")
    controller.start()
    controller.request_pause()
    settle_for(controller)()
    assert controller.state is expected

    returned = threading.Event()

    def late_checkpoint() -> None:
        controller.checkpoint()
        returned.set()

    # The one deliberately daemonic thread in this module, and the reason is the
    # failure it is probing for. Every other thread here has a bounded wait of
    # its own, so it exits whatever happens. This one has none: if the contract
    # ever broke, ``checkpoint`` would park on the condition with nothing left to
    # wake it. Non-daemon, that would hang the interpreter at exit and the
    # regression would look like a stuck suite; daemon, the bounded join below
    # fails the assertion loudly and the run still ends.
    latecomer = threading.Thread(target=late_checkpoint, name="late", daemon=True)
    latecomer.start()
    latecomer.join(WAIT)

    assert returned.is_set(), "a checkpoint after the ending waited for a resume"
    assert not latecomer.is_alive()
    assert controller.state is expected
    controller.resume()
    assert controller.state is expected, "resume revived a terminal run"


def test_a_cancel_settlement_racing_a_pause_stays_coherent():
    """The fourth terminal state, which can only be reached through a checkpoint.

    ``CANCELLED`` needs an acknowledgement, so the pause is asked for while the
    worker is parked before its last checkpoint and the cancel is what that
    checkpoint meets. The pause must lose without leaving a trace.
    """
    watcher = TerminalWatcher()
    controller = jc.JobController("run-pause-cancel", listener=watcher)
    controller.start()
    worker = SettlingWorker(controller).start()

    controller.request_pause()
    assert controller.state is JobState.PAUSE_REQUESTED
    controller.request_cancel()
    assert controller.state is JobState.CANCEL_REQUESTED, "cancel outranks pause"

    worker.let_finish()

    assert controller.state is JobState.CANCELLED
    assert controller.snapshot().is_paused is False
    assert watcher.terminal_states == [JobState.CANCELLED], watcher.terminal_states


# --------------------------------------------------------------------------- #
# Race 4 — close racing an in-flight scan
# --------------------------------------------------------------------------- #


def test_closing_the_coordinator_mid_scan_makes_the_late_result_inert(tmp_path):
    """The foundation-level contract every adopting panel then inherits."""
    manager = ImportedFileManager()
    release = threading.Event()
    started = threading.Event()
    threads = RealThreads()
    coordinator = ImportCoordinator(
        manager,
        scanner=ControlledScanner(started=started, release=release),
        thread_factory=threads,
        home=None,
        join_timeout=0.05,
    )
    coordinator.start(folder_request(book(tmp_path)))
    assert started.wait(WAIT), "the scan never started"

    report = coordinator.close()

    assert report.closed is True
    assert report.worker_stopped is False, "a running scandir was not interrupted"
    assert coordinator.is_closed

    release.set()                       # the scan finishes *after* the close
    threads.made[0].join(WAIT)
    assert not threads.made[0].is_alive(), "a worker outlived the close"
    assert coordinator.pump().status is OutcomeStatus.CLOSED
    assert manager.count == 0, "a late scan result mutated a closed manager"


@pytest.fixture()
def adopting_panel(request, cover_panel, tts_panel, tmp_path):
    """Either adopting panel, plus a source file it will accept.

    The two panels take different input types and expose different processing
    controls, but Phase 11's close contract is one contract, so it is stated
    once and parametrized over both rather than written twice.
    """
    which = request.param

    def build(**kwargs):
        if which == "cover":
            panel = cover_panel(**kwargs)
            source = touch(tmp_path / "Loose" / "a.jpg", "x")
        else:
            panel = tts_panel(**kwargs)
            source = touch(tmp_path / "Loose" / "a.pdf", "Body text.\n")
        return panel, source

    return build


@pytest.mark.parametrize("adopting_panel", ["cover", "tts"], indirect=True)
def test_closing_a_panel_mid_scan_leaves_nothing_scheduled_or_reserved(
        adopting_panel, tmp_path, output_base):
    """Both adopting panels honour the identical close contract.

    Held in flight, closed, then released — in that order, by latch. Afterwards
    nothing may be scheduled on Tk, no worker may survive, the late result must
    be inert, the manager must be untouched, and — because no run was ever
    validated — no output run may have been reserved.
    """
    scan = ParkedScan()
    panel, source = adopting_panel(**scan.seams())
    add_files(panel, source)
    before = panel.manager.count
    scan.arrive(panel, book(tmp_path, "Folder", source.name))

    panel.close()

    assert panel._pump.closed is True
    assert panel._pump.pending is None, "a Tk callback outlived the close"
    assert panel.importer.closed is True
    assert panel.importer.coordinator.is_closed is True

    scan.let_finish()                   # the scan publishes after everything closed

    panel._pump.tick()                  # inert: the pump forgot every drain
    assert panel.manager.count == before, "a late scan result reached a closed panel"
    assert panel.importer.coordinator.pump().status is OutcomeStatus.CLOSED
    assert panel.manager.count == before
    assert not output_base.exists(), "closing a scan reserved an output run"
    assert scan.worker_count == 1, "the close created a second import worker"
    panel.close()                       # idempotent


@pytest.mark.parametrize("adopting_panel", ["cover", "tts"], indirect=True)
def test_a_close_that_races_a_scan_starts_no_processing_run(
        adopting_panel, tmp_path, output_base):
    """The close path must not become a way to *start* work.

    Closing asks a *processing* run to stop; with no run ever accepted there is
    nothing to stop, and the import side must not be turned into one. Cover's
    job runner is the observable proof — nothing was ever handed to it.
    """
    scan = ParkedScan()
    panel, source = adopting_panel(**scan.seams())
    add_files(panel, source)
    scan.arrive(panel, book(tmp_path, "Folder", source.name))

    panel.close()
    scan.let_finish()

    assert scan.worker_count == 1
    assert not output_base.exists()
    runner = getattr(panel, "_job_runner", None)
    if runner is not None:
        assert runner.calls == [], "the close started a processing run"
    assert panel._controller is None, "a controller appeared without a run"


# --------------------------------------------------------------------------- #
# Race 5 — stale-revision recomputation on commit
# --------------------------------------------------------------------------- #


def append_directly(manager: ImportedFileManager, *paths: Path) -> None:
    """Add files through the manager's own validate / plan / commit path.

    ``ImportedFileManager``'s methods are named explicitly so this never reaches
    a subclass's instrumented override: it is a genuine production append, but
    it is not the commit under test, so it must not be counted as one.
    """
    request = direct_request(request_id="req-mutation")
    result = validate_direct_files(
        paths,
        request_id=request.request_id,
        root=request.roots[0],
        catalog=request.catalog,
        options=request.options,
    )
    transaction = ImportedFileManager.plan(manager, result, options=request.options)
    ImportedFileManager.commit(manager, transaction)


def clear_directly(manager: ImportedFileManager) -> None:
    ImportedFileManager.clear(manager)


class MutatingManager(ImportedFileManager):
    """A real manager that moves its own revision at chosen commit instants.

    Nothing about the revision mechanism is faked. Each armed mutation is a
    genuine append or clear through the manager's own API, timed to land
    *between* the plan and the commit that was planned against it — which is
    exactly the interleaving a user creates by pressing Clear, or by importing
    something else, while a large-result confirmation is open. The timing is
    arranged, never waited for.

    Mutations are consumed one per commit, in order, so a test states precisely
    how many times the revision moves and when.
    """

    __slots__ = ("commits", "recomputes", "_pending")

    def __init__(self) -> None:
        super().__init__()
        self.commits = 0
        self.recomputes = 0
        self._pending: list = []

    def arm(self, *mutations) -> "MutatingManager":
        """Queue one mutation per upcoming commit. Call it *after* any setup."""
        self._pending = list(mutations)
        return self

    def commit(self, transaction):
        self.commits += 1
        if self._pending:
            self._pending.pop(0)(self)
        return super().commit(transaction)

    def recompute(self, transaction):
        self.recomputes += 1
        return super().recompute(transaction)


def test_a_revision_that_moves_at_the_commit_instant_recomputes_exactly_once(tmp_path):
    """Plan, mutate at the commit, recompute once, commit against current state.

    Every step travels the production seam: the stale verdict comes from the
    real revision check, the recomputation from the real ``recompute``, and the
    retry from the real second ``commit``. Nothing is stubbed to force the path.
    """
    root = book(tmp_path, "Book", "a.mp3", "b.mp3")
    manager = MutatingManager()
    append_directly(manager, root / "a.mp3")
    assert manager.count == 1
    planned_against = manager.revision

    manager.arm(clear_directly)      # the list is emptied at the commit instant
    coordinator = ImportCoordinator(
        manager, thread_factory=RecordingThreads(), home=None)
    report = coordinator.start(folder_request(root))
    assert report.started

    outcome = coordinator.pump()

    assert outcome.status is OutcomeStatus.COMMITTED
    assert manager.recomputes == 1, "the recomputation is once, never a retry loop"
    assert manager.commits == 2, (
        "one stale attempt and exactly one retry", manager.commits)
    assert manager.revision != planned_against
    # The list the user is left with is the one derived from *current* state:
    # a.mp3 was cleared away, so the retry proposes both files rather than the
    # one the stale transaction had planned.
    assert [entry.path.name for entry in manager.snapshot().files] == ["a.mp3", "b.mp3"]
    assert manager.count == 2, "an accidental duplicate append"
    assert outcome.added_count == 2
    coordinator.close()


def test_the_recomputed_commit_keeps_ordering_provenance_and_occurrence_identity(
        tmp_path):
    """A recomputation is a re-plan, not a merge: nothing is reordered or lost."""
    root = book(tmp_path, "Book", "a.mp3", "b.mp3", "c.mp3")
    other = touch(tmp_path / "Other" / "z.mp3", "z")
    manager = MutatingManager().arm(lambda owner: append_directly(owner, other))
    coordinator = ImportCoordinator(
        manager, thread_factory=RecordingThreads(), home=None)

    report = coordinator.start(folder_request(root))
    assert report.started
    outcome = coordinator.pump()

    assert outcome.status is OutcomeStatus.COMMITTED
    assert manager.recomputes == 1
    assert manager.commits == 2
    snapshot = manager.snapshot()
    assert [entry.path.name for entry in snapshot.files] == [
        "z.mp3", "a.mp3", "b.mp3", "c.mp3"], "the recomputed commit reordered the list"
    folder_derived = [entry for entry in snapshot.files
                      if entry.source_root.path is not None]
    assert [entry.path.name for entry in folder_derived] == ["a.mp3", "b.mp3", "c.mp3"], (
        "folder provenance was lost by the recomputation")
    assert len({entry.occurrence_id for entry in snapshot.files}) == 4
    coordinator.close()


def test_a_second_conflict_reports_truthfully_and_appends_nothing(tmp_path):
    """One recomputation, one retry, then the truth — never a third attempt.

    Two mutations are armed, so the revision has moved again by the time the
    recomputed transaction is committed. The importer must report the conflict
    rather than loop, and must leave the scan's own files entirely unimported.
    """
    root = book(tmp_path, "Book", "a.mp3")
    interference = (touch(tmp_path / "Other" / "x.mp3", "x"),
                    touch(tmp_path / "Other" / "y.mp3", "y"))
    manager = MutatingManager().arm(
        lambda owner: append_directly(owner, interference[0]),
        lambda owner: append_directly(owner, interference[1]),
    )
    coordinator = ImportCoordinator(
        manager, thread_factory=RecordingThreads(), home=None)
    report = coordinator.start(folder_request(root))
    assert report.started

    outcome = coordinator.pump()

    assert outcome.status is OutcomeStatus.CONFLICT
    assert outcome.commit.status is CommitStatus.STALE_REVISION
    assert manager.recomputes == 1, "no further attempt is made after the retry"
    assert manager.commits == 2, "exactly two commit attempts, then the truth"
    assert outcome.added == ()
    assert [entry.path.name for entry in manager.snapshot().files] == [
        "x.mp3", "y.mp3"], "the conflicted scan appended something"
    assert "changed while this import was finishing" in outcome.display_message
    assert coordinator.phase is ImportPhase.IDLE
    coordinator.close()


# --------------------------------------------------------------------------- #
# Race 6 — duplicate and post-terminal events
# --------------------------------------------------------------------------- #


def run_stream(item_ids=("item-1", "item-2")):
    """One reporter and one stream over the same run id, as a panel wires them."""
    published: "queue.SimpleQueue" = queue.SimpleQueue()
    reporter = JobReporter("run-events", clock=lambda: 0.0, publish=published.put)
    stream = JobEventStream("run-events", item_ids=item_ids)
    return reporter, stream, published


def test_a_duplicated_terminal_event_is_refused_and_changes_nothing():
    """The second ending is rejected, not merged and not allowed to overwrite."""
    reporter, stream, _published = run_stream()
    controller = jc.JobController("run-events")
    controller.start()
    stream.accept(reporter.progress(1, 2, stage="converting"))
    terminal = reporter.completed(controller.succeed())

    assert stream.accept(terminal) is EventVerdict.ACCEPTED
    accepted_before = stream.events
    summary_before = project_summary(stream.events)

    assert stream.accept(terminal) is EventVerdict.DUPLICATE_TERMINAL

    assert stream.events == accepted_before, "a duplicate reached the history"
    assert project_summary(stream.events) == summary_before
    assert stream.terminal is terminal
    assert [verdict for _entry, verdict in stream.rejected] == [
        EventVerdict.DUPLICATE_TERMINAL]


def test_a_post_terminal_event_is_inert_and_cannot_move_progress_or_summary():
    """Late progress, a late failure and a late warning all change nothing."""
    reporter, stream, _published = run_stream()
    controller = jc.JobController("run-events")
    controller.start()
    tracker = ProgressTracker()
    for entry in (reporter.progress(1, 2, stage="converting"),
                  reporter.current_item("item-1")):
        assert stream.accept(entry) is EventVerdict.ACCEPTED
        tracker.apply(entry)
    stream.accept(reporter.completed(controller.succeed()))

    view_before = tracker.view
    summary_before = project_summary(stream.events)
    history_before = stream.events

    late = (
        reporter.progress(2, 2, stage="converting"),
        reporter.failure("It did not convert.", item_id="item-2"),
        reporter.warning("Something happened."),
    )
    verdicts = tuple(stream.accept(entry) for entry in late)

    assert verdicts == (EventVerdict.AFTER_TERMINAL,) * 3
    assert stream.events == history_before, "a late event reached the history"
    assert project_summary(stream.events) == summary_before, "the summary moved"
    for entry in late:
        assert entry not in stream.events
    # A panel feeds its tracker only what the stream accepted, so replaying the
    # accepted history must land on exactly the view it already had.
    replayed = ProgressTracker()
    for entry in stream.events:
        replayed.apply(entry)
    assert replayed.view == view_before, "the projected progress regressed"


def test_an_out_of_order_event_stays_strictly_refused():
    """Phase 7's ordering authority, restated: not-after is refused, always.

    A replayed event and an event whose sequence merely equals the last accepted
    one are both ``OUT_OF_ORDER``. Relaxing either would let a reporter's second
    thread interleave a stale number into a settled history.
    """
    reporter, stream, _published = run_stream()
    first = reporter.progress(1, 2, stage="converting")
    second = reporter.progress(2, 2, stage="converting")
    assert stream.accept(first) is EventVerdict.ACCEPTED
    assert stream.accept(second) is EventVerdict.ACCEPTED

    assert stream.accept(first) is EventVerdict.OUT_OF_ORDER
    assert stream.accept(second) is EventVerdict.OUT_OF_ORDER
    assert stream.events == (first, second)


def test_a_duplicated_whole_run_replayed_into_one_stream_adds_nothing(tmp_path):
    """The end-to-end shape: an entire published run, drained twice.

    The second drain is the deterministic stand-in for a worker that published
    its lifetime twice. Every event of it must be refused, and the projection
    the panel renders must be byte-identical to the first pass.
    """
    reporter, stream, published = run_stream()
    controller = jc.JobController("run-events")
    controller.start()
    reporter.progress(0, 2, stage="converting")
    reporter.current_item("item-1")
    reporter.progress(1, 2, stage="converting")
    reporter.failure("It did not convert.", item_id="item-2")
    reporter.completed(controller.complete_with_failures())

    events = []
    while True:
        try:
            events.append(published.get_nowait())
        except queue.Empty:
            break
    assert len(events) == 5

    first_pass = stream.drain(events)
    assert set(first_pass) == {EventVerdict.ACCEPTED}
    history = stream.events
    summary = project_summary(stream.events)

    second_pass = stream.drain(events)

    assert EventVerdict.ACCEPTED not in second_pass, second_pass
    assert set(second_pass) <= {
        EventVerdict.AFTER_TERMINAL, EventVerdict.DUPLICATE_TERMINAL,
        EventVerdict.OUT_OF_ORDER}, second_pass
    assert stream.events == history, "a replayed run mutated the history"
    assert project_summary(stream.events) == summary, "a replayed run moved the summary"
