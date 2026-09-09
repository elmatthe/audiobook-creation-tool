"""Immutable vocabulary for the shared multi-book workspace — v0.6.3 Drop 1 (Plan 6), Phase 1.

This module is **contracts only**, in the same sense ``shared.importing`` is: it
defines the frozen value objects a multi-book workspace is built from and the
invariants that make them safe to freeze into a run, and it deliberately implements
none of the behaviour that consumes them.

What lives here
---------------
``BookJob`` — one book: a stable opaque identity, a frozen configuration, and its
own imported-file list. ``WorkspaceSnapshot`` — an ordered collection of those plus
the selected book, as one immutable value. ``new_book_id`` — identity minted through
the existing Plan 3 ``IdFactory``. ``FIELD_ROLES`` / :func:`field_role` — Decision
49A's configuration-versus-imported-input split, stated in exactly one place.

Phase 2 added the workspace controller, as **pure functions over that value**:
:func:`add_book`, :func:`duplicate_book`, :func:`remove_book`, :func:`previous_book`,
:func:`next_book`, :func:`select_book` and :func:`replace_book`, each returning a
frozen :class:`BookMutation`; plus :func:`has_meaningful_work`, Decision 50A's single
predicate. There is no controller *object*: a caller holds one snapshot, calls an
operation, and receives a new one. Nothing here is stateful, and nothing mutates its
argument.

What deliberately does **not** live here
---------------------------------------
No folder-to-book grouping; no Shared Metadata precedence; no effective-value
resolution; no run capture; no numbering; no dispositions; no Retry Failed; and no
Tk. Those are Plan 6 Phases 3–8 of the active drop. In particular **this module never
looks at a file's parent directory** — turning imported files into books is Decision
12A and Phase 3's, and a structural guard proves the mechanism is absent.

No thread, no lock, no queue, no clock, no subprocess, no network, and no filesystem
access of any kind. A ``Path`` reaches this module only as data already inside a
frozen Plan 3 ``ImportedFile``; nothing here reads, writes, plans or resolves one.

Boundaries this module keeps
----------------------------
* It **consumes** ``shared.importing`` for identity (``IdFactory``), ordering stamps
  (``Revision``) and the imported list (``ImportedFileSnapshot``). It creates no
  second identifier scheme, no second revision type and no second file-list type.
  A book never holds a raw ``list[Path]``.
* It **consumes** ``shared.job_control.freeze_options`` as the single deep-freeze.
  There is no second implementation here, and this module neither widens nor
  weakens what that contract accepts — a widget, a variable, a callable, a thread,
  an open file, a mutable dataclass or a reference cycle is refused by the existing
  function, and a book's configuration therefore cannot become a window onto
  changing state.
* It creates **no** output path, plans no destination and reserves no run. Plan 2
  keeps sole ownership of where anything lands; ``shared.output_paths`` is not
  imported, and Decision 51A's filename behaviour belongs to Plan 7.

Everything is a frozen dataclass validated in ``__post_init__``, so an invalid value
cannot be constructed at all — there is no "validate later" path to forget.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from shared.importing import (
    INITIAL_REVISION,
    IdFactory,
    ImportedFileSnapshot,
    Revision,
)
from shared.job_control import freeze_options

__all__ = [
    "BookContractError",
    "BookIdentityError",
    "BookConfigurationError",
    "WorkspaceContractError",
    "BOOK_ID_KIND",
    "new_book_id",
    "NO_FILES",
    "EMPTY_CONFIGURATION",
    "FIELD_ROLES",
    "ROLE_IDENTITY",
    "ROLE_CONFIGURATION",
    "ROLE_INPUTS",
    "field_role",
    "BookJob",
    "WorkspaceSnapshot",
    "has_meaningful_work",
    "WorkspaceOperation",
    "BookMutation",
    "add_book",
    "duplicate_book",
    "remove_book",
    "previous_book",
    "next_book",
    "select_book",
    "replace_book",
]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class BookContractError(ValueError):
    """Raised when a value would violate one of this module's invariants.

    A ``ValueError`` subclass so ordinary ``except ValueError`` handling still
    works, and a named type so a caller can tell a contract violation apart from
    an arbitrary bad argument — the same shape as ``importing.ImportContractError``
    and ``job_control.JobContractError``.
    """


class BookIdentityError(BookContractError):
    """A book identity is missing, malformed, duplicated or unknown."""


class BookConfigurationError(BookContractError):
    """A book's configuration is not something that can be frozen into a value."""


