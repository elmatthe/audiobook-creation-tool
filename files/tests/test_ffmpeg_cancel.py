"""Cancel stops a running FFmpeg step in the MP3 Tool and the M4B Maker (v0.7.2 Phase 6C, ACT72-023).

Before, both tools ran FFmpeg and ffprobe through a blocking ``subprocess.run``: Cancel was seen only at the next
checkpoint, so a long encode ran to its end first (measured at 56c3b55 on a one-hour source: 9 s for the MP3 Tool,
27 s for the Maker), and a Write ID3 run whose only Book was encoding when Cancel was pressed published it and settled
SUCCEEDED. Now every such step goes through ``subprocess_utils.run_supervised`` inside the worker's
``cancellable`` block, which watches the controller's non-blocking ``cancel_check``.

Three layers, each with real processes:

* the supervisor itself, with controlled children: a copy of PING.EXE named ``ffmpeg.exe`` (a real, harmless,
  long-running program under the image name the rule looks for, as ``test_close_stops_media_children`` uses) and the
  base Python interpreter (one process, unlike the venv launcher);
* every FFmpeg and ffprobe step of both tools, each replaced in turn by that stand-in through the real supervisor, so
  Cancel is shown to reach the step it was pressed in and no later step to start;
* real media: a half-hour source, real FFmpeg, the tools' own worker bodies (the MP3 panel with real threads, the
  Maker's ``Attempt.run``), Cancel and Pause pressed while a long encode runs.

Every Cancel test also shows that an unrelated FFmpeg-named sentinel, a child of this very process, lives on.
"""

from __future__ import annotations

import ast
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path, PurePath

import pytest

from shared import book_workspace, ffmpeg_utils
from shared import subprocess_utils as sp
from shared.book_workspace import BookDisposition, BookJob
from shared.cancellation import ConversionCancelled
from shared.importing import IdFactory, ImportedFile, ImportedFileSnapshot, ImportRoot, Revision
from shared.job_control import JobController, JobState

from m4b.maker import m4b_maker_plan as mkp
from m4b.maker import m4b_maker_processing as mproc
from mp3 import mp3_plan, mp3_processing as proc

import source_probe
import test_m4b_maker_batch as mt
import test_mp3_write_id3 as w3
from test_import_coordination import RealThreads
from test_mp3_orchestration import wait_for
from test_mp3_tool_ui import (  # noqa: F401  (fixtures are collected by name)
    import_folder,
    make_panel,
    reservations_under,
    tk_root,
    windows_theme,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process identity")

PING = Path(r"C:\Windows\System32\PING.EXE")
BASE_PYTHON = Path(getattr(sys, "_base_executable", "") or sys.executable)
#: From the press to the worker having settled. Measured at about 0.05 s; the old blocking call took the rest of the step.
PROMPT_SECONDS = 2.0
_IDS = IdFactory("cx-")


# --------------------------------------------------------------------------- #
# Processes: identity, stand-ins, the sentinel
# --------------------------------------------------------------------------- #


def _media_children() -> list[int]:
    """Process ids of every ffmpeg.exe / ffprobe.exe whose parent is this process. Read-only."""
    import ctypes.wintypes as wt

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD),
                    ("szExeFile", wt.WCHAR * 260)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(ENTRY)]
    kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(ENTRY)]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    found = []
    try:
        entry = ENTRY()
        entry.dwSize = ctypes.sizeof(ENTRY)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32ParentProcessID == os.getpid() and entry.szExeFile.lower() in ("ffmpeg.exe", "ffprobe.exe"):
                found.append(int(entry.th32ProcessID))
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def _ping(image: Path, seconds: int = 120) -> list[str]:
    return [str(image), "-n", str(seconds), "127.0.0.1"]


@pytest.fixture
def named_ffmpeg(tmp_path) -> Path:
    target = tmp_path / "stand-in" / "ffmpeg.exe"
    target.parent.mkdir()
    shutil.copyfile(PING, target)
    return target


