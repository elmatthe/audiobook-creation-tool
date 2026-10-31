"""v0.7.0 portability remediation: the app environment's hash lock, verified package store and pip policy.

Three properties, each proved here rather than assumed:

* **Reproducible.** ``scripts/requirements-lock-windows-py312.txt`` is a complete, minimal, hash-pinned freeze of
  ``requirements.txt`` (closed under the locked packages' own dependency metadata), this test environment *is* that set,
  and setup/repair install only from it: pip is never upgraded and a package the lock does not name cannot be installed.
* **Contained.** Every ACT-managed pip command for the app environment runs with no inherited pip/Python settings, no pip
  configuration file and its cache inside the app's folder, set explicitly (pip ignores a redirected ``LOCALAPPDATA``).
* **Recoverable.** Verified artifacts are kept in ``files/runtime-data/python-packages``; a complete store installs
  without the network, and a damaged kept file is fetched once more rather than installed.

The real-pip tests run the test interpreter's own pip offline (``--no-index``) against tiny generated wheels in a
disposable folder; nothing touches the working environment, the network or the user's pip cache.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from shared import base_packages, bootstrap

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
REQUIREMENTS = SCRIPTS / "requirements.txt"
LOCK = base_packages.lock_path(REQUIREMENTS)
#: The only locked releases PyPI publishes without a wheel; built by the environment's own locked setuptools.
SOURCE_ONLY = {"docopt", "antlr4-python3-runtime"}
WINDOWS_CP312 = {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt", "platform_machine": "AMD64",
                 "python_version": "3.12", "python_full_version": "3.12.15", "implementation_name": "cpython",
                 "platform_python_implementation": "CPython", "platform_release": "10", "platform_version": "10",
                 "implementation_version": "3.12.15"}


def _lock():
    return base_packages.parse_lock(LOCK.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# The lock is a faithful, complete and minimal freeze
# --------------------------------------------------------------------------- #
def test_the_lock_records_this_requirements_file_and_every_pin_of_it():
    assert base_packages.lock_problems(REQUIREMENTS.read_text(encoding="utf-8"), LOCK.read_text(encoding="utf-8"),
                                       hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()) == []


def test_every_locked_artifact_is_one_windows_cp312_or_pure_python_build():
    for entry in _lock().entries:
        assert len(entry.sha256) == 1, f"{entry.name}: exactly the one artifact pip installs"
        if entry.artifact.endswith(".whl"):
            tags = entry.artifact[:-4].split("-")[-3:]
            python, abi, platform = tags
            assert platform in ("any", "win_amd64"), entry.artifact
            assert python in ("py3", "py2.py3", "cp312") or python.startswith("cp3"), entry.artifact
            assert abi in ("none", "cp312", "abi3"), entry.artifact
        else:
            assert entry.key in SOURCE_ONLY, f"a new source-only release must be reviewed: {entry.artifact}"


def test_the_qualified_smart_app_control_pins_and_formerly_floating_transitives_are_frozen():
    locked = {entry.key: entry.version for entry in _lock().entries}
    for name, version in {"srsly": "2.5.3", "scikit-learn": "1.9.0", "numpy": "1.26.4", "torch": "2.6.0",
                          "spacy": "3.8.16", "chatterbox-tts": "0.1.7", "kokoro": "0.9.4", "setuptools": "80.9.0",
                          # previously resolved afresh on every install (review MAJOR 3), now fixed:
                          "filelock": "4.2.5", "aiohttp": "3.14.5", "pandas": "3.0.6", "regex": "2026.9.29",
                          "llvmlite": "0.50.0", "tokenizers": "0.22.2", "protobuf": "7.36.2"}.items():
        assert locked[name] == version, name
    assert "pip" not in locked, "pip is the base Python's own ensurepip pip, never installed or upgraded from the index"


def _closure() -> dict[str, set]:
    """Walk requirements.txt through the installed packages' own metadata, for Windows x86-64 CPython 3.12."""
    from importlib import metadata

    from packaging.requirements import Requirement

    locked = {entry.key: entry for entry in _lock().entries}
    todo = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate({**WINDOWS_CP312, "extra": ""}):
                todo.append((requirement, "requirements.txt"))
    needed: dict[str, set] = {}
    seen = set()
    while todo:
        requirement, wanted_by = todo.pop()
        key = base_packages.canonical_name(requirement.name)
        assert key in locked, f"{requirement} (needed by {wanted_by}) is not in the lock"
        assert requirement.specifier.contains(locked[key].version, prereleases=True), \
            f"{wanted_by} needs {requirement}, the lock has {locked[key].version}"
        needed.setdefault(key, set()).update(requirement.extras)
        state = (key, frozenset(requirement.extras))
        if state in seen:
            continue
        seen.add(state)
        for raw in metadata.distribution(locked[key].name).requires or []:
            child = Requirement(raw)
            extras = requirement.extras or {""}
            if child.marker is None or any(child.marker.evaluate({**WINDOWS_CP312, "extra": extra})
                                           for extra in extras):
                todo.append((child, f"{locked[key].name}=={locked[key].version}"))
    return needed


