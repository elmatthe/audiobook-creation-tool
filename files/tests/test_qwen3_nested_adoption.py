"""v0.7.0 P04C Stage 2 — the canonical Qwen3 engine at ``.venv/engines/qwen3``, and first installs that cannot race a repair.

**What changed.** New installs of the Qwen3 engine go to ``.venv/engines/qwen3`` only, created there directly by the
verified base CPython 3.12 the app's environment was built from (never by the app's own interpreter), with the identity
of that base recorded outside the parent (``state.json``). The path authority, ``qwen3_runtime.venv_dir``, picks the
legacy ``.venv-qwen3`` only while nothing is at the canonical path, and never falls back to it from a canonical engine
that is damaged, unverified or half-installed.

**The race this closes.** Stage 1 made the bootstrap take ``shared.engine_lease`` before touching a parent that holds
an engine. With nothing held yet, a repair could set ``.venv`` aside at the very moment a first install was creating
its engine inside it. Now the lease is taken whether or not anything is held, and the installer holds ``setup.lock``
(``InstallLock``) from its first check until the folder exists and is recorded, so whichever starts first wins and the
other refuses, changing nothing -- in both orders, with the engine's folder not yet existing.

Every environment, record and lock here lives in ``tmp_path``. Cross-process cases run the production installer, the
production lease or the production worker claim in real subprocesses; nothing touches ``.venv``, ``.venv-qwen3`` or
the real runtime folder.

**v0.8.2 Phase 5A.** New installs now go to the independent ``.venv-engines/qwen3``, built by uv from the engine's
locked project on this copy's managed CPython (``tts.qwen3_setup._install_uv_environment``); the base-interpreter
checks above belonged to the retired ``python -m venv`` + pip installer and live on only behind the test-only sealed
seam. What this module still proves: an earlier version's nested engine keeps working and is judged exactly as before
until the new one is installed; nothing is created through a link; and an install and a repair of the app's own
environment still refuse each other in both orders -- now with the engine beside ``.venv``, which a repair never
touches.
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

from test_qwen3_runtime import install_environment, sandbox  # noqa: F401  (sandbox is a fixture)
from test_qwen3_setup import FakeRunner, fake_runner, runner  # noqa: F401  (runner is a fixture)
from test_qwen3_lifecycle_locks import ALL_FREE, SCRIPTS, free, held_by_another_process, wait_free
from test_venv_recovery import (  # noqa: F401  (``env`` is a fixture)
    _Log, _existing_venv, _successful_repair_fakes, _tree, env,
)

NESTED_PARTS = (".venv", "engines", "qwen3")
ENGINE_PARTS = (".venv-engines", "qwen3")  # v0.8.2 Phase 5A: where every new install goes


def _is_uv(cmd, verb: str) -> bool:
    return Path(str(cmd[0])).name.lower() == "uv.exe" and len(cmd) > 1 and str(cmd[1]) == verb


def _tree_or_none(root: Path):
    return _tree(root) if root.exists() else None


# --------------------------------------------------------------------------- #
# A. Which engine is used: the selection matrix
# --------------------------------------------------------------------------- #
def test_with_nothing_installed_the_canonical_path_is_the_one_and_it_is_simply_not_installed(sandbox):
    assert rt.venv_dir() == sandbox.joinpath(*ENGINE_PARTS) and rt.is_canonical() and not rt.is_nested()
    ok, reason = rt.environment_status()
    assert not ok and "not installed on this computer" in reason and "nothing is downloaded until you ask" in reason
    assert "older engine" not in reason


def test_a_legacy_only_engine_keeps_working_exactly_as_before(sandbox):
    (sandbox / ".venv-qwen3").mkdir()
    install_environment(sandbox)
    assert rt.venv_dir() == sandbox / ".venv-qwen3" and not rt.is_nested()
    assert rt.venv_python() == venv_layout.interpreter(sandbox / ".venv-qwen3")
    assert rt.environment_status() == (True, "ok")
    assert "environment" in rt.read_state() and rt.NESTED_RECORD not in rt.read_state()  # its record, in its old shape
    assert rt.installed_probe()["torch"] == "2.10.0+cu128"
    assert not os.path.lexists(sandbox.joinpath(*NESTED_PARTS))  # using it never creates the canonical folder


def test_when_both_are_present_the_validated_canonical_engine_is_used(sandbox):
    (sandbox / ".venv-qwen3").mkdir()
    install_environment(sandbox)  # legacy, healthy
    legacy_record = dict(rt.read_state()["environment"])
    sandbox.joinpath(*NESTED_PARTS).mkdir(parents=True)
    install_environment(sandbox)  # now the canonical one
    assert rt.venv_dir() == sandbox.joinpath(*NESTED_PARTS)
    assert rt.environment_status() == (True, "ok")
    assert rt.read_state()["environment"] == legacy_record  # the legacy record is left as it was


def _rewrite_cfg(folder: Path, **changes) -> None:
    lines = []
    for line in (folder / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
        key = line.partition("=")[0].strip()
        lines.append(f"{key} = {changes.pop(key)}" if key in changes else line)
    lines.extend(f"{key} = {value}" for key, value in changes.items())
    (folder / "pyvenv.cfg").write_text("\n".join(lines) + "\n", encoding="utf-8")


DAMAGES = {
    # name: (damage(folder, sandbox), words the status must contain)
    "sees the system's packages": (lambda f, s: _rewrite_cfg(f, **{"include-system-site-packages": "true"}),
                                   "broken"),
    "has no interpreter": (lambda f, s: venv_layout.interpreter(f).unlink(), "broken"),
    "has no pyvenv.cfg": (lambda f, s: (f / "pyvenv.cfg").unlink(), "broken"),
    "was built from the parent's interpreter": (
        lambda f, s: _rewrite_cfg(f, home=s / ".venv" / "Scripts", executable=s / ".venv" / "Scripts" / "python.exe"),
        "broken"),
    "was created elsewhere and moved": (lambda f, s: _rewrite_cfg(f, command=f"x -m venv {s / 'elsewhere'}"),
                                        "cannot be verified"),
    "was built from a Python that has changed": (
        lambda f, s: (s / "base-python" / "python.exe").write_bytes(b"an upgraded base interpreter"),
        "cannot be verified"),
    "was built from a Python that is gone": (lambda f, s: (s / "base-python" / "python.exe").unlink(),
                                             "cannot be verified"),
    "has a record written for another folder": (
        lambda f, s: rt.atomic_write_json(rt.state_path(), {**rt.read_state(), rt.NESTED_RECORD: {
            **rt.read_state()[rt.NESTED_RECORD], "path": str(s / "elsewhere")}}),
        "cannot be verified"),
    "has no record at all": (lambda f, s: rt.clear_environment_state(f), "cannot be verified"),
    "was only created, never probed": (lambda f, s: rt.record_environment_stage(f, rt.STAGE_CREATED),
                                       "not installed completely"),
    "was being created when it stopped": (lambda f, s: rt.record_environment_stage(f, rt.STAGE_CREATING),
                                          "not installed completely"),
    "was being removed when it stopped": (lambda f, s: rt.record_environment_stage(f, rt.STAGE_REMOVING),
                                          "not installed completely"),
}


@pytest.mark.parametrize("legacy_too", [False, True], ids=["canonical only", "legacy present too"])
@pytest.mark.parametrize("damage", sorted(DAMAGES))
def test_a_damaged_canonical_engine_is_reported_never_hidden_behind_the_legacy_one(sandbox, damage, legacy_too):
    if legacy_too:
        (sandbox / ".venv-qwen3").mkdir()
        install_environment(sandbox)  # a healthy legacy engine
        assert rt.environment_status() == (True, "ok")
    sandbox.joinpath(*NESTED_PARTS).mkdir(parents=True)
    install_environment(sandbox)
    assert rt.environment_status() == (True, "ok")
    harm, words = DAMAGES[damage]
    harm(sandbox.joinpath(*NESTED_PARTS), sandbox)

    ok, reason = rt.environment_status()
    assert not ok and words in reason and "Install / repair Qwen3 voices" in reason, reason
    assert rt.venv_dir() == sandbox.joinpath(*NESTED_PARTS)  # still the one judged and the one any worker would use
    assert rt.venv_python() == venv_layout.interpreter(sandbox.joinpath(*NESTED_PARTS))
    assert ("The older engine in .venv-qwen3 is not used" in reason) is legacy_too


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows mechanism")
@pytest.mark.parametrize("linked", [".venv-engines", ".venv-engines/qwen3"])
def test_a_canonical_path_reached_through_a_link_is_unusable_and_nothing_is_created_through_it(
        sandbox, runner, linked, tmp_path):
    from test_qwen3_runtime import make_junction

    decoy = tmp_path / "files" / "decoy"
    decoy.mkdir(parents=True)
    link = sandbox.joinpath(*linked.split("/"))
    link.parent.mkdir(parents=True, exist_ok=True)
    make_junction(link, decoy)
    before = _tree(decoy)

    ok, reason = rt.environment_status()
    assert not ok and "link" in reason
    with pytest.raises(su.SetupError, match="link"):
        su.install_environment(runner=runner)
    assert runner.commands == [] and runner.base_probes == [] and _tree(decoy) == before
    assert rt.ENGINE_RECORD not in rt.read_state()


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows mechanism")
def test_a_legacy_location_that_is_a_link_is_never_used_and_the_install_goes_to_the_canonical_path(
        sandbox, runner, tmp_path):
    from test_qwen3_runtime import make_junction

    decoy = tmp_path / "files" / "legacy-decoy"
    (decoy / "Scripts").mkdir(parents=True)
    (decoy / "Scripts" / "python.exe").write_bytes(b"somebody's interpreter")
    (decoy / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    make_junction(sandbox / ".venv-qwen3", decoy)
    before = _tree(decoy)
    assert rt.venv_dir() == sandbox / ".venv-qwen3"  # legacy-only by presence, so it is the one judged
    ok, reason = rt.environment_status()
    assert not ok and ".venv-qwen3 is a link to another folder" in reason

    su.install_environment(runner=runner)  # never into the link: the canonical engine is created beside it

    assert _tree(decoy) == before and rt.venv_dir() == sandbox.joinpath(*ENGINE_PARTS)
    assert rt.environment_status() == (True, "ok")


# --------------------------------------------------------------------------- #
# B. Creating the canonical engine: where, from what, and what is recorded
# --------------------------------------------------------------------------- #
def test_a_first_install_creates_the_engine_at_its_final_path_on_the_managed_python(sandbox, runner, monkeypatch):
    from shared import engine_env

    stages: list[tuple[str, bool]] = []
    real_record = rt.record_environment_stage

    def watch(folder, stage):
        stages.append((stage, os.path.lexists(folder)))
        real_record(folder, stage)

    monkeypatch.setattr(rt, "record_environment_stage", watch)
    final = sandbox.joinpath(*ENGINE_PARTS)
    assert not os.path.lexists(final) and not os.path.lexists(sandbox / ".venv-qwen3")

    su.install_environment(runner=runner)

    venv_cmd = runner.commands[0]["cmd"]
    assert venv_cmd == [str(c) for c in engine_env.venv_command(sandbox, "qwen3")] and _is_uv(venv_cmd, "venv")
    assert Path(venv_cmd[2]).is_absolute() and venv_layout.same_path(venv_cmd[2], final)  # final, absolute
    assert _is_uv(runner.commands[1]["cmd"], "sync") and runner.base_probes == []  # no base interpreter is consulted
    assert stages == [(rt.STAGE_CREATING, False), (rt.STAGE_CREATED, True)]  # recorded before, then after, creation
    record = rt.read_state()[rt.ENGINE_RECORD]
    assert record["stage"] == rt.STAGE_INSTALLED and record["probe_ok"] is True and record["installer"] == "uv"
    assert venv_layout.same_path(record["path"], final)
    assert not rt.state_path().is_relative_to(sandbox / ".venv")  # outside the app's own environment
    assert rt.environment_status() == (True, "ok") and not os.path.lexists(sandbox / ".venv-qwen3")
    assert not os.path.lexists(sandbox / ".venv" / "engines")  # nothing is created inside the app's environment


class BuildsOnAnotherPython(FakeRunner):
    """``uv venv`` that writes a ``pyvenv.cfg`` naming a Python other than this copy's managed CPython."""

    def __call__(self, cmd, **kw):
        code = super().__call__(cmd, **kw)
        if _is_uv(cmd, "venv"):
            cfg = Path(cmd[2]) / "pyvenv.cfg"
            lines = [f"home = {self.base}" if line.startswith("home") else line
                     for line in cfg.read_text(encoding="utf-8").splitlines()]
            cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return code


