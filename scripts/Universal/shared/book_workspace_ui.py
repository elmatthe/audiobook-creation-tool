"""The Tk adapter for the shared multi-book workspace — v0.6.3 Drop 1 (Plan 6), Phase 8,
salvaged and extended by the focused MP3 continuation (Phase 2).

This is the **one** Plan 6 module that may touch Tk, exactly as ``shared/job_ui.py``
is Plan 3's. It owns pixels and callback routing; ``shared/book_workspace.py`` keeps
owning every decision, and nothing here re-implements a rule that lives there.

What lives here
---------------
:class:`BookNavigator` — Previous, Next, a ``Book X of Y`` label, a compact direct
Book selector, Add Book, Duplicate Book and Remove Book. :class:`SharedMetadataSurface`
— the distinct workspace-level Shared Metadata region, together with the matching
per-book controls the Decision 20B disabled projection lands on. The surface is a
**text-field** surface and nothing more: a consumer whose Shared vocabulary includes
something that is not a line of text (artwork, a toggle, a status) owns that control
itself and asks the same model projection for whether it is overridden.

The house idiom, without exception
----------------------------------
Each class **owns** a ``frame`` rather than subclassing ``ttk.Frame``,
``ttk.Labelframe`` or a universal panel base class — there is no universal base panel
in this repository and Plan 6 does not introduce one. Every decision arrives as a
caller-supplied callback. Every public method that reaches Tk opens with
``MainThreadGuard.require``, so a worker is refused *before* a widget is touched.
Teardown is idempotent and survives a destroyed root.

What deliberately does **not** live here
---------------------------------------
**No business logic.** Not :func:`~shared.book_workspace.has_meaningful_work`, not
the add/duplicate/remove/navigate rules, not
:func:`~shared.book_workspace.disabled_fields`, not Shared Metadata precedence, not
:func:`~shared.book_workspace.effective_metadata`, not capture, dispositions, retry or
numbering. This module *calls* those pure projections and renders their answers; it
computes none of them, and it never asks its own version of a question the model has
already answered. In particular it contains no ``value.strip()``, no ``bool(value)``
and no second blankness test: whether a per-book control is disabled comes from
``disabled_fields`` and from nowhere else.

**No second Plan 3 UI.** No imported-file list, no import options bar, no import or
job adapter, no progress or status view, no Retry Failed button, no pause/resume/cancel
controls, no log tabs, no logger and no event pump. A consumer composes this navigator
and this surface *alongside* the existing Plan 3 adapters; Plan 6 adds only what Plan 3
has not got — book navigation and a Shared Metadata surface.

**No second ``after`` chain.** Nothing here polls, schedules, sleeps or times. Plan 3's
``MainThreadPump`` owns the one callback chain. This adapter is push-driven: the caller
changes the model and then calls :meth:`render` with the workspace it got back.

**No mutation, and no identity.** The adapter mints no book id, builds no
``BookMutation`` and never edits a ``WorkspaceSnapshot``. It renders one immutable
snapshot at a time and reports presses through callbacks; the caller applies the model
operation and hands back the result.

**No platform branch and no new theme token.** There is no ``sys.platform``, no
``os.name`` and no ``platform.system()`` anywhere in this file. Styles are asked for
through ``job_ui.style_name``, which returns the registered ``ACT.*`` name on Windows
and ``""`` — native appearance — on aqua and classic. No colour, font, metric or hex
literal is declared here, and no Windows-only metric is read: aqua bundles have no
``styles``, no ``fonts`` and a smaller ``metrics`` set, so this module reads none of
them and lays out with plain padding the way ``job_ui`` already does. Every widget
here is a ttk widget, which ttk styles by name, so ``ui_theme.style_tk_widget`` is
not needed and not called — a consumer that adds a classic ``Text`` or ``Canvas``
of its own uses it there, as the developer harness does.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable, Mapping, Sequence
from tkinter import ttk
from types import MappingProxyType

from shared.book_workspace import (
    BookJob,
    SharedMetadata,
    WorkspaceSnapshot,
    disabled_fields,
    has_meaningful_work,
)
from shared.job_control import ControlKind
from shared.job_ui import JobUiError, MainThreadGuard, style_name

__all__ = [
    "BookWorkspaceUiError",
    "BookNavigator",
    "SharedMetadataSurface",
]


class BookWorkspaceUiError(JobUiError):
    """Raised when this adapter is used in a way its contract forbids.

    A ``JobUiError`` subclass so a consumer that already handles the Plan 3 adapters'
    errors handles these too, and a named type so a Plan 6 contract violation is
    distinguishable from a Plan 3 one.
    """


# --------------------------------------------------------------------------- #
# Small widget helpers
#
# The same defensive shape ``job_ui`` uses: a destroyed widget is an answer, not a
# crash. They are private because they are not a second widget framework.
# --------------------------------------------------------------------------- #


def _alive(widget: object) -> bool:
    if widget is None:
        return False
    exists = getattr(widget, "winfo_exists", None)
    if exists is None:
        return False
    try:
        return bool(exists())
    except tk.TclError:
        return False


def _configure(widget: object, **options: object) -> bool:
    if not _alive(widget):
        return False
    try:
        widget.configure(**options)  # type: ignore[attr-defined]
    except tk.TclError:
        return False
    return True


def _enable(widget: object, enabled: bool) -> bool:
    return _configure(widget, state="normal" if enabled else "disabled")


def _read(variable: object) -> str:
    """A ``StringVar``'s raw text, or ``""`` if Tk has already gone away."""
    try:
        return str(variable.get())  # type: ignore[attr-defined]
    except (tk.TclError, AttributeError):
        return ""


