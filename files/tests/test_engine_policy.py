"""macOS P4C: one platform capability policy decides which voice engines the app offers (plan §12.F, §19 P4C).

Owner decisions (2026-11-16): Q2=A and the P4A acceptance. macOS offers Edge 5 + Kokoro 9 + OmniVoice 6 = 20 voices;
Chatterbox Turbo and Qwen3-TTS are SKIPPED BY OWNER DECISION there: absent from every macOS surface, and refused at
every dispatch, setup, repair and probe entry with a plain message, never switched to another voice, never downloaded,
never imported. Windows keeps all 34 voices and every setup choice exactly as released.

Every test names the platform it asks about -- ``shared.engine_policy``'s ``platform=`` argument, its
``current_platform`` seam, or ``sys.platform`` where the code under test reads it -- so the file runs the same on a Mac
and on Windows. Nothing here is Windows-native evidence: the Windows rows prove the shared logic only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import engine_policy  # noqa: E402
from shared import optional_setup_protocol as proto  # noqa: E402
from tts import epub2tts_gui as panel_module  # noqa: E402
from tts import voice_install  # noqa: E402
from tts import voice_registry as vr  # noqa: E402

from test_tts_importing import (  # noqa: E402,F401
    _Stubs,
    make_panel,
    output_base,
    panel_tree,
    sources,
    stubs,
    tk_root,
)
from test_tts_jobs import accept, direct_panel, finish, landed, run_attempt  # noqa: E402,F401
from test_chatterbox_integration import ChatterboxStub  # noqa: E402
from test_qwen3_gui import Qwen3Stub  # noqa: E402
from test_setup_log_follow import native_theme, run_as_toplevel, settle, setup_log  # noqa: E402,F401

REPO = Path(__file__).resolve().parents[2]
MAC, WINDOWS = "darwin", "win32"
OTHER_ENGINES = ("Chatterbox", "Qwen3", "Qwen")

#: The macOS roster, pinned by identity and label (owner decision, 2026-11-16): registry order, nothing renamed.
MAC_ROSTER = [
    ("edge", "en-US-SteffanNeural", "Edge Male - Steffan (en-US)"),
    ("edge", "en-US-AndrewNeural", "Edge Male - Andrew (en-US)"),
    ("edge", "en-US-AriaNeural", "Edge Female - Aria (en-US)"),
    ("edge", "en-US-AvaNeural", "Edge Female - Ava (en-US)"),
    ("edge", "en-US-JennyNeural", "Edge Female - Jenny (en-US)"),
    ("kokoro", "af_heart", "Kokoro Female (Default) - Heart (en-US)"),
    ("kokoro", "af_bella", "Kokoro Female - Bella (en-US)"),
    ("kokoro", "am_michael", "Kokoro Male - Michael (en-US)"),
    ("kokoro", "am_fenrir", "Kokoro Male - Fenrir (en-US)"),
    ("kokoro", "am_puck", "Kokoro Male - Puck (en-US)"),
    ("kokoro", "am_onyx", "Kokoro Male - Onyx (en-US)"),
    ("kokoro", "bf_emma", "Kokoro Female - Emma (en-UK)"),
    ("kokoro", "bm_george", "Kokoro Male - George (en-UK)"),
    ("kokoro", "bm_daniel", "Kokoro Male - Daniel (en-UK)"),
    ("omnivoice", "omnivoice-female-1", "OmniVoice - Female 1"),
    ("omnivoice", "omnivoice-female-2", "OmniVoice - Female 2"),
    ("omnivoice", "omnivoice-male-1", "OmniVoice - Male 1"),
    ("omnivoice", "omnivoice-male-2", "OmniVoice - Male 2"),
    ("omnivoice", "omnivoice-male-3", "OmniVoice - Male 3"),
    ("omnivoice", "omnivoice-male-4", "OmniVoice - Male 4"),
]
MAC_HEADINGS = ["Microsoft Edge TTS — English (US)", "Kokoro Local AI — American English",
                "Kokoro Local AI — British English", "OmniVoice Local AI — Cloned Voices"]
NOT_ON_MAC = [v for v in vr.VOICES if v.backend in ("chatterbox", "qwen3")]


@pytest.fixture
def on_platform(monkeypatch):
    """Answer the policy for *name*, whatever this computer is (the policy's own seam; nothing else changes)."""
    def use(name: str) -> None:
        monkeypatch.setattr(engine_policy, "current_platform", lambda: name)
    return use


def mentions_another_engine(text: str) -> bool:
    return any(word in text for word in OTHER_ENGINES)


# =========================================================================== #
# The policy itself
# =========================================================================== #
def test_the_policy_knows_every_registered_engine_and_every_setup_component():
    assert engine_policy.ENGINES == vr.BACKENDS
    assert set(engine_policy.COMPONENT_ENGINES) == set(proto.COMPONENTS)
    assert set(engine_policy.ENGINE_NAMES) == set(engine_policy.ENGINES)
    assert engine_policy.COMPONENT_ENGINES[proto.OMNIVOICE] == "omnivoice"
    assert {engine_policy.COMPONENT_ENGINES[c] for c in (proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE)} == {"qwen3"}


def test_macos_offers_edge_kokoro_and_omnivoice_and_windows_every_engine():
    assert engine_policy.offered_engines(MAC) == ("edge", "kokoro", "omnivoice")
    assert engine_policy.offered_engines(WINDOWS) == ("edge", "kokoro", "chatterbox", "qwen3", "omnivoice")
    for engine in ("chatterbox", "qwen3"):
        assert not engine_policy.is_offered(engine, MAC) and engine_policy.is_offered(engine, WINDOWS)
    assert not engine_policy.is_offered("piper", WINDOWS) and not engine_policy.is_offered("piper", MAC)
    assert engine_policy.offered_components(proto.COMPONENTS, MAC) == (proto.KOKORO, proto.OMNIVOICE)
    assert engine_policy.offered_components(proto.COMPONENTS, WINDOWS) == proto.COMPONENTS
    assert not engine_policy.component_offered("chatterbox-model", WINDOWS)  # a unit is not a component


def test_the_platform_is_the_real_one_read_at_call_time(monkeypatch):
    monkeypatch.setattr(sys, "platform", MAC)
    assert engine_policy.current_platform() == MAC and not engine_policy.is_offered("chatterbox")
    monkeypatch.setattr(sys, "platform", WINDOWS)
    assert engine_policy.current_platform() == WINDOWS and engine_policy.is_offered("chatterbox")


@pytest.mark.parametrize("engine", ["chatterbox", "qwen3"])
def test_a_refusal_says_what_is_not_offered_that_nothing_happened_and_what_to_choose(engine):
    message = engine_policy.not_offered_message(engine, MAC)
    assert message.startswith(engine_policy.ENGINE_NAMES[engine] + " voices are not available in this app on macOS")
    assert "nothing was started, installed or downloaded" in message
    assert message.endswith("Choose a Microsoft Edge TTS, Kokoro or OmniVoice voice instead.")
    with pytest.raises(engine_policy.EngineNotOffered) as caught:
        engine_policy.require_offered(engine, MAC)
    assert caught.value.engine == engine and str(caught.value) == message
    for offered in engine_policy.ENGINES:
        engine_policy.require_offered(offered, WINDOWS)  # Windows refuses nothing it released
    for offered in engine_policy.MACOS_ENGINES:
        engine_policy.require_offered(offered, MAC)


# =========================================================================== #
# The roster
# =========================================================================== #
def test_the_macos_roster_is_exactly_the_twenty_voices_in_registry_order():
    offered = vr.offered_voices(MAC)
    assert [(v.backend, v.voice_id, v.display_label) for v in offered] == MAC_ROSTER
    assert vr.offered_labels(MAC) == [label for _b, _v, label in MAC_ROSTER]
    assert [sum(v.backend == b for v in offered) for b in ("edge", "kokoro", "omnivoice")] == [5, 9, 6]
    order = [v.key for v in vr.VOICES]
    assert [order.index(v.key) for v in offered] == sorted(order.index(v.key) for v in offered)


def test_the_macos_engine_headings_are_only_the_offered_engines():
    headings = list(dict.fromkeys(v.group_label for v in vr.offered_voices(MAC)))
    assert headings == MAC_HEADINGS
    assert not any(mentions_another_engine(h) for h in headings)


def test_windows_keeps_all_34_identities_labels_and_order():
    assert vr.offered_voices(WINDOWS) == vr.VOICES and len(vr.VOICES) == 34
    assert vr.offered_labels(WINDOWS) == vr.display_labels()
    assert len({v.key for v in vr.VOICES}) == 34


def test_the_default_voice_is_steffan_and_offered_on_both_platforms():
    assert vr.DEFAULT_VOICE_KEY == ("edge", "en-US-SteffanNeural")
    for platform in (MAC, WINDOWS):
        assert vr.offered_labels(platform)[0] == vr.default_voice_label() == "Edge Male - Steffan (en-US)"


def test_a_default_voice_a_mac_would_not_offer_is_refused(monkeypatch):
    monkeypatch.setattr(vr, "DEFAULT_VOICE_KEY", ("chatterbox", "chatterbox-female-1"))
    assert vr.registry_problems(vr.VOICES) == [
        "the default voice chatterbox/chatterbox-female-1 is not offered on macOS; the default must be offered everywhere"]
    monkeypatch.setattr(vr, "DEFAULT_VOICE_KEY", ("edge", "en-US-SteffanNeural"))
    assert vr.registry_problems(vr.VOICES) == []


def test_nothing_is_removed_every_identity_and_recording_stays_registered():
    assert {v.backend for v in NOT_ON_MAC} == {"chatterbox", "qwen3"} and len(NOT_ON_MAC) == 14
    assert len(vr.REFERENCE_RECORDINGS) == 18 and len(vr.VOICE_REFERENCES) == 18
    for voice in NOT_ON_MAC:
        assert vr.voice_by_key(*voice.key) is voice and vr.get_voice(voice.display_label) is voice


def test_all_six_omnivoice_voices_are_offered_on_a_mac_with_their_own_recordings():
    omni = [v for v in vr.offered_voices(MAC) if v.backend == "omnivoice"]
    assert [v.voice_id for v in omni] == [f"omnivoice-{n}" for n in
                                          ("female-1", "female-2", "male-1", "male-2", "male-3", "male-4")]
    for voice in omni:
        parts = vr.reference_recording_parts(*voice.key)
        assert parts[2] == "OmniVoice" and REPO.joinpath(*parts).is_file()
        assert voice_install.component_for(*voice.key) == proto.OMNIVOICE  # still installable on a Mac


# =========================================================================== #
# First-run setup (the wizard)
# =========================================================================== #
def test_the_mac_first_run_offers_exactly_kokoro_and_omnivoice():
    from shared import bootstrap

    mac = bootstrap.optional_choices_for(MAC)
    assert [(c, label, default) for c, label, default, _note in mac] == [
        ("kokoro", "Kokoro voices", True), ("omnivoice", "OmniVoice — Six Cloned Voices", False)]
    assert mac[0][3] == bootstrap.WINDOWS_OPTIONAL_CHOICES[0][3], "Kokoro's choice is Windows' own, unchanged"
    assert mac[1][3] == bootstrap.OMNIVOICE_MAC_NOTE and "Apple Silicon" in mac[1][3] and "NON-COMMERCIAL" in mac[1][3]
    assert not any(mentions_another_engine(" ".join(row[1:2] + row[3:])) for row in mac)
    assert bootstrap.OPTIONAL_CHOICES == bootstrap.optional_choices_for(sys.platform)


def test_windows_first_run_is_exactly_as_released():
    from shared import bootstrap

    windows = bootstrap.optional_choices_for(WINDOWS)
    assert windows is bootstrap.WINDOWS_OPTIONAL_CHOICES
    assert [(c, d) for c, _l, d, _n in windows] == [("kokoro", True), ("chatterbox", False),
                                                   ("qwen3-customvoice", False), ("qwen3-base", False),
                                                   ("omnivoice", False)]


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


@pytest.mark.parametrize("skip_kokoro_default", [False, True])
def test_the_mac_first_run_window_shows_two_choices_and_names_no_other_engine(
        monkeypatch, tk_root, setup_log, native_theme, skip_kokoro_default):
    from shared import bootstrap

    monkeypatch.setattr(bootstrap, "OPTIONAL_CHOICES", bootstrap.optional_choices_for(MAC))
    monkeypatch.setattr(bootstrap, "optional_estimates", lambda: {})
    monkeypatch.setattr(bootstrap, "run_setup", lambda *a, **k: pytest.fail("Cancel started setup"))
    seen: dict = {}

    def script(window):
        settle(window)
        widgets = list(_descendants(window))
        checks = [w for w in widgets if isinstance(w, tk.ttk.Checkbutton)]
        seen["labels"] = [c.cget("text") for c in checks]
        seen["values"] = [bool(window.getvar(c.cget("variable"))) for c in checks]
        seen["texts"] = [str(w.cget("text")) for w in widgets if isinstance(w, (tk.ttk.Label, tk.ttk.Checkbutton,
                                                                                  tk.ttk.Button))]
        window.destroy()

    run_as_toplevel(monkeypatch, tk_root, script)
    bootstrap.run_with_gui(skip_kokoro_default=skip_kokoro_default)
    assert seen["labels"] == ["Kokoro voices", "OmniVoice — Six Cloned Voices"]
    assert seen["values"] == [not skip_kokoro_default, False], "Kokoro's default and its skip are unchanged"
    assert not [t for t in seen["texts"] if mentions_another_engine(t)], "no word about an engine a Mac does not offer"


# =========================================================================== #
# Optional setup: plans, consent, acquisition and health
# =========================================================================== #
@pytest.fixture
def mac_world(world, monkeypatch):  # noqa: F811 - the optional-setup sandbox, as a Mac
    monkeypatch.setattr(sys, "platform", MAC)
    return world


from test_optional_tts_setup import as_json, component, sandbox, tiny_assets, world  # noqa: E402,F401


def test_a_mac_plan_refuses_chatterbox_and_qwen3_and_acquires_nothing_for_them(mac_world):
    from tts import optional_setup as osu

    data = as_json([proto.KOKORO, proto.CHATTERBOX, proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE],
                   health={proto.KOKORO: True, proto.CHATTERBOX: True})
    for name, engine in ((proto.CHATTERBOX, "chatterbox"), (proto.QWEN3_CUSTOMVOICE, "qwen3"),
                         (proto.QWEN3_BASE, "qwen3")):
        assert component(data, name)["readiness"] == proto.UNSUPPORTED
        assert component(data, name)["reason"] == engine_policy.not_offered_message(engine, MAC)
        assert component(data, name)["units"] == []
    assert not any(c in u["components"] for u in data["units"] for c in (proto.CHATTERBOX, proto.QWEN3_CUSTOMVOICE,
                                                                         proto.QWEN3_BASE))
    assert not any(u.startswith(("chatterbox", "qwen3")) for u in data["acquire_units"])
    assert component(data, proto.KOKORO)["readiness"] != proto.UNSUPPORTED, "Kokoro is planned as before"
    assert data["hardware"]["qwen3"] == engine_policy.not_offered_message("qwen3", MAC)
    assert not any(mentions_another_engine(line) for line in data["hardware"]["limits"])
    assert not mentions_another_engine(data["base_packages"]["note"])
    with pytest.raises(proto.ProtocolError) as caught:
        osu.consent_for(as_json([proto.KOKORO, proto.CHATTERBOX], health={proto.KOKORO: True}))
    assert caught.value.code == proto.NOT_ACQUIRABLE


def test_the_mac_first_run_estimate_refuses_them_too(mac_world):
    from tts import optional_setup as osu

    data = osu.plan_to_json(osu.estimate([proto.KOKORO, proto.CHATTERBOX, proto.QWEN3_BASE]))
    assert [component(data, c)["readiness"] for c in (proto.CHATTERBOX, proto.QWEN3_BASE)] == [proto.UNSUPPORTED] * 2
    assert not any(u.startswith(("chatterbox", "qwen3")) for u in data["acquire_units"])
    with pytest.raises(proto.ProtocolError) as caught:
        osu.consent_for(data)
    assert caught.value.code == proto.NOT_ACQUIRABLE


def test_on_windows_the_same_plan_still_offers_chatterbox_and_qwen3(world):
    data = as_json([proto.CHATTERBOX, proto.QWEN3_CUSTOMVOICE], health={proto.CHATTERBOX: True})
    assert component(data, proto.CHATTERBOX)["readiness"] != proto.UNSUPPORTED
    assert component(data, proto.QWEN3_CUSTOMVOICE)["readiness"] != proto.UNSUPPORTED


def test_the_acquirer_refuses_an_unoffered_component_before_any_download(on_platform):
    from tts import optional_setup_acquire as osa

    on_platform(MAC)
    plan = {"acquire_units": ["chatterbox-model"], "units": [
        {"id": "chatterbox-model", "label": "Chatterbox Turbo model", "components": [proto.CHATTERBOX],
         "source": "x"}], "totals": {"disk": {"bytes": 1}, "temp": {"bytes": 0}}}
    acquirer = osa.RealAcquirer(opener=lambda *a, **k: pytest.fail("opened the network"),
                                runner=lambda *a, **k: pytest.fail("started a process"),
                                disk_free=lambda root: pytest.fail("asked about disk"))
    with pytest.raises(osa.AcquisitionRefused) as caught:
        acquirer.acquire(plan, consent=None, progress=lambda event: None, cancel_check=lambda: False)
    assert str(caught.value) == engine_policy.not_offered_message("chatterbox", MAC)
    assert acquirer.openers == []


def test_a_mac_health_check_never_probes_chatterbox(on_platform, monkeypatch):
    from tts import optional_setup_health as osh

    asked = []
    monkeypatch.setattr(osh, "kokoro_health", lambda root, **k: (asked.append("kokoro"), (True, ""))[1])
    monkeypatch.setattr(osh, "chatterbox_health", lambda root, **k: (asked.append("chatterbox"), (True, ""))[1])
    on_platform(MAC)
    assert osh.local_health(REPO, [proto.KOKORO, proto.CHATTERBOX], cancel_check=lambda: False) == {
        proto.KOKORO: True}
    assert asked == ["kokoro"]
    on_platform(WINDOWS)
    assert osh.local_health(REPO, [proto.KOKORO, proto.CHATTERBOX], cancel_check=lambda: False) == {
        proto.KOKORO: True, proto.CHATTERBOX: True}


def test_install_and_continue_never_offers_chatterbox_or_qwen3_on_a_mac(on_platform):
    on_platform(MAC)
    for voice in NOT_ON_MAC:
        assert voice_install.component_for(*voice.key) is None
        assert voice_install.installable(*voice.key, f"x {voice_install.NOT_INSTALLED} y") is None
    assert voice_install.component_for("kokoro", "af_heart") == proto.KOKORO
    on_platform(WINDOWS)
    assert voice_install.component_for("chatterbox", "chatterbox-female-1") == proto.CHATTERBOX
    assert voice_install.component_for("qwen3", "qwen3-female-1") == proto.QWEN3_BASE


# =========================================================================== #
# The TTS panel: the list, a restored selection, Start, the worker and Retry
# =========================================================================== #
def test_the_mac_dropdown_lists_exactly_the_twenty_voices(make_panel, on_platform):
    on_platform(MAC)
    panel = make_panel()
    values = [str(v) for v in panel.voice_combo.cget("values")]
    assert values == [label for _b, _v, label in MAC_ROSTER]
    assert not any(mentions_another_engine(v) for v in values)
    assert panel.selected_voice_label.get() == "Edge Male - Steffan (en-US)"


def test_the_windows_dropdown_keeps_all_34(make_panel, on_platform):
    on_platform(WINDOWS)
    panel = make_panel()
    assert [str(v) for v in panel.voice_combo.cget("values")] == vr.display_labels()


@pytest.mark.parametrize("voice", [NOT_ON_MAC[0], NOT_ON_MAC[-1]], ids=lambda v: v.backend)
def test_a_restored_selection_naming_an_unoffered_engine_becomes_the_default_and_is_logged(
        make_panel, on_platform, voice):
    on_platform(MAC)
    panel = make_panel()
    panel.selected_voice_label.set(voice.display_label)
    panel._on_voice_selected()
    assert panel.selected_voice_label.get() == vr.default_voice_label()
    assert panel.voice_var.get() == "en-US-SteffanNeural"
    assert panel.log.summary[-1] == (f'The voice "{voice.display_label}" is not available on macOS; the default voice, '
                                     'Edge Male - Steffan (en-US), is selected instead.')
    assert "Engine: Microsoft Edge TTS" in panel.backend_label_var.get()


def test_on_windows_the_same_selection_is_kept(make_panel, on_platform):
    on_platform(WINDOWS)
    panel = make_panel(chatterbox_status=lambda voice_id: (True, ""))
    label = vr.label_for("chatterbox", "chatterbox-female-1")
    panel.selected_voice_label.set(label)
    panel._on_voice_selected()
    assert panel.selected_voice_label.get() == label and panel.voice_var.get() == "chatterbox-female-1"


@pytest.mark.parametrize("voice", [NOT_ON_MAC[0], NOT_ON_MAC[-1]], ids=lambda v: v.backend)
def test_start_refuses_an_unoffered_voice_before_anything_is_frozen_or_reserved(
        make_panel, output_base, tmp_path, stubs, on_platform, monkeypatch, voice):
    from tkinter import messagebox

    chatterbox = ChatterboxStub().install(monkeypatch)
    qwen3 = Qwen3Stub().install(monkeypatch)
    warned = []
    monkeypatch.setattr(messagebox, "showwarning", lambda title, message, **k: warned.append((title, message)))
    on_platform(MAC)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", qwen3_status=qwen3.status,
                                  chatterbox_status=chatterbox.status)
    panel.selected_voice_label.set(voice.display_label)  # as if restored or imported: no selection event
    assert accept(panel) == {}, "nothing was started"
    assert warned == [("Voice unavailable", engine_policy.not_offered_message(voice.backend, MAC))]
    assert chatterbox.calls == [] and qwen3.calls == [] and panel._snapshot is None
    assert not any(Path(output_base).rglob("*")), "no run folder was reserved"


