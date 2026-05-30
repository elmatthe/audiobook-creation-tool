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


# --------------------------------------------------------------------------- #
# Output-folder resolution (v0.1.1)
# --------------------------------------------------------------------------- #
#
# Every transforming tool delivers its results to an auto-named subfolder of the
# user's Downloads directory: ``Downloads/<ToolName>-N``. The ``-N`` suffix is the
# lowest positive integer that does not already collide with an existing folder
# *at the moment it is computed* — and each tool computes it exactly once, at
# build_ui() time, so the number stays fixed for the whole session (recomputing
# per-save would shift the number mid-session). The folder itself is created
# lazily on the first successful write, so merely opening a tool never litters
# Downloads with empty folders.
#
# Canonical tool-name slugs (keep these stable — they are user-visible folder
# names). One per tool, matching the launcher sidebar:
TOOL_SLUGS: dict[str, str] = {
    "tts": "TTS-Audiobook",
    "m4b_converter": "M4B-Converter",
    "mp3_tool": "MP3-Tool",
    "m4b_maker": "M4B-Maker",
    "cover": "Cover-Image",
    "m4b_metadata": "M4B-Metadata",
}


def downloads_dir() -> Path:
    """Resolve the current user's Downloads folder cross-platform.

    Falls back to the home directory if Downloads does not exist.
    """
    home = Path.home()
    candidate = home / "Downloads"
    return candidate if candidate.exists() else home


def next_output_dir(tool_name: str, *, create: bool = False) -> Path:
    """Return ``Downloads/<tool_name>-N`` for the lowest free positive ``N``.

    ``N`` starts at 1 and increments only to avoid a folder that already exists
    at call time. With ``create=True`` the folder (and parents) is created;
    otherwise the path is returned without touching the filesystem.

    ``tool_name`` is the short tool slug (see :data:`TOOL_SLUGS`), e.g.
    ``"M4B-Metadata"`` or ``"TTS-Audiobook"``.
    """
    base = downloads_dir()
    n = 1
    while (base / f"{tool_name}-{n}").exists():
        n += 1
    target = base / f"{tool_name}-{n}"
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def avoid_input_overwrite(out_path: Path, inputs) -> Path:
    """Guarantee a transforming tool never writes over one of its own inputs.

    Returns ``out_path`` unchanged unless it resolves to one of the given input
    files — in which case it returns the first ``"<stem> (N)<suffix>"`` sibling
    that is neither an input nor an already-existing file. This is the
    input==output collision guard used when a tool's output folder happens to be
    the same folder the inputs were loaded from.
    """
    resolved_inputs: set[Path] = set()
    for p in inputs:
        try:
            resolved_inputs.add(Path(p).resolve())
        except OSError:
            pass

    def is_input(p: Path) -> bool:
        try:
            return p.resolve() in resolved_inputs
        except OSError:
            return False

    if not is_input(out_path):
        return out_path

    parent, stem, suffix = out_path.parent, out_path.stem, out_path.suffix
    n = 1
    while True:
        candidate = parent / f"{stem} ({n}){suffix}"
        if not is_input(candidate) and not candidate.exists():
            return candidate
        n += 1


def resources_dir() -> Path:
    return ensure_dir(RESOURCES_DIR)


def logs_dir() -> Path:
    return ensure_dir(LOGS_DIR)


def bin_dir() -> Path:
    return ensure_dir(BIN_DIR)
