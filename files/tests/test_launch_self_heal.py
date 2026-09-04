"""PRE-PLAN-6 Phase 5 — a normal launch repairs what is broken, then launches.

**What was wrong.** Phases 1-4 built the pieces: an environment assessment that
can tell working from wrecked, a requirements/import contract that repairs in
place, a hash-verified repo-local FFmpeg build, and a runtime that refuses to
execute anything unproved. None of it was reachable from the thing people
actually do, which is double-click the launcher.

``--launch-only`` detected a missing FFmpeg, opened a modal saying the audio
tools were unavailable, and launched anyway (**C1**). The only provisioning
route lived behind ``run_setup``, which an existing installation never reaches.
The advice the app could offer therefore amounted to running the same launcher
again — the same non-repairing path, with the same result (**M3**). On macOS the
first-run ``.command`` knew how to ask Homebrew, but an existing ``.venv`` went
straight to ``--launch-only`` and could not (**M4**). And the WinGet FFmpeg call
never said which scope it wanted, so the answer depended on a package default
on machines where a machine-wide install prompts for a password nobody has
(**M5**).

**The contract now.** ASSESS → REPAIR → PROVE → PIN → LAUNCH, entered
identically by ``--launch-only`` and by a bare ``bootstrap.py`` that finds a
usable environment. Only the broken component does work. An installer's exit
code never means "ready" — ``ffmpeg_health`` alone decides that. And a
recoverable failure never holds the process in front of a person who is not
there: the GUI starts first, and at most one truthful notice follows it.

Everything here is mocked, staged or ``tmp_path``-contained. Nothing installs a
package, downloads an archive, touches the real ``.venv`` or writes real state —
see the ``_no_real_provisioning`` guard in ``conftest.py``.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from shared import bootstrap, ffmpeg_health, ffmpeg_portable, ffmpeg_utils

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
BOOTSTRAP_SRC = (UNIVERSAL / "shared" / "bootstrap.py").read_text(encoding="utf-8")
EXE = ffmpeg_health.EXE


class Log:
    """A SetupLog stand-in that keeps every line and writes nothing."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.path = "<sandbox>"

    def line(self, text: str = "") -> None:
        self.lines.append(text)

    def close(self) -> None:
        pass

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def install(directory: Path) -> Path:
    """A coherent ffmpeg + ffprobe pair on disk. Executes nothing."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        (directory / f"{name}{EXE}").write_text("binary", encoding="utf-8")
    return directory


def completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Every FFmpeg state path inside ``tmp_path``, and nothing on PATH.

    Redirected *before* the first write, per the phase's isolation rule: the
    real ``ffmpeg-state.json``, ``files/bin`` and PATH are the preserved
    HOME-PC reproduction condition and Phase 7 needs them exactly as they are.
    """
    resources = tmp_path / "runtime-data"
    resources.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", resources)
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [])
    monkeypatch.setattr(ffmpeg_health, "_brew_dirs", lambda: [])
    monkeypatch.setenv("PATH", "")
    ffmpeg_utils.refresh()
    yield tmp_path
    ffmpeg_utils.refresh()


@pytest.fixture
def proves_everything(monkeypatch):
    """Every pair that is asked to run, runs. Executes nothing."""
    monkeypatch.setattr(
        ffmpeg_health, "prove_pair",
        lambda pair, runner=None: ffmpeg_health.Proof(
            ok=True, version_text="ffmpeg version 9.0.1"))


@pytest.fixture
def proves_nothing(monkeypatch):
    """Nothing this machine has will run — the blocked-binary shape."""
    monkeypatch.setattr(
        ffmpeg_health, "prove_pair",
        lambda pair, runner=None: ffmpeg_health.Proof(
            ok=False, detail="refused by policy", failed="ffmpeg"))


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setattr(bootstrap, "IS_MAC", False)


@pytest.fixture
def macos(monkeypatch):
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
    monkeypatch.setattr(bootstrap, "IS_MAC", True)


@pytest.fixture
def tools(monkeypatch):
    """Control which package managers this machine appears to have."""
    present: set[str] = set()

    def which(name):
        return f"/usr/bin/{name}" if name in present else None

    monkeypatch.setattr(bootstrap.shutil, "which", which)
    return present


class Recorder(list):
    """The argv of every command that would have run. ``returncode`` is theirs."""

    returncode = 0


