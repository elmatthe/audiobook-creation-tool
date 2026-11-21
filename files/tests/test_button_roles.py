"""v0.8.1 Checkpoint B: the outlined semantic button roles.

Pins, without any one tool panel, that

* the approved inventory is 146 controls with Appendix A's per-surface counts and
  the ten blue Book controls (the live per-surface audits live in each panel's own
  test file and call ``button_role_inventory.audit``; the last test here proves
  every surface is audited);
* the four role styles draw their colour in text and border only: the background
  is a neutral grey in every interaction state, Light and Dark, with readable
  contrast, a visible disabled state and a focus ring;
* the old Danger style no longer fills red on hover or press;
* the roles survive a live Light/Dark switch; on Aqua (Checkpoint E) the four
  roles draw their own outline image at the native size and the plain button
  stays native.
"""

from __future__ import annotations

import ast
import itertools
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pytest

from shared import appearance

import button_role_inventory as inventory
from test_launcher_smoke import fake_settings, fresh_root, tk_root  # noqa: F401
from source_probe import UNIVERSAL as SCRIPTS
from source_probe import application_python_files

TESTS = Path(__file__).resolve().parent

ROLE_KEYS = ("button_red", "button_green", "button_yellow", "button_blue")
TONES = {"button_red": "role_red", "button_green": "role_green",
         "button_yellow": "role_yellow", "button_blue": "role_blue"}
STATE_SETS = [
    [], ["active"], ["pressed"], ["pressed", "active"], ["focus"], ["selected"],
    ["alternate"], ["active", "focus"], ["pressed", "focus"],
    ["alternate", "active"], ["alternate", "pressed"], ["alternate", "focus"],
    ["selected", "active"], ["readonly"],
]
DISABLED_STATE_SETS = [["disabled"], ["disabled", "active"], ["disabled", "focus"],
                       ["disabled", "alternate"], ["disabled", "pressed"],
                       ["disabled", "selected"]]


def _bundle(root, value):
    return appearance.build_bundle(ttk.Style(root), value, platform="win32", root=root)


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(color: str) -> float:
    def lin(channel):
        channel /= 255
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _is_neutral(color: str) -> bool:
    return max(_rgb(color)) - min(_rgb(color)) <= 10


def _hex(root, color) -> str:
    """Normalise a Tk colour result (``#rrggbb`` or a Tcl colour object) to hex."""
    text = str(color)
    if text.startswith("#") and len(text) == 7:
        return text.lower()
    r, g, b = (value >> 8 for value in root.winfo_rgb(text))
    return f"#{r:02x}{g:02x}{b:02x}"


# --------------------------------------------------------------------------- #
# the inventory and the taxonomy (no Tk)
# --------------------------------------------------------------------------- #


def test_the_inventory_is_146_controls_with_appendix_a_counts():
    assert {surface: len(rows) for surface, rows in inventory.INVENTORY.items()} \
        == inventory.APPROVED_COUNTS
    assert sum(len(rows) for rows in inventory.INVENTORY.values()) == 146
    for surface, rows in inventory.INVENTORY.items():
        labels = [label for label, _letter in rows]
        assert len(labels) == len(set(labels)), f"{surface} repeats a row"
        assert {letter for _label, letter in rows} <= set(appearance.BUTTON_ROLE_LETTERS)


def test_the_ten_blue_book_controls_are_blue_and_nothing_else_in_books_is():
    for surface, label in inventory.BLUE_BOOK_CONTROLS:
        assert dict(inventory.INVENTORY[surface])[label] == "D", (surface, label)
    assert len(inventory.BLUE_BOOK_CONTROLS) == 10
    for surface in ("mp3", "maker", "metadata"):
        blue = {label for label, letter in inventory.INVENTORY[surface] if letter == "D"}
        assert blue == {label for s, label in inventory.BLUE_BOOK_CONTROLS if s == surface}


def test_application_navigation_is_entirely_normal():
    assert {letter for _label, letter in inventory.INVENTORY["navigation"]} == {"E"}


