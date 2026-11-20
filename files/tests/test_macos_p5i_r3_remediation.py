"""v0.8.x P5-I-R3, remediation of the independent implementation review of 0204a55 (REJECTED: 2 BLOCKER, 5 HIGH, 4
MEDIUM). One test (or more) per finding, each reproducing the reviewer's interleaving with real processes and the
reviewer's fault injection (refused unlink/rename/signals, a held thread, a stopped process):

1. a gate stopped before it read its go byte, with unlink, rename and SIGKILL refused, never runs its program after the
   latch: the ``G`` is taken back out of the pipe; an uncontained start stays a run fault after the process is gone;
2. a Qwen3 worker that exits on Cancel leaves no same-group helper behind a clean result;
3. a grant in progress when the app begins closing never starts its program;
4. a media wrapper never returns success for a child whose guardian was lost before the loss was recorded;
5. a recorded worker that is an unreaped zombie still blocks a clean end;
6. the settlement's bound: nothing granted past it; never given up before it; the packet scan's one stop window;
7. the guardian signals a leader once, identity read right before, and hears unregistrations first;
8. a launch whose setup fails before ``Popen`` leaves no phantom start;
11. relative ``PATH`` entries resolve against ``cwd``; a gate whose status descriptor is above 1024 still works.
(9, the Converter's single result, and 10, the TTS pool on Windows, are covered in their own modules.)
macOS only.
"""

from __future__ import annotations
#: C1, Cancel acknowledgment: about one second (owner decision 2026-11-20; was 0.5 s).
C1_ACK_S = 1.0

import contextlib
import errno
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from shared import child_ownership as co
from shared import subprocess_utils as sp
from shared.cancellation import ConversionCancelled
from shared.job_control import JobController

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="POSIX containment is the Mac's")

PY = sys.executable


def _wait(fn, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.01)
    return fn()


def _live(pid, start) -> bool:
    return co.process_start_time(pid) == start and not co._has_exited(pid)


def _stat(pid) -> int:
    info = co._darwin_kinfo(pid)
    return -1 if info is None else info[co._P_STAT_OFFSET]


def _controller(name="r3-remed") -> JobController:
    job = JobController(name, cancel_clock=time.monotonic)
    job.start()
    return job


@pytest.fixture()
def owner(monkeypatch):
    made = co.Owner(lifeline=False)
    monkeypatch.setattr(sp, "_owner", made)
    yield made
    monkeypatch.undo()
    made.shutdown()


def _marker_program(folder: Path, marker: Path) -> Path:
    folder.mkdir(exist_ok=True)
    script = folder / "ffmpeg"
    script.write_text(f"#!/bin/sh\nprintf ran > {marker}\n", encoding="utf-8")
    script.chmod(0o700)
    return script


def _ffmpeg() -> str:
    from shared import ffmpeg_utils

    if not ffmpeg_utils.have_ffmpeg():
        pytest.skip("requires the app's verified FFmpeg")
    return ffmpeg_utils.ffmpeg_cmd()


# =========================================================================== 1 (BLOCKER)

def _stopped_gate_with_everything_refused(owner, controller, script, *, take_back=True):
    """The reviewer's ``late`` interleaving: the gate is SIGSTOPped right before ``G`` is written, and unlink, rename,
    chmod and every owner signal to it are refused. Returns (gate entry, latch seconds, the start's outcome)."""
    gate, entered, outcome = [], threading.Event(), {}
    saved_write, saved_unlink, saved_rename, saved_chmod = os.write, os.unlink, os.rename, os.chmod
    saved_deliver = co.Owner._deliver

    def write(fd, data):
        if data == b"G" and not gate:
            entry = owner.outstanding(controller.cancel_check)[0]
            gate.append(entry)
            os.kill(entry.pid, signal.SIGSTOP)
            assert _wait(lambda: _stat(entry.pid) == 4, 5)
            answer = saved_write(fd, data)
            entered.set()
            return answer
        return saved_write(fd, data)

    def refuse_path(saved):
        def call(path, *args, **kwargs):
            if gate and str(path).startswith(owner._permits):
                raise PermissionError(errno.EACCES, "test: refused")
            return saved(path, *args, **kwargs)
        return call

    def deliver(self, entry, sig):
        return False if gate and entry is gate[0] else saved_deliver(self, entry, sig)

    def run():
        try:
            owner.popen_external([str(script)], **sp._launch_kwargs(controller.cancel_check))
        except BaseException as exc:  # noqa: BLE001 - the outcome is the assertion
            outcome["error"] = exc

    owner.ensure_guardian()
    patches = [patch.object(os, "write", write), patch.object(os, "unlink", refuse_path(saved_unlink)),
               patch.object(os, "rename", refuse_path(saved_rename)), patch.object(os, "chmod", refuse_path(saved_chmod)),
               patch.object(co.Owner, "_deliver", deliver)]
    if not take_back:
        patches.append(patch.object(co.Owner, "_take_back_go", staticmethod(lambda launch: False)))
    with contextlib.ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        assert entered.wait(10)
        began = time.monotonic()
        controller.request_cancel()
        latched = time.monotonic() - began
        thread.join(5)
    return gate[0], latched, outcome