@pytest.fixture
def commands(monkeypatch):
    """Capture the argv of every package-manager call, running none of them."""
    calls = Recorder()

    def _run(cmd, **kwargs):
        calls.append(list(cmd))
        return completed(calls.returncode)

    monkeypatch.setattr(bootstrap, "_run", _run)
    return calls


@pytest.fixture
def installs_when_run(commands, monkeypatch, sandbox):
    """A package manager that only delivers once its command has run.

    The realistic shape, and the one that makes these tests mean anything: if
    the installed files were already on disk before the repair started, step A
    would find them and the installer would never be reached — so a test that
    pre-creates them proves nothing about the install route.
    """
    package = sandbox / "package-manager-install"
    delivered: list[Path] = []
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs",
                        lambda: list(delivered))
    monkeypatch.setattr(ffmpeg_health, "_brew_dirs", lambda: list(delivered))
    recording_run = bootstrap._run

    def _run(cmd, **kwargs):
        result = recording_run(cmd, **kwargs)
        if result.returncode == 0:
            install(package)
            delivered.append(package)
        return result

    monkeypatch.setattr(bootstrap, "_run", _run)
    return package


# --------------------------------------------------------------------------- #
#  Call-graph helpers (AST — never substrings)
# --------------------------------------------------------------------------- #
_TREE = ast.parse(BOOTSTRAP_SRC)
_FUNCTIONS = {n.name: n for n in ast.walk(_TREE)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _called_names(fn) -> set[str]:
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def reaches(entry: str, target: str) -> bool:
    """Whether ``target`` is reachable from ``entry`` in bootstrap's call graph."""
    seen: set[str] = set()

    def walk(name: str) -> bool:
        if name in seen:
            return False
        seen.add(name)
        fn = _FUNCTIONS.get(name)
        if fn is None:
            return False
        called = _called_names(fn)
        if target in called:
            return True
        return any(walk(other) for other in called)

    return walk(entry)


# =========================================================================== #
# A. One steady-state launch orchestration
# =========================================================================== #
def test_both_launch_entry_points_use_the_same_orchestration():
    """``--launch-only`` and a bare bootstrap must not drift apart.

    They are the same launch as far as a person is concerned — one comes from
    the ``.bat``/``.command``, the other from running bootstrap directly — and
    two implementations would mean the fast path could keep a defect the other
    had fixed. Asserted over ``main``'s own branches rather than by reading the
    file, so a second helper wired into one branch fails this.
    """
    main = _FUNCTIONS["main"]
    launch_calls = [n for n in ast.walk(main)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id.startswith("_launch")]
    assert launch_calls, "main() no longer calls a launch orchestration"
    assert {n.func.id for n in launch_calls} == {"_launch_with_kokoro_healthcheck"}
    assert len(launch_calls) == 2, "the two existing-installation paths"


def test_the_post_repair_handoff_returns_to_the_same_orchestration():
    """After a venv repair, the Phase-2 no-second-handoff guard still applies."""
    fn = _FUNCTIONS["_repair_and_launch"]
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "_launch_with_kokoro_healthcheck"]
    assert len(calls) == 1
    keywords = {kw.arg: kw.value for kw in calls[0].keywords}
    assert "allow_repair_handoff" in keywords
    assert keywords["allow_repair_handoff"].value is False


def test_the_normal_launch_now_reaches_provisioning():
    """C1, structurally. Phase 3 sealed this deliberately; Phase 5 opens it."""
    assert reaches("_launch_with_kokoro_healthcheck", "repair_ffmpeg")
    assert reaches("_launch_with_kokoro_healthcheck", "_install_ffmpeg")
    assert reaches("_launch_with_kokoro_healthcheck",
                   "_download_portable_ffmpeg_windows")


def test_the_classification_and_venv_repair_paths_still_do_not_provision():
    """``--venv-check`` answers a question; ``repair_venv`` repairs Python.

    Neither is allowed to acquire FFmpeg. ``--venv-check`` runs on the Windows
    launcher's critical path before anything is shown, and a venv repair that
    quietly downloaded 251 MB would be the opposite of minimum scope.
    """
    for entry in ("_venv_check", "repair_venv"):
        for target in ("acquire", "_download_portable_ffmpeg_windows",
                       "_install_ffmpeg", "repair_ffmpeg", "ensure_ffmpeg"):
            assert not reaches(entry, target), f"{entry} can reach {target}"


