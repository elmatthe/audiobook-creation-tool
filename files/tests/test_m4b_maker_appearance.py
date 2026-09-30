"""M4B Maker compact visual standardization — v0.6.6 Phase 7.

The M4B Maker was the second dense multi-Book panel still drawn in the retired
oversized ``ACT.*`` interior. Inside the real launcher's 920x600 content area
(721x457) it asked for 1043x649: the track list, Chapter Titles box and the
four track buttons were never mapped, Remove Book and the custom-destination
toggle were cut off, and the log was 3 px tall. Phase 7 rebuilds its
*presentation* as the dense Family-B hierarchy on the approved
Cover/TTS/Converter/MP3 Tool control language, without touching one Maker
workflow, plan, batch or output rule:

  1. Import & Books   2. Book Settings   3. Tracks, Chapters & Build   Activity

What is proved here:

* the numbered hierarchy, with Activity the universal Summary | Detailed view
  (and Clear Log) at the bottom, and Build the one accent-outlined run action;
* Shared is visibly distinct from Current Book in Light and in Dark, and a Dark
  bundle reaches the whole interior, classic Tk widgets included;
* a live Light/Dark toggle is presentation-only -- Books, current Book,
  selection, Shared and Book values, chapter titles, track order, the run
  options, the custom destination, log, layout and a *running* build survive;
* the track list's §4 shortcuts move a block, obey the run lock and never
  reach an Entry or the Chapter Titles box;
* inside the **real launcher shell** every required control is on screen at
  full size at 920x600, 1024x720, 1280x900 and 1920x1009 -- with the custom
  destination's path row shown too, and with a busy workspace -- with only the
  track list, Chapter Titles and log giving up height.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk

import pytest

# ``shared.paths`` must be imported at collection: the session-scoped log
# sandbox in ``conftest.py`` redirects only modules already imported, and the
# real launcher built below logs through it.
from shared import appearance, ffmpeg_utils, paths, ui_theme  # noqa: F401
from shared.job_control import JobState

from mp3_tools import m4b_artwork_ui, m4b_maker

import test_import_coordination as tic
from test_import_coordination import RecordingThreads
from test_m4b_maker_ui import (  # noqa: F401 - fixtures are collected by name
    add_files,
    import_folder,
    make_panel,
    output_base,
    png,
    tk_root,
    tone,
    tracks,
    widgets_of,
    windows_theme,
)


def _bundle(root, value: str) -> dict:
    return appearance.build_bundle(ttk.Style(root), value, platform="win32", root=root)


def _settled(root, times: int = 8) -> None:
    for _ in range(times):
        root.update_idletasks()
        root.update()


def _is_aqua(widget) -> bool:
    return widget.tk.call("tk", "windowingsystem") == "aqua"


def _within(widget, ancestor) -> bool:
    node = widget
    while node is not None:
        if node is ancestor:
            return True
        node = node.master
    return False


def _linespace(widget) -> int:
    return tkfont.Font(font=widget.cget("font")).metrics("linespace")


def _chroma(color: str) -> float:
    """How colorful, independent of how dark: 0 is grey, 1 a pure hue."""
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return max(channels) - min(channels)


def _names(panel) -> list[str]:
    return [entry.name for entry in panel.workspace.current.files.files]


# --------------------------------------------------------------------------- #
# A. The Family-B hierarchy on the shared compact control language
# --------------------------------------------------------------------------- #


def test_the_four_sections_are_the_family_b_hierarchy(make_panel):
    panel = make_panel()
    assert [str(s.cget("text")) for s in panel.sections] == [
        "1. Import & Books", "2. Book Settings", "3. Tracks, Chapters & Build",
        "Activity"]
    assert tuple(m4b_maker.SECTION_TITLES) == tuple(str(s.cget("text"))
                                                    for s in panel.sections)
    # One column, top to bottom: Activity is last and below, never beside.
    for row, section in enumerate(panel.sections):
        info = section.grid_info()
        assert (int(info["row"]), int(info["column"])) == (row, 0)
    homes = {
        panel.import_section: (panel.btn_import_folder, panel.btn_clear_imports,
                               panel.import_status.frame, panel.output_label,
                               panel.navigator.frame),
        panel.settings_section: (panel.surface.frame, panel.shared_artwork.frame,
                                 panel.book_artwork.frame, *panel.book_entries.values(),
                                 panel.status_label),
        panel.run_section: (panel.track_list, panel.chapter_text, panel.btn_add_files,
                            panel.btn_move_up, panel.btn_move_down,
                            panel.btn_remove_tracks, panel.check_auto_number,
                            panel.entry_start_part, panel.check_fast_first,
                            panel.chk_custom_dest, panel.customrow, panel.btn_build,
                            panel.jobs.frame),
        panel.activity: (panel.log.frame, panel.btn_clear_log, panel.activity_note),
    }
    for section, widgets in homes.items():
        for widget in widgets:
            assert _within(widget, section), (str(widget), section.cget("text"))
    # The one persistent log is the adapter's view, so history survives runs.
    assert panel.jobs.views is panel.log
    assert [panel.log.frame.tab(i, "text") for i in range(2)] == ["Summary", "Detailed"]


def test_build_and_activity_are_the_shared_compact_presentation(make_panel, tk_root):
    dark = _bundle(tk_root, appearance.DARK)
    panel = make_panel(appearance_bundle=dark)
    styles = dark["styles"]
    assert str(panel.log.frame.cget("style")) == styles["notebook"]
    assert str(panel.btn_clear_log.cget("style")) == styles["button"]
    assert str(panel.activity_note.cget("style")) == styles["secondary_label"]
    # Build: the compact button with the restrained accent outline.
    assert str(panel.btn_build.cget("style")) == styles["button"]
    assert str(panel.btn_build.cget("default")) == "active"
    cancel = [b for b in panel.jobs.controls.buttons.values()
              if str(b.cget("text")) == "Cancel"]
    assert cancel and str(cancel[0].cget("style")) == styles["danger_button"]
    assert str(panel.btn_clear_imports.cget("style")) == styles["danger_button"]
    assert str(panel.status.indicator.bar.cget("style")) == styles["progressbar"]
    assert str(panel.status.indicator.frame.cget("style")) == styles["card"]
    assert str(panel.status.label_status.cget("style")) == styles["secondary_label"]
    for widget, key in ((panel.check_auto_number, "checkbutton"),
                        (panel.check_fast_first, "checkbutton"),
                        (panel.chk_custom_dest, "checkbutton"),
                        (panel.entry_start_part, "entry"),
                        (panel.entry_custom, "entry"),
                        (panel.book_entries["title"], "entry"),
                        (panel.navigator.selector, "combobox"),
                        (panel.status_label, "label")):
        assert str(widget.cget("style")) == styles[key], str(widget)


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_shared_is_tinted_and_current_book_is_the_ordinary_surface(
        make_panel, tk_root, value):
    """§2: Shared takes the restrained cool tint with the stronger border and
    heading, Current Book the normal surface and quieter border -- the same
    semantic distinction in Light and in Dark, and never a warning color."""
    bundle = _bundle(tk_root, value)
    panel = make_panel(appearance_bundle=bundle)
    colors, style = bundle["colors"], ttk.Style(panel)
    shared, book = panel.surface.shared_frame, panel.surface.book_frame
    shared_style, book_style = str(shared.cget("style")), str(book.cget("style"))
    assert shared_style == bundle["styles"]["shared_labelframe"]
    assert book_style == bundle["styles"]["labelframe"]

    assert style.lookup(shared_style, "background") == colors["shared_bg"]
    assert style.lookup(shared_style, "bordercolor") == colors["shared_border"]
    assert style.lookup(f"{shared_style}.Label", "foreground") == colors["shared_header"]
    heading = tkfont.Font(font=style.lookup(f"{shared_style}.Label", "font"))
    assert heading.actual("weight") == "bold"
    assert style.lookup(book_style, "background") == colors["surface"]
    assert style.lookup(book_style, "bordercolor") == colors["border"]

    assert colors["shared_bg"] != colors["surface"]
    assert _chroma(colors["shared_bg"]) < 0.15
    assert _chroma(colors["warning"]) > 2 * _chroma(colors["shared_bg"])
    assert m4b_maker.SHARED_TITLE == str(shared.cget("text"))
    assert "applies to every Book and overrides its own value" in m4b_maker.SHARED_TITLE
    assert str(book.cget("text")) == "Current Book"
    # The Shared group's own controls sit on the tint; the Book-only row and
    # the Book's artwork on the ordinary surface.
    assert style.lookup(str(panel.shared_artwork.frame.cget("style")), "background") \
        == colors["shared_bg"]
    for name in panel.surface.fields:
        label = panel.surface._row(name).label
        assert style.lookup(str(label.cget("style")), "background") == colors["shared_bg"]
    assert style.lookup(str(panel.book_own.cget("style")), "background") == colors["surface"]
    assert style.lookup(str(panel.book_artwork.frame.cget("style")), "background") \
        == colors["surface"]


def test_a_dark_bundle_reaches_the_whole_interior(make_panel, tk_root):
    """No light island: the panel, its four sections, the classic Tk track
    list, Chapter Titles box and log panes, and the Book selector's drop-down."""
    dark = _bundle(tk_root, appearance.DARK)
    panel = make_panel(appearance_bundle=dark)
    colors, style = dark["colors"], ttk.Style(panel)
    assert style.lookup(str(panel.cget("style")), "background") == colors["window"]
    for section in panel.sections:
        assert style.lookup(str(section.cget("style")), "background") == colors["surface"]
    for widget in (panel.track_list, panel.chapter_text, panel.log.summary_text,
                   panel.log.details_text):
        assert widget.cget("background") == colors["field"], str(widget)
        assert widget.cget("foreground") == colors["text"], str(widget)
    selector = panel.navigator.selector
    popdown = selector.tk.eval(f"ttk::combobox::PopdownWindow {selector}")
    assert selector.tk.call(f"{popdown}.f.l", "cget", "-background") == colors["field"]
    # Every ttk widget names a compact style: none generic, none ACT.
    generic = [str(w) for w in widgets_of(panel, ttk.Widget) if not str(w.cget("style"))]
    assert generic == []
    assert not [w for w in widgets_of(panel, ttk.Widget)
                if str(w.cget("style")).startswith("ACT.")]