def test_this_test_environment_is_exactly_the_locked_set():
    """The full gate tests what a user installs: every locked package is installed here at its locked version."""
    from importlib import metadata

    wrong = []
    for entry in _lock().entries:
        try:
            installed = metadata.version(entry.name)
        except metadata.PackageNotFoundError:
            installed = None
        if installed != entry.version:
            wrong.append(f"{entry.name}: locked {entry.version}, installed {installed}")
    assert not wrong, ("this environment is not the locked set; reconcile it (start the app, or run "
                       "bootstrap.install_base_packages): " + "; ".join(wrong))


def test_the_lock_is_closed_and_minimal_under_its_packages_own_dependency_metadata():
    needed = _closure()
    locked = {entry.key for entry in _lock().entries}
    assert set(needed) == locked, (f"missing from the lock: {sorted(set(needed) - locked)}; "
                                   f"locked but needed by nothing: {sorted(locked - set(needed))}")


# --------------------------------------------------------------------------- #
# The pip policy
# --------------------------------------------------------------------------- #
def test_the_pip_environment_drops_inherited_steering_and_names_its_own_cache(tmp_path):
    cache = tmp_path / "files" / "runtime-data" / "pip-cache"
    base = {"PATH": r"C:\Windows", "PIP_INDEX_URL": "https://egress.invalid/simple", "PIP_TARGET": r"C:\elsewhere",
            "PIP_CACHE_DIR": r"C:\Users\someone\AppData\Local\pip\cache", "PIP_REQUIRE_HASHES": "0",
            "pip_find_links": r"C:\elsewhere", "PYTHONPATH": r"C:\ambient", "PYTHONHOME": r"C:\ambient",
            "VIRTUAL_ENV": r"C:\other\venv", "CONDA_PREFIX": r"C:\conda", "LOCALAPPDATA": r"C:\Users\someone\AppData"}
    env = base_packages.pip_environment(base, cache)
    assert env["PIP_CONFIG_FILE"] == os.devnull
    assert env["PIP_CACHE_DIR"] == str(cache)
    assert env["PIP_DISABLE_PIP_VERSION_CHECK"] == "1" and env["PIP_NO_INPUT"] == "1"
    for name in ("PIP_INDEX_URL", "PIP_TARGET", "PIP_REQUIRE_HASHES", "pip_find_links", "PYTHONPATH", "PYTHONHOME",
                 "VIRTUAL_ENV", "CONDA_PREFIX"):
        assert name not in env, name
    assert env["PATH"] == base["PATH"] and env["LOCALAPPDATA"] == base["LOCALAPPDATA"]


