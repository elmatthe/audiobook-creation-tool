"""A busy file manager never holds a window (v0.7.2 Phase 8, ACT72-062).

When a run ended, the M4B Converter asked the operating system to show its output folder from the window's own
thread. That call waits for Explorer; while Explorer was busy or restarting the whole window stopped (36.9 s measured
in Phase 7B). ``shared.subprocess_utils.reveal_in_file_manager`` now hands the call to one background thread and
returns at once.

Two layers:

* **The helper**, with the operating system's call (``_ask_file_manager``) replaced by a stand-in that holds its caller
  until the test lets go: who waits, what is refused, what a failure says, and that nothing is asked twice.
* **The real Converter panel in the real Tk loop**, with its real worker thread and its real pump, converting a real
  book with the pinned FFmpeg. The test turns the loop itself and records the longest time it ever went without
  turning. The same measurement is shown to see the old behaviour (the call made by the window's thread), so a pass
  here cannot be an instrument that sees nothing.

No file manager window is opened by any test: every route to the operating system goes through the stand-in.
"""

from __future__ import annotations

import ast
import sys
import threading
import time
import unittest.mock as mock
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import job_control as jc  # noqa: E402
from shared import output_paths  # noqa: E402
from shared import subprocess_utils as sp  # noqa: E402

from m4b.converter import m4b_converter  # noqa: E402

from test_importing import make_config  # noqa: E402
from test_m4b_continuous import make_book  # noqa: E402
from test_m4b_conversion_plan import _reservation  # noqa: E402
from test_m4b_metadata import require_ffmpeg  # noqa: E402
import source_probe  # noqa: E402
import tk_gate  # noqa: E402

#: Every wait here is bounded, so a defect fails rather than hangs.
WAIT = 30.0
#: The longest the Tk loop may go without turning while the file manager is busy. The loop is turned every 5 ms; a
#: window that waited on the file manager would show the whole hold (seconds).
LOOP_LIMIT_SECONDS = 0.5


class FileManager:
    """Stands where the operating system's call stands: records who asked, then holds each caller until released."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []     # (folder, asked on the main thread?)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.answer: str | None = None
        #: Set to a number of seconds to hold each caller exactly that long instead of until released.
        self.hold: float | None = None

    def __call__(self, target: str, platform=None):
        self.calls.append((target, threading.current_thread() is threading.main_thread()))
        self.entered.set()
        if self.hold is not None:
            time.sleep(self.hold)
        else:
            assert self.release.wait(WAIT), "the test never released the stand-in file manager"
        return self.answer


@pytest.fixture()
def manager(monkeypatch):
    stand_in = FileManager()
    monkeypatch.setattr(sp, "_ask_file_manager", stand_in)
    yield stand_in
    stand_in.release.set()
    _drained()


def _drained() -> None:
    """Wait for the helper's thread to end, so no request of one test is still waiting in the next."""
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        with sp._reveal_lock:
            if not sp._reveal_queue and sp._reveal_thread is None:
                return
        time.sleep(0.01)
    raise AssertionError("the reveal thread did not end")


# --------------------------------------------------------------------------- #
# The helper
# --------------------------------------------------------------------------- #


def test_the_request_returns_while_the_file_manager_is_still_busy(manager, tmp_path):
    started = time.monotonic()
    request = sp.reveal_in_file_manager(tmp_path)
    returned = time.monotonic() - started
    assert manager.entered.wait(WAIT)
    assert returned < 0.5, f"the caller waited {returned:.2f} s"
    assert manager.calls == [(str(tmp_path), False)], "asked once, and not by the caller's thread"
    assert not request.done and request.reason is None
    manager.release.set()
    assert request.wait(WAIT) and request.reason is None


def test_a_folder_that_cannot_be_shown_says_why_exactly_once(manager, tmp_path):
    manager.answer = "FileNotFoundError: no such folder"
    told: list[str] = []
    request = sp.reveal_in_file_manager(tmp_path / "gone")
    request.on_failure(told.append)
    manager.release.set()
    assert request.wait(WAIT)
    assert request.reason == "FileNotFoundError: no such folder"
    assert told == ["FileNotFoundError: no such folder"]
    late: list[str] = []
    request.on_failure(late.append)
    assert late == ["FileNotFoundError: no such folder"], "a listener that arrives after the answer is still told"
    assert told == ["FileNotFoundError: no such folder"], "and the first is not told twice"


