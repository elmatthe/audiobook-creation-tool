"""v0.7.0 P05A/P05B Stage 1 — optional voice setup: the planning contract, honest sizes, the worker protocol and its
execution home; consent bound to the plan shown, worker containment, fail-closed results and the operation lifecycle.

Plan Revision 2 §5.4 (Q14-Q20, Q32). Everything runs offline. The planner is driven against the Qwen3 runtime sandbox
(``test_qwen3_runtime.sandbox``: a fake repository root with a tiny model manifest) plus a fake in-tree Hugging Face
cache and tiny stand-ins for the measured Kokoro/Chatterbox tables. Network and process creation are tripwired in
process; the real worker is also run as a child process inside a disposable copy of the app, in a pip-less venv built
from the base CPython 3.12, whose ``sitecustomize`` aborts on any socket or process event and records what was imported.
No real model, cache, environment or state file is written.
"""

from __future__ import annotations

import dataclasses
import errno
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from shared import optional_setup_protocol as proto
from shared import venv_layout
from tts import model_assets as assets
from tts import optional_setup as osu
from tts import optional_setup_health as osh
from tts import optional_setup_lifecycle as osl
from tts import optional_setup_worker as worker
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su
from test_qwen3_runtime import install_environment, install_model, make_engine, sandbox  # noqa: F401

#: P05B Stage 2 (Task A): every test here is refused, at the write itself, any write to the real installation.
pytestmark = pytest.mark.usefixtures("production_writes_refused")


