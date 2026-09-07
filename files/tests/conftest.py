"""Shared pytest setup: make scripts/Universal (the import root) importable.

These are behaviour-preservation smoke tests: fast, deterministic, no network
(Edge TTS / Kokoro downloads are never touched). Fixtures that need real media
live in files/test-files/ (gitignored, local-only) and tests that use them skip
when the folder is absent.

They must also leave the machine exactly as they found it — see the autouse
guard at the bottom of this file.
"""

from __future__ import annotations

import hashlib
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
#  PRE-PLAN-6 Phase 6 (row 17) completed the set. Phases 3 to 5 gave the suite
#  three more ways to write production state — an FFmpeg pin, an installed
#  build, and a staging tree — and the guard did not cover any of them. That was
#  not hypothetical: an intermediate Phase-5 run created
#  ``files/runtime-data/ffmpeg-staging/9.0.1`` and nothing in the suite noticed.
#  It was found by hand, afterwards. All three are now guarded, and the absence
#  of the last two is itself the thing being protected, because Phase 7's real
#  acceptance depends on this machine still having no FFmpeg.
_GUARDED_PATHS = {
    "the real requirements stamp": REPO_ROOT / ".venv" / ".requirements-state.json",
    "the real import proof": REPO_ROOT / ".venv" / ".import-proof.json",
    "the real FFmpeg pin": (REPO_ROOT / "files" / "runtime-data"
                            / "ffmpeg-state.json"),
    "the real installed FFmpeg build": REPO_ROOT / "files" / "bin",
    "the real FFmpeg staging tree": (REPO_ROOT / "files" / "runtime-data"
                                     / "ffmpeg-staging"),
    "the real setup log directory": REPO_ROOT / "files" / "runtime-data" / "logs",
}
#  Everything except the log directory is checked around every test, so a
#  violation names the test that caused it. That is affordable because each is
#  either one small file or — for the two FFmpeg trees — a path that does not
#  exist on a machine in the preserved condition, which costs a single failed
#  stat. The log directory keeps its session-scoped check: ~80 entries either
#  side of ~5500 tests is over ten thousand scans, and paying that per test is
#  what previously perturbed the suite's timing enough to trip a bounded thread
#  wait in test_job_ui.py.
_PER_TEST_GUARDED = ("the real requirements stamp", "the real import proof",
                     "the real FFmpeg pin", "the real installed FFmpeg build",
                     "the real FFmpeg staging tree")


# Captured at import, before any test can monkeypatch them. The guard has to
# observe the real filesystem: a test that fakes ``os.scandir`` to prove some
# walk tolerates a vanishing file must not also fake what the guard sees.
_REAL_SCANDIR = os.scandir
_REAL_STAT = os.stat


def _fingerprint(path: Path):
    """(size, mtime_ns, sha256) for a file, or the metadata equivalent for a directory.

    A missing path fingerprints as ``None``, so a machine with no ``.venv`` and a
    machine with one are both handled without special-casing.

    **The single-file case hashes the content.** Size and timestamp alone would
    miss a same-size edit whose mtime was restored — a stamp rewritten with a
    different ``requirements_sha256`` is exactly that shape, and it is the
    falsification this guard exists to catch. The file is a few hundred bytes and
    the guard reads it twice per test, so the hash is free in practice.

    **The directory case deliberately does not hash.** It covers the real logs
    directory, whose ~80 entries are checked once per session; hashing a growing
    log tree around every test would be expensive for no gain, since a log that
    is written at all has changed size or timestamp.

    **It does recurse, and that matters.** ``files/bin`` holds a versioned
    layout — ``ffmpeg/<version>/bin/ffmpeg.exe`` — so a single-level listing
    would let a whole installed build appear three directories down behind an
    unchanged top level. The same is true of the staging tree. Recursion is what
    makes "this path is absent" a claim about the tree rather than about its
    root, and absence is precisely what Phase 7 needs preserved.

    ``os.scandir`` rather than ``Path.iterdir`` + ``Path.stat``: on Windows
    scandir carries size and timestamps back from the directory enumeration
    itself instead of paying a separate stat syscall per entry.
    """
    try:
        return tuple(sorted(_walk(path, "")))
    except NotADirectoryError:
        pass
    except OSError:
        return None
    try:
        stat = _REAL_STAT(path)
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        return (stat.st_size, stat.st_mtime_ns, digest)
    except OSError:
        return None