@pytest.fixture
def sentinel(named_ffmpeg):
    """An FFmpeg-named process this very process started that no tool owns. It must outlive every Cancel."""
    process = subprocess.Popen(_ping(named_ffmpeg, 300), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        yield process
        assert process.poll() is None, "an FFmpeg this run did not start was stopped"
    finally:
        process.kill()
        process.wait(10)


class Spawned:
    """Every child the supervisor starts, through the real hidden-window ``popen``."""

    def __init__(self, monkeypatch) -> None:
        self.children: list[tuple[list[str], subprocess.Popen, dict]] = []
        real = sp.popen

        def spy(cmd, **kwargs):
            child = real(cmd, **kwargs)
            self.children.append((list(cmd), child, kwargs))
            return child

        monkeypatch.setattr(sp, "popen", spy)

    def running(self, predicate=lambda argv: True) -> subprocess.Popen | None:
        for argv, child, _ in reversed(self.children):
            if predicate(argv) and child.poll() is None:
                return child
        return None

    def alive(self) -> list[subprocess.Popen]:
        return [child for _argv, child, _ in self.children if child.poll() is None]


class StandIn:
    """Run the *occurrence*-th FFmpeg/ffprobe step matching *matches* as the long stand-in, through the real supervisor.

    Every step the engine asks for is recorded, so a test can prove nothing ran after the one Cancel stopped."""

    def __init__(self, monkeypatch, image: Path, matches, occurrence: int = 1) -> None:
        self.calls: list[list[str]] = []
        self.replaced: list[str] | None = None
        self._seen = 0
        real = sp.run_supervised

        def run(args, **kwargs):
            argv = list(args)
            self.calls.append(argv)
            if self.replaced is None and matches(argv):
                self._seen += 1
                if self._seen == occurrence:
                    self.replaced = argv
                    return real(_ping(image), **kwargs)
            return real(argv, **kwargs)

        monkeypatch.setattr(sp, "run_supervised", run)


def _in_thread(target):
    box: dict = {}

    def body():
        try:
            box["value"] = target()
        except BaseException as exc:  # noqa: BLE001 - the test inspects it
            box["error"] = exc

    thread = threading.Thread(target=body, name="act72-023-worker", daemon=True)
    thread.start()
    return thread, box


def _until(predicate, timeout: float = 60.0, what: str = "the step") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


# --------------------------------------------------------------------------- #
# 1. The supervisor
# --------------------------------------------------------------------------- #


def _python(code: str) -> list[str]:
    return [str(BASE_PYTHON), "-I", "-c", code]


@contextmanager
def _cancel_block(flag: threading.Event, acknowledged: list | None = None):
    def acknowledge():
        if acknowledged is not None:
            acknowledged.append(time.monotonic())
        raise ConversionCancelled("Cancelled.")

    with sp.cancellable(flag.is_set, acknowledge):
        yield


def test_a_supervised_child_runs_to_its_end_and_returns_its_exit_code_and_output():
    flag = threading.Event()
    with _cancel_block(flag):
        done = sp.run_supervised(_python("import sys;sys.stdout.buffer.write(b'out');sys.stderr.buffer.write(b'err');"
                                         "sys.exit(3)"))
    assert done.returncode == 3, "a failure stays a failure: its own exit code, nothing invented"
    assert (done.stdout, done.stderr) == (b"out", b"err")


def test_cancel_stops_the_running_child_through_its_own_handle_promptly(monkeypatch, named_ffmpeg, sentinel):
    spawned = Spawned(monkeypatch)
    flag = threading.Event()
    acknowledged: list[float] = []
    with _cancel_block(flag, acknowledged):
        timer = threading.Timer(0.5, flag.set)
        timer.start()
        started = time.monotonic()
        with pytest.raises(ConversionCancelled):
            sp.run_supervised(_ping(named_ffmpeg, 120))
        elapsed = time.monotonic() - started
    (argv, child, kwargs), = spawned.children
    assert child.poll() is not None, "the child was stopped and collected"
    assert elapsed < 0.5 + PROMPT_SECONDS, f"Cancel took {elapsed:.2f} s to stop a 120 s child"
    assert len(acknowledged) == 1, "the worker's checkpoint hears the Cancel exactly once"
    assert kwargs.get("stdin") is subprocess.DEVNULL and kwargs.get("stdout") not in (None, subprocess.PIPE)
    assert _media_children() == [sentinel.pid]


def test_a_cancel_already_requested_starts_nothing(monkeypatch):
    spawned = Spawned(monkeypatch)
    flag = threading.Event()
    flag.set()
    acknowledged: list[float] = []
    with _cancel_block(flag, acknowledged), pytest.raises(ConversionCancelled):
        sp.run_supervised(_python("raise SystemExit(0)"))
    assert spawned.children == [] and len(acknowledged) == 1


def test_a_supervised_child_gets_no_console_window(monkeypatch):
    seen: dict = {}
    real = subprocess.Popen

    class Recording(real):  # type: ignore[valid-type, misc]
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", Recording)
    assert sp.run_supervised(_python("pass")).returncode == 0
    assert seen["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert seen["startupinfo"].wShowWindow == subprocess.SW_HIDE
    assert seen["stdin"] is subprocess.DEVNULL


def test_outside_a_cancel_block_a_child_simply_runs_to_its_end():
    done = sp.run_supervised(_python("print('whole')"))
    assert done.returncode == 0 and done.stdout.strip() == b"whole"


def test_a_child_that_floods_both_streams_cannot_block_and_only_the_tails_are_kept():
    code = ("import sys;e=sys.stderr.buffer;o=sys.stdout.buffer;[e.write(b'E'*65536) for _ in range(96)];"
            "e.write(b'<err-end>');e.flush();[o.write(b'O'*65536) for _ in range(96)];o.write(b'<out-end>');o.flush()")
    flag = threading.Event()
    started = time.monotonic()
    with _cancel_block(flag):
        done = sp.run_supervised(_python(code))
    assert done.returncode == 0 and time.monotonic() - started < 60
    for stream, end in ((done.stdout, b"<out-end>"), (done.stderr, b"<err-end>")):
        assert len(stream) == sp.SUPERVISED_TAIL_BYTES and stream.endswith(end)


class _Stubborn:
    """A child that ignores terminate (and, with ``immortal``, kill too): the ladder must still end."""

    def __init__(self, immortal: bool) -> None:
        self.pid = 4242
        self.returncode = None
        self.steps: list[str] = []
        self._immortal = immortal

    def wait(self, timeout=None):
        if self.steps[-1:] == ["kill"] and not self._immortal:
            self.returncode = 1
            return 1
        time.sleep(min(timeout or 0, 0.01))
        raise subprocess.TimeoutExpired("stand-in", timeout)

    def terminate(self):
        self.steps.append("terminate")

    def kill(self):
        self.steps.append("kill")


@pytest.mark.parametrize("immortal", [False, True], ids=["killed", "never-exits"])
def test_a_child_that_will_not_stop_is_killed_and_waited_for_only_boundedly(monkeypatch, immortal):
    stubborn = _Stubborn(immortal)
    monkeypatch.setattr(sp, "popen", lambda cmd, **kwargs: stubborn)
    calls = {"n": 0}

    def cancel_check():  # not yet when the step starts, then at the first look
        calls["n"] += 1
        return calls["n"] > 1

    started = time.monotonic()
    with sp.cancellable(cancel_check), pytest.raises(ConversionCancelled) as raised:
        sp.run_supervised(["ffmpeg"], grace_seconds=0.05)
    assert time.monotonic() - started < 1.0
    assert stubborn.steps == ["terminate", "kill"], "terminate first, then kill, never more"
    notes = getattr(raised.value, "__notes__", [])
    assert bool(notes) is immortal, "a child that did not exit is reported, not waited on for ever"


def test_an_error_while_watching_still_stops_and_collects_the_child(monkeypatch, named_ffmpeg):
    spawned = Spawned(monkeypatch)
    started = time.monotonic()

    def broken():
        if time.monotonic() - started > 0.3:
            raise RuntimeError("the predicate failed")
        return False

    with sp.cancellable(broken), pytest.raises(RuntimeError):
        sp.run_supervised(_ping(named_ffmpeg, 120))
    (_argv, child, _), = spawned.children
    assert child.poll() is not None


# --------------------------------------------------------------------------- #
# 2. Every FFmpeg / ffprobe step of the MP3 Tool answers to Cancel
# --------------------------------------------------------------------------- #


def _mp3_plan(sources: Path, reserve, *, operation="write", rates=(44100,), seconds=1.0, **configuration):
    files = []
    for index, rate in enumerate(rates, start=1):
        path = sources / "Book" / f"{index:02d}.mp3"
        path.parent.mkdir(parents=True, exist_ok=True)
        sp.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                "-i", f"sine=frequency={400 + 50 * index}:duration={seconds}", "-ac", "2", "-ar", str(rate),
                "-c:a", "libmp3lame", "-b:a", "64k", str(path)], check=True)
        occurrence = w3._IDS.next_id("occurrence")
        files.append(ImportedFile(occurrence, path, ImportRoot("r", sources, 0), PurePath("Book") / path.name, "mp3",
                                  f"id-{occurrence}"))
    entry = w3.book(files, **configuration)
    space, store = w3.workspace(entry), w3.observe(entry)
    if operation == "combine":
        import test_mp3_combine as cm
        return cm.plan(space, store, reserve)
    return w3.plan(space, store, reserve)


