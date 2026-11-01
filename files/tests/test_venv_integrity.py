"""v0.7.0 acceptance D1 and D3: a copied installation runs on its own Python and FFmpeg, and a damaged app
environment is noticed at launch and repaired -- from the launcher or from an obvious GUI action.

D1 (reproduced on the acceptance copies): a robocopy of an installed app folder kept the original's absolute
``pyvenv.cfg`` ``home`` and ``ffmpeg-state.json``, so the copy ran on the original's Python and FFmpeg -- and every
conversion failed with ``WinError 2`` once the original's FFmpeg was moved. D3: ``numpy/__init__.py`` removed from the
app environment passed ``--venv-check``, the first Kokoro job failed with "pip install kokoro …", and Clear Downloaded
Data (rightly) would not offer the environment while it held the Qwen3 engine, so there was no way back in the app.

Every environment here is a fake under ``tmp_path``; nothing touches the real ``.venv``, installs or runs a model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared import bootstrap, ffmpeg_health, venv_integrity

EXE = ".exe" if os.name == "nt" else ""


# --------------------------------------------------------------------------- #
# Fake environments
# --------------------------------------------------------------------------- #
def make_venv(venv: Path, *, home: Path | None = None, version: str = "3.12.15") -> Path:
    venv.mkdir(parents=True, exist_ok=True)
    lines = [] if home is None else [f"home = {home}"]
    lines += ["include-system-site-packages = false", f"version = {version}"]
    (venv / "pyvenv.cfg").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return venv


def site_of(venv: Path) -> Path:
    site = venv / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    return site


def install_dist(venv: Path, name: str, version: str, files: dict[str, bytes]) -> None:
    """A distribution as pip leaves it: its files plus a dist-info whose RECORD lists them with sizes."""
    site = site_of(venv)
    rows = []
    for relative, data in files.items():
        path = site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        rows.append(f"{relative},sha256=x,{len(data)}")
    info = site / f"{name}-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n", encoding="utf-8")
    rows += [f"{name}-{version}.dist-info/METADATA,,", f"{name}-{version}.dist-info/RECORD,,",
             f"../../Scripts/{name}.exe,sha256=x,10", f"{name}/__pycache__/__init__.cpython-312.pyc,,"]
    (info / "RECORD").write_text("\n".join(rows) + "\n", encoding="utf-8")


@pytest.fixture
def healthy_numpy(tmp_path):
    venv = make_venv(tmp_path / "app" / ".venv")
    install_dist(venv, "numpy", "1.26.4", {"numpy/__init__.py": b"# numpy\n",
                                          "numpy/core/_multiarray_umath.cp312-win_amd64.pyd": b"\0" * 64,
                                          "numpy/core/numeric.py": b"x = 1\n"})
    install_dist(venv, "six", "1.17.0", {"six.py": b"# six\n"})
    return venv


# --------------------------------------------------------------------------- #
# D1 — whose Python is it?
# --------------------------------------------------------------------------- #
def test_another_installations_own_python_is_foreign(tmp_path):
    original, copy = tmp_path / "ACT A1", tmp_path / "copies" / "ACT C1"
    venv = make_venv(copy / ".venv", home=original / "files" / "runtime-data" / "python")
    assert venv_integrity.foreign_base_python(venv, copy) == original / "files" / "runtime-data" / "python"


def test_this_installations_own_python_and_a_system_python_are_not_foreign(tmp_path):
    root = tmp_path / "ACT"
    own = make_venv(root / ".venv", home=root / "files" / "runtime-data" / "python")
    assert venv_integrity.foreign_base_python(own, root) is None
    system = make_venv(tmp_path / "dev" / ".venv", home=Path(r"C:\Users\someone\AppData\Local\Programs\Python\Python312"))
    assert venv_integrity.foreign_base_python(system, tmp_path / "dev") is None, "a developer checkout's base"
    assert venv_integrity.foreign_base_python(make_venv(tmp_path / "nohome" / ".venv"), tmp_path / "nohome") is None


@pytest.mark.skipif(os.name != "nt", reason="Windows paths compare without regard to case")
def test_the_same_folder_spelled_in_another_case_is_still_this_installation(tmp_path):
    root = tmp_path / "ACT"
    venv = make_venv(root / ".venv", home=Path(str(root).upper()) / "FILES" / "Runtime-Data" / "PYTHON")
    assert venv_integrity.foreign_base_python(venv, root) is None


@pytest.fixture
def env(monkeypatch, tmp_path):
    """bootstrap pointed at a disposable installation; the venv interpreter probe is faked as healthy."""
    root = tmp_path / "ACT C1"
    venv = root / ".venv"
    monkeypatch.setattr(bootstrap, "REPO_ROOT", root)
    monkeypatch.setattr(bootstrap, "VENV_DIR", venv)
    monkeypatch.setattr(bootstrap, "REQUIREMENTS_FILE", root / "scripts" / "requirements.txt")
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: {"version": (3, 12), "ssl": True, "tk": True})
    interpreter = bootstrap.venv_python()
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_bytes(b"interpreter")
    return SimpleNamespace(root=root, venv=venv)


def test_a_copy_running_on_the_originals_python_is_repaired_not_launched(env, tmp_path):
    make_venv(env.venv, home=tmp_path / "ACT A1" / "files" / "runtime-data" / "python")
    health = bootstrap.assess_venv_health()
    assert (health.state, health.reason) == (bootstrap.VENV_REPAIRABLE, "foreign-python")
    assert "another copy of the app" in health.detail and health.executes
    assert bootstrap._venv_check() == bootstrap.EXIT_VENV_REPAIR_REQUIRED, "the launcher rebuilds it"


def test_a_copy_on_its_own_python_launches(env):
    make_venv(env.venv, home=env.root / "files" / "runtime-data" / "python")
    assert bootstrap.assess_venv_health().state == bootstrap.VENV_HEALTHY
    assert bootstrap._venv_check() == 0


@pytest.mark.skipif(not bootstrap.IS_WINDOWS, reason="the app's own base Python is the Windows layout")
def test_the_rebuild_happens_on_this_copys_own_python_first():
    """bootstrap.find_suitable_python tries the app's own Python before anything on the computer."""
    assert bootstrap._candidate_interpreters()[0] == [str(bootstrap.APP_PYTHON)]