def _write(variable: object, value: str) -> bool:
    try:
        variable.set(value)  # type: ignore[attr-defined]
    except (tk.TclError, AttributeError):
        return False
    return True


def _field_specs(fields: Iterable[object]) -> tuple[tuple[str, str], ...]:
    """The consumer's declared vocabulary: ``(field key, display label)`` pairs.

    This adapter has **no** universal field list. It does not know what a title is,
    and it must not learn: the consumer declares its own supported fields exactly as
    it declares its own ``SupportedTypeCatalog``.

    A consumer may write either spelling, and **one** declaration carries both halves
    so a key and its label cannot drift apart::

        ("title", "author")                    # label == key
        (("title", "Title"), ("author", "Author"))

    The label is presentation and nothing else. It carries no validation and no
    business meaning: two fields may not share a *key*, because a key addresses a
    value, but nothing here inspects a label beyond requiring it to be showable.
    """
    if isinstance(fields, (str, bytes)) or not isinstance(fields, Iterable):
        raise BookWorkspaceUiError("fields must be an iterable of field declarations")
    specs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in fields:
        if isinstance(entry, str):
            key, label = entry, entry
        elif isinstance(entry, Sequence) and not isinstance(entry, (str, bytes)):
            items = tuple(entry)
            if len(items) != 2:
                raise BookWorkspaceUiError(
                    "a field declaration is a name or a (key, label) pair, got "
                    f"{len(items)} values")
            key, label = items
        else:
            raise BookWorkspaceUiError(
                f"a field declaration must be a name or a (key, label) pair, "
                f"got {entry!r}")
        if not isinstance(key, str) or not key.strip():
            raise BookWorkspaceUiError(
                f"a field key must be a non-blank string, got {key!r}")
        if not isinstance(label, str) or not label.strip():
            raise BookWorkspaceUiError(
                f"a field label must be a non-blank string, got {label!r}")
        if key in seen:
            raise BookWorkspaceUiError(f"duplicate field key {key!r}")
        seen.add(key)
        specs.append((key, label))
    return tuple(specs)


# --------------------------------------------------------------------------- #
# The book navigator (drop section 19)
# --------------------------------------------------------------------------- #


