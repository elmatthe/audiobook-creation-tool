"""uv_runner.py — the one way ACT runs uv (v0.8.2 Phase 4). Standard library only.

Every uv invocation of the application, its setup and its developers goes through this module, so each one names
exactly which uv, which project, which environment, which Python, which cache and which temporary folder it uses, and
none can be steered by the computer's own configuration:

* **Pins.** uv 0.13.10 and CPython 3.12.15 from python-build-standalone 20261009, per platform, by SHA-256 (owner
  decisions recorded in Phase 3B). The interpreter is installed by ``uv python install`` from ACT's own verified archive
  (``python-downloads.json`` beside this file is ACT's download metadata, so uv can never choose another build), read
  from a local ``file://`` mirror, so installing or restoring it needs no network.
* **Isolation.** :func:`environment` drops every inherited ``UV_*``, ``PIP_*``, ``XDG_*``, ``CONDA_*``, ``PYTHON*``,
  ``VIRTUAL_ENV`` and ``SSL_CERT_*`` setting and sets the contained cache, Python, bin, tool, credential and temporary
  folders, no user configuration, no Windows registry and no automatic Python download (Phase 3A section 2).
* **Targets.** :func:`check_target` accepts only this copy's own ``.venv`` (and, from Phase 5, ``.venv-engines/<name>``),
  reached through no link, with the project's ``pyproject.toml`` and ``uv.lock`` beside it. Every call passes
  ``--project`` and ``--python 3.12.15``; uv never picks the parent project or another environment.
* **Scratch.** :class:`Operation` gives each uv call its own temporary folder (``TEMP``/``TMPDIR`` and the Python
  download cache: a refused archive stays there and would block every later install, Phase 3A) and removes exactly that
  folder afterwards.

Link mode (approved A4/D-8): Windows ``copy``, macOS ``clone``, never ``hardlink``. Bytecode is compiled at install.

Developers use the same rules from a terminal::

    python scripts/shared/uv_runner.py lock                 # re-lock after editing pyproject.toml
    python scripts/shared/uv_runner.py check-lock           # does uv.lock still match pyproject.toml?
    python scripts/shared/uv_runner.py uv -- tree           # any other uv command, contained

The developer profile (pytest) is chosen with ``bootstrap.py --profile dev``, which records the choice so every later
launch keeps it, syncs and writes the receipt. Setup itself never runs ``lock``: launches and repairs use
``sync --locked``.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Sequence

# --------------------------------------------------------------------------------------------------------------------
#  Pins (keep in step with bootstrap_host.ps1, bootstrap_host_fallback.cmd and bootstrap_host_macos.sh; a test pins it)
# --------------------------------------------------------------------------------------------------------------------
UV_VERSION = "0.13.10"
PYTHON_VERSION = "3.12.15"
PYTHON_BUILD = "20261009"
PROFILE_USER = "user"
PROFILE_DEV = "dev"
PROFILES = (PROFILE_USER, PROFILE_DEV)


@dataclass(frozen=True)
class PlatformPins:
    """Everything platform-specific about the pinned uv and the pinned interpreter."""

    uv_archive: str
    uv_size: int
    uv_sha256: str
    uv_exe: str               # the program's name inside the contained uv folder
    uv_exe_sha256: str        # the program's own digest (identity of an installed uv)
    python_key: str           # uv's name for the exact install (its folder name)
    python_minor_key: str     # the minor-version link uv always creates beside it
    python_archive: str
    python_size: int
    python_sha256: str
    python_sys_version: str   # ``sys.version`` of exactly this build
    link_mode: str

    @property
    def uv_url(self) -> str:
        return f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{self.uv_archive}"

    @property
    def python_url(self) -> str:
        return ("https://github.com/astral-sh/python-build-standalone/releases/download/"
                f"{PYTHON_BUILD}/{self.python_archive.replace('+', '%2B')}")


WINDOWS = PlatformPins(
    uv_archive="uv-x86_64-pc-windows-msvc.zip",
    uv_size=15_641_577,
    uv_sha256="297b3881fe1adfb922becc2c1613202abb41dc83ea5ff43d472aa087ca1f8683",
    uv_exe="uv.exe",
    uv_exe_sha256="9f9f3631112f847c81b2063637ce01f4dd8d65e8ac2a8f4bb1c121f7effa5c76",
    python_key="cpython-3.12.15-windows-x86_64-none",
    python_minor_key="cpython-3.12-windows-x86_64-none",
    python_archive="cpython-3.12.15+20261009-x86_64-pc-windows-msvc-install_only.tar.gz",
    python_size=46_352_482,
    python_sha256="194c8f0d9e0de6f1c4576e5dfa67819a48c764be87608b74b8ad43387a57b93b",
    python_sys_version="3.12.15 (main, Oct  9 2026, 15:21:55) [MSC v.1944 64 bit (AMD64)]",
    link_mode="copy",
)
MACOS = PlatformPins(
    uv_archive="uv-aarch64-apple-darwin.tar.gz",
    uv_size=14_700_626,
    uv_sha256="e419bf07533bdbf48795fc793601c834dd79db57a8c49ce8e25cfe3a8639958d",
    uv_exe="uv",
    uv_exe_sha256="4ff271e49765b1d8ed72cfbf720401941efccac6b2997ce87bb05ee790312ab3",
    python_key="cpython-3.12.15-macos-aarch64-none",
    python_minor_key="cpython-3.12-macos-aarch64-none",
    python_archive="cpython-3.12.15+20261009-aarch64-apple-darwin-install_only.tar.gz",
    python_size=25_165_569,
    python_sha256="83dcb04777c798bd95f3687acf9ae84b09860272ee6bdfb05be8bcf9447f75b8",
    python_sys_version="3.12.15 (main, Oct  9 2026, 15:10:57) [Clang 22.1.3 ]",
    link_mode="clone",
)


def pins(platform: Optional[str] = None) -> PlatformPins:
    """The pins for *platform* (default: this one). Windows and Apple Silicon macOS are the supported platforms; any
    other POSIX system is given the macOS names so paths stay computable, and its install simply fails its checks."""
    platform = sys.platform if platform is None else platform
    return WINDOWS if platform == "win32" else MACOS


# --------------------------------------------------------------------------------------------------------------------
#  Paths, all inside the copy of the app
# --------------------------------------------------------------------------------------------------------------------
BASE_ENV_NAME = ".venv"
ENGINE_ENVS_NAME = ".venv-engines"
_ENGINE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


def runtime_dir(root) -> Path:
    return Path(root) / "files" / "runtime-data"


def uv_home(root) -> Path:
    """``files/runtime-data/uv``: the pinned uv, the managed Python, ACT's archive mirror and per-operation scratch."""
    return runtime_dir(root) / "uv"