def test_a_frozen_run_that_reaches_the_worker_is_refused_before_the_engine_is_called(
        make_panel, output_base, tmp_path, stubs, on_platform, monkeypatch):
    chatterbox = ChatterboxStub().install(monkeypatch)
    on_platform(WINDOWS)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", chatterbox_status=chatterbox.status)
    panel.selected_voice_label.set(vr.label_for("chatterbox", "chatterbox-female-1"))
    panel._on_voice_selected()
    captured = accept(panel)
    assert captured["params"]["backend"] == "chatterbox"
    on_platform(MAC)  # the run reaches dispatch on a platform that does not offer it
    params = finish(panel, captured)
    assert chatterbox.calls == [] and landed(params) == []
    record = panel._result.failures.records[-1]
    assert not record.retryable and record.technical_detail == (
        "EngineNotOffered: " + engine_policy.not_offered_message("chatterbox", MAC))


def test_retry_of_an_unoffered_engine_is_refused_and_starts_nothing(
        make_panel, output_base, tmp_path, stubs, on_platform, monkeypatch):
    from tkinter import messagebox

    chatterbox = ChatterboxStub(failing="bad").install(monkeypatch)
    on_platform(WINDOWS)
    panel, _chosen = direct_panel(make_panel, tmp_path, "bad.txt", chatterbox_status=chatterbox.status)
    panel.selected_voice_label.set(vr.label_for("chatterbox", "chatterbox-female-1"))
    panel._on_voice_selected()
    run_attempt(panel)
    assert panel._result.has_retryable and len(chatterbox.calls) == 1
    warned = []
    monkeypatch.setattr(messagebox, "showwarning", lambda title, message, **k: warned.append((title, message)))
    on_platform(MAC)
    assert accept(panel, panel.retry_failed) == {}
    assert warned == [("Voice unavailable", engine_policy.not_offered_message("chatterbox", MAC))]
    assert len(chatterbox.calls) == 1, "the engine was not called again"


