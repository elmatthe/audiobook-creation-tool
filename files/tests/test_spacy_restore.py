"""v0.7.0: a rebuilt .venv gets Kokoro's English pronunciation model back offline, from the verified wheel kept locally.

The model is a pip package inside .venv, so a main-environment repair (or a lost .venv) removed it while every other
Kokoro file under files/ survived, and Kokoro then asked to download it again (found on HOME-PC 2026-10-30 by a real
repair of an extracted copy). The consented install now keeps its verified wheel under files/runtime-data/models/spacy,
and bootstrap's one reconcile path reinstalls it from there: no index, no dependencies, hash enforced, nothing
downloaded. Nothing here runs pip or touches the real installation: interpreter and pip are fakes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from shared import bootstrap, spacy_store
from tts import model_assets as assets
from tts import qwen3_runtime as rt

WHEEL = b"synthetic en_core_web_sm wheel " * 64


class Log:
    def __init__(self):
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)


@pytest.fixture
def kept(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(bootstrap, "REPO_ROOT", tmp_path)
    for module in (assets, spacy_store):  # bootstrap reads the shared pins, the worker model_assets' names
        monkeypatch.setattr(module, "SPACY_WHEEL_SIZE", len(WHEEL))
        monkeypatch.setattr(module, "SPACY_WHEEL_SHA256", hashlib.sha256(WHEEL).hexdigest())
    store = assets.spacy_store_dir()
    assert store == spacy_store.store_dir(tmp_path)
    store.mkdir(parents=True)
    (store / assets.SPACY_WHEEL_NAME).write_bytes(WHEEL)
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    monkeypatch.setattr(bootstrap, "venv_python", lambda: python)
    return store / assets.SPACY_WHEEL_NAME


@pytest.fixture
def pip(monkeypatch):
    """The venv interpreter, faked: answers the version probe, records every other command."""

    class Fake:
        versions = {"spacy": "3.8.16", "model": None}
        code = 0
        calls: list = []
        requirements: list[str] = []

        def __call__(self, cmd, **kwargs):
            cmd = [str(c) for c in cmd]
            self.calls.append((cmd, kwargs))
            if "-c" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(self.versions) + "\n", stderr="")
            self.requirements.append(open(cmd[cmd.index("-r") + 1], encoding="utf-8").read())
            return subprocess.CompletedProcess(cmd, self.code, stdout="", stderr="")

    fake = Fake()
    fake.calls, fake.requirements = [], []
    monkeypatch.setattr(bootstrap.subprocess, "run", fake)
    return fake


def installs(pip) -> list[list[str]]:
    return [cmd for cmd, _kw in pip.calls if "-c" not in cmd]


def test_a_missing_model_is_reinstalled_offline_from_the_kept_verified_wheel(kept, pip, monkeypatch):
    monkeypatch.setenv("PIP_INDEX_URL", "https://refused.invalid/simple")
    log = Log()
    assert bootstrap.restore_kept_spacy_model(log) is True
    (cmd,) = installs(pip)
    for flag in ("--no-index", "--no-deps", "--require-hashes", "--isolated", "--require-virtualenv"):
        assert flag in cmd
    assert cmd[:3] == [str(bootstrap.venv_python()), "-m", "pip"]
    (requirement,) = pip.requirements
    assert requirement == assets.spacy_requirement_line(kept)
    env = pip.calls[-1][1]["env"]
    assert not any(name.upper().startswith("PIP_") and name != "PIP_CONFIG_FILE" for name in env)
    assert not (assets.spacy_store_dir() / "restore-requirement.txt").exists()  # nothing left behind
    assert any("nothing is downloaded" in line for line in log.lines)


@pytest.mark.parametrize("versions", [
    {"spacy": "3.8.16", "model": "3.8.0"},   # already there
    {"spacy": "3.8.16", "model": "3.7.1"},   # another model version is never replaced automatically
    {"spacy": "3.9.1", "model": None},       # spaCy outside the approved range
    {"spacy": None, "model": None},          # no spaCy at all
])
def test_nothing_is_installed_unless_the_model_is_absent_and_spacy_is_compatible(kept, pip, versions):
    pip.versions = versions
    assert bootstrap.restore_kept_spacy_model(Log()) is False
    assert installs(pip) == []


@pytest.mark.parametrize("damage", ["absent", "size", "content"])
def test_without_an_exact_kept_wheel_nothing_runs_at_all(kept, pip, damage):
    if damage == "absent":
        kept.unlink()
    elif damage == "size":
        kept.write_bytes(WHEEL + b"x")
    else:
        kept.write_bytes(WHEEL[:-1] + b"!")
    assert bootstrap.restore_kept_spacy_model(Log()) is False
    assert pip.calls == []


def test_a_failed_reinstall_is_reported_and_never_fails_setup(kept, pip):
    pip.code = 1
    log = Log()
    assert bootstrap.restore_kept_spacy_model(log) is False
    assert any("Could not reinstall" in line for line in log.lines)


@pytest.mark.parametrize("validated", [True, False])
def test_reconcile_restores_only_after_every_required_import_is_proved(monkeypatch, validated):
    calls = []
    monkeypatch.setattr(bootstrap, "pip_install_requirements", lambda log: True)
    monkeypatch.setattr(bootstrap, "validate_installed_packages", lambda log: validated)
    monkeypatch.setattr(bootstrap, "record_requirements_state", lambda: calls.append("stamp"))
    monkeypatch.setattr(bootstrap, "record_import_proof", lambda: calls.append("proof"))
    monkeypatch.setattr(bootstrap, "restore_kept_spacy_model", lambda log: calls.append("restore"))
    ok, _reason = bootstrap.reconcile_requirements(Log())
    assert ok is validated
    assert calls == (["stamp", "proof", "restore"] if validated else [])
