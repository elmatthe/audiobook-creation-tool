"""v0.6.7 CP6 — the eight Qwen3 voices in the unified queue.

The owner's rulings (``Decisions.md``, 2026-10-19) fix what the panel must do:

* the voices are ``Qwen3 - Aiden`` ... ``Qwen3 - Male 4`` in their own group, with their own backend, never confused with
  Chatterbox (dispatch reads ``VoiceEntry.backend``, not the label);
* a voice that cannot run here (platform, engine, model, reference, transcript) is reported as setup-required, never
  swapped for another voice, engine or model;
* the run follows the existing narration policy and its single progress model; a long file refreshes its current-item
  message per chunk without adding a second bar;
* one Qwen3 file at a time.

**No synthesis ever runs.** ``tts.qwen3_synth`` is replaced by a stub module at ``sys.modules``, the availability seam is
injected, and nothing here touches a model, a GPU, the network or the Qwen3 environment.
"""

from __future__ import annotations

import ast
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
from test_tts_jobs import (  # noqa: E402,F401
    accept,
    direct_panel,
    finish,
    folder_panel,
    relative,
    run_attempt,
)
from test_chatterbox_integration import ChatterboxStub  # noqa: E402

AIDEN = "Qwen3 - Aiden"
MALE_1 = "Qwen3 - Male 1"
HARDWARE = "Runs on your NVIDIA GPU (Test GPU, 12 GB). Speed depends on the computer."

QWEN3_VOICES = (
    ("qwen3-aiden", "Qwen3 - Aiden"), ("qwen3-ryan", "Qwen3 - Ryan"),
    ("qwen3-female-1", "Qwen3 - Female 1"), ("qwen3-female-2", "Qwen3 - Female 2"),
    ("qwen3-male-1", "Qwen3 - Male 1"), ("qwen3-male-2", "Qwen3 - Male 2"),
    ("qwen3-male-3", "Qwen3 - Male 3"), ("qwen3-male-4", "Qwen3 - Male 4"),
)


class Qwen3Stub:
    """Stands in for ``tts.qwen3_synth`` and answers the availability seam from a dictionary the test controls."""

    def __init__(self, *, available=None):
        self.calls: list[dict] = []
        self.status_requests: list[str] = []
        self.available: dict[str, tuple[bool, str]] = dict(available or {})
        self.chunks = ()  # (done, total) pairs the engine reports through progress_callback
        self.cancel_at_chunk = None
        self.failing = ""

    def status(self, voice_id: str) -> tuple[bool, str]:
        self.status_requests.append(voice_id)
        return self.available.get(voice_id, (True, "ok"))

    def qwen3_file_to_mp3(self, source_path, output_mp3_path, voice_id, **kwargs):
        self.calls.append({"source": str(source_path), "output": str(output_mp3_path), "voice_id": voice_id, **kwargs})
        cancel_check = kwargs.get("cancel_check")
        if cancel_check is not None and cancel_check():
            raise ConversionCancelled("Conversion cancelled by user.")
        for done, total in self.chunks:
            kwargs["progress_callback"](done, total)
        if self.cancel_at_chunk is not None:
            self.cancel_at_chunk()
            Path(output_mp3_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_mp3_path).write_bytes(b"a partly written file")
            raise ConversionCancelled("Conversion cancelled by user.")
        if self.failing and self.failing in Path(source_path).name:
            raise RuntimeError("the Qwen3 engine refused this book")
        Path(output_mp3_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_mp3_path).write_bytes(b"audio")

    def install(self, monkeypatch):
        module = types.ModuleType("tts.qwen3_synth")
        module.qwen3_file_to_mp3 = self.qwen3_file_to_mp3
        monkeypatch.setitem(sys.modules, "tts.qwen3_synth", module)
        return self


@pytest.fixture()
def qwen3(monkeypatch):
    return Qwen3Stub().install(monkeypatch)


