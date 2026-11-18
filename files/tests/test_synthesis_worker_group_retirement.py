"""v0.8.x P5-D -- a synthesis worker is never reaped before its process group has been ended (POSIX).

**Reproduced at ``bafa792``** (``files/dev-work/macos-p5d/repro/before/``, real processes, recorded before any
production change). The local-engine worker (Kokoro on a Mac, ``tts.local_engine_host``) and the OmniVoice worker
(``tts.omnivoice_synth.run_worker``) are class-A children: each leads its own process group on its owner's lifeline. A
stand-in worker left a helper in that group and then ended -- normally, on Cancel, or by crashing. Their supervisors
reaped it first (``WorkerHost.alive``/``kill``/``close``/``_died`` through ``poll()``/``wait()``,
``qwen3_process.kill_tree`` through ``poll()``, ``run_worker``'s ``finally``), so the group's id could no longer be
proved the worker's and nothing -- not the supervisor, not the owner's orderly end, not the lifeline -- ever ended the
helper. A helper holding the worker's output made it worse: the local-engine host closed that pipe under its blocked
reader and hung until the helper ended (a crash, an engine switch); a helper on the protocol channel kept a request
waiting for its unrelated chunk timeout; OmniVoice waited 20 + 10 s after ``done`` and then reported success, and took
22 s to return a "clean" Cancel (bound: 4 s).

**Now**: whatever ends the worker, its group is ended the P5-A way first (``child_ownership.end_led_group``: under the
``Popen``'s waitpid lock, unreaped, same kernel start time, signalled until the kernel says nothing is left), its exit
is seen without reaping it, a pipe is closed only once its reader has finished, and only then is the worker reaped. A
group that cannot be proved or confirmed ended, or output held open past it, makes the file a failure -- never a
success, never a clean Cancel. ``kill_tree`` reaches a group whose leader has already exited, and signals none it
cannot prove.

Real, disposable processes throughout. A process is "gone" only when its pid no longer has the kernel start time
recorded while it ran (a zombie does not count as running); nothing is found by name or by a scan, and whatever a test
leaves is ended by that same identity after its assertions. An unrelated process started for each test must survive it.
"""

from __future__ import annotations

import contextlib
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

from shared import child_ownership as co
from shared.cancellation import ConversionCancelled
from tts import local_engine_host as hosts
from tts import omnivoice_synth as osy
from tts import qwen3_process

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX synthesis-worker group retirement (Windows: Job Objects)")
#: How long a supervisor may take to return once its worker has ended, whatever it left. Before P5-D a helper holding the
#: worker's output kept it waiting for as long as the helper ran (300 s here), or for an unrelated timeout.
PROMPT_S = 5.0
#: How long a process its group's end has already killed may take to finish exiting (the helpers sleep 300 s).
EXIT_S = 2.0
#: The macOS Cancel contract (plan 11.2.1): the local-engine worker is stopped and reaped within 2 s, OmniVoice within
#: 4 s (its 2 s grace included).
LOCAL_ENGINE_STOP_S = hosts.CANCEL_BOUND_S
OMNIVOICE_STOP_S = 4.0

# --------------------------------------------------------------------------- #
#  Stand-ins: a helper in the worker's own group, the two workers
# --------------------------------------------------------------------------- #
#: Starts a helper -- a plain child, so a member of the worker's own process group -- and records its identity (and
#: the worker's) before returning. ``stdio``: ``detached`` (no pipe of the worker's), ``inherit`` (the worker's fds 1
#: and 2), ``channel:<fd>`` (also the descriptor <fd>, as a forked helper would hold it), ``escapee`` (it leaves the
#: group with setsid and holds fds 1 and 2: the documented limit no group end reaches).
HELPER = r'''
import json, os, subprocess, sys
from pathlib import Path


def start_helper(stdio, record, scripts):
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from shared.child_ownership import process_start_time
    kwargs = {"stdin": subprocess.DEVNULL}
    if stdio == "detached":
        kwargs.update(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif stdio == "escapee":
        kwargs.update(start_new_session=True)
    elif stdio.startswith("channel:"):
        kwargs.update(pass_fds=(int(stdio.split(":", 1)[1]),))
    helper = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(300)"], **kwargs)
    row = {"pid": helper.pid, "pgid": os.getpgid(helper.pid), "start": process_start_time(helper.pid),
           "worker_pid": os.getpid(), "worker_pgid": os.getpgrp(), "worker_start": process_start_time(os.getpid())}
    Path(record + ".new").write_text(json.dumps(row))
    os.replace(record + ".new", record)
'''

