"""v0.7.0 P04C Stage 1 — the app environment is never replaced around a Qwen3 engine that is in use.

**The defect (P04B, proven natively on HOME-PC).** With the candidate nested layout an independent Qwen3 environment
lives at ``.venv/engines/qwen3``. A running worker, and separately a real app conversion holding ``inference.lock`` and
the machine guard, did not stop ``repair_venv``: Windows lets a folder be renamed while programs inside it are mapped
into memory, so the parent was set aside with the running engine inside it, rebuilt, and the engine carried back
~99 s later. The app-shaped run also left a partial ``.venv.replaced`` (17 mapped DLLs) and still reported plain
success.

**The contract now.**

* Whenever the parent, or the environment it set aside, holds anything under ``engines/``, the bootstrap takes
  ``shared.engine_lease`` -- ``setup.lock`` -> ``inference.lock`` -> ``engine.lock``, non-blocking, all or none --
  *before* recovery or any rename, and holds it through replacement, rollback, commit and cleanup. A busy, denied or
  unusable lock is an immediate refusal that changes nothing and says what to do.
* The worker holds ``engine.lock`` itself for as long as it runs, so even a worker whose app has gone is seen; a
  worker that cannot take it, or that finds itself running from a set-aside environment, refuses before any import.
* A superseded environment is renamed out of the "last known good" name before it is deleted, a leftover is reported
  as one (never as a clean success), and recovery only ever finishes deleting it -- it is never put back.
* With nothing held (the legacy layout) the repair behaves exactly as before and touches no lock file.

Every environment and lock here lives in ``tmp_path``. Cross-process cases use real subprocesses holding the real
locks; nothing touches ``.venv``, ``.venv-qwen3`` or the real runtime folder.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from shared import bootstrap
from shared import engine_lease as el
from shared import venv_layout
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su
from tts import qwen3_synth
from tts import qwen3_worker as worker

from test_qwen3_runtime import sandbox  # noqa: F401  (the sandbox fixture)
from test_venv_recovery import (  # noqa: F401  (``env`` is a fixture)
    _Log, _caps, _creates_venv, _engine_in, _existing_venv, _plant_engine, _probe, _protected, _protected_after,
    _reconcile_spy, _seed_interpreter, _successful_repair_fakes, _tree, env,
)

SCRIPTS = Path(bootstrap.SCRIPTS_DIR)
BASE_PYTHON = Path(getattr(sys, "_base_executable", sys.executable))


def lock_dir(env) -> Path:
    """The copy's Qwen3 runtime folder, beside the disposable ``.venv`` the ``env`` fixture created."""
    return env.tmp / "files" / "runtime-data" / "qwen3"


def free(folder: Path) -> dict[str, bool]:
    """Which of the three locks another process could take right now."""
    out = {}
    for name in el.ORDER:
        folder.mkdir(parents=True, exist_ok=True)
        lock = el.FileLock(folder / name)
        out[name] = lock.acquire()
        lock.release()
    return out


ALL_FREE = {name: True for name in el.ORDER}


def wait_free(folder: Path, timeout_s: float = 10.0) -> dict[str, bool]:
    """``free`` once a killed holder's locks are gone. Windows drops them as the process is torn down, which can lag
    the process's own exit slightly; a repair that comes in during that moment is refused (safely) and retried."""
    deadline = time.monotonic() + timeout_s
    while True:
        state = free(folder)
        if state == ALL_FREE or time.monotonic() > deadline:
            return state
        time.sleep(0.05)


# --------------------------------------------------------------------------- #
# Real holders in other processes
# --------------------------------------------------------------------------- #
_HOLDER = textwrap.dedent("""
    import sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    mode, folder, guard = sys.argv[2], Path(sys.argv[3]), sys.argv[4]
    from tts import qwen3_runtime as rt
    rt.runtime_dir = lambda: folder
    rt.MACHINE_GUARD_NAME = guard
    if mode == "worker":
        from tts import qwen3_worker as worker
        refusal = worker.claim_engine({"engine_lock": str(folder / "engine.lock")})
        assert refusal is None, refusal
    elif mode == "conversion":
        rt.inference_lease().__enter__()
    elif mode == "install":
        from tts import qwen3_setup as su
        su.InstallLock().acquire()
    elif mode == "guard":
        assert rt.MachineGuard().acquire()
    elif mode == "lease":
        from shared import engine_lease as el
        el.Lease(folder, root=folder.parents[2]).take()
    else:
        raise SystemExit("unknown mode " + mode)
    print("READY", flush=True)
    sys.stdin.readline()
""")


