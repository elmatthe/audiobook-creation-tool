"""v0.8.x P5-C -- a pip or probe that exits normally is never reaped before its process group has been ended (POSIX).

**Reproduced at ``05ec184``** (``files/dev-work/macos-p5c/repro/before/``, real processes, recorded before any
production change): a pip or engine probe started as a class-A child (its own process group, on its owner's lifeline)
started a helper in that group -- a build backend -- and exited normally. Its caller reaped it straight away
(``qwen3_setup.run_command`` and ``bootstrap._pip`` once its output ended, ``Owner.run_python`` through
``subprocess.run``, the first-run "Stop setup?" through ``poll()``), so the group's id could no longer be proved its own
and nothing ever ended the helper: not the run, not the owner's orderly end (it had forgotten the child, or never
registered it), not the lifeline (only pip held it). The same under the first-run window, the app window's Install &
Continue and the base installation. A helper that inherited pip's output was worse: the caller waited for that output
to end, so it waited as long as the helper ran.

**Now** (``shared.child_ownership``): the caller waits for the LEADER's exit, observed without reaping it, never for
the end of its output alone; it then ends the leader's group the P5-A way (``end_led_group``: under the ``Popen``'s
waitpid lock, unreaped, same kernel start time, signalled until the kernel says nothing is left), hands on the output
already written, and only then reaps the leader (``follow_lines``, ``communicate_led``). A group that could not be
proved the leader's own, or not confirmed ended, is reported as a failure -- never a success. The owner's orderly end
(``Owner.shutdown``) checks and signals a child only under that same lock.

Real, disposable processes throughout. A process is "gone" only when its pid no longer has the kernel start time
recorded while it ran; nothing is found by name or by a scan, and whatever a test leaves is ended by the same identity,
after its assertions. An unrelated process started by each test must survive it.
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from shared import bootstrap, child_ownership as co
from shared import optional_setup_client as client
from shared import optional_setup_protocol as proto
from shared import subprocess_utils
from tts import qwen3_process, qwen3_setup

tk = pytest.importorskip("tkinter")
from tkinter import messagebox  # noqa: E402

from test_first_run_setup_ownership import (  # noqa: E402,F401  (fixtures are collected by name)
    Runs,
    app_copy,
    install_consent,
    outcome_of,
    press,
    pump_until,
)
from test_setup_log_follow import native_theme, run_as_toplevel, setup_log, tk_root  # noqa: E402,F401

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
K = proto.KOKORO
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX normal-exit group retirement (Windows: Job Objects)")
#: Every test: a fresh owner for this process (none left behind) and the setup log in a temporary folder.
pytestmark = pytest.mark.usefixtures("fresh_containment_owner", "setup_log")
#: How long after pip's normal exit its caller may take to have ended the helper and returned. The follower looks every
#: 0.1 s and ending a group takes milliseconds; before P5-C a helper holding the output kept the caller waiting for as
#: long as the helper ran (300 s here).
PROMPT_S = 5.0
#: How long a process its group's end has already killed may take to finish exiting. A helper that was never ended
#: sleeps 300 s, so this cannot mistake one for gone.
EXIT_S = 2.0
#: The real ``qwen3_setup.run_command``: the suite's guard (conftest ``_no_real_qwen3_install``) replaces the module
#: attribute for every test, and these tests run only the stand-in "pip" through it (as test_spacy_consumer does).
NATIVE_RUN = qwen3_setup.run_command

# --------------------------------------------------------------------------- #
#  The "pip" (or engine probe) and its helper
# --------------------------------------------------------------------------- #
#: argv: <its folder> <output: devnull|pipe> <exit status; negative: killed by that signal> [hold]
#: Starts a helper in its own process group (a build backend) and records it, prints a line, records itself (so its own
#: record means both exist), waits for the test's ``go`` barrier -- or, with ``hold``, runs on -- prints its last line
#: and exits normally with the status it was given. The helper's output goes to /dev/null or (``pipe``) to pip's own
#: stdout and stderr, as a backend that prints does.
PIP = r'''
import json, os, subprocess, sys, time
from pathlib import Path
ev, output, code = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
hold = len(sys.argv) > 4 and sys.argv[4] == "hold"
def note(name):
    (ev / (name + ".new")).write_text(json.dumps({"pid": os.getpid(), "pgid": os.getpgrp()}))
    os.replace(ev / (name + ".new"), ev / (name + ".json"))
HELPER = ("import json, os, sys, time; from pathlib import Path; ev = Path(sys.argv[1]); "
          "(ev / 'helper.new').write_text(json.dumps({'pid': os.getpid(), 'pgid': os.getpgrp()})); "
          "os.replace(ev / 'helper.new', ev / 'helper.json'); print('helper: building', flush=True); time.sleep(300)")
sink = None if output == "pipe" else subprocess.DEVNULL
subprocess.Popen([sys.executable, "-c", HELPER, str(ev)], stdout=sink, stderr=sink)
deadline = time.monotonic() + 30
while not (ev / "helper.json").exists() and time.monotonic() < deadline:
    time.sleep(0.01)
print("Collecting example==1.0", flush=True)
note("pip")
deadline = time.monotonic() + 60
while (hold or not (ev / "go").exists()) and time.monotonic() < deadline:
    time.sleep(0.01)
print("Successfully installed example-1.0", flush=True)
if code < 0:
    os.kill(os.getpid(), -code)
sys.exit(code)
'''
LAST_LINE = "Successfully installed example-1.0"


class Scene:
    """One pip (or probe) and its helper, in a folder of their own: their identities, recorded while both run."""

    def __init__(self, folder: Path):
        self.ev = folder
        self.ev.mkdir(parents=True, exist_ok=True)
        self.ids: dict = {}

    def argv(self, output: str = "devnull", code: int = 0, *extra: str) -> list:
        return [sys.executable, "-c", PIP, str(self.ev), output, str(code), *extra]

    def started(self, bound: float = 30.0) -> dict:
        """Wait for pip's own record (written after its helper's), then record both identities while both run."""
        deadline = time.monotonic() + bound
        while not (self.ev / "pip.json").exists():
            assert time.monotonic() < deadline, "the stand-in pip never started"
            time.sleep(0.01)
        for name in ("pip", "helper"):
            pid = json.loads((self.ev / f"{name}.json").read_text())["pid"]
            self.ids[name] = (pid, co.process_start_time(pid))
            assert self.ids[name][1] is not None, f"{name} was already gone when it was recorded"
        return self.ids

    def go(self) -> None:
        (self.ev / "go").write_text("go")

    def alive(self, name: str) -> bool:
        return same(self.ids[name])

    def gone(self, name: str, bound: float = EXIT_S) -> bool:
        """True once *name* is no longer running, waiting at most *bound* s for an exit already under way (a process
        SIGKILLed a moment ago, which the kernel no longer counts as signallable). Nothing is signalled here."""
        deadline = time.monotonic() + bound
        while self.alive(name):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)
        return True

    def end_left(self) -> None:
        """The test's own clean-up, AFTER its assertions: by pid and start time, never by name."""
        for identity in self.ids.values():
            co.signal_if_same(*identity, signal.SIGKILL)


