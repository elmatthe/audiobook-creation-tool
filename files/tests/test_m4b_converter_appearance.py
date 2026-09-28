"""M4B Converter guided layout — v0.6.6 Phase 4.

The Converter was the last Family-A tool still drawn with classic/native widgets
in one tall single column (queue, options, Convert, run area, a separate raw
"Log"): in Dark it was a light island, and inside the real launcher's 920x600
content area its run controls and logs were squeezed. Phase 4 rebuilds its
*presentation* on the approved Cover/TTS interiors (the maintainer's 2026-09-28
ruling makes the approved Cover UI the concrete visual reference), without
touching one conversion, metadata, chapter, artwork, numbering, retry or output
rule:

  LEFT   1. Sources / 2. Conversion & Metadata / 3. Output & Run
  RIGHT  Activity (Summary | Detailed, Clear Log)

with Output structure (Whole book / Split by chapter) first in Section 2, and
-- where the vertical workflow cannot fit -- the approved TTS small-window
precedent: 1 over 2 on the left, 3 over Activity on the right.

What is proved here:

* a real panel built against an explicit Dark bundle is Dark everywhere a person
  looks -- no ttk widget it owns is left on a generic (native) style and no
  widget is handed a color literal;
* the replacement metadata fields stay visible and are disabled exactly when
  they cannot apply (Write none, or a run in flight), with typed text kept;
* a live Light/Dark toggle is presentation-only -- imports, selection, mode,
  metadata values, output settings, log, layout and a *running* job survive;
* the imported list carries the shared §4 keyboard contract;
* inside the **real launcher shell** every required control is on screen with
  Activity on the right, at 920x600, 1024x720, 1280x900 and 1920x1009.
"""

from __future__ import annotations

import ast
import tkinter as tk
from tkinter import ttk
from unittest import mock

import pytest

from shared import appearance
from shared import job_control as jc
from shared import output_paths
from shared import ui_theme

from mp3_tools import m4b_converter as panel_module
from mp3_tools.m4b_metadata import MetadataMode
from mp3_tools.m4b_plan import ConversionMode

from test_m4b_converter_importing import add_files, books
from test_m4b_converter_jobs import (  # noqa: F401 - fixtures are used by name
    PANEL_SOURCE,
    Clock,
    logger,
    make_panel,
    output_base,
    run_env,
    start,
    tk_root,
)
from test_m4b_conversion_plan import _reservation


def _bundle(root, value: str) -> dict:
    return appearance.build_bundle(ttk.Style(root), value, platform="win32", root=root)


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _settled(root, times: int = 8) -> None:
    for _ in range(times):
        root.update_idletasks()
        root.update()


def _is_aqua(widget) -> bool:
    return widget.tk.call("tk", "windowingsystem") == "aqua"


def _state(widget) -> str:
    return str(widget.cget("state"))


# --------------------------------------------------------------------------- #
# A. The Family-A composition, on the shared compact control language
# --------------------------------------------------------------------------- #


def test_the_four_sections_are_the_family_a_workflow(make_panel):
    panel = make_panel()
    titles = [str(section.cget("text")) for section in (
        panel.sources_section, panel.options_section, panel.run_section,
        panel.activity)]
    assert titles == ["1. Sources", "2. Conversion & Metadata", "3. Output & Run",
                      "Activity"]
    # The shared importer lives in Sources; Convert and the shared job controls
    # in Output & Run; the one Summary | Detailed log in Activity.
    assert str(panel.importer.frame.winfo_parent()) == str(panel.sources_section)
    assert str(panel.run_row.winfo_parent()) == str(panel.run_section)
    assert panel.btn_convert.master is panel.run_row
    assert panel.job_area.master is panel.run_row
    assert panel.log.frame.master is panel.activity
    assert panel.jobs.views is panel.log
    # The old separate raw "Log" box is gone: the transcript lives in Detailed.
    assert isinstance(panel.log, panel_module.job_ui.SummaryDetailsView)
    labels = [str(w.cget("text")) for w in _descendants(panel)
              if isinstance(w, ttk.LabelFrame)]
    assert "Log" not in labels