def test_the_recorded_ffmpeg_of_another_copy_is_never_this_copys_pin(monkeypatch, tmp_path):
    original, copy = tmp_path / "ACT A1", tmp_path / "ACT C1"
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", copy / "files" / "bin")
    for root in (original, copy):
        assert ffmpeg_health.belongs_to_another_installation(root / "files" / "bin") is (root == original)
        assert ffmpeg_health.belongs_to_another_installation(
            root / "files" / "bin" / "ffmpeg" / "9.0.1" / "bin") is (root == original)
    assert not ffmpeg_health.belongs_to_another_installation(
        Path(r"C:\Users\x\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg\ffmpeg-9.0.1-full_build\bin"))


def _pair_in(directory: Path) -> ffmpeg_health.Pair:
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        (directory / f"{name}{EXE}").write_bytes(b"binary " + name.encode())
    return ffmpeg_health.pair_in(directory)


def test_a_copied_ffmpeg_state_is_replaced_by_this_copys_own_ffmpeg(monkeypatch, tmp_path):
    """The acceptance shape: the copy's ffmpeg-state.json names the original's bundled FFmpeg, which still exists
    and still runs. The copy proves and pins its own instead, and never executes the original's."""
    original, copy = tmp_path / "ACT A1", tmp_path / "ACT C1"
    monkeypatch.setattr(ffmpeg_health, "REPO_ROOT", copy)
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", copy / "files" / "bin")
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", copy / "files" / "runtime-data")
    monkeypatch.setattr(ffmpeg_health, "_path_dirs", lambda: [original / "files" / "bin"])
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [])
    theirs, ours = _pair_in(original / "files" / "bin"), _pair_in(copy / "files" / "bin")
    assert ffmpeg_health.save_state(ffmpeg_health.HealthState(pair=theirs))  # what the copy inherited
    ran: list[Path] = []
    pair = ffmpeg_health.ensure_ready(runner=lambda exe: ran.append(Path(exe)) or (True, "ffmpeg version 9"))
    assert pair is not None and pair.directory == ours.directory
    assert all(original not in path.parents for path in ran), "the original's binaries were never run"
    assert ffmpeg_health.pinned_pair().directory == ours.directory
    assert [p.directory for p in ffmpeg_health.discover_pairs()] == [ours.directory], "theirs is no candidate"


