"""v0.8.0 -- the unified ``.venv`` layout: OmniVoice held inside the app's environment, beside Qwen3.

Owner decision 2026-11-13 (it supersedes the sibling ``.venv-omnivoice`` of the v0.8.0 plan, section 4): one top-level
``.venv`` holding three independent Python environments -- the app's own, ``.venv/engines/qwen3`` and
``.venv/engines/omnivoice``. This module is the deterministic matrix for that decision:

* **the path contract** -- one runtime path, built at its final place from the app's base Python, a receipt bound to
  that path (and to another file and version than the sibling's ever was);
* **the earlier sibling** -- recognised, never used, never adopted, never moved into place: the engine is built again
  at the nested path, proved, recorded, and only then is the sibling retired, whole, to a labelled set-aside folder;
  every failure or interruption before that leaves it exactly where it was;
* **the parent's repair** -- both held engines survive every outcome of replacing the app's own environment (success,
  a failed build, failed packages, a refused carry, an interruption at each step), and a repair is refused while
  either engine is in use or being installed;
* **independent repairs** -- repairing one engine changes nothing of the other, or of the app's own packages;
* **no false readiness** -- a stale, copied or foreign receipt, a moved environment, a changed base Python, a missing
  interpreter, a wrong package or a failed proof never make the engine ready.

Nothing here reaches the internet, runs pip, creates a real environment or loads a model: the installer's world is the
loopback sandbox of ``test_omnivoice_setup`` and the parent's transaction is the disposable one of
``test_venv_recovery``. Every test is refused, at the write itself, any write to the real installation.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from shared import bootstrap
from shared import engine_lease as el
from shared import optional_setup_protocol as proto
from shared import venv_layout
from tts import omnivoice_runtime as ov
from tts import omnivoice_setup as ovs
from tts import omnivoice_worker as ow
from tts import optional_setup as osu
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su
from test_omnivoice_setup import (ENGINE, MODEL, MODEL_FILES, OV, PINS, WHEELS, FakeGuard, FakeRunner,  # noqa: F401
                                  Omni, make_env, omni)
from test_optional_tts_setup import (component, probes_are_explicit, sandbox, tiny_assets, tripwire, unit,  # noqa: F401
                                     world)
from test_qwen3_runtime import install_environment as install_qwen3
from test_qwen3_setup import FakeRunner as Qwen3Runner
from test_venv_recovery import (_Log, _caps, _creates_venv, _existing_venv, _probe, _protected,  # noqa: F401
                                _protected_after, _reconcile_spy, _seed_interpreter, _successful_repair_fakes, _tree,
                                env)

pytestmark = pytest.mark.usefixtures("production_writes_refused")

SCRIPTS = Path(bootstrap.SCRIPTS_DIR)
NESTED = ("engines", "omnivoice")
QWEN3 = ("engines", "qwen3")
MODEL_PATHS = [f"/k2-fsa/OmniVoice/resolve/{'c' * 40}/{name}" for name in MODEL_FILES]
WHEEL_PATHS = [f"/wheels/{name}" for name in WHEELS]


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


def cache_wheels() -> None:
    """The pinned wheels already on this computer, unrecorded: the installer verifies each by its SHA-256."""
    ov.wheel_cache_dir().mkdir(parents=True, exist_ok=True)
    for name, data in WHEELS.items():
        (ov.wheel_cache_dir() / name).write_bytes(data)


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
def test_the_two_locations_are_exact_and_only_the_nested_one_is_ever_the_runtime_path(omni):
    assert venv_layout.NESTED_OMNIVOICE == ".venv/engines/omnivoice" and venv_layout.LEGACY_OMNIVOICE == ".venv-omnivoice"
    assert venv_layout.NESTED_QWEN3 == ".venv/engines/qwen3"  # Qwen3 stays where it was
    nested = omni.root / ".venv" / "engines" / "omnivoice"
    assert ov.nested_venv_dir() == nested and ov.legacy_venv_dir() == omni.root / ".venv-omnivoice"
    assert ov.parent_venv_dir() == omni.root / ".venv"
    for state in ("nothing", "sibling only", "both"):
        if state == "sibling only":
            make_legacy(omni)
        elif state == "both":
            omni.env()
        assert ov.venv_dir() == nested, state
        assert ov.venv_python() == venv_layout.interpreter(nested), state
    layouts = venv_layout.omnivoice_layouts(omni.root)
    assert layouts.both and layouts.nested == nested and layouts.legacy == ov.legacy_venv_dir()
    assert venv_layout.qwen3_layouts(omni.root).nested is None  # the two engines' layouts are told apart


def test_the_nested_receipt_is_another_file_and_version_than_the_sibling_s_and_both_are_outside_the_parent(omni):
    assert ov.receipt_path() != ov.legacy_receipt_path()
    assert ov.receipt_path().parent == ov.legacy_receipt_path().parent == ov.runtime_dir()
    assert not venv_layout.is_within(ov.parent_venv_dir(), ov.receipt_path())
    assert ov.RECEIPT_VERSION != ov.LEGACY_RECEIPT_VERSION
    omni.env()
    written = omni.receipt()
    assert written["version"] == ov.RECEIPT_VERSION
    assert venv_layout.same_path(written["path"], ov.nested_venv_dir())
    assert not ov.legacy_receipt_path().exists(), "writing the nested receipt never touches the sibling's"


def test_a_fresh_install_builds_the_nested_environment_at_its_final_path_from_the_base_python(omni):
    """A. Nothing here at all: the environment is created where it will run, never beside the app's and moved."""
    code, result = omni.install()
    assert result["state"] == proto.SUCCEEDED and result["verified"] == [OV], result
    nested = ov.nested_venv_dir()
    venv = next(cmd for cmd in omni.runner.commands if cmd[1:4] == ["-I", "-m", "venv"])
    assert venv[0] == str(omni.base) and venv_layout.same_path(venv[4], nested)  # the base Python, the final path
    config = venv_layout.read_pyvenv_cfg(nested)
    assert venv_layout.same_path(config["home"], omni.base.parent) and config["command"].endswith(str(nested))
    assert not venv_layout.is_within(ov.parent_venv_dir(), config["home"])  # independent of the parent's interpreter
    pip = next(cmd for cmd in omni.runner.commands if ovs.OFFLINE_PIP in cmd)
    assert venv_layout.same_path(Path(pip[0]).parents[1], nested)  # pip ran in the nested interpreter, nowhere else
    job = omni.runner.probe_jobs[0]
    assert venv_layout.same_path(job["environment"], nested)
    assert [Path(p) for p in job["foreign"]] == [omni.root / ".venv", omni.root / ".venv" / "engines" / "qwen3",
                                                 omni.root / ".venv-qwen3", omni.root / ".venv-omnivoice"]
    receipt = ov.read_receipt()
    assert receipt["stage"] == ov.STAGE_INSTALLED and venv_layout.same_path(receipt["path"], nested)
    assert receipt["base"] == venv_layout.base_identity(nested)
    assert not os.path.lexists(ov.legacy_venv_dir()) and not ov.legacy_receipt_path().exists()
    assert venv_layout.held_entries(ov.parent_venv_dir()) == ("omnivoice",)
    assert retired(omni) == []  # nothing to retire


