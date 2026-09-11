"""The Plan 6 Tk boundary — v0.6.3 Drop 1, Phase 8.

``shared/book_workspace_ui.py`` is the only Plan 6 module that may touch Tk, so this
is the only Plan 6 test module that builds widgets. What it asserts is about the
**boundary**, not about behaviour proved elsewhere: Phases 1–7 own what the workspace,
the shared metadata, the capture, the dispositions and the retry composition do, and
those suites are unchanged. What is new here is whether a widget can be reached from
the wrong thread, whether a callback survives a close, whether the adapter renders
exactly what the model's projections say, and whether it stays native off Windows.

Determinism
-----------
**No test sleeps and nothing polls.** The adapter opens no ``after`` chain, so there
is nothing to tick: a render is a call. The one threading test uses a foreign thread
id rather than a real race, which is the seam ``MainThreadGuard`` exposes for exactly
this purpose.

Safety
------
No dialog is ever opened — ``ask_confirm`` is the caller's to show and this module
asserts the adapter never reaches for it. Nothing scans a disk, starts a process,
touches real media or writes a setting. The ``ImportedFile`` values below are
test-owned records over paths that are never opened, stat-ed or required to exist.

Appearance is asserted **mechanically**, never by sampling pixels: the question is
which style key the adapter asked the theme for, not what colour came back.
"""

from __future__ import annotations

import ast
import dataclasses
from collections.abc import Mapping
import os
import threading
from pathlib import Path, PurePath

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

import tk_gate  # noqa: E402

from shared import book_workspace, book_workspace_ui, job_ui, ui_theme  # noqa: E402
from shared.book_workspace import (  # noqa: E402
    BookJob,
    SharedMetadata,
    WorkspaceSnapshot,
    add_book,
    disabled_fields,
    duplicate_book,
    has_meaningful_work,
    next_book,
    previous_book,
    remove_book,
    replace_book,
    set_shared_metadata,
)
from shared.book_workspace_ui import (  # noqa: E402
    BookNavigator,
    BookWorkspaceUiError,
    SharedMetadataSurface,
)
from shared.importing import (  # noqa: E402
    IdFactory,
    ImportedFile,
    ImportedFileSnapshot,
    ImportRoot,
    Revision,
)
from shared.job_control import ControlKind, JobState  # noqa: E402
from shared.job_ui import LockGroup, MainThreadError  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #

ROOT = Path(os.path.abspath(os.sep + "act-fixture-root"))
ROOTED = ImportRoot("root-1", ROOT, 0)

#: This module's own consumer vocabulary. The adapter must know none of these names;
#: they are here to prove it renders whatever it is handed. Phase 4 requires a field
#: name to be identifier-shaped, and this suite respects that rather than working
#: around it -- the model is the authority on what a declared field may be called.
FIELDS = ("display_name", "Author", "Narrator")

_IDS = IdFactory("u-")

#: Spelled once, so a synthetic AST sample never needs an escape in its own source.
NEWLINE = chr(10)


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
def windows_theme(tk_root, monkeypatch):
    """The Windows ``ACT.*`` bundle, forced on any host."""
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style)
    yield theme
    restore = ttk.Style(tk_root)
    if "vista" in restore.theme_names():
        restore.theme_use("vista")


#: The three bundle shapes drop section 20 names. Aqua and classic publish no
#: ``styles`` and no ``fonts``, and aqua's ``metrics`` is smaller — so a bundle that
#: is *missing* keys is the point, not an oversight.
AQUA_THEME = {
    "mode": "aqua",
    "geometry": ui_theme.DEFAULT_GEOMETRY,
    "min_size": ui_theme.MIN_SIZE,
    "metrics": {"content_pad": 12},
}
CLASSIC_THEME = {
    "mode": "classic",
    "geometry": ui_theme.DEFAULT_GEOMETRY,
    "min_size": ui_theme.MIN_SIZE,
    "metrics": {},
}
NATIVE_THEMES = {"aqua": AQUA_THEME, "classic": CLASSIC_THEME, "none": None}


def files(label: str = "A", count: int = 2) -> ImportedFileSnapshot:
    """Test-owned records. These paths are never opened, stat-ed or required."""
    return ImportedFileSnapshot(Revision(1), tuple(
        ImportedFile(f"{label}-occ-{index}", ROOT / label / f"{index}.mp3", ROOTED,
                     PurePath(label) / f"{index}.mp3", "mp3", f"{label}-id-{index}")
        for index in range(1, count + 1)))


def book(count: int = 0, **configuration) -> BookJob:
    return BookJob(book_id=book_workspace.new_book_id(_IDS),
                   configuration=configuration,
                   files=files(count=count) if count else ImportedFileSnapshot())


def workspace(*books: BookJob, shared: SharedMetadata | None = None
              ) -> WorkspaceSnapshot:
    entries = books or (book(),)
    return WorkspaceSnapshot(
        books=entries, current_book_id=entries[0].book_id,
        shared=SharedMetadata.for_fields(FIELDS) if shared is None else shared)


