"""The Converter's last step: Cancel, validation, authorization, commit (v0.7.2 Phase 9, review findings P9-02 and P9-05).

The Phase 9 independent review drove the real Converter with real FFmpeg and found two things at the moment a finished
file gets its name:

* Cancel pressed while the finished file was being measured was followed by that file being published, and the run
  reported SUCCEEDED (P9-02). Nothing between the last process and the destination looked at Cancel.
* A file that took the planned name after the Converter had looked at it was replaced (P9-05). The look was
  ``exists()``; the move was ``os.replace``.

What must hold now, and what each section proves:

1. ``output_paths.publish_new`` gives a temporary file a new name only if the name is free, by one operation: no
   interleaving of writers can make it replace anything.
2. One segment: Cancel is asked again on both sides of the measurement, the commit is authorized in one step ordered
   against the Cancel latch, and only an authorized commit reaches the filesystem.
3. The panel, with its real worker thread, real controller and Cancel pressed on the main thread while the worker is
   held at an exact point: the run settles as what really happened, on the last book as on any other.
4. The same on real media through the real panel with the real FFmpeg, including the review's own scenario, and a
   control that takes the new ordering out and shows the journey then publishing after Cancel, as the reviewed
   candidate did.

Nothing here sleeps to make a race come out: the worker is stopped at a named point by an event and released by one.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
import threading
import unittest.mock as mock
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import job_control as jc  # noqa: E402
from shared import output_paths  # noqa: E402
from shared import subprocess_utils as sp  # noqa: E402
from shared.cancellation import ConversionCancelled  # noqa: E402

from m4b import m4b_execution  # noqa: E402
from m4b.converter import m4b_converter  # noqa: E402
from m4b.converter.m4b_metadata import MetadataMode  # noqa: E402
from m4b.converter.m4b_plan import ConversionMode  # noqa: E402
from m4b.m4b_execution import CommitGate, ProcessResult, SegmentWork, convert_segment  # noqa: E402

from test_m4b_continuous import _ThreadShim, make_book  # noqa: E402
from test_m4b_conversion_plan import StubThread, _reservation  # noqa: E402
from test_m4b_converter_importing import add_files, books  # noqa: E402
from test_m4b_converter_jobs import logger, make_panel, output_base, run_env, tk_root  # noqa: E402,F401  (fixtures)
from test_m4b_metadata import require_ffmpeg  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXECUTION_SOURCE = REPO_ROOT / "scripts" / "m4b" / "m4b_execution.py"

#: Every wait is bounded, so a defect fails rather than hangs.
WAIT = 20.0
#: The genuine thread class: ``run_env`` replaces the one the panel would start its worker with.
RealThread = threading.Thread
COMPETITOR = b"another program's file, written under the planned name"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def temporaries(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.rglob(f"{output_paths.TEMP_SIBLING_PREFIX}*"))


# --------------------------------------------------------------------------- #
# 1. The publication itself: a new name, or nothing
# --------------------------------------------------------------------------- #


def staged(folder: Path, content: bytes = b"the finished file") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = output_paths.temporary_sibling(folder / "Book.mp3", suffix=".mp3")
    path.write_bytes(content)
    return path


def test_a_free_name_is_given_and_the_temporary_name_is_gone(tmp_path):
    temporary = staged(tmp_path)
    destination = tmp_path / "Book.mp3"
    output_paths.publish_new(temporary, destination)
    assert destination.read_bytes() == b"the finished file"
    assert [path.name for path in tmp_path.iterdir()] == ["Book.mp3"]


def test_a_taken_name_is_refused_and_both_files_keep_their_bytes(tmp_path):
    temporary = staged(tmp_path)
    destination = tmp_path / "Book.mp3"
    destination.write_bytes(COMPETITOR)
    with pytest.raises(output_paths.DestinationOccupied) as refused:
        output_paths.publish_new(temporary, destination)
    assert "already exists" in refused.value.message
    assert destination.read_bytes() == COMPETITOR, "the file that was there is exactly as it was"
    assert temporary.read_bytes() == b"the finished file", "and the finished file is still its owner's, to discard"


def test_a_name_taken_by_a_folder_is_refused_too(tmp_path):
    temporary = staged(tmp_path)
    destination = tmp_path / "Book.mp3"
    destination.mkdir()
    (destination / "inside.txt").write_text("kept", encoding="utf-8")
    with pytest.raises(output_paths.OutputPathError):
        output_paths.publish_new(temporary, destination)
    assert (destination / "inside.txt").read_text(encoding="utf-8") == "kept" and temporary.exists()


def test_only_a_plan_owned_temporary_file_may_be_published(tmp_path):
    ordinary = tmp_path / "someones.mp3"
    ordinary.write_bytes(b"a user's file")
    with pytest.raises(output_paths.UnsafePathError):
        output_paths.publish_new(ordinary, tmp_path / "Book.mp3")
    assert ordinary.read_bytes() == b"a user's file" and not (tmp_path / "Book.mp3").exists()


def test_eight_writers_racing_for_one_name_have_exactly_one_winner_every_time(tmp_path):
    """The property a look followed by a move does not have, shown without relying on who is quickest: whatever the
    interleaving, one writer's file takes the name whole, and every other writer is refused with its file intact."""
    for round_number in range(25):
        folder = tmp_path / f"round-{round_number}"
        destination = folder / "Book.mp3"
        entries = [staged(folder, f"writer {index}".encode()) for index in range(8)]
        barrier = threading.Barrier(len(entries))
        results: list = [None] * len(entries)

        def publish(index: int) -> None:
            barrier.wait(WAIT)
            try:
                output_paths.publish_new(entries[index], destination)
                results[index] = "won"
            except output_paths.DestinationOccupied:
                results[index] = "refused"

        threads = [RealThread(target=publish, args=(index,)) for index in range(len(entries))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(WAIT)
        assert results.count("won") == 1 and results.count("refused") == 7, (round_number, results)
        winner = results.index("won")
        assert destination.read_bytes() == f"writer {winner}".encode(), "the name holds the winner's bytes, whole"
        assert not entries[winner].exists()
        assert all(entries[index].read_bytes() == f"writer {index}".encode() for index in range(8) if index != winner)


def test_a_look_followed_by_a_replace_loses_the_other_writers_file_and_the_publication_does_not(tmp_path):
    """The reviewed candidate's sequence against the new one, at the same interleaving: the name is free when it is
    looked at, and taken before the move."""
    def taken_after_the_look(publish) -> bytes:
        folder = tmp_path / publish.__name__
        temporary, destination = staged(folder), folder / "Book.mp3"
        assert not destination.exists(), "the look: the name is free"
        destination.write_bytes(COMPETITOR)  # the other writer, between the look and the move
        try:
            publish(temporary, destination)
        except output_paths.DestinationOccupied:
            pass
        return destination.read_bytes()

    assert taken_after_the_look(output_paths.atomic_replace) == b"the finished file", "the control: replaced"
    assert taken_after_the_look(output_paths.publish_new) == COMPETITOR


def test_replacing_a_file_in_place_is_still_what_atomic_replace_does_and_only_it(tmp_path):
    """The confirmed in-place replacement (Cover Image, the Metadata Editor) keeps its operation; the Converter's segment
    does not use it."""
    temporary = staged(tmp_path, b"the new version")
    original = tmp_path / "Book.mp3"
    original.write_bytes(b"the old version")
    output_paths.atomic_replace(temporary, original)
    assert original.read_bytes() == b"the new version"
    tree = ast.parse(EXECUTION_SOURCE.read_text(encoding="utf-8"))
    segment = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "convert_segment")
    called = {node.attr for node in ast.walk(segment) if isinstance(node, ast.Attribute)}
    assert "publish_new" in called and "atomic_replace" not in called and "replace" not in called


