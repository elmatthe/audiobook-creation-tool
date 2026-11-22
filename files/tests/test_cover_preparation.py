"""Cover Image's standard Start prepares the run off the Tk thread — v0.8.2 Checkpoint 5.

At fee286f a standard-output Start reserved the run folder and planned every destination inside the button's Tk
callback (one shared-planner pass, two OS path resolutions and a link walk per image), so the press held the window
for seconds at a few thousand images. Now the press validates and freezes on Tk exactly as before, shows "Preparing
job…" with Cancel, and one ``cover-prepare-N`` worker reserves and plans (:func:`cover_resizer.prepare_run`); the
pump adopts the plan and only then builds the run's controller and job area and starts the resize worker.

What these tests protect:

1. **Nothing on Tk.** The press reserves and plans nothing; the worker reaches no widget (statically and by a thread
   profiler); a real ``mainloop`` heartbeat keeps beating at 2,341 images.
2. **Same destinations.** The prepared plan is the synchronous planner's, for every import shape.
3. **One owner per reservation.** Cancel and Close before, during and after the offer; stale and duplicate endings;
   a slow release never holds Tk; every abandoned run folder is released exactly once and only while empty.
4. **Failures change nothing.** A refused or faulted preparation, a worker or job area that cannot start, and a resize
   worker that cannot start each leave the previous run, its result and Retry Failed as they were, and the next Start
   works.
5. **The source-side modes are untouched.** Numbered copies and replacement reserve nothing and never prepare; the
   replacement confirmation is asked on the Tk thread, and a refusal changes nothing.
6. **The resize worker checks each image against one index** of its attempt's inputs, not every input again.
"""

from __future__ import annotations

import ast
import json
import threading
import time
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")
tk = pytest.importorskip("tkinter")

from shared import config  # noqa: E402
from shared import job_control as jc  # noqa: E402
from shared import job_ui  # noqa: E402
from shared import output_paths as op  # noqa: E402

from artwork import cover_resizer as cr  # noqa: E402

from test_import_coordination import RealThreads, RecordingThreads  # noqa: E402
from test_cover_jobs import (  # noqa: E402,F401 - fixtures are found by name
    InlineRunner,
    _clean_capability_cache,
    arm_replacement,
    drain,
    fail_named,
    import_files,
    import_folder,
    make_image,
    make_panel,
    output_base,
    run_dir_of,
    sha,
    tk_root,
    written_under,
)

#: Every wait is bounded, so a deadlock fails instead of hanging the suite.
WAIT = 30.0

SOURCE = Path(cr.__file__)


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
    """Inline for every thread (imports, releases) except the preparation worker, whose body is kept until the test
    runs it -- on the test's own thread, so the moment it runs is the test's choice."""

    def __init__(self) -> None:
        super().__init__()
        self.held: list = []

    def __call__(self, target, name):
        if name.startswith("cover-prepare-"):
            self.held.append(target)
            self.made.append(_Idle(name))
            return self.made[-1]
        return super().__call__(target, name)

    def run(self, index: int = -1) -> None:
        self.held[index]()


def run_folders(output_base: Path) -> list[Path]:
    """Every reserved run folder under the standard output base."""
    return sorted(run for tool in output_base.glob("*-Outputs") for run in tool.iterdir())


def dialogs(monkeypatch) -> list[tuple[str, str, str]]:
    shown: list[tuple[str, str, str]] = []
    for kind in ("showwarning", "showerror", "showinfo"):
        monkeypatch.setattr(cr.messagebox, kind,
                            lambda title, text="", *a, _k=kind, **k: shown.append((_k, title, text)))
    return shown


def start_enabled(panel) -> bool:
    return str(panel.btn_convert.cget("state")) == "normal"


def idle_and_usable(panel) -> bool:
    return panel._preparing is None and not panel._busy.is_set() and start_enabled(panel)


def press(panel, size: int = 256) -> None:
    panel.var_size.set(size)
    panel.start_resize()


def take_the_suites_thread_start_collection() -> None:
    """Take the suite's once-per-test thread-start ``gc.collect`` now, outside any timed window (Checkpoint 2)."""
    boundary = threading.Thread(target=lambda: None, name="cp5-gate-boundary")
    boundary.start()
    boundary.join()


class TkCallsFromWorkers:
    """Every Tcl call and every tkinter-level Python call made on a thread other than the main one.

    Threads are identified by ``threading.get_ident()`` only: ``threading.current_thread()`` from a profile hook
    deadlocks a profiled thread that ends while the hook is set (v0.8.2 Checkpoint 4).
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
    """What the fee286f press planned for the panel's current queue: the same function, on this thread."""
    return cr.plan_destinations(panel.manager.snapshot(), run_directory,
                                planner=op.DestinationPlanner(run_directory))


