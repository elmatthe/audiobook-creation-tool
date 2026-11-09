"""M4B Maker staging lives exactly as long as a Retry Failed can reach it — v0.7.2 Phase 6, ACT72-031.

A Book whose publication or Series Part write failed keeps its validated candidate in staging for Retry Failed. Before
v0.7.2 Phase 6 nothing removed it when Clear All Imports, a new Build or closing the tool dropped the run, a cancelled
attempt kept an earlier Book's candidate that nothing could retry, and custom mode staged in a loose
``%TEMP%\\act-m4b-build-*`` folder that no record owned, so a killed Maker left it for good.

Now the run's end removes everything its attempt cannot retry, ``MakerRun.abandon`` removes the rest when the panel lets
go, and a custom build stages in an entry of the owned TTS work area (``tts.work_area``, kind ``maker``): listed with
its owner before it exists, removed through handles that never follow a link, and recovered by the next run only once
its owner is provably gone. Real tones through the real engine; published outputs and sources are checked every time.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared.book_workspace import BookDisposition  # noqa: E402
from shared.job_control import JobAction, JobState  # noqa: E402

from m4b.maker import m4b_maker, m4b_maker_batch as batch  # noqa: E402
from m4b.maker import m4b_maker_plan as mp  # noqa: E402
from m4b.maker import m4b_maker_processing as proc  # noqa: E402
from tts import work_area  # noqa: E402

from test_m4b_maker_batch import (  # noqa: E402,F401  (fixtures are collected by name)
    _ffmpeg,
    make_run,
    reserve,
    sources,
    three_books,
)
from test_m4b_maker_ui import (  # noqa: E402,F401
    import_folder,
    make_panel,
    output_base,
    tk_root,
    tone,
    windows_theme,
)
from test_import_traversal import touch  # noqa: E402
from test_tts_work_area import (  # noqa: E402,F401
    _IDENTIFY,
    SCRIPTS,
    children,
    kill,
    temp,
    wait_ready,
    windows_only,
    workspace_of,
)


def tree(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def refuse_publication_of(monkeypatch, book_id: str) -> None:
    real = proc.publish_book

    def publish(entry, *, work_root):
        if entry.book_id == book_id:
            raise proc.ProcessingError("the destination refused it", stage="publish", detail="test")
        return real(entry, work_root=work_root)

    monkeypatch.setattr(proc, "publish_book", publish)


def refuse_numbering_of(monkeypatch, staged: Path) -> None:
    """Refuse only the batch's own Series Part write on *staged*; the engine's staging writes go through."""
    real = batch.metadata.write_m4b_tags

    def write(path, tags, *args, **kwargs):
        caller = sys._getframe(1).f_code.co_filename
        if Path(path) == staged and Path(caller).name == "m4b_maker_batch.py":
            raise OSError("the tag could not be written")
        return real(path, tags, *args, **kwargs)

    monkeypatch.setattr(batch.metadata, "write_m4b_tags", write)


# --------------------------------------------------------------------------- the run itself, headless


def test_a_publication_failure_keeps_the_candidate_until_the_run_is_abandoned(sources, reserve, monkeypatch):
    made, _ = three_books(sources, reserve)
    a, b, c = made.books
    refuse_publication_of(monkeypatch, b.book_id)
    released = []
    run, _ = make_run(made, on_staging_released=lambda: released.append(True))
    before = tree(sources)
    result = run.start().run()
    assert result.retryable_book_ids == (b.book_id,) and result.can_retry_failed
    assert b.staged.is_file(), "the validated candidate is kept for Retry Failed"
    assert not released, "the work area is still in use"
    published = {path: path.read_bytes() for path in (a.published, c.published)}
    assert run.abandon() == ()
    assert not b.staging_dir.exists() and not made.work_root.exists(), "nothing can retry an abandoned run"
    assert released, "the owner of the work area was told it is free"
    assert {path: path.read_bytes() for path in published} == published
    assert tree(sources) == before
    assert run.abandon() == (), "abandoning again finds nothing to do"


def test_a_numbering_failure_keeps_the_candidate_until_the_run_is_abandoned(sources, reserve, monkeypatch):
    made, _ = three_books(sources, reserve, auto_number=True, start_part_text="1")
    b = made.books[1]
    refuse_numbering_of(monkeypatch, b.staged)
    run, _ = make_run(made)
    result = run.start().run()
    assert result.retryable_book_ids == (b.book_id,)
    assert b.staged.is_file(), "a numbering failure keeps the candidate for the retry"
    run.abandon()
    assert not made.work_root.exists()


def test_a_cancel_after_a_kept_candidate_leaves_no_staging(sources, reserve, monkeypatch):
    """B's candidate is kept when its publication fails; the run is then cancelled, so no retry can ever use it."""
    made, _ = three_books(sources, reserve)
    a, b, c = made.books
    refuse_publication_of(monkeypatch, b.book_id)
    real_refuse = proc.publish_book
    refused = []

    def note(entry, *, work_root):
        try:
            return real_refuse(entry, work_root=work_root)
        except proc.ProcessingError:
            refused.append(entry.book_id)
            raise

    monkeypatch.setattr(proc, "publish_book", note)
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


