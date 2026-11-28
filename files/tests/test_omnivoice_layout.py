"""OmniVoice's environment layout: v0.8.2 Phase 5B's ``.venv-engines/omnivoice`` and the two places before it.

v0.8.0 (owner decision 2026-11-13) held the engine INSIDE the app's ``.venv`` (``.venv/engines/omnivoice``, beside
``.venv/engines/qwen3``), superseding the first builds' sibling ``.venv-omnivoice``. v0.8.2 Phase 5B (approved A1) moves
it beside ``.venv``, to ``.venv-engines/omnivoice``, built by uv from the engine's own locked project on this copy's
managed CPython. This module is the deterministic matrix for that layout:

* **the path contract** -- one place every install goes, built there by uv (never moved there), independent of the
  app's own environment; each place's receipt is its own file and version, bound to its own folder (and to the lock);
* **the earlier nested engine** -- keeps working, untouched, until the new engine is built and proved; only then is it
  moved whole to a labelled set-aside folder (never deleted); an interrupted or failed replacement leaves it in use;
* **the earlier sibling** -- recognised, never used, never adopted, never moved into place: the engine is built again
  in its own place, proved, recorded, and only then is the sibling retired, whole; every failure or interruption
  before that leaves it exactly where it was;
* **the parent's repair** -- an earlier copy's held engines survive every outcome of replacing the app's own
  environment (success, a failed build, failed packages, a refused carry, an interruption at each step), and a repair
  is refused while either engine is in use or being installed;
* **independent repairs** -- repairing one engine changes nothing of the other, or of the app's own packages;
* **no false readiness** -- a stale, copied or foreign receipt, an environment uv did not build on this copy's own
  Python, a changed managed Python, a missing interpreter, a wrong package or a failed proof never make it ready.

Nothing here reaches the internet, runs uv or pip, creates a real environment or loads a model: the installer's world is
the loopback sandbox of ``test_omnivoice_setup`` and the parent's transaction is the disposable one of
``test_venv_recovery``. Every test is refused, at the write itself, any write to the real installation.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from shared import bootstrap
from shared import engine_env
from shared import engine_lease as el
from shared import optional_setup_protocol as proto
from shared import venv_layout
from tts import omnivoice_runtime as ov
from tts import omnivoice_setup as ovs
from tts import omnivoice_worker as ow
from tts import optional_setup as osu
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su
from test_omnivoice_setup import (ENGINE, MODEL, MODEL_FILES, OV, PINS, WHEEL_BYTES, FakeGuard,  # noqa: F401
                                  FakeRunner, Omni, make_env, omni)
from test_omnivoice_synth import DLL_193, NETWORK_AT_IMPORT, PAGING_1455, SAC_4551, run_stack_worker
from test_optional_tts_setup import (component, fig, probes_are_explicit, sandbox, tiny_assets, tripwire,  # noqa: F401
                                     unit, world)
# The layout these tests model is v0.8.1's: both engines held inside .venv (Qwen3 moves to .venv-engines in v0.8.2
# Phase 5A, once a new install replaces it; until then a copy keeps exactly this layout).
from test_qwen3_runtime import install_engine_environment, install_nested_environment as install_qwen3
from test_qwen3_setup import FakeRunner as Qwen3Runner
from test_venv_recovery import (_Log, _caps, _creates_venv, _existing_venv, _probe, _protected,  # noqa: F401
                                _protected_after, _reconcile_spy, _seed_interpreter, _successful_repair_fakes, _tree,
                                env)

pytestmark = pytest.mark.usefixtures("production_writes_refused")

SCRIPTS = Path(bootstrap.SCRIPTS_DIR)
NESTED = ("engines", "omnivoice")
QWEN3 = ("engines", "qwen3")
MODEL_PATHS = [f"/k2-fsa/OmniVoice/resolve/{'c' * 40}/{name}" for name in MODEL_FILES]


@pytest.fixture(autouse=True)
def a_gpu(monkeypatch):
    """This computer has the GPU OmniVoice needs, so a voice's answer is about the environment and the model -- never
    "there is no graphics card", which would make every "not available" assertion here pass for the wrong reason."""
    monkeypatch.setattr(ov, "detect_gpu", lambda: rt.GpuInfo("RTX Test", 12000))


# --------------------------------------------------------------------------- #
# Helpers: the earlier sibling, a cached wheel set, a planted child engine
# --------------------------------------------------------------------------- #
def make_legacy(omni, *, pins=PINS, receipt=True) -> Path:
    """The earlier sibling as the first v0.8.0 builds left it: an environment at ``.venv-omnivoice`` and, beside the
    model, the version-1 receipt that recorded it as proved."""
    folder = ov.legacy_venv_dir()
    make_env(folder, omni.base, pins)
    (folder / "Lib" / "site-packages" / "omnivoice").mkdir(parents=True, exist_ok=True)
    (folder / "Lib" / "site-packages" / "omnivoice" / "weights.bin").write_bytes(b"legacy engine " * 512)
    if receipt:
        write_legacy_receipt(folder)
    return folder


def write_legacy_receipt(folder: Path, **over) -> dict:
    record = {"schema": ov.RECEIPT_SCHEMA, "version": ov.LEGACY_RECEIPT_VERSION, "stage": ov.STAGE_INSTALLED,
              "path": os.path.normpath(os.path.abspath(folder)), "packages_sha256": ov.packages_sha256(),
              "omnivoice": "0.2.1", "origin": ov.ORIGIN_ADOPTED, "base": venv_layout.base_identity(folder),
              "probe": {}, "probe_ok": True, **over}
    ov.legacy_receipt_path().parent.mkdir(parents=True, exist_ok=True)
    ov.legacy_receipt_path().write_text(json.dumps(record), encoding="utf-8")
    return record


def retired(omni) -> list[Path]:
    root = ov.set_aside_root()
    return sorted(p for p in root.iterdir() if p.name.startswith(ovs.RETIRED_PREFIX)) if root.is_dir() else []


def plant(parent: Path, parts: tuple[str, ...], marker: str) -> dict[str, str]:
    """A held child environment's worth of identifiable files under ``parent/engines/<name>``. Returns their hashes."""
    child = parent.joinpath(*parts)
    (child / "Lib" / "site-packages" / "torch").mkdir(parents=True)
    (child / "Scripts").mkdir()
    (child / "pyvenv.cfg").write_text("home = C:/base\ninclude-system-site-packages = false\n", encoding="utf-8")
    (child / "Scripts" / "python.exe").write_bytes(b"child interpreter " + marker.encode())
    (child / "Lib" / "site-packages" / "torch" / "weights.bin").write_bytes(marker.encode() * 4096)
    return _tree(child)


def both_engines(parent: Path) -> tuple[dict, dict]:
    return plant(parent, QWEN3, "qwen3"), plant(parent, NESTED, "omnivoice")


def engines_of(parent: Path) -> tuple[dict, dict]:
    return _tree(parent.joinpath(*QWEN3)), _tree(parent.joinpath(*NESTED))


_HOLDER = textwrap.dedent("""
    import sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from shared import engine_lease as el
    lock = el.FileLock(Path(sys.argv[2]))
    Path(sys.argv[2]).parent.mkdir(parents=True, exist_ok=True)
    assert lock.acquire()
    print("READY", flush=True)
    sys.stdin.readline()
""")