class BookNavigator:
    """Previous / Next / ``Book X of Y`` / Add / Duplicate / Remove.

    It renders **one immutable ``WorkspaceSnapshot`` at a time** and owns none of it.
    The caller owns the current workspace, calls the model operation when a callback
    fires, and hands the resulting snapshot back to :meth:`render`.

    Availability is the model's answer, not this class's opinion: ``Previous`` is
    unavailable at the first book and ``Next`` at the last, both read straight off
    ``WorkspaceSnapshot.current_position`` and ``.count``. **Navigation does not
    wrap** — and it does not wrap here because the model does not wrap, not because
    this class re-decided it.

    ``Book X of Y`` is rendered from those same two derived values. No second index
    and no second count is stored, there is no page identity, and there is no fixed
    number of pages.

    **The direct selector** (added by the focused MP3 continuation, Phase 2) is a
    read-only ``ttk.Combobox`` beside that label. Its rows are the rendered
    snapshot's books in order — ``Book 3``, or ``Book 3 — <hint>`` when the consumer
    passes a ``describe`` callback — and a pick is resolved back to the **stable
    book id** and reported through ``on_select(book_id)``. The consumer calls the
    model's ``select_book`` and renders the result; the navigator resolves rows
    through the snapshot every time and keeps no table of its own, so the selector
    creates no page identity and no fixed page count either. Two books described
    identically stay two rows because the number leads.

    **A row label may be the consumer's** (Phase 4 manual-gate remediation).
    ``Book {position}`` is a position, and a position is reused: remove the first
    of three books and the second is relabelled ``Book 1``, which reads as one
    book's files appearing under another's name. A consumer that keeps a stable
    display fact beside the stable id — a number assigned once and never reused,
    say — passes ``label_for(book, position)`` and that string becomes the whole
    row label, and the heading beside the buttons shows it with the position in
    brackets. The navigator still knows no numbering scheme, stores none, and
    resolves every row through the snapshot exactly as before.

    Remove Book passes the model's own meaningful-work answer to ``on_remove``. This
    class does not decide whether to confirm and never calls ``ask_confirm``: it
    reports ``has_meaningful_work(current_book)`` and the caller shows the dialog or
    does not (Decision 50A).

    **Two geometries, one contract** (focused MP3 plan, Phase 12). ``layout="row"``
    is the accepted single row. ``layout="stacked"`` puts Previous / Next / the
    heading / the selector on one row and Add / Duplicate / Remove beneath, for a
    consumer whose native controls are too wide for one row inside its minimum
    window. The consumer chooses; nothing here reads a platform or a theme
    metric, and the buttons, labels, callbacks and rendering are the same either way.
    """

    #: The two geometries. ``"row"`` is the accepted single row; ``"stacked"``
    #: folds the three Book actions under the navigation row.
    LAYOUTS = ("row", "stacked")

    #: The labels this navigator renders, in the order it renders them.
    ADD = "add"
    DUPLICATE = "duplicate"
    REMOVE = "remove"
    PREVIOUS = "previous"
    NEXT = "next"
    #: The direct selector. Not a button: it reports a chosen book id through
    #: :meth:`choose` rather than a bare press through :meth:`invoke`.
    SELECT = "select"

    LABELS: Mapping[str, str] = {
        PREVIOUS: "◀ Previous",
        NEXT: "Next ▶",
        ADD: "Add Book",
        DUPLICATE: "Duplicate Book",
        REMOVE: "Remove Book",
    }

    #: Characters the direct selector shows before the dropdown takes over. A
    #: long hint is not clipped by anything the adapter decides — the consumer
    #: chooses what to describe a book by, and the popup lists every row whole.
    SELECTOR_WIDTH = 22

    __slots__ = ("_guard", "_theme", "_closed", "_locked", "_workspace",
                 "_callbacks", "_position", "_describe", "_label_for", "_layout",
                 "frame", "buttons", "label", "position_variable", "selector")

    def __init__(
        self,
        parent: object,
        *,
        theme: Mapping[str, object] | None = None,
        thread_id: int | None = None,
        layout: str = "row",
        describe: Callable[[BookJob], object] | None = None,
        label_for: Callable[[BookJob, int], object] | None = None,
        on_previous: Callable[[], object] | None = None,
        on_next: Callable[[], object] | None = None,
        on_add: Callable[[], object] | None = None,
        on_duplicate: Callable[[], object] | None = None,
        on_remove: Callable[[bool], object] | None = None,
        on_select: Callable[[str], object] | None = None,
    ) -> None:
        if layout not in self.LAYOUTS:
            raise BookWorkspaceUiError(
                f"layout must be one of {self.LAYOUTS!r}, got {layout!r}")
        if describe is not None and not callable(describe):
            raise BookWorkspaceUiError(
                "describe must be a callable taking a BookJob and returning the "
                f"display hint for the selector, got {type(describe).__name__}")
        if label_for is not None and not callable(label_for):
            raise BookWorkspaceUiError(
                "label_for must be a callable taking (BookJob, position) and "
                f"returning the row label, got {type(label_for).__name__}")
        self._guard = MainThreadGuard(thread_id)
        self._theme = theme
        self._closed = False
        self._locked = False
        self._layout = layout
        self._workspace: WorkspaceSnapshot | None = None
        self._position: tuple[int, int] = (0, 0)
        self._describe = describe
        self._label_for = label_for
        self._callbacks: dict[str, Callable[..., object] | None] = {
            self.PREVIOUS: on_previous,
            self.NEXT: on_next,
            self.ADD: on_add,
            self.DUPLICATE: on_duplicate,
            self.REMOVE: on_remove,
            self.SELECT: on_select,
        }

        self.frame = ttk.Frame(parent, style=style_name(theme, "card"))
        self.position_variable = tk.StringVar(master=self.frame, value="")
        self.label = ttk.Label(self.frame, textvariable=self.position_variable,
                               style=style_name(theme, "section"))

        neutral = style_name(theme, "button")
        self.buttons: dict[str, ttk.Button] = {}
        for column, action in enumerate(
                (self.PREVIOUS, self.NEXT, self.ADD, self.DUPLICATE, self.REMOVE)):
            button = ttk.Button(
                self.frame, text=self.LABELS[action], style=neutral,
                command=lambda bound=action: self.invoke(bound))
            self.buttons[action] = button

        # The direct selector (focused MP3 plan section 13): read-only, so the
        # only text it can ever hold is a row this navigator rendered. Its rows
        # are the rendered snapshot's books in order and nothing else; the pick
        # is resolved back to that snapshot's stable book id in :meth:`_picked`.
        self.selector = ttk.Combobox(
            self.frame, state="readonly", width=self.SELECTOR_WIDTH,
            exportselection=False, style=style_name(theme, "combobox"))
        self.selector.bind("<<ComboboxSelected>>", self._picked)

        # Prev | Next | "Book X of Y" | [selector] | Add | Duplicate | Remove
        #
        # The label column carries the weight, so the slack lives in the middle and
        # the actions keep their own width. Its padding is deliberately modest:
        # this row is the widest bounded thing Plan 6 draws, and at the 920px minimum
        # width every pixel it does not claim is a pixel an action cannot be clipped
        # by. Section 19.1 forbids solving that with a whole-panel scrollbar.
        if layout == "row":
            self.buttons[self.PREVIOUS].grid(row=0, column=0)
            self.buttons[self.NEXT].grid(row=0, column=1, padx=(6, 0))
            self.label.grid(row=0, column=2, padx=(8, 8))
            self.selector.grid(row=0, column=3, padx=(0, 8))
            self.buttons[self.ADD].grid(row=0, column=4)
            self.buttons[self.DUPLICATE].grid(row=0, column=5, padx=(6, 0))
            self.buttons[self.REMOVE].grid(row=0, column=6, padx=(6, 0))
        else:
            # Stacked: the three Book actions fold under the navigation row,
            # left-aligned in the same columns so the two rows read as one
            # block. The label column still carries the slack, and the
            # selector keeps the right edge of the block.
            self.buttons[self.PREVIOUS].grid(row=0, column=0, sticky="w")
            self.buttons[self.NEXT].grid(row=0, column=1, sticky="w", padx=(6, 0))
            self.label.grid(row=0, column=2, sticky="w", padx=(8, 8))
            self.selector.grid(row=0, column=3, sticky="e")
            self.buttons[self.ADD].grid(row=1, column=0, sticky="w", pady=(4, 0))
            self.buttons[self.DUPLICATE].grid(row=1, column=1, sticky="w",
                                              padx=(6, 0), pady=(4, 0))
            self.buttons[self.REMOVE].grid(row=1, column=2, columnspan=2,
                                           sticky="w", padx=(8, 0), pady=(4, 0))
        self.frame.columnconfigure(2, weight=1)

    # -- pure state, no Tk reached ----------------------------------------- #

    @property
    def guard(self) -> MainThreadGuard:
        return self._guard

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def layout(self) -> str:
        return self._layout

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def workspace(self) -> WorkspaceSnapshot | None:
        """The snapshot last rendered. Held to read, never to edit."""
        return self._workspace

    @property
    def position(self) -> tuple[int, int]:
        """``(X, Y)`` as last rendered, both from the model's derived values."""
        return self._position

    @property
    def position_text(self) -> str:
        """Exactly ``Book X of Y``, or ``""`` before anything has been rendered."""
        position, count = self._position
        return f"Book {position} of {count}" if count else ""

    @property
    def selector_ids(self) -> tuple[str, ...]:
        """Row -> stable book id, derived from the rendered snapshot on demand.

        Nothing is stored beside the snapshot: row ``i`` means ``books[i]`` of the
        workspace last handed to :meth:`render`, and there is no other table. A
        removed or reordered book therefore cannot leave a stale row behind.
        """
        if self._workspace is None:
            return ()
        return tuple(entry.book_id for entry in self._workspace.books)

    def _row_label(self, entry: BookJob, position: int) -> str:
        """One row's text: the consumer's rule if given, else ``Book {position}``
        with the optional hint. Presentation only — whitespace is collapsed and
        nothing about it is stored, compared or validated."""
        if self._label_for is not None:
            return " ".join(str(self._label_for(entry, position)).split())
        hint = ""
        if self._describe is not None:
            hint = " ".join(str(self._describe(entry)).split())
        return f"Book {position} — {hint}" if hint else f"Book {position}"

    @property
    def selector_labels(self) -> tuple[str, ...]:
        """One row per book, in the rendered snapshot's order.

        By default ``Book N``, or ``Book N — <hint>`` when the consumer supplied a
        ``describe`` callback and it returned something to show; the number leads,
        so two books described identically remain two distinct rows. With a
        ``label_for`` rule the consumer's string is the whole row, and keeping
        rows distinguishable is then its responsibility — rows still resolve to
        ids, never to their text.
        """
        if self._workspace is None:
            return ()
        return tuple(self._row_label(entry, position)
                     for position, entry in enumerate(self._workspace.books, start=1))

    @property
    def heading_text(self) -> str:
        """What the label beside the buttons shows.

        ``Book X of Y`` unless the consumer labels rows itself, in which case the
        current book's own label with its position in brackets — so the heading
        names the book, and the slot it happens to occupy stays visibly a slot.
        """
        if self._label_for is None or self._workspace is None:
            return self.position_text
        position, count = self._position
        current = self._workspace.current
        if not isinstance(current, BookJob) or not count:
            return self.position_text
        return f"{self._row_label(current, position)}  ({position} of {count})"

    def availability(self) -> Mapping[str, bool]:
        """Which actions are offered, derived from the rendered snapshot.

        Previous is unavailable at the first book and Next at the last — the model's
        own no-wrap rule, read rather than restated. Add is always meaningful.
        Duplicate, Remove and the direct selector need a book to act on.
        """
        position, count = self._position
        has_book = count > 0
        return {
            self.PREVIOUS: has_book and position > 1,
            self.NEXT: has_book and position < count,
            self.ADD: True,
            self.DUPLICATE: has_book,
            self.REMOVE: has_book,
            self.SELECT: has_book,
        }

    # -- Tk-reaching, guarded ---------------------------------------------- #

    def render(self, workspace: WorkspaceSnapshot) -> Mapping[str, bool]:
        """Show one immutable snapshot. Returns which actions are offered."""
        self._guard.require("render")
        if not isinstance(workspace, WorkspaceSnapshot):
            raise BookWorkspaceUiError(
                "workspace must be a book_workspace.WorkspaceSnapshot, got "
                f"{type(workspace).__name__}")
        self._workspace = workspace
        self._position = (workspace.current_position, workspace.count)
        available = self.availability()
        if not self._closed:
            _write(self.position_variable, self.heading_text)
            for action, offered in available.items():
                _enable(self.buttons.get(action), offered and not self._locked)
            self._render_selector(available[self.SELECT])
        return available

    def _render_selector(self, offered: bool) -> None:
        """Rows from the snapshot, the current book highlighted, nothing remembered."""
        labels = self.selector_labels
        if not _configure(self.selector, values=labels):
            return
        position, _count = self._position
        try:
            if labels and position >= 1:
                self.selector.current(position - 1)
            else:
                self.selector.set("")
        except tk.TclError:
            return
        self._enable_selector(offered and not self._locked)

    def _enable_selector(self, enabled: bool) -> bool:
        # A read-only combobox has three states, not two: "readonly" is its
        # enabled state, so the generic normal/disabled helper cannot be used.
        return _configure(self.selector, state="readonly" if enabled else "disabled")

    def _picked(self, _event: object = None) -> None:
        """The user opened the dropdown and chose a row. Resolve it to an id."""
        if self._closed or self._locked:
            return
        try:
            row = int(self.selector.current())
        except (tk.TclError, ValueError):
            return
        ids = self.selector_ids
        if 0 <= row < len(ids):
            self.choose(ids[row])

    def choose(self, book_id: str) -> bool:
        """Report that *book_id* was chosen directly. The model applies it.

        The id must be one the rendered snapshot holds — a row is only ever a
        view of that snapshot, so an id from anywhere else is a contract error,
        not a silent no-op. Choosing the book that is already current reports
        nothing, exactly as ``select_book`` would change nothing.
        """
        self._guard.require("choose")
        if self._closed or self._locked or self._workspace is None:
            return False
        if book_id not in self.selector_ids:
            raise BookWorkspaceUiError(
                f"{book_id!r} is not a book of the rendered workspace")
        if book_id == self._workspace.current_book_id:
            # Put the highlight back where the model says it is; the pick
            # changed nothing and must not look as though it did.
            self._render_selector(self.availability()[self.SELECT])
            return False
        callback = self._callbacks.get(self.SELECT)
        if callback is None:
            return False
        callback(book_id)
        return True

    def invoke(self, action: str) -> bool:
        """Press one button. A press the current snapshot forbids does nothing."""
        self._guard.require("invoke")
        if action not in self._callbacks or action == self.SELECT:
            raise BookWorkspaceUiError(f"unknown navigator action {action!r}")
        if self._closed or self._locked or not self.availability().get(action, False):
            return False
        callback = self._callbacks.get(action)
        if callback is None:
            return False
        if action == self.REMOVE:
            # Decision 50A: the model answers "would this lose work?", and the
            # caller decides whether that deserves a confirmation. This class does
            # not own either half.
            callback(self.meaningful_work())
        else:
            callback()
        return True

    def meaningful_work(self) -> bool:
        """Whether removing the current book would lose work — **the model's answer**.

        Delegated whole to ``book_workspace.has_meaningful_work``. There is no second
        predicate here, and this class never inspects a file list or a configuration
        value to reach its own opinion.
        """
        self._guard.require("meaningful_work")
        current = self._workspace.current if self._workspace is not None else None
        if not isinstance(current, BookJob):
            return False
        return has_meaningful_work(current)

    def set_locked(self, locked: bool) -> None:
        """The ``job_ui.LockGroup`` seam: a run owns these controls while it runs."""
        self._guard.require("set_locked")
        self._locked = bool(locked)
        if self._closed:
            return
        available = self.availability()
        for action, offered in available.items():
            _enable(self.buttons.get(action), offered and not self._locked)
        self._enable_selector(available[self.SELECT] and not self._locked)

    def close(self) -> None:
        """Idempotent, and safe after the root has already been destroyed."""
        self._guard.require("close")
        if self._closed:
            return
        self._closed = True
        for button in self.buttons.values():
            _enable(button, False)
        self._enable_selector(False)
        # A dropped callback cannot be resurrected by a late press.
        self._callbacks = dict.fromkeys(self._callbacks, None)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"BookNavigator(position={self._position}, "
                f"closed={self._closed})")