def test_the_commands_check_every_hash_and_the_installs_never_reach_an_index(tmp_path):
    py, req, store = tmp_path / "python.exe", tmp_path / "lock.txt", tmp_path / "store"
    download = base_packages.download_command(py, req, store)
    install = base_packages.install_command(py, req, store)
    forced = base_packages.install_command(py, req, store, no_deps=True, force=True)
    for command in (download, install, forced):
        assert command[:3] == [str(py), "-m", "pip"]
        assert "--require-hashes" in command and "--no-cache-dir" in command and "--no-build-isolation" in command
        assert "--upgrade" not in command and "-U" not in command and "--user" not in command
    assert download[3] == "download" and download[download.index("--dest") + 1] == str(store)
    for command in (install, forced):
        assert "--no-index" in command and command[command.index("--find-links") + 1] == str(store)
        assert "--require-virtualenv" in command
    assert "--no-deps" not in install, "the full install checks dependencies, so an incomplete lock fails loudly"
    assert {"--no-deps", "--force-reinstall"} <= set(forced)


def test_pip_is_never_upgraded_and_no_shipped_module_builds_an_unmanaged_pip_command():
    source = (SCRIPTS / "shared" / "bootstrap.py").read_text(encoding="utf-8")
    assert '"--upgrade", "pip"' not in source and "install --upgrade pip" not in source
    # Every literal pip invocation in shipped code lives where its policy is pinned and tested.
    allowed = {"shared/base_packages.py", "shared/spacy_store.py", "shared/bootstrap.py"}
    found = set()
    for path in SCRIPTS.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple)):
                strings = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if any(a == "-m" and b == "pip" for a, b in zip(strings, strings[1:])):
                    found.add(path.relative_to(SCRIPTS).as_posix())
    assert found <= allowed, found - allowed
    # bootstrap's only literal is venv_pip(); every bootstrap pip command passes the policy environment.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("_force_reinstall", "install_base_packages"):
            assert "_pip_environment()" in ast.get_source_segment(source, node), node.name


def test_the_other_pip_users_keep_their_own_contained_policy():
    from shared import spacy_store
    from tts import qwen3_packages, qwen3_wheels

    spacy = spacy_store.offline_install_command(Path("python.exe"), Path("req.txt"))
    assert {"--isolated", "--no-cache-dir", "--no-index", "--require-hashes"} <= set(spacy)
    # The Qwen3 engine installs only its own verified wheels (qwen3_wheels.install_command -> _pip_command).
    assert "qwen3_packages._pip_command(" in inspect.getsource(qwen3_wheels.install_command)
    source = inspect.getsource(qwen3_packages._pip_command)
    for flag in ("'--isolated'", "'--no-cache-dir'", "'--no-index'", "'--require-hashes'"):
        assert flag in source, flag


def _run_pip(*args, env):
    return subprocess.run([sys.executable, "-m", "pip", *args], capture_output=True, text=True, env=env,
                          timeout=180)


def test_real_pip_uses_the_named_cache_and_no_configuration_whatever_the_profile_says(tmp_path):
    """pip resolves its default cache through the Windows known-folder API, so a redirected LOCALAPPDATA does not
    move it (measured 2026-10-31). The explicit policy does, and a hostile config file is not read at all."""
    hostile = tmp_path / "hostile.ini"
    hostile.write_text("[global]\ncache-dir = C:\\hostile-cache\nindex-url = https://egress.invalid/simple\n",
                       encoding="utf-8")
    cache = tmp_path / "app" / "files" / "runtime-data" / "pip-cache"
    env = base_packages.pip_environment({**os.environ, "PIP_CONFIG_FILE": str(hostile),
                                         "LOCALAPPDATA": str(tmp_path / "fake-profile")}, cache)
    assert _run_pip("cache", "dir", env=env).stdout.strip().lower() == str(cache).lower()
    listed = _run_pip("config", "list", env=env)
    lines = listed.stdout.strip().splitlines()
    assert listed.returncode == 0 and lines, listed.stderr
    assert all(line.startswith(":env:.") for line in lines), "only the policy's own settings; no configuration file"
    assert "hostile" not in listed.stdout and "egress" not in listed.stdout


