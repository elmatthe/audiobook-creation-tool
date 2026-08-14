"""Cover's adoption of the shared job-control foundation — v0.6.1 Plan 4, Phase 4.

Phase 2 gave Cover the shared importer and Phase 3 the three browser views. This
phase moves the *run* itself onto Plan 3's ``JobController`` and ``JobAdapter``
and Plan 2's output planning, without loosening a single clause of the
destructive contract that governs this panel.

What these tests prove, in the order the phase contract states it:

1. one run is frozen once, and nothing later can reach inside it;
2. standard output is planned through ``planning_groups`` and the three
   Plan 2 planners, and stays inside the reserved run;
3. numbered copies still write ``stem-1.ext`` beside each source;
4. replacement still needs all four gates and is still atomic;
5. the retry control is built from ``RunResult.retry()`` and nothing else;
6. pause, resume and cancel take effect only at a boundary between images;
7. Summary, Details, progress and the estimate come from the shared adapter;
8. there is still exactly one pump, and closing leaves nothing behind.

Determinism
-----------
**No test sleeps.** The worker runs inline through an injected runner in every
test that is not specifically about threading. The few that are use a real
thread and wait only on real signals — a :class:`threading.Event` the worker
sets, a :class:`queue.Queue` the run publishes to, or a bounded ``join`` — so a
run that never reaches the expected state fails loudly instead of hanging.
Clocks are injected and tick by a fixed amount.

Safety
------
Every image is generated into ``tmp_path``. No repository media, no user media,
no real output base, no real settings file and no dialog. The replacement
confirmation is answered through the panel's own seam, never by opening a modal.
"""

from __future__ import annotations

import ast
import hashlib
import queue
import threading
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")
tk = pytest.importorskip("tkinter")

from shared import config  # noqa: E402
from shared import image_capabilities as caps  # noqa: E402
from shared import job_control as jc  # noqa: E402
from shared import output_paths as op  # noqa: E402
from shared import settings as app_settings  # noqa: E402
from shared.importing import planning_groups  # noqa: E402

from mp3_tools import cover_resizer as cr  # noqa: E402

from test_import_coordination import RecordingThreads  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PANEL_SOURCE = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "cover_resizer.py"

#: Every wait here is bounded so a deadlock fails rather than hangs.
WAIT = 5.0

#: The genuine resize function, captured before any test can patch over it.
REAL_RESIZE = cr.resize_for_audiobook


# --------------------------------------------------------------------------- #
# Fixtures and helpers
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
    caps.reset_cache()
    yield
    caps.reset_cache()


@pytest.fixture()
def output_base(tmp_path, monkeypatch):
    """An in-memory configuration whose output base is under ``tmp_path``."""
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    base = tmp_path / "OutputBase"
    root = tmp_path / "fakerepo"
    (root / "scripts" / "Universal").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "Universal" / "launcher.py").write_text("#\n", encoding="utf-8")
    (root / "config.toml").write_text(
        "[project]\n"
        f'version = "{config.DEFAULTS["project.version"]}"\n'
        "[output]\n"
        f'base_directory = "{base.as_posix()}"\n',
        encoding="utf-8",
    )
    snapshot = config.load(config_path=root / "config.toml", settings_data={}, repo_root=root)
    monkeypatch.setattr(config, "get_effective", lambda: snapshot)
    config.invalidate()
    try:
        yield base
    finally:
        app_settings.use_path(None)
        config.invalidate()


class InlineRunner:
    """The job runner seam. Runs the worker body on the calling thread.

    ``defer=True`` keeps the parameters instead, so a test can start a run, look
    at the world before any image is touched, and then release the worker — with
    no thread, no sleep and no timing assumption anywhere.
    """

    def __init__(self, defer: bool = False):
        self.defer = defer
        self.calls: list[dict] = []
        self.panels: list = []

    def __call__(self, panel, params):
        self.panels.append(panel)
        self.calls.append(params)
        if not self.defer:
            panel.resize_worker(params)
        return None

    def release(self, index: int = -1) -> None:
        self.panels[index].resize_worker(self.calls[index])


class ThreadRunner:
    """A real, joinable, non-daemon worker, for the pause and cancel races only."""

    def __init__(self):
        self.threads: list[threading.Thread] = []

    def __call__(self, panel, params):
        worker = threading.Thread(
            target=panel.resize_worker, args=(params,), name="cover-resize-test")
        worker.start()
        self.threads.append(worker)
        return worker

    def join(self) -> None:
        for worker in self.threads:
            worker.join(WAIT)
            assert not worker.is_alive(), "a worker outlived its bounded join"


class Gate:
    """A per-image barrier around the real resize. Signals only, never a sleep."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.seen: list[str] = []

    def __call__(self, in_path, out_path, size, letterbox):
        self.seen.append(Path(in_path).name)
        self.entered.set()
        assert self.release.wait(WAIT), "the gate was never released"
        self.release.clear()
        self.entered.clear()
        return REAL_RESIZE(in_path, out_path, size=size, letterbox=letterbox)

    def let_through(self) -> None:
        """Release exactly the image now waiting."""
        assert self.entered.wait(WAIT), "no image ever reached the gate"
        self.release.set()


def no_previews(requests, publish):
    """The browser's decoder seam, stubbed: this file is not about previews."""
    return None


def _counter():
    """A monotonic injected clock. One fixed tick per read, so timing is exact."""
    state = {"t": 0.0}

    def clock() -> float:
        state["t"] += 1.0
        return state["t"]

    return clock


@pytest.fixture()
def make_panel(tk_root, output_base):
    made: list[cr.CoverResizerUI] = []

    def build(**kwargs):
        kwargs.setdefault("clock", _counter())
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        kwargs.setdefault("preview_runner", no_previews)
        kwargs.setdefault("job_runner", InlineRunner())
        panel = cr.CoverResizerUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