#: The REAL local-engine worker program (protocol, private channel, errors) serving a stand-in engine. On its first chunk
#: it starts a helper (``P5D_PLAN["helper"]``), then: ``ok`` answers; ``crash`` exits 3 mid-chunk after a last word;
#: ``block`` blocks every chunk in a native wait; ``exit-after`` answers and then exits 0 on its own.
LOCAL_ENGINE_STAND_IN = r'''
import json, os, select, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = json.loads(os.environ["P5D_PLAN"])
sys.path[:0] = [PLAN["scripts"], HERE]
from tts import local_engine_worker as worker
from p5d_helper import start_helper
STATE = {"chunks": 0}


def native_wait(seconds):
    read, _write = os.pipe()
    select.select([read], [], [], None if seconds < 0 else seconds)


class StandIn:
    sample_rate = 24000

    def versions(self):
        return {"stand-in": "p5d"}

    def load(self, request):
        return {"lang_code": request.get("lang_code"), "cached": False, "load_s": 0.01, "device": "cpu",
                "dtype": "float32", "threads": 1}

    def synthesize(self, request):
        import numpy as np
        STATE["chunks"] += 1
        then = PLAN["then"]
        if STATE["chunks"] == 1 and PLAN.get("helper"):
            stdio = PLAN["helper"]
            if stdio == "channel":
                stdio = "channel:%d" % worker._channel.fileno()
            start_helper(stdio, PLAN["record"], PLAN["scripts"])
            if then == "crash":
                print("stand-in: its last words before it fell over", file=sys.stderr, flush=True)
                os._exit(3)
        if then == "block":
            native_wait(-1)
        if then == "exit-after" and STATE["chunks"] == 1:
            threading.Thread(target=lambda: (time.sleep(0.2), os._exit(0)), daemon=True).start()
        pcm = (0.25 * np.sin(2 * np.pi * 220 * np.arange(2400) / 24000)).astype(np.float32)
        return pcm, {"segments": 1, "phonemes": ["x"]}


worker.ADAPTERS["kokoro"] = StandIn
sys.exit(worker.main(sys.argv[1:]))
'''

#: A stand-in OmniVoice worker speaking the real ``@@EVENT`` protocol: ``loaded``, then a helper (``P5D_PLAN["helper"]``,
#: if any), then: ``done`` (a chunk event per chunk, ``done``, exit 0); ``cancel`` (waits for the cancel flag, then
#: ``canceled`` and exit 130 -- it obeys); ``crash`` (exit 3, no terminal event); ``stubborn`` (ignores SIGTERM and the
#: flag, blocked). ``ready``: a file written once the helper is recorded.
OMNIVOICE_STAND_IN = r'''
import json, os, signal, sys, time
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
plan = json.loads(os.environ.get("P5D_PLAN", "{}"))
job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
then = plan.get("then", "done")


def emit(event):
    print("@@EVENT " + json.dumps(event), flush=True)


emit({"event": "loaded", "device": "mps", "device_name": "Stand-in", "load_s": 0.01, "prompt": "built",
      "prompt_s": 0.01, "chunks": len(job["chunks"])})
if plan.get("helper"):
    from p5d_helper import start_helper
    start_helper(plan["helper"], plan["record"], plan["scripts"])
if plan.get("ready"):
    Path(plan["ready"]).write_text("ready")
if then == "cancel":
    while not os.path.exists(job["cancel_file"]):
        time.sleep(0.02)
    emit({"event": "canceled", "completed": 0})
    sys.exit(130)
if then == "crash":
    sys.stderr.write("stand-in: the engine fell over\n")
    sys.exit(3)
if then == "stubborn":
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(120)
for chunk in job["chunks"]:
    index = chunk["index"]
    emit({"event": "chunk", "index": index, "of": len(job["chunks"]), "wav": "chunk-%04d.wav" % (index + 1),
          "audio_s": 0.2, "gen_s": 0.01, "sample_rate": 24000, "peak": 0.1})
emit({"event": "done", "chunks": len(job["chunks"]), "sample_rate": 24000, "device": "mps"})
sys.exit(0)
'''

REQUEST = {"text": "Hello there.", "voice": "af_heart", "speed": 1.0, "split_pattern": r"\n+", "seed": None}


def running(identity) -> bool:
    """True while *identity* ``(pid, start)`` is still that process and not merely a zombie."""
    pid, start = identity
    if start is None or co.process_start_time(pid) != tuple(start):
        return False
    if sys.platform == "darwin":
        info = co._darwin_kinfo(pid)
        return info is not None and info[co._P_STAT_OFFSET] != co._SZOMB
    return True


