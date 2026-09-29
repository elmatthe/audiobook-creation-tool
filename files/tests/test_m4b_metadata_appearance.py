"""M4B Metadata Editor compact visual standardization — v0.6.6 Phase 8.

The M4B Metadata Editor was the last panel still drawn in the retired oversized
``ACT.*`` interior. Inside the real launcher's 920x600 content area (721x457) it
asked for 1334x665: the Chapter Titles box and the log were never mapped, and
Open Output Folder, Resume / Cancel / Retry Failed and Clear Log lay outside the
content area. Phase 8 rebuilds its *presentation* as the dense Family-B
hierarchy on the approved Cover/TTS/Converter/MP3 Tool/Maker control language,
without touching one Editor workflow, plan, batch or processing rule:

  1. Import & Books   2. Metadata   3. Chapters & Save   Activity

What is proved here:

* the numbered hierarchy, with Activity the universal Summary | Detailed view
  (and Clear Log) at the bottom, and Save Tags the one accent-outlined run
  action beside the two destructive ones;
* Shared is visibly distinct from Current Book in Light and in Dark, and a Dark
  bundle reaches the whole interior, classic Tk widgets included;
* a live Light/Dark toggle is presentation-only -- Books, current page, Shared
  and Book edits, chapter titles, the run options, the log, the layout and a
  *running* Save survive;
* text-editing keys are never hijacked, and Tab follows the workflow;
* inside the **real launcher shell** every required control is on screen at
  full size at 920x600, 1024x720, 1280x900 and 1920x1009 -- with a busy
  workspace too -- with only the Chapter Titles box and the log giving up
  height, and the preserve-by-default statement always on screen.
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
from shared import appearance, paths, ui_theme  # noqa: F401
from shared.job_control import JobState

from mp3_tools import m4b_artwork_ui, m4b_metadata_editor as editor
from mp3_tools import m4b_metadata_workflow as wf

from test_m4b_metadata_editor_ui import (  # noqa: F401 - fixtures are collected by name
    container,
    import_folder,
    library,
    make_panel,
    output_base,
    parked_threads,
    source_hashes,
    tk_root,
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


def _png(path: Path, size=(600, 400)) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (40, 90, 160)).save(path)
    return path


def _populate(panel) -> None:
    """Three readable Books through the panel's own model, touching no disk
    (the developer fixture's canned import)."""
    import manual_windows_ui_prototype as fixture

    fixture._populate(panel)


# --------------------------------------------------------------------------- #
# A. The Family-B hierarchy on the shared compact control language
# --------------------------------------------------------------------------- #


def test_the_four_sections_are_the_family_b_hierarchy(make_panel):
    panel = make_panel()
    assert [str(s.cget("text")) for s in panel.sections] == [
        "1. Import & Books", "2. Metadata", "3. Chapters & Save", "Activity"]
    assert tuple(editor.SECTION_TITLES) == tuple(str(s.cget("text"))
                                                 for s in panel.sections)
    # One column, top to bottom: Activity is last and below, never beside.
    for row, section in enumerate(panel.sections):
        info = section.grid_info()
        assert (int(info["row"]), int(info["column"])) == (row, 0)
    homes = {
        panel.import_section: (panel.btn_import_folder, panel.btn_add_files,
                               panel.btn_clear_imports, panel.import_status.frame,
                               panel.output_label, panel.navigator.frame),
        panel.metadata_section: (panel.surface.frame, panel.shared_artwork.frame,
                                 panel.book_artwork.frame, panel.source_label,
                                 panel.readback_label, panel.facts_label,
                                 panel.status_label),
        panel.chapters_section: (panel.chapter_text, panel.chapters_caption,
                                 panel.check_auto_number, panel.entry_start_part,
                                 panel.hint_label, panel.btn_save, panel.btn_clear_tags,
                                 panel.btn_remove_numbering, panel.btn_open_out,
                                 panel.jobs.frame),
        panel.activity: (panel.log.frame, panel.btn_clear_log, panel.activity_note),
    }
    for section, widgets in homes.items():
        for widget in widgets:
            assert _within(widget, section), (str(widget), section.cget("text"))
    # The one persistent log is the adapter's view, so history survives runs.
    assert panel.jobs.views is panel.log
    assert [panel.log.frame.tab(i, "text") for i in range(2)] == ["Summary", "Detailed"]


def test_the_actions_and_activity_are_the_shared_compact_presentation(make_panel, tk_root):
    dark = _bundle(tk_root, appearance.DARK)
    panel = make_panel(appearance_bundle=dark)
    styles = dark["styles"]
    assert str(panel.log.frame.cget("style")) == styles["notebook"]
    assert str(panel.btn_clear_log.cget("style")) == styles["button"]
    assert str(panel.activity_note.cget("style")) == styles["secondary_label"]
    # Save Tags: the compact button with the restrained accent outline; the
    # two destructive actions in the shared destructive treatment.
    assert str(panel.btn_save.cget("style")) == styles["button"]
    assert str(panel.btn_save.cget("default")) == "active"
    assert str(panel.btn_clear_tags.cget("style")) == styles["danger_button"]
    assert str(panel.btn_remove_numbering.cget("style")) == styles["danger_button"]
    assert str(panel.btn_open_out.cget("style")) == styles["button"]
    cancel = [b for b in panel.jobs.controls.buttons.values()
              if str(b.cget("text")) == "Cancel"]
    assert cancel and str(cancel[0].cget("style")) == styles["danger_button"]
    assert str(panel.btn_clear_imports.cget("style")) == styles["danger_button"]
    assert str(panel.status.indicator.bar.cget("style")) == styles["progressbar"]
    assert str(panel.status.indicator.frame.cget("style")) == styles["card"]
    assert str(panel.status.label_status.cget("style")) == styles["secondary_label"]
    for widget, key in ((panel.check_auto_number, "checkbutton"),
                        (panel.entry_start_part, "entry"),
                        (panel.surface._row("title").book_entry, "entry"),
                        (panel.navigator.selector, "combobox"),
                        (panel.chapters_caption, "label"),
                        (panel.status_label, "label"),
                        (panel.hint_label, "secondary_label")):
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
    # One Shared caption across the three dense tools; Current Book states
    # preserve-by-default.
    assert editor.SHARED_TITLE == str(shared.cget("text"))
    assert "applies to every Book and overrides its own value" in editor.SHARED_TITLE
    assert "blank or unchanged = keep the source's own value" in str(book.cget("text"))
    # The Shared group's own controls sit on the tint; the read-back and the
    # Book's artwork on the ordinary surface.
    assert style.lookup(str(panel.shared_artwork.frame.cget("style")), "background") \
        == colors["shared_bg"]
    for name in panel.surface.fields:
        label = panel.surface._row(name).label
        assert style.lookup(str(label.cget("style")), "background") == colors["shared_bg"]
    assert style.lookup(str(panel.readback.cget("style")), "background") == colors["surface"]
    assert style.lookup(str(panel.book_artwork.frame.cget("style")), "background") \
        == colors["surface"]


def test_a_dark_bundle_reaches_the_whole_interior(make_panel, tk_root):
    """No light island: the panel, its four sections, the classic Tk Chapter
    Titles box and log panes, and the Book selector's drop-down."""
    dark = _bundle(tk_root, appearance.DARK)
    panel = make_panel(appearance_bundle=dark)
    colors, style = dark["colors"], ttk.Style(panel)
    assert style.lookup(str(panel.cget("style")), "background") == colors["window"]
    for section in panel.sections:
        assert style.lookup(str(section.cget("style")), "background") == colors["surface"]
    for widget in (panel.chapter_text, panel.log.summary_text, panel.log.details_text):
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
    """The previews are no taller than the control's caption and buttons (no
    layout jump), as on the MP3 Tool and the Maker; the shared control's own
    default is untouched."""
    panel = make_panel()
    for control in (panel.shared_artwork, panel.book_artwork):
        assert control.preview_max == m4b_artwork_ui.COMPACT_PREVIEW_MAX == (40, 40)
    panel._choose_artwork = lambda: str(_png(tmp_path / "cover.png"))
    panel.choose_shared_artwork()
    assert panel.shared_artwork.has_preview
    image = panel.shared_artwork.preview.cget("image")
    assert int(panel.tk.call("image", "height", image)) <= 40
    assert int(panel.tk.call("image", "width", image)) <= 40
    assert m4b_artwork_ui.PREVIEW_MAX == (56, 56)


# --------------------------------------------------------------------------- #
# B. A live toggle is presentation-only
# --------------------------------------------------------------------------- #


def test_a_live_toggle_preserves_every_piece_of_workspace_state(make_panel, tk_root, tmp_path):
    panel = make_panel(appearance_bundle=_bundle(tk_root, appearance.LIGHT))
    _populate(panel)
    assert panel.workspace.count == 3
    panel.navigator.choose(panel.workspace.books[1].book_id)
    panel.surface.set_shared_text("genre", "Shared Genre")
    panel.set_book_field("album", "Book Two Album")
    panel.type_chapter_titles("Opening\n\nEnd")
    panel.var_auto_number.set(True)
    panel.var_start_part.set("4")
    panel._choose_artwork = lambda: str(_png(tmp_path / "art.png"))
    panel.choose_book_artwork()
    panel.log.append("kept across the toggle")
    panel.log.append_detail("a detailed line")

    def state():
        return (panel.workspace, panel.store, panel.chapter_titles_text(),
                panel.var_auto_number.get(), panel.var_start_part.get(),
                panel.navigator.heading_text, panel.density, dict(panel.book_numbers),
                panel.book_field_enabled("genre"), panel.book_value("album"),
                panel.source_text(), panel.series_readback_text(), panel.facts_text(),
                panel.book_status_text(), panel.output_hint_text,
                panel.preserve_note_text)

    before = state()
    widgets = (panel.chapter_text, panel.surface, panel.navigator, panel.jobs,
               panel.log.summary_text, panel.btn_save, panel.hint_label)

    panel._on_appearance_changed(_bundle(tk_root, appearance.DARK))
    assert panel.chapter_text.cget("background") == appearance.DARK_COLORS["field"]
    assert panel.log.summary_text.cget("background") == appearance.DARK_COLORS["field"]
    panel._on_appearance_changed(_bundle(tk_root, appearance.LIGHT))

    after = state()
    assert after == before
    assert after[0] is before[0], "the workspace snapshot itself is untouched"
    assert before[8] is False, "a populated Shared value still disables the Book's"
    assert panel.surface.shared_value("genre") == "Shared Genre"
    assert "kept across the toggle" in panel.log.summary
    assert "a detailed line" in panel.log.details
    assert (panel.chapter_text, panel.surface, panel.navigator, panel.jobs,
            panel.log.summary_text, panel.btn_save, panel.hint_label) == widgets
    assert panel.chapter_text.cget("background") == appearance.LIGHT_COLORS["field"]


def test_toggling_mid_run_leaves_the_running_save_alone(make_panel, tk_root, container,
                                                       tmp_path, output_base):
    """A theme switch while Save Tags is under way touches no controller,
    adapter, plan, lock or progress: the run settles as it would have, the
    copies carry the edit and the originals are untouched."""
    panel = make_panel(appearance_bundle=_bundle(tk_root, appearance.LIGHT))
    import_folder(panel, library(container, tmp_path / "Library"))
    originals = source_hashes(panel)
    panel.surface.set_shared_text("genre", "Toggled")
    panel._thread_factory = parked_threads()
    assert panel.save() is True
    controller, jobs, plan, run = panel.job_controller, panel.jobs, panel.last_plan, panel.run
    assert panel.is_running and controller.state is JobState.RUNNING
    assert "disabled" in panel.btn_save.state()

    panel._on_appearance_changed(_bundle(tk_root, appearance.DARK))
    panel._pump.tick()
    assert panel.job_controller is controller and panel.jobs is jobs
    assert panel.last_plan is plan and panel.run is run and panel.is_running
    assert "disabled" in panel.btn_save.state()
    assert panel.navigator.locked is True
    assert panel.book_field_enabled("title") is False

    panel._thread_factory.bodies[0]()
    panel._pump.tick()
    assert controller.state is JobState.SUCCEEDED
    assert panel.last_result.state is JobState.SUCCEEDED
    assert all(book.published.is_file() for book in plan.books)
    assert source_hashes(panel) == originals, "the originals are never written"
    assert "disabled" not in panel.btn_save.state()
    _bundle(tk_root, appearance.LIGHT)


def test_a_closed_panel_stops_listening_for_appearance_changes(make_panel):
    panel = make_panel()
    assert panel._on_appearance_changed in appearance._listeners
    panel.close()
    assert panel._on_appearance_changed not in appearance._listeners


# --------------------------------------------------------------------------- #
# C. Keyboard: text keys stay the text's, Tab follows the workflow
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


def test_text_editing_keys_are_never_hijacked(make_panel, shown):
    """Ctrl+A, Delete, BackSpace and Alt+Up/Down in a metadata Entry, Start
    Part or the Chapter Titles box act on that text only: no Book is removed,
    moved or switched."""
    panel = make_panel()
    panel.pack(fill="both", expand=True)
    try:
        _populate(panel)
        books = tuple(book.book_id for book in panel.workspace.books)
        current = panel.workspace.current.book_id
        for widget in (panel.surface._row("album").book_entry,
                       panel.surface._row("title").shared_entry,
                       panel.entry_start_part, panel.chapter_text):
            for sequence in ("<Control-a>", "<Delete>", "<BackSpace>", "<Alt-Down>",
                             "<Alt-Up>"):
                _key(shown, widget, sequence)
        assert tuple(book.book_id for book in panel.workspace.books) == books
        assert panel.workspace.current.book_id == current
    finally:
        panel.pack_forget()


def test_tab_order_follows_the_visible_workflow(make_panel, shown):
    """§5: Section 1 → Section 2 → Section 3 → Activity, where practical."""
    panel = make_panel()
    panel.pack(fill="both", expand=True)
    try:
        _populate(panel)
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
    app.select_tool("m4b_metadata")
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
    return app.containers["m4b_metadata"].winfo_children()[0]


def _required_controls(panel) -> dict:
    nav = panel.navigator
    controls = {
        "Import Folder": panel.btn_import_folder,
        "Add Files": panel.btn_add_files,
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
        "Source": panel.source_label,
        "Read-back": panel.readback_label,
        "Facts": panel.facts_label,
        "Status": panel.status_label,
        "Chapter Titles caption": panel.chapters_caption,
        "Chapter Titles": panel.chapter_text,
        "Auto-number": panel.check_auto_number,
        "Start Part label": panel.label_start_part,
        "Start Part": panel.entry_start_part,
        "Save Tags": panel.btn_save,
        "Clear All Tags": panel.btn_clear_tags,
        "Remove Series Numbering": panel.btn_remove_numbering,
        "Open Output Folder": panel.btn_open_out,
        "progress": panel.status.indicator.bar,
        "Clear Log": panel.btn_clear_log,
        "Summary | Detailed": panel.log.frame,
    }
    if panel.hint_label.winfo_manager():
        controls["Preserve note"] = panel.hint_label
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
#: shows the path's tail; a long Book name in the navigator's heading is shown
#: whole in the selector beside it; and the read-back lines are the source's
#: own facts, which a long path or series atom may overrun at the minimum.
YIELDING = ("Output folder", "Book position", "Source", "Read-back")


def _problems(app, panel, *, yielding=YIELDING) -> list[str]:
    host = app.content
    top, left = host.winfo_rooty(), host.winfo_rootx()
    bottom, right = top + host.winfo_height(), left + host.winfo_width()
    found = []
    required = _required_controls(panel)
    # A reflow must never stack one control on another (clipped or covered
    # regions pass an on-screen test; they do not pass this one).
    boxes = {name: (w.winfo_rootx(), w.winfo_rooty(),
                    w.winfo_rootx() + w.winfo_width(), w.winfo_rooty() + w.winfo_height())
             for name, w in required.items() if w.winfo_ismapped()}
    names = list(boxes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if _within(required[a], required[b]) or _within(required[b], required[a]):
                continue
            ba, bb = boxes[a], boxes[b]
            if not (ba[2] <= bb[0] or bb[2] <= ba[0] or ba[3] <= bb[1] or bb[3] <= ba[1]):
                found.append(f"{a} overlaps {b}")
    for name, widget in required.items():
        if not widget.winfo_ismapped():
            found.append(f"{name}: not on screen")
            continue
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        if not (left <= x and top <= y and x + widget.winfo_width() <= right
                and y + widget.winfo_height() <= bottom):
            found.append(f"{name}: outside the content area")
        if widget in (panel.chapter_text, panel.log.frame):
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
    # The Book caption, carrying preserve-by-default, is never clipped.
    book = panel.surface.book_frame
    caption = tkfont.Font(font=ttk.Style(book).lookup(
        f"{book.cget('style')}.Label", "font") or "TkDefaultFont")
    if caption.measure(str(book.cget("text"))) > book.winfo_width():
        found.append("Current Book caption: clipped")
    return found


def _assert_floors(panel, where) -> None:
    tight = panel.density == "tight"
    chapter_floor = (editor.TIGHT_CHAPTER_FLOOR_ROWS if tight
                     else editor.CHAPTER_FLOOR_ROWS)
    log_floor = editor.TIGHT_LOG_FLOOR_LINES if tight else editor.LOG_FLOOR_LINES
    rows = panel.chapter_text.winfo_height() / _linespace(panel.chapter_text)
    lines = panel.log.summary_text.winfo_height() / _linespace(panel.log.summary_text)
    assert rows >= chapter_floor - 0.1, (where, rows)
    assert lines >= log_floor - 0.1, (where, lines)


@pytest.mark.parametrize("geometry", sorted(SHELL_GEOMETRIES))
def test_every_required_control_is_on_screen_in_the_real_shell(
        fake_settings, tk_root, geometry):
    """No core scrolling: at every supported size each control is simply
    there at its full requested size, the four sections stack in order with
    Activity last, the flexible regions keep their floors, and the
    preserve-by-default statement is on screen. 920x600 is below the aqua
    minimum, so that case is Windows-only."""
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
        assert panel.activity.winfo_rooty() > panel.chapters_section.winfo_rooty()
        assert not widgets_of(panel, tk.Canvas), "no page canvas"
        # The wording and placement follow the density; the variables never do.
        tight = panel.density == "tight"
        assert panel.check_auto_number.cget("text") == (
            editor.AUTO_NUMBER_LABEL_SHORT if tight else editor.AUTO_NUMBER_LABEL)
        assert panel.label_start_part.cget("text") == (
            editor.START_PART_LABEL_SHORT if tight else editor.START_PART_LABEL)
        note = panel.preserve_note_text.lower()
        assert "never modified" in note and "blank or unchanged" in note
    finally:
        _tear_down_shell(tk_root, existing)


def test_the_tight_reflow_keeps_every_statement_and_control(fake_settings, tk_root):
    """At the minimum the series numbering joins the Chapter Titles caption's
    line and the preserve note's statement joins the Current Book caption;
    with room both return to their own lines. The same widgets and variables
    throughout."""
    if _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = _panel(app)
        panel.var_auto_number.set(True)
        panel.var_start_part.set("3")
        options = panel.run_options
        assert panel.density == "tight"
        info = options.grid_info()
        assert (int(info["row"]), int(info["column"])) == (0, 1)
        caption = panel.chapters_caption
        assert options.winfo_rooty() < caption.winfo_rooty() + caption.winfo_height()
        assert options.winfo_rootx() > caption.winfo_rootx(), "beside the caption"
        assert not panel.hint_label.winfo_manager()
        book = str(panel.surface.book_frame.cget("text"))
        assert book == editor.BOOK_TITLE_TIGHT
        assert "originals are never modified" in book
        assert "blank or unchanged" in str(caption.cget("text"))

        tk_root.geometry("1920x1009")
        _settled(tk_root)
        assert panel.density == "regular"
        info = options.grid_info()
        assert (int(info["row"]), int(info["column"])) == (3, 0)
        assert panel.hint_label.winfo_ismapped()
        assert str(panel.hint_label.cget("text")) == editor.PRESERVE_HINT
        assert str(panel.surface.book_frame.cget("text")) == editor.BOOK_TITLE
        assert str(caption.cget("text")) == editor.CHAPTERS_CAPTION
        assert panel.var_auto_number.get() is True and panel.var_start_part.get() == "3"
        assert not _problems(app, panel)

        tk_root.geometry(MINIMUM)
        _settled(tk_root)
        assert panel.density == "tight" and not _problems(app, panel)
    finally:
        _tear_down_shell(tk_root, existing)


def test_a_busy_workspace_still_fits_the_real_minimum_without_layout_jumps(
        fake_settings, tk_root, tmp_path):
    """The minimum with a real workload: three Books, long values, Shared
    values, chosen artwork on both sides, many chapter titles and series
    numbering on. Nothing leaves the screen or is squeezed, and Metadata does
    not grow when artwork appears."""
    if _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = _panel(app)
        metadata_height = panel.metadata_section.winfo_height()
        _populate(panel)
        panel.surface.set_shared_text("series", "A Very Long Series Name Indeed")
        panel.surface.set_shared_text("comment", "A long shared comment for every Book")
        panel.set_book_field("title", "An Extremely Long Book Title That Goes On And On")
        panel.type_chapter_titles("\n".join(f"Chapter {n} — a rather long title"
                                            for n in range(1, 41)))
        panel.var_auto_number.set(True)
        panel._choose_artwork = lambda: str(_png(tmp_path / "art" / "cover.png"))
        panel.choose_book_artwork()
        panel.choose_shared_artwork()
        _settled(tk_root)
        assert panel.book_artwork.has_preview and panel.shared_artwork.has_preview
        assert panel.density == "tight"
        problems = _problems(app, panel)
        assert not problems, "busy at the minimum:\n  " + "\n  ".join(problems)
        _assert_floors(panel, "busy at the minimum")
        assert panel.metadata_section.winfo_height() == metadata_height
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
                                 "that" / "cannot" / "fit" / "M4B-Metadata-Outputs"))
        _settled(tk_root)
        shown = panel.output_hint_text
        assert shown.startswith("…") and shown.endswith("M4B-Metadata-Outputs"), shown
        assert panel.var_outdir.get().endswith("M4B-Metadata-Outputs")
        font = tkfont.Font(font=ttk.Style(panel).lookup(
            str(panel.output_label.cget("style")), "font"))
        assert font.measure(shown) <= panel.output_label.winfo_width()
        tk_root.geometry("1920x1009")
        _settled(tk_root)
        assert panel.output_hint_text == panel.var_outdir.get()
    finally:
        _tear_down_shell(tk_root, existing)


