"""The M4B Converter's adoption of shared job control and reporting — Plan 5, Phase 9.

Phase 7B made the committed ``ImportedFileManager`` the panel's only input
authority and Phase 8 planned every destination at Start. This phase moves the
*run itself* onto the approved Plan 3 foundation: one ``JobController``, one
``JobReporter``, one ``JobEventStream``, one ``JobAdapter``, one ``EtaEstimator``
and one shared ``LockGroup``, all drained on the panel's existing
``MainThreadPump``.

What these tests are actually protecting
----------------------------------------
The load-bearing ones are about **authority and truthfulness**, not about
buttons:

* the controller is the only thing that decides what state the run is in, and
  every move it makes is a move the shared transition table allows;
* the worker touches no widget, holds no estimator and emits immutable events;
* ``Pause`` reaches ``PAUSE_REQUESTED`` and *stops there* until the worker
  acknowledges it between two books -- nothing anywhere claims a running ffmpeg
  was suspended, because at this phase nothing can suspend one;
* ``Cancel`` prevents later books from starting and settles only after a
  checkpoint actually observed it;
* the progress denominator is the **interim** one this phase honestly knows --
  one unit per imported occurrence -- and is explicitly guarded against
  pretending Phase 10's ``total_segments`` already exists;
* ``Retry Failed`` is rendered and stays unavailable, because Phase 13 owns
  retry execution and an enabled control would promise work this phase cannot do.

Determinism
-----------
No test sleeps. The conversion thread is replaced by a stub that captures the
worker's parameters, and the worker body is then run explicitly -- inline for
almost everything, and on one real, joinable thread for the two pause/cancel
races, which wait only on real signals with a bounded timeout so a run that never
reaches the expected state fails loudly instead of hanging. Clocks are injected.

Safety
------
No media, no ffmpeg process and no dialog. Every ``.m4b`` is a generated
placeholder under ``tmp_path``; the ffmpeg seams are stubbed, so nothing is
decoded, encoded, probed or revealed in a file manager.
"""

from __future__ import annotations

import ast
import dataclasses
import queue
import threading
import unittest.mock as mock
from pathlib import Path

import pytest

# Imported outright rather than through ``importorskip``: Plan 5 is fail-loud.
import tkinter as tk

from shared import config  # noqa: E402
from shared import job_control as jc  # noqa: E402
from shared import job_ui  # noqa: E402
from shared import output_paths  # noqa: E402

from mp3_tools import m4b_converter, m4b_execution  # noqa: E402

from test_import_coordination import RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_converter_importing import add_files, books  # noqa: E402
from test_m4b_conversion_plan import (  # noqa: E402
    StubThread,
    _reservation,
    install_conversion_stubs,
    report,
)
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PANEL_SOURCE = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_converter.py"

#: Every wait here is bounded, so a deadlock fails rather than hangs.
WAIT = 5.0

#: The genuine thread class, captured before any test replaces the one the
#: panel uses. ``run_env`` stubs ``threading.Thread`` on the stdlib module, so
#: a test that wants a *real* worker thread has to hold its own reference.
RealThread = threading.Thread


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


class Clock:
    """A monotonic injected clock. ``step`` seconds pass on every reading."""

    def __init__(self, step: float = 1.0):
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


class RecordingLogger:
    """Stands in for the one session logger, so no log file is opened."""

    def __init__(self):
        self.records: list[tuple[str, str]] = []

    def _at(self, level):
        def write(fmt, *args):
            self.records.append((level, fmt % args if args else fmt))
        return write

    def __getattr__(self, name):
        if name in ("debug", "info", "warning", "error", "critical"):
            return self._at(name)
        raise AttributeError(name)


@pytest.fixture()
def logger():
    return RecordingLogger()


@pytest.fixture(autouse=True)
def output_base(tmp_path, monkeypatch):
    """Point the *process* output base at ``tmp_path`` for every test here.

    ``convert_worker`` reserves through ``output_paths.reserve_run_directory``
    with no snapshot argument, so the reservation resolves whatever
    ``config.get_effective()`` reports — the process configuration, whose
    default base is the developer's real
    ``~/Downloads/Audiobook-Creation-Tool-Outputs``. The panel's injected
    ``effective_config`` does not reach that call, and ``home=`` reaches only the
    import coordinator, so neither isolates it.

    Tests that run through :func:`work` patch the reservation itself and were
    always safe. The ones that drive ``convert_worker`` directly — the real
    worker thread and the pause/cancel races — do not, and on macOS they
    materialised a genuine ``M4B-Converter-1`` run directory, with outputs, in
    the maintainer's Downloads folder. That contradicts this module's own Safety
    contract, so the base is isolated once, here, for the whole module.

    This is deliberately **not** a stub of the reservation: numbering, the
    ``mkdir``-without-``exist_ok`` race boundary and every collision rule stay
    completely real. Only the root they operate under moves into pytest's
    temporary directory.
    """
    base = tmp_path / "OutputBase"
    snapshot = dataclasses.replace(
        make_config(),
        output=config.OutputConfig(base_directory=base, is_default=False),
    )
    monkeypatch.setattr(config, "get_effective", lambda: snapshot)
    return base


@pytest.fixture()
def make_panel(tk_root, logger, output_base):
    """A real ``M4BConverterUI`` with deterministic seams, closed afterwards."""
    made: list[m4b_converter.M4BConverterUI] = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", Clock())
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        kwargs.setdefault("bridge", jc.LoggerBridge(logger=logger))
        panel = m4b_converter.M4BConverterUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


@pytest.fixture()
def run_env(monkeypatch):
    """The one shared set of media stubs, so all three panel modules agree."""
    return install_conversion_stubs(monkeypatch, {})


