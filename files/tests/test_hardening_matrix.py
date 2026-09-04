"""PRE-PLAN-6 Phase 6 — the gaps the hardening matrix audit actually found.

The matrix has eighteen rows. Most were already covered, strongly, by the tests
Phases 1 to 5 left behind, and re-testing them here would inflate the count
without improving the gate. This module holds only what the audit found missing,
plus the small self-checks that keep the shared AST helper honest.

===  ==================================================  ====================
Row  Scenario                                            Where it lives
===  ==================================================  ====================
1    download failure                                    test_ffmpeg_portable
2    SHA / hash mismatch                                 test_ffmpeg_portable
3    archive missing ffprobe                             test_ffmpeg_portable
4    broken / unexecutable ffmpeg                        test_ffmpeg_health
5    mismatched halves from different directories        test_ffmpeg_health
6    stale pin — changed / deleted                       test_ffmpeg_health
6    stale pin — **moved**                               *here* (gap)
7    requirements validation failure                     test_bootstrap_requirements_state
8    broken venv                                         test_venv_recovery
9    multiple Python versions                            test_bootstrap_python_selection
10   spaced **interpreter** path                         test_bootstrap_python_selection
10   spaced **repository** path                          *here* (gap)
11   winget unavailable → repo-local fallback            test_launch_self_heal
12   no-admin / user-scope semantics                     test_launch_self_heal
13   interrupted staging and promotion                   test_ffmpeg_portable
14   last-known-good preservation                        test_ffmpeg_portable
15   successful repair → second launch no-op             test_launch_self_heal
16   macOS existing venv, brew present/absent            test_launch_self_heal
16   macOS **through the normal launch path**            *here* (gap)
17   full test isolation                                 test_suite_isolation
18   Tk finalisation on worker threads                   test_tk_finalisation
===  ==================================================  ====================

Everything here is mocked or ``tmp_path``-contained. Nothing installs a package,
downloads an archive, or writes production state.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

import source_probe
from shared import bootstrap, ffmpeg_health

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXE = ffmpeg_health.EXE


class Log:
    path = "<sandbox>"

    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str = "") -> None:
        self.lines.append(text)

    def close(self) -> None:
        pass


def install(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        (directory / f"{name}{EXE}").write_text("binary", encoding="utf-8")
    return directory


def completed(returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, "", "")


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Every FFmpeg state path inside ``tmp_path``, nothing on PATH."""
    resources = tmp_path / "runtime-data"
    resources.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", resources)
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [])
    monkeypatch.setattr(ffmpeg_health, "_brew_dirs", lambda: [])
    monkeypatch.setenv("PATH", "")
    return tmp_path


@pytest.fixture
def proves_everything(monkeypatch):
    monkeypatch.setattr(
        ffmpeg_health, "prove_pair",
        lambda pair, runner=None: ffmpeg_health.Proof(
            ok=True, version_text="ffmpeg version 9.0.1"))


# =========================================================================== #
# Row 6 — a stale pin whose build MOVED
#
# The existing suite covers a changed binary and a deleted half. A move is the
# third shape and behaves differently from both: every byte is still there and
# still runs, so a hash would say the installation is fine. What has changed is
# the *path*, and the pin records absolute paths — a WinGet upgrade that
# relocates a versioned package directory is exactly this.
# =========================================================================== #
def test_a_pin_whose_build_moved_is_not_treated_as_working(
        sandbox, proves_everything, monkeypatch):
    original = install(sandbox / "installed" / "9.0.0" / "bin")
    monkeypatch.setenv("PATH", str(original))
    assert ffmpeg_health.establish() is not None
    pinned = ffmpeg_health.pinned_pair()
    assert pinned.directory == original

    moved = sandbox / "installed" / "9.0.1" / "bin"
    moved.parent.mkdir(parents=True, exist_ok=True)
    original.rename(moved)

    assert ffmpeg_health.pinned_pair() is None, \
        "the pin still names a path that no longer holds those binaries"


def test_a_moved_build_is_re_proved_at_its_new_location(
        sandbox, proves_everything, monkeypatch):
    """Not merely invalidated — repaired, without an install."""
    original = install(sandbox / "installed" / "9.0.0" / "bin")
    monkeypatch.setenv("PATH", str(original))
    ffmpeg_health.establish()

    moved = sandbox / "installed" / "9.0.1" / "bin"
    moved.parent.mkdir(parents=True, exist_ok=True)
    original.rename(moved)
    monkeypatch.setenv("PATH", str(moved))

    repaired = ffmpeg_health.ensure_ready(Log())

    assert repaired is not None
    assert repaired.directory == moved
    assert ffmpeg_health.pinned_pair().directory == moved