@pytest.mark.parametrize("problem, words", [
    ("no parent", "missing or incomplete"),
    ("pending repair", "did not finish"),
    ("pending repair, numbered", "did not finish"),
])
def test_the_engine_is_never_created_inside_a_parent_that_is_missing_or_half_way_through_a_repair(omni, problem, words):
    """An engine built into a half-made replacement could leave two environments each holding an engine."""
    parent = ov.parent_venv_dir()
    if problem == "no parent":
        (parent / "pyvenv.cfg").unlink()
    elif problem == "pending repair":
        (omni.root / ".venv.replaced").mkdir()
    else:
        (omni.root / ".venv.replaced-1763000000").mkdir()
    assert words in ovs.parent_problem()
    code, result = omni.install()
    assert result["state"] == proto.FAILED and words in result["error"]["message"]
    assert not os.path.lexists(ov.nested_venv_dir()) and ov.read_receipt() == {}
    assert omni.runner.commands == [] and omni.fetched() == [], "said before anything is downloaded or run"


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is the Windows link that needs no privilege")
@pytest.mark.parametrize("where", ["engines", "parent"])
def test_a_link_above_the_nested_path_is_unverified_and_nothing_is_built_through_it(omni, tmp_path, where):
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    if where == "engines":
        _winapi.CreateJunction(str(outside), str(ov.parent_venv_dir() / "engines"))
    else:
        os.rename(ov.parent_venv_dir(), omni.root / "real-venv")
        _winapi.CreateJunction(str(omni.root / "real-venv"), str(ov.parent_venv_dir()))
    assert ov.assess_engine().state == ov.ENGINE_UNVERIFIED
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.UNVERIFIED and data["acquire_units"] == []
    with pytest.raises(ovs.OmniVoiceSetupError):
        ovs.build_engine(runner=omni.runner, progress=lambda p: None, cancel_check=lambda: False)
    assert list(outside.iterdir()) == [] and omni.runner.commands == []


def test_a_copy_of_the_app_too_deep_for_the_nested_engine_is_refused_for_this_component_alone(omni, monkeypatch):
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
            (ov.LEGACY_BROKEN, lambda: (folder / "Lib" / "site-packages" / "torch-2.8.0+cu128.dist-info").rmdir()),
            (ov.LEGACY_OCCUPIED, lambda: (folder / "pyvenv.cfg").unlink())):
        change()
        assessment = ov.assess_legacy()
        assert assessment.state == expected, (expected, assessment)
        assert assessment.retirable is (expected != ov.LEGACY_OCCUPIED)
        # whatever the sibling is, OmniVoice is not installed until the nested engine is
        assert ov.assess_engine().state == ov.ENGINE_ABSENT and ov.environment_status()[0] is False
        assert ov.venv_dir() == ov.nested_venv_dir()


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


