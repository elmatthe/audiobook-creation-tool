"""Environments held inside the app's environment: where they may be, and what keeps them safe.

v0.7.0 P04A (plan Revision 2 §5.5); adopted in P04C Stage 2. The app runs in ``.venv``; the Qwen3 engine runs in a
second, independent environment held inside it, at ``.venv/engines/qwen3`` (``tts.qwen3_runtime.venv_dir`` is the
path authority, and an older ``.venv-qwen3`` beside the parent is still used while it is the only one). This module
is the vocabulary the parent's own lifecycle needs so that replacing, restoring or clearing the parent can never
delete what is held there, strand it in a backup, or run it from a place it was not built.

The rules it encodes:

* **Anything under ``engines/`` is held.** A folder, a file or a link: only the installer that put it there may
  decide what it is, so nothing here guesses. A folder that cannot be read counts as holding something.
* **A child is identified, never assumed.** It must be at its own final path, reached through no link, not see the
  system's packages, not be built from the parent's interpreter, still be where it was created (``pyvenv.cfg``
  ``command``), and match a recorded base-interpreter identity. Missing, changed or unrecorded evidence is
  *unverified*, never healthy. Identity is necessary, not sufficient: the engine's own import probe is still needed.
* **The two Qwen3 locations are named exactly.** Nothing is searched for; when both are present, neither is chosen.
* **So are the two OmniVoice locations** (v0.8.0, owner decision 2026-11-13: one ``.venv`` holding three independent
  environments). ``.venv/engines/omnivoice`` is the only place the OmniVoice engine is installed or run from
  (``tts.omnivoice_runtime.venv_dir``); the earlier ``.venv-omnivoice`` beside the parent is never a runtime target --
  it is only recognised so that a proved replacement can retire it, kept, to a set-aside folder.

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
#: The two Qwen3 locations, relative to the repository root. New installs go to the nested (canonical) one only.
LEGACY_QWEN3 = ".venv-qwen3"
NESTED_QWEN3 = ".venv/engines/qwen3"  # canonical since P04C Stage 2
#: The two OmniVoice locations (v0.8.0). Only the nested one is ever installed into or run from; the sibling is where
#: the first v0.8.0 development builds put it, and is only ever retired (moved aside, kept), never used or deleted.
LEGACY_OMNIVOICE = ".venv-omnivoice"
NESTED_OMNIVOICE = ".venv/engines/omnivoice"  # canonical (owner decision 2026-11-13, unified .venv layout)

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
# The two locations of each separately installed engine
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EngineLayouts:
    legacy: Optional[Path]
    nested: Optional[Path]

    @property
    def both(self) -> bool:
        return self.legacy is not None and self.nested is not None


#: The name this had while Qwen3 was the only engine held in the parent (v0.7.0 P04A).
Qwen3Layouts = EngineLayouts


def _layouts(repo_root, legacy: str, nested: str) -> EngineLayouts:
    root = Path(os.path.abspath(str(repo_root)))
    found = []
    for relative in (legacy, nested):
        path = root.joinpath(*relative.split("/"))
        try:
            found.append(path if os.path.lexists(path) else None)
        except OSError:
            found.append(path)
    return EngineLayouts(legacy=found[0], nested=found[1])


def qwen3_layouts(repo_root) -> EngineLayouts:
    """Which of the two exact Qwen3 locations have something at them (anything, even a link or a stray file).

    No other name is recognised and nothing is searched for. Presence is not health and never a reason to remove the
    other one: when both are present that is a decision to report, not to take.
    """
    return _layouts(repo_root, LEGACY_QWEN3, NESTED_QWEN3)


def omnivoice_layouts(repo_root) -> EngineLayouts:
    """Which of the two exact OmniVoice locations have something at them (anything, even a link or a stray file).

    The same rule as :func:`qwen3_layouts`: two exact names, no search, and presence is not health. Unlike Qwen3's,
    the sibling is never used -- what is at the nested path is the only thing ever judged or run.
    """
    return _layouts(repo_root, LEGACY_OMNIVOICE, NESTED_OMNIVOICE)
