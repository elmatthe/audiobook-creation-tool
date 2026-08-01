"""Behaviour preservation: the launcher registers all six tools and builds
every panel through the real ``LauncherApp`` with no error panels.

This is the same headless build-all used as the Phase 0 baseline of the
v0.5.0 restructure — 6/6 tools built then, and must keep building.

v0.6.0 Drop 1 Phase 2 converted the *Windows shell* (nav rail, header, content
card, status bar). The lifecycle contract below is what proves the conversion
did not cost anything: six tools in order, build-once containers, state that
survives switching, saved/fallback selection, launcher chrome on the intended
``ACT.*`` styles — and child-panel contents that inherit none of them.
"""

from __future__ import annotations

import sys

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

EXPECTED_TOOLS = ["tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover", "m4b_metadata"]

#: The Windows shell only exists on win32 — ``apply_theme`` routes on the real
#: platform, and monkeypatching ``sys.platform`` for a *whole launcher build*
#: would also lie to the six tool modules while they construct.
windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="the ACT Windows shell only builds on win32"
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
def fresh_root(tk_root):
    """A root with no leftover shell, so each test builds its own launcher."""
    for child in tk_root.winfo_children():
        child.destroy()
    yield tk_root
    for child in tk_root.winfo_children():
        child.destroy()


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


@pytest.fixture
def error_recorder(monkeypatch):
    """Collects every tool that fell back to the launcher's error panel."""
    import launcher

    failures: list[str] = []
    orig = launcher.LauncherApp._show_load_error

    def record_error(self, container, spec, exc):
        failures.append(f"{spec.key}: {type(exc).__name__}: {exc}")
        orig(self, container, spec, exc)

    monkeypatch.setattr(launcher.LauncherApp, "_show_load_error", record_error)
    return failures


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _style_of(widget) -> str:
    try:
        return str(widget.cget("style"))
    except tk.TclError:  # a classic tk widget has no -style option
        return ""


def _first_entry(container):
    for widget in _walk(container):
        if isinstance(widget, (ttk.Entry, tk.Entry)):
            return widget
    return None


def test_all_six_tools_build_without_error_panels(tk_root, tmp_path, monkeypatch):
    import launcher
    from shared import paths

    # select_tool() persists last_tool; snapshot settings.json so the test
    # leaves no trace.
    settings_file = paths.SETTINGS_FILE
    backup = settings_file.read_bytes() if settings_file.exists() else None

    failures: list[str] = []
    orig = launcher.LauncherApp._show_load_error

    def record_error(self, container, spec, exc):
        failures.append(f"{spec.key}: {type(exc).__name__}: {exc}")
        orig(self, container, spec, exc)

    monkeypatch.setattr(launcher.LauncherApp, "_show_load_error", record_error)

    try:
        app = launcher.LauncherApp(tk_root)
        tools = app._available_tools()
        assert [t.key for t in tools] == EXPECTED_TOOLS
        for spec in tools:
            app.select_tool(spec.key)
        tk_root.update_idletasks()
        assert failures == []
        assert len(app.containers) == len(EXPECTED_TOOLS)
    finally:
        if backup is not None:
            settings_file.write_bytes(backup)


# ---------------------------------------------------------------------------
# Lifecycle: registry order, build-once containers, preserved state
# ---------------------------------------------------------------------------

def test_registry_order_is_unchanged_by_the_shell(fresh_root, fake_settings):
    """Whichever shell is built, the six tools stay in their existing order."""
    import launcher

    assert [t.key for t in launcher.TOOLS] == EXPECTED_TOOLS
    app = launcher.LauncherApp(fresh_root)
    assert [t.key for t in app._available_tools()] == EXPECTED_TOOLS
    # Every available tool got a navigation control in the same order.
    assert list(app.buttons) == EXPECTED_TOOLS


def test_panels_are_built_once_and_switching_does_not_rebuild(
    fresh_root, fake_settings, error_recorder
):
    import launcher

    app = launcher.LauncherApp(fresh_root)
    keys = [t.key for t in app._available_tools()]
    for key in keys:
        app.select_tool(key)
    fresh_root.update_idletasks()
    assert error_recorder == []

    first_pass = {key: app.containers[key] for key in keys}
    assert len(first_pass) == len(EXPECTED_TOOLS)

    # Two more full sweeps: same container objects, no new containers, and
    # still no error panel.
    for _ in range(2):
        for key in keys:
            app.select_tool(key)
    fresh_root.update_idletasks()

    assert error_recorder == []
    assert len(app.containers) == len(keys)
    for key in keys:
        assert app.containers[key] is first_pass[key], f"{key} was rebuilt"


def test_panel_state_survives_switching_away_and_back(
    fresh_root, fake_settings, error_recorder
):
    """A harmless typed value must still be there after leaving and returning."""
    import launcher

    marker = "ACT-STATE-MARKER"
    app = launcher.LauncherApp(fresh_root)
    app.select_tool("m4b_metadata")
    fresh_root.update_idletasks()
    assert error_recorder == []

    container = app.containers["m4b_metadata"]
    entry = _first_entry(container)
    assert entry is not None, "no text field found to use as a state marker"
    entry.delete(0, "end")
    entry.insert(0, marker)

    for key in ("tts", "mp3_tool", "cover", "m4b_metadata"):
        app.select_tool(key)
    fresh_root.update_idletasks()

    assert app.containers["m4b_metadata"] is container
    assert entry.get() == marker
    assert app.current_key == "m4b_metadata"


