"""TTS job-control adoption and output consolidation — v0.6.1 Plan 4, Phase 7.

Phase 6 gave the TTS panel one unified PDF/TXT queue and a state-owning host.
It deliberately stopped there: processing still ran under a bare
``threading.Event`` with a panel-owned progress bar and a panel-owned log, and
``shared/job_control.py`` was asserted *absent*. This phase moves the run onto
the shared foundation.

What these tests are about
--------------------------
* **One run, frozen once.** ``capture_run`` is called once per accepted run.
  After that the worker and every retry read the frozen
  :class:`~shared.job_control.RunSnapshot` and nothing else — not a widget, not
  a ``tk.Variable``, not the live :class:`~shared.importing.ImportedFileManager`,
  not today's configuration.
* **The controller is the only cancellation authority.** Phase 6's second
  ``threading.Event`` is gone. ``CANCELLED`` means the worker acknowledged the
  cancellation at a checkpoint and cleaned up — never "someone pressed Cancel".
* **Pause happens between source files.** Never inside a chapter, a synthesis
  chunk, a PDF extraction or any other indivisible engine operation. "Pause
  requested" stays truthful while the current source finishes.
* **Destinations are keyed by occurrence id.** Retry Failed needs identity, and
  a path is not one: the same file may be in the queue twice, deliberately, with
  two occurrence ids and two collision-safe destinations. A retry reuses the
  destination its original run planned and can never overwrite an earlier
  success.
* **An item failure is not a job failure.** One source that will not convert is
  a :class:`~shared.job_control.FailureRecord` against its occurrence; the run
  continues and settles ``COMPLETED_WITH_FAILURES``, which is what makes Retry
  Failed possible at all.

Determinism
-----------
**No test sleeps.** Most runs execute the worker body inline on this thread with
the pump ticked by hand. The handful that are genuinely about threads gate on
:class:`threading.Event` and wait in bounded steps, so a deadlock fails loudly
at the deadline instead of hanging the suite.

Safety
------
Every fixture is generated under ``tmp_path``. **No synthesis ever runs**: every
engine entry point is stubbed, so nothing reaches Edge TTS over the network,
loads a Kokoro model, or writes real audio. Nothing scans the repository, the
real home directory, an output base or real media.

Scope
-----
Phase 7 is job control and the output/retry contract. Phase 8 (Chatterbox) is
asserted *absent* below, and the conversion engines themselves are asserted
unchanged.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import job_control  # noqa: E402
from shared.job_control import (  # noqa: E402
    ControlKind,
    JobState,
    RunSnapshot,
    is_locked,
)

from tts import epub2tts_gui as panel_module  # noqa: E402

# The Phase 6 module owns the panel fixtures and the engine stubs; reusing them
# keeps one description of "a TtsPanel built safely" rather than two that drift.
from test_tts_importing import (  # noqa: E402,F401
    PANEL_SOURCE,
    WAIT,
    _Stubs,
    make_panel,
    method_named,
    output_base,
    panel_tree,
    sources,
    stubs,
    tk_root,
)

#: The stage name every conversion event and failure record carries. Written as a
#: literal rather than read from the module, so the test states the contract
#: instead of agreeing with whatever the module happens to define.
STAGE = "converting"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _FakeThread:
    """Captures the worker's arguments instead of starting a thread."""

    def __init__(self, kwargs, sink):
        sink["params"] = kwargs["args"][0]
        sink["target"] = kwargs["target"]
        self.daemon = kwargs.get("daemon", False)

    def start(self):
        return None

    def join(self, timeout=None):
        return None


def accept(panel, action=None) -> dict:
    """Accept one run or retry without starting a real thread.

    Returns the captured ``{"params", "target"}``; an empty dict means the panel
    declined to start, which is itself something several tests assert.
    """
    captured: dict = {}
    real_thread = panel_module.threading.Thread
    try:
        panel_module.threading.Thread = lambda **kw: _FakeThread(kw, captured)
        (panel.run_job if action is None else action)()
    finally:
        panel_module.threading.Thread = real_thread
    return captured


def finish(panel, captured: dict) -> dict:
    """Run the captured worker body inline, then drain both pumps' queues."""
    if "target" in captured:
        captured["target"](captured["params"])
    panel._pump.tick()
    return captured.get("params", {})


def run_attempt(panel, action=None, *, before_worker=None) -> dict:
    """Accept a run, optionally interfere, run the worker, drain. Returns params."""
    captured = accept(panel, action)
    if before_worker is not None:
        before_worker(captured)
    return finish(panel, captured)


def wait_for(predicate, message: str, *, panel=None) -> None:
    """Wait for *predicate* in bounded steps, ticking the pump if one is given.

    Not a sleep: a condition that never becomes true fails at the deadline
    rather than passing by luck or hanging the suite.
    """
    deadline = time.monotonic() + WAIT
    gate = threading.Event()
    while time.monotonic() < deadline:
        if panel is not None:
            panel._pump.tick()
        if predicate():
            return
        gate.wait(0.01)
    if panel is not None:
        panel._pump.tick()
    assert predicate(), message


def direct_panel(make_panel, tmp_path, *names, **kwargs):
    """A queue of directly added files only."""
    chosen = sources(tmp_path / "Loose", *names)
    panel = make_panel(choose_files=lambda: chosen, **kwargs)
    panel.importer.add_files()
    return panel, chosen


def folder_panel(make_panel, tmp_path, roots=1, **kwargs):
    """A queue built from one or more imported folder roots."""
    folders = []
    for index in range(roots):
        root = tmp_path / f"Library {index + 1}"
        sources(root, "01.pdf")
        sources(root / "Book A", "02.txt")
        folders.append(root)
    pending = list(folders)

    def choose_folder():
        return (pending.pop(0),) if pending else ()

    panel = make_panel(choose_folder=choose_folder, **kwargs)
    for _ in folders:
        panel.importer.add_folder()
        panel._pump.tick()
    return panel, tuple(folders)


def mixed_panel(make_panel, tmp_path, roots=1, **kwargs):
    """Two directly added files plus one or more folder roots, in one queue."""
    direct = sources(tmp_path / "Loose", "solo.pdf", "notes.txt")
    folders = []
    for index in range(roots):
        root = tmp_path / f"Library {index + 1}"
        sources(root, "01.pdf")
        sources(root / "Book A", "02.txt")
        folders.append(root)
    pending = list(folders)

    def choose_folder():
        return (pending.pop(0),) if pending else ()

    panel = make_panel(choose_files=lambda: direct, choose_folder=choose_folder,
                       **kwargs)
    panel.importer.add_files()
    for _ in folders:
        panel.importer.add_folder()
        panel._pump.tick()
    return panel, direct, tuple(folders)


def relative(path, root) -> str:
    return str(Path(path).relative_to(root)).replace("\\", "/")