def test_output_structure_leads_section_two_and_is_prominent(make_panel, tk_root):
    """Whole book / Split by chapter is the first row of Conversion & Metadata,
    introduced by a heading-weight label, above quality and metadata."""
    dark = _bundle(tk_root, appearance.DARK)
    panel = make_panel(appearance_bundle=dark)
    structure = panel.rb_whole.master
    assert panel.rb_split.master is structure
    assert structure.master is panel.options_section
    assert int(structure.grid_info()["row"]) == 0
    assert str(panel.structure_label.cget("text")) == "Output structure"
    assert str(panel.structure_label.cget("style")) == dark["styles"]["subheading"]
    for later in (panel.entry_quality.master, panel.rb_preserve.master,
                  panel.title_entry, panel.chk_auto_num.master):
        assert int(later.grid_info()["row"]) > 0
    # Still one batch-wide choice, defaulting to Whole book.
    assert panel.var_mode.get() == ConversionMode.WHOLE.value
    assert str(panel.rb_whole.cget("variable")) == str(panel.rb_split.cget("variable"))


def test_a_dark_bundle_colors_the_panel_and_its_four_sections(make_panel, tk_root):
    dark = _bundle(tk_root, appearance.DARK)
    panel = make_panel(appearance_bundle=dark)
    colors, style = dark["colors"], ttk.Style(panel)
    assert style.lookup(str(panel.cget("style")), "background") == colors["window"]
    assert style.lookup(str(panel.workflow.cget("style")), "background") == colors["window"]
    for section in (panel.sources_section, panel.options_section, panel.run_section,
                    panel.activity):
        assert style.lookup(str(section.cget("style")), "background") == colors["surface"]
    assert panel.importer.list.listbox.cget("background") == colors["field"]
    for pane in (panel.log.summary_text, panel.log.details_text):
        assert pane.cget("background") == colors["field"]
        assert pane.cget("foreground") == colors["text"]


def test_no_converter_owned_ttk_widget_is_left_on_a_generic_style(make_panel, tk_root):
    """Every ttk widget in the panel -- its own and the shared importer/job/log
    components it hosts -- is on a ``Compact.*`` style. A generic (empty) style
    renders native and light inside a Dark tool."""
    if _is_aqua(tk_root):
        pytest.skip("aqua keeps native controls")
    panel = make_panel(appearance_bundle=_bundle(tk_root, appearance.DARK))
    generic = []
    for widget in _descendants(panel):
        cls = widget.winfo_class()
        if not (cls.startswith("T") or cls == "Treeview"):
            continue
        try:
            name = str(widget.cget("style"))
        except tk.TclError:
            continue
        if not name.startswith(appearance.STYLE_PREFIX + "."):
            generic.append(f"{cls} {widget}")
    assert not generic, generic