def _walk(directory: Path, prefix: str):
    """Every file under ``directory``, recursively, as (relpath, size, mtime).

    Raises ``NotADirectoryError`` for a file so :func:`_fingerprint` can fall
    through to its content-hashing branch, and ``OSError`` for a missing path so
    absence fingerprints as ``None``.
    """
    with _REAL_SCANDIR(directory) as entries:
        for entry in entries:
            name = f"{prefix}{entry.name}"
            if entry.is_dir():
                # A directory that exists but is empty still has to register,
                # or an emptied tree would look identical to an absent one.
                yield (name + "/", -1, -1)
                yield from _walk(Path(entry.path), name + "/")
            elif entry.is_file():
                info = entry.stat()
                yield (name, info.st_size, info.st_mtime_ns)


@pytest.fixture
def pinned_ffmpeg(monkeypatch, tmp_path):
    """A sandbox ffmpeg + ffprobe pair, proved and pinned. Returns its directory.

    PRE-PLAN-6 Phase 4 closed the runtime trust boundary: ``ffmpeg_cmd()`` and
    ``ffprobe_cmd()`` now resolve **only** the pinned pair and raise otherwise,
    instead of falling back to the bare names. That is the point of the change —
    a command line can no longer escape the health authority — but it means a
    test that merely *builds* a command now needs a pinned pair to build it from.

    So this models the real contract rather than weakening production for old
    fixtures: real files, a real ``establish`` call, a stub runner standing in
    for execution, and every state path inside ``tmp_path``.
    """
    from shared import ffmpeg_health, ffmpeg_utils

    resources = tmp_path / "ffmpeg-state"
    resources.mkdir(parents=True, exist_ok=True)
    directory = tmp_path / "ffmpeg-bin"
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        (directory / f"{name}{ffmpeg_health.EXE}").write_text(
            "sandbox binary", encoding="utf-8")

    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", resources)
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", tmp_path / "no-bundled-bin")
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [])
    monkeypatch.setattr(ffmpeg_health, "_brew_dirs", lambda: [])
    monkeypatch.setenv("PATH", str(directory))

    proven = ffmpeg_health.establish(runner=lambda exe: (True, "ffmpeg version 9.0.1"))
    assert proven is not None, "the sandbox pair should have pinned"
    ffmpeg_utils.refresh()
    yield directory
    ffmpeg_utils.refresh()


# --------------------------------------------------------------------------- #
#  pydub's configuration is process-wide  (PRE-PLAN-6 Phase 7)
# --------------------------------------------------------------------------- #

#: The three ``AudioSegment`` class attributes ``configure_pydub()`` writes.
_PYDUB_ATTRIBUTES = ("converter", "ffmpeg", "ffprobe")

#: Sentinel for "this attribute did not exist", which is different from "it was
#: None" and must round-trip as its own answer.
_ABSENT = object()

#: pydub's import-time configuration, captured the first time it is seen. Used
#: only for a test that is itself the first thing to import pydub: there is no
#: per-test "before" to go back to in that case, and leaving the test's own
#: answer installed is the thing this guard exists to prevent.
_PYDUB_BASELINE: dict | None = None


def _pydub_modules():
    """``(audio_segment, utils)`` for the real pydub, or ``None``.

    ``None`` covers both "not imported yet" and "some fixture injected a
    stand-in", the same way ``tk_gate._live_types`` tolerates a fake ``tkinter``.
    A stand-in has nothing process-wide to restore.
    """
    segment = sys.modules.get("pydub.audio_segment")
    utils = sys.modules.get("pydub.utils")
    if segment is None or utils is None:
        return None
    if not hasattr(segment, "AudioSegment") or not hasattr(utils, "get_prober_name"):
        return None
    return segment, utils