def test_the_artwork_preview_is_compact_and_the_shared_default_is_unchanged(
        make_panel, tmp_path):
    """The Maker's previews are no taller than the control's caption and
    buttons (no layout jump). The shared control's own default is the one the
    Metadata Editor still uses, untouched until its phase."""
    panel = make_panel()
    for control in (panel.shared_artwork, panel.book_artwork):
        assert control.preview_max == m4b_artwork_ui.COMPACT_PREVIEW_MAX == (40, 40)
    panel._choose_artwork = lambda: str(png(tmp_path / "cover.png", size=(600, 400)))
    panel.choose_shared_artwork()
    assert panel.shared_artwork.has_preview
    image = panel.shared_artwork.preview.cget("image")
    assert int(panel.tk.call("image", "height", image)) <= 40
    assert int(panel.tk.call("image", "width", image)) <= 40

    default = m4b_artwork_ui.ArtworkControl(
        ttk.Frame(panel), caption="Artwork", theme={}, shared=False,
        on_choose=lambda: None, on_clear=lambda: None)
    try:
        assert default.preview_max == m4b_artwork_ui.PREVIEW_MAX == (56, 56)
    finally:
        default.close()


# --------------------------------------------------------------------------- #
# B. A live toggle is presentation-only
# --------------------------------------------------------------------------- #


