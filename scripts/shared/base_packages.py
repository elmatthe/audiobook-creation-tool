"""base_packages.py — the app environment's packages: the hash lock, the verified local package store, and the one
pip policy every ACT-managed pip command of the app environment runs under (v0.7.0 portability remediation).

Standard library only, under ``shared/`` on purpose: ``bootstrap`` runs it on the app's base Python before the app
environment has any packages, and ``scripts/verify.py`` and the developer lock generator read the same rules.

* **The lock** (``scripts/requirements-lock-windows-py312.txt``) names every package of the app environment on
  Windows x86-64 CPython 3.12, transitive ones included, at one version, with the SHA-256 of the one artifact pip
  installs there. ``scripts/requirements.txt`` stays the human-maintained list the lock is generated from (by
  ``files/dev-tools/lock_base_requirements.py``); the lock records that file's SHA-256, so editing one without the
  other is a verify failure, not a silent drift.
* **The store** (``files/runtime-data/python-packages``) keeps the verified artifacts after a successful install, so a
  repair or a rebuilt environment installs again without the network. pip checks every artifact's hash again on every
  use (``--require-hashes``), so a damaged or substituted file is refused, never installed.
* **The pip policy**: no inherited ``PIP_*``/``PYTHON*``/activation settings, no pip configuration file
  (``PIP_CONFIG_FILE`` = the null device), no version check, no prompts, and pip's cache at
  ``files/runtime-data/pip-cache`` inside the app's folder. pip finds its default cache through the Windows
  known-folder API, not ``LOCALAPPDATA``, so only an explicit cache setting keeps it out of the user's profile. The
  commands below also pass ``--no-cache-dir``: the store is the cache.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

#: The lock's file name, beside ``requirements.txt``.
LOCK_NAME = "requirements-lock-windows-py312.txt"
#: The one interpreter line the lock describes.
LOCKED_PYTHON = (3, 12)
LOCKED_MACHINES = frozenset({"amd64", "x86_64"})

#: Header keys the generator writes and :func:`lock_problems` reads.
HEADER_REQUIREMENTS = "requirements.txt sha256"
HEADER_SOURCE = "versions proved by"
HEADER_RESOLVER = "resolved with"
HEADER_COUNT = "packages"
#: The comment line naming an entry's artifact, written immediately above the entry.
ARTIFACT_PREFIX = "artifact:"

#: Build backends installed from the lock before anything else: the two locked packages that have no wheel (docopt,
#: antlr4-python3-runtime) are built by the environment's own locked setuptools (``--no-build-isolation``), so no
#: unpinned build tool is ever fetched.
BUILD_BACKENDS = ("setuptools", "wheel")

#: Inherited variables that point a Python or pip at another environment.
_STEERING = frozenset({"VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_PYTHON_EXE",
                       "__PYVENV_LAUNCHER__"})


class LockError(ValueError):
    """The lock (or a requirements line it is checked against) is not in the expected form."""


@dataclass(frozen=True)
class LockEntry:
    name: str
    version: str
    sha256: tuple[str, ...]
    artifact: str  # the artifact's file name, from the comment above the entry ("" when absent)

    @property
    def key(self) -> str:
        return canonical_name(self.name)

    def requirement_line(self) -> str:
        return f"{self.name}=={self.version} " + " ".join(f"--hash=sha256:{h}" for h in self.sha256)


@dataclass(frozen=True)
class Lock:
    header: dict
    entries: tuple[LockEntry, ...]

    def by_key(self) -> dict[str, LockEntry]:
        return {entry.key: entry for entry in self.entries}


def canonical_name(name: str) -> str:
    """PEP 503 normalised project name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def lock_path(requirements_file: Path) -> Path:
    """The lock that belongs to ``requirements_file`` (its sibling)."""
    return Path(requirements_file).with_name(LOCK_NAME)


def store_dir(root: Path) -> Path:
    """``files/runtime-data/python-packages`` of the installation at ``root``: the verified package artifacts."""
    return Path(root) / "files" / "runtime-data" / "python-packages"


def cache_dir(root: Path) -> Path:
    """``files/runtime-data/pip-cache`` of the installation at ``root``: pip's only cache location."""
    return Path(root) / "files" / "runtime-data" / "pip-cache"