def wait_for(predicate, *, panel=None, root=None) -> None:
    deadline = time.monotonic() + WAIT
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        if panel is not None:
            drain(panel, 1)
        if root is not None:
            root.update()
        time.sleep(0.002)


def previous_partial_run(make_panel, tmp_path, monkeypatch, **kwargs):
    """A finished standard run with one retryable failure (Retry Failed available)."""
    runner = kwargs.pop("job_runner", None) or InlineRunner()
    panel = make_panel(job_runner=runner, **kwargs)
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"), make_image(tmp_path / "art" / "b.jpg"))
    with monkeypatch.context() as patch:
        fail_named(patch, "b.jpg")
        press(panel)
        drain(panel)
    assert panel.jobs.has_retryable is True
    return panel, runner


# --------------------------------------------------------------------------- #
# 1. Nothing on Tk
# --------------------------------------------------------------------------- #


def test_the_press_reserves_and_plans_nothing_on_tk_and_shows_preparing(make_panel, output_base, tmp_path):
    threads = HeldPreparations()
    runner = InlineRunner(defer=True)
    panel = make_panel(thread_factory=threads, job_runner=runner)
    import_files(panel, make_image(tmp_path / "one" / "cover.jpg"), make_image(tmp_path / "two" / "cover.jpg"))

    press(panel)

    assert run_folders(output_base) == [], "the press reserved nothing"
    assert runner.calls == [] and panel._preparing is not None and not panel._busy.is_set()
    assert panel.jobs.status.status_text == cr.STATUS_PREPARING
    assert panel.jobs.controls.availability()[jc.JobAction.CANCEL] is True
    assert not start_enabled(panel), "Start is unavailable while preparing"
    assert [t.name for t in threads.made if t.name.startswith("cover-")] == ["cover-prepare-1"]

    threads.run()
    drain(panel)
    run_dir = run_dir_of(output_base)
    assert run_folders(output_base) == [run_dir]
    assert len(runner.calls) == 1 and panel._preparing is None and panel._busy.is_set()
    assert runner.calls[0]["destinations"] == synchronous_plan(panel, run_dir)
    assert panel.var_outdir.get() == str(run_dir) and panel._last_run_dir == run_dir
    runner.release()
    drain(panel)
    assert written_under(run_dir) == ["cover-1.jpg", "cover.jpg"]


def test_progress_updates_the_stage_line_and_keeps_preparing(make_panel, output_base, tmp_path):
    threads = HeldPreparations()
    panel = make_panel(thread_factory=threads, job_runner=InlineRunner(defer=True))
    import_files(panel, make_image(tmp_path / "a.jpg"), make_image(tmp_path / "b.jpg"))
    press(panel)
    preparation = panel._preparing
    panel._post_preparation(cr._PreparationMessage(preparation, "progress", done=1, total=2))
    drain(panel)
    assert panel._preparing is preparation, "progress never ends a preparation"
    assert panel.jobs.status.var_stage.get() == "Preparing 2 image(s): planning output names (50%)"
    assert panel.jobs.status.status_text == cr.STATUS_PREPARING


def test_repeated_presses_start_one_preparation(make_panel, output_base, tmp_path):
    threads = HeldPreparations()
    panel = make_panel(thread_factory=threads, job_runner=InlineRunner(defer=True))
    import_files(panel, make_image(tmp_path / "a.jpg"))
    for _ in range(3):
        press(panel)
    assert len(threads.held) == 1


def test_the_worker_side_names_no_tk_and_no_panel_state():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    bodies = [node for node in tree.body
              if (isinstance(node, ast.FunctionDef) and node.name in ("prepare_run", "plan_destinations"))
              or (isinstance(node, ast.ClassDef) and node.name in ("_Preparation", "_PreparationMessage"))]
    assert len(bodies) == 4
    for body in bodies:
        names = {n.id for n in ast.walk(body) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(body) if isinstance(n, ast.Attribute)}
        assert not names & {"tk", "ttk", "messagebox", "filedialog", "CoverResizerUI"}, body.name
        tk_calls = {"after", "after_idle", "update_idletasks", "configure", "winfo_toplevel", "event_generate"}
        assert not {a for a in attrs if a.startswith("var_") or a in tk_calls}, body.name
        if isinstance(body, ast.FunctionDef):  # module-level bodies: no panel to reach at all
            assert "self" not in names, body.name


