"""v0.8.x P1A -- POSIX containment of setup's children (``shared/child_ownership.py``, plan section 11.2.2).

KX-4 (automated part): ``kill -9`` of the setup owner while pip (through the real ``bootstrap._pip``) and a build
backend below it run -- both gone within 3 s. KX-7 (negative control): the same with the lifeline switched off; the
orphan IS seen, so this test can fail. KX-8 (identity control): a recorded pid that now belongs to an unrelated
process with another start time is never signalled. Guardian loss: the owner fails closed (the external program loses
its guardian, so it is stopped and reported as a failure), starts a new guardian, and the next external program is
contained when the owner is killed. KX-9: every spawn site in bootstrap.py goes through the containment helpers or is
on the deliberately-detached allow-list. Windows controls: with ``IS_WINDOWS`` the released spawn paths are used.
P5-A: a group whose leader exited while a member lived on is ended only while its id is proved to be the leader's
own (unreaped, under the ``Popen``'s waitpid lock, same start time); after a reap, or for another identity, nothing
is signalled.

Every process is identified by pid AND kernel start time before it is declared gone; nothing is found by name.
"""

from __future__ import annotations

import ast
import json
import os
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
BOOTSTRAP = SCRIPTS / "shared" / "bootstrap.py"
NATIVE_MACOS = "native macOS only (P1A): bash 3.2 stage 0, POSIX process groups, Mach-O and codesign checks"
native = pytest.mark.skipif(sys.platform != "darwin", reason=NATIVE_MACOS)

from shared import bootstrap, child_ownership  # noqa: E402


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _alive(pid: int, start) -> bool:
    return start is not None and child_ownership.process_start_time(pid) == start


def _wait_gone(identities, timeout: float) -> list:
    deadline = time.monotonic() + timeout
    while True:
        alive = [(pid, start) for pid, start in identities if _alive(pid, start)]
        if not alive or time.monotonic() >= deadline:
            return alive
        time.sleep(0.05)


