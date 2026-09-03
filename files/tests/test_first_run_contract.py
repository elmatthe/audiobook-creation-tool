"""The first-run product contract — v0.6.2 Plan 5, Phase 15 acceptance checkpoint.

**What a person is promised.** They download the tool, double-click
``Setup_and_Run-audiobook-creation-tool.bat``, and it works. They are **not**
expected to have Python, to have FFmpeg, or to be told to go and fetch either
one. A machine that already has a *broken* FFmpeg must not be worse off than a
machine with none at all.

That promise had never been pinned anywhere. Phase 15's blocker was one half of
it failing in the field — an unusable FFmpeg being accepted because a path
resolved — and the fix would be worth very little if the *other* half, actually
obtaining a usable one on a machine that has none, quietly regressed later.

Three chains are asserted here:

* **No Python.** The ``.bat`` is the only part of the product that runs before
  Python exists, so its contract is asserted against its text; everything after
  it is asserted against the code.
* **No FFmpeg.** Setup must install one itself, prove both halves, and pin them.
* **A blocked FFmpeg already installed.** The presence of *something* called
  ffmpeg must not be mistaken for readiness, and must not stop setup installing
  something that works.

Nothing here installs anything, downloads anything, runs winget, or touches the
machine's real state: the installer seams are stubbed and every candidate is a
generated placeholder under ``tmp_path``. The live end-to-end proof is recorded
in the Handoff.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PureWindowsPath

import pytest

from shared import bootstrap
from shared import ffmpeg_health

from test_ffmpeg_health import Log, both, install, runner_for  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BAT = REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.bat"
EXE = ffmpeg_health.EXE


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """No test may read or write the developer's real FFmpeg state."""
    resources = tmp_path / "runtime-data"
    resources.mkdir()
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", resources)
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [])
    monkeypatch.setattr(ffmpeg_health, "_brew_dirs", lambda: [])
    return resources


@pytest.fixture()
def bat_text() -> str:
    return BAT.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# A. No Python on the machine
# --------------------------------------------------------------------------- #


def test_the_launcher_takes_the_fast_path_only_when_the_venv_exists(bat_text):
    assert r'if exist ".venv\Scripts\pythonw.exe"' in bat_text
    assert "--launch-only" in bat_text


def test_a_freshly_extracted_tree_therefore_runs_first_run_setup(bat_text):
    """No ``.venv`` means the fast path cannot be taken, so setup runs."""
    fast = bat_text.index(r'if exist ".venv\Scripts\pythonw.exe"')
    first_run = bat_text.index("first-time setup")
    assert fast < first_run


def test_it_looks_for_both_py_and_python_before_installing(bat_text):
    assert "where py " in bat_text or "where py>" in bat_text or "where py >" in bat_text
    assert "where python " in bat_text or "where python >" in bat_text


def test_it_installs_python_312_through_winget_when_none_is_found(bat_text):
    assert "winget install --id Python.Python.3.12" in bat_text
    assert "--accept-source-agreements" in bat_text
    assert "--accept-package-agreements" in bat_text