@pytest.fixture
def scene(tmp_path):
    made = Scene(tmp_path / "pip")
    yield made
    made.end_left()


@pytest.fixture
def group_rule_only(monkeypatch):
    """v0.8.x P5-I-R3: these tests prove the P5-A group rule -- an owner signals a group only while its id is proved
    the leader's own. Since remediation 2 the guardian also ends, once its owner is gone, every descendant carrying the
    owner's child token (a separate identity proof), which would end the helper these tests watch survive. Here the
    guardian is given no token, so what is observed is the group rule alone."""
    monkeypatch.setattr(co, "SWEEP_TOKEN_ENV", "ACT_SWEEP_TOKEN_NOT_GIVEN")


@pytest.fixture
def sentinel():
    """An unrelated process of this account, in a session of its own: no test may touch it."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    identity = (proc.pid, co.process_start_time(proc.pid))
    yield identity
    co.signal_if_same(*identity, signal.SIGKILL)
    proc.wait(10)


def same(identity) -> bool:
    """Still that very process, and still running: same pid, same kernel start time, and not a zombie (a helper ended
    after pip has gone is reaped by launchd a moment later, and until then the kernel still lists it)."""
    pid, start = identity
    if start is None or co.process_start_time(pid) != tuple(start):
        return False
    return not (sys.platform == "darwin" and co._has_exited(pid))


def in_thread(fn) -> dict:
    """Run *fn* on a daemon thread; the box gets ``value`` or ``error``, and ``done`` (monotonic) once it returns."""
    box: dict = {}

    def go():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - judged by the test
            box["error"] = exc
        box["done"] = time.monotonic()

    box["thread"] = threading.Thread(target=go, daemon=True)
    box["thread"].start()
    return box


def let_go_and_wait(scene: Scene, box: dict, bound: float = PROMPT_S) -> float:
    """Release pip (it exits normally) and wait at most *bound* s for the call to return. Seconds it took."""
    released = time.monotonic()
    scene.go()
    box["thread"].join(bound)
    assert not box["thread"].is_alive(), \
        f"the caller was still waiting {bound:.0f} s after pip exited normally (its helper is still running)"
    return box["done"] - released


def leader(owner: co.Owner, scene: Scene, output: str = "devnull", code: int = 0, *extra: str):
    """A registered class-A pip with its output on a pipe, as setup and the worker start it; and its start time."""
    proc = owner.popen_python(scene.argv(output, code, *extra), label="pip", stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
    return proc, owner.child(proc).start_time


def reaped_behind_its_back(owner: co.Owner, monkeypatch, scene: Scene):
    """Make *owner*'s next class-A child one that is reaped behind its caller's back, and return the line callback
    that does it: handed pip's first line, it waits for the test to release pip, then for pip's exit, and reaps it
    through its ``Popen`` -- while the caller is inside that callback, so deterministically before the caller looks at
    pip again."""
    held: dict = {}
    real = owner.popen_python

    def started(argv, **kwargs):
        held["proc"] = real(argv, **kwargs)
        return held["proc"]

    def on_line(line: str) -> None:
        if "Collecting example==1.0" in line and "proc" in held:
            deadline = time.monotonic() + 30
            while not (scene.ev / "go").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            held["proc"].wait(timeout=30)

    monkeypatch.setattr(owner, "popen_python", started)
    return on_line


def unconfirmed(answer: str):
    """An ``end_led_group`` that really ends the group but answers *answer*: only the reporting is under test."""
    real = co.end_led_group

    def end(proc, start_time, **kwargs):
        real(proc, start_time, **kwargs)
        return answer

    return end


# --------------------------------------------------------------------------- #
#  The mechanism: follow a leader to its exit, end its group, hand on its output, reap it last
# --------------------------------------------------------------------------- #
@POSIX_ONLY
@pytest.mark.parametrize("output", ["devnull", "pipe"])
def test_a_leader_that_exits_normally_is_reaped_only_after_its_group_and_helper_have_ended(output, scene, sentinel):
    owner = co.Owner()
    try:
        proc, start = leader(owner, scene, output)
        scene.started()
        assert scene.alive("pip") and scene.alive("helper")
        lines: list = []
        box = in_thread(lambda: co.follow_lines(proc, start, lambda line: lines.append(line.rstrip("\n"))))
        let_go_and_wait(scene, box)
        retired = box["value"]
        assert (retired.group, retired.returncode, retired.problem()) == (co.GROUP_ENDED, 0, None)
        assert proc.returncode == 0
        assert scene.gone("helper") and scene.gone("pip")
        assert "Collecting example==1.0" in lines and lines[-1] == LAST_LINE, "everything pip wrote is handed on"
        assert ("helper: building" in lines) == (output == "pipe")
        assert same(sentinel)
    finally:
        owner.shutdown()


@POSIX_ONLY
def test_a_stop_ends_the_running_leader_and_its_group_at_once(scene, sentinel):
    owner = co.Owner()
    try:
        proc, start = leader(owner, scene, "pipe", 0, "hold")
        scene.started()
        asked = time.monotonic()
        retired = co.follow_lines(proc, start, lambda line: None, stop=lambda: True)
        assert time.monotonic() - asked < 2.0, "a stop waits for no exit, no output and no grace"
        assert retired.stopped and retired.group == co.GROUP_ENDED and retired.problem() is None
        assert proc.returncode == -signal.SIGKILL
        assert scene.gone("pip") and scene.gone("helper")
        assert same(sentinel)
    finally:
        owner.shutdown()


@POSIX_ONLY
def test_a_leader_already_reaped_is_never_signalled_and_is_reported(scene, sentinel):
    """Its id may already be someone else's: nothing is signalled, and the answer is a failure, not a success."""
    owner = co.Owner()
    try:
        proc, start = leader(owner, scene, "devnull")
        scene.started()
        scene.go()
        proc.wait(timeout=30)  # reaped through its own Popen, before the follower looks
        retired = co.follow_lines(proc, start, lambda line: None)
        assert retired.group == co.GROUP_UNPROVED and "could not be proved" in retired.problem()
        assert not scene.gone("helper", bound=1.0), \
            "nothing was signalled: the group's id could no longer be proved pip's own"
        assert same(sentinel)
    finally:
        scene.end_left()
        owner.shutdown()