def _wait_for_line(path: Path, prefix: str, timeout: float = 30) -> list[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip().startswith(prefix):
                    return line.split()
        time.sleep(0.05)
    raise AssertionError(f"{prefix} never appeared in {path}: {path.read_text() if path.exists() else '(none)'}")


DRIVER_HEAD = f"""
import os, sys, time, types
sys.path.insert(0, {str(SCRIPTS)!r})
from shared import bootstrap, child_ownership
bootstrap.LOG = types.SimpleNamespace(line=lambda *a, **k: None, path=None)
out = sys.argv[1]
def note(text):
    with open(out, "a") as handle:
        handle.write(text + "\\n")
"""

FAKE_PIP = ("import os, subprocess, sys, time; "
            "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)']); "
            "print('PIDS', os.getpid(), g.pid, flush=True); time.sleep(600)")


def _start_driver(tmp_path: Path, body: str) -> tuple[subprocess.Popen, Path]:
    script = tmp_path / "owner_driver.py"
    script.write_text(DRIVER_HEAD + body, encoding="utf-8")
    out = tmp_path / "owner.out"
    proc = subprocess.Popen([sys.executable, "-I", str(script), str(out)], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc, out


def _kill_identified(identities) -> None:
    for pid, start in identities:
        child_ownership.signal_if_same(pid, start, signal.SIGKILL)


# --------------------------------------------------------------------------- #
#  Pure pieces (every platform)
# --------------------------------------------------------------------------- #
def test_the_entry_goes_in_front_of_the_program_and_after_interpreter_options():
    entry = str(child_ownership.ENTRY)
    assert child_ownership.python_argv(["py", "-m", "pip", "install", "x"]) == ["py", entry, "-m", "pip", "install", "x"]
    assert child_ownership.python_argv(["py", "-I", "-c", "code"]) == ["py", "-I", entry, "-c", "code"]
    assert child_ownership.python_argv(["py", "-X", "utf8", "script.py", "a"]) == ["py", "-X", "utf8", entry,
                                                                                    "script.py", "a"]


def test_a_class_a_child_always_leads_its_own_group_and_never_gets_the_write_end():
    owner = child_ownership.Owner()
    try:
        kw = owner.class_a_kwargs({"env": {"A": "1"}})
        assert kw["start_new_session"] is True and kw["close_fds"] is True
        assert kw["env"][child_ownership.LIFELINE_ENV] == str(owner._read)
        assert owner._write not in kw["pass_fds"] and kw["pass_fds"] == (owner._read,)
        assert os.get_inheritable(owner._write) is False, "PEP 446: the write end never reaches a child"
        with pytest.raises(ValueError):
            owner.class_a_kwargs({"process_group": 0})
    finally:
        owner.shutdown()


def test_containment_is_posix_only_and_windows_keeps_its_spawn_paths(monkeypatch):
    assert child_ownership.supported("win32") is False
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setattr(bootstrap, "_hidden", lambda: {})
    assert bootstrap._contained() is False
    calls = []
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or "ran")
    assert bootstrap._child_run(["python.exe", "-c", "x"], timeout=5) == "ran"
    assert bootstrap._run(["python.exe", "-m", "venv", "v"]) == "ran"
    assert calls[0] == (["python.exe", "-c", "x"], {"timeout": 5})
    assert calls[1] == (["python.exe", "-m", "venv", "v"], {"capture_output": True, "text": True})
    assert all(str(child_ownership.ENTRY) not in cmd for cmd, _ in calls), "Windows commands are not rewritten"


SPAWN_FUNCS = {"run", "Popen", "call", "check_output", "check_call"}
#: Deliberately detached (class D) or Windows-only routes, with why.
ALLOWED_DIRECT = {
    "launch_gui": "class D: the app window, detached into its own session to outlive setup",
    "_open_folder": "class D: Finder's `open` for a folder reveal",
    "relaunch_setup": "Windows-only: setup re-run after the Windows long-path switch",
    "hand_off_launch_only": "Windows-only: --launch-only restarted with a hidden console so the .bat's window can close",
}
#: Helpers whose direct subprocess call is the Windows branch, under `not _contained()`.
WINDOWS_BRANCH = {"_child_run", "_run", "_pip"}


def _spawn_calls(tree: ast.AST):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in SPAWN_FUNCS \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
            chain, cursor = [], node
            while cursor in parents:
                cursor = parents[cursor]
                chain.append(cursor)
            function = next((c.name for c in chain if isinstance(c, ast.FunctionDef)), "<module>")
            branch = next((c for c in chain if isinstance(c, ast.If)), None)
            yield function, node, branch


def test_kx9_every_spawn_in_bootstrap_is_contained_or_allow_listed():
    tree = ast.parse(BOOTSTRAP.read_text(encoding="utf-8"))
    seen = set()
    for function, call, branch in _spawn_calls(tree):
        seen.add(function)
        if function in WINDOWS_BRANCH:
            assert branch is not None and "_contained()" in ast.unparse(branch.test), \
                f"{function}: a direct subprocess call outside the Windows (`not _contained()`) branch"
        else:
            assert function in ALLOWED_DIRECT, f"{function} spawns directly; route it through child_ownership"
    assert seen >= WINDOWS_BRANCH | {"launch_gui"}
    # No Homebrew anywhere it could run.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value in ("brew", "/opt/homebrew/bin"):
            raise AssertionError("bootstrap.py still names Homebrew as something to run")


def test_kx9_the_only_detached_spawn_is_the_app_window():
    tree = ast.parse(BOOTSTRAP.read_text(encoding="utf-8"))
    detached = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and ast.unparse(node) == 'kwargs["start_new_session"]':
            detached.add("launch_gui")
        if isinstance(node, ast.keyword) and node.arg in ("start_new_session", "process_group"):
            detached.add(ast.unparse(node))
    assert detached <= {"launch_gui", "**group"} | {"start_new_session=True"}


def test_no_production_module_forks_without_exec():
    """The lifeline's write end can leak only through fork without exec; the multiprocessing start method stays
    `spawn` (the macOS default) and nothing in scripts/ changes it or forks."""
    from source_probe import application_python_files

    offenders = []
    for path in application_python_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if "set_start_method" in text or "os.fork(" in text or "os.forkpty(" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


@native
def test_multiprocessing_start_method_is_spawn():
    import multiprocessing

    assert multiprocessing.get_start_method(allow_none=False) == "spawn"


# --------------------------------------------------------------------------- #
#  Native containment proofs
# --------------------------------------------------------------------------- #
@native
def test_process_start_time_identifies_a_process_and_not_its_pid_reuse():
    proc = subprocess.Popen(["/bin/sleep", "30"])
    try:
        start = child_ownership.process_start_time(proc.pid)
        assert start is not None and start == child_ownership.process_start_time(proc.pid)
        assert child_ownership.process_start_time(os.getpid()) != start
    finally:
        proc.kill()
        proc.wait()
    assert child_ownership.process_start_time(proc.pid) in (None,) or \
        child_ownership.process_start_time(proc.pid) != start


@native
def test_kx8_a_recorded_pid_with_another_start_time_is_never_signalled():
    stranger = subprocess.Popen(["/bin/sleep", "30"])
    try:
        real = child_ownership.process_start_time(stranger.pid)
        wrong = (real[0] - 1000, real[1])
        assert child_ownership.signal_if_same(stranger.pid, wrong, signal.SIGKILL) is False
        assert child_ownership.signal_if_same(stranger.pid, wrong, signal.SIGKILL, group=True) is False
        time.sleep(0.2)
        assert stranger.poll() is None, "the unrelated process is untouched"
        assert child_ownership.signal_if_same(stranger.pid, real, signal.SIGKILL) is True
        assert stranger.wait(timeout=5) == -signal.SIGKILL
    finally:
        if stranger.poll() is None:
            stranger.kill()
            stranger.wait()


@native
def test_kx4_killing_the_setup_owner_ends_pip_and_its_build_backend_within_3s(tmp_path):
    driver, out = _start_driver(tmp_path, f"""
bootstrap._pip([sys.executable, "-c", {FAKE_PIP!r}], dict(os.environ), note)
""")
    try:
        _, child, grandchild = _wait_for_line(out, "PIDS")
        identities = [(int(child), child_ownership.process_start_time(int(child))),
                      (int(grandchild), child_ownership.process_start_time(int(grandchild)))]
        assert all(start is not None for _, start in identities)
        assert os.getpgid(int(child)) == int(child), "pip leads its own group"
        assert os.getpgid(int(grandchild)) == int(child), "its build backend is in that group"
        os.kill(driver.pid, signal.SIGKILL)
        driver.wait()
        killed_at = time.monotonic()
        remaining = _wait_gone(identities, 3.0)
        assert remaining == [], f"orphans after {time.monotonic() - killed_at:.2f}s: {remaining}"
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait()


@native
def test_kx7_negative_control_without_the_lifeline_the_orphan_is_seen(tmp_path):
    driver, out = _start_driver(tmp_path, f"""
child_ownership._OWNER = child_ownership.Owner(lifeline=False)
bootstrap._pip([sys.executable, "-c", {FAKE_PIP!r}], dict(os.environ), note)
""")
    identities = []
    try:
        _, child, grandchild = _wait_for_line(out, "PIDS")
        identities = [(int(child), child_ownership.process_start_time(int(child))),
                      (int(grandchild), child_ownership.process_start_time(int(grandchild)))]
        os.kill(driver.pid, signal.SIGKILL)
        driver.wait()
        remaining = _wait_gone(identities, 3.0)
        assert len(remaining) == 2, "with no lifeline the children outlive their owner: the detector works"
    finally:
        _kill_identified(identities)
        if driver.poll() is None:
            driver.kill()
            driver.wait()


@native
def test_an_orderly_stop_ends_pip_by_identity(tmp_path):
    driver, out = _start_driver(tmp_path, f"""
import threading
threading.Thread(target=lambda: note("CODE %s" % bootstrap._pip([sys.executable, "-c", {FAKE_PIP!r}],
                                                                 dict(os.environ), note)), daemon=True).start()
while not os.path.exists(out) or "PIDS" not in open(out).read():
    time.sleep(0.05)
note("STOPPED %s" % bootstrap.request_setup_stop())
time.sleep(2)
""")
    try:
        _, child, grandchild = _wait_for_line(out, "PIDS")
        identities = [(int(child), child_ownership.process_start_time(int(child))),
                      (int(grandchild), child_ownership.process_start_time(int(grandchild)))]
        assert _wait_for_line(out, "STOPPED") == ["STOPPED", "True"]
        assert _wait_for_line(out, "CODE") == ["CODE", str(bootstrap.PIP_STOPPED)]
        assert _wait_gone(identities, 3.0) == []
    finally:
        driver.wait(timeout=30)


@native
def test_guardian_loss_fails_closed_then_a_new_guardian_contains_the_next_program(tmp_path):
    """The user's safeguard 1: a guardian that dies on its own never leaves an uncounted, uncontained program."""
    driver, out = _start_driver(tmp_path, """
o = bootstrap._owner()
first = o.popen_external(["/bin/sleep", "600"], label="first")
note("FIRST %d %d" % (first.pid, o.guardian_pid()))
while not o.degraded:
    time.sleep(0.02)
deadline = time.time() + 5
while first.poll() is None and time.time() < deadline:
    time.sleep(0.02)
lost = o.child(first).lost_containment
note("LOST %s %s" % (lost, first.returncode))
second = o.popen_external(["/bin/sleep", "600"], label="second")
note("SECOND %d %d" % (second.pid, o.guardian_pid()))
time.sleep(600)
""")
    identities = []
    try:
        _, first, guardian1 = _wait_for_line(out, "FIRST")
        first_id = (int(first), child_ownership.process_start_time(int(first)))
        guardian1_id = (int(guardian1), child_ownership.process_start_time(int(guardian1)))
        assert os.getpgid(int(first)) == int(guardian1), "the external program is in the guardian's group"
        os.kill(int(guardian1), signal.SIGKILL)  # the guardian dies on its own, by hand
        assert _wait_for_line(out, "LOST")[1] == "True", "the program that lost its guardian is reported"
        assert _wait_gone([first_id], 3.0) == [], "and stopped (fail closed)"
        _, second, guardian2 = _wait_for_line(out, "SECOND")
        assert guardian2 != guardian1 and os.getpgid(int(second)) == int(guardian2)
        identities = [(int(second), child_ownership.process_start_time(int(second))),
                      (int(guardian2), child_ownership.process_start_time(int(guardian2)))]
        os.kill(driver.pid, signal.SIGKILL)
        driver.wait()
        assert _wait_gone(identities, 3.0) == [], "the next program is contained when the owner is killed"
        assert _wait_gone([guardian1_id], 0.1) == []
    finally:
        _kill_identified(identities)
        if driver.poll() is None:
            driver.kill()
            driver.wait()


@native
def test_a_bounded_external_run_that_loses_its_guardian_is_a_failure_not_a_success():
    owner = child_ownership.Owner()
    try:
        import threading

        result = {}
        worker = threading.Thread(target=lambda: result.setdefault(
            "done", owner.run_external(["/bin/sleep", "30"], timeout=60, label="sleep")))
        worker.start()
        deadline = time.monotonic() + 10
        while owner.guardian_pid() is None or not owner.children():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        os.kill(owner.guardian_pid(), signal.SIGKILL)
        worker.join(15)
        done = result["done"]
        assert done.returncode != 0 and "lost containment" in done.stderr
        assert owner.degraded and any("ended on its own" in e for e in owner.events)
    finally:
        owner.shutdown()


@native
def test_the_orderly_shutdown_ends_everything_within_its_bound():
    owner = child_ownership.Owner()
    a = owner.popen_python([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, "
                            "signal.SIG_IGN); time.sleep(600)"])
    b = owner.popen_external(["/bin/sleep", "600"])
    guardian = owner.guardian_pid()
    ids = [(p, child_ownership.process_start_time(p)) for p in (a.pid, b.pid, guardian)]
    started = time.monotonic()
    owner.shutdown()
    assert time.monotonic() - started <= child_ownership.SHUTDOWN_BOUND_S + 0.5
    assert _wait_gone(ids, 2.0) == []


@native
def test_an_exited_child_is_seen_without_being_reaped():
    """CPython has no os.waitid on macOS; the group is SIGKILLed before the leader is reaped, so exit must be observable
    while the child is still a zombie (found on this Mac in P1A: the first version called os.waitid and crashed)."""
    proc = subprocess.Popen(["/bin/sleep", "0.2"])
    try:
        assert child_ownership._has_exited(proc.pid) is False
        assert child_ownership._wait_exited(proc.pid, 5.0) is True
        assert child_ownership.process_start_time(proc.pid) is not None, "still unreaped: its identity still reads"
    finally:
        proc.wait()


# --------------------------------------------------------------------------- #
#  v0.8.x P5-A: a group whose leader has exited -- ended only while its id is proved
# --------------------------------------------------------------------------- #
#: A leader that starts one member of its own process group, prints the member's pid, then exits (or keeps running).
LEADER_CODE = ("import subprocess, sys, time; "
               "m = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'], "
               "stdout=subprocess.DEVNULL); "
               "print(m.pid, flush=True); time.sleep(float(sys.argv[1]))")


def _leader_with_member(linger: float = 0.0):
    """A real leader of its own session and group (as every class-A child and the setup worker is) that leaves one
    member behind. Returns ``(leader, leader_start, (member_pid, member_start))``; the leader is never reaped here."""
    leader = subprocess.Popen([sys.executable, "-I", "-c", LEADER_CODE, str(linger)], start_new_session=True,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
    start = child_ownership.process_start_time(leader.pid)
    member = int(leader.stdout.readline())
    leader.stdout.close()
    member_identity = (member, child_ownership.process_start_time(member))
    assert start is not None and member_identity[1] is not None
    return leader, start, member_identity


def _cleanup(leader: subprocess.Popen, *identities) -> None:
    _kill_identified(identities)
    if leader.returncode is None:
        try:
            leader.wait(timeout=10)
        except subprocess.TimeoutExpired:
            leader.kill()
            leader.wait()
    assert _wait_gone(identities, 5.0) == []


@native
def test_a_group_whose_leader_exited_is_ended_while_the_leader_is_still_unreaped():
    """The defect P5-A fixes: the leader exits normally and a member of its group lives on. Exit is seen without
    reaping (the zombie keeps the id), the group is ended, the kernel confirms nothing is left, and only then is the
    leader reaped -- by its caller."""
    leader, start, member = _leader_with_member()
    try:
        assert child_ownership.wait_exited(leader, 10.0, start) is True
        assert leader.returncode is None and child_ownership.process_start_time(leader.pid) == start  # unreaped
        assert os.getpgid(member[0]) == leader.pid and _alive(*member)  # left behind in the leader's group
        assert child_ownership.end_led_group(leader, start, bound_s=5.0) == child_ownership.GROUP_ENDED
        assert _wait_gone([member], 2.0) == []
        assert leader.returncode is None  # end_led_group never reaps
        assert child_ownership.end_led_group(leader, start, bound_s=5.0) == child_ownership.GROUP_ENDED  # idempotent
    finally:
        _cleanup(leader, member)
    assert leader.returncode == 0


@native
def test_a_running_leaders_group_is_ended_with_the_leader():
    """Cancel and time-out: the leader is still running; it and every member end, and the leader is left to reap."""
    leader, start, member = _leader_with_member(linger=600)
    try:
        assert child_ownership.has_exited(leader, start) is False
        assert child_ownership.end_led_group(leader, start, bound_s=5.0) == child_ownership.GROUP_ENDED
        assert _wait_gone([member], 2.0) == [] and child_ownership.has_exited(leader, start)
    finally:
        _cleanup(leader, member)
    assert leader.returncode == -signal.SIGKILL


@native
def test_a_group_is_never_signalled_once_its_leader_has_been_reaped():
    """After the reap the id -- the group's id -- may be handed to another process, so nothing is signalled at all:
    the member left behind is proved untouched (it is then ended by the test, by identity)."""
    leader, start, member = _leader_with_member()
    try:
        assert leader.wait(timeout=10) == 0
        assert child_ownership.end_led_group(leader, start, bound_s=1.0) == child_ownership.GROUP_UNPROVED
        time.sleep(0.2)
        assert _alive(*member), "a group whose leader was reaped must never be signalled"
    finally:
        _cleanup(leader, member)


@native
def test_a_leader_that_is_not_the_recorded_process_is_never_signalled():
    """KX-8 for groups: a recorded start time that no longer matches, no recorded identity, or no ``Popen`` lock to
    hold off a reap -- each is unprovable, so nothing is signalled, whether the leader is running or has exited."""
    leader, start, member = _leader_with_member(linger=600)
    try:
        other = (start[0] - 1000, start[1])  # as if the id now named another process
        assert child_ownership.has_exited(leader, start) is False
        assert child_ownership.has_exited(leader, other) is True  # the recorded process is not there any more
        no_lock = types.SimpleNamespace(pid=leader.pid, returncode=None)  # not a Popen: no reap can be held off
        for exited in (False, True):
            if exited:
                leader.send_signal(signal.SIGKILL)  # the leader alone (running: not reaped); its member lives on
                assert child_ownership.wait_exited(leader, 10.0, start)
            for identity, proc in ((other, leader), (None, leader), (start, no_lock)):
                assert child_ownership.end_led_group(proc, identity, bound_s=1.0) == child_ownership.GROUP_UNPROVED
            time.sleep(0.2)
            assert _alive(*member) and leader.returncode is None
            assert exited or child_ownership.has_exited(leader, start) is False  # a running leader was not touched
    finally:
        _cleanup(leader, member)


@native
def test_a_group_is_not_signalled_while_another_thread_may_be_reaping_its_leader():
    """``Popen`` reaps only under its waitpid lock. While another thread holds it the leader may be reaped at any
    moment, so the group is not signalled, and the wait for the lock is bounded."""
    leader, start, member = _leader_with_member()
    try:
        assert child_ownership.wait_exited(leader, 10.0, start)
        with leader._waitpid_lock:
            began = time.monotonic()
            assert child_ownership.end_led_group(leader, start, bound_s=0.3) == child_ownership.GROUP_UNPROVED
            assert time.monotonic() - began < 2.0
        assert _alive(*member)
        assert child_ownership.end_led_group(leader, start, bound_s=5.0) == child_ownership.GROUP_ENDED
        assert _wait_gone([member], 2.0) == []
    finally:
        _cleanup(leader, member)


@native
def test_ending_a_group_never_touches_an_unrelated_process():
    """Two bystanders: one in this test's own process group, one leading a session of its own. Ending another
    leader's group (exited, and running) leaves both alone."""
    same_group = subprocess.Popen(["/bin/sleep", "600"])
    own_session = subprocess.Popen(["/bin/sleep", "600"], start_new_session=True)
    bystanders = [(p.pid, child_ownership.process_start_time(p.pid)) for p in (same_group, own_session)]
    try:
        for linger in (0.0, 600):
            leader, start, member = _leader_with_member(linger)
            try:
                if not linger:
                    assert child_ownership.wait_exited(leader, 10.0, start)
                assert child_ownership.end_led_group(leader, start, bound_s=5.0) == child_ownership.GROUP_ENDED
            finally:
                _cleanup(leader, member)
        assert all(_alive(*b) for b in bystanders)
    finally:
        _kill_identified(bystanders)
        same_group.wait()
        own_session.wait()


def test_the_popen_lock_the_group_proof_relies_on_exists():
    """``end_led_group`` holds ``Popen._waitpid_lock`` (CPython's own guard against signalling a reaped id, bpo-38630).
    A Python without it makes every group unprovable -- nothing signalled, a failure reported -- so this pins it."""
    import threading

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert type(proc._waitpid_lock) is type(threading.Lock())
