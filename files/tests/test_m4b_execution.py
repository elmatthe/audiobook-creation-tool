"""Executing the frozen plan, and being able to stop it — Plan 5, Phase 11.

Phase 10 decided every question a run can be asked. This phase answers only one:
does the file exist afterwards, and if not, is the reason true? So the tests
here are unusually concrete. They start real child processes and prove the PID
is gone; they encode real audio with a real ffmpeg and read the samples back to
prove the seek shape the executor runs is the one Phase 5 measured; and they
fill a pipe buffer to prove the classic deadlock cannot happen.

What is actually being protected
--------------------------------
1. **No half-written file ever carries a finished name.** Every pass writes to a
   temporary file in the destination's own folder, and the frozen destination
   appears only after the process exited cleanly, the artwork pass (if any) did
   too, and the measured duration matched the plan.
2. **A cancelled run leaves nothing behind.** Terminate, bounded grace, kill,
   and *always* reap — then the partial file goes, and only then is the
   cancellation settled.
3. **A partial book never looks whole.** If segment four of a split fails, the
   three already written for that book are taken back. Other books keep theirs.
4. **Pause never lies.** A running ffmpeg is not suspended; the request settles
   at the boundary between segments.
5. **Nothing is reinterpreted.** The executor consumes the plan; it does not
   re-probe, re-plan, rename, or read a widget.

Determinism
-----------
No test sleeps to make a race come out right. Real child processes are waited on
with bounded joins and real signals; a defect fails loudly rather than hanging.
The long-lived child is this interpreter, not media, so process-lifecycle
coverage does not depend on ffmpeg at all.

Safety
------
No repository media and no private fixtures. Every audiobook here is six seconds
of a generated tone. ffmpeg's absence **fails** rather than skips — Plan 5 adds
no optional skip.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import unittest.mock as mock
from pathlib import Path

import pytest

import tkinter as tk

from shared import ffmpeg_utils, output_paths
from shared import job_control as jc
from shared import subprocess_utils as sp

from mp3_tools import m4b_converter, m4b_execution
from mp3_tools.m4b_execution import (
    DRIFT_TOLERANCE,
    ProcessLaunchError,
    ProcessResult,
    SegmentOutcome,
    SegmentWork,
    convert_segment,
    drift_of,
    needs_artwork_pass,
    remove_outputs,
    run_argv,
    tail_of,
)
from mp3_tools.m4b_metadata import AttachedPicture, MetadataMode, SourceTags
from mp3_tools.m4b_plan import ConversionMode

from test_import_coordination import RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_commands import (  # noqa: E402
    _SR,
    _decode,
    _marker_offsets,
    _write_fixture,
)
from test_m4b_conversion_plan import (  # noqa: E402
    StubThread,
    _reservation,
    book,
    chapters,
    direct,
    install_conversion_stubs,
    report,
)
from test_m4b_metadata import require_ffmpeg  # noqa: E402
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UNIVERSAL = REPO_ROOT / "scripts" / "Universal" / "mp3_tools"
PANEL_SOURCE = UNIVERSAL / "m4b_converter.py"
EXECUTION_SOURCE = UNIVERSAL / "m4b_execution.py"

#: Every wait here is bounded, so a defect fails rather than hangs.
WAIT = 10.0

#: The genuine thread class, captured before any test replaces the panel's.
RealThread = threading.Thread


# --------------------------------------------------------------------------- #
# Process doubles — enough of Popen to drive the ladder without media
# --------------------------------------------------------------------------- #


class FakeProc:
    """A child that finishes after *polls* polls, or never on its own."""

    def __init__(self, *, returncode=0, polls=1, obeys_terminate=True,
                 dies_on_kill=True, writes=b""):
        self._returncode = returncode
        self._left = polls
        self.obeys_terminate = obeys_terminate
        self.dies_on_kill = dies_on_kill
        self.writes = writes
        self.terminated = 0
        self.killed = 0
        self.waited = 0
        self.returncode = None

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        if self._left <= 0:
            self.returncode = self._returncode
            return self.returncode
        self._left -= 1
        return None

    def terminate(self):
        self.terminated += 1
        if self.obeys_terminate:
            self._left = 0

    def kill(self):
        self.killed += 1
        if self.dies_on_kill:
            self._left = 0
            self.returncode = -9

    def wait(self, timeout=None):
        self.waited += 1
        if self.returncode is None:
            if self._left <= 0 or self.dies_on_kill:
                self.returncode = self._returncode if self._left <= 0 else -9
            else:
                raise subprocess.TimeoutExpired("child", timeout or 0)
        return self.returncode


def spawner(proc, *, record=None, fail=None):
    """A ``popen`` seam that hands back *proc* and writes its diagnostics."""

    def spawn(argv, *, stdout=None, stderr=None, **kwargs):
        if fail is not None:
            raise fail
        if record is not None:
            record.append([str(part) for part in argv])
        if stdout is not None and getattr(proc, "writes", b""):
            stdout.write(proc.writes)
            stdout.flush()
        return proc

    return spawn


def never() -> bool:
    return False


def always() -> bool:
    return True


@pytest.fixture()
def workspace(tmp_path) -> Path:
    folder = tmp_path / "run"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# --------------------------------------------------------------------------- #
# The poll loop, the ladder, and the reaping
# --------------------------------------------------------------------------- #


def test_a_clean_child_is_polled_to_completion_and_reaped(workspace):
    proc = FakeProc(returncode=0, polls=3)
    result = run_argv(["ffmpeg"], cancelled=never, workspace=workspace,
                      popen=spawner(proc), wait=lambda _s: None)
    assert result.ok and result.returncode == 0
    assert result.cancelled is False
    assert proc.waited == 1, "always waited on, exactly once"
    assert proc.terminated == 0 and proc.killed == 0


def test_a_failing_child_reports_its_code_and_is_still_reaped(workspace):
    proc = FakeProc(returncode=1, polls=1)
    result = run_argv(["ffmpeg"], cancelled=never, workspace=workspace,
                      popen=spawner(proc), wait=lambda _s: None)
    assert result.returncode == 1 and not result.ok
    assert proc.waited == 1


def test_a_cancellation_terminates_the_child(workspace):
    proc = FakeProc(polls=99)
    result = run_argv(["ffmpeg"], cancelled=always, workspace=workspace,
                      popen=spawner(proc), wait=lambda _s: None)
    assert result.cancelled is True
    assert proc.terminated == 1
    assert proc.killed == 0, "it went when asked"
    assert proc.waited == 1


def test_a_stubborn_child_is_killed_after_the_grace_period(workspace):
    """The rung of the ladder a real terminate can never exercise on Windows."""
    proc = FakeProc(polls=99, obeys_terminate=False)
    ticks = iter([0.0, 0.0, 1.0, 2.0, 99.0])
    result = run_argv(["ffmpeg"], cancelled=always, workspace=workspace,
                      popen=spawner(proc), wait=lambda _s: None,
                      monotonic=lambda: next(ticks), grace_seconds=5.0)
    assert proc.terminated == 1
    assert proc.killed == 1, "it did not go, so it was killed"
    assert result.killed is True
    assert result.cancelled is True
    assert proc.waited == 1, "and it was still reaped"


def test_a_child_that_will_not_die_is_reported_not_ignored(workspace):
    proc = FakeProc(polls=99, obeys_terminate=False, dies_on_kill=False)
    ticks = iter([0.0, 99.0] + [99.0] * 20)
    result = run_argv(["ffmpeg"], cancelled=always, workspace=workspace,
                      popen=spawner(proc), wait=lambda _s: None,
                      monotonic=lambda: next(ticks))
    assert result.unreaped is True, "an uncollectable child is never silent"


def test_a_launch_failure_is_typed(workspace):
    with pytest.raises(ProcessLaunchError):
        run_argv(["nope"], cancelled=never, workspace=workspace,
                 popen=spawner(None, fail=OSError("no such file")))


def test_the_diagnostic_file_is_removed_afterwards(workspace):
    proc = FakeProc(writes=b"ffmpeg said something\n")
    result = run_argv(["ffmpeg"], cancelled=never, workspace=workspace,
                      popen=spawner(proc), wait=lambda _s: None)
    assert "ffmpeg said something" in result.detail
    leftovers = [p for p in workspace.iterdir()
                 if p.name.startswith(output_paths.TEMP_SIBLING_PREFIX)]
    assert leftovers == [], "the diagnostic temp file is not left behind"


def test_the_diagnostic_detail_is_bounded(workspace):
    proc = FakeProc(writes=b"x" * 200_000)
    result = run_argv(["ffmpeg"], cancelled=never, workspace=workspace,
                      popen=spawner(proc), wait=lambda _s: None)
    assert len(result.detail) <= m4b_execution.DETAIL_TAIL
    assert len(result.detail) > 0


def test_the_child_is_never_given_a_pipe(workspace):
    """The undrained-PIPE deadlock is unconstructible, not merely avoided."""
    seen: dict = {}

    def spawn(argv, *, stdout=None, stderr=None, **kwargs):
        seen["stdout"] = stdout
        seen["stderr"] = stderr
        return FakeProc()

    run_argv(["ffmpeg"], cancelled=never, workspace=workspace, popen=spawn,
             wait=lambda _s: None)
    assert seen["stdout"] is not subprocess.PIPE
    assert hasattr(seen["stdout"], "write"), "a real file object, not a pipe"
    assert seen["stderr"] is subprocess.STDOUT


def test_tail_of_a_missing_file_is_empty(tmp_path):
    assert tail_of(tmp_path / "nothing.log") == ""


# --------------------------------------------------------------------------- #
# Real child processes — §26, with no media involved at all
# --------------------------------------------------------------------------- #


def alive(pid: int) -> bool:
    """Whether *pid* is still a running process on this platform."""
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - not ours, but it exists
        return True
    return True


SLEEPER = [sys.executable, "-c", "import time; time.sleep(600)"]


def test_a_real_child_is_started_terminated_and_reaped(workspace):
    """The whole ladder against a genuine process. No mock anywhere in it."""
    started = threading.Event()
    stop = threading.Event()
    captured: dict = {}

    def watching_popen(argv, **kwargs):
        proc = sp.popen(argv, **kwargs)
        captured["pid"] = proc.pid
        started.set()
        return proc

    result: dict = {}

    def body():
        result["value"] = run_argv(
            SLEEPER, cancelled=stop.is_set, workspace=workspace,
            popen=watching_popen, poll_seconds=0.01)

    worker = RealThread(target=body, name="real-child")
    worker.start()
    assert started.wait(WAIT), "the child never started"
    pid = captured["pid"]
    assert alive(pid), "the child is not running, so nothing is being proved"

    stop.set()
    worker.join(WAIT)
    assert not worker.is_alive(), "run_argv never returned"

    outcome = result["value"]
    assert outcome.cancelled is True
    assert outcome.unreaped is False, "the child was collected"
    assert not alive(pid), "the child is still running"


def test_a_real_child_leaves_no_diagnostic_file(workspace):
    stop = threading.Event()
    stop.set()
    run_argv(SLEEPER, cancelled=stop.is_set, workspace=workspace, poll_seconds=0.01)
    leftovers = [p for p in workspace.iterdir()
                 if p.name.startswith(output_paths.TEMP_SIBLING_PREFIX)]
    assert leftovers == []


def test_a_talkative_child_does_not_deadlock_the_poll_loop(workspace):
    """§29: far more output than any OS pipe buffer holds, and it still finishes.

    Windows pipes are 64 KiB by default and POSIX is typically 64 KiB too. This
    writes four megabytes. A ``stdout=PIPE`` that nobody drains blocks the child
    forever at the first full buffer, and a poll loop that is waiting on the
    child would then never return — which is exactly the bug §18.2 exists to
    forbid.
    """
    chatty = [sys.executable, "-c",
              "import sys\n"
              "block = 'y' * 4096 + '\\n'\n"
              "for _ in range(1024):\n"
              "    sys.stderr.write(block)\n"
              "sys.stderr.flush()\n"]
    finished: dict = {}

    def body():
        finished["value"] = run_argv(chatty, cancelled=never, workspace=workspace,
                                     poll_seconds=0.01)

    worker = RealThread(target=body, name="chatty-child")
    worker.start()
    worker.join(WAIT)
    assert not worker.is_alive(), "the poll loop deadlocked on an undrained pipe"
    outcome = finished["value"]
    assert outcome.returncode == 0
    assert len(outcome.detail) <= m4b_execution.DETAIL_TAIL
    assert "y" in outcome.detail, "the tail really came from the child"


def test_a_real_launch_failure_is_typed(workspace):
    with pytest.raises(ProcessLaunchError):
        run_argv([str(workspace / "there-is-no-such-binary")], cancelled=never,
                 workspace=workspace, poll_seconds=0.01)


# --------------------------------------------------------------------------- #
# One segment: temporary files, finalisation, and refusing to overwrite
# --------------------------------------------------------------------------- #


def whole_work(tmp_path, **kwargs) -> SegmentWork:
    defaults = dict(
        source=tmp_path / "src" / "Book.m4b",
        destination=tmp_path / "run" / "Book.mp3",
        expected_duration=600.0,
        quality=2,
        metadata_mode=MetadataMode.PRESERVE,
        tags={"album": "A"},
    )
    defaults.update(kwargs)
    return SegmentWork(**defaults)


def stub_convert(work, *, outcome=ProcessResult(0), measure=lambda p: None,
                 record=None, sources=()):
    """Run ``convert_segment`` with the process replaced and nothing else."""
    def fake_run(argv, *, cancelled, workspace, **kwargs):
        if record is not None:
            record.append([str(part) for part in argv])
        if cancelled():
            return ProcessResult(None, cancelled=True)
        return outcome

    with mock.patch.object(m4b_execution, "run_argv", fake_run):
        return convert_segment(work, ffmpeg="ffmpeg", cancelled=never,
                               measure=measure, sources=sources)


def test_a_successful_segment_appears_only_at_its_frozen_destination(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    work = whole_work(tmp_path)
    outcome = stub_convert(work)
    assert outcome.finalised is True
    assert work.destination.exists()
    assert [p.name for p in work.destination.parent.iterdir()] == ["Book.mp3"]


def test_the_mirrored_folder_is_created_at_execution_time(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    destination = tmp_path / "run" / "Series" / "Deep" / "Book.mp3"
    outcome = stub_convert(whole_work(tmp_path, destination=destination))
    assert outcome.finalised and destination.exists()


def test_a_failed_process_leaves_no_file_at_all(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    work = whole_work(tmp_path)
    outcome = stub_convert(work, outcome=ProcessResult(1, detail="ffmpeg exploded"))
    assert outcome.failed and not outcome.finalised
    assert not work.destination.exists()
    assert list(work.destination.parent.iterdir()) == [], "no temporary survives"
    assert "ffmpeg exploded" in outcome.detail


def test_a_cancelled_process_leaves_no_file_at_all(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    work = whole_work(tmp_path)

    def fake_run(argv, *, cancelled, workspace, **kwargs):
        return ProcessResult(None, cancelled=True)

    with mock.patch.object(m4b_execution, "run_argv", fake_run):
        outcome = convert_segment(work, ffmpeg="ffmpeg", cancelled=always,
                                  measure=lambda p: None)
    assert outcome.cancelled is True
    assert not work.destination.exists()
    assert list(work.destination.parent.iterdir()) == []


def test_an_occupied_destination_is_refused_rather_than_overwritten(tmp_path):
    """The frozen plan stays authoritative: no renumbering during execution."""
    book(tmp_path / "src", "Book.m4b")
    work = whole_work(tmp_path)
    work.destination.parent.mkdir(parents=True, exist_ok=True)
    work.destination.write_text("something else got here first", encoding="utf-8")

    outcome = stub_convert(work)
    assert outcome.failed
    assert "already exists" in outcome.message
    assert work.destination.read_text(encoding="utf-8") == (
        "something else got here first")
    assert [p.name for p in work.destination.parent.iterdir()] == ["Book.mp3"], (
        "and the temporary candidate was cleaned up")


def test_a_destination_that_is_a_source_is_refused_before_anything_runs(tmp_path):
    source = book(tmp_path / "run", "Book.mp3")
    work = whole_work(tmp_path, source=source, destination=source)
    record: list = []
    outcome = stub_convert(work, record=record, sources=(source,))
    assert outcome.failed
    assert record == [], "no process was started"


def test_drift_beyond_the_threshold_discards_the_candidate(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    work = whole_work(tmp_path, expected_duration=600.0)
    outcome = stub_convert(work, measure=lambda p: 300.0)
    assert outcome.failed
    assert "xHE-AAC" in outcome.message, "the existing diagnostic is preserved"
    assert not work.destination.exists()
    assert list(work.destination.parent.iterdir()) == []


def test_drift_inside_the_threshold_is_finalised(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    work = whole_work(tmp_path, expected_duration=600.0)
    outcome = stub_convert(work, measure=lambda p: 600.0 * (1 + DRIFT_TOLERANCE / 2))
    assert outcome.finalised and work.destination.exists()


def test_a_span_too_short_to_judge_is_not_judged(tmp_path):
    assert drift_of(0.5, 0.4) is None
    assert drift_of(None, 600.0) is None
    assert drift_of(600.0, 600.0) == 0.0


def test_a_split_segment_is_measured_against_its_own_span_not_the_book(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    work = SegmentWork(
        source=tmp_path / "src" / "Book.m4b",
        destination=tmp_path / "run" / "01 - One.mp3",
        expected_duration=200.0,
        quality=2,
        metadata_mode=MetadataMode.PRESERVE,
        tags={"title": "One", "track": 1},
        span=(0.0, 200.0),
    )
    # 600 s would be the *book's* length; against a 200 s span it is a breach.
    outcome = stub_convert(work, measure=lambda p: 600.0)
    assert outcome.failed and "segment length" in outcome.message


# --------------------------------------------------------------------------- #
# Which commands each shape runs
# --------------------------------------------------------------------------- #


def test_a_whole_book_runs_one_pass_with_the_unseeked_builder(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    record: list = []
    stub_convert(whole_work(tmp_path), record=record)
    assert len(record) == 1
    argv = record[0]
    assert "-ss" not in argv and "-t" not in argv
    assert "libmp3lame" in argv and argv[argv.index("-q:a") + 1] == "2"
    assert argv[argv.index("-threads") + 1] == "0"


def test_a_fragment_runs_the_measured_output_side_seek(tmp_path):
    """§15: ``-ss`` **after** ``-i``, with an explicit ``-t`` duration."""
    book(tmp_path / "src", "Book.m4b")
    work = SegmentWork(
        source=tmp_path / "src" / "Book.m4b",
        destination=tmp_path / "run" / "02 - Two.mp3",
        expected_duration=150.0, quality=2,
        metadata_mode=MetadataMode.PRESERVE, tags={"title": "Two", "track": 2},
        span=(200.0, 350.0))
    record: list = []
    stub_convert(work, record=record)
    argv = record[0]
    assert argv.index("-ss") > argv.index("-i"), "input-side seek corrupts audio"
    assert argv[argv.index("-ss") + 1] == "200.000000"
    assert argv[argv.index("-t") + 1] == "150.000000"
    assert "-to" not in argv


def test_a_fragment_with_a_cover_runs_two_passes(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    work = SegmentWork(
        source=tmp_path / "src" / "Book.m4b",
        destination=tmp_path / "run" / "01 - One.mp3",
        expected_duration=200.0, quality=2,
        metadata_mode=MetadataMode.PRESERVE, tags={"title": "One", "track": 1},
        picture=AttachedPicture(2, "mjpeg"), span=(0.0, 200.0))
    assert needs_artwork_pass(work) is True
    record: list = []
    outcome = stub_convert(work, record=record)
    assert len(record) == 2, "audio, then cover"
    audio, attach = record
    assert "-ss" in audio and "-c:a" in audio
    assert "-ss" not in attach, "the second pass never seeks"
    assert attach[attach.index("-c") + 1] == "copy", "and never re-encodes"
    assert attach[attach.index("-map_chapters") + 1] == "-1"
    assert outcome.finalised


def test_a_fragment_without_a_cover_runs_one_pass(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    work = SegmentWork(
        source=tmp_path / "src" / "Book.m4b",
        destination=tmp_path / "run" / "01 - One.mp3",
        expected_duration=200.0, quality=2,
        metadata_mode=MetadataMode.PRESERVE, tags={"title": "One"},
        span=(0.0, 200.0))
    assert needs_artwork_pass(work) is False
    record: list = []
    stub_convert(work, record=record)
    assert len(record) == 1


def test_a_stripped_fragment_runs_one_pass_even_with_a_cover(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    work = SegmentWork(
        source=tmp_path / "src" / "Book.m4b",
        destination=tmp_path / "run" / "01 - One.mp3",
        expected_duration=200.0, quality=2,
        metadata_mode=MetadataMode.STRIP, tags={},
        picture=AttachedPicture(2, "mjpeg"), span=(0.0, 200.0))
    assert needs_artwork_pass(work) is False
    record: list = []
    stub_convert(work, record=record)
    assert len(record) == 1
    assert "-vn" in record[0]


def test_a_whole_book_with_a_cover_still_runs_one_pass(tmp_path):
    """No seek, so there is nothing to discard the cover frame."""
    book(tmp_path / "src", "Book.m4b")
    work = whole_work(tmp_path, picture=AttachedPicture(2, "mjpeg"))
    record: list = []
    stub_convert(work, record=record)
    assert len(record) == 1
    assert "0:2" in record[0]


def test_the_id3_version_this_tool_has_always_written_survives(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    record: list = []
    stub_convert(whole_work(tmp_path), record=record)
    assert record[0][record[0].index("-id3v2_version") + 1] == "3"


def test_strip_writes_no_id3_version_because_it_writes_no_tags(tmp_path):
    book(tmp_path / "src", "Book.m4b")
    record: list = []
    stub_convert(whole_work(tmp_path, metadata_mode=MetadataMode.STRIP, tags={}),
                 record=record)
    assert "-id3v2_version" not in record[0]


# --------------------------------------------------------------------------- #
# Taking back a partial book
# --------------------------------------------------------------------------- #


def test_remove_outputs_takes_back_only_what_is_inside_the_run(tmp_path):
    run = tmp_path / "run"
    inside = book(run, "01 - One.mp3")
    nested = book(run / "Series", "02 - Two.mp3")
    outside = book(tmp_path / "elsewhere", "Precious.mp3")

    removed = remove_outputs([inside, nested, outside], inside=run)
    assert set(removed) == {inside, nested}
    assert not inside.exists() and not nested.exists()
    assert outside.exists(), "a path outside the run is refused, not deleted"


def test_remove_outputs_tolerates_a_file_that_is_already_gone(tmp_path):
    run = tmp_path / "run"
    run.mkdir(parents=True)
    assert remove_outputs([run / "never-existed.mp3"], inside=run) == (
        run / "never-existed.mp3",)


# --------------------------------------------------------------------------- #
# Through the panel: split, failure isolation, cancellation
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


class _Silent:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture()
def make_panel(tk_root):
    made: list = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        kwargs.setdefault("bridge", jc.LoggerBridge(logger=_Silent()))
        panel = m4b_converter.M4BConverterUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


@pytest.fixture()
def run_env(monkeypatch):
    return install_conversion_stubs(monkeypatch, {})


class _ThreadShim:
    """``threading`` with only ``Thread`` replaced; everything else is real."""

    Thread = StubThread

    def __getattr__(self, name):
        return getattr(threading, name)


def add(panel, *paths: Path):
    panel.importer._choose_files = lambda: tuple(str(p) for p in paths)
    return panel.importer.add_files()


def start(panel):
    panel.start_convert()
    assert StubThread.started, "the worker was never handed a run"
    return StubThread.started[-1].args[0]


def convert(panel, tmp_path):
    params = start(panel)
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()
    return panel.run_plan


def split_panel(make_panel, tmp_path, run_env, *names, starts=(0.0, 200.0, 400.0)):
    panel = make_panel()
    add(panel, *[book(tmp_path / "src", name) for name in names])
    panel.var_mode.set(ConversionMode.SPLIT.value)
    run_env["default_report"] = report(duration=600.0,
                                       chapter_list=chapters(*starts))
    return panel


def test_a_split_book_produces_every_planned_segment(make_panel, tmp_path, run_env):
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b")
    plan = convert(panel, tmp_path)
    produced = sorted(p.name for p in plan.run_directory.iterdir())
    assert produced == [segment.destination.name
                        for segment in plan.items[0].segments]
    assert len(produced) == 3


def test_a_failed_segment_takes_back_the_whole_book(make_panel, tmp_path, run_env):
    """§21: a partially split book must never masquerade as complete."""
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b")

    def outcome(joined):
        line = " ".join(joined)
        return (ProcessResult(1, detail="ffmpeg exploded")
                if "02 - Chapter 2" in line else None)

    run_env["outcome"] = outcome
    plan = convert(panel, tmp_path)

    assert list(plan.run_directory.iterdir()) == [], (
        "chapter one was written first and had to be taken back")
    assert panel.run_result.failed_count == 1
    assert panel.run_result.succeeded_count == 0


def test_one_books_failure_does_not_touch_another_books_outputs(
        make_panel, tmp_path, run_env):
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b")

    def outcome(joined):
        line = " ".join(joined)
        return (ProcessResult(1, detail="no")
                if ("A.m4b" in line and "02 - Chapter 2" in line) else None)

    run_env["outcome"] = outcome
    plan = convert(panel, tmp_path)

    survived = sorted(p.name for p in plan.run_directory.iterdir())
    assert len(survived) == 3, survived
    assert panel.run_result.succeeded_count == 1
    assert panel.run_result.failed_count == 1


def test_a_cancellation_mid_book_takes_back_that_books_segments(
        make_panel, tmp_path, run_env):
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b")

    def outcome(joined):
        if "02 - Chapter 2" in " ".join(joined):
            panel.cancel()
            return ProcessResult(None, cancelled=True)
        return None

    run_env["outcome"] = outcome
    plan = convert(panel, tmp_path)

    assert list(plan.run_directory.iterdir()) == []
    assert panel.job_controller.state is jc.JobState.CANCELLED
    assert panel.run_result.failed_count == 0, "a cancellation is not a failure"


def test_a_cancellation_keeps_books_that_already_finished(
        make_panel, tmp_path, run_env):
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b")

    def outcome(joined):
        if "B.m4b" in " ".join(joined):
            panel.cancel()
            return ProcessResult(None, cancelled=True)
        return None

    run_env["outcome"] = outcome
    plan = convert(panel, tmp_path)

    survived = sorted(p.name for p in plan.run_directory.iterdir())
    assert len(survived) == 3, "the completed book keeps its outputs"
    assert panel.job_controller.state is jc.JobState.CANCELLED


def test_a_cancelled_run_settles_only_after_cleanup(make_panel, tmp_path, run_env):
    """``CANCELLED`` means it stopped and the mess is gone, not that a button moved."""
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b")
    seen: list = []

    def outcome(joined):
        if "02 - Chapter 2" in " ".join(joined):
            panel.cancel()
            seen.append(panel.job_controller.state)
            return ProcessResult(None, cancelled=True)
        return None

    run_env["outcome"] = outcome
    convert(panel, tmp_path)
    assert seen == [jc.JobState.CANCEL_REQUESTED], "requested, not yet settled"
    assert panel.job_controller.state is jc.JobState.CANCELLED


def test_a_launch_failure_fails_only_its_own_item(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))

    real_run = m4b_execution.run_argv

    def maybe_launch(argv, **kwargs):
        if "A.m4b" in " ".join(str(p) for p in argv):
            raise ProcessLaunchError("OSError: ffmpeg is not on this machine")
        return real_run(argv, **kwargs)

    with mock.patch.object(m4b_execution, "run_argv", maybe_launch):
        plan = convert(panel, tmp_path)

    assert [p.name for p in plan.run_directory.iterdir()] == ["B.mp3"]
    assert panel.run_result.failed_count == 1
    assert panel.run_result.succeeded_count == 1
    detail = "\n".join(panel.jobs.views.details)
    assert "not on this machine" in detail


def test_progress_counts_segments_not_books(make_panel, tmp_path, run_env):
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b")
    convert(panel, tmp_path)
    counted = [(e.completed, e.total) for e in panel.jobs.stream.events
               if e.kind is jc.JobEventKind.PROGRESS and e.total is not None]
    assert counted == [(0, 6), (1, 6), (2, 6), (3, 6), (4, 6), (5, 6), (6, 6)]


def test_a_run_that_lost_a_book_does_not_claim_completion(
        make_panel, tmp_path, run_env):
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b")
    run_env["outcome"] = lambda joined: (
        ProcessResult(1) if "02 - Chapter 2" in " ".join(joined) else None)
    convert(panel, tmp_path)
    view = panel.jobs.summary_view.progress
    assert view.completed == 2 and view.total == 3
    assert view.fraction is not None and view.fraction < 1.0


def test_the_eta_samples_only_finalised_segments(make_panel, tmp_path, run_env):
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b")
    run_env["outcome"] = lambda joined: (
        ProcessResult(1) if "03 - Chapter 3" in " ".join(joined) else None)
    convert(panel, tmp_path)
    assert panel.job_estimator.sample_count == 2, "a discarded segment is not history"


# --------------------------------------------------------------------------- #
# The Whole / Split control
# --------------------------------------------------------------------------- #


def test_whole_book_is_the_default(make_panel):
    panel = make_panel()
    assert panel.var_mode.get() == ConversionMode.WHOLE.value
    assert panel.read_options().mode is ConversionMode.WHOLE


def test_split_is_selectable_and_frozen_at_start(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    panel.var_mode.set(ConversionMode.SPLIT.value)
    params = start(panel)
    assert params["options"].mode is ConversionMode.SPLIT

    panel.var_mode.set(ConversionMode.WHOLE.value)
    assert params["options"].mode is ConversionMode.SPLIT, "the run keeps its own copy"


def test_the_mode_locks_while_a_run_is_going(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    start(panel)
    panel._pump.tick()
    assert str(panel.rb_whole.cget("state")) == "disabled"
    assert str(panel.rb_split.cget("state")) == "disabled"


def test_the_mode_is_restored_after_the_run(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    convert(panel, tmp_path)
    assert str(panel.rb_whole.cget("state")) == "normal"
    assert str(panel.rb_split.cget("state")) == "normal"


def test_there_is_no_per_item_mode_anywhere():
    """One batch-wide choice (44A): a per-book mode would be two runs in one."""
    from mp3_tools.m4b_plan import ItemPlan, SegmentPlan
    for holder in (ItemPlan, SegmentPlan):
        assert "mode" not in holder.__dataclass_fields__, holder.__name__
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert source.count("var_mode") >= 1
    assert "item_mode" not in source and "per_item" not in source


def test_the_mode_reaches_both_the_plan_and_the_executor(
        make_panel, tmp_path, run_env):
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b")
    plan = convert(panel, tmp_path)
    assert plan.mode is ConversionMode.SPLIT
    assert plan.items[0].fragment is True
    assert len(run_env["commands"]) == 3
    for argv in run_env["commands"]:
        assert "-ss" in argv, "every fragment ran the seeked shape"


def test_every_required_control_is_reachable_at_the_minimum_window(tk_root):
    """Actual mapped geometry at 920x600 with the mode control in place."""
    from shared import ui_theme
    assert ui_theme.MIN_SIZE == (920, 600)

    host = tk.Toplevel(tk_root)
    try:
        host.geometry("920x600")
        panel = m4b_converter.M4BConverterUI(
            host, effective_config=make_config(), clock=lambda: 0.0, home=None,
            thread_factory=RecordingThreads(),
            choose_files=lambda: (), choose_folder=lambda: ())
        panel.pack(fill="both", expand=True)
        host.update_idletasks()
        host.update()

        required = {
            "Whole book": panel.rb_whole,
            "Split by chapter": panel.rb_split,
            "MP3 Quality": panel.entry_quality,
            "Metadata: Preserve": panel.rb_preserve,
            "Metadata: Replace": panel.rb_replace,
            "Metadata: Write none": panel.rb_strip,
            "Convert": panel.btn_convert,
            "Pause": panel.jobs.controls.buttons[jc.JobAction.PAUSE],
            "Cancel": panel.jobs.controls.buttons[jc.JobAction.CANCEL],
            "Progress bar": panel.jobs.status.indicator.bar,
        }
        unreachable = {}
        for label, widget in required.items():
            mapped = bool(widget.winfo_ismapped())
            width, height = widget.winfo_width(), widget.winfo_height()
            bottom = widget.winfo_rooty() - host.winfo_rooty() + height
            if not mapped or width <= 1 or height < 16 or bottom > 600:
                unreachable[label] = (mapped, width, height, bottom)
        assert not unreachable, unreachable

        panel.close()
        panel.destroy()
    finally:
        host.destroy()


# --------------------------------------------------------------------------- #
# Closing the panel while a child is running — §32
# --------------------------------------------------------------------------- #


def test_closing_the_panel_stops_and_reaps_a_running_child(
        make_panel, tmp_path, run_env):
    """The teardown contract, against a real process this time."""
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    params = start(panel)

    started = threading.Event()
    captured: dict = {}
    real_popen = sp.popen

    def watching_popen(argv, **kwargs):
        proc = real_popen(SLEEPER, **kwargs)
        captured["pid"] = proc.pid
        started.set()
        return proc

    def real_run(argv, **kwargs):
        kwargs["popen"] = watching_popen
        kwargs.setdefault("poll_seconds", 0.01)
        return m4b_execution.run_argv.__wrapped__(argv, **kwargs) if False else None

    # Use the production loop, but hand it a long-lived child instead of ffmpeg.
    with mock.patch.object(m4b_execution, "run_argv",
                           lambda argv, **kw: run_argv(
                               SLEEPER, popen=watching_popen, poll_seconds=0.01,
                               **{k: v for k, v in kw.items()
                                  if k in ("cancelled", "workspace")})), \
            mock.patch.object(output_paths, "reserve_run_directory",
                              side_effect=_reservation(tmp_path)):
        worker = RealThread(target=panel.convert_worker, args=(params,),
                            name="m4b-close")
        worker.start()
        assert started.wait(WAIT), "the child never started"
        pid = captured["pid"]
        assert alive(pid)

        panel.close()
        worker.join(WAIT)

    assert not worker.is_alive(), "the worker did not unwind on close"
    assert not alive(pid), "the child outlived the panel"
    assert panel._pump.closed is True
    assert panel._pump.scheduled_count == 0
    run_directory = tmp_path / "run-1"
    if run_directory.exists():
        assert list(run_directory.iterdir()) == [], "no partial file survived"


# --------------------------------------------------------------------------- #
# Generated media — the executor against a real ffmpeg
# --------------------------------------------------------------------------- #

_META = (
    ";FFMETADATA1\ntitle=Generated Book\nartist=Gen Artist\nalbum=Gen Album\n"
    "album_artist=Gen Album Artist\ntrack=3/9\ncomment=NEVER\n"
    "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle=Ch One\n"
    "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=2000\nEND=4000\ntitle=Ch Two\n"
    "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=4000\nEND=6000\ntitle=Ch Three\n"
)

#: Deliberately not starting at zero: the pre-roll case (§27.3).
_PREROLL_META = (
    ";FFMETADATA1\ntitle=Late Start\nalbum=Gen Album\n"
    "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=1500\nEND=4000\ntitle=After The Wait\n"
    "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=4000\nEND=6000\ntitle=The Rest\n"
)


def _ff(*args):
    out = subprocess.run(
        [ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-y", *args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert out.returncode == 0, out.stdout.decode("utf-8", "replace")[-800:]


def _probe(path, *args) -> dict:
    out = subprocess.run(
        [ffmpeg_utils.ffprobe_cmd(), "-v", "error", *args, "-of", "json", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    return json.loads(out.decode("utf-8", "replace"))


def _duration(path) -> float:
    return float(_probe(path, "-show_format")["format"]["duration"])


def _covers(path) -> list:
    from mutagen.id3 import ID3
    try:
        return ID3(str(path)).getall("APIC")
    except Exception:
        return []


def _chapter_count(path) -> int:
    return len(_probe(path, "-show_chapters")["chapters"])


def _tags(path) -> dict:
    return _probe(path, "-show_format")["format"].get("tags", {})


@pytest.fixture(scope="module")
def media(tmp_path_factory) -> dict:
    """Real six-second M4Bs: chaptered with a cover, without, and a late start.

    The audio is the Phase 5 marker fixture — one identifiable burst per source
    second — so a produced segment can be decoded and asked which seconds of the
    source it actually contains.
    """
    require_ffmpeg()
    w = tmp_path_factory.mktemp("m4b_exec_media")
    (w / "meta.txt").write_text(_META, encoding="utf-8")
    (w / "preroll.txt").write_text(_PREROLL_META, encoding="utf-8")

    wav = w / "signal.wav"
    _write_fixture(wav, 6)
    _ff("-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(w / "a.m4a"))
    _ff("-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1",
        str(w / "c.jpg"))

    out: dict = {"dir": w, "wav": wav}
    out["cover"] = w / "WithCover.m4b"
    _ff("-i", str(w / "a.m4a"), "-i", str(w / "c.jpg"), "-i", str(w / "meta.txt"),
        "-map", "0:a", "-map", "1:v", "-map_metadata", "2", "-map_chapters", "2",
        "-c:a", "copy", "-c:v", "copy", "-disposition:v:0", "attached_pic",
        str(out["cover"]))
    out["plain"] = w / "NoCover.m4b"
    _ff("-i", str(w / "a.m4a"), "-i", str(w / "meta.txt"), "-map", "0:a",
        "-map_metadata", "1", "-map_chapters", "1", "-c:a", "copy",
        str(out["plain"]))
    out["preroll"] = w / "LateStart.m4b"
    _ff("-i", str(w / "a.m4a"), "-i", str(w / "preroll.txt"), "-map", "0:a",
        "-map_metadata", "1", "-map_chapters", "1", "-c:a", "copy",
        str(out["preroll"]))
    return out


def real_work(source: Path, destination: Path, **kwargs) -> SegmentWork:
    defaults = dict(
        source=source, destination=destination, quality=6,
        metadata_mode=MetadataMode.PRESERVE, tags={"album": "Gen Album"},
        expected_duration=6.0)
    defaults.update(kwargs)
    return SegmentWork(**defaults)


def execute(work: SegmentWork) -> SegmentOutcome:
    return convert_segment(work, ffmpeg=ffmpeg_utils.ffmpeg_cmd(),
                           cancelled=never, measure=m4b_converter.measured_duration,
                           poll_seconds=0.01)


def test_the_generated_media_is_shaped_as_intended(media):
    assert _chapter_count(media["cover"]) == 3
    assert abs(_duration(media["cover"]) - 6.0) < 0.2
    streams = _probe(media["cover"], "-show_streams")["streams"]
    assert any(s.get("disposition", {}).get("attached_pic") for s in streams)
    assert not any(s.get("disposition", {}).get("attached_pic")
                   for s in _probe(media["plain"], "-show_streams")["streams"])


def test_a_whole_book_is_really_encoded(media, tmp_path):
    destination = tmp_path / "run" / "Book.mp3"
    outcome = execute(real_work(media["plain"], destination))
    assert outcome.finalised, outcome.detail
    assert destination.exists() and destination.stat().st_size > 0
    assert abs(_duration(destination) - 6.0) < 0.2


def test_a_whole_book_keeps_its_chapter_map_under_preserve(media, tmp_path):
    destination = tmp_path / "run" / "Book.mp3"
    assert execute(real_work(media["plain"], destination)).finalised
    assert _chapter_count(destination) == 3, "D6A: whole Preserve retains chapters"


def test_a_whole_book_under_strip_keeps_nothing(media, tmp_path):
    destination = tmp_path / "run" / "Stripped.mp3"
    assert execute(real_work(media["cover"], destination,
                             metadata_mode=MetadataMode.STRIP, tags={})).finalised
    assert _chapter_count(destination) == 0
    assert _covers(destination) == []
    assert "album" not in {k.lower() for k in _tags(destination)}


def test_a_whole_book_carries_its_cover_in_one_pass(media, tmp_path):
    destination = tmp_path / "run" / "Cover.mp3"
    streams = _probe(media["cover"], "-show_streams")["streams"]
    index = next(s["index"] for s in streams
                 if s.get("disposition", {}).get("attached_pic"))
    outcome = execute(real_work(media["cover"], destination,
                                picture=AttachedPicture(index, "mjpeg")))
    assert outcome.finalised, outcome.detail
    assert len(outcome.commands) == 1, "no second pass is needed without a seek"
    assert len(_covers(destination)) == 1


def test_a_source_is_never_modified(media, tmp_path):
    before = hashlib.sha256(media["cover"].read_bytes()).hexdigest()
    destination = tmp_path / "run" / "Book.mp3"
    assert execute(real_work(media["cover"], destination)).finalised
    assert hashlib.sha256(media["cover"].read_bytes()).hexdigest() == before


def split_works(source: Path, run: Path, spans, *, picture=None,
                mode=MetadataMode.PRESERVE):
    return [
        SegmentWork(
            source=source,
            destination=run / f"{order:02d} - Chapter {order}.mp3",
            expected_duration=end - start,
            quality=6,
            metadata_mode=mode,
            tags=({} if mode is MetadataMode.STRIP
                  else {"album": "Gen Album", "title": f"Chapter {order}",
                        "track": order}),
            picture=picture,
            span=(start, end),
        )
        for order, (start, end) in enumerate(spans, 1)
    ]


def test_a_split_produces_one_file_per_span_with_the_right_lengths(media, tmp_path):
    run = tmp_path / "run"
    spans = [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]
    for work in split_works(media["plain"], run, spans):
        outcome = execute(work)
        assert outcome.finalised, outcome.detail

    produced = sorted(run.iterdir())
    assert len(produced) == 3
    lengths = [_duration(p) for p in produced]
    for actual, (start, end) in zip(lengths, spans):
        assert abs(actual - (end - start)) < 0.15, (actual, start, end)
    assert abs(sum(lengths) - 6.0) < 0.3, "the segments tile the whole timeline"


def test_a_split_segment_drops_the_books_chapter_map(media, tmp_path):
    run = tmp_path / "run"
    work = split_works(media["plain"], run, [(0.0, 2.0)])[0]
    assert execute(work).finalised
    assert _chapter_count(work.destination) == 0, "a fragment is not the book"


def test_every_split_fragment_gets_the_cover(media, tmp_path):
    """§16's second pass, proved on produced media rather than on an argv."""
    run = tmp_path / "run"
    streams = _probe(media["cover"], "-show_streams")["streams"]
    index = next(s["index"] for s in streams
                 if s.get("disposition", {}).get("attached_pic"))
    works = split_works(media["cover"], run, [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)],
                        picture=AttachedPicture(index, "mjpeg"))
    for work in works:
        outcome = execute(work)
        assert outcome.finalised, outcome.detail
        assert len(outcome.commands) == 2, "audio, then the cover"
        assert len(_covers(work.destination)) == 1, work.destination.name
        assert abs(_duration(work.destination) - 2.0) < 0.15, (
            "the second pass copied the audio rather than re-encoding it")