# ---------------------------------------------------------------------------
# Saved selection and safe fallback
# ---------------------------------------------------------------------------

def test_valid_saved_tool_is_restored(fresh_root, fake_settings, error_recorder):
    import launcher

    fake_settings["last_tool"] = "mp3_tool"
    app = launcher.LauncherApp(fresh_root)
    fresh_root.update_idletasks()

    assert app.current_key == "mp3_tool"
    assert error_recorder == []
    # Only the restored tool was built — the rest are still lazy.
    assert list(app.containers) == ["mp3_tool"]


def test_invalid_saved_tool_falls_back_to_the_first_available(
    fresh_root, fake_settings, error_recorder
):
    import launcher

    fake_settings["last_tool"] = "a_tool_that_never_existed"
    app = launcher.LauncherApp(fresh_root)
    fresh_root.update_idletasks()

    assert app.current_key == app._available_tools()[0].key == "tts"
    assert error_recorder == []


def test_unavailable_saved_tool_falls_back_safely(
    fresh_root, fake_settings, error_recorder, monkeypatch
):
    """A saved tool whose module has gone missing must not strand the launcher."""
    import launcher

    monkeypatch.setattr(launcher.LauncherApp, "_module_exists",
                        staticmethod(lambda module: False))
    fake_settings["last_tool"] = "m4b_metadata"
    app = launcher.LauncherApp(fresh_root)
    fresh_root.update_idletasks()

    available = [t.key for t in app._available_tools()]
    assert "m4b_metadata" not in available
    assert available == EXPECTED_TOOLS[:-1]
    assert app.current_key == "tts"
    assert "m4b_metadata" not in app.buttons
    assert error_recorder == []


# ---------------------------------------------------------------------------
# Windows shell: namespaced chrome, and isolation from the child panels
# ---------------------------------------------------------------------------

@windows_only
def test_windows_shell_chrome_uses_act_styles(fresh_root, fake_settings):
    import launcher

    app = launcher.LauncherApp(fresh_root)
    s = app.theme["styles"]
    assert app.theme["mode"] == "windows"

    for key, button in app.buttons.items():
        assert str(button.cget("style")) == s["nav_button"], key
    assert str(app._toolbar_title.cget("style")) == s["title"]
    assert str(app._toolbar_desc.cget("style")) == s["status_label"]
    assert str(app._status_label.cget("style")) == s["status_label"]
    assert str(app._log_button.cget("style")) == s["ghost_button"]

    # Every styled widget in the shell is inside the namespace, and the shell
    # actually uses it (a silently-unstyled shell would also pass "no leak").
    used = {_style_of(w) for w in _walk(fresh_root)} - {""}
    assert used, "the Windows shell applied no styles at all"
    assert all(name.startswith("ACT.") for name in used), sorted(used)

    # The base theme is still the native one, so unconverted panels are safe.
    assert app.theme["base_theme"] == "vista"
    assert ttk.Style(fresh_root).theme_use() == "vista"


@windows_only
def test_windows_selected_tool_state_and_status(fresh_root, fake_settings,
                                                error_recorder):
    """Selection is the ttk ``selected`` flag, and the header/status follow."""
    import launcher

    app = launcher.LauncherApp(fresh_root)
    app.select_tool("m4b_maker")
    fresh_root.update_idletasks()
    assert error_recorder == []

    spec = next(t for t in launcher.TOOLS if t.key == "m4b_maker")
    assert "selected" in app.buttons["m4b_maker"].state()
    for key, button in app.buttons.items():
        if key != "m4b_maker":
            assert "selected" not in button.state(), key
        # Unlike the classic cue, no row is disabled — every one stays
        # reachable by keyboard.
        assert "disabled" not in button.state(), key

    assert app._toolbar_title.cget("text") == spec.title
    assert app._toolbar_desc.cget("text") == spec.description
    assert app.status_var.get() == f"{spec.title} — ready."

    # Switching moves the flag rather than accumulating it.
    app.select_tool("cover")
    assert "selected" not in app.buttons["m4b_maker"].state()
    assert "selected" in app.buttons["cover"].state()


@windows_only
def test_child_panels_do_not_inherit_act_styles(fresh_root, fake_settings,
                                                error_recorder):
    """The five unconverted panels (and the sixth, pre-Phase-3) stay generic."""
    import launcher

    app = launcher.LauncherApp(fresh_root)
    for spec in app._available_tools():
        app.select_tool(spec.key)
    fresh_root.update_idletasks()
    assert error_recorder == [], "an error panel would be launcher-owned chrome"

    offenders = []
    counted = 0
    for key, container in app.containers.items():
        for widget in _walk(container):
            counted += 1
            style = _style_of(widget)
            if style.startswith("ACT."):
                offenders.append((key, str(widget), style))
    assert counted > 0
    assert offenders == [], f"panel contents inherited shell styles: {offenders}"

    # The swap host and every tool container are deliberately unstyled, which
    # is *why* nothing inherits: there is nothing to inherit from.
    assert str(app.content.cget("style")) == ""
    for key, container in app.containers.items():
        assert str(container.cget("style")) == "", key

    # And the generic styles the panels render with are still the native ones.
    style = ttk.Style(fresh_root)
    assert style.lookup("TButton", "background") == "SystemButtonFace"
    assert style.lookup("TFrame", "background") == "SystemButtonFace"
    assert style.lookup(app.theme["styles"]["primary_button"], "background") \
        == app.theme["colors"]["accent"]
