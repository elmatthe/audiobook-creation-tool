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

from shared import base_packages, bootstrap  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BOOTSTRAP_SRC = Path(bootstrap.__file__).read_text(encoding="utf-8")


@pytest.fixture
def recorded_runs(monkeypatch):
    """Capture every subprocess.run the bootstrap would make."""
    runs: list[list[str]] = []

    def fake_run(cmd, *a, **k):
        runs.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="OK", stderr="")

    def fake_install(venv_py, log):
        # v0.7.0: the one package installer (the dependency lock); recorded in its place in the sequence.
        runs.append([str(venv_py), "-m", "pip", "<install_base_packages>"])
        return True

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    monkeypatch.setattr(bootstrap, "install_base_packages", fake_install)
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
    assert recorded_runs[0] == [str(tmp_path / "python.exe"), "-m", "pip", "<install_base_packages>"]
    # The one installer installs the lock, which carries every pin of the Chatterbox repair set.
    locked = {entry.key: entry.version for entry in base_packages.parse_lock(
        base_packages.lock_path(bootstrap.REQUIREMENTS_FILE).read_text(encoding="utf-8")).entries}
    for pkg in bootstrap.CHATTERBOX_PKGS:
        name, version = pkg.split("==")
        assert locked[base_packages.canonical_name(name)] == version, pkg


def test_the_repair_verifies_itself_with_the_health_probe(recorded_runs, tmp_path):
    bootstrap.ensure_chatterbox_installed(tmp_path / "python.exe", lambda _m: None)
    assert len(recorded_runs) >= 2, "the repair must re-probe after installing"
    assert recorded_runs[1][-1] == bootstrap._CHATTERBOX_PROBE


def test_a_failed_repair_returns_false(monkeypatch, tmp_path):
    probes = []
    monkeypatch.setattr(bootstrap, "install_base_packages", lambda venv_py, log: False)
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: probes.append(a) or SimpleNamespace(
        returncode=0, stdout="OK", stderr=""))
    assert bootstrap.ensure_chatterbox_installed(tmp_path / "python.exe", lambda _m: None) is False
    assert probes == [], "a failed install is not followed by a health claim"


# --------------------------------------------------------------------------- #
# v0.7.0: first-run setup never downloads a model; the four choices go through the consented panel
# --------------------------------------------------------------------------- #
def test_the_unpinned_predownload_and_warmup_routes_are_gone():
    """They fetched at upstream ``main`` with no review screen; the consented worker replaced them."""
    for name in ("predownload_kokoro", "predownload_chatterbox", "warmup_kokoro_pipeline", "warmup_chatterbox"):
        assert not hasattr(bootstrap, name), name
    tree = ast.parse(BOOTSTRAP_SRC)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_setup")
    src = ast.get_source_segment(BOOTSTRAP_SRC, fn)
    for forbidden in ("snapshot_download", "KPipeline", "from_pretrained", "hf_hub_download"):
        assert forbidden not in src


def test_the_wizard_offers_the_four_choices_in_order_with_the_approved_defaults():
    assert [(c, d) for c, _label, d, _note in bootstrap.OPTIONAL_CHOICES] == [
        ("kokoro", True), ("chatterbox", False), ("qwen3-customvoice", False), ("qwen3-base", False)]


def test_choosing_is_not_installing_the_panel_is_the_only_install_route():
    tree = ast.parse(BOOTSTRAP_SRC)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_with_gui")
    src = ast.get_source_segment(BOOTSTRAP_SRC, fn)
    assert "OptionalSetupPanel" in src
    assert "run_setup(on_progress, LOG)" in src  # the base install takes no voice choice at all
    assert "selection[:] = " in src  # read once on the Tk thread when Begin Setup is pressed


def _isolate_environment(monkeypatch, tmp_path):
    """Point run_setup's environment state at tmp_path, not the real repo.

    ``run_setup`` ends by stamping the environment it just built. These tests
    stub every install *step* but left ``VENV_DIR``/``LOGS_DIR`` pointing at the
    real checkout, so each run rewrote the developer's real
    ``.venv/.requirements-state.json`` and appended to the real setup log —
    traced mechanically in PRE-PLAN-6 Phase 1 (finding L1b). The shared guard in
    ``conftest.py`` now fails any test that touches production state.
    """
    monkeypatch.setattr(bootstrap, "VENV_DIR", tmp_path / ".venv")
    monkeypatch.setattr(bootstrap, "LOGS_DIR", tmp_path / "logs")


def test_run_setup_builds_the_base_and_starts_nothing_else(monkeypatch, tmp_path):
    _isolate_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(bootstrap, "find_suitable_python", lambda *a, **k: ["py"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda a: (3, 12))
    monkeypatch.setattr(bootstrap, "preflight_report", lambda *a, **k: {})
    monkeypatch.setattr(bootstrap, "_create_validated_venv", lambda *a, **k: True)
    monkeypatch.setattr(bootstrap, "reconcile_requirements", lambda *a: (True, ""))
    monkeypatch.setattr(bootstrap, "ensure_ffmpeg", lambda *a: True)
    monkeypatch.setattr(bootstrap.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("the base setup started a process of its own"))
    steps: list[int] = []
    ok, msg = bootstrap.run_setup(lambda step, _m: steps.append(step), bootstrap.SetupLog())
    assert ok is True and msg == "Setup complete."
    assert steps[-1] == bootstrap.BASE_SETUP_STEPS


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
    assert "Cloned-Voice-Uploads" not in BOOTSTRAP_SRC


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
