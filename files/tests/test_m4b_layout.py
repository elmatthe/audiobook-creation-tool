"""v0.6.4 Phase 13 — the M4B Maker and M4B Metadata Editor must fit the real Aqua shell.

The Mac parity gate measured the accepted Windows compositions of both M4B
tools under native aqua metrics, in the real ``LauncherApp`` at the aqua
minimum of the time (1024x720, the size the launcher opened at), and found
four places where the layout asks for more width than the 771 px content
host has:

* the import band: ``Import Folder`` / ``Clear All Imports`` (Phase 12
  amendment) / the import status bar / the output-folder hint (and, on the
  Editor, ``Open Output Folder``) ask for ~1087 / ~1373 px, so the status bar
  — the only place the running scan and its ``Cancel Import`` appear — is
  squeezed to one pixel, the hint runs past the host, and the Editor's
  ``Open Output Folder`` lies entirely outside it;
* the Shared / Current Book band: five (Maker) or seven (Editor) fields plus
  the artwork control on one row, so every entry is squeezed below the eight
  characters it asked for — the Editor's to 61 px;
* the Maker's Book-only row (Title / Series Part / Output Filename / Status)
  needs ~769 px in the ~481 px it has beside the artwork, so ``Status`` runs
  past the host;
* the Maker's run-options row needs ~854 px, so ``Choose custom destination``
  is cut off.

And one of height: the fixed bands alone left the Maker 154 px and the Editor
102 px for their tracks / chapter editor / log, where two readable rows of
each need ~175 and ~137 — before any of the width remedies, each of which
folds a band onto more lines. The maintainer ruled (2026-09-15) that the
macOS minimum, and the size the launcher opens at, is ``ui_theme.AQUA_MIN_SIZE``
= 1024x800; Windows keeps 920x600. The remedies are aqua layout hints read
through each panel's ``_layout_hints`` seam with the Windows values as
defaults — the same mechanism as the MP3 Tool's Phase 12 fix.

These tests are the Phase 13 regression, in the shape of the MP3 Tool's
Phase 12 one (``test_mp3_tool_layout.py``): build the real launcher, open the
real tool through ``select_tool`` and read live geometry at the theme's
default, its minimum and one larger window. A control is *reachable* when its
whole bounding box lies inside the content host and it is at least as wide as
it asked to be; an entry is *editable* when it is as wide as requested and
shows a handful of characters; a list or text region is *usable* when it
shows at least two rows. The output-folder hint is a display label that may
yield width to keep the controls beside it whole, so it is only required to
stay inside the host.

**Aqua only.** The assertions describe native aqua metrics; on Windows the
accepted Phase 6 / Phase 10 layouts are protected by the two panel suites,
and asking Windows to satisfy aqua numbers would be a fake gate. The module
skips itself wherever ``tk windowingsystem`` is not ``aqua``.
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


TOOLS = ("m4b_maker", "m4b_metadata")


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


def _fresh_shell(root, geometry, tool):
    """The real launcher at *geometry* with the real *tool* selected.

    Deiconified because every assertion below is about what is genuinely on
    screen: ``winfo_ismapped`` on a withdrawn toplevel says nothing.
    """
    import launcher

    root.deiconify()
    app = launcher.LauncherApp(root)
    root.geometry(geometry)
    _settled(root)
    app.select_tool(tool)
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


#: One window larger than the default in both dimensions, to prove the
#: layout grows with it.
LARGER = "1280x900"


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


def _panel(app, tool):
    return app.containers[tool].winfo_children()[0]


#: Display labels that may yield width so the controls beside them stay whole.
YIELDING = ("Output folder",)


def _essential_controls(tool, panel) -> dict[str, object]:
    """Every control the plan says must stay reachable, by name."""
    nav = panel.navigator
    controls = {
        "Import Folder": panel.btn_import_folder,
        "Clear All Imports": panel.btn_clear_imports,
        "Import status": panel.import_status.frame,
        "Output folder": panel.output_label,
        "Previous": nav.buttons[nav.PREVIOUS],
        "Next": nav.buttons[nav.NEXT],
        "Book position": nav.label,
        "Book selector": nav.selector,
        "Remove Book": nav.buttons[nav.REMOVE],
        "Shared artwork Choose": panel.shared_artwork.btn_choose,
        "Shared artwork Clear": panel.shared_artwork.btn_clear,
        "Book artwork Choose": panel.book_artwork.btn_choose,
        "Book artwork Clear": panel.book_artwork.btn_clear,
        "Auto-number": panel.check_auto_number,
        "Start Part": panel.entry_start_part,
        "Status": panel.status_label,
        "Clear Log": panel.btn_clear_log,
    }
    if tool == "m4b_maker":
        controls.update({
            "Add Book": nav.buttons[nav.ADD],
            "Duplicate Book": nav.buttons[nav.DUPLICATE],
            "Add Files": panel.btn_add_files,
            "Move Up": panel.btn_move_up,
            "Move Down": panel.btn_move_down,
            "Remove Selected": panel.btn_remove_tracks,
            "Try FAST first": panel.check_fast_first,
            "Choose custom destination": panel.chk_custom_dest,
            "Build M4B(s)": panel.btn_build,
        })
        for key, entry in panel.book_entries.items():
            controls[f"Book {key} entry"] = entry
    else:
        controls.update({
            "Add Files": panel.btn_add_files,
            "Open Output Folder": panel.btn_open_out,
            "Preserve hint": panel.hint_label,
            "Read-back": panel.readback_label,
            "Save Tags": panel.btn_save,
            "Clear All Tags": panel.btn_clear_tags,
            "Remove Series Numbering": panel.btn_remove_numbering,
        })
    for action, button in panel.jobs.controls.buttons.items():
        controls[f"job {action.name}"] = button
    for name in panel.surface.fields:
        row = panel.surface._row(name)
        controls[f"Shared {name} entry"] = row.shared_entry
        controls[f"Book {name} entry"] = row.book_entry
    return controls


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("which", ["default", "minimum", "larger"])
def test_every_essential_control_is_reachable_in_the_real_shell(
        fake_settings, tk_root, tool, which):
    """Whole bounding box inside the content host, at every supported size.

    Failed on the pre-fix layouts at 1024x720: the import status bar was one
    pixel wide and the output hint ran past the host on both tools, the
    Editor's ``Open Output Folder`` lay entirely outside it, the Maker's
    ``Status`` and ``Choose custom destination`` were cut off, and every
    Shared / Book entry was narrower than it asked to be.
    """
    geometry = _geometries(tk_root)[which]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry, tool)
        panel = _panel(app, tool)
        host = _box(app.content)
        problems = []
        for name, widget in _essential_controls(tool, panel).items():
            if not widget.winfo_ismapped():
                problems.append(f"{name}: not on screen")
                continue
            box = _box(widget)
            if (name not in YIELDING
                    and widget.winfo_width() < widget.winfo_reqwidth() - 1):
                problems.append(f"{name}: squeezed to {widget.winfo_width()}px "
                                f"of {widget.winfo_reqwidth()} requested")
            if not _inside(box, host):
                problems.append(f"{name}: box {box} outside host {host}")
        assert not problems, f"{tool} at {geometry}:\n  " + "\n  ".join(problems)
    finally:
        _tear_down_shell(tk_root, existing)


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("which", ["default", "minimum", "larger"])
def test_no_essential_controls_overlap(fake_settings, tk_root, tool, which):
    """Folding a band onto more lines must not stack anything on anything:
    the artwork control beside the fields, the Book-only row, the options and
    the primary / job controls each keep their own space."""
    geometry = _geometries(tk_root)[which]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry, tool)
        panel = _panel(app, tool)
        named = _essential_controls(tool, panel)
        named["progress"] = panel.jobs.status.indicator.bar
        boxes = {name: _box(widget) for name, widget in named.items()
                 if widget.winfo_ismapped()}
        names = list(boxes)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                assert not _overlaps(boxes[a], boxes[b]), (
                    f"{a} {boxes[a]} overlaps {b} {boxes[b]} — {tool} at {geometry}")
    finally:
        _tear_down_shell(tk_root, existing)


def _regions(tool, panel) -> dict[str, object]:
    summary_text = next(
        widget for widget in panel.log.frame.winfo_children()[0].winfo_children()
        if isinstance(widget, tk.Text))
    regions = {"Chapter Titles": panel.chapter_text, "Summary/Detailed": summary_text}
    if tool == "m4b_maker":
        regions["MP3 Tracks"] = panel.track_list
    return regions


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("which", ["default", "minimum", "larger"])
def test_the_variable_regions_show_at_least_two_rows(fake_settings, tk_root, tool, which):
    """Yielding space is not collapsing: a list or log you cannot read is not
    a list or log. Two rows is the floor for interacting with content at all."""
    geometry = _geometries(tk_root)[which]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry, tool)
        panel = _panel(app, tool)
        problems = []
        for name, widget in _regions(tool, panel).items():
            rows = widget.winfo_height() / max(1, _linespace(widget))
            if rows < 2:
                problems.append(f"{name}: {widget.winfo_height()}px shows "
                                f"{rows:.1f} rows")
        assert not problems, f"{tool} at {geometry}:\n  " + "\n  ".join(problems)
    finally:
        _tear_down_shell(tk_root, existing)


@pytest.mark.parametrize("tool", TOOLS)
def test_metadata_editing_is_comfortable_at_the_default_size(fake_settings, tk_root, tool):
    """No Shared / Book field may be a tiny input, and no field label may be
    clipped by the grid, at the size the launcher opens at."""
    geometry = _geometries(tk_root)["default"]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry, tool)
        panel = _panel(app, tool)
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
        assert not problems, f"{tool} at {geometry}:\n  " + "\n  ".join(problems)
    finally:
        _tear_down_shell(tk_root, existing)


@pytest.mark.parametrize("tool", TOOLS)
def test_nothing_scrolls_the_whole_tool(fake_settings, tk_root, tool):
    """The lists and the log scroll; the tool itself never does."""
    geometry = _geometries(tk_root)["minimum"]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry, tool)
        panel = _panel(app, tool)
        assert not any(isinstance(w, tk.Canvas) for w in panel.winfo_children())
        assert not any(isinstance(w, (tk.Scrollbar, ttk.Scrollbar))
                       for w in panel.winfo_children())
    finally:
        _tear_down_shell(tk_root, existing)


@pytest.mark.parametrize("tool", TOOLS)
def test_a_larger_window_expands_the_variable_regions(fake_settings, tk_root, tool):
    """No fixed-width whitespace: the lists, the log and the entries grow."""
    def measure(geometry):
        existing = set(tk_root.winfo_children())
        try:
            app = _fresh_shell(tk_root, geometry, tool)
            panel = _panel(app, tool)
            regions = _regions(tool, panel)
            row = panel.surface._row(panel.surface.fields[0])
            measured = {name: widget.winfo_height() for name, widget in regions.items()}
            measured["entry"] = row.shared_entry.winfo_width()
            measured["chapters_width"] = panel.chapter_text.winfo_width()
            return measured
        finally:
            _tear_down_shell(tk_root, existing)

    small, large = measure(_geometries(tk_root)["default"]), measure(LARGER)
    for name in small:
        assert large[name] > small[name], f"{tool} {name}: {small[name]} -> {large[name]}"


def test_the_aqua_minimum_is_the_default_and_the_shell_enforces_it(fake_settings, tk_root):
    """The ruled contract, pinned where it is enforced: the real launcher.

    ``ui_theme.AQUA_MIN_SIZE`` is 1024x800 (v0.6.4 Phase 13 maintainer
    ruling, superseding the 1024x720 of v0.6.3) and equals the geometry the
    shell opens at; the shell's ``minsize`` is that, so a Mac window cannot
    be dragged to a size the composition was never accepted at. Windows keeps
    ``ui_theme.MIN_SIZE`` — see ``test_ui_theme.py``.
    """
    assert ui_theme.AQUA_MIN_SIZE == (1024, 800)
    assert ui_theme.MIN_SIZE == (920, 600)
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, "1024x800", "m4b_metadata")
        assert app.theme["mode"] == "aqua"
        assert tuple(app.theme["min_size"]) == ui_theme.AQUA_MIN_SIZE
        assert app.theme["geometry"] == "1024x800"
        assert tuple(tk_root.minsize()) == ui_theme.AQUA_MIN_SIZE
        # Asking for the earlier aqua minimum no longer produces a smaller window.
        tk_root.geometry("1024x720")
        _settled(tk_root)
        assert tk_root.winfo_width() >= 1024 and tk_root.winfo_height() >= 800
    finally:
        _tear_down_shell(tk_root, existing)
