"""Cover Image's Family-A layout — v0.6.6 Phase 2 remediation (maintainer override).

History. v0.6.1 Plan 4 Phase 13A fixed an unreachable ``Resize Covers`` by gridding
the panel's six stacked bands and moving the resize options onto a scrolling
canvas. The v0.6.6 Phase 2 repeat manual gate failed that presentation: a core
control group inside a scrolling region is exactly what the frozen UI contract's
no-core-scroll rule forbids, and the panel did not look like TTS, the
maintainer's visual-control reference. By explicit maintainer sequencing override
(Decisions.md, 2026-09-27) the Family-A conversion planned for Phase 5 was done
now. The two tests that pinned the old six-row stack and the scrolling options
canvas are therefore retired here, and the tests below pin what replaced them.

What is proved, in the terms of the maintainer's verification list:

* the visible hierarchy is ``1. Sources`` / ``2. Resize Options`` /
  ``3. Output & Run`` with ``Activity`` on the right;
* no whole-panel scrollbar and no scrolling core-control container exist, and
  Resize Options is not inside any scrollable container;
* inside the **real launcher shell** at the Windows 920x600 minimum, the default
  size and a large window, every required Cover control is on screen within the
  content area, and Activity stays beside the workflow;
* the source browser and the Activity log are the flexible regions -- they grow
  with the window while the buttons do not;
* all three browser views remain available and functional.

Every real-shell case builds a completely fresh launcher beneath the module's one
Tk root (a second interpreter is what made the original gate flaky) and tears it
down again, leaving the root withdrawn.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

import pytest

from shared import ui_theme

from test_cover_browser import (  # noqa: F401 - fixtures are used by name
    make_panel,
    tk_root,
)
import tk_gate  # noqa: E402,F401

from mp3_tools import cover_resizer as cr  # noqa: E402

#: The launcher's default size, its Windows minimum, and a large window.
MINIMUM = "{}x{}".format(*ui_theme.MIN_SIZE)
SHELL_GEOMETRIES = [MINIMUM, ui_theme.DEFAULT_GEOMETRY, "1920x1009"]

SECTION_TITLES = ("1. Sources", "2. Resize Options", "3. Output & Run", "Activity")


@pytest.fixture
def fake_settings(monkeypatch):
    """In-memory ``last_tool`` storage, so no test touches settings.json."""
    import launcher

    store: dict = {}

    class _Settings:
        @staticmethod
        def get(key, default=None):
            return store.get(key, default)

        @staticmethod
        def set(key, value, **_kwargs):
            store[key] = value

    monkeypatch.setattr(launcher, "app_settings", _Settings)
    return store


def _settled(root, times: int = 8) -> None:
    for _ in range(times):
        root.update_idletasks()
        root.update()


def _fresh_shell(root, geometry):
    """A launcher on the module's own root, at *geometry*, showing Cover.

    Deiconified because the assertions are about what is genuinely **on
    screen**: ``winfo_ismapped`` on a withdrawn toplevel tells you nothing.
    """
    import launcher

    root.deiconify()
    app = launcher.LauncherApp(root)
    root.geometry(geometry)
    _settled(root)
    app.select_tool("cover")
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


def _required_controls(panel) -> dict[str, tk.Misc]:
    """Every control a person needs to use the tool, by a readable name."""
    controls = {
        "view " + view: button for view, button in panel.browser.view_buttons.items()}
    controls.update({
        "import " + key: button for key, button in panel.importer.list.buttons.items()})
    controls.update({
        "type " + key: button
        for key, button in panel.importer.options.type_buttons.items()})
    options = panel.importer.options
    controls.update({
        "Include subfolders": options.check_subfolders,
        "Include hidden folders": options.check_hidden,
        "Allow duplicate files": options.check_duplicates,
        "Cancel Import": panel.importer.status.button_cancel,
        "Target size": panel.entry_size,
        "Keep full image": panel.chk_letterbox,
        "Save beside source images": panel.chk_source_side,
        "Create numbered copies": panel.rb_numbered,
        "Replace original files": panel.rb_replace,
        "Output": panel.entry_outdir,
        "Resize Covers": panel.btn_convert,
        "Clear Log": panel.btn_clear_log,
        "progress": panel.progress.bar,
    })
    controls.update({
        action.name: button for action, button in panel.jobs.controls.buttons.items()})
    return controls


def _inside(widget, host) -> bool:
    top, left = widget.winfo_rooty(), widget.winfo_rootx()
    bottom, right = top + widget.winfo_height(), left + widget.winfo_width()
    host_top, host_left = host.winfo_rooty(), host.winfo_rootx()
    return (host_top <= top and bottom <= host_top + host.winfo_height()
            and host_left <= left and right <= host_left + host.winfo_width())


def _is_windows_shell(root) -> bool:
    return root.tk.call("tk", "windowingsystem") == "win32"


@pytest.mark.parametrize("geometry", SHELL_GEOMETRIES)
def test_every_required_control_is_on_screen_in_the_real_shell(
        fake_settings, tk_root, geometry):
    """No core scrolling: at every supported size each control is simply there.

    920x600 is the Windows minimum; aqua's own minimum is larger, so that one
    case is Windows-only, exactly like the TTS layout suite.
    """
    if geometry == MINIMUM and not _is_windows_shell(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = app.containers["cover"].winfo_children()[0]
        host = app.content
        missing = [name for name, widget in _required_controls(panel).items()
                   if not (widget.winfo_ismapped() and _inside(widget, host)
                           and widget.winfo_height() >= 10)]
        assert not missing, f"not on screen at {geometry}: {missing}"
        assert str(panel.btn_convert.cget("command")).endswith("start_resize")
        # The browser and the log keep their floors even at the minimum, and
        # above it the browser keeps at least one full thumbnail row.
        assert panel.browser.frame.winfo_height() >= panel._needs["browser_floor"] - 1
        if geometry != MINIMUM:
            assert panel.browser.frame.winfo_height() >= cr.BROWSER_COMFORT_HEIGHT - 2
        assert panel.log.frame.winfo_height() >= panel._needs["log_floor"] - 1
    finally:
        _tear_down_shell(tk_root, existing)


@pytest.mark.parametrize("geometry", SHELL_GEOMETRIES)
def test_activity_is_on_the_right_in_the_real_shell(fake_settings, tk_root, geometry):
    """Family A: the workflow on the left, Activity the column to its right."""
    if geometry == MINIMUM and not _is_windows_shell(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = app.containers["cover"].winfo_children()[0]
        assert panel.layout_mode != "stacked", geometry
        workflow_right = panel.workflow.winfo_rootx() + panel.workflow.winfo_width()
        assert panel.activity.winfo_rootx() >= workflow_right, geometry
        # Activity spans the panel's height beside the workflow.
        assert abs(panel.activity.winfo_rooty() - panel.workflow.winfo_rooty()) <= 1
    finally:
        _tear_down_shell(tk_root, existing)


def test_the_browser_and_the_log_absorb_a_larger_window(fake_settings, tk_root):
    """Flexible regions grow; buttons and settings stay compact."""
    if not _is_windows_shell(tk_root):
        pytest.skip("920x600 is below the aqua minimum")
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["cover"].winfo_children()[0]
        small = (panel.browser.frame.winfo_height(), panel.log.frame.winfo_height(),
                 panel.log.frame.winfo_width(), panel.btn_convert.winfo_height())
        tk_root.geometry("1920x1009")
        _settled(tk_root)
        large = (panel.browser.frame.winfo_height(), panel.log.frame.winfo_height(),
                 panel.log.frame.winfo_width(), panel.btn_convert.winfo_height())
        assert large[0] > small[0], "the source browser did not grow"
        assert large[1] > small[1] and large[2] > small[2], "the log did not grow"
        assert large[3] == small[3], "the primary button stretched"
    finally:
        _tear_down_shell(tk_root, existing)


def test_the_hierarchy_is_the_numbered_workflow_then_activity(make_panel):
    panel = make_panel()
    titles = (panel.sources_section.cget("text"), panel.options_section.cget("text"),
              panel.run_section.cget("text"), panel.activity.cget("text"))
    assert titles == SECTION_TITLES
    for section in (panel.sources_section, panel.options_section, panel.run_section):
        assert section.master is panel.workflow
    assert panel.activity.master is panel
    # Each section owns its controls.
    assert str(panel.browser.frame).startswith(str(panel.sources_section))
    assert str(panel.importer.frame).startswith(str(panel.sources_section))
    for name in ("entry_size", "chk_letterbox", "chk_source_side", "rb_numbered",
                 "rb_replace"):
        assert str(getattr(panel, name)).startswith(str(panel.options_section)), name
    for name in ("entry_outdir", "btn_convert", "job_area"):
        assert str(getattr(panel, name)).startswith(str(panel.run_section)), name
    assert str(panel.log.frame).startswith(str(panel.activity))
    assert str(panel.btn_clear_log).startswith(str(panel.activity))


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def test_only_the_browser_views_and_the_log_can_scroll(make_panel):
    """No whole-panel scrollbar and no scrolling core-control container."""
    panel = make_panel()
    allowed = (str(panel.browser.body), str(panel.log.frame))
    for widget in _descendants(panel):
        if isinstance(widget, ttk.Scrollbar):
            owner = str(widget)
            hidden_importer_list = widget is panel.importer.list.scrollbar
            assert owner.startswith(allowed) or hidden_importer_list, owner
        if isinstance(widget, tk.Canvas):
            assert widget is panel.browser.canvas, f"unexpected canvas {widget}"
    assert not hasattr(panel, "options_canvas")


def test_resize_options_live_in_no_scrollable_container(make_panel):
    panel = make_panel()
    for name in ("entry_size", "chk_letterbox", "chk_source_side", "rb_numbered",
                 "rb_replace"):
        widget = getattr(panel, name)
        ancestor = widget.master
        while ancestor is not None and ancestor is not panel:
            assert not isinstance(ancestor, tk.Canvas), f"{name} is on a canvas"
            assert not isinstance(ancestor, tk.Text), f"{name} is in a text widget"
            ancestor = ancestor.master


def test_the_arrangement_keeps_activity_right_and_the_browser_usable(make_panel):
    """The arrangement is a pure function of size, measured from the widgets.

    At the real launcher's 920x600 (721x457) and 1024x720 (825x577) content
    hosts, no arrangement with Sources on top leaves the browser a usable
    height, so Sources takes its own column beside Resize Options over Output
    & Run -- still left of Activity. A large window uses the TTS-like vertical
    workflow. Whenever Sources is on top, the browser keeps a full thumbnail
    row.
    """
    panel = make_panel()
    if panel.tk.call("tk", "windowingsystem") != "win32":
        pytest.skip("the measured breakpoints are Windows metrics")
    assert panel._choose_layout(721, 457) == "columns"
    assert panel._choose_layout(825, 577) == "columns"
    assert panel._choose_layout(1721, 866) == "wide"
    for width in range(700, 2601, 50):
        for height in range(450, 1401, 50):
            mode = panel._choose_layout(width, height)
            if mode in ("wide", "split"):
                assert panel._browser_height(mode, height) >= cr.BROWSER_COMFORT_HEIGHT
    for width in range(700, 2001, 50):
        for height in range(450, 1101, 50):
            assert panel._choose_layout(width, height) in (
                "wide", "split", "columns", "stacked")


@pytest.mark.parametrize("view", cr.VIEW_IDS)
def test_every_browser_view_is_selectable_and_shows_the_list(make_panel, tmp_path, view):
    from test_cover_browser import loaded

    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    panel.browser.view_buttons[view].invoke()
    assert panel.browser.view == view
    assert panel.browser.order == tuple(ids)
    panel.browser.click(ids[1])
    assert panel.manager.selection == (ids[1],)
    # The importer's actions follow the browser's selection.
    assert panel.importer.list.button_states()["remove"] is True


def test_the_browser_views_carry_the_ordered_list_keyboard_contract(
        make_panel, tk_root, tmp_path):
    """The browser is the list, so §4's shortcuts live on its views: Delete
    removes the selection and Alt+Down moves it, through the same guarded
    importer actions the buttons call. Real key events need a shown, focused
    window, so the shared root is shown for this test and withdrawn again."""
    from test_cover_browser import loaded

    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    for view in (panel.browser.details, panel.browser.simple, panel.browser.canvas):
        bound = view.bind()
        for sequence in ("<Key-Delete>", "<Key-BackSpace>", "<Alt-Key-Up>",
                         "<Alt-Key-Down>", "<Control-Key-a>"):
            assert sequence in bound, (view, sequence)
    tk_root.deiconify()
    try:
        panel.pack(fill="both", expand=True)
        _settled(tk_root)
        details = panel.browser.details
        details.focus_force()
        _settled(tk_root)
        panel.browser.click(ids[0])
        details.event_generate("<Alt-Down>")
        _settled(tk_root, 2)
        assert panel.manager.snapshot().occurrence_ids[1] == ids[0]
        details.event_generate("<Delete>")
        _settled(tk_root, 2)
        assert ids[0] not in panel.manager.snapshot().occurrence_ids
        assert panel.manager.count == 2
    finally:
        tk_root.withdraw()
