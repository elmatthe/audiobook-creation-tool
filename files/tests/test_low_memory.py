"""Running out of memory, and stalling, on the Edge routes: every run ends, with a reason, and keeps what can be kept (v0.7.1, R2).

The review found that an allocation failure while pydub read FFmpeg's output hung the whole run for ever, with its gate reservation
held and Cancel powerless. Three groups here:

* The rules, on injected readings and failures: what the gate counts, how it falls back, when it gives up, what Cancel does.
* :mod:`tts.ffmpeg_watch` on real child processes: nothing can block on a pipe, and every deadline really fires.
* The whole thing on Windows under a real limit (``low_memory_probe``): a Job Object makes allocations really fail in a child process,
  with the real gate, runner, folder worker and FFmpeg, and a parent outside the limit that can see a hang and clean up after it.
  ``test_the_old_hang_is_what_this_test_would_see`` puts pydub back on the raw module and requires that hang: the negative control.
"""

from __future__ import annotations

import contextlib
import inspect
import os
import subprocess
import sys
import tempfile
import threading
import time
import weakref
from pathlib import Path

import pytest
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError, CouldntEncodeError

from shared import ffmpeg_utils
from shared.cancellation import ConversionCancelled
from tts import batch_convert, disk_assembly, edge_failures, ffmpeg_watch, publication
from tts import worker_limits as wl
from tts.epub2tts_edge import epub2tts_edge as engine

from test_assembly_on_disk import clip_for, direct_mp3, folder_mp3, write_book

GB = 1024 ** 3
MB = 1024 ** 2
needs_ffmpeg = pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(), reason="needs the pinned FFmpeg")


def Machine(available_gb, total_gb=32, commit_gb=None, process_mb=None, job_mb=None):
    reading = wl.MemoryInfo(int(available_gb * GB), int(total_gb * GB), None if commit_gb is None else int(commit_gb * GB),
                            None if process_mb is None else int(process_mb * MB), None if job_mb is None else int(job_mb * MB))
    return lambda: reading


# --------------------------------------------------------------------------- what is usable, and what the routes need


@pytest.mark.parametrize("reading, expected", [
    (wl.MemoryInfo(16 * GB, 32 * GB), 8 * GB),                                   # physical alone, as ever
    (wl.MemoryInfo(16 * GB, 32 * GB, 64 * GB), 8 * GB),                          # plenty to commit: physical decides
    (wl.MemoryInfo(16 * GB, 32 * GB, 3 * GB), 2 * GB),                           # the commit limit decides, less its reserve
    (wl.MemoryInfo(16 * GB, 32 * GB, 64 * GB, 500 * MB), 468 * MB),              # a limit on this process
    (wl.MemoryInfo(16 * GB, 32 * GB, 64 * GB, None, 200 * MB), 168 * MB),        # a limit on its job
    (wl.MemoryInfo(16 * GB, 32 * GB, 3 * GB, 500 * MB, 200 * MB), 168 * MB),     # the tightest of all
])
def test_what_is_usable_is_the_tightest_reading_less_its_own_margin(reading, expected):
    assert wl.memory_usable(reading) == expected


def test_plenty_of_physical_memory_with_little_to_commit_goes_to_disk():
    """The review's condition: what a process can allocate is not what is physically free."""
    gate = wl.AssemblyGate(Machine(24, commit_gb=1.5))
    with gate.reserve(1 * GB) as in_memory:
        assert in_memory is False


def test_with_commit_to_spare_the_same_assembly_stays_in_memory():
    gate = wl.AssemblyGate(Machine(24, commit_gb=20))
    with gate.reserve(1 * GB) as in_memory:
        assert in_memory is True


def test_an_unread_commit_figure_decides_nothing():
    gate = wl.AssemblyGate(Machine(24))
    with gate.reserve(1 * GB) as in_memory:
        assert in_memory is True


def test_a_process_limit_is_compared_with_this_process_part_of_the_disk_route():
    """FFmpeg has its own per-process limit, so a limit of 30 MB leaves room for this process's 24 MB of disk assembly."""
    with wl.AssemblyGate(Machine(24, commit_gb=20, process_mb=30), wait_seconds=0).reserve(1 * GB) as in_memory:
        assert in_memory is False
    with pytest.raises(wl.AssemblyMemoryError):
        with wl.AssemblyGate(Machine(24, commit_gb=20, process_mb=20), wait_seconds=0).reserve(1 * GB):
            pass


def test_a_job_limit_covers_ffmpeg_too_so_the_whole_disk_route_counts_against_it():
    with pytest.raises(wl.AssemblyMemoryError):
        with wl.AssemblyGate(Machine(24, commit_gb=20, job_mb=63), wait_seconds=0).reserve(1 * GB):
            pass
    with wl.AssemblyGate(Machine(24, commit_gb=20, job_mb=64), wait_seconds=0).reserve(1 * GB) as in_memory:
        assert in_memory is False


def test_too_little_commit_for_even_the_disk_route_fails_with_a_reason():
    gate = wl.AssemblyGate(Machine(24, commit_gb=0.05), wait_seconds=0)
    with pytest.raises(wl.AssemblyMemoryError, match="Close other programs"):
        with gate.reserve(1 * GB):
            pass
    assert gate._in_use == 0 and not gate._queue


def test_the_plan_also_holds_to_commit_and_says_so():
    budgets = [wl.budget_for_seconds(8 * 3600)] * 8
    plan = wl.plan_workers(8, "edge", budgets, cpu_count=16, memory=wl.MemoryInfo(16 * GB, 16 * GB, 3 * GB))
    assert plan.effective == 1
    assert "can be committed" in plan.reasons[0]


@pytest.mark.skipif(sys.platform != "win32", reason="what Windows reports")
def test_this_machine_really_reports_commit():
    reading = wl.memory_info()
    assert reading is not None and reading.commit_available and reading.commit_available > 0
    assert wl.own_private_bytes() > 0


# --------------------------------------------------------------------------- not counting a reservation twice


def test_what_has_been_allocated_is_not_counted_against_a_reading_that_already_shows_it():
    """Holder reserves 4 GB and allocates it; the reading falls by that. A newcomer needing 3 of the 4 GB left fits."""
    private = [10 * GB]
    available = [16 * GB]
    gate = wl.AssemblyGate(lambda: wl.MemoryInfo(available[0], 16 * GB), private_reader=lambda: private[0], poll_seconds=0.01)
    with gate.reserve(4 * GB) as first:
        assert first is True
        private[0] += 4 * GB
        available[0] -= 4 * GB  # 12 free, 4 reserved: 8 usable, and 4 of those were counted twice before
        assert gate._claimed() == 0
        with gate.reserve(7 * GB) as second:
            assert second is True, "7 fits in the 8 usable: nothing is still to come"


