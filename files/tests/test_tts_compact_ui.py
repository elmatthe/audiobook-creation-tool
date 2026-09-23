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


def test_audio_group_holds_bitrate_workers_and_rate_controls(make_panel):
    """One audio group inside section 2 (Voice & Audio): bitrate, workers and
    whichever rate control the backend supports, in one place."""
    panel = make_panel()
    assert panel.combo_bitrate.master is panel.audio_group
    assert panel.spin_workers.master is panel.audio_group
    assert panel.edge_rate_frm.master is panel.audio_group
    assert panel.kokoro_speed_frm.master is panel.audio_group
    assert panel.audio_group.master is panel.voice_section
    assert panel.voice_section.cget("text") == "2. Voice & Audio"


def test_the_workers_control_is_labelled_as_requested_file_level_concurrency():
    text = source()
    assert "File workers (requested)" in text
    assert "Whole files only, never within one" in text


def test_the_workers_caption_points_to_the_truthful_effective_cap_report():
    text = source()
    # The effective-workers line is written to the Detailed log; the caption
    # names that place rather than a position ("below"), which the responsive
    # layout does not guarantee -- on a wide window the log is to the right.
    assert "effective count shown" in text and "in the Detailed log" in text
    assert "logged below" not in text
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
# D. Layout: a measured, responsive four-section composition
#
# v0.6.5 Phase 7 UI/UX redesign. The panel is 1. Sources, 2. Voice & Audio,
# 3. Output & Run (the workflow) plus Activity (the one Summary | Detailed log).
# ``TtsPanel._choose_layout`` arranges them from the panel's size alone, using
# thresholds measured from the live widgets: two columns (workflow left,
# Activity right) when both fit at their natural widths, otherwise Activity
# drops beneath the workflow; Voice & Audio and Output & Run sit side by side
# whenever the width allows. Never a whole-tool scrollbar -- only the imported
# list and the log scroll, and each keeps a measured floor.
#
# Every geometry test packs and deiconifies the panel: make_panel only
# constructs it, and winfo_* geometry of an unmanaged panel or a withdrawn
# toplevel says nothing reliable (the convention test_mp3_tool_layout.py and
# test_m4b_layout.py already use).
# --------------------------------------------------------------------------- #

GEOMETRIES = ("920x600", "1024x720", "1280x900", "1920x1009")


def _widgets_of(root, cls) -> list:
    found = []
    for child in root.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_widgets_of(child, cls))
    return found


def _is_inside(widget, ancestor) -> bool:
    node = widget
    while node is not None:
        if node is ancestor:
            return True
        node = node.master
    return False


class _Shown:
    """Pack the panel into its toplevel at one size, and undo that afterwards."""

    def __init__(self, panel, geometry):
        self.panel = panel
        self.top = panel.winfo_toplevel()
        self.geometry = geometry

    def __enter__(self):
        self.was_withdrawn = self.top.state() == "withdrawn"
        self.panel.pack(fill=tk.BOTH, expand=True)
        self.top.deiconify()
        self.resize(self.geometry)
        return self

    def resize(self, geometry):
        self.top.geometry(geometry)
        for _ in range(10):
            self.top.update_idletasks()
            self.top.update()

    def __exit__(self, *exc):
        self.panel.pack_forget()
        if self.was_withdrawn:
            self.top.withdraw()
        return False


def _box(panel, widget):
    x = widget.winfo_rootx() - panel.winfo_rootx()
    y = widget.winfo_rooty() - panel.winfo_rooty()
    return (x, y, x + widget.winfo_width(), y + widget.winfo_height())


def _overlaps(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _regions(panel):
    return {"sources": panel.sources_section, "voice": panel.voice_section,
            "run": panel.run_section, "activity": panel.activity}


def _assert_composed(panel, where):
    """No region overlaps another, every region is wholly inside the panel, and
    every primary control is on screen."""
    width, height = panel.winfo_width(), panel.winfo_height()
    boxes = {name: _box(panel, widget) for name, widget in _regions(panel).items()}
    for name, (left, top, right, bottom) in boxes.items():
        assert left >= 0 and top >= 0, (where, name, boxes[name])
        assert right <= width and bottom <= height, (where, name, boxes[name], width, height)
    names = list(boxes)
    offenders = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]
                 if _overlaps(boxes[a], boxes[b])]
    assert not offenders, (where, offenders)
    for widget in (panel.importer.list.listbox, panel.importer.options.frame,
                   panel.importer.list.buttons["add_files"], panel.voice_combo,
                   panel.combo_bitrate, panel.spin_workers, panel.entry_outdir,
                   panel.btn_open_out, panel.chk_resume, panel.chk_overwrite,
                   panel.go_btn, panel.jobs.controls.frame, panel.jobs.status.frame,
                   panel.btn_clear_log, panel.log.frame):
        assert widget.winfo_ismapped(), (where, str(widget))
        wbox = _box(panel, widget)
        assert wbox[2] <= width and wbox[3] <= height, (where, str(widget), wbox)