@POSIX_ONLY
@pytest.mark.parametrize("answer, words", [(co.GROUP_REMAINING, "had not ended in time"),
                                          (co.GROUP_SIGNALLED, "cannot confirm")])
def test_a_group_end_that_was_not_confirmed_is_reported_never_a_success(answer, words, monkeypatch, scene, sentinel):
    monkeypatch.setattr(co, "end_led_group", unconfirmed(answer))
    owner = co.Owner()
    try:
        proc, start = leader(owner, scene, "devnull")
        scene.started()
        scene.go()
        retired = co.follow_lines(proc, start, lambda line: None)
        assert retired.returncode == 0 and retired.group == answer and words in retired.problem()
        assert scene.gone("helper")
        assert same(sentinel)
    finally:
        owner.shutdown()


# --------------------------------------------------------------------------- #
#  The base installation's probes, proofs, ``-m venv`` and offline pip: ``_child_run`` -> ``Owner.run_python``
# --------------------------------------------------------------------------- #
@POSIX_ONLY
@pytest.mark.parametrize("output", ["devnull", "pipe"])
def test_a_base_install_probe_that_exits_normally_leaves_no_helper_and_never_waits_on_its_pipe(
        output, scene, sentinel):
    box = in_thread(lambda: bootstrap._child_run(scene.argv(output), capture_output=True, text=True))
    scene.started()
    assert scene.alive("helper")
    let_go_and_wait(scene, box)
    result = box.get("value")
    assert result is not None, box.get("error")
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert "Collecting example==1.0" in lines and lines[-1] == LAST_LINE
    assert ("helper: building" in result.stdout) == (output == "pipe")
    assert scene.gone("helper") and scene.gone("pip")
    assert all(c.pid != scene.ids["pip"][0] for c in bootstrap._owner().children()), "forgotten once reaped"
    assert same(sentinel)


@POSIX_ONLY
def test_a_probe_past_its_timeout_is_ended_with_its_whole_group_and_times_out_as_subprocess_run_does(scene, sentinel):
    started = time.monotonic()
    box = in_thread(lambda: bootstrap._child_run(scene.argv("pipe", 0, "hold"), capture_output=True, text=True,
                                                 timeout=3))
    scene.started()
    box["thread"].join(3 + PROMPT_S)
    assert not box["thread"].is_alive()
    assert isinstance(box.get("error"), subprocess.TimeoutExpired) and box["error"].timeout == 3
    assert 3.0 <= box["done"] - started < 3.0 + PROMPT_S
    assert scene.gone("pip") and scene.gone("helper"), "the timeout ends the probe's whole group"
    assert same(sentinel)


