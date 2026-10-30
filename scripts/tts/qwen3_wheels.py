"""qwen3_wheels.py — the Qwen3 engine's packages: fetched one verified wheel at a time, then installed offline.

v0.7.0. pip used to reach the package indexes itself, so the bytes an engine install would fetch were only an estimate
and nothing outside pip could bound them. Now every package is the exact artifact of the reviewed manifest
(``scripts/qwen3-artifacts.json``, checked by :mod:`tts.qwen3_package_manifest` against its code anchor): its publisher
URL (PyPI, or PyTorch for torch/torchaudio), size and SHA-256. sox is the accepted derivative wheel, fetched from its
commit-pinned supply URL (never the source archive, which would need a build).

* :func:`fetch` downloads only the wheels not already verified here, through ``qwen3_setup.download_file`` (resumes a
  ``.part``, accepts a file only at its exact size and SHA-256) and the caller's opener, so a confirmed byte budget can
  be enforced before each transfer. A verified wheel is recorded by size, modification time and hash, so a retry never
  fetches or hashes it again.
* :func:`install_command` is pip reading only those local files: ``--no-index --require-hashes --no-deps
  --only-binary=:all:`` through ``qwen3_packages.OFFLINE_BOOTSTRAP``, which refuses network and subprocesses inside pip.
* :func:`discard` gives the space back once the engine is installed and proved.

Everything lives in ``files/runtime-data/qwen3/cache/wheels/`` (inside the app's folder, never the user profile).
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from tts import qwen3_package_manifest as qm
from tts import qwen3_runtime as rt

RECORD_NAME = "verified.json"
LOCK_NAME = "requirements.txt"


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
    """All 89 wheels of the engine, in manifest order, each with the one URL it may come from."""
    manifest = reviewed()
    sox_url = qm.published_sox_source(manifest)["url"]
    return tuple(Wheel(a.name, a.filename, sox_url if a.name == "sox" else a.source_url, a.size, a.sha256)
                 for a in manifest.wheels)


def urls() -> list[str]:
    return [w.url for w in wheels()]


def total_bytes() -> int:
    return sum(w.size for w in wheels())


def wheel_dir() -> Path:
    return rt.cache_root() / "wheels"


def _record_path() -> Path:
    return wheel_dir() / RECORD_NAME


def _load_record() -> dict:
    try:
        data = json.loads(_record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_record(record: dict) -> None:
    path = _record_path()
    tmp = path.with_name(path.name + ".tmp")
    rt.remove_entry(tmp)
    tmp.write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _stat_regular(path: Path) -> Optional[os.stat_result]:
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return st if stat.S_ISREG(st.st_mode) else None


def _recorded(wheel: Wheel, record: dict) -> bool:
    st = _stat_regular(wheel_dir() / wheel.filename)
    return st is not None and st.st_size == wheel.size and \
        record.get(wheel.filename) == [wheel.size, st.st_mtime_ns, wheel.sha256]


def missing() -> list[Wheel]:
    """The wheels that would have to be downloaded now (anything not recorded as verified here)."""
    record = _load_record()
    return [w for w in wheels() if not _recorded(w, record)]


def missing_bytes() -> int:
    return sum(w.size for w in missing())


def fetch(*, opener=None, progress: Optional[Callable[[int, int, str], None]] = None,
          cancel_check: Optional[Callable[[], bool]] = None, sleep=None) -> int:
    """Download every wheel not yet verified here. ``progress(done, total, message)``; returns the bytes fetched.

    A file already present at the right size is hashed first and kept if it is the approved one, so an interrupted
    earlier run is reused rather than fetched again.
    """
    from tts import qwen3_setup as setup

    folder = wheel_dir()
    folder.mkdir(parents=True, exist_ok=True)
    record = _load_record()
    todo = [w for w in wheels() if not _recorded(w, record)]
    total = sum(w.size for w in todo)
    done = 0
    for wheel in todo:
        setup._check_cancel(cancel_check)
        target = folder / wheel.filename
        st = _stat_regular(target)
        if not (st is not None and st.st_size == wheel.size and rt.sha256_file(target) == wheel.sha256):
            if os.path.lexists(target):
                rt.remove_entry(target)
            shown = {"done": done}

            def on_bytes(count: int, name: str = wheel.filename) -> None:
                shown["done"] += count
                if progress is not None:
                    progress(shown["done"], total, f"Downloading {name}")

            kwargs = {"sleep": sleep} if sleep is not None else {}
            setup.download_file(wheel.url, target, wheel.size, wheel.sha256, opener=opener, progress=on_bytes,
                                cancel_check=cancel_check, **kwargs)
        done += wheel.size
        st = _stat_regular(target)
        if st is None:
            raise setup.SetupError(f"{wheel.filename} disappeared after it was downloaded.")
        record[wheel.filename] = [wheel.size, st.st_mtime_ns, wheel.sha256]
        _save_record(record)
        if progress is not None:
            progress(done, total, f"Verified {wheel.filename}")
    return total


def install_command(python: Path) -> tuple[list[str], Path]:
    """The offline pip command for *python* and the folder it must run in. Every wheel must already be verified."""
    from tts import qwen3_packages
    from tts import qwen3_setup as setup

    if missing():
        raise setup.SetupError("Some Qwen3 packages are not downloaded and verified yet; nothing was installed.")
    folder = wheel_dir()
    lock = folder / LOCK_NAME
    rt.remove_entry(lock)
    lock.write_bytes(qm.effective_lock(reviewed()))
    paths = [(folder / w.filename, w.sha256) for w in wheels()]
    return qwen3_packages._pip_command(python, folder, lock, paths), folder


def discard() -> None:
    """Remove the downloaded wheels (after a proved install). Best effort."""
    shutil.rmtree(wheel_dir(), ignore_errors=True)