def test_a_live_toggle_preserves_every_piece_of_workspace_state(make_panel, tk_root, tmp_path):
    panel = make_panel(appearance_bundle=_bundle(tk_root, appearance.LIGHT))
    library = tmp_path / "Library"
    for folder in ("A", "B", "C"):
        tracks(library / folder, "01 One.mp3", "02 Two.mp3", "03 Three.mp3")
    import_folder(panel, library)
    assert panel.workspace.count == 3
    panel.navigator.choose(panel.workspace.books[1].book_id)
    panel.surface.set_shared_text("artist", "Shared Author")
    panel.surface.set_book_text("album", "Book Two")
    panel.book_vars["title"].set("The Second Book")
    panel.book_vars["output_filename"].set("second")
    panel.type_chapter_titles("Opening\nMiddle\nEnd")
    panel.var_auto_number.set(True)
    panel.on_auto_number()
    panel.var_start_part.set("4")
    panel.var_fast_first.set(False)
    panel.var_custom_dest.set(True)
    panel._on_custom_dest_change()
    panel.var_custom_path.set(str(tmp_path / "Chosen"))
    panel.select_tracks(0, 1)
    panel.move_down()
    panel.log.append("kept across the toggle")
    panel.log.append_detail("a detailed line")

    def state():
        return (panel.workspace, panel.selected_occurrences(), panel.chapter_titles_text(),
                panel.var_auto_number.get(), panel.var_start_part.get(),
                panel.var_fast_first.get(), panel.custom_destination(),
                panel.navigator.heading_text, panel.density, dict(panel.book_numbers),
                panel.book_field_enabled("series_part"), panel.book_title_text())

    before = state()
    widgets = (panel.track_list, panel.chapter_text, panel.surface, panel.navigator,
               panel.jobs, panel.log.summary_text, panel.btn_build, panel.customrow)

    panel._on_appearance_changed(_bundle(tk_root, appearance.DARK))
    assert panel.track_list.cget("background") == appearance.DARK_COLORS["field"]
    assert panel.chapter_text.cget("background") == appearance.DARK_COLORS["field"]
    panel._on_appearance_changed(_bundle(tk_root, appearance.LIGHT))

    after = state()
    assert after == before
    assert after[0] is before[0], "the workspace snapshot itself is untouched"
    assert before[-2] is False, "Auto-number still disables the manual Series Part"
    assert panel.surface.shared_value("artist") == "Shared Author"
    assert panel.surface.book_value("album") == "Book Two"
    assert panel.customrow.winfo_manager() == "grid"
    assert "kept across the toggle" in panel.log.summary
    assert "a detailed line" in panel.log.details
    assert (panel.track_list, panel.chapter_text, panel.surface, panel.navigator,
            panel.jobs, panel.log.summary_text, panel.btn_build, panel.customrow) == widgets
    assert panel.track_list.cget("background") == appearance.LIGHT_COLORS["field"]


