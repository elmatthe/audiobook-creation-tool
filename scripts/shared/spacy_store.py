"""spacy_store.py — the approved spaCy English wheel, and the verified copy of it kept beside the models.

Standard library only, under ``shared/`` on purpose: ``bootstrap`` (which must never import anything under ``tts``, so
a main-environment repair can never reach the Qwen3 installer) reinstalls the model from the kept copy after it
rebuilds ``.venv``, and ``tts.model_assets`` / the optional-setup worker use the same pins and the same command.

The model is a pip package inside ``.venv``. Every other Kokoro file lives under ``files/`` and survives a rebuilt
``.venv``; keeping this 12.8 MB wheel there too means a repair gets the model back offline instead of downloading it.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Optional

#: The owner-approved spaCy English model (ruling 2026-10-25): this wheel only, size- and hash-verified before pip sees
#: it, installed with ``--no-deps`` and hash enforcement into a spaCy ``>=3.8.0,<3.9.0`` that is never upgraded for it.
SPACY_ENGLISH = "en_core_web_sm"
SPACY_ENGLISH_VERSION = "3.8.0"
SPACY_WHEEL_NAME = "en_core_web_sm-3.8.0-py3-none-any.whl"
SPACY_WHEEL_URL = ("https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/"
                   + SPACY_WHEEL_NAME)
SPACY_WHEEL_SIZE = 12_806_118
SPACY_WHEEL_SHA256 = "1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"
SPACY_COMPATIBLE = ((3, 8, 0), (3, 9, 0))  # >= first, < second


def store_dir(root: Path) -> Path:
    """``files/runtime-data/models/spacy`` of the installation at ``root``."""
    return Path(root) / "files" / "runtime-data" / "models" / "spacy"


def _is_link(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def kept_wheel(root: Path, *, size: Optional[int] = None, sha256: Optional[str] = None) -> Optional[Path]:
    """The kept wheel, only if it is a plain regular file of exactly the approved size and SHA-256; otherwise None.

    No component below ``root`` may be a link or junction. ``size``/``sha256`` default to the approved pins.
    """
    size = SPACY_WHEEL_SIZE if size is None else size
    sha256 = SPACY_WHEEL_SHA256 if sha256 is None else sha256
    root = Path(os.path.abspath(str(root)))
    path = store_dir(root) / SPACY_WHEEL_NAME
    walked = root
    for part in path.parts[len(root.parts):]:
        walked = walked / part
        if _is_link(walked):
            return None
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_size != size:
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return None
    return path if digest.hexdigest() == sha256 else None


def requirement_line(wheel: Path, sha256: Optional[str] = None) -> str:
    """A requirement naming exactly this local file, with its hash enforced."""
    return f"{SPACY_ENGLISH} @ {Path(wheel).resolve().as_uri()} --hash=sha256:{sha256 or SPACY_WHEEL_SHA256}\n"


def offline_install_command(python: Path, requirement: Path) -> list[str]:
    """pip reads only the one verified local wheel the requirement file names: no index, no dependencies, its hash
    enforced a second time. The single command both the setup worker and bootstrap's offline restore use."""
    return [str(python), "-m", "pip", "install", "--isolated", "--require-virtualenv", "--no-deps", "--no-index",
            "--require-hashes", "--no-input", "--disable-pip-version-check", "--no-cache-dir",
            "--no-warn-script-location", "--progress-bar", "off", "-r", str(requirement)]