class WorkspaceContractError(BookContractError):
    """A workspace value would break one of its own construction invariants."""


# --------------------------------------------------------------------------- #
# Small pure validators
#
# Each module in this foundation states its own, raising its own error type —
# the pattern ``importing`` and ``job_control`` already follow. All are lexical;
# none looks at the filesystem.
# --------------------------------------------------------------------------- #


#: Characters that must never appear inside an identifier, so a book id can never
#: be mistaken for — or quietly used as — a path fragment.
_PATH_SEPARATORS = tuple(s for s in (os.sep, os.altsep, "/", "\\") if s)


def _require_identifier(field_name: str, value: object, *,
                        error: type[BookContractError] = BookContractError) -> str:
    """Non-blank text with no whitespace and no path separator.

    The separator check is not decoration. Decision 13A's identity must be opaque,
    and an id that can hold ``/`` is an id something downstream will eventually
    join onto a directory. ``importing._require_identifier`` refuses them for the
    same reason; this keeps the two vocabularies saying the same thing.
    """
    if not isinstance(value, str):
        raise error(f"{field_name} must be a string, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise error(f"{field_name} must not be blank")
    if any(character.isspace() for character in text):
        raise error(f"{field_name} must not contain whitespace: {text!r}")
    if any(separator in text for separator in _PATH_SEPARATORS):
        raise error(f"{field_name} must not contain a path separator: {text!r}")
    return text


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #

#: The ``kind`` this module asks ``IdFactory`` for. One word, so a book id reads as
#: ``book-000001`` and can never be mistaken for an occurrence id.
BOOK_ID_KIND = "book"


def new_book_id(id_factory: IdFactory) -> str:
    """Mint one stable, opaque book identity through the existing Plan 3 factory.

    Deliberately a thin call rather than a second generator. A book id is **opaque**:
    it is not an index, not a path, not a display position and not derived from any
    of them, so reordering, navigating, removing a neighbour or running a book leaves
    it untouched. That is what lets a frozen run and a later retry refer to the same
    book without consulting the live list.
    """
    if not isinstance(id_factory, IdFactory):
        raise BookIdentityError(
            "book ids are minted by an importing.IdFactory, got "
            f"{type(id_factory).__name__}")
    return id_factory.next_id(BOOK_ID_KIND)


# --------------------------------------------------------------------------- #
# The pristine values a book starts from
# --------------------------------------------------------------------------- #

#: The imported list a book that has imported nothing owns. Shared safely because
#: ``ImportedFileSnapshot`` is frozen; it is the empty list at ``INITIAL_REVISION``.
NO_FILES: ImportedFileSnapshot = ImportedFileSnapshot(revision=INITIAL_REVISION, files=())

#: The configuration a book that has been configured with nothing owns. Produced by
#: the one deep-freeze, so it is exactly what every other configuration is.
EMPTY_CONFIGURATION: Mapping[str, Any] = freeze_options(None)


# --------------------------------------------------------------------------- #
# Decision 49A — the configuration / imported-input split, stated once
# --------------------------------------------------------------------------- #

ROLE_IDENTITY = "identity"
ROLE_CONFIGURATION = "configuration"
ROLE_INPUTS = "inputs"

#: **Decision 49A lives here and nowhere else.** Every field of :class:`BookJob` has
#: exactly one role, and there is no fourth category:
#:
#: * ``identity`` — minted fresh; never copied from another book.
#: * ``configuration`` — everything the user chooses *about* a book. Copied by value.
#: * ``inputs`` — the imported files, and only those. **Never** copied.
#:
#: Phase 2's Duplicate Book is therefore fully determined by this table rather than
#: by a comment: mint a new identity, carry the configuration, reset the inputs to
#: :data:`NO_FILES`. A test pins this mapping against the dataclass itself, so a
#: field added later cannot quietly escape classification and become a third
#: category that two consumers then disagree about.
FIELD_ROLES: Mapping[str, str] = MappingProxyType({
    "book_id": ROLE_IDENTITY,
    "configuration": ROLE_CONFIGURATION,
    "files": ROLE_INPUTS,
})


def field_role(field_name: str) -> str:
    """The role of one :class:`BookJob` field, or a refusal.

    Refusing an unclassified name is the point: it is what makes "there is no third
    category" a rule the code enforces rather than a sentence in a plan.
    """
    name = _require_identifier("field_name", field_name)
    try:
        return FIELD_ROLES[name]
    except KeyError:
        raise BookContractError(
            f"{name!r} is not a BookJob field; every field is exactly one of "
            f"{sorted(set(FIELD_ROLES.values()))}") from None


# --------------------------------------------------------------------------- #
# One book
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class BookJob:
    """One book job: a stable identity, a frozen configuration, its own inputs.

    The three fields are the three roles of :data:`FIELD_ROLES` and nothing else. A
    book holds no widget, no Tk variable, no output path, no reserved run, no
    planner and no failure — outputs stay Plan 2's and failures stay Plan 3's.

    ``configuration`` is deep-frozen on construction rather than trusted from the
    caller, exactly as ``job_control.RunSnapshot`` freezes ``tool_options``: this is
    the single point at which a live payload can be turned away, so mutating
    whatever was passed in afterwards cannot reach the book.
    """

    book_id: str
    configuration: Mapping[str, Any] = field(default_factory=dict)
    files: ImportedFileSnapshot = NO_FILES

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "book_id",
            _require_identifier("book_id", self.book_id, error=BookIdentityError))
        if not isinstance(self.files, ImportedFileSnapshot):
            raise BookContractError(
                "files must be an importing.ImportedFileSnapshot, got "
                f"{type(self.files).__name__}")
        # Freeze here rather than trusting the caller. ``freeze_options`` raises its
        # own ``OptionFreezeError``; re-raise as this module's configuration error so
        # a caller can catch one Plan 6 type, without weakening what is refused.
        try:
            frozen = freeze_options(self.configuration)
        except ValueError as exc:
            raise BookConfigurationError(
                f"book {self.book_id} configuration cannot be frozen: {exc}") from exc
        object.__setattr__(self, "configuration", frozen)

    @property
    def is_empty(self) -> bool:
        """True when this book has imported nothing.

        Decision 13A's *empty job*: identifiable, and safely skipped by a later
        consumer. Derived from the inputs, never stored, so it cannot disagree
        with them.
        """
        return self.files.is_empty

    @property
    def file_count(self) -> int:
        return self.files.count

    @property
    def configuration_keys(self) -> tuple[str, ...]:
        """The configured keys, sorted — a stable view for a test or a summary."""
        return tuple(sorted(self.configuration))