def test_no_canvas_anywhere_in_the_panel(make_panel):
    """§11: no whole-tool scrollbar and no page canvas of any kind. Matches the
    MP3 Tool's own convention (``test_no_whole_tool_scrollbar_only_local_ones``)."""
    panel = make_panel()
    assert _widgets_of(panel, tk.Canvas) == [], "no page canvas anywhere"
    assert not hasattr(panel, "options_canvas")


def test_exactly_one_summary_details_notebook_and_no_engine_output_widget(make_panel):
    """One panel-owned job_ui.SummaryDetailsView and no separate "Engine
    output" box -- mirrors the sibling tools' proof of the same shape
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


def test_every_scrollbar_belongs_to_the_list_or_the_log(make_panel):
    """Only the imported list and the Summary | Detailed log scroll (§11's
    explicit allowance); no scrollbar belongs to the panel or a section."""
    from tkinter import ttk as _ttk

    panel = make_panel()
    scrollbars = _widgets_of(panel, _ttk.Scrollbar) + _widgets_of(panel, tk.Scrollbar)
    local_masters = {panel.importer.list.listbox.master,
                     panel.log.summary_text.master, panel.log.details_text.master}
    assert scrollbars, "the variable-length regions should scroll locally"
    for bar in scrollbars:
        assert bar.master in local_masters, str(bar)


def test_the_sections_follow_the_workflow_and_own_their_controls(make_panel):
    """Numbered in the order a first-time user works, and every control lives
    in the section it belongs to -- re-parented, never duplicated."""
    from tkinter import ttk as _ttk

    panel = make_panel()
    titles = [str(section.cget("text")) for section in
              (panel.sources_section, panel.voice_section, panel.run_section,
               panel.activity)]
    assert titles == ["1. Sources", "2. Voice & Audio", "3. Output & Run", "Activity"]
    for section in _regions(panel).values():
        assert isinstance(section, _ttk.LabelFrame)
    assert _is_inside(panel.importer.frame, panel.sources_section)
    for widget in (panel.voice_combo, panel.backend_lbl, panel.kokoro_notice_lbl,
                   panel.voice_status_lbl, panel.combo_bitrate, panel.spin_workers,
                   panel.edge_rate_frm, panel.kokoro_speed_frm):
        assert _is_inside(widget, panel.voice_section), str(widget)
    for widget in (panel.entry_outdir, panel.btn_open_out, panel.chk_resume,
                   panel.chk_overwrite, panel.go_btn, panel.job_area,
                   panel.jobs.frame):
        assert _is_inside(widget, panel.run_section), str(widget)
    for widget in (panel.log.frame, panel.btn_clear_log):
        assert _is_inside(widget, panel.activity), str(widget)
    # One of each: no second importer, log, Start or job area anywhere.
    starts = [b for b in _widgets_of(panel, _ttk.Button) if str(b.cget("text")) == "Start"]
    assert starts == [panel.go_btn]


def test_start_is_the_primary_action_leading_the_job_controls(make_panel):
    panel = make_panel()
    assert str(panel.go_btn.cget("default")) == "active"
    assert panel.go_btn.master is panel.job_area.master
    assert panel.go_btn.grid_info()["column"] == 0
    assert panel.job_area.grid_info()["column"] == 1


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_every_region_fits_and_nothing_overlaps(make_panel, geometry):
    """The regression the redesign exists for: at the 920x600 minimum the old
    stacked bands needed ~720 px, so the log sat wholly below the window. At
    every measured size now, each section is inside the panel, none overlaps
    another, and every primary control is on screen."""
    panel = make_panel()
    with _Shown(panel, geometry):
        _assert_composed(panel, geometry)


def test_the_minimum_window_stacks_and_large_windows_use_two_columns(make_panel):
    """At 920x600 the two columns cannot both have their natural widths, so
    Activity sits beneath the workflow; maximized, it is a column to its right."""
    panel = make_panel()
    with _Shown(panel, "920x600") as shown:
        assert panel._layout_mode[0] == "stacked"
        assert _box(panel, panel.activity)[1] >= _box(panel, panel.run_section)[3]
        shown.resize("1920x1009")
        assert panel._layout_mode == ("wide", "stack")
        assert _box(panel, panel.activity)[0] >= _box(panel, panel.workflow)[2]


def _assert_vertical_workflow(panel, where):
    """Sources, then Voice & Audio directly beneath it, then Output & Run
    directly beneath that: one column, same left edge and width, in order."""
    sources_box, voice, run = (_box(panel, panel.sources_section),
                               _box(panel, panel.voice_section),
                               _box(panel, panel.run_section))
    assert sources_box[0] == voice[0] == run[0], (where, sources_box, voice, run)
    assert sources_box[2] == voice[2] == run[2], (where, sources_box, voice, run)
    gap = panel_module.SECTION_GAP
    assert 0 <= voice[1] - sources_box[3] <= gap + 2, (where, sources_box, voice)
    assert 0 <= run[1] - voice[3] <= gap + 2, (where, voice, run)


@pytest.mark.parametrize("geometry", ("1024x720", "1280x900", "1600x900", "1920x1009",
                                      "2560x1400"))
def test_beside_activity_the_workflow_is_one_vertical_column(make_panel, geometry):
    """The maintainer's final composition: whenever Activity is beside the
    workflow, it reads 1. Sources, 2. Voice & Audio, 3. Output & Run from
    top to bottom -- never 2 and 3 side by side -- with Activity to the right
    of all three and filling the height."""
    panel = make_panel()
    with _Shown(panel, geometry):
        assert panel._layout_mode == ("wide", "stack"), geometry
        _assert_vertical_workflow(panel, geometry)
        activity = _box(panel, panel.activity)
        assert activity[0] >= _box(panel, panel.run_section)[2]
        assert activity[1] == panel_module.OUTER_PAD
        assert activity[3] == panel.winfo_height() - panel_module.OUTER_PAD
        _assert_composed(panel, geometry)


def test_no_size_ever_puts_sections_2_and_3_side_by_side_beside_activity(make_panel):
    """``_choose_layout`` is a pure function of size, so sweep it: across every
    width from the 920 minimum to 2560 and every height from 600 to 1440, a
    two-column result is always the vertical workflow."""
    panel = make_panel()
    seen = set()
    for width in range(920, 2561, 20):
        for height in range(600, 1441, 40):
            mode = panel._choose_layout(width, height)
            seen.add(mode)
            if mode[0] == "wide":
                assert mode[1] == "stack", (width, height, mode)
    assert ("wide", "stack") in seen and ("stacked", "side") in seen, seen


def test_the_minimum_falls_back_only_because_the_vertical_workflow_cannot_fit(
    make_panel
):
    """Why 920x600 is the one place 2 and 3 share a row: measured, the vertical
    workflow at its floors is taller than the window's content height by
    itself -- before Activity gets a single pixel -- and it cannot sit beside
    Activity because both columns' natural widths exceed the window width."""
    panel = make_panel()
    flow_w, flow_floor = panel._workflow_needs("stack")
    room_w = 920 - 2 * panel_module.OUTER_PAD
    room_h = 600 - 2 * panel_module.OUTER_PAD
    assert flow_floor > room_h, (flow_floor, room_h)
    assert flow_w + panel._needs["activity"][0] + panel_module.COLUMN_GAP > room_w
    assert panel._choose_layout(920, 600) == ("stacked", "side")


