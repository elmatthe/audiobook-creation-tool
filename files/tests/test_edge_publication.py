"""v0.7.1 — how a finished Edge narration reaches its final name (``tts.publication``), on every Edge route.

The independent review (Codex, HIGH-001) reproduced: direct output staged in the system temp folder and moved with
``shutil.move``, which copies straight onto the final name across filesystems (and on Windows also when the name is
taken); the folder route encoding straight onto its final name; ``overwrite=False`` not being enforced; and
``discard_partial`` deleting whatever sat at a planned path.

The destructive scenarios use fault injection, never a real interruption. The races and the Windows lock are real.
"""

from __future__ import annotations

import contextlib
import errno
import io
import multiprocessing
import os
import shutil
import struct
import threading
import time
from pathlib import Path

import pytest
from pydub import AudioSegment
from pydub.exceptions import CouldntEncodeError
from pydub.generators import Sine

from shared import ffmpeg_utils, output_paths
from shared.cancellation import ConversionCancelled
from tts import batch_convert, edge_failures, output_names, publication, worker_limits
from tts import epub2tts_gui as panel_module
from tts.epub2tts_edge import epub2tts_edge as engine
from tts.epub2tts_edge import runner

windows_only = pytest.mark.skipif(os.name != "nt", reason="a Windows lock")
needs_ffmpeg = pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(), reason="requires a real ffmpeg/ffprobe pair")


def stage_files(folder: Path) -> list[Path]:
    return [p for p in folder.rglob("*") if p.name.startswith(output_paths.TEMP_SIBLING_PREFIX)]


def finished_file(folder: Path, payload: bytes = b"F" * 300_000) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "finished.mp3"
    path.write_bytes(payload)
    return path


@pytest.fixture()
def workspace(tmp_path):
    return tmp_path / "scratch", tmp_path / "run"


# --------------------------------------------------------------------------- #
# A/B/C. Finished first, private staging on the destination's filesystem, one atomic operation
# --------------------------------------------------------------------------- #


def test_a_file_is_published_complete_and_its_source_is_left(workspace):
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "deep" / "book-Voice.mp3"

    assert publication.publish_file(finished, destination) == destination

    assert destination.read_bytes() == finished.read_bytes()
    assert finished.exists(), "the caller's scratch copy is the caller's to remove"
    assert stage_files(run) == []


def test_staging_is_beside_the_destination_and_is_never_an_mp3(workspace):
    _scratch, run = workspace
    destination = run / "book-Voice.mp3"
    with publication.Stage(destination) as stage:
        assert stage.path.parent == destination.parent, "same folder, so same filesystem, whatever the temp folder is"
        assert stage.path.suffix == publication.STAGE_SUFFIX != ".mp3"
        assert stage.path.name.startswith(output_paths.TEMP_SIBLING_PREFIX)
    assert stage_files(run) == []


def test_the_final_name_does_not_exist_until_the_publishing_operation(workspace, monkeypatch):
    """Watches the final name at every step of a simulated cross-volume transfer."""
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    seen = []
    real_copy, real_publish = publication._copy_chunk, publication._publish_no_clobber

    def copy(reader, writer):
        seen.append(destination.exists())
        return real_copy(reader, writer)

    def publish(staged, final):
        seen.append(destination.exists())
        assert Path(staged).stat().st_size == finished.stat().st_size, "staging is complete first"
        real_publish(staged, final)

    monkeypatch.setattr(publication, "_copy_chunk", copy)
    monkeypatch.setattr(publication, "_publish_no_clobber", publish)
    publication.publish_file(finished, destination)

    assert seen and not any(seen)
    assert destination.read_bytes() == finished.read_bytes()


def test_a_cross_volume_source_never_reaches_the_final_name_by_copy(workspace, monkeypatch):
    """No rename, link or move is ever tried between the scratch folder and the destination: the only copy is into
    staging, and what gets the final name is the staged file. So a different volume changes nothing."""
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    renames = []
    real_rename = os.rename

    def rename(src, dst, **kwargs):
        renames.append((Path(src), Path(dst)))
        if Path(src).parent == scratch:
            raise OSError(errno.EXDEV, "simulated: another volume", str(src), 17, str(dst))
        return real_rename(src, dst, **kwargs)

    monkeypatch.setattr(os, "rename", rename)
    monkeypatch.setattr(shutil, "move", lambda *a, **k: pytest.fail("shutil.move is not a publication"))
    publication.publish_file(finished, destination)

    assert destination.read_bytes() == finished.read_bytes()
    if os.name == "nt":
        assert [(src.parent, dst) for src, dst in renames] == [(run, destination)]


@pytest.mark.parametrize("failure,message", [
    (OSError(errno.ENOSPC, "simulated: no space left on device"), "not enough free disk space"),
    (OSError(errno.EIO, "simulated: the drive went away"), "EIO|Errno 5|the drive went away"),
])
def test_an_interrupted_copy_leaves_nothing_under_the_final_name(workspace, monkeypatch, failure, message):
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    steps = []
    real_copy = publication._copy_chunk

    def dying_copy(reader, writer):
        if steps:
            raise failure
        steps.append(1)
        writer.write(reader.read(1000))
        return True

    monkeypatch.setattr(publication, "_copy_chunk", dying_copy)
    with pytest.raises(publication.PublicationError, match=message):
        publication.publish_file(finished, destination)
    monkeypatch.setattr(publication, "_copy_chunk", real_copy)

    assert not destination.exists()
    assert stage_files(run) == []
    assert finished.exists()


def test_a_short_copy_is_refused_even_when_nothing_raised(workspace, monkeypatch):
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"

    def short_copy(reader, writer):
        data = reader.read(1000)
        reader.seek(0, 2)
        writer.write(data[:500])
        return False

    monkeypatch.setattr(publication, "_copy_chunk", short_copy)
    with pytest.raises(publication.PublicationError, match="500 bytes of 300000"):
        publication.publish_file(finished, destination)
    assert not destination.exists() and stage_files(run) == []


def test_an_empty_result_is_never_published(workspace):
    _scratch, run = workspace
    destination = run / "book-Voice.mp3"
    with pytest.raises(publication.PublicationError, match="empty"):
        with publication.Stage(destination) as stage:  # an encode that wrote nothing
            stage.publish()
    assert not destination.exists() and stage_files(run) == []


