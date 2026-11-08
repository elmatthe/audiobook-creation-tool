"""An Edge speech rate the service will refuse is refused at Start -- v0.7.2 Phase 5, ACT72-044.

Folder-imported Edge files send the typed rate with every request, and the Edge library refuses any rate that is not a
sign, a whole number and ``%``. Before this phase a rate such as ``10%`` was frozen and a run folder reserved, and then
every folder-imported Edge file failed (reproduced at ``fa9d3c3`` by the planted unchecked rate below). Now Start says
so before anything is frozen or reserved, and only when the rate would be sent: a queue of directly added files keeps
Edge's natural pace and never uses it. Nothing here reaches the network: the Edge library is asked only to construct a
request, which is where it validates.
"""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

from tts import epub2tts_gui as panel_module  # noqa: E402

from test_tts_importing import (  # noqa: E402,F401
    make_panel,
    output_base,
    sources,
    stubs,
    tk_root,
)
from test_tts_jobs import accept, direct_panel, folder_panel  # noqa: E402

RATES = ("+10%", "-5%", "+0%", "-0%", "+100%", "10%", "+10", "+10 %", "fast", "+1.5%", "%", "+-5%")


@pytest.mark.parametrize("rate", RATES)
def test_the_start_check_agrees_with_the_pinned_edge_library(rate):
    import edge_tts

    try:
        edge_tts.Communicate(text="x", voice="en-US-AriaNeural", rate=rate)  # validates; sends nothing
        library_accepts = True
    except ValueError:
        library_accepts = False
    assert bool(panel_module.EDGE_RATE.fullmatch(rate)) is library_accepts


def _warnings(monkeypatch) -> list:
    from tkinter import messagebox

    said: list = []
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: said.append(a))
    return said


@pytest.mark.parametrize("rate", ("10%", "fast", "+1.5%"))
def test_a_rate_edge_refuses_stops_a_folder_queue_before_anything_is_reserved(
        make_panel, output_base, tmp_path, stubs, monkeypatch, rate):
    said = _warnings(monkeypatch)
    monkeypatch.setattr(panel_module.output_paths, "reserve_run_directory",
                        lambda *a, **k: pytest.fail("a refused rate reserved a run folder"))
    panel, _folders = folder_panel(make_panel, tmp_path)
    assert panel.selected_voice_label.get() and panel_module.get_voice(panel.selected_voice_label.get()).backend == "edge"
    panel.rate_var.set(rate)
    assert accept(panel) == {}, "no worker was started"
    assert len(said) == 1 and said[0][0] == "Edge speech rate"
    assert repr(rate) in said[0][1] and "+10%" in said[0][1] and "Nothing was started" in said[0][1]
    assert stubs.conversion_jobs == [] and stubs.kokoro_calls == []


def test_a_rate_edge_accepts_reaches_the_frozen_folder_run(make_panel, output_base, tmp_path, stubs, monkeypatch):
    said = _warnings(monkeypatch)
    panel, _folders = folder_panel(make_panel, tmp_path)
    panel.rate_var.set("  -5%  ")
    captured = accept(panel)
    assert said == [] and captured, "a valid rate starts the run"
    assert captured["params"]["snapshot"].tool_options["rate"] == "-5%"


def test_a_queue_of_direct_files_never_uses_the_rate_so_it_is_not_judged(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    said = _warnings(monkeypatch)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    panel.rate_var.set("fast")
    captured = accept(panel)
    assert said == [] and captured, "directly added Edge files keep Edge's own pace; the rate is never sent"