class _Parked(tic.InlineThread):
    """A worker that does not start: the run stays RUNNING for inspection."""

    def start(self):
        pass


@pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(),
                    reason="ffmpeg/ffprobe not available in this environment")
def test_toggling_mid_run_leaves_the_running_build_alone(make_panel, tk_root, tmp_path,
                                                         output_base):
    """A theme switch while a build is under way touches no controller,
    adapter, plan, lock or progress: the run settles as it would have."""
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    tone(root / "B" / "01.mp3")
    panel = make_panel(appearance_bundle=_bundle(tk_root, appearance.LIGHT))
    import_folder(panel, root)
    panel._thread_factory = RecordingThreads(kind=_Parked)
    assert panel.build() is True
    controller, jobs, plan, run = panel.job_controller, panel.jobs, panel.last_plan, panel.run
    assert panel.is_running and controller.state is JobState.RUNNING
    assert "disabled" in panel.btn_build.state()

    panel._on_appearance_changed(_bundle(tk_root, appearance.DARK))
    panel._pump.tick()
    assert panel.job_controller is controller and panel.jobs is jobs
    assert panel.last_plan is plan and panel.run is run and panel.is_running
    assert "disabled" in panel.btn_build.state()
    assert panel.navigator.locked is True
    assert panel.book_field_enabled("title") is False

    panel._thread_factory.bodies[0]()
    panel._pump.tick()
    assert controller.state is JobState.SUCCEEDED
    assert panel.last_result.state is JobState.SUCCEEDED
    assert sorted(p.name for p in plan.root.iterdir() if p.is_file()) == ["A.m4b", "B.m4b"]
    assert "disabled" not in panel.btn_build.state()
    _bundle(tk_root, appearance.LIGHT)


def test_a_closed_panel_stops_listening_for_appearance_changes(make_panel):
    panel = make_panel()
    assert panel._on_appearance_changed in appearance._listeners
    panel.close()
    assert panel._on_appearance_changed not in appearance._listeners


# --------------------------------------------------------------------------- #
# C. The track list's keyboard contract, focus-sensitive and lock-aware
# --------------------------------------------------------------------------- #


@pytest.fixture
def shown(tk_root):
    """The shared module root, briefly shown so a real key event arrives."""
    tk_root.deiconify()
    _settled(tk_root)
    try:
        yield tk_root
    finally:
        tk_root.withdraw()


def _key(root, widget, sequence) -> None:
    widget.focus_force()
    _settled(root, 2)
    widget.event_generate(sequence)
    _settled(root, 2)