# =========================================================================== #
# The engines' own entry points, the sample helper and the CLI
# =========================================================================== #
def test_the_chatterbox_entry_points_refuse_on_a_mac_before_reading_or_loading(on_platform, monkeypatch, tmp_path):
    from tts import chatterbox_synth as cbx

    monkeypatch.setattr(cbx, "_MODEL_CACHE", {})
    monkeypatch.setattr(cbx, "select_device", lambda: pytest.fail("chose a device"))
    on_platform(MAC)
    missing = str(tmp_path / "absent.txt")  # the guard comes first: no FileNotFoundError
    calls = [lambda: cbx.chatterbox_file_to_mp3(missing, str(tmp_path / "o.mp3"), "chatterbox-female-1"),
             lambda: cbx.synthesize_text_to_mp3("Hi.", str(tmp_path / "o.mp3"), "chatterbox-female-1"),
             lambda: cbx.synthesize_text_to_wav("Hi.", str(tmp_path / "o.wav"), "chatterbox-female-1"),
             lambda: cbx._get_model("cpu")]
    for call in calls:
        with pytest.raises(engine_policy.EngineNotOffered):
            call()
    assert not any(tmp_path.iterdir())
    on_platform(WINDOWS)
    with pytest.raises(FileNotFoundError):
        cbx.chatterbox_file_to_mp3(missing, str(tmp_path / "o.mp3"), "chatterbox-female-1")