def test_setup_and_launch_share_one_ffmpeg_implementation():
    """One answer to "what happens when FFmpeg is missing?", not two."""
    assert reaches("run_setup", "repair_ffmpeg")
    assert reaches("ensure_ffmpeg_ready_for_launch", "repair_ffmpeg")
    assert BOOTSTRAP_SRC.count("def repair_ffmpeg(") == 1


# =========================================================================== #
# B. Windows FFmpeg route matrix
# =========================================================================== #
def test_a_healthy_active_pair_installs_nothing(
        sandbox, windows, tools, commands, proves_everything, monkeypatch):
    """Row 1. The steady state, and the one that must stay cheap."""
    tools.add("winget")
    directory = install(sandbox / "pinned")
    monkeypatch.setenv("PATH", str(directory))
    assert ffmpeg_health.establish() is not None
    monkeypatch.setenv("PATH", "")

    result = bootstrap.repair_ffmpeg(Log())

    assert result.ready
    assert result.routes == (bootstrap.FFMPEG_ROUTE_EXISTING,)
    assert commands == [], "a working machine was needlessly reinstalled"


def test_a_discovered_but_unpinned_pair_is_proved_rather_than_reinstalled(
        sandbox, windows, tools, commands, proves_everything, monkeypatch):
    """Row 2. Coherent and runnable, just never recorded — pin it, do not buy one."""
    tools.add("winget")
    directory = install(sandbox / "found")
    monkeypatch.setenv("PATH", str(directory))
    assert ffmpeg_health.pinned_pair() is None

    result = bootstrap.repair_ffmpeg(Log())

    assert result.ready
    assert commands == []
    assert ffmpeg_health.pinned_pair().directory == directory


def test_a_successful_user_scope_winget_install_ends_the_repair(
        sandbox, windows, tools, installs_when_run, proves_everything,
        monkeypatch):
    """Row 3. WinGet worked and the result proves — the fallback stays unused."""
    tools.add("winget")
    package = installs_when_run
    portable: list = []
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: portable.append(1) or True)

    result = bootstrap.repair_ffmpeg(Log())

    assert result.ready
    assert result.routes == (bootstrap.FFMPEG_ROUTE_EXISTING,
                             bootstrap.FFMPEG_ROUTE_WINGET)
    assert portable == [], "the fallback ran even though WinGet succeeded"
    assert ffmpeg_health.pinned_pair().directory == package


def test_a_missing_winget_falls_through_to_the_repo_local_build(
        sandbox, windows, tools, commands, proves_nothing, monkeypatch):
    """Row 4. No package manager is not a dead end."""
    portable: list = []
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: portable.append(1) or False)

    result = bootstrap.repair_ffmpeg(Log())

    assert commands == [], "winget was invoked on a machine that has none"
    assert portable == [1]
    assert result.routes == (bootstrap.FFMPEG_ROUTE_EXISTING,
                             bootstrap.FFMPEG_ROUTE_PORTABLE)


def test_a_failing_user_scope_winget_install_falls_through(
        sandbox, windows, tools, commands, proves_nothing, monkeypatch):
    """Row 5. Including the scope/elevation refusal this phase must tolerate.

    A Standard User's machine-wide install prompts for a password nobody has,
    which surfaces here as a non-zero exit. That is "this route is unavailable",
    not "the repair failed".
    """
    tools.add("winget")
    commands.returncode = 1
    portable: list = []
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: portable.append(1) or False)

    bootstrap.repair_ffmpeg(Log())

    assert commands and commands[0][:2] == ["winget", "install"]
    assert portable == [1]


def test_winget_exit_zero_without_a_provable_pair_still_falls_through(
        sandbox, windows, tools, commands, proves_nothing, monkeypatch):
    """Row 6 — the defect this orchestration exists to fix.

    ``_install_ffmpeg`` used to return True on exit 0 and the caller then gave
    up when ``establish`` found nothing provable, because the repo-local
    fallback lived *inside* the function that had already returned. An install
    that produced nothing runnable was a permanent dead end with a verified
    build sitting unused behind it.
    """
    tools.add("winget")
    package = install(sandbox / "winget-package")
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [package])
    portable: list = []
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: portable.append(1) or False)

    result = bootstrap.repair_ffmpeg(Log())

    assert commands[0][:2] == ["winget", "install"], "winget did run"
    assert commands.returncode == 0, "and it exited 0"
    assert portable == [1], "exit 0 was treated as the end of the repair"
    assert not result.ready
    assert bootstrap.FFMPEG_ROUTE_PORTABLE in result.routes


