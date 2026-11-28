"""v0.8.2 Phase 4 — the base environment's uv provisioning: pins, containment, targets, commands, the interpreter
resolver and the sync / proof / repair sequence in ``shared/bootstrap.py``.

uv is the base environment's only installer. Everything here is a fake under ``tmp_path`` or a recorded command: no uv
runs, nothing is downloaded, the real ``.venv`` and runtime data are never touched (the conftest refuses a real uv).
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

import gate_locator
import source_probe
from shared import app_python, bootstrap, uv_runner

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED = REPO_ROOT / "scripts" / "shared"
PLATFORMS = ("win32", "darwin")


# --------------------------------------------------------------------------- #
# A. One set of pins
# --------------------------------------------------------------------------- #
def test_the_download_metadata_names_exactly_the_pinned_archives():
    downloads = json.loads((SHARED / "python-downloads.json").read_text(encoding="utf-8"))
    assert set(downloads) == {uv_runner.WINDOWS.python_key, uv_runner.MACOS.python_key}
    for pins in (uv_runner.WINDOWS, uv_runner.MACOS):
        entry = downloads[pins.python_key]
        assert entry["url"] == pins.python_url and entry["sha256"] == pins.python_sha256
        assert entry["build"] == uv_runner.PYTHON_BUILD
        assert (entry["major"], entry["minor"], entry["patch"]) == (3, 12, 15)
        assert entry["url"].startswith("https://github.com/astral-sh/python-build-standalone/releases/download/")


def test_the_macos_stage_zero_carries_the_same_pins():
    text = (SHARED / "bootstrap_host_macos.sh").read_text(encoding="utf-8")
    pins = uv_runner.MACOS
    for line in (f'UV_VERSION="{uv_runner.UV_VERSION}"', f'UV_ARCHIVE_NAME="{pins.uv_archive}"',
                 f"UV_SIZE={pins.uv_size}", f'UV_SHA256="{pins.uv_sha256}"', f'UV_EXE_SHA256="{pins.uv_exe_sha256}"',
                 f'PY_VERSION="{uv_runner.PYTHON_VERSION}"', f'BUILD_TAG="{uv_runner.PYTHON_BUILD}"',
                 f'PY_KEY="{pins.python_key}"', f'PY_MINOR_KEY="{pins.python_minor_key}"',
                 f"ARCHIVE_SIZE={pins.python_size}", f'ARCHIVE_SHA256="{pins.python_sha256}"',
                 f'PY_SYS_VERSION="{pins.python_sys_version}"'):
        assert f"\n{line}\n" in text, line


def test_the_base_project_requires_the_pinned_uv_and_python_and_is_this_version():
    from shared import version

    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == version.VERSION
    assert project["project"]["requires-python"] == "==3.12.*", "the exact 3.12.15 is every command's --python"
    tool = project["tool"]["uv"]
    assert tool["required-version"] == f"=={uv_runner.UV_VERSION}"
    assert tool["package"] is False and tool["default-groups"] == []
    assert tool["python-preference"] == "only-managed" and tool["python-downloads"] == "manual"
    assert "workspace" not in tool, "no uv workspaces"
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert lock["requires-python"] == "==3.12.*"


def test_the_gate_reads_its_one_pytest_pin_from_the_base_projects_dev_group():
    verify = gate_locator.load_gate("act_verify_uv_pin")
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = tomllib.loads(text)
    assert project["dependency-groups"]["dev"] == [f"pytest=={verify._pinned_pytest()}"]
    assert text.count('"pytest==') == 1, "one pytest pin, nowhere else (not even as a constraint)"


# --------------------------------------------------------------------------- #
# B. Everything uv writes stays inside the copy
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_uv_path_is_inside_the_copy(tmp_path, platform):
    root = tmp_path / "ACT C1"
    runtime = root / "files" / "runtime-data"
    assert uv_runner.uv_exe(root, platform).parent == runtime / "uv"
    assert uv_runner.managed_python_home(root, platform) == runtime / "uv" / "python" / uv_runner.pins(platform).python_key
    assert uv_runner.cache_dir(root) == runtime / "uvc", "short on purpose: the path budget"
    assert uv_runner.mirror_archive(root, platform).parent == runtime / "uv" / "mirror" / uv_runner.PYTHON_BUILD
    assert uv_runner.base_env(root) == root / ".venv"
    assert uv_runner.engine_env(root, "qwen3") == root / ".venv-engines" / "qwen3"
    with pytest.raises(ValueError):
        uv_runner.engine_env(root, "../escape")


def test_the_environment_drops_every_inherited_steering_and_confines_uv(tmp_path):
    root = tmp_path / "ACT C1"
    inherited = {"PATH": "x", "UV_INDEX_URL": "https://egress.invalid", "uv_cache_dir": "C:/elsewhere",
                 "PIP_INDEX_URL": "x", "PYTHONPATH": "x", "PYTHONHOME": "x", "VIRTUAL_ENV": "x", "CONDA_PREFIX": "x",
                 "XDG_CONFIG_HOME": "x", "SSL_CERT_FILE": "x", "__PYVENV_LAUNCHER__": "x", "KEEP_ME": "1"}
    with uv_runner.Operation(root) as operation:
        env = uv_runner.environment(root, operation, offline=True, env_dir=root / ".venv", base=inherited)
        assert env["KEEP_ME"] == "1" and env["PATH"] == "x"
        for dropped in ("UV_INDEX_URL", "uv_cache_dir", "PIP_INDEX_URL", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
                        "CONDA_PREFIX", "XDG_CONFIG_HOME", "SSL_CERT_FILE", "__PYVENV_LAUNCHER__"):
            assert dropped not in env, dropped
        assert env["UV_NO_CONFIG"] == "1" and env["UV_NO_ENV_FILE"] == "1" and env["UV_OFFLINE"] == "1"
        assert env["UV_PYTHON_PREFERENCE"] == "only-managed" and env["UV_PYTHON_DOWNLOADS"] == "manual"
        assert env["UV_PYTHON_INSTALL_BIN"] == "0" and env["UV_PYTHON_INSTALL_REGISTRY"] == "0"
        assert env["UV_PYTHON_NO_REGISTRY"] == "1"
        assert env["UV_PYTHON_DOWNLOADS_JSON_URL"] == str(SHARED / "python-downloads.json")
        assert env["UV_PROJECT_ENVIRONMENT"] == str(root / ".venv")
        assert env["UV_LINK_MODE"] in ("copy", "clone")
        for key in ("UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "UV_PYTHON_CACHE_DIR", "UV_PYTHON_BIN_DIR", "UV_TOOL_DIR",
                    "UV_TOOL_BIN_DIR", "UV_CREDENTIALS_DIR", "TEMP", "TMP", "TMPDIR"):
            assert Path(env[key]).is_relative_to(root), key
        assert Path(env["UV_PYTHON_CACHE_DIR"]).is_relative_to(operation.path), "a refused archive never sticks"
        assert Path(env["TEMP"]).is_relative_to(operation.path)
    assert "UV_OFFLINE" not in uv_runner.environment(root, operation, base={})


def test_an_operations_scratch_is_its_own_and_is_removed_alone(tmp_path):
    root = tmp_path / "ACT"
    sibling = uv_runner.scratch_root(root) / "someone-else"
    sibling.mkdir(parents=True)
    with uv_runner.Operation(root) as operation:
        assert operation.tmp.is_dir() and operation.python_cache.is_dir()
        assert operation.path.parent == uv_runner.scratch_root(root)
        (operation.tmp / "partial.whl").write_bytes(b"x")
    assert not operation.path.exists() and sibling.is_dir()


# --------------------------------------------------------------------------- #
# C. Only this copy's own environments, only its own project
# --------------------------------------------------------------------------- #
@pytest.fixture
def project(tmp_path):
    root = tmp_path / "ACT C1"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    return root


def test_a_sync_targets_only_the_base_or_an_engine_environment(project, tmp_path):
    uv_runner.check_target(project, project / ".venv")
    uv_runner.check_target(project, project / ".venv-engines" / "omnivoice")
    for wrong in (project / ".venv" / "engines" / "qwen3", project / "venv", tmp_path / "elsewhere" / ".venv",
                  project / ".venv-engines" / "Bad Name", project / ".venv-engines"):
        with pytest.raises(uv_runner.TargetRefused):
            uv_runner.sync_command(project, wrong, profile="user", offline=True)
    (project / "uv.lock").unlink()
    with pytest.raises(uv_runner.TargetRefused):
        uv_runner.check_target(project, project / ".venv")


@pytest.mark.parametrize("platform, mode", [("win32", "copy"), ("darwin", "clone")])
def test_the_sync_is_locked_exact_and_profile_explicit(project, platform, mode):
    user = uv_runner.sync_command(project, project / ".venv", profile="user", offline=True,
                                  reinstall_packages=("kokoro",), platform=platform)
    assert user[1:4] == ["sync", "--project", str(project)]
    for token in ("--locked", "--no-python-downloads", "--compile-bytecode", "--no-config", "--no-dev", "--offline"):
        assert token in user, token
    assert user[user.index("--python") + 1] == "3.12.15"
    assert user[user.index("--link-mode") + 1] == mode
    assert user[user.index("--reinstall-package") + 1] == "kokoro"
    dev = uv_runner.sync_command(project, project / ".venv", profile="dev", offline=False,
                                 refresh_packages=("numpy",), platform=platform)
    assert dev[dev.index("--group") + 1] == "dev" and "--no-dev" not in dev and "--offline" not in dev
    assert dev[dev.index("--refresh-package") + 1] == "numpy"
    for command in (user, dev):
        assert "hardlink" not in command and "--managed-python" not in command and "--frozen" not in command
    with pytest.raises(ValueError):
        uv_runner.sync_command(project, project / ".venv", profile="test", offline=True)


def test_the_interpreter_is_installed_from_acts_own_archive_and_never_registered(project):
    command = uv_runner.python_install_command(project, reinstall=True)
    assert command[1:4] == ["python", "install", "3.12.15"]
    assert command[command.index("--mirror") + 1] == uv_runner.mirror_dir(project).resolve().as_uri()
    assert command[command.index("--python-downloads-json-url") + 1] == str(SHARED / "python-downloads.json")
    assert {"--no-bin", "--no-registry", "--no-config", "--reinstall"} <= set(command)
    venv = uv_runner.venv_command(project, project / ".venv")
    assert venv[1:3] == ["venv", str(project / ".venv")] and "--no-python-downloads" in venv
    assert venv[venv.index("--python") + 1] == "3.12.15"


# --------------------------------------------------------------------------- #
# D. Whose interpreter is it?
# --------------------------------------------------------------------------- #
def _cfg(env: Path, home: Path | None, *, uv: bool) -> Path:
    env.mkdir(parents=True, exist_ok=True)
    lines = ([f"home = {home}"] if home else []) + ["include-system-site-packages = false", "version_info = 3.12.15"]
    if uv:
        lines.append("uv = 0.13.10")
    (env / "pyvenv.cfg").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env


@pytest.mark.parametrize("platform", PLATFORMS)
def test_an_environment_on_the_exact_managed_folder_passes_and_nothing_else_does(tmp_path, platform):
    root = tmp_path / "ACT C1"
    env = root / ".venv"
    _cfg(env, uv_runner.managed_venv_home(root, platform), uv=True)
    assert uv_runner.built_by_uv(env) and uv_runner.home_problem(root, env, platform) == ""
    minor = uv_runner.python_install_dir(root) / uv_runner.pins(platform).python_minor_key
    _cfg(env, minor if platform == "win32" else minor / "bin", uv=True)
    assert "not on this copy's managed Python" in uv_runner.home_problem(root, env, platform), "never the link"
    _cfg(env, None, uv=True)
    assert uv_runner.home_problem(root, env, platform) == "it has no readable pyvenv.cfg home"
    _cfg(env, root / "files" / "runtime-data" / "python", uv=False)
    assert not uv_runner.built_by_uv(env)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_the_resolver_keeps_a_migrated_copys_engines_on_their_own_interpreter(tmp_path, platform):
    root = tmp_path / "ACT C1"
    managed_home, legacy_home = app_python.own_homes(root, platform)
    assert app_python.app_env_base(root, platform) == app_python.managed(root, platform), "a fresh copy"
    _cfg(root / ".venv", legacy_home, uv=False)
    assert app_python.app_env_base(root, platform) == app_python.legacy(root, platform), "not yet migrated"
    _cfg(root / ".venv", managed_home, uv=True)
    assert app_python.app_env_base(root, platform) == app_python.managed(root, platform), "migrated"
    _cfg(root / ".venv", tmp_path / "elsewhere" / "python", uv=False)
    assert app_python.app_env_base(root, platform) == app_python.managed(root, platform), "never another's"
    assert app_python.is_own_base(root, app_python.legacy(root, platform), platform)
    assert app_python.is_own_base(root, app_python.managed(root, platform), platform)
    assert not app_python.is_own_base(root, tmp_path / "python.exe", platform)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_another_copys_python_is_recognised_in_either_layout(tmp_path, platform):
    other = tmp_path / "ACT A1"
    managed_home, legacy_home = app_python.own_homes(other, platform)
    assert app_python.owner_of_home(managed_home, platform) == other
    assert app_python.owner_of_home(legacy_home, platform) == other
    assert app_python.owner_of_home(tmp_path / "Python312", platform) is None


def test_every_engine_installer_asks_the_one_resolver():
    """Qwen3 and OmniVoice keep their own installers until 5A/5B; their base interpreter comes from app_python."""
    import inspect

    from shared import cleanup_state, optional_setup_protocol
    from tts import omnivoice_runtime, qwen3_runtime

    for function in (qwen3_runtime.app_base_python, omnivoice_runtime.app_owned_python, cleanup_state.app_base_python,
                     optional_setup_protocol.app_python):
        assert "app_env_base" in inspect.getsource(function), function.__qualname__


# --------------------------------------------------------------------------- #
# E. The sync sequence in bootstrap
# --------------------------------------------------------------------------- #
class _Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)

    __call__ = line

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def uv_env(monkeypatch, tmp_path):
    """bootstrap against a disposable copy whose .venv is uv's, on the copy's managed interpreter; uv recorded."""
    root = tmp_path / "ACT C1"
    root.mkdir()
    for name in ("pyproject.toml", "uv.lock"):
        (root / name).write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "REPO_ROOT", root)
    monkeypatch.setattr(bootstrap, "VENV_DIR", root / ".venv")
    monkeypatch.setattr(bootstrap, "PYPROJECT_FILE", root / "pyproject.toml")
    monkeypatch.setattr(bootstrap, "UV_LOCK_FILE", root / "uv.lock")
    monkeypatch.setattr(bootstrap, "PROFILE_FILE", root / "files" / "runtime-data" / "environment-profile.json")
    managed = uv_runner.managed_python(root)
    monkeypatch.setattr(bootstrap, "APP_PYTHON", managed)
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"python")
    _cfg(root / ".venv", uv_runner.managed_venv_home(root), uv=True)
    venv_py = bootstrap.venv_python()
    venv_py.parent.mkdir(parents=True, exist_ok=True)
    venv_py.write_bytes(b"python")
    monkeypatch.setattr(bootstrap.uv_runner, "uv_problem", lambda root, platform=None: "")
    monkeypatch.setattr(bootstrap, "_SYNCED", [False])  # module state: never leaks into another test
    monkeypatch.setattr(bootstrap, "_REINSTALLS", [0])
    calls: list[SimpleNamespace] = []
    outcomes: list[tuple[int, list[str]]] = []

    def fake_uv(command, *, offline, log, env_dir):
        calls.append(SimpleNamespace(command=list(command), offline=offline, env_dir=env_dir))
        return outcomes.pop(0) if outcomes else (0, [])

    monkeypatch.setattr(bootstrap, "_uv", fake_uv)
    asked: list[str] = []
    monkeypatch.setattr(bootstrap, "_ask_download_consent", lambda log, why: asked.append(why) or allowed[0])
    allowed = [False]
    return SimpleNamespace(root=root, calls=calls, outcomes=outcomes, asked=asked, allowed=allowed)


def test_a_sync_runs_offline_from_the_repair_cache_first_and_asks_nothing(uv_env):
    assert bootstrap.sync_base_packages(_Log()) is True
    [call] = uv_env.calls
    assert call.offline is True and "--offline" in call.command and "--no-dev" in call.command
    assert call.env_dir == bootstrap.VENV_DIR and uv_env.asked == []


@pytest.mark.parametrize("said", [
    # uv 0.13.10, verbatim from the Phase 4 fresh-copy run (a cold cache):
    "  cause: Network connectivity is disabled, but the requested data wasn't found in the cache: "
    "https://files.pythonhosted.org/packages/18/cf/ae99bd066571656185be0d88ee70abc58467b76f2f7c8bfeb48735a71fe6/"
    "torch-2.6.0-cp312-cp312-win_amd64.whl",
    "error: `tqdm` was not found in the cache",
])
def test_a_cache_that_lacks_a_file_asks_once_and_a_no_downloads_nothing(uv_env, said):
    uv_env.outcomes.append((1, ["Resolved 171 packages in 1ms", "error: Failed to download `torch==2.6.0`", said]))
    log = _Log()
    assert bootstrap.sync_base_packages(log) is False
    assert len(uv_env.calls) == 1 and len(uv_env.asked) == 1
    assert "downloading them was not allowed" in log.text


def test_a_yes_syncs_online_once(uv_env):
    uv_env.outcomes.append((2, ["was not found in the cache"]))
    uv_env.allowed[0] = True
    assert bootstrap.sync_base_packages(_Log()) is True
    offline, online = uv_env.calls
    assert offline.offline and not online.offline and "--offline" not in online.command


def test_any_other_failure_is_not_a_reason_to_go_online(uv_env):
    uv_env.outcomes.append((1, ["error: Failed to build `something`"]))
    assert bootstrap.sync_base_packages(_Log()) is False
    assert len(uv_env.calls) == 1 and uv_env.asked == []


def test_the_developer_profile_is_kept_by_every_sync(uv_env):
    bootstrap.select_profile("dev")
    bootstrap.sync_base_packages(_Log(), reinstall=("kokoro",))
    command = uv_env.calls[-1].command
    assert command[command.index("--group") + 1] == "dev" and "--no-dev" not in command


@pytest.mark.parametrize("damage", ["legacy", "foreign-home", "no-interpreter"])
def test_uv_never_syncs_an_environment_it_could_delete_with_its_engines(uv_env, damage):
    """uv recreates an environment it cannot use -- deleting everything in it, engines included. Only uv's own
    environment on exactly this copy's managed interpreter is synced where it stands."""
    if damage == "legacy":
        _cfg(bootstrap.VENV_DIR, uv_env.root / "files" / "runtime-data" / "python", uv=False)
    elif damage == "foreign-home":
        _cfg(bootstrap.VENV_DIR, uv_env.root.parent / "ACT A1" / "files" / "runtime-data" / "uv" / "python"
             / uv_runner.pins().python_key, uv=True)
    else:
        bootstrap.APP_PYTHON.unlink()
    log = _Log()
    assert bootstrap.sync_base_packages(log) is False
    assert uv_env.calls == [] and "was not synced where it stands" in log.text