# --------------------------------------------------------------------------- #
# D3 — are the packages whole?
# --------------------------------------------------------------------------- #
def test_an_intact_environment_has_no_damage(healthy_numpy):
    assert venv_integrity.package_damage(healthy_numpy) == []


def test_a_package_whose_files_are_gone_under_its_metadata_is_damage(healthy_numpy):
    """The acceptance reproduction: numpy/__init__.py removed, numpy's .dist-info left (pip: "already satisfied")."""
    assert venv_integrity.package_damage(healthy_numpy) == []  # the cached list is built while intact...
    (healthy_numpy / "Lib" / "site-packages" / "numpy" / "__init__.py").unlink()
    assert venv_integrity.package_damage(healthy_numpy) == ["numpy-1.26.4: numpy/__init__.py is missing"]


def test_damage_is_found_even_when_no_list_was_cached_before_it(healthy_numpy):
    """The list comes from each package's RECORD, never from what is on disk at the time."""
    (healthy_numpy / "Lib" / "site-packages" / "numpy" / "core" / "_multiarray_umath.cp312-win_amd64.pyd").unlink()
    assert not (healthy_numpy / venv_integrity.MANIFEST_NAME).exists()
    assert venv_integrity.package_damage(healthy_numpy) == [
        "numpy-1.26.4: numpy/core/_multiarray_umath.cp312-win_amd64.pyd is missing"]


def test_a_truncated_native_library_and_a_missing_module_are_damage(healthy_numpy):
    site = healthy_numpy / "Lib" / "site-packages"
    (site / "numpy" / "core" / "_multiarray_umath.cp312-win_amd64.pyd").write_bytes(b"\0" * 10)
    (site / "six.py").unlink()
    assert sorted(venv_integrity.package_damage(healthy_numpy)) == [
        "numpy-1.26.4: numpy/core/_multiarray_umath.cp312-win_amd64.pyd has changed", "six-1.17.0: six.py is missing"]


def test_deep_pure_python_files_are_left_to_the_import_proof(healthy_numpy):
    (healthy_numpy / "Lib" / "site-packages" / "numpy" / "core" / "numeric.py").unlink()
    assert venv_integrity.package_damage(healthy_numpy) == [], "only __init__, top-level modules and native files"


def test_a_required_distribution_that_is_gone_entirely_is_damage(healthy_numpy):
    found = venv_integrity.package_damage(healthy_numpy, required=["numpy", "Six", "scipy"])
    assert found == ["scipy is not installed"]