def test_no_worker_ever_calls_tk(make_panel, output_base, tmp_path, tk_root):
    runner = InlineRunner(defer=True)
    panel = make_panel(job_runner=runner)
    import_files(panel, *[make_image(tmp_path / f"d{i}" / "cover.jpg") for i in range(30)])
    threads = RealThreads()
    panel._thread_factory = threads
    take_the_suites_thread_start_collection()
    with TkCallsFromWorkers() as recorder:
        press(panel)
        wait_for(lambda: runner.calls, panel=panel, root=tk_root)
    for thread in threads.made:
        thread.join(WAIT)
    assert recorder.violations == []
    assert [t.name for t in threads.made] == ["cover-prepare-1"]


def test_the_worker_plans_only_after_tk_has_painted_the_press(make_panel, output_base, tmp_path, monkeypatch,
                                                              tk_root):
    runner = InlineRunner(defer=True)
    panel = make_panel(job_runner=runner)
    import_files(panel, make_image(tmp_path / "a.jpg"))
    seen = {}
    real = op.reserve_run_directory

    def reserve(*args, **kwargs):
        seen["painted"] = panel._preparing is not None and panel._preparing.painted.is_set()
        seen["thread"] = threading.current_thread().name
        return real(*args, **kwargs)

    monkeypatch.setattr(op, "reserve_run_directory", reserve)
    panel._thread_factory = RealThreads()
    press(panel)
    wait_for(lambda: runner.calls, panel=panel, root=tk_root)
    assert seen == {"painted": True, "thread": "cover-prepare-1"}


# --------------------------------------------------------------------------- #
# 2. Same destinations
# --------------------------------------------------------------------------- #


def _shape(panel, tmp_path: Path, shape: str) -> None:
    if shape == "duplicates":
        import_files(panel, *[make_image(tmp_path / f"d{i}" / name)
                              for i, name in enumerate(["cover.jpg", "Cover.jpg", "COVER.JPG", "cover.jpg"])])
    elif shape == "one-folder":
        for i in range(4):
            make_image(tmp_path / "lib" / f"Book {i}" / "cover.jpg")
        make_image(tmp_path / "lib" / "cover.jpg")
        import_folder(panel, tmp_path / "lib")
    elif shape == "two-roots":
        for root in ("x", "y"):
            make_image(tmp_path / root / "Art" / "Part 1" / "cover.jpg")
            make_image(tmp_path / root / "Art" / "front.png")
        import_folder(panel, tmp_path / "x" / "Art")
        import_folder(panel, tmp_path / "y" / "Art")
    elif shape == "mixed":
        import_files(panel, make_image(tmp_path / "picked" / "cover.jpg"))
        make_image(tmp_path / "lib" / "cover.jpg")
        make_image(tmp_path / "lib" / "Sub" / "cover.jpg")
        import_folder(panel, tmp_path / "lib")
    elif shape == "written-as-jpg":
        webp = tmp_path / "w" / "art.webp"
        webp.parent.mkdir(parents=True)
        Image.new("RGB", (40, 40)).save(webp, format="WEBP")
        import_files(panel, webp, make_image(tmp_path / "j" / "art.jpg"))
    else:  # pragma: no cover
        raise AssertionError(shape)


@pytest.mark.parametrize("shape", ["duplicates", "one-folder", "two-roots", "mixed", "written-as-jpg"])
def test_the_prepared_destinations_are_exactly_the_synchronous_planners(make_panel, output_base, tmp_path, shape):
    threads = HeldPreparations()
    runner = InlineRunner(defer=True)
    panel = make_panel(thread_factory=threads, job_runner=runner)
    _shape(panel, tmp_path, shape)
    press(panel)
    threads.run()
    drain(panel)
    run_dir = run_dir_of(output_base)
    prepared = runner.calls[0]["destinations"]
    assert prepared == synchronous_plan(panel, run_dir)
    assert list(prepared) == list(panel.manager.snapshot().occurrence_ids), "occurrence order kept"


def test_the_planning_checkpoint_changes_no_name_and_sees_each_source_once(make_panel, tmp_path):
    panel = make_panel()
    _shape(panel, tmp_path, "mixed")
    snapshot = panel.manager.snapshot()
    seen = []
    with_checkpoint = cr.plan_destinations(snapshot, tmp_path / "run", checkpoint=lambda: seen.append(1))
    without = cr.plan_destinations(snapshot, tmp_path / "run")
    assert with_checkpoint == without
    assert len(seen) == len(snapshot.files)


# --------------------------------------------------------------------------- #
# 3. One owner per reservation
# --------------------------------------------------------------------------- #


