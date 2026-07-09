"""Platform-aware UI theming for the launcher shell.

``apply_theme(root, style)`` is the single place the launcher's theme, fonts,
colors and metrics come from, so the platform split stays auditable in one
file:

- **darwin** — the native ``aqua`` ttk theme (real macOS controls in every
  tool panel, automatic light/dark adaptation) plus a Finder-style palette
  resolved from macOS *semantic* system colors (window background, the user's
  accent color for selection, label/link colors). aqua cannot recolor
  native-drawn ttk buttons, so the launcher builds its sidebar chrome from
  classic tk widgets using the ``colors`` dict returned here.
- **win32 / everything else** — a byte-identical reproduction of the classic
  pre-v0.5.0 look: ``vista`` theme + "Segoe UI" on Windows, ``clam`` +
  TkDefaultFont elsewhere. Regression-critical: Windows rendering must not
  change.

Fonts on macOS use ``.AppleSystemUIFont`` (San Francisco). SF Pro Text/Display
are NOT installed as named font families on macOS (verified live on macOS 26 /
Tk 9.0.3), so the system-font alias is the sanctioned way to get SF, with
"Helvetica Neue" as the fallback for older Tk builds that don't resolve it.

Alpha-based semantic colors (separators, secondary labels) flatten to their
base color through ``winfo_rgb``, so those shades are computed blends instead.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

DEFAULT_GEOMETRY = "1024x720"
MIN_SIZE = (920, 600)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _classic_font_family() -> str:
    """The historical launcher font choice (Windows branch must not change)."""
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return "TkDefaultFont"


def _resolve_color(root: tk.Tk, name: str, fallback: str) -> str:
    """Resolve a (possibly semantic) Tk color name to '#rrggbb'."""
    try:
        r, g, b = root.winfo_rgb(name)
    except tk.TclError:
        return fallback
    return "#%02x%02x%02x" % (r // 257, g // 257, b // 257)


def _blend(hex_a: str, hex_b: str, t: float) -> str:
    """Mix two '#rrggbb' colors: 0.0 -> a, 1.0 -> b."""
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(
        round(ca + (cb - ca) * t) for ca, cb in zip(a, b)
    )


def _is_dark(hex_color: str) -> bool:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


def _mac_font_family(root: tk.Tk) -> str:
    """San Francisco via the system-font alias, else Helvetica Neue."""
    try:
        probe = tkfont.Font(root=root, family=".AppleSystemUIFont", size=13)
        if probe.actual("family") == ".AppleSystemUIFont":
            return ".AppleSystemUIFont"
    except tk.TclError:
        pass
    return "Helvetica Neue"


# ---------------------------------------------------------------------------
# branches
# ---------------------------------------------------------------------------

def _apply_classic(root: tk.Tk, style: ttk.Style) -> dict:
    """Reproduce today's exact look (vista/Segoe UI on Windows, clam elsewhere)."""
    try:
        style.theme_use("vista" if sys.platform == "win32" else "clam")
    except tk.TclError:
        pass
    family = _classic_font_family()
    return {
        "mode": "classic",
        "family": family,
        "font_heading": (family, 15, "bold"),
        "font_button": (family, 11),
        "geometry": DEFAULT_GEOMETRY,
        "min_size": MIN_SIZE,
        "colors": None,
        "metrics": None,
    }


def _apply_darwin(root: tk.Tk, style: ttk.Style) -> dict:
    """Native aqua controls + a Finder-style chrome palette (auto light/dark)."""
    try:
        style.theme_use("aqua")
    except tk.TclError:  # a Tk built without aqua — style like the classic look
        return _apply_classic(root, style)

    window = _resolve_color(root, "systemWindowBackgroundColor", "#ececec")
    text = _resolve_color(root, "systemLabelColor", "#000000")
    accent = _resolve_color(root, "systemSelectedContentBackgroundColor", "#0a5fd7")
    link = _resolve_color(root, "systemLinkColor", "#0068da")
    dark = _is_dark(window)

    # aqua draws ttk.Frame interiors (i.e. every tool panel) in the plain
    # window background and ignores background styling on native widgets, so
    # the content card must stay window-colored (hairline-outlined) and the
    # Finder tint goes on the sidebar instead — lighter than the content in
    # dark mode, darker in light mode, like Finder's source list.
    sidebar = (_blend(window, "#ffffff", 0.055) if dark
               else _blend(window, "#000000", 0.045))
    colors = {
        "window": window,
        "sidebar": sidebar,
        "card": window,
        "text": text,
        "secondary": _blend(text, window, 0.45),
        "accent": accent,
        "selection": accent,
        "selection_text": "#ffffff",
        "hover": _blend(sidebar, text, 0.08),
        "separator": _blend(window, text, 0.14),
        "link": link,
        "is_dark": dark,
    }

    family = _mac_font_family(root)
    return {
        "mode": "aqua",
        "family": family,
        "font_heading": (family, 15, "bold"),
        "font_button": (family, 11),
        "font_body": (family, 13),
        "font_row": (family, 13),
        "font_section": (family, 11, "bold"),
        "font_status": (family, 11),
        "geometry": DEFAULT_GEOMETRY,
        "min_size": MIN_SIZE,
        "colors": colors,
        "metrics": {
            "sidebar_width": 220,
            "row_height": 30,
            "row_padx": 10,
            "row_gap": 2,
            "sidebar_pad": 10,
            "toolbar_height": 44,
            "content_pad": 14,
            "status_pad": (12, 5),
        },
    }