def panel_kwargs(qwen3, chatterbox=None):
    kwargs = {"qwen3_status": qwen3.status, "qwen3_hardware": lambda: HARDWARE}
    if chatterbox is not None:
        kwargs["chatterbox_status"] = chatterbox.status
    return kwargs


def select(panel, label: str = AIDEN) -> None:
    panel.selected_voice_label.set(label)
    panel._on_voice_selected()


# --------------------------------------------------------------------------- #
# A. One file at a time
# --------------------------------------------------------------------------- #
def test_qwen3_runs_one_file_at_a_time_whatever_is_requested():
    assert panel_module.QWEN3_BACKEND_SAFE_WORKERS == 1
    assert panel_module._device_safe_workers("qwen3") == 1
    for requested, queued in ((1, 1), (8, 8), (32, 100)):
        assert panel_module.resolve_effective_workers(requested, queued, "qwen3") == 1


def test_the_other_backends_worker_ceilings_are_unchanged(monkeypatch):
    monkeypatch.setattr(panel_module, "_cpu_count", lambda: 16)
    assert panel_module.resolve_effective_workers(8, 8, "chatterbox") == 1
    assert panel_module.resolve_effective_workers(8, 8, "kokoro") == 1
    assert panel_module.resolve_effective_workers(8, 8, "edge") == 8


# --------------------------------------------------------------------------- #
# B. Selection: engine line, controls, disclosure, and which seam is asked
# --------------------------------------------------------------------------- #
def test_the_engine_line_names_qwen3_and_no_other_engine(make_panel, qwen3):
    panel = make_panel(**panel_kwargs(qwen3))
    select(panel)
    shown = panel.backend_label_var.get()
    assert panel_module.QWEN3_ENGINE_LABEL in shown and "qwen3-aiden" in shown and vr.QWEN3_GROUP_LABEL in shown
    for other in ("Chatterbox", "Kokoro", "Edge"):
        assert other not in shown


def test_the_hardware_and_speed_disclosure_is_shown_beside_a_qwen3_voice_and_nowhere_else(make_panel, qwen3):
    panel = make_panel(**panel_kwargs(qwen3))
    select(panel)
    assert panel.kokoro_notice_var.get() == HARDWARE and panel.kokoro_notice_lbl.winfo_manager()
    select(panel, "Chatterbox - Female 1")
    assert not panel.kokoro_notice_lbl.winfo_manager()
    select(panel, vr.DEFAULT_VOICE_LABEL)
    assert not panel.kokoro_notice_lbl.winfo_manager()


def test_neither_speed_control_is_offered_for_a_qwen3_voice(make_panel, qwen3):
    panel = make_panel(**panel_kwargs(qwen3))
    kokoro = next(v for v in vr.VOICES if v.backend == "kokoro")
    select(panel, kokoro.display_label)
    assert panel.kokoro_speed_frm.winfo_manager()
    select(panel)
    assert not panel.kokoro_speed_frm.winfo_manager() and not panel.edge_rate_frm.winfo_manager()


def test_the_voice_status_line_is_empty_for_an_available_voice(make_panel, qwen3):
    panel = make_panel(**panel_kwargs(qwen3))
    select(panel)
    assert panel._voice_available is True and panel.voice_status_var.get() == ""
    assert not panel.voice_status_lbl.winfo_manager()


def test_building_the_panel_and_choosing_other_engines_asks_qwen3_nothing(make_panel, qwen3):
    chatterbox = ChatterboxStub()
    panel = make_panel(**panel_kwargs(qwen3, chatterbox))
    kokoro = next(v for v in vr.VOICES if v.backend == "kokoro")
    for label in (kokoro.display_label, vr.DEFAULT_VOICE_LABEL, "Chatterbox - Male 4"):
        select(panel, label)
    assert qwen3.status_requests == []