# --------------------------------------------------------------------------- #
# The Shared Metadata surface (drop section 19, Decision 20B)
# --------------------------------------------------------------------------- #


class _FieldRow:
    """One declared field: its shared control, its per-book control, and two locks.

    This exists because a per-book control can be disabled for **two unrelated
    reasons** — a run owns it (``job_ui.LockGroup`` applying
    ``job_control.LOCK_MATRIX``), or Shared Metadata overrides it (Decision 20B). They
    are recorded separately and combined here, so clearing one never wrongly enables a
    control the other still holds.

    That separation is the whole reason this class exists rather than a fake
    ``JobState``: "a run is using this" and "a shared value overrides this" are
    different facts, and encoding the second as the first would make Retry Failed and
    a populated Shared field indistinguishable to every reader of the lock state.
    """

    __slots__ = ("name", "shared_variable", "book_variable", "shared_entry",
                 "book_entry", "label", "book_label", "job_locked",
                 "shared_disabled")

    def __init__(self, name: str) -> None:
        self.name = name
        self.shared_variable: tk.StringVar | None = None
        self.book_variable: tk.StringVar | None = None
        self.shared_entry: ttk.Entry | None = None
        self.book_entry: ttk.Entry | None = None
        self.label: ttk.Label | None = None
        self.book_label: ttk.Label | None = None
        self.job_locked = False
        self.shared_disabled = False

    @property
    def book_enabled(self) -> bool:
        """Enabled only when **neither** reason holds."""
        return not (self.job_locked or self.shared_disabled)