# --------------------------------------------------------------------------- #
# 2. One segment: the order
# --------------------------------------------------------------------------- #


class Latch:
    """The low-level Cancel latch a segment is polled against."""

    def __init__(self) -> None:
        self.cancelled = False

    def __call__(self) -> bool:
        return self.cancelled


def whole_work(tmp_path: Path) -> SegmentWork:
    source = tmp_path / "src" / "Book.m4b"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("not an audiobook", encoding="utf-8")
    return SegmentWork(source=source, destination=tmp_path / "run" / "Book.mp3", expected_duration=600.0, quality=2,
                       metadata_mode=MetadataMode.PRESERVE, tags={"album": "A"})


def run_segment(work, *, latch=None, measure=lambda path: None, commit=None, as_the_pass_ends=None, events=None):
    """``convert_segment`` with the one function that starts a process replaced, and nothing else."""
    latch = latch or Latch()

    def fake_run(argv, *, cancelled, workspace, **kwargs):
        if cancelled():
            return ProcessResult(None, cancelled=True)
        if events is not None:
            events.append("pass")
        if as_the_pass_ends is not None:
            as_the_pass_ends()
        return ProcessResult(0)  # the process ended by itself: it reports no cancellation of its own

    with mock.patch.object(m4b_execution, "run_argv", fake_run):
        return convert_segment(work, ffmpeg="ffmpeg", cancelled=latch, measure=measure, commit=commit)