def test_each_local_engine_asks_only_its_own_seam(make_panel, qwen3):
    chatterbox = ChatterboxStub()
    panel = make_panel(**panel_kwargs(qwen3, chatterbox))
    select(panel, MALE_1)
    assert qwen3.status_requests == ["qwen3-male-1"] and chatterbox.status_requests == []
    select(panel, "Chatterbox - Male 1")
    assert qwen3.status_requests == ["qwen3-male-1"] and chatterbox.status_requests == ["chatterbox-male-1"]


# --------------------------------------------------------------------------- #
# C. Availability: registered is not available, and nothing is substituted
# --------------------------------------------------------------------------- #
def unavailable(voice_id: str, reason: str) -> Qwen3Stub:
    return Qwen3Stub(available={voice_id: (False, reason)})


def test_an_unavailable_voice_is_shown_with_the_engines_own_sentence(make_panel, monkeypatch):
    reason = ('The Qwen3 CustomVoice model (4.5 GB) is not installed. Choose "Install / repair Qwen3 voices" to install '
              "it; nothing is downloaded until you ask.")
    stub = unavailable("qwen3-aiden", reason).install(monkeypatch)
    panel = make_panel(**panel_kwargs(stub))
    select(panel)
    assert panel._voice_available is False
    assert panel.voice_status_var.get() == reason and panel.voice_status_lbl.winfo_manager()
    assert panel_module.QWEN3_ENGINE_LABEL in panel.backend_label_var.get()  # the engine line still tells the truth


def test_starting_with_an_unavailable_voice_is_refused_before_a_run_is_reserved(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    from tkinter import messagebox

    stub = unavailable("qwen3-aiden", "Setup required: the model is not installed.").install(monkeypatch)
    warned: list = []
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: warned.append(a))
    monkeypatch.setattr(panel_module.output_paths, "reserve_run_directory",
                        lambda *a, **k: pytest.fail("a refused run reserved a directory"))
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(stub))
    select(panel)
    assert accept(panel) == {}, "no worker was started"
    assert warned and "model is not installed" in " ".join(str(part) for part in warned[0])
    assert stub.calls == [] and stubs.conversion_jobs == [] and stubs.kokoro_calls == []


def test_a_selection_that_goes_stale_after_picking_is_refused_at_start(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    from tkinter import messagebox

    stub = Qwen3Stub().install(monkeypatch)
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: None)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(stub))
    select(panel)
    assert panel._voice_available is True
    stub.available["qwen3-aiden"] = (False, "the Qwen3 model was removed")
    assert accept(panel) == {} and stub.calls == []
    assert "removed" in panel.voice_status_var.get()


def test_a_refused_run_substitutes_no_other_voice_engine_or_model(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    from tkinter import messagebox

    stub = unavailable("qwen3-male-1", "Setup required for Qwen3 - Male 1: no approved transcript.").install(monkeypatch)
    chatterbox = ChatterboxStub().install(monkeypatch)
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: None)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(stub, chatterbox))
    select(panel, MALE_1)
    accept(panel)
    assert panel.selected_voice_label.get() == MALE_1, "no silent swap"
    assert stub.calls == [] and chatterbox.calls == [], "no fallback to the Chatterbox twin that shares the recording"
    assert stubs.conversion_jobs == [] and stubs.kokoro_calls == [], "no fallback to Edge or Kokoro"


def test_one_unavailable_qwen3_voice_leaves_the_others_and_every_other_engine_usable(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    stub = unavailable("qwen3-male-1", "no transcript").install(monkeypatch)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(stub))
    select(panel, MALE_1)
    assert panel._voice_available is False
    select(panel, "Qwen3 - Male 2")
    assert panel._voice_available is True
    params = run_attempt(panel)
    assert params["voice_id"] == "qwen3-male-2" and [c["voice_id"] for c in stub.calls] == ["qwen3-male-2"]


def test_an_unimportable_engine_is_reported_rather_than_raised(make_panel):
    panel = make_panel(qwen3_status=panel_module.qwen3_status, qwen3_hardware=lambda: HARDWARE)
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "tts.qwen3_runtime", None)
        select(panel)
    assert panel._voice_available is False
    assert "Every other voice is unaffected" in panel.voice_status_var.get()


