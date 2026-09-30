"""The six tools as one application -- v0.6.6 Phase 9.

Phases 3-8 each proved one tool against a hand-picked list of its own required
controls. This module treats the six panels as one application and asks the
same questions of every one of them, with no per-tool list to go stale. It
walks **every** interactive widget a panel shows, inside the **real launcher
shell**, at every supported size, in Light and in Dark:

* **No core scrolling, nothing clipped.** Each control is mapped, lies wholly
  inside the content host and the window, is at least as large as it asked to
  be (the flexible lists, editors, browser and logs excepted: they give way,
  within reason), and no two visible controls overlap. The four sections lie
  inside the host, and no Canvas or Scrollbar sits between the panel and a
  section.
* **Family placement.** Activity is to the right of Sections 1 and 2 on the
  guided tools (TTS, Converter, Cover) and below Section 3 on the dense ones
  (MP3 Tool, Maker, Metadata).
* **Keyboard.** Tab reaches every visible, enabled control; it never stops on
  a widget the user cannot see (the Cover browser's two lowered views used to
  be exactly that); and it walks Section 1 -> 2 -> 3 -> Activity.
* **Consistency.** The numbered titles, one section treatment, one Activity
  (Summary | Detailed + Clear Log, the same log colors) and one job-control set
  in every tool, and no ttk widget left on a non-``Compact`` style.
* **Light/Dark in the shell.** The shell's own toggle moves no control of any
  tool -- the one showing or the five hidden -- and rebuilds none.
* **DPI.** The Windows process is DPI-*unaware* (a deliberate v0.6.6 decision,
  ``Decisions.md`` 2026-09-28): Windows bitmap-scales the whole window at
  125%/150% and Tk lays out in the same logical pixels. So the logical client
  areas a maximized window gets on a 1920x1080 display at 125% and 150% are
  measured here, and a tripwire keeps any silent DPI opt-in out of the code.

**Platform-aware.** The sizes are the running shell's own: Windows' 920x600
minimum, 1024x720 default, the 1024x800 macOS minimum, larger and maximized
windows; on aqua the 1024x800 minimum/default, a larger window and maximized.
Nothing here pins a Windows pixel count, so on a Mac this module is the
1024x800 cross-tool gate as it stands.
"""

from __future__ import annotations

import ast
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pytest

import tk_gate
# ``shared.paths`` must be imported at collection: the session-scoped log
# sandbox in ``conftest.py`` redirects only modules already imported, and the
# real launcher built below logs through it.
from shared import appearance, paths, ui_theme  # noqa: F401

TOOLS = ("tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover", "m4b_metadata")
GUIDED = ("tts", "m4b_converter", "cover")  # Family A: Activity on the right
DENSE = ("mp3_tool", "m4b_maker", "m4b_metadata")  # Family B: Activity below

#: The frozen contract's numbered hierarchy (§2), then Activity.
SECTION_TITLES = {
    "tts": ("1. Sources", "2. Voice & Audio", "3. Output & Run"),
    "m4b_converter": ("1. Sources", "2. Conversion & Metadata", "3. Output & Run"),
    "cover": ("1. Sources", "2. Resize Options", "3. Output & Run"),
    "mp3_tool": ("1. Import & Books", "2. Book Settings", "3. Tracks & Run"),
    "m4b_maker": ("1. Import & Books", "2. Book Settings", "3. Tracks, Chapters & Build"),
    "m4b_metadata": ("1. Import & Books", "2. Metadata", "3. Chapters & Save"),
}

#: Widget classes a person operates. Labels, frames and separators are not.
INTERACTIVE = frozenset({
    "TButton", "TCheckbutton", "TRadiobutton", "TEntry", "TCombobox", "TSpinbox",
    "TMenubutton", "TScale", "TNotebook", "Button", "Checkbutton", "Radiobutton",
    "Entry", "Spinbox", "Scale", "Menubutton", "Text", "Listbox", "Treeview", "Canvas",
})
#: The naturally scrollable regions: allowed to give up size (§1), never to
#: vanish.
FLEXIBLE = frozenset({"Text", "Listbox", "Treeview", "Canvas", "TNotebook"})
FLEX_MIN_HEIGHT = 12
FLEX_MIN_WIDTH = 40

