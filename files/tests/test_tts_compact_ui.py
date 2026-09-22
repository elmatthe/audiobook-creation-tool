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
    assert "Whole files only, never within one" in text


def test_the_workers_caption_points_to_the_truthful_effective_cap_report():
    text = source()
    assert "effective cap logged below" in text
    # v0.6.5 Phase 7 remediation: the separate "Engine output" LabelFrame is
    # gone -- the effective-workers line the caption refers to now lands in
    # the one Summary/Detailed log's Detailed tab instead.
    assert 'text="Engine output"' not in text


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
    panel._append_engine_output("hello world\n")
    assert "hello world" in panel.log.rendered(panel.log.details_text)
    panel.clear_log()
    assert panel.log.rendered(panel.log.details_text).strip() == ""
    assert panel.log.rendered(panel.log.summary_text).strip() == ""
    # Both panes must return to their normal read-only state, not stay editable.
    assert str(panel.log.details_text.cget("state")) == "disabled"
    assert str(panel.log.summary_text.cget("state")) == "disabled"


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
#
# The final v0.6.5 Phase 7 layout-refinement pass removed the options form's
# canvas/scrollbar entirely (it shrank enough, across the Compact UI pass and
# this one, that it no longer needs its own scroll mechanism) and adopted the
# same weighted-row scheme the MP3 Tool and M4B Converter already use for the
# identical "fixed bands exceed the 920x600 minimum" problem: the imported
# queue and the one Summary/Detailed log carry the weight and compress/scroll
# locally, the options form and the Start row are pinned at weight=0, and the
# shared run controls' row is protected by a measured floor
# (_hold_job_area_open, mirrors the M4B Converter's own fix) rather than a
# hard-coded pixel count. A remediation pass then consolidated the JobAdapter's
# own Summary/Details view and the separate "Engine output" ScrolledText into
# this one panel-owned job_ui.SummaryDetailsView (matches the MP3 Tool/M4B
# Maker/M4B Metadata Editor pattern), so row 3 (the shared run controls) is now
# pinned too and row 4 (the log) absorbed the weight it gave up.
# --------------------------------------------------------------------------- #


def _widgets_of(root, cls) -> list:
    found = []
    for child in root.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_widgets_of(child, cls))
    return found


def test_no_canvas_anywhere_in_the_panel(make_panel):
    """§11: no whole-tool scrollbar, and -- now that the options form shrank
    enough to drop its own canvas too -- no page canvas of any kind. Matches
    the MP3 Tool's own established convention for this exact situation
    (``test_no_whole_tool_scrollbar_only_local_ones``)."""
    panel = make_panel()
    assert _widgets_of(panel, tk.Canvas) == [], "no page canvas anywhere"
    assert not hasattr(panel, "options_canvas")


def test_exactly_one_summary_details_notebook_and_no_engine_output_widget(make_panel):
    """v0.6.5 Phase 7 remediation: the JobAdapter's own internally built
    Summary/Details view and the separate "Engine output" ScrolledText below
    it are gone, replaced by one panel-owned job_ui.SummaryDetailsView --
    mirrors the sibling tools' own proof of the identical shape
    (test_mp3_tool_ui.py)."""
    from tkinter import scrolledtext as _scrolledtext
    from tkinter import ttk as _ttk

    panel = make_panel()
    notebooks = _widgets_of(panel, _ttk.Notebook)
    assert len(notebooks) == 1
    assert notebooks[0] is panel.log.frame
    tabs = [notebooks[0].tab(tab_id, "text") for tab_id in notebooks[0].tabs()]
    assert tabs == ["Summary", "Detailed"]
    assert _widgets_of(panel, _scrolledtext.ScrolledText) == []
    label_texts = [str(w.cget("text")) for w in _widgets_of(panel, _ttk.LabelFrame)]
    assert not any("Engine output" in text for text in label_texts)


