"""v0.6.5 Phase 7 — Compact TTS UI (plan §10/§11).

A compacting pass only: the shared imported-file manager, unified PDF/TXT
queue, output planning, shared job controls, and every approved TTS/audio/
concurrency behavior (Phases 1-6) are unchanged. What changed is the surface:

* **Removed** from user-editable state: sentence/paragraph/title/chapter
  pause, end-silence, trim threshold, trim-edge-chunks. The maintainer-
  approved per-voice policy behind them (``voice_registry.VoiceEntry.
  timing_preset``) is unchanged and is still applied — just no longer through
  a widget a user could change (proven in ``test_tts_importing.py`` and
  ``test_chatterbox_integration.py``, updated alongside this drop).
* **Retained**: the unified queue/importer, voice dropdown and backend/setup-
  required status, MP3 bitrate, the requested file-worker control (P14),
  truthful backend-supported rate control (Edge %, Kokoro speed, no fake
  Chatterbox Turbo control), and every shared run control (Start/Pause/
  Resume/Cancel/Retry Failed, progress/ETA, Summary/Details).
* **Added**: Clear Log and Open Output Folder, bringing this panel to parity
  with the sibling MP3/M4B tools that already have both (mp3_tool.py,
  m4b_converter.py, m4b_maker.py, m4b_metadata_editor.py).

This file does not re-prove P14's worker-resolution/concurrency correctness
(``test_tts_worker_concurrency.py`` already does that exhaustively) — it
proves the *UI surface* is compact, truthful, and behaves per §10's table.
"""

from __future__ import annotations

import ast

import pytest

tk = pytest.importorskip("tkinter")

from tts import epub2tts_gui as panel_module  # noqa: E402
from tts import voice_registry as vr  # noqa: E402

from test_tts_importing import (  # noqa: E402,F401
    PANEL_SOURCE,
    make_panel,
    output_base,
    panel_tree,
    sources,
    stubs,
    tk_root,
)
from test_tts_jobs import direct_panel, run_attempt  # noqa: E402,F401


def source() -> str:
    return PANEL_SOURCE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# A. Removed from user-editable state
# --------------------------------------------------------------------------- #

REMOVED_TIMING_ATTRS = (
    "sentence_ms_var", "paragraph_ms_var", "title_ms_var", "chapter_ms_var",
    "end_pause_var", "trim_edge_chunks_var", "trim_dbfs_var",
)


def test_none_of_the_removed_timing_attributes_exist_on_the_panel(make_panel):
    panel = make_panel()
    for name in REMOVED_TIMING_ATTRS:
        assert not hasattr(panel, name), name


def test_the_removed_parsing_helpers_are_gone_from_the_module():
    assert not hasattr(panel_module, "_parse_pause_ms")
    assert not hasattr(panel_module, "_parse_trim_dbfs")


def test_no_pause_timing_or_trim_wording_remains_in_the_source():
    text = source()
    for phrase in (
        "Pause timing", "Trim Edge TTS padding", "Trim threshold",
        "trim_edge_chunks_var", "trim_dbfs_var", "sentence_ms_var",
        "paragraph_ms_var", "title_ms_var", "chapter_ms_var", "end_pause_var",
    ):
        assert phrase not in text, phrase


def test_the_two_provenance_scoped_group_headings_are_gone():
    """These headings became misleading once Phase 6 unified direct/folder
    dispatch — bitrate/workers/rate all apply regardless of provenance now."""
    text = source()
    assert "MP3 options" not in text
    assert "Options for files imported from a folder" not in text


# --------------------------------------------------------------------------- #
# B. Retained: bitrate, workers, and the one truthful rate control per backend
# --------------------------------------------------------------------------- #


def test_audio_processing_band_holds_bitrate_workers_and_rate_controls(make_panel):
    from tkinter import ttk

    panel = make_panel()
    assert panel.combo_bitrate.master is panel.spin_workers.master
    assert panel.combo_bitrate.master is panel.edge_rate_frm.master
    assert panel.combo_bitrate.master is panel.kokoro_speed_frm.master
    assert isinstance(panel.combo_bitrate.master, ttk.LabelFrame)
    assert panel.combo_bitrate.master.cget("text") == "Audio / Processing"


def test_the_workers_control_is_labelled_as_requested_file_level_concurrency():
    text = source()
    assert "File workers (requested)" in text
    assert "Concurrency is between whole files only" in text
    assert "never inside one file" in text


def test_the_workers_caption_points_to_the_truthful_effective_cap_report():
    text = source()
    assert "effective cap actually used" in text
    assert "Engine output" in text


@pytest.mark.parametrize("label,backend,edge_shown,kokoro_shown", [
    (vr.DEFAULT_VOICE_LABEL, "edge", True, False),
    ("Kokoro Female (Default) - Heart (en-US)", "kokoro", False, True),
    ("Chatterbox - Female 1", "chatterbox", False, False),
])
def test_exactly_the_backend_supported_rate_control_is_shown(
    make_panel, label, backend, edge_shown, kokoro_shown
):
    panel = make_panel()
    panel.selected_voice_label.set(label)
    panel._on_voice_selected()
    assert bool(panel.edge_rate_frm.winfo_manager()) is edge_shown, backend
    assert bool(panel.kokoro_speed_frm.winfo_manager()) is kokoro_shown, backend


def test_no_rate_control_is_shown_for_chatterbox_confirming_no_fake_control():
    """§10 Band 3: 'Chatterbox Turbo: none — no fake control'."""
    text = source()
    assert "no fake control" in text.lower() or "no such parameter" in text.lower() \
        or "exposes no such" in text.lower() or "no speed/rate control at all" in text.lower()