def test_damaged_files_are_reinstalled_from_the_cache_then_fetched_again_then_refused(uv_env, monkeypatch):
    reports = [{"numpy": "x is missing"}, {"numpy": "x has changed (SHA-256)"}, {"numpy": "x has changed (SHA-256)"}]
    monkeypatch.setattr(bootstrap.venv_integrity, "record_damage", lambda venv, **kw: reports.pop(0))
    uv_env.allowed[0] = True
    assert bootstrap.prove_installed_files(_Log()) is False
    cache, clean, refresh = uv_env.calls
    assert cache.offline and cache.command[cache.command.index("--reinstall-package") + 1] == "numpy"
    # The damaged kept files are removed first: --refresh-package alone revalidates metadata and installs the same
    # damaged unpacked archive again (Phase 4 cache-damage scenario, real uv 0.13.10).
    assert clean.command[1:4] == ["cache", "clean", "numpy"] and clean.env_dir is None
    assert not refresh.offline and refresh.command[refresh.command.index("--reinstall-package") + 1] == "numpy"
    assert len(uv_env.asked) == 1, "a refresh downloads: asked first"


def test_a_no_to_fetching_damaged_kept_files_again_removes_nothing(uv_env, monkeypatch):
    reports = [{"numpy": "x is missing"}, {"numpy": "x has changed (SHA-256)"}]
    monkeypatch.setattr(bootstrap.venv_integrity, "record_damage", lambda venv, **kw: reports.pop(0))
    assert bootstrap.prove_installed_files(_Log()) is False
    [cache] = uv_env.calls
    assert cache.offline and len(uv_env.asked) == 1, "asked, refused: no cache clean, no download"