def uv_exe(root, platform: Optional[str] = None) -> Path:
    return uv_home(root) / pins(platform).uv_exe


def python_install_dir(root) -> Path:
    return uv_home(root) / "python"


def managed_python_home(root, platform: Optional[str] = None) -> Path:
    """The exact versioned install folder (never the minor-version link uv puts beside it)."""
    return python_install_dir(root) / pins(platform).python_key


def managed_python(root, platform: Optional[str] = None) -> Path:
    platform = sys.platform if platform is None else platform
    home = managed_python_home(root, platform)
    return home / "python.exe" if platform == "win32" else home / "bin" / "python3.12"


def managed_venv_home(root, platform: Optional[str] = None) -> Path:
    """What ``pyvenv.cfg`` ``home`` must say for an environment built on the managed Python (Windows: the install
    folder; POSIX: its ``bin``)."""
    platform = sys.platform if platform is None else platform
    home = managed_python_home(root, platform)
    return home if platform == "win32" else home / "bin"


def mirror_dir(root) -> Path:
    """ACT's own verified copy of the interpreter archive, laid out as uv's ``--mirror`` expects:
    ``<mirror>/<build>/<archive name>``."""
    return uv_home(root) / "mirror"


def mirror_archive(root, platform: Optional[str] = None) -> Path:
    return mirror_dir(root) / PYTHON_BUILD / pins(platform).python_archive


def cache_dir(root) -> Path:
    """The repair cache (approved D-8). A short name on purpose: its deepest path sets the Windows path budget."""
    return runtime_dir(root) / "uvc"


def scratch_root(root) -> Path:
    return uv_home(root) / "t"


def confined_dir(root) -> Path:
    """Folders uv must never use but would otherwise default to the user's profile for (bin, tools, credentials)."""
    return uv_home(root) / "home"


def downloads_json() -> Path:
    return Path(__file__).resolve().parent / "python-downloads.json"


def project_dir(root) -> Path:
    return Path(root)


def base_env(root) -> Path:
    return Path(root) / BASE_ENV_NAME


def engine_env(root, name: str) -> Path:
    if not _ENGINE_NAME.match(name or ""):
        raise ValueError(f"not an engine name: {name!r}")
    return Path(root) / ENGINE_ENVS_NAME / name


def venv_python(env, platform: Optional[str] = None) -> Path:
    platform = sys.platform if platform is None else platform
    return Path(env) / ("Scripts/python.exe" if platform == "win32" else "bin/python")