@contextlib.contextmanager
def held_by_another_process(mode: str, folder: Path, *, kill: bool = False):
    """A separate Python process holding a real lock: a worker, a conversion, an install, the guard or a lease."""
    folder.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([sys.executable, "-c", _HOLDER, str(SCRIPTS), mode, str(folder), rt.MACHINE_GUARD_NAME],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline().strip()
        assert line == "READY", (line, proc.stderr.read() if proc.poll() is not None else "")
        yield proc
    finally:
        if kill:
            proc.kill()
        else:
            with contextlib.suppress(OSError):
                proc.stdin.close()
        proc.wait(timeout=30)


def nested_parent(env, monkeypatch) -> tuple[Path, dict]:
    """A repairable parent holding a child, with everything a successful repair calls faked."""
    keepsake = _existing_venv(env)
    engine = _plant_engine(env.venv)
    _successful_repair_fakes(monkeypatch)
    return keepsake, engine


def assert_nothing_changed(env, keepsake: Path, engine: dict) -> None:
    assert keepsake.read_text(encoding="utf-8") == "previous"
    assert not (env.venv / "candidate.txt").exists()
    assert _tree(_engine_in(env.venv)) == engine
    assert not os.path.lexists(bootstrap._venv_aside_path())


# --------------------------------------------------------------------------- #
# A. The lease itself
# --------------------------------------------------------------------------- #
def test_the_lock_names_are_the_ones_the_qwen3_code_locks(sandbox):
    assert rt.setup_lock_path() == el.runtime_dir(rt.repo_root()) / el.SETUP_LOCK
    assert rt.inference_lock_path() == el.runtime_dir(rt.repo_root()) / el.INFERENCE_LOCK
    assert rt.engine_lock_path() == el.runtime_dir(rt.repo_root()) / el.ENGINE_LOCK
    assert el.ORDER == (el.SETUP_LOCK, el.INFERENCE_LOCK, el.ENGINE_LOCK)


def test_the_bootstrap_finds_the_same_folder_production_qwen3_uses():
    """Production: the bootstrap's ``.venv`` and Qwen3's runtime folder belong to one copy of the app."""
    assert bootstrap._qwen3_lock_dir() == el.runtime_dir(bootstrap.REPO_ROOT)
    assert el.runtime_dir(bootstrap.REPO_ROOT) == rt.runtime_dir()


def test_one_lock_two_implementations(tmp_path):
    """``engine_lease.FileLock`` and ``qwen3_runtime.FileLock`` are the same lock, whichever takes it first."""
    path = tmp_path / "x.lock"
    theirs, ours = rt.FileLock(path), el.FileLock(path)
    assert theirs.acquire() and not ours.acquire()
    theirs.release()
    assert ours.acquire() and not theirs.acquire()
    ours.release()


def test_a_busy_lock_in_another_process_refuses_and_takes_nothing(tmp_path):
    folder = tmp_path / "repo" / "files" / "runtime-data" / "qwen3"
    with held_by_another_process("conversion", folder):
        lease = el.Lease(folder, root=tmp_path / "repo")
        with pytest.raises(el.Refused) as refused:
            lease.take()
        assert refused.value.lock == el.INFERENCE_LOCK and refused.value.reason == el.BUSY
        assert "conversion" in str(refused.value) and "Nothing was changed" in str(refused.value)
        assert lease.taken == [] and not lease.held
        # setup.lock was taken first and given back; engine.lock was never reached.
        assert free(folder)[el.SETUP_LOCK] and free(folder)[el.ENGINE_LOCK]
    assert free(folder) == ALL_FREE


def test_locks_are_taken_in_one_order_and_released_in_reverse(tmp_path, monkeypatch):
    seen = []
    real_acquire, real_release = el.FileLock.acquire, el.FileLock.release
    monkeypatch.setattr(el.FileLock, "acquire", lambda self: seen.append(("take", self.path.name)) or real_acquire(self))
    monkeypatch.setattr(el.FileLock, "release",
                        lambda self: (self.held and seen.append(("give", self.path.name))) or real_release(self))
    folder = tmp_path / "repo" / "files" / "runtime-data" / "qwen3"
    with el.Lease(folder, root=tmp_path / "repo") as lease:
        assert lease.held
    assert seen == [("take", n) for n in el.ORDER] + [("give", n) for n in reversed(el.ORDER)]


def test_a_lock_file_that_cannot_be_opened_fails_closed(tmp_path, monkeypatch):
    """Denied (an ACL, a read-only file): not "free", and not "busy" either -- it cannot be checked."""
    folder = tmp_path / "repo" / "files" / "runtime-data" / "qwen3"
    real_open = el.os.open

    def denying_open(path, *args, **kwargs):
        if Path(path).name == el.ENGINE_LOCK:
            raise PermissionError(13, "Access is denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(el.os, "open", denying_open)
    lease = el.Lease(folder, root=tmp_path / "repo")
    with pytest.raises(el.Refused) as refused:
        lease.take()
    assert refused.value.reason == el.UNAVAILABLE and refused.value.lock == el.ENGINE_LOCK
    assert "could not check" in str(refused.value) and "Nothing was changed" in str(refused.value)
    monkeypatch.undo()
    assert free(folder) == ALL_FREE  # the two it had taken were given back


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows mechanism")
def test_a_linked_runtime_folder_is_refused_not_followed(tmp_path):
    from test_qwen3_runtime import make_junction

    root, elsewhere = tmp_path / "repo", tmp_path / "elsewhere"
    (root / "files").mkdir(parents=True)
    elsewhere.mkdir()
    make_junction(root / "files" / "runtime-data", elsewhere)
    with pytest.raises(el.Refused) as refused:
        el.Lease(el.runtime_dir(root), root=root).take()
    assert refused.value.reason == el.UNAVAILABLE and refused.value.lock is None
    assert list(elsewhere.iterdir()) == []  # nothing was created behind the link


def test_the_lease_is_released_when_its_block_raises(tmp_path):
    folder = tmp_path / "repo" / "files" / "runtime-data" / "qwen3"
    with pytest.raises(RuntimeError):
        with el.Lease(folder, root=tmp_path / "repo"):
            assert not any(free(folder).values())
            raise RuntimeError("boom")
    assert free(folder) == ALL_FREE


def test_a_holder_that_dies_releases_every_lock(tmp_path):
    """No stale-lock case: the operating system drops the locks of a killed process."""
    folder = tmp_path / "repo" / "files" / "runtime-data" / "qwen3"
    with held_by_another_process("lease", folder, kill=True):
        assert not any(free(folder).values())
    assert wait_free(folder) == ALL_FREE


# --------------------------------------------------------------------------- #
# B. A repair refuses, changing nothing, while the held engine is in use
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode, words", [
    ("worker", "voice engine is still running"),
    ("conversion", "conversion"),
    ("install", "being installed or repaired"),
])
def test_a_repair_refuses_while_the_held_engine_is_in_use(env, monkeypatch, mode, words):
    keepsake, engine = nested_parent(env, monkeypatch)
    recovered = []
    monkeypatch.setattr(bootstrap, "recover_interrupted_replacement",
                        lambda log, require_tk=True: recovered.append(1))
    log = _Log()
    with held_by_another_process(mode, lock_dir(env)):
        ok, message = bootstrap.repair_venv(log, headless=True)
    assert ok is False and words in message and "Nothing was changed" in message
    assert recovered == []  # refused before recovery, too
    assert_nothing_changed(env, keepsake, engine)
    assert free(lock_dir(env)) == ALL_FREE