def test_an_engine_built_on_any_other_python_is_not_used(sandbox, monkeypatch):
    fake = BuildsOnAnotherPython(sandbox.parent / f"{sandbox.name}-other-python")
    with pytest.raises(su.SetupError, match="could not be verified"):
        su.install_environment(runner=fake)
    assert [c["cmd"][1] for c in fake.commands] == ["venv"]  # no sync ran into it
    assert rt.environment_status()[0] is False


@pytest.mark.parametrize("problem", ["no pyvenv.cfg", "no parent at all", ".venv.replaced", ".venv.replaced-20261025"])
def test_the_independent_engine_never_reaches_into_the_app_s_own_environment(sandbox, runner, problem):
    """The engine beside ``.venv`` is built on the managed CPython, not from ``.venv`` and not inside it: the app's own
    environment, whatever its state (a repair's leftovers included), is neither read nor changed by the install."""
    parent = sandbox / ".venv"
    if problem in ("no pyvenv.cfg", "no parent at all"):
        (parent / "pyvenv.cfg").unlink()
        if problem == "no parent at all":
            parent.rmdir()
    else:
        (sandbox / problem).mkdir()
    before = {name: _tree_or_none(sandbox / name) for name in (".venv", problem)}
    su.install_environment(runner=runner)
    assert rt.environment_status() == (True, "ok") and rt.venv_dir() == sandbox.joinpath(*ENGINE_PARTS)
    assert {name: _tree_or_none(sandbox / name) for name in (".venv", problem)} == before