def test_the_cached_list_follows_the_installed_distributions(healthy_numpy):
    venv_integrity.package_damage(healthy_numpy)
    cached = json.loads((healthy_numpy / venv_integrity.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert cached["distributions"] == ["numpy-1.26.4.dist-info", "six-1.17.0.dist-info"]
    assert ["numpy/__init__.py", 8] in cached["files"]["numpy-1.26.4.dist-info"]
    assert all("../" not in path and "__pycache__" not in path
               for files in cached["files"].values() for path, _size in files)
    install_dist(healthy_numpy, "tqdm", "4.67.3", {"tqdm/__init__.py": b"x"})
    (healthy_numpy / "Lib" / "site-packages" / "tqdm" / "__init__.py").unlink()
    assert venv_integrity.package_damage(healthy_numpy) == ["tqdm-4.67.3: tqdm/__init__.py is missing"]


def test_a_check_that_cannot_read_anything_finds_nothing(tmp_path):
    assert venv_integrity.package_damage(make_venv(tmp_path / ".venv")) == []
    assert venv_integrity.package_damage(tmp_path / "absent") == []


def test_findings_are_bounded(tmp_path):
    venv = make_venv(tmp_path / ".venv")
    install_dist(venv, "many", "1.0", {f"m{n}.py": b"x" for n in range(9)})
    for n in range(9):
        (venv / "Lib" / "site-packages" / f"m{n}.py").unlink()
    found = venv_integrity.package_damage(venv, limit=3)
    assert len(found) == 4 and found[-1] == "and 6 more"


def test_a_damaged_environment_is_repaired_by_the_launcher(env, healthy_numpy, monkeypatch):
    monkeypatch.setattr(bootstrap, "VENV_DIR", healthy_numpy)
    interpreter = bootstrap.venv_python()
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_bytes(b"interpreter")
    assert bootstrap.assess_venv_health().state == bootstrap.VENV_HEALTHY
    (healthy_numpy / "Lib" / "site-packages" / "numpy" / "__init__.py").unlink()
    health = bootstrap.assess_venv_health()
    assert (health.state, health.reason) == (bootstrap.VENV_REPAIRABLE, "damaged-packages")
    assert "numpy/__init__.py is missing" in health.detail and "package files kept in this folder" in health.detail
    assert bootstrap._venv_check() == bootstrap.EXIT_VENV_REPAIR_REQUIRED


def test_a_locked_package_that_vanished_is_damage_once_the_environment_was_reconciled(env, monkeypatch):
    site_of(make_venv(env.venv))
    monkeypatch.setattr(bootstrap, "_locked_distributions", lambda version: ("numpy",))
    health = bootstrap.assess_venv_health()
    assert (health.state, health.reason) == (bootstrap.VENV_REPAIRABLE, "damaged-packages")
    assert "numpy is not installed" in health.detail


def test_the_lock_names_required_packages_only_for_a_reconciled_locked_environment(env, monkeypatch):
    scripts = env.root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "requirements.txt").write_text("tqdm==4.67.3\n", encoding="utf-8")
    (scripts / "requirements-lock-windows-py312.txt").write_text(
        f"# artifact: tqdm-4.67.3-py3-none-any.whl\ntqdm==4.67.3 --hash=sha256:{'a' * 64}\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap.base_packages, "lock_applies", lambda version, **kw: True)
    monkeypatch.setattr(bootstrap, "requirements_are_current", lambda: False)
    assert bootstrap._locked_distributions((3, 12)) == (), "not yet reconciled: the drift path installs them"
    monkeypatch.setattr(bootstrap, "requirements_are_current", lambda: True)
    assert bootstrap._locked_distributions((3, 12)) == ("tqdm",)


# --------------------------------------------------------------------------- #
# D3 — a repair the user can ask for, and a launch that never dead-ends
# --------------------------------------------------------------------------- #
def test_a_requested_repair_makes_the_next_launch_rebuild(env):
    make_venv(env.venv)
    assert venv_integrity.request_repair(env.venv, "test")
    health = bootstrap.assess_venv_health()
    assert (health.state, health.reason) == (bootstrap.VENV_REPAIRABLE, "repair-requested")
    assert bootstrap._venv_check() == bootstrap.EXIT_VENV_REPAIR_REQUIRED


def test_the_request_lives_in_the_environment_it_condemns(tmp_path):
    """A rebuilt environment is born without it; one that was put back keeps it for the next try."""
    venv = make_venv(tmp_path / ".venv")
    assert venv_integrity.request_repair(venv)
    assert venv_integrity.repair_request_path(venv).parent == venv
    assert not venv_integrity.request_repair(tmp_path / "no-environment"), "nothing to repair: not recorded"
    assert not (tmp_path / "no-environment").exists()


def test_a_failed_repair_of_a_still_running_environment_opens_the_app_with_a_notice(monkeypatch):
    """Before: any failed repair ended in a dialog and no app at all. An environment that still runs opens with
    limits, says why, and the repair is tried again next start (the request or the damage is still there)."""
    monkeypatch.setattr(bootstrap, "repair_venv", lambda log, headless=False: (False, "The files were refused."))
    monkeypatch.setattr(bootstrap, "assess_venv_health", lambda **kw: bootstrap.VenvHealth(
        bootstrap.VENV_REPAIRABLE, "damaged-packages", "x", version=(3, 12), ssl=True, tk=True, executes=True))
    seen = {}
    monkeypatch.setattr(bootstrap, "_launch_with_kokoro_healthcheck",
                        lambda **kw: seen.update(kw) or 0)
    monkeypatch.setattr(bootstrap, "show_warning_dialog", lambda *a: seen.setdefault("dialog", a))
    assert bootstrap._repair_and_launch(headless=False) == 0
    assert seen["allow_repair_handoff"] is False and "dialog" not in seen
    assert "could not be repaired: The files were refused." in seen["notices"][0]


def test_a_failed_repair_of_an_environment_that_cannot_run_still_says_so(monkeypatch):
    monkeypatch.setattr(bootstrap, "repair_venv", lambda log, headless=False: (False, "No Python."))
    monkeypatch.setattr(bootstrap, "assess_venv_health", lambda **kw: bootstrap.VenvHealth(
        bootstrap.VENV_REPAIRABLE, "interpreter-dead", "x"))
    shown = []
    monkeypatch.setattr(bootstrap, "show_warning_dialog", lambda *a: shown.append(a))
    monkeypatch.setattr(bootstrap, "_launch_with_kokoro_healthcheck", lambda **kw: pytest.fail("must not launch"))
    assert bootstrap._repair_and_launch(headless=False) == 1 and shown


def test_kokoro_never_tells_a_user_to_pip_install(monkeypatch):
    from tts import kokoro_synth

    text = str(kokoro_synth._pipeline_failure(ImportError("No module named 'numpy.core'")))
    assert "pip install" not in text and "Setup_and_Run-audiobook-creation-tool" in text
    assert "Repair App Environment" in text and "numpy.core" in text


# --------------------------------------------------------------------------- #
# D3 — the GUI action (Preferences & Data)
# --------------------------------------------------------------------------- #
tk = pytest.importorskip("tkinter")
import tk_gate  # noqa: E402
from shared import config, preferences_ui  # noqa: E402
from shared import settings as app_settings  # noqa: E402


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def dialog_for(tk_root, tmp_path):
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    config.invalidate()
    made = []

    def make(repo_root, answer=True):
        calls = []
        dialog = preferences_ui.PreferencesDialog(
            tk_root, {}, confirm=lambda title, message: calls.append((title, message)) or answer,
            repo_root=repo_root)
        made.append(dialog)
        return dialog, calls

    yield make
    for dialog in made:
        dialog.close()
    app_settings.use_path(None)
    config.invalidate()


def test_repair_app_environment_schedules_the_launchers_repair_and_removes_nothing(dialog_for, tmp_path):
    root = tmp_path / "ACT"
    venv = make_venv(root / ".venv")
    engine = venv / "engines" / "qwen3"
    engine.mkdir(parents=True)
    (engine / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    dialog, calls = dialog_for(root)
    assert dialog.button_repair.cget("text") == preferences_ui.REPAIR_BUTTON_LABEL
    assert dialog.button_repair is not dialog.button_cleanup
    assert dialog.repair_environment() is True
    assert calls and calls[0][0] == preferences_ui.REPAIR_CONFIRM_TITLE
    assert "Qwen3 voice engine are kept" in calls[0][1] and "Setup_and_Run-audiobook-creation-tool" in calls[0][1]
    assert venv_integrity.repair_requested(venv)
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    assert after == sorted(before + [f".venv/{venv_integrity.REPAIR_REQUEST_NAME}"]), "nothing else changed"
    assert dialog.status_kind == "success" and "Close the app" in dialog.var_status.get()


def test_declining_the_repair_changes_nothing(dialog_for, tmp_path):
    venv = make_venv(tmp_path / "ACT" / ".venv")
    dialog, _calls = dialog_for(tmp_path / "ACT", answer=False)
    assert dialog.repair_environment() is False
    assert not venv_integrity.repair_requested(venv)
    assert "Nothing was changed" in dialog.var_status.get()


def test_a_repair_that_cannot_be_recorded_says_what_to_do(dialog_for, tmp_path):
    dialog, _calls = dialog_for(tmp_path / "ACT-without-environment")
    assert dialog.repair_environment() is False
    assert dialog.status_kind == "error" and "Setup_and_Run-audiobook-creation-tool" in dialog.var_status.get()