def test_a_moved_build_grants_no_runtime_permission_until_re_proved(
        sandbox, proves_everything, monkeypatch):
    """Phase-4 trust: an invalid pin is not a licence to run something else."""
    from shared import ffmpeg_utils

    original = install(sandbox / "installed" / "9.0.0" / "bin")
    monkeypatch.setenv("PATH", str(original))
    ffmpeg_health.establish()
    ffmpeg_utils.refresh()
    assert ffmpeg_utils.verified_ffmpeg() is True

    moved = sandbox / "installed" / "9.0.1" / "bin"
    moved.parent.mkdir(parents=True, exist_ok=True)
    original.rename(moved)
    monkeypatch.setenv("PATH", str(moved))
    ffmpeg_utils.refresh()

    assert ffmpeg_utils.verified_ffmpeg() is False
    assert ffmpeg_utils.ffmpeg_path() is None
    with pytest.raises(ffmpeg_utils.FFmpegUnavailable):
        ffmpeg_utils.ffmpeg_cmd()
    ffmpeg_utils.refresh()


# =========================================================================== #
# Row 10 — a REPOSITORY path containing spaces
#
# The interpreter side is covered: candidates are structured argv and a spaced
# executable is never split. The repository side was not. It is the likelier of
# the two on the machines this ships to — ``C:\\Users\\Firstname Lastname\\``,
# ``~/My Documents/`` — and every path the app derives comes from ``__file__``,
# so a single unquoted interpolation anywhere would break all of them at once.
# =========================================================================== #
@pytest.fixture
def spaced_repo(monkeypatch, tmp_path):
    """Relocate every root bootstrap owns into a directory with spaces in it."""
    root = tmp_path / "My Audio Books" / "Audiobook Creation Tool"
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "bin").mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "REPO_ROOT", root)
    monkeypatch.setattr(bootstrap, "VENV_DIR", root / ".venv")
    monkeypatch.setattr(bootstrap, "FILES_DIR", root / "files")
    monkeypatch.setattr(bootstrap, "RESOURCES_DIR", root / "files" / "runtime-data")
    monkeypatch.setattr(bootstrap, "LOGS_DIR",
                        root / "files" / "runtime-data" / "logs")
    return root


def test_the_venv_interpreter_survives_a_spaced_repository_path(spaced_repo):
    interpreter = bootstrap.venv_python()

    assert " " in str(interpreter)
    assert str(interpreter).startswith(str(spaced_repo))
    assert interpreter.parent.parent == spaced_repo / ".venv"


def test_pip_is_one_argv_element_per_token_not_a_command_string(spaced_repo):
    """The failure this prevents is ``["C:/My", "Audio", "Books/...", "-m"]``."""
    argv = bootstrap.venv_pip()

    assert isinstance(argv, list)
    assert argv[1:] == ["-m", "pip"]
    assert " " in argv[0], "the fixture did not actually produce a spaced path"
    assert argv[0] == str(bootstrap.venv_python())
    assert len(argv) == 3, f"a spaced path was split into extra tokens: {argv}"


def test_no_production_command_is_built_by_splitting_a_string():
    """Structural, over every argv-building call in bootstrap.

    ``shlex.split``/``str.split`` on a path is how a spaced repository breaks,
    and it breaks silently: the first element still looks like a program name.
    """
    tree = source_probe.module("shared/bootstrap.py")
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "split":
            # A split of a *path-derived* value is the hazard. Splitting a
            # version string or command output is not.
            source = ast.dump(func.value)
            if any(token in source for token in
                   ("REPO_ROOT", "VENV_DIR", "venv_python", "__file__")):
                offenders.append(ast.unparse(node))
    assert offenders == [], offenders


def test_every_subprocess_argv_in_bootstrap_is_a_list(spaced_repo):
    """A string command line is where quoting rules start deciding correctness."""
    tree = source_probe.module("shared/bootstrap.py")
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", None))
        if name not in ("run", "Popen", "_run") or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, (ast.List, ast.Name, ast.Starred)):
            continue
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            bad.append(ast.unparse(node))
    assert bad == [], bad