def test_a_second_repair_of_the_same_copy_refuses_while_one_runs(env, monkeypatch):
    keepsake, engine = nested_parent(env, monkeypatch)
    with held_by_another_process("lease", lock_dir(env)):
        ok, message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is False and "being installed or repaired" in message
    assert_nothing_changed(env, keepsake, engine)


def test_a_dead_worker_does_not_block_the_next_repair(env, monkeypatch):
    keepsake, engine = nested_parent(env, monkeypatch)
    with held_by_another_process("worker", lock_dir(env), kill=True):
        pass
    assert wait_free(lock_dir(env)) == ALL_FREE
    ok, message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is True and (env.venv / "candidate.txt").exists()
    assert _tree(_engine_in(env.venv)) == engine


def test_the_machine_guard_of_another_copy_does_not_block_this_copy_s_repair(env, monkeypatch):
    """Deliberate (see ``shared.engine_lease``): the guard keeps copies of the app off one GPU; it protects no file of
    this copy, and this copy's own conversions are refused through ``inference.lock`` whatever the guard says."""
    keepsake, engine = nested_parent(env, monkeypatch)
    with held_by_another_process("guard", lock_dir(env)):
        ok, message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is True and not keepsake.exists() and _tree(_engine_in(env.venv)) == engine


def test_first_run_setup_refuses_the_same_way_before_it_recovers_anything(env, monkeypatch):
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    engine = _plant_engine(aside)  # an interrupted repair left the engine in the set-aside parent
    searched = []
    monkeypatch.setattr(bootstrap, "find_suitable_python", lambda log, prefer_tk=True: searched.append(1))
    with held_by_another_process("worker", lock_dir(env)):
        ok, message = bootstrap.run_setup(False, lambda i, m: None, _Log(), headless=True)
    assert ok is False and "voice engine is still running" in message
    assert searched == [] and not env.venv.exists()  # not restored, not rebuilt
    assert _tree(_engine_in(aside)) == engine


