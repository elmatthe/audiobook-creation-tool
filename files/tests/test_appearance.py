"""v0.6.6 Phase 1 — shared Light/Dark appearance foundation.

Three layers of coverage, in the order this module has them:

* pure settings-persistence logic (no Tk at all) — default, round-trip,
  toggle, and the invalid-value guards;
* the two palettes, held to the same WCAG contrast bar
  ``test_ui_theme.py`` holds the ``ACT.*`` palette to;
* the live ``ttk.Style`` registration — isolation from every generic style
  *and* from ``ACT.*`` (both families clone the same ``clam`` elements under
  different prefixes and must never collide), plus the state-preserving
  refresh path a live toggle depends on.

Every test redirects the settings layer at a temporary file, exactly as
``test_settings.py`` does, so no test can touch the maintainer's real
preferences.
"""

from __future__ import annotations

import sys

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import appearance  # noqa: E402
from shared import settings as app_settings  # noqa: E402
from shared import ui_theme  # noqa: E402
import tk_gate  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path):
    """Point the settings layer at a throwaway file for the whole test."""
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    try:
        yield
    finally:
        app_settings.use_path(None)


# --------------------------------------------------------------------------- #
# Persisted setting — pure logic, no Tk
# --------------------------------------------------------------------------- #


def test_a_fresh_settings_file_defaults_to_light():
    assert appearance.get_appearance() == "light"
    assert appearance.DEFAULT_APPEARANCE == "light"


def test_set_and_get_round_trip():
    assert appearance.set_appearance("dark") is True
    assert appearance.get_appearance() == "dark"
    assert appearance.set_appearance("light") is True
    assert appearance.get_appearance() == "light"


def test_set_rejects_an_invalid_value():
    with pytest.raises(ValueError):
        appearance.set_appearance("blue")
    # Rejected outright — not stored, not silently coerced.
    assert appearance.get_appearance() == "light"


def test_a_hand_edited_invalid_stored_value_falls_back_to_the_default():
    app_settings.set("appearance", "not-a-real-value")
    assert appearance.get_appearance() == "light"


def test_toggle_stored_appearance_flips_and_persists():
    assert appearance.get_appearance() == "light"
    first = appearance.toggle_stored_appearance()
    assert first == "dark"
    assert appearance.get_appearance() == "dark"
    second = appearance.toggle_stored_appearance()
    assert second == "light"
    assert appearance.get_appearance() == "light"


def test_the_setting_never_touches_config_toml(tmp_path):
    """The settings-key contract, asserted directly against the key name."""
    appearance.set_appearance("dark")
    assert app_settings.get("appearance") == "dark"
    assert appearance.SETTINGS_KEY == "appearance"


# --------------------------------------------------------------------------- #
# Palettes — structure and the same WCAG bar ui_theme.py's palette holds to
# --------------------------------------------------------------------------- #