def gone(identity, within: float = EXIT_S) -> bool:
    deadline = time.monotonic() + within
    while running(identity):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return True


class Scene:
    """One test's stand-ins, its unrelated sentinel, and what it recorded (ended by identity afterwards)."""

    def __init__(self, folder: Path, monkeypatch):
        self.dir = folder
        self.monkeypatch = monkeypatch
        (folder / "p5d_helper.py").write_text(HELPER, encoding="utf-8")
        (folder / "le_stand_in.py").write_text(LOCAL_ENGINE_STAND_IN, encoding="utf-8")
        (folder / "ov_stand_in.py").write_text(OMNIVOICE_STAND_IN, encoding="utf-8")
        self.record = folder / "helper.json"
        self.ready = folder / "ready"
        self.hosts: list[hosts.WorkerHost] = []
        self.owners: list[co.Owner] = []
        self.logs: list[str] = []
        self.extra: list[tuple] = []  # identities a test started itself
        self.sentinel = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(300)"],
                                         start_new_session=True, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.sentinel_id = (self.sentinel.pid, co.process_start_time(self.sentinel.pid))

    def plan(self, helper, then: str) -> dict:
        plan = {"helper": helper, "then": then, "record": str(self.record), "ready": str(self.ready),
                "scripts": str(SCRIPTS)}
        self.monkeypatch.setenv("P5D_PLAN", json.dumps(plan))
        return plan

    # -- the local-engine worker
    def host(self, helper, then: str, **kwargs) -> hosts.WorkerHost:
        self.plan(helper, then)
        owner = co.Owner()
        self.owners.append(owner)
        host = hosts.WorkerHost("kokoro", sample_rate=24000, owner=owner, log=self.logs.append,
                                argv=[sys.executable, "-I", "-B", str(self.dir / "le_stand_in.py"), "kokoro"],
                                **kwargs)
        self.hosts.append(host)
        return host

    # -- the OmniVoice worker
    def omnivoice(self, helper, then: str, *, cancel_when_ready: bool = False, spawn=None, **kwargs):
        plan = self.plan(helper, then)
        env = dict(os.environ, P5D_PLAN=json.dumps(plan))
        job_dir = self.dir / "job"
        job_dir.mkdir(exist_ok=True)
        job = {"cancel_file": str(job_dir / "cancel"), "out_dir": str(job_dir / "chunks"),
               "chunks": [{"index": 0, "text": "One.", "seed": 1}, {"index": 1, "text": "Two.", "seed": 2}]}
        self.latched_at = None

        def cancel() -> bool:
            if cancel_when_ready and self.latched_at is None and self.ready.exists():
                self.latched_at = time.monotonic()
            return self.latched_at is not None

        return osy.run_worker(job, job_dir, name="job-001", python=Path(sys.executable),
                              script=self.dir / "ov_stand_in.py", env=env, cancel_check=cancel, log=self.logs.append,
                              spawn=spawn, **kwargs)

    # -- what was left
    def helper(self, bound: float = 30.0) -> dict:
        deadline = time.monotonic() + bound
        while not self.record.exists():
            assert time.monotonic() < deadline, "the stand-in never recorded its helper"
            time.sleep(0.01)
        row = json.loads(self.record.read_text())
        assert row["start"] is not None and row["worker_pgid"] == row["worker_pid"], "the worker leads its own group"
        assert row["pgid"] in (row["worker_pgid"], row["pid"]), "the helper is in it (an escapee: in a group of its own)"
        return row

    def helper_id(self) -> tuple:
        row = self.helper()
        return (row["pid"], tuple(row["start"]))

    def worker_id(self) -> tuple:
        row = self.helper()
        return (row["worker_pid"], tuple(row["worker_start"]))

    def bounded(self, call, seconds: float):
        """Run *call* on a thread for at most *seconds*: ``("returned", value)``, ``("raised", exc)`` or ``("hung",
        None)``. A hung call is released afterwards by ending what the test recorded (by identity)."""
        box: dict = {}

        def target() -> None:
            try:
                box["value"] = call()
            except BaseException as exc:  # noqa: BLE001 - handed to the test
                box["exc"] = exc

        thread = threading.Thread(target=target, daemon=True)
        began = time.monotonic()
        thread.start()
        thread.join(seconds)
        self.elapsed = time.monotonic() - began
        if thread.is_alive():
            self._hung.append(thread)
            return "hung", None
        return ("raised", box["exc"]) if "exc" in box else ("returned", box.get("value"))

    _hung: list

    def sentinel_alive(self) -> bool:
        return running(self.sentinel_id)

    def cleanup(self) -> None:
        identities = list(self.extra)
        if self.record.exists():
            row = json.loads(self.record.read_text())
            identities += [(row["pid"], tuple(row["start"])), (row["worker_pid"], tuple(row["worker_start"]))]
        for pid, start in identities:  # ends a hung supervisor's cause first, by recorded identity only
            co.signal_if_same(pid, start, signal.SIGKILL)
        for thread in self._hung:
            thread.join(10)
        for host in self.hosts:
            done = threading.Thread(target=host.close, args=("test over",), daemon=True)
            done.start()
            done.join(10)
        for owner in self.owners:
            owner.shutdown()
        co.signal_if_same(self.sentinel_id[0], self.sentinel_id[1], signal.SIGKILL)
        self.sentinel.wait(5)


