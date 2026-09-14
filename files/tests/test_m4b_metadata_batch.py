"""The M4B Metadata Editor batch runner — v0.6.4 Phase 9.

``mp3_tools/m4b_metadata_batch.py`` runs one frozen Editor ``RunPlan`` through
the shared job architecture with no panel involved: one ``JobController`` and
one ``JobReporter`` per attempt, the Phase 9 engine per Book in frozen order,
continue-on-failure, the Plan 6 ``WorkspaceRunResult`` and Retry Failed, and
the shared success-only ``SuccessNumbers`` for Series auto-number. Pause,
Resume and Cancel are the controller's requests, honoured at checkpoints.

Media are the Phase 7 fixtures (real tiny FFmpeg-built containers); every
test proves the sources are never written.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from shared import metadata
from shared.book_workspace import BookDisposition, WorkspaceRunResult, remove_book
from shared.importing import IdFactory
from shared.job_control import JobController, JobEventKind, JobState

from mp3_tools import m4b_metadata_batch as batch
from mp3_tools import m4b_metadata_plan as mp
from mp3_tools import m4b_metadata_processing as proc
from mp3_tools import m4b_metadata_workflow as wf
from mp3_tools.m4b_metadata_batch import Attempt, BatchError, EditorRun
from mp3_tools.m4b_metadata_plan import EditorAction, EditorRunOptions

from test_m4b_metadata_processing import (  # noqa: F401 - fixtures by import
    audio_md5, build, container, plan, png, reserve, sha, shared_with, sources,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_metadata_batch.py"

_IDS = IdFactory("eb-")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class Events:
    """Everything the reporter published, in order. No queue, no thread hop."""

    def __init__(self) -> None:
        self.seen = []

    def __call__(self, event) -> None:
        self.seen.append(event)

    def of(self, kind):
        return [e for e in self.seen if e.kind == kind]


def three_books(container, sources, reserve, *, action=EditorAction.SAVE_TAGS,
                genre="Shared G", **options):
    """Three tagged Books with a Shared Genre so every Save writes something."""
    space, store = build(container, sources,
                         ("A.m4b", dict(title="A", series="Saga", series_part="7")),
                         ("B.m4b", dict(title="B", series="Saga", series_part="8")),
                         ("C.m4b", dict(title="C", series="Saga", series_part="9")))
    if genre:
        space = shared_with(space, genre=genre)
    made = plan(space, store, reserve, action, EditorRunOptions(**options))
    return made, space, store


def make_run(made: mp.RunPlan, **kwargs) -> tuple[EditorRun, Events]:
    events = Events()
    run = EditorRun(made, id_factory=_IDS, clock=time.monotonic, publish=events, **kwargs)
    return run, events


def break_tags_of(monkeypatch, entry: mp.BookPlan) -> None:
    """Make exactly one Book's tag write fail, through the shared writer seam."""
    real = metadata.write_m4b_tags

    def broken(path, tags, total=None):
        if Path(path) == entry.staged:
            raise RuntimeError("tag write refused")
        return real(path, tags, total=total)

    monkeypatch.setattr(metadata, "write_m4b_tags", broken)


def dispositions(result: WorkspaceRunResult) -> list[BookDisposition]:
    return [d for _id, d in result.dispositions]


def series_part(path: Path) -> str:
    return str(metadata.read_m4b_tags(path).get("series_part", "") or "")


def source_hashes(made: mp.RunPlan) -> dict[str, str]:
    return {entry.book_id: sha(entry.source) for entry in made.books}