def test_a_publication_failure_is_never_retried_as_a_service_failure():
    """Neither Edge route synthesises the whole file again because a disk or the memory was full."""
    for failure in (publication.PublicationError("disk full"), publication.DestinationExists("taken"), MemoryError()):
        assert not edge_failures.is_retryable(failure)
        assert edge_failures.final_error(failure, 1) is failure


def test_a_full_disk_is_named_whichever_windows_error_says_so():
    destination = Path("run") / "book-Voice.mp3"
    assert "disk space" in str(publication._explain(destination, OSError(errno.ENOSPC, "full")))
    if os.name == "nt":
        assert "disk space" in str(publication._explain(destination, OSError(0, "full", None, 39)))
        assert "disk space" in str(publication._explain(destination, OSError(0, "full", None, 112)))


# --------------------------------------------------------------------------- #
# D. overwrite=False: atomic, whatever appeared after planning
# --------------------------------------------------------------------------- #


def test_overwrite_false_never_replaces_an_existing_file(workspace):
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"theirs")

    with pytest.raises(FileExistsError) as caught:
        publication.publish_file(finished, destination, overwrite=False)

    assert isinstance(caught.value, publication.DestinationExists)
    assert destination.read_bytes() == b"theirs"
    assert stage_files(run) == []


def test_a_destination_appearing_after_staging_began_is_not_replaced(workspace, monkeypatch):
    """The window a look-then-move leaves: the name was free at every check before the operation."""
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    real_publish = publication._publish_no_clobber

    def appears_first(staged, final):
        Path(final).write_bytes(b"appeared at the last instant")
        real_publish(staged, final)

    monkeypatch.setattr(publication, "_publish_no_clobber", appears_first)
    with pytest.raises(publication.DestinationExists):
        publication.publish_file(finished, destination, overwrite=False)

    assert destination.read_bytes() == b"appeared at the last instant"
    assert stage_files(run) == []


def test_a_folder_at_the_destination_is_never_replaced(workspace):
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    destination.mkdir(parents=True)
    for overwrite in (False, True):
        with pytest.raises(publication.PublicationError):
            publication.publish_file(finished, destination, overwrite=overwrite)
    assert destination.is_dir() and stage_files(run) == []


def test_refuse_existing_stops_a_doomed_conversion_before_any_synthesis(workspace):
    _scratch, run = workspace
    destination = run / "book-Voice.mp3"
    publication.refuse_existing(destination, overwrite=False)  # nothing there: no complaint
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"theirs")
    publication.refuse_existing(destination, overwrite=True)
    with pytest.raises(FileExistsError):
        publication.refuse_existing(destination, overwrite=False)


def test_threads_racing_for_one_name_produce_one_winner_and_one_whole_file(workspace):
    _scratch, run = workspace
    destination = run / "book-Voice.mp3"
    racers = 16
    barrier = threading.Barrier(racers)
    outcomes: list[object] = []
    lock = threading.Lock()

    def racer(index: int) -> None:
        payload = bytes([65 + index]) * 200_000
        source = finished_file(run.parent / f"scratch{index}", payload)
        with publication.Stage(destination, overwrite=False) as stage:
            stage.receive(source)
            barrier.wait(30)
            try:
                stage.publish()
                result: object = index
            except publication.DestinationExists:
                result = "lost"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=racer, args=(index,)) for index in range(racers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    winners = [outcome for outcome in outcomes if outcome != "lost"]
    assert len(outcomes) == racers and len(winners) == 1
    assert destination.read_bytes() == bytes([65 + winners[0]]) * 200_000
    assert stage_files(run) == []


def _process_racer(staged: str, destination: str, barrier, results) -> None:
    barrier.wait(60)
    try:
        publication._publish_no_clobber(Path(staged), Path(destination))
        results.put(staged)
    except FileExistsError:
        results.put("lost")


def test_processes_racing_for_one_name_produce_one_winner(workspace):
    """Separate processes, because threads are partly serialized by the GIL. The production primitive, not a stand-in."""
    _scratch, run = workspace
    run.mkdir(parents=True)
    destination = run / "book-Voice.mp3"
    context = multiprocessing.get_context("spawn")
    racers = 4
    barrier, results = context.Barrier(racers), context.Queue()
    staged = []
    for index in range(racers):
        path = run / f"racer{index}.part"
        path.write_bytes(bytes([65 + index]) * 100_000)
        staged.append(path)
    processes = [context.Process(target=_process_racer, args=(str(path), str(destination), barrier, results))
                 for path in staged]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=90) for _ in processes]
    for process in processes:
        process.join(60)

    winners = [outcome for outcome in outcomes if outcome != "lost"]
    assert len(winners) == 1
    assert destination.read_bytes()[:1] == bytes([65 + staged.index(Path(winners[0]))])
    assert destination.stat().st_size == 100_000


def test_elsewhere_the_no_clobber_primitive_is_a_hard_link_and_an_unsupported_drive_fails_safely(workspace, monkeypatch):
    """A POSIX ``rename`` replaces silently, so it must never be the no-clobber path there."""
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    monkeypatch.setattr(publication, "_IS_WINDOWS", False)
    monkeypatch.setattr(publication.os, "rename", lambda *a, **k: pytest.fail("rename would replace on POSIX"))
    monkeypatch.setattr(publication.os, "link", lambda *a, **k: (_ for _ in ()).throw(
        OSError(errno.ENOTSUP, "simulated: no hard links on this drive")))
    with pytest.raises(publication.PublicationError, match="cannot publish a file without risking"):
        publication.publish_file(finished, destination, overwrite=False)
    assert not destination.exists(), "there is no fallback to a copy or a check-then-move"


# --------------------------------------------------------------------------- #
# E. overwrite=True: atomic replacement, the old file valid until then
# --------------------------------------------------------------------------- #