def test_cleaning_the_cache_always_names_its_packages():
    with pytest.raises(ValueError):
        uv_runner.cache_clean_command(Path("R"), ())
    assert uv_runner.cache_clean_command(Path("R"), ("tqdm",))[1:4] == ["cache", "clean", "tqdm"]


def test_files_repaired_from_the_cache_are_proved_before_anything_is_recorded(uv_env, monkeypatch):
    reports = [{"tqdm": "its RECORD is missing"}, {}]
    monkeypatch.setattr(bootstrap.venv_integrity, "record_damage", lambda venv, **kw: reports.pop(0))
    assert bootstrap.prove_installed_files(_Log()) is True
    [call] = uv_env.calls
    assert call.offline and "tqdm" in call.command


def test_a_targeted_repair_withdraws_the_receipt_and_names_the_damage_too(uv_env, monkeypatch):
    bootstrap.requirements_state_path().write_text("{}", encoding="utf-8")
    seen = []
    monkeypatch.setattr(bootstrap.venv_integrity, "record_damage", lambda venv, **kw: {"scipy": "x is missing"})

    def fake_sync(log, reinstall=(), refresh=()):
        seen.append((bootstrap.requirements_state_path().exists(), tuple(reinstall)))
        return False

    monkeypatch.setattr(bootstrap, "sync_base_packages", fake_sync)
    assert bootstrap.repair_base_packages(("kokoro", "misaki"), _Log()) is False
    assert seen == [(False, ("kokoro", "misaki", "scipy"))]