def test_the_repo_local_build_completes_the_repair(
        sandbox, windows, tools, commands, proves_everything, monkeypatch):
    """Row 7. And the pin the fallback wrote is the one that is used."""
    final = install(sandbox / "bin" / "ffmpeg" / "9.0.1" / "bin")

    def acquire(log):
        ffmpeg_health.adopt_pair(ffmpeg_health.pair_in(final), log)
        return True

    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows", acquire)

    result = bootstrap.repair_ffmpeg(Log())

    assert result.ready
    assert ffmpeg_health.pinned_pair().directory == final


def test_a_portable_success_is_not_followed_by_a_second_discovery(
        sandbox, windows, tools, commands, proves_everything, monkeypatch):
    """Phase-3 interaction: do not replace a pin that was just written.

    ``acquire`` already proved the pair at its final paths and pinned it
    atomically. Running ``establish`` afterwards — which old code did after
    every install — could pin a *different* installation, so the orchestration
    confirms the pair that exists instead of asking the machine again.
    """
    final = install(sandbox / "bin" / "ffmpeg" / "9.0.1" / "bin")
    decoy = install(sandbox / "decoy")

    def acquire(log):
        ffmpeg_health.adopt_pair(ffmpeg_health.pair_in(final), log)
        # A stranger appears on PATH between the pin and the confirmation.
        monkeypatch.setenv("PATH", str(decoy))
        return True

    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows", acquire)
    establishes: list = []
    real_establish = ffmpeg_health.establish
    monkeypatch.setattr(ffmpeg_health, "establish",
                        lambda *a, **kw: establishes.append(1) or real_establish(*a, **kw))

    result = bootstrap.repair_ffmpeg(Log())

    assert result.ready
    assert ffmpeg_health.pinned_pair().directory == final, \
        "a post-install discovery replaced the build that was just pinned"
    assert len(establishes) == 1, "discovery ran again after the portable pin"


def test_a_portable_install_that_does_not_prove_is_not_ready(
        sandbox, windows, tools, commands, monkeypatch):
    """Row 8's precondition. Installed is still not ready."""
    final = install(sandbox / "bin" / "ffmpeg" / "9.0.1" / "bin")
    monkeypatch.setattr(
        ffmpeg_health, "prove_pair",
        lambda pair, runner=None: ffmpeg_health.Proof(ok=True))
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: ffmpeg_health.adopt_pair(
                            ffmpeg_health.pair_in(final), log) and True)
    # It pinned. Now the binary stops running before the final confirmation.
    monkeypatch.setattr(
        ffmpeg_health, "prove_pair",
        lambda pair, runner=None: ffmpeg_health.Proof(
            ok=False, detail="refused", failed="ffmpeg"))

    assert bootstrap.repair_ffmpeg(Log()).ready is False


def test_the_final_word_is_the_health_authority_not_the_installer(
        sandbox, windows, tools, commands, proves_nothing, monkeypatch):
    """Every route reported success; nothing proved; the repair failed."""
    tools.add("winget")
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: True)

    result = bootstrap.repair_ffmpeg(Log())

    assert result.ready is False
    assert ffmpeg_health.pinned_pair() is None


# =========================================================================== #
# C. macOS route matrix
# =========================================================================== #
def test_a_mac_with_a_valid_pin_never_calls_brew(
        sandbox, macos, tools, commands, proves_everything, monkeypatch):
    """Row 1."""
    tools.add("brew")
    directory = install(sandbox / "pinned")
    monkeypatch.setenv("PATH", str(directory))
    assert ffmpeg_health.establish() is not None

    assert bootstrap.repair_ffmpeg(Log()).ready
    assert commands == []


def test_an_existing_mac_venv_reaches_the_homebrew_repair(
        sandbox, macos, tools, commands, installs_when_run, proves_everything):
    """Row 2 — M4. The existing-venv path could not repair at all before."""
    tools.add("brew")
    cellar = installs_when_run

    result = bootstrap.repair_ffmpeg(Log())

    assert commands and commands[0] == ["brew", "install", "ffmpeg"]
    assert result.ready
    assert result.routes == (bootstrap.FFMPEG_ROUTE_EXISTING,
                             bootstrap.FFMPEG_ROUTE_HOMEBREW)
    assert ffmpeg_health.pinned_pair().directory == cellar