def test_what_has_not_been_allocated_yet_still_counts():
    private = [10 * GB]
    gate = wl.AssemblyGate(lambda: wl.MemoryInfo(16 * GB, 16 * GB), private_reader=lambda: private[0], poll_seconds=0.01, wait_seconds=0)
    with gate.place(4 * GB):
        assert gate._claimed() == 4 * GB
        private[0] += GB
        assert gate._claimed() == 3 * GB, "only the part still to come"
        result = []
        waiter = threading.Thread(target=lambda: result.append(_enter(gate, 10 * GB)))
        waiter.start()
        time.sleep(0.1)
        assert not result, "3 still to come + 10 is over the 12 usable: it waits for the holder"
    waiter.join(5)
    assert result == [True]


def _enter(gate, need):
    with gate.reserve(need) as in_memory:
        return in_memory


def test_without_a_reading_of_this_process_the_whole_reservation_counts():
    gate = wl.AssemblyGate(Machine(16, 16), private_reader=lambda: None, poll_seconds=0.01)
    with gate.place(4 * GB):
        assert gate._claimed() == 4 * GB


# --------------------------------------------------------------------------- deadlines at the gate


def test_a_whole_queue_with_nothing_to_wait_for_ends_at_one_deadline():
    """One after another it was 8 x 300 seconds on 8 workers, and hours on 32: the review's serial starvation."""
    gate = wl.AssemblyGate(Machine(0, 8), poll_seconds=0.01, wait_seconds=1.0)
    ended = []

    def wait():
        started = time.monotonic()
        with pytest.raises(wl.AssemblyMemoryError):
            with gate.reserve(GB):
                pass
        ended.append(time.monotonic() - started)

    waiters = [threading.Thread(target=wait) for _ in range(8)]
    started = time.monotonic()
    for waiter in waiters:
        waiter.start()
    for waiter in waiters:
        waiter.join(30)
    assert len(ended) == 8
    assert time.monotonic() - started < 2.5, "one deadline, not eight"
    assert gate._in_use == 0 and not gate._queue and gate._starved_since is None


def test_a_later_file_is_given_a_new_deadline_once_the_queue_has_emptied():
    gate = wl.AssemblyGate(Machine(0, 8), poll_seconds=0.01, wait_seconds=0.3)
    for _ in range(2):
        started = time.monotonic()
        with pytest.raises(wl.AssemblyMemoryError):
            with gate.reserve(GB):
                pass
        assert time.monotonic() - started >= 0.25


def test_memory_coming_back_ends_the_starvation_for_the_whole_queue():
    free = [0]
    gate = wl.AssemblyGate(lambda: wl.MemoryInfo(free[0], 8 * GB), poll_seconds=0.01, wait_seconds=30)
    results = []
    waiters = [threading.Thread(target=lambda: results.append(_enter(gate, GB))) for _ in range(4)]
    for waiter in waiters:
        waiter.start()
    time.sleep(0.2)
    free[0] = 5 * GB
    for waiter in waiters:
        waiter.join(10)
    assert len(results) == 4 and gate._in_use == 0


def test_a_disk_assembly_in_progress_keeps_the_starvation_clock_from_running():
    """It will end and give its memory back, so failing the next file meanwhile would be wrong: its length is not this gate's to
    judge, and FFmpeg's deadlines cover it if it has stopped."""
    free = [GB]
    gate = wl.AssemblyGate(lambda: wl.MemoryInfo(free[0], 8 * GB), poll_seconds=0.01, wait_seconds=0.1)
    with gate.reserve(4 * GB) as first:
        assert first is False
        free[0] = 0
        outcome = []

        def later():
            with contextlib.suppress(wl.AssemblyMemoryError):
                outcome.append(_enter(gate, 4 * GB))
            outcome.append("ended")

        waiter = threading.Thread(target=later)
        waiter.start()
        time.sleep(0.4)
        assert not outcome, "past the wait, and still waiting for the disk assembly"
        free[0] = GB
    waiter.join(5)
    assert outcome == [False, "ended"]


def test_a_note_never_runs_with_the_gates_lock_held():
    """A log that blocks must not stop anyone else's reservation coming back."""
    gate = wl.AssemblyGate(Machine(4, 4), poll_seconds=0.01)
    held = threading.Event()
    go = threading.Event()
    released = threading.Event()
    note_entered = threading.Event()
    unblock = threading.Event()

    def holder():
        with gate.reserve(GB):
            held.set()
            go.wait(5)
        released.set()

    def blocking_note(_message):
        assert gate._condition.acquire(blocking=False), "the gate's lock is free while a note runs"
        gate._condition.release()
        note_entered.set()
        unblock.wait(5)

    def waiter():
        with gate.reserve(3 * GB, note=blocking_note):
            pass

    first = threading.Thread(target=holder)
    first.start()
    held.wait(5)
    second = threading.Thread(target=waiter)
    second.start()
    assert note_entered.wait(5)
    go.set()
    assert released.wait(2), "the holder finished while the note was still blocked"
    unblock.set()
    first.join(5)
    second.join(5)
    assert gate._in_use == 0


# --------------------------------------------------------------------------- Cancel at the gate


def test_cancel_sends_a_finished_narration_to_disk_past_whoever_holds_or_waits():
    gate = wl.AssemblyGate(Machine(4, 4), poll_seconds=0.01)
    holding, done = threading.Event(), threading.Event()
    cancelled = threading.Event()
    answers = []

    def holder():
        with gate.reserve(GB):
            holding.set()
            done.wait(10)

    def behind_it():
        with gate.reserve(3 * GB):
            pass

    def finished():
        with gate.reserve(3 * GB, finishing_check=cancelled.is_set) as in_memory:
            answers.append(in_memory)

    threads = [threading.Thread(target=holder)]
    threads[0].start()
    holding.wait(5)
    threads += [threading.Thread(target=behind_it), threading.Thread(target=finished)]
    threads[1].start()
    time.sleep(0.05)
    threads[2].start()
    time.sleep(0.05)
    assert not answers
    started = time.monotonic()
    cancelled.set()
    threads[2].join(5)
    assert answers == [False] and time.monotonic() - started < 1
    done.set()
    for thread in threads:
        thread.join(5)
    assert gate._in_use == 0 and not gate._queue


def test_cancel_with_no_room_even_on_disk_says_it_was_not_saved_within_its_deadline(monkeypatch):
    monkeypatch.setattr(wl, "CANCEL_FINISH_WAIT_SECONDS", 0.3)
    gate = wl.AssemblyGate(Machine(0, 8), poll_seconds=0.01, wait_seconds=60)
    started = time.monotonic()
    with pytest.raises(ConversionCancelled, match="nothing was saved"):
        with gate.reserve(GB, finishing_check=lambda: True):
            pass
    assert 0.25 <= time.monotonic() - started < 2
    assert gate._in_use == 0 and not gate._queue


def test_cancel_stops_a_file_with_more_to_synthesise_at_once_wherever_it_waits():
    gate = wl.AssemblyGate(Machine(4, 4), poll_seconds=0.01)
    cancelled = threading.Event()
    outcome = []
    held = threading.Event()
    done = threading.Event()

    def holder():
        with gate.reserve(GB):
            held.set()
            done.wait(10)

    def waiter():
        try:
            with gate.reserve(3 * GB, cancel_check=cancelled.is_set):
                outcome.append("entered")
        except ConversionCancelled:
            outcome.append("cancelled")

    first = threading.Thread(target=holder)
    first.start()
    held.wait(5)
    waiters = [threading.Thread(target=waiter) for _ in range(3)]
    for thread in waiters:
        thread.start()
    time.sleep(0.1)
    cancelled.set()
    for thread in waiters:
        thread.join(1)
    assert outcome == ["cancelled"] * 3
    done.set()
    first.join(5)
    assert gate._in_use == 0 and not gate._queue