@pytest.fixture
def scene(tmp_path, monkeypatch):
    made = Scene(tmp_path, monkeypatch)
    made._hung = []
    yield made
    made.cleanup()


def _settled(outcome, kind, *, within: float):
    status, value = outcome
    assert status != "hung", f"the supervisor did not return within {within} s (it waited on what its worker left)"
    if kind is None:
        assert status == "returned", f"expected a return, got {value!r}"
    else:
        assert status == "raised" and isinstance(value, kind), f"expected {kind.__name__}, got {status}: {value!r}"
    return value


# --------------------------------------------------------------------------- #
#  The local-engine worker (tts.local_engine_host)
# --------------------------------------------------------------------------- #
@POSIX_ONLY
@pytest.mark.parametrize("held", ["detached", "inherit", "channel"])
def test_a_crashed_local_engine_worker_takes_its_helper_with_it_and_fails_the_file_promptly(scene, held):
    """Crash mid-chunk with a helper in its group: on /dev/null, on the worker's stderr, or on its protocol channel.
    Before: the helper outlived it; on stderr the host hung closing that pipe; on the channel it waited for the chunk
    timeout (60 s here, 1,800 s in production) and then hung. Now: the exit is seen, the group ended, the file failed
    with the worker's own last words, at once."""
    host = scene.host(held, "crash", chunk_timeout_s=60.0)
    host.load({"lang_code": "a"})
    error = _settled(scene.bounded(lambda: host.synthesize(REQUEST, folder=scene.dir), PROMPT_S),
                     hosts.LocalEngineFailed, within=PROMPT_S)
    text = str(error)
    assert "stopped unexpectedly" in text and "exit code 3" in text, text
    assert "last words before it fell over" in text, "its standard error reached its end: the tail is whole"
    assert "could not be confirmed stopped" not in text
    assert gone(scene.helper_id()), "the helper ended with the worker's group"
    assert host._proc is None and host.last_end is not None and host.last_end.problem() is None
    assert scene.sentinel_alive()


@POSIX_ONLY
@pytest.mark.parametrize("held", ["detached", "inherit"])
def test_closing_a_local_engine_worker_ends_its_group_before_it_is_reaped(scene, held):
    """An engine switch (``close``): the worker obeys ``exit`` and exits normally. Before: it was reaped at once, so
    its helper outlived the close and even the owner's orderly end; one on its stderr hung the close. Now: neither."""
    host = scene.host(held, "ok")
    host.load({"lang_code": "a"})
    assert host.synthesize(REQUEST, folder=scene.dir).pcm.size > 0
    helper, worker = scene.helper_id(), scene.worker_id()
    _settled(scene.bounded(lambda: host.close("engine switched"), PROMPT_S), None, within=PROMPT_S)
    assert gone(helper) and gone(worker)
    assert host.last_end.group == co.GROUP_ENDED and host.last_end.problem() is None
    assert scene.sentinel_alive()


@POSIX_ONLY
def test_alive_never_reaps_a_worker_that_exited_on_its_own(scene):
    """``alive()`` used ``poll()``, which reaped an idle worker that had exited, so its group could never be ended.
    Now the exit is seen without reaping it: the worker stays this process's zombie until its group has been ended."""
    host = scene.host("detached", "exit-after")
    host.load({"lang_code": "a"})
    host.synthesize(REQUEST, folder=scene.dir)
    worker = scene.worker_id()
    deadline = time.monotonic() + PROMPT_S
    while host.alive():
        assert time.monotonic() < deadline, "the stand-in never exited"
        time.sleep(0.02)
    assert host._proc.returncode is None, "not reaped by alive()"
    assert co.process_start_time(worker[0]) == worker[1], "still this process's zombie: its group's id is still its own"
    host.kill("cancel")
    assert gone(scene.helper_id()) and host.last_end.group == co.GROUP_ENDED
    assert scene.sentinel_alive()


