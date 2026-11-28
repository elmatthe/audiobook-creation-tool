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

**v0.8.2 Phase 4.** uv is now the base environment's only installer: ``pyproject.toml`` + ``uv.lock`` (a parity
translation of these pins), synced by ``shared/uv_runner.py``. ``requirements.txt`` and the two hash locks stay as a
frozen parity reference -- this module's lock rules, the deps gate and the parity tests at the end hold them to
``uv.lock`` -- until Phase 6 retires them. The tests of the retired pip installer (``install_base_packages``,
``_force_reinstall`` and the store routes) were retired with it; the uv route is held by test_uv_provisioning.py.
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

import gate_locator
from shared import base_packages, bootstrap
from source_probe import application_python_files

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
REQUIREMENTS = SCRIPTS / "requirements.txt"
#: This module's subject is the Windows lock (v0.8.x P1A: one lock per platform; the macOS lock is held by
#: test_macos_foundation.py).
LOCK = base_packages.lock_path(REQUIREMENTS, platform="win32", machine="AMD64")
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
                                       base_packages.requirements_digest(REQUIREMENTS.read_bytes())) == []


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
    # The lock of the machine running the suite: the environment under test is that platform's locked set.
    own = base_packages.parse_lock(base_packages.lock_path(REQUIREMENTS).read_text(encoding="utf-8"))
    for entry in own.entries:
        try:
            installed = metadata.version(entry.name)
        except metadata.PackageNotFoundError:
            installed = None
        if installed != entry.version:
            wrong.append(f"{entry.name}: locked {entry.version}, installed {installed}")
    assert not wrong, ("this environment is not the locked set; reconcile it (start the app, or run "
                       "scripts/shared/bootstrap.py --profile dev): " + "; ".join(wrong))


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


#: The one literal pip command outside the three policy modules, by module and enclosing function: the long-path check's probe
#: (v0.8.0), which installs a wheel it has just written into its own folder. Approved for that one use, pinned whole below.
LONG_PATH_PROBE_PIP = ("shared/long_paths.py", "_pip_command")