class Calls:
    """A deterministic callback recorder. No dialog, no timer, no thread."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, tuple]] = []

    def make(self, name: str):
        def record(*args):
            self.seen.append((name, args))
        return record

    def names(self) -> list[str]:
        return [name for name, _args in self.seen]


@pytest.fixture
def calls():
    return Calls()


@pytest.fixture
def navigator(parent, calls, windows_theme):
    made = BookNavigator(
        parent, theme=windows_theme,
        on_previous=calls.make("previous"), on_next=calls.make("next"),
        on_add=calls.make("add"), on_duplicate=calls.make("duplicate"),
        on_remove=calls.make("remove"))
    yield made
    if not made.closed:
        made.close()


@pytest.fixture
def surface(parent, calls, windows_theme):
    made = SharedMetadataSurface(
        parent, FIELDS, theme=windows_theme,
        on_shared_change=calls.make("shared"),
        on_book_change=calls.make("book"))
    yield made
    if not made.closed:
        made.close()


def adapter_tree() -> ast.Module:
    return ast.parse(
        Path(book_workspace_ui.__file__).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Composition — the house idiom, without exception
# --------------------------------------------------------------------------- #


def test_each_component_owns_a_frame_rather_than_being_one(navigator, surface):
    assert isinstance(navigator.frame, ttk.Frame)
    assert isinstance(surface.frame, ttk.Frame)
    # The two labelled groups are owned, not inherited from, either.
    assert isinstance(surface.shared_frame, ttk.Labelframe)
    assert isinstance(surface.book_frame, ttk.Labelframe)
    for component in (navigator, surface):
        assert not isinstance(component, (ttk.Frame, ttk.Labelframe, tk.Frame))
        assert not isinstance(component, tk.Widget)


def test_no_component_subclasses_a_widget_or_a_universal_base_panel():
    tree = adapter_tree()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            spelled = ast.unparse(base)
            assert "Frame" not in spelled, (node.name, spelled)
            assert "Labelframe" not in spelled, (node.name, spelled)
            assert "Widget" not in spelled, (node.name, spelled)
            assert "Panel" not in spelled, (node.name, spelled)


def test_the_public_surface_is_exactly_two_components_and_one_error():
    assert book_workspace_ui.__all__ == [
        "BookWorkspaceUiError", "BookNavigator", "SharedMetadataSurface"]
    tree = adapter_tree()
    public = {node.name for node in tree.body
              if isinstance(node, ast.ClassDef) and not node.name.startswith("_")}
    assert public == {"BookWorkspaceUiError", "BookNavigator", "SharedMetadataSurface"}


def test_no_manager_controller_or_service_class_was_invented():
    tree = adapter_tree()
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef)}
    for invented in ("BookWorkspaceController", "WorkspaceManager", "BookService",
                     "NavigatorController", "SharedMetadataController",
                     "BookPanel", "BasePanel"):
        assert invented not in declared, invented


# --------------------------------------------------------------------------- #
# The navigator
# --------------------------------------------------------------------------- #


def test_a_single_book_reads_book_one_of_one(navigator):
    navigator.render(workspace(book()))
    assert navigator.position_text == "Book 1 of 1"
    assert navigator.position_variable.get() == "Book 1 of 1"


def test_previous_is_unavailable_at_the_first_book(navigator):
    navigator.render(workspace(book(), book(), book()))
    assert navigator.availability()[BookNavigator.PREVIOUS] is False
    assert str(navigator.buttons[BookNavigator.PREVIOUS].cget("state")) == "disabled"


def test_next_is_unavailable_at_the_last_book(navigator):
    first, second = book(), book()
    space = workspace(first, second)
    space = next_book(space).workspace
    navigator.render(space)
    assert navigator.position_text == "Book 2 of 2"
    assert navigator.availability()[BookNavigator.NEXT] is False
    assert str(navigator.buttons[BookNavigator.NEXT].cget("state")) == "disabled"


def test_both_are_available_in_the_middle(navigator):
    space = next_book(workspace(book(), book(), book())).workspace
    navigator.render(space)
    assert navigator.position_text == "Book 2 of 3"
    assert navigator.availability()[BookNavigator.PREVIOUS] is True
    assert navigator.availability()[BookNavigator.NEXT] is True


def test_navigation_does_not_wrap(navigator):
    """The model does not wrap, and the adapter reads that rather than restating it."""
    space = workspace(book(), book())
    navigator.render(space)
    assert navigator.availability()[BookNavigator.PREVIOUS] is False
    assert previous_book(space).changed is False, "the model agrees"

    space = next_book(space).workspace
    navigator.render(space)
    assert navigator.availability()[BookNavigator.NEXT] is False
    assert next_book(space).changed is False


@pytest.mark.parametrize("action", ["previous", "next", "add", "duplicate"])
def test_pressing_a_button_calls_its_callback(navigator, calls, action):
    space = next_book(workspace(book(), book(), book())).workspace
    navigator.render(space)
    assert navigator.invoke(action) is True
    assert calls.names() == [action]


def test_pressing_an_unavailable_button_does_nothing(navigator, calls):
    navigator.render(workspace(book()))
    assert navigator.invoke(BookNavigator.PREVIOUS) is False
    assert calls.seen == []


def test_rendering_the_model_result_after_add_gives_book_two_of_two(navigator):
    space = workspace(book())
    navigator.render(space)
    assert navigator.position_text == "Book 1 of 1"

    space = add_book(space, id_factory=IdFactory("late-")).workspace
    navigator.render(space)
    assert navigator.position_text == "Book 2 of 2", "and the new book is selected"


def test_rendering_the_model_result_after_remove_updates_x_of_y(navigator):
    space = workspace(book(), book(), book())
    space = next_book(space).workspace
    navigator.render(space)
    assert navigator.position_text == "Book 2 of 3"

    space = remove_book(space, id_factory=IdFactory("late-")).workspace
    navigator.render(space)
    assert navigator.position_text == "Book 2 of 2"


def test_duplicate_through_the_model_copies_configuration_and_empties_inputs(navigator):
    original = book(count=2, **{"Author": "Kept"})
    space = workspace(original)
    navigator.render(space)
    navigator.invoke(BookNavigator.DUPLICATE)

    space = duplicate_book(space, id_factory=IdFactory("late-")).workspace
    navigator.render(space)
    assert navigator.position_text == "Book 2 of 2"
    copy = space.current
    assert copy.configuration["Author"] == "Kept"
    assert copy.is_empty, "the duplicate starts with no imported inputs"
    assert copy.book_id != original.book_id


def test_the_navigator_stores_no_second_index_or_count():
    tree = adapter_tree()
    navigator = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.ClassDef) and node.name == "BookNavigator")
    slots = [node for node in ast.walk(navigator)
             if isinstance(node, ast.Assign)
             and any(getattr(t, "id", "") == "__slots__" for t in node.targets)]
    assert slots, "the house idiom uses __slots__"
    spelled = ast.unparse(slots[0])
    for invented in ("_index", "_count", "_total", "_page", "_pages"):
        assert invented not in spelled, invented


def test_the_position_comes_from_the_models_derived_values(navigator):
    space = next_book(workspace(book(), book(), book())).workspace
    navigator.render(space)
    assert navigator.position == (space.current_position, space.count)


def test_the_adapter_mints_no_identity_and_mutates_no_workspace(navigator, calls):
    space = workspace(book())
    before = space.books, space.current_book_id, space.revision
    navigator.render(space)
    navigator.invoke(BookNavigator.ADD)
    navigator.invoke(BookNavigator.DUPLICATE)

    assert (space.books, space.current_book_id, space.revision) == before
    assert navigator.workspace is space
    assert calls.names() == ["add", "duplicate"], "it only reported"

    tree = adapter_tree()
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    called |= {node.func.attr for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for model_op in ("new_book_id", "next_id", "add_book", "duplicate_book",
                     "remove_book", "previous_book", "next_book", "select_book",
                     "replace_book", "BookMutation", "WorkspaceSnapshot", "BookJob"):
        assert model_op not in called, model_op


def test_rendering_refuses_anything_but_a_workspace_snapshot(navigator):
    for wrong in (None, "workspace", 7, {"books": ()}):
        with pytest.raises(BookWorkspaceUiError):
            navigator.render(wrong)


def test_an_unknown_action_is_refused(navigator):
    navigator.render(workspace(book()))
    with pytest.raises(BookWorkspaceUiError):
        navigator.invoke("teleport")


# --------------------------------------------------------------------------- #
# Remove — Decision 50A routing, and nothing more
# --------------------------------------------------------------------------- #


def test_a_pristine_book_reports_meaningful_work_false(navigator, calls):
    pristine = book()
    navigator.render(workspace(pristine))
    navigator.invoke(BookNavigator.REMOVE)
    assert calls.seen == [("remove", (False,))]
    assert has_meaningful_work(pristine) is False, "the model agrees"


def test_a_book_with_imported_files_reports_true(navigator, calls):
    imported = book(count=2)
    navigator.render(workspace(imported))
    navigator.invoke(BookNavigator.REMOVE)
    assert calls.seen == [("remove", (True,))]
    assert has_meaningful_work(imported) is True


def test_a_book_with_edited_configuration_reports_true(navigator, calls):
    configured = book(**{"Author": "Someone"})
    navigator.render(workspace(configured))
    navigator.invoke(BookNavigator.REMOVE)
    assert calls.seen == [("remove", (True,))]
    assert has_meaningful_work(configured) is True


def test_the_answer_is_the_models_not_a_second_predicate(navigator):
    for entry in (book(), book(count=2), book(**{"Author": "A"}),
                  book(count=1, **{"Narrator": "N"})):
        navigator.render(workspace(entry))
        assert navigator.meaningful_work() is has_meaningful_work(entry)


def test_the_adapter_declares_no_meaningful_work_predicate_of_its_own():
    tree = adapter_tree()
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for reimplemented in ("has_meaningful_work", "is_meaningful", "_meaningful",
                          "is_pristine", "_would_lose_work"):
        assert reimplemented not in declared, reimplemented

    # It calls the model's, which is how the answer stays single.
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "has_meaningful_work" in called


def test_the_adapter_never_reaches_for_a_confirmation_dialog():
    """Confirmation policy is the caller's. Decision 50A, split correctly."""
    tree = adapter_tree()
    seen = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    seen |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for dialog in ("ask_confirm", "askyesno", "showwarning", "showerror",
                   "messagebox", "ask_files", "ask_folder"):
        assert dialog not in seen, dialog
    assert not hasattr(book_workspace_ui, "ask_confirm")


# --------------------------------------------------------------------------- #
# The Shared Metadata surface
# --------------------------------------------------------------------------- #


def test_the_consumer_vocabulary_drives_the_rendered_fields(surface):
    assert surface.fields == FIELDS
    for name in FIELDS:
        assert surface.book_field_enabled(name) is True


def test_the_adapter_hard_codes_no_universal_metadata_vocabulary():
    """It must not know what a title is."""
    tree = adapter_tree()
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for universal in ("title", "author", "narrator", "series", "album", "genre",
                      "album_artist", "series_index", "year", "comment"):
        assert universal not in literals, universal
        assert universal.title() not in literals, universal


@pytest.mark.parametrize("vocabulary", [
    ("only_one",),
    ("a", "b", "c", "d", "e"),
    ("one", "two"),
])
def test_any_consumer_vocabulary_renders(parent, windows_theme, vocabulary):
    made = SharedMetadataSurface(parent, vocabulary, theme=windows_theme)
    try:
        assert made.fields == tuple(vocabulary)
        made.render(workspace(book(), shared=SharedMetadata.for_fields(vocabulary)))
    finally:
        made.close()


@pytest.mark.parametrize("bad", ["fields", b"fields", 7, None])
def test_a_vocabulary_must_be_an_iterable_of_names(parent, bad):
    with pytest.raises(BookWorkspaceUiError):
        SharedMetadataSurface(parent, bad)


@pytest.mark.parametrize("bad", [("",), ("   ",), (None,), (7,)])
def test_a_field_name_must_be_a_non_blank_string(parent, bad):
    with pytest.raises(BookWorkspaceUiError):
        SharedMetadataSurface(parent, bad)


def test_a_duplicate_field_name_is_refused(parent):
    with pytest.raises(BookWorkspaceUiError):
        SharedMetadataSurface(parent, ("Author", "Author"))


def test_raw_shared_values_render_exactly(surface):
    shared = SharedMetadata(FIELDS, {"Author": "  Ursula  ", "Narrator": "Kit"})
    surface.render(workspace(book(), shared=shared))
    assert surface.shared_value("Author") == "  Ursula  ", "not stripped"
    assert surface.shared_value("Narrator") == "Kit"
    assert surface.shared_value("display_name") == ""


def test_editing_a_shared_field_calls_the_consumer_callback(surface, calls):
    surface.render(workspace(book()))
    surface.set_shared_text("Author", "Typed")
    assert ("shared", ("Author", "Typed")) in calls.seen


def test_the_raw_text_is_not_silently_canonicalised(surface, calls):
    surface.render(workspace(book()))
    surface.set_shared_text("Author", "  spaced  ")
    reported = [args for name, args in calls.seen if name == "shared"]
    assert reported[-1] == ("Author", "  spaced  ")


def test_rendering_does_not_masquerade_as_a_user_edit(surface, calls):
    """A render writes the same variables an edit does; it must report nothing."""
    shared = SharedMetadata(FIELDS, {"Author": "From the model"})
    surface.render(workspace(book(), shared=shared))
    assert calls.seen == []