def _decode_of(path_of):
    return lambda made: (lambda argv: "-progress" in argv and "-xerror" in argv
                         and argv[argv.index("-i") + 1] == str(path_of(made)))


def _track(m):
    return m.books[0].tracks[0].staged


def _combined(m):
    return m.books[0].combined_staged


def _nothing(m):
    return None


_COMBINE_ALIKE = {"operation": "combine", "rates": (44100, 44100)}
_COMBINE_UNLIKE = {"operation": "combine", "rates": (44100, 22050)}

_MP3_STAGES = {
    # name: (plan options, matcher(made) -> predicate(argv), what the stopped step was writing)
    "source-duration": ({}, _decode_of(lambda m: m.books[0].tracks[0].source), _nothing),
    "copy": ({}, lambda m: lambda argv: "copy" in argv and argv[-1] == str(_track(m)), _track),
    "append": ({"time_delta": "1"}, lambda m: lambda argv: "-filter_complex" in argv, _track),
    "trim": ({"time_delta": "-0.5"}, lambda m: lambda argv: "-t" in argv and "libmp3lame" in argv, _track),
    "staged-duration": ({}, _decode_of(_track), _nothing),
    "eligibility-probe": (_COMBINE_ALIKE, lambda m: lambda argv: argv[0] == ffmpeg_utils.ffprobe_cmd(), _nothing),
    "fast-concat": (_COMBINE_ALIKE, lambda m: lambda argv: any(a.endswith("inputs_fast.txt") for a in argv),
                    _combined),
    "safe-normalize": (_COMBINE_UNLIKE, lambda m: lambda argv: argv[-1].endswith(".wav"), _nothing),
    "safe-concat": (_COMBINE_UNLIKE, lambda m: lambda argv: any(a.endswith("inputs_safe.txt") for a in argv),
                    _combined),
    "combined-duration": (_COMBINE_ALIKE, _decode_of(_combined), _nothing),
}