def test_the_offer_adopt_withdraw_protocol_hands_each_plan_to_exactly_one_side(tmp_path):
    """The lock-held decisions on their own: one offer per press; nothing is adopted once Cancel was asked, even if a
    plan is waiting; withdraw hands an offered plan back exactly once; the checkpoint stops a cancelled worker."""
    def fresh():
        return cr._Preparation(snapshot=type("S", (), {"item_ids": ("a",)})(), run_config=None, number=1)

    plan = cr.PreparedRun(reservation=None, destinations={})
    preparation = fresh()
    assert preparation.offer(plan) is True
    assert preparation.offer(cr.PreparedRun(reservation=None, destinations={})) is False, "one offer per press"
    preparation.cancel_requested.set()  # asked, not yet withdrawn
    assert preparation.adopt() is None, "never adopted once Cancel was asked"
    assert preparation.withdraw() is plan and preparation.withdraw() is None, "handed back exactly once"
    with pytest.raises(cr.ConversionCancelled):
        preparation.checkpoint()

    preparation = fresh()
    assert preparation.offer(plan) is True and preparation.adopt() is plan and preparation.adopt() is None
    assert preparation.withdraw() is None, "an adopted plan is never handed back for release"

    preparation = fresh()
    assert preparation.withdraw() is None and preparation.painted.is_set()
    assert preparation.offer(plan) is False, "an offer after withdrawal is refused: the worker releases it"


def test_cancel_before_the_worker_runs_reserves_nothing_and_starts_nothing(make_panel, output_base, tmp_path):
    threads = HeldPreparations()
    runner = InlineRunner()
    panel = make_panel(thread_factory=threads, job_runner=runner)
    import_files(panel, make_image(tmp_path / "a.jpg"))
    press(panel)
    panel.cancel()
    assert panel.jobs.status.status_text == cr.STATUS_CANCELLING_PREPARATION
    panel.cancel()  # a second click changes nothing
    threads.run()
    drain(panel)
    assert run_folders(output_base) == [] and runner.calls == []
    assert panel.jobs.status.status_text == cr.STATUS_PREPARATION_CANCELLED
    assert idle_and_usable(panel)


def test_cancel_while_planning_stops_at_the_next_image_and_releases_the_run(make_panel, output_base, tmp_path,
                                                                           monkeypatch):
    threads = HeldPreparations()
    runner = InlineRunner()
    panel = make_panel(thread_factory=threads, job_runner=runner)
    import_files(panel, *[make_image(tmp_path / f"d{i}" / "cover.jpg") for i in range(8)])
    named = []
    real = cr.written_name

    def naming(source):
        named.append(source)
        if len(named) == 3:
            panel.cancel()
        return real(source)

    monkeypatch.setattr(cr, "written_name", naming)
    press(panel)
    threads.run()
    drain(panel)
    assert len(named) == 3, "the worker stopped at the next image"
    assert run_folders(output_base) == [], "the reserved run folder was released"
    assert runner.calls == [] and idle_and_usable(panel)


def test_a_plan_offered_just_before_cancel_is_never_adopted(make_panel, output_base, tmp_path):
    threads = HeldPreparations()
    runner = InlineRunner()
    panel = make_panel(thread_factory=threads, job_runner=runner)
    import_files(panel, make_image(tmp_path / "a.jpg"))
    press(panel)
    threads.run()  # offered, not yet adopted
    assert len(run_folders(output_base)) == 1
    panel.cancel()  # withdrawn: released at once by a release worker (inline here)
    assert run_folders(output_base) == []
    drain(panel)
    assert runner.calls == [] and idle_and_usable(panel)
    assert panel.jobs.status.status_text == cr.STATUS_PREPARATION_CANCELLED


@pytest.mark.parametrize("when", ["before-offer", "after-offer"])
def test_close_during_preparation_starts_nothing_and_leaves_no_run(make_panel, output_base, tmp_path, when):
    threads = HeldPreparations()
    runner = InlineRunner()
    panel = make_panel(thread_factory=threads, job_runner=runner)
    import_files(panel, make_image(tmp_path / "a.jpg"))
    press(panel)
    if when == "after-offer":
        threads.run()
    panel.close()
    if when == "before-offer":
        threads.run()  # the late worker sees the withdrawal at its first checkpoint
    drain(panel)
    assert run_folders(output_base) == [] and runner.calls == []


