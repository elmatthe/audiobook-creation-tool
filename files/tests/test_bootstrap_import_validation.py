"""First-run package validation: a slow cold import is not a broken package,
and a repair never leaves the pinned requirements.

v0.6.6 Phase 11 defect, found by a real first-run install from the freshly built
Windows release archive on HOME-PC. Setup failed with "Python packages installed
but could not be imported" although nothing was broken:

- ``validate_installed_packages`` probed each import with a **30 s** timeout and
  counted a timeout as a failed import. The first import in a brand-new venv
  compiles and security-scans thousands of just-written files; ``import nltk``
  (which pulls in ``scipy.stats``) measured **32.4 s** cold and **1.1 s** warm, and
  ``chatterbox`` (torch) also ran past 30 s.
- The "repair" was ``pip install --force-reinstall <name>`` with **no version**:
  it replaced the package and its dependency tree with whatever PyPI had that
  day, ignoring ``requirements.txt``, and wrote fresh uncompiled files so the
  re-probe was cold and timed out again. The requirements stamp fingerprints the
  file, not the installed set, so that drift would never have been reconciled.

The launch-time proof (``prove_required_imports``) already allowed 600 s and
treated a probe that could not finish as no finding; the setup-time check now
uses the same named window, and its reinstall is constrained by the pins.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from shared import bootstrap  # noqa: E402


class _Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)


@pytest.fixture
def env(monkeypatch, tmp_path):
    venv = tmp_path / ".venv"
    (venv / "Scripts").mkdir(parents=True)
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("nltk==3.9.4\ntqdm==4.67.3\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "VENV_DIR", venv)
    monkeypatch.setattr(bootstrap, "REQUIREMENTS_FILE", reqs)
    monkeypatch.setattr(bootstrap, "REQUIRED_IMPORTS", ["nltk"])
    # The venv's version decides the <3.13 gate only; nltk is not gated.
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    return SimpleNamespace(reqs=reqs)


def _fake_run(monkeypatch, *, import_seconds: float, import_rc: int = 0):
    """``_run`` stand-in: an import that takes *import_seconds* of wall time."""
    calls: list[tuple[list[str], dict]] = []

    def run(cmd, **kw):
        calls.append((list(cmd), kw))
        if "-c" in cmd and any(str(a).startswith("import ") for a in cmd):
            timeout = kw.get("timeout")
            if timeout is not None and import_seconds > timeout:
                raise subprocess.TimeoutExpired(cmd, timeout)
            return subprocess.CompletedProcess(cmd, import_rc, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bootstrap, "_run", run)
    return calls


def _pip_calls(calls):
    return [c for c, _kw in calls if "pip" in " ".join(c) and "install" in c]


def test_a_cold_first_import_slower_than_30_seconds_is_not_a_failure(env, monkeypatch):
    calls = _fake_run(monkeypatch, import_seconds=33.0)   # measured: nltk 32.4 s cold
    log = _Log()
    assert bootstrap.validate_installed_packages(log) is True
    assert _pip_calls(calls) == []
    assert not any("failed to import" in line for line in log.lines)


def test_the_setup_check_uses_the_launch_proof_window(env, monkeypatch):
    calls = _fake_run(monkeypatch, import_seconds=0.1)
    bootstrap.validate_installed_packages(_Log())
    timeouts = {kw.get("timeout") for c, kw in calls if "import nltk" in c}
    assert timeouts == {bootstrap.IMPORT_PROBE_TIMEOUT_S}
    assert bootstrap.IMPORT_PROBE_TIMEOUT_S >= 600


def test_a_real_import_failure_reinstalls_within_the_pins(env, monkeypatch):
    calls = _fake_run(monkeypatch, import_seconds=0.1, import_rc=1)
    log = _Log()
    assert bootstrap.validate_installed_packages(log) is False
    [pip] = _pip_calls(calls)
    assert "--force-reinstall" in pip and "nltk" in pip
    constraint = pip[pip.index("-c") + 1]
    assert constraint == str(env.reqs)


def test_a_hung_import_is_still_a_failure_after_the_full_window(env, monkeypatch):
    _fake_run(monkeypatch, import_seconds=bootstrap.IMPORT_PROBE_TIMEOUT_S + 1)
    assert bootstrap.validate_installed_packages(_Log()) is False


def test_the_capability_probes_keep_their_short_timeout(monkeypatch):
    """tkinter/ssl/venv on a base interpreter are cheap; only the package check waits."""
    calls = _fake_run(monkeypatch, import_seconds=0.1)
    bootstrap._probe_import("python", "ssl")
    assert calls[0][1]["timeout"] == 30


def test_both_import_proofs_share_one_named_window():
    import inspect

    source = inspect.getsource(bootstrap.prove_required_imports)
    assert "timeout=IMPORT_PROBE_TIMEOUT_S" in source