def make_image(path: Path, size=(200, 400), colour=(200, 30, 30)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_files(panel, *paths: Path) -> tuple[str, ...]:
    """Add files through the real shared direct-file path, never past it."""
    panel.importer._choose_files = lambda: tuple(str(p) for p in paths)
    panel.importer.add_files()
    return panel.manager.snapshot().occurrence_ids


def import_folder(panel, root: Path) -> tuple[str, ...]:
    panel.importer._choose_folder = lambda: (str(root),)
    panel.importer.add_folder()
    panel._pump.tick()
    return panel.manager.snapshot().occurrence_ids


def drain(panel, times: int = 3) -> None:
    """Tick the one pump. Draining is idempotent, so extra ticks cost nothing."""
    for _ in range(times):
        panel._pump.tick()


def start(panel, *, size: int = 64) -> None:
    panel.var_size.set(size)
    panel.start_resize()
    drain(panel)


def wait_for_state(panel, state) -> None:
    """Block on the run's own event queue until the controller reports *state*.

    A real signal, not a poll: ``Queue.get`` waits on a condition variable, so
    nothing here sleeps, and a run that never reaches the state fails on the
    bounded timeout instead of hanging the suite. Every event taken is put back
    in the order it arrived — the pump only drains when a test ticks it, so this
    queue is exclusively ours for the duration.
    """
    held = []
    while True:
        event = panel._event_q.get(timeout=WAIT)
        held.append(event)
        if getattr(event, "state", None) is state:
            break
    for event in held:
        panel._event_q.put(event)


def run_dir_of(output_base: Path, number: int = 1) -> Path:
    return output_base / "Cover-Image-Outputs" / f"Cover-Image-{number}"


def written_under(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def panel_tree() -> ast.Module:
    return ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"), filename=str(PANEL_SOURCE))


def method_named(name: str, *, owner: str = "CoverResizerUI") -> ast.AST:
    for node in panel_tree().body:
        if isinstance(node, ast.ClassDef) and node.name == owner:
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == name:
                    return member
    raise AssertionError(f"{owner}.{name} is not defined in cover_resizer.py")


def summary_text(panel) -> str:
    return "\n".join(panel.jobs.views.summary)


def details_text(panel) -> str:
    return "\n".join(panel.jobs.views.details)


def fail_named(monkeypatch, *names: str) -> None:
    """Make exactly the listed filenames fail, and let everything else through."""
    wanted = set(names)

    def selective(in_path, out_path, size, letterbox):
        if Path(in_path).name in wanted:
            raise OSError(f"refused {Path(in_path).name}")
        return REAL_RESIZE(in_path, out_path, size=size, letterbox=letterbox)

    monkeypatch.setattr(cr, "resize_for_audiobook", selective)


def arm_replacement(panel, *, answer: bool = True) -> list[int]:
    """Open the first three gates and record every confirmation asked for."""
    panel.var_source_side.set(True)
    panel._on_source_side_change()
    panel.var_source_action.set(cr.ACTION_REPLACE)
    asked: list[int] = []

    def confirm(count: int) -> bool:
        asked.append(count)
        return answer

    panel.confirm_replacement = confirm
    return asked


def capture_dialog(monkeypatch, name: str) -> list:
    """Record a messagebox call instead of opening it."""
    from tkinter import messagebox

    seen: list = []
    monkeypatch.setattr(messagebox, name, lambda *a, **k: seen.append(a))
    return seen


# --------------------------------------------------------------------------- #
# 1. The frozen run
# --------------------------------------------------------------------------- #


def test_a_run_captures_the_manager_snapshot_and_its_occurrence_ids(make_panel, tmp_path):
    sources = [make_image(tmp_path / "art" / "a.jpg"),
               make_image(tmp_path / "art" / "b.jpg")]
    panel = make_panel(job_runner=InlineRunner(defer=True))
    ids = import_files(panel, *sources)

    start(panel)

    snapshot = panel.run_snapshot
    assert isinstance(snapshot, jc.RunSnapshot)
    assert snapshot.item_ids == ids
    assert [entry.path for entry in snapshot.files.files] == sources


def test_every_output_affecting_setting_is_frozen_onto_the_run(make_panel, tmp_path):
    source = make_image(tmp_path / "art" / "a.jpg")
    panel = make_panel(job_runner=InlineRunner(defer=True))
    import_files(panel, source)
    panel.var_letterbox.set(False)

    start(panel, size=128)

    options = panel.run_snapshot.tool_options
    assert options["size"] == 128
    assert options["letterbox"] is False
    assert options["mode"] == cr.MODE_STANDARD
    assert jc.is_frozen_options(options), "the run's options must be a frozen mapping"


def test_a_later_ui_change_cannot_reach_a_run_that_already_started(
    make_panel, output_base, tmp_path
):
    source = make_image(tmp_path / "art" / "a.jpg")
    runner = InlineRunner(defer=True)
    panel = make_panel(job_runner=runner)
    import_files(panel, source)
    start(panel, size=64)

    panel.var_size.set(2048)
    panel.var_letterbox.set(False)
    runner.release()
    drain(panel)

    assert panel.run_snapshot.tool_options["size"] == 64
    with Image.open(run_dir_of(output_base) / "a.jpg") as img:
        assert img.size == (64, 64), "the run used the size it froze"


def test_a_later_import_cannot_change_the_items_of_a_running_job(make_panel, tmp_path):
    first = make_image(tmp_path / "art" / "a.jpg")
    later = make_image(tmp_path / "art" / "b.jpg")
    runner = InlineRunner(defer=True)
    panel = make_panel(job_runner=runner)
    import_files(panel, first)
    start(panel)

    import_files(panel, later)
    assert panel.manager.count == 2
    assert panel.run_snapshot.count == 1, "the frozen run kept its own list"
    assert len(runner.calls[0]["files"]) == 1


def test_deliberate_duplicates_stay_two_occurrences_through_a_run(
    make_panel, output_base, tmp_path
):
    source = make_image(tmp_path / "art" / "cover.jpg")
    panel = make_panel()
    panel.importer.options.set_allow_duplicates(True)
    import_files(panel, source)
    ids = import_files(panel, source)
    assert len(ids) == 2 and ids[0] != ids[1]

    start(panel)

    result = panel.run_result
    assert result.snapshot.item_ids == ids
    assert result.succeeded_count == 2
    assert len(set(panel.destinations().values())) == 2, "two occurrences, two outputs"


def test_the_run_id_is_the_frozen_snapshot_id(make_panel, tmp_path):
    source = make_image(tmp_path / "art" / "a.jpg")
    panel = make_panel(job_runner=InlineRunner(defer=True))
    import_files(panel, source)
    start(panel)
    assert panel.jobs.run_id == panel.run_snapshot.snapshot_id


def test_a_second_start_is_refused_while_a_run_is_active(make_panel, tmp_path):
    source = make_image(tmp_path / "art" / "a.jpg")
    runner = InlineRunner(defer=True)
    panel = make_panel(job_runner=runner)
    import_files(panel, source)
    start(panel)
    first = panel.run_snapshot

    panel.start_resize()

    assert panel.run_snapshot is first
    assert len(runner.calls) == 1


# --------------------------------------------------------------------------- #
# 2. Standard output
# --------------------------------------------------------------------------- #


def test_validation_completes_before_any_run_directory_is_reserved(
    make_panel, output_base, monkeypatch
):
    panel = make_panel()
    warned = capture_dialog(monkeypatch, "showwarning")

    panel.start_resize()

    assert warned, "the empty-list warning still comes first"
    assert not output_base.exists(), "nothing was reserved for a run that never began"


def test_a_bad_target_size_reserves_nothing(make_panel, output_base, tmp_path, monkeypatch):
    source = make_image(tmp_path / "art" / "a.jpg")
    panel = make_panel()
    import_files(panel, source)
    panel.var_size.set(-5)
    errors = capture_dialog(monkeypatch, "showerror")

    panel.start_resize()

    assert errors
    assert not output_base.exists()
    assert panel.run_snapshot is None


def test_standard_mode_reserves_exactly_one_numbered_run(make_panel, output_base, tmp_path):
    panel = make_panel()
    import_files(panel,
                 make_image(tmp_path / "art" / "a.jpg"),
                 make_image(tmp_path / "art" / "b.jpg"))

    start(panel)

    parent = output_base / "Cover-Image-Outputs"
    assert sorted(p.name for p in parent.iterdir()) == ["Cover-Image-1"]


def test_every_standard_output_lands_inside_the_reserved_run(
    make_panel, output_base, tmp_path
):
    panel = make_panel()
    import_files(panel,
                 make_image(tmp_path / "one" / "a.jpg"),
                 make_image(tmp_path / "two" / "b.jpg"))

    start(panel)

    run_dir = run_dir_of(output_base)
    assert written_under(run_dir) == ["a.jpg", "b.jpg"]
    for destination in panel.destinations().values():
        assert run_dir in destination.parents


def test_individually_added_files_are_planned_flat(make_panel, output_base, tmp_path):
    """Decision 31A: a chosen file has no tree to reproduce."""
    panel = make_panel()
    import_files(panel,
                 make_image(tmp_path / "one" / "cover.jpg"),
                 make_image(tmp_path / "two" / "cover.jpg"))

    start(panel)

    assert written_under(run_dir_of(output_base)) == ["cover-1.jpg", "cover.jpg"]


def test_one_imported_folder_is_planned_mirrored(make_panel, output_base, tmp_path):
    """Decision 7A: a folder root reproduces its relative parents."""
    root = tmp_path / "Covers"
    make_image(root / "Series A" / "ch1.jpg")
    make_image(root / "Series B" / "ch1.jpg")
    make_image(root / "flat.jpg")
    panel = make_panel()
    import_folder(panel, root)

    start(panel)

    assert written_under(run_dir_of(output_base)) == [
        "Series A/ch1.jpg", "Series B/ch1.jpg", "flat.jpg"]


def test_two_imported_folders_are_planned_multi_root(make_panel, output_base, tmp_path):
    """Decision 41A: one collision-safe container per root."""
    first = tmp_path / "A" / "Covers"
    second = tmp_path / "B" / "Covers"
    make_image(first / "ch1.jpg")
    make_image(second / "ch1.jpg")
    panel = make_panel()
    import_folder(panel, first)
    import_folder(panel, second)

    start(panel)

    assert written_under(run_dir_of(output_base)) == ["Covers-1/ch1.jpg", "Covers/ch1.jpg"]


def test_mixed_direct_and_folder_files_keep_their_own_provenance(
    make_panel, output_base, tmp_path
):
    root = tmp_path / "Covers"
    make_image(root / "Series A" / "ch1.jpg")
    loose = make_image(tmp_path / "loose" / "ch1.jpg")
    panel = make_panel()
    import_folder(panel, root)
    import_files(panel, loose)

    start(panel)

    assert written_under(run_dir_of(output_base)) == ["Series A/ch1.jpg", "ch1.jpg"], (
        "the folder file mirrors and the chosen file stays flat")


def test_planning_goes_through_planning_groups_and_the_plan2_services():
    """The bridge is the shared one; nothing here regroups paths by hand."""
    tree = panel_tree()
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    bare = {node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    named = called | bare
    for service in ("planning_groups", "plan_flat", "plan_mirrored", "plan_multi_root"):
        assert service in named, service
    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for service in ("planning_groups", "plan_flat", "plan_mirrored", "plan_multi_root",
                    "reserve_run_directory", "SourceSidePlanner", "DestinationPlanner"):
        assert service not in defined, f"{service} must be consumed, never redefined"


def test_plan_destinations_covers_every_occurrence_of_the_shared_grouping(
    make_panel, tmp_path
):
    root = tmp_path / "Covers"
    make_image(root / "Sub" / "a.jpg")
    loose = make_image(tmp_path / "loose" / "b.png")
    panel = make_panel()
    import_folder(panel, root)
    import_files(panel, loose)

    snapshot = panel.manager.snapshot()
    groups = planning_groups(snapshot)
    mapping = cr.plan_destinations(snapshot, tmp_path / "run")

    assert set(mapping) == set(snapshot.occurrence_ids)
    assert len(groups.direct) == 1 and len(groups.grouped) == 1
    assert mapping[snapshot.occurrence_ids[0]].as_posix().endswith("run/Sub/a.jpg")
    assert mapping[snapshot.occurrence_ids[1]].as_posix().endswith("run/b.png")


def test_a_destination_is_planned_under_the_name_it_will_be_written_as():
    """``resize_for_audiobook`` writes ``.jpg`` for anything it cannot encode."""
    assert cr.written_name(Path("/x/art.webp")) == "art.jpg"
    assert cr.written_name(Path("/x/art.PNG")) == "art.png"
    assert cr.written_name(Path("/x/art.heic")) == "art.heic"


def test_a_planned_destination_never_collides_with_an_input(
    make_panel, output_base, tmp_path
):
    source = make_image(tmp_path / "art" / "a.jpg")
    panel = make_panel()
    import_files(panel, source)
    before = sha(source)

    start(panel)

    assert sha(source) == before, "an input is never a destination"
    assert source not in set(panel.destinations().values())


def test_a_heic_input_is_planned_as_a_heic_output_never_a_jpg(
    make_panel, output_base, tmp_path
):
    """Decision 3A: no silent format substitution, in any mode."""
    caps.reset_cache()
    caps.heif_capability(probe=lambda: caps.FormatCapability(
        "heif", caps.HEIF_SUFFIXES, True, False, "no encoder in this build"))
    source = tmp_path / "art" / "cover.heic"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"not really a heic")

    panel = make_panel()
    ids = import_files(panel, source)
    assert ids, "a decode-capable machine may import a heic"

    start(panel)

    assert panel.destinations()[ids[0]].suffix == ".heic"
    assert list(run_dir_of(output_base).rglob("*.jpg")) == [], "no silent substitution"
    assert panel.run_result.failed_count == 1, "it failed truthfully instead"


# --------------------------------------------------------------------------- #
# 3. Numbered copies beside the source
# --------------------------------------------------------------------------- #


def test_source_side_mode_is_off_and_numbered_copies_are_preselected(make_panel):
    panel = make_panel()
    assert panel.var_source_side.get() is False
    assert panel.var_source_action.get() == cr.ACTION_NUMBERED
    assert panel.effective_mode() == cr.MODE_STANDARD


def test_turning_source_side_off_resets_the_action_to_numbered_copies(make_panel):
    panel = make_panel()
    panel.var_source_side.set(True)
    panel._on_source_side_change()
    panel.var_source_action.set(cr.ACTION_REPLACE)
    assert panel.effective_mode() == cr.ACTION_REPLACE

    panel.var_source_side.set(False)
    panel._on_source_side_change()

    assert panel.var_source_action.get() == cr.ACTION_NUMBERED
    assert panel.effective_mode() == cr.MODE_STANDARD


def test_numbered_copies_write_beside_the_source_and_never_its_own_name(
    make_panel, output_base, tmp_path
):
    source = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(source)
    panel = make_panel()
    import_files(panel, source)
    panel.var_source_side.set(True)
    panel._on_source_side_change()

    start(panel)

    assert sorted(p.name for p in source.parent.iterdir()) == ["cover-1.jpg", "cover.jpg"]
    assert sha(source) == before
    assert not output_base.exists(), "an exception mode reserves no standard run"


def test_numbered_copies_advance_past_existing_numbers(make_panel, tmp_path):
    source = make_image(tmp_path / "art" / "cover.jpg")
    make_image(tmp_path / "art" / "cover-1.jpg")
    panel = make_panel()
    import_files(panel, source)
    panel.var_source_side.set(True)
    panel._on_source_side_change()

    start(panel)

    assert (tmp_path / "art" / "cover-2.jpg").exists()


def test_numbered_mode_uses_the_shared_source_side_planner():
    """The one place a source-side plan is made, and it is Plan 2's."""
    body = ast.unparse(method_named("_launch"))
    assert "output_paths.SourceSidePlanner()" in body
    assert PANEL_SOURCE.read_text(encoding="utf-8").count("SourceSidePlanner(") == 1


def test_two_duplicate_occurrences_get_two_numbered_copies(make_panel, tmp_path):
    source = make_image(tmp_path / "art" / "cover.jpg")
    panel = make_panel()
    panel.importer.options.set_allow_duplicates(True)
    import_files(panel, source)
    import_files(panel, source)
    panel.var_source_side.set(True)
    panel._on_source_side_change()

    start(panel)

    assert sorted(p.name for p in source.parent.iterdir()) == [
        "cover-1.jpg", "cover-2.jpg", "cover.jpg"]


# --------------------------------------------------------------------------- #
# 4. Replacement — the destructive contract (§4.2)
# --------------------------------------------------------------------------- #


def test_replacement_needs_the_toggle_as_well_as_the_radio(make_panel, tmp_path):
    source = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(source)
    panel = make_panel()
    import_files(panel, source)
    asked = arm_replacement(panel)
    panel.var_source_side.set(False)          # the toggle closes again
    panel._on_source_side_change()

    start(panel)

    assert asked == [], "no confirmation is even asked without the toggle"
    assert sha(source) == before


def test_a_confirmed_replacement_asks_once_and_replaces_atomically(make_panel, tmp_path):
    source = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(source)
    panel = make_panel()
    import_files(panel, source)
    asked = arm_replacement(panel)

    start(panel)

    assert asked == [1], "exactly one confirmation, for the validated count"
    assert sha(source) != before
    with Image.open(source) as img:
        assert img.size == (64, 64)
    strays = [p.name for p in source.parent.iterdir()
              if p.name.startswith(op.TEMP_SIBLING_PREFIX)]
    assert strays == []


def test_a_declined_confirmation_creates_no_run_no_temporary_and_no_output(
    make_panel, output_base, tmp_path
):
    source = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(source)
    panel = make_panel()
    import_files(panel, source)
    asked = arm_replacement(panel, answer=False)

    start(panel)

    assert asked == [1]
    assert sha(source) == before
    assert sorted(p.name for p in source.parent.iterdir()) == ["cover.jpg"]
    assert not output_base.exists()
    assert panel.run_snapshot is None, "a declined run was never accepted"
    assert panel._busy.is_set() is False


def test_every_source_is_validated_before_the_dialog(make_panel, tmp_path, monkeypatch):
    """One unreplaceable source stops the whole run before anything is asked."""
    good = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(good)
    gone = make_image(tmp_path / "art" / "vanished.jpg")
    panel = make_panel()
    import_files(panel, good, gone)
    gone.unlink()                       # imported, then removed behind our back
    asked = arm_replacement(panel)
    errors = capture_dialog(monkeypatch, "showerror")

    start(panel)

    assert asked == [], "the dialog is never reached with an unreplaceable source"
    assert errors, "the refusal is reported instead"
    assert sha(good) == before, "the replaceable source was not touched either"
    assert panel.run_snapshot is None


def test_a_format_written_as_jpg_can_never_be_replaced_under_its_own_name(
    make_panel, tmp_path
):
    """The suffix gate, checked directly: a .webp is written as .jpg."""
    source = tmp_path / "art" / "cover.webp"
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 40), (1, 2, 3)).save(source)
    panel = make_panel()

    with pytest.raises(op.UnsafePathError) as excinfo:
        panel._validated_replacement_sources([source])

    assert "numbered copies" in excinfo.value.message