def test_a_stopped_gate_whose_revocation_and_kill_are_refused_never_runs_after_the_latch(owner, tmp_path):
    controller = _controller("r3-late")
    marker = tmp_path / "ran"
    script = _marker_program(tmp_path / "bin", marker)
    gate, latched, outcome = _stopped_gate_with_everything_refused(owner, controller, script)
    try:
        assert latched < C1_ACK_S, f"C1: the latch took {latched:.3f} s"
        assert isinstance(outcome.get("error"), ConversionCancelled), outcome
        os.kill(gate.pid, signal.SIGCONT)  # resumed after the latch: it reads end-of-file, never G
        assert _wait(lambda: gate.proc.poll() is not None or co._has_exited(gate.pid), 5)
        time.sleep(0.2)
        assert not marker.exists(), "the program ran after the Cancel latched"
    finally:
        if _live(gate.pid, gate.start_time):
            os.kill(gate.pid, signal.SIGKILL)


def test_control_without_the_take_back_the_late_gate_runs_and_the_run_is_failed_for_good(owner, tmp_path):
    """The reviewer's BLOCKER, reproduced with the take-back switched off (every other channel refused): the program
    runs after the latch -- the stated OS-refusal exception -- and the run is reported FAILED for it, also once the
    program has ended (it used to settle clean)."""
    controller = _controller("r3-late-control")
    marker = tmp_path / "ran"
    script = _marker_program(tmp_path / "bin", marker)
    gate, _latched, _outcome = _stopped_gate_with_everything_refused(owner, controller, script, take_back=False)
    saved = co.Owner._deliver
    try:
        # The kill stays refused while it is resumed (the owner keeps ending it otherwise, and SIGKILL ends a stopped
        # process before it could run anything).
        refuse = patch.object(co.Owner, "_deliver", lambda self, e, sig: False if e is gate else saved(self, e, sig))
        refuse.start()
        os.kill(gate.pid, signal.SIGCONT)
        assert _wait(marker.exists, 5), "control: with no take-back the late gate does run"
        assert _wait(lambda: gate.proc.poll() is not None, 5)
        refuse.stop()
        problem = sp.containment_problem(controller.cancel_check, stop_s=0.3)
        assert problem is not None and "uncontained" in problem, problem
    finally:
        with contextlib.suppress(RuntimeError):
            refuse.stop()
        if _live(gate.pid, gate.start_time):
            os.kill(gate.pid, signal.SIGKILL)


# =========================================================================== 2 (BLOCKER)

