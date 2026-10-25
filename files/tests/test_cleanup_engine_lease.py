"""v0.7.0 P04C Stage 3 — Clear Downloaded Data never races the Qwen3 voices of its own copy.

**The race this closes.** The post-exit coordinator (``shared.cleanup_worker``) refused a ``.venv`` holding anything
under ``engines/`` -- but only by looking. With no engine there yet, a first Qwen3 install of the same copy (another
window, or one started after the requester exited) could hold ``setup.lock`` and be about to create
``.venv/engines/qwen3`` at the moment the coordinator looked, found nothing, and began deleting ``.venv``; or the
install could start while the deletion was under way and build its engine inside a half-deleted parent. The models
folder had the same gap against a running conversion, model check or worker.

Now an item marked ``requires_engine_lease`` (``.venv`` and the models folder) is re-authorized and removed only while
the coordinator holds this copy's ``shared.engine_lease`` (``setup.lock`` → ``inference.lock`` → ``engine.lock``),
taken first and released last. Busy or uncheckable leaves the item exactly as it was and says so; every other selected
item is handled as before. ``MachineGuard`` (the cross-copy GPU limit) is deliberately not taken.

Every root here is a disposable folder under ``tmp_path``. Cross-process cases use real subprocesses: the production
installer stopped inside ``python -m venv`` (``test_qwen3_nested_adoption``'s harness) and real lock holders
(``test_qwen3_lifecycle_locks``'s). Nothing touches the real ``.venv``, ``.venv-qwen3``, models or runtime folder.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from shared import cleanup_state as state
from shared import cleanup_worker as worker
from shared import engine_lease as el
from shared import maintenance as mnt
from tts import qwen3_runtime as rt

from test_cleanup_worker import (
    base_python, disposable_copy, exits_immediately, make_junction, outcomes_by_id, scheduled, snapshot, write,
    _dead_pid,
)
from test_qwen3_lifecycle_locks import ALL_FREE, SCRIPTS, held_by_another_process, wait_free
from test_qwen3_nested_adoption import (  # noqa: F401  (sandbox is a fixture)
    DAMAGES, NESTED_PARTS, free_from_another_process, installer_mid_creation, run_installer,
)
from test_qwen3_runtime import install_environment, install_model, sandbox  # noqa: F401

LEASED = ("virtual_environment", "downloaded_models")
UNLEASED = ("portable_binaries", "application_logs")
NONE_FREE = {name: False for name in el.ORDER}
REGIONS = {
    "virtual_environment": ".venv/",
    "downloaded_models": "files/runtime-data/models/",
    "portable_binaries": "files/bin/",
    "application_logs": "files/runtime-data/logs/",
}
#: Private records and settings: never a target, never changed by any run here.
PRIVATE = ("files/runtime-data/settings.json", "files/runtime-data/qwen3/transcripts.json")


def region(root: Path, prefix: str) -> dict[str, str]:
    return {k: v for k, v in snapshot(root).items() if k.startswith(prefix)}


def private(root: Path) -> dict[str, str]:
    return {k: v for k, v in snapshot(root).items() if k in PRIVATE}


def lock_dir(root: Path) -> Path:
    return el.runtime_dir(root)


@pytest.fixture()
def copy(sandbox):
    """A copy of the app with no Qwen3 engine yet: data in all four items, private records, and a base Python outside.

    ``(root, base)``. ``sandbox`` points ``tts.qwen3_runtime`` at this root and already made ``.venv`` (no ``engines``).
    """
    root = sandbox
    write(root / ".venv" / "Lib" / "site-packages" / "app_package.py", b"a" * 400)
    write(root / "files" / "bin" / "tool.exe", b"b" * 1000)
    write(root / "files" / "runtime-data" / "models" / "kokoro" / "model.bin", b"m" * 2048)
    install_model(root, "customvoice")  # files/runtime-data/models/qwen3-tts/...
    write(root / "files" / "runtime-data" / "logs" / "session.log", b"l" * 50)
    write(root / "files" / "runtime-data" / "settings.json", b"{}")
    write(root / "files" / "runtime-data" / "qwen3" / "transcripts.json", b'{"private": true}')
    (root / "scripts" / "qwen3-requirements.txt").write_bytes(b"torch==1.0\n")
    base = root.parent / f"{root.name}-base" / "python.exe"
    write(base, b"base interpreter")
    assert not os.path.lexists(root / ".venv" / "engines")  # the child does not exist yet
    return root, base


# --------------------------------------------------------------------------- #
# A. Which items are leased, and that the lease spans re-authorization and removal
# --------------------------------------------------------------------------- #
def test_exactly_the_items_a_qwen3_user_can_reach_are_leased():
    assert tuple(a.asset_id for a in mnt.CATALOG if a.requires_engine_lease) == LEASED
    assert all(not mnt.asset(a).requires_engine_lease for a in UNLEASED)


@pytest.mark.parametrize("asset_id", LEASED)
def test_the_lease_is_held_from_before_reauthorization_until_the_removal_is_over(copy, monkeypatch, asset_id):
    root, _ = copy
    seen: dict[str, dict] = {}
    real_authorize, real_tree, real_contents = (mnt.authorized_target, worker.remove_directory_tree,
                                                worker.remove_directory_contents)

    def authorize(*args, **kwargs):
        seen.setdefault("re-authorization", free_from_another_process(lock_dir(root)))
        return real_authorize(*args, **kwargs)

    def removing(real):
        def remove(target):
            seen["removal"] = free_from_another_process(lock_dir(root))
            return real(target)
        return remove

    monkeypatch.setattr(mnt, "authorized_target", authorize)
    monkeypatch.setattr(worker, "remove_directory_tree", removing(real_tree))
    monkeypatch.setattr(worker, "remove_directory_contents", removing(real_contents))

    outcome = worker.process_asset(asset_id, root)

    assert outcome.status == "removed", outcome
    assert seen == {"re-authorization": NONE_FREE, "removal": NONE_FREE}
    assert free_from_another_process(lock_dir(root)) == ALL_FREE  # released the moment it is done


@pytest.mark.parametrize("asset_id", UNLEASED)
def test_an_item_no_qwen3_user_reaches_takes_no_lock(copy, asset_id):
    root, _ = copy
    assert worker.process_asset(asset_id, root).status == "removed"
    assert not any(os.path.lexists(lock_dir(root) / name) for name in el.ORDER)


# --------------------------------------------------------------------------- #
# B. The first-install race, in both orders, with no engine folder there to begin with
# --------------------------------------------------------------------------- #
def test_install_first_cleanup_leaves_the_environment_and_models_whole_and_still_clears_the_rest(copy):
    root, base = copy
    venv_before, models_before = region(root, ".venv/"), region(root, "files/runtime-data/models/")
    private_before = private(root)
    with installer_mid_creation(root, base) as installer:  # InstallLock held, .venv/engines not created yet
        request = scheduled(root, mnt.ASSET_IDS)
        result = worker.run(root, request.request_id, wait=exits_immediately)
        outcomes = outcomes_by_id(result)
        busy = mnt.engine_in_use_problem(el.BUSY_MESSAGES[el.SETUP_LOCK])
        for asset_id in LEASED:
            assert (outcomes[asset_id].status, outcomes[asset_id].bytes_freed, outcomes[asset_id].message) == (
                "refused", 0, busy), asset_id
        for asset_id in UNLEASED:  # the unrelated items the user also selected are cleared exactly as before
            assert outcomes[asset_id].status == "removed", asset_id
            assert region(root, REGIONS[asset_id]) == {}
        assert region(root, ".venv/") == venv_before and region(root, "files/runtime-data/models/") == models_before
        assert not os.path.lexists(root / ".venv" / "engines")
        assert mnt.result_heading(result) == mnt.RESULT_HEADING_PARTIAL  # never "cleared"

        installer.stdin.write("\n")
        installer.stdin.flush()
        out = installer.stdout.read()
        assert installer.wait(timeout=60) == 0 and "INSTALLED" in out, out
    child = root.joinpath(*NESTED_PARTS)
    assert child.is_dir() and rt.environment_status() == (True, "ok")  # built inside the untouched parent
    engine = region(root, ".venv/engines/")

    outcome = worker.process_asset("virtual_environment", root)  # lease free now: the held engine stops it
    assert outcome.status == "refused" and outcome.message == mnt.HELD_ENVIRONMENT_PROBLEM
    assert region(root, ".venv/engines/") == engine and rt.environment_status() == (True, "ok")
    assert private(root) == private_before


def test_cleanup_first_an_install_refuses_and_nothing_is_created_under_the_parent_being_removed(copy, monkeypatch):
    root, base = copy
    attempts: list[tuple] = []
    real = worker.remove_directory_tree

    def try_to_install(moment: str) -> None:
        code, out = run_installer(root, base)
        attempts.append((moment, code, "REFUSED" in out and "being installed or repaired" in out,
                         os.path.lexists(root / ".venv" / "engines"), free_from_another_process(lock_dir(root))))

    def removing(target):
        try_to_install("re-authorized, nothing removed yet")
        freed, problems = real(target)
        try_to_install("removed, lease still held")
        return freed, problems

    monkeypatch.setattr(worker, "remove_directory_tree", removing)
    outcome = worker.process_asset("virtual_environment", root)

    assert outcome.status == "removed" and not os.path.lexists(root / ".venv")
    assert attempts == [("re-authorized, nothing removed yet", 2, True, False, NONE_FREE),
                        ("removed, lease still held", 2, True, False, NONE_FREE)]
    code, out = run_installer(root, base)  # afterwards: refused for the missing parent, and it makes no .venv
    assert code == 2 and "missing or incomplete" in out, out
    assert not os.path.lexists(root / ".venv") and rt.NESTED_RECORD not in rt.read_state()


_CONVERSION = textwrap.dedent("""
    import sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from tts import qwen3_runtime as rt
    rt.runtime_dir = lambda: Path(sys.argv[2])
    rt.MACHINE_GUARD_NAME = sys.argv[3]
    try:
        rt.inference_lease().__enter__()
    except rt.Qwen3Unavailable as exc:
        print("REFUSED " + str(exc))
    else:
        print("ENTERED")