def test_the_replacement_gate_is_reached_from_exactly_one_place():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert source.count("self.confirm_replacement(") == 1, (
        "one gate, called from one helper that both a run and a retry go through")
    assert source.count("_validated_replacement_sources(") == 2, (
        "defined once, called once, from that same helper")


def test_replacement_writes_a_validated_temporary_before_one_atomic_install():
    worker = ast.unparse(method_named("resize_worker"))
    assert worker.index("temporary_sibling") < worker.index("atomic_replace")
    for banned in ("unlink", "os.remove", "shutil.move", "rename("):
        assert banned not in worker, banned


def test_a_failed_replacement_leaves_the_original_untouched(
    make_panel, tmp_path, monkeypatch
):
    source = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(source)
    panel = make_panel()
    import_files(panel, source)
    arm_replacement(panel)
    fail_named(monkeypatch, "cover.jpg")

    start(panel)

    assert sha(source) == before
    strays = [p.name for p in source.parent.iterdir()
              if p.name.startswith(op.TEMP_SIBLING_PREFIX)]
    assert strays == []
    assert panel.run_result.failed_count == 1


def test_a_completed_replacement_survives_a_later_failure_and_is_reported(
    make_panel, tmp_path, monkeypatch
):
    first = make_image(tmp_path / "art" / "a.jpg")
    second = make_image(tmp_path / "art" / "b.jpg")
    second_before = sha(second)
    panel = make_panel()
    import_files(panel, first, second)
    arm_replacement(panel)
    fail_named(monkeypatch, "b.jpg")

    start(panel)

    with Image.open(first) as img:
        assert img.size == (64, 64)
    assert sha(second) == second_before
    result = panel.run_result
    assert result.succeeded_count == 1 and result.failed_count == 1
    assert result.state is jc.JobState.COMPLETED_WITH_FAILURES


