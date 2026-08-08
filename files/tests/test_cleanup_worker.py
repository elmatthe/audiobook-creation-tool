"""v0.6.0 Drop 2 Phase 7 — the post-exit cleanup coordinator.

**Every deletion in this file happens inside a disposable fake repository root
built in ``tmp_path``.** Nothing here points at, enumerates, walks, modifies,
renames, chmods, locks, deletes or rebuilds the maintainer's real ``.venv``,
``files/bin``, ``files/runtime-data/models``, ``files/runtime-data/logs``,
``settings.json``, Downloads folder, output base, source media, source, docs,
tests, ``config.toml`` or ``config-template.toml``. A structural test at the end
proves no call in this module is handed the real repository root, and the
subprocess drills run a *copy* of the coordinator inside the temporary tree, so
even a coordinator that ignored its arguments could only reach the copy's root.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared import cleanup_state as state
from shared import cleanup_worker as worker
from shared import maintenance as mnt

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODULE = Path(worker.__file__)
UTC = timezone.utc

#: The four modules a coordinator needs, and nothing else.
COORDINATOR_MODULES = ("__init__.py", "maintenance.py", "cleanup_state.py",
                       "cleanup_worker.py")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


VENV_BYTES = 500
BIN_BYTES = 1000
MODEL_BYTES = 2048
LOG_BYTES = 50


def fake_root(tmp_path: Path, *, name="fake-repo", venv=True, binaries=True,
              models=True, logs=True) -> Path:
    """A disposable stand-in for the repository root, with known byte totals."""
    root = tmp_path / name
    (root / "scripts" / "Universal" / "shared").mkdir(parents=True, exist_ok=True)
    (root / "md-instructions").mkdir(parents=True, exist_ok=True)
    (root / "files" / "tests").mkdir(parents=True, exist_ok=True)
    (root / "files" / "runtime-data").mkdir(parents=True, exist_ok=True)
    write(root / "config.toml", b"# fake\n")
    write(root / "README.md", b"# fake\n")
    write(root / "files" / "runtime-data" / "settings.json", b"{}")
    write(root / "md-instructions" / "Briefing.md", b"# fake\n")

    if venv:
        write(root / ".venv" / "pyvenv.cfg", b"x" * 100)
        write(root / ".venv" / "Lib" / "site-packages" / "thing.py", b"y" * 400)
    if binaries:
        write(root / "files" / "bin" / "ffmpeg.exe", b"z" * BIN_BYTES)
    if models:
        write(root / "files" / "runtime-data" / "models" / "kokoro" / "model.bin",
              b"m" * MODEL_BYTES)
    if logs:
        write(root / "files" / "runtime-data" / "logs" / "session.log", b"l" * LOG_BYTES)
    return root


def snapshot(root: Path) -> dict[str, str]:
    """Path -> sha256 for everything except the maintenance state folder.

    The state folder is deliberately excluded: a run is *supposed* to write a
    request, an acknowledgement and a result there, and including it would turn
    every "nothing changed" assertion into a comparison of the bookkeeping
    rather than of the data.
    """
    out: dict[str, str] = {}
    skip = "/".join(state.STATE_DIR_PARTS) + "/"
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(skip):
            continue
        out[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def make_junction(link: Path, target: Path) -> bool:
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        return subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                              capture_output=True).returncode == 0
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        return False


def build(ids, *, pid=4321, when=None, request_id=None):
    return mnt.build_request(
        ids, process_id=pid,
        clock=(lambda: when) if when is not None else None,
        request_id=request_id,
    )


def scheduled(root: Path, ids, *, pid=4321, when=None):
    """Store a request the way a successful handoff would have."""
    request = build(ids, pid=pid, when=when)
    state.store_request(request, root)
    return request


def exits_immediately(*_a, **_k) -> bool:
    return True


def never_exits(*_a, **_k) -> bool:
    return False


def outcomes_by_id(result):
    return {o.asset_id: o for o in result.outcomes}


# --------------------------------------------------------------------------- #
# Trusted root
# --------------------------------------------------------------------------- #


def test_the_coordinator_finds_its_own_project_folder():
    assert worker.repository_root() == REPO_ROOT


def test_the_coordinator_agrees_with_the_state_layer_about_the_root():
    assert mnt.same_path(worker.repository_root(), state.default_repo_root())


def test_the_root_comes_from_the_file_not_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert worker.repository_root() == REPO_ROOT


# --------------------------------------------------------------------------- #
# Request validation — nothing is deleted before it passes
# --------------------------------------------------------------------------- #


def test_a_missing_request_is_refused(tmp_path):
    root = fake_root(tmp_path)
    state.ensure_state_dir(root)
    with pytest.raises(worker.CoordinatorRefusal):
        worker.load_and_validate(root, "")


def test_a_request_for_a_different_identifier_is_refused(tmp_path):
    root = fake_root(tmp_path)
    scheduled(root, ("application_logs",))
    with pytest.raises(worker.CoordinatorRefusal):
        worker.load_and_validate(root, "3f2504e0-4f89-11d3-9a0c-0305e82c3301")


def test_a_stale_request_is_refused(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, ("application_logs",),
                        when=datetime.now(UTC) - state.MAX_REQUEST_AGE
                        - timedelta(minutes=5))
    with pytest.raises(worker.CoordinatorRefusal):
        worker.load_and_validate(root, request.request_id)


def test_a_request_naming_the_coordinator_itself_is_refused(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, ("application_logs",), pid=os.getpid())
    with pytest.raises(worker.CoordinatorRefusal):
        worker.load_and_validate(root, request.request_id)


@pytest.mark.parametrize("payload", [
    {"schema_version": 1, "asset_ids": ["../../../etc"], "process_id": 4321,
     "created_at": "2999-01-01T00:00:00+00:00", "request_id": "x"},
    {"schema_version": 1, "asset_ids": ["C:\\Windows"], "process_id": 4321,
     "created_at": "2026-08-04T09:30:00+00:00",
     "request_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301"},
    {"schema_version": 2, "asset_ids": ["application_logs"], "process_id": 4321,
     "created_at": "2026-08-04T09:30:00+00:00",
     "request_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301"},
    {"schema_version": 1, "asset_ids": ["application_logs"], "process_id": 4321,
     "created_at": "2026-08-04T09:30:00+00:00",
     "request_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
     "repo_root": "C:\\"},
    {"schema_version": 1, "asset_ids": ["application_logs"], "process_id": 4321,
     "created_at": "2026-08-04T09:30:00+00:00",
     "request_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
     "target": "C:\\Users"},
])
def test_a_tampered_request_never_reaches_deletion(tmp_path, payload):
    root = fake_root(tmp_path)
    before = snapshot(root)
    state.ensure_state_dir(root)
    state.request_path(root).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(worker.CoordinatorRefusal):
        worker.run(root, "", wait=exits_immediately)
    assert snapshot(root) == before


def test_a_request_cannot_redirect_the_repository_root(tmp_path):
    """An extra ``repo_root`` key is refused outright, and the root is ignored."""
    root = fake_root(tmp_path)
    elsewhere = fake_root(tmp_path, name="not-this-one")
    before = snapshot(elsewhere)
    state.ensure_state_dir(root)
    payload = mnt.request_to_dict(build(("application_logs",)))
    payload["repo_root"] = str(elsewhere)
    state.request_path(root).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(worker.CoordinatorRefusal):
        worker.run(root, "", wait=exits_immediately)
    assert snapshot(elsewhere) == before


def test_corrupt_request_json_is_refused(tmp_path):
    root = fake_root(tmp_path)
    before = snapshot(root)
    state.ensure_state_dir(root)
    state.request_path(root).write_text("{{{not json", encoding="utf-8")
    with pytest.raises(worker.CoordinatorRefusal):
        worker.run(root, "", wait=exits_immediately)
    assert snapshot(root) == before


# --------------------------------------------------------------------------- #
# The handshake and the wait
# --------------------------------------------------------------------------- #


def test_acknowledgement_only_happens_after_validation(tmp_path):
    root = fake_root(tmp_path)
    state.ensure_state_dir(root)
    state.request_path(root).write_text("{}", encoding="utf-8")
    with pytest.raises(worker.CoordinatorRefusal):
        worker.run(root, "", wait=exits_immediately)
    assert not state.accepted_path(root).exists()


def test_a_valid_request_is_acknowledged_before_the_wait(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, ("application_logs",))
    seen = {}

    def wait(process_id, **kwargs):
        seen["acknowledged"] = state.read_acceptance(root, request) is not None
        return True

    worker.run(root, request.request_id, wait=wait)
    assert seen["acknowledged"] is True


def test_the_coordinator_waits_for_the_requesting_process(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, ("application_logs",), pid=4321)
    seen = {}

    def wait(process_id, **kwargs):
        seen["pid"] = process_id
        return True

    worker.run(root, request.request_id, wait=wait)
    assert seen["pid"] == 4321


def test_a_process_that_never_exits_removes_nothing(tmp_path):
    root = fake_root(tmp_path)
    before = snapshot(root)
    request = scheduled(root, tuple(mnt.ASSET_IDS))
    result = worker.run(root, request.request_id, wait=never_exits)
    assert {o.status for o in result.outcomes} == {"refused"}
    assert snapshot(root) == before


def test_a_process_that_never_exits_still_consumes_its_request(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, ("application_logs",))
    worker.run(root, request.request_id, wait=never_exits)
    assert state.load_request(root) is None


def test_the_wait_is_bounded_and_is_not_a_busy_loop():
    ticks = iter([0.0, 0.5, 1.0, 1.5, 2.0])
    slept: list[float] = []
    finished = state.wait_for_process_exit(
        999_999_999, handle=None, timeout=1.0, poll=0.25,
        sleep=slept.append, monotonic=lambda: next(ticks),
    )
    assert finished is True          # a process id that is not running
    assert slept == []


def test_the_wait_gives_up_on_a_process_that_outlives_the_timeout(monkeypatch):
    monkeypatch.setattr(state, "process_is_running", lambda _p: True)
    ticks = iter([0.0, 0.5, 1.0, 1.5])
    slept: list[float] = []
    assert state.wait_for_process_exit(
        4321, handle=None, timeout=1.0, poll=0.5,
        sleep=slept.append, monotonic=lambda: next(ticks),
    ) is False
    assert slept          # it slept between probes rather than spinning


def test_a_process_that_has_already_gone_is_not_waited_for():
    assert state.process_is_running(0) is False
    assert state.process_is_running(-1) is False


def test_this_process_is_seen_as_running():
    assert state.process_is_running(os.getpid()) is True


@pytest.mark.skipif(os.name != "nt", reason="handles are a Windows primitive")
def test_a_handle_binds_the_wait_to_one_exact_process():
    handle = state.open_process_handle(os.getpid())
    assert handle is not None
    state.close_process_handle(handle)
    assert state.open_process_handle(999_999_999) is None


# --------------------------------------------------------------------------- #
# Deletion semantics
# --------------------------------------------------------------------------- #


def test_one_selected_asset_is_removed_and_the_others_are_untouched(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, ("application_logs",))
    result = worker.run(root, request.request_id, wait=exits_immediately)

    outcome = outcomes_by_id(result)["application_logs"]
    assert outcome.status == "removed"
    assert outcome.bytes_freed == LOG_BYTES
    assert (root / "files" / "runtime-data" / "logs").is_dir()
    assert not any((root / "files" / "runtime-data" / "logs").iterdir())
    assert (root / ".venv" / "pyvenv.cfg").exists()
    assert (root / "files" / "bin" / "ffmpeg.exe").exists()
    assert (root / "files" / "runtime-data" / "models" / "kokoro" / "model.bin").exists()


def test_all_four_assets_are_removed_with_their_exact_semantics(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, tuple(mnt.ASSET_IDS))
    result = worker.run(root, request.request_id, wait=exits_immediately)

    assert [o.status for o in result.outcomes] == ["removed"] * 4
    # The environment goes entirely; the other three keep their folder.
    assert not (root / ".venv").exists()
    for relative in ("files/bin", "files/runtime-data/models",
                     "files/runtime-data/logs"):
        directory = root.joinpath(*relative.split("/"))
        assert directory.is_dir()
        assert not any(directory.iterdir())


def test_the_reported_byte_totals_match_the_fixture(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, tuple(mnt.ASSET_IDS))
    result = worker.run(root, request.request_id, wait=exits_immediately)
    freed = {o.asset_id: o.bytes_freed for o in result.outcomes}
    assert freed == {
        "virtual_environment": VENV_BYTES,
        "portable_binaries": BIN_BYTES,
        "downloaded_models": MODEL_BYTES,
        "application_logs": LOG_BYTES,
    }


def test_a_missing_target_is_a_successful_no_op(tmp_path):
    root = fake_root(tmp_path, venv=False, binaries=False)
    request = scheduled(root, ("virtual_environment", "portable_binaries"))
    result = worker.run(root, request.request_id, wait=exits_immediately)
    for outcome in result.outcomes:
        assert outcome.status == "missing"
        assert outcome.bytes_freed == 0


def test_nested_folders_are_emptied_completely(tmp_path):
    root = fake_root(tmp_path)
    deep = root / "files" / "runtime-data" / "models" / "a" / "b" / "c"
    write(deep / "weights.bin", b"w" * 64)
    request = scheduled(root, ("downloaded_models",))
    result = worker.run(root, request.request_id, wait=exits_immediately)
    assert outcomes_by_id(result)["downloaded_models"].bytes_freed == MODEL_BYTES + 64
    assert not any((root / "files" / "runtime-data" / "models").iterdir())


def test_nothing_outside_the_selected_targets_is_touched(tmp_path):
    root = fake_root(tmp_path)
    protected = {
        "config.toml": (root / "config.toml"),
        "settings.json": (root / "files" / "runtime-data" / "settings.json"),
        "briefing": (root / "md-instructions" / "Briefing.md"),
        "readme": (root / "README.md"),
    }
    before = {key: hashlib.sha256(path.read_bytes()).hexdigest()
              for key, path in protected.items()}
    request = scheduled(root, tuple(mnt.ASSET_IDS))
    worker.run(root, request.request_id, wait=exits_immediately)
    for key, path in protected.items():
        assert path.exists(), key
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before[key]
    assert (root / "scripts").is_dir()
    assert (root / "files" / "tests").is_dir()


def test_a_read_only_file_is_still_removed(tmp_path):
    root = fake_root(tmp_path)
    stubborn = root / "files" / "runtime-data" / "logs" / "read-only.log"
    write(stubborn, b"r" * 10)
    os.chmod(stubborn, 0o444)
    request = scheduled(root, ("application_logs",))
    result = worker.run(root, request.request_id, wait=exits_immediately)
    assert outcomes_by_id(result)["application_logs"].status == "removed"
    assert not stubborn.exists()


@pytest.mark.skipif(os.name != "nt", reason="an open handle only blocks deletion on Windows")
def test_a_locked_file_becomes_a_truthful_partial_failure(tmp_path):
    root = fake_root(tmp_path)
    locked = root / "files" / "runtime-data" / "logs" / "open.log"
    write(locked, b"o" * 20)
    other = root / "files" / "runtime-data" / "logs" / "closed.log"
    write(other, b"c" * 30)
    request = scheduled(root, ("application_logs",))
    handle = open(locked, "r+b")
    try:
        result = worker.run(root, request.request_id, wait=exits_immediately)
    finally:
        handle.close()
    outcome = outcomes_by_id(result)["application_logs"]
    assert outcome.status == "failed"
    assert "open.log" in outcome.message
    assert locked.exists()
    assert not other.exists()          # the pass continued past the failure
    assert outcome.bytes_freed >= 30


@pytest.mark.skipif(os.name != "nt", reason="an open handle only blocks deletion on Windows")
def test_a_failure_in_one_asset_does_not_stop_the_others(tmp_path):
    root = fake_root(tmp_path)
    locked = root / "files" / "runtime-data" / "logs" / "open.log"
    write(locked, b"o" * 20)
    request = scheduled(root, ("application_logs", "downloaded_models"))
    handle = open(locked, "r+b")
    try:
        result = worker.run(root, request.request_id, wait=exits_immediately)
    finally:
        handle.close()
    statuses = {o.asset_id: o.status for o in result.outcomes}
    assert statuses == {"application_logs": "failed", "downloaded_models": "removed"}


def test_a_target_that_is_not_a_folder_is_refused(tmp_path):
    root = fake_root(tmp_path, binaries=False)
    write(root / "files" / "bin", b"not a folder")
    request = scheduled(root, ("portable_binaries",))
    result = worker.run(root, request.request_id, wait=exits_immediately)
    outcome = outcomes_by_id(result)["portable_binaries"]
    assert outcome.status == "refused"
    assert (root / "files" / "bin").is_file()


def test_a_target_swapped_for_a_link_between_review_and_deletion_is_refused(tmp_path):
    root = fake_root(tmp_path, models=False)
    elsewhere = tmp_path / "real-models"
    write(elsewhere / "precious.bin", b"p" * 4096)
    request = scheduled(root, ("downloaded_models",))
    if not make_junction(root / "files" / "runtime-data" / "models", elsewhere):
        pytest.skip("this account cannot create a junction")
    result = worker.run(root, request.request_id, wait=exits_immediately)
    outcome = outcomes_by_id(result)["downloaded_models"]
    assert outcome.status == "refused"
    assert "link" in outcome.message
    assert (elsewhere / "precious.bin").read_bytes() == b"p" * 4096


def test_a_link_inside_a_target_is_detached_but_never_followed(tmp_path):
    root = fake_root(tmp_path)
    elsewhere = tmp_path / "outside-data"
    write(elsewhere / "keep-me.bin", b"k" * 999)
    inside = root / "files" / "runtime-data" / "models" / "shortcut"
    if not make_junction(inside, elsewhere):
        pytest.skip("this account cannot create a junction")
    request = scheduled(root, ("downloaded_models",))
    result = worker.run(root, request.request_id, wait=exits_immediately)
    outcome = outcomes_by_id(result)["downloaded_models"]
    assert outcome.status == "removed"
    assert outcome.bytes_freed == MODEL_BYTES        # the link's contents never counted
    assert not inside.exists()
    assert (elsewhere / "keep-me.bin").read_bytes() == b"k" * 999


def test_an_unknown_id_can_never_be_processed(tmp_path):
    root = fake_root(tmp_path)
    for bad in ("everything", "../..", "C:\\Windows", "files/tests", ""):
        with pytest.raises(mnt.UnknownAssetError):
            worker.process_asset(bad, root)


def test_processing_re_authorizes_rather_than_trusting_the_caller(tmp_path):
    root = fake_root(tmp_path)
    link_root = tmp_path / "linked-repo"
    if not make_junction(link_root, root):
        pytest.skip("this account cannot create a junction")
    outcome = worker.process_asset("application_logs", link_root)
    assert outcome.status == "refused"
    assert (root / "files" / "runtime-data" / "logs" / "session.log").exists()


# --------------------------------------------------------------------------- #
# One attempt, one result
# --------------------------------------------------------------------------- #


def test_the_request_is_consumed_before_anything_is_deleted(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, ("application_logs",))
    seen = {}

    original = worker.remove_directory_contents

    def watch(target):
        seen["request_gone"] = state.load_request(root) is None
        return original(target)

    worker.remove_directory_contents = watch
    try:
        worker.run(root, request.request_id, wait=exits_immediately)
    finally:
        worker.remove_directory_contents = original
    assert seen["request_gone"] is True


def test_a_replayed_request_deletes_nothing_a_second_time(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, ("downloaded_models",))
    worker.run(root, request.request_id, wait=exits_immediately)
    write(root / "files" / "runtime-data" / "models" / "new.bin", b"n" * 12)
    with pytest.raises(worker.CoordinatorRefusal):
        worker.run(root, request.request_id, wait=exits_immediately)
    assert (root / "files" / "runtime-data" / "models" / "new.bin").exists()


def test_a_withdrawn_request_stops_the_run_before_deletion(tmp_path):
    root = fake_root(tmp_path)
    before = snapshot(root)
    request = scheduled(root, ("application_logs",))

    def withdraw(process_id, **kwargs):
        state.discard_request(root, request.request_id)
        return True

    assert worker.run(root, request.request_id, wait=withdraw) is None
    after = snapshot(root)
    for name, digest in before.items():
        assert after[name] == digest


def test_the_result_is_written_where_nothing_can_delete_it(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, tuple(mnt.ASSET_IDS))
    worker.run(root, request.request_id, wait=exits_immediately)
    assert state.result_path(root).exists()
    for asset_id in mnt.ASSET_IDS:
        target = mnt.compiled_target(asset_id, root)
        assert not mnt.is_within(target, state.result_path(root))


def test_the_result_matches_the_request(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, ("application_logs", "portable_binaries"))
    result = worker.run(root, request.request_id, wait=exits_immediately)
    assert result.request_id == request.request_id
    assert [o.asset_id for o in result.outcomes] == list(request.asset_ids)
    assert state.load_result(root) == result


def test_the_result_names_no_path(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, tuple(mnt.ASSET_IDS))
    worker.run(root, request.request_id, wait=exits_immediately)
    text = state.result_path(root).read_text(encoding="utf-8")
    assert str(root) not in text
    assert "\\\\" not in text


def test_the_coordinator_log_lives_outside_every_target(tmp_path):
    root = fake_root(tmp_path)
    log = worker.CoordinatorLog(root)
    try:
        log.line("hello")
    finally:
        log.close()
    path = state.state_dir(root) / state.COORDINATOR_LOG_NAME
    assert path.exists()
    for asset_id in mnt.ASSET_IDS:
        assert not mnt.is_within(mnt.compiled_target(asset_id, root), path)


def test_the_run_records_technical_detail_without_raising(tmp_path):
    root = fake_root(tmp_path)
    request = scheduled(root, ("application_logs",))
    log = worker.CoordinatorLog(root)
    try:
        worker.run(root, request.request_id, log, wait=exits_immediately)
    finally:
        log.close()
    text = (state.state_dir(root) / state.COORDINATOR_LOG_NAME).read_text(
        encoding="utf-8"
    )
    assert "accepted request" in text
    assert "application_logs" in text


# --------------------------------------------------------------------------- #
# Result wording
# --------------------------------------------------------------------------- #


def result_with(statuses, *, freed=100):
    now = datetime.now(UTC)
    return mnt.CleanupResult(
        schema_version=mnt.SCHEMA_VERSION,
        request_id="3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        started_at=now, completed_at=now,
        outcomes=tuple(mnt.AssetOutcome(asset_id, status, freed,
                                        "" if status in ("removed", "missing")
                                        else "thing.dll: Access is denied")
                       for asset_id, status in statuses.items()),
    )


def test_a_complete_result_says_so():
    result = result_with({"application_logs": "removed"})
    assert mnt.result_heading(result) == mnt.RESULT_HEADING_COMPLETE
    assert mnt.result_is_complete(result) is True


def test_a_result_where_nothing_was_there_does_not_claim_a_removal():
    result = result_with({"application_logs": "missing", "portable_binaries": "missing"},
                         freed=0)
    assert mnt.result_heading(result) == mnt.RESULT_HEADING_NOTHING


@pytest.mark.parametrize("status", ["failed", "refused"])
def test_a_result_with_any_problem_never_claims_complete_success(status):
    result = result_with({"application_logs": "removed", "portable_binaries": status})
    assert mnt.result_heading(result) == mnt.RESULT_HEADING_PARTIAL
    assert mnt.RESULT_RECOVERY_LINE in mnt.result_body(result)


def test_every_outcome_is_listed_by_name():
    result = result_with({asset_id: "removed" for asset_id in mnt.ASSET_IDS})
    body = mnt.result_body(result)
    for definition in mnt.CATALOG:
        assert definition.display_name in body


def test_a_failure_message_is_carried_into_the_summary():
    body = mnt.result_body(result_with({"application_logs": "failed"}))
    assert "thing.dll: Access is denied" in body
    assert mnt.STATUS_TEXT["failed"] in body


def test_freed_space_is_never_invented():
    now = datetime.now(UTC)
    result = mnt.CleanupResult(
        schema_version=mnt.SCHEMA_VERSION,
        request_id="3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        started_at=now, completed_at=now,
        outcomes=(mnt.AssetOutcome("application_logs", "removed", None, ""),),
    )
    known, complete = mnt.result_freed_bytes(result)
    assert (known, complete) == (0, False)
    assert "at least" in mnt.result_body(result)


def test_the_summary_carries_no_path():
    body = mnt.result_body(result_with({asset_id: "removed" for asset_id in mnt.ASSET_IDS}))
    assert ":\\" not in body
    assert "/home/" not in body


# --------------------------------------------------------------------------- #
# A real coordinator process, inside a disposable copy
# --------------------------------------------------------------------------- #


def disposable_copy(tmp_path: Path, *, name="disposable-repo") -> Path:
    """A fake root carrying its own copy of the coordinator's four modules."""
    root = fake_root(tmp_path, name=name)
    source = REPO_ROOT / "scripts" / "Universal" / "shared"
    destination = root / "scripts" / "Universal" / "shared"
    destination.mkdir(parents=True, exist_ok=True)
    for module in COORDINATOR_MODULES:
        shutil.copy2(source / module, destination / module)
    return root


