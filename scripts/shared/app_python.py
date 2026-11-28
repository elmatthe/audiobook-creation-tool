"""app_python.py — which of this copy's own base interpreters a consumer means (v0.8.2 Phase 4). Standard library only.

Phase 4 moved the app's environment (``.venv``) onto the uv-managed CPython 3.12.15 (PBS 20261009) in
``files/runtime-data/uv/python/<versioned folder>``. The interpreter every earlier release placed in
``files/runtime-data/python`` (the *legacy* one, the same build) stays where it is on an existing installation, because
voice-engine environments made before Phase 4 name it in their ``pyvenv.cfg`` (transitional rule 2); nothing here ever
deletes or moves it. This module is the one resolver every consumer asks, so the two never drift apart:

* :func:`managed` / :func:`legacy` -- the two places, by platform.
* :func:`own_homes` -- the ``pyvenv.cfg`` ``home`` values that mean "this copy's own Python" (either one).
* :func:`app_env_base` -- the base interpreter the app's ``.venv`` actually runs on: what the not-yet-migrated engine
  installers (Qwen3, OmniVoice) build a new environment from, and what the cleanup coordinator may run on. A fresh
  installation has only the managed interpreter; a migrated one uses the managed interpreter for everything new while
  its existing engines keep their legacy one.

Seam (removed in Phase 6, once every environment runs on the managed interpreter): the legacy interpreter and the
legacy half of :func:`own_homes`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from shared import uv_runner

#: The legacy base interpreter's folder, relative to the copy (v0.7.0 to v0.8.1).
LEGACY_PARTS = ("files", "runtime-data", "python")


def _platform(platform: Optional[str]) -> str:
    return sys.platform if platform is None else platform


def legacy_home(root) -> Path:
    return Path(root).joinpath(*LEGACY_PARTS)


def legacy(root, platform: Optional[str] = None) -> Path:
    home = legacy_home(root)
    return home / "python.exe" if _platform(platform) == "win32" else home / "bin" / "python3.12"


def managed(root, platform: Optional[str] = None) -> Path:
    return uv_runner.managed_python(root, platform)


def _venv_home_of(interpreter_home: Path, platform: Optional[str]) -> Path:
    return interpreter_home if _platform(platform) == "win32" else interpreter_home / "bin"


def own_homes(root, platform: Optional[str] = None) -> tuple[Path, Path]:
    """``(managed, legacy)`` as ``pyvenv.cfg`` writes them (Windows: the interpreter folder; POSIX: its ``bin``)."""
    return (uv_runner.managed_venv_home(root, platform), _venv_home_of(legacy_home(root), platform))


def _same(first, second) -> bool:
    from shared import venv_layout

    return venv_layout.same_path(first, second)


def app_env_base(root, platform: Optional[str] = None) -> Path:
    """The base interpreter of the copy's ``.venv`` when it is one of the copy's own two, else the managed one.

    Read from ``.venv/pyvenv.cfg`` (no process is started). The managed interpreter is the answer for a fresh copy and
    for any environment this copy did not build, so nothing new is ever built on an interpreter from elsewhere."""
    home = uv_runner.read_pyvenv_home(Path(root) / ".venv")
    managed_home, legacy_venv_home = own_homes(root, platform)
    if home is not None and _same(home, legacy_venv_home) and not _same(home, managed_home):
        return legacy(root, platform)
    return managed(root, platform)


def is_own_base(root, candidate, platform: Optional[str] = None) -> bool:
    """True when *candidate* is exactly one of this copy's two base interpreters."""
    return any(_same(candidate, path) for path in (managed(root, platform), legacy(root, platform)))


def owner_of_home(home, platform: Optional[str] = None) -> Optional[Path]:
    """The installation root whose own base interpreter folder *home* is (managed or legacy layout), else None.

    Used to recognise an environment that runs on another copy's Python (a copied app folder, v0.7.0 D1)."""
    parts = Path(os.path.abspath(str(home))).parts
    folded = tuple(part.casefold() for part in parts)
    if _platform(platform) != "win32" and folded and folded[-1] == "bin":
        parts, folded = parts[:-1], folded[:-1]
    legacy_tail = tuple(part.casefold() for part in LEGACY_PARTS)
    if len(parts) > len(LEGACY_PARTS) and folded[-len(LEGACY_PARTS):] == legacy_tail:
        return Path(*parts[: -len(LEGACY_PARTS)])
    managed_tail = ("files", "runtime-data", "uv", "python", uv_runner.pins(platform).python_key.casefold())
    if len(parts) > len(managed_tail) and folded[-len(managed_tail):] == managed_tail:
        return Path(*parts[: -len(managed_tail)])
    return None