def _literal_pip_sites(tree: ast.AST) -> list[str]:
    """The enclosing function (``<module>`` at the top level) of every list or tuple literal holding ``"-m", "pip"``."""
    sites: list[str] = []

    def visit(node: ast.AST, where: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            where = node.name
        if isinstance(node, (ast.List, ast.Tuple)):
            strings = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if any(a == "-m" and b == "pip" for a, b in zip(strings, strings[1:])):
                sites.append(where)
        for child in ast.iter_child_nodes(node):
            visit(child, where)

    visit(tree, "<module>")
    return sites


def test_pip_is_never_upgraded_and_no_shipped_module_builds_an_unmanaged_pip_command():
    source = (SCRIPTS / "shared" / "bootstrap.py").read_text(encoding="utf-8")
    assert '"--upgrade", "pip"' not in source and "install --upgrade pip" not in source
    # Every literal pip invocation in shipped code lives where its policy is pinned and tested: the three policy modules,
    # and one approved call site elsewhere (the long-path probe), held by function so a second literal beside it fails too.
    allowed = {"shared/base_packages.py", "shared/spacy_store.py", "shared/bootstrap.py"}
    elsewhere = []
    for path in application_python_files():  # the one definition of the shipped source
        relative = path.relative_to(SCRIPTS).as_posix()
        if relative not in allowed:
            elsewhere += [(relative, where) for where in _literal_pip_sites(ast.parse(path.read_text(encoding="utf-8")))]
    assert elsewhere == [LONG_PATH_PROBE_PIP], elsewhere
    # v0.8.2 Phase 4: bootstrap builds no pip command for the base environment any more (uv is its only installer).
    assert _literal_pip_sites(ast.parse(source)) == []
    for retired in ("venv_pip", "install_base_packages", "_force_reinstall", "pip_install_requirements"):
        assert not hasattr(bootstrap, retired), retired


def test_the_other_pip_users_keep_their_own_contained_policy():
    from shared import spacy_store
    from tts import qwen3_packages, qwen3_setup

    spacy = spacy_store.offline_install_command(Path("python.exe"), Path("req.txt"))
    assert {"--isolated", "--no-cache-dir", "--no-index", "--require-hashes"} <= set(spacy)
    # v0.8.2 Phase 5A: the Qwen3 engine is installed by uv from its lock; pip is left only behind the sealed-package
    # seam (test-only, removed in Phase 6), which installs only its own sealed wheels (pip_command -> _pip_command).
    assert "qwen3_packages.pip_command(" in inspect.getsource(qwen3_setup._install_sealed_environment)
    assert "pip_command" not in inspect.getsource(qwen3_setup._install_uv_environment)
    source = inspect.getsource(qwen3_packages._pip_command)
    for flag in ("'--isolated'", "'--no-cache-dir'", "'--no-index'", "'--require-hashes'"):
        assert flag in source, flag


def test_the_long_path_probe_installs_only_its_own_wheel_offline_into_its_own_folder():
    """The approved exception above (v0.8.0): the long-path check proves a package installs as deep as the installation goes
    by installing, with this interpreter's own pip, a one-module wheel it has just written, into its own probe folder (made
    and removed by ``verify_runtime``; pinned in test_long_paths). Pinned whole, so another flag, index, upgrade, target,
    environment or caller is a new decision rather than this exception."""
    import source_probe

    relative = "shared/long_paths.py"
    # The interpreter in isolated mode (-I: no PYTHON* variables, no user site), its own pip or the bundled copy, nothing more.
    builder = source_probe.function(relative, "_pip_command")
    lists = sorted((node for node in ast.walk(builder) if isinstance(node, ast.List)), key=lambda node: node.lineno)
    assert [ast.unparse(node) for node in lists] == [
        "[sys.executable, '-I', '-m', 'pip']", "[sys.executable, '-I', str(bundled[-1] / 'pip')]"]
    # The probe is the builder's only caller, here or anywhere in shipped code.
    probe = source_probe.function(relative, "_probe")

    def uses(tree: ast.AST) -> list:
        return [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == "_pip_command"]

    assert len(uses(source_probe.module(relative))) == len(uses(probe)) == 1
    for path in application_python_files():
        if path.relative_to(SCRIPTS).as_posix() == relative:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            assert not (isinstance(node, ast.ImportFrom) and (node.module or "").endswith("long_paths")
                        and {alias.name for alias in node.names} & {"_pip_command", "*"}), path
            assert not (isinstance(node, ast.Attribute) and node.attr == "_pip_command"
                        and ast.unparse(node.value).endswith("long_paths")), path
    # Exactly this install: offline (--no-index, --no-deps, a local wheel file), no PIP_* variable or user configuration
    # (--isolated), no cache, nothing compiled, no upgrade, into the probe's own folder and nowhere else (--target).
    (command,) = [node for node in ast.walk(probe) if isinstance(node, ast.BinOp) and ast.unparse(node.left) == "_pip_command()"]
    assert isinstance(command.op, ast.Add) and isinstance(command.right, ast.List)
    assert [item.value if isinstance(item, ast.Constant) else ast.unparse(item) for item in command.right.elts] == [
        "install", "--isolated", "--no-index", "--no-deps", "--no-compile", "--no-cache-dir", "--disable-pip-version-check",
        "--quiet", "--target", "into", "wheel"]
    assigned = {ast.unparse(node.targets[0]): ast.unparse(node.value) for node in ast.walk(probe)
                if isinstance(node, ast.Assign) and len(node.targets) == 1}
    assert assigned["into"] == "os.path.join(base, 't')"
    assert assigned["wheel"] == "os.path.join(base, 'actlongpathprobe-0-py3-none-any.whl')"
    assert "_wheel(wheel, os.path.relpath(installed, into).replace(os.sep, '/'))" in ast.unparse(probe), "the wheel is its own"
    # Run once, as written: the command alone, bounded, no shell and no environment handed in.
    (run,) = [node for node in ast.walk(probe) if isinstance(node, ast.Call) and node.args and node.args[0] is command]
    assert ast.unparse(run.func) == "subprocess.run" and len(run.args) == 1
    keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in run.keywords}
    assert sorted(keywords) == ["capture_output", "creationflags", "text", "timeout"] and keywords["timeout"] == "180", keywords