def test_a_leftover_that_is_only_awaiting_deletion_does_not_block_an_install(sandbox, runner):
    (sandbox / ".venv.discarded").mkdir()
    su.install_environment(runner=runner)
    assert rt.environment_status() == (True, "ok")


@pytest.mark.parametrize("stage", [rt.STAGE_CREATING, rt.STAGE_REMOVING])
def test_an_interrupted_install_or_removal_is_cleared_and_redone_by_the_next_install(sandbox, runner, stage):
    """A creation or deletion that stopped half-way leaves a folder with no ``pyvenv.cfg``; the record says it was the
    app's own, so the next install clears it (no rebuild needed) and builds it again."""
    final = sandbox.joinpath(*ENGINE_PARTS)
    (final / "Lib" / "site-packages").mkdir(parents=True)
    (final / "Lib" / "site-packages" / "half.py").write_text("x", encoding="utf-8")
    rt.record_environment_stage(final, stage)
    assert not rt.environment_status()[0] and "not installed completely" in rt.environment_status()[1]

    su.install_environment(runner=runner)

    assert not (final / "Lib" / "site-packages" / "half.py").exists() and rt.environment_status() == (True, "ok")


def test_an_engine_folder_the_app_cannot_vouch_for_is_left_alone_until_a_repair_rebuilds_it(sandbox, runner):
    final = sandbox.joinpath(*ENGINE_PARTS)
    final.mkdir(parents=True)
    install_environment(sandbox)
    rt.clear_environment_state(final)  # e.g. copied in from elsewhere: no record vouches for it
    (final / "Lib").mkdir()
    (final / "Lib" / "theirs.py").write_text("x", encoding="utf-8")
    before = _tree(final)
    with pytest.raises(su.SetupError, match="cannot be verified.*left as it is"):
        su.install_environment(runner=runner)  # an install never runs uv into it
    assert _tree(final) == before and runner.commands == []

    su.install_environment(runner=runner, rebuild=True)  # the repair path the message points to
    assert not (final / "Lib" / "theirs.py").exists() and rt.environment_status() == (True, "ok")