@contextlib.contextmanager
def held_elsewhere(path: Path):
    """A real operating-system lock on *path*, held by another process (a conversion, a worker, an installer)."""
    proc = subprocess.Popen([sys.executable, "-I", "-B", "-c", _HOLDER, str(SCRIPTS), str(path)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline().strip()
        assert line == "READY", (line, proc.stderr.read() if proc.poll() is not None else "")
        yield proc
    finally:
        with contextlib.suppress(OSError):
            proc.stdin.close()
        proc.wait(timeout=60)


# =========================================================================== #
# 1. The path contract
# =========================================================================== #
def test_the_engine_has_one_place_of_its_own_and_an_earlier_nested_engine_is_used_only_until_then(omni):
    assert venv_layout.ENGINE_OMNIVOICE == ".venv-engines/omnivoice" and venv_layout.LEGACY_OMNIVOICE == ".venv-omnivoice"
    assert venv_layout.NESTED_OMNIVOICE == ".venv/engines/omnivoice" and venv_layout.NESTED_QWEN3 == ".venv/engines/qwen3"
    engine = omni.root / ".venv-engines" / "omnivoice"
    nested = omni.root / ".venv" / "engines" / "omnivoice"
    assert ov.engine_venv_dir() == engine and ov.nested_venv_dir() == nested
    assert ov.legacy_venv_dir() == omni.root / ".venv-omnivoice" and ov.parent_venv_dir() == omni.root / ".venv"
    assert not venv_layout.is_within(ov.parent_venv_dir(), engine), "beside the app's environment, never inside it"
    assert ov.venv_dir() == engine, "nothing installed: the one place every install goes"
    make_legacy(omni)
    assert ov.venv_dir() == engine, "the sibling is never a runtime target"
    omni.nested()
    assert ov.venv_dir() == nested and ov.venv_python() == venv_layout.interpreter(nested), "the earlier engine works on"
    omni.env()
    omni.receipt(ov.STAGE_CREATED)
    assert ov.venv_dir() == nested, "a new engine that is not installed to the end is not used"
    omni.receipt()
    assert ov.venv_dir() == engine and ov.venv_python() == venv_layout.interpreter(engine)
    assert ov.reject_ready_engine("ImportError: x") and ov.venv_dir() == engine, \
        "once installed it stays the one in use: a damaged engine is never hidden behind an older one"
    layouts = venv_layout.omnivoice_layouts(omni.root)
    assert layouts.both and layouts.nested == nested and layouts.legacy == ov.legacy_venv_dir()


def test_each_place_has_its_own_receipt_file_and_version_and_none_lies_inside_an_environment(omni):
    paths = (ov.receipt_path(), ov.nested_receipt_path(), ov.legacy_receipt_path())
    assert len(set(paths)) == 3 and all(p.parent == ov.runtime_dir() for p in paths)
    assert len({ov.RECEIPT_VERSION, ov.NESTED_RECEIPT_VERSION, ov.LEGACY_RECEIPT_VERSION}) == 3
    for folder in (ov.parent_venv_dir(), ov.engine_venv_dir()):
        assert not any(venv_layout.is_within(folder, p) for p in paths)
    omni.env()
    written = omni.receipt()
    assert written["version"] == ov.RECEIPT_VERSION and venv_layout.same_path(written["path"], ov.engine_venv_dir())
    assert written["lock"] == ov.lock_identity()
    assert not ov.nested_receipt_path().exists() and not ov.legacy_receipt_path().exists()
    with pytest.raises(ValueError, match="never installed into"):
        ov.write_nested_receipt(ov.STAGE_INSTALLED)


def test_a_fresh_install_builds_the_engine_with_uv_at_its_final_place_beside_the_app_s_environment(omni):
    """A. Nothing here at all: the environment is created where it will run, on the managed CPython, never inside the
    app's own environment and never moved."""
    code, result = omni.install()
    assert result["state"] == proto.SUCCEEDED and result["verified"] == [OV], result
    engine = ov.engine_venv_dir()
    assert omni.runner.kinds() == ["venv", "sync", "probe"]
    venv, sync = omni.runner.commands[:2]
    assert venv == [str(c) for c in engine_env.venv_command(omni.root, ov.ENGINE_KEY)]
    assert venv_layout.same_path(venv[2], engine) and "--python" in venv and "--no-python-downloads" in venv
    assert sync == [str(c) for c in engine_env.sync_command(omni.root, ov.ENGINE_KEY)]
    assert engine_env.identity_problem(omni.root, ov.ENGINE_KEY) == "", "uv's environment on this copy's own CPython"
    assert not venv_layout.is_within(ov.parent_venv_dir(), venv_layout.read_pyvenv_cfg(engine)["home"])
    job = omni.runner.probe_jobs[0]
    assert venv_layout.same_path(job["environment"], engine)
    assert [Path(p) for p in job["foreign"]] == [omni.root / ".venv", omni.root / ".venv" / "engines" / "qwen3",
                                                 omni.root / ".venv-qwen3", omni.root / ".venv-omnivoice",
                                                 omni.root / ".venv-engines" / "qwen3"]
    receipt = ov.read_receipt()
    assert receipt["stage"] == ov.STAGE_INSTALLED and venv_layout.same_path(receipt["path"], engine)
    assert venv_layout.held_entries(ov.parent_venv_dir()) == (), "nothing is held inside the app's environment"
    assert not os.path.lexists(ov.legacy_venv_dir()) and retired(omni) == []


@pytest.mark.parametrize("problem", ["no parent", "pending repair"])
def test_the_engine_does_not_depend_on_the_app_s_own_environment(omni, problem):
    """The engine is independent of ``.venv`` (approved A1): a missing app environment, or one whose repair did not
    finish, neither blocks nor touches it (the shared install lock keeps a repair and an install apart)."""
    if problem == "no parent":
        (ov.parent_venv_dir() / "pyvenv.cfg").unlink()
    else:
        (omni.root / ".venv.replaced").mkdir()
    assert ovs.build_problem() == ""
    code, result = omni.install()
    assert result["state"] == proto.SUCCEEDED, result
    assert not (omni.root / ".venv" / "engines").exists() and ov.environment_status() == (True, "ok")


@pytest.mark.parametrize("missing, words", [
    ("lock", "package lock is missing"), ("uv", "package tool (uv)"), ("python", "package tool (uv)"),
])
def test_without_its_lock_uv_or_managed_python_nothing_is_downloaded_or_built(omni, monkeypatch, missing, words):
    from shared import uv_runner

    if missing == "lock":
        (ov.project_dir() / "uv.lock").unlink()
    elif missing == "uv":
        monkeypatch.setattr(uv_runner, "uv_problem", lambda root, platform=None: "uv is missing")
    else:
        uv_runner.managed_python(omni.root).unlink()
    assert words in ovs.build_problem()
    code, result = omni.install()
    if missing == "lock":  # without its lock the packages have no pinned source at all: the consent is refused
        assert result["state"] == proto.REFUSED and result["error"]["code"] == proto.SOURCE_UNPINNED, result
    else:
        assert result["state"] == proto.FAILED and words in result["error"]["message"], result
    assert omni.runner.commands == [] and omni.fetched() == [], "said before anything is downloaded or run"
    assert not os.path.lexists(ov.engine_venv_dir()) and ov.read_receipt() == {}


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is the Windows link that needs no privilege")
@pytest.mark.parametrize("where", ["engines folder", "engine"])
def test_a_link_at_or_above_the_engine_s_place_is_unverified_and_nothing_is_built_through_it(omni, tmp_path, where):
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    if where == "engines folder":
        _winapi.CreateJunction(str(outside), str(omni.root / ".venv-engines"))
    else:
        (omni.root / ".venv-engines").mkdir()
        _winapi.CreateJunction(str(outside), str(ov.engine_venv_dir()))
    assert ov.assess_engine().state == ov.ENGINE_UNVERIFIED and ov.assess_install().state == ov.ENGINE_UNVERIFIED
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.UNVERIFIED and data["acquire_units"] == []
    with pytest.raises(ovs.OmniVoiceSetupError):
        ovs.build_engine(runner=omni.runner, progress=lambda p: None, cancel_check=lambda: False)
    assert list(outside.iterdir()) == [] and omni.runner.commands == []


def test_a_copy_of_the_app_too_deep_for_the_engine_is_refused_for_this_component_alone(omni, monkeypatch):
    """``.venv-engines/omnivoice`` is exactly as long as the earlier ``.venv/engines/omnivoice``, so the measured depth of
    the deepest file holds unchanged for the new place."""
    assert len(venv_layout.ENGINE_OMNIVOICE) == len(venv_layout.NESTED_OMNIVOICE)
    assert ov.DEEPEST_NATIVE_LIBRARY_CHARS >= 136 and ov.DEEPEST_FILE_CHARS >= 169  # measured 135 + 1 and 168 + 1
    limit = ov.WINDOWS_MAX_PATH - ov.DEEPEST_NATIVE_LIBRARY_CHARS
    assert ov.install_depth_problem("C:\\" + "a" * (limit - 3), long_paths=True) == ""
    assert "OmniVoice needs" in ov.install_depth_problem("C:\\" + "a" * (limit - 2), long_paths=True)
    short = ov.WINDOWS_MAX_PATH - ov.DEEPEST_FILE_CHARS
    assert ov.install_depth_problem("C:\\" + "a" * (short - 3), long_paths=False) == ""
    assert ov.install_depth_problem("C:\\" + "a" * (short - 2), long_paths=False)
    monkeypatch.setattr(ov, "windows_long_paths_enabled", lambda: None)  # it could not be read: treated as off
    assert ov.install_depth_problem("C:\\" + "a" * (short - 2)) and not ov.install_depth_problem(
        "C:\\" + "a" * (short - 3))
    monkeypatch.setattr(ov, "windows_long_paths_enabled", lambda: True)
    assert ov.install_depth_problem("C:\\" + "a" * (short - 2)) == ""

    monkeypatch.setattr(ov, "install_depth_problem", lambda *a, **k: "too deep for OmniVoice")
    data = omni.plan()
    entry = component(data, OV)
    assert entry["readiness"] == proto.UNSUPPORTED and entry["reason"] == "too deep for OmniVoice"
    assert data["acquire_units"] == [] and ov.install_would_help() is False
    assert ov.assess_engine() == ov.EngineAssessment(ov.ENGINE_ABSENT, "too deep for OmniVoice")
    with pytest.raises(ovs.OmniVoiceSetupError, match="too deep"):
        ovs.build_engine(runner=omni.runner, progress=lambda p: None, cancel_check=lambda: False)
    assert omni.runner.commands == []
    omni.env()
    omni.model()
    omni.receipt()
    assert component(omni.plan(), OV)["readiness"] == proto.READY, "an engine that already works here is never refused"


# =========================================================================== #
# 2. The earlier sibling: recognised, never used, retired only after the proof
# =========================================================================== #
def test_the_sibling_s_states_are_told_apart_and_none_of_them_is_ever_ready(omni, tmp_path):
    assert ov.assess_legacy().state == ov.LEGACY_ABSENT and not ov.assess_legacy().present
    folder = make_legacy(omni)
    assert ov.assess_legacy().state == ov.LEGACY_HEALTHY
    for expected, change in (
            (ov.LEGACY_UNVERIFIED, lambda: ov.legacy_receipt_path().unlink()),
            (ov.LEGACY_UNVERIFIED, lambda: write_legacy_receipt(folder, packages_sha256="0" * 64)),
            (ov.LEGACY_UNVERIFIED, lambda: write_legacy_receipt(folder, path=str(tmp_path / "elsewhere"))),
            (ov.LEGACY_UNVERIFIED, lambda: write_legacy_receipt(folder, version=ov.RECEIPT_VERSION)),
            (ov.LEGACY_BROKEN, lambda: shutil.rmtree(folder / "Lib" / "site-packages" / "torch-2.8.0+cu128.dist-info")),
            (ov.LEGACY_OCCUPIED, lambda: (folder / "pyvenv.cfg").unlink())):
        change()
        assessment = ov.assess_legacy()
        assert assessment.state == expected, (expected, assessment)
        assert assessment.retirable is (expected != ov.LEGACY_OCCUPIED)
        # whatever the sibling is, OmniVoice is not installed until the new engine is
        assert ov.assess_engine().state == ov.ENGINE_ABSENT and ov.environment_status()[0] is False
        assert ov.venv_dir() == ov.engine_venv_dir()


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is the Windows link that needs no privilege")
def test_a_linked_sibling_is_never_read_into_moved_or_mentioned(omni, tmp_path):
    import _winapi

    elsewhere = tmp_path / "somebody-elses"
    make_env(elsewhere, omni.base)
    before = omni.tree(elsewhere)
    _winapi.CreateJunction(str(elsewhere), str(ov.legacy_venv_dir()))
    assert ov.assess_legacy().state == ov.LEGACY_LINK and not ov.assess_legacy().retirable
    assert ov.assess_engine().reason == ov.NOT_INSTALLED_MESSAGE  # an ordinary fresh install, and no word about it
    code, result = omni.install()
    assert result["state"] == proto.SUCCEEDED, result
    assert venv_layout.is_link(ov.legacy_venv_dir()) and omni.tree(elsewhere) == before and retired(omni) == []


def test_a_healthy_sibling_is_built_again_in_its_new_place_and_then_retired_whole(omni):
    """B. The migration: the model reused, the sibling never moved into place, kept whole once the new one works."""
    legacy = make_legacy(omni)
    omni.model()
    legacy_before, receipt_before = omni.tree(legacy), ov.legacy_receipt_path().read_bytes()
    assert ov.assess_engine() == ov.EngineAssessment(ov.ENGINE_ABSENT, ov.LEGACY_MOVE_MESSAGE)
    assert ov.voice_availability("omnivoice-male-1")[0] is False  # the sibling is not a runtime target

    data = omni.plan()
    entry, engine = component(data, OV), unit(data, ENGINE)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.MISSING, proto.SCOPE_INSTALL)
    assert engine["note"] == osu.MOVE_NOTE and engine["download"] == fig(WHEEL_BYTES, proto.MANIFEST)
    assert engine["disk"]["bytes"] > 0, "a build, not an adoption: the sibling is never taken over"
    assert unit(data, MODEL)["state"] == proto.READY
    assert omni.tree(legacy) == legacy_before, "planning changes nothing"

    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED and result["verified"] == [OV], result
    assert omni.fetched() == [], "no model file was downloaded again"
    assert omni.runner.kinds() == ["venv", "sync", "probe"]
    assert venv_layout.same_path(omni.runner.commands[0][2], ov.engine_venv_dir())  # built there, not moved there
    assert ov.assess_engine().state == ov.ENGINE_READY and ov.read_receipt()["origin"] == ov.ORIGIN_INSTALLED

    assert not os.path.lexists(legacy), "the sibling is no longer beside the app's environment"
    (container,) = retired(omni)
    assert omni.tree(container / legacy.name) == legacy_before, "kept whole, byte for byte, never deleted"
    assert (container / ov.legacy_receipt_path().name).read_bytes() == receipt_before, "with its own old receipt"
    assert not ov.legacy_receipt_path().exists() and ov.read_legacy_receipt() == {}
    record = json.loads((container / ovs.RETIRED_RECORD_NAME).read_text(encoding="utf-8"))
    assert record["runnable_here"] is False and record["state_when_moved"] == ov.LEGACY_HEALTHY
    assert venv_layout.same_path(record["original_path"], legacy)
    assert venv_layout.same_path(record["replaced_by"], ov.engine_venv_dir())
    assert "NOT a working environment" in (container / ovs.RETIRED_NOTE_NAME).read_text(encoding="utf-8")
    assert ov.assess_legacy().state == ov.LEGACY_ABSENT

    # Z. and afterwards: a relaunch plans nothing, downloads nothing and runs nothing
    commands = len(omni.runner.commands)
    again = omni.plan()
    assert component(again, OV)["readiness"] == proto.READY and again["acquire_units"] == []
    assert unit(again, ENGINE)["note"] == "" and omni.fetched() == [] and len(omni.runner.commands) == commands


def test_the_retired_copy_is_never_judged_an_environment_where_it_is_kept(omni):
    """A moved Windows environment is not immediately executable, and nothing here treats it as one."""
    legacy = make_legacy(omni)
    omni.model()
    omni.install()
    (container,) = retired(omni)
    kept = container / legacy.name
    assert "moved" in ov.structure_problem(kept)  # its pyvenv.cfg still names the place it was created at
    assessment = venv_layout.assess_child(kept, final_path=ov.engine_venv_dir(), root=omni.root)
    assert assessment.state == venv_layout.UNVERIFIED and "never used" in assessment.reason
    assert not venv_layout.is_within(ov.engine_venv_dir(), kept) and not venv_layout.is_within(kept, ov.venv_python())


def test_an_interrupted_migration_leaves_the_sibling_untouched_and_the_retry_finishes_it(omni):
    """C. Cancelled while uv installs: the sibling and its receipt are byte-identical; the retry completes it."""
    legacy = make_legacy(omni)
    omni.model()
    legacy_before, receipt_before = omni.tree(legacy), ov.legacy_receipt_path().read_bytes()
    omni.runner.hang = "sync"
    cancel = threading.Event()
    shown = omni.plan()
    timer = threading.Timer(0.3, cancel.set)
    timer.start()
    report = omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: None,
                                     cancel_check=cancel.is_set)
    timer.cancel()
    assert not report.completed and report.detail == "cancelled"
    assert omni.tree(legacy) == legacy_before and ov.legacy_receipt_path().read_bytes() == receipt_before
    assert ov.assess_legacy().state == ov.LEGACY_HEALTHY and retired(omni) == []
    assert ov.read_receipt()["stage"] == ov.STAGE_CREATED and ov.assess_engine().state == ov.ENGINE_INCOMPLETE
    assert ov.assess_engine().reason == ov.INCOMPLETE_MESSAGE + ov.LEGACY_NOT_USED_NOTE

    data = omni.plan()
    entry = component(data, OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)
    assert unit(data, ENGINE)["note"] == osu.UNFINISHED_NOTE + osu.LEGACY_KEPT_NOTE
    omni.runner.hang = None
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED, result
    assert omni.fetched() == [] and ov.assess_engine().state == ov.ENGINE_READY
    (container,) = retired(omni)
    assert omni.tree(container / legacy.name) == legacy_before and not os.path.lexists(legacy)