@POSIX_ONLY
@pytest.mark.parametrize("code", [3, -int(signal.SIGABRT)], ids=["fails", "crashes"])
def test_a_failing_or_crashing_probe_keeps_its_status_and_leaves_no_descendant(code, scene, sentinel):
    box = in_thread(lambda: bootstrap._child_run(scene.argv("pipe", code), capture_output=True, text=True))
    scene.started()
    let_go_and_wait(scene, box)
    assert box["value"].returncode == code
    assert scene.gone("helper") and scene.gone("pip")
    assert same(sentinel)


@POSIX_ONLY
def test_run_python_keeps_subprocess_runs_arguments_and_results():
    echo = [sys.executable, "-c", "import sys; data = sys.stdin.read(); print(data.upper(), end=''); "
                                  "print('err', file=sys.stderr, end='')"]
    text = bootstrap._child_run(echo, input="abc\r\ndef", capture_output=True, text=True)
    assert (text.returncode, text.stdout, text.stderr) == (0, "ABC\nDEF", "err"), "text mode: universal newlines"
    assert text.args[0] == sys.executable and text.args[1] == str(co.ENTRY), "still started through child_entry"
    raw = bootstrap._child_run(echo, input=b"abc", capture_output=True)
    assert (raw.stdout, raw.stderr) == (b"ABC", b"err")
    quiet = bootstrap._child_run([sys.executable, "-c", "print('x')"], stdout=subprocess.DEVNULL)
    assert (quiet.returncode, quiet.stdout, quiet.stderr) == (0, None, None)
    both = "import sys; print('a', flush=True); print('b', file=sys.stderr)"
    merged = bootstrap._child_run([sys.executable, "-c", both], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True)
    assert merged.stdout.split() == ["a", "b"] and merged.stderr is None
    with pytest.raises(subprocess.CalledProcessError) as raised:
        bootstrap._child_run([sys.executable, "-c", "import sys; print('out'); sys.exit(4)"], capture_output=True,
                             text=True, check=True)
    assert (raised.value.returncode, raised.value.output, raised.value.stderr) == (4, "out\n", "")
    with pytest.raises(ValueError):
        bootstrap._child_run(echo, input="x", stdin=subprocess.DEVNULL)
    with pytest.raises(ValueError):
        bootstrap._child_run(echo, capture_output=True, stdout=subprocess.PIPE)
    assert bootstrap._owner().children() == [], "every probe was forgotten once reaped"


@POSIX_ONLY
def test_a_probe_whose_group_end_was_not_confirmed_is_never_a_success(monkeypatch, scene, sentinel):
    monkeypatch.setattr(co, "end_led_group", unconfirmed(co.GROUP_REMAINING))
    box = in_thread(lambda: bootstrap._child_run(scene.argv("devnull"), capture_output=True, text=True))
    scene.started()
    let_go_and_wait(scene, box)
    result = box["value"]
    assert result.returncode == co.UNCONFIRMED_RETURNCODE != 0, "the probe exited 0, but its group was not confirmed"
    assert "could not be confirmed ended" in result.stderr and "had not ended in time" in result.stderr
    assert any("could not be confirmed ended" in e for e in bootstrap._owner().events), "and setup's log says so"
    with pytest.raises(subprocess.CalledProcessError):
        bootstrap._child_run([sys.executable, "-c", "pass"], capture_output=True, check=True)
    assert same(sentinel)


# --------------------------------------------------------------------------- #
#  The base installation's pip: ``bootstrap._pip`` and the first-run "Stop setup?"
# --------------------------------------------------------------------------- #
@pytest.fixture
def no_stop(monkeypatch):
    monkeypatch.setattr(bootstrap, "_SETUP_STOP", threading.Event())


@POSIX_ONLY
@pytest.mark.parametrize("output", ["devnull", "pipe"])
def test_the_base_installs_pip_that_exits_normally_leaves_no_helper_and_never_waits_on_its_pipe(
        output, no_stop, scene, sentinel):
    logged: list = []
    box = in_thread(lambda: bootstrap._pip(scene.argv(output), dict(os.environ), logged.append))
    scene.started()
    assert scene.alive("helper")
    let_go_and_wait(scene, box)
    assert box.get("value") == 0, (box.get("error"), logged)
    assert "  Collecting example==1.0" in logged and logged[-1] == "  " + LAST_LINE
    assert scene.gone("helper") and scene.gone("pip")
    assert bootstrap._RUNNING_PIP is None and bootstrap._owner().children() == []
    assert same(sentinel)


@POSIX_ONLY
def test_stop_setup_ends_a_running_pip_and_its_helper_at_once(no_stop, scene, sentinel):
    box = in_thread(lambda: bootstrap._pip(scene.argv("pipe", 0, "hold"), dict(os.environ), lambda line: None))
    scene.started()
    asked = time.monotonic()
    assert bootstrap.request_setup_stop() is True
    box["thread"].join(PROMPT_S)
    assert not box["thread"].is_alive() and box["done"] - asked < 2.0
    assert box["value"] == bootstrap.PIP_STOPPED
    assert scene.gone("pip") and scene.gone("helper")
    assert same(sentinel)


