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
- **win32** — ``mode="windows"``: the ``vista`` base theme is *kept* so every
  panel that has not been converted still renders exactly as it did before
  v0.6.0, and a dark design system is layered on top as a set of
  ``ACT``-namespaced ttk styles plus centralized semantic colors, metrics and
  fonts. Nothing in the bundle is applied to a widget automatically — a panel
  opts in by naming an ``ACT.*`` style or by calling ``style_tk_widget``.
- **everything else** — the historical classic look: ``clam`` +
  TkDefaultFont, ``colors``/``metrics`` ``None``. Unchanged.

Fonts on macOS use ``.AppleSystemUIFont`` (San Francisco). SF Pro Text/Display
are NOT installed as named font families on macOS (verified live on macOS 26 /
Tk 9.0.3), so the system-font alias is the sanctioned way to get SF, with
"Helvetica Neue" as the fallback for older Tk builds that don't resolve it.

Alpha-based semantic colors (separators, secondary labels) flatten to their
base color through ``winfo_rgb``, so those shades are computed blends instead.

Why the Windows dark styles clone ``clam`` elements
---------------------------------------------------
``vista`` draws buttons, entries, comboboxes, scrollbars, notebook tabs and
Treeview headings with native Windows theme parts that ignore ``-background``
and ``-foreground``; a dark palette simply does not stick to them. Switching
the whole application to ``clam`` *would* recolor, but it would also silently
restyle the five tool panels this drop must leave alone.

So the base theme stays ``vista`` and each recolorable element is cloned into
it under an ``ACT.`` prefix (``ttk::style element create ACT.Button.border
from clam Button.border``). The ``ACT.*`` styles are then given layouts built
from those clones. Generic ``TButton``/``TEntry``/``Treeview``/... are never
touched, so an unconverted panel keeps its native vista rendering while a
converted one gets a fully colorable dark control set from the same widget
toolkit. ``tests/test_ui_theme.py`` asserts that isolation.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

DEFAULT_GEOMETRY = "1024x720"
MIN_SIZE = (920, 600)

#: Every ttk style this module registers for Windows begins with this prefix.
#: Nothing outside the prefix is created, redefined or configured, which is
#: what keeps the unconverted panels on their native vista rendering.
WINDOWS_STYLE_PREFIX = "ACT"


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


# ---------------------------------------------------------------------------
# Windows design system (v0.6.0 Drop 1)
# ---------------------------------------------------------------------------

#: Semantic Windows color roles. Panels must read these through the theme
#: bundle (``theme["colors"]["accent"]``) or through an ``ACT.*`` ttk style —
#: never re-declare a hex literal in a panel.
_WINDOWS_COLORS: dict[str, str | bool] = {
    # --- surfaces, back to front -------------------------------------------
    "window": "#0f1319",        # application background
    "sidebar": "#151b24",       # navigation rail
    "surface": "#1a212b",       # primary surface / card
    "elevated": "#212a36",      # elevated surface (popover, log, toolbar)
    "muted": "#17222f",         # muted surface (Shared Metadata group)
    "border": "#2b3542",        # card + control border
    "divider": "#232c38",       # hairline rule inside a surface
    # --- text ---------------------------------------------------------------
    "text": "#e8edf4",          # primary text
    "secondary": "#a3b0c2",     # secondary / supporting text
    "disabled": "#6d7a8c",      # disabled text (>=3:1 on every surface above)
    "inverse": "#0b0f14",       # text drawn on an accent fill
    # --- accent + focus -----------------------------------------------------
    "accent": "#4f8ff7",
    "accent_hover": "#6ba2fa",
    "accent_pressed": "#3a76d8",
    "accent_soft": "#1e3350",   # tinted fill for selected nav rows
    "focus": "#8ab6ff",         # keyboard focus ring, readable on every surface
    "link": "#6ba2fa",
    # --- status -------------------------------------------------------------
    "success": "#4cb782",
    "warning": "#d9a441",
    "danger": "#e0645c",
    "danger_hover": "#ec7a72",
    "danger_pressed": "#c24f48",
    # --- inputs, lists, text areas -----------------------------------------
    "field": "#141a22",
    "field_disabled": "#1a212b",
    "field_border": "#33404f",
    "selection": "#2b5488",
    "selection_text": "#ffffff",
    "selection_inactive": "#243a55",
    # --- scrollbars ---------------------------------------------------------
    "scroll_trough": "#151b24",
    "scroll_thumb": "#39465a",
    "scroll_thumb_hover": "#4a5a72",
    # --- Shared Metadata surface (the drop's distinct batch-wide treatment) --
    "shared_bg": "#17222f",
    "shared_border": "#3a5a80",
    "shared_header": "#9cc2f5",
    # --- meta ---------------------------------------------------------------
    "is_dark": True,
}

