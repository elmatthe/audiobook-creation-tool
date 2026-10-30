"""GUI health means Tk really initialises (v0.6.7, audit ACT67-AUD-006).

Every bootstrap probe used ``tkinter.Tcl()``, which starts Tcl and never loads Tk. The audit blocked only Tk's
initialisation in a real interpreter: the venv probe still said ``tk: true``, then ``Tk()`` failed with "Can't find a
usable tk.tcl". These tests repeat that fault injection against the production probes, in real child interpreters,
without touching any installed file: a ``sitecustomize`` on the child's PYTHONPATH makes every ``tkinter.Tk()`` fail as
a missing ``tk.tcl`` does, while ``Tcl()`` keeps working.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shared import bootstrap

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE_ZERO = REPO_ROOT / "scripts" / "shared" / "bootstrap_host.ps1"

# Loaded by the child at startup: Tcl stays healthy, Tk initialisation fails the way a missing tk.tcl makes it fail.
# ``tkinter.Tcl()`` is ``Tk(None, None, None, 0)`` -- the same class with useTk false -- so only useTk=True is broken.
BREAK_TK = (
    "import tkinter\n"
    "_real = tkinter.Tk.__init__\n"
    "def _init(self, screenName=None, baseName=None, className='Tk', useTk=True, *args, **kwargs):\n"
    "    if useTk:\n"
    "        raise tkinter.TclError(\"Can't find a usable tk.tcl in the following directories (simulated by the test)\")\n"
    "    _real(self, screenName, baseName, className, useTk, *args, **kwargs)\n"
    "tkinter.Tk.__init__ = _init\n"
)


@pytest.fixture
def broken_tk(tmp_path, monkeypatch):
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "sitecustomize.py").write_text(BREAK_TK, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(shim))
    return shim


def _tk_works_here() -> bool:
    # Independent of the production proof on purpose, so a weakened proof cannot skip the tests that judge it.
    return subprocess.run([sys.executable, "-c", "import tkinter; r = tkinter.Tk(); r.withdraw(); r.destroy()"],
                          capture_output=True, timeout=60).returncode == 0


needs_tk = pytest.mark.skipif(not _tk_works_here(), reason="no working Tk/display for this interpreter")


def run_venv_probe() -> dict:
    out = subprocess.run([sys.executable, "-c", bootstrap._VENV_PROBE], capture_output=True, text=True, timeout=120)
    return json.loads(out.stdout.strip())


@needs_tk
def test_tcl_still_works_under_the_fault(broken_tk):
    """The injected fault is the audit's: Tcl healthy, Tk not."""
    tcl = subprocess.run([sys.executable, "-c", "import tkinter; print(tkinter.Tcl().eval('info patchlevel'))"],
                         capture_output=True, text=True, timeout=60)
    assert tcl.returncode == 0 and tcl.stdout.strip()
    tk = subprocess.run([sys.executable, "-c", "import tkinter; tkinter.Tk()"], capture_output=True, text=True,
                        timeout=60)
    assert tk.returncode != 0 and "tk.tcl" in tk.stderr


@needs_tk
def test_the_old_tcl_only_probe_would_have_passed_this_fault(broken_tk):
    """Why the probe changed: the exact pre-fix check succeeds on an interpreter that cannot open a window."""
    old = subprocess.run([sys.executable, "-c", "import tkinter; tkinter.Tcl()"], capture_output=True, timeout=60)
    assert old.returncode == 0


@needs_tk
def test_the_venv_probe_reports_broken_tk_with_its_reason(broken_tk):
    payload = run_venv_probe()
    assert payload["tk"] is False and payload["ssl"] is True
    assert "tk.tcl" in payload["tk_error"]


@needs_tk
def test_the_base_interpreter_check_rejects_broken_tk(broken_tk):
    assert bootstrap._tcl_tk_ok([sys.executable]) is False