def test_cancel_reaches_a_file_behind_one_that_goes_on_waiting():
    """The head has no reason to stop: a finished narration from before this was in force, or simply one that is told nothing. Who
    waits behind it must not have to wait for it to learn of a Cancel."""
    gate = wl.AssemblyGate(Machine(4, 4), poll_seconds=0.01)
    held, done, cancelled = threading.Event(), threading.Event(), threading.Event()
    outcome = []

    def holder():
        with gate.reserve(GB):
            held.set()
            done.wait(10)

    def head():
        with gate.reserve(3 * GB):
            outcome.append("head entered")

    def behind():
        try:
            with gate.reserve(3 * GB, cancel_check=cancelled.is_set):
                outcome.append("behind entered")
        except ConversionCancelled:
            outcome.append("behind cancelled")

    threads = [threading.Thread(target=holder)]
    threads[0].start()
    held.wait(5)
    threads += [threading.Thread(target=head)]
    threads[1].start()
    time.sleep(0.05)
    threads += [threading.Thread(target=behind)]
    threads[2].start()
    time.sleep(0.05)
    cancelled.set()
    threads[2].join(2)
    assert outcome == ["behind cancelled"], "and the head is still waiting"
    done.set()
    for thread in threads:
        thread.join(5)
    assert gate._in_use == 0 and not gate._queue


# --------------------------------------------------------------------------- falling back


@pytest.fixture()
def quick_gate(monkeypatch):
    gate = wl.AssemblyGate(Machine(32, 32), poll_seconds=0.01, wait_seconds=0.2)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    monkeypatch.setattr(wl, "DISK_RETRY_PAUSE_SECONDS", 0)
    return gate


@pytest.mark.parametrize("failure", [MemoryError(), MemoryError("big"), OSError(22, "x", None, 1455), OSError(22, "x", None, 8),
                                     RuntimeError("can't start new thread"), CouldntDecodeError("ffmpeg: Cannot allocate memory"),
                                     CouldntEncodeError("Encoding failed. ffmpeg/avlib returned error code: 3221225495")])
def test_an_allocation_failure_however_it_surfaces_falls_back_to_disk(quick_gate, failure):
    calls = []
    notes = []

    def in_memory():
        calls.append("memory")
        assert quick_gate._in_memory == 1 and quick_gate._in_use > 64 * MB
        raise failure

    def on_disk():
        calls.append("disk")
        assert quick_gate._in_memory == 0 and quick_gate._in_use == wl.DISK_ASSEMBLY_BYTES, "the rest of the reservation went back first"
        return "the result"

    assert wl.assemble(48_000 * 3600, in_memory, on_disk, note=notes.append) == "the result"
    assert calls == ["memory", "disk"]
    assert "assembled on disk instead" in notes[0] and "Nothing is being requested" in notes[0]
    assert quick_gate._in_use == 0 and quick_gate._on_disk == 0 and quick_gate._in_memory == 0


def test_the_failed_attempts_memory_is_gone_before_the_disk_route_runs(quick_gate):
    """All that it managed to build: the fallback is for a computer with none to spare."""
    class Built:
        pass

    built = []
    alive_when_falling_back = []

    def in_memory():
        narration = Built()
        built.append(weakref.ref(narration))
        raise MemoryError()

    def on_disk():
        alive_when_falling_back.append(built[0]() is not None)

    wl.assemble(48_000 * 3600, in_memory, on_disk)
    assert alive_when_falling_back == [False]


@pytest.mark.parametrize("failure", [ValueError("no"), OSError(13, "denied"), CouldntEncodeError("no space left"), publication.PublicationError("no")])
def test_any_other_failure_is_not_retried_as_if_it_were_memory(quick_gate, failure):
    calls = []

    def in_memory():
        calls.append("memory")
        raise failure

    with pytest.raises(type(failure)):
        wl.assemble(48_000 * 3600, in_memory, lambda: calls.append("disk"))
    assert calls == ["memory"] and quick_gate._in_use == 0


def test_recovery_is_bounded_and_ends_with_a_named_reason_never_a_blank_one(quick_gate):
    calls = []

    def fail_memory():
        calls.append("memory")
        raise MemoryError()

    def fail_disk():
        calls.append("disk")
        raise MemoryError()

    with pytest.raises(wl.AssemblyMemoryError) as caught:
        wl.assemble(48_000 * 3600, fail_memory, fail_disk)
    assert calls == ["memory", "disk", "disk"]
    assert "ran out of memory" in str(caught.value) and "Retry Failed" in str(caught.value)
    assert quick_gate._in_use == 0 and quick_gate._on_disk == 0
    assert not edge_failures.is_retryable(caught.value)


def test_the_disk_routes_second_attempt_waits_for_whoever_holds_memory(monkeypatch):
    """Their peak may be all that was in the way, and it ends: the review's case of three at once."""
    gate = wl.AssemblyGate(Machine(32, 32), poll_seconds=0.01, wait_seconds=30)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    monkeypatch.setattr(wl, "DISK_RETRY_PAUSE_SECONDS", 0)
    release = threading.Event()
    attempts = []
    other_held_at_second = []

    def other():
        with gate.reserve(GB):
            release.wait(10)

    holder = threading.Thread(target=other)
    holder.start()
    while not gate._in_memory:
        time.sleep(0.005)

    def on_disk():
        attempts.append(time.monotonic())
        if len(attempts) == 1:
            threading.Timer(0.3, release.set).start()
            raise MemoryError()
        other_held_at_second.append(gate._in_memory)
        return "saved"

    def in_memory():
        raise MemoryError()

    assert wl.assemble(48_000 * 3600, in_memory, on_disk) == "saved"
    assert attempts[1] - attempts[0] >= 0.25 and other_held_at_second == [0]
    holder.join(5)


def test_every_reservation_comes_back_from_any_ending(quick_gate):
    def ending(error):
        def run():
            raise error
        return run

    for error, kind in ((ValueError("x"), ValueError), (KeyboardInterrupt(), KeyboardInterrupt), (SystemExit(), SystemExit), (ConversionCancelled("x"), ConversionCancelled)):
        with pytest.raises(kind):
            wl.assemble(48_000 * 3600, ending(error), lambda: None)
        assert quick_gate._in_use == 0 and quick_gate._in_memory == 0 and quick_gate._on_disk == 0, repr(error)
        with pytest.raises(kind):
            with quick_gate.place(GB) as place:
                place.to_disk()
                raise error
        assert quick_gate._in_use == 0 and quick_gate._on_disk == 0, repr(error)