class FailingStubs(_Stubs):
    """Engine stubs that refuse the sources whose name contains a marker."""

    def __init__(self, marker: str = "bad"):
        super().__init__()
        self.marker = marker

    def install(self, monkeypatch):
        from tts import batch_convert
        from tts import pdf_extractor
        from tts.epub2tts_edge import runner

        def run_conversion_job(sourcefile, **kwargs):
            self.conversion_jobs.append({"source": sourcefile, **kwargs})
            if self.marker in Path(sourcefile).name:
                raise RuntimeError("engine refused this book")
            produced = Path(kwargs["output_dir"]) / (
                f"{Path(sourcefile).stem} ({kwargs['speaker']}).mp3")
            produced.parent.mkdir(parents=True, exist_ok=True)
            produced.write_bytes(b"audio")
            return str(produced)

        def convert_single_pdf(path, output_dir, speaker, rate, log=print,
                               progress_report=None, cancel_check=None, out_mp3=None,
                               bitrate=None):
            self.batch_items.append({
                "source": path, "output_dir": output_dir, "speaker": speaker,
                "rate": rate, "out_mp3": out_mp3, "bitrate": bitrate})
            if self.marker in Path(path).name:
                # A partial artifact is exactly what a failed conversion leaves
                # behind, and Phase 7 must not mistake it for a resume skip.
                Path(out_mp3).parent.mkdir(parents=True, exist_ok=True)
                Path(out_mp3).write_bytes(b"partial")
                return "failed", Path(path), "chunk merge failed"
            Path(out_mp3).parent.mkdir(parents=True, exist_ok=True)
            Path(out_mp3).write_bytes(b"audio")
            return "success", Path(path), None

        def pdf_to_txt(source_path, target):
            self.extracted.append((str(source_path), str(target)))
            Path(target).write_text("Body text.\n", encoding="utf-8")
            return target

        monkeypatch.setattr(runner, "run_conversion_job", run_conversion_job)
        monkeypatch.setattr(batch_convert, "convert_single_pdf", convert_single_pdf)
        monkeypatch.setattr(pdf_extractor, "pdf_to_txt", pdf_to_txt)
        return self


@pytest.fixture()
def failing_stubs(monkeypatch):
    from tts.epub2tts_edge import epub2tts_edge as engine

    monkeypatch.setattr(engine, "ensure_punkt", lambda: None)
    monkeypatch.setattr(panel_module, "ensure_punkt", lambda: None)
    return FailingStubs().install(monkeypatch)


class GatedStubs(_Stubs):
    """Engine stubs that block inside a conversion until released.

    This is how a test can stand *inside* an indivisible engine operation and
    ask what the controller says while it is still running.
    """

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.gate_on = "gate"
        self.order: list[str] = []

    def install(self, monkeypatch):
        from tts import batch_convert
        from tts.epub2tts_edge import runner

        def hold(name: str) -> None:
            self.order.append(name)
            if self.gate_on in name:
                self.entered.set()
                assert self.release.wait(WAIT), "the gate was never released"

        def run_conversion_job(sourcefile, **kwargs):
            self.conversion_jobs.append({"source": sourcefile, **kwargs})
            hold(Path(sourcefile).name)
            produced = Path(kwargs["output_dir"]) / (
                f"{Path(sourcefile).stem} ({kwargs['speaker']}).mp3")
            produced.parent.mkdir(parents=True, exist_ok=True)
            produced.write_bytes(b"audio")
            return str(produced)

        def convert_single_pdf(path, output_dir, speaker, rate, log=print,
                               progress_report=None, cancel_check=None, out_mp3=None,
                               bitrate=None):
            self.batch_items.append({"source": path, "out_mp3": out_mp3,
                                     "bitrate": bitrate})
            hold(Path(path).name)
            Path(out_mp3).parent.mkdir(parents=True, exist_ok=True)
            Path(out_mp3).write_bytes(b"audio")
            return "success", Path(path), None

        monkeypatch.setattr(runner, "run_conversion_job", run_conversion_job)
        monkeypatch.setattr(batch_convert, "convert_single_pdf", convert_single_pdf)
        return self


@pytest.fixture()
def gated_stubs(monkeypatch):
    from tts.epub2tts_edge import epub2tts_edge as engine

    monkeypatch.setattr(engine, "ensure_punkt", lambda: None)
    monkeypatch.setattr(panel_module, "ensure_punkt", lambda: None)
    return GatedStubs().install(monkeypatch)


# --------------------------------------------------------------------------- #
# A. Run capture — one run, frozen once
# --------------------------------------------------------------------------- #