def controller_gate(controller, events=None) -> CommitGate:
    def authorize() -> bool:
        granted = controller.authorize_commit()
        if events is not None:
            events.append("authorized" if granted else "denied")
        return granted

    def finished() -> None:
        controller.commit_finished()
        if events is not None:
            events.append("given back")

    return CommitGate(authorize=authorize, finished=finished)


def running_controller() -> jc.JobController:
    controller = jc.JobController("order-run")
    controller.start()
    return controller


def recording_publication(monkeypatch, events, before=None):
    real = output_paths.publish_new

    def publish_new(temporary, destination):
        if before is not None:
            before(Path(destination))
        events.append("publish")
        return real(temporary, destination)

    monkeypatch.setattr(output_paths, "publish_new", publish_new)


def test_the_control_with_no_cancel_the_steps_come_in_one_order_and_the_file_is_published(tmp_path, monkeypatch):
    work, controller, events = whole_work(tmp_path), running_controller(), []
    recording_publication(monkeypatch, events)
    outcome = run_segment(work, commit=controller_gate(controller, events), events=events,
                          measure=lambda path: events.append("measure"))
    assert outcome.finalised and not outcome.cancelled
    assert events == ["pass", "measure", "authorized", "publish", "given back"]
    assert [path.name for path in work.destination.parent.iterdir()] == ["Book.mp3"]
    assert controller.commits_in_flight == 0


def test_a_cancel_that_lands_as_the_last_pass_ends_by_itself_publishes_nothing(tmp_path):
    """The process was already gone, so it reports no cancellation; until Phase 9 nothing else asked."""
    work, latch, measured = whole_work(tmp_path), Latch(), []
    outcome = run_segment(work, latch=latch, as_the_pass_ends=lambda: setattr(latch, "cancelled", True),
                          measure=lambda path: measured.append(path))
    assert outcome.cancelled and not outcome.finalised and not outcome.failed
    assert measured == [], "a cancelled segment is not measured either"
    assert list(work.destination.parent.iterdir()) == [], "no output and no temporary file"


@pytest.mark.parametrize("gated", [False, True], ids=["no-gate", "with-the-controllers-gate"])
def test_a_cancel_during_the_final_validation_publishes_nothing(tmp_path, monkeypatch, gated):
    """The review's scenario, at the segment: the latch is set while the finished file is being measured."""
    work, latch, controller, events = whole_work(tmp_path), Latch(), running_controller(), []
    recording_publication(monkeypatch, events)

    def measure(path):
        assert Path(path).is_file() and not work.destination.exists()
        latch.cancelled = True
        return 600.0  # a perfectly good measurement: only the Cancel stands between this file and its name

    outcome = run_segment(work, latch=latch, measure=measure, events=events,
                          commit=controller_gate(controller, events) if gated else None)
    assert outcome.cancelled and not outcome.finalised
    assert events == ["pass"], "no authorization was asked for and nothing reached the filesystem"
    assert list(work.destination.parent.iterdir()) == []


def test_a_cancel_immediately_before_the_authorization_is_the_one_that_came_first(tmp_path, monkeypatch):
    """Cancel takes the controller's lock, then the commit asks: denied, in one step, with nothing recorded in flight."""
    work, controller, events = whole_work(tmp_path), running_controller(), []
    recording_publication(monkeypatch, events)
    real = controller_gate(controller, events)

    def authorize() -> bool:
        controller.request_cancel()  # the last instant before the commit asks
        return real.authorize()

    outcome = run_segment(work, commit=CommitGate(authorize=authorize, finished=real.finished), events=events)
    assert outcome.cancelled and not outcome.finalised
    assert events == ["pass", "denied"] and controller.commits_in_flight == 0
    assert list(work.destination.parent.iterdir()) == []


def test_a_cancel_immediately_before_the_filesystem_commit_has_lost_and_can_see_what_it_lost_to(tmp_path, monkeypatch):
    """The other order: the commit was authorized first. The Cancel that follows can read that one commit is landing, the
    run cannot be reported cancelled while it is, and the file is published whole and stays."""
    work, controller, events, seen = whole_work(tmp_path), running_controller(), [], {}

    def cancel_now(destination: Path) -> None:
        controller.request_cancel()
        seen["in_flight"] = controller.commits_in_flight
        with pytest.raises(ConversionCancelled):
            controller.checkpoint()  # the worker's own acknowledgement of that Cancel
        with pytest.raises(jc.JobContractError, match="may still become final"):
            controller.finish_cancelled()
        seen["destination_existed"] = destination.exists()

    recording_publication(monkeypatch, events, before=cancel_now)
    outcome = run_segment(work, commit=controller_gate(controller, events), events=events)
    assert outcome.finalised and not outcome.cancelled
    assert seen == {"in_flight": 1, "destination_existed": False}
    assert events == ["pass", "authorized", "publish", "given back"] and controller.commits_in_flight == 0
    assert [path.name for path in work.destination.parent.iterdir()] == ["Book.mp3"]