def test_overwrite_true_replaces_only_once_the_new_file_is_complete(workspace, monkeypatch):
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"the old valid output")
    seen = []
    real_copy, real_replace = publication._copy_chunk, publication._publish_replacing

    def copy(reader, writer):
        seen.append(destination.read_bytes())
        return real_copy(reader, writer)

    def replace(staged, final):
        seen.append(destination.read_bytes())
        real_replace(staged, final)

    monkeypatch.setattr(publication, "_copy_chunk", copy)
    monkeypatch.setattr(publication, "_publish_replacing", replace)
    monkeypatch.setattr(os, "unlink", lambda *a, **k: pytest.fail("the destination is never deleted first"))
    publication.publish_file(finished, destination, overwrite=True)
    monkeypatch.undo()

    assert set(seen) == {b"the old valid output"}
    assert destination.read_bytes() == finished.read_bytes()
    assert stage_files(run) == []


def test_a_failed_staging_keeps_the_old_output_under_overwrite(workspace, monkeypatch):
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"the old valid output")

    def full_disk(reader, writer):
        raise OSError(errno.ENOSPC, "simulated")

    monkeypatch.setattr(publication, "_copy_chunk", full_disk)
    with pytest.raises(publication.PublicationError, match="disk space"):
        publication.publish_file(finished, destination, overwrite=True)
    assert destination.read_bytes() == b"the old valid output"
    assert stage_files(run) == []


@windows_only
def test_a_destination_locked_by_another_program_is_kept_and_the_reason_is_given(workspace):
    """A real Windows lock: Python's own ``open`` does not share delete, as a media player may not."""
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"the old valid output")
    naps = []
    with open(destination, "rb"):
        with publication.Stage(destination, overwrite=True, sleep=naps.append) as stage:
            stage.receive(finished)
            with pytest.raises(publication.PublicationError, match="in use by another program"):
                stage.publish()
    assert naps == list(publication._LOCK_RETRY_DELAYS), "bounded: it tried, waited and then said so"
    assert destination.read_bytes() == b"the old valid output"
    assert stage_files(run) == []


@contextlib.contextmanager
def exclusively_held(path: Path):
    """A real Windows lock: no sharing at all, as a scanner may hold a just-closed file. ``yield`` a release function."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                     wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0, None)  # GENERIC_READ, no sharing, OPEN_EXISTING
    assert handle != wintypes.HANDLE(-1).value, ctypes.get_last_error()
    released = threading.Event()

    def release():
        if not released.is_set():
            released.set()
            kernel32.CloseHandle(handle)

    try:
        yield release
    finally:
        release()


def _release_after(release, seconds=0.3):
    timer = threading.Timer(seconds, release)
    timer.start()
    return timer


@windows_only
def test_a_real_lock_on_the_staged_file_is_waited_out(workspace):
    """Python's own ``open`` reports this as a bare EACCES with no Windows error attached, and it used to fail the attempt
    at once, with the whole narration lost, in the moment a scanner has a just-closed file (found by review)."""
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    with publication.Stage(destination) as stage:
        stage.receive(finished)
        with exclusively_held(stage.path) as release:
            timer = _release_after(release)
            stage.publish()
            timer.join()
    assert destination.read_bytes() == finished.read_bytes()


@windows_only
def test_a_real_lock_on_the_finished_file_is_waited_out(workspace):
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    with exclusively_held(finished) as release:
        timer = _release_after(release)
        publication.publish_file(finished, destination)
        timer.join()
    assert destination.read_bytes() == finished.read_bytes()


@windows_only
@needs_ffmpeg
def test_a_real_lock_is_not_mistaken_for_an_invalid_mp3(tmp_path):
    ffmpeg_utils.configure_pydub()
    path = tmp_path / "a.mp3"
    Sine(440, sample_rate=24000).to_audio_segment(duration=500, volume=-20).export(str(path), format="mp3")
    with exclusively_held(path) as release:
        timer = _release_after(release)
        publication.verify_finished_mp3(path)
        timer.join()


@windows_only
def test_a_lock_that_never_lets_go_fails_within_its_bound_and_changes_nothing(workspace):
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    naps = []
    with exclusively_held(finished):
        with pytest.raises(publication.PublicationError, match="in use by another program"):
            with publication.Stage(destination, sleep=naps.append) as stage:
                stage.receive(finished)
    assert naps[:len(publication._LOCK_RETRY_DELAYS)] == list(publication._LOCK_RETRY_DELAYS)
    assert not destination.exists() and stage_files(run) == []


def test_a_brief_lock_at_the_publishing_operation_is_waited_out(workspace, monkeypatch):
    scratch, run = workspace
    finished = finished_file(scratch)
    destination = run / "book-Voice.mp3"
    busy = PermissionError(errno.EACCES, "simulated: a scanner has it")
    busy.winerror = 32
    attempts = []
    real_publish = publication._publish_no_clobber

    def scanner_then_free(staged, final):
        attempts.append(1)
        if len(attempts) < 3:
            raise busy
        real_publish(staged, final)

    monkeypatch.setattr(publication, "_publish_no_clobber", scanner_then_free)
    with publication.Stage(destination, sleep=lambda _s: None) as stage:
        stage.receive(finished)
        stage.publish()
    assert destination.read_bytes() == finished.read_bytes()
    assert len(attempts) == 3


# --------------------------------------------------------------------------- #
# G/I. Only the attempt's own staging file is ever cleaned up
# --------------------------------------------------------------------------- #


def test_a_failing_attempt_removes_its_own_staging_and_nothing_else(workspace):
    _scratch, run = workspace
    destination = run / "book-Voice.mp3"
    run.mkdir(parents=True)
    neighbours = {run / ".act-tmp-not-mine.part": b"a", run / "notes.part": b"b", run / "sibling-Voice.mp3": b"c",
                  run / f".act-tmp-{'0' * 13}.part": b"d"}
    for path, data in neighbours.items():
        path.write_bytes(data)

    with pytest.raises(RuntimeError):
        with publication.Stage(destination) as stage:
            stage.path.write_bytes(b"half an encode")
            raise RuntimeError("the encoder died")

    assert not destination.exists()
    for path, data in neighbours.items():
        assert path.read_bytes() == data


def test_an_open_handle_held_by_a_failed_encoder_does_not_keep_the_staging_file(workspace):
    """A failed pydub export still holds the staged file open in its traceback, and Windows will not delete an open
    file: this is exactly how an orphan would appear on every failed encode."""
    _scratch, run = workspace
    destination = run / "book-Voice.mp3"

    def failing_export(path):
        handle = open(path, "wb")  # noqa: SIM115 - held by this frame, as pydub's export holds its out_f
        handle.write(b"half an encode")
        raise RuntimeError("ffmpeg failed")

    with pytest.raises(RuntimeError):
        with publication.Stage(destination, sleep=lambda _s: None) as stage:
            failing_export(stage.path)
    assert stage_files(run) == []


def _kept_leftover(run: Path, pid_field: str, *, old: bool = True) -> Path:
    path = run / f"{output_paths.TEMP_SIBLING_PREFIX}{pid_field}abcde{publication.STAGE_SUFFIX}"
    path.write_bytes(b"left by an interrupted run")
    if old:
        os.utime(path, (1_000_000, 1_000_000))
    return path


def test_a_recent_file_naming_a_process_unknown_here_may_be_another_computers(workspace):
    """On a shared output folder, another computer's process number means nothing here (found by review)."""
    _scratch, run = workspace
    run.mkdir(parents=True)
    recent = _kept_leftover(run, "00000bad", old=False)
    assert publication.sweep_orphans(run, is_alive=lambda pid: False) == []
    assert recent.exists()


