"""v0.6.1 Plan 4 Phase 12 Block 1 — the Cover browser must hydrate as it scrolls.

The maintainer's Block 1 run found, with `B-cover-browser` (34 images):

* Details showed real dimensions/format/size for the first screenful and a
  permanent ``…`` for everything below it;
* Medium Thumbnails drew the first screenful and left the rest blank;
* the mouse wheel did nothing over the thumbnail viewport, while the scrollbar
  worked.

Reproduced here on the real panel before any fix — 11/34 metadata rows and 10/34
thumbnails hydrated, and **still 11/34 and 10/34 after scrolling to the bottom**.

The cause is one gap, not three. ``CoverBrowser.request_visible()`` is reached
only from ``refresh()``, and ``refresh()`` runs on construction, a view switch, or
a manager *revision* change. Scrolling is none of those, so the visible span was
computed once and never recomputed. ``_render_tiles`` compounds it for thumbnails:
it draws only ``self._order[start:stop]`` while setting ``scrollregion`` for every
row, so scrolling reveals canvas area that was never drawn at all.

The wheel is a separate, smaller fact: ``ttk.Treeview`` has ``<MouseWheel>`` in its
**class** bindings, so Details and List scrolled for free, while ``tk.Canvas`` has
no such class binding and nothing in this panel supplied one.

These tests fail on the pre-fix code for the reasons above, not incidentally.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from mp3_tools import cover_resizer

from test_cover_browser import (  # noqa: F401 - fixtures are used by name
    RecordingRunner,
    import_into,
    make_image,
    make_panel,
    tk_root,
)


def _many(tmp_path: Path, count: int = 34) -> tuple[Path, ...]:
    """Enough images to exceed one screenful — the count the defect needs."""
    return tuple(make_image(tmp_path / f"browse-{i:02d}.png", fmt="PNG")
                 for i in range(count))


class _Viewport:
    """A movable viewport seam: the visible window can be scrolled in the test."""

    def __init__(self, size: int = 10):
        self.size = size
        self.offset = 0

    def __call__(self, _view: str, count: int) -> tuple[float, float]:
        if count <= 0:
            return (0.0, 0.0)
        first = min(self.offset, max(0, count - self.size)) / count
        last = min(1.0, (min(self.offset, count) + self.size) / count)
        return (first, last)

    def scroll_to(self, index: int) -> None:
        self.offset = index


def _loaded(make_panel, tmp_path, count=34, size=10):
    viewport = _Viewport(size)
    runner = RecordingRunner()
    panel = make_panel(preview_runner=runner, viewport=viewport)
    import_into(panel, *_many(tmp_path, count))
    panel.browser.refresh()
    return panel, viewport, runner


def _sized_canvas(panel, tk_root):
    """The thumbnail canvas, mapped and with a real viewport.

    Both steps matter and both were learned the hard way. ``make_panel`` never
    packs the panel and the shared root is withdrawn, and **Tk does not deliver
    ``<MouseWheel>`` to an unmapped widget at all** — verified directly: the same
    binding fires once the widget is mapped and never before. An unmapped canvas
    also reports ~1px of height, so Tk's scroll unit rounds to zero. Neither has
    anything to do with the binding under test, so the test supplies both.
    """
    tk_root.deiconify()
    panel.pack(fill="both", expand=True)
    canvas = panel.browser.canvas
    canvas.configure(scrollregion=(0, 0, 400, 4000), height=240, width=400,
                     yscrollincrement=20)
    tk_root.update_idletasks()
    tk_root.update()
    assert canvas.winfo_ismapped(), "the canvas must be mapped to receive the wheel"
    return canvas


@pytest.fixture
def hidden_root_again(tk_root):
    """Leave the shared root withdrawn for every other test in the session."""
    yield tk_root
    tk_root.withdraw()
    tk_root.update_idletasks()


def _hydrated_facts(panel) -> int:
    return sum(1 for o in panel.browser._order
               if panel.browser._facts.get(o) is not None)


def _hydrated_images(panel) -> int:
    return sum(1 for o in panel.browser._order
               if panel.browser.cache.peek(o) is not None)


# --------------------------------------------------------------------------- #
# A. Details metadata hydrates as the view scrolls
# --------------------------------------------------------------------------- #
def test_details_hydrates_rows_that_scroll_into_view(make_panel, tmp_path):
    panel, viewport, _runner = _loaded(make_panel, tmp_path)
    panel.browser.set_view(cover_resizer.VIEW_DETAILS)
    first_pass = _hydrated_facts(panel)
    assert 0 < first_pass < 34, "fixture must not fit on one screen"

    viewport.scroll_to(24)
    panel.browser.notify_scrolled()
    assert _hydrated_facts(panel) > first_pass, (
        "rows scrolled into view never had their metadata requested")


def test_scrolling_to_the_bottom_leaves_no_stuck_placeholder(make_panel, tmp_path):
    panel, viewport, _runner = _loaded(make_panel, tmp_path)
    panel.browser.set_view(cover_resizer.VIEW_DETAILS)
    for offset in range(0, 34, 5):
        viewport.scroll_to(offset)
        panel.browser.notify_scrolled()
    assert _hydrated_facts(panel) == 34


def test_a_row_never_clicked_still_shows_real_metadata(make_panel, tmp_path):
    """The exact symptom: valid *visible* rows stayed '…' until interacted with.

    Only the visible span is asserted, because hydration is deliberately lazy —
    a row that has never been on screen showing a placeholder is the design, and
    demanding otherwise would turn a 3,000-image import into 3,000 decodes.
    """
    panel, viewport, _runner = _loaded(make_panel, tmp_path)
    panel.browser.set_view(cover_resizer.VIEW_DETAILS)
    viewport.scroll_to(24)
    panel.browser.notify_scrolled()

    start, stop = panel.browser.visible_range()
    visible_ids = set(panel.browser._order[start:stop])
    assert visible_ids, "the viewport seam produced an empty span"
    tree = panel.browser.details
    stuck = [tree.item(iid, "values")[0] for iid in tree.get_children("")
             if iid in visible_ids
             and any(v == cover_resizer.PENDING_TEXT
                     for v in tree.item(iid, "values"))]
    assert not stuck, f"visible rows still showing {cover_resizer.PENDING_TEXT}: {stuck}"
    assert panel.manager.selection == (), "nothing was selected to achieve this"


def test_an_unreadable_file_stays_truthful_rather_than_fabricated(
        make_panel, tmp_path):
    from test_cover_browser import make_broken

    viewport = _Viewport(10)
    panel = make_panel(preview_runner=RecordingRunner(), viewport=viewport)
    good = _many(tmp_path, 12)
    bad = make_broken(tmp_path / "broken.png")
    import_into(panel, *good, bad)
    panel.browser.refresh()
    panel.browser.set_view(cover_resizer.VIEW_DETAILS)
    viewport.scroll_to(12)
    panel.browser.notify_scrolled()

    tree = panel.browser.details
    values = {v[0]: v for v in
              (tree.item(i, "values") for i in tree.get_children(""))}
    assert "broken.png" in values
    assert cover_resizer.UNAVAILABLE_TEXT in values["broken.png"]


# --------------------------------------------------------------------------- #
# B. Thumbnails hydrate and are drawn as the view scrolls
# --------------------------------------------------------------------------- #
def test_thumbnails_hydrate_tiles_that_scroll_into_view(make_panel, tmp_path):
    panel, viewport, _runner = _loaded(make_panel, tmp_path)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    first_pass = _hydrated_images(panel)
    assert 0 < first_pass < 34

    viewport.scroll_to(24)
    panel.browser.notify_scrolled()
    assert _hydrated_images(panel) > first_pass, (
        "tiles scrolled into view never had their thumbnail requested")


def test_scrolled_tiles_are_actually_drawn_not_just_decoded(make_panel, tmp_path):
    """`_render_tiles` drew only the initial span while sizing scrollregion for all."""
    panel, viewport, _runner = _loaded(make_panel, tmp_path)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    viewport.scroll_to(24)
    panel.browser.notify_scrolled()
    assert panel.browser._order[-1] in panel.browser._tiles, (
        "the last occurrence is inside the viewport but was never painted")


def test_clicking_is_not_required_to_render_a_visible_thumbnail(
        make_panel, tmp_path):
    panel, viewport, _runner = _loaded(make_panel, tmp_path)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    viewport.scroll_to(24)
    panel.browser.notify_scrolled()
    for occurrence_id in panel.browser._tiles:
        assert panel.browser.cache.peek(occurrence_id) is not None
    assert panel.manager.selection == ()


def test_thumbnails_already_decoded_survive_a_view_round_trip(make_panel, tmp_path):
    panel, viewport, _runner = _loaded(make_panel, tmp_path)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    before = _hydrated_images(panel)
    panel.browser.set_view(cover_resizer.VIEW_LIST)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    assert _hydrated_images(panel) >= before


def test_scrolling_does_not_re_request_what_is_already_hydrated(
        make_panel, tmp_path):
    """Hydration stays lazy — a scroll must not restart finished work."""
    panel, viewport, runner = _loaded(make_panel, tmp_path)
    panel.browser.set_view(cover_resizer.VIEW_DETAILS)
    panel.browser.notify_scrolled()
    panel.browser.notify_scrolled()
    ids = list(runner.requested)
    assert len(ids) == len(set(ids)), "an occurrence was decoded more than once"


# --------------------------------------------------------------------------- #
# C. The Windows mouse wheel
# --------------------------------------------------------------------------- #
def test_the_thumbnail_canvas_binds_the_mouse_wheel(make_panel, tmp_path):
    panel, _viewport, _runner = _loaded(make_panel, tmp_path)
    assert "<MouseWheel>" in panel.browser.canvas.bind()


def test_the_treeviews_keep_their_built_in_wheel_behaviour(make_panel, tmp_path):
    """Details and List already scrolled via Tk's Treeview class binding."""
    panel, _viewport, _runner = _loaded(make_panel, tmp_path)
    for widget in (panel.browser.details, panel.browser.simple):
        assert "<MouseWheel>" in widget.bind_class(widget.winfo_class())