def _run_pip(python, *args, env):
    # v0.8.2 Phase 4: a uv-built environment has no pip, so real pip runs in the module's disposable venv (ensurepip's).
    return subprocess.run([str(python), "-m", "pip", *args], capture_output=True, text=True, env=env, timeout=180)


def test_real_pip_uses_the_named_cache_and_no_configuration_whatever_the_profile_says(tmp_path, disposable_venv):
    """pip resolves its default cache through the Windows known-folder API, so a redirected LOCALAPPDATA does not
    move it (measured 2026-10-31). The explicit policy does, and a hostile config file is not read at all."""
    hostile = tmp_path / "hostile.ini"
    hostile.write_text("[global]\ncache-dir = C:\\hostile-cache\nindex-url = https://egress.invalid/simple\n",
                       encoding="utf-8")
    cache = tmp_path / "app" / "files" / "runtime-data" / "pip-cache"
    env = base_packages.pip_environment({**os.environ, "PIP_CONFIG_FILE": str(hostile),
                                         "LOCALAPPDATA": str(tmp_path / "fake-profile")}, cache)
    assert _run_pip(disposable_venv, "cache", "dir", env=env).stdout.strip().lower() == str(cache).lower()
    listed = _run_pip(disposable_venv, "config", "list", env=env)
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
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_the_store_keeps_only_the_locks_exact_verified_artifacts(tmp_path):
    """v0.7.0 acceptance D2: eligibility is the lock's exact file name AND its exact SHA-256. An older release is
    deleted as before; anything else that is not a verified locked artifact leaves the store for the quarantine."""
    store, quarantine = tmp_path / "store", tmp_path / "quarantine"
    store.mkdir()
    files = {"tqdm-4.67.3-py3-none-any.whl": b"tqdm", "tqdm-4.67.2-py3-none-any.whl": b"old",
             "docopt-0.6.2.tar.gz": b"docopt-damaged", "docopt-0.6.1.tar.gz": b"old",
             "tqdm-4.67.3-cp312-cp312-win_amd64.whl": b"stray", "notes.txt": b"x"}
    for name, data in files.items():
        (store / name).write_bytes(data)
    (store / "docopt-0.6.2-py3-none-any.whl").mkdir()  # a folder named like a locked artifact
    lock = base_packages.parse_lock(f"# {base_packages.ARTIFACT_PREFIX} tqdm-4.67.3-py3-none-any.whl\n"
                                    f"tqdm==4.67.3 --hash=sha256:{_sha(b'tqdm')}\n"
                                    f"# {base_packages.ARTIFACT_PREFIX} docopt-0.6.2.tar.gz\n"
                                    f"docopt==0.6.2 --hash=sha256:{_sha(b'docopt')}\n")
    swept = base_packages.sweep_store(lock, store, quarantine)
    assert sorted(swept.removed) == ["docopt-0.6.1.tar.gz", "tqdm-4.67.2-py3-none-any.whl"]
    assert dict(swept.quarantined) == {
        "docopt-0.6.2.tar.gz": "its contents do not match the SHA-256 the lock names",
        "docopt-0.6.2-py3-none-any.whl": "it claims a locked release but is not the locked file",
        "notes.txt": "the lock does not name it",
        "tqdm-4.67.3-cp312-cp312-win_amd64.whl": "it claims a locked release but is not the locked file"}
    assert swept.problems == ()
    assert os.listdir(store) == ["tqdm-4.67.3-py3-none-any.whl"], "only the exact, verified artifact stays"
    assert sorted(os.listdir(quarantine)) == sorted(dict(swept.quarantined))
    assert (quarantine / "tqdm-4.67.3-cp312-cp312-win_amd64.whl").read_bytes() == b"stray", "moved, not rewritten"
    assert base_packages.missing_artifacts(lock, store) == [lock.by_key()["docopt"]], "the damaged one is refetched"


