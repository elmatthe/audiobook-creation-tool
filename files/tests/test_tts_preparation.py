"""v0.8.2 Checkpoint 4: a TTS Start is prepared off the Tk thread.

Start used to reserve the run folder and plan every destination inside the button's Tk callback; at 2,341 files the
window froze about 3.8 s, at 5,000 files in sub-folders about 12 s (the Checkpoint 3 measurements). Now the press
validates and freezes on Tk exactly as before, shows "Preparing job…" and returns; one preparation worker reserves and
plans from the frozen values alone; the pump adopts the plan and only then creates the run's controller, job area and
conversion worker.

What is pinned here:

* the press and the hand-off: nothing is reserved or planned on Tk, the panel is locked with Cancel and without
  Pause, Tk keeps its heartbeat on a real event loop while a large job is prepared;
* the names: exactly what the synchronous planner chose (direct, mirrored, multi-root, duplicates), checks included;
* ownership: offer / adopt / withdraw decide once, exactly one side releases a reservation, nothing nobody adopted
  ever starts synthesis -- Cancel and Close before, during and after planning, duplicate and stale endings;
* failures: reservation, planning, an unexpected fault, a preparation worker that cannot start, a job area that
  cannot be built, a conversion worker that cannot start -- each leaves the panel usable and the previous run,
  result and Retry Failed as they were;
* the frozen configuration: Preferences changed after the press do not move the run; a voice made unavailable while
  preparing stops the run before anything is synthesised; Retry Failed keeps the original destinations;
* the worker side touches no Tk (static and dynamic).
"""

from __future__ import annotations

import ast
import json
import threading
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import config as shared_config  # noqa: E402
from shared import job_ui  # noqa: E402
from shared import output_paths as op  # noqa: E402
from shared.job_control import JobAction, JobState  # noqa: E402

from tts import epub2tts_gui as panel_module  # noqa: E402
from tts import output_names  # noqa: E402
from tts import voice_registry as vr  # noqa: E402

from test_import_coordination import RealThreads, RecordingThreads  # noqa: E402
from test_tts_importing import (  # noqa: E402,F401  (fixtures are collected by name)
    PANEL_SOURCE,
    _Stubs,
    adopt_preparation,
    make_panel,
    output_base,
    sources,
    stubs,
    tk_root,
)
from test_tts_jobs import (  # noqa: E402
    _FakeThread,
    direct_panel,
    failing_stubs,  # noqa: F401  (fixture)
    finish,
    folder_panel,
    mixed_panel,
)

#: Every wait is bounded, so a deadlock fails instead of hanging the suite.
WAIT = 30.0


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _Idle:
    """A thread that was made but whose body the test runs itself."""

    def __init__(self, name: str) -> None:
        self.name = name

    def start(self) -> None:
        return None

    def is_alive(self) -> bool:
        return False

    def join(self, timeout=None) -> None:
        return None


class HeldPreparations(RecordingThreads):
    """Inline for every thread (import scans, releases) except the preparation worker, whose body is kept until the
    test runs it -- on the test's own thread, so the moment it runs is the test's choice."""

    def __init__(self) -> None:
        super().__init__()
        self.held: list = []

    def __call__(self, target, name):
        if name.startswith("tts-prepare-"):
            self.held.append(target)
            self.made.append(_Idle(name))
            return self.made[-1]
        return super().__call__(target, name)

    def run(self, index: int = -1) -> None:
        self.held[index]()


class Conversion:
    """Captures the conversion worker ``_launch`` starts (``threading.Thread(target=conversion_worker, ...)``)."""

    def __init__(self, monkeypatch) -> None:
        self.captured: list[dict] = []
        real = panel_module.threading.Thread

        def make(*args, **kwargs):
            if kwargs.get("target") is not None and getattr(kwargs["target"], "__name__", "") == "conversion_worker":
                sink: dict = {}
                self.captured.append(sink)
                return _FakeThread(kwargs, sink)
            return real(*args, **kwargs)

        monkeypatch.setattr(panel_module.threading, "Thread", make)

    @property
    def started(self) -> int:
        return len(self.captured)


def run_folders(output_base: Path) -> list[Path]:
    """Every reserved run folder under the standard output base."""
    return sorted(run for tool in output_base.glob("*-Outputs") for run in tool.iterdir())


def dialogs(monkeypatch) -> list[tuple[str, str, str]]:
    shown: list[tuple[str, str, str]] = []
    for kind in ("showwarning", "showerror", "showinfo"):
        monkeypatch.setattr(panel_module.messagebox, kind,
                            lambda title, text="", *a, _k=kind, **k: shown.append((_k, title, text)))
    return shown


def go_enabled(panel) -> bool:
    return str(panel.go_btn.cget("state")) == "normal"


def listbox_locked(panel) -> bool:
    return str(panel.importer.list.listbox.cget("state")) == "disabled"


def idle_and_usable(panel) -> bool:
    return (panel._preparing is None and not panel._busy.is_set() and go_enabled(panel)
            and not listbox_locked(panel))


def take_the_suites_thread_start_collection() -> None:
    """Take the suite's once-per-test thread-start ``gc.collect`` now, outside any timed window (Checkpoint 2)."""
    boundary = threading.Thread(target=lambda: None, name="cp4-gate-boundary")
    boundary.start()
    boundary.join()