def enable_mousewheel(scroll_target, hover_region=None):
    """Make wheel + two-finger trackpad scroll work while the pointer is anywhere
    over hover_region (defaults to scroll_target). scroll_target must support
    yview_scroll (a Canvas, Listbox, or Text)."""
    hover_region = hover_region or scroll_target

    def _on_mousewheel(event):
        # Sign-only scrolling is correct on both macOS raw deltas and the
        # Windows ±120 convention.
        if getattr(event, "delta", 0):
            scroll_target.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _on_enter(_event):
        scroll_target.bind_all("<MouseWheel>", _on_mousewheel)

    def _on_leave(detail):
        # Tk fires <Leave detail=NotifyInferior> when the pointer merely
        # crosses into a CHILD widget of hover_region — the pointer is still
        # over the region, so tearing the binding down there would break
        # scroll over the form's own controls.
        if detail == "NotifyInferior":
            return
        scroll_target.unbind_all("<MouseWheel>")

    hover_region.bind("<Enter>", _on_enter, add="+")
    # tkinter's bind() never substitutes the crossing detail (%d is absent
    # from Misc._subst_format_str, so event.detail does not exist), so the
    # Leave side must be bound at the Tcl level to see NotifyInferior.
    leave_cb = hover_region.register(_on_leave)
    hover_region.tk.call(
        "bind", hover_region._w, "<Leave>", "+%s %%d" % leave_cb
    )


class ProgressIndicator:
    """A ttk.Progressbar plus a counter/percentage label, shared by all tools.

    MAIN-THREAD ONLY: every method here touches Tk widgets, so workers must
    never call them directly. A worker enqueues e.g. ``("progress", (done,
    total))`` on its tool's existing queue and the main-thread drain loop
    calls ``update`` — the same path that feeds the tool's Log box.

    ``self.frame`` is the widget to pack/grid into the tool's layout.
    """

    def __init__(self, parent, *, length: int = 240):
        self.frame = ttk.Frame(parent)
        self.bar = ttk.Progressbar(
            self.frame, mode="determinate", length=length
        )
        self.bar.pack(side="left", fill="x", expand=True)
        self.label = ttk.Label(self.frame, text="", width=14, anchor="e")
        self.label.pack(side="left", padx=(6, 0))
        self._indeterminate = False

    def _stop_indeterminate(self) -> None:
        if self._indeterminate:
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self._indeterminate = False

    def update(self, done, total) -> None:
        """Show determinate progress: done/total items and a percentage."""
        self._stop_indeterminate()
        total = max(1, int(total))
        done = min(max(0, int(done)), total)
        self.bar.configure(maximum=total, value=done)
        pct = round(100 * done / total)
        self.label.configure(text=f"{done}/{total}  {pct}%")

    def set_indeterminate(self, text: str = "Working…") -> None:
        """Animate the bar when no meaningful total exists."""
        if not self._indeterminate:
            self.bar.configure(mode="indeterminate")
            self.bar.start(60)
            self._indeterminate = True
        self.label.configure(text=text)

    def reset(self) -> None:
        """Return to the idle state (empty bar, blank label)."""
        self._stop_indeterminate()
        self.bar.configure(maximum=100, value=0)
        self.label.configure(text="")

    def finish(self) -> None:
        """End-of-run cleanup: a still-animating indeterminate bar resets to
        idle; a determinate bar keeps its final value on screen."""
        if self._indeterminate:
            self.reset()


def apply_theme(root: tk.Tk, style: ttk.Style) -> dict:
    """Apply the platform theme and return the resolved fonts/colors/metrics.

    The launcher builds its widgets exclusively from this dict; ``colors`` and
    ``metrics`` are ``None`` on the classic (non-darwin) branch, whose visual
    output must stay identical to the pre-v0.5.0 launcher.
    """
    if sys.platform == "darwin":
        return _apply_darwin(root, style)
    return _apply_classic(root, style)
