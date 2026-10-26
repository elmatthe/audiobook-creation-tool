"""Contain Numba's compiled cache before collection imports any numerical library."""

import atexit
import os
import sys
import tempfile
from pathlib import Path


def install():
    """Keep JIT and disk caching enabled, with no installed-library locator fallback.

    The directory and environment outlive pytest teardown. Independent child
    interpreters need their own explicit environment/qualification.
    """
    if "numba" in sys.modules:
        raise RuntimeError("Numba cache containment must precede the first numba import")
    parent = Path(__file__).resolve().parents[1] / "dev-work"
    parent.mkdir(exist_ok=True)
    folder = tempfile.TemporaryDirectory(prefix="pytest-numba-", dir=parent)
    values = {"NUMBA_CACHE_DIR": folder.name, "NUMBA_CACHE_LOCATOR_CLASSES": "UserProvidedCacheLocator"}
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)

    def restore():
        try:
            folder.cleanup()
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    atexit.register(restore)
    return Path(folder.name)
