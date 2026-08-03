"""Persistent application settings stored as JSON under ``files/runtime-data/settings.json``.

Tools and the launcher use this to remember things across runs: last-used input
and output folders, the selected voice / bitrate / timing preset, the launcher
window size, and which sidebar tool was open at last close. This file holds
**mutable user state only** — the committed root ``config.toml`` holds the
project's documented defaults, and nothing here ever writes to it.

The read API is intentionally tiny and forgiving: a missing or corrupt settings
file never raises and is never rewritten during a load, so a user who
hand-edited it into invalid JSON does not silently lose the file — they get
defaults plus a diagnostic (``last_load_error``) until they replace it or reset.

Writes are atomic (temp file in the same directory, then ``os.replace``) so a
crash mid-write cannot corrupt the file, and every writing function reports
success as a bool rather than failing silently.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from . import paths

# In-memory cache of the settings dict. Loaded lazily on first access.
_cache: dict[str, Any] | None = None

# Why the last load fell back to defaults, if it did. Read by the configuration
# layer so a malformed file can be reported once instead of failing silently.
_load_error: str | None = None

# Test/injection override for the settings file location. None = the real path.
_path_override: Path | None = None


def settings_path() -> Path:
    """The settings file currently in use."""
    return _path_override if _path_override is not None else paths.SETTINGS_FILE


def use_path(path: str | os.PathLike[str] | None) -> None:
    """Point the settings layer at *path*; ``None`` restores the real location.

    This is the injection seam tests use so a suite never reads, rewrites or
    resets the maintainer's actual preferences. It clears the cache so the next
    read comes from the new location.
    """
    global _path_override
    _path_override = Path(path) if path is not None else None
    invalidate()


def invalidate() -> None:
    """Drop the in-memory cache so the next read comes from disk."""
    global _cache, _load_error
    _cache = None
    _load_error = None


def last_load_error() -> str | None:
    """Technical detail of the last failed load, or ``None`` if it was clean."""
    _load()  # make sure a load has actually been attempted
    return _load_error


def _load() -> dict[str, Any]:
    global _cache, _load_error
    if _cache is not None:
        return _cache
    error: str | None = None
    path = settings_path()
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            error = f"expected a JSON object, found a {type(data).__name__}"
            data = {}
    except FileNotFoundError:
        # Not an error: the first run has no settings file yet.
        data = {}
    except (OSError, ValueError) as exc:
        # Malformed JSON or an unreadable file. Fall back to defaults and
        # remember why — but do NOT rewrite the file here; a load must never
        # destroy something the user may still want to fix by hand.
        error = f"{type(exc).__name__}: {exc}"
        data = {}
    _cache = data
    _load_error = error
    return _cache


def all_settings() -> dict[str, Any]:
    """Return a copy of the full settings dict."""
    return dict(_load())


def get(key: str, default: Any = None) -> Any:
    """Return the stored value for ``key`` or ``default`` if absent."""
    return _load().get(key, default)


def _write(data: dict[str, Any]) -> bool:
    """Atomically replace the settings file with *data*. True on success."""
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    # Write to a temp file in the same directory, then atomically replace.
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".settings_", suffix=".json", dir=str(path.parent))
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_name, path)
        return True
    except OSError:
        # Best-effort: clean up the temp file rather than leaving a stray one.
        # Losing a settings write is never worth crashing the app for, but the
        # caller is told it failed so it can say so instead of claiming success.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return False


def save() -> bool:
    """Write the in-memory settings to disk atomically. True on success."""
    return _write(_load())


def set(key: str, value: Any, *, autosave: bool = True) -> bool:
    """Store ``value`` under ``key``; persist immediately unless ``autosave`` is False.

    Returns whether the value reached disk (always True when ``autosave`` is
    False, since nothing was attempted).
    """
    _load()[key] = value
    return save() if autosave else True


def update(values: dict[str, Any], *, autosave: bool = True) -> bool:
    """Merge ``values`` into the settings; persist once unless ``autosave`` is False."""
    _load().update(values)
    return save() if autosave else True


def reset() -> bool:
    """Clear every stored preference, atomically. True on success.

    This is the whole of "Reset Preferences" at the data layer: the settings
    file becomes an empty object, so last-used tool, remembered dialog
    directories and any output-base override are gone and the application falls
    back to its documented defaults.

    It deliberately does **not** touch ``config.toml``, the virtual
    environment, downloaded models, portable binaries, logs, produced outputs or
    any source media — clearing downloaded data is a separate, differently
    confirmed action.
    """
    global _cache
    if not _write({}):
        return False
    _cache = {}
    return True