@POSIX_ONLY
def test_stop_setup_never_reaps_a_pip_that_has_exited_and_ends_what_it_left(monkeypatch, no_stop, scene, sentinel):
    """A pip that exited but is not yet reaped still names its group: the stop ends the group and leaves the reap to the
    thread that follows pip. Before P5-C the stop's own ``poll()`` reaped it, and its helper could never be ended."""
    owner = bootstrap._owner()
    proc = owner.popen_python(scene.argv("devnull"), label="pip", stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    start = owner.child(proc).start_time
    monkeypatch.setattr(bootstrap, "_RUNNING_PIP", proc)
    scene.started()
    scene.go()
    assert co.wait_exited(proc, 30, start)
    assert scene.alive("helper")
    assert bootstrap.request_setup_stop() is False, "pip itself was no longer running"
    assert proc.returncode is None, "the stop did not reap it"
    assert scene.gone("helper")
    assert proc.wait(timeout=5) == 0
    assert same(sentinel)


@POSIX_ONLY
def test_the_base_installs_pip_reaped_behind_its_back_fails_and_says_why(monkeypatch, no_stop, scene, sentinel):
    reap = reaped_behind_its_back(bootstrap._owner(), monkeypatch, scene)
    logged: list = []

    def log(line: str) -> None:
        logged.append(line)
        reap(line)

    box = in_thread(lambda: bootstrap._pip(scene.argv("devnull"), dict(os.environ), log))
    scene.started()
    let_go_and_wait(scene, box)
    assert box["value"] == -1, "never 0: nothing could vouch that what pip started has ended"
    assert any("could not be confirmed ended" in line and "could not be proved" in line for line in logged), logged
    assert not scene.gone("helper", bound=1.0), "nothing was signalled"
    assert same(sentinel)


# --------------------------------------------------------------------------- #
#  The setup worker's pip and engine probes: ``qwen3_setup.run_command`` (Kokoro, OmniVoice, Qwen3, spaCy)
# --------------------------------------------------------------------------- #
def run_command(scene: Scene, output: str = "devnull", code: int = 0, *extra: str, cancel=None, on_line=None):
    lines: list = []

    def keep(line: str) -> None:
        lines.append(line)
        if on_line is not None:
            on_line(line)

    box = in_thread(lambda: NATIVE_RUN(scene.argv(output, code, *extra), env=dict(os.environ), cwd=SCRIPTS,
                                       on_line=keep, cancel_check=cancel))
    box["lines"] = lines
    return box


@POSIX_ONLY
@pytest.mark.parametrize("owned", [True, False], ids=["under-an-owner", "own-session"])
@pytest.mark.parametrize("output", ["devnull", "pipe"])
def test_the_workers_pip_that_exits_normally_leaves_no_helper_and_never_waits_on_its_pipe(
        output, owned, scene, sentinel):
    if owned:
        subprocess_utils.enable_containment()  # what a worker under a lifeline (or the app window) is
    box = run_command(scene, output)
    scene.started()
    assert scene.alive("helper")
    let_go_and_wait(scene, box)
    assert box.get("value") == 0, box.get("error")
    assert "Collecting example==1.0" in box["lines"] and box["lines"][-1] == LAST_LINE
    assert scene.gone("helper") and scene.gone("pip")
    owner = subprocess_utils.containment_owner()
    assert owner is None or all(c.pid != scene.ids["pip"][0] for c in owner.children())
    assert same(sentinel)


@POSIX_ONLY
@pytest.mark.parametrize("code", [1, -int(signal.SIGABRT)], ids=["fails", "crashes"])
def test_the_workers_pip_that_fails_or_crashes_keeps_its_status_and_leaves_no_helper(code, scene, sentinel):
    subprocess_utils.enable_containment()
    box = run_command(scene, "pipe", code)
    scene.started()
    let_go_and_wait(scene, box)
    assert box.get("value") == code, box.get("error")
    assert scene.gone("helper") and scene.gone("pip")
    assert same(sentinel)


@POSIX_ONLY
def test_cancel_ends_the_workers_running_pip_and_its_helper_at_once(scene, sentinel):
    subprocess_utils.enable_containment()
    cancel = threading.Event()
    box = run_command(scene, "pipe", 0, "hold", cancel=cancel.is_set)
    scene.started()
    asked = time.monotonic()
    cancel.set()
    box["thread"].join(PROMPT_S)
    assert not box["thread"].is_alive() and box["done"] - asked < 2.0
    assert type(box.get("error")) is qwen3_setup.SetupCancelled
    assert scene.gone("pip") and scene.gone("helper")
    assert same(sentinel)


@POSIX_ONLY
def test_the_workers_pip_reaped_behind_its_back_is_a_setup_error_never_a_success(monkeypatch, scene, sentinel):
    reap = reaped_behind_its_back(subprocess_utils.enable_containment(), monkeypatch, scene)
    box = run_command(scene, "devnull", on_line=reap)
    scene.started()
    let_go_and_wait(scene, box)
    error = box.get("error")
    assert type(error) is qwen3_setup.SetupError, box
    assert "could not be confirmed ended" in str(error) and "could not be proved" in str(error)
    assert not scene.gone("helper", bound=1.0), "nothing was signalled"
    assert same(sentinel)


# --------------------------------------------------------------------------- #
#  The owner's orderly end, and a run that retires its own child at the same moment
# --------------------------------------------------------------------------- #
@POSIX_ONLY
def test_the_orderly_end_ends_what_an_exited_unreaped_leader_left_and_then_reaps_it(scene, sentinel):
    owner = co.Owner()
    proc, start = leader(owner, scene, "devnull")
    scene.started()
    scene.go()
    assert co.wait_exited(proc, 30, start) and scene.alive("helper")
    owner.shutdown()
    assert proc.returncode == 0 and scene.gone("helper")
    assert same(sentinel)


@POSIX_ONLY
def test_the_orderly_end_never_signals_a_leader_reaped_while_it_waited_for_the_lock(scene, sentinel, group_rule_only):
    """``Owner.shutdown`` checks a child's identity and signals it only under the ``Popen``'s waitpid lock. A thread
    that holds that lock and reaps the leader meanwhile (a run settling its own worker) makes the id unprovable, and the
    orderly end must then signal nothing. Before P5-C it checked and signalled without the lock."""
    owner = co.Owner()
    proc, start = leader(owner, scene, "devnull")
    scene.started()
    scene.go()
    assert co.wait_exited(proc, 30, start) and scene.alive("helper")
    lock = proc._waitpid_lock
    assert lock.acquire(timeout=5)
    try:
        ending = in_thread(owner.shutdown)
        time.sleep(0.5)  # the orderly end is now waiting for the lock
        _pid, status = os.waitpid(proc.pid, 0)  # what Popen.wait does under that lock
        proc._handle_exitstatus(status)
    finally:
        lock.release()
    ending["thread"].join(15)
    assert not ending["thread"].is_alive() and "error" not in ending
    assert proc.returncode == 0
    assert not scene.gone("helper", bound=1.0), \
        "the orderly end signalled a group whose leader had been reaped meanwhile"
    assert same(sentinel)


@POSIX_ONLY
def test_the_orderly_end_and_a_runs_own_retirement_never_race_to_signal_or_reap(tmp_path, sentinel):
    """Repeatedly: a child exits normally leaving a helper on its output, while its own follower retires it and the
    owner's orderly end starts at that same moment. Whichever comes first ends the group; neither raises; nothing is
    left."""
    for round_ in range(8):
        scene = Scene(tmp_path / f"round-{round_}")
        owner = co.Owner()
        try:
            proc, start = leader(owner, scene, "pipe")
            scene.started()
            following = in_thread(lambda: co.follow_lines(proc, start, lambda line: None))
            barrier = threading.Barrier(2)
            ending = in_thread(lambda: (barrier.wait(10), owner.shutdown()))
            scene.go()
            assert co.wait_exited(proc, 30, start)
            barrier.wait(10)
            for box in (following, ending):
                box["thread"].join(15)
                assert not box["thread"].is_alive() and "error" not in box, box.get("error")
            assert proc.returncode == 0
            assert scene.gone("helper") and scene.gone("pip"), f"round {round_}"
        finally:
            scene.end_left()
            owner.shutdown()
    assert same(sentinel)


# --------------------------------------------------------------------------- #
#  End to end: the optional-setup worker's pip, under the first-run window and the app window's Install & Continue
# --------------------------------------------------------------------------- #
#: The worker (only its program is a stand-in; WorkerRun, qwen3_process.spawn, run_command and child_ownership are
#: production): runs its "pip" through ``qwen3_setup.run_command``, as the real worker runs pip and the engine probes,
#: records what that gave, and publishes its one result -- the success the request asks for, or, when run_command
#: raised ``SetupError``, a failure carrying its message (as ``optional_setup_acquire`` reports one).
#: behaviour: ``<devnull|pipe>[+reaped]``; ``reaped``: pip is reaped behind run_command's back -- by run_command's own
#: line callback, handed pip's first line, once the test has released pip and pip has exited.
WORKER = r'''
import json, os, sys, time
from pathlib import Path
from shared import optional_setup_protocol as proto
from shared import subprocess_utils
from tts import qwen3_setup
ev, how, request_path, result_path = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
request = json.loads(request_path.read_text())
rid, tag = request["request_id"], request["action"]
output, _, reaped = how.partition("+")
folder = ev / (tag + "-pip")
folder.mkdir(parents=True, exist_ok=True)
env = {k: v for k, v in os.environ.items() if k != "ACT_LIFELINE_FD"}
held = {}
def on_line(line):
    if reaped and "Collecting example==1.0" in line:
        deadline = time.monotonic() + 30
        while not (folder / "go").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        held["proc"].wait(timeout=30)
if reaped:
    owner = subprocess_utils.enable_containment()  # what the worker's first spawn does under its lifeline
    real = owner.popen_python
    def started(argv, **kwargs):
        held["proc"] = real(argv, **kwargs)
        return held["proc"]
    owner.popen_python = started
after = {}
try:
    pip = [sys.executable, "-c", (ev / "pip.py").read_text(), str(folder), output, "0"]
    after["code"] = qwen3_setup.run_command(pip, env=env, cwd=Path.cwd(), on_line=on_line)
    if tag == proto.ACTION_PLAN:
        from tts import optional_setup
        facts = optional_setup.Facts(health={c: True for c in request["components"]},
                                     package_version={"spacy": "3.8.16"}.get)
        result = proto.make_result(rid, proto.SUCCEEDED, plan=optional_setup.plan_to_json(
            optional_setup.plan(request["components"], facts=facts)))
    else:
        result = proto.make_result(rid, proto.SUCCEEDED, verified=request["components"])
except qwen3_setup.SetupError as exc:
    after["error"] = str(exc)
    result = proto.make_result(rid, proto.FAILED, error=(proto.ACQUISITION_FAILED, str(exc)))
after["t"] = time.monotonic()
(ev / (tag + "-after.json")).write_text(json.dumps(after))
proto.publish_once(result_path, proto.encode(result))
'''


@pytest.fixture
def ev(tmp_path):
    folder = tmp_path / "evidence"
    folder.mkdir()
    (folder / "pip.py").write_text(PIP, encoding="utf-8")
    return folder


def launch(ev: Path, how: str):
    """``proto.worker_launch`` for the stand-in: the copy's own ``.venv/bin/python``, its ``scripts`` folder, the
    request and result paths the client made."""
    def made(root, path, session, **_kwargs):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
        result = Path(path).with_name(proto.RESULT_NAME)
        return proto.LaunchSpec((str(proto.main_console_python(root)), "-c", WORKER, str(ev), how, str(path),
                                 str(result)), Path(root) / "scripts", env, Path(path), result)
    return made


def owner_for(window: str):
    """The containment owner each window gives its workers: setup's own (P5-B) or the app window's (launcher.main)."""
    return bootstrap.own_optional_setup() if window == "first-run" else subprocess_utils.enable_containment()


@POSIX_ONLY
@pytest.mark.parametrize("window", ["first-run", "app"])
@pytest.mark.parametrize("output", ["devnull", "pipe"])
def test_an_optional_setup_whose_pip_exits_normally_succeeds_and_leaves_nothing_running(
        window, output, monkeypatch, app_copy, ev, sentinel):
    owner = owner_for(window)
    runs = Runs(monkeypatch)
    monkeypatch.setattr(proto, "worker_launch", launch(ev, output))
    scene = Scene(ev / "install-pip")
    try:
        box = in_thread(lambda: client.run(app_copy, proto.ACTION_INSTALL, [K], consent=install_consent(),
                                           cancelled=lambda: False, timeout_s=120))
        scene.started(bound=60)
        assert scene.alive("helper")
        let_go_and_wait(scene, box, bound=PROMPT_S + 5)
        result = box.get("value")
        assert result is not None and result["state"] == proto.SUCCEEDED, (result, box.get("error"))
        run = runs.made[-1]
        assert run.group_end == co.GROUP_ENDED and outcome_of(run) == result
        after = json.loads((ev / "install-after.json").read_text())
        assert after == {"code": 0, "t": after["t"]}
        assert scene.gone("helper") and scene.gone("pip")
        if window == "first-run":
            assert bootstrap.settle_optional_setup(owner) is True
        assert same(sentinel)
    finally:
        scene.end_left()


@POSIX_ONLY
@pytest.mark.parametrize("window", ["first-run", "app"])
def test_an_optional_setup_whose_pip_cannot_be_proved_ended_fails_once_and_says_why(
        window, monkeypatch, app_copy, ev, sentinel):
    owner = owner_for(window)
    runs = Runs(monkeypatch)
    monkeypatch.setattr(proto, "worker_launch", launch(ev, "devnull+reaped"))
    scene = Scene(ev / "install-pip")
    try:
        box = in_thread(lambda: client.run(app_copy, proto.ACTION_INSTALL, [K], consent=install_consent(),
                                           cancelled=lambda: False, timeout_s=120))
        scene.started(bound=60)
        let_go_and_wait(scene, box, bound=PROMPT_S + 5)
        result = box["value"]
        error = result["error"] or {}
        assert result["state"] == proto.FAILED and error.get("code") == proto.ACQUISITION_FAILED
        assert "could not be confirmed ended" in error["message"] and "could not be proved" in error["message"]
        run = runs.made[-1]
        published = proto.decode_result(proto.read_message_file(run.spec.result_path),
                                        request_id=run.request.request_id, request=run.request)
        assert published == result and not result["forced"], "the worker's own result, published once, is the answer"
        assert run.group_end == co.GROUP_ENDED
        # The group rule signalled nothing (the message above: its group "could not be proved"). v0.8.x P5-I-R3
        # remediation 2: the helper no longer outlives the worker that started its pip, though -- that worker is an
        # owner in turn, and once it has exited its guardian ends every descendant carrying its child token (a
        # separate identity proof: its own random token in the helper's environment, start time read right before).
        assert scene.gone("helper", bound=10.0), "a descendant of the app's pip outlived the worker that owned it"
        if window == "first-run":
            assert bootstrap.settle_optional_setup(owner) is True
        assert same(sentinel)
    finally:
        scene.end_left()


@POSIX_ONLY
def test_the_first_run_window_completes_a_check_and_install_whose_pip_leaves_a_helper_on_its_output(
        monkeypatch, tk_root, setup_log, native_theme, app_copy, ev, sentinel):
    """The real first-run window ("Begin Setup", the review, "Install Selected Components", "Continue"): each step's pip
    exits normally while its helper holds its output. Before P5-C the check never finished."""
    runs = Runs(monkeypatch)
    seen = {"launched": 0, "errors": []}
    scenes = {tag: Scene(ev / f"{tag}-pip") for tag in ("plan", "install")}
    monkeypatch.setattr(bootstrap, "run_setup", lambda on_progress, log: (True, "Setup complete."))
    monkeypatch.setattr(bootstrap, "optional_estimates", lambda: {})
    monkeypatch.setattr(bootstrap, "launch_gui", lambda log: seen.__setitem__("launched", seen["launched"] + 1))
    monkeypatch.setattr(bootstrap, "REPO_ROOT", app_copy)
    monkeypatch.setattr(proto, "worker_launch", launch(ev, "pipe"))
    monkeypatch.setattr(messagebox, "askyesno", lambda title, text, **kw: True)
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: seen["errors"].append(a))

    def release(window, tag: str) -> None:
        pump_until(window, lambda: (scenes[tag].ev / "pip.json").exists(), f"the {tag} pip and its helper")
        scenes[tag].started()
        assert scenes[tag].alive("helper")
        scenes[tag].go()

    def script(window):
        press(window, "Begin Setup")
        release(window, "plan")
        press(window, "Install Selected Components")  # shown only once the check has finished
        release(window, "install")
        press(window, "Continue")

    try:
        run_as_toplevel(monkeypatch, tk_root, script)
        code = bootstrap.run_with_gui(skip_kokoro_default=False)
        assert code == 0 and seen == {"launched": 1, "errors": []}
        assert [r.request.action for r in runs.made] == [proto.ACTION_PLAN, proto.ACTION_INSTALL]
        assert [outcome_of(r)["state"] for r in runs.made] == [proto.SUCCEEDED] * 2
        assert [r.group_end for r in runs.made] == [co.GROUP_ENDED] * 2
        for tag, scene in scenes.items():
            assert scene.gone("helper") and scene.gone("pip"), tag
        assert same(sentinel)
    finally:
        for scene in scenes.values():
            scene.end_left()