def base_python(root: Path):
    found = state.find_non_venv_python(root)
    if found is None:
        pytest.skip("no verified base interpreter on this machine")
    return found


def test_a_real_coordinator_process_runs_entirely_outside_the_venv(tmp_path):
    """Imported by a base interpreter, with no project packages available."""
    root = disposable_copy(tmp_path)
    python = base_python(root)
    script = root / "scripts" / "Universal" / "shared" / "cleanup_worker.py"
    finished = subprocess.run(
        [str(python), "-c",
         "import sys; sys.path.insert(0, r'%s'); "
         "from shared import cleanup_worker as w; "
         "print(w.repository_root())" % (root / "scripts" / "Universal")],
        capture_output=True, text=True, timeout=120, cwd=str(tmp_path),
    )
    assert finished.returncode == 0, finished.stderr
    assert Path(finished.stdout.strip()) == root
    assert script.exists()


def test_a_real_coordinator_process_deletes_only_the_disposable_copy(tmp_path):
    root = disposable_copy(tmp_path)
    bystander = disposable_copy(tmp_path, name="bystander-repo")
    before = snapshot(bystander)
    python = base_python(root)
    script = root / "scripts" / "Universal" / "shared" / "cleanup_worker.py"
    request = scheduled(root, ("application_logs", "downloaded_models"),
                        pid=os.getpid())

    # The coordinator waits for *this* process, which is not going to exit, so
    # drive it past the wait with an already-dead requester instead.
    dead = build(("application_logs", "downloaded_models"), pid=_dead_pid())
    state.discard_request(root, request.request_id)
    state.store_request(dead, root)

    finished = subprocess.run(
        [str(python), str(script), "--run", "--request-id", dead.request_id],
        capture_output=True, text=True, timeout=180, cwd=str(tmp_path),
    )
    assert finished.returncode == 0, finished.stderr
    result = state.load_result(root)
    assert result is not None
    assert {o.status for o in result.outcomes} == {"removed"}
    assert not any((root / "files" / "runtime-data" / "logs").iterdir())
    assert snapshot(bystander) == before


