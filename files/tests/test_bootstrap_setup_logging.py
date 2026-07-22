"""Regression: run_setup's Kokoro warmup call and the SetupLog interface.

v0.5.0 bug: ``run_setup`` handed its ``SetupLog`` object straight to
``warmup_kokoro_pipeline`` — which expects a plain ``Callable[[str], None]``
and does ``log(...)`` — so first-time setup crashed with
``TypeError: 'SetupLog' object is not callable`` right after the Kokoro model
download. These tests drive ``run_setup`` through that exact call site with
every install step stubbed (no venv, no network, no subprocess — the warmup
Popen is faked), so any caller/callee logging-interface mismatch fails here
instead of on a user's first install. Fully headless: no Tk anywhere.
"""

from __future__ import annotations

import io
import sys

from shared import bootstrap


class _FakeWarmupPopen:
    """Stands in for the venv-python warmup subprocess."""

    def __init__(self, *args, **kwargs):
        self.stdout = io.StringIO("Kokoro pipeline warmup complete.\n")

    def wait(self):
        return 0


def _stub_setup_steps(monkeypatch):
    """Stub every run_setup stage so it reaches the Kokoro warmup call."""
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: [sys.executable])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    monkeypatch.setattr(bootstrap, "preflight_report", lambda py, log: {})
    monkeypatch.setattr(bootstrap, "_create_validated_venv",
                        lambda py, log, headless: True)
    monkeypatch.setattr(bootstrap, "pip_install_requirements", lambda log: True)
    monkeypatch.setattr(bootstrap, "validate_installed_packages", lambda log: True)
    monkeypatch.setattr(bootstrap, "ensure_ffmpeg", lambda log: True)
    monkeypatch.setattr(bootstrap, "predownload_kokoro", lambda log: None)
    monkeypatch.setattr(bootstrap, "kokoro_is_healthy",
                        lambda venv_py: (True, "ok"))
    monkeypatch.setattr(bootstrap.subprocess, "Popen", _FakeWarmupPopen)


def test_run_setup_reaches_kokoro_warmup_without_typeerror(monkeypatch):
    """run_setup must invoke the warmup with the logger it actually holds.

    With the pre-fix code (``warmup_kokoro_pipeline(venv_python(), log)``)
    this raises ``TypeError: 'SetupLog' object is not callable``.
    """
    _stub_setup_steps(monkeypatch)
    ok, msg = bootstrap.run_setup(download_kokoro=True,
                                  progress=lambda step, text: None,
                                  log=bootstrap.LOG)
    assert ok is True
    assert msg == "Setup complete."


def test_warmup_kokoro_pipeline_accepts_setuplog_line(monkeypatch):
    """warmup_kokoro_pipeline works with the bound method both callers pass.

    Every log(...) inside the function must land through SetupLog.line —
    captured here via the UI sink.
    """
    monkeypatch.setattr(bootstrap.subprocess, "Popen", _FakeWarmupPopen)
    captured: list[str] = []
    bootstrap.LOG.set_ui_sink(captured.append)
    try:
        bootstrap.warmup_kokoro_pipeline(bootstrap.venv_python(),
                                         bootstrap.LOG.line)
    finally:
        bootstrap.LOG.set_ui_sink(None)
    assert any("Initializing AI voice engine" in line for line in captured)
    assert any("Kokoro pipeline warmup complete." in line for line in captured)
