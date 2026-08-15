"""v0.6.1 Plan 4 Phase 8 — Chatterbox setup/self-heal inside the existing bootstrap.

Chatterbox follows the Kokoro shape already in ``shared/bootstrap.py`` rather than
growing a second setup system: a package list, a subprocess health probe, an
in-venv repair install, a warm-up and a weights pre-download gated by a first-run
checkbox. The model is ~3.86 GiB, so unlike Kokoro that checkbox is **opt-in**.

Nothing here installs anything, downloads weights or touches the working ``.venv``:
the subprocess seams are stubbed and only their arguments are asserted.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared import bootstrap  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BOOTSTRAP_SRC = Path(bootstrap.__file__).read_text(encoding="utf-8")


@pytest.fixture
def recorded_runs(monkeypatch):
    """Capture every subprocess.run the bootstrap would make."""
    runs: list[list[str]] = []

    def fake_run(cmd, *a, **k):
        runs.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    return runs


# --------------------------------------------------------------------------- #
# The pinned repair set
# --------------------------------------------------------------------------- #
def test_the_chatterbox_repair_set_names_the_proven_engine_release():
    assert "chatterbox-tts==0.1.7" in bootstrap.CHATTERBOX_PKGS


def test_the_repair_set_carries_the_setuptools_compatibility_pin():
    """Without it, PerTh cannot import pkg_resources and the model cannot build."""
    assert "setuptools==80.9.0" in bootstrap.CHATTERBOX_PKGS


def test_every_repair_package_is_exactly_pinned():
    for pkg in bootstrap.CHATTERBOX_PKGS:
        assert "==" in pkg and not any(c in pkg for c in "<>~!")


def test_the_repair_set_mirrors_requirements_exactly():
    text = (REPO_ROOT / "scripts" / "requirements.txt").read_text(encoding="utf-8")
    pinned = {line.split("#", 1)[0].split(";", 1)[0].strip()
              for line in text.splitlines()}
    for pkg in bootstrap.CHATTERBOX_PKGS:
        assert pkg in pinned, f"{pkg} is not the version requirements.txt pins"


def test_the_kokoro_repair_set_is_unchanged():
    assert bootstrap.KOKORO_PKGS == ["kokoro==0.9.4", "soundfile==0.13.1", "scipy==1.17.1"]


# --------------------------------------------------------------------------- #
# The health probe
# --------------------------------------------------------------------------- #
def test_the_health_probe_runs_in_a_subprocess_against_the_venv(recorded_runs, tmp_path):
    venv_py = tmp_path / "python.exe"
    bootstrap.chatterbox_is_healthy(venv_py)
    assert recorded_runs, "the probe must not evaluate the package in this process"
    assert recorded_runs[0][0] == str(venv_py)


def test_the_health_probe_checks_the_exact_shipped_module_and_class(recorded_runs, tmp_path):
    bootstrap.chatterbox_is_healthy(tmp_path / "python.exe")
    script = recorded_runs[0][-1]
    assert "chatterbox.tts_turbo" in script
    assert "ChatterboxTurboTTS" in script


def test_the_health_probe_never_imports_the_unexported_root_symbol(recorded_runs, tmp_path):
    """``from chatterbox import ChatterboxTurboTTS`` fails against the 0.1.7 wheel."""
    bootstrap.chatterbox_is_healthy(tmp_path / "python.exe")
    script = recorded_runs[0][-1]
    assert "from chatterbox import ChatterboxTurboTTS" not in script


def test_the_health_probe_downloads_no_weights_and_builds_no_model(recorded_runs, tmp_path):
    bootstrap.chatterbox_is_healthy(tmp_path / "python.exe")
    script = recorded_runs[0][-1]
    for token in ("from_pretrained", "from_local", "snapshot_download", "ChatterboxTurboTTS("):
        assert token not in script, f"the probe would load weights via {token!r}"


def test_a_healthy_probe_reports_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="OK\n", stderr=""))
    ok, reason = bootstrap.chatterbox_is_healthy(tmp_path / "python.exe")
    assert ok is True and reason == "ok"


def test_a_missing_package_reports_truthfully(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="MISSING:chatterbox\n", stderr=""))
    ok, reason = bootstrap.chatterbox_is_healthy(tmp_path / "python.exe")
    assert ok is False and "chatterbox" in reason


def test_a_broken_class_import_reports_truthfully(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="BROKEN:ChatterboxTurboTTS\n", stderr=""))
    ok, reason = bootstrap.chatterbox_is_healthy(tmp_path / "python.exe")
    assert ok is False and "ChatterboxTurboTTS" in reason


def test_a_crashed_probe_is_reported_rather_than_swallowed(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("no such interpreter")

    monkeypatch.setattr(bootstrap.subprocess, "run", boom)
    ok, reason = bootstrap.chatterbox_is_healthy(tmp_path / "python.exe")
    assert ok is False and "probe failed" in reason


# --------------------------------------------------------------------------- #
# The self-heal install
# --------------------------------------------------------------------------- #
def test_the_repair_installs_into_the_existing_venv_only(recorded_runs, tmp_path):
    bootstrap.ensure_chatterbox_installed(tmp_path / "python.exe", lambda _m: None)
    install = recorded_runs[0]
    assert install[:4] == [str(tmp_path / "python.exe"), "-m", "pip", "install"]
    assert "--user" not in install
    for pkg in bootstrap.CHATTERBOX_PKGS:
        assert pkg in install


def test_the_repair_verifies_itself_with_the_health_probe(recorded_runs, tmp_path):
    bootstrap.ensure_chatterbox_installed(tmp_path / "python.exe", lambda _m: None)
    assert len(recorded_runs) >= 2, "the repair must re-probe after installing"


def test_a_failed_repair_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="", stderr="resolution impossible"))
    assert bootstrap.ensure_chatterbox_installed(tmp_path / "python.exe", lambda _m: None) is False


# --------------------------------------------------------------------------- #
# Weights pre-download and warm-up
# --------------------------------------------------------------------------- #
def test_the_predownload_targets_the_one_project_huggingface_cache(monkeypatch, tmp_path):
    captured: dict = {}

    class FakeProc:
        stdout = iter(())

        def wait(self):
            return 0

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = kwargs.get("env") or {}
        return FakeProc()

    monkeypatch.setattr(bootstrap.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(bootstrap, "venv_python", lambda: tmp_path / "python.exe")
    monkeypatch.setattr(bootstrap, "_run", lambda *a, **k: SimpleNamespace(returncode=0))
    bootstrap.predownload_chatterbox(bootstrap.SetupLog())

    hf = str(bootstrap.RESOURCES_DIR / "models" / "huggingface")
    assert captured["env"].get("HF_HOME") == hf
    assert "ResembleAI/chatterbox-turbo" in captured["cmd"][-1]


def test_the_predownload_is_skipped_when_the_package_is_absent(monkeypatch, tmp_path):
    called = {"popen": False}
    monkeypatch.setattr(bootstrap, "venv_python", lambda: tmp_path / "python.exe")
    monkeypatch.setattr(bootstrap, "_run", lambda *a, **k: SimpleNamespace(returncode=1))
    monkeypatch.setattr(bootstrap.subprocess, "Popen",
                        lambda *a, **k: called.__setitem__("popen", True))
    bootstrap.predownload_chatterbox(bootstrap.SetupLog())
    assert called["popen"] is False


def test_the_warmup_builds_the_model_on_cpu_and_never_raises(monkeypatch, tmp_path):
    captured: dict = {}

    class FakeProc:
        stdout = iter(("warm\n",))

        def wait(self):
            return 0

    monkeypatch.setattr(bootstrap.subprocess, "Popen",
                        lambda cmd, **k: (captured.update(cmd=list(cmd), env=k.get("env") or {}),
                                          FakeProc())[1])
    bootstrap.warmup_chatterbox(tmp_path / "python.exe", lambda _m: None)
    script = captured["cmd"][-1]
    assert "from_pretrained" in script
    assert '"cpu"' in script or "'cpu'" in script


def test_a_failed_warmup_is_logged_not_raised(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("blocked")

    monkeypatch.setattr(bootstrap.subprocess, "Popen", boom)
    lines: list[str] = []
    bootstrap.warmup_chatterbox(tmp_path / "python.exe", lines.append)
    assert lines


# --------------------------------------------------------------------------- #
# The first-run checkbox — opt-in, honest about the size
# --------------------------------------------------------------------------- #
def test_run_setup_accepts_a_chatterbox_download_flag():
    import inspect

    params = inspect.signature(bootstrap.run_setup).parameters
    assert "download_chatterbox" in params
    assert params["download_chatterbox"].default is False


def test_the_chatterbox_download_is_opt_in_unlike_kokoro():
    """~3.86 GiB is too large to check by default; Kokoro's ~300 MB stays as it was."""
    tree = ast.parse(BOOTSTRAP_SRC)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "run_with_gui")
    src = ast.get_source_segment(BOOTSTRAP_SRC, fn)
    assert '"download_chatterbox": tk.BooleanVar(value=False)' in src