def test_an_orphan_of_a_dead_process_is_removed_and_a_live_ones_work_is_not(workspace):
    _scratch, run = workspace
    (run / "nested").mkdir(parents=True)
    dead = _kept_leftover(run, "00000bad")
    nested_dead = _kept_leftover(run / "nested", "00000bad")
    live = _kept_leftover(run, "00000a11")
    foreign = {run / ".act-tmp-00000badabcde.tmp", run / ".act-tmp-00000badabcdeX.part",
               run / ".act-tmp-book-1a2b3c.mp3", run / "book-Voice.mp3", run / "00000badabcde.part"}
    for path in foreign:
        path.write_bytes(b"not a staging file")

    removed = publication.sweep_orphans(run, is_alive=lambda pid: pid == 0xa11)

    assert set(removed) == {dead, nested_dead}
    assert live.exists()
    for path in foreign:
        assert path.exists(), path.name


def test_an_attempt_in_progress_in_this_process_is_never_swept(workspace):
    _scratch, run = workspace
    with publication.Stage(run / "book-Voice.mp3") as stage:
        assert publication.sweep_orphans(run) == []
        assert stage.path.exists()
    assert publication.sweep_orphans(run) == []


def test_this_process_can_sweep_what_an_earlier_attempt_could_not_remove(workspace, monkeypatch):
    """The OS would not let go of a staging file when the attempt ended. Nothing is using it now."""
    _scratch, run = workspace
    stage = publication.Stage(run / "book-Voice.mp3", sleep=lambda _s: None)
    stage.__enter__()
    leftover = stage.path
    monkeypatch.setattr(output_paths, "discard_temporary", lambda path: False)
    assert stage.discard() is False
    monkeypatch.undo()
    assert leftover.exists()

    assert publication.sweep_orphans(run) == [leftover]
    assert not leftover.exists()


def test_a_process_is_gone_only_when_it_provably_is():
    assert publication.process_is_alive(os.getpid()) is True
    if os.name == "nt":
        assert publication.process_is_alive(4) is True, "the Windows System process: not ours to open, and not gone"
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=int)
    process.start()
    gone = process.pid
    process.join(60)
    process.close()
    assert publication.process_is_alive(gone) is False


def test_the_sweep_does_not_follow_a_link_out_of_the_folder(workspace):
    _scratch, run = workspace
    outside = run.parent / "outside"
    outside.mkdir()
    victim = _kept_leftover(outside, "00000bad")
    run.mkdir(parents=True)
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(outside), str(run / "link"))  # needs no privilege, unlike a symbolic link
    else:
        os.symlink(outside, run / "link", target_is_directory=True)
    assert publication.sweep_orphans(run, is_alive=lambda pid: False) == []
    assert victim.exists()


def test_a_missing_or_absent_root_is_simply_nothing_to_sweep(tmp_path):
    assert publication.sweep_orphans(None) == []
    assert publication.sweep_orphans(tmp_path / "gone") == []


def test_the_staging_name_fits_wherever_a_planned_name_fits():
    """The name is stem-free, so it never exceeds the budget ``output_names`` keeps for a temporary sibling."""
    smallest_planned_name = len(f"x{output_names.SEPARATOR}L{output_names.EXTENSION}")
    assert (publication.STAGE_NAME_LENGTH
            <= smallest_planned_name + output_names.COLLISION_HEADROOM + output_names.PUBLISH_HEADROOM)


def test_the_real_staging_name_has_the_stated_length(tmp_path):
    with publication.Stage(tmp_path / "x.mp3") as stage:
        assert len(stage.path.name) == publication.STAGE_NAME_LENGTH


def test_the_deepest_folder_a_name_can_be_planned_in_still_has_room_for_the_staging_name():
    """Arithmetic against ``planned_name`` on a machine without long paths; no such folder is created."""
    budget = output_names.NameBudget(path_limit=259, directory_limit=247, windows=True)
    room = 259 - 1 - 7 - output_names.COLLISION_HEADROOM - output_names.PUBLISH_HEADROOM
    folder = "C:\\" + "d" * (room - 3)
    assert output_names.planned_name("x.txt", "L", folder, budget=budget) == "x-L.mp3"
    assert len(folder) + 1 + publication.STAGE_NAME_LENGTH <= 259


# --------------------------------------------------------------------------- #
# J. Nothing incomplete, silent or invalid counts as a success
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tone():
    ffmpeg_utils.configure_pydub()
    return Sine(440, sample_rate=24000).to_audio_segment(duration=2000, volume=-20)


@needs_ffmpeg
def test_a_real_encode_passes_the_finished_file_check(tmp_path, tone):
    path = tmp_path / "tone.mp3"
    tone.export(str(path), format="mp3", bitrate="192k")
    publication.verify_finished_mp3(path, len(tone))
    publication.require_audible(tone)