def test_every_produced_file_carries_the_same_id3_version(media, tmp_path):
    """One run must not produce two tag versions, and it nearly did.

    The artwork pass re-muxes, so the mp3 muxer chooses the ID3 version again
    and its default is 2.4. Measured on produced media during Phase 11: a
    covered split fragment came out ID3v2.4 while the whole book and the
    uncovered fragment beside it were 2.3 -- and Windows Explorer, which this
    tool's audience uses, reads 2.3. ``attach_artwork_argv`` gained an additive,
    default-empty ``output_args`` seam so the second pass can be told the same
    thing the first was.
    """
    from mutagen.id3 import ID3

    run = tmp_path / "run"
    streams = _probe(media["cover"], "-show_streams")["streams"]
    index = next(s["index"] for s in streams
                 if s.get("disposition", {}).get("attached_pic"))
    picture = AttachedPicture(index, "mjpeg")

    whole = tmp_path / "whole" / "Book.mp3"
    assert execute(real_work(media["cover"], whole, picture=picture)).finalised

    covered = split_works(media["cover"], run, [(0.0, 2.0)], picture=picture)[0]
    assert execute(covered).finalised
    bare = split_works(media["plain"], run / "bare", [(0.0, 2.0)])[0]
    assert execute(bare).finalised

    versions = {path.name: ID3(str(path)).version[1]
                for path in (whole, covered.destination, bare.destination)}
    assert set(versions.values()) == {3}, versions
    assert len(ID3(str(covered.destination)).getall("APIC")) == 1, (
        "and the cover survived the version it was written at")