def test_a_successful_install_tidies_the_cache_once_and_only_after_a_real_sync(uv_env):
    assert bootstrap.install_requirements(_Log()) is True
    commands = [call.command[1:3] for call in uv_env.calls]
    assert commands == [["sync", "--project"], ["cache", "prune"]]
    bootstrap._prune_cache(_Log())
    assert len(uv_env.calls) == 2, "nothing synced since the last prune"


def test_creating_the_environment_uses_uv_on_the_managed_python_only(uv_env):
    assert bootstrap.create_venv([str(bootstrap.APP_PYTHON)], _Log()) is True
    [call] = uv_env.calls
    assert call.command[1:3] == ["venv", str(bootstrap.VENV_DIR)] and call.command[call.command.index("--python") + 1] \
        == "3.12.15"


def test_the_spacy_model_is_restored_by_uv_in_a_uv_environment(uv_env, monkeypatch, tmp_path):
    from shared import spacy_store

    wheel = tmp_path / "en_core_web_sm-3.8.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    monkeypatch.setattr(spacy_store, "kept_wheel", lambda root: wheel)
    monkeypatch.setattr(spacy_store, "store_dir", lambda root: tmp_path)
    monkeypatch.setattr(spacy_store, "requirement_line", lambda path: f"{path} --hash=sha256:{'a' * 64}\n")
    monkeypatch.setattr(bootstrap, "_child_run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps({"spacy": "3.8.7", "model": None}), stderr=""))
    assert bootstrap.restore_kept_spacy_model(_Log()) is True
    [call] = uv_env.calls
    assert call.command[1:3] == ["pip", "install"] and "--offline" in call.command and "--require-hashes" in call.command


# --------------------------------------------------------------------------- #
# F. No second installer, no second wrapper
# --------------------------------------------------------------------------- #
def test_bootstrap_runs_uv_only_through_the_one_wrapper():
    source = (SHARED / "bootstrap.py").read_text(encoding="utf-8")
    assert len(re.findall(r"uv_runner\.Operation\(", source)) == 1, "one place builds uv's environment"
    assert "astral.sh/uv/install" not in source and "pip install uv" not in source
    for module in SHARED.glob("*.py"):
        if module.name in ("uv_runner.py", "bootstrap.py"):
            continue
        text = module.read_text(encoding="utf-8")
        assert "UV_PYTHON_INSTALL_DIR" not in text and '"sync", "--project"' not in text, module.name


def test_the_profile_switch_is_explicit_and_never_inferred_from_pytest():
    source = (SHARED / "bootstrap.py").read_text(encoding="utf-8")
    writers = re.findall(r"select_profile\(", source)
    assert len(writers) == 2, "the definition and the --profile handler"
    assert "pytest" not in source[source.index("def selected_profile"):source.index("def select_profile")]


def test_the_path_budget_covers_what_python_opens_and_only_uv_touches_the_deeper_cache():
    """Measured 2026-11-27 on this exact lock (bootstrap.DEEPEST_FILE_CHARS): a uv-built .venv reaches 155 characters
    below the app's folder, the managed Python 164; both fit the 172 budget the long-path check applies. The repair
    cache reaches 171, which only uv (Rust: \\\\?\\ paths past MAX_PATH by itself) reads or writes -- so no module of the
    app's Python may name it except the wrapper that hands its path to uv."""
    assert bootstrap.DEEPEST_FILE_CHARS >= 164 + 1
    assert uv_runner.cache_dir(Path("R")).relative_to("R").as_posix() == "files/runtime-data/uvc", "kept short"
    def code(path: Path) -> str:  # comments may describe it
        return "\n".join(line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                         if not line.lstrip().startswith("#"))

    naming = sorted(path.name for path in source_probe.application_python_files()
                    if re.search(r"""["'/\\]uvc\b""", code(path)))
    assert naming == ["uv_runner.py"], naming


# --------------------------------------------------------------------------- #
# G. The download question is never asked with Tk off the main thread
# --------------------------------------------------------------------------- #
def test_a_worker_thread_never_creates_tk_and_asks_through_the_window_that_owns_the_main_thread(monkeypatch):
    """Launch-time self-heals run on show_repair_dialog's worker thread. A Tk root made there while the main thread
    runs Tk ends the process inside Tcl, so the question goes to the window (or is a No without one)."""
    import threading

    import tkinter

    monkeypatch.setattr(bootstrap, "_DOWNLOAD_ALLOWED", None)
    monkeypatch.setattr(tkinter, "Tk", lambda *a, **k: pytest.fail("Tk was created on a worker thread"))
    answers: dict = {}

    def ask(asker):
        monkeypatch.setattr(bootstrap, "_CONSENT_ASKER", asker)
        worker = threading.Thread(target=lambda: answers.setdefault(
            asker, bootstrap._ask_download_consent(lambda line: None, "why")))
        worker.start()
        worker.join(10)

    ask(None)
    seen = []
    ask(lambda question: seen.append(question) or True)
    assert list(answers.values()) == [False, True]
    assert "Download them now" in seen[0]
    monkeypatch.setattr(bootstrap, "_DOWNLOAD_ALLOWED", True)
    assert bootstrap._ask_download_consent(lambda line: None, "why") is True, "setup itself already consented"


def test_a_persons_answer_is_asked_once_per_process_and_a_no_without_anyone_to_ask_is_not_kept(monkeypatch):
    """Found natively on HOME-MacOS (Phase 4, damaged-cache repair with downloads refused): the in-place repair asked,
    the rebuild route that followed asked the same question again. A person's answer now stands for the process; a No
    given only because no window could ask is not remembered, so a later window still asks."""
    import threading

    monkeypatch.setattr(bootstrap, "_DOWNLOAD_ALLOWED", None)
    asked: list[str] = []

    def on_worker(asker):
        monkeypatch.setattr(bootstrap, "_CONSENT_ASKER", asker)
        result: list[bool] = []
        worker = threading.Thread(target=lambda: result.append(bootstrap._ask_download_consent(lambda line: None, "x")))
        worker.start()
        worker.join(10)
        return result[0]

    assert on_worker(None) is False and bootstrap._DOWNLOAD_ALLOWED is None, "nobody answered: nothing is kept"
    assert on_worker(lambda question: asked.append(question) or False) is False
    assert on_worker(lambda question: asked.append(question) or True) is False, "the person's No stands"
    assert len(asked) == 1, "asked exactly once"


# --------------------------------------------------------------------------- #
# H. A damaged package is reinstalled in place before anything is rebuilt
# --------------------------------------------------------------------------- #
@pytest.fixture
def repair_route(uv_env, monkeypatch):
    monkeypatch.setattr(bootstrap, "install_path_problem", lambda *a, **k: None)
    monkeypatch.setattr(bootstrap, "long_path_runtime_problem", lambda log: None)
    monkeypatch.setattr(bootstrap, "_take_engine_lease", lambda log, refusal: (None, None))
    monkeypatch.setattr(bootstrap, "recover_interrupted_replacement", lambda log, **k: None)
    rebuilt: list[str] = []
    monkeypatch.setattr(bootstrap, "_create_validated_venv", lambda *a, **k: rebuilt.append("rebuild") or False)
    damaged = bootstrap.VenvHealth(bootstrap.VENV_REPAIRABLE, "damaged-packages", "numpy is not installed",
                                   version=(3, 12), ssl=True, tk=True, executes=True)
    healthy = bootstrap.VenvHealth(bootstrap.VENV_HEALTHY, "ok", "ok", version=(3, 12), ssl=True, tk=True,
                                   executes=True)
    verdicts: list = []
    monkeypatch.setattr(bootstrap, "assess_venv_health", lambda **k: verdicts.pop(0))
    repaired: list[tuple] = []
    outcome = [True]
    monkeypatch.setattr(bootstrap, "repair_base_packages",
                        lambda names, log: repaired.append(tuple(names)) or outcome[0])
    return SimpleNamespace(rebuilt=rebuilt, verdicts=verdicts, damaged=damaged, healthy=healthy,
                           repaired=repaired, outcome=outcome)


def test_damaged_packages_are_reinstalled_in_place_and_nothing_is_rebuilt(repair_route):
    repair_route.verdicts += [repair_route.damaged, repair_route.healthy]
    ok, message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is True and "reinstalled" in message
    assert repair_route.repaired == [()] and repair_route.rebuilt == []


def test_a_targeted_repair_that_does_not_make_it_whole_falls_back_to_the_rebuild(repair_route, monkeypatch):
    monkeypatch.setattr(bootstrap, "find_suitable_python", lambda log, prefer_tk=True: [str(bootstrap.APP_PYTHON)])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    repair_route.verdicts += [repair_route.damaged, repair_route.damaged]
    ok, _message = bootstrap.repair_venv(_Log(), headless=True)
    assert ok is False and repair_route.repaired == [()] and repair_route.rebuilt == ["rebuild"]


@pytest.mark.parametrize("reason", ["repair-requested", "legacy-environment", "interpreter-mismatch"])
def test_other_reasons_go_straight_to_the_rebuild(repair_route, monkeypatch, reason):
    monkeypatch.setattr(bootstrap, "find_suitable_python", lambda log, prefer_tk=True: [str(bootstrap.APP_PYTHON)])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    repair_route.verdicts.append(bootstrap.VenvHealth(bootstrap.VENV_REPAIRABLE, reason, "x", executes=True))
    bootstrap.repair_venv(_Log(), headless=True)
    assert repair_route.repaired == [] and repair_route.rebuilt == ["rebuild"]


# --------------------------------------------------------------------------- #
# Small Phase 4 corrections found on HOME-PC, closed on HOME-MacOS
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("argv, expected", [
    (["uv", "--", "run", "--", "python", "-V"], ["run", "--", "python", "-V"]),
    (["uv", "run", "--", "python", "-V"], ["run", "--", "python", "-V"]),
    (["uv", "--", "--version"], ["--version"]),
])
def test_the_developer_passthrough_drops_only_the_separator(monkeypatch, argv, expected):
    """Minor finding 3: every "--" used to be stripped once the first was the separator, so `uv run -- cmd` lost the
    one uv needs. Nothing runs: uv's start is recorded, and the operation scratch is a stand-in."""
    started: list[list[str]] = []

    class _Operation:
        def __init__(self, root):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(uv_runner, "uv_problem", lambda root, platform=None: "")
    monkeypatch.setattr(uv_runner, "Operation", _Operation)
    monkeypatch.setattr(uv_runner, "environment", lambda root, operation, **kw: {})
    monkeypatch.setattr(uv_runner, "run", lambda command, env, **kw: started.append(list(command)) or 0)
    assert uv_runner._main(argv) == 0
    assert started[0][1:] == expected


@pytest.mark.parametrize("tk_works", [True, False])
def test_the_headless_summary_says_what_the_environment_really_has(monkeypatch, tk_works):
    """Minor finding 2: headless setup always said the window "needs Tk, which is not available", also on a Python whose
    Tk works (seen natively on HOME-MacOS, Phase 4). The summary now follows a real Tk proof of the environment."""
    lines: list[str] = []
    monkeypatch.setattr(bootstrap, "LOG", SimpleNamespace(line=lines.append, close=lambda: None))
    monkeypatch.setattr(bootstrap, "run_setup", lambda progress, log, headless: (True, "Setup complete."))
    monkeypatch.setattr(bootstrap, "_tcl_tk_ok", lambda py: tk_works)
    assert bootstrap._run_headless(skip_kokoro=True) == 0
    text = "\n".join(lines)
    assert "Tk is unavailable" not in text
    assert ("needs Tk" in text) is (not tk_works)
    assert ("The app window can start" in text) is tk_works