def wait_for(predicate, *, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


# --------------------------------------------------------------------------- #
# One batch: frozen order, continue after failure, correct settlement
# --------------------------------------------------------------------------- #


def test_all_books_succeed_in_frozen_order_under_one_controller(container, sources, reserve):
    made, _, _ = three_books(container, sources, reserve)
    before = source_hashes(made)
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
    assert all(metadata.read_m4b_tags(e.published)["genre"] == "Shared G" for e in made.books)
    assert run.result is result and run.active is None
    assert attempt.controller.state is JobState.SUCCEEDED
    assert {e.run_id for e in events.seen} == {attempt.run_id}
    assert events.of(JobEventKind.COMPLETED)[-1].state is JobState.SUCCEEDED
    stages = [e.stage for e in events.of(JobEventKind.STAGE_CHANGED) if e.stage.startswith("book-")]
    assert stages == ["book-1", "book-2", "book-3"]
    assert len(events.of(JobEventKind.OUTPUT_LOCATION)) >= 3
    assert source_hashes(made) == before, "sources never written"
    assert not made.work_root.exists(), "the work area is gone once every Book is done"


def test_a_failed_book_does_not_stop_later_books(container, sources, reserve, monkeypatch):
    made, _, _ = three_books(container, sources, reserve)
    b = made.books[1]
    break_tags_of(monkeypatch, b)
    run, events = make_run(made)
    result = run.start().run()
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert dispositions(result) == [BookDisposition.SUCCEEDED, BookDisposition.FAILED,
                                    BookDisposition.SUCCEEDED]
    assert made.books[0].published.is_file() and made.books[2].published.is_file()
    assert not b.published.exists() and not b.staging_dir.exists()
    failed = result.result_for(b.book_id)
    assert failed.state is JobState.COMPLETED_WITH_FAILURES
    assert set(failed.retryable_ids) == {b.occurrence_id}, "attributed to the real occurrence"
    assert result.retryable_book_ids == (b.book_id,)
    failures = events.of(JobEventKind.FAILURE)
    assert failures and all(e.item_id == b.occurrence_id for e in failures)
    assert all(e.stage == "tags" for e in failures)


def test_a_fatal_book_failure_is_item_less_and_not_retryable(container, sources, reserve):
    bad_art = sources / "art.png"
    bad_art.write_bytes(b"not an image")
    space, store = build(container, sources, ("A.m4b", {}), ("B.m4b", {}))
    space = wf.set_book_field(space, "artwork", str(bad_art)).workspace
    made = plan(space, store, reserve)
    run, _ = make_run(made)
    result = run.start().run()
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    a = result.result_for(made.books[0].book_id)
    assert a.state is JobState.FAILED and a.failures.fatal
    assert all(entry.item_id is None for entry in a.failures.records)
    assert not a.has_retryable
    assert result.retryable_book_ids == ()
    assert made.books[1].published.is_file()


def test_an_unreadable_source_keeps_its_skipped_invalid_disposition(container, sources, reserve):
    space, store = build(container, sources, ("A.m4b", dict(title="A")), unreadable=("bad.m4b",))
    space = shared_with(space, genre="G")
    made = plan(space, store, reserve)
    assert len(made.books) == 1
    run, _ = make_run(made)
    result = run.start().run()
    assert result.state is JobState.SUCCEEDED
    assert dispositions(result) == [BookDisposition.SUCCEEDED, BookDisposition.SKIPPED_INVALID]
    assert (sources / "bad.m4b").read_bytes() == b"not an mp4"


def test_the_worker_body_runs_exactly_once_per_attempt(container, sources, reserve):
    made, _, _ = three_books(container, sources, reserve)
    run, _ = make_run(made)
    attempt = run.start()
    attempt.run()
    with pytest.raises(BatchError):
        attempt.run()
    with pytest.raises(BatchError):
        run.start()


def test_a_second_start_while_an_attempt_is_active_is_refused(container, sources, reserve):
    made, _, _ = three_books(container, sources, reserve)
    run, _ = make_run(made)
    run.start()
    with pytest.raises(BatchError):
        run.start()
    with pytest.raises(BatchError):
        run.retry_failed()


def test_the_run_refuses_anything_but_an_editor_plan():
    with pytest.raises(BatchError):
        EditorRun("nope", id_factory=_IDS)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Series auto-number: success-only, through the shared allocator
# --------------------------------------------------------------------------- #


def test_auto_number_off_preserves_the_source_series_part(container, sources, reserve):
    made, _, _ = three_books(container, sources, reserve)
    run, _ = make_run(made)
    assert run.numbers is None
    run.start().run()
    assert [series_part(e.published) for e in made.books] == ["7", "8", "9"]


def test_auto_number_gives_consecutive_parts_to_successes_only(container, sources, reserve,
                                                               monkeypatch):
    made, _, _ = three_books(container, sources, reserve, auto_number=True, start_part_text="5")
    b = made.books[1]
    break_tags_of(monkeypatch, b)
    run, events = make_run(made)
    assert run.numbers.next_number == 5
    result = run.start().run()
    assert dispositions(result) == [BookDisposition.SUCCEEDED, BookDisposition.FAILED,
                                    BookDisposition.SUCCEEDED]
    assert series_part(made.books[0].published) == "5"
    assert series_part(made.books[2].published) == "6", "the failure consumed no number"
    assert run.numbers.consumed == 2 and run.numbers.next_number == 7
    tags = metadata.read_m4b_tags(made.books[2].published)
    assert tags["series"] == "Saga", "the source Series Name stays beside the new part"
    assert [r.part for r in run.attempts[0].records] == [5, None, 6]


def test_clear_all_with_auto_number_numbers_the_cleared_copy(container, sources, reserve):
    made, _, _ = three_books(container, sources, reserve, action=EditorAction.CLEAR_ALL_TAGS,
                             genre="", auto_number=True, start_part_text="1")
    run, _ = make_run(made)
    result = run.start().run()
    assert result.state is JobState.SUCCEEDED
    for expected, entry in zip(("1", "2", "3"), made.books):
        tags = metadata.read_m4b_tags(entry.published)
        assert series_part(entry.published) == expected
        assert not tags.get("title") and not tags.get("series")
        assert metadata.read_chapter_titles(entry.published) == ["Opening", "Closing"]


def test_remove_series_numbering_never_creates_the_allocator(container, sources, reserve):
    made, _, _ = three_books(container, sources, reserve,
                             action=EditorAction.REMOVE_SERIES_NUMBERING, genre="",
                             auto_number=True, start_part_text="1")
    assert made.auto_number is False
    run, _ = make_run(made)
    assert run.numbers is None
    result = run.start().run()
    assert result.state is JobState.SUCCEEDED
    for entry in made.books:
        tags = metadata.read_m4b_tags(entry.published)
        assert not tags.get("series_part") and tags["series"] == "Saga"


def test_a_publication_failure_commits_no_number_and_retains_the_candidate(
        container, sources, reserve, monkeypatch):
    made, _, _ = three_books(container, sources, reserve, auto_number=True, start_part_text="1")
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


def test_retry_failed_reruns_only_the_failed_book_and_takes_the_next_part(
        container, sources, reserve, monkeypatch):
    made, _, _ = three_books(container, sources, reserve, auto_number=True, start_part_text="1")
    b = made.books[1]
    break_tags_of(monkeypatch, b)
    run, events = make_run(made)
    first = run.start().run()
    assert dispositions(first) == [BookDisposition.SUCCEEDED, BookDisposition.FAILED,
                                   BookDisposition.SUCCEEDED]
    before = {e.book_id: (sha(e.published), e.published.stat().st_mtime_ns)
              for e in (made.books[0], made.books[2])}
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
        container, sources, reserve, monkeypatch):
    made, _, _ = three_books(container, sources, reserve, auto_number=True, start_part_text="1")
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
    assert ran == [], "the retained, validated candidate was reused; nothing re-copied"
    assert series_part(b.published) == "3"
    assert not b.staged.exists() and not b.staging_dir.exists()