@pytest.mark.parametrize("stage", list(_MP3_STAGES))
def test_cancel_stops_every_mp3_ffmpeg_step_and_nothing_runs_after_it(stage, tmp_path, monkeypatch, named_ffmpeg,
                                                                      sentinel):
    options, matcher, writes = _MP3_STAGES[stage]
    options = dict(options)
    sources = tmp_path / "Sources"
    made = _mp3_plan(sources, _mp3_reserve(tmp_path), **options)
    before = hashes(sources)
    stand_in = StandIn(monkeypatch, named_ffmpeg, matcher(made))
    spawned = Spawned(monkeypatch)
    controller = JobController("cx-mp3")
    controller.start()
    engine = proc.combine_run if made.operation is mp3_plan.MP3Operation.COMBINE else proc.write_id3_run
    thread, box = _in_thread(lambda: engine(made, checkpoint=controller.checkpoint,
                                            cancel_check=controller.cancel_check))
    _until(lambda: spawned.running(lambda argv: argv[0] == str(named_ffmpeg)) is not None or not thread.is_alive(),
           what=f"the {stage} step")
    assert stand_in.replaced is not None, f"the run never reached its {stage} step"
    partial = writes(made)
    if partial is not None:  # what a real FFmpeg would have written so far; the stand-in writes nothing itself
        partial.write_bytes(b"\xff\xfb half-written")
    pressed = time.monotonic()
    controller.request_cancel()
    controller.request_cancel()
    thread.join(PROMPT_SECONDS + 5)
    elapsed = time.monotonic() - pressed
    assert not thread.is_alive() and isinstance(box.get("error"), ConversionCancelled), box
    assert elapsed < PROMPT_SECONDS, f"Cancel took {elapsed:.2f} s to stop the {stage} step"
    assert stand_in.calls[-1] is stand_in.replaced, "a step started after Cancel"
    assert spawned.alive() == [] and _media_children() == [sentinel.pid]
    controller.finish_cancelled()  # the worker acknowledged it, so the run can settle as cancelled
    book = made.books[0]
    assert not book.published_dir.exists() or not any(p.is_file() for p in book.published_dir.rglob("*")),         "nothing was published"
    assert partial is None or not partial.exists(), f"the stopped step's half-written {partial.name} was left"
    assert hashes(sources) == before


def _mp3_reserve(tmp_path: Path):
    from shared import output_paths

    counter = {"n": 0}

    def make(tool_key="mp3_tool", **_kw):
        counter["n"] += 1
        directory = tmp_path / "Outputs" / f"MP3-Tool-{counter['n']}"
        directory.mkdir(parents=True)
        return output_paths.RunReservation(tool_key=tool_key, base_directory=tmp_path / "Outputs",
                                           tool_directory=tmp_path / "Outputs", run_directory=directory,
                                           run_number=counter["n"])
    return make


def test_cancel_latched_between_two_steps_starts_no_further_ffmpeg(tmp_path, monkeypatch):
    """No checkpoint lies between a track's duration probe and its encode: the supervisor is what refuses the encode."""
    made = _mp3_plan(tmp_path / "Sources", _mp3_reserve(tmp_path), time_delta="1")
    spawned = Spawned(monkeypatch)
    controller = JobController("cx-latch")
    controller.start()
    real = proc._decode_duration_seconds

    def probe_then_cancel(path):
        value = real(path)
        controller.request_cancel()  # latched after the probe finished, before the encode is asked for
        return value

    monkeypatch.setattr(proc, "_decode_duration_seconds", probe_then_cancel)
    with pytest.raises(ConversionCancelled):
        proc.write_id3_run(made, checkpoint=controller.checkpoint, cancel_check=controller.cancel_check)
    assert len(spawned.children) == 1 and "-progress" in spawned.children[0][0], "only the probe ever ran"
    assert not made.books[0].tracks[0].staged.exists() and not made.books[0].published_dir.exists()


def test_a_launch_failure_is_still_the_999_failure_and_a_cancel_is_never_one(monkeypatch):
    def cannot_start(cmd, **kwargs):
        raise OSError("no such program")

    monkeypatch.setattr(sp, "popen", cannot_start)
    code, out, err = proc.run_ff(["ffmpeg", "-version"])
    assert (code, out) == (999, "") and "no such program" in err
    flag = threading.Event()
    flag.set()
    with _cancel_block(flag), pytest.raises(ConversionCancelled):
        proc.run_ff(["ffmpeg", "-version"])


