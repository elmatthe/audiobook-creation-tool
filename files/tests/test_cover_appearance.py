"""Cover Image Resizer's Light/Dark coherence — v0.6.6 Phase 2 remediation.

The maintainer's manual gate on the original Phase 2 checkpoint (0ab862d) failed:
toggling to Dark recolored only the two shared ``job_ui`` components (the imported-
file list and the Activity log) this panel had been wired to, leaving every other
widget — the browser's three views, the resize-options form, the output/action
row, the panel's own run log — on native/classic rendering. In practice that meant
large light/white regions inside an otherwise-Dark tool, and a hardcoded
``background="white"`` thumbnail canvas plus two hardcoded hex colors on the
selection-highlight tiles made it worse. The maintainer's 2026-09-27 ruling
(recorded in ``Decisions.md``) is that TTS's compact control language is the
reference for every tool interior, and that no app-owned tool interior may mix
unstyled native regions into a Dark shell.

This file is the coherence half of the fix's regression coverage —
``test_cover_browser.py`` carries the structural half (every ``style=`` keyword
resolves through ``style_name``, no color literal on a classic widget). What this
file proves instead is that a *real* panel, built against an *explicit* Dark
bundle (never the real stored setting — ``appearance_bundle`` is a constructor
seam exactly like every other keyword ``CoverResizerUI`` already accepts), shows
Dark colors literally everywhere a person would look: the panel's own background,
the browser's LabelFrame/Radiobuttons/Treeviews/thumbnail canvas, the resize
options form's every control, the primary action button, and the panel's raw run
log. It also proves the live-refresh path: toggling the *same* panel from Light to
Dark recolors it in place, with no widget rebuilt and no state lost.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")
tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import appearance  # noqa: E402
from shared import job_ui  # noqa: E402

from mp3_tools import cover_resizer as cr  # noqa: E402

from test_cover_jobs import InlineRunner, output_base  # noqa: E402,F401
from test_import_coordination import RecordingThreads  # noqa: E402
import tk_gate  # noqa: E402


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


def no_previews(requests, publish):
    return None


def _bundle(tk_root, value: str) -> dict:
    style = ttk.Style(tk_root)
    return appearance.build_bundle(style, value, platform="win32", root=tk_root)


@pytest.fixture
def dark_bundle(tk_root):
    return _bundle(tk_root, appearance.DARK)


@pytest.fixture
def make_panel(tk_root, output_base):
    made: list[cr.CoverResizerUI] = []

    def build(**kwargs):
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        kwargs.setdefault("preview_runner", no_previews)
        kwargs.setdefault("job_runner", InlineRunner())
        panel = cr.CoverResizerUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        try:
            panel.destroy()
        except tk.TclError:
            pass


def test_a_dark_bundle_colors_the_panels_own_background(make_panel, dark_bundle):
    panel = make_panel(appearance_bundle=dark_bundle)
    colors = dark_bundle["colors"]
    style = ttk.Style(panel)
    assert style.lookup(str(panel.cget("style")), "background") == colors["window"]


def test_a_dark_bundle_colors_every_resize_option_control(make_panel, dark_bundle):
    """Every control the maintainer's gate found left native/light: the
    Spinbox, both Checkbuttons, both Radiobuttons, the Entry and both Labels."""
    panel = make_panel(appearance_bundle=dark_bundle)
    colors = dark_bundle["colors"]
    style = ttk.Style(panel)

    def bg(widget) -> str:
        return style.lookup(str(widget.cget("style")), "background")

    def fg(widget) -> str:
        return style.lookup(str(widget.cget("style")), "foreground")

    assert bg(panel.entry_size) == colors["field"]
    assert bg(panel.chk_letterbox) == colors["surface"]
    assert bg(panel.chk_source_side) == colors["surface"]
    assert bg(panel.rb_numbered) == colors["surface"]
    assert bg(panel.rb_replace) == colors["surface"]
    assert bg(panel.entry_outdir) == colors["field"]
    # Resize Covers is the panel's default button, drawn the way TTS's Start
    # is: an ordinary compact button with the restrained accent outline ttk
    # gives a default="active" button -- not a filled blue block.
    assert bg(panel.btn_convert) == colors["elevated"]
    assert fg(panel.btn_convert) == colors["text"]
    assert str(panel.btn_convert.cget("default")) == "active"
    assert ("alternate", colors["accent"]) in [
        (tuple(state)[0] if len(tuple(state)) == 1 else " ".join(state), value)
        for *state, value in style.map(str(panel.btn_convert.cget("style")),
                                       "bordercolor")]


def test_a_dark_bundle_colors_the_browsers_three_views(make_panel, dark_bundle):
    panel = make_panel(appearance_bundle=dark_bundle)
    colors = dark_bundle["colors"]
    style = ttk.Style(panel)
    browser = panel.browser

    assert style.lookup(str(browser.frame.cget("style")), "background") == colors["surface"]
    for button in browser.view_buttons.values():
        assert style.lookup(str(button.cget("style")), "background") == colors["surface"]
    for tree in (browser.details, browser.simple):
        assert style.lookup(str(tree.cget("style")), "background") == colors["field"]
    # The thumbnail canvas is classic Tk, not ttk -- the exact widget the
    # maintainer's gate found hardcoded to background="white".
    assert browser.canvas.cget("background") == colors["field"]


def test_a_dark_bundle_colors_the_activity_log(make_panel, dark_bundle):
    """Activity is the shared Summary | Detailed view; both panes follow Dark."""
    panel = make_panel(appearance_bundle=dark_bundle)
    colors = dark_bundle["colors"]
    for pane in (panel.log.summary_text, panel.log.details_text):
        assert pane.cget("background") == colors["field"]
        assert pane.cget("foreground") == colors["text"]
    style = ttk.Style(panel)
    assert style.lookup(str(panel.activity.cget("style")), "background") == colors["surface"]


def test_no_cover_owned_ttk_widget_is_left_on_a_generic_style(make_panel, dark_bundle):
    """Regression guard for partial theming: every ttk widget the panel owns,
    including the shared components it hosts, is on a ``Compact.*`` style --
    a generic (empty) style would render native/light inside a Dark tool."""
    panel = make_panel(appearance_bundle=dark_bundle)

    def walk(widget):
        for child in widget.winfo_children():
            yield child
            yield from walk(child)

    generic = []
    for widget in walk(panel):
        if not widget.winfo_class().startswith("T") and widget.winfo_class() != "Treeview":
            continue
        try:
            name = str(widget.cget("style"))
        except tk.TclError:
            continue
        if not name.startswith(appearance.STYLE_PREFIX + "."):
            generic.append(f"{widget.winfo_class()} {widget}")
    assert not generic, generic


def test_selected_tiles_paint_from_the_theme_not_a_literal(make_panel, dark_bundle, tmp_path):
    """The other half of the hardcoded-white defect: the selection rectangle
    was a fixed light-blue hex pair, wrong on every appearance, not only Dark."""
    from test_cover_jobs import make_image

    panel = make_panel(appearance_bundle=dark_bundle)
    image_path = make_image(tmp_path / "a.jpg")
    panel.importer._choose_files = lambda: (str(image_path),)
    panel.importer.add_files()
    panel._pump.tick()
    browser = panel.browser
    browser.set_view(cr.VIEW_THUMBNAILS)
    occurrence_id = browser.order[0]
    panel._manager.select((occurrence_id,))
    browser.refresh()

    items = browser.canvas.find_withtag(occurrence_id)
    rectangles = [item for item in items
                 if browser.canvas.type(item) == "rectangle"]
    assert rectangles, "no selection rectangle was painted for the selected tile"
    fill = browser.canvas.itemcget(rectangles[0], "fill")
    outline = browser.canvas.itemcget(rectangles[0], "outline")
    assert fill == dark_bundle["colors"]["selection"]
    assert outline == dark_bundle["colors"]["accent"]
    assert fill != "#cde3f7" and outline != "#3b7dd8"


def test_toggling_appearance_recolors_the_whole_panel_in_place(make_panel, tk_root):
    """The live-refresh path: the same widgets, the same state, new colors.

    Built and asserted in strict sequence, on purpose: ``Compact.*`` style names
    are shared process-wide (the same "state-preserving refresh" mechanic Phase 1
    relies on), so a bundle built *after* another silently reconfigures the same
    names — exactly what a real toggle does, and exactly why the light assertion
    below must run before the dark bundle is ever built, not after.
    """
    style = ttk.Style(tk_root)
    light = appearance.build_bundle(style, appearance.LIGHT, platform="win32", root=tk_root)
    panel = make_panel(appearance_bundle=light)
    panel.var_size.set(999)
    assert style.lookup(str(panel.entry_size.cget("style")), "background") == \
        light["colors"]["field"]

    dark = appearance.build_bundle(style, appearance.DARK, platform="win32", root=tk_root)
    panel._on_appearance_changed(dark)
    assert style.lookup(str(panel.entry_size.cget("style")), "background") == \
        dark["colors"]["field"]
    assert panel.log.summary_text.cget("background") == dark["colors"]["field"]
    assert panel.browser.canvas.cget("background") == dark["colors"]["field"]
    # Nothing about the panel's own state moved.
    assert panel.var_size.get() == 999


def test_a_live_toggle_preserves_every_piece_of_panel_state(make_panel, tk_root, tmp_path):
    """Theme switching is presentation-only: imports, selection, browser view,
    resize and output settings, and log history all survive, and no widget is
    rebuilt."""
    from test_cover_jobs import make_image

    style = ttk.Style(tk_root)
    light = appearance.build_bundle(style, appearance.LIGHT, platform="win32", root=tk_root)
    panel = make_panel(appearance_bundle=light)
    paths = [make_image(tmp_path / f"{name}.jpg") for name in ("a", "b", "c")]
    panel.importer._choose_files = lambda: tuple(str(p) for p in paths)
    panel.importer.add_files()
    panel._pump.tick()
    order = panel.browser.order
    panel.browser.set_view(cr.VIEW_LIST)
    panel.browser.click(order[1])
    panel.var_size.set(1400)
    panel.var_letterbox.set(False)
    panel.var_source_side.set(True)
    panel._on_source_side_change()
    panel.var_source_action.set(cr.ACTION_REPLACE)
    panel.log.append("kept across the toggle")
    widgets = (panel.browser.canvas, panel.entry_size, panel.log.summary_text,
               panel.importer.list.listbox, panel.btn_convert)

    dark = appearance.build_bundle(style, appearance.DARK, platform="win32", root=tk_root)
    panel._on_appearance_changed(dark)

    assert panel.browser.order == order
    assert panel.manager.selection == (order[1],)
    assert panel.browser.view == cr.VIEW_LIST
    assert panel.var_size.get() == 1400
    assert panel.var_letterbox.get() is False
    assert panel.var_source_side.get() is True
    assert panel.var_source_action.get() == cr.ACTION_REPLACE
    assert "kept across the toggle" in panel.log.summary
    assert all(widget.winfo_exists() for widget in widgets)
    assert (panel.browser.canvas, panel.entry_size, panel.log.summary_text,
            panel.importer.list.listbox, panel.btn_convert) == widgets


def test_toggling_mid_run_leaves_the_running_resize_alone(make_panel, tk_root, output_base,
                                                          tmp_path, monkeypatch):
    """v0.6.6 Phase 9: Cover was the one tool without a mid-run toggle test.
    A theme switch while a real worker holds the first image touches no
    controller, run or lock: the run settles as it would have, every output
    lands, and the sources are byte-identical."""
    import hashlib

    from shared.job_control import JobState
    from test_cover_jobs import (Gate, ThreadRunner, drain, import_files, make_image,
                                 run_dir_of, start, written_under)

    runner = ThreadRunner()
    panel = make_panel(appearance_bundle=_bundle(tk_root, appearance.LIGHT),
                       job_runner=runner)
    sources = [make_image(tmp_path / "art" / f"{name}.jpg") for name in ("a", "b")]
    hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    import_files(panel, *sources)
    gate = Gate()
    monkeypatch.setattr(cr, "resize_for_audiobook", gate)
    try:
        start(panel)
        gate.wait_for_entry(1)
        controller = panel.job_controller
        assert controller.state is JobState.RUNNING
        assert panel.btn_convert.instate(["disabled"])

        dark = _bundle(tk_root, appearance.DARK)
        panel._on_appearance_changed(dark)
        drain(panel)
        assert panel.job_controller is controller
        assert controller.state is JobState.RUNNING
        assert panel.btn_convert.instate(["disabled"])
        assert panel.log.summary_text.cget("background") == dark["colors"]["field"]
    finally:
        gate.let_through(2)
        runner.join()
    drain(panel)
    assert controller.state is JobState.SUCCEEDED
    assert panel.run_result.succeeded_count == 2
    assert written_under(run_dir_of(output_base)) == ["a.jpg", "b.jpg"]
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources} == hashes
    _bundle(tk_root, appearance.LIGHT)


def test_clear_log_clears_the_visible_activity_only(make_panel):
    panel = make_panel()
    panel.log_write("a transcript line\n")
    panel.log.append("a summary line")
    assert panel.log.details and panel.log.summary
    panel.btn_clear_log.invoke()
    assert panel.log.summary == () and panel.log.details == ()


def test_the_worker_transcript_goes_to_detailed_not_summary(make_panel):
    panel = make_panel()
    panel.log_write("\nprocessing a.jpg\n\n")
    assert "processing a.jpg" in panel.log.details
    assert "processing a.jpg" not in panel.log.summary