def test_every_scrollbar_belongs_to_a_locally_scrolling_widget(make_panel):
    """The imported queue's file list and the one shared Summary/Detailed log
    may each scroll locally (§11's explicit allowance). Every ``Scrollbar`` in
    the panel must be owned by one of those, never by the panel itself or by
    the (now-removed) options form."""
    from tkinter import ttk as _ttk

    panel = make_panel()
    scrollbars = _widgets_of(panel, _ttk.Scrollbar) + _widgets_of(panel, tk.Scrollbar)
    local_masters = {panel.importer.list.frame,
                     panel.log.summary_text.master, panel.log.details_text.master}
    # job_ui's Summary/Details text widgets each sit beside their own Scrollbar
    # in a private page frame -- collect every plausible "owns a scrollable
    # text widget" master rather than hard-coding job_ui's private attributes.
    local_masters |= {
        w.master for w in _widgets_of(panel, tk.Text) + _widgets_of(panel, tk.Listbox)
    }
    assert scrollbars, "the variable-length regions should scroll locally"
    for bar in scrollbars:
        assert bar.master is not panel, str(bar)


def test_the_options_form_is_a_plain_pinned_frame_not_inside_a_canvas(make_panel):
    """The form (Voice/Engine + Audio/Processing + run options) is now an
    ordinary ``ttk.Frame`` gridded directly at row 1, pinned at weight=0 so
    its controls are never squeezed below what they ask for."""
    from tkinter import ttk as _ttk

    panel = make_panel()
    frm = next(c for c in panel.winfo_children() if c.grid_info().get("row") == 1)
    assert isinstance(frm, _ttk.Frame)
    assert not isinstance(frm.master, tk.Canvas)
    assert frm.master is panel
    assert panel.grid_rowconfigure(1)["weight"] == 0


def test_removing_the_pause_band_and_the_canvas_kept_the_form_compact(make_panel):
    """A real, mechanical (not visual) proof that the form stays compact after
    both layout passes -- the pause/trim band, the canvas/scrollbar machinery,
    and the redundant footer prose are all gone.

    Not a substitute for the mandatory Windows manual layout/functional smoke
    gate: this measures real Tk geometry, but only a human can confirm how it
    actually renders and behaves on a real Windows desktop.
    """
    panel = make_panel()
    panel.update_idletasks()
    frm = next(c for c in panel.winfo_children() if c.grid_info().get("row") == 1)
    height = frm.winfo_reqheight()
    # Pre-Phase-7 this form was documented at ~1300px against a ~660px window
    # (its own comment, long since removed). The Compact UI pass brought it to
    # ~445px; this final layout pass (shorter footer/caption, tighter padding,
    # no canvas chrome) brings it lower still.
    assert height < 400, f"the options form is still {height}px tall"


@pytest.mark.parametrize("geometry", ["920x600", "1280x900"])
def test_no_primary_band_overlaps_another(make_panel, geometry):
    """The real regression this whole pass exists to prevent: at the
    supported Windows minimum, and at a larger (roughly maximized) window,
    none of the five top-level bands may overlap another. Mirrors the
    reachability convention ``test_mp3_tool_layout.py``/``test_m4b_layout.py``
    already use for the aqua case, applied here for the Windows case those
    files explicitly leave to this panel's own suite."""
    panel = make_panel()
    top = panel.winfo_toplevel()
    was_withdrawn = top.state() == "withdrawn"
    # make_panel only constructs the panel; the real launcher (build_ui) is
    # what fills the window with it (panel.pack(fill=tk.BOTH, expand=True)),
    # and this measurement is meaningless without that -- an unmanaged panel
    # never receives the toplevel's geometry at all, so every row keeps its
    # own natural size regardless of what ``geometry()`` below asks for.
    panel.pack(fill=tk.BOTH, expand=True)
    # Deiconified because every assertion below is about what is genuinely on
    # screen: winfo_rootx/rooty/ismapped on a withdrawn toplevel say nothing
    # reliable (matches test_mp3_tool_layout.py/test_m4b_layout.py's own
    # convention for the identical measurement).
    top.deiconify()
    top.geometry(geometry)
    for _ in range(6):
        top.update_idletasks()
        top.update()
    try:
        def box(w):
            return (w.winfo_rootx(), w.winfo_rooty(),
                   w.winfo_rootx() + w.winfo_width(), w.winfo_rooty() + w.winfo_height())

        def overlaps(a, b):
            return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])

        frm = next(c for c in panel.winfo_children() if c.grid_info().get("row") == 1)
        bands = {
            "importer": panel.importer.frame,
            "options_form": frm,
            "start_row": panel.go_btn.master,
            "job_area": panel.job_area,
            "log_frame": panel.log.frame,
        }
        boxes = {name: box(w) for name, w in bands.items()}
        names = list(boxes)
        offenders = [
            (names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))
            if overlaps(boxes[names[i]], boxes[names[j]])
        ]
        assert not offenders, f"overlapping bands at {geometry}: {offenders}"

        # Every primary, always-relevant control is mapped (on screen)
        # regardless of how much the variable-length regions had to compress.
        for widget in (panel.importer.options.frame, panel.voice_combo,
                      panel.combo_bitrate, panel.spin_workers, panel.go_btn,
                      panel.btn_open_out, panel.btn_clear_log):
            assert widget.winfo_ismapped(), widget
    finally:
        panel.pack_forget()
        if was_withdrawn:
            top.withdraw()