def test_editing_a_per_book_field_calls_the_consumer_callback(surface, calls):
    surface.render(workspace(book()))
    surface.set_book_text("Narrator", "Per book")
    assert ("book", ("Narrator", "Per book")) in calls.seen


def test_an_undeclared_field_is_refused(surface):
    surface.render(workspace(book()))
    for wrong in ("Publisher", "", "author"):
        with pytest.raises(BookWorkspaceUiError):
            surface.shared_value(wrong)


def test_the_surface_refuses_a_workspace_whose_shared_is_wrong(surface):
    for wrong in (None, "shared", 3):
        with pytest.raises(BookWorkspaceUiError):
            surface.render(wrong)


# --------------------------------------------------------------------------- #
# Decision 20B — the disabled projection is the model's
# --------------------------------------------------------------------------- #


def test_a_populated_shared_field_disables_the_matching_per_book_control(surface):
    shared = SharedMetadata(FIELDS, {"Author": "Shared value"})
    surface.render(workspace(book(**{"Author": "Mine"}), shared=shared))

    assert surface.book_field_enabled("Author") is False
    assert surface.book_field_enabled("Narrator") is True
    assert "Author" in disabled_fields(shared), "the model agrees"


def test_a_blank_shared_field_leaves_the_control_enabled(surface):
    for blank in ("", "   ", "\t"):
        shared = SharedMetadata(FIELDS, {"Author": blank})
        surface.render(workspace(book(), shared=shared))
        assert surface.book_field_enabled("Author") is True, repr(blank)
        assert "Author" not in disabled_fields(shared)


def test_clearing_a_shared_field_re_enables_the_control(surface):
    space = workspace(book(**{"Author": "Mine"}),
                      shared=SharedMetadata(FIELDS, {"Author": "Shared"}))
    surface.render(space)
    assert surface.book_field_enabled("Author") is False

    cleared = set_shared_metadata(space, SharedMetadata.for_fields(FIELDS)).workspace
    surface.render(cleared)
    assert surface.book_field_enabled("Author") is True


def test_the_per_book_raw_value_survives_the_whole_override_cycle(surface):
    entry = book(**{"Author": "Mine, untouched"})
    space = workspace(entry)
    surface.render(space)
    assert surface.book_value("Author") == "Mine, untouched"

    overridden = set_shared_metadata(
        space, SharedMetadata(FIELDS, {"Author": "Shared"})).workspace
    surface.render(overridden)
    assert surface.book_value("Author") == "Mine, untouched", "shown, just not editable"
    assert overridden.current.configuration["Author"] == "Mine, untouched"

    cleared = set_shared_metadata(
        overridden, SharedMetadata.for_fields(FIELDS)).workspace
    surface.render(cleared)
    assert surface.book_field_enabled("Author") is True
    assert surface.book_value("Author") == "Mine, untouched"


def test_render_returns_the_models_disabled_set(surface):
    shared = SharedMetadata(FIELDS, {"Author": "A", "Narrator": "N"})
    returned = surface.render(workspace(book(), shared=shared))
    assert returned == frozenset({"Author", "Narrator"})
    assert returned == disabled_fields(shared) & set(FIELDS)
    assert surface.shared_disabled_fields() == returned


def test_the_disabled_decision_reaches_the_model_rather_than_local_blank_logic():
    tree = adapter_tree()
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "disabled_fields" in called, "the projection must be asked for"

    attrs = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "strip" not in attrs or True  # see the stricter check below


def test_the_adapter_contains_no_second_blankness_rule():
    """``strip`` appears only where a field NAME is validated, never a value."""
    tree = adapter_tree()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "strip":
            owner = ast.unparse(node.func.value)
            assert owner in {"key", "label"}, (
                "strip() may validate a declared field key or label and nothing "
                f"else; found it on {owner!r}")
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for reimplemented in ("is_populated", "_is_populated", "_blank", "is_blank",
                          "effective_value", "effective_metadata", "_precedence"):
        assert reimplemented not in declared, reimplemented


def test_the_surface_never_writes_a_books_configuration(surface):
    entry = book(**{"Author": "Mine"})
    space = workspace(entry, shared=SharedMetadata(FIELDS, {"Author": "Shared"}))
    surface.render(space)
    surface.set_book_text("Author", "typed over")
    assert entry.configuration["Author"] == "Mine", "the value object is untouched"
    assert space.current.configuration["Author"] == "Mine"


def test_the_surface_reports_no_effective_value(surface, calls):
    space = workspace(book(**{"Author": "Mine"}),
                      shared=SharedMetadata(FIELDS, {"Author": "Shared"}))
    surface.render(space)
    surface.set_shared_text("Narrator", "N")
    for name, args in calls.seen:
        assert args[1] != "Mine", "an effective value must never travel a callback"


# --------------------------------------------------------------------------- #
# LockGroup — the real one, in a semantically valid composition
# --------------------------------------------------------------------------- #


def test_the_surface_registers_with_the_real_lock_group(surface, tk_root):
    group = LockGroup()
    try:
        surface.register_with(group)
        assert surface in group.registered(ControlKind.PROCESSING_OPTION)
    finally:
        group.close()


def test_a_running_job_locks_the_fields_through_the_lock_group(surface):
    group = LockGroup()
    try:
        surface.render(workspace(book()))
        surface.register_with(group)

        group.apply(JobState.RUNNING)
        assert surface.book_field_enabled("Author") is False

        group.apply(JobState.IDLE)
        assert surface.book_field_enabled("Author") is True
    finally:
        group.close()


def test_two_reasons_and_clearing_one_does_not_enable_the_control(surface):
    """A run owns it AND a shared value overrides it. Both must clear."""
    group = LockGroup()
    try:
        space = workspace(book(**{"Author": "Mine"}),
                          shared=SharedMetadata(FIELDS, {"Author": "Shared"}))
        surface.render(space)
        surface.register_with(group)

        group.apply(JobState.RUNNING)
        assert surface.book_field_enabled("Author") is False

        # Reason one goes: the run ends. The shared override still holds.
        group.apply(JobState.SUCCEEDED)
        assert surface.book_field_enabled("Author") is False, "still overridden"

        # Reason two goes: the shared value is cleared. Now, and only now.
        cleared = set_shared_metadata(
            space, SharedMetadata.for_fields(FIELDS)).workspace
        surface.render(cleared)
        assert surface.book_field_enabled("Author") is True
    finally:
        group.close()


def test_clearing_the_shared_override_alone_does_not_beat_a_running_job(surface):
    group = LockGroup()
    try:
        space = workspace(book(), shared=SharedMetadata(FIELDS, {"Author": "Shared"}))
        surface.render(space)
        surface.register_with(group)
        group.apply(JobState.RUNNING)

        cleared = set_shared_metadata(
            space, SharedMetadata.for_fields(FIELDS)).workspace
        surface.render(cleared)
        assert surface.book_field_enabled("Author") is False, "the run still owns it"

        group.apply(JobState.IDLE)
        assert surface.book_field_enabled("Author") is True
    finally:
        group.close()


def test_no_fake_job_state_represents_a_shared_override():
    """The two reasons are different facts and are never spelled as each other."""
    tree = adapter_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and ast.unparse(node).startswith("JobState"):
            raise AssertionError(f"the adapter names {ast.unparse(node)}")
    seen = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "JobState" not in seen
    assert "is_locked" not in seen
    assert "LOCK_MATRIX" not in seen
    # It uses the one seam LockGroup actually calls.
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)}
    assert "set_locked" in declared


def test_plan6_builds_no_second_lock_framework():
    tree = adapter_tree()
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef)}
    for invented in ("LockGroup", "FieldLockGroup", "LockMatrix", "LockManager"):
        assert invented not in declared, invented


def test_the_navigator_locks_as_one_unit(navigator):
    group = LockGroup()
    try:
        navigator.render(workspace(book(), book()))
        group.register(ControlKind.IMPORTED_INPUT, navigator)
        group.apply(JobState.RUNNING)
        assert navigator.locked is True
        assert str(navigator.buttons[BookNavigator.ADD].cget("state")) == "disabled"
        assert navigator.invoke(BookNavigator.ADD) is False

        group.apply(JobState.IDLE)
        assert navigator.locked is False
        assert str(navigator.buttons[BookNavigator.ADD].cget("state")) == "normal"
    finally:
        group.close()


def test_register_with_refuses_something_that_is_not_a_lock_group(surface):
    for wrong in (None, "group", 7, object()):
        with pytest.raises(BookWorkspaceUiError):
            surface.register_with(wrong)


# --------------------------------------------------------------------------- #
# Thread ownership
# --------------------------------------------------------------------------- #


def foreign_id() -> int:
    """An id that is certainly not this thread's."""
    return threading.get_ident() + 1


@pytest.mark.parametrize("method,args", [
    ("render", None), ("invoke", ("add",)), ("meaningful_work", ()),
    ("choose", ("u-1",)), ("set_locked", (True,)), ("close", ()),
])
def test_a_wrong_thread_navigator_call_is_refused(parent, method, args):
    made = BookNavigator(parent, thread_id=foreign_id())
    space = workspace(book())
    with pytest.raises(MainThreadError):
        getattr(made, method)(*(args if args is not None else (space,)))