def test_a_healthy_sibling_is_rebuilt_at_the_nested_path_from_cached_wheels_and_then_retired_whole(omni):
    """B. The migration: nothing downloaded, the sibling never moved into place, kept whole once the new one works."""
    legacy = make_legacy(omni)
    omni.model()
    cache_wheels()
    legacy_before, receipt_before = omni.tree(legacy), ov.legacy_receipt_path().read_bytes()
    assert ov.assess_engine() == ov.EngineAssessment(ov.ENGINE_ABSENT, ov.LEGACY_MOVE_MESSAGE)
    assert ov.voice_availability("omnivoice-male-1")[0] is False  # the sibling is not a runtime target

    data = omni.plan()
    entry, engine = component(data, OV), unit(data, ENGINE)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.MISSING, proto.SCOPE_INSTALL)
    assert engine["note"] == osu.MOVE_NOTE and engine["download"]["bytes"] == 0, "the cached wheels are reused"
    assert engine["disk"]["bytes"] > 0, "a build, not an adoption: the sibling is never taken over"
    assert unit(data, MODEL)["state"] == proto.READY and data["totals"]["download"]["bytes"] == 0
    assert omni.tree(legacy) == legacy_before, "planning changes nothing"

    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED and result["verified"] == [OV], result
    assert omni.fetched() == [], "no wheel and no model file was downloaded again"
    assert omni.runner.kinds() == ["venv", "pip", "probe"]
    nested = ov.nested_venv_dir()
    assert venv_layout.same_path(omni.runner.commands[0][4], nested)  # built there, not moved there
    assert ov.assess_engine().state == ov.ENGINE_READY and ov.read_receipt()["origin"] == ov.ORIGIN_INSTALLED
    assert ov.read_receipt()["version"] == ov.RECEIPT_VERSION

    assert not os.path.lexists(legacy), "the sibling is no longer beside the app's environment"
    (container,) = retired(omni)
    assert omni.tree(container / legacy.name) == legacy_before, "kept whole, byte for byte, never deleted"
    assert (container / ov.legacy_receipt_path().name).read_bytes() == receipt_before, "with its own old receipt"
    assert not ov.legacy_receipt_path().exists() and ov.read_legacy_receipt() == {}
    record = json.loads((container / ovs.RETIRED_RECORD_NAME).read_text(encoding="utf-8"))
    assert record["runnable_here"] is False and record["state_when_moved"] == ov.LEGACY_HEALTHY
    assert venv_layout.same_path(record["original_path"], legacy)
    assert venv_layout.same_path(record["replaced_by"], nested)
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
    cache_wheels()
    omni.install()
    (container,) = retired(omni)
    kept = container / legacy.name
    assert "moved" in ov.structure_problem(kept)  # its pyvenv.cfg still names the place it was created at
    assessment = venv_layout.assess_child(kept, final_path=ov.nested_venv_dir(), root=omni.root)
    assert assessment.state == venv_layout.UNVERIFIED and "never used" in assessment.reason
    assert not venv_layout.is_within(ov.nested_venv_dir(), kept) and not venv_layout.is_within(kept, ov.venv_python())


def test_an_interrupted_migration_leaves_the_sibling_untouched_and_the_retry_finishes_it(omni):
    """C. Cancelled while pip runs: the sibling and its receipt are byte-identical, the retry downloads nothing."""
    legacy = make_legacy(omni)
    omni.model()
    cache_wheels()
    legacy_before, receipt_before = omni.tree(legacy), ov.legacy_receipt_path().read_bytes()
    omni.runner.hang = "pip"
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
    assert ov.read_receipt()["stage"] == ov.STAGE_CREATING and ov.assess_engine().state == ov.ENGINE_INCOMPLETE
    assert ov.assess_engine().reason == ov.INCOMPLETE_MESSAGE + ov.LEGACY_NOT_USED_NOTE

    data = omni.plan()
    entry = component(data, OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)
    assert unit(data, ENGINE)["note"] == osu.UNFINISHED_NOTE + osu.LEGACY_KEPT_NOTE
    assert unit(data, ENGINE)["download"]["bytes"] == 0, "the verified wheels were kept"
    omni.runner.hang = None
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED, result
    assert omni.fetched() == [] and ov.assess_engine().state == ov.ENGINE_READY
    (container,) = retired(omni)
    assert omni.tree(container / legacy.name) == legacy_before and not os.path.lexists(legacy)


