"""MP3 Tool staging lives exactly as long as a Retry Failed can reach it — v0.7.2 Phase 6, ACT72-019 and ACT72-037.

A run stages every Book under its run folder's private ``.work`` area. A Book that failed retryably keeps its good pieces
there for Retry Failed; everything else is disposable. Before v0.7.2 Phase 6 the work area outlived the run whenever the
run did not end in a clean success: a Cancel escaped ``write_id3_run`` / ``combine_run`` before ``discard_run_staging``
(ACT72-037), and the pieces kept for a retry stayed after Clear All Imports, a new run or closing the tool, when no Retry
Failed could reach them any more (ACT72-019).

Real one-second tones through the real engines and the real panel; the panel's own actions only. Every test checks that
nothing published, nothing outside the work area and no source is touched.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from shared import ffmpeg_utils
from shared.job_control import JobAction, JobState

from mp3 import mp3_plan, mp3_processing as proc, mp3_tool  # noqa: E402

from test_import_coordination import RealThreads  # noqa: E402
from test_mp3_orchestration import settle, three_books, wait_for  # noqa: E402
from test_mp3_tool_ui import (  # noqa: E402,F401  (fixtures are collected by name)
    make_panel,
    tk_root,
    windows_theme,
)

pytestmark = pytest.mark.skipif(
    not ffmpeg_utils.have_ffmpeg(), reason="ffmpeg/ffprobe not available in this environment")


def tree(root: Path) -> dict[str, str]:
    """Every file under *root* by relative path, with its content hash."""
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            found[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def published(panel) -> dict[str, str]:
    """What the run published: every file of the run folder outside its private work area."""
    run = panel.last_plan.run_directory
    return {name: digest for name, digest in tree(run).items() if not name.startswith(mp3_plan.WORK_DIRNAME + "/")}


def sentinels(tmp_path: Path, run: Path) -> dict[Path, bytes]:
    """Unrelated files beside the run and inside it, which nothing may touch."""
    planted = {run / "unrelated.txt": b"not the tool's", run.parent / "other-run-file.txt": b"someone else's"}
    for path, data in planted.items():
        path.write_bytes(data)
    return planted


def assert_untouched(planted: dict[Path, bytes]) -> None:
    for path, data in planted.items():
        assert path.read_bytes() == data, path


def failed_run(panel, tmp_path, monkeypatch):
    """A / B / C with B's second track broken: A and C publish, B keeps its good pieces for Retry Failed."""
    made, root = three_books(panel, tmp_path, monkeypatch)
    sources = tree(root)
    panel.write_id3_tags()
    settle(panel)
    result = panel.last_result
    assert result.state is JobState.COMPLETED_WITH_FAILURES and result.can_retry_failed
    work = panel.last_plan.work_root
    b = panel.last_plan.book_for(panel.workspace.books[1].book_id)
    assert sorted(path.name for path in work.iterdir()) == [b.staging_dir.name], "only B's staging is retained"
    assert any(track.staged.is_file() for track in b.tracks), "B's good pieces stay for Retry Failed"
    return root, sources, work


