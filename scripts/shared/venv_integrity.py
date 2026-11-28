"""venv_integrity.py — cheap launch-time facts about the app's ``.venv`` that its interpreter cannot report itself
(v0.7.0 acceptance D1 and D3).

Standard library only: ``bootstrap`` reads these on the launch path (``--venv-check``, ~150 ms in all) and before the
app environment has any packages, and the GUI writes the repair request through the same module.

* **Whose Python is it?** A venv runs on the base interpreter named by ``home`` in its ``pyvenv.cfg``. A copied app
  folder keeps the original's absolute ``home``, so while the original exists the copy silently runs on the original's
  Python -- and breaks the moment that folder is moved or deleted (D1). :func:`foreign_base_python` recognises a
  ``home`` that is another installation's own Python (``<root>/files/runtime-data/python`` of a different root).
* **Are the installed packages still whole?** A package whose files are gone while its metadata remains is "already
  satisfied" to pip and passes every cheap check, then fails at the first conversion (D3: ``numpy/__init__.py``
  removed). :func:`package_damage` compares what each installed distribution's own ``RECORD`` says must exist --
  every package's ``__init__.py``, every top-level module and every native library -- with the disk: about 600 files
  for the whole Windows environment, ~10 ms warm. The list is cached in the venv (:data:`MANIFEST_NAME`), keyed by
  the installed distributions, and is rebuilt from the ``RECORD`` files (never from what is on disk) whenever that set
  changes. A deeper break inside a package (one ``.py`` deep in a tree) is left to the real import proof.
* **Has the user asked for a repair?** :data:`REPAIR_REQUEST_NAME` inside the venv. It lives in the environment it
  condemns, so a rebuilt environment is born without it and a repair that is rolled back keeps it for the next try.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Iterable, Optional

#: The cached list of files :func:`package_damage` checks, inside the venv.
MANIFEST_NAME = ".package-manifest.json"
MANIFEST_SCHEMA = 1
#: Written by "Repair App Environment" (Preferences & Data), inside the venv it asks to replace.
REPAIR_REQUEST_NAME = ".repair-requested"

#: Library files a package cannot work without and that an antivirus or a partial delete typically takes.
_NATIVE_SUFFIXES = (".pyd", ".dll", ".so", ".dylib")
#: The installation-relative parts of an app's own base Python (``bootstrap.APP_PYTHON_DIR``).
APP_PYTHON_PARTS = ("files", "runtime-data", "python")


def _key(path) -> tuple[str, ...]:
    absolute = os.path.abspath(str(path))
    parts = Path(absolute).parts
    # v0.8.x P1A (MAC-015): the volume decides on a Mac; Windows is always case-blind, as before.
    from . import venv_layout

    return tuple(p.casefold() for p in parts) if venv_layout.case_insensitive(absolute) else parts


def pyvenv_home(venv_dir: Path) -> Optional[Path]:
    """The ``home`` (base interpreter folder) named by ``venv_dir/pyvenv.cfg``, or None when unreadable/absent."""
    try:
        text = (Path(venv_dir) / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() == "home" and value.strip():
            return Path(value.strip())
    return None


def app_python_owner(home: Path) -> Optional[Path]:
    """The installation root whose own base Python ``home`` is, else None: ``<root>/files/runtime-data/python`` (the
    legacy layout) or, since v0.8.2 Phase 4, the managed ``<root>/files/runtime-data/uv/python/<versioned folder>``
    (``shared.app_python``, the one resolver of both)."""
    from shared import app_python

    return app_python.owner_of_home(home)


def foreign_base_python(venv_dir: Path, root: Path) -> Optional[Path]:
    """``home`` of ``venv_dir`` when it is ANOTHER installation's own Python (a copied app folder), else None.

    A system Python (a developer checkout's, or one a first run found before v0.7.0) is not foreign: it belongs to no
    copy of the app, so moving or deleting a copy cannot take it away.
    """
    home = pyvenv_home(venv_dir)
    owner = app_python_owner(home) if home is not None else None
    if owner is None or _key(owner) == _key(root):
        return None
    return home


def site_packages(venv_dir: Path) -> Optional[Path]:
    venv_dir = Path(venv_dir)
    windows = venv_dir / "Lib" / "site-packages"
    if windows.is_dir():
        return windows
    try:
        found = sorted((venv_dir / "lib").glob("python3*/site-packages"))
    except OSError:
        return None
    return found[-1] if found else None


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _distributions(site: Path) -> Optional[list[str]]:
    try:
        with os.scandir(site) as entries:
            return sorted(e.name for e in entries if e.name.endswith(".dist-info") and e.is_dir())
    except OSError:
        return None


def _record_files(site: Path, dist: str) -> list[list]:
    """``[relative path, size or -1]`` of the files in ``dist``'s RECORD that a launch checks.

    v0.8.2 Phase 4: a distribution without a RECORD is damage, never "nothing to check" -- an interrupted uv sync
    leaves exactly that (a dist-info with no RECORD and most files gone) while ``uv sync --check`` sees nothing wrong
    (Phase 3A/3B). Its RECORD is then listed as the file that must exist, so the launch reports it missing."""
    try:
        text = (site / dist / "RECORD").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [[f"{dist}/RECORD", -1]]
    chosen = []
    for row in csv.reader(io.StringIO(text)):
        if not row or not row[0] or row[0].startswith(("..", "/")) or "__pycache__" in row[0]:
            continue
        path = row[0]
        parts = path.split("/")
        lowered = path.lower()
        if not (lowered.endswith(_NATIVE_SUFFIXES)
                or (len(parts) == 2 and parts[1] == "__init__.py")
                or (len(parts) == 1 and lowered.endswith(".py"))):
            continue
        size = row[2] if len(row) > 2 else ""
        chosen.append([path, int(size) if size.isdigit() else -1])
    return chosen


def _manifest(venv_dir: Path, site: Path, dists: list[str]) -> dict:
    """``{distribution: [[path, size], ...]}``: the cached list when it describes exactly these distributions, else
    rebuilt from their RECORD files and cached (best effort: an unwritable venv is simply re-read next time)."""
    cache = Path(venv_dir) / MANIFEST_NAME
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
        if payload.get("schema") == MANIFEST_SCHEMA and payload.get("distributions") == dists:
            return payload["files"]
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        pass
    files = {dist: _record_files(site, dist) for dist in dists}
    try:
        temporary = cache.with_name(f"{cache.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps({"schema": MANIFEST_SCHEMA, "distributions": dists, "files": files}),
                             encoding="utf-8")
        os.replace(temporary, cache)
    except OSError:
        pass
    return files


def package_damage(venv_dir: Path, *, required: Iterable[str] = (), limit: int = 4) -> list[str]:
    """What is materially missing or damaged among the environment's installed packages; [] when nothing was found.

    ``required`` names distributions that must be installed (the dependency lock's, once the environment has been
    reconciled against it): one that is absent altogether has no RECORD left to check. Anything this cannot read is no
    finding -- a check that cannot run must never send a working environment into a rebuild. At most ``limit``
    findings are described; one more line says how many others there were.
    """
    site = site_packages(venv_dir)
    dists = _distributions(site) if site is not None else None
    if dists is None:
        return []
    findings: list[str] = []
    installed = {_canonical(d[: -len(".dist-info")].rpartition("-")[0]) for d in dists}
    for name in required:
        if _canonical(name) not in installed:
            findings.append(f"{name} is not installed")
    for dist, files in _manifest(venv_dir, site, dists).items():
        shown = dist[: -len(".dist-info")]
        for path, size in files:
            try:
                actual = os.stat(site / path).st_size
            except OSError:
                findings.append(f"{shown}: {path} is missing")
                continue
            if size >= 0 and actual != size:
                findings.append(f"{shown}: {path} has changed")
    if len(findings) > limit:
        return findings[:limit] + [f"and {len(findings) - limit} more"]
    return findings


def _dist_name(dist: str) -> tuple[str, str]:
    """``(canonical name, version)`` from a ``<name>-<version>.dist-info`` folder name."""
    name, _sep, version = dist[: -len(".dist-info")].rpartition("-")
    return _canonical(name), version


def installed_distributions(venv_dir: Path) -> list[str]:
    """``name==version`` of every distribution installed in the environment (its dist-info folders), sorted."""
    site = site_packages(venv_dir)
    dists = _distributions(site) if site is not None else None
    return sorted("==".join(_dist_name(dist)) for dist in (dists or []))


def _record_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256=" + base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")


def record_damage(venv_dir: Path, *, hashes: bool = True) -> dict[str, str]:
    """``{canonical name: first problem}`` for every installed distribution whose files do not match its RECORD.

    The full check a sync must pass before a receipt is written (v0.8.2 Phase 4; the launch keeps the cheap
    :func:`package_damage`). The RECORD is parsed here with ``csv``, never through ``importlib.metadata``: Python
    3.12's ``Distribution.files`` silently drops files that no longer exist. A dist-info without RECORD or METADATA is
    damage; so is a listed file that is missing, of another size or (``hashes``) of another SHA-256. Entries outside
    the environment are refused rather than read. uv reuses cached files without checking them, so this is also what
    notices a damaged repair cache. Measured cost on Windows: about 4 s for the base environment without hashes and
    about 10 s with them.
    """
    venv_dir = Path(venv_dir)
    site = site_packages(venv_dir)
    dists = _distributions(site) if site is not None else None
    if not dists:
        return {}
    top = os.path.normcase(os.path.abspath(str(venv_dir)))
    findings: dict[str, str] = {}
    for dist in dists:
        name, _version = _dist_name(dist)
        folder = site / dist
        if not (folder / "METADATA").is_file():
            findings[name] = "its METADATA is missing"
            continue
        try:
            text = (folder / "RECORD").read_text(encoding="utf-8", errors="replace")
        except OSError:
            findings[name] = "its RECORD is missing"
            continue
        for row in csv.reader(io.StringIO(text)):
            if not row or not row[0]:
                continue
            relative = row[0]
            target = os.path.abspath(os.path.join(str(site), relative))
            if os.path.normcase(target) != top and not os.path.normcase(target).startswith(top + os.sep):
                findings[name] = f"its RECORD names a file outside the environment ({relative})"
                break
            expected_hash = row[1] if len(row) > 1 else ""
            expected_size = row[2] if len(row) > 2 else ""
            try:
                size = os.stat(target).st_size
            except OSError:
                findings[name] = f"{relative} is missing"
                break
            if expected_size.isdigit() and size != int(expected_size):
                findings[name] = f"{relative} has changed (size)"
                break
            if hashes and expected_hash.startswith("sha256="):
                try:
                    if _record_digest(Path(target)) != expected_hash:
                        findings[name] = f"{relative} has changed (SHA-256)"
                        break
                except OSError:
                    findings[name] = f"{relative} cannot be read"
                    break
    return findings


def repair_request_path(venv_dir: Path) -> Path:
    return Path(venv_dir) / REPAIR_REQUEST_NAME


def request_repair(venv_dir: Path, reason: str = "") -> bool:
    """Ask the next launch to rebuild ``venv_dir``. True when the request is recorded."""
    venv_dir = Path(venv_dir)
    if not (venv_dir / "pyvenv.cfg").is_file():
        return False  # nothing to repair here; the launcher already treats a missing environment as a first run
    try:
        repair_request_path(venv_dir).write_text(
            json.dumps({"requested_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": reason}, indent=2),
            encoding="utf-8")
        return True
    except OSError:
        return False


def repair_requested(venv_dir: Path) -> bool:
    return repair_request_path(venv_dir).is_file()
