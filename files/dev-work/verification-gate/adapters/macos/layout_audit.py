"""What Tk itself says about one window at the moment it is pictured (v0.8.x P1B closeout). Runs on Tk's main thread, reads only.

A picture alone cannot say whether a label lost the end of its text or two controls sit on each other; Tk can. Each finding is
named by widget path, class and text, so a reviewer can find it in the picture:

  * ``clipped``: a text-bearing widget given less room than it asked for (``winfo_reqwidth``/``reqheight`` above its size).
    A label that wraps (``wraplength``) is judged on height only. A control (button, check box, radio button) clipped is a defect;
    a clipped label is advisory, for the reviewer to judge (a long path shown in a fixed field is clipped by design).
  * ``outside``: a viewable widget reaching past the window's own edge, when no scrolling canvas holds it (a panel's content
    scrolled out of view is not a defect). A control outside the window is a defect.
  * ``overlaps``: two viewable siblings placed by pack or grid whose boxes intersect. Always a defect.
  * ``contrast``: each enabled text widget's foreground against the background it is drawn on, as WCAG's contrast ratio,
    from colours Tk resolves (``winfo_rgb``, which knows the system colours). Below 3.0 is a defect; below 4.5 is advisory.
    A colour Tk cannot resolve is counted, never guessed.
  * ``probes``: points inside widgets drawn in a solid, known background, uncovered by any child, with that colour. The gate
    finds them in the picture to show it is this window, drawn as Tk laid it out (helpers/visual_review.py).
  * ``surrounds`` (ACT72-081): for each natively drawn button that sits on a classic Tk surface (a ``Frame``), the surface's
    colour and a point of the button's own rectangle, just inside its corner and outside the rounded bezel. Aqua fills that
    rectangle in the window colour of the window's current appearance, which no ttk style reaches (measured); where the
    surface is another colour the button shows in a box. The gate compares the two in the picture.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

_TEXT = frozenset({"TButton", "Button", "TCheckbutton", "Checkbutton", "TRadiobutton", "Radiobutton", "TLabel", "Label",
                   "TMenubutton", "Menubutton", "Message"})
_CONTROLS = frozenset({"TButton", "Button", "TCheckbutton", "Checkbutton", "TRadiobutton", "Radiobutton", "TMenubutton", "Menubutton"})
_SOLID = frozenset({"Frame", "Label", "Canvas", "Text", "Listbox"})
#: What a person operates. Overlap is judged between these only: containers stacked in one cell (a card layout, where the
#: raised card hides the others) are a design, not a collision.
_OPERABLE = _CONTROLS | frozenset({"TEntry", "Entry", "TCombobox", "TSpinbox", "Spinbox", "Listbox", "Text", "Treeview", "TScale", "Scale"})
#: ttk classes Aqua draws natively (a bezel and text colour AppKit chooses: the default button is white on the accent blue).
#: Tk's style lookups do not describe that drawing, so their contrast is counted as unresolved, never guessed; the picture
#: itself is what shows them.
_NATIVE_FACE = frozenset({"TButton", "TMenubutton"})
DEFECT_CONTRAST, ADVISORY_CONTRAST = 3.0, 4.5
_SLACK = 2  # points: Tk's own rounding
#: Classic Tk containers whose ``background`` is what a child is drawn on.
_CLASSIC_SURFACE = frozenset({"Frame", "Labelframe"})


def _all(widget) -> list:
    found = [widget]
    for child in widget.winfo_children():
        if child.winfo_class() not in ("Toplevel", "Tk", "Menu"):
            found.extend(_all(child))
    return found


def _box(widget) -> tuple[int, int, int, int]:
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    return x, y, x + widget.winfo_width(), y + widget.winfo_height()


def _text(widget) -> str:
    try:
        return str(widget.cget("text"))[:80]
    except tk.TclError:
        return ""


def _in_canvas(widget, top) -> bool:
    parent = widget.master
    while parent is not None and parent is not top:
        if parent.winfo_class() == "Canvas":
            return True
        parent = parent.master
    return False


def _rgb(widget, colour) -> tuple[int, int, int] | None:
    if not colour:
        return None
    try:
        red, green, blue = widget.winfo_rgb(str(colour))
    except tk.TclError:
        return None
    return red >> 8, green >> 8, blue >> 8


def _ttk_colour(widget, option: str):
    style = ""
    try:
        style = str(widget.cget("style"))
    except tk.TclError:
        pass
    style = style or widget.winfo_class()
    try:
        state = list(widget.state())
    except (tk.TclError, AttributeError, TypeError):
        state = []
    return ttk.Style(widget).lookup(style, option, state) or None


def _colour(widget, option: str):
    if widget.winfo_class().startswith("T"):
        return _ttk_colour(widget, option)
    try:
        return str(widget.cget(option)) or None
    except tk.TclError:
        return None


def _background(widget, top) -> tuple[int, int, int] | None:
    """The colour this widget is drawn on: its own background, else the nearest ancestor's that Tk can resolve (except a
    natively drawn face, which is never the parent's)."""
    if widget.winfo_class() in _NATIVE_FACE and str(widget.tk.call("tk", "windowingsystem")) == "aqua":
        return None
    current = widget
    while current is not None:
        found = _rgb(current, _colour(current, "background"))
        if found is not None:
            return found
        if current is top:
            return None
        current = current.master
    return None


def _luminance(rgb) -> float:
    def channel(value):
        value = value / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = rgb
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast(first, second) -> float:
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return round((light + 0.05) / (dark + 0.05), 2)