def test_releasing_an_unadopted_run_never_waits_on_the_storage(make_panel, output_base, tmp_path, monkeypatch):
    threads = HeldPreparations()
    panel = make_panel(thread_factory=threads, job_runner=InlineRunner())
    import_files(panel, make_image(tmp_path / "a.jpg"))
    press(panel)
    threads.run()
    real = op.release_if_empty
    monkeypatch.setattr(op, "release_if_empty", lambda reservation: (time.sleep(0.4), real(reservation))[1])
    released = RealThreads()
    panel._thread_factory = released
    take_the_suites_thread_start_collection()
    began = time.perf_counter()
    panel.cancel()
    spent = time.perf_counter() - began
    assert spent < 0.1, spent
    for thread in released.made:
        thread.join(WAIT)
    assert [t.name for t in released.made] == ["cover-release-1"]
    assert run_folders(output_base) == []


def test_a_duplicate_ending_starts_one_run_and_its_extra_reservation_is_released(make_panel, output_base, tmp_path):
    threads = HeldPreparations()
    runner = InlineRunner(defer=True)
    panel = make_panel(thread_factory=threads, job_runner=runner)
    import_files(panel, make_image(tmp_path / "a.jpg"))
    press(panel)
    threads.run()
    threads.run()  # the same body again: its offer is refused and it releases its own reservation
    drain(panel)
    assert len(runner.calls) == 1
    assert run_folders(output_base) == [run_dir_of(output_base)]


def test_a_stale_ending_of_an_earlier_press_is_ignored_and_its_plan_released(make_panel, output_base, tmp_path):
    runner = InlineRunner(defer=True)
    panel = make_panel(job_runner=runner)
    import_files(panel, make_image(tmp_path / "a.jpg"))
    snapshot = jc.capture_run(snapshot_id="cover-old", files=panel.manager, catalog=panel.import_catalog,
                              import_options=panel.importer.options.options(),
                              effective_config=panel._effective_config,
                              tool_options=cr.freeze_cover_options(256, False, cr.MODE_STANDARD), created_at=0.0)
    old = cr._Preparation(snapshot=snapshot, run_config=config.get_effective(), number=99)
    reservation = op.reserve_run_directory(cr.TOOL_KEY)
    assert old.offer(cr.PreparedRun(reservation=reservation, destinations={}))
    panel._post_preparation(cr._PreparationMessage(old, "prepared"))
    drain(panel)
    assert runner.calls == [] and run_folders(output_base) == []
    assert idle_and_usable(panel)


# --------------------------------------------------------------------------- #
# 4. Failures change nothing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("failure", ["reserve-refused", "plan-refused", "plan-fault"])
def test_a_failed_preparation_keeps_the_previous_result_and_a_following_start_works(
        make_panel, output_base, tmp_path, monkeypatch, failure):
    panel, runner = previous_partial_run(make_panel, tmp_path, monkeypatch)
    previous = (panel.jobs, panel.run_result, panel._last_run_dir, panel.var_outdir.get(), dict(panel.destinations()))
    shown = dialogs(monkeypatch)
    with monkeypatch.context() as patch:
        if failure == "reserve-refused":
            def refuse(tool_key, **kwargs):
                raise op.OutputPathError("The output folder cannot be created.", "denied for this test")
            patch.setattr(op, "reserve_run_directory", refuse)
        elif failure == "plan-refused":
            def refuse(*args, **kwargs):
                raise op.OutputPathError("A destination could not be planned.", "refused for this test")
            patch.setattr(cr, "plan_destinations", refuse)
        else:
            def broken(*args, **kwargs):
                raise RuntimeError("planner broke for this test")
            patch.setattr(cr, "plan_destinations", broken)
        press(panel)
        drain(panel)
    expected = {"reserve-refused": ("showerror", "Output folder", "The output folder cannot be created."),
                "plan-refused": ("showerror", "Output folder", "A destination could not be planned."),
                "plan-fault": ("showerror", "Resize not started", cr._NOT_PREPARED)}[failure]
    assert shown == [expected]
    assert (panel.jobs, panel.run_result, panel._last_run_dir, panel.var_outdir.get(),
            dict(panel.destinations())) == previous
    assert panel.jobs.has_retryable is True and len(runner.calls) == 1
    assert run_folders(output_base) == [run_dir_of(output_base)], "no empty folder left behind"
    assert idle_and_usable(panel)
    press(panel)
    drain(panel)
    assert len(runner.calls) == 2 and run_folders(output_base)[-1] == run_dir_of(output_base, 2)


def test_a_preparation_worker_that_cannot_start_unlocks_the_panel(make_panel, output_base, tmp_path, monkeypatch):
    panel, runner = previous_partial_run(make_panel, tmp_path, monkeypatch)
    shown = dialogs(monkeypatch)
    inline = panel._thread_factory

    def factory(target, name):
        if name.startswith("cover-prepare-"):
            raise RuntimeError("no thread for this test")
        return inline(target, name)

    panel._thread_factory = factory
    press(panel)
    assert shown == [("showerror", "Resize not started", cr._NOT_PREPARED)]
    assert panel.jobs.has_retryable is True and idle_and_usable(panel)
    assert run_folders(output_base) == [run_dir_of(output_base)]
    panel._thread_factory = inline
    press(panel)
    drain(panel)
    assert len(runner.calls) == 2