def test_brew_succeeding_is_not_ffmpeg_succeeding(
        sandbox, macos, tools, commands, proves_nothing, monkeypatch):
    """Row 3. ``shutil.which`` finding a file is not the pair having run.

    The old code accepted ``_ffmpeg_on_path()`` after ``brew install`` — a
    filename, on a machine whose whole problem may be that the binary will not
    execute.
    """
    tools.add("brew")
    install(sandbox / "opt" / "homebrew" / "bin")
    monkeypatch.setattr(ffmpeg_health, "_brew_dirs",
                        lambda: [sandbox / "opt" / "homebrew" / "bin"])

    result = bootstrap.repair_ffmpeg(Log())

    assert commands[0] == ["brew", "install", "ffmpeg"], "brew ran and exited 0"
    assert result.ready is False
    assert ffmpeg_health.pinned_pair() is None


def test_a_mac_without_homebrew_does_not_install_homebrew(
        sandbox, macos, tools, commands, proves_nothing):
    """Row 4. Installing Homebrew is a first-run decision, not a repair.

    The root ``.command`` may run Homebrew's own installer on a first run,
    where a person is watching and consented by double-clicking. A background
    launch repair must not make that choice for them, and must not loop.
    """
    result = bootstrap.repair_ffmpeg(Log())

    assert commands == []
    assert result.ready is False
    assert result.routes == (bootstrap.FFMPEG_ROUTE_EXISTING,)
    assert "Homebrew" in result.detail
    assert "brew.sh" in result.detail


def test_the_mac_failure_notice_names_homebrew_truthfully(
        sandbox, macos, tools, commands, proves_nothing):
    """It must not claim a route that was never attempted."""
    notice = bootstrap.repair_ffmpeg(Log()).notice()

    assert "Homebrew" in notice
    assert "WinGet" not in notice
    assert "the FFmpeg copies already on this computer" in notice


def test_no_portable_route_exists_on_macos(
        sandbox, macos, tools, commands, proves_nothing, monkeypatch):
    """This drop does not invent a macOS portable-binary architecture."""
    portable: list = []
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: portable.append(1) or True)
    tools.add("brew")

    result = bootstrap.repair_ffmpeg(Log())

    assert portable == []
    assert bootstrap.FFMPEG_ROUTE_PORTABLE not in result.routes


# =========================================================================== #
# D. Minimum-scope repair
# =========================================================================== #
def test_no_ffmpeg_repair_path_rebuilds_the_environment():
    """A stale FFmpeg pin is not evidence that Python is unhealthy."""
    for entry in ("repair_ffmpeg", "ensure_ffmpeg",
                  "ensure_ffmpeg_ready_for_launch", "_install_ffmpeg",
                  "_download_portable_ffmpeg_windows"):
        for target in ("repair_venv", "create_venv", "_create_validated_venv",
                       "_move_venv_aside"):
            assert not reaches(entry, target), f"{entry} can reach {target}"


def test_the_requirements_drift_path_repairs_in_place():
    """A missing package is not evidence the interpreter needs replacing."""
    for entry in ("ensure_requirements_current", "reconcile_requirements",
                  "repair_missing_requirements"):
        for target in ("repair_venv", "create_venv", "_create_validated_venv"):
            assert not reaches(entry, target), f"{entry} can reach {target}"


def test_the_launch_path_does_not_route_through_full_setup():
    """Healing must stay bounded: no launch runs the whole first-run install."""
    assert not reaches("_launch_with_kokoro_healthcheck", "run_setup")


# =========================================================================== #
# E. Failure UX — repair first, GUI, then at most one notice
# =========================================================================== #
@pytest.fixture
def launch(monkeypatch, tmp_path, sandbox):
    """Drive ``_launch_with_kokoro_healthcheck`` with every seam recorded.

    The environment, requirements and Kokoro all report healthy unless a test
    says otherwise, so each test changes exactly one thing.
    """
    events: list[str] = []
    warnings: list[tuple[str, str]] = []

    log = Log()
    monkeypatch.setattr(bootstrap, "LOG", log)
    monkeypatch.setattr(bootstrap, "assess_venv_health",
                        lambda **kw: bootstrap.VenvHealth(
                            state=bootstrap.VENV_HEALTHY, reason="ok",
                            detail="ok", version=(3, 12), ssl=True, tk=True,
                            executes=True))
    monkeypatch.setattr(bootstrap, "venv_python", lambda windowed=False:
                        tmp_path / "python")
    monkeypatch.setattr(bootstrap, "requirements_are_current", lambda: True)
    monkeypatch.setattr(bootstrap, "required_modules_present",
                        lambda py: (True, "ok"))
    monkeypatch.setattr(bootstrap, "import_proof_is_current", lambda: True)
    monkeypatch.setattr(bootstrap, "kokoro_is_healthy", lambda py: (True, "ok"))

    def repair_dialog(work, **kwargs):
        events.append("repair-dialog")
        return work()

    def gui(_log):
        events.append("launch_gui")
        return True

    def warn(title, message):
        events.append("warning")
        warnings.append((title, message))

    monkeypatch.setattr(bootstrap, "show_repair_dialog", repair_dialog)
    monkeypatch.setattr(bootstrap, "launch_gui", gui)
    monkeypatch.setattr(bootstrap, "show_warning_dialog", warn)

    class Harness:
        def __init__(self) -> None:
            self.events = events
            self.warnings = warnings
            self.log = log

        def run(self) -> int:
            return bootstrap._launch_with_kokoro_healthcheck()

    return Harness()


