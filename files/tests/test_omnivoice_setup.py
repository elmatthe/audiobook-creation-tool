"""v0.8.0 Phase 3 -- OmniVoice as the fifth component of the EXISTING optional-voice installer.

One more component in the same protocol, planner, consent, worker, acquirer and panel -- no second installer. These
tests prove: the five-component contract (the four earlier ones unchanged); honest plans (installed, missing, partial,
unchecked, unfinished, broken, busy, unsupported, unverified, bad bundle); the licence and hardware disclosure before
any consent; consent bound to the plan (stale terms refused, nothing fetched beyond the confirmed budget or outside the
pinned sources, no cross-component installs); the adoption of an existing environment WITHOUT a receipt -- proved,
never rebuilt, never downloaded again, then recorded; repair that moves a broken environment aside and never deletes
what the app did not make; offline failures and cancellation that never claim success; and the first-run window's
fifth checkbox.

Nothing here reaches the internet, runs pip or loads a model. The OmniVoice manifest is a tiny stand-in served by a
loopback hub (``test_qwen3_setup.Hub``); venv, pip and the worker's proof are a fake runner; the repository is the
Qwen3 runtime sandbox (``test_optional_tts_setup.world``); the GPU is a caller fact. Every test is refused, at the write
itself, any write to the real installation (``production_writes_refused``).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
from pathlib import Path

import pytest

from shared import optional_setup_client as client
from shared import optional_setup_protocol as proto
from shared import venv_layout
from tts import model_assets as assets
from tts import omnivoice_runtime as ov
from tts import omnivoice_setup as ovs
from tts import omnivoice_worker as ow
from tts import optional_setup as osu
from tts import optional_setup_acquire as osa
from tts import optional_setup_health as osh
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su
from tts import voice_install
from test_optional_tts_setup import (SESSION, K, component, fig, probes_are_explicit, run_main, sandbox,  # noqa: F401
                                     tiny_assets, tripwire, unit, world)
from test_qwen3_setup import Hub, no_sleep, opener

pytestmark = pytest.mark.usefixtures("production_writes_refused")

REPO = Path(__file__).resolve().parents[2]
OV = proto.OMNIVOICE
ENGINE, MODEL = osu.OMNIVOICE_ENGINE_UNIT, osu.OMNIVOICE_MODEL_UNIT
PINS = (("omnivoice", "0.2.1"), ("torch", "2.8.0+cu128"), ("huggingface-hub", "1.7.2"))
WHEELS = {f"{n.replace('-', '_')}-{v}-py3-none-any.whl": f"wheel {n}=={v};".encode() * 4 for n, v in PINS}
MODEL_FILES = {"config.json": b'{"model": 1}', "audio_tokenizer/config.json": b'{"tokenizer": 2}',
               "model.safetensors": b"w" * 64, "README.md": b"License: CC-BY-NC"}
WHEEL_BYTES = sum(len(b) for b in WHEELS.values())
MODEL_BYTES = sum(len(b) for b in MODEL_FILES.values())
ENV_BYTES = 5_000  # the stand-in for the measured environment size
MARGIN = osu.OMNIVOICE_DISK_MARGIN_BYTES


# --------------------------------------------------------------------------- #
# The sandbox: a tiny OmniVoice manifest on a loopback hub, a fake runner, and a base Python outside the app
# --------------------------------------------------------------------------- #
def make_env(folder: Path, base: Path, pins=PINS) -> None:
    """A stand-in environment: the layout ``omnivoice_runtime`` reads (pyvenv.cfg, interpreter, dist-info listing)."""
    (folder / "Scripts").mkdir(parents=True, exist_ok=True)
    (folder / "Scripts" / "python.exe").write_bytes(b"venv launcher")
    (folder / "pyvenv.cfg").write_text(
        f"home = {base.parent}\ninclude-system-site-packages = false\nversion = 3.12.10\nexecutable = {base}\n"
        f"command = {base} -m venv {folder}\n", encoding="utf-8")
    site = ov.site_packages(folder)
    site.mkdir(parents=True, exist_ok=True)
    for name, version in pins:
        (site / f"{name.replace('-', '_')}-{version}.dist-info").mkdir(exist_ok=True)


class FakeRunner:
    """The base-interpreter check, ``python -m venv``, offline pip and the worker's ``probe`` job, faked.

    pip installs exactly the lock it is handed (a dist-info per line); the probe answers as configured. ``hang``
    ("pip" or "probe") waits for the cancel; ``sac`` makes the next probes fail the way Smart App Control does."""

    def __init__(self, base: Path):
        self.base = base
        self.commands: list[list[str]] = []
        self.probe_jobs: list[dict] = []
        self.probe_failure: tuple[str, str] | None = None
        self.fail_pip = False
        self.hang: str | None = None
        self.sac = 0

    def _wait_for_cancel(self, cancel_check) -> None:
        deadline = time.monotonic() + 10
        while not cancel_check():
            assert time.monotonic() < deadline, "never cancelled"
            time.sleep(0.01)
        raise su.SetupCancelled()

    def kinds(self) -> list[str]:
        out = []
        for cmd in self.commands:
            out.append("venv" if cmd[1:4] == ["-I", "-m", "venv"] else "pip" if ovs.OFFLINE_PIP in cmd else "probe")
        return out

    def __call__(self, cmd, *, env, cwd, on_line, cancel_check=None):
        cmd = [str(c) for c in cmd]
        if cmd[1:3] == ["-I", "-c"] and ovs._BASE_PROBE_MARK in cmd[3]:
            on_line(ovs._BASE_PROBE_MARK + json.dumps({
                "version": [3, 12, 10], "implementation": "cpython", "prefix": str(Path(cmd[0]).parent),
                "base_prefix": str(Path(cmd[0]).parent), "executable": cmd[0]}))
            return 0
        self.commands.append(cmd)
        if cmd[1:4] == ["-I", "-m", "venv"]:
            make_env(Path(cmd[4]), Path(cmd[0]), pins=())
            return 0
        if ovs.OFFLINE_PIP in cmd:
            assert "--no-index" in cmd and "--require-hashes" in cmd and "--no-deps" in cmd and "--only-binary=:all:" in cmd
            if self.hang == "pip":
                self._wait_for_cancel(cancel_check)
            if self.fail_pip:
                on_line("ERROR: THESE PACKAGES DO NOT MATCH THE HASHES")
                return 1
            env_dir = Path(cmd[0]).parents[1]
            for line in Path(cmd[cmd.index("-r") + 1]).read_text(encoding="utf-8").splitlines():
                name, version = line.split(" ", 1)[0].split("==")
                (ov.site_packages(env_dir) / f"{name.replace('-', '_')}-{version}.dist-info").mkdir()
            return 0
        assert cmd[1] == "-I" and cmd[2] == str(ov.worker_script()), cmd
        job = json.loads(Path(cmd[3]).read_text(encoding="utf-8"))
        assert ow.job_problems(job, {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}) == [], job
        assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1"
        self.probe_jobs.append(job)
        if self.hang == "probe":
            self._wait_for_cancel(cancel_check)
        if self.sac:
            self.sac -= 1
            on_line("@@EVENT " + json.dumps({"event": "failed", "stage": "import", "message":
                                             "ImportError: DLL load failed: An Application Control policy has "
                                             "blocked this file."}))
            return 2
        if self.probe_failure:
            stage, message = self.probe_failure
            on_line("@@EVENT " + json.dumps({"event": "failed", "stage": stage, "message": message}))
            return 2
        on_line("@@EVENT " + json.dumps({"event": "probe", "versions": {"omnivoice": "0.2.1"}, "device_name": "RTX Test",
                                         "total_mib": 12000, "load_s": 1.5, "isolation": "ok",
                                         "network_attempts": 0, "vram_allocated_mib": 2300,
                                         "vram_reserved_mib": 2400}))
        return 0


class FakeGuard:
    held = 0
    refuse = False
    refusal_message = "another copy is using the OmniVoice model"

    def acquire(self) -> bool:
        if FakeGuard.refuse:
            return False
        FakeGuard.held += 1
        return True

    def release(self) -> None:
        pass


class Omni:
    def __init__(self, root: Path, hub: Hub, base: Path, monkeypatch):
        self.root, self.hub, self.base, self.mp = root, hub, base, monkeypatch
        self.runner = FakeRunner(base)

    # -- state ---------------------------------------------------------------------------------------------------
    def env(self, pins=PINS) -> Path:
        make_env(ov.venv_dir(), self.base, pins)
        return ov.venv_dir()

    def model(self, *, without=(), record=True, wrong=()) -> Path:
        for name, data in MODEL_FILES.items():
            if name in without:
                continue
            path = ov.model_dir().joinpath(*name.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes(b ^ 0x1 for b in data) if name in wrong else data)
        if record and not without and not wrong:
            assert ov.verify_model_files() == []
        return ov.model_dir()

    def receipt(self, stage=ov.STAGE_INSTALLED, **fields):
        if stage == ov.STAGE_INSTALLED:
            fields = {"origin": ov.ORIGIN_INSTALLED, "base": venv_layout.base_identity(ov.venv_dir()), "probe": {},
                      "probe_ok": True, **fields}
        return ov.write_receipt(stage, **fields)

    def tree(self, folder: Path) -> dict:
        return {str(p.relative_to(folder)): (p.stat().st_size, p.stat().st_mtime_ns) if p.is_file() else None
                for p in sorted(folder.rglob("*"))} if folder.exists() else {}

    # -- plan, consent, install -----------------------------------------------------------------------------------
    def facts(self, *, gpu=True, busy=(), health=None, **kwargs) -> osu.Facts:
        return osu.Facts(health=health or {}, busy=frozenset(busy), python=(3, 12), is_64bit=True, gpu=gpu,
                         package_version=lambda name: {assets.SPACY_ENGLISH: "3.8.0", "spacy": "3.8.16"}.get(name),
                         **kwargs)

    def plan(self, components=(OV,), **facts) -> dict:
        return osu.plan_to_json(osu.plan(components, facts=self.facts(**facts)))

    def acquirer(self, **kwargs) -> osa.RealAcquirer:
        options = dict(opener=opener, runner=self.runner, disk_free=lambda path: 10**12, sleep=no_sleep)
        options.update(kwargs)
        return osa.RealAcquirer(**options)

    def install(self, components=(OV,), *, plan=None, acq=None, cancel_after=None, **facts) -> tuple[int, dict]:
        shown = plan or self.plan(components, **facts)
        request = proto.new_request(proto.ACTION_INSTALL, components, session=SESSION, consent=osu.consent_for(shown))
        return run_main(self.root, request, facts=self.facts(**facts), acquirer=acq or self.acquirer(),
                        health=lambda c: {K: True} if K in c else {})

    def fetched(self) -> list[str]:
        return [r["path"] for r in self.hub.requests]


@pytest.fixture
def omni(world, tmp_path_factory, monkeypatch):
    files = {f"/wheels/{name}": data for name, data in WHEELS.items()}
    files.update({f"/k2-fsa/OmniVoice/resolve/{'c' * 40}/{name}": data for name, data in MODEL_FILES.items()})
    for pinned in (assets.kokoro_set(),):  # Kokoro's stand-ins, for the two-component installs
        for name, (size, _) in pinned.files.items():
            files[f"/{pinned.repo}/resolve/{pinned.revision}/{name}"] = b"k" * size
    hub = Hub(files)
    base_url = f"http://127.0.0.1:{hub.port}"
    real = json.loads(ov.manifest_path().read_text(encoding="utf-8"))
    manifest = {
        "schema": "act-omnivoice-engine", "version": 1, "engine": {"omnivoice": "0.2.1"},
        "licenses": real["licenses"], "license_documents": real["license_documents"],
        "model": {"repo": "k2-fsa/OmniVoice", "revision": "c" * 40,
                  "url_template": base_url + "/{repo}/resolve/{revision}/{path}",
                  "load_required": ["config.json", "audio_tokenizer/config.json"],
                  "files": {n: {"size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in MODEL_FILES.items()}},
        "packages": [[n, v] for n, v in PINS],
        "wheels": [{"name": n, "version": v, "filename": f, "url": f"{base_url}/wheels/{f}", "size": len(WHEELS[f]),
                    "sha256": hashlib.sha256(WHEELS[f]).hexdigest()}
                   for (n, v), f in zip(PINS, WHEELS)],
        "installed_bytes": {"environment": ENV_BYTES},
    }
    monkeypatch.setattr(ov, "load_manifest", lambda: manifest)
    monkeypatch.setattr(ov, "reference_status", lambda voice: (True, "ok"))
    monkeypatch.setattr(su, "HUB_URL", base_url + "/{repo}/resolve/{revision}/{path}")
    base = tmp_path_factory.mktemp("base-python") / "python.exe"  # outside the sandboxed app folder
    base.write_bytes(b"base interpreter")
    monkeypatch.setattr(ov, "app_base_python", lambda: base)
    monkeypatch.setattr(ov, "MachineGuard", FakeGuard)
    FakeGuard.held, FakeGuard.refuse = 0, False
    yield Omni(world, hub, base, monkeypatch)
    hub.close()


# =========================================================================== #
# A. Component registration
# =========================================================================== #
def test_exactly_five_components_the_four_earlier_unchanged_and_omnivoice_last_and_unchecked():
    assert proto.COMPONENTS == ("kokoro", "chatterbox", "qwen3-customvoice", "qwen3-base", "omnivoice")
    assert proto.COMPONENTS[:4] == (proto.KOKORO, proto.CHATTERBOX, proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE)
    assert proto.OMNIVOICE == ov.COMPONENT == voice_install.component_for("omnivoice", "omnivoice-male-1")
    assert proto.LABELS[OV] == "OmniVoice — Six Cloned Voices"
    assert proto.WIZARD_DEFAULTS == {"kokoro": True, "chatterbox": False, "qwen3-customvoice": False,
                                     "qwen3-base": False, "omnivoice": False}
    from shared import bootstrap

    assert [c for c, *_ in bootstrap.OPTIONAL_CHOICES] == list(proto.COMPONENTS)
    choice = bootstrap.OPTIONAL_CHOICES[-1]
    assert choice[:3] == ("omnivoice", "OmniVoice — Six Cloned Voices", False)
    assert "NVIDIA GPU" in choice[3] and "NON-COMMERCIAL" in choice[3] and "CC-BY-NC" in choice[3]


@pytest.mark.parametrize("components, code", [
    (["OmniVoice"], proto.UNKNOWN_COMPONENT), (["omni-voice"], proto.UNKNOWN_COMPONENT),
    ([OV, OV], proto.DUPLICATE_COMPONENT), (["omnivoice", "omnivoice-engine"], proto.UNKNOWN_COMPONENT),
])
def test_unknown_or_repeated_names_are_refused(components, code):
    with pytest.raises(proto.ProtocolError) as caught:
        proto.canonical_selection(components)
    assert caught.value.code == code


def test_selections_with_omnivoice_are_canonical_and_round_trip_through_the_existing_protocol():
    assert proto.canonical_selection([OV, proto.KOKORO]) == (proto.KOKORO, OV)
    request = proto.new_request(proto.ACTION_PLAN, [OV, proto.QWEN3_BASE], session=SESSION)
    assert request.components == (proto.QWEN3_BASE, OV)
    assert proto.decode_request(proto.encode(request.to_json()), session=SESSION) == request
    assert proto.PROTOCOL_VERSION == 2, "no second protocol: the existing v2 bridge carries the fifth component"


# =========================================================================== #
# B. First-run planning (pre-venv): manifest figures, no heavy imports, the real shipped manifest
# =========================================================================== #
def test_the_shipped_manifest_pins_every_wheel_and_model_file_exactly_as_phase_1_verified_them():
    manifest = json.loads(ov.manifest_path().read_text(encoding="utf-8"))
    assert ov.manifest_problems(manifest) == []
    dev = json.loads((REPO / "files" / "dev-tools" / "omnivoice_p1_manifest.json").read_text(encoding="utf-8"))
    assert [(w["name"], w["version"], w["url"], w["size"], w["sha256"]) for w in manifest["wheels"]] == \
        [(w["name"], w["version"], w["url"], w["size"], w["sha256"]) for w in
         sorted(dev["wheels"], key=lambda w: [p[0] for p in manifest["packages"]].index(w["name"]))]
    assert len(manifest["wheels"]) == 88 and sum(w["size"] for w in manifest["wheels"]) == 3_663_315_198
    files = manifest["model"]["files"]
    assert all(dev["model"]["files"][n]["sha256"] == e["sha256"] for n, e in files.items())
    assert sum(e["size"] for e in files.values()) == 3_267_467_171  # Phase 1's 3,267,470,260 less two .gitattributes
    assert manifest["model"]["url_template"] == ov.HUB_URL_TEMPLATE
    assert all(w["url"].startswith(ov.WHEEL_HOSTS) for w in manifest["wheels"])
    assert "dev-tools" not in json.dumps(manifest), "a customer install never depends on developer-only files"
    assert "annual active users" in manifest["licenses"]["audio_tokenizer"]  # what audio_tokenizer/LICENSE says


def test_the_pre_venv_estimate_is_the_manifest_upper_bound_and_proves_nothing():
    data = osu.plan_to_json(osu.estimate([OV]))
    assert component(data, OV)["readiness"] == proto.UNVERIFIED and data["upper_bound"]
    assert data["acquire_units"] == [ENGINE, MODEL]
    assert data["totals"]["download"] == fig(6_930_782_369, proto.MANIFEST)
    assert data["totals"]["disk"] == fig(ov.engine_installed_bytes() + 3_267_467_171, proto.APPROXIMATE)
    assert data["totals"]["temp"] == fig(3_663_315_198 + MARGIN, proto.MANIFEST)
    assert client.estimate_texts([OV]) == {OV: "6.9 GB"}
    assert data["disclosures"][OV]["summary"] and "checked before anything is downloaded" in data["hardware"]["omnivoice"]


def test_the_pre_venv_estimate_offers_nothing_on_another_platform(monkeypatch):
    monkeypatch.setattr(ov, "platform_supported", lambda: False)
    data = osu.plan_to_json(osu.estimate([OV]))
    assert component(data, OV)["readiness"] == proto.UNSUPPORTED and data["units"] == []
    with pytest.raises(proto.ProtocolError):
        client.consent_for(data)


# =========================================================================== #
# B. Main-context planning against the sandbox
# =========================================================================== #
def test_nothing_installed_plans_the_full_pinned_download_and_disk(omni, tripwire):
    data = omni.plan()
    entry = component(data, OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.MISSING, proto.SCOPE_INSTALL)
    assert data["acquire_units"] == [ENGINE, MODEL]
    assert unit(data, ENGINE)["source"] == osu.omnivoice_engine_source()
    assert unit(data, MODEL)["source"].startswith("hf:k2-fsa/OmniVoice@" + "c" * 40 + "#manifest-sha256:")
    assert data["totals"]["download"] == fig(WHEEL_BYTES + MODEL_BYTES, proto.MANIFEST)
    assert data["totals"]["disk"] == fig(ENV_BYTES + MODEL_BYTES, proto.APPROXIMATE)
    assert data["totals"]["temp"] == fig(WHEEL_BYTES + MARGIN, proto.MANIFEST)
    assert omni.fetched() == [] and tripwire == []


def test_an_installed_and_recorded_omnivoice_downloads_nothing(omni):
    omni.env()
    omni.model()
    omni.receipt()
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.READY and data["acquire_units"] == []
    assert data["totals"]["download"] == fig(0, proto.EXACT) and not client.needs_install(data)
    assert unit(data, MODEL)["reused"] == fig(MODEL_BYTES, proto.EXACT)


def test_a_partial_model_downloads_only_what_is_missing_and_counts_what_is_there(omni):
    omni.env()
    omni.receipt()
    omni.model(without=("model.safetensors",), record=False)
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.MISSING and data["acquire_units"] == [MODEL]
    assert unit(data, MODEL)["download"] == fig(64, proto.MANIFEST)
    assert unit(data, MODEL)["reused"] == fig(MODEL_BYTES - 64, proto.EXACT)


def test_a_complete_but_unrecorded_model_is_only_verified_and_recorded(omni):
    omni.env()
    omni.receipt()
    omni.model(record=False)
    data = omni.plan()
    assert unit(data, MODEL)["state"] == proto.MISSING and unit(data, MODEL)["download"] == fig(0, proto.EXACT)
    assert "nothing is downloaded" in unit(data, MODEL)["note"]
    assert data["totals"]["temp"] == fig(0, proto.EXACT), "no margin when nothing large is written"


def test_a_wrong_model_file_is_damaged_and_replaced_only_under_repair_consent(omni):
    omni.env()
    omni.receipt()
    omni.model(record=False, wrong=("config.json",))
    data = omni.plan()
    entry = component(data, OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)
    assert unit(data, MODEL)["temp"] == fig(len(MODEL_FILES["config.json"]), proto.MANIFEST)


def test_an_existing_environment_without_a_receipt_is_planned_as_an_adoption_that_downloads_nothing(omni):
    omni.env()
    omni.model()
    assert ov.assess_engine().state == ov.ENGINE_UNCHECKED
    data = omni.plan()
    engine = unit(data, ENGINE)
    assert component(data, OV)["readiness"] == proto.MISSING and data["acquire_units"] == [ENGINE]
    assert engine["download"] == fig(0, proto.EXACT) and engine["disk"] == fig(0, proto.EXACT)
    assert engine["reused"] == fig(ENV_BYTES, proto.APPROXIMATE) and engine["note"] == osu.ADOPT_NOTE
    assert data["totals"] == {"download": fig(0, proto.EXACT), "reused": fig(ENV_BYTES, proto.APPROXIMATE),
                              "local_copy": fig(0, proto.EXACT), "disk": fig(0, proto.EXACT),
                              "temp": fig(0, proto.EXACT)}
    text = client.disclosure(data)
    assert "Install - nothing to download" in text and "adopts it" in text


@pytest.mark.parametrize("how, expected", [
    ("wrong-version", "1 at another version: torch"), ("extra", "not part of it: openai-whisper"),
    ("other-python", "another Python than the app's own"), ("not-isolated", "not isolated"),
])
def test_an_environment_that_is_not_the_pinned_one_is_damaged_never_adopted(omni, tmp_path, how, expected):
    if how == "wrong-version":
        omni.env(pins=(PINS[0], ("torch", "2.10.0"), PINS[2]))
    elif how == "extra":
        omni.env(pins=(*PINS, ("openai-whisper", "1.0")))
    elif how == "other-python":
        other = tmp_path / "other" / "python.exe"
        other.parent.mkdir()
        other.write_bytes(b"x")
        make_env(ov.venv_dir(), other)
    else:
        omni.env()
        cfg = ov.venv_dir() / "pyvenv.cfg"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace("= false", "= true"), encoding="utf-8")
    omni.model()
    data = omni.plan()
    entry = component(data, OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)
    assert expected in entry["reason"] and osu.REBUILD_NOTE in entry["reason"]
    assert unit(data, ENGINE)["download"] == fig(WHEEL_BYTES, proto.MANIFEST)


def test_an_unfinished_install_by_this_app_is_damaged_and_says_so(omni):
    omni.env(pins=())
    omni.receipt(ov.STAGE_CREATING, base_python=str(omni.base))
    omni.model()
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.DAMAGED
    assert unit(data, ENGINE)["note"] == osu.UNFINISHED_NOTE


def test_a_receipt_for_another_folder_or_a_changed_base_python_never_vouches(omni):
    omni.env()
    omni.model()
    omni.receipt(path=str(omni.root / "elsewhere"))
    assert ov.read_receipt() == {} and ov.assess_engine().state == ov.ENGINE_UNCHECKED
    omni.receipt()
    assert ov.assess_engine().state == ov.ENGINE_READY
    omni.base.write_bytes(b"base interpreter, upgraded in place")  # its size changes: the base identity changes
    assert ov.assess_engine().state == ov.ENGINE_UNCHECKED, "re-proved (adopted again), never trusted unchanged"


def test_no_gpu_is_unsupported_unchecked_gpu_is_unverified_and_neither_can_be_consented(omni):
    omni.model()
    data = omni.plan(gpu=False)
    entry = component(data, OV)
    assert (entry["readiness"], entry["reason"], data["units"]) == (proto.UNSUPPORTED, ov.NO_GPU_MESSAGE, [])
    assert "cannot be installed here" in data["hardware"]["omnivoice"]
    unchecked = omni.plan(gpu=None)
    assert component(unchecked, OV)["readiness"] == proto.UNVERIFIED and unchecked["acquire_units"] == []
    for shown in (data, unchecked):
        with pytest.raises(proto.ProtocolError) as caught:
            client.consent_for(shown)
        assert caught.value.code == proto.NOT_ACQUIRABLE


def test_another_platform_is_unsupported_and_every_other_voice_still_plans(omni, monkeypatch):
    monkeypatch.setattr(ov, "platform_supported", lambda: False)
    data = omni.plan((K, OV))
    assert component(data, OV)["readiness"] == proto.UNSUPPORTED
    assert component(data, K)["readiness"] in (proto.MISSING, proto.UNVERIFIED)
    assert all(not u["id"].startswith("omnivoice-") for u in data["units"])


def test_busy_locks_and_bad_recordings_are_reported_and_never_acquire(omni, monkeypatch):
    omni.model()
    lock = rt.FileLock(ov.inference_lock_path())
    assert lock.acquire()
    try:
        assert osh.busy_components([OV, K]) == frozenset({OV})
    finally:
        lock.release()
    assert osh.busy_components([OV]) == frozenset()
    data = omni.plan(busy={OV})
    assert component(data, OV)["readiness"] == proto.BUSY and data["acquire_units"] == []
    monkeypatch.setattr(ov, "reference_status", lambda voice: (False, "Setup required for OmniVoice - Male 1"))
    data = omni.plan()
    entry = component(data, OV)
    assert entry["readiness"] == proto.BAD_BUNDLE and "Male 1" in entry["reason"] and data["acquire_units"] == []


def test_links_make_it_unverified_and_nothing_is_written_through_them(omni, tmp_path):
    outside = tmp_path / "outside-env"
    outside.mkdir()
    if sys.platform == "win32":  # a junction needs no privilege, so this never skips on Windows
        import _winapi

        ov.venv_dir().parent.mkdir(parents=True, exist_ok=True)  # .venv/engines, inside the app's own environment
        _winapi.CreateJunction(str(outside), str(ov.venv_dir()))
    else:
        ov.venv_dir().parent.mkdir(parents=True, exist_ok=True)
        os.symlink(outside, ov.venv_dir(), target_is_directory=True)
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.UNVERIFIED and data["acquire_units"] == []
    assert ov.install_would_help() is False
    assert list(outside.iterdir()) == []  # nothing was written through it


def test_the_worker_asks_for_the_gpu_only_when_omnivoice_is_chosen(omni, monkeypatch):
    asked: list = []
    monkeypatch.setattr(ov, "detect_gpu", lambda: asked.append(1))  # None: no GPU found
    facts = osh.facts(omni.root, [OV], probe_hardware=False, cancel_check=lambda: False, health={})
    assert facts.gpu is False and asked == [1]
    monkeypatch.setattr(ov, "detect_gpu", lambda: rt.GpuInfo("RTX Test", 12000))
    assert osh.facts(omni.root, [OV], probe_hardware=False, cancel_check=lambda: False, health={}).gpu is True
    assert osh.facts(omni.root, [K], probe_hardware=False, cancel_check=lambda: False, health={}).gpu is None


def test_a_damaged_model_file_is_never_replaced_without_repair_consent(omni):
    omni.model(record=False, wrong=("config.json",))
    before = omni.tree(ov.model_dir())
    with pytest.raises(ovs.OmniVoiceSetupError, match="needs a repair"):
        ovs.acquire_model(opener=opener, progress=lambda p: None, cancel_check=lambda: False, allow_replace=False)
    assert omni.tree(ov.model_dir()) == before and omni.fetched() == []
    ovs.acquire_model(opener=opener, progress=lambda p: None, cancel_check=lambda: False, allow_replace=True)
    assert ov.model_status() == (True, "ok") and omni.fetched() == [f"/k2-fsa/OmniVoice/resolve/{'c' * 40}/config.json"]


def test_planning_writes_nothing_and_asks_no_process_or_network(omni, tripwire):
    omni.env()
    omni.model(record=False)
    before = omni.tree(omni.root)
    omni.plan()
    osu.plan_to_json(osu.estimate([OV]))
    assert omni.tree(omni.root) == before and tripwire == [] and omni.fetched() == []


def test_omnivoice_with_another_component_counts_each_unit_once(omni):
    data = omni.plan((K, OV), health={K: True})
    assert [c["id"] for c in data["components"] if c["selected"]] == [K, OV]
    omni_units = [u for u in data["acquire_units"] if u.startswith("omnivoice-")]
    assert omni_units == [ENGINE, MODEL] and len(set(data["acquire_units"])) == len(data["acquire_units"])
    assert all(len(u["components"]) == 1 for u in data["units"])


# =========================================================================== #
# C. Consent and the licence disclosure
# =========================================================================== #
def test_the_licence_and_hardware_terms_are_shown_before_any_consent(omni):
    data = omni.plan()
    text = client.disclosure(data)
    for needle in ("Apache-2.0", "CC-BY-NC", "NON-COMMERCIAL", "does not say which version",
                   "does not give you the right to make commercial audiobooks", "Boson Higgs Audio 2",
                   "100,000 annual active users", "improve any other large language model", "Acceptable Use Policy",
                   "unauthorised voice cloning", ov.TOKENIZER_ATTRIBUTION, "NVIDIA", "RTX 5070",
                   "not promised", "huggingface.co/k2-fsa/OmniVoice/blob/c5fdb5ccb189668d56333f77ba2629f4cd7535f4"):
        assert needle in text, needle
    assert "licensed Apache-2.0" in text and "OmniVoice is licensed Apache" not in text, "never the whole engine"
    assert text.index("CC-BY-NC") < text.index("Downloads come only from the pinned sources")
    terms = client.license_disclosure(data)
    assert [d["id"] for d in terms["documents"]] == ["weights", "audio_tokenizer", "code"]


def test_no_licence_block_when_omnivoice_is_ready_or_not_chosen(omni):
    assert client.license_disclosure(omni.plan((K,), health={K: True})) is None
    omni.env()
    omni.model()
    omni.receipt()
    assert client.license_disclosure(omni.plan()) is None


def test_no_download_without_a_valid_consent(omni):
    data = omni.plan()
    plan_request = proto.new_request(proto.ACTION_PLAN, [OV], session=SESSION)
    code, result = run_main(omni.root, plan_request, facts=omni.facts(), acquirer=omni.acquirer())
    assert result["state"] == proto.SUCCEEDED and omni.fetched() == [] and omni.runner.commands == []
    real = osu.consent_for(data)
    forged = [proto.Consent(proto.new_token(), real.plan_context, real.components, real.scopes, real.units,
                            real.unknown_units, real.download_bytes, "0" * 64),  # a fingerprint of no shown plan
              proto.Consent(proto.new_token(), real.plan_context, real.components, real.scopes, (ENGINE,),
                            real.unknown_units, real.download_bytes, real.acquisition_fingerprint)]  # fewer units
    for consent in forged:
        request = proto.new_request(proto.ACTION_INSTALL, [OV], session=SESSION, consent=consent)
        code, result = run_main(omni.root, request, facts=omni.facts(), acquirer=omni.acquirer())
        assert result["state"] == proto.REFUSED, result
    assert omni.fetched() == [] and omni.runner.commands == [] and ov.read_receipt() == {}


def test_a_stale_consent_is_refused_and_nothing_is_fetched(omni):
    shown = omni.plan()
    omni.model(without=("model.safetensors",), record=False)  # the plan's terms change after it was shown
    code, result = omni.install(plan=shown)
    assert result["state"] == proto.REFUSED and result["error"]["code"] == proto.CONSENT_STALE
    assert omni.fetched() == [] and omni.runner.commands == []


def test_a_plan_whose_component_is_not_acquirable_has_no_consent_at_all(omni):
    with pytest.raises(proto.ProtocolError):
        client.consent_for(omni.plan(gpu=None))


def test_the_byte_budget_stops_a_download_larger_than_was_confirmed(omni, monkeypatch):
    shown = omni.plan()
    real = ov.wheel_bytes
    monkeypatch.setattr(ov, "wheel_bytes", lambda: (0, WHEEL_BYTES))  # the plan understates the download ...
    understated = omni.plan()
    monkeypatch.setattr(ov, "wheel_bytes", real)  # ... but the wheels are really missing
    assert understated["totals"]["download"]["bytes"] < shown["totals"]["download"]["bytes"]
    acq = omni.acquirer()
    report = acq.acquire(understated, osu.consent_for(understated), progress=lambda p: None, cancel_check=lambda: False)
    assert not report.completed and "more than" in report.detail
    assert not any(p.startswith("/wheels/") for p in omni.fetched()), "refused before a wheel request was sent"
    assert ov.read_receipt() == {} and not ov.venv_dir().exists()


def test_a_source_the_build_does_not_approve_is_refused_before_anything_happens(omni):
    shown = omni.plan()
    for u in shown["units"]:
        if u["id"] == MODEL:
            u["source"] = "hf:someone/else@" + "d" * 40
    with pytest.raises(osa.AcquisitionRefused):
        omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: None, cancel_check=lambda: False)
    assert omni.fetched() == []


def test_the_scoped_opener_refuses_any_url_outside_the_pinned_files(omni):
    import urllib.request

    pinned = ov.model_url("config.json")
    opener_ = osa.ScopedOpener([pinned])
    for other in (pinned.replace("c" * 40, "main"), pinned.replace("config.json", "pytorch_model.bin")):
        with pytest.raises(osa.AcquisitionRefused):
            opener_(urllib.request.Request(other))
    assert omni.fetched() == []


def test_a_wrong_download_is_never_installed_or_recorded(omni):
    path = f"/wheels/{next(iter(WHEELS))}"
    omni.hub.wrong_bytes.add(path)
    code, result = omni.install()
    assert result["state"] == proto.FAILED and result["error"]["code"] == proto.ACQUISITION_FAILED
    # the corrupt file is refused by its hash; fetching it again would exceed the confirmed bytes, so it stops there
    assert next(iter(WHEELS)) in result["error"]["message"] and "Nothing more was downloaded" in result["error"]["message"]
    assert ov.read_receipt() == {} and not ov.venv_dir().exists() and "pip" not in omni.runner.kinds()
    assert not (ov.wheel_cache_dir() / next(iter(WHEELS))).exists(), "a file that failed its hash is never kept"


def test_an_omnivoice_only_consent_changes_nothing_of_any_other_component(omni):
    qwen_state = rt.state_path()
    code, result = omni.install()
    assert result["state"] == proto.SUCCEEDED, result
    paths = omni.fetched()
    assert paths and all(p.startswith(("/wheels/", "/k2-fsa/OmniVoice/")) for p in paths)
    assert not assets.snapshot_dir(assets.kokoro_set()).exists() and not qwen_state.exists()
    assert not rt.nested_venv_dir().exists() and not (omni.root / ".venv-qwen3").exists()


def test_a_kokoro_only_consent_never_touches_omnivoice(omni):
    code, result = omni.install((K,), health={K: True})
    assert result["state"] == proto.SUCCEEDED, result
    assert not any(p.startswith(("/wheels/", "/k2-fsa/")) for p in omni.fetched())
    assert not ov.venv_dir().exists() and not ov.receipt_path().exists() and not ov.model_dir().exists()


# =========================================================================== #
# C/9. New installation, repeat launch, offline, interruption
# =========================================================================== #
def test_a_fresh_install_fetches_the_pinned_files_builds_offline_proves_and_only_then_records(omni):
    code, result = omni.install()
    assert result["state"] == proto.SUCCEEDED and result["verified"] == [OV], result
    assert sorted(omni.fetched()) == sorted([f"/wheels/{n}" for n in WHEELS] +
                                            [f"/k2-fsa/OmniVoice/resolve/{'c' * 40}/{n}" for n in MODEL_FILES])
    assert omni.runner.kinds() == ["venv", "pip", "probe"]
    receipt = ov.read_receipt()
    assert receipt["stage"] == ov.STAGE_INSTALLED and receipt["origin"] == ov.ORIGIN_INSTALLED
    assert receipt["probe_ok"] is True and receipt["packages_sha256"] == ov.packages_sha256()
    assert ov.environment_status() == (True, "ok") and ov.model_status() == (True, "ok")
    assert not any((ov.wheel_cache_dir() / n).exists() for n in WHEELS), "the wheels' space is given back"
    job = omni.runner.probe_jobs[0]
    assert job["kind"] == "probe" and job["device"] == "cuda" and job["model_dir"] == str(ov.model_dir())
    assert FakeGuard.held == 1, "the proof takes the machine-wide model guard"


def test_relaunching_after_an_install_downloads_and_runs_nothing(omni):
    omni.install()
    requests, commands = len(omni.hub.requests), len(omni.runner.commands)
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.READY and data["totals"]["download"] == fig(0, proto.EXACT)
    assert len(omni.hub.requests) == requests and len(omni.runner.commands) == commands


def test_omnivoice_and_kokoro_install_together_each_once(omni):
    code, result = omni.install((K, OV), health={K: True})
    assert result["state"] == proto.SUCCEEDED and result["verified"] == [K, OV], result
    paths = omni.fetched()
    assert len(paths) == len(set(paths)), "no file fetched twice"
    assert ov.environment_status()[0] and assets.snapshot_dir(assets.kokoro_set()).is_dir()


def test_offline_the_install_fails_cleanly_keeps_nothing_half_done_and_claims_nothing(omni, monkeypatch):
    def offline(request):
        raise urllib.error.URLError("[WinError 10051] A socket operation was attempted to an unreachable network")

    code, result = omni.install(acq=omni.acquirer(opener=offline))
    assert result["state"] == proto.FAILED and result["verified"] == []
    assert "unreachable network" in result["error"]["message"] or "Could not download" in result["error"]["message"]
    assert ov.read_receipt() == {} and not ov.venv_dir().exists() and omni.runner.commands == []
    assert component(omni.plan(), OV)["readiness"] == proto.MISSING, "a later consented attempt can resume"


def test_a_cancel_during_a_download_is_cancelled_keeps_verified_files_and_the_retry_fetches_them_once(
        omni, monkeypatch):
    monkeypatch.setattr(su, "DOWNLOAD_BLOCK", 4)  # several reads per file: the cancel really lands mid-file
    cancel = threading.Event()

    def watch(payload):
        if "model.safetensors" in str(payload.get("message")):
            cancel.set()

    acq = omni.acquirer()
    shown = omni.plan()
    report = acq.acquire(shown, osu.consent_for(shown), progress=watch, cancel_check=cancel.is_set)
    assert not report.completed and report.detail == "cancelled"
    assert ov.read_receipt() == {} and not ov.venv_dir().exists() and not ov.model_status()[0]
    completed = {p for p in omni.fetched() if not p.endswith("model.safetensors")}
    before = len(omni.hub.requests)
    code, result = omni.install()
    assert result["state"] == proto.SUCCEEDED, result
    again = [r["path"] for r in omni.hub.requests[before:]]
    assert not set(again) & completed, "a file verified before the cancel is never fetched again"
    resumed = [r for r in omni.hub.requests[before:] if r["path"].endswith("model.safetensors")]
    assert resumed and resumed[0]["range"], "the interrupted file resumes from its kept .part"


def test_a_cancel_during_pip_leaves_an_unfinished_environment_that_a_repair_finishes_without_downloading(omni):
    omni.runner.hang = "pip"
    cancel = threading.Event()
    acq = omni.acquirer()
    shown = omni.plan()
    timer = threading.Timer(0.3, cancel.set)
    timer.start()
    report = acq.acquire(shown, osu.consent_for(shown), progress=lambda p: None, cancel_check=cancel.is_set)
    timer.cancel()
    assert not report.completed and report.detail == "cancelled"
    assert ov.read_receipt()["stage"] == ov.STAGE_CREATING and not ov.environment_status()[0]
    data = omni.plan()
    assert component(data, OV)["readiness"] == proto.DAMAGED and unit(data, ENGINE)["note"] == osu.UNFINISHED_NOTE
    assert unit(data, ENGINE)["download"] == fig(0, proto.MANIFEST), "the verified wheels were kept"
    omni.runner.hang = None
    fetched = len(omni.hub.requests)
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED, result
    assert len(omni.hub.requests) == fetched, "nothing downloaded twice"
    assert not ov.set_aside_root().exists(), "an environment this app left unfinished is removed, not set aside"


def test_a_cancel_during_the_proof_records_nothing(omni):
    omni.env()
    omni.model()
    omni.runner.hang = "probe"
    cancel = threading.Event()
    timer = threading.Timer(0.3, cancel.set)
    timer.start()
    shown = omni.plan()
    report = omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: None,
                                     cancel_check=cancel.is_set)
    timer.cancel()
    assert not report.completed and ov.read_receipt() == {} and ov.assess_engine().state == ov.ENGINE_UNCHECKED


# =========================================================================== #
# D. Adopting an existing installation
# =========================================================================== #
def test_a_healthy_unreceipted_environment_is_adopted_without_downloading_rebuilding_or_changing_it(omni, tripwire):
    omni.env()
    omni.model()
    env_before, model_before = omni.tree(ov.venv_dir()), omni.tree(ov.model_dir())
    code, result = omni.install()
    assert result["state"] == proto.SUCCEEDED and result["verified"] == [OV], result
    assert omni.fetched() == [], "nothing downloaded"
    assert omni.runner.kinds() == ["probe"], "no venv, no pip: only the proof"
    assert omni.tree(ov.venv_dir()) == env_before and omni.tree(ov.model_dir()) == model_before
    receipt = ov.read_receipt()
    assert receipt["origin"] == ov.ORIGIN_ADOPTED and receipt["base"] == venv_layout.base_identity(ov.venv_dir())
    assert ov.environment_status() == (True, "ok")
    assert not ov.set_aside_root().exists() and not ov.wheel_cache_dir().exists()


def test_a_genuinely_broken_unreceipted_environment_is_not_adopted_and_a_repair_is_offered_then_kept(omni):
    omni.env()
    omni.model()
    omni.runner.probe_failure = ("import", "ImportError: DLL load failed while importing _C")
    code, result = omni.install()
    assert result["state"] == proto.FAILED and "DLL load failed" in result["error"]["message"]
    assert ov.read_receipt()["stage"] == ov.STAGE_REJECTED and ov.venv_dir().is_dir()
    data = omni.plan()
    entry = component(data, OV)
    assert (entry["readiness"], entry["consent_scope"]) == (proto.DAMAGED, proto.SCOPE_REPAIR)
    assert "checked and does not work" in entry["reason"]
    old = omni.tree(ov.venv_dir())
    omni.runner.probe_failure = None
    code, result = omni.install(plan=data)
    assert result["state"] == proto.SUCCEEDED, result
    (moved,) = list(ov.set_aside_root().iterdir())
    assert omni.tree(moved) == old, "the old environment is kept whole, never deleted"
    assert ov.read_receipt()["origin"] == ov.ORIGIN_INSTALLED


@pytest.mark.parametrize("stage", ["gpu", "load", "timeout"])
def test_a_gpu_memory_or_time_failure_rejects_nothing(omni, stage):
    omni.env()
    omni.model()
    omni.runner.probe_failure = (stage, "PyTorch reports no usable CUDA GPU")
    code, result = omni.install()
    assert result["state"] == proto.FAILED
    assert ov.read_receipt() == {} and ov.assess_engine().state == ov.ENGINE_UNCHECKED
    assert component(omni.plan(), OV)["readiness"] == proto.MISSING, "still adoptable, nothing to repair"


def test_smart_app_control_first_loads_are_retried_and_never_reject(omni):
    omni.env()
    omni.model()
    omni.runner.sac = 2
    code, result = omni.install()
    assert result["state"] == proto.SUCCEEDED and omni.runner.kinds() == ["probe", "probe", "probe"]
    omni.runner.sac = ovs.APPLICATION_CONTROL_ATTEMPTS
    ov.clear_receipt()
    code, result = omni.install()
    assert result["state"] == proto.FAILED and ov.read_receipt() == {}, "a policy refusal says nothing against the env"


def test_a_busy_model_guard_fails_the_proof_without_rejecting(omni):
    omni.env()
    omni.model()
    FakeGuard.refuse = True
    code, result = omni.install()
    assert result["state"] == proto.FAILED and "another copy" in result["error"]["message"]
    assert ov.read_receipt() == {}


def test_an_engine_that_changed_after_the_plan_is_refused_and_unchanged(omni):
    omni.env()
    omni.model()
    shown = omni.plan()  # an adoption
    import shutil

    shutil.rmtree(ov.venv_dir())  # gone before the install runs: no silent fresh build under an adoption's consent
    report = omni.acquirer().acquire(shown, osu.consent_for(shown), progress=lambda p: None, cancel_check=lambda: False)
    assert not report.completed and "changed after the plan was shown" in report.detail
    assert omni.fetched() == [] and omni.runner.commands == []


def test_only_an_environment_this_app_left_unfinished_is_ever_removed(omni):
    omni.env()
    with pytest.raises(ovs.OmniVoiceSetupError):
        ovs.remove_unfinished_engine()
    assert ov.venv_dir().is_dir()
    omni.receipt(ov.STAGE_CREATING, base_python=str(omni.base))
    ovs.remove_unfinished_engine()
    assert not ov.venv_dir().exists()


def test_installs_are_refused_while_omnivoice_is_converting_or_another_install_runs(omni):
    for path in (ov.inference_lock_path(), rt.setup_lock_path()):
        held = rt.FileLock(path)
        assert held.acquire()
        try:
            with pytest.raises(ovs.OmniVoiceSetupError):
                ovs.InstallLock().acquire()
        finally:
            held.release()
    with ovs.InstallLock():
        pass


# =========================================================================== #
# E. The worker's proof job, and the voice-level answers
# =========================================================================== #
def test_the_probe_job_is_checked_before_anything_heavy_and_names_its_failures(tmp_path):
    model = tmp_path / "model"
    (model / "audio_tokenizer").mkdir(parents=True)
    (model / "config.json").write_text("{}")
    (model / "audio_tokenizer" / "config.json").write_text("{}")
    job = {"schema": 1, "kind": "probe", "model_dir": str(model), "omnivoice_version": "0.2.1", "dtype": "float16",
           "device": "cuda", "engine_lock": str(tmp_path / "engine.lock"), "packages": {"torch": "2.8.0+cu128"},
           "environment": str(tmp_path), "foreign": []}
    offline = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    assert ow.job_problems(job, offline) == []
    assert any("GPU only" in p for p in ow.job_problems({**job, "device": "cpu"}, offline))
    assert any("HF_HUB_OFFLINE" in p for p in ow.job_problems(job, {}))
    assert any("missing" in p for p in ow.job_problems({"schema": 1, "kind": "probe"}, offline))
    assert ow.version_problems({"pytest": "0.0.0-not"}) == ["pytest is " + __import__("pytest").__version__ +
                                                            ", not 0.0.0-not"]
    problems = ow.isolation_problems({"environment": str(tmp_path / "elsewhere"), "foreign": [sys.prefix]})
    assert any("sys.prefix is not" in p for p in problems) and any("another environment" in p for p in problems)
    assert ovs.DAMAGING_STAGES == {"versions", "isolation", "import"}


def test_install_and_continue_is_offered_for_an_unchecked_engine_and_not_for_a_bad_recording(omni, monkeypatch):
    omni.env()
    omni.model()
    monkeypatch.setattr(ov, "detect_gpu", lambda: rt.GpuInfo("RTX Test", 12000))
    assert ov.voice_availability("omnivoice-male-1")[1] == ov.UNCHECKED_MESSAGE
    assert voice_install.installable("omnivoice", "omnivoice-male-1", ov.UNCHECKED_MESSAGE) == OV
    monkeypatch.setattr(ov, "reference_status", lambda voice: (voice.voice_id != "omnivoice-male-1", "changed"))
    assert voice_install.installable("omnivoice", "omnivoice-male-1", "changed") is None
    assert voice_install.installable("omnivoice", "omnivoice-male-2", ov.UNCHECKED_MESSAGE) == OV
    monkeypatch.setattr(ov, "detect_gpu", lambda: None)
    assert voice_install.installable("omnivoice", "omnivoice-male-2", ov.NO_GPU_MESSAGE) is None


def test_a_successful_install_makes_the_voices_ready_for_the_existing_status_seam(omni, monkeypatch):
    monkeypatch.setattr(ov, "detect_gpu", lambda: rt.GpuInfo("RTX Test", 12000))
    assert not ov.voice_availability("omnivoice-female-1")[0]
    omni.install()
    assert ov.voice_availability("omnivoice-female-1") == (True, "ok")
    assert voice_install.installable("omnivoice", "omnivoice-female-1", "x") is None


# =========================================================================== #
# E. The panel and the first-run window
# =========================================================================== #
tk = pytest.importorskip("tkinter")
from test_setup_log_follow import native_theme, run_as_toplevel, settle, setup_log, tk_root  # noqa: E402,F401


def _pump(widget, condition, what: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        settle(widget.winfo_toplevel())
        if condition():
            return
        time.sleep(0.01)
    pytest.fail(f"never happened: {what}")


def test_the_review_shows_the_terms_and_reading_them_is_never_a_consent(omni, tk_root):
    from shared.optional_setup_panel import OptionalSetupPanel

    data = omni.plan()
    installs, opened, outcome = [], [], []
    top = tk.Toplevel(tk_root)
    try:
        panel = OptionalSetupPanel(top, omni.root, [OV], on_done=outcome.append,
                                   run_plan=lambda *a, **k: {"state": proto.SUCCEEDED, "plan": data},
                                   run_install=lambda *a, **k: installs.append(a) or {}, open_url=opened.append)
        panel.pack(fill="both", expand=True)
        panel.start()
        _pump(panel, lambda: panel.state == "review", "the review")
        labels = [b.cget("text") for b in panel.buttons.winfo_children()]
        assert labels == ["Install Selected Components", "Skip", "View licence terms"]  # packed right to left
        shown = panel.text.get("1.0", "end")
        assert "CC-BY-NC" in shown and "100,000 annual active users" in shown
        panel.show_terms()
        settle(top)
        window = panel.terms_window
        buttons = [w for w in _descendants(window) if isinstance(w, tk.ttk.Button)]
        opens = [b for b in buttons if b.cget("text") == "Open"]
        assert len(opens) == 3
        for button in opens:
            button.invoke()
        assert opened == [d["url"] for d in reversed(client.license_disclosure(data)["documents"])] or \
            sorted(opened) == sorted(d["url"] for d in client.license_disclosure(data)["documents"])
        assert installs == [] and outcome == [], "reading the terms installs nothing and settles nothing"
        next(b for b in buttons if b.cget("text") == "Close").invoke()
        assert panel.terms_window is None
    finally:
        top.destroy()


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def test_the_first_run_window_shows_five_choices_omnivoice_last_unchecked_and_fits(
        monkeypatch, tk_root, setup_log, native_theme):
    from shared import bootstrap

    seen: dict = {}

    def script(window):
        settle(window)
        checks = [w for w in _descendants(window) if isinstance(w, tk.ttk.Checkbutton)]
        seen["labels"] = [c.cget("text") for c in checks]
        seen["values"] = [bool(window.getvar(c.cget("variable"))) for c in checks]
        begin = next(w for w in _descendants(window) if isinstance(w, tk.ttk.Button) and w.cget("text") == "Begin Setup")
        seen["fits"] = (begin.winfo_y() + begin.winfo_height() <= begin.master.winfo_height()
                        and begin.winfo_rooty() + begin.winfo_height() <= window.winfo_rooty() + window.winfo_height())
        notes = [w for w in _descendants(window) if isinstance(w, tk.ttk.Label) and "NON-COMMERCIAL" in w.cget("text")]
        seen["note_inside"] = bool(notes) and all(
            n.winfo_rooty() + n.winfo_height() <= window.winfo_rooty() + window.winfo_height() for n in notes)
        window.destroy()

    run_as_toplevel(monkeypatch, tk_root, script)
    monkeypatch.setattr(bootstrap, "optional_estimates", lambda: {"omnivoice": "6.9 GB"})
    monkeypatch.setattr(bootstrap, "run_setup", lambda *a, **k: pytest.fail("Cancel started setup"))
    bootstrap.run_with_gui()
    assert seen["labels"][:4] == ["Kokoro voices", "Chatterbox Turbo voices", "Qwen3 CustomVoice voices (Aiden, Ryan)",
                                  "Qwen3 Cloned Voices (six bundled voices)"]
    assert seen["labels"][4] == "OmniVoice — Six Cloned Voices (up to 6.9 GB)" and len(seen["labels"]) == 5
    assert seen["values"] == [True, False, False, False, False]
    assert seen["fits"] and seen["note_inside"], "the fifth choice and Begin Setup fit inside the window"
