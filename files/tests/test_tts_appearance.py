"""TTS reference conformance — v0.6.6 Phase 3.

The TTS panel was the one tool interior still drawn entirely with native/classic
widgets: in Dark it was a bright island inside the dark shell. Phase 3 brings it
onto the same shared compact appearance bundle the approved Cover Image panel
uses (the maintainer's 2026-09-28 ruling makes that approved Cover UI the
concrete visual reference for every remaining tool interior), without touching
TTS's text, voice, engine, worker, job or output behaviour.

It also closes a layout gap the v0.6.5 suite could not see. Those tests size a
bare toplevel to 920x600, but inside the real launcher the sidebar and header
leave the panel only 721x457 at that window size (825x577 at 1024x720), and
there the frozen vertical workflow -- and its old Activity-beneath fallback --
put Start, the job controls and Activity below the visible area. By maintainer
ruling (2026-09-28) the small-window arrangement is now 1 over 2 on the left and
3 over Activity on the right; 1280x900 and larger keep the frozen geometry.

What is proved here:

* a real panel built against an explicit Dark bundle is Dark everywhere a
  person looks -- no ttk widget it owns is left on a generic (native) style,
  every caption takes a palette role instead of a color literal, and the
  combobox drop-down lists and Activity panes follow too;
* a live Light/Dark toggle is presentation-only: imports, selection, voice,
  worker count, entered values, log, layout and a *running* job all survive,
  and no widget is rebuilt;
* the importer list carries the shared §4 keyboard contract;
* inside the **real launcher shell** at 920x600, 1024x720 and 1920x1009, every
  required TTS control is on screen with Activity on the right -- including
  the tallest voice notices at the minimum.
"""

from __future__ import annotations

import ast
import tkinter as tk
from tkinter import ttk

import pytest

from shared import appearance
from shared import ui_theme
from shared.job_control import JobState

from tts import epub2tts_gui as panel_module

from test_tts_importing import (  # noqa: F401 - fixtures are used by name
    PANEL_SOURCE,
    make_panel,
    output_base,
    sources,
    stubs,
    tk_root,
)
from test_tts_jobs import WAIT, gated_stubs, wait_for  # noqa: F401

KOKORO = "Kokoro Female (Default) - Heart (en-US)"
CHATTERBOX = "Chatterbox - Female 1"
SETUP_REASON = (
    "Setup required: this voice's reference recording is missing on this "
    "computer. Edge and Kokoro voices are still available; re-run setup to "
    "restore the local cloning voices, then choose this voice again.")


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


# --------------------------------------------------------------------------- #
# A. Dark reaches the whole interior
# --------------------------------------------------------------------------- #


def test_a_dark_bundle_colors_the_panel_and_its_four_sections(make_panel, tk_root):
    dark = _bundle(tk_root, appearance.DARK)
    panel = make_panel(appearance_bundle=dark)
    colors, style = dark["colors"], ttk.Style(panel)
    assert style.lookup(str(panel.cget("style")), "background") == colors["window"]
    assert style.lookup(str(panel.workflow.cget("style")), "background") == colors["window"]
    for section in (panel.sources_section, panel.voice_section, panel.run_section,
                    panel.activity):
        assert style.lookup(str(section.cget("style")), "background") == colors["surface"]


def test_no_tts_owned_ttk_widget_is_left_on_a_generic_style(make_panel, tk_root):
    """The partial-theming regression guard Cover already carries: every ttk
    widget in the panel -- its own and the shared importer/job/log components
    it hosts -- is on a ``Compact.*`` style. A generic (empty) style renders
    native and light inside a Dark tool."""
    if _is_aqua(tk_root):
        pytest.skip("aqua keeps native controls (and the Phase 8 Toolbutton restyle)")
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


def test_every_toned_caption_takes_a_palette_role(make_panel, tk_root):
    """The four caption tones (engine line, Kokoro notice, setup-required line,
    gray notes) follow the palette rather than fixed navy/orange/red/gray."""
    dark = _bundle(tk_root, appearance.DARK)
    panel = make_panel(appearance_bundle=dark,
                       chatterbox_status=lambda voice_id: (False, SETUP_REASON))
    colors, style = dark["colors"], ttk.Style(panel)

    def fg(widget):
        return style.lookup(str(widget.cget("style")), "foreground")

    def bg(widget):
        return style.lookup(str(widget.cget("style")), "background")

    assert fg(panel.backend_lbl) == colors["link"]
    assert fg(panel.kokoro_notice_lbl) == colors["warning"]
    assert fg(panel.voice_status_lbl) == colors["danger"]
    for note in (panel.workers_note, panel.edge_rate_note, panel.output_note,
                 panel.activity_note):
        assert fg(note) == colors["secondary"]
    # All of them sit on the section surface -- no darker/lighter band.
    for label in (panel.backend_lbl, panel.kokoro_notice_lbl, panel.voice_status_lbl,
                  panel.workers_note, panel.output_note, panel.activity_note):
        assert bg(label) == colors["surface"], str(label)


