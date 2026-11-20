"""v0.8.0 macOS Revision 1 (pre-merge remediation) — Cover Image: Cancel is ordered against publication.

The independent pre-merge review reproduced this on the real worker: a Cancel that latched after the between-images
checkpoint but before the resize ran still resized the image, installed it over the original and settled ``SUCCEEDED``.
Standard and numbered saves also wrote unfinished bytes under their final names, because Pillow was handed the final path.

The contract these tests pin:

* every image is first written to a private staging file beside its destination; nothing carries a final name until it is
  complete;
* the one operation that makes an image final (the atomic source replacement, or the exclusive new-name publication) runs
  only after ``JobController.authorize_commit()`` granted it, under the same lock the Cancel latch is taken under, so
  exactly one of Cancel and that publication wins, and it is recorded;
* a denied authorization discards the staging file, leaves the original and every earlier result alone, stops the run
  at once and settles ``CANCELLED`` with no completed-item record for the aborted image;
* a publication that won stays what it is: it is never rolled back, and the remaining images are not started.

Determinism: nothing here sleeps. The worker runs inline (the panel's runner seam), and Cancel is pressed from inside a
hook at the exact point under test, so the order is a fact of the test, not a race it hopes to win. Every image is generated
into ``tmp_path``; no real user image is touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")
pytest.importorskip("tkinter")

from shared import job_control as jc  # noqa: E402
from shared import output_paths as op  # noqa: E402

from artwork import cover_resizer as cr  # noqa: E402

# The shared fixtures and helpers of the Cover job tests: the panel factory, the inline runner, the replacement arming.
from test_cover_jobs import (  # noqa: E402,F401  (fixtures are used by name)
    REAL_RESIZE,
    Gate,
    InlineRunner,
    ThreadRunner,
    arm_replacement,
    details_text,
    drain,
    import_files,
    make_image,
    make_panel,
    output_base,
    run_dir_of,
    sha,
    start,
    tk_root,
    wait_for_state,
    written_under,
)

SIZE = 256


def strays(folder: Path) -> list[str]:
    """Every staging file left in *folder* (recursively)."""
    return sorted(p.name for p in folder.rglob("*") if p.name.startswith(op.TEMP_SIBLING_PREFIX))


def run_with_hook(panel, *, before_resize=None, after_resize=None):
    """Run the panel's resize with a hook on each image, and put the real resize back afterwards."""
    seen: list[str] = []

    def hooked(in_path, out_path, size, letterbox):
        seen.append(Path(in_path).name)
        if before_resize is not None:
            before_resize(len(seen), Path(in_path), Path(out_path))
        written = REAL_RESIZE(in_path, out_path, size=size, letterbox=letterbox)
        if after_resize is not None:
            after_resize(len(seen), Path(in_path), Path(written))
        return written

    cr.resize_for_audiobook = hooked
    try:
        start(panel, size=SIZE)
    finally:
        cr.resize_for_audiobook = REAL_RESIZE
    return seen


def replace_panel(make_panel, tmp_path, count=2, **kwargs):
    """A panel armed for Replace Original over *count* generated images; returns (panel, originals, hashes)."""
    files = [make_image(tmp_path / "art" / f"{name}.jpg") for name in "abcdef"[:count]]
    panel = make_panel(**kwargs)
    import_files(panel, *files)
    asked = arm_replacement(panel)
    return panel, files, [sha(f) for f in files], asked


def state_of(panel):
    return panel.job_controller.state


# --------------------------------------------------------------------------- #
# A. Cancel after the checkpoint, before the resize starts
# --------------------------------------------------------------------------- #