@pytest.mark.parametrize("failure", ["pip", "proof", "proof cancelled"])
def test_a_failed_migration_keeps_the_sibling_and_never_claims_readiness(omni, failure):
    """C. Whatever stops the new engine short of its proof, the earlier one is still exactly where it was."""
    legacy = make_legacy(omni)
    omni.model()
    cache_wheels()
    legacy_before, receipt_before = omni.tree(legacy), ov.legacy_receipt_path().read_bytes()
    cancel = threading.Event()
    if failure == "pip":
        omni.runner.fail_pip = True
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

    omni.runner.fail_pip, omni.runner.probe_failure, omni.runner.hang = False, None, None
    code, result = omni.install()  # the safe retry, under a fresh plan and consent
    assert result["state"] == proto.SUCCEEDED, result
    assert omni.fetched() == [] and ov.assess_engine().state == ov.ENGINE_READY and len(retired(omni)) == 1


def test_a_sibling_that_cannot_be_moved_stays_whole_and_unused_and_the_new_engine_still_stands(omni, monkeypatch):
    legacy = make_legacy(omni)
    omni.model()
    cache_wheels()
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
    assert ov.assess_engine().state == ov.ENGINE_READY and ov.venv_dir() == ov.nested_venv_dir()
    assert unit(omni.plan(), ENGINE)["note"] == ov.LEGACY_LEFTOVER_NOTE

    monkeypatch.setattr(ovs.os, "rename", real_rename)
    with ovs.InstallLock():
        container = ovs.retire_legacy()  # the next install or repair retires it
    assert omni.tree(container / legacy.name) == legacy_before and unit(omni.plan(), ENGINE)["note"] == ""


def test_the_sibling_is_never_retired_before_the_nested_engine_is_proved(omni):
    legacy = make_legacy(omni)
    before = omni.tree(legacy)
    for state in ("absent", "unchecked", "unfinished"):
        if state == "unchecked":
            omni.env()
        elif state == "unfinished":
            omni.receipt(ov.STAGE_CREATING, base_python=str(omni.base))
        with pytest.raises(ovs.OmniVoiceSetupError, match="not proved yet"):
            ovs.retire_legacy()
        assert omni.tree(legacy) == before and retired(omni) == [], state
    assert ov.legacy_receipt_path().is_file()


def test_both_present_a_proved_nested_engine_is_used_and_the_leftover_sibling_is_said_never_chosen(omni):
    """D. Two installations are never ambiguous: only the nested path can be ready, and only by its own receipt."""
    legacy = make_legacy(omni)
    omni.env()
    omni.model()
    omni.receipt()
    before = omni.tree(legacy)
    assert ov.assess_engine() == ov.EngineAssessment(ov.ENGINE_READY, "ok")
    assert ov.venv_dir() == ov.nested_venv_dir() and ov.voice_availability("omnivoice-male-1") == (True, "ok")
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.READY and data["acquire_units"] == []
    assert unit(data, ENGINE)["note"] == ov.LEGACY_LEFTOVER_NOTE
    assert omni.tree(legacy) == before and retired(omni) == [], "a plan moves nothing"


def test_both_present_an_unproved_nested_engine_is_adopted_by_proof_and_only_then_is_the_sibling_retired(omni):
    """D. The nested engine is complete but unrecorded (its proof was interrupted); the sibling was the proved one."""
    legacy = make_legacy(omni)
    omni.env()
    omni.model()
    nested_before, legacy_before = omni.tree(ov.nested_venv_dir()), omni.tree(legacy)
    assert ov.assess_engine().state == ov.ENGINE_UNCHECKED
    assert ov.assess_engine().reason == ov.UNCHECKED_MESSAGE + ov.LEGACY_NOT_USED_NOTE
    assert ov.environment_status()[0] is False, "the sibling's proof never stands in for the nested engine's"
    data = omni.plan()
    assert unit(data, ENGINE)["note"] == osu.ADOPT_NOTE + osu.LEGACY_KEPT_NOTE
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED and omni.runner.kinds() == ["probe"] and omni.fetched() == []
    assert omni.tree(ov.nested_venv_dir()) == nested_before and ov.read_receipt()["origin"] == ov.ORIGIN_ADOPTED
    (container,) = retired(omni)
    assert omni.tree(container / legacy.name) == legacy_before


def test_a_broken_nested_engine_is_never_preferred_over_or_hidden_behind_a_healthy_sibling(omni):
    """E. The nested path exists but is broken: it is said, the healthy sibling is named, and neither is used."""
    legacy = make_legacy(omni)
    omni.model()
    cache_wheels()
    omni.env(pins=PINS[:2])  # a package is missing: not the pinned engine
    broken_before, legacy_before = omni.tree(ov.nested_venv_dir()), omni.tree(legacy)
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
    assert len(kept) == 2, kept  # the broken nested one and the retired sibling: both kept, neither deleted
    broken = next(p for p in ov.set_aside_root().iterdir() if not p.name.startswith(ovs.RETIRED_PREFIX))
    (container,) = retired(omni)
    assert omni.tree(broken) == broken_before and omni.tree(container / legacy.name) == legacy_before