def test_no_color_literal_is_passed_to_any_widget_in_the_panel_source():
    """Structural half of the guard: nothing in the panel passes a
    ``foreground=``/``background=`` keyword. Colors come from the shared
    palette's styles; only ``_tone``'s aqua fallback carries the old native
    caption colors, and it returns them as data, not as a widget keyword."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    offenders = [
        (node.lineno, keyword.arg)
        for node in ast.walk(tree) if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg in ("foreground", "background", "fg", "bg")
    ]
    assert not offenders, offenders


def test_the_activity_region_is_the_shared_compact_presentation(make_panel, tk_root):
    """Summary | Detailed, Clear Log, progress and status all take the same
    compact treatment Cover's Activity/run area does."""
    dark = _bundle(tk_root, appearance.DARK)
    panel = make_panel(appearance_bundle=dark)
    colors, style = dark["colors"], ttk.Style(panel)
    for pane in (panel.log.summary_text, panel.log.details_text):
        assert pane.cget("background") == colors["field"]
        assert pane.cget("foreground") == colors["text"]
    assert str(panel.log.frame.cget("style")) == dark["styles"]["notebook"]
    assert str(panel.btn_clear_log.cget("style")) == dark["styles"]["button"]
    assert str(panel.progress.bar.cget("style")) == dark["styles"]["progressbar"]
    assert str(panel.progress.frame.cget("style")) == dark["styles"]["card"]
    assert str(panel.jobs.status.label_status.cget("style")) == \
        dark["styles"]["secondary_label"]
    # Start is the panel's default button -- the ordinary compact button with
    # ttk's restrained accent outline, exactly as Cover's Resize Covers.
    assert str(panel.go_btn.cget("style")) == dark["styles"]["button"]
    assert str(panel.go_btn.cget("default")) == "active"
    cancel = [b for b in panel.jobs.controls.buttons.values()
              if str(b.cget("text")) == "Cancel"]
    assert cancel and str(cancel[0].cget("style")) == dark["styles"]["danger_button"]
    assert style.lookup(dark["styles"]["button"], "background") == colors["elevated"]


def test_the_combobox_drop_down_lists_follow_the_appearance(make_panel, tk_root):
    """The voice and bitrate lists are classic Tk listboxes ttk styles cannot
    reach; the shared helper colors them, and recolors them on a toggle."""
    if _is_aqua(tk_root):
        pytest.skip("aqua drop-downs are native")
    style = ttk.Style(tk_root)
    light = appearance.build_bundle(style, appearance.LIGHT, platform="win32",
                                    root=tk_root)
    panel = make_panel(appearance_bundle=light)

    def listbox_of(combo):
        popdown = combo.tk.eval(f"ttk::combobox::PopdownWindow {combo}")
        return f"{popdown}.f.l"

    for combo in (panel.voice_combo, panel.combo_bitrate):
        assert combo.tk.call(listbox_of(combo), "cget", "-background") == \
            light["colors"]["field"]
    dark = appearance.build_bundle(style, appearance.DARK, platform="win32", root=tk_root)
    panel._on_appearance_changed(dark)
    for combo in (panel.voice_combo, panel.combo_bitrate):
        listbox = listbox_of(combo)
        assert combo.tk.call(listbox, "cget", "-background") == dark["colors"]["field"]
        assert combo.tk.call(listbox, "cget", "-foreground") == dark["colors"]["text"]


# --------------------------------------------------------------------------- #
# B. A live toggle is presentation-only
# --------------------------------------------------------------------------- #