def test_every_action_role_is_a_defined_role_and_the_keys_resolve():
    assert set(appearance.BUTTON_ACTION_ROLES.values()) <= set(appearance.BUTTON_ROLE_STYLE_KEYS)
    for letter, role in appearance.BUTTON_ROLE_LETTERS.items():
        assert appearance.button_style_key(letter) == appearance.BUTTON_ROLE_STYLE_KEYS[role]
        assert appearance.button_style_key(role) == appearance.BUTTON_ROLE_STYLE_KEYS[role]
    for action, role in appearance.BUTTON_ACTION_ROLES.items():
        assert appearance.button_style_key(action) == appearance.BUTTON_ROLE_STYLE_KEYS[role]
    for bad in ("", "purple", "Cancel", "F"):
        with pytest.raises(ValueError):
            appearance.button_style_key(bad)


def test_the_taxonomy_matches_the_approved_meaning():
    roles = appearance.BUTTON_ACTION_ROLES
    assert {roles[k] for k in ("cancel", "clear", "remove", "reset", "clear_log",
                               "cancel_import", "clear_imports")} == {"red"}
    assert {roles[k] for k in ("run", "save", "install")} == {"green"}
    assert {roles[k] for k in ("pause", "resume", "retry")} == {"yellow"}
    assert {roles[k] for k in ("book_previous", "book_next", "book_add",
                               "book_duplicate")} == {"blue"}
    assert roles["book_remove"] == "red"
    assert {roles[k] for k in ("add_files", "add_folder", "import_folder", "move_up",
                               "move_down", "open_output", "browse", "close")} == {"normal"}


def test_the_older_style_names_are_the_roles_not_fills():
    for platform in ("win32", "darwin"):
        names = appearance._AQUA_STYLES if platform == "darwin" else appearance._STYLES
        assert names["danger_button"] == names["button_red"]
        assert names["primary_button"] == names["button_green"]