def test_no_color_literal_is_passed_to_any_widget_in_the_panel_source():
    """Colors come only from the shared palette's styles."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    offenders = [
        (node.lineno, keyword.arg)
        for node in ast.walk(tree) if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg in ("foreground", "background", "fg", "bg")
    ]
    assert not offenders, offenders


def test_the_activity_and_run_area_are_the_shared_compact_presentation(make_panel, tk_root):
    dark = _bundle(tk_root, appearance.DARK)
    panel = make_panel(appearance_bundle=dark)
    styles = dark["styles"]
    assert str(panel.log.frame.cget("style")) == styles["notebook"]
    assert [panel.log.frame.tab(i, "text") for i in range(2)] == ["Summary", "Detailed"]
    assert str(panel.btn_clear_log.cget("style")) == styles["button"]
    assert str(panel.progress.bar.cget("style")) == styles["progressbar"]
    assert str(panel.progress.frame.cget("style")) == styles["card"]
    assert str(panel.jobs.status.label_status.cget("style")) == styles["secondary_label"]
    # Convert is the panel's default button -- the ordinary compact button with
    # ttk's restrained accent outline, exactly as TTS's Start and Cover's Resize.
    assert str(panel.btn_convert.cget("style")) == styles["button"]
    assert str(panel.btn_convert.cget("default")) == "active"
    cancel = [b for b in panel.jobs.controls.buttons.values()
              if str(b.cget("text")) == "Cancel"]
    assert cancel and str(cancel[0].cget("style")) == styles["danger_button"]
    for widget, key in ((panel.entry_quality, "spinbox"), (panel.title_entry, "entry"),
                        (panel.entry_outdir, "entry"), (panel.rb_whole, "radiobutton"),
                        (panel.rb_strip, "radiobutton"),
                        (panel.chk_auto_num, "checkbutton")):
        assert str(widget.cget("style")) == styles[key], str(widget)


# --------------------------------------------------------------------------- #
# B. Replacement fields: always visible, disabled only where they cannot apply
# --------------------------------------------------------------------------- #


def test_the_metadata_fields_follow_the_mode_and_never_disappear(make_panel):
    panel = make_panel()
    fields = panel.replacement_fields()
    assert fields == (panel.title_entry, panel.artist_entry,
                      panel.album_artist_entry, panel.album_entry)
    grid = [field.grid_info() for field in fields]
    # Preserve (the default): a filled field overrides the source, so usable.
    assert panel.var_metadata_mode.get() == MetadataMode.PRESERVE.value
    assert all(_state(field) == "normal" for field in fields)
    panel.album_entry.insert(0, "Kept")
    for mode, expected in ((MetadataMode.STRIP, "disabled"),
                           (MetadataMode.REPLACE, "normal"),
                           (MetadataMode.STRIP, "disabled"),
                           (MetadataMode.PRESERVE, "normal")):
        panel.var_metadata_mode.set(mode.value)
        assert all(_state(field) == expected for field in fields), mode
        # Never hidden, never moved: the form does not jump.
        assert [field.grid_info() for field in fields] == grid
        assert panel.album_entry.get() == "Kept"


def test_a_run_keeps_the_fields_disabled_and_write_none_survives_the_unlock(make_panel):
    panel = make_panel()
    panel.disable_inputs(True)
    for mode in MetadataMode:
        panel.var_metadata_mode.set(mode.value)
        assert all(_state(f) == "disabled" for f in panel.replacement_fields()), mode
    panel.var_metadata_mode.set(MetadataMode.STRIP.value)
    panel.disable_inputs(False)
    assert all(_state(f) == "disabled" for f in panel.replacement_fields())
    panel.var_metadata_mode.set(MetadataMode.REPLACE.value)
    assert all(_state(f) == "normal" for f in panel.replacement_fields())


def test_disabling_is_presentation_only_the_options_read_the_same(make_panel):
    """The typed values reach the frozen options exactly as before, whatever
    the fields' enabled state; Write none's own semantics are the metadata
    module's, untouched."""
    panel = make_panel()
    panel.var_metadata_mode.set(MetadataMode.REPLACE.value)
    panel.title_entry.insert(0, "A Title")
    panel.album_entry.insert(0, "An Album")
    panel.var_metadata_mode.set(MetadataMode.STRIP.value)
    options = panel.read_options()
    assert options.metadata_mode is MetadataMode.STRIP
    assert options.replacement["title"] == "A Title"
    assert options.replacement["album"] == "An Album"


# --------------------------------------------------------------------------- #
# C. A live toggle is presentation-only
# --------------------------------------------------------------------------- #


def test_a_live_toggle_preserves_every_piece_of_panel_state(make_panel, tk_root, tmp_path):
    style = ttk.Style(tk_root)
    light = appearance.build_bundle(style, appearance.LIGHT, platform="win32",
                                    root=tk_root)
    panel = make_panel(appearance_bundle=light)
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    order = panel.manager.snapshot().occurrence_ids
    panel.importer.list.select((order[1],))
    panel.var_mode.set(ConversionMode.SPLIT.value)
    panel.var_metadata_mode.set(MetadataMode.REPLACE.value)
    panel.title_entry.insert(0, "Title")
    panel.artist_entry.insert(0, "Artist")
    panel.album_artist_entry.insert(0, "Album Artist")
    panel.album_entry.insert(0, "Album")
    panel.var_quality.set(5)
    panel.var_auto_num.set(True)
    panel.var_start_num.set(7)
    outdir = panel.var_outdir.get()
    panel.log.append("kept across the toggle")
    panel.log.append_detail("a detailed line")
    widgets = (panel.importer.list.listbox, panel.title_entry, panel.btn_convert,
               panel.log.summary_text, panel.jobs, panel.progress)
    mode = panel.layout_mode
    before = panel.read_options()

    panel._on_appearance_changed(_bundle(tk_root, appearance.DARK))
    panel._on_appearance_changed(_bundle(tk_root, appearance.LIGHT))

    assert panel.manager.snapshot().occurrence_ids == order
    assert panel.manager.selection == (order[1],)
    assert panel.importer.list.selection == (order[1],)
    assert panel.read_options() == before
    assert panel.var_outdir.get() == outdir
    assert all(_state(f) == "normal" for f in panel.replacement_fields())
    assert "kept across the toggle" in panel.log.summary
    assert "a detailed line" in panel.log.details
    assert panel.layout_mode == mode
    assert (panel.importer.list.listbox, panel.title_entry, panel.btn_convert,
            panel.log.summary_text, panel.jobs, panel.progress) == widgets