def test_a_run_abandoned_while_its_attempt_runs_keeps_nothing_when_it_ends(sources, reserve, monkeypatch):
    made, _ = three_books(sources, reserve)
    b = made.books[1]
    refuse_publication_of(monkeypatch, b.book_id)
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
    assert run.result.state is JobState.COMPLETED_WITH_FAILURES, "it completed as it would have"
    assert not made.work_root.exists(), "but nothing is kept for a retry no one can start"


def test_retry_failed_reuses_the_kept_candidate_and_a_full_success_releases_the_work_area(sources, reserve, monkeypatch):
    made, _ = three_books(sources, reserve)
    b = made.books[1]
    real_publish = proc.publish_book
    refuse_publication_of(monkeypatch, b.book_id)
    released = []
    run, events = make_run(made, on_staging_released=lambda: released.append(True))
    run.start().run()
    candidate = b.staged.read_bytes()
    monkeypatch.setattr(proc, "publish_book", real_publish)  # the destination is back
    result = run.retry_failed().run()
    assert result.state is JobState.SUCCEEDED
    assert b.published.read_bytes() == candidate, "the kept candidate itself was published"
    assert any("reusing the staged candidate" in e.detail for e in events.seen)
    assert not made.work_root.exists() and released


# --------------------------------------------------------------------------- the panel lets go


def failed_panel_build(make_panel, tmp_path):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    tone(root / "B" / "01.mp3")
    panel = make_panel()
    import_folder(panel, root)
    return panel, root


def build_with_b_refused(panel, monkeypatch):
    """Build A and B; B's publication is refused, so its validated candidate is kept for Retry Failed."""
    real = proc.publish_book

    def publish(entry, *, work_root):
        if entry.filename == "B.m4b":
            raise proc.ProcessingError("the destination refused it", stage="publish", detail="test")
        return real(entry, work_root=work_root)

    monkeypatch.setattr(proc, "publish_book", publish)
    assert panel.build() is True
    panel._pump.tick()
    plan = panel.last_plan
    candidate = next(book for book in plan.books if book.filename == "B.m4b")
    assert panel.last_result.can_retry_failed and candidate.staged.is_file()
    assert panel.jobs.controls.availability()[JobAction.RETRY_FAILED] is True
    return plan, candidate


@pytest.mark.parametrize("action", ["close", "clear_all_imports", "build_again"])
def test_dropping_the_run_removes_the_kept_candidate(action, make_panel, tmp_path, monkeypatch, output_base):
    panel, root = failed_panel_build(make_panel, tmp_path)
    sources_before = tree(root)
    plan, candidate = build_with_b_refused(panel, monkeypatch)
    a = plan.books[0]
    published = a.published.read_bytes()
    stray = plan.root / "unrelated.txt"
    stray.write_bytes(b"someone else's")
    if action == "close":
        panel.close()
    elif action == "clear_all_imports":
        assert panel.clear_all_imports() is True
    else:
        assert panel.build() is True
        panel._pump.tick()
        assert panel.last_plan is not plan
    assert not candidate.staging_dir.exists() and not plan.work_root.exists(), action
    assert a.published.read_bytes() == published
    assert stray.read_bytes() == b"someone else's"
    assert tree(root) == sources_before


# --------------------------------------------------------------------------- custom mode: an owned work area


def custom_panel(make_panel, tmp_path, chosen: Path):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    tone(root / "B" / "01.mp3")
    panel = make_panel(choose_destination=lambda: str(chosen))
    import_folder(panel, root)
    panel.var_custom_dest.set(True)
    panel._on_custom_dest_change()
    panel.choose_custom_dest()
    return panel, root


def entries_of_kind(temp: Path, kind: str) -> list[tuple[Path, dict]]:
    found = []
    root = temp / work_area.ROOT_NAME
    if not root.exists():
        return found
    for manifest in root.glob("*/" + work_area.MANIFEST_NAME):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for name, facts in data["entries"].items():
            if facts["kind"] == kind:
                found.append((manifest.parent / name, facts))
    return found


def test_a_custom_build_stages_in_an_owned_entry_and_leaves_nothing(
        make_panel, tmp_path, temp, monkeypatch, output_base):
    chosen = tmp_path / "Chosen"
    chosen.mkdir()
    panel, root = custom_panel(make_panel, tmp_path, chosen)
    seen = {}
    real_stage = proc.stage_book

    def stage(book, *, work_root, **kwargs):
        seen["entries"] = entries_of_kind(temp, "maker")
        seen["work_root"] = work_root
        return real_stage(book, work_root=work_root, **kwargs)

    monkeypatch.setattr(proc, "stage_book", stage)
    assert panel.build() is True
    panel._pump.tick()
    assert panel.last_result.state is JobState.SUCCEEDED
    (entry, facts), = seen["entries"]
    assert facts["state"] == work_area.ACTIVE and facts["retention"] == work_area.DISPOSABLE
    assert Path(seen["work_root"]).parent == entry, "the build stages inside its listed entry"
    assert not list(temp.glob("act-m4b-build-*")), "no loose, unowned staging root any more"
    area = temp / work_area.ROOT_NAME
    assert not area.exists() or not any(area.iterdir()), "a finished build leaves nothing in the work area"
    assert sorted(path.name for path in chosen.iterdir()) == ["A.m4b", "B.m4b"]