@pytest.mark.parametrize("failure", ["sync", "proof", "proof cancelled"])
def test_a_failed_migration_keeps_the_sibling_and_never_claims_readiness(omni, failure):
    """C. Whatever stops the new engine short of its proof, the earlier one is still exactly where it was."""
    legacy = make_legacy(omni)
    omni.model()
    legacy_before, receipt_before = omni.tree(legacy), ov.legacy_receipt_path().read_bytes()
    cancel = threading.Event()
    if failure == "sync":
        omni.runner.fail_sync = True
    elif failure == "proof":
        omni.runner.probe_failure = ("gpu", "PyTorch reports no usable CUDA GPU")
    else:
        omni.runner.hang = "probe"
        threading.Timer(0.3, cancel.set).start()
    shown = omni.plan()
    report = omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: None,
                                     cancel_check=cancel.is_set)
    assert not report.completed
    assert omni.tree(legacy) == legacy_before and ov.legacy_receipt_path().read_bytes() == receipt_before
    assert retired(omni) == [] and ov.assess_legacy().state == ov.LEGACY_HEALTHY
    assert ov.environment_status()[0] is False and ov.read_receipt().get("stage") != ov.STAGE_INSTALLED
    assert ov.voice_availability("omnivoice-male-1")[0] is False

    omni.runner.fail_sync, omni.runner.probe_failure, omni.runner.hang = False, None, None
    code, result = omni.install()  # the safe retry, under a fresh plan and consent
    assert result["state"] == proto.SUCCEEDED, result
    assert omni.fetched() == [] and ov.assess_engine().state == ov.ENGINE_READY and len(retired(omni)) == 1


def test_a_sibling_that_cannot_be_moved_stays_whole_and_unused_and_the_new_engine_still_stands(omni, monkeypatch):
    legacy = make_legacy(omni)
    omni.model()
    legacy_before = omni.tree(legacy)
    real_rename = os.rename

    def refuse(source, target, *args, **kwargs):
        if Path(source).name == venv_layout.LEGACY_OMNIVOICE:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real_rename(source, target, *args, **kwargs)

    monkeypatch.setattr(ovs.os, "rename", refuse)
    said: list[str] = []
    shown = omni.plan()
    report = omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: said.append(str(p.get("message"))),
                                     cancel_check=lambda: False)
    assert report.completed, report.detail  # the engine is proved and recorded; the leftover is said, not hidden
    assert any("could not be moved aside" in line and "nothing was deleted" in line for line in said)
    assert omni.tree(legacy) == legacy_before and retired(omni) == []
    assert not any(ov.set_aside_root().iterdir()), "no empty set-aside folder is left behind"
    assert ov.assess_engine().state == ov.ENGINE_READY and ov.venv_dir() == ov.engine_venv_dir()
    assert unit(omni.plan(), ENGINE)["note"] == ov.LEGACY_LEFTOVER_NOTE

    monkeypatch.setattr(ovs.os, "rename", real_rename)
    with ovs.InstallLock():
        container = ovs.retire_legacy()  # the next install or repair retires it
    assert omni.tree(container / legacy.name) == legacy_before and unit(omni.plan(), ENGINE)["note"] == ""


def test_the_sibling_is_never_retired_before_the_new_engine_is_proved(omni):
    legacy = make_legacy(omni)
    before = omni.tree(legacy)
    for state in ("absent", "unchecked", "unfinished"):
        if state == "unchecked":
            omni.env()
        elif state == "unfinished":
            omni.receipt(ov.STAGE_CREATING)
        with pytest.raises(ovs.OmniVoiceSetupError, match="not proved yet"):
            ovs.retire_legacy()
        assert omni.tree(legacy) == before and retired(omni) == [], state
    assert ov.legacy_receipt_path().is_file()


def test_both_present_a_proved_engine_is_used_and_the_leftover_sibling_is_said_never_chosen(omni):
    """D. Two installations are never ambiguous: only the engine's own place can be ready, and only by its receipt."""
    legacy = make_legacy(omni)
    omni.env()
    omni.model()
    omni.receipt()
    before = omni.tree(legacy)
    assert ov.assess_engine() == ov.EngineAssessment(ov.ENGINE_READY, "ok")
    assert ov.venv_dir() == ov.engine_venv_dir() and ov.voice_availability("omnivoice-male-1") == (True, "ok")
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.READY and data["acquire_units"] == []
    assert unit(data, ENGINE)["note"] == ov.LEGACY_LEFTOVER_NOTE
    assert omni.tree(legacy) == before and retired(omni) == [], "a plan moves nothing"


def test_both_present_an_unproved_engine_is_adopted_by_proof_and_only_then_is_the_sibling_retired(omni):
    """D. The new engine is complete but unrecorded (its proof was interrupted); the sibling was the proved one."""
    legacy = make_legacy(omni)
    engine = omni.env()
    omni.model()
    engine_before, legacy_before = omni.tree(engine), omni.tree(legacy)
    assert engine_before, "the engine is really there"
    assert ov.assess_engine().state == ov.ENGINE_UNCHECKED
    assert ov.assess_engine().reason == ov.UNCHECKED_MESSAGE + ov.LEGACY_NOT_USED_NOTE
    assert ov.environment_status()[0] is False, "the sibling's proof never stands in for the new engine's"
    data = omni.plan()
    assert unit(data, ENGINE)["note"] == osu.ADOPT_NOTE + osu.LEGACY_KEPT_NOTE
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED and omni.runner.kinds() == ["probe"] and omni.fetched() == []
    assert ov.read_receipt()["origin"] == ov.ORIGIN_ADOPTED
    changed = {k for k in set(engine_before) | set(omni.tree(engine)) if engine_before.get(k) != omni.tree(engine).get(k)}
    assert changed <= {engine_env.RECEIPT_NAME}, "only the environment's own receipt is added to it"
    (container,) = retired(omni)
    assert omni.tree(container / legacy.name) == legacy_before