def test_the_status_seam_answers_rather_than_propagating_an_engine_error():
    module = types.ModuleType("tts.qwen3_runtime")

    def exploding(_voice_id):
        raise OSError("disk on fire")

    module.voice_availability = exploding
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "tts.qwen3_runtime", module)
        ok, reason = panel_module.qwen3_status("qwen3-aiden")
    assert ok is False and "disk on fire" in reason and "Every other voice is unaffected" in reason


def test_the_real_seams_agree_with_the_runtime_module(monkeypatch):
    from tts import qwen3_runtime as rt

    monkeypatch.setattr(rt, "voice_availability", lambda voice_id: (False, f"asked about {voice_id}"))
    assert panel_module.qwen3_status("qwen3-ryan") == (False, "asked about qwen3-ryan")
    monkeypatch.setattr(rt, "hardware_summary", lambda: "a disclosure")
    assert panel_module.qwen3_hardware_note() == "a disclosure"

    def broken():
        raise RuntimeError("probe failed")

    monkeypatch.setattr(rt, "hardware_summary", broken)
    assert "slower than real time" in panel_module.qwen3_hardware_note()  # a disclosure never breaks voice selection


# --------------------------------------------------------------------------- #
# D. Dispatch: the frozen backend decides, the preset's pauses are used
# --------------------------------------------------------------------------- #
def test_the_frozen_options_carry_the_qwen3_backend_and_voice_id(make_panel, output_base, tmp_path, stubs, qwen3):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(qwen3))
    select(panel)
    params = run_attempt(panel)
    options = params["snapshot"].tool_options
    assert (options["backend"], options["voice_id"]) == ("qwen3", "qwen3-aiden")
    assert params["pause_kw"] == {}, "pause_kw only ever applies to the Edge engine"


@pytest.mark.parametrize("voice_id,label", QWEN3_VOICES)
def test_all_eight_voices_route_to_the_qwen3_engine_by_voice_id(
        make_panel, output_base, tmp_path, stubs, qwen3, voice_id, label):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(qwen3))
    select(panel, label)
    params = run_attempt(panel)
    assert params["backend"] == "qwen3"
    assert [c["voice_id"] for c in qwen3.calls] == [voice_id]
    # v0.7.0 P02B: presets and clones alike are named by the frozen label; never the voice id or the backend.
    assert relative(qwen3.calls[0]["output"], params["run_directory"]) == f"one-{label}.mp3"
    assert voice_id not in qwen3.calls[0]["output"]
    assert stubs.conversion_jobs == [] and stubs.kokoro_calls == []


def test_a_qwen3_clone_never_reaches_its_chatterbox_twin(make_panel, output_base, tmp_path, stubs, monkeypatch):
    chatterbox = ChatterboxStub().install(monkeypatch)
    qwen3 = Qwen3Stub().install(monkeypatch)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(qwen3, chatterbox))
    select(panel, MALE_1)
    run_attempt(panel)
    assert [c["voice_id"] for c in qwen3.calls] == ["qwen3-male-1"] and chatterbox.calls == []
    select(panel, "Chatterbox - Male 1")
    run_attempt(panel)
    assert [c["voice_id"] for c in chatterbox.calls] == ["chatterbox-male-1"] and len(qwen3.calls) == 1


def test_the_run_hands_the_engine_the_voice_presets_pauses_and_the_chosen_bitrate(
        make_panel, output_base, tmp_path, stubs, qwen3):
    entry = vr.get_voice(AIDEN)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(qwen3))
    select(panel)
    panel.bitrate_var.set("320k")
    run_attempt(panel)
    call = qwen3.calls[0]
    assert call["end_silence_ms"] == int(entry.timing_preset["end_pause"]) == 0  # v0.7.0 Q1: no closing pause
    assert call["chunk_pause_ms"] == int(entry.timing_preset["paragraphpause"]) == 700
    assert call["bitrate"] == "320k"
    assert callable(call["cancel_check"]) and callable(call["progress_callback"]) and callable(call["log"])