@pytest.mark.parametrize("method,args", [
    ("render", None), ("shared_value", ("Author",)), ("book_value", ("Author",)),
    ("set_shared_text", ("Author", "x")), ("set_book_text", ("Author", "x")),
    ("set_locked", (True,)), ("register_with", (LockGroup,)), ("close", ()),
])
def test_a_wrong_thread_surface_call_is_refused(parent, method, args):
    made = SharedMetadataSurface(parent, FIELDS, thread_id=foreign_id())
    space = workspace(book())
    with pytest.raises(MainThreadError):
        getattr(made, method)(*(args if args is not None else (space,)))


def test_the_refusal_happens_before_a_widget_is_touched(parent):
    """The guard is the first statement, so nothing is half-done when it raises."""
    made = BookNavigator(parent, thread_id=foreign_id())
    before = made.position_variable.get()
    with pytest.raises(MainThreadError):
        made.render(workspace(book(), book()))
    assert made.position_variable.get() == before, "no label was written"
    assert made.workspace is None, "no state was recorded either"
    assert made.position == (0, 0)


def test_the_surface_refusal_happens_before_a_variable_is_written(parent):
    made = SharedMetadataSurface(parent, FIELDS, thread_id=foreign_id())
    shared = SharedMetadata(FIELDS, {"Author": "Would be written"})
    with pytest.raises(MainThreadError):
        made.render(workspace(book(), shared=shared))
    assert made.workspace is None
    assert made.shared_disabled_fields() == frozenset()


def test_every_public_tk_reaching_method_opens_with_the_guard():
    """Structural, so a method added later cannot quietly skip it."""
    tree = adapter_tree()
    expected = {
        "BookNavigator": {"render", "invoke", "meaningful_work", "choose",
                          "set_locked", "close"},
        "SharedMetadataSurface": {"render", "shared_value", "book_value",
                                  "set_shared_text", "set_book_text", "set_locked",
                                  "register_with", "close"},
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name not in expected:
            continue
        found = set()
        for method in node.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            if method.name.startswith("_"):
                continue
            body = [statement for statement in method.body
                    if not (isinstance(statement, ast.Expr)
                            and isinstance(statement.value, ast.Constant))]
            if not body:
                continue
            first = ast.unparse(body[0])
            if first.startswith("self._guard.require("):
                found.add(method.name)
        assert found == expected[node.name], (node.name, found)


def test_the_adapter_implements_no_threading_check_of_its_own():
    tree = adapter_tree()
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    assert "threading" not in modules
    seen = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "current_thread" not in seen
    assert "get_ident" not in seen


# --------------------------------------------------------------------------- #
# No second after chain
# --------------------------------------------------------------------------- #


def test_the_adapter_opens_no_after_chain():
    tree = adapter_tree()
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for scheduled in ("after", "after_idle", "after_cancel", "update",
                      "update_idletasks", "mainloop", "sleep"):
        assert scheduled not in called, scheduled


def test_the_adapter_builds_no_pump_thread_or_clock():
    tree = adapter_tree()
    seen = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    seen |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for owned_elsewhere in ("MainThreadPump", "Thread", "Timer", "Queue", "Event",
                            "monotonic", "perf_counter", "time", "now"):
        assert owned_elsewhere not in seen, owned_elsewhere


def test_no_scheduled_callback_is_left_behind(navigator, surface, tk_root):
    navigator.render(workspace(book(), book()))
    surface.render(workspace(book()))
    navigator.close()
    surface.close()
    # ``after info`` lists every pending Tk callback on this interpreter.
    assert tk_root.tk.call("after", "info") == ""


# --------------------------------------------------------------------------- #
# Teardown
# --------------------------------------------------------------------------- #


def test_close_is_idempotent(navigator, surface):
    navigator.render(workspace(book()))
    surface.render(workspace(book()))
    for component in (navigator, surface):
        component.close()
        assert component.closed is True
        component.close()          # must not raise
        assert component.closed is True


def test_a_press_after_close_does_nothing(navigator, calls):
    navigator.render(workspace(book(), book()))
    navigator.close()
    assert navigator.invoke(BookNavigator.ADD) is False
    assert calls.seen == []


def test_an_edit_after_close_reports_nothing(surface, calls):
    surface.render(workspace(book()))
    surface.close()
    surface.set_shared_text("Author", "too late")
    assert calls.seen == []


def test_close_survives_a_destroyed_parent(parent, windows_theme):
    made = BookNavigator(parent, theme=windows_theme)
    other = SharedMetadataSurface(parent, FIELDS, theme=windows_theme)
    made.render(workspace(book()))
    other.render(workspace(book()))
    parent.destroy()
    made.close()               # must not raise merely because Tk went first
    other.close()
    assert made.closed and other.closed


def test_render_after_close_does_not_raise(navigator, surface):
    navigator.close()
    surface.close()
    navigator.render(workspace(book(), book()))
    surface.render(workspace(book()))
    assert navigator.position_text == "Book 1 of 2", "state still tracked"


def test_a_closed_component_cannot_resurrect_a_callback(navigator, surface, calls):
    navigator.render(workspace(book()))
    navigator.close()
    navigator.render(workspace(book(), book()))
    navigator.invoke(BookNavigator.NEXT)
    surface.close()
    surface.render(workspace(book()))
    surface.set_shared_text("Author", "x")
    assert calls.seen == []


# --------------------------------------------------------------------------- #
# Platform and theme — Decision 29A
# --------------------------------------------------------------------------- #


def test_the_windows_surface_asks_for_the_approved_shared_keys(tk_root, windows_theme):
    """Mechanical: which key was asked for, not what colour came back."""
    asked: list[str] = []
    real = book_workspace_ui.style_name

    def spy(theme, key):
        asked.append(key)
        return real(theme, key)

    book_workspace_ui.style_name = spy
    try:
        frame = ttk.Frame(tk_root)
        made = SharedMetadataSurface(frame, FIELDS, theme=windows_theme)
        made.close()
        frame.destroy()
    finally:
        book_workspace_ui.style_name = real

    for approved in ("shared_labelframe", "shared_header", "shared_label"):
        assert approved in asked, approved
    # The per-book side is deliberately the ORDINARY treatment, so the two groups
    # cannot read as the same kind of thing.
    for ordinary in ("labelframe", "label"):
        assert ordinary in asked, ordinary
    for name in asked:
        assert real(windows_theme, name).startswith("ACT."), (name, real(windows_theme, name))


def test_the_windows_keys_resolve_to_the_already_approved_act_styles(windows_theme):
    expected = {
        "shared_surface": "ACT.Shared.TFrame",
        "shared_header": "ACT.SharedHeader.TLabel",
        "shared_label": "ACT.Shared.TLabel",
        "shared_secondary": "ACT.SharedSecondary.TLabel",
        "shared_checkbutton": "ACT.Shared.TCheckbutton",
        "shared_labelframe": "ACT.Shared.TLabelframe",
    }
    for key, style in expected.items():
        assert job_ui.style_name(windows_theme, key) == style


def test_the_adapter_declares_no_colour_font_or_metric_of_its_own():
    tree = adapter_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not node.value.startswith("#"), f"hex literal {node.value!r}"
    seen = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    seen |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for token in ("colors", "fonts", "metrics", "palette", "COLORS", "PALETTE"):
        assert token not in seen, token


def test_no_windows_only_metric_is_read():
    """Aqua bundles have a smaller metrics set; reading one unconditionally KeyErrors."""
    tree = adapter_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            spelled = ast.unparse(node)
            for windows_only in ("metrics", "styles", "fonts", "colors"):
                assert windows_only not in spelled, spelled


@pytest.mark.parametrize("shape", sorted(NATIVE_THEMES))
def test_the_adapter_renders_against_a_native_bundle(parent, shape):
    """Aqua and classic publish no ``styles``; the adapter must not care."""
    theme = NATIVE_THEMES[shape]
    made = BookNavigator(parent, theme=theme)
    other = SharedMetadataSurface(parent, FIELDS, theme=theme)
    try:
        made.render(workspace(book(), book()))
        other.render(workspace(book(),
                               shared=SharedMetadata(FIELDS, {"Author": "A"})))
        assert made.position_text == "Book 1 of 2"
        assert other.book_field_enabled("Author") is False
    finally:
        made.close()
        other.close()


@pytest.mark.parametrize("shape", ["aqua", "classic"])
def test_no_act_style_is_forced_onto_a_native_bundle(shape):
    theme = NATIVE_THEMES[shape]
    for key in ("shared_labelframe", "shared_header", "shared_label",
                "shared_secondary", "card", "button", "entry", "section"):
        assert job_ui.style_name(theme, key) == "", key


@pytest.mark.parametrize("shape", ["aqua", "classic"])
def test_a_native_bundle_yields_no_key_error(parent, shape):
    """The failure this test exists for is a KeyError, so it must not be caught."""
    theme = NATIVE_THEMES[shape]
    made = SharedMetadataSurface(parent, FIELDS, theme=theme)
    try:
        made.render(workspace(book()))
        made.set_locked(True)
        made.set_locked(False)
        assert made.shared_value("Author") == ""
    finally:
        made.close()


def test_the_adapter_contains_no_platform_branch():
    tree = adapter_tree()
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    assert "platform" not in modules
    assert "sys" not in modules
    seen = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    seen |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for branch in ("platform", "system", "uname", "win32", "darwin", "name"):
        if branch == "name":
            continue          # a field's ``.name`` is not ``os.name``
        assert branch not in seen, branch


def test_the_theme_is_asked_through_the_one_shared_helper():
    """Every style comes from ``style_name``, and nothing is coloured by hand.

    The adapter builds only ttk widgets, which ttk styles by name, so it needs no
    ``style_tk_widget`` call at all — a consumer that adds a classic ``Text`` uses
    that there, as the developer harness does for its chapter box.
    """
    tree = adapter_tree()
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "style_name" in called

    built = {ast.unparse(node.func) for node in ast.walk(tree)
             if isinstance(node, ast.Call)}
    widgets = {spelled for spelled in built if spelled.startswith(("tk.", "ttk."))}
    classic = {spelled for spelled in widgets
               if spelled.startswith("tk.") and spelled != "tk.StringVar"}
    assert classic == set(), (
        f"a classic widget would need ui_theme.style_tk_widget: {classic}")


# --------------------------------------------------------------------------- #
# No second Plan 3 UI, and no business logic
# --------------------------------------------------------------------------- #


def test_the_adapter_recreates_no_plan3_component():
    tree = adapter_tree()
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef)}
    seen = declared | {node.id for node in ast.walk(tree)
                       if isinstance(node, ast.Name)}
    for plan3 in ("ImportedFileList", "ImportOptionsBar", "ImportStatusBar",
                  "ImportAdapter", "JobControlBar", "JobStatusView",
                  "SummaryDetailsView", "JobAdapter", "ProgressIndicator",
                  "MainThreadPump", "JobEventStream", "JobReporter", "EtaEstimator",
                  "LoggerBridge", "JobController"):
        assert plan3 not in seen, plan3