def test_a_folder_that_was_shown_tells_nobody(manager, tmp_path):
    told: list[str] = []
    request = sp.reveal_in_file_manager(tmp_path)
    request.on_failure(told.append)
    manager.release.set()
    assert request.wait(WAIT)
    request.on_failure(told.append)
    assert told == [] and request.reason is None


def test_a_listener_that_raises_does_not_stop_the_requests_behind_it(manager, tmp_path):
    manager.answer = "refused"
    first = sp.reveal_in_file_manager(tmp_path / "a")
    second = sp.reveal_in_file_manager(tmp_path / "b")

    def explode(reason):
        raise RuntimeError("a listener's own defect")

    told: list[str] = []
    first.on_failure(explode)
    second.on_failure(told.append)
    manager.release.set()
    assert first.wait(WAIT) and second.wait(WAIT)
    assert told == ["refused"]
    assert [call[0] for call in manager.calls] == [str(tmp_path / "a"), str(tmp_path / "b")], "in the order asked"


def test_a_folder_already_waiting_is_not_asked_for_twice(manager, tmp_path):
    first = sp.reveal_in_file_manager(tmp_path)
    assert manager.entered.wait(WAIT)
    again = sp.reveal_in_file_manager(tmp_path)
    assert again is first, "the click that asks again gets the request already waiting"
    manager.release.set()
    assert first.wait(WAIT)
    assert len(manager.calls) == 1
    _drained()
    manager.release.set()
    later = sp.reveal_in_file_manager(tmp_path)
    assert later is not first and later.wait(WAIT), "once it has ended, asking again asks again"
    assert len(manager.calls) == 2


def test_a_file_manager_that_stopped_answering_is_not_asked_without_limit(manager, tmp_path):
    waiting = [sp.reveal_in_file_manager(tmp_path / f"folder-{index}") for index in range(sp.REVEAL_LIMIT)]
    assert manager.entered.wait(WAIT)
    before = threading.active_count()
    started = time.monotonic()
    refused = sp.reveal_in_file_manager(tmp_path / "one-too-many")
    assert time.monotonic() - started < 0.5
    assert refused.done and "has not answered" in refused.reason and str(sp.REVEAL_LIMIT) in refused.reason
    assert threading.active_count() == before, "a refused request starts no thread"
    assert len(manager.calls) == 1, "one at a time: the others wait their turn"
    assert sum(1 for thread in threading.enumerate() if thread.name == "reveal-in-file-manager") == 1
    manager.release.set()
    assert all(request.wait(WAIT) and request.reason is None for request in waiting)
    assert [call[0] for call in manager.calls] == [str(tmp_path / f"folder-{index}") for index in range(sp.REVEAL_LIMIT)]


def test_the_thread_is_a_daemon_and_ends_when_nothing_is_waiting(manager, tmp_path):
    request = sp.reveal_in_file_manager(tmp_path)
    assert manager.entered.wait(WAIT)
    thread = sp._reveal_thread
    assert thread is not None and thread.daemon, "closing the application never waits for the file manager"
    manager.release.set()
    assert request.wait(WAIT)
    _drained()
    thread.join(WAIT)
    assert not thread.is_alive() and sp._reveal_thread is None and not sp._reveal_queue


def test_a_replaced_thread_class_cannot_strand_a_request(manager, tmp_path, monkeypatch):
    """The suite's own stubs replace ``threading.Thread`` for whole tests. The helper keeps the class it loaded with."""

    class NeverRuns:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(threading, "Thread", NeverRuns)
    request = sp.reveal_in_file_manager(tmp_path)
    assert manager.entered.wait(WAIT), "the request was really made"
    manager.release.set()
    assert request.wait(WAIT)


def test_windows_asks_through_startfile_and_reports_its_refusal(monkeypatch, tmp_path):
    opened: list[str] = []
    monkeypatch.setattr(sp.os, "startfile", lambda target: opened.append(target), raising=False)
    assert sp._ask_file_manager(str(tmp_path), platform="win32") is None
    assert opened == [str(tmp_path)]

    def refuse(target):
        raise FileNotFoundError(2, "The system cannot find the file specified", target)

    monkeypatch.setattr(sp.os, "startfile", refuse, raising=False)
    reason = sp._ask_file_manager(str(tmp_path / "gone"), platform="win32")
    assert reason is not None and reason.startswith("FileNotFoundError") and "gone" in reason