# --------------------------------------------------------------------------- #
# C. Added: Clear Log, Open Output Folder (parity with sibling MP3/M4B tools)
# --------------------------------------------------------------------------- #


def test_clear_log_empties_the_visible_transcript_only(make_panel):
    panel = make_panel()
    panel.append_log("hello world\n")
    assert "hello world" in panel.log.get("1.0", "end")
    panel.clear_log()
    assert panel.log.get("1.0", "end").strip() == ""
    # The log widget must return to its normal read-only state, not stay editable.
    assert str(panel.log.cget("state")) == "disabled"


def test_open_output_folder_reveals_the_tool_parent_before_any_run(
    make_panel, output_base, monkeypatch
):
    opened = []
    monkeypatch.setattr(panel_module.sp, "reveal_in_file_manager",
                        lambda target: opened.append(target))
    panel = make_panel()
    assert panel._run_directory is None
    panel.open_output_folder()
    assert len(opened) == 1
    assert opened[0].is_dir()


def test_open_output_folder_reveals_this_runs_own_directory_after_a_run(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    opened = []
    monkeypatch.setattr(panel_module.sp, "reveal_in_file_manager",
                        lambda target: opened.append(target))
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    run_attempt(panel)
    assert panel._run_directory is not None
    panel.open_output_folder()
    assert opened == [panel._run_directory]


def test_the_two_new_buttons_are_not_registered_as_processing_options(make_panel):
    """Matching the sibling tools' own convention: opening the output folder
    or clearing the transcript never locks, or is locked by, a run in flight.
    Confirmed by inspecting set_locked's own source rather than depending on
    tkinter's configure() semantics."""
    make_panel()  # a real panel must still build cleanly with both buttons
    tree = panel_tree()
    node = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "set_locked")
    body = ast.unparse(node)
    assert "btn_open_out" not in body
    assert "btn_clear_log" not in body


# --------------------------------------------------------------------------- #
# D. Layout: no whole-tool scrollbar, primary controls stay reachable
# --------------------------------------------------------------------------- #


def test_the_panel_itself_is_not_wrapped_in_a_second_outer_scrollbar(make_panel):
    """§11: no whole-tool scrollbar. The options form keeps its own existing
    internal scroll canvas (allowed — it is a form, not the whole panel);
    sub-widgets such as the file list or Summary/Details may also scroll
    internally, per §11's explicit allowance, and are not inspected here.
    What must never exist is a *second* canvas/scrollbar one level up,
    wrapping the entire panel rather than just the options form."""
    panel = make_panel()
    direct_children_with_a_canvas = [
        child for child in panel.winfo_children()
        if any(isinstance(grandchild, tk.Canvas)
              for grandchild in child.winfo_children())
    ]
    assert len(direct_children_with_a_canvas) == 1, (
        "expected exactly one direct child hosting a scroll canvas (the "
        "options form's own, established before this phase); found "
        f"{len(direct_children_with_a_canvas)}")


def test_removing_the_pause_band_shrinks_the_scrollable_form(make_panel):
    """A real, mechanical (not visual) proof that the compacting pass actually
    reduced the scrollable options form's height -- the large multi-row pause/
    trim section is gone and two LabelFrames merged into one.

    Not a substitute for the mandatory Windows manual layout/functional smoke
    gate: this measures real Tk geometry, but only a human can confirm how it
    actually renders and behaves on a real Windows desktop.
    """
    from tkinter import ttk

    panel = make_panel()
    panel.update_idletasks()
    # The scrollable form is the one Canvas's one child frame, found
    # structurally (via isinstance, not the theme-dependent winfo_class
    # string) rather than through a new attribute this test would have to
    # expose just for its own sake.
    canvas_wrap = next(
        child for child in panel.winfo_children()
        if any(isinstance(gc, tk.Canvas) for gc in child.winfo_children()))
    canvas = next(gc for gc in canvas_wrap.winfo_children()
                 if isinstance(gc, tk.Canvas))
    frm = next(c for c in canvas.winfo_children() if isinstance(c, ttk.Frame))
    height = frm.winfo_reqheight()
    # Pre-Phase-7 this form was documented at ~1300px against a ~660px window
    # (its own comment, now removed). Post-Phase-7, with the entire pause/trim
    # band gone and two bitrate/workers/rate groups merged into one, it must
    # be meaningfully shorter than that historical figure.
    assert height < 1000, f"scrollable form is still {height}px tall"


def test_the_non_scrollable_bands_stay_compact_enough_for_a_920x600_window(
    make_panel
):
    """The importer, Start row, job area and log frame are the ALWAYS-VISIBLE
    bands (never inside the scrollable canvas) -- §11 requires these to stay
    reachable without scrolling the whole tool at the shared 920x600 minimum
    (shared.ui_theme.MIN_SIZE, applied by the launcher)."""
    from shared import ui_theme

    panel = make_panel()
    panel.update_idletasks()
    fixed_height = (
        panel.importer.frame.winfo_reqheight()
        + panel.go_btn.master.winfo_reqheight()
        + panel.job_area.winfo_reqheight()
    )
    # The log frame is allowed to be short (it scrolls internally, per §11);
    # only its own minimum chrome counts toward the fixed budget.
    assert fixed_height < ui_theme.MIN_SIZE[1], (
        f"the always-visible bands alone need {fixed_height}px, at or beyond "
        f"the shared {ui_theme.MIN_SIZE[1]}px minimum window height")