def test_a_broken_engine_is_never_preferred_over_or_hidden_behind_a_healthy_sibling(omni):
    """E. The engine's place holds something broken that this app did not build: it is said, the healthy sibling is
    named, neither is used; the repair keeps both, whole."""
    legacy = make_legacy(omni)
    omni.model()
    omni.env(pins=PINS[:2])  # a package is missing: not the pinned engine
    broken_before, legacy_before = omni.tree(ov.engine_venv_dir()), omni.tree(legacy)
    assessment = ov.assess_engine()
    assert assessment.state == ov.ENGINE_BROKEN and "1 missing" in assessment.reason
    assert assessment.reason.endswith(ov.LEGACY_NOT_USED_NOTE)
    assert ov.assess_legacy().state == ov.LEGACY_HEALTHY and ov.environment_status()[0] is False
    assert ov.voice_availability("omnivoice-male-1")[0] is False

    data = omni.plan()
    entry = component(data, OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED, result
    assert omni.fetched() == [] and ov.assess_engine().state == ov.ENGINE_READY
    kept = sorted(p.name for p in ov.set_aside_root().iterdir())
    assert len(kept) == 2, kept  # the broken one and the retired sibling: both kept, neither deleted
    broken = next(p for p in ov.set_aside_root().iterdir() if not p.name.startswith(ovs.RETIRED_PREFIX))
    (container,) = retired(omni)
    assert omni.tree(broken) == broken_before and omni.tree(container / legacy.name) == legacy_before


def test_an_earlier_nested_engine_keeps_working_until_a_new_one_is_proved_and_is_then_retired_whole(omni):
    """v0.8.2 Phase 5B. A v0.8.1 engine in ``.venv/engines/omnivoice`` is the one in use, untouched, until a repair
    builds and proves the new engine; only then is it moved whole to set-aside, with its own receipt and a note."""
    nested = omni.nested()
    omni.model()
    before, receipt_before = omni.tree(nested), ov.nested_receipt_path().read_bytes()
    assert ov.venv_dir() == nested and ov.assess_engine() == ov.EngineAssessment(ov.ENGINE_READY, "ok")
    assert ov.voice_availability("omnivoice-male-1") == (True, "ok")
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.READY and data["acquire_units"] == [], "nothing forces a move"

    # the conversion finds a damaged library in it: the v0.8.1 receipt records that, and a repair is offered
    assert ov.reject_ready_engine("ImportError: cannot import name 'OmniVoice'")
    assert ov.read_nested_receipt()["stage"] == ov.STAGE_REJECTED and ov.venv_dir() == nested
    receipt_rejected = ov.nested_receipt_path().read_bytes()
    data = omni.plan()
    entry = component(data, OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)
    assert unit(data, ENGINE)["note"].endswith(osu.NESTED_REPAIR_NOTE)
    omni.runner.hang = "sync"  # an interrupted repair changes nothing of the engine in use
    cancel = threading.Event()
    timer = threading.Timer(0.3, cancel.set)
    timer.start()
    report = omni.acquirer().acquire(data, osu.consent_for(data), progress=lambda p: None, cancel_check=cancel.is_set)
    timer.cancel()
    assert not report.completed and omni.tree(nested) == before and ov.venv_dir() == nested
    assert ov.nested_receipt_path().read_bytes() == receipt_rejected
    omni.runner.hang = None
    said: list[str] = []
    data = omni.plan()
    report = omni.acquirer().acquire(data, osu.consent_for(data), progress=lambda p: said.append(str(p.get("message"))),
                                     cancel_check=lambda: False)
    assert report.completed, report.detail
    assert ov.venv_dir() == ov.engine_venv_dir() and ov.assess_engine().state == ov.ENGINE_READY
    assert not os.path.lexists(nested) and venv_layout.held_entries(ov.parent_venv_dir()) == ()
    (holder,) = [p for p in ov.set_aside_root().iterdir() if p.name.startswith("nested-omnivoice-")]
    assert omni.tree(holder / "omnivoice") == before, "moved whole, byte for byte, never deleted"
    assert (holder / ov.nested_receipt_path().name).read_bytes() == receipt_rejected, "its receipt went with it"
    assert "no longer uses it" in (holder / "RETIRED-READ-ME.txt").read_text(encoding="utf-8")
    assert any("moved, unchanged" in line for line in said)
    assert omni.fetched() == [], "the model was reused"
    assert receipt_before != receipt_rejected


def test_a_new_engine_left_half_built_beside_a_working_nested_one_never_stops_the_voices(omni):
    """An install of the new engine killed half-way leaves the earlier engine in use and ready; the plan offers to
    finish the new one, which then takes over and retires the earlier one."""
    nested = omni.nested()
    omni.model()
    before = omni.tree(nested)
    omni.runner.hang = "sync"
    cancel = threading.Event()
    timer = threading.Timer(0.3, cancel.set)
    timer.start()
    with ovs.InstallLock(), pytest.raises(su.SetupCancelled):
        ovs.build_engine(runner=omni.runner, progress=lambda p: None, cancel_check=cancel.is_set)
    timer.cancel()
    assert ov.read_receipt()["stage"] == ov.STAGE_CREATED and omni.tree(nested) == before
    assert ov.venv_dir() == nested and ov.environment_status() == (True, "ok"), "the voices keep working"
    assert ov.assess_install().state == ov.ENGINE_INCOMPLETE
    data = omni.plan()
    assert (component(data, OV)["readiness"], unit(data, ENGINE)["note"]) == (
        proto.DAMAGED, osu.UNFINISHED_NOTE + osu.NESTED_IN_USE_NOTE)
    omni.runner.hang = None
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED, result
    assert ov.venv_dir() == ov.engine_venv_dir() and not os.path.lexists(nested)
    assert "venv" not in omni.runner.kinds()[1:], "synced again in place"


def test_a_nested_engine_that_cannot_be_moved_aside_stays_whole_and_unused_and_is_said(omni, monkeypatch):
    from shared import engine_env as shared_engine_env

    nested = omni.nested(receipt=False)  # never proved by v0.8.1: not used, so a repair builds the new engine
    omni.model()
    before = omni.tree(nested)
    assert ov.assess_engine().reason == ov.NESTED_UNPROVED_MESSAGE
    real_replace = os.replace

    def refuse(source, target, *args, **kwargs):
        if venv_layout.same_path(source, nested):
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real_replace(source, target, *args, **kwargs)

    monkeypatch.setattr(shared_engine_env.os, "replace", refuse)
    said: list[str] = []
    data = omni.plan()
    report = omni.acquirer().acquire(data, osu.consent_for(data), progress=lambda p: said.append(str(p.get("message"))),
                                     cancel_check=lambda: False)
    assert report.completed, report.detail
    assert omni.tree(nested) == before and ov.venv_dir() == ov.engine_venv_dir()
    assert any("could not be moved aside now" in line for line in said), said
    assert not ov.set_aside_root().exists() or not any(ov.set_aside_root().iterdir()), "no empty folder left"
    assert unit(omni.plan(), ENGINE)["note"] == ov.NESTED_LEFTOVER_NOTE


# =========================================================================== #
# 3. No false readiness
# =========================================================================== #
def test_a_copied_stale_or_foreign_receipt_never_vouches_for_the_engine(omni, tmp_path):
    """F. A receipt is for one folder, one file, one version and one lock; anything else is no receipt."""
    omni.env()
    omni.model()
    good = omni.receipt()
    assert ov.assess_engine().state == ov.ENGINE_READY

    def rewrite(**changes) -> None:
        ov.receipt_path().write_text(json.dumps({**good, **changes}), encoding="utf-8")

    for label, changes in (("another copy's path", {"path": str(tmp_path / "other-app" / ".venv-engines" / "omnivoice")}),
                           ("the nested path", {"path": str(ov.nested_venv_dir())}),
                           ("the nested version", {"version": ov.NESTED_RECEIPT_VERSION}),
                           ("the sibling's version", {"version": ov.LEGACY_RECEIPT_VERSION}),
                           ("another schema", {"schema": "something-else"}),
                           ("another lock", {"lock": {**good["lock"], "uv_lock_sha256": "0" * 64}}),
                           ("no proof", {"probe_ok": False})):
        rewrite(**changes)
        assert ov.assess_engine().state == ov.ENGINE_UNCHECKED, label
        assert ov.environment_status()[0] is False, label
    rewrite()
    assert ov.assess_engine().state == ov.ENGINE_READY
    (ov.engine_venv_dir() / engine_env.RECEIPT_NAME).unlink()  # the environment's own receipt is part of it
    assert ov.assess_engine().state == ov.ENGINE_BROKEN and "installation receipt" in ov.assess_engine().reason
    omni.receipt()

    # another place's receipt copied over this one, or left in its own file, proves nothing here
    make_legacy(omni)
    ov.receipt_path().write_bytes(ov.legacy_receipt_path().read_bytes())
    assert ov.read_receipt() == {} and ov.assess_engine().state == ov.ENGINE_UNCHECKED
    ov.nested_receipt_path().write_text(json.dumps({**good, "version": ov.NESTED_RECEIPT_VERSION,
                                                    "path": str(ov.nested_venv_dir())}), encoding="utf-8")
    assert ov.read_receipt() == {} and ov.assess_engine().state == ov.ENGINE_UNCHECKED
    # and this engine's receipt copied into the sibling's file does not make the sibling "proved"
    ov.legacy_receipt_path().write_text(json.dumps(good), encoding="utf-8")
    assert ov.read_legacy_receipt() == {} and ov.assess_legacy().state == ov.LEGACY_UNVERIFIED


@pytest.mark.parametrize("damage, words", [
    ("no pyvenv.cfg", "no readable pyvenv.cfg"),
    ("not isolated", "not isolated"),
    ("not uv", "not built by uv"),
    ("another python", "not on this copy's managed Python"),
    ("no interpreter", "its interpreter is missing"),
    ("managed python gone", "own Python is missing"),
    ("another build", "not the pinned build"),
])
def test_an_environment_that_is_not_this_copy_s_own_uv_engine_is_broken_whatever_its_receipt_says(
        omni, tmp_path, damage, words):
    """G / U. The receipt stays exactly as it was; the folder (or the Python under it) no longer is what it vouched
    for."""
    from shared import uv_runner

    engine = omni.env()
    omni.model()
    omni.receipt()
    assert ov.assess_engine().state == ov.ENGINE_READY
    config = engine / "pyvenv.cfg"
    text = config.read_text(encoding="utf-8")
    if damage == "no pyvenv.cfg":
        config.unlink()
    elif damage == "not isolated":
        config.write_text(text.replace("include-system-site-packages = false", "include-system-site-packages = true"),
                          encoding="utf-8")
    elif damage == "not uv":
        config.write_text("\n".join(line for line in text.splitlines() if not line.startswith("uv =")), encoding="utf-8")
    elif damage == "another python":
        config.write_text(text.replace(str(uv_runner.managed_venv_home(omni.root, "win32")), str(tmp_path / "py")),
                          encoding="utf-8")
    elif damage == "no interpreter":
        venv_layout.interpreter(engine).unlink()
    elif damage == "managed python gone":
        uv_runner.managed_python(omni.root).unlink()
    else:
        (uv_runner.managed_python_home(omni.root, "win32") / "BUILD").write_text("19990101", encoding="ascii")
    assessment = ov.assess_engine()
    assert assessment.state == ov.ENGINE_BROKEN and words in assessment.reason, assessment
    assert ov.environment_status()[0] is False and ov.voice_availability("omnivoice-male-1")[0] is False
    entry = component(omni.plan(), OV)
    assert (entry["readiness"], entry["consent_scope"]) in (
        (proto.DAMAGED, proto.SCOPE_REPAIR), (proto.UNSUPPORTED, None))


def test_a_wrong_package_version_is_broken_and_a_failed_import_proof_is_recorded_as_rejected(omni):
    """V. Neither a listing that is not the pinned set nor an engine whose packages do not import is ever ready."""
    omni.env(pins=(("omnivoice", "0.2.1"), ("torch", "2.10.0"), ("huggingface-hub", "1.7.2")))
    omni.model()
    omni.receipt()
    assessment = ov.assess_engine()
    assert assessment.state == ov.ENGINE_BROKEN and "1 at another version: torch" in assessment.reason
    ov.clear_receipt()
    shutil.rmtree(ov.engine_venv_dir())
    omni.env()  # the pinned set, unrecorded: the RECORD check and the proof decide
    omni.runner.probe_failure = ("import", "ImportError: DLL load failed while importing _C")
    code, result = omni.install()
    assert result["state"] == proto.FAILED and ov.read_receipt()["stage"] == ov.STAGE_REJECTED
    assert ov.assess_engine().state == ov.ENGINE_BROKEN and "checked and does not work" in ov.assess_engine().reason
    assert component(omni.plan(), OV)["consent_scope"] == proto.SCOPE_REPAIR


def test_the_model_without_the_environment_and_the_environment_without_the_model_are_each_said_and_fixed_alone(omni):
    """W / X. Each half is judged on its own, and only the missing half is acquired."""
    omni.model()  # W: the model is here and verified, the environment is not
    assert ov.model_status() == (True, "ok") and ov.voice_availability("omnivoice-male-1") == (
        False, ov.NOT_INSTALLED_MESSAGE)
    data = omni.plan()
    assert unit(data, MODEL)["state"] == proto.READY and unit(data, ENGINE)["state"] == proto.MISSING
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED and omni.fetched() == [], "the packages only, through uv"
    assert omni.runner.kinds() == ["venv", "sync", "probe"]
    assert ov.voice_availability("omnivoice-male-1") == (True, "ok")

    shutil.rmtree(ov.model_dir())  # X: the environment is ready, the model is gone
    ok, reason = ov.voice_availability("omnivoice-male-1")
    assert ok is False and "model" in reason and ov.assess_engine().state == ov.ENGINE_READY
    data = omni.plan()
    assert unit(data, ENGINE)["state"] == proto.READY and unit(data, MODEL)["state"] == proto.MISSING
    before, commands = len(omni.hub.requests), len(omni.runner.commands)
    receipt = ov.receipt_path().read_bytes()
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED, result
    assert sorted(r["path"] for r in omni.hub.requests[before:]) == sorted(MODEL_PATHS), "the model only"
    assert omni.runner.kinds()[commands:] == ["probe"], "the engine is proved again, never rebuilt"
    assert ov.receipt_path().read_bytes() == receipt, "and its receipts are not rewritten"

    (ov.model_dir() / "config.json").write_bytes(b'{"model": 2}')  # X: corrupt, same size
    assert ov.voice_availability("omnivoice-male-1")[0] is False
    entry = component(omni.plan(), OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)


def test_deleting_the_app_s_environment_leaves_the_engine_ready_and_a_deleted_engine_s_receipt_authorises_nothing(omni):
    """Y. ``.venv`` deleted: the engine beside it is not lost (approved A1). The engine deleted: the receipt that survives
    outside it is just a file, and installing builds it again with the model reused."""
    omni.install()
    install_engine_environment(omni.root)  # Qwen3 beside .venv as well (Phase 5A)
    assert ov.environment_status() == (True, "ok") and rt.environment_status() == (True, "ok")
    shutil.rmtree(ov.parent_venv_dir())
    assert ov.environment_status() == (True, "ok") and rt.environment_status() == (True, "ok")
    assert ov.voice_availability("omnivoice-male-1") == (True, "ok")

    stale = ov.receipt_path().read_bytes()
    shutil.rmtree(ov.engine_venv_dir())
    assert ov.receipt_path().read_bytes() == stale and ov.read_receipt()["stage"] == ov.STAGE_INSTALLED
    assert ov.assess_engine() == ov.EngineAssessment(ov.ENGINE_ABSENT, ov.NOT_INSTALLED_MESSAGE)
    assert ov.environment_status()[0] is False and ov.model_status() == (True, "ok")
    data = omni.plan()
    assert unit(data, ENGINE)["state"] == proto.MISSING and unit(data, MODEL)["state"] == proto.READY
    before = len(omni.hub.requests)
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED, result
    assert len(omni.hub.requests) == before, "the model is not fetched again"
    assert ov.environment_status() == (True, "ok") and ov.read_receipt()["recorded_utc"]


# =========================================================================== #
# 4. Independent repairs
# =========================================================================== #
def test_an_omnivoice_only_repair_changes_nothing_of_qwen3_or_of_the_app_s_own_packages(omni):
    """S. The broken OmniVoice engine is moved aside and built again; ``.venv`` and Qwen3 stay byte-identical."""
    install_qwen3(omni.root)
    install_engine_environment(omni.root)
    parent = ov.parent_venv_dir()
    (parent / "Lib" / "site-packages" / "numpy").mkdir(parents=True)
    (parent / "Lib" / "site-packages" / "numpy" / "__init__.py").write_text("# the app's own package\n")
    omni.env(pins=PINS[:1])  # broken
    omni.model()

    def tree_bytes(folder: Path) -> dict:
        return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}

    before, qwen3 = tree_bytes(parent), tree_bytes(rt.engine_venv_dir())
    qwen3_state = rt.state_path().read_bytes()
    data = omni.plan()
    assert component(data, OV)["consent_scope"] == proto.SCOPE_REPAIR
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED, result
    assert tree_bytes(parent) == before and tree_bytes(rt.engine_venv_dir()) == qwen3
    assert rt.state_path().read_bytes() == qwen3_state
    assert ov.environment_status() == (True, "ok")
    assert all(venv_layout.same_path(env["UV_PROJECT_ENVIRONMENT"], ov.engine_venv_dir())
               for cmd, env in zip(omni.runner.commands, omni.runner.envs) if FakeRunner._uv(cmd, "sync"))