# --------------------------------------------------------------------------- #
# the styles themselves
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_no_role_ever_fills_with_a_colour(tk_root, value):
    bundle = _bundle(tk_root, value)
    style = ttk.Style(tk_root)
    colors = bundle["colors"]
    semantic = {_hex(tk_root, colors[k]) for k in (
        "danger", "danger_hover", "danger_pressed", "success", "warning", "accent",
        "accent_hover", "accent_pressed", "accent_soft", "role_red", "role_green",
        "role_yellow", "role_blue", "selection", "shared_bg")}
    # the guard is only meaningful if the colours it forbids are not themselves greys
    assert not any(_is_neutral(_hex(tk_root, colors[k]))
                   for k in ("role_red", "role_green", "role_yellow", "role_blue"))
    for key in ROLE_KEYS:
        name = bundle["styles"][key]
        for states in STATE_SETS + DISABLED_STATE_SETS:
            for option in ("background", "lightcolor", "darkcolor"):
                fill = _hex(tk_root, style.lookup(name, option, states))
                assert _is_neutral(fill), (value, key, states, option, fill)
                assert fill not in semantic, (value, key, states, option, fill)


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_text_and_border_carry_the_role_colour_in_every_live_state(tk_root, value):
    bundle = _bundle(tk_root, value)
    style = ttk.Style(tk_root)
    colors = bundle["colors"]
    for key in ROLE_KEYS:
        name = bundle["styles"][key]
        tone = _hex(tk_root, colors[TONES[key]])
        for states in STATE_SETS:
            assert _hex(tk_root, style.lookup(name, "foreground", states)) == tone, (key, states)
            assert _hex(tk_root, style.lookup(name, "bordercolor", states)) == tone, (key, states)


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_the_roles_are_four_different_colours(tk_root, value):
    bundle = _bundle(tk_root, value)
    colors = {_hex(tk_root, bundle["colors"][TONES[key]]) for key in ROLE_KEYS}
    assert len(colors) == 4


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_role_text_stays_readable_on_its_neutral_background_in_every_state(tk_root, value):
    bundle = _bundle(tk_root, value)
    style = ttk.Style(tk_root)
    for key in ROLE_KEYS:
        name = bundle["styles"][key]
        for states in STATE_SETS:
            text = _hex(tk_root, style.lookup(name, "foreground", states))
            fill = _hex(tk_root, style.lookup(name, "background", states))
            assert _contrast(text, fill) >= 4.5, (value, key, states, text, fill)


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_disabled_is_visibly_disabled_and_never_role_coloured(tk_root, value):
    bundle = _bundle(tk_root, value)
    style = ttk.Style(tk_root)
    colors = bundle["colors"]
    for key in ROLE_KEYS:
        name = bundle["styles"][key]
        tone = _hex(tk_root, colors[TONES[key]])
        for states in DISABLED_STATE_SETS:
            assert _hex(tk_root, style.lookup(name, "foreground", states)) \
                == _hex(tk_root, colors["disabled"]), (key, states)
            border = _hex(tk_root, style.lookup(name, "bordercolor", states))
            assert border == _hex(tk_root, colors["border"]) != tone, (key, states)
        enabled = _hex(tk_root, style.lookup(name, "foreground", []))
        assert enabled != _hex(tk_root, style.lookup(name, "foreground", ["disabled"]))


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_hover_and_pressed_change_only_between_neutral_greys(tk_root, value):
    bundle = _bundle(tk_root, value)
    style = ttk.Style(tk_root)
    for key in ROLE_KEYS:
        name = bundle["styles"][key]
        rest = _hex(tk_root, style.lookup(name, "background", []))
        hover = _hex(tk_root, style.lookup(name, "background", ["active"]))
        pressed = _hex(tk_root, style.lookup(name, "background", ["pressed", "active"]))
        assert len({rest, hover, pressed}) == 3, (key, rest, hover, pressed)
        assert all(_is_neutral(c) for c in (rest, hover, pressed))
        # the default-button cue (ttk's ``alternate``) must not move the fill either
        assert _hex(tk_root, style.lookup(name, "background", ["alternate"])) == rest


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_the_keyboard_focus_ring_is_kept_and_visible(tk_root, value):
    bundle = _bundle(tk_root, value)
    style = ttk.Style(tk_root)
    focus_element = f"{appearance.STYLE_PREFIX}.Button.focus"
    for key in ROLE_KEYS:
        name = bundle["styles"][key]
        assert focus_element in str(style.layout(name)), key
        ring = _hex(tk_root, style.lookup(name, "focuscolor"))
        for states in ([], ["active"], ["pressed", "active"]):
            fill = _hex(tk_root, style.lookup(name, "background", states + ["focus"]))
            assert _contrast(ring, fill) >= 4.5, (key, states, ring, fill)
        # a focused button keeps its role border; the ring is the indicator
        assert _hex(tk_root, style.lookup(name, "bordercolor", ["focus"])) \
            == _hex(tk_root, bundle["colors"][TONES[key]])


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_role_buttons_match_the_geometry_of_the_plain_button(tk_root, value):
    """Typography, padding and border width are the plain compact button's."""
    bundle = _bundle(tk_root, value)
    style = ttk.Style(tk_root)
    plain = bundle["styles"]["button"]
    for key in ROLE_KEYS:
        name = bundle["styles"][key]
        for option in ("font", "padding", "borderwidth", "relief", "anchor"):
            assert str(style.lookup(name, option)) == str(style.lookup(plain, option)), (key, option)
        assert style.layout(name) == style.layout(plain), key


@pytest.mark.skipif(sys.platform != "win32", reason="the ACT shell navigation styles are Windows")
def test_application_navigation_stays_normal_and_never_takes_a_role(fresh_root, fake_settings):
    """Appendix A, Application navigation: all 9 controls keep the shell's own nav/ghost
    treatment; none of them is a semantic role."""
    import launcher

    app = launcher.LauncherApp(fresh_root)
    s = app.theme["styles"]
    titles = {b.cget("text"): b for b in app.buttons.values()}
    assert sorted(titles) == ["Cover Image", "M4B Converter", "M4B Maker", "M4B Metadata",
                              "MP3 Tool", "TTS Audiobook"]
    rows = {f"{title} navigation": button for title, button in titles.items()}
    rows.update({"Light / Dark toggle": app.appearance_button,
                 "Preferences & Data…": app.preferences_button,
                 "Open log folder": app._log_button})
    own = {label: (s["nav_button"] if label.endswith("navigation") else s["ghost_button"]) for label in rows}
    inventory.audit("navigation", app.appearance_bundle, rows, own_normal=own)
    role_styles = {app.appearance_bundle["styles"][key] for key in ROLE_KEYS}
    assert not {str(b.cget("style")) for b in rows.values()} & role_styles