@pytest.mark.parametrize("geometry", ("1280x900", "1920x1009", "2560x1400"))
def test_sources_stays_compact_beside_activity(make_panel, geometry):
    """Sources is only as tall as a useful queue needs: WIDE_LIST_ROWS rows at
    most, the list does not stretch, and whatever height the workflow does not
    need is left below Output & Run rather than handed to an empty list."""
    panel = make_panel()
    with _Shown(panel, geometry):
        listbox = panel.importer.list.listbox
        rows = int(listbox.cget("height"))
        assert rows == panel_module.WIDE_LIST_ROWS, (geometry, rows)
        row_px = panel._needs["list_row_px"]
        assert listbox.winfo_height() <= rows * row_px + 6, (geometry, listbox.winfo_height())
        assert (panel.sources_section.winfo_height()
                <= panel.sources_section.winfo_reqheight())


def test_a_short_two_column_window_shows_fewer_list_rows_not_less_workflow(make_panel):
    """At the 1024x720 launcher default the list gives up rows (never below
    IMPORTER_FLOOR_ROWS) so sections 2 and 3 stay whole and on screen."""
    panel = make_panel()
    with _Shown(panel, "1024x720"):
        rows = int(panel.importer.list.listbox.cget("height"))
        assert panel_module.IMPORTER_FLOOR_ROWS <= rows < panel_module.WIDE_LIST_ROWS
        _assert_vertical_workflow(panel, "1024x720")
        _assert_composed(panel, "1024x720")