def test_toggling_mid_run_leaves_the_running_job_alone(make_panel, tk_root, tmp_path,
                                                       run_env):
    """A theme switch between Start and the worker's end touches no controller,
    adapter, progress model or plan: the run settles exactly as it would have."""
    panel = make_panel(appearance_bundle=_bundle(tk_root, appearance.LIGHT))
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    params = start(panel)
    controller, jobs, snapshot = panel.job_controller, panel.jobs, panel.run_snapshot
    assert controller.state is jc.JobState.RUNNING
    assert _state(panel.btn_convert) == "disabled"

    panel._on_appearance_changed(_bundle(tk_root, appearance.DARK))
    panel._pump.tick()
    assert panel.job_controller is controller and panel.jobs is jobs
    assert panel.run_snapshot is snapshot and panel._busy.is_set()
    assert _state(panel.btn_convert) == "disabled"
    assert all(_state(f) == "disabled" for f in panel.replacement_fields())

    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()
    assert controller.state is jc.JobState.SUCCEEDED
    assert not panel._busy.is_set()
    assert _state(panel.btn_convert) == "normal"
    assert any(line.startswith("All done.") for line in panel.log.summary)
    _bundle(tk_root, appearance.LIGHT)


def test_a_closed_panel_stops_listening_for_appearance_changes(make_panel):
    panel = make_panel()
    assert panel._on_appearance_changed in appearance._listeners
    panel.close()
    assert panel._on_appearance_changed not in appearance._listeners


def test_clear_log_clears_the_visible_activity_only(make_panel):
    panel = make_panel()
    panel.log_write("a transcript line\n")
    panel.log_write("a closing line\n", summary=True)
    assert panel.log.details and panel.log.summary
    panel.btn_clear_log.invoke()
    assert panel.log.summary == () and panel.log.details == ()


def test_the_transcript_goes_to_detailed_and_never_to_summary(make_panel):
    panel = make_panel()
    summary = panel.log.summary
    panel.log_write("  ffmpeg: -i a.m4b out.mp3\n\n")
    assert panel.log.summary == summary
    assert "  ffmpeg: -i a.m4b out.mp3" in panel.log.details


# --------------------------------------------------------------------------- #
# D. The importer's keyboard contract
# --------------------------------------------------------------------------- #