def test_an_interrupted_repair_holding_the_engine_is_recovered_only_under_the_lease(env, monkeypatch):
    """The aside holds the only copy of the engine and no parent exists: recovery would rename it; it must wait."""
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    (aside / "keepsake.txt").write_text("previous", encoding="utf-8")
    engine = _plant_engine(aside)
    _successful_repair_fakes(monkeypatch)
    with held_by_another_process("conversion", lock_dir(env)):
        ok, message = bootstrap.repair_venv(_Log(), headless=True)
        assert ok is False and not env.venv.exists() and _tree(_engine_in(aside)) == engine
    ok, message = bootstrap.repair_venv(_Log(), headless=True)  # released: recovery then the repair proceed
    assert ok is True and (env.venv / "candidate.txt").exists() and not aside.exists()
    assert _tree(_engine_in(env.venv)) == engine


# --------------------------------------------------------------------------- #
# C. While a repair runs, nothing can start using the engine
# --------------------------------------------------------------------------- #
def _worker_job(tmp_path: Path, lock: Path, kind: str = "dance") -> Path:
    job = tmp_path / f"job-{kind}.json"
    job.write_text(json.dumps({"kind": kind, "engine_lock": str(lock)}), encoding="utf-8")
    return job


def _run_worker_script(python: Path, job: Path) -> tuple[int, list[dict]]:
    result = subprocess.run([str(python), str(rt.worker_script()), str(job)], capture_output=True, text=True,
                            timeout=60, env={k: v for k, v in os.environ.items()
                                             if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")})
    events = [json.loads(line[len(worker.EVENT_PREFIX):]) for line in result.stdout.splitlines()
              if line.startswith(worker.EVENT_PREFIX)]
    return result.returncode, events


def test_the_lease_is_held_for_the_whole_replacement_and_refuses_every_newcomer(env, monkeypatch):
    keepsake, engine = nested_parent(env, monkeypatch)
    folder = lock_dir(env)
    monkeypatch.setattr(rt, "runtime_dir", lambda: folder)
    observed = {}

    def reconcile_mid_transaction(log):
        aside = bootstrap._venv_aside_path()
        observed["engine_in_aside"] = _engine_in(aside).is_dir()
        observed["free"] = free(folder)
        with pytest.raises(rt.Qwen3Unavailable, match="installed or repaired"):
            with rt.inference_lease():
                pass
        with pytest.raises(su.SetupError, match="already being installed or repaired"):
            su.InstallLock().acquire()
        observed["worker"] = _run_worker_script(Path(sys.executable),
                                                _worker_job(env.tmp, folder / el.ENGINE_LOCK))
        return True, bootstrap.RECONCILE_OK

    monkeypatch.setattr(bootstrap, "reconcile_requirements", reconcile_mid_transaction)
    ok, message = bootstrap.repair_venv(_Log(), headless=True)

    assert ok is True and observed["engine_in_aside"] is True
    assert observed["free"] == {name: False for name in el.ORDER}
    code, events = observed["worker"]
    assert code == worker.EXIT_FAILED and events[-1]["event"] == "failed" and events[-1]["stage"] == "engine"
    assert _tree(_engine_in(env.venv)) == engine and free(folder) == ALL_FREE


def test_the_lease_is_held_through_a_rollback_too(env, monkeypatch):
    keepsake, engine = nested_parent(env, monkeypatch)
    folder = lock_dir(env)
    during = {}
    real_restore = bootstrap._restore_venv

    def watched_restore(aside, log):
        during["free"] = free(folder)
        return real_restore(aside, log)

    monkeypatch.setattr(bootstrap, "_restore_venv", watched_restore)
    monkeypatch.setattr(bootstrap, "reconcile_requirements", lambda log: (False, bootstrap.RECONCILE_PIP_FAILED))
    ok, message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is False and "put back" in message
    assert during["free"] == {name: False for name in el.ORDER}
    assert keepsake.exists() and _tree(_engine_in(env.venv)) == engine and free(folder) == ALL_FREE


def test_a_repair_that_crashes_mid_transaction_releases_the_lease(env, monkeypatch):
    nested_parent(env, monkeypatch)

    def crash(log):
        raise RuntimeError("pip exploded")

    monkeypatch.setattr(bootstrap, "reconcile_requirements", crash)
    with pytest.raises(RuntimeError):
        bootstrap.repair_venv(_Log(), headless=True)
    assert free(lock_dir(env)) == ALL_FREE


# --------------------------------------------------------------------------- #
# D. The worker holds the engine lock itself, and never runs from a set-aside parent
# --------------------------------------------------------------------------- #
def test_a_worker_refuses_before_any_import_while_the_engine_lock_is_held(tmp_path, monkeypatch, capsys):
    lock = tmp_path / el.ENGINE_LOCK
    holder = el.FileLock(lock)
    assert holder.acquire()
    monkeypatch.setattr(worker, "run_probe", lambda job: pytest.fail("the engine started"))
    try:
        assert worker.main(["worker", str(_worker_job(tmp_path, lock, "probe"))]) == worker.EXIT_FAILED
    finally:
        holder.release()
    failed = [json.loads(l[len(worker.EVENT_PREFIX):]) for l in capsys.readouterr().out.splitlines()][-1]
    assert failed["event"] == "failed" and failed["stage"] == "engine"
    assert "repaired" in failed["message"] and "in use" in failed["message"]


def test_a_job_that_names_no_engine_lock_is_refused(tmp_path, monkeypatch, capsys):
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"kind": "probe"}), encoding="utf-8")
    monkeypatch.setattr(worker, "run_probe", lambda job: pytest.fail("the engine started"))
    assert worker.main(["worker", str(job)]) == worker.EXIT_FAILED
    assert '"stage": "engine"' in capsys.readouterr().out


