"""v0.7.0 P05B Stage 2 — consented acquisition, pinned sources, first-use containment, health and test isolation.

Nothing here reaches the internet, runs pip or loads a model: Hugging Face is a loopback server holding tiny stand-ins
of the pinned files (``test_qwen3_setup.Hub``), pip is a fake that records its command line, the Qwen3 installer's
commands are ``test_qwen3_setup.FakeRunner``, and the upstream engine libraries are fake modules. Every test is refused,
at the write itself, any write to the real installation (``production_writes_refused``).
"""

from __future__ import annotations

import ast
import dataclasses
import errno
import hashlib
import json
import os
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import write_tripwire
from shared import optional_setup_protocol as proto
from tts import model_assets as assets
from tts import optional_setup as osu
from tts import optional_setup_acquire as osa
from tts import optional_setup_health as osh
from tts import optional_setup_lifecycle as osl
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su
from test_optional_tts_setup import (ALL, B, C, CV, K, SESSION, WHEEL, as_json, component, facts, install_chatterbox,  # noqa: F401
                                     install_kokoro, install_request, probes_are_explicit, run_main, sandbox,
                                     tiny_assets, tripwire, unit, world)
from test_qwen3_runtime import BASE_ONLY, CUSTOM_ONLY, TINY_FILES, install_environment, install_model
from test_qwen3_setup import Hub, fake_runner, no_sleep, opener, url_path
from test_optional_setup_authority import (authority_world, b1_zero_consent_control,  # noqa: F401
                                            b2_model_only_control,
                                            test_chatterbox_race_is_checked_after_real_lock_before_any_transfer as
                                            chatterbox_race_control)

pytestmark = pytest.mark.usefixtures("production_writes_refused")

REPO = Path(__file__).resolve().parents[2]
WHEEL_PATH = "/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/" + assets.SPACY_WHEEL_NAME


# --------------------------------------------------------------------------- #
# Fixtures: a loopback hub, a fake pip, an acquirer wired to both
# --------------------------------------------------------------------------- #
def hub_path(files: assets.AssetSet, name: str) -> str:
    return f"/{files.repo}/resolve/{files.revision}/{name}"


@pytest.fixture
def server(world, monkeypatch):
    """Every pinned stand-in at its pinned commit (b"k" * size), the stand-in spaCy wheel, and both Qwen3 models."""
    files = {}
    for pinned in (assets.kokoro_set(), assets.chatterbox_set()):
        for name, (size, _) in pinned.files.items():
            files[hub_path(pinned, name)] = b"k" * size
    for key, extra in (("customvoice", CUSTOM_ONLY), ("base", BASE_ONLY)):
        spec = rt.model_spec(key)
        for name, data in {**TINY_FILES, **extra}.items():
            files[url_path(spec, name)] = data
    files[WHEEL_PATH] = WHEEL
    hub = Hub(files)
    base = f"http://127.0.0.1:{hub.port}"
    monkeypatch.setattr(su, "HUB_URL", base + "/{repo}/resolve/{revision}/{path}")
    monkeypatch.setattr(assets, "SPACY_WHEEL_URL", base + WHEEL_PATH)
    monkeypatch.setattr(su, "DOWNLOAD_BLOCK", 4)  # several reads per file: a cut really is mid-file
    python = proto.main_console_python(world)  # the app's own interpreter, as the pip step expects to find it
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"")
    yield hub
    hub.close()


class FakePip:
    """pip, faked: records the command, checks it installs exactly the verified local wheel, then reports the version."""

    def __init__(self, *, spacy="3.8.16", installed=None, code=0, hang=False, reports="3.8.0"):
        self.versions = {"spacy": spacy, assets.SPACY_ENGLISH: installed}
        self.code, self.hang, self.reports = code, hang, reports
        self.commands: list[list[str]] = []
        self.requirements: list[str] = []

    def version_of(self, name):
        return self.versions.get(name)

    def __call__(self, cmd, *, env, cwd, on_line, cancel_check=None):
        cmd = [str(c) for c in cmd]
        self.commands.append(cmd)
        requirement = Path(cmd[cmd.index("-r") + 1])
        self.requirements.append(requirement.read_text(encoding="utf-8"))
        wheel = Path(cwd) / assets.SPACY_WHEEL_NAME
        assert hashlib.sha256(wheel.read_bytes()).hexdigest() == assets.SPACY_WHEEL_SHA256  # verified before pip
        if self.hang:
            deadline = time.monotonic() + 10
            while not cancel_check():
                assert time.monotonic() < deadline, "pip was never cancelled"
                time.sleep(0.01)
            raise su.SetupCancelled()
        if self.code:
            on_line("ERROR: wheel is invalid")
            return self.code
        self.versions[assets.SPACY_ENGLISH] = self.reports
        return 0


def acquirer(pip: FakePip | None = None, **kwargs) -> osa.RealAcquirer:
    pip = pip or FakePip()
    options = dict(opener=opener, runner=pip, disk_free=lambda path: 10**12, sleep=no_sleep, version_of=pip.version_of)
    options.update(kwargs)
    return osa.RealAcquirer(**options)


def local_facts(pip: FakePip, health=None, **kwargs) -> osu.Facts:
    return osu.Facts(health=health or {}, python=(3, 12), is_64bit=True, package_version=pip.version_of, **kwargs)


def install(root, components, pip, *, health, acq=None, proof=None, **kwargs) -> tuple[int, dict, osa.RealAcquirer]:
    """A whole consented install through the worker: plan, consent, spend, acquire, prove."""
    plan = osu.plan_to_json(osu.plan(components, facts=local_facts(pip, health)))
    request = proto.new_request(proto.ACTION_INSTALL, components, session=SESSION, consent=osu.consent_for(plan))
    acq = acq or acquirer(pip)
    code, result = run_main(root, request, facts=local_facts(pip, health), acquirer=acq,
                            health=proof or (lambda c: health), **kwargs)
    return code, result, acq


def fetched(hub: Hub) -> list[str]:
    return [p for p in hub.paths()]


KOKORO_HEALTHY = {K: True}


# =========================================================================== #
# Task A — test isolation: refusal at the write boundary
# =========================================================================== #
WRITES = {
    "open-w": lambda p: open(p / "f.txt", "w").close(),
    "open-a": lambda p: open(p / "f.txt", "a").close(),
    "os-open-create": lambda p: os.close(os.open(p / "f.txt", os.O_CREAT | os.O_WRONLY)),
    "write-bytes": lambda p: (p / "f.txt").write_bytes(b"x"),
    "mkdir": lambda p: (p / "d").mkdir(),
    "makedirs": lambda p: os.makedirs(p / "a" / "b"),
    "replace-into": lambda p: os.replace(p.parent / "outside.txt", p / "f.txt"),
    "rename-out": lambda p: os.rename(p / "existing.txt", p.parent / "moved.txt"),
    "unlink": lambda p: (p / "existing.txt").unlink(),
    "rmtree": lambda p: __import__("shutil").rmtree(p / "tree"),
    "hardlink-into": lambda p: os.link(p.parent / "outside.txt", p / "f.txt"),
}