def _wheel(store: Path, name: str, version: str, requires: tuple = ()) -> tuple[str, str]:
    module = name.replace("-", "_")
    filename = f"{module}-{version}-py3-none-any.whl"
    path = store / filename
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{module}.py", f"VERSION = {version!r}\n")
        archive.writestr(f"{module}-{version}.dist-info/METADATA",
                         f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
                         + "".join(f"Requires-Dist: {r}\n" for r in requires))
        archive.writestr(f"{module}-{version}.dist-info/WHEEL",
                         "Wheel-Version: 1.0\nGenerator: ACT-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr(f"{module}-{version}.dist-info/RECORD", "")
    return filename, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def disposable_venv(tmp_path_factory):
    """A throwaway virtual environment with the base interpreter's own ensurepip pip (offline, about 10 s)."""
    folder = tmp_path_factory.mktemp("lock-venv") / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(folder)], check=True, capture_output=True, timeout=300)
    python = folder / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    return python


def _offline_install(python: Path, store: Path, lock_text: str, tmp_path: Path, *, policy_cache: Path):
    lock = tmp_path / "lock.txt"
    lock.write_text(lock_text, encoding="utf-8")
    env = base_packages.pip_environment(os.environ, policy_cache)
    return subprocess.run(base_packages.install_command(python, lock, store), capture_output=True, text=True,
                          env=env, timeout=300)


def test_real_pip_installs_a_complete_lock_from_the_store_alone_and_writes_no_cache(disposable_venv, tmp_path):
    store, cache = tmp_path / "store", tmp_path / "app-cache"
    store.mkdir()
    a_file, a_hash = _wheel(store, "act-lock-a", "1.0", requires=("act-lock-b==1.0",))
    b_file, b_hash = _wheel(store, "act-lock-b", "1.0")
    lock = (f"# {base_packages.ARTIFACT_PREFIX} {a_file}\nact-lock-a==1.0 --hash=sha256:{a_hash}\n"
            f"# {base_packages.ARTIFACT_PREFIX} {b_file}\nact-lock-b==1.0 --hash=sha256:{b_hash}\n")
    done = _offline_install(disposable_venv, store, lock, tmp_path, policy_cache=cache)
    assert done.returncode == 0, done.stdout + done.stderr
    shown = subprocess.run([str(disposable_venv), "-c", "import act_lock_a, act_lock_b; print(act_lock_a.VERSION)"],
                           capture_output=True, text=True)
    assert shown.stdout.strip() == "1.0"
    assert not cache.exists() or not any(cache.rglob("*")), "the store is the cache; pip kept nothing else"