def test_a_stripped_split_fragment_has_no_cover(media, tmp_path):
    run = tmp_path / "run"
    streams = _probe(media["cover"], "-show_streams")["streams"]
    index = next(s["index"] for s in streams
                 if s.get("disposition", {}).get("attached_pic"))
    work = split_works(media["cover"], run, [(0.0, 2.0)],
                       picture=AttachedPicture(index, "mjpeg"),
                       mode=MetadataMode.STRIP)[0]
    outcome = execute(work)
    assert outcome.finalised and len(outcome.commands) == 1
    assert _covers(work.destination) == []


def test_a_source_with_no_cover_needs_no_second_pass(media, tmp_path):
    run = tmp_path / "run"
    work = split_works(media["plain"], run, [(0.0, 2.0)])[0]
    outcome = execute(work)
    assert outcome.finalised and len(outcome.commands) == 1
    assert _covers(work.destination) == []


def test_a_split_fragment_carries_its_own_title_and_track(media, tmp_path):
    run = tmp_path / "run"
    work = split_works(media["plain"], run, [(0.0, 2.0), (2.0, 4.0)])[1]
    assert execute(work).finalised
    tags = {k.lower(): v for k, v in _tags(work.destination).items()}
    assert tags.get("title") == "Chapter 2"
    assert str(tags.get("track", "")).split("/")[0] == "2"
    assert "NEVER" not in json.dumps(tags), "no unknown source atom leaked in"


