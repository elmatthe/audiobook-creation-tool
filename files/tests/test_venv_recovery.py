"""PRE-PLAN-6 Phase 2 — venv liveness, recovery, and the launcher handoff.

**The defect this file pins down.** The Windows launcher decided the environment
was fine by asking whether ``.venv\\Scripts\\pythonw.exe`` existed, and macOS by
asking whether ``.venv/bin/python`` was executable. Both are questions about a
*file*, not about an environment: a venv whose Python no longer runs, that lost
``ssl``, or that sits on a Python too new for the pinned voice engines still has
that file. ``bootstrap.main`` then returned from ``--launch-only`` before
``venv_is_valid()`` was ever consulted, so every recovery path the setup code
already owned was structurally unreachable from a normal launch.

**The contract now.** Bootstrap owns one health authority,
:func:`assess_venv_health`, which classifies rather than answers yes/no. The
launchers know nothing about Python versions, ssl or Tk; they ask, and act on an
exit code. A venv cannot replace itself — Windows locks the running
``python.exe`` — so replacement is requested with
:data:`bootstrap.EXIT_VENV_REPAIR_REQUIRED` and performed from a base
interpreter.

**Scope boundaries this file also guards.** Recovery goes through
``repair_venv``, never through ``run_setup``: the latter reaches
``ensure_ffmpeg`` and, beyond it, portable FFmpeg acquisition, which Phase 3
exists to make safe *before* a launch can reach it. And a missing or stale
package is never a reason to rebuild an environment.

Every environment here is built in ``tmp_path``. Nothing touches the real venv,
installs anything, or provisions FFmpeg.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared import bootstrap  # noqa: E402
from shared import venv_layout  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BAT = REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.bat"
COMMAND = REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.command"

WINDOWS_ONLY = pytest.mark.skipif(not bootstrap.IS_WINDOWS,
                                  reason="exercises the Windows .bat launcher")


class _Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def env(monkeypatch, tmp_path):
    """A disposable venv location, fully detached from the real one."""
    venv = tmp_path / ".venv"
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("pillow==12.2.0\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "VENV_DIR", venv)
    monkeypatch.setattr(bootstrap, "REQUIREMENTS_FILE", reqs)
    monkeypatch.setattr(bootstrap, "LOGS_DIR", tmp_path / "logs")
    return SimpleNamespace(venv=venv, reqs=reqs, tmp=tmp_path)


def _fake_interpreter(env) -> Path:
    """A file where the venv interpreter goes, so ``exists()`` is satisfied."""
    py = bootstrap.venv_python()
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_bytes(b"not a real interpreter")
    return py


def _seed_interpreter(root: Path) -> Path:
    """Put an interpreter under ``root`` at the layout *this* platform uses.

    Derived from ``venv_python()`` relative to ``VENV_DIR`` rather than spelled
    out, because that relative path is ``Scripts/python.exe`` on Windows and
    ``bin/python`` on macOS and Linux. Seeding a set-aside environment with a
    hard-coded ``Scripts`` produced an aside that production restored correctly
    and ``assess_venv_health`` then classified ``absent``, because the
    interpreter it looks for was not where the test had put it — so a test
    written to be cross-platform could only ever pass on Windows.
    """
    interpreter = root / bootstrap.venv_python().relative_to(bootstrap.VENV_DIR)
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_bytes(b"interpreter")
    return interpreter


def _probe(version=(3, 12), ssl=True, tk=True):
    return {"version": version, "ssl": ssl, "tk": tk}


# --------------------------------------------------------------------------- #
# A. Health is classified, not reduced to a boolean
# --------------------------------------------------------------------------- #
def test_no_environment_at_all_is_absent(env):
    health = bootstrap.assess_venv_health()
    assert health.state == bootstrap.VENV_ABSENT
    assert health.can_launch is False


def test_an_interpreter_that_cannot_execute_is_repairable(env, monkeypatch):
    """The case the old existence test could not see."""
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: None)

    health = bootstrap.assess_venv_health()

    assert health.state == bootstrap.VENV_REPAIRABLE
    assert health.reason == "interpreter-dead"
    assert health.can_launch is False


def test_a_healthy_environment_is_healthy(env, monkeypatch):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    health = bootstrap.assess_venv_health()

    assert health.state == bootstrap.VENV_HEALTHY
    assert health.is_fully_healthy is True
    assert health.can_launch is True


def test_a_311_environment_is_healthy(env, monkeypatch):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 11)))
    assert bootstrap.assess_venv_health().state == bootstrap.VENV_HEALTHY


def test_a_missing_ssl_environment_is_repairable(env, monkeypatch):
    """pip and Edge TTS both need ssl, so this is a real failure."""
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(ssl=False))

    health = bootstrap.assess_venv_health()

    assert health.state == bootstrap.VENV_REPAIRABLE
    assert health.reason == "no-ssl"


def test_a_313_environment_with_a_compatible_base_is_repairable(env, monkeypatch):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 13)))

    health = bootstrap.assess_venv_health(compatible_base_available=True)

    assert health.state == bootstrap.VENV_REPAIRABLE
    assert health.reason == "incompatible-python"


def test_a_313_environment_with_no_compatible_base_is_degraded_not_broken(
        env, monkeypatch):
    """It runs. Rebuilding it every launch would achieve nothing but churn."""
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 13)))

    health = bootstrap.assess_venv_health(compatible_base_available=False)

    assert health.state == bootstrap.VENV_DEGRADED
    assert health.can_launch is True
    assert health.is_fully_healthy is False


def test_a_tkless_environment_with_a_better_base_is_repairable(env, monkeypatch):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(tk=False))

    health = bootstrap.assess_venv_health(compatible_base_available=True)

    assert health.state == bootstrap.VENV_REPAIRABLE
    assert health.reason == "no-tk"


def test_a_tkless_environment_with_no_better_base_is_degraded(env, monkeypatch):
    """The CLI still works; destroying it every launch would not help."""
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(tk=False))

    health = bootstrap.assess_venv_health(compatible_base_available=False)

    assert health.state == bootstrap.VENV_DEGRADED
    assert health.reason == "no-tk-unfixable"
    assert health.can_launch is True


def test_tk_is_not_required_in_headless_mode(env, monkeypatch):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(tk=False))
    assert bootstrap.assess_venv_health(require_tk=False).state == bootstrap.VENV_HEALTHY


def test_tk_health_means_tk_actually_initialises_not_that_tkinter_imports():
    """Homebrew python@3.12 imports tkinter fine and then cannot open a window; and Tcl() alone never loads Tk at all
    (audit ACT67-AUD-006). The proof is a real, withdrawn, destroyed Tk root; test_tk_proof.py runs it for real."""
    assert "_root = tkinter.Tk()" in bootstrap._VENV_PROBE and "_root.withdraw()" in bootstrap._VENV_PROBE
    assert "Tcl()" not in bootstrap._VENV_PROBE


def test_the_whole_assessment_costs_one_subprocess(env, monkeypatch):
    """It is on the launch path; four spawns (probe_capabilities) is too many."""
    _fake_interpreter(env)
    calls: list = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"version": [3, 12, 10], "ssl": True, "tk": True}),
            stderr="")

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    bootstrap.assess_venv_health()
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# B. The launch path acts on health instead of ignoring it
# --------------------------------------------------------------------------- #
@pytest.fixture
def launch_spies(monkeypatch):
    """Neutralise everything after the health gate so routing is what is tested."""
    seen = {"launched": 0, "ffmpeg": 0, "kokoro": 0}
    monkeypatch.setattr(bootstrap, "launch_gui",
                        lambda log: seen.__setitem__("launched", seen["launched"] + 1) or True)
    monkeypatch.setattr(
        bootstrap, "ensure_ffmpeg_ready_for_launch",
        lambda: seen.__setitem__("ffmpeg", seen["ffmpeg"] + 1)
        or bootstrap.FFmpegRepair(True, (bootstrap.FFMPEG_ROUTE_EXISTING,)))
    monkeypatch.setattr(bootstrap, "kokoro_is_healthy",
                        lambda py: (seen.__setitem__("kokoro", seen["kokoro"] + 1), (True, "ok"))[1])
    monkeypatch.setattr(bootstrap, "requirements_are_current", lambda: True)
    monkeypatch.setattr(bootstrap, "required_modules_present", lambda py: (True, "ok"))
    monkeypatch.setattr(bootstrap, "import_proof_is_current", lambda: True)
    monkeypatch.setattr(bootstrap, "show_warning_dialog", lambda *a, **k: None)
    return seen


def test_a_healthy_environment_launches_without_any_repair(env, monkeypatch,
                                                           launch_spies):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    rc = bootstrap._launch_with_kokoro_healthcheck()

    assert rc == 0
    assert launch_spies["launched"] == 1


def test_a_dead_interpreter_asks_the_launcher_for_a_repair(env, monkeypatch,
                                                           launch_spies):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: None)

    rc = bootstrap._launch_with_kokoro_healthcheck()

    assert rc == bootstrap.EXIT_VENV_REPAIR_REQUIRED
    assert launch_spies["launched"] == 0


def test_a_broken_ssl_environment_asks_the_launcher_for_a_repair(env, monkeypatch,
                                                                 launch_spies):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(ssl=False))
    assert bootstrap._launch_with_kokoro_healthcheck() == \
        bootstrap.EXIT_VENV_REPAIR_REQUIRED


def test_a_313_environment_asks_for_repair_when_a_312_can_be_had(
        env, monkeypatch, launch_spies):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 13)))
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))

    assert bootstrap._launch_with_kokoro_healthcheck() == \
        bootstrap.EXIT_VENV_REPAIR_REQUIRED


def test_a_313_environment_launches_degraded_when_nothing_better_exists(
        env, monkeypatch, launch_spies):
    """No compatible Python anywhere: launch and say so, do not loop."""
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 13)))
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: None)

    rc = bootstrap._launch_with_kokoro_healthcheck()

    assert rc == 0
    assert launch_spies["launched"] == 1


def test_a_tkless_environment_launches_degraded_when_nothing_better_exists(
        env, monkeypatch, launch_spies):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(tk=False))
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: None)

    rc = bootstrap._launch_with_kokoro_healthcheck()

    assert rc == 0
    assert launch_spies["launched"] == 1


def test_a_repair_never_asks_for_a_second_repair(env, monkeypatch, launch_spies):
    """The loop guard: after a repair, still-imperfect means launch, not retry."""
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 13)))
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))

    rc = bootstrap._launch_with_kokoro_healthcheck(allow_repair_handoff=False)

    assert rc == 0
    assert launch_spies["launched"] == 1


def test_an_unusable_environment_after_a_repair_fails_truthfully(
        env, monkeypatch, launch_spies):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: None)

    rc = bootstrap._launch_with_kokoro_healthcheck(allow_repair_handoff=False)

    assert rc == 1
    assert launch_spies["launched"] == 0


# --------------------------------------------------------------------------- #
# C. Repair scope — packages are repaired in place, FFmpeg is never provisioned
# --------------------------------------------------------------------------- #
def test_repair_venv_never_reaches_ffmpeg_provisioning():
    """Structural, on the parsed tree: Phase 3 owns making that route safe."""
    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "repair_venv")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "ensure_ffmpeg" not in called
    assert "_install_ffmpeg" not in called
    assert "run_setup" not in called
    # What it must do instead.
    assert "_create_validated_venv" in called
    assert "reconcile_requirements" in called


def test_the_repair_entry_point_never_reaches_run_setup():
    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_repair_and_launch")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "run_setup" not in called
    assert "ensure_ffmpeg" not in called
    assert "repair_venv" in called


def test_a_repair_run_installs_no_ffmpeg(env, monkeypatch):
    """Behavioural companion to the structural guard above."""
    touched: list[str] = []
    monkeypatch.setattr(bootstrap, "ensure_ffmpeg",
                        lambda log: touched.append("ensure_ffmpeg") or True)
    monkeypatch.setattr(bootstrap, "_install_ffmpeg",
                        lambda log: touched.append("_install_ffmpeg") or True)
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    monkeypatch.setattr(bootstrap, "_create_validated_venv",
                        lambda argv, log, headless, txn=None: True)
    monkeypatch.setattr(bootstrap, "reconcile_requirements",
                        lambda log: (True, bootstrap.RECONCILE_OK))
    monkeypatch.setattr(bootstrap, "assess_venv_health",
                        lambda **kw: bootstrap.VenvHealth(
                            bootstrap.VENV_HEALTHY, "ok", "ok",
                            version=(3, 12), ssl=True, tk=True, executes=True))

    ok, _msg = bootstrap.repair_venv(_Log())

    assert ok is True
    assert touched == []


def test_a_package_problem_does_not_rebuild_the_environment(env, monkeypatch):
    """Phase 1 owns packages. A missing module is not an environment failure."""
    rebuilt: list[str] = []
    monkeypatch.setattr(bootstrap, "_create_validated_venv",
                        lambda *a, **k: rebuilt.append("rebuild") or True)
    monkeypatch.setattr(bootstrap, "pip_install_requirements", lambda log: True)
    monkeypatch.setattr(bootstrap, "validate_installed_packages", lambda log: True)

    ok, _msg = bootstrap.repair_missing_requirements(_Log(), "MISSING:pydub")

    assert ok is True
    assert rebuilt == []


def test_a_missing_ffmpeg_never_triggers_an_environment_rebuild(env, monkeypatch,
                                                                launch_spies):
    """FFmpeg absence is the preserved HOME-PC condition; it is not a venv fault."""
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    rc = bootstrap._launch_with_kokoro_healthcheck()

    assert rc == 0
    assert launch_spies["ffmpeg"] == 1     # detection still runs
    assert launch_spies["launched"] == 1   # and it still launches


# --------------------------------------------------------------------------- #
# D. Replacement is rollback-safe
# --------------------------------------------------------------------------- #
def test_a_failed_rebuild_restores_the_previous_environment(env, monkeypatch):
    """The invariant: never leave the user with nothing.

    The old code deleted the environment and only then tried to build one. A
    failing ``create_venv`` — no base interpreter, no disk, an interrupted run —
    left a machine that had been working a moment earlier with nothing at all.
    """
    py = _fake_interpreter(env)
    marker = env.venv / "keepsake.txt"
    marker.write_text("the previous environment", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "venv_is_valid", lambda: False)
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    monkeypatch.setattr(bootstrap, "create_venv", lambda argv, log: False)

    ok = bootstrap._create_validated_venv(["py", "-3.12"], _Log(), False)

    assert ok is False
    assert env.venv.is_dir()
    assert marker.read_text(encoding="utf-8") == "the previous environment"
    assert py.exists()


def test_a_replacement_that_cannot_import_ssl_gives_the_old_one_back(env, monkeypatch):
    marker = env.venv / "keepsake.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("the previous environment", encoding="utf-8")
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "venv_is_valid", lambda: False)
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))

    def fake_create(argv, log):
        bootstrap.VENV_DIR.mkdir(parents=True, exist_ok=True)
        return True

    monkeypatch.setattr(bootstrap, "create_venv", fake_create)
    monkeypatch.setattr(bootstrap, "probe_capabilities",
                        lambda py: {"ssl": False, "tcl_tk_functional": False,
                                    "tkinter": False, "venv": True})

    ok = bootstrap._create_validated_venv(["py", "-3.12"], _Log(), False)

    assert ok is False
    assert marker.exists(), "a worse replacement replaced a usable environment"


def test_a_successful_rebuild_discards_the_set_aside_copy(env, monkeypatch):
    """Rollback safety must not leave a duplicate environment behind forever."""
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "venv_is_valid", lambda: False)
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))

    def fake_create(argv, log):
        bootstrap.VENV_DIR.mkdir(parents=True, exist_ok=True)
        return True

    monkeypatch.setattr(bootstrap, "create_venv", fake_create)
    monkeypatch.setattr(bootstrap, "probe_capabilities",
                        lambda py: {"ssl": True, "tcl_tk_functional": True,
                                    "tkinter": True, "venv": True})

    ok = bootstrap._create_validated_venv(["py", "-3.12"], _Log(), False)

    assert ok is True
    assert not bootstrap._venv_aside_path().exists()


def test_setting_aside_is_a_rename_not_a_copy(env):
    """Same volume, so it is atomic and costs nothing on a large environment."""
    _fake_interpreter(env)
    aside = bootstrap._move_venv_aside(_Log())
    assert aside is not None
    assert aside.parent == env.venv.parent
    assert not env.venv.exists()
    assert bootstrap._restore_venv(aside, _Log()) is True
    assert env.venv.is_dir()


# --------------------------------------------------------------------------- #
# E. An import proof belongs to the interpreter that produced it
# --------------------------------------------------------------------------- #
def test_a_replaced_interpreter_invalidates_the_import_proof(env):
    """Phase 2 can swap the interpreter under an otherwise-matching stamp."""
    py = _fake_interpreter(env)
    bootstrap.record_import_proof("3.12.10")
    assert bootstrap.import_proof_is_current() is True

    # A rebuild writes a new python.exe: different bytes, different timestamp.
    py.write_bytes(b"a different interpreter entirely")
    os.utime(py, ns=(0, 1))

    assert bootstrap.import_proof_is_current() is False


def test_a_rebuilt_environment_cannot_inherit_the_old_proof(env, monkeypatch):
    _fake_interpreter(env)
    bootstrap.record_import_proof("3.12.10")
    assert bootstrap.import_proof_path().exists()

    monkeypatch.setattr(bootstrap, "venv_is_valid", lambda: False)
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    monkeypatch.setattr(bootstrap, "create_venv",
                        lambda argv, log: bootstrap.VENV_DIR.mkdir(parents=True,
                                                                   exist_ok=True) or True)
    monkeypatch.setattr(bootstrap, "probe_capabilities",
                        lambda py: {"ssl": True, "tcl_tk_functional": True,
                                    "tkinter": True, "venv": True})

    bootstrap._create_validated_venv(["py", "-3.12"], _Log(), False)

    assert not bootstrap.import_proof_path().exists()
    assert bootstrap.import_proof_is_current() is False


def test_a_proof_without_an_interpreter_identity_is_re_proved(env):
    """Records written before Phase 2 simply have nothing to match."""
    _fake_interpreter(env)
    bootstrap.record_import_proof("3.12.10")
    payload = json.loads(bootstrap.import_proof_path().read_text(encoding="utf-8"))
    del payload["interpreter"]
    bootstrap.import_proof_path().write_text(json.dumps(payload), encoding="utf-8")

    assert bootstrap.import_proof_is_current() is False


def test_the_proof_window_is_still_one_named_constant():
    assert bootstrap.IMPORT_PROOF_MAX_AGE_DAYS == 7


# --------------------------------------------------------------------------- #
# F. The launchers, run for real in a sandbox
# --------------------------------------------------------------------------- #
def _sandbox(tmp_path: Path, *, exit_code: int | None, runnable: bool = True,
             venv_present: bool = True) -> Path:
    """A copy of the real launcher beside a stub bootstrap that answers as told.

    ``exit_code`` is what the stub returns for ``--venv-check``; ``runnable``
    decides whether the venv interpreter is a real one or a file that merely
    exists. A first-run fixture never creates an environment just to delete it.
    """
    root = tmp_path / "tree"
    (root / "scripts" / "shared").mkdir(parents=True)
    if venv_present:
        (root / ".venv" / "Scripts").mkdir(parents=True)

    if venv_present and runnable:
        subprocess.run([sys.executable, "-m", "venv", "--without-pip",
                        str(root / ".venv")], capture_output=True, check=True)
    elif venv_present:
        (root / ".venv" / "Scripts" / "python.exe").write_bytes(b"not an executable")
    # pythonw.exe only has to exist for the fast path's launch step.
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    if venv_present and not pythonw.exists():
        pythonw.write_bytes(b"")

    stub = root / "scripts" / "shared" / "bootstrap.py"
    stub.write_text(
        "import sys, pathlib\n"
        "log = pathlib.Path(__file__).resolve().parents[2] / 'calls.log'\n"
        "with log.open('a', encoding='utf-8') as fh:\n"
        "    fh.write(' '.join(sys.argv[1:]) + '\\n')\n"
        f"sys.exit({exit_code if exit_code is not None else 0})\n",
        encoding="utf-8")
    (root / BAT.name).write_bytes(BAT.read_bytes())
    return root


def _calls(root: Path) -> list[str]:
    log = root / "calls.log"
    return log.read_text(encoding="utf-8").split("\n") if log.exists() else []


@WINDOWS_ONLY
def test_a_healthy_environment_launches_once_and_does_not_repair(tmp_path):
    root = _sandbox(tmp_path, exit_code=0)

    r = subprocess.run(["cmd", "/c", str(root / BAT.name)], cwd=root,
                       capture_output=True, text=True, timeout=120)

    assert r.returncode == 0
    calls = _calls(root)
    assert "--venv-check" in calls
    assert not any("--repair-venv" in c for c in calls)


@WINDOWS_ONLY
def test_an_environment_bootstrap_calls_unhealthy_is_repaired(tmp_path):
    root = _sandbox(tmp_path, exit_code=bootstrap.EXIT_VENV_REPAIR_REQUIRED)

    r = subprocess.run(["cmd", "/c", str(root / BAT.name)], cwd=root,
                       capture_output=True, text=True, timeout=180)

    calls = _calls(root)
    assert "--venv-check" in calls
    assert any("--repair-venv" in c for c in calls), r.stdout
    assert "repairing the app environment" in r.stdout.lower()


@WINDOWS_ONLY
def test_an_interpreter_that_cannot_run_at_all_is_repaired(tmp_path):
    """Bootstrap cannot report this: it never gets to start."""
    root = _sandbox(tmp_path, exit_code=0, runnable=False)

    r = subprocess.run(["cmd", "/c", str(root / BAT.name)], cwd=root,
                       capture_output=True, text=True, timeout=180)

    assert any("--repair-venv" in c for c in _calls(root)), r.stdout


@WINDOWS_ONLY
def test_a_missing_environment_still_runs_first_time_setup(tmp_path):
    root = _sandbox(tmp_path, exit_code=0, venv_present=False)
    assert not (root / ".venv").exists()

    r = subprocess.run(["cmd", "/c", str(root / BAT.name)], cwd=root,
                       capture_output=True, text=True, timeout=180)

    assert "first-time setup" in r.stdout.lower()
    calls = _calls(root)
    assert not any("--venv-check" in c for c in calls)
    assert not any("--repair-venv" in c for c in calls)


# --------------------------------------------------------------------------- #
# G. Launcher contracts that are cheaper to state than to run
# --------------------------------------------------------------------------- #
def test_the_windows_launcher_asks_bootstrap_instead_of_looking_for_a_file():
    text = BAT.read_text(encoding="utf-8", errors="replace")
    assert "--venv-check" in text
    assert "--repair-venv" in text
    assert "--launch-only" in text
    # The old contract, gone: existence of pythonw.exe is no longer the gate.
    assert 'if exist ".venv\\Scripts\\pythonw.exe"' not in text


def test_the_windows_launcher_still_launches_without_a_console():
    """The healthy steady state keeps its instant, console-free start."""
    text = BAT.read_text(encoding="utf-8", errors="replace")
    assert 'start "" ".venv\\Scripts\\pythonw.exe"' in text


def test_the_windows_launcher_owns_no_python_version_policy():
    """Version, ssl and Tk rules live in bootstrap, in one place."""
    text = BAT.read_text(encoding="utf-8", errors="replace").lower()
    for leaked in ("import ssl", "tkinter", "3.13", "version_info"):
        assert leaked not in text


def test_the_macos_launcher_acts_on_the_repair_exit_code():
    text = COMMAND.read_text(encoding="utf-8", errors="replace")
    assert "VENV_REPAIR_REQUIRED=3" in text
    assert "--repair-venv" in text
    assert "--launch-only" in text


def test_the_macos_launcher_notices_an_unrunnable_interpreter():
    text = COMMAND.read_text(encoding="utf-8", errors="replace")
    assert 'elif [ -e ".venv/bin/python" ]' in text


def test_the_repair_exit_code_is_not_an_overloaded_one():
    assert bootstrap.EXIT_VENV_REPAIR_REQUIRED == 3
    assert bootstrap.EXIT_VENV_REPAIR_REQUIRED != bootstrap.EXIT_SETUP_CANCELLED
    assert bootstrap.EXIT_VENV_REPAIR_REQUIRED not in (0, 1)


def test_python_is_never_installed_on_the_computer():
    """Reachable from an ordinary repair, and CSPW-PC has no admin rights. v0.7.0 portable layout: nothing is installed
    in any scope; the app's own Python is downloaded into its folder by stage 0."""
    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "install_python")
    literals = [n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert "winget" not in literals and "--scope" not in literals

    text = BAT.read_text(encoding="utf-8", errors="replace")
    assert "bootstrap_host.ps1" in text  # the launcher hands Python acquisition to stage 0
    stage0 = (BAT.parent / "scripts" / "shared" / "bootstrap_host.ps1").read_text(encoding="ascii")
    assert "winget" not in stage0 and "InstallAllUsers" not in stage0
    assert "files\\runtime-data\\python" in stage0


def test_the_ffmpeg_winget_command_is_left_alone():
    """M5's FFmpeg half belongs to a later phase; only Python changed here."""
    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_install_ffmpeg")
    literals = [n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert "--scope" not in literals


# --------------------------------------------------------------------------- #
# H. The replacement transaction (Phase 2 remediation)
#
# The first cut of Phase 2 preserved the old environment, but not for long
# enough and not on every path. Review found four related gaps, all of which
# come down to the same thing: replacing an environment is a transaction, and it
# is not finished when the new interpreter can import ssl.
#
#   1. A Tk-broken environment passes venv_is_valid (interpreter + ssl), so it
#      was never set aside -- and the recreate step then rmtree'd it outright.
#   2. The aside was discarded when the candidate's capabilities passed, before
#      repair_venv had installed or proved a single package.
#   3. The replace decision used _is_kokoro_compatible (floor 3.10) while the
#      health model used is_full_feature_python (floor 3.11), so a 3.10 venv
#      could be called incompatible and then kept.
#   4. The final report read the version of the *base* interpreter, which says
#      nothing about the environment that actually ended up on disk.
# --------------------------------------------------------------------------- #
def _reconcile_spy(monkeypatch, *, pip_ok=True, validate_ok=True):
    calls = {"pip": 0, "validate": 0}

    def fake_pip(log):
        calls["pip"] += 1
        return pip_ok

    def fake_validate(log):
        calls["validate"] += 1
        return validate_ok

    monkeypatch.setattr(bootstrap, "pip_install_requirements", fake_pip)
    monkeypatch.setattr(bootstrap, "validate_installed_packages", fake_validate)
    return calls


def _existing_venv(env, marker: str = "previous") -> Path:
    """An environment on disk with something identifiable inside it."""
    keepsake = env.venv / "keepsake.txt"
    keepsake.parent.mkdir(parents=True, exist_ok=True)
    keepsake.write_text(marker, encoding="utf-8")
    _fake_interpreter(env)
    return keepsake


def _creates_venv(monkeypatch, *, ok=True):
    def fake_create(argv, log):
        if not ok:
            return False
        (bootstrap.VENV_DIR / "Scripts").mkdir(parents=True, exist_ok=True)
        (bootstrap.VENV_DIR / "candidate.txt").write_text("new", encoding="utf-8")
        _fake_interpreter(SimpleNamespace(venv=bootstrap.VENV_DIR))
        return True

    monkeypatch.setattr(bootstrap, "create_venv", fake_create)


def _caps(ssl=True, tk=True):
    return {"ssl": ssl, "tcl_tk_functional": tk, "tkinter": tk, "venv": True}


# --- Gap 1: a Tk-broken environment is preserved before it is replaced ------ #
def _versions(monkeypatch, *, venv, base):
    """Make the venv interpreter and the base report different versions.

    Load-bearing for the 3.10 case: with a single flat stub both sides look
    alike and the replace decision cannot be observed at all.
    """
    venv_exe = str(bootstrap.venv_python())

    def fake_version(argv):
        return venv if argv and str(argv[0]) == venv_exe else base

    monkeypatch.setattr(bootstrap, "_interp_version_argv", fake_version)


def test_a_tk_broken_environment_is_set_aside_before_replacement(env, monkeypatch):
    """The exact Gap-1 precondition: venv_is_valid says yes, Tk says no.

    ``venv_is_valid`` tests the interpreter and ssl only, so a Tk-broken
    environment passed it — and nothing set it aside before the recreate step
    deleted it outright.
    """
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "venv_is_valid", lambda: True)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(tk=False))
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps(tk=False))
    _versions(monkeypatch, venv=(3, 12), base=(3, 12))
    _creates_venv(monkeypatch, ok=False)          # the replacement fails

    ok = bootstrap._create_validated_venv(["py", "-3.12"], _Log(), False)

    assert ok is False
    assert keepsake.exists(), "a CLI-capable environment was destroyed"
    assert keepsake.read_text(encoding="utf-8") == "previous"