""")


def a_conversion_starts(root: Path) -> str:
    proc = subprocess.run([sys.executable, "-c", _CONVERSION, str(SCRIPTS), str(lock_dir(root)), rt.MACHINE_GUARD_NAME],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_cleanup_first_no_conversion_or_model_install_starts_while_the_models_are_removed(copy, monkeypatch):
    root, base = copy
    seen: list[tuple] = []
    real = worker.remove_directory_contents

    def removing(target):
        code, out = run_installer(root, base)
        seen.append((a_conversion_starts(root).startswith("REFUSED"), code, free_from_another_process(lock_dir(root))))
        return real(target)

    monkeypatch.setattr(worker, "remove_directory_contents", removing)
    outcome = worker.process_asset("downloaded_models", root)

    assert outcome.status == "removed" and region(root, "files/runtime-data/models/") == {}
    assert seen == [(True, 2, NONE_FREE)]
    assert a_conversion_starts(root) == "ENTERED"  # and once it is over, a conversion may start again


# --------------------------------------------------------------------------- #
# C. Real holders in other processes: every busy lock refuses, every time, with nothing removed
# --------------------------------------------------------------------------- #
BUSY_LOCK = {"worker": el.ENGINE_LOCK, "conversion": el.INFERENCE_LOCK, "install": el.SETUP_LOCK,
             "lease": el.SETUP_LOCK}


@pytest.mark.parametrize("asset_id", LEASED)
@pytest.mark.parametrize("mode", sorted(BUSY_LOCK))
def test_a_busy_engine_of_this_copy_leaves_the_item_whole_and_says_why(copy, mode, asset_id):
    root, _ = copy
    before, private_before = region(root, REGIONS[asset_id]), private(root)
    with held_by_another_process(mode, lock_dir(root)):
        request = scheduled(root, (asset_id, "application_logs"))
        outcomes = outcomes_by_id(worker.run(root, request.request_id, wait=exits_immediately))
    refused = outcomes[asset_id]
    assert (refused.status, refused.bytes_freed) == ("refused", 0)
    assert refused.message == mnt.engine_in_use_problem(el.BUSY_MESSAGES[BUSY_LOCK[mode]])
    assert "nothing in it was removed" in refused.message
    assert outcomes["application_logs"].status == "removed"
    assert region(root, REGIONS[asset_id]) == before and private(root) == private_before

    assert wait_free(lock_dir(root)) == ALL_FREE  # the holder is gone: the same item now clears
    assert worker.process_asset(asset_id, root).status == "removed"


def test_a_worker_that_dies_frees_the_cleanup(copy):
    root, _ = copy
    with held_by_another_process("worker", lock_dir(root), kill=True):
        assert worker.process_asset("virtual_environment", root).status == "refused"
    assert wait_free(lock_dir(root)) == ALL_FREE
    assert worker.process_asset("virtual_environment", root).status == "removed"


def test_another_copy_s_gpu_guard_does_not_stop_this_copy_s_cleanup(copy):
    """MachineGuard keeps every copy to one model on the GPU; it protects no file of this copy, so it is not taken."""
    root, _ = copy
    with held_by_another_process("guard", lock_dir(root)):
        for asset_id in LEASED:
            assert worker.process_asset(asset_id, root).status == "removed", asset_id


def test_the_coordinator_never_takes_the_machine_guard():
    source = Path(worker.__file__).read_text(encoding="utf-8")
    assert "MachineGuard" not in source
    assert "qwen3_runtime" not in source and "from tts" not in source


# --------------------------------------------------------------------------- #
# D. Locks that cannot be checked: refused, nothing removed, nothing followed
# --------------------------------------------------------------------------- #
def _without_lock_folder(root: Path) -> None:
    """The fixture keeps a private record in the lock folder; these cases need the folder itself replaced."""
    folder = lock_dir(root)
    for path in folder.iterdir():
        path.unlink()
    folder.rmdir()


def _engine_lock_is_a_folder(root: Path, tmp_path: Path, monkeypatch) -> None:
    (lock_dir(root) / el.ENGINE_LOCK).mkdir(parents=True)


def _lock_folder_is_a_file(root: Path, tmp_path: Path, monkeypatch) -> None:
    _without_lock_folder(root)
    write(lock_dir(root), b"not a folder")


def _locks_are_denied(root: Path, tmp_path: Path, monkeypatch) -> None:
    def denied(self):
        raise PermissionError(13, "Access is denied", str(self.path))
    monkeypatch.setattr(el.FileLock, "acquire", denied)


def _lock_folder_is_a_junction(root: Path, tmp_path: Path, monkeypatch) -> None:
    if os.name != "nt":
        pytest.skip("junctions are a Windows mechanism")
    _without_lock_folder(root)
    elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    write(elsewhere / "keep.txt", b"outside")
    if not make_junction(lock_dir(root), elsewhere):
        pytest.skip("cannot create a junction here")


UNCHECKABLE = {
    "engine.lock is a folder": _engine_lock_is_a_folder,
    "the lock folder is a file": _lock_folder_is_a_file,
    "the locks are denied": _locks_are_denied,
    "the lock folder is a junction out of the app": _lock_folder_is_a_junction,
}


@pytest.mark.parametrize("asset_id", LEASED)
@pytest.mark.parametrize("case", sorted(UNCHECKABLE))
def test_a_lock_that_cannot_be_checked_leaves_the_item_whole(copy, tmp_path, monkeypatch, case, asset_id):
    root, _ = copy
    UNCHECKABLE[case](root, tmp_path, monkeypatch)
    before = region(root, REGIONS[asset_id])
    elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"

    outcome = worker.process_asset(asset_id, root)

    assert (outcome.status, outcome.bytes_freed, outcome.message) == ("refused", 0, mnt.ENGINE_UNCHECKABLE_PROBLEM)
    assert region(root, REGIONS[asset_id]) == before
    if elsewhere.exists():
        assert sorted(p.name for p in elsewhere.iterdir()) == ["keep.txt"]  # nothing created through the junction
    assert worker.process_asset("application_logs", root).status == "removed"  # the unrelated item is unaffected


# --------------------------------------------------------------------------- #
# E. What is held in .venv: canonical healthy / damaged / partial, legacy-only, both, unexpected entries
# --------------------------------------------------------------------------- #
def _child(root: Path) -> Path:
    return root.joinpath(*NESTED_PARTS)


@pytest.mark.parametrize("damage", ["healthy", "has no pyvenv.cfg", "was created elsewhere and moved",
                                    "was built from a Python that has changed", "was being created when it stopped"])
def test_a_canonical_engine_in_any_state_is_never_removed_and_the_models_still_clear(copy, damage):
    root, _ = copy
    install_environment(root)
    if damage != "healthy":
        DAMAGES[damage][0](_child(root), root)
    engine, venv_before = region(root, ".venv/engines/"), region(root, ".venv/")
    assert engine

    outcome = worker.process_asset("virtual_environment", root)
    assert (outcome.status, outcome.message) == ("refused", mnt.HELD_ENVIRONMENT_PROBLEM)
    assert region(root, ".venv/") == venv_before

    assert worker.process_asset("downloaded_models", root).status == "removed"  # lease free: regenerable models go
    assert region(root, ".venv/") == venv_before  # the models item never reaches into the environment


def test_an_engine_left_half_made_by_a_killed_installer_is_never_removed(copy):
    root, base = copy
    with installer_mid_creation(root, base, mode="die") as installer:
        installer.stdin.write("\n")
        installer.stdin.flush()
        assert installer.wait(timeout=60) == 3
    assert wait_free(lock_dir(root)) == ALL_FREE
    assert (_child(root) / "Lib" / "half.py").is_file()
    before = region(root, ".venv/")
    outcome = worker.process_asset("virtual_environment", root)
    assert (outcome.status, outcome.message) == ("refused", mnt.HELD_ENVIRONMENT_PROBLEM)
    assert region(root, ".venv/") == before


def test_with_only_the_legacy_engine_the_environment_clears_and_the_legacy_engine_is_untouched(copy):
    root, _ = copy
    (root / ".venv-qwen3").mkdir()
    install_environment(root)
    legacy = region(root, ".venv-qwen3/")
    assert legacy and rt.venv_dir() == root / ".venv-qwen3"

    assert worker.process_asset("virtual_environment", root).status == "removed"
    assert not os.path.lexists(root / ".venv") and region(root, ".venv-qwen3/") == legacy
    assert rt.venv_dir() == root / ".venv-qwen3"  # still the one in use


def test_with_both_engines_present_neither_is_removed(copy):
    root, _ = copy
    (root / ".venv-qwen3").mkdir()
    install_environment(root)
    _child(root).mkdir(parents=True)
    install_environment(root)
    before = {**region(root, ".venv/"), **region(root, ".venv-qwen3/")}
    assert worker.process_asset("virtual_environment", root).status == "refused"
    assert {**region(root, ".venv/"), **region(root, ".venv-qwen3/")} == before


def _plant(root: Path, tmp_path: Path, kind: str) -> None:
    engines = root / ".venv" / "engines"
    if kind == "another engine":
        write(engines / "other" / "pyvenv.cfg", b"home = x\n")
    elif kind == "a stray file":
        write(engines / "notes.txt", b"x")
    elif kind == "engines is a file":
        write(engines, b"x")
    elif kind == "engines is a junction":
        if os.name != "nt":
            pytest.skip("junctions are a Windows mechanism")
        elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
        write(elsewhere / "keep.txt", b"outside")
        if not make_junction(engines, elsewhere):
            pytest.skip("cannot create a junction here")


@pytest.mark.parametrize("kind", ["another engine", "a stray file", "engines is a file", "engines is a junction"])
def test_anything_unexpected_under_engines_stops_the_removal(copy, tmp_path, kind):
    root, _ = copy
    _plant(root, tmp_path, kind)
    before = region(root, ".venv/")
    outcome = worker.process_asset("virtual_environment", root)
    assert (outcome.status, outcome.message) == ("refused", mnt.HELD_ENVIRONMENT_PROBLEM)
    assert region(root, ".venv/") == before
    elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    if elsewhere.exists():
        assert sorted(p.name for p in elsewhere.iterdir()) == ["keep.txt"]


def test_an_empty_engines_folder_does_not_stop_it(copy):
    root, _ = copy
    (root / ".venv" / "engines").mkdir()
    assert worker.process_asset("virtual_environment", root).status == "removed"


# --------------------------------------------------------------------------- #
# F. Links and escapes, under the lease
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows mechanism")
@pytest.mark.parametrize("where", [".venv", "files/runtime-data/models"])
def test_a_leased_item_that_is_a_junction_out_of_the_app_is_refused_and_not_followed(copy, tmp_path, where):
    root, _ = copy
    target = root.joinpath(*where.split("/"))
    asset_id = "virtual_environment" if where == ".venv" else "downloaded_models"
    for path in sorted(target.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    target.rmdir()
    elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    write(elsewhere / "keep.txt", b"outside")
    if not make_junction(target, elsewhere):
        pytest.skip("cannot create a junction here")
    outcome = worker.process_asset(asset_id, root)
    assert outcome.status == "refused" and "link" in outcome.message
    assert (elsewhere / "keep.txt").read_bytes() == b"outside"
    assert free_from_another_process(lock_dir(root)) == ALL_FREE


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows mechanism")
def test_a_junction_inside_the_environment_is_removed_as_a_link_only(copy, tmp_path):
    root, _ = copy
    elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    write(elsewhere / "keep.txt", b"outside")
    if not make_junction(root / ".venv" / "Lib" / "linked", elsewhere):
        pytest.skip("cannot create a junction here")
    assert worker.process_asset("virtual_environment", root).status == "removed"
    assert not os.path.lexists(root / ".venv") and (elsewhere / "keep.txt").read_bytes() == b"outside"


# --------------------------------------------------------------------------- #
# G. Interrupted cleanup, honest outcomes, and a real coordinator process
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(os.name != "nt", reason="an open handle only blocks deletion on Windows")
def test_an_interrupted_removal_reports_failure_releases_the_lease_and_a_second_run_finishes(copy):
    root, _ = copy
    locked = root / ".venv" / "Lib" / "site-packages" / "app_package.py"
    with open(locked, "rb"):
        first = worker.process_asset("virtual_environment", root)
        assert free_from_another_process(lock_dir(root)) == ALL_FREE
    assert first.status == "failed" and "app_package.py" in first.message
    second = worker.process_asset("virtual_environment", root)
    assert second.status == "removed" and not os.path.lexists(root / ".venv")


def test_a_removal_that_crashes_still_releases_the_lease(copy, monkeypatch):
    root, _ = copy

    def crash(target):
        raise RuntimeError("stopped part-way")

    monkeypatch.setattr(worker, "remove_directory_tree", crash)
    with pytest.raises(RuntimeError):
        worker.process_asset("virtual_environment", root)
    assert free_from_another_process(lock_dir(root)) == ALL_FREE


def test_a_refused_item_reads_as_left_alone_in_the_result_the_user_sees(copy):
    root, _ = copy
    with held_by_another_process("conversion", lock_dir(root)):
        request = scheduled(root, ("downloaded_models",))
        result = worker.run(root, request.request_id, wait=exits_immediately)
    body = mnt.result_body(result)
    assert mnt.result_heading(result) == mnt.RESULT_HEADING_PARTIAL
    assert "Left alone for safety" in body and el.BUSY_MESSAGES[el.INFERENCE_LOCK] in body
    assert mnt.RESULT_RECOVERY_LINE in body


def test_a_real_coordinator_process_refuses_under_a_busy_install_and_clears_once_it_is_over(tmp_path):
    """The coordinator as shipped: a base interpreter, its own copied modules, a real installer lock elsewhere."""
    root = disposable_copy(tmp_path)
    python = base_python(root)
    script = root / "scripts" / "shared" / "cleanup_worker.py"
    models_before = region(root, "files/runtime-data/models/")

    def run_coordinator(ids):
        request = mnt.build_request(ids, process_id=_dead_pid())
        state.store_request(request, root)
        finished = subprocess.run([str(python), str(script), "--run", "--request-id", request.request_id],
                                  capture_output=True, text=True, timeout=180, cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr
        return outcomes_by_id(state.load_result(root))

    with held_by_another_process("install", lock_dir(root)):
        outcomes = run_coordinator(("downloaded_models", "application_logs"))
    assert outcomes["downloaded_models"].status == "refused"
    assert outcomes["downloaded_models"].message == mnt.engine_in_use_problem(el.BUSY_MESSAGES[el.SETUP_LOCK])
    assert outcomes["application_logs"].status == "removed"
    assert region(root, "files/runtime-data/models/") == models_before

    assert wait_free(lock_dir(root)) == ALL_FREE
    assert run_coordinator(("downloaded_models",))["downloaded_models"].status == "removed"
    assert region(root, "files/runtime-data/models/") == {}


# --------------------------------------------------------------------------- #
# H. Wording: rebuilding the app's dependencies is not removing a voice engine
# --------------------------------------------------------------------------- #
def test_the_environment_item_says_it_rebuilds_only_the_app_s_own_dependencies():
    item = mnt.asset("virtual_environment")
    for text in (item.consequence, item.effect_line):
        assert "app's own dependencies" in text and "Qwen3 voice engine is not part of this item" in text
    assert "never removed with it" in item.effect_line


def test_the_refusals_say_nothing_was_removed_and_what_to_do():
    for lock in el.ORDER:
        text = mnt.engine_in_use_problem(el.BUSY_MESSAGES[lock])
        assert text.startswith(el.BUSY_MESSAGES[lock]) and "nothing in it was removed" in text
        assert "clear this item again" in text
    assert "could not check" in mnt.ENGINE_UNCHECKABLE_PROBLEM
    assert "Nothing in it was removed" in mnt.ENGINE_UNCHECKABLE_PROBLEM
    for text in (mnt.ENGINE_IN_USE_SUFFIX, mnt.ENGINE_UNCHECKABLE_PROBLEM):
        assert ":\\" not in text and "/" not in text  # no path in front of a user


def test_no_test_here_points_the_coordinator_at_the_real_repository():
    import ast

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    assert not any(isinstance(n, ast.Name) and n.id == "REPO_ROOT" for n in ast.walk(tree))
