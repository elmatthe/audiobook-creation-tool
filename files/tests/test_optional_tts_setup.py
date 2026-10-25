"""v0.7.0 P05A — optional voice setup: the planning contract, honest sizes, the worker protocol and its execution home.

Plan Revision 2 §5.4 (Q14-Q20, Q32). Everything runs offline. The planner is driven against the Qwen3 runtime sandbox
(``test_qwen3_runtime.sandbox``: a fake repository root with a tiny model manifest) plus a fake in-tree Hugging Face
cache and tiny stand-ins for the measured Kokoro/Chatterbox tables. Network and process creation are tripwired in
process; the real worker is also run as a child process inside a disposable copy of the app, in a pip-less venv built
from the base CPython 3.12, whose ``sitecustomize`` aborts on any socket or process event and records what was imported.
No real model, cache, environment or state file is written.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shared import optional_setup_protocol as proto
from shared import venv_layout
from tts import optional_setup as osu
from tts import optional_setup_worker as worker
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su
from test_qwen3_runtime import install_environment, install_model, make_engine, sandbox  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
ALL = proto.COMPONENTS
K, C, CV, B = proto.KOKORO, proto.CHATTERBOX, proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE
#: The sandbox manifest (test_qwen3_runtime): CustomVoice 58 bytes, Base 62, of which 39 are identical in both.
CV_BYTES, BASE_BYTES, SHARED_BYTES = 58, 62, 39
ENV_DOWNLOAD, ENV_INSTALLED, MARGIN = 3_100_000_000, 5_300_000_000, 2 * 10**9


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


@pytest.fixture
def tiny_assets(monkeypatch):
    """Tiny stand-ins for the measured upstream tables, so a 'model' is a few bytes."""
    monkeypatch.setattr(osu, "KOKORO_MODEL_FILES", {"config.json": 4, "kokoro-v1_0.pth": 40})
    monkeypatch.setattr(osu, "KOKORO_VOICE_FILES", {v: 5 for v in osu.kokoro_roster()})
    monkeypatch.setattr(osu, "CHATTERBOX_FILES", {"t3_turbo_v1.safetensors": 300, "s3gen.safetensors": 200,
                                                  "s3gen_meanflow.safetensors": 100, "vocab.json": 7})
    monkeypatch.setattr(osu, "SPACY_ENGLISH_INSTALLED_BYTES", 11)
    monkeypatch.setattr(osu, "BASE_PACKAGES_INSTALLED_BYTES", 1000)


KOKORO_ALL = 44 + 5 * 9  # model + nine roster voices
CHATTERBOX_ALL = 607


@pytest.fixture
def world(sandbox, tiny_assets, monkeypatch):  # noqa: F811 - pytest fixture injection
    """The sandbox with the bundled references and transcript bundle reported intact (their own tests prove those)."""
    monkeypatch.setattr(rt, "reference_status", lambda voice: (True, "ok"))
    monkeypatch.setattr(rt, "bundle_status", lambda: (True, "ok"))
    return sandbox


def facts(*, health=None, busy=(), spacy=False, python=(3, 12), is_64bit=True, probe=False) -> osu.Facts:
    return osu.Facts(health=health or {}, busy=frozenset(busy), python=python, is_64bit=is_64bit,
                     probe_hardware=probe, package_present=lambda name: spacy and name == osu.SPACY_ENGLISH)


HEALTHY = {K: True, C: True}


def hf_snapshot(root: Path, repo: str, files: dict[str, int], *, revision: str = "1" * 40) -> Path:
    folder = root / "files" / "runtime-data" / "models" / "huggingface" / "hub" / ("models--" + repo.replace("/", "--"))
    (folder / "refs").mkdir(parents=True, exist_ok=True)
    (folder / "refs" / "main").write_text(revision, encoding="ascii")
    snapshot = folder / "snapshots" / revision
    for name, size in files.items():
        path = snapshot.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"k" * size)
    return snapshot


def install_kokoro(root: Path) -> Path:
    files = dict(osu.KOKORO_MODEL_FILES)
    files.update({f"voices/{v}.pt": size for v, size in osu.KOKORO_VOICE_FILES.items()})
    return hf_snapshot(root, osu.KOKORO_REPO, files)


def install_chatterbox(root: Path, *, without=()) -> Path:
    return hf_snapshot(root, osu.CHATTERBOX_REPO, {n: s for n, s in osu.CHATTERBOX_FILES.items() if n not in without})


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
    assert set(osu.kokoro_roster()) <= set(osu.KOKORO_VOICE_FILES), "every roster voice needs a measured size"
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


def test_kokoro_alone_lists_model_voices_and_the_lazy_spacy_package(world, tripwire):
    data = as_json([K], health={K: True})
    kokoro = component(data, K)
    assert kokoro["readiness"] == proto.MISSING and kokoro["consent_scope"] == proto.SCOPE_INSTALL
    assert data["acquire_units"] == ["kokoro-model", *(f"kokoro-voice:{v}" for v in osu.kokoro_roster()),
                                     "spacy-english"]
    assert data["totals"]["download"] == fig(KOKORO_ALL, proto.AT_LEAST)  # the spaCy wheel's size is not known
    assert data["totals"]["disk"] == fig(KOKORO_ALL + 11, proto.APPROXIMATE)
    assert unit(data, "spacy-english")["download"] == fig(None, proto.UNKNOWN)
    assert tripwire == []


def test_chatterbox_alone_counts_the_file_turbo_does_not_need_but_the_library_still_fetches(world):
    data = as_json([C], health={C: True})
    assert component(data, C)["readiness"] == proto.MISSING
    assert data["totals"]["download"] == fig(CHATTERBOX_ALL, proto.APPROXIMATE)
    install_chatterbox(world, without={"s3gen.safetensors"})  # everything Turbo loads is here
    data = as_json([C], health={C: True})
    assert component(data, C)["readiness"] == proto.READY and data["acquire_units"] == []


@pytest.mark.parametrize("name, model_bytes", [(CV, CV_BYTES), (B, BASE_BYTES)])
def test_each_qwen3_component_alone_is_the_shared_engine_plus_its_own_model(world, tripwire, name, model_bytes):
    data = as_json([name])
    assert component(data, name)["readiness"] == proto.MISSING
    assert data["acquire_units"] == ["qwen3-engine", f"qwen3-model:{proto.QWEN3_MODEL_KEYS[name]}"]
    assert data["totals"]["download"] == fig(ENV_DOWNLOAD + model_bytes, proto.APPROXIMATE)
    assert data["totals"]["disk"] == fig(ENV_INSTALLED + model_bytes, proto.APPROXIMATE)
    assert data["totals"]["temp"] == fig(ENV_DOWNLOAD + MARGIN, proto.APPROXIMATE)  # pip cache + installer margin
    assert tripwire == []


def test_both_qwen3_components_count_the_engine_and_the_shared_model_files_once(world):
    data = as_json([CV, B])
    engine = unit(data, "qwen3-engine")
    assert engine["components"] == [CV, B] and data["acquire_units"].count("qwen3-engine") == 1
    base = unit(data, "qwen3-model:base")
    assert base["download"] == fig(BASE_BYTES - SHARED_BYTES, proto.MANIFEST)
    assert base["local_copy"] == fig(SHARED_BYTES, proto.MANIFEST)  # copied or linked locally, not downloaded
    assert data["totals"]["download"] == fig(ENV_DOWNLOAD + CV_BYTES + BASE_BYTES - SHARED_BYTES, proto.APPROXIMATE)
    assert data["totals"]["temp"] == fig(ENV_DOWNLOAD + MARGIN, proto.APPROXIMATE)  # one engine, one margin
    # Negative control: the per-component figures DO include the engine each time; only the plan total dedupes.
    per_component = sum(component(data, c)["download"]["bytes"] for c in (CV, B))
    assert per_component == data["totals"]["download"]["bytes"] + ENV_DOWNLOAD


def test_all_four_together_is_the_deduplicated_union(world):
    data = as_json(list(reversed(ALL)), health=HEALTHY)  # any input order; the plan is canonical
    assert data["selected"] == list(ALL)
    expected = KOKORO_ALL + CHATTERBOX_ALL + ENV_DOWNLOAD + CV_BYTES + BASE_BYTES - SHARED_BYTES
    assert data["totals"]["download"] == fig(expected, proto.AT_LEAST)
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


def test_a_file_of_another_size_is_unverified_not_damaged_and_not_healthy(world):
    snapshot = install_kokoro(world)
    (snapshot / "kokoro-v1_0.pth").write_bytes(b"x" * 41)  # upstream is unpinned: maybe just newer
    data = as_json([K], health={K: True}, spacy=True)
    assert unit(data, "kokoro-model")["state"] == proto.UNVERIFIED
    assert component(data, K)["readiness"] == proto.UNVERIFIED and data["acquire_units"] == []


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
    monkeypatch.setattr(osu, "KOKORO_VOICE_FILES", {v: 5 for v in roster[1:]})  # one voice without a measurement
    data = as_json([K], health={K: True}, spacy=True)
    assert unit(data, f"kokoro-voice:{roster[0]}")["download"] == fig(None, proto.UNKNOWN)
    assert data["totals"]["download"]["basis"] == proto.AT_LEAST
    before = as_json([CV])
    manifest = rt.load_manifest()
    monkeypatch.setitem(manifest, "environment", {"approx_download_bytes": ENV_DOWNLOAD + 1, "approx_installed_bytes": 1})
    after = as_json([CV])
    assert after["fingerprint"] != before["fingerprint"]
    assert proto.consent_covers(osu.consent_for(before), after) == (
        False, "the download is now larger than was agreed (or no longer known)")


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
    expected = KOKORO_ALL + CHATTERBOX_ALL + ENV_DOWNLOAD + CV_BYTES + BASE_BYTES - SHARED_BYTES
    assert data["totals"]["download"] == fig(expected, proto.AT_LEAST)
    assert data["acquire_units"].count("qwen3-engine") == 1
    assert unit(data, "qwen3-model:base")["local_copy"] == fig(SHARED_BYTES, proto.MANIFEST)
    assert any("most each choice could cost" in n for n in data["notes"])
    assert tripwire == []


def test_the_pre_venv_estimate_on_another_platform_offers_no_qwen3(world, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    data = osu.plan_to_json(osu.estimate([K, CV]))
    assert component(data, CV)["readiness"] == proto.UNSUPPORTED
    assert not any(u.startswith("qwen3") for u in data["acquire_units"])


def test_consent_from_the_wizard_estimate_covers_the_exact_plan_and_nothing_more(world, monkeypatch):
    consent = osu.consent_for(osu.plan_to_json(osu.estimate(ALL)))
    assert consent.scope == proto.SCOPE_INSTALL and consent.components == ALL
    assert proto.consent_covers(consent, as_json(ALL, health=HEALTHY)) == (True, "ok")
    install_environment(world)
    install_model(world, "customvoice")
    (rt.model_spec("customvoice").directory / "model.safetensors").unlink()
    ok, why = proto.consent_covers(consent, as_json(ALL, health=HEALTHY))
    assert not ok and "repair consent" in why  # a repair is a different agreement
    narrower = osu.consent_for(osu.plan_to_json(osu.estimate([K])))
    ok, why = proto.consent_covers(narrower, as_json([K, CV], health=HEALTHY))
    assert not ok


def test_consent_never_covers_an_unverified_component(world):
    consent = osu.consent_for(osu.plan_to_json(osu.estimate([K])))
    ok, why = proto.consent_covers(consent, as_json([K]))  # Kokoro's engine not proved
    assert not ok and "unverified" in why


# --------------------------------------------------------------------------- #
# Task C — the request protocol
# --------------------------------------------------------------------------- #
SESSION = "a" * 32


def request_json(**changes) -> dict:
    message = proto.new_request(proto.ACTION_PLAN, [K, B], session=SESSION).to_json()
    message.update(changes)
    return message


def install_json(**consent_changes) -> dict:
    consent = {"scope": "install", "components": [K], "units": ["kokoro-model"], "download_bytes": 10,
               "plan_fingerprint": "f" * 64}
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


@pytest.mark.parametrize("version", [0, 2, 99])
def test_other_protocol_versions_are_refused(version):
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
    lambda: install_json(scope="everything"), lambda: install_json(components=[K, C]),
    lambda: install_json(units=["../x"]), lambda: install_json(units=["a", "a"]),
    lambda: install_json(download_bytes=-1), lambda: install_json(download_bytes=1.5),
    lambda: install_json(plan_fingerprint="0" * 63), lambda: install_json(extra=True),
])
def test_consent_must_be_explicit_and_exact(message):
    built = message()
    code = proto.MALFORMED if built["action"] == "install" and not built["components"] else proto.BAD_CONSENT
    refuse(built, code)


def test_a_complete_install_request_is_accepted():
    request = proto.decode_request(json.dumps(install_json()).encode(), session=SESSION)
    assert request.consent == proto.Consent("install", (K,), ("kokoro-model",), 10, "f" * 64)


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
    consent = osu.consent_for(osu.plan_to_json(osu.plan([K, CV], facts=facts(health=HEALTHY))))
    request = proto.new_request(proto.ACTION_INSTALL, [K, CV], session=SESSION, consent=consent)
    code, result = run_main(world, request, facts=facts(health=HEALTHY))
    assert code == proto.EXIT_CODES[proto.REFUSED]
    assert result["error"]["code"] == proto.ACQUISITION_UNAVAILABLE and "Nothing was downloaded" in result["error"]["message"]
    assert not (world / ".venv" / "engines").exists() and not rt.models_root().exists()
    assert tripwire == []


def test_an_install_request_whose_plan_grew_is_refused_as_stale_consent(world, no_acquisition):
    consent = osu.consent_for(osu.plan_to_json(osu.plan([CV], facts=facts())))
    smaller = proto.Consent(consent.scope, consent.components, consent.units, consent.download_bytes - 1,
                            consent.plan_fingerprint)
    request = proto.new_request(proto.ACTION_INSTALL, [CV], session=SESSION, consent=smaller)
    code, result = run_main(world, request, facts=facts())
    assert result["state"] == proto.REFUSED and result["error"]["code"] == proto.CONSENT_STALE


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
import atexit, json, os, sys
_LOG = os.path.join(sys.prefix, "act-tripwire.log")
_WATCH = ("socket.", "subprocess.Popen", "os.system", "os.startfile", "os.spawn", "os.posix_spawn", "os.exec",
          "urllib.Request", "http.client.connect")
def _hook(event, args):
    if event.startswith(_WATCH):
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


def launch(root: Path, request: proto.Request, *, session: str) -> proto.WorkerRun:
    path = proto.write_request(root, request)
    run = proto.WorkerRun(root, proto.worker_launch(root, path, session), request)
    run.start()
    return run


def test_the_worker_runs_in_the_apps_environment_and_acquires_nothing(app):
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
    # The copy has no references, no models and a pip-less environment: nothing is ready and nothing is assumed.
    assert got == {K: proto.UNVERIFIED, C: proto.BAD_BUNDLE, CV: proto.MISSING, B: proto.BAD_BUNDLE}
    assert tripped(app) == ""
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
    assert result["state"] == proto.CANCELLED_STATE and result["forced"] is True
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
ALLOWED_PROJECT = {"shared", "shared.optional_setup_protocol", "shared.venv_layout", "tts", "tts.optional_setup",
                   "tts.qwen3_runtime", "tts.voice_registry"}
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