def test_the_health_module_derives_its_roots_from_its_own_file():
    """It runs before the venv exists, so it cannot import shared.paths.

    Which means a spaced repository has to work through ``__file__`` alone —
    stated here so the derivation is not quietly replaced with something that
    assumes a well-behaved path.
    """
    assert ffmpeg_health.REPO_ROOT == Path(ffmpeg_health.__file__).resolve() \
        .parent.parent.parent.parent
    assert ffmpeg_health.RESOURCES_DIR.is_absolute()
    assert ffmpeg_health.BIN_DIR.is_absolute()


def test_a_spaced_repository_still_yields_a_usable_state_path(monkeypatch,
                                                              tmp_path):
    resources = tmp_path / "My Audio Books" / "runtime-data"
    resources.mkdir(parents=True)
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", resources)

    path = ffmpeg_health.state_path()

    assert " " in str(path)
    assert path.parent == resources
    assert path.name == ffmpeg_health.HEALTH_STATE_NAME


def test_a_pinned_pair_under_a_spaced_path_round_trips(monkeypatch, tmp_path,
                                                       proves_everything):
    """The pin stores absolute paths as JSON strings; spaces must survive that."""
    resources = tmp_path / "My Audio Books" / "runtime-data"
    resources.mkdir(parents=True)
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", resources)
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", tmp_path / "no-bin")
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [])
    monkeypatch.setattr(ffmpeg_health, "_brew_dirs", lambda: [])
    directory = install(tmp_path / "Program Files" / "FFmpeg build" / "bin")
    monkeypatch.setenv("PATH", str(directory))

    assert ffmpeg_health.establish() is not None
    pinned = ffmpeg_health.pinned_pair()

    assert pinned is not None
    assert pinned.directory == directory
    assert " " in str(pinned.ffmpeg.as_path)
    assert pinned.ffmpeg.as_path.parent == pinned.ffprobe.as_path.parent


# =========================================================================== #
# Row 16 — macOS repair reached through the NORMAL LAUNCH, not a unit call
#
# The Phase-5 macOS matrix drives ``repair_ffmpeg`` directly, which proves the
# orchestration but not the thing M4 was about: an existing ``.venv`` goes
# straight to ``--launch-only``, and that path could not repair at all. These
# drive ``_launch_with_kokoro_healthcheck`` — the function both launch entry
# points call — so the reachability itself is what is under test.
# =========================================================================== #
@pytest.fixture
def mac_launch(monkeypatch, tmp_path, sandbox):
    """A healthy macOS existing-venv launch with every seam recorded."""
    events: list[str] = []
    argv: list[list[str]] = []
    warnings: list[tuple[str, str]] = []

    monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
    monkeypatch.setattr(bootstrap, "IS_MAC", True)
    monkeypatch.setattr(bootstrap, "LOG", Log())
    monkeypatch.setattr(bootstrap, "assess_venv_health",
                        lambda **kw: bootstrap.VenvHealth(
                            state=bootstrap.VENV_HEALTHY, reason="ok",
                            detail="ok", version=(3, 12), ssl=True, tk=True,
                            executes=True))
    monkeypatch.setattr(bootstrap, "venv_python",
                        lambda windowed=False: tmp_path / "python")
    monkeypatch.setattr(bootstrap, "requirements_are_current", lambda: True)
    monkeypatch.setattr(bootstrap, "required_modules_present",
                        lambda py: (True, "ok"))
    monkeypatch.setattr(bootstrap, "import_proof_is_current", lambda: True)
    monkeypatch.setattr(bootstrap, "kokoro_is_healthy", lambda py: (True, "ok"))
    monkeypatch.setattr(bootstrap, "show_repair_dialog",
                        lambda work, **kw: (events.append("repair-dialog")
                                            or work()))
    monkeypatch.setattr(bootstrap, "launch_gui",
                        lambda log: (events.append("launch_gui") or True))
    monkeypatch.setattr(bootstrap, "show_warning_dialog",
                        lambda title, message: (events.append("warning")
                                                or warnings.append((title, message))))
    monkeypatch.setattr(bootstrap, "_refresh_brew_path", lambda: None)

    def _run(cmd, **kwargs):
        argv.append(list(cmd))
        return completed(0)

    monkeypatch.setattr(bootstrap, "_run", _run)

    class Harness:
        events = None

        def __init__(self) -> None:
            self.events = events
            self.argv = argv
            self.warnings = warnings

        def with_brew(self, delivers=None):
            """Homebrew exists, and — if asked — delivers when it is run.

            ``delivers`` is created by the ``brew install`` call rather than
            beforehand: a cellar that already holds a working pair would be
            found by the assessment step and the installer would never be
            reached, so the test would prove nothing about the repair route.
            """
            monkeypatch.setattr(
                bootstrap.shutil, "which",
                lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None)
            if delivers is None:
                return
            delivered: list = []
            monkeypatch.setattr(ffmpeg_health, "_brew_dirs",
                                lambda: list(delivered))
            recording = bootstrap._run

            def installing(cmd, **kwargs):
                result = recording(cmd, **kwargs)
                if result.returncode == 0:
                    install(delivers)
                    delivered.append(delivers)
                return result

            monkeypatch.setattr(bootstrap, "_run", installing)

        def without_brew(self):
            monkeypatch.setattr(bootstrap.shutil, "which", lambda name: None)

        def run(self) -> int:
            return bootstrap._launch_with_kokoro_healthcheck()

    return Harness()