@needs_ffmpeg
@pytest.mark.parametrize("corrupt", [b"", b"this is not an mp3 at all" * 40])
def test_something_that_is_not_an_mp3_is_refused(tmp_path, corrupt):
    path = tmp_path / "bad.mp3"
    path.write_bytes(corrupt)
    with pytest.raises(publication.PublicationError, match="not a valid MP3"):
        publication.verify_finished_mp3(path)


@needs_ffmpeg
def test_an_encode_much_shorter_than_its_audio_is_refused(tmp_path, tone):
    path = tmp_path / "short.mp3"
    tone.export(str(path), format="mp3")
    with pytest.raises(publication.PublicationError, match="was encoded"):
        publication.verify_finished_mp3(path, 60_000)


@needs_ffmpeg
def test_a_truncated_encode_is_refused(tmp_path, tone):
    """A long encode cut off by the disk: its frames no longer add up to what was encoded."""
    path = tmp_path / "cut.mp3"
    longer = tone * 60
    longer.export(str(path), format="mp3", bitrate="192k")
    publication.verify_finished_mp3(path, len(longer))
    data = path.read_bytes()
    for kept in (0.5, 0.95):
        path.write_bytes(data[:int(len(data) * kept)])
        with pytest.raises(publication.PublicationError):
            publication.verify_finished_mp3(path, len(longer))


def test_a_narration_too_long_for_a_wav_is_refused_with_a_reason():
    """pydub encodes through a WAV, whose sizes are 32-bit: about 24.85 hours. Without this it is a bare struct.error."""
    class Oversized:
        max_dBFS = -10.0

        @property
        def raw_data(self):
            class Length:
                def __len__(self):
                    return 2 ** 32

            return Length()

    with pytest.raises(publication.PublicationError, match="over 24 hours"):
        publication.check_narration(Oversized())


@pytest.mark.parametrize("failure", [struct.error("'L' format requires 0 <= number <= 4294967295"),
                                     CouldntEncodeError("ffmpeg: No space left on device"), MemoryError()])
def test_the_folder_route_does_not_synthesise_a_whole_file_again_for_a_local_failure(tmp_path, monkeypatch, failure):
    """A failed encode counted as retryable: three passes of synthesis, each with the same full disk (found by review)."""
    source = source_file(tmp_path / "in")
    out = tmp_path / "run"
    target = out / "book-Voice.mp3"
    synthesised = []
    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3", lambda text, path, voice, rate: (synthesised.append(text),
                                                                                                 Path(path).write_bytes(b""))[0])
    monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)

    def failing_merge(chunk_paths, output_path, bitrate=None):
        raise failure

    monkeypatch.setattr(batch_convert, "merge_mp3s", failing_merge)
    status, _path, _message = batch_convert.convert_single_pdf(source, out, "v", "+0%", lambda _m: None, out_mp3=target)
    assert status == "failed"
    assert len(synthesised) == 1
    assert not target.exists() and stage_files(out) == []


@needs_ffmpeg
def test_digital_silence_from_end_to_end_is_refused():
    ffmpeg_utils.configure_pydub()
    with pytest.raises(publication.PublicationError, match="silent"):
        publication.require_audible(AudioSegment.silent(duration=500, frame_rate=24000))


@needs_ffmpeg
def test_a_very_quiet_narration_is_still_a_narration():
    ffmpeg_utils.configure_pydub()
    publication.require_audible(Sine(440, sample_rate=24000).to_audio_segment(duration=200, volume=-60))


# --------------------------------------------------------------------------- #
# The routes: every Edge entry point publishes through the one contract
# --------------------------------------------------------------------------- #


_CLIP: dict[str, bytes] = {}


def _clip() -> bytes:
    if "mp3" not in _CLIP:
        ffmpeg_utils.configure_pydub()
        buffer = io.BytesIO()
        Sine(440, sample_rate=24000).to_audio_segment(duration=200, volume=-20).export(buffer, format="mp3")
        _CLIP["mp3"] = buffer.getvalue()
    return _CLIP["mp3"]


@pytest.fixture()
def offline_engine(monkeypatch):
    """The real runner and engine; only the network request is replaced."""
    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)
    monkeypatch.setattr(engine, "run_edgespeak", lambda text, speaker, path: Path(path).write_bytes(_clip()))


@pytest.fixture()
def offline_folder(monkeypatch):
    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3", lambda text, path, voice, rate: Path(path).write_bytes(_clip()))
    monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)


def source_file(folder: Path, name: str = "book.txt") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("Title: T\nAuthor: A\n# Heading\n\nOne sentence here. Another one here.\n", encoding="utf-8")
    return path


def direct_item(source: Path, destination: Path) -> dict:
    return {"source": source, "destination": destination, "item_id": "occ-1", "direct": True}


def direct_params(overwrite: bool) -> dict:
    return {"pause_kw": {}, "speaker": "en-US-SteffanNeural", "bitrate": "192k", "overwrite": overwrite,
            "speech_prep": None}


@needs_ffmpeg
def test_the_standalone_runner_publishes_whole_and_refuses_a_taken_name(tmp_path, offline_engine):
    source = source_file(tmp_path / "in")
    out = tmp_path / "out"
    produced = Path(runner.run_conversion_job(str(source), output_dir=str(out), audio_format="mp3"))
    assert produced.parent == out.resolve() and produced.stat().st_size > 0
    first = produced.read_bytes()

    produced.write_bytes(b"someone edited this")
    with pytest.raises(FileExistsError):
        runner.run_conversion_job(str(source), output_dir=str(out), audio_format="mp3", overwrite=False)
    assert produced.read_bytes() == b"someone edited this"

    runner.run_conversion_job(str(source), output_dir=str(out), audio_format="mp3", overwrite=True)
    assert produced.read_bytes() == first
    assert stage_files(out) == []


@needs_ffmpeg
def test_the_panel_direct_route_refuses_a_taken_name_before_any_synthesis(tmp_path, monkeypatch):
    source = source_file(tmp_path / "in")
    destination = tmp_path / "run" / "book-Voice.mp3"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"appeared after planning")
    monkeypatch.setattr(runner, "run_conversion_job", lambda *a, **k: pytest.fail("nothing to synthesise for"))

    with pytest.raises(FileExistsError):
        panel_module.convert_with_edge_engine(direct_item(source, destination), direct_params(False), None, lambda: False)
    assert destination.read_bytes() == b"appeared after planning"