@pytest.fixture
def protected(tmp_path):
    """A disposable stand-in for production: a folder the tripwire guards, with a file, a tree, and a file beside it."""
    root = tmp_path / "production"
    (root / "tree").mkdir(parents=True)
    (root / "existing.txt").write_text("kept", encoding="utf-8")
    (root / "tree" / "inner.txt").write_text("kept", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("source", encoding="utf-8")
    return root


def listing(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root.parent)) for p in root.parent.rglob("*"))


@pytest.mark.parametrize("name", sorted(WRITES))
def test_every_write_capable_operation_on_a_protected_tree_is_refused_before_it_happens(protected, name):
    before = listing(protected)
    with write_tripwire.armed([protected]) as attempts:
        with pytest.raises(PermissionError, match="write tripwire"):
            WRITES[name](protected)
    assert listing(protected) == before  # nothing created, moved or removed
    assert attempts and all(str(protected) in path for _, path in attempts)


def test_reads_and_writes_elsewhere_are_untouched_by_the_tripwire(protected, tmp_path):
    with write_tripwire.armed([protected]) as attempts:
        assert (protected / "existing.txt").read_text(encoding="utf-8") == "kept"
        (tmp_path / "elsewhere.txt").write_text("fine", encoding="utf-8")
        os.replace(tmp_path / "elsewhere.txt", tmp_path / "moved.txt")
    assert attempts == [] and (tmp_path / "moved.txt").read_text(encoding="utf-8") == "fine"


def test_a_junction_in_a_sandbox_cannot_carry_a_write_into_the_protected_tree(protected, tmp_path):
    from test_optional_tts_setup import _junction

    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    if not _junction(sandbox_dir / "door", protected):
        pytest.skip("cannot create a junction here")
    with write_tripwire.armed([protected]) as attempts:
        with pytest.raises(PermissionError, match="write tripwire"):
            (sandbox_dir / "door" / "planted.txt").write_text("x", encoding="utf-8")
    assert not (protected / "planted.txt").exists()
    assert [path for _, path in attempts] == [str(sandbox_dir / "door" / "planted.txt")]  # and reported as this layer's