class SharedMetadataSurface:
    """The workspace-level Shared Metadata region, and the controls it overrides.

    **The vocabulary is the consumer's.** This class hard-codes no field name — no
    title, no author, no narrator, no series. It is handed the fields its consumer
    supports, exactly as Plan 3's importer is handed a ``SupportedTypeCatalog``, and
    it renders those and only those.

    **It edits raw shared values only.** The Phase 4 triple stays apart: the raw
    per-book value lives in ``BookJob.configuration``, the raw shared value lives in
    ``WorkspaceSnapshot.shared``, and the *effective* value is computed by the model on
    demand and stored nowhere. This surface displays and edits the middle one. It never
    writes ``BookJob.configuration``, never computes precedence, and never reports an
    effective value through a callback.

    **The disabled projection is the model's.** Which per-book controls go dead comes
    from ``book_workspace.disabled_fields(shared)`` and from nowhere else. There is no
    ``strip()``, no ``bool(value)`` and no second blankness rule in this file; Phase 4
    remains the authority on what "populated" means.

    **Text fields only, in one of two geometries.** Every declared field is a
    single-line ``ttk.Entry`` on each side. ``layout="columns"`` keeps the prototype's
    side-by-side groups; ``layout="rows"`` stacks Shared above This Book with the
    fields left to right, for a consumer that has more below them than above.
    ``show_header=False`` drops the caption and explanatory line for a consumer that
    captions the region itself; ``wraplength`` lets a long display label fold
    instead of widening its column — one width in pixels for every label, or a
    mapping of field name to width for just those labels — and ``entry_width``
    sets the entries' minimum width in characters so a wide vocabulary still
    fits the minimum window. The consumer places ``frame`` — and may place
    its own non-text controls beside these groups — but nothing tool-specific is
    drawn here.

    Editing delegates. A keystroke in a shared field reports ``(field_name, raw text)``
    to ``on_shared_change``; the caller builds the new ``SharedMetadata``, calls
    ``set_shared_metadata`` and renders the workspace it gets back. The raw text is
    passed through **unchanged** — trailing spaces included — because canonicalising a
    user's value is a model decision this adapter has no business making.
    """

    #: The two geometries. ``"columns"`` is the Phase 8 prototype's: Shared and
    #: This Book side by side, fields stacked — right for a short vocabulary.
    #: ``"rows"`` (focused MP3 continuation, Phase 2) puts Shared above This Book
    #: and runs the fields left to right, which is what a consumer with five
    #: fields and a track list, a chapter editor and a log below them needs at
    #: 920x600. Same contract either way; only the geometry differs.
    LAYOUTS = ("columns", "rows")

    __slots__ = ("_guard", "_theme", "_closed", "_specs", "_rows", "_workspace",
                 "_on_shared_change", "_on_book_change", "_suspended", "_traces",
                 "_layout", "frame", "header", "title_label", "shared_frame",
                 "book_frame")

    def __init__(
        self,
        parent: object,
        fields: Sequence[str],
        *,
        theme: Mapping[str, object] | None = None,
        thread_id: int | None = None,
        title: str = "Shared Metadata",
        shared_title: str = "Shared",
        book_title: str = "This Book",
        layout: str = "columns",
        show_header: bool = True,
        wraplength: int | Mapping[str, int] | None = None,
        entry_width: int | None = None,
        on_shared_change: Callable[[str, str], object] | None = None,
        on_book_change: Callable[[str, str], object] | None = None,
    ) -> None:
        if layout not in self.LAYOUTS:
            raise BookWorkspaceUiError(
                f"layout must be one of {self.LAYOUTS!r}, got {layout!r}")
        self._guard = MainThreadGuard(thread_id)
        self._theme = theme
        self._closed = False
        self._suspended = False
        self._layout = layout
        self._workspace: WorkspaceSnapshot | None = None
        self._on_shared_change = on_shared_change
        self._on_book_change = on_book_change
        self._specs = _field_specs(fields)
        self._rows: dict[str, _FieldRow] = {name: _FieldRow(name)
                                            for name, _label in self._specs}
        self._traces: list[tuple[tk.StringVar, str]] = []

        # Two labelled groups rather than one wide row.
        #
        # The first draft put the field name once, on the far left, with a "Shared"
        # and a "This book" heading above two entries. It was technically
        # unambiguous and visually was not: the right-hand entry looked unlabelled,
        # because knowing what it held meant tracking a row back across the window.
        # So each side is its own group and **every entry carries its own label**,
        # directly above it, in both layouts. The two sides stay visually distinct
        # - the Shared group keeps the approved Shared treatment, the per-book group
        # takes the ordinary one - so "applies everywhere" and "just this book" read
        # before the words do.
        self.frame = ttk.Frame(parent, style=style_name(theme, "card"))

        # A consumer that captions and explains the region itself asks for no
        # second caption: the two groups then start at row 0.
        self.title_label: ttk.Label | None = None
        self.header: ttk.Label | None = None
        groups_row = 0
        if show_header:
            self.title_label = ttk.Label(self.frame, text=title,
                                         style=style_name(theme, "section"))
            self.title_label.grid(row=0, column=0, columnspan=2, sticky="w")
            self.header = ttk.Label(
                self.frame,
                text="Applies to every book. A value here overrides that book's own.",
                style=style_name(theme, "shared_header"))
            self.header.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
            groups_row = 2

        self.shared_frame = ttk.Labelframe(
            self.frame, text=shared_title,
            style=style_name(theme, "shared_labelframe"))
        self.book_frame = ttk.Labelframe(
            self.frame, text=book_title, style=style_name(theme, "labelframe"))
        if layout == "columns":
            self.shared_frame.grid(row=groups_row, column=0, sticky="nsew")
            self.book_frame.grid(row=groups_row, column=1, sticky="nsew",
                                 padx=(12, 0))
            self.frame.columnconfigure(0, weight=1, uniform="metadata")
            self.frame.columnconfigure(1, weight=1, uniform="metadata")
        else:
            self.shared_frame.grid(row=groups_row, column=0, sticky="ew")
            self.book_frame.grid(row=groups_row + 1, column=0, sticky="ew",
                                 pady=(8, 0))
            self.frame.columnconfigure(0, weight=1)

        entry_style = style_name(theme, "entry")
        shared_label_style = style_name(theme, "shared_label")
        book_label_style = style_name(theme, "label")
        # A long display label wraps rather than widening its column: the
        # consumer says how wide a field may be, in pixels — for every field,
        # or per field by name — and a label that needs more folds onto a
        # second line. No font or metric is read.
        if wraplength is None:
            wrap_for = {}
        elif isinstance(wraplength, Mapping):
            wrap_for = {str(name): {"wraplength": int(width)}
                        for name, width in wraplength.items()}
        else:
            wrap_for = {name: {"wraplength": int(wraplength)}
                        for name, _label in self._specs}
        # Likewise the entries' *minimum* width, in characters: they still
        # stretch with their column, but a consumer with many fields across
        # one row can keep the row inside the supported minimum window.
        narrow = {} if entry_width is None else {"width": int(entry_width)}
        for index, (name, display) in enumerate(self._specs):
            row = self._rows[name]
            if layout == "columns":
                # Stacked: label row, entry row, next field beneath.
                label_at = {"row": index * 2, "column": 0,
                            "pady": (0 if index == 0 else 8, 0)}
                entry_at = {"row": index * 2 + 1, "column": 0}
            else:
                # Side by side: every label on row 0, every entry on row 1.
                label_at = {"row": 0, "column": index,
                            "padx": (0 if index == 0 else 8, 0)}
                entry_at = {"row": 1, "column": index,
                            "padx": (0 if index == 0 else 8, 0)}

            wrap = wrap_for.get(name, {})
            row.label = ttk.Label(self.shared_frame, text=display,
                                  style=shared_label_style, **wrap)
            row.label.grid(sticky="w", **label_at)
            row.shared_variable = tk.StringVar(master=self.frame, value="")
            row.shared_entry = ttk.Entry(
                self.shared_frame, textvariable=row.shared_variable,
                style=entry_style, **narrow)
            row.shared_entry.grid(sticky="ew", **entry_at)

            row.book_label = ttk.Label(self.book_frame, text=display,
                                       style=book_label_style, **wrap)
            row.book_label.grid(sticky="w", **label_at)
            row.book_variable = tk.StringVar(master=self.frame, value="")
            row.book_entry = ttk.Entry(
                self.book_frame, textvariable=row.book_variable, style=entry_style,
                **narrow)
            row.book_entry.grid(sticky="ew", **entry_at)

            self._arm(row.shared_variable, name, self._report_shared)
            self._arm(row.book_variable, name, self._report_book)

        # Equal *growth*, not equal width: a ``uniform`` group would size every
        # column to the widest label and push a five-field consumer past the
        # 920px minimum. Each column keeps its own natural width and the slack
        # is shared evenly.
        field_columns = len(self._specs) if layout == "rows" else 1
        for group in (self.shared_frame, self.book_frame):
            for column in range(max(1, field_columns)):
                group.columnconfigure(column, weight=1)

    # -- wiring ------------------------------------------------------------- #

    def _arm(self, variable: tk.StringVar, name: str,
             report: Callable[[str, str], None]) -> None:
        """A trace, not a poll: it fires on a keystroke, never on a timer."""
        token = variable.trace_add(
            "write", lambda *_args, field=name: report(field, _read(variable)))
        self._traces.append((variable, token))

    def _report_shared(self, name: str, raw: str) -> None:
        if self._closed or self._suspended or self._on_shared_change is None:
            return
        # The raw text, exactly as typed. Phase 4 decides what counts as blank.
        self._on_shared_change(name, raw)

    def _report_book(self, name: str, raw: str) -> None:
        if self._closed or self._suspended or self._on_book_change is None:
            return
        self._on_book_change(name, raw)

    # -- pure state, no Tk reached ----------------------------------------- #

    @property
    def guard(self) -> MainThreadGuard:
        return self._guard

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def layout(self) -> str:
        """``"columns"`` (side by side, fields stacked) or ``"rows"`` (stacked
        groups, fields left to right). Fixed at construction."""
        return self._layout

    @property
    def fields(self) -> tuple[str, ...]:
        """The declared field **keys**, in declaration order."""
        return tuple(name for name, _label in self._specs)

    @property
    def labels(self) -> Mapping[str, str]:
        """Key -> the label shown beside *both* of that field's entries."""
        return MappingProxyType({name: label for name, label in self._specs})

    @property
    def workspace(self) -> WorkspaceSnapshot | None:
        return self._workspace

    def book_field_enabled(self, name: str) -> bool:
        """Whether that per-book control is usable — both reasons combined."""
        row = self._row(name)
        return row.book_enabled

    def shared_disabled_fields(self) -> frozenset[str]:
        """The fields the model says are overridden, as last rendered."""
        return frozenset(name for name, row in self._rows.items()
                         if row.shared_disabled)

    def _row(self, name: str) -> _FieldRow:
        row = self._rows.get(name)
        if row is None:
            raise BookWorkspaceUiError(
                f"{name!r} is not one of this consumer declared fields "
                f"{self.fields!r}")
        return row

    # -- Tk-reaching, guarded ---------------------------------------------- #

    def render(self, workspace: WorkspaceSnapshot) -> frozenset[str]:
        """Show the raw shared values and project the model's disabled set.

        Returns the disabled-field set, which is ``disabled_fields(workspace.shared)``
        narrowed to the fields this consumer declared — never recomputed.
        """
        self._guard.require("render")
        if not isinstance(workspace, WorkspaceSnapshot):
            raise BookWorkspaceUiError(
                "workspace must be a book_workspace.WorkspaceSnapshot, got "
                f"{type(workspace).__name__}")
        self._workspace = workspace
        shared = workspace.shared
        if not isinstance(shared, SharedMetadata):
            raise BookWorkspaceUiError(
                "workspace.shared must be a book_workspace.SharedMetadata, got "
                f"{type(shared).__name__}")

        # THE model projection. Not a local blankness test.
        overridden = disabled_fields(shared)
        current = workspace.current
        configuration = current.configuration if isinstance(current, BookJob) else {}

        self._suspended = True          # rendering is not a user edit
        try:
            for name, row in self._rows.items():
                row.shared_disabled = name in overridden
                if self._closed:
                    continue
                _write(row.shared_variable, str(shared.values.get(name, "")))
                _write(row.book_variable, str(configuration.get(name, "")))
                _enable(row.shared_entry, True)
                _enable(row.book_entry, row.book_enabled)
        finally:
            self._suspended = False
        return frozenset(name for name in self.fields if name in overridden)

    def shared_value(self, name: str) -> str:
        """The raw text currently in that shared control."""
        self._guard.require("shared_value")
        return _read(self._row(name).shared_variable)

    def book_value(self, name: str) -> str:
        """The raw text currently in that per-book control."""
        self._guard.require("book_value")
        return _read(self._row(name).book_variable)

    def set_shared_text(self, name: str, raw: str) -> None:
        """Type into a shared control programmatically. Reports like a keystroke."""
        self._guard.require("set_shared_text")
        if self._closed:
            return
        _write(self._row(name).shared_variable, raw)

    def set_book_text(self, name: str, raw: str) -> None:
        self._guard.require("set_book_text")
        if self._closed:
            return
        _write(self._row(name).book_variable, raw)

    def set_locked(self, locked: bool) -> None:
        """The ``job_ui.LockGroup`` seam — the *run* reason, and only that one.

        ``LockGroup.apply(state)`` calls this with ``is_locked(kind, state)``. It sets
        the run reason; the Shared Metadata reason is untouched, which is why
        unlocking after a run does not re-enable a control a populated shared value
        still overrides.
        """
        self._guard.require("set_locked")
        value = bool(locked)
        for row in self._rows.values():
            row.job_locked = value
            if self._closed:
                continue
            _enable(row.shared_entry, not value)
            _enable(row.book_entry, row.book_enabled)

    def register_with(self, group: object, kind: ControlKind | None = None) -> None:
        """Register as a single unit with an existing ``job_ui.LockGroup``.

        A convenience over ``group.register(kind, self)``, kept because the right
        ``ControlKind`` for a metadata field is a fact about this surface rather than
        about every consumer. Plan 6 builds no second lock framework.
        """
        self._guard.require("register_with")
        register = getattr(group, "register", None)
        if not callable(register):
            raise BookWorkspaceUiError(
                "group must be a job_ui.LockGroup, got "
                f"{type(group).__name__}")
        register(ControlKind.PROCESSING_OPTION if kind is None else kind, self)

    def close(self) -> None:
        """Idempotent, and safe after the root has already been destroyed."""
        self._guard.require("close")
        if self._closed:
            return
        self._closed = True
        self._suspended = True
        for variable, token in self._traces:
            try:
                variable.trace_remove("write", token)
            except (tk.TclError, AttributeError, ValueError):
                pass
        self._traces.clear()
        for row in self._rows.values():
            _enable(row.shared_entry, False)
            _enable(row.book_entry, False)
        self._on_shared_change = None
        self._on_book_change = None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"SharedMetadataSurface(fields={self.fields!r}, "
                f"closed={self._closed})")