def test_real_pip_refuses_a_dependency_the_lock_does_not_name(disposable_venv, tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    c_file, c_hash = _wheel(store, "act-lock-c", "1.0", requires=("act-lock-d==1.0",))
    _wheel(store, "act-lock-d", "1.0")  # present in the store, but NOT in the lock
    lock = f"# {base_packages.ARTIFACT_PREFIX} {c_file}\nact-lock-c==1.0 --hash=sha256:{c_hash}\n"
    done = _offline_install(disposable_venv, store, lock, tmp_path, policy_cache=tmp_path / "cache")
    assert done.returncode != 0
    assert "hash" in (done.stdout + done.stderr).lower()


def test_real_pip_refuses_a_kept_file_whose_hash_is_not_the_locked_one(disposable_venv, tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    e_file, e_hash = _wheel(store, "act-lock-e", "1.0")
    with zipfile.ZipFile(store / e_file, "a") as archive:  # the kept file is changed after it was locked
        archive.writestr("act_lock_e_extra.py", "X = 1\n")
    lock = f"# {base_packages.ARTIFACT_PREFIX} {e_file}\nact-lock-e==1.0 --hash=sha256:{e_hash}\n"
    done = _offline_install(disposable_venv, store, lock, tmp_path, policy_cache=tmp_path / "cache")
    assert done.returncode != 0
    assert "do not match the hashes" in (done.stdout + done.stderr).lower()


# --------------------------------------------------------------------------- #
# Setup and repair install only through the lock
# --------------------------------------------------------------------------- #
@pytest.fixture
def installer(tmp_path, monkeypatch):
    """bootstrap's installer against a disposable installation, with pip itself replaced by a recorder."""
    root = tmp_path / "app"
    (root / "scripts").mkdir(parents=True)
    requirements = root / "scripts" / "requirements.txt"
    requirements.write_text("tqdm==4.67.3\nsetuptools==80.9.0\n", encoding="utf-8")
    entries = {"setuptools": ("80.9.0", "setuptools-80.9.0-py3-none-any.whl"),
               "tqdm": ("4.67.3", "tqdm-4.67.3-py3-none-any.whl")}
    body = "".join(f"# {base_packages.ARTIFACT_PREFIX} {artifact}\n{name}=={version} --hash=sha256:{'a' * 64}\n"
                   for name, (version, artifact) in entries.items())
    base_packages.lock_path(requirements).write_text(body, encoding="utf-8")
    monkeypatch.setattr(bootstrap, "REPO_ROOT", root)
    monkeypatch.setattr(bootstrap, "REQUIREMENTS_FILE", requirements)
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    monkeypatch.setattr(base_packages, "lock_applies", lambda version, **kw: tuple(version or ())[:2] == (3, 12))
    monkeypatch.setenv("PIP_INDEX_URL", "https://egress.invalid/simple")
    monkeypatch.setenv("PIP_CACHE_DIR", r"C:\Users\someone\AppData\Local\pip\cache")
    calls = []
    outcomes = []

    def fake_pip(command, env, log):
        calls.append((list(command), dict(env)))
        return outcomes.pop(0) if outcomes else 0

    monkeypatch.setattr(bootstrap, "_pip", fake_pip)
    store = base_packages.store_dir(root)
    return type("Installer", (), {"root": root, "calls": calls, "outcomes": outcomes, "store": store,
                                  "entries": entries, "python": root / ".venv" / "Scripts" / "python.exe"})


def _verbs(calls):
    return [(command[3], "--no-deps" in command) for command, _env in calls]


def test_a_fresh_install_fetches_into_the_store_then_installs_from_it_alone(installer):
    assert bootstrap.install_base_packages(installer.python, lambda line: None) is True
    assert _verbs(installer.calls) == [("download", True), ("install", True), ("download", True),
                                       ("install", False)], "build tools first, then the whole lock"
    for command, env in installer.calls:
        assert "--require-hashes" in command and "--upgrade" not in command
        assert env["PIP_CONFIG_FILE"] == os.devnull and "PIP_INDEX_URL" not in env
        assert env["PIP_CACHE_DIR"] == str(base_packages.cache_dir(installer.root))
        if command[3] == "install":
            assert "--no-index" in command and command[command.index("--find-links") + 1] == str(installer.store)
    first_backend = installer.calls[0][0]
    assert Path(first_backend[first_backend.index("-r") + 1]).name == "build-backends.txt"
    full = installer.calls[3][0]
    assert full[full.index("-r") + 1] == str(base_packages.lock_path(bootstrap.REQUIREMENTS_FILE))
    assert installer.store.is_dir() and base_packages.cache_dir(installer.root).parent == installer.store.parent


def test_a_complete_store_reinstalls_without_any_download(installer):
    installer.store.mkdir(parents=True)
    for _version, artifact in installer.entries.values():
        (installer.store / artifact).write_bytes(b"kept")
    assert bootstrap.install_base_packages(installer.python, lambda line: None) is True
    assert [verb for verb, _ in _verbs(installer.calls)] == ["install", "install"]


def test_a_kept_file_that_fails_its_check_is_fetched_once_more(installer):
    installer.store.mkdir(parents=True)
    for _version, artifact in installer.entries.values():
        (installer.store / artifact).write_bytes(b"kept")
    installer.outcomes.extend([0, 1, 0, 0])  # backends ok; the full install refuses a damaged file; fetch; install
    assert bootstrap.install_base_packages(installer.python, lambda line: None) is True
    assert [verb for verb, _ in _verbs(installer.calls)] == ["install", "install", "download", "install"]


def test_a_failed_fetch_leaves_the_environment_alone(installer):
    installer.outcomes.extend([1])
    assert bootstrap.install_base_packages(installer.python, lambda line: None) is False
    assert [verb for verb, _ in _verbs(installer.calls)] == ["download"], "nothing is installed after a failed fetch"


def test_an_interpreter_the_lock_does_not_describe_installs_requirements_txt_under_the_same_policy(installer,
                                                                                                    monkeypatch):
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 13))
    assert bootstrap.install_base_packages(installer.python, lambda line: None) is True
    [(command, env)] = installer.calls
    assert command[3] == "install" and command[command.index("-r") + 1] == str(bootstrap.REQUIREMENTS_FILE)
    assert env["PIP_CONFIG_FILE"] == os.devnull and env["PIP_CACHE_DIR"] == str(base_packages.cache_dir(installer.root))