def test_the_adapter_offers_no_retry_or_run_control():
    tree = adapter_tree()
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for label in ("Retry Failed", "Pause", "Resume", "Cancel", "Start", "Open Output"):
        assert label not in literals, label
    seen = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    for name in ("RunResult", "RetryRequest", "retry_failed_books",
                 "WorkspaceRunResult", "BookDisposition", "RunSnapshot",
                 "capture_workspace_run", "SuccessNumbers"):
        assert name not in seen, name


def test_the_adapter_reaches_no_disk_process_or_network():
    """Structural, and deliberately *not* a bare name match.

    An earlier draft of this guard failed on the adapter's own ``winfo_exists``
    probe: the defensive helper binds the bound method to a local called ``exists``
    and then calls it, which looks like ``Path.exists`` to a name-matching check and
    is nothing of the sort. That is the same false positive Phase 0 recorded against
    a substring check, so the question is asked properly instead — a filesystem call
    is an attribute call on something, and none of the modules that could supply one
    is imported at all.
    """
    tree = adapter_tree()
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    for banned in ("os", "os.path", "pathlib", "subprocess", "shutil", "socket",
                   "urllib", "http", "requests", "shared.output_paths",
                   "shared.paths"):
        assert banned not in modules, banned

    attribute_calls = {ast.unparse(node.func) for node in ast.walk(tree)
                       if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Attribute)}
    for spelled in attribute_calls:
        leaf = spelled.rsplit(".", 1)[-1]
        for forbidden in ("open", "Popen", "mkdir", "makedirs", "rmtree", "unlink",
                          "glob", "rglob", "walk", "listdir", "scandir", "iterdir",
                          "stat", "urlopen", "connect", "is_file", "is_dir",
                          "resolve", "expanduser", "samefile"):
            assert leaf != forbidden, spelled
        # ``winfo_exists`` is a Tk widget probe; ``Path.exists`` would not be.
        assert leaf != "exists" or spelled.endswith("winfo_exists"), spelled

    bare_calls = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    for forbidden in ("open", "Popen", "eval", "exec", "compile", "__import__"):
        assert forbidden not in bare_calls, forbidden


def test_that_disk_guard_actually_detects_a_filesystem_call():
    """Mutation check: the corrected guard must still reject the real thing."""
    sample = ast.parse(
        "from pathlib import Path" + NEWLINE
        + "def f(name):" + NEWLINE
        + "    return Path(name).exists()" + NEWLINE)
    attribute_calls = {ast.unparse(node.func) for node in ast.walk(sample)
                       if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Attribute)}
    offending = [spelled for spelled in attribute_calls
                 if spelled.rsplit(".", 1)[-1] == "exists"
                 and not spelled.endswith("winfo_exists")]
    assert offending == ["Path(name).exists"]


def test_that_disk_guard_accepts_the_tk_widget_probe():
    sample = ast.parse(
        "def alive(widget):" + NEWLINE
        + "    return bool(widget.winfo_exists())" + NEWLINE)
    attribute_calls = {ast.unparse(node.func) for node in ast.walk(sample)
                       if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Attribute)}
    offending = [spelled for spelled in attribute_calls
                 if spelled.rsplit(".", 1)[-1] == "exists"
                 and not spelled.endswith("winfo_exists")]
    assert offending == []


def test_the_business_layer_stays_the_one_authority():
    """The adapter calls the model's projections; it declares none of them."""
    tree = adapter_tree()
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for model_owned in ("has_meaningful_work", "disabled_fields", "effective_value",
                        "effective_metadata", "is_populated", "add_book",
                        "duplicate_book", "remove_book", "previous_book",
                        "next_book", "select_book", "replace_book", "book_groups",
                        "capture_workspace_run", "retry_failed_books"):
        assert model_owned not in declared, model_owned


def test_book_workspace_itself_stays_tk_free():
    for module in ("book_workspace.py", "numbering.py"):
        source = (Path(book_workspace.__file__).parent / module).read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module or "")
        assert not any(entry.split(".")[0] == "tkinter" for entry in modules), module
        assert "shared.book_workspace_ui" not in modules, module


# --------------------------------------------------------------------------- #
# Field labels — the maintainer's manual-gate finding
#
# The first draft put the field name once, at the far left of a wide row, with
# "Shared" and "This book" headings above two entries. The maintainer reported
# the right-hand entry reading as unlabelled, which it did: knowing what it held
# meant tracking a row back across the window. Each entry now carries its own
# label, and these tests hold it there.
# --------------------------------------------------------------------------- #


def label_texts(widget) -> list[str]:
    """Every label text inside one container, in grid order."""
    return [child.cget("text") for child in widget.winfo_children()
            if isinstance(child, ttk.Label)]


def test_the_consumer_supplies_a_display_label_for_each_field(parent, windows_theme):
    made = SharedMetadataSurface(
        parent, (("title", "Title"), ("author", "Author")), theme=windows_theme)
    try:
        assert made.fields == ("title", "author"), "keys address values"
        assert dict(made.labels) == {"title": "Title", "author": "Author"}
    finally:
        made.close()


def test_both_sides_of_every_field_carry_that_label(parent, windows_theme):
    """Shared Title AND This Book Title; Shared Author AND This Book Author."""
    made = SharedMetadataSurface(
        parent, (("title", "Title"), ("author", "Author")), theme=windows_theme)
    try:
        shared_side = label_texts(made.shared_frame)
        book_side = label_texts(made.book_frame)
        assert shared_side == ["Title", "Author"], shared_side
        assert book_side == ["Title", "Author"], book_side
    finally:
        made.close()


def test_each_entry_sits_in_the_same_group_as_its_own_label(parent, windows_theme):
    """Nobody has to trace a row across the window to know what an entry means."""
    made = SharedMetadataSurface(
        parent, (("title", "Title"), ("author", "Author")), theme=windows_theme)
    try:
        for key, display in (("title", "Title"), ("author", "Author")):
            row = made._rows[key]
            assert row.label.cget("text") == display
            assert row.book_label.cget("text") == display
            # Same parent, adjacent rows: label directly above its entry.
            assert row.label.master is row.shared_entry.master is made.shared_frame
            assert row.book_label.master is row.book_entry.master is made.book_frame
            assert (row.label.grid_info()["row"]
                    == row.shared_entry.grid_info()["row"] - 1)
            assert (row.book_label.grid_info()["row"]
                    == row.book_entry.grid_info()["row"] - 1)
    finally:
        made.close()


def test_the_two_groups_are_captioned_and_visually_different(parent, windows_theme):
    made = SharedMetadataSurface(parent, FIELDS, theme=windows_theme,
                                 shared_title="Shared", book_title="This Book")
    try:
        assert made.shared_frame.cget("text") == "Shared"
        assert made.book_frame.cget("text") == "This Book"
        shared_style = str(made.shared_frame.cget("style"))
        book_style = str(made.book_frame.cget("style"))
        assert shared_style == "ACT.Shared.TLabelframe"
        assert book_style == "ACT.TLabelframe"
        assert shared_style != book_style, "LEFT is global, RIGHT is this book"
    finally:
        made.close()


def test_the_shared_side_keeps_the_approved_shared_treatment(parent, windows_theme):
    made = SharedMetadataSurface(parent, FIELDS, theme=windows_theme)
    try:
        for key in made.fields:
            row = made._rows[key]
            assert str(row.label.cget("style")) == "ACT.Shared.TLabel"
            assert str(row.book_label.cget("style")) == "ACT.TLabel"
    finally:
        made.close()


def test_a_bare_name_still_works_and_labels_itself(parent, windows_theme):
    """The simpler spelling is not removed; the label just defaults to the key."""
    made = SharedMetadataSurface(parent, ("author",), theme=windows_theme)
    try:
        assert made.fields == ("author",)
        assert dict(made.labels) == {"author": "author"}
        assert label_texts(made.shared_frame) == ["author"]
        assert label_texts(made.book_frame) == ["author"]
    finally:
        made.close()