def _pydub_snapshot() -> dict | None:
    """The four process-wide settings, plus the modules they were read from.

    The module objects travel with the values so a restore always writes back to
    the same objects it read: a test that swaps a stand-in into ``sys.modules``
    must not redirect the restore onto the stand-in it is about to discard.
    """
    modules = _pydub_modules()
    if modules is None:
        return None
    segment, utils = modules
    state = {"segment": segment, "utils": utils,
             "get_prober_name": utils.get_prober_name}
    for name in _PYDUB_ATTRIBUTES:
        state[name] = getattr(segment.AudioSegment, name, _ABSENT)
    return state


def _pydub_restore(state: dict) -> None:
    segment, utils = state["segment"], state["utils"]
    for name in _PYDUB_ATTRIBUTES:
        value = state[name]
        if value is _ABSENT:
            # Absence is a value here, not a gap: ``ffprobe`` does not exist on
            # a freshly imported AudioSegment -- configure_pydub() creates it --
            # so restoring by assignment alone would leave the attribute behind
            # and quietly change what a later test sees.
            if hasattr(segment.AudioSegment, name):
                delattr(segment.AudioSegment, name)
        else:
            setattr(segment.AudioSegment, name, value)
    utils.get_prober_name = state["get_prober_name"]


@pytest.fixture(scope="session", autouse=True)
def _pydub_baseline():
    """Record pydub's own import-time configuration once, before any test runs.

    Without this there is a hole exactly one test wide: the first test to import
    pydub is also the first that can configure it, so the per-test guard below
    would have no "before" to return to and would have to leave that test's
    answer installed -- which, if it is a sandbox path, is the whole defect.
    Importing pydub here is not a cost the suite avoids anyway; it is a declared
    dependency that most of these tests reach eventually.
    """
    global _PYDUB_BASELINE
    try:
        import pydub.audio_segment  # noqa: F401
        import pydub.utils  # noqa: F401
    except Exception:  # pragma: no cover - pydub absent is not this file's problem
        return
    if _PYDUB_BASELINE is None:
        _PYDUB_BASELINE = _pydub_snapshot()


@pytest.fixture(autouse=True)
def _restore_pydub_configuration():
    """No test may leave its own ffmpeg paths installed in pydub.

    ``ffmpeg_utils.configure_pydub()`` writes absolute paths into
    ``pydub.AudioSegment`` and rebinds ``pydub.utils.get_prober_name``. Those are
    **module globals of a third-party package** — nothing pytest knows how to
    undo, and nothing ``monkeypatch`` ever patched. So a test that pins a sandbox
    pair and then configures pydub leaves those globals pointing inside its own
    ``tmp_path``, which pytest deletes moments later.

    ``refresh()`` does not close this. It clears ``ffmpeg_utils``' own caches and
    lowers ``_pydub_configured``, and rewriting pydub is deliberately the *next*
    ``configure_pydub()`` call's job — but a consumer like ``kokoro_synth`` never
    makes one. It calls ``AudioSegment.export`` and inherits whatever is there.

    That is precisely how Phase 7 found two ``test_kokoro_timing_wiring`` tests
    trying to spawn a deleted temporary directory. It was invisible for as long
    as this machine had no FFmpeg, because those tests were failing earlier for a
    different reason; consuming the missing-FFmpeg condition is what exposed it.

    Restoring rather than clearing is the point: the next test observes exactly
    the configuration that existed before this one ran, whatever that was.
    """
    global _PYDUB_BASELINE
    before = _pydub_snapshot()
    if before is not None and _PYDUB_BASELINE is None:
        _PYDUB_BASELINE = before
    yield
    after = _pydub_snapshot()
    if after is None:
        return
    # ``before`` when this test inherited a configuration; the session baseline
    # when this test is the one that first imported pydub.
    target = before if before is not None else _PYDUB_BASELINE
    if target is None or after == target:
        return
    _pydub_restore(target)
    # The paths pydub holds and the pair ffmpeg_utils would hand out next must
    # agree; refresh() is the supported way to say "resolve again from scratch".
    from shared import ffmpeg_utils

    ffmpeg_utils.refresh()