def test_a_large_queue_scrolls_inside_the_compact_list(make_panel, tmp_path):
    names = [f"Chapter {index:02d}.txt" for index in range(1, 61)]
    chosen = sources(tmp_path / "Big", *names)
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    for geometry in GEOMETRIES:
        with _Shown(panel, geometry):
            listbox = panel.importer.list.listbox
            assert listbox.size() == 60
            first, last = listbox.yview()
            assert first == 0.0 and last < 0.5, (geometry, first, last)
            _assert_composed(panel, (geometry, "60 files"))


@pytest.mark.parametrize("geometry", ("1280x900", "1920x1009"))
def test_activity_is_the_dominant_region_on_wide_windows(make_panel, geometry):
    """The workflow keeps its measured natural width plus at most
    WORKFLOW_BREATHING; every other pixel of width goes to Activity."""
    panel = make_panel()
    with _Shown(panel, geometry):
        natural, _ = panel._workflow_needs("stack")
        assert panel.workflow.winfo_width() <= natural + panel_module.WORKFLOW_BREATHING
        assert panel.activity.winfo_width() > panel.workflow.winfo_width()
        if geometry == "1920x1009":
            assert panel.activity.winfo_width() >= 2 * panel.workflow.winfo_width()


LONG_SETUP_REASON = (
    "Setup required: this voice's reference recording is missing on this "
    "computer. Edge and Kokoro voices are still available; re-run setup to "
    "restore the local cloning voices, then choose this voice again.")


@pytest.mark.parametrize("geometry,voice", [
    *[(g, None) for g in GEOMETRIES],
    ("920x600", "Kokoro Female (Default) - Heart (en-US)"),
    ("920x600", "Chatterbox - Female 1"),
])
def test_the_log_and_the_list_keep_their_floors(make_panel, geometry, voice):
    """Neither scrolling region collapses: the log keeps LOG_FLOOR_LINES lines
    and the imported list IMPORTER_FLOOR_ROWS rows, at every size -- including
    the minimum window with the tallest voice messages showing, which is where
    the floors actually bind."""
    import tkinter.font as tkfont

    panel = make_panel(chatterbox_status=lambda voice_id: (False, LONG_SETUP_REASON))
    with _Shown(panel, geometry) as shown:
        if voice is not None:
            panel.selected_voice_label.set(voice)
            panel._on_voice_selected()
            shown.resize(geometry)
            _assert_composed(panel, (geometry, voice))
        line = tkfont.Font(font=panel.log.summary_text.cget("font")).metrics("linespace")
        assert panel.log.summary_text.winfo_height() >= panel_module.LOG_FLOOR_LINES * line
        listbox = panel.importer.list.listbox
        row = listbox.winfo_reqheight() / panel_module.IMPORTER_LIST_HEIGHT
        assert listbox.winfo_height() >= int(panel_module.IMPORTER_FLOOR_ROWS * row) - 2


@pytest.mark.parametrize("geometry", ("920x600", "1280x900"))
def test_the_floors_are_the_measured_values(make_panel, geometry):
    """The floors are wired to live measurements: the log row keeps
    LOG_FLOOR_LINES lines everywhere, and at the stacked minimum -- the one
    layout where the list is elastic -- the list row keeps IMPORTER_FLOOR_ROWS
    rows (beside Activity the list's rows are set explicitly instead). At the
    supported sizes grid absorbs the shortfall before either floor binds (the
    test above), so this is the proof the guard exists for larger fonts or
    scaling, where it would."""
    panel = make_panel()
    with _Shown(panel, geometry):
        needs = panel._needs
        if panel._layout_mode[0] == "stacked":
            assert int(panel.workflow.grid_rowconfigure(0)["minsize"]) == (
                panel.sources_section.winfo_reqheight() - needs["list_give"])
        else:
            assert int(panel.workflow.grid_rowconfigure(0)["weight"]) == 0
        assert int(panel.activity.grid_rowconfigure(1)["minsize"]) == (
            panel.log.frame.winfo_reqheight() - needs["log_give"])
        assert needs["list_give"] > 0 and needs["log_give"] > 0