def test_a_job_area_that_cannot_be_built_changes_nothing_and_releases_the_run(make_panel, output_base, tmp_path,
                                                                               monkeypatch):
    panel, runner = previous_partial_run(make_panel, tmp_path, monkeypatch)
    previous = (panel.jobs, panel.run_result, panel._last_run_dir, panel.var_outdir.get(), panel.run_snapshot)
    shown = dialogs(monkeypatch)
    with monkeypatch.context() as patch:
        def broken(*args, **kwargs):
            raise RuntimeError("no job area for this test")
        patch.setattr(job_ui, "JobAdapter", broken)
        press(panel)
        drain(panel)
    assert shown == [("showerror", "Resize not started", "The resize could not be started, so nothing was created.")]
    assert (panel.jobs, panel.run_result, panel._last_run_dir, panel.var_outdir.get(), panel.run_snapshot) == previous
    assert panel.jobs.has_retryable is True and len(runner.calls) == 1
    assert run_folders(output_base) == [run_dir_of(output_base)], "the unused run folder was released"
    assert idle_and_usable(panel)
    panel.retry_failed()  # the previous run's Retry Failed still works
    drain(panel)
    assert len(runner.calls) == 2 and runner.calls[-1]["run_dir"] == run_dir_of(output_base)


def test_a_resize_worker_that_cannot_start_settles_the_run_as_failed(make_panel, output_base, tmp_path, monkeypatch):
    panel, runner = previous_partial_run(make_panel, tmp_path, monkeypatch)

    def no_worker(panel_, params):
        raise RuntimeError("no worker thread for this test")

    panel._job_runner = no_worker
    press(panel)
    drain(panel)
    assert panel.run_result.state is jc.JobState.FAILED
    assert panel.run_result.has_retryable is False
    assert idle_and_usable(panel)
    assert run_folders(output_base) == [run_dir_of(output_base)], "the run that never started left no folder"
    panel._job_runner = runner
    press(panel)
    drain(panel)
    assert len(runner.calls) == 2


def test_the_drain_frees_the_panel_even_when_ending_a_preparation_fails_once(make_panel, output_base, tmp_path,
                                                                             monkeypatch):
    threads = HeldPreparations()
    panel = make_panel(thread_factory=threads, job_runner=InlineRunner())
    import_files(panel, make_image(tmp_path / "a.jpg"))
    press(panel)
    real = panel._end_preparation
    calls = []

    def flaky(*args):
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError("render failed once for this test")
        return real(*args)

    monkeypatch.setattr(panel, "_end_preparation", flaky)
    panel.cancel()
    threads.run()
    drain(panel)
    assert len(calls) == 2 and idle_and_usable(panel) and run_folders(output_base) == []


def test_preferences_changed_after_the_press_do_not_move_the_run(make_panel, output_base, tmp_path, monkeypatch):
    threads = HeldPreparations()
    runner = InlineRunner(defer=True)
    panel = make_panel(thread_factory=threads, job_runner=runner)
    import_files(panel, make_image(tmp_path / "a.jpg"))
    press(panel)
    elsewhere = tmp_path / "Elsewhere"
    root = tmp_path / "fakerepo2"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "launcher.py").write_text("#\n", encoding="utf-8")
    (root / "config.toml").write_text(
        "[project]\n"
        f'version = "{config.DEFAULTS["project.version"]}"\n'
        "[output]\n"
        f'base_directory = "{elsewhere.as_posix()}"\n', encoding="utf-8")
    moved = config.load(config_path=root / "config.toml", settings_data={}, repo_root=root)
    monkeypatch.setattr(config, "get_effective", lambda: moved)
    threads.run()
    drain(panel)
    assert runner.calls and runner.calls[0]["run_dir"] == run_dir_of(output_base)
    assert not elsewhere.exists()


def test_retry_is_refused_while_a_preparation_is_pending(make_panel, output_base, tmp_path, monkeypatch):
    panel, runner = previous_partial_run(make_panel, tmp_path, monkeypatch)
    threads = HeldPreparations()
    panel._thread_factory = threads
    press(panel)
    assert len(threads.held) == 1
    assert panel.retry_failed() is None and len(runner.calls) == 1


# --------------------------------------------------------------------------- #
# 5. The source-side modes are untouched
# --------------------------------------------------------------------------- #