def test_a_direct_pdf_goes_through_the_existing_extractor_first(make_panel, output_base, tmp_path, stubs, qwen3):
    panel, chosen = direct_panel(make_panel, tmp_path, "book.pdf", **panel_kwargs(qwen3))
    select(panel)
    params = run_attempt(panel)
    assert [source for source, _target in stubs.extracted] == [str(chosen[0])]
    assert qwen3.calls[0]["source"].endswith(".txt") and qwen3.calls[0]["source"] != str(chosen[0])
    assert relative(qwen3.calls[0]["output"], params["run_directory"]) == f"book-{AIDEN}.mp3"


def test_folder_imported_files_mirror_their_root(make_panel, output_base, tmp_path, stubs, qwen3):
    panel, _folders = folder_panel(make_panel, tmp_path, **panel_kwargs(qwen3))
    select(panel)
    params = run_attempt(panel)
    assert sorted(relative(c["output"], params["run_directory"]) for c in qwen3.calls) == [
        f"01-{AIDEN}.mp3", f"Book A/02-{AIDEN}.mp3"]
    assert stubs.batch_items == [], "the Edge batch worker was not used"


def test_changing_the_voice_after_start_cannot_reach_a_running_run(make_panel, output_base, tmp_path, stubs, qwen3):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(qwen3))
    select(panel)
    captured = accept(panel)
    select(panel, vr.DEFAULT_VOICE_LABEL)
    params = finish(panel, captured)
    assert params["backend"] == "qwen3" and [c["voice_id"] for c in qwen3.calls] == ["qwen3-aiden"]
    assert stubs.conversion_jobs == []


# --------------------------------------------------------------------------- #
# E. Progress, cancellation, failure
# --------------------------------------------------------------------------- #
def test_each_finished_chunk_refreshes_the_current_item_message_without_a_second_progress_model(
        tmp_path, monkeypatch):
    messages = []

    class Publisher:
        def current_item(self, item_id, message=""):
            messages.append((item_id, message))

    stub = Qwen3Stub()
    stub.chunks = ((1, 3), (2, 3), (3, 3))
    stub.install(monkeypatch)
    source = tmp_path / "Long Book.txt"
    source.write_text("text", encoding="utf-8")
    item = {"item_id": "occ-7", "source": source, "destination": tmp_path / "out" / "Long Book.mp3"}
    params = {"voice_id": "qwen3-aiden", "end_pause": 3000, "paragraph_pause": 700, "bitrate": "192k",
              "publisher": Publisher()}
    panel_module.convert_with_qwen3(item, params, None, lambda m: None, lambda: False)
    assert messages == [("occ-7", f"Converting Long Book.txt — chunk {n}/3") for n in (1, 2, 3)]
    assert (tmp_path / "out" / "Long Book.mp3").read_bytes() == b"audio"


def test_the_engine_is_usable_without_a_publisher(tmp_path, monkeypatch):
    stub = Qwen3Stub()
    stub.chunks = ((1, 1),)
    stub.install(monkeypatch)
    source = tmp_path / "a.txt"
    source.write_text("text", encoding="utf-8")
    item = {"item_id": "x", "source": source, "destination": tmp_path / "a.mp3"}
    panel_module.convert_with_qwen3(item, {"voice_id": "qwen3-ryan", "end_pause": 1, "paragraph_pause": 1,
                                           "bitrate": None}, None, lambda m: None, lambda: False)
    assert stub.calls[0]["voice_id"] == "qwen3-ryan"


def test_a_cancel_mid_file_removes_the_partial_output(make_panel, output_base, tmp_path, stubs, qwen3):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(qwen3))
    select(panel)
    qwen3.cancel_at_chunk = panel.cancel_job
    params = run_attempt(panel)
    destinations = [item["destination"] for item in params["items"]]
    assert qwen3.calls, "the engine was reached"
    assert not any(d.exists() for d in destinations), "the cancelled file's partial output was removed"