#: The Windows process-DPI APIs; none may be called (see the module docstring).
DPI_APIS = frozenset({"SetProcessDpiAwareness", "SetProcessDPIAware",
                      "SetProcessDpiAwarenessContext", "SetThreadDpiAwarenessContext"})
UNIVERSAL = Path(__file__).resolve().parents[2] / "scripts" / "Universal"


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


def _system(root) -> str:
    return root.tk.call("tk", "windowingsystem")


def _geometries(root) -> dict[str, str]:
    """The running shell's supported sizes, by name."""
    system = _system(root)
    if system == "aqua":
        return {"aqua minimum 1024x800": ui_theme.AQUA_GEOMETRY,
                "1280x900": "1280x900", "maximized": "zoomed"}
    sizes = {"minimum 920x600": "{}x{}".format(*ui_theme.MIN_SIZE),
             "default 1024x720": ui_theme.DEFAULT_GEOMETRY,
             "macOS-minimum size 1024x800": ui_theme.AQUA_GEOMETRY,
             "1280x900": "1280x900"}
    if system == "win32":
        # A maximized window's client area on a 1920x1080 display, in the
        # logical pixels a DPI-unaware process sees: the 1032 px work area less
        # the title bar, at 125% and at 150%.
        sizes["125% maximized (1536x800)"] = "1536x800"
        sizes["150% maximized (1280x665)"] = "1280x665"
        sizes["maximized"] = "zoomed"
    return sizes


@pytest.fixture
def fake_settings(monkeypatch):
    """In-memory launcher/appearance storage: no test touches settings.json."""
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
    return store


def _settled(root, times: int = 8) -> None:
    for _ in range(times):
        root.update_idletasks()
        root.update()


class _Shell:
    """The real launcher at one size, every tool built; torn down on exit."""

    def __init__(self, root, geometry: str):
        self.root, self.geometry = root, geometry

    def __enter__(self):
        import launcher

        self.existing = set(self.root.winfo_children())
        self.root.deiconify()
        self.app = launcher.LauncherApp(self.root)
        self.resize(self.geometry)
        for key in TOOLS:
            self.show(key)
        return self

    def resize(self, geometry: str) -> None:
        if geometry == "zoomed":
            self.root.state("zoomed")
        else:
            self.root.state("normal")
            self.root.geometry(geometry)
        _settled(self.root)

    def show(self, key: str):
        self.app.select_tool(key)
        _settled(self.root)
        return self.panel(key)

    def panel(self, key: str):
        return self.app.containers[key].winfo_children()[0]

    def __exit__(self, *_exc):
        try:
            self.root.state("normal")
        except tk.TclError:  # pragma: no cover - a platform without the state
            pass
        for child in list(self.root.winfo_children()):
            if child not in self.existing:
                child.destroy()
        try:
            self.root.protocol("WM_DELETE_WINDOW", "")
        except tk.TclError:  # pragma: no cover - no handler was installed
            pass
        _settled(self.root)
        self.root.withdraw()


# --------------------------------------------------------------------------- #
# Walking a panel
# --------------------------------------------------------------------------- #


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _box(widget) -> tuple[int, int, int, int]:
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    return x, y, x + widget.winfo_width(), y + widget.winfo_height()


def _inside(inner, outer) -> bool:
    return (inner[0] >= outer[0] and inner[1] >= outer[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])


