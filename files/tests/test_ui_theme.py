"""Headless-guarded smoke tests for shared/ui_theme.py.

``apply_theme`` must apply without raising and hand back the fonts/metrics
contract the launcher builds from. Both platform branches are exercised where
possible: the current platform's real branch, plus the classic win32/other
branch forced via a monkeypatched ``sys.platform`` (regression-critical: the
Windows look is a byte-identical reproduction of the pre-v0.5.0 launcher).
"""

from __future__ import annotations

import sys

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import ui_theme  # noqa: E402

REQUIRED_KEYS = {"mode", "family", "font_heading", "font_button",
                 "geometry", "min_size", "colors", "metrics"}


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # headless box with no display
        pytest.skip(f"Tk cannot open a display here: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def test_apply_theme_on_current_platform(tk_root):
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style)

    assert REQUIRED_KEYS <= set(theme)
    assert theme["geometry"] == "1024x720"
    assert theme["min_size"] == (920, 600)
    assert theme["font_heading"][1:] == (15, "bold")

    if sys.platform == "darwin":
        assert theme["mode"] == "aqua"
        assert style.theme_use() == "aqua"
        colors, metrics = theme["colors"], theme["metrics"]
        assert colors and metrics
        for name, value in colors.items():
            if name == "is_dark":
                assert isinstance(value, bool)
            else:
                assert isinstance(value, str) and value.startswith("#") \
                    and len(value) == 7, f"{name} not '#rrggbb': {value!r}"
        assert metrics["sidebar_width"] > 0 and metrics["row_height"] > 0
    else:
        assert theme["mode"] == "classic"
        assert theme["colors"] is None and theme["metrics"] is None


def test_classic_branch_win32(tk_root, monkeypatch):
    """The Windows branch must reproduce today's exact values on any host."""
    monkeypatch.setattr(sys, "platform", "win32")
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style)

    assert theme["mode"] == "classic"
    assert theme["family"] == "Segoe UI"
    assert theme["font_heading"] == ("Segoe UI", 15, "bold")
    assert theme["font_button"] == ("Segoe UI", 11)
    assert theme["colors"] is None and theme["metrics"] is None
    # On a real Windows box vista applies; elsewhere the try/TclError guard
    # must swallow the missing theme rather than raise (same as today).


def test_enable_mousewheel_wires_without_raising(tk_root):
    """enable_mousewheel binds hover Enter/Leave against a dummy scrollable.

    Real wheel motion cannot be simulated headless, so this asserts the
    wiring only: both crossing events bound on the hover region, and the
    Leave side bound at the Tcl level with the %d (crossing detail)
    substitution — tkinter's own bind() never delivers detail, and without
    it the NotifyInferior guard (ignore Leave into a child widget) cannot
    work.
    """
    wrap = ttk.Frame(tk_root)
    canvas = tk.Canvas(wrap)
    ui_theme.enable_mousewheel(canvas, hover_region=wrap)
    assert "<Enter>" in wrap.bind()
    assert "<Leave>" in wrap.bind()
    assert "%d" in wrap.bind("<Leave>")

    # hover_region defaults to the scroll target itself
    lb = tk.Listbox(tk_root)
    ui_theme.enable_mousewheel(lb)
    assert "<Enter>" in lb.bind() and "<Leave>" in lb.bind()

    wrap.destroy()
    lb.destroy()


def test_progress_indicator(tk_root):
    """ProgressIndicator constructs and runs its whole API without raising.

    Wheel-style visual checks aren't possible headless; this asserts the
    state contract: determinate updates set bar value/maximum and render a
    "done/total  pct%" label, indeterminate flips the bar mode, and reset
    returns to idle. (Thread-safety is a usage rule — every call below is
    main-thread, matching how the tools' queue drains invoke it.)
    """
    ind = ui_theme.ProgressIndicator(tk_root)
    assert isinstance(ind.frame, ttk.Frame)
    assert str(ind.bar.cget("mode")) == "determinate"
    assert ind.label.cget("text") == ""

    ind.update(3, 10)
    assert float(ind.bar.cget("maximum")) == 10
    assert float(ind.bar.cget("value")) == 3
    assert ind.label.cget("text") == "3/10  30%"

    # done clamps into [0, total]; total clamps to >= 1
    ind.update(15, 10)
    assert ind.label.cget("text") == "10/10  100%"
    ind.update(0, 0)
    assert ind.label.cget("text") == "0/1  0%"

    ind.set_indeterminate("Encoding…")
    assert str(ind.bar.cget("mode")) == "indeterminate"
    assert ind.label.cget("text") == "Encoding…"

    # a determinate update recovers from indeterminate mode
    ind.update(1, 4)
    assert str(ind.bar.cget("mode")) == "determinate"
    assert ind.label.cget("text") == "1/4  25%"

    ind.set_indeterminate()
    ind.reset()
    assert str(ind.bar.cget("mode")) == "determinate"
    assert float(ind.bar.cget("value")) == 0
    assert ind.label.cget("text") == ""

    # finish() only resets a still-animating indeterminate bar; a completed
    # determinate bar keeps its final value on screen.
    ind.update(4, 4)
    ind.finish()
    assert ind.label.cget("text") == "4/4  100%"
    ind.set_indeterminate("Encoding…")
    ind.finish()
    assert str(ind.bar.cget("mode")) == "determinate"
    assert ind.label.cget("text") == ""

    ind.frame.destroy()


def test_classic_branch_other_platform(tk_root, monkeypatch):
    """Non-win32/non-darwin keeps the historical clam + TkDefaultFont look."""
    monkeypatch.setattr(sys, "platform", "linux")
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style)

    assert theme["mode"] == "classic"
    assert theme["family"] == "TkDefaultFont"
    assert style.theme_use() == "clam"
