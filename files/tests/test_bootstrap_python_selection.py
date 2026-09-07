"""PRE-PLAN-6 Phase 1 — interpreter discovery, argv shape and the version contract.

**The defect this file pins down (M1).** ``find_suitable_python`` built each
candidate's argv with the equivalent of::

    argv = cand.split() if " " in cand else [cand]

which conflates two unrelated things: *"this is a two-token launcher command"*
(``py -3.12``) and *"this string happens to contain a space"* (a path). So
``C:\\Program Files\\Python312\\python.exe`` became two argv elements,
``["C:\\Program", "Files\\Python312\\python.exe"]``. Both cheap guards were
written as ``len(argv) == 1`` so neither applied, the spawn failed inside
``_interp_version_argv``, its bare ``except`` swallowed the error, and the
candidate was **silently dropped**. A machine-scope Python 3.12 was therefore
undiscoverable on every English Windows install, and a user whose Windows
account name contains a space lost the per-user candidate the same way.

It was a silent capability loss, not a crash, which is exactly why nothing
caught it: ``sys.executable`` and the trailing bare ``python`` candidate usually
masked it.

**The contract now.** Candidates are structured argv sequences from the moment
they are created -- ``["py", "-3.12"]``, ``[r"C:\\Program Files\\...\\python.exe"]``
-- and nothing anywhere infers an argv boundary from whitespace.

**The version contract.** The project's full-feature range is ``>=3.11,<3.13``
(the Kokoro/Chatterbox pins). 3.12 is preferred, 3.11 is accepted, and 3.13+ is
never reported as the preferred fully-compatible result -- it is a degraded
fallback that setup then tries to replace. Note this is *not* the same predicate
as ``_is_kokoro_compatible``, whose floor is Kokoro's own ``>=3.10``.

Nothing here installs, uninstalls or modifies a real interpreter. Every
interpreter is a file in ``tmp_path`` plus a stubbed version probe.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from shared import bootstrap  # noqa: E402

WINDOWS_ONLY = pytest.mark.skipif(
    not bootstrap.IS_WINDOWS,
    reason="exercises the Windows candidate locations (LOCALAPPDATA / ProgramFiles)",
)


class _Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def probe(monkeypatch):
    """A fake interpreter world: which paths exist, what version each reports.

    Returns a recorder whose ``seen`` list holds every argv the version probe was
    handed -- which is where the argv-shattering defect becomes visible.
    """
    versions: dict[tuple[str, ...], tuple[int, int] | None] = {}
    seen: list[list[str]] = []

    def fake_version(argv):
        seen.append(list(argv))
        return versions.get(tuple(argv))

    # Step 1 of find_suitable_python prefers the *running* interpreter. These
    # tests are about the candidate walk, so it is switched off by making
    # sys.executable falsy; monkeypatch restores it.
    monkeypatch.setattr(sys, "executable", "")
    monkeypatch.setattr(bootstrap, "_interp_version_argv", fake_version)
    monkeypatch.setattr(bootstrap, "_tcl_tk_ok", lambda argv: True)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: None)

    from types import SimpleNamespace
    return SimpleNamespace(versions=versions, seen=seen)


def _install(directory: Path, name: str = "python.exe") -> Path:
    """Create a file that stands in for an installed interpreter."""
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / name
    exe.write_bytes(b"")
    return exe


# --------------------------------------------------------------------------- #
# A. Candidate shape -- the root fix
# --------------------------------------------------------------------------- #
def test_every_candidate_is_a_structured_argv_sequence():
    """No candidate is a string that a caller would have to re-parse."""
    for argv in bootstrap._candidate_interpreters():
        assert isinstance(argv, list), f"{argv!r} is not an argv sequence"
        assert argv, "an empty argv is not a candidate"
        assert all(isinstance(token, str) for token in argv)


def test_no_candidate_needs_whitespace_splitting_to_be_understood():
    """A path token may contain spaces; that must not imply two tokens."""
    for argv in bootstrap._candidate_interpreters():
        if len(argv) == 1:
            continue
        # Multi-token candidates are launcher invocations only: `py -3.12`.
        assert argv[0] == "py"
        assert all(" " not in token for token in argv)


@WINDOWS_ONLY
def test_the_launcher_candidates_carry_their_version_as_a_separate_token():
    argv_list = bootstrap._candidate_interpreters()
    assert ["py", "-3.12"] in argv_list
    assert ["py", "-3.11"] in argv_list


# --------------------------------------------------------------------------- #
# B. Paths containing spaces -- the actual defect
# --------------------------------------------------------------------------- #
@WINDOWS_ONLY
def test_a_program_files_python_survives_the_space_in_its_path(
        probe, monkeypatch, tmp_path):
    """The headline case: C:\\Program Files\\Python312\\python.exe.

    Pre-fix this candidate reached the probe as TWO argv elements, the spawn
    failed, the error was swallowed, and a machine-scope 3.12 was invisible.
    """
    progfiles = tmp_path / "Program Files"
    exe = _install(progfiles / "Python312")
    monkeypatch.setenv("ProgramFiles", str(progfiles))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "no-such-local"))
    probe.versions[(str(exe),)] = (3, 12)

    chosen = bootstrap.find_suitable_python(_Log())

    assert chosen == [str(exe)]
    assert [str(exe)] in probe.seen, (
        "the spaced path never reached the probe as a single argv element")


@WINDOWS_ONLY
def test_a_user_profile_python_survives_a_space_in_the_account_name(
        probe, monkeypatch, tmp_path):
    """C:\\Users\\John Smith\\AppData\\Local\\... -- the realistic user hazard."""
    local = tmp_path / "John Smith" / "AppData" / "Local"
    exe = _install(local / "Programs" / "Python" / "Python312")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "no-such-progfiles"))
    probe.versions[(str(exe),)] = (3, 12)

    assert bootstrap.find_suitable_python(_Log()) == [str(exe)]


def test_a_spaced_path_is_never_split_even_when_it_is_the_only_candidate(
        probe, monkeypatch, tmp_path):
    """Platform-independent statement of the same rule."""
    exe = _install(tmp_path / "a directory with spaces")
    monkeypatch.setattr(bootstrap, "_candidate_interpreters",
                        lambda: [[str(exe)]])
    probe.versions[(str(exe),)] = (3, 12)

    assert bootstrap.find_suitable_python(_Log()) == [str(exe)]
    assert probe.seen == [[str(exe)]]


# --------------------------------------------------------------------------- #
# C. The version contract
# --------------------------------------------------------------------------- #
@WINDOWS_ONLY
def test_312_wins_when_312_and_313_are_both_installed(
        probe, monkeypatch, tmp_path):
    local = tmp_path / "Local"
    exe312 = _install(local / "Programs" / "Python" / "Python312")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "none"))
    probe.versions[(str(exe312),)] = (3, 12)
    # A 3.13 that PATH would hand over first.
    monkeypatch.setattr(bootstrap.shutil, "which",
                        lambda name: "python-from-path" if name == "python" else None)
    probe.versions[("python",)] = (3, 13)

    assert bootstrap.find_suitable_python(_Log()) == [str(exe312)]


@WINDOWS_ONLY
def test_path_order_cannot_make_313_beat_a_compatible_312(
        probe, monkeypatch, tmp_path):
    """Selection is by version predicate, never by PATH order."""
    local = tmp_path / "Local"
    exe312 = _install(local / "Programs" / "Python" / "Python312")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "none"))
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: f"/path/{name}")
    probe.versions[("py", "-3.12")] = (3, 13)   # even a lying launcher
    probe.versions[("python",)] = (3, 13)
    probe.versions[(str(exe312),)] = (3, 12)

    chosen = bootstrap.find_suitable_python(_Log())

    assert chosen == [str(exe312)]
    assert bootstrap.is_full_feature_python(probe.versions[tuple(chosen)])


def test_a_compatible_311_is_accepted_when_no_312_exists(
        probe, monkeypatch, tmp_path):
    exe = _install(tmp_path / "py311")
    monkeypatch.setattr(bootstrap, "_candidate_interpreters",
                        lambda: [[str(exe)]])
    probe.versions[(str(exe),)] = (3, 11)

    assert bootstrap.find_suitable_python(_Log()) == [str(exe)]


def test_a_313_only_machine_is_not_reported_as_fully_compatible(
        probe, monkeypatch, tmp_path):
    """3.13 may still be returned as a degraded fallback -- but not as success.

    The contract is that selection never *labels* 3.13+ the preferred
    fully-compatible result. run_setup then tries to obtain a 3.12.
    """
    exe = _install(tmp_path / "py313")
    monkeypatch.setattr(bootstrap, "_candidate_interpreters",
                        lambda: [[str(exe)]])
    probe.versions[(str(exe),)] = (3, 13)
    log = _Log()

    chosen = bootstrap.find_suitable_python(log)

    assert chosen == [str(exe)]
    assert bootstrap.is_full_feature_python((3, 13)) is False
    assert "degraded" in log.text.lower() or "not a fully" in log.text.lower()


def test_the_full_feature_range_is_311_to_312_inclusive():
    assert bootstrap.is_full_feature_python((3, 11)) is True
    assert bootstrap.is_full_feature_python((3, 12)) is True
    assert bootstrap.is_full_feature_python((3, 13)) is False
    assert bootstrap.is_full_feature_python((3, 14)) is False
    assert bootstrap.is_full_feature_python(None) is False


def test_the_project_floor_is_311_and_is_not_widened_to_310():
    """Kokoro's wheels start at 3.10; the *project* does not.

    These are two different questions and must not collapse into one predicate.
    """
    assert bootstrap.is_full_feature_python((3, 10)) is False
    assert bootstrap._is_kokoro_compatible((3, 10)) is True


# --------------------------------------------------------------------------- #
# D. Candidates that cannot or should not be probed
# --------------------------------------------------------------------------- #
@WINDOWS_ONLY
def test_the_py_launcher_is_not_probed_when_it_is_absent(
        probe, monkeypatch, tmp_path):
    """HOME-PC has no resolvable `py`; spawning it twice is pure waste."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "none"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "none2"))

    bootstrap.find_suitable_python(_Log())

    assert not any(argv and argv[0] == "py" for argv in probe.seen)