def test_a_second_sweep_never_overwrites_an_earlier_quarantined_file(tmp_path):
    store, quarantine = tmp_path / "store", tmp_path / "quarantine"
    store.mkdir()
    lock = base_packages.parse_lock(f"# {base_packages.ARTIFACT_PREFIX} tqdm-4.67.3-py3-none-any.whl\n"
                                    f"tqdm==4.67.3 --hash=sha256:{_sha(b'tqdm')}\n")
    for data in (b"first", b"second"):
        (store / "tqdm-4.67.3-py3-none-any.whl").write_bytes(data)
        base_packages.sweep_store(lock, store, quarantine)
    assert {p.name: p.read_bytes() for p in quarantine.iterdir()} == {
        "tqdm-4.67.3-py3-none-any.whl": b"first", "tqdm-4.67.3-py3-none-any.whl.1": b"second"}


def test_a_file_that_cannot_be_moved_out_is_a_problem_not_a_silent_keep(tmp_path, monkeypatch):
    store, quarantine = tmp_path / "store", tmp_path / "quarantine"
    store.mkdir()
    (store / "tqdm-4.67.3-cp312-cp312-win_amd64.whl").write_bytes(b"stray")
    lock = base_packages.parse_lock(f"# {base_packages.ARTIFACT_PREFIX} tqdm-4.67.3-py3-none-any.whl\n"
                                    f"tqdm==4.67.3 --hash=sha256:{_sha(b'tqdm')}\n")

    def refuse(source, destination):
        raise PermissionError(13, "in use")

    monkeypatch.setattr(base_packages.os, "replace", refuse)
    swept = base_packages.sweep_store(lock, store, quarantine)
    assert swept.quarantined == () and len(swept.problems) == 1 and "in use" in swept.problems[0]


def test_real_pip_prefers_a_stray_same_release_file_and_the_sweep_lets_the_install_succeed(disposable_venv,
                                                                                           tmp_path):
    """The accepted D2 reproduction, offline and in miniature: other bytes named as a more specific build of a locked
    release sit beside the locked artifact. pip picks the stray and refuses its hash -- every install fails, forever.
    After the sweep the same offline install succeeds from the locked artifact, and the stray is kept aside."""
    store, quarantine = tmp_path / "store", tmp_path / "quarantine"
    store.mkdir()
    s_file, s_hash = _wheel(store, "act-lock-s", "1.0")
    tag = f"py{sys.version_info[0]}{sys.version_info[1]}-none-any"  # preferred over py3-none-any by this interpreter
    stray = store / f"act_lock_s-1.0-{tag}.whl"
    _wheel(tmp_path, "act-lock-docopt", "0.6.2")
    shutil.copyfile(tmp_path / "act_lock_docopt-0.6.2-py3-none-any.whl", stray)  # a different, valid archive
    lock_text = f"# {base_packages.ARTIFACT_PREFIX} {s_file}\nact-lock-s==1.0 --hash=sha256:{s_hash}\n"

    before = _offline_install(disposable_venv, store, lock_text, tmp_path, policy_cache=tmp_path / "cache")
    assert before.returncode != 0 and "do not match the hashes" in (before.stdout + before.stderr).lower()
    assert stray.name in (before.stdout + before.stderr), "pip chose the stray file"

    swept = base_packages.sweep_store(base_packages.parse_lock(lock_text), store, quarantine)
    assert [name for name, _why in swept.quarantined] == [stray.name] and swept.problems == ()
    after = _offline_install(disposable_venv, store, lock_text, tmp_path, policy_cache=tmp_path / "cache")
    assert after.returncode == 0, after.stdout + after.stderr
    shown = subprocess.run([str(disposable_venv), "-c", "import act_lock_s; print(act_lock_s.VERSION)"],
                           capture_output=True, text=True)
    assert shown.stdout.strip() == "1.0"
    assert (quarantine / stray.name).is_file() and not stray.exists()