def test_a_name_taken_at_the_commit_is_refused_keeps_its_bytes_and_gives_the_authorization_back(tmp_path, monkeypatch):
    """After the look, after the authorization, in the instant before the operation: the file that appears is not replaced."""
    work, controller, events = whole_work(tmp_path), running_controller(), []
    recording_publication(monkeypatch, events, before=lambda destination: destination.write_bytes(COMPETITOR))
    outcome = run_segment(work, commit=controller_gate(controller, events), events=events)
    assert outcome.failed and not outcome.finalised and not outcome.cancelled
    assert "already exists" in outcome.message and "occupied after the run was planned" in outcome.detail
    assert work.destination.read_bytes() == COMPETITOR
    assert [path.name for path in work.destination.parent.iterdir()] == ["Book.mp3"], "the finished file was discarded"
    assert events == ["pass", "authorized", "publish", "given back"] and controller.commits_in_flight == 0


def test_a_publication_the_filesystem_refuses_still_gives_the_authorization_back(tmp_path, monkeypatch):
    work, controller = whole_work(tmp_path), running_controller()

    def full_disk(temporary, destination):
        raise output_paths.OutputPathError("Book.mp3 could not be saved", "OSError: [Errno 28] No space left on device")

    monkeypatch.setattr(output_paths, "publish_new", full_disk)
    with pytest.raises(output_paths.OutputPathError):
        run_segment(work, commit=controller_gate(controller))
    assert controller.commits_in_flight == 0, "an attempt that failed cannot be mistaken for one that may still land"
    assert list(work.destination.parent.iterdir()) == [], "and its temporary file is gone with it"


# --------------------------------------------------------------------------- #
# 3. The panel: a real worker thread, a real controller, Cancel on the main thread
# --------------------------------------------------------------------------- #


class Hold:
    """Stops the worker inside one call, at its *nth* use, until the main thread lets it go."""

    def __init__(self, nth: int = 1, result=None) -> None:
        self.nth, self.result, self.calls = nth, result, 0
        self.entered, self.release = threading.Event(), threading.Event()

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls == self.nth:
            self.entered.set()
            assert self.release.wait(WAIT), "the worker was never released"
        return self.result(*args, **kwargs) if callable(self.result) else self.result


def start(panel):
    panel.start_convert()
    assert StubThread.started, "the worker was never handed a run"
    return StubThread.started[-1].args[0]


def work_on_a_thread(panel, params, folder: Path, while_it_works) -> None:
    """The worker on a thread of its own, as in the application; *while_it_works* runs here, on the Tk thread."""
    with mock.patch.object(output_paths, "reserve_run_directory", side_effect=_reservation(folder)):
        worker = RealThread(target=panel.convert_worker, args=(params,), name="m4b-order")
        worker.start()
        try:
            while_it_works()
        finally:
            worker.join(WAIT)
        assert not worker.is_alive(), "the worker did not settle"
    panel._pump.tick()


def press_cancel_while_held(panel, hold: Hold) -> None:
    assert hold.entered.wait(WAIT), "the worker never reached the point it was to be held at"
    panel.cancel()  # on the main thread, as the button does
    assert panel._cancel_event.is_set() and panel.job_controller.cancel_check(), "Cancel is latched before the worker goes on"
    hold.release.set()


def destinations(panel) -> list[Path]:
    return [item.segments[0].destination for item in panel.run_plan.items]


@pytest.mark.parametrize("held_book, kept", [(1, []), (2, ["A.m4b"]), (3, ["A.m4b", "B.m4b"])],
                         ids=["the-first-book", "a-middle-book", "the-last-book"])
