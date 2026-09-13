"""The M4B Maker batch runner — v0.6.4 Phase 5.

``mp3_tools/m4b_maker_batch.py`` runs one frozen ``RunPlan`` through the shared
job architecture without a panel: exactly one ``JobController`` and one
``JobReporter`` per batch attempt, one worker body, the Phase 4 single-Book
engine for every Book in frozen order, continue-after-failure, the Plan 6
``WorkspaceRunResult`` / ``BookDisposition`` / ``retry_failed_books`` contract,
and — with Auto-number on — the shared ``SuccessNumbers`` allocator: propose,
write the part on the **staged** file, publish, then commit only on success.

Media are one-second FFmpeg tones under ``tmp_path``; FFmpeg is required.
"""

from __future__ import annotations

import ast
import hashlib
import threading
import time
from pathlib import Path, PurePath

import pytest

from shared import book_workspace, ffmpeg_utils, metadata, output_paths
from shared import subprocess_utils as sp
from shared.book_workspace import (
    BookDisposition, BookJob, SharedMetadata, WorkspaceRunResult, WorkspaceSnapshot,
    remove_book, set_shared_metadata,
)
from shared.importing import (
    IdFactory, ImportOptions, ImportedFile, ImportedFileSnapshot, ImportRoot, Revision,
)
from shared.job_control import JobController, JobEventKind, JobState, RunResult
from shared.numbering import SuccessNumbers

from mp3_tools import m4b_maker_batch as batch
from mp3_tools import m4b_maker_plan as mp
from mp3_tools import m4b_maker_processing as proc
from mp3_tools import m4b_maker_workflow as wf
from mp3_tools.m4b_maker_batch import Attempt, BatchError, MakerRun

from test_importing import make_config

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_maker_batch.py"

_IDS = IdFactory("bt-")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _ffmpeg():
    if not ffmpeg_utils.have_ffmpeg():
        pytest.fail("ffmpeg/ffprobe could not be resolved; the batch runner cannot be proved")


def tone(path: Path, seconds: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sp.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "64k", str(path)],
           check=True)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def sources(tmp_path: Path) -> Path:
    root = tmp_path / "Sources"
    root.mkdir()
    return root


@pytest.fixture
def reserve(tmp_path: Path):
    counter = {"n": 0}

    def make(**_kw):
        counter["n"] += 1
        directory = tmp_path / "Outputs" / "M4B-Maker-Outputs" / f"M4B-Maker-{counter['n']}"
        directory.mkdir(parents=True)
        return output_paths.RunReservation(
            tool_key="m4b_maker", base_directory=tmp_path / "Outputs",
            tool_directory=directory.parent, run_directory=directory, run_number=counter["n"])

    make.calls = counter  # type: ignore[attr-defined]
    return make


def imported(sources: Path, folder: str, name: str) -> ImportedFile:
    path = tone(sources / folder / name)
    occurrence = _IDS.next_id("occurrence")
    return ImportedFile(occurrence, path, ImportRoot("r", sources, 0),
                        PurePath(folder) / name, "mp3", f"id-{occurrence}")


def book(sources: Path, folder: str, names=("01.mp3",), **configuration) -> BookJob:
    files = tuple(imported(sources, folder, name) for name in names)
    return BookJob(book_id=book_workspace.new_book_id(_IDS), configuration=configuration,
                   files=ImportedFileSnapshot(Revision(1), files))