def test_numbered_copies_never_prepare_and_still_write_beside_each_source(make_panel, output_base, tmp_path):
    threads = HeldPreparations()
    panel = make_panel(thread_factory=threads)
    first = make_image(tmp_path / "one" / "cover.jpg")
    second = make_image(tmp_path / "two" / "cover.jpg")
    make_image(tmp_path / "two" / "cover-1.jpg")
    import_files(panel, first, second)
    panel.var_source_side.set(True)
    panel._on_source_side_change()
    press(panel)
    drain(panel)
    assert threads.held == [], "no preparation worker"
    assert run_folders(output_base) == []
    assert sorted(p.name for p in first.parent.iterdir()) == ["cover-1.jpg", "cover.jpg"]
    assert sorted(p.name for p in second.parent.iterdir()) == ["cover-1.jpg", "cover-2.jpg", "cover.jpg"]
    assert panel.run_result.state is jc.JobState.SUCCEEDED


@pytest.mark.parametrize("answer", [False, True])
def test_replacement_is_confirmed_on_tk_and_a_refusal_changes_nothing(make_panel, output_base, tmp_path, answer):
    threads = HeldPreparations()
    runner = InlineRunner()
    panel = make_panel(thread_factory=threads, job_runner=runner)
    image = make_image(tmp_path / "art" / "cover.jpg", size=(300, 500))
    before = sha(image)
    import_files(panel, image)
    asked = arm_replacement(panel, answer=answer)
    where = []
    confirm = panel.confirm_replacement

    def on_which_thread(count):
        where.append(threading.current_thread() is threading.main_thread())
        return confirm(count)

    panel.confirm_replacement = on_which_thread
    press(panel)
    drain(panel)
    assert asked == [1] and where == [True]
    assert threads.held == [] and run_folders(output_base) == []
    if answer:
        assert sha(image) != before and len(runner.calls) == 1
    else:
        assert sha(image) == before and runner.calls == []
        assert sorted(p.name for p in image.parent.iterdir()) == ["cover.jpg"]
    assert idle_and_usable(panel)


# --------------------------------------------------------------------------- #
# 6. The resize worker checks each image against one index
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", ["standard", "numbered"])
def test_the_resize_worker_normalises_each_input_once(make_panel, output_base, tmp_path, monkeypatch, mode):
    """fee286f checked every image against every input again: N·(N+1) input keys (120 images: 14,520)."""
    panel = make_panel()
    paths = [make_image(tmp_path / f"d{i:03d}" / "cover.jpg", size=(20, 20)) for i in range(120)]
    import_files(panel, *paths)
    if mode == "numbered":
        panel.var_source_side.set(True)
        panel._on_source_side_change()
    monkeypatch.setattr(cr, "resize_for_audiobook",
                        lambda src, out, size, letterbox: (Path(out).write_bytes(b"x"), Path(out))[1])
    keys = []
    real = op._input_key
    monkeypatch.setattr(op, "_input_key", lambda path: (keys.append(1), real(path))[1])
    press(panel)
    drain(panel)
    assert panel.run_result.state is jc.JobState.SUCCEEDED and panel.run_result.succeeded_count == 120
    assert len(keys) <= 2 * 120 + 5, len(keys)


@pytest.mark.parametrize("spelling", ["exact", "case"])
def test_an_output_that_is_an_input_is_still_refused_per_image(make_panel, tmp_path, spelling):
    """The index refuses exactly as the one-shot check did: that image fails, the others are written, and the input
    named as a destination is untouched. Driven through the worker body with a destination pointed at an input."""
    panel = make_panel()
    a = make_image(tmp_path / "art" / "a.jpg")
    b = make_image(tmp_path / "art" / "b.jpg")
    before = sha(a)
    target = a if spelling == "exact" else a.with_name("A.JPG")
    out = tmp_path / "run" / "b.jpg"
    panel.resize_worker({"size": 256, "letterbox": False, "mode": cr.MODE_STANDARD, "files": [b, a],
                         "planner": None, "source_planner": None, "item_ids": ("ib", "ia"),
                         "destinations": {"ib": out, "ia": target}})
    lines = []
    while not panel._log_q.empty():
        kind, payload = panel._log_q.get_nowait()
        if kind == "log":
            lines.append(payload)
    text = "".join(lines)
    assert "an output would overwrite one of the files being read" in text
    assert sha(a) == before and sorted(p.name for p in a.parent.iterdir()) == ["a.jpg", "b.jpg"]
    assert out.exists() and Image.open(out).size == (256, 256)


