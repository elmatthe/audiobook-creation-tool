"""Kokoro health is proved, not presumed (v0.6.7, audit ACT67-AUD-002).

The old launch check asked ``find_spec`` whether kokoro, soundfile and scipy were present. On 2026-10-20 a fresh install
resolved srsly 2.5.4, Smart App Control refused its ``_epoch`` extension, every Kokoro voice failed -- and the log said
``Kokoro health-check: ok`` throughout, because presence never loads spaCy or srsly. These tests pin the replacement:

* presence stays the cheap per-launch half; a real offline proof of the synthesis chain decides health and is recorded,
  so the healthy launch does not pay for it every time;
* a blocked or broken import is a failure with its native detail kept, and a plain-language reason that never blames
  "Python 3.13+" for a DLL problem;
* every repair installs from ``requirements.txt`` (so ``srsly==2.5.3`` applies), and a repair that still fails is not
  rerun on every launch;
* missing model weights are reported, never downloaded, and are not a broken install;
* a real synthesis that cannot load the pipeline forgets the recorded success.

Everything runs against a temporary ``VENV_DIR``; the real environment is never written (conftest guards it).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shared import bootstrap

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOCKED = ("DLL load failed while importing _epoch: An Application Control policy has blocked this file. "
           "(WinError 4551)")


@pytest.fixture
def venv(monkeypatch, tmp_path):
    folder = tmp_path / "venv"
    folder.mkdir()
    monkeypatch.setattr(bootstrap, "VENV_DIR", folder)
    return folder


class Child:
    """Stands in for the venv interpreter: answers the presence probe and the proof, counting each."""

    def __init__(self, monkeypatch, *, present=True, proof="ok", facts=None):
        self.present, self.proof, self.facts = present, proof, facts or {"english_model": True, "weights": True}
        self.calls: list[list[str]] = []
        monkeypatch.setattr(bootstrap.subprocess, "run", self.run)

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        script = argv[-1]
        if "-m" in argv and "pip" in argv:
            return subprocess.CompletedProcess(argv, 0, "Requirement already satisfied", "")
        if script == bootstrap._KOKORO_PROOF:
            if self.proof == "timeout":
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
            if self.proof == "oserror":
                raise OSError("the interpreter could not be started")
            if self.proof == "ok":
                return subprocess.CompletedProcess(argv, 0, "noise\nOK:" + json.dumps(self.facts), "")
            info = {"stage": "import", "type": "ImportError", "error": self.proof}
            return subprocess.CompletedProcess(argv, 1, "BROKEN:" + json.dumps(info), "")
        if "find_spec" in script:
            return subprocess.CompletedProcess(argv, 0 if self.present else 1,
                                               "OK" if self.present else "MISSING:kokoro", "")
        raise AssertionError(f"unexpected subprocess {argv}")

    def count(self, kind: str) -> int:
        if kind == "proof":
            return sum(1 for a in self.calls if a[-1] == bootstrap._KOKORO_PROOF)
        if kind == "pip":
            return sum(1 for a in self.calls if "pip" in a)
        return sum(1 for a in self.calls if "find_spec" in a[-1])


PY = Path("venv-python")


# --------------------------------------------------------------------------- #
# Presence is not health
# --------------------------------------------------------------------------- #
def test_a_blocked_srsly_import_is_not_health(venv, monkeypatch):
    child = Child(monkeypatch, proof=BLOCKED)
    ok, reason = bootstrap.kokoro_is_healthy(PY)
    assert ok is False
    assert "Application Control" in reason and "_epoch" in reason, "the native detail must survive for the log"
    assert bootstrap.current_kokoro_proof()["ok"] is False
    assert child.count("proof") == 1


def test_a_healthy_proof_is_recorded_so_the_next_launch_only_checks_presence(venv, monkeypatch):
    child = Child(monkeypatch)
    assert bootstrap.kokoro_is_healthy(PY) == (True, "ok")
    assert bootstrap.kokoro_is_healthy(PY) == (True, "ok")
    assert child.count("proof") == 1
    assert child.count("presence") == 2


def test_absence_is_decided_by_presence_alone(venv, monkeypatch):
    child = Child(monkeypatch, present=False)
    ok, reason = bootstrap.kokoro_is_healthy(PY)
    assert (ok, reason) == (False, "MISSING:kokoro")
    assert child.count("proof") == 0


@pytest.mark.parametrize("change", ["requirements", "interpreter", "age"])
def test_a_recorded_proof_stops_applying_when_anything_it_vouched_for_changes(venv, monkeypatch, change):
    child = Child(monkeypatch)
    bootstrap.kokoro_is_healthy(PY)
    if change == "requirements":
        monkeypatch.setattr(bootstrap, "requirements_fingerprint", lambda: "different pins")
    elif change == "interpreter":
        monkeypatch.setattr(bootstrap, "_interpreter_identity", lambda: ["another python", 1, 2])
    else:
        record = json.loads(bootstrap.kokoro_proof_path().read_text(encoding="utf-8"))
        record["proved_at"] = time.time() - bootstrap.KOKORO_PROOF_MAX_AGE_S - 60
        bootstrap.kokoro_proof_path().write_text(json.dumps(record), encoding="utf-8")
    bootstrap.kokoro_is_healthy(PY)
    assert child.count("proof") == 2


def test_a_failed_proof_is_trusted_for_a_day_only(venv, monkeypatch):
    Child(monkeypatch, proof=BLOCKED)
    bootstrap.kokoro_is_healthy(PY)
    record = json.loads(bootstrap.kokoro_proof_path().read_text(encoding="utf-8"))
    record["proved_at"] = time.time() - bootstrap.KOKORO_FAILED_PROOF_MAX_AGE_S - 60
    bootstrap.kokoro_proof_path().write_text(json.dumps(record), encoding="utf-8")
    assert bootstrap.current_kokoro_proof() is None


@pytest.mark.parametrize("proof", ["timeout", "oserror"])
def test_a_proof_that_cannot_finish_is_unverified_not_healthy_and_not_broken(venv, monkeypatch, proof):
    """CLR-001: "not proven broken" is not "proven healthy". Three states, and the middle one is ``None``."""
    Child(monkeypatch, proof=proof)
    ok, reason = bootstrap.kokoro_is_healthy(PY)
    assert ok is None, "an unfinished proof is neither health nor a finding"
    assert "could not be verified" in reason
    assert not bootstrap.kokoro_proof_path().exists(), "nothing proved, so nothing recorded (no success cache)"


def test_a_later_completed_proof_clears_the_unverified_state(venv, monkeypatch):
    child = Child(monkeypatch, proof="timeout")
    assert bootstrap.kokoro_is_healthy(PY)[0] is None
    child.proof = "ok"
    assert bootstrap.kokoro_is_healthy(PY) == (True, "ok")
    assert bootstrap.current_kokoro_proof()["ok"] is True
    child.proof = "timeout"
    assert bootstrap.kokoro_is_healthy(PY) == (True, "ok"), "the recorded success keeps the cheap launch path"
    assert child.count("proof") == 2


def test_a_later_completed_proof_can_also_find_the_install_broken(venv, monkeypatch):
    child = Child(monkeypatch, proof="timeout")
    assert bootstrap.kokoro_is_healthy(PY)[0] is None
    child.proof = BLOCKED
    ok, reason = bootstrap.kokoro_is_healthy(PY)
    assert ok is False and "_epoch" in reason


# --------------------------------------------------------------------------- #
# Truthful messages
# --------------------------------------------------------------------------- #
def test_a_blocked_file_is_explained_as_application_control_not_python_version():
    message = bootstrap.kokoro_failure_message("import: ImportError: " + BLOCKED)
    assert "Application Control" in message
    assert "3.13" not in message
    assert "reinstall" in message.lower()


@pytest.mark.parametrize("detail, expected", [
    ("import: ImportError: DLL load failed while importing _C: The specified module could not be found.", "library"),
    ("import: ModuleNotFoundError: No module named 'misaki'", "missing"),
    ("MISSING:kokoro", "not installed"),
    ("pipeline: RuntimeError: espeak exploded", "failed to start"),
])
def test_each_failure_class_gets_its_own_plain_reason(detail, expected):
    message = bootstrap.kokoro_failure_message(detail)
    assert expected in message
    assert "3.13" not in message


def test_predownload_never_blames_python_313_for_a_blocked_dll(venv, monkeypatch):
    Child(monkeypatch, proof=BLOCKED)
    monkeypatch.setattr(bootstrap, "venv_python", lambda windowed=False: PY)
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    downloads: list = []
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *a, **k: downloads.append(a))
    lines: list[str] = []

    class Log:
        def line(self, text):
            lines.append(text)

    bootstrap.predownload_kokoro(Log())
    text = "\n".join(lines)
    assert "3.13" not in text
    assert "Application Control" in text and "_epoch" in text
    assert downloads == [], "a broken install must not start a 300 MB download"


def test_predownload_names_a_missing_package_as_missing_on_a_supported_python(venv, monkeypatch):
    Child(monkeypatch, present=False)
    monkeypatch.setattr(bootstrap, "venv_python", lambda windowed=False: PY)
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    lines: list[str] = []

    class Log:
        def line(self, text):
            lines.append(text)

    bootstrap.predownload_kokoro(Log())
    assert "not installed" in lines[0] and "too new" not in lines[0]


# --------------------------------------------------------------------------- #
# Repair honours the authoritative requirements and is not repeated blindly
# --------------------------------------------------------------------------- #
def test_every_repair_installs_from_the_requirements_file(venv, monkeypatch):
    child = Child(monkeypatch)
    assert bootstrap.ensure_kokoro_installed(PY, lambda line: None) is True
    pip = next(a for a in child.calls if "pip" in a)
    assert pip[pip.index("-r") + 1] == str(bootstrap.REQUIREMENTS_FILE)
    assert not set(bootstrap.KOKORO_PKGS) & set(pip), "a hand-kept list would bypass the srsly pin"


def test_the_requirements_file_carries_the_qualified_srsly_pin_and_the_kokoro_pins():
    lines = {line.split(";")[0].strip() for line in
             bootstrap.REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines()}
    assert "srsly==2.5.3" in lines
    assert set(bootstrap.KOKORO_PKGS) <= lines


def test_a_repair_whose_proof_still_fails_is_recorded_and_not_rerun_today(venv, monkeypatch):
    child = Child(monkeypatch, proof=BLOCKED)
    assert bootstrap.ensure_kokoro_installed(PY, lambda line: None) is False
    assert bootstrap.current_kokoro_proof()["after_repair"] is True
    assert bootstrap.kokoro_repair_is_worthwhile() is False
    ok, reason = bootstrap.kokoro_is_healthy(PY)
    assert ok is False and "_epoch" in reason
    assert child.count("proof") == 1, "the blocked file is not loaded again on the next launch"


@pytest.mark.parametrize("proof", ["timeout", "oserror"])
def test_a_repair_whose_proof_cannot_finish_does_not_claim_success(venv, monkeypatch, proof):
    """CLR-001: installed and present is not "proved working", and nothing is cached as either outcome."""
    child = Child(monkeypatch, proof=proof)
    lines: list[str] = []
    assert bootstrap.ensure_kokoro_installed(PY, lines.append) is None
    assert not bootstrap.kokoro_proof_path().exists(), "neither a success nor a failure was proved"
    assert bootstrap.kokoro_repair_is_worthwhile() is True, "an inconclusive proof is not a failed repair"
    assert child.count("pip") == 1
    child.proof = "ok"
    assert bootstrap.kokoro_is_healthy(PY) == (True, "ok"), "a later completed proof recovers to healthy"


def test_a_failure_found_at_launch_still_earns_one_repair(venv, monkeypatch):
    Child(monkeypatch, proof=BLOCKED)
    bootstrap.kokoro_is_healthy(PY)
    assert bootstrap.kokoro_repair_is_worthwhile() is True


def test_missing_weights_are_reported_not_downloaded_and_not_a_failure(venv, monkeypatch):
    child = Child(monkeypatch, facts={"english_model": True, "weights": False})
    lines: list[str] = []
    assert bootstrap.ensure_kokoro_installed(PY, lines.append) is True
    assert any("not downloaded yet" in line for line in lines)
    assert child.count("pip") == 1


def test_the_proof_is_offline_and_builds_no_model():
    script = bootstrap._KOKORO_PROOF
    assert "os.environ['HF_HUB_OFFLINE'] = '1'" in script
    assert "model=False" in script
    assert "spacy.util.is_package('en_core_web_sm')" in script, "never let misaki download spaCy's model"


# --------------------------------------------------------------------------- #
# The real proof script, run for real
# --------------------------------------------------------------------------- #
def _real_venv_python() -> Path:
    exe = REPO_ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return exe


def test_the_real_proof_reports_a_shadowed_blocked_srsly_as_broken(tmp_path, monkeypatch):
    """The proof script itself, in a real interpreter, with srsly replaced by one that refuses to load."""
    fake = tmp_path / "shadow" / "srsly"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text(f"raise ImportError({BLOCKED!r})\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(fake.parent))
    proved, detail, _ = bootstrap.prove_kokoro_dependencies(Path(sys.executable))
    assert proved is False
    assert detail.startswith("import: ImportError") and "4551" in detail


@pytest.mark.skipif(not _real_venv_python().is_file(), reason="no development .venv")
def test_the_real_proof_passes_on_the_qualified_environment():
    """End to end on this checkout's own venv: the chain imports and the G2P builds, offline, writing nothing."""
    py = _real_venv_python()
    if subprocess.run([str(py), "-c", "import kokoro"], capture_output=True).returncode != 0:
        pytest.skip("Kokoro is not installed in this checkout's venv")
    proved, detail, facts = bootstrap.prove_kokoro_dependencies(py)
    assert (proved, detail) == (True, "ok")
    assert set(facts) == {"english_model", "weights"}