def test_a_successful_repair_shows_no_warning_at_all(
        launch, windows, tools, installs_when_run, proves_everything, sandbox):
    """§8.7. Repair succeeded; there is nothing to tell anyone."""
    tools.add("winget")

    assert launch.run() == 0

    assert launch.warnings == []
    assert launch.events.index("repair-dialog") < launch.events.index("launch_gui")


def test_a_failed_repair_launches_the_gui_before_it_says_anything(
        launch, windows, tools, commands, proves_nothing, monkeypatch):
    """M3. The old order held the process in front of an empty screen.

    ``show_warning_dialog`` ran before ``launch_gui``, and a messagebox is
    modal while it is displayed — so a launcher double-clicked by someone who
    then walked away sat on a warning with no window behind it, forever.
    """
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: False)

    assert launch.run() == 0

    assert "warning" in launch.events
    assert launch.events.index("launch_gui") < launch.events.index("warning")


def test_several_broken_components_still_produce_exactly_one_notice(
        launch, windows, tools, commands, proves_nothing, monkeypatch):
    """Requirements, FFmpeg and Kokoro could each open their own modal."""
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: False)
    monkeypatch.setattr(bootstrap, "requirements_are_current", lambda: False)
    monkeypatch.setattr(bootstrap, "ensure_requirements_current",
                        lambda log: (False, "pip could not reach the index"))
    monkeypatch.setattr(bootstrap, "kokoro_is_healthy", lambda py: (False, "no kokoro"))
    monkeypatch.setattr(bootstrap, "ensure_kokoro_installed", lambda py, log: False)

    assert launch.run() == 0

    assert launch.events.count("warning") == 1
    title, message = launch.warnings[0]
    assert "unavailable" in title.lower()
    assert "pip could not reach the index" in message
    assert "FFmpeg" in message
    assert "Kokoro" in message


def test_the_one_notice_names_only_the_routes_that_actually_ran(
        launch, windows, tools, commands, proves_nothing, monkeypatch):
    """A machine with no WinGet must not be told WinGet was tried."""
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: False)

    launch.run()

    message = launch.warnings[0][1]
    assert "The app tried the FFmpeg copies already on this computer and " \
           "the app's own verified FFmpeg build." in message
    assert "install through WinGet" not in message, \
        "the notice claimed a route this machine could not attempt"


def test_a_fatal_environment_still_reports_before_there_is_a_gui(monkeypatch,
                                                                 sandbox):
    """Not every failure is recoverable, and a fatal one has nothing to hide behind."""
    warned: list = []
    launched: list = []
    monkeypatch.setattr(bootstrap, "LOG", Log())
    monkeypatch.setattr(bootstrap, "assess_venv_health",
                        lambda **kw: bootstrap.VenvHealth(
                            state=bootstrap.VENV_REPAIRABLE, reason="broken",
                            detail="the interpreter does not run",
                            version=None, ssl=False, tk=False, executes=False))
    monkeypatch.setattr(bootstrap, "show_warning_dialog",
                        lambda title, message: warned.append(title))
    monkeypatch.setattr(bootstrap, "launch_gui",
                        lambda log: launched.append(1) or True)

    assert bootstrap._launch_with_kokoro_healthcheck(
        allow_repair_handoff=False) == 1
    assert warned and not launched