def test_a_widget_keeps_its_role_style_name_through_a_live_theme_switch(tk_root):
    light = _bundle(tk_root, appearance.LIGHT)
    style = ttk.Style(tk_root)
    buttons = {key: ttk.Button(tk_root, text=key, style=light["styles"][key]) for key in ROLE_KEYS}
    before = {key: _hex(tk_root, style.lookup(light["styles"][key], "foreground", []))
              for key in ROLE_KEYS}
    dark = _bundle(tk_root, appearance.DARK)
    assert dark["styles"] == light["styles"]
    try:
        for key, button in buttons.items():
            assert str(button.cget("style")) == dark["styles"][key]
            now = _hex(tk_root, style.lookup(dark["styles"][key], "foreground", []))
            assert now == _hex(tk_root, dark["colors"][TONES[key]])
            assert now != before[key]
            assert _is_neutral(_hex(tk_root, style.lookup(dark["styles"][key], "background", [])))
        back = _bundle(tk_root, appearance.LIGHT)
        for key in ROLE_KEYS:
            assert _hex(tk_root, style.lookup(back["styles"][key], "foreground", [])) == before[key]
    finally:
        for button in buttons.values():
            button.destroy()


def test_danger_no_longer_fills_red_on_hover_or_press(tk_root):
    """The pre-v0.8.1 defect: hover/pressed painted the whole button danger-red."""
    for value in (appearance.LIGHT, appearance.DARK):
        bundle = _bundle(tk_root, value)
        style = ttk.Style(tk_root)
        name = bundle["styles"]["danger_button"]
        reds = {_hex(tk_root, bundle["colors"][k]) for k in ("danger", "danger_hover", "danger_pressed")}
        for states in (["active"], ["pressed"], ["pressed", "active"]):
            assert _hex(tk_root, style.lookup(name, "background", states)) not in reds
            assert _hex(tk_root, style.lookup(name, "foreground", states)) \
                == _hex(tk_root, bundle["colors"]["danger"])


def test_the_plain_button_and_the_shell_styles_are_untouched(tk_root):
    bundle = _bundle(tk_root, appearance.LIGHT)
    style = ttk.Style(tk_root)
    colors = bundle["colors"]
    plain = bundle["styles"]["button"]
    assert _hex(tk_root, style.lookup(plain, "background", [])) == colors["elevated"]
    assert _hex(tk_root, style.lookup(plain, "background", ["active"])) == colors["accent_soft"]
    assert _hex(tk_root, style.lookup(plain, "foreground", [])) == colors["text"]


def _aqua_bundle(root, value):
    return appearance.build_bundle(ttk.Style(root), value, platform="darwin", root=root)