def test_the_two_spellings_may_be_mixed(parent, windows_theme):
    made = SharedMetadataSurface(parent, ("author", ("title", "Title")),
                                 theme=windows_theme)
    try:
        assert dict(made.labels) == {"author": "author", "title": "Title"}
    finally:
        made.close()


@pytest.mark.parametrize("bad", [
    (("title",),),                      # a one-element pair is not a pair
    (("title", "Title", "extra"),),
    ((None, "Title"),),
    (("title", None),),
    (("title", "   "),),
    ((7, "Title"),),
])
def test_a_malformed_field_declaration_is_refused(parent, bad):
    with pytest.raises(BookWorkspaceUiError):
        SharedMetadataSurface(parent, bad)


def test_a_duplicate_key_is_refused_even_with_different_labels(parent):
    with pytest.raises(BookWorkspaceUiError):
        SharedMetadataSurface(parent, (("title", "Title"), ("title", "Name")))


def test_two_fields_may_share_a_label_because_a_label_is_presentation(
        parent, windows_theme):
    """Only the key addresses a value, so only the key has to be unique."""
    made = SharedMetadataSurface(
        parent, (("title", "Name"), ("author", "Name")), theme=windows_theme)
    try:
        assert made.fields == ("title", "author")
        assert label_texts(made.shared_frame) == ["Name", "Name"]
    finally:
        made.close()


def test_the_label_declaration_carries_no_business_meaning(parent, windows_theme):
    """A label changes what is drawn and nothing about precedence."""
    keyed = SharedMetadataSurface(parent, (("author", "Author"),),
                                  theme=windows_theme)
    plain = SharedMetadataSurface(parent, ("author",), theme=windows_theme)
    try:
        shared = SharedMetadata(("author",), {"author": "A"})
        space = workspace(book(**{"author": "Mine"}), shared=shared)
        assert keyed.render(space) == plain.render(space)
        assert keyed.book_field_enabled("author") is plain.book_field_enabled("author")
    finally:
        keyed.close()
        plain.close()


def test_the_adapter_still_hard_codes_no_metadata_label_either():
    """A display label is consumer data, exactly as a key is."""
    tree = adapter_tree()
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for concrete in ("title", "Title", "author", "Author", "narrator", "Narrator",
                     "series", "Series", "album", "Album"):
        assert concrete not in literals, concrete


# --------------------------------------------------------------------------- #
# The direct Book selector — v0.6.3 Plan 6 Phase 2 (focused MP3 plan section 13)
#
# Phase 8 shipped Previous / Next only. Phase 2 of the focused continuation adds
# the compact direct selector the Phase 1 audit named as the gap: a read-only
# ``ttk.Combobox`` whose rows are the rendered snapshot's books, in order, and
# whose choice reports the **stable book id** — never a row number, never a
# label. The navigator keeps no list of its own: every row is derived from the
# last rendered ``WorkspaceSnapshot`` at the moment it is asked for.
# --------------------------------------------------------------------------- #


def hinted(label: str, count: int = 0) -> BookJob:
    """A book carrying this suite's own display hint. The adapter knows no key."""
    return book(count, display_name=label)


def describe(entry: BookJob) -> str:
    return str(entry.configuration.get("display_name", ""))


@pytest.fixture
def described(parent, calls, windows_theme):
    made = BookNavigator(
        parent, theme=windows_theme, describe=describe,
        on_select=calls.make("select"), on_next=calls.make("next"))
    yield made
    if not made.closed:
        made.close()


def test_the_navigator_owns_a_read_only_combobox_selector(navigator):
    assert isinstance(navigator.selector, ttk.Combobox)
    assert str(navigator.selector.cget("state")) == "readonly"
    assert navigator.selector.master is navigator.frame


def test_the_selector_lists_every_book_by_position(navigator):
    space = workspace(book(), book(), book())
    navigator.render(space)
    assert navigator.selector_labels == ("Book 1", "Book 2", "Book 3")
    assert tuple(navigator.selector.cget("values")) == navigator.selector_labels


def test_the_selector_shows_the_consumers_hint_after_the_position(described):
    space = workspace(hinted(""), hinted("The Hobbit"), hinted("  "))
    described.render(space)
    assert described.selector_labels == ("Book 1", "Book 2 — The Hobbit", "Book 3")


def test_duplicate_hints_stay_unambiguous_because_the_number_leads(described):
    space = workspace(hinted("Dune"), hinted("Dune"))
    described.render(space)
    assert described.selector_labels == ("Book 1 — Dune", "Book 2 — Dune")
    assert len(set(described.selector_labels)) == 2


def test_a_describe_that_is_not_callable_is_refused(parent):
    for wrong in ("display_name", 7, object()):
        with pytest.raises(BookWorkspaceUiError):
            BookNavigator(parent, describe=wrong)


def test_the_selector_rows_resolve_to_stable_book_ids(navigator):
    space = workspace(book(), book(), book())
    navigator.render(space)
    assert navigator.selector_ids == tuple(entry.book_id for entry in space.books)

    # Remove the first book: row 1 now means what used to be row 2.
    after = remove_book(space, id_factory=_IDS).workspace
    navigator.render(after)
    assert navigator.selector_ids == tuple(entry.book_id for entry in after.books)
    assert navigator.selector_ids == tuple(
        entry.book_id for entry in space.books[1:])
    assert navigator.selector_labels == ("Book 1", "Book 2"), "position, not identity"


def test_the_selector_tracks_the_current_book(navigator):
    space = workspace(book(), book(), book())
    navigator.render(space)
    assert navigator.selector.current() == 0
    moved = next_book(space).workspace
    navigator.render(moved)
    assert navigator.selector.current() == 1
    assert navigator.selector.get() == "Book 2"


def test_choosing_reports_the_book_id_and_never_a_row_number(described, calls):
    space = workspace(hinted("A"), hinted("B"), hinted("C"))
    described.render(space)
    target = space.books[2].book_id
    assert described.choose(target) is True
    assert calls.seen == [("select", (target,))]


def test_a_combobox_pick_routes_through_the_same_id_mapping(described, calls):
    space = workspace(hinted("A"), hinted("B"), hinted("C"))
    described.render(space)
    described.selector.current(1)
    described.selector.event_generate("<<ComboboxSelected>>")
    assert calls.seen == [("select", (space.books[1].book_id,))]


def test_choosing_the_current_book_is_a_no_op(described, calls):
    space = workspace(hinted("A"), hinted("B"))
    described.render(space)
    assert described.choose(space.current_book_id) is False
    described.selector.current(0)
    described.selector.event_generate("<<ComboboxSelected>>")
    assert calls.seen == []


def test_choosing_an_id_the_snapshot_does_not_hold_is_refused(described):
    space = workspace(hinted("A"), hinted("B"))
    described.render(space)
    stranger = book().book_id
    with pytest.raises(BookWorkspaceUiError):
        described.choose(stranger)
    with pytest.raises(BookWorkspaceUiError):
        described.choose("")


def test_choosing_before_any_render_does_nothing(described, calls):
    assert described.choose("u-anything") is False
    assert calls.seen == []


def test_the_selection_is_applied_by_the_model_and_rendered_back(described, calls):
    """The adapter reports; the consumer calls ``select_book``; render shows it."""
    space = workspace(hinted("A"), hinted("B"), hinted("C"))
    described.render(space)
    target = space.books[2].book_id
    described.choose(target)
    selected = book_workspace.select_book(space, target).workspace
    described.render(selected)
    assert described.position == (3, 3)
    assert described.selector.current() == 2
    assert described.workspace is selected


def test_the_selector_locks_with_the_rest_of_the_navigator(described, calls):
    space = workspace(hinted("A"), hinted("B"))
    described.render(space)
    described.set_locked(True)
    assert str(described.selector.cget("state")) == "disabled"
    assert described.choose(space.books[1].book_id) is False
    assert calls.seen == []
    described.set_locked(False)
    assert str(described.selector.cget("state")) == "readonly"


def test_the_selector_is_unavailable_without_a_rendered_book(navigator):
    assert navigator.availability()[BookNavigator.SELECT] is False
    navigator.render(workspace(book()))
    assert navigator.availability()[BookNavigator.SELECT] is True


def test_choosing_after_close_does_nothing(described, calls):
    space = workspace(hinted("A"), hinted("B"))
    described.render(space)
    described.close()
    assert described.choose(space.books[1].book_id) is False
    assert calls.seen == []
    assert str(described.selector.cget("state")) == "disabled"


def test_the_navigator_keeps_no_row_table_of_its_own():
    """Rows and ids are derived from the rendered snapshot, never stored beside it."""
    tree = adapter_tree()
    navigator = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.ClassDef) and node.name == "BookNavigator")
    slots = next(node for node in ast.walk(navigator)
                 if isinstance(node, ast.Assign)
                 and any(getattr(t, "id", "") == "__slots__" for t in node.targets))
    spelled = ast.unparse(slots)
    for invented in ("_ids", "_labels", "_rows", "_selector_ids", "_by_row",
                     "_book_ids", "_lookup"):
        assert invented not in spelled, invented