def test_a_genuine_mp3_failure_in_a_supervised_run_stays_retryable_and_retry_failed_rebuilds_it(
        tmp_path, monkeypatch):
    made = _mp3_plan(tmp_path / "Sources", _mp3_reserve(tmp_path), rates=(44100, 44100), time_delta="1")
    book = made.books[0]
    broken = book.tracks[1]
    real_args = proc._append_silence_args
    controller = JobController("cx-fail")
    controller.start()
    with monkeypatch.context() as patch:
        patch.setattr(proc, "_append_silence_args", lambda source, seconds, out: (
            real_args(source, seconds, out)[:-1] + ["-no_such_option_for_ffmpeg", str(out)]
            if out == broken.staged else real_args(source, seconds, out)))
        first = proc.write_id3_run(made, checkpoint=controller.checkpoint, cancel_check=controller.cancel_check)
    assert controller.cancel_check() is False and controller.state is JobState.RUNNING, "no Cancel was involved"
    (report,) = first.books
    (failure,) = report.result.failures.records
    assert failure.item_id == broken.occurrence_id and failure.retryable and failure.stage == "append"
    assert not book.published_dir.exists() or not any(book.published_dir.iterdir())
    retry = JobController("cx-fail-2")
    retry.start()
    second = proc.write_id3_run(made, checkpoint=retry.checkpoint, cancel_check=retry.cancel_check,
                                retry_items={book.book_id: (broken.occurrence_id,)})
    assert second.books[0].succeeded
    assert all(track.published.is_file() for track in book.tracks)


# --------------------------------------------------------------------------- #
# 3. Every FFmpeg / ffprobe step of the M4B Maker answers to Cancel
# --------------------------------------------------------------------------- #


def _maker_run(tmp_path: Path, *, silence: str = "0", fast_first: bool = True, auto_number: bool = False,
               books: int = 1):
    sources = tmp_path / "Sources"
    sources.mkdir(exist_ok=True)
    reserve = _maker_reserve(tmp_path)
    extra = {"silence": silence} if silence != "0" else {}
    jobs = [mt.book(sources, f"B{index}", ("01.mp3", "02.mp3"), title=f"B{index}", **extra)
            for index in range(books)]
    options = mkp.MakerRunOptions(fast_first=fast_first, auto_number=auto_number,
                                  **({"start_part_text": "1"} if auto_number else {}))
    made = mt.plan(mt.workspace(*jobs), reserve, options)
    run, events = mt.make_run(made)
    return made, run, sources


def _maker_reserve(tmp_path: Path):
    from shared import output_paths

    counter = {"n": 0}

    def make(**_kw):
        counter["n"] += 1
        directory = tmp_path / "Outputs" / "M4B-Maker-Outputs" / f"M4B-Maker-{counter['n']}"
        directory.mkdir(parents=True)
        return output_paths.RunReservation(tool_key="m4b_maker", base_directory=tmp_path / "Outputs",
                                           tool_directory=directory.parent, run_directory=directory,
                                           run_number=counter["n"])
    return make


def _probe_of(path_of):
    return lambda made: (lambda argv: argv[0] == ffmpeg_utils.ffprobe_cmd() and "stream=duration" in argv
                         and argv[-1] == str(path_of(made)))


_MAKER_STAGES = {
    # name: (run options, matcher(made) -> predicate(argv), occurrence)
    "decoded-duration": ({}, lambda m: lambda argv: "-progress" in argv, 1),
    "fast-concat": ({}, lambda m: lambda argv: "-fflags" in argv and argv[-1] == str(m.books[0].staged), 1),
    "normalize": ({"silence": "0.5"}, lambda m: lambda argv: argv[-1].endswith("0001.wav"), 1),
    "silence": ({"silence": "0.5"}, lambda m: lambda argv: any(a.startswith("anullsrc") for a in argv), 1),
    "safe-concat": ({"fast_first": False},
                    lambda m: lambda argv: "-fflags" not in argv and "concat" in argv
                    and argv[-1] == str(m.books[0].staged), 1),
    "validate-probe": ({}, _probe_of(lambda m: m.books[0].staged), 1),
    "number-probe": ({"auto_number": True}, _probe_of(lambda m: m.books[0].staged), 2),
}


@pytest.mark.parametrize("stage", list(_MAKER_STAGES))
def test_cancel_stops_every_maker_ffmpeg_step_and_nothing_runs_after_it(stage, tmp_path, monkeypatch, named_ffmpeg,
                                                                        sentinel):
    options, matcher, occurrence = _MAKER_STAGES[stage]
    made, run, sources = _maker_run(tmp_path, **options)
    before = hashes(sources)
    stand_in = StandIn(monkeypatch, named_ffmpeg, matcher(made), occurrence)
    spawned = Spawned(monkeypatch)
    attempt = run.start()
    thread, box = _in_thread(attempt.run)
    _until(lambda: spawned.running(lambda argv: argv[0] == str(named_ffmpeg)) is not None or not thread.is_alive(),
           what=f"the {stage} step")
    assert stand_in.replaced is not None, f"the build never reached its {stage} step"
    pressed = time.monotonic()
    run.cancel()
    run.cancel()
    thread.join(PROMPT_SECONDS + 5)
    elapsed = time.monotonic() - pressed
    assert not thread.is_alive() and "error" not in box, box
    assert elapsed < PROMPT_SECONDS, f"Cancel took {elapsed:.2f} s to stop the {stage} step"
    result = box["value"]
    assert result.state is JobState.CANCELLED and attempt.controller.state is JobState.CANCELLED
    assert [d for _id, d in result.dispositions] == [BookDisposition.NOT_ATTEMPTED], "never a retryable failure"
    assert stand_in.calls[-1] is stand_in.replaced, "a step started after Cancel"
    assert spawned.alive() == [] and _media_children() == [sentinel.pid]
    book = made.books[0]
    assert not book.published.exists() and not book.staging_dir.exists()
    assert not made.work_root.exists() or not any(made.work_root.iterdir())
    if run.numbers is not None:
        assert run.numbers.consumed == 0, "a cancelled Book commits no Series Part"
    assert hashes(sources) == before