#: Spacing, sizing and density tokens. Same rule as the colors: no panel-local
#: magic numbers.
_WINDOWS_METRICS: dict[str, object] = {
    # shell
    # 180, not 232: Phase 2 measured the rail costing the tool panels 110px of
    # content width against the classic shell, which clipped a primary action at
    # the 920x600 minimum. 180 recovers 52px and still leaves ~44px of slack
    # after the longest tool name at 125% scaling (maintainer-approved, Phase 3).
    "sidebar_width": 180,
    "row_height": 34,
    "row_padx": 12,
    "row_gap": 2,
    "sidebar_pad": 10,
    "toolbar_height": 52,
    "content_pad": 16,
    "status_pad": (14, 6),
    "content_max_width": 1180,
    # cards / sections
    "card_pad": 14,
    "card_gap": 12,
    "section_gap": 18,
    # spacing scale
    "gap_xs": 4,
    "gap_sm": 8,
    "gap_md": 12,
    "gap_lg": 18,
    "gap_xl": 26,
    # controls
    "field_pad": (10, 6),
    "button_pad": (14, 7),
    "nav_pad": (12, 8),
    "tab_pad": (16, 8),
    "border_width": 1,
    "focus_width": 1,
    "scroll_width": 13,
    "progress_thickness": 10,
    "tree_row_height": 26,
}

#: Semantic name -> registered ttk style name. Panels should look styles up
#: here (``theme["styles"]["primary_button"]``) so a later rename stays in this
#: module.
_WINDOWS_STYLES: dict[str, str] = {
    # frames / surfaces
    "window": "ACT.Window.TFrame",
    "surface": "ACT.TFrame",
    "card": "ACT.Card.TFrame",
    "elevated": "ACT.Elevated.TFrame",
    "muted": "ACT.Muted.TFrame",
    "shared_surface": "ACT.Shared.TFrame",
    "sidebar": "ACT.Sidebar.TFrame",
    "divider": "ACT.Divider.TFrame",
    "toolbar": "ACT.Toolbar.TFrame",
    # labels
    "label": "ACT.TLabel",
    "title": "ACT.Title.TLabel",
    "heading": "ACT.Heading.TLabel",
    "subheading": "ACT.Subheading.TLabel",
    "section": "ACT.Section.TLabel",
    "secondary_label": "ACT.Secondary.TLabel",
    "status_label": "ACT.Status.TLabel",
    "link_label": "ACT.Link.TLabel",
    "success_label": "ACT.Success.TLabel",
    "warning_label": "ACT.Warning.TLabel",
    "danger_label": "ACT.Danger.TLabel",
    "sidebar_label": "ACT.Sidebar.TLabel",
    "muted_label": "ACT.Muted.TLabel",
    "shared_header": "ACT.SharedHeader.TLabel",
    "shared_label": "ACT.Shared.TLabel",
    "shared_secondary": "ACT.SharedSecondary.TLabel",
    # buttons
    "button": "ACT.TButton",
    "primary_button": "ACT.Primary.TButton",
    "danger_button": "ACT.Danger.TButton",
    "ghost_button": "ACT.Ghost.TButton",
    "nav_button": "ACT.Nav.TButton",
    # inputs
    "entry": "ACT.TEntry",
    "combobox": "ACT.TCombobox",
    "spinbox": "ACT.TSpinbox",
    "checkbutton": "ACT.TCheckbutton",
    "radiobutton": "ACT.TRadiobutton",
    "muted_checkbutton": "ACT.Muted.TCheckbutton",
    "shared_checkbutton": "ACT.Shared.TCheckbutton",
    # containers / indicators
    "labelframe": "ACT.TLabelframe",
    "shared_labelframe": "ACT.Shared.TLabelframe",
    "notebook": "ACT.TNotebook",
    "progressbar": "ACT.Horizontal.TProgressbar",
    "vscrollbar": "ACT.Vertical.TScrollbar",
    "hscrollbar": "ACT.Horizontal.TScrollbar",
    "treeview": "ACT.Treeview",
    "separator": "ACT.TSeparator",
}

#: ``clam`` elements cloned into the live theme under the ACT prefix. vista
#: draws these natively and ignores color options, so a clone is the only way
#: to recolor them without switching the whole application to clam.
_CLONED_ELEMENTS: tuple[str, ...] = (
    "Button.border",
    "Button.focus",
    "Entry.field",
    "Combobox.field",
    "Combobox.downarrow",
    "Spinbox.field",
    "Spinbox.uparrow",
    "Spinbox.downarrow",
    "Checkbutton.indicator",
    "Radiobutton.indicator",
    "Notebook.client",
    "Notebook.tab",
    "Horizontal.Progressbar.trough",
    "Horizontal.Progressbar.pbar",
    "Vertical.Scrollbar.trough",
    "Vertical.Scrollbar.thumb",
    "Vertical.Scrollbar.uparrow",
    "Vertical.Scrollbar.downarrow",
    "Horizontal.Scrollbar.trough",
    "Horizontal.Scrollbar.thumb",
    "Horizontal.Scrollbar.leftarrow",
    "Horizontal.Scrollbar.rightarrow",
    "Treeview.field",
    "Treeitem.indicator",
    "Treeheading.cell",
    "Treeheading.border",
    "Labelframe.border",
    "Separator.separator",
)