def test_one_failing_file_fails_that_file_only(make_panel, output_base, tmp_path, stubs, qwen3):
    qwen3.failing = "bad"
    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt", **panel_kwargs(qwen3))
    select(panel)
    params = run_attempt(panel)
    outputs = sorted(item["destination"].name for item in params["items"] if item["destination"].exists())
    assert outputs == [f"good-{AIDEN}.mp3"]


# --------------------------------------------------------------------------- #
# F. The panel stays an adopter
# --------------------------------------------------------------------------- #
def test_the_panel_imports_only_the_qwen3_seams_it_is_allowed_and_no_model_stack():
    names: set[str] = set()
    for node in ast.walk(panel_tree()):
        if isinstance(node, ast.ImportFrom) and "qwen3" in (node.module or ""):
            names.update(alias.name for alias in node.names)
        if isinstance(node, ast.Import):
            assert not any(alias.name.split(".")[0] in {"torch", "qwen_tts", "transformers"} for alias in node.names)
    assert names == {"voice_availability", "hardware_summary", "platform_supported", "qwen3_file_to_mp3"}, names


def test_the_panel_reimplements_none_of_the_engines_checks():
    body = ast.unparse(panel_tree())
    for forbidden in ("venv_python", "model_status", "load_transcript", "transcripts.json", "worker_environment",
                      "Chatterbox-Voice-Uploads", "taskkill"):
        assert forbidden not in body, forbidden


def test_dispatch_reads_the_backend_never_the_label():
    compares = [ast.unparse(node) for node in ast.walk(panel_tree()) if isinstance(node, ast.Compare)]
    qwen_tests = [text for text in compares if "'qwen3'" in text]
    assert qwen_tests, "the dispatch has to test the backend somewhere"
    for text in qwen_tests:
        assert "backend" in text, text
        assert "display_label" not in text and "selected_voice_label" not in text, text
    body = ast.unparse(panel_tree())
    assert "convert_with_qwen3" in body and "params['backend']" in body


def test_a_platform_where_qwen3_is_not_yet_available_shows_that_and_makes_no_speed_claim(make_panel, monkeypatch):
    from tts import qwen3_runtime as rt

    monkeypatch.setattr(rt, "platform_supported", lambda: False)
    panel = make_panel(qwen3_status=panel_module.qwen3_status, qwen3_hardware=panel_module.qwen3_hardware_note)
    select(panel)
    assert panel._voice_available is False
    assert "not yet available" in panel.voice_status_var.get() and panel.voice_status_lbl.winfo_manager()
    assert panel.kokoro_notice_var.get() == "" and not panel.kokoro_notice_lbl.winfo_manager()
    select(panel, vr.DEFAULT_VOICE_LABEL)  # every other engine keeps working
    assert panel._voice_available is True


# --------------------------------------------------------------------------- #
# G. The in-app install / repair route (one action for first-time and existing users)
# --------------------------------------------------------------------------- #
from test_tts_compact_ui import (  # noqa: E402
    GEOMETRIES,
    _assert_composed,
    _box,
    _Shown,
    _skip_920x600_off_windows,
)


def setup_panel(make_panel, qwen3, *, offered=True, dialogs=None):
    opened = [] if dialogs is None else dialogs
    panel = make_panel(**panel_kwargs(qwen3), qwen3_setup_offered=lambda: offered,
                       qwen3_setup_dialog=lambda p: opened.append(p))
    return panel, opened


def test_the_install_route_is_offered_only_beside_a_qwen3_voice(make_panel, qwen3):
    panel, _ = setup_panel(make_panel, qwen3)
    assert not panel.qwen3_setup_btn.winfo_manager(), "hidden on the default Edge voice"
    select(panel)
    assert panel.qwen3_setup_btn.winfo_manager() and panel.qwen3_setup_btn.cget("text") == "Install / repair Qwen3 voices..."
    select(panel, "Chatterbox - Female 1")
    assert not panel.qwen3_setup_btn.winfo_manager()
    kokoro = next(v for v in vr.VOICES if v.backend == "kokoro")
    select(panel, kokoro.display_label)
    assert not panel.qwen3_setup_btn.winfo_manager()
    select(panel, MALE_1)
    assert panel.qwen3_setup_btn.winfo_manager()