def test_cancel_while_a_retained_candidate_is_checked_discards_it_and_publishes_nothing(
        tmp_path, monkeypatch, named_ffmpeg, sentinel):
    made, run, _sources = _maker_run(tmp_path, auto_number=True)
    book = made.books[0]
    real_publish = mproc.publish_book

    def refuse_once(entry, *, work_root):
        if not refuse_once.done:
            refuse_once.done = True
            raise mproc.ProcessingError("destination refused", stage="publish", detail="x")
        return real_publish(entry, work_root=work_root)

    refuse_once.done = False
    monkeypatch.setattr(mproc, "publish_book", refuse_once)
    first = run.start().run()
    assert first.state is JobState.COMPLETED_WITH_FAILURES and book.staged.is_file(), "the candidate is retained"
    stand_in = StandIn(monkeypatch, named_ffmpeg, _probe_of(lambda m: m.books[0].staged)(made))
    spawned = Spawned(monkeypatch)
    retry = run.retry_failed()
    thread, box = _in_thread(retry.run)
    _until(lambda: spawned.running(lambda argv: argv[0] == str(named_ffmpeg)) is not None or not thread.is_alive(),
           what="the retained candidate's check")
    assert stand_in.replaced is not None, "the retry never checked its kept candidate"
    pressed = time.monotonic()
    run.cancel()
    thread.join(PROMPT_SECONDS + 5)
    elapsed = time.monotonic() - pressed
    assert elapsed < PROMPT_SECONDS, f"Cancel took {elapsed:.2f} s to stop the candidate's check"
    assert box["value"].state is JobState.CANCELLED
    assert stand_in.calls == [stand_in.replaced], "nothing re-encoded or published after Cancel"
    assert not book.published.exists() and not book.staging_dir.exists()
    assert run.numbers.consumed == 0
    assert _media_children() == [sentinel.pid]


# --------------------------------------------------------------------------- #
# 4. Real media, the tools' own worker bodies
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def half_hour(tmp_path_factory) -> Path:
    """A 30-minute MP3 of plain frames, made in seconds: one 10-minute encode joined three times (no tag in between)."""
    if not ffmpeg_utils.have_ffmpeg():
        pytest.fail("ffmpeg/ffprobe could not be resolved; real-media Cancel cannot be proved")
    folder = tmp_path_factory.mktemp("act72-023-media")
    segment = folder / "segment.mp3"
    sp.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=600", "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "64k",
            "-write_xing", "0", "-id3v2_version", "0", "-write_id3v1", "0", str(segment)], check=True)
    whole = folder / "half-hour.mp3"
    whole.write_bytes(segment.read_bytes() * 3)
    return whole


def _place(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def _short(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    sp.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", "sine=frequency=550:duration=2", "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "64k",
            str(target)], check=True)
    return target


def _imported(path: Path, root: Path) -> ImportedFile:
    occurrence = _IDS.next_id("occurrence")
    return ImportedFile(occurrence, path, ImportRoot("r", root, 0), PurePath(path.parent.name) / path.name, "mp3",
                        f"id-{occurrence}")


def _two_book_mp3_plan(tmp_path: Path, first: Path, second: Path, **configuration):
    root = tmp_path / "Sources"
    entries = [w3.book([_imported(path, root)], **configuration) for path in (first, second)]
    return w3.plan(w3.workspace(*entries), w3.observe(*entries), _mp3_reserve(tmp_path))