_A = WINDOWS_STYLE_PREFIX  # keeps the layout tables readable

#: Layouts for the ACT styles, expressed with the cloned elements above. The
#: shapes are clam's, captured verbatim; only the element names are prefixed.
_ACT_LAYOUTS: dict[str, list] = {
    "ACT.TButton": [
        (f"{_A}.Button.border", {"sticky": "nswe", "border": "1", "children": [
            (f"{_A}.Button.focus", {"sticky": "nswe", "children": [
                ("Button.padding", {"sticky": "nswe", "children": [
                    ("Button.label", {"sticky": "nswe"})]})]})]})],
    "ACT.TEntry": [
        (f"{_A}.Entry.field", {"sticky": "nswe", "border": "1", "children": [
            ("Entry.padding", {"sticky": "nswe", "children": [
                ("Entry.textarea", {"sticky": "nswe"})]})]})],
    "ACT.TCombobox": [
        (f"{_A}.Combobox.downarrow", {"side": "right", "sticky": "ns"}),
        (f"{_A}.Combobox.field", {"sticky": "nswe", "children": [
            ("Combobox.padding", {"sticky": "nswe", "children": [
                ("Combobox.textarea", {"sticky": "nswe"})]})]})],
    "ACT.TSpinbox": [
        (f"{_A}.Spinbox.field", {"side": "top", "sticky": "we", "children": [
            ("null", {"side": "right", "sticky": "", "children": [
                (f"{_A}.Spinbox.uparrow", {"side": "top", "sticky": "e"}),
                (f"{_A}.Spinbox.downarrow", {"side": "bottom", "sticky": "e"})]}),
            ("Spinbox.padding", {"sticky": "nswe", "children": [
                ("Spinbox.textarea", {"sticky": "nswe"})]})]})],
    "ACT.TCheckbutton": [
        ("Checkbutton.padding", {"sticky": "nswe", "children": [
            (f"{_A}.Checkbutton.indicator", {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nswe"})]})]})],
    "ACT.TRadiobutton": [
        ("Radiobutton.padding", {"sticky": "nswe", "children": [
            (f"{_A}.Radiobutton.indicator", {"side": "left", "sticky": ""}),
            ("Radiobutton.focus", {"side": "left", "sticky": "", "children": [
                ("Radiobutton.label", {"sticky": "nswe"})]})]})],
    "ACT.TNotebook": [(f"{_A}.Notebook.client", {"sticky": "nswe"})],
    "ACT.TNotebook.Tab": [
        (f"{_A}.Notebook.tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                ("Notebook.focus", {"side": "top", "sticky": "nswe", "children": [
                    ("Notebook.label", {"side": "top", "sticky": ""})]})]})]})],
    "ACT.Horizontal.TProgressbar": [
        (f"{_A}.Horizontal.Progressbar.trough", {"sticky": "nswe", "children": [
            (f"{_A}.Horizontal.Progressbar.pbar",
             {"side": "left", "sticky": "ns"})]})],
    "ACT.Vertical.TScrollbar": [
        (f"{_A}.Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            (f"{_A}.Vertical.Scrollbar.uparrow", {"side": "top", "sticky": ""}),
            (f"{_A}.Vertical.Scrollbar.downarrow", {"side": "bottom", "sticky": ""}),
            (f"{_A}.Vertical.Scrollbar.thumb", {"sticky": "nswe"})]})],
    "ACT.Horizontal.TScrollbar": [
        (f"{_A}.Horizontal.Scrollbar.trough", {"sticky": "we", "children": [
            (f"{_A}.Horizontal.Scrollbar.leftarrow", {"side": "left", "sticky": ""}),
            (f"{_A}.Horizontal.Scrollbar.rightarrow", {"side": "right", "sticky": ""}),
            (f"{_A}.Horizontal.Scrollbar.thumb", {"sticky": "nswe"})]})],
    "ACT.Treeview": [
        (f"{_A}.Treeview.field", {"sticky": "nswe", "border": "1", "children": [
            ("Treeview.padding", {"sticky": "nswe", "children": [
                ("Treeview.treearea", {"sticky": "nswe"})]})]})],
    "ACT.Treeview.Item": [
        ("Treeitem.padding", {"sticky": "nswe", "children": [
            (f"{_A}.Treeitem.indicator", {"side": "left", "sticky": ""}),
            ("Treeitem.image", {"side": "left", "sticky": ""}),
            ("Treeitem.text", {"sticky": "nswe"})]})],
    "ACT.Treeview.Heading": [
        (f"{_A}.Treeheading.cell", {"sticky": "nswe"}),
        (f"{_A}.Treeheading.border", {"sticky": "nswe", "children": [
            ("Treeheading.padding", {"sticky": "nswe", "children": [
                ("Treeheading.image", {"side": "right", "sticky": ""}),
                ("Treeheading.text", {"sticky": "we"})]})]})],
    "ACT.TLabelframe": [(f"{_A}.Labelframe.border", {"sticky": "nswe"})],
    "ACT.TLabelframe.Label": [
        ("Label.fill", {"sticky": "nswe", "children": [
            ("Label.text", {"sticky": "nswe"})]})],
    "ACT.TSeparator": [(f"{_A}.Separator.separator", {"sticky": "nswe"})],
}