def test_a_truncated_write_never_reaches_the_original(make_panel, tmp_path, monkeypatch):
    source = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(source)
    panel = make_panel()
    import_files(panel, source)
    arm_replacement(panel)

    def half_written(in_path, out_path, size, letterbox):
        Path(out_path).write_bytes(b"truncated")
        return Path(out_path)

    monkeypatch.setattr(cr, "resize_for_audiobook", half_written)
    start(panel)

    assert sha(source) == before
    strays = [p.name for p in source.parent.iterdir()
              if p.name.startswith(op.TEMP_SIBLING_PREFIX)]
    assert strays == [], "the operation's own temporary is always removed"
    assert panel.run_result.failed_count == 1


def test_no_suppression_path_was_introduced_around_the_confirmation():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    names = set()
    for node in ast.walk(panel_tree()):
        if isinstance(node, ast.Name):
            names.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value.lower())
    for forbidden in ("dont_ask", "do_not_ask", "suppress_confirm", "skip_confirm",
                      "remember_choice", "confirmed_once", "already_confirmed"):
        assert not any(forbidden in name for name in names), forbidden
    assert "REPLACEMENT_TITLE" in source


# --------------------------------------------------------------------------- #
# 5. The retry control
# --------------------------------------------------------------------------- #


def test_the_retry_control_appears_only_after_a_retryable_failure(
    make_panel, output_base, tmp_path, monkeypatch
):
    panel = make_panel()
    import_files(panel,
                 make_image(tmp_path / "art" / "a.jpg"),
                 make_image(tmp_path / "art" / "b.jpg"))
    fail_named(monkeypatch, "b.jpg")

    start(panel)

    assert panel.jobs.has_retryable is True
    assert panel.jobs.controls.availability()[jc.JobAction.RETRY_FAILED] is True


def test_a_run_with_no_failure_offers_no_retry(make_panel, output_base, tmp_path):
    panel = make_panel()
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))

    start(panel)

    assert panel.run_result.state is jc.JobState.SUCCEEDED
    assert panel.jobs.has_retryable is False
    assert panel.jobs.controls.availability()[jc.JobAction.RETRY_FAILED] is False