def _disabled(widget) -> bool:
    try:
        if "disabled" in [str(flag) for flag in widget.state()]:
            return True
    except (tk.TclError, AttributeError, TypeError):
        pass
    try:
        return str(widget.cget("state")) == "disabled"
    except tk.TclError:
        return False


def _probe(widget, top, children_boxes) -> dict | None:
    """A point inside a solid widget that no child covers, with the colour it should show."""
    if widget.winfo_class() not in _SOLID or widget.winfo_width() < 24 or widget.winfo_height() < 24:
        return None
    try:
        colour = str(widget.cget("background"))
    except tk.TclError:
        return None
    rgb = _rgb(widget, colour)
    if rgb is None:
        return None
    left, upper, right, lower = _box(widget)
    candidates = [(left + 4, upper + 4), (right - 5, upper + 4), (left + 4, lower - 5), (right - 5, lower - 5),
                  ((left + right) // 2, upper + 4), ((left + right) // 2, lower - 5)]
    for x, y in candidates:
        if not any(a - 2 <= x <= c + 2 and b - 2 <= y <= d + 2 for a, b, c, d in children_boxes):
            origin_x, origin_y = top.winfo_rootx(), top.winfo_rooty()
            return {"path": str(widget), "class": widget.winfo_class(), "x": x - origin_x, "y": y - origin_y, "rgb": list(rgb)}
    return None


def _surround(widget, top) -> dict | None:
    """A natively drawn button on a classic surface: the surface's colour, and a point of the button's own rectangle."""
    if widget.winfo_class() not in _NATIVE_FACE or str(widget.tk.call("tk", "windowingsystem")) != "aqua":
        return None
    surface = widget.master
    if surface is None or surface.winfo_class() not in _CLASSIC_SURFACE or min(widget.winfo_width(), widget.winfo_height()) < 8:
        return None
    try:
        rgb = _rgb(surface, surface.cget("background"))
    except tk.TclError:
        return None
    if rgb is None:
        return None
    left, upper = _box(widget)[:2]
    return {"path": str(widget), "surface": str(surface), "text": _text(widget), "x": left + 1 - top.winfo_rootx(),
            "y": upper + 1 - top.winfo_rooty(), "rgb": list(rgb)}


def audit(top) -> dict:
    """The findings for one toplevel, with the counts that show how much was looked at."""
    top.update_idletasks()
    window = _box(top)
    widgets = [item for item in _all(top) if item.winfo_ismapped() and item.winfo_viewable()]
    result = {"widgets": len(widgets), "clipped": [], "outside": [], "overlaps": [], "contrast": [], "contrast_checked": 0,
              "contrast_unresolved": 0, "probes": [], "surrounds": [], "window_points": [top.winfo_width(), top.winfo_height()]}
    by_parent: dict = {}
    for widget in widgets:
        cls = widget.winfo_class()
        width, height = widget.winfo_width(), widget.winfo_height()
        if width <= 1 or height <= 1:
            continue
        by_parent.setdefault(str(widget.master), []).append(widget)
        surround = _surround(widget, top)
        if surround is not None:
            result["surrounds"].append(surround)
        if cls in _TEXT:
            try:
                wraps = int(float(str(widget.cget("wraplength")) or 0)) > 0
            except (tk.TclError, ValueError):
                wraps = False
            wide = widget.winfo_reqwidth() - width > _SLACK and not wraps
            tall = widget.winfo_reqheight() - height > _SLACK
            if (wide or tall) and _text(widget).strip():
                result["clipped"].append({"path": str(widget), "class": cls, "text": _text(widget), "kind": "control" if cls in _CONTROLS else "label",
                                          "requested": [widget.winfo_reqwidth(), widget.winfo_reqheight()], "given": [width, height]})
            if not _disabled(widget) and _text(widget).strip():
                foreground = _rgb(widget, _colour(widget, "foreground"))
                background = _background(widget, top)
                if foreground is None or background is None:
                    result["contrast_unresolved"] += 1
                else:
                    result["contrast_checked"] += 1
                    ratio = contrast(foreground, background)
                    if ratio < ADVISORY_CONTRAST:
                        result["contrast"].append({"path": str(widget), "class": cls, "text": _text(widget), "ratio": ratio,
                                                   "kind": "defect" if ratio < DEFECT_CONTRAST else "advisory",
                                                   "foreground": list(foreground), "background": list(background)})
        box = _box(widget)
        if widget is not top and not _in_canvas(widget, top) and (box[0] < window[0] - _SLACK or box[1] < window[1] - _SLACK
                                                                   or box[2] > window[2] + _SLACK or box[3] > window[3] + _SLACK):
            result["outside"].append({"path": str(widget), "class": cls, "text": _text(widget), "kind": "control" if cls in _CONTROLS else "other",
                                      "box": [box[0] - window[0], box[1] - window[1], box[2] - window[0], box[3] - window[1]]})
    for siblings in by_parent.values():
        placed = [item for item in siblings if item.winfo_manager() in ("pack", "grid") and item.winfo_class() in _OPERABLE]
        for index, first in enumerate(placed):
            a = _box(first)
            for second in placed[index + 1:]:
                b = _box(second)
                width = min(a[2], b[2]) - max(a[0], b[0])
                height = min(a[3], b[3]) - max(a[1], b[1])
                if width > _SLACK and height > _SLACK:
                    result["overlaps"].append({"first": str(first), "second": str(second), "area": width * height})
    for widget in widgets:
        children = [_box(child) for child in widget.winfo_children() if child.winfo_ismapped() and child.winfo_class() not in ("Toplevel", "Menu")]
        probe = _probe(widget, top, children)
        if probe is not None:
            result["probes"].append(probe)
        if len(result["probes"]) >= 24:
            break
    return result