# ttk resolves a style name by stripping leading components, so
# "ACT.Primary.TButton" falls back to plain "TButton" — the *native vista*
# button — unless the variant is given its own layout. Without this the dark
# fill would silently not stick to any variant style.
for _variant, _base in (
    ("ACT.Primary.TButton", "ACT.TButton"),
    ("ACT.Danger.TButton", "ACT.TButton"),
    ("ACT.Ghost.TButton", "ACT.TButton"),
    ("ACT.Nav.TButton", "ACT.TButton"),
    ("ACT.Muted.TCheckbutton", "ACT.TCheckbutton"),
    ("ACT.Shared.TCheckbutton", "ACT.TCheckbutton"),
    ("ACT.Shared.TLabelframe", "ACT.TLabelframe"),
    ("ACT.Shared.TLabelframe.Label", "ACT.TLabelframe.Label"),
):
    _ACT_LAYOUTS[_variant] = _ACT_LAYOUTS[_base]
del _variant, _base


def _windows_fonts(family: str) -> dict[str, tuple]:
    """The Windows type scale. ``heading``/``button`` keep their historical
    values so the bundle stays drop-in compatible with the classic launcher."""
    mono = "Consolas"
    return {
        "title": (family, 17, "bold"),
        "heading": (family, 15, "bold"),
        "subheading": (family, 11, "bold"),
        "section": (family, 9, "bold"),
        "body": (family, 10),
        "body_bold": (family, 10, "bold"),
        "row": (family, 10),
        "small": (family, 9),
        "status": (family, 9),
        "button": (family, 10),
        "mono": (mono, 9),
    }


def _windows_base_theme(style: ttk.Style) -> str:
    """Keep the native Windows base theme so unconverted panels don't change.

    ``vista`` is the real target. ``clam`` is the fallback when this runs on a
    host without it (a monkeypatched-platform test on macOS/Linux, or a Tk
    build without the vista engine) — theme application must never raise just
    because the preferred native theme is missing.
    """
    for name in ("vista", "clam", "default"):
        try:
            style.theme_use(name)
            return name
        except tk.TclError:
            continue
    try:
        return style.theme_use()
    except tk.TclError:
        return "unknown"


def _clone_elements(style: ttk.Style) -> None:
    """Clone the recolorable clam elements into the live theme, once.

    ``element_create`` raises "Duplicate element" on a second call, so a
    repeated ``apply_theme`` (the launcher probes the theme, tests re-apply)
    must swallow that. A genuinely missing source element is also non-fatal:
    the style that needs it simply fails to lay out and is skipped, which the
    tests detect rather than the user.
    """
    try:
        existing = set(style.element_names())
    except tk.TclError:
        existing = set()
    for element in _CLONED_ELEMENTS:
        target = f"{WINDOWS_STYLE_PREFIX}.{element}"
        if target in existing:
            continue
        try:
            style.element_create(target, "from", "clam", element)
        except tk.TclError:
            continue


