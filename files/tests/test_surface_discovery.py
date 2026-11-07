"""Surface discovery, static and live, and its maintenance check proved on real code (plan sections 7.1 and 10; v0.7.2 Phase 4).

Each control starts from something that passes, adds or changes one thing, and asserts the problem that names it. The live journey's own
negative control (``control.unmapped-live-control-is-caught``) runs the same comparison against a real running instance in the gate.
"""

from __future__ import annotations

import enum
import json
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

from gate_locator import GATE_DIR, REPO_ROOT

sys.path.insert(0, str(GATE_DIR))
from helpers import surface_discovery as sd  # noqa: E402

sys.path.remove(str(GATE_DIR))

PANEL = textwrap.dedent('''
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog


    class Panel(ttk.Frame):
        def __init__(self, master):
            super().__init__(master)
            self.btn_go = ttk.Button(self, text="Go", command=self.go)
            ttk.Button(self, text="Again")
            ttk.Button(self, text="Again")
            self.entry = ttk.Entry(self, textvariable=self.var)
            self.bind("<Configure>", self.resized)
            sock.bind(("127.0.0.1", 0))

        def go(self):
            if not messagebox.askyesno("Replace originals?", "Sure?"):
                return
            filedialog.askopenfilenames(title="Source files")
''')


def _discover(tmp_path: Path, text: str = PANEL) -> dict:
    (tmp_path / "scripts").mkdir(exist_ok=True)
    path = tmp_path / "scripts" / "panel.py"
    path.write_text(text, encoding="utf-8")
    return sd.discover(tmp_path, [path])


