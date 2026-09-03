"""Shared pytest setup: make scripts/Universal (the import root) importable.

These are behaviour-preservation smoke tests: fast, deterministic, no network
(Edge TTS / Kokoro downloads are never touched). Fixtures that need real media
live in files/test-files/ (gitignored, local-only) and tests that use them skip
when the folder is absent.

They must also leave the machine exactly as they found it — see the autouse
guard at the bottom of this file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_ROOT = REPO_ROOT / "scripts" / "Universal"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))


# --------------------------------------------------------------------------- #
#  Production-state isolation guard  (PRE-PLAN-6 Phase 1, finding L1)
#
#  A full suite run used to rewrite the developer's REAL
#  ``.venv/.requirements-state.json``: three tests drove ``run_setup`` with every
#  install step stubbed but left ``VENV_DIR`` pointing at the real checkout, so
#  the stamp at the end of setup landed in the real environment. It was harmless
#  only because the fingerprint happened to match — a suite that can write the
#  real stamp can write a FALSE one, which is precisely the invariant the
#  requirements work exists to protect. Importing ``bootstrap`` also created and
#  appended to the real dated setup log, because the shared ``SetupLog`` opened
#  its file at construction.
#
#  Both are fixed at the source. This guard is what stops either from coming
#  back silently.
#
#  It is split by cost, deliberately. The requirements stamp is a single file, so
#  it is checked around every test and a violation names the exact test. The log
#  directory is checked once per session instead: enumerating ~80 entries either
#  side of ~5100 tests is over ten thousand directory scans, and paying that per
#  test measurably slowed the run — enough to push a already-marginal
#  five-second thread-start wait in ``test_job_ui.py`` over its bound. The
#  trade-off is that a log leak is reported for the session rather than
#  attributed to one test; the redirect above makes that the unlikely case.
# --------------------------------------------------------------------------- #
_GUARDED_PATHS = {
    "the real requirements stamp": REPO_ROOT / ".venv" / ".requirements-state.json",
    "the real setup log directory": REPO_ROOT / "files" / "runtime-data" / "logs",
}
_PER_TEST_GUARDED = ("the real requirements stamp",)


# Captured at import, before any test can monkeypatch them. The guard has to
# observe the real filesystem: a test that fakes ``os.scandir`` to prove some
# walk tolerates a vanishing file must not also fake what the guard sees.
_REAL_SCANDIR = os.scandir
_REAL_STAT = os.stat


def _fingerprint(path: Path):
    """(size, mtime_ns) for a file, or the sorted equivalent for a directory.

    A missing path fingerprints as ``None``, so a machine with no ``.venv`` and a
    machine with one are both handled without special-casing.

    ``os.scandir`` rather than ``Path.iterdir`` + ``Path.stat``: this runs twice
    for every test in the suite, and on Windows scandir carries the size and
    timestamps back from the directory enumeration itself instead of paying a
    separate stat syscall per entry. With ~80 files in the real logs directory
    the naive version turned the guard into the slowest thing in the run.
    """
    try:
        with _REAL_SCANDIR(path) as entries:
            return tuple(sorted(
                (e.name, e.stat().st_size, e.stat().st_mtime_ns)
                for e in entries if e.is_file()
            ))
    except NotADirectoryError:
        pass
    except OSError:
        return None
    try:
        stat = _REAL_STAT(path)
        return (stat.st_size, stat.st_mtime_ns)
    except OSError:
        return None


@pytest.fixture(scope="session")
def _sandbox_logs_dir(tmp_path_factory):
    """One throwaway logs directory for the whole session."""
    return tmp_path_factory.mktemp("setup-logs")


def _already_imported(name: str):
    """The module if this session has imported it, else None.

    The redirect below must not be what *causes* a module to be imported.
    Importing ``shared.bootstrap`` reconfigures ``sys.stdout``/``sys.stderr`` to
    UTF-8 at module scope, which is correct for a real setup run and disruptive
    when triggered from a fixture in the middle of an unrelated test — it broke
    a threading test in ``test_job_ui.py`` that has nothing to do with setup.
    Collection imports every test module before the first test runs, so any
    module the suite actually uses is already here by the time this is asked.
    """
    return sys.modules.get(name)


@pytest.fixture(scope="session")
def _sandbox_setup_log(_sandbox_logs_dir):
    """One sandboxed ``SetupLog`` for the whole session, closed at the end.

    Session-scoped on purpose. A fresh logger per test would open — and leak — a
    file handle for every test that logs, and on Windows those open handles then
    block pytest's temp-directory cleanup at interpreter shutdown.
    """
    bootstrap = _already_imported("shared.bootstrap")
    if bootstrap is None:
        yield None
        return

    original = bootstrap.LOGS_DIR
    bootstrap.LOGS_DIR = _sandbox_logs_dir
    log = None
    try:
        log = bootstrap.SetupLog()
        yield log
    finally:
        if log is not None:
            log.close()
        bootstrap.LOGS_DIR = original


@pytest.fixture(scope="session", autouse=True)
def _isolated_setup_log(_sandbox_logs_dir, _sandbox_setup_log):
    """Send the session's setup logging to a sandbox, never to the real log.

    The production half of this fix made ``SetupLog`` open its file on first use
    instead of at construction, so merely importing ``bootstrap`` no longer
    writes anything. This is the other half: a test that legitimately *uses* a
    logger still must not append to ``files/runtime-data/logs/setup_<date>.log``.

    ``LOG`` is replaced as well as ``LOGS_DIR`` being redirected, because the
    shared logger caches its resolved path on first use — a stale cache would
    otherwise outlive the redirect. The replacement is the session-scoped
    sandbox logger, so the whole run costs one directory and one file handle.

    There are two independent writers of that directory and both are redirected:
    ``bootstrap`` (``setup_<date>.log``) and ``shared.logging_setup`` via
    ``shared.paths.LOGS_DIR`` (``session_<timestamp>.log``, written whenever a
    test builds the launcher). The second was leaving real session logs behind
    long before this phase.

    **Session-scoped, not per-test, and that matters.** The redirect only has to
    hold for the run, so doing it once replaces roughly fifteen thousand
    per-test attribute swaps with three. The per-test version was not merely
    wasteful: the extra allocations shifted when the cyclic collector ran, and a
    collection landing on an import worker thread finalised a leftover
    ``tkinter.Variable`` there — ``Variable.__del__`` calls into Tcl, which stalls
    off the main thread, so an unrelated five-second thread-start wait in
    ``test_job_ui.py`` timed out. That Tk-finalisation hazard is latent in the
    suite and predates this work; the fix here is simply not to poke it.

    Only modules the session has already imported are touched — see
    ``_already_imported``. Individual tests may still redirect these paths
    themselves with ``monkeypatch``; a function-scoped patch wins over this and
    is undone normally.
    """
    bootstrap = _already_imported("shared.bootstrap")
    paths = _already_imported("shared.paths")
    restore: list[tuple[object, str, object]] = []

    if bootstrap is not None:
        restore.append((bootstrap, "LOGS_DIR", bootstrap.LOGS_DIR))
        bootstrap.LOGS_DIR = _sandbox_logs_dir
        if _sandbox_setup_log is not None:
            restore.append((bootstrap, "LOG", bootstrap.LOG))
            bootstrap.LOG = _sandbox_setup_log
    if paths is not None:
        restore.append((paths, "LOGS_DIR", paths.LOGS_DIR))
        paths.LOGS_DIR = _sandbox_logs_dir

    try:
        yield
    finally:
        for module, name, original in reversed(restore):
            setattr(module, name, original)


def _violations(before: dict) -> list[str]:
    return [
        f"{name} ({_GUARDED_PATHS[name]})"
        for name, snapshot in before.items()
        if _fingerprint(_GUARDED_PATHS[name]) != snapshot
    ]


_ADVICE = ("\nRedirect bootstrap.VENV_DIR / bootstrap.LOGS_DIR to tmp_path "
           "instead of writing the developer's real environment.")


@pytest.fixture(autouse=True)
def _no_production_state_writes():
    """Fail any test that mutates the real requirements stamp.

    Tests exercising setup, logging or environment stamping must redirect the
    module-level paths (``bootstrap.VENV_DIR``, ``bootstrap.LOGS_DIR``) into
    ``tmp_path`` first. If this fires, that redirect is missing — do not relax
    the guard, and never repair the real environment to make it pass.
    """
    before = {name: _fingerprint(_GUARDED_PATHS[name])
              for name in _PER_TEST_GUARDED}
    yield
    changed = _violations(before)
    if changed:
        pytest.fail("this test mutated real production state: "
                    + "; ".join(changed) + _ADVICE)


@pytest.fixture(scope="session", autouse=True)
def _no_production_log_writes():
    """The same contract for the log directory, checked once for the session.

    Session-scoped purely for cost — see the note beside ``_GUARDED_PATHS``.
    """
    watched = {name: _fingerprint(path) for name, path in _GUARDED_PATHS.items()
               if name not in _PER_TEST_GUARDED}
    yield
    changed = _violations(watched)
    if changed:
        pytest.fail("this test run mutated real production state: "
                    + "; ".join(changed) + _ADVICE)