def test_the_install_route_is_not_offered_where_the_voices_are_not_yet_available(make_panel, qwen3):
    panel, _ = setup_panel(make_panel, qwen3, offered=False)
    select(panel)
    assert not panel.qwen3_setup_btn.winfo_manager()


def test_pressing_the_button_opens_the_dialog_and_then_asks_the_voice_status_again(make_panel, monkeypatch):
    stub = unavailable("qwen3-aiden", "The Qwen3 CustomVoice model (4.5 GB) is not installed.").install(monkeypatch)
    panel, opened = setup_panel(make_panel, stub)
    select(panel)
    assert panel._voice_available is False and "not installed" in panel.voice_status_var.get()

    def dialog_that_installs(p):
        opened.append(p)
        stub.available.pop("qwen3-aiden")  # the user installed the model inside the dialog

    panel._qwen3_setup_dialog = dialog_that_installs
    panel.qwen3_setup_btn.invoke()
    assert opened == [panel]
    assert panel._voice_available is True and panel.voice_status_var.get() == ""  # usable without reselecting


def test_the_dialog_is_refused_while_a_conversion_is_running(make_panel, qwen3, monkeypatch):
    from tkinter import messagebox

    shown = []
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: shown.append(a))
    panel, opened = setup_panel(make_panel, qwen3)
    select(panel)
    panel._busy.set()
    try:
        panel.open_qwen3_setup()
    finally:
        panel._busy.clear()
    assert opened == [] and shown and "when the current conversion has finished" in shown[0][1]


def test_the_button_is_locked_with_the_rest_of_the_options_during_a_run(make_panel, qwen3):
    panel, _ = setup_panel(make_panel, qwen3)
    select(panel)
    panel.set_locked(True)
    assert str(panel.qwen3_setup_btn.cget("state")) == "disabled"
    panel.set_locked(False)
    assert str(panel.qwen3_setup_btn.cget("state")) == "normal"


def test_the_default_seams_open_the_real_dialog_lazily_and_offer_it_on_windows_only(monkeypatch):
    from tts import qwen3_runtime as rt

    monkeypatch.setattr(rt, "platform_supported", lambda: True)
    assert panel_module.qwen3_setup_offered() is True
    monkeypatch.setattr(rt, "platform_supported", lambda: False)
    assert panel_module.qwen3_setup_offered() is False
    assert "qwen3_install_ui" not in {n.module for n in ast.walk(panel_tree()) if isinstance(n, ast.ImportFrom) and n.col_offset == 0}


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_with_every_qwen3_extra_showing_every_region_still_fits_and_nothing_overlaps(make_panel, monkeypatch, geometry):
    """The tallest the voice section gets: engine line, hardware notice, a setup-required message AND the new button."""
    _skip_920x600_off_windows(geometry)
    long_reason = ('The Qwen3 CustomVoice model (4.5 GB) is not installed. Choose "Install / repair Qwen3 voices" to '
                   "install it; nothing is downloaded until you ask.")
    stub = unavailable("qwen3-aiden", long_reason).install(monkeypatch)
    panel, _ = setup_panel(make_panel, stub)
    with _Shown(panel, geometry):
        select(panel)
        panel.update_idletasks()
        panel.update()
        _assert_composed(panel, geometry)
        for widget in (panel.qwen3_setup_btn, panel.voice_status_lbl, panel.kokoro_notice_lbl, panel.backend_lbl):
            assert widget.winfo_ismapped(), (geometry, str(widget))
            box = _box(panel, widget)
            assert box[2] <= panel.winfo_width() and box[3] <= panel.winfo_height(), (geometry, str(widget), box)
        button, section = _box(panel, panel.qwen3_setup_btn), _box(panel, panel.voice_section)
        assert section[0] <= button[0] and button[2] <= section[2] and section[1] <= button[1] and button[3] <= section[3]