def test_the_panel_direct_route_refuses_a_name_taken_during_synthesis(tmp_path, monkeypatch):
    """Codex's reproduction: the name appears while the file is converting, and overwrite is off."""
    source = source_file(tmp_path / "in")
    destination = tmp_path / "run" / "book-Voice.mp3"

    def conversion(sourcefile, *, output_dir, **_kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"appeared during synthesis")
        produced = Path(output_dir) / "artifact.mp3"
        produced.write_bytes(b"F" * 1000)
        return str(produced)

    monkeypatch.setattr(runner, "run_conversion_job", conversion)
    with pytest.raises(FileExistsError):
        panel_module.convert_with_edge_engine(direct_item(source, destination), direct_params(False), None, lambda: False)
    assert destination.read_bytes() == b"appeared during synthesis"
    assert stage_files(destination.parent) == []


def test_the_panel_direct_route_interrupted_across_volumes_leaves_nothing(tmp_path, monkeypatch):
    """Codex's reproduction: half an MP3 was left under the final name when the cross-volume copy died."""
    source = source_file(tmp_path / "in")
    destination = tmp_path / "run" / "book-Voice.mp3"

    def conversion(sourcefile, *, output_dir, **_kwargs):
        produced = Path(output_dir) / "artifact.mp3"
        produced.write_bytes(b"F" * 1_000_000)
        return str(produced)

    def dying_copy(reader, writer):
        writer.write(reader.read(500_000))
        raise OSError(errno.ENOSPC, "simulated")

    monkeypatch.setattr(runner, "run_conversion_job", conversion)
    monkeypatch.setattr(publication, "_copy_chunk", dying_copy)
    with pytest.raises(publication.PublicationError):
        panel_module.convert_with_edge_engine(direct_item(source, destination), direct_params(False), None, lambda: False)
    assert not destination.exists()
    assert stage_files(destination.parent) == []


def test_the_panel_direct_route_overwrite_true_replaces_atomically(tmp_path, monkeypatch):
    source = source_file(tmp_path / "in")
    destination = tmp_path / "run" / "book-Voice.mp3"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")

    def conversion(sourcefile, *, output_dir, **_kwargs):
        produced = Path(output_dir) / "artifact.mp3"
        produced.write_bytes(b"new")
        return str(produced)

    monkeypatch.setattr(runner, "run_conversion_job", conversion)
    panel_module.convert_with_edge_engine(direct_item(source, destination), direct_params(True), None, lambda: False)
    assert destination.read_bytes() == b"new"


@needs_ffmpeg
def test_the_folder_route_encodes_in_staging_and_publishes_whole(tmp_path, offline_folder, monkeypatch):
    source = source_file(tmp_path / "in")
    out = tmp_path / "run"
    target = out / "sub" / "book-Voice.mp3"
    real_merge = batch_convert.merge_mp3s
    seen = {}

    def merge(chunk_paths, output_path, bitrate=None):
        seen["encoded_at"] = Path(output_path)
        seen["final_exists_during_encode"] = target.exists()
        return real_merge(chunk_paths, output_path, bitrate)

    monkeypatch.setattr(batch_convert, "merge_mp3s", merge)
    status, _path, message = batch_convert.convert_single_pdf(source, out, "v", "+0%", lambda _m: None, out_mp3=target)

    assert status == "success", message
    assert seen["encoded_at"].parent == target.parent and seen["encoded_at"] != target
    assert seen["final_exists_during_encode"] is False
    publication.verify_finished_mp3(target)
    assert stage_files(out) == []


@needs_ffmpeg
def test_the_folder_route_failing_export_leaves_an_existing_file_alone(tmp_path, offline_folder, monkeypatch):
    """Codex's reproduction: a failing export replaced an earlier good file with its partial."""
    source = source_file(tmp_path / "in")
    out = tmp_path / "run"
    target = out / "book-Voice.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"an earlier good file")

    def dying_export(self, out_f=None, **_kwargs):
        with open(out_f, "wb") as writer:
            writer.write(b"PARTIAL")
        raise OSError(errno.ENOSPC, "simulated: no space left on device")

    monkeypatch.setattr(AudioSegment, "export", dying_export)
    status, _path, message = batch_convert.convert_single_pdf(source, out, "v", "+0%", lambda _m: None, out_mp3=target,
                                                              overwrite=True)
    assert status == "failed" and "no space left" in message
    assert target.read_bytes() == b"an earlier good file"
    assert stage_files(out) == []


@needs_ffmpeg
def test_the_folder_route_refuses_a_taken_name_before_any_synthesis_unless_told_otherwise(tmp_path, monkeypatch):
    source = source_file(tmp_path / "in")
    out = tmp_path / "run"
    target = out / "book-Voice.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"theirs")
    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3", lambda *a, **k: pytest.fail("no synthesis"))
    reports = []

    status, _path, message = batch_convert.convert_single_pdf(source, out, "v", "+0%", lambda _m: None,
                                                              lambda stem, state: reports.append(state),
                                                              out_mp3=target)
    assert status == "failed" and "already exists" in message
    assert reports == ["failed"]
    assert target.read_bytes() == b"theirs"


@needs_ffmpeg
def test_the_folder_route_refuses_a_name_taken_during_synthesis(tmp_path, monkeypatch):
    source = source_file(tmp_path / "in")
    out = tmp_path / "run"
    target = out / "book-Voice.mp3"
    calls = []

    def synth(text, path, voice, rate):
        calls.append(text)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"appeared during synthesis")
        Path(path).write_bytes(_clip())

    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3", synth)
    monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)
    status, _path, message = batch_convert.convert_single_pdf(source, out, "v", "+0%", lambda _m: None, out_mp3=target)
    assert status == "failed" and "already exists" in message
    assert len(calls) == 1, "not synthesised again by the whole-file retry"
    assert target.read_bytes() == b"appeared during synthesis"
    assert stage_files(out) == []


