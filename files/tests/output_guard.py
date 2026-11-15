"""Fail closed on where a test's run publishes: the test's own folder, never the real default output location.

v0.8.x P1B, after MAC-032. ``shared.config`` caches one effective configuration snapshot per process
(``config.get_effective``), and under the focused gate one pytest process runs many test files. A test that sets its
own output base through ``shared.settings`` after an earlier test has cached the snapshot is therefore still resolved
against the earlier snapshot, whose base is the default: the user's real ``~/Downloads/Audiobook-Creation-Tool-Outputs``.
That is how MAC-032's real MP3 Combine published there (2d02485 fixed that one test). ``conftest`` sends the settings
file and the logs to scratch for the session, but not the default output folder -- the default is exactly what a stale
snapshot falls back to, so moving it would only hide the fault.

Two layers, for any test that runs a real tool:

* :func:`require_isolated_output_base`, before the run starts. It resolves the base exactly as the run will
  (``output_paths.resolve_output_base``, with the process's cached snapshot as it stands: a stale snapshot is caught,
  never quietly refreshed) and raises :class:`UnsafeOutputBase` unless that base is the test's own folder and neither
  lies in a real location (the default output folder, the Downloads folder, the repository's ``files/runtime-data``).
  It reads; it creates nothing.
* :func:`real_output_locations_refused`, around the run. ``write_tripwire`` refuses (``PermissionError``, before the
  write) any write into the real default output folder or the real Downloads folder by anything in the process, on any
  thread, and the block fails afterwards even when the code under test caught the refusal and carried on.

"Real" means what ``shared.config`` and ``shared.paths`` compute when asked, from the home folder this process sees.
That is also the seam a test injects a stand-in home through (``shared.paths.downloads_dir``). Importable without
pytest.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

import write_tripwire
from shared import config, output_paths, paths

#: How many recorded attempts a refusal names before it summarises the rest.
_SHOWN = 5


class UnsafeOutputBase(AssertionError):
    """A run would publish somewhere other than the test's own folder, or into a real output location."""


def real_default_output_base() -> Path:
    """The app's default output folder, ``<Downloads>/Audiobook-Creation-Tool-Outputs``. Computed, never created."""
    return Path(config.default_output_base())


def real_downloads_dir() -> Path:
    """The user's Downloads folder as ``shared.paths`` finds it. Computed, never created.

    Where there is no Downloads folder ``shared.paths`` falls back to the home folder itself. Refusing all of that
    would refuse every test tree below the home folder (this repository's among them), so the Downloads folder that
    would be there is named instead; the default output folder beside it is guarded on its own.
    """
    found = Path(paths.downloads_dir())
    return found if found.name.casefold() == "downloads" else found / "Downloads"


def real_runtime_data_dir() -> Path:
    """The repository's application-owned state, ``files/runtime-data``."""
    return paths.REPO_ROOT / "files" / "runtime-data"


def real_output_locations() -> tuple[tuple[str, Path], ...]:
    """Every place no test's run may publish into, each with the name a refusal gives it."""
    return (
        ("the real default output folder", real_default_output_base()),
        ("the real Downloads folder", real_downloads_dir()),
        ("the repository's files/runtime-data", real_runtime_data_dir()),
    )


# The containment rule is the tripwire's own, so "inside" means the same thing to both layers: lexically, or once
# links on the existing part of the path are resolved (a scratch folder linked into Downloads is inside Downloads).
def _forms(path: Path) -> set[str]:
    lexical = write_tripwire._norm(os.fspath(path))
    return {lexical, write_tripwire._resolved(lexical)}


def _inside(candidate: Path, root: Path) -> bool:
    roots = tuple(_forms(root))
    return any(write_tripwire._inside(form, roots) for form in _forms(candidate))


def _same(first: Path, second: Path) -> bool:
    """The same folder by name. Strict on purpose: a run that reaches it only through a link is not 'the same'."""
    return write_tripwire._norm(os.fspath(first)) == write_tripwire._norm(os.fspath(second))


def _stale_hint(expected: Path, effective) -> str:
    """Say so when it is the process's cached snapshot that is out of date: a fresh load (which writes nothing and
    leaves the cache alone) would already name the test's folder."""
    if effective is not None:
        return ""
    try:
        fresh = output_paths.resolve_output_base(config.load())
    except Exception:  # a diagnosis must never mask the refusal itself
        return ""
    if not _same(fresh, expected):
        return ""
    return (" -- the process's cached configuration snapshot predates this test's output base; call "
            "shared.config.invalidate() after setting it, then check again")


def require_isolated_output_base(expected: str | os.PathLike[str], *, effective=None) -> Path:
    """The base a run will publish into, proven to be *expected* and outside every real location; else
    :class:`UnsafeOutputBase`.

    Resolved exactly as the run resolves it, ``output_paths.resolve_output_base(effective)``: with no *effective*, the
    process's cached snapshot as it stands. The cache is deliberately not invalidated first. A snapshot older than the
    test's own base is the very fault to catch; refreshing it here would hide it from the test while a later reader
    could still pick up a stale one. Reads only: nothing is created, and the cache is left exactly as it was found.
    """
    expected = Path(expected)
    resolved = output_paths.resolve_output_base(effective)
    problems: list[str] = []
    candidates = [("this test's folder", expected)]
    if not _same(resolved, expected):
        problems.append(f"the run would publish into {resolved}, not this test's own folder {expected}"
                        + _stale_hint(expected, effective))
        candidates.append(("the resolved output base", resolved))
    for label, root in real_output_locations():
        for role, candidate in candidates:
            if _inside(candidate, root):
                problems.append(f"{role} {candidate} is inside {label} ({root})")
    if problems:
        raise UnsafeOutputBase("refusing to start a run: " + "; ".join(problems))
    return resolved


def _attempted(attempts: list[tuple[str, str]]) -> str:
    shown = "; ".join(f"{event} {path}" for event, path in attempts[:_SHOWN])
    more = f" (and {len(attempts) - _SHOWN} more)" if len(attempts) > _SHOWN else ""
    return f"a write into a real output location was attempted (refused before anything changed): {shown}{more}"


@contextmanager
def real_output_locations_refused(extra: Iterable[str | os.PathLike[str]] = ()) -> Iterator[tuple[Path, ...]]:
    """Refuse, for the duration, any write into the real default output folder and the real Downloads folder (and
    *extra*) by anything in this process; then raise :class:`UnsafeOutputBase` if one was even attempted.

    The refusal is ``write_tripwire``'s: ``PermissionError`` before the write, on whichever thread makes it. The code
    under test may catch that -- a tool turns a failed run reservation into an error message and no run -- so the block
    fails afterwards whenever an attempt was recorded, naming it, and chains whatever the block itself raised. Writes
    anywhere else (the test's own folders) are untouched. Yields the protected roots.
    """
    roots = (real_default_output_base(), real_downloads_dir(), *(Path(root) for root in extra))
    attempts: list[tuple[str, str]] = []
    try:
        with write_tripwire.armed(roots) as attempts:
            yield roots
    except Exception as exc:
        if attempts:
            raise UnsafeOutputBase(_attempted(attempts)) from exc
        raise
    if attempts:
        raise UnsafeOutputBase(_attempted(attempts))