def test_the_imported_list_carries_the_ordered_list_keyboard_contract(
    make_panel, tk_root, tmp_path
):
    """§4 on the Converter's queue: Alt+Down moves the selection as a block,
    Delete removes it, Ctrl+A selects all -- the same guarded actions as the
    buttons. Real key events need a shown, focused window."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    listbox = panel.importer.list.listbox
    bound = listbox.bind()
    for sequence in ("<Key-Delete>", "<Key-BackSpace>", "<Alt-Key-Up>",
                     "<Alt-Key-Down>", "<Control-Key-a>"):
        assert sequence in bound, sequence
    ids = panel.manager.snapshot().occurrence_ids
    tk_root.deiconify()
    try:
        panel.pack(fill="both", expand=True)
        _settled(tk_root)
        listbox.focus_force()
        _settled(tk_root)
        panel.importer.list.select((ids[0],))
        listbox.event_generate("<Alt-Down>")
        _settled(tk_root, 2)
        assert panel.manager.snapshot().occurrence_ids[1] == ids[0]
        listbox.event_generate("<Delete>")
        _settled(tk_root, 2)
        assert ids[0] not in panel.manager.snapshot().occurrence_ids
        listbox.event_generate("<Control-a>")
        _settled(tk_root, 2)
        assert set(panel.manager.selection) == set(panel.manager.snapshot().occurrence_ids)
    finally:
        panel.pack_forget()
        tk_root.withdraw()


# --------------------------------------------------------------------------- #
# E. The real launcher shell: every control on screen, Activity on the right
# --------------------------------------------------------------------------- #

MINIMUM = "{}x{}".format(*ui_theme.MIN_SIZE)
#: The two small content areas take the approved split; the two large ones the
#: vertical workflow with Activity beside it.
SHELL_GEOMETRIES = {MINIMUM: "split", ui_theme.DEFAULT_GEOMETRY: "split",
                    "1280x900": "wide", "1920x1009": "wide"}


@pytest.fixture
def fake_settings(monkeypatch):
    """In-memory launcher/appearance storage: no test touches settings.json."""
    import launcher

    store: dict = {}

    class _Settings:
        @staticmethod
        def get(key, default=None):
            return store.get(key, default)

        @staticmethod
        def set(key, value, **_kwargs):
            store[key] = value
            return True

    monkeypatch.setattr(launcher, "app_settings", _Settings)
    monkeypatch.setattr(appearance, "app_settings", _Settings)
    return store


def _fresh_shell(root, geometry):
    import launcher

    root.deiconify()
    app = launcher.LauncherApp(root)
    root.geometry(geometry)
    _settled(root)
    app.select_tool("m4b_converter")
    _settled(root)
    return app


def _tear_down_shell(root, existing):
    for child in list(root.winfo_children()):
        if child not in existing:
            child.destroy()
    try:
        root.protocol("WM_DELETE_WINDOW", "")
    except tk.TclError:  # pragma: no cover - no handler was installed
        pass
    _settled(root)
    root.withdraw()


def _required_controls(panel) -> dict:
    controls = {"import " + key: button
                for key, button in panel.importer.list.buttons.items()}
    controls.update({"type " + key: button
                     for key, button in panel.importer.options.type_buttons.items()})
    options = panel.importer.options
    controls.update({
        "list": panel.importer.list.listbox,
        "Include subfolders": options.check_subfolders,
        "Include hidden folders": options.check_hidden,
        "Allow duplicate files": options.check_duplicates,
        "Cancel Import": panel.importer.status.button_cancel,
        "Whole book": panel.rb_whole,
        "Split by chapter": panel.rb_split,
        "MP3 quality": panel.entry_quality,
        "Preserve": panel.rb_preserve,
        "Replace": panel.rb_replace,
        "Write none": panel.rb_strip,
        "Title": panel.title_entry,
        "Artist": panel.artist_entry,
        "Album Artist": panel.album_artist_entry,
        "Album": panel.album_entry,
        "Auto-number tracks": panel.chk_auto_num,
        "Start #": panel.entry_start_num,
        "Output": panel.entry_outdir,
        "Open Output Folder": panel.btn_open_out,
        "Convert": panel.btn_convert,
        "progress": panel.progress.bar,
        "Clear Log": panel.btn_clear_log,
        "Summary | Detailed": panel.log.frame,
    })
    controls.update({action.name: button
                     for action, button in panel.jobs.controls.buttons.items()})
    return controls


def _inside(widget, host) -> bool:
    top, left = widget.winfo_rooty(), widget.winfo_rootx()
    bottom, right = top + widget.winfo_height(), left + widget.winfo_width()
    host_top, host_left = host.winfo_rooty(), host.winfo_rootx()
    return (host_top <= top and bottom <= host_top + host.winfo_height()
            and host_left <= left and right <= host_left + host.winfo_width())


def _assert_on_screen(app, panel, where):
    host = app.content
    missing = [name for name, widget in _required_controls(panel).items()
               if not (widget.winfo_ismapped() and _inside(widget, host)
                       and widget.winfo_height() >= 10)]
    assert not missing, f"not on screen at {where}: {missing}"


def _assert_activity_right(panel, where):
    activity_left = panel.activity.winfo_rootx()
    for section in (panel.sources_section, panel.options_section):
        assert activity_left >= section.winfo_rootx() + section.winfo_width(), where


@pytest.mark.parametrize("geometry", sorted(SHELL_GEOMETRIES))
def test_every_required_control_is_on_screen_with_activity_right_in_the_real_shell(
    fake_settings, output_base, tk_root, geometry
):
    """No core scrolling: at every supported size each control is simply there,
    Activity is right of Sources and Conversion & Metadata, and the list and the
    log keep usable height. 920x600 is below the aqua minimum, so that one case
    is Windows-only."""
    if geometry == MINIMUM and _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = app.containers["m4b_converter"].winfo_children()[0]
        _assert_on_screen(app, panel, geometry)
        _assert_activity_right(panel, geometry)
        assert panel.layout_mode == SHELL_GEOMETRIES[geometry], (geometry,
                                                                 panel.layout_mode)
        # The flexible regions keep a usable size: the list at least one row,
        # the log at least its floor lines.
        assert panel.importer.list.listbox.winfo_height() >= panel._needs["list_row_px"]
        line = panel._needs["log_give"] / (panel_module.LOG_HEIGHT
                                           - panel_module.LOG_FLOOR_LINES)
        assert panel.log.summary_text.winfo_height() >= \
            panel_module.LOG_FLOOR_LINES * line - 2
        if panel.layout_mode == "wide":
            # 1 over 2 over 3, one vertical column.
            assert (panel.sources_section.winfo_rooty()
                    < panel.options_section.winfo_rooty()
                    < panel.run_section.winfo_rooty())
            assert panel.run_section.winfo_rootx() < panel.activity.winfo_rootx()
        else:
            # The approved TTS precedent: 3 over Activity on the right.
            assert panel.run_section.winfo_rootx() == panel.activity.winfo_rootx()
            assert panel.run_section.winfo_rooty() < panel.activity.winfo_rooty()
    finally:
        _tear_down_shell(tk_root, existing)


def test_write_none_and_a_filled_queue_still_fit_at_the_real_minimum(
    fake_settings, output_base, tk_root, tmp_path
):
    """The minimum with the list populated and the fields disabled: the list
    scrolls within its floor, and nothing else moves off screen."""
    if _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["m4b_converter"].winfo_children()[0]
        add_files(panel, *books(tmp_path / "src", *(f"B{n:02}.m4b" for n in range(30))))
        panel.var_metadata_mode.set(MetadataMode.STRIP.value)
        _settled(tk_root)
        _assert_on_screen(app, panel, "filled, Write none")
        _assert_activity_right(panel, "filled, Write none")
        assert all(_state(f) == "disabled" for f in panel.replacement_fields())
    finally:
        _tear_down_shell(tk_root, existing)


def test_a_live_toggle_in_the_real_shell_keeps_the_layout_and_state(
    fake_settings, output_base, tk_root
):
    """The shell's own Light/Dark toggle, end to end: the panel is Dark after
    it, Light again after a second press, and neither press moves a pixel of
    the layout or a value the person entered."""
    if _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["m4b_converter"].winfo_children()[0]
        panel.var_quality.set(4)
        panel.var_mode.set(ConversionMode.SPLIT.value)
        before = (panel.layout_mode, panel.btn_convert.winfo_rootx(),
                  panel.btn_convert.winfo_rooty(), panel.activity.winfo_width())
        style = ttk.Style(panel)
        app._toggle_appearance()
        _settled(tk_root)
        assert panel.log.summary_text.cget("background") == \
            appearance._PALETTES[appearance.DARK]["field"]
        assert style.lookup(str(panel.options_section.cget("style")), "background") == \
            appearance._PALETTES[appearance.DARK]["surface"]
        app._toggle_appearance()
        _settled(tk_root)
        assert panel.log.summary_text.cget("background") == \
            appearance._PALETTES[appearance.LIGHT]["field"]
        after = (panel.layout_mode, panel.btn_convert.winfo_rootx(),
                 panel.btn_convert.winfo_rooty(), panel.activity.winfo_width())
        assert after == before
        assert panel.var_quality.get() == 4
        assert panel.var_mode.get() == ConversionMode.SPLIT.value
    finally:
        _tear_down_shell(tk_root, existing)