def test_giving_memory_back_wakes_whoever_was_waiting_for_it():
    gate = wl.AssemblyGate(Machine(4, 4), poll_seconds=5)  # no polling to hide behind: only a notification can wake it this soon
    entered = threading.Event()
    held = threading.Event()
    finish = threading.Event()
    woken = []

    def holder():
        with gate.place(2 * GB) as place:  # 3 GB usable: the 1.5 GB below does not fit beside this until it is given back
            held.set()
            finish.wait(10)
            place.to_disk()
            woken.append(entered.wait(3))  # it was woken when the memory came back, while this one still works on disk

    def waiter():
        with gate.reserve(1500 * MB):
            entered.set()

    first = threading.Thread(target=holder)
    first.start()
    held.wait(5)
    second = threading.Thread(target=waiter)
    second.start()
    time.sleep(0.1)
    assert not entered.is_set(), "it really was waiting"
    finish.set()
    first.join(8)
    second.join(8)
    assert woken == [True] and gate._in_use == 0


def test_a_cancel_that_loses_finished_narration_is_said_out_loud_for_that_file(quick_gate):
    notes = []

    def stopped():
        raise ConversionCancelled("Cancelled before this file was saved: nothing was saved for it.")

    with pytest.raises(ConversionCancelled):
        wl.assemble(48_000 * 3600, stopped, lambda: None, finishing_check=lambda: False, note=notes.append)
    assert notes == ["Cancelled before this file was saved: nothing was saved for it."]


def test_a_mid_book_cancel_is_not_announced_as_a_lost_narration(quick_gate):
    notes = []

    def stopped():
        raise ConversionCancelled("Conversion cancelled by user.")

    with pytest.raises(ConversionCancelled):
        wl.assemble(48_000 * 3600, stopped, lambda: None, cancel_check=lambda: False, note=notes.append)
    assert notes == []


# --------------------------------------------------------------------------- what fails with what


def test_a_decoder_out_of_memory_is_not_a_damaged_clip_worth_synthesising_again():
    assert not edge_failures.is_retryable(CouldntDecodeError("Decoding failed. ffmpeg: Cannot allocate memory"))
    assert edge_failures.is_retryable(CouldntDecodeError("Decoding failed. Invalid data found when processing input"))


def test_a_stopped_ffmpeg_is_not_worth_synthesising_again():
    assert not edge_failures.is_retryable(ffmpeg_watch.ProcessingStalled("x"))


def test_the_panels_one_line_message_is_the_reason_itself():
    text = wl.out_of_memory_text("MemoryError: ")
    assert edge_failures.split_failure_text(f"AssemblyMemoryError: {text}") == text
    assert edge_failures.split_failure_text(f"{text}\nTraceback (most recent call last):") == text
    starved = "Too little memory is free to assemble this file's narration, even on disk."
    assert edge_failures.split_failure_text(f"{starved}\nTraceback (most recent call last):") == starved
    assert edge_failures.split_failure_text(f"AssemblyMemoryError: {starved}") == starved


def test_a_failure_of_the_disk_route_on_memory_is_not_mistaken_for_a_second_memory_failure():
    assert wl.is_memory_failure(wl.AssemblyMemoryError("x")) is False, "the answer, not another occurrence of the question"


# --------------------------------------------------------------------------- real child processes


def _python(code: str) -> list[str]:
    return [sys.executable, "-I", "-c", code]


def test_what_pydub_uses_is_what_was_replaced():
    """pydub is pinned; this says so if a new version starts FFmpeg some other way, or under another name."""
    import pydub.audio_segment
    import pydub.utils

    assert ffmpeg_watch.installed()
    source = inspect.getsource(pydub.audio_segment)
    assert "subprocess.Popen(" in source and "from tempfile import" in source and "NamedTemporaryFile(" in source
    source = inspect.getsource(pydub.utils)
    assert "from subprocess import Popen" in source and "Popen(" in source
    assert "os.system" not in source and "check_output" not in source and "subprocess.run" not in source


@needs_ffmpeg
def test_a_failed_export_leaves_no_temporary_file_behind(tmp_path, monkeypatch):
    """pydub keeps two when it fails: the first is the whole narration as a WAV."""
    ffmpeg_utils.configure_pydub()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    segment = AudioSegment.silent(200)
    with ffmpeg_watch.controlled(None):
        with pytest.raises(CouldntEncodeError):
            segment.export(tmp_path / "o.flac", format="flac", parameters=["-no-such-option"])
        assert len(list(tmp_path.glob("tmp*"))) == 2, "pydub really does leave them"
    assert not list(tmp_path.glob("tmp*"))


@needs_ffmpeg
def test_an_export_that_works_keeps_nothing_in_memory_or_on_disk(tmp_path, monkeypatch):
    ffmpeg_utils.configure_pydub()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with ffmpeg_watch.controlled(None):
        for _ in range(5):
            AudioSegment.silent(200).export(tmp_path / "o.flac", format="flac")
        assert not list(tmp_path.glob("tmp*"))
        remembered = ffmpeg_watch._control.get().temporaries
        assert len(remembered) <= 2, "those that have gone are forgotten as it goes"


@needs_ffmpeg
def test_falling_back_removes_what_the_failed_export_left_before_the_disk_route_needs_the_room(tmp_path, quick_gate, monkeypatch):
    ffmpeg_utils.configure_pydub()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    seen = []

    def in_memory():
        AudioSegment.silent(200).export(tmp_path / "o.flac", format="flac", parameters=["-no-such-option"])

    def failing_in_memory():
        try:
            in_memory()
        except CouldntEncodeError:
            raise MemoryError() from None

    with ffmpeg_watch.controlled(None):
        wl.assemble(48_000 * 3600, failing_in_memory, lambda: seen.append(list(tmp_path.glob("tmp*"))))
    assert seen == [[]]


@needs_ffmpeg
def test_the_direct_route_leaves_no_work_folder_when_the_final_encode_fails(tmp_path, offline, monkeypatch):
    from tts.epub2tts_edge import runner

    source = write_book(tmp_path / "in", LONG_BOOK)
    direct_mp3(source, tmp_path / "plain")  # every clip is made once, by the export replaced below, and kept
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    real_export = AudioSegment.export

    def export(self, out_f=None, format="mp3", **kwargs):
        if format == "mp3":
            kwargs["parameters"] = ["-no-such-option"]
        return real_export(self, out_f, format=format, **kwargs)

    monkeypatch.setattr(AudioSegment, "export", export)
    with pytest.raises(CouldntEncodeError):
        runner.run_conversion_job(str(source), output_dir=str(tmp_path / "out"), speaker="v", audio_format="mp3")
    assert not list(tmp_path.glob("epub2tts_*")) and not list(tmp_path.glob("tmp*"))


def test_nothing_else_on_these_routes_starts_a_process_with_threads_of_its_own():
    for module in (disk_assembly, batch_convert):
        source = inspect.getsource(module)
        assert "subprocess_utils" not in source and "communicate" not in source and "subprocess.run" not in source, module.__name__