def lock_applies(version: Optional[tuple], *, platform: Optional[str] = None, machine: Optional[str] = None) -> bool:
    """True when an environment of this interpreter version on this computer is described by the lock."""
    import platform as _platform

    platform = sys.platform if platform is None else platform
    machine = _platform.machine() if machine is None else machine
    return (platform == "win32" and version is not None and tuple(version[:2]) == LOCKED_PYTHON
            and machine.lower() in LOCKED_MACHINES)


_ENTRY = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.+!_-]*)((?:\s+--hash=sha256:[0-9a-f]{64})+)")
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")


def parse_lock(text: str) -> Lock:
    """Read a lock: header comments, then entries (``name==version --hash=sha256:...``, each preceded by its artifact
    comment). Anything else -- another option, a marker, an unpinned line, a duplicate -- is a :class:`LockError`."""
    header: dict = {}
    entries: list[LockEntry] = []
    seen: set[str] = set()
    artifact = ""
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            body = line[1:].strip()
            if body.startswith(ARTIFACT_PREFIX):
                artifact = body[len(ARTIFACT_PREFIX):].strip()
            elif not entries and ":" in body:
                key, _, value = body.partition(":")
                header.setdefault(key.strip(), value.strip())
            continue
        match = _ENTRY.fullmatch(line)
        if not match:
            raise LockError(f"line {number} is not 'name==version --hash=sha256:...': {line[:120]!r}")
        entry = LockEntry(match.group(1), match.group(2), tuple(_HASH.findall(match.group(3))), artifact)
        if entry.key in seen:
            raise LockError(f"line {number}: {entry.name} is listed twice")
        seen.add(entry.key)
        entries.append(entry)
        artifact = ""
    if not entries:
        raise LockError("the lock lists no packages")
    return Lock(header, tuple(entries))


_MARKER = re.compile(r'python_version\s*(==|!=|>=|<=|<|>)\s*["\'](\d+)\.(\d+)["\']')


def _marker_holds(marker: str, python: tuple[int, int]) -> bool:
    """The only marker form ``requirements.txt`` uses: ``python_version <op> "X.Y"``. Any other is a LockError."""
    match = _MARKER.fullmatch(marker.strip())
    if not match:
        raise LockError(f"unsupported environment marker {marker!r}; extend base_packages to evaluate it")
    op, wanted = match.group(1), (int(match.group(2)), int(match.group(3)))
    return {"==": python == wanted, "!=": python != wanted, ">=": python >= wanted, "<=": python <= wanted,
            "<": python < wanted, ">": python > wanted}[op]


def requirement_pins(requirements_text: str, python: tuple[int, int] = LOCKED_PYTHON) -> dict[str, tuple[str, str]]:
    """``{canonical name: (name, version)}`` of the ``==`` pins in ``requirements.txt`` that apply to ``python``."""
    pins: dict[str, tuple[str, str]] = {}
    for raw in requirements_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        spec, _, marker = line.partition(";")
        if marker and not _marker_holds(marker, python):
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", spec.strip())
        if not match:
            raise LockError(f"requirements.txt line is not an == pin: {line!r}")
        pins[canonical_name(match.group(1))] = (match.group(1), match.group(2))
    return pins


def lock_problems(requirements_text: str, lock_text: str, requirements_sha256: str) -> list[str]:
    """Everything that makes the lock not a faithful, complete freeze of ``requirements.txt`` (empty when none)."""
    try:
        lock = parse_lock(lock_text)
        pins = requirement_pins(requirements_text)
    except LockError as exc:
        return [str(exc)]
    problems = []
    if lock.header.get(HEADER_REQUIREMENTS) != requirements_sha256:
        problems.append("the lock was generated from a different requirements.txt; regenerate it "
                        "(files/dev-tools/lock_base_requirements.py)")
    if lock.header.get(HEADER_COUNT) != str(len(lock.entries)):
        problems.append(f"the lock header counts {lock.header.get(HEADER_COUNT)} packages but lists "
                        f"{len(lock.entries)}")
    entries = lock.by_key()
    for key, (name, version) in sorted(pins.items()):
        entry = entries.get(key)
        if entry is None:
            problems.append(f"{name}=={version} from requirements.txt is not in the lock")
        elif entry.version != version:
            problems.append(f"{name}: requirements.txt pins {version}, the lock has {entry.version}")
    for entry in lock.entries:
        if not entry.artifact:
            problems.append(f"{entry.name} has no artifact line")
        elif artifact_identity(entry.artifact) != (entry.key, entry.version):
            problems.append(f"{entry.name}=={entry.version}: the artifact {entry.artifact} is not that release")
    return problems