@needs_tk
def test_a_healthy_tk_still_passes_quickly_and_leaves_no_window():
    started = time.monotonic()
    payload = run_venv_probe()
    assert payload["tk"] is True and "tk_error" not in payload
    assert bootstrap._tcl_tk_ok([sys.executable]) is True
    assert time.monotonic() - started < 30
    # The proof withdraws the root before the event loop ever runs and destroys it: nothing can be mapped.
    lines = bootstrap._TK_PROOF_LINES
    assert lines.index("_root.withdraw()") == lines.index("_root = tkinter.Tk()") + 1
    assert lines[-1] == "_root.destroy()" and not any("mainloop" in line or "update" in line for line in lines)


def test_a_hung_tk_counts_as_no_tk_within_the_bound(monkeypatch):
    seen = {}

    def hang(cmd, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(bootstrap, "_run", hang)
    assert bootstrap._tcl_tk_ok(["python"]) is False
    assert seen["timeout"] == bootstrap.TK_PROOF_TIMEOUT_S


def _assess(monkeypatch, tmp_path, tk_error: str, require_tk: bool = True):
    py = tmp_path / "python.exe"
    py.write_bytes(b"")
    monkeypatch.setattr(bootstrap, "venv_python", lambda windowed=False: py)
    monkeypatch.setattr(bootstrap, "probe_venv",
                        lambda p: {"version": (3, 12), "ssl": True, "tk": False, "tk_error": tk_error})
    return bootstrap.assess_venv_health(require_tk=require_tk)


def test_broken_tk_makes_the_environment_repairable(monkeypatch, tmp_path):
    health = _assess(monkeypatch, tmp_path, "TclError: Can't find a usable tk.tcl")
    assert (health.state, health.reason) == (bootstrap.VENV_REPAIRABLE, "no-tk")


def test_no_display_is_not_mistaken_for_a_broken_environment(monkeypatch, tmp_path):
    """A service or CI box without a display cannot open a window whatever the venv; rebuilding it would loop."""
    error = "TclError: no display name and no $DISPLAY environment variable"
    health = _assess(monkeypatch, tmp_path, error)
    assert (health.state, health.reason) == (bootstrap.VENV_DEGRADED, "no-display")
    assert _assess(monkeypatch, tmp_path, error, require_tk=False).state == bootstrap.VENV_HEALTHY


def test_stage_zero_uses_the_same_real_tk_proof_and_a_bounded_run():
    text = STAGE_ZERO.read_text(encoding="ascii")
    probe = next(line for line in text.splitlines() if line.startswith("$Probe = "))
    assert "r = tkinter.Tk(); r.withdraw(); r.destroy()" in probe and "Tcl()" not in probe
    assert "WaitForExit($ProbeTimeoutMs)" in text and "$ProbeTimeoutMs = 30000" in text
    assert "& $exe @rest -c $Probe" not in text, "an unbounded '&' call can wait forever on a hung interpreter"


@needs_tk
@pytest.mark.skipif(not sys.platform.startswith("win"), reason="stage 0 is Windows PowerShell")
def test_stage_zero_rejects_a_python_whose_tk_cannot_initialise(broken_tk, tmp_path):
    """Real stage 0 with Tk broken: no Python is accepted and nothing is downloaded. (v0.7.0: stage 0 only ever uses
    the app's own Python in files/runtime-data/python, never one installed on the computer.)"""
    out = tmp_path / "selected.txt"
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(STAGE_ZERO),
                             "-OutFile", str(out), "-AssumeNo"], capture_output=True, text=True, timeout=300)
    assert result.returncode == 2, result.stdout + result.stderr
    assert not out.exists()


# --------------------------------------------------------------------------- #
# One bound for every GUI capability proof (closure review ACT67-CLR-003)
#
# AUD-006 fixed the proof and bounded the base-interpreter check and stage 0 at TK_PROOF_TIMEOUT_S, but the venv probe --
# the one on every ordinary launch -- still allowed 120 s. These tests pin the argument of each route, then hang a real
# child to see the bound enforced and the child gone.
# --------------------------------------------------------------------------- #
HANG = (
    "import os, time\n"
    "open(os.environ['ACT_HANG_PID_FILE'], 'w').write(str(os.getpid()))\n"
    "time.sleep(600)\n"
)


