"""MP3 Tool compact visual standardization — v0.6.6 Phase 6.

The MP3 Tool was the dense multi-Book panel still drawn in the retired oversized
``ACT.*`` interior, and inside the real launcher's 920x600 content area it did
not fit: the track list, Chapter Titles box and log collapsed to a pixel and
Remove Book and Retry Failed were cut off. Phase 6 rebuilds its *presentation*
as the dense Family-B hierarchy on the approved Cover/TTS/Converter control
language, without touching one MP3 workflow, plan, engine or output rule:

  1. Import & Books   2. Book Settings   3. Tracks & Run   Activity (below)

What is proved here:

* the numbered hierarchy, with Activity the universal Summary | Detailed view
  (and Clear Log) at the bottom;
* Shared is visibly distinct from Current Book -- the restrained tinted surface
  with the stronger border and heading -- in Light and in Dark, and Current Book
  is the ordinary section surface;
* a Dark bundle reaches the whole interior, classic Tk widgets included;
* a live Light/Dark toggle is presentation-only -- Books, current Book,
  selection, Shared and Book values, chapter titles, track order, log, layout
  and a *running* job all survive;
* the track list's §4 shortcuts obey the run lock and never reach an Entry or
  the Chapter Titles box;
* inside the **real launcher shell** every required control is on screen at
  full size, at 920x600, 1024x720, 1280x900 and 1920x1009, with only the
  track list, Chapter Titles and log giving up height.
"""

from __future__ import annotations

import threading
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

from mp3_tools import mp3_tool

from test_import_coordination import RealThreads
from test_mp3_tool_ui import (  # noqa: F401 - fixtures are collected by name
    add_files,
    import_folder,
    make_panel,
    tagged,
    tk_root,
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
    """How colorful, independent of how dark: 0 is grey, 1 a pure hue.

    HSV saturation over-reads near-black colors (Dark's muted blue-grey
    Shared surface scores 0.45 there), so restraint is judged by chroma."""
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return max(channels) - min(channels)


# --------------------------------------------------------------------------- #
# A. The Family-B hierarchy on the shared compact control language
# --------------------------------------------------------------------------- #


def test_the_four_sections_are_the_family_b_hierarchy(make_panel):
    panel = make_panel()
    assert [str(s.cget("text")) for s in panel.sections] == [
        "1. Import & Books", "2. Book Settings", "3. Tracks & Run", "Activity"]
    assert tuple(mp3_tool.SECTION_TITLES) == tuple(str(s.cget("text"))
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
                                 panel.book_artwork.frame, panel.check_auto_number,
                                 panel.entry_start_number, panel.status_label),
        panel.run_section: (panel.track_list, panel.chapter_text, panel.btn_add_files,
                            panel.btn_move_up, panel.btn_move_down,
                            panel.btn_remove_tracks, panel.btn_write_id3,
                            panel.btn_combine, panel.jobs.frame),
        panel.activity: (panel.log.frame, panel.btn_clear_log, panel.activity_note),
    }
    for section, widgets in homes.items():
        for widget in widgets:
            assert _within(widget, section), (str(widget), section.cget("text"))
    # The one persistent log is the adapter's view, so history survives runs.
    assert panel.jobs.views is panel.log
    assert [panel.log.frame.tab(i, "text") for i in range(2)] == ["Summary", "Detailed"]