def test_it_accepts_the_user_scope_install_without_waiting_for_path(bat_text):
    """winget installs per-user and does not refresh a running shell's PATH.

    Re-checking ``where`` alone would report failure for an install that had
    just succeeded, which is the same defect Phase 15 removed from the FFmpeg
    branch. The ``.bat`` checks the known location directly.
    """
    assert r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" in bat_text
    install_at = bat_text.index("winget install --id Python.Python.3.12")
    direct_at = bat_text.index(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe")
    assert install_at < direct_at, "the direct check must come after the install"


def test_the_located_interpreter_is_what_runs_the_bootstrap(bat_text):
    assert '"%PYCMD%" "%BOOTSTRAP%"' in bat_text
    assert r"set \"BOOTSTRAP=scripts\Universal\shared\bootstrap.py\"".replace("\\\"", '"') \
        in bat_text or "BOOTSTRAP=scripts\\Universal\\shared\\bootstrap.py" in bat_text


def test_failing_to_obtain_python_fails_truthfully_rather_than_obscurely(bat_text):
    """The worst outcome is running ``"" bootstrap.py`` and showing a shell error."""
    tail = bat_text[bat_text.index("if not defined PYCMD", bat_text.index("winget install")):]
    assert "Could not find or install Python automatically" in tail
    assert "python.org/downloads" in tail
    assert "exit /b 1" in tail
    # And it must stop rather than fall through into the bootstrap call.
    assert tail.index("exit /b 1") < tail.index('"%PYCMD%" "%BOOTSTRAP%"')


def test_a_cancelled_setup_is_not_reported_as_a_failure(bat_text):
    assert '"%RC%"=="2"' in bat_text
    assert "Setup cancelled" in bat_text


def test_the_bootstrap_probes_the_winget_user_scope_python_location(monkeypatch):
    """The same PATH-independence, on the Python side of the boundary.

    Forced onto the Windows branch rather than skipped off it: this is a
    Windows contract, and a macOS run that quietly skipped it would stop
    protecting it. Plan 5 adds no new conditional coverage.
    """
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    candidates = bootstrap._candidate_interpreters()

    # Compared under *Windows* path semantics rather than the host's. Forcing
    # ``IS_WINDOWS`` picks the Windows branch but cannot turn ``pathlib.Path``
    # into ``WindowsPath``, so off Windows that branch joins with ``/`` and
    # yields ``C:\Users\...\Local/Programs/Python/Python312/python.exe``. That is
    # the *same path* Windows itself builds with backslashes — identical
    # ``PureWindowsPath.parts`` — so the old raw ``str.endswith`` was really
    # asserting which host ran the suite. On Windows this compares exactly the
    # value it always did; the contract itself is unchanged and no weaker.
    # Candidates are structured argv sequences (PRE-PLAN-6 Phase 1): a path
    # candidate is a one-element list whose single element may contain spaces,
    # and a launcher candidate is ["py", "-3.12"]. Only the single-token path
    # candidates can name a user-scope install.
    paths = [argv[0] for argv in candidates if len(argv) == 1]
    user_scope = [PureWindowsPath(c) for c in paths
                  if PureWindowsPath(c).parts[-4:]
                  == ("Programs", "Python", "Python312", "python.exe")]
    assert user_scope, candidates
    assert user_scope[0] == PureWindowsPath(
        r"C:\Users\someone\AppData\Local\Programs\Python\Python312\python.exe")
    assert ["py", "-3.12"] in candidates


def test_installing_python_re_probes_even_if_winget_reports_a_problem(monkeypatch):
    """A non-zero winget exit is not proof the interpreter is absent."""
    calls: list = []
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "winget")
    monkeypatch.setattr(bootstrap, "_run",
                        lambda *a, **k: calls.append(a) or _Completed(1))
    probed: list = []
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: probed.append(1) or ["python"])
    assert bootstrap.install_python(Log()) == ["python"]
    assert probed == [1], "the re-probe must happen regardless of the exit code"


def test_no_python_at_all_produces_a_truthful_setup_failure(monkeypatch):
    monkeypatch.setattr(bootstrap, "find_suitable_python", lambda log, prefer_tk=True: None)
    monkeypatch.setattr(bootstrap, "install_python", lambda log, prefer_tk=True: None)
    ok, message = bootstrap.run_setup(False, lambda step, text: None, Log())
    assert ok is False
    assert "Python 3.12 could not be found or installed" in message


class _Completed:
    def __init__(self, code: int) -> None:
        self.returncode = code
        self.stdout = ""
        self.stderr = ""


# --------------------------------------------------------------------------- #
# B. No FFmpeg on the machine
# --------------------------------------------------------------------------- #


@pytest.fixture()
def installer(monkeypatch, tmp_path):
    """Stand in for ``winget install Gyan.FFmpeg``.

    It does what a real install does and nothing more: puts a working pair in a
    package directory that is **not on PATH**, because a fresh winget install
    never is in the process that ran it. If setup only looked at PATH it would
    conclude its own install had failed.
    """
    package = tmp_path / "WinGet" / "Packages" / "Gyan.FFmpeg_x" / "ffmpeg-9.0-full_build" / "bin"
    state = {"installed": 0}

    def do_install(log):
        state["installed"] += 1
        install(package)
        monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [package])
        return True

    monkeypatch.setattr(bootstrap, "_install_ffmpeg", do_install)
    state["package"] = package
    return state


def test_an_empty_machine_is_not_reported_as_ready(monkeypatch):
    monkeypatch.setattr(bootstrap, "_install_ffmpeg", lambda log: False)
    assert bootstrap.ensure_ffmpeg(Log()) is False
    assert ffmpeg_health.pinned_pair() is None