# --------------------------------------------------------------------------- #
# Drift and the gate
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("damage, expected", [
    (lambda text: text.replace("filelock==4.2.5", "filelock==4.2.4"), "is not that release"),
    (lambda text: text.replace("torch==2.6.0", "torch==2.7.0"), "requirements.txt pins 2.6.0"),
    (lambda text: re.sub(r"(?m)^# artifact: tqdm.*\ntqdm==.*\n", "", text), "tqdm"),
    (lambda text: text.replace("requirements.txt sha256: ", "requirements.txt sha256: 0"), "different requirements"),
    (lambda text: text + "colorama>=0.4\n", "not 'name==version"),
    (lambda text: text.replace("--hash=sha256:", "--hash=md5:", 1), "not 'name==version"),
])
def test_the_deps_gate_refuses_a_stale_incomplete_or_loosened_lock(tmp_path, monkeypatch, damage, expected):
    verify = gate_locator.load_gate("act_verify_base_packages")

    requirements = tmp_path / "requirements.txt"
    shutil.copyfile(REQUIREMENTS, requirements)
    lock_text = damage(LOCK.read_text(encoding="utf-8"))
    base_packages.lock_path(requirements).write_text(lock_text, encoding="utf-8")
    monkeypatch.setattr(verify, "REQUIREMENTS", requirements)
    name, ok, detail = verify.check_requirements()
    assert name == "deps" and ok is False and expected in detail, detail


def test_the_deps_gate_passes_on_the_committed_files_and_requires_the_lock(tmp_path, monkeypatch):
    verify = gate_locator.load_gate("act_verify_base_packages")

    name, ok, detail = verify.check_requirements()
    assert ok is True and "locks 170 packages" in detail, detail
    requirements = tmp_path / "requirements.txt"
    shutil.copyfile(REQUIREMENTS, requirements)
    monkeypatch.setattr(verify, "REQUIREMENTS", requirements)
    name, ok, detail = verify.check_requirements()
    assert ok is False and base_packages.LOCK_NAME in detail



# --------------------------------------------------------------------------- #
# v0.8.2 Phase 4: uv.lock is a parity translation of the frozen hash locks
# --------------------------------------------------------------------------- #
def _uv_locked() -> dict[str, set]:
    import tomllib

    found: dict[str, set] = {}
    for package in tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]:
        if package.get("source", {}).get("virtual") == ".":
            continue  # the project itself
        found.setdefault(base_packages.canonical_name(package["name"]), set()).add(package["version"])
    return found


def test_uv_lock_carries_every_hash_locked_release_and_nothing_else():
    """Until Phase 6 retires them, the Windows and macOS hash locks and uv.lock name exactly the same releases: uv
    installs what v0.8.1 qualified, no more and no fewer (Phase 3A measured 170 packages, identical as data)."""
    uv = _uv_locked()
    hashed: dict[str, set] = {}
    for platform, machine in (("win32", "AMD64"), ("darwin", "arm64")):
        lock = base_packages.parse_lock(
            base_packages.lock_path(REQUIREMENTS, platform=platform, machine=machine).read_text(encoding="utf-8"))
        for entry in lock.entries:
            assert entry.version in uv.get(entry.key, set()), f"{platform}: {entry.key}=={entry.version} not in uv.lock"
            hashed.setdefault(entry.key, set()).add(entry.version)
    assert uv == hashed, {name: (uv.get(name), hashed.get(name)) for name in set(uv) | set(hashed)
                          if uv.get(name) != hashed.get(name)}
    assert len(uv) == 170


def test_the_base_project_pins_exactly_requirements_txt_with_pytest_in_the_dev_group():
    import tomllib

    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {line.strip() for line in project["project"]["dependencies"]}
    dev = set(project["dependency-groups"]["dev"])
    required = {line.split("#", 1)[0].strip() for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()}
    required.discard("")

    def plain(entries):
        return {" ".join(entry.replace(" ;", ";").replace("; ", ";").split()) for entry in entries}

    assert plain(declared | dev) == plain(required), plain(declared | dev) ^ plain(required)
    assert dev == {"pytest==9.1.1"}, "the developer profile adds pytest only"
    assert not any(entry.startswith("pytest") for entry in declared), "a user install never carries pytest"
