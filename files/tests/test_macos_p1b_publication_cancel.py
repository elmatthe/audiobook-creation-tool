"""v0.8.x P1B, CX-8 -- Cancel inside the publication window, in both orders (plan section 11.2.3).

The window runs from a Book's last staging step to the rename that gives its output the final name. The rule is the
tools' existing commit ordering: **nothing is published, or the whole Book is published and reported**. Never a part,
never a published file the run does not report, never a staged file left under a final name.

Driven with real FFmpeg on the adopted macOS build, through each tool's own engine (the MP3 Tool's ``write_id3_run`` and
``combine_run``, the M4B Maker's ``MakerRun``). Cancel is pressed at three exact points, by wrapping the step at that
point -- never by timing:

* before the last checkpoint ahead of the publish (Cancel wins: nothing is published, nothing is left in staging);
* after it, just before the rename (the rename is not interruptible: the Book is published whole and reported);
* just after the rename, before the run has reported it (published whole and reported).

On macOS the rename is ``renamex_np(RENAME_EXCL)`` (``output_paths.move_without_replacing``), and its file is checked
to be the very file that was staged.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

NATIVE_P1B = "native macOS only (P1B): Aqua Tk 9 shell, POSIX containment and macOS filesystem checks"
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason=NATIVE_P1B)

ORDERS = ("cancel-then-rename", "rename-then-cancel")


@pytest.fixture(autouse=True)
def _ffmpeg():
    from shared import ffmpeg_utils

    if not ffmpeg_utils.have_ffmpeg():
        pytest.fail("the adopted FFmpeg is not pinned in this checkout; set the app up before CX-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _finals(folder: Path) -> list[Path]:
    """Files under a final name: anything in the run folder outside the private work area."""
    if not folder.exists():
        return []
    return sorted(p for p in folder.rglob("*") if p.is_file() and ".work" not in p.relative_to(folder).parts)


class RenameWindow:
    """Wraps the one rename every publish goes through, and presses Cancel on the chosen side of the first one."""

    def __init__(self, monkeypatch, cancel, order: str) -> None:
        from shared import output_paths

        self.moves: list[tuple[Path, Path, str]] = []
        self.pressed = False
        real = output_paths.move_without_replacing

        def move(source, destination):
            digest = _sha(source)
            if order == "cancel-then-rename" and not self.pressed:
                self.pressed = True
                cancel()
            real(source, destination)
            self.moves.append((Path(source), Path(destination), digest))
            if order == "rename-then-cancel" and not self.pressed:
                self.pressed = True
                cancel()

        monkeypatch.setattr(output_paths, "move_without_replacing", move)

    def assert_whole(self) -> None:
        for _source, destination, digest in self.moves:
            assert destination.is_file() and _sha(destination) == digest, f"{destination.name} is not the staged file"


# --------------------------------------------------------------------------- #
#  The MP3 Tool
# --------------------------------------------------------------------------- #
def _mp3_two_books(tmp_path: Path, operation: str):
    import test_ffmpeg_cancel as cx
    import test_mp3_write_id3 as w3

    sources = tmp_path / "Sources"
    entries = [w3.book([w3.imported(sources, f"Book{n}", f"0{i} Part.mp3", freq=300 + 100 * i) for i in (1, 2)])
               for n in (1, 2)]
    space, store = w3.workspace(*entries), w3.observe(*entries)
    if operation == "combine":
        import test_mp3_combine as cm

        return cm.plan(space, store, cx._mp3_reserve(tmp_path)), sources
    return w3.plan(space, store, cx._mp3_reserve(tmp_path)), sources


def _mp3_engine(made):
    from mp3 import mp3_plan
    from mp3 import mp3_processing as proc

    return proc.combine_run if made.operation is mp3_plan.MP3Operation.COMBINE else proc.write_id3_run


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("operation", ["write", "combine"])
def test_mp3_cancel_at_the_rename_publishes_the_whole_book_reports_it_and_starts_no_other(tmp_path, monkeypatch,
                                                                                           operation, order):
    import test_ffmpeg_cancel as cx
    from mp3 import mp3_plan
    from shared.cancellation import ConversionCancelled
    from shared.job_control import JobController

    made, sources = _mp3_two_books(tmp_path, operation)
    before = cx.hashes(sources)
    controller = JobController("cx8-mp3")
    controller.start()
    window = RenameWindow(monkeypatch, controller.request_cancel, order)
    heard = []
    with pytest.raises(ConversionCancelled):
        _mp3_engine(made)(made, checkpoint=controller.checkpoint, cancel_check=controller.cancel_check,
                          on_book=heard.append)
    controller.finish_cancelled()
    mp3_plan.release_staging(made, keep=())  # the tool's own half after a Cancel (mp3_tool._worker)
    first, second = made.books
    planned = list(first.published_outputs)
    assert window.pressed and [m[1] for m in window.moves] == planned, "every output of the Book was renamed"
    window.assert_whole()
    assert [report.book_id for report in heard] == [first.book_id], "the published Book is reported, and only it"
    assert heard[0].succeeded and tuple(heard[0].published) == tuple(planned)
    assert _finals(made.run_directory) == sorted(planned), "nothing else is under a final name"
    assert not second.published_dir.exists() and not second.staging_dir.exists(), "the next Book never started"
    assert not made.work_root.exists(), "no private staging is left after the Cancel"
    assert cx.hashes(sources) == before


def test_mp3_cancel_before_the_last_checkpoint_publishes_nothing(tmp_path, monkeypatch):
    import test_ffmpeg_cancel as cx
    from mp3 import mp3_plan
    from mp3 import mp3_processing as proc
    from shared import output_paths
    from shared.cancellation import ConversionCancelled
    from shared.job_control import JobController

    made, sources = _mp3_two_books(tmp_path, "combine")
    before = cx.hashes(sources)
    controller = JobController("cx8-mp3-before")
    controller.start()
    real_validate = proc.validate_combined_book

    def validated_then_cancelled(*args, **kwargs):
        real_validate(*args, **kwargs)
        controller.request_cancel()  # every output staged and checked; the checkpoint ahead of the publish is next

    monkeypatch.setattr(proc, "validate_combined_book", validated_then_cancelled)
    renamed = []
    real_move = output_paths.move_without_replacing
    monkeypatch.setattr(output_paths, "move_without_replacing", lambda s, d: (renamed.append(d), real_move(s, d)))
    heard = []
    with pytest.raises(ConversionCancelled):
        proc.combine_run(made, checkpoint=controller.checkpoint, cancel_check=controller.cancel_check,
                         on_book=heard.append)
    controller.finish_cancelled()
    mp3_plan.release_staging(made, keep=())
    assert renamed == [] and heard == [], "nothing was published, so nothing is reported"
    assert _finals(made.run_directory) == []
    assert not made.work_root.exists()
    assert cx.hashes(sources) == before


# --------------------------------------------------------------------------- #
#  The M4B Maker
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("order", ORDERS)
def test_maker_cancel_at_the_rename_publishes_the_whole_book_reports_it_and_commits_its_number(tmp_path, monkeypatch,
                                                                                              order):
    import test_ffmpeg_cancel as cx
    import test_m4b_maker_batch as mt
    from m4b.maker import m4b_maker_plan as mkp
    from m4b.maker import m4b_maker_processing as mproc
    from shared.book_workspace import BookDisposition
    from shared.job_control import JobEventKind, JobState

    sources = tmp_path / "Sources"
    sources.mkdir()
    jobs = [mt.book(sources, f"B{index}", ("01.mp3", "02.mp3"), title=f"B{index}") for index in range(2)]
    made = mt.plan(mt.workspace(*jobs), cx._maker_reserve(tmp_path),
                   mkp.MakerRunOptions(auto_number=True, start_part_text="1"))
    run, events = mt.make_run(made)
    before = cx.hashes(sources)
    window = RenameWindow(monkeypatch, run.cancel, order)
    result = run.start().run()
    first, second = made.books
    assert window.pressed and [m[1] for m in window.moves] == [first.published]
    window.assert_whole()
    mproc.validate_staged_m4b(first, first.published)
    assert result.state is JobState.CANCELLED
    assert [d for _id, d in result.dispositions] == [BookDisposition.SUCCEEDED, BookDisposition.NOT_ATTEMPTED]
    assert not result.can_retry_failed
    locations = [Path(e.location) for e in events.seen if e.kind is JobEventKind.OUTPUT_LOCATION]
    assert first.published in locations, "the published Book is reported"
    assert set(locations) <= {first.published, made.destination.root}, "only it, beside the run folder itself"
    assert run.numbers.consumed == 1, "the published Book's Series Part is committed, and no other"
    assert _finals(made.destination.root) == [first.published]
    assert not second.published.exists() and not second.staging_dir.exists()
    assert not made.work_root.exists() or not any(made.work_root.iterdir())
    assert cx.hashes(sources) == before


def test_maker_cancel_before_the_last_checkpoint_publishes_nothing_and_commits_no_number(tmp_path, monkeypatch):
    import test_ffmpeg_cancel as cx
    from m4b.maker import m4b_maker_processing as mproc
    from shared import output_paths
    from shared.book_workspace import BookDisposition
    from shared.job_control import JobState

    made, run, sources = cx._maker_run(tmp_path, books=2)
    before = cx.hashes(sources)
    real_stage = mproc.stage_book

    def staged_then_cancelled(*args, **kwargs):
        outcome = real_stage(*args, **kwargs)
        run.cancel()  # the Book is staged and validated; the checkpoint ahead of the publish is next
        return outcome

    monkeypatch.setattr(mproc, "stage_book", staged_then_cancelled)
    renamed = []
    real_move = output_paths.move_without_replacing
    monkeypatch.setattr(output_paths, "move_without_replacing", lambda s, d: (renamed.append(d), real_move(s, d)))
    result = run.start().run()
    assert result.state is JobState.CANCELLED
    assert [d for _id, d in result.dispositions] == [BookDisposition.NOT_ATTEMPTED] * 2
    assert renamed == []
    for book in made.books:
        assert not book.published.exists() and not book.staging_dir.exists()
    assert not made.work_root.exists() or not any(made.work_root.iterdir())
    assert cx.hashes(sources) == before