class TkCallsFromWorkers:
    """Every Tcl call and every tkinter-level Python call made on a thread other than the main one.

    The hook identifies threads by ``threading.get_ident()`` only. ``threading.current_thread()`` must not be called
    from it: a profiled thread that ends while the hook is set runs it inside ``Thread._delete`` with ``threading``'s
    non-reentrant ``_active_limbo_lock`` held, after its entry is gone, so ``current_thread()`` builds a
    ``_DummyThread`` that takes that lock again and the thread deadlocks holding it (every later ``Thread.start``
    then hangs). Found in this module, v0.8.2 Checkpoint 4.
    """

    def __init__(self) -> None:
        self.violations: list[str] = []
        self._main = threading.main_thread().ident

    def _profile(self, frame, event, arg):
        ident = threading.get_ident()
        if ident == self._main:
            return
        if event == "c_call":
            owner = getattr(arg, "__self__", None)
            if owner is not None and type(owner).__name__ == "tkapp":
                self.violations.append(f"thread {ident}: Tcl {getattr(arg, '__name__', arg)}")
        elif event == "call" and "/tkinter/" in frame.f_code.co_filename.replace("\\", "/"):
            self.violations.append(f"thread {ident}: {frame.f_code.co_name}")

    def __enter__(self):
        threading.setprofile(self._profile)
        return self

    def __exit__(self, *exc):
        threading.setprofile(None)


def synchronous_plan(panel, run_directory: Path) -> dict:
    """What the pre-Checkpoint-4 press planned for the panel's current queue: the same function, on this thread."""
    snapshot = panel._manager.snapshot()
    label = vr.get_voice(panel.selected_voice_label.get()).display_label
    return panel_module.plan_destinations(snapshot, run_directory, label=label,
                                          planner=op.DestinationPlanner(run_directory))


def as_names(mapping: dict, root: Path) -> dict:
    return {key: str(Path(value.destination).relative_to(root)).replace("\\", "/") for key, value in mapping.items()}


def kokoro_label() -> str:
    return next(v.display_label for v in vr.VOICES if v.backend == "kokoro")


# --------------------------------------------------------------------------- #
# The press and the hand-off
# --------------------------------------------------------------------------- #