def test_shortcuts_move_a_block_and_obey_the_run_lock(make_panel, shown, tmp_path):
    panel = make_panel()
    panel.pack(fill="both", expand=True)
    try:
        add_files(panel, *tracks(tmp_path, "a.mp3", "b.mp3", "c.mp3", "d.mp3"))
        # A multi-selection moves as one block, keeping its internal order.
        panel.select_tracks(0, 1)
        _key(shown, panel.track_list, "<Alt-Down>")
        assert _names(panel) == ["c.mp3", "a.mp3", "b.mp3", "d.mp3"]
        assert sorted(panel.track_list.curselection()) == [1, 2]
        # The chapter defaults follow the new order, as the buttons' do.
        assert panel.chapter_titles_text().splitlines()[0] == "c"

        # While a run owns the track controls, the keys are as locked as the
        # buttons: nothing moves and nothing is removed.
        panel.lock_group.apply(JobState.RUNNING)
        _key(shown, panel.track_list, "<Alt-Up>")
        _key(shown, panel.track_list, "<Delete>")
        _key(shown, panel.track_list, "<BackSpace>")
        assert _names(panel) == ["c.mp3", "a.mp3", "b.mp3", "d.mp3"]

        panel.lock_group.apply(JobState.IDLE)
        _key(shown, panel.track_list, "<Delete>")
        assert _names(panel) == ["c.mp3", "d.mp3"]
        _key(shown, panel.track_list, "<Control-a>")
        assert sorted(panel.track_list.curselection()) == [0, 1]
    finally:
        panel.pack_forget()


def test_text_editing_keys_are_never_hijacked(make_panel, shown, tmp_path):
    """Ctrl+A, Delete and BackSpace in a metadata Entry, a Book-only field,
    Start Part or the Chapter Titles box edit that text; the track list's
    selection and order never move."""
    panel = make_panel()
    panel.pack(fill="both", expand=True)
    try:
        add_files(panel, *tracks(tmp_path, "a.mp3", "b.mp3", "c.mp3"))
        panel.select_tracks(1)
        order = [e.occurrence_id for e in panel.workspace.current.files.files]
        for widget in (panel.surface._row("album").book_entry, panel.book_entries["title"],
                       panel.entry_start_part, panel.chapter_text):
            for sequence in ("<Control-a>", "<Delete>", "<BackSpace>", "<Alt-Down>"):
                _key(shown, widget, sequence)
        assert [e.occurrence_id for e in panel.workspace.current.files.files] == order
        assert panel.track_list.curselection() == (1,)
    finally:
        panel.pack_forget()


def test_tab_order_follows_the_visible_workflow(make_panel, shown, tmp_path):
    """§5: Section 1 → Section 2 → Section 3 → Activity, where practical."""
    panel = make_panel()
    panel.pack(fill="both", expand=True)
    try:
        add_files(panel, *tracks(tmp_path, "a.mp3", "b.mp3"))
        _settled(shown)
        order, widget = [], panel.btn_import_folder
        for _ in range(250):
            section = next((index for index, s in enumerate(panel.sections)
                            if _within(widget, s)), None)
            if section is not None and (not order or order[-1] != section):
                order.append(section)
            widget = widget.tk_focusNext()
            if widget is None or widget is panel.btn_import_folder:
                break
        assert order == [0, 1, 2, 3], order
    finally:
        panel.pack_forget()


# --------------------------------------------------------------------------- #
# D. The real launcher shell: no core scrolling at any supported size
# --------------------------------------------------------------------------- #

MINIMUM = "{}x{}".format(*ui_theme.MIN_SIZE)
#: The launcher's two small content areas take the tight density.
SHELL_GEOMETRIES = {MINIMUM: "tight", ui_theme.DEFAULT_GEOMETRY: "tight",
                    "1280x900": "regular", "1920x1009": "regular"}


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
    app.select_tool("m4b_maker")
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


def _panel(app):
    return app.containers["m4b_maker"].winfo_children()[0]