def _overlaps(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _managed(widget, panel) -> bool:
    """Placed by its geometry manager all the way up to the panel -- i.e. the
    panel means to show it. An inactive notebook tab's page is managed but
    unmapped by design, and is excluded by the caller."""
    node = widget
    while node is not None and node is not panel:
        if not node.winfo_manager():
            return False
        node = node.master
    return True


def _in_inactive_tab(widget, panel) -> bool:
    node = widget
    while node is not None and node is not panel:
        parent = node.master
        if parent is not None and parent.winfo_class() == "TNotebook":
            return str(node) != parent.select()
        node = parent
    return False


def _covered(widget, panel) -> bool:
    """Mapped, but beneath a later sibling that covers it (a raised page).

    ``winfo children`` lists siblings in stacking order, lowest first, so any
    mapped sibling after an ancestor that covers the ancestor's whole box hides
    it from view.
    """
    node = widget
    while node is not None and node is not panel:
        parent = node.master
        if parent is None:
            break
        siblings = parent.winfo_children()
        box = _box(node)
        for sibling in siblings[siblings.index(node) + 1:]:
            if (sibling.winfo_ismapped() and not isinstance(sibling, tk.Toplevel)
                    and _inside(box, _box(sibling))):
                return True
        node = parent
    return False


def _name(widget) -> str:
    try:
        text = str(widget.cget("text"))
    except tk.TclError:
        text = ""
    return f"{widget.winfo_class()}[{text[:30]}] {str(widget)[-48:]}"


def _controls(panel) -> list:
    """Every interactive widget the panel means to show."""
    return [w for w in _descendants(panel)
            if w.winfo_class() in INTERACTIVE and _managed(w, panel)
            and not _in_inactive_tab(w, panel)]


def _sections(key, panel) -> list:
    """The three numbered sections and Activity, in contract order."""
    frames = {str(w.cget("text")): w for w in _descendants(panel)
              if w.winfo_class() in ("TLabelframe", "Labelframe")}
    titles = SECTION_TITLES[key] + ("Activity",)
    missing = [title for title in titles if title not in frames]
    assert not missing, f"{key}: sections missing {missing}; found {sorted(frames)}"
    return [frames[title] for title in titles]


def _takes_focus(widget) -> bool:
    try:
        if str(widget.cget("takefocus")) == "0":
            return False
    except tk.TclError:
        return False
    try:
        return not widget.instate(["disabled"])
    except (AttributeError, tk.TclError):
        try:
            return str(widget.cget("state")) != "disabled"
        except tk.TclError:
            return True


def _geometry_problems(shell, key, panel) -> list[str]:
    root, host = shell.root, _box(shell.app.content)
    window = _box(root)
    found = []
    visible = []
    for widget in _controls(panel):
        name = _name(widget)
        if not widget.winfo_ismapped():
            found.append(f"{name}: not on screen")
            continue
        box = _box(widget)
        if not _inside(box, host):
            found.append(f"{name}: {box} outside the content area {host}")
        if not _inside(box, window):
            found.append(f"{name}: outside the window")
        if widget.winfo_class() in FLEXIBLE:
            if widget.winfo_height() < FLEX_MIN_HEIGHT or widget.winfo_width() < FLEX_MIN_WIDTH:
                found.append(f"{name}: collapsed to {widget.winfo_width()}x"
                             f"{widget.winfo_height()}")
        else:
            if widget.winfo_height() < widget.winfo_reqheight() - 1:
                found.append(f"{name}: squeezed to {widget.winfo_height()}px of "
                             f"{widget.winfo_reqheight()} tall")
            if widget.winfo_width() < widget.winfo_reqwidth() - 1:
                found.append(f"{name}: squeezed to {widget.winfo_width()}px of "
                             f"{widget.winfo_reqwidth()} wide")
        if not _covered(widget, panel):
            visible.append(widget)
    for i, a in enumerate(visible):
        for b in visible[i + 1:]:
            if str(b).startswith(str(a) + ".") or str(a).startswith(str(b) + "."):
                continue
            if _overlaps(_box(a), _box(b)):
                found.append(f"{_name(a)} overlaps {_name(b)}")
    sections = _sections(key, panel)
    for section in sections:
        if not (section.winfo_ismapped() and _inside(_box(section), host)):
            found.append(f"section {section.cget('text')!r}: not wholly in the content area")
        node = section.master
        while node is not None and node is not panel:
            if isinstance(node, (tk.Canvas, tk.Scrollbar, ttk.Scrollbar)):
                found.append(f"section {section.cget('text')!r} scrolls inside {_name(node)}")
            node = node.master
    if any(isinstance(w, (tk.Canvas, tk.Scrollbar, ttk.Scrollbar))
           for w in panel.winfo_children()):
        found.append("the panel itself carries a Canvas/Scrollbar")
    one, two, three, activity = (_box(s) for s in sections)
    if key in GUIDED:
        if not activity[0] >= max(one[2], two[2]):
            found.append("Activity is not to the right of Sections 1 and 2")
    elif not activity[1] >= three[3]:
        found.append("Activity is not below Section 3")
    return found


# --------------------------------------------------------------------------- #
# A. Geometry: no core scrolling, nothing clipped, at every supported size
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_every_tool_fits_every_supported_size(fake_settings, tk_root, value):
    """§1's no-core-scroll release contract across all six tools, from the
    minimum to maximized, in Light and Dark."""
    fake_settings[appearance.SETTINGS_KEY] = value
    problems = []
    for label, geometry in _geometries(tk_root).items():
        with _Shell(tk_root, geometry) as shell:
            for key in TOOLS:
                panel = shell.show(key)
                problems += [f"{value} {label} {key}: {p}"
                             for p in _geometry_problems(shell, key, panel)]
    assert not problems, "\n  " + "\n  ".join(problems)


def test_maximized_grows_every_flexible_region(fake_settings, tk_root):
    """§1: when the window grows the lists, editors, browser and logs grow.
    From the platform minimum to maximized, every tool's flexible regions are
    at least as tall and wide as they were, and together strictly larger."""
    minimum = next(iter(_geometries(tk_root).values()))
    measured = {}
    for geometry in (minimum, "zoomed"):
        with _Shell(tk_root, geometry) as shell:
            for key in TOOLS:
                panel = shell.show(key)
                # By position in the walk: two shells name their widgets apart.
                measured[(geometry, key)] = [
                    (_name(w), w.winfo_width(), w.winfo_height())
                    for w in _controls(panel) if w.winfo_class() in FLEXIBLE]
    problems = []
    for key in TOOLS:
        small, large = measured[(minimum, key)], measured[("zoomed", key)]
        assert len(small) == len(large), key
        for (name, width, height), (_same, wide, tall) in zip(small, large):
            if wide < width or tall < height:
                problems.append(f"{key} {name}: {width}x{height} -> {wide}x{tall}")
        if sum(item[2] for item in large) <= sum(item[2] for item in small):
            problems.append(f"{key}: nothing grew")
    assert not problems, "\n  " + "\n  ".join(problems)


# --------------------------------------------------------------------------- #
# B. Keyboard: every visible control reachable, nothing invisible, in order
# --------------------------------------------------------------------------- #


def _tab_stops(panel) -> list:
    """Tab's own walk through the panel, from its first stop back round."""
    stops, node = [], panel.tk_focusNext()
    first = node
    for _ in range(400):
        if node is None:
            break
        if str(node).startswith(str(panel) + "."):
            stops.append(node)
        node = node.tk_focusNext()
        if node is None or node is first:
            break
    return stops


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_tab_reaches_every_visible_control_and_only_visible_ones(
        fake_settings, tk_root, value):
    """§5: keyboard-accessible core controls, in workflow order. At the
    minimum and at the default size (the tight/split and regular layouts)."""
    fake_settings[appearance.SETTINGS_KEY] = value
    problems = []
    sizes = list(_geometries(tk_root).values())[:2]
    for geometry in sizes:
        with _Shell(tk_root, geometry) as shell:
            for key in TOOLS:
                panel = shell.show(key)
                stops = _tab_stops(panel)
                for stop in stops:
                    if not stop.winfo_ismapped() or _covered(stop, panel):
                        problems.append(f"{geometry} {key}: Tab stops on hidden {_name(stop)}")
                wanted = [w for w in _controls(panel) if w.winfo_ismapped()
                          and not _covered(w, panel) and _takes_focus(w)
                          and w.winfo_class() not in ("Text",)]
                for widget in wanted:
                    if widget not in stops:
                        problems.append(f"{geometry} {key}: Tab never reaches {_name(widget)}")
                sections = _sections(key, panel)
                order = []
                for stop in stops:
                    index = next((i for i, s in enumerate(sections)
                                  if str(stop).startswith(str(s) + ".")), None)
                    if index is not None and (not order or order[-1] != index):
                        order.append(index)
                if order != [0, 1, 2, 3]:
                    problems.append(f"{geometry} {key}: Tab visits sections {order}")
    assert not problems, "\n  " + "\n  ".join(problems)


# --------------------------------------------------------------------------- #
# C. One application: sections, Activity, job controls, styles
# --------------------------------------------------------------------------- #


def _activity_signature(panel, native: bool) -> tuple:
    activity = panel.activity
    notebooks = [w for w in _descendants(activity) if w.winfo_class() == "TNotebook"]
    assert len(notebooks) == 1
    notebook = notebooks[0]
    tabs = tuple(notebook.tab(tab, "text") for tab in notebook.tabs())
    buttons = tuple(sorted(str(w.cget("text")) for w in _descendants(activity)
                           if w.winfo_class() == "TButton"))
    logs = tuple(sorted({(str(w.cget("background")), str(w.cget("foreground")),
                          str(w.cget("font")))
                         for w in _descendants(activity) if w.winfo_class() == "Text"}))
    style = "" if native else str(notebook.cget("style"))
    return tabs, buttons, logs, style


@pytest.mark.parametrize("value", [appearance.LIGHT, appearance.DARK])
def test_the_six_tools_share_one_section_activity_and_job_treatment(
        fake_settings, tk_root, value):
    """§2/§3/§5: the numbered titles, one section style, one Activity (only its
    messages differ), one job-control set, and -- where ttk is styled at all --
    nothing left on a generic style."""
    fake_settings[appearance.SETTINGS_KEY] = value
    native = _system(tk_root) == "aqua"  # aqua keeps native ttk controls
    with _Shell(tk_root, "1280x900") as shell:
        activity, jobs, section_styles, strays = {}, {}, set(), []
        for key in TOOLS:
            panel = shell.show(key)
            sections = _sections(key, panel)
            section_styles |= {str(s.cget("style")) for s in sections}
            activity[key] = _activity_signature(panel, native)
            jobs[key] = tuple(sorted(
                (str(button.cget("text")), "" if native else str(button.cget("style")))
                for button in panel.jobs.controls.buttons.values()))
            if not native:
                strays += [f"{key}: {_name(w)} on {w.cget('style')!r}"
                           for w in _descendants(panel)
                           if w.winfo_class().startswith("T") and "style" in w.keys()
                           and not str(w.cget("style")).startswith(appearance.STYLE_PREFIX)]
    assert len(section_styles) == 1, section_styles
    assert len(set(activity.values())) == 1, activity
    tabs, buttons, _logs, _style = activity["tts"]
    assert tabs == ("Summary", "Detailed") and "Clear Log" in buttons
    assert len(set(jobs.values())) == 1, jobs
    assert {text for text, _style in jobs["tts"]} >= {"Pause", "Resume", "Cancel",
                                                      "Retry Failed"}
    assert not strays, "\n  " + "\n  ".join(strays)


# --------------------------------------------------------------------------- #
# D. The shell's Light/Dark toggle moves nothing, in any tool
# --------------------------------------------------------------------------- #


def _layout(shell) -> dict:
    measured = {}
    for key in TOOLS:
        panel = shell.show(key)
        for widget in _controls(panel):
            measured[(key, str(widget))] = (widget, _box(widget), widget.winfo_ismapped())
        measured[(key, "mode")] = (panel, getattr(panel, "density", None),
                                   getattr(panel, "layout_mode", None))
    return measured


def test_the_shell_toggle_moves_and_rebuilds_nothing_in_any_tool(fake_settings, tk_root):
    """Theme switching is presentation-only (§1): toggled from one tool with
    the other five hidden, then back, every control of every tool is the same
    widget in the same place, and each tool keeps its layout mode."""
    fake_settings[appearance.SETTINGS_KEY] = appearance.LIGHT
    minimum = next(iter(_geometries(tk_root).values()))
    with _Shell(tk_root, minimum) as shell:
        before = _layout(shell)
        shell.show("mp3_tool")
        shell.app._toggle_appearance()
        _settled(tk_root)
        assert fake_settings[appearance.SETTINGS_KEY] == appearance.DARK
        dark = _layout(shell)
        shell.app._toggle_appearance()
        _settled(tk_root)
        light = _layout(shell)
    for after in (dark, light):
        assert after.keys() == before.keys()
        moved = [f"{key}: {before[key]} -> {after[key]}" for key in before
                 if before[key] != after[key]]
        assert not moved, "\n  " + "\n  ".join(moved)


# --------------------------------------------------------------------------- #
# E. DPI: the process stays DPI-unaware, so 125%/150% scale the proven layout
# --------------------------------------------------------------------------- #


def test_the_windows_process_is_dpi_unaware_so_the_layout_is_scale_invariant(tk_root):
    """With Tk up, the process has not opted into DPI awareness and Tk lays out
    at 96 logical DPI. Windows therefore bitmap-scales the window at 125% or
    150%, and the logical sizes measured above are exactly what such a display
    shows -- which is why they are a valid 125%/150% proof on a 100% machine."""
    if sys.platform != "win32":
        pytest.skip("process DPI awareness is a Windows concept")
    import ctypes

    awareness = ctypes.c_int(-1)
    assert ctypes.windll.shcore.GetProcessDpiAwareness(
        None, ctypes.byref(awareness)) == 0
    assert awareness.value == 0, "PROCESS_DPI_UNAWARE"
    assert tk_root.winfo_fpixels("1i") == pytest.approx(96.0)


def _dpi_opt_ins(tree: ast.AST) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in DPI_APIS:
            found.append(node.attr)
        elif isinstance(node, ast.Name) and node.id in DPI_APIS:
            found.append(node.id)
        elif isinstance(node, ast.Constant) and node.value in DPI_APIS:
            found.append(node.value)
        elif isinstance(node, ast.Call):
            literals = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if "tk" in literals and "scaling" in literals and len(node.args) > 2:
                found.append("tk scaling")
    return found


def test_no_code_opts_the_process_into_dpi_awareness():
    """A tripwire, not a wish: turning DPI awareness on is a deliberate change
    that must re-measure every fixed pixel metric (see ``Decisions.md``), so it
    cannot arrive by accident. The detector itself is proved on a sample."""
    assert sorted(_dpi_opt_ins(ast.parse(
        "import ctypes\nctypes.windll.shcore.SetProcessDpiAwareness(2)\n"
        "root.tk.call('tk', 'scaling', 1.25)\n"))) == ["SetProcessDpiAwareness",
                                                      "tk scaling"]
    offenders = {}
    files = sorted(UNIVERSAL.rglob("*.py"))
    assert len(files) > 50
    for path in files:
        found = _dpi_opt_ins(ast.parse(path.read_text(encoding="utf-8")))
        if found:
            offenders[str(path.relative_to(UNIVERSAL))] = found
    assert not offenders, offenders