def test_a_qwen3_worker_that_exits_on_cancel_leaves_no_same_group_helper(owner, tmp_path):
    from tts import qwen3_synth as qs

    controller = _controller("r3-qwen")
    work = tmp_path / "job"
    work.mkdir()
    stub = work / "worker.py"
    stub.write_text("import os, subprocess, time\nfrom pathlib import Path\nwork = Path.cwd()\n"
                    "child = subprocess.Popen(['/bin/sleep', '30'], stdout=subprocess.DEVNULL, "
                    "stderr=subprocess.DEVNULL)\n(work / 'ready').write_text(f'{os.getpid()} {child.pid}')\n"
                    "while not (work / 'cancel').exists():\n    time.sleep(0.01)\n", encoding="utf-8")
    box: dict = {}

    def run():
        try:
            qs.run_worker({"cancel_file": str(work / "cancel")}, work, python=Path(PY), script=stub,
                          env=dict(os.environ), cancel_check=controller.cancel_check)
        except BaseException as exc:  # noqa: BLE001 - the outcome is the assertion
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready = work / "ready"
    leader, helper = map(int, _wait(lambda: ready.exists() and ready.read_text(), 20).split())
    ident = co.process_start_time(helper)
    try:
        assert os.getpgid(helper) == leader
        controller.request_cancel()
        thread.join(15)
        assert not thread.is_alive()
        assert not _live(helper, ident), "a helper in the worker's group outlived a clean Cancel"
        assert isinstance(box.get("error"), ConversionCancelled), box
        assert sp.containment_problem(controller.cancel_check) is None
    finally:
        if _live(helper, ident):
            os.kill(helper, signal.SIGKILL)


# =========================================================================== 3 (HIGH)

def test_a_grant_in_progress_when_the_app_begins_closing_never_starts_its_program(owner, tmp_path):
    marker = tmp_path / "ran"
    script = _marker_program(tmp_path / "bin", marker)
    owner.ensure_guardian()
    saved = co.os.symlink
    in_grant, release, result = threading.Event(), threading.Event(), []

    def link(src, dst, *args, **kwargs):
        if str(dst).startswith(owner._permits):
            in_grant.set()
            assert release.wait(10)
        return saved(src, dst, *args, **kwargs)

    def run():
        try:
            result.append(owner.popen_external([str(script)]))
        except BaseException as exc:  # noqa: BLE001
            result.append(exc)

    with patch.object(co.os, "symlink", link):
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        assert in_grant.wait(5)
        began = time.monotonic()
        owner.begin_closing()  # the closing latch, with the grant held inside its symlink
        assert time.monotonic() - began < 1.0
        release.set()
        thread.join(5)
    assert result and isinstance(result[0], co.ContainmentUnavailable), result
    time.sleep(0.3)
    assert not marker.exists(), "a program began executing after the closing latch"


# =========================================================================== 4 (HIGH)

def test_a_supervised_step_whose_guardian_dies_is_never_a_success_even_before_the_loss_is_recorded(owner):
    ffmpeg = _ffmpeg()
    controller = _controller("r3-lost")
    hold, waiting, outcomes = threading.Event(), threading.Event(), []
    real_lost = owner._guardian_lost

    def held(proc, generation):
        if threading.current_thread().name == "act-guardian-watch":
            waiting.set()
            hold.wait(10)
        return real_lost(proc, generation)

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi", "-i", "sine=d=1", "-f", "null", "-"]

    def run():
        with sp.cancellable(controller.cancel_check):
            outcomes.append(sp.run_supervised(cmd))

    with patch.object(owner, "_guardian_lost", held):
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            _wait(lambda: any(e.state == co.LIVE for e in owner.outstanding(controller.cancel_check)), 10)
            guardian = owner._current
            os.kill(guardian.pid, signal.SIGKILL)
            assert waiting.wait(5)
            thread.join(10)
            assert outcomes and outcomes[0].returncode != 0, "a step that lost its guardian returned success"
            assert b"lost containment" in outcomes[0].stderr
        finally:
            hold.set()
            thread.join(5)


# =========================================================================== 5 (HIGH)

def test_a_recorded_worker_that_is_an_unreaped_zombie_still_blocks_a_clean_end(owner):
    controller = _controller("r3-zombie")
    proc = owner.popen_python([PY, "-c", "pass"])
    entry = owner.child(proc)
    try:
        assert co.wait_exited(proc, 5, entry.start_time)
        assert proc.returncode is None and _stat(proc.pid) == co._SZOMB
        sp.note_unresolved(proc.pid, entry.start_time, "a worker whose reap was not confirmed")
        controller.request_cancel()
        assert proc.pid in sp.unresolved_children()
        assert sp.containment_problem(controller.cancel_check, stop_s=0.2) is not None
    finally:
        proc.wait(5)
    assert proc.pid not in sp.unresolved_children(), "reaped: dropped"