# --------------------------------------------------------------------------- #
#  Every platform: Windows keeps its Job Object and released spawn paths
# --------------------------------------------------------------------------- #
def _never(*args, **kwargs):
    raise AssertionError("the POSIX normal-exit retirement was consulted on the Windows path")


def test_windows_run_command_keeps_its_job_object_path(monkeypatch):
    class JobProcess:  # what qwen3_process.spawn returns on Windows: a process in a Job Object
        act_job = object()
        pid = 4242

        def __init__(self):
            self.stdout = io.StringIO("Collecting example==1.0\nSuccessfully installed example-1.0\n")
            self.returncode = None

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

    calls: list = []
    monkeypatch.setattr(qwen3_process, "spawn", lambda cmd, **kwargs: JobProcess())
    monkeypatch.setattr(qwen3_process, "kill_tree", lambda proc, **kwargs: calls.append("kill_tree"))
    monkeypatch.setattr(qwen3_process, "release", lambda proc: calls.append("release"))
    monkeypatch.setattr(co, "follow_lines", _never)
    monkeypatch.setattr(co, "end_led_group", _never)
    lines: list = []
    for platform in ("win32", sys.platform):  # Windows' answer; and here, a process that is in a Job Object anyway
        monkeypatch.setattr(qwen3_setup, "sys", types.SimpleNamespace(platform=platform))
        lines.clear()
        calls.clear()
        assert NATIVE_RUN(["python", "-c", "pass"], env={}, cwd=SCRIPTS, on_line=lines.append) == 0
        assert lines == ["Collecting example==1.0", LAST_LINE] and calls == ["release"]