def test_a_normal_mac_launch_reaches_the_homebrew_repair(mac_launch, sandbox,
                                                         proves_everything):
    """M4, through the path a person actually takes.

    Before Phase 5 this launch detected the missing FFmpeg, warned, and opened
    the app anyway — the Homebrew route the first-run ``.command`` knows about
    was unreachable from an existing installation.
    """
    cellar = sandbox / "opt" / "homebrew" / "bin"
    mac_launch.with_brew(delivers=cellar)

    assert mac_launch.run() == 0

    assert ["brew", "install", "ffmpeg"] in mac_launch.argv
    assert ffmpeg_health.pinned_pair().directory == cellar
    assert mac_launch.warnings == [], "a successful repair must say nothing"
    assert mac_launch.events.index("repair-dialog") < \
        mac_launch.events.index("launch_gui")


def test_a_normal_mac_launch_proves_the_pair_before_calling_it_ready(
        mac_launch, sandbox, monkeypatch):
    """``brew`` exiting 0 is not readiness; a pair that will not run is not ready."""
    install(sandbox / "opt" / "homebrew" / "bin")
    monkeypatch.setattr(ffmpeg_health, "_brew_dirs",
                        lambda: [sandbox / "opt" / "homebrew" / "bin"])
    monkeypatch.setattr(
        ffmpeg_health, "prove_pair",
        lambda pair, runner=None: ffmpeg_health.Proof(
            ok=False, detail="refused", failed="ffmpeg"))
    mac_launch.with_brew()

    assert mac_launch.run() == 0

    assert ["brew", "install", "ffmpeg"] in mac_launch.argv
    assert ffmpeg_health.pinned_pair() is None
    assert mac_launch.events.count("warning") == 1
    assert mac_launch.events.index("launch_gui") < \
        mac_launch.events.index("warning")


def test_a_normal_mac_launch_without_brew_installs_nothing_and_says_so(
        mac_launch, sandbox, monkeypatch):
    """No Homebrew install from a launch repair, no loop, and a truthful notice."""
    monkeypatch.setattr(
        ffmpeg_health, "prove_pair",
        lambda pair, runner=None: ffmpeg_health.Proof(
            ok=False, detail="nothing here", failed="ffmpeg"))
    mac_launch.without_brew()

    assert mac_launch.run() == 0

    assert mac_launch.argv == [], f"a package manager ran: {mac_launch.argv}"
    assert mac_launch.events.count("warning") == 1
    message = mac_launch.warnings[0][1]
    assert "Homebrew" in message
    assert "brew.sh" in message
    assert "WinGet" not in message


def test_a_normal_mac_launch_never_reaches_a_windows_portable_route(
        mac_launch, sandbox, monkeypatch):
    """This drop does not invent a macOS portable-binary architecture."""
    portable: list = []
    monkeypatch.setattr(bootstrap, "_download_portable_ffmpeg_windows",
                        lambda log: portable.append(1) or True)
    monkeypatch.setattr(
        ffmpeg_health, "prove_pair",
        lambda pair, runner=None: ffmpeg_health.Proof(
            ok=False, detail="nothing here", failed="ffmpeg"))
    mac_launch.with_brew()

    mac_launch.run()

    assert portable == []