def test_the_checkbox_states_the_real_download_size():
    tree = ast.parse(BOOTSTRAP_SRC)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "run_with_gui")
    src = ast.get_source_segment(BOOTSTRAP_SRC, fn)
    assert "3.9 GB" in src or "3.86" in src


def test_the_kokoro_checkbox_default_is_untouched():
    tree = ast.parse(BOOTSTRAP_SRC)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "run_with_gui")
    src = ast.get_source_segment(BOOTSTRAP_SRC, fn)
    assert '"download_kokoro": tk.BooleanVar(value=not skip_kokoro_default)' in src


def test_run_setup_skips_the_chatterbox_steps_when_not_requested(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(bootstrap, "find_suitable_python", lambda *a, **k: ["py"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda a: (3, 12))
    monkeypatch.setattr(bootstrap, "preflight_report", lambda *a, **k: {})
    monkeypatch.setattr(bootstrap, "_create_validated_venv", lambda *a, **k: True)
    monkeypatch.setattr(bootstrap, "pip_install_requirements", lambda *a: True)
    monkeypatch.setattr(bootstrap, "validate_installed_packages", lambda *a: True)
    monkeypatch.setattr(bootstrap, "ensure_ffmpeg", lambda *a: True)
    monkeypatch.setattr(bootstrap, "predownload_kokoro",
                        lambda *a: calls.append("kokoro"))
    monkeypatch.setattr(bootstrap, "predownload_chatterbox",
                        lambda *a: calls.append("chatterbox"))
    ok, _msg = bootstrap.run_setup(False, lambda *a: None, bootstrap.SetupLog())
    assert ok is True
    assert calls == []


def test_run_setup_downloads_chatterbox_only_when_asked(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(bootstrap, "find_suitable_python", lambda *a, **k: ["py"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda a: (3, 12))
    monkeypatch.setattr(bootstrap, "preflight_report", lambda *a, **k: {})
    monkeypatch.setattr(bootstrap, "_create_validated_venv", lambda *a, **k: True)
    monkeypatch.setattr(bootstrap, "pip_install_requirements", lambda *a: True)
    monkeypatch.setattr(bootstrap, "validate_installed_packages", lambda *a: True)
    monkeypatch.setattr(bootstrap, "ensure_ffmpeg", lambda *a: True)
    monkeypatch.setattr(bootstrap, "predownload_kokoro", lambda *a: None)
    monkeypatch.setattr(bootstrap, "predownload_chatterbox",
                        lambda *a: calls.append("chatterbox"))
    monkeypatch.setattr(bootstrap, "chatterbox_is_healthy", lambda p: (False, "absent"))
    monkeypatch.setattr(bootstrap, "venv_python", lambda *a, **k: Path("py"))
    ok, _msg = bootstrap.run_setup(False, lambda *a: None, bootstrap.SetupLog(),
                                   download_chatterbox=True)
    assert ok is True
    assert calls == ["chatterbox"]


# --------------------------------------------------------------------------- #
# Required imports and startup safety
# --------------------------------------------------------------------------- #
def test_chatterbox_is_a_verified_import_with_its_pip_name_mapped():
    assert "chatterbox" in bootstrap.REQUIRED_IMPORTS
    assert bootstrap._PIP_NAME["chatterbox"] == "chatterbox-tts"


def test_the_pre_existing_required_imports_are_untouched():
    for mod in ("edge_tts", "pydub", "fitz", "mutagen", "PIL", "nltk"):
        assert mod in bootstrap.REQUIRED_IMPORTS


def test_missing_local_recordings_are_not_a_setup_requirement():
    """A machine may have the package and no references — it must still launch."""
    assert "Chatterbox-Voice-Uploads" not in BOOTSTRAP_SRC


def test_the_launch_fast_path_still_only_health_checks_kokoro(monkeypatch):
    """The Chatterbox probe imports torch; it must not run on every launch."""
    tree = ast.parse(BOOTSTRAP_SRC)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "_launch_with_kokoro_healthcheck")
    src = ast.get_source_segment(BOOTSTRAP_SRC, fn)
    assert "chatterbox_is_healthy" not in src


def test_the_bootstrap_pins_no_cuda_specific_install():
    for token in ("+cu", "download.pytorch.org", "--extra-index-url"):
        assert token not in BOOTSTRAP_SRC