@needs_ffmpeg
def test_the_standalone_batch_keeps_siblings_when_one_name_is_taken_late(tmp_path, offline_folder, monkeypatch):
    in_dir = tmp_path / "in"
    out = tmp_path / "out"
    for name in ("a.txt", "b.txt", "c.txt"):
        source_file(in_dir, name)
    real_publish = publication._publish_no_clobber

    def publish(staged, destination):
        # b's planned name is taken by someone else at the last instant, long after all three names were planned.
        if Path(destination).name == "b-Aria.mp3":
            Path(destination).write_bytes(b"late arrival")
        real_publish(staged, destination)

    monkeypatch.setattr(publication, "_publish_no_clobber", publish)
    ok, fail, error_log = batch_convert.run_batch_convert(in_dir, out, workers=3, use_tqdm=False, log=lambda _m: None,
                                                          label="Aria", speaker="en-US-AriaNeural")

    assert (ok, fail) == (2, 1)
    assert (out / "b-Aria.mp3").read_bytes() == b"late arrival"
    publication.verify_finished_mp3(out / "a-Aria.mp3")
    publication.verify_finished_mp3(out / "c-Aria.mp3")
    assert "already exists" in error_log.read_text(encoding="utf-8")
    assert stage_files(out) == []


def test_the_standalone_batch_removes_a_dead_runs_staging_but_not_a_live_runs_chunks(tmp_path, monkeypatch):
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    dead = _kept_leftover(out, "00000bad")
    monkeypatch.setattr(publication, "process_is_alive", lambda pid: False)
    active = out / ".tmp_chunks" / "live0000"
    active.mkdir(parents=True)
    (active / "chunk_001.mp3").write_bytes(b"another run is using this")
    stale = out / ".tmp_chunks" / "stale000"
    stale.mkdir()
    old = 1_000_000
    os.utime(stale, (old, old))

    batch_convert.run_batch_convert(in_dir, out, workers=1, use_tqdm=False, log=lambda _m: None, label="Aria",
                                    speaker="en-US-AriaNeural")

    assert not dead.exists()
    assert (active / "chunk_001.mp3").exists(), "another run's scratch is not a leftover"
    assert not stale.exists()


def test_a_finished_runs_empty_scratch_root_goes_and_a_busy_one_stays(tmp_path, offline_folder):
    in_dir = tmp_path / "in"
    source_file(in_dir)
    out = tmp_path / "out"
    active = out / ".tmp_chunks" / "live0000"
    active.mkdir(parents=True)
    batch_convert.run_batch_convert(in_dir, out, workers=1, use_tqdm=False, log=lambda _m: None, label="Aria",
                                    speaker="en-US-AriaNeural")
    assert active.exists()
    active.rmdir()
    batch_convert.run_batch_convert(in_dir, out, workers=1, use_tqdm=False, log=lambda _m: None, label="Aria",
                                    speaker="en-US-AriaNeural")
    assert not (out / ".tmp_chunks").exists()


@needs_ffmpeg
def test_a_narration_that_comes_out_silent_is_a_failure_on_both_routes(tmp_path, monkeypatch):
    """A source of nothing the voice can read (the engine sends no request and uses a 50 ms silence for each) used to
    be published as a silent MP3 and counted as a success."""
    ffmpeg_utils.configure_pydub()
    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)
    source = tmp_path / "in" / "cyrillic.txt"
    source.parent.mkdir()
    source.write_text("Привет мир.\n", encoding="utf-8")
    with pytest.raises(publication.PublicationError, match="silent"):
        runner.run_conversion_job(str(source), output_dir=str(tmp_path / "out"), audio_format="mp3")
    assert not (tmp_path / "out").exists()

    silence = tmp_path / "silence.mp3"
    AudioSegment.silent(duration=200, frame_rate=24000).export(str(silence), format="mp3")
    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3", lambda text, path, voice, rate: shutil.copyfile(silence, path))
    monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)
    target = tmp_path / "out2" / "x.mp3"
    status, _path, message = batch_convert.convert_single_pdf(source, tmp_path / "out2", "v", "+0%", lambda _m: None,
                                                              out_mp3=target)
    assert status == "failed" and "silent" in message
    assert not target.exists()


# --------------------------------------------------------------------------- #
# Cancel, before and during publication
# --------------------------------------------------------------------------- #


@needs_ffmpeg
def test_cancel_before_the_last_synthesis_step_publishes_nothing_on_either_route(tmp_path, offline_engine, offline_folder):
    source = source_file(tmp_path / "in")
    out = tmp_path / "out"
    with pytest.raises(ConversionCancelled):
        runner.run_conversion_job(str(source), output_dir=str(out), audio_format="mp3", cancel_check=lambda: True)
    assert not out.exists() or list(out.iterdir()) == []

    answers = iter([False, True])  # past the start, then cancelled at the chunk checkpoint
    target = out / "book-Voice.mp3"
    status, _path, _message = batch_convert.convert_single_pdf(source, out, "v", "+0%", lambda _m: None,
                                                               cancel_check=lambda: next(answers, True), out_mp3=target)
    assert status == "cancelled"
    assert not target.exists() and stage_files(out) == []


@needs_ffmpeg
def test_cancel_during_publication_never_leaves_a_partial_and_keeps_finished_work(tmp_path, offline_engine, monkeypatch):
    """A narration past its last synthesis step is finished work (``test_a_success_finishing_during_cancellation...``):
    a Cancel pressed mid-copy lets the copy finish, the name appears whole, and the item counts as a success."""
    source = source_file(tmp_path / "in")
    destination = tmp_path / "run" / "book-Voice.mp3"
    cancelled = threading.Event()
    real_copy = publication._copy_chunk
    during = []

    def copy(reader, writer):
        if Path(writer.name).parent == destination.parent:
            cancelled.set()  # the person presses Cancel with the copy into the run folder under way
        during.append(destination.exists())
        return real_copy(reader, writer)

    monkeypatch.setattr(publication, "_copy_chunk", copy)
    panel_module.convert_with_edge_engine(direct_item(source, destination), direct_params(False), None, cancelled.is_set)

    assert cancelled.is_set()
    assert not any(during)
    publication.verify_finished_mp3(destination)
    assert stage_files(destination.parent) == []


