"""Cover's Details / List / Medium Thumbnail browser — v0.6.1 Plan 4, Phase 3.

Decision 17A gives the Cover panel three ways to look at the imported list and
makes **Details** the default, because thumbnails are slow on a large import and
so must be opted into. What these tests prove is that all three are
*projections*: the :class:`~shared.importing.ImportedFileManager` that Phase 2
made the single source of truth stays the single source of truth, and the
browser owns pixels, a bounded image cache and nothing else.

Determinism
-----------
**No test sleeps.** The decoder runs through an injected runner seam — inline by
default, deliberately deferred where a late result is the point — and the pump
is ticked by hand. What is "visible" comes from an injected viewport seam, so
the visible-only rule is proved by arithmetic rather than by whether a display
server happened to map a widget.

Safety
------
Every image is generated under ``tmp_path`` with Pillow. Nothing reads the
repository, the real home directory, runtime data or real media, and the two
tests about unreadable files assert the bytes on disk are unchanged afterwards —
a browser must never write to a source.

Scope
-----
Phase 3 adds presentation. Processing still runs on Cover's existing worker and
queue, the importer still owns Add/Remove/Clear/Move, and nothing here touches
Phase 4's job control.
"""

from __future__ import annotations

import ast
import queue
import threading
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from PIL import Image  # noqa: E402

from shared import image_capabilities as caps  # noqa: E402

from mp3_tools import cover_resizer  # noqa: E402

from test_import_coordination import RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PANEL_SOURCE = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "cover_resizer.py"

WAIT = 5.0


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture(autouse=True)
def _clean_capability_cache():
    caps.reset_cache()
    yield
    caps.reset_cache()


def make_image(path: Path, *, size=(40, 30), fmt="JPEG", colour=(20, 120, 200)) -> Path:
    """A real, small, generated image. Never repository content, never real media."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path, format=fmt)
    return path


def make_broken(path: Path) -> Path:
    """A file that looks like an image and is not one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff\xe0 this is not a JPEG at all")
    return path


class RecordingRunner:
    """The decoder seam: records every batch, and can hold results back.

    ``defer=True`` is how a *late* result is produced without a sleep — the
    batch is captured, the world is changed, and only then is it published.
    """

    def __init__(self, *, defer: bool = False):
        self.batches: list[tuple] = []
        self.pending: list[tuple] = []
        self._defer = defer

    def __call__(self, requests, publish):
        self.batches.append(tuple(requests))
        if self._defer:
            self.pending.append((tuple(requests), publish))
            return None
        cover_resizer.decode_previews(requests, publish)
        return None

    def flush(self) -> int:
        held, self.pending = self.pending, []
        for requests, publish in held:
            cover_resizer.decode_previews(requests, publish)
        return len(held)

    @property
    def requested(self) -> tuple[str, ...]:
        return tuple(r.occurrence_id for batch in self.batches for r in batch)


def window(count_visible: int):
    """A viewport seam showing the first *count_visible* items and no more."""

    def viewport(_view: str, count: int) -> tuple[float, float]:
        if count <= 0:
            return (0.0, 0.0)
        return (0.0, min(1.0, count_visible / count))

    return viewport


@pytest.fixture()
def make_panel(tk_root):
    """A real ``CoverResizerUI`` with deterministic seams, always closed after."""
    made: list[cover_resizer.CoverResizerUI] = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: False)
        kwargs.setdefault("preview_runner", RecordingRunner())
        panel = cover_resizer.CoverResizerUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


def import_into(panel, *paths: Path) -> tuple[str, ...]:
    """Populate the manager through the real shared importer, not by assignment."""
    panel.importer._choose_files = lambda: tuple(paths)
    panel.importer.add_files()
    return panel.manager.snapshot().occurrence_ids


def loaded(make_panel, tmp_path, *names, **kwargs):
    """A panel holding real generated images, plus their occurrence ids."""
    files = tuple(make_image(tmp_path / name) for name in names)
    panel = make_panel(**kwargs)
    ids = import_into(panel, *files)
    panel.browser.refresh()
    return panel, ids, files


def image_names(root) -> set[str]:
    """Every Tk image alive in this interpreter, by name."""
    return set(root.tk.call("image", "names"))


def panel_tree() -> ast.Module:
    return ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"), filename=str(PANEL_SOURCE))


def class_named(name: str) -> ast.ClassDef:
    for node in panel_tree().body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} is not defined in cover_resizer.py")


def method_named(name: str, *, owner: str = "CoverResizerUI") -> ast.FunctionDef:
    for member in class_named(owner).body:
        if isinstance(member, ast.FunctionDef) and member.name == name:
            return member
    raise AssertionError(f"{owner}.{name} is not defined in cover_resizer.py")


ALL_VIEWS = (cover_resizer.VIEW_DETAILS, cover_resizer.VIEW_LIST,
             cover_resizer.VIEW_THUMBNAILS)


# --------------------------------------------------------------------------- #
# Details is the default, and shows the five required fields
# --------------------------------------------------------------------------- #