# =========================================================================== #
# 3. No false readiness
# =========================================================================== #
def test_a_copied_stale_or_foreign_receipt_never_vouches_for_the_nested_engine(omni, tmp_path):
    """F. A receipt is for one folder, one file and one version; anything else is no receipt."""
    omni.env()
    omni.model()
    good = omni.receipt()
    assert ov.assess_engine().state == ov.ENGINE_READY

    def rewrite(**changes) -> None:
        ov.receipt_path().write_text(json.dumps({**good, **changes}), encoding="utf-8")

    for label, changes in (("another copy's path", {"path": str(tmp_path / "other-app" / ".venv" / "engines" / "omnivoice")}),
                           ("the sibling's path", {"path": str(ov.legacy_venv_dir())}),
                           ("the sibling's version", {"version": ov.LEGACY_RECEIPT_VERSION}),
                           ("another schema", {"schema": "something-else"}),
                           ("another package set", {"packages_sha256": "0" * 64}),
                           ("no proof", {"probe_ok": False})):
        rewrite(**changes)
        assert ov.assess_engine().state == ov.ENGINE_UNCHECKED, label
        assert ov.environment_status()[0] is False, label
    rewrite()
    assert ov.assess_engine().state == ov.ENGINE_READY

    # the sibling's own (version 1) receipt copied over the nested one, or left in its own file, proves nothing here
    legacy = make_legacy(omni)
    ov.receipt_path().write_bytes(ov.legacy_receipt_path().read_bytes())
    assert ov.read_receipt() == {} and ov.assess_engine().state == ov.ENGINE_UNCHECKED
    ov.receipt_path().unlink()
    assert ov.read_legacy_receipt() != {} and ov.assess_engine().state == ov.ENGINE_UNCHECKED
    # and a nested receipt copied into the sibling's file does not make the sibling "proved"
    ov.legacy_receipt_path().write_text(json.dumps(good), encoding="utf-8")
    assert ov.read_legacy_receipt() == {} and ov.assess_legacy().state == ov.LEGACY_UNVERIFIED
    assert legacy.is_dir()


@pytest.mark.parametrize("damage, words", [
    ("no pyvenv.cfg", "no readable pyvenv.cfg"),
    ("not isolated", "not isolated"),
    ("moved", "created in another folder and moved"),
    ("built from the parent", "built from the app's own environment"),
    ("another version", "not made with Python 3.12"),
    ("base gone", "the Python it was built from is missing"),
    ("no interpreter", "its Python interpreter is missing"),
])
def test_an_invalid_pyvenv_cfg_or_interpreter_makes_a_recorded_engine_broken(omni, tmp_path, damage, words):
    """G / U. The receipt stays exactly as it was; the folder no longer is what it vouched for."""
    nested = omni.env()
    omni.model()
    omni.receipt()
    assert ov.assess_engine().state == ov.ENGINE_READY
    config = nested / "pyvenv.cfg"
    text = config.read_text(encoding="utf-8")
    if damage == "no pyvenv.cfg":
        config.unlink()
    elif damage == "not isolated":
        config.write_text(text.replace("include-system-site-packages = false", "include-system-site-packages = true"),
                          encoding="utf-8")
    elif damage == "moved":
        config.write_text(text.replace(str(nested), str(tmp_path / "built" / "somewhere-else")), encoding="utf-8")
    elif damage == "built from the parent":
        parent_python = ov.parent_venv_dir() / "Scripts" / "python.exe"
        parent_python.parent.mkdir(parents=True, exist_ok=True)
        parent_python.write_bytes(b"the app's own interpreter")
        config.write_text(text.replace(str(omni.base.parent), str(parent_python.parent))
                          .replace(str(omni.base), str(parent_python)), encoding="utf-8")
    elif damage == "another version":
        config.write_text(text.replace("version = 3.12.10", "version = 3.13.1"), encoding="utf-8")
    elif damage == "base gone":
        omni.base.unlink()
    else:
        venv_layout.interpreter(nested).unlink()
    assessment = ov.assess_engine()
    assert assessment.state == ov.ENGINE_BROKEN and words in assessment.reason, assessment
    assert ov.environment_status()[0] is False and ov.voice_availability("omnivoice-male-1")[0] is False
    entry = component(omni.plan(), OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)


def test_a_base_python_replaced_in_place_is_noticed_and_the_engine_must_be_proved_again(omni):
    """G. ``pyvenv.cfg`` cannot see an interpreter reinstalled into the same folder; the recorded identity can."""
    omni.env()
    omni.model()
    omni.receipt()
    omni.base.write_bytes(b"another build of the base interpreter")
    assert ov.assess_engine().state == ov.ENGINE_UNCHECKED and ov.environment_status()[0] is False
    code, result = omni.install()
    assert result["state"] == proto.SUCCEEDED and omni.runner.kinds() == ["probe"]  # proved again, nothing rebuilt
    assert ov.read_receipt()["base"] == venv_layout.base_identity(ov.nested_venv_dir())