def _aqua_images(root):
    return root.winfo_toplevel()._compact_aqua_button_images


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_aqua_role_buttons_carry_the_role_in_text_and_outline_only(tk_root, value):
    """v0.8.1 Checkpoint E. Aqua ignores ttk border and background options, so the
    four roles draw their own outline image; the plain button stays native."""
    bundle = _aqua_bundle(tk_root, value)
    style = ttk.Style(tk_root)
    colors = bundle["colors"]
    for key in ROLE_KEYS:
        name = bundle["styles"][key]
        assert name.startswith("CompactAqua.")
        assert _hex(tk_root, style.lookup(name, "foreground", [])) \
            == _hex(tk_root, colors[TONES[key]])
        assert _hex(tk_root, style.lookup(name, "foreground", ["disabled"])) \
            == _hex(tk_root, colors["disabled"])
        # the layout draws the role's own image element, not Cocoa's Button.button
        assert style.layout(name)[0][0].startswith(f"CompactAqua.{key[7:]}.button."), key
    # Never configured: ttk resolves the neutral role to the platform's own button.
    assert style.configure(bundle["styles"]["button"]) in (None, {})
    assert style.layout(bundle["styles"]["button"])[0][0] == "Button.button"


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_aqua_role_images_are_outlined_neutral_and_transparent_outside(tk_root, value):
    bundle = _aqua_bundle(tk_root, value)
    colors = bundle["colors"]
    images = _aqua_images(tk_root)
    fills = {"normal": colors["field"], "active": colors["role_hover"],
             "pressed": colors["role_pressed"], "disabled": colors["field_disabled"]}
    assert len({_hex(tk_root, c) for c in fills.values()}) == 4
    assert len(images) == 4 * 4 * 2
    for key, image in images.items():
        role, fill, ring = key.split("_")
        tone = _hex(tk_root, colors["role_" + role])
        centre = "#%02x%02x%02x" % image.get(12, 14)
        edge = "#%02x%02x%02x" % image.get(appearance._AQUA_INSET, 14)
        assert centre == _hex(tk_root, fills[fill]), key
        assert _is_neutral(centre), key
        assert edge == (_hex(tk_root, colors["border"]) if fill == "disabled" else tone), key
        assert image.transparency_get(0, 0), key
        # the keyboard-focus halo lives in the margin and never on a disabled button
        halo = not image.transparency_get(1, 14)
        assert halo == (ring == "ring" and fill != "disabled"), key
        if fill != "disabled":  # a disabled label is meant to be dim
            assert _contrast(tone, centre) >= 4.5, key


def assert_aqua_button_layout(style, bundle, name, role=None):
    """The Aqua button-layout contract since Checkpoint E, for any panel's button.

    A semantic role button (red, green, yellow, blue) draws its own outlined image
    element, with the padding and label nesting of a button and no separate focus
    element (the keyboard-focus ring is part of the image); its native size is pinned
    on a Mac by ``test_aqua_role_buttons_ask_for_exactly_the_native_size``. Every other
    button stays on the native TButton layout exactly. ``role`` ("red"...) names the
    role the style must be; ``None`` means it must be the plain, native button.
    """
    by_style = {bundle["styles"][key]: key[len("button_"):] for key in ROLE_KEYS}
    assert by_style.get(str(name)) == role, (str(name), role)
    layout, native = style.layout(str(name)), style.layout("TButton")
    assert len(layout) == 1 and len(native) == 1, (layout, native)
    if role is None:
        assert layout == native, str(name)
        return
    element, options = layout[0]
    assert element.startswith(f"CompactAqua.{role}.button."), element
    assert options == {"sticky": "nswe", "children": [
        ("Button.padding", {"sticky": "nswe", "children": [
            ("Button.label", {"sticky": "nswe"})]})]}, (element, options)


@pytest.mark.parametrize("label", ["X", "Start", "Add Files", "Remove Selected"])
@pytest.mark.parametrize("key", ROLE_KEYS)
@pytest.mark.skipif(sys.platform != "darwin", reason="compares with the native Aqua button")
def test_aqua_role_buttons_ask_for_exactly_the_native_size(tk_root, key, label):
    bundle = _aqua_bundle(tk_root, appearance.LIGHT)
    native = ttk.Button(tk_root, text=label)
    role = ttk.Button(tk_root, text=label, style=bundle["styles"][key])
    try:
        native.update_idletasks()
        assert (role.winfo_reqwidth(), role.winfo_reqheight()) \
            == (native.winfo_reqwidth(), native.winfo_reqheight())
    finally:
        native.destroy()
        role.destroy()


def test_aqua_roles_repaint_in_place_on_a_live_light_dark_switch(tk_root):
    light = _aqua_bundle(tk_root, appearance.LIGHT)
    image = _aqua_images(tk_root)["red_normal_flat"]
    before = image.get(12, 14)
    style = ttk.Style(tk_root)
    button = ttk.Button(tk_root, text="Cancel", style=light["styles"]["button_red"])
    try:
        dark = _aqua_bundle(tk_root, appearance.DARK)
        assert _aqua_images(tk_root)["red_normal_flat"] is image  # the same object
        assert image.get(12, 14) != before
        assert button.cget("style") == light["styles"]["button_red"]
        assert _hex(tk_root, style.lookup(dark["styles"]["button_red"], "foreground", [])) \
            == _hex(tk_root, dark["colors"]["role_red"])
    finally:
        button.destroy()
        _aqua_bundle(tk_root, appearance.LIGHT)


