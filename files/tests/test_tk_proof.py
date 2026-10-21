"""GUI health means Tk really initialises (v0.6.7, audit ACT67-AUD-006).

Every bootstrap probe used ``tkinter.Tcl()``, which starts Tcl and never loads Tk. The audit blocked only Tk's
initialisation in a real interpreter: the venv probe still said ``tk: true``, then ``Tk()`` failed with "Can't find a
usable tk.tcl". These tests repeat that fault injection against the production probes, in real child interpreters,
without touching any installed file: a ``sitecustomize`` on the child's PYTHONPATH makes every ``tkinter.Tk()`` fail as
a missing ``tk.tcl`` does, while ``Tcl()`` keeps working.
"""

from __future__ import annotations

import json
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
    """Real stage 0 against this machine's Pythons with Tk broken for all of them: none is accepted, nothing installed."""
    out = tmp_path / "selected.txt"
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(STAGE_ZERO),
                             "-OutFile", str(out), "-AssumeNo"], capture_output=True, text=True, timeout=300)
    assert result.returncode == 2, result.stdout + result.stderr
    assert not out.exists()
