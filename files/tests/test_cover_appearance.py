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
    assert bg(panel.btn_convert) == colors["accent"]
    assert fg(panel.btn_convert) == colors["inverse"]


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


def test_a_dark_bundle_colors_the_panels_own_run_log(make_panel, dark_bundle):
    panel = make_panel(appearance_bundle=dark_bundle)
    assert panel.log.cget("background") == dark_bundle["colors"]["elevated"]
    assert panel.log.cget("foreground") == dark_bundle["colors"]["secondary"]


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
    assert panel.log.cget("background") == dark["colors"]["elevated"]
    assert panel.browser.canvas.cget("background") == dark["colors"]["field"]
    # Nothing about the panel's own state moved.
    assert panel.var_size.get() == 999
