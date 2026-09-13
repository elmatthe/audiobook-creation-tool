"""v0.6.3 focused MP3 plan, Phase 12 — the MP3 Tool must fit the real Aqua shell.

The Mac gate measured the accepted Windows composition under native aqua
metrics and found it does not fit the launcher's content host. Native buttons,
entries and labels are wider and taller than the ACT design's, so the panel
asks for ~1024 px of width where the host offers 771 px at the 1024x720 default
and 667 px at the 920x600 minimum. The consequences, all measured on the real
``LauncherApp`` rather than a widget harness:

* the navigator row (``Previous / Next / Book X of Y / selector / Add /
  Duplicate / Remove``) asks for ~909 px, so ``Remove Book`` is cut off and the
  ``Book X (n of N)`` label is squeezed to nothing — at the default size;
* the ``Retry Failed`` job control's right edge lies past the host at 920x600;
* the ``Add/Remove Time at End of Each Track (seconds)`` label reserves ~308 px
  of column, so the Artist / Album Artist / Album entries collapse to 59 / 68 /
  59 px at 1024x720 and 33 / 42 / 33 px at 920x600;
* the track list and the Summary/Detailed text yield to a single pixel.

These tests are the Phase 12 regression: they build the real launcher, open
the real MP3 Tool through ``select_tool`` and read live geometry. The criteria
are practical rather than pixel snapshots — a control is *reachable* when its
whole bounding box lies inside the content host, an entry is *editable* when
it is at least as wide as it asked to be and shows a handful of characters,
and a list or text region is *usable* when it shows at least two rows.

**The minimum is the platform's.** The first version of this module measured
the composition at the Windows 920x600 minimum too and found the six fixed
bands alone (~440 px) taller than that window's 484 px content host — no
wrap, weight or padding change closes that, only a Mac-only redesign. The
maintainer inspected the remediation on the real launcher and ruled: the
aqua minimum is ``ui_theme.AQUA_MIN_SIZE`` (1024x720, the size the launcher
opens at); Windows keeps 920x600. So the sizes below are the theme's own
default and minimum plus one larger window, and the 920x600 case is retired
by that ruling rather than skipped.

**Aqua only.** The assertions describe native aqua metrics; on Windows the
accepted Phase 11 layout is protected by ``test_mp3_tool_ui.py`` and the
theme suite, and asking Windows to satisfy aqua numbers would be a fake gate.
The module skips itself wherever ``tk windowingsystem`` is not ``aqua``.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import pytest

import tk_gate  # noqa: E402
# ``shared.paths`` must be imported at collection: the session-scoped log
# sandbox in ``conftest.py`` redirects only modules already imported, and the
# real launcher built below logs through it.
from shared import paths  # noqa: E402,F401
from shared import ui_theme  # noqa: E402


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture(scope="module", autouse=True)
def _aqua_only(tk_root):
    """The real windowing system decides, not ``sys.platform``."""
    if tk_root.tk.call("tk", "windowingsystem") != "aqua":
        pytest.skip("aqua geometry regression: native macOS metrics only")


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


def _settled(root, times: int = 6) -> None:
    for _ in range(times):
        root.update_idletasks()
        root.update()


def _fresh_shell(root, geometry):
    """The real launcher at *geometry* with the real MP3 Tool selected.

    Deiconified because every assertion below is about what is genuinely on
    screen: ``winfo_ismapped`` on a withdrawn toplevel says nothing.
    """
    import launcher

    root.deiconify()
    app = launcher.LauncherApp(root)
    root.geometry(geometry)
    _settled(root)
    app.select_tool("mp3_tool")
    _settled(root)
    return app


def _tear_down_shell(root, existing):
    for child in list(root.winfo_children()):
        if child not in existing:
            child.destroy()
    try:
        root.protocol("WM_DELETE_WINDOW", "")
    except tk.TclError:  # pragma: no cover - no handler was installed
        pass
    _settled(root)
    root.withdraw()


#: One window larger than the default, to prove the layout grows with it.
LARGER = "1280x800"


def _geometries(root):
    """The shell's default, its minimum, and a larger window — the theme's own."""
    style = ttk.Style(root)
    theme = ui_theme.apply_theme(root, style)
    return {
        "default": theme["geometry"],
        "minimum": "{}x{}".format(*theme["min_size"]),
        "larger": LARGER,
    }


def _box(widget) -> tuple[int, int, int, int]:
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    return x, y, x + widget.winfo_width(), y + widget.winfo_height()


def _inside(inner, outer) -> bool:
    return (inner[0] >= outer[0] and inner[1] >= outer[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])


def _overlaps(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _linespace(widget) -> int:
    return tkfont.Font(root=widget, font=widget.cget("font")).metrics("linespace")


def _panel(app):
    return app.containers["mp3_tool"].winfo_children()[0]


def _essential_controls(panel) -> dict[str, object]:
    """Every control the focused plan says must stay reachable, by name."""
    nav = panel.navigator
    controls = {
        "Import Folder": panel.btn_import_folder,
        "Previous": nav.buttons[nav.PREVIOUS],
        "Next": nav.buttons[nav.NEXT],
        "Book position": nav.label,
        "Book selector": nav.selector,
        "Add Book": nav.buttons[nav.ADD],
        "Duplicate Book": nav.buttons[nav.DUPLICATE],
        "Remove Book": nav.buttons[nav.REMOVE],
        "Shared artwork Choose": panel.shared_artwork.btn_choose,
        "Shared artwork Clear": panel.shared_artwork.btn_clear,
        "Book artwork Choose": panel.book_artwork.btn_choose,
        "Book artwork Clear": panel.book_artwork.btn_clear,
        "Auto-number": panel.check_auto_number,
        "Start #": panel.entry_start_number,
        "Add Files": panel.btn_add_files,
        "Move Up": panel.btn_move_up,
        "Move Down": panel.btn_move_down,
        "Remove Selected": panel.btn_remove_tracks,
        "Write ID3 Tags": panel.btn_write_id3,
        "Combine": panel.btn_combine,
        "Clear Log": panel.btn_clear_log,
    }
    for action, button in panel.jobs.controls.buttons.items():
        controls[f"job {action.name}"] = button
    for name in panel.surface.fields:
        row = panel.surface._row(name)
        controls[f"Shared {name} entry"] = row.shared_entry
        controls[f"Book {name} entry"] = row.book_entry
    return controls


@pytest.mark.parametrize("which", ["default", "minimum", "larger"])
def test_every_essential_control_is_reachable_in_the_real_shell(
        fake_settings, tk_root, which):
    """Whole bounding box inside the content host, at every supported size.

    Failed on the pre-fix layout: ``Remove Book`` was cut off and the position
    label collapsed at 1024x720 (``Retry Failed`` and ``Remove Selected`` too
    at the since-retired 920x600).
    """
    geometry = _geometries(tk_root)[which]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = _panel(app)
        host = _box(app.content)
        problems = []
        for name, widget in _essential_controls(panel).items():
            if not widget.winfo_ismapped():
                problems.append(f"{name}: not on screen")
                continue
            box = _box(widget)
            if widget.winfo_width() < widget.winfo_reqwidth() - 1:
                problems.append(f"{name}: squeezed to {widget.winfo_width()}px "
                                f"of {widget.winfo_reqwidth()} requested")
            if not _inside(box, host):
                problems.append(f"{name}: box {box} outside host {host}")
        assert not problems, f"at {geometry}:\n  " + "\n  ".join(problems)
    finally:
        _tear_down_shell(tk_root, existing)


@pytest.mark.parametrize("which", ["default", "minimum", "larger"])
def test_primary_and_job_controls_never_overlap(fake_settings, tk_root, which):
    geometry = _geometries(tk_root)[which]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = _panel(app)
        named = {
            "Write ID3 Tags": panel.btn_write_id3,
            "Combine": panel.btn_combine,
            "Clear Log": panel.btn_clear_log,
            "progress": panel.jobs.status.indicator.bar,
        }
        for action, button in panel.jobs.controls.buttons.items():
            named[f"job {action.name}"] = button
        boxes = {name: _box(widget) for name, widget in named.items()}
        names = list(boxes)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                assert not _overlaps(boxes[a], boxes[b]), (
                    f"{a} {boxes[a]} overlaps {b} {boxes[b]} at {geometry}")
    finally:
        _tear_down_shell(tk_root, existing)


@pytest.mark.parametrize("which", ["default", "minimum", "larger"])
def test_the_variable_regions_show_at_least_two_rows(fake_settings, tk_root, which):
    """Yielding space is not collapsing: a list or log you cannot read is not
    a list or log. Two rows is the floor for interacting with content at all."""
    geometry = _geometries(tk_root)[which]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = _panel(app)
        summary_text = next(
            widget for widget in panel.log.frame.winfo_children()[0].winfo_children()
            if isinstance(widget, tk.Text))
        regions = {
            "MP3 Tracks": panel.track_list,
            "Chapter Titles": panel.chapter_text,
            "Summary/Detailed": summary_text,
        }
        problems = []
        for name, widget in regions.items():
            rows = widget.winfo_height() / max(1, _linespace(widget))
            if rows < 2:
                problems.append(f"{name}: {widget.winfo_height()}px shows "
                                f"{rows:.1f} rows")
        assert not problems, f"at {geometry}:\n  " + "\n  ".join(problems)
    finally:
        _tear_down_shell(tk_root, existing)


def test_metadata_editing_is_comfortable_at_the_default_size(fake_settings, tk_root):
    """Artist / Album Artist / Album must not be tiny inputs, and no field
    label may be clipped by the grid, at the size the launcher opens at."""
    geometry = _geometries(tk_root)["default"]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = _panel(app)
        problems = []
        for name in panel.surface.fields:
            row = panel.surface._row(name)
            for side, entry in (("Shared", row.shared_entry), ("Book", row.book_entry)):
                chars = entry.winfo_width() / max(1, _linespace(entry) * 0.6)
                if entry.winfo_width() < entry.winfo_reqwidth() - 1 or chars < 8:
                    problems.append(f"{side} {name} entry: {entry.winfo_width()}px")
            for side, label in (("Shared", row.label), ("Book", row.book_label)):
                if label.winfo_width() < label.winfo_reqwidth() - 1:
                    problems.append(f"{side} {name} label: clipped to "
                                    f"{label.winfo_width()}px of "
                                    f"{label.winfo_reqwidth()}")
        assert not problems, f"at {geometry}:\n  " + "\n  ".join(problems)
    finally:
        _tear_down_shell(tk_root, existing)


def test_the_aqua_minimum_is_the_default_and_the_shell_enforces_it(fake_settings, tk_root):
    """The accepted contract, pinned where it is enforced: the real launcher.

    ``ui_theme.AQUA_MIN_SIZE`` is 1024x720 and equals the geometry the shell
    opens at; the shell's ``minsize`` is that, so a Mac window cannot be
    dragged to a size the composition was never accepted at. Windows keeps
    ``ui_theme.MIN_SIZE`` — see ``test_ui_theme.py``.
    """
    assert ui_theme.AQUA_MIN_SIZE == (1024, 720)
    assert ui_theme.MIN_SIZE == (920, 600)
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, "1024x720")
        assert app.theme["mode"] == "aqua"
        assert tuple(app.theme["min_size"]) == ui_theme.AQUA_MIN_SIZE
        assert app.theme["geometry"] == "1024x720"
        assert tuple(tk_root.minsize()) == ui_theme.AQUA_MIN_SIZE
        # Asking for the old Windows minimum no longer produces a smaller window.
        tk_root.geometry("920x600")
        _settled(tk_root)
        assert tk_root.winfo_width() >= 1024 and tk_root.winfo_height() >= 720
    finally:
        _tear_down_shell(tk_root, existing)


def test_a_larger_window_expands_the_variable_regions(fake_settings, tk_root):
    """No fixed-width whitespace: the lists, the log and the entries grow."""
    def measure(geometry):
        existing = set(tk_root.winfo_children())
        try:
            app = _fresh_shell(tk_root, geometry)
            panel = _panel(app)
            summary_text = next(
                widget for widget in panel.log.frame.winfo_children()[0].winfo_children()
                if isinstance(widget, tk.Text))
            row = panel.surface._row(panel.surface.fields[0])
            return {
                "tracks": panel.track_list.winfo_height(),
                "chapters": panel.chapter_text.winfo_height(),
                "log": summary_text.winfo_height(),
                "entry": row.shared_entry.winfo_width(),
                "chapters_width": panel.chapter_text.winfo_width(),
            }
        finally:
            _tear_down_shell(tk_root, existing)

    small, large = measure("1024x720"), measure(LARGER)
    for name in small:
        assert large[name] > small[name], f"{name}: {small[name]} -> {large[name]}"