def test_a_wrong_package_version_is_broken_and_a_failed_import_proof_is_recorded_as_rejected(omni):
    """V. Neither a listing that is not the pinned set nor an engine whose packages do not import is ever ready."""
    omni.env(pins=(("omnivoice", "0.2.1"), ("torch", "2.10.0"), ("huggingface-hub", "1.7.2")))
    omni.model()
    omni.receipt()
    assessment = ov.assess_engine()
    assert assessment.state == ov.ENGINE_BROKEN and "1 at another version: torch" in assessment.reason
    ov.clear_receipt()
    omni.env()  # the pinned set again, unrecorded: the proof decides
    omni.runner.probe_failure = ("import", "ImportError: DLL load failed while importing _C")
    code, result = omni.install()
    assert result["state"] == proto.FAILED and ov.read_receipt()["stage"] == ov.STAGE_REJECTED
    assert ov.assess_engine().state == ov.ENGINE_BROKEN and "checked and does not work" in ov.assess_engine().reason
    assert component(omni.plan(), OV)["consent_scope"] == proto.SCOPE_REPAIR


def test_the_model_without_the_environment_and_the_environment_without_the_model_are_each_said_and_fixed_alone(omni):
    """W / X. Each half is judged on its own, and only the missing half is fetched."""
    omni.model()  # W: the model is here and verified, the environment is not
    assert ov.model_status() == (True, "ok") and ov.voice_availability("omnivoice-male-1") == (
        False, ov.NOT_INSTALLED_MESSAGE)
    data = omni.plan()
    assert unit(data, MODEL)["state"] == proto.READY and unit(data, ENGINE)["state"] == proto.MISSING
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED and sorted(omni.fetched()) == sorted(WHEEL_PATHS), "the wheels only"
    assert ov.voice_availability("omnivoice-male-1") == (True, "ok")

    import shutil

    shutil.rmtree(ov.model_dir())  # X: the environment is ready, the model is gone
    ok, reason = ov.voice_availability("omnivoice-male-1")
    assert ok is False and "model" in reason and ov.assess_engine().state == ov.ENGINE_READY
    data = omni.plan()
    assert unit(data, ENGINE)["state"] == proto.READY and unit(data, MODEL)["state"] == proto.MISSING
    before, commands = len(omni.hub.requests), len(omni.runner.commands)
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED, result
    assert sorted(r["path"] for r in omni.hub.requests[before:]) == sorted(MODEL_PATHS), "the model only"
    assert omni.runner.kinds()[commands:] == ["probe"], "the engine is proved again, never rebuilt"

    (ov.model_dir() / "config.json").write_bytes(b'{"model": 2}')  # X: corrupt, same size
    assert ov.voice_availability("omnivoice-male-1")[0] is False
    entry = component(omni.plan(), OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)


def test_with_the_whole_parent_gone_stale_receipts_outside_it_authorise_nothing(omni):
    """Y. ``.venv`` was deleted, and both engines with it: the receipts that survive outside it are just files."""
    omni.install()
    install_qwen3(omni.root)
    assert ov.environment_status() == (True, "ok") and rt.environment_status() == (True, "ok")
    stale_omnivoice, stale_qwen3 = ov.receipt_path().read_bytes(), rt.state_path().read_bytes()
    import shutil

    shutil.rmtree(ov.parent_venv_dir())

    assert ov.receipt_path().read_bytes() == stale_omnivoice and ov.read_receipt()["stage"] == ov.STAGE_INSTALLED
    assert ov.assess_engine() == ov.EngineAssessment(ov.ENGINE_ABSENT, ov.NOT_INSTALLED_MESSAGE)
    assert ov.environment_status()[0] is False and ov.voice_availability("omnivoice-male-1")[0] is False
    assert rt.state_path().read_bytes() == stale_qwen3 and rt.environment_status()[0] is False
    assert ov.model_status() == (True, "ok"), "the model, outside .venv, is still here and still verified"
    data = omni.plan()
    assert unit(data, ENGINE)["state"] == proto.MISSING and unit(data, MODEL)["state"] == proto.READY
    assert "missing or incomplete" in ovs.parent_problem()  # nothing is built until the app's own environment is back
    fetched = len(omni.hub.requests)
    code, result = omni.install(plan=data)
    assert result["state"] == proto.FAILED and not os.path.lexists(ov.nested_venv_dir())
    assert ov.receipt_path().read_bytes() == stale_omnivoice and ov.environment_status()[0] is False
    assert len(omni.hub.requests) == fetched, "nothing is downloaded for a build that cannot happen"

    # Z. the app's own environment is rebuilt (by Setup_and_Run); the engine is then installed again, the model reused
    ov.parent_venv_dir().mkdir()
    (ov.parent_venv_dir() / "pyvenv.cfg").write_text("home = C:/base\ninclude-system-site-packages = false\n",
                                                     encoding="utf-8")
    assert ov.environment_status()[0] is False, "a rebuilt parent does not bring the engine back by itself"
    before = len(omni.hub.requests)
    code, result = omni.install()
    assert result["state"] == proto.SUCCEEDED, result
    assert sorted(r["path"] for r in omni.hub.requests[before:]) == sorted(WHEEL_PATHS), "the model is not fetched again"
    assert ov.read_receipt()["recorded_utc"] and ov.environment_status() == (True, "ok")
    after = len(omni.hub.requests)
    assert component(omni.plan(), OV)["readiness"] == proto.READY and len(omni.hub.requests) == after