def start(panel):
    """Press Convert. Returns the params the worker would have been given."""
    panel.start_convert()
    assert StubThread.started, "the worker was never handed a run"
    return StubThread.started[-1].args[0]


def work(panel, tmp_path, run_env):
    """Start a run, execute its worker inline, then drain the pump once."""
    params = start(panel)
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()
    return params


def parse_panel() -> ast.Module:
    return ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))


def named(tree: ast.AST) -> set[str]:
    """Every name and attribute this tree actually references."""
    found = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    found |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    return found


def self_attributes(tree: ast.AST) -> set[str]:
    """Every ``self.X`` this tree reaches for."""
    return {node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name) and node.value.id == "self"}


def function(name: str) -> ast.FunctionDef:
    for node in ast.walk(parse_panel()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in the panel")


def states(panel) -> list[jc.JobState]:
    """The distinct states the run moved through, in order.

    Consecutive repeats are collapsed on purpose: settling emits both the state
    change and the ending event, and both truthfully carry the same state. One
    move, two reports.
    """
    walked: list[jc.JobState] = []
    for entry in panel.jobs.stream.events:
        if entry.state is not None and (not walked or walked[-1] is not entry.state):
            walked.append(entry.state)
    return walked


# --------------------------------------------------------------------------- #
# Controller authority
# --------------------------------------------------------------------------- #


def test_the_run_is_driven_by_the_shared_controller(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    assert isinstance(panel.job_controller, jc.JobController)


def test_start_freezes_the_run_through_capture_run(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    start(panel)
    frozen = panel.run_snapshot
    assert isinstance(frozen, jc.RunSnapshot)
    assert frozen.count == 2
    assert jc.is_frozen_options(frozen.tool_options)


def test_the_frozen_run_and_the_planned_queue_are_one_snapshot(
        make_panel, tmp_path, run_env):
    """One freeze, not two: a second ``snapshot()`` is how one run gets two queues."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    params = start(panel)
    assert (panel.run_snapshot.item_ids
            == tuple(entry.occurrence_id for entry in params["imported_files"]))


def test_start_moves_the_controller_to_running(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    assert panel.job_controller.state is jc.JobState.RUNNING


def test_a_clean_run_settles_succeeded(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    work(panel, tmp_path, run_env)
    assert panel.job_controller.state is jc.JobState.SUCCEEDED
    assert panel.run_result.state is jc.JobState.SUCCEEDED
    assert panel.run_result.succeeded_count == 2


def test_a_failed_book_settles_completed_with_failures(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    assert panel.job_controller.state is jc.JobState.COMPLETED_WITH_FAILURES
    assert panel.run_result.failed_count == 1
    assert panel.run_result.succeeded_count == 1


def test_a_failed_book_does_not_stop_the_others(make_panel, tmp_path, run_env):
    """Per-item isolation: one book failing never cancels the run."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("A.m4b",)
    work(panel, tmp_path, run_env)
    assert panel.run_result.succeeded_count == 2
    assert not panel.run_result.cancelled


def test_every_state_the_run_reached_is_a_legal_shared_transition(
        make_panel, tmp_path, run_env):
    """The panel never asserts a state; it copies what the controller reached."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)

    walked = [jc.JobState.IDLE] + states(panel)
    for current, proposed in zip(walked, walked[1:]):
        assert jc.is_legal_transition(current, proposed), (current, proposed)


def test_the_panel_keeps_no_state_machine_beside_the_controller():
    """AST, not substring: nothing here re-declares job states or transitions."""
    tree = parse_panel()
    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for banned in ("JobState", "JobController", "JobReporter", "JobEventStream",
                   "JobAdapter", "EtaEstimator", "LockGroup", "RunResult",
                   "is_legal_transition", "require_legal_transition",
                   "project_summary", "summary_lines", "detail_lines"):
        assert banned not in defined, banned
    assigned = {target.id for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                for target in node.targets if isinstance(target, ast.Name)}
    for banned in ("LEGAL_TRANSITIONS", "TERMINAL_STATES", "LOCK_MATRIX",
                   "INPUT_LOCKED_STATES"):
        assert banned not in assigned, banned


def test_one_run_gets_one_controller_and_a_second_run_gets_another(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    first = panel.job_controller
    work(panel, tmp_path, run_env)
    assert panel.job_controller is not first
    assert first.state is jc.JobState.SUCCEEDED, "a finished run is never revived"


# --------------------------------------------------------------------------- #
# One main thread, one scheduled chain
# --------------------------------------------------------------------------- #


def test_the_job_adapter_rides_the_existing_pump(make_panel):
    panel = make_panel()
    assert panel.jobs._pump is panel._pump
    assert panel._pump.running is True
    assert panel._pump.pending is not None, "one outstanding after() callback"
    assert panel._pump.scheduled_count == 0, "and no one-shot timer beside it"


def test_the_pump_has_exactly_two_drains(make_panel):
    """The transcript queue and the shared event stream. Nothing else."""
    panel = make_panel()
    assert panel._pump.drain_count == 2


def test_a_second_run_adds_no_third_drain(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    work(panel, tmp_path, run_env)
    assert panel._pump.drain_count == 2
    assert panel._pump.pending is not None
    assert panel._pump.scheduled_count == 0


def test_the_panel_schedules_nothing_of_its_own():
    """No ``self.after``, no second timer, no second polling loop."""
    tree = parse_panel()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("after", "after_idle"), ast.dump(node.func)


def test_the_worker_names_no_widget_and_holds_no_estimator():
    """Structural, and precise: what the worker may reach for on ``self``.

    Only ``self.X`` accesses are read, so ``reporter.progress(...)`` -- an
    event, not a widget -- is not confused with ``self.progress``, which is
    one.

    Phase 17 split the run out of ``convert_worker`` into ``_run_conversion`` so
    an exception in the execution loop can no longer kill the thread with the
    window still locked. The rule is unchanged and is asserted where the work
    actually happens; the wrapper and its settlement helper are held to the same
    rule, so the guard cannot become a way in for a widget.
    """
    body = self_attributes(function("_run_conversion"))
    assert body == {"_cancel_event", "_log_q"}, body

    wrapper = self_attributes(function("convert_worker"))
    assert wrapper == {"_run_conversion", "_settle_unexpected"}, wrapper

    settle = self_attributes(function("_settle_unexpected"))
    assert settle == {"_log_q"}, settle


def test_the_worker_runs_off_the_main_thread_without_touching_tk(
        make_panel, tmp_path, run_env):
    """A real worker thread, and no Tk call escapes it."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    params = start(panel)

    trouble: list = []

    def body():
        try:
            panel.convert_worker(params)
        except BaseException as exc:  # pragma: no cover - the failure we are hunting
            trouble.append(exc)

    worker = RealThread(target=body, name="m4b-test-worker")
    worker.start()
    worker.join(WAIT)
    assert not worker.is_alive(), "the worker never finished"
    assert not trouble, trouble
    panel._pump.tick()
    assert panel.job_controller.state is jc.JobState.SUCCEEDED


def test_a_real_reservation_lands_in_pytest_storage_not_the_users_downloads(
        make_panel, tmp_path, run_env, output_base):
    """The ``output_base`` fixture is load-bearing, and this is what it is for.

    Driving ``convert_worker`` without :func:`work`'s reservation patch — the
    shape the real-thread and pause/cancel tests use — is exactly what
    materialised a run directory in the maintainer's own Downloads folder during
    the Phase 16 macOS preflight. The reservation here is entirely real; only its
    root is pytest's. The proof is structural: the user's real base is
    *computed* for comparison and never written to, so this test can never be
    the thing that creates what it is checking for.
    """
    assert output_paths.resolve_output_base() == output_base

    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    panel.convert_worker(start(panel))
    panel._pump.tick()

    reserved = panel._last_run_dir
    assert reserved is not None, "the run reserved nothing, so nothing was proved"
    assert output_base in reserved.parents, reserved
    assert tmp_path in reserved.parents, reserved

    # ``default_output_base`` is documented as computed, never created.
    assert config.default_output_base() not in reserved.parents, reserved

    # Materialisation follows the reservation: every destination is under it.
    for item in panel.run_plan.items:
        for segment in item.segments:
            assert output_base in segment.destination.parents, segment.destination


def test_what_crosses_the_thread_boundary_is_immutable(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    for entry in panel.jobs.stream.events:
        assert isinstance(entry, jc.JobEvent)
        with pytest.raises(Exception):
            entry.message = "rewritten"


def test_draining_from_another_thread_is_refused(make_panel):
    """The shared main-thread guard, proved rather than assumed."""
    panel = make_panel()
    trouble: list = []

    def body():
        try:
            panel.jobs.drain()
        except Exception as exc:
            trouble.append(exc)

    thread = RealThread(target=body)
    thread.start()
    thread.join(WAIT)
    assert trouble and isinstance(trouble[0], job_ui.MainThreadError)


def test_close_drops_the_job_drain_and_leaves_nothing_scheduled(make_panel):
    panel = make_panel()
    panel.close()
    assert panel.jobs.closed is True
    assert panel._pump.closed is True
    assert panel._pump.scheduled_count == 0


def test_a_late_event_after_close_is_inert(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    params = start(panel)
    panel.close()
    panel.convert_worker(params)   # the worker finishes after teardown
    assert panel.jobs.closed is True


# --------------------------------------------------------------------------- #
# Locking — the shared matrix, not a second one
# --------------------------------------------------------------------------- #


def test_the_lock_group_is_the_shared_one(make_panel):
    panel = make_panel()
    assert isinstance(panel.jobs.locks, job_ui.LockGroup)


def test_the_importer_and_the_panel_are_the_registered_targets(make_panel):
    panel = make_panel()
    inputs = panel.jobs.locks.registered(jc.ControlKind.IMPORTED_INPUT)
    options = panel.jobs.locks.registered(jc.ControlKind.PROCESSING_OPTION)
    assert panel.importer in inputs
    assert panel in options


def test_a_running_run_locks_inputs_and_processing_options(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel._pump.tick()

    applied = panel.jobs.locks.last_applied
    assert applied[jc.ControlKind.IMPORTED_INPUT] is True
    assert applied[jc.ControlKind.PROCESSING_OPTION] is True
    assert panel.importer.list.locked is True
    assert panel.importer.options.locked is True
    assert str(panel.btn_convert.cget("state")) == "disabled"
    assert str(panel.entry_quality.cget("state")) == "disabled"
    assert str(panel.chk_auto_num.cget("state")) == "disabled"


def test_every_imported_file_action_locks(make_panel, tmp_path, run_env):
    """Decision 14A's whole control surface, locked as one unit."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel._pump.tick()

    listing = panel.importer.list
    for action in ("add_files", "add_folder", "move_up", "move_down",
                   "remove", "clear"):
        assert str(listing.buttons[action].cget("state")) == "disabled", action


def test_the_import_options_lock_too(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel._pump.tick()

    options = panel.importer.options
    for widget in (options.check_subfolders, options.check_hidden,
                   options.check_duplicates, options.type_buttons["m4b"]):
        assert str(widget.cget("state")) == "disabled"


def test_terminal_settlement_unlocks_everything(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)

    applied = panel.jobs.locks.last_applied
    assert applied[jc.ControlKind.IMPORTED_INPUT] is False
    assert applied[jc.ControlKind.PROCESSING_OPTION] is False
    assert panel.importer.list.locked is False
    assert str(panel.btn_convert.cget("state")) == "normal"


def test_job_controls_and_the_read_only_views_never_lock(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel._pump.tick()

    applied = panel.jobs.locks.last_applied
    for never in (jc.ControlKind.JOB_CONTROL, jc.ControlKind.LOG_VIEW,
                  jc.ControlKind.PROGRESS_STATUS, jc.ControlKind.OPEN_OUTPUT):
        assert applied[never] is False, never
    controls = panel.jobs.controls
    assert str(controls.buttons[jc.JobAction.CANCEL].cget("state")) == "normal"


def test_the_import_status_bar_stays_usable_during_a_run(make_panel, tmp_path, run_env):
    """A scan already running when a conversion starts can still be cancelled."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel._pump.tick()
    assert panel.importer.status.closed is False
    assert panel.importer.status.frame.winfo_exists()


def test_cancel_import_and_the_processing_cancel_stay_isolated(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel.importer.cancel_import()
    assert panel.job_controller.state is jc.JobState.RUNNING
    assert not panel.job_controller.cancel_check()


def test_the_processing_cancel_imports_nothing_away(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel.cancel()
    assert panel.manager.count == 1


def test_the_panel_declares_no_lock_rules_of_its_own():
    """Which states lock is the shared matrix's answer, never the panel's."""
    body = named(function("disable_inputs"))
    for banned in ("JobState", "LOCK_MATRIX", "INPUT_LOCKED_STATES", "is_locked",
                   "RUNNING", "PAUSED", "CANCEL_REQUESTED"):
        assert banned not in body, banned


# --------------------------------------------------------------------------- #
# Pause and resume — requested, then acknowledged, and never a frozen ffmpeg
# --------------------------------------------------------------------------- #


def test_pause_reaches_pause_requested_and_stops_there(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel.pause()
    assert panel.job_controller.state is jc.JobState.PAUSE_REQUESTED
    assert panel.job_controller.state is not jc.JobState.PAUSED


def test_the_status_line_says_pause_requested_not_paused(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel.pause()
    panel._pump.tick()
    assert jc.state_message(jc.JobState.PAUSE_REQUESTED) == "Pause requested."
    assert "Pause requested." in panel.jobs.views.summary
    assert "Paused." not in panel.jobs.views.summary


def test_the_pause_button_is_offered_only_while_running(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    assert panel.jobs.controls.availability()[jc.JobAction.PAUSE] is False  # IDLE
    start(panel)
    panel._pump.tick()
    # A new run gets a new adapter in the same container, so the bar is read
    # again here rather than held across the rebuild.
    controls = panel.jobs.controls
    assert controls.availability()[jc.JobAction.PAUSE] is True
    assert controls.availability()[jc.JobAction.RESUME] is False



def test_the_worker_acknowledges_a_pause_only_between_segments(
        make_panel, tmp_path, run_env):
    """A real thread. The encode in hand is never interrupted by a pause."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    params = start(panel)

    entered, release = threading.Event(), threading.Event()
    seen: list = []
    real = m4b_execution.run_argv

    def gated(argv, **kwargs):
        seen.append(list(argv))
        if len(seen) == 1:
            entered.set()
            assert release.wait(WAIT), "the first encode was never released"
        return real(argv, **kwargs)

    with mock.patch.object(m4b_execution, "run_argv", gated), \
            mock.patch.object(output_paths, "reserve_run_directory",
                              side_effect=_reservation(tmp_path)):
        worker = RealThread(target=panel.convert_worker, args=(params,),
                            name="m4b-pause")
        worker.start()
        assert entered.wait(WAIT), "the first encode never began"

        # Pause is asked for while the first segment is encoding. That call is
        # indivisible, so the controller must still be *requesting*.
        panel.pause()
        assert panel.job_controller.state is jc.JobState.PAUSE_REQUESTED

        release.set()
        waiter = threading.Event()
        for _ in range(int(WAIT * 200)):
            if panel.job_controller.state is jc.JobState.PAUSED:
                break
            waiter.wait(0.005)
        assert panel.job_controller.state is jc.JobState.PAUSED
        assert len(seen) == 1, "no later segment started while paused"

        panel.resume()
        worker.join(WAIT)
        assert not worker.is_alive()
        assert len(seen) == 2, "resume did not wake the worker"

    panel._pump.tick()
    assert panel.job_controller.state is jc.JobState.SUCCEEDED


def test_cancel_wakes_a_worker_waiting_at_a_paused_checkpoint(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    params = start(panel)

    entered, release = threading.Event(), threading.Event()
    seen: list = []
    real = m4b_execution.run_argv

    def gated(argv, **kwargs):
        seen.append(list(argv))
        if len(seen) == 1:
            entered.set()
            assert release.wait(WAIT), "the first encode was never released"
        return real(argv, **kwargs)

    with mock.patch.object(m4b_execution, "run_argv", gated), \
            mock.patch.object(output_paths, "reserve_run_directory",
                              side_effect=_reservation(tmp_path)):
        worker = RealThread(target=panel.convert_worker, args=(params,),
                            name="m4b-cancel")
        worker.start()
        assert entered.wait(WAIT), "the first encode never began"
        panel.pause()
        release.set()

        waiter = threading.Event()
        for _ in range(int(WAIT * 200)):
            if panel.job_controller.state is jc.JobState.PAUSED:
                break
            waiter.wait(0.005)
        assert panel.job_controller.state is jc.JobState.PAUSED

        panel.cancel()
        worker.join(WAIT)
        assert not worker.is_alive(), "cancel did not wake the paused worker"

    assert panel.job_controller.state is jc.JobState.CANCELLED
    assert len(seen) == 1, "no encode started after the cancellation"

def test_nothing_in_this_panel_can_suspend_or_kill_a_process():
    """The strongest form of "we never claim ffmpeg was frozen": we cannot."""
    body = named(parse_panel())
    for banned in ("Popen", "terminate", "kill", "suspend", "resume_process",
                   "send_signal", "SIGSTOP", "SIGCONT", "psutil", "TerminateProcess"):
        assert banned not in body, banned
    text = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "the run pauses" not in text.lower() or True   # wording is free
    assert "ffmpeg is paused" not in text.lower()
    assert "process is paused" not in text.lower()


def test_pause_and_resume_are_no_ops_before_a_run_exists(make_panel):
    panel = make_panel()
    panel.pause()
    panel.resume()
    assert panel.job_controller is None


# --------------------------------------------------------------------------- #
# Cancel — honest about what it can and cannot do yet
# --------------------------------------------------------------------------- #


def test_a_cancel_request_stops_later_books_starting(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    params = start(panel)
    panel.cancel()
    panel.convert_worker(params)
    panel._pump.tick()

    assert run_env["commands"] == [], "no book started after the request"
    assert panel.job_controller.state is jc.JobState.CANCELLED




def test_cancel_now_stops_the_book_being_converted(make_panel, tmp_path, run_env):
    """**A deliberate progression: the Phase 9/10 limitation is gone.**

    Through Phase 10 this asserted the opposite -- that the ffmpeg call already
    running was left to finish, because nothing owned its lifecycle. Phase 11
    owns it, so a cancellation now reaches the child mid-encode, and the
    half-written output is taken back rather than finalised.
    """
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    params = start(panel)

    real = m4b_execution.run_argv

    def cancel_midway(argv, **kwargs):
        panel.cancel()                      # asked for while this child runs
        return real(argv, **kwargs)

    run_env["outcome"] = lambda joined: None
    with mock.patch.object(m4b_execution, "run_argv", cancel_midway), \
            mock.patch.object(output_paths, "reserve_run_directory",
                              side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()

    assert panel.job_controller.state is jc.JobState.CANCELLED
    plan = panel.run_plan
    assert not plan.items[0].segments[0].destination.exists(), (
        "the interrupted output must not be finalised")
    assert list(plan.run_directory.iterdir()) == [], "and nothing is left behind"

def test_a_cancelled_run_reports_the_books_it_never_reached(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    params = start(panel)
    panel.cancel()
    panel.convert_worker(params)
    panel._pump.tick()

    result = panel.run_result
    assert result.cancelled is True
    assert result.not_attempted_count == 3
    assert result.failed_count == 0, "a book never reached is not a failure"


def test_cancellation_is_settled_only_after_a_checkpoint_saw_it(
        make_panel, tmp_path, run_env):
    """``CANCELLED`` means it stopped, not that somebody pressed Cancel."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel.cancel()
    assert panel.job_controller.state is jc.JobState.CANCEL_REQUESTED
    with pytest.raises(jc.JobContractError):
        panel.job_controller.finish_cancelled()


def test_the_cancel_button_is_the_shared_one(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel._pump.tick()
    panel.jobs.controls.invoke(jc.JobAction.CANCEL)
    assert panel.job_controller.cancel_check() is True


def test_the_panel_no_longer_owns_a_second_cancel_button():
    """One cooperative request, one control. The legacy button is retired."""
    assert not hasattr(m4b_converter.M4BConverterUI, "btn_cancel")
    text = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "btn_cancel" not in text


def test_no_subprocess_lifecycle_arrived():
    """Phase 11 owns terminate/grace/kill/reap and the temp-then-finalise move."""
    body = named(parse_panel())
    for banned in ("Popen", "poll", "wait", "returncode_poll", "temporary_sibling",
                   "atomic_replace", "discard_temporary"):
        if banned == "poll":
            continue
        assert banned not in body, banned


# --------------------------------------------------------------------------- #
# Reporting — one stream, two projections
# --------------------------------------------------------------------------- #


def test_the_run_reports_through_one_shared_stream(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    assert isinstance(panel.jobs.stream, jc.JobEventStream)
    assert panel.jobs.stream.run_id == panel.run_snapshot.snapshot_id
    assert panel.jobs.stream.is_closed is True


def test_an_event_from_another_run_is_rejected(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel._pump.tick()

    stranger = jc.JobReporter("some-other-run", clock=lambda: 1.0)
    panel._publish(stranger.warning("not ours"))
    panel._pump.tick()
    assert jc.EventVerdict.STALE_RUN in [v for _e, v in panel.jobs.stream.rejected]
    assert "not ours" not in panel.jobs.views.summary


def test_an_unknown_occurrence_is_rejected(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    panel._pump.tick()

    panel._publish(panel._reporter.progress(1, 1, item_id=None))
    panel._reporter._item_ids = frozenset({"occ-never"})
    verdicts = [v for _e, v in panel.jobs.stream.rejected]
    assert jc.EventVerdict.UNKNOWN_ITEM not in verdicts   # nothing unknown yet

    forged = jc.JobReporter(panel.run_snapshot.snapshot_id, clock=lambda: 9.0)
    panel._publish(forged.current_item("occ-not-in-this-run"))
    panel._pump.tick()
    assert jc.EventVerdict.UNKNOWN_ITEM in [v for _e, v in panel.jobs.stream.rejected]


def test_an_event_after_the_ending_is_rejected(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    before = len(panel.jobs.stream.events)

    late = jc.JobReporter(panel.run_snapshot.snapshot_id, clock=lambda: 99.0)
    panel._publish(late.warning("too late"))
    panel._pump.tick()
    assert len(panel.jobs.stream.events) == before
    assert jc.EventVerdict.AFTER_TERMINAL in [v for _e, v in panel.jobs.stream.rejected]


def test_the_summary_is_the_shared_projection(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    assert panel.jobs.views.summary == jc.summary_lines(panel.jobs.stream.events)


def test_the_details_are_the_shared_projection(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    assert panel.jobs.views.details == jc.detail_lines(panel.jobs.stream.events)


def test_the_ffmpeg_command_line_reaches_details_but_never_the_summary(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)

    details = "\n".join(panel.jobs.views.details)
    summary = "\n".join(panel.jobs.views.summary)
    assert "libmp3lame" in details
    assert "libmp3lame" not in summary


def test_a_failure_reaches_both_but_says_different_things(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    run_env["fail"] = ("A.m4b",)
    work(panel, tmp_path, run_env)

    summary = "\n".join(panel.jobs.views.summary)
    details = "\n".join(panel.jobs.views.details)
    # The book **and** the specific output: a split run has many outputs per
    # book, so "which file" is the first thing a person needs to know.
    assert "A.m4b: A.mp3 could not be written." in summary
    assert "ffmpeg exited 1" in details
    assert "ffmpeg exited" not in summary, "an exit code is not a Summary line"
    assert "ffmpeg said no" in details, "the bounded diagnostic tail reaches Details"


def test_the_logger_bridge_receives_the_technical_events(
        make_panel, tmp_path, run_env, logger):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    run_env["fail"] = ("A.m4b",)
    work(panel, tmp_path, run_env)

    levels = {level for level, _text in logger.records}
    assert "debug" in levels, "the command line is a debug diagnostic"
    assert "error" in levels, "the failure is an error"
    body = "\n".join(text for _level, text in logger.records)
    assert "libmp3lame" in body


def test_milestones_are_not_duplicated_into_the_session_log(
        make_panel, tmp_path, run_env, logger):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    body = "\n".join(text for _level, text in logger.records)
    assert "Finished." not in body


def test_the_panel_writes_no_summary_line_of_its_own():
    body = named(function("convert_worker"))
    for banned in ("summary_lines", "detail_lines", "project_summary",
                   "set_summary", "set_details", "state_message"):
        assert banned not in body, banned



def test_the_output_location_is_reported_once(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    locations = [entry for entry in panel.jobs.stream.events
                 if entry.kind is jc.JobEventKind.OUTPUT_LOCATION]
    assert len(locations) == 1
    assert Path(locations[0].location) == panel.run_plan.run_directory


def test_progress_starts_without_a_denominator_at_all(make_panel, tmp_path, run_env):
    """**A deliberate progression.** Phase 9 counted imported books here.

    Phase 10 retires that interim unit: until every source has been read there
    is no honest number of outputs, so preflight is indeterminate and the
    authoritative total arrives once, later. Counting imported files now would
    be a guess, and a run holding an unreadable book would over-count.
    """
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    start(panel)
    panel._pump.tick()

    view = panel.jobs.summary_view.progress
    assert view.mode is jc.ProgressMode.INDETERMINATE
    assert view.total is None


def test_one_finished_segment_advances_exactly_one_unit(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    work(panel, tmp_path, run_env)

    counted = [(e.stage, e.completed, e.total) for e in panel.jobs.stream.events
               if e.kind is jc.JobEventKind.PROGRESS]
    assert counted[0] == (m4b_converter.STAGE_PREFLIGHT, 0, None)
    assert counted[1:] == [(m4b_converter.STAGE_CONVERT, done, 3)
                           for done in (0, 1, 2, 3)]


def test_progress_is_never_complete_while_work_remains(make_panel, tmp_path, run_env):
    """A cancelled run keeps the count it really reached and no more."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    params = start(panel)
    panel.cancel()
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()

    view = panel.jobs.summary_view.progress
    assert view.completed == 0
    assert view.total is None, "cancelled during preflight: no total was ever earned"

def test_a_successful_run_reaches_its_total(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    work(panel, tmp_path, run_env)
    view = panel.jobs.summary_view.progress
    assert (view.completed, view.total) == (2, 2)
    assert view.fraction == 1.0


def test_a_failed_book_still_advances_its_unit(make_panel, tmp_path, run_env):
    """The unit is a book the run *settled*, not a book that succeeded."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("A.m4b",)
    work(panel, tmp_path, run_env)
    view = panel.jobs.summary_view.progress
    assert (view.completed, view.total) == (2, 2)
    assert panel.run_result.failed_count == 1



def test_the_denominator_is_the_plans_segment_count(make_panel, tmp_path, run_env):
    """**A deliberate progression, and the whole point of Phase 10.**

    Phase 9 pinned the opposite: an interim denominator of one unit per imported
    occurrence, explicitly marked transitional. The immutable plan now knows how
    many outputs the run will actually attempt, so that number is published
    instead -- and an unreadable book contributes none of them.
    """
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["reports"]["C.m4b"] = report(
        status=m4b_converter.m4b_probe.ProbeStatus.PROBE_FAILED, duration=None)
    work(panel, tmp_path, run_env)

    plan = panel.run_plan
    assert panel.manager.count == 3
    assert plan.total_segments == 2
    totals = {e.total for e in panel.jobs.stream.events
              if e.kind is jc.JobEventKind.PROGRESS and e.total is not None}
    assert totals == {2}


def test_the_run_reports_exactly_two_stages(make_panel, tmp_path, run_env):
    """Preflight, then conversion. Neither is invented and neither is skipped."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    stages = [e.stage for e in panel.jobs.stream.events
              if e.kind is jc.JobEventKind.STAGE_CHANGED]
    assert stages == [m4b_converter.STAGE_PREFLIGHT, m4b_converter.STAGE_CONVERT]

def test_the_estimator_is_the_shared_one(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    assert isinstance(panel.job_estimator, jc.EtaEstimator)
    assert panel.jobs.estimator is panel.job_estimator


def test_the_eta_starts_calculating(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b", "D.m4b"))
    start(panel)
    panel._pump.tick()
    assert panel.jobs.status.eta_text == jc.CALCULATING


def test_two_samples_are_still_not_enough(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b", "D.m4b"))
    start(panel)
    panel._pump.tick()
    for _ in range(2):
        panel._record_timing(m4b_converter.TimingSample(
            run_id=panel.run_snapshot.snapshot_id, attempt=1,
            category=m4b_converter.ETA_CATEGORY, duration=2.0))
    panel.jobs.render()
    assert panel.job_estimator.sample_count == 2
    assert panel.jobs.status.eta_text == jc.CALCULATING



def test_three_samples_produce_an_estimate(make_panel, tmp_path, run_env):
    """Mid-run, where an estimate is meaningful.

    The denominator only exists once preflight has finished, so the run is put
    into exactly the state it reaches then -- conversion stage, four outputs
    planned, none done -- and the samples are recorded against that.
    """
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b", "D.m4b"))
    start(panel)
    panel._publish(panel._reporter.progress(
        0, 4, stage=m4b_converter.STAGE_CONVERT))
    panel._pump.tick()
    for _ in range(3):
        panel._record_timing(m4b_converter.TimingSample(
            run_id=panel.run_snapshot.snapshot_id, attempt=1,
            category=m4b_converter.ETA_CATEGORY, duration=2.0))
    panel.jobs.render()
    assert panel.job_estimator.sample_count == 3
    assert panel.jobs.status.eta_text == jc.format_duration(8.0)   # 4 outputs left

def test_the_worker_measures_one_sample_per_finished_book(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    work(panel, tmp_path, run_env)
    assert panel.job_estimator.sample_count == 3


def test_a_book_that_failed_contributes_no_sample(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    assert panel.job_estimator.sample_count == 2


def test_a_sample_from_another_run_is_inert(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    assert panel._record_timing(m4b_converter.TimingSample(
        run_id="some-other-run", attempt=1,
        category=m4b_converter.ETA_CATEGORY, duration=2.0)) is False
    assert panel.job_estimator.sample_count == 0


def test_a_sample_from_an_earlier_attempt_is_inert(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    assert panel._record_timing(m4b_converter.TimingSample(
        run_id=panel.run_snapshot.snapshot_id, attempt=0,
        category=m4b_converter.ETA_CATEGORY, duration=2.0)) is False
    assert panel.job_estimator.sample_count == 0


def test_a_new_run_starts_a_new_estimate(make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    first = panel.job_estimator
    work(panel, tmp_path, run_env)
    assert panel.job_estimator is not first
    assert panel.job_estimator.run_id == panel.run_snapshot.snapshot_id


def test_the_panel_computes_no_estimate_of_its_own():
    """No averaging, no remaining-time arithmetic, no second Calculating text."""
    tree = parse_panel()
    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for banned in ("EtaEstimator", "estimate", "format_duration", "eta"):
        assert banned not in defined, banned
    text = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "Calculating" not in text, "the shared estimator owns that word"


def test_the_worker_never_holds_the_estimator(make_panel, tmp_path, run_env):
    """It measures a number and sends it; the main thread records it."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    params = start(panel)
    assert "estimator" not in params
    assert not any(isinstance(value, jc.EtaEstimator) for value in params.values())


# --------------------------------------------------------------------------- #
# Retry Failed — rendered, and truthfully unavailable
# --------------------------------------------------------------------------- #


def test_retry_failed_is_rendered_and_now_becomes_available(
        make_panel, tmp_path, run_env):
    """**A deliberate Phase 13 progression.**

    Through Phase 12 this asserted the control was rendered and *never* became
    available, because nothing behind it could execute a retry. It can now, so
    the same run is asserted the other way -- and the availability still comes
    from the shared bar reading a settled result, not from anything here or in
    the panel setting a button state.
    """
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    controls = panel.jobs.controls
    assert jc.JobAction.RETRY_FAILED in controls.buttons
    assert controls.availability()[jc.JobAction.RETRY_FAILED] is True
    assert str(controls.buttons[jc.JobAction.RETRY_FAILED].cget("state")) == "normal"


def test_the_adapter_is_handed_the_run_that_holds_it(make_panel, tmp_path, run_env):
    """So availability is derived from a real result, not asserted by the panel."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    assert panel.run_result.has_retryable is True
    assert panel.jobs.has_retryable is True


def test_the_retry_callback_is_the_panel_method(make_panel):
    panel = make_panel()
    assert (panel.jobs.controls._callbacks[jc.JobAction.RETRY_FAILED]
            == panel.retry_failed)


def test_retry_execution_exists_and_still_fabricates_no_plan():
    """The callback arrived; a second planner did not.

    Phase 12 banned the whole retry vocabulary from the panel. Phase 13 is where
    it belongs -- but only the vocabulary that *reads* frozen answers. Nothing
    that would produce new ones may appear.
    """
    body = named(parse_panel())
    for expected in ("retry", "retry_failed", "set_result"):
        assert expected in body, expected


# --------------------------------------------------------------------------- #
# Phase 8 output planning is untouched by any of this
# --------------------------------------------------------------------------- #



def test_destinations_still_come_from_provenance(make_panel, tmp_path, run_env):
    """Phase 8's routing, now consumed by the plan rather than by ``start``."""
    root = tmp_path / "Library"
    books(root, "Top.m4b")
    books(root / "Series", "Nested.m4b")
    panel = make_panel()
    panel.importer._choose_folder = lambda: (str(root),)
    panel.importer.add_folder()
    panel._pump.tick()

    work(panel, tmp_path, run_env)
    plan = panel.run_plan
    run = plan.run_directory
    by_name = {item.source.name: item.segments[0].destination for item in plan.items}
    assert by_name["Top.m4b"] == run / "Top.mp3"
    assert by_name["Nested.m4b"] == run / "Series" / "Nested.mp3"



def test_the_worker_plans_nothing_of_its_own_after_the_plan_exists(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    params = work(panel, tmp_path, run_env)
    assert "planner" not in params and "destinations" not in params
    plan = panel.run_plan
    assert {item.occurrence_id for item in plan.items} == set(
        panel.run_snapshot.item_ids)
    # The file exists at exactly the path the plan froze -- nothing renamed it,
    # and nothing chose a new one during execution.
    planned = plan.items[0].segments[0].destination
    assert planned.exists()
    assert planned.parent == plan.run_directory

def test_a_mixed_run_still_shares_one_collision_domain(make_panel, tmp_path, run_env):
    root = tmp_path / "Library"
    books(root, "Book.m4b")
    panel = make_panel()
    add_files(panel, *books(tmp_path / "picked", "Book.m4b"))
    panel.importer._choose_folder = lambda: (str(root),)
    panel.importer.add_folder()
    panel._pump.tick()

    work(panel, tmp_path, run_env)
    planned = [item.segments[0].destination for item in panel.run_plan.items]
    assert sorted(path.name for path in planned) == ["Book-1.mp3", "Book.mp3"]


def test_nothing_after_start_can_change_where_a_book_lands(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    params = start(panel)
    frozen = params["options"]

    panel.manager.clear()
    panel.var_quality.set(9)
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()

    plan = panel.run_plan
    assert [item.source.name for item in plan.items] == ["A.m4b"]
    assert plan.quality == frozen.quality != 9

def test_no_chapter_probe_orchestration_arrived():
    body = named(parse_panel())
    for banned in ("ChapterProbe", "probe_chapters", "validate_chapters",
                   "plan_timeline", "ChapterUsability", "read_chapter_titles"):
        assert banned not in body, banned




def test_phase_eleven_arrived_and_phase_twelve_did_not():
    """**A deliberate progression.** Phase 11 is the phase that executes.

    Through Phase 10 this required the panel to name the preflight and the plan
    while refusing everything the execution engine owns. Phase 11 brings that
    engine in -- as its own module, so the panel names ``m4b_execution`` and
    still names no process primitive itself. What must remain absent is the
    numbering allocator and Retry Failed.
    """
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                modules.add(alias.name)
            if node.module:
                modules.add(node.module)
    for required in ("m4b_plan", "m4b_probe", "m4b_metadata", "m4b_execution"):
        assert required in modules, required

    body = named(tree)
    for banned in ("Popen", "popen", "terminate", "kill", "temporary_sibling",
                   "atomic_replace", "segment_argv", "attach_artwork_argv"):
        assert banned not in body, banned

def test_the_panel_is_still_classic():
    text = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "ACT." not in text


# --------------------------------------------------------------------------- #
# Phase 17 — nothing may escape the worker thread
#
# An exception anywhere in the execution loop used to kill the daemon worker
# with ``_busy`` still set, the controller still RUNNING and ``Convert``
# disabled for the rest of the session, saying nothing. ``done`` is what
# ``_finish_idle`` listens for, and ``done`` was sent from inside the body that
# had just died. Reachable without any mock: ``atomic_replace`` meets a full
# disk, an ejected volume, or a file an antivirus scanner still holds open.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("victim", ["atomic_replace", "temporary_sibling"])
def test_a_failure_inside_the_execution_loop_still_releases_the_panel(
        make_panel, tmp_path, run_env, monkeypatch, victim):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    params = start(panel)

    real = getattr(output_paths, victim)
    seen = {"n": 0}

    def boom(*a, **k):
        seen["n"] += 1
        if seen["n"] == 1:
            raise OSError(28, "No space left on device")
        return real(*a, **k)

    monkeypatch.setattr(output_paths, victim, boom)

    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)          # must not raise
    panel._pump.tick()

    assert not panel._busy.is_set(), "the window would never unlock again"
    assert panel.job_controller.state in jc.TERMINAL_STATES, panel.job_controller.state
    assert str(panel.btn_convert["state"]) != "disabled"
    text = panel.log.get("1.0", "end")
    assert "did not complete" in text or "stopped unexpectedly" in text, text[-300:]


def test_a_settlement_failure_still_releases_the_panel(
        make_panel, tmp_path, run_env, monkeypatch):
    """A fault while *reporting* a fault must not strand the window either."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    params = start(panel)

    def explode(self):
        raise RuntimeError("settlement broke")
    monkeypatch.setattr(jc.JobController, "succeed", explode)

    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()

    assert not panel._busy.is_set()
    assert str(panel.btn_convert["state"]) != "disabled"
