"""Environments held inside the app's environment: where they may be, and what keeps them safe.

v0.7.0 P04A (plan Revision 2 §5.5). The app runs in ``.venv``; the Qwen3 engine runs in a second, independent
environment, today ``.venv-qwen3`` beside it. A *candidate* layout puts such an engine inside the parent, at
``.venv/engines/<name>/``. **That layout is not adopted.** Nothing installs there and the Qwen3 path authority
(``tts.qwen3_runtime.venv_dir``) is unchanged. This module is the vocabulary the parent's own lifecycle needs so
that, if anything is ever there, replacing, restoring or clearing the parent can never delete it, strand it in a
backup, or run it from a place it was not built.

The rules it encodes:

* **Anything under ``engines/`` is held.** A folder, a file or a link: only the installer that put it there may
  decide what it is, so nothing here guesses. A folder that cannot be read counts as holding something.
* **A child is identified, never assumed.** It must be at its own final path, reached through no link, not see the
  system's packages, not be built from the parent's interpreter, still be where it was created (``pyvenv.cfg``
  ``command``), and match a recorded base-interpreter identity. Missing, changed or unrecorded evidence is
  *unverified*, never healthy. Identity is necessary, not sufficient: the engine's own import probe is still needed.
* **The two Qwen3 locations are named exactly.** Nothing is searched for; when both are present, neither is chosen.

Read-only and standard-library only, because the bootstrap (a base interpreter) and the cleanup coordinator (a
non-venv interpreter) both import it. It removes and renames nothing; the bootstrap owns those transactions.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: The one folder inside a parent environment where an independent child environment may be held.
ENGINES_DIRNAME = "engines"
#: The two Qwen3 locations, relative to the repository root. Only the legacy one is in use.
LEGACY_QWEN3 = ".venv-qwen3"
NESTED_QWEN3 = ".venv/engines/qwen3"  # candidate only (P04A); not adopted

IDENTITY_OK = "identity-ok"
UNVERIFIED = "unverified"
BROKEN = "broken"
ABSENT = "absent"

_CASE_INSENSITIVE = os.name == "nt"


def _fold(text: str) -> str:
    return text.casefold() if _CASE_INSENSITIVE else text


def _norm(path) -> str:
    return _fold(os.path.normpath(os.path.abspath(str(path))))


def same_path(first, second) -> bool:
    """Whether two paths name one location, lexically (links are not resolved)."""
    return _norm(first) == _norm(second)


def is_within(root, candidate) -> bool:
    """Whether *candidate* is *root* or lies inside it, lexically."""
    root_text, cand_text = _norm(root), _norm(candidate)
    return cand_text == root_text or cand_text.startswith(root_text.rstrip(os.sep) + os.sep)


def is_link(path) -> bool:
    """A symlink, a junction or any other reparse point. True when it cannot be told (fail closed)."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(info, "st_file_attributes", 0) & reparse)


def unsafe_component(root, path) -> Optional[Path]:
    """The first thing that makes *path* unsafe to reach from *root*, or ``None``.

    That is *path* itself when it is not inside *root*, or else the first component below *root*, down to and
    including *path*, that is a link. *root* itself is trusted: a repository kept on another drive through a link is
    legitimate, a link inside it that redirects one of its own environments is not.
    """
    root_abs, path_abs = Path(os.path.abspath(str(root))), Path(os.path.abspath(str(path)))
    if not is_within(root_abs, path_abs):
        return path_abs
    walked = root_abs
    for part in path_abs.parts[len(root_abs.parts):]:
        walked = walked / part
        if is_link(walked):
            return walked
    return None


def engines_dir(parent) -> Path:
    return Path(parent) / ENGINES_DIRNAME


def held_entries(parent) -> Optional[tuple[str, ...]]:
    """The names held under ``parent/engines``: ``()`` for nothing, ``None`` when it cannot be read.

    An ``engines`` that is itself a link or a file is reported as held (``("engines",)``): it is somebody's, and a
    parent's removal would take it.
    """
    folder = engines_dir(parent)
    try:
        if not os.path.lexists(folder):
            return ()
    except OSError:
        return None
    if is_link(folder) or not folder.is_dir():
        return (ENGINES_DIRNAME,)
    try:
        with os.scandir(folder) as entries:
            return tuple(sorted(entry.name for entry in entries))
    except OSError:
        return None


def holds_environments(parent) -> bool:
    """Whether removing *parent* would also remove something held under its ``engines`` folder."""
    entries = held_entries(parent)
    return entries is None or bool(entries)


# --------------------------------------------------------------------------- #
# A child environment's identity
# --------------------------------------------------------------------------- #
def interpreter(env) -> Path:
    sub = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    return Path(env).joinpath(*sub)