# =========================================================================== #
# 4. Independent repairs
# =========================================================================== #
def test_an_omnivoice_only_repair_changes_nothing_of_qwen3_or_of_the_app_s_own_packages(omni):
    """S. The broken OmniVoice engine is moved aside and built again; everything else under ``.venv`` is byte-identical."""
    install_qwen3(omni.root)
    parent = ov.parent_venv_dir()
    (parent / "Lib" / "site-packages" / "numpy").mkdir(parents=True)
    (parent / "Lib" / "site-packages" / "numpy" / "__init__.py").write_text("# the app's own package\n")
    omni.env(pins=PINS[:1])  # broken
    omni.model()

    def everything_else() -> dict:
        nested = ov.nested_venv_dir()
        return {str(p.relative_to(parent)): p.read_bytes() for p in sorted(parent.rglob("*"))
                if p.is_file() and not venv_layout.is_within(nested, p)}

    before, qwen3_state = everything_else(), rt.state_path().read_bytes()
    assert rt.environment_status() == (True, "ok")
    data = omni.plan()
    assert component(data, OV)["consent_scope"] == proto.SCOPE_REPAIR
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED, result
    assert everything_else() == before and rt.state_path().read_bytes() == qwen3_state
    assert rt.environment_status() == (True, "ok") and ov.environment_status() == (True, "ok")
    assert venv_layout.held_entries(parent) == ("omnivoice", "qwen3")
    assert all(venv_layout.is_within(ov.nested_venv_dir(), Path(cmd[4])) or venv_layout.same_path(cmd[4], ov.nested_venv_dir())
               for cmd in omni.runner.commands if cmd[1:4] == ["-I", "-m", "venv"])


def test_a_qwen3_only_repair_changes_nothing_of_omnivoice(omni, tmp_path_factory, monkeypatch):
    """T. Qwen3's own installer rebuilds ``.venv/engines/qwen3`` and never reaches the folder beside it."""
    omni.install()
    install_qwen3(omni.root)
    nested = ov.nested_venv_dir()
    before, receipt = omni.tree(nested), ov.receipt_path().read_bytes()
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
def test_a_repair_brings_both_engines_home_to_their_own_paths_byte_identical(env, monkeypatch):
    """H. One rename of ``engines/``: each child is whole, in exactly one place, at the path it was built for."""
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
        assert result["state"] == proto.FAILED and not os.path.lexists(ov.nested_venv_dir())
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
# 6. The worker's own view of its isolation, now that it lives inside the parent
# =========================================================================== #
def isolation(monkeypatch, tmp_path, *, prefix=None, base=None, path=()):
    root = tmp_path / "app"
    environment = root / ".venv" / "engines" / "omnivoice"
    job = {"environment": str(environment),
           "foreign": [str(root / ".venv"), str(root / ".venv" / "engines" / "qwen3"), str(root / ".venv-qwen3"),
                       str(root / ".venv-omnivoice")]}
    base_python = tmp_path / "base-python"
    monkeypatch.setattr(sys, "prefix", str(prefix or environment))
    monkeypatch.setattr(sys, "base_prefix", str(base or base_python))
    own = [str(root / "scripts" / "tts"), str(base_python / "python312.zip"), str(base_python / "DLLs"),
           str(base_python / "Lib"), str(base_python), str(environment), str(environment / "Lib" / "site-packages")]
    monkeypatch.setattr(sys, "path", own + [str(p) for p in path])
    import site

    monkeypatch.setattr(site, "ENABLE_USER_SITE", False)
    return root, ow.isolation_problems(job)


def test_the_nested_environment_s_own_paths_are_its_own_although_they_lie_inside_the_parent(monkeypatch, tmp_path):
    assert isolation(monkeypatch, tmp_path)[1] == []