# =========================================================================== 6 (HIGH)

def test_a_child_still_running_when_the_bound_has_passed_is_never_settled_clean(owner):
    ffmpeg = _ffmpeg()
    controller = _controller("r3-bound")
    proc = owner.popen_external([ffmpeg, "-nostdin", "-loglevel", "error", "-re", "-f", "lavfi", "-i", "sine=d=20",
                                 "-f", "null", "-"], owner_run=controller.cancel_check)
    controller.request_cancel()
    assert sp.settle_bound(controller.cancel_check, 0.0) == 0.0, "no extra look granted past the bound"
    problem = sp.containment_problem(controller.cancel_check, stop_s=0.0)
    assert problem is not None and f"pid {proc.pid}" in problem


def test_settlement_keeps_ending_a_child_until_its_bound_not_its_own_first_deadline(owner):
    """A SIGKILL refused for 1.4 s: the child is reaped at about 1.45 s, inside the 4 s bound -- the run settles clean
    (it used to fail at 1.0 s, the entry's own confirmation deadline)."""
    ffmpeg = _ffmpeg()
    controller = _controller("r3-patient")
    saved = co.Owner._deliver
    began = [time.monotonic()]

    def deliver(self, entry, sig):
        if entry.kind == co.CLASS_B and time.monotonic() - began[0] < 1.4:
            return False
        return saved(self, entry, sig)

    with patch.object(co.Owner, "_deliver", deliver):
        proc = owner.popen_external([ffmpeg, "-nostdin", "-loglevel", "error", "-re", "-f", "lavfi", "-i",
                                     "sine=d=20", "-f", "null", "-"], owner_run=controller.cancel_check)
        began[0] = time.monotonic()
        controller.request_cancel()
        problem = sp.containment_problem(controller.cancel_check)
        took = time.monotonic() - began[0]
    assert problem is None, problem
    assert proc.returncode is not None and 1.3 < took < sp.FFMPEG_STOP_S


def test_a_cancelled_run_with_no_click_instant_gets_the_whole_stop_bound(owner):
    controller = JobController("r3-no-clock")
    controller.start()
    controller.request_cancel()
    assert sp.settle_bound(controller.cancel_check, 4.0) == 4.0
    quiet = JobController("r3-quiet")
    quiet.start()
    assert sp.settle_bound(quiet.cancel_check, 4.0) == 1.0


def test_a_packet_scan_that_cannot_be_stopped_returns_inside_the_bound_and_is_never_a_cancellation(owner, tmp_path):
    from m4b import m4b_continuous as mc

    controller = _controller("r3-scan")
    probe = tmp_path / "ffprobe"
    probe.write_text(f"#!{PY}\nimport time\ntime.sleep(30)\n", encoding="utf-8")
    probe.chmod(0o700)
    result, saved = [], co.Owner._deliver

    def work():
        with sp.run_context(controller.cancel_check):
            result.append(mc.scan_packets("fake.m4b", total=1024, priming=0, duration_seconds=1,
                                          cancelled=controller.cancel_check, ffprobe=str(probe)))

    with patch.object(co.Owner, "_deliver", lambda self, e, sig: False if e.label == "ffprobe" else saved(self, e, sig)), \
            patch.object(co.Owner, "kill_now", lambda self, p: False):
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        child = _wait(lambda: next((e for e in owner.outstanding(controller.cancel_check) if e.state == co.LIVE), None),
                      10)
        try:
            began = time.monotonic()
            controller.request_cancel()
            thread.join(10)
            took = time.monotonic() - began
            assert result == ["the packet scan could not be stopped"], result
            assert took <= 2 * mc._GRACE_SECONDS + 0.3, f"returned after {took:.2f} s"
            assert sp.containment_problem(controller.cancel_check, stop_s=0.2) is not None
        finally:
            if _live(child.pid, child.start_time):
                os.kill(child.pid, signal.SIGKILL)


# =========================================================================== 7 (HIGH)

