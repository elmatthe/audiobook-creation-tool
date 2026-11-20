"""v0.8.x P1B -- the app window's containment, end to end (plan sections 11.2.2 and 11.2.3).

The REAL launcher (``launcher.main()``) runs in a separate process through ``macos_gui_driver.py``, isolated from the
real settings, logs and runtime data, and starts its work through the production spawn paths. Then it is ended the way
each KX case says, and every ACT-owned descendant is checked by pid AND kernel start time, and its process group by
``killpg(pgid, 0)``; nothing is found or ended by name:

* KX-1(d): ``kill -9`` of the window during an FFmpeg step (the adopted FFmpeg, through ``run_supervised``).
* KX-1(e): ``kill -9`` during an optional-setup install: a stand-in worker started through the production setup
  spawn, running a stand-in pip (which starts a long-running child, as pip starts a build backend) through the
  production ``qwen3_setup.run_command``. The real pip and the real worker's acquisition are P2's (Kokoro); what this
  proves is the route: the worker is class A of the window and the pip is class A of the worker.
* KX-2(d): ``kill -SEGV`` and ``kill -ABRT`` (a simulated crash) during an FFmpeg step. macOS writes a crash report
  for each (``~/Library/Logs/DiagnosticReports``); the test does not touch them.
* KX-3(d): SIGTERM (Activity Monitor's Quit), the application menu's Quit / Cmd+Q (``::tk::mac::Quit``, the command
  the menu and the key call) and the red button (``WM_DELETE_WINDOW``) during an FFmpeg step: the orderly path
  completes within 5 s, the last tool is remembered, nothing is left.
* KX-6: the guardian killed by hand during a step: that step is stopped (fail closed) and recorded, the next step gets
  a new guardian, and ``kill -9`` of the window then ends it.
* KX-7 (negative controls): the same ``kill -9`` with the window's containment taken away, and the setup route with an
  owner that gives no lifeline -- the orphans ARE seen, so these tests can fail. They are then ended by identity.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shared import child_ownership, ffmpeg_utils

NATIVE_P1B = "native macOS only (P1B): Aqua Tk 9 shell, POSIX containment and macOS filesystem checks"
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason=NATIVE_P1B)

HERE = Path(__file__).resolve().parent
DRIVER = HERE / "macos_gui_driver.py"
ORPHAN_BOUND_S = 3.0
ORDERLY_BOUND_S = 5.0


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _identity(pid) -> tuple[int, tuple[int, int] | None]:
    pid = int(pid)
    return pid, child_ownership.process_start_time(pid)


def _alive(identity) -> bool:
    pid, start = identity
    return start is not None and child_ownership.process_start_time(pid) == start


def _group_empty(pgid: int) -> bool:
    try:
        os.killpg(int(pgid), 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _wait_gone(identities, groups=(), timeout: float = ORPHAN_BOUND_S):
    deadline = time.monotonic() + timeout
    while True:
        alive = [i for i in identities if _alive(i)]
        occupied = [g for g in groups if not _group_empty(g)]
        if (not alive and not occupied) or time.monotonic() >= deadline:
            return alive, occupied
        time.sleep(0.02)


class App:
    """One driver process: the real launcher, isolated."""

    def __init__(self, tmp_path: Path, scenario: str, **options) -> None:
        self.dir = tmp_path
        self.out = tmp_path / "driver.out"
        self.requests = tmp_path / "driver.request"
        self.runtime = tmp_path / "runtime"
        output = tmp_path / "output"
        output.mkdir()
        config = {"out": str(self.out), "requests": str(self.requests), "runtime": str(self.runtime),
                  "output": str(output), "scenario": scenario, **options}
        path = tmp_path / "driver.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        self.stderr = open(tmp_path / "driver.stderr", "wb")
        # Its own session, so no signal meant for it can reach the test run, and the negative control's orphan is
        # never in pytest's own group.
        self.proc = subprocess.Popen([sys.executable, str(DRIVER), str(path)], stdin=subprocess.DEVNULL,
                                     stdout=self.stderr, stderr=self.stderr, start_new_session=True)
        self.identity = _identity(self.proc.pid)
        self.leftovers: list = []

    def lines(self) -> list[list[str]]:
        if not self.out.exists():
            return []
        return [line.split() for line in self.out.read_text(encoding="utf-8").splitlines() if line.strip()]

    def wait_for(self, word: str, *values: str, timeout: float = 60.0) -> list[str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for words in self.lines():
                if words[0] == word and tuple(words[1:1 + len(values)]) == values:
                    return words
            if self.proc.poll() is not None:
                break
            time.sleep(0.02)
        raise AssertionError(f"{word} {values} never came (driver exit {self.proc.poll()}):\n"
                             f"{self.out.read_text() if self.out.exists() else '(no output)'}\n{self.stderr_text()}")

    def stderr_text(self) -> str:
        self.stderr.flush()
        return (self.dir / "driver.stderr").read_text(encoding="utf-8", errors="replace")[-4000:]

    def ask(self, request: str) -> float:
        self.requests.write_text(request, encoding="utf-8")
        return time.monotonic()

    def log_text(self) -> str:
        logs = self.runtime / "logs"
        return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(logs.glob("*.log")))

    def settings(self) -> dict:
        return json.loads((self.runtime / "settings.json").read_text(encoding="utf-8"))

    def close(self) -> None:
        if self.proc.poll() is None and _alive(self.identity):
            child_ownership.signal_if_same(self.proc.pid, self.identity[1], signal.SIGKILL)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            pass
        for identity in self.leftovers:
            child_ownership.signal_if_same(identity[0], identity[1], signal.SIGKILL)
        self.stderr.close()


@pytest.fixture
def app_factory(tmp_path):
    made: list[App] = []

    def make(scenario: str, **options) -> App:
        if scenario != "setup" and not ffmpeg_utils.ffmpeg_path():
            pytest.fail("the adopted FFmpeg is not pinned in this checkout; set the app up before P1B's KX tests")
        folder = tmp_path / f"app{len(made)}"
        folder.mkdir()
        app = App(folder, scenario, **options)
        made.append(app)
        return app

    yield make
    for app in made:
        app.close()


def _ffmpeg_step(app: App):
    gui = app.wait_for("GUI")
    assert gui[3:5] == ["owner", "True"], gui
    _, _, pid, group = app.wait_for("FFMPEG", "1")
    ffmpeg = _identity(pid)
    guardian = _identity(group)
    assert ffmpeg[1] is not None and guardian[1] is not None
    assert os.getpgid(ffmpeg[0]) == guardian[0], "the FFmpeg is in the guardian's group"
    assert os.getpgid(guardian[0]) == guardian[0] != os.getpgid(app.proc.pid), "the guardian leads its own group"
    app.leftovers += [ffmpeg, guardian]
    return ffmpeg, guardian


def _ended_by_signal(app: App, sig: int) -> float:
    os.kill(app.proc.pid, sig)
    app.proc.wait(timeout=30)
    return time.monotonic()


# --------------------------------------------------------------------------- #
#  KX-1(d), KX-2(d): the window killed or crashed during an FFmpeg step
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sig", [getattr(signal, "SIGKILL", None), signal.SIGSEGV, signal.SIGABRT], ids=["KX-1d-SIGKILL",
                                                                                       "KX-2d-SIGSEGV",
                                                                                       "KX-2d-SIGABRT"])
def test_kx1d_kx2d_the_window_ends_abnormally_during_an_ffmpeg_step(app_factory, sig):
    app = app_factory("ffmpeg")
    ffmpeg, guardian = _ffmpeg_step(app)
    time.sleep(0.5)  # FFmpeg is well into its step
    _ended_by_signal(app, sig)
    assert app.proc.returncode == -sig, f"the window ended by {signal.Signals(sig).name}: {app.stderr_text()}"
    alive, occupied = _wait_gone([ffmpeg, guardian], [guardian[0]])
    assert (alive, occupied) == ([], []), f"orphans after {signal.Signals(sig).name}: {alive} groups {occupied}"
    assert "MAIN_RETURNED" not in app.out.read_text(), "no orderly code ran: this is the lifeline's work alone"


# --------------------------------------------------------------------------- #
#  KX-1(e): the window killed during an optional-setup install
# --------------------------------------------------------------------------- #
def _setup_tree(app: App):
    _, worker_pid, worker_group = app.wait_for("SETUP")
    words = app.wait_for("WORKER")
    assert words[1] == worker_pid and words[2] == worker_group == worker_pid, "the worker leads its own group"
    _, _, pip_pid, backend_pid = app.wait_for("PIP", "PIDS")
    worker, pip, backend = _identity(worker_pid), _identity(pip_pid), _identity(backend_pid)
    app.leftovers += [worker, pip, backend]
    return worker, pip, backend, words[3] == "True"


def test_kx1e_the_window_killed_during_an_optional_setup_install_takes_worker_pip_and_backend(app_factory):
    app = app_factory("setup")
    worker, pip, backend, worker_has_lifeline = _setup_tree(app)
    assert worker_has_lifeline, "the worker watches the window's lifeline"
    assert os.getpgid(pip[0]) == pip[0] != worker[0], "the pip leads its own group (class A of the worker)"
    assert os.getpgid(backend[0]) == pip[0], "its build backend is in the pip's group"
    _ended_by_signal(app, signal.SIGKILL)
    alive, occupied = _wait_gone([worker, pip, backend], [worker[0], pip[0]])
    assert (alive, occupied) == ([], []), f"orphans: {alive} groups {occupied}"


# --------------------------------------------------------------------------- #
#  KX-3(d): the orderly ends during an FFmpeg step
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("how", ["SIGTERM", "SIGHUP", "SIGINT", "quit", "close"])
def test_kx3d_an_orderly_end_during_an_ffmpeg_step_completes_within_5s(app_factory, how):
    app = app_factory("ffmpeg")
    gui = app.wait_for("GUI")
    if how == "quit" and gui[-1] != "True":
        pytest.fail("the application menu's Quit exists only in the aqua shell; this Mac's Tk is not aqua")
    ffmpeg, guardian = _ffmpeg_step(app)
    time.sleep(0.5)
    began = time.monotonic()
    if how.startswith("SIG"):
        os.kill(app.proc.pid, getattr(signal, how))
    else:
        began = app.ask(how)
    app.proc.wait(timeout=30)
    took = time.monotonic() - began
    assert app.proc.returncode == 0, f"{how}: exit {app.proc.returncode}\n{app.stderr_text()}"
    assert took <= ORDERLY_BOUND_S, f"{how}: the orderly end took {took:.2f} s"
    app.wait_for("MAIN_RETURNED", "0", timeout=1)
    alive, occupied = _wait_gone([ffmpeg, guardian], [guardian[0]], timeout=0.5)
    assert (alive, occupied) == ([], []), f"{how}: left behind {alive} groups {occupied}"
    assert app.settings().get("last_tool") == "mp3_tool", "the close path ran: the last tool was remembered"


def test_kx3_an_orderly_end_during_an_optional_setup_install_ends_the_worker_tree(app_factory):
    app = app_factory("setup")
    worker, pip, backend, _ = _setup_tree(app)
    began = time.monotonic()
    os.kill(app.proc.pid, signal.SIGTERM)
    app.proc.wait(timeout=30)
    assert time.monotonic() - began <= ORDERLY_BOUND_S and app.proc.returncode == 0, app.stderr_text()
    alive, occupied = _wait_gone([worker, pip, backend], [worker[0], pip[0]])
    assert (alive, occupied) == ([], []), f"left behind {alive} groups {occupied}"


# --------------------------------------------------------------------------- #
#  KX-6: the guardian killed by hand
# --------------------------------------------------------------------------- #
def test_kx6_after_the_guardian_is_killed_the_next_step_is_contained(app_factory):
    app = app_factory("guardian-loss")
    first, guardian1 = _ffmpeg_step(app)
    os.kill(guardian1[0], signal.SIGKILL)  # by hand, as a user with Activity Monitor could
    step = app.wait_for("STEP", "1", timeout=10)
    assert step[-1] == "True", "the owner records that it lost its guardian"
    alive, occupied = _wait_gone([first], [guardian1[0]])
    assert (alive, occupied) == ([], []), "the step whose guardian went was stopped (fail closed), nothing left"
    _, _, pid, group = app.wait_for("FFMPEG", "2")
    second, guardian2 = _identity(pid), _identity(group)
    app.leftovers += [second, guardian2]
    assert guardian2[0] != guardian1[0] and os.getpgid(second[0]) == guardian2[0], "a new guardian holds the next step"
    _ended_by_signal(app, signal.SIGKILL)
    alive, occupied = _wait_gone([second, guardian2], [guardian2[0]])
    assert (alive, occupied) == ([], []), f"the step after the restart was not contained: {alive} {occupied}"
    assert "ended on its own" in app.log_text(), "the loss is in the app's log"


# --------------------------------------------------------------------------- #
#  KX-7: negative controls -- the detectors can fail
# --------------------------------------------------------------------------- #
def test_kx7_without_the_windows_containment_the_ffmpeg_orphan_is_seen(app_factory):
    app = app_factory("ffmpeg", contain=False)
    gui = app.wait_for("GUI")
    assert gui[3:5] == ["owner", "False"], gui
    _, _, pid, _ = app.wait_for("FFMPEG", "1")
    ffmpeg = _identity(pid)
    app.leftovers.append(ffmpeg)
    time.sleep(0.5)
    _ended_by_signal(app, signal.SIGKILL)
    alive, _ = _wait_gone([ffmpeg], timeout=ORPHAN_BOUND_S)
    assert alive == [ffmpeg], "with no containment the FFmpeg outlives the window: the detector works"


def test_kx7_without_the_lifeline_the_setup_workers_orphans_are_seen(app_factory):
    app = app_factory("setup", lifeline=False)
    worker, pip, backend, worker_has_lifeline = _setup_tree(app)
    assert not worker_has_lifeline
    _ended_by_signal(app, signal.SIGKILL)
    alive, _ = _wait_gone([worker, pip, backend], timeout=ORPHAN_BOUND_S)
    assert worker in alive, "with no lifeline the worker outlives the window: the detector works"