# --------------------------------------------------------------------------- #
# Boundary audio — §28: the executor really runs the measured seek
# --------------------------------------------------------------------------- #


def test_the_executed_segments_neither_lose_nor_repeat_a_source_second(
        media, tmp_path):
    """The ledger, applied to what the **executor** produced.

    The fixture carries one identifiable burst per source second, so decoding
    every produced segment and mapping each burst back to its source second must
    recover 0..5 exactly once. A boundary that lost audio shows up as a missing
    second; one that repeated audio shows up as a second appearing twice.
    """
    run = tmp_path / "run"
    spans = [(0.0, 2.7), (2.7, 6.0)]
    recovered: list[int] = []
    for work, (start, end) in zip(split_works(media["plain"], run, spans), spans):
        assert execute(work).finalised
        samples = _decode(work.destination)
        assert abs(len(samples) / _SR - (end - start)) < 0.05
        recovered += [round(start + offset) for offset in _marker_offsets(samples)]

    assert sorted(recovered) == [0, 1, 2, 3, 4, 5], recovered
    assert len(recovered) == len(set(recovered)), recovered


def test_the_first_executed_segment_contains_the_very_beginning(media, tmp_path):
    run = tmp_path / "run"
    work = split_works(media["plain"], run, [(0.0, 2.0)])[0]
    assert execute(work).finalised
    offsets = _marker_offsets(_decode(work.destination))
    assert offsets, "no marker recovered at all"
    assert offsets[0] < 0.05, "source second 0 is missing from the first segment"