def test_a_worker_holds_the_engine_lock_while_it_runs_and_gives_it_back(tmp_path, monkeypatch, capsys):
    lock = tmp_path / el.ENGINE_LOCK
    seen = {}

    def probe(job):
        probe_lock = el.FileLock(lock)
        seen["free_while_running"] = probe_lock.acquire()
        probe_lock.release()
        return worker.EXIT_OK

    monkeypatch.setattr(worker, "run_probe", probe)
    assert worker.main(["worker", str(_worker_job(tmp_path, lock, "probe"))]) == worker.EXIT_OK
    assert seen["free_while_running"] is False
    after = el.FileLock(lock)
    assert after.acquire()
    after.release()


def _venv_at(path: Path) -> Path:
    subprocess.run([str(BASE_PYTHON), "-m", "venv", "--without-pip", str(path)], check=True, capture_output=True,
                   timeout=120, env={k: v for k, v in os.environ.items()
                                     if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")})
    return venv_layout.interpreter(path)


@pytest.mark.parametrize("aside_name", [".venv.replaced", ".venv.replaced-1729800000", ".venv.discarded"])
def test_a_real_child_running_from_a_set_aside_parent_refuses(tmp_path, aside_name):
    """A real interpreter whose prefix is inside a set-aside parent: the worker stops before reading its job's kind."""
    lock = tmp_path / el.ENGINE_LOCK
    python = _venv_at(tmp_path / "repo" / aside_name / "engines" / "qwen3")
    code, events = _run_worker_script(python, _worker_job(tmp_path, lock))
    assert code == worker.EXIT_FAILED and events[-1]["stage"] == "engine"
    assert "set aside" in events[-1]["message"]


def test_the_same_real_child_at_its_own_path_gets_past_the_claim(tmp_path):
    """The control: at ``.venv/engines/qwen3`` the claim succeeds and the job is judged on its own merits."""
    lock = tmp_path / el.ENGINE_LOCK
    python = _venv_at(tmp_path / "repo" / ".venv" / "engines" / "qwen3")
    code, events = _run_worker_script(python, _worker_job(tmp_path, lock))
    assert code == worker.EXIT_FAILED and "unknown job kind" in events[-1]["message"]


def test_every_job_the_app_writes_names_the_engine_lock(sandbox, monkeypatch, tmp_path):
    expected = str(rt.engine_lock_path())
    voice = rt.get_voice("qwen3-ryan")
    job = qwen3_synth.build_job(voice, [], job_dir=tmp_path, model_dir=tmp_path)
    assert job["engine_lock"] == expected

    captured = []

    def runner(cmd, **kwargs):
        captured.append(json.loads(Path(cmd[2]).read_text(encoding="utf-8")))
        return 0

    monkeypatch.setattr(rt, "venv_python", lambda: tmp_path / "python.exe")
    with contextlib.suppress(su.SetupError):
        su.probe_environment(runner=runner)
    assert captured and captured[0]["kind"] == "probe" and captured[0]["engine_lock"] == expected


def test_the_transcription_job_names_the_engine_lock_too():
    """Source check: the third job the app writes (clone drafts) carries the same key."""
    from source_probe import function
    import ast

    node = function("tts/qwen3_clone_setup.py", "create_drafts")
    keys = {k.value for d in ast.walk(node) if isinstance(d, ast.Dict) for k in d.keys
            if isinstance(k, ast.Constant)}
    assert "kind" in keys and worker.ENGINE_LOCK_KEY in keys


# --------------------------------------------------------------------------- #
# E. A previous environment that could not all be deleted is never a clean success and never comes back
# --------------------------------------------------------------------------- #
def _leaving_one_file(monkeypatch):
    """``shutil.rmtree`` as it behaves with a DLL still mapped: everything goes except one file."""
    real_rmtree = bootstrap.shutil.rmtree

    def partial(path, ignore_errors=False, **kwargs):
        path = Path(path)
        if path.name.startswith(".venv.discarded"):
            stuck = path / "Lib" / "site-packages" / "mapped.dll"
            for item in sorted(path.rglob("*"), reverse=True):
                if item.is_file() and item != stuck:
                    item.unlink()
            stuck.parent.mkdir(parents=True, exist_ok=True)
            stuck.write_bytes(b"still mapped")
            return None
        return real_rmtree(path, ignore_errors=ignore_errors, **kwargs)

    monkeypatch.setattr(bootstrap.shutil, "rmtree", partial)


def test_a_partly_deleted_previous_environment_is_reported_not_hidden(env, monkeypatch):
    _existing_venv(env)
    _successful_repair_fakes(monkeypatch)
    _leaving_one_file(monkeypatch)
    log = _Log()
    ok, message = bootstrap.repair_venv(log, headless=True)
    assert ok is True  # the environment itself was repaired and can launch
    assert "could not be deleted" in message and "removed the next time" in message
    assert "separately installed voice engine" not in message
    assert "[!!]" in log.text
    assert not os.path.lexists(bootstrap._venv_aside_path())  # never left under the name recovery restores
    assert (env.tmp / ".venv.discarded" / "Lib" / "site-packages" / "mapped.dll").exists()


def test_a_clean_discard_is_still_a_plain_success(env, monkeypatch):
    keepsake = _existing_venv(env)
    _successful_repair_fakes(monkeypatch)
    ok, message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is True and message == "The app's Python environment was repaired (Python 3.12)."
    assert not keepsake.exists() and not os.path.lexists(env.tmp / ".venv.discarded")


@pytest.mark.parametrize("parent_exists", [True, False])
def test_recovery_finishes_deleting_a_leftover_and_never_restores_it(env, monkeypatch, parent_exists):
    leftover = env.tmp / ".venv.discarded"
    _seed_interpreter(leftover)
    (leftover / "pyvenv.cfg").write_text("home = C:/base\n", encoding="utf-8")
    if parent_exists:
        keepsake = _existing_venv(env, marker="current")  # no import proof: an aside would have been put back
    bootstrap.recover_interrupted_replacement(_Log())
    assert not os.path.lexists(leftover)
    if parent_exists:
        assert keepsake.read_text(encoding="utf-8") == "current"
    else:
        assert not env.venv.exists()  # scrap is never promoted to the environment


def test_a_leftover_holding_an_engine_is_never_deleted(env):
    leftover = env.tmp / ".venv.discarded"
    engine = _plant_engine(leftover)
    log = _Log()
    bootstrap.recover_interrupted_replacement(log)
    assert _tree(_engine_in(leftover)) == engine and "[!!]" in log.text


@pytest.mark.skipif(not bootstrap.IS_WINDOWS, reason="an open handle only blocks a rename on Windows")
def test_a_real_open_handle_in_the_previous_environment_keeps_it_whole_and_is_reported(env, monkeypatch):
    """Not simulated: a handle a program still has open refuses the rename, so nothing of it is deleted at all."""
    _existing_venv(env)
    held = env.venv / "Lib" / "held.bin"
    held.parent.mkdir(parents=True)
    held.write_bytes(b"open in another program")
    _successful_repair_fakes(monkeypatch)
    real_commit = bootstrap.VenvReplacement.commit
    handles = []

    def commit_with_a_handle_open(self, log=None):
        handles.append(open(self.aside / "Lib" / "held.bin", "rb"))
        try:
            return real_commit(self, log)
        finally:
            handles[-1].close()

    monkeypatch.setattr(bootstrap.VenvReplacement, "commit", commit_with_a_handle_open)
    ok, message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is True and "could not be deleted" in message
    aside = bootstrap._venv_aside_path()
    assert (aside / "keepsake.txt").read_text(encoding="utf-8") == "previous"  # whole, not half-deleted
    assert (aside / "Lib" / "held.bin").exists()


# --------------------------------------------------------------------------- #
# F. Nothing held yet, or only a legacy engine: the lease is taken all the same (P04C Stage 2)
#
# Since the canonical engine is created inside .venv, "nothing under engines/" no longer means "nothing to protect": an
# install holding setup.lock may be about to create it. So the lease no longer depends on what the parent holds.
# --------------------------------------------------------------------------- #
def test_with_nothing_held_a_repair_still_takes_the_whole_lease_and_still_works(env, monkeypatch):
    keepsake = _existing_venv(env)
    _successful_repair_fakes(monkeypatch)
    taken: list[list[str]] = []
    real_take = el.Lease.take

    def spy(self):
        real_take(self)
        taken.append(list(self.taken))

    monkeypatch.setattr(el.Lease, "take", spy)
    ok, message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is True and not keepsake.exists() and (env.venv / "candidate.txt").exists()
    assert taken == [list(el.ORDER)]
    assert sorted(p.name for p in lock_dir(env).iterdir()) == sorted(el.ORDER)  # the three lock files and nothing else
    assert all((lock_dir(env) / name).stat().st_size == 0 for name in el.ORDER)
    assert free(lock_dir(env)) == ALL_FREE  # and all three given back


def test_a_legacy_engine_s_conversion_now_refuses_the_repair_and_changes_nothing(env, monkeypatch):
    """A ``.venv-qwen3`` conversion never moves with the parent, but its ``inference.lock`` is the same lock an install
    of the canonical engine holds; the repair cannot tell them apart, so it waits for either rather than race one."""
    keepsake = _existing_venv(env)
    _successful_repair_fakes(monkeypatch)
    with held_by_another_process("conversion", lock_dir(env)):
        ok, message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is False and "conversion" in message and "Nothing was changed" in message
    assert keepsake.read_text(encoding="utf-8") == "previous" and not (env.venv / "candidate.txt").exists()
    assert not os.path.lexists(bootstrap._venv_aside_path())


# --------------------------------------------------------------------------- #
# G. Boundaries
# --------------------------------------------------------------------------- #
def test_the_lease_module_and_the_worker_s_claim_are_standard_library_only():
    import ast

    for relative, allowed_local in (("shared/engine_lease.py", {"shared"}), ("tts/qwen3_worker.py", set())):
        tree = ast.parse((SCRIPTS / relative).read_text(encoding="utf-8"))
        top = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                top.add((node.module or "").split(".")[0])
        top -= {"__future__"} | allowed_local
        assert top <= set(sys.stdlib_module_names), (relative, top - set(sys.stdlib_module_names))


def test_the_set_aside_names_the_worker_refuses_are_the_bootstrap_s():
    assert bootstrap._venv_aside_path().name in worker.SET_ASIDE_NAMES
    assert bootstrap._venv_discard_path().name in worker.SET_ASIDE_NAMES