def _required_controls(panel, *, custom: bool = False) -> dict:
    nav = panel.navigator
    controls = {
        "Import Folder": panel.btn_import_folder,
        "Clear All Imports": panel.btn_clear_imports,
        "Cancel Import": panel.import_status.button_cancel,
        "Import status": panel.import_status.label,
        "Output folder": panel.output_label,
        "Book position": nav.label,
        "Book selector": nav.selector,
        "Shared artwork Choose": panel.shared_artwork.btn_choose,
        "Shared artwork Clear": panel.shared_artwork.btn_clear,
        "Book artwork Choose": panel.book_artwork.btn_choose,
        "Book artwork Clear": panel.book_artwork.btn_clear,
        "Status": panel.status_label,
        "Track list": panel.track_list,
        "Chapter Titles": panel.chapter_text,
        "Add Files": panel.btn_add_files,
        "Move Up": panel.btn_move_up,
        "Move Down": panel.btn_move_down,
        "Remove Selected": panel.btn_remove_tracks,
        "Auto-number": panel.check_auto_number,
        "Start Part": panel.entry_start_part,
        "Start Part label": panel.label_start_part,
        "Try FAST first": panel.check_fast_first,
        "Custom destination": panel.chk_custom_dest,
        "Build": panel.btn_build,
        "progress": panel.status.indicator.bar,
        "Clear Log": panel.btn_clear_log,
        "Summary | Detailed": panel.log.frame,
    }
    if custom:
        controls["Custom path"] = panel.entry_custom
        controls["Browse"] = panel.btn_browse_custom
    controls.update({f"Book {key}": entry for key, entry in panel.book_entries.items()})
    controls.update({f"nav {key}": button for key, button in nav.buttons.items()})
    controls.update({f"job {action.name}": button
                     for action, button in panel.jobs.controls.buttons.items()})
    for name in panel.surface.fields:
        row = panel.surface._row(name)
        controls[f"Shared {name}"] = row.shared_entry
        controls[f"Book {name}"] = row.book_entry
        controls[f"Shared {name} label"] = row.label
        controls[f"Book {name} label"] = row.book_label
    return controls


#: Display-only text allowed to yield width (never height): the output hint
#: shows the path's tail, and a long Book name in the navigator's heading is
#: shown whole in the selector beside it. The custom path entry is a stretching
#: text field whose content scrolls.
YIELDING = ("Output folder", "Book position", "Custom path")


def _problems(app, panel, *, custom: bool = False, yielding=YIELDING) -> list[str]:
    host = app.content
    top, left = host.winfo_rooty(), host.winfo_rootx()
    bottom, right = top + host.winfo_height(), left + host.winfo_width()
    found = []
    for name, widget in _required_controls(panel, custom=custom).items():
        if not widget.winfo_ismapped():
            found.append(f"{name}: not on screen")
            continue
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        if not (left <= x and top <= y and x + widget.winfo_width() <= right
                and y + widget.winfo_height() <= bottom):
            found.append(f"{name}: outside the content area")
        if widget in (panel.track_list, panel.chapter_text, panel.log.frame):
            continue  # the flexible regions: measured against their floors below
        if widget.winfo_height() < widget.winfo_reqheight() - 1:
            found.append(f"{name}: squeezed to {widget.winfo_height()}px tall")
        if name not in yielding and widget.winfo_width() < widget.winfo_reqwidth() - 1:
            found.append(f"{name}: squeezed to {widget.winfo_width()}px of "
                         f"{widget.winfo_reqwidth()}")
    # Every section inside the content area, in order, one above the next.
    previous = top
    for section in panel.sections:
        if section.winfo_rooty() < previous:
            found.append(f"{section.cget('text')}: out of order")
        previous = section.winfo_rooty() + section.winfo_height()
        if previous > bottom:
            found.append(f"{section.cget('text')}: runs below the content area")
    return found


def _assert_floors(panel, where) -> None:
    tight = panel.density == "tight"
    track_floor = (m4b_maker.TIGHT_TRACK_FLOOR_ROWS if tight
                   else m4b_maker.TRACK_FLOOR_ROWS)
    log_floor = m4b_maker.TIGHT_LOG_FLOOR_LINES if tight else m4b_maker.LOG_FLOOR_LINES
    rows = panel.track_list.winfo_height() / _linespace(panel.track_list)
    lines = panel.log.summary_text.winfo_height() / _linespace(panel.log.summary_text)
    assert rows >= track_floor - 0.1, (where, rows)
    assert panel.chapter_text.winfo_height() >= panel.track_list.winfo_height(), where
    assert lines >= log_floor - 0.1, (where, lines)


def _show_custom(panel, root, path: str = "") -> None:
    panel.var_custom_dest.set(True)
    panel._on_custom_dest_change()
    if path:
        panel.var_custom_path.set(path)
    _settled(root)