# --------------------------------------------------------------------------- #
# The workspace, as one immutable value
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    """An ordered collection of books plus the selected one, frozen.

    This is a **value**, not a controller. Phase 2 changes a workspace by building a
    new snapshot and replacing the old one, which is why there is no ``add``,
    ``remove``, ``select``, ``next``, ``previous`` or ``advance`` here and why
    ``revision`` is carried but never moved.

    Selection is by ``book_id``, never by index. An index is a display position and
    changes when a neighbour is removed; the identity does not, which is the whole
    reason Decision 13A's navigation can be safe.
    """

    books: tuple[BookJob, ...]
    current_book_id: str
    revision: Revision = INITIAL_REVISION

    def __post_init__(self) -> None:
        if isinstance(self.books, (str, bytes)) or not isinstance(self.books, Iterable):
            raise WorkspaceContractError("books must be an iterable of BookJob")
        entries = tuple(self.books)
        if not entries:
            # Decision 13A begins with one book job, and ``Book X of Y`` has no
            # coherent reading at Y = 0. A workspace is never empty.
            raise WorkspaceContractError("a workspace holds at least one book")
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, BookJob):
                raise WorkspaceContractError(
                    f"workspace entries must be BookJob, got {type(entry).__name__}")
            if entry.book_id in seen:
                raise BookIdentityError(f"duplicate book_id {entry.book_id!r}")
            seen.add(entry.book_id)
        object.__setattr__(self, "books", entries)

        current = _require_identifier(
            "current_book_id", self.current_book_id, error=BookIdentityError)
        if current not in seen:
            raise BookIdentityError(
                f"current_book_id {current!r} is not one of this workspace's books")
        object.__setattr__(self, "current_book_id", current)

        if not isinstance(self.revision, Revision):
            raise WorkspaceContractError(
                f"revision must be an importing.Revision, got "
                f"{type(self.revision).__name__}")

    @property
    def count(self) -> int:
        """How many books this workspace holds — the *Y* of ``Book X of Y``."""
        return len(self.books)

    @property
    def book_ids(self) -> tuple[str, ...]:
        """The book identities, in workspace order."""
        return tuple(entry.book_id for entry in self.books)

    @property
    def current(self) -> BookJob:
        """The selected book. Always present, because construction proved it is."""
        return self.books[self.book_ids.index(self.current_book_id)]

    @property
    def current_position(self) -> int:
        """The *X* of ``Book X of Y``, 1-based.

        A read-only projection of the selection, not a navigation step: it reports
        where the selected book sits, and moving the selection is Phase 2's.
        """
        return self.book_ids.index(self.current_book_id) + 1

    def book_for(self, book_id: str) -> BookJob | None:
        """The book with this identity, or ``None`` — a lookup, never a selection."""
        wanted = _require_identifier("book_id", book_id, error=BookIdentityError)
        for entry in self.books:
            if entry.book_id == wanted:
                return entry
        return None

