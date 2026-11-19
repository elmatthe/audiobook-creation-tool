"""v0.8.x P5-I: the POSIX containment lifecycle redesigned (one ledger, spawn admission apart from the registry lock, one
guardian state protocol, one shared retirement deadline, failure reaching the outcome first).

Deterministic negative controls for the ten findings of Codex re-review 5 at ``6c3e3e7`` (three HIGH, seven MEDIUM) and the
cases the P5-I drop names, plus positive controls. Each control synchronises on events and barriers (never a sleep as an
assertion), times with ``time.monotonic()``, and judges by the process table -- every process a test creates is
recorded at its spawn and checked with ``poll()``/``returncode`` -- and by the owner's ledger, not only by what was raised.
Faults are injected where the owner signals (``child_ownership.signal_if_same``: a SIGKILL that does not take), where it
reaps (a ``poll`` that raises), where it registers (``Owner._register``), and at the spawn itself (a ``Popen`` held on a
barrier). macOS only: the containment owner is the Mac's.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from shared import child_ownership, subprocess_utils
from shared.cancellation import ConversionCancelled
from shared.job_control import JobController
from tts import ffmpeg_watch

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="POSIX containment is the Mac's")

STUBBORN = ("import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); "
            "time.sleep(60)")
SLEEP = "import time; time.sleep(60)"
REAL_POPEN = subprocess.Popen
REAL_SIGNAL = child_ownership.signal_if_same


def _caller() -> str:
    """The thread a start was asked from (v0.8.x P5-I-R3: a contained start runs on ``act-launch:<caller>``)."""
    return threading.current_thread().name.removeprefix("act-launch:")


def _wait_for(predicate, seconds=10.0, step=0.01) -> bool:
    stop = time.monotonic() + seconds
    while time.monotonic() < stop:
        if predicate():
            return True
        time.sleep(step)
    return bool(predicate())


class Spawns:
    """Every process this test creates (the process table's oracle), with the thread that created it."""

    def __init__(self, monkeypatch):
        self.all: list[subprocess.Popen] = []
        self.hooks = []
        self.after = []  # v0.8.x P5-I-R3: called with each created process (class-B gates are created through this)
        monkeypatch.setattr(subprocess, "Popen", self._popen)

    def _popen(self, cmd, *args, **kwargs):
        for hook in list(self.hooks):
            hook(cmd)
        proc = REAL_POPEN(cmd, *args, **kwargs)
        proc.act_thread = threading.current_thread().name.removeprefix("act-launch:")  # P5-I-R3 launch thread
        self.all.append(proc)
        for hook in list(self.after):
            hook(proc)
        return proc

    def guardians(self):
        return [p for p in self.all if str(child_ownership.GUARDIAN) in [str(a) for a in p.args]]

    def live(self):
        return [p for p in self.all if p.poll() is None]


@pytest.fixture()
def spawns(monkeypatch):
    record = Spawns(monkeypatch)
    yield record
    leftovers = []
    for proc in record.all:
        if proc.poll() is None:
            leftovers.append(proc.pid)
            with contextlib.suppress(OSError):
                os.kill(proc.pid, signal.SIGCONT)
                REAL_POPEN.kill(proc)
            with contextlib.suppress(Exception):
                proc.wait(5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()
    assert leftovers == [], f"processes this test created were still running at its end: {leftovers}"


@pytest.fixture()
def owner(monkeypatch, spawns):
    made = child_ownership.Owner(lifeline=False)
    monkeypatch.setattr(subprocess_utils, "_owner", made)
    yield made
    made.shutdown()


@pytest.fixture()
def ff(tmp_path):
    """A program the owner contains as class B (its name is ``ffmpeg``) that is really this Python: children whose
    behaviour each test chooses (one that ignores SIGTERM, one that exits on cue)."""
    link = tmp_path / "bin" / "ffmpeg"
    link.parent.mkdir()
    link.symlink_to(sys.executable)
    return str(link)


def refuse_sigkill(monkeypatch, pids: set):
    """Fault: the owner's SIGKILL to these pids does not take (``signal_if_same`` answers as if refused)."""
    def signal_if_same(pid, start_time, sig, **kw):
        if pid in pids and sig == signal.SIGKILL:
            return False
        return REAL_SIGNAL(pid, start_time, sig, **kw)

    monkeypatch.setattr(child_ownership, "signal_if_same", signal_if_same)


def run_in_thread(fn, name):
    box: dict = {}

    def body():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - the test reads it
            box["error"] = exc
        box["ended_at"] = time.monotonic()

    thread = threading.Thread(target=body, name=name, daemon=True)
    thread.start()
    return thread, box


def start_media(controller, argv, **kwargs):
    with ffmpeg_watch.controlled(controller.cancel_check):
        child = ffmpeg_watch.Supervised(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        try:
            return child.communicate()
        finally:
            child.abandon()


def stubborn_children(owner, ff, count, **kwargs):
    kids = [owner.popen_external([ff, "-B", "-c", STUBBORN], stdout=subprocess.PIPE, **kwargs) for _ in range(count)]
    for kid in kids:
        assert kid.stdout.readline() == b"ready\n"
    return kids


def kill_guardian_unreaped(owner):
    """The guardian dies (killed by hand); nobody but the owner reaps it."""
    guardian = owner._guardian
    os.kill(guardian.pid, signal.SIGKILL)
    assert _wait_for(lambda: child_ownership.has_exited(guardian), 5)
    return guardian


# =========================================================================== HIGH 1: lost generation, shared deadline


@pytest.mark.parametrize("whose", ["another-runs", "the-cancelled-runs"])
def test_h1_five_term_ignoring_children_of_a_lost_guardian_never_hold_the_run_past_c2(owner, ff, monkeypatch, whose):
    """Codex re-review 5 HIGH 1: a conversion that itself saw the guardian lost retired its five SIGTERM-ignoring children
    one after another, a 1 s grace each, on its own thread, and settled at 5.1 s (C2: 4 s). Now the loss is recorded --
    all five marked before any is ended -- and handed to the owner's retirement under one shared deadline; the
    conversion goes on at once. When the five are the cancelled run's own, its settlement waits for them, once."""
    monkeypatch.setattr(child_ownership.Owner, "_watch_guardian", lambda self, proc, generation: None)  # A sees it first
    controller = JobController("p5i-h1")
    controller.start()
    owner.ensure_guardian()
    tag = {"owner_run": controller.cancel_check} if whose == "the-cancelled-runs" else {}
    kids = stubborn_children(owner, ff, 5, **tag)
    noticed, cancelled = threading.Event(), threading.Event()
    seen = {}
    real_lost = owner._guardian_lost

    def lost(proc, generation):
        real_lost(proc, generation)
        if _caller() == "A" and not noticed.is_set():
            seen["flags"] = [owner.child(k).lost_containment for k in kids]
            seen["alive"] = [k.poll() is None for k in kids]
            seen["at"] = time.monotonic()
            noticed.set()
            assert cancelled.wait(5)

    monkeypatch.setattr(owner, "_guardian_lost", lost)
    kill_guardian_unreaped(owner)
    a, outcome = run_in_thread(lambda: start_media(controller, [ff, "-B", "-c", "pass"]), "A")
    assert noticed.wait(10)
    began = time.monotonic()
    controller.request_cancel()
    latched_in = time.monotonic() - began
    ffmpeg_watch.wake()
    cancelled.set()
    a.join(10)
    stuck = ffmpeg_watch.settle_children(controller.cancel_check)
    settled_in = time.monotonic() - began
    assert latched_in < 0.5, f"C1: {latched_in:.3f} s"
    assert isinstance(outcome.get("error"), ConversionCancelled), outcome
    assert seen["flags"] == [True] * 5 and seen["alive"] == [True] * 5, "all marked lost before any was ended"
    assert stuck == [] and settled_in < 4.0, f"C2: settled in {settled_in:.3f} s, unconfirmed {stuck}"
    if whose == "the-cancelled-runs":
        assert all(k.returncode is not None for k in kids), "the run's own children were confirmed ended before it settled"
    bound = child_ownership.TERM_GRACE_S + child_ownership.KILL_CONFIRM_S + 0.5
    assert _wait_for(lambda: all(k.returncode is not None for k in kids), bound), "one shared deadline, not five"
    assert [k.returncode for k in kids] == [-signal.SIGKILL] * 5
    assert time.monotonic() - seen["at"] < bound + 0.5
    assert owner.outstanding() == [] or all(e.kind == child_ownership.GUARDIAN_KIND for e in owner.outstanding())


# =========================================================================== HIGH 2: spawn admission apart from the lock


@pytest.mark.parametrize("blocked", ["setup-run-external", "class-a-popen-python"])
def test_h2_a_blocked_spawn_holds_neither_the_registry_nor_another_runs_start_nor_its_cancel(owner, ff, spawns,
                                                                                           monkeypatch, blocked):
    """Codex re-review 5 HIGH 2: the owner's lock was held across a synchronous ``Popen`` and registration, so a setup
    spawn paused there delayed a conversion's counted start and its Cancel latch to 0.57 s (C1: 0.5 s). The registry lock
    is now never held across a spawn: with the setup spawn held, the registry still answers at once, the conversion's
    child is created, and its Cancel latches inside C1."""
    owner.ensure_guardian()
    controller = JobController("p5i-h2")
    controller.start()
    held, release = threading.Event(), threading.Event()

    def hold_setup(cmd):
        if _caller() == "setup":
            held.set()
            assert release.wait(10)

    spawns.hooks.append(hold_setup)
    if blocked == "setup-run-external":
        setup = lambda: owner.run_external([ff, "-B", "-c", "print('setup-ok')"], timeout=10)  # noqa: E731
    else:
        setup = lambda: owner.run_python([sys.executable, "-c", "print('setup-ok')"], capture_output=True,  # noqa: E731
                                         text=True, timeout=10)
    b, b_out = run_in_thread(setup, "setup")
    try:
        assert held.wait(10)
        answered, ans = run_in_thread(lambda: (owner.children(), owner.outstanding(), owner.child(object())), "reader")
        answered.join(0.2)
        assert not answered.is_alive(), "the ledger answered while a spawn was held"
        a, a_out = run_in_thread(lambda: start_media(controller, [ff, "-B", "-c", SLEEP]), "A")
        assert _wait_for(lambda: any(p.act_thread == "A" for p in spawns.all), 5), "A's child was created meanwhile"
        began = time.monotonic()
        controller.request_cancel()
        latched_in = time.monotonic() - began
        ffmpeg_watch.wake()
        a.join(10)
        assert latched_in < 0.5 and controller.cancel_check(), f"C1: {latched_in:.3f} s"
        assert isinstance(a_out.get("error"), ConversionCancelled), a_out
        assert b.is_alive(), "the setup spawn was still held throughout"
    finally:
        release.set()
        b.join(10)
    assert b_out["value"].returncode == 0 and "setup-ok" in b_out["value"].stdout
    assert ffmpeg_watch.settle_children(controller.cancel_check) == []


def test_h2_a_runs_own_spawn_held_in_popen_never_holds_its_cancel_and_its_late_child_is_stopped(owner, ff, spawns):
    """The run's own spawn held inside ``Popen`` (a slow or blocked fork/exec). Only the start's admission is ordered
    against Cancel, so the latch lands inside C1 regardless. The process that the held spawn then creates -- admitted
    before the latch -- is stopped at once, is the run's in the owner's ledger, and the run settles with nothing owed."""
    owner.ensure_guardian()
    controller = JobController("p5i-h2-own")
    controller.start()
    held, release = threading.Event(), threading.Event()

    def hold(cmd):
        if cmd and ff in [str(a) for a in cmd] and _caller() == "A":
            held.set()
            assert release.wait(10)

    spawns.hooks.append(hold)
    a, out = run_in_thread(lambda: start_media(controller, [ff, "-B", "-c", SLEEP]), "A")
    assert held.wait(10)
    entry = next(e for e in owner.outstanding(controller.cancel_check) if e.kind == child_ownership.CLASS_B)
    assert entry.state == child_ownership.SPAWNING, "admitted, in the ledger, under its run, before it exists"
    began = time.monotonic()
    controller.request_cancel()
    latched_in = time.monotonic() - began
    release.set()
    a.join(10)
    assert latched_in < 0.5, f"C1: {latched_in:.3f} s"
    assert isinstance(out.get("error"), ConversionCancelled), out
    late = [p for p in spawns.all if p.act_thread == "A" and p not in spawns.guardians()]
    # P5-I-R3: what the held spawn created is the inert launch gate; its launch thread refuses to let it run (its caller
    # left at the Cancel) and retires it -- asynchronously, so it is waited for, bounded.
    assert len(late) == 1 and _wait_for(lambda: late[0].returncode is not None, 2), "created after the latch, stopped"
    assert ffmpeg_watch.settle_children(controller.cancel_check) == [] and owner.outstanding(controller.cancel_check) == []


def test_h2_a_cancel_latched_between_gate_creation_and_grant_runs_nothing(owner, ff, spawns, monkeypatch, tmp_path):
    """v0.8.x P5-I-R3 (was: between admission and spawn). A Cancel that latches after the launch gate exists and before
    it is allowed to run: the counted start refuses, the gate -- which never executed anything -- is retired, nothing
    of the program runs, and the run owes nothing."""
    owner.ensure_guardian()
    controller = JobController("p5i-h2-gap")
    controller.start()
    marker = tmp_path / "ran"
    real = owner._grant

    def grant(launch):
        controller.request_cancel()  # not inside a counted start: the latch does not wait for this one
        return real(launch)

    monkeypatch.setattr(owner, "_grant", grant)
    with pytest.raises(ConversionCancelled):
        start_media(controller, [ff, "-B", "-c", f"open({str(marker)!r}, 'w').close()"])
    gates = [p for p in spawns.all if p not in spawns.guardians()]
    assert gates, "the launch gate was created (the Cancel came after it)"
    assert _wait_for(lambda: all(p.returncode is not None for p in gates), 3), "the inert gate was retired"
    assert not marker.exists(), "nothing of the program ran"
    assert ffmpeg_watch.settle_children(controller.cancel_check) == []
    assert owner.outstanding(controller.cancel_check) == [] and not ffmpeg_watch._watched


# =========================================================================== HIGH 3: failed registration, honest settlement


def test_h3_a_failed_registration_with_an_ineffective_kill_is_never_a_clean_settlement(owner, ff, spawns, monkeypatch):
    """Codex re-review 5 HIGH 3: with ``Owner._register`` failing and the kill ineffective, the run settled CANCELLED in
    0.054 s with the encoder alive and outside what settlement asked (``unconfirmed_children() == []``). The child now
    stays in the owner's ledger under its run, settlement retires and waits for it (bounded by its own deadline), and
    reports it unconfirmed; once the kill takes it is reaped and the next settlement is clean."""
    owner.ensure_guardian()
    controller = JobController("p5i-h3")
    controller.start()
    refused: set = set()
    refuse_sigkill(monkeypatch, refused)
    monkeypatch.setattr(owner, "_register", lambda *a, **k: (_ for _ in ()).throw(MemoryError("injected")))
    spawns.after.append(lambda proc: refused.add(proc.pid) if proc not in spawns.guardians() else None)
    began = time.monotonic()
    with pytest.raises(MemoryError):
        start_media(controller, [ff, "-B", "-c", SLEEP])
    caller_held = time.monotonic() - began
    encoder = [p for p in spawns.all if p not in spawns.guardians()][0]
    controller.request_cancel()
    settle_began = time.monotonic()
    stuck = ffmpeg_watch.settle_children(controller.cancel_check)
    settled_in = time.monotonic() - settle_began
    assert caller_held < 0.5, f"the caller was held {caller_held:.3f} s"
    assert stuck == [encoder.pid], f"settlement must name the live encoder, got {stuck}"
    assert encoder.poll() is None, "it really is still running (the kill did not take)"
    # P5-I-R3 remediation 6: the settlement keeps ending it for its whole bound (from the click), never past it.
    assert settled_in <= child_ownership.SETTLE_BOUND_S + 0.1, settled_in
    entry = owner.child(encoder)
    assert entry is not None and entry.state == child_ownership.UNCONFIRMED and entry.run == controller.cancel_check
    refused.clear()
    assert _wait_for(lambda: encoder.returncode is not None, 5), "reaped once the kill took"
    assert owner.child(encoder) is None and ffmpeg_watch.settle_children(controller.cancel_check) == []


def test_h3_a_failed_registration_whose_kill_takes_settles_cleanly_and_quickly(owner, ff, spawns, monkeypatch):
    """The positive side of HIGH 3: the same failure with an effective kill is retired and confirmed at once."""
    owner.ensure_guardian()
    controller = JobController("p5i-h3-ok")
    controller.start()
    monkeypatch.setattr(owner, "_register", lambda *a, **k: (_ for _ in ()).throw(MemoryError("injected")))
    with pytest.raises(MemoryError):
        start_media(controller, [ff, "-B", "-c", SLEEP])
    encoder = [p for p in spawns.all if p not in spawns.guardians()][0]
    assert ffmpeg_watch.settle_children(controller.cancel_check) == []
    assert encoder.returncode == -signal.SIGKILL and owner.child(encoder) is None


# =========================================================================== MEDIUM 1: closing vs spawn and adoption


@pytest.mark.parametrize("latch", ["begin_closing", "shutdown"])
def test_m1_closing_during_a_guardian_spawn_admits_nothing_after_it_and_retires_the_late_guardian(owner, spawns, latch):
    """Codex re-review 5 MEDIUM 1: a creator paused after its last closing check spawned a real guardian after
    ``begin_closing()`` returned, and one after ``shutdown()`` returned. Admission and the closing latch are now one
    decision under the owner's lock: the creator was admitted before the latch, so its spawn is in flight; the latch waits
    for it only briefly, and once its guardian exists it is never adopted and is retired at once. Nothing is admitted
    after the latch."""
    held, release = threading.Event(), threading.Event()

    def hold_guardian(cmd):
        if str(child_ownership.GUARDIAN) in [str(a) for a in cmd] and _caller() == "creator":
            held.set()
            assert release.wait(10)

    spawns.hooks.append(hold_guardian)
    creator, out = run_in_thread(owner.ensure_guardian, "creator")
    assert held.wait(10)
    began = time.monotonic()
    result = getattr(owner, latch)()
    took = time.monotonic() - began
    bound = child_ownership.START_SETTLE_S + 0.2 if latch == "begin_closing" else child_ownership.SHUTDOWN_BOUND_S + 0.3
    assert took < bound, f"{latch} took {took:.3f} s"
    with pytest.raises(child_ownership.ContainmentUnavailable, match="closing"):
        owner.popen_external([sys.executable, "-c", "pass"])  # nothing is admitted after the latch
    release.set()
    creator.join(10)
    assert isinstance(out.get("error"), child_ownership.ContainmentUnavailable), out
    guardians = spawns.guardians()
    assert len(guardians) == 1, "exactly the guardian admitted before the latch"
    assert _wait_for(lambda: guardians[0].returncode is not None, 2), "retired at once, never adopted"
    assert owner._current is None and owner.guardian_pid() is None
    assert owner.outstanding() == []
    if latch == "shutdown":
        assert result == [], result


def test_m1_closing_while_a_guardian_is_being_adopted_refuses_the_adoption(owner, spawns, monkeypatch):
    """The adoption window of MEDIUM 1: paused after ``ready`` and before adoption, closing began; the guardian was then
    adopted and generation 1 returned. Adoption is now decided under the same lock as closing: refused, retired."""
    at, release = threading.Event(), threading.Event()
    born = child_ownership.process_start_time

    def birth(pid):
        pending = owner._pending_guardian
        if _caller() == "creator" and pending is not None and pending.pid == pid and not at.is_set():
            at.set()
            assert release.wait(10)
        return born(pid)

    monkeypatch.setattr(child_ownership, "process_start_time", birth)
    creator, out = run_in_thread(owner.ensure_guardian, "creator")
    assert at.wait(10)
    owner.begin_closing()
    release.set()
    creator.join(10)
    assert isinstance(out.get("error"), child_ownership.ContainmentUnavailable) and "closing" in str(out["error"])
    assert _wait_for(lambda: spawns.guardians()[0].returncode is not None, 2)
    assert owner._current is None and owner.outstanding() == []


def test_m1_shutdown_during_guardian_readiness_returns_with_nothing_left(owner, spawns):
    """A guardian stalled before ``ready`` (stopped): the orderly end retires it and returns with nothing unconfirmed."""
    creator, out = run_in_thread(owner.ensure_guardian, "creator")
    assert _wait_for(lambda: spawns.guardians(), 5)
    os.kill(spawns.guardians()[0].pid, signal.SIGSTOP)
    began = time.monotonic()
    result = owner.shutdown()
    took = time.monotonic() - began
    creator.join(10)
    assert result == [] and took < child_ownership.SHUTDOWN_BOUND_S, (result, took)
    assert isinstance(out.get("error"), child_ownership.ContainmentUnavailable), out
    assert spawns.guardians()[0].returncode is not None and owner.outstanding() == []


# =========================================================================== MEDIUM 2: shutdown's one deadline


def test_m2_shutdown_holds_its_bound_when_kills_do_not_take_and_reports_what_it_could_not_end(monkeypatch, spawns):
    """Codex re-review 5 MEDIUM 2: four children ignoring SIGTERM whose SIGKILL did not take kept ``shutdown()`` for
    9.55 s (bound 5 s). Every wait is now measured against one deadline: shutdown returns within its bound and names the
    children it could not confirm ended; they stay owned and are reaped once the kill takes. (Class A without a
    lifeline, so neither the guardian nor a lifeline can end them behind the test's back.)"""
    owner = child_ownership.Owner(lifeline=False)
    refused: set = set()
    refuse_sigkill(monkeypatch, refused)
    kids = [owner.popen_python([sys.executable, "-B", "-c", STUBBORN], stdout=subprocess.PIPE) for _ in range(4)]
    for kid in kids:
        assert kid.stdout.readline() == b"ready\n"
        refused.add(kid.pid)
    began = time.monotonic()
    result = owner.shutdown()
    took = time.monotonic() - began
    try:
        assert took <= child_ownership.SHUTDOWN_BOUND_S + 0.3, f"shutdown took {took:.3f} s"
        assert result == sorted(k.pid for k in kids), result
        assert all(k.poll() is None for k in kids), "they really are still running"
        assert {e.proc for e in owner.unconfirmed()} == set(kids), "still owned"
        assert any("could not confirm" in e for e in owner.events)
    finally:
        refused.clear()
    assert _wait_for(lambda: all(k.returncode is not None for k in kids), 5), "reaped once the kill took"
    assert owner.outstanding() == []


def test_m2_seven_unregistered_children_of_a_lost_guardian_do_not_stretch_shutdown(owner, ff, spawns, monkeypatch):
    """Codex re-review 5 MEDIUM 2 (stray path): seven live strays from a lost generation took shutdown to 5.22 s, each
    wait given at least 0.1 s past the deadline. All are now one batch under the one deadline."""
    owner.ensure_guardian()
    monkeypatch.setattr(owner, "_register", lambda *a, **k: (_ for _ in ()).throw(MemoryError("injected")))
    refused: set = set()
    refuse_sigkill(monkeypatch, refused)
    spawns.after.append(lambda proc: refused.add(proc.pid) if proc not in spawns.guardians() else None)
    for _ in range(7):
        with pytest.raises(MemoryError):
            owner.popen_external([ff, "-B", "-c", SLEEP])
    assert len(owner._strays) == 7
    kill_guardian_unreaped(owner)
    began = time.monotonic()
    owner.shutdown()
    took = time.monotonic() - began
    refused.clear()
    assert took <= child_ownership.SHUTDOWN_BOUND_S + 0.3, f"shutdown took {took:.3f} s"
    assert _wait_for(lambda: not spawns.live(), 5)


# =========================================================================== MEDIUM 3: a wait that fails proves nothing


def test_m3_a_reap_that_raises_never_drops_a_live_child(owner, ff, spawns, monkeypatch):
    """Codex re-review 5 MEDIUM 3: after a registration failure and an ineffective kill, an ``OSError`` in the stray
    reaper's wait removed the live child from every record. A failing wait or poll now proves nothing: the child stays in
    the ledger (unconfirmed once its deadline passes) until it is really reaped."""
    owner.ensure_guardian()
    monkeypatch.setattr(owner, "_register", lambda *a, **k: (_ for _ in ()).throw(MemoryError("injected")))
    refused: set = set()
    refuse_sigkill(monkeypatch, refused)
    faulty = {"on": True}
    def spawn(proc):
        if proc in spawns.guardians():
            return
        refused.add(proc.pid)
        real_poll, real_wait = proc.poll, proc.wait

        def poll():
            if faulty["on"] and _caller() == "act-owner-reaper":
                raise OSError("injected poll error")
            return real_poll()

        def wait(*a, **k):
            if faulty["on"] and _caller() == "act-owner-reaper":
                raise OSError("injected wait error")
            return real_wait(*a, **k)

        proc.poll, proc.wait = poll, wait

    spawns.after.append(spawn)
    with pytest.raises(MemoryError):
        owner.popen_external([ff, "-B", "-c", SLEEP])
    child = [p for p in spawns.all if p not in spawns.guardians()][0]
    assert _wait_for(lambda: [e.proc for e in owner.unconfirmed()] == [child], 5), "kept and reported, not dropped"
    assert child.returncode is None and REAL_POPEN.poll(child) is None, "live"
    refused.clear()  # the kill takes; the poll still fails: still owned
    assert _wait_for(lambda: child_ownership.has_exited(child), 5)
    assert owner.child(child) is not None, "a reap that failed did not drop it"
    faulty["on"] = False
    assert _wait_for(lambda: child.returncode is not None and owner.child(child) is None, 5)


# =========================================================================== MEDIUM 4: Cancel during adoption


def test_m4_a_cancel_during_provisional_adoption_leaves_no_guardian_running_for_the_cancelled_run(owner, ff, spawns,
                                                                                                monkeypatch):
    """Codex re-review 5 MEDIUM 4: Cancel latched while the conversion's new guardian was ready and not yet recorded; the
    conversion refused FFmpeg but then adopted that guardian after the latch and left it running. Adoption is now inside
    the run's Cancel ordering: refused, and the guardian -- the run's -- is retired before the run settles."""
    controller = JobController("p5i-m4")
    controller.start()
    at, release = threading.Event(), threading.Event()
    born = child_ownership.process_start_time

    def birth(pid):
        pending = owner._pending_guardian
        if _caller() == "A" and pending is not None and pending.pid == pid and not at.is_set():
            at.set()
            assert release.wait(10)
        return born(pid)

    monkeypatch.setattr(child_ownership, "process_start_time", birth)
    a, out = run_in_thread(lambda: start_media(controller, [ff, "-B", "-c", "pass"]), "A")
    assert at.wait(10)
    began = time.monotonic()
    controller.request_cancel()
    latched_in = time.monotonic() - began
    release.set()
    a.join(10)
    assert latched_in < 0.5
    assert isinstance(out.get("error"), ConversionCancelled), out
    assert ffmpeg_watch.settle_children(controller.cancel_check) == []
    guardians = spawns.guardians()
    assert len(guardians) == 1 and guardians[0].returncode is not None, "not adopted, ended and reaped"
    assert owner._current is None and [p for p in spawns.all if p not in guardians] == [], "no FFmpeg"


# =========================================================================== MEDIUM 5: identity before adoption


def test_m5_a_guardian_whose_identity_cannot_be_read_is_never_adopted_and_never_left_running(owner, spawns, monkeypatch):
    """Codex re-review 5 MEDIUM 5: a ``None`` birth identity let a live guardian be adopted; the next request then took it
    for lost and made a second one, and both ran. Identity is now required before adoption: that guardian is retired,
    the request fails honestly, and the next makes exactly one."""
    born = child_ownership.process_start_time
    once = {"left": 1}

    def birth(pid):
        pending = owner._pending_guardian
        if pending is not None and pending.pid == pid and once["left"]:
            once["left"] -= 1
            return None
        return born(pid)

    monkeypatch.setattr(child_ownership, "process_start_time", birth)
    with pytest.raises(child_ownership.ContainmentUnavailable, match="identity"):
        owner.ensure_guardian()
    first = spawns.guardians()[0]
    assert _wait_for(lambda: first.returncode is not None, 2), "retired, not adopted"
    owner.ensure_guardian()
    guardians = spawns.guardians()
    assert len(guardians) == 2 and [g.poll() is None for g in guardians] == [False, True], "exactly one guardian runs"
    assert owner.guardian_pid() == guardians[1].pid


# =========================================================================== MEDIUM 6: loss reaches setup's outcome first


ON_CUE = "import pathlib, sys, time\ngo = pathlib.Path(sys.argv[1])\nwhile not go.exists(): time.sleep(0.01)\nprint('done')"


def test_m6_a_setup_child_that_exits_normally_after_its_guardian_died_is_not_a_success(owner, ff, monkeypatch, tmp_path):
    """Codex re-review 5 MEDIUM 6: with the guardian dead, a setup child exited normally and ``run_external`` returned 0
    before the loss was recorded. Now the run's outcome looks at containment after the child has ended: the loss is
    recorded then (if nobody had yet) and the run is a failure."""
    monkeypatch.setattr(child_ownership.Owner, "_watch_guardian", lambda self, proc, generation: None)  # nobody else sees it
    owner.ensure_guardian()
    go = tmp_path / "go"
    b, out = run_in_thread(lambda: owner.run_external([ff, "-B", "-c", ON_CUE, str(go)], timeout=10), "setup")
    # P5-I-R3: a start is in the ledger from its gate's creation; the child is running once it is LIVE.
    assert _wait_for(lambda: [c for c in owner.children() if c.state == child_ownership.LIVE], 5)
    kill_guardian_unreaped(owner)
    assert not owner.degraded, "not recorded yet: nobody has looked"
    go.touch()
    b.join(10)
    result = out["value"]
    assert result.returncode != 0 and "lost containment" in result.stderr, result
    assert owner.degraded and any("ended on its own" in e for e in owner.events)


def test_m6_every_child_of_a_lost_guardian_is_marked_before_any_is_waited_for(owner, ff, tmp_path):
    """The reported interleaving: two children, the first ignoring SIGTERM, the second exiting normally during the
    first's grace. Every child is now marked lost at the moment the loss is recorded, so the second reports failure."""
    owner.ensure_guardian()
    stubborn = stubborn_children(owner, ff, 1)[0]
    go = tmp_path / "go"
    b, out = run_in_thread(lambda: owner.run_external([ff, "-B", "-c", ON_CUE, str(go)], timeout=10), "setup")
    assert _wait_for(lambda: len([c for c in owner.children() if c.state == child_ownership.LIVE]) == 2, 5)
    second = [c for c in owner.children() if c.proc is not stubborn][0]
    kill_guardian_unreaped(owner)
    assert _wait_for(lambda: owner.degraded, 5)
    assert owner.child(stubborn).lost_containment and second.lost_containment, "both marked at once"
    assert stubborn.poll() is None, "while the first is still in its grace"
    go.touch()
    b.join(10)
    assert out["value"].returncode != 0 and "lost containment" in out["value"].stderr
    assert _wait_for(lambda: stubborn.returncode == -signal.SIGKILL, 4)


# =========================================================================== MEDIUM 7: guardian death at group join


@pytest.mark.parametrize("how", ["reaped-by-someone", "zombie"])
def test_m7_a_guardian_that_dies_as_a_child_joins_its_group_is_replaced_and_the_start_retried(owner, ff, spawns, how):
    """Codex re-review 5 MEDIUM 7: the guardian died (and was reaped) after the start was validated and before the real
    spawn; the group join failed (``PermissionError``) and the start failed after one attempt. The failed join -- or a
    child found in a dead guardian's group -- is now recognised as the guardian's loss and the start is prepared again
    for a new guardian (bounded); an unrelated spawn error is still the caller's."""
    controller = JobController("p5i-m7")
    controller.start()
    owner.ensure_guardian()
    first = owner._guardian
    attempts = []

    def kill_on_join(cmd):
        if cmd and ff in [str(a) for a in cmd]:
            attempts.append(owner._guardian)
            if first.poll() is None and first.returncode is None and not child_ownership.has_exited(first):
                os.kill(first.pid, signal.SIGKILL)
                assert _wait_for(lambda: child_ownership.has_exited(first), 5)
                if how == "reaped-by-someone":
                    first.wait(5)

    spawns.hooks.append(kill_on_join)
    start_media(controller, [ff, "-B", "-c", "pass"])
    medias = [p for p in spawns.all if p not in spawns.guardians()]
    assert len(attempts) >= 2, attempts
    assert medias[-1].returncode == 0, "the retried start ran to its end"
    assert all(p.returncode is not None for p in medias), "anything made in the dead group was ended"
    assert owner.guardian_pid() not in (None, first.pid)


def test_m7_an_unrelated_spawn_error_is_still_the_callers(owner):
    owner.ensure_guardian()
    with pytest.raises(OSError):
        owner.popen_external(["/nonexistent/ffmpeg", "-version"])
    assert owner.guardian_pid() is not None and owner.outstanding() == []


# =========================================================================== drop cases 13-15 and the positive controls


def test_a_process_that_exits_while_it_is_being_retired_is_confirmed_and_never_signalled_after(owner, ff, monkeypatch):
    """A child that ends on its own during its SIGTERM grace is confirmed then; nothing is sent to it once it has ended."""
    owner.ensure_guardian()
    proc = owner.popen_external([ff, "-B", "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                                 "print('ready', flush=True); time.sleep(0.3)"], stdout=subprocess.PIPE)
    assert proc.stdout.readline() == b"ready\n"
    sent = []

    def spy(pid, start, sig, **kw):
        sent.append((pid, sig, proc.returncode))
        return REAL_SIGNAL(pid, start, sig, **kw)

    monkeypatch.setattr(child_ownership, "signal_if_same", spy)
    began = time.monotonic()
    owner.end(proc, grace=1.0)
    took = time.monotonic() - began
    assert proc.returncode == 0 and took < 0.9, (proc.returncode, took)
    assert [s for s in sent if s[0] == proc.pid and s[1] == signal.SIGKILL] == [], sent
    assert all(code is None for _pid, _sig, code in sent), "never signalled once reaped"
    assert owner.child(proc) is None and owner.outstanding() == []


def test_concurrent_starts_and_a_cancel_from_other_threads_create_nothing_after_the_latch(owner, ff, spawns):
    """Six workers start children of one run while a Cancel comes from another thread: every child either exists before
    the latch (and is stopped) or is refused; none is created after it; the run settles with nothing owed."""
    controller = JobController("p5i-concurrent")
    controller.start()
    owner.ensure_guardian()
    created_after_latch = []

    def note(cmd):
        if cmd and ff in [str(a) for a in cmd] and controller.cancel_check():
            created_after_latch.append(cmd)

    spawns.hooks.append(note)
    outcomes = []

    def worker():
        try:
            while True:
                start_media(controller, [ff, "-B", "-c", SLEEP])
        except ConversionCancelled:
            outcomes.append("cancelled")
        except BaseException as exc:  # noqa: BLE001
            outcomes.append(exc)

    threads = [threading.Thread(target=worker, name=f"w{i}", daemon=True) for i in range(6)]
    for thread in threads:
        thread.start()
    assert _wait_for(lambda: len([p for p in spawns.all if p not in spawns.guardians()]) >= 6, 10)
    pressing, _ = run_in_thread(controller.request_cancel, "Cancel")
    pressing.join(0.5)
    assert not pressing.is_alive(), "C1"
    ffmpeg_watch.wake()
    for thread in threads:
        thread.join(10)
    assert outcomes == ["cancelled"] * 6, outcomes
    assert created_after_latch == [], created_after_latch
    assert ffmpeg_watch.settle_children(controller.cancel_check) == []
    assert all(p.returncode is not None for p in spawns.all if p not in spawns.guardians())
    assert owner.outstanding(controller.cancel_check) == []


def test_positive_normal_cancel_then_an_independent_run_succeeds(owner, ff, spawns):
    """Normal Cancel of a running child, then the next run with the same owner: started, finished, clean."""
    first = JobController("p5i-first")
    first.start()
    a, out = run_in_thread(lambda: start_media(first, [ff, "-B", "-c", SLEEP]), "A")
    assert _wait_for(lambda: [p for p in spawns.all if p not in spawns.guardians()], 10)
    first.request_cancel()
    ffmpeg_watch.wake()
    a.join(10)
    assert isinstance(out.get("error"), ConversionCancelled)
    assert ffmpeg_watch.settle_children(first.cancel_check) == []
    second = JobController("p5i-second")
    second.start()
    start_media(second, [ff, "-B", "-c", "pass"])
    medias = [p for p in spawns.all if p not in spawns.guardians()]
    assert [p.returncode for p in medias] == [-signal.SIGKILL, 0]
    assert ffmpeg_watch.settle_children(second.cancel_check) == [] and owner.outstanding() == []


def test_positive_setup_child_guardian_replacement_and_orderly_end(owner, ff, spawns):
    """A setup child runs and reports success; a guardian killed by hand is replaced (its loss recorded) and the next
    child runs in the new group; the orderly end returns quickly with nothing left."""
    result = owner.run_external([ff, "-B", "-c", "print('ok')"], timeout=10)
    assert result.returncode == 0 and result.stdout.strip() == "ok"
    first = owner.guardian_pid()
    kill_guardian_unreaped(owner)
    assert _wait_for(lambda: owner.degraded, 5)
    again = owner.run_external([ff, "-B", "-c", "import os; print(os.getpgrp())"], timeout=10)
    assert again.returncode == 0 and int(again.stdout) == owner.guardian_pid() != first
    began = time.monotonic()
    assert owner.shutdown() == []
    assert time.monotonic() - began < child_ownership.SHUTDOWN_BOUND_S
    assert spawns.live() == [] and owner.outstanding() == []


def test_positive_two_successive_runs_settle_independently(owner, ff):
    """One run's ledger entries never stand in another's settlement."""
    one, two = JobController("p5i-one"), JobController("p5i-two")
    one.start()
    two.start()
    a, out = run_in_thread(lambda: start_media(one, [ff, "-B", "-c", SLEEP]), "one")
    assert _wait_for(lambda: owner.outstanding(one.cancel_check), 10)
    start_media(two, [ff, "-B", "-c", "pass"])
    assert ffmpeg_watch.settle_children(two.cancel_check) == [], "the other run's live child is not this run's"
    one.request_cancel()
    ffmpeg_watch.wake()
    a.join(10)
    assert ffmpeg_watch.settle_children(one.cancel_check) == []