def test_a_later_executed_segment_begins_at_the_intended_boundary(media, tmp_path):
    run = tmp_path / "run"
    work = split_works(media["plain"], run, [(0.0, 2.7), (2.7, 4.2)])[1]
    assert execute(work).finalised
    offsets = _marker_offsets(_decode(work.destination))
    assert offsets, "no marker recovered"
    # Source second 3 sits 0.3 s into a segment that starts at 2.7 s.
    assert abs(offsets[0] - 0.3) < 0.05, offsets



def test_pre_roll_before_the_first_chapter_is_inside_the_first_output(
        media, tmp_path):
    """§27.3: the first chapter starts at 1.5 s, and second 0 must still ship.

    The late start is expressed as chapter *data* over the real audio rather
    than baked into the container, because ffmpeg's mov muxer normalises a first
    chapter back to zero when it writes one — which would quietly remove the
    very case this is testing. The audio, the duration and the execution are all
    real; only the chapter map is stated directly.
    """
    from mp3_tools import m4b_probe
    from mp3_tools.m4b_chapters import ChapterProbe, plan_timeline

    found = m4b_probe.probe_source(media["plain"])
    late = ChapterProbe(
        status=found.probe.status,
        duration=found.probe.duration,
        chapters=chapters(1.5, 4.0, titles=["After The Wait", "The Rest"]),
    )
    timeline = plan_timeline(late)
    assert timeline[0].start == 0.0, "pre-roll belongs to chapter one"
    assert len(timeline) == 2, "and no synthetic Opening file was invented"

    run = tmp_path / "run"
    work = SegmentWork(
        source=media["plain"],
        destination=run / "01 - After The Wait.mp3",
        expected_duration=timeline[0].duration, quality=6,
        metadata_mode=MetadataMode.PRESERVE,
        tags={"title": timeline[0].title, "track": 1},
        span=(timeline[0].start, timeline[0].end))
    assert execute(work).finalised
    offsets = _marker_offsets(_decode(work.destination))
    assert offsets and offsets[0] < 0.05, "the pre-roll was dropped"


