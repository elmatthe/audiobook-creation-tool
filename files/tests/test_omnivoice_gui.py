"""v0.8.0 Phase 2 -- the six OmniVoice voices in the TTS panel's existing queue.

Dispatch reads ``VoiceEntry.backend``; the voices route to ``omnivoice_file_to_mp3`` by voice id; the output is named by
the frozen label; an unavailable voice is reported with the engine's own sentence and refused at Start before a run is
reserved when installing cannot help (no NVIDIA GPU, a changed recording); otherwise (v0.8.0 Phase 3) the existing
Install & Continue offers the ``omnivoice`` component, and only an installed-and-rechecked voice starts the frozen run,
once. Cancel and the file-boundary run loop are the ones every local engine uses. **No synthesis runs**:
``tts.omnivoice_synth`` is a stub, and the review dialog is a stand-in (nothing is planned, downloaded or installed).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared.cancellation import ConversionCancelled  # noqa: E402
from tts import epub2tts_gui as panel_module  # noqa: E402
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
from test_tts_jobs import accept, direct_panel, landed, run_attempt  # noqa: E402,F401
from test_qwen3_gui import Qwen3Stub  # noqa: E402

OMNIVOICE = [(v.voice_id, v.display_label) for v in vr.VOICES if v.backend == "omnivoice"]


class OmniVoiceStub:
    """Stands in for ``tts.omnivoice_synth`` and answers the OmniVoice availability seam from a dictionary."""

    def __init__(self, *, available=None):
        self.calls: list[dict] = []
        self.status_requests: list[str] = []
        self.available = dict(available or {})
        self.cancel_at_chunk = None

    def status(self, voice_id: str) -> tuple[bool, str]:
        self.status_requests.append(voice_id)
        return self.available.get(voice_id, (True, "ok"))

    def omnivoice_file_to_mp3(self, source_path, output_mp3_path, voice_id, **kwargs):
        self.calls.append({"voice_id": voice_id, **kwargs})
        if self.cancel_at_chunk is not None:
            self.cancel_at_chunk()
            Path(output_mp3_path).write_bytes(b"a partly written file")
            raise ConversionCancelled("Conversion cancelled by user.")
        kwargs["progress_callback"](1, 1)
        Path(output_mp3_path).write_bytes(b"audio")

    def install(self, monkeypatch):
        module = types.ModuleType("tts.omnivoice_synth")
        module.omnivoice_file_to_mp3 = self.omnivoice_file_to_mp3
        monkeypatch.setitem(sys.modules, "tts.omnivoice_synth", module)
        return self


@pytest.fixture()
def omni(monkeypatch):
    return OmniVoiceStub().install(monkeypatch)


def offers(log: list):
    def installable(backend, voice_id, reason):
        from tts import voice_install

        component = voice_install.installable(backend, voice_id, reason)
        log.append((backend, component))
        return component
    return installable


def select(panel, label: str) -> None:
    panel.selected_voice_label.set(label)
    panel._on_voice_selected()


def test_the_six_voices_are_in_the_dropdown_after_every_earlier_voice(make_panel, omni):
    panel = make_panel(omnivoice_status=omni.status)
    values = list(panel.voice_combo["values"])
    assert values[-6:] == [label for _id, label in OMNIVOICE] and len(values) == 34


@pytest.mark.parametrize("voice_id,label", OMNIVOICE)
def test_each_voice_routes_to_the_omnivoice_engine_by_voice_id(make_panel, output_base, tmp_path, stubs, omni,
                                                              voice_id, label):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", omnivoice_status=omni.status)
    select(panel, label)
    params = run_attempt(panel)
    assert params["backend"] == "omnivoice"
    (call,) = omni.calls
    assert call["voice_id"] == voice_id and call["chunk_pause_ms"] == 700 and call["end_silence_ms"] == 0
    assert call["cancel_check"] == panel._controller.cancel_check
    assert landed(params) == [f"one-{label}.mp3"], "named by the frozen label, never the id"
    assert stubs.conversion_jobs == [] and stubs.kokoro_calls == []


def test_an_omnivoice_clone_never_reaches_its_qwen3_twin(make_panel, output_base, tmp_path, stubs, omni, monkeypatch):
    qwen3 = Qwen3Stub().install(monkeypatch)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", omnivoice_status=omni.status,
                                  qwen3_status=qwen3.status, qwen3_hardware=lambda: "")
    select(panel, "OmniVoice - Male 1")
    run_attempt(panel)
    select(panel, "Qwen3 - Male 1")
    run_attempt(panel)
    assert [c["voice_id"] for c in omni.calls] == ["omnivoice-male-1"]
    assert [c["voice_id"] for c in qwen3.calls] == ["qwen3-male-1"]


def test_the_engine_line_names_omnivoice_and_no_speed_control_or_qwen3_setup_is_shown(make_panel, omni):
    panel = make_panel(omnivoice_status=omni.status)
    select(panel, "OmniVoice - Female 2")
    assert panel.backend_label_var.get().startswith(f"Engine: {panel_module.OMNIVOICE_ENGINE_LABEL}  |")
    assert not panel.kokoro_speed_frm.winfo_manager() and not panel.edge_rate_frm.winfo_manager()
    assert not panel.qwen3_setup_btn.winfo_manager() and not panel.kokoro_notice_lbl.winfo_manager()
    assert omni.status_requests == ["omnivoice-female-2"]


def test_choosing_other_engines_asks_the_omnivoice_seam_nothing(make_panel, omni):
    panel = make_panel(omnivoice_status=omni.status)
    kokoro = next(v for v in vr.VOICES if v.backend == "kokoro")
    for label in (kokoro.display_label, vr.DEFAULT_VOICE_LABEL):
        select(panel, label)
    assert omni.status_requests == []


def test_an_unavailable_voice_installing_cannot_help_is_refused_at_start_without_an_install_offer(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    """No NVIDIA GPU (or a changed recording): the real ``voice_install.installable`` answers ``None``, so the voice's
    own sentence is shown and nothing is offered, frozen or reserved (v0.8.0 Phase 3: never a useless install)."""
    from tkinter import messagebox

    from tts import omnivoice_runtime as ov

    omni = OmniVoiceStub(available={"omnivoice-male-3": (False, ov.NO_GPU_MESSAGE)}).install(monkeypatch)
    monkeypatch.setattr(ov, "detect_gpu", lambda: None)
    asked: list = []
    warnings: list = []
    monkeypatch.setattr(messagebox, "showwarning", lambda title, message, **k: warnings.append((title, message)))
    monkeypatch.setattr(panel_module.output_paths, "reserve_run_directory",
                        lambda *a, **k: pytest.fail("a refused run reserved a directory"))
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", omnivoice_status=omni.status,
                                  installable=offers(asked),
                                  install_dialog=lambda *a: pytest.fail("an install that cannot help was offered"))
    select(panel, "OmniVoice - Male 3")
    assert panel._voice_available is False and panel.voice_status_var.get() == ov.NO_GPU_MESSAGE
    assert accept(panel) == {}, "no worker was started"
    assert warnings == [("Voice unavailable", ov.NO_GPU_MESSAGE)]
    assert asked == [("omnivoice", None)] and omni.calls == []


def _install_offer(monkeypatch, *, outcome: dict, make_available: bool):
    """A stand-in review dialog: records the offer and, like the real one, makes the voice available only by
    'installing' it. The real ``voice_install.installable`` decides the offer (installing would help: a GPU is present,
    the engine is not ready)."""
    from tts import omnivoice_runtime as ov

    omni = OmniVoiceStub(available={"omnivoice-female-2": (False, ov.UNCHECKED_MESSAGE)}).install(monkeypatch)
    monkeypatch.setattr(ov, "install_would_help", lambda voice_id=None: True)
    offered: list = []

    def dialog(panel, component, reason):
        offered.append((component, reason, len(omni.calls)))
        if make_available:
            omni.available["omnivoice-female-2"] = (True, "ok")
        return dict(outcome)

    return omni, offered, dialog


def test_a_skipped_omnivoice_voice_offers_install_and_continue_and_starts_the_frozen_run_once(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    from tkinter import messagebox

    from tts import omnivoice_runtime as ov

    omni, offered, dialog = _install_offer(monkeypatch, outcome={"state": "installed", "verified": ["omnivoice"]},
                                           make_available=True)
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: pytest.fail(f"warned: {a}"))
    asked: list = []
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", omnivoice_status=omni.status,
                                  installable=offers(asked), install_dialog=dialog)
    select(panel, "OmniVoice - Female 2")
    params = run_attempt(panel)
    assert asked == [("omnivoice", "omnivoice")]
    assert offered == [("omnivoice", ov.UNCHECKED_MESSAGE, 0)], "offered once, before anything was synthesised"
    assert [c["voice_id"] for c in omni.calls] == ["omnivoice-female-2"], "the frozen run started exactly once"
    assert landed(params) == ["one-OmniVoice - Female 2.mp3"]


@pytest.mark.parametrize("outcome", [{}, {"state": "skipped"}, {"state": "cancelled"},
                                     {"state": "failed", "message": "offline"}])
def test_closing_skipping_cancelling_or_failing_the_install_never_starts_a_conversion(
        make_panel, output_base, tmp_path, stubs, monkeypatch, outcome):
    from tkinter import messagebox

    omni, offered, dialog = _install_offer(monkeypatch, outcome=outcome, make_available=False)
    said: list = []
    monkeypatch.setattr(messagebox, "showinfo", lambda title, message, **k: said.append((title, message)))
    monkeypatch.setattr(panel_module.output_paths, "reserve_run_directory",
                        lambda *a, **k: pytest.fail("an abandoned install reserved a directory"))
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", omnivoice_status=omni.status,
                                  installable=offers([]), install_dialog=dialog)
    select(panel, "OmniVoice - Female 2")
    assert accept(panel) == {}
    assert len(offered) == 1 and omni.calls == []
    assert said and said[0][0] == "Conversion not started"


def test_a_source_changed_during_install_and_continue_is_not_narrated(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    """The run is frozen before the install; a source that changes meanwhile is never silently narrated."""
    from tkinter import messagebox

    omni, offered, dialog = _install_offer(monkeypatch, outcome={"state": "installed"}, make_available=True)
    panel, chosen = direct_panel(make_panel, tmp_path, "one.txt", omnivoice_status=omni.status,
                                 installable=offers([]), install_dialog=None)

    def changing_dialog(panel_, component, reason):
        result = dialog(panel_, component, reason)
        for source in chosen:
            Path(source).write_text("a different book", encoding="utf-8")
        return result

    panel._install_dialog = changing_dialog
    said: list = []
    monkeypatch.setattr(messagebox, "showinfo", lambda title, message, **k: said.append((title, message)))
    select(panel, "OmniVoice - Female 2")
    assert accept(panel) == {}
    assert len(offered) == 1 and omni.calls == []
    assert said and "changed or was removed" in said[0][1]


def test_a_cancel_mid_file_removes_the_partial_output(make_panel, output_base, tmp_path, stubs, omni):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", omnivoice_status=omni.status)
    select(panel, "OmniVoice - Female 1")
    omni.cancel_at_chunk = panel.cancel_job
    params = run_attempt(panel)
    assert omni.calls, "the engine was reached"
    assert not any(item["destination"].exists() for item in params["items"])


def test_dispatch_reads_the_backend_never_the_label():
    import ast

    compares = [ast.unparse(node) for node in ast.walk(panel_tree()) if isinstance(node, ast.Compare)]
    omni_tests = [text for text in compares if "'omnivoice'" in text]
    assert omni_tests and all("backend" in t and "display_label" not in t for t in omni_tests)
    assert "convert_with_omnivoice" in ast.unparse(panel_tree())