def _coverage() -> dict:
    return json.loads((GATE_DIR / "coverage.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Static discovery
# --------------------------------------------------------------------------- #
def test_the_no_change_control_finds_exactly_what_the_file_declares(tmp_path):
    found = _discover(tmp_path)
    assert sorted(found) == [
        "binding:scripts/panel.py::Panel.__init__::bind:<Configure>",
        "dialog:scripts/panel.py::Panel.go::filedialog.askopenfilenames:Source files",
        "dialog:scripts/panel.py::Panel.go::messagebox.askyesno:Replace originals?",
        "widget:scripts/panel.py::Panel.__init__::Button:Again",
        "widget:scripts/panel.py::Panel.__init__::Button:Again#2",
        "widget:scripts/panel.py::Panel.__init__::Button:Go",
        "widget:scripts/panel.py::Panel.__init__::Entry:var=self.var",
    ], "a socket's bind is not a Tk binding, and two identical buttons are numbered"
    assert sd.compare_static({key: "ACT.X.Y" for key in found}, found) == []


def test_a_new_control_is_reported_as_unmapped(tmp_path):
    index = {key: "ACT.X.Y" for key in _discover(tmp_path)}
    added = PANEL.replace('ttk.Button(self, text="Again")\n', 'ttk.Button(self, text="Again")\n        ttk.Checkbutton(self, text="Sneaked in")\n', 1)
    problems = sd.compare_static(index, _discover(tmp_path, added))
    assert problems == ["a static surface nobody has mapped: widget:scripts/panel.py::Panel.__init__::Checkbutton:Sneaked in (scripts/panel.py:11)"]


def test_a_renamed_control_is_both_new_and_gone(tmp_path):
    index = {key: "ACT.X.Y" for key in _discover(tmp_path)}
    problems = sd.compare_static(index, _discover(tmp_path, PANEL.replace('text="Go"', 'text="Start"')))
    assert any("nobody has mapped" in item and "Button:Start" in item for item in problems)
    assert any("no longer declares" in item and "Button:Go" in item and "ACT.X.Y" in item for item in problems)


def test_a_new_dialog_and_a_new_binding_are_reported(tmp_path):
    index = {key: "ACT.X.Y" for key in _discover(tmp_path)}
    added = PANEL.replace("            return\n", '            return\n        messagebox.showerror("Could not save", "x")\n        self.bind_all("<Control-s>", self.go)\n')
    problems = sd.compare_static(index, _discover(tmp_path, added))
    assert len(problems) == 2 and any("Could not save" in item for item in problems) and any("<Control-s>" in item for item in problems)


def test_an_unmapped_control_added_to_a_real_panel_is_caught(tmp_path):
    """The real Cover Image panel, copied, with one button added inside a real method: discovery against the real index names it."""
    real = REPO_ROOT / "scripts" / "artwork" / "cover_resizer.py"
    copy = tmp_path / "scripts" / "artwork" / "cover_resizer.py"
    copy.parent.mkdir(parents=True)
    shutil.copyfile(real, copy)
    index = {key: value for key, value in _coverage()["surfaces"]["static"].items() if "scripts/artwork/cover_resizer.py::" in key}
    clean = sd.discover(tmp_path, [copy])
    assert sd.compare_static(index, clean) == [], "the no-change control: the real file against the real index"
    text = copy.read_text(encoding="utf-8")
    anchor = "    def pause(self) -> None:\n"
    assert text.count(anchor) == 1, "CoverResizerUI.pause moved or was renamed; pick another real one-line method"
    line = text.index(anchor) + len(anchor)
    body = text[line:]
    indent = body[:len(body) - len(body.lstrip())]
    copy.write_text(text[:line] + f"{indent}ttk.Button(self, text=\"Unmapped probe\")\n" + body, encoding="utf-8")
    problems = sd.compare_static(index, sd.discover(tmp_path, [copy]))
    assert len(problems) == 1 and "nobody has mapped" in problems[0] and "Unmapped probe" in problems[0], problems


def test_every_static_surface_of_the_real_application_is_in_the_reviewed_index():
    found = sd.discover(REPO_ROOT, sd.application_files(REPO_ROOT))
    assert len(found) >= 250, "discovery found far fewer surfaces than the application declares; it is broken, not the index"
    assert sd.compare_static(_coverage()["surfaces"]["static"], found) == []


# --------------------------------------------------------------------------- #
# Live trees
# --------------------------------------------------------------------------- #
def _widget(path, cls, parent=".p", key=None, text=None):
    return {"path": path, "class": cls, "parent": parent, "key": key, "text": text, "viewable": True}


def test_live_widgets_are_named_by_their_key_or_their_nearest_kept_ancestor():
    widgets = [_widget(".p", "TFrame", parent="."),
               _widget(".p.box", "TFrame", key="sources"),
               _widget(".p.box.b1", "TButton", parent=".p.box", key="buttons[add]", text="Add"),
               _widget(".p.box.b2", "TButton", parent=".p.box", text="Remove"),
               _widget(".p.box.b3", "TButton", parent=".p.box", text="Remove"),
               _widget(".p.box.e", "TEntry", parent=".p.box", text="PY_VAR12"),
               _widget(".p.l", "TLabel", text="Just a label")]
    named = sd.live_keys(widgets)
    assert sorted(named) == ["buttons[add]", "~sources/TButton:Remove", "~sources/TButton:Remove#2", "~sources/TEntry:"], \
        "a kept widget by its key; others by their kept ancestor and label, repeats numbered, and an entry's PY_VAR text never used"


def test_live_comparison_reports_both_directions_and_nothing_on_a_match():
    seen = {"a": {"class": "TButton", "text": "A"}, "b": {"class": "TEntry"}}
    assert sd.compare_live({"a": "ACT.X.A", "b": "ACT.X.B"}, seen, scope="cover") == []
    problems = sd.compare_live({"a": "ACT.X.A", "gone": "ACT.X.G"}, seen, scope="cover")
    assert problems == ["cover: a live control nobody has mapped: b (TEntry, None)",
                        "cover: an indexed control the running application no longer shows: gone (mapped to ACT.X.G); renamed or removed"]


def _channel():
    sys.path.insert(0, str(GATE_DIR / "adapters" / "windows"))
    try:
        import channel
    finally:
        sys.path.pop(0)
    return channel


class _Which(enum.Enum):
    CANCEL = "cancel"


class _Slotted:
    __slots__ = ("buttons", "spare")

    def __init__(self, buttons):
        self.buttons = buttons


def test_the_key_walk_reads_attributes_slots_and_containers_and_calls_nothing():
    channel = _channel()

    class Fake:
        """Stands where a widget would: the walk is given this type as the widget type, so no Tk is needed."""

    calls = []

    class Owner:
        __module__ = "shared.fake_panel"

        def __init__(self):
            self.go = Fake()
            self.controls = _Slotted({_Which.CANCEL: Fake()})
            self.rows = {"album": Fake()}

        @property
        def trap(self):
            calls.append("property ran")
            return Fake()

    _Slotted.__module__ = "shared.fake_slots"
    found = channel.key_paths(Owner(), widget_type=Fake)
    assert sorted(found.values()) == ["controls.buttons[CANCEL]", "go", "rows[album]"]
    assert calls == [], "the walk ran a property"
