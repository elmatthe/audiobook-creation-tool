"""The navigator's optional Book-action subset — v0.6.4 Phase 1.

The M4B Metadata Editor is a one-file-per-Book editor: ``Duplicate Book`` is
meaningless there and a manual ``Add Book`` would make an empty page, so the
v0.6.4 plan (section 6.3, Phase 1) lets a consumer choose **which of the three
Book actions** the shared ``BookNavigator`` shows. The seam is narrow by
contract: it is opt-in through one keyword, it may only *drop* Book actions
(never navigation, never the direct selector), and a consumer that does not
name it — the MP3 Tool, and the Maker to come — gets exactly the navigator it
always had.

Everything the navigator already promised still holds under a subset: pure
state before any Tk is reached, availability read from the snapshot, presses
routed through callbacks, the run lock, idempotent close. A dropped action is
not merely disabled — it has no button, is never offered and can never be
invoked, so the Editor cannot press ``Duplicate`` by accident through the
keyboard or a test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

import tk_gate  # noqa: E402

from shared import book_workspace, ui_theme  # noqa: E402
from shared.book_workspace import (  # noqa: E402
    BookJob, IdFactory, SharedMetadata, WorkspaceSnapshot,
)
from shared.book_workspace_ui import BookNavigator, BookWorkspaceUiError  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER = REPO_ROOT / "scripts" / "Universal" / "shared" / "book_workspace_ui.py"

FIELDS = ("Title",)
_IDS = IdFactory("na-")

ALL_BOOK_ACTIONS = (BookNavigator.ADD, BookNavigator.DUPLICATE, BookNavigator.REMOVE)
NAVIGATION = (BookNavigator.PREVIOUS, BookNavigator.NEXT, BookNavigator.SELECT)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def parent(tk_root):
    frame = ttk.Frame(tk_root)
    yield frame
    try:
        frame.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def windows_theme(tk_root):
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style, platform="win32")
    yield theme
    restore = ttk.Style(tk_root)
    if "vista" in restore.theme_names():
        restore.theme_use("vista")


def book() -> BookJob:
    return BookJob(book_id=book_workspace.new_book_id(_IDS), configuration={})


def workspace(count: int = 2) -> WorkspaceSnapshot:
    entries = tuple(book() for _ in range(count))
    return WorkspaceSnapshot(books=entries, current_book_id=entries[0].book_id,
                             shared=SharedMetadata.for_fields(FIELDS))


class Calls:
    def __init__(self) -> None:
        self.seen: list[tuple[str, tuple]] = []

    def make(self, name: str):
        def record(*args):
            self.seen.append((name, args))
        return record

    def names(self) -> list[str]:
        return [name for name, _ in self.seen]


def make(parent, calls: Calls, **kwargs) -> BookNavigator:
    return BookNavigator(
        parent,
        on_previous=calls.make("previous"), on_next=calls.make("next"),
        on_add=calls.make("add"), on_duplicate=calls.make("duplicate"),
        on_remove=calls.make("remove"), on_select=calls.make("select"),
        **kwargs)


# --------------------------------------------------------------------------- #
# The default is the navigator the MP3 Tool already has
# --------------------------------------------------------------------------- #


def test_the_default_offers_every_book_action_in_order(parent):
    made = make(parent, Calls())
    assert made.actions == ALL_BOOK_ACTIONS
    assert tuple(made.buttons) == NAVIGATION[:2] + ALL_BOOK_ACTIONS
    made.close()


def test_the_default_availability_and_presses_are_unchanged(parent):
    """The MP3 Tool passes no subset and must see exactly what it saw before."""
    calls = Calls()
    made = make(parent, calls)
    offered = made.render(workspace(2))
    assert offered == {
        BookNavigator.PREVIOUS: False, BookNavigator.NEXT: True,
        BookNavigator.ADD: True, BookNavigator.DUPLICATE: True,
        BookNavigator.REMOVE: True, BookNavigator.SELECT: True,
    }
    for action in ALL_BOOK_ACTIONS:
        assert made.invoke(action) is True
    assert calls.names() == ["add", "duplicate", "remove"]
    made.close()


def test_the_class_publishes_the_subset_vocabulary():
    assert BookNavigator.BOOK_ACTIONS == ALL_BOOK_ACTIONS
    assert set(BookNavigator.BOOK_ACTIONS).isdisjoint(NAVIGATION)


# --------------------------------------------------------------------------- #
# A subset drops Book actions — and only Book actions
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("layout", BookNavigator.LAYOUTS)
def test_an_editor_style_subset_has_no_add_or_duplicate_button(parent, layout):
    made = make(parent, Calls(), actions=(BookNavigator.REMOVE,), layout=layout)
    assert made.actions == (BookNavigator.REMOVE,)
    assert BookNavigator.ADD not in made.buttons
    assert BookNavigator.DUPLICATE not in made.buttons
    assert BookNavigator.REMOVE in made.buttons
    for always in (BookNavigator.PREVIOUS, BookNavigator.NEXT):
        assert always in made.buttons
    # Nothing but the widgets this navigator owns is gridded in its frame,
    # and none of them is a button for a dropped action.
    gridded = {str(child) for child in made.frame.grid_slaves()}
    assert str(made.buttons[BookNavigator.REMOVE]) in gridded
    assert str(made.selector) in gridded and str(made.label) in gridded
    assert len(gridded) == 5
    made.close()


def test_a_dropped_action_is_never_offered(parent):
    made = make(parent, Calls(), actions=(BookNavigator.REMOVE,))
    offered = made.render(workspace(2))
    assert offered[BookNavigator.ADD] is False
    assert offered[BookNavigator.DUPLICATE] is False
    assert offered[BookNavigator.REMOVE] is True
    assert offered[BookNavigator.NEXT] is True
    assert offered[BookNavigator.SELECT] is True
    assert set(offered) == set(NAVIGATION) | set(ALL_BOOK_ACTIONS), (
        "the availability mapping keeps every key so a consumer can read it uniformly")
    made.close()


def test_a_dropped_action_cannot_be_invoked_even_with_a_callback(parent):
    """The Editor may pass the callbacks it has; a dropped action still never fires."""
    calls = Calls()
    made = make(parent, calls, actions=(BookNavigator.REMOVE,))
    made.render(workspace(2))
    assert made.invoke(BookNavigator.ADD) is False
    assert made.invoke(BookNavigator.DUPLICATE) is False
    assert made.invoke(BookNavigator.REMOVE) is True
    assert calls.names() == ["remove"]


def test_navigation_and_the_selector_are_untouched_by_a_subset(parent):
    calls = Calls()
    made = make(parent, calls, actions=())
    space = workspace(3)
    made.render(space)
    assert made.actions == ()
    assert made.position_text == "Book 1 of 3"
    assert made.selector_ids == tuple(entry.book_id for entry in space.books)
    assert made.invoke(BookNavigator.NEXT) is True
    assert made.choose(space.books[2].book_id) is True
    assert calls.names() == ["next", "select"]
    made.close()


def test_the_subset_is_rendered_in_canonical_order_whatever_order_is_given(parent):
    made = make(parent, Calls(), actions=(BookNavigator.REMOVE, BookNavigator.ADD))
    assert made.actions == (BookNavigator.ADD, BookNavigator.REMOVE)
    assert tuple(made.buttons) == (BookNavigator.PREVIOUS, BookNavigator.NEXT,
                                   BookNavigator.ADD, BookNavigator.REMOVE)
    made.close()


@pytest.mark.parametrize("bad", [
    ("previous",), ("select",), ("bogus",), ("remove", "remove"), ("add", 3),
])
def test_a_subset_may_name_only_book_actions_once_each(parent, bad):
    with pytest.raises(BookWorkspaceUiError):
        BookNavigator(parent, actions=bad)


def test_a_subset_that_is_not_a_sequence_is_refused(parent):
    with pytest.raises(BookWorkspaceUiError):
        BookNavigator(parent, actions="remove")


# --------------------------------------------------------------------------- #
# The rest of the contract holds under a subset
# --------------------------------------------------------------------------- #


def test_lock_render_and_close_tolerate_the_missing_buttons(parent):
    made = make(parent, Calls(), actions=(BookNavigator.REMOVE,))
    made.render(workspace(2))
    made.set_locked(True)
    assert made.locked
    assert "disabled" in made.buttons[BookNavigator.REMOVE].state()
    made.set_locked(False)
    assert "disabled" not in made.buttons[BookNavigator.REMOVE].state()
    made.close()
    made.close()
    assert made.closed


def test_a_themed_subset_navigator_builds_on_the_windows_bundle(parent, windows_theme):
    made = make(parent, Calls(), theme=windows_theme, actions=(BookNavigator.REMOVE,),
                layout="stacked")
    made.render(workspace(1))
    assert made.render(workspace(1))[BookNavigator.DUPLICATE] is False
    made.close()


def test_the_seam_adds_no_second_index_count_or_row_table():
    """The new slot is the subset and nothing else; the old guards still apply."""
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    navigator = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.ClassDef) and node.name == "BookNavigator")
    slots = next(node for node in ast.walk(navigator)
                 if isinstance(node, ast.Assign)
                 and any(getattr(t, "id", "") == "__slots__" for t in node.targets))
    spelled = ast.unparse(slots)
    assert "_actions" in spelled
    for invented in ("_index", "_count", "_total", "_page", "_pages", "_ids",
                     "_labels", "_rows", "_hidden", "_visible"):
        assert invented not in spelled, invented