def test_setup_and_every_repair_route_use_the_one_installer():
    for function in (bootstrap.pip_install_requirements, bootstrap.ensure_kokoro_installed,
                     bootstrap.ensure_chatterbox_installed):
        assert "install_base_packages(" in inspect.getsource(function), function.__name__


def test_a_force_reinstall_reinstalls_the_whole_lock_from_the_store(installer):
    """A package that does not import may be broken below it: a dependency whose files are gone while its metadata
    remains is "already satisfied" to pip (found by the offline-repair qualification, 2026-10-31). So the forced
    reinstall covers every locked package, from the verified store, dependencies checked."""
    assert bootstrap._force_reinstall(installer.python, "tqdm", lambda line: None) is True
    (download, _env), (install, env) = installer.calls
    assert download[3] == "download", "the store was empty, so it is filled first"
    assert install[3] == "install" and {"--force-reinstall", "--no-index", "--require-hashes"} <= set(install)
    assert "--no-deps" not in install
    assert install[install.index("-r") + 1] == str(base_packages.lock_path(bootstrap.REQUIREMENTS_FILE))
    assert env["PIP_CONFIG_FILE"] == os.devnull


def test_a_force_reinstall_from_a_complete_store_needs_no_network(installer):
    installer.store.mkdir(parents=True)
    for _version, artifact in installer.entries.values():
        (installer.store / artifact).write_bytes(b"kept")
    assert bootstrap._force_reinstall(installer.python, "tqdm", lambda line: None) is True
    assert [command[3] for command, _env in installer.calls] == ["install"]


def test_a_dependency_damaged_below_its_metadata_is_repaired_by_one_whole_lock_reinstall(installer, monkeypatch):
    """The real case: numpy's files deleted, its .dist-info left. chatterbox (and nltk) fail to import; one forced
    reinstall of the lock fixes both, and it is not repeated for the second module."""
    installer.store.mkdir(parents=True)
    for _version, artifact in installer.entries.values():
        (installer.store / artifact).write_bytes(b"kept")
    monkeypatch.setattr(bootstrap, "REQUIRED_IMPORTS", ["edge_tts", "chatterbox", "nltk"])
    monkeypatch.setattr(bootstrap, "venv_python", lambda windowed=False: installer.python)
    repaired = {"done": False}

    def probe(py, module, timeout=30):
        return module == "edge_tts" or repaired["done"]

    def fake_pip(command, env, log):
        installer.calls.append((list(command), dict(env)))
        repaired["done"] = "--force-reinstall" in command
        return 0

    monkeypatch.setattr(bootstrap, "_probe_import", probe)
    monkeypatch.setattr(bootstrap, "_pip", fake_pip)

    class Log:
        lines: list = []

        def line(self, text):
            self.lines.append(text)

    assert bootstrap.validate_installed_packages(Log()) is True
    forced = [command for command, _env in installer.calls if "--force-reinstall" in command]
    assert len(forced) == 1, "one whole-lock reinstall, not one per failing module"