def test_a_custom_builds_kept_candidate_stays_in_its_entry_until_the_tool_closes(
        make_panel, tmp_path, temp, monkeypatch, output_base):
    chosen = tmp_path / "Chosen"
    chosen.mkdir()
    panel, root = custom_panel(make_panel, tmp_path, chosen)
    plan, candidate = build_with_b_refused(panel, monkeypatch)
    (entry, facts), = entries_of_kind(temp, "maker")
    assert candidate.staged.is_file() and entry in candidate.staged.parents
    assert facts["state"] == work_area.ACTIVE, "kept for Retry Failed, so still in use"
    panel.close()
    assert not candidate.staged.exists() and not entry.exists()
    assert not entries_of_kind(temp, "maker")
    assert sorted(path.name for path in chosen.iterdir()) == ["A.m4b"], "the chosen folder keeps what was published"


MAKER_CHILD = _IDENTIFY + r"""
import tempfile, time
temp, barrier, scripts = sys.argv[1:4]
tempfile.tempdir = temp
sys.path.insert(0, scripts)
from tts import work_area
folder = work_area.new_folder("maker")
staging = folder.path / "staging" / "Book"
staging.mkdir(parents=True)
(staging / "Book.m4b").write_bytes(b"M" * 4096)
identify(barrier, scripts)
while True:
    time.sleep(60)
"""


@windows_only
def test_a_killed_makers_work_area_is_recovered_by_the_next_custom_build_and_nothing_else_is(
        make_panel, tmp_path, temp, children, output_base):
    loose = temp / "act-m4b-build-legacy1"
    loose.mkdir()
    (loose / "old.m4b").write_bytes(b"left by an older version, owner unknown")
    killed = children(MAKER_CHILD, str(temp), str(tmp_path / "barrier-killed"), str(SCRIPTS))
    wait_ready(killed, tmp_path / "barrier-killed")
    alive = children(MAKER_CHILD, str(temp), str(tmp_path / "barrier-alive"), str(SCRIPTS))
    wait_ready(alive, tmp_path / "barrier-alive")
    dead_workspace = workspace_of(temp, killed)
    live_workspace = workspace_of(temp, alive)
    live_before = tree(live_workspace)
    kill(killed)
    chosen = tmp_path / "Chosen"
    chosen.mkdir()
    panel, root = custom_panel(make_panel, tmp_path, chosen)
    assert panel.build() is True
    panel._pump.tick()
    assert panel.last_result.state is JobState.SUCCEEDED
    assert not dead_workspace.exists(), "the killed Maker's staging is recovered"
    assert tree(live_workspace) == live_before, "a running owner is never disturbed"
    assert (loose / "old.m4b").is_file(), "nothing is ever removed by its name alone"
    assert any("interrupted run" in line for line in panel.log.details), "the recovery is told in Detailed"


# --------------------------------------------------------------------------- a Book stopped part-way (ACT72-004)


def test_a_book_a_cancel_stopped_part_way_reads_cancelled_and_one_never_reached_not_attempted(
        make_panel, tmp_path, monkeypatch, output_base):
    """v0.7.2 Phase 6, ACT72-004: the Book under way when Cancel landed read 'Not attempted', like one never reached.
    Its result stays NOT_ATTEMPTED (no new disposition); the status and the summary tell the two apart."""
    root = tmp_path / "Library"
    for folder in ("A", "B", "C"):
        tone(root / folder / "01.mp3")
    panel = make_panel()
    import_folder(panel, root)
    real = proc.stage_book

    def stage(book, **kwargs):
        if book.filename == "B.m4b":
            panel.run.cancel()                  # pressed as B's staging begins: B stops at its first checkpoint
        return real(book, **kwargs)

    monkeypatch.setattr(proc, "stage_book", stage)
    assert panel.build() is True
    panel._pump.tick()
    a, b, c = panel.workspace.books
    assert [panel.book_status_for(book.book_id) for book in (a, b, c)] == [
        m4b_maker.STATUS_COMPLETED, m4b_maker.STATUS_CANCELLED, m4b_maker.STATUS_NOT_ATTEMPTED]
    summary = "\n".join(panel.log.summary)
    assert "1 Book(s) completed, 0 failed, 0 skipped, 1 stopped by Cancel, 1 not attempted" in summary, summary