def test_the_tail_after_the_last_chapter_is_inside_the_last_output(media, tmp_path):
    """The final segment ends at the source's own duration, not the last start."""
    from mp3_tools import m4b_probe
    from mp3_tools.m4b_chapters import ChapterProbe, plan_timeline

    found = m4b_probe.probe_source(media["plain"])
    late = ChapterProbe(
        status=found.probe.status,
        duration=found.probe.duration,
        chapters=chapters(1.5, 4.0, titles=["After The Wait", "The Rest"]),
    )
    timeline = plan_timeline(late)
    last = timeline[-1]
    assert abs(last.end - found.probe.duration) < 1e-9

    run = tmp_path / "run"
    work = SegmentWork(
        source=media["plain"], destination=run / "02 - The Rest.mp3",
        expected_duration=last.duration, quality=6,
        metadata_mode=MetadataMode.PRESERVE,
        tags={"title": last.title, "track": 2}, span=(last.start, last.end))
    assert execute(work).finalised
    recovered = [round(last.start + offset)
                 for offset in _marker_offsets(_decode(work.destination))]
    assert 5 in recovered, "the final source second was cut off"

def test_a_real_drift_breach_is_not_finalised(media, tmp_path):
    """A candidate whose length does not match the plan never becomes a file."""
    run = tmp_path / "run"
    work = SegmentWork(
        source=media["plain"], destination=run / "01 - Wrong.mp3",
        expected_duration=6.0,            # the plan asked for the whole book...
        quality=6, metadata_mode=MetadataMode.PRESERVE,
        tags={"title": "Wrong", "track": 1},
        span=(0.0, 2.0))                  # ...but the command produces two seconds
    outcome = execute(work)
    assert outcome.failed, "a 2 s output against a 6 s plan must not pass"
    assert "xHE-AAC" in outcome.message
    assert not work.destination.exists()
    assert list(run.iterdir()) == [], "and the candidate was cleaned up"