def read_pyvenv_cfg(env) -> Optional[dict[str, str]]:
    """The ``key = value`` pairs of ``env/pyvenv.cfg`` (keys lower-cased), or ``None`` when it cannot be read."""
    try:
        text = (Path(env) / "pyvenv.cfg").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip().lower()] = value.strip()
    return values


def base_identity(env) -> Optional[dict]:
    """What *env* was built from, explicitly: home, version, executable and that executable's size and mtime.

    ``None`` when ``pyvenv.cfg`` names no home or the base interpreter is gone. The size and mtime are what notices an
    interpreter replaced in place (a reinstall or upgrade into the same folder), which ``pyvenv.cfg`` cannot.
    """
    cfg = read_pyvenv_cfg(env)
    if not cfg or not cfg.get("home"):
        return None
    name = "python.exe" if sys.platform == "win32" else "python3"
    executable = cfg.get("executable") or str(Path(cfg["home"]) / name)
    try:
        info = os.stat(executable)
    except OSError:
        return None
    return {"home": _norm(cfg["home"]), "version": cfg.get("version") or cfg.get("version_info", ""),
            "executable": _norm(executable), "size": info.st_size, "mtime_ns": info.st_mtime_ns}


@dataclass(frozen=True)
class ChildAssessment:
    state: str
    reason: str

    @property
    def identity_ok(self) -> bool:
        return self.state == IDENTITY_OK


def assess_child(env, *, final_path, root, parent=None, recorded_base: Optional[dict] = None) -> ChildAssessment:
    """Whether *env* is provably the independent environment that belongs at *final_path*.

    *root* bounds where it may be reached from; *parent* is the environment it is held in, if any; *recorded_base* is
    the :func:`base_identity` captured when it was installed (stored outside the parent). Checked in this order, and
    the first failure is the answer.
    """
    env = Path(os.path.abspath(str(env)))
    if not same_path(env, final_path):
        return ChildAssessment(UNVERIFIED, "it is not at its own location (a held or moved copy is never used)")
    linked = unsafe_component(root, env)
    if linked is not None:
        return ChildAssessment(UNVERIFIED, f"it is reached through a link or lies outside the app folder ({linked.name})")
    if not os.path.lexists(env):
        return ChildAssessment(ABSENT, "it is not installed")
    if not env.is_dir():
        return ChildAssessment(BROKEN, "it is not a folder")
    cfg = read_pyvenv_cfg(env)
    if cfg is None:
        return ChildAssessment(BROKEN, "it has no readable pyvenv.cfg")
    if cfg.get("include-system-site-packages", "").lower() != "false":
        return ChildAssessment(BROKEN, "it is not isolated (include-system-site-packages is not false)")
    if not interpreter(env).is_file():
        return ChildAssessment(BROKEN, "its interpreter is missing")
    if parent is not None:
        if same_path(env, parent):
            return ChildAssessment(BROKEN, "it is the parent environment itself")
        for key in ("home", "executable"):
            if cfg.get(key) and is_within(parent, cfg[key]):
                return ChildAssessment(BROKEN, "it was built from the parent environment's interpreter")
    command = cfg.get("command")  # venv records the absolute destination it was created at, last
    if command and not _fold(command.rstrip().rstrip("\\/")).endswith(_fold(str(env))):
        return ChildAssessment(UNVERIFIED, "it was created somewhere else and moved; environments cannot be moved")
    current = base_identity(env)
    if current is None:
        return ChildAssessment(UNVERIFIED, "the Python it was built from is missing")
    if recorded_base is None:
        return ChildAssessment(UNVERIFIED, "no base-interpreter identity was recorded for it")
    if current != recorded_base:
        return ChildAssessment(UNVERIFIED, "the Python it was built from has changed since it was installed")
    return ChildAssessment(IDENTITY_OK, "identity matches; the engine's own import check is still required")


# --------------------------------------------------------------------------- #
# The two Qwen3 locations
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Qwen3Layouts:
    legacy: Optional[Path]
    nested: Optional[Path]

    @property
    def both(self) -> bool:
        return self.legacy is not None and self.nested is not None


def qwen3_layouts(repo_root) -> Qwen3Layouts:
    """Which of the two exact Qwen3 locations have something at them (anything, even a link or a stray file).

    No other name is recognised and nothing is searched for. Presence is not health and never a reason to remove the
    other one: when both are present that is a decision to report, not to take.
    """
    root = Path(os.path.abspath(str(repo_root)))
    found = []
    for relative in (LEGACY_QWEN3, NESTED_QWEN3):
        path = root.joinpath(*relative.split("/"))
        try:
            found.append(path if os.path.lexists(path) else None)
        except OSError:
            found.append(path)
    return Qwen3Layouts(legacy=found[0], nested=found[1])
