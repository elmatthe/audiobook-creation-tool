"""qwen3_wheels.py — the Qwen3 engine's packages as the reviewed manifest states them: exact names, files and sizes.

v0.8.2 Phase 5A: the engine is installed by uv from its locked project (``scripts/tts/engines/qwen3/uv.lock``, through
``tts.qwen3_setup``), which downloads and hash-checks exactly the locked artifacts itself. The reviewed manifest
(``scripts/qwen3-artifacts.json``, checked by :mod:`tts.qwen3_package_manifest` against its code anchor) stays the
parity reference of that lock (``files/tests/test_qwen3_uv_project.py``) and the source of the download size a person
is shown before anything is fetched: the PyTorch index publishes no sizes, so ``uv.lock`` has none for torch and
torchaudio. sox is ACT's own derivative wheel (its commit-pinned supply URL), never the source archive.

What v0.7.0 to v0.8.1 did here -- fetch every wheel into ``files/runtime-data/qwen3/cache/wheels/`` and install them with
pip -- is retired; :func:`discard_earlier_store` gives the space of such a store back once uv has installed the engine.
"""

from __future__ import annotations

import functools
import shutil
from dataclasses import dataclass
from pathlib import Path

from tts import qwen3_package_manifest as qm
from tts import qwen3_runtime as rt

#: The record file the earlier wheel store kept beside its wheels (how that store is recognised as this app's).
EARLIER_RECORD_NAME = "verified.json"


@dataclass(frozen=True)
class Wheel:
    name: str
    filename: str
    url: str
    size: int
    sha256: str


@functools.lru_cache(maxsize=1)
def reviewed() -> qm.ReviewedManifest:
    """The reviewed manifest; refused (``ManifestError``) if the file or the lock differs from the reviewed content."""
    folder = Path(__file__).resolve().parents[1]
    return qm.load_manifest((folder / "qwen3-artifacts.json").read_bytes(),
                            (folder / "qwen3-requirements.txt").read_bytes())


def wheels() -> tuple[Wheel, ...]:
    """All 89 wheels of the engine, in manifest order, each with the one URL it comes from."""
    manifest = reviewed()
    sox_url = qm.published_sox_source(manifest)["url"]
    return tuple(Wheel(a.name, a.filename, sox_url if a.name == "sox" else a.source_url, a.size, a.sha256)
                 for a in manifest.wheels)


def total_bytes() -> int:
    """What installing the engine downloads: every wheel, every time (no Qwen3 package cache is kept)."""
    return sum(w.size for w in wheels())


def earlier_store() -> Path:
    """``files/runtime-data/qwen3/cache/wheels/``: where v0.7.0 to v0.8.1 kept verified wheels between attempts."""
    return rt.cache_root() / "wheels"


def discard_earlier_store() -> bool:
    """Remove that store -- only when it is this app's (its ``verified.json`` record is there) and reached through no
    link -- after uv has installed the engine: nothing reads it any more. Best effort; True when it was removed."""
    folder = earlier_store()
    try:
        if rt.is_link(folder) or rt.link_below_root(folder) is not None or not (folder / EARLIER_RECORD_NAME).is_file():
            return False
    except OSError:
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return not folder.exists()