def test_the_run_actions_and_activity_are_the_shared_compact_presentation(
        make_panel, tk_root):
    dark = _bundle(tk_root, appearance.DARK)
    panel = make_panel(appearance_bundle=dark)
    styles = dark["styles"]
    assert str(panel.log.frame.cget("style")) == styles["notebook"]
    assert str(panel.btn_clear_log.cget("style")) == styles["button"]
    assert str(panel.activity_note.cget("style")) == styles["secondary_label"]
    # Both operations: the compact button with the restrained accent outline.
    for button in (panel.btn_write_id3, panel.btn_combine):
        assert str(button.cget("style")) == styles["button"]
        assert str(button.cget("default")) == "active"
    cancel = [b for b in panel.jobs.controls.buttons.values()
              if str(b.cget("text")) == "Cancel"]
    assert cancel and str(cancel[0].cget("style")) == styles["danger_button"]
    assert str(panel.btn_clear_imports.cget("style")) == styles["danger_button"]
    assert str(panel.status.indicator.bar.cget("style")) == styles["progressbar"]
    assert str(panel.status.indicator.frame.cget("style")) == styles["card"]
    assert str(panel.status.label_status.cget("style")) == styles["secondary_label"]
    for widget, key in ((panel.check_auto_number, "checkbutton"),
                        (panel.entry_start_number, "entry"),
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
    assert style.lookup(f"{book_style}.Label", "foreground") == colors["text"]

    # Distinct, and restrained: a cool low-saturation tint, not an alert.
    assert colors["shared_bg"] != colors["surface"]
    assert colors["shared_border"] != colors["border"]
    assert _chroma(colors["shared_bg"]) < 0.15
    assert _chroma(colors["warning"]) > 2 * _chroma(colors["shared_bg"])
    assert colors["shared_bg"] not in (colors["warning"], colors["danger"])
    # The words say it too, and the Shared group's own controls sit on the tint.
    assert "applies to every Book and overrides its own value" in str(shared.cget("text"))
    assert str(book.cget("text")) == "Current Book"
    assert style.lookup(str(panel.shared_artwork.frame.cget("style")), "background") \
        == colors["shared_bg"]
    for name in panel.surface.fields:
        label = panel.surface._row(name).label
        assert style.lookup(str(label.cget("style")), "background") == colors["shared_bg"]


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


# --------------------------------------------------------------------------- #
# B. A live toggle is presentation-only
# --------------------------------------------------------------------------- #


def test_a_live_toggle_preserves_every_piece_of_workspace_state(make_panel, tk_root, tmp_path):
    light = _bundle(tk_root, appearance.LIGHT)
    panel = make_panel(appearance_bundle=light)
    library = tmp_path / "Library"
    for folder in ("A", "B", "C"):
        tracks(library / folder, "01 One.mp3", "02 Two.mp3", "03 Three.mp3")
    import_folder(panel, library)
    assert panel.workspace.count == 3
    panel.navigator.choose(panel.workspace.books[1].book_id)
    panel.surface.set_shared_text("artist", "Shared Author")
    panel.surface.set_book_text("album", "Book Two")
    panel.type_chapter_titles("Opening\nMiddle\nEnd")
    panel.type_start_number("7")
    panel.select_tracks(0, 1)
    panel.move_down()
    panel.log.append("kept across the toggle")
    panel.log.append_detail("a detailed line")
    before = (panel.workspace, panel.selected_occurrences(), panel.chapter_titles_text(),
              panel.var_start_number.get(), panel.var_auto_number.get(),
              panel.navigator.heading_text, panel.density, dict(panel.book_numbers))
    widgets = (panel.track_list, panel.chapter_text, panel.surface, panel.navigator,
               panel.jobs, panel.log.summary_text, panel.btn_write_id3)

    panel._on_appearance_changed(_bundle(tk_root, appearance.DARK))
    assert panel.track_list.cget("background") == appearance.DARK_COLORS["field"]
    assert panel.chapter_text.cget("background") == appearance.DARK_COLORS["field"]
    panel._on_appearance_changed(_bundle(tk_root, appearance.LIGHT))

    after = (panel.workspace, panel.selected_occurrences(), panel.chapter_titles_text(),
             panel.var_start_number.get(), panel.var_auto_number.get(),
             panel.navigator.heading_text, panel.density, dict(panel.book_numbers))
    assert after == before
    assert after[0] is before[0], "the workspace snapshot itself is untouched"
    assert panel.surface.shared_value("artist") == "Shared Author"
    assert panel.surface.book_value("album") == "Book Two"
    assert "kept across the toggle" in panel.log.summary
    assert "a detailed line" in panel.log.details
    assert (panel.track_list, panel.chapter_text, panel.surface, panel.navigator,
            panel.jobs, panel.log.summary_text, panel.btn_write_id3) == widgets
    assert panel.track_list.cget("background") == appearance.LIGHT_COLORS["field"]


@pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(),
                    reason="ffmpeg/ffprobe not available in this environment")