# --------------------------------------------------------------------------- #
# Decision 50A — the one meaningful-work predicate
# --------------------------------------------------------------------------- #


def has_meaningful_work(book: BookJob) -> bool:
    """Would removing *book* lose work the user did? Decision 50A, stated once.

    True when the book has any imported file **or** any configuration value; false
    for a pristine book. Remove Book consults only this, and a consumer's own
    confirmation dialog consults only Remove Book — so the question is answered in
    one place instead of three panels each inventing their own idea of "empty".

    On "a default the model supplied": section 13.3 distinguishes a value the user
    set from one the model supplied. **This vocabulary supplies none** — a pristine
    book's configuration is literally empty (:data:`EMPTY_CONFIGURATION`), so the
    minimal rule is the correct one and a defaults-tracking framework would be a
    second truth invented to answer a question nothing is asking yet. If a later
    phase genuinely introduces model-supplied defaults, this predicate is the single
    place that changes.
    """
    if not isinstance(book, BookJob):
        raise BookContractError(
            f"book must be a BookJob, got {type(book).__name__}")
    return not book.files.is_empty or bool(book.configuration)


# --------------------------------------------------------------------------- #
# The workspace operations and their frozen result
# --------------------------------------------------------------------------- #


class WorkspaceOperation(Enum):
    """Which workspace mutation a :class:`BookMutation` describes.

    Deliberately **not** ``importing.ManagerOperation``: that enum names file-list
    mutations (``APPEND``, ``MOVE_UP``, …) and overloading it would make one symbol
    mean two different things depending on who is reading. Two vocabularies, each
    saying exactly what it means.
    """

    ADD = "add"
    DUPLICATE = "duplicate"
    REMOVE = "remove"
    PREVIOUS = "previous"
    NEXT = "next"
    SELECT = "select"
    REPLACE = "replace"


@dataclass(frozen=True, slots=True)
class BookMutation:
    """The frozen outcome of one workspace operation, including the no-ops.

    Shaped after ``importing.MutationResult``, which reports its own no-ops the same
    way: an operation that changed nothing still returns a result, so a caller never
    has to tell "nothing happened" apart from "something went wrong" by inspecting a
    return of ``None``.

    ``removed`` carries the books that are gone, so a consumer can name them without
    having kept the previous workspace. Everything else a caller needs — the
    revision, the selection, the selected book — is **derived** from ``workspace``
    rather than stored beside it, because two copies of one fact can disagree and
    one cannot.
    """

    operation: WorkspaceOperation
    changed: bool
    workspace: WorkspaceSnapshot
    removed: tuple[BookJob, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.operation, WorkspaceOperation):
            raise WorkspaceContractError(
                "operation must be a WorkspaceOperation, got "
                f"{type(self.operation).__name__}")
        if not isinstance(self.changed, bool):
            raise WorkspaceContractError(
                f"changed must be a bool, got {type(self.changed).__name__}")
        if not isinstance(self.workspace, WorkspaceSnapshot):
            raise WorkspaceContractError(
                "workspace must be a WorkspaceSnapshot, got "
                f"{type(self.workspace).__name__}")
        removed = tuple(self.removed)
        for entry in removed:
            if not isinstance(entry, BookJob):
                raise WorkspaceContractError(
                    f"removed must be BookJob, got {type(entry).__name__}")
        object.__setattr__(self, "removed", removed)

    @property
    def revision(self) -> Revision:
        """Derived from the workspace — two counters cannot disagree if there is one."""
        return self.workspace.revision

    @property
    def current_book_id(self) -> str:
        return self.workspace.current_book_id

    @property
    def current(self) -> BookJob:
        return self.workspace.current


# --------------------------------------------------------------------------- #
# Shared helpers for the operations
# --------------------------------------------------------------------------- #