@POSIX_ONLY
@pytest.mark.parametrize("route", ["the run's own end", "cancel_requested"])
def test_cancel_after_an_idle_worker_exited_still_ends_its_helper(scene, monkeypatch, route):
    """Cancel arriving just after the worker exited on its own (idle between files). Before: ``kill`` polled -- and so
    reaped -- it first and ``cancel_requested`` returned at ``alive()``'s reap; the helper ran on. Now both end its
    group first."""
    host = scene.host("detached", "exit-after")
    host.load({"lang_code": "a"})
    host.synthesize(REQUEST, folder=scene.dir)
    helper = scene.helper_id()
    co.wait_exited(host._proc, PROMPT_S)
    if route == "cancel_requested":
        monkeypatch.setattr(hosts, "_HOST", host)
        hosts.cancel_requested("kokoro")
    else:
        host.kill("cancel")  # kokoro_synth._end_worker_after_cancel
    assert gone(helper, within=LOCAL_ENGINE_STOP_S + EXIT_S)
    deadline = time.monotonic() + LOCAL_ENGINE_STOP_S
    while host._proc is not None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert host._proc is None and host.last_end.problem() is None
    assert scene.sentinel_alive()


@POSIX_ONLY
def test_cancel_mid_chunk_ends_worker_and_helper_within_the_bound(scene):
    """Control (it held before P5-D too): Cancel while the worker is busy SIGKILLs its whole group at once."""
    host = scene.host("detached", "block")
    host.load({"lang_code": "a"})
    latched: dict = {}

    def cancel() -> bool:
        if "at" not in latched and scene.record.exists():
            latched["at"] = time.monotonic()
        return "at" in latched

    _settled(scene.bounded(lambda: host.synthesize(REQUEST, cancel_check=cancel, folder=scene.dir), PROMPT_S),
             ConversionCancelled, within=PROMPT_S)
    assert time.monotonic() - latched["at"] <= LOCAL_ENGINE_STOP_S
    assert gone(scene.helper_id()) and gone(scene.worker_id())
    names = [e.name for e in host.history]
    assert names[-2:] == ["killed", "cancel-stopped"] and host.history[-2].detail["returncode"] == -signal.SIGKILL
    assert scene.sentinel_alive()


@POSIX_ONLY
def test_a_cancel_whose_group_end_is_not_confirmed_fails_the_file_instead(scene, monkeypatch):
    """A group the kernel did not confirm empty is never a clean Cancel: the file fails and says why (the group is
    really ended here; only the answer is withheld, as when a member outlasts the bound)."""
    host = scene.host("detached", "block")
    host.load({"lang_code": "a"})
    real = co.end_led_group

    def unconfirmed(proc, start_time, **kwargs):
        real(proc, start_time, **kwargs)
        return co.GROUP_REMAINING

    monkeypatch.setattr(co, "end_led_group", unconfirmed)
    error = _settled(scene.bounded(lambda: host.synthesize(REQUEST, cancel_check=scene.record.exists,
                                                           folder=scene.dir), PROMPT_S),
                     hosts.LocalEngineFailed, within=PROMPT_S)
    assert "asked to stop, but it could not be confirmed stopped" in str(error)
    assert host.last_end.group == co.GROUP_REMAINING
    assert any("could not be confirmed stopped" in line for line in scene.logs), "said in the run's log too"
    assert scene.sentinel_alive()


@POSIX_ONLY
def test_output_held_by_an_escapee_is_reported_not_waited_for(scene):
    """The documented limit: a helper that leaves the group (``setsid``) is not reached by a group end. Holding the
    worker's stderr it once hung the host; now the end returns within its bounds and reports the open output."""
    host = scene.host("escapee", "crash")
    host.load({"lang_code": "a"})
    error = _settled(scene.bounded(lambda: host.synthesize(REQUEST, folder=scene.dir), PROMPT_S),
                     hosts.LocalEngineFailed, within=PROMPT_S)
    assert "could not be confirmed stopped" in str(error) and "output was still held open" in str(error)
    assert host.last_end.output_open
    assert running(scene.helper_id()), "an escapee is outside the group: reported, never signalled by a guess"
    assert scene.sentinel_alive()