def test_a_retry_runs_only_the_failed_items_against_the_original_snapshot(
    make_panel, output_base, tmp_path, monkeypatch
):
    runner = InlineRunner()
    panel = make_panel(job_runner=runner)
    ids = import_files(panel,
                       make_image(tmp_path / "art" / "a.jpg"),
                       make_image(tmp_path / "art" / "b.jpg"))
    fail_named(monkeypatch, "b.jpg")
    start(panel)
    original = panel.run_snapshot

    monkeypatch.undo()
    panel.retry_failed()
    drain(panel)

    assert panel.run_snapshot is original, "the retry re-used the exact original run"
    assert runner.calls[-1]["item_ids"] == (ids[1],)
    assert [p.name for p in runner.calls[-1]["files"]] == ["b.jpg"]
    assert panel.run_result.succeeded_count == 1


def test_a_successful_item_is_never_offered_for_retry(
    make_panel, output_base, tmp_path, monkeypatch
):
    panel = make_panel()
    ids = import_files(panel,
                       make_image(tmp_path / "art" / "a.jpg"),
                       make_image(tmp_path / "art" / "b.jpg"))
    fail_named(monkeypatch, "b.jpg")

    start(panel)

    request = panel.run_result.retry()
    assert request.item_ids == (ids[1],)
    assert ids[0] not in request.item_ids


def test_a_retried_standard_item_lands_where_it_would_originally_have_landed(
    make_panel, output_base, tmp_path, monkeypatch
):
    panel = make_panel()
    ids = import_files(panel,
                       make_image(tmp_path / "one" / "cover.jpg"),
                       make_image(tmp_path / "two" / "cover.jpg"))
    fail_named(monkeypatch, "cover.jpg")             # both fail
    start(panel)
    planned = dict(panel.destinations())
    assert panel.run_result.failed_count == 2

    monkeypatch.undo()
    panel.retry_failed()
    drain(panel)

    run_dir = run_dir_of(output_base)
    assert written_under(run_dir) == ["cover-1.jpg", "cover.jpg"]
    assert planned[ids[0]] == run_dir / "cover.jpg"
    assert planned[ids[1]] == run_dir / "cover-1.jpg"
    assert panel.destinations() == planned, "a retry re-uses the original plan"


def test_a_retry_cannot_overwrite_an_earlier_success(
    make_panel, output_base, tmp_path, monkeypatch
):
    make_image(tmp_path / "one" / "cover.jpg", colour=(10, 200, 10))
    make_image(tmp_path / "two" / "cover.jpg", colour=(10, 10, 200))
    panel = make_panel()
    import_files(panel, tmp_path / "one" / "cover.jpg", tmp_path / "two" / "cover.jpg")

    calls = {"n": 0}

    def second_fails(in_path, out_path, size, letterbox):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("refused the second")
        return REAL_RESIZE(in_path, out_path, size=size, letterbox=letterbox)

    monkeypatch.setattr(cr, "resize_for_audiobook", second_fails)
    start(panel)
    run_dir = run_dir_of(output_base)
    survivor = sha(run_dir / "cover.jpg")

    monkeypatch.undo()
    panel.retry_failed()
    drain(panel)

    assert sha(run_dir / "cover.jpg") == survivor, "the earlier success is untouched"
    assert (run_dir / "cover-1.jpg").exists()


def test_two_duplicate_occurrences_cannot_collapse_into_one_retry_item(
    make_panel, output_base, tmp_path, monkeypatch
):
    source = make_image(tmp_path / "art" / "cover.jpg")
    panel = make_panel()
    panel.importer.options.set_allow_duplicates(True)
    import_files(panel, source)
    ids = import_files(panel, source)
    fail_named(monkeypatch, "cover.jpg")

    start(panel)

    request = panel.run_result.retry()
    assert request.item_ids == ids, "two occurrences, two retry items"
    assert request.count == 2


def test_a_retried_numbered_copy_keeps_its_source_side_provenance(
    make_panel, tmp_path, monkeypatch
):
    source = make_image(tmp_path / "art" / "cover.jpg")
    panel = make_panel()
    import_files(panel, source)
    panel.var_source_side.set(True)
    panel._on_source_side_change()
    fail_named(monkeypatch, "cover.jpg")
    start(panel)
    assert sorted(p.name for p in source.parent.iterdir()) == ["cover.jpg"]

    monkeypatch.undo()
    panel.retry_failed()
    drain(panel)

    assert sorted(p.name for p in source.parent.iterdir()) == ["cover-1.jpg", "cover.jpg"]
    assert panel.run_snapshot.tool_options["mode"] == cr.ACTION_NUMBERED


def test_a_retried_replacement_revalidates_and_asks_again(
    make_panel, tmp_path, monkeypatch
):
    source = make_image(tmp_path / "art" / "cover.jpg")
    panel = make_panel()
    import_files(panel, source)
    asked = arm_replacement(panel)
    fail_named(monkeypatch, "cover.jpg")

    start(panel)
    assert asked == [1]
    assert panel.run_result.failed_count == 1

    monkeypatch.undo()
    panel.retry_failed()
    drain(panel)

    assert asked == [1, 1], "the retry asked for its own confirmation"
    with Image.open(source) as img:
        assert img.size == (64, 64)


def test_a_declined_retry_confirmation_creates_no_artifact(
    make_panel, tmp_path, monkeypatch
):
    source = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(source)
    panel = make_panel()
    import_files(panel, source)
    answers = [True, False]
    asked: list[int] = []
    panel.var_source_side.set(True)
    panel._on_source_side_change()
    panel.var_source_action.set(cr.ACTION_REPLACE)

    def confirm(count: int) -> bool:
        asked.append(count)
        return answers.pop(0)

    panel.confirm_replacement = confirm
    fail_named(monkeypatch, "cover.jpg")
    start(panel)
    assert sha(source) == before
    result_before = panel.run_result

    monkeypatch.undo()
    panel.retry_failed()
    drain(panel)

    assert asked == [1, 1]
    assert sha(source) == before, "a declined retry changed nothing"
    assert sorted(p.name for p in source.parent.iterdir()) == ["cover.jpg"]
    assert panel.run_result is result_before, "no new run was accepted"


def test_the_retry_is_built_only_from_the_shared_run_result():
    body = ast.unparse(method_named("retry_failed"))
    assert ".retry(" in body, "the retry comes from RunResult.retry and nothing else"
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    for invented in ("_failed_list", "failed_paths", "_retry_queue", "RetryRequest("):
        assert invented not in source, invented


def test_no_widget_private_failure_list_competes_with_the_result():
    """Failures live in the shared FailureLog, reachable only through the result."""
    assigned = {
        target.attr
        for node in ast.walk(panel_tree())
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
    }
    for rival in ("failures", "failed", "errors", "retry_items"):
        assert rival not in assigned, rival


def test_the_retry_button_invokes_the_panels_retry(make_panel, output_base, tmp_path,
                                                   monkeypatch):
    panel = make_panel()
    import_files(panel,
                 make_image(tmp_path / "art" / "a.jpg"),
                 make_image(tmp_path / "art" / "b.jpg"))
    fail_named(monkeypatch, "b.jpg")
    start(panel)

    monkeypatch.undo()
    assert panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED) is True
    drain(panel)

    assert panel.run_result.succeeded_count == 1
    assert (run_dir_of(output_base) / "b.jpg").exists()


# --------------------------------------------------------------------------- #
# 6. Pause, resume and cancel
# --------------------------------------------------------------------------- #