def test_a_repair_of_a_broken_legacy_engine_builds_the_canonical_one_and_says_so(sandbox, runner):
    legacy = sandbox / ".venv-qwen3"
    legacy.mkdir()
    install_environment(sandbox)
    rt.clear_environment_state(legacy)  # the legacy engine is incomplete
    (legacy / "Lib").mkdir()
    (legacy / "Lib" / "legacy.bin").write_bytes(b"legacy engine")
    before = _tree(legacy)
    plan = su.analyze_repair([], runner=runner)
    assert plan.rebuild_environment
    shown = "\n".join(su.describe_repair(plan))
    assert ".venv-engines\\qwen3" in shown or ".venv-engines/qwen3" in shown
    assert "not changed or deleted" in shown

    result = su.repair([], plan=plan, runner=runner, load_check=False, disk_free=lambda p: 10 ** 13)

    assert result.ok, result.message
    assert _tree(legacy) == before and "environment" not in rt.read_state()  # nothing was written for the legacy engine
    assert rt.venv_dir() == sandbox.joinpath(*ENGINE_PARTS) and rt.environment_status() == (True, "ok")


def test_the_install_plan_says_where_the_engine_goes_only_when_an_older_one_is_there(sandbox):
    assert su.legacy_engine_note() == []
    plain = su.describe_plan(su.plan_install(["customvoice"]))
    assert not any("older" in line for line in plain)
    (sandbox / ".venv-qwen3").mkdir()  # an empty (unusable) legacy folder: the engine needs installing
    lines = su.describe_plan(su.plan_install(["customvoice"]))
    assert any("new place" in line and "not changed or deleted" in line for line in lines)


def test_a_healthy_legacy_engine_is_not_reinstalled_when_a_model_is_added(sandbox):
    (sandbox / ".venv-qwen3").mkdir()
    install_environment(sandbox)
    plan = su.plan_install(["customvoice"])
    assert plan.needs_environment is False and su.legacy_engine_note() != []
    assert not any("new place" in line for line in su.describe_plan(plan))


def test_only_the_canonical_folder_can_ever_be_removed(sandbox):
    (sandbox / ".venv-qwen3").mkdir()
    install_environment(sandbox)
    assert su.safe_to_remove_environment(sandbox / ".venv-qwen3") is False  # never the legacy engine
    sandbox.joinpath(*NESTED_PARTS).mkdir(parents=True)
    install_environment(sandbox)
    assert su.safe_to_remove_environment(sandbox.joinpath(*NESTED_PARTS)) is True
    assert su.safe_to_remove_environment(sandbox / ".venv") is False
    assert su.safe_to_remove_environment(sandbox / ".venv" / "engines") is False