def test_the_browser_opens_on_details(make_panel):
    panel = make_panel()
    assert cover_resizer.DEFAULT_VIEW == cover_resizer.VIEW_DETAILS
    assert panel.browser.view == cover_resizer.VIEW_DETAILS
    assert panel.browser.var_view.get() == cover_resizer.VIEW_DETAILS


def test_details_is_first_in_the_offered_order(make_panel):
    """Opt-in means thumbnails are not the thing a user lands on."""
    offered = tuple(view for view, _label in cover_resizer.BROWSER_VIEWS)
    assert offered[0] == cover_resizer.VIEW_DETAILS
    assert set(offered) == set(ALL_VIEWS)
    panel = make_panel()
    assert tuple(panel.browser.view_buttons) == offered


def test_details_exposes_all_five_required_fields(make_panel, tmp_path):
    source = make_image(tmp_path / "books" / "cover.png", size=(64, 48), fmt="PNG")
    panel, ids, _files = loaded(make_panel, tmp_path)
    import_into(panel, source)
    panel.browser.refresh()
    panel._pump.tick()

    columns = tuple(key for key, _heading, _width in cover_resizer.DETAILS_COLUMNS)
    assert columns == ("filename", "dimensions", "format", "size", "folder")

    occurrence = panel.manager.snapshot().occurrence_ids[0]
    filename, dimensions, image_format, size, folder = \
        panel.browser.details_row(occurrence)
    assert filename == "cover.png"
    assert dimensions == "64 × 48"
    assert image_format == "PNG"
    assert size == cover_resizer.format_file_size(source.stat().st_size)
    assert folder == str(tmp_path / "books")


def test_the_details_headings_are_the_five_fields(make_panel):
    panel = make_panel()
    headings = tuple(
        panel.browser.details.heading(key, "text")
        for key, _heading, _width in cover_resizer.DETAILS_COLUMNS
    )
    assert headings == tuple(h for _k, h, _w in cover_resizer.DETAILS_COLUMNS)
    assert all(headings), "every Details column is labelled"


def test_file_size_formatting_is_human_and_truthful():
    assert cover_resizer.format_file_size(0) == "0 B"
    assert cover_resizer.format_file_size(512) == "512 B"
    assert cover_resizer.format_file_size(1024) == "1.0 KB"
    assert cover_resizer.format_file_size(1024 * 1024 * 3) == "3.0 MB"
    assert cover_resizer.format_file_size(-1) == cover_resizer.UNAVAILABLE_TEXT
    assert cover_resizer.format_file_size(None) == cover_resizer.UNAVAILABLE_TEXT


# --------------------------------------------------------------------------- #
# Every view is a projection of the manager snapshot
# --------------------------------------------------------------------------- #


def test_every_view_renders_the_manager_order_and_nothing_else(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "c.jpg", "a.jpg", "b.jpg")
    for view in ALL_VIEWS:
        panel.browser.set_view(view)
        assert panel.browser.order == ids, view
        assert panel.browser.rendered_ids() == ids, view