def test_pause_takes_effect_only_at_the_boundary_between_images(
    make_panel, output_base, tmp_path, monkeypatch
):
    runner = ThreadRunner()
    panel = make_panel(job_runner=runner)
    import_files(panel,
                 make_image(tmp_path / "art" / "a.jpg"),
                 make_image(tmp_path / "art" / "b.jpg"))
    gate = Gate()
    monkeypatch.setattr(cr, "resize_for_audiobook", gate)

    start(panel)
    assert gate.entered.wait(WAIT), "the first image never started"

    panel.pause()
    assert panel.job_controller.state is jc.JobState.PAUSE_REQUESTED, (
        "an indivisible stage keeps running; only the request is recorded")

    gate.release.set()
    wait_for_state(panel, jc.JobState.PAUSED)
    assert gate.seen == ["a.jpg"], "the second image was not begun"
    drain(panel)
    assert "Pause requested" in details_text(panel) + summary_text(panel)

    panel.resume()
    gate.let_through()
    runner.join()
    drain(panel)

    assert gate.seen == ["a.jpg", "b.jpg"]
    assert panel.run_result.succeeded_count == 2


def test_a_paused_run_holds_no_half_written_output(
    make_panel, output_base, tmp_path, monkeypatch
):
    runner = ThreadRunner()
    panel = make_panel(job_runner=runner)
    import_files(panel,
                 make_image(tmp_path / "art" / "a.jpg"),
                 make_image(tmp_path / "art" / "b.jpg"))
    gate = Gate()
    monkeypatch.setattr(cr, "resize_for_audiobook", gate)

    start(panel)
    gate.let_through()
    panel.pause()
    wait_for_state(panel, jc.JobState.PAUSED)

    assert written_under(run_dir_of(output_base)) == ["a.jpg"], (
        "exactly the finished image, and nothing partial")

    panel.resume()
    gate.let_through()
    runner.join()
    drain(panel)


def test_resume_continues_without_redoing_completed_work(
    make_panel, output_base, tmp_path, monkeypatch
):
    runner = ThreadRunner()
    panel = make_panel(job_runner=runner)
    import_files(panel,
                 make_image(tmp_path / "art" / "a.jpg"),
                 make_image(tmp_path / "art" / "b.jpg"))
    gate = Gate()
    monkeypatch.setattr(cr, "resize_for_audiobook", gate)

    start(panel)
    gate.let_through()
    panel.pause()
    wait_for_state(panel, jc.JobState.PAUSED)
    panel.resume()
    gate.let_through()
    runner.join()
    drain(panel)

    assert gate.seen == ["a.jpg", "b.jpg"], "each image was attempted exactly once"


def test_cancel_wakes_a_paused_worker(make_panel, output_base, tmp_path, monkeypatch):
    runner = ThreadRunner()
    panel = make_panel(job_runner=runner)
    import_files(panel,
                 make_image(tmp_path / "art" / "a.jpg"),
                 make_image(tmp_path / "art" / "b.jpg"))
    gate = Gate()
    monkeypatch.setattr(cr, "resize_for_audiobook", gate)

    start(panel)
    gate.let_through()
    panel.pause()
    wait_for_state(panel, jc.JobState.PAUSED)

    panel.cancel()
    runner.join()                      # would hang if cancel did not wake it
    drain(panel)

    assert panel.job_controller.state is jc.JobState.CANCELLED
    assert panel.run_result.cancelled is True
    assert gate.seen == ["a.jpg"]


def test_cancel_after_a_completed_replacement_leaves_it_replaced_and_says_so(
    make_panel, tmp_path, monkeypatch
):
    first = make_image(tmp_path / "art" / "a.jpg")
    second = make_image(tmp_path / "art" / "b.jpg")
    second_before = sha(second)
    runner = ThreadRunner()
    panel = make_panel(job_runner=runner)
    import_files(panel, first, second)
    arm_replacement(panel)
    gate = Gate()
    monkeypatch.setattr(cr, "resize_for_audiobook", gate)

    start(panel)
    gate.let_through()
    panel.cancel()
    runner.join()
    drain(panel)

    with Image.open(first) as img:
        assert img.size == (64, 64), "a completed replacement is never rolled back"
    assert sha(second) == second_before, "the unreached original is unchanged"
    log = panel.log.get("1.0", "end")
    assert "1 of 2 original(s) replaced" in log
    assert "unchanged" in log
    assert panel.run_result.cancelled is True


def test_a_cancelled_run_reports_unreached_items_as_not_attempted(
    make_panel, output_base, tmp_path
):
    runner = InlineRunner(defer=True)
    panel = make_panel(job_runner=runner)
    import_files(panel,
                 make_image(tmp_path / "art" / "a.jpg"),
                 make_image(tmp_path / "art" / "b.jpg"))

    start(panel)
    panel.cancel()
    runner.release()
    drain(panel)

    result = panel.run_result
    assert result.cancelled is True
    assert result.not_attempted_count == 2
    assert result.failed_count == 0, "an unreached item is not a failure"
    assert written_under(run_dir_of(output_base)) == []


def test_import_cancellation_and_processing_cancellation_stay_independent(make_panel):
    body = ast.unparse(method_named("cancel"))
    assert "_cancel_event" in body
    assert "importer" not in body and "coordinator" not in body
    panel = make_panel()
    assert isinstance(panel._cancel_event, threading.Event)


def test_the_checkpoint_is_reached_only_between_images():
    """The cooperative boundary sits at the top of the per-image loop."""
    worker = method_named("resize_worker")
    loops = [node for node in ast.walk(worker) if isinstance(node, ast.For)]
    assert len(loops) == 1, "one loop, one boundary"
    checkpoints = [node for node in ast.walk(worker)
                   if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "checkpoint"]
    assert len(checkpoints) == 1
    body = ast.unparse(loops[0])
    assert body.index("checkpoint") < body.index("resize_for_audiobook")


def test_a_cancelled_run_is_only_settled_after_the_worker_acknowledged_it(
    make_panel, output_base, tmp_path
):
    runner = InlineRunner(defer=True)
    panel = make_panel(job_runner=runner)
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))

    start(panel)
    panel.cancel()
    assert panel.job_controller.state is jc.JobState.CANCEL_REQUESTED
    assert panel.job_controller.cancel_acknowledged is False

    runner.release()

    assert panel.job_controller.cancel_acknowledged is True
    assert panel.job_controller.state is jc.JobState.CANCELLED


# --------------------------------------------------------------------------- #
# 7. Job UI and reporting
# --------------------------------------------------------------------------- #


def test_the_panel_composes_the_shared_job_widgets_and_defines_none_of_them():
    defined = {node.name for node in ast.walk(panel_tree())
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for shared in ("JobController", "JobAdapter", "JobControlBar", "JobStatusView",
                   "SummaryDetailsView", "JobReporter", "JobEventStream",
                   "ProgressTracker", "EtaEstimator", "LockGroup", "RunResult"):
        assert shared not in defined, shared


def test_the_panel_offers_the_shared_run_controls(make_panel):
    panel = make_panel()
    labels = {action: str(button.cget("text"))
              for action, button in panel.jobs.controls.buttons.items()}
    assert labels[jc.JobAction.PAUSE] == "Pause"
    assert labels[jc.JobAction.RESUME] == "Resume"
    assert labels[jc.JobAction.CANCEL] == "Cancel"
    assert jc.JobAction.RETRY_FAILED in labels


def test_the_summary_never_carries_a_traceback_or_a_command(
    make_panel, output_base, tmp_path, monkeypatch
):
    panel = make_panel()
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))

    def explode(*_a, **_k):
        raise OSError(
            "C:\\tools\\ffmpeg.exe -i secret --flag\nTraceback (most recent call last)")

    monkeypatch.setattr(cr, "resize_for_audiobook", explode)
    start(panel)

    summary = summary_text(panel)
    assert "Traceback (most recent call last)" not in summary
    assert "--flag" not in summary
    assert "a.jpg" in summary