@POSIX_ONLY
def test_two_ends_at_once_retire_the_worker_once(scene):
    """A run's own end and a Cancel hook meeting on the same worker: one retires it (group ended, then reaped), the
    other finds nothing left to end; neither raises, nothing else is signalled."""
    for _round in range(3):
        scene.record.unlink(missing_ok=True)
        host = scene.host("detached", "block")
        host.load({"lang_code": "a"})
        def serve(host=host) -> None:  # the request in flight sees its worker die under it: that is its failure
            with contextlib.suppress(hosts.LocalEngineFailed):
                host.synthesize(REQUEST, cancel_check=lambda: False, folder=scene.dir)

        threading.Thread(target=serve, daemon=True).start()
        helper = scene.helper_id()
        barrier = threading.Barrier(2)
        results: list = []

        def end() -> None:
            barrier.wait()
            results.append(host._end("race"))

        threads = [threading.Thread(target=end) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(PROMPT_S)
        retired = [r for _s, r in results if r is not None]
        assert len(results) == 2 and len(retired) == 1, results
        assert retired[0].group == co.GROUP_ENDED and retired[0].problem() is None
        assert gone(helper) and host._proc is None
    assert scene.sentinel_alive()


# --------------------------------------------------------------------------- #
#  The OmniVoice worker (tts.omnivoice_synth.run_worker)
# --------------------------------------------------------------------------- #
@POSIX_ONLY
@pytest.mark.parametrize("held", ["detached", "inherit"])
def test_an_omnivoice_worker_that_finishes_takes_its_helper_with_it(scene, held):
    """``done`` and exit 0. Before: success with the helper still running; holding the worker's output it cost 20 + 10
    + 10 s and leaked the reader. Now: success at once, nothing left."""
    run = _settled(scene.bounded(lambda: scene.omnivoice(held, "done"), PROMPT_S), None, within=PROMPT_S)
    assert run.terminal["event"] == "done" and run.returncode == 0 and len(run.chunk_events) == 2
    assert gone(scene.helper_id()) and gone(scene.worker_id())
    assert scene.sentinel_alive()


@POSIX_ONLY
@pytest.mark.parametrize("held", ["detached", "inherit"])
def test_an_omnivoice_cancel_the_worker_obeys_ends_its_helper_within_the_bound(scene, held):
    """The worker obeys the flag and exits 130. Before: a "clean" Cancel with the helper still running -- 22 s after
    the latch when it held the output (bound 4 s). Now: within the bound, nothing left."""
    _settled(scene.bounded(lambda: scene.omnivoice(held, "cancel", cancel_when_ready=True), PROMPT_S + 4),
             ConversionCancelled, within=PROMPT_S + 4)
    assert time.monotonic() - scene.latched_at <= OMNIVOICE_STOP_S
    assert gone(scene.helper_id()) and gone(scene.worker_id())
    assert scene.sentinel_alive()


@POSIX_ONLY
def test_a_stubborn_omnivoice_worker_and_its_helper_end_within_the_bound(scene):
    """Control (it held before P5-D too): a worker that ignores the flag and SIGTERM is ended with its group after
    the released 2 s grace."""
    _settled(scene.bounded(lambda: scene.omnivoice("detached", "stubborn", cancel_when_ready=True,
                                                   grace_s=osy.CANCEL_GRACE_S), PROMPT_S + 4),
             ConversionCancelled, within=PROMPT_S + 4)
    assert time.monotonic() - scene.latched_at <= OMNIVOICE_STOP_S
    assert gone(scene.helper_id()) and gone(scene.worker_id())
    with pytest.raises(ProcessLookupError):
        os.killpg(scene.helper()["worker_pgid"], 0)
    assert scene.sentinel_alive()


@POSIX_ONLY
@pytest.mark.parametrize("held", ["detached", "inherit"])
def test_an_omnivoice_worker_that_crashes_fails_at_once_and_takes_its_helper(scene, held):
    """Exit 3 with no result. Before: the helper ran on; holding the output, the run waited for the event timeout (60 s
    here, 900 s in production). Now: "ended unexpectedly" at once, nothing left."""
    error = _settled(scene.bounded(lambda: scene.omnivoice(held, "crash", event_timeout_s=60.0), PROMPT_S),
                     osy.OmniVoiceFailed, within=PROMPT_S)
    assert "ended unexpectedly (exit code 3)" in str(error)
    assert gone(scene.helper_id())
    assert scene.sentinel_alive()


@POSIX_ONLY
@pytest.mark.parametrize("then, cancel", [("done", False), ("cancel", True)])
def test_an_omnivoice_group_end_not_confirmed_is_never_success_or_a_clean_cancel(scene, monkeypatch, then, cancel):
    real = co.end_led_group

    def unconfirmed(proc, start_time, **kwargs):
        real(proc, start_time, **kwargs)
        return co.GROUP_REMAINING

    monkeypatch.setattr(co, "end_led_group", unconfirmed)
    error = _settled(scene.bounded(lambda: scene.omnivoice("detached", then, cancel_when_ready=cancel), PROMPT_S + 4),
                     osy.OmniVoiceFailed, within=PROMPT_S + 4)
    expected = "asked to stop, but it could not be confirmed stopped" if cancel else "its audio was discarded"
    assert expected in str(error) and "had not ended in time" in str(error), str(error)
    assert scene.sentinel_alive()


@POSIX_ONLY
def test_omnivoice_output_held_by_an_escapee_is_reported_within_the_bound(scene):
    """An escapee (``setsid``) holding the worker's output: its group's end cannot reach it, so the run is a failure
    that says so -- promptly, never a success after waiting on it."""
    error = _settled(scene.bounded(lambda: scene.omnivoice("escapee", "done"), PROMPT_S + 2),
                     osy.OmniVoiceFailed, within=PROMPT_S + 2)
    assert "could not be confirmed stopped" in str(error) and "output was still held open" in str(error)
    assert running(scene.helper_id()), "outside the group: reported, never signalled by a guess"
    assert scene.sentinel_alive()


@POSIX_ONLY
def test_under_the_app_windows_owner_the_omnivoice_worker_is_retired_the_same_way(scene, fresh_containment_owner):
    """The app window's own owner (``qwen3_process.spawn`` finds it): the identity it recorded is the one used."""
    from shared import subprocess_utils

    owner = subprocess_utils.enable_containment()
    seen: list = []

    def spawn(cmd, **kwargs):
        proc = qwen3_process.spawn(cmd, require_job=True, **kwargs)
        seen.append((proc, owner.child(proc)))
        return proc

    run = _settled(scene.bounded(lambda: scene.omnivoice("inherit", "done", spawn=spawn), PROMPT_S), None,
                   within=PROMPT_S)
    proc, child = seen[0]
    assert run.terminal["event"] == "done" and child is not None and child.kind == co.CLASS_A
    assert proc.act_start_time == child.start_time and proc.act_group_end == co.GROUP_ENDED
    assert gone(scene.helper_id())
    assert scene.sentinel_alive()


# --------------------------------------------------------------------------- #
#  qwen3_process.kill_tree on POSIX (the twins of test_qwen3_process.py's Windows-only tree tests)
# --------------------------------------------------------------------------- #
PARENT_THEN_CHILD = (
    "import json, os, subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(300)'], {stdio})\n"
    "sys.path.insert(0, sys.argv[2])\n"
    "from shared.child_ownership import process_start_time\n"
    "open(sys.argv[1], 'w').write(json.dumps([child.pid, process_start_time(child.pid)]))\n"
    "{tail}")


def _child_of(scene, marker: Path) -> tuple:
    deadline = time.monotonic() + 30
    while not (marker.exists() and marker.read_text()):
        assert time.monotonic() < deadline, "the parent never recorded its child"
        time.sleep(0.02)
    pid, start = json.loads(marker.read_text())
    scene.extra.append((pid, tuple(start)))
    return (pid, tuple(start))


@POSIX_ONLY
def test_kill_tree_still_reaches_a_child_whose_parent_already_exited(scene):
    """``kill_tree``'s own promise -- "whether or not the process itself is still running" -- held only on Windows:
    on POSIX it polled first, reaping the exited parent and losing its group's proof. Now it ends that group."""
    marker = scene.dir / "child.json"
    script = PARENT_THEN_CHILD.format(stdio="stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL", tail="")
    proc = qwen3_process.spawn([sys.executable, "-I", "-c", script, str(marker), str(SCRIPTS)])
    child = _child_of(scene, marker)
    assert co.wait_exited(proc, PROMPT_S) and proc.returncode is None
    qwen3_process.kill_tree(proc)
    assert gone(child), "the child it left in its group ended with the tree"
    assert proc.act_group_end == co.GROUP_ENDED and proc.returncode == 0
    assert scene.sentinel_alive()


@POSIX_ONLY
def test_the_pipe_reaches_eof_once_the_whole_tree_is_killed(scene):
    marker = scene.dir / "child.json"
    script = PARENT_THEN_CHILD.format(stdio="", tail="print('parent done', flush=True)\n")
    proc = qwen3_process.spawn([sys.executable, "-I", "-c", script, str(marker), str(SCRIPTS)],
                               stdout=subprocess.PIPE, text=True)
    child = _child_of(scene, marker)
    assert proc.stdout.readline().strip() == "parent done"
    assert co.wait_exited(proc, PROMPT_S)
    qwen3_process.kill_tree(proc)
    outcome = scene.bounded(proc.stdout.read, PROMPT_S)
    assert outcome == ("returned", ""), "end of file once nothing of the tree holds the pipe"
    assert gone(child)
    proc.stdout.close()
    assert scene.sentinel_alive()


@POSIX_ONLY
def test_kill_tree_signals_no_group_it_cannot_prove(scene):
    """Identity control: a recorded start time that no longer matches (as if the id had been handed on) gets no signal
    at all -- the process runs on, untouched; and a process already reaped is never signalled again."""
    proc = qwen3_process.spawn([sys.executable, "-I", "-c", "import time; time.sleep(300)"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    real = getattr(proc, "act_start_time", None) or co.process_start_time(proc.pid)
    scene.extra.append((proc.pid, real))
    proc.act_start_time = (real[0] - 1, real[1])
    qwen3_process.kill_tree(proc, wait_s=0.5)
    assert running((proc.pid, real)) and proc.returncode is None, "never signalled on an unproved identity"
    assert proc.act_group_end == co.GROUP_UNPROVED
    proc.act_start_time = real
    qwen3_process.kill_tree(proc)
    assert proc.act_group_end == co.GROUP_ENDED and not running((proc.pid, real))
    qwen3_process.kill_tree(proc)  # reaped already: nothing is signalled, the earlier answer stands
    assert proc.act_group_end == co.GROUP_ENDED
    assert scene.sentinel_alive()


# --------------------------------------------------------------------------- #
#  Every platform: Windows keeps its paths
# --------------------------------------------------------------------------- #
def test_kill_tree_keeps_its_windows_paths(monkeypatch):
    """On Windows a job is terminated, and without one ``taskkill /T`` runs while the process lives -- exactly as
    released; no group identity is consulted there, even if one were present."""
    monkeypatch.setattr(qwen3_process.sys, "platform", "win32")
    calls: list = []

    class Proc:
        pid = 4242
        returncode = None

        def __init__(self, job=None):
            self.act_job = job
            self.act_start_time = (1, 2)

        def poll(self):
            calls.append("poll")
            return None

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return 1

    job = types.SimpleNamespace(terminate=lambda: calls.append("terminate"))
    qwen3_process.kill_tree(Proc(job))
    assert calls == ["terminate", ("wait", 15.0)]
    calls.clear()
    monkeypatch.setattr(qwen3_process.subprocess_utils, "run", lambda argv, **kw: calls.append(list(argv)))
    proc = Proc()
    qwen3_process.kill_tree(proc, wait_s=3)
    assert calls == ["poll", ["taskkill", "/PID", "4242", "/T", "/F"], ("wait", 3)]
    assert not hasattr(proc, "act_group_end")


def test_a_worker_without_a_proved_group_keeps_the_released_supervision(tmp_path, monkeypatch):
    """Every platform: a worker that does not lead a group with a recorded identity (Windows; any injected spawn) is
    supervised exactly as released -- end of output, then ``poll``/``wait`` -- and its success is its own."""
    (tmp_path / "ov_stand_in.py").write_text(OMNIVOICE_STAND_IN, encoding="utf-8")
    monkeypatch.setenv("P5D_PLAN", json.dumps({"then": "done"}))
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    job = {"cancel_file": str(job_dir / "cancel"), "out_dir": str(job_dir / "chunks"),
           "chunks": [{"index": 0, "text": "One.", "seed": 1}]}
    started: list = []

    def plain(cmd, **kwargs):
        proc = subprocess.Popen(cmd, **kwargs)
        proc.act_job = None
        started.append(proc)
        return proc

    run = osy.run_worker(job, job_dir, name="job-001", python=Path(sys.executable),
                         script=tmp_path / "ov_stand_in.py", env=dict(os.environ), log=lambda _s: None, spawn=plain)
    assert run.terminal["event"] == "done" and run.returncode == 0 and started[0].returncode == 0
    assert not hasattr(started[0], "act_start_time") and not hasattr(started[0], "act_group_end")