def test_a_tk_broken_environment_is_replaced_when_a_better_base_exists(env, monkeypatch):
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "venv_is_valid", lambda: True)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(tk=False))
    _versions(monkeypatch, venv=(3, 12), base=(3, 12))
    _creates_venv(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())

    ok = bootstrap._create_validated_venv(["py", "-3.12"], _Log(), False)

    assert ok is True
    assert (env.venv / "candidate.txt").exists()
    assert not keepsake.exists()
    assert not bootstrap._venv_aside_path().exists()


def test_nothing_destroys_an_environment_it_did_not_create(env, monkeypatch):
    """The recreate step may only ever discard a candidate."""
    keepsake = _existing_venv(env)
    # Healthy enough to keep, but the capability probe disagrees about Tk.
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(tk=False))
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 13))
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps(tk=False))
    monkeypatch.setattr(bootstrap, "create_venv",
                        lambda argv, log: pytest.fail("must not rebuild"))

    bootstrap._create_validated_venv(["py", "-3.13"], _Log(), False)

    assert keepsake.exists()


# --- Gap 2: the transaction spans package install and real imports ---------- #
def test_a_pip_failure_after_a_new_venv_restores_the_previous_one(env, monkeypatch):
    """Capabilities passing is not the commit point."""
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: None)   # dead: replace
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    _creates_venv(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    _reconcile_spy(monkeypatch, pip_ok=False)

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is False
    assert keepsake.exists(), "the old environment was gone before pip even ran"
    assert keepsake.read_text(encoding="utf-8") == "previous"
    assert "put back" in message
    assert not (env.venv / "candidate.txt").exists()


def test_an_import_failure_after_a_new_venv_restores_the_previous_one(env, monkeypatch):
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: None)
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    _creates_venv(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    _reconcile_spy(monkeypatch, validate_ok=False)

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is False
    assert keepsake.exists()
    assert "put back" in message


def test_no_success_state_is_written_when_the_replacement_fails(env, monkeypatch):
    """Phase 1's rules are untouched by the transaction change."""
    _existing_venv(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: None)
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    _creates_venv(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    _reconcile_spy(monkeypatch, validate_ok=False)

    bootstrap.repair_venv(_Log())

    assert not bootstrap.requirements_state_path().exists()
    assert not bootstrap.import_proof_path().exists()


def test_a_committed_replacement_removes_the_previous_environment(env, monkeypatch):
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    _creates_venv(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    _reconcile_spy(monkeypatch)

    # The real health authority throughout: dead until the candidate exists,
    # healthy afterwards. Stubbing it out would have hidden the replace
    # decision, which is the thing under test.
    def staged_probe(py):
        return _probe() if (bootstrap.VENV_DIR / "candidate.txt").exists() else None

    monkeypatch.setattr(bootstrap, "probe_venv", staged_probe)

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is True
    assert not keepsake.exists()
    assert (env.venv / "candidate.txt").exists()
    assert not bootstrap._venv_aside_path().exists()
    assert "repaired" in message


# --- Gap 3: one compatibility authority, floor 3.11 ------------------------- #
def test_a_310_environment_is_replaced_by_a_312_base(env, monkeypatch):
    """3.10 satisfies Kokoro's floor and not the project's. The project wins.

    ``venv_is_valid`` is True here on purpose: the 3.10 environment runs and has
    ssl, so the only thing that can decide to replace it is the version
    predicate — which is exactly the one that was wrong.
    """
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "venv_is_valid", lambda: True)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 10)))
    _versions(monkeypatch, venv=(3, 10), base=(3, 12))
    _creates_venv(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())

    ok = bootstrap._create_validated_venv(["py", "-3.12"], _Log(), False)

    assert ok is True
    assert not keepsake.exists(), "the 3.10 environment was kept"
    assert (env.venv / "candidate.txt").exists()