def test_details_keeps_the_diagnostic_the_summary_refused(
    make_panel, output_base, tmp_path, monkeypatch
):
    panel = make_panel()
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))
    monkeypatch.setattr(
        cr, "resize_for_audiobook",
        lambda *a, **k: (_ for _ in ()).throw(OSError("device lost")))

    start(panel)

    assert "device lost" in details_text(panel)


def test_progress_is_never_rounded_up_to_a_false_success(
    make_panel, output_base, tmp_path, monkeypatch
):
    runner = ThreadRunner()
    panel = make_panel(job_runner=runner)
    import_files(panel,
                 make_image(tmp_path / "art" / "a.jpg"),
                 make_image(tmp_path / "art" / "b.jpg"))
    gate = Gate()
    monkeypatch.setattr(cr, "resize_for_audiobook", gate)

    start(panel)
    gate.let_through()
    panel.cancel()
    runner.join()
    drain(panel)

    view = panel.jobs.status.view
    assert view.total == 2
    assert view.completed == 1, "a cancelled run keeps the count it really reached"
    assert panel.run_result.succeeded_count == 1


def test_the_estimate_says_calculating_until_it_is_trustworthy(
    make_panel, output_base, tmp_path
):
    panel = make_panel(job_runner=InlineRunner(defer=True))
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))

    start(panel)

    assert panel.jobs.status.eta_text == jc.CALCULATING
    assert panel.job_estimator.sample_count == 0


def test_the_estimate_measures_one_comparable_category(make_panel, output_base, tmp_path):
    sources = [make_image(tmp_path / "art" / f"{index}.jpg") for index in range(5)]
    panel = make_panel()
    import_files(panel, *sources)

    start(panel)

    assert panel.job_estimator.sample_count == 5
    assert panel.job_estimator.category == cr.ETA_CATEGORY


def test_a_failed_item_contributes_no_timing_sample(
    make_panel, output_base, tmp_path, monkeypatch
):
    panel = make_panel()
    import_files(panel,
                 make_image(tmp_path / "art" / "a.jpg"),
                 make_image(tmp_path / "art" / "b.jpg"))
    fail_named(monkeypatch, "b.jpg")

    start(panel)

    assert panel.job_estimator.sample_count == 1, "a failed unit is not history"


def test_inputs_and_options_lock_through_the_shared_matrix(make_panel, tmp_path):
    panel = make_panel(job_runner=InlineRunner(defer=True))
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))

    start(panel)

    applied = panel.jobs.locks.last_applied
    assert applied[jc.ControlKind.IMPORTED_INPUT] is True
    assert applied[jc.ControlKind.PROCESSING_OPTION] is True
    assert applied[jc.ControlKind.JOB_CONTROL] is False
    assert applied[jc.ControlKind.LOG_VIEW] is False
    assert applied[jc.ControlKind.PROGRESS_STATUS] is False
    assert applied[jc.ControlKind.OPEN_OUTPUT] is False
    assert panel.importer.list.locked is True
    assert panel.browser.locked is True
    assert str(panel.entry_size.cget("state")) == "disabled"


def test_the_panel_registers_its_controls_under_the_shared_kinds(make_panel):
    panel = make_panel()
    inputs = panel.jobs.locks.registered(jc.ControlKind.IMPORTED_INPUT)
    options = panel.jobs.locks.registered(jc.ControlKind.PROCESSING_OPTION)
    assert panel.importer in inputs and panel.browser in inputs
    assert panel in options, "the panel's own option widgets lock as one unit"


def test_no_panel_specific_lock_table_was_written():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    for invented in ("LOCK_STATES", "LOCKED_WIDGETS", "INPUT_LOCKED", "LOCK_MATRIX"):
        assert invented not in source, invented


def test_the_view_switch_stays_available_while_selection_locks(make_panel, tmp_path):
    panel = make_panel(job_runner=InlineRunner(defer=True))
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))

    start(panel)

    assert panel.browser.locked is True
    assert panel.browser.set_view(cr.VIEW_LIST) == cr.VIEW_LIST
    assert panel.browser.view == cr.VIEW_LIST


def test_everything_unlocks_when_the_run_ends(make_panel, output_base, tmp_path):
    panel = make_panel()
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))

    start(panel)

    assert panel.jobs.locks.last_applied[jc.ControlKind.IMPORTED_INPUT] is False
    assert panel.importer.list.locked is False
    assert str(panel.entry_size.cget("state")) == "normal"


def test_the_output_location_is_reported_once_for_a_standard_run(
    make_panel, output_base, tmp_path
):
    panel = make_panel()
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))

    start(panel)

    run_dir = run_dir_of(output_base)
    locations = [event.location for event in panel.jobs.stream.events
                 if event.kind is jc.JobEventKind.OUTPUT_LOCATION]
    assert locations == [run_dir]
    assert panel.var_outdir.get() == str(run_dir)


def test_a_state_is_only_ever_copied_from_the_controller(
    make_panel, output_base, tmp_path
):
    panel = make_panel()
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))

    start(panel)

    states = [event.state for event in panel.jobs.stream.events if event.state is not None]
    assert jc.JobState.RUNNING in states
    assert states[-1] is jc.JobState.SUCCEEDED
    assert panel.jobs.stream.terminal is not None
    assert panel.jobs.stream.terminal.kind is jc.JobEventKind.COMPLETED


def test_the_stream_refuses_an_event_from_another_run(make_panel, output_base, tmp_path):
    panel = make_panel()
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))
    start(panel)

    stranger = jc.JobEvent(kind=jc.JobEventKind.WARNING, run_id="cover-run-999",
                           sequence=0, timestamp=1.0, message="from elsewhere")
    before = len(panel.jobs.stream.events)
    panel._event_q.put(stranger)
    drain(panel)

    assert len(panel.jobs.stream.events) == before
    assert panel.jobs.stream.rejected[-1][0] is stranger


# --------------------------------------------------------------------------- #
# 8. One pump, and close safety
# --------------------------------------------------------------------------- #


def test_exactly_one_pump_owns_every_scheduled_callback(make_panel):
    panel = make_panel()
    assert panel._pump.running is True
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "self.after(" not in source, "the panel's own after-chain is retired"
    assert source.count("MainThreadPump(") == 1
    assert "after_idle" not in source


def test_the_three_expected_drains_ride_that_one_pump(make_panel):
    """Named, not counted: a number alone would hide which drain arrived."""
    panel = make_panel()
    registered = list(panel._pump._drains)
    assert panel.browser.drain in registered
    assert panel.jobs.drain in registered
    assert panel._drain_worker_queue in registered
    assert len(registered) == 3, registered


def test_swapping_the_run_adapter_leaves_exactly_three_drains(
    make_panel, output_base, tmp_path
):
    panel = make_panel()
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))

    start(panel)
    assert panel._pump.drain_count == 3
    start(panel)
    assert panel._pump.drain_count == 3, "the retired adapter dropped its drain"