def test_a_qwen3_only_repair_changes_nothing_of_omnivoice(omni, tmp_path_factory, monkeypatch):
    """T. Qwen3's own installer rebuilds ``.venv/engines/qwen3`` and never reaches OmniVoice's engine."""
    omni.install()
    install_qwen3(omni.root)
    nested = ov.engine_venv_dir()
    before, receipt = omni.tree(nested), ov.receipt_path().read_bytes()
    assert before, "the engine is really there"
    runner = Qwen3Runner(tmp_path_factory.mktemp("qwen3-base"))
    monkeypatch.setattr(su, "base_python_candidate", lambda: runner.python)
    su.install_environment(runner=runner, rebuild=True)
    assert rt.environment_status() == (True, "ok")
    assert omni.tree(nested) == before and ov.receipt_path().read_bytes() == receipt
    assert ov.environment_status() == (True, "ok")
    assert not any("omnivoice" in " ".join(command["cmd"]) for command in runner.commands)


# =========================================================================== #
# 5. The parent's repair keeps BOTH held engines (shared.bootstrap, shared.engine_lease)
# =========================================================================== #
def test_a_repair_brings_both_engines_home_to_their_own_paths_byte_identical(env, monkeypatch, windows_engine_policy):
    """H. One rename of ``engines/``: each child is whole, in exactly one place, at the path it was built for.

    Its log line is Windows' words (the policy's seam); a Mac's, naming only OmniVoice, are pinned in
    test_engine_policy.py (macOS P4C)."""
    keepsake = _existing_venv(env)
    qwen3, omnivoice = both_engines(env.venv)
    protected = _protected(env)
    _successful_repair_fakes(monkeypatch)
    log = _Log()

    ok, message = bootstrap.repair_venv(log)

    assert ok is True and "repaired" in message and "kept" not in message
    assert not keepsake.exists() and (env.venv / "candidate.txt").exists()  # the parent really was replaced
    assert engines_of(env.venv) == (qwen3, omnivoice)
    assert venv_layout.held_entries(env.venv) == ("omnivoice", "qwen3")
    assert not bootstrap._venv_aside_path().exists() and not bootstrap._venv_discard_path().exists()
    assert _protected_after(env) == protected, "receipts, models and locks outside .venv are untouched"
    assert "Qwen3 and OmniVoice voice engines are not in use" in log.text


@pytest.mark.parametrize("route", ["first-run setup", "repair"])
def test_a_parent_folder_that_lost_its_interpreter_is_replaced_and_both_engines_come_home(env, monkeypatch, route):
    """U (the parent's own interpreter). ``.venv`` is there, both engines are in it, and ``Scripts\\python.exe`` is
    gone: the launcher takes the first-run route. Setup used to *keep* that folder ("absent"), find no interpreter to
    probe and fail on every start; it is now set aside like any environment that cannot run, a new one is built, and
    the engines are carried into it byte for byte."""
    keepsake = _existing_venv(env)
    bootstrap.venv_python().unlink()  # the interpreter is gone; everything else, engines included, is still there
    qwen3, omnivoice = both_engines(env.venv)
    protected = _protected(env)
    _successful_repair_fakes(monkeypatch)
    assert bootstrap.assess_venv_health().state == bootstrap.VENV_ABSENT and env.venv.is_dir()
    log = _Log()

    if route == "repair":
        ok, message = bootstrap.repair_venv(log)
        assert ok is True, message
    else:  # what run_setup does for the environment itself, owning the transaction
        assert bootstrap._create_validated_venv(["py", "-3.12"], log, headless=True) is True

    assert "Replacing the existing environment" in log.text and "no Python interpreter" in log.text
    assert "Keeping the existing environment" not in log.text
    assert not keepsake.exists() and (env.venv / "candidate.txt").exists() and bootstrap.venv_python().is_file()
    assert engines_of(env.venv) == (qwen3, omnivoice)
    assert venv_layout.held_entries(env.venv) == ("omnivoice", "qwen3")
    assert not bootstrap._venv_aside_path().exists() and not bootstrap._venv_discard_path().exists()
    assert _protected_after(env) == protected


def test_a_parent_folder_without_an_interpreter_that_cannot_be_rebuilt_is_put_back_with_both_engines(env, monkeypatch):
    """The same start, but the new environment cannot be created: the old folder comes back whole, engines included."""
    keepsake = _existing_venv(env)
    bootstrap.venv_python().unlink()
    qwen3, omnivoice = both_engines(env.venv)
    _successful_repair_fakes(monkeypatch)
    _creates_venv(monkeypatch, ok=False)
    log = _Log()
    assert bootstrap._create_validated_venv(["py", "-3.12"], log, headless=True) is False
    assert keepsake.exists() and engines_of(env.venv) == (qwen3, omnivoice)
    assert not bootstrap._venv_aside_path().exists()


