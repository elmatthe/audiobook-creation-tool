"""Single source of truth for project-relative paths.

Every path in the application derives from this module so that no script ever
depends on the current working directory or hardcodes an absolute path.

Layout (per OS folder, e.g. ``Windows/`` or ``MacOS/``)::

    <os_root>/
        scripts/
            shared/paths.py   <- this file
            tts/
            mp3_tools/
        resources/
            logs/
            bin/              <- portable ffmpeg, if bundled
            settings.json
        requirements.txt
"""

from __future__ import annotations

from pathlib import Path

# This file lives at <os_root>/scripts/shared/paths.py
_THIS = Path(__file__).resolve()

SHARED_DIR: Path = _THIS.parent
SCRIPTS_DIR: Path = SHARED_DIR.parent
OS_ROOT: Path = SCRIPTS_DIR.parent

TTS_DIR: Path = SCRIPTS_DIR / "tts"
MP3_TOOLS_DIR: Path = SCRIPTS_DIR / "mp3_tools"

RESOURCES_DIR: Path = OS_ROOT / "resources"
LOGS_DIR: Path = RESOURCES_DIR / "logs"
BIN_DIR: Path = RESOURCES_DIR / "bin"
SETTINGS_FILE: Path = RESOURCES_DIR / "settings.json"

REQUIREMENTS_FILE: Path = OS_ROOT / "requirements.txt"


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if missing and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def resources_dir() -> Path:
    return ensure_dir(RESOURCES_DIR)


def logs_dir() -> Path:
    return ensure_dir(LOGS_DIR)


def bin_dir() -> Path:
    return ensure_dir(BIN_DIR)