def test_closing_during_a_run_leaves_nothing_scheduled(
    make_panel, output_base, tmp_path
):
    panel = make_panel(job_runner=InlineRunner(defer=True))
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))
    start(panel)

    panel.close()

    assert panel._pump.closed is True
    assert panel._pump.pending is None
    assert panel._pump.drain_count == 0
    assert panel.jobs.closed is True
    assert panel.browser.closed is True
    assert panel.importer.closed is True


def test_closing_is_idempotent_and_safe_late(make_panel):
    panel = make_panel()
    panel.close()
    panel.close()
    assert panel._pump.closed is True


def test_closing_a_paused_run_cannot_deadlock(
    make_panel, output_base, tmp_path, monkeypatch
):
    runner = ThreadRunner()
    panel = make_panel(job_runner=runner)
    import_files(panel,
                 make_image(tmp_path / "art" / "a.jpg"),
                 make_image(tmp_path / "art" / "b.jpg"))
    gate = Gate()
    monkeypatch.setattr(cr, "resize_for_audiobook", gate)

    start(panel)
    gate.let_through()
    panel.pause()
    wait_for_state(panel, jc.JobState.PAUSED)

    panel.close()                       # must request cancellation, then join

    runner.join()
    assert panel._pump.closed is True
    assert gate.seen == ["a.jpg"]


def test_closing_leaves_no_worker_thread_behind(
    make_panel, output_base, tmp_path, monkeypatch
):
    runner = ThreadRunner()
    panel = make_panel(job_runner=runner)
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))
    gate = Gate()
    monkeypatch.setattr(cr, "resize_for_audiobook", gate)

    start(panel)
    gate.let_through()
    panel.close()

    assert all(not worker.is_alive() for worker in runner.threads)


def test_an_event_published_after_close_is_inert(make_panel, output_base, tmp_path):
    panel = make_panel(job_runner=InlineRunner(defer=True))
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))
    start(panel)
    jobs = panel.jobs
    before = len(jobs.stream.events)

    panel.close()
    panel._event_q.put(jc.JobEvent(
        kind=jc.JobEventKind.WARNING, run_id=jobs.run_id, sequence=999,
        timestamp=1.0, message="too late"))
    jobs.drain()

    assert len(jobs.stream.events) == before


def test_destroying_the_panel_finishes_its_own_teardown(tk_root, output_base):
    """A regression test for a defect this phase introduced and fixed.

    The shared job widgets bring Tk variables that survive ``destroy`` inside
    reference cycles. Left there, they are freed by the cyclic collector on
    whichever thread crosses its threshold — and a Tk variable finalized off the
    main thread raises "main thread is not in main loop", surfacing in whatever
    unrelated code happened to be running. The panel therefore finishes its own
    teardown on the thread that owns the widgets.

    The suite-wide warning count is what proves the outcome; what is checked
    here is that the mechanism is still the deliberate one and that it runs
    after the widgets are gone, rather than the warning having been silenced.
    """
    body = ast.unparse(method_named("destroy"))
    assert "gc.collect()" in body, (
        "the collection is deliberate; do not suppress the warning instead")
    assert body.index("super().destroy()") < body.index("gc.collect()")
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    for suppression in ("filterwarnings", "simplefilter", "PytestUnraisable"):
        assert suppression not in source, suppression

    panel = cr.CoverResizerUI(
        tk_root, clock=_counter(), home=None, thread_factory=RecordingThreads(),
        preview_runner=no_previews, job_runner=InlineRunner())
    assert panel.jobs.status.var_eta is not None, "the shared view owns Tk variables"

    panel.destroy()
    panel.destroy()                     # still idempotent with the collection in it


def test_the_worker_touches_no_tk_object_and_no_panel_widget():
    """The Phase 4 crash class this project already paid for once."""
    worker = method_named("resize_worker")
    reached = {
        node.attr for node in ast.walk(worker)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name) and node.value.id == "self"
    }
    assert reached == {"_log_q", "_cancel_event"}, reached
    names = {node.id for node in ast.walk(worker) if isinstance(node, ast.Name)}
    assert "tk" not in names and "ttk" not in names


def test_no_arbitrary_sleep_exists_in_this_file_or_the_panel():
    # Assembled rather than written out, so this guard cannot match itself.
    forbidden = ".".join(("time", "sleep"))
    assert forbidden not in Path(__file__).read_text(encoding="utf-8")
    assert forbidden not in PANEL_SOURCE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Phase 2 and Phase 3 preservation
# --------------------------------------------------------------------------- #


def test_the_manager_is_still_the_single_imported_file_source(make_panel, tmp_path):
    source = make_image(tmp_path / "art" / "a.jpg")
    panel = make_panel()
    import_files(panel, source)
    assert panel.imported_files() == [source]
    text = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "self.files" not in text and "self.listbox" not in text


def test_the_three_browser_views_are_untouched(make_panel, tmp_path):
    source = make_image(tmp_path / "art" / "a.jpg")
    panel = make_panel()
    import_files(panel, source)
    assert panel.browser.view == cr.DEFAULT_VIEW == cr.VIEW_DETAILS
    for view in cr.VIEW_IDS:
        assert panel.browser.set_view(view) == view
    assert panel.browser.order == panel.manager.snapshot().occurrence_ids


def test_the_import_cancel_is_still_usable_while_a_resize_runs(make_panel, tmp_path):
    """Locking the inputs for a run deliberately leaves the import status bar alone."""
    panel = make_panel(job_runner=InlineRunner(defer=True))
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"))
    panel.importer.status.set_cancel_enabled(True)      # as a live scan would

    start(panel)

    assert panel.importer.list.locked is True
    assert panel.importer.options.locked is True
    assert panel.importer.status.cancel_enabled is True, "the scan stays cancellable"


def test_the_catalog_still_follows_the_capability_probe(make_panel):
    panel = make_panel()
    assert {entry.type_id for entry in panel.import_catalog.types} >= {"jpg", "png"}


def test_the_replaceable_suffixes_and_written_suffix_are_unchanged():
    assert cr.REPLACEABLE_SUFFIXES == frozenset(
        {".jpg", ".jpeg", ".png", ".heic", ".heif"})
    assert cr.written_suffix(".webp") == ".jpg"
    assert cr.written_suffix(".HEIC") == ".heic"


def test_the_legacy_worker_contract_still_runs_without_job_control(tmp_path):
    """``resize_worker`` is still drivable with the plain parameter dict."""

    class Host:
        def __init__(self):
            self._cancel_event = threading.Event()
            self._log_q: queue.Queue = queue.Queue()

    source = make_image(tmp_path / "art" / "cover.jpg")
    host = Host()
    cr.CoverResizerUI.resize_worker(host, {
        "size": 64, "letterbox": True, "mode": cr.ACTION_NUMBERED,
        "files": [source], "run_dir": None, "planner": None,
        "source_planner": op.SourceSidePlanner(),
    })

    assert (tmp_path / "art" / "cover-1.jpg").exists()
    kinds = []
    while True:
        try:
            kinds.append(host._log_q.get_nowait()[0])
        except queue.Empty:
            break
    assert "progress" in kinds and "done" in kinds
    assert "result" not in kinds, "a run with no frozen snapshot settles nothing"