def test_retry_uses_the_original_frozen_plan_whatever_changed_since(container, sources, reserve,
                                                                     monkeypatch):
    made, space, _ = three_books(container, sources, reserve, auto_number=True,
                                 start_part_text="1")
    b = made.books[1]
    break_tags_of(monkeypatch, b)
    run, _ = make_run(made)
    run.start().run()
    monkeypatch.undo()
    edited = wf.set_book_field(space, "title", "Renamed").workspace
    edited = shared_with(edited, genre="Other", series="Other Saga")
    edited = remove_book(edited, id_factory=_IDS).workspace
    assert edited.count == 2
    retry = run.retry_failed()
    assert retry.books[0] is b, "the same frozen BookPlan object"
    result = retry.run()
    assert result.state is JobState.SUCCEEDED
    tags = metadata.read_m4b_tags(b.published)
    assert tags["title"] == "B" and tags["genre"] == "Shared G" and tags["series"] == "Saga"
    assert tags["series_part"] == "3"


def test_retry_is_refused_when_nothing_is_retryable(container, sources, reserve):
    made, _, _ = three_books(container, sources, reserve)
    run, _ = make_run(made)
    with pytest.raises(BatchError):
        run.retry_failed()
    run.start().run()
    with pytest.raises(BatchError):
        run.retry_failed()