def test_the_selector_never_calls_the_model_operation_itself():
    tree = adapter_tree()
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    called |= {node.func.attr for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "select_book" not in called


def test_the_selector_hint_vocabulary_is_the_consumers():
    literals = {node.value for node in ast.walk(adapter_tree())
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for consumer_owned in ("display_name", "album", "folder", "title", "Album"):
        assert consumer_owned not in literals, consumer_owned


# --------------------------------------------------------------------------- #
# Stable row labels — Phase 4 manual-gate remediation
#
# ``Book {position}`` is a position, and a position is reused: remove the first
# of three and the second is relabelled "Book 1". The maintainer read that as a
# Book's files moving under another Book's name. The navigator therefore lets
# the consumer label a row itself, from whatever stable fact it keeps beside the
# stable id; it still knows no numbering scheme and stores no table of its own.
# --------------------------------------------------------------------------- #


def stable_label(entry: BookJob, position: int) -> str:
    """This suite's own rule: the book's ``display_name`` is the whole label."""
    return f"#{entry.configuration.get('display_name', '?')}"


@pytest.fixture
def labelled(parent, calls, windows_theme):
    made = BookNavigator(parent, theme=windows_theme, label_for=stable_label,
                         on_select=calls.make("select"))
    yield made
    if not made.closed:
        made.close()


def test_a_consumer_label_replaces_the_positional_row_label(labelled):
    space = workspace(hinted("A"), hinted("B"), hinted("C"))
    labelled.render(space)
    assert labelled.selector_labels == ("#A", "#B", "#C")


def test_removing_the_first_book_does_not_relabel_the_survivors(labelled):
    space = workspace(hinted("A"), hinted("B"), hinted("C"))
    labelled.render(space)
    survivors = remove_book(space, id_factory=_IDS).workspace
    labelled.render(survivors)
    assert labelled.selector_labels == ("#B", "#C"), "no row is called A any more"
    assert labelled.selector_ids == tuple(b.book_id for b in survivors.books)
    assert labelled.position_text == "Book 1 of 2", "position stays a position"
    assert labelled.heading_text == "#B  (1 of 2)"
    assert labelled.position_variable.get() == labelled.heading_text


def test_the_heading_names_the_current_book_not_its_slot(labelled):
    space = workspace(hinted("A"), hinted("B"))
    labelled.render(next_book(space).workspace)
    assert labelled.heading_text == "#B  (2 of 2)"
    assert labelled.selector.get() == "#B"


def test_without_a_consumer_rule_the_heading_is_the_position(navigator):
    navigator.render(workspace(book(), book()))
    assert navigator.heading_text == navigator.position_text == "Book 1 of 2"
    assert navigator.position_variable.get() == "Book 1 of 2"


def test_a_label_rule_that_is_not_callable_is_refused(parent):
    with pytest.raises(BookWorkspaceUiError):
        BookNavigator(parent, label_for="display_name")


def test_the_label_rule_receives_the_position_but_owes_it_nothing(parent, windows_theme):
    seen: list[tuple[str, int]] = []

    def rule(entry, position):
        seen.append((entry.configuration.get("display_name", ""), position))
        return "same"

    made = BookNavigator(parent, theme=windows_theme, label_for=rule)
    try:
        made.render(workspace(hinted("A"), hinted("B")))
        assert set(seen) >= {("A", 1), ("B", 2)}
        # Even identical labels resolve by id: the row table is the snapshot.
        assert len(made.selector_ids) == 2
    finally:
        made.close()


# --------------------------------------------------------------------------- #
# Compact, consumer-placeable surface layout — Phase 2
#
# The prototype laid the two groups side by side with the fields stacked, which
# is right for two fields and too tall for five plus a track list, a chapter
# editor and a log at 920x600. ``layout="rows"`` puts Shared above This Book and
# runs the fields left to right. Same contract, same labels on both sides, same
# two-reason locking; only the geometry moves.
# --------------------------------------------------------------------------- #


TWO = (("title_key", "Title"), ("author_key", "Author"))


def test_columns_is_still_the_default_layout(parent, windows_theme):
    made = SharedMetadataSurface(parent, TWO, theme=windows_theme)
    try:
        assert made.layout == "columns"
        assert made.shared_frame.grid_info()["row"] == made.book_frame.grid_info()["row"]
        assert made.shared_frame.grid_info()["column"] == 0
        assert made.book_frame.grid_info()["column"] == 1
    finally:
        made.close()


def test_the_rows_layout_stacks_shared_above_this_book(parent, windows_theme):
    made = SharedMetadataSurface(parent, TWO, theme=windows_theme, layout="rows")
    try:
        assert made.layout == "rows"
        shared_at = made.shared_frame.grid_info()
        book_at = made.book_frame.grid_info()
        assert shared_at["column"] == book_at["column"] == 0
        assert shared_at["row"] < book_at["row"], "global first, this book beneath"
    finally:
        made.close()


def test_the_rows_layout_runs_the_fields_left_to_right(parent, windows_theme):
    made = SharedMetadataSurface(parent, TWO, theme=windows_theme, layout="rows")
    try:
        for column, (key, display) in enumerate(TWO):
            row = made._rows[key]
            # Each side still labels its own entry, directly above it.
            assert row.label.cget("text") == display
            assert row.book_label.cget("text") == display
            assert row.label.master is row.shared_entry.master is made.shared_frame
            assert row.book_label.master is row.book_entry.master is made.book_frame
            assert row.label.grid_info()["column"] == column
            assert row.shared_entry.grid_info()["column"] == column
            assert row.book_entry.grid_info()["column"] == column
            assert row.label.grid_info()["row"] == row.shared_entry.grid_info()["row"] - 1
            assert row.book_label.grid_info()["row"] == row.book_entry.grid_info()["row"] - 1
        # Every field column shares the width equally.
        for frame in (made.shared_frame, made.book_frame):
            for column in range(len(TWO)):
                assert int(frame.grid_columnconfigure(column)["weight"]) == 1
    finally:
        made.close()


def test_the_rows_layout_keeps_the_whole_contract(parent, windows_theme, calls):
    made = SharedMetadataSurface(
        parent, TWO, theme=windows_theme, layout="rows",
        on_shared_change=calls.make("shared"), on_book_change=calls.make("book"))
    try:
        keys = tuple(key for key, _label in TWO)
        shared = SharedMetadata(keys, {"title_key": "Everyone"})
        overridden = made.render(workspace(book(title_key="Mine"), shared=shared))
        assert overridden == frozenset({"title_key"})
        assert made.book_field_enabled("title_key") is False
        assert made.book_field_enabled("author_key") is True
        assert made.book_value("title_key") == "Mine", "the per-book value survives"
        assert str(made.shared_frame.cget("style")) == "ACT.Shared.TLabelframe"
        assert str(made.book_frame.cget("style")) == "ACT.TLabelframe"
        made.set_shared_text("author_key", "typed")
        assert calls.seen[-1] == ("shared", ("author_key", "typed"))
    finally:
        made.close()


def test_an_unknown_layout_is_refused(parent, windows_theme):
    for wrong in ("grid", "", None, 3):
        with pytest.raises(BookWorkspaceUiError):
            SharedMetadataSurface(parent, TWO, theme=windows_theme, layout=wrong)


def test_the_caption_and_header_can_be_dropped_by_a_compact_consumer(
        parent, windows_theme):
    """A consumer that captions the region itself does not get a second caption."""
    made = SharedMetadataSurface(parent, TWO, theme=windows_theme,
                                 layout="rows", show_header=False)
    try:
        assert made.title_label is None
        assert made.header is None
        captions = [child for child in made.frame.winfo_children()
                    if isinstance(child, ttk.Label)]
        assert captions == [], "nothing but the two groups"
        assert made.shared_frame.grid_info()["row"] == 0
    finally:
        made.close()


def test_the_default_still_shows_the_caption_and_header(parent, windows_theme):
    made = SharedMetadataSurface(parent, TWO, theme=windows_theme)
    try:
        assert isinstance(made.title_label, ttk.Label)
        assert isinstance(made.header, ttk.Label)
        assert made.title_label.cget("text") == "Shared Metadata"
    finally:
        made.close()


def test_a_long_label_can_wrap_and_entries_can_start_narrow(parent, windows_theme):
    """Two presentation knobs a wide consumer needs at 920px, and nothing more.

    Added for the MP3 Tool (focused MP3 plan, Phase 4): five fields across one
    row only fit the minimum window when the entries' *requested* width is
    small and a long display label may fold. Neither knob reads a font or a
    metric, and neither changes the contract.
    """
    long = (("time", "Add/Remove Time at End of Each Track (seconds)"),
            ("album", "Album"))
    made = SharedMetadataSurface(parent, long, theme=windows_theme, layout="rows",
                                 wraplength=150, entry_width=12)
    try:
        for key in ("time", "album"):
            row = made._rows[key]
            assert int(row.label.cget("wraplength")) == 150
            assert int(row.book_label.cget("wraplength")) == 150
            assert int(row.shared_entry.cget("width")) == 12
            assert int(row.book_entry.cget("width")) == 12
        # Equal growth, not equal width: no uniform group ties the columns.
        for frame in (made.shared_frame, made.book_frame):
            for column in range(2):
                assert not frame.grid_columnconfigure(column)["uniform"]
    finally:
        made.close()


def test_the_knobs_are_absent_by_default(parent, windows_theme):
    made = SharedMetadataSurface(parent, TWO, theme=windows_theme)
    try:
        row = made._rows["title_key"]
        assert str(row.label.cget("wraplength")) in ("", "0"), "unset"
        assert int(row.shared_entry.cget("width")) == 20, "ttk's own default"
    finally:
        made.close()


@pytest.mark.parametrize("shape", sorted(NATIVE_THEMES))
def test_the_rows_layout_and_the_selector_stay_native_off_windows(parent, shape):
    theme = NATIVE_THEMES[shape]
    made = BookNavigator(parent, theme=theme, describe=describe)
    other = SharedMetadataSurface(parent, TWO, theme=theme, layout="rows")
    try:
        made.render(workspace(hinted("A"), hinted("B")))
        other.render(workspace(book()))
        assert str(made.selector.cget("style")) == ""
        assert made.selector_labels == ("Book 1 — A", "Book 2 — B")
    finally:
        made.close()
        other.close()


def test_on_windows_the_selector_asks_for_the_combobox_style(tk_root, windows_theme):
    asked: list[str] = []
    real = book_workspace_ui.style_name

    def spy(theme, key):
        asked.append(key)
        return real(theme, key)

    book_workspace_ui.style_name = spy
    try:
        frame = ttk.Frame(tk_root)
        made = BookNavigator(frame, theme=windows_theme)
        made.close()
        frame.destroy()
    finally:
        book_workspace_ui.style_name = real
    assert "combobox" in asked
    assert real(windows_theme, "combobox").startswith("ACT.")


# --------------------------------------------------------------------------- #
# The harness's Chapter Titles section — live behaviour
#
# Chapter titles are ORDINARY per-book ``BookJob.configuration``. Everything
# below therefore works because the Phase 1-4 model already works, not because
# anything chapter-shaped was added to it: no production module knows the key,
# and ``has_meaningful_work`` was not taught about chapters.
#
# These tests drive the real harness, so they are also the only place the
# harness itself is executed. It builds widgets, so it belongs here with the
# other live-Tk coverage rather than in a structural module.
# --------------------------------------------------------------------------- #

import importlib.util  # noqa: E402

HARNESS_PATH = Path(__file__).resolve().parent / "manual_plan6_harness.py"


@pytest.fixture(scope="module")
def harness_module():
    spec = importlib.util.spec_from_file_location("plan6_harness", HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness(tk_root, harness_module, monkeypatch):
    """A real harness on a hidden window. No dialog is ever shown."""
    monkeypatch.setattr(harness_module.job_ui, "ask_confirm",
                        lambda parent, title, message: False)
    window = tk.Toplevel(tk_root)
    window.withdraw()
    made = harness_module.Harness(window, books=1)
    yield made
    try:
        made.navigator.close()
        made.surface.close()
        window.destroy()
    except tk.TclError:
        pass


def chapters_of(made) -> str:
    return str(made._workspace.current.configuration.get("chapter_titles", ""))


def test_the_harness_vocabulary_is_title_and_author_only(harness_module):
    assert harness_module.FIELDS == (("title", "Title"), ("author", "Author"))
    assert harness_module.FIELD_KEYS == ("title", "author")
    assert "narrator" not in harness_module.FIELD_KEYS


def test_the_chapter_section_is_labelled_unmistakably(harness):
    assert harness.chapters.cget("text") == "Chapter Titles"
    captions = [child.cget("text") for child in harness.chapters.winfo_children()
                if isinstance(child, ttk.Label)]
    assert "One chapter title per line." in captions


def test_typing_chapter_titles_stores_the_raw_multiline_string(harness):
    harness.type_chapter_titles("Chapter One\nChapter Two\nChapter Three")
    assert chapters_of(harness) == "Chapter One\nChapter Two\nChapter Three"
    assert harness.chapter_titles_text() == "Chapter One\nChapter Two\nChapter Three"


def test_the_raw_text_is_stored_without_being_parsed(harness):
    """Plan 6 does not interpret chapter semantics, so it must not tidy them."""
    raw = "  Leading space\n\nBlank line above\nTrailing space   "
    harness.type_chapter_titles(raw)
    assert chapters_of(harness) == raw


def test_chapter_text_is_ordinary_book_configuration(harness):
    harness.type_chapter_titles("Only this")
    current = harness._workspace.current
    assert current.configuration["chapter_titles"] == "Only this"
    assert set(current.configuration) <= {"title", "author", "chapter_titles"}
    # And it is frozen with everything else, through the one deep-freeze.
    assert isinstance(current.configuration, Mapping)
    with pytest.raises(TypeError):
        current.configuration["chapter_titles"] = "no"


def test_add_book_starts_with_blank_chapter_text(harness):
    harness.type_chapter_titles("Book one chapters")
    harness.on_add()
    assert harness.navigator.position_text == "Book 2 of 2"
    assert harness.chapter_titles_text() == ""
    assert chapters_of(harness) == ""


def test_each_book_keeps_its_own_chapter_text_across_navigation(harness):
    harness.type_chapter_titles("First book")
    harness.on_add()
    harness.type_chapter_titles("Second book")

    harness.on_previous()
    assert harness.chapter_titles_text() == "First book", "preserved exactly"
    harness.on_next()
    assert harness.chapter_titles_text() == "Second book"
    harness.on_previous()
    assert harness.chapter_titles_text() == "First book"


def test_duplicate_copies_chapter_text_and_leaves_inputs_empty(harness):
    harness.type_chapter_titles("Chapter One\nChapter Two")
    original = harness._workspace.current
    harness.on_duplicate()

    copy = harness._workspace.current
    assert copy.book_id != original.book_id
    assert chapters_of(harness) == "Chapter One\nChapter Two", "configuration copied"
    assert harness.chapter_titles_text() == "Chapter One\nChapter Two"
    assert copy.is_empty, "Decision 49A: the imported inputs do not come with it"


def test_editing_the_copy_does_not_touch_the_original(harness):
    harness.type_chapter_titles("Shared start")
    harness.on_duplicate()
    harness.type_chapter_titles("Changed on the copy")
    harness.on_previous()
    assert harness.chapter_titles_text() == "Shared start"


def test_a_book_with_only_chapter_text_is_meaningful_work(harness):
    """It works because chapter text is ordinary configuration, not by a special rule."""
    harness.on_add()
    blank = harness._workspace.current
    assert has_meaningful_work(blank) is False

    harness.type_chapter_titles("Chapter One")
    assert has_meaningful_work(harness._workspace.current) is True


def test_removing_a_chapter_text_only_book_asks_for_confirmation(
        harness, harness_module, monkeypatch):
    asked: list[str] = []
    monkeypatch.setattr(
        harness_module.job_ui, "ask_confirm",
        lambda parent, title, message: asked.append(title) or False)

    harness.on_add()
    harness.navigator.invoke("remove")
    assert asked == [], "a pristine book is removed without asking"

    harness.on_add()
    harness.type_chapter_titles("Chapter One")
    before = harness._workspace.count
    harness.navigator.invoke("remove")
    assert asked == ["Remove book"], "chapter text alone is work worth protecting"
    assert harness._workspace.count == before, "cancelling changed nothing"


def test_the_production_predicate_was_not_taught_about_chapters():
    """``has_meaningful_work`` must not name the harness's key."""
    source = Path(book_workspace.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    predicate = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef)
                     and node.name == "has_meaningful_work")
    spelled = ast.unparse(predicate)
    assert "chapter" not in spelled.lower(), spelled


def test_chapter_titles_never_enter_shared_metadata(harness):
    assert "chapter_titles" not in harness._workspace.shared.fields
    harness.type_chapter_titles("Chapter One")
    assert "chapter_titles" not in harness._workspace.shared.fields
    assert "chapter_titles" not in harness._workspace.shared.values
    assert "chapter_titles" not in harness.surface.fields


def test_a_shared_override_never_targets_the_chapter_field(harness):
    harness.type_chapter_titles("Chapter One")
    harness.on_shared_change("title", "A series title")

    assert harness.surface.book_field_enabled("title") is False
    assert harness.surface.book_field_enabled("author") is True
    assert "chapter_titles" not in disabled_fields(harness._workspace.shared)
    assert str(harness.chapter_text.cget("state")) == "normal", "still editable"
    assert harness.chapter_titles_text() == "Chapter One", "and untouched"


def test_clearing_a_shared_field_leaves_the_chapter_text_alone(harness):
    harness.type_chapter_titles("Chapter One")
    harness.on_shared_change("title", "Series")
    harness.on_shared_change("title", "")
    assert harness.surface.book_field_enabled("title") is True
    assert harness.chapter_titles_text() == "Chapter One"


def test_rendering_the_chapter_box_is_not_reported_as_an_edit(harness):
    """Navigation rewrites the box; that must not look like typing."""
    harness.type_chapter_titles("First")
    revision_before = harness.on_add() or harness._workspace.revision
    harness.on_previous()
    settled = harness._workspace.revision
    harness.render_chapters()          # a repaint with nothing to change
    assert harness._workspace.revision == settled, "no model change from a repaint"


def test_the_chapter_editor_opens_no_scheduled_callback(harness, tk_root):
    harness.type_chapter_titles("Chapter One")
    harness.render_chapters()
    assert tk_root.tk.call("after", "info") == ""