def test_setup_installs_ffmpeg_itself_and_pins_the_result(monkeypatch, installer):
    monkeypatch.setattr(ffmpeg_health, "prove_pair",
                        lambda pair, runner=None: ffmpeg_health.Proof(
                            ok=True, version_text="ffmpeg version 9.0"))
    log = Log()
    assert bootstrap.ensure_ffmpeg(log) is True
    assert installer["installed"] == 1
    pinned = ffmpeg_health.pinned_pair()
    assert pinned is not None
    assert pinned.directory == installer["package"]


def test_the_installed_pair_is_found_even_though_path_never_refreshed(
        monkeypatch, installer):
    """The install lands off-PATH, which is the realistic case."""
    monkeypatch.setattr(ffmpeg_health, "prove_pair",
                        lambda pair, runner=None: ffmpeg_health.Proof(ok=True))
    bootstrap.ensure_ffmpeg(Log())
    assert os.environ.get("PATH", "") == ""
    assert ffmpeg_health.pinned_pair().directory == installer["package"]


def test_both_halves_of_the_installed_pair_are_executed(monkeypatch, installer):
    executed: list = []

    def watching(pair, runner=None):
        executed.append(pair.ffmpeg.as_path)
        executed.append(pair.ffprobe.as_path)
        return ffmpeg_health.Proof(ok=True)

    monkeypatch.setattr(ffmpeg_health, "prove_pair", watching)
    bootstrap.ensure_ffmpeg(Log())
    assert len(executed) == 2
    assert executed[0].name.startswith("ffmpeg")
    assert executed[1].name.startswith("ffprobe")


def test_an_install_that_still_does_not_run_is_reported_as_failure(
        monkeypatch, installer):
    """Installing something is not the same as having something that works."""
    monkeypatch.setattr(ffmpeg_health, "prove_pair",
                        lambda pair, runner=None: ffmpeg_health.Proof(
                            ok=False, detail="blocked", failed="ffprobe"))
    log = Log()
    assert bootstrap.ensure_ffmpeg(log) is False
    assert "could not be run" in log.text
    assert ffmpeg_health.pinned_pair() is None


def test_setup_does_not_reinstall_when_a_healthy_pair_already_exists(
        monkeypatch, tmp_path, installer):
    directory = install(tmp_path / "already-good")
    monkeypatch.setenv("PATH", str(directory))
    monkeypatch.setattr(ffmpeg_health, "prove_pair",
                        lambda pair, runner=None: ffmpeg_health.Proof(ok=True))
    assert bootstrap.ensure_ffmpeg(Log()) is True
    assert installer["installed"] == 0


def test_the_windows_installer_prefers_the_stable_winget_package():
    """A moving nightly cannot accumulate the reputation an unsigned build needs."""
    source = (REPO_ROOT / "scripts" / "Universal" / "shared"
              / "bootstrap.py").read_text(encoding="utf-8")
    branch = source[source.index("def _install_ffmpeg("):]
    windows = branch[:branch.index("if IS_MAC")]
    assert "Gyan.FFmpeg" in windows
    assert windows.index("Gyan.FFmpeg") < windows.index("_download_portable_ffmpeg_windows")


def test_the_user_is_never_told_to_fetch_ffmpeg_before_using_the_app():
    """A manual-download instruction may only ever be a last-resort message.

    It must not appear anywhere that a normal first run would reach.
    """
    source = (REPO_ROOT / "scripts" / "Universal" / "shared"
              / "bootstrap.py").read_text(encoding="utf-8")
    setup = source[source.index("def run_setup("):source.index("def _install_ffmpeg(")]
    for line in setup.splitlines():
        if "ffmpeg.org/download" in line:
            assert "could not be installed automatically" in setup, (
                "a download link may only follow an automatic-install failure")


# --------------------------------------------------------------------------- #
# C. A blocked FFmpeg is already installed
# --------------------------------------------------------------------------- #


@pytest.fixture()
def blocked(monkeypatch, tmp_path):
    """The Phase 15 machine, reduced: something named ffmpeg that will not run."""
    directory = install(tmp_path / "blocked-ffmpeg")
    monkeypatch.setenv("PATH", str(directory))
    return directory