def test_a_wheel_event_over_the_canvas_scrolls_it(
        make_panel, tmp_path, hidden_root_again):
    panel, _viewport, _runner = _loaded(make_panel, tmp_path)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    canvas = _sized_canvas(panel, hidden_root_again)
    before = canvas.yview()
    canvas.event_generate("<MouseWheel>", delta=-120, x=5, y=5)
    canvas.update_idletasks()
    assert canvas.yview() != before


def test_wheel_scrolling_up_and_down_are_opposite(
        make_panel, tmp_path, hidden_root_again):
    panel, _viewport, _runner = _loaded(make_panel, tmp_path)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    canvas = _sized_canvas(panel, hidden_root_again)
    canvas.event_generate("<MouseWheel>", delta=-120, x=5, y=5)
    canvas.update_idletasks()
    scrolled = canvas.yview()[0]
    assert scrolled > 0.0
    canvas.event_generate("<MouseWheel>", delta=120, x=5, y=5)
    canvas.update_idletasks()
    assert canvas.yview()[0] < scrolled


def test_the_wheel_binding_is_local_and_never_global(make_panel, tmp_path, tk_root):
    """A bind_all would steal the wheel from every other panel in the launcher."""
    panel, _viewport, _runner = _loaded(make_panel, tmp_path)
    assert not [b for b in tk_root.bind_all() if "MouseWheel" in b]
    # Executable code only — the module legitimately *explains* in a comment why
    # bind_all is refused, and a raw substring search would flag that prose.
    import ast

    tree = ast.parse(Path(cover_resizer.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    assert "bind_all" not in ast.unparse(tree)


def test_a_wheel_event_over_the_canvas_hydrates_newly_visible_tiles(
        make_panel, tmp_path, hidden_root_again):
    """The wheel must reach the same hydration path the scrollbar does."""
    panel, viewport, _runner = _loaded(make_panel, tmp_path)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    before = _hydrated_images(panel)
    viewport.scroll_to(24)
    canvas = _sized_canvas(panel, hidden_root_again)
    canvas.event_generate("<MouseWheel>", delta=-120, x=5, y=5)
    canvas.update_idletasks()
    assert _hydrated_images(panel) > before


# --------------------------------------------------------------------------- #
# D. Nothing Phase 3 proved may regress
# --------------------------------------------------------------------------- #
def test_selection_and_order_survive_the_new_scroll_path(make_panel, tmp_path):
    panel, viewport, _runner = _loaded(make_panel, tmp_path)
    order = panel.browser._order
    panel.browser.click(order[3], None)
    panel.browser.click(order[9], "extend")
    chosen = panel.manager.selection

    for view in (cover_resizer.VIEW_LIST, cover_resizer.VIEW_THUMBNAILS,
                 cover_resizer.VIEW_DETAILS):
        panel.browser.set_view(view)
        viewport.scroll_to(20)
        panel.browser.notify_scrolled()

    assert panel.manager.selection == chosen
    assert panel.browser._order == order


def test_notify_scrolled_is_inert_after_close(make_panel, tmp_path):
    panel, _viewport, _runner = _loaded(make_panel, tmp_path)
    panel.browser.close()
    panel.browser.notify_scrolled()  # must not raise


def test_notify_scrolled_is_inert_with_an_empty_list(make_panel, tmp_path):
    panel = make_panel(preview_runner=RecordingRunner())
    panel.browser.notify_scrolled()  # must not raise