def test_a_live_toggle_preserves_every_piece_of_panel_state(make_panel, tk_root, tmp_path):
    style = ttk.Style(tk_root)
    light = appearance.build_bundle(style, appearance.LIGHT, platform="win32",
                                    root=tk_root)
    chosen = sources(tmp_path / "Books", "a.txt", "b.txt", "c.pdf")
    panel = make_panel(appearance_bundle=light, choose_files=lambda: chosen)
    panel.importer.add_files()
    order = panel.manager.snapshot().occurrence_ids
    panel.importer.list.select((order[1],))
    panel.selected_voice_label.set(KOKORO)
    panel._on_voice_selected()
    panel.kokoro_speed_var.set("1.25")
    panel.workers_var.set("3")
    panel.bitrate_var.set("320k")
    panel.resume_var.set(False)
    panel.overwrite_var.set(False)
    panel.log.append("kept across the toggle")
    panel.log.append_detail("a detailed line")
    widgets = (panel.importer.list.listbox, panel.voice_combo, panel.spin_workers,
               panel.go_btn, panel.log.summary_text, panel.jobs, panel.progress)
    mode = panel._layout_mode

    dark = appearance.build_bundle(style, appearance.DARK, platform="win32", root=tk_root)
    panel._on_appearance_changed(dark)
    back = appearance.build_bundle(style, appearance.LIGHT, platform="win32", root=tk_root)
    panel._on_appearance_changed(back)

    assert panel.manager.snapshot().occurrence_ids == order
    assert panel.manager.selection == (order[1],)
    assert panel.importer.list.selection == (order[1],)
    assert panel.selected_voice_label.get() == KOKORO
    assert panel.voice_var.get() == panel_module.get_voice(KOKORO).voice_id
    assert panel.kokoro_speed_var.get() == "1.25"
    assert panel.workers_var.get() == "3"
    assert panel.bitrate_var.get() == "320k"
    assert panel.resume_var.get() is False and panel.overwrite_var.get() is False
    assert "kept across the toggle" in panel.log.summary
    assert "a detailed line" in panel.log.details
    assert panel._layout_mode == mode
    assert (panel.importer.list.listbox, panel.voice_combo, panel.spin_workers,
            panel.go_btn, panel.log.summary_text, panel.jobs, panel.progress) == widgets
    assert all(w.winfo_exists() for w in widgets[:5])


def test_toggling_mid_run_leaves_the_running_job_alone(
    make_panel, tk_root, output_base, tmp_path, gated_stubs
):
    """A theme switch during a conversion touches no controller, adapter,
    progress model or worker: the run keeps running and settles normally."""
    style = ttk.Style(tk_root)
    light = appearance.build_bundle(style, appearance.LIGHT, platform="win32",
                                    root=tk_root)
    chosen = sources(tmp_path / "Loose", "gate.txt")
    panel = make_panel(appearance_bundle=light, choose_files=lambda: chosen)
    panel.importer.add_files()
    panel.run_job()
    worker, controller, jobs = panel._worker, panel._controller, panel.jobs
    try:
        assert gated_stubs.entered.wait(WAIT), "the engine never started"
        assert controller.state is JobState.RUNNING
        dark = appearance.build_bundle(style, appearance.DARK, platform="win32",
                                       root=tk_root)
        panel._on_appearance_changed(dark)
        panel._pump.tick()
        assert panel._controller is controller and panel.jobs is jobs
        assert controller.state is JobState.RUNNING
        assert panel._busy.is_set()
        gated_stubs.release.set()
        wait_for(lambda: controller.is_terminal, "the run never finished", panel=panel)
        assert controller.state is JobState.SUCCEEDED
    finally:
        panel.cancel_job()
        gated_stubs.release.set()
        worker.join(WAIT)
        appearance.build_bundle(style, appearance.LIGHT, platform="win32", root=tk_root)


def test_a_closed_panel_stops_listening_for_appearance_changes(make_panel):
    panel = make_panel()
    assert panel._on_appearance_changed in appearance._listeners
    panel.close()
    assert panel._on_appearance_changed not in appearance._listeners


def test_clear_log_clears_the_visible_activity_only(make_panel):
    panel = make_panel()
    panel._append_engine_output("an engine line\n")
    panel.log.append("a summary line")
    assert panel.log.details and panel.log.summary
    panel.btn_clear_log.invoke()
    assert panel.log.summary == () and panel.log.details == ()


# --------------------------------------------------------------------------- #
# C. The importer's keyboard contract
# --------------------------------------------------------------------------- #


def test_the_imported_list_carries_the_ordered_list_keyboard_contract(
    make_panel, tk_root, tmp_path
):
    """§4 on TTS's queue: Alt+Down moves the selection as a block, Delete
    removes it, Ctrl+A selects all -- the same guarded actions as the buttons.
    Real key events need a shown, focused window."""
    chosen = sources(tmp_path / "Books", "a.txt", "b.txt", "c.txt")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
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
# D. The real launcher shell: every control on screen, Activity on the right
# --------------------------------------------------------------------------- #