def test_toggling_mid_run_leaves_the_running_job_alone(make_panel, tk_root, tmp_path,
                                                       monkeypatch):
    """A theme switch while a real worker is inside a Book touches no
    controller, adapter, plan or progress: the run settles as it would have."""
    from test_mp3_orchestration import three_books, wait_for

    panel = make_panel(thread_factory=RealThreads(),
                       appearance_bundle=_bundle(tk_root, appearance.LIGHT))
    three_books(panel, tmp_path, monkeypatch, broken=None)
    started, release = threading.Event(), threading.Event()
    real_book = mp3_tool.mp3_processing.write_id3_book

    def gated(book, *, checkpoint=None, on_event=None, **kwargs):
        started.set()
        release.wait(10.0)
        return real_book(book, checkpoint=checkpoint, on_event=on_event, **kwargs)

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_book", gated)
    try:
        assert panel.write_id3_tags()
        controller, jobs, plan = panel.job_controller, panel.jobs, panel.last_plan
        assert started.wait(10.0)
        panel._pump.tick()
        assert panel.is_running and controller.state is JobState.RUNNING
        assert str(panel.btn_write_id3.cget("state")) == "disabled"

        panel._on_appearance_changed(_bundle(tk_root, appearance.DARK))
        panel._pump.tick()
        assert panel.job_controller is controller and panel.jobs is jobs
        assert panel.last_plan is plan and panel.is_running
        assert str(panel.btn_write_id3.cget("state")) == "disabled"
        assert panel.navigator.locked is True
    finally:
        release.set()
    wait_for(panel, lambda: not panel.is_running)
    assert controller.state is JobState.SUCCEEDED
    assert panel.last_result.state is JobState.SUCCEEDED
    assert str(panel.btn_write_id3.cget("state")) == "normal"
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
    """The shared session root, briefly shown so a real key event arrives."""
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
        names = lambda: [e.name for e in panel.workspace.current.files.files]  # noqa: E731
        # A multi-selection moves as one block, keeping its internal order.
        panel.select_tracks(0, 1)
        _key(shown, panel.track_list, "<Alt-Down>")
        assert names() == ["c.mp3", "a.mp3", "b.mp3", "d.mp3"]
        assert sorted(panel.track_list.curselection()) == [1, 2]

        # While a run owns the track controls, the keys are as locked as the
        # buttons: nothing moves and nothing is removed.
        panel.lock_group.apply(JobState.RUNNING)
        _key(shown, panel.track_list, "<Alt-Up>")
        _key(shown, panel.track_list, "<Delete>")
        _key(shown, panel.track_list, "<BackSpace>")
        assert names() == ["c.mp3", "a.mp3", "b.mp3", "d.mp3"]

        panel.lock_group.apply(JobState.IDLE)
        _key(shown, panel.track_list, "<Delete>")
        assert names() == ["c.mp3", "d.mp3"]
        _key(shown, panel.track_list, "<Control-a>")
        assert sorted(panel.track_list.curselection()) == [0, 1]
    finally:
        panel.pack_forget()


def test_text_editing_keys_are_never_hijacked(make_panel, shown, tmp_path):
    """Ctrl+A, Delete and BackSpace in a metadata Entry or the Chapter Titles
    box edit that text; the track list's selection and order never move."""
    panel = make_panel()
    panel.pack(fill="both", expand=True)
    try:
        add_files(panel, *tracks(tmp_path, "a.mp3", "b.mp3", "c.mp3"))
        panel.select_tracks(1)
        order = [e.occurrence_id for e in panel.workspace.current.files.files]
        entry = panel.surface._row("album").book_entry
        for widget in (entry, panel.chapter_text):
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
        for _ in range(200):
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
    app.select_tool("mp3_tool")
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
    return app.containers["mp3_tool"].winfo_children()[0]


def _required_controls(panel) -> dict:
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
        "Auto-number": panel.check_auto_number,
        "Start #": panel.entry_start_number,
        "Status": panel.status_label,
        "Track list": panel.track_list,
        "Chapter Titles": panel.chapter_text,
        "Add Files": panel.btn_add_files,
        "Move Up": panel.btn_move_up,
        "Move Down": panel.btn_move_down,
        "Remove Selected": panel.btn_remove_tracks,
        "Write ID3 Tags": panel.btn_write_id3,
        "Combine": panel.btn_combine,
        "progress": panel.status.indicator.bar,
        "Clear Log": panel.btn_clear_log,
        "Summary | Detailed": panel.log.frame,
    }
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
#: shown whole in the selector beside it.
YIELDING = ("Output folder", "Book position")