def test_the_qwen3_entry_point_refuses_on_a_mac_even_when_its_availability_seam_says_yes(on_platform, tmp_path):
    from tts import qwen3_synth

    source = tmp_path / "one.txt"
    source.write_text("Hello there.", encoding="utf-8")
    on_platform(MAC)
    with pytest.raises(engine_policy.EngineNotOffered) as caught:
        qwen3_synth.qwen3_file_to_mp3(str(source), str(tmp_path / "o.mp3"), "qwen3-female-1",
                                      availability=lambda voice_id: (True, ""), python=tmp_path / "no-python",
                                      jobs_root=tmp_path / "jobs")
    assert caught.value.engine == "qwen3" and not (tmp_path / "jobs").exists() and not (tmp_path / "o.mp3").exists()


def test_samples_on_a_mac_cover_the_twenty_voices_and_refuse_the_rest(on_platform, monkeypatch, capsys):
    from tts import generate_voice_samples as gvs

    on_platform(MAC)
    assert [v.key for v in gvs._select([])] == [(b, v) for b, v, _l in MAC_ROSTER]
    assert gvs._select(["chatterbox"]) == [] and gvs._select(["qwen3"]) == []
    assert [v.key for v in gvs._refused(["chatterbox"])] == [v.key for v in NOT_ON_MAC if v.backend == "chatterbox"]
    with pytest.raises(engine_policy.EngineNotOffered):
        gvs._synthesize_for_voice(NOT_ON_MAC[0], "Hi.", Path("never.mp3"))
    for flag in ("--chatterbox-eval", "--chatterbox-candidates", "--qwen-eval=preflight"):
        monkeypatch.setattr(sys, "argv", ["generate_voice_samples.py", *flag.split("=")])
        monkeypatch.setattr(gvs, "run_chatterbox_evaluation", lambda *a, **k: pytest.fail("synthesised"))
        monkeypatch.setattr(gvs, "run_chatterbox_candidate_evaluation", lambda *a, **k: pytest.fail("synthesised"))
        monkeypatch.setattr(gvs, "_run_qwen_eval", lambda *a, **k: pytest.fail("synthesised"))
        assert gvs.main() == 2
    monkeypatch.setattr(sys, "argv", ["generate_voice_samples.py", "chatterbox"])
    monkeypatch.setattr(gvs, "_synthesize_for_voice", lambda *a, **k: pytest.fail("synthesised"))
    assert gvs.main() == 1
    out = capsys.readouterr().out
    assert engine_policy.not_offered_message("chatterbox", MAC) in out
    on_platform(WINDOWS)
    assert len(gvs._select([])) == 34 and gvs._refused(["chatterbox"]) == []