def test_cancel_before_the_resize_starts_never_replaces_the_original(make_panel, tmp_path):
    panel, files, hashes, asked = replace_panel(make_panel, tmp_path)

    seen = run_with_hook(panel, before_resize=lambda n, _in, _out: panel.cancel() if n == 1 else None)

    assert [sha(f) for f in files] == hashes, "an original changed after Cancel won"
    assert state_of(panel) is jc.JobState.CANCELLED, "must not settle SUCCEEDED"
    assert panel.run_result.cancelled is True
    assert panel.run_result.succeeded_count == 0, "no completed-item record for the aborted image"
    assert seen == ["a.jpg"], "no further image may start"
    assert strays(tmp_path) == [], "the interrupted operation's staging file is discarded"
    assert asked == [2], "the destructive confirmation is unchanged: asked once, with the count"


# --------------------------------------------------------------------------- #
# B. Cancel while resizing, before the commit
# --------------------------------------------------------------------------- #


def test_cancel_during_the_resize_discards_the_staged_file_and_keeps_the_original(make_panel, tmp_path):
    panel, files, hashes, _asked = replace_panel(make_panel, tmp_path)
    staged_seen: list[bool] = []

    def after(n, _in, written):
        if n == 1:
            staged_seen.append(written.exists())     # the finished staging file exists at this very moment
            panel.cancel()

    seen = run_with_hook(panel, after_resize=after)

    assert staged_seen == [True], "the scenario must really cancel with a finished staged image on disk"
    assert [sha(f) for f in files] == hashes
    assert strays(tmp_path) == []
    assert seen == ["a.jpg"]
    assert state_of(panel) is jc.JobState.CANCELLED
    assert panel.jobs.status.view.completed == 0, "the aborted image is not counted as done"
    assert panel.run_result.not_attempted_count == 2 and panel.run_result.failed_count == 0


def test_cancel_during_the_resize_reports_the_truth_in_the_log(make_panel, tmp_path):
    panel, _files, _hashes, _asked = replace_panel(make_panel, tmp_path)
    run_with_hook(panel, after_resize=lambda n, *_: panel.cancel() if n == 1 else None)
    drain(panel)

    log = details_text(panel)
    assert "0 of 2 original(s) replaced" in log
    assert "Done" not in log.replace("All done", ""), "no ✓ Done line for an image that was never published"


# --------------------------------------------------------------------------- #
# C. Exactly one winner at the authorization
# --------------------------------------------------------------------------- #


def test_cancel_just_before_the_authorization_wins_and_nothing_is_replaced(make_panel, tmp_path, monkeypatch):
    panel, files, hashes, _asked = replace_panel(make_panel, tmp_path)
    real = jc.JobController.authorize_commit
    answers: list[bool] = []

    def cancel_first(controller):
        panel.cancel()
        granted = real(controller)
        answers.append(granted)
        return granted

    monkeypatch.setattr(jc.JobController, "authorize_commit", cancel_first)
    run_with_hook(panel)

    assert answers == [False], "Cancel took the lock first, so the authorization is refused"
    assert [sha(f) for f in files] == hashes
    assert strays(tmp_path) == []
    assert state_of(panel) is jc.JobState.CANCELLED


def test_cancel_just_after_the_authorization_loses_and_the_replacement_stands(make_panel, tmp_path, monkeypatch):
    panel, files, hashes, _asked = replace_panel(make_panel, tmp_path)
    real = jc.JobController.authorize_commit
    answers: list[bool] = []

    def commit_first(controller):
        granted = real(controller)
        answers.append(granted)
        if len(answers) == 1:
            panel.cancel()          # arrives with the commit already authorized: it lost, and the commit goes on
        return granted

    monkeypatch.setattr(jc.JobController, "authorize_commit", commit_first)
    seen = run_with_hook(panel)

    assert answers == [True], "the first image's commit won; the second image must never ask"
    with Image.open(files[0]) as img:
        assert img.size == (SIZE, SIZE), "a commit that won is never rolled back"
    assert sha(files[1]) == hashes[1], "the unreached image is untouched"
    assert seen == ["a.jpg"], "the remaining image is not started"
    assert state_of(panel) is jc.JobState.CANCELLED
    assert panel.run_result.succeeded_count == 1 and panel.run_result.cancelled is True
    assert strays(tmp_path) == []
    assert "1 of 2 original(s) replaced" in details_text(panel)