def test_the_log_grows_substantially_on_larger_windows(make_panel):
    areas = {}
    for geometry in ("920x600", "1280x900", "1920x1009"):
        panel = make_panel()
        with _Shown(panel, geometry):
            text = panel.log.summary_text
            areas[geometry] = text.winfo_width() * text.winfo_height()
    assert areas["1280x900"] >= 4 * areas["920x600"], areas
    assert areas["1920x1009"] >= 6 * areas["920x600"], areas


@pytest.mark.parametrize("start", ("920x600", "1920x1009"))
@pytest.mark.parametrize("geometry", ("1024x720", "1280x900", "1600x900", "1920x1009"))
def test_two_column_widths_are_exactly_the_layout_math(make_panel, geometry, start):
    """Regression for a bug found while building this layout: captions that
    re-wrapped to their *allocated* width let the workflow column's request
    chase its allocation, so after starting at the stacked minimum and
    widening to 1024x720 the log was squeezed below its own natural width.
    In every two-column size the workflow is exactly its natural width plus
    its breathing room (``_left_width``), and Activity is never below its
    natural width."""
    panel = make_panel()
    with _Shown(panel, start) as shown:
        shown.resize(geometry)
        assert panel._layout_mode[0] == "wide", geometry
        expected = panel._left_width(panel.winfo_width(), panel._layout_mode[1])
        assert abs(panel.workflow.winfo_width() - expected) <= 1, (
            geometry, panel.workflow.winfo_width(), expected)
        assert panel.activity.winfo_width() >= panel._needs["activity"][0], geometry


def test_resizing_is_deterministic_and_never_ratchets_a_column(make_panel):
    """Regression for a bug found while building this layout: wrapped captions
    re-wrapping to their allocated width let the workflow column's request
    chase its allocation and grow on every resize. Widths are now a pure
    function of the window size, whatever sizes came before."""
    panel = make_panel()
    with _Shown(panel, "1280x900") as shown:
        first = (panel.workflow.winfo_width(), panel.activity.winfo_width(),
                 panel._layout_mode)
        for geometry in ("1920x1009", "1024x720", "920x600", "1600x900", "1280x900"):
            shown.resize(geometry)
            _assert_composed(panel, geometry)
        again = (panel.workflow.winfo_width(), panel.activity.winfo_width(),
                 panel._layout_mode)
    assert again == first


@pytest.mark.parametrize("geometry", ("920x600", "1920x1009"))
def test_backend_switching_leaves_no_ghost_controls(make_panel, geometry):
    """Each backend shows exactly its own rate control (Chatterbox: none) and
    its own notices, and the layout stays whole after every switch."""
    panel = make_panel()
    expected = [
        ("Kokoro Female (Default) - Heart (en-US)", False, True, True),
        ("Chatterbox - Female 1", False, False, False),
        (vr.DEFAULT_VOICE_LABEL, True, False, False),
        ("Kokoro Female (Default) - Heart (en-US)", False, True, True),
        (vr.DEFAULT_VOICE_LABEL, True, False, False),
    ]
    with _Shown(panel, geometry) as shown:
        for label, edge, kokoro, notice in expected:
            panel.selected_voice_label.set(label)
            panel._on_voice_selected()
            shown.resize(geometry)
            assert bool(panel.edge_rate_frm.winfo_manager()) is edge, label
            assert bool(panel.kokoro_speed_frm.winfo_manager()) is kokoro, label
            assert bool(panel.kokoro_notice_lbl.winfo_manager()) is notice, label
            _assert_composed(panel, (geometry, label))


@pytest.mark.parametrize("geometry", ("920x600", "1024x720"))
def test_a_setup_required_message_expands_without_corrupting_the_layout(
    make_panel, geometry
):
    reason = ("Setup required: this voice's reference recording is missing on "
              "this computer. Edge and Kokoro voices are still available; "
              "re-run setup to restore the local cloning voices.")
    panel = make_panel(chatterbox_status=lambda voice_id: (False, reason))
    with _Shown(panel, geometry) as shown:
        panel.selected_voice_label.set("Chatterbox - Female 1")
        panel._on_voice_selected()
        shown.resize(geometry)
        assert panel.voice_status_lbl.winfo_manager()
        assert panel.voice_status_lbl.winfo_ismapped()
        wrap = int(float(str(panel.voice_status_lbl.cget("wraplength"))))
        assert 0 < wrap <= panel.voice_section.winfo_width()
        _assert_composed(panel, (geometry, "setup required"))
