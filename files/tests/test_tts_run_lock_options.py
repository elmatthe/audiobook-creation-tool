"""TTS options a run has frozen are locked while it runs — v0.7.2 Phase 6, ACT72-014.

Start freezes every option into the run (Decision 9A). ``TtsPanel.set_locked`` locked Start, workers, overwrite,
Install / repair, bitrate and the voice, but left Resume, the Edge speech rate and the Kokoro speed editable: during a
run they looked live and changed nothing. A real run, through the panel's own worker and the shared lock matrix, held
inside the engine by a gate the test releases; what a person had chosen is still there afterwards. Open Output Folder
and Clear Log are not options and stay available.
"""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

from shared.job_control import ControlKind  # noqa: E402

from test_tts_jobs import direct_panel, gated_stubs, wait_for  # noqa: E402,F401  (fixtures are collected by name)
from test_tts_importing import WAIT, make_panel, output_base, tk_root  # noqa: E402,F401

FROZEN = ("chk_resume", "entry_rate", "spin_kokoro_speed")
ALWAYS_AVAILABLE = ("btn_open_out", "btn_clear_log")


def state_of(panel, name: str) -> str:
    return str(getattr(panel, name).cget("state"))


def test_resume_edge_rate_and_kokoro_speed_lock_with_a_run_and_keep_what_was_chosen(
        make_panel, output_base, tmp_path, gated_stubs):
    panel, _chosen = direct_panel(make_panel, tmp_path, "gate.txt")
    panel.resume_var.set(False)
    panel.rate_var.set("-10%")
    panel.kokoro_speed_var.set("1.25")
    chosen = (panel.resume_var.get(), panel.rate_var.get(), panel.kokoro_speed_var.get())
    assert {name: state_of(panel, name) for name in FROZEN} == {name: "normal" for name in FROZEN}

    panel.run_job()
    worker = panel._worker
    try:
        assert gated_stubs.entered.wait(WAIT), "the run is inside the engine"
        wait_for(lambda: panel.jobs.locks.last_applied.get(ControlKind.PROCESSING_OPTION) is True,
                 "the run never locked its options", panel=panel)
        assert {name: state_of(panel, name) for name in FROZEN} == {name: "disabled" for name in FROZEN}
        assert {name: state_of(panel, name) for name in ALWAYS_AVAILABLE} == {
            name: "normal" for name in ALWAYS_AVAILABLE}, "not options: they never lock"
    finally:
        gated_stubs.release.set()
        worker.join(WAIT)
        panel._pump.tick()

    assert {name: state_of(panel, name) for name in FROZEN} == {name: "normal" for name in FROZEN}
    assert (panel.resume_var.get(), panel.rate_var.get(), panel.kokoro_speed_var.get()) == chosen


@pytest.mark.parametrize("locked, expected", [(True, "disabled"), (False, "normal")])
def test_set_locked_reaches_every_frozen_option(make_panel, locked, expected):
    panel = make_panel()
    panel.set_locked(locked)
    for name in ("go_btn", "spin_workers", "chk_overwrite", "qwen3_setup_btn", *FROZEN):
        assert state_of(panel, name) == expected, name
    for combo in ("combo_bitrate", "voice_combo"):
        assert state_of(panel, combo) == ("disabled" if locked else "readonly"), combo
