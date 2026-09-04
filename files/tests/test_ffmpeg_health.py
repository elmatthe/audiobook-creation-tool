"""The proven ffmpeg + ffprobe pair — v0.6.2 Plan 5, Phase 15 blocker remediation.

**The defect this file pins down.** The Windows manual matrix stopped at item 5
with ``This file could not be read``. The machine had two FFmpeg installations:
``C:\\ffmpeg``, which Smart App Control refuses to execute
(``VerifiedAndReputableDesktop``, ``WinError 4551`` / ``0xC0E90002``), and a
WinGet ``Gyan.FFmpeg`` build that runs perfectly. ``C:\\ffmpeg\\bin`` came first
on PATH, so that is what the app picked — and ``have_ffmpeg()`` returned ``True``
because the old contract was *"available if a path can be found"*. Setup agreed,
the GUI printed "FFmpeg detected", and the first thing that ever **ran** ffprobe
was the preflight of a real 13-hour audiobook, in front of the user.

**The contract these tests hold.** FFmpeg capability exists only through one
coherent ffmpeg + ffprobe pair that setup or repair has established as usable.
Four properties carry it, and each has its own section below:

* pairs are **coherent** — both halves from one installation directory, never
  assembled from two;
* readiness means the pair **executed**, not that it resolved;
* the proven pair is **pinned**, so PATH order cannot re-decide later;
* a candidate already proven unusable is **never executed again**, because
  attempting to run a blocked binary is itself what raises the Windows Security
  notification.

Determinism and safety
----------------------
Nothing here runs a real ffmpeg, downloads anything, installs anything or reads
the machine's real state file: every test drives the pure seams with a stub
runner over generated placeholder files under ``tmp_path``. The one place the
real binaries are exercised is the live Stage 1 proof, which is recorded in the
Handoff rather than run here.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path

import pytest

from shared import bootstrap
from shared import ffmpeg_health
from shared import ffmpeg_utils

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXE = ffmpeg_health.EXE


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    """Point every test at a disposable state file and an empty candidate set.

    Autouse on purpose: a test that accidentally read the developer's real
    ``files/runtime-data/ffmpeg-state.json`` would pass or fail according to
    which machine ran it.
    """
    resources = tmp_path / "runtime-data"
    resources.mkdir()
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", resources)
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [])
    monkeypatch.setattr(ffmpeg_health, "_brew_dirs", lambda: [])
    ffmpeg_utils.refresh()
    yield resources
    ffmpeg_utils.refresh()


def install(directory: Path, *, ffmpeg: bool = True, ffprobe: bool = True,
            body: str = "binary") -> Path:
    """A placeholder installation directory. Never a real executable."""
    directory.mkdir(parents=True, exist_ok=True)
    if ffmpeg:
        (directory / f"ffmpeg{EXE}").write_text(body, encoding="utf-8")
    if ffprobe:
        (directory / f"ffprobe{EXE}").write_text(body, encoding="utf-8")
    return directory


def runner_for(*, healthy: set = (), version: str = "ffmpeg version 9.0"):
    """A stub ``-version`` runner, and a record of everything it executed.

    The record is the point: several tests below are about what must *not* be
    run, and only a spy can prove a binary was left alone.
    """
    healthy_keys = {os.path.normcase(str(Path(p))) for p in healthy}
    executed: list[str] = []

    def run(executable) -> tuple:
        executed.append(str(executable))
        if os.path.normcase(str(executable)) in healthy_keys:
            return True, version
        return False, "[WinError 4551] An Application Control policy has blocked this file"

    run.executed = executed  # type: ignore[attr-defined]
    return run


def both(directory: Path) -> set:
    return {directory / f"ffmpeg{EXE}", directory / f"ffprobe{EXE}"}


def pin(monkeypatch, directory: Path, *, healthy: Path | None = None):
    """Put *directory* where discovery looks, then prove and pin it.

    Without the PATH half these tests would call ``establish`` with nothing to
    discover, and then assert against ``None`` -- which is how two of them
    originally passed while proving nothing at all.
    """
    monkeypatch.setenv("PATH", str(directory))
    pair = ffmpeg_health.establish(
        runner=runner_for(healthy=both(healthy or directory)))
    return pair


class Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


# --------------------------------------------------------------------------- #
# A. Pair coherence — never one installation's ffmpeg with another's ffprobe
# --------------------------------------------------------------------------- #


def test_a_directory_with_both_halves_is_a_pair(tmp_path):
    directory = install(tmp_path / "good")
    pair = ffmpeg_health.pair_in(directory)
    assert pair is not None
    assert pair.is_coherent()
    assert pair.ffmpeg.as_path.parent == pair.ffprobe.as_path.parent


@pytest.mark.parametrize("missing", ["ffmpeg", "ffprobe"])
def test_half_an_installation_is_not_a_candidate(tmp_path, missing):
    """The failure this prevents is silent, so it is worth stating twice.

    If a directory holding only ffmpeg could contribute, the missing half would
    be filled in from somewhere else — and the run would be using two different
    FFmpeg builds without anything saying so.
    """
    directory = install(tmp_path / "partial",
                        ffmpeg=(missing != "ffmpeg"),
                        ffprobe=(missing != "ffprobe"))
    assert ffmpeg_health.pair_in(directory) is None


def test_a_lone_ffmpeg_never_borrows_another_directorys_ffprobe(monkeypatch, tmp_path):
    lonely = install(tmp_path / "lonely", ffprobe=False)
    complete = install(tmp_path / "complete")
    monkeypatch.setenv("PATH", os.pathsep.join([str(lonely), str(complete)]))

    pairs = ffmpeg_health.discover_pairs()
    assert [p.directory for p in pairs] == [complete]
    assert all(p.is_coherent() for p in pairs)


def test_discovery_keeps_path_order_and_deduplicates(monkeypatch, tmp_path):
    first = install(tmp_path / "first")
    second = install(tmp_path / "second")
    monkeypatch.setenv("PATH", os.pathsep.join(
        [str(first), str(second), str(first)]))
    assert [p.directory for p in ffmpeg_health.discover_pairs()] == [first, second]


def test_the_bundled_directory_is_considered_before_path(monkeypatch, tmp_path):
    bundled = install(tmp_path / "bin")
    other = install(tmp_path / "elsewhere")
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", bundled)
    monkeypatch.setenv("PATH", str(other))
    assert [p.directory for p in ffmpeg_health.discover_pairs()] == [bundled, other]


def test_a_winget_package_is_a_candidate_even_when_not_on_path(monkeypatch, tmp_path):
    """A fresh ``winget install`` does not touch a running process's PATH.

    Before Phase 15 that made setup conclude the install had failed and go and
    fetch a second, worse copy.
    """
    package = install(tmp_path / "WinGet" / "Gyan.FFmpeg_x" / "ffmpeg-9.0-full_build" / "bin")
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [package])
    assert [p.directory for p in ffmpeg_health.discover_pairs()] == [package]


def test_the_winget_build_directory_is_not_hard_coded():
    """**Structural.** A ``winget upgrade`` renames the versioned folder.

    Pinning today's ``ffmpeg-9.0-full_build`` would break silently at the next
    upgrade, which is exactly the class of failure this module exists to stop.
    """
    source = (REPO_ROOT / "scripts" / "Universal" / "shared"
              / "ffmpeg_health.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    # Structural, not prose: the comment explaining *why* the version must not
    # be pinned naturally contains a version, and a substring guard would fail
    # on that sentence while missing a real hard-coded path.
    literals = [node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node is not ast.get_docstring(tree, clean=False)]
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
    winget = functions["_winget_package_dirs"]
    doc = ast.get_docstring(winget, clean=False)
    inside = [node.value for node in ast.walk(winget)
              if isinstance(node, ast.Constant) and isinstance(node.value, str)
              and node.value != doc]
    assert not any("full_build" in text for text in inside), inside
    assert "ffmpeg-*/bin" in inside
    assert any("Gyan.FFmpeg" in text for text in literals)


# --------------------------------------------------------------------------- #
# B. Proof — both halves must actually execute
# --------------------------------------------------------------------------- #


def test_a_pair_where_both_halves_run_is_proven(tmp_path):
    directory = install(tmp_path / "good")
    pair = ffmpeg_health.pair_in(directory)
    proof = ffmpeg_health.prove_pair(pair, runner=runner_for(healthy=both(directory)))
    assert proof.ok is True
    assert proof.version_text == "ffmpeg version 9.0"


def test_ffmpeg_runs_but_ffprobe_is_blocked_is_unhealthy(tmp_path):
    """The Phase 15 shape exactly: one half usable, the other refused."""
    directory = install(tmp_path / "half-blocked")
    pair = ffmpeg_health.pair_in(directory)
    runner = runner_for(healthy={directory / f"ffmpeg{EXE}"})
    proof = ffmpeg_health.prove_pair(pair, runner=runner)
    assert proof.ok is False
    assert proof.failed == "ffprobe"
    assert "4551" in proof.detail


def test_ffprobe_runs_but_ffmpeg_is_blocked_is_unhealthy(tmp_path):
    directory = install(tmp_path / "other-half")
    pair = ffmpeg_health.pair_in(directory)
    runner = runner_for(healthy={directory / f"ffprobe{EXE}"})
    proof = ffmpeg_health.prove_pair(pair, runner=runner)
    assert proof.ok is False
    assert proof.failed == "ffmpeg"


def test_a_failing_ffmpeg_short_circuits_before_ffprobe(tmp_path):
    directory = install(tmp_path / "dead")
    pair = ffmpeg_health.pair_in(directory)
    runner = runner_for(healthy=set())
    ffmpeg_health.prove_pair(pair, runner=runner)
    assert runner.executed == [str(pair.ffmpeg.as_path)], (
        "a pair already known unusable was probed twice")


def test_a_hanging_binary_is_unhealthy_rather_than_a_hung_launch(monkeypatch, tmp_path):
    directory = install(tmp_path / "hangs")

    def hang(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, ffmpeg_health.PROBE_TIMEOUT)

    monkeypatch.setattr(ffmpeg_health._sp, "run", hang)
    ok, detail = ffmpeg_health._run_version(directory / f"ffmpeg{EXE}")
    assert ok is False and "timed out" in detail


def test_the_probe_is_bounded_and_hidden(monkeypatch, tmp_path):
    """Routed through the shared no-window wrappers, with a timeout.

    A bare ``subprocess.run`` here would flash a console window under
    ``pythonw.exe`` — the thing every other binary call in this app avoids.
    """
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ffmpeg version 9.0\n", stderr="")

    monkeypatch.setattr(ffmpeg_health._sp, "run", fake_run)
    ffmpeg_health._run_version(tmp_path / f"ffmpeg{EXE}")
    assert seen["timeout"] == ffmpeg_health.PROBE_TIMEOUT
    assert seen["capture_output"] is True
    assert seen["cmd"][1] == "-version"


def test_a_nonzero_exit_is_unhealthy_and_reports_the_code(monkeypatch, tmp_path):
    """``C:\\ffmpeg\\bin\\ffmpeg.exe`` exits 0xC0E90002 rather than failing to start."""
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 3236495362, stdout="", stderr="blocked")

    monkeypatch.setattr(ffmpeg_health._sp, "run", fake_run)
    ok, detail = ffmpeg_health._run_version(tmp_path / f"ffmpeg{EXE}")
    assert ok is False and "3236495362" in detail


def test_proving_a_pair_does_not_modify_it(tmp_path):
    directory = install(tmp_path / "untouched")
    pair = ffmpeg_health.pair_in(directory)
    before = {p: p.read_bytes() for p in directory.iterdir()}
    ffmpeg_health.prove_pair(pair, runner=runner_for(healthy=both(directory)))
    assert {p: p.read_bytes() for p in directory.iterdir()} == before


def test_the_recorded_detail_is_bounded(monkeypatch, tmp_path):
    directory = install(tmp_path / "chatty")
    pair = ffmpeg_health.pair_in(directory)

    def noisy(executable):
        return False, "x" * 5000

    proof = ffmpeg_health.prove_pair(pair, runner=noisy)
    assert len(proof.detail) <= ffmpeg_health.MAX_DETAIL


# --------------------------------------------------------------------------- #
# C. The bad-first / good-second machine
# --------------------------------------------------------------------------- #


@pytest.fixture()
def messy(monkeypatch, tmp_path):
    """This machine: a blocked installation first on PATH, a working one after."""
    blocked = install(tmp_path / "blocked", body="refused")
    working = install(tmp_path / "working", body="fine")
    monkeypatch.setenv("PATH", os.pathsep.join([str(blocked), str(working)]))
    return blocked, working


def test_the_blocked_first_pair_is_rejected_and_the_later_one_wins(messy):
    blocked, working = messy
    pair = ffmpeg_health.establish(Log(), runner=runner_for(healthy=both(working)))
    assert pair is not None
    assert pair.directory == working
    assert pair.directory != blocked


def test_the_winning_pair_is_pinned_to_disk(messy):
    _blocked, working = messy
    ffmpeg_health.establish(runner=runner_for(healthy=both(working)))
    assert ffmpeg_health.pinned_pair().directory == working


def test_runtime_then_uses_the_working_pair_despite_path_order(messy):
    """The heart of the fix, asserted through the API the app actually calls."""
    blocked, working = messy
    ffmpeg_health.establish(runner=runner_for(healthy=both(working)))
    ffmpeg_utils.refresh()

    assert Path(ffmpeg_utils.ffmpeg_path()).parent == working
    assert Path(ffmpeg_utils.ffprobe_path()).parent == working
    assert str(blocked) not in ffmpeg_utils.ffmpeg_cmd()
    assert ffmpeg_utils.verified_ffmpeg() is True


def test_no_usable_pair_is_reported_truthfully(messy):
    ffmpeg_health.establish(runner=runner_for(healthy=set()))
    assert ffmpeg_health.pinned_pair() is None
    ffmpeg_utils.refresh()
    assert ffmpeg_utils.verified_ffmpeg() is False


def test_the_rejected_candidate_is_never_executed_a_second_time(messy):
    """Running a blocked binary is what raises the Windows notification.

    So the user must see it at most once per broken installation, during setup —
    never again on a later repair, and never during a conversion.
    """
    blocked, working = messy
    first = runner_for(healthy=both(working))
    ffmpeg_health.establish(runner=first)
    assert str(blocked / f"ffmpeg{EXE}") in first.executed

    # Force a repair by removing the pinned pair.
    (working / f"ffmpeg{EXE}").unlink()
    second = runner_for(healthy=set())
    ffmpeg_health.establish(runner=second)
    assert not any(str(blocked) in entry for entry in second.executed), (
        "a candidate already proven blocked was executed again")


def test_a_blocked_bundled_directory_does_not_become_ready(monkeypatch, tmp_path):
    """``files/bin`` is preferred, but preference is not proof.

    A stale or blocked bundled copy used to be unbeatable: it was checked first
    and accepted on existence alone.
    """
    bundled = install(tmp_path / "bin", body="refused")
    working = install(tmp_path / "working")
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", bundled)
    monkeypatch.setenv("PATH", str(working))

    pair = ffmpeg_health.establish(runner=runner_for(healthy=both(working)))
    assert pair.directory == working


# --------------------------------------------------------------------------- #
# D. The remembered state
# --------------------------------------------------------------------------- #


def test_a_proof_writes_state_carrying_the_pair_identity(
        monkeypatch, tmp_path, isolated_state):
    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)

    payload = json.loads((isolated_state / "ffmpeg-state.json").read_text(encoding="utf-8"))
    assert payload["proof_version"] == ffmpeg_health.PROOF_VERSION
    for half in ("ffmpeg", "ffprobe"):
        entry = payload["pair"][half]
        assert entry["path"].endswith(f"{half}{EXE}")
        assert entry["size"] > 0
        assert len(entry["sha256"]) == 64
    assert payload["pair"]["version_text"] == "ffmpeg version 9.0"


def test_an_unchanged_pair_is_reused_without_re_establishing(monkeypatch, tmp_path):
    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)
    assert ffmpeg_health.pinned_pair().directory == directory


def test_a_missing_state_file_means_nothing_is_pinned():
    assert ffmpeg_health.load_state().pair is None
    assert ffmpeg_health.pinned_pair() is None


def test_a_malformed_state_degrades_to_nothing_pinned(isolated_state):
    (isolated_state / "ffmpeg-state.json").write_text("{not json", encoding="utf-8")
    assert ffmpeg_health.load_state().pair is None


def test_a_state_from_an_older_contract_is_not_trusted(
        monkeypatch, tmp_path, isolated_state):
    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)
    path = isolated_state / "ffmpeg-state.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["proof_version"] = ffmpeg_health.PROOF_VERSION - 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert ffmpeg_health.pinned_pair() is None


def test_a_hand_edited_mixed_pair_is_refused(monkeypatch, tmp_path, isolated_state):
    """Two directories in one state entry is not a pair, however it got there."""
    good = install(tmp_path / "good")
    other = install(tmp_path / "other")
    pin(monkeypatch, good)
    path = isolated_state / "ffmpeg-state.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["pair"]["ffprobe"]["path"] = str(other / f"ffprobe{EXE}")
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert ffmpeg_health.load_state().pair is None


@pytest.mark.parametrize("half", ["ffmpeg", "ffprobe"])
def test_a_deleted_half_invalidates_the_pin(monkeypatch, tmp_path, half):
    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)
    assert ffmpeg_health.pinned_pair() is not None, "nothing was pinned to invalidate"
    (directory / f"{half}{EXE}").unlink()
    assert ffmpeg_health.pinned_pair() is None


@pytest.mark.parametrize("half", ["ffmpeg", "ffprobe"])
def test_a_changed_binary_invalidates_the_pin(monkeypatch, tmp_path, half):
    """A ``winget upgrade`` replaces the bytes; the old proof no longer applies."""
    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)
    assert ffmpeg_health.pinned_pair() is not None, "nothing was pinned to invalidate"
    target = directory / f"{half}{EXE}"
    target.write_text("a different build entirely", encoding="utf-8")
    os.utime(target, ns=(1, 1))
    assert ffmpeg_health.pinned_pair() is None


def test_reordering_path_does_not_move_the_pinned_pair(monkeypatch, tmp_path):
    blocked = install(tmp_path / "blocked")
    working = install(tmp_path / "working")
    monkeypatch.setenv("PATH", str(working))
    ffmpeg_health.establish(runner=runner_for(healthy=both(working)))

    # The user installs something else, or PATH is reordered underneath us.
    monkeypatch.setenv("PATH", os.pathsep.join([str(blocked), str(working)]))
    ffmpeg_utils.refresh()
    assert Path(ffmpeg_utils.ffmpeg_path()).parent == working


def test_an_unrelated_new_installation_does_not_redirect_runtime(monkeypatch, tmp_path):
    working = install(tmp_path / "working")
    monkeypatch.setenv("PATH", str(working))
    ffmpeg_health.establish(runner=runner_for(healthy=both(working)))

    newcomer = install(tmp_path / "newcomer")
    monkeypatch.setenv("PATH", os.pathsep.join([str(newcomer), str(working)]))
    ffmpeg_utils.refresh()
    assert Path(ffmpeg_utils.ffprobe_path()).parent == working


def test_the_state_file_is_local_disposable_and_not_tracked():
    """It lives under ``files/runtime-data/``, which ``.gitignore`` excludes whole."""
    assert ffmpeg_health.state_path().parent.name == "runtime-data"
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "files/runtime-data/" in ignored
    tracked = REPO_ROOT / "files" / "runtime-data" / ffmpeg_health.HEALTH_STATE_NAME
    assert "runtime-data" not in {p.name for p in (REPO_ROOT / "scripts").iterdir()}
    assert tracked.parent.name == "runtime-data"


def test_an_unwritable_state_directory_is_not_fatal(monkeypatch, tmp_path):
    """It must not crash, and it must not claim a pin it could not record.

    This previously asserted that ``establish`` still returned the pair — on the
    reasoning that losing the record only costs a re-proof. That conflated two
    facts. *Both binaries ran* is true; *this is now the active runtime pair* is
    not, when nothing could be written. Phase 4 makes consumers trust the active
    pin, so returning an unrecorded pair as one would let the app act on a pin
    that no later run can see. Not fatal, still retryable, but not a pin.
    """
    directory = install(tmp_path / "good")
    blocker = tmp_path / "blocker"
    blocker.write_text("this is a file, not a directory", encoding="utf-8")
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", blocker / "runtime-data")
    monkeypatch.setenv("PATH", str(directory))

    pair = ffmpeg_health.establish(runner=runner_for(healthy=both(directory)))

    assert pair is None, "an unrecorded proof must not be reported as pinned"
    assert ffmpeg_health.pinned_pair() is None


def test_a_state_write_failure_leaves_the_run_retryable(monkeypatch, tmp_path):
    """The other half of "not fatal": once writing works, it pins normally."""
    directory = install(tmp_path / "good")
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", tmp_path / "state")
    monkeypatch.setenv("PATH", str(directory))
    runner = runner_for(healthy=both(directory))

    monkeypatch.setattr(ffmpeg_health, "save_state", lambda state: False)
    assert ffmpeg_health.establish(runner=runner) is None

    monkeypatch.undo()
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", tmp_path / "state")
    monkeypatch.setenv("PATH", str(directory))
    assert ffmpeg_health.establish(runner=runner_for(healthy=both(directory))) \
        is not None


# --------------------------------------------------------------------------- #
# E. ensure_ready — what a launch does
# --------------------------------------------------------------------------- #


def test_a_valid_pin_is_re_proved_and_reused(monkeypatch, tmp_path):
    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)

    runner = runner_for(healthy=both(directory))
    pair = ffmpeg_health.ensure_ready(runner=runner)
    assert pair.directory == directory
    assert len(runner.executed) == 2, "a launch proves the pinned pair and nothing else"


def test_a_launch_never_executes_other_candidates_while_the_pin_holds(monkeypatch, tmp_path):
    """Sweeping PATH on every launch is how a launch would provoke a toast."""
    working = install(tmp_path / "working")
    stranger = install(tmp_path / "stranger")
    monkeypatch.setenv("PATH", str(working))
    ffmpeg_health.establish(runner=runner_for(healthy=both(working)))

    monkeypatch.setenv("PATH", os.pathsep.join([str(stranger), str(working)]))
    runner = runner_for(healthy=both(working))
    ffmpeg_health.ensure_ready(runner=runner)
    assert not any(str(stranger) in entry for entry in runner.executed)


def test_a_pinned_pair_that_stops_running_triggers_repair(monkeypatch, tmp_path):
    """Nothing about the bytes changes when a policy does, so identity cannot
    see this. Re-proving the pinned pair is what does."""
    first = install(tmp_path / "first")
    second = install(tmp_path / "second")
    monkeypatch.setenv("PATH", os.pathsep.join([str(first), str(second)]))
    ffmpeg_health.establish(runner=runner_for(healthy=both(first)))
    assert ffmpeg_health.pinned_pair().directory == first

    # The machine now refuses the pair it accepted yesterday.
    pair = ffmpeg_health.ensure_ready(Log(), runner=runner_for(healthy=both(second)))
    assert pair.directory == second


def test_a_vanished_pin_repairs_without_being_asked(monkeypatch, tmp_path):
    first = install(tmp_path / "first")
    second = install(tmp_path / "second")
    monkeypatch.setenv("PATH", os.pathsep.join([str(first), str(second)]))
    ffmpeg_health.establish(runner=runner_for(healthy=both(first)))

    for entry in first.iterdir():
        entry.unlink()
    pair = ffmpeg_health.ensure_ready(runner=runner_for(healthy=both(second)))
    assert pair is not None and pair.directory == second


def test_the_failure_message_names_no_security_product_to_disable():
    message = ffmpeg_health.describe_failure()
    lowered = message.lower()
    for banned in ("disable", "turn off smart app", "exclusion", "defender off"):
        assert banned not in lowered, banned
    assert "administrator" in lowered


# --------------------------------------------------------------------------- #
# F. What the rest of the application sees
# --------------------------------------------------------------------------- #


def test_both_halves_always_come_from_the_same_installation(monkeypatch, tmp_path):
    lonely = install(tmp_path / "lonely", ffprobe=False)
    complete = install(tmp_path / "complete")
    monkeypatch.setenv("PATH", os.pathsep.join([str(lonely), str(complete)]))
    ffmpeg_utils.refresh()

    assert Path(ffmpeg_utils.ffmpeg_path()).parent == Path(ffmpeg_utils.ffprobe_path()).parent


def test_have_ffmpeg_is_false_when_no_coherent_pair_exists(monkeypatch, tmp_path):
    install(tmp_path / "lonely", ffprobe=False)
    monkeypatch.setenv("PATH", str(tmp_path / "lonely"))
    ffmpeg_utils.refresh()
    assert ffmpeg_utils.have_ffmpeg() is False
    assert ffmpeg_utils.ffmpeg_path() is None


def test_have_ffmpeg_is_true_for_an_unproven_but_coherent_pair(monkeypatch, tmp_path):
    """Still not a claim that it runs — that is ``verified_ffmpeg``."""
    directory = install(tmp_path / "found")
    monkeypatch.setenv("PATH", str(directory))
    ffmpeg_utils.refresh()
    assert ffmpeg_utils.have_ffmpeg() is True
    assert ffmpeg_utils.verified_ffmpeg() is False


def test_the_status_line_distinguishes_found_from_verified(monkeypatch, tmp_path):
    directory = install(tmp_path / "found")
    monkeypatch.setenv("PATH", str(directory))
    ffmpeg_utils.refresh()
    assert "not yet verified" in ffmpeg_utils.status_line()

    pin(monkeypatch, directory)
    ffmpeg_utils.refresh()
    assert ffmpeg_utils.status_line() == "FFmpeg verified and ready."


def test_nothing_says_ffmpeg_detected_any_more():
    """**Structural.** The exact sentence that misled the maintainer."""
    panel = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools"
             / "m4b_converter.py").read_text(encoding="utf-8")
    tree = ast.parse(panel)
    # Structural: the comment recording that the sentence was removed contains
    # the sentence, so only string *literals* may be inspected.
    said = [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and "FFmpeg detected" in node.value]
    assert said == [], said
    assert "status_line()" in panel


def test_the_commands_still_receive_plain_strings(monkeypatch, tmp_path):
    """Every consumer builds argv lists; a Path here would change their shape."""
    directory = install(tmp_path / "good")
    monkeypatch.setenv("PATH", str(directory))
    ffmpeg_utils.refresh()
    assert isinstance(ffmpeg_utils.ffmpeg_cmd(), str)
    assert isinstance(ffmpeg_utils.ffprobe_cmd(), str)


def test_the_bare_name_fallback_survives_for_command_building(monkeypatch):
    monkeypatch.setenv("PATH", "")
    ffmpeg_utils.refresh()
    assert ffmpeg_utils.ffmpeg_cmd() == "ffmpeg"
    assert ffmpeg_utils.ffprobe_cmd() == "ffprobe"


# --------------------------------------------------------------------------- #
# G. Setup and the launch fast path
# --------------------------------------------------------------------------- #


def test_setup_no_longer_accepts_a_path_it_never_executed():
    """**Structural.** ``ensure_ffmpeg`` used to return on ``shutil.which`` alone."""
    source = (REPO_ROOT / "scripts" / "Universal" / "shared"
              / "bootstrap.py").read_text(encoding="utf-8")
    body = source[source.index("def ensure_ffmpeg("):source.index("def _install_ffmpeg(")]
    assert "ffmpeg_health.ensure_ready" in body
    assert "_ffmpeg_on_path()" not in body
    assert "_ffmpeg_in_bin()" not in body


def test_setup_reports_ready_only_when_a_pair_was_proven(monkeypatch, tmp_path):
    install(tmp_path / "blocked")
    monkeypatch.setenv("PATH", str(tmp_path / "blocked"))
    monkeypatch.setattr(ffmpeg_health, "prove_pair",
                        lambda pair, runner=None: ffmpeg_health.Proof(
                            ok=False, detail="blocked", failed="ffprobe"))
    monkeypatch.setattr(bootstrap, "_install_ffmpeg", lambda log: False)
    log = Log()
    assert bootstrap.ensure_ffmpeg(log) is False


def test_setup_installs_only_when_nothing_here_works(monkeypatch, tmp_path):
    directory = install(tmp_path / "working")
    monkeypatch.setenv("PATH", str(directory))
    monkeypatch.setattr(ffmpeg_health, "prove_pair",
                        lambda pair, runner=None: ffmpeg_health.Proof(ok=True))
    installs: list = []
    monkeypatch.setattr(bootstrap, "_install_ffmpeg",
                        lambda log: installs.append(1) or True)
    assert bootstrap.ensure_ffmpeg(Log()) is True
    assert installs == [], "a working machine was needlessly reinstalled"


def test_a_winget_install_is_accepted_without_waiting_for_path(monkeypatch, tmp_path):
    """winget updates the user's PATH, not this process's.

    Gating success on ``_ffmpeg_on_path()`` made setup abandon installs that had
    just succeeded and download a second, worse copy instead.
    """
    source = (REPO_ROOT / "scripts" / "Universal" / "shared"
              / "bootstrap.py").read_text(encoding="utf-8")
    branch = source[source.index("def _install_ffmpeg("):]
    winget = branch[branch.index("winget install"):branch.index("if IS_MAC")]
    assert "and _ffmpeg_on_path()" not in winget


def test_the_launch_fast_path_checks_ffmpeg_before_the_gui():
    """**Structural.** The gap that let a broken pair reach a real conversion."""
    source = (REPO_ROOT / "scripts" / "Universal" / "shared"
              / "bootstrap.py").read_text(encoding="utf-8")
    body = source[source.index("def _launch_with_kokoro_healthcheck("):]
    body = body[:body.index("def ")] if "def " in body[10:] else body
    assert "ensure_ffmpeg_ready_for_launch()" in source
    launch = source.index("def _launch_with_kokoro_healthcheck(")
    check = source.index("ensure_ffmpeg_ready_for_launch()", launch)
    gui = source.index("launch_gui(LOG)", launch)
    assert check < gui, "the health check must run before the GUI is launched"


def test_the_launch_check_still_leaves_kokoro_and_requirements_alone():
    source = (REPO_ROOT / "scripts" / "Universal" / "shared"
              / "bootstrap.py").read_text(encoding="utf-8")
    body = source[source.index("def _launch_with_kokoro_healthcheck("):]
    assert "requirements_are_current()" in body
    assert "kokoro_is_healthy(venv_py)" in body


def test_a_launch_with_no_usable_ffmpeg_warns_but_still_opens(monkeypatch, tmp_path):
    """Edge TTS does not need ffmpeg, so this is a warning, not a refusal."""
    warned: list = []
    monkeypatch.setattr(bootstrap, "show_warning_dialog",
                        lambda title, message: warned.append((title, message)))
    monkeypatch.setattr(ffmpeg_health, "ensure_ready", lambda log=None, **kw: None)
    assert bootstrap.ensure_ffmpeg_ready_for_launch() is False
    assert warned and "audio tools" in warned[0][0]


def test_bootstrap_and_the_runtime_share_one_implementation():
    """Two module objects would each carry their own state and caches.

    Setup and the app could then hold different answers to "which FFmpeg?"
    while both looked correct, so this pins that they are literally the same
    module rather than merely equivalent files.
    """
    source = (REPO_ROOT / "scripts" / "Universal" / "shared"
              / "bootstrap.py").read_text(encoding="utf-8")
    assert "from shared import ffmpeg_health" in source
    assert bootstrap.ffmpeg_health is ffmpeg_health


def test_the_health_module_stays_importable_before_the_venv_exists():
    """It runs in bootstrap's pre-venv environment, so stdlib only.

    Anything imported here that needs a pip package would make setup fail on the
    one machine that has not run setup yet.
    """
    import ast
    source = (REPO_ROOT / "scripts" / "Universal" / "shared"
              / "ffmpeg_health.py").read_text(encoding="utf-8")
    roots: set = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= {
        "__future__", "hashlib", "json", "os", "shutil", "subprocess", "sys",
        "time", "dataclasses", "pathlib", "typing", "subprocess_utils",
    }, sorted(roots)