# --------------------------------------------------------------------------- #
# Pause / Resume / Cancel through the shared controller
# --------------------------------------------------------------------------- #


def test_pause_is_acknowledged_at_a_checkpoint_and_resume_continues(container, sources, reserve):
    made, _, _ = three_books(container, sources, reserve)
    run, events = make_run(made)
    attempt = run.start()
    asked = {"done": False}

    def on_event(event):
        if event.kind is JobEventKind.OUTPUT_LOCATION and not asked["done"]:
            asked["done"] = True
            run.pause()

    run.add_listener(on_event)
    worker = threading.Thread(target=attempt.run, name="editor-batch-test")
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
        container, sources, reserve):
    made, _, _ = three_books(container, sources, reserve)
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


def test_cancel_mid_book_publishes_no_partial_work(container, sources, reserve):
    made, _, _ = three_books(container, sources, reserve)
    before = source_hashes(made)
    run, _ = make_run(made)
    attempt = run.start()
    calls = {"n": 0}
    real_checkpoint = attempt.controller.checkpoint

    def checkpoint():
        calls["n"] += 1
        if calls["n"] == 3:      # after the copy landed in staging
            run.cancel()
        real_checkpoint()

    attempt.checkpoint = checkpoint
    result = attempt.run()
    assert result.state is JobState.CANCELLED
    assert dispositions(result) == [BookDisposition.NOT_ATTEMPTED] * 3
    assert not made.books[0].published.exists()
    assert not made.books[0].staging_dir.exists()
    assert not any(made.run_directory.iterdir())
    assert source_hashes(made) == before


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
    for banned in ("tkinter", "threading", "queue", "shutil", "subprocess", "mutagen",
                   "shared.job_ui", "shared.ui_theme", "shared.import_coordination",
                   "shared.ffmpeg_utils", "shared.subprocess_utils",
                   "mp3_tools.m4b_metadata_editor", "mp3_tools.m4b_maker",
                   "mp3_tools.m4b_maker_batch", "mp3_tools.m4b_maker_processing",
                   "mp3_tools.mp3_tool", "mp3_tools.mp3_processing", "mp3_tools.mp3_plan",
                   "mp3_tools.m4b_metadata_workflow", "mp3_tools.m4b_numbering"):
        assert banned not in modules, banned
    for required in ("shared.job_control", "shared.book_workspace", "shared.numbering",
                     "shared.metadata", "mp3_tools.m4b_metadata_plan",
                     "mp3_tools.m4b_metadata_processing"):
        assert required in modules, required
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for owned_elsewhere in ("JobController", "JobReporter", "JobEventStream", "RunResult",
                            "FailureRecord", "RetryRequest", "WorkspaceRunResult",
                            "SuccessNumbers", "Tentative", "BookDisposition",
                            "retry_failed_books", "propose", "commit", "stage_book",
                            "publish_book", "build_book", "validate_staged", "plan_run",
                            "capture_workspace_run", "MakerRun"):
        assert owned_elsewhere not in declared, owned_elsewhere
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    called |= {node.func.attr for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for reused in ("retry_failed_books", "propose", "commit", "settle", "stage_book",
                   "publish_book", "validate_staged", "write_m4b_tags", "checkpoint"):
        assert reused in called, reused
    assert "Thread" not in called, "the worker thread is the caller's"
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for live in ("WorkspaceSnapshot", "BookJob", "ObservationStore", "StringVar", "current"):
        assert live not in names, live
    sites = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("JobController")]
    assert len(sites) == 1
    for loop in (n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.While))):
        assert sites[0] not in ast.walk(loop)


def test_the_runner_is_registered_as_a_plan3_adopter():
    from test_plan3_boundaries import ADOPTED

    assert "mp3_tools/m4b_metadata_batch.py" in ADOPTED


def test_the_editor_panel_is_still_byte_identical_and_runs_nothing_through_this():
    from test_plan6_boundaries import PHASE0_PANEL_HASHES, sha256_as_checked_out_on_windows

    panel = UNIVERSAL / "mp3_tools" / "m4b_metadata_editor.py"
    assert sha256_as_checked_out_on_windows(panel) == PHASE0_PANEL_HASHES[
        "mp3_tools/m4b_metadata_editor.py"]
    assert "m4b_metadata_batch" not in panel.read_text(encoding="utf-8")