def test_cancel_during_a_books_final_validation_cancels_the_run_and_keeps_only_what_was_already_finished(
        make_panel, tmp_path, run_env, monkeypatch, held_book, kept):
    """The last book is not an exception: before Phase 9 its output was published and the run said SUCCEEDED."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    sources = {path.name: digest(path) for path in (tmp_path / "src").iterdir()}
    stranger = tmp_path / "a-file-of-someone-elses.txt"
    stranger.write_text("not this run's", encoding="utf-8")
    params = start(panel)
    hold = Hold(nth=held_book)
    monkeypatch.setattr(m4b_converter, "measured_duration", hold)

    work_on_a_thread(panel, params, tmp_path, lambda: press_cancel_while_held(panel, hold))

    assert panel.job_controller.state is jc.JobState.CANCELLED
    assert panel.run_result.cancelled is True
    planned = destinations(panel)
    assert [path.name for path in planned if path.exists()] == [Path(name).with_suffix(".mp3").name for name in kept]
    assert temporaries(tmp_path) == [], "the held book's finished file was discarded, not published"
    assert len(run_env["commands"]) == held_book, "no book was started after the Cancel"
    assert hold.calls == held_book
    assert {path.name: digest(path) for path in (tmp_path / "src").iterdir()} == sources
    assert stranger.read_text(encoding="utf-8") == "not this run's"
    assert panel.job_controller.commits_in_flight == 0


def test_pause_during_the_final_validation_publishes_that_output_and_only_then_pauses(
        make_panel, tmp_path, run_env, monkeypatch):
    """Pause is not Cancel: the output in hand is finished and published, and the run waits before the next book."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    params = start(panel)
    hold = Hold(nth=1)
    monkeypatch.setattr(m4b_converter, "measured_duration", hold)

    def pause_then_resume() -> None:
        assert hold.entered.wait(WAIT)
        panel.pause()
        assert panel.job_controller.state is jc.JobState.PAUSE_REQUESTED
        hold.release.set()
        waiter = threading.Event()
        for _ in range(int(WAIT * 200)):
            if panel.job_controller.state is jc.JobState.PAUSED:
                break
            waiter.wait(0.005)
        assert panel.job_controller.state is jc.JobState.PAUSED, "a pause is acknowledged, never turned into a cancel"
        panel._pump.tick()  # the plan reaches the panel through its queue, as it does while the application runs
        first, second = destinations(panel)
        assert first.exists() and not second.exists(), "the output in hand was published; the next book has not begun"
        assert len(run_env["commands"]) == 1 and panel.job_controller.cancel_check() is False
        panel.resume()

    work_on_a_thread(panel, params, tmp_path, pause_then_resume)
    assert panel.job_controller.state is jc.JobState.SUCCEEDED
    assert all(path.exists() for path in destinations(panel))


@pytest.mark.parametrize("held_book, state, published", [(1, jc.JobState.CANCELLED, ["A.mp3"]),
                                                         (2, jc.JobState.SUCCEEDED, ["A.mp3", "B.mp3"])],
                         ids=["a-book-with-another-after-it", "the-last-book"])
def test_a_cancel_between_the_authorization_and_the_commit_has_lost_to_that_one_output(
        make_panel, tmp_path, run_env, monkeypatch, held_book, state, published):
    """The commit was authorized before the Cancel, so that output is published whole and stays, as every output finished
    before a Cancel stays. Nothing after it starts. On the last book there is nothing left to cancel: the run succeeded."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    params = start(panel)
    real = output_paths.publish_new
    hold = Hold(nth=held_book, result=real)
    monkeypatch.setattr(output_paths, "publish_new", hold)
    seen = {}

    def cancel_inside_the_commit() -> None:
        assert hold.entered.wait(WAIT)
        seen["in_flight"] = panel.job_controller.commits_in_flight
        panel.cancel()
        seen["latched"] = panel.job_controller.cancel_check()
        hold.release.set()

    work_on_a_thread(panel, params, tmp_path, cancel_inside_the_commit)
    assert seen == {"in_flight": 1, "latched": True}
    assert panel.job_controller.state is state
    assert sorted(path.name for path in destinations(panel) if path.exists()) == published
    assert len(run_env["commands"]) == held_book, "no book was started after the Cancel"
    assert temporaries(tmp_path) == [] and panel.job_controller.commits_in_flight == 0


def test_a_cancel_after_the_last_output_was_published_leaves_it_and_the_run_succeeded(
        make_panel, tmp_path, run_env, monkeypatch):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    params = start(panel)
    real = output_paths.publish_new
    published, release = threading.Event(), threading.Event()

    def publish_new(temporary, destination):
        real(temporary, destination)
        published.set()
        assert release.wait(WAIT)

    monkeypatch.setattr(output_paths, "publish_new", publish_new)

    def cancel_afterwards() -> None:
        assert published.wait(WAIT)
        panel._pump.tick()
        assert destinations(panel)[0].exists()
        panel.cancel()
        release.set()

    work_on_a_thread(panel, params, tmp_path, cancel_afterwards)
    assert panel.job_controller.state is jc.JobState.SUCCEEDED
    assert destinations(panel)[0].exists(), "a file legitimately published before the Cancel is never taken back"


class Contended:
    """The panel's decision lock, saying when another thread has had to wait for it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.waited = threading.Event()

    def __enter__(self):
        if not self._lock.acquire(blocking=False):
            self.waited.set()
            self._lock.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self._lock.release()