# =========================================================================== #
# F. Second launch is a no-op
# =========================================================================== #
def test_a_second_launch_after_a_repair_does_no_work(
        launch, windows, tools, commands, installs_when_run, proves_everything,
        monkeypatch, sandbox):
    """Launch #1 repairs and pins; launch #2 re-proves that pin and stops."""
    tools.add("winget")
    portable: list = []
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: portable.append(1) or True)

    assert launch.run() == 0
    assert commands, "the first launch did repair"
    pinned = ffmpeg_health.pinned_pair()
    assert pinned is not None

    commands.clear()
    launch.events.clear()

    assert launch.run() == 0

    assert commands == [], "the second launch called a package manager"
    assert portable == [], "the second launch acquired a portable build"
    assert launch.events == ["launch_gui"], "the second launch did work"
    assert launch.warnings == []
    assert ffmpeg_health.pinned_pair().directory == pinned.directory


def test_a_second_launch_repairs_nothing_else_either(
        launch, windows, tools, commands, proves_everything, monkeypatch,
        sandbox):
    """No pip, no venv repair, no Kokoro reinstall on a healthy machine."""
    directory = install(sandbox / "pinned")
    monkeypatch.setenv("PATH", str(directory))
    assert ffmpeg_health.establish() is not None
    forbidden = []
    for name in ("repair_venv", "pip_install_requirements",
                 "ensure_requirements_current", "ensure_kokoro_installed"):
        monkeypatch.setattr(bootstrap, name,
                            lambda *a, **kw: forbidden.append(name))

    assert launch.run() == 0
    assert forbidden == []
    assert launch.events == ["launch_gui"]


# =========================================================================== #
# G. A pin that has stopped being true
# =========================================================================== #
def test_a_broken_pin_enters_ffmpeg_repair_and_leaves_python_alone(
        launch, windows, tools, commands, installs_when_run, monkeypatch,
        sandbox):
    """State names a pair; one binary is gone. That is an FFmpeg problem."""
    monkeypatch.setattr(
        ffmpeg_health, "prove_pair",
        lambda pair, runner=None: ffmpeg_health.Proof(ok=True))
    directory = install(sandbox / "was-good")
    monkeypatch.setenv("PATH", str(directory))
    assert ffmpeg_health.establish() is not None
    (directory / f"ffprobe{EXE}").unlink()

    tools.add("winget")
    package = installs_when_run
    monkeypatch.setenv("PATH", "")
    repairs: list = []
    monkeypatch.setattr(bootstrap, "repair_venv",
                        lambda *a, **kw: repairs.append(1) or (True, "ok"))

    assert launch.run() == 0

    assert commands and commands[0][:2] == ["winget", "install"]
    assert repairs == [], "an FFmpeg problem cost a Python repair"
    assert ffmpeg_health.pinned_pair().directory == package
    assert launch.warnings == []


# =========================================================================== #
# H. Package-manager scope (M5)
# =========================================================================== #
def test_the_ffmpeg_winget_install_asks_for_user_scope(
        sandbox, windows, tools, commands, proves_nothing, monkeypatch):
    """M5, on the actual argv rather than on the source text.

    CSPW-PC is a Standard User with no administrator rights: a machine-wide
    install there prompts for a password nobody has. Naming the scope also
    stops the answer depending on a package default that can change under us.
    """
    tools.add("winget")
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: False)

    bootstrap.repair_ffmpeg(Log())

    argv = commands[0]
    assert argv[:2] == ["winget", "install"]
    assert "Gyan.FFmpeg" in argv
    assert argv[argv.index("--scope") + 1] == "user"


def test_the_python_winget_install_still_asks_for_user_scope(
        windows, tools, commands, monkeypatch):
    """The Phase-1/2 rule, re-asserted because this phase moved scope around."""
    tools.add("winget")
    monkeypatch.setattr(bootstrap, "find_suitable_python",
                        lambda log, prefer_tk=True: None)

    bootstrap.install_python(Log())

    argv = commands[0]
    assert argv[:2] == ["winget", "install"]
    assert bootstrap.WINGET_PYTHON_ID in argv
    assert argv[argv.index("--scope") + 1] == "user"


def test_every_production_winget_install_names_a_scope():
    """Inventory, not a spot check: a new call site must not be able to omit it."""
    installs = []
    for node in ast.walk(_TREE):
        if not isinstance(node, ast.List):
            continue
        head = node.elts[0] if node.elts else None
        if isinstance(head, ast.Constant) and head.value == "winget":
            installs.append([e.value for e in node.elts
                             if isinstance(e, ast.Constant)])
    assert len(installs) == 2, f"expected the Python and FFmpeg calls, got {installs}"
    for argv in installs:
        assert "install" in argv
        assert argv[argv.index("--scope") + 1] == "user", argv