def test_the_two_compatibility_predicates_disagree_about_310_on_purpose():
    """The bug was using the wrong one; both still exist and mean what they say."""
    assert bootstrap._is_kokoro_compatible((3, 10)) is True
    assert bootstrap.is_full_feature_python((3, 10)) is False


def test_a_310_environment_with_no_better_base_is_not_called_healthy(env, monkeypatch):
    _existing_venv(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 10)))

    health = bootstrap.assess_venv_health(compatible_base_available=False)

    assert health.state == bootstrap.VENV_DEGRADED
    assert health.is_fully_healthy is False
    assert health.can_launch is True


def test_a_310_environment_is_not_replaced_when_the_base_is_no_better(env, monkeypatch):
    """Nothing better to build with means churn, not repair."""
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 10)))
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 10))
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    monkeypatch.setattr(bootstrap, "create_venv",
                        lambda argv, log: pytest.fail("must not rebuild"))

    bootstrap._create_validated_venv(["py", "-3.10"], _Log(), False)

    assert keepsake.exists()


# --- Gap 4: report the environment that exists, not the base that built it -- #
def test_a_repair_reports_the_resulting_venv_not_the_selected_base(env, monkeypatch):
    """Base 3.12, resulting venv still 3.10: no full-health claim."""
    _existing_venv(env)
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    monkeypatch.setattr(bootstrap, "_create_validated_venv",
                        lambda argv, log, headless, txn=None: True)
    _reconcile_spy(monkeypatch)
    # The environment on disk did not actually become 3.12.
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 10)))

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is True                      # usable
    assert "repaired (Python" not in message   # but not claimed as full health
    assert "limits" in message
    assert "3.10" in message