@pytest.mark.parametrize("leak, kind", [
    ("the parent's packages", "another environment"), ("the parent's standard library folder", "another environment"),
    ("qwen3's packages", "another environment"), ("qwen3's scripts", "another environment"),
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
    system = r"C:\Windows\System32"
    entries = [str(parent / "Scripts"), str(nested / "Scripts"), str(rt.nested_venv_dir() / "Scripts"), system]
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
    cache_wheels()
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
    for terminal in ({"stage": "worker", "message": "RuntimeError: an import of nothing"},
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


def test_a_ready_engine_that_fails_at_use_is_recorded_broken_and_its_repair_keeps_it_and_builds_a_fresh_one(omni):
    """S/V on the nested engine. The listing and the receipt cannot see a deleted file inside a package; the
    conversion that meets it records it, and the ordinary repair then sets the damaged environment aside whole."""
    nested = omni.env()
    omni.model()
    assert ov.reject_ready_engine("ImportError: x") is False, "an engine no receipt calls ready is never rejected"
    assert ov.read_receipt() == {} and ov.assess_engine().state == ov.ENGINE_UNCHECKED
    omni.receipt()
    assert ov.assess_engine().state == ov.ENGINE_READY and ov.voice_availability("omnivoice-male-1") == (True, "ok")

    assert ov.reject_ready_engine("ImportError: cannot import name 'OmniVoice' from 'omnivoice' (unknown location)")
    receipt = ov.read_receipt()
    assert receipt["stage"] == ov.STAGE_REJECTED and receipt["rejected_at"] == "conversion"
    state = ov.assess_engine()
    assert state.state == ov.ENGINE_BROKEN and "cannot import name 'OmniVoice'" in state.reason
    assert ov.INSTALL_ACTION in state.reason and "to repair it" in state.reason
    ok, why = ov.voice_availability("omnivoice-male-1")
    assert ok is False and why == state.reason and ov.install_would_help()
    assert ov.reject_ready_engine("again") is False and ov.read_receipt() == receipt  # only a READY engine, only once

    data = omni.plan()
    entry = component(data, OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)
    cache_wheels()
    damaged = omni.tree(nested)
    shown = omni.plan()
    report = omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: None, cancel_check=lambda: False)
    assert report.completed, report.detail
    assert ov.assess_engine() == ov.EngineAssessment(ov.ENGINE_READY, "ok") and omni.fetched() == []
    kept = [p for p in ov.set_aside_root().iterdir() if not p.name.startswith(ovs.RETIRED_PREFIX)]
    assert len(kept) == 1 and omni.tree(kept[0]) == damaged, "the damaged environment is kept whole, never deleted"


def test_a_ready_engine_whose_recheck_fails_is_recorded_broken_so_a_repair_is_offered(omni):
    """The engine is ready, only the model has to be fetched again, and the proof that follows shows the engine's own
    packages no longer import: that is recorded (it used to be recorded only for a never-checked environment)."""
    omni.env()
    omni.model(record=False)
    omni.receipt()
    assert ov.assess_engine().state == ov.ENGINE_READY
    shown = omni.plan()
    assert shown["acquire_units"] == [MODEL]
    omni.runner.probe_failure = ("import", "ImportError: DLL load failed while importing _C")
    report = omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: None, cancel_check=lambda: False)
    assert not report.completed
    assert ov.read_receipt()["stage"] == ov.STAGE_REJECTED and ov.assess_engine().state == ov.ENGINE_BROKEN
    entry = component(omni.plan(), OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)

    omni.receipt()  # ready again: a failure that says nothing about the environment condemns nothing
    ov.model_record_path().unlink()
    omni.runner.probe_failure = ("gpu", "PyTorch reports no usable CUDA GPU")
    shown = omni.plan()
    assert shown["acquire_units"] == [MODEL]
    report = omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: None, cancel_check=lambda: False)
    assert not report.completed
    assert ov.read_receipt()["stage"] == ov.STAGE_INSTALLED and ov.assess_engine().state == ov.ENGINE_READY


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


def test_locks_that_cannot_even_be_checked_refuse_a_repair_with_nothing_changed(env, monkeypatch):
    """A lock folder that cannot be made is not permission to go on (there are two such folders now)."""
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


def test_an_engine_built_through_another_spelling_of_the_same_base_python_is_accepted(tmp_path):
    """``venv`` records the base interpreter by its real path; a copy reached through a mapped or substituted drive
    names the same file by another spelling. Same file: accepted. Another file: refused."""
    base = tmp_path / "python" / "python.exe"
    base.parent.mkdir()
    base.write_bytes(b"base interpreter")
    other = tmp_path / "other" / "python.exe"
    other.parent.mkdir()
    other.write_bytes(b"base interpreter")
    link = tmp_path / "drive"
    import _winapi

    _winapi.CreateJunction(str(base.parent), str(link))
    assert ovs._same_file(base, base) and ovs._same_file(str(base).upper(), base)
    assert ovs._same_file(link / "python.exe", base), "one file, two spellings"
    assert not ovs._same_file(other, base) and not ovs._same_file(tmp_path / "missing.exe", base)