@pytest.mark.parametrize("only", [QWEN3, NESTED])
def test_a_repair_with_only_one_engine_installed_keeps_it_and_invents_no_other(env, monkeypatch, only):
    """I."""
    _existing_venv(env)
    engine = plant(env.venv, only, only[1])
    _successful_repair_fakes(monkeypatch)

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is True and _tree(env.venv.joinpath(*only)) == engine
    assert venv_layout.held_entries(env.venv) == (only[1],)


@pytest.mark.parametrize("failure, words", [
    ("the replacement cannot be created", "could not be rebuilt"),
    ("the replacement has no ssl", "could not be rebuilt"),
    ("the packages do not install", "could not be installed"),
    ("the packages do not import", "could not be imported"),
    ("the rebuilt environment cannot launch", "still not usable"),
])
def test_a_failed_repair_restores_the_previous_environment_with_both_engines(env, monkeypatch, failure, words):
    """J / K. No partial candidate is ever left in charge, and no engine is lost with it."""
    keepsake = _existing_venv(env)
    qwen3, omnivoice = both_engines(env.venv)
    protected = _protected(env)
    _successful_repair_fakes(monkeypatch)
    if failure == "the replacement cannot be created":
        _creates_venv(monkeypatch, ok=False)
    elif failure == "the replacement has no ssl":
        monkeypatch.setattr(bootstrap, "probe_capabilities", lambda py: _caps(ssl=False))
    elif failure == "the packages do not install":
        monkeypatch.setattr(bootstrap, "reconcile_requirements", lambda log: (False, bootstrap.RECONCILE_PIP_FAILED))
    elif failure == "the packages do not import":
        monkeypatch.setattr(bootstrap, "reconcile_requirements", lambda log: (False, bootstrap.RECONCILE_IMPORT_FAILED))
    else:
        monkeypatch.setattr(bootstrap, "probe_venv", lambda py: None)  # the candidate's interpreter never starts

    ok, message = bootstrap.repair_venv(_Log())

    assert ok is False and words in message and "put back" in message, message
    assert keepsake.read_text(encoding="utf-8") == "previous" and not (env.venv / "candidate.txt").exists()
    assert engines_of(env.venv) == (qwen3, omnivoice)
    assert not bootstrap._venv_aside_path().exists()
    assert _protected_after(env) == protected


def test_if_the_engines_cannot_be_carried_home_the_old_folder_is_kept_with_both_never_deleted(env, monkeypatch):
    """L. The carry at commit is refused: the app's environment is repaired, and nothing held is deleted or faked."""
    _existing_venv(env)
    qwen3, omnivoice = both_engines(env.venv)
    _successful_repair_fakes(monkeypatch)
    monkeypatch.setattr(bootstrap, "_carry_held_environments", lambda source, destination, log: False)

    ok, message = bootstrap.repair_venv(_Log())

    aside = bootstrap._venv_aside_path()
    assert ok is True and "kept" in message and "nothing was deleted" in message
    assert engines_of(aside) == (qwen3, omnivoice)
    assert venv_layout.held_entries(env.venv) == (), "neither engine is pretended to be installed"
    assert bootstrap.unfinished_replacement() is True  # the next launch hands over to finish it

    monkeypatch.undo()  # the next repair: the carry works again
    monkeypatch.setattr(bootstrap, "VENV_DIR", env.venv)
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    bootstrap.record_import_proof("3.12")
    bootstrap.recover_interrupted_replacement(_Log())
    assert engines_of(env.venv) == (qwen3, omnivoice) and not aside.exists()


def test_a_rollback_never_deletes_a_candidate_holding_an_engine_it_cannot_take_back(env, monkeypatch):
    """L. The restore direction: an engine in the candidate that cannot go back keeps both folders, whole."""
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    (aside / "keepsake.txt").write_text("previous", encoding="utf-8")
    _seed_interpreter(env.venv)
    qwen3, omnivoice = both_engines(env.venv)
    monkeypatch.setattr(bootstrap, "_carry_held_environments", lambda source, destination, log: False)
    log = _Log()

    assert bootstrap._restore_venv(aside, log) is False

    assert "both were kept and nothing was deleted" in log.text
    assert engines_of(env.venv) == (qwen3, omnivoice) and (aside / "keepsake.txt").exists()


def test_interrupted_with_the_parent_set_aside_the_next_launch_puts_it_back_with_both_engines(env):
    """M. The process died between the rename and a working replacement: there is no ``.venv`` at all."""
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    (aside / "keepsake.txt").write_text("previous", encoding="utf-8")
    qwen3, omnivoice = both_engines(aside)
    assert bootstrap.unfinished_replacement() is True and not env.venv.exists()

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "keepsake.txt").read_text(encoding="utf-8") == "previous"
    assert engines_of(env.venv) == (qwen3, omnivoice) and not aside.exists()
    assert bootstrap.unfinished_replacement() is False


@pytest.mark.parametrize("proved", [False, True])
def test_interrupted_after_the_candidate_was_created_but_before_commit(env, monkeypatch, proved):
    """N. Without the commit condition the previous environment comes back; with it the candidate receives both."""
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    (aside / "keepsake.txt").write_text("previous", encoding="utf-8")
    qwen3, omnivoice = both_engines(aside)
    _seed_interpreter(env.venv)
    (env.venv / "candidate.txt").write_text("new", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    if proved:
        bootstrap.record_import_proof("3.12")
    assert bootstrap.unfinished_replacement() is True

    bootstrap.recover_interrupted_replacement(_Log())

    assert engines_of(env.venv) == (qwen3, omnivoice) and not aside.exists()
    assert (env.venv / "candidate.txt").exists() is proved
    assert (env.venv / "keepsake.txt").exists() is (not proved)


def test_an_interrupted_rollback_is_finished_on_the_next_launch_without_losing_an_engine(env, monkeypatch):
    """O. The rollback had carried both engines back to the previous environment and removed the candidate's proof,
    and died before the candidate was deleted: both folders exist, the engines are in the one being restored."""
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    (aside / "keepsake.txt").write_text("previous", encoding="utf-8")
    qwen3, omnivoice = both_engines(aside)
    _seed_interpreter(env.venv)
    (env.venv / "candidate.txt").write_text("half deleted", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    assert not bootstrap.import_proof_is_current() and bootstrap.unfinished_replacement() is True

    bootstrap.recover_interrupted_replacement(_Log())

    assert (env.venv / "keepsake.txt").exists() and not (env.venv / "candidate.txt").exists()
    assert engines_of(env.venv) == (qwen3, omnivoice) and not aside.exists()


def test_an_engine_in_each_folder_is_reported_and_neither_is_merged_chosen_or_deleted(env, monkeypatch):
    """R. Qwen3 held by the previous environment, OmniVoice by the candidate: two ``engines`` folders are never merged."""
    aside = bootstrap._venv_aside_path()
    _seed_interpreter(aside)
    qwen3 = plant(aside, QWEN3, "qwen3")
    _seed_interpreter(env.venv)
    omnivoice = plant(env.venv, NESTED, "omnivoice")
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: _probe())
    bootstrap.record_import_proof("3.12")
    log = _Log()

    bootstrap.recover_interrupted_replacement(log)

    assert "both hold separately installed voice engines" in log.text
    assert _tree(aside.joinpath(*QWEN3)) == qwen3 and _tree(env.venv.joinpath(*NESTED)) == omnivoice
    assert bootstrap.unfinished_replacement() is False  # left for a person: never a repair on every launch


def test_an_unknown_entry_under_engines_is_protected_exactly_like_a_known_engine(env, monkeypatch):
    """R. Nothing guesses what is disposable: a stray file and a folder nobody recognises go home with the rest."""
    _existing_venv(env)
    qwen3, omnivoice = both_engines(env.venv)
    (env.venv / "engines" / "somebody-elses" / "data").mkdir(parents=True)
    (env.venv / "engines" / "somebody-elses" / "data" / "x.bin").write_bytes(b"unknown" * 100)
    (env.venv / "engines" / "notes.txt").write_text("a stray file", encoding="utf-8")
    everything = _tree(env.venv / "engines")
    _successful_repair_fakes(monkeypatch)

    ok, _message = bootstrap.repair_venv(_Log())

    assert ok is True and _tree(env.venv / "engines") == everything
    assert venv_layout.held_entries(env.venv) == ("notes.txt", "omnivoice", "qwen3", "somebody-elses")


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is the Windows link that needs no privilege")
def test_a_junction_planted_as_the_omnivoice_engine_is_carried_as_a_link_and_never_followed(env, monkeypatch, tmp_path):
    """R. The carry is one rename of ``engines``; what a link inside it points at is never moved, read or deleted."""
    import _winapi

    _existing_venv(env)
    qwen3 = plant(env.venv, QWEN3, "qwen3")
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "precious").mkdir(parents=True)
    (elsewhere / "precious" / "data.bin").write_bytes(b"not the app's" * 64)
    target_before = _tree(elsewhere)
    _winapi.CreateJunction(str(elsewhere), str(env.venv.joinpath(*NESTED)))
    _successful_repair_fakes(monkeypatch)

    ok, _message = bootstrap.repair_venv(_Log())

    assert ok is True and _tree(env.venv.joinpath(*QWEN3)) == qwen3
    assert venv_layout.is_link(env.venv.joinpath(*NESTED)) and _tree(elsewhere) == target_before
    assert not bootstrap._venv_aside_path().exists()


def test_the_lease_is_qwen3_s_three_locks_then_omnivoice_s_two_all_or_none(tmp_path):
    root = tmp_path / "copy"
    assert el.OMNIVOICE_ORDER == (el.INFERENCE_LOCK, el.ENGINE_LOCK)
    assert el.omnivoice_runtime_dir(root) == root / "files" / "runtime-data" / "omnivoice"
    lease = el.EnvironmentLease(root)
    lease.take()
    assert lease.held and lease.taken == [(el.QWEN3, name) for name in el.ORDER] + [
        (el.OMNIVOICE, name) for name in el.OMNIVOICE_ORDER]
    for folder, names in ((el.runtime_dir(root), el.ORDER), (el.omnivoice_runtime_dir(root), el.OMNIVOICE_ORDER)):
        assert sorted(p.name for p in folder.iterdir()) == sorted(names)
        assert all((folder / name).stat().st_size == 0 for name in names)
        for name in names:  # held: nobody else can take any of them
            other = el.FileLock(folder / name)
            assert other.acquire() is False
    lease.release()
    assert not lease.held and lease.taken == []
    with el.EnvironmentLease(root) as again:  # and all given back
        assert again.held