def _register_windows_styles(
    style: ttk.Style, c: dict, m: dict, f: dict
) -> None:
    """Define every ``ACT.*`` style. No generic style is created or modified."""
    _clone_elements(style)

    for name, layout in _ACT_LAYOUTS.items():
        try:
            style.layout(name, layout)
        except tk.TclError:
            # A missing cloned element on an exotic Tk build: leave the style
            # undefined rather than half-drawn. test_ui_theme asserts the set
            # that must exist on a supported host.
            continue

    # --- surfaces ----------------------------------------------------------
    style.configure("ACT.TFrame", background=c["surface"])
    style.configure("ACT.Window.TFrame", background=c["window"])
    style.configure("ACT.Card.TFrame", background=c["surface"])
    style.configure("ACT.Elevated.TFrame", background=c["elevated"])
    style.configure("ACT.Muted.TFrame", background=c["muted"])
    # The Shared Metadata surface gets its own frame/label/toggle family rather
    # than borrowing the "muted" ones: the two tokens happen to be equal today,
    # and a converted panel must not silently depend on that.
    style.configure("ACT.Shared.TFrame", background=c["shared_bg"])
    style.configure("ACT.Sidebar.TFrame", background=c["sidebar"])
    style.configure("ACT.Toolbar.TFrame", background=c["window"])
    # A 1px hairline: pack/grid this frame with height=1 or width=1.
    style.configure("ACT.Divider.TFrame", background=c["border"])

    # --- labels ------------------------------------------------------------
    style.configure("ACT.TLabel", background=c["surface"],
                    foreground=c["text"], font=f["body"])
    style.configure("ACT.Title.TLabel", background=c["window"],
                    foreground=c["text"], font=f["title"])
    style.configure("ACT.Heading.TLabel", background=c["surface"],
                    foreground=c["text"], font=f["heading"])
    style.configure("ACT.Subheading.TLabel", background=c["surface"],
                    foreground=c["text"], font=f["subheading"])
    style.configure("ACT.Section.TLabel", background=c["surface"],
                    foreground=c["secondary"], font=f["section"])
    style.configure("ACT.Secondary.TLabel", background=c["surface"],
                    foreground=c["secondary"], font=f["body"])
    style.configure("ACT.Status.TLabel", background=c["window"],
                    foreground=c["secondary"], font=f["status"])
    style.configure("ACT.Link.TLabel", background=c["window"],
                    foreground=c["link"], font=f["status"])
    style.configure("ACT.Success.TLabel", background=c["surface"],
                    foreground=c["success"], font=f["body"])
    style.configure("ACT.Warning.TLabel", background=c["surface"],
                    foreground=c["warning"], font=f["body"])
    style.configure("ACT.Danger.TLabel", background=c["surface"],
                    foreground=c["danger"], font=f["body"])
    style.configure("ACT.Sidebar.TLabel", background=c["sidebar"],
                    foreground=c["secondary"], font=f["section"])
    style.configure("ACT.Muted.TLabel", background=c["muted"],
                    foreground=c["text"], font=f["body"])
    style.configure("ACT.SharedHeader.TLabel", background=c["shared_bg"],
                    foreground=c["shared_header"], font=f["subheading"])
    style.configure("ACT.Shared.TLabel", background=c["shared_bg"],
                    foreground=c["text"], font=f["body"])
    style.configure("ACT.SharedSecondary.TLabel", background=c["shared_bg"],
                    foreground=c["secondary"], font=f["small"])
    for name in ("ACT.TLabel", "ACT.Heading.TLabel", "ACT.Subheading.TLabel",
                 "ACT.Secondary.TLabel", "ACT.Muted.TLabel",
                 "ACT.Shared.TLabel", "ACT.SharedSecondary.TLabel"):
        style.map(name, foreground=[("disabled", c["disabled"])])

    # --- buttons -----------------------------------------------------------
    # Secondary (default) button: quiet surface fill, accent focus ring.
    style.configure(
        "ACT.TButton", background=c["elevated"], foreground=c["text"],
        bordercolor=c["border"], lightcolor=c["elevated"],
        darkcolor=c["elevated"], focuscolor=c["focus"], font=f["button"],
        padding=m["button_pad"], relief="flat", borderwidth=m["border_width"],
        anchor="center",
    )
    style.map(
        "ACT.TButton",
        background=[("disabled", c["surface"]), ("pressed", c["border"]),
                    ("active", c["border"]), ("selected", c["accent_soft"])],
        foreground=[("disabled", c["disabled"])],
        bordercolor=[("focus", c["focus"]), ("active", c["field_border"])],
        lightcolor=[("pressed", c["border"]), ("active", c["border"])],
        darkcolor=[("pressed", c["border"]), ("active", c["border"])],
    )
    # Primary action.
    style.configure(
        "ACT.Primary.TButton", background=c["accent"], foreground=c["inverse"],
        bordercolor=c["accent"], lightcolor=c["accent"], darkcolor=c["accent"],
        focuscolor=c["inverse"], font=f["button"], padding=m["button_pad"],
        relief="flat", borderwidth=m["border_width"], anchor="center",
    )
    style.map(
        "ACT.Primary.TButton",
        background=[("disabled", c["surface"]), ("pressed", c["accent_pressed"]),
                    ("active", c["accent_hover"])],
        foreground=[("disabled", c["disabled"])],
        bordercolor=[("disabled", c["border"]), ("focus", c["focus"]),
                     ("pressed", c["accent_pressed"]),
                     ("active", c["accent_hover"])],
        lightcolor=[("pressed", c["accent_pressed"]), ("active", c["accent_hover"])],
        darkcolor=[("pressed", c["accent_pressed"]), ("active", c["accent_hover"])],
    )
    # Destructive action (Clear All Tags, Remove Series Numbering, ...).
    style.configure(
        "ACT.Danger.TButton", background=c["surface"], foreground=c["danger"],
        bordercolor=c["danger"], lightcolor=c["surface"], darkcolor=c["surface"],
        focuscolor=c["focus"], font=f["button"], padding=m["button_pad"],
        relief="flat", borderwidth=m["border_width"], anchor="center",
    )
    style.map(
        "ACT.Danger.TButton",
        background=[("disabled", c["surface"]), ("pressed", c["danger_pressed"]),
                    ("active", c["danger"])],
        foreground=[("disabled", c["disabled"]), ("pressed", c["selection_text"]),
                    ("active", c["selection_text"])],
        bordercolor=[("disabled", c["border"]), ("focus", c["focus"]),
                     ("pressed", c["danger_pressed"]), ("active", c["danger_hover"])],
        lightcolor=[("pressed", c["danger_pressed"]), ("active", c["danger"])],
        darkcolor=[("pressed", c["danger_pressed"]), ("active", c["danger"])],
    )
    # Borderless button for toolbars / inline actions.
    style.configure(
        "ACT.Ghost.TButton", background=c["window"], foreground=c["secondary"],
        bordercolor=c["window"], lightcolor=c["window"], darkcolor=c["window"],
        focuscolor=c["focus"], font=f["button"], padding=m["button_pad"],
        relief="flat", borderwidth=0, anchor="center",
    )
    style.map(
        "ACT.Ghost.TButton",
        background=[("disabled", c["window"]), ("pressed", c["surface"]),
                    ("active", c["surface"])],
        foreground=[("disabled", c["disabled"]), ("active", c["text"])],
        bordercolor=[("focus", c["focus"])],
        lightcolor=[("pressed", c["surface"]), ("active", c["surface"])],
        darkcolor=[("pressed", c["surface"]), ("active", c["surface"])],
    )
    # Sidebar navigation row. The launcher marks the active tool with the
    # standard ttk ``selected`` state flag rather than a second style.
    style.configure(
        "ACT.Nav.TButton", background=c["sidebar"], foreground=c["secondary"],
        bordercolor=c["sidebar"], lightcolor=c["sidebar"],
        darkcolor=c["sidebar"], focuscolor=c["focus"], font=f["row"],
        padding=m["nav_pad"], relief="flat", borderwidth=0, anchor="w",
    )
    style.map(
        "ACT.Nav.TButton",
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

    # --- text inputs -------------------------------------------------------
    style.configure(
        "ACT.TEntry", fieldbackground=c["field"], background=c["field"],
        foreground=c["text"],
        bordercolor=c["field_border"], lightcolor=c["field"],
        darkcolor=c["field"], insertcolor=c["text"], padding=m["field_pad"],
        borderwidth=m["border_width"], relief="flat",
        selectbackground=c["selection"], selectforeground=c["selection_text"],
    )
    style.map(
        "ACT.TEntry",
        fieldbackground=[("disabled", c["field_disabled"]),
                         ("readonly", c["field_disabled"])],
        foreground=[("disabled", c["disabled"])],
        bordercolor=[("focus", c["focus"]), ("hover", c["border"])],
        lightcolor=[("focus", c["focus"])],
        darkcolor=[("focus", c["focus"])],
    )
    style.configure(
        "ACT.TCombobox", fieldbackground=c["field"], background=c["field"],
        foreground=c["text"], bordercolor=c["field_border"],
        lightcolor=c["field"], darkcolor=c["field"], arrowcolor=c["secondary"],
        arrowsize=13, padding=m["field_pad"], borderwidth=m["border_width"],
        relief="flat", selectbackground=c["selection"],
        selectforeground=c["selection_text"], insertcolor=c["text"],
    )
    style.map(
        "ACT.TCombobox",
        fieldbackground=[("disabled", c["field_disabled"]),
                         ("readonly", c["field"])],
        foreground=[("disabled", c["disabled"])],
        arrowcolor=[("disabled", c["disabled"]), ("active", c["text"])],
        bordercolor=[("focus", c["focus"]), ("active", c["border"])],
        lightcolor=[("focus", c["focus"])],
        darkcolor=[("focus", c["focus"])],
    )
    style.configure(
        "ACT.TSpinbox", fieldbackground=c["field"], background=c["field"],
        foreground=c["text"], bordercolor=c["field_border"],
        lightcolor=c["field"], darkcolor=c["field"], arrowcolor=c["secondary"],
        arrowsize=12, padding=m["field_pad"], borderwidth=m["border_width"],
        relief="flat", insertcolor=c["text"],
        selectbackground=c["selection"], selectforeground=c["selection_text"],
    )
    style.map(
        "ACT.TSpinbox",
        fieldbackground=[("disabled", c["field_disabled"])],
        foreground=[("disabled", c["disabled"])],
        arrowcolor=[("disabled", c["disabled"]), ("active", c["text"])],
        bordercolor=[("focus", c["focus"])],
        lightcolor=[("focus", c["focus"])],
        darkcolor=[("focus", c["focus"])],
    )

    # --- toggles -----------------------------------------------------------
    for name, surface in (("ACT.TCheckbutton", c["surface"]),
                          ("ACT.Muted.TCheckbutton", c["muted"]),
                          ("ACT.Shared.TCheckbutton", c["shared_bg"]),
                          ("ACT.TRadiobutton", c["surface"])):
        style.configure(
            name, background=surface, foreground=c["text"], font=f["body"],
            focuscolor=c["focus"], indicatorbackground=c["field"],
            indicatorforeground=c["accent"], indicatormargin=(0, 0, 8, 0),
            bordercolor=c["field_border"], lightcolor=c["field"],
            darkcolor=c["field"], padding=(0, 3),
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

    # --- grouping containers ----------------------------------------------
    style.configure("ACT.TLabelframe", background=c["surface"],
                    bordercolor=c["border"], lightcolor=c["surface"],
                    darkcolor=c["surface"], borderwidth=m["border_width"],
                    relief="solid", padding=m["card_pad"])
    style.configure("ACT.TLabelframe.Label", background=c["surface"],
                    foreground=c["secondary"], font=f["section"])
    # The Shared Metadata surface: muted accent fill, accent border, accent
    # header — the batch-wide treatment this drop must make visibly distinct.
    style.configure("ACT.Shared.TLabelframe", background=c["shared_bg"],
                    bordercolor=c["shared_border"], lightcolor=c["shared_bg"],
                    darkcolor=c["shared_bg"], borderwidth=m["border_width"],
                    relief="solid", padding=m["card_pad"])
    style.configure("ACT.Shared.TLabelframe.Label", background=c["shared_bg"],
                    foreground=c["shared_header"], font=f["subheading"])

    # --- notebook (Summary / Details specimen in Phase 3) ------------------
    style.configure("ACT.TNotebook", background=c["surface"],
                    bordercolor=c["border"], lightcolor=c["surface"],
                    darkcolor=c["surface"], borderwidth=0,
                    tabmargins=(0, 0, 0, 0))
    style.configure("ACT.TNotebook.Tab", background=c["surface"],
                    foreground=c["secondary"], font=f["body"],
                    padding=m["tab_pad"], bordercolor=c["border"],
                    lightcolor=c["surface"], darkcolor=c["surface"],
                    focuscolor=c["focus"], borderwidth=0)
    style.map(
        "ACT.TNotebook.Tab",
        background=[("selected", c["elevated"]), ("active", c["elevated"])],
        foreground=[("selected", c["text"]), ("active", c["text"]),
                    ("disabled", c["disabled"])],
        lightcolor=[("selected", c["elevated"]), ("active", c["elevated"])],
        darkcolor=[("selected", c["elevated"]), ("active", c["elevated"])],
    )

    # --- progress / scrollbars --------------------------------------------
    style.configure("ACT.Horizontal.TProgressbar",
                    background=c["accent"], troughcolor=c["field"],
                    bordercolor=c["border"], lightcolor=c["accent"],
                    darkcolor=c["accent"], borderwidth=0,
                    thickness=m["progress_thickness"])
    for name in ("ACT.Vertical.TScrollbar", "ACT.Horizontal.TScrollbar"):
        style.configure(name, background=c["scroll_thumb"],
                        troughcolor=c["scroll_trough"],
                        bordercolor=c["scroll_trough"],
                        lightcolor=c["scroll_thumb"],
                        darkcolor=c["scroll_thumb"],
                        arrowcolor=c["secondary"], borderwidth=0,
                        arrowsize=m["scroll_width"], gripcount=0,
                        width=m["scroll_width"])
        style.map(
            name,
            background=[("disabled", c["scroll_trough"]),
                        ("pressed", c["accent"]),
                        ("active", c["scroll_thumb_hover"])],
            arrowcolor=[("disabled", c["disabled"]), ("active", c["text"])],
            lightcolor=[("active", c["scroll_thumb_hover"])],
            darkcolor=[("active", c["scroll_thumb_hover"])],
        )

    # --- treeview ----------------------------------------------------------
    style.configure("ACT.Treeview", background=c["field"],
                    fieldbackground=c["field"], foreground=c["text"],
                    bordercolor=c["field_border"], lightcolor=c["field"],
                    darkcolor=c["field"], borderwidth=m["border_width"],
                    relief="flat", font=f["row"],
                    rowheight=m["tree_row_height"])
    style.map("ACT.Treeview",
              background=[("selected", c["selection"])],
              foreground=[("selected", c["selection_text"]),
                          ("disabled", c["disabled"])])
    style.configure("ACT.Treeview.Heading", background=c["elevated"],
                    foreground=c["secondary"], font=f["section"],
                    bordercolor=c["border"], lightcolor=c["elevated"],
                    darkcolor=c["elevated"], relief="flat",
                    padding=(m["gap_sm"], m["gap_xs"]))
    style.map("ACT.Treeview.Heading",
              background=[("active", c["border"])],
              foreground=[("active", c["text"])])

    # --- separator ---------------------------------------------------------
    style.configure("ACT.TSeparator", background=c["border"])


def _apply_windows(root: tk.Tk, style: ttk.Style) -> dict:
    """Explicit Windows branch: native base theme + the ACT dark design system.

    This registers styles and returns tokens. It deliberately changes nothing
    that an existing widget already renders with, so a panel that has not been
    converted looks exactly as it did before this branch existed.
    """
    base = _windows_base_theme(style)
    family = _classic_font_family()
    colors = dict(_WINDOWS_COLORS)
    metrics = dict(_WINDOWS_METRICS)
    fonts = _windows_fonts(family)

    _register_windows_styles(style, colors, metrics, fonts)

    return {
        "mode": "windows",
        "base_theme": base,
        "family": family,
        # Kept at their historical values so the bundle stays a drop-in
        # replacement for the classic one until the shell is converted.
        "font_heading": (family, 15, "bold"),
        "font_button": (family, 11),
        "font_body": fonts["body"],
        "font_row": fonts["row"],
        "font_section": fonts["section"],
        "font_status": fonts["status"],
        "fonts": fonts,
        "geometry": DEFAULT_GEOMETRY,
        "min_size": MIN_SIZE,
        "colors": colors,
        "metrics": metrics,
        "styles": dict(_WINDOWS_STYLES),
        "style_prefix": WINDOWS_STYLE_PREFIX,
    }


#: Role -> (background token, foreground token) for classic Tk widgets.
_TK_WIDGET_ROLES: dict[str, tuple[str, str]] = {
    "window": ("window", "text"),
    "surface": ("surface", "text"),
    "elevated": ("elevated", "text"),
    "muted": ("muted", "text"),
    "sidebar": ("sidebar", "text"),
    "shared": ("shared_bg", "text"),
    "field": ("field", "text"),
    "list": ("field", "text"),
    "text": ("field", "text"),
    "log": ("elevated", "secondary"),
    "canvas": ("surface", "text"),
    "divider": ("border", "text"),
}


def style_tk_widget(widget, theme: dict, role: str = "surface", **overrides):
    """Apply the theme's tokens to a classic Tk widget ttk cannot style.

    ``Canvas``, ``Listbox``, ``Text``, ``Frame`` and friends are not ttk
    widgets, so scroll regions, log boxes and chapter editors have to be
    colored by hand. This is the one sanctioned way to do that — panels must
    not carry their own hex literals.

    Options the widget does not support are dropped, so the same call works
    for a ``Canvas`` (no ``foreground``) and a ``Text`` (no
    ``selectborderwidth`` concerns). ``overrides`` win over the role defaults.

    A no-op on any theme without a color bundle (macOS aqua chrome has its own
    palette; the Linux/other classic branch has none), so a panel may call it
    unconditionally.

    Returns the option dict that was applied, which is ``{}`` on a no-op.
    """
    if role not in _TK_WIDGET_ROLES:
        raise ValueError(
            f"unknown ui_theme role {role!r}; "
            f"expected one of {sorted(_TK_WIDGET_ROLES)}"
        )
    colors = (theme or {}).get("colors")
    if not colors or theme.get("mode") != "windows":
        return {}

    bg_key, fg_key = _TK_WIDGET_ROLES[role]
    opts = {
        "background": colors[bg_key],
        "foreground": colors[fg_key],
        "highlightbackground": colors["border"],
        "highlightcolor": colors["focus"],
        "highlightthickness": 0,
        "borderwidth": 0,
        "relief": "flat",
        "insertbackground": colors["text"],
        "selectbackground": colors["selection"],
        "selectforeground": colors["selection_text"],
        "inactiveselectbackground": colors["selection_inactive"],
        "disabledforeground": colors["disabled"],
        "troughcolor": colors["scroll_trough"],
        "activebackground": colors["elevated"],
        "activeforeground": colors["text"],
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

    The launcher builds its widgets exclusively from this dict. Each platform
    is routed explicitly — Windows is never inferred from "not macOS":

    - ``darwin`` -> ``mode="aqua"``  (Finder chrome palette + metrics)
    - ``win32``  -> ``mode="windows"`` (dark tokens + ACT ttk styles)
    - otherwise  -> ``mode="classic"`` (``colors``/``metrics`` are ``None``)

    Every mode returns the same bundle keys the launcher already reads, so a
    caller written against the classic bundle keeps working.
    """
    if sys.platform == "darwin":
        return _apply_darwin(root, style)
    if sys.platform == "win32":
        return _apply_windows(root, style)
    return _apply_classic(root, style)
