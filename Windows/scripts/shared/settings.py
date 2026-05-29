"""Persistent application settings stored as JSON under ``resources/settings.json``.

Tools and the launcher use this to remember things across runs: last-used input
and output folders, the selected voice / bitrate / timing preset, the launcher
window size, and which sidebar tool was open at last close.

The API is intentionally tiny and forgiving — a missing or corrupt settings file
never raises; it just falls back to defaults. Writes are atomic (temp file +
replace) so a crash mid-write can't corrupt the file.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from . import paths

# In-memory cache of the settings dict. Loaded lazily on first access.
_cache: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        with paths.SETTINGS_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        # Missing file or malformed JSON — start fresh rather than crash.
        data = {}
    _cache = data
    return _cache


def all_settings() -> dict[str, Any]:
    """Return a copy of the full settings dict."""
    return dict(_load())


def get(key: str, default: Any = None) -> Any:
    """Return the stored value for ``key`` or ``default`` if absent."""
    return _load().get(key, default)


def save() -> None:
    """Write the in-memory settings to disk atomically."""
    data = _load()
    paths.resources_dir()  # ensure resources/ exists
    # Write to a temp file in the same directory, then atomically replace.
    fd, tmp_name = tempfile.mkstemp(
        prefix=".settings_", suffix=".json", dir=str(paths.RESOURCES_DIR)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_name, paths.SETTINGS_FILE)
    except OSError:
        # Best-effort: clean up the temp file and give up silently. Losing a
        # settings write is never worth crashing the app for.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def set(key: str, value: Any, *, autosave: bool = True) -> None:
    """Store ``value`` under ``key``; persist immediately unless ``autosave`` is False."""
    _load()[key] = value
    if autosave:
        save()


def update(values: dict[str, Any], *, autosave: bool = True) -> None:
    """Merge ``values`` into the settings; persist once unless ``autosave`` is False."""
    _load().update(values)
    if autosave:
        save()