def test_the_press_reserves_and_plans_nothing_on_tk_and_shows_preparing(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    threads = HeldPreparations()
    conversion = Conversion(monkeypatch)
    planned_on: list[str] = []
    real_plan = panel_module.plan_destinations

    def spy(*args, **kwargs):
        planned_on.append(threading.current_thread().name)
        return real_plan(*args, **kwargs)

    monkeypatch.setattr(panel_module, "plan_destinations", spy)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", "two.txt", thread_factory=threads)

    panel.run_job()

    assert run_folders(output_base) == [], "the press reserves nothing"
    assert planned_on == [] and conversion.started == 0
    assert panel._preparing is not None and len(threads.held) == 1
    status = panel.jobs.status
    assert status.status_text == panel_module.STATUS_PREPARING
    assert "planning output names" in status.stage_text
    availability = panel.jobs.controls.availability()
    assert availability[JobAction.CANCEL] is True
    assert str(panel.jobs.controls.buttons[JobAction.PAUSE].cget("state")) == "disabled", "a preparation has no Pause"
    assert not go_enabled(panel) and listbox_locked(panel)
    assert [t.name for t in threads.made if t.name.startswith("tts-prepare")] == ["tts-prepare-1"]

    threads.run()
    assert conversion.started == 0, "nothing starts until the pump adopts the plan"
    adopt_preparation(panel)
    assert conversion.started == 1 and planned_on == ["MainThread"], "the body ran where the test ran it"
    params = conversion.captured[0]["params"]
    assert len(run_folders(output_base)) == 1 and params["run_directory"] == run_folders(output_base)[0]
    assert panel.var_outdir.get() == str(params["run_directory"])
    assert panel._busy.is_set() and panel._preparing is None


def test_repeated_presses_start_one_preparation(make_panel, output_base, tmp_path, stubs, monkeypatch):
    threads = HeldPreparations()
    conversion = Conversion(monkeypatch)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", thread_factory=threads)

    panel.run_job()
    panel.run_job()
    panel._start_frozen(panel._preparing.snapshot)
    assert len(threads.held) == 1 and panel._preparations == 1

    threads.run()
    adopt_preparation(panel)
    panel.run_job()  # busy now: refused
    assert conversion.started == 1 and len(run_folders(output_base)) == 1


@pytest.mark.parametrize("shape", ["direct", "folder", "two roots", "mixed", "duplicates"])
def test_the_prepared_names_are_exactly_the_synchronous_planners(make_panel, output_base, tmp_path, stubs,
                                                                  monkeypatch, shape):
    conversion = Conversion(monkeypatch)
    if shape == "direct":
        panel, _ = direct_panel(make_panel, tmp_path, "Alpha.txt", "beta.pdf", "Gamma.txt")
    elif shape == "folder":
        panel, _ = folder_panel(make_panel, tmp_path, roots=1)
    elif shape == "two roots":
        panel, _ = folder_panel(make_panel, tmp_path, roots=2)
    elif shape == "mixed":
        panel, *_ = mixed_panel(make_panel, tmp_path, roots=2)
    else:
        chosen = (sources(tmp_path / "a", "Chapter.txt") + sources(tmp_path / "b", "Chapter.txt")
                  + sources(tmp_path / "c", "chapter.TXT") + sources(tmp_path / "d", "Chapter.pdf"))
        panel = make_panel(choose_files=lambda: chosen)
        panel.importer.add_files()

    panel.run_job()
    adopt_preparation(panel)
    params = conversion.captured[0]["params"]
    run = Path(params["run_directory"])
    prepared = {item["item_id"]: item["destination"] for item in params["items"]}

    reference_root = tmp_path / "reference-run"
    reference_root.mkdir()
    expected = as_names(synchronous_plan(panel, reference_root), reference_root)
    got = {key: str(Path(value).relative_to(run)).replace("\\", "/") for key, value in prepared.items()}
    assert got == expected
    assert list(prepared) == list(panel._manager.snapshot().occurrence_ids), "occurrence order is kept"
    if shape == "duplicates":
        label = vr.get_voice(panel.selected_voice_label.get()).display_label
        assert sorted(got.values()) == sorted([f"Chapter-{label}.mp3", f"Chapter-{label}-1.mp3",
                                               f"chapter-{label}-2.mp3", f"Chapter-{label}-3.mp3"])


def test_the_naming_checkpoint_never_changes_a_name_and_sees_each_source_twice(tmp_path):
    files = sources(tmp_path / "lib", "A.txt", "B.txt", "a.TXT", "Book One.pdf")
    root = tmp_path / "run"
    root.mkdir()
    seen = []
    plain = output_names.plan_named(op.plan_flat, root, files, label="Voice", planner=op.DestinationPlanner(root))
    ticked = output_names.plan_named(op.plan_flat, root, files, label="Voice", planner=op.DestinationPlanner(root),
                                     checkpoint=lambda: seen.append(1))
    assert [item.destination for item in plain.items] == [item.destination for item in ticked.items]
    assert len(seen) == 2 * len(files)


def _identifiers(node) -> tuple[set[str], set[str]]:
    """Every bare name and every attribute name used in *node* (docstrings and comments do not count)."""
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    attributes = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
    return names, attributes


def test_the_worker_side_names_no_tk_and_no_panel_state():
    """Static half of the boundary: the worker body and the hand-off record reach no widget, Tk variable or panel."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    nodes = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    tk_names = {"tk", "ttk", "tkfont", "messagebox", "filedialog", "TtsPanel", "job_ui"}
    panel_attributes = {"jobs", "log", "go_btn", "after", "after_idle", "_pump", "importer", "_manager",
                        "selected_voice_label", "voice_var", "rate_var", "configure", "grid", "update"}
    for name in ("prepare_run", "_Preparation", "_PreparationMessage", "PreparedRun", "voice_readiness"):
        names, attributes = _identifiers(nodes[name])
        assert not names & tk_names, (name, names & tk_names)
        assert not attributes & panel_attributes, (name, attributes & panel_attributes)
    worker_names, worker_attributes = _identifiers(nodes["prepare_run"])
    assert "self" not in worker_names
    assert {"reserve_run_directory", "release_if_empty", "run_config"} <= worker_attributes
    assert "plan_destinations" in worker_names
    press = next(n for n in ast.walk(nodes["TtsPanel"]) if isinstance(n, ast.FunctionDef) and n.name == "_start_frozen")
    press_names, press_attributes = _identifiers(press)
    assert "reserve_run_directory" not in press_attributes and "plan_destinations" not in press_names
    assert "prepare_run" in press_names


def test_no_worker_ever_calls_tk(make_panel, output_base, tmp_path, stubs, monkeypatch, tk_root):
    """Dynamic half: real threads; every Tcl or tkinter call from any thread but the main one is recorded."""
    Conversion(monkeypatch)
    threads = RealThreads()
    panel, *_ = mixed_panel(make_panel, tmp_path, roots=2, thread_factory=RecordingThreads())
    panel._thread_factory = threads
    with TkCallsFromWorkers() as recorder:
        panel.run_job()
        deadline = time.monotonic() + WAIT
        while panel._preparing is not None:
            assert time.monotonic() < deadline
            tk_root.update()
            panel._pump.tick()
            time.sleep(0.005)
        for thread in threads.made:
            thread.join(WAIT)
            assert not thread.is_alive(), thread.name
    assert recorder.violations == []
    assert [t.name for t in threads.made] == ["tts-prepare-1"]
    assert panel._busy.is_set()


def test_the_worker_plans_only_after_tk_has_painted_the_press(make_panel, output_base, tmp_path, stubs,
                                                              monkeypatch, tk_root):
    Conversion(monkeypatch)
    entered = threading.Event()
    real = op.reserve_run_directory

    def reserve(*args, **kwargs):
        entered.set()
        return real(*args, **kwargs)

    monkeypatch.setattr(op, "reserve_run_directory", reserve)
    monkeypatch.setattr(panel_module, "PREPARATION_PAINT_WAIT", 20.0)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt")
    threads = RealThreads()
    panel._thread_factory = threads
    tk_root.update()

    panel.run_job()
    preparation = panel._preparing
    assert not entered.wait(0.3), "the worker waits until Tk has painted the press"
    assert not preparation.painted.is_set()
    tk_root.update_idletasks()
    assert preparation.painted.is_set()
    assert entered.wait(WAIT)
    for thread in threads.made:
        thread.join(WAIT)
    adopt_preparation(panel)
    assert panel._busy.is_set()


# --------------------------------------------------------------------------- #
# Cancel and Close
# --------------------------------------------------------------------------- #


def test_cancel_before_the_worker_runs_reserves_nothing_and_starts_nothing(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    threads = HeldPreparations()
    conversion = Conversion(monkeypatch)
    shown = dialogs(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt", "two.txt", thread_factory=threads)

    panel.run_job()
    started = time.perf_counter()
    panel.cancel_job()
    assert time.perf_counter() - started < 0.5
    assert panel.jobs.status.status_text == panel_module.STATUS_CANCELLING_PREPARATION
    assert panel._preparing is not None, "the panel waits for the worker's acknowledgement"
    panel.cancel_job()  # a second press changes nothing

    threads.run()
    adopt_preparation(panel)
    assert conversion.started == 0 and run_folders(output_base) == []
    assert idle_and_usable(panel)
    assert panel.jobs.status.status_text == panel_module.STATUS_PREPARATION_CANCELLED
    assert any("Cancelled before anything was started" in line for line in panel.log.summary)
    assert shown == []


def test_cancel_while_planning_stops_at_the_next_file_and_releases_the_run(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    threads = HeldPreparations()
    conversion = Conversion(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, *[f"{i:02d}.txt" for i in range(12)], thread_factory=threads)
    named: list[str] = []
    real = output_names.planned_name

    def planned_name(source, *args, **kwargs):
        named.append(Path(source).name)
        if len(named) == 3:
            panel.cancel_job()  # the test thread is the main thread, so this is the button
        return real(source, *args, **kwargs)

    monkeypatch.setattr(output_names, "planned_name", planned_name)
    panel.run_job()
    threads.run()
    assert len(named) == 3, "the next file's checkpoint saw the Cancel"
    adopt_preparation(panel)
    assert conversion.started == 0 and run_folders(output_base) == [], "the empty run folder was released"
    assert idle_and_usable(panel)


def test_a_plan_offered_just_before_cancel_is_never_adopted(make_panel, output_base, tmp_path, stubs, monkeypatch):
    threads = HeldPreparations()
    conversion = Conversion(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt", thread_factory=threads)

    panel.run_job()
    threads.run()  # planned and offered; the ending is queued
    assert len(run_folders(output_base)) == 1
    panel.cancel_job()  # takes the offered plan back; its folder is released by a release worker (inline here)
    assert run_folders(output_base) == []
    assert [t.name for t in threads.made if t.name.startswith("tts-release")] == ["tts-release-1"]
    adopt_preparation(panel)
    assert conversion.started == 0 and idle_and_usable(panel)


@pytest.mark.parametrize("moment", ["before the worker", "after the offer"])
def test_close_during_preparation_starts_nothing_and_leaves_no_run(
        make_panel, output_base, tmp_path, stubs, monkeypatch, moment):
    threads = HeldPreparations()
    conversion = Conversion(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt", "two.txt", thread_factory=threads)

    panel.run_job()
    if moment == "after the offer":
        threads.run()
    started = time.perf_counter()
    panel.close()
    assert time.perf_counter() - started < 1.0, "Close never waits for the preparation worker"
    if moment == "before the worker":
        threads.run()  # it sees the Cancel at its first checkpoint, before reserving
    assert run_folders(output_base) == [] and conversion.started == 0
    assert panel._preparing is None


def test_a_slow_filesystem_call_does_not_hold_cancel_and_the_panel_ends_when_it_returns(
        make_panel, output_base, tmp_path, stubs, monkeypatch, tk_root):
    conversion = Conversion(monkeypatch)
    inside = threading.Event()
    release = threading.Event()
    real = op.reserve_run_directory

    def slow_reserve(*args, **kwargs):
        inside.set()
        assert release.wait(WAIT)
        return real(*args, **kwargs)

    monkeypatch.setattr(op, "reserve_run_directory", slow_reserve)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt")
    threads = RealThreads()
    panel._thread_factory = threads
    take_the_suites_thread_start_collection()

    panel.run_job()
    tk_root.update_idletasks()
    assert inside.wait(WAIT)
    started = time.perf_counter()
    panel.cancel_job()
    acknowledged = time.perf_counter() - started
    panel._pump.tick()
    assert acknowledged < 0.1, acknowledged
    assert panel.jobs.status.status_text == panel_module.STATUS_CANCELLING_PREPARATION
    assert panel._preparing is not None and not go_enabled(panel), "no second Start while the first still holds a call"

    release.set()
    for thread in threads.made:
        thread.join(WAIT)
    adopt_preparation(panel)
    assert conversion.started == 0 and run_folders(output_base) == [] and idle_and_usable(panel)


def test_releasing_an_unadopted_run_never_waits_on_the_storage(make_panel, output_base, tmp_path, stubs,
                                                               monkeypatch):
    """Cancel and Close after the offer hand the empty folder to a release worker; the press returns at once."""
    Conversion(monkeypatch)
    real_release = op.release_if_empty
    released = threading.Event()

    def slow_release(reservation):
        time.sleep(0.4)
        try:
            return real_release(reservation)
        finally:
            released.set()

    monkeypatch.setattr(op, "release_if_empty", slow_release)
    held = HeldPreparations()
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt", thread_factory=held)
    real_threads = RealThreads()

    panel.run_job()
    held.run()
    panel._thread_factory = real_threads  # the release worker is a real thread
    take_the_suites_thread_start_collection()
    started = time.perf_counter()
    panel.cancel_job()
    assert time.perf_counter() - started < 0.1
    assert released.wait(WAIT)
    for thread in real_threads.made:
        thread.join(WAIT)
    adopt_preparation(panel)
    assert run_folders(output_base) == [] and idle_and_usable(panel)


# --------------------------------------------------------------------------- #
# Duplicate and stale endings
# --------------------------------------------------------------------------- #


def test_a_duplicate_ending_starts_one_run_and_its_extra_reservation_is_released(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    threads = HeldPreparations()
    conversion = Conversion(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt", thread_factory=threads)

    panel.run_job()
    threads.run()
    threads.run()  # the same body again: its second offer is refused and it releases its own reservation
    assert len(run_folders(output_base)) == 1
    panel._drain_preparation()
    panel._drain_preparation()
    assert conversion.started == 1 and len(run_folders(output_base)) == 1


def test_a_stale_ending_of_an_earlier_press_is_ignored_and_its_plan_released(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    threads = HeldPreparations()
    conversion = Conversion(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt", thread_factory=threads)

    panel.run_job()
    first = panel._preparing
    panel.cancel_job()
    threads.run(0)
    adopt_preparation(panel)  # the first preparation ended: cancelled
    panel.run_job()
    second = panel._preparing
    assert second is not first

    # A forged late ending of the first press that carries a real reservation (as a replayed body would).
    reservation = op.reserve_run_directory(panel_module.TOOL_KEY)
    late = panel_module._Preparation(snapshot=first.snapshot, run_config=None, readiness=lambda: (True, ""), number=1)
    assert late.offer(panel_module.PreparedRun(reservation=reservation, destinations={}))
    panel._prep_q.put(panel_module._PreparationMessage(late, "prepared"))
    panel._drain_preparation()
    assert not reservation.run_directory.exists(), "a stale plan's empty folder is released"
    assert panel._preparing is second and conversion.started == 0

    threads.run(1)
    adopt_preparation(panel)
    assert conversion.started == 1 and len(run_folders(output_base)) == 1


# --------------------------------------------------------------------------- #
# Failures leave the panel usable and the previous run untouched
# --------------------------------------------------------------------------- #


def _previous_partial_run(make_panel, tmp_path, monkeypatch, **kwargs):
    """A settled run with one retryable failure, the way a user reaches Retry Failed."""
    conversion = Conversion(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt", **kwargs)
    panel.run_job()
    adopt_preparation(panel)
    finish(panel, conversion.captured[-1])
    assert panel._result is not None and panel._result.has_retryable
    return panel, conversion


@pytest.mark.parametrize("failure", ["reservation", "planning", "fault"])
def test_a_failed_preparation_keeps_the_previous_result_and_a_following_start_works(
        make_panel, output_base, tmp_path, failing_stubs, monkeypatch, failure):
    panel, conversion = _previous_partial_run(make_panel, tmp_path, monkeypatch)
    previous_jobs, previous_result = panel.jobs, panel._result
    previous_run = Path(conversion.captured[-1]["params"]["run_directory"])
    previous_files = sorted(p.name for p in previous_run.rglob("*.mp3"))
    shown = dialogs(monkeypatch)
    real_reserve, real_named = op.reserve_run_directory, output_names.planned_name
    if failure == "reservation":
        monkeypatch.setattr(op, "reserve_run_directory", lambda *a, **k: (_ for _ in ()).throw(
            op.ReservationError("the output folder could not be created: X", "detail")))
    elif failure == "planning":
        monkeypatch.setattr(output_names, "planned_name", lambda *a, **k: (_ for _ in ()).throw(
            output_names.OutputNameError("the output folder path is too long", "detail")))
    else:
        monkeypatch.setattr(output_names, "planned_name", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    panel.run_job()
    adopt_preparation(panel)
    assert conversion.started == 1, "nothing new started"
    assert run_folders(output_base) == [previous_run], "a failed preparation leaves no run folder"
    assert sorted(p.name for p in previous_run.rglob("*.mp3")) == previous_files
    assert panel.jobs is previous_jobs and panel._result is previous_result and panel.jobs.has_retryable
    assert idle_and_usable(panel)
    assert panel.jobs.status.status_text == panel_module.STATUS_PREPARATION_FAILED
    expected_title = "Conversion not started" if failure == "fault" else "Output folder"
    assert shown and shown[-1][:2] == ("showerror", expected_title)

    monkeypatch.setattr(op, "reserve_run_directory", real_reserve)
    monkeypatch.setattr(output_names, "planned_name", real_named)
    panel.run_job()
    adopt_preparation(panel)
    assert conversion.started == 2 and len(run_folders(output_base)) == 2


def test_a_preparation_worker_that_cannot_start_unlocks_the_panel(make_panel, output_base, tmp_path, stubs,
                                                                   monkeypatch):
    conversion = Conversion(monkeypatch)
    shown = dialogs(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt")
    real_factory = panel._thread_factory

    def refusing(target, name):
        if name.startswith("tts-prepare"):
            raise RuntimeError("can't start new thread")
        return real_factory(target, name)

    panel._thread_factory = refusing
    panel.run_job()
    assert panel._preparing is None and idle_and_usable(panel)
    assert run_folders(output_base) == [] and conversion.started == 0
    assert shown and shown[-1][:2] == ("showerror", "Conversion not started")
    panel._thread_factory = real_factory
    panel.run_job()
    adopt_preparation(panel)
    assert conversion.started == 1


@pytest.mark.parametrize("where", ["constructor", "render"])
def test_a_job_area_that_cannot_be_built_changes_nothing_and_releases_the_run(
        make_panel, output_base, tmp_path, failing_stubs, monkeypatch, where):
    panel, conversion = _previous_partial_run(make_panel, tmp_path, monkeypatch)
    previous_jobs, previous_result = panel.jobs, panel._result
    previous_snapshot, previous_destinations = panel._snapshot, panel.destinations()
    drains_before = len(panel._pump._drains)
    shown = dialogs(monkeypatch)
    real_adapter = job_ui.JobAdapter

    armed: list = []

    class Broken(real_adapter):
        """Fails in its constructor, or -- once constructed -- on the build's own render."""

        __slots__ = ()

        def __init__(self, *args, **kwargs):
            if where == "constructor":
                raise RuntimeError("no job area today")
            super().__init__(*args, **kwargs)  # its constructor renders once, successfully
            armed.append(self)

        def render(self):
            if any(self is built for built in armed):
                raise RuntimeError("cannot draw")
            return super().render()

    monkeypatch.setattr(job_ui, "JobAdapter", Broken)
    panel.run_job()
    adopt_preparation(panel)
    assert conversion.started == 1, "no conversion worker for an attempt that never got a job area"
    assert run_folders(output_base) == [Path(conversion.captured[0]["params"]["run_directory"])]
    assert panel.jobs is previous_jobs and not previous_jobs.closed
    assert panel._result is previous_result and panel.jobs.has_retryable
    assert panel._snapshot is previous_snapshot and panel.destinations() == previous_destinations
    assert len(panel._pump._drains) == drains_before, "no extra drain was left behind"
    assert idle_and_usable(panel)
    assert shown and shown[-1][:2] == ("showerror", "Conversion not started")

    monkeypatch.setattr(job_ui, "JobAdapter", real_adapter)
    retried = panel.retry_failed()
    assert retried is not None and conversion.started == 2, "the previous run's Retry Failed still works"


def test_an_unexpected_error_before_the_run_takes_over_releases_the_run_and_frees_the_panel(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    conversion = Conversion(monkeypatch)
    shown = dialogs(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt")

    class Broken:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("no controller today")

    monkeypatch.setattr(panel_module.job_control, "JobController", Broken)
    panel.run_job()
    adopt_preparation(panel)
    assert conversion.started == 0 and run_folders(output_base) == [] and idle_and_usable(panel)
    assert shown and shown[-1][:2] == ("showerror", "Conversion not started")


def test_the_drain_frees_the_panel_even_when_ending_a_preparation_fails_once(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    threads = HeldPreparations()
    Conversion(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt", thread_factory=threads)
    real_end = panel._end_preparation
    calls = {"n": 0}

    def end_once_broken(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("the first ending could not be drawn")
        return real_end(*args, **kwargs)

    monkeypatch.setattr(panel, "_end_preparation", end_once_broken)
    panel.run_job()
    panel.cancel_job()
    threads.run()
    panel._drain_preparation()  # must not raise
    assert calls["n"] == 2 and idle_and_usable(panel) and run_folders(output_base) == []


def test_a_conversion_worker_that_cannot_start_settles_the_run_as_failed(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt", "two.txt")

    class Refused:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(panel_module.threading, "Thread", Refused)
    panel.run_job()
    adopt_preparation(panel)
    panel._pump.tick()
    panel._pump.tick()
    assert panel._controller.state is JobState.FAILED
    assert panel._result is not None and not panel._result.has_retryable
    assert not panel._busy.is_set() and go_enabled(panel) and not listbox_locked(panel)
    assert panel._worker is None
    assert [p for p in Path(panel._run_directory).rglob("*") if p.is_file()] == [], "nothing was written"


# --------------------------------------------------------------------------- #
# The frozen configuration
# --------------------------------------------------------------------------- #


def test_preferences_changed_after_the_press_do_not_move_the_run(make_panel, tmp_path, stubs, monkeypatch):
    from shared import settings as app_settings

    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    shared_config.invalidate()
    try:
        bases = {"first": tmp_path / "first-base", "second": tmp_path / "second-base"}
        current = {"name": "first"}
        monkeypatch.setattr(shared_config, "get_effective", lambda: {"base": current["name"]})
        monkeypatch.setattr(op, "resolve_output_base",
                            lambda effective=None: bases[(effective or {"base": current["name"]})["base"]])
        threads = HeldPreparations()
        conversion = Conversion(monkeypatch)
        panel, _ = direct_panel(make_panel, tmp_path, "one.txt", thread_factory=threads)

        panel.run_job()
        current["name"] = "second"  # Preferences saved while the worker waits
        threads.run()
        adopt_preparation(panel)
        run = Path(conversion.captured[0]["params"]["run_directory"])
        assert run.is_relative_to(bases["first"]) and not bases["second"].exists()
    finally:
        app_settings.use_path(None)
        shared_config.invalidate()


def test_a_voice_made_unavailable_while_preparing_stops_the_run_before_synthesis(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    threads = HeldPreparations()
    conversion = Conversion(monkeypatch)
    shown = dialogs(monkeypatch)
    ready = {"ok": True}
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt", thread_factory=threads,
                            local_assets=lambda backend, voice_id: (ready["ok"], "" if ready["ok"] else
                                                                    "The Kokoro voices are not installed"))
    panel.selected_voice_label.set(kokoro_label())
    panel._on_voice_selected()

    panel.run_job()
    ready["ok"] = False  # the model files went away while the job was being prepared
    threads.run()
    adopt_preparation(panel)
    assert conversion.started == 0 and run_folders(output_base) == []
    assert idle_and_usable(panel)
    assert shown and shown[-1][:2] == ("showwarning", "Voice unavailable")
    assert panel.voice_status_var.get() == "The Kokoro voices are not installed", "the projection caught up"

    ready["ok"] = True
    panel.run_job()
    threads.run()
    adopt_preparation(panel)
    assert conversion.started == 1 and conversion.captured[0]["params"]["backend"] == "kokoro"


def test_retry_failed_after_a_partial_run_keeps_its_destinations_and_the_finished_file(
        make_panel, output_base, tmp_path, failing_stubs, monkeypatch):
    panel, conversion = _previous_partial_run(make_panel, tmp_path, monkeypatch)
    first = conversion.captured[0]["params"]
    run = Path(first["run_directory"])
    good = next(item for item in first["items"] if "good" in Path(item["source"]).name)
    bad = next(item for item in first["items"] if "bad" in Path(item["source"]).name)
    finished_bytes = Path(good["destination"]).read_bytes()

    failing_stubs.marker = "never"
    panel.retry_failed()
    assert conversion.started == 2 and panel._preparing is None, "a retry is not re-planned"
    retry = conversion.captured[1]["params"]
    assert [item["item_id"] for item in retry["items"]] == [bad["item_id"]]
    assert retry["items"][0]["destination"] == bad["destination"] and retry["run_directory"] == run
    finish(panel, conversion.captured[1])
    assert Path(good["destination"]).read_bytes() == finished_bytes, "the finished file is never overwritten"
    assert Path(bad["destination"]).is_file()
    assert run_folders(output_base) == [run]


def test_a_new_start_after_a_partial_run_takes_a_new_folder_and_leaves_the_old_one(
        make_panel, output_base, tmp_path, failing_stubs, monkeypatch):
    panel, conversion = _previous_partial_run(make_panel, tmp_path, monkeypatch)
    first_run = Path(conversion.captured[0]["params"]["run_directory"])
    before = {p: p.read_bytes() for p in first_run.rglob("*.mp3")}
    panel.run_job()
    adopt_preparation(panel)
    second_run = Path(conversion.captured[1]["params"]["run_directory"])
    assert second_run != first_run and {p: p.read_bytes() for p in first_run.rglob("*.mp3")} == before


# --------------------------------------------------------------------------- #
# Small Tk costs that stayed on the press
# --------------------------------------------------------------------------- #


def test_an_unchanged_voice_message_is_not_re_measured_at_start(make_panel, output_base, tmp_path, stubs,
                                                                 monkeypatch):
    calls: list[str] = []
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt")
    monkeypatch.setattr(panel, "_content_changed", lambda: calls.append("measure"))
    panel.run_job()
    assert calls == [], "Edge has no voice message, so nothing to re-measure"
    adopt_preparation(panel)


def test_a_voice_message_that_appears_at_start_is_measured(make_panel, output_base, tmp_path, stubs, monkeypatch):
    ready = {"ok": True}
    shown = dialogs(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt",
                            local_assets=lambda b, v: (ready["ok"], "" if ready["ok"] else "missing models"),
                            installable=lambda b, v, r: None)
    panel.selected_voice_label.set(kokoro_label())
    panel._on_voice_selected()
    calls: list[str] = []
    monkeypatch.setattr(panel, "_content_changed", lambda: calls.append("measure"))
    ready["ok"] = False
    panel.run_job()
    assert calls == ["measure"] and shown[-1][:2] == ("showwarning", "Voice unavailable")


def test_the_imported_list_is_reconfigured_only_when_its_lock_really_changes(make_panel, output_base, tmp_path,
                                                                             stubs, monkeypatch):
    """A Tk Listbox re-measures every row when configured (about 40 ms at 5,000 files): an unchanged lock is not sent,
    and an accepted run is never unlocked and locked again between the press and its first state."""
    conversion = Conversion(monkeypatch)
    panel, _ = direct_panel(make_panel, tmp_path, "one.txt", "two.txt")
    listbox = panel.importer.list.listbox
    sent: list[str] = []
    real_configure = listbox.configure

    def configure(*args, **kwargs):
        if "state" in kwargs:
            sent.append(kwargs["state"])
        return real_configure(*args, **kwargs)

    monkeypatch.setattr(listbox, "configure", configure)
    panel.importer.list.set_locked(False)
    assert sent == [], "already unlocked: nothing reaches Tk"
    panel.run_job()
    adopt_preparation(panel)
    panel._pump.tick()
    panel._pump.tick()
    assert panel.jobs.state is JobState.RUNNING and listbox_locked(panel)
    assert sent == ["disabled"], "locked once, at the press"
    finish(panel, conversion.captured[0])
    assert sent == ["disabled", "normal"] and not listbox_locked(panel)


# --------------------------------------------------------------------------- #
# Responsiveness on a real Tk event loop
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shape, size", [("direct-same", 2341), ("folder", 2341), ("direct-same", 5000)],
                         ids=["direct-identical-2341", "folder-2341", "direct-identical-5000"])
def test_the_press_returns_at_once_and_tk_keeps_its_heartbeat_while_the_job_is_prepared(
        make_panel, output_base, tmp_path, stubs, monkeypatch, tk_root, shape, size):
    """de62430 planned on Tk: the press held the window 3.80 s (2,341 identical direct titles), 5.76 s (2,341 files in
    sub-folders of one folder) and 7.86 s (5,000 identical). The heartbeat is a real ``after`` chain on ``mainloop``
    and the panel's own pump adopts the plan. Bounds are generous on purpose (Windows' 15.6 ms timer quantum alone
    makes an idle 20 ms heartbeat's largest gap about 63 ms); the measured figures are printed (CP4MEASURE)."""
    conversion = Conversion(monkeypatch)
    library = tmp_path / "lib"
    if shape == "direct-same":
        chosen = sources(library, *[f"d{i:05d}/Chapter.txt" for i in range(size)])
        panel = make_panel(choose_files=lambda: chosen, thread_factory=RecordingThreads(),
                           confirm_large_result=lambda outcome: True)
        panel.importer.add_files()
    else:
        sources(library, *[f"Book {i:05d}/Chapter.txt" for i in range(size)])
        panel = make_panel(choose_folder=lambda: (library,), thread_factory=RecordingThreads(),
                           confirm_large_result=lambda outcome: True)
        panel.importer.add_folder()
        deadline = time.monotonic() + WAIT
        while len(panel._manager.snapshot().files) < size and time.monotonic() < deadline:
            panel._pump.tick()
    assert len(panel._manager.snapshot().files) == size
    threads = RealThreads()
    panel._thread_factory = threads
    panel.pack(fill="both", expand=True)
    tk_root.update()
    take_the_suites_thread_start_collection()

    gaps: list[tuple[float, float]] = []
    press: dict = {}
    state = {"last": time.perf_counter(), "after": None, "hard": time.perf_counter() + 180.0}

    def beat():
        now = time.perf_counter()
        gaps.append((now, now - state["last"]))
        state["last"] = now
        if conversion.started and "adopted" not in press:
            press["adopted"] = now
        if ("adopted" in press and now > press["adopted"] + 0.2) or now > state["hard"]:
            tk_root.quit()
            return
        state["after"] = tk_root.after(20, beat)

    def press_start():
        press["at"] = time.perf_counter()
        panel.run_job()
        press["returned"] = time.perf_counter()
        press["status"] = panel.jobs.status.status_text
        press["cancel"] = panel.jobs.controls.availability()[JobAction.CANCEL]
        press["locked"] = listbox_locked(panel)

    state["after"] = tk_root.after(20, beat)
    tk_root.after(60, press_start)
    tk_root.mainloop()
    for thread in threads.made:
        thread.join(WAIT)
    assert "adopted" in press, "the prepared plan was never adopted"
    window = sorted(gap for at, gap in gaps if press["at"] <= at <= press["adopted"])
    measure = {"shape": shape, "n": size, "press_ms": round((press["returned"] - press["at"]) * 1000, 2),
               "press_to_adoption_s": round(press["adopted"] - press["at"], 3), "beats": len(window),
               "max_gap_ms": round(window[-1] * 1000, 1),
               "p95_gap_ms": round(window[min(len(window) - 1, int(0.95 * len(window)))] * 1000, 1)}
    print("CP4MEASURE " + json.dumps(measure))
    assert press["returned"] - press["at"] < 0.5, measure
    assert press["status"] == panel_module.STATUS_PREPARING and press["cancel"] is True and press["locked"] is True
    assert window[-1] < 0.5, measure
    assert conversion.started == 1 and len(conversion.captured[0]["params"]["items"]) == size
    assert [t.name for t in threads.made] == ["tts-prepare-1"]