def test_a_real_run_through_the_panel_produces_real_files(media, tmp_path,
                                                          make_panel, monkeypatch):
    """End to end with nothing stubbed but the thread and the reservation.

    The thread is replaced through a **shim** rather than on the stdlib module:
    ``subprocess.communicate`` builds reader threads of its own, and swapping
    ``threading.Thread`` out from under it would break the very subprocess
    machinery this test exists to exercise.
    """
    StubThread.started = []
    monkeypatch.setattr(m4b_converter, "threading", _ThreadShim())
    monkeypatch.setattr(m4b_converter.sp, "reveal_in_file_manager", lambda t: None)

    panel = make_panel()
    add(panel, media["cover"])
    panel.var_mode.set(ConversionMode.SPLIT.value)
    plan = convert(panel, tmp_path)

    assert plan.total_segments == 3
    produced = sorted(p.name for p in plan.run_directory.iterdir())
    assert produced == ["01 - Ch One.mp3", "02 - Ch Two.mp3", "03 - Ch Three.mp3"]
    for name in produced:
        path = plan.run_directory / name
        assert len(_covers(path)) == 1, name
        assert _chapter_count(path) == 0, name
    assert panel.run_result.succeeded_count == 1
    assert panel.run_result.failed_count == 0

def test_the_execution_module_holds_no_tk_and_no_planning():
    tree = ast.parse(EXECUTION_SOURCE.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    assert "tkinter" not in modules
    text = EXECUTION_SOURCE.read_text(encoding="utf-8")
    for forbidden in ("tkinter", "messagebox", "job_ui", "job_control",
                      "planning_groups", "plan_timeline", "segment_filename",
                      "probe_source", "assemble_plan"):
        assert forbidden not in text, forbidden


def test_every_child_goes_through_the_shared_subprocess_seam():
    text = EXECUTION_SOURCE.read_text(encoding="utf-8")
    assert "subprocess.Popen" not in text
    assert "creationflags" not in text and "startupinfo" not in text
    assert "sp.popen" in text


def test_success_only_numbering_arrived_and_stayed_out_of_the_executor():
    """**A deliberate progression.** Phase 12 is the phase that adds the allocator.

    Through Phase 11 this asserted that no whole-book success allocator existed
    anywhere, because Phase 11's numbering was still the transitional positional
    form. It now asserts the two things that actually matter: the allocator
    exists in the panel that orchestrates a run, and the **executor still knows
    nothing about it**. Numbering is a layer around one metadata value, not part
    of the process lifecycle.
    """
    panel = PANEL_SOURCE.read_text(encoding="utf-8")
    execution = EXECUTION_SOURCE.read_text(encoding="utf-8")

    assert "SuccessNumbers" in panel
    assert "start_number + index" not in panel, "the positional form is retired"

    for absent in ("SuccessNumbers", "m4b_numbering", "auto_number",
                   "start_number", "propose(", "commit("):
        assert absent not in execution, absent

def test_retry_failed_is_wired_to_the_panel_and_to_a_real_result():
    """**A deliberate Phase 13 progression, not a deleted guard.**

    Through Phase 12 this asserted the opposite: no ``on_retry`` keyword and no
    ``set_result`` call anywhere in the panel, because offering Retry Failed
    before anything could execute one would have been a button promising work
    the phase could not do. Phase 13 is that work, so the same two facts are now
    asserted the other way round -- and they still have to arrive **together**,
    which is what the pairing below pins: a callback with no result behind it
    would leave the control permanently unavailable, and a result with no
    callback would make it available and inert.
    """
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "set_result" in called
    keywords = {keyword.arg for node in ast.walk(tree)
                if isinstance(node, ast.Call) for keyword in node.keywords}
    assert "on_retry" in keywords


def test_the_executor_re_plans_nothing():
    """It consumes the frozen answers; it does not compute new ones."""
    text = EXECUTION_SOURCE.read_text(encoding="utf-8")
    for forbidden in ("DestinationPlanner", "plan_flat", "plan_mirrored",
                      "plan_multi_root", "validate_chapters", "select_attached_picture",
                      "reserve_run_directory"):
        assert forbidden not in text, forbidden


def test_the_panel_stays_classic():
    assert "ACT." not in PANEL_SOURCE.read_text(encoding="utf-8")