def test_a_process_that_fills_stderr_and_then_stdout_cannot_block():
    """Each pipe's worth at once, in the order that blocks anything reading them one at a time."""
    code = ("import sys;e=sys.stderr.buffer;o=sys.stdout.buffer;[e.write(b'E'*65536) for _ in range(64)];e.flush();"
            "[o.write(b'O'*65536) for _ in range(64)];o.flush()")
    child = ffmpeg_watch.Supervised(_python(code), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, errors = child.communicate()
    assert child.returncode == 0 and len(output) == 64 * 65536
    assert errors and len(errors) == ffmpeg_watch.STDERR_TAIL_BYTES and set(errors) == {ord("E")}


def test_an_allocation_failure_while_reading_kills_the_process_where_it_can_be_caught(monkeypatch):
    """The review's hang: this is the failure that used to happen on a thread, with nobody to tell."""
    code = "import sys,time;\nwhile True: sys.stdout.buffer.write(b'x'*65536);sys.stdout.buffer.flush()"
    child = ffmpeg_watch.Supervised(_python(code), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    real_blocks = child.blocks

    def failing(size=ffmpeg_watch.BLOCK_BYTES):
        for count, block in enumerate(real_blocks(size)):
            if count == 2:
                raise MemoryError()
            yield block

    monkeypatch.setattr(child, "blocks", failing)
    started = time.monotonic()
    with pytest.raises(MemoryError):
        child.communicate()
    assert time.monotonic() - started < 15
    assert child.process.poll() is not None, "the process is gone"
    assert child._item not in ffmpeg_watch._watched


def test_a_stalled_process_is_stopped_with_a_reason(monkeypatch):
    monkeypatch.setattr(ffmpeg_watch, "STALL_SECONDS", 0.5)
    child = ffmpeg_watch.Supervised(_python("import time;time.sleep(60)"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = time.monotonic()
    with pytest.raises(ffmpeg_watch.ProcessingStalled, match="stopped making progress"):
        child.communicate()
    assert time.monotonic() - started < 10
    assert child.process.poll() is not None


def test_a_process_making_progress_is_not_stalled_however_long_it_takes(monkeypatch):
    monkeypatch.setattr(ffmpeg_watch, "STALL_SECONDS", 0.7)
    code = "import sys,time;\nfor _ in range(6):\n  sys.stdout.buffer.write(b'x'*(1<<20));sys.stdout.buffer.flush();time.sleep(0.3)"
    child = ffmpeg_watch.Supervised(_python(code), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, _errors = child.communicate()
    assert child.returncode == 0 and len(output) == 6 << 20


def test_growth_of_the_file_being_written_is_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpeg_watch, "STALL_SECONDS", 0.7)
    target = tmp_path / "out.bin"
    code = (f"import time;f=open({str(target)!r},'wb')\nfor _ in range(6):\n  f.write(b'x'*4096);f.flush();time.sleep(0.3)\n")
    done = ffmpeg_watch.run(_python(code) + [str(target)])
    assert done.returncode == 0


def test_cancel_with_more_to_synthesise_stops_it_within_one_look(monkeypatch):
    cancelled = threading.Event()
    with ffmpeg_watch.controlled(cancelled.is_set, abort_on_cancel=True):
        child = ffmpeg_watch.Supervised(_python("import time;time.sleep(60)"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    threading.Timer(0.2, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        child.communicate()
    assert time.monotonic() - started < 3


def test_cancel_of_finished_narration_lets_it_finish_while_it_progresses(monkeypatch):
    monkeypatch.setattr(ffmpeg_watch, "CANCEL_STALL_SECONDS", 0.7)
    code = "import sys,time;\nfor _ in range(6):\n  sys.stdout.buffer.write(b'x'*(1<<20));sys.stdout.buffer.flush();time.sleep(0.3)"
    with ffmpeg_watch.controlled(lambda: True):
        child = ffmpeg_watch.Supervised(_python(code), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, _errors = child.communicate()
    assert child.returncode == 0 and len(output) == 6 << 20


def test_cancel_of_finished_narration_that_has_stopped_ends_at_its_deadline(monkeypatch):
    monkeypatch.setattr(ffmpeg_watch, "CANCEL_STALL_SECONDS", 0.5)
    with ffmpeg_watch.controlled(lambda: True):
        child = ffmpeg_watch.Supervised(_python("import time;time.sleep(60)"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = time.monotonic()
    with pytest.raises(ConversionCancelled, match="nothing was saved"):
        child.communicate()
    assert time.monotonic() - started < 10


def test_cancel_of_finished_narration_ends_at_its_cap_however_well_it_is_going(monkeypatch):
    monkeypatch.setattr(ffmpeg_watch, "CANCEL_STALL_SECONDS", 30)
    monkeypatch.setattr(ffmpeg_watch, "CANCEL_FINISH_SECONDS", 1)
    code = "import sys,time;\nwhile True: sys.stdout.buffer.write(b'x'*(1<<20));sys.stdout.buffer.flush();time.sleep(0.1)"
    with ffmpeg_watch.controlled(lambda: True):
        child = ffmpeg_watch.Supervised(_python(code), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        child.communicate()
    assert time.monotonic() - started < 15


def test_a_cancel_check_that_fails_does_not_stop_the_stall_deadline(monkeypatch):
    """It would be asked first, every time, and if that took the rest of the look with it nothing would ever be stopped."""
    monkeypatch.setattr(ffmpeg_watch, "STALL_SECONDS", 0.5)

    def broken():
        raise OSError("gone")

    with ffmpeg_watch.controlled(broken):
        child = ffmpeg_watch.Supervised(_python("import time;time.sleep(60)"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = time.monotonic()
    with pytest.raises(ffmpeg_watch.ProcessingStalled):
        child.communicate()
    assert time.monotonic() - started < 10


def test_a_process_that_cannot_start_leaves_nothing_watched():
    before = len(ffmpeg_watch._watched)
    with pytest.raises(OSError):
        ffmpeg_watch.Supervised(["no-such-program-anywhere-at-all"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert len(ffmpeg_watch._watched) == before


# --------------------------------------------------------------------------- real audio: the same bytes, however it got there


@needs_ffmpeg
def test_pydub_decodes_and_exports_the_same_bytes_through_the_watch(tmp_path):
    ffmpeg_utils.configure_pydub()
    source = tmp_path / "clip.mp3"
    subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=24000:duration=3",
                    "-ac", "1", "-b:a", "48k", str(source)], check=True)
    assert ffmpeg_watch.installed()
    watched = AudioSegment.from_file(str(source))
    watched.export(tmp_path / "w.mp3", format="mp3", bitrate="64k")
    ffmpeg_watch.uninstall()
    try:
        raw = AudioSegment.from_file(str(source))
        raw.export(tmp_path / "r.mp3", format="mp3", bitrate="64k")
    finally:
        ffmpeg_watch.install()
    assert watched.raw_data == raw.raw_data
    assert (tmp_path / "w.mp3").read_bytes() == (tmp_path / "r.mp3").read_bytes()


@pytest.fixture()
def offline(monkeypatch):
    """The service, replaced by a clip per text. Holds every request made."""
    requests = []

    def speak(text, path):
        requests.append(text)
        Path(path).write_bytes(clip_for(text))

    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)
    monkeypatch.setattr(engine, "run_edgespeak", lambda text, speaker, path: speak(text, path))
    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3", lambda text, path, voice, rate: speak(text, path))
    monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)
    return requests


def _failing_every(monkeypatch, attribute, predicate):
    """``AudioSegment.<attribute>`` fails with a real exception type when ``predicate(args)`` says so. Returns the count."""
    real = getattr(AudioSegment, attribute)
    hits = [0]

    def wrapper(*args, **kwargs):
        if predicate(args, kwargs):
            hits[0] += 1
            raise MemoryError()
        return real(*args, **kwargs)

    monkeypatch.setattr(AudioSegment, attribute, wrapper if attribute == "export" else classmethod(lambda cls, *a, **k: wrapper(*a, **k)))
    return hits


LONG_BOOK = "# First Title\n\nOne sentence here, then another. Two more words!\n\nA second paragraph, with a comma.\n\n# Second Title\n\nThe last words.\n"


@needs_ffmpeg
def test_running_out_of_memory_in_a_spill_writes_each_piece_and_gives_the_same_bytes(tmp_path, offline, monkeypatch):
    """A long paragraph writing out what it holds: if there is no memory to join that first, each piece is a file of its own."""
    source = write_book(tmp_path / "in", LONG_BOOK)
    expected = direct_mp3(source, tmp_path / "plain")
    monkeypatch.setattr(wl, "SYNTHESIS_HELD_PCM_BYTES", 20_000)
    # Only the join's export: the pieces it falls back to are small enough to write. The frames are this lambda, the wrapper, its caller.
    hits = _failing_every(monkeypatch, "export", lambda args, kwargs: sys._getframe(2).f_code.co_name == "write")
    assert direct_mp3(source, tmp_path / "pressed") == expected
    assert hits[0], "the failure happened"


@needs_ffmpeg
def test_running_out_of_memory_adding_a_chapters_pause_writes_it_as_a_file_and_gives_the_same_bytes(tmp_path, offline, monkeypatch):
    source = write_book(tmp_path / "in", LONG_BOOK)
    expected = direct_mp3(source, tmp_path / "plain")
    real_append = engine.append_silence
    hits = []

    def append(path, duration=1200):
        hits.append(path)
        raise MemoryError()

    monkeypatch.setattr(engine, "append_silence", append)
    assert direct_mp3(source, tmp_path / "pressed") == expected
    assert hits and real_append


@needs_ffmpeg
@pytest.mark.parametrize("where", ["a clip's decode", "the paragraph's export", "the chapter join's export", "the final export"])
def test_running_out_at_any_step_of_the_direct_route_gives_the_same_bytes_with_no_new_request(tmp_path, offline, monkeypatch, where):
    source = write_book(tmp_path / "in", LONG_BOOK)
    expected = direct_mp3(source, tmp_path / "plain")
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", wl.AssemblyGate(Machine(32, 32)))
    monkeypatch.setattr(wl, "DISK_RETRY_PAUSE_SECONDS", 0)
    requested_before = len(offline)
    if where == "a clip's decode":
        hits = _failing_every(monkeypatch, "from_file", lambda args, kwargs: "sntnc1_sub1" in str(args[0]))
    elif where == "the paragraph's export":
        hits = _failing_every(monkeypatch, "export", lambda args, kwargs: "pgraphs0.flac" in str(args[1]))
    elif where == "the chapter join's export":
        hits = _failing_every(monkeypatch, "export", lambda args, kwargs: "part1.flac" in str(args[1]))
    else:
        hits = _failing_every(monkeypatch, "export", lambda args, kwargs: kwargs.get("format") == "mp3")
    produced = direct_mp3(source, tmp_path / "pressed")
    assert hits[0], "the failure happened"
    assert produced == expected, "the same MP3, to the byte"
    assert len(offline) - requested_before == requested_before, "as many requests as the first time: nothing asked for twice"


@needs_ffmpeg
def test_running_out_on_the_folder_route_gives_the_same_bytes_with_no_new_request(tmp_path, offline, monkeypatch):
    source = write_book(tmp_path / "in", LONG_BOOK)
    expected = folder_mp3(source, tmp_path / "plain")
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", wl.AssemblyGate(Machine(32, 32)))
    requested_before = len(offline)
    hits = _failing_every(monkeypatch, "export", lambda args, kwargs: True)
    produced = folder_mp3(source, tmp_path / "pressed")
    assert hits[0] and produced == expected
    assert len(offline) - requested_before == requested_before


@needs_ffmpeg
def test_when_nothing_can_be_done_the_direct_route_names_it_and_publishes_nothing(tmp_path, offline, monkeypatch):
    from tts.epub2tts_edge import runner

    source = write_book(tmp_path / "in", LONG_BOOK)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    monkeypatch.setattr(wl, "DISK_RETRY_PAUSE_SECONDS", 0)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", wl.AssemblyGate(Machine(32, 32)))
    monkeypatch.setattr(disk_assembly, "encode_mp3", lambda *a, **k: (_ for _ in ()).throw(MemoryError()))
    _failing_every(monkeypatch, "export", lambda args, kwargs: kwargs.get("format") == "mp3")
    with pytest.raises(wl.AssemblyMemoryError, match="ran out of memory"):
        runner.run_conversion_job(str(source), output_dir=str(tmp_path / "out"), speaker="v", audio_format="mp3")
    assert not list((tmp_path / "out").glob("*")) if (tmp_path / "out").exists() else True
    assert wl.ASSEMBLY_GATE._in_use == 0


def test_a_memory_error_anywhere_in_the_direct_route_is_never_a_blank_message(tmp_path, monkeypatch):
    from tts.epub2tts_edge import runner

    source = tmp_path / "book.txt"
    source.write_text("Words.\n", encoding="utf-8")
    monkeypatch.setattr(runner, "get_book", lambda *a, **k: (_ for _ in ()).throw(MemoryError()))
    with pytest.raises(wl.AssemblyMemoryError) as caught:
        runner.run_conversion_job(str(source), output_dir=str(tmp_path / "out"), speaker="v", audio_format="mp3")
    assert f"{type(caught.value).__name__}: {caught.value}" != "MemoryError: " and "Close other programs" in str(caught.value)


def test_a_memory_error_in_the_folder_route_is_named_and_not_synthesised_again(tmp_path, monkeypatch):
    source = write_book(tmp_path / "in", "Plain words here to read aloud.\n")
    calls = []
    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3", lambda text, path, voice, rate: (calls.append(text), Path(path).write_bytes(b""))[1])
    monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)
    monkeypatch.setattr(wl, "DISK_RETRY_PAUSE_SECONDS", 0)
    for name in ("merge_mp3s", "merge_mp3s_on_disk"):
        monkeypatch.setattr(batch_convert, name, lambda *a, **k: (_ for _ in ()).throw(MemoryError()))
    status, _path, message = batch_convert.convert_single_pdf(source, tmp_path / "out", "v", "+0%", lambda _m: None, out_mp3=tmp_path / "out" / "b.mp3")
    assert status == "failed" and len(calls) == 1
    assert message.startswith("This computer ran out of memory")


def test_a_memory_error_outside_the_assembly_on_the_folder_route_is_named_too(tmp_path, monkeypatch):
    source = write_book(tmp_path / "in", "Plain words here to read aloud.\n")
    monkeypatch.setattr(batch_convert, "split_into_chunks", lambda text: (_ for _ in ()).throw(MemoryError()))
    status, _path, message = batch_convert.convert_single_pdf(source, tmp_path / "out", "v", "+0%", lambda _m: None, out_mp3=tmp_path / "out" / "b.mp3")
    assert status == "failed"
    assert message.startswith("This computer ran out of memory")


# --------------------------------------------------------------------------- disk space, and what an interrupted run left


def test_a_full_disk_named_by_ffmpeg_is_named_for_the_person(tmp_path, monkeypatch):
    part = tmp_path / "part.flac"
    part.write_bytes(b"")
    monkeypatch.setattr(disk_assembly.WavSpool, "append_file", lambda self, path, format=None: (_ for _ in ()).throw(
        CouldntEncodeError("av_interleaved_write_frame(): No space left on device")))
    with pytest.raises(publication.PublicationError, match="ran out of space"):
        disk_assembly.encode_mp3([part], tmp_path / "o.mp3", tmp_path / "s.wav")
    assert not (tmp_path / "s.wav").exists()


def test_too_little_disk_is_refused_before_starting(tmp_path, monkeypatch):
    part = tmp_path / "part.flac"
    part.write_bytes(b"")
    monkeypatch.setattr(wl, "decoded_size", lambda paths: 5 * GB)
    monkeypatch.setattr(disk_assembly.shutil, "disk_usage", lambda path: type("U", (), {"free": GB})())
    with pytest.raises(publication.PublicationError, match="1.0 GB free.*5.0 GB"):
        disk_assembly.encode_mp3([part], tmp_path / "o.mp3", tmp_path / "s.wav")
    assert not (tmp_path / "s.wav").exists()


def _chunk_folder(root: Path, name: str, *, age: float) -> Path:
    folder = root / ".tmp_chunks" / name
    folder.mkdir(parents=True)
    (folder / "assembly.wav").write_bytes(b"x")
    os.utime(folder, (time.time() - age, time.time() - age))
    return folder


def test_only_an_interrupted_runs_own_stale_working_folder_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(publication, "process_is_alive", lambda pid: pid == 0x1234)
    old = batch_convert.STALE_CHUNK_FOLDER_SECONDS + 60
    gone = _chunk_folder(tmp_path / "TTS-Audiobook-1", "00000bad-deadbeef", age=old)
    alive = _chunk_folder(tmp_path / "TTS-Audiobook-2", "00001234-deadbeef", age=old)
    recent = _chunk_folder(tmp_path / "TTS-Audiobook-3", "00000bad-deadbee0", age=0)
    foreign = _chunk_folder(tmp_path / "TTS-Audiobook-4", "my-own-folder", age=old)
    elsewhere = tmp_path / "TTS-Audiobook-5" / "tmp_chunks" / "00000bad-deadbeef"
    elsewhere.mkdir(parents=True)
    os.utime(elsewhere, (time.time() - old, time.time() - old))
    assert batch_convert.sweep_stale_chunk_folders(tmp_path) == [gone]
    assert not gone.exists() and alive.exists() and recent.exists() and foreign.exists() and elsewhere.exists()


# --------------------------------------------------------------------------- a real limit, on Windows

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows'")
HANG_DEADLINE = 45


@pytest.fixture(scope="module")
def real_clip(tmp_path_factory):
    if not ffmpeg_utils.have_ffmpeg():
        pytest.skip("needs the pinned FFmpeg")
    path = tmp_path_factory.mktemp("clip") / "clip.mp3"
    subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=24000:duration=900",
                    "-af", "apad=pad_dur=0.2", "-ac", "1", "-ar", "24000", "-b:a", "48k", str(path)], check=True)
    return str(path)


def _supervised(tmp_path, clip, *, deadline=180, **scenario):
    import low_memory_probe as probe

    full = dict(name=tmp_path.name, clip=clip, clips_per_file=4, files=3, headroom_mb=0, gate="real", route="direct")
    full.update(scenario)
    return probe.supervise(full, code_root=Path(__file__).resolve().parents[2], python=sys.executable, deadline_seconds=deadline, work_dir=tmp_path)


def _assert_ended_cleanly(report, *, statuses=None):
    assert not report.get("invalid"), report
    assert report["hung"] is False, report.get("stacks", "")
    assert report["exit_code"] == 0, report.get("child_output", "")
    assert report["survivors"] == [], "no FFmpeg of this probe is left running"
    assert report["gate_after"] == {"in_use": 0, "in_memory": 0, "queued": 0}, "no reservation left"
    assert report["leftovers"] == [], "nothing at all stays, in the output folder or in temporary files"
    for name, result in report["results"].items():
        assert result["status"] in ("success", "failed", "cancelled"), (name, result)
        if result["status"] == "failed":
            assert "ran out of memory" in result["message"] or "Too little memory" in result["message"] or "stopped making progress" in result["message"], result
    for name, published in report["published"].items():
        assert published["size"] > 100_000, name
    if statuses is not None:
        assert sorted(result["status"] for result in report["results"].values()) == sorted(statuses)


@pytest.fixture(scope="module")
def reference(real_clip, tmp_path_factory):
    """What an unlimited run with room makes: every run below that publishes anything must publish exactly this."""
    shas = {}
    for route in ("direct", "folder"):
        report = _supervised(tmp_path_factory.mktemp(f"reference-{route}"), real_clip, route=route, files=1, gate="roomy")
        _assert_ended_cleanly(report, statuses=["success"])
        shas[route] = next(iter(report["published"].values()))["sha256"]
    return shas


def _assert_same_audio(report, reference):
    for name, result in report["results"].items():
        published = report["published"].get(name.replace(".txt", "-V.mp3"))
        if result["status"] == "success":
            assert published and published["sha256"] == reference[result["route"]], name
        else:
            assert published is None, f"{name} {result['status']} but something was published"


@windows_only
@pytest.mark.parametrize("route, headroom", [("direct", 60), ("direct", 100), ("direct", 200), ("folder", 60), ("folder", 100), ("folder", 200), ("mixed", 100)])
def test_real_allocation_failure_on_the_in_memory_route_ends_with_the_right_audio(tmp_path, real_clip, reference, route, headroom):
    """The gate is told everything fits, so route selection cannot hide the in-memory route: it really runs into the limit."""
    report = _supervised(tmp_path, real_clip, route=route, headroom_mb=headroom, gate="roomy", files=3)
    _assert_ended_cleanly(report)
    _assert_same_audio(report, reference)
    per_file = {"direct": 4, "folder": 5}
    assert report["requests"] == sum(per_file[result["route"]] for result in report["results"].values()), "nothing was asked for twice"
    assert report["peak_gate"]["in_memory"] >= 1, "the in-memory route really was taken"


@windows_only
@pytest.mark.parametrize("route, headroom", [("direct", 60), ("direct", 200), ("folder", 100), ("mixed", 60)])
def test_the_real_gate_under_a_real_limit_sees_it_and_chooses_disk(tmp_path, real_clip, reference, route, headroom):
    report = _supervised(tmp_path, real_clip, route=route, headroom_mb=headroom, gate="real", files=3)
    _assert_ended_cleanly(report, statuses=["success"] * 3)
    _assert_same_audio(report, reference)
    assert "process_headroom=None" not in report["memory_reading_under_limit"], "the limit was read"
    assert report["peak_gate"]["in_memory"] == 0, "it never tried memory it could see it did not have"


@windows_only
def test_a_limit_on_the_whole_job_is_read_and_respected(tmp_path, real_clip, reference):
    report = _supervised(tmp_path, real_clip, route="mixed", files=2, headroom_mb=300, whole_job=True, gate="real")
    _assert_ended_cleanly(report)
    _assert_same_audio(report, reference)
    assert "job_headroom=None" not in report["memory_reading_under_limit"], report["memory_reading_under_limit"]


@windows_only
@pytest.mark.parametrize("route", ["direct", "folder"])
def test_memory_going_after_the_gate_said_yes_falls_back_to_the_same_audio(tmp_path, real_clip, reference, route):
    report = _supervised(tmp_path, real_clip, route=route, files=1, headroom_mb=1500, gate="roomy", pressure="after_admission", pressure_keep_mb=70)
    _assert_ended_cleanly(report, statuses=["success"])
    _assert_same_audio(report, reference)
    assert report["pressure_started_with_in_memory"] == 1 and report["ballast_mb"] > 1000, "the memory really went after admission"


@windows_only
@pytest.mark.parametrize("route", ["direct", "folder"])
def test_memory_gone_for_good_after_the_gate_said_yes_is_a_named_failure(tmp_path, real_clip, route):
    report = _supervised(tmp_path, real_clip, route=route, files=1, headroom_mb=1500, gate="roomy", pressure="after_admission")
    _assert_ended_cleanly(report)
    result = next(iter(report["results"].values()))
    assert result["status"] in ("failed", "success")
    if result["status"] == "failed":
        assert "Close other programs" in result["message"]


@windows_only
@pytest.mark.parametrize("route", ["direct", "folder"])
def test_cancel_with_one_file_in_memory_and_others_waiting_under_a_real_limit(tmp_path, real_clip, reference, route):
    report = _supervised(tmp_path, real_clip, route=route, headroom_mb=100, gate="one-fits", cancel_when="waiting", files=3)
    _assert_ended_cleanly(report)
    _assert_same_audio(report, reference)
    assert report["cancelled_with_waiting"]["queued"] >= 1 and report["cancelled_with_waiting"]["in_memory"] >= 1, "it really was waiting"
    assert report["cancel_to_end_seconds"] < 60, "the finishing deadlines: nothing waits on anyone else's memory after Cancel"


@windows_only
@pytest.mark.parametrize("route, stall", [("direct", "final"), ("folder", "final"), ("folder", "decode")])
def test_cancel_after_ffmpeg_really_stops_ends_at_its_deadline_and_says_so(tmp_path, real_clip, route, stall):
    report = _supervised(tmp_path, real_clip, route=route, files=1, gate="roomy", stall=stall, cancel_when="stalled",
                         constants={"tts.ffmpeg_watch.CANCEL_STALL_SECONDS": 5})
    _assert_ended_cleanly(report, statuses=["cancelled"])
    assert report["published"] == {}
    assert "stalled" in report, "FFmpeg really was suspended"
    assert 4 <= report["cancel_to_end_seconds"] < 20
    assert "nothing was saved for it" in report["child_output_tail"], "the person is told"


@windows_only
def test_cancel_with_more_to_synthesise_stops_midbook_ffmpeg_at_once(tmp_path, real_clip):
    """A chapter is still to come, so Cancel would discard this anyway: it does not sit out a stalled FFmpeg's deadline."""
    report = _supervised(tmp_path, real_clip, route="direct", files=1, chapters=2, clips_per_file=1, gate="roomy", stall="decode", cancel_when="stalled",
                         constants={"tts.ffmpeg_watch.CANCEL_STALL_SECONDS": 300}, deadline=60)
    _assert_ended_cleanly(report, statuses=["cancelled"])
    assert report["cancel_to_end_seconds"] < 5


@windows_only
def test_a_stalled_holder_without_cancel_is_stopped_and_those_waiting_go_on(tmp_path, real_clip, reference):
    report = _supervised(tmp_path, real_clip, route="folder", files=3, gate="one-fits", stall="decode",
                         constants={"tts.ffmpeg_watch.STALL_SECONDS": 6})
    _assert_ended_cleanly(report)
    statuses = sorted(result["status"] for result in report["results"].values())
    assert statuses == ["failed", "success", "success"], report["results"]
    _assert_same_audio(report, reference)


@windows_only
def test_a_starved_queue_of_eight_ends_at_one_deadline_for_real(tmp_path, real_clip):
    report = _supervised(tmp_path, real_clip, route="mixed", files=8, clips_per_file=1, gate="starved", gate_wait_seconds=4)
    _assert_ended_cleanly(report, statuses=["failed"] * 8)
    assert report["published"] == {}
    assert report["run_seconds"] < 30, "one after another this would have been at least 32 seconds"


@windows_only
def test_a_starved_narration_given_cancel_reports_it_was_not_saved_at_the_deadline(tmp_path, real_clip):
    report = _supervised(tmp_path, real_clip, route="direct", files=2, clips_per_file=1, gate="starved", cancel_after=3,
                         constants={"tts.worker_limits.CANCEL_FINISH_WAIT_SECONDS": 3})
    _assert_ended_cleanly(report, statuses=["cancelled"] * 2)
    assert report["cancel_to_end_seconds"] < 15
    assert all("nothing was saved" in result["message"] for result in report["results"].values())


@windows_only
def test_a_limit_below_what_the_process_needs_is_refused_not_reported(tmp_path, real_clip):
    report = _supervised(tmp_path, real_clip, route="direct", files=1, headroom_mb=2)
    assert report["invalid"], "a probe that could not have told anything about assembly must say so"
    assert "results" not in report


@windows_only
def test_the_old_hang_is_what_this_test_would_see(tmp_path, real_clip):
    """The negative control: pydub back on the raw ``subprocess`` module, as it was at e0aab03, with the same limit. The hang must
    come back, and the supervisor must see it and clean up exactly what it owns. If this ever passes without hanging, every test above
    has stopped proving anything."""
    report = _supervised(tmp_path, real_clip, route="direct", headroom_mb=60, gate="roomy", files=3, unsupervised=True, deadline=HANG_DEADLINE)
    assert report["hung"] is True, report
    assert "_readerthread" in report["stacks"] and "communicate" in report["stacks"], "the same stuck stacks as the review's"
    assert report["survivors"] == []
