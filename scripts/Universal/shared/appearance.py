"""The v0.6.6 shared Light/Dark appearance system: one remembered setting, one
compact cross-platform ttk style catalogue, and a state-preserving refresh path.

This is deliberately **separate** from ``shared/ui_theme.py``. That module owns
the launcher's outer shell chrome (the dark/navy Windows design and the native
aqua Finder chrome) and the ``ACT.*`` style family, both of which the v0.6.6
Frozen UI Contract keeps "substantially unchanged". This module owns the new
**compact Tkinter/ttk visual system** that individual tool panels and app-owned
dialogs adopt in later phases, under one global remembered ``"light"``/``"dark"``
setting — a decision orthogonal to platform, unlike ``ui_theme``'s per-platform
branching.

Persistence goes through ``shared.settings`` under the key ``"appearance"`` —
never ``config.toml`` — exactly as the frozen contract requires. ``"light"`` is
the default for a first run or an unrecognised stored value, so a corrupted or
hand-edited setting degrades to the documented default rather than raising.

Why a second clam-clone under a new prefix, not a reuse of ``ACT.*``
----------------------------------------------------------------------
Windows' native ``vista`` base theme (kept so any still-unconverted panel
renders unchanged) ignores ``-background``/``-foreground`` on its native
elements, exactly as documented in ``ui_theme.py``. ``ACT.*`` already solves
this by cloning ``clam``'s recolorable elements under its own prefix — but
``ACT.*`` carries one fixed dark palette and is the identity of the *old*
Windows-only conversion this plan retires. The compact system needs **two**
palettes (light/dark) available on **every** platform, so it clones the same
``clam`` elements again under ``Compact.*`` — a namespace fully disjoint from
``ACT.*`` and from every generic style name. Nothing here ever touches
``ACT.*``, a generic ``TButton``/``TFrame``/etc., or ``style.theme_use()``.

On macOS, the controls retain their native Aqua layouts and metrics. Their
window's native appearance is explicitly set to match the app preference;
otherwise native controls follow the OS while classic Tk content follows the
app, producing a mixed Light/Dark interior. Namespaced surface/label colors
and the Shared border provide the same semantic distinction as other platforms,
without installing Windows button, field or check/radio layouts on Aqua.

State-preserving refresh
-------------------------
``ttk.Style.configure`` mutates a *named style* process-wide: every widget
already built with that style name repaints the next time Tk redraws, with no
widget destroyed and no Python-level state touched. So :func:`build_bundle`
doubles as the refresh path — calling it again with a new appearance
reconfigures the same ``Compact.*`` names in place. The one thing ttk styling
cannot reach is a raw ``Toplevel``'s own ``-background`` (it is a plain Tk
window option, not a ttk style), so an app-owned dialog that sets its own
background from ``bundle["colors"]["window"]`` must re-apply that one line
itself when notified — see :func:`register_listener`.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable

from . import settings as app_settings

#: The persisted settings key. Never written to config.toml.
SETTINGS_KEY = "appearance"

LIGHT = "light"
DARK = "dark"
_VALID = (LIGHT, DARK)

#: First-run default, per the frozen UI contract.
DEFAULT_APPEARANCE = LIGHT

#: Every ttk style this module registers begins with this prefix. Disjoint
#: from ``ui_theme.WINDOWS_STYLE_PREFIX`` ("ACT") and from every generic name.
STYLE_PREFIX = "Compact"


# ---------------------------------------------------------------------------
# persisted setting
# ---------------------------------------------------------------------------


def get_appearance() -> str:
    """The remembered appearance, or the documented default.

    A missing key, or a value that is not exactly ``"light"``/``"dark"``
    (hand-edited settings, an older/newer build's value), falls back to the
    default rather than raising — the same forgiving contract
    ``shared.settings`` itself documents.
    """
    value = app_settings.get(SETTINGS_KEY, DEFAULT_APPEARANCE)
    return value if value in _VALID else DEFAULT_APPEARANCE


def set_appearance(value: str) -> bool:
    """Persist *value* (``"light"`` or ``"dark"``). True when it reached disk.

    Raises ``ValueError`` for anything else — this is a programming-error
    guard, not a place to silently coerce an invalid caller-supplied value.
    """
    if value not in _VALID:
        raise ValueError(f"appearance must be one of {_VALID}, got {value!r}")
    return app_settings.set(SETTINGS_KEY, value)


def toggle_stored_appearance() -> str:
    """Flip and persist the stored setting; return the new value.

    Pure data — no ``ttk.Style``/root involved, so it is safe to unit-test
    without a display. :func:`toggle_appearance` is the Tk-aware counterpart a
    shell toggle button actually calls.
    """
    new_value = DARK if get_appearance() == LIGHT else LIGHT
    set_appearance(new_value)
    # settings.set rolls back on a failed atomic write. Render that actual
    # value as well, so a failed save cannot put the live UI ahead of storage.
    return get_appearance()


# ---------------------------------------------------------------------------
# palettes
# ---------------------------------------------------------------------------

#: Close to the current compact classic Tkinter presentation, per the frozen
#: contract's instruction for Light mode.
#: v0.6.6 Phase 2 remediation: retuned so Light reads as the classic Windows
#: presentation the TTS panel (the maintainer's visual-control reference) draws
#: natively -- a #f0f0f0 panel and sections, near-white bordered buttons and
#: white fields -- rather than white sections with darker buttons, which
#: inverted it. The accent was darkened just enough to keep its >= 4.5:1 bar
#: against the now-grey surface.
LIGHT_COLORS: dict[str, object] = {
    "window": "#f0f0f0", "sidebar": "#eeeeee", "surface": "#f0f0f0",
    "elevated": "#fdfdfd", "muted": "#e9edf3", "border": "#c9c9c9",
    "divider": "#d9d9d9",
    "text": "#1a1a1a", "secondary": "#555555", "disabled": "#6b6b6b",
    "inverse": "#ffffff",
    "accent": "#1860c0", "accent_hover": "#2f74d0", "accent_pressed": "#134f9e",
    "accent_soft": "#dce8fb", "focus": "#1860c0", "link": "#1860c0",
    "success": "#166b2e", "warning": "#744300", "danger": "#b42424",
    "danger_hover": "#c83a3a", "danger_pressed": "#931c1c",
    "field": "#ffffff", "field_disabled": "#f4f4f4", "field_border": "#adadad",
    "selection": "#1860c0", "selection_text": "#ffffff",
    "selection_inactive": "#cfe0f7",
    "scroll_trough": "#eeeeee", "scroll_thumb": "#c4c4c4",
    "scroll_thumb_hover": "#adadad",
    # Shared vs Current Book tint (Frozen UI Contract §2), ready for the
    # Family B tools this module does not itself build.
    "shared_bg": "#e7edf7", "shared_border": "#8fa9d1", "shared_header": "#2f5da8",
    "is_dark": False,
}

#: A neutral charcoal/dark-grey palette with restrained navy/blue accents, per
#: the frozen contract: "the same UI with a dark appearance, not a second
#: design system."
DARK_COLORS: dict[str, object] = {
    "window": "#1e1f22", "sidebar": "#232427", "surface": "#26282c",
    "elevated": "#2d2f34", "muted": "#20242b", "border": "#3a3c41",
    "divider": "#33353a",
    "text": "#e7e8ea", "secondary": "#a6a9ae", "disabled": "#767a80",
    "inverse": "#101113",
    "accent": "#5b9bf7", "accent_hover": "#7bacf8", "accent_pressed": "#3f80dd",
    "accent_soft": "#233551", "focus": "#5b9bf7", "link": "#7bacf8",
    "success": "#57b975", "warning": "#d3a94a", "danger": "#e57a72",
    "danger_hover": "#ec8f88", "danger_pressed": "#c24f48",
    "field": "#1c1d20", "field_disabled": "#26282c", "field_border": "#44474d",
    "selection": "#3f6fb0", "selection_text": "#ffffff",
    "selection_inactive": "#33475f",
    "scroll_trough": "#232427", "scroll_thumb": "#42454b",
    "scroll_thumb_hover": "#54585f",
    "shared_bg": "#1c2733", "shared_border": "#3a5a80", "shared_header": "#9cc2f5",
    "is_dark": True,
}

_PALETTES = {LIGHT: LIGHT_COLORS, DARK: DARK_COLORS}

#: Compact spacing/sizing tokens. Appearance-independent — only colors differ
#: between Light and Dark, per the frozen contract's "same geometry/hierarchy".
#:
#: v0.6.6 Phase 2 remediation: ``field_pad``/``button_pad``/``tab_pad``/
#: ``tree_row_height`` were retuned so a compact control measures the same as
#: the native control the TTS panel (the visual-control reference) draws. With
#: the body font at ``TkDefaultFont``'s size, measured on Windows ``vista``:
#: Button "Add Files" 76x25 native vs 76x25 compact (was 103x31); Entry
#: width=10 66x21 vs 68x21 (was 76x25); Combobox width=7 65x21 vs 63x21 (was
#: 71x25); Checkbutton 21 px tall either way (was 23).
METRICS: dict[str, object] = {
    "gap_xs": 2, "gap_sm": 4, "gap_md": 8, "gap_lg": 12, "gap_xl": 16,
    "card_pad": 6, "card_gap": 6, "section_gap": 8,
    "field_pad": (2, 1), "button_pad": (2, 2), "nav_pad": (8, 4),
    "tab_pad": (8, 2),
    "border_width": 1, "focus_width": 1, "scroll_width": 11,
    "progress_thickness": 8, "tree_row_height": 20,
    "row_height": 26, "row_padx": 8, "row_gap": 1,
    "content_pad": 10, "status_pad": (10, 4),
}

#: Semantic name -> registered ttk style name, mirroring
#: ``ui_theme._WINDOWS_STYLES``'s vocabulary so an app-owned dialog written
#: against that convention needs no new lookup pattern.
_STYLES: dict[str, str] = {
    "window": f"{STYLE_PREFIX}.Window.TFrame",
    "surface": f"{STYLE_PREFIX}.TFrame",
    "card": f"{STYLE_PREFIX}.Card.TFrame",
    "elevated": f"{STYLE_PREFIX}.Elevated.TFrame",
    "muted": f"{STYLE_PREFIX}.Muted.TFrame",
    "shared_surface": f"{STYLE_PREFIX}.Shared.TFrame",
    "sidebar": f"{STYLE_PREFIX}.Sidebar.TFrame",
    "divider": f"{STYLE_PREFIX}.Divider.TFrame",
    "toolbar": f"{STYLE_PREFIX}.Toolbar.TFrame",
    "label": f"{STYLE_PREFIX}.TLabel",
    "title": f"{STYLE_PREFIX}.Title.TLabel",
    "heading": f"{STYLE_PREFIX}.Heading.TLabel",
    "subheading": f"{STYLE_PREFIX}.Subheading.TLabel",
    "section": f"{STYLE_PREFIX}.Section.TLabel",
    "secondary_label": f"{STYLE_PREFIX}.Secondary.TLabel",
    "status_label": f"{STYLE_PREFIX}.Status.TLabel",
    "link_label": f"{STYLE_PREFIX}.Link.TLabel",
    "success_label": f"{STYLE_PREFIX}.Success.TLabel",
    "warning_label": f"{STYLE_PREFIX}.Warning.TLabel",
    "danger_label": f"{STYLE_PREFIX}.Danger.TLabel",
    "muted_label": f"{STYLE_PREFIX}.Muted.TLabel",
    "shared_header": f"{STYLE_PREFIX}.SharedHeader.TLabel",
    "shared_label": f"{STYLE_PREFIX}.Shared.TLabel",
    "shared_secondary": f"{STYLE_PREFIX}.SharedSecondary.TLabel",
    "button": f"{STYLE_PREFIX}.TButton",
    "primary_button": f"{STYLE_PREFIX}.Primary.TButton",
    "danger_button": f"{STYLE_PREFIX}.Danger.TButton",
    "ghost_button": f"{STYLE_PREFIX}.Ghost.TButton",
    "nav_button": f"{STYLE_PREFIX}.Nav.TButton",
    "entry": f"{STYLE_PREFIX}.TEntry",
    "combobox": f"{STYLE_PREFIX}.TCombobox",
    "spinbox": f"{STYLE_PREFIX}.TSpinbox",
    "checkbutton": f"{STYLE_PREFIX}.TCheckbutton",
    "radiobutton": f"{STYLE_PREFIX}.TRadiobutton",
    "muted_checkbutton": f"{STYLE_PREFIX}.Muted.TCheckbutton",
    "shared_checkbutton": f"{STYLE_PREFIX}.Shared.TCheckbutton",
    "labelframe": f"{STYLE_PREFIX}.TLabelframe",
    "shared_labelframe": f"{STYLE_PREFIX}.Shared.TLabelframe",
    "notebook": f"{STYLE_PREFIX}.TNotebook",
    "progressbar": f"{STYLE_PREFIX}.Horizontal.TProgressbar",
    "vscrollbar": f"{STYLE_PREFIX}.Vertical.TScrollbar",
    "hscrollbar": f"{STYLE_PREFIX}.Horizontal.TScrollbar",
    "treeview": f"{STYLE_PREFIX}.Treeview",
    "separator": f"{STYLE_PREFIX}.TSeparator",
}

# A separate namespace prevents a Windows comparison/test registration from
# leaving cloned control layouts or padding behind in the native Aqua branch.
_AQUA_STYLE_PREFIX = "CompactAqua"
_AQUA_STYLES = {key: name.replace(STYLE_PREFIX + ".", _AQUA_STYLE_PREFIX + ".", 1)
                for key, name in _STYLES.items()}

#: ``clam`` elements cloned under this module's own prefix. Same source
#: elements ``ui_theme`` clones for ``ACT.*`` — cloning is per-target-name, so
#: the two prefixes coexist without conflict.
_CLONED_ELEMENTS: tuple[str, ...] = (
    "Button.border", "Button.focus", "Entry.field", "Combobox.field",
    "Combobox.downarrow", "Spinbox.field", "Spinbox.uparrow",
    "Spinbox.downarrow", "Checkbutton.indicator", "Radiobutton.indicator",
    "Notebook.client", "Notebook.tab", "Horizontal.Progressbar.trough",
    "Horizontal.Progressbar.pbar", "Vertical.Scrollbar.trough",
    "Vertical.Scrollbar.thumb", "Vertical.Scrollbar.uparrow",
    "Vertical.Scrollbar.downarrow", "Horizontal.Scrollbar.trough",
    "Horizontal.Scrollbar.thumb", "Horizontal.Scrollbar.leftarrow",
    "Horizontal.Scrollbar.rightarrow", "Treeview.field", "Treeitem.indicator",
    "Treeheading.cell", "Treeheading.border", "Labelframe.border",
    "Separator.separator",
)

_P = STYLE_PREFIX  # keeps the layout tables readable

#: Layouts for the Compact styles — the same clam shapes ``ui_theme`` uses,
#: with this module's own cloned-element names.
_LAYOUTS: dict[str, list] = {
    f"{_P}.TButton": [
        (f"{_P}.Button.border", {"sticky": "nswe", "border": "1", "children": [
            (f"{_P}.Button.focus", {"sticky": "nswe", "children": [
                ("Button.padding", {"sticky": "nswe", "children": [
                    ("Button.label", {"sticky": "nswe"})]})]})]})],
    f"{_P}.TEntry": [
        (f"{_P}.Entry.field", {"sticky": "nswe", "border": "1", "children": [
            ("Entry.padding", {"sticky": "nswe", "children": [
                ("Entry.textarea", {"sticky": "nswe"})]})]})],
    f"{_P}.TCombobox": [
        (f"{_P}.Combobox.downarrow", {"side": "right", "sticky": "ns"}),
        (f"{_P}.Combobox.field", {"sticky": "nswe", "children": [
            ("Combobox.padding", {"sticky": "nswe", "children": [
                ("Combobox.textarea", {"sticky": "nswe"})]})]})],
    f"{_P}.TSpinbox": [
        (f"{_P}.Spinbox.field", {"side": "top", "sticky": "we", "children": [
            ("null", {"side": "right", "sticky": "", "children": [
                (f"{_P}.Spinbox.uparrow", {"side": "top", "sticky": "e"}),
                (f"{_P}.Spinbox.downarrow", {"side": "bottom", "sticky": "e"})]}),
            ("Spinbox.padding", {"sticky": "nswe", "children": [
                ("Spinbox.textarea", {"sticky": "nswe"})]})]})],
    f"{_P}.TCheckbutton": [
        ("Checkbutton.padding", {"sticky": "nswe", "children": [
            (f"{_P}.Checkbutton.check", {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nswe"})]})]})],
    f"{_P}.TRadiobutton": [
        ("Radiobutton.padding", {"sticky": "nswe", "children": [
            (f"{_P}.Radiobutton.radio", {"side": "left", "sticky": ""}),
            ("Radiobutton.focus", {"side": "left", "sticky": "", "children": [
                ("Radiobutton.label", {"sticky": "nswe"})]})]})],
    f"{_P}.TNotebook": [(f"{_P}.Notebook.client", {"sticky": "nswe"})],
    f"{_P}.TNotebook.Tab": [
        (f"{_P}.Notebook.tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                ("Notebook.focus", {"side": "top", "sticky": "nswe", "children": [
                    ("Notebook.label", {"side": "top", "sticky": ""})]})]})]})],
    f"{_P}.Horizontal.TProgressbar": [
        (f"{_P}.Horizontal.Progressbar.trough", {"sticky": "nswe", "children": [
            (f"{_P}.Horizontal.Progressbar.pbar",
             {"side": "left", "sticky": "ns"})]})],
    f"{_P}.Vertical.TScrollbar": [
        (f"{_P}.Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            (f"{_P}.Vertical.Scrollbar.uparrow", {"side": "top", "sticky": ""}),
            (f"{_P}.Vertical.Scrollbar.downarrow", {"side": "bottom", "sticky": ""}),
            (f"{_P}.Vertical.Scrollbar.thumb", {"sticky": "nswe"})]})],
    f"{_P}.Horizontal.TScrollbar": [
        (f"{_P}.Horizontal.Scrollbar.trough", {"sticky": "we", "children": [
            (f"{_P}.Horizontal.Scrollbar.leftarrow", {"side": "left", "sticky": ""}),
            (f"{_P}.Horizontal.Scrollbar.rightarrow", {"side": "right", "sticky": ""}),
            (f"{_P}.Horizontal.Scrollbar.thumb", {"sticky": "nswe"})]})],
    f"{_P}.Treeview": [
        (f"{_P}.Treeview.field", {"sticky": "nswe", "border": "1", "children": [
            ("Treeview.padding", {"sticky": "nswe", "children": [
                ("Treeview.treearea", {"sticky": "nswe"})]})]})],
    f"{_P}.Treeview.Item": [
        ("Treeitem.padding", {"sticky": "nswe", "children": [
            (f"{_P}.Treeitem.indicator", {"side": "left", "sticky": ""}),
            ("Treeitem.image", {"side": "left", "sticky": ""}),
            ("Treeitem.text", {"sticky": "nswe"})]})],
    f"{_P}.Treeview.Heading": [
        (f"{_P}.Treeheading.cell", {"sticky": "nswe"}),
        (f"{_P}.Treeheading.border", {"sticky": "nswe", "children": [
            ("Treeheading.padding", {"sticky": "nswe", "children": [
                ("Treeheading.image", {"side": "right", "sticky": ""}),
                ("Treeheading.text", {"sticky": "we"})]})]})],
    f"{_P}.TLabelframe": [(f"{_P}.Labelframe.border", {"sticky": "nswe"})],
    f"{_P}.TLabelframe.Label": [
        ("Label.fill", {"sticky": "nswe", "children": [
            ("Label.text", {"sticky": "nswe"})]})],
    f"{_P}.TSeparator": [(f"{_P}.Separator.separator", {"sticky": "nswe"})],
}

# Same ttk style-resolution reason ``ui_theme`` documents: a variant with no
# layout of its own falls back to the native generic style, not its base.
for _variant, _base in (
    (f"{_P}.Primary.TButton", f"{_P}.TButton"),
    (f"{_P}.Danger.TButton", f"{_P}.TButton"),
    (f"{_P}.Ghost.TButton", f"{_P}.TButton"),
    (f"{_P}.Nav.TButton", f"{_P}.TButton"),
    (f"{_P}.Muted.TCheckbutton", f"{_P}.TCheckbutton"),
    (f"{_P}.Shared.TCheckbutton", f"{_P}.TCheckbutton"),
    (f"{_P}.Shared.TLabelframe", f"{_P}.TLabelframe"),
    (f"{_P}.Shared.TLabelframe.Label", f"{_P}.TLabelframe.Label"),
):
    _LAYOUTS[_variant] = _LAYOUTS[_base]
del _variant, _base


def _classic_font_family(platform: str) -> str:
    if platform == "win32":
        return "Segoe UI"
    if platform == "darwin":
        return "Helvetica Neue"
    return "TkDefaultFont"


def _mac_font_family(root: tk.Misc) -> str:
    try:
        probe = tkfont.Font(root=root, family=".AppleSystemUIFont", size=13)
        if probe.actual("family") == ".AppleSystemUIFont":
            return ".AppleSystemUIFont"
    except tk.TclError:
        pass
    return "Helvetica Neue"


#: The body size when no live root can be asked -- ``TkDefaultFont``'s size on
#: Windows, where the ``Compact.*`` catalogue is actually registered.
_FALLBACK_BODY_SIZE = 9


def _default_font_size(root: tk.Misc | None) -> int:
    """``TkDefaultFont``'s point size: what the TTS panel's native controls use.

    The TTS panel is the maintainer's visual-control reference (Decisions.md,
    2026-09-27), and it draws every label, button and check with the platform's
    own default font. Deriving the compact body size from that font -- rather than
    choosing a number -- is what keeps a compact control the same size as its
    native TTS counterpart on any scaling. A pixel size (negative) or an
    unreadable font falls back to the Windows value.
    """
    if root is None:
        return _FALLBACK_BODY_SIZE
    try:
        size = int(tkfont.nametofont("TkDefaultFont", root=root).actual("size"))
    except (tk.TclError, ValueError, RuntimeError):
        return _FALLBACK_BODY_SIZE
    return size if size > 0 else _FALLBACK_BODY_SIZE


def _fonts(family: str, body: int = _FALLBACK_BODY_SIZE) -> dict[str, tuple]:
    return {
        "title": (family, body + 6, "bold"), "heading": (family, body + 4, "bold"),
        "subheading": (family, body + 1, "bold"), "section": (family, body),
        "body": (family, body), "body_bold": (family, body, "bold"),
        "row": (family, body), "small": (family, body), "status": (family, body),
        "button": (family, body), "mono": ("Consolas", body),
    }


def _clone_elements(style: ttk.Style) -> None:
    """Clone the recolorable clam elements under ``Compact.*``, once.

    Tolerant of a repeated call (``element_create`` raises "Duplicate element"
    the second time) and of a missing source element on an exotic Tk build,
    for the same reasons ``ui_theme._clone_elements`` is.
    """
    try:
        existing = set(style.element_names())
    except tk.TclError:
        existing = set()
    for element in _CLONED_ELEMENTS:
        target = f"{STYLE_PREFIX}.{element}"
        if target in existing:
            continue
        try:
            style.element_create(target, "from", "clam", element)
        except tk.TclError:
            continue


#: Side, in pixels, of the drawn check/radio indicators -- the size TTS's native
#: Windows indicators draw at 100% scaling.
_INDICATOR_SIZE = 13
#: Transparent columns to the right of each indicator: the gap before its
#: label (an image element ignores the ``indicatormargin`` style option).
_INDICATOR_GAP = 5
_CHECK_MARK = ((3, 6), (4, 7), (5, 8), (6, 7), (7, 6), (8, 5), (9, 4),
               (3, 7), (4, 8), (5, 9), (6, 8), (7, 7), (8, 6), (9, 5))
_INDICATOR_STATES = ("off", "on", "disabled_off", "disabled_on")


def _indicator_pixels(kind: str, state: str, c: dict) -> dict[tuple[int, int], str]:
    """Pixel -> color for one indicator image; unlisted pixels stay transparent.

    Drawn from the palette so the same box-and-checkmark / ringed-dot the TTS
    panel shows natively reads correctly on every surface, Light or Dark. The
    ``clam`` indicator this replaces draws an X, which is not the control
    language the maintainer's reference uses.
    """
    disabled = state.startswith("disabled")
    selected = state.endswith("on")
    size = _INDICATOR_SIZE
    pixels: dict[tuple[int, int], str] = {}
    if kind == "check":
        if selected:
            edge = fill = c["disabled"] if disabled else c["accent"]
        else:
            edge = c["border"] if disabled else c["field_border"]
            fill = c["field_disabled"] if disabled else c["field"]
        for y in range(size):
            for x in range(size):
                border = x in (0, size - 1) or y in (0, size - 1)
                pixels[(x, y)] = edge if border else fill
        if selected:
            mark = c["field_disabled"] if disabled else c["inverse"]
            for point in _CHECK_MARK:
                pixels[point] = mark
        return pixels
    centre = (size - 1) / 2
    if selected:
        ring = dot = c["disabled"] if disabled else c["accent"]
    else:
        ring = c["border"] if disabled else c["field_border"]
        dot = None
    fill = c["field_disabled"] if disabled else c["field"]
    for y in range(size):
        for x in range(size):
            distance = ((x - centre) ** 2 + (y - centre) ** 2) ** 0.5
            if distance < 5.0:
                pixels[(x, y)] = dot if dot is not None and distance <= 2.6 else fill
            elif distance < 6.3:
                pixels[(x, y)] = ring
    return pixels


def _indicator_images(style: ttk.Style, c: dict) -> dict[str, tk.PhotoImage]:
    """Create (once per interpreter) and redraw the indicator images in place.

    Redrawing the *same* image objects is what makes a Light/Dark toggle
    repaint every existing Checkbutton/Radiobutton without rebuilding any of
    them -- the indicator equivalent of reconfiguring a named style.
    """
    holder = style.master if style.master is not None else tk._default_root
    # Held by the toplevel, never by whichever panel frame asked: the elements
    # are created once per interpreter and outlive any one panel, and a
    # collected PhotoImage deletes its Tcl image out from under them.
    try:
        holder = holder.winfo_toplevel()
    except (AttributeError, tk.TclError):
        pass
    images = getattr(holder, "_compact_indicator_images", None)
    if images is None:
        images = {f"{kind}_{state}": tk.PhotoImage(
                      master=holder, width=_INDICATOR_SIZE + _INDICATOR_GAP,
                  height=_INDICATOR_SIZE)
                  for kind in ("check", "radio") for state in _INDICATOR_STATES}
        holder._compact_indicator_images = images
    for key, image in images.items():
        kind, state = key.split("_", 1)
        image.blank()
        for (x, y), color in _indicator_pixels(kind, state, c).items():
            image.put(color, to=(x, y, x + 1, y + 1))
    return images


def _ensure_indicator_elements(style: ttk.Style, c: dict) -> None:
    images = _indicator_images(style, c)
    try:
        existing = set(style.element_names())
    except tk.TclError:
        existing = set()
    for kind, element in (("check", f"{STYLE_PREFIX}.Checkbutton.check"),
                          ("radio", f"{STYLE_PREFIX}.Radiobutton.radio")):
        if element in existing:
            continue
        try:
            style.element_create(
                element, "image", images[f"{kind}_off"],
                ("disabled", "selected", images[f"{kind}_disabled_on"]),
                ("disabled", images[f"{kind}_disabled_off"]),
                ("selected", images[f"{kind}_on"]),
                sticky="")
        except tk.TclError:
            continue


def _register_ttk_styles(style: ttk.Style, c: dict, m: dict, f: dict) -> None:
    """Define every ``Compact.*`` style. No generic style is touched."""
    _clone_elements(style)
    _ensure_indicator_elements(style, c)

    for name, layout in _LAYOUTS.items():
        try:
            style.layout(name, layout)
        except tk.TclError:
            continue

    style.configure(f"{_P}.TFrame", background=c["surface"])
    style.configure(f"{_P}.Window.TFrame", background=c["window"])
    style.configure(f"{_P}.Card.TFrame", background=c["surface"])
    style.configure(f"{_P}.Elevated.TFrame", background=c["elevated"])
    style.configure(f"{_P}.Muted.TFrame", background=c["muted"])
    style.configure(f"{_P}.Shared.TFrame", background=c["shared_bg"])
    style.configure(f"{_P}.Sidebar.TFrame", background=c["sidebar"])
    style.configure(f"{_P}.Toolbar.TFrame", background=c["window"])
    style.configure(f"{_P}.Divider.TFrame", background=c["border"])

    style.configure(f"{_P}.TLabel", background=c["surface"],
                    foreground=c["text"], font=f["body"])
    style.configure(f"{_P}.Title.TLabel", background=c["window"],
                    foreground=c["text"], font=f["title"])
    style.configure(f"{_P}.Heading.TLabel", background=c["surface"],
                    foreground=c["text"], font=f["heading"])
    style.configure(f"{_P}.Subheading.TLabel", background=c["surface"],
                    foreground=c["text"], font=f["subheading"])
    style.configure(f"{_P}.Section.TLabel", background=c["surface"],
                    foreground=c["secondary"], font=f["section"])
    style.configure(f"{_P}.Secondary.TLabel", background=c["surface"],
                    foreground=c["secondary"], font=f["body"])
    style.configure(f"{_P}.Status.TLabel", background=c["window"],
                    foreground=c["secondary"], font=f["status"])
    # An accent caption inside a tool section (TTS's engine line), so it sits
    # on the section surface like every other content label.
    style.configure(f"{_P}.Link.TLabel", background=c["surface"],
                    foreground=c["link"], font=f["body"])
    style.configure(f"{_P}.Success.TLabel", background=c["surface"],
                    foreground=c["success"], font=f["body"])
    style.configure(f"{_P}.Warning.TLabel", background=c["surface"],
                    foreground=c["warning"], font=f["body"])
    style.configure(f"{_P}.Danger.TLabel", background=c["surface"],
                    foreground=c["danger"], font=f["body"])
    style.configure(f"{_P}.Muted.TLabel", background=c["muted"],
                    foreground=c["text"], font=f["body"])
    style.configure(f"{_P}.SharedHeader.TLabel", background=c["shared_bg"],
                    foreground=c["shared_header"], font=f["subheading"])
    style.configure(f"{_P}.Shared.TLabel", background=c["shared_bg"],
                    foreground=c["text"], font=f["body"])
    style.configure(f"{_P}.SharedSecondary.TLabel", background=c["shared_bg"],
                    foreground=c["secondary"], font=f["small"])
    for name in (f"{_P}.TLabel", f"{_P}.Heading.TLabel", f"{_P}.Subheading.TLabel",
                 f"{_P}.Secondary.TLabel", f"{_P}.Muted.TLabel",
                 f"{_P}.Shared.TLabel", f"{_P}.SharedSecondary.TLabel"):
        style.map(name, foreground=[("disabled", c["disabled"])])

    # A bordered box in every state, the way TTS's native buttons draw: the
    # field-border outline stays visible even disabled, so a greyed action
    # still reads as a button rather than as stray text.
    style.configure(
        f"{_P}.TButton", background=c["elevated"], foreground=c["text"],
        bordercolor=c["field_border"], lightcolor=c["elevated"],
        darkcolor=c["elevated"], focuscolor=c["focus"], font=f["button"],
        padding=m["button_pad"], relief="raised", borderwidth=m["border_width"],
        anchor="center",
    )
    style.map(
        f"{_P}.TButton",
        background=[("disabled", c["field_disabled"]), ("pressed", c["accent_soft"]),
                    ("active", c["accent_soft"]), ("selected", c["accent_soft"])],
        foreground=[("disabled", c["disabled"])],
        # ``alternate`` is ttk's state for ``default="active"`` -- the same
        # restrained primary-action cue TTS's Start button gets natively.
        bordercolor=[("disabled", c["border"]), ("focus", c["focus"]),
                     ("alternate", c["accent"]), ("active", c["accent"])],
        lightcolor=[("disabled", c["field_disabled"]), ("pressed", c["accent_soft"]),
                    ("active", c["accent_soft"])],
        darkcolor=[("disabled", c["field_disabled"]), ("pressed", c["accent_soft"]),
                   ("active", c["accent_soft"])],
    )
    style.configure(
        f"{_P}.Primary.TButton", background=c["accent"], foreground=c["inverse"],
        bordercolor=c["accent"], lightcolor=c["accent"], darkcolor=c["accent"],
        focuscolor=c["inverse"], font=f["button"], padding=m["button_pad"],
        relief="raised", borderwidth=m["border_width"], anchor="center",
    )
    style.map(
        f"{_P}.Primary.TButton",
        background=[("disabled", c["surface"]), ("pressed", c["accent_pressed"]),
                    ("active", c["accent_hover"])],
        foreground=[("disabled", c["disabled"])],
        bordercolor=[("disabled", c["border"]), ("focus", c["focus"]),
                     ("pressed", c["accent_pressed"]), ("active", c["accent_hover"])],
        lightcolor=[("pressed", c["accent_pressed"]), ("active", c["accent_hover"])],
        darkcolor=[("pressed", c["accent_pressed"]), ("active", c["accent_hover"])],
    )
    style.configure(
        f"{_P}.Danger.TButton", background=c["surface"], foreground=c["danger"],
        bordercolor=c["danger"], lightcolor=c["surface"], darkcolor=c["surface"],
        focuscolor=c["focus"], font=f["button"], padding=m["button_pad"],
        relief="raised", borderwidth=m["border_width"], anchor="center",
    )
    style.map(
        f"{_P}.Danger.TButton",
        background=[("disabled", c["surface"]), ("pressed", c["danger_pressed"]),
                    ("active", c["danger"])],
        foreground=[("disabled", c["disabled"]), ("pressed", c["selection_text"]),
                    ("active", c["selection_text"])],
        bordercolor=[("disabled", c["border"]), ("focus", c["focus"]),
                     ("pressed", c["danger_pressed"]), ("active", c["danger_hover"])],
        lightcolor=[("pressed", c["danger_pressed"]), ("active", c["danger"])],
        darkcolor=[("pressed", c["danger_pressed"]), ("active", c["danger"])],
    )
    style.configure(
        f"{_P}.Ghost.TButton", background=c["window"], foreground=c["secondary"],
        bordercolor=c["window"], lightcolor=c["window"], darkcolor=c["window"],
        focuscolor=c["focus"], font=f["button"], padding=m["button_pad"],
        relief="flat", borderwidth=0, anchor="center",
    )
    style.map(
        f"{_P}.Ghost.TButton",
        background=[("disabled", c["window"]), ("pressed", c["surface"]),
                    ("active", c["surface"])],
        foreground=[("disabled", c["disabled"]), ("active", c["text"])],
        bordercolor=[("focus", c["focus"])],
        lightcolor=[("pressed", c["surface"]), ("active", c["surface"])],
        darkcolor=[("pressed", c["surface"]), ("active", c["surface"])],
    )
    style.configure(
        f"{_P}.Nav.TButton", background=c["sidebar"], foreground=c["secondary"],
        bordercolor=c["sidebar"], lightcolor=c["sidebar"], darkcolor=c["sidebar"],
        focuscolor=c["focus"], font=f["row"], padding=m["nav_pad"],
        relief="flat", borderwidth=0, anchor="w",
    )
    style.map(
        f"{_P}.Nav.TButton",
        background=[("disabled", c["sidebar"]), ("selected", c["accent_soft"]),
                    ("pressed", c["accent_soft"]), ("active", c["surface"])],
        foreground=[("disabled", c["disabled"]), ("selected", c["text"]),
                    ("active", c["text"])],
        bordercolor=[("focus", c["focus"])],
        lightcolor=[("selected", c["accent_soft"]), ("pressed", c["accent_soft"]),
                    ("active", c["surface"])],
        darkcolor=[("selected", c["accent_soft"]), ("pressed", c["accent_soft"]),
                   ("active", c["surface"])],
    )

    style.configure(
        f"{_P}.TEntry", fieldbackground=c["field"], background=c["field"],
        foreground=c["text"], bordercolor=c["field_border"],
        lightcolor=c["field"], darkcolor=c["field"], insertcolor=c["text"],
        padding=m["field_pad"], borderwidth=m["border_width"], relief="flat",
        selectbackground=c["selection"], selectforeground=c["selection_text"],
    )
    style.map(
        f"{_P}.TEntry",
        fieldbackground=[("disabled", c["field_disabled"]),
                         ("readonly", c["field_disabled"])],
        foreground=[("disabled", c["disabled"])],
        bordercolor=[("focus", c["focus"]), ("hover", c["border"])],
        lightcolor=[("focus", c["focus"])], darkcolor=[("focus", c["focus"])],
    )
    style.configure(
        f"{_P}.TCombobox", fieldbackground=c["field"], background=c["field"],
        foreground=c["text"], bordercolor=c["field_border"],
        lightcolor=c["field"], darkcolor=c["field"], arrowcolor=c["secondary"],
        arrowsize=12, padding=m["field_pad"], borderwidth=m["border_width"],
        relief="flat", selectbackground=c["selection"],
        selectforeground=c["selection_text"], insertcolor=c["text"],
    )
    style.map(
        f"{_P}.TCombobox",
        fieldbackground=[("disabled", c["field_disabled"]), ("readonly", c["field"])],
        foreground=[("disabled", c["disabled"])],
        arrowcolor=[("disabled", c["disabled"]), ("active", c["text"])],
        bordercolor=[("focus", c["focus"]), ("active", c["border"])],
        lightcolor=[("focus", c["focus"])], darkcolor=[("focus", c["focus"])],
    )
    style.configure(
        f"{_P}.TSpinbox", fieldbackground=c["field"], background=c["field"],
        foreground=c["text"], bordercolor=c["field_border"],
        lightcolor=c["field"], darkcolor=c["field"], arrowcolor=c["secondary"],
        arrowsize=11, padding=m["field_pad"], borderwidth=m["border_width"],
        relief="flat", insertcolor=c["text"], selectbackground=c["selection"],
        selectforeground=c["selection_text"],
    )
    style.map(
        f"{_P}.TSpinbox",
        fieldbackground=[("disabled", c["field_disabled"])],
        foreground=[("disabled", c["disabled"])],
        arrowcolor=[("disabled", c["disabled"]), ("active", c["text"])],
        bordercolor=[("focus", c["focus"])],
        lightcolor=[("focus", c["focus"])], darkcolor=[("focus", c["focus"])],
    )

    for name, surface in ((f"{_P}.TCheckbutton", c["surface"]),
                          (f"{_P}.Muted.TCheckbutton", c["muted"]),
                          (f"{_P}.Shared.TCheckbutton", c["shared_bg"]),
                          (f"{_P}.TRadiobutton", c["surface"])):
        style.configure(
            name, background=surface, foreground=c["text"], font=f["body"],
            focuscolor=c["focus"], indicatorbackground=c["field"],
            indicatorforeground=c["accent"], indicatormargin=(0, 0, 6, 0),
            bordercolor=c["field_border"], lightcolor=c["field"],
            darkcolor=c["field"], padding=(0, 2),
        )
        style.map(
            name,
            background=[("active", surface)],
            foreground=[("disabled", c["disabled"])],
            indicatorbackground=[("disabled", c["field_disabled"]),
                                 ("selected", c["accent"]),
                                 ("pressed", c["accent_pressed"]),
                                 ("active", c["field"])],
            indicatorforeground=[("disabled", c["disabled"]),
                                 ("selected", c["inverse"])],
            bordercolor=[("focus", c["focus"]), ("selected", c["accent"]),
                         ("active", c["border"])],
        )

    style.configure(f"{_P}.TLabelframe", background=c["surface"],
                    bordercolor=c["border"], lightcolor=c["surface"],
                    darkcolor=c["surface"], borderwidth=m["border_width"],
                    relief="solid", padding=m["card_pad"])
    # The section caption reads like TTS's native LabelFrame caption: the body
    # font in the ordinary text color, not a smaller bold secondary heading.
    style.configure(f"{_P}.TLabelframe.Label", background=c["surface"],
                    foreground=c["text"], font=f["section"])
    style.configure(f"{_P}.Shared.TLabelframe", background=c["shared_bg"],
                    bordercolor=c["shared_border"], lightcolor=c["shared_bg"],
                    darkcolor=c["shared_bg"], borderwidth=m["border_width"],
                    relief="solid", padding=m["card_pad"])
    style.configure(f"{_P}.Shared.TLabelframe.Label", background=c["shared_bg"],
                    foreground=c["shared_header"], font=f["subheading"])

    style.configure(f"{_P}.TNotebook", background=c["surface"],
                    bordercolor=c["border"], lightcolor=c["surface"],
                    darkcolor=c["surface"], borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure(f"{_P}.TNotebook.Tab", background=c["surface"],
                    foreground=c["secondary"], font=f["body"], padding=m["tab_pad"],
                    bordercolor=c["border"], lightcolor=c["surface"],
                    darkcolor=c["surface"], focuscolor=c["focus"], borderwidth=0)
    style.map(
        f"{_P}.TNotebook.Tab",
        background=[("selected", c["elevated"]), ("active", c["elevated"])],
        foreground=[("selected", c["text"]), ("active", c["text"]),
                    ("disabled", c["disabled"])],
        lightcolor=[("selected", c["elevated"]), ("active", c["elevated"])],
        darkcolor=[("selected", c["elevated"]), ("active", c["elevated"])],
    )

    style.configure(f"{_P}.Horizontal.TProgressbar",
                    background=c["accent"], troughcolor=c["field"],
                    bordercolor=c["border"], lightcolor=c["accent"],
                    darkcolor=c["accent"], borderwidth=0,
                    thickness=m["progress_thickness"])
    for name in (f"{_P}.Vertical.TScrollbar", f"{_P}.Horizontal.TScrollbar"):
        style.configure(name, background=c["scroll_thumb"],
                        troughcolor=c["scroll_trough"], bordercolor=c["scroll_trough"],
                        lightcolor=c["scroll_thumb"], darkcolor=c["scroll_thumb"],
                        arrowcolor=c["secondary"], borderwidth=0,
                        arrowsize=m["scroll_width"], gripcount=0,
                        width=m["scroll_width"])
        style.map(
            name,
            background=[("disabled", c["scroll_trough"]), ("pressed", c["accent"]),
                        ("active", c["scroll_thumb_hover"])],
            arrowcolor=[("disabled", c["disabled"]), ("active", c["text"])],
            lightcolor=[("active", c["scroll_thumb_hover"])],
            darkcolor=[("active", c["scroll_thumb_hover"])],
        )

    style.configure(f"{_P}.Treeview", background=c["field"],
                    fieldbackground=c["field"], foreground=c["text"],
                    bordercolor=c["field_border"], lightcolor=c["field"],
                    darkcolor=c["field"], borderwidth=m["border_width"],
                    relief="flat", font=f["row"], rowheight=m["tree_row_height"])
    style.map(f"{_P}.Treeview",
              background=[("selected", c["selection"])],
              foreground=[("selected", c["selection_text"]),
                          ("disabled", c["disabled"])])
    style.configure(f"{_P}.Treeview.Heading", background=c["elevated"],
                    foreground=c["secondary"], font=f["section"],
                    bordercolor=c["border"], lightcolor=c["elevated"],
                    darkcolor=c["elevated"], relief="flat",
                    padding=(m["gap_sm"], m["gap_xs"]))
    style.map(f"{_P}.Treeview.Heading",
              background=[("active", c["border"])],
              foreground=[("active", c["text"])])

    style.configure(f"{_P}.TSeparator", background=c["border"])


# ---------------------------------------------------------------------------
# the bundle
# ---------------------------------------------------------------------------


def apply_native_appearance(window: tk.Misc, bundle: dict) -> bool:
    """Match one app-owned Aqua window to the app setting, keeping native controls.

    Tk 8.6's documented MacWindowStyle appearance command operates per window.
    Unsupported/older Tk builds and other window systems are harmless no-ops.
    https://github.com/tcltk/tk/blob/core-8-6-branch/macosx/README
    """
    try:
        if window.tk.call("tk", "windowingsystem") != "aqua":
            return False
        native = "darkaqua" if bundle.get("appearance") == DARK else "aqua"
        top = window.winfo_toplevel()
        pending = getattr(top, "_compact_native_map_binding", None)
        if pending is not None:
            top.unbind("<Map>", pending)
            top._compact_native_map_binding = None
        previous = window.tk.call("tk::unsupported::MacWindowStyle", "appearance",
                                  str(top), native)
        if previous == "":
            # Tk's WmWinAppearance silently returns empty before an NSWindow
            # exists. Retry once when this window maps, without running an
            # event loop inside a half-built launcher/dialog constructor.
            def on_map(event):
                if event.widget is top:
                    apply_native_appearance(top, bundle)

            top._compact_native_map_binding = top.bind("<Map>", on_map, add="+")
            return False
        return True
    except tk.TclError:
        return False


def _refresh_native_windows(root: tk.Misc, bundle: dict) -> None:
    """Refresh already-open app windows, including modeless result/warning dialogs."""
    apply_native_appearance(root, bundle)

    def visit(widget):
        try:
            children = widget.winfo_children()
        except tk.TclError:
            return
        for child in children:
            if isinstance(child, tk.Toplevel):
                apply_native_appearance(child, bundle)
            # A Toplevel may be owned by a panel or another dialog's frame.
            visit(child)

    visit(root)


def _register_aqua_styles(style: ttk.Style, c: dict) -> dict[str, str]:
    """Native control inheritance, with named colors and one tinted Shared border.

    No control padding, fonts, indicator images or native control layouts change.
    The only cloned element is the Shared group's recolorable section border.
    """
    for key, color in {
        "window": "window", "surface": "surface", "card": "surface",
        "elevated": "elevated", "muted": "muted", "shared_surface": "shared_bg",
        "sidebar": "sidebar", "divider": "border", "toolbar": "window",
    }.items():
        style.configure(_AQUA_STYLES[key], background=c[color])
    for key, foreground in {
        "label": "text", "title": "text", "heading": "text", "subheading": "text",
        "section": "text", "secondary_label": "secondary", "status_label": "secondary",
        "link_label": "link", "success_label": "success", "warning_label": "warning",
        "danger_label": "danger", "muted_label": "secondary",
        "shared_header": "shared_header", "shared_label": "text",
        "shared_secondary": "secondary",
    }.items():
        shared = key.startswith("shared_")
        style.configure(_AQUA_STYLES[key], foreground=c[foreground],
                        background=c["shared_bg" if shared else "surface"])
        style.map(_AQUA_STYLES[key], foreground=[("disabled", c["disabled"])])
    style.configure(_AQUA_STYLES["treeview"], background=c["field"],
                    fieldbackground=c["field"], foreground=c["text"])
    style.map(_AQUA_STYLES["treeview"], background=[("selected", c["selection"])],
              foreground=[("selected", c["selection_text"])])
    shared = _AQUA_STYLES["shared_labelframe"]
    element = f"{_AQUA_STYLE_PREFIX}.Shared.border"
    if element not in style.element_names():
        style.element_create(element, "from", "clam", "Labelframe.border")
    style.layout(shared, [(element, {"sticky": "nswe"})])
    style.configure(shared, background=c["shared_bg"], bordercolor=c["shared_border"],
                    lightcolor=c["shared_bg"], darkcolor=c["shared_bg"],
                    borderwidth=1, relief="solid")
    style.configure(shared + ".Label", background=c["shared_bg"],
                    foreground=c["shared_header"])
    return dict(_AQUA_STYLES)


def build_bundle(style: ttk.Style, appearance: str | None = None, *,
                 platform: str | None = None, root: tk.Misc | None = None) -> dict:
    """Build (or refresh in place) the compact bundle for *appearance*.

    Never calls ``style.theme_use()`` and never touches ``ACT.*`` or a generic
    style name — the base theme a caller already applied (via
    ``ui_theme.apply_theme``) is left exactly as it was.

    Calling this again with the same ``style`` object is the state-preserving
    refresh path: every ``Compact.*`` style is reconfigured in place, so any
    widget already built with one repaints without being destroyed. Nothing
    here reads or writes Python-level widget state.

    On macOS, names inherit native Aqua controls; only semantic surface/label
    colors and the Shared section border are configured. The native window
    appearance and classic Tk colors follow the same resolved setting.
    """
    resolved = appearance if appearance in _VALID else get_appearance()
    branch = sys.platform if platform is None else platform
    colors = dict(_PALETTES[resolved])
    body = _default_font_size(root)

    if branch == "darwin":
        family = _mac_font_family(root) if root is not None else "Helvetica Neue"
        styles = _register_aqua_styles(style, colors)
    else:
        family = _classic_font_family(branch)
        _register_ttk_styles(style, colors, METRICS, _fonts(family, body))
        styles = dict(_STYLES)

    bundle = {
        "mode": "compact",
        "appearance": resolved,
        "platform": branch,
        "family": family,
        "fonts": _fonts(family, body),
        "colors": colors,
        "metrics": dict(METRICS),
        "styles": styles,
        "style_prefix": _AQUA_STYLE_PREFIX if branch == "darwin" else STYLE_PREFIX,
        "ttk_active": bool(styles),
    }
    if branch == "darwin" and root is not None:
        _refresh_native_windows(root, bundle)
    return bundle


# ---------------------------------------------------------------------------
# classic Tk widget coloring (Canvas/Listbox/Text — ttk cannot style these)
# ---------------------------------------------------------------------------

_TK_WIDGET_ROLES: dict[str, tuple[str, str]] = {
    "window": ("window", "text"), "surface": ("surface", "text"),
    "elevated": ("elevated", "text"), "muted": ("muted", "text"),
    "sidebar": ("sidebar", "text"), "shared": ("shared_bg", "text"),
    "field": ("field", "text"), "list": ("field", "text"),
    "text": ("field", "text"),
    # A white field in Light, as TTS's native log pane is.
    "log": ("field", "text"),
    "canvas": ("surface", "text"), "divider": ("border", "text"),
}


def style_tk_widget(widget, bundle: dict, role: str = "surface", **overrides):
    """Color a classic Tk widget from *bundle* — the ``ui_theme`` pattern,
    generalised to every platform since ``colors`` is always populated here.

    A no-op (returns ``{}``) when *bundle* carries no ``colors``, so a caller
    may call this unconditionally regardless of how the bundle was built.
    """
    colors = (bundle or {}).get("colors")
    if not colors:
        return {}
    if role not in _TK_WIDGET_ROLES:
        raise ValueError(
            f"unknown appearance role {role!r}; expected one of "
            f"{sorted(_TK_WIDGET_ROLES)}"
        )
    bg_key, fg_key = _TK_WIDGET_ROLES[role]
    opts = {
        "background": colors[bg_key], "foreground": colors[fg_key],
        "highlightbackground": colors["border"], "highlightcolor": colors["focus"],
        "highlightthickness": 0, "borderwidth": 0, "relief": "flat",
        "insertbackground": colors["text"], "selectbackground": colors["selection"],
        "selectforeground": colors["selection_text"],
        "inactiveselectbackground": colors["selection_inactive"],
        "disabledforeground": colors["disabled"], "troughcolor": colors["scroll_trough"],
        "activebackground": colors["elevated"], "activeforeground": colors["text"],
    }
    opts.update(overrides)
    try:
        supported = set(widget.keys())
    except tk.TclError:
        supported = set()
    applied = {k: v for k, v in opts.items() if k in supported}
    if applied:
        widget.configure(**applied)
    return applied


def style_combobox_popdown(combo, bundle: dict) -> bool:
    """Color a ``Compact.TCombobox``'s drop-down list from *bundle*.

    The list a combobox drops down is a classic Tk ``Listbox`` inside a popdown
    ``Toplevel`` that ttk builds on its own; no ttk style reaches it, so a Dark
    combobox would otherwise open a white list. ttk's own
    ``ttk::combobox::PopdownWindow`` returns (creating it if needed) that
    popdown, and its listbox is always ``<popdown>.f.l``. Calling this again
    after a toggle recolors the same listbox in place.

    Only where the compact ttk styles are active: on aqua the combobox is
    native and so is its menu. Returns whether anything was colored.
    """
    colors = (bundle or {}).get("colors")
    if (not colors or not (bundle or {}).get("ttk_active")
            or bundle.get("platform") == "darwin"):
        return False
    try:
        popdown = combo.tk.eval(f"ttk::combobox::PopdownWindow {combo}")
        combo.tk.call(
            f"{popdown}.f.l", "configure",
            "-background", colors["field"], "-foreground", colors["text"],
            "-selectbackground", colors["selection"],
            "-selectforeground", colors["selection_text"],
            "-highlightthickness", 0, "-borderwidth", 0)
    except tk.TclError:
        return False
    return True


# ---------------------------------------------------------------------------
# live refresh notification
# ---------------------------------------------------------------------------

#: Callbacks notified after a toggle, so a currently-open app-owned dialog can
#: re-apply its own raw ``Toplevel`` background (the one thing ttk style
#: mutation cannot reach) without losing any widget state. Each callback takes
#: the new bundle and must not raise; a dead window is the callback's own
#: problem to detect (e.g. via ``winfo_exists``), not this registry's.
_listeners: list[Callable[[dict], None]] = []


def register_listener(callback: Callable[[dict], None]) -> None:
    """Ask to be told about every future appearance change."""
    if callback not in _listeners:
        _listeners.append(callback)


def unregister_listener(callback: Callable[[dict], None]) -> None:
    """Stop being told — call this when the listening window closes."""
    try:
        _listeners.remove(callback)
    except ValueError:
        pass


def notify_listeners(bundle: dict) -> None:
    """Tell every registered listener about *bundle*. Never raises."""
    for callback in list(_listeners):
        try:
            callback(bundle)
        except Exception:
            continue


def toggle_appearance(style: ttk.Style, *, platform: str | None = None,
                      root: tk.Misc | None = None) -> dict:
    """Flip the stored setting, refresh the ``Compact.*`` styles in place, tell
    every registered listener, and return the new bundle.

    This is the one call a shell toggle button needs: ``ttk.Style.configure``
    repaints every already-built widget that names a ``Compact.*`` style with
    no destruction and no lost state, and :func:`notify_listeners` covers the
    one thing that mutation cannot reach — a Toplevel's own raw background.
    """
    new_value = toggle_stored_appearance()
    bundle = build_bundle(style, new_value, platform=platform, root=root)
    notify_listeners(bundle)
    return bundle