def test_the_windows_launcher_python_fallback_is_user_scope():
    """The root ``.bat``'s own winget call, verified rather than assumed."""
    bat = (REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.bat").read_text(
        encoding="utf-8", errors="replace")
    lines = [ln for ln in bat.splitlines()
             if "winget install" in ln and not ln.strip().startswith("REM")]
    assert lines, "the launcher no longer installs Python"
    for line in lines:
        assert "--scope user" in line, line


def test_no_production_install_asks_for_machine_scope():
    """Never silently escalate because user scope failed."""
    for source in (BOOTSTRAP_SRC,
                   (REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.bat")
                   .read_text(encoding="utf-8", errors="replace")):
        assert "--scope machine" not in source
        assert "runas" not in source.lower()


# =========================================================================== #
# I. No "run it again" loop left in active user-facing text
# =========================================================================== #
_ACTIVE_SOURCES = sorted(
    p for p in UNIVERSAL.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.parametrize("path", _ACTIVE_SOURCES, ids=lambda p: p.name)
def test_no_active_source_tells_a_person_to_re_run_the_same_launcher(path):
    """M3's other half: advice that repeats an identical non-repairing path.

    The launch now performs the repair, so "run Setup_and_Run again" describes
    a path that has already run and already failed. Instructions that name a
    *different* action first — install Python, install Tk support — are not
    this, and are left alone.
    """
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    for phrase in ("setup_and_run again", "re-run setup_and_run",
                   "rerun setup_and_run", "run the launcher again",
                   "double-click setup_and_run again"):
        assert phrase not in text, f"{path.name} still says {phrase!r}"


def test_the_ffmpeg_failure_text_says_retrying_will_not_help():
    message = ffmpeg_health.describe_failure()

    assert "already tried" in message
    assert "Setup_and_Run" not in message
    assert "administrator" in message


def test_no_failure_text_suggests_turning_protection_off():
    """Managed-machine guidance, unchanged and re-asserted."""
    message = ffmpeg_health.describe_failure().lower()

    assert "turning protection off" in message  # as the thing NOT to do
    assert "disable" not in message
    assert "turn off windows" not in message


# =========================================================================== #
# J. Phase-4 runtime trust is untouched by repairing earlier
# =========================================================================== #
def test_the_runtime_still_refuses_an_unproved_pair_after_all_this(
        sandbox, monkeypatch):
    directory = install(sandbox / "found")
    monkeypatch.setenv("PATH", str(directory))
    ffmpeg_utils.refresh()

    assert ffmpeg_utils.have_ffmpeg() is False
    assert ffmpeg_utils.ffmpeg_path() is None
    with pytest.raises(ffmpeg_utils.FFmpegUnavailable):
        ffmpeg_utils.ffmpeg_cmd()


def test_a_repaired_pin_is_what_the_runtime_then_executes(
        sandbox, windows, tools, commands, proves_everything, monkeypatch):
    """Provisioning happens before launch precisely so the gates open."""
    tools.add("winget")
    package = install(sandbox / "winget-package")
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [package])

    assert bootstrap.repair_ffmpeg(Log()).ready
    ffmpeg_utils.refresh()

    assert ffmpeg_utils.verified_ffmpeg() is True
    assert Path(ffmpeg_utils.ffmpeg_cmd()).parent == package
    assert Path(ffmpeg_utils.ffprobe_cmd()).parent == package


def test_ffmpeg_utils_still_provisions_nothing():
    source = (UNIVERSAL / "shared" / "ffmpeg_utils.py").read_text(encoding="utf-8")
    for needle in ("ffmpeg_portable", "repair_ffmpeg", "_install_ffmpeg",
                   "winget", "brew"):
        assert needle not in source


# =========================================================================== #
# K. The launchers stayed thin transport
# =========================================================================== #
@pytest.mark.parametrize("launcher", ["Setup_and_Run-audiobook-creation-tool.bat",
                                      "Setup_and_Run-audiobook-creation-tool.command"])
def test_the_root_launchers_learned_no_ffmpeg_semantics(launcher):
    """They ask bootstrap for a verdict and invoke it. That is all they know."""
    text = (REPO_ROOT / launcher).read_text(encoding="utf-8", errors="replace")
    for needle in ("ffmpeg_health", "ffmpeg_portable", "ffprobe",
                   "Gyan.FFmpeg", "ffmpeg-state"):
        assert needle not in text, f"{launcher} learned {needle}"