# --------------------------------------------------------------------------- #
# Real mainloop: the press returns at once and the heartbeat keeps beating
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shape,size,cancel", [
    ("direct-same", 2341, False),
    ("folder-unique", 2341, False),
    ("direct-same", 2341, True),
])
def test_the_press_returns_at_once_and_tk_keeps_its_heartbeat_while_the_job_is_prepared(
        make_panel, output_base, tmp_path, tk_root, shape, size, cancel):
    """fee286f planned on Tk: the press was the freeze (figures in the Handoff block). The heartbeat is a real
    ``after`` chain on ``mainloop`` and the panel's own pump adopts the plan. Bounds are generous on purpose
    (Windows' 15.6 ms timer quantum alone makes an idle 20 ms heartbeat's largest gap about 63 ms); the measured
    figures are printed (CP5MEASURE)."""
    blob = (tmp_path / "blob.jpg")
    Image.new("RGB", (8, 8)).save(blob)
    data = blob.read_bytes()

    def put(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    runner = InlineRunner(defer=True)
    if shape == "direct-same":
        chosen = tuple(str(put(tmp_path / "lib" / f"d{i:05d}" / "cover.jpg")) for i in range(size))
        panel = make_panel(job_runner=runner, choose_files=lambda: chosen)
        panel.importer.add_files()
    else:
        for i in range(size):
            put(tmp_path / "lib" / f"Book {i:05d}" / "cover.jpg")
        panel = make_panel(job_runner=runner, choose_folder=lambda: (str(tmp_path / "lib"),))
        panel.importer.add_folder()
        wait_for(lambda: len(panel.manager.snapshot().files) >= size, panel=panel)
    assert len(panel.manager.snapshot().files) == size
    threads = RealThreads()
    panel._thread_factory = threads
    panel.pack(fill="both", expand=True)
    tk_root.update()
    take_the_suites_thread_start_collection()

    gaps: list[tuple[float, float]] = []
    marks: dict = {}
    state = {"last": time.perf_counter(), "after": None, "hard": time.perf_counter() + 180.0}

    def finished() -> bool:
        if cancel:
            return "cancel_returned" in marks and panel._preparing is None
        return bool(runner.calls)

    def beat():
        now = time.perf_counter()
        gaps.append((now, now - state["last"]))
        state["last"] = now
        if "at" in marks and "over" not in marks and finished():
            marks["over"] = now
        if ("over" in marks and now > marks["over"] + 0.2) or now > state["hard"]:
            tk_root.quit()
            return
        state["after"] = tk_root.after(20, beat)

    def press_start():
        marks["at"] = time.perf_counter()
        press(panel)
        marks["returned"] = time.perf_counter()
        marks["status"] = panel.jobs.status.status_text
        marks["cancel"] = panel.jobs.controls.availability()[jc.JobAction.CANCEL]
        marks["start"] = start_enabled(panel)
        if cancel:
            tk_root.after(150, do_cancel)

    def do_cancel():
        marks["cancel_at"] = time.perf_counter()
        panel.cancel()
        marks["cancel_returned"] = time.perf_counter()

    state["after"] = tk_root.after(20, beat)
    tk_root.after(60, press_start)
    tk_root.mainloop()
    for thread in threads.made:
        thread.join(WAIT)
    drain(panel)
    assert "over" in marks, "the preparation never ended"
    window = sorted(gap for at, gap in gaps if marks["at"] <= at <= marks["over"])
    measure = {"shape": shape, "n": size, "cancel": cancel,
               "press_ms": round((marks["returned"] - marks["at"]) * 1000, 2),
               "press_to_end_s": round(marks["over"] - marks["at"], 3), "beats": len(window),
               "max_gap_ms": round(window[-1] * 1000, 1),
               "p95_gap_ms": round(window[min(len(window) - 1, int(0.95 * len(window)))] * 1000, 1)}
    if cancel:
        measure["cancel_callback_ms"] = round((marks["cancel_returned"] - marks["cancel_at"]) * 1000, 2)
        measure["cancel_to_idle_s"] = round(marks["over"] - marks["cancel_at"], 3)
    print("CP5MEASURE " + json.dumps(measure))
    assert marks["returned"] - marks["at"] < 0.5, measure
    assert marks["status"] == cr.STATUS_PREPARING and marks["cancel"] is True and marks["start"] is False
    assert window[-1] < 0.5, measure
    if cancel:
        assert runner.calls == [] and run_folders(output_base) == []
        assert measure["cancel_callback_ms"] < 100, measure
        assert idle_and_usable(panel)
    else:
        assert len(runner.calls) == 1 and len(runner.calls[0]["destinations"]) == size
    assert [t.name for t in threads.made][:1] == ["cover-prepare-1"]