def test_the_real_repository_is_never_the_coordinators_target(tmp_path):
    """The copy's root is the copy — proven from the copy's own output."""
    root = disposable_copy(tmp_path)
    python = base_python(root)
    finished = subprocess.run(
        [str(python), "-c",
         "import sys; sys.path.insert(0, r'%s'); "
         "from shared import cleanup_worker as w, maintenance as m; "
         "print(m.compiled_target('virtual_environment', w.repository_root()))"
         % (root / "scripts" / "Universal")],
        capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
    )
    assert finished.returncode == 0, finished.stderr
    target = Path(finished.stdout.strip())
    assert target == root / ".venv"
    assert not mnt.is_within(REPO_ROOT, target)


def _dead_pid() -> int:
    for candidate in range(999_990, 999_899, -1):
        if not state.process_is_running(candidate):
            return candidate
    return 999_999


# --------------------------------------------------------------------------- #
# Structural guards
# --------------------------------------------------------------------------- #


def module_tree():
    return ast.parse(MODULE.read_text(encoding="utf-8"))


def test_the_coordinator_is_standard_library_only():
    tree = module_tree()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    allowed = {"__future__", "argparse", "os", "stat", "sys", "datetime",
               "pathlib", "shared"}
    assert imported <= allowed, imported - allowed