def test_the_non_scrollable_bands_stay_within_the_920x600_minimum(make_panel):
    """The options form and the Start row are pinned (weight=0): §11 requires
    these -- the controls that never scroll -- to fit inside the shared
    920x600 minimum (shared.ui_theme.MIN_SIZE) on their own, leaving whatever
    remains to the queue/job-area/log rows that are allowed to compress."""
    from shared import ui_theme

    panel = make_panel()
    panel.update_idletasks()
    frm = next(c for c in panel.winfo_children() if c.grid_info().get("row") == 1)
    fixed_height = frm.winfo_reqheight() + panel.go_btn.master.winfo_reqheight()
    assert fixed_height < ui_theme.MIN_SIZE[1], (
        f"the pinned bands alone need {fixed_height}px, at or beyond the "
        f"shared {ui_theme.MIN_SIZE[1]}px minimum window height")


@pytest.mark.parametrize("label,edge_shown,kokoro_shown", [
    (vr.DEFAULT_VOICE_LABEL, True, False),
    ("Kokoro Female (Default) - Heart (en-US)", False, True),
    ("Chatterbox - Female 1", False, False),
])
def test_backend_switching_shows_the_correct_rate_control_at_the_920x600_minimum(
    make_panel, label, edge_shown, kokoro_shown
):
    """Re-proves the existing per-backend rate-control test (section B, above)
    at the exact supported minimum window, per this pass's own instruction to
    verify backend switching under the constrained size, not just unsized."""
    panel = make_panel()
    top = panel.winfo_toplevel()
    top.geometry("920x600")
    for _ in range(6):
        top.update_idletasks()
        top.update()
    panel.selected_voice_label.set(label)
    panel._on_voice_selected()
    top.update_idletasks()
    assert bool(panel.edge_rate_frm.winfo_manager()) is edge_shown
    assert bool(panel.kokoro_speed_frm.winfo_manager()) is kokoro_shown


def test_the_log_region_keeps_a_real_visible_floor_at_the_920x600_minimum(make_panel):
    """Regression for a remediation-pass bug: ``_hold_job_area_open`` and
    ``_hold_log_open`` each read the JobAdapter's/view's widgets for a floor
    immediately after building them, before Tk's geometry manager had settled
    a placeholder reqheight into a real one -- which silently pinned row 3's
    floor at a few pixels and left row 4 (the log) with no floor at all, so it
    could be squeezed to a 1x1 sliver at the supported minimum. Both methods
    now force an idle-task pass before measuring; this proves the log stays a
    real, visible, multi-line region rather than collapsing."""
    panel = make_panel()
    top = panel.winfo_toplevel()
    panel.pack(fill=tk.BOTH, expand=True)
    top.deiconify()
    top.geometry("920x600")
    for _ in range(8):
        top.update_idletasks()
        top.update()
    try:
        assert panel.log.frame.winfo_ismapped()
        assert panel.log.frame.winfo_height() > 30, panel.log.frame.winfo_height()
        assert panel.job_area.winfo_height() >= panel.jobs.controls.frame.winfo_reqheight()
    finally:
        panel.pack_forget()
        top.withdraw()