def test_a_repair_that_leaves_an_unusable_venv_is_reported_as_failure(env, monkeypatch):
    _existing_venv(env)
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    monkeypatch.setattr(bootstrap, "_create_validated_venv",
                        lambda argv, log, headless, txn=None: True)
    _reconcile_spy(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: None)   # dead

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is False
    assert "still not usable" in message


def test_a_successful_repair_names_the_version_the_venv_actually_has(env, monkeypatch):
    _existing_venv(env)
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    monkeypatch.setattr(bootstrap, "_create_validated_venv",
                        lambda argv, log, headless, txn=None: True)
    _reconcile_spy(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 11)))

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is True
    assert "3.11" in message


# --- Interrupted repairs -------------------------------------------------- #
def test_an_aside_left_with_no_environment_is_restored(env, monkeypatch):
    """Interruption A: renamed aside, killed before a candidate existed."""
    aside = bootstrap._venv_aside_path()
    (aside / "Scripts").mkdir(parents=True)
    (aside / "keepsake.txt").write_text("previous", encoding="utf-8")

    bootstrap.recover_interrupted_replacement(_Log())

    assert env.venv.is_dir()
    assert (env.venv / "keepsake.txt").read_text(encoding="utf-8") == "previous"
    assert not aside.exists()


def test_an_unproven_candidate_loses_to_the_preserved_environment(env, monkeypatch):
    """Interruption B: both present, candidate never finished its proof."""
    aside = bootstrap._venv_aside_path()
    (aside / "Scripts").mkdir(parents=True)
    (aside / "keepsake.txt").write_text("previous", encoding="utf-8")
    (env.venv / "Scripts").mkdir(parents=True)
    (env.venv / "candidate.txt").write_text("unproven", encoding="utf-8")

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "keepsake.txt").exists()
    assert not (env.venv / "candidate.txt").exists()
    assert not aside.exists()


def _interrupted_both(env, *, proved: bool = True) -> Path:
    """Both directories present: a preserved environment and a candidate."""
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    (aside / "keepsake.txt").write_text("previous", encoding="utf-8")
    _fake_interpreter(env)
    (env.venv / "candidate.txt").write_text("candidate", encoding="utf-8")
    if proved:
        bootstrap.record_import_proof("3.12.10")
    return aside


def test_an_interrupted_aside_is_seeded_with_this_platform_s_venv_layout(env):
    """The recovery fixtures must describe *this* platform's venv, not Windows'.

    ``aside / "Scripts" / <python>`` is where a Windows venv keeps its
    interpreter; on macOS and Linux it is ``bin/``. Seeding the Windows shape on
    a Mac produced an aside that production restored perfectly — the log says
    "Restored the previous environment; nothing was lost." — and that
    ``assess_venv_health`` then called ``absent``, because the interpreter was
    not where ``venv_python()`` looks. The repair therefore reported failure for
    a reason that existed only in the test. Asserted behaviourally: after a real
    restore, production must find its interpreter.
    """
    aside = _interrupted_both(env)

    assert (aside / bootstrap.venv_python().relative_to(bootstrap.VENV_DIR)).is_file()

    assert bootstrap._restore_venv(aside, _Log()) is True
    assert bootstrap.venv_python().is_file(), \
        "a restored aside must satisfy the interpreter production looks for"


def test_a_proved_and_launchable_candidate_supersedes_the_preserved_environment(
        env, monkeypatch):
    """Both halves of the commit condition, so the transaction had finished."""
    aside = _interrupted_both(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "candidate.txt").exists()
    assert not aside.exists()


def test_a_proved_but_unlaunchable_candidate_does_not_win(env, monkeypatch):
    """The interruption window the import proof alone could not see.

    pip succeeded, the imports were proved, the proof was written -- and the
    process died before the final health check ever ran. Treating the proof as
    the whole commit condition deleted a working environment on the strength of
    a candidate nobody had confirmed could launch.
    """
    aside = _interrupted_both(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: None)   # will not run

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "keepsake.txt").read_text(encoding="utf-8") == "previous"
    assert not (env.venv / "candidate.txt").exists()
    assert not aside.exists()


def test_a_proved_candidate_that_lost_ssl_does_not_win(env, monkeypatch):
    """Same window, a different way for the candidate to be unusable."""
    aside = _interrupted_both(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(ssl=False))

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "keepsake.txt").exists()
    assert not aside.exists()