def test_cancel_pressed_while_a_publication_is_being_authorized_waits_for_that_decision_and_the_commit_stays(
        make_panel, tmp_path, run_env, monkeypatch):
    """v0.7.2 Phase 9 remote re-review R9-04, the reviewer's interleaving on the real panel: the worker has read the
    Cancel latch clear and is inside the controller's authorization when Cancel is pressed. Until then Cancel set its
    latch at once and the authorization that followed was granted with the latch already set ("controller authorized
    True with event True"). The latch and the decision now share one lock: Cancel waits the moment the decision takes,
    the commit that came first is published whole and stays, and nothing after it starts. The worker is let go only by
    Cancel having to wait, so a Cancel that does not wait leaves it held and fails this, with no sleep."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    params = start(panel)
    decision = panel._cancel_decision = Contended()
    real = jc.JobController.authorize_commit
    inside, decided = threading.Event(), []

    def authorize_commit(controller) -> bool:
        if not decided:
            inside.set()
            assert decision.waited.wait(WAIT), "Cancel latched without waiting for the authorization under way"
        granted = real(controller)
        decided.append((granted, panel._cancel_event.is_set()))
        return granted

    monkeypatch.setattr(jc.JobController, "authorize_commit", authorize_commit)

    def cancel_during_the_authorization() -> None:
        assert inside.wait(WAIT), "the worker never reached the authorization"
        panel.cancel()  # on the main thread, as the button does; returns once the decision under way is made
        assert decision.waited.is_set(), "Cancel latched without waiting for the authorization under way"
        assert panel._cancel_event.is_set() and panel.job_controller.cancel_check()

    work_on_a_thread(panel, params, tmp_path, cancel_during_the_authorization)
    assert decided == [(True, False)], "granted, and only ever with the latch still clear"
    assert panel.job_controller.state is jc.JobState.CANCELLED
    assert [path.name for path in destinations(panel) if path.exists()] == ["A.mp3"]
    assert len(run_env["commands"]) == 1, "no book was started after the Cancel"
    assert temporaries(tmp_path) == [] and panel.job_controller.commits_in_flight == 0


def test_a_cancel_latched_before_the_controller_hears_of_it_already_refuses_the_next_authorization(
        make_panel, tmp_path, run_env, monkeypatch):
    """The other side of the same boundary, in the reviewer's order: Cancel's latch is set, the worker then asks to
    publish before the controller has heard of the Cancel, and only then does the controller hear. The latch decides:
    the authorization is refused, nothing is published, and the run is cancelled."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    params = start(panel)
    held, decided, made = Hold(nth=1), [], threading.Event()
    real_gate = m4b_execution.CommitGate

    def gate(*, authorize, finished):
        def held_then_authorize() -> bool:
            held()  # after the segment's last look at Cancel, before the decision
            granted = authorize()
            decided.append(granted)
            made.set()
            return granted
        return real_gate(authorize=held_then_authorize, finished=finished)

    monkeypatch.setattr(m4b_execution, "CommitGate", gate)
    real_request = jc.JobController.request_cancel

    def request_cancel(controller):
        held.release.set()  # the latch is set; the worker decides before the controller hears of the Cancel
        assert made.wait(WAIT), "the worker never decided"
        return real_request(controller)

    monkeypatch.setattr(jc.JobController, "request_cancel", request_cancel)

    def cancel_before_the_decision() -> None:
        assert held.entered.wait(WAIT), "the worker never reached the decision"
        panel.cancel()

    work_on_a_thread(panel, params, tmp_path, cancel_before_the_decision)
    assert decided == [False], "the latch came first, so the decision was a refusal"
    assert panel.job_controller.state is jc.JobState.CANCELLED
    assert [path for path in destinations(panel) if path.exists()] == []
    assert temporaries(tmp_path) == [] and panel.job_controller.commits_in_flight == 0
    assert len(run_env["commands"]) == 1


