"""M4B Metadata Editor staging lives exactly as long as a Retry Failed can reach it — v0.7.2 Phase 6, ACT72-034.

A Book whose publication or Series Part write failed keeps its validated candidate in the run's ``.work`` for Retry
Failed. Before v0.7.2 Phase 6 nothing removed it when Clear All Imports, a new action or closing the tool dropped the run,
and a cancelled attempt kept an earlier Book's candidate that nothing could retry (the same class as the MP3 Tool's
ACT72-019). Real FFmpeg-built containers through the real engine; published outputs and sources are checked every time.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared.job_control import JobAction, JobState  # noqa: E402

from m4b.metadata import m4b_metadata_batch as batch  # noqa: E402
from m4b.metadata import m4b_metadata_processing as proc  # noqa: E402

from test_m4b_metadata_batch import make_run, three_books  # noqa: E402
from test_m4b_metadata_processing import (  # noqa: E402,F401  (fixtures are collected by name)
    container,
    reserve,
    sha,
    sources,
)
from test_m4b_metadata_editor_ui import (  # noqa: E402,F401
    import_folder,
    library,
    make_panel,
    output_base,
    tk_root,
    windows_theme,
)


def tree(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def refuse_publication(monkeypatch, refuse) -> None:
    real = proc.publish_book

    def publish(entry, *, work_root):
        if refuse(entry):
            raise proc.ProcessingError("the destination refused it", stage="publish", detail="test")
        return real(entry, work_root=work_root)

    monkeypatch.setattr(proc, "publish_book", publish)


def refuse_numbering_of(monkeypatch, staged: Path) -> None:
    """Refuse only the batch's own Series Part write on *staged*; the engine's tag writes go through."""
    real = batch.metadata.write_m4b_tags

    def write(path, tags, *args, **kwargs):
        caller = sys._getframe(1).f_code.co_filename
        if Path(path) == staged and Path(caller).name == "m4b_metadata_batch.py":
            raise OSError("the tag could not be written")
        return real(path, tags, *args, **kwargs)

    monkeypatch.setattr(batch.metadata, "write_m4b_tags", write)


# --------------------------------------------------------------------------- the run itself, headless


def test_a_publication_failure_keeps_the_candidate_until_the_run_is_abandoned(container, sources, reserve, monkeypatch):
    made, _, _ = three_books(container, sources, reserve)
    a, b, c = made.books
    refuse_publication(monkeypatch, lambda entry: entry.book_id == b.book_id)
    before = tree(sources)
    run, _ = make_run(made)
    result = run.start().run()
    assert result.retryable_book_ids == (b.book_id,) and result.can_retry_failed
    assert b.staged.is_file(), "the validated candidate is kept for Retry Failed"
    published = {path: sha(path) for path in (a.published, c.published)}
    assert run.abandon() == ()
    assert not b.staging_dir.exists() and not made.work_root.exists(), "nothing can retry an abandoned run"
    assert {path: sha(path) for path in published} == published
    assert tree(sources) == before
    assert run.abandon() == (), "abandoning again finds nothing to do"


def test_a_series_part_failure_keeps_the_candidate_until_the_run_is_abandoned(container, sources, reserve, monkeypatch):
    made, _, _ = three_books(container, sources, reserve, auto_number=True, start_part_text="1")
    b = made.books[1]
    refuse_numbering_of(monkeypatch, b.staged)
    run, _ = make_run(made)
    result = run.start().run()
    assert result.retryable_book_ids == (b.book_id,)
    assert b.staged.is_file(), "a Series Part failure keeps the candidate for the retry"
    run.abandon()
    assert not made.work_root.exists()


def test_a_cancel_after_a_kept_candidate_leaves_no_staging(container, sources, reserve, monkeypatch):
    made, _, _ = three_books(container, sources, reserve)
    a, b, c = made.books
    refused = []
    refuse_publication(monkeypatch, lambda entry: entry.book_id == b.book_id and not refused.append(True))
    run, _ = make_run(made)
    attempt = run.start()
    real_checkpoint = attempt.checkpoint
    seen = {"n": 0}

    def checkpoint():
        if refused and b.staged.is_file():  # after B's refusal, so at C's checkpoint
            seen["n"] += 1
            run.cancel()
        real_checkpoint()

    attempt.checkpoint = checkpoint
    result = attempt.run()
    assert seen["n"], "the Cancel came after B's candidate was kept"
    assert result.state is JobState.CANCELLED and not result.can_retry_failed
    assert a.published.is_file() and not c.published.exists()
    assert not made.work_root.exists(), "a cancelled run keeps nothing it cannot retry"


def test_a_run_abandoned_while_its_attempt_runs_keeps_nothing_when_it_ends(container, sources, reserve, monkeypatch):
    made, _, _ = three_books(container, sources, reserve)
    b = made.books[1]
    refuse_publication(monkeypatch, lambda entry: entry.book_id == b.book_id)
    run, _ = make_run(made, staging_lock=threading.Lock())
    attempt = run.start()
    started, release = threading.Event(), threading.Event()
    real_checkpoint = attempt.checkpoint

    def checkpoint():
        started.set()
        release.wait(30.0)
        real_checkpoint()

    attempt.checkpoint = checkpoint
    worker = threading.Thread(target=attempt.run)
    worker.start()
    assert started.wait(30.0)
    assert run.abandon() == (), "the running attempt is left to finish"
    release.set()
    worker.join(60.0)
    assert not worker.is_alive()
    assert run.result.state is JobState.COMPLETED_WITH_FAILURES
    assert not made.work_root.exists(), "nothing is kept for a retry no one can start"


# --------------------------------------------------------------------------- the panel lets go


@pytest.mark.parametrize("action", ["close", "clear_all_imports", "save_again"])
def test_dropping_the_run_removes_the_kept_candidate(action, make_panel, container, tmp_path, monkeypatch, output_base):
    root = library(container, tmp_path / "Library")
    before = tree(root)
    panel = make_panel()
    import_folder(panel, root)
    refuse_publication(monkeypatch, lambda entry: entry.filename == "Beta.m4b")
    assert panel.save() is True
    panel._pump.tick()
    plan = panel.last_plan
    candidate = next(book for book in plan.books if book.filename == "Beta.m4b")
    assert panel.last_result.can_retry_failed and candidate.staged.is_file()
    assert panel.jobs.controls.availability()[JobAction.RETRY_FAILED] is True
    published = {book.published: sha(book.published) for book in plan.books if book.published.is_file()}
    assert published, "the other Books were published"
    stray = plan.run_directory / "unrelated.txt"
    stray.write_bytes(b"someone else's")
    if action == "close":
        panel.close()
    elif action == "clear_all_imports":
        assert panel.clear_all_imports() is True
    else:
        assert panel.save() is True
        panel._pump.tick()
        assert panel.last_plan is not plan
    assert not candidate.staging_dir.exists() and not plan.work_root.exists(), action
    assert {path: sha(path) for path in published} == published
    assert stray.read_bytes() == b"someone else's"
    assert tree(root) == before
