"""v0.6.1 Plan 4 Phase 13A — the Cover panel's primary action must stay visible.

The Mac gate found ``Resize Covers`` unreachable: a genuine HEIC imported and
previewed, and the button that resizes it was nowhere on screen. Measured on the
real Aqua shell, the panel asks for ~1219 px of height while the launcher's
content host is 604 px at the supported 1024x720 default and 484 px at the
920x600 minimum. Stacked with ``pack``, requested height is claimed in packing
order, so the options, the action, the run area and the log were never mapped at
all — ``winfo_ismapped()`` returned 0 for every one of them.

The fix is the panel's outer geometry only: ``grid`` with explicit row weights,
the queue and the action on weight-0 rows that always get their requested
height, and the options form on the same scrollable canvas the TTS panel and the
metadata editor already use. Nothing about importing, the browser views, the
source-side safeguards, the job controls or the output logic changes.

These tests fail on the pre-fix code because the button is unmapped there.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from shared import ui_theme

from test_cover_browser import (  # noqa: F401 - fixtures are used by name
    make_panel,
    tk_root,
)
import tk_gate  # noqa: E402

#: The two window sizes the launcher actually supports: the size it opens at,
#: and the smallest the user can drag it to.
SUPPORTED_GEOMETRIES = [
    ui_theme.DEFAULT_GEOMETRY,
    "{}x{}".format(*ui_theme.MIN_SIZE),
]


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


def _settled(root, times: int = 6) -> None:
    for _ in range(times):
        root.update_idletasks()
        root.update()


def _fresh_shell(root, geometry):
    """A launcher built on the module's own root, at *geometry*, ready to read.

    The window is deiconified because the assertions below are about what is
    genuinely **on screen**: ``winfo_ismapped`` on a withdrawn toplevel tells
    you nothing.
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
    """Remove everything the shell built, leaving the root as it was found.

    *existing* is the set of children the root had beforehand, so this can
    never destroy a widget belonging to something else. The window manager
    protocol handler is dropped too: it belongs to an app that is going away,
    and the root outlives it.
    """
    for child in list(root.winfo_children()):
        if child not in existing:
            child.destroy()
    try:
        root.protocol("WM_DELETE_WINDOW", "")
    except tk.TclError:  # pragma: no cover - no handler was installed
        pass
    _settled(root)
    root.withdraw()


@pytest.mark.parametrize("geometry", SUPPORTED_GEOMETRIES)
def test_resize_covers_is_visible_in_the_real_shell(fake_settings, tk_root,
                                                   geometry):
    """The whole point of the tool, inside the visible content area, every shell.

    **Runs on the module's own root rather than opening another one.** Opening
    a second Tcl interpreter inside a pytest process is what made this gate
    flaky: create a root, destroy it, create another, and the second fails --
    measured 5/5 at Phase 10 HEAD, deterministically. Every other live-Tk
    module in this suite already owns exactly one module-scoped root; this
    test was the only place that did not.

    Each parameter case still gets a **completely fresh launcher**, built and
    torn down beneath that one root, so nothing from the 1024x720 case can
    make the 920x600 case pass. Not one assertion below is relaxed.
    """
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)

        panel = app.containers["cover"].winfo_children()[0]
        button = panel.btn_convert

        assert button.winfo_exists(), "the primary action must be constructed"
        assert button.winfo_ismapped(), (
            f"'Resize Covers' is not on screen at {geometry}")
        assert button.cget("text") == "Resize Covers"
        assert str(button.cget("command")).endswith("start_resize"), (
            "the visible button must still be the one that starts a resize")

        host_top = app.content.winfo_rooty()
        host_bottom = host_top + app.content.winfo_height()
        top = button.winfo_rooty()
        bottom = top + button.winfo_height()
        assert host_top <= top and bottom <= host_bottom, (
            f"the action spans {top}..{bottom}, outside the visible content "
            f"area {host_top}..{host_bottom} at {geometry}")
        assert button.winfo_height() >= 20, "clipped to a sliver is not visible"
    finally:
        _tear_down_shell(tk_root, existing)


def test_the_action_row_is_pinned_and_the_flexible_rows_absorb_the_shortfall(
        make_panel):
    """A weight-0 row keeps its requested height however short the window is."""
    panel = make_panel()
    weights = {row: int(panel.grid_rowconfigure(row)["weight"]) for row in range(6)}
    assert weights[0] == 0, "the imported queue is fixed chrome"
    assert weights[3] == 0, "the primary action is fixed chrome"
    assert all(weights[row] > 0 for row in (1, 2, 4, 5)), (
        "the browser, options, run area and log are the flexible rows")
    # A floor on a row *above* the action would push it back off a short
    # window, which is the defect this test exists for.
    for row in (0, 1, 2, 3):
        assert int(panel.grid_rowconfigure(row)["minsize"]) == 0


def test_every_resize_option_survives_the_move_onto_the_scrolling_canvas(
        tk_root, make_panel):
    """The options form is unchanged — only its container scrolls now."""
    tk_root.deiconify()
    panel = make_panel()
    panel.pack(fill="both", expand=True)
    _settled(tk_root)
    try:
        for name in ("entry_size", "chk_letterbox", "chk_source_side",
                     "rb_numbered", "rb_replace", "entry_outdir"):
            widget = getattr(panel, name)
            assert widget.winfo_exists(), f"{name} was lost in the move"
            assert str(widget).startswith(str(panel)), f"{name} left the panel"
        # The scroll region covers the whole options form, so nothing in it is
        # stranded when the region on screen is shorter than the form itself.
        canvas = panel.options_canvas
        region = [int(float(value))
                  for value in str(canvas.cget("scrollregion")).split()]
        form_height = panel.chk_source_side.master.winfo_reqheight()
        assert len(region) == 4, "the options canvas must declare a scroll region"
        assert region[3] >= form_height, (
            f"scroll region {region[3]} px cannot reach a {form_height} px form")
    finally:
        tk_root.withdraw()