def test_the_store_keeps_only_releases_the_lock_names(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    for name in ("tqdm-4.67.3-py3-none-any.whl", "tqdm-4.67.2-py3-none-any.whl", "docopt-0.6.2.tar.gz",
                 "docopt-0.6.1.tar.gz", "notes.txt"):
        (store / name).write_bytes(b"x")
    lock = base_packages.parse_lock(f"# {base_packages.ARTIFACT_PREFIX} tqdm-4.67.3-py3-none-any.whl\n"
                                    f"tqdm==4.67.3 --hash=sha256:{'a' * 64}\n"
                                    f"# {base_packages.ARTIFACT_PREFIX} docopt-0.6.2.tar.gz\n"
                                    f"docopt==0.6.2 --hash=sha256:{'b' * 64}\n")
    assert sorted(base_packages.prune_store(lock, store)) == ["docopt-0.6.1.tar.gz", "tqdm-4.67.2-py3-none-any.whl"]
    assert sorted(os.listdir(store)) == ["docopt-0.6.2.tar.gz", "notes.txt", "tqdm-4.67.3-py3-none-any.whl"]


# --------------------------------------------------------------------------- #
# Drift and the gate
# --------------------------------------------------------------------------- #
def test_the_requirements_fingerprint_covers_the_lock(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("tqdm==4.67.3\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "REQUIREMENTS_FILE", requirements)
    plain = bootstrap.requirements_fingerprint()
    assert plain == hashlib.sha256(requirements.read_bytes()).hexdigest(), "no lock: the old value exactly"
    lock = base_packages.lock_path(requirements)
    lock.write_text(f"tqdm==4.67.3 --hash=sha256:{'a' * 64}\n", encoding="utf-8")
    first = bootstrap.requirements_fingerprint()
    lock.write_text(f"tqdm==4.67.3 --hash=sha256:{'b' * 64}\n", encoding="utf-8")
    assert len({plain, first, bootstrap.requirements_fingerprint()}) == 3


@pytest.mark.parametrize("damage, expected", [
    (lambda text: text.replace("filelock==4.2.5", "filelock==4.2.4"), "is not that release"),
    (lambda text: text.replace("torch==2.6.0", "torch==2.7.0"), "requirements.txt pins 2.6.0"),
    (lambda text: re.sub(r"(?m)^# artifact: tqdm.*\ntqdm==.*\n", "", text), "tqdm"),
    (lambda text: text.replace("requirements.txt sha256: ", "requirements.txt sha256: 0"), "different requirements"),
    (lambda text: text + "colorama>=0.4\n", "not 'name==version"),
    (lambda text: text.replace("--hash=sha256:", "--hash=md5:", 1), "not 'name==version"),
])
def test_the_deps_gate_refuses_a_stale_incomplete_or_loosened_lock(tmp_path, monkeypatch, damage, expected):
    sys.path.insert(0, str(SCRIPTS))
    import verify

    requirements = tmp_path / "requirements.txt"
    shutil.copyfile(REQUIREMENTS, requirements)
    lock_text = damage(LOCK.read_text(encoding="utf-8"))
    base_packages.lock_path(requirements).write_text(lock_text, encoding="utf-8")
    monkeypatch.setattr(verify, "REQUIREMENTS", requirements)
    name, ok, detail = verify.check_requirements()
    assert name == "deps" and ok is False and expected in detail, detail


def test_the_deps_gate_passes_on_the_committed_files_and_requires_the_lock(tmp_path, monkeypatch):
    sys.path.insert(0, str(SCRIPTS))
    import verify

    name, ok, detail = verify.check_requirements()
    assert ok is True and "locks 170 packages" in detail, detail
    requirements = tmp_path / "requirements.txt"
    shutil.copyfile(REQUIREMENTS, requirements)
    monkeypatch.setattr(verify, "REQUIREMENTS", requirements)
    name, ok, detail = verify.check_requirements()
    assert ok is False and base_packages.LOCK_NAME in detail