MINIMUM = "{}x{}".format(*ui_theme.MIN_SIZE)
SHELL_GEOMETRIES = [MINIMUM, ui_theme.DEFAULT_GEOMETRY, "1920x1009"]


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
    app.select_tool("tts")
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
        "Voice": panel.voice_combo,
        "MP3 bitrate": panel.combo_bitrate,
        "File workers": panel.spin_workers,
        "Output": panel.entry_outdir,
        "Open Output Folder": panel.btn_open_out,
        "Resume": panel.chk_resume,
        "Overwrite": panel.chk_overwrite,
        "Start": panel.go_btn,
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
    for section in (panel.sources_section, panel.voice_section):
        assert activity_left >= section.winfo_rootx() + section.winfo_width(), where


@pytest.mark.parametrize("geometry", SHELL_GEOMETRIES)
def test_every_required_control_is_on_screen_with_activity_right_in_the_real_shell(
    fake_settings, output_base, tk_root, geometry
):
    """No core scrolling: at every supported size each control is simply there,
    and Activity is right of Sources and Voice & Audio. 920x600 is below the
    aqua minimum, so that one case is Windows-only."""
    if geometry == MINIMUM and _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = app.containers["tts"].winfo_children()[0]
        _assert_on_screen(app, panel, geometry)
        _assert_activity_right(panel, geometry)
        # The mode names are Windows measurements; aqua picks its own from its
        # own metrics (Phase 9), and the on-screen checks hold either way.
        if not _is_aqua(tk_root):
            expected = "wide" if geometry == "1920x1009" else "split"
            assert panel._layout_mode[0] == expected, (geometry, panel._layout_mode)
        # The flexible regions keep a usable size: the list at least one row,
        # the log at least its floor lines.
        row_px = panel._needs["list_row_px"]
        assert panel.importer.list.listbox.winfo_height() >= row_px
        line = panel._needs["log_give"] / (panel_module.LOG_HEIGHT
                                           - panel_module.LOG_FLOOR_LINES)
        assert panel.log.summary_text.winfo_height() >= \
            panel_module.LOG_FLOOR_LINES * line - 2
    finally:
        _tear_down_shell(tk_root, existing)


@pytest.mark.parametrize("voice", (KOKORO, CHATTERBOX))
def test_the_tallest_voice_notices_still_fit_at_the_real_minimum(
    fake_settings, output_base, tk_root, monkeypatch, voice
):
    """Kokoro's download notice and a Chatterbox setup-required message are
    the tallest Voice & Audio states; at the real 920x600 content area the list
    gives way and every control stays on screen."""
    if _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    monkeypatch.setattr(panel_module, "chatterbox_status",
                        lambda voice_id: (False, SETUP_REASON))
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["tts"].winfo_children()[0]
        panel.selected_voice_label.set(voice)
        panel._on_voice_selected()
        _settled(tk_root)
        _assert_on_screen(app, panel, voice)
        _assert_activity_right(panel, voice)
        if voice == KOKORO:
            assert panel.kokoro_notice_lbl.winfo_ismapped()
            assert _inside(panel.kokoro_speed_frm, app.content)
        else:
            assert panel.voice_status_lbl.winfo_ismapped()
            assert _inside(panel.voice_status_lbl, app.content)
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
        panel = app.containers["tts"].winfo_children()[0]
        panel.workers_var.set("5")
        before = (panel._layout_mode, panel.go_btn.winfo_rootx(),
                  panel.go_btn.winfo_rooty(), panel.activity.winfo_width())
        style = ttk.Style(panel)
        app._toggle_appearance()
        _settled(tk_root)
        assert panel.log.summary_text.cget("background") == \
            appearance._PALETTES[appearance.DARK]["field"]
        assert style.lookup(str(panel.voice_section.cget("style")), "background") == \
            appearance._PALETTES[appearance.DARK]["surface"]
        app._toggle_appearance()
        _settled(tk_root)
        assert panel.log.summary_text.cget("background") == \
            appearance._PALETTES[appearance.LIGHT]["field"]
        after = (panel._layout_mode, panel.go_btn.winfo_rootx(),
                 panel.go_btn.winfo_rooty(), panel.activity.winfo_width())
        assert after == before
        assert panel.workers_var.get() == "5"
    finally:
        _tear_down_shell(tk_root, existing)