@WINDOWS_ONLY
def test_the_py_launcher_is_probed_when_it_is_present(
        probe, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "none"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "none2"))
    monkeypatch.setattr(bootstrap.shutil, "which",
                        lambda name: r"C:\Windows\py.exe" if name == "py" else None)
    probe.versions[("py", "-3.12")] = (3, 12)

    assert bootstrap.find_suitable_python(_Log()) == ["py", "-3.12"]


def test_a_candidate_path_that_does_not_exist_is_never_spawned(
        probe, monkeypatch, tmp_path):
    missing = tmp_path / "gone" / "python.exe"
    monkeypatch.setattr(bootstrap, "_candidate_interpreters",
                        lambda: [[str(missing)]])

    assert bootstrap.find_suitable_python(_Log()) is None
    assert probe.seen == []


def test_a_windowsapps_style_stub_that_reports_no_version_is_skipped(
        probe, monkeypatch, tmp_path):
    """The Store redirector exists and runs, but yields no usable version."""
    stub = _install(tmp_path / "WindowsApps")
    good = _install(tmp_path / "real312")
    monkeypatch.setattr(bootstrap, "_candidate_interpreters",
                        lambda: [[str(stub)], [str(good)]])
    probe.versions[(str(stub),)] = None      # probe returns nothing usable
    probe.versions[(str(good),)] = (3, 12)

    assert bootstrap.find_suitable_python(_Log()) == [str(good)]


def test_a_candidate_that_cannot_execute_yields_no_version_instead_of_raising(
        tmp_path, monkeypatch):
    """The real probe, not a stub: a non-executable file must not raise."""
    monkeypatch.setattr(sys, "executable", "")
    broken = _install(tmp_path / "broken")
    assert bootstrap._interp_version_argv([str(broken)]) is None


def test_no_suitable_python_is_reported_truthfully(probe, monkeypatch):
    monkeypatch.setattr(bootstrap, "_candidate_interpreters", lambda: [])
    log = _Log()

    assert bootstrap.find_suitable_python(log) is None
    assert "no suitable python" in log.text.lower()