def test_an_accepted_run_is_frozen_exactly_once_with_capture_run(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    calls: list[dict] = []
    real = job_control.capture_run

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(panel_module, "capture_run", spy)
    panel, chosen = direct_panel(make_panel, tmp_path, "one.txt", "two.txt")
    params = run_attempt(panel)

    assert len(calls) == 1, "one accepted run is captured once"
    snapshot = params["snapshot"]
    assert isinstance(snapshot, RunSnapshot)
    assert snapshot.count == 2
    assert [entry.path for entry in snapshot.files.files] == list(chosen)


def test_the_frozen_snapshot_carries_the_catalog_options_and_config(
    make_panel, output_base, tmp_path, stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    params = run_attempt(panel)
    snapshot = params["snapshot"]

    assert snapshot.catalog is panel.import_catalog
    assert set(snapshot.catalog.type_ids) == {"pdf", "txt"}
    assert snapshot.import_options == panel.importer.options.options()
    assert snapshot.effective_config is panel._effective_config


def test_every_processing_option_the_worker_uses_is_frozen_in_tool_options(
    make_panel, output_base, tmp_path, stubs
):
    """The run reads its settings from the snapshot, never from a widget."""
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    panel.bitrate_var.set("320k")
    panel.workers_var.set("3")
    panel.rate_var.set("+10%")
    panel.resume_var.set(False)
    panel.overwrite_var.set(False)
    params = run_attempt(panel)

    options = params["snapshot"].tool_options
    assert options["bitrate"] == "320k"
    assert options["workers"] == 3
    assert options["rate"] == "+10%"
    assert options["resume"] is False
    assert options["overwrite"] is False
    assert options["speaker"] == "en-US-SteffanNeural"
    # Phase 10 replaced the single ``kokoro_voice_id`` field with the run's
    # explicit engine identity, which is what the three-way dispatch reads.
    assert options["backend"] == "edge"
    assert options["voice_id"] == "en-US-SteffanNeural"
    assert options["pause_kw"]["sentencepause"] == 800
    assert options["pause_kw"]["trim_silence_db"] == -58.0
    assert job_control.is_frozen_options(options)


def test_a_later_widget_or_queue_change_cannot_reach_a_running_run(
    make_panel, output_base, tmp_path, stubs
):
    panel, chosen = direct_panel(make_panel, tmp_path, "one.txt")
    captured = accept(panel)

    # Everything a user could touch between Start and the worker finishing.
    panel.bitrate_var.set("128k")
    panel.voice_var.set("en-GB-RyanNeural")
    panel._manager.clear()

    finish(panel, captured)
    assert len(stubs.conversion_jobs) == 1
    job = stubs.conversion_jobs[0]
    assert job["source"] == str(chosen[0])
    assert job["mp3_bitrate"] == "192k", "the frozen bitrate, not the new one"
    assert job["speaker"] == "en-US-SteffanNeural"


def test_the_run_directory_is_still_reserved_only_after_validation(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    from tkinter import messagebox

    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: None)
    panel = make_panel()
    reserved: list = []
    real = panel_module.output_paths.reserve_run_directory
    monkeypatch.setattr(
        panel_module.output_paths, "reserve_run_directory",
        lambda key, **kw: reserved.append(key) or real(key, **kw))

    assert accept(panel) == {}, "an empty queue starts nothing"
    assert reserved == [], "and reserves nothing"


# --------------------------------------------------------------------------- #
# B. The job controller owns the run's state
# --------------------------------------------------------------------------- #


def test_one_controller_per_attempt_and_start_reaches_running(
    make_panel, output_base, tmp_path, stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    captured = accept(panel)
    controller = panel._controller

    assert isinstance(controller, job_control.JobController)
    assert controller.run_id == panel._snapshot.snapshot_id
    assert controller.state is JobState.RUNNING
    finish(panel, captured)
    assert controller.state is JobState.SUCCEEDED


def test_pause_is_a_request_until_the_worker_acknowledges_it(
    make_panel, output_base, tmp_path, gated_stubs
):
    """Truthfulness: an indivisible engine call keeps running while pausing."""
    panel, _chosen = direct_panel(make_panel, tmp_path, "gate.txt", "second.txt")
    panel.run_job()
    worker = panel._worker
    controller = panel._controller
    try:
        assert gated_stubs.entered.wait(WAIT), "the engine never started"
        panel.pause()
        assert controller.state is JobState.PAUSE_REQUESTED
        assert controller.pause_requested is True

        gated_stubs.release.set()
        wait_for(lambda: controller.state is JobState.PAUSED,
                 "the worker never acknowledged the pause", panel=panel)
        assert gated_stubs.order == ["gate.txt"], "no new source began while paused"

        panel.resume()
        wait_for(lambda: controller.is_terminal,
                 "the resumed run never finished", panel=panel)
        assert gated_stubs.order == ["gate.txt", "second.txt"]
        assert controller.state is JobState.SUCCEEDED
    finally:
        panel.cancel_job()
        gated_stubs.release.set()
        worker.join(WAIT)


def test_cancel_while_paused_wakes_the_worker_and_outranks_the_pause(
    make_panel, output_base, tmp_path, gated_stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "gate.txt", "second.txt")
    panel.run_job()
    worker = panel._worker
    controller = panel._controller
    try:
        assert gated_stubs.entered.wait(WAIT)
        panel.pause()
        gated_stubs.release.set()
        wait_for(lambda: controller.state is JobState.PAUSED,
                 "the worker never paused", panel=panel)

        panel.cancel_job()
        wait_for(lambda: controller.state is JobState.CANCELLED,
                 "cancel did not wake the paused worker", panel=panel)
        assert gated_stubs.order == ["gate.txt"], "no source began after the cancel"
        assert controller.cancel_acknowledged is True
    finally:
        worker.join(WAIT)


def test_a_terminal_state_cannot_be_overwritten(
    make_panel, output_base, tmp_path, stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    run_attempt(panel)
    controller = panel._controller
    assert controller.state is JobState.SUCCEEDED

    controller.request_cancel()
    controller.request_pause()
    controller.resume()
    assert controller.state is JobState.SUCCEEDED


def test_cancelled_requires_a_real_acknowledgement_not_a_button_press(
    make_panel, output_base, tmp_path, stubs
):
    """``finish_cancelled`` refuses a run no checkpoint ever stopped."""
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    accept(panel)
    controller = panel._controller
    controller.request_cancel()
    assert controller.state is JobState.CANCEL_REQUESTED
    with pytest.raises(job_control.JobContractError):
        controller.finish_cancelled()


# --------------------------------------------------------------------------- #
# C. The shared job adapter is the processing UI
# --------------------------------------------------------------------------- #


def test_the_panel_installs_the_shared_job_adapter(make_panel):
    from shared import job_ui

    panel = make_panel()
    assert isinstance(panel.jobs, job_ui.JobAdapter)
    assert panel.jobs.run_id == panel_module.IDLE_RUN_ID
    assert isinstance(panel.jobs.controls, job_ui.JobControlBar)
    assert isinstance(panel.jobs.status, job_ui.JobStatusView)
    assert isinstance(panel.jobs.views, job_ui.SummaryDetailsView)


def test_one_progress_model_survives_and_it_is_the_shared_one(make_panel):
    panel = make_panel()
    assert panel.progress is panel.jobs.status.indicator
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert source.count("ProgressIndicator(") == 0, (
        "the panel must not build a second progress indicator")


def test_the_existing_pump_owns_every_drain_and_no_second_after_loop_exists(
    make_panel
):
    panel = make_panel()
    drains = list(panel._pump._drains)
    assert panel._drain_worker_queue in drains
    assert panel.jobs.drain in drains
    assert len(drains) == 2, drains

    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert source.count("MainThreadPump(") == 1
    assert "root.after(" not in source
    drain = method_named("_drain_worker_queue")
    calls = {
        node.func.attr for node in ast.walk(drain)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "after" not in calls


def test_a_new_run_replaces_the_adapter_without_leaking_a_drain(
    make_panel, output_base, tmp_path, stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    first = panel.jobs
    run_attempt(panel)
    assert panel.jobs is not first
    assert first.closed is True
    assert len(list(panel._pump._drains)) == 2, "still exactly one job drain"


def test_the_imported_input_and_processing_options_lock_through_the_matrix(
    make_panel, output_base, tmp_path, gated_stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "gate.txt")
    registered_inputs = panel.jobs.locks.registered(ControlKind.IMPORTED_INPUT)
    registered_options = panel.jobs.locks.registered(ControlKind.PROCESSING_OPTION)
    assert panel.importer in registered_inputs
    assert panel in registered_options

    panel.run_job()
    worker = panel._worker
    try:
        assert gated_stubs.entered.wait(WAIT)
        assert str(panel.go_btn["state"]) == "disabled"
        wait_for(
            lambda: panel.jobs.locks.last_applied.get(
                ControlKind.IMPORTED_INPUT) is True,
            "the run never locked its inputs through the matrix", panel=panel)
        applied = panel.jobs.locks.last_applied
        assert applied[ControlKind.PROCESSING_OPTION] is True
        assert applied[ControlKind.JOB_CONTROL] is False
        assert applied[ControlKind.LOG_VIEW] is False
    finally:
        gated_stubs.release.set()
        worker.join(WAIT)
        panel._pump.tick()

    assert panel.jobs.locks.last_applied[ControlKind.IMPORTED_INPUT] is False
    assert str(panel.go_btn["state"]) == "normal"


def test_the_lock_matrix_is_consulted_rather_than_restated():
    """No local table of which state locks what."""
    for kind in ControlKind:
        for state in JobState:
            expected = state in job_control.LOCK_MATRIX[kind]
            assert is_locked(kind, state) is expected
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "INPUT_LOCKED_STATES" not in source
    assert "LOCK_MATRIX = " not in source


def test_summary_and_details_are_the_authoritative_job_record(
    make_panel, output_base, tmp_path, stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    params = run_attempt(panel)

    summary = "\n".join(panel.jobs.views.summary)
    details = "\n".join(panel.jobs.views.details)
    assert str(params["run_directory"]) in summary, "the output location is reported"
    assert "Completed" in summary or "Succeeded" in summary or summary
    assert panel.jobs.state is JobState.SUCCEEDED
    assert details, "Details carries the timestamped event history"


def test_retry_availability_follows_the_shared_state(
    make_panel, output_base, tmp_path, failing_stubs
):
    from shared.job_control import JobAction

    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt")
    run_attempt(panel)

    assert panel.jobs.has_retryable is True
    assert panel.jobs.controls.availability()[JobAction.RETRY_FAILED] is True
    assert panel.jobs.controls.availability()[JobAction.PAUSE] is False


# --------------------------------------------------------------------------- #
# D. Direct and folder-derived output in one run
# --------------------------------------------------------------------------- #


def test_a_directly_added_file_lands_flat_in_the_run(
    make_panel, output_base, tmp_path, stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "solo.txt", "notes.txt")
    params = run_attempt(panel)
    run = params["run_directory"]
    speaker = "en-US-SteffanNeural"

    placed = [relative(item["destination"], run) for item in params["items"]]
    assert placed == [f"solo ({speaker}).mp3", f"notes ({speaker}).mp3"]
    for item in params["items"]:
        assert item["destination"].exists()


def test_one_folder_root_still_mirrors_its_relative_parents(
    make_panel, output_base, tmp_path, stubs
):
    panel, _folders = folder_panel(make_panel, tmp_path)
    params = run_attempt(panel)
    run = params["run_directory"]

    placed = sorted(relative(item["destination"], run) for item in params["items"])
    assert placed == ["01.mp3", "Book A/02.mp3"]


def test_several_folder_roots_each_get_a_collision_safe_container(
    make_panel, output_base, tmp_path, stubs
):
    panel, folders = folder_panel(make_panel, tmp_path, roots=2)
    params = run_attempt(panel)
    run = params["run_directory"]

    placed = sorted(relative(item["destination"], run) for item in params["items"])
    assert placed == [
        f"{folders[0].name}/01.mp3",
        f"{folders[0].name}/Book A/02.mp3",
        f"{folders[1].name}/01.mp3",
        f"{folders[1].name}/Book A/02.mp3",
    ]


def test_direct_and_folder_items_share_one_run_and_one_reservation(
    make_panel, output_base, tmp_path, stubs
):
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path)
    params = run_attempt(panel)
    run = params["run_directory"]
    speaker = "en-US-SteffanNeural"

    placed = [relative(item["destination"], run) for item in params["items"]]
    assert placed == [
        f"solo ({speaker}).mp3",
        f"notes ({speaker}).mp3",
        "01.mp3",
        "Book A/02.mp3",
    ]
    assert len({item["destination"] for item in params["items"]}) == 4
    assert len([p for p in output_base.iterdir() if p.is_dir()]) == 1


def test_a_direct_and_a_grouped_file_cannot_be_planned_onto_one_path(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    """One shared planner, so a flat name and a mirrored name cannot collide."""
    from tts import voice_registry as vr

    stubs.install_kokoro(monkeypatch)
    kokoro = next(voice for voice in vr.VOICES if voice.backend == "kokoro")
    direct = sources(tmp_path / "Loose", "01.pdf")
    root = tmp_path / "Library"
    sources(root, "01.pdf")

    panel = make_panel(choose_files=lambda: direct, choose_folder=lambda: (root,))
    panel.importer.add_files()
    panel.importer.add_folder()
    panel._pump.tick()
    panel.selected_voice_label.set(kokoro.display_label)
    panel._on_voice_selected()

    params = run_attempt(panel)
    run = params["run_directory"]
    placed = [relative(item["destination"], run) for item in params["items"]]
    assert placed == ["01.mp3", "01-1.mp3"], placed
    assert len(set(placed)) == 2


def test_edge_and_kokoro_receive_identical_placement_for_one_source_tree(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    from tts import voice_registry as vr

    panel, _folders = folder_panel(make_panel, tmp_path)
    edge = run_attempt(panel)
    edge_layout = sorted(
        relative(item["destination"], edge["run_directory"]) for item in edge["items"])

    stubs.install_kokoro(monkeypatch)
    kokoro = next(voice for voice in vr.VOICES if voice.backend == "kokoro")
    panel2, _folders2 = folder_panel(make_panel, tmp_path / "second")
    panel2.selected_voice_label.set(kokoro.display_label)
    panel2._on_voice_selected()
    kok = run_attempt(panel2)
    kokoro_layout = sorted(
        relative(item["destination"], kok["run_directory"]) for item in kok["items"])

    assert edge_layout == kokoro_layout == ["01.mp3", "Book A/02.mp3"]


def test_the_panel_owns_no_second_planner_and_no_inline_mirroring():
    """Plan 2 decides placement; nothing here recomputes a relative path."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert source.count("DestinationPlanner(") == 1
    assert source.count("reserve_run_directory(") == 1
    assert "relative_to(" not in source, "mirroring belongs to plan_mirrored"
    assert "rglob(" not in source
    tree = panel_tree()
    defined = {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for owned in ("plan_flat", "plan_mirrored", "plan_multi_root", "planning_groups"):
        assert owned not in defined, owned


# --------------------------------------------------------------------------- #
# E. Occurrence identity is the key, never a path
# --------------------------------------------------------------------------- #


def test_every_occurrence_maps_to_exactly_one_source_and_destination(
    make_panel, output_base, tmp_path, stubs
):
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path)
    params = run_attempt(panel)
    snapshot = params["snapshot"]
    planned = panel.destinations()

    assert set(planned) == set(snapshot.item_ids)
    assert len({entry.destination for entry in planned.values()}) == len(planned)
    lookup = {entry.occurrence_id: entry.path for entry in snapshot.files.files}
    for occurrence_id, entry in planned.items():
        assert entry.source == lookup[occurrence_id]


def test_deliberate_duplicates_stay_distinct_with_two_safe_destinations(
    make_panel, output_base, tmp_path, stubs
):
    """The same path twice is two occurrences, and two outputs."""
    chosen = sources(tmp_path / "Loose", "solo.txt")
    panel = make_panel(choose_files=lambda: chosen,
                       confirm_large_result=lambda outcome: True)
    panel.importer.add_files()
    panel.importer.options.set_allow_duplicates(True)
    panel.importer.add_files()
    panel._pump.tick()
    assert panel.manager.count == 2, "the duplicate was deliberately admitted"

    params = run_attempt(panel)
    snapshot = params["snapshot"]
    planned = panel.destinations()
    first, second = snapshot.item_ids

    assert first != second
    assert planned[first].source == planned[second].source
    assert planned[first].destination != planned[second].destination
    run = params["run_directory"]
    speaker = "en-US-SteffanNeural"
    assert sorted(relative(entry.destination, run) for entry in planned.values()) == [
        f"solo ({speaker})-1.mp3", f"solo ({speaker}).mp3"]


def test_a_mismatched_pairing_is_refused_loudly_rather_than_guessed(
    make_panel, output_base, tmp_path, stubs
):
    from shared import output_paths

    panel, _direct, _folders = mixed_panel(make_panel, tmp_path)
    snapshot = panel._manager.snapshot()

    class Broken:
        """A planner that hands back one destination too few."""

        def __init__(self, real):
            self._real = real
            self._calls = 0

        def plan(self, name, **kwargs):
            self._calls += 1
            return self._real.plan(name, **kwargs)

    # Feeding the pairing a snapshot with a different occurrence order than the
    # plan is the failure this guard exists for.
    with pytest.raises(output_paths.UnsafePathError):
        panel_module._pair(
            ("occ-a", "occ-b"),
            type("P", (), {"items": ()})(),
            (),
            {"occ-a": Path("x"), "occ-b": Path("y")},
            direct=True,
        )


def test_destination_identity_does_not_depend_on_path_uniqueness():
    """The mapping is keyed by occurrence id in the source, not by path."""
    body = ast.unparse(panel_tree())
    assert "self._destinations[" in body or "_destinations.get(" in body
    plan = None
    for node in panel_tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == "plan_destinations":
            plan = node
    assert plan is not None
    text = ast.unparse(plan)
    assert "occurrence_id" in text


# --------------------------------------------------------------------------- #
# F. Retry Failed
# --------------------------------------------------------------------------- #


def test_retry_reuses_the_exact_original_snapshot_and_only_failed_ids(
    make_panel, output_base, tmp_path, failing_stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt")
    first = run_attempt(panel)
    original = first["snapshot"]
    result = panel._result

    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert result.has_retryable is True
    failed_id = result.retryable_ids[0]

    second = run_attempt(panel, panel.retry_failed)
    assert second["snapshot"] is original, "the exact object, not a rebuild"
    assert [item["item_id"] for item in second["items"]] == [failed_id]
    assert panel._attempt == 2


def test_a_retry_lands_on_the_original_destination_and_replans_nothing(
    make_panel, output_base, tmp_path, failing_stubs, monkeypatch
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt")
    first = run_attempt(panel)
    planned_before = dict(panel.destinations())
    run_before = first["run_directory"]

    reserved: list = []
    monkeypatch.setattr(
        panel_module.output_paths, "reserve_run_directory",
        lambda *a, **k: reserved.append(a) or pytest.fail("a retry reserved a run"))

    second = run_attempt(panel, panel.retry_failed)
    assert panel.destinations() == planned_before, "no destination was recomputed"
    assert second["run_directory"] == run_before
    failed_id = second["items"][0]["item_id"]
    assert second["items"][0]["destination"] == planned_before[failed_id].destination


def test_a_retry_never_overwrites_an_earlier_success(
    make_panel, output_base, tmp_path, failing_stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt")
    first = run_attempt(panel)
    survivor = next(item["destination"] for item in first["items"]
                    if "good" in item["source"].name)
    survivor.write_bytes(b"the first success")

    run_attempt(panel, panel.retry_failed)
    assert survivor.read_bytes() == b"the first success"


def test_a_retry_reads_no_live_widget_manager_or_configuration(
    make_panel, output_base, tmp_path, failing_stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt")
    run_attempt(panel)

    # Everything a user might change between the run and pressing Retry Failed.
    panel._manager.clear()
    panel.bitrate_var.set("128k")
    panel.workers_var.set("9")
    panel.rate_var.set("+50%")
    panel.overwrite_var.set(False)
    panel.importer.options.set_types(("txt",))

    second = run_attempt(panel, panel.retry_failed)
    options = second["snapshot"].tool_options
    assert options["bitrate"] == "192k"
    assert options["workers"] == 2
    assert options["rate"] == "+0%"
    assert options["overwrite"] is True
    assert second["items"], "a cleared queue does not empty a frozen retry"


def test_retrying_one_duplicate_occurrence_leaves_the_other_alone(
    make_panel, output_base, tmp_path, monkeypatch
):
    """Same path, two occurrences: retrying B may never touch A's output."""
    chosen = sources(tmp_path / "Loose", "twice.txt")
    stubs = FailingStubs(marker="never").install(monkeypatch)
    from tts.epub2tts_edge import epub2tts_edge as engine

    monkeypatch.setattr(engine, "ensure_punkt", lambda: None)
    monkeypatch.setattr(panel_module, "ensure_punkt", lambda: None)

    seen: list[str] = []
    from tts.epub2tts_edge import runner

    def flaky(sourcefile, **kwargs):
        seen.append(str(sourcefile))
        produced = Path(kwargs["output_dir"]) / (
            f"{Path(sourcefile).stem} ({kwargs['speaker']}).mp3")
        produced.parent.mkdir(parents=True, exist_ok=True)
        produced.write_bytes(b"audio")
        if len(seen) == 2:
            raise RuntimeError("the second occurrence failed")
        return str(produced)

    monkeypatch.setattr(runner, "run_conversion_job", flaky)

    panel = make_panel(choose_files=lambda: chosen,
                       confirm_large_result=lambda outcome: True)
    panel.importer.add_files()
    panel.importer.options.set_allow_duplicates(True)
    panel.importer.add_files()
    panel._pump.tick()

    first = run_attempt(panel)
    result = panel._result
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    failed_id = result.retryable_ids[0]
    survivor_id = next(i for i in first["snapshot"].item_ids if i != failed_id)
    survivor = panel.destinations()[survivor_id].destination
    survivor.write_bytes(b"first occurrence")

    second = run_attempt(panel, panel.retry_failed)
    assert [item["item_id"] for item in second["items"]] == [failed_id]
    assert second["items"][0]["destination"] != survivor
    assert survivor.read_bytes() == b"first occurrence"


def test_retry_failed_is_unavailable_without_a_retryable_failure(
    make_panel, output_base, tmp_path, stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    run_attempt(panel)
    assert panel._result.has_retryable is False
    assert panel.jobs.has_retryable is False
    assert accept(panel, panel.retry_failed) == {}, "nothing was started"


# --------------------------------------------------------------------------- #
# G. Item failure versus job failure
# --------------------------------------------------------------------------- #


def test_one_source_failure_is_recorded_against_its_occurrence_and_the_run_goes_on(
    make_panel, output_base, tmp_path, failing_stubs
):
    panel, _chosen = direct_panel(
        make_panel, tmp_path, "first.txt", "bad.txt", "third.txt")
    params = run_attempt(panel)
    result = panel._result

    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert result.failed_count == 1
    assert result.succeeded_count == 2, "later items continued"
    record = result.failures.records[0]
    assert record.item_id is not None
    assert record.retryable is True
    assert record.stage == STAGE
    assert "bad.txt" in record.display_message
    assert "RuntimeError" in record.technical_detail
    assert panel._controller.state is JobState.COMPLETED_WITH_FAILURES
    assert len(params["items"]) == 3


def test_a_folder_item_failure_is_an_item_failure_too(
    make_panel, output_base, tmp_path, failing_stubs
):
    root = tmp_path / "Library"
    sources(root, "01.pdf")
    sources(root / "Book A", "bad.txt")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()

    run_attempt(panel)
    result = panel._result
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert result.failed_count == 1 and result.succeeded_count == 1
    assert result.has_retryable is True


def test_an_orchestration_failure_is_fatal_and_not_retryable(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")

    def boom():
        raise OSError("the punkt corpus could not be prepared")

    monkeypatch.setattr(panel_module, "ensure_punkt", boom)
    run_attempt(panel)
    result = panel._result

    assert result.state is JobState.FAILED
    assert result.failures.fatal, "a job-level failure records why"
    assert result.failures.fatal[0].item_id is None
    assert result.failures.fatal[0].retryable is False
    assert result.has_retryable is False
    assert panel._controller.state is JobState.FAILED


def test_the_failure_message_is_concise_and_the_detail_is_technical(
    make_panel, output_base, tmp_path, failing_stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "bad.txt")
    run_attempt(panel)

    summary = "\n".join(panel.jobs.views.summary)
    details = "\n".join(panel.jobs.views.details)
    assert "RuntimeError" not in summary, "no traceback vocabulary in Summary"
    assert "RuntimeError" in details
    assert "bad.txt" in summary


# --------------------------------------------------------------------------- #
# H. Pause between source files, never inside one
# --------------------------------------------------------------------------- #


def test_the_worker_checkpoints_between_source_files_only():
    """The engines are never handed a pause hook, and never call one."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "request_pause" not in ast.unparse(method_named("conversion_worker"))
    for helper in ("convert_with_edge_engine", "convert_with_kokoro"):
        node = next(n for n in panel_tree().body
                    if isinstance(n, ast.FunctionDef) and n.name == helper)
        text = ast.unparse(node)
        assert "checkpoint()" not in text, (
            f"{helper} must not pause inside an indivisible engine call")
    assert "checkpoint()" in source


def test_a_folder_pool_starts_no_new_source_after_a_pause_is_acknowledged(
    make_panel, output_base, tmp_path, gated_stubs
):
    root = tmp_path / "Library"
    # The gated file is named to sort first, so the pause lands with real work
    # still queued behind it rather than after the last source has begun.
    sources(root, "a gate.txt", "b.txt", "c.txt", "d.txt")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()
    panel.workers_var.set("1")

    panel.run_job()
    worker = panel._worker
    controller = panel._controller
    try:
        assert gated_stubs.entered.wait(WAIT)
        panel.pause()
        gated_stubs.release.set()
        wait_for(lambda: controller.state is JobState.PAUSED,
                 "the pool never acknowledged the pause", panel=panel)
        started = list(gated_stubs.order)
        assert started == ["a gate.txt"], started

        panel.resume()
        wait_for(lambda: controller.is_terminal, "the pool never finished", panel=panel)
        assert sorted(gated_stubs.order) == ["a gate.txt", "b.txt", "c.txt", "d.txt"]
    finally:
        panel.cancel_job()
        worker.join(WAIT)


def test_pause_and_resume_use_no_sleep_or_poll_in_production():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "time.sleep(" not in source
    assert "sleep(" not in source


# --------------------------------------------------------------------------- #
# I. Cancellation
# --------------------------------------------------------------------------- #


def test_the_engines_receive_the_controllers_cancel_check(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    from tts import voice_registry as vr

    stubs.install_kokoro(monkeypatch)
    kokoro = next(voice for voice in vr.VOICES if voice.backend == "kokoro")
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path)
    panel.selected_voice_label.set(kokoro.display_label)
    panel._on_voice_selected()
    run_attempt(panel)

    controller = panel._controller
    assert stubs.kokoro_calls
    for call in stubs.kokoro_calls:
        assert call["cancel_check"] == controller.cancel_check


def test_the_edge_engines_receive_the_controllers_cancel_check(
    make_panel, output_base, tmp_path, stubs
):
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path)
    run_attempt(panel)
    check = panel._controller.cancel_check

    assert stubs.conversion_jobs
    for job in stubs.conversion_jobs:
        assert job["cancel_check"] == check


def test_the_legacy_processing_cancel_event_is_gone(make_panel):
    """One cancellation authority for processing, and it is the controller."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "_cancel_event" not in source
    body = ast.unparse(method_named("cancel_job"))
    assert "request_cancel" in body
    assert "importer" not in body and "coordinator" not in body


def test_a_cancelled_run_reports_exactly_one_terminal_event(
    make_panel, output_base, tmp_path, gated_stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "gate.txt", "second.txt")
    panel.run_job()
    worker = panel._worker
    controller = panel._controller
    try:
        assert gated_stubs.entered.wait(WAIT)
        panel.cancel_job()
        gated_stubs.release.set()
        wait_for(lambda: controller.state is JobState.CANCELLED,
                 "the run never settled as cancelled", panel=panel)
    finally:
        worker.join(WAIT)
    panel._pump.tick()

    terminal = [event for event in panel.jobs.stream.events if event.is_terminal]
    assert len(terminal) == 1
    assert terminal[0].state is JobState.CANCELLED
    assert panel._result.cancelled is True
    assert panel.jobs.state is JobState.CANCELLED


def test_a_cancelled_run_keeps_the_outputs_that_already_finished(
    make_panel, output_base, tmp_path, gated_stubs
):
    # A third file after the gate, so a checkpoint still lies ahead when Cancel is
    # pressed. Cancelling during the *last* source would correctly succeed instead:
    # the shared contract refuses to call a run cancelled if the work finished.
    panel, _chosen = direct_panel(
        make_panel, tmp_path, "first.txt", "gate.txt", "third.txt")
    panel.run_job()
    worker = panel._worker
    controller = panel._controller
    try:
        assert gated_stubs.entered.wait(WAIT)
        finished = panel.destinations()[panel._snapshot.item_ids[0]].destination
        assert finished.exists(), "the first file completed before the gate"

        panel.cancel_job()
        gated_stubs.release.set()
        wait_for(lambda: controller.state is JobState.CANCELLED,
                 "the run never cancelled", panel=panel)
    finally:
        worker.join(WAIT)

    assert finished.exists(), "a completed output survives a cancellation"
    # The controller reaches CANCELLED before the settled result is queued for the
    # main thread, so the run is drained to its end rather than read mid-flight.
    wait_for(lambda: panel._result is not None,
             "the settled result never reached the panel", panel=panel)
    assert panel._result.cancelled is True


def test_a_failed_item_leaves_no_partial_at_its_own_destination(
    make_panel, output_base, tmp_path, failing_stubs
):
    """The batch worker's partial is this occurrence's own, and only its own."""
    root = tmp_path / "Library"
    sources(root, "01.pdf")
    sources(root / "Book A", "bad.txt")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()

    params = run_attempt(panel)
    result = panel._result
    failed_id = result.retryable_ids[0]
    planned = panel.destinations()

    assert not planned[failed_id].destination.exists(), (
        "the failed occurrence's partial artifact was cleaned")
    survivor = next(entry.destination for item_id, entry in planned.items()
                    if item_id != failed_id)
    assert survivor.exists(), "a sibling's finished output was never touched"
    assert survivor.is_relative_to(params["run_directory"])


def test_closing_the_panel_during_a_paused_run_is_safe(
    make_panel, output_base, tmp_path, gated_stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "gate.txt", "second.txt")
    panel.run_job()
    worker = panel._worker
    controller = panel._controller
    assert gated_stubs.entered.wait(WAIT)
    panel.pause()
    gated_stubs.release.set()
    wait_for(lambda: controller.state is JobState.PAUSED, "never paused", panel=panel)

    panel.close()
    assert worker.is_alive() is False, "close woke and joined the paused worker"
    assert panel.importer.closed is True
    assert panel._pump.closed is True
    panel.close()


# --------------------------------------------------------------------------- #
# J. Resume semantics
# --------------------------------------------------------------------------- #


def test_resume_still_skips_a_folder_target_that_already_exists(
    make_panel, output_base, tmp_path, stubs
):
    panel, _folders = folder_panel(make_panel, tmp_path)
    captured = accept(panel)
    already = captured["params"]["items"][0]["destination"]
    already.parent.mkdir(parents=True, exist_ok=True)
    already.write_bytes(b"already converted")
    finish(panel, captured)

    assert already.read_bytes() == b"already converted"
    assert len(stubs.batch_items) == 1, "the existing target was skipped"


def test_a_retry_is_never_skipped_by_its_own_partial_artifact(
    make_panel, output_base, tmp_path, failing_stubs
):
    """The failed item left a partial file at its own destination; retry it anyway."""
    root = tmp_path / "Library"
    sources(root, "01.pdf")
    sources(root / "Book A", "bad.txt")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()
    assert panel.resume_var.get() is True

    run_attempt(panel)
    result = panel._result
    failed_id = result.retryable_ids[0]
    # Put an artifact back at the failed occurrence's own destination. Resume
    # would skip a folder target that exists; a retry must not be silenced by
    # the remains of the very attempt it is retrying.
    partial = panel.destinations()[failed_id].destination
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"left over from the failed attempt")

    before = len(failing_stubs.batch_items)
    second = run_attempt(panel, panel.retry_failed)
    assert [item["item_id"] for item in second["items"]] == [failed_id]
    assert len(failing_stubs.batch_items) == before + 1, (
        "the retried item was attempted, not resume-skipped")


def test_resume_is_not_redefined_for_the_user(make_panel):
    panel = make_panel()
    assert panel.resume_var.get() is True
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "Resume (skip existing MP3s)" in source


# --------------------------------------------------------------------------- #
# K. Mirroring regression — the layout did not move
# --------------------------------------------------------------------------- #


def test_nested_folders_still_mirror_and_same_stems_stay_separate(
    make_panel, output_base, tmp_path, stubs
):
    root = tmp_path / "Library"
    sources(root, "root chapter.txt")
    sources(root / "Book A", "Chapter 1.txt")
    sources(root / "Book B", "Chapter 1.txt")
    sources(root / "Book A" / "deep", "Chapter 2.txt")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()

    params = run_attempt(panel)
    run = params["run_directory"]
    placed = sorted(relative(item["destination"], run) for item in params["items"])
    assert placed == [
        "Book A/Chapter 1.mp3",
        "Book A/deep/Chapter 2.mp3",
        "Book B/Chapter 1.mp3",
        "root chapter.mp3",
    ]


def test_a_flat_folder_import_still_produces_a_flat_output(
    make_panel, output_base, tmp_path, stubs
):
    root = tmp_path / "Library"
    sources(root, "one.txt", "two.txt")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()

    params = run_attempt(panel)
    run = params["run_directory"]
    placed = sorted(relative(item["destination"], run) for item in params["items"])
    assert placed == ["one.mp3", "two.mp3"]
    assert not [p for p in run.iterdir() if p.is_dir()]


def test_the_batch_worker_still_keys_its_temp_chunks_on_the_run_root(
    make_panel, output_base, tmp_path, stubs
):
    panel, _folders = folder_panel(make_panel, tmp_path)
    params = run_attempt(panel)
    for item in stubs.batch_items:
        assert Path(item["output_dir"]) == params["run_directory"]


# --------------------------------------------------------------------------- #
# L. ETA and reporting
# --------------------------------------------------------------------------- #


def test_the_estimate_starts_at_calculating_and_belongs_to_the_run(
    make_panel, output_base, tmp_path, gated_stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "gate.txt", "b.txt", "c.txt")
    panel.run_job()
    worker = panel._worker
    try:
        assert gated_stubs.entered.wait(WAIT)
        panel._pump.tick()
        assert panel.jobs.estimator is panel.job_estimator
        assert panel.job_estimator.run_id == panel._snapshot.snapshot_id
        assert panel.jobs.status.eta_text == job_control.CALCULATING
    finally:
        gated_stubs.release.set()
        worker.join(WAIT)
        panel._pump.tick()


def test_completed_items_feed_the_estimate_through_the_main_thread(
    make_panel, output_base, tmp_path, stubs
):
    import itertools

    ticks = itertools.count()
    panel, _chosen = direct_panel(
        make_panel, tmp_path, "a.txt", "b.txt", "c.txt", "d.txt",
        clock=lambda: float(next(ticks)))
    run_attempt(panel)

    assert panel.job_estimator.sample_count == 4
    assert panel.job_estimator.category == panel_module.ETA_CATEGORY_DIRECT


def test_a_stale_or_earlier_attempts_timing_sample_is_inert(
    make_panel, output_base, tmp_path, stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    run_attempt(panel)
    estimator = panel.job_estimator
    before = estimator.sample_count

    panel._log_q.put((panel_module.TIMING_MESSAGE, panel_module.TimingSample(
        run_id="tts-run-999", attempt=panel._attempt,
        category=panel_module.ETA_CATEGORY_DIRECT, duration=1.0)))
    panel._log_q.put((panel_module.TIMING_MESSAGE, panel_module.TimingSample(
        run_id=estimator.run_id, attempt=panel._attempt + 5,
        category=panel_module.ETA_CATEGORY_DIRECT, duration=1.0)))
    panel._pump.tick()
    assert estimator.sample_count == before


def test_no_fake_completion_is_reported_when_a_run_fails(
    make_panel, output_base, tmp_path, failing_stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "bad.txt")
    run_attempt(panel)
    view = panel.jobs.summary_view

    assert view.state is JobState.COMPLETED_WITH_FAILURES
    assert view.progress.completed == 1 and view.progress.total == 1
    assert panel._result.succeeded_count == 0, "nothing actually succeeded"


def test_the_session_logger_bridge_is_used_rather_than_a_second_logger():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "logging.getLogger(" not in source
    assert "basicConfig(" not in source


# --------------------------------------------------------------------------- #
# M. Main-thread safety
# --------------------------------------------------------------------------- #


def test_the_conversion_worker_reaches_only_the_queue_on_the_panel():
    """The Phase 4 crash class, measured as a whitelist rather than promised.

    Phase 6 allowed ``_log_q`` and ``_cancel_event``; Phase 7 retires the second
    one, so the worker now reaches exactly one attribute of the panel.
    """
    worker = method_named("conversion_worker")
    reached = {
        node.attr for node in ast.walk(worker)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name) and node.value.id == "self"
    }
    assert reached == {"_log_q"}, reached


def test_no_worker_body_touches_a_variable_widget_or_the_live_manager():
    for name in ("conversion_worker",):
        body = ast.unparse(method_named(name))
        for forbidden in ("_var.get()", "var_outdir", "messagebox.", "ttk.",
                          "self.log", "self.progress", "self.importer",
                          "self._manager", "self.jobs", "self._estimator"):
            assert forbidden not in body, (name, forbidden)


def test_the_worker_never_holds_the_estimator(
    make_panel, output_base, tmp_path, stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    captured = accept(panel)
    params = captured["params"]

    assert "estimator" not in params
    for value in params.values():
        assert not isinstance(value, job_control.EtaEstimator)


def test_the_worker_receives_no_tk_object_and_no_import_state(
    make_panel, output_base, tmp_path, stubs
):
    from shared import importing as shared_importing
    from shared import job_ui

    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    params = accept(panel)["params"]
    forbidden = (tk.Variable, tk.Misc, shared_importing.ImportedFileManager,
                 job_ui.ImportAdapter, job_ui.JobAdapter, job_ui.MainThreadPump)
    for key, value in params.items():
        assert not isinstance(value, forbidden), (key, type(value))
    assert isinstance(params["snapshot"], RunSnapshot)
    assert isinstance(params["controller"], job_control.JobController)
    # The run's one publication authority, not the shared reporter behind it:
    # ordering is only guaranteed while there is nothing to bypass it with.
    assert isinstance(params["publisher"], panel_module.RunPublisher)
    for key, value in params.items():
        assert not isinstance(value, job_control.JobReporter), key


def test_events_reach_the_ui_only_through_the_queue_the_pump_drains(make_panel):
    """One route from a producer to the UI: the authority, then the queue."""
    deliver = method_named("_deliver", owner="RunPublisher")
    text = ast.unparse(deliver)
    assert "_sink.put" in text
    assert "jobs" not in text and "render" not in text


def test_the_two_cancellation_domains_never_cross(make_panel, tmp_path):
    from test_import_coordination import ControlledScanner

    root = tmp_path / "Library"
    sources(root, "01.pdf")
    started, release = threading.Event(), threading.Event()
    scanner = ControlledScanner(counts=(1,), started=started, release=release)
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner,
                       thread_factory=None)
    panel.importer.add_folder()
    assert started.wait(WAIT)

    assert panel.importer.cancel_import() is True
    assert panel.importer.coordinator.cancel_requested is True
    assert panel._controller is None, "the import cancel started no processing run"
    release.set()
    wait_for(lambda: not panel.importer.is_importing,
             "the cancelled scan never settled", panel=panel)

    # Cancelling an import stops the import and nothing else: no controller was
    # created, no run was accepted, and the cancelled scan committed nothing.
    assert panel.manager.count == 0
    assert panel._controller is None
    assert panel._snapshot is None


# --------------------------------------------------------------------------- #
# N. The engines are frozen
# --------------------------------------------------------------------------- #


def test_no_engine_module_changed_and_no_timing_default_moved():
    from tts import batch_convert
    from tts import voice_registry as vr
    from tts.epub2tts_edge import epub2tts_edge as engine

    assert batch_convert.CHUNK_TARGET == 3000
    assert batch_convert.CHUNK_PAUSE_MS == 50
    assert batch_convert.INTER_CHUNK_DELAY_SEC == 0.8
    assert batch_convert.END_RECORDING_SILENCE_MS == 3000
    assert batch_convert.CHUNK_MAX_RETRIES == 5
    assert batch_convert.PDF_MAX_RETRIES == 2

    assert engine.DEFAULT_SPEAKER == "en-US-SteffanNeural"
    assert engine.DEFAULT_SENTENCE_PAUSE_MS == 800
    assert engine.DEFAULT_PARAGRAPH_PAUSE_MS == 850
    assert engine.DEFAULT_TITLE_PAUSE_MS == 1200
    assert engine.DEFAULT_CHAPTER_PAUSE_MS == 2000
    assert engine.DEFAULT_END_OF_BOOK_PAUSE_MS == 3000
    assert engine.DEFAULT_TRIM_SILENCE_DB == -58.0

    assert vr.DEFAULT_VOICE_LABEL == "Edge Male - Steffan (en-US)"
    assert vr.DEFAULT_VOICE_LABEL == vr.VOICES[0].display_label
    assert len(vr.VOICES) == 16


def test_the_panel_reimplements_no_engine():
    defined = {
        node.name for node in ast.walk(panel_tree())
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for engine_symbol in ("read_book", "run_edgespeak", "make_mp3", "make_m4b",
                          "convert_single_pdf", "run_batch_convert",
                          "kokoro_file_to_mp3", "pdf_to_txt", "split_into_chunks"):
        assert engine_symbol not in defined, engine_symbol


def test_the_batch_worker_is_still_called_through_its_existing_seam(
    make_panel, output_base, tmp_path, stubs
):
    panel, _folders = folder_panel(make_panel, tmp_path)
    params = run_attempt(panel)
    assert len(stubs.batch_items) == 2
    for item in stubs.batch_items:
        assert item["out_mp3"] is not None, "the planned target travels as out_mp3"
        assert Path(item["out_mp3"]).is_relative_to(params["run_directory"])
        # v0.6.1 Plan 4 Phase 12: the run's chosen MP3 bitrate has to reach the
        # folder half of the queue too. It did not before, so folder items were
        # finished on ffmpeg's default while direct items used the real choice.
        assert item["bitrate"] == params["bitrate"], (
            "the run's bitrate must reach the batch worker")


# --------------------------------------------------------------------------- #
# O. The phase boundary — nothing from Phase 8 arrived
# --------------------------------------------------------------------------- #


def test_the_panel_composes_the_shared_job_foundation():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "shared.job_control" in source or "from shared import job_control" in source
    defined = {
        node.name for node in ast.walk(panel_tree())
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    forbidden = {
        "JobController", "JobReporter", "JobAdapter", "JobEventStream",
        "EtaEstimator", "RunResult", "RetryRequest", "FailureLog", "capture_run",
        "ImportedFileManager", "ImportCoordinator", "ImportAdapter",
        "MainThreadPump",
    }
    assert not (defined & forbidden), defined & forbidden


def test_no_chatterbox_or_later_phase_vocabulary_arrived():
    """Retargeted at Phase 10, which was authorized to add exactly the Chatterbox seam.

    The panel may now name the local cloning engine — that is the whole of what
    Phase 10 did, and the shape of it is asserted in detail by
    ``test_chatterbox_integration.py``. What must still be absent is everything the
    panel has no business importing: the model stack itself, a device pivot, or
    another tool's image dependency. The GUI asks one status question and calls one
    engine entry point; it never touches torch.
    """
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    for later in ("torch", "pillow_heif", "resemble_perth", "librosa"):
        assert later not in source, later
    # The panel may import this project's engine wrapper; it may never import the
    # third-party model package, which is what would drag torch into a GUI build.
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots = {(node.module or "").split(".")[0]}
        else:
            continue
        assert "chatterbox" not in roots, ast.dump(node)


def test_the_only_engine_dependency_added_since_is_the_authorized_one():
    """Phase 7 itself added no dependency; Phase 8 added exactly one engine stack.

    This test previously asserted that ``chatterbox``/``resemble-perth``/
    ``torchaudio`` were absent, which was Phase 7's boundary. v0.6.1 Plan 4 Phase 8
    is the maintainer-authorized phase that adds precisely those, so the guard is
    retargeted rather than dropped: the three are now required to be present, and
    the checks that stop the stack growing sideways stay in force. The GUI-side
    boundary is unchanged and still asserted by
    ``test_no_chatterbox_or_later_phase_vocabulary_arrived`` above.
    """
    requirements = (Path(__file__).resolve().parent.parent.parent
                    / "scripts" / "requirements.txt")
    text = requirements.read_text(encoding="utf-8").lower()
    for authorized in ("chatterbox-tts==0.1.7", "resemble-perth==1.0.1",
                       "torchaudio==2.6.0"):
        assert authorized in text, authorized
    # No second engine, no CUDA pivot, no unpinned source — none of which is
    # authorized by any phase up to and including 8.
    for unauthorized in ("+cu", "download.pytorch.org", "--extra-index-url",
                         "git+", "chatterbox-vc", "chatterbox-nano"):
        assert unauthorized not in text, unauthorized


def test_epub_stays_retired_and_the_archive_stays_inert():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    tree = panel_tree()
    prose = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef))
        and getattr(node, "body", None)
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in prose:
                continue
            assert ".epub" not in node.value, node.value
            assert "archived-code" not in node.value, node.value
    assert "epub2tts_gui" in str(PANEL_SOURCE), "the compatibility name is retained"
    assert source.count("SupportedType(") == 2, "PDF and TXT, and nothing else"