def test_the_default_dialog_is_handed_the_panels_confirmation_and_style_so_it_imports_no_foundation(monkeypatch):
    """The install dialog imports none of the Plan 3 job foundation: the adopting TTS panel injects what it needs."""
    from shared import job_ui
    from tts import epub2tts_gui, qwen3_install_ui

    seen = {}
    monkeypatch.setattr(qwen3_install_ui, "run_dialog", lambda parent, **kwargs: seen.update(parent=parent, **kwargs))

    class Panel:
        appearance_bundle = {"styles": {}}

        def _on_qwen3_setup_changed(self):
            pass

    panel = Panel()
    epub2tts_gui._default_qwen3_setup_dialog(panel)
    assert seen["parent"] is panel and seen["confirm"] is job_ui.ask_confirm and seen["style_name"] is job_ui.style_name
    assert seen["theme"] is panel.appearance_bundle and seen["on_change"] == panel._on_qwen3_setup_changed


# --------------------------------------------------------------------------- #
# v0.7.0 P02A: labels and order are cosmetic, through the real panel and stubbed engine entry points
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["reversed", "interleaved"])
def test_numbered_labels_in_any_order_reach_the_same_engine_and_voice_through_the_panel(
        make_panel, output_base, tmp_path, stubs, monkeypatch, name):
    """All 28 rows relabelled "1".."28" in a disposable in-memory registry, reordered, then run one by one."""
    from test_voice_labels import PERMUTATIONS, SHIPPED_KEYS, relabelled

    order = PERMUTATIONS[name]
    chatterbox = ChatterboxStub().install(monkeypatch)
    qwen3 = Qwen3Stub().install(monkeypatch)
    stubs.install_kokoro(monkeypatch)
    monkeypatch.setattr(vr, "VOICES", relabelled(order))
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(qwen3, chatterbox))

    assert [str(v) for v in panel.voice_combo.cget("values")] == [str(n) for n in range(1, 29)]  # exact edited order
    assert vr.get_voice(panel.selected_voice_label.get()).key == ("edge", "en-US-SteffanNeural")  # default by identity

    engines = {"edge": (stubs.conversion_jobs, "speaker"), "kokoro": (stubs.kokoro_calls, "voice_id"),
               "chatterbox": (chatterbox.calls, "voice_id"), "qwen3": (qwen3.calls, "voice_id")}
    reached = []
    for n in range(1, 29):
        before = {backend: len(calls) for backend, (calls, _field) in engines.items()}
        select(panel, str(n))
        params = run_attempt(panel)
        options = params["snapshot"].tool_options
        called = [(backend, calls[-1][field]) for backend, (calls, field) in engines.items()
                  if len(calls) == before[backend] + 1]
        assert len(called) == 1, (n, called)  # exactly one engine ran, once
        assert called[0] == (options["backend"], options["voice_id"]) == (params["backend"], options["voice_id"])
        reached.append(called[0])
    assert reached == [SHIPPED_KEYS[i] for i in order]


def test_a_label_that_names_no_registered_voice_is_refused_not_run_as_an_edge_voice(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    """Before P02A an unresolvable label fell back to backend "edge" with the last voice id: a silent engine switch."""
    from tkinter import messagebox

    warned = []
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: warned.append(a))
    qwen3 = Qwen3Stub().install(monkeypatch)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **panel_kwargs(qwen3))
    select(panel, AIDEN)
    panel.selected_voice_label.set("Qwen3 - Aiden (renamed elsewhere)")  # a label the registry no longer has
    assert accept(panel) == {}, "the panel must decline to start"
    assert [w[0] for w in warned] == ["Voice not recognised"]
    assert stubs.conversion_jobs == [] and stubs.kokoro_calls == [] and qwen3.calls == []
