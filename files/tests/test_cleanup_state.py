"""v0.6.0 Drop 2 Phase 7 — maintenance state, persistence, and the handoff.

Every filesystem assertion here runs against a disposable fake repository root
built in ``tmp_path``. Nothing in this file reads, walks, modifies, deletes,
renames or rebuilds the maintainer's real ``.venv``, ``files/bin``,
``files/runtime-data/models``, ``files/runtime-data/logs``, ``settings.json``,
Downloads folder, output base, source media, source, docs, tests, ``config.toml``
or ``config-template.toml``. No coordinator is ever started against the real
repository: every spawn is a stub or a disposable copy.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared import cleanup_state as state
from shared import maintenance as mnt

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODULE = Path(state.__file__)
UTC = timezone.utc


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def fake_root(tmp_path: Path) -> Path:
    """A disposable stand-in for the repository root."""
    root = tmp_path / "fake-repo"
    (root / "scripts" / "Universal" / "shared").mkdir(parents=True, exist_ok=True)
    (root / "files" / "runtime-data").mkdir(parents=True, exist_ok=True)
    write(root / "config.toml", b"# fake\n")
    write(root / "files" / "runtime-data" / "settings.json", b"{}")
    write(root / ".venv" / "pyvenv.cfg", b"x" * 100)
    write(root / "files" / "bin" / "ffmpeg.exe", b"z" * 1000)
    write(root / "files" / "runtime-data" / "models" / "model.bin", b"m" * 2048)
    write(root / "files" / "runtime-data" / "logs" / "session.log", b"l" * 50)
    return root


def snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return out


def build(ids=("application_logs",), *, pid=None, when=None, request_id=None):
    return mnt.build_request(
        ids,
        process_id=pid if pid is not None else os.getpid(),
        clock=(lambda: when) if when is not None else None,
        request_id=request_id,
    )


class FakeProcess:
    """A stand-in for ``Popen`` that never starts anything."""

    def __init__(self, code=None):
        self.code = code
        self.command = None

    def poll(self):
        return self.code


class Spawner:
    """Records the command it was given and returns a fake process."""

    def __init__(self, process=None, error=None):
        self.process = process if process is not None else FakeProcess()
        self.error = error
        self.commands: list[list[str]] = []

    def __call__(self, command):
        self.commands.append(list(command))
        if self.error is not None:
            raise self.error
        self.process.command = list(command)
        return self.process


def accepting_spawner(root, request, *, code=None):
    """A spawner that writes the acknowledgement the coordinator would write."""

    def spawn(command):
        state.write_acceptance(root, request, process_id=4321)
        return FakeProcess(code)

    return spawn


# --------------------------------------------------------------------------- #
# The state folder
# --------------------------------------------------------------------------- #


def test_the_state_folder_is_the_one_documented_location(tmp_path):
    root = fake_root(tmp_path)
    assert state.state_dir(root) == root / "files" / "runtime-data" / "maintenance"


def test_the_state_folder_is_outside_every_removable_target(tmp_path):
    root = fake_root(tmp_path)
    directory = state.state_dir(root)
    for asset_id in mnt.ASSET_IDS:
        target = mnt.compiled_target(asset_id, root)
        assert not mnt.same_path(directory, target)
        assert not mnt.is_within(target, directory)


def test_the_state_folder_is_inside_the_project_and_is_not_its_root(tmp_path):
    root = fake_root(tmp_path)
    directory = state.state_dir(root)
    assert mnt.is_within(root, directory)
    assert not mnt.same_path(directory, root)


def test_the_state_folder_follows_the_root_it_is_given(tmp_path):
    first = fake_root(tmp_path)
    second = fake_root(tmp_path / "other")
    assert state.state_dir(first) != state.state_dir(second)
    assert str(state.state_dir(second)).startswith(str(second))


def test_a_linked_state_folder_is_refused_rather_than_followed(tmp_path):
    root = fake_root(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = root / "files" / "runtime-data" / "maintenance"
    if os.name == "nt":
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(elsewhere)],
                              capture_output=True).returncode == 0
    else:
        link.symlink_to(elsewhere, target_is_directory=True)
        made = True
    if not made:
        pytest.skip("this account cannot create a junction")
    with pytest.raises(state.StateError):
        state.state_dir(root)


def test_a_linked_project_root_is_refused(tmp_path):
    root = fake_root(tmp_path)
    link = tmp_path / "linked-repo"
    if os.name == "nt":
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(root)],
                              capture_output=True).returncode == 0
    else:
        link.symlink_to(root, target_is_directory=True)
        made = True
    if not made:
        pytest.skip("this account cannot create a junction")
    with pytest.raises(state.StateError):
        state.state_dir(link)


def test_only_named_state_files_can_be_addressed(tmp_path):
    root = fake_root(tmp_path)
    for name in state.STATE_FILENAMES:
        assert state.state_file(root, name).name == name
    for bad in ("settings.json", "../config.toml", "anything.json", ""):
        with pytest.raises(state.StateError):
            state.state_file(root, bad)


def test_the_state_folder_is_created_only_when_asked(tmp_path):
    root = fake_root(tmp_path)
    assert not state.state_dir(root).exists()
    assert state.ensure_state_dir(root).is_dir()


# --------------------------------------------------------------------------- #
# Atomic writes
# --------------------------------------------------------------------------- #


def test_a_request_is_written_atomically_and_reads_back(tmp_path):
    root = fake_root(tmp_path)
    request = build(("application_logs", "downloaded_models"))
    path = state.store_request(request, root)
    assert path == state.request_path(root)
    assert state.load_request(root) == request


def test_no_temporary_file_survives_a_successful_write(tmp_path):
    root = fake_root(tmp_path)
    state.store_request(build(), root)
    leftovers = [p.name for p in state.state_dir(root).iterdir()
                 if p.name.startswith(state.TEMP_PREFIX)]
    assert leftovers == []


def test_an_interrupted_write_leaves_the_previous_file_intact(tmp_path, monkeypatch):
    root = fake_root(tmp_path)
    first = build(("application_logs",))
    state.store_request(first, root)

    def explode(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(state.os, "replace", explode)
    with pytest.raises(OSError):
        state.write_json(state.request_path(root), {"schema_version": 1})
    assert state.load_request(root) == first
    leftovers = [p.name for p in state.state_dir(root).iterdir()
                 if p.name.startswith(state.TEMP_PREFIX)]
    assert leftovers == []


def test_a_half_written_request_is_not_loadable(tmp_path):
    root = fake_root(tmp_path)
    state.ensure_state_dir(root)
    state.request_path(root).write_text('{"schema_version": 1, "asset_ids"',
                                        encoding="utf-8")
    assert state.load_request(root) is None


def test_only_this_modules_own_temporary_files_are_swept(tmp_path):
    root = fake_root(tmp_path)
    directory = state.ensure_state_dir(root)
    mine = directory / f"{state.TEMP_PREFIX}abc.json"
    theirs = directory / "someone-elses.json"
    for path in (mine, theirs):
        path.write_text("{}", encoding="utf-8")
        os.utime(path, (0, 0))
    assert state.sweep_temporary_files(root) == 1
    assert not mine.exists()
    assert theirs.exists()


def test_a_fresh_temporary_file_is_left_alone(tmp_path):
    root = fake_root(tmp_path)
    directory = state.ensure_state_dir(root)
    fresh = directory / f"{state.TEMP_PREFIX}live.json"
    fresh.write_text("{}", encoding="utf-8")
    assert state.sweep_temporary_files(root) == 0
    assert fresh.exists()


def test_this_module_refuses_to_remove_anything_it_does_not_own(tmp_path):
    root = fake_root(tmp_path)
    state.ensure_state_dir(root)
    intruder = state.state_dir(root) / "not-ours.json"
    intruder.write_text("{}", encoding="utf-8")
    with pytest.raises(state.StateError):
        state._discard_own_file(intruder)
    assert intruder.exists()


# --------------------------------------------------------------------------- #
# One active request at a time
# --------------------------------------------------------------------------- #


def test_an_active_request_is_never_silently_overwritten(tmp_path):
    root = fake_root(tmp_path)
    first = build(("application_logs",))
    state.store_request(first, root)
    with pytest.raises(state.ActiveRequestError):
        state.store_request(build(("downloaded_models",)), root)
    assert state.load_request(root) == first


def test_a_stale_request_is_moved_aside_rather_than_lost(tmp_path):
    root = fake_root(tmp_path)
    old = build(("application_logs",),
                when=datetime.now(UTC) - state.MAX_REQUEST_AGE - timedelta(minutes=1))
    state.store_request(old, root)
    fresh = build(("downloaded_models",))
    state.store_request(fresh, root)
    assert state.load_request(root) == fresh
    assert state.state_file(root, state.UNUSABLE_REQUEST_NAME).exists()


def test_a_request_from_a_dead_process_is_not_active(tmp_path):
    root = fake_root(tmp_path)
    dead = build(("application_logs",), pid=_dead_pid())
    state.store_request(dead, root)
    kind, _ = state.describe_existing_request(root)
    assert kind == "stale"


def test_a_request_from_a_live_process_is_active(tmp_path):
    root = fake_root(tmp_path)
    state.store_request(build(("application_logs",), pid=os.getpid()), root)
    kind, request = state.describe_existing_request(root)
    assert kind == "active"
    assert request.process_id == os.getpid()


def test_an_unusable_request_file_is_classified_and_replaced(tmp_path):
    root = fake_root(tmp_path)
    state.ensure_state_dir(root)
    state.request_path(root).write_text("not json at all", encoding="utf-8")
    assert state.describe_existing_request(root)[0] == "unusable"
    state.store_request(build(), root)
    assert state.load_request(root) is not None


def test_a_future_dated_request_is_stale(tmp_path):
    request = build(when=datetime.now(UTC) + state.MAX_CLOCK_SKEW + timedelta(minutes=5))
    assert state.request_is_stale(request)


def test_a_recent_request_is_not_stale():
    assert not state.request_is_stale(build())


def _dead_pid() -> int:
    """A process id that is almost certainly not running."""
    for candidate in range(999_990, 999_899, -1):
        if not state.process_is_running(candidate):
            return candidate
    return 999_999


# --------------------------------------------------------------------------- #
# Consumption
# --------------------------------------------------------------------------- #


def test_a_request_is_consumed_exactly_once(tmp_path):
    root = fake_root(tmp_path)
    request = build(("application_logs",))
    state.store_request(request, root)
    assert state.consume_request(root, request) is True
    assert state.consume_request(root, request) is False
    assert not state.request_path(root).exists()
    assert state.state_file(root, state.CONSUMED_NAME).exists()


def test_a_consumed_request_cannot_be_replayed(tmp_path):
    root = fake_root(tmp_path)
    request = build(("application_logs",))
    state.store_request(request, root)
    state.consume_request(root, request)
    assert state.load_request(root) is None


def test_consuming_someone_elses_request_is_refused(tmp_path):
    root = fake_root(tmp_path)
    state.store_request(build(("application_logs",)), root)
    other = build(("application_logs",))
    assert state.consume_request(root, other) is False
    assert state.request_path(root).exists()


def test_withdrawing_only_removes_the_named_request(tmp_path):
    root = fake_root(tmp_path)
    request = build(("application_logs",))
    state.store_request(request, root)
    assert state.discard_request(root, "3f2504e0-4f89-11d3-9a0c-0305e82c3301") is False
    assert state.request_path(root).exists()
    assert state.discard_request(root, request.request_id) is True
    assert not state.request_path(root).exists()


# --------------------------------------------------------------------------- #
# The acknowledgement
# --------------------------------------------------------------------------- #


def test_an_acknowledgement_round_trips(tmp_path):
    root = fake_root(tmp_path)
    request = build()
    state.write_acceptance(root, request, process_id=4321)
    data = state.read_acceptance(root, request)
    assert data["request_id"] == request.request_id
    assert data["coordinator_process_id"] == 4321


def test_an_acknowledgement_for_another_request_is_not_one(tmp_path):
    root = fake_root(tmp_path)
    state.write_acceptance(root, build(), process_id=4321)
    assert state.read_acceptance(root, build()) is None


@pytest.mark.parametrize("mutate", [
    lambda d: d.__setitem__("schema_version", 99),
    lambda d: d.__setitem__("coordinator_process_id", 0),
    lambda d: d.__setitem__("coordinator_process_id", "1"),
    lambda d: d.__setitem__("extra", 1),
    lambda d: d.pop("accepted_at"),
])
def test_a_malformed_acknowledgement_is_not_one(tmp_path, mutate):
    root = fake_root(tmp_path)
    request = build()
    state.write_acceptance(root, request, process_id=4321)
    data = json.loads(state.accepted_path(root).read_text(encoding="utf-8"))
    mutate(data)
    state.accepted_path(root).write_text(json.dumps(data), encoding="utf-8")
    assert state.read_acceptance(root, request) is None


def test_a_previous_acknowledgement_is_cleared_before_a_new_handoff(tmp_path):
    root = fake_root(tmp_path)
    old = build()
    state.write_acceptance(root, old, process_id=4321)
    state.clear_acceptance(root)
    assert state.read_acceptance(root, old) is None


def test_waiting_stops_when_the_helper_dies_without_acknowledging(tmp_path):
    root = fake_root(tmp_path)
    state.ensure_state_dir(root)
    assert state.wait_for_acceptance(root, build(), FakeProcess(code=1),
                                     timeout=5, sleep=lambda _s: None) is False


def test_waiting_is_bounded_when_nothing_ever_answers(tmp_path):
    root = fake_root(tmp_path)
    state.ensure_state_dir(root)
    ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert state.wait_for_acceptance(
        root, build(), None, timeout=1.0, sleep=lambda _s: None,
        monotonic=lambda: next(ticks),
    ) is False


def test_waiting_succeeds_as_soon_as_the_acknowledgement_lands(tmp_path):
    root = fake_root(tmp_path)
    request = build()
    state.write_acceptance(root, request, process_id=4321)
    assert state.wait_for_acceptance(root, request, FakeProcess(),
                                     timeout=1, sleep=lambda _s: None) is True


# --------------------------------------------------------------------------- #
# Choosing an interpreter and building the command
# --------------------------------------------------------------------------- #


def test_an_interpreter_inside_the_project_is_never_chosen(tmp_path):
    root = fake_root(tmp_path)
    inside = root / ".venv" / "Scripts" / "python.exe"
    write(inside, b"")
    outside = tmp_path / "system" / "python.exe"
    write(outside, b"")
    chosen = state.find_non_venv_python(root, candidates=[inside, outside],
                                        probe=lambda _p: True)
    assert chosen == mnt.absolute(outside)


def test_an_interpreter_that_reports_itself_as_a_venv_is_rejected(tmp_path):
    root = fake_root(tmp_path)
    outside = tmp_path / "system" / "python.exe"
    write(outside, b"")
    assert state.find_non_venv_python(root, candidates=[outside],
                                      probe=lambda _p: False) is None


def test_a_missing_candidate_is_skipped(tmp_path):
    root = fake_root(tmp_path)
    missing = tmp_path / "nope" / "python.exe"
    real = tmp_path / "system" / "python.exe"
    write(real, b"")
    assert state.find_non_venv_python(root, candidates=[missing, real],
                                      probe=lambda _p: True) == mnt.absolute(real)


def test_the_real_base_interpreter_is_found_and_is_outside_the_project(tmp_path):
    """The live probe, run against a disposable root — never a real deletion."""
    root = fake_root(tmp_path)
    found = state.find_non_venv_python(root)
    assert found is not None
    assert not mnt.is_within(REPO_ROOT, found)


def test_the_command_is_an_argument_vector_not_a_shell_string(tmp_path):
    request = build()
    command = state.build_coordinator_command(Path("C:/Py/python.exe"), request)
    assert isinstance(command, list)
    assert all(isinstance(part, str) for part in command)
    assert command[1].endswith("cleanup_worker.py")
    assert command[-1] == request.request_id
    assert not any(part.startswith("&") or ";" in part or "|" in part
                   for part in command)


def test_the_command_carries_no_path_from_the_request():
    request = build(("application_logs", "downloaded_models"))
    command = state.build_coordinator_command("python", request)
    serialized = json.dumps(mnt.request_to_dict(request))
    for part in command[2:]:
        assert part not in ("/", "\\")
        assert part in serialized or part in ("--run", "--request-id")


def test_spaces_unicode_and_apostrophes_survive_the_command(tmp_path, monkeypatch):
    awkward = tmp_path / "Réal's Audio Projects" / "Audiobook Tool"
    script = awkward / "scripts" / "Universal" / "shared" / "cleanup_worker.py"
    write(script, b"# stand-in\n")
    monkeypatch.setattr(state, "coordinator_script", lambda: script)
    command = state.build_coordinator_command(awkward / "py thon.exe", build())
    assert command[0] == str(awkward / "py thon.exe")
    assert command[1] == str(script)
    assert "Réal's Audio Projects" in command[1]


# --------------------------------------------------------------------------- #
# The handoff
# --------------------------------------------------------------------------- #


def test_a_successful_handoff_leaves_a_request_and_an_acknowledgement(tmp_path):
    root = fake_root(tmp_path)
    request = build(("application_logs",))
    outcome = state.start_cleanup(request, root, python=Path(sys.executable),
                                  spawn=accepting_spawner(root, request),
                                  sleep=lambda _s: None)
    assert bool(outcome) is True
    assert state.load_request(root) == request
    assert state.read_acceptance(root, request) is not None


def test_a_successful_handoff_deletes_nothing(tmp_path):
    root = fake_root(tmp_path)
    before = snapshot(root)
    request = build(tuple(mnt.ASSET_IDS))
    state.start_cleanup(request, root, python=Path(sys.executable),
                        spawn=accepting_spawner(root, request), sleep=lambda _s: None)
    after = snapshot(root)
    for name, digest in before.items():
        assert after[name] == digest


def test_a_spawn_failure_withdraws_the_request_and_changes_nothing(tmp_path):
    root = fake_root(tmp_path)
    before = snapshot(root)
    outcome = state.start_cleanup(build(("application_logs",)), root,
                                  python=Path(sys.executable),
                                  spawn=Spawner(error=OSError("no such file")),
                                  sleep=lambda _s: None)
    assert bool(outcome) is False
    assert outcome.detail
    assert not state.request_path(root).exists()
    assert snapshot(root) == before


def test_a_missing_interpreter_fails_closed(tmp_path, monkeypatch):
    root = fake_root(tmp_path)
    before = snapshot(root)
    spawner = Spawner()
    monkeypatch.setattr(state, "find_non_venv_python", lambda *_a, **_k: None)
    outcome = state.start_cleanup(build(("application_logs",)), root,
                                  python=None, spawn=spawner,
                                  sleep=lambda _s: None)
    assert bool(outcome) is False
    assert "No suitable Python" in outcome.detail
    assert spawner.commands == []
    assert not state.request_path(root).exists()
    assert snapshot(root) == before


def test_no_acknowledgement_within_the_timeout_withdraws_the_request(tmp_path):
    root = fake_root(tmp_path)
    before = snapshot(root)
    outcome = state.start_cleanup(build(("application_logs",)), root,
                                  python=Path(sys.executable), spawn=Spawner(),
                                  timeout=0.0, sleep=lambda _s: None)
    assert bool(outcome) is False
    assert "did not confirm" in outcome.detail
    assert not state.request_path(root).exists()
    assert snapshot(root) == before


def test_a_late_acknowledgement_during_withdrawal_is_honoured(tmp_path):
    root = fake_root(tmp_path)
    request = build(("application_logs",))

    class LateSpawner:
        def __call__(self, command):
            return FakeProcess()

    def late_wait(*_a, **_k):
        state.write_acceptance(root, request, process_id=4321)
        return False

    original = state.wait_for_acceptance
    try:
        state.wait_for_acceptance = late_wait          # type: ignore[assignment]
        outcome = state.start_cleanup(request, root, python=Path(sys.executable),
                                      spawn=LateSpawner(), sleep=lambda _s: None)
    finally:
        state.wait_for_acceptance = original           # type: ignore[assignment]
    assert bool(outcome) is True


def test_a_second_handoff_while_one_is_live_is_refused(tmp_path):
    root = fake_root(tmp_path)
    first = build(("application_logs",), pid=os.getpid())
    state.start_cleanup(first, root, python=Path(sys.executable),
                        spawn=accepting_spawner(root, first), sleep=lambda _s: None)
    second = build(("downloaded_models",), pid=os.getpid())
    outcome = state.start_cleanup(second, root, python=Path(sys.executable),
                                  spawn=accepting_spawner(root, second),
                                  sleep=lambda _s: None)
    assert bool(outcome) is False
    assert "already scheduled" in outcome.detail
    assert state.load_request(root) == first


def test_the_handoff_refuses_anything_that_is_not_a_request(tmp_path):
    root = fake_root(tmp_path)
    outcome = state.start_cleanup({"asset_ids": ["application_logs"]}, root,
                                  python=Path(sys.executable), spawn=Spawner(),
                                  sleep=lambda _s: None)
    assert bool(outcome) is False
    assert not state.request_path(root).exists()


def test_the_handoff_uses_the_root_it_is_given(tmp_path):
    root = fake_root(tmp_path)
    request = build(("application_logs",))
    state.start_cleanup(request, root, python=Path(sys.executable),
                        spawn=accepting_spawner(root, request), sleep=lambda _s: None)
    assert (root / "files" / "runtime-data" / "maintenance"
            / state.REQUEST_NAME).exists()


# --------------------------------------------------------------------------- #
# The result
# --------------------------------------------------------------------------- #


def make_result(statuses, *, request_id=None):
    request = build(tuple(statuses), request_id=request_id)
    now = datetime.now(UTC)
    return mnt.CleanupResult(
        schema_version=mnt.SCHEMA_VERSION,
        request_id=request.request_id,
        started_at=now,
        completed_at=now,
        outcomes=tuple(mnt.AssetOutcome(asset_id, status, 10, "")
                       for asset_id, status in statuses.items()),
    )


def test_a_result_round_trips_through_the_state_folder(tmp_path):
    root = fake_root(tmp_path)
    result = make_result({"application_logs": "removed"})
    state.store_result(result, root)
    assert state.load_result(root) == result


def test_a_result_is_written_atomically(tmp_path):
    root = fake_root(tmp_path)
    state.store_result(make_result({"application_logs": "removed"}), root)
    leftovers = [p.name for p in state.state_dir(root).iterdir()
                 if p.name.startswith(state.TEMP_PREFIX)]
    assert leftovers == []


def test_a_result_is_presented_once(tmp_path):
    root = fake_root(tmp_path)
    result = make_result({"application_logs": "removed"})
    state.store_result(result, root)
    assert state.mark_result_presented(root, result) is True
    assert state.load_result(root) is None
    assert state.state_file(root, state.PRESENTED_NAME).exists()


def test_marking_a_result_that_is_not_there_reports_failure(tmp_path):
    root = fake_root(tmp_path)
    state.ensure_state_dir(root)
    assert state.mark_result_presented(root, make_result({"application_logs": "removed"})) is False


def test_a_corrupt_result_is_moved_aside_and_never_executed(tmp_path):
    root = fake_root(tmp_path)
    before = snapshot(root)
    state.ensure_state_dir(root)
    state.result_path(root).write_text('{"schema_version": 1, "outcomes": "rm -rf /"}',
                                       encoding="utf-8")
    assert state.load_result(root) is None
    assert state.state_file(root, state.UNREADABLE_RESULT_NAME).exists()
    after = snapshot(root)
    for name, digest in before.items():
        assert after[name] == digest


def test_a_result_for_an_unsupported_schema_is_not_loaded(tmp_path):
    root = fake_root(tmp_path)
    result = make_result({"application_logs": "removed"})
    payload = mnt.result_to_dict(result)
    payload["schema_version"] = 99
    state.ensure_state_dir(root)
    state.result_path(root).write_text(json.dumps(payload), encoding="utf-8")
    assert state.load_result(root) is None


def test_a_stored_result_names_no_path(tmp_path):
    root = fake_root(tmp_path)
    state.store_result(make_result({"application_logs": "removed",
                                    "virtual_environment": "missing"}), root)
    text = state.result_path(root).read_text(encoding="utf-8")
    assert "/" not in text and "\\" not in text


# --------------------------------------------------------------------------- #
# Launcher and bootstrap routes
# --------------------------------------------------------------------------- #


def test_the_windows_launcher_still_rebuilds_a_missing_environment():
    text = (REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.bat").read_text(
        encoding="utf-8", errors="replace"
    )
    assert 'if exist ".venv\\Scripts\\pythonw.exe"' in text
    assert "--launch-only" in text
    assert '"%PYCMD%" "%BOOTSTRAP%"' in text


def test_the_macos_launcher_still_rebuilds_a_missing_environment():
    text = (REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.command").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "--launch-only" in text
    assert ".venv" in text


def test_both_root_launchers_quote_every_path_they_pass():
    for name in ("Setup_and_Run-audiobook-creation-tool.bat",
                 "Setup_and_Run-audiobook-creation-tool.command"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8", errors="replace")
        if name.endswith(".bat"):
            assert 'cd /d "%~dp0"' in text
            assert '"%BOOTSTRAP%"' in text
        else:
            assert '"$DIR"' in text or 'cd "' in text


def test_neither_root_launcher_gained_a_cleanup_route():
    for name in ("Setup_and_Run-audiobook-creation-tool.bat",
                 "Setup_and_Run-audiobook-creation-tool.command"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8", errors="replace").lower()
        for word in ("cleanup", "maintenance", "request-id"):
            assert word not in text, f"{name}: {word}"


def test_bootstrap_is_unchanged_by_this_phase():
    source = (REPO_ROOT / "scripts" / "Universal" / "shared" / "bootstrap.py").read_text(
        encoding="utf-8"
    )
    for word in ("cleanup_state", "cleanup_worker", "CleanupRequest", "maintenance",
                 "request-id"):
        assert word not in source, word
    # The ordinary fast path and the ordinary repair path are still there.
    assert "--launch-only" in source
    assert "_launch_with_kokoro_healthcheck" in source
    assert "venv_is_valid" in source


def test_a_normal_launch_without_any_state_reads_nothing(tmp_path):
    """No request, no result: the state folder is not even created."""
    root = fake_root(tmp_path)
    assert state.load_result(root) is None
    assert state.load_request(root) is None
    assert not state.state_dir(root).exists()


# --------------------------------------------------------------------------- #
# Structural guards
# --------------------------------------------------------------------------- #


def module_tree():
    return ast.parse(MODULE.read_text(encoding="utf-8"))


def test_the_state_module_never_recursively_deletes(tmp_path):
    tree = module_tree()
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    called |= {n.func.id for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    for destructive in ("rmtree", "rmdir", "removedirs"):
        assert destructive not in called, destructive


def test_the_state_module_is_standard_library_only():
    tree = module_tree()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    allowed = {"__future__", "json", "os", "shutil", "subprocess", "sys",
               "tempfile", "time", "dataclasses", "datetime", "pathlib",
               "ctypes", ""}
    assert imported <= allowed, imported - allowed


def test_process_creation_never_uses_a_shell():
    source = MODULE.read_text(encoding="utf-8")
    assert "shell=False" in source
    assert "shell=True" not in source
    assert "os.system" not in source
    tree = module_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("Popen", "run", "call", "check_output"):
                for keyword in node.keywords:
                    if keyword.arg == "shell":
                        assert isinstance(keyword.value, ast.Constant)
                        assert keyword.value.value is False


def test_no_request_field_can_name_a_file_the_state_layer_writes():
    source = MODULE.read_text(encoding="utf-8")
    for field in mnt.REQUEST_FIELDS:
        assert f'data["{field}"]' not in source
    # Every filename is a module constant, never composed from input.
    for name in (state.REQUEST_NAME, state.RESULT_NAME, state.ACCEPTED_NAME):
        assert f'"{name}"' in source


def test_the_state_module_never_defaults_to_the_real_repository_in_tests():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in ("start_cleanup", "store_request", "store_result",
                        "ensure_state_dir", "consume_request"):
            continue
        for argument in list(call.args) + [k.value for k in call.keywords]:
            assert not any(isinstance(n, ast.Name) and n.id == "REPO_ROOT"
                           for n in ast.walk(argument))


def test_the_unrelated_template_is_never_read_or_removed():
    source = MODULE.read_text(encoding="utf-8")
    assert "config-template" not in source
    assert "config.toml" not in source