def test_a_name_taken_at_the_commit_during_retry_failed_is_refused_and_the_plan_does_not_move(
        make_panel, tmp_path, run_env, monkeypatch):
    """Retry Failed repeats a frozen plan. A stranger's file at the frozen name, appearing in the instant before the
    retry's commit, is kept; the book fails again at the same name; and once the name is free the retry lands there."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    params = start(panel)
    with mock.patch.object(output_paths, "reserve_run_directory", side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()
    assert panel.run_result.state is jc.JobState.COMPLETED_WITH_FAILURES
    first, second = destinations(panel)
    assert first.exists() and not second.exists()
    finished_book = digest(first)

    def retry() -> None:
        assert panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED) is True, "Retry Failed was not available"
        with mock.patch.object(output_paths, "reserve_run_directory",
                               side_effect=AssertionError("a retry reserved a run directory")):
            panel.convert_worker(StubThread.started[-1].args[0])
        panel._pump.tick()

    run_env["fail"] = ()
    real = output_paths.publish_new

    def taken_at_the_commit(temporary, destination):
        Path(destination).write_bytes(COMPETITOR)
        return real(temporary, destination)

    monkeypatch.setattr(output_paths, "publish_new", taken_at_the_commit)
    retry()
    assert panel.run_result.state is jc.JobState.COMPLETED_WITH_FAILURES
    assert second.read_bytes() == COMPETITOR, "the stranger's file is byte for byte what it wrote"
    assert destinations(panel) == [first, second], "the frozen plan was not renumbered around the collision"
    assert digest(first) == finished_book, "the book that had finished is untouched"
    assert temporaries(tmp_path) == []
    failure = panel.run_result.failures.records[-1]
    assert "already exists" in failure.display_message and failure.retryable is True

    monkeypatch.setattr(output_paths, "publish_new", real)
    second.unlink()  # the person moves the stranger's file away and presses Retry Failed again
    retry()
    assert panel.run_result.state is jc.JobState.SUCCEEDED
    assert second.exists() and second.read_bytes() != COMPETITOR and digest(first) == finished_book


# --------------------------------------------------------------------------- #
# 4. Real media: the real panel, the real FFmpeg, Cancel on the main thread
# --------------------------------------------------------------------------- #

CHAPTERS_MS = (1500, 1400, 1600)


@pytest.fixture(scope="module")
def real_book(tmp_path_factory) -> Path:
    require_ffmpeg()
    return make_book(tmp_path_factory.mktemp("order_media"), "Ordered", cover=False, lengths=CHAPTERS_MS)


@pytest.fixture()
def real_run(make_panel, monkeypatch, real_book):
    """The real panel on real media. Only the thread the panel would start is replaced, so the test can start that same
    worker itself and act on the main thread while it runs; every probe, plan, FFmpeg pass and measurement is real."""
    StubThread.started = []
    monkeypatch.setattr(m4b_converter, "threading", _ThreadShim())
    monkeypatch.setattr(m4b_converter.sp, "reveal_in_file_manager", lambda target: None)
    children: list = []
    real_popen = sp.popen

    def popen(cmd, **kwargs):
        proc = real_popen(cmd, **kwargs)
        children.append(([str(part) for part in cmd], proc))
        return proc

    monkeypatch.setattr(sp, "popen", popen)

    def run(folder: Path, mode: ConversionMode, while_it_works=lambda: None):
        panel = make_panel()
        add_files(panel, real_book)
        panel.var_mode.set(mode.value)
        work_on_a_thread(panel, start(panel), folder, while_it_works)
        assert all(proc.poll() is not None for _cmd, proc in children), "a child of the run is still running"
        return panel, children

    return run


def outputs(panel) -> list[Path]:
    """Published MP3s: a file still under its temporary name is not an output."""
    return sorted(path for path in panel.run_plan.run_directory.rglob("*.mp3")
                  if not path.name.startswith(output_paths.TEMP_SIBLING_PREFIX))


def test_the_control_the_real_journey_without_a_cancel_publishes_a_whole_book(real_run, real_book, tmp_path):
    panel, children = real_run(tmp_path, ConversionMode.WHOLE)
    assert panel.run_result.state is jc.JobState.SUCCEEDED, list(panel.log.details)[-6:]
    book, = outputs(panel)
    assert abs(m4b_converter.measured_duration(book) - sum(CHAPTERS_MS) / 1000) < 0.2
    assert temporaries(tmp_path) == [] and children, "real FFmpeg ran"


def held_validation(monkeypatch, nth: int = 1) -> tuple[Hold, dict]:
    """The real measurement, entered and then held: Cancel is latched while the validation is in progress, and the real
    measurement then runs to its end on the finished file."""
    real = m4b_converter.measured_duration
    measured: dict = {}

    def measure(path):
        measured["staged_bytes"] = Path(path).stat().st_size
        measured["seconds"] = real(path)
        return measured["seconds"]

    hold = Hold(nth=nth, result=measure)
    monkeypatch.setattr(m4b_converter, "measured_duration", hold)
    return hold, measured


def test_the_journey_cancel_on_the_main_thread_during_the_real_final_validation_publishes_nothing(
        real_run, real_book, tmp_path, monkeypatch):
    """The Phase 9 reviewer's journey. A real book, the real panel, real FFmpeg. The encode finishes by itself; while the
    finished file is being measured the Cancel button's own method runs on the main thread and latches; the measurement
    then completes and is a good one. The reviewed candidate published the file and reported SUCCEEDED."""
    source_before = digest(real_book)
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        hold, measured = held_validation(monkeypatch)
        panel, children = real_run(tmp_path, ConversionMode.WHOLE, lambda: press_cancel_while_held(panel_of(), hold))
        assert measured["staged_bytes"] > 10_000 and abs(measured["seconds"] - sum(CHAPTERS_MS) / 1000) < 0.2, \
            "the file Cancel stopped was a whole, valid encode: only the Cancel kept it from being published"
        assert panel.job_controller.state is jc.JobState.CANCELLED
        assert panel.run_result.cancelled is True and panel.run_result.state is not jc.JobState.SUCCEEDED
        assert outputs(panel) == [], "nothing was published after the Cancel"
        assert temporaries(tmp_path) == [], "and the finished file was discarded"
        assert any(proc.returncode == 0 for _cmd, proc in children), "the encode had finished by itself"
        assert digest(real_book) == source_before
        assert sentinel.poll() is None, "an unrelated process is untouched"
    finally:
        sentinel.kill()
        sentinel.wait(WAIT)


def panel_of():
    """The panel of the run in progress: the one ``start`` handed its worker's parameters to."""
    return StubThread.started[-1].target.__self__


