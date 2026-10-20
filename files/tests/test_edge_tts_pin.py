"""edge-tts is pinned to 7.3.1 (2026-10-20): Microsoft's read-aloud endpoint refuses 7.2.8 with HTTP 403 at the WebSocket
handshake (upstream rany2/edge-tts issue #490). Offline checks only: the pin, the installed version, the part of the edge_tts
API that ACT calls, and that a changed pin reaches existing installs through the bootstrap's requirements fingerprint.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from pathlib import Path

import pytest

REQUIREMENTS = Path(__file__).resolve().parents[2] / "scripts" / "requirements.txt"
PINNED = "7.3.1"
BROKEN = "7.2.8"


def pins() -> list[str]:
    return re.findall(r"^edge-tts==(\S+)", REQUIREMENTS.read_text(encoding="utf-8"), re.MULTILINE)


def test_requirements_pin_edge_tts_once_at_the_fixed_version():
    assert pins() == [PINNED]


def test_the_installed_edge_tts_is_the_pinned_one():
    edge_tts = pytest.importorskip("edge_tts")
    assert edge_tts.__version__ == PINNED, "run Setup_and_Run: the launch reconciles a changed pin"


def test_the_edge_tts_api_act_calls_is_still_there():
    edge_tts = pytest.importorskip("edge_tts")
    parameters = inspect.signature(edge_tts.Communicate.__init__).parameters
    assert list(parameters)[1:3] == ["text", "voice"] and "rate" in parameters
    assert inspect.iscoroutinefunction(edge_tts.Communicate.save)
    communicate = edge_tts.Communicate("A short sentence.", "en-US-SteffanNeural", rate="+0%")
    assert not asyncio.iscoroutine(communicate)  # constructing it makes no network call


def test_the_production_callers_use_only_that_api():
    scripts = REQUIREMENTS.parent
    calls = []
    for relative in ("tts/batch_convert.py", "tts/epub2tts_edge/epub2tts_edge.py", "tts/generate_voice_samples.py"):
        calls += re.findall(r"edge_tts\.(\w+)", (scripts / relative).read_text(encoding="utf-8"))
    assert set(calls) == {"Communicate"}


def test_a_changed_pin_changes_the_fingerprint_an_existing_install_reconciles_against(tmp_path, monkeypatch):
    from shared import bootstrap

    reqs = tmp_path / "requirements.txt"
    monkeypatch.setattr(bootstrap, "REQUIREMENTS_FILE", reqs)
    reqs.write_text(REQUIREMENTS.read_text(encoding="utf-8").replace(f"edge-tts=={PINNED}", f"edge-tts=={BROKEN}"),
                    encoding="utf-8")
    old = bootstrap.requirements_fingerprint()
    reqs.write_text(REQUIREMENTS.read_text(encoding="utf-8"), encoding="utf-8")
    new = bootstrap.requirements_fingerprint()
    assert old and new and old != new


def test_the_bootstrap_still_proves_edge_tts_imports():
    from shared import bootstrap

    assert "edge_tts" in bootstrap.REQUIRED_IMPORTS