def test_recovery_uses_the_same_health_meaning_as_the_commit(env, monkeypatch):
    """A degraded-but-launchable candidate is committable, so it wins.

    ``can_launch``, not ``is_fully_healthy`` -- the same meaning repair_venv
    uses immediately before commit. A different standard here would make
    recovery disagree with the transaction it is completing.
    """
    aside = _interrupted_both(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 13)))

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "candidate.txt").exists()
    assert not aside.exists()


def test_an_interrupted_headless_repair_is_not_judged_against_a_gui_standard(
        env, monkeypatch):
    """A headless transaction never claimed Tk, so recovery must not demand it."""
    aside = _interrupted_both(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(tk=False))

    bootstrap.recover_interrupted_replacement(_Log(), require_tk=False)

    assert (env.venv / "candidate.txt").exists()
    assert not aside.exists()


def test_a_tkless_candidate_is_launchable_under_either_context(env, monkeypatch):
    """Honest about what ``require_tk`` does and does not decide here.

    With no better base available, a Tk-less environment is *degraded*, and
    degraded still launches — so the Tk context changes the state that gets
    reported, not whether the candidate may commit. The context is threaded
    through anyway so recovery evaluates the identical call to the one
    ``repair_venv`` makes before committing; a divergence there is precisely how
    the two would drift apart later.
    """
    aside = _interrupted_both(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(tk=False))
    gui = bootstrap.assess_venv_health(require_tk=True,
                                       compatible_base_available=False)
    headless = bootstrap.assess_venv_health(require_tk=False,
                                            compatible_base_available=False)

    assert gui.state == bootstrap.VENV_DEGRADED
    assert headless.state == bootstrap.VENV_HEALTHY
    assert gui.can_launch is headless.can_launch is True

    bootstrap.recover_interrupted_replacement(_Log(), require_tk=True)

    assert (env.venv / "candidate.txt").exists()
    assert not aside.exists()


def test_an_unlaunchable_candidate_loses_under_both_contexts(env, monkeypatch):
    """The conditions that do decide it are context-independent, by design."""
    for require_tk in (True, False):
        aside = _interrupted_both(env)
        monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(ssl=False))

        bootstrap.recover_interrupted_replacement(_Log(), require_tk=require_tk)

        assert (env.venv / "keepsake.txt").exists(), require_tk
        shutil.rmtree(env.venv, ignore_errors=True)


def test_both_callers_pass_their_own_tk_context():
    """Recovery must not silently apply a standard the caller did not choose."""
    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for name in ("repair_venv", "run_setup"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        call = next(c for c in ast.walk(fn)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id == "recover_interrupted_replacement")
        assert [kw.arg for kw in call.keywords] == ["require_tk"], name


def test_no_new_success_marker_file_was_introduced(env, monkeypatch):
    """Recovery re-evaluates the existing authorities; it records nothing new."""
    aside = _interrupted_both(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    before = {p.name for p in env.venv.iterdir()}

    bootstrap.recover_interrupted_replacement(_Log())

    assert {p.name for p in env.venv.iterdir()} == before
    assert not aside.exists()


def test_a_repair_recovers_before_starting_a_new_transaction(env, monkeypatch):
    """Interruption A, then the next repair: no manual deletion anywhere."""
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    (aside / "keepsake.txt").write_text("previous", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    _creates_venv(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    _reconcile_spy(monkeypatch)

    ok, _message = bootstrap.repair_venv(_Log())

    assert ok is True
    assert env.venv.is_dir()
    assert not aside.exists()


def test_an_aside_is_never_silently_overwritten(env):
    """If one somehow survives, a second gets a unique name rather than eating it."""
    aside = bootstrap._venv_aside_path()
    (aside / "Scripts").mkdir(parents=True)
    (aside / "keepsake.txt").write_text("previous", encoding="utf-8")
    _fake_interpreter(env)

    second = bootstrap._move_venv_aside(_Log())

    assert second is not None
    assert second != aside
    assert (aside / "keepsake.txt").read_text(encoding="utf-8") == "previous"


def test_first_run_setup_also_recovers_an_interrupted_repair():
    """An interrupted repair leaves no .venv, which looks like a fresh machine."""
    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "run_setup")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "recover_interrupted_replacement" in called


def test_a_rollback_that_failed_is_not_reported_as_success(env, monkeypatch):
    txn = bootstrap.VenvReplacement(None)
    assert txn.rollback(_Log()) is False

    aside = bootstrap._venv_aside_path()
    (aside / "Scripts").mkdir(parents=True)
    txn = bootstrap.VenvReplacement(aside)
    monkeypatch.setattr(bootstrap, "_restore_venv", lambda a, log: False)
    assert txn.rollback(_Log()) is False


def test_the_second_launch_after_a_repair_is_an_ordinary_fast_path(env, monkeypatch,
                                                                   launch_spies):
    """No repair loop: a committed replacement just launches next time."""
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    first = bootstrap._launch_with_kokoro_healthcheck()
    second = bootstrap._launch_with_kokoro_healthcheck()

    assert (first, second) == (0, 0)
    assert launch_spies["launched"] == 2
    assert not bootstrap._venv_aside_path().exists()


# --------------------------------------------------------------------------- #
# I. The launcher's "any non-zero means repair" rule is safe
#
# The .bat cannot tell "bootstrap ran and returned 3" from "the interpreter
# could not start" -- cmd reports both as a non-zero errorlevel, and the second
# is precisely the case bootstrap cannot report, because it never runs. So the
# launcher treats every non-zero answer as a repair request.
#
# That is only defensible because a repair request is not itself destructive.
# --repair-venv re-asks the health authority, and an environment that turns out
# to be healthy is kept, not replaced. So an unrelated bootstrap failure costs a
# reconcile pass, never the environment. These tests hold that property in place,
# since it is what makes the coarse launcher rule acceptable.
# --------------------------------------------------------------------------- #
def test_a_spurious_repair_request_does_not_replace_a_healthy_environment(
        env, monkeypatch):
    """The safety net under the launcher's coarse exit-code rule."""
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "venv_is_valid", lambda: True)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    _versions(monkeypatch, venv=(3, 12), base=(3, 12))
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    monkeypatch.setattr(bootstrap, "create_venv",
                        lambda argv, log: pytest.fail("a healthy environment was replaced"))
    _reconcile_spy(monkeypatch)

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is True
    assert keepsake.read_text(encoding="utf-8") == "previous"
    assert "repaired" in message


def test_the_launcher_treats_every_non_zero_check_as_a_repair_request():
    """Documented on purpose: cmd cannot distinguish the dead-interpreter case."""
    text = BAT.read_text(encoding="utf-8", errors="replace")
    assert "if errorlevel 1 goto needsrepair" in text


def test_the_repair_request_code_is_what_bootstrap_actually_returns(env, monkeypatch):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: None)
    monkeypatch.setattr(bootstrap, "show_warning_dialog", lambda *a, **k: None)

    assert bootstrap._venv_check() == bootstrap.EXIT_VENV_REPAIR_REQUIRED


def test_a_healthy_environment_answers_the_check_with_zero(env, monkeypatch):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    assert bootstrap._venv_check() == 0


def test_a_degraded_environment_answers_the_check_with_zero(env, monkeypatch):
    """Degraded launches. Only a genuine repair opportunity returns 3."""
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 13)))
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: None)

    assert bootstrap._venv_check() == 0


def _interrupted_repair(env, *, aside_engine=True, candidate_engine=False) -> Path:
    """What a repair killed during pip leaves: a candidate whose interpreter runs, and the aside it replaced."""
    _fake_interpreter(env)
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    if aside_engine:
        (aside / "engines" / "qwen3").mkdir(parents=True)
    if candidate_engine:
        (env.venv / "engines" / "qwen3").mkdir(parents=True)
    return aside


def test_an_unfinished_repair_is_a_repair_request_even_when_the_candidate_runs(env, monkeypatch):
    """HOME-PC 2026-10-30: the candidate's interpreter already ran, so the health check called it healthy and the
    launcher used it, while the replaced environment and its Qwen3 engine stayed set aside."""
    _interrupted_repair(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())  # healthy on its own
    assert bootstrap.unfinished_replacement() is True
    assert bootstrap._venv_check() == bootstrap.EXIT_VENV_REPAIR_REQUIRED