def mirror_uri(root) -> str:
    return mirror_dir(root).resolve().as_uri()


# --------------------------------------------------------------------------------------------------------------------
#  Validation
# --------------------------------------------------------------------------------------------------------------------
class TargetRefused(ValueError):
    """A uv call was asked to use a project or environment that is not this copy's own."""


def _same(first, second) -> bool:
    from shared import venv_layout  # local import: keeps this module importable from a bare scripts/shared path

    return venv_layout.same_path(first, second)


def _unsafe(root, path) -> Optional[Path]:
    from shared import venv_layout

    return venv_layout.unsafe_component(root, path)


def check_target(root, env_dir, *, project=None) -> None:
    """Raise :class:`TargetRefused` unless *env_dir* is this copy's own base or engine environment and *project* holds
    a real ``pyproject.toml`` and ``uv.lock``. Nothing on the way may be a link or junction (the copy's own folder
    itself may be reached through one, as everywhere in ACT)."""
    root = Path(os.path.abspath(str(root)))
    env_dir = Path(os.path.abspath(str(env_dir)))
    project = root if project is None else Path(os.path.abspath(str(project)))
    allowed = _same(env_dir, base_env(root)) or (
        _same(env_dir.parent, root / ENGINE_ENVS_NAME) and bool(_ENGINE_NAME.match(env_dir.name)))
    if not allowed:
        raise TargetRefused(f"{env_dir} is not an environment of the app at {root}")
    if _unsafe(root, env_dir) is not None:
        raise TargetRefused(f"{env_dir} is reached through a link")
    for name in ("pyproject.toml", "uv.lock"):
        path = project / name
        if _unsafe(root, path) is not None or not path.is_file():
            raise TargetRefused(f"{path} is missing or reached through a link")


