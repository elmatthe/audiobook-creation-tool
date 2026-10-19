"""Give espeak-ng a path to its bundled data that its own buffer can hold.

Kokoro's English G2P (``misaki`` -> ``phonemizer-fork`` -> ``libespeak-ng``) reads
its phoneme tables from a directory handed to ``espeak_Initialize``. eSpeak NG
copies that argument into a **fixed 160-byte buffer** (``N_PATH_HOME`` in
``speech.h``) as ``"<given path>/espeak-ng-data"``. Anything longer is silently
truncated, the truncated directory does not exist, and the library falls back to
the data path that was compiled into it — on a PyPI wheel that is the path from
the *build machine*, e.g.
``/Users/runner/work/espeakng-loader/.../espeak-ng-data``. It then fails to open
``phontab`` and **calls ``exit()``**, so the Python ``try``/``except`` that
upstream wraps the fallback in never runs and the whole process dies.

Nothing is wrong with the installed wheel: ``espeakng_loader.get_data_path()``
points at a complete data directory. What overflows the buffer is where the
*project* is installed. Measured on the macOS gate machine:

* ``…/audiobook-creation-tool-v0.6.x/.venv/lib/python3.12/site-packages/espeakng_loader``
  is 147 characters, and 147 + ``len("/espeak-ng-data")`` = 162 > 160;
* the same call succeeds from a short directory, and the boundary sits exactly
  where the arithmetic says: a root of 144 characters works, 145 does not.

So this module hands eSpeak a **short** path to the **same** bundled data — a
link, never a copy, so the wheel stays the only source of the data — and only
when the real one does not fit. On an installation whose paths already fit
(which is most of them, and every one that works today) it does nothing at all.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from shared import paths

#: eSpeak NG's ``N_PATH_HOME``. The library ``snprintf``s ``"%s/espeak-ng-data"``
#: into a buffer this size, so the usable budget is one byte smaller.
PATH_HOME_LIMIT = 160

#: The directory name eSpeak NG appends to whatever path it is given.
DATA_DIR_NAME = "espeak-ng-data"

#: Where a short-path link is placed inside the already-ignored runtime data.
LINK_PARENT_NAME = "espeak-ng"

#: Name of the short-root directory used when even the runtime data is too deep.
TEMP_ROOT_NAME = "act-espeak-ng"

#: Set once per process so repeated pipeline builds do no filesystem work.
_configured: str | None = None
_configured_for: str | None = None


def root_fits(root: object) -> bool:
    """Whether eSpeak NG can hold ``<root>/espeak-ng-data`` without truncating."""
    return len(f"{os.fspath(root)}{os.sep}{DATA_DIR_NAME}") < PATH_HOME_LIMIT


def bundled_data_dir(loader: object = None) -> Path | None:
    """The installed wheel's own ``espeak-ng-data`` directory, or ``None``.

    Discovered from the package, never hardcoded: a machine that has no
    ``espeakng-loader`` — or a wheel whose data is genuinely missing — answers
    ``None`` here and every caller then leaves the stack exactly as it found it.
    """
    module = loader
    if module is None:
        try:
            import espeakng_loader as module  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001 - an absent optional wheel is an answer
            return None
    try:
        data = Path(module.get_data_path())
    except Exception:  # noqa: BLE001 - the loader raises when its data is missing
        return None
    return data if (data / "phontab").exists() else None


def candidate_roots() -> tuple[Path, ...]:
    """Short-root candidates, most project-owned first.

    The runtime-data directory is the project's own scratch area — already
    ignored by Git, already excluded from release packages, and already what the
    documented "uninstall" deletes. The temporary directory is the fallback for a
    checkout so deep that even that path cannot hold the name.
    """
    return (
        paths.RESOURCES_DIR / LINK_PARENT_NAME,
        Path(tempfile.gettempdir()) / TEMP_ROOT_NAME,
    )


def _link_to(target: Path, link_path: Path) -> bool:
    """Point ``link_path`` at ``target`` without copying it. Never raises."""
    try:
        if link_path.is_symlink() or link_path.exists():
            if link_path.is_symlink() and Path(os.readlink(link_path)) == target:
                return True
            if link_path.is_symlink():
                link_path.unlink()
            elif link_path.is_dir():
                # A junction (Windows) reports as a directory; replace it only if
                # it does not already lead to the same data.
                if (link_path / "phontab").exists():
                    return True
                return False
        link_path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link_path, target_is_directory=True)
        return True
    except OSError:
        pass
    if sys.platform == "win32":
        # A directory junction needs no privilege, where a symlink does.
        try:
            import _winapi

            link_path.parent.mkdir(parents=True, exist_ok=True)
            _winapi.CreateJunction(str(target), str(link_path))
            return True
        except (ImportError, AttributeError, OSError):
            return False
    return False


def short_root(data_dir: Path, candidates=None) -> Path | None:
    """A root eSpeak NG can hold, whose ``espeak-ng-data`` is *data_dir*."""
    for root in (candidate_roots() if candidates is None else candidates):
        root = Path(root)
        if not root_fits(root):
            continue
        if _link_to(data_dir, root / DATA_DIR_NAME) and (
                root / DATA_DIR_NAME / "phontab").exists():
            return root
    return None


def configure(*, data_dir: Path | None = None, candidates=None,
              environ: dict | None = None) -> str | None:
    """Make the bundled eSpeak data reachable, and return the path handed over.

    Returns the directory eSpeak NG will read (its parent-of-data form), or
    ``None`` when there is nothing to do or nothing that can be done. Safe to
    call repeatedly: after the first success it only re-states the answer.

    Three outcomes, all truthful:

    * **no eSpeak data installed** — ``None``, and nothing is touched, so a venv
      without Kokoro behaves exactly as it does today;
    * **the wheel's own path already fits** — ``None``, and nothing is touched,
      which is every installation that works today, Windows included;
    * **the path is too long** — a short link is made, and both the environment
      and ``phonemizer``'s class-level override are pointed at it.
    """
    global _configured, _configured_for

    data = bundled_data_dir() if data_dir is None else Path(data_dir)
    if data is None:
        return None
    if _configured is not None and _configured_for == str(data):
        return _configured
    if root_fits(data.parent) and root_fits(data):
        # The library can hold what misaki already gives it; leave it alone.
        return None

    root = short_root(data, candidates=candidates)
    if root is None:
        return None

    env = os.environ if environ is None else environ
    # Process-local, and deliberately unconditional: eSpeak reads this only when
    # it is given no explicit path, and pointing it at the link keeps the answer
    # the *bundled* data in every route — including a machine where something
    # else has aimed the variable at a system eSpeak installation. It repairs any
    # consumer that does not go through phonemizer, and changes nothing outside
    # this process.
    env["ESPEAK_DATA_PATH"] = str(root)
    _set_phonemizer_data_path(str(root))
    _configured, _configured_for = str(root), str(data)
    return _configured


def _set_phonemizer_data_path(root: str) -> None:
    """Override the long path ``misaki`` installs on ``phonemizer``'s wrapper.

    ``misaki.espeak`` sets it at import time to the wheel's own directory, and an
    explicit path beats the environment variable inside ``phonemizer``, so the
    override has to be applied after that import and before the first wrapper is
    built. The library it points at is not changed — only how the data is named.
    """
    try:
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
    except Exception:  # noqa: BLE001 - no phonemizer means nothing to override
        return
    try:
        EspeakWrapper.set_data_path(root)
    except Exception:  # noqa: BLE001 - a renamed setter must not break synthesis
        pass


def reset_cache() -> None:
    """Forget the per-process answer. For tests; production calls it never."""
    global _configured, _configured_for
    _configured = _configured_for = None