# --------------------------------------------------------------------------- #
# C. The installer's own locks: engine.lock checked, InstallLock never taken twice
# --------------------------------------------------------------------------- #
def test_an_engine_still_running_from_an_earlier_app_stops_an_install_and_nothing_is_changed(sandbox, runner):
    with held_by_another_process("worker", rt.runtime_dir()):
        with pytest.raises(su.SetupError, match="still running.*Nothing was changed"):
            su.install_environment(runner=runner)
        assert runner.base_probes == [] and runner.commands == []
        assert not os.path.lexists(sandbox.joinpath(*NESTED_PARTS))
        state = free(rt.runtime_dir())
        assert state["setup.lock"] and state["inference.lock"] and not state["engine.lock"]  # it gave back what it took


def test_the_installer_s_own_probe_can_take_the_engine_lock_while_the_install_lock_is_held(sandbox):
    with su.InstallLock():
        with held_by_another_process("worker", rt.runtime_dir()):  # READY only if the worker's claim succeeded
            pass
    assert free(rt.runtime_dir()) == ALL_FREE


def test_an_install_holds_the_install_lock_itself_and_reuses_one_already_held(sandbox, runner, monkeypatch):
    seen: list[dict] = []
    real_call = FakeRunner.__call__

    def observe(self, cmd, **kw):
        if _is_uv(cmd, "venv"):
            seen.append(free_from_another_process(rt.runtime_dir()))
        return real_call(self, cmd, **kw)

    monkeypatch.setattr(FakeRunner, "__call__", observe)
    su.install_environment(runner=runner)  # not called under InstallLock: it takes it
    with su.InstallLock():
        su.install_environment(runner=runner, rebuild=True)  # under one: reused, not taken twice (which would refuse)
    held = {"setup.lock": False, "inference.lock": False, "engine.lock": True}
    assert seen == [held, held]
    assert free(rt.runtime_dir()) == ALL_FREE and not su.InstallLock.held_by_this_thread()


_FREE_PROBE = textwrap.dedent("""
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from shared import engine_lease as el
    out = {}
    for name in el.ORDER:
        lock = el.FileLock(Path(sys.argv[2]) / name)
        out[name] = lock.acquire()
        lock.release()
    print(json.dumps(out))
""")