def _require_workspace(workspace: object) -> WorkspaceSnapshot:
    """Validate the argument **before** anything else happens.

    Ordering matters: every operation checks this first, so an operation that is
    going to be rejected has not yet asked the factory for an identity. See
    :func:`add_book` on why that is the best this can do without touching Plan 3.
    """
    if not isinstance(workspace, WorkspaceSnapshot):
        raise WorkspaceContractError(
            f"workspace must be a WorkspaceSnapshot, got {type(workspace).__name__}")
    return workspace


def _unchanged(operation: WorkspaceOperation,
               workspace: WorkspaceSnapshot) -> BookMutation:
    """A no-op: the same value back, and **the revision does not move**."""
    return BookMutation(operation=operation, changed=False, workspace=workspace)


def _changed(operation: WorkspaceOperation,
             workspace: WorkspaceSnapshot,
             books: tuple[BookJob, ...],
             current_book_id: str,
             removed: tuple[BookJob, ...] = ()) -> BookMutation:
    """A real change: one new frozen value, revision advanced exactly once."""
    return BookMutation(
        operation=operation,
        changed=True,
        workspace=WorkspaceSnapshot(
            books=books,
            current_book_id=current_book_id,
            revision=workspace.revision.advance(),
        ),
        removed=removed,
    )


# --------------------------------------------------------------------------- #
# Add and Duplicate (Decisions 13A, 49A)
# --------------------------------------------------------------------------- #


def add_book(workspace: WorkspaceSnapshot, *, id_factory: IdFactory) -> BookMutation:
    """Append a new pristine book and select it. Decision 13A.

    Every existing book comes through untouched — the same objects, in the same
    order — because a workspace is a value and adding to it copies no state.

    **On identity consumption.** The workspace is validated before the factory is
    asked, so a rejected call consumes no id. Once a valid workspace is in hand the
    remaining construction cannot fail: the new book is pristine and the new
    snapshot is the old tuple plus one. Making this transactional in the harder
    sense would mean giving ``IdFactory`` a rollback, and Plan 3's factory is not
    this phase's to change.
    """
    space = _require_workspace(workspace)
    fresh = BookJob(book_id=new_book_id(id_factory))
    return _changed(WorkspaceOperation.ADD, space,
                    space.books + (fresh,), fresh.book_id)


def duplicate_book(workspace: WorkspaceSnapshot, *,
                   id_factory: IdFactory) -> BookMutation:
    """Copy the current book's configuration into a new book, and select it.

    **Decision 49A is not re-stated here; it is obeyed.** The split lives in
    :data:`FIELD_ROLES`, and this function reads it rather than hard-coding which
    fields travel: the *identity* field is minted fresh, the *configuration* field
    is carried, and the *inputs* field is reset to :data:`NO_FILES`. A field added
    to :class:`BookJob` later cannot be silently forgotten here, because
    :func:`field_role` refuses to classify anything the table does not name.

    The copy is inserted immediately after its source, where a user who just asked
    for "another one like this" will look for it.
    """
    space = _require_workspace(workspace)
    source = space.current

    carried = {
        name: getattr(source, name)
        for name in FIELD_ROLES
        if field_role(name) == ROLE_CONFIGURATION
    }
    copy = BookJob(book_id=new_book_id(id_factory), files=NO_FILES, **carried)

    position = space.book_ids.index(source.book_id)
    books = space.books[:position + 1] + (copy,) + space.books[position + 1:]
    return _changed(WorkspaceOperation.DUPLICATE, space, books, copy.book_id)


# --------------------------------------------------------------------------- #
# Remove (Decisions 13A, 50A)
# --------------------------------------------------------------------------- #