def workspace(*books: BookJob, shared: SharedMetadata | None = None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(books=books, current_book_id=books[0].book_id,
                             shared=wf.new_shared_metadata() if shared is None else shared)


def plan(space, reserve, options: mp.MakerRunOptions | None = None) -> mp.RunPlan:
    return mp.plan_run(space, options=options or mp.MakerRunOptions(),
                       destination=mp.standard_destination(reserve()),
                       catalog=wf.MAKER_CATALOG,
                       import_options=ImportOptions.for_catalog(wf.MAKER_CATALOG),
                       effective_config=make_config(), id_factory=_IDS)


def three_books(sources, reserve, **options):
    space = workspace(book(sources, "A", title="A", series="Saga"),
                      book(sources, "B", title="B", series="Saga"),
                      book(sources, "C", title="C", series="Saga"))
    return plan(space, reserve, mp.MakerRunOptions(**options)), space


class Events:
    """Everything the reporter published, in order. No queue, no thread hop."""

    def __init__(self) -> None:
        self.seen = []

    def __call__(self, event) -> None:
        self.seen.append(event)

    def kinds(self):
        return [e.kind for e in self.seen]

    def of(self, kind):
        return [e for e in self.seen if e.kind == kind]


def make_run(made: mp.RunPlan, **kwargs) -> tuple[MakerRun, Events]:
    events = Events()
    run = MakerRun(made, id_factory=_IDS, clock=time.monotonic, publish=events, **kwargs)
    return run, events


def break_named(monkeypatch, made: mp.RunPlan, book_id: str) -> None:
    """Make exactly one Book's encode fail, through the engine's own command seam."""
    target = made.book_for(book_id).staged
    real_fast = proc.fast_concat_args
    real_safe = proc.safe_concat_args

    def broken(real):
        def build(listfile, ffmeta, out_path, bitrate):
            args = real(listfile, ffmeta, out_path, bitrate)
            if Path(out_path) == target:
                return args[:-1] + ["-no_such_option_for_ffmpeg", args[-1]]
            return args
        return build

    monkeypatch.setattr(proc, "fast_concat_args", broken(real_fast))
    monkeypatch.setattr(proc, "safe_concat_args", broken(real_safe))


def dispositions(result: WorkspaceRunResult) -> list[BookDisposition]:
    return [d for _id, d in result.dispositions]


def series_part(path: Path) -> str:
    return str(metadata.read_m4b_tags(path).get("series_part", "") or "")


# --------------------------------------------------------------------------- #
# One batch: frozen order, continue after failure, correct settlement
# --------------------------------------------------------------------------- #


def test_all_books_succeed_in_frozen_order_under_one_controller(sources, reserve):
    made, _ = three_books(sources, reserve)
    run, events = make_run(made)
    attempt = run.start()
    assert isinstance(attempt, Attempt)
    assert isinstance(attempt.controller, JobController)
    assert attempt.controller.state is JobState.RUNNING
    result = attempt.run()
    assert isinstance(result, WorkspaceRunResult)
    assert result.state is JobState.SUCCEEDED
    assert dispositions(result) == [BookDisposition.SUCCEEDED] * 3
    assert [entry.published.is_file() for entry in made.books] == [True, True, True]
    assert run.result is result and run.active is None
    assert attempt.controller.state is JobState.SUCCEEDED
    # One controller, one reporter for the whole batch; events carry one run id.
    assert {e.run_id for e in events.seen} == {attempt.run_id}
    assert events.of(JobEventKind.COMPLETED)[-1].state is JobState.SUCCEEDED
    stages = [e.stage for e in events.of(JobEventKind.STAGE_CHANGED) if e.stage.startswith("book-")]
    assert stages == ["book-1", "book-2", "book-3"]
    assert len(events.of(JobEventKind.OUTPUT_LOCATION)) >= 3


def test_a_failed_book_does_not_stop_later_books(sources, reserve, monkeypatch):
    made, _ = three_books(sources, reserve)
    b = made.books[1]
    break_named(monkeypatch, made, b.book_id)
    run, events = make_run(made)
    result = run.start().run()
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert dispositions(result) == [BookDisposition.SUCCEEDED, BookDisposition.FAILED,
                                    BookDisposition.SUCCEEDED]
    assert made.books[0].published.is_file() and made.books[2].published.is_file()
    assert not b.published.exists()
    failed = result.result_for(b.book_id)
    assert failed.state is JobState.COMPLETED_WITH_FAILURES
    assert set(failed.retryable_ids) == set(b.occurrence_ids), "attributed to the real inputs"
    assert result.retryable_book_ids == (b.book_id,)
    failures = events.of(JobEventKind.FAILURE)
    assert failures and all(e.item_id in b.occurrence_ids for e in failures)


def test_a_fatal_book_failure_is_item_less_and_not_retryable(sources, reserve):
    bad_art = sources / "art.jpg"
    bad_art.write_bytes(b"not an image")
    space = workspace(book(sources, "A", title="A", artwork=str(bad_art)),
                      book(sources, "B", title="B"))
    made = plan(space, reserve)
    run, _ = make_run(made)
    result = run.start().run()
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    a = result.result_for(made.books[0].book_id)
    assert a.state is JobState.FAILED and a.failures.fatal
    assert all(entry.item_id is None for entry in a.failures.records)
    assert not a.has_retryable
    assert result.retryable_book_ids == ()
    assert made.books[1].published.is_file()


def test_skipped_empty_books_keep_their_shared_disposition(sources, reserve):
    empty = BookJob(book_id=book_workspace.new_book_id(_IDS), configuration={"title": "E"})
    space = workspace(book(sources, "A", title="A"), empty)
    made = plan(space, reserve)
    run, _ = make_run(made)
    result = run.start().run()
    assert dispositions(result) == [BookDisposition.SUCCEEDED, BookDisposition.SKIPPED_EMPTY]


def test_the_worker_body_runs_exactly_once_per_attempt(sources, reserve):
    made, _ = three_books(sources, reserve)
    run, _ = make_run(made)
    attempt = run.start()
    attempt.run()
    with pytest.raises(BatchError):
        attempt.run()
    with pytest.raises(BatchError):
        run.start()


def test_a_second_start_while_an_attempt_is_active_is_refused(sources, reserve):
    made, _ = three_books(sources, reserve)
    run, _ = make_run(made)
    run.start()
    with pytest.raises(BatchError):
        run.start()


# --------------------------------------------------------------------------- #
# Success-only Series Part numbering
# --------------------------------------------------------------------------- #


def test_auto_number_off_preserves_the_manual_series_part(sources, reserve):
    space = workspace(book(sources, "A", title="A", series="Saga", series_part="7"),
                      book(sources, "B", title="B", series="Saga"))
    made = plan(space, reserve, mp.MakerRunOptions(auto_number=False))
    run, _ = make_run(made)
    assert run.numbers is None, "no allocator is created when Auto-number is off"
    run.start().run()
    assert series_part(made.books[0].published) == "7"
    assert series_part(made.books[1].published) == ""


def test_auto_number_gives_consecutive_parts_to_successes_only(sources, reserve, monkeypatch):
    made, _ = three_books(sources, reserve, auto_number=True, start_part_text="1")
    b = made.books[1]
    break_named(monkeypatch, made, b.book_id)
    run, _ = make_run(made)
    assert isinstance(run.numbers, SuccessNumbers) and run.numbers.start == 1
    result = run.start().run()
    assert dispositions(result) == [BookDisposition.SUCCEEDED, BookDisposition.FAILED,
                                    BookDisposition.SUCCEEDED]
    assert series_part(made.books[0].published) == "1"
    assert series_part(made.books[2].published) == "2", "B consumed nothing"
    assert run.numbers.consumed == 2 and run.numbers.next_number == 3
    tags = metadata.read_m4b_tags(made.books[2].published)
    assert tags["series"] == "Saga"


def test_the_start_part_is_the_frozen_one(sources, reserve):
    made, _ = three_books(sources, reserve, auto_number=True, start_part_text="4")
    run, _ = make_run(made)
    run.start().run()
    assert [series_part(e.published) for e in made.books] == ["4", "5", "6"]


def test_a_publication_failure_commits_no_number_and_retains_the_candidate(sources, reserve,
                                                                             monkeypatch):
    made, _ = three_books(sources, reserve, auto_number=True, start_part_text="1")
    b = made.books[1]
    real = proc.publish_book

    def refuse_b(entry, *, work_root):
        if entry.book_id == b.book_id:
            raise proc.ProcessingError("destination refused", stage="publish", detail="x")
        return real(entry, work_root=work_root)

    monkeypatch.setattr(proc, "publish_book", refuse_b)
    run, _ = make_run(made)
    result = run.start().run()
    assert dispositions(result) == [BookDisposition.SUCCEEDED, BookDisposition.FAILED,
                                    BookDisposition.SUCCEEDED]
    assert run.numbers.consumed == 2
    assert series_part(made.books[2].published) == "2", "B's tentative 2 was never committed"
    assert b.staged.is_file(), "the validated candidate is retained for the retry"
    assert series_part(b.staged) == "2", "it still carries the stale tentative part"
    assert not b.published.exists()
    assert result.retryable_book_ids == (b.book_id,)


# --------------------------------------------------------------------------- #
# Retry Failed
# --------------------------------------------------------------------------- #


def test_retry_failed_rebuilds_only_the_failed_book_and_takes_the_next_part(
        sources, reserve, monkeypatch):
    made, space = three_books(sources, reserve, auto_number=True, start_part_text="1")
    b = made.books[1]
    break_named(monkeypatch, made, b.book_id)
    run, events = make_run(made)
    first = run.start().run()
    assert dispositions(first) == [BookDisposition.SUCCEEDED, BookDisposition.FAILED,
                                   BookDisposition.SUCCEEDED]
    before = {e.book_id: (sha(e.published), e.published.stat().st_mtime_ns)
              for e in (made.books[0], made.books[2])}
    # Building the retry consumes no number.
    consumed = run.numbers.consumed
    monkeypatch.undo()
    retry = run.retry_failed()
    assert isinstance(retry, Attempt) and retry.is_retry
    assert run.numbers.consumed == consumed and run.numbers.next_number == 3
    assert [entry.book_id for entry in retry.books] == [b.book_id]
    assert retry.run_id == events.seen[0].run_id, "a retry is a new attempt at the same run"
    assert retry.controller is not run.attempts[0].controller

    result = retry.run()
    assert result.state is JobState.SUCCEEDED
    assert dispositions(result) == [BookDisposition.SUCCEEDED] * 3
    assert b.published.is_file() and series_part(b.published) == "3"
    assert run.numbers.consumed == 3
    assert {e.book_id: (sha(e.published), e.published.stat().st_mtime_ns)
            for e in (made.books[0], made.books[2])} == before, "successes untouched"
    assert result.result_for(made.books[0].book_id) is first.result_for(made.books[0].book_id)


def test_a_retained_candidate_gets_its_stale_part_rewritten_before_publication(
        sources, reserve, monkeypatch):
    made, _ = three_books(sources, reserve, auto_number=True, start_part_text="1")
    b = made.books[1]
    real = proc.publish_book

    def refuse_b_once(entry, *, work_root):
        if entry.book_id == b.book_id and not refuse_b_once.done:
            refuse_b_once.done = True
            raise proc.ProcessingError("destination refused", stage="publish", detail="x")
        return real(entry, work_root=work_root)

    refuse_b_once.done = False
    monkeypatch.setattr(proc, "publish_book", refuse_b_once)
    ran: list[str] = []
    real_stage = proc.stage_book

    def spy_stage(entry, **kwargs):
        ran.append(entry.book_id)
        return real_stage(entry, **kwargs)

    monkeypatch.setattr(proc, "stage_book", spy_stage)
    run, _ = make_run(made)
    run.start().run()
    assert series_part(b.staged) == "2"
    ran.clear()
    result = run.retry_failed().run()
    assert result.state is JobState.SUCCEEDED
    assert ran == [], "the retained, validated candidate was reused; nothing re-encoded"
    assert series_part(b.published) == "3"
    assert not b.staged.exists() and not b.staging_dir.exists()


def test_retry_uses_the_original_frozen_plan_whatever_changed_since(sources, reserve,
                                                                     monkeypatch):
    made, space = three_books(sources, reserve, auto_number=True, start_part_text="1")
    b = made.books[1]
    break_named(monkeypatch, made, b.book_id)
    run, _ = make_run(made)
    run.start().run()
    monkeypatch.undo()
    # Everything the user could change afterwards changes.
    edited = wf.set_book_field(space, "title", "Renamed").workspace
    edited = set_shared_metadata(edited, SharedMetadata(fields=wf.SHARED_FIELDS,
                                                        values={"series": "Other"})).workspace
    edited = remove_book(edited, id_factory=_IDS).workspace
    assert edited.count == 2
    retry = run.retry_failed()
    assert retry.books[0] is b, "the same frozen BookPlan object"
    result = retry.run()
    assert result.state is JobState.SUCCEEDED
    tags = metadata.read_m4b_tags(b.published)
    assert tags["title"] == "B" and tags["series"] == "Saga" and tags["series_part"] == "3"


def test_retry_is_refused_when_nothing_is_retryable(sources, reserve):
    made, _ = three_books(sources, reserve)
    run, _ = make_run(made)
    with pytest.raises(BatchError):
        run.retry_failed()
    run.start().run()
    with pytest.raises(BatchError):
        run.retry_failed()


# --------------------------------------------------------------------------- #
# Pause / Resume / Cancel through the shared controller
# --------------------------------------------------------------------------- #


def wait_for(predicate, *, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_pause_is_acknowledged_at_a_checkpoint_and_resume_continues(sources, reserve):
    made, _ = three_books(sources, reserve)
    run, events = make_run(made)
    attempt = run.start()
    asked = {"done": False}

    def on_event(event):
        # After Book 1 publishes, ask for a pause from the worker's own thread.
        if event.kind is JobEventKind.OUTPUT_LOCATION and not asked["done"]:
            asked["done"] = True
            run.pause()

    run.add_listener(on_event)
    worker = threading.Thread(target=attempt.run, name="maker-batch-test")
    worker.start()
    wait_for(lambda: attempt.controller.state is JobState.PAUSED)
    states = [e.state for e in events.of(JobEventKind.STATE_CHANGED)]
    assert JobState.PAUSE_REQUESTED in states and states[-1] is JobState.PAUSED
    assert not made.books[2].published.exists(), "nothing runs while paused"
    run.resume()
    worker.join(timeout=30)
    assert not worker.is_alive()
    assert run.result.state is JobState.SUCCEEDED
    assert dispositions(run.result) == [BookDisposition.SUCCEEDED] * 3


def test_cancel_stops_at_the_next_checkpoint_and_leaves_the_rest_not_attempted(
        sources, reserve):
    made, _ = three_books(sources, reserve)
    run, events = make_run(made)
    attempt = run.start()

    def on_event(event):
        if event.kind is JobEventKind.OUTPUT_LOCATION:
            run.cancel()

    run.add_listener(on_event)
    result = attempt.run()
    assert result.state is JobState.CANCELLED
    assert dispositions(result) == [BookDisposition.SUCCEEDED, BookDisposition.NOT_ATTEMPTED,
                                    BookDisposition.NOT_ATTEMPTED]
    assert made.books[0].published.is_file()
    assert not made.books[1].published.exists() and not made.books[2].published.exists()
    assert not made.work_root.exists() or not any(made.work_root.iterdir())
    assert events.of(JobEventKind.CANCELLED)
    assert attempt.controller.state is JobState.CANCELLED
    assert result.not_attempted_count == 2


def test_cancel_mid_book_publishes_no_partial_work(sources, reserve):
    space = workspace(book(sources, "A", ("01.mp3", "02.mp3"), title="A", silence="0.5"))
    made = plan(space, reserve)
    run, _ = make_run(made)
    attempt = run.start()
    calls = {"n": 0}
    real_checkpoint = attempt.controller.checkpoint

    def checkpoint():
        calls["n"] += 1
        if calls["n"] == 3:
            run.cancel()
        real_checkpoint()

    attempt.checkpoint = checkpoint
    result = attempt.run()
    assert result.state is JobState.CANCELLED
    assert dispositions(result) == [BookDisposition.NOT_ATTEMPTED]
    assert not made.books[0].published.exists()
    assert not made.books[0].staging_dir.exists()


# --------------------------------------------------------------------------- #
# Structure: one framework, Tk-free
# --------------------------------------------------------------------------- #


def test_the_runner_composes_the_shared_framework_and_defines_none_of_it():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    for banned in ("tkinter", "threading", "queue", "shared.job_ui", "shared.ui_theme",
                   "shared.import_coordination", "mp3_tools.m4b_maker", "mp3_tools.mp3_tool",
                   "mp3_tools.mp3_processing", "mp3_tools.mp3_plan", "mp3_tools.mp3_workflow",
                   "mp3_tools.m4b_maker_workflow", "mp3_tools.m4b_numbering"):
        assert banned not in modules, banned
    for required in ("shared.job_control", "shared.book_workspace", "shared.numbering",
                     "mp3_tools.m4b_maker_plan", "mp3_tools.m4b_maker_processing"):
        assert required in modules, required
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for owned_elsewhere in ("JobController", "JobReporter", "JobEventStream", "RunResult",
                            "FailureRecord", "RetryRequest", "WorkspaceRunResult",
                            "SuccessNumbers", "Tentative", "BookDisposition",
                            "retry_failed_books", "propose", "commit", "stage_book",
                            "publish_book", "build_book", "plan_run", "capture_workspace_run"):
        assert owned_elsewhere not in declared, owned_elsewhere
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    called |= {node.func.attr for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for reused in ("retry_failed_books", "propose", "commit", "settle", "stage_book",
                   "publish_book", "checkpoint"):
        assert reused in called, reused
    assert "Thread" not in called, "the worker thread is the caller's"
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for live in ("WorkspaceSnapshot", "BookJob", "StringVar", "current", "books_var"):
        assert live not in names, live
    # Exactly one place constructs the controller, outside any loop.
    sites = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("JobController")]
    assert len(sites) == 1
    for loop in (n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.While))):
        assert sites[0] not in ast.walk(loop)


def test_the_runner_is_registered_as_a_plan3_adopter():
    from test_plan3_boundaries import ADOPTED

    assert "mp3_tools/m4b_maker_batch.py" in ADOPTED


def test_the_maker_panel_is_still_byte_identical():
    from test_plan6_boundaries import PHASE0_PANEL_HASHES, sha256_as_checked_out_on_windows

    panel = UNIVERSAL / "mp3_tools" / "m4b_maker.py"
    assert sha256_as_checked_out_on_windows(panel) == PHASE0_PANEL_HASHES["mp3_tools/m4b_maker.py"]
    assert "m4b_maker_batch" not in panel.read_text(encoding="utf-8")
