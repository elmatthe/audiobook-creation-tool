"""engine_env.py — what every independent engine environment shares (v0.8.2 Phase 5A). Standard library only.

An engine with its own uv project (``tts.engines.registry`` placement ``engine``: Qwen3 since 5A; OmniVoice, Kokoro and
Chatterbox follow in 5B-5D) lives in ``ACT_ROOT/.venv-engines/<key>/``, a sibling of the app's ``.venv`` (approved A1),
built by uv on this copy's managed CPython 3.12.15 from ``scripts/tts/engines/<key>/pyproject.toml`` + ``uv.lock``.
This module holds only what such engines have in common, so each engine installer keeps its own model acquisition,
health probe and synthesis:

* **Selection.** :func:`project_dir` and :func:`env_dir` come from the registry; ``shared.uv_runner.check_target``
  refuses anything that is not this copy's own ``.venv-engines/<key>`` reached through no link, or a project without
  its ``pyproject.toml`` and ``uv.lock``.
* **Commands.** :func:`venv_command` (``uv venv`` on exactly the managed interpreter) and :func:`sync_command`
  (``uv sync --locked --no-dev``, bytecode compiled, Windows copy / macOS clone; ``--no-cache`` by default: no GPU
  engine keeps a package cache, approved A4/D-8), both through ``shared.uv_runner``, the one uv wrapper.
* **Interpreter validation.** :func:`identity_problem`: at its own place, no link, isolated, built by uv, on this
  copy's managed interpreter folder with the pinned build stamp. (A size/mtime stamp of ``python.exe`` is deliberately
  not part of it: a byte-identical ``uv python install --reinstall`` must not cost a multi-gigabyte download.)
* **Receipts.** :func:`write_receipt` -- only after the sync, a direct RECORD check (:func:`record_damage`,
  ``shared.venv_integrity``) and the engine's own health proof -- binds the environment to its project's lock, the
  interpreter, the profile and that proof; :func:`receipt_problem` says why a receipt is not current. A missing or
  stale receipt is never success.
* **Offline reporting.** :func:`offline_miss` recognises uv's "not in the cache" answers.
* **Retirement.** :func:`retire` moves a superseded environment of an earlier version, whole and on the same volume,
  to ``files/runtime-data/<key>/set-aside/`` with a ``RETIRED-READ-ME.txt`` (the convention OmniVoice set in v0.8.0):
  kept for the owner to delete, never deleted here.

Locks, runtime-use leases, process ownership and cancellation stay the caller's (the engine's own install lock and
command runner), so this module starts no process and takes no lock.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Iterable, Optional

from shared import uv_runner, venv_integrity, venv_layout
from tts.engines import registry

RECEIPT_NAME = ".act-environment.json"
RECEIPT_SCHEMA = 1
RETIRED_NOTE_NAME = "RETIRED-READ-ME.txt"


def definition(key: str) -> registry.EngineDefinition:
    item = registry.definition(key)
    if item.placement != registry.PLACEMENT_ENGINE:
        raise ValueError(f"{key} has no environment of its own under {registry.ENGINE_ENVS_DIR}")
    return item


def project_dir(root, key: str) -> Path:
    return Path(root).joinpath(*definition(key).project.split("/"))


def env_dir(root, key: str) -> Path:
    definition(key)
    return uv_runner.engine_env(root, key)


def env_python(root, key: str, platform: Optional[str] = None) -> Path:
    return uv_runner.venv_python(env_dir(root, key), platform)


def check(root, key: str) -> None:
    """``uv_runner.TargetRefused`` unless the environment and the project are this copy's own."""
    uv_runner.check_target(root, env_dir(root, key), project=project_dir(root, key))


def lock_identity(root, key: str) -> Optional[dict]:
    """What a receipt binds the environment to: the engine project's definition and lock (line endings normalised)."""
    return uv_runner.lock_identity(root, project=project_dir(root, key))


# --------------------------------------------------------------------------------------------------------------------
#  Commands (run by the engine's own command runner, which owns stop and process ownership)
# --------------------------------------------------------------------------------------------------------------------
def venv_command(root, key: str, platform: Optional[str] = None) -> list[str]:
    return uv_runner.venv_command(root, env_dir(root, key), project=project_dir(root, key), platform=platform)


def sync_command(root, key: str, *, offline: bool = False, no_cache: bool = True,
                 reinstall: Iterable[str] = (), platform: Optional[str] = None) -> list[str]:
    return uv_runner.sync_command(root, env_dir(root, key), profile=uv_runner.PROFILE_USER, offline=offline,
                                  reinstall_packages=tuple(reinstall), no_cache=no_cache,
                                  project=project_dir(root, key), platform=platform)


def environment(root, operation: "uv_runner.Operation", key: str, *, offline: bool = False) -> dict:
    return uv_runner.environment(root, operation, offline=offline, env_dir=env_dir(root, key))


def offline_miss(lines: Iterable[str]) -> bool:
    """Whether uv's output says an offline run lacked a file (so a download would be needed)."""
    return any(marker in line.lower() for line in lines for marker in uv_runner.OFFLINE_MISSING_MARKERS)