def test_the_coordinator_never_uses_a_high_level_tree_remover():
    source = MODULE.read_text(encoding="utf-8")
    assert "shutil" not in source
    assert "rmtree" not in source


def test_the_coordinator_never_starts_another_process():
    tree = module_tree()
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for spawning in ("Popen", "system", "spawnv", "execv", "fork", "startfile", "run"):
        assert spawning not in called, spawning


def test_deletion_of_a_catalog_target_is_reachable_only_from_the_coordinator():
    """Only the coordinator removes a directory as part of cleanup.

    Two pre-existing, unrelated uses of ``rmtree`` are named explicitly rather
    than waved through: ``bootstrap.py`` rebuilds a broken virtual environment
    during setup, and ``metadata.py`` removes its own temporary work folder.
    Neither derives a path from the catalog, which is what the second assertion
    pins.
    """
    shared = REPO_ROOT / "scripts" / "Universal" / "shared"
    allowed_rmtree = {"bootstrap.py", "metadata.py"}
    for path in sorted(shared.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if path.name != "cleanup_worker.py":
            assert "os.rmdir" not in source, path.name
        if "rmtree" in source:
            assert path.name in allowed_rmtree, path.name
            assert "authorized_target" not in source
            assert "compiled_target" not in source


def test_the_gui_contains_no_recursive_deletion():
    for relative in ("shared/preferences_ui.py", "launcher.py"):
        source = (REPO_ROOT / "scripts" / "Universal" / relative).read_text(
            encoding="utf-8"
        )
        for destructive in ("rmtree", "os.remove", "os.unlink", "os.rmdir",
                            "shutil"):
            assert destructive not in source, f"{relative}: {destructive}"


def test_the_coordinator_never_names_a_user_location():
    source = MODULE.read_text(encoding="utf-8")
    for foreign in ("Downloads", "output_base", "settings.json", "config.toml",
                    "config-template", "ffmpeg", "site-packages"):
        assert foreign not in source, foreign


def test_no_test_in_this_module_deletes_from_the_real_repository():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    entry_points = {"run", "process_asset", "remove_directory_contents",
                    "remove_directory_tree", "store_request", "scheduled"}
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        owner = getattr(getattr(func, "value", None), "id", "")
        if owner in ("subprocess", "state", "mnt"):
            continue
        if name not in entry_points:
            continue
        for argument in list(call.args) + [k.value for k in call.keywords]:
            assert not any(isinstance(n, ast.Name) and n.id == "REPO_ROOT"
                           for n in ast.walk(argument)), name