def free_from_another_process(folder: Path) -> dict:
    """``free`` asked by a different process (a lock held by this one is busy to it)."""
    proc = subprocess.run([sys.executable, "-c", _FREE_PROBE, str(SCRIPTS), str(folder)], capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize("first", ["repair lease", "install lock"])
def test_in_one_process_the_lease_and_the_install_lock_refuse_each_other_at_once(sandbox, first):
    """No reentrant wait: whichever is held, the other is refused immediately, in either order."""
    lease = el.Lease(rt.runtime_dir(), root=sandbox)
    if first == "repair lease":
        lease.take()
        started = time.monotonic()
        with pytest.raises(su.SetupError, match="being installed or repaired"):
            su.InstallLock().acquire()
        lease.release()
    else:
        with su.InstallLock():
            started = time.monotonic()
            with pytest.raises(el.Refused) as refused:
                lease.take()
        assert refused.value.lock == el.SETUP_LOCK and refused.value.reason == el.BUSY
    assert time.monotonic() - started < 2.0
    assert free(rt.runtime_dir()) == ALL_FREE and not su.InstallLock.held_by_this_thread()


# --------------------------------------------------------------------------- #
# D. The first-install race, in both orders, with the engine's folder not yet there
# --------------------------------------------------------------------------- #
_INSTALLER = textwrap.dedent("""
    import json, os, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    root, base, mode, guard = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5]
    from shared import uv_runner
    from tts import qwen3_runtime as rt
    from tts import qwen3_setup as su
    rt.repo_root = lambda: root
    rt.MACHINE_GUARD_NAME = guard
    uv_runner.uv_problem = lambda root, platform=None: ""  # the stand-in uv is never run: its identity is answered

    def runner(cmd, *, env, cwd, on_line, cancel_check=None):
        cmd = [str(c) for c in cmd]
        uv = Path(cmd[0]).name.lower() == "uv.exe"
        if uv and cmd[1] == "venv":
            target = Path(cmd[2])
            if mode in ("pause", "die"):
                print("CREATING " + str(os.path.lexists(target)), flush=True)  # InstallLock held, folder not made
            if mode == "pause":
                sys.stdin.readline()
            if mode == "die":
                (target / "Lib").mkdir(parents=True)
                (target / "Lib" / "half.py").write_text("x", encoding="utf-8")
                sys.stdin.readline()
                os._exit(3)
            (target / "Scripts").mkdir(parents=True)
            (target / "Scripts" / "python.exe").write_bytes(b"")
            (target / "pyvenv.cfg").write_text(
                f"home = {uv_runner.managed_venv_home(root, 'win32')}\\nimplementation = CPython\\n"
                f"uv = {uv_runner.UV_VERSION}\\nversion_info = {uv_runner.PYTHON_VERSION}\\n"
                "include-system-site-packages = false\\n", encoding="utf-8")
            return 0
        if uv and cmd[1] == "sync":
            return 0
        if cmd[1].endswith("qwen3_worker.py"):
            on_line("@@EVENT " + json.dumps({"event": "probe", "versions": {"torch": "test"}}))
            on_line("@@EVENT " + json.dumps({"event": "done"}))
            return 0
        raise SystemExit("unexpected command " + repr(cmd))

    try:
        su.install_environment(runner=runner)
    except su.SetupError as exc:
        print("REFUSED " + str(exc), flush=True)
        sys.exit(2)
    print("INSTALLED " + str(rt.venv_dir()), flush=True)
""")


@pytest.fixture()
def first_install(env, sandbox, monkeypatch):
    """A copy with a repairable ``.venv`` holding no engine, the Qwen3 requirements, and a base interpreter outside it."""
    keepsake = _existing_venv(env)
    _successful_repair_fakes(monkeypatch)
    faked_create = bootstrap.create_venv

    def create_a_real_looking_parent(argv, log):  # a rebuilt .venv has its pyvenv.cfg, as uv venv leaves it
        made = faked_create(argv, log)
        if made:
            # v0.8.2 Phase 4: uv builds the base environment on this copy's managed CPython and says so (``uv = ``).
            home = bootstrap.uv_runner.managed_venv_home(bootstrap.REPO_ROOT)
            (bootstrap.VENV_DIR / "pyvenv.cfg").write_text(
                f"home = {home}\nuv = {bootstrap.uv_runner.UV_VERSION}\ninclude-system-site-packages = false\n",
                encoding="utf-8")
        return made

    monkeypatch.setattr(bootstrap, "create_venv", create_a_real_looking_parent)
    (sandbox / "scripts" / "qwen3-requirements.txt").write_bytes(b"torch==1.0\n")
    base = sandbox.parent / f"{sandbox.name}-base" / "python.exe"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_bytes(b"base interpreter")
    assert bootstrap.VENV_DIR == sandbox / ".venv" and rt.runtime_dir() == sandbox / "files" / "runtime-data" / "qwen3"
    assert not os.path.lexists(sandbox / ".venv" / "engines")  # the child does not exist yet
    return keepsake, base


def _installer_argv(sandbox: Path, base: Path, mode: str) -> list[str]:
    return [sys.executable, "-c", _INSTALLER, str(SCRIPTS), str(sandbox), str(base), mode, rt.MACHINE_GUARD_NAME]


@contextlib.contextmanager
def installer_mid_creation(sandbox: Path, base: Path, mode: str = "pause"):
    """The production installer in another process, stopped inside ``uv venv``: InstallLock held, folder absent."""
    proc = subprocess.Popen(_installer_argv(sandbox, base, mode), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline().strip()
        assert line == "CREATING False", (line, proc.stderr.read() if proc.poll() is not None else "")
        yield proc
    finally:
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.stdin.close()
        proc.wait(timeout=60)


def run_installer(sandbox: Path, base: Path) -> tuple[int, str]:
    proc = subprocess.run(_installer_argv(sandbox, base, "now"), capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def test_install_first_a_repair_refuses_until_the_engine_exists_at_its_final_path(first_install, env, sandbox):
    keepsake, base = first_install
    with installer_mid_creation(sandbox, base) as installer:
        ok, message = bootstrap.repair_venv(_Log(), headless=True)  # the installer holds setup.lock, the folder is absent
        assert ok is False and "being installed or repaired" in message and "Nothing was changed" in message
        assert keepsake.read_text(encoding="utf-8") == "previous" and not (env.venv / "candidate.txt").exists()
        assert not os.path.lexists(bootstrap._venv_aside_path())
        installer.stdin.write("\n")
        installer.stdin.flush()
        out = installer.stdout.read()
        assert installer.wait(timeout=60) == 0 and "INSTALLED" in out, out
    child = sandbox.joinpath(*ENGINE_PARTS)
    assert child.is_dir() and keepsake.read_text(encoding="utf-8") == "previous"  # created beside the unchanged parent
    assert rt.environment_status() == (True, "ok") and not os.path.lexists(env.venv / "engines")

    engine = _tree(child)
    ok, message = bootstrap.repair_venv(_Log(), headless=True)  # once it is done, the repair goes ahead
    assert ok is True and (env.venv / "candidate.txt").exists(), message
    assert _tree(child) == engine and rt.environment_status() == (True, "ok")  # beside it, never touched


def test_install_first_first_run_setup_refuses_the_same_way(first_install, env, sandbox, monkeypatch):
    keepsake, base = first_install
    monkeypatch.setattr(bootstrap, "recover_interrupted_replacement",
                        lambda *a, **k: pytest.fail("setup recovered something under a running install"))
    with installer_mid_creation(sandbox, base) as installer:
        ok, message = bootstrap.run_setup(lambda *a: None, _Log(), headless=True)
        assert ok is False and message.startswith("Setup was not started.") and "Nothing was changed" in message
        assert keepsake.read_text(encoding="utf-8") == "previous"
        installer.stdin.write("\n")
        installer.stdin.flush()
        assert installer.wait(timeout=60) == 0


@pytest.mark.parametrize("moment", ["before recovery", "parent set aside", "packages being installed"])
def test_repair_first_a_new_install_refuses_and_nothing_is_created_under_the_parent_being_replaced(
        first_install, env, sandbox, monkeypatch, moment):
    keepsake, base = first_install
    attempts: list[tuple[int, str, bool, bool]] = []

    def try_to_install():
        code, out = run_installer(sandbox, base)
        attempts.append((code, out, os.path.lexists(env.venv / "engines") or os.path.lexists(sandbox / ".venv-engines"),
                         os.path.lexists(bootstrap._venv_aside_path() / "engines")))

    hook = {"before recovery": "recover_interrupted_replacement", "parent set aside": "create_venv",
            "packages being installed": "reconcile_requirements"}[moment]
    real = getattr(bootstrap, hook)

    def hooked(*args, **kwargs):
        try_to_install()
        return real(*args, **kwargs)

    monkeypatch.setattr(bootstrap, hook, hooked)
    ok, message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is True, message

    assert len(attempts) == 1
    code, out, engines_in_parent, engines_in_aside = attempts[0]
    assert code == 2 and "REFUSED" in out and "being installed or repaired" in out, out
    assert not engines_in_parent and not engines_in_aside  # nothing appeared under either while the repair ran
    assert not os.path.lexists(env.venv / "engines") and not os.path.lexists(bootstrap._venv_aside_path())
    assert rt.ENGINE_RECORD not in rt.read_state()

    code, out = run_installer(sandbox, base)  # after the repair: installed at its final path beside the new parent
    assert code == 0 and "INSTALLED" in out, out
    assert (env.venv / "candidate.txt").exists() and sandbox.joinpath(*ENGINE_PARTS).is_dir()
    assert rt.environment_status() == (True, "ok")


def test_an_installer_that_dies_mid_creation_frees_the_repair_and_its_leftover_is_redone(first_install, env, sandbox):
    keepsake, base = first_install
    with installer_mid_creation(sandbox, base, mode="die") as installer:
        installer.stdin.write("\n")
        installer.stdin.flush()
        assert installer.wait(timeout=60) == 3
    assert wait_free(rt.runtime_dir()) == ALL_FREE  # the operating system dropped every lock it held
    child = sandbox.joinpath(*ENGINE_PARTS)
    assert (child / "Lib" / "half.py").is_file() and rt.environment_record(child)["stage"] == rt.STAGE_CREATING

    ok, message = bootstrap.repair_venv(_Log(), headless=True)  # the half-made engine is beside it: never touched
    assert ok is True, message
    assert (child / "Lib" / "half.py").is_file()
    assert "not installed completely" in rt.environment_status()[1]

    code, out = run_installer(sandbox, base)
    assert code == 0, out
    assert not (child / "Lib" / "half.py").exists() and rt.environment_status() == (True, "ok")


def test_a_lock_that_cannot_be_checked_refuses_a_repair_even_before_any_engine_exists(first_install, env, sandbox):
    keepsake, _ = first_install
    rt.runtime_dir().mkdir(parents=True, exist_ok=True)
    (rt.runtime_dir() / el.ENGINE_LOCK).mkdir()  # a folder where the lock file goes: it cannot be opened
    ok, message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is False and "could not check whether the Qwen3 voices are in use" in message
    assert keepsake.read_text(encoding="utf-8") == "previous" and not os.path.lexists(bootstrap._venv_aside_path())


# --------------------------------------------------------------------------- #
# E. What a worker or installer subprocess inherits
# --------------------------------------------------------------------------- #
def _environment_folders(tmp_path: Path) -> dict[str, Path]:
    foreign_venv = tmp_path / "elsewhere-venv"
    (foreign_venv / "Scripts").mkdir(parents=True)
    (foreign_venv / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    conda = tmp_path / "conda-env"
    (conda / "conda-meta").mkdir(parents=True)
    (conda / "Library" / "bin").mkdir(parents=True)
    (conda / "Scripts").mkdir()
    cuda = tmp_path / "NVIDIA GPU Computing Toolkit" / "CUDA" / "v12.8" / "bin"
    cuda.mkdir(parents=True)
    base = tmp_path / "Python312"
    (base / "Scripts").mkdir(parents=True)
    return {"foreign": foreign_venv / "Scripts", "conda_bin": conda / "Library" / "bin", "conda_root": conda,
            "conda_scripts": conda / "Scripts", "cuda": cuda, "base": base, "base_scripts": base / "Scripts"}


def test_the_worker_environment_drops_steering_variables_and_other_environments_but_keeps_system_paths(
        sandbox, tmp_path):
    folders = _environment_folders(tmp_path)
    sandbox.joinpath(*NESTED_PARTS).mkdir(parents=True)
    install_environment(sandbox)
    own = venv_layout.interpreter(rt.venv_dir()).parent
    app = sandbox / ".venv" / "Scripts"
    app.mkdir()
    system = r"C:\Windows\System32"
    path = os.pathsep.join([str(folders["foreign"]), system, str(app), "", str(folders["conda_bin"]),
                            f'"{folders["conda_root"]}"', str(folders["cuda"]), str(own), str(folders["conda_scripts"]),
                            str(folders["base"]), str(folders["base_scripts"])])
    inherited = {"Path": path, "VIRTUAL_ENV": str(folders["foreign"].parent), "VIRTUAL_ENV_PROMPT": "(x)",
                 "PYTHONPATH": "x", "PYTHONHOME": "y", "PYTHONSAFEPATH": "1", "PYTHONWARNINGS": "error",
                 "PYTHONEXECUTABLE": "z", "PYTHONUSERBASE": "u", "PIP_TARGET": "t", "pip_index_url": "i",
                 "PIP_REQUIRE_VIRTUALENV": "0", "__PYVENV_LAUNCHER__": "l", "CONDA_PREFIX": "c",
                 "CONDA_DEFAULT_ENV": "base", "SystemRoot": r"C:\Windows", "CUDA_PATH": str(folders["cuda"].parent),
                 "PATHEXT": ".COM;.EXE", "ComSpec": r"C:\Windows\System32\cmd.exe", "NVIDIA_VISIBLE": "1"}

    env = rt.worker_environment(inherited)

    assert env["Path"].split(os.pathsep) == [system, str(folders["cuda"]), str(own), str(folders["base"]),
                                             str(folders["base_scripts"])]
    for gone in ("VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "PYTHONPATH", "PYTHONHOME", "PYTHONSAFEPATH", "PYTHONWARNINGS",
                 "PYTHONEXECUTABLE", "PYTHONUSERBASE", "PIP_TARGET", "pip_index_url", "PIP_REQUIRE_VIRTUALENV",
                 "__PYVENV_LAUNCHER__", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"):
        assert gone not in env, gone
    for kept in ("SystemRoot", "CUDA_PATH", "PATHEXT", "ComSpec", "NVIDIA_VISIBLE"):
        assert env[kept] == inherited[kept], kept
    assert env["PYTHONNOUSERSITE"] == "1" and env["PYTHONUTF8"] == "1" and env["HF_HUB_OFFLINE"] == "1"


def test_the_installer_environment_is_scrubbed_the_same_way(sandbox, tmp_path, monkeypatch):
    folders = _environment_folders(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join([str(folders["foreign"]), str(folders["cuda"])]))
    monkeypatch.setenv("VIRTUAL_ENV", str(folders["foreign"].parent))
    monkeypatch.setenv("PYTHONPATH", "x")
    monkeypatch.setenv("PIP_INDEX_URL", "https://example.invalid/simple")
    env = su.installer_environment()
    path_key = next(k for k in env if k.upper() == "PATH")
    assert env[path_key].split(os.pathsep) == [str(folders["cuda"])]
    assert "VIRTUAL_ENV" not in env and "PYTHONPATH" not in env and "PIP_INDEX_URL" not in env
    assert env["PIP_CONFIG_FILE"] == os.devnull


def test_the_real_environment_of_this_test_run_loses_only_environment_folders(sandbox):
    """Against this machine's real PATH: nothing that is not a Python environment's folder is ever dropped."""
    real = os.environ.get("PATH", "")
    kept = rt.worker_environment()[next(k for k in os.environ if k.upper() == "PATH")].split(os.pathsep)
    dropped = [e for e in real.split(os.pathsep) if e.strip() and e not in kept]
    for entry in dropped:
        folder = Path(entry.strip().strip('"'))
        assert any((c / "pyvenv.cfg").is_file() for c in (folder, folder.parent)) or \
            any((c / "conda-meta").is_dir() for c in (folder, folder.parent, folder.parent.parent)), entry