# --------------------------------------------------------------------------- #
# A real synthesis failure forgets the recorded success
# --------------------------------------------------------------------------- #
def test_a_pipeline_that_cannot_load_forgets_the_recorded_proof(tmp_path, monkeypatch):
    from tts import kokoro_synth

    assert kokoro_synth.KOKORO_PROOF_NAME == bootstrap.KOKORO_PROOF_NAME
    record = tmp_path / kokoro_synth.KOKORO_PROOF_NAME
    record.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(kokoro_synth.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(kokoro_synth, "_PIPELINE_CACHE", {})
    monkeypatch.setattr(kokoro_synth, "_first_pipeline_load_attempted", True)

    def blocked(lang_code):
        raise ImportError(BLOCKED)

    monkeypatch.setattr(kokoro_synth, "_instantiate_pipeline", blocked)
    with pytest.raises(ImportError):
        kokoro_synth._get_pipeline("a")
    assert not record.exists()


def test_a_pipeline_that_loads_keeps_the_record(tmp_path, monkeypatch):
    from tts import kokoro_synth

    record = tmp_path / kokoro_synth.KOKORO_PROOF_NAME
    record.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(kokoro_synth.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(kokoro_synth, "_PIPELINE_CACHE", {})
    monkeypatch.setattr(kokoro_synth, "_first_pipeline_load_attempted", True)
    monkeypatch.setattr(kokoro_synth, "_instantiate_pipeline", lambda lang_code: object())
    kokoro_synth._get_pipeline("a")
    assert record.exists()