def test_a_failed_run_keeps_only_the_retryable_book_and_closing_the_tool_removes_it(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    root, sources, work = failed_run(panel, tmp_path, monkeypatch)
    planted = sentinels(tmp_path, panel.last_plan.run_directory)
    outputs = published(panel)
    assert outputs, "A and C were published"
    panel.close()
    assert not work.exists(), "nothing can retry once the tool is closed (ACT72-019)"
    assert published(panel) == outputs, "published Books are never touched"
    assert tree(root) == sources, "the originals are byte-identical"
    assert_untouched(planted)
    panel.close()  # idempotent
    assert not work.exists()


def test_clear_all_imports_removes_the_staging_kept_for_retry(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    root, sources, work = failed_run(panel, tmp_path, monkeypatch)
    plan = panel.last_plan
    planted = sentinels(tmp_path, plan.run_directory)
    outputs = published(panel)
    assert panel.clear_all_imports() is True
    assert not work.exists(), "Clear All Imports drops the run, and with it every chance of a retry"
    assert {name: digest for name, digest in tree(plan.run_directory).items()} == {**outputs, "unrelated.txt": hashlib.sha256(b"not the tool's").hexdigest()}
    assert tree(root) == sources
    assert_untouched(planted)


def test_a_new_run_removes_the_previous_runs_retained_staging_and_keeps_its_own(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    root, sources, first_work = failed_run(panel, tmp_path, monkeypatch)
    first_plan = panel.last_plan
    first_outputs = published(panel)
    panel.write_id3_tags()  # B is still broken: the new run keeps its own B for its own retry
    settle(panel)
    assert panel.last_plan is not first_plan
    assert not first_work.exists(), "the first run's Retry Failed is no longer reachable"
    assert {k: v for k, v in tree(first_plan.run_directory).items()} == first_outputs
    assert panel.last_plan.work_root.is_dir(), "the new run's own retry keeps its pieces"
    assert panel.controls.availability()[JobAction.RETRY_FAILED] is True
    assert tree(root) == sources


def test_retry_failed_still_reuses_the_kept_pieces_and_a_successful_retry_leaves_no_work_area(
        make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    root, sources, work = failed_run(panel, tmp_path, monkeypatch)
    plan = panel.last_plan
    b = plan.book_for(panel.workspace.books[1].book_id)
    kept = {track.staged: hashlib.sha256(track.staged.read_bytes()).hexdigest() for track in b.tracks if track.staged.is_file()}
    broken = next(track.source for track in b.tracks if not track.staged.is_file())
    good = next(track.source for track in b.tracks if track.staged.is_file())
    broken.write_bytes(good.read_bytes())  # the user repairs the file; the retry re-stages only it
    reused: list[Path] = []
    real = proc._stage_clean_copy

    def watch(book, track):
        reused.append(track.staged)
        return real(book, track)

    monkeypatch.setattr(proc, "_stage_clean_copy", watch)
    assert panel.retry_failed() is True
    settle(panel)
    assert panel.last_result.state is JobState.SUCCEEDED
    assert not set(kept) & set(reused), "the kept pieces were reused, not re-made"
    assert not work.exists(), "a successful retry leaves no work area"


def test_a_cancel_during_ffmpeg_leaves_no_work_area_and_publishes_nothing_partial(make_panel, tmp_path, monkeypatch):
    """ACT72-037: the Cancel escaped the engine before discard_run_staging and left ``.work`` behind."""
    panel = make_panel(thread_factory=RealThreads())
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    sources = tree(root)
    stopped: dict[str, object] = {}
    real_args = proc._clean_copy_args

    def slow_second_track_of_b(source, staged):
        args = real_args(source, staged)
        if source.parent.name == "B" and source.name.startswith("02"):
            # Real FFmpeg at the playing rate, so Cancel lands while it runs.
            args = [args[0], "-re", *args[1:]]
            controller = panel.job_controller
            threading.Timer(0.3, controller.request_cancel).start()
            stopped["staged"] = staged
        return args

    monkeypatch.setattr(proc, "_clean_copy_args", slow_second_track_of_b)
    panel.write_id3_tags()
    plan = panel.last_plan
    planted = sentinels(tmp_path, plan.run_directory)
    wait_for(panel, lambda: not panel.is_running, timeout=30.0)
    for thread in panel._thread_factory.made:
        thread.join(10.0)
    assert panel.last_result.state is JobState.CANCELLED
    assert "staged" in stopped, "the Cancel landed during B's second FFmpeg"
    assert not plan.work_root.exists(), "a cancelled run cannot be retried, so nothing is kept (ACT72-037)"
    a = plan.book_for(panel.workspace.books[0].book_id)
    assert a.published_dir.is_dir() and all(path.is_file() for path in a.published_outputs), "Book A stays published"
    b = plan.book_for(panel.workspace.books[1].book_id)
    assert not b.published_dir.exists(), "nothing of the cancelled Book was published"
    assert tree(root) == sources
    assert_untouched(planted)


def test_an_item_less_failure_cannot_be_retried_so_its_staging_goes_at_once(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    sources = tree(root)
    real_publish = mp3_plan.publish_book

    def refuse_b(book):
        if book.number == 2:
            raise mp3_plan.PlanError("the destination vanished")
        return real_publish(book)

    monkeypatch.setattr(proc.mp3_plan, "publish_book", refuse_b)
    panel.write_id3_tags()
    settle(panel)
    result = panel.last_result
    assert result.state is JobState.COMPLETED_WITH_FAILURES and not result.can_retry_failed
    assert not panel.last_plan.work_root.exists(), "an item-less publication failure offers no retry"
    assert tree(root) == sources


def test_an_unexpected_worker_fault_leaves_no_work_area(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    made, root = three_books(panel, tmp_path, monkeypatch, broken=None)
    real_validate = proc.validate_staged_track

    def fault_in_b(book, track, artwork, **kwargs):
        if book.number == 2:
            raise RuntimeError("disk vanished")
        return real_validate(book, track, artwork, **kwargs)

    monkeypatch.setattr(proc, "validate_staged_track", fault_in_b)
    panel.write_id3_tags()
    settle(panel)
    assert panel.last_result.state is JobState.FAILED
    assert not panel.last_plan.work_root.exists()


@pytest.mark.skipif(os.name != "nt", reason="a directory junction is a Windows link")
def test_a_junction_planted_in_the_kept_staging_never_exposes_what_it_points_at(make_panel, tmp_path, monkeypatch):
    panel = make_panel()
    root, sources, work = failed_run(panel, tmp_path, monkeypatch)
    outside = tmp_path / "Foreign"
    outside.mkdir()
    (outside / "keep.txt").write_bytes(b"foreign data")
    b = panel.last_plan.book_for(panel.workspace.books[1].book_id)
    link = b.staging_dir / "planted"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    staged = [track.staged for track in b.tracks if track.staged.is_file()]
    assert staged
    panel.close()
    assert (outside / "keep.txt").read_bytes() == b"foreign data", "nothing behind a link is ever removed"
    assert not any(path.exists() for path in staged), "the release ran: B's own pieces are gone"
    assert not b.staging_dir.exists() and not work.exists(), "the junction was unlinked as a link, so nothing stayed"
    assert tree(root) == sources


def test_the_release_is_bounded_to_the_plans_own_staging_and_safe_to_repeat(tmp_path, monkeypatch, make_panel):
    """The function itself: Books named in *keep* stay, the rest go, the work area goes once empty."""
    panel = make_panel()
    root, sources, work = failed_run(panel, tmp_path, monkeypatch)
    plan = panel.last_plan
    b = plan.book_for(panel.workspace.books[1].book_id)
    assert mp3_plan.release_staging(plan, keep={b.book_id}) == ()
    assert b.staging_dir.is_dir(), "a kept Book is untouched"
    assert mp3_plan.release_staging(plan) == ()
    assert not work.exists()
    assert mp3_plan.release_staging(plan) == (), "repeating it finds nothing to do"
    time.sleep(0)  # nothing asynchronous: the release is done when it returns