def remove_book(workspace: WorkspaceSnapshot, *,
                id_factory: IdFactory) -> BookMutation:
    """Remove the current book. **The workspace is never empty.**

    With more than one book, the removed slot is taken over by whatever falls into
    it — the next book along, or the new last book when the removed one was last.
    That is what a user watching the list expects, and it keeps ``Book X of Y``
    reading sensibly without a special case.

    With only one book, Decision 13A's "begin with one book job" is preserved by
    replacing it with a **fresh pristine book** rather than briefly holding zero:
    there is no zero-book state, not even internally. Meaningful configuration and
    imported files are genuinely discarded, because the user asked to remove them.

    **A judgement call, recorded rather than hidden.** When the only book is already
    pristine there is nothing to lose and nothing would visibly change, so this
    reports a no-op: the value is returned untouched, the revision does not move and
    no identity is consumed. The observable invariant the drop states — *removing
    the last book leaves one pristine book* — holds either way, and treating it as a
    change would spend an id and a revision to replace a book with an identical one.

    This function shows no dialog. Whether a consumer should confirm first is
    :func:`has_meaningful_work`'s answer, asked before calling this.
    """
    space = _require_workspace(workspace)
    victim = space.current

    if space.count == 1:
        if not has_meaningful_work(victim):
            return _unchanged(WorkspaceOperation.REMOVE, space)
        fresh = BookJob(book_id=new_book_id(id_factory))
        return _changed(WorkspaceOperation.REMOVE, space,
                        (fresh,), fresh.book_id, removed=(victim,))

    position = space.book_ids.index(victim.book_id)
    books = space.books[:position] + space.books[position + 1:]
    successor = books[position] if position < len(books) else books[-1]
    return _changed(WorkspaceOperation.REMOVE, space,
                    books, successor.book_id, removed=(victim,))


# --------------------------------------------------------------------------- #
# Navigation and selection
# --------------------------------------------------------------------------- #


def _step(workspace: WorkspaceSnapshot, operation: WorkspaceOperation,
          offset: int) -> BookMutation:
    """One non-wrapping step. At an end the action is simply unavailable."""
    space = _require_workspace(workspace)
    target = space.book_ids.index(space.current_book_id) + offset
    if not 0 <= target < space.count:
        return _unchanged(operation, space)
    return _changed(operation, space, space.books, space.books[target].book_id)


def previous_book(workspace: WorkspaceSnapshot) -> BookMutation:
    """Select the book one to the left. **Navigation does not wrap.**

    No book is reordered and no book's own state is touched — only the selection
    moves, which is why navigating away and back returns exactly what was left
    behind.
    """
    return _step(workspace, WorkspaceOperation.PREVIOUS, -1)


def next_book(workspace: WorkspaceSnapshot) -> BookMutation:
    """Select the book one to the right. **Navigation does not wrap.**"""
    return _step(workspace, WorkspaceOperation.NEXT, 1)


def select_book(workspace: WorkspaceSnapshot, book_id: str) -> BookMutation:
    """Select a book by its stable identity. Never by index.

    An index is a display position and moves when a neighbour is removed; the
    identity does not. An unknown identity is refused outright rather than clamped
    or ignored, because silently selecting *something* is how a user ends up editing
    the wrong book.
    """
    space = _require_workspace(workspace)
    wanted = _require_identifier("book_id", book_id, error=BookIdentityError)
    if wanted not in space.book_ids:
        raise BookIdentityError(
            f"book_id {wanted!r} is not one of this workspace's books")
    if wanted == space.current_book_id:
        return _unchanged(WorkspaceOperation.SELECT, space)
    return _changed(WorkspaceOperation.SELECT, space, space.books, wanted)


# --------------------------------------------------------------------------- #
# Replace — the primitive every later phase edits a book through
# --------------------------------------------------------------------------- #


def replace_book(workspace: WorkspaceSnapshot, book: BookJob) -> BookMutation:
    """Swap one book's value for a new one, in place, keeping order and selection.

    **The replacement identifies its own target.** ``book.book_id`` names the book
    being replaced, so a replacement can never carry a different identity than the
    book it replaces — which is exactly how an ordinary metadata or file edit would
    otherwise turn into a silent remove-and-add, losing the book's place in the
    order and any frozen run that refers to it. An identity that is not in this
    workspace is refused.

    Replacing a book with an equal value is a no-op and moves no revision. Phases
    4–7 edit a book by building the new immutable value and calling this; there is
    deliberately no ``replace_configuration`` or ``replace_files`` beside it,
    because one primitive that swaps a whole immutable value cannot disagree with
    itself about what a partial update means.
    """
    space = _require_workspace(workspace)
    if not isinstance(book, BookJob):
        raise WorkspaceContractError(
            f"book must be a BookJob, got {type(book).__name__}")
    if book.book_id not in space.book_ids:
        raise BookIdentityError(
            f"book_id {book.book_id!r} is not one of this workspace's books; a "
            "replacement carries the identity of the book it replaces")

    position = space.book_ids.index(book.book_id)
    if space.books[position] == book:
        return _unchanged(WorkspaceOperation.REPLACE, space)
    books = space.books[:position] + (book,) + space.books[position + 1:]
    return _changed(WorkspaceOperation.REPLACE, space, books,
                    space.current_book_id)