def _process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True)
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def hung_interpreter(tmp_path, monkeypatch):
    """This interpreter with a sitecustomize that records its pid and never returns: a Tk that hangs the way a stuck
    display or a blocked DLL does, without touching any installed file. Returns the file the pid lands in."""
    shim = tmp_path / "hang-shim"
    shim.mkdir()
    (shim / "sitecustomize.py").write_text(HANG, encoding="utf-8")
    pid_file = tmp_path / "hung.pid"
    monkeypatch.setenv("PYTHONPATH", str(shim))
    monkeypatch.setenv("ACT_HANG_PID_FILE", str(pid_file))
    return pid_file


def _assert_child_gone(pid_file: Path) -> None:
    assert pid_file.exists(), "the hanging child never started, so the bound was not what ended it"
    pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 10
    while _process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _process_alive(pid), "the timed-out probe left its interpreter running"


def test_the_venv_probe_passes_the_shared_tk_bound(monkeypatch):
    seen = {}

    def capture(cmd, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(bootstrap.subprocess, "run", capture)
    assert bootstrap.probe_venv(Path("python")) is None
    assert seen["timeout"] == bootstrap.TK_PROOF_TIMEOUT_S == 30


def test_every_gui_capability_proof_is_bounded_by_the_one_constant():
    """Source-level companion to the call tests: no literal bound can creep back next to a Tk proof."""
    import ast

    tree = ast.parse(Path(bootstrap.__file__).read_text(encoding="utf-8"))
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name in ("probe_venv", "_tcl_tk_ok"):
        timeouts = [kw.value for call in ast.walk(functions[name]) if isinstance(call, ast.Call)
                    for kw in call.keywords if kw.arg == "timeout"]
        assert timeouts, f"{name} runs a subprocess without any bound"
        assert all(isinstance(t, ast.Name) and t.id == "TK_PROOF_TIMEOUT_S" for t in timeouts), name


def test_a_hung_venv_probe_is_ended_at_the_bound_and_leaves_no_child(hung_interpreter, monkeypatch):
    monkeypatch.setattr(bootstrap, "TK_PROOF_TIMEOUT_S", 2)  # accelerated: the same code path, a shorter bound
    started = time.monotonic()
    assert bootstrap.probe_venv(Path(sys.executable)) is None
    assert time.monotonic() - started < 20
    _assert_child_gone(hung_interpreter)


def test_a_hung_base_interpreter_check_is_ended_at_the_bound_and_leaves_no_child(hung_interpreter, monkeypatch):
    monkeypatch.setattr(bootstrap, "TK_PROOF_TIMEOUT_S", 2)
    started = time.monotonic()
    assert bootstrap._tcl_tk_ok([sys.executable]) is False
    assert time.monotonic() - started < 20
    _assert_child_gone(hung_interpreter)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="stage 0 is Windows PowerShell")
def test_a_hung_stage_zero_candidate_is_killed_at_the_bound(tmp_path):
    """The real ``Test-Candidate`` from bootstrap_host.ps1, with the 30 s bound and the probe swapped for an accelerated
    1 s sleeper. Everything else (process start, bounded wait, kill) is the production text."""
    import re

    text = STAGE_ZERO.read_text(encoding="ascii")
    match = re.search(r"function Test-Candidate\(.*?(?=^function )", text, re.DOTALL | re.MULTILINE)
    assert match, "Test-Candidate not found in the stage 0 script"
    assert "$ProbeTimeoutMs = 30000" in text
    pid_file = tmp_path / "stage0.pid"
    probe = f"import os,time;open(r'{pid_file}','w').write(str(os.getpid()));time.sleep(600)"
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        f'$ProbeTimeoutMs = 1000\n$Probe = "{probe}"\n{match.group(0)}\n'
        f"$sw = [Diagnostics.Stopwatch]::StartNew()\n"
        f"$r = Test-Candidate @('{sys.executable}')\n"
        f"Write-Output ('RESULT=' + [string]($null -eq $r) + ' ELAPSED=' + [int]$sw.Elapsed.TotalSeconds)\n",
        encoding="ascii")
    done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                          capture_output=True, text=True, timeout=120)
    assert "RESULT=True" in done.stdout, done.stdout + done.stderr
    assert int(done.stdout.split("ELAPSED=")[1].split()[0]) < 15
    _assert_child_gone(pid_file)
