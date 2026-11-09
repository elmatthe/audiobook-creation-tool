"""Cancel stops a running chapter-title remux in the M4B Metadata Editor (v0.7.2 Phase 6D, ACT72-033).

Before, ``shared/metadata._run_chapter_remux_step`` ran both FFmpeg steps of the remux (the ffmetadata dump and the
chapter-track rebuild) through a blocking ``subprocess.run``. Cancel was seen only at the Editor's next checkpoint,
after the remux, its validation and four ffprobe read-backs had finished. Now each step goes through Phase 6C's
``subprocess_utils.run_supervised``; the Editor's worker body (``m4b_metadata_batch.Attempt.run``) puts the attempt in
``subprocess_utils.cancellable`` with the controller's non-blocking ``cancel_check``, as the Maker's does.

Three layers, each with real processes:

* the remux itself (``apply_chapter_titles``) with real FFmpeg, inside and outside a cancel block: a Cancel during
  the rebuild, a Cancel latched between its two steps, and the ordinary rename with its integrity guarantees;
* the Editor's worker body with a real ``JobController``: each remux step of a later Book replaced in turn by a
  controlled long child (a copy of PING.EXE named ``ffmpeg.exe``) or reached by a latched Cancel; a real rebuild
  slowed with ``-re`` and cancelled, then paused; real FFmpeg failures (a non-zero exit, and exit 0 with an error
  logged) that must stay ordinary retryable failures that Retry Failed rebuilds;
* the panel itself with real threads, Cancel pressed while a real rebuild runs.

The slow real rebuild is the Editor's own command line with ``-re`` before the first ``-i``. FFmpeg 9 ignores ``-re``
while the attached cover picture is mapped (measured: 0.04 s instead of 60 s), so the slowed Books carry no cover;
the cover is proved intact on the unslowed paths. The Books carry a tone, never silence: AAC codes silence to the
same frames whatever the bitrate, so a silent Book's audio checksum cannot see a re-encode.

Every Cancel test also shows that an unrelated FFmpeg-named sentinel, a child of this very process, lives on.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from shared import book_workspace, metadata
from shared import subprocess_utils as sp
from shared.book_workspace import BookDisposition
from shared.cancellation import ConversionCancelled
from shared.importing import IdFactory, ImportedFileSnapshot, Revision
from shared.job_control import JobEventKind, JobState

from m4b.metadata import m4b_metadata_batch as batch
from m4b.metadata import m4b_metadata_editor as editor
from m4b.metadata import m4b_metadata_workflow as wf
from m4b.metadata.m4b_metadata_plan import EditorAction, EditorRunOptions
from m4b.metadata.m4b_metadata_workflow import ObservationStore

import source_probe
import test_m4b_metadata_processing as tp
from test_ffmpeg_cancel import (  # noqa: F401  (fixtures are collected by name)
    PROMPT_SECONDS,
    Spawned,
    _cancel_block,
    _in_thread,
    _media_children,
    _ping,
    _until,
    hashes,
    named_ffmpeg,
    sentinel,
    sha,
)
from test_import_coordination import RealThreads
from test_m4b_chapter_remux_timescale import LONG_CHAPTERS, assert_boundaries, audio_md5
from test_m4b_metadata_editor_ui import (  # noqa: F401  (fixtures are collected by name)
    import_folder,
    make_panel,
    output_base,
    tk_root,
    windows_theme,
)
from test_m4b_metadata_processing import container  # noqa: F401  (a fixture, collected by name)
from test_m4b_metadata_workflow import _ff, require_ffmpeg
from test_mp3_orchestration import wait_for

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process identity")

_IDS = IdFactory("rx-")

#: Slowed with -re, each runs for its whole length: one Cancel never waits for it, one Pause lets it finish.
SLOW_CHAPTERS = (("Intro", 5), ("Chapter 1", 50), ("Outro", 5))
PAUSE_CHAPTERS = (("Intro", 1), ("Chapter 1", 3), ("Outro", 1))
#: A freeform atom the stream-copy remux drops and ``apply_chapter_titles`` must put back.
ASIN_KEY = "----:com.apple.iTunes:ASIN"


# --------------------------------------------------------------------------- #
# Media
# --------------------------------------------------------------------------- #


def toned_chaptered_m4b(work: Path, target: Path, chapters) -> Path:
    """``build_chaptered_m4b``'s shape (44.1 kHz mono AAC, an attached MJPEG cover, movie timescale 1000) with a tone
    where it has silence. AAC codes digital silence to the same frames at any bitrate, so an audio checksum of a
    silent Book cannot tell a re-encode from a stream copy: a planted re-encode survived every such check here."""
    require_ffmpeg()
    total = sum(seconds for _, seconds in chapters)
    lines = [";FFMETADATA1", "title=Long Book"]
    at = 0
    for title, seconds in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={at * 1000}", f"END={(at + seconds) * 1000}",
                  f"title={title}"]
        at += seconds
    meta = work / f"{target.stem}.ffmeta"
    meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _ff("-f", "lavfi", "-i", f"sine=frequency=330:sample_rate=44100:duration={total}",
        "-t", "1", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=1",
        "-i", str(meta),
        "-map", "0:a", "-map", "1:v", "-map_metadata", "2", "-map_chapters", "2",
        "-ac", "1", "-c:a", "aac", "-b:a", "32k", "-c:v", "mjpeg", "-disposition:v", "attached_pic",
        "-movie_timescale", "1000", str(target))
    return target


def _without_cover(source: Path, target: Path) -> Path:
    _ff("-i", str(source), "-map", "0:a", "-map_metadata", "0", "-map_chapters", "0", "-c", "copy",
        "-movie_timescale", "1000", str(target))
    return target


@pytest.fixture(scope="module")
def long_book(tmp_path_factory) -> Path:
    """The 2026-09-20 shape: a cover-art video stream and a ten-minute chapter between two short ones."""
    work = tmp_path_factory.mktemp("act72-033-long")
    return toned_chaptered_m4b(work, work / "long.m4b", LONG_CHAPTERS)


@pytest.fixture(scope="module")
def slow_book(tmp_path_factory) -> Path:
    work = tmp_path_factory.mktemp("act72-033-slow")
    return _without_cover(toned_chaptered_m4b(work, work / "cover.m4b", SLOW_CHAPTERS), work / "slow.m4b")


@pytest.fixture(scope="module")
def pause_book(tmp_path_factory) -> Path:
    work = tmp_path_factory.mktemp("act72-033-pause")
    return _without_cover(toned_chaptered_m4b(work, work / "cover.m4b", PAUSE_CHAPTERS), work / "pause.m4b")


def _with_freeform(path: Path) -> Path:
    from mutagen.mp4 import MP4, MP4FreeForm

    mp4 = MP4(str(path))
    if mp4.tags is None:
        mp4.add_tags()
    mp4.tags[ASIN_KEY] = [MP4FreeForm(b"B000ACT033")]
    mp4.save()
    return path


def freeform(path: Path) -> dict:
    from mutagen.mp4 import MP4

    tags = MP4(str(path)).tags or {}
    return {key: [bytes(value) for value in values] for key, values in tags.items() if key.startswith("----:")}


def _place(source: Path, target: Path, title: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    metadata.write_m4b_tags(target, {"title": title, "series": "Saga"})
    return _with_freeform(target)


# --------------------------------------------------------------------------- #
# The remux's two FFmpeg steps, observed and steered
# --------------------------------------------------------------------------- #


def _step_of(argv: list[str]) -> str | None:
    last = str(argv[-1]) if argv else ""
    if "-map_chapters" in argv and ".retitle.tmp" in Path(last).name:
        return "rebuild"
    if "ffmetadata" in argv and Path(last).name == "in.ffmeta":
        return "dump"
    return None


def slowed(target: Path):
    """The Editor's own rebuild of *target*, reading at the native rate: a real remux that takes the Book's length."""
    def edit(step, source, argv):
        if step == "rebuild" and source == str(target):
            at = argv.index("-i")
            return argv[:at] + ["-re"] + argv[at:]
        return argv
    return edit


class Remux:
    """Every chapter-remux step, through the real supervisor; ``edit`` may change one step's command line and
    ``before`` / ``after`` run around a step on the worker thread.

    On code that predates the supervisor (the negative control) the steps arrive through the old blocking ``run``;
    that route is followed too, through ``popen``, so the same steering applies and a failing test can still stop
    what it started.
    """

    def __init__(self, monkeypatch, *, edit=None, before=None, after=None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._edit, self._before, self._after = edit, before, after
        supervised, blocking = sp.run_supervised, sp.run

        def steer(argv):
            step = _step_of(argv)
            if step is None:
                return None, argv
            source = argv[argv.index("-i") + 1]
            self.calls.append((step, source))
            if self._before is not None:
                self._before(step, source)
            return (step, source), (self._edit(step, source, argv) if self._edit else argv)

        def run_supervised(args, **kwargs):
            seen, argv = steer(list(args))
            try:
                return supervised(argv, **kwargs)
            finally:
                if seen is not None and self._after is not None:
                    self._after(*seen)

        def run(cmd, **kwargs):
            seen, argv = steer(list(cmd))
            if seen is None:
                return blocking(cmd, **kwargs)
            try:
                child = sp.popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                out, err = child.communicate()
                if kwargs.get("check") and child.returncode:
                    raise subprocess.CalledProcessError(child.returncode, argv, out, err)
                return subprocess.CompletedProcess(argv, child.returncode, out, err)
            finally:
                if self._after is not None:
                    self._after(*seen)

        monkeypatch.setattr(sp, "run_supervised", run_supervised)
        monkeypatch.setattr(sp, "run", run)

    def steps_for(self, path: Path) -> list[str]:
        return [step for step, source in self.calls if source == str(path)]


@pytest.fixture
def spawned(monkeypatch):
    """Every child started through ``popen``; whatever a failing test left running is stopped by its own handle."""
    seen = Spawned(monkeypatch)
    yield seen
    for child in seen.alive():
        child.kill()
        child.wait(10)


@pytest.fixture
def private_temp(tmp_path, monkeypatch) -> Path:
    """The remux's ``chaptitles_`` folder lands here, where a test can see that it went."""
    folder = tmp_path / "temp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