def test_every_authorization_is_given_back(make_panel, tmp_path, monkeypatch):
    """commit_finished pairs every grant, including a grant whose publication then failed."""
    panel, files, hashes, _asked = replace_panel(make_panel, tmp_path, count=2)
    granted = {"n": 0}
    finished = {"n": 0}
    real_authorize, real_finish = jc.JobController.authorize_commit, jc.JobController.commit_finished

    def authorize(controller):
        ok = real_authorize(controller)
        granted["n"] += int(ok)
        return ok

    def finish(controller):
        finished["n"] += 1
        return real_finish(controller)

    monkeypatch.setattr(jc.JobController, "authorize_commit", authorize)
    monkeypatch.setattr(jc.JobController, "commit_finished", finish)
    calls = {"n": 0}
    real_replace = op.atomic_replace

    def refuse_first(temporary, target):
        calls["n"] += 1
        if calls["n"] == 1:
            raise op.OutputPathError("replace refused", "test")
        return real_replace(temporary, target)

    monkeypatch.setattr(op, "atomic_replace", refuse_first)
    run_with_hook(panel)

    assert granted["n"] == finished["n"] == 2
    assert sha(files[0]) == hashes[0], "the refused replacement left the original"
    assert state_of(panel) is jc.JobState.COMPLETED_WITH_FAILURES


# --------------------------------------------------------------------------- #
# D. Cancel after a replacement completed
# --------------------------------------------------------------------------- #


def test_cancel_after_a_finished_replacement_keeps_it_and_stops_the_rest(make_panel, tmp_path):
    panel, files, hashes, _asked = replace_panel(make_panel, tmp_path, count=3)

    seen = run_with_hook(panel, before_resize=lambda n, *_: panel.cancel() if n == 2 else None)

    with Image.open(files[0]) as img:
        assert img.size == (SIZE, SIZE), "an earlier completed replacement is preserved"
    assert [sha(f) for f in files[1:]] == hashes[1:]
    assert seen == ["a.jpg", "b.jpg"], "the third image never starts"
    assert state_of(panel) is jc.JobState.CANCELLED
    assert panel.run_result.succeeded_count == 1 and panel.run_result.cancelled is True
    assert strays(tmp_path) == []
    assert "1 of 3 original(s) replaced" in details_text(panel)


def test_cancel_pressed_during_the_last_commit_does_not_undo_it(make_panel, tmp_path, monkeypatch):
    """Nothing is left to cancel once the last image is final: the work is complete and is reported as such."""
    panel, files, hashes, _asked = replace_panel(make_panel, tmp_path, count=1)
    real = jc.JobController.authorize_commit

    def commit_then_cancel(controller):
        granted = real(controller)
        panel.cancel()
        return granted

    monkeypatch.setattr(jc.JobController, "authorize_commit", commit_then_cancel)
    run_with_hook(panel)

    with Image.open(files[0]) as img:
        assert img.size == (SIZE, SIZE)
    assert state_of(panel) is jc.JobState.SUCCEEDED
    assert panel.run_result.succeeded_count == 1


# --------------------------------------------------------------------------- #
# E. Ordinary replacement, and the confirmation that guards it
# --------------------------------------------------------------------------- #


def test_a_normal_replacement_still_installs_a_valid_image_atomically(make_panel, tmp_path):
    panel, files, hashes, asked = replace_panel(make_panel, tmp_path)

    run_with_hook(panel)

    for original, before in zip(files, hashes):
        assert sha(original) != before
        with Image.open(original) as img:
            img.load()
            assert img.size == (SIZE, SIZE)
    assert asked == [2]
    assert state_of(panel) is jc.JobState.SUCCEEDED
    assert strays(tmp_path) == []
    assert sorted(p.name for p in (tmp_path / "art").iterdir()) == ["a.jpg", "b.jpg"]