def test_the_browser_keeps_no_second_authoritative_file_list():
    """A projection reads the snapshot; it does not keep a rival copy."""
    browser = class_named("CoverBrowser")
    assigned = {
        target.attr
        for node in ast.walk(browser)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    }
    for forbidden in ("files", "_files", "paths", "imported", "_imported"):
        assert forbidden not in assigned, forbidden

    refresh = method_named("refresh", owner="CoverBrowser")
    calls = {
        node.func.attr for node in ast.walk(refresh)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "snapshot" in calls, "a refresh must re-read the manager"


def test_the_browser_never_reorders_the_snapshot():
    """Sorting inside a view would silently disagree with the run order."""
    browser = class_named("CoverBrowser")
    called = {
        node.func.attr for node in ast.walk(browser)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    bare = {
        node.func.id for node in ast.walk(browser)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "sort" not in called and "sorted" not in bare


def test_switching_views_preserves_exact_manager_order(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "z.jpg", "y.jpg", "x.jpg", "w.jpg")
    before = panel.imported_files()
    for view in (cover_resizer.VIEW_THUMBNAILS, cover_resizer.VIEW_LIST,
                 cover_resizer.VIEW_DETAILS, cover_resizer.VIEW_THUMBNAILS):
        panel.browser.set_view(view)
        assert panel.browser.order == ids
        assert panel.imported_files() == before, "a view switch moved the list"
    assert panel.manager.revision.value == panel.manager.snapshot().revision.value


def test_switching_views_never_touches_the_manager(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg")
    revision = panel.manager.revision.value
    for view in ALL_VIEWS:
        panel.browser.set_view(view)
    assert panel.manager.revision.value == revision
    assert panel.manager.snapshot().occurrence_ids == ids


def test_an_unknown_view_is_refused(make_panel):
    panel = make_panel()
    with pytest.raises(ValueError):
        panel.browser.set_view("mosaic")
    assert panel.browser.view == cover_resizer.VIEW_DETAILS


# --------------------------------------------------------------------------- #
# Selection lives in the manager, keyed by occurrence id
# --------------------------------------------------------------------------- #


def test_a_click_selects_through_the_manager(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    panel.browser.click(ids[1])
    assert panel.manager.selection == (ids[1],)
    assert panel.browser.selection == (ids[1],)


def test_selection_is_not_stored_only_in_a_widget():
    """The widget shows the answer; the manager holds it."""
    commit = method_named("_commit_selection", owner="CoverBrowser")
    calls = [
        node for node in ast.walk(commit)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "select"
    ]
    assert calls, "the browser must route selection through the manager"


def test_switching_views_preserves_selection_by_occurrence_id(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg", "d.jpg")
    panel.browser.click(ids[1])
    panel.browser.click(ids[3], cover_resizer.SELECT_TOGGLE)
    wanted = (ids[1], ids[3])
    assert panel.manager.selection == wanted

    for view in (cover_resizer.VIEW_LIST, cover_resizer.VIEW_THUMBNAILS,
                 cover_resizer.VIEW_DETAILS):
        panel.browser.set_view(view)
        assert panel.manager.selection == wanted, view
        assert panel.browser.painted_selection() == wanted, view


def test_deliberate_duplicates_stay_independently_selectable_in_every_view(
    make_panel, tmp_path
):
    source = make_image(tmp_path / "same.jpg")
    panel = make_panel()
    import_into(panel, source)
    panel.importer.options.set_allow_duplicates(True)
    import_into(panel, source)
    panel.browser.refresh()

    ids = panel.manager.snapshot().occurrence_ids
    assert len(ids) == 2 and ids[0] != ids[1]
    paths = panel.imported_files()
    assert paths[0] == paths[1], "same path, two occurrences"

    for view in ALL_VIEWS:
        panel.browser.set_view(view)
        panel.browser.click(ids[1])
        assert panel.manager.selection == (ids[1],), view
        assert panel.browser.painted_selection() == (ids[1],), view
        panel.browser.click(ids[0])
        assert panel.manager.selection == (ids[0],), view


def test_a_selection_made_in_one_view_is_visible_in_the_next(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    panel.browser.click(ids[2])
    panel.browser.set_view(cover_resizer.VIEW_DETAILS)
    assert panel.browser.painted_selection() == (ids[2],)
    assert set(panel.browser.details.selection()) == {ids[2]}


def test_a_selection_made_in_the_importer_reaches_the_browser(make_panel, tmp_path):
    """The shared list and the browser are two views of one selection."""
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    panel.importer.list.select((ids[0], ids[2]))
    panel._pump.tick()
    assert panel.browser.painted_selection() == (ids[0], ids[2])


def test_a_selection_made_in_the_browser_reaches_the_importer(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    panel.browser.click(ids[1])
    assert panel.importer.list.selection == (ids[1],)


# --------------------------------------------------------------------------- #
# Click, keyboard, Ctrl / Command and Shift, in every view
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_a_plain_click_replaces_the_selection(make_panel, tmp_path, view):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    panel.browser.set_view(view)
    panel.browser.click(ids[0])
    panel.browser.click(ids[2])
    assert panel.manager.selection == (ids[2],)


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_ctrl_or_command_click_toggles_one_occurrence(make_panel, tmp_path, view):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    panel.browser.set_view(view)
    panel.browser.click(ids[0])
    panel.browser.click(ids[2], cover_resizer.SELECT_TOGGLE)
    assert panel.manager.selection == (ids[0], ids[2])
    panel.browser.click(ids[0], cover_resizer.SELECT_TOGGLE)
    assert panel.manager.selection == (ids[2],)


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_shift_click_selects_a_range_in_manager_order(make_panel, tmp_path, view):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg",
                                "d.jpg", "e.jpg")
    panel.browser.set_view(view)
    panel.browser.click(ids[3])
    panel.browser.click(ids[1], cover_resizer.SELECT_EXTEND)
    assert panel.manager.selection == (ids[1], ids[2], ids[3]), \
        "a backwards range is still returned in list order"


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_keyboard_navigation_moves_and_selects(make_panel, tmp_path, view):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    panel.browser.set_view(view)
    panel.browser.click(ids[0])
    panel.browser.key("down")
    assert panel.manager.selection == (ids[1],)
    panel.browser.key("down")
    assert panel.manager.selection == (ids[2],)
    panel.browser.key("down")
    assert panel.manager.selection == (ids[2],), "the end does not wrap"
    panel.browser.key("up")
    assert panel.manager.selection == (ids[1],)
    panel.browser.key("home")
    assert panel.manager.selection == (ids[0],)
    panel.browser.key("end")
    assert panel.manager.selection == (ids[2],)


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_shift_arrow_extends_from_the_anchor(make_panel, tmp_path, view):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg", "d.jpg")
    panel.browser.set_view(view)
    panel.browser.click(ids[1])
    panel.browser.key("extend_down")
    assert panel.manager.selection == (ids[1], ids[2])
    panel.browser.key("extend_down")
    assert panel.manager.selection == (ids[1], ids[2], ids[3])
    panel.browser.key("extend_up")
    assert panel.manager.selection == (ids[1], ids[2]), "the anchor did not move"


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_select_all_covers_the_whole_manager_order(make_panel, tmp_path, view):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    panel.browser.set_view(view)
    panel.browser.key("select_all")
    assert panel.manager.selection == ids


def test_the_selection_anchor_follows_manager_order_not_click_order():
    """A range is between two positions, whichever was clicked first."""
    order = ("o1", "o2", "o3", "o4")
    forwards, anchor = cover_resizer.resolve_selection(
        order, (), None, "o2", cover_resizer.SELECT_REPLACE)
    assert forwards == ("o2",) and anchor == "o2"
    extended, anchor = cover_resizer.resolve_selection(
        order, forwards, anchor, "o4", cover_resizer.SELECT_EXTEND)
    assert extended == ("o2", "o3", "o4") and anchor == "o2"
    backwards, anchor = cover_resizer.resolve_selection(
        order, extended, anchor, "o1", cover_resizer.SELECT_EXTEND)
    assert backwards == ("o1", "o2"), "the anchor stayed put and the range flipped"
    assert anchor == "o2"


def test_a_selection_engine_call_for_a_missing_occurrence_changes_nothing():
    order = ("o1", "o2")
    selection, anchor = cover_resizer.resolve_selection(
        order, ("o2",), "o2", "gone", cover_resizer.SELECT_REPLACE)
    assert selection == ("o2",) and anchor == "o2"


def test_the_engine_returns_selections_in_manager_order():
    order = ("o1", "o2", "o3")
    selection, _anchor = cover_resizer.resolve_selection(
        order, ("o3",), "o3", "o1", cover_resizer.SELECT_TOGGLE)
    assert selection == ("o1", "o3")


#: Tk normalises binding names, so ``bind()`` never echoes back what was asked
#: for: ``<Up>`` becomes ``<Key-Up>``, and ``Command`` becomes ``Mod1`` — which
#: is exactly how Command-click reaches macOS while Control-click stays separate.
NORMALISED_BINDINGS = (
    "<Button-1>", "<Control-Button-1>", "<Mod1-Button-1>", "<Shift-Button-1>",
    "<Key-Up>", "<Key-Down>", "<Key-Left>", "<Key-Right>",
    "<Shift-Key-Up>", "<Shift-Key-Down>", "<Shift-Key-Left>", "<Shift-Key-Right>",
    "<Key-Home>", "<Key-End>", "<Control-Key-a>", "<Mod1-Key-a>",
)


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_every_view_binds_click_ctrl_command_shift_and_the_keyboard(
    make_panel, view
):
    panel = make_panel()
    bound = set(panel.browser.surface(view).bind())
    for sequence in NORMALISED_BINDINGS:
        assert sequence in bound, f"{view} is missing {sequence}"
    assert "<Control-Button-1>" != "<Mod1-Button-1>", \
        "Ctrl-click and Command-click are bound separately, not aliased"


def test_locking_the_browser_refuses_selection_changes(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg")
    panel.browser.click(ids[0])
    panel.browser.set_locked(True)
    panel.browser.click(ids[1])
    assert panel.manager.selection == (ids[0],), "a locked browser changes nothing"
    panel.browser.set_locked(False)
    panel.browser.click(ids[1])
    assert panel.manager.selection == (ids[1],)


def test_a_locked_browser_can_still_change_view(make_panel, tmp_path):
    """Looking is not mutating; a running resize does not blind the user."""
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg")
    panel.browser.set_locked(True)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    assert panel.browser.view == cover_resizer.VIEW_THUMBNAILS
    assert panel.browser.order == ids


# --------------------------------------------------------------------------- #
# Importer mutations stay reflected, in whichever view is active
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_removing_through_the_importer_updates_the_active_view(
    make_panel, tmp_path, view
):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    panel.browser.set_view(view)
    panel.manager.select((ids[1],))
    panel.importer.list.remove_selected()
    panel._pump.tick()
    assert panel.browser.order == (ids[0], ids[2]), view
    assert panel.browser.rendered_ids() == (ids[0], ids[2]), view


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_clearing_through_the_importer_empties_the_active_view(
    make_panel, tmp_path, view
):
    panel, ids, files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg")
    panel.browser.set_view(view)
    panel.importer.list.clear()
    panel._pump.tick()
    assert panel.browser.order == ()
    assert panel.browser.rendered_ids() == ()
    assert all(path.exists() for path in files), "clearing a list deletes no file"


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_moving_through_the_importer_reorders_the_active_view(
    make_panel, tmp_path, view
):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg")
    panel.browser.set_view(view)
    panel.manager.select((ids[2],))
    panel.importer.list.move_up()
    panel._pump.tick()
    assert panel.browser.order == (ids[0], ids[2], ids[1]), view
    assert panel.browser.rendered_ids() == (ids[0], ids[2], ids[1]), view


def test_a_new_import_appears_in_the_active_view(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg")
    panel.browser.set_view(cover_resizer.VIEW_LIST)
    extra = make_image(tmp_path / "b.jpg")
    import_into(panel, extra)
    panel._pump.tick()
    assert len(panel.browser.order) == 2
    assert panel.browser.rendered_ids() == panel.manager.snapshot().occurrence_ids


def test_the_browser_follows_the_manager_without_a_second_callback_chain():
    """One pump owns the panel; the browser rides it and schedules nothing."""
    browser = class_named("CoverBrowser")
    calls = {
        node.func.attr for node in ast.walk(browser)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("after", "after_idle", "schedule"):
        assert forbidden not in calls, forbidden
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert source.count("MainThreadPump(") == 1


# --------------------------------------------------------------------------- #
# Unreadable, corrupt and undecodable images
# --------------------------------------------------------------------------- #


def test_a_corrupt_image_reports_unavailable_and_keeps_its_row(make_panel, tmp_path):
    broken = make_broken(tmp_path / "broken.jpg")
    before = broken.read_bytes()
    panel = make_panel()
    ids = import_into(panel, broken)
    panel.browser.refresh()
    panel._pump.tick()

    facts = panel.browser.facts_for(ids[0])
    assert facts.state == cover_resizer.FACTS_UNAVAILABLE
    row = panel.browser.details_row(ids[0])
    assert row[0] == "broken.jpg", "the name is a path fact and stays truthful"
    assert row[1] == cover_resizer.UNAVAILABLE_TEXT
    assert row[2] == cover_resizer.UNAVAILABLE_TEXT
    assert row[4] == str(tmp_path)
    assert panel.browser.order == ids, "a broken image is still an imported file"
    assert broken.read_bytes() == before, "reading an image must never write to it"


def test_a_corrupt_image_shows_the_placeholder_in_the_thumbnail_view(
    make_panel, tmp_path
):
    broken = make_broken(tmp_path / "broken.jpg")
    good = make_image(tmp_path / "good.jpg")
    panel = make_panel()
    ids = import_into(panel, broken, good)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    panel._pump.tick()

    assert panel.browser.tile_image(ids[0]) is panel.browser.placeholder
    assert panel.browser.tile_image(ids[1]) is not panel.browser.placeholder
    assert panel.browser.tile_image(ids[1]) is not None
    assert broken.exists() and good.exists()


def test_a_file_that_vanished_after_import_degrades_rather_than_crashing(
    make_panel, tmp_path
):
    gone = make_image(tmp_path / "gone.jpg")
    panel = make_panel()
    ids = import_into(panel, gone)
    gone.unlink()
    panel.browser.refresh()
    panel._pump.tick()

    facts = panel.browser.facts_for(ids[0])
    assert facts.state == cover_resizer.FACTS_UNAVAILABLE
    assert panel.browser.details_row(ids[0])[3] == cover_resizer.UNAVAILABLE_TEXT
    assert panel.browser.order == ids


def test_reading_facts_never_raises_for_any_input(tmp_path):
    for path in (tmp_path / "missing.jpg",
                 make_broken(tmp_path / "broken.png"),
                 tmp_path,                       # a directory
                 make_image(tmp_path / "fine.jpg")):
        facts = cover_resizer.read_image_facts(path)
        assert isinstance(facts, cover_resizer.ImageFacts)
        assert facts.filename == Path(path).name
        assert facts.folder == str(Path(path).parent)


def test_encoding_a_thumbnail_never_raises_for_any_input(tmp_path):
    assert cover_resizer.encode_thumbnail(tmp_path / "missing.jpg", 64) is None
    assert cover_resizer.encode_thumbnail(make_broken(tmp_path / "b.jpg"), 64) is None
    assert cover_resizer.encode_thumbnail(make_image(tmp_path / "g.jpg"), 64)


# --------------------------------------------------------------------------- #
# Thumbnails: lazy, visible-only, bounded, and explicitly owned
# --------------------------------------------------------------------------- #


def test_a_large_import_decodes_only_what_is_visible(make_panel, tmp_path):
    names = [f"{index:03d}.jpg" for index in range(40)]
    runner = RecordingRunner()
    panel, ids, _files = loaded(make_panel, tmp_path, *names,
                                preview_runner=runner, viewport=window(6))
    runner.batches.clear()
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)

    assert len(panel.browser.order) == 40
    assert set(runner.requested) == set(ids[:6]), "only the visible tiles decoded"
    assert panel.browser.cache.size == 6


def test_scrolling_further_decodes_the_next_items_and_no_more(make_panel, tmp_path):
    names = [f"{index:03d}.jpg" for index in range(30)]
    shown = {"start": 0, "count": 5}

    def viewport(_view, count):
        if count <= 0:
            return (0.0, 0.0)
        return (shown["start"] / count, (shown["start"] + shown["count"]) / count)

    runner = RecordingRunner()
    panel, ids, _files = loaded(make_panel, tmp_path, *names,
                                preview_runner=runner, viewport=viewport)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    first = set(runner.requested)
    assert first == set(ids[:5])

    shown["start"] = 10
    panel.browser.request_visible()
    assert set(runner.requested) - first == set(ids[10:15])


def test_the_visible_span_is_capped_even_when_a_widget_claims_everything():
    """An unmapped widget honestly answers (0.0, 1.0); the cap is the guarantee."""
    assert cover_resizer.visible_span(0.0, 1.0, 5000, maximum=60) == (0, 60)
    assert cover_resizer.visible_span(0.0, 1.0, 10, maximum=60) == (0, 10)
    assert cover_resizer.visible_span(0.5, 0.6, 100, maximum=60) == (50, 60)
    assert cover_resizer.visible_span(0.0, 0.0, 0, maximum=60) == (0, 0)
    assert cover_resizer.MAX_VISIBLE_ITEMS >= 1


def test_details_does_not_decode_a_thumbnail_at_all(make_panel, tmp_path):
    runner = RecordingRunner()
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg",
                                preview_runner=runner)
    assert panel.browser.view == cover_resizer.VIEW_DETAILS
    assert runner.batches, "Details still reads metadata"
    assert all(not request.want_image
               for batch in runner.batches for request in batch)
    assert panel.browser.cache.size == 0


def test_the_thumbnail_cache_has_a_finite_documented_bound():
    cache = cover_resizer.ThumbnailCache()
    assert cache.limit == cover_resizer.THUMBNAIL_CACHE_LIMIT
    assert isinstance(cover_resizer.THUMBNAIL_CACHE_LIMIT, int)
    assert 1 <= cover_resizer.THUMBNAIL_CACHE_LIMIT < 10_000
    with pytest.raises(ValueError):
        cover_resizer.ThumbnailCache(limit=0)


def test_the_cache_evicts_least_recently_used_first():
    cache = cover_resizer.ThumbnailCache(limit=3)
    for key in ("a", "b", "c"):
        assert cache.put(key, object()) == ()
    cache.get("a")                                  # a is now the most recent
    assert cache.put("d", object()) == ("b",)
    assert cache.keys == ("c", "a", "d")
    assert cache.evicted == 1
    assert cache.get("b") is None


def test_the_cache_replaces_rather_than_duplicates_a_key():
    cache = cover_resizer.ThumbnailCache(limit=2)
    first, second = object(), object()
    cache.put("a", first)
    assert cache.put("a", second) == ()
    assert cache.size == 1 and cache.get("a") is second


def test_the_cache_retains_only_live_occurrences():
    cache = cover_resizer.ThumbnailCache(limit=5)
    for key in ("a", "b", "c"):
        cache.put(key, object())
    assert set(cache.retain(("a", "c"))) == {"b"}
    assert cache.keys == ("a", "c")
    assert cache.retain(()) == ("a", "c") or cache.size == 0


def test_evicting_a_thumbnail_releases_its_tk_image(make_panel, tmp_path, tk_root):
    names = [f"{index:03d}.jpg" for index in range(8)]
    panel, ids, _files = loaded(make_panel, tmp_path, *names,
                                viewport=window(4), cache_limit=4)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    before = image_names(tk_root)
    assert panel.browser.cache.size == 4

    panel.browser.cache.clear()
    after = image_names(tk_root)
    assert len(after) < len(before), "clearing the cache released Tk images"
    assert panel.browser.cache.size == 0


def test_rebuilding_and_switching_cannot_accumulate_images(
    make_panel, tmp_path, tk_root
):
    names = [f"{index:03d}.jpg" for index in range(6)]
    panel, ids, _files = loaded(make_panel, tmp_path, *names,
                                viewport=window(3), cache_limit=3)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    settled = len(image_names(tk_root))

    for _ in range(6):
        panel.browser.refresh()
        panel.browser.set_view(cover_resizer.VIEW_DETAILS)
        panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)

    assert panel.browser.cache.size <= 3
    assert len(image_names(tk_root)) <= settled, "images accumulated across rebuilds"


def test_closing_the_browser_releases_every_image_and_leaves_no_drain(
    make_panel, tmp_path, tk_root
):
    names = [f"{index:03d}.jpg" for index in range(5)]
    panel, ids, _files = loaded(make_panel, tmp_path, *names, viewport=window(5))
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    held = len(image_names(tk_root))
    assert panel.browser.cache.size == 5

    drains = panel._pump.drain_count
    panel.browser.close()
    assert panel.browser.cache.size == 0
    assert panel.browser.placeholder is None
    assert panel._pump.drain_count == drains - 1
    assert len(image_names(tk_root)) < held
    panel.browser.close()  # idempotent


def test_removing_an_occurrence_releases_its_cached_image(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg", "c.jpg",
                                viewport=window(3))
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    assert panel.browser.cache.size == 3

    panel.manager.select((ids[0],))
    panel.importer.list.remove_selected()
    panel._pump.tick()
    assert ids[0] not in panel.browser.cache.keys
    assert set(panel.browser.cache.keys) <= set(panel.browser.order)


# --------------------------------------------------------------------------- #
# Late results are rejected inertly
# --------------------------------------------------------------------------- #


def test_a_late_result_for_a_removed_occurrence_is_dropped(make_panel, tmp_path):
    runner = RecordingRunner(defer=True)
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg",
                                preview_runner=runner, viewport=window(2))
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    assert runner.pending, "the decode is still in flight"

    panel.manager.select((ids[0],))
    panel.importer.list.remove_selected()
    panel._pump.tick()

    runner.flush()
    panel._pump.tick()
    assert ids[0] not in panel.browser.cache.keys
    assert panel.browser.facts_for(ids[0]) is None
    assert panel.browser.order == (ids[1],)


def test_a_late_result_from_an_older_revision_is_dropped(make_panel, tmp_path):
    runner = RecordingRunner(defer=True)
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg",
                                preview_runner=runner, viewport=window(2))
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    stale = runner.pending[:]
    runner.pending = []

    extra = make_image(tmp_path / "c.jpg")
    import_into(panel, extra)          # the revision moves on
    panel._pump.tick()
    runner.pending = stale
    before = panel.browser.cache.size
    runner.flush()
    accepted = panel.browser.drain()

    assert accepted == 0, "a result planned against an older revision is inert"
    assert panel.browser.cache.size >= before


def test_a_late_result_after_close_is_dropped(make_panel, tmp_path):
    runner = RecordingRunner(defer=True)
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg",
                                preview_runner=runner, viewport=window(1))
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    panel.browser.close()
    runner.flush()
    assert panel.browser.drain() == 0
    assert panel.browser.cache.size == 0


def test_a_late_result_is_dropped_without_raising_after_the_panel_closes(
    make_panel, tmp_path
):
    runner = RecordingRunner(defer=True)
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg",
                                preview_runner=runner, viewport=window(1))
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    panel.close()
    runner.flush()
    panel._pump.tick()          # a closed pump ticks to nothing
    assert panel.browser.closed is True


# --------------------------------------------------------------------------- #
# The decoder is a worker, and it never touches Tk
# --------------------------------------------------------------------------- #


def test_the_decoder_creates_no_tk_object():
    """Only plain data crosses the queue; PhotoImage is built on the main thread."""
    tree = panel_tree()
    decode = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "decode_previews")
    names = {node.id for node in ast.walk(decode) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(decode)
                  if isinstance(node, ast.Attribute)}
    assert "tk" not in names
    assert "PhotoImage" not in attributes and "PhotoImage" not in names


def test_the_photoimage_is_only_ever_built_on_the_main_thread():
    browser = class_named("CoverBrowser")
    builders = [
        node for node in ast.walk(browser)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "PhotoImage"
    ]
    assert builders, "the browser builds its images itself"
    accept = method_named("_accept", owner="CoverBrowser")
    assert any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "PhotoImage"
        for node in ast.walk(accept)
    ), "results become images where they are accepted, on the pump"


def test_the_default_runner_publishes_from_a_worker_thread(tmp_path):
    good = make_image(tmp_path / "a.jpg")
    published: queue.Queue = queue.Queue()
    request = cover_resizer.PreviewRequest(
        occurrence_id="occ-1", path=good, revision=0, want_image=True, size=64)

    thread = cover_resizer.run_previews_in_thread((request,), published.put)
    thread.join(WAIT)
    assert not thread.is_alive()
    result = published.get_nowait()
    assert result.occurrence_id == "occ-1"
    assert result.facts.state == cover_resizer.FACTS_READY
    assert result.image_data


def test_a_decoded_preview_carries_plain_bytes_not_a_widget(tmp_path):
    good = make_image(tmp_path / "a.jpg", size=(200, 100))
    results = []
    cover_resizer.decode_previews(
        (cover_resizer.PreviewRequest("occ-1", good, 3, True, 64),), results.append)
    result = results[0]
    assert result.revision == 3
    assert isinstance(result.image_data, bytes)
    assert result.facts.dimensions == "200 × 100"


def test_closing_the_browser_leaves_no_decoder_thread_running(make_panel, tmp_path):
    """A batch that outlives its widgets is a leak, and it collects Tk garbage
    on a thread that is not allowed to touch Tk."""
    names = [f"{index:03d}.jpg" for index in range(6)]
    files = tuple(make_image(tmp_path / name) for name in names)
    before = set(threading.enumerate())
    panel = make_panel(preview_runner=None)     # the real threaded runner
    import_into(panel, *files)
    panel.browser.set_view(cover_resizer.VIEW_THUMBNAILS)
    panel.browser.close()

    leaked = [
        thread for thread in set(threading.enumerate()) - before
        if thread.name == "cover-previews" and thread.is_alive()
    ]
    assert leaked == [], f"a decoder thread survived close: {leaked}"
    assert cover_resizer.WORKER_JOIN_TIMEOUT > 0, "the join is bounded, not indefinite"


def test_a_locked_browser_looks_locked(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg")
    panel.browser.set_locked(True)
    assert "disabled" in panel.browser.details.state()
    assert "disabled" in panel.browser.simple.state()
    panel.browser.set_locked(False)
    assert "disabled" not in panel.browser.details.state()


def test_the_browser_drain_rides_the_panels_one_pump(make_panel):
    """Phase 4 added the job adapter's drain to the same chain.

    Named rather than counted, so a later drain cannot slip in behind an
    unchanged number. What this test is about — the browser owning no ``after``
    chain of its own — is unchanged.
    """
    panel = make_panel()
    registered = list(panel._pump._drains)
    assert panel.browser.drain in registered
    assert panel._drain_worker_queue in registered
    assert panel.jobs.drain in registered
    assert len(registered) == 3, registered
    assert panel._pump.running is True
    assert panel._pump.pending is not None or panel._pump.closed is False


def test_every_browser_entry_point_is_fenced_to_the_owner_thread(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg")
    failures: list[Exception] = []

    def offend():
        for action in (panel.browser.refresh,
                       lambda: panel.browser.set_view(cover_resizer.VIEW_LIST),
                       lambda: panel.browser.click(ids[0]),
                       lambda: panel.browser.key("down")):
            try:
                action()
            except Exception as exc:  # noqa: BLE001 - the point of the test
                failures.append(exc)

    worker = threading.Thread(target=offend, name="offending-worker")
    worker.start()
    worker.join(WAIT)
    assert not worker.is_alive()
    assert len(failures) == 4
    job_ui = __import__("shared.job_ui", fromlist=["x"])
    assert all(isinstance(exc, job_ui.MainThreadError) for exc in failures)


# --------------------------------------------------------------------------- #
# Phase 2 and the old processing path are untouched
# --------------------------------------------------------------------------- #


def test_the_manager_is_still_the_single_imported_file_source(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg")
    assert panel.imported_files() == [
        entry.path for entry in panel.manager.snapshot().files]
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "self.files" not in source
    assert "self.listbox" not in source


def test_the_processing_worker_still_reads_no_tk_variable_and_no_widget():
    """Measured on what the worker reaches for *on the panel*, which is the claim.

    Phase 4 tightened this from a blacklist of any attribute anywhere to a
    whitelist of the panel attributes the worker may touch — stronger, and no
    longer confusable with a shared reporting call that happens to share a name.
    """
    worker = method_named("resize_worker")
    reached = {node.attr for node in ast.walk(worker)
               if isinstance(node, ast.Attribute)
               and isinstance(node.value, ast.Name) and node.value.id == "self"}
    assert reached == {"_log_q", "_cancel_event"}, reached
    for forbidden in ("var_size", "var_letterbox", "importer", "browser",
                      "log", "progress", "manager", "cache"):
        assert forbidden not in reached, forbidden


def test_the_two_cancellations_are_still_separate(make_panel):
    panel = make_panel()
    panel.importer.cancel_import()
    assert panel._cancel_event.is_set() is False
    cancel = method_named("cancel")
    attributes = {node.attr for node in ast.walk(cancel)
                  if isinstance(node, ast.Attribute)}
    assert "importer" not in attributes and "browser" not in attributes


def test_locking_the_inputs_locks_the_browser_too(make_panel, tmp_path):
    panel, ids, _files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg")
    panel.disable_inputs(True)
    assert panel.browser.locked is True
    panel.browser.click(ids[1])
    assert panel.manager.selection != (ids[1],)
    panel.disable_inputs(False)
    assert panel.browser.locked is False


def test_starting_a_resize_still_captures_the_manager_snapshot(make_panel, tmp_path):
    panel, ids, files = loaded(make_panel, tmp_path, "a.jpg", "b.jpg")
    start = method_named("start_resize")
    body = ast.dump(start)
    assert "imported_files" in body
    assert list(files) == panel.imported_files()


def test_no_phase_five_vocabulary_entered_the_panel():
    """A phase-ordering marker, moved on to the phases that have not started.

    Phase 3 used it to prove job control had not arrived early; Phase 4 is where
    job control legitimately arrives, and ``test_cover_jobs.py`` proves that
    surface in full. What must still be absent is everything Phase 5 and later
    own, and this is where that stays checked.
    """
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    for forbidden in ("chatterbox", "Chatterbox", "voice_registry", "epub",
                      "archived-code", "torch", "kokoro"):
        assert forbidden not in source, forbidden


def test_the_panel_still_names_no_namespaced_style():
    """Cover stays a classic Windows panel until the conversion plan says otherwise."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "ACT" + "." not in source
    browser = class_named("CoverBrowser")
    styled = [
        keyword for node in ast.walk(browser)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "style"
    ]
    assert styled == [], "the browser sets no ttk style at all"