def test_mp3_cancel_during_a_real_encode_stops_it_at_once_and_keeps_the_earlier_book(
        tmp_path, monkeypatch, half_hour, sentinel):
    short = _short(tmp_path / "Sources" / "A" / "01 Short.mp3")
    long = _place(half_hour, tmp_path / "Sources" / "B" / "01 Long.mp3")
    made = _two_book_mp3_plan(tmp_path, short, long, time_delta="1")
    before = hashes(tmp_path / "Sources")
    spawned = Spawned(monkeypatch)
    controller = JobController("cx-real-mp3")
    controller.start()
    thread, box = _in_thread(lambda: proc.write_id3_run(made, checkpoint=controller.checkpoint,
                                                        cancel_check=controller.cancel_check))
    target = made.books[1].tracks[0].staged
    _until(lambda: spawned.running(lambda argv: argv[-1] == str(target)) is not None and target.exists(),
           what="the half-hour encode")
    encode = spawned.running(lambda argv: argv[-1] == str(target))
    time.sleep(0.3)
    published = {p: sha(p) for p in made.books[0].published_dir.rglob("*") if p.is_file()}
    assert published, "the first Book was published before the long one started"
    pressed = time.monotonic()
    controller.request_cancel()
    controller.request_cancel()
    thread.join(60)
    elapsed = time.monotonic() - pressed
    assert isinstance(box.get("error"), ConversionCancelled), box
    assert elapsed < PROMPT_SECONDS, f"the encode ran on for {elapsed:.2f} s after Cancel"
    assert encode.returncode not in (None, 0), "the encode was stopped, not finished"
    controller.finish_cancelled()
    assert {p: sha(p) for p in published} == published, "the Book published before Cancel is untouched"
    assert not made.books[1].published_dir.exists(), "nothing of the cancelled Book was published"
    assert not target.exists(), "the half-written staged track was removed"
    assert hashes(tmp_path / "Sources") == before
    assert spawned.alive() == [] and _media_children() == [sentinel.pid]


def test_mp3_panel_cancel_stops_a_real_combine_encode(make_panel, tmp_path, monkeypatch, half_hour, sentinel):
    panel = make_panel(thread_factory=RealThreads())
    reservations_under(tmp_path, monkeypatch)
    folder = tmp_path / "Library" / "Book"
    _place(half_hour, folder / "01 Long.mp3")
    _short(folder / "02 Short.mp3")
    before = hashes(tmp_path / "Library")
    import_folder(panel, tmp_path / "Library")
    wait_for(panel, lambda: panel.workspace.count == 1 and len(panel.workspace.books[0].files.files) == 2,
             timeout=60)
    spawned = Spawned(monkeypatch)
    assert panel.combine_mp3s(), make_panel.dialogs
    fast = lambda argv: any(a.endswith("inputs_fast.txt") for a in argv)  # noqa: E731
    wait_for(panel, lambda: spawned.running(fast) is not None, timeout=60)
    encode = spawned.running(fast)
    time.sleep(0.3)
    pressed = time.monotonic()
    panel.cancel()
    panel.cancel()
    wait_for(panel, lambda: not panel.is_running, timeout=30)
    elapsed = time.monotonic() - pressed
    assert elapsed < PROMPT_SECONDS, f"the combine ran on for {elapsed:.2f} s after Cancel"
    assert encode.returncode not in (None, 0)
    result = panel.last_result
    assert result.state is JobState.CANCELLED
    book = panel.last_plan.books[0]
    assert result.disposition_for(book.book_id) is BookDisposition.NOT_ATTEMPTED
    assert not result.can_retry_failed, "Retry Failed is never offered after Cancel"
    assert not book.combined_published.exists() and not book.combined_staged.exists()
    assert hashes(tmp_path / "Library") == before
    assert spawned.alive() == [] and _media_children() == [sentinel.pid]


def test_mp3_pause_lets_the_running_encode_finish_and_waits_at_the_next_book(tmp_path, monkeypatch, half_hour):
    long = _place(half_hour, tmp_path / "Sources" / "A" / "01 Long.mp3")
    short = _short(tmp_path / "Sources" / "B" / "01 Short.mp3")
    made = _two_book_mp3_plan(tmp_path, long, short, time_delta="1")
    spawned = Spawned(monkeypatch)
    controller = JobController("cx-pause-mp3")
    controller.start()
    thread, box = _in_thread(lambda: proc.write_id3_run(made, checkpoint=controller.checkpoint,
                                                        cancel_check=controller.cancel_check))
    target = made.books[0].tracks[0].staged
    _until(lambda: spawned.running(lambda argv: argv[-1] == str(target)) is not None, what="the half-hour encode")
    encode = spawned.running(lambda argv: argv[-1] == str(target))
    controller.request_pause()
    while encode.poll() is None:
        assert controller.state is JobState.PAUSE_REQUESTED, "PAUSED was claimed while FFmpeg was still encoding"
        time.sleep(0.02)
    assert encode.returncode == 0, "Pause let the step finish; it was not stopped"
    _until(lambda: controller.state is JobState.PAUSED, what="the pause at the next Book")
    assert made.books[0].tracks[0].published.is_file(), "the Book in flight completed before the pause"
    assert not made.books[1].published_dir.exists() and not made.books[1].tracks[0].staged.exists(), \
        "nothing of the next Book ran while paused"
    controller.resume()
    thread.join(60)
    report = box["value"]
    assert all(entry.succeeded for entry in report.books)
    assert abs(w3.duration(made.books[0].tracks[0].published) - (w3.duration(long) + 1.0)) < 0.5