def _leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.glob("chaptitles_*"))


def _tmp_out(staged: Path) -> Path:
    return staged.with_name(staged.stem + ".retitle.tmp" + staged.suffix)


def _child_for(spawned: Spawned, step: str, target: Path):
    for argv, child, _kwargs in reversed(spawned.children):
        if _step_of(argv) == step and argv[argv.index("-i") + 1] == str(target):
            return child
    return None


# --------------------------------------------------------------------------- #
# 1. The remux itself
# --------------------------------------------------------------------------- #


def test_outside_a_cancel_block_the_remux_runs_to_its_end_through_the_supervisor(long_book, tmp_path, monkeypatch,
                                                                                private_temp):
    """The established behaviour, unchanged for any caller without a cancel block: every chapter, boundary and text
    track sample kept, only the given titles changed, the audio byte-equal, the cover and freeform atoms kept, no
    temporary left, and each step a hidden-window child with no stdin."""
    copy = _place(long_book, tmp_path / "book.m4b", "Long")
    before_audio, before_freeform = audio_md5(copy), freeform(copy)
    assert ASIN_KEY in before_freeform
    remux = Remux(monkeypatch)
    started: list[dict] = []
    real = subprocess.Popen

    class Recording(real):  # type: ignore[valid-type, misc]
        def __init__(self, *args, **kwargs):
            started.append(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", Recording)
    metadata.apply_chapter_titles(copy, ["Opening", "", "Closing"])
    assert remux.steps_for(copy) == ["dump", "rebuild"], "both steps went through the supervisor"
    assert len(started) == 2
    for kwargs in started:
        assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert kwargs["startupinfo"].wShowWindow == subprocess.SW_HIDE
        assert kwargs["stdin"] is subprocess.DEVNULL
    assert metadata.read_chapter_titles(copy) == ["Opening", "Chapter 1", "Closing"]
    seen = metadata.read_chapter_structure(copy)
    assert seen.count == 3 and seen.track_samples == 3
    assert_boundaries(seen.boundaries, ((0, 30), (30, 630), (630, 660)))
    assert audio_md5(copy) == before_audio, "-c copy: the audio stream is byte-equal"
    assert metadata.read_m4b_tags(copy)["has_cover"], "the cover survives the remux"
    assert freeform(copy) == before_freeform, "every freeform atom the remux dropped was restored"
    assert not _tmp_out(copy).exists() and _leftovers(private_temp) == []


def test_cancel_during_the_rebuild_stops_ffmpeg_and_leaves_the_copy_and_no_temporary(
        slow_book, tmp_path, monkeypatch, spawned, private_temp, sentinel):
    """``apply_chapter_titles`` itself, without the Editor's staging to clean up after it: the half-written
    ``.retitle.tmp`` sibling and the ``chaptitles_`` folder are its own to remove."""
    copy = _place(slow_book, tmp_path / "book.m4b", "Slow")
    before = sha(copy)
    remux = Remux(monkeypatch, edit=slowed(copy))
    flag = threading.Event()
    acknowledged: list[float] = []

    def body():
        with _cancel_block(flag, acknowledged):
            metadata.apply_chapter_titles(copy, ["Opening", "", "Closing"])

    thread, box = _in_thread(body)
    target = _tmp_out(copy)
    _until(lambda: _child_for(spawned, "rebuild", copy) is not None and target.is_file(), what="the slowed rebuild")
    rebuild = _child_for(spawned, "rebuild", copy)
    time.sleep(0.3)
    assert rebuild.poll() is None and target.is_file(), "the rebuild is really writing its output"
    pressed = time.monotonic()
    flag.set()
    thread.join(PROMPT_SECONDS + 5)
    elapsed = time.monotonic() - pressed
    assert not thread.is_alive(), "the rebuild ran on after Cancel"
    assert isinstance(box.get("error"), ConversionCancelled), box
    assert elapsed < PROMPT_SECONDS, f"Cancel took {elapsed:.2f} s to stop the rebuild"
    assert rebuild.returncode not in (None, 0), "the rebuild was stopped, not finished"
    assert len(acknowledged) == 1
    assert remux.steps_for(copy) == ["dump", "rebuild"]
    assert sha(copy) == before, "the copy is untouched until the rebuild has succeeded"
    assert not target.exists(), "the half-written remux output was removed"
    assert _leftovers(private_temp) == [], "the ffmetadata folder was removed"
    assert spawned.alive() == [] and _media_children() == [sentinel.pid]


def test_a_cancel_latched_after_the_dump_starts_no_rebuild(container, tmp_path, monkeypatch, spawned, private_temp):
    copy = _place(container, tmp_path / "book.m4b", "Short")
    before = sha(copy)
    flag = threading.Event()
    remux = Remux(monkeypatch, after=lambda step, _source: flag.set() if step == "dump" else None)
    with _cancel_block(flag), pytest.raises(ConversionCancelled):
        metadata.apply_chapter_titles(copy, ["Opening", "Closing"])
    assert remux.steps_for(copy) == ["dump", "rebuild"], "the rebuild was asked for"
    assert [_step_of(argv) for argv, _child, _kw in spawned.children] == ["dump"], "but never started"
    assert sha(copy) == before
    assert not _tmp_out(copy).exists() and _leftovers(private_temp) == []


# --------------------------------------------------------------------------- #
# 2. The Editor's worker body
# --------------------------------------------------------------------------- #


class Events:
    def __init__(self) -> None:
        self.seen: list = []

    def __call__(self, event) -> None:
        self.seen.append(event)

    def of(self, kind) -> list:
        return [event for event in self.seen if event.kind == kind]


def _reserver(tmp_path: Path):
    from shared import output_paths

    counter = {"n": 0}

    def make(**_kw):
        counter["n"] += 1
        directory = tmp_path / "Outputs" / "M4B-Metadata-Outputs" / f"M4B-Metadata-{counter['n']}"
        directory.mkdir(parents=True)
        return output_paths.RunReservation(tool_key="m4b_metadata", base_directory=tmp_path / "Outputs",
                                           tool_directory=directory.parent, run_directory=directory,
                                           run_number=counter["n"])
    return make


#: Line 1 renames chapter 1 of either Book; for a three-chapter Book line 3 renames its last; for the two-chapter
#: container it lies past the count and is ignored. Every Book therefore really runs the remux.
TITLES_A = "Opening A\nClosing A"
TITLES_B = "Opening B\n\nClosing B"


def two_books(tmp_path: Path, first: Path, second: Path):
    """Book A then Book B, each renaming chapters, with a Shared Genre write; the sources carry a freeform atom."""
    reserve = _reserver(tmp_path)
    titles = (TITLES_A, TITLES_B)
    library = tmp_path / "Library"
    paths = (_place(first, library / "A" / "A.m4b", "A"), _place(second, library / "B" / "B.m4b", "B"))
    entries = tuple(tp.imported(library, f"{p.parent.name}/{p.name}", p) for p in paths)
    result = wf.import_folder(wf.new_workspace(id_factory=_IDS), ImportedFileSnapshot(Revision(1), entries),
                              id_factory=_IDS, store=ObservationStore())
    space, store = result.mutation.workspace, result.store
    for book, text in zip(space.books, titles):
        space = book_workspace.select_book(space, book.book_id).workspace
        space = wf.set_book_field(space, "chapter_titles", text).workspace
    space = tp.shared_with(space, genre="Shared G")
    made = tp.plan(space, store, reserve, EditorAction.SAVE_TAGS, EditorRunOptions())
    assert [book.source for book in made.books] == list(paths)
    events = Events()
    run = batch.EditorRun(made, id_factory=_IDS, clock=time.monotonic, publish=events)
    return made, run, events, library


def _assert_cancelled_cleanly(made, result, events, library, before_sources, a_hash, private_temp, sentinel,
                              spawned):
    a, b = made.books
    assert result.state is JobState.CANCELLED
    assert [d for _id, d in result.dispositions] == [BookDisposition.SUCCEEDED, BookDisposition.NOT_ATTEMPTED]
    assert not result.can_retry_failed, "a Cancel is never offered to Retry Failed"
    assert events.of(JobEventKind.FAILURE) == [], "a Cancel is never reported as a failure"
    assert events.of(JobEventKind.CANCELLED)
    assert sha(a.published) == a_hash, "the Book published before Cancel is untouched"
    assert not b.published.exists() and not b.staging_dir.exists(), "nothing of the cancelled Book was published"
    assert not made.work_root.exists() or not any(made.work_root.iterdir())
    assert hashes(library) == before_sources, "the originals are byte-identical"
    assert _leftovers(private_temp) == []
    assert spawned.alive() == [] and _media_children() == [sentinel.pid]


def _start_until(run, what: str, ready):
    attempt = run.start()
    thread, box = _in_thread(attempt.run)
    _until(lambda: ready() or not thread.is_alive(), what=what)
    assert thread.is_alive(), f"the run ended before {what}: {box}"
    return attempt, thread, box


#: name: how the stage is reached. A stand-in replaces a running step; a latched Cancel is set just before / after one.
_STAGES = {
    "during-the-dump": ("stand-in", "dump"),
    "during-the-rebuild": ("stand-in", "rebuild"),
    "latched-before-the-dump": ("before", "dump"),
    "latched-between-the-dump-and-the-rebuild": ("after", "dump"),
}


@pytest.mark.parametrize("stage", list(_STAGES))
def test_cancel_at_each_remux_step_of_a_later_book_stops_it_and_starts_nothing_more(
        stage, container, tmp_path, monkeypatch, spawned, private_temp, named_ffmpeg, sentinel):
    how, step = _STAGES[stage]
    made, run, events, library = two_books(tmp_path, container, container)
    a, b = made.books
    before_sources = hashes(library)
    latched: list[float] = []

    def latch(at_step, source):
        if at_step == step and source == str(b.staged) and not latched:
            latched.append(time.monotonic())
            run.cancel()

    def stand_in(at_step, source, argv):
        return _ping(named_ffmpeg) if at_step == step and source == str(b.staged) else argv

    remux = Remux(monkeypatch, edit=stand_in if how == "stand-in" else None,
                  before=latch if how == "before" else None, after=latch if how == "after" else None)
    if how == "stand-in":
        attempt, thread, box = _start_until(run, f"B's {step}",
                                            lambda: spawned.running(lambda argv: argv[0] == str(named_ffmpeg)))
        stand = spawned.running(lambda argv: argv[0] == str(named_ffmpeg))
        a_hash = sha(a.published)
        pressed = time.monotonic()
        run.cancel()
        run.cancel()
        thread.join(PROMPT_SECONDS + 5)
        elapsed = time.monotonic() - pressed
        assert elapsed < PROMPT_SECONDS, f"Cancel took {elapsed:.2f} s to stop B's {step}"
        assert stand.returncode not in (None, 0), "the running step was stopped, not finished"
    else:
        attempt = run.start()
        thread, box = _in_thread(attempt.run)
        thread.join(60)
        assert latched, f"the run never reached B's {step}"
        a_hash = sha(a.published)
    assert not thread.is_alive() and "error" not in box, box
    asked, started = {
        "during-the-dump": (["dump"], []),
        "during-the-rebuild": (["dump", "rebuild"], ["dump"]),
        "latched-before-the-dump": (["dump"], []),
        "latched-between-the-dump-and-the-rebuild": (["dump", "rebuild"], ["dump"]),
    }[stage]
    assert remux.steps_for(b.staged) == asked, "no step was asked for after the one Cancel met"
    started_for_b = [_step_of(argv) for argv, _child, _kw in spawned.children
                     if "-i" in argv and argv[argv.index("-i") + 1] == str(b.staged)]
    assert started_for_b == started, f"a step started after Cancel: {started_for_b}"
    assert attempt.controller.state is JobState.CANCELLED
    _assert_cancelled_cleanly(made, box["value"], events, library, before_sources, a_hash, private_temp, sentinel,
                              spawned)


def test_cancel_during_a_real_rebuild_cancels_the_run_and_keeps_the_earlier_book(
        container, slow_book, tmp_path, monkeypatch, spawned, private_temp, sentinel):
    made, run, events, library = two_books(tmp_path, container, slow_book)
    a, b = made.books
    before_sources = hashes(library)
    Remux(monkeypatch, edit=slowed(b.staged))
    target = _tmp_out(b.staged)
    attempt, thread, box = _start_until(run, "B's slowed rebuild",
                                        lambda: _child_for(spawned, "rebuild", b.staged) is not None
                                        and target.is_file())
    rebuild = _child_for(spawned, "rebuild", b.staged)
    time.sleep(0.3)
    assert rebuild.poll() is None and target.is_file() and b.staged.is_file(), "the rebuild is really writing"
    a_hash = sha(a.published)
    pressed = time.monotonic()
    run.cancel()
    run.cancel()
    thread.join(PROMPT_SECONDS + 5)
    elapsed = time.monotonic() - pressed
    assert not thread.is_alive() and "error" not in box, box
    assert elapsed < PROMPT_SECONDS, f"the rebuild ran on for {elapsed:.2f} s after Cancel"
    assert rebuild.returncode not in (None, 0), "the rebuild was stopped, not finished"
    assert not target.exists(), "the half-written remux output is gone"
    _assert_cancelled_cleanly(made, box["value"], events, library, before_sources, a_hash, private_temp, sentinel,
                              spawned)


def test_pause_during_a_real_rebuild_lets_it_finish_and_waits_at_the_checkpoint_after_it(
        container, pause_book, tmp_path, monkeypatch, spawned, private_temp):
    made, run, events, library = two_books(tmp_path, pause_book, container)
    a, b = made.books
    before_sources = hashes(library)
    remux = Remux(monkeypatch, edit=slowed(a.staged))
    attempt, thread, box = _start_until(run, "A's slowed rebuild",
                                        lambda: _child_for(spawned, "rebuild", a.staged) is not None)
    rebuild = _child_for(spawned, "rebuild", a.staged)
    controller = attempt.controller
    run.pause()
    while rebuild.poll() is None:
        assert controller.state is JobState.PAUSE_REQUESTED, "PAUSED was claimed while FFmpeg was still rebuilding"
        time.sleep(0.02)
    assert rebuild.returncode == 0, "Pause let the rebuild finish; it was not stopped"
    _until(lambda: controller.state is JobState.PAUSED, what="the pause at the checkpoint after the step")
    time.sleep(0.3)
    assert controller.state is JobState.PAUSED
    assert a.staged.is_file() and not a.published.exists(), "A waits, validated, in staging"
    assert remux.steps_for(b.staged) == [] and not b.staging_dir.exists(), "nothing of the next Book ran while paused"
    run.resume()
    thread.join(60)
    assert not thread.is_alive() and box["value"].state is JobState.SUCCEEDED, box
    assert metadata.read_chapter_titles(a.published) == ["Opening A", "Closing A", "Outro"]
    seen = metadata.read_chapter_structure(a.published)
    assert seen.count == 3 and seen.track_samples == 3
    assert_boundaries(seen.boundaries, ((0, 1), (1, 4), (4, 5)))
    assert audio_md5(a.published) == audio_md5(a.source)
    assert freeform(a.published) == freeform(a.source)
    assert metadata.read_chapter_titles(b.published) == ["Opening B", "Closing"]
    assert events.of(JobEventKind.FAILURE) == []
    assert hashes(library) == before_sources
    assert _leftovers(private_temp) == []




def _pathological(target: Path):
    """FFmpeg 9's own timescale for a 44.1 kHz Book beside its cover: the long chapter is dropped and FFmpeg exits 0."""
    def edit(step, source, argv):
        if step == "rebuild" and source == str(target) and not edit.done:
            edit.done = True
            argv = list(argv)
            argv[argv.index("-movie_timescale") + 1] = "4410000"
        return argv
    edit.done = False
    return edit


def _missing_metadata(target: Path):
    """The rebuild told to read an ffmetadata file that is not there: a real non-zero FFmpeg exit."""
    def edit(step, source, argv):
        if step == "rebuild" and source == str(target) and not edit.done:
            edit.done = True
            argv = list(argv)
            second = [i for i, token in enumerate(argv) if token == "-i"][1]
            argv[second + 1] = str(Path(argv[second + 1]).with_name("missing.ffmeta"))
        return argv
    edit.done = False
    return edit


_FAILURES = {
    "a-non-zero-exit": (_missing_metadata, "CalledProcessError"),
    "exit-zero-with-an-error-logged": (_pathological, "ChapterRemuxError"),
}


@pytest.mark.parametrize("kind", list(_FAILURES))
def test_a_genuine_remux_failure_stays_retryable_and_retry_failed_rebuilds_it(
        kind, container, long_book, tmp_path, monkeypatch, spawned, private_temp):
    breaker, error = _FAILURES[kind]
    made, run, events, library = two_books(tmp_path, container, long_book)
    a, b = made.books
    before_sources = hashes(library)
    Remux(monkeypatch, edit=breaker(b.staged))
    first = run.start().run()
    assert first.state is JobState.COMPLETED_WITH_FAILURES
    assert [d for _id, d in first.dispositions] == [BookDisposition.SUCCEEDED, BookDisposition.FAILED]
    failures = events.of(JobEventKind.FAILURE)
    assert failures and all(e.stage == "chapters" and e.item_id == b.occurrence_id for e in failures)
    record = first.result_for(b.book_id)
    assert set(record.retryable_ids) == {b.occurrence_id}, "an ordinary, retryable failure"
    assert any(error in entry.technical_detail for entry in record.failures.records), record.failures.records
    assert not events.of(JobEventKind.CANCELLED)
    assert not b.published.exists() and not b.staging_dir.exists()
    a_hash = sha(a.published)

    retry = run.retry_failed()
    result = retry.run()
    assert result.state is JobState.SUCCEEDED
    assert sha(a.published) == a_hash, "the earlier success is untouched"
    assert metadata.read_chapter_titles(b.published) == ["Opening B", "Chapter 1", "Closing B"]
    seen = metadata.read_chapter_structure(b.published)
    assert seen.count == 3 and seen.track_samples == 3, "every chapter in the rebuilt text track"
    assert_boundaries(seen.boundaries, ((0, 30), (30, 630), (630, 660)))
    assert audio_md5(b.published) == audio_md5(b.source)
    assert metadata.read_m4b_tags(b.published)["has_cover"]
    assert freeform(b.published) == freeform(b.source)
    assert hashes(library) == before_sources
    assert _leftovers(private_temp) == []


# --------------------------------------------------------------------------- #
# 3. The panel, with real threads
# --------------------------------------------------------------------------- #


def test_the_editor_panel_cancel_stops_a_real_rebuild(make_panel, slow_book, tmp_path, monkeypatch, spawned,
                                                      private_temp, sentinel):
    panel = make_panel(thread_factory=RealThreads())
    library = tmp_path / "Library"
    _place(slow_book, library / "Slow.m4b", "Slow")
    before = hashes(library)
    import_folder(panel, library)
    # The panel starts with one blank Book; the scan, on a real thread, replaces it with the imported one.
    wait_for(panel, lambda: panel.workspace.count == 1 and wf.source_of(panel.workspace.current) is not None,
             timeout=60)
    panel.type_chapter_titles("Opening\n\nClosing")
    holder: dict = {}

    def edit(step, source, argv):
        if step == "rebuild":
            holder["staged"] = Path(source)
            at = argv.index("-i")
            return argv[:at] + ["-re"] + argv[at:]
        return argv

    Remux(monkeypatch, edit=edit)
    assert panel.save(), make_panel.dialogs
    wait_for(panel, lambda: "staged" in holder and _child_for(spawned, "rebuild", holder["staged"]) is not None,
             timeout=60)
    rebuild = _child_for(spawned, "rebuild", holder["staged"])
    time.sleep(0.3)
    pressed = time.monotonic()
    panel.cancel()
    panel.cancel()
    wait_for(panel, lambda: not panel.is_running, timeout=30)
    elapsed = time.monotonic() - pressed
    assert elapsed < PROMPT_SECONDS, f"the rebuild ran on for {elapsed:.2f} s after Cancel"
    assert rebuild.returncode not in (None, 0)
    result = panel.last_result
    assert result.state is JobState.CANCELLED
    book = panel.last_plan.books[0]
    assert result.disposition_for(book.book_id) is BookDisposition.NOT_ATTEMPTED
    # Stopped part-way by Cancel: it reads Cancelled while its result stays NOT_ATTEMPTED (v0.7.2 Phase 6, ACT72-004).
    assert panel.book_status_for(panel.workspace.books[0].book_id) == editor.STATUS_CANCELLED
    assert not result.can_retry_failed
    assert not book.published.exists() and not book.staging_dir.exists()
    assert hashes(library) == before
    for worker in panel._thread_factory.made:
        worker.join(10)
        assert not worker.is_alive()
    assert _leftovers(private_temp) == []
    assert spawned.alive() == [] and _media_children() == [sentinel.pid]


# --------------------------------------------------------------------------- #
# 4. Structure
# --------------------------------------------------------------------------- #


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def test_each_remux_step_goes_through_the_supervisor_and_nothing_else():
    tree = source_probe.module("shared/metadata.py")
    step = _function(tree, "_run_chapter_remux_step")
    via_sp = {node.func.attr for node in ast.walk(step) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute) and ast.unparse(node.func.value) == "sp"}
    assert via_sp == {"run_supervised"}, via_sp
    remux = _function(tree, "apply_chapter_titles")
    calls = [ast.unparse(node.func) for node in ast.walk(remux) if isinstance(node, ast.Call)]
    assert calls.count("_run_chapter_remux_step") == 2
    assert not any(call.startswith("sp.") or call.startswith("subprocess.") for call in calls), calls


def test_the_editor_worker_body_hands_the_remux_the_non_blocking_cancel_check():
    tree = source_probe.module("m4b/metadata/m4b_metadata_batch.py")
    attempt = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Attempt")
    body = _function(attempt, "run")
    blocks = [node for node in ast.walk(body) if isinstance(node, ast.With)
              and any(ast.unparse(item.context_expr) == "sp.cancellable(controller.cancel_check, controller.checkpoint)"
                      for item in node.items)]
    assert len(blocks) == 1, "the attempt's Books run inside one cancel block with the non-blocking predicate"
    assert any(ast.unparse(node) == "self._execute(records)" for node in ast.walk(blocks[0]))
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name) and node.value.id == "sp"}
    assert used == {"cancellable"}, f"the runner starts no process itself: {sorted(used)}"