# --------------------------------------------------------------------------------------------------------------------
#  Interpreter validation
# --------------------------------------------------------------------------------------------------------------------
def identity_problem(root, key: str, folder=None) -> str:
    """Why *folder* (default: the engine's environment) is not provably this copy's own uv-built environment on the
    managed interpreter, or ``""``. Identity is necessary, never sufficient: the engine's own health proof follows."""
    target = env_dir(root, key)
    folder = target if folder is None else Path(folder)
    if not venv_layout.same_path(folder, target):
        return "it is not at its own location (a moved or copied environment is never used)"
    linked = venv_layout.unsafe_component(root, folder)
    if linked is not None:
        return f"it is reached through a link or lies outside the app folder ({linked.name})"
    if not os.path.lexists(folder):
        return "it is not installed"
    if not folder.is_dir():
        return "it is not a folder"
    cfg = venv_layout.read_pyvenv_cfg(folder)
    if cfg is None:
        return "it has no readable pyvenv.cfg"
    if cfg.get("include-system-site-packages", "").lower() != "false":
        return "it is not isolated (include-system-site-packages is not false)"
    if not uv_runner.built_by_uv(folder):
        return "it was not built by uv"
    if not uv_runner.venv_python(folder).is_file():
        return "its interpreter is missing"
    problem = uv_runner.home_problem(root, folder)
    if problem:
        return problem
    if not uv_runner.managed_python(root).is_file():
        return "this copy's own Python is missing"
    if uv_runner.interpreter_build(root) != uv_runner.PYTHON_BUILD:
        return "this copy's own Python is not the pinned build"
    return ""


def record_damage(root, key: str) -> dict[str, str]:
    """Every installed file against its distribution's RECORD (presence, size, SHA-256): ``{distribution: why}``."""
    return venv_integrity.record_damage(env_dir(root, key))


# --------------------------------------------------------------------------------------------------------------------
#  Receipts
# --------------------------------------------------------------------------------------------------------------------
def receipt_path(root, key: str) -> Path:
    return env_dir(root, key) / RECEIPT_NAME


def _interpreter_record(root) -> dict:
    pins = uv_runner.pins()
    return {"home": str(uv_runner.managed_venv_home(root)), "build": uv_runner.interpreter_build(root),
            "archive_sha256": pins.python_sha256, "sys_version": pins.python_sys_version}


def read_receipt(root, key: str) -> Optional[dict]:
    try:
        payload = json.loads(receipt_path(root, key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != RECEIPT_SCHEMA or payload.get("engine") != key:
        return None
    return payload


def invalidate_receipt(root, key: str) -> None:
    """Withdraw the receipt before anything changes the environment (an interrupted sync never leaves one behind)."""
    try:
        receipt_path(root, key).unlink(missing_ok=True)
    except OSError:
        pass


def write_receipt(root, key: str, *, health: dict) -> dict:
    """Write the receipt. **Only after the sync, an empty :func:`record_damage` and the engine's health proof.**"""
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "engine": key,
        "manager": "uv",
        "uv": uv_runner.UV_VERSION,
        "lock": lock_identity(root, key),
        "interpreter": _interpreter_record(root),
        "profile": uv_runner.PROFILE_USER,
        "distributions": venv_integrity.installed_distributions(env_dir(root, key)),
        "health": dict(health),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path = receipt_path(root, key)
    temporary = path.with_name(f"{RECEIPT_NAME}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return receipt


def receipt_problem(root, key: str) -> str:
    """Why the environment's receipt does not vouch for it as it is now, or ``""``. Cheap: no process is started."""
    receipt = read_receipt(root, key)
    if receipt is None:
        return "it has no installation receipt (the last install did not finish)"
    if receipt.get("lock") != lock_identity(root, key):
        return "it was installed for a different version of its package lock"
    if receipt.get("uv") != uv_runner.UV_VERSION or receipt.get("profile") != uv_runner.PROFILE_USER:
        return "it was installed by a different uv or for a different profile"
    recorded, current = receipt.get("interpreter"), _interpreter_record(root)
    if not isinstance(recorded, dict) or any(recorded.get(k) != current[k] for k in current):
        return "the Python it was built on has changed since it was installed"
    return ""


# --------------------------------------------------------------------------------------------------------------------
#  Retirement of an earlier version's environment
# --------------------------------------------------------------------------------------------------------------------
def set_aside_dir(root, key: str) -> Path:
    return Path(root) / "files" / "runtime-data" / key / "set-aside"


def retire(root, key: str, folder, *, label: str, note: str) -> Path:
    """Move *folder* (an environment an earlier version made, already proved superseded by the caller) whole into
    ``files/runtime-data/<key>/set-aside/<label>-<UTC>-<id>/`` with a note, on the same volume (a rename: nothing is
    copied). Kept for the owner to delete; nothing is deleted here. Raises ``OSError`` when it cannot be moved
    (a file in use), leaving it exactly where it was."""
    folder = Path(folder)
    if venv_layout.unsafe_component(root, folder) is not None or not folder.is_dir():
        raise OSError(f"{folder} is not a folder of this app reached through no link")
    holder = set_aside_dir(root, key) / f"{label}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}"
    holder.mkdir(parents=True)
    destination = holder / folder.name
    try:
        os.replace(folder, destination)
    except OSError:
        try:
            holder.rmdir()
        except OSError:
            pass
        raise
    (holder / RETIRED_NOTE_NAME).write_text(note, encoding="utf-8")
    return destination