@pytest.mark.parametrize("lock", el.OMNIVOICE_ORDER)
def test_a_parent_repair_is_refused_while_the_omnivoice_engine_is_in_use_and_nothing_is_changed(env, monkeypatch, lock):
    """P. A real lock held by another process -- a conversion (``inference.lock``) or a worker still running
    (``engine.lock``). Windows would let the folder be renamed under it; the lock is what refuses."""
    keepsake = _existing_venv(env)
    qwen3, omnivoice = both_engines(env.venv)
    _successful_repair_fakes(monkeypatch)
    folder = el.omnivoice_runtime_dir(env.tmp)
    log = _Log()
    with held_elsewhere(folder / lock):
        ok, message = bootstrap.repair_venv(log, headless=True)
        assert ok is False and el.OMNIVOICE_BUSY_MESSAGES[lock] in message and el.NOTHING_CHANGED in message
        assert "The OmniVoice voice engine of this copy is in use" in log.text
        assert keepsake.read_text(encoding="utf-8") == "previous" and not (env.venv / "candidate.txt").exists()
        assert engines_of(env.venv) == (qwen3, omnivoice) and not os.path.lexists(bootstrap._venv_aside_path())
        # everything already taken was given back: Qwen3's three are free again for their own users
        for name in el.ORDER:
            probe = el.FileLock(el.runtime_dir(env.tmp) / name)
            assert probe.acquire() is True
            probe.release()
    deadline = __import__("time").monotonic() + 10
    while True:  # Windows drops a dead process's locks a moment after it exits
        ok, message = bootstrap.repair_venv(_Log(), headless=True)
        if ok or __import__("time").monotonic() > deadline:
            break
    assert ok is True and engines_of(env.venv) == (qwen3, omnivoice), "no stale lock: the repair goes ahead afterwards"


def test_a_setup_and_first_run_recovery_hold_the_same_two_engine_lease(env, monkeypatch):
    folder = el.omnivoice_runtime_dir(env.tmp)
    monkeypatch.setattr(bootstrap, "install_path_problem", lambda: "")
    with held_elsewhere(folder / el.INFERENCE_LOCK):
        ok, message = bootstrap.run_setup(lambda step, text: None, _Log(), headless=True)
    assert ok is False and message.startswith("Setup was not started.")
    assert el.OMNIVOICE_BUSY_MESSAGES[el.INFERENCE_LOCK] in message


def test_an_omnivoice_install_and_a_parent_repair_exclude_each_other_in_both_orders(omni, env, monkeypatch):
    """Q. One ``setup.lock`` for every installer of this copy and for the repair of the app's own environment."""
    monkeypatch.setattr(bootstrap, "VENV_DIR", omni.root / ".venv")
    _successful_repair_fakes(monkeypatch)
    parent_before = omni.tree(omni.root / ".venv")
    with ovs.InstallLock():  # the installer first (it is about to create .venv/engines/omnivoice)
        ok, message = bootstrap.repair_venv(_Log(), headless=True)
        assert ok is False and el.BUSY_MESSAGES[el.SETUP_LOCK] in message
        assert omni.tree(omni.root / ".venv") == parent_before and not os.path.lexists(omni.root / ".venv.replaced")
    lease = el.EnvironmentLease(omni.root)  # the repair first
    lease.take()
    try:
        with pytest.raises(ovs.OmniVoiceSetupError, match="Another install or repair"):
            ovs.InstallLock().acquire()
        code, result = omni.install()
        assert result["state"] == proto.FAILED and not os.path.lexists(ov.engine_venv_dir())
        assert omni.fetched() == [] and omni.runner.commands == []
    finally:
        lease.release()
    with ovs.InstallLock():
        pass  # and nothing is left held


def test_the_cleanup_coordinator_holds_the_same_lease_and_names_the_engine_that_is_busy(tmp_path):
    from shared import cleanup_worker, maintenance

    root = tmp_path / "copy"
    (root / ".venv").mkdir(parents=True)
    notes: list[str] = []
    with held_elsewhere(el.omnivoice_runtime_dir(root) / el.ENGINE_LOCK):
        lease, problem = cleanup_worker.hold_engine_still(root, notes.append)
    assert lease is None and problem == maintenance.engine_in_use_problem(el.OMNIVOICE_BUSY_MESSAGES[el.ENGINE_LOCK])
    assert "OmniVoice" in notes[0]
    lease, problem = cleanup_worker.hold_engine_still(root, notes.append)
    try:
        assert problem is None and isinstance(lease, el.EnvironmentLease) and lease.held
    finally:
        lease.release()


# =========================================================================== #
# 6. The worker's own view of its isolation, in its own place or in the earlier one inside the parent
# =========================================================================== #
def isolation(monkeypatch, tmp_path, *, prefix=None, base=None, path=(), place="engine"):
    """The worker's view of itself in the engine at *place*: ``engine`` (``.venv-engines/omnivoice``, on the managed
    CPython) or ``nested`` (the earlier ``.venv/engines/omnivoice``, inside the app's ``.venv``)."""
    root = tmp_path / "app"
    environment = root.joinpath(*(venv_layout.ENGINE_OMNIVOICE if place == "engine"
                                  else venv_layout.NESTED_OMNIVOICE).split("/"))
    job = {"environment": str(environment),
           "foreign": [str(root / ".venv"), str(root / ".venv" / "engines" / "qwen3"), str(root / ".venv-qwen3"),
                       str(root / ".venv-omnivoice"), str(root / ".venv-engines" / "qwen3")]}
    base_python = root / "files" / "runtime-data" / "python" / "cpython" if place == "engine" else tmp_path / "base"
    monkeypatch.setattr(sys, "prefix", str(prefix or environment))
    monkeypatch.setattr(sys, "base_prefix", str(base or base_python))
    own = [str(root / "scripts" / "tts"), str(base_python / "python312.zip"), str(base_python / "DLLs"),
           str(base_python / "Lib"), str(base_python), str(environment), str(environment / "Lib" / "site-packages")]
    monkeypatch.setattr(sys, "path", own + [str(p) for p in path])
    import site

    monkeypatch.setattr(site, "ENABLE_USER_SITE", False)
    return root, ow.isolation_problems(job)


@pytest.mark.parametrize("place", ["engine", "nested"])
def test_the_engine_s_own_paths_are_its_own_and_an_earlier_nested_one_s_too_although_they_lie_inside_the_parent(
        monkeypatch, tmp_path, place):
    assert isolation(monkeypatch, tmp_path, place=place)[1] == []


@pytest.mark.parametrize("leak, kind", [
    ("the parent's packages", "another environment"), ("the parent's standard library folder", "another environment"),
    ("qwen3's packages", "another environment"), ("qwen3's scripts", "another environment"),
    ("qwen3's own place", "another environment"), ("the earlier nested engine", "another environment"),
    ("the sibling's packages", "another environment"),
    ("another site-packages", "a site-packages outside the OmniVoice environment")])
def test_any_other_environment_on_the_path_is_an_isolation_failure(monkeypatch, tmp_path, leak, kind):
    """Everything of another environment of this copy, a ``site-packages`` or not; and any ``site-packages`` at all
    outside the engine's own."""
    root = tmp_path / "app"
    entry = {"the parent's packages": root / ".venv" / "Lib" / "site-packages",
             "the parent's standard library folder": root / ".venv" / "Lib",
             "qwen3's packages": root / ".venv" / "engines" / "qwen3" / "Lib" / "site-packages",
             "qwen3's scripts": root / ".venv" / "engines" / "qwen3" / "Scripts",
             "qwen3's own place": root / ".venv-engines" / "qwen3" / "Lib" / "site-packages",
             "the earlier nested engine": root / ".venv" / "engines" / "omnivoice" / "Lib" / "site-packages",
             "the sibling's packages": root / ".venv-omnivoice" / "Lib" / "site-packages",
             "another site-packages": tmp_path / "elsewhere" / "Lib" / "site-packages"}[leak]
    _root, problems = isolation(monkeypatch, tmp_path, path=[entry])
    assert len(problems) == 1 and str(entry) in problems[0] and kind in problems[0], problems


def test_an_engine_built_from_the_parent_s_interpreter_or_running_elsewhere_fails_its_isolation(monkeypatch, tmp_path):
    root = tmp_path / "app"
    _root, problems = isolation(monkeypatch, tmp_path, base=root / ".venv")
    assert any("built from another environment's interpreter" in p for p in problems)
    _root, problems = isolation(monkeypatch, tmp_path, prefix=root / ".venv-omnivoice")
    assert "sys.prefix is not the OmniVoice environment" in problems


def test_the_worker_s_search_path_keeps_its_own_folder_and_drops_the_parent_s_and_qwen3_s(omni):
    nested = omni.env()
    parent = ov.parent_venv_dir()
    (parent / "Scripts").mkdir(exist_ok=True)
    install_qwen3(omni.root)
    install_engine_environment(omni.root)  # v0.8.2 Phase 5A: Qwen3's own place beside .venv is dropped too
    system = r"C:\Windows\System32"
    entries = [str(parent / "Scripts"), str(nested / "Scripts"), str(rt.nested_venv_dir() / "Scripts"),
               str(rt.engine_venv_dir() / "Scripts"), system]
    environment = ov.worker_environment({"PATH": os.pathsep.join(entries), "VIRTUAL_ENV": str(parent)})
    kept = environment["PATH"].split(os.pathsep)
    assert kept == [str(nested / "Scripts"), system] and "VIRTUAL_ENV" not in environment


# =========================================================================== #
# 7. Found by the independent review and on the real test copies (2026-11-13)
# =========================================================================== #
def test_a_set_aside_folder_that_is_a_link_keeps_the_sibling_and_never_fails_the_finished_install(omni, tmp_path):
    """The engine is built, proved and recorded before the sibling is touched; a set-aside folder the app refuses to
    use (a junction to another drive) must leave the sibling where it is and the install a success, said plainly."""
    import _winapi

    legacy = make_legacy(omni)
    omni.model()
    before = omni.tree(legacy)
    elsewhere = tmp_path / "another-drive"
    elsewhere.mkdir()
    ov.set_aside_root().parent.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(elsewhere), str(ov.set_aside_root()))
    said: list[str] = []
    shown = omni.plan()
    report = omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: said.append(str(p.get("message"))),
                                     cancel_check=lambda: False)
    assert report.completed, report.detail
    assert ov.assess_engine().state == ov.ENGINE_READY and ov.read_receipt()["stage"] == ov.STAGE_INSTALLED
    assert omni.tree(legacy) == before and ov.legacy_receipt_path().is_file(), "the sibling and its receipt stay put"
    assert list(elsewhere.iterdir()) == [], "nothing is written through the link"
    assert any("was not moved aside" in line and "nothing was deleted" in line for line in said), said
    assert unit(omni.plan(), ENGINE)["note"] == ov.LEGACY_LEFTOVER_NOTE


def test_the_leftover_note_promises_only_what_happens(omni):
    """Nothing moves a leftover sibling while the engine stays ready (no install runs), so the note must not say that
    it will be moved "the next time"; it says the folder is unused and may be removed by hand."""
    note = ov.LEGACY_LEFTOVER_NOTE
    assert "no longer used" in note and "You may move or delete that folder yourself" in note
    assert "the next time" not in note and "is moved to" not in note
    make_legacy(omni)
    omni.env()
    omni.model()
    omni.receipt()
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.READY and data["acquire_units"] == []  # so no acquirer will run