def test_a_blocked_installation_does_not_count_as_ready(monkeypatch, blocked):
    monkeypatch.setattr(bootstrap, "_install_ffmpeg", lambda log: False)
    monkeypatch.setattr(ffmpeg_health, "prove_pair",
                        lambda pair, runner=None: ffmpeg_health.Proof(
                            ok=False, detail="WinError 4551", failed="ffprobe"))
    assert bootstrap.ensure_ffmpeg(Log()) is False


def test_setup_still_installs_rather_than_giving_up_because_ffmpeg_exists(
        monkeypatch, blocked, installer):
    """The heart of it: a broken machine must not be worse off than an empty one.

    ``ensure_ffmpeg`` used to return ``True`` the moment ``shutil.which`` found
    anything, so a blocked installation stopped setup from ever installing a
    working one.
    """
    healthy = installer["package"]

    def prove(pair, runner=None):
        ok = os.path.normcase(str(pair.directory)) == os.path.normcase(str(healthy))
        return ffmpeg_health.Proof(ok=ok, detail="WinError 4551",
                                   failed="" if ok else "ffprobe")

    monkeypatch.setattr(ffmpeg_health, "prove_pair", prove)
    assert bootstrap.ensure_ffmpeg(Log()) is True
    assert installer["installed"] == 1, "setup gave up instead of installing"
    assert ffmpeg_health.pinned_pair().directory == healthy


def test_the_new_pair_wins_even_though_the_blocked_one_is_earlier_on_path(
        monkeypatch, blocked, installer):
    healthy = installer["package"]

    def prove(pair, runner=None):
        return ffmpeg_health.Proof(
            ok=os.path.normcase(str(pair.directory)) == os.path.normcase(str(healthy)))

    monkeypatch.setattr(ffmpeg_health, "prove_pair", prove)
    bootstrap.ensure_ffmpeg(Log())

    # The blocked directory is still first on PATH, and still loses.
    assert os.environ["PATH"].startswith(str(blocked))
    pinned = ffmpeg_health.pinned_pair()
    assert pinned.directory == healthy
    assert pinned.ffmpeg.as_path.parent == pinned.ffprobe.as_path.parent


def test_the_blocked_candidate_is_not_executed_again_after_the_install(
        monkeypatch, blocked, installer):
    """One security notification per broken installation, not one per attempt."""
    healthy = installer["package"]
    seen: list = []

    def prove(pair, runner=None):
        seen.append(os.path.normcase(str(pair.directory)))
        return ffmpeg_health.Proof(
            ok=os.path.normcase(str(pair.directory)) == os.path.normcase(str(healthy)))

    monkeypatch.setattr(ffmpeg_health, "prove_pair", prove)
    bootstrap.ensure_ffmpeg(Log())
    assert seen.count(os.path.normcase(str(blocked))) == 1, seen


def test_a_later_launch_does_not_probe_the_blocked_installation_at_all(
        monkeypatch, blocked, installer):
    healthy = installer["package"]
    monkeypatch.setattr(ffmpeg_health, "prove_pair",
                        lambda pair, runner=None: ffmpeg_health.Proof(
                            ok=os.path.normcase(str(pair.directory))
                            == os.path.normcase(str(healthy))))
    bootstrap.ensure_ffmpeg(Log())

    seen: list = []

    def prove(pair, runner=None):
        seen.append(os.path.normcase(str(pair.directory)))
        return ffmpeg_health.Proof(ok=True)

    monkeypatch.setattr(ffmpeg_health, "prove_pair", prove)
    assert bootstrap.ensure_ffmpeg_ready_for_launch() is True
    assert seen == [os.path.normcase(str(healthy))], seen


def test_nothing_in_the_setup_path_weakens_a_security_policy():
    """**Structural.** The one thing this must never buy readiness with."""
    for name in ("bootstrap.py", "ffmpeg_health.py", "ffmpeg_utils.py"):
        source = (REPO_ROOT / "scripts" / "Universal" / "shared"
                  / name).read_text(encoding="utf-8")
        lowered = source.lower()
        for banned in ("unblock-file", "zone.identifier", "set-mppreference",
                       "add-mppreference", "exclusionpath", "icacls",
                       "verifiedandreputablepolicystate", "smartscreenenabled"):
            assert banned not in lowered, (name, banned)


def test_the_setup_bat_installs_no_security_change(bat_text):
    lowered = bat_text.lower()
    for banned in ("unblock-file", "set-mppreference", "exclusionpath",
                   "icacls", "attrib -r", "reg add"):
        assert banned not in lowered, banned