def test_the_same_journey_with_the_new_ordering_taken_out_publishes_after_cancel_as_the_reviewed_candidate_did(
        real_run, real_book, tmp_path, monkeypatch):
    """The negative control of the journey above. The segment is run as it was before Phase 9: nothing looks at Cancel
    once the last process has ended, and there is no authorization. Same book, same Cancel at the same point: the file is
    published and the run says SUCCEEDED, which is the review's finding P9-02. So the journey above passes because of the
    ordering, and would fail without it."""
    real_convert = m4b_execution.convert_segment

    def as_before_phase_9(work, **kwargs):
        kwargs.pop("commit", None)
        latch, measure, measuring = kwargs["cancelled"], kwargs["measure"], []

        def measured(path):
            measuring.append(path)
            return measure(path)

        kwargs.update(measure=measured, cancelled=lambda: False if measuring else latch())
        return real_convert(work, **kwargs)

    monkeypatch.setattr(m4b_execution, "convert_segment", as_before_phase_9)
    hold, measured = held_validation(monkeypatch)
    panel, _children = real_run(tmp_path, ConversionMode.WHOLE, lambda: press_cancel_while_held(panel_of(), hold))
    assert panel.job_controller.cancel_check() is True, "the Cancel was pressed and latched all the same"
    assert panel.job_controller.state is jc.JobState.SUCCEEDED
    assert len(outputs(panel)) == 1, "published after Cancel"


def test_a_cancel_during_a_later_chapters_validation_takes_the_whole_real_book_back(real_run, real_book, tmp_path, monkeypatch):
    """Split by chapter: the first chapter was published before the Cancel, and a partly split book must not stay."""
    hold, _measured = held_validation(monkeypatch, nth=2)
    seen = {}

    def cancel_in_the_second_chapter() -> None:
        assert hold.entered.wait(WAIT)
        panel_of()._pump.tick()
        seen["published_before"] = len(outputs(panel_of()))
        press_cancel_while_held(panel_of(), hold)

    panel, _children = real_run(tmp_path, ConversionMode.SPLIT, cancel_in_the_second_chapter)
    assert seen == {"published_before": 1}, "the first chapter really was published when Cancel was pressed"
    assert panel.job_controller.state is jc.JobState.CANCELLED
    assert outputs(panel) == [] and temporaries(tmp_path) == []
    assert [path for path in panel.run_plan.run_directory.iterdir()] == [], "and the book's own folder went with it"


def test_a_file_that_takes_the_name_while_a_real_output_is_being_published_is_kept(real_run, real_book, tmp_path, monkeypatch):
    """The review's second scenario on real media: the name is free when it is looked at and taken at the commit."""
    source_before = digest(real_book)
    real = output_paths.publish_new
    taken = {}

    def taken_at_the_commit(temporary, destination):
        assert not Path(destination).exists(), "the Converter's own look found the name free"
        Path(destination).write_bytes(COMPETITOR)
        taken["sha256"] = digest(Path(destination))
        return real(temporary, destination)

    monkeypatch.setattr(output_paths, "publish_new", taken_at_the_commit)
    panel, _children = real_run(tmp_path, ConversionMode.WHOLE)
    assert panel.run_result.state is jc.JobState.FAILED or panel.run_result.state is jc.JobState.COMPLETED_WITH_FAILURES
    occupant, = outputs(panel)
    assert digest(occupant) == taken["sha256"] and occupant.read_bytes() == COMPETITOR
    assert temporaries(tmp_path) == [] and digest(real_book) == source_before
    assert "already exists" in panel.run_result.failures.records[-1].display_message