def test_declining_the_confirmation_changes_nothing_and_starts_no_run(make_panel, tmp_path):
    files = [make_image(tmp_path / "art" / "a.jpg")]
    panel = make_panel()
    import_files(panel, *files)
    asked = arm_replacement(panel, answer=False)
    before = sha(files[0])

    seen = run_with_hook(panel)

    assert asked == [1] and seen == []
    assert sha(files[0]) == before
    assert strays(tmp_path) == []


# --------------------------------------------------------------------------- #
# F. Standard and numbered outputs: complete under a final name, or absent
# --------------------------------------------------------------------------- #


def test_standard_output_holds_no_final_name_while_the_image_is_being_written(make_panel, output_base, tmp_path):
    src = make_image(tmp_path / "art" / "a.jpg")
    panel = make_panel()
    import_files(panel, src)
    during: list[list[str]] = []

    def before(_n, _in, out_path):
        during.append(sorted(p.name for p in out_path.parent.iterdir() if not p.name.startswith(op.TEMP_SIBLING_PREFIX)))
        assert out_path.name.startswith(op.TEMP_SIBLING_PREFIX), "Pillow must be handed a staging path"

    run_with_hook(panel, before_resize=before)

    assert during == [[]], "no final-named file existed while the image was still being encoded"
    assert written_under(run_dir_of(output_base)) == ["a.jpg"]
    assert strays(output_base) == []
    with Image.open(run_dir_of(output_base) / "a.jpg") as img:
        assert img.size == (SIZE, SIZE)


def test_cancel_before_publication_leaves_no_standard_output_for_the_aborted_image(make_panel, output_base, tmp_path):
    panel = make_panel()
    import_files(panel, make_image(tmp_path / "art" / "a.jpg"), make_image(tmp_path / "art" / "b.jpg"))

    seen = run_with_hook(panel, after_resize=lambda n, *_: panel.cancel() if n == 2 else None)

    assert seen == ["a.jpg", "b.jpg"]
    assert written_under(run_dir_of(output_base)) == ["a.jpg"], "image 1 finished before Cancel; image 2 was never published"
    assert strays(output_base) == []
    assert state_of(panel) is jc.JobState.CANCELLED
    assert panel.run_result.succeeded_count == 1


def test_numbered_copies_are_named_beside_the_source_and_never_overwrite_it(make_panel, tmp_path):
    src = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(src)
    panel = make_panel()
    import_files(panel, src)
    panel.var_source_side.set(True)
    panel._on_source_side_change()
    panel.var_source_action.set(cr.ACTION_NUMBERED)

    run_with_hook(panel)

    assert sha(src) == before, "numbered mode never touches the input"
    names = sorted(p.name for p in (tmp_path / "art").iterdir())
    assert len(names) == 2 and "cover.jpg" in names, names
    other = next(n for n in names if n != "cover.jpg")
    with Image.open(tmp_path / "art" / other) as img:
        assert img.size == (SIZE, SIZE)
    assert state_of(panel) is jc.JobState.SUCCEEDED


def test_cancel_before_a_numbered_copy_is_published_leaves_only_the_source(make_panel, tmp_path):
    src = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(src)
    panel = make_panel()
    import_files(panel, src)
    panel.var_source_side.set(True)
    panel._on_source_side_change()
    panel.var_source_action.set(cr.ACTION_NUMBERED)

    run_with_hook(panel, after_resize=lambda n, *_: panel.cancel() if n == 1 else None)

    assert sorted(p.name for p in (tmp_path / "art").iterdir()) == ["cover.jpg"]
    assert sha(src) == before
    assert state_of(panel) is jc.JobState.CANCELLED