# =========================================================================== #
# Wording: the launcher, maintenance and repair; settings carry no voice
# =========================================================================== #
def test_the_launcher_describes_only_the_offered_engines_and_keeps_all_six_tools():
    import launcher

    mac = launcher.tts_description(MAC)
    assert "Edge TTS" in mac and "Kokoro" in mac and "OmniVoice" in mac and not mentions_another_engine(mac)
    assert launcher.tts_description(WINDOWS) == (
        "Convert PDF / TXT into a narrated MP3 using Edge TTS or the local Kokoro, Chatterbox and Qwen3 voices.")
    assert [tool.key for tool in launcher.TOOLS] == ["tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover",
                                                     "m4b_metadata"], "the five other tools are unchanged"
    assert launcher.TOOLS[0].description == launcher.tts_description(sys.platform)


def test_maintenance_and_repair_wording_on_a_mac_names_no_unoffered_engine():
    from shared import maintenance, preferences_ui

    mac = maintenance.catalog_for(MAC)
    windows = maintenance.catalog_for(WINDOWS)
    assert [a.asset_id for a in mac] == [a.asset_id for a in windows] == list(maintenance.ASSET_IDS)
    for asset in mac:
        assert not mentions_another_engine(asset.consequence + asset.effect_line), asset.asset_id
    assert [(a.relative_target, a.requires_post_exit, a.removes_target_itself, a.requires_engine_lease)
            for a in mac] == [(a.relative_target, a.requires_post_exit, a.removes_target_itself,
                               a.requires_engine_lease) for a in windows], "only the words differ"
    assert "Qwen3 voice engine is not part of this item" in windows[0].consequence
    assert maintenance.CATALOG == maintenance.catalog_for(sys.platform)
    assert not mentions_another_engine(preferences_ui.repair_confirm_text(MAC))
    assert "Qwen3 voice engine are kept" in preferences_ui.repair_confirm_text(WINDOWS)
    assert preferences_ui.REPAIR_CONFIRM_TEXT == preferences_ui.repair_confirm_text(sys.platform)


def test_no_setting_can_carry_a_voice_or_an_engine():
    from shared import config

    names = " ".join(str(key) for key in config.USER_STATE_SETTINGS).lower()
    assert not any(word in names for word in ("voice", "engine", "backend", "speaker"))