@pytest.mark.parametrize("custom", [False, True], ids=["standard", "custom-destination"])
@pytest.mark.parametrize("geometry", sorted(SHELL_GEOMETRIES))
def test_every_required_control_is_on_screen_in_the_real_shell(
        fake_settings, tk_root, geometry, custom):
    """No core scrolling: at every supported size each control is simply
    there at its full requested size -- the custom destination's path row
    included -- the four sections stack in order with Activity last, and the
    flexible regions keep their floors. 920x600 is below the aqua minimum, so
    that case is Windows-only."""
    if geometry == MINIMUM and _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = _panel(app)
        if custom:
            _show_custom(panel, tk_root)
        problems = _problems(app, panel, custom=custom)
        assert not problems, f"at {geometry}:\n  " + "\n  ".join(problems)
        # The density names are Windows measurements; aqua picks its own from
        # its own metrics (Phase 9), and the on-screen checks hold either way.
        if not _is_aqua(tk_root):
            assert panel.density == SHELL_GEOMETRIES[geometry], (geometry,
                                                                 panel.density)
        _assert_floors(panel, geometry)
        # Activity is below, as wide as the workflow sections -- never beside.
        widths = {s.winfo_width() for s in panel.sections}
        assert len(widths) == 1, widths
        assert panel.activity.winfo_rooty() > panel.run_section.winfo_rooty()
        assert not widgets_of(panel, tk.Canvas), "no page canvas"
        # The wording follows the density; the variables never do.
        tight = panel.density == "tight"
        assert panel.check_fast_first.cget("text") == (
            m4b_maker.FAST_LABEL_SHORT if tight else m4b_maker.FAST_LABEL)
        assert panel.label_start_part.cget("text") == (
            m4b_maker.START_PART_LABEL_SHORT if tight else m4b_maker.START_PART_LABEL)
        assert panel.chk_custom_dest.cget("text") == m4b_maker.CUSTOM_DEST_LABEL
    finally:
        _tear_down_shell(tk_root, existing)


def test_the_custom_path_row_joins_the_options_line_only_when_tight(fake_settings, tk_root,
                                                                    tmp_path):
    """At the minimum the path row sits on the options line (so turning the
    mode on adds no height); with room it sits beneath. Resizing moves it and
    keeps the chosen path; turning the mode off hides it again."""
    if _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = _panel(app)
        section = panel.run_section.winfo_height()
        chosen = str(tmp_path / "Chosen")
        _show_custom(panel, tk_root, chosen)
        assert panel.density == "tight"
        info = panel.customrow.grid_info()
        assert (int(info["row"]), int(info["column"])) == (0, 5)
        toggle, row = panel.chk_custom_dest, panel.customrow
        assert row.winfo_rooty() < toggle.winfo_rooty() + toggle.winfo_height()
        assert toggle.winfo_rooty() < row.winfo_rooty() + row.winfo_height()
        assert row.winfo_rootx() > toggle.winfo_rootx(), "beside the toggle, same line"
        # No extra line: at most the difference between a button's height
        # (Browse) and a checkbutton's, which the options line now holds.
        grew = panel.run_section.winfo_height() - section
        assert grew <= max(0, panel.btn_browse_custom.winfo_reqheight()
                           - panel.chk_custom_dest.winfo_reqheight()), grew
        assert not _problems(app, panel, custom=True)

        tk_root.geometry("1920x1009")
        _settled(tk_root)
        assert panel.density == "regular"
        info = panel.customrow.grid_info()
        assert (int(info["row"]), int(info["column"])) == (panel._customrow_at, 0)
        assert panel.customrow.winfo_rooty() > panel.chk_custom_dest.winfo_rooty()
        assert panel.custom_destination() == chosen

        tk_root.geometry(MINIMUM)
        _settled(tk_root)
        assert panel.density == "tight" and panel.custom_destination() == chosen
        panel.var_custom_dest.set(False)
        panel._on_custom_dest_change()
        _settled(tk_root)
        assert not panel.customrow.winfo_manager()
        assert panel.custom_destination() is None
        assert not _problems(app, panel)
    finally:
        _tear_down_shell(tk_root, existing)