def test_a_live_toggle_in_the_real_shell_keeps_the_layout_and_state(
        fake_settings, tk_root):
    """The shell's own Light/Dark toggle, end to end: Dark after one press,
    Light after the second, and neither moves a pixel or a value."""
    if _is_aqua(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = _panel(app)
        _populate(panel)
        panel.surface.set_shared_text("artist", "Kept")
        panel.set_book_field("title", "Kept Title")
        panel.type_chapter_titles("One\nTwo")
        _settled(tk_root)
        geometry = lambda: tuple(  # noqa: E731
            (w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height())
            for w in (*panel.sections, panel.btn_save, panel.chapter_text,
                      panel.run_options, panel.log.frame, panel.readback))
        before = (geometry(), panel.density, panel.workspace, panel.chapter_titles_text(),
                  panel.preserve_note_text)
        style = ttk.Style(panel)
        app._toggle_appearance()
        _settled(tk_root)
        dark = appearance.DARK_COLORS
        assert panel.chapter_text.cget("background") == dark["field"]
        assert style.lookup(str(panel.chapters_section.cget("style")), "background") \
            == dark["surface"]
        assert style.lookup(str(panel.surface.shared_frame.cget("style")),
                            "background") == dark["shared_bg"]
        app._toggle_appearance()
        _settled(tk_root)
        assert panel.chapter_text.cget("background") == appearance.LIGHT_COLORS["field"]
        assert (geometry(), panel.density, panel.workspace, panel.chapter_titles_text(),
                panel.preserve_note_text) == before
        assert panel.surface.shared_value("artist") == "Kept"
        assert panel.book_value("title") == "Kept Title"
    finally:
        _tear_down_shell(tk_root, existing)


# --------------------------------------------------------------------------- #
# E. Presentation only: no Editor rule moved into the panel
# --------------------------------------------------------------------------- #


def test_the_panel_still_composes_the_editor_layers_only():
    """Phase 8 re-homed widgets; it added no business rule. The workflow,
    plan, batch and processing layers are what the panel calls, and the only
    new imports are the shared appearance module and Tk's font measure."""
    import ast

    source = Path(editor.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    assert "shared.metadata" not in modules and "mutagen" not in modules
    assert "mp3_tools.m4b_metadata_processing" not in modules
    # The preserve-by-default rules stay the model's.
    assert wf.page_values.__module__ == "mp3_tools.m4b_metadata_workflow"
    for owned in ("edit_intent", "page_values", "chapter_edits"):
        assert f"def {owned}" not in source