# --------------------------------------------------------------------------- #
# source-level guards
# --------------------------------------------------------------------------- #

#: Windows/Mac surfaces that build ``ttk.Button`` outside the 146-control inventory.
#: Each stays on its platform/plain style until the maintainer classifies it.
UNCLASSIFIED_BUTTON_SOURCES = {
    "launcher.py": "application shell: navigation, toggle, Preferences, log folder (all E)",
    "shared/bootstrap.py": "first-run wizard's own Begin Setup / Cancel / Close (pre-app, native)",
    "shared/long_paths.py": "stage-0 long-path prompt (pre-app, native)",
    "shared/optional_setup_tk_harness_v3.py": "developer harness",
    "tts/qwen3_clone_setup_ui.py": "Qwen3 developer clone tools (not in Appendix A)",
}
ROLE_HELPERS = {"_action_style", "action_style", "role"}
#: Style-less buttons in an otherwise classified file (text -> why). Not in Appendix A.
UNSTYLED_BUTTONS = {
    "tts/epub2tts_gui.py": {"Cancel": "the English sentence-data download dialog's Cancel"},
}


def _button_styles(path: Path):  # yields (line, style node, constant text)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "Button" and getattr(node.func.value, "id", "") == "ttk":
            style = next((k.value for k in node.keywords if k.arg == "style"), None)
            text = next((k.value.value for k in node.keywords if k.arg == "text"
                         and isinstance(k.value, ast.Constant)), "")
            yield node.lineno, style, text


def _helper_name(node) -> str:
    if isinstance(node, ast.Call):
        func = node.func
        return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    return ""


def test_every_classified_button_takes_its_style_through_a_role_helper():
    offenders = []
    for path in application_python_files():
        relative = path.relative_to(SCRIPTS).as_posix()
        if relative in UNCLASSIFIED_BUTTON_SOURCES or relative == "shared/ui_theme.py":
            continue
        for line, style, text in _button_styles(path):
            if _helper_name(style) not in ROLE_HELPERS                     and not (style is None and text in UNSTYLED_BUTTONS.get(relative, {})):
                offenders.append(f"{relative}:{line}")
    assert not offenders, offenders


def test_no_widget_source_picks_a_button_colour_directly():
    pattern = re.compile(r"button_(?:red|green|yellow|blue)|danger_button|primary_button")
    allowed = {"shared/appearance.py", "shared/ui_theme.py"}  # ui_theme: the shell's own ACT.* map
    offenders = [p.relative_to(SCRIPTS).as_posix() for p in application_python_files()
                 if p.relative_to(SCRIPTS).as_posix() not in allowed
                 and pattern.search(p.read_text(encoding="utf-8"))]
    assert not offenders, offenders


@pytest.mark.parametrize("relative", ["shared/bootstrap.py", "tts/epub2tts_gui.py"])
def test_both_hosts_of_the_setup_panel_hand_it_a_theme(relative):
    """The first-run wizard (Light palette: its window is the platform's own) and the TTS
    Install & Continue dialog (the app's live bundle) both pass ``theme=``."""
    tree = ast.parse((SCRIPTS / relative).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "OptionalSetupPanel"]
    assert len(calls) == 1, relative
    assert any(k.arg == "theme" for k in calls[0].keywords), relative


def test_every_inventory_surface_has_a_live_audit_in_the_suite():
    text = "\n".join(p.read_text(encoding="utf-8") for p in TESTS.glob("test_*.py"))
    unaudited = [surface for surface in inventory.INVENTORY
                 if f'audit("{surface}"' not in text and f"audit('{surface}'" not in text]
    assert unaudited == [], unaudited


def test_the_state_sets_cover_a_default_focused_pressed_and_alternate_button():
    flat = set(itertools.chain.from_iterable(STATE_SETS + DISABLED_STATE_SETS))
    assert {"active", "pressed", "focus", "alternate", "selected", "disabled"} <= flat