def test_a_refused_bytecode_cache_write_is_not_reported_as_the_tests_attempt(protected):
    import importlib.util

    source = protected / "cache_probe.py"
    source.write_text("VALUE = 73\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("cache_probe", source)
    module = importlib.util.module_from_spec(spec)
    start = len(write_tripwire.refusals)
    # Exercise the actual frozen CPython writer, even under the guarded runner's -B.
    with pytest.MonkeyPatch.context() as patch, write_tripwire.armed([protected]) as attempts:
        patch.setattr(sys, "dont_write_bytecode", False)
        spec.loader.exec_module(module)
    assert module.VALUE == 73 and len(write_tripwire.refusals) > start
    assert attempts == []
    assert not (protected / "__pycache__").exists()


def test_the_stage1_slip_is_now_stopped_at_the_write_itself(protected, monkeypatch):
    """P05B Stage 1: ``monkeypatch.undo()`` also undid the sandbox's ``repo_root`` redirect, and the next line ran
    ``mkdir`` on the real ``.venv/engines/qwen3``. Reproduced against a disposable 'production' root."""
    (protected / ".venv").mkdir()
    sandbox_root = protected.parent / "sandbox"
    (sandbox_root / ".venv").mkdir(parents=True)
    monkeypatch.setattr(rt, "repo_root", lambda: protected)  # what the real value would be
    inner = pytest.MonkeyPatch()
    inner.setattr(rt, "repo_root", lambda: sandbox_root)  # the sandbox redirect
    assert rt.nested_venv_dir().is_relative_to(sandbox_root)
    inner.undo()  # the slip: the redirect is gone
    with write_tripwire.armed([protected]) as attempts:
        with pytest.raises(PermissionError, match="write tripwire"):
            rt.nested_venv_dir().mkdir(parents=True)
    assert attempts and not (protected / ".venv" / "engines").exists()
    # The corrected pattern: a scoped patch is undone alone, and the sandbox redirect survives -- even a fault inside.
    monkeypatch.setattr(rt, "repo_root", lambda: sandbox_root)
    with pytest.raises(RuntimeError):
        with monkeypatch.context() as patch:
            patch.setattr(assets, "KOKORO_REVISION", "9" * 40)
            raise RuntimeError("a fault injected mid-test")
    assert rt.repo_root() == sandbox_root and assets.KOKORO_REVISION != "9" * 40


def _undo_calls(source: str) -> list[int]:
    return [node.lineno for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "undo"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "monkeypatch"]


def test_no_optional_setup_test_calls_monkeypatch_undo():
    for name in ("test_optional_tts_setup.py", "test_optional_setup_acquisition.py"):
        assert _undo_calls((Path(__file__).parent / name).read_text(encoding="utf-8")) == [], name
    assert _undo_calls("def t(monkeypatch):\n    monkeypatch.undo()\n") == [2]  # negative control: it would be seen


def test_the_production_roots_cover_both_environments_runtime_data_and_bundled_assets():
    import conftest

    roots = {Path(p) for p in conftest.PRODUCTION_WRITE_ROOTS}
    for must in (REPO / ".venv", REPO / ".venv-qwen3", REPO / "files" / "runtime-data",
                 REPO / "files" / "Cloned-Voice-Uploads", REPO / "scripts" / "tts" / "data"):
        assert must in roots
    assert write_tripwire._armed, "this module runs with the production tripwire armed"
    armed = {root for layer in write_tripwire._armed for root in layer}
    for real in (REPO / ".venv" / "engines" / "qwen3", REPO / "files" / "runtime-data" / "models" / "huggingface",
                 REPO / "files" / "runtime-data" / "optional-setup"):
        assert write_tripwire._inside(write_tripwire._norm(str(real)), tuple(armed))


def test_the_write_boundary_refuses_outside_paths_and_links_on_the_way(world, tmp_path):
    from test_optional_tts_setup import _junction

    hub_root = assets.hf_hub_root()
    hub_root.mkdir(parents=True)
    osa._require_inside(world, hub_root, hub_root / "models--a--b" / "snapshots" / "c" / "f.bin")  # fine
    with pytest.raises(osa.AcquisitionRefused, match="outside"):
        osa._require_inside(world, hub_root, world / "files" / "elsewhere.bin")
    with pytest.raises(osa.AcquisitionRefused, match="outside"):
        osa._require_inside(world, hub_root, hub_root / ".." / ".." / "escaped.bin")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    if not _junction(hub_root / "models--x--y", outside):
        pytest.skip("cannot create a junction here")
    with pytest.raises(osa.AcquisitionRefused, match="link"):
        osa._require_inside(world, hub_root, hub_root / "models--x--y" / "f.bin")


def test_the_acquirer_checks_containment_at_each_write_not_once(world, server, monkeypatch, tmp_path):
    """A link swapped into the cache between planning and writing is caught at the write: nothing lands outside."""
    from test_optional_tts_setup import _junction

    pip = FakePip(installed="3.8.0")
    plan = osu.plan_to_json(osu.plan([K], facts=local_facts(pip, KOKORO_HEALTHY)))
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    snapshot = assets.snapshot_dir(assets.kokoro_set())
    snapshot.parent.mkdir(parents=True)
    if not _junction(snapshot, outside):
        pytest.skip("cannot create a junction here")
    report = acquirer(pip).acquire(plan, osu.consent_for(plan), progress=lambda e: None, cancel_check=lambda: False)
    assert not report.completed and "link" in report.detail
    assert list(outside.iterdir()) == [] and server.paths() == []


# =========================================================================== #
# Task B — the four real acquisition paths
# =========================================================================== #
def test_kokoro_alone_is_fetched_at_its_pinned_commit_verified_recorded_and_proved(world, server):
    pip = FakePip()
    code, result, acq = install(world, [K], pip, health=KOKORO_HEALTHY)
    assert code == 0 and result["state"] == proto.SUCCEEDED and result["verified"] == [K], result
    kokoro = assets.kokoro_set()
    expected = sorted(hub_path(kokoro, name) for name in kokoro.files) + [WHEEL_PATH]
    assert sorted(fetched(server)) == sorted(expected)
    assert all("/resolve/main/" not in p for p in fetched(server))  # never a moving branch
    assert assets.assess(kokoro, kokoro.files) == {n: (assets.READY, "") for n in kokoro.files}
    record = json.loads(assets.record_path(kokoro).read_text(encoding="utf-8"))
    assert record["revision"] == kokoro.revision and set(record["files"]) == set(kokoro.files)
    (cmd,), (requirement,) = pip.commands, pip.requirements
    for flag in ("--no-deps", "--no-index", "--require-hashes", "--isolated", "--require-virtualenv", "--no-input"):
        assert flag in cmd
    assert cmd[:3] == [str(proto.main_console_python(world)), "-m", "pip"]
    assert requirement.startswith(f"{assets.SPACY_ENGLISH} @ file:///") and \
        requirement.rstrip().endswith(f"--hash=sha256:{assets.SPACY_WHEEL_SHA256}")
    assert not (proto.exchange_root(world) / "downloads" / assets.SPACY_WHEEL_NAME).exists()  # space given back
    assert component(result["plan"], K)["readiness"] == proto.READY
    assert [opener_.requested for opener_ in acq.openers if opener_.requested]  # through the scoped door only


def test_chatterbox_alone_fetches_exactly_the_files_turbo_loads(world, server):
    code, result, _ = install(world, [C], FakePip(installed="3.8.0"), health={C: True})
    assert result["state"] == proto.SUCCEEDED and result["verified"] == [C]
    cbx = assets.chatterbox_set()
    assert sorted(fetched(server)) == sorted(hub_path(cbx, n) for n in cbx.files)
    assert not any("s3gen.safetensors" in p and "meanflow" not in p for p in fetched(server))


def test_nothing_selected_acquires_nothing(world, server):
    request = proto.new_request(proto.ACTION_PLAN, [], session=SESSION)
    code, result = run_main(world, request, facts=facts(), acquirer=acquirer())
    assert code == 0 and result["plan"]["acquire_units"] == [] and server.paths() == []


class FakeQwen:
    """``qwen3_setup.install``/``repair`` stand-in: records each call, then leaves the sandbox as a real one would."""

    def __init__(self, root: Path, *, ok=True, cancelled=False):
        self.root, self.ok, self.cancelled = root, ok, cancelled
        self.calls: list[tuple[str, tuple]] = []

    def _do(self, kind, keys, **kwargs):
        self.calls.append((kind, tuple(keys)))
        assert isinstance(kwargs["opener"], osa.ScopedOpener)  # the installer is handed the scoped door only
        if self.cancelled:
            return su.SetupResult(False, "Cancelled.", cancelled=True)
        if not self.ok:
            return su.SetupResult(False, "Installing the Qwen3 packages failed.")
        if not rt.environment_status()[0]:
            install_environment(self.root, requirements=(self.root / "scripts" / "qwen3-requirements.txt")
                                .read_text(encoding="utf-8"))
        for key in keys:
            install_model(self.root, key)
        return su.SetupResult(True, "done")

    def install(self, keys, **kwargs):
        return self._do("install", keys, **kwargs)

    def repair(self, keys, **kwargs):
        return self._do("repair", keys, **kwargs)


def test_all_four_together_install_once_each_and_both_qwen3_models_in_one_installer_call(world, server):
    pip = FakePip()
    qwen = FakeQwen(world)
    health = {K: True, C: True}
    code, result, acq = install(world, list(ALL), pip, health=health,
                                acq=acquirer(pip, qwen_install=qwen.install, qwen_repair=qwen.repair))
    assert result["state"] == proto.SUCCEEDED and result["verified"] == list(ALL), result
    assert qwen.calls == [("install", ("customvoice", "base"))]  # the shared engine and both models: one install
    assert sorted(set(fetched(server))) == sorted(fetched(server))  # no file fetched twice


def test_both_qwen3_models_through_the_real_installer_fetch_the_shared_files_once(world, server, monkeypatch):
    runner = fake_runner(world, monkeypatch)
    code, result, acq = install(world, [CV, B], FakePip(installed="3.8.0"), health={},
                                acq=acquirer(runner=runner))
    assert result["state"] == proto.SUCCEEDED and result["verified"] == [CV, B], result
    shared = [p for p in fetched(server) if p.endswith("speech_tokenizer/model.safetensors")]
    assert len(shared) == 1  # the second model links/copies the shared tokenizer from the first
    for key in ("customvoice", "base"):
        spec = rt.model_spec(key)
        assert all(p.startswith(f"/{spec.repo}/resolve/{spec.revision}/") for p in fetched(server) if spec.repo in p)
    assert [job.get("model_dir") is not None for job in runner.probe_jobs].count(True) == 2  # each model load-checked


def test_a_second_qwen3_model_added_later_installs_only_that_model(world, server):
    install_environment(world, requirements=(world / "scripts" / "qwen3-requirements.txt").read_text(encoding="utf-8"))
    install_model(world, "customvoice")
    qwen = FakeQwen(world)
    code, result, _ = install(world, [CV, B], FakePip(installed="3.8.0"), health={},
                              acq=acquirer(qwen_install=qwen.install, qwen_repair=qwen.repair))
    assert result["state"] == proto.SUCCEEDED and qwen.calls == [("install", ("base",))]


def test_a_damaged_qwen3_model_goes_through_the_installers_own_repair(world, server):
    install_environment(world, requirements=(world / "scripts" / "qwen3-requirements.txt").read_text(encoding="utf-8"))
    install_model(world, "customvoice")
    (rt.model_spec("customvoice").directory / "model.safetensors").unlink()
    qwen = FakeQwen(world)
    code, result, _ = install(world, [CV], FakePip(installed="3.8.0"), health={},
                              acq=acquirer(qwen_install=qwen.install, qwen_repair=qwen.repair))
    assert qwen.calls == [("repair", ("customvoice",))] and result["state"] == proto.SUCCEEDED


def test_everything_already_ready_downloads_nothing_and_runs_no_pip(world, server):
    install_kokoro(world)
    pip = FakePip(installed="3.8.0")
    code, result, _ = install(world, [K], pip, health=KOKORO_HEALTHY)
    assert result["state"] == proto.SUCCEEDED and server.paths() == [] and pip.commands == []


def test_mixed_damaged_and_missing_files_fetch_only_those_under_repair_consent(world, server):
    snapshot = install_kokoro(world, without={"voices/af_heart.pt"})
    (snapshot / "kokoro-v1_0.pth").write_bytes(b"x" * 40)  # same size, wrong bytes
    pip = FakePip(installed="3.8.0")
    plan = osu.plan_to_json(osu.plan([K], facts=local_facts(pip, KOKORO_HEALTHY)))
    assert component(plan, K)["consent_scope"] == proto.SCOPE_REPAIR
    code, result, _ = install(world, [K], pip, health=KOKORO_HEALTHY)
    kokoro = assets.kokoro_set()
    assert sorted(fetched(server)) == sorted([hub_path(kokoro, "kokoro-v1_0.pth"), hub_path(kokoro, "voices/af_heart.pt")])
    assert result["state"] == proto.SUCCEEDED and (snapshot / "kokoro-v1_0.pth").read_bytes() == b"k" * 40


def test_a_consent_given_to_the_first_run_estimate_acquires_only_what_is_still_missing(world, server):
    install_kokoro(world, without={assets.kokoro_voice_name(v) for v in osu.kokoro_roster()})
    pip = FakePip()
    shown = osu.plan_to_json(osu.estimate([K]))
    request = proto.new_request(proto.ACTION_INSTALL, [K], session=SESSION, consent=osu.consent_for(shown))
    code, result = run_main(world, request, facts=local_facts(pip, KOKORO_HEALTHY), acquirer=acquirer(pip),
                            health=lambda c: KOKORO_HEALTHY)
    assert result["state"] == proto.SUCCEEDED
    assert not any(p.endswith(("config.json", "kokoro-v1_0.pth")) for p in fetched(server))


# =========================================================================== #
# Task C — pinned sources: drift, hash, size, spaCy
# =========================================================================== #
def test_a_plan_unit_naming_any_other_source_is_refused_before_any_network(world, server):
    pip = FakePip(installed="3.8.0")
    plan = osu.plan_to_json(osu.plan([K], facts=local_facts(pip, KOKORO_HEALTHY)))
    consent = osu.consent_for(plan)
    drifted = json.loads(json.dumps(plan))
    unit(drifted, "kokoro-model")["source"] = f"hf:{assets.KOKORO_REPO}@main"
    with pytest.raises(osa.AcquisitionRefused, match="source"):
        acquirer(pip).acquire(drifted, consent, progress=lambda e: None, cancel_check=lambda: False)
    outside = json.loads(json.dumps(plan))
    outside["acquire_units"].append("qwen3-engine")  # not in the consent
    with pytest.raises(osa.AcquisitionRefused, match="does not cover"):
        acquirer(pip).acquire(outside, consent, progress=lambda e: None, cancel_check=lambda: False)
    assert server.paths() == []


def test_the_scoped_opener_refuses_any_url_outside_the_confirmed_files():
    door = osa.ScopedOpener(["https://example.invalid/allowed"], base=lambda request: "opened")
    assert door(types.SimpleNamespace(full_url="https://example.invalid/allowed")) == "opened"
    with pytest.raises(osa.AcquisitionRefused):
        door(types.SimpleNamespace(full_url="https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/config.json"))
    assert door.requested == ["https://example.invalid/allowed"]
    assert not issubclass(osa.AcquisitionRefused, (OSError, ValueError))  # never retried by the downloader


@pytest.mark.parametrize("fault", ["wrong-bytes", "wrong-size"])
def test_a_served_file_that_is_not_the_pinned_one_is_never_installed(world, server, fault):
    kokoro = assets.kokoro_set()
    path = hub_path(kokoro, "kokoro-v1_0.pth")
    if fault == "wrong-bytes":
        server.wrong_bytes.add(path)
    else:
        server.files[path] = b"k" * 41
    code, result, _ = install(world, [K], FakePip(installed="3.8.0"), health=KOKORO_HEALTHY)
    assert result["state"] == proto.FAILED and result["error"]["code"] == proto.ACQUISITION_FAILED
    target = assets.snapshot_dir(kokoro) / "kokoro-v1_0.pth"
    assert not target.exists() and not target.with_name(target.name + ".part").exists()  # nothing kept to resume
    assert assets.file_state(kokoro, "kokoro-v1_0.pth")[0] != assets.READY


def test_a_moved_upstream_main_is_never_asked_for(world, server):
    kokoro = assets.kokoro_set()
    server.files[f"/{kokoro.repo}/resolve/main/config.json"] = b"something else entirely"
    install(world, [K], FakePip(installed="3.8.0"), health=KOKORO_HEALTHY)
    assert all(f"/resolve/{kokoro.revision}/" in p for p in fetched(server))


def test_the_wheel_is_verified_before_pip_and_an_invalid_one_never_reaches_pip(world, server):
    server.wrong_bytes.add(WHEEL_PATH)
    install_kokoro(world)
    pip = FakePip()
    code, result, _ = install(world, [K], pip, health=KOKORO_HEALTHY)
    assert result["state"] == proto.FAILED and pip.commands == []


def test_a_wheel_pip_rejects_is_a_failure_and_nothing_is_claimed(world, server):
    install_kokoro(world)
    pip = FakePip(code=1)
    code, result, _ = install(world, [K], pip, health=KOKORO_HEALTHY)
    assert result["state"] == proto.FAILED and "pip could not install" in result["error"]["message"]
    assert pip.versions[assets.SPACY_ENGLISH] is None and result["verified"] == []


def test_pip_reporting_another_version_afterwards_is_not_a_success(world, server):
    install_kokoro(world)
    code, result, _ = install(world, [K], FakePip(reports="3.7.1"), health=KOKORO_HEALTHY)
    assert result["state"] == proto.FAILED and "3.7.1" in result["error"]["message"]


@pytest.mark.parametrize("spacy", ["3.9.0", "3.7.5", "3.8.0rc1", None])
def test_an_incompatible_or_absent_spacy_is_never_changed_to_fit(world, server, spacy):
    install_kokoro(world)
    pip = FakePip(spacy=spacy)
    plan = osu.plan_to_json(osu.plan([K], facts=local_facts(pip, KOKORO_HEALTHY)))
    assert unit(plan, "spacy-english")["state"] == proto.UNVERIFIED  # so Kokoro is not acquirable at all
    with pytest.raises(proto.ProtocolError) as refused:
        osu.consent_for(plan)
    assert refused.value.code == proto.NOT_ACQUIRABLE
    with pytest.raises(osa.AcquisitionError):  # and the acquirer refuses on its own too, before any download or pip
        acquirer(pip)._acquire_spacy(world, lambda e: None, lambda: False)
    assert pip.commands == [] and server.paths() == []


def test_another_installed_english_model_is_reported_not_replaced(world):
    state, detail = assets.spacy_english_state(lambda n: {"spacy": "3.8.16", assets.SPACY_ENGLISH: "3.7.1"}.get(n))
    assert state == proto.UNVERIFIED and "not replaced" in detail
    assert assets.parse_version("3.8.16") == (3, 8, 16) and assets.parse_version("3.8") is None


def test_the_real_pins_are_the_approved_ones():
    """The owner's spaCy ruling and the Stage 1 measured identities, pinned exactly (not the stand-ins)."""
    real = assets  # no tiny_assets fixture here: these are the module's own constants
    assert real.SPACY_WHEEL_URL == ("https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/"
                                    "en_core_web_sm-3.8.0-py3-none-any.whl")
    assert real.SPACY_WHEEL_SIZE == 12_806_118
    assert real.SPACY_WHEEL_SHA256 == "1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"
    assert real.SPACY_COMPATIBLE == ((3, 8, 0), (3, 9, 0)) and real.SPACY_ENGLISH_VERSION == "3.8.0"
    assert real.KOKORO_REVISION == "f3ff3571791e39611d31c381e3a41a3af07b4987"
    assert real.CHATTERBOX_REVISION == "749d1c1a46eb10492095d68fbcf55691ccf137cd"
    assert real.KOKORO_FILES["kokoro-v1_0.pth"] == (
        327_212_226, "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4")
    assert len(real.KOKORO_FILES) == 11 and len(real.CHATTERBOX_FILES) == 9
    assert "s3gen.safetensors" not in real.CHATTERBOX_FILES
    assert all(len(sha) == 64 and size > 0 for size, sha in [*real.KOKORO_FILES.values(), *real.CHATTERBOX_FILES.values()])
    requirements = (REPO / "scripts" / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "en_core_web_sm" not in requirements and "en-core-web-sm" not in requirements  # never unconditional


# =========================================================================== #
# Task C — first use can never download
# =========================================================================== #
@pytest.fixture
def fake_kokoro(monkeypatch):
    """Fake ``kokoro``/``torch`` modules: a KModel/KPipeline that record how they were built, and whose Hub path fails."""
    built: dict = {"models": [], "pipelines": []}

    def no_hub(*args, **kwargs):
        raise AssertionError("hf_hub_download was reached")

    class KModel:
        def __init__(self, repo_id=None, config=None, model=None):
            if not config or not model:
                no_hub()
            built["models"].append({"repo_id": repo_id, "config": config, "model": model})

        def to(self, device):
            return self

        def eval(self):
            return self

    class KPipeline:
        def __init__(self, lang_code, repo_id=None, model=True):
            if model is True:
                no_hub()
            built["pipelines"].append({"lang": lang_code, "model": model})
            self.voices = {}

        def load_single_voice(self, voice):
            if not voice.endswith(".pt"):
                no_hub()
            self.voices[voice] = f"pack:{Path(voice).name}"
            return self.voices[voice]

    kokoro = types.ModuleType("kokoro")
    kokoro.KModel, kokoro.KPipeline = KModel, KPipeline
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    monkeypatch.setitem(sys.modules, "kokoro", kokoro)
    monkeypatch.setitem(sys.modules, "torch", torch)
    from shared import espeak_data

    monkeypatch.setattr(espeak_data, "configure", lambda *a, **k: None)
    return built


def test_a_kokoro_pipeline_is_built_from_the_verified_local_files_only(world, fake_kokoro, monkeypatch):
    from tts import kokoro_synth

    install_kokoro(world)
    monkeypatch.setattr(assets, "installed_version", lambda name: "3.8.0")
    pipeline = kokoro_synth._instantiate_pipeline("a")
    (model,) = fake_kokoro["models"]
    snapshot = assets.snapshot_dir(assets.kokoro_set())
    assert Path(model["config"]) == snapshot / "config.json" and Path(model["model"]) == snapshot / "kokoro-v1_0.pth"
    pack = pipeline.load_single_voice("af_heart")  # by id, exactly as the pipeline asks for it
    assert pack == "pack:af_heart.pt" and pipeline.voices["af_heart"] == pack


def test_a_missing_or_wrong_kokoro_file_is_refused_not_downloaded(world, fake_kokoro, monkeypatch):
    from tts import kokoro_synth

    monkeypatch.setattr(assets, "installed_version", lambda name: "3.8.0")
    with pytest.raises(assets.AssetsUnavailable, match="Nothing was downloaded"):
        kokoro_synth._instantiate_pipeline("a")
    assert fake_kokoro["models"] == [] and fake_kokoro["pipelines"] == []
    snapshot = install_kokoro(world, without={"voices/af_bella.pt"})
    pipeline = kokoro_synth._instantiate_pipeline("a")
    with pytest.raises(assets.AssetsUnavailable):
        pipeline.load_single_voice("af_bella")  # a missing voice: refused at first use, not fetched
    with pytest.raises(assets.AssetsUnavailable, match="approved"):
        pipeline.load_single_voice("zf_unknown")  # a voice with no pinned identity is never fetched either
    (snapshot / "config.json").write_bytes(b"x" * 4)  # same size, wrong content
    with pytest.raises(assets.AssetsUnavailable, match="SHA-256"):
        kokoro_synth._instantiate_pipeline("a")


def test_a_missing_english_model_is_refused_before_misaki_could_pip_install_it(world, fake_kokoro, monkeypatch):
    from tts import kokoro_synth

    install_kokoro(world)
    downloads: list = []
    spacy = types.ModuleType("spacy")
    spacy.cli = types.SimpleNamespace(download=lambda name: downloads.append(name))
    monkeypatch.setitem(sys.modules, "spacy", spacy)
    monkeypatch.setattr(assets, "installed_version", lambda name: None)
    with pytest.raises(assets.AssetsUnavailable, match="en_core_web_sm"):
        kokoro_synth._instantiate_pipeline("a")
    assert downloads == [] and fake_kokoro["pipelines"] == []


def test_a_refusal_is_not_mistaken_for_a_broken_engine(world, fake_kokoro, monkeypatch):
    """It is neither retried as a first-load Application Control block nor allowed to forget the dependency proof."""
    from tts import kokoro_synth

    forgotten: list = []
    monkeypatch.setattr(kokoro_synth, "_forget_kokoro_proof", lambda: forgotten.append(1))
    monkeypatch.setattr(kokoro_synth, "_PIPELINE_CACHE", {})
    monkeypatch.setattr(kokoro_synth, "_first_pipeline_load_attempted", False)
    monkeypatch.setattr(assets, "installed_version", lambda name: "3.8.0")
    slept: list = []
    monkeypatch.setattr(kokoro_synth.time, "sleep", lambda s: slept.append(s))
    with pytest.raises(assets.AssetsUnavailable):
        kokoro_synth._get_pipeline("a")
    assert forgotten == [] and slept == []
    assert not issubclass(assets.AssetsUnavailable, (RuntimeError, OSError, ImportError))
    with pytest.raises(assets.AssetsUnavailable):
        kokoro_synth.synthesize_text_to_mp3("Hello.", str(world / "out.mp3"), voice_id="af_heart")


def test_chatterbox_loads_from_the_verified_pinned_folder_never_from_pretrained(world, monkeypatch):
    from tts import chatterbox_synth

    calls: list = []

    class Turbo:
        @classmethod
        def from_pretrained(cls, device):
            raise AssertionError("from_pretrained (snapshot_download at main) was reached")

        @classmethod
        def from_local(cls, folder, device):
            calls.append((Path(folder), device))
            return "model"

    turbo = types.ModuleType("chatterbox.tts_turbo")
    turbo.ChatterboxTurboTTS = Turbo
    package = types.ModuleType("chatterbox")
    package.tts_turbo = turbo
    monkeypatch.setitem(sys.modules, "chatterbox", package)
    monkeypatch.setitem(sys.modules, "chatterbox.tts_turbo", turbo)
    monkeypatch.setattr(chatterbox_synth, "_ensure_structural_colon_patch", lambda module: None)
    with pytest.raises(assets.AssetsUnavailable):
        chatterbox_synth._instantiate_model("cpu")
    assert calls == []
    install_chatterbox(world)
    assert chatterbox_synth._instantiate_model("cpu") == "model"
    assert calls == [(assets.snapshot_dir(assets.chatterbox_set()), "cpu")]


def test_no_production_module_reaches_a_lazy_download_entry_point():
    """AST guard: only the consented acquirer may name a downloader; inference names none of the lazy entry points."""
    banned = {"from_pretrained", "hf_hub_download", "snapshot_download", "download"}
    for name in ("kokoro_synth.py", "chatterbox_synth.py", "model_assets.py"):
        tree = ast.parse((REPO / "scripts" / "tts" / name).read_text(encoding="utf-8"))
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        called |= {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert not banned & called, (name, banned & called)


# =========================================================================== #
# Task D — health, busy, progress, cancellation, recovery
# =========================================================================== #
def test_a_lock_is_read_without_ever_being_created(world):
    path = rt.setup_lock_path()
    assert osh.lock_held(path) is False and not path.exists()
    lock = rt.FileLock(path)
    assert lock.acquire()
    try:
        assert osh.lock_held(path) is True
        assert osh.busy_components(ALL) == frozenset(ALL)
    finally:
        lock.release()
    assert osh.lock_held(path) is False
    inference = rt.FileLock(rt.inference_lock_path())
    assert inference.acquire()
    try:
        assert osh.busy_components(ALL) == frozenset({CV, B})  # a Qwen3 conversion holds only the Qwen3 voices
    finally:
        inference.release()


def test_a_busy_component_is_refused_and_nothing_is_fetched(world, server):
    lock = rt.FileLock(rt.setup_lock_path())
    assert lock.acquire()
    try:
        request = install_request([C], health={C: True})
        code, result = run_main(world, request, acquirer=acquirer())  # the worker's own facts: real locks
    finally:
        lock.release()
    assert result["state"] == proto.REFUSED and result["error"]["code"] == proto.NOT_ACQUIRABLE
    assert "busy" in result["error"]["message"] and server.paths() == []


def test_a_concurrent_installer_is_refused_by_the_install_lock(world, server):
    pip = FakePip(installed="3.8.0")
    plan = osu.plan_to_json(osu.plan([C], facts=local_facts(pip, {C: True})))
    with su.InstallLock():
        report = acquirer(pip).acquire(plan, osu.consent_for(plan), progress=lambda e: None,
                                       cancel_check=lambda: False)
    assert not report.completed and "already being installed" in report.detail and server.paths() == []


def runner_lines(lines, *, code=0, hang=False):
    def run(cmd, *, env, cwd, on_line, cancel_check):
        run.calls.append({"cmd": [str(c) for c in cmd], "env": env, "cwd": cwd})
        if hang:
            while not cancel_check():
                time.sleep(0.01)
            raise su.SetupCancelled()
        for line in lines:
            on_line(line)
        return code
    run.calls = []
    return run


def test_the_engine_probes_are_offline_bounded_and_tri_state(world):
    ok = runner_lines(['OK:{"english_model": true, "weights": true}'])
    assert osh.kokoro_health(world, cancel_check=lambda: False, runner=ok) == (True, "ok")
    (call,) = ok.calls
    assert call["cmd"][:4] == [str(proto.main_console_python(world)), "-E", "-s", "-c"]
    assert call["env"]["HF_HUB_OFFLINE"] == "1" and call["env"]["TRANSFORMERS_OFFLINE"] == "1"
    assert not any(k.upper().startswith(("PYTHON", "PIP_")) for k in call["env"])
    broken = runner_lines(['BROKEN:{"stage": "import"}'], code=1)
    assert osh.kokoro_health(world, cancel_check=lambda: False, runner=broken)[0] is False
    assert osh.chatterbox_health(world, cancel_check=lambda: False, runner=runner_lines(["OK"]))[0] is True
    assert osh.chatterbox_health(world, cancel_check=lambda: False,
                                 runner=runner_lines(["MISSING:chatterbox"], code=1))[0] is False
    started = time.monotonic()
    proved, why = osh.kokoro_health(world, cancel_check=lambda: False, runner=runner_lines([], hang=True),
                                    timeout_s=0.3)
    assert proved is None and "did not finish" in why and time.monotonic() - started < 5  # unverified, never broken
    flag = threading.Event()
    threading.Timer(0.2, flag.set).start()
    proved, why = osh.chatterbox_health(world, cancel_check=flag.is_set, runner=runner_lines([], hang=True))
    assert (proved, why) == (None, "cancelled")

    def explodes(cmd, **kwargs):
        raise AssertionError("cannot start")
    assert osh.kokoro_health(world, cancel_check=lambda: False, runner=explodes)[0] is None
    assert not (world / ".venv" / ".kokoro-proof.json").exists()  # a probe never records anything


def test_the_worker_probes_exactly_the_chosen_local_engines(world, probes_are_explicit):
    request = proto.new_request(proto.ACTION_PLAN, [K, CV], session=SESSION)
    code, result = run_main(world, request, acquirer=acquirer())
    assert code == 0 and probes_are_explicit == [(K, CV)]  # asked once, after "started"; Qwen3 is judged by its record


def test_a_proved_broken_local_engine_gets_no_download(world, server):
    pip = FakePip(installed="3.8.0")
    code, result, _ = install(world, [K, C], pip, health={K: False, C: True}, proof=lambda c: {K: False, C: True})
    assert component(result["plan"], K)["engine"] == "broken"
    assert result["state"] == proto.FAILED and result["verified"] == [C]  # Chatterbox still went ahead and works
    assert not any("Kokoro-82M" in p for p in fetched(server)) and "packages" in result["error"]["message"]


def test_progress_travels_through_the_worker_events(world, server, capsys):
    from test_optional_tts_setup import events

    pip = FakePip(installed="3.8.0")
    plan = osu.plan_to_json(osu.plan([C], facts=local_facts(pip, {C: True})))
    request = proto.new_request(proto.ACTION_INSTALL, [C], session=SESSION, consent=osu.consent_for(plan))
    run_main(world, request, facts=local_facts(pip, {C: True}), acquirer=acquirer(pip), health=lambda c: {C: True})
    progress = [e["payload"] for e in events(capsys, request.request_id) if e["kind"] == "progress"]
    assert progress and progress[-1]["unit"] == "chatterbox-model"
    downloads = [p for p in progress if p["step"] == "download"]
    assert downloads[-1]["done"] == downloads[-1]["total"] == 407


def cancel_after(root: Path, request: proto.Request, when):
    """A cancel flag published the first time *when(event)* is true."""
    flag = proto.exchange_dir(root, request.request_id) / proto.CANCEL_NAME

    def progress(event):
        if when(event) and not flag.exists():
            proto.publish_once(flag, b"cancel\n")
    return progress


def test_cancel_during_a_transfer_keeps_the_partial_file_for_a_later_consented_resume(world, server):
    pip = FakePip(installed="3.8.0")
    plan = osu.plan_to_json(osu.plan([C], facts=local_facts(pip, {C: True})))
    request = proto.new_request(proto.ACTION_INSTALL, [C], session=SESSION, consent=osu.consent_for(plan))
    acq = acquirer(pip)
    trigger = cancel_after(world, request, lambda e: e.get("step") == "download" and e["done"] >= 8)
    original = osa._Meter.add

    def add(self, count, message=""):
        original(self, count, message)
        trigger({"step": "download", "done": self.done})
    import unittest.mock as mock
    with mock.patch.object(osa._Meter, "add", add):
        code, result = run_main(world, request, facts=local_facts(pip, {C: True}), acquirer=acq,
                                health=lambda c: {C: True})
    assert result["state"] == proto.CANCELLED_STATE and code == proto.EXIT_CODES[proto.CANCELLED_STATE]
    parts = list(assets.snapshot_dir(assets.chatterbox_set()).rglob("*.part"))
    assert parts and not assets.record_path(assets.chatterbox_set()).exists()  # nothing claimed verified
    # Resuming needs a fresh plan and a fresh confirmation; the partial file is resumed with a Range request.
    server.requests.clear()
    code, result, _ = install(world, [C], pip, health={C: True})
    assert result["state"] == proto.SUCCEEDED
    assert any(r["range"] for r in server.requests)


def test_a_cut_connection_is_resumed_and_the_whole_file_rehashed(world, server):
    kokoro = assets.kokoro_set()
    server.drop_once[hub_path(kokoro, "kokoro-v1_0.pth")] = 12
    code, result, _ = install(world, [K], FakePip(installed="3.8.0"), health=KOKORO_HEALTHY)
    assert result["state"] == proto.SUCCEEDED
    ranged = [r for r in server.requests if r["path"].endswith("kokoro-v1_0.pth")]
    assert len(ranged) == 2 and ranged[1]["range"] == "bytes=12-"


def test_cancel_during_pip_ends_cancelled_and_installs_nothing(world, server):
    install_kokoro(world)
    pip = FakePip(hang=True)
    plan = osu.plan_to_json(osu.plan([K], facts=local_facts(pip, KOKORO_HEALTHY)))
    request = proto.new_request(proto.ACTION_INSTALL, [K], session=SESSION, consent=osu.consent_for(plan))
    flag = proto.exchange_dir(world, request.request_id) / proto.CANCEL_NAME
    original = pip.__call__

    def cancel_then_pip(cmd, **kwargs):
        proto.publish_once(flag, b"cancel\n")
        return original(cmd, **kwargs)
    code, result = run_main(world, request, facts=local_facts(pip, KOKORO_HEALTHY),
                            acquirer=acquirer(pip, runner=cancel_then_pip), health=lambda c: KOKORO_HEALTHY)
    assert result["state"] == proto.CANCELLED_STATE and pip.versions[assets.SPACY_ENGLISH] is None


def test_cancel_during_the_health_proof_is_one_cancelled_outcome(world, server):
    pip = FakePip(installed="3.8.0")
    plan = osu.plan_to_json(osu.plan([C], facts=local_facts(pip, {C: True})))
    request = proto.new_request(proto.ACTION_INSTALL, [C], session=SESSION, consent=osu.consent_for(plan))
    flag = proto.exchange_dir(world, request.request_id) / proto.CANCEL_NAME

    def proof(components):
        proto.publish_once(flag, b"cancel\n")
        return {}  # the probe, stopped by the cancel, proved nothing
    code, result = run_main(world, request, facts=local_facts(pip, {C: True}), acquirer=acquirer(pip), health=proof)
    assert result["state"] == proto.CANCELLED_STATE and result["verified"] == []
    assert assets.file_state(assets.chatterbox_set(), "vocab.json")[0] == assets.READY  # what was fetched is kept


def test_too_little_disk_space_is_refused_before_anything_is_fetched(world, server):
    pip = FakePip(installed="3.8.0")
    code, result, _ = install(world, [C], pip, health={C: True}, acq=acquirer(pip, disk_free=lambda p: 100))
    assert result["state"] == proto.FAILED and "free disk space" in result["error"]["message"]
    assert server.paths() == []


def test_a_disk_full_error_mid_download_fails_that_component_and_keeps_the_others_working(world, server):
    install_kokoro(world)
    pip = FakePip(installed="3.8.0")
    before = {p: p.stat().st_mtime_ns for p in assets.snapshot_dir(assets.kokoro_set()).rglob("*") if p.is_file()}

    def full(request):
        raise OSError(errno.ENOSPC, "No space left on device")
    code, result, _ = install(world, [K, C], pip, health={K: True, C: True}, acq=acquirer(pip, opener=full))
    assert result["state"] == proto.FAILED and result["verified"] == [K]  # Kokoro still works
    after = {p: p.stat().st_mtime_ns for p in assets.snapshot_dir(assets.kokoro_set()).rglob("*") if p.is_file()}
    assert after == before


def test_a_permission_denied_write_is_a_failure_that_changes_nothing_verified(world, server, monkeypatch):
    pip = FakePip(installed="3.8.0")
    real_replace = os.replace

    def denied(src, dst, *args, **kwargs):
        if str(dst).endswith(".safetensors"):
            raise PermissionError(errno.EACCES, "Access is denied")
        return real_replace(src, dst, *args, **kwargs)
    monkeypatch.setattr(os, "replace", denied)
    code, result, _ = install(world, [C], pip, health={C: True})
    assert result["state"] == proto.FAILED and not assets.record_path(assets.chatterbox_set()).exists()


def test_a_changed_file_behind_a_valid_record_is_hashed_again_and_found_damaged(world, server):
    code, result, _ = install(world, [C], FakePip(installed="3.8.0"), health={C: True})
    assert result["state"] == proto.SUCCEEDED
    path = assets.snapshot_dir(assets.chatterbox_set()) / "vocab.json"
    path.write_bytes(b"x" * 7)  # same size, new content, new timestamp
    assets._HASHED.clear()
    assert assets.file_state(assets.chatterbox_set(), "vocab.json", record=assets._record(assets.chatterbox_set()))[0] \
        == assets.DAMAGED
    forged = json.loads(assets.record_path(assets.chatterbox_set()).read_text(encoding="utf-8"))
    forged["files"]["vocab.json"]["mtime_ns"] = path.stat().st_mtime_ns
    forged["files"]["vocab.json"]["sha256"] = "0" * 64  # a record can never vouch for bytes other than the pin
    assets.record_path(assets.chatterbox_set()).write_text(json.dumps(forged), encoding="utf-8")
    assert assets.assess(assets.chatterbox_set(), ["vocab.json"])["vocab.json"][0] == assets.DAMAGED


def test_a_linked_cache_is_unverified_and_never_acquired_over(world, tmp_path):
    from test_optional_tts_setup import _junction

    outside = tmp_path / "elsewhere-cache"
    outside.mkdir()
    hub_root = assets.hf_hub_root()
    hub_root.parent.mkdir(parents=True, exist_ok=True)
    if not _junction(hub_root, outside):
        pytest.skip("cannot create a junction here")
    data = as_json([K], health=KOKORO_HEALTHY, spacy=True)
    assert unit(data, "kokoro-model")["state"] == proto.UNVERIFIED
    with pytest.raises(proto.ProtocolError):
        osu.consent_for(data)


def test_a_failed_optional_install_leaves_healthy_voices_and_their_files_exactly_as_they_were(world, server):
    install_kokoro(world)
    pip = FakePip(installed="3.8.0")
    snapshot = assets.snapshot_dir(assets.kokoro_set())
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in snapshot.rglob("*") if p.is_file()}
    server.status[hub_path(assets.chatterbox_set(), "vocab.json")] = 404
    code, result, _ = install(world, [K, C], pip, health={K: True, C: True})
    assert result["state"] == proto.FAILED and result["verified"] == [K] and "Kokoro" in result["error"]["message"]
    assert {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in snapshot.rglob("*") if p.is_file()} == before


def test_forged_stale_or_replayed_consent_acquires_nothing(world, server):
    pip = FakePip(installed="3.8.0")
    plan = osu.plan_to_json(osu.plan([C], facts=local_facts(pip, {C: True})))
    consent = osu.consent_for(plan)
    forged = dataclasses.replace(consent, acquisition_fingerprint="0" * 64)
    request = proto.new_request(proto.ACTION_INSTALL, [C], session=SESSION, consent=forged)
    code, result = run_main(world, request, facts=local_facts(pip, {C: True}), acquirer=acquirer(pip))
    assert result["state"] == proto.REFUSED and server.paths() == []
    install_chatterbox(world, without={"vocab.json"})  # the world changed after confirming: a different plan
    request = proto.new_request(proto.ACTION_INSTALL, [C], session=SESSION, consent=consent)
    code, result = run_main(world, request, facts=local_facts(pip, {C: True}), acquirer=acquirer(pip))
    assert result["error"]["code"] == proto.CONSENT_STALE and server.paths() == []
    fresh = osu.consent_for(osu.plan_to_json(osu.plan([C], facts=local_facts(pip, {C: True}))))
    first = proto.new_request(proto.ACTION_INSTALL, [C], session=SESSION, consent=fresh)
    _, result = run_main(world, first, facts=local_facts(pip, {C: True}), acquirer=acquirer(pip),
                         health=lambda c: {C: True})
    assert result["state"] == proto.SUCCEEDED and len(server.paths()) == 1
    replay = proto.new_request(proto.ACTION_INSTALL, [C], session=SESSION, consent=fresh)
    _, result = run_main(world, replay, facts=local_facts(pip, {C: True}), acquirer=acquirer(pip))
    assert result["error"]["code"] in (proto.CONSENT_USED, proto.CONSENT_STALE) and len(server.paths()) == 1


def test_exactly_one_terminal_result_whatever_the_acquirer_does(world, server):
    pip = FakePip(installed="3.8.0")
    for acq in (acquirer(pip, disk_free=lambda p: 1), acquirer(pip, opener=lambda r: (_ for _ in ()).throw(OSError())),
                acquirer(pip)):
        request = install_request([C], health={C: True})
        path = proto.write_request(world, request)
        import tts.optional_setup_worker as worker
        worker.main(["--request", str(path), "--result", str(path.with_name("result.json")), "--session", SESSION],
                    repo_root=world, home_check=lambda r: "", facts=local_facts(pip, {C: True}), acquirer=acq,
                    health=lambda c: {C: True})
        result = proto.decode_result(proto.read_message_file(path.with_name("result.json")),
                                     request_id=request.request_id, request=request)
        assert result["state"] in proto.TERMINAL_STATES
        assert proto.publish_once(path.with_name("result.json"), b"{}") is False  # never a second one


# =========================================================================== #
# P05B Stage 3 independent consent-safety reproductions
# =========================================================================== #
def test_qwen_same_sized_corruption_cannot_exceed_confirmed_zero_download(authority_world):
    """Stage 3 B1, migrated to v3 in 4B-3A; original red patch retained in checkpoint evidence.

    Initial corruption now requires repair bytes. Preserve the zero-consent attack
    by corrupting the same-sized file after legitimate zero-byte confirmation.
    """
    b1_zero_consent_control(authority_world)


def test_model_only_repair_cannot_rebuild_an_unconsented_engine(authority_world):
    """A later failed engine probe must stop model-only repair before any package or download action."""
    b2_model_only_control(authority_world)


def test_chatterbox_change_at_lock_cannot_expand_the_confirmed_download(authority_world, monkeypatch):
    """A previously verified weight disappearing at lock acquisition cannot expand a seven-byte plan."""
    chatterbox_race_control(authority_world, monkeypatch)