def test_a_second_mac_launch_after_a_repair_calls_no_package_manager(
        mac_launch, sandbox, proves_everything):
    """Row 15's macOS half, through the launch path."""
    cellar = sandbox / "opt" / "homebrew" / "bin"
    mac_launch.with_brew(delivers=cellar)
    assert mac_launch.run() == 0
    assert mac_launch.argv, "the first launch did repair"

    mac_launch.argv.clear()
    mac_launch.events.clear()

    assert mac_launch.run() == 0

    assert mac_launch.argv == []
    assert mac_launch.events == ["launch_gui"]
    assert mac_launch.warnings == []


def test_a_mac_ffmpeg_failure_never_rebuilds_the_environment(
        mac_launch, sandbox, monkeypatch):
    """Minimum scope, on the platform where the repair route is different."""
    repairs: list = []
    monkeypatch.setattr(bootstrap, "repair_venv",
                        lambda *a, **kw: repairs.append(1) or (True, "ok"))
    monkeypatch.setattr(
        ffmpeg_health, "prove_pair",
        lambda pair, runner=None: ffmpeg_health.Proof(
            ok=False, detail="nothing here", failed="ffmpeg"))
    mac_launch.without_brew()

    mac_launch.run()

    assert repairs == []


# =========================================================================== #
# The AST helper has to be able to fail
#
# A structural guard that cannot fail reads as coverage while testing nothing —
# which is exactly the weakness the substring slicing had. These run the helper
# against synthetic code whose answers are known, so the guards built on it are
# themselves grounded.
# =========================================================================== #
def _synthetic(source: str):
    tree = ast.parse(source)
    return next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef))


def test_the_probe_sees_a_call_that_is_really_there():
    fn = _synthetic("def f():\n    _ffmpeg_on_path()\n")
    assert "_ffmpeg_on_path" in source_probe.calls(fn)


def test_the_probe_does_not_see_a_call_that_is_only_mentioned():
    """A docstring naming a symbol is prose, not a call — the old guard's bug."""
    fn = _synthetic('def f():\n    """Never call _ffmpeg_on_path()."""\n    return 1\n')
    assert "_ffmpeg_on_path" not in source_probe.calls(fn)


def test_the_probe_reports_call_order_and_can_see_it_reversed():
    forward = _synthetic("def f():\n    a()\n    b()\n")
    backward = _synthetic("def f():\n    b()\n    a()\n")

    assert source_probe.call_order(forward, ("a", "b")) == ["a", "b"]
    assert source_probe.call_order(backward, ("a", "b")) == ["b", "a"]


def test_the_probe_reads_an_argv_as_values_not_as_text():
    fn = _synthetic('def f():\n    run(["winget", "install", "--scope", "user"])\n')

    assert source_probe.literal_lists(fn) == [
        ["winget", "install", "--scope", "user"]]


def test_the_probe_separates_code_strings_from_docstrings():
    fn = _synthetic('def f():\n    """doc"""\n    return "code"\n')

    assert source_probe.code_strings(fn) == {"code"}


def test_the_probe_follows_an_edge_and_stops_at_a_missing_one():
    assert source_probe.reaches("shared/bootstrap.py", "ensure_ffmpeg",
                                "repair_ffmpeg")
    assert not source_probe.reaches("shared/bootstrap.py", "ensure_ffmpeg",
                                    "a_function_that_does_not_exist")


def test_the_probe_refuses_to_silently_match_nothing():
    """Naming a function that no longer exists must fail, not pass vacuously."""
    with pytest.raises(AssertionError):
        source_probe.function("shared/bootstrap.py", "no_such_function")


def test_no_structural_guard_in_this_phase_slices_python_source():
    """The standing rule, enforced on the modules this phase touched.

    ``source.index("def f(")`` is a claim about where two lines sit in a file.
    Batch and shell launchers are exempt: they have no AST, and their ordering
    really is textual.
    """
    offenders = []
    for name in ("test_ffmpeg_health.py", "test_first_run_contract.py",
                 "test_hardening_matrix.py", "test_launch_self_heal.py",
                 "test_tk_finalisation.py", "test_suite_isolation.py"):
        tree = ast.parse((Path(__file__).parent / name).read_text(
            encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "index"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and node.args[0].value.lstrip().startswith("def ")):
                offenders.append(f"{name}:{node.lineno}: {ast.unparse(node)}")
    assert offenders == [], offenders