def test_windows_base_install_keeps_its_released_spawn_paths(monkeypatch):
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setattr(bootstrap, "_hidden", lambda: {})
    monkeypatch.setattr(bootstrap, "_SETUP_STOP", threading.Event())
    monkeypatch.setattr(bootstrap, "_owner", _never)
    monkeypatch.setattr(co, "follow_lines", _never)
    monkeypatch.setattr(co, "communicate_led", _never)
    ran: list = []
    monkeypatch.setattr(bootstrap.subprocess, "run",
                        lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    assert bootstrap._child_run(["python", "-c", "pass"], capture_output=True).returncode == 0
    assert ran == [["python", "-c", "pass"]]

    class Popen:
        pid = 4242

        def __init__(self, cmd, **kwargs):
            self.stdout = io.StringIO("Collecting example==1.0\n")
            self.returncode = None

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(bootstrap.subprocess, "Popen", Popen)
    logged: list = []
    assert bootstrap._pip(["python", "-m", "pip"], {}, logged.append) == 0
    assert logged == ["  Collecting example==1.0"]
    proc = Popen(["pip"])
    monkeypatch.setattr(bootstrap, "_RUNNING_PIP", proc)
    killed: list = []
    monkeypatch.setattr(bootstrap, "_run", lambda cmd, **kw: killed.append(cmd))
    assert bootstrap.request_setup_stop() is True and killed[0][:2] == ["taskkill", "/PID"], "the stop is taskkill /T"