def _two_book_maker_run(tmp_path: Path, first: Path, second: Path):
    sources = tmp_path / "Sources"
    jobs = [BookJob(book_id=book_workspace.new_book_id(_IDS), configuration={"title": f"T{index}"},
                    files=ImportedFileSnapshot(Revision(1), (_imported(path, sources),)))
            for index, path in enumerate((first, second))]
    made = mt.plan(mt.workspace(*jobs), _maker_reserve(tmp_path), mkp.MakerRunOptions())
    run, _events = mt.make_run(made)
    return made, run


def test_maker_cancel_during_a_real_encode_stops_it_at_once_and_keeps_the_earlier_book(
        tmp_path, monkeypatch, half_hour, sentinel):
    short = _short(tmp_path / "Sources" / "A" / "01 Short.mp3")
    long = _place(half_hour, tmp_path / "Sources" / "B" / "01 Long.mp3")
    made, run = _two_book_maker_run(tmp_path, short, long)
    before = hashes(tmp_path / "Sources")
    spawned = Spawned(monkeypatch)
    attempt = run.start()
    thread, box = _in_thread(attempt.run)
    target = made.books[1].staged
    _until(lambda: spawned.running(lambda argv: argv[-1] == str(target)) is not None and target.exists(),
           what="the half-hour AAC encode")
    encode = spawned.running(lambda argv: argv[-1] == str(target))
    time.sleep(0.3)
    first = made.books[0].published
    kept = sha(first)
    pressed = time.monotonic()
    run.cancel()
    run.cancel()
    thread.join(60)
    elapsed = time.monotonic() - pressed
    assert elapsed < PROMPT_SECONDS, f"the encode ran on for {elapsed:.2f} s after Cancel"
    assert encode.returncode not in (None, 0)
    result = box["value"]
    assert result.state is JobState.CANCELLED
    assert [d for _id, d in result.dispositions] == [BookDisposition.SUCCEEDED, BookDisposition.NOT_ATTEMPTED]
    assert not result.can_retry_failed
    assert sha(first) == kept
    assert not made.books[1].published.exists() and not made.books[1].staging_dir.exists()
    assert not made.work_root.exists() or not any(made.work_root.iterdir())
    assert hashes(tmp_path / "Sources") == before
    assert spawned.alive() == [] and _media_children() == [sentinel.pid]


def test_maker_pause_lets_the_running_encode_finish_and_waits_at_the_next_book(tmp_path, monkeypatch, half_hour):
    long = _place(half_hour, tmp_path / "Sources" / "A" / "01 Long.mp3")
    short = _short(tmp_path / "Sources" / "B" / "01 Short.mp3")
    made, run = _two_book_maker_run(tmp_path, long, short)
    spawned = Spawned(monkeypatch)
    attempt = run.start()
    thread, box = _in_thread(attempt.run)
    target = made.books[0].staged
    _until(lambda: spawned.running(lambda argv: argv[-1] == str(target)) is not None, what="the half-hour encode")
    encode = spawned.running(lambda argv: argv[-1] == str(target))
    run.pause()
    while encode.poll() is None:
        assert attempt.controller.state is JobState.PAUSE_REQUESTED, "PAUSED was claimed while FFmpeg was encoding"
        time.sleep(0.02)
    assert encode.returncode == 0, "Pause let the step finish; it was not stopped"
    # The Maker's approved boundary is its next checkpoint: between steps inside a Book, or between Books.
    _until(lambda: attempt.controller.state is JobState.PAUSED, what="the pause at the next checkpoint")
    assert not made.books[1].staging_dir.exists(), "nothing of the next Book ran while paused"
    run.resume()
    thread.join(120)
    assert box["value"].state is JobState.SUCCEEDED
    for book in made.books:
        mproc.validate_staged_m4b(book, book.published)


# --------------------------------------------------------------------------- #
# 5. Structure: no FFmpeg step of either tool can bypass the supervisor
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module", ["mp3/mp3_processing.py", "m4b/maker/m4b_maker_processing.py"])
def test_every_ffmpeg_call_of_the_engines_goes_through_the_supervisor(module):
    tree = source_probe.module(module)
    called = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)]
    through_sp = {func.attr for func in called if func.value.id == "sp"}
    assert "run_supervised" in through_sp and through_sp <= {"run_supervised", "cancellable"}, \
        f"{module} starts a process another way: {sorted(through_sp)}"
    assert not any(func.value.id == "subprocess" for func in called)
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                and node.module == "subprocess" for alias in node.names}
    assert imported <= {"CalledProcessError"}, imported


def test_both_worker_bodies_hand_their_ffmpeg_steps_the_non_blocking_cancel_check():
    attempt = next(node for node in ast.walk(source_probe.module("m4b/maker/m4b_maker_batch.py"))
                   if isinstance(node, ast.FunctionDef) and node.name == "run")
    text = ast.unparse(attempt)
    assert "sp.cancellable(controller.cancel_check, controller.checkpoint)" in text
    panel = next(node for node in ast.walk(source_probe.module("mp3/mp3_tool.py"))
                 if isinstance(node, ast.FunctionDef) and node.name == "_run_attempt")
    assert "cancel_check=attempt.controller.cancel_check" in ast.unparse(panel)
