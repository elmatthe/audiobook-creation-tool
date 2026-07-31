"""Headless-guarded smoke tests for shared/ui_theme.py.

``apply_theme`` must apply without raising and hand back the fonts/metrics
contract the launcher builds from. All three platform branches are exercised
where possible: the current platform's real branch, plus the win32 and
Linux/other branches forced via a monkeypatched ``sys.platform``.

The Windows branch (v0.6.0 Drop 1) additionally has to prove *isolation*: it
registers a dark ``ACT.*`` design system on top of the native base theme
without redefining any generic style, because five tool panels are not being
converted and must keep rendering exactly as they do today.
"""

from __future__ import annotations

import sys

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import ui_theme  # noqa: E402

REQUIRED_KEYS = {"mode", "family", "font_heading", "font_button",
                 "geometry", "min_size", "colors", "metrics"}

#: Generic styles the five unconverted panels render with. Not one of them may
#: be created, reconfigured or re-laid-out by the Windows branch.
GENERIC_STYLES = (
    "TFrame", "TLabel", "TButton", "TEntry", "TCombobox", "TSpinbox",
    "TCheckbutton", "TRadiobutton", "TLabelframe", "TLabelframe.Label",
    "TNotebook", "TNotebook.Tab", "Treeview", "Treeview.Heading",
    "Horizontal.TProgressbar", "Vertical.TScrollbar", "Horizontal.TScrollbar",
    "TSeparator",
)


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # headless box with no display
        pytest.skip(f"Tk cannot open a display here: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def windows_theme(tk_root, monkeypatch):
    """(style, theme) for the Windows branch, forced on any host."""
    monkeypatch.setattr(sys, "platform", "win32")
    style = ttk.Style(tk_root)
    return style, ui_theme.apply_theme(tk_root, style)


def _luminance(hex_color: str) -> float:
    """WCAG relative luminance of '#rrggbb'."""
    def channel(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _snapshot_generic(style: ttk.Style) -> dict:
    out = {}
    for name in GENERIC_STYLES:
        try:
            layout = style.layout(name)
        except tk.TclError:
            layout = None
        out[name] = (
            layout,
            style.configure(name),
            style.lookup(name, "background"),
            style.lookup(name, "foreground"),
            style.lookup(name, "fieldbackground"),
            style.map(name),
        )
    return out


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
    elif sys.platform == "win32":
        assert theme["mode"] == "windows"
        # The native base theme is kept so unconverted panels don't change.
        assert theme["base_theme"] == "vista"
        assert style.theme_use() == "vista"
        assert theme["colors"] and theme["metrics"] and theme["styles"]
    else:
        assert theme["mode"] == "classic"
        assert theme["colors"] is None and theme["metrics"] is None


# ---------------------------------------------------------------------------
# Windows branch — bundle contract
# ---------------------------------------------------------------------------

def test_windows_branch_bundle(windows_theme):
    """An explicit Windows mode carrying nonempty token bundles."""
    _style, theme = windows_theme

    assert REQUIRED_KEYS <= set(theme)
    assert theme["mode"] == "windows"
    assert theme["style_prefix"] == "ACT"
    # Backwards-compatible with the classic bundle the launcher reads today.
    assert theme["family"] == "Segoe UI"
    assert theme["font_heading"] == ("Segoe UI", 15, "bold")
    assert theme["font_button"] == ("Segoe UI", 11)
    assert theme["geometry"] == "1024x720"
    assert theme["min_size"] == (920, 600)
    # New, and required to be nonempty.
    assert theme["colors"] and theme["metrics"]
    assert theme["styles"] and theme["fonts"]

    for key in ("title", "heading", "body", "small", "section", "button",
                "status", "mono", "row"):
        font = theme["fonts"][key]
        assert isinstance(font, tuple) and isinstance(font[0], str)
        assert isinstance(font[1], int) and font[1] > 0, f"{key}: {font!r}"


def test_windows_colors_are_valid_and_readable(windows_theme):
    """Every semantic color parses, and the text roles stay legible."""
    _style, theme = windows_theme
    c = theme["colors"]

    for name, value in c.items():
        if name == "is_dark":
            assert value is True
            continue
        assert isinstance(value, str) and value.startswith("#") \
            and len(value) == 7, f"{name} not '#rrggbb': {value!r}"
        int(value[1:], 16)  # parses as hex

    # Every semantic role the plan requires is present.
    required_roles = {
        "window", "surface", "elevated", "muted", "sidebar", "border",
        "divider", "text", "secondary", "disabled", "accent", "accent_hover",
        "accent_pressed", "focus", "success", "warning", "danger", "field",
        "selection", "selection_text", "shared_bg", "shared_border",
        "shared_header",
    }
    assert required_roles <= set(c)

    surfaces = [c["window"], c["surface"], c["elevated"], c["muted"],
                c["sidebar"], c["field"], c["shared_bg"]]
    for bg in surfaces:
        assert _contrast(c["text"], bg) >= 7.0, f"primary text on {bg}"
        assert _contrast(c["secondary"], bg) >= 4.5, f"secondary text on {bg}"
        # Disabled text is intentionally quiet but must still be perceivable,
        # and keyboard focus must be visible against every background.
        assert _contrast(c["disabled"], bg) >= 3.0, f"disabled text on {bg}"
        assert _contrast(c["focus"], bg) >= 3.0, f"focus ring on {bg}"

    for role in ("accent", "success", "warning", "danger"):
        assert _contrast(c[role], c["surface"]) >= 4.5, role
    assert _contrast(c["inverse"], c["accent"]) >= 4.5
    assert _contrast(c["selection_text"], c["selection"]) >= 4.5
    assert _contrast(c["shared_header"], c["shared_bg"]) >= 4.5
    # The Shared Metadata surface has to read as distinct from a normal card.
    assert c["shared_bg"] != c["surface"]
    assert c["shared_border"] != c["border"]


def test_windows_metrics_are_usable(windows_theme):
    _style, theme = windows_theme
    m = theme["metrics"]

    required = {"sidebar_width", "row_height", "content_pad", "card_pad",
                "field_pad", "button_pad", "border_width", "scroll_width",
                "gap_sm", "gap_md", "gap_lg", "content_max_width",
                "tree_row_height", "progress_thickness"}
    assert required <= set(m)

    for name, value in m.items():
        if isinstance(value, tuple):
            assert value and all(isinstance(v, int) and v >= 0 for v in value), name
        else:
            assert isinstance(value, int) and value >= 0, f"{name}={value!r}"

    # Sanity on the ones that drive layout at 1920x1080 / 125%.
    assert m["sidebar_width"] >= 180
    assert m["row_height"] >= 28
    assert m["content_max_width"] > m["sidebar_width"]


# ---------------------------------------------------------------------------
# Windows branch — style namespace, states, and isolation
# ---------------------------------------------------------------------------

def test_windows_styles_are_namespaced_and_registered(windows_theme):
    style, theme = windows_theme

    for key, name in theme["styles"].items():
        assert name.startswith("ACT."), f"{key} -> {name} is not namespaced"
        layout = style.layout(name)
        assert layout, f"{name} has no layout"

    # The natively-drawn widget classes must be laid out from the cloned ACT
    # elements; if they fell back to the vista layout the dark fill would be
    # silently ignored.
    for key in ("button", "primary_button", "danger_button", "ghost_button",
                "nav_button", "entry", "combobox", "spinbox", "checkbutton",
                "muted_checkbutton", "radiobutton", "notebook", "progressbar",
                "vscrollbar", "hscrollbar", "treeview", "labelframe",
                "shared_labelframe", "separator"):
        name = theme["styles"][key]
        root_element = style.layout(name)[0][0]
        assert root_element.startswith("ACT.") \
            or root_element in ("Checkbutton.padding", "Radiobutton.padding"), \
            f"{name} falls back to a native element: {root_element}"

    # Sub-styles the widgets resolve on their own.
    for name in ("ACT.TNotebook.Tab", "ACT.Treeview.Heading",
                 "ACT.Treeview.Item", "ACT.Shared.TLabelframe.Label"):
        assert style.layout(name)


def test_windows_styles_define_widget_states(windows_theme):
    """Hover, pressed, selected, disabled, focus and danger are all defined."""
    style, theme = windows_theme
    c = theme["colors"]
    s = theme["styles"]

    def bg(name, *state):
        return style.lookup(name, "background", list(state))

    for key in ("button", "primary_button", "nav_button"):
        name = s[key]
        normal = bg(name)
        assert normal, name
        assert bg(name, "active") != normal, f"{name} has no hover state"
        assert bg(name, "pressed") != normal, f"{name} has no pressed state"
        # Disabled always dims the text; only the filled buttons also change
        # their fill (a disabled sidebar row keeps the rail background).
        assert style.lookup(name, "foreground", ["disabled"]) == c["disabled"]
        assert style.lookup(name, "foreground", ["disabled"]) \
            != style.lookup(name, "foreground"), f"{name} disabled == normal"
        assert style.lookup(name, "focuscolor"), f"{name} has no focus color"

    for key in ("button", "primary_button"):
        name = s[key]
        assert bg(name, "disabled") != bg(name), f"{name} has no disabled fill"

    # Selection is how the launcher will mark the active tool.
    assert bg(s["nav_button"], "selected") == c["accent_soft"]
    assert bg(s["nav_button"], "selected") != bg(s["nav_button"])

    # Danger role is distinct from the neutral button and reacts to hover.
    danger = s["danger_button"]
    assert style.lookup(danger, "foreground") == c["danger"]
    assert bg(danger, "active") != bg(danger)

    # Inputs: focus ring, disabled fill, selection colors.
    for key in ("entry", "combobox", "spinbox"):
        name = s[key]
        assert style.lookup(name, "fieldbackground") == c["field"]
        assert style.lookup(name, "bordercolor", ["focus"]) == c["focus"]
        assert style.lookup(name, "fieldbackground", ["disabled"]) \
            == c["field_disabled"]
        assert style.lookup(name, "foreground", ["disabled"]) == c["disabled"]

    # Toggles: the indicator changes on selected/disabled.
    for key in ("checkbutton", "radiobutton", "muted_checkbutton"):
        name = s[key]
        base = style.lookup(name, "indicatorbackground")
        assert style.lookup(name, "indicatorbackground", ["selected"]) != base
        assert style.lookup(name, "indicatorbackground", ["disabled"]) != base

    # Lists and tabs carry a selected state too.
    assert style.lookup(s["treeview"], "background", ["selected"]) == c["selection"]
    assert style.lookup("ACT.TNotebook.Tab", "background", ["selected"]) \
        != style.lookup("ACT.TNotebook.Tab", "background")
    assert style.lookup(s["vscrollbar"], "background", ["active"]) \
        == c["scroll_thumb_hover"]


def test_windows_theme_does_not_replace_generic_styles(tk_root, monkeypatch):
    """The five unconverted panels must render exactly as they do today.

    Snapshot every generic style the panels use, apply the Windows branch,
    and require the layouts, configured options, resolved colors and state
    maps to be byte-identical afterwards.
    """
    style = ttk.Style(tk_root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    before = _snapshot_generic(style)

    monkeypatch.setattr(sys, "platform", "win32")
    theme = ui_theme.apply_theme(tk_root, style)
    after = _snapshot_generic(style)

    changed = [name for name in GENERIC_STYLES if before[name] != after[name]]
    assert not changed, f"Windows theme leaked into generic styles: {changed}"

    # And nothing outside the namespace was invented.
    assert all(n.startswith("ACT.") for n in theme["styles"].values())
    act_elements = [e for e in style.element_names() if e.startswith("ACT.")]
    assert act_elements, "no ACT elements were cloned"
    assert all(e.startswith("ACT.") or "." in e for e in act_elements)


def test_windows_theme_application_is_repeatable(tk_root, monkeypatch):
    """Re-applying must not raise on the duplicate element clones."""
    monkeypatch.setattr(sys, "platform", "win32")
    style = ttk.Style(tk_root)
    first = ui_theme.apply_theme(tk_root, style)
    second = ui_theme.apply_theme(tk_root, style)
    third = ui_theme.apply_theme(tk_root, style)
    assert first == second == third
    assert style.layout(first["styles"]["primary_button"])


def test_windows_branch_survives_missing_native_theme(tk_root, monkeypatch):
    """No vista (non-Windows host, or a Tk built without it) -> still works."""
    class _NoVistaStyle(ttk.Style):
        def theme_use(self, themename=None):
            if themename == "vista":
                raise tk.TclError("vista unavailable (simulated)")
            return super().theme_use(themename)

    monkeypatch.setattr(sys, "platform", "win32")
    style = _NoVistaStyle(tk_root)
    try:
        theme = ui_theme.apply_theme(tk_root, style)
        assert theme["mode"] == "windows"
        assert theme["base_theme"] != "vista"
        assert theme["colors"] and theme["metrics"] and theme["styles"]
        # The design system is still usable on the fallback base theme.
        real = ttk.Style(tk_root)
        assert real.layout(theme["styles"]["primary_button"])
    finally:
        restore = ttk.Style(tk_root)
        if "vista" in restore.theme_names():
            restore.theme_use("vista")


def test_windows_widgets_build_with_act_styles(tk_root, monkeypatch):
    """Every ACT style resolves on a real widget without raising."""
    monkeypatch.setattr(sys, "platform", "win32")
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style)
    s = theme["styles"]

    host = ttk.Frame(tk_root, style=s["window"])
    try:
        for key in ("label", "title", "heading", "subheading", "section",
                    "secondary_label", "status_label", "link_label",
                    "success_label", "warning_label", "danger_label",
                    "sidebar_label", "muted_label", "shared_header"):
            ttk.Label(host, text=key, style=s[key]).pack()
        for key in ("button", "primary_button", "danger_button",
                    "ghost_button", "nav_button"):
            ttk.Button(host, text=key, style=s[key]).pack()
        for key in ("surface", "card", "elevated", "muted", "sidebar",
                    "divider", "toolbar"):
            ttk.Frame(host, style=s[key]).pack()
        ttk.Entry(host, style=s["entry"]).pack()
        ttk.Combobox(host, style=s["combobox"], values=["a"]).pack()
        ttk.Spinbox(host, style=s["spinbox"], from_=1, to=5).pack()
        ttk.Checkbutton(host, text="c", style=s["checkbutton"]).pack()
        ttk.Checkbutton(host, text="m", style=s["muted_checkbutton"]).pack()
        ttk.Radiobutton(host, text="r", style=s["radiobutton"]).pack()
        ttk.Labelframe(host, text="g", style=s["labelframe"]).pack()
        ttk.Labelframe(host, text="Shared", style=s["shared_labelframe"]).pack()
        nb = ttk.Notebook(host, style=s["notebook"])
        nb.add(ttk.Frame(nb, style=s["surface"]), text="Summary")
        nb.add(ttk.Frame(nb, style=s["surface"]), text="Details")
        nb.pack()
        ttk.Progressbar(host, style=s["progressbar"], value=40).pack()
        ttk.Scrollbar(host, style=s["vscrollbar"], orient="vertical").pack()
        ttk.Scrollbar(host, style=s["hscrollbar"], orient="horizontal").pack()
        tree = ttk.Treeview(host, style=s["treeview"], height=2)
        tree.heading("#0", text="File")
        tree.insert("", "end", text="row")
        tree.pack()
        ttk.Separator(host, style=s["separator"], orient="horizontal").pack()
        tk_root.update_idletasks()
    finally:
        host.destroy()


# ---------------------------------------------------------------------------
# Classic Tk token helper
# ---------------------------------------------------------------------------

def test_style_tk_widget_applies_tokens(tk_root, monkeypatch):
    """Canvas/Listbox/Text get the tokens; unsupported options are dropped."""
    monkeypatch.setattr(sys, "platform", "win32")
    theme = ui_theme.apply_theme(tk_root, ttk.Style(tk_root))
    c = theme["colors"]

    listbox = tk.Listbox(tk_root)
    text = tk.Text(tk_root, height=2)
    canvas = tk.Canvas(tk_root)
    frame = tk.Frame(tk_root)
    try:
        applied = ui_theme.style_tk_widget(listbox, theme, "list")
        assert listbox.cget("background") == c["field"]
        assert listbox.cget("foreground") == c["text"]
        assert listbox.cget("selectbackground") == c["selection"]
        # Listbox has no insertion cursor: that option must be dropped, not
        # raise, so one call works for every classic widget.
        assert "insertbackground" not in applied

        ui_theme.style_tk_widget(text, theme, "log")
        assert text.cget("background") == c["elevated"]
        assert text.cget("insertbackground") == c["text"]

        ui_theme.style_tk_widget(canvas, theme, "canvas")
        assert canvas.cget("background") == c["surface"]

        ui_theme.style_tk_widget(frame, theme, "divider")
        assert frame.cget("background") == c["border"]

        # Overrides win over the role defaults.
        ui_theme.style_tk_widget(canvas, theme, "canvas",
                                 background=c["muted"], highlightthickness=1)
        assert canvas.cget("background") == c["muted"]
        assert int(canvas.cget("highlightthickness")) == 1

        with pytest.raises(ValueError):
            ui_theme.style_tk_widget(canvas, theme, "not-a-role")
    finally:
        for w in (listbox, text, canvas, frame):
            w.destroy()


def test_style_tk_widget_is_a_noop_without_a_windows_bundle(tk_root, monkeypatch):
    """Panels may call it unconditionally: non-Windows themes change nothing."""
    monkeypatch.setattr(sys, "platform", "linux")
    classic = ui_theme.apply_theme(tk_root, ttk.Style(tk_root))
    assert classic["colors"] is None

    canvas = tk.Canvas(tk_root)
    try:
        before = canvas.cget("background")
        assert ui_theme.style_tk_widget(canvas, classic, "canvas") == {}
        assert canvas.cget("background") == before
        # Role validation still happens, so typos surface on every platform.
        with pytest.raises(ValueError):
            ui_theme.style_tk_widget(canvas, classic, "nope")
    finally:
        canvas.destroy()


# ---------------------------------------------------------------------------
# Unchanged contracts
# ---------------------------------------------------------------------------

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


def test_progress_indicator_default_style_is_untouched(tk_root):
    """The shared indicator stays generic — five panels use it unconverted."""
    ind = ui_theme.ProgressIndicator(tk_root)
    assert str(ind.bar.cget("style")) == ""
    assert str(ind.frame.cget("style")) == ""
    assert str(ind.label.cget("style")) == ""
    ind.frame.destroy()


def test_classic_branch_other_platform(tk_root, monkeypatch):
    """Non-win32/non-darwin keeps the historical clam + TkDefaultFont look."""
    monkeypatch.setattr(sys, "platform", "linux")
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style)

    assert theme["mode"] == "classic"
    assert theme["family"] == "TkDefaultFont"
    assert theme["colors"] is None and theme["metrics"] is None
    assert theme["geometry"] == "1024x720"
    assert theme["min_size"] == (920, 600)
    assert style.theme_use() == "clam"