def test_the_launch_path_hands_an_unfinished_repair_back_before_touching_packages(env, monkeypatch):
    _interrupted_repair(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    monkeypatch.setattr(bootstrap, "requirements_are_current",
                        lambda *a, **k: pytest.fail("packages were reconciled into an unproved candidate"))
    monkeypatch.setattr(bootstrap, "launch_gui", lambda *a, **k: pytest.fail("an unproved candidate was launched"))
    assert bootstrap._launch_with_kokoro_healthcheck() == bootstrap.EXIT_VENV_REPAIR_REQUIRED


def test_the_unresolvable_both_hold_an_engine_state_never_becomes_a_repair_on_every_launch(env, monkeypatch):
    """Recovery leaves this one alone on purpose (it chooses neither engine); asking for a repair would loop."""
    _interrupted_repair(env, candidate_engine=True)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    assert bootstrap.unfinished_replacement() is False
    assert bootstrap._venv_check() == 0


def test_without_an_aside_nothing_changes(env, monkeypatch):
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    assert bootstrap.unfinished_replacement() is False
    assert bootstrap._venv_check() == 0


# --------------------------------------------------------------------------- #
# J. A refused rename is a failed replacement, never a kept-and-reported one
#
# On Windows another process (an indexer, a scanner, an editor's file watcher)
# can hold a directory open for a millisecond or two, and while it does,
# os.replace of that directory fails with WinError 5. _move_venv_aside reported
# that by returning None, and _create_validated_venv carried on regardless: it
# kept the environment it had just decided must be replaced, reconciled packages
# into it, and repair_venv told the user "The environment was rebuilt, with
# limits" when nothing had been rebuilt. This was caught as an intermittent
# failure of the 3.10 and Tk-broken replacement tests above.
#
# The rule now: when a replacement is required, the old environment must have
# been moved aside before anything is created in its place. If it cannot be,
# the repair stops and says so, with the old environment exactly as it was.
# Short-lived refusals (WinError 5 and 32 only) get a few retries of the same
# rename inside one bounded window, driven here by a controlled clock.
# --------------------------------------------------------------------------- #
class _Clock:
    """Stands in for the retry's monotonic clock and sleep."""

    def __init__(self, *, oversleep: float = 0.0) -> None:
        self.start = self.now = 1000.0
        self.oversleep = oversleep
        self.sleeps: list[float] = []
        self.planned_wakes: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.planned_wakes.append(self.now + seconds)
        self.now += seconds + self.oversleep


def _controlled_time(monkeypatch, **kwargs) -> _Clock:
    clock = _Clock(**kwargs)
    monkeypatch.setattr(bootstrap, "_aside_monotonic", clock.monotonic)
    monkeypatch.setattr(bootstrap, "_aside_sleep", clock.sleep)
    return clock


def _win_error(code: int | None) -> OSError:
    """A refusal carrying ``code`` as its Windows error, on any platform."""
    exc = PermissionError(13, "Access is denied")
    exc.winerror = code
    return exc


def _always(code: int | None):
    while True:
        yield _win_error(code)


def _refusing_rename(monkeypatch, refusals, clock: _Clock | None = None,
                     *, cost: float = 0.0) -> list:
    """``os.replace`` that refuses to move the venv, then really moves it.

    Each attempt on the venv takes the next exception from ``refusals`` and
    raises it; once they run out the real rename happens. Every other rename
    (restoring an aside, pytest's own) goes straight through. Returns the
    attempts, stamped with the controlled clock's time when there is one;
    ``cost`` is how long each attempt takes on that clock.
    """
    real_replace = os.replace
    pending = iter(refusals)
    attempts: list = []

    def fake_replace(src, dst, *args, **kwargs):
        if Path(src) == bootstrap.VENV_DIR:
            attempts.append(clock.now if clock is not None else None)
            if clock is not None:
                clock.now += cost
            exc = next(pending, None)
            if exc is not None:
                raise exc
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(bootstrap.os, "replace", fake_replace)
    return attempts


def _no_aside_exists(env) -> bool:
    return not any(p.name.startswith(bootstrap._venv_aside_path().name)
                   for p in env.tmp.iterdir())


def test_a_refused_aside_stops_the_replacement_before_anything_is_built(
        env, monkeypatch):
    """Scenario A, first-run ownership: the replace decision stands or nothing happens."""
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setattr(bootstrap, "venv_is_valid", lambda: True)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(tk=False))
    _versions(monkeypatch, venv=(3, 12), base=(3, 12))
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    monkeypatch.setattr(bootstrap, "create_venv",
                        lambda argv, log: pytest.fail("built over an environment "
                                                      "that was never set aside"))
    clock = _controlled_time(monkeypatch)
    _refusing_rename(monkeypatch, _always(5), clock)
    log = _Log()

    ok = bootstrap._create_validated_venv(["py", "-3.12"], log, False)

    assert ok is False
    assert keepsake.read_text(encoding="utf-8") == "previous"
    assert bootstrap.venv_python().read_bytes() == b"not a real interpreter"
    assert _no_aside_exists(env)
    assert "Could not set the existing environment aside" in log.text
    assert "venv ready" not in log.text


def test_a_refused_aside_is_a_truthful_repair_failure(env, monkeypatch):
    """Scenario A through repair_venv: the exact false success that was observed.

    A 3.10 environment runs, so with the rename refused the old code kept it,
    reconciled into it and reported "rebuilt, with limits".
    """
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setattr(bootstrap, "venv_is_valid", lambda: True)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 10)))
    _versions(monkeypatch, venv=(3, 10), base=(3, 12))
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    monkeypatch.setattr(bootstrap, "create_venv",
                        lambda argv, log: pytest.fail("built over an environment "
                                                      "that was never set aside"))
    calls = _reconcile_spy(monkeypatch)
    clock = _controlled_time(monkeypatch)
    _refusing_rename(monkeypatch, _always(5), clock)
    log = _Log()

    ok, message = bootstrap.repair_venv(log)

    assert ok is False
    assert "could not be rebuilt" in message
    assert "with limits" not in message and "repaired" not in message
    assert calls == {"pip": 0, "validate": 0}, "packages went into the old environment"
    assert keepsake.read_text(encoding="utf-8") == "previous"
    assert _no_aside_exists(env)
    assert not bootstrap.requirements_state_path().exists()
    assert not bootstrap.import_proof_path().exists()
    assert "Could not set the existing environment aside" in log.text


@pytest.mark.parametrize("code", [5, 32])
def test_a_momentary_refusal_is_retried_and_the_replacement_goes_ahead(
        env, monkeypatch, code):
    """Scenario B: one refusal, then the same rename succeeds and the transaction runs."""
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    _creates_venv(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    _reconcile_spy(monkeypatch)
    monkeypatch.setattr(
        bootstrap, "probe_venv",
        lambda py: _probe() if (bootstrap.VENV_DIR / "candidate.txt").exists() else None)
    clock = _controlled_time(monkeypatch)
    attempts = _refusing_rename(monkeypatch, [_win_error(code)], clock)

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is True
    assert "repaired" in message
    assert len(attempts) == 2
    assert len(clock.sleeps) == 1
    assert not keepsake.exists()
    assert (env.venv / "candidate.txt").exists()
    assert _no_aside_exists(env)


@pytest.mark.parametrize("oversleep, cost", [(0.0, 0.0), (0.1, 0.0), (0.0, 0.06)])
def test_a_refusal_that_persists_is_retried_inside_one_bounded_window(
        env, monkeypatch, oversleep, cost):
    """Scenario C: bounded by attempts and by the clock, then an honest None.

    ``oversleep`` makes every sleep run long and ``cost`` makes every refused
    rename slow, as a busy machine can, so the deadline rather than the attempt
    count is what has to stop it: no attempt starts after it, and no sleep is
    begun that would only end beyond it.
    """
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    clock = _controlled_time(monkeypatch, oversleep=oversleep)
    attempts = _refusing_rename(monkeypatch, _always(5), clock, cost=cost)
    log = _Log()

    assert bootstrap._move_venv_aside(log) is None

    window_end = clock.start + bootstrap._ASIDE_RETRY_BUDGET_S
    assert 1 < len(attempts) <= len(bootstrap._ASIDE_RETRY_DELAYS_S) + 1
    assert all(t <= window_end for t in attempts)
    assert all(t <= window_end for t in clock.planned_wakes)
    assert sum(clock.sleeps) <= bootstrap._ASIDE_RETRY_BUDGET_S
    assert keepsake.read_text(encoding="utf-8") == "previous"
    assert _no_aside_exists(env)
    assert "Could not set the existing environment aside" in log.text


def test_the_retry_window_is_the_one_the_owner_approved():
    assert bootstrap._ASIDE_RETRY_BUDGET_S <= 0.25
    assert sum(bootstrap._ASIDE_RETRY_DELAYS_S) <= bootstrap._ASIDE_RETRY_BUDGET_S
    assert set(bootstrap._ASIDE_TRANSIENT_WINERRORS) == {5, 32}


@pytest.mark.parametrize("code", [None, 2, 3, 17, 183])
def test_any_other_refusal_fails_at_once(env, monkeypatch, code):
    """Scenario D: not access-denied or a sharing violation, so not retried."""
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    clock = _controlled_time(monkeypatch)
    attempts = _refusing_rename(monkeypatch, _always(code), clock)

    assert bootstrap._move_venv_aside(_Log()) is None

    assert len(attempts) == 1
    assert clock.sleeps == []
    assert keepsake.read_text(encoding="utf-8") == "previous"
    assert _no_aside_exists(env)


def test_off_windows_a_refusal_is_never_retried(env, monkeypatch):
    """Non-Windows semantics are unchanged, whatever the exception carries."""
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
    clock = _controlled_time(monkeypatch)
    attempts = _refusing_rename(monkeypatch, _always(5), clock)

    assert bootstrap._move_venv_aside(_Log()) is None

    assert len(attempts) == 1
    assert clock.sleeps == []
    assert keepsake.exists()


def test_a_retry_never_lands_on_an_aside_that_appeared_meanwhile(env, monkeypatch):
    """The guard is re-checked before every retry, not only the first attempt."""
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    clock = _controlled_time(monkeypatch)
    aside = bootstrap._venv_aside_path()

    def sleep_while_an_aside_appears(seconds):
        clock.sleep(seconds)
        aside.mkdir()
        (aside / "keepsake.txt").write_text("someone else's", encoding="utf-8")

    monkeypatch.setattr(bootstrap, "_aside_sleep", sleep_while_an_aside_appears)
    attempts = _refusing_rename(monkeypatch, [_win_error(5)], clock)

    assert bootstrap._move_venv_aside(_Log()) is None

    assert len(attempts) == 1
    assert (aside / "keepsake.txt").read_text(encoding="utf-8") == "someone else's"
    assert keepsake.read_text(encoding="utf-8") == "previous"


def test_a_degraded_environment_is_still_kept_without_any_rename(env, monkeypatch):
    """Scenario E: the new stop applies only when replacement was actually required."""
    keepsake = _existing_venv(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(version=(3, 13)))
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 13))
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    attempts = _refusing_rename(monkeypatch, _always(5))

    ok = bootstrap._create_validated_venv(["py", "-3.13"], _Log(), False)

    assert ok is True
    assert attempts == []
    assert keepsake.read_text(encoding="utf-8") == "previous"