def test_a_busy_workspace_still_fits_the_real_minimum_without_layout_jumps(
        fake_settings, tk_root, tmp_path):
    """The minimum with a real workload: three Books, many tracks, long names
    and titles, Shared values, chosen artwork, series numbering on and a
    custom destination. Nothing leaves the screen or is squeezed, and Book
    Settings does not grow when artwork appears."""
    if _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = _panel(app)
        settings_height = panel.settings_section.winfo_height()
        add_files(panel, *tracks(tmp_path / "A", *(
            f"{n:02d} A Chapter With A Rather Long Name {n}.mp3" for n in range(1, 31))))
        for folder in ("B", "C"):
            panel.on_add()
            add_files(panel, *tracks(tmp_path / folder, "01 One.mp3", "02 Two.mp3"))
        panel.on_select(panel.workspace.books[0].book_id)
        panel.surface.set_shared_text("album_artist", "Shared Album Artist")
        panel.surface.set_shared_text("series", "A Very Long Series Name Indeed")
        panel.book_vars["title"].set("An Extremely Long Book Title That Goes On And On")
        panel.book_vars["output_filename"].set("an-extremely-long-output-filename")
        panel.var_auto_number.set(True)
        panel.on_auto_number()
        panel._choose_artwork = lambda: str(png(tmp_path / "art" / "cover.png",
                                                size=(600, 400)))
        panel.choose_book_artwork()
        panel.choose_shared_artwork()
        _show_custom(panel, tk_root, str(tmp_path / "a" / "deep" / "custom" / "folder"))
        assert panel.book_artwork.has_preview and panel.shared_artwork.has_preview
        assert panel.density == "tight"
        problems = _problems(app, panel, custom=True)
        assert not problems, "busy at the minimum:\n  " + "\n  ".join(problems)
        _assert_floors(panel, "busy at the minimum")
        assert panel.settings_section.winfo_height() == settings_height
    finally:
        _tear_down_shell(tk_root, existing)


def test_the_output_hint_shows_where_the_run_lands(fake_settings, tk_root):
    """At the minimum the hint shows the path's *tail* (the run folder), not
    its drive letter; the full path is kept for everything else."""
    if _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = _panel(app)
        full = panel.var_outdir.get()
        panel.var_outdir.set(str(Path(full) / "a" / "very" / "deep" / "folder" /
                                 "that" / "cannot" / "fit" / "M4B-Maker-Outputs"))
        _settled(tk_root)
        shown = panel.output_hint_text
        assert shown.startswith("…") and shown.endswith("M4B-Maker-Outputs"), shown
        assert panel.var_outdir.get().endswith("M4B-Maker-Outputs")
        font = tkfont.Font(font=ttk.Style(panel).lookup(
            str(panel.output_label.cget("style")), "font"))
        assert font.measure(shown) <= panel.output_label.winfo_width()
        tk_root.geometry("1920x1009")
        _settled(tk_root)
        assert panel.output_hint_text == panel.var_outdir.get()
    finally:
        _tear_down_shell(tk_root, existing)


def test_a_live_toggle_in_the_real_shell_keeps_the_layout_and_state(
        fake_settings, tk_root, tmp_path):
    """The shell's own Light/Dark toggle, end to end: Dark after one press,
    Light after the second, and neither moves a pixel or a value."""
    if _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = _panel(app)
        add_files(panel, *tracks(tmp_path, "a.mp3", "b.mp3"))
        panel.surface.set_shared_text("artist", "Kept")
        panel.book_vars["title"].set("Kept Title")
        panel.select_tracks(1)
        _show_custom(panel, tk_root, str(tmp_path / "Chosen"))
        geometry = lambda: tuple(  # noqa: E731
            (w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height())
            for w in (*panel.sections, panel.btn_build, panel.track_list,
                      panel.customrow, panel.log.frame))
        before = (geometry(), panel.density, panel.selected_occurrences(),
                  panel.workspace, panel.custom_destination())
        style = ttk.Style(panel)
        app._toggle_appearance()
        _settled(tk_root)
        dark = appearance.DARK_COLORS
        assert panel.track_list.cget("background") == dark["field"]
        assert style.lookup(str(panel.run_section.cget("style")), "background") \
            == dark["surface"]
        assert style.lookup(str(panel.surface.shared_frame.cget("style")),
                            "background") == dark["shared_bg"]
        app._toggle_appearance()
        _settled(tk_root)
        assert panel.track_list.cget("background") == appearance.LIGHT_COLORS["field"]
        assert (geometry(), panel.density, panel.selected_occurrences(),
                panel.workspace, panel.custom_destination()) == before
        assert panel.surface.shared_value("artist") == "Kept"
        assert panel.book_title_text() == "Kept Title"
    finally:
        _tear_down_shell(tk_root, existing)