def read_pyvenv_home(env_dir) -> Optional[str]:
    try:
        text = (Path(env_dir) / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() == "home":
            return value.strip() or None
    return None


def built_by_uv(env_dir) -> bool:
    """True when ``pyvenv.cfg`` carries uv's own ``uv = <version>`` line (pip/stdlib ``venv`` never writes it)."""
    try:
        text = (Path(env_dir) / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(line.partition("=")[0].strip().lower() == "uv" for line in text.splitlines())


def home_problem(root, env_dir, platform: Optional[str] = None) -> str:
    """Why *env_dir* does not run on this copy's exact managed interpreter, or ``""``.

    Judged against the versioned folder, never the minor-version link: an environment created through the link is
    later accepted by uv without recreation (Phase 3B), and would follow the link wherever it points."""
    home = read_pyvenv_home(env_dir)
    if home is None:
        return "it has no readable pyvenv.cfg home"
    expected = managed_venv_home(root, platform)
    if not _same(home, expected):
        return f"it runs on {home}, not on this copy's managed Python {expected}"
    return ""


def interpreter_build(root, platform: Optional[str] = None) -> Optional[str]:
    """The ``BUILD`` stamp uv writes into a managed install, or None."""
    try:
        return (managed_python_home(root, platform) / "BUILD").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def file_sha256(path) -> Optional[str]:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def uv_problem(root, platform: Optional[str] = None) -> str:
    """Why this copy's uv is not exactly the pinned program, or ``""`` (one SHA-256 of a ~50 MB file)."""
    exe = uv_exe(root, platform)
    if _unsafe(root, exe) is not None or not exe.is_file():
        return f"{exe} is missing"
    if file_sha256(exe) != pins(platform).uv_exe_sha256:
        return f"{exe} is not the pinned uv {UV_VERSION}"
    return ""


def text_sha256(path) -> Optional[str]:
    """SHA-256 of a text file with its line endings normalised, so a CRLF checkout and an LF one agree."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def lock_identity(root) -> Optional[dict]:
    """What a receipt binds an environment to: the project definition and its lock."""
    project = text_sha256(Path(root) / "pyproject.toml")
    lock = text_sha256(Path(root) / "uv.lock")
    if project is None or lock is None:
        return None
    return {"pyproject_sha256": project, "uv_lock_sha256": lock, "uv": UV_VERSION}


# --------------------------------------------------------------------------------------------------------------------
#  Environment and scratch
# --------------------------------------------------------------------------------------------------------------------
_DROPPED_PREFIXES = ("UV_", "PIP_", "XDG_", "CONDA_", "PYTHON", "SSL_CERT_")
_DROPPED_NAMES = frozenset({"VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "__PYVENV_LAUNCHER__"})


def _dropped(name: str) -> bool:
    upper = name.upper()
    return upper in _DROPPED_NAMES or upper.startswith(_DROPPED_PREFIXES)


class Operation:
    """One uv call's own scratch folder: ``files/runtime-data/uv/t/<id>/`` holding ``tmp`` and ``pyc`` (the Python
    download cache). Removed on exit, and only that folder; nothing else in ``t`` is touched."""

    def __init__(self, root) -> None:
        self.root = Path(root)
        self.path = scratch_root(self.root) / uuid.uuid4().hex[:8]

    def __enter__(self) -> "Operation":
        parent = scratch_root(self.root)
        parent.mkdir(parents=True, exist_ok=True)
        if _unsafe(self.root, parent) is not None:
            raise TargetRefused(f"{parent} is reached through a link")
        self.path.mkdir()
        (self.path / "tmp").mkdir()
        (self.path / "pyc").mkdir()
        return self

    def __exit__(self, *exc) -> None:
        self.remove()

    def remove(self) -> None:
        if self.path.parent == scratch_root(self.root) and not os.path.islink(self.path):
            shutil.rmtree(self.path, ignore_errors=True)

    @property
    def tmp(self) -> Path:
        return self.path / "tmp"

    @property
    def python_cache(self) -> Path:
        return self.path / "pyc"


def environment(root, operation: Operation, *, offline: bool = False, env_dir=None,
                base: Optional[Mapping[str, str]] = None, platform: Optional[str] = None) -> dict:
    """The complete environment of one uv process: inherited settings uv or Python would read are dropped, and every
    folder uv could write to is inside the copy (Phase 3A section 2, Phase 3B section 11)."""
    root = Path(os.path.abspath(str(root)))
    source = os.environ if base is None else base
    env = {key: value for key, value in source.items() if not _dropped(key)}
    confined = confined_dir(root)
    tmp = str(operation.tmp)
    env.update({
        "UV_NO_CONFIG": "1",
        "UV_NO_ENV_FILE": "1",
        "UV_CACHE_DIR": str(cache_dir(root)),
        "UV_PYTHON_INSTALL_DIR": str(python_install_dir(root)),
        "UV_PYTHON_CACHE_DIR": str(operation.python_cache),
        "UV_PYTHON_BIN_DIR": str(confined / "pybin"),
        "UV_PYTHON_INSTALL_BIN": "0",
        "UV_PYTHON_INSTALL_REGISTRY": "0",
        "UV_PYTHON_NO_REGISTRY": "1",
        "UV_PYTHON_PREFERENCE": "only-managed",
        "UV_PYTHON_DOWNLOADS": "manual",
        "UV_PYTHON_DOWNLOADS_JSON_URL": str(downloads_json()),
        "UV_TOOL_DIR": str(confined / "tools"),
        "UV_TOOL_BIN_DIR": str(confined / "tool-bin"),
        "UV_CREDENTIALS_DIR": str(confined / "credentials"),
        "UV_LINK_MODE": pins(platform).link_mode,
        "UV_NO_PROGRESS": "1",
        "NO_COLOR": "1",
        "TEMP": tmp,
        "TMP": tmp,
        "TMPDIR": tmp,
    })
    if offline:
        env["UV_OFFLINE"] = "1"
    if env_dir is not None:
        env["UV_PROJECT_ENVIRONMENT"] = os.path.abspath(str(env_dir))
    return env


# --------------------------------------------------------------------------------------------------------------------
#  Commands
# --------------------------------------------------------------------------------------------------------------------
def _common() -> list[str]:
    return ["--no-config", "--color", "never", "--no-progress"]


def python_install_command(root, *, reinstall: bool = False, platform: Optional[str] = None) -> list[str]:
    """Install (or, after a move, refresh) the pinned interpreter from ACT's own archive: no network is needed."""
    command = [str(uv_exe(root, platform)), "python", "install", PYTHON_VERSION, "--mirror", mirror_uri(root),
               "--python-downloads-json-url", str(downloads_json()), "--no-bin", "--no-registry", *_common()]
    if reinstall:
        command.append("--reinstall")
    return command


def venv_command(root, env_dir, *, platform: Optional[str] = None) -> list[str]:
    """Create an empty environment at *env_dir* on exactly the managed interpreter (no pip: uv installs everything)."""
    check_target(root, env_dir)
    return [str(uv_exe(root, platform)), "venv", str(env_dir), "--project", str(project_dir(root)),
            "--python", PYTHON_VERSION, "--no-python-downloads", *_common()]


def sync_command(root, env_dir, *, profile: str, offline: bool, reinstall_packages: Iterable[str] = (),
                 refresh_packages: Iterable[str] = (), no_cache: bool = False, project=None,
                 platform: Optional[str] = None) -> list[str]:
    """``uv sync --locked`` of *env_dir* against *project* (default: the base project at *root*), for one explicit
    profile. Validates the target first (:func:`check_target`)."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}")
    check_target(root, env_dir, project=project)
    project = Path(root) if project is None else Path(project)
    command = [str(uv_exe(root, platform)), "sync", "--project", str(project), "--locked",
               "--python", PYTHON_VERSION, "--no-python-downloads",
               "--link-mode", pins(platform).link_mode, "--compile-bytecode", *_common()]
    command += ["--no-dev"] if profile == PROFILE_USER else ["--group", "dev"]
    if offline:
        command.append("--offline")
    if no_cache:
        command.append("--no-cache")
    for name in reinstall_packages:
        command += ["--reinstall-package", name]
    for name in refresh_packages:
        command += ["--refresh-package", name]
    return command


def pip_install_command(root, python, requirement, *, platform: Optional[str] = None) -> list[str]:
    """Install exactly the verified local files a hash-pinned requirement file names into one environment of this
    copy, offline, with no dependencies (the kept spaCy English model, until Phase 5C moves it to Kokoro)."""
    python = Path(python)
    env_dir = python.parent.parent
    check_target(root, env_dir)
    return [str(uv_exe(root, platform)), "pip", "install", "--python", str(python), "--offline", "--no-index",
            "--no-deps", "--require-hashes", "--link-mode", pins(platform).link_mode, "--compile-bytecode",
            *_common(), "-r", str(requirement)]


def cache_clean_command(root, packages: Iterable[str], platform: Optional[str] = None) -> list[str]:
    """Remove every cache entry of the named packages (their wheels and unpacked archives), so the next sync must fetch
    them again. ``--refresh-package`` alone only revalidates metadata and reuses an unpacked archive whose files were
    damaged (seen in the Phase 4 cache-damage scenario: uv "prepared" the damaged copy again without a download)."""
    names = [str(name) for name in packages]
    if not names:
        raise ValueError("cache_clean_command needs at least one package (never the whole cache)")
    return [str(uv_exe(root, platform)), "cache", "clean", *names, *_common()]


def cache_prune_command(root, platform: Optional[str] = None) -> list[str]:
    """Remove cache entries nothing refers to any more (never the entries the current lock uses)."""
    return [str(uv_exe(root, platform)), "cache", "prune", *_common()]


def lock_command(root, *, check: bool = False, platform: Optional[str] = None) -> list[str]:
    command = [str(uv_exe(root, platform)), "lock", "--project", str(project_dir(root)), "--python", PYTHON_VERSION,
               "--no-python-downloads", *_common()]
    if check:
        command.append("--check")
    return command


# --------------------------------------------------------------------------------------------------------------------
#  Running (the setup's own runner owns stop and child ownership; this one serves developers and small probes)
# --------------------------------------------------------------------------------------------------------------------
def run(command: Sequence[str], env: Mapping[str, str], *, on_line: Callable[[str], None] = print,
        timeout: Optional[float] = None) -> int:
    """Run one uv command, its output streamed line by line. Returns its exit code (-1 if it could not start)."""
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(list(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=dict(env), stdin=subprocess.DEVNULL, **kwargs)
    except OSError as exc:
        on_line(f"uv could not be started: {exc}")
        return -1
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if line:
            on_line(line)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait()


def _main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    root = Path(__file__).resolve().parents[2]
    if str(root / "scripts") not in sys.path:
        sys.path.insert(0, str(root / "scripts"))
    parser = argparse.ArgumentParser(description="Run uv for this copy of ACT, contained (developer use).")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("lock", help="re-lock uv.lock after editing pyproject.toml")
    sub.add_parser("check-lock", help="fail when uv.lock does not match pyproject.toml")
    passthrough = sub.add_parser("uv", help="any other uv command, contained (arguments after --)")
    passthrough.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    problem = uv_problem(root)
    if problem:
        print(f"{problem}. Run the app's Setup_and_Run once to install it.")
        return 2
    with Operation(root) as operation:
        if args.action in ("lock", "check-lock"):
            command = lock_command(root, check=args.action == "check-lock")
            env = environment(root, operation)
        else:
            # Only the separator itself is dropped; a later "--" belongs to uv (e.g. `uv run -- cmd`).
            extra = list(args.args[1:]) if args.args[:1] == ["--"] else list(args.args)
            command = [str(uv_exe(root)), *extra]
            env = environment(root, operation)
        return run(command, env)


if __name__ == "__main__":
    raise SystemExit(_main())