@pytest.mark.parametrize("platform, opener", [("darwin", "open"), ("linux", "xdg-open")])
def test_the_other_platforms_openers_are_waited_for_briefly_and_reaped(monkeypatch, tmp_path, platform, opener):
    class Child:
        def __init__(self, code):
            self.code, self.waited = code, []

        def wait(self, timeout=None):
            self.waited.append(timeout)
            if self.code is None:
                raise sp.subprocess.TimeoutExpired(opener, timeout)
            return self.code

    started: list = []

    def popen(cmd, **kwargs):
        child = Child(outcomes.pop(0))
        started.append((cmd, child))
        return child

    monkeypatch.setattr(sp, "popen", popen)
    outcomes = [0, 3, None]
    assert sp._ask_file_manager(str(tmp_path), platform=platform) is None
    assert sp._ask_file_manager(str(tmp_path), platform=platform) == f"{opener} ended with code 3"
    assert sp._ask_file_manager(str(tmp_path), platform=platform) is None, "still working: the system's to finish"
    assert [cmd for cmd, _child in started] == [[opener, str(tmp_path)]] * 3
    assert all(child.waited == [sp.REVEAL_OPENER_SECONDS] for _cmd, child in started), "each one is waited for, once"


def test_the_application_reaches_the_operating_system_call_in_one_place():
    """``os.startfile`` appears in the shared helper's one function. The first-run setup window keeps its own, older
    "Open log folder" call in ``bootstrap.py`` (it must work before the environment exists); nothing else may add one,
    or a window could wait on the file manager again without this module noticing."""
    users: dict[str, list[str]] = {}
    for path in source_probe.application_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.Attribute) and node.attr == "startfile":
                    users.setdefault(path.name, []).append(function.name)
    assert {name: sorted(set(found)) for name, found in users.items()} == {
        "subprocess_utils.py": ["_ask_file_manager"], "bootstrap.py": ["_open_folder"]}


# --------------------------------------------------------------------------- #
# The real Converter panel in the real Tk loop
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture(scope="module")
def book(tmp_path_factory) -> Path:
    require_ffmpeg()
    return make_book(tmp_path_factory.mktemp("reveal_media"), "Reveal", cover=False, lengths=(1500, 1300))


class _Silent:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class Loop:
    """Turns the real Tk loop from the test and remembers when each turn ended."""

    def __init__(self, root) -> None:
        self.root = root
        self.turns: list[float] = [time.perf_counter()]

    def until(self, done, seconds: float = WAIT) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root.update()
            self.turns.append(time.perf_counter())
            if done():
                return True
            time.sleep(0.005)
        return False

    def longest_gap_since(self, moment: float) -> float:
        kept = [turn for turn in self.turns if turn >= moment]
        return max((later - earlier for earlier, later in zip(kept, kept[1:])), default=0.0)


@pytest.fixture()
def running(tk_root, tmp_path, book):
    """The real panel with its real worker thread and pump. Only where the run folder goes is given to it."""
    made: list = []

    def build():
        panel = m4b_converter.M4BConverterUI(
            tk_root, effective_config=make_config(), home=None, choose_files=lambda: (str(book),),
            choose_folder=lambda: (), confirm_broad_root=lambda roots: False,
            confirm_large_result=lambda outcome: True, bridge=jc.LoggerBridge(logger=_Silent()))
        made.append(panel)
        loop = Loop(tk_root)
        panel.importer.add_files()
        assert loop.until(lambda: len(panel._manager.snapshot().files) == 1), "the book was not imported"
        return panel, loop

    with mock.patch.object(output_paths, "reserve_run_directory", side_effect=_reservation(tmp_path)):
        yield build
    for panel in made:
        panel.close()
        panel.destroy()


def _run_to_its_end(panel, loop: Loop) -> float:
    panel.start_convert()
    assert loop.until(lambda: panel.run_result is not None and not panel._busy.is_set(), 120), "the run did not end"
    return time.perf_counter()