def test_the_guardian_signals_a_leader_once_with_its_identity_read_right_before(monkeypatch):
    from shared import child_guardian as cg

    now = {123: (100, 1)}
    seen = []

    def killpg(pid, sig):
        seen.append(("killpg", pid, now[pid]))
        now[pid] = (101, 1)  # reaped and the id handed on right after

    monkeypatch.setattr(cg, "_start_time", now.get)
    monkeypatch.setattr(cg.os, "killpg", killpg)
    monkeypatch.setattr(cg.os, "kill", lambda pid, sig: seen.append(("kill", pid, now[pid])))
    cg._end_leaders({123: (100, 1)})
    assert seen == [("killpg", 123, (100, 1))], "one signal, never a second unchecked one"


def test_the_guardian_hears_an_unregistration_written_before_its_trigger():
    from shared import child_guardian as cg

    read, write = os.pipe()
    try:
        os.write(write, b"A 4242 1 2\na 4242\nA 4343 3 4\n")
        leaders = {}
        cg._drain(read, b"", leaders)
        assert leaders == {4343: (3, 4)}
    finally:
        os.close(read)
        os.close(write)


# =========================================================================== 8 (MEDIUM)

def test_a_launch_whose_setup_fails_before_popen_leaves_no_phantom_start(owner, tmp_path):
    controller = _controller("r3-dropped")
    script = _marker_program(tmp_path / "bin", tmp_path / "ran")
    owner.ensure_guardian()
    with patch.object(co.os, "mkdir", side_effect=OSError(errno.ENOSPC, "test: no space")):
        with pytest.raises(OSError):
            owner.popen_external([str(script)], owner_run=controller.cancel_check)
    assert owner.outstanding(controller.cancel_check) == []
    assert owner._current.spawns == 0
    assert owner.settle_run(controller.cancel_check, 0.25) == []


# =========================================================================== 11 (MEDIUM)

def test_a_relative_path_entry_is_searched_from_the_programs_working_folder(owner, tmp_path):
    ffmpeg = _ffmpeg()
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "ffmpeg").symlink_to(ffmpeg)
    env = dict(os.environ, PATH="bin")
    direct = subprocess.run(["ffmpeg", "-version"], env=env, cwd=tmp_path, capture_output=True)
    proc = owner.popen_external(["ffmpeg", "-version"], cwd=tmp_path, env=env, stdout=subprocess.PIPE)
    out, _ = proc.communicate(timeout=10)
    assert direct.returncode == 0 and proc.returncode == 0 and out.startswith(b"ffmpeg version")


def test_a_gate_whose_descriptors_are_above_1024_still_identifies_itself(owner):
    import resource

    ffmpeg = _ffmpeg()
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft < 1100:
        if hard != resource.RLIM_INFINITY and hard < 1100:
            pytest.skip("the descriptor limit cannot be raised here")
        resource.setrlimit(resource.RLIMIT_NOFILE, (1100, hard))
    owner.ensure_guardian()
    opened = []
    try:
        while not opened or opened[-1] < 1030:
            opened.append(os.open(os.devnull, os.O_RDONLY))
        proc = owner.popen_external([ffmpeg, "-version"], stdout=subprocess.PIPE)
        out, _ = proc.communicate(timeout=10)
        assert proc.returncode == 0 and out.startswith(b"ffmpeg version")
    finally:
        for fd in opened:
            os.close(fd)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


# =========================================================================== 9 (MEDIUM)

def test_the_converter_asks_containment_before_it_settles_its_one_result():
    """The Converter used to settle its RunResult first and then fail the controller on a containment problem: the
    queued result could still say CANCELLED or SUCCEEDED. The question now comes before every settlement call."""
    import ast

    from source_probe import UNIVERSAL

    tree = ast.parse((UNIVERSAL / "m4b/converter/m4b_converter.py").read_text(encoding="utf-8"))
    body = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_run_conversion")
    calls = [(n.lineno, getattr(n.func, "attr", getattr(n.func, "id", ""))) for n in ast.walk(body)
             if isinstance(n, ast.Call)]
    asked = min(line for line, name in calls if name == "containment_problem")
    settled = [line for line, name in calls if name in ("settle", "merge_attempt")]
    assert settled and all(asked < line for line in settled), (asked, settled)
