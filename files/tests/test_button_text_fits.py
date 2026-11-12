"""No button's label is cut short, in any of the six tools -- v0.7.2 Phase 5, ACT72-020.

A ttk button given a positive ``width`` gets exactly that many average characters, whatever its text needs. The
artwork "Choose…" buttons of the MP3 Tool, M4B Maker and M4B Metadata Editor had ``width=7``: 52 px for a label that
needs 59, so every one read "Choose." (reproduced at ``fa9d3c3``; first seen in the Metadata Editor at 920x600, but it
was the same at every size and in all three tools).

What a label needs is measured, not assumed: an identical button with ``width=0`` -- ttk's "the natural width of the
text" -- says how wide it must be under the running theme and fonts. Every visible button in every tool, in the real
launcher shell at the Windows minimum and default sizes, must be requested and given at least that.
"""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import appearance, ui_theme  # noqa: E402

import tk_gate  # noqa: E402

TOOLS = ("tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover", "m4b_metadata")


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def shell(tk_root, monkeypatch):
    """The real launcher, every tool built; settings kept in memory."""
    import launcher

    store: dict = {}

    class _Settings:
        @staticmethod
        def get(key, default=None):
            return store.get(key, default)

        @staticmethod
        def set(key, value, **_kwargs):
            store[key] = value
            return True

    monkeypatch.setattr(launcher, "app_settings", _Settings)
    monkeypatch.setattr(appearance, "app_settings", _Settings)
    existing = set(tk_root.winfo_children())
    tk_root.deiconify()
    app = launcher.LauncherApp(tk_root)
    try:
        yield app
    finally:
        for child in list(tk_root.winfo_children()):
            if child not in existing:
                child.destroy()
        try:
            tk_root.protocol("WM_DELETE_WINDOW", "")
        except tk.TclError:  # pragma: no cover - no handler was installed
            pass
        _settle(tk_root)
        tk_root.geometry("")
        tk_root.withdraw()


def _settle(root) -> None:
    for _ in range(8):
        root.update_idletasks()
        root.update()


def _needs(button) -> int:
    twin = ttk.Button(button.master, text=button.cget("text"), style=button.cget("style"), width=0)
    try:
        return twin.winfo_reqwidth()
    finally:
        twin.destroy()


@pytest.mark.parametrize("geometry", ("{}x{}".format(*ui_theme.MIN_SIZE), ui_theme.DEFAULT_GEOMETRY))
def test_every_visible_button_is_at_least_as_wide_as_its_label(shell, tk_root, geometry):
    tk_root.geometry(geometry)
    _settle(tk_root)
    short, seen = [], 0
    for key in TOOLS:
        shell.select_tool(key)
        _settle(tk_root)
        stack = [shell.containers[key]]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if widget.winfo_class() != "TButton" or not widget.winfo_viewable() or not str(widget.cget("text")):
                continue
            seen += 1
            need = _needs(widget)
            if min(widget.winfo_reqwidth(), widget.winfo_width()) < need:
                short.append((key, str(widget.cget("text")), widget.winfo_reqwidth(), widget.winfo_width(), need))
    assert seen > 40, f"only {seen} buttons were measured: this check has lost its subject"
    assert not short, f"buttons narrower than their labels at {geometry} (tool, text, requested, given, needed): {short}"