def _hold_the_gate(monkeypatch):
    """A gate another file is assembling at, with no room beside it, and every join big enough to ask."""
    tight = worker_limits.MemoryInfo(5 * 1024 ** 3, 16 * 1024 ** 3)  # 1 GiB usable
    gate = worker_limits.AssemblyGate(lambda: tight, poll_seconds=0.01)
    monkeypatch.setattr(worker_limits, "ASSEMBLY_GATE", gate)
    monkeypatch.setattr(worker_limits, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    return gate


def _route_waits_then_finishes(gate, convert, cancelled):
    """Runs *convert* while another assembly holds the gate; presses Cancel once it is waiting; then frees the gate."""
    outcome = {}

    def work():
        outcome["result"] = convert()

    with gate.reserve(1024 ** 3):  # the other file, assembling
        worker = threading.Thread(target=work)
        worker.start()
        deadline = time.monotonic() + 60
        while not gate._queue:
            assert time.monotonic() < deadline, "it never reached the gate"
            time.sleep(0.005)
        cancelled.set()
        time.sleep(0.05)
        assert worker.is_alive(), "Cancel does not throw away a finished narration waiting for its turn"
    worker.join(60)
    return outcome["result"]


@needs_ffmpeg
def test_cancel_during_the_memory_wait_keeps_a_finished_direct_narration(tmp_path, offline_engine, monkeypatch):
    """Whether a finished file survived a Cancel used to depend on its place in the queue (found by review)."""
    gate = _hold_the_gate(monkeypatch)
    source = source_file(tmp_path / "in")
    # The chapter's own join comes first; with the book's last checkpoint behind it, that one does not honour Cancel either.
    cancelled = threading.Event()
    produced = _route_waits_then_finishes(
        gate, lambda: runner.run_conversion_job(str(source), output_dir=str(tmp_path / "out"), audio_format="mp3",
                                                cancel_check=cancelled.is_set), cancelled)
    publication.verify_finished_mp3(produced)


@needs_ffmpeg
def test_cancel_during_the_memory_wait_keeps_a_finished_folder_narration(tmp_path, offline_folder, monkeypatch):
    gate = _hold_the_gate(monkeypatch)
    source = source_file(tmp_path / "in")
    target = tmp_path / "out" / "book-Voice.mp3"
    cancelled = threading.Event()
    answers_before_the_gate = iter([False, False])  # the start, then the chunk: both before the Cancel

    def cancel_check():
        return next(answers_before_the_gate, True) if not cancelled.is_set() else True

    status = _route_waits_then_finishes(
        gate, lambda: batch_convert.convert_single_pdf(source, tmp_path / "out", "v", "+0%", lambda _m: None,
                                                       cancel_check=cancel_check, out_mp3=target), cancelled)
    assert status[0] == "success"
    publication.verify_finished_mp3(target)


@needs_ffmpeg
def test_cancel_during_the_memory_wait_stops_a_book_with_more_to_synthesise(tmp_path, offline_engine, monkeypatch):
    """Mid-book, the next checkpoint would stop it anyway, so it does not sit out the wait first."""
    gate = _hold_the_gate(monkeypatch)
    source = tmp_path / "in" / "two.txt"
    source.parent.mkdir()
    source.write_text("# One\n\nFirst chapter.\n\n# Two\n\nSecond chapter.\n", encoding="utf-8")
    cancelled = threading.Event()
    errors = []

    def work():
        try:
            runner.run_conversion_job(str(source), output_dir=str(tmp_path / "out"), audio_format="mp3",
                                      cancel_check=cancelled.is_set)
        except ConversionCancelled as exc:
            errors.append(exc)

    with gate.reserve(1024 ** 3):
        worker = threading.Thread(target=work)
        worker.start()
        deadline = time.monotonic() + 60
        while not gate._queue:
            assert time.monotonic() < deadline, "it never reached the gate"
            time.sleep(0.005)
        cancelled.set()
        worker.join(30)
        assert not worker.is_alive(), "it stopped while the other file was still assembling"
    assert len(errors) == 1
    assert not (tmp_path / "out").exists()


@needs_ffmpeg
@pytest.mark.parametrize("route", ["direct", "folder"])
def test_the_gate_is_given_each_narrations_real_size(tmp_path, offline_engine, offline_folder, monkeypatch, route):
    """Not an estimate: what is reserved for the final assembly matches the audio that comes out."""
    asked = []
    real_reserve = worker_limits.ASSEMBLY_GATE.reserve

    def reserve(need, **kwargs):
        asked.append(need)
        return real_reserve(need, **kwargs)

    monkeypatch.setattr(worker_limits.ASSEMBLY_GATE, "reserve", reserve)
    monkeypatch.setattr(worker_limits, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    source = source_file(tmp_path / "in")
    if route == "direct":
        produced = runner.run_conversion_job(str(source), output_dir=str(tmp_path / "out"), audio_format="mp3")
    else:
        produced = tmp_path / "out" / "book-Voice.mp3"
        batch_convert.convert_single_pdf(source, tmp_path / "out", "v", "+0%", lambda _m: None, out_mp3=produced)
    from mutagen.mp3 import MP3

    seconds = MP3(produced).info.length
    assert asked, "the gate was asked"
    assert asked[-1] == pytest.approx(worker_limits.peak_bytes_for_seconds(seconds), abs=2_000_000)


# --------------------------------------------------------------------------- #
# Guards on the code itself
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module", [runner, batch_convert, panel_module])
def test_no_edge_route_moves_or_copies_a_file_onto_a_final_name_any_more(module):
    import ast

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            target = ast.unparse(node.func)
            assert target not in ("shutil.move", "os.rename", "os.replace"), f"{module.__name__}: {target}"


def test_the_standalone_engine_command_line_reaches_the_same_contract(monkeypatch):
    """``python -m ...epub2tts_edge`` calls ``run_conversion_job``; there is no second way out of the engine."""
    source = Path(engine.__file__).read_text(encoding="utf-8")
    assert "shutil" not in source and "os.replace" not in source and "os.rename" not in source
    assert "from .runner import run_conversion_job" in source