# --------------------------------------------------------------------------- #
# K. An engine held inside the venv survives every step of the venv's own
#    replacement (v0.7.0 P04A, plan Revision 2 §5.5)
#
# The candidate layout keeps an independent Qwen3 environment at
# ``.venv/engines/qwen3``. It is not adopted, but the parent's transaction
# already had to be safe for it, and was not: setting ``.venv`` aside carries
# the child into ``.venv.replaced``, and ``commit`` then ``rmtree``'d that whole
# folder — a multi-gigabyte engine gone with the old app environment, never
# rebuilt with it. Now commit moves ``engines/`` home first (one rename, so it
# is in exactly one place at every instant, at the same absolute path as
# before), an aside still holding anything is never deleted, a rollback takes
# the engine back before the candidate goes, and recovery uses the same rules.
#
# The matrix: before the parent is set aside; after; before the engine is
# reattached; after, but before commit; after commit, before cleanup; during the
# rollback; during cleanup; and with each rename or delete refused. Every engine
# here is a synthetic folder whose bytes are hashed before and after.
# --------------------------------------------------------------------------- #
_ENGINE = ("engines", "qwen3")


def _tree(root: Path) -> dict[str, str]:
    """Every file under ``root`` by relative path, with its SHA-256."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _engine_in(parent: Path) -> Path:
    return parent.joinpath(*_ENGINE)


def _plant_engine(parent: Path, marker: str = "engine") -> dict[str, str]:
    """A held child environment's worth of identifiable files. Returns their hashes."""
    child = _engine_in(parent)
    (child / "Lib" / "site-packages" / "torch").mkdir(parents=True)
    (child / "pyvenv.cfg").write_text("home = C:/base\ninclude-system-site-packages = false\n", encoding="utf-8")
    (child / "Scripts").mkdir()
    (child / "Scripts" / "python.exe").write_bytes(b"child interpreter " + marker.encode())
    (child / "Lib" / "site-packages" / "torch" / "weights.bin").write_bytes(marker.encode() * 4096)
    return _tree(child)


def _protected(env) -> dict[str, str]:
    """Models, transcripts, settings, caches and logs: outside every environment, and hashed.

    The engine's three lock files are here too, empty, as on any copy that has installed it: since v0.7.0 P04C a
    repair locks them (``shared.engine_lease``), and locking must neither change them nor add anything beside them.
    """
    data = env.tmp / "files" / "runtime-data"
    for relative, payload in (("models/qwen3/base/model.safetensors", b"model" * 512),
                              ("qwen3/transcript-selection.json", b'{"schema": 1, "voices": {}}'),
                              ("qwen3/cache/hf/blob", b"cache"),
                              ("qwen3/setup.lock", b""), ("qwen3/inference.lock", b""), ("qwen3/engine.lock", b""),
                              ("settings.json", b"{}"),
                              ("logs/session.log", b"log")):
        target = data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return _tree(data)


def _protected_after(env) -> dict[str, str]:
    return _tree(env.tmp / "files" / "runtime-data")


def _successful_repair_fakes(monkeypatch, *, reconcile=None):
    """Everything ``repair_venv`` calls out to, faked so the real transaction runs."""
    monkeypatch.setattr(bootstrap, "find_suitable_python", lambda log, prefer_tk=True: ["py", "-3.12"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    _creates_venv(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())
    if reconcile is None:
        _reconcile_spy(monkeypatch)
    else:
        monkeypatch.setattr(bootstrap, "reconcile_requirements", reconcile)
    monkeypatch.setattr(bootstrap, "probe_venv",
                        lambda py: _probe() if (bootstrap.VENV_DIR / "candidate.txt").exists() else None)


def _refusing_engine_rename(monkeypatch, refusals) -> list:
    """``os.replace`` that refuses to move an ``engines`` folder, then really moves it."""
    real_replace = os.replace
    pending = iter(refusals)
    attempts: list = []

    def fake_replace(src, dst, *args, **kwargs):
        if Path(src).name == venv_layout.ENGINES_DIRNAME:
            attempts.append(str(dst))
            exc = next(pending, None)
            if exc is not None:
                raise exc
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(bootstrap.os, "replace", fake_replace)
    return attempts


# --- the whole repair ------------------------------------------------------ #
def test_a_repair_brings_a_held_engine_home_to_the_same_absolute_path(env, monkeypatch):
    keepsake = _existing_venv(env)
    engine = _plant_engine(env.venv)
    final = _engine_in(env.venv)
    protected = _protected(env)
    _successful_repair_fakes(monkeypatch)

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is True and "repaired" in message and "kept" not in message
    assert not keepsake.exists() and (env.venv / "candidate.txt").exists()  # really replaced
    assert _engine_in(env.venv) == final and _tree(final) == engine  # home, at its own path, byte-identical
    assert not bootstrap._venv_aside_path().exists()
    assert _protected_after(env) == protected


def test_if_the_engine_cannot_be_moved_home_the_old_folder_is_kept_not_deleted(env, monkeypatch):
    """Defence in depth: the discard refuses on its own, whatever the carry did."""
    _existing_venv(env)
    engine = _plant_engine(env.venv)
    _successful_repair_fakes(monkeypatch)
    monkeypatch.setattr(bootstrap, "_carry_held_environments", lambda source, destination, log: False)

    ok, message = bootstrap.repair_venv(_Log())

    aside = bootstrap._venv_aside_path()
    assert ok is True  # the app environment itself was repaired
    assert "kept" in message and "nothing was deleted" in message
    assert _tree(_engine_in(aside)) == engine
    assert not _engine_in(env.venv).exists()  # and it is not pretended to be installed


def test_first_run_setup_carries_a_held_engine_through_its_own_replacement(env, monkeypatch):
    """``_create_validated_venv`` owning the transaction (first-run setup) commits the same way."""
    _existing_venv(env)
    engine = _plant_engine(env.venv)
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    monkeypatch.setattr(bootstrap, "probe_venv",
                        lambda py: _probe() if (bootstrap.VENV_DIR / "candidate.txt").exists() else None)
    _creates_venv(monkeypatch)
    monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps())

    assert bootstrap._create_validated_venv(["py", "-3.12"], _Log(), False) is True

    assert (env.venv / "candidate.txt").exists() and _tree(_engine_in(env.venv)) == engine
    assert not bootstrap._venv_aside_path().exists()


# --- 1. before the parent is replaced -------------------------------------- #
def test_a_refused_aside_leaves_the_parent_and_its_engine_exactly_where_they_were(env, monkeypatch):
    keepsake = _existing_venv(env)
    engine = _plant_engine(env.venv)
    _successful_repair_fakes(monkeypatch)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    _controlled_time(monkeypatch)
    _refusing_rename(monkeypatch, _always(5))

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is False and "could not be rebuilt" in message
    assert keepsake.read_text(encoding="utf-8") == "previous"
    assert _tree(_engine_in(env.venv)) == engine
    assert _no_aside_exists(env)


@pytest.mark.skipif(not bootstrap.IS_WINDOWS, reason="an open handle only blocks a rename on Windows")
def test_a_running_engine_holds_its_parent_in_place_and_nothing_is_lost(env):
    """A real Windows handle inside the child (a worker still running), not a simulated refusal."""
    keepsake = _existing_venv(env)
    engine = _plant_engine(env.venv)
    weights = _engine_in(env.venv) / "Lib" / "site-packages" / "torch" / "weights.bin"
    log = _Log()
    with open(weights, "rb"):
        assert bootstrap._move_venv_aside(log) is None
    assert "Could not set the existing environment aside" in log.text
    assert keepsake.exists() and _tree(_engine_in(env.venv)) == engine
    assert _no_aside_exists(env)


# --- 2. after the parent was set aside ------------------------------------- #
def test_interrupted_after_the_aside_the_parent_comes_back_with_its_engine(env):
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    (aside / "keepsake.txt").write_text("previous", encoding="utf-8")
    engine = _plant_engine(aside)

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "keepsake.txt").exists() and _tree(_engine_in(env.venv)) == engine
    assert not aside.exists()


# --- 3. before the engine is reattached ------------------------------------ #
def test_interrupted_before_reattachment_a_proved_candidate_receives_the_engine(env, monkeypatch):
    aside = _interrupted_both(env)
    engine = _plant_engine(aside)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "candidate.txt").exists() and _tree(_engine_in(env.venv)) == engine
    assert not aside.exists()


def test_interrupted_before_reattachment_an_unproved_candidate_loses_and_the_engine_is_intact(env, monkeypatch):
    aside = _interrupted_both(env, proved=False)
    engine = _plant_engine(aside)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "keepsake.txt").exists() and not (env.venv / "candidate.txt").exists()
    assert _tree(_engine_in(env.venv)) == engine
    assert not aside.exists()


# --- 4. after reattachment, before commit ----------------------------------- #
def test_interrupted_after_reattachment_a_proved_candidate_keeps_the_engine(env, monkeypatch):
    aside = _interrupted_both(env)
    engine = _plant_engine(env.venv)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "candidate.txt").exists() and _tree(_engine_in(env.venv)) == engine
    assert not aside.exists()


def test_interrupted_after_reattachment_a_losing_candidate_hands_the_engine_back(env, monkeypatch):
    """The candidate holds the engine and is about to be deleted: the engine must leave with the restore."""
    aside = _interrupted_both(env)
    engine = _plant_engine(env.venv)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe(ssl=False))  # proved, but cannot run

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "keepsake.txt").exists() and not (env.venv / "candidate.txt").exists()
    assert _tree(_engine_in(env.venv)) == engine
    assert not aside.exists()