def _luminance(hex_color: str) -> float:
    def channel(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("colors,expected_dark", [
    (appearance.LIGHT_COLORS, False),
    (appearance.DARK_COLORS, True),
])
def test_palette_keys_and_shape(colors, expected_dark):
    assert set(appearance.LIGHT_COLORS) == set(appearance.DARK_COLORS)
    assert colors["is_dark"] is expected_dark
    for name, value in colors.items():
        if name == "is_dark":
            continue
        assert isinstance(value, str) and value.startswith("#") \
            and len(value) == 7, f"{name} not '#rrggbb': {value!r}"
        int(value[1:], 16)  # parses as hex

    required_roles = {
        "window", "surface", "elevated", "muted", "sidebar", "border",
        "divider", "text", "secondary", "disabled", "accent", "accent_hover",
        "accent_pressed", "focus", "success", "warning", "danger", "field",
        "selection", "selection_text", "shared_bg", "shared_border",
        "shared_header",
    }
    assert required_roles <= set(colors)


@pytest.mark.parametrize("c", [appearance.LIGHT_COLORS, appearance.DARK_COLORS])
def test_palette_contrast_clears_the_project_bar(c):
    surfaces = [c["window"], c["surface"], c["elevated"], c["muted"],
                c["sidebar"], c["field"], c["shared_bg"]]
    for bg in surfaces:
        assert _contrast(c["text"], bg) >= 7.0, f"primary text on {bg}"
        assert _contrast(c["secondary"], bg) >= 4.5, f"secondary text on {bg}"
        assert _contrast(c["disabled"], bg) >= 3.0, f"disabled text on {bg}"
        assert _contrast(c["focus"], bg) >= 3.0, f"focus ring on {bg}"

    for role in ("accent", "success", "warning", "danger"):
        assert _contrast(c[role], c["surface"]) >= 4.5, role
    assert _contrast(c["inverse"], c["accent"]) >= 4.5
    assert _contrast(c["selection_text"], c["selection"]) >= 4.5
    assert _contrast(c["shared_header"], c["shared_bg"]) >= 4.5
    assert c["shared_bg"] != c["surface"]
    assert c["shared_border"] != c["border"]


def test_light_and_dark_are_actually_different_palettes():
    assert appearance.LIGHT_COLORS["window"] != appearance.DARK_COLORS["window"]
    assert appearance.LIGHT_COLORS["text"] != appearance.DARK_COLORS["text"]


# --------------------------------------------------------------------------- #
# Live ttk registration — isolation and the refresh path
# --------------------------------------------------------------------------- #

#: Generic styles that must never be created, reconfigured or re-laid-out —
#: the same discipline ``ui_theme.py``'s ``ACT.*`` family holds itself to.
GENERIC_STYLES = (
    "TFrame", "TLabel", "TButton", "TEntry", "TCombobox", "TSpinbox",
    "TCheckbutton", "TRadiobutton", "TLabelframe", "TLabelframe.Label",
    "TNotebook", "TNotebook.Tab", "Treeview", "Treeview.Heading",
    "Horizontal.TProgressbar", "Vertical.TScrollbar", "Horizontal.TScrollbar",
    "TSeparator",
)

#: A representative sample of ``ACT.*`` styles. Must never be touched by this
#: module — the two families clone the same ``clam`` elements independently.
ACT_SAMPLE = (
    "ACT.TButton", "ACT.Primary.TButton", "ACT.TEntry", "ACT.TFrame",
    "ACT.TLabel", "ACT.Heading.TLabel",
)


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


def _snapshot(style: ttk.Style, names) -> dict:
    out = {}
    for name in names:
        try:
            layout = style.layout(name)
        except tk.TclError:
            layout = None
        out[name] = (
            layout, style.configure(name), style.map(name),
            style.lookup(name, "background"), style.lookup(name, "foreground"),
        )
    return out


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_build_bundle_contract(tk_root, platform):
    style = ttk.Style(tk_root)
    bundle = appearance.build_bundle(style, "light", platform=platform, root=tk_root)

    assert bundle["mode"] == "compact"
    assert bundle["appearance"] == "light"
    assert bundle["platform"] == platform
    assert bundle["colors"] and bundle["metrics"] and bundle["fonts"]

    if platform == "darwin":
        # Native aqua is preserved: no ttk style registered.
        assert bundle["styles"] == {}
        assert bundle["ttk_active"] is False
        assert bundle["style_prefix"] == ""
    else:
        assert bundle["styles"]
        assert bundle["ttk_active"] is True
        assert bundle["style_prefix"] == appearance.STYLE_PREFIX
        for name in bundle["styles"].values():
            assert name.startswith(appearance.STYLE_PREFIX + "."), name


def test_registering_compact_styles_leaves_generic_styles_untouched(tk_root):
    style = ttk.Style(tk_root)
    before = _snapshot(style, GENERIC_STYLES)
    appearance.build_bundle(style, "dark", platform="win32", root=tk_root)
    after = _snapshot(style, GENERIC_STYLES)
    changed = [n for n in GENERIC_STYLES if before[n] != after[n]]
    assert not changed, f"Compact.* leaked into generic styles: {changed}"


def test_compact_and_act_coexist_without_collision(tk_root):
    """Both families clone the same clam elements under disjoint prefixes.

    Registering one after the other on the same live Style object — exactly
    what the launcher does at startup — must leave each family's own styles
    exactly as it left them.
    """
    style = ttk.Style(tk_root)
    ui_theme.apply_theme(tk_root, style, platform="win32")
    act_before = _snapshot(style, ACT_SAMPLE)

    appearance.build_bundle(style, "dark", platform="win32", root=tk_root)

    act_after = _snapshot(style, ACT_SAMPLE)
    assert act_before == act_after, "Compact.* registration altered an ACT.* style"

    # And the reverse direction: re-applying the shell theme afterwards must
    # not touch what Compact.* just registered.
    compact_before = _snapshot(style, [f"{appearance.STYLE_PREFIX}.TButton",
                                        f"{appearance.STYLE_PREFIX}.TEntry"])
    ui_theme.apply_theme(tk_root, style, platform="win32")
    compact_after = _snapshot(style, [f"{appearance.STYLE_PREFIX}.TButton",
                                       f"{appearance.STYLE_PREFIX}.TEntry"])
    assert compact_before == compact_after, "ui_theme re-application altered Compact.*"


def test_refresh_in_place_changes_color_without_a_new_style_name(tk_root):
    """The state-preserving refresh path: same style names, new colors."""
    style = ttk.Style(tk_root)
    light = appearance.build_bundle(style, "light", platform="win32", root=tk_root)
    light_bg = style.lookup(f"{appearance.STYLE_PREFIX}.TButton", "background")

    dark = appearance.build_bundle(style, "dark", platform="win32", root=tk_root)
    dark_bg = style.lookup(f"{appearance.STYLE_PREFIX}.TButton", "background")

    assert light["styles"] == dark["styles"], "refresh must not rename any style"
    assert light_bg != dark_bg, "refreshing to Dark did not change the button color"


def test_a_widget_survives_a_refresh_with_its_state_intact(tk_root):
    """A live widget's own state must not be touched by a refresh."""
    style = ttk.Style(tk_root)
    appearance.build_bundle(style, "light", platform="win32", root=tk_root)
    entry_var = tk.StringVar(tk_root, value="untouched")
    entry = ttk.Entry(tk_root, textvariable=entry_var,
                      style=f"{appearance.STYLE_PREFIX}.TEntry")
    entry.pack()
    try:
        entry.icursor(3)
        appearance.build_bundle(style, "dark", platform="win32", root=tk_root)
        assert entry.winfo_exists()
        assert entry_var.get() == "untouched"
        assert str(entry.cget("style")) == f"{appearance.STYLE_PREFIX}.TEntry"
    finally:
        entry.destroy()


# --------------------------------------------------------------------------- #
# style_tk_widget — the classic-widget coloring primitive
# --------------------------------------------------------------------------- #


def test_style_tk_widget_is_a_no_op_without_colors():
    assert appearance.style_tk_widget(None, {}, "surface") == {}
    assert appearance.style_tk_widget(None, None, "surface") == {}


def test_style_tk_widget_rejects_an_unknown_role(tk_root):
    text = tk.Text(tk_root)
    try:
        with pytest.raises(ValueError):
            appearance.style_tk_widget(text, {"colors": appearance.LIGHT_COLORS}, "nonsense")
    finally:
        text.destroy()


def test_style_tk_widget_colors_a_classic_widget(tk_root):
    bundle = {"colors": appearance.DARK_COLORS}
    listbox = tk.Listbox(tk_root)
    try:
        applied = appearance.style_tk_widget(listbox, bundle, "list")
        assert applied
        assert listbox.cget("background") == appearance.DARK_COLORS["field"]
    finally:
        listbox.destroy()


# --------------------------------------------------------------------------- #
# Listener registry
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clear_listeners():
    """Every test starts and ends with an empty listener registry."""
    appearance._listeners.clear()
    yield
    appearance._listeners.clear()


def test_register_and_notify():
    seen = []
    appearance.register_listener(seen.append)
    appearance.notify_listeners({"appearance": "dark"})
    assert seen == [{"appearance": "dark"}]


def test_unregister_stops_notification():
    seen = []
    appearance.register_listener(seen.append)
    appearance.unregister_listener(seen.append)
    appearance.notify_listeners({"appearance": "dark"})
    assert seen == []


def test_registering_the_same_callback_twice_notifies_once():
    seen = []

    def callback(bundle):
        seen.append(bundle)

    appearance.register_listener(callback)
    appearance.register_listener(callback)
    appearance.notify_listeners({"x": 1})
    assert seen == [{"x": 1}]


def test_a_raising_listener_does_not_stop_the_others():
    seen = []

    def bad(_bundle):
        raise RuntimeError("boom")

    appearance.register_listener(bad)
    appearance.register_listener(seen.append)
    appearance.notify_listeners({"x": 1})  # must not raise
    assert seen == [{"x": 1}]


def test_toggle_appearance_persists_refreshes_and_notifies(tk_root):
    style = ttk.Style(tk_root)
    seen = []
    appearance.register_listener(seen.append)

    assert appearance.get_appearance() == "light"
    bundle = appearance.toggle_appearance(style, platform="win32", root=tk_root)

    assert bundle["appearance"] == "dark"
    assert appearance.get_appearance() == "dark"
    assert seen == [bundle]


def test_the_appearance_key_is_recognised_user_state_not_a_config_override():
    """Phase 1 regression, found in the Phase 2 remediation: once a person had
    toggled Light/Dark, every launch reported ``appearance`` in settings.json
    as an unrecognised configuration override. It is remembered user state,
    like ``last_tool``."""
    from shared import config

    assert appearance.SETTINGS_KEY in config.USER_STATE_SETTINGS
    snapshot = config.load(settings_data={appearance.SETTINGS_KEY: appearance.DARK})
    assert not any(appearance.SETTINGS_KEY in str(note) for note in snapshot.diagnostics)