def artifact_identity(filename: str) -> Optional[tuple[str, str]]:
    """``(canonical name, version)`` from a wheel or source-archive file name, or None for anything else."""
    if filename.endswith(".whl"):
        parts = filename[:-4].split("-")
        return (canonical_name(parts[0]), parts[1]) if len(parts) >= 5 else None
    for suffix in (".tar.gz", ".zip"):
        if filename.endswith(suffix):
            stem = filename[: -len(suffix)]
            name, _, version = stem.rpartition("-")
            return (canonical_name(name), version) if name and version else None
    return None


def pip_environment(base: Mapping[str, str], cache: Path) -> dict:
    """The environment of every ACT-managed pip command for the app environment (see the module note)."""
    env = {key: value for key, value in base.items()
           if not key.upper().startswith(("PIP_", "PYTHON")) and key.upper() not in _STEERING}
    env.update({
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_CACHE_DIR": str(cache),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    return env


def _common(python: Path) -> list[str]:
    return [str(python), "-m", "pip"]


def download_command(python: Path, requirements: Path, store: Path) -> list[str]:
    """Fetch every artifact ``requirements`` names into ``store``, each checked against its SHA-256. An artifact
    already there with the right hash is kept; one with the wrong hash is downloaded again."""
    return [*_common(python), "download", "--require-hashes", "--no-deps", "--no-build-isolation", "--no-cache-dir",
            "--progress-bar", "off", "--dest", str(store), "-r", str(requirements)]


def install_command(python: Path, requirements: Path, store: Path, *, no_deps: bool = False,
                    force: bool = False) -> list[str]:
    """Install exactly what ``requirements`` names from ``store`` alone: no index, every hash checked, into this
    virtual environment only. Dependencies are checked (unless ``no_deps``), so a lock missing one fails loudly."""
    command = [*_common(python), "install", "--require-hashes", "--require-virtualenv", "--no-index",
               "--find-links", str(store), "--no-build-isolation", "--no-cache-dir", "--progress-bar", "off"]
    if no_deps:
        command.append("--no-deps")
    if force:
        command.append("--force-reinstall")
    return [*command, "-r", str(requirements)]


def unlocked_install_command(python: Path, requirements_file: Path) -> list[str]:
    """An interpreter the lock does not describe (not Windows x86-64 CPython 3.12): the ``==`` pins of
    ``requirements.txt``, with the same pip policy (cache inside the app's folder via :func:`pip_environment`)."""
    return [*_common(python), "install", "--require-virtualenv", "--progress-bar", "off", "-r", str(requirements_file)]


def requirement_text(entries: Iterable[LockEntry]) -> str:
    """A requirements file of these lock entries alone (hashes kept)."""
    return "".join(entry.requirement_line() + "\n" for entry in entries)


def build_backends(lock: Lock) -> list[LockEntry]:
    entries = lock.by_key()
    return [entries[name] for name in BUILD_BACKENDS if name in entries]


def missing_artifacts(lock: Lock, store: Path, entries: Optional[Iterable[LockEntry]] = None) -> list[LockEntry]:
    """Entries whose artifact is not in ``store`` as a regular file (no hash check: pip does that on use)."""
    missing = []
    for entry in (lock.entries if entries is None else entries):
        path = store / entry.artifact if entry.artifact else None
        try:
            ok = path is not None and stat.S_ISREG(os.lstat(path).st_mode)
        except OSError:
            ok = False
        if not ok:
            missing.append(entry)
    return missing


def prune_store(lock: Lock, store: Path) -> list[str]:
    """Remove artifacts of releases the lock no longer names from ``store``; returns their names. Only plain files
    whose names parse as a wheel or source archive are considered; anything else is left exactly as it is."""
    wanted = {(entry.key, entry.version) for entry in lock.entries}
    removed = []
    try:
        names = sorted(os.listdir(store))
    except OSError:
        return removed
    for name in names:
        identity = artifact_identity(name)
        path = store / name
        if identity is None or identity in wanted:
            continue
        try:
            if stat.S_ISREG(os.lstat(path).st_mode):
                path.unlink()
                removed.append(name)
        except OSError:
            pass
    return removed