# --- 5. after commit, before / during cleanup ------------------------------- #
def test_interrupted_during_cleanup_a_half_deleted_aside_is_finished_off(env, monkeypatch):
    """Commit had moved the engine home; the aside's deletion was cut short."""
    aside = bootstrap._venv_aside_path()
    (aside / "Lib" / "leftover").mkdir(parents=True)
    (aside / "Lib" / "leftover" / "half.pyc").write_bytes(b"x")
    _fake_interpreter(env)
    (env.venv / "candidate.txt").write_text("candidate", encoding="utf-8")
    bootstrap.record_import_proof("3.12.10")
    engine = _plant_engine(env.venv)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    bootstrap.recover_interrupted_replacement(_Log())

    assert not aside.exists() and _tree(_engine_in(env.venv)) == engine


# --- 6. during the rollback ------------------------------------------------- #
class _Killed(BaseException):
    """The process dying mid-step: not an error anything may catch."""


def test_a_rollback_killed_while_deleting_the_candidate_is_not_mistaken_for_a_finished_repair(env, monkeypatch):
    aside = _interrupted_both(env)  # the candidate carries a current proof
    engine = _plant_engine(env.venv)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    def killed(*args, **kwargs):
        raise _Killed()

    with monkeypatch.context() as patch:
        patch.setattr(bootstrap.shutil, "rmtree", killed)
        with pytest.raises(_Killed):
            bootstrap._restore_venv(aside, _Log())

    # The engine went back to the aside first, and the candidate's proof went before any deletion began.
    assert _tree(_engine_in(aside)) == engine and not _engine_in(env.venv).exists()
    assert not bootstrap.import_proof_is_current()

    bootstrap.recover_interrupted_replacement(_Log())  # the next run: a healthy-looking candidate must not win

    assert (env.venv / "keepsake.txt").exists() and _tree(_engine_in(env.venv)) == engine
    assert not aside.exists()


def test_a_rollback_never_deletes_a_candidate_whose_engine_cannot_go_back(env, monkeypatch):
    """Both hold an engine (one was installed into the candidate meanwhile): nothing is chosen or deleted."""
    keepsake = _existing_venv(env)
    old_engine = _plant_engine(env.venv, "old")
    protected = _protected(env)
    new_engine: dict = {}

    def reconcile_installs_an_engine_then_fails(log):
        new_engine.update(_plant_engine(bootstrap.VENV_DIR, "new"))
        return False, "pip failed"

    _successful_repair_fakes(monkeypatch, reconcile=reconcile_installs_an_engine_then_fails)

    ok, message = bootstrap.repair_venv(_Log())

    aside = bootstrap._venv_aside_path()
    assert ok is False and "could not be put back either" in message
    assert _tree(_engine_in(aside)) == old_engine and (aside / keepsake.name).exists()
    assert _tree(_engine_in(env.venv)) == new_engine
    assert _protected_after(env) == protected


# --- 7. refused renames and deletes ---------------------------------------- #
def test_a_refused_carry_keeps_the_old_folder_and_the_next_run_brings_the_engine_home(env, monkeypatch):
    _existing_venv(env)
    engine = _plant_engine(env.venv)
    protected = _protected(env)
    _successful_repair_fakes(monkeypatch)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    _controlled_time(monkeypatch)
    with monkeypatch.context() as patch:
        attempts = _refusing_engine_rename(patch, _always(32))
        ok, message = bootstrap.repair_venv(_Log())

    aside = bootstrap._venv_aside_path()
    assert ok is True and "kept" in message
    assert 1 < len(attempts) <= 1 + len(bootstrap._ASIDE_RETRY_DELAYS_S)  # retried inside the bounded window
    assert _tree(_engine_in(aside)) == engine and not _engine_in(env.venv).exists()

    bootstrap.recover_interrupted_replacement(_Log())  # the rename works again

    assert _tree(_engine_in(env.venv)) == engine and not aside.exists()
    assert _protected_after(env) == protected


def test_a_momentary_carry_refusal_is_retried_and_the_engine_still_comes_home(env, monkeypatch):
    aside = _interrupted_both(env)
    engine = _plant_engine(aside)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    _controlled_time(monkeypatch)
    attempts = _refusing_engine_rename(monkeypatch, [_win_error(5)])
    log = _Log()

    bootstrap.recover_interrupted_replacement(log)

    assert len(attempts) == 2 and _tree(_engine_in(env.venv)) == engine and not aside.exists()


def test_a_carry_refusal_that_is_not_transient_is_not_retried(env, monkeypatch):
    aside = _interrupted_both(env)
    engine = _plant_engine(aside)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    _controlled_time(monkeypatch)
    attempts = _refusing_engine_rename(monkeypatch, _always(1392))  # ERROR_FILE_CORRUPT

    bootstrap.recover_interrupted_replacement(_Log())

    assert len(attempts) == 1
    assert _tree(_engine_in(aside)) == engine and (env.venv / "candidate.txt").exists()


@pytest.mark.skipif(not bootstrap.IS_WINDOWS, reason="an open handle only blocks a rename on Windows")
def test_a_real_handle_on_the_held_engine_keeps_it_in_the_aside_until_it_is_released(env, monkeypatch):
    aside = _interrupted_both(env)
    engine = _plant_engine(aside)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    weights = _engine_in(aside) / "Lib" / "site-packages" / "torch" / "weights.bin"
    log = _Log()
    with open(weights, "rb"):
        bootstrap.recover_interrupted_replacement(log)
    assert "Could not move the separately installed voice engines" in log.text
    assert "Kept .venv.replaced" in log.text
    assert _tree(_engine_in(aside)) == engine

    bootstrap.recover_interrupted_replacement(_Log())

    assert _tree(_engine_in(env.venv)) == engine and not aside.exists()


def test_a_backup_holding_the_only_copy_of_an_engine_is_never_deleted(env):
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    engine = _plant_engine(aside)
    txn = bootstrap.VenvReplacement(aside)
    _fake_interpreter(env)
    (env.venv / "engines").mkdir()
    (env.venv / "engines" / "something").write_text("already here", encoding="utf-8")  # the carry must refuse

    assert txn.commit(_Log()) is False
    assert txn.retained == aside and txn.committed
    assert _tree(_engine_in(aside)) == engine
    assert bootstrap._discard_venv_aside(aside, _Log()) is False and _tree(_engine_in(aside)) == engine


def test_when_both_hold_an_engine_recovery_keeps_both_and_chooses_neither(env, monkeypatch):
    aside = _interrupted_both(env)
    old_engine = _plant_engine(aside, "old")
    new_engine = _plant_engine(env.venv, "new")
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    log = _Log()

    bootstrap.recover_interrupted_replacement(log)

    assert "both hold separately installed voice engines" in log.text
    assert _tree(_engine_in(aside)) == old_engine and _tree(_engine_in(env.venv)) == new_engine


def test_an_unreadable_engines_folder_is_never_deleted_with_its_parent(env, monkeypatch):
    aside = bootstrap._venv_aside_path()
    (aside / "engines" / "qwen3").mkdir(parents=True)
    real_scandir = os.scandir

    def refused(path):
        if Path(path).name == "engines":
            raise PermissionError(13, "Access is denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr(venv_layout.os, "scandir", refused)
    assert bootstrap._discard_venv_aside(aside, _Log()) is False
    assert (aside / "engines" / "qwen3").is_dir()


@pytest.mark.skipif(not bootstrap.IS_WINDOWS, reason="junctions are a Windows mechanism")
def test_an_engines_junction_is_neither_followed_nor_moved_nor_deleted_through(env, monkeypatch):
    from test_qwen3_runtime import make_junction

    elsewhere = env.tmp / "somebody-elses-folder"
    elsewhere.mkdir()
    (elsewhere / "precious.txt").write_text("keep", encoding="utf-8")
    aside = _interrupted_both(env)
    make_junction(aside / "engines", elsewhere)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    log = _Log()

    bootstrap.recover_interrupted_replacement(log)

    assert "is a link or cannot be read" in log.text
    assert venv_layout.is_link(aside / "engines") and not (env.venv / "engines").exists()
    assert (elsewhere / "precious.txt").read_text(encoding="utf-8") == "keep"


def test_a_uniquely_named_older_aside_holding_an_engine_is_never_touched(env, monkeypatch):
    """``_move_venv_aside`` never overwrites an aside; recovery only ever resolves the canonical one."""
    stranded = env.tmp / (bootstrap._venv_aside_path().name + "-1790000000")
    _seed_interpreter(stranded)
    engine = _plant_engine(stranded)
    _fake_interpreter(env)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())

    bootstrap.recover_interrupted_replacement(_Log())

    assert _tree(_engine_in(stranded)) == engine


# --- boundaries ------------------------------------------------------------ #
def test_the_app_environment_repair_can_never_reach_the_qwen3_installer():
    """A main repair must not be able to start a multi-gigabyte engine acquisition."""
    tree = ast.parse(Path(bootstrap.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any(name == "tts" or name.startswith("tts.") for name in imported), imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
        {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for installer in ("qwen3_setup", "install_environment", "install_model", "qwen3_runtime"):
        assert installer not in names, installer


def test_every_delete_of_a_whole_environment_is_guarded_by_the_held_engine_check():
    """The two places that delete a set-aside or replaced parent ask first; the recreate deletes only its own candidate."""
    from source_probe import function

    for name in ("_discard_venv_aside", "_restore_venv"):
        node = function("shared/bootstrap.py", name)
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
        asks = [n.lineno for n in calls
                if isinstance(n.func, ast.Attribute) and n.func.attr == "holds_environments"]
        deletes = [n.lineno for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == "rmtree"]
        assert asks and deletes and min(asks) < min(deletes), name