def test_an_install_lock_that_cannot_open_a_later_lock_gives_back_the_ones_it_took(omni, monkeypatch):
    """A lock that RAISES (a lock file that cannot be opened) is not a lock that answers "busy": whatever was already
    taken must be released, or this copy looks busy to every install, repair and cleanup until the worker exits."""
    real = rt.FileLock.acquire

    def acquire(self):
        if self.path == ov.inference_lock_path():
            raise PermissionError(13, "Access is denied")
        return real(self)

    monkeypatch.setattr(rt.FileLock, "acquire", acquire)
    lock = ovs.InstallLock()
    with pytest.raises(PermissionError):
        lock.acquire()
    lock.release()  # a no-op: nothing is recorded as held
    monkeypatch.setattr(rt.FileLock, "acquire", real)
    other = rt.FileLock(rt.setup_lock_path())
    try:
        assert other.acquire(), "setup.lock was left held by the failed acquisition"
    finally:
        other.release()
    with ovs.InstallLock():
        pass
    lease = el.EnvironmentLease(omni.root)
    lease.take()
    lease.release()


def test_which_worker_failures_condemn_the_environment():
    assert ov.failure_needs_rebuild({"stage": "import", "message": "ImportError: cannot import name 'OmniVoice'"})
    assert ov.failure_needs_rebuild({"stage": "import", "message": "ModuleNotFoundError: No module named 'torch._C'"})
    assert ov.failure_needs_rebuild({"stage": "versions", "message": "torch 2.7.0 is installed, not the pinned 2.8.0"})
    # what the real worker sent for a deleted omnivoice/__init__.py during a conversion (test copy M1, 2026-11-13)
    assert ov.failure_needs_rebuild({"stage": "worker", "message": "ImportError: cannot import name 'OmniVoice' from "
                                                                   "'omnivoice' (unknown location)"})
    assert ov.failure_needs_rebuild({"stage": "worker", "message": "ModuleNotFoundError: No module named 'torchaudio'"})
    # v0.8.0 independent review R1: a native library Windows will not load, met by a conversion's startup imports
    assert ov.failure_needs_rebuild({"stage": "import", "winerror": 193, "message": "OSError: [WinError 193] Error "
                                     "loading \"torch\\lib\\torch_cpu.dll\" or one of its dependencies."})
    for terminal in ({"stage": "worker", "message": "RuntimeError: an import of nothing"},
                     {"stage": "worker", "message": "OSError: [WinError 193] outside the imports it says nothing"},
                     {"stage": "memory", "winerror": 1455, "message": "OSError: [WinError 1455] The paging file is "
                                                                       "too small for this operation to complete."},
                     {"stage": "memory", "message": "MemoryError: "},
                     {"stage": "import", "winerror": 4551, "message": "OSError: [WinError 4551] An Application "
                                                                     "Control policy has blocked this file."},
                     {"stage": "worker", "message": "ImportError: DLL load failed: An Application Control policy has "
                                                    "blocked this file."},
                     {"stage": "generate", "message": "ImportError: raised while generating, not while starting"},{"stage": "import", "message": "ImportError: DLL load failed while importing _C: An Application "
                                                     "Control policy has blocked this file."},
                     {"stage": "isolation", "message": "sys.path holds another environment"},
                     {"stage": "load", "message": "CUDA out of memory", "oom": True},
                     {"stage": "load", "message": "PyTorch reports no usable CUDA GPU", "gpu": False},
                     {"stage": "generate", "message": "RuntimeError: kaboom"}, {"stage": "job", "message": "refused"},
                     {"stage": "engine", "message": "busy"}, {"stage": "network", "message": "socket.connect"}, {}):
        assert not ov.failure_needs_rebuild(terminal), terminal


def test_a_ready_engine_that_fails_at_use_is_recorded_broken_and_its_repair_builds_a_fresh_one(omni):
    """S/V. The listing and the receipt cannot see a deleted file inside a package; the conversion that meets it records
    it on the engine it built (which stays the one in use), and the repair builds a fresh one in its place."""
    omni.env()
    omni.model()
    assert ov.reject_ready_engine("ImportError: x") is False, "an engine no receipt calls ready is never rejected"
    assert ov.read_receipt() == {} and ov.assess_engine().state == ov.ENGINE_UNCHECKED
    omni.receipt()
    assert ov.assess_engine().state == ov.ENGINE_READY and ov.voice_availability("omnivoice-male-1") == (True, "ok")

    assert ov.reject_ready_engine("ImportError: cannot import name 'OmniVoice' from 'omnivoice' (unknown location)")
    receipt = ov.read_receipt()
    assert receipt["stage"] == ov.STAGE_INSTALLED and receipt["rejected_at"] == "conversion" and receipt["rejected"]
    assert ov.venv_dir() == ov.engine_venv_dir()
    state = ov.assess_engine()
    assert state.state == ov.ENGINE_BROKEN and "cannot import name 'OmniVoice'" in state.reason
    assert ov.INSTALL_ACTION in state.reason and "to repair it" in state.reason
    ok, why = ov.voice_availability("omnivoice-male-1")
    assert ok is False and why == state.reason and ov.install_would_help()
    assert ov.reject_ready_engine("again") is False and ov.read_receipt() == receipt  # only a READY engine, only once

    data = omni.plan()
    entry = component(data, OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)
    report = omni.acquirer().acquire(data, osu.consent_for(data), progress=lambda p: None, cancel_check=lambda: False)
    assert report.completed, report.detail
    assert ov.assess_engine() == ov.EngineAssessment(ov.ENGINE_READY, "ok") and omni.fetched() == []
    assert omni.runner.kinds() == ["venv", "sync", "probe"], "this app's own engine is removed and built again"
    assert not ov.set_aside_root().exists() and "rejected" not in ov.read_receipt()


def test_a_native_library_the_real_worker_cannot_load_makes_the_ready_engine_broken_and_offers_the_repair(
        omni, tmp_path):
    """v0.8.0 independent review R1. The real worker's terminal (a stand-in stack; nothing loads Torch or touches a
    library) for a damaged PyTorch library is stage ``import``: the ready receipt records the rejection, the engine says
    BROKEN with the library's own words, and Install & Continue offers the repair. Running out of memory, Smart App
    Control and the network guard leave the same ready engine untouched."""
    omni.env()
    omni.model()
    omni.receipt()
    ready = ov.read_receipt()
    assert ov.assess_engine().state == ov.ENGINE_READY and not ov.install_would_help("omnivoice-male-1")

    for number, plan in enumerate((PAGING_1455, SAC_4551, NETWORK_AT_IMPORT)):
        code, events = run_stack_worker(tmp_path / f"excluded-{number}", plan)
        assert code == 2 and not ov.failure_needs_rebuild(events[-1]), events
        assert ov.read_receipt() == ready and ov.assess_engine().state == ov.ENGINE_READY

    code, events = run_stack_worker(tmp_path / "damaged", DLL_193)
    (terminal,) = events
    assert code == 2 and terminal["stage"] == "import" and terminal["message"].startswith("OSError")
    assert ov.failure_needs_rebuild(terminal)
    assert ov.reject_ready_engine(str(terminal["message"]))  # exactly what the conversion does (omnivoice_synth)
    state = ov.assess_engine()
    assert state.state == ov.ENGINE_BROKEN and "torch_cpu.dll" in state.reason and ov.INSTALL_ACTION in state.reason
    assert "torch_cpu.dll" in ov.read_receipt()["rejected"] and ov.install_would_help("omnivoice-male-1")
    entry = component(omni.plan(), OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)


def test_a_ready_engine_whose_recheck_fails_is_recorded_broken_so_a_repair_is_offered(omni):
    """The engine is ready, only the model has to be fetched again, and the proof that follows shows the engine's own
    packages no longer import: that is recorded on the engine in use."""
    omni.env()
    omni.model(record=False)
    omni.receipt()
    assert ov.assess_engine().state == ov.ENGINE_READY
    shown = omni.plan()
    assert shown["acquire_units"] == [MODEL]
    omni.runner.probe_failure = ("import", "ImportError: DLL load failed while importing _C")
    report = omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: None, cancel_check=lambda: False)
    assert not report.completed
    assert ov.read_receipt().get("rejected") and ov.assess_engine().state == ov.ENGINE_BROKEN
    entry = component(omni.plan(), OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)

    omni.receipt()  # ready again: a failure that says nothing about the environment condemns nothing
    ov.model_record_path().unlink()
    omni.runner.probe_failure = ("gpu", "PyTorch reports no usable CUDA GPU")
    shown = omni.plan()
    assert shown["acquire_units"] == [MODEL]
    report = omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: None, cancel_check=lambda: False)
    assert not report.completed
    assert not ov.read_receipt().get("rejected") and ov.assess_engine().state == ov.ENGINE_READY


def test_the_setup_lock_sentence_names_no_engine_and_a_refused_repair_says_what_is_true(env, monkeypatch):
    """``setup.lock`` is held by every optional install of this copy (Kokoro, Chatterbox, Qwen3, OmniVoice): saying
    "Qwen3" while OmniVoice is being installed was false."""
    sentence = el.BUSY_MESSAGES[el.SETUP_LOCK]
    assert "Qwen3" not in sentence and "OmniVoice" not in sentence and "installed or repaired" in sentence
    _existing_venv(env)
    log = _Log()
    with held_elsewhere(el.runtime_dir(env.tmp) / el.SETUP_LOCK):
        ok, message = bootstrap.repair_venv(log, headless=True)
    assert ok is False and sentence in message and el.NOTHING_CHANGED in message
    refusal = "\n".join(line for line in log.lines if "[!!]" in line)
    assert "Voices of this copy are being installed or repaired" in refusal
    assert "Qwen3 voice engine" not in refusal and "OmniVoice voice engine" not in refusal
    log = _Log()
    with held_elsewhere(el.omnivoice_runtime_dir(env.tmp) / el.ENGINE_LOCK):
        ok, message = bootstrap.repair_venv(log, headless=True)
    assert ok is False and any("The OmniVoice voice engine of this copy is in use" in line for line in log.lines)


def test_locks_that_cannot_even_be_checked_refuse_a_repair_with_nothing_changed(env, monkeypatch,
                                                                                 windows_engine_policy):
    """A lock folder that cannot be made is not permission to go on (there are two such folders now).

    Windows' words through the policy's seam; a Mac's, naming only OmniVoice, are pinned in test_engine_policy.py
    (macOS P4C)."""
    _existing_venv(env)
    before = _tree(env.venv)

    def refuse(self):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(el.EnvironmentLease, "take", refuse)
    log = _Log()
    ok, message = bootstrap.repair_venv(log, headless=True)
    assert ok is False and "could not check whether the Qwen3 or OmniVoice voices are in use" in message
    assert "Nothing was changed" in message and _tree(env.venv) == before
    assert not any(p.name.startswith(".venv.") for p in env.tmp.iterdir())