def test_a_busy_file_manager_does_not_hold_the_converter_window(running, manager, tmp_path, book):
    panel, loop = running()
    source = book.read_bytes()
    _run_to_its_end(panel, loop)
    assert loop.until(manager.entered.is_set), "the finished run never asked for its folder"
    asked = time.perf_counter()

    # The file manager is busy from here until the test lets go. The window must go on turning the whole time.
    assert loop.until(lambda: time.perf_counter() - asked >= 2.0)
    assert not manager.release.is_set() and manager.calls == [(str(panel.run_plan.run_directory), False)], \
        "asked once, for the run's own folder, and not by the window's thread"
    gap = loop.longest_gap_since(asked)
    assert gap < LOOP_LIMIT_SECONDS, f"the Tk loop stopped for {gap:.2f} s while the file manager was busy"

    # Terminal reporting did not wait for it either: the run is settled, said so, and the controls are back.
    assert panel.run_result.state is jc.JobState.SUCCEEDED
    assert list(panel.log.summary)[-1].startswith("All done. Output:")
    assert str(panel.btn_convert.cget("state")) != "disabled", "Convert is available again"
    produced = sorted(path.name for path in panel.run_plan.run_directory.rglob("*.mp3"))
    assert produced == ["Reveal.mp3"] and book.read_bytes() == source

    # Nor does a second run: it starts, finishes and reports while the first folder is still waiting.
    _run_to_its_end(panel, loop)
    assert panel.run_result.state is jc.JobState.SUCCEEDED and len(manager.calls) == 1
    assert loop.longest_gap_since(asked) < LOOP_LIMIT_SECONDS

    # And closing does not wait for it.
    closing = time.perf_counter()
    panel.close()
    assert time.perf_counter() - closing < 2.0, "closing waited for the file manager"
    assert not manager.release.is_set()


def test_the_measurement_sees_a_request_made_by_the_windows_own_thread(running, manager, monkeypatch):
    """The negative control: the old behaviour, restored for this test only, must be seen as a stopped loop."""
    manager.hold = 1.5   # a stopped loop could release nothing, so the stand-in lets go by itself
    monkeypatch.setattr(m4b_converter.sp, "reveal_in_file_manager", lambda folder: sp._ask_file_manager(str(folder)))
    panel, loop = running()
    panel.start_convert()
    began = time.perf_counter()
    assert loop.until(lambda: panel.run_result is not None and not panel._busy.is_set() and bool(manager.calls), 120)
    assert manager.calls == [(str(panel.run_plan.run_directory), True)], \
        "this arm asks on the window's thread, as the application used to"
    gap = loop.longest_gap_since(began)
    assert gap >= manager.hold, f"the instrument saw only {gap:.2f} s of a {manager.hold} s hold on the Tk thread"
    assert gap >= 3 * LOOP_LIMIT_SECONDS, "and the limit the real test applies would have caught it"


def test_a_folder_that_cannot_be_opened_is_said_in_the_log_and_the_run_still_succeeded(running, manager):
    manager.answer = "OSError: [WinError 1223] The operation was canceled by the user"
    manager.release.set()
    panel, loop = running()
    _run_to_its_end(panel, loop)
    folder = str(panel.run_plan.run_directory)
    said = "The folder could not be opened in the file manager"
    assert loop.until(lambda: any(said in line for line in panel.log.summary)), "the failure never reached the log"
    line = next(line for line in panel.log.summary if said in line)
    assert "WinError 1223" in line and folder in line, line
    assert any(said in line for line in panel.log.details), "and in the detailed log"
    assert panel.run_result.state is jc.JobState.SUCCEEDED, "a conversion that succeeded has still succeeded"
    assert panel.run_result.failed_count == 0
    assert sorted(path.name for path in panel.run_plan.run_directory.rglob("*.mp3")) == ["Reveal.mp3"]
    assert str(panel.btn_convert.cget("state")) != "disabled"


def test_open_output_folder_does_not_wait_for_the_file_manager_either(running, manager):
    panel, loop = running()
    _run_to_its_end(panel, loop)
    assert loop.until(manager.entered.is_set)
    started = time.perf_counter()
    panel.open_outdir()
    assert time.perf_counter() - started < 0.5, "the button waited for the file manager"
    assert len(manager.calls) == 1, "the run's folder is already waiting, so it is not asked for again"


def test_the_failure_reporter_holds_the_queue_and_never_the_panel():
    """Whatever the helper's thread holds last is released on that thread, and a Tk object released there ends the
    program. So the listener may close over the queue and a string, and nothing else."""
    import queue

    log_q: queue.Queue = queue.Queue()
    report = m4b_converter._reveal_failure_reporter(log_q, "C:/out/run-1")
    held = [cell.cell_contents for cell in report.__closure__]
    assert sorted(type(item).__name__ for item in held) == ["Queue", "str"], held
    report("refused")
    kind, text = log_q.get_nowait()
    assert kind == m4b_converter.REVEAL_FAILED_MESSAGE and "refused" in text and "C:/out/run-1" in text