def test_a_numbered_name_taken_meanwhile_is_not_overwritten(make_panel, tmp_path, monkeypatch):
    """publish_new refuses a taken name: a file that appeared after planning stays exactly as it is."""
    src = make_image(tmp_path / "art" / "cover.jpg")
    panel = make_panel()
    import_files(panel, src)
    panel.var_source_side.set(True)
    panel._on_source_side_change()
    panel.var_source_action.set(cr.ACTION_NUMBERED)
    planned: list[Path] = []
    real_plan = op.SourceSidePlanner.plan_beside

    def remember(planner, source, **kwargs):
        planned.append(real_plan(planner, source, **kwargs))
        return planned[-1]

    monkeypatch.setattr(op.SourceSidePlanner, "plan_beside", remember)

    def occupy(*_):
        planned[0].write_bytes(b"someone else's file")

    run_with_hook(panel, before_resize=occupy)

    assert planned[0].read_bytes() == b"someone else's file", "the squatter's file was overwritten"
    assert strays(tmp_path) == []
    assert state_of(panel) is jc.JobState.COMPLETED_WITH_FAILURES
    assert panel.run_result.failed_count == 1


# --------------------------------------------------------------------------- #
# G. Pause is not Cancel
# --------------------------------------------------------------------------- #


def test_a_pause_pressed_mid_image_still_publishes_that_image_then_waits(make_panel, tmp_path, monkeypatch):
    runner = ThreadRunner()
    panel, files, hashes, _asked = replace_panel(make_panel, tmp_path, job_runner=runner)
    gate = Gate()
    monkeypatch.setattr(cr, "resize_for_audiobook", gate)

    start(panel, size=SIZE)
    gate.wait_for_entry(1)
    panel.pause()
    gate.let_through()
    wait_for_state(panel, jc.JobState.PAUSED)

    with Image.open(files[0]) as img:
        assert img.size == (SIZE, SIZE), "Pause lets the current image finish and publish"
    assert sha(files[1]) == hashes[1], "the next image waits"

    panel.resume()
    gate.let_through()
    runner.join()
    drain(panel)

    with Image.open(files[1]) as img:
        assert img.size == (SIZE, SIZE)
    assert gate.seen == ["a.jpg", "b.jpg"]
    assert state_of(panel) is jc.JobState.SUCCEEDED


def test_cancel_while_paused_wakes_the_worker_and_publishes_nothing_more(make_panel, tmp_path, monkeypatch):
    runner = ThreadRunner()
    panel, files, hashes, _asked = replace_panel(make_panel, tmp_path, job_runner=runner)
    gate = Gate()
    monkeypatch.setattr(cr, "resize_for_audiobook", gate)

    start(panel, size=SIZE)
    gate.wait_for_entry(1)
    panel.pause()
    gate.let_through()
    wait_for_state(panel, jc.JobState.PAUSED)
    panel.cancel()
    runner.join()
    drain(panel)

    assert state_of(panel) is jc.JobState.CANCELLED
    with Image.open(files[0]) as img:
        assert img.size == (SIZE, SIZE)
    assert sha(files[1]) == hashes[1]


# --------------------------------------------------------------------------- #
# H. Close / shutdown
# --------------------------------------------------------------------------- #


def test_closing_the_window_mid_image_cannot_replace_a_source_late(make_panel, tmp_path):
    panel, files, hashes, _asked = replace_panel(make_panel, tmp_path)

    run_with_hook(panel, after_resize=lambda n, *_: panel.close() if n == 1 else None)

    assert [sha(f) for f in files] == hashes, "a close that arrived before the commit forbids the commit"
    assert strays(tmp_path) == []
    assert state_of(panel) is jc.JobState.CANCELLED


# --------------------------------------------------------------------------- #
# No lock is held over the expensive work
# --------------------------------------------------------------------------- #


def test_the_controller_lock_is_not_held_while_an_image_is_resized(make_panel, tmp_path):
    """Cancel must stay answerable (and a snapshot readable) while the decode and encode run."""
    panel, files, _hashes, _asked = replace_panel(make_panel, tmp_path, count=1)
    probes: list[bool] = []

    def probe(_n, *_):
        # A fresh thread asks the controller for a snapshot with a bound: it can only answer if the lock is free.
        import threading

        answered = threading.Event()
        worker = threading.Thread(target=lambda: (panel.job_controller.snapshot(), answered.set()), daemon=True)
        worker.start()
        probes.append(answered.wait(2.0))
        worker.join(2.0)

    run_with_hook(panel, before_resize=probe)

    assert probes == [True]
