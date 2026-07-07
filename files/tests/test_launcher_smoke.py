"""Behaviour preservation: the launcher registers all six tools and builds
every panel through the real ``LauncherApp`` with no error panels.

This is the same headless build-all used as the Phase 0 baseline of the
v0.5.0 restructure — 6/6 tools built then, and must keep building.
"""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

EXPECTED_TOOLS = ["tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover", "m4b_metadata"]


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # headless box with no display
        pytest.skip(f"Tk cannot open a display here: {exc}")
    root.withdraw()
    yield root
    root.destroy()


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