def test_disappearing_lock_is_never_created_by_read_only_probe(world, monkeypatch):
    """The lock exists at the initial check, then disappears immediately before the open."""
    path = rt.setup_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    real_open = os.open

    def disappeared(target, flags, *args, **kwargs):
        if Path(target) == path:
            path.unlink()
        return real_open(target, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", disappeared)
    assert osh.lock_held(path) is None
    assert not path.exists()


def test_stage2_survivor_is_not_equivalent_when_the_lock_disappears(world, monkeypatch):
    """An O_CREAT mutant creates the missing lock under the same deterministic race."""
    import inspect

    source = inspect.getsource(osh.lock_held)
    assert "os.O_RDWR)" in source
    namespace = dict(osh.__dict__)
    mutant = source.replace("os.O_RDWR)", "os.O_RDWR | os.O_CREAT)")
    exec(compile(mutant, "<M20-lock-disappears>", "exec"), namespace)
    path = rt.setup_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    real_open = os.open

    def disappeared(target, flags, *args, **kwargs):
        if Path(target) == path:
            path.unlink()
        return real_open(target, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", disappeared)
    assert namespace["lock_held"](path) is False
    assert path.exists(), "M20 must be detected because its read-only probe creates a replacement lock"

REPO = Path(__file__).resolve().parents[2]
ALL = proto.COMPONENTS
K, C, CV, B = proto.KOKORO, proto.CHATTERBOX, proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE
#: The sandbox manifest (test_qwen3_runtime): CustomVoice 58 bytes, Base 62, of which 39 are identical in both.
CV_BYTES, BASE_BYTES, SHARED_BYTES = 58, 62, 39
#: v0.7.0: the engine's download is the exact wheel set -- in the sandbox, the two tiny served wheels.
from test_qwen3_runtime import TINY_WHEELS  # noqa: E402
ENV_DOWNLOAD, ENV_INSTALLED, MARGIN = sum(len(d) for d in TINY_WHEELS.values()), 5_300_000_000, 2 * 10**9


# --------------------------------------------------------------------------- #
# Tripwires and fixtures
# --------------------------------------------------------------------------- #
class TripwireError(AssertionError):
    pass


@pytest.fixture
def tripwire(monkeypatch):
    """Any socket, name lookup, process start or shell call fails the test, naming itself."""
    calls: list[str] = []

    def trip(name):
        def refuse(*args, **kwargs):
            calls.append(name)
            raise TripwireError(f"tripwire: {name}")
        return refuse

    monkeypatch.setattr(socket.socket, "connect", trip("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", trip("socket.connect_ex"))
    monkeypatch.setattr(socket, "getaddrinfo", trip("socket.getaddrinfo"))
    monkeypatch.setattr(socket, "create_connection", trip("socket.create_connection"))
    monkeypatch.setattr(subprocess, "Popen", trip("subprocess.Popen"))
    monkeypatch.setattr(os, "system", trip("os.system"))
    return calls


def pin(size: int, fill: bytes = b"k") -> tuple[int, str]:
    """A pinned identity for a stand-in file of *size* bytes of *fill*."""
    return size, hashlib.sha256(fill * size).hexdigest()


#: The stand-in spaCy wheel: 13 bytes of "w".
WHEEL = b"w" * 13


@pytest.fixture
def tiny_assets(monkeypatch):
    """Tiny stand-ins for the pinned upstream tables (``tts.model_assets``), so a 'model' is a few bytes of b"k"."""
    monkeypatch.setattr(assets, "KOKORO_FILES", {"config.json": pin(4), "kokoro-v1_0.pth": pin(40),
                                                 **{assets.kokoro_voice_name(v): pin(5) for v in osu.kokoro_roster()}})
    monkeypatch.setattr(assets, "CHATTERBOX_FILES", {"t3_turbo_v1.safetensors": pin(300),
                                                     "s3gen_meanflow.safetensors": pin(100), "vocab.json": pin(7)})
    monkeypatch.setattr(assets, "SPACY_WHEEL_SIZE", len(WHEEL))
    monkeypatch.setattr(assets, "SPACY_WHEEL_SHA256", hashlib.sha256(WHEEL).hexdigest())
    monkeypatch.setattr(osu, "SPACY_ENGLISH_INSTALLED_BYTES", 11)
    monkeypatch.setattr(osu, "BASE_PACKAGES_INSTALLED_BYTES", 1000)


@pytest.fixture(autouse=True)
def probes_are_explicit(monkeypatch):
    """No in-process test here runs a real engine probe: unless a test supplies its own facts or proof, the worker's
    Kokoro/Chatterbox health is "not proved" (as in Stage 1), and every probe asked for is recorded."""
    asked: list[tuple] = []

    def unproved(root, components, **kwargs):
        asked.append(tuple(components))
        return {}

    monkeypatch.setattr(osh, "local_health", unproved)
    return asked


KOKORO_ALL = 44 + 5 * 9  # model + nine roster voices
SPACY_WHEEL = len(WHEEL)
CHATTERBOX_ALL = 407  # the three stand-in files Turbo loads (no s3gen.safetensors: never acquired)


@pytest.fixture
def world(sandbox, tiny_assets, monkeypatch):  # noqa: F811 - pytest fixture injection
    """The sandbox with the bundled references and transcript bundle reported intact (their own tests prove those),
    and a stand-in hash-locked Qwen3 requirements file, so the engine has a pinned source."""
    monkeypatch.setattr(rt, "reference_status", lambda voice: (True, "ok"))
    monkeypatch.setattr(rt, "bundle_status", lambda: (True, "ok"))
    (sandbox / "scripts" / "qwen3-requirements.txt").write_text("tiny==1.0 --hash=sha256:" + "0" * 64 + "\n",
                                                               encoding="utf-8")
    return sandbox


def versions(*, spacy_model=None, spacy="3.8.16"):
    return lambda name: {assets.SPACY_ENGLISH: spacy_model, "spacy": spacy}.get(name)


def facts(*, health=None, busy=(), spacy=False, python=(3, 12), is_64bit=True, probe=False,
          spacy_version="3.8.16") -> osu.Facts:
    return osu.Facts(health=health or {}, busy=frozenset(busy), python=python, is_64bit=is_64bit,
                     probe_hardware=probe,
                     package_version=versions(spacy_model="3.8.0" if spacy else None, spacy=spacy_version))


HEALTHY = {K: True, C: True}


def hf_snapshot(root: Path, files: assets.AssetSet, *, without=()) -> Path:
    """The pinned files of *files* in the sandbox's cache, in the pinned commit's folder (b"k" * size each)."""
    assert rt.repo_root() == root  # never anywhere but the sandbox
    snapshot = assets.snapshot_dir(files)
    for name, (size, _) in files.files.items():
        if name in without:
            continue
        path = snapshot.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"k" * size)
    return snapshot


def install_kokoro(root: Path, *, without=()) -> Path:
    return hf_snapshot(root, assets.kokoro_set(), without=without)


def install_chatterbox(root: Path, *, without=()) -> Path:
    return hf_snapshot(root, assets.chatterbox_set(), without=without)


def as_json(components, **kwargs) -> dict:
    return osu.plan_to_json(osu.plan(components, facts=facts(**kwargs)))


def component(data: dict, name: str) -> dict:
    return next(c for c in data["components"] if c["id"] == name)


def unit(data: dict, unit_id: str) -> dict:
    return next(u for u in data["units"] if u["id"] == unit_id)


def fig(nbytes, basis) -> dict:
    return {"bytes": nbytes, "basis": basis}


# --------------------------------------------------------------------------- #
# Task A — the component contract
# --------------------------------------------------------------------------- #
def test_the_four_components_their_order_labels_and_approved_defaults():
    assert proto.COMPONENTS == ("kokoro", "chatterbox", "qwen3-customvoice", "qwen3-base")
    assert [proto.LABELS[c] for c in ALL] == ["Kokoro", "Chatterbox Turbo", "Qwen3 CustomVoice",
                                              "Qwen3 Cloned Voices / Base"]
    assert proto.WIZARD_DEFAULTS == {K: True, C: False, CV: False, B: False}
    assert tuple(proto.QWEN3_MODEL_KEYS.values()) == rt.MODEL_KEYS  # the runtime's own model keys, not new ones


def test_constants_repeated_for_the_pre_venv_path_agree_with_their_authorities():
    from shared import bootstrap

    assert osu.QWEN3_DISK_MARGIN_BYTES == su.DISK_MARGIN_BYTES
    assert proto.MAIN_PYTHON == su.SUPPORTED_PYTHON
    assert osu.hf_hub_root() == rt.repo_root() / Path(bootstrap.RESOURCES_DIR, "models", "huggingface", "hub") \
        .relative_to(bootstrap.REPO_ROOT)
    assert {assets.kokoro_voice_name(v) for v in osu.kokoro_roster()} <= set(assets.KOKORO_FILES), \
        "every roster voice needs a pinned identity"
    assert len(osu.kokoro_roster()) == 9


def test_readiness_precedence_never_turns_unknown_into_healthy_or_installable():
    order = proto.READINESS
    assert order == ("unsupported", "bad-bundle", "busy", "damaged", "unverified", "missing", "ready")
    assert proto.combine_readiness([]) == proto.UNVERIFIED  # nothing proved is not ready
    assert proto.combine_readiness([proto.READY, proto.UNVERIFIED]) == proto.UNVERIFIED
    assert proto.combine_readiness([proto.MISSING, proto.UNVERIFIED]) == proto.UNVERIFIED
    assert proto.combine_readiness([proto.MISSING, proto.DAMAGED]) == proto.DAMAGED
    assert proto.combine_readiness([proto.READY, proto.READY]) == proto.READY
    assert {s: proto.acquisition_scope(s) for s in order} == {
        "unsupported": None, "bad-bundle": None, "busy": None, "damaged": "repair", "unverified": None,
        "missing": "install", "ready": None}
    with pytest.raises(ValueError):
        proto.combine_readiness(["healthy"])


def test_figures_keep_how_they_are_known():
    a, m, x = proto.Figure(5, proto.APPROXIMATE), proto.Figure(7, proto.MANIFEST), proto.Figure(2, proto.EXACT)
    assert proto.add_figures([x, m]) == proto.Figure(9, proto.MANIFEST)
    assert proto.add_figures([x, m, a]) == proto.Figure(14, proto.APPROXIMATE)
    assert proto.add_figures([a, proto.NOT_KNOWN]) == proto.Figure(5, proto.AT_LEAST)
    assert proto.add_figures([proto.NOT_KNOWN]) == proto.NOT_KNOWN
    assert proto.add_figures([]) == proto.ZERO
    for bad in [(None, proto.EXACT), (3, proto.UNKNOWN), (-1, proto.EXACT), (True, proto.EXACT)]:
        with pytest.raises(ValueError):
            proto.Figure(*bad)
    assert osu.format_bytes(proto.Figure(4_500_000_000, proto.APPROXIMATE)) == "about 4.5 GB"
    assert osu.format_bytes(proto.Figure(12_000_000, proto.AT_LEAST)) == "at least 12 MB"
    assert osu.format_bytes(proto.NOT_KNOWN) == "unknown"


# --------------------------------------------------------------------------- #
# Task B — plans and honest sizes (main context)
# --------------------------------------------------------------------------- #
def test_nothing_selected_costs_nothing_but_the_base_packages_are_still_disclosed(world, tripwire):
    data = as_json([])
    assert data["selected"] == [] and data["acquire_units"] == [] and data["units"] == []
    assert data["totals"] == {n: fig(0, proto.EXACT) for n in ("download", "reused", "local_copy", "disk", "temp")}
    assert [c["id"] for c in data["components"]] == list(ALL)
    assert all(not c["selected"] and c["readiness"] == proto.UNVERIFIED for c in data["components"])
    base = data["base_packages"]
    assert base["installed"] == fig(1000, proto.APPROXIMATE) and base["download"] == fig(None, proto.UNKNOWN)
    assert "Kokoro" in base["note"] and "Chatterbox" in base["note"] and "skipped" in base["note"]
    text = json.dumps(data).lower()
    assert "edge-only" not in text and "slim" not in text
    assert tripwire == []


def test_kokoro_alone_lists_model_voices_and_the_pinned_spacy_wheel(world, tripwire):
    data = as_json([K], health={K: True})
    kokoro = component(data, K)
    assert kokoro["readiness"] == proto.MISSING and kokoro["consent_scope"] == proto.SCOPE_INSTALL
    assert data["acquire_units"] == ["kokoro-model", *(f"kokoro-voice:{v}" for v in osu.kokoro_roster()),
                                     "spacy-english"]
    assert data["totals"]["download"] == fig(KOKORO_ALL + SPACY_WHEEL, proto.MANIFEST)  # every size is pinned now
    assert data["totals"]["disk"] == fig(KOKORO_ALL + 11, proto.APPROXIMATE)
    spacy = unit(data, "spacy-english")
    assert spacy["download"] == fig(SPACY_WHEEL, proto.MANIFEST) and spacy["source"] == assets.spacy_source()
    assert spacy["source"].startswith("wheel:https://github.com/explosion/spacy-models/releases/download/")
    assert tripwire == []


def test_chatterbox_alone_counts_only_the_files_turbo_loads(world):
    data = as_json([C], health={C: True})
    assert component(data, C)["readiness"] == proto.MISSING
    assert data["totals"]["download"] == fig(CHATTERBOX_ALL, proto.MANIFEST)
    assert "s3gen.safetensors" not in assets.CHATTERBOX_FILES  # in the repository, never loaded, never acquired
    install_chatterbox(world)
    data = as_json([C], health={C: True})
    assert component(data, C)["readiness"] == proto.READY and data["acquire_units"] == []


@pytest.mark.parametrize("name, model_bytes", [(CV, CV_BYTES), (B, BASE_BYTES)])
def test_each_qwen3_component_alone_is_the_shared_engine_plus_its_own_model(world, tripwire, name, model_bytes):
    data = as_json([name])
    assert component(data, name)["readiness"] == proto.MISSING
    assert data["acquire_units"] == ["qwen3-engine", f"qwen3-model:{proto.QWEN3_MODEL_KEYS[name]}"]
    assert data["totals"]["download"] == fig(ENV_DOWNLOAD + model_bytes, proto.MANIFEST)
    assert data["totals"]["disk"] == fig(ENV_INSTALLED + model_bytes, proto.APPROXIMATE)
    assert data["totals"]["temp"] == fig(ENV_DOWNLOAD + MARGIN, proto.MANIFEST)  # pip cache + installer margin
    assert tripwire == []


def test_both_qwen3_components_count_the_engine_and_the_shared_model_files_once(world):
    data = as_json([CV, B])
    engine = unit(data, "qwen3-engine")
    assert engine["components"] == [CV, B] and data["acquire_units"].count("qwen3-engine") == 1
    base = unit(data, "qwen3-model:base")
    assert base["download"] == fig(BASE_BYTES - SHARED_BYTES, proto.MANIFEST)
    assert base["local_copy"] == fig(SHARED_BYTES, proto.MANIFEST)  # copied or linked locally, not downloaded
    assert data["totals"]["download"] == fig(ENV_DOWNLOAD + CV_BYTES + BASE_BYTES - SHARED_BYTES, proto.MANIFEST)
    assert data["totals"]["temp"] == fig(ENV_DOWNLOAD + MARGIN, proto.MANIFEST)  # one engine, one margin
    # Negative control: the per-component figures DO include the engine each time; only the plan total dedupes.
    per_component = sum(component(data, c)["download"]["bytes"] for c in (CV, B))
    assert per_component == data["totals"]["download"]["bytes"] + ENV_DOWNLOAD


def test_all_four_together_is_the_deduplicated_union(world):
    data = as_json(list(reversed(ALL)), health=HEALTHY)  # any input order; the plan is canonical
    assert data["selected"] == list(ALL)
    expected = KOKORO_ALL + SPACY_WHEEL + CHATTERBOX_ALL + ENV_DOWNLOAD + CV_BYTES + BASE_BYTES - SHARED_BYTES
    assert data["totals"]["download"] == fig(expected, proto.MANIFEST)  # v0.7.0: the engine is exact too
    assert len(data["acquire_units"]) == len(set(data["acquire_units"])) == 15


def test_a_later_second_qwen3_model_reuses_the_engine_and_the_shared_files_on_disk(world):
    install_environment(world)
    install_model(world, "customvoice")
    data = as_json([CV, B])
    assert component(data, CV)["readiness"] == proto.READY
    assert data["acquire_units"] == ["qwen3-model:base"]
    assert unit(data, "qwen3-model:base")["local_copy"] == fig(SHARED_BYTES, proto.MANIFEST)
    assert data["totals"]["download"] == fig(BASE_BYTES - SHARED_BYTES, proto.MANIFEST)
    assert data["totals"]["temp"] == fig(MARGIN, proto.EXACT)  # no engine install: only the installer's margin


def test_already_healthy_components_acquire_nothing(world, tripwire):
    install_environment(world)
    install_model(world, "customvoice")
    install_model(world, "base")
    install_kokoro(world)
    install_chatterbox(world)
    data = as_json(ALL, health=HEALTHY, spacy=True)
    assert [c["readiness"] for c in data["components"]] == [proto.READY] * 4
    assert data["acquire_units"] == [] and data["totals"]["download"] == fig(0, proto.EXACT)
    assert unit(data, "kokoro-model")["reused"] == fig(44, proto.EXACT)
    assert tripwire == []


def test_present_files_without_a_health_proof_stay_unverified(world):
    install_kokoro(world)
    install_chatterbox(world)
    data = as_json([K, C], spacy=True)  # no health facts supplied
    assert [component(data, n)["readiness"] for n in (K, C)] == [proto.UNVERIFIED] * 2
    assert all(component(data, n)["consent_scope"] is None for n in (K, C))


@pytest.mark.parametrize("content", [b"x" * 41, b"x" * 40], ids=["another-size", "same-size-other-content"])
def test_a_file_that_is_not_the_pinned_one_is_damaged_and_fetched_again_only_under_repair_consent(world, content):
    snapshot = install_kokoro(world)
    (snapshot / "kokoro-v1_0.pth").write_bytes(content)  # the identity is pinned: this is not "maybe newer"
    data = as_json([K], health={K: True}, spacy=True)
    assert unit(data, "kokoro-model")["state"] == proto.DAMAGED
    assert component(data, K)["readiness"] == proto.DAMAGED and component(data, K)["consent_scope"] == "repair"
    assert data["acquire_units"] == ["kokoro-model"]
    assert unit(data, "kokoro-model")["download"] == fig(40, proto.MANIFEST)  # only the wrong file, never the config
    assert unit(data, "kokoro-model")["temp"] == fig(40, proto.MANIFEST)  # the old copy stays until the new one is proved


def test_a_moved_refs_main_never_changes_what_the_plan_reports(world):
    snapshot = install_kokoro(world)
    folder = snapshot.parent.parent
    (folder / "refs").mkdir(parents=True)
    (folder / "refs" / "main").write_text("9" * 40, encoding="ascii")  # a lazy fetch once moved main elsewhere
    data = as_json([K], health={K: True}, spacy=True)
    assert component(data, K)["readiness"] == proto.READY  # the pinned commit's folder is the only one looked at


def test_mixed_states_each_get_their_own_answer_and_only_installable_or_repairable_work_is_planned(world, monkeypatch):
    install_environment(world)
    install_model(world, "customvoice")
    install_model(world, "base")
    (rt.model_spec("customvoice").directory / "model.safetensors").unlink()  # verified once, now damaged
    install_kokoro(world)
    monkeypatch.setattr(rt, "bundle_status", lambda: (False, "The bundled transcripts are damaged."))
    data = as_json(ALL, health={K: True, C: True}, spacy=True)
    got = {c["id"]: (c["readiness"], c["consent_scope"]) for c in data["components"]}
    assert got == {K: (proto.READY, None), C: (proto.MISSING, "install"), CV: (proto.DAMAGED, "repair"),
                   B: (proto.BAD_BUNDLE, None)}
    assert component(data, B)["reason"] == "The bundled transcripts are damaged."
    assert data["acquire_units"] == ["chatterbox-model", "qwen3-model:customvoice"]
    assert unit(data, "qwen3-model:customvoice")["download"] == fig(None, proto.UNKNOWN)  # a full check decides
    assert data["totals"]["download"] == fig(CHATTERBOX_ALL, proto.AT_LEAST)


def test_an_unverified_engine_blocks_both_qwen3_choices_without_permission_to_install(world):
    make_engine(rt.nested_venv_dir(), world / "base-python")  # looks built, but no identity was ever recorded
    data = as_json([CV, B])
    assert unit(data, "qwen3-engine")["state"] == proto.UNVERIFIED
    assert [component(data, n)["readiness"] for n in (CV, B)] == [proto.UNVERIFIED] * 2
    assert data["acquire_units"] == []
    assert data["pending_units"] == ["qwen3-model:customvoice", "qwen3-model:base"]  # disclosed, not acquired
    assert data["pending"]["download"] == fig(CV_BYTES + BASE_BYTES - SHARED_BYTES, proto.MANIFEST)


def test_a_broken_engine_is_damaged_and_rebuilt_only_under_repair_consent(world):
    rt.nested_venv_dir().mkdir(parents=True)  # a folder with no pyvenv.cfg
    data = as_json([CV])
    assert unit(data, "qwen3-engine")["state"] == proto.DAMAGED
    assert component(data, CV)["consent_scope"] == proto.SCOPE_REPAIR


def test_unsupported_platform_python_and_architecture(world, monkeypatch):
    data = as_json(ALL, health=HEALTHY, python=(3, 13))
    assert [component(data, n)["readiness"] for n in (K, C)] == [proto.UNSUPPORTED] * 2
    assert not any(u["id"].startswith(("kokoro", "chatterbox", "spacy")) for u in data["units"])
    assert "3.13" in component(data, K)["reason"]
    assert component(as_json([K], health=HEALTHY, is_64bit=False), K)["readiness"] == proto.UNSUPPORTED
    monkeypatch.setattr(sys, "platform", "darwin")
    data = as_json([CV, B])
    assert [component(data, n)["readiness"] for n in (CV, B)] == [proto.UNSUPPORTED] * 2
    assert data["units"] == [] and data["hardware"]["qwen3"] == rt.platform_reason()


def test_busy_and_bad_bundle_are_reported_and_never_acquire(world, monkeypatch):
    data = as_json([CV, K], busy=[CV], health={K: True})
    assert component(data, CV)["readiness"] == proto.BUSY and "qwen3-engine" not in data["acquire_units"]
    monkeypatch.setattr(rt, "reference_status", lambda voice: (False, "Male 4's recording is missing."))
    data = as_json([C, CV, B], health=HEALTHY)
    assert component(data, C)["readiness"] == proto.BAD_BUNDLE and component(data, B)["readiness"] == proto.BAD_BUNDLE
    assert component(data, CV)["readiness"] == proto.MISSING  # the presets need no recording
    assert data["acquire_units"] == ["qwen3-engine", "qwen3-model:customvoice"]


def test_unknown_and_changed_estimates_are_never_passed_off_as_known(world, monkeypatch):
    roster = osu.kokoro_roster()
    monkeypatch.delitem(assets.KOKORO_FILES, assets.kokoro_voice_name(roster[0]))  # a voice with no pinned identity
    data = as_json([K], health={K: True}, spacy=True)
    assert unit(data, f"kokoro-voice:{roster[0]}")["download"] == fig(None, proto.UNKNOWN)
    assert unit(data, f"kokoro-voice:{roster[0]}")["source"] is None  # so no consent can acquire it
    assert data["totals"]["download"]["basis"] == proto.AT_LEAST
    before = as_json([CV])
    from tts import qwen3_wheels  # v0.7.0: the engine download is the exact wheel set; a changed set is a new plan
    wheels = qwen3_wheels.wheels()
    monkeypatch.setattr(qwen3_wheels, "wheels", lambda: wheels + (qwen3_wheels.Wheel(
        "extra", "extra-1.0-py3-none-any.whl", "https://wheels.invalid/extra-1.0-py3-none-any.whl", 1, "0" * 64),))
    after = as_json([CV])
    assert after["fingerprint"] != before["fingerprint"]
    assert after["acquisition_fingerprint"] != before["acquisition_fingerprint"]
    ok, code, why = proto.consent_covers(osu.consent_for(before), after)
    assert (ok, code) == (False, proto.CONSENT_STALE) and "not the one that was confirmed" in why


def test_hardware_is_described_without_probing_unless_asked(world, tripwire, monkeypatch):
    probes = []
    monkeypatch.setattr(rt, "gpu_probe", lambda: probes.append(1) or rt.GpuInfo("RTX Test", 12288))
    rt._GPU_CACHE.clear()
    data = as_json([CV])
    assert data["hardware"]["gpu"] == {"probed": False, "name": None, "memory_mb": None} and probes == []
    assert "not been checked" in data["hardware"]["qwen3"]
    assert any("No speed is promised" in line for line in data["hardware"]["limits"])
    data = as_json([CV], probe=True)
    assert data["hardware"]["gpu"] == {"probed": True, "name": "RTX Test", "memory_mb": 12288} and probes == [1]
    assert data["hardware"]["qwen3"] == rt.hardware_summary()


def test_planning_never_writes_into_the_installation(world):
    install_kokoro(world)
    before = sorted(str(p.relative_to(world)) for p in world.rglob("*"))
    as_json(ALL, health=HEALTHY)
    osu.plan_to_json(osu.estimate(ALL))
    assert sorted(str(p.relative_to(world)) for p in world.rglob("*")) == before


# --------------------------------------------------------------------------- #
# Task B — the pre-venv estimate, and consent carried from it
# --------------------------------------------------------------------------- #
def test_the_pre_venv_estimate_is_a_manifest_upper_bound_that_proves_nothing(world, tripwire):
    install_environment(world)  # even with things installed, the wizard's estimate does not look
    install_model(world, "customvoice")
    data = osu.plan_to_json(osu.estimate(ALL))
    assert data["context"] == osu.CONTEXT_PRE_VENV and data["upper_bound"] is True
    assert all(c["readiness"] == proto.UNVERIFIED and c["consent_scope"] is None for c in data["components"])
    assert data["hardware"]["python"] is None and data["hardware"]["gpu"]["probed"] is False
    # The pre-venv estimate still reads the engine's manifest approximation (it may not import the package manifest).
    expected = KOKORO_ALL + SPACY_WHEEL + CHATTERBOX_ALL + 3_100_000_000 + CV_BYTES + BASE_BYTES - SHARED_BYTES
    assert data["totals"]["download"] == fig(expected, proto.APPROXIMATE)
    assert data["acquire_units"].count("qwen3-engine") == 1
    assert unit(data, "qwen3-model:base")["local_copy"] == fig(SHARED_BYTES, proto.MANIFEST)
    assert any("most each choice could cost" in n for n in data["notes"])
    assert tripwire == []


def test_the_pre_venv_estimate_on_another_platform_offers_no_qwen3(world, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    data = osu.plan_to_json(osu.estimate([K, CV]))
    assert component(data, CV)["readiness"] == proto.UNSUPPORTED
    assert not any(u.startswith("qwen3") for u in data["acquire_units"])


def estimate_json(components) -> dict:
    return osu.plan_to_json(osu.estimate(components))


def test_consent_from_the_wizard_estimate_covers_the_exact_plan_and_nothing_more(world, monkeypatch):
    shown = estimate_json(ALL)
    consent = osu.consent_for(shown)
    assert consent.plan_context == proto.CONTEXT_PRE_VENV and consent.components == ALL
    assert consent.scopes == {c: proto.SCOPE_INSTALL for c in ALL}
    assert proto.consent_covers(consent, as_json(ALL, health=HEALTHY, spacy=True), estimate=shown) == (True, "", "ok")
    install_environment(world)
    install_model(world, "customvoice")
    (rt.model_spec("customvoice").directory / "model.safetensors").unlink()
    ok, code, why = proto.consent_covers(consent, as_json(ALL, health=HEALTHY, spacy=True), estimate=shown)
    assert (ok, code) == (False, proto.CONSENT_STALE) and "repair" in why  # a repair is a different agreement
    narrower = osu.consent_for(estimate_json([K]))
    ok, code, why = proto.consent_covers(narrower, as_json([K, CV], health=HEALTHY, spacy=True),
                                         estimate=estimate_json([K]))
    assert not ok and code == proto.CONSENT_STALE


def test_consent_never_covers_an_unverified_component(world):
    shown = estimate_json([K])
    ok, code, why = proto.consent_covers(osu.consent_for(shown), as_json([K]), estimate=shown)  # engine not proved
    assert (ok, code) == (False, proto.NOT_ACQUIRABLE) and "unverified" in why


# --------------------------------------------------------------------------- #
# Task C — the request protocol
# --------------------------------------------------------------------------- #
SESSION = "a" * 32


def request_json(**changes) -> dict:
    message = proto.new_request(proto.ACTION_PLAN, [K, B], session=SESSION).to_json()
    message.update(changes)
    return message


def install_json(**consent_changes) -> dict:
    consent = {"consent_id": "c" * 32, "plan_context": "main", "components": [K], "scopes": {K: "install"},
               "units": ["kokoro-model", "kokoro-voice:af_heart"], "unknown_units": ["kokoro-voice:af_heart"],
               "download_bytes": 10, "acquisition_fingerprint": "f" * 64}
    consent.update(consent_changes)
    return request_json(action="install", components=[K], consent=consent)


def refuse(message, code, *, session=SESSION, now=time.time, raw=None):
    data = raw if raw is not None else json.dumps(message).encode("utf-8")
    with pytest.raises(proto.ProtocolError) as caught:
        proto.decode_request(data, session=session, now=now)
    assert caught.value.code == code, str(caught.value)


def test_a_request_round_trips_exactly():
    request = proto.new_request(proto.ACTION_PLAN, [B, K], session=SESSION, probe_hardware=True)
    assert request.components == (K, B) and len(request.request_id) == 32
    assert proto.decode_request(proto.encode(request.to_json()), session=SESSION) == request
    assert proto.new_request(proto.ACTION_PLAN, [], session=SESSION).components == ()


@pytest.mark.parametrize("raw", [b"", b"not json", b"[1, 2]", b'{"a": NaN}', "\u00e9".encode("latin-1"),
                                 b'{"protocol": "act-optional-setup", "protocol": "x"}', b" " * (65 * 1024)],
                         ids=["empty", "text", "array", "nan", "latin-1", "duplicate-key", "oversized"])
def test_malformed_bytes_are_refused(raw):
    refuse(None, proto.MALFORMED, raw=raw)


@pytest.mark.parametrize("change", [
    {"extra": 1}, {"options": {"probe_hardware": 1}}, {"options": {}}, {"request_id": "A" * 32},
    {"request_id": "a" * 31}, {"issued_utc": "2026-10-25 12:00:00"}, {"issued_utc": "2026-13-45T99:00:00Z"},
    {"action": "download"}, {"action": "shell"}, {"components": "kokoro"}, {"components": [B, K]},
    {"protocol": "other"}, {"version": "1"}, {"version": True},
])
def test_any_unexpected_key_type_or_value_is_refused(change):
    refuse(request_json(**change), proto.MALFORMED)


def test_missing_keys_are_refused():
    message = request_json()
    del message["options"]
    refuse(message, proto.MALFORMED)


@pytest.mark.parametrize("version", [0, 1, 3, 99])
def test_other_protocol_versions_are_refused(version):
    """Version 1 included: a P05A consent named a fingerprint nothing checked, so it is refused, never upgraded."""
    assert proto.PROTOCOL_VERSION == 2
    refuse(request_json(version=version), proto.UNSUPPORTED_VERSION)


@pytest.mark.parametrize("components, code", [
    (["edge"], proto.UNKNOWN_COMPONENT), (["Kokoro"], proto.UNKNOWN_COMPONENT), ([1], proto.UNKNOWN_COMPONENT),
    (["qwen3"], proto.UNKNOWN_COMPONENT), ([K, K], proto.DUPLICATE_COMPONENT),
])
def test_only_the_four_allowlisted_components_once_each(components, code):
    refuse(request_json(components=components), code)
    with pytest.raises(proto.ProtocolError):
        proto.canonical_selection(components)


@pytest.mark.parametrize("message", [
    lambda: request_json(consent={"scope": "install"}),  # a plan carries no consent
    lambda: request_json(action="install", components=[K], consent=None),
    lambda: request_json(action="install", components=[], consent=None),
    lambda: install_json(scopes={K: "everything"}), lambda: install_json(scopes={}),
    lambda: install_json(scopes={K: "install", C: "install"}), lambda: install_json(components=[K, C]),
    lambda: install_json(plan_context="pre-venv", scopes={K: "repair"}),
    lambda: install_json(plan_context="pre-venv", scopes={K: None}), lambda: install_json(plan_context="later"),
    lambda: install_json(consent_id="C" * 32), lambda: install_json(consent_id=None),
    lambda: install_json(units=["../x"]), lambda: install_json(units=["a", "a"]),
    lambda: install_json(unknown_units=["spacy-english"]), lambda: install_json(unknown_units="kokoro-model"),
    lambda: install_json(download_bytes=-1), lambda: install_json(download_bytes=1.5),
    lambda: install_json(download_bytes=None), lambda: install_json(acquisition_fingerprint="0" * 63),
    lambda: install_json(extra=True),
], ids=lambda m: "consent")
def test_consent_must_be_explicit_and_exact(message):
    built = message()
    code = proto.MALFORMED if built["action"] == "install" and not built["components"] else proto.BAD_CONSENT
    refuse(built, code)


def test_a_v1_consent_shape_is_refused_even_under_the_current_version():
    v1 = {"scope": "install", "components": [K], "units": ["kokoro-model"], "download_bytes": 10,
          "plan_fingerprint": "f" * 64}
    refuse(request_json(action="install", components=[K], consent=v1), proto.BAD_CONSENT)


def test_a_complete_install_request_is_accepted():
    request = proto.decode_request(json.dumps(install_json()).encode(), session=SESSION)
    assert request.consent == proto.Consent("c" * 32, "main", (K,), {K: "install"},
                                            ("kokoro-model", "kokoro-voice:af_heart"), ("kokoro-voice:af_heart",), 10,
                                            "f" * 64)


def test_old_consent_is_never_replayed_another_session_or_a_stale_time():
    refuse(request_json(), proto.WRONG_SESSION, session="b" * 32)
    refuse(request_json(), proto.WRONG_SESSION, session="not-a-token")
    refuse(request_json(), proto.STALE_REQUEST, now=lambda: time.time() + proto.MAX_REQUEST_AGE_S + 5)
    refuse(request_json(), proto.STALE_REQUEST, now=lambda: time.time() - proto.MAX_CLOCK_SKEW_S - 5)


def test_events_are_marked_strict_and_bound_to_their_request():
    rid = "c" * 32
    line = proto.encode_event(rid, 0, "progress", {"done": 1})
    assert proto.decode_event(line, request_id=rid)["payload"] == {"done": 1}
    assert proto.decode_event("ordinary output", request_id=rid) is None
    for bad in [line.replace('"seq":0', '"seq":-1'), proto.EVENT_MARK + "{", line[:-1]]:
        with pytest.raises(proto.ProtocolError):
            proto.decode_event(bad, request_id=rid)
    with pytest.raises(proto.ProtocolError):
        proto.decode_event(line, request_id="d" * 32)
    with pytest.raises(ValueError):
        proto.encode_event(rid, 1, "exec", {})


def test_results_are_strict_and_a_success_never_carries_an_error():
    rid = "c" * 32
    ok = proto.make_result(rid, proto.SUCCEEDED, plan={})
    assert proto.decode_result(proto.encode(ok), request_id=rid) == ok
    for bad in [dict(ok, state="done"), dict(ok, error={"code": "internal", "message": "x"}), dict(ok, forced=1),
                dict(ok, request_id="d" * 32), {**ok, "extra": 1}]:
        with pytest.raises(proto.ProtocolError):
            proto.decode_result(proto.encode(bad), request_id=rid)
    with pytest.raises(ValueError):
        proto.make_result(rid, proto.FAILED)


# --------------------------------------------------------------------------- #
# Task C — containment, exactly-once results, execution home and launch
# --------------------------------------------------------------------------- #
RID = "e" * 32


def exchange(root: Path, name: str = proto.REQUEST_NAME, rid: str = RID) -> str:
    return str(proto.exchange_dir(root, rid) / name)


@pytest.mark.parametrize("make", [
    lambda r: "", lambda r: "relative/request.json", lambda r: exchange(r).replace(RID, "x" * 32),
    lambda r: str(r / "files" / "runtime-data" / "optional-setup" / RID / ".." / RID / "request.json"),
    lambda r: str(r.parent / "elsewhere" / RID / "request.json"), lambda r: exchange(r, proto.RESULT_NAME),
    lambda r: str(proto.exchange_dir(r, RID) / "sub" / "request.json"), lambda r: exchange(r) + "\x00",
])
def test_exchange_paths_outside_their_one_place_are_refused(tmp_path, make):
    with pytest.raises(proto.ProtocolError) as caught:
        proto.check_exchange_path(tmp_path, make(tmp_path), proto.REQUEST_NAME)
    assert caught.value.code == proto.UNSAFE_PATH


def test_the_exchange_path_is_accepted_only_in_its_place(tmp_path):
    path, rid = proto.check_exchange_path(tmp_path, exchange(tmp_path), proto.REQUEST_NAME)
    assert rid == RID and path == proto.exchange_dir(tmp_path, RID) / "request.json"


def _junction(link: Path, target: Path) -> bool:
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        return subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True).returncode == 0
    link.symlink_to(target, target_is_directory=True)
    return True


@pytest.mark.parametrize("linked", ["optional-setup", "request", "inside-the-app"])
def test_a_junction_anywhere_on_the_way_is_refused(tmp_path, linked):
    root, outside = tmp_path / "app", tmp_path / "outside"
    (outside / RID).mkdir(parents=True)
    if linked == "optional-setup":
        made = _junction(proto.exchange_root(root), outside)
    elif linked == "request":
        made = _junction(proto.exchange_dir(root, RID), outside / RID)
    else:  # still inside the app once resolved: only the link check itself can refuse this one
        (root / "files" / "elsewhere" / RID).mkdir(parents=True)
        made = _junction(proto.exchange_root(root), root / "files" / "elsewhere")
    if not made:
        pytest.skip("this account cannot create a junction")
    with pytest.raises(proto.ProtocolError) as caught:
        proto.check_exchange_path(root, exchange(root), proto.REQUEST_NAME)
    assert caught.value.code == proto.UNSAFE_PATH
    if linked != "request":  # nothing new may be created through it either
        with pytest.raises(proto.ProtocolError):
            proto.write_request(root, proto.new_request(proto.ACTION_PLAN, [K], session=SESSION))


def test_a_linked_message_file_is_never_read(tmp_path):
    target = tmp_path / "real.json"
    target.write_bytes(b"{}")
    link = tmp_path / "request.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("this account cannot create a file symlink")
    with pytest.raises(proto.ProtocolError) as caught:
        proto.read_message_file(link)
    assert caught.value.code == proto.UNSAFE_PATH


def test_a_result_is_published_exactly_once_and_never_replaced(tmp_path):
    path = tmp_path / "result.json"
    assert proto.publish_once(path, b"first") is True
    assert proto.publish_once(path, b"second") is False
    assert path.read_bytes() == b"first"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["result.json"]  # no temporary left behind


def test_write_request_makes_a_fresh_folder_and_refuses_reuse(tmp_path):
    request = proto.new_request(proto.ACTION_PLAN, [K], session=SESSION)
    path = proto.write_request(tmp_path, request)
    assert proto.decode_request(proto.read_message_file(path), session=SESSION) == request
    with pytest.raises(FileExistsError):
        proto.write_request(tmp_path, request)


def test_the_execution_home_is_only_the_apps_own_cpython_3_12_environment(tmp_path):
    root = tmp_path
    venv = root / ".venv"
    good = dict(implementation="cpython", version=(3, 12), prefix=str(venv), base_prefix="C:/Python312",
                executable=str(venv_layout.interpreter(venv)))
    assert proto.execution_home_problem(root, **good) == ""
    for change, words in [({"version": (3, 11)}, "CPython 3.12"), ({"version": (3, 13)}, "CPython 3.12"),
                          ({"implementation": "pypy"}, "CPython 3.12"),
                          ({"prefix": "C:/Python312"}, "base interpreter"),
                          ({"prefix": str(root / ".venv" / "engines" / "qwen3")}, "own environment"),
                          ({"prefix": str(root / ".venv-qwen3")}, "own environment"),
                          ({"executable": str(venv / "Scripts" / "pythonw.exe")}, "console interpreter")]:
        assert words in proto.execution_home_problem(root, **{**good, **change})


def test_the_running_test_interpreter_is_judged_by_the_same_rule():
    """The suite runs in the real .venv: against the real repository it is a valid home; against any other it is not."""
    assert proto.execution_home_problem(REPO) == ""
    assert proto.execution_home_problem(REPO / "files") != ""


def test_the_launch_is_an_argv_list_from_scripts_with_no_ambient_python_settings(tmp_path):
    root = tmp_path
    python = proto.main_console_python(root)
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    worker_file = root / "scripts" / "tts" / "optional_setup_worker.py"
    worker_file.parent.mkdir(parents=True)
    worker_file.write_text("", encoding="utf-8")
    request = proto.new_request(proto.ACTION_PLAN, [K], session=SESSION)
    path = proto.write_request(root, request)
    env = {"PATH": "x", "PYTHONPATH": "evil", "PYTHONHOME": "evil", "PYTHONSTARTUP": "evil", "VIRTUAL_ENV": "v",
           "pythonpath": "evil"}
    spec = proto.worker_launch(root, path, SESSION, base_env=env)
    assert spec.argv == (str(python), "-E", "-s", "-m", "tts.optional_setup_worker", "--request", str(path),
                         "--result", str(path.with_name("result.json")), "--session", SESSION)
    assert spec.cwd == root / "scripts" and spec.env == {"PATH": "x"}
    for other in (root / ".venv" / "Scripts" / "pythonw.exe", Path(sys._base_executable),
                  rt.repo_root() / ".venv" / "engines" / "qwen3" / "Scripts" / "python.exe"):
        with pytest.raises(proto.ProtocolError) as caught:
            proto.worker_launch(root, path, SESSION, python=other)
        assert caught.value.code == proto.WRONG_INTERPRETER
    with pytest.raises(proto.ProtocolError):
        proto.worker_launch(root, root / "request.json", SESSION)


# --------------------------------------------------------------------------- #
# Task C — the worker, in process
# --------------------------------------------------------------------------- #
@pytest.fixture
def no_acquisition(monkeypatch):
    """Every acquisition seam this build could reach fails loudly if touched."""
    def forbidden(*args, **kwargs):
        raise TripwireError("an acquisition seam was reached")
    for name in ("install", "install_model", "install_environment", "download_file", "repair", "probe_environment"):
        monkeypatch.setattr(su, name, forbidden)


def run_main(root: Path, request: proto.Request, *, session: str = SESSION, home="", **kwargs) -> tuple[int, dict]:
    path = proto.write_request(root, request)
    code = worker.main(["--request", str(path), "--result", str(path.with_name("result.json")), "--session", session],
                       repo_root=root, home_check=lambda r: home, **kwargs)
    result = proto.decode_result(proto.read_message_file(path.with_name("result.json")),
                                 request_id=request.request_id)
    return code, result


def events(capsys, rid: str) -> list[dict]:
    out = capsys.readouterr().out.splitlines()
    return [e for e in (proto.decode_event(line, request_id=rid) for line in out) if e is not None]


def test_the_worker_answers_a_plan_request_with_events_and_one_result(world, tripwire, no_acquisition, capsys):
    request = proto.new_request(proto.ACTION_PLAN, ALL, session=SESSION)
    code, result = run_main(world, request, facts=facts(health=HEALTHY))
    assert code == 0 and result["state"] == proto.SUCCEEDED and result["forced"] is False
    assert result["plan"]["selected"] == list(ALL) and result["plan"]["fingerprint"] == osu.fingerprint(result["plan"])
    seen = events(capsys, request.request_id)
    assert [(e["seq"], e["kind"]) for e in seen] == [(0, "started"), (1, "readiness"), (2, "plan")]
    assert seen[2]["payload"]["fingerprint"] == result["plan"]["fingerprint"]
    assert tripwire == []


def test_an_install_request_is_checked_and_then_refused_without_acquiring_anything(world, tripwire, no_acquisition):
    """An ``Operation`` given the disabled acquirer (the default when it is given none) checks, then refuses."""
    consent = osu.consent_for(osu.plan_to_json(osu.plan([K, CV], facts=facts(health=HEALTHY, spacy=True))))
    request = proto.new_request(proto.ACTION_INSTALL, [K, CV], session=SESSION, consent=consent)
    code, result = run_main(world, request, facts=facts(health=HEALTHY, spacy=True), acquirer=osl.DisabledAcquirer())
    assert code == proto.EXIT_CODES[proto.REFUSED]
    assert result["error"]["code"] == proto.ACQUISITION_UNAVAILABLE and "Nothing was downloaded" in result["error"]["message"]
    assert result["verified"] == []
    assert not (world / ".venv" / "engines").exists() and not rt.models_root().exists()
    assert not (proto.exchange_root(world) / proto.CONSENTS_DIR).exists()  # checked, but never spent
    assert tripwire == []


def test_an_install_request_whose_consent_was_altered_is_refused(world, no_acquisition):
    consent = osu.consent_for(osu.plan_to_json(osu.plan([CV], facts=facts())))
    smaller = dataclasses.replace(consent, download_bytes=consent.download_bytes - 1)
    request = proto.new_request(proto.ACTION_INSTALL, [CV], session=SESSION, consent=smaller)
    code, result = run_main(world, request, facts=facts(), acquirer=osl.DisabledAcquirer())
    assert result["state"] == proto.REFUSED and result["error"]["code"] == proto.BAD_CONSENT


@pytest.mark.parametrize("stop_at, kinds", [(1, ["started"]), (2, ["started"]), (3, ["started", "readiness", "plan"])])
def test_cancellation_at_every_checkpoint_gives_one_cancelled_result(world, stop_at, kinds):
    seen, calls = [], []

    def cancel_check():
        calls.append(1)
        return len(calls) >= stop_at

    request = proto.new_request(proto.ACTION_PLAN, [CV], session=SESSION)
    result = worker.run(request, emit=lambda kind, payload: seen.append(kind), cancel_check=cancel_check,
                        facts=facts())
    assert result["state"] == proto.CANCELLED_STATE and result["error"]["code"] == proto.CANCELLED
    assert result["plan"] is None and seen == kinds


def test_a_cancel_flag_written_before_the_worker_looks_is_honoured(world):
    request = proto.new_request(proto.ACTION_PLAN, [K], session=SESSION)
    path = proto.write_request(world, request)
    proto.publish_once(path.with_name(proto.CANCEL_NAME), b"cancel\n")
    code = worker.main(["--request", str(path), "--result", str(path.with_name("result.json")), "--session", SESSION],
                       repo_root=world, home_check=lambda r: "", facts=facts())
    assert code == proto.EXIT_CODES[proto.CANCELLED_STATE]


@pytest.mark.parametrize("kwargs, code", [
    ({"session": "b" * 32}, proto.WRONG_SESSION),
    ({"home": "the setup worker needs CPython 3.12, not cpython 3.11"}, proto.WRONG_INTERPRETER),
])
def test_refusals_are_terminal_results(world, kwargs, code):
    request = proto.new_request(proto.ACTION_PLAN, [K], session=SESSION)
    exit_code, result = run_main(world, request, **kwargs)
    assert exit_code == proto.EXIT_CODES[proto.REFUSED] and result["error"]["code"] == code


def test_an_unexpected_planner_failure_is_one_failed_result(world, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("planner exploded")
    monkeypatch.setattr(osu, "plan", boom)
    code, result = run_main(world, proto.new_request(proto.ACTION_PLAN, [K], session=SESSION))
    assert code == proto.EXIT_CODES[proto.FAILED] and result["error"] == {"code": "internal",
                                                                           "message": "RuntimeError: planner exploded"}


def test_a_request_is_answered_once_and_a_second_run_changes_nothing(world):
    request = proto.new_request(proto.ACTION_PLAN, [K], session=SESSION)
    run_main(world, request, facts=facts())
    folder = proto.exchange_dir(world, request.request_id)
    before = (folder / "result.json").read_bytes()
    code = worker.main(["--request", str(folder / "request.json"), "--result", str(folder / "result.json"),
                        "--session", SESSION], repo_root=world, home_check=lambda r: "", facts=facts())
    assert code == proto.EXIT_NO_RESULT and (folder / "result.json").read_bytes() == before


def test_a_result_path_outside_its_place_writes_nothing(world, tmp_path):
    request = proto.new_request(proto.ACTION_PLAN, [K], session=SESSION)
    path = proto.write_request(world, request)
    outside = tmp_path / "result.json"
    code = worker.main(["--request", str(path), "--result", str(outside), "--session", SESSION], repo_root=world,
                       home_check=lambda r: "")
    assert code == proto.EXIT_NO_RESULT and not outside.exists()
    other = proto.new_request(proto.ACTION_PLAN, [K], session=SESSION)
    other_path = proto.write_request(world, other)
    code = worker.main(["--request", str(path), "--result", str(other_path.with_name("result.json")), "--session",
                        SESSION], repo_root=world, home_check=lambda r: "")
    result = proto.decode_result(proto.read_message_file(other_path.with_name("result.json")),
                                 request_id=other.request_id)
    assert result["error"]["code"] == proto.UNSAFE_PATH  # a request from another folder is never run


# --------------------------------------------------------------------------- #
# Task C — the real bridge: a child process in a disposable copy of the app
# --------------------------------------------------------------------------- #
SITECUSTOMIZE = '''\
import atexit, json, os, subprocess, sys
_LOG = os.path.join(sys.prefix, "act-tripwire.log")
_PROCESSES = os.path.join(sys.prefix, "act-processes.log")
_WATCH = ("socket.", "os.system", "os.startfile", "os.spawn", "os.posix_spawn", "os.exec", "urllib.Request",
          "http.client.connect")
def _hook(event, args):
    if event == "subprocess.Popen":  # recorded, not refused: planning runs bounded engine probes (P05B Stage 2)
        with open(_PROCESSES, "a", encoding="utf-8") as handle:
            line = args[1] if isinstance(args[1], str) else subprocess.list2cmdline([str(a) for a in args[1]])
            handle.write(json.dumps(line[:400]) + "\\n")  # Windows audits the command line as one string
    elif event.startswith(_WATCH):
        with open(_LOG, "a", encoding="utf-8") as handle:
            handle.write(event + "\\n")
        raise RuntimeError("tripwire: " + event)
sys.addaudithook(_hook)
@atexit.register
def _record_modules():
    names = {n: getattr(m, "__file__", None) for n, m in list(sys.modules.items())}
    name = "act-modules-%d-%d.json" % (os.getppid(), os.getpid())  # a Windows venv python.exe starts the real one
    with open(os.path.join(sys.prefix, name), "w", encoding="utf-8") as handle:
        json.dump(names, handle)
'''
HEAVY = ("torch", "kokoro", "chatterbox", "huggingface_hub", "spacy", "numpy", "transformers", "misaki", "tkinter")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """A disposable copy of the app: its scripts, an empty ``files/``, and a pip-less ``.venv`` built from the base
    CPython 3.12 with a tripwire ``sitecustomize``. Nothing of the real installation is used or touched."""
    base = Path(getattr(sys, "_base_executable", "") or sys.executable)
    root = tmp_path_factory.mktemp("disposable-app")
    for package in ("shared", "tts"):
        shutil.copytree(REPO / "scripts" / package, root / "scripts" / package,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(REPO / "scripts" / "qwen3-requirements.txt", root / "scripts" / "qwen3-requirements.txt")
    shutil.copyfile(REPO / "scripts" / "qwen3-artifacts.json", root / "scripts" / "qwen3-artifacts.json")
    (root / "files").mkdir()
    made = subprocess.run([str(base), "-I", "-m", "venv", "--without-pip", str(root / ".venv")], capture_output=True,
                          text=True, timeout=300)
    assert made.returncode == 0, made.stderr
    python = proto.main_console_python(root)
    site = subprocess.run([str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                          capture_output=True, text=True, timeout=60).stdout.strip()
    (Path(site) / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    return root


def child_modules(root: Path, pid: int) -> dict:
    """What the interpreter started as *pid* imported (*pid* itself, or the child a venv redirector started)."""
    found = [p for p in (root / ".venv").glob("act-modules-*.json") if str(pid) in p.stem.split("-")[2:]]
    assert len(found) == 1, found
    return json.loads(found[0].read_text(encoding="utf-8"))


def process_gone(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False
    import ctypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return True
    try:
        return kernel.WaitForSingleObject(ctypes.c_void_p(handle), 5000) == 0
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


def tripped(root: Path) -> str:
    log = root / ".venv" / "act-tripwire.log"
    return log.read_text(encoding="utf-8") if log.exists() else ""


def started_processes(root: Path, *, clear: bool = True) -> list[list[str]]:
    log = root / ".venv" / "act-processes.log"
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    if clear and log.exists():
        log.unlink()
    return lines


def launch(root: Path, request: proto.Request, *, session: str) -> proto.WorkerRun:
    path = proto.write_request(root, request)
    run = proto.WorkerRun(root, proto.worker_launch(root, path, session), request)
    run.start()
    return run


def test_the_worker_runs_in_the_apps_environment_and_acquires_nothing(app):
    started_processes(app)
    session = proto.new_token()
    request = proto.new_request(proto.ACTION_PLAN, ALL, session=session)
    started = time.monotonic()
    run = launch(app, request, session=session)
    result = run.wait(120)
    assert result["state"] == proto.SUCCEEDED, (result, run.output)
    assert run.process.returncode == 0 and result["forced"] is False and time.monotonic() - started < 120
    assert [e["kind"] for e in run.events] == ["started", "readiness", "plan"] and run.protocol_errors == []
    plan = result["plan"]
    assert plan["context"] == osu.CONTEXT_MAIN
    got = {c["id"]: c["readiness"] for c in plan["components"]}
    # The copy has no references, no models and a pip-less environment: the real probes prove the Kokoro and
    # Chatterbox packages absent (broken, not "unverified"), nothing is ready and nothing is assumed.
    assert got == {K: proto.DAMAGED, C: proto.BAD_BUNDLE, CV: proto.MISSING, B: proto.BAD_BUNDLE}
    assert {c["id"]: c["engine"] for c in plan["components"]} == {K: "broken", C: "broken", CV: None, B: None}
    assert tripped(app) == ""  # no network
    probes = started_processes(app)  # the only processes: the two bounded engine probes, in the app's own Python
    head = subprocess.list2cmdline([str(proto.main_console_python(app)), "-E", "-s", "-c"])
    assert len(probes) == 2 and all(p.startswith(head + " ") for p in probes), probes
    modules = child_modules(app, run.process.pid)
    assert not [m for m in modules if m.split(".")[0] in HEAVY]
    ours = {m: f for m, f in modules.items() if m.split(".")[0] in ("shared", "tts") and f}
    assert ours and all(venv_layout.is_within(app / "scripts", f) for f in ours.values())
    assert sorted(p.name for p in (app / "files").iterdir()) == ["runtime-data"]
    assert sorted(p.name for p in (app / "files" / "runtime-data").iterdir()) == ["optional-setup"]


def test_a_child_cancelled_before_it_starts_reports_cancelled(app):
    session = proto.new_token()
    request = proto.new_request(proto.ACTION_PLAN, [K], session=session)
    path = proto.write_request(app, request)
    proto.publish_once(path.with_name(proto.CANCEL_NAME), b"cancel\n")
    run = proto.WorkerRun(app, proto.worker_launch(app, path, session), request)
    run.start()
    result = run.wait(120)
    assert result["state"] == proto.CANCELLED_STATE and not result["forced"] and run.process.returncode == 3


def test_a_hung_child_is_ended_within_its_bound_and_given_one_forced_result(app, tmp_path):
    session = proto.new_token()
    request = proto.new_request(proto.ACTION_PLAN, [K], session=session)
    path = proto.write_request(app, request)
    spec = proto.worker_launch(app, path, session)
    pid_file = tmp_path / "interpreter.pid"
    script = f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(120)"
    hung = proto.LaunchSpec((spec.argv[0], "-c", script), spec.cwd, spec.env, spec.request_path, spec.result_path)
    run = proto.WorkerRun(app, hung, request)
    started = time.monotonic()
    run.start()
    while not (pid_file.exists() and pid_file.read_text()) and time.monotonic() - started < 30:
        time.sleep(0.05)
    result = run.wait(1.0, cancel_grace_s=1.0)
    assert time.monotonic() - started < 40 and run.process.poll() is not None
    assert process_gone(int(pid_file.read_text()))  # the real interpreter, not just a venv redirector, is gone
    assert result["state"] == proto.FAILED and result["error"]["code"] == proto.TIMED_OUT and result["forced"] is True
    assert run.timed_out and run.terminated and run.lingering == 0
    assert proto.publish_once(spec.result_path, b"late") is False  # a late writer can never replace it
    assert run.result() == result


def test_negative_control_the_child_tripwire_really_fires(app):
    python = proto.main_console_python(app)
    probe = subprocess.run([str(python), "-E", "-s", "-c", "import socket; socket.getaddrinfo('localhost', 80)"],
                           capture_output=True, text=True, timeout=60)
    assert probe.returncode != 0 and "tripwire: socket.getaddrinfo" in probe.stderr
    assert "socket.getaddrinfo" in tripped(app)
    (app / ".venv" / "act-tripwire.log").unlink()


def test_negative_control_the_base_interpreter_is_refused_by_the_worker_itself(app):
    session = proto.new_token()
    request = proto.new_request(proto.ACTION_PLAN, [K], session=session)
    path = proto.write_request(app, request)
    argv = list(proto.worker_launch(app, path, session).argv)
    argv[0] = str(Path(getattr(sys, "_base_executable", "") or sys.executable))
    done = subprocess.run(argv, cwd=app / "scripts", capture_output=True, text=True, timeout=120)
    result = proto.decode_result(proto.read_message_file(path.with_name("result.json")), request_id=request.request_id)
    assert done.returncode == 4 and result["error"]["code"] == proto.WRONG_INTERPRETER


def test_negative_control_an_ambient_pythonpath_cannot_choose_the_workers_code(app, tmp_path):
    planted = tmp_path / "planted"
    (planted / "tts").mkdir(parents=True)
    marker = tmp_path / "PLANTED-RAN"
    (planted / "tts" / "__init__.py").write_text("", encoding="utf-8")
    (planted / "tts" / "optional_setup_worker.py").write_text(
        f"open({str(marker)!r}, 'w').close()\n", encoding="utf-8")
    # The scripts/ folder precedes PYTHONPATH for -m, so a planted 'tts' alone cannot prove -E. A planted stdlib module
    # can: PYTHONPATH precedes the standard library, so without -E this 'argparse' would be the one imported.
    (planted / "argparse.py").write_text(f"open({str(marker)!r}, 'w').close()\n", encoding="utf-8")
    session = proto.new_token()
    request = proto.new_request(proto.ACTION_PLAN, [K], session=session)
    path = proto.write_request(app, request)
    spec = proto.worker_launch(app, path, session)
    leaky = proto.LaunchSpec(spec.argv, spec.cwd, {**spec.env, "PYTHONPATH": str(planted)}, spec.request_path,
                             spec.result_path)  # the scrub bypassed on purpose: -E alone must hold
    run = proto.WorkerRun(app, leaky, request)
    run.start()
    assert run.wait(120)["state"] == proto.SUCCEEDED and not marker.exists()


# --------------------------------------------------------------------------- #
# Task C — the pre-venv import set, proved in a bare interpreter
# --------------------------------------------------------------------------- #
FORBIDDEN_PRE_VENV = ("subprocess", "socket", "ssl", "urllib.request", "http.client", "tkinter", "_tkinter",
                      "threading", "ctypes", "tts.qwen3_setup", "tts.qwen3_process", "shared.bootstrap")
ALLOWED_PROJECT = {"shared", "shared.optional_setup_protocol", "shared.spacy_store", "shared.venv_layout", "tts",
                   "tts.model_assets",
                   "tts.optional_setup", "tts.qwen3_runtime", "tts.voice_registry"}
PRE_VENV_PROBE = '''\
import json, sys
sys.path.insert(0, {scripts!r})
from shared import optional_setup_protocol
from tts import optional_setup
{extra}
optional_setup.plan_to_json(optional_setup.estimate(optional_setup_protocol.COMPONENTS))
print(json.dumps(sorted(sys.modules)))
'''


def pre_venv_modules(tmp_path: Path, extra: str = "") -> list[str]:
    base = Path(getattr(sys, "_base_executable", "") or sys.executable)
    probe = PRE_VENV_PROBE.format(scripts=str(REPO / "scripts"), extra=extra)
    done = subprocess.run([str(base), "-I", "-S", "-c", probe], cwd=tmp_path, capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def pre_venv_violations(modules: list[str]) -> list[str]:
    project = {m for m in modules if m.split(".")[0] in ("shared", "tts")}
    foreign = [m for m in modules if m.split(".")[0] not in sys.stdlib_module_names
               and m.split(".")[0] not in ("shared", "tts", "__main__")]
    return sorted(set(foreign) | (project - ALLOWED_PROJECT) | {m for m in FORBIDDEN_PRE_VENV if m in modules})


def test_the_pre_venv_planning_path_is_standard_library_only_and_process_free(tmp_path):
    modules = pre_venv_modules(tmp_path)
    assert pre_venv_violations(modules) == []
    assert ALLOWED_PROJECT <= set(modules)


def test_negative_control_the_pre_venv_check_catches_the_installer_and_its_network_modules(tmp_path):
    modules = pre_venv_modules(tmp_path, extra="from tts import qwen3_setup")
    violations = pre_venv_violations(modules)
    assert {"tts.qwen3_setup", "subprocess", "socket"} <= set(violations)


# --------------------------------------------------------------------------- #
# Production preservation: planning the real installation reads, and changes nothing
# --------------------------------------------------------------------------- #
def _fingerprint(paths: list[Path]) -> dict:
    out = {}
    for path in paths:
        try:
            info = os.lstat(path)
            out[str(path)] = (info.st_size, info.st_mtime_ns)
        except FileNotFoundError:
            out[str(path)] = None
    return out


def test_planning_the_real_installation_is_read_only_offline_and_never_claims_unproved_health(tripwire):
    hub = REPO / "files" / "runtime-data" / "models" / "huggingface" / "hub"
    watched = [REPO / "files" / "runtime-data" / "qwen3" / "state.json", REPO / "files" / "runtime-data" / "qwen3",
               REPO / ".venv" / "engines" / "qwen3" / "pyvenv.cfg", REPO / ".venv-qwen3" / "pyvenv.cfg",
               proto.exchange_root(REPO), hub, hub / "models--hexgrad--Kokoro-82M" / "refs" / "main",
               hub / "models--ResembleAI--chatterbox-turbo" / "refs" / "main", rt.models_root()]
    watched += [rt.marker_path(k) for k in rt.MODEL_KEYS]
    before = _fingerprint(watched)
    data = osu.plan_to_json(osu.plan(ALL))  # no health facts, no hardware probe
    assert _fingerprint(watched) == before and tripwire == []
    assert all(c["readiness"] in proto.READINESS for c in data["components"])
    assert component(data, K)["readiness"] != proto.READY and component(data, C)["readiness"] != proto.READY
    assert data["hardware"]["gpu"]["probed"] is False


# =========================================================================== #
# P05B Stage 1 — Task A: a consent is bound to the plan that was shown
# =========================================================================== #
def covers(consent, plan, shown=None):
    return proto.consent_covers(consent, plan, estimate=shown)


def altered(plan: dict, unit_id: str, **changes) -> dict:
    """*plan* as the caller's own fresh plan, with one unit changed (the rule is tested against what a plan can say)."""
    plan = json.loads(json.dumps(plan))
    unit(plan, unit_id).update(changes)
    plan["acquisition_fingerprint"] = proto.acquisition_fingerprint(plan)
    return plan


def test_every_unit_names_its_exact_pinned_source(world):
    data = as_json(ALL, health=HEALTHY)
    sources = {u["id"]: u["source"] for u in data["units"]}
    assert sources["kokoro-model"] == f"hf:{assets.KOKORO_REPO}@{assets.KOKORO_REVISION}"
    assert sources["kokoro-voice:af_heart"] == sources["kokoro-model"]
    assert sources["chatterbox-model"] == f"hf:{assets.CHATTERBOX_REPO}@{assets.CHATTERBOX_REVISION}"
    assert sources["spacy-english"] == f"wheel:{assets.SPACY_WHEEL_URL}#sha256:{assets.SPACY_WHEEL_SHA256}"
    assert sources["qwen3-engine"] == f"pip-lock:qwen3-requirements.txt@sha256:{rt.requirements_sha256()}"
    spec = rt.model_spec("base")
    assert sources["qwen3-model:base"] == f"hf:{spec.repo}@{spec.revision}#manifest-sha256:{spec.manifest_sha256()}"
    assert [u for u, s in sources.items() if s is None] == []  # spaCy's English model is pinned since Stage 2
    shown = {u["id"]: u["source"] for u in estimate_json(ALL)["units"]}
    assert shown == {u: sources[u] for u in shown}  # the estimate names exactly the same sources
    assert data["schema"] == osu.PLAN_SCHEMA == 3
    assert data["acquisition_fingerprint"] == proto.acquisition_fingerprint(data)


def test_a_forged_or_unrelated_fingerprint_authorises_nothing(world, tripwire):
    data = as_json([C], health=HEALTHY)
    real = osu.consent_for(data)
    assert covers(real, data) == (True, "", "ok")
    other = osu.consent_for(as_json([C, CV], health=HEALTHY))  # a real fingerprint, of another plan
    for forged in ("0" * 64, "f" * 64, other.acquisition_fingerprint, data["fingerprint"]):
        ok, code, _ = covers(dataclasses.replace(real, acquisition_fingerprint=forged), data)
        assert (ok, code) == (False, proto.CONSENT_STALE), forged
    # The right fingerprint with terms that are not the plan's (more units, more bytes): refused too.
    inflated = dataclasses.replace(real, units=real.units + ("qwen3-engine",), download_bytes=real.download_bytes * 9)
    assert covers(inflated, data)[:2] == (False, proto.BAD_CONSENT)
    shown = estimate_json([C])
    pre = osu.consent_for(shown)
    for forged in ("0" * 64, real.acquisition_fingerprint):
        assert covers(dataclasses.replace(pre, acquisition_fingerprint=forged), data, shown)[:2] == (
            False, proto.BAD_CONSENT)
    assert covers(pre, data)[:2] == (False, proto.BAD_CONSENT)  # an estimate consent needs the reproduced estimate
    assert covers(pre, data, estimate_json([C, K]))[:2] == (False, proto.BAD_CONSENT)  # ...for the same choices
    assert covers(pre, estimate_json([C]), shown)[:2] == (False, proto.MALFORMED)  # checked only against a main plan
    assert tripwire == []


def test_same_units_and_bytes_but_a_changed_source_or_scope_is_a_different_plan(world, monkeypatch):
    before = as_json([K], health={K: True}, spacy=True)
    shown = estimate_json([K])
    exact, pre = osu.consent_for(before), osu.consent_for(shown)
    # Scoped, never monkeypatch.undo(): that would also undo the sandbox's repo_root and reach the real installation.
    with monkeypatch.context() as patch:
        patch.setattr(assets, "KOKORO_REVISION", "9" * 40)  # another commit; same files, same sizes
        after = as_json([K], health={K: True}, spacy=True)
        assert after["acquire_units"] == before["acquire_units"] and after["totals"] == before["totals"]
        assert covers(exact, after)[:2] == (False, proto.CONSENT_STALE)
        assert covers(pre, after, estimate_json([K]))[:2] == (False, proto.BAD_CONSENT)  # not the estimate given to
    assert rt.repo_root() == world  # still inside the sandbox
    before = as_json([CV])
    rt.nested_venv_dir().mkdir(parents=True)  # the missing engine becomes a broken one: same units, same bytes
    after = as_json([CV])
    assert after["acquire_units"] == before["acquire_units"]
    assert after["totals"]["download"] == before["totals"]["download"]
    assert (component(before, CV)["consent_scope"], component(after, CV)["consent_scope"]) == ("install", "repair")
    assert covers(osu.consent_for(before), after)[:2] == (False, proto.CONSENT_STALE)


def test_immaterial_changes_do_not_invalidate_an_exact_consent(world, monkeypatch):
    before = as_json([CV])
    consent = osu.consent_for(before)
    monkeypatch.setattr(rt, "gpu_probe", lambda: rt.GpuInfo("RTX Test", 12288))
    rt._GPU_CACHE.clear()
    after = as_json([CV], probe=True)  # different hardware facts and wording; nothing that would be fetched changed
    assert after["fingerprint"] != before["fingerprint"]
    assert after["acquisition_fingerprint"] == before["acquisition_fingerprint"]
    assert covers(consent, after) == (True, "", "ok")


def test_a_legitimate_estimate_refines_into_a_smaller_main_plan(world, tripwire):
    shown = estimate_json(ALL)
    consent = osu.consent_for(shown)
    install_environment(world)
    install_model(world, "customvoice")
    install_kokoro(world, without={assets.kokoro_voice_name(v) for v in osu.kokoro_roster()})  # the model only
    data = as_json(ALL, health=HEALTHY, spacy=True)
    assert component(data, CV)["readiness"] == proto.READY
    assert not {"qwen3-engine", "kokoro-model", "spacy-english"} & set(data["acquire_units"])
    assert data["totals"]["download"]["bytes"] < consent.download_bytes
    assert covers(consent, data, shown) == (True, "", "ok")
    assert tripwire == []


def test_an_estimate_consent_never_stretches_to_cover_more(world):
    shown = estimate_json(ALL)
    consent = osu.consent_for(shown)
    data = as_json(ALL, health=HEALTHY, spacy=True)
    assert covers(consent, data, shown)[0]
    cases = {
        "more than was confirmed": altered(data, "chatterbox-model", download=fig(CHATTERBOX_ALL + 1, proto.APPROXIMATE)),
        "is not known": altered(data, "kokoro-model", download=fig(None, proto.UNKNOWN)),
        "different source": altered(data, "qwen3-model:base", source="hf:someone/else@" + "1" * 40),
        "serves a choice": altered(data, "kokoro-model", components=[K, C]),
    }
    extra = json.loads(json.dumps(data))
    extra["units"].append({**unit(data, "kokoro-model"), "id": "kokoro-voice:zz_new", "label": "Kokoro voice zz_new"})
    extra["acquire_units"].append("kokoro-voice:zz_new")
    extra["acquisition_fingerprint"] = proto.acquisition_fingerprint(extra)
    cases["was not confirmed"] = extra
    for words, plan_ in cases.items():
        ok, code, why = covers(consent, plan_, shown)
        assert (ok, code) == (False, proto.CONSENT_STALE) and words in why, (words, why)


def test_unknown_size_is_listed_and_agreed_never_counted_as_zero(world, monkeypatch):
    # Every Kokoro size is pinned since Stage 2, so the rule is exercised on what a plan can say: a pinned unit whose
    # size is shown as unknown (a Qwen3 repair below is the real case).
    voice = f"kokoro-voice:{osu.kokoro_roster()[0]}"
    data = altered(as_json([K], health={K: True}, spacy=True), voice, download=fig(None, proto.UNKNOWN))
    consent = osu.consent_for(data)
    assert consent.unknown_units == (voice,) and voice in consent.units
    assert consent.download_bytes == 44 + 5 * 8  # the known part only: the unknown voice is not a zero
    assert covers(consent, data) == (True, "", "ok")
    assert covers(dataclasses.replace(consent, unknown_units=()), data)[:2] == (False, proto.BAD_CONSENT)
    shown = altered(estimate_json([K]), voice, download=fig(None, proto.UNKNOWN))
    pre = osu.consent_for(shown)
    assert voice in pre.unknown_units
    assert covers(pre, data, shown) == (True, "", "ok")  # shown as unknown, agreed as unknown, still unknown
    ok, code, why = covers(pre, altered(data, voice, download=fig(5, proto.MANIFEST)), shown)
    assert (ok, code) == (False, proto.CONSENT_STALE) and "must be confirmed" in why  # unknown -> known is new terms
    # A repair whose size only a full check can tell: listed as unknown, and the known total is not presented as all.
    install_environment(world)
    install_model(world, "customvoice")
    (rt.model_spec("customvoice").directory / "model.safetensors").unlink()
    repair = osu.consent_for(as_json([CV]))
    assert repair.scopes == {CV: "repair"} and repair.unknown_units == ("qwen3-model:customvoice",)
    assert repair.download_bytes == 0 and repair.units == ("qwen3-model:customvoice",)


def test_an_unpinned_source_is_refused_whoever_confirmed_it(world, monkeypatch):
    roster = osu.kokoro_roster()
    monkeypatch.delitem(assets.KOKORO_FILES, assets.kokoro_voice_name(roster[0]))  # a voice with no pinned identity
    shown = estimate_json([K])
    data = as_json([K], health={K: True}, spacy=True)
    assert f"kokoro-voice:{roster[0]}" in data["acquire_units"]
    for consent, estimate in ((osu.consent_for(data), None), (osu.consent_for(shown), shown)):
        ok, code, why = covers(consent, data, estimate)
        assert (ok, code) == (False, proto.SOURCE_UNPINNED) and roster[0] in why
    (world / "scripts" / "qwen3-requirements.txt").unlink()  # no lock file: the engine has no pinned source either
    data = as_json([CV])
    assert unit(data, "qwen3-engine")["source"] is None
    assert covers(osu.consent_for(data), data)[:2] == (False, proto.SOURCE_UNPINNED)


def test_install_and_repair_are_agreed_per_component_and_never_stretched(world):
    install_environment(world)
    install_model(world, "customvoice")
    (rt.model_spec("customvoice").directory / "model.safetensors").unlink()  # verified once, now damaged
    data = as_json([C, CV], health=HEALTHY)
    consent = osu.consent_for(data)
    assert consent.scopes == {C: proto.SCOPE_INSTALL, CV: proto.SCOPE_REPAIR}
    assert covers(consent, data) == (True, "", "ok")
    for scopes in ({C: "install", CV: "install"}, {C: "repair", CV: "repair"}, {C: "install", CV: None}):
        assert covers(dataclasses.replace(consent, scopes=scopes), data)[:2] == (False, proto.BAD_CONSENT), scopes
    shown = estimate_json([C, CV])
    ok, code, why = covers(osu.consent_for(shown), data, shown)
    assert (ok, code) == (False, proto.CONSENT_STALE) and "repair" in why


@pytest.mark.parametrize("state", [proto.UNVERIFIED, proto.BUSY, proto.BAD_BUNDLE, proto.UNSUPPORTED])
def test_states_that_permit_no_acquisition_stay_distinct_and_cannot_be_consented(world, monkeypatch, state):
    kwargs = {"health": HEALTHY, "spacy": True}
    if state == proto.UNVERIFIED:
        kwargs["health"] = {}
    elif state == proto.BUSY:
        kwargs["busy"] = [C]
    elif state == proto.UNSUPPORTED:
        kwargs["python"] = (3, 13)
    else:
        monkeypatch.setattr(rt, "reference_status", lambda voice: (False, "Male 4's recording is missing."))
    data = as_json([C], **kwargs)
    assert component(data, C)["readiness"] == state and component(data, C)["consent_scope"] is None
    with pytest.raises(proto.ProtocolError) as caught:
        osu.consent_for(data)
    assert caught.value.code == proto.NOT_ACQUIRABLE and f"is {state}" in str(caught.value)
    shown = estimate_json([C])
    ok, code, why = covers(osu.consent_for(shown), data, shown)
    assert (ok, code) == (False, proto.NOT_ACQUIRABLE) and f"is {state}" in why


def test_an_unsupported_choice_cannot_be_consented_even_from_the_estimate(world, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(proto.ProtocolError) as caught:
        osu.consent_for(estimate_json([K, CV]))
    assert caught.value.code == proto.NOT_ACQUIRABLE


# =========================================================================== #
# P05B Stage 1 — Task B: fail-closed publication, claims, untrustworthy results
# =========================================================================== #
def stand_in_spec(root: Path, request_path: Path) -> proto.LaunchSpec:
    return proto.LaunchSpec(("never-started",), root / "scripts", {}, request_path,
                            request_path.with_name(proto.RESULT_NAME))


def install_request(components, *, session=SESSION, **plan_kwargs) -> proto.Request:
    consent = osu.consent_for(as_json(components, **plan_kwargs))
    return proto.new_request(proto.ACTION_INSTALL, components, session=session, consent=consent)


def test_without_atomic_publication_nothing_is_published_never_half(tmp_path, monkeypatch):
    def no_links(*args, **kwargs):
        raise OSError(errno.EXDEV, "hard links are not supported here")
    monkeypatch.setattr(os, "link", no_links)
    path = tmp_path / "result.json"
    with pytest.raises(proto.ProtocolError) as caught:
        proto.publish_once(path, b'{"state": "succeeded"}')
    assert caught.value.code == proto.PUBLICATION_UNAVAILABLE
    assert list(tmp_path.iterdir()) == []  # neither the result nor its temporary
    with pytest.raises(proto.ProtocolError):
        proto.write_request(tmp_path, proto.new_request(proto.ACTION_PLAN, [K], session=SESSION))
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]  # no request, so no worker could ever start


def test_a_worker_that_cannot_publish_atomically_publishes_nothing_and_the_parent_fails_closed(world, monkeypatch):
    request = proto.new_request(proto.ACTION_PLAN, [K], session=SESSION)
    path = proto.write_request(world, request)
    real_link = os.link

    def no_result_links(src, dst, *args, **kwargs):
        if Path(dst).name == proto.RESULT_NAME:
            raise OSError(errno.EXDEV, "hard links are not supported here")
        return real_link(src, dst, *args, **kwargs)
    monkeypatch.setattr(os, "link", no_result_links)
    code = worker.main(["--request", str(path), "--result", str(path.with_name("result.json")), "--session", SESSION],
                       repo_root=world, home_check=lambda r: "", facts=facts())
    assert code == proto.EXIT_NO_RESULT and sorted(p.name for p in path.parent.iterdir()) == ["claim", "request.json"]
    result = proto.WorkerRun(world, stand_in_spec(world, path), request).result()
    assert result["state"] == proto.FAILED and result["forced"] and "could not be recorded" in result["error"]["message"]
    assert not path.with_name("result.json").exists()


SUCCESS_WITHOUT_PROOF = "success-without-proof"


@pytest.mark.parametrize("content", [b'{"protocol": "act-optional-setup", "vers', b"", b"[]", SUCCESS_WITHOUT_PROOF],
                         ids=["truncated", "empty", "not-an-object", "success-without-proof"])
def test_a_partial_or_unproved_success_is_never_accepted(world, content):
    request = install_request([C], health={C: True})
    path = proto.write_request(world, request)
    if content == SUCCESS_WITHOUT_PROOF:
        content = proto.encode(proto.make_result(request.request_id, proto.SUCCEEDED, plan={}))
    path.with_name("result.json").write_bytes(content)  # a writer that bypassed the atomic publication
    result = proto.WorkerRun(world, stand_in_spec(world, path), request).result()
    assert result["state"] == proto.FAILED and result["forced"] and result["error"]["code"] == proto.MALFORMED


def test_results_vouch_only_for_what_was_requested(world):
    plan_request = proto.new_request(proto.ACTION_PLAN, [C], session=SESSION)
    rid = plan_request.request_id
    for bad in (proto.make_result(rid, proto.SUCCEEDED, plan={}, verified=[C]),
                proto.make_result(rid, proto.FAILED, error=(proto.INTERNAL, "x"), verified=[K])):
        with pytest.raises(proto.ProtocolError):
            proto.decode_result(proto.encode(bad), request_id=rid, request=plan_request)
    request = install_request([C], health={C: True})
    rid = request.request_id
    proto.decode_result(proto.encode(proto.make_result(rid, proto.SUCCEEDED, plan={}, verified=[C])), request_id=rid,
                        request=request)
    partial = proto.make_result(rid, proto.FAILED, error=(proto.HEALTH_UNPROVED, "x"), verified=[C])
    assert proto.decode_result(proto.encode(partial), request_id=rid, request=request)["verified"] == [C]
    with pytest.raises(ValueError):
        proto.make_result(rid, proto.SUCCEEDED, verified=["edge"])


def test_a_result_reached_through_a_junction_is_never_believed(tmp_path):
    root, outside = tmp_path / "app", tmp_path / "outside"
    request = proto.new_request(proto.ACTION_PLAN, [K], session=SESSION)
    forged = outside / request.request_id
    forged.mkdir(parents=True)
    (forged / "result.json").write_bytes(proto.encode(proto.make_result(request.request_id, proto.SUCCEEDED,
                                                                        plan={})))
    proto.exchange_root(root).mkdir(parents=True)
    if not _junction(proto.exchange_dir(root, request.request_id), forged):
        pytest.skip("this account cannot create a junction")
    result = proto.WorkerRun(root, stand_in_spec(root, proto.exchange_dir(root, request.request_id) / "request.json"),
                             request).result()
    assert result["state"] == proto.FAILED and result["error"]["code"] == proto.UNSAFE_PATH


def test_a_consent_record_folder_reached_through_a_junction_is_refused(tmp_path):
    root, outside = tmp_path / "app", tmp_path / "outside"
    outside.mkdir()
    proto.exchange_root(root).mkdir(parents=True)
    if not _junction(proto.exchange_root(root) / proto.CONSENTS_DIR, outside):
        pytest.skip("this account cannot create a junction")
    with pytest.raises(proto.ProtocolError) as caught:
        proto.claim_consent(root, "a" * 32, "b" * 32)
    assert caught.value.code == proto.UNSAFE_PATH and list(outside.iterdir()) == []
    with pytest.raises(proto.ProtocolError):
        proto.claim_consent(root, "../" + "a" * 29, "b" * 32)


def test_a_second_worker_on_the_same_request_never_runs_it(world, no_acquisition):
    request = proto.new_request(proto.ACTION_PLAN, [K], session=SESSION)
    path = proto.write_request(world, request)
    assert proto.claim_request(world, request.request_id) is True  # the first worker
    assert proto.claim_request(world, request.request_id) is False
    code = worker.main(["--request", str(path), "--result", str(path.with_name("result.json")), "--session", SESSION],
                       repo_root=world, home_check=lambda r: "", facts=facts())
    assert code == proto.EXIT_NO_RESULT and not path.with_name("result.json").exists()


# =========================================================================== #
# P05B Stage 1 — Task D: the operation lifecycle (stand-in acquirers only; nothing is ever fetched)
# =========================================================================== #
class StandInAcquirer:
    """Puts the planned Chatterbox files into the sandbox -- a few bytes, never a download."""

    available = True

    def __init__(self, root: Path, *, complete=True, units=None, error=None, write=True, wait_for_cancel=False):
        self.root, self.complete, self.units, self.error = root, complete, units, error
        self.write, self.wait_for_cancel = write, wait_for_cancel
        self.calls = 0

    def acquire(self, plan, consent, *, progress, cancel_check):
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.wait_for_cancel:
            deadline = time.monotonic() + 10
            while not cancel_check() and time.monotonic() < deadline:
                time.sleep(0.01)
            return osl.AcquisitionReport(False, (), "stopped")
        if self.write:
            install_chatterbox(self.root)
        progress({"unit": "chatterbox-model", "done": 1, "total": 1})
        return osl.AcquisitionReport(self.complete, tuple(plan["acquire_units"]) if self.units is None else self.units)


PROVED = {C: True}


def test_a_consented_acquisition_succeeds_only_once_its_components_are_proved_working(world, tripwire, capsys):
    request = install_request([C], health=PROVED)
    acquirer = StandInAcquirer(world)
    code, result = run_main(world, request, facts=facts(health=PROVED), acquirer=acquirer, health=lambda c: PROVED)
    assert code == 0 and result["state"] == proto.SUCCEEDED and result["verified"] == [C] and acquirer.calls == 1
    assert component(result["plan"], C)["readiness"] == proto.READY
    assert [e["kind"] for e in events(capsys, request.request_id)] == ["started", "readiness", "plan", "progress"]
    assert (proto.exchange_root(world) / proto.CONSENTS_DIR / request.consent.consent_id).is_file()  # spent
    assert tripwire == []


@pytest.mark.parametrize("proof", [{}, {C: None}, {C: False}], ids=["none", "unproved", "broken"])
def test_without_a_post_install_proof_there_is_no_success(world, proof):
    request = install_request([C], health=PROVED)
    code, result = run_main(world, request, facts=facts(health=PROVED), acquirer=StandInAcquirer(world),
                            health=lambda c: proof)
    assert code == proto.EXIT_CODES[proto.FAILED]
    assert result["error"]["code"] == proto.HEALTH_UNPROVED and result["verified"] == []


@pytest.mark.parametrize("kwargs, working", [({"complete": False}, [C]),
                                             ({"units": ("chatterbox-model", "qwen3-engine")}, []), ({"units": ()}, []),
                                             ({"error": OSError(28, "No space left on device")}, [])],
                         ids=["incomplete", "more-than-planned", "less-than-planned", "error"])
def test_an_incomplete_failed_or_unexpected_acquisition_is_never_a_success(world, kwargs, working):
    request = install_request([C], health=PROVED)
    code, result = run_main(world, request, facts=facts(health=PROVED), acquirer=StandInAcquirer(world, **kwargs),
                            health=lambda c: PROVED)
    assert code == proto.EXIT_CODES[proto.FAILED] and result["state"] == proto.FAILED
    # An incomplete report is still a failure, but the components that do work are named (proved afresh, Stage 2);
    # an acquisition outside the plan, or one that raised, is not trusted enough to be proved at all.
    assert result["error"]["code"] == proto.ACQUISITION_FAILED and result["verified"] == working


def test_cancel_reaches_an_active_acquisition_and_ends_it_cancelled(world):
    request = install_request([C], health=PROVED)
    path = proto.write_request(world, request)
    acquirer = StandInAcquirer(world, wait_for_cancel=True)
    timer = threading.Timer(0.3, lambda: proto.publish_once(path.with_name(proto.CANCEL_NAME), b"cancel\n"))
    timer.start()
    code = worker.main(["--request", str(path), "--result", str(path.with_name("result.json")), "--session", SESSION],
                       repo_root=world, home_check=lambda r: "", facts=facts(health=PROVED), acquirer=acquirer,
                       health=lambda c: PROVED)
    timer.join()
    result = proto.decode_result(proto.read_message_file(path.with_name("result.json")),
                                 request_id=request.request_id, request=request)
    assert code == proto.EXIT_CODES[proto.CANCELLED_STATE] and result["state"] == proto.CANCELLED_STATE
    assert acquirer.calls == 1 and result["verified"] == []


def test_a_consent_is_acted_on_once_and_never_replayed(world):
    consent = osu.consent_for(as_json([C], health=PROVED))
    acquirer = StandInAcquirer(world, write=False)  # reports done but leaves the plan unchanged
    first = proto.new_request(proto.ACTION_INSTALL, [C], session=SESSION, consent=consent)
    _, result = run_main(world, first, facts=facts(health=PROVED), acquirer=acquirer, health=lambda c: PROVED)
    assert result["error"]["code"] == proto.HEALTH_UNPROVED and acquirer.calls == 1
    duplicate = proto.new_request(proto.ACTION_INSTALL, [C], session=SESSION, consent=consent)  # same confirmation
    _, result = run_main(world, duplicate, facts=facts(health=PROVED), acquirer=acquirer, health=lambda c: PROVED)
    assert result["error"]["code"] == proto.CONSENT_USED and acquirer.calls == 1  # never acquired twice
    after_restart = proto.new_request(proto.ACTION_INSTALL, [C], session=SESSION, consent=consent)
    _, result = run_main(world, after_restart, session="b" * 32, facts=facts(health=PROVED), acquirer=acquirer)
    assert result["error"]["code"] == proto.WRONG_SESSION and acquirer.calls == 1


def test_an_install_with_nothing_to_acquire_is_proved_not_performed(world, no_acquisition):
    install_chatterbox(world)
    request = install_request([C], health=PROVED)
    assert request.consent.units == ()
    code, result = run_main(world, request, facts=facts(health=PROVED), health=lambda c: PROVED,
                            acquirer=osl.DisabledAcquirer())  # explicit lifecycle test seam; production is gated
    assert code == 0 and result["state"] == proto.SUCCEEDED and result["verified"] == [C]
    assert not (proto.exchange_root(world) / proto.CONSENTS_DIR).exists()


def test_an_operation_settles_exactly_one_terminal_outcome_and_never_goes_back(world):
    request = proto.new_request(proto.ACTION_PLAN, [C], session=SESSION)

    def operation():
        return osl.Operation(request, planner=lambda health: as_json([C]), estimator=dict, emit=lambda k, p: None,
                             cancel_check=lambda: False)
    op = operation()
    assert op.run()["state"] == proto.SUCCEEDED and op.history == ["planning", "validating", "succeeded"]
    with pytest.raises(RuntimeError):
        op._finish(proto.FAILED, error=(proto.INTERNAL, "a second outcome"))
    with pytest.raises(RuntimeError):
        op._enter(osl.ACQUIRING)
    fresh = operation()
    fresh._enter(osl.VALIDATING)
    with pytest.raises(RuntimeError):
        fresh._enter(osl.VALIDATING)
    assert osl.DisabledAcquirer.available is False
    with pytest.raises(RuntimeError):
        osl.DisabledAcquirer().acquire({}, None, progress=print, cancel_check=lambda: False)


def test_the_worker_command_line_cannot_steer_acquisition_and_only_a_consent_can_start_one():
    import inspect
    import re

    options = re.findall(r'add_argument\("(--[a-z-]+)"', inspect.getsource(worker.main))
    assert options == ["--request", "--result", "--session"]  # nothing to choose a source, a unit or skip a check
    assert inspect.signature(worker.main).parameters["acquirer"].default is None  # None = the production acquirer
    source = inspect.getsource(worker.run)  # v0.7.0: built only for an install request, after which the consent rules
    assert "if request.action == proto.ACTION_INSTALL and acquirer is None:" in source
    assert isinstance(osl.Operation(proto.new_request(proto.ACTION_PLAN, [K], session=SESSION), planner=dict,
                                    estimator=dict, emit=print, cancel_check=bool).acquirer, osl.DisabledAcquirer)


# =========================================================================== #
# P05B Stage 1 — Task B: the real process tree, contained and ended (a second disposable app, no tripwire)
# =========================================================================== #
@pytest.fixture(scope="module")
def plain_app(tmp_path_factory):
    """Another disposable copy of the app with a pip-less ``.venv`` and no tripwire: these tests start grandchildren
    on purpose, to prove that cancelling, timing out or finishing a run ends every one of them."""
    base = Path(getattr(sys, "_base_executable", "") or sys.executable)
    root = tmp_path_factory.mktemp("disposable-plain-app")
    for package in ("shared", "tts"):
        shutil.copytree(REPO / "scripts" / package, root / "scripts" / package,
                        ignore=shutil.ignore_patterns("__pycache__"))
    (root / "files").mkdir()
    made = subprocess.run([str(base), "-I", "-m", "venv", "--without-pip", str(root / ".venv")], capture_output=True,
                          text=True, timeout=300)
    assert made.returncode == 0, made.stderr
    return root


GRANDCHILD_CODE = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(45)"


def wait_for_pid(path: Path, bound_s: float = 30.0) -> int:
    deadline = time.monotonic() + bound_s
    while time.monotonic() < deadline:
        try:
            text = path.read_text()
        except OSError:
            text = ""
        if text:
            return int(text)
        time.sleep(0.02)
    raise AssertionError(f"{path.name} never appeared")


def tree_run(app: Path, tmp_path: Path, then: str, *, on_event=None) -> tuple[proto.WorkerRun, int, int]:
    """A stand-in worker that starts a grandchild (through the venv launcher, as an installer would) and then does
    *then*. Returns the run and the real interpreter PIDs of the worker and of the grandchild."""
    session = proto.new_token()
    request = proto.new_request(proto.ACTION_PLAN, [K], session=session)
    path = proto.write_request(app, request)
    spec = proto.worker_launch(app, path, session)
    own, grand = tmp_path / "own.pid", tmp_path / "grand.pid"
    script = ("import os, subprocess, sys, time\n"
              f"subprocess.Popen([sys.executable, '-c', {GRANDCHILD_CODE!r}, {str(grand)!r}])\n"
              f"open({str(own)!r}, 'w').write(str(os.getpid()))\n"
              f"while not (os.path.exists({str(grand)!r}) and open({str(grand)!r}).read()): time.sleep(0.02)\n"
              + then)
    stand_in = proto.LaunchSpec((spec.argv[0], "-c", script), spec.cwd, spec.env, spec.request_path, spec.result_path)
    run = proto.WorkerRun(app, stand_in, request, on_event=on_event)
    run.start()
    return run, wait_for_pid(own), wait_for_pid(grand)


def test_a_timed_out_worker_and_its_grandchild_are_ended_and_the_job_is_left_empty(plain_app, tmp_path):
    run, worker_pid, grandchild_pid = tree_run(plain_app, tmp_path, "time.sleep(120)\n")
    started = time.monotonic()
    result = run.wait(1.0, cancel_grace_s=1.0)
    assert time.monotonic() - started < 30
    assert process_gone(worker_pid) and process_gone(grandchild_pid)
    assert result["state"] == proto.FAILED and result["error"]["code"] == proto.TIMED_OUT and result["forced"]
    if os.name == "nt":  # every launcher and interpreter was a member, and none is left
        assert run.lingering == 0 and run.members_seen >= 3


def test_stopping_a_worker_ends_its_grandchild_too(plain_app, tmp_path):
    run, worker_pid, grandchild_pid = tree_run(plain_app, tmp_path, "time.sleep(120)\n")
    result = run.stop(grace_s=1.0)
    assert process_gone(worker_pid) and process_gone(grandchild_pid)
    assert result["state"] == proto.CANCELLED_STATE and result["forced"] and run.terminated


def test_a_grandchild_left_behind_by_a_worker_that_exited_is_ended_with_the_run(plain_app, tmp_path):
    run, worker_pid, grandchild_pid = tree_run(plain_app, tmp_path, "")  # the worker exits; its child would live on
    started = time.monotonic()
    result = run.wait(60)
    assert time.monotonic() - started < 30  # not held up by the grandchild's copy of the output pipe
    assert process_gone(worker_pid) and process_gone(grandchild_pid)
    assert not run.terminated and not run.timed_out
    assert result["state"] == proto.FAILED and result["error"]["code"] == proto.NO_RESULT


def test_a_failing_event_callback_cannot_strand_the_worker(plain_app, tmp_path):
    count = 3000  # far more than a pipe buffer holds: a dead reader would block the worker for good
    session = proto.new_token()
    request = proto.new_request(proto.ACTION_PLAN, [K], session=session)
    path = proto.write_request(plain_app, request)
    spec = proto.worker_launch(plain_app, path, session)
    cancel = str(path.with_name(proto.CANCEL_NAME))
    script = ("import os, time\n"
              "from shared import optional_setup_protocol as p\n"
              f"for i in range({count}):\n"
              f"    print(p.encode_event({request.request_id!r}, i, 'progress', {{'i': i, 'pad': 'x' * 100}}), "
              "flush=True)\n"
              "deadline = time.monotonic() + 30\n"
              f"while not os.path.exists({cancel!r}) and time.monotonic() < deadline: time.sleep(0.02)\n")
    stand_in = proto.LaunchSpec((spec.argv[0], "-c", script), spec.cwd, spec.env, spec.request_path, spec.result_path)
    calls = []

    def broken(event):
        calls.append(event["seq"])
        raise RuntimeError("the progress display went away")
    run = proto.WorkerRun(plain_app, stand_in, request, on_event=broken)
    run.start()
    result = run.wait(25)
    assert not run.timed_out and not run.terminated  # it was cancelled and stopped by itself, promptly
    assert calls == [0] and len(run.events) == count and run.callback_errors == [
        "RuntimeError: the progress display went away"]
    assert run.cancel_sent and result["state"] == proto.CANCELLED_STATE


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object containment")
def test_a_worker_that_cannot_be_contained_is_never_run(plain_app, tmp_path, monkeypatch):
    from tts import qwen3_process

    def refused():
        raise OSError(5, "job objects are not allowed here")
    monkeypatch.setattr(qwen3_process, "ProcessJob", refused)
    session = proto.new_token()
    request = proto.new_request(proto.ACTION_PLAN, [K], session=session)
    path = proto.write_request(plain_app, request)
    spec = proto.worker_launch(plain_app, path, session)
    marker = tmp_path / "RAN"
    stand_in = proto.LaunchSpec((spec.argv[0], "-c", f"open({str(marker)!r}, 'w').close()"), spec.cwd, spec.env,
                                spec.request_path, spec.result_path)
    run = proto.WorkerRun(plain_app, stand_in, request)
    with pytest.raises(qwen3_process.ContainmentUnavailable):
        run.start()
    time.sleep(1.0)
    assert not marker.exists() and run.process is None
    result = run.result()
    assert result["state"] == proto.FAILED and result["error"]["code"] == proto.CONTAINMENT_UNAVAILABLE
    assert proto.decode_result(proto.read_message_file(spec.result_path), request_id=request.request_id) == result