@pytest.fixture(autouse=True)
def _no_real_provisioning(monkeypatch):
    """No test may install a real package or download the real FFmpeg archive.

    PRE-PLAN-6 Phase 5 wires provisioning into the *normal launch*, which means
    the orchestration a test drives can now reach ``winget install`` and the
    ~251 MB Gyan download. Before this phase those calls sat behind a function
    every relevant test happened to monkeypatch; that is not a guarantee, it is
    a coincidence, and the cost of the coincidence failing is a real install on
    the developer's machine — which would also destroy the preserved
    no-FFmpeg condition Phase 7's acceptance depends on.

    So the two seams are closed here instead of hoped about. A test that wants
    a route exercised stubs it itself, and a function-scoped patch wins over
    this one; a test that reaches either seam *without* stubbing gets a clear
    failure naming the call rather than a package manager doing real work.

    ``urllib.request.urlopen`` is the download seam because ``acquire`` takes an
    explicit ``opener``: patching ``acquire`` itself would break the Phase-3
    tests that legitimately drive the whole transaction with a fixture archive.
    """
    import urllib.request

    def _refuse_download(*args, **kwargs):
        raise AssertionError(
            "a test tried to open a real network connection. Pass a stub "
            "`opener=` to ffmpeg_portable.acquire/download_archive, or patch "
            "the route you are exercising.")

    monkeypatch.setattr(urllib.request, "urlopen", _refuse_download)

    bootstrap = _already_imported("shared.bootstrap")
    if bootstrap is None:
        return

    def _refuse_portable(log=None):
        raise AssertionError(
            "a test reached bootstrap._download_portable_ffmpeg_windows "
            "without stubbing it. That path acquires the real ~251 MB build "
            "and creates files/runtime-data/ffmpeg-staging, which is part of "
            "the preserved no-FFmpeg reproduction condition. Patch it, or "
            "drive ffmpeg_portable.acquire directly with a fixture archive.")

    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        _refuse_portable)
    real_run = bootstrap._run

    def _guarded_run(cmd, **kwargs):
        head = Path(str(cmd[0])).name.lower() if cmd else ""
        if head.split(".")[0] in ("winget", "brew"):
            raise AssertionError(
                f"a test tried to run a real package manager: {list(cmd)!r}. "
                "Patch bootstrap._run (or the route function) in the test.")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(bootstrap, "_run", _guarded_run)


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
        # Resolve the path now, while LOGS_DIR is definitely the sandbox.
        # SetupLog resolves lazily and then caches, so a test that redirects
        # LOGS_DIR for its own purposes before this logger is first used would
        # otherwise capture it and pin the shared logger to that test's tmp_path
        # for the rest of the session.
        _ = log.path
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


_ADVICE = ("\nRedirect the writer to tmp_path before it runs — "
           "bootstrap.VENV_DIR / bootstrap.LOGS_DIR for setup state, "
           "ffmpeg_health.RESOURCES_DIR / ffmpeg_health.BIN_DIR for the FFmpeg "
           "pin, installed build and staging tree — instead of writing the "
           "developer's real environment.")


@pytest.fixture(autouse=True)
def _no_production_state_writes():
    """Fail any test that mutates real production state.

    Tests exercising setup, logging, environment stamping or FFmpeg
    acquisition must redirect the module-level paths first —
    ``bootstrap.VENV_DIR``, ``bootstrap.LOGS_DIR``,
    ``ffmpeg_health.RESOURCES_DIR``, ``ffmpeg_health.BIN_DIR`` — into
    ``tmp_path``, **before the first write**. If this fires, that redirect is
    missing or came too late.

    Do not relax the guard, and never repair the real environment to make it
    pass: the environment it is protecting is the input to Phase 7's real
    acceptance, and a test that can quietly create ``files/bin`` or pin an
    FFmpeg pair has spent that acceptance rather than merely made a mess.
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
