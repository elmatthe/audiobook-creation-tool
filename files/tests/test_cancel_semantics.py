"""Cancel stops active work promptly, everywhere, and nothing unfinished is published (v0.7.2 Phase 1).

The owner's revised contract (plan §3.1 / §11.1): Cancel latches at once and stops dispatch, synthesis, memory waits,
assembly and encoding for every active file; it never starts a disk fallback, a retry or another Edge request; a file
whose publication already won stays; a file whose cancellation won leaves nothing under its final name. Pause is
unchanged: active files finish, nothing new starts, and a paused queue is cancellable immediately. The old deliberate
"finish a narration for up to 30 s idle / 600 s after Cancel" allowance is gone, and these tests hold the door shut.

Barriers, never sleeps, decide the order of events wherever two threads race.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from shared import cancellation
from shared.cancellation import ConversionCancelled
from tts import ffmpeg_watch, publication
from tts import worker_limits as wl

GB = 1024 ** 3
MB = 1024 ** 2


def _python(code: str) -> list[str]:
    return [sys.executable, "-I", "-c", code]


def Machine(available_gb, total_gb=32):
    reading = wl.MemoryInfo(int(available_gb * GB), int(total_gb * GB), None, None, None)
    return lambda: reading


# --------------------------------------------------------------------------- the primitives


def test_waiting_unless_cancelled_returns_as_soon_as_cancel_is_latched():
    cancelled = threading.Event()
    threading.Timer(0.1, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        cancellation.wait_unless_cancelled(30, cancelled.is_set, step=0.02)
    assert time.monotonic() - started < 2


def test_waiting_unless_cancelled_waits_the_whole_time_when_nobody_cancels():
    started = time.monotonic()
    cancellation.wait_unless_cancelled(0.2, lambda: False, step=0.05)
    assert 0.18 <= time.monotonic() - started < 2


def test_an_awaited_request_is_abandoned_as_soon_as_cancel_is_latched():
    """An in-flight Edge request (a coroutine) ends with the Cancel, not with the service."""
    cancelled = threading.Event()
    abandoned = {"value": False}

    async def long_request():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            abandoned["value"] = True
            raise

    threading.Timer(0.1, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        asyncio.run(cancellation.await_unless_cancelled(long_request(), cancelled.is_set, poll=0.02))
    assert time.monotonic() - started < 2 and abandoned["value"] is True


def test_an_awaited_request_that_finishes_returns_its_result():
    async def quick():
        return 42

    assert asyncio.run(cancellation.await_unless_cancelled(quick(), lambda: False, poll=0.02)) == 42


# --------------------------------------------------------------------------- ffmpeg_watch: Cancel always kills


def test_the_finish_after_cancel_allowance_no_longer_exists():
    for name in ("CANCEL_STALL_SECONDS", "CANCEL_FINISH_SECONDS", "abort_on_cancel"):
        assert not hasattr(ffmpeg_watch, name), name
    assert not hasattr(wl, "CANCEL_FINISH_WAIT_SECONDS")


def test_a_cancelled_child_is_killed_within_one_look_even_while_it_progresses():
    """The exact scenario the old policy let run to completion: steady progress, Cancel asserted from the start."""
    code = "import sys,time;\nfor _ in range(40):\n  sys.stdout.buffer.write(b'x'*(1<<20));sys.stdout.buffer.flush();time.sleep(0.1)"
    with ffmpeg_watch.controlled(lambda: True):
        child = ffmpeg_watch.Supervised(_python(code), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        child.communicate()
    assert time.monotonic() - started < 3
    assert child.process.poll() is not None and child._item not in ffmpeg_watch._watched


def test_a_cancelled_child_that_has_stalled_is_killed_within_one_look_not_at_a_deadline():
    with ffmpeg_watch.controlled(lambda: True):
        child = ffmpeg_watch.Supervised(_python("import time;time.sleep(60)"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        child.communicate()
    assert time.monotonic() - started < 3


def test_waking_the_watchdog_ends_a_cancelled_child_before_its_next_look(monkeypatch):
    """The panel's Cancel wakes the watchdog, so the kill does not wait for the next poll."""
    monkeypatch.setattr(ffmpeg_watch, "WATCH_SECONDS", 5.0)
    cancelled = threading.Event()
    with ffmpeg_watch.controlled(cancelled.is_set):
        child = ffmpeg_watch.Supervised(_python("import time;time.sleep(60)"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
    time.sleep(0.3)  # past the watchdog's first look at this child, so it is asleep for WATCH_SECONDS
    started = time.monotonic()
    cancelled.set()
    ffmpeg_watch.wake()
    with pytest.raises(ConversionCancelled):
        child.communicate()
    assert time.monotonic() - started < 2.5, "it waited for the next look instead of being woken"


def test_controlled_no_longer_takes_a_finish_flag():
    with pytest.raises(TypeError):
        with ffmpeg_watch.controlled(lambda: False, abort_on_cancel=True):  # noqa: the old keyword
            pass


# --------------------------------------------------------------------------- the gate and assemble: no fallback, no retry, no wait after Cancel


@pytest.fixture
def quick_gate(monkeypatch):
    gate = wl.AssemblyGate(Machine(16), poll_seconds=0.01, wait_seconds=1)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    return gate


def test_a_cancel_latched_before_assembly_runs_neither_route(quick_gate):
    calls = []
    with pytest.raises(ConversionCancelled):
        wl.assemble(48_000 * 3600, lambda: calls.append("memory"), lambda: calls.append("disk"), cancel_check=lambda: True)
    assert calls == [] and quick_gate._in_use == 0


def test_a_cancel_during_the_in_memory_route_starts_no_disk_fallback(quick_gate):
    cancelled = threading.Event()
    calls, notes = [], []

    def in_memory():
        calls.append("memory")
        cancelled.set()           # the person presses Cancel while the join runs...
        raise MemoryError()       # ...and memory runs out: the old code fell back to disk here

    with pytest.raises(ConversionCancelled):
        wl.assemble(48_000 * 3600, in_memory, lambda: calls.append("disk"), cancel_check=cancelled.is_set, note=notes.append)
    assert calls == ["memory"] and quick_gate._in_use == 0
    assert not any("on disk" in note for note in notes), f"a fall back was announced that must not happen: {notes}"


def test_a_cancel_after_a_failed_disk_attempt_makes_no_second_attempt(quick_gate, monkeypatch):
    monkeypatch.setattr(wl, "DISK_RETRY_PAUSE_SECONDS", 30)
    cancelled = threading.Event()
    calls = []

    def on_disk():
        calls.append("disk")
        cancelled.set()
        raise MemoryError()

    gate = wl.AssemblyGate(Machine(0.1), poll_seconds=0.01, wait_seconds=1)  # too little for memory: straight to disk
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        wl.assemble(48_000 * 3600, lambda: calls.append("memory"), on_disk, cancel_check=cancelled.is_set)
    assert calls == ["disk"] and time.monotonic() - started < 5 and gate._in_use == 0


def test_a_finished_narration_waiting_for_memory_is_cancelled_within_the_poll_and_goes_nowhere():
    """Yesterday a finished narration was sent to disk by a Cancel; today it stops like everything else."""
    gate = wl.AssemblyGate(Machine(4, 4), poll_seconds=0.01)
    holding, done, cancelled = threading.Event(), threading.Event(), threading.Event()
    outcome = []

    def holder():
        with gate.reserve(GB):
            holding.set()
            done.wait(10)

    def finished_narration():
        try:
            with gate.reserve(3 * GB, cancel_check=cancelled.is_set) as in_memory:
                outcome.append(in_memory)
        except ConversionCancelled:
            outcome.append("cancelled")

    first = threading.Thread(target=holder)
    first.start()
    holding.wait(5)
    second = threading.Thread(target=finished_narration)
    second.start()
    deadline = time.monotonic() + 5
    while not gate._queue and time.monotonic() < deadline:
        time.sleep(0.005)
    assert gate._queue, "it never reached the gate"
    started = time.monotonic()
    cancelled.set()
    second.join(5)
    assert outcome == ["cancelled"] and time.monotonic() - started < 1
    done.set()
    first.join(5)
    assert gate._in_use == 0 and not gate._queue


def test_waking_the_gate_ends_a_cancelled_wait_before_its_next_poll():
    gate = wl.AssemblyGate(Machine(4, 4), poll_seconds=10)
    holding, done, cancelled = threading.Event(), threading.Event(), threading.Event()
    outcome = []

    def holder():
        with gate.reserve(GB):
            holding.set()
            done.wait(30)

    def waiter():
        try:
            with gate.reserve(3 * GB, cancel_check=cancelled.is_set):
                outcome.append("entered")
        except ConversionCancelled:
            outcome.append("cancelled")

    first = threading.Thread(target=holder)
    first.start()
    holding.wait(5)
    second = threading.Thread(target=waiter)
    second.start()
    deadline = time.monotonic() + 5
    while not gate._queue and time.monotonic() < deadline:
        time.sleep(0.005)
    time.sleep(0.2)  # into the 10 s poll
    started = time.monotonic()
    cancelled.set()
    gate.wake()
    second.join(5)
    assert outcome == ["cancelled"] and time.monotonic() - started < 2
    done.set()
    first.join(5)
    assert gate._in_use == 0


def test_the_gate_no_longer_knows_a_finishing_narration(quick_gate):
    with pytest.raises(TypeError):
        with quick_gate.reserve(GB, finishing_check=lambda: True):
            pass
    with pytest.raises(TypeError):
        wl.assemble(1, lambda: None, lambda: None, finishing_check=lambda: True)


def test_waiting_for_room_without_a_gate_stops_when_cancelled(monkeypatch):
    monkeypatch.setattr(wl, "DISK_RETRY_PAUSE_SECONDS", 30)
    cancelled = threading.Event()
    threading.Timer(0.1, cancelled.set).start()
    started = time.monotonic()
    wl.AssemblyPlace(None, True, 0).wait_for_room(cancelled.is_set)
    assert time.monotonic() - started < 2


# --------------------------------------------------------------------------- publication: the commit boundary


def _finished(tmp_path: Path) -> Path:
    finished = tmp_path / "finished.bin"
    finished.write_bytes(b"MP3" * 1000)
    return finished


def test_a_cancel_before_the_commit_publishes_nothing_and_leaves_no_staging(tmp_path):
    destination = tmp_path / "out" / "book.mp3"
    with pytest.raises(ConversionCancelled):
        publication.publish_file(_finished(tmp_path), destination, cancel_check=lambda: True)
    assert not destination.exists()
    assert [p.name for p in destination.parent.iterdir()] == []


def test_a_cancel_that_arrives_after_the_commit_check_leaves_the_published_file_whole(tmp_path, monkeypatch):
    """The linearization point is the atomic rename. A Cancel after the last check loses: the file is complete and stays."""
    destination = tmp_path / "out" / "book.mp3"
    cancelled = threading.Event()
    real = publication._publish_no_clobber

    def commit(staged, final):
        cancelled.set()  # pressed at the instant of the commit
        return real(staged, final)

    monkeypatch.setattr(publication, "_publish_no_clobber", commit)
    produced = publication.publish_file(_finished(tmp_path), destination, cancel_check=cancelled.is_set)
    assert produced == destination and destination.read_bytes() == b"MP3" * 1000
    assert [p.name for p in destination.parent.iterdir()] == ["book.mp3"]


def test_a_cancel_that_lands_during_the_final_flush_is_still_seen_before_the_commit(tmp_path, monkeypatch):
    """Between publish()'s first look and the rename sits the fsync of the staged file; a Cancel latched there must be
    seen by the last look, immediately before the one operation that commits the name."""
    destination = tmp_path / "out" / "book.mp3"
    cancelled = threading.Event()
    real_flush = publication.Stage._flush_staged

    def flush(self):
        real_flush(self)
        cancelled.set()  # pressed while the staged file is being flushed, after the first look

    monkeypatch.setattr(publication.Stage, "_flush_staged", flush)
    with pytest.raises(ConversionCancelled):
        publication.publish_file(_finished(tmp_path), destination, cancel_check=cancelled.is_set)
    assert cancelled.is_set() and not destination.exists()
    assert [p.name for p in destination.parent.iterdir()] == []


def test_a_cancel_during_the_copy_into_staging_publishes_nothing(tmp_path, monkeypatch):
    destination = tmp_path / "out" / "book.mp3"
    cancelled = threading.Event()
    real = publication._copy_chunk

    def copy(reader, writer):
        cancelled.set()
        return real(reader, writer)

    monkeypatch.setattr(publication, "_copy_chunk", copy)
    with pytest.raises(ConversionCancelled):
        publication.publish_file(_finished(tmp_path), destination, cancel_check=cancelled.is_set)
    assert not destination.exists() and [p.name for p in destination.parent.iterdir()] == []


def test_an_existing_destination_is_never_touched_by_a_cancelled_publication(tmp_path):
    destination = tmp_path / "out" / "book.mp3"
    destination.parent.mkdir()
    destination.write_bytes(b"earlier")
    with pytest.raises(ConversionCancelled):
        publication.publish_file(_finished(tmp_path), destination, overwrite=True, cancel_check=lambda: True)
    assert destination.read_bytes() == b"earlier"


def test_publication_without_a_cancel_check_behaves_as_before(tmp_path):
    destination = tmp_path / "out" / "book.mp3"
    assert publication.publish_file(_finished(tmp_path), destination) == destination
    assert destination.read_bytes() == b"MP3" * 1000


# --------------------------------------------------------------------------- the Edge request loop


def test_the_direct_request_loop_makes_no_further_attempt_after_cancel(monkeypatch, tmp_path):
    from tts.epub2tts_edge import epub2tts_edge as engine

    cancelled = threading.Event()
    attempts = []

    class FailingCommunicate:
        def __init__(self, sentence, speaker):
            attempts.append(sentence)

        async def save(self, filename):
            Path(filename).write_bytes(b"partial")
            cancelled.set()  # Cancel lands while the first attempt is failing
            raise ConnectionResetError("transient")

    monkeypatch.setattr(engine.edge_tts, "Communicate", FailingCommunicate)
    monkeypatch.setattr(engine, "RETRY_BASE_DELAY_SEC", 30.0)
    target = tmp_path / "clip.mp3"
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        engine.run_edgespeak("Hello there.", "v", str(target), cancel_check=cancelled.is_set)
    assert len(attempts) == 1 and time.monotonic() - started < 3
    assert not target.exists(), "the failed attempt's partial audio is not left behind"


def test_a_cancel_latched_before_the_first_request_makes_none(monkeypatch, tmp_path):
    from tts.epub2tts_edge import epub2tts_edge as engine

    constructed = []

    class Communicate:
        def __init__(self, sentence, speaker):
            constructed.append(sentence)

        async def save(self, filename):
            Path(filename).write_bytes(b"audio")

    monkeypatch.setattr(engine.edge_tts, "Communicate", Communicate)
    target = tmp_path / "clip.mp3"
    with pytest.raises(ConversionCancelled):
        engine.run_edgespeak("Hello there.", "v", str(target), cancel_check=lambda: True)
    assert constructed == [] and not target.exists()


def test_the_direct_request_loop_does_not_sit_out_a_back_off_after_cancel(monkeypatch, tmp_path):
    from tts.epub2tts_edge import epub2tts_edge as engine

    cancelled = threading.Event()
    attempts = []

    class FailingCommunicate:
        def __init__(self, sentence, speaker):
            attempts.append(sentence)

        async def save(self, filename):
            raise ConnectionResetError("transient")

    monkeypatch.setattr(engine.edge_tts, "Communicate", FailingCommunicate)
    monkeypatch.setattr(engine, "RETRY_BASE_DELAY_SEC", 30.0)
    threading.Timer(0.2, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        engine.run_edgespeak("Hello there.", "v", str(tmp_path / "clip.mp3"), cancel_check=cancelled.is_set)
    assert len(attempts) == 1 and time.monotonic() - started < 3


def test_an_in_flight_direct_request_is_abandoned_on_cancel(monkeypatch, tmp_path):
    from tts.epub2tts_edge import epub2tts_edge as engine

    cancelled = threading.Event()
    abandoned = []

    class SlowCommunicate:
        def __init__(self, sentence, speaker):
            pass

        async def save(self, filename):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                abandoned.append(True)
                raise

    monkeypatch.setattr(engine.edge_tts, "Communicate", SlowCommunicate)
    threading.Timer(0.2, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        engine.run_edgespeak("Hello there.", "v", str(tmp_path / "clip.mp3"), cancel_check=cancelled.is_set)
    assert abandoned == [True] and time.monotonic() - started < 3


def test_eight_workers_make_no_request_after_the_latch(monkeypatch, tmp_path):
    """Eight conversions, each parked inside its first request at a barrier; Cancel is pressed while all eight are there;
    every request then fails as a transient would. Not one of them makes a second request, every conversion ends as a
    Cancel, and nothing is published. Deterministic: the barrier, not timing, decides who is where when Cancel lands."""
    from tts.epub2tts_edge import epub2tts_edge as engine
    from tts.epub2tts_edge import runner

    workers = 8
    cancelled = threading.Event()
    all_parked = threading.Barrier(workers + 1)
    constructed = []
    lock = threading.Lock()

    class ParkedCommunicate:
        def __init__(self, sentence, speaker):
            with lock:
                constructed.append(threading.get_ident())

        async def save(self, filename):
            await asyncio.get_running_loop().run_in_executor(None, all_parked.wait)
            raise ConnectionResetError("transient")

    monkeypatch.setattr(engine.edge_tts, "Communicate", ParkedCommunicate)
    monkeypatch.setattr(engine, "RETRY_BASE_DELAY_SEC", 30.0)
    monkeypatch.setattr(engine, "ensure_punkt", lambda: None, raising=False)
    sources = []
    for n in range(workers):
        folder = tmp_path / "in" / str(n)
        folder.mkdir(parents=True)
        source = folder / "book.txt"
        source.write_text("# One\n\nA sentence to read.\n", encoding="utf-8")
        sources.append(source)
    outcomes: dict[int, object] = {}

    def convert(n: int) -> None:
        try:
            outcomes[n] = runner.run_conversion_job(str(sources[n]), output_dir=str(tmp_path / "out" / str(n)),
                                                    audio_format="mp3", cancel_check=cancelled.is_set)
        except BaseException as exc:  # noqa: BLE001 - recorded, then judged
            outcomes[n] = exc

    threads = [threading.Thread(target=convert, args=(n,)) for n in range(workers)]
    for thread in threads:
        thread.start()
    all_parked.wait(timeout=30)  # every worker is inside its first request
    cancelled.set()
    for thread in threads:
        thread.join(30)
    assert all(not t.is_alive() for t in threads)
    assert all(isinstance(outcomes[n], ConversionCancelled) for n in range(workers)), outcomes
    assert len(constructed) == workers, "exactly one request per worker: none after the latch"
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").rglob("*.mp3"))


# --------------------------------------------------------------------------- the local engines and the panel


@pytest.fixture
def fake_kokoro(monkeypatch):
    import numpy as np
    import tts.kokoro_synth as ks

    calls: list[str] = []

    class Pipeline:
        def __call__(self, text, voice=None, speed=1.0, split_pattern=None):
            calls.append(text)
            yield ("graphemes", "phonemes", (0.3 * np.sin(2 * np.pi * 220 * np.arange(6000) / 24000)).astype(np.float32))

    monkeypatch.setattr(ks, "_get_pipeline", lambda lang_code: Pipeline())
    return calls


def test_kokoro_stops_before_its_one_encode_when_cancelled_after_the_last_chunk(tmp_path, fake_kokoro):
    """The model has rendered everything; the Cancel lands before the encode: nothing is written."""
    import tts.kokoro_synth as ks

    source = tmp_path / "k.txt"
    source.write_text("Words to read aloud.", encoding="utf-8")
    out = tmp_path / "k.mp3"
    with pytest.raises(ConversionCancelled):
        ks.kokoro_file_to_mp3(str(source), str(out), voice_id="af_heart", log=lambda s: None,
                              cancel_check=lambda: bool(fake_kokoro))  # latched once the model has been asked
    assert fake_kokoro and not out.exists()


def test_the_local_engine_routes_run_under_the_runs_cancel_control(monkeypatch):
    """Kokoro and Chatterbox encode through pydub; inside the control block that encode answers to the run's Cancel."""
    from tts import epub2tts_gui as panel_module

    seen: dict = {}

    def fake_local(item, params, log, synthesize, cancel_check=None):
        seen["control"] = ffmpeg_watch.current_cancel_check()
        seen["passed"] = cancel_check

    monkeypatch.setattr(panel_module, "_convert_with_local_engine", fake_local)

    def check() -> bool:
        return False

    params = {"voice_id": "v", "kokoro_speed": 1.0, "end_pause": 0, "paragraph_pause": 50, "bitrate": "192k"}
    item = {"source": Path("x.txt"), "destination": Path("y.mp3")}
    for convert in (panel_module.convert_with_kokoro, panel_module.convert_with_chatterbox):
        seen.clear()
        convert(item, params, None, lambda s: None, check)
        assert seen["control"] is check and seen["passed"] is check, convert.__name__
    assert ffmpeg_watch.current_cancel_check() is None, "the control is released with the block"


def test_the_panels_cancel_wakes_the_watchdog_and_the_gate():
    """Pressing Cancel does not wait for anybody's next poll: the panel wakes the FFmpeg watchdog and the memory gate."""
    import source_probe

    cancel_job = source_probe.function("tts/epub2tts_gui.py", "cancel_job")
    called = source_probe.calls(cancel_job)
    assert {"request_cancel", "wake"} <= called
    assert source_probe.call_order(cancel_job, {"request_cancel", "wake"}) == ["request_cancel", "wake", "wake"], \
        "the latch first, then both wakes"


def test_the_folder_request_is_abandoned_on_cancel_too(monkeypatch, tmp_path):
    from tts import batch_convert

    cancelled = threading.Event()
    abandoned = []

    class SlowCommunicate:
        def __init__(self, text, voice, rate):
            pass

        async def save(self, path):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                abandoned.append(True)
                raise

    monkeypatch.setattr(batch_convert.edge_tts, "Communicate", SlowCommunicate)
    threading.Timer(0.2, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        batch_convert.synthesize_chunk_mp3("Hello.", str(tmp_path / "c.mp3"), "v", "+0%", cancel_check=cancelled.is_set)
    assert abandoned == [True] and time.monotonic() - started < 3