def _problems(app, panel, *, yielding=("Output folder",)) -> list[str]:
    host = app.content
    top, left = host.winfo_rooty(), host.winfo_rootx()
    bottom, right = top + host.winfo_height(), left + host.winfo_width()
    found = []
    for name, widget in _required_controls(panel).items():
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
    track_floor = (mp3_tool.TIGHT_TRACK_FLOOR_ROWS if tight
                   else mp3_tool.TRACK_FLOOR_ROWS)
    log_floor = mp3_tool.TIGHT_LOG_FLOOR_LINES if tight else mp3_tool.LOG_FLOOR_LINES
    rows = panel.track_list.winfo_height() / _linespace(panel.track_list)
    lines = panel.log.summary_text.winfo_height() / _linespace(panel.log.summary_text)
    assert rows >= track_floor - 0.1, (where, rows)
    assert panel.chapter_text.winfo_height() >= panel.track_list.winfo_height(), where
    assert lines >= log_floor - 0.1, (where, lines)


@pytest.mark.parametrize("geometry", sorted(SHELL_GEOMETRIES))
def test_every_required_control_is_on_screen_in_the_real_shell(
        fake_settings, tk_root, geometry):
    """No core scrolling: at every supported size each control is simply
    there at its full requested size, the four sections stack in order with
    Activity last, and the flexible regions keep their floors. 920x600 is
    below the aqua minimum, so that case is Windows-only."""
    if geometry == MINIMUM and _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = _panel(app)
        problems = _problems(app, panel)
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
    finally:
        _tear_down_shell(tk_root, existing)


def _png(path: Path) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (600, 400), (10, 60, 120)).save(path)
    return path


def test_a_busy_workspace_still_fits_the_real_minimum_without_layout_jumps(
        fake_settings, tk_root, tmp_path):
    """The minimum with a real workload: three Books, many tracks, a long Book
    name, Shared values, chosen artwork and a mixed-source marker. Nothing
    leaves the screen or is squeezed, and Book Settings does not grow when
    artwork or the marker appears."""
    if _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = _panel(app)
        settings_height = panel.settings_section.winfo_height()
        first = tuple(tagged(path, artist=f"Reader {n}", album="An Extremely Long "
                             "Album Name That Goes On And On")
                      for n, path in enumerate(tracks(tmp_path / "A", *(
                          f"{n:02d} Chapter {n}.mp3" for n in range(1, 31)))))
        add_files(panel, *first)
        for folder in ("B", "C"):
            panel.on_add()
            add_files(panel, *tracks(tmp_path / folder, "01 One.mp3", "02 Two.mp3"))
        panel.on_select(panel.workspace.books[0].book_id)
        panel.surface.set_shared_text("album_artist", "Shared Album Artist")
        panel._choose_artwork = lambda: str(_png(tmp_path / "art" / "cover.png"))
        panel.choose_book_artwork()
        _settled(tk_root)
        assert panel.book_artwork.has_preview
        # The same marker, in the tight density's short wording.
        assert panel.density == "tight"
        assert panel.mixed_text("artist") == mp3_tool.MIXED_MARK_SHORT
        assert panel.mixed_text("album") == ""
        problems = _problems(app, panel, yielding=YIELDING)
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
                                 "that" / "cannot" / "fit" / "MP3-Tool-Outputs"))
        _settled(tk_root)
        shown = panel.output_hint_text
        assert shown.startswith("…") and shown.endswith("MP3-Tool-Outputs"), shown
        assert panel.var_outdir.get().endswith("MP3-Tool-Outputs")
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
        panel.select_tracks(1)
        _settled(tk_root)
        geometry = lambda: tuple(  # noqa: E731
            (w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height())
            for w in (*panel.sections, panel.btn_write_id3, panel.track_list,
                      panel.log.frame))
        before = (geometry(), panel.density, panel.selected_occurrences(),
                  panel.workspace)
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
                panel.workspace) == before
        assert panel.surface.shared_value("artist") == "Kept"
    finally:
        _tear_down_shell(tk_root, existing)
