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

Phase 3 added Decision 12A: :func:`book_groups`, :func:`books_from_import` and
:func:`replace_workspace_from_import` turn one already-committed
``ImportedFileSnapshot`` into books, one per directory that directly contains
imported files. It is a **projection**: the importer still owns scanning, traversal,
cancellation, commits and occurrence identity, and nothing here reads a disk.

Phase 4 added Decision 20B: :class:`SharedMetadata` holds the consumer's declared
fields and the raw shared values, once, on the workspace; :func:`effective_value`
and :func:`effective_metadata` resolve precedence without storing anything; and
:func:`disabled_fields` projects the controls a consumer must disable. The raw
per-book value is never rewritten, so clearing a shared field restores it exactly.

Phase 5 added Decision 9A for a workspace: :func:`effective_run_options` resolves
what one book's run will consume, and :func:`capture_workspace_run` freezes a whole
workspace into a :class:`BookRunSnapshot` — **one existing Plan 3 ``RunSnapshot``
per eligible book**, composed, never replaced. After capture the run never consults
the workspace again.
That last sentence is why Phase 7 froze the *reason* a book was skipped alongside
the id: telling ``SKIPPED_EMPTY`` from ``SKIPPED_INVALID`` afterwards would have
meant asking a workspace that may have changed since.

Phase 7 added sections 18.1–18.3: :class:`BookDisposition` — the five book-level
answers Plan 3's ``ItemStatus`` deliberately does not hold — plus
:class:`WorkspaceRunResult`, which composes **one existing Plan 3 ``RunResult`` per
attempted book** with Plan 3's own ``JobState`` for the batch, and
:func:`retry_failed_books`, which returns one existing Plan 3 ``RetryRequest`` per
retryable book. It **describes** a retry; it never runs one.

What deliberately does **not** live here
---------------------------------------
No numbering, no ``JobController`` and no Tk. The allocator is
``shared.numbering``'s, a controller is one-per-run and the consumer's, and the Tk
adapter is Phase 8 of the active drop; structural guards prove none has been pulled
forward. Phase 5 **captures** and Phase 7 **composes**; neither runs anything — no
worker, no thread, no ffmpeg, no output, and no number allocated.

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
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from shared.importing import (
    INITIAL_REVISION,
    IdFactory,
    ImportedFile,
    ImportedFileSnapshot,
    ImportOptions,
    Revision,
    SupportedTypeCatalog,
    natural_key,
)
from shared.job_control import (
    JobAction,
    JobState,
    RetryRequest,
    RunResult,
    RunSnapshot,
    TERMINAL_STATES,
    capture_run,
    freeze_options,
    is_available,
)

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
    "book_groups",
    "books_from_import",
    "replace_workspace_from_import",
    "BLANK",
    "SharedMetadataError",
    "SharedMetadata",
    "NO_SHARED_METADATA",
    "is_populated",
    "effective_value",
    "effective_metadata",
    "disabled_fields",
    "set_shared_metadata",
    "RUN_ID_KIND",
    "effective_run_options",
    "BookRunSnapshot",
    "capture_workspace_run",
    "BookDisposition",
    "SKIP_DISPOSITIONS",
    "WorkspaceRunResult",
    "retry_failed_books",
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


class SharedMetadataError(BookContractError):
    """A Shared Metadata value names an undeclared field or a value it cannot hold."""


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
# Decision 20B — Shared Metadata
#
# Three values are kept apart and never conflated: the **raw per-book** value,
# which lives in ``BookJob.configuration`` and is never rewritten; the **raw
# shared** value, stored once on the workspace; and the **effective** value,
# which is computed here and stored nowhere. A fourth stored truth is exactly
# what would let two consumers disagree about what a run is going to write.
# --------------------------------------------------------------------------- #

#: What an unset field resolves to. Blank is a value, not an error: the drop
#: leaves what blank *means* to the consumer that eventually writes a tag.
BLANK = ""


def is_populated(value: object) -> bool:
    """Whether a metadata value counts as set. **The one predicate.**

    Non-blank after stripping surrounding whitespace, exactly as the drop states —
    a field holding only spaces is blank, because a user cannot tell it apart from
    an empty one.

    Precedence and the disabled-control projection both ask *this* function. Two
    predicates would eventually disagree, and the disagreement would show up as a
    control the user can still type into whose value is silently discarded — the
    precise failure Decision 20B exists to prevent.

    Stripping happens **here, for the question only**. Nothing strips the stored
    value: raw stays raw.
    """
    if value is None:
        return False
    if not isinstance(value, str):
        # A non-string per-book value is somebody's deliberate configuration entry,
        # not text this predicate can judge. It is populated because it is there.
        return True
    return bool(value.strip())


@dataclass(frozen=True, slots=True)
class SharedMetadata:
    """The workspace's declared metadata fields and their raw shared values.

    **The vocabulary belongs to the consumer.** There is no universal field list
    here, deliberately: ``shared/metadata.py`` has no public field constants and the
    shared importer has no universal media list — each tool supplies its own
    ``SupportedTypeCatalog``, and Plan 6 follows that precedent. A hard-coded list
    would be wrong for M4B Maker, MP3 Tool and the Metadata Editor simultaneously.

    ``fields`` is the declared vocabulary, in the consumer's own order. ``values``
    holds only raw shared values, only for declared fields, and is deep-frozen
    through the project's one freeze so a caller's dictionary cannot be edited
    afterwards to reach in here.

    An inconsistent state is refused at construction rather than tidied away: a
    value for an undeclared field raises instead of being dropped, so narrowing the
    vocabulary while a raw value still exists for the removed field fails loudly
    rather than silently discarding what the user typed.
    """

    fields: tuple[str, ...] = ()
    values: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.fields, (str, bytes)) or not isinstance(self.fields, Iterable):
            raise SharedMetadataError("fields must be an iterable of field names")
        declared: list[str] = []
        seen: set[str] = set()
        for name in self.fields:
            clean = _require_identifier("field name", name, error=SharedMetadataError)
            if clean in seen:
                raise SharedMetadataError(f"duplicate declared field {clean!r}")
            seen.add(clean)
            declared.append(clean)
        object.__setattr__(self, "fields", tuple(declared))

        if not isinstance(self.values, Mapping):
            raise SharedMetadataError(
                f"values must be a mapping, got {type(self.values).__name__}")
        for name, value in self.values.items():
            if name not in seen:
                raise SharedMetadataError(
                    f"{name!r} is not a declared field; declared: {declared}")
            if not isinstance(value, str):
                # The drop defines populatedness as "non-blank after stripping",
                # which is a statement about text. Refusing anything else keeps this
                # from inventing populatedness for a type nobody has specified.
                raise SharedMetadataError(
                    f"shared value for {name!r} must be a string, got "
                    f"{type(value).__name__}")
        try:
            object.__setattr__(self, "values", freeze_options(dict(self.values)))
        except ValueError as exc:  # pragma: no cover - defensive
            raise SharedMetadataError(f"shared values cannot be frozen: {exc}") from exc

    @classmethod
    def for_fields(cls, fields: Iterable[str]) -> "SharedMetadata":
        """A declared vocabulary with nothing shared yet."""
        return cls(fields=tuple(fields), values={})

    def declares(self, field_name: str) -> bool:
        return _require_identifier(
            "field name", field_name, error=SharedMetadataError) in self.fields

    def raw(self, field_name: str) -> str:
        """The raw shared value for a declared field, or :data:`BLANK`.

        Raw means raw: whatever the user typed, spaces and all. Only
        :func:`is_populated` strips, and only to answer its own question.
        """
        name = self._require_declared(field_name)
        return self.values.get(name, BLANK)

    def populated(self, field_name: str) -> bool:
        """Whether this shared field overrides. Asks :func:`is_populated`."""
        return is_populated(self.raw(field_name))

    @property
    def populated_fields(self) -> tuple[str, ...]:
        """Declared fields carrying a shared value, in declaration order."""
        return tuple(name for name in self.fields if is_populated(self.raw(name)))

    @property
    def is_empty(self) -> bool:
        """True when nothing is shared, whatever is declared."""
        return not self.populated_fields

    def _require_declared(self, field_name: str) -> str:
        name = _require_identifier(
            "field name", field_name, error=SharedMetadataError)
        if name not in self.fields:
            raise SharedMetadataError(
                f"{name!r} is not a declared field; declared: {list(self.fields)}")
        return name


#: The shared metadata a workspace has before a consumer declares anything.
NO_SHARED_METADATA: SharedMetadata = SharedMetadata()


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
    #: Decision 20B. Stored **once**, here, and never copied into a BookJob.
    shared: SharedMetadata = NO_SHARED_METADATA

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

        if not isinstance(self.shared, SharedMetadata):
            raise WorkspaceContractError(
                f"shared must be a SharedMetadata, got {type(self.shared).__name__}")

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
    #: Phase 3. Deliberately its own member rather than reusing ``REPLACE``, which
    #: means "swap one book's value, identified by the id it carries". A whole
    #: workspace rebuilt from an import replaces every book *and* the selection, so
    #: reporting it as ``REPLACE`` would make one member mean two different scopes.
    IMPORT = "import"
    #: Phase 4. Its own member because it changes neither the books nor the
    #: selection, so reporting it as anything else would misdescribe what moved.
    SHARED_METADATA = "shared_metadata"


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
             removed: tuple[BookJob, ...] = (),
             shared: SharedMetadata | None = None) -> BookMutation:
    """A real change: one new frozen value, revision advanced exactly once.

    Shared Metadata is **carried forward** unless an operation explicitly replaces
    it. Because every operation builds its result here, that preservation is a
    property of the one constructor rather than something each of the eight has to
    remember - which is why importing a new set of books cannot silently discard
    what the user shared across them.
    """
    return BookMutation(
        operation=operation,
        changed=True,
        workspace=WorkspaceSnapshot(
            books=books,
            current_book_id=current_book_id,
            revision=workspace.revision.advance(),
            shared=workspace.shared if shared is None else shared,
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


# --------------------------------------------------------------------------- #
# Decision 12A — folder to book construction
#
# This is a **projection**, not an import. The Plan 3 importer still owns
# scanning, compatible-file detection, traversal, cancellation, commits,
# occurrence identity and source identity; everything below reads one already
# committed ``ImportedFileSnapshot`` and touches no disk at all.
# --------------------------------------------------------------------------- #


def book_groups(
    snapshot: ImportedFileSnapshot,
) -> tuple[tuple[Path, tuple[ImportedFile, ...]], ...]:
    """Group an imported list by the directory that **directly contains** each file.

    Decision 12A: every directory holding one or more imported compatible files is
    exactly one book, and two distinct directories are never silently combined.

    **This is not ``importing.planning_groups``, and it must not become it.** That
    function buckets on ``source_root.root_id`` — the folder the *user selected* —
    which is the right key for reproducing a tree under an output root and the wrong
    key for this. Selecting one folder of twelve audiobooks has to yield twelve
    books, not one, and only the file's own parent can say that.

    **The key is the file's own parent path**, taken lexically. ``Path.parent``
    reads no disk, and ``Path`` equality and hashing already apply the running
    system's directory-identity rules — case-folding where the platform folds,
    case-sensitive where it does not — so grouping inherits the correct semantics
    without this module ever naming a platform or asking the filesystem a question.
    ``…/SeriesA/Book1`` and ``…/Archive/Book1`` stay two books because their paths
    differ, not because their basenames were compared.

    **Order.** Groups come back in the order each directory *first appears* in the
    snapshot, so the traversal order the user actually saw survives into the book
    order; the directories are deliberately **not** sorted against each other.
    Within a group, files are natural-ordered by name — ``1, 2, 10``, never
    ``1, 10, 2`` — using the importer's own :func:`~shared.importing.natural_key`
    applied to the same value ``scan_roots`` applies it to.

    That sort is not redundant. ``scan_roots`` already natural-orders a directory's
    files during traversal, but ``validate_direct_files`` deliberately preserves the
    order the user picked files in and sorts nothing, so a snapshot built through
    Add Files arrives unordered. Sorting here makes one guarantee that holds
    whichever entry path produced the snapshot.

    Returns an empty tuple for an empty snapshot: a workspace can never hold zero
    books, but a *grouping* legitimately finds none. Keeping those two facts apart
    is what lets :func:`replace_workspace_from_import` stay honest.
    """
    if not isinstance(snapshot, ImportedFileSnapshot):
        raise BookContractError(
            "snapshot must be an importing.ImportedFileSnapshot, got "
            f"{type(snapshot).__name__}")

    # ``dict`` preserves insertion order, which is exactly the first-appearance
    # order Decision 12A asks for, so no second ordering structure is needed.
    buckets: dict[Path, list[ImportedFile]] = {}
    for entry in snapshot.files:
        buckets.setdefault(entry.path.parent, []).append(entry)

    return tuple(
        (directory, tuple(sorted(entries, key=lambda item: natural_key(item.name))))
        for directory, entries in buckets.items()
    )


def books_from_import(snapshot: ImportedFileSnapshot, *,
                      id_factory: IdFactory) -> tuple[BookJob, ...]:
    """One pristine-configuration :class:`BookJob` per Decision 12A group.

    The imported files are **carried, not rebuilt**: each group's snapshot holds the
    very same immutable ``ImportedFile`` objects, so every occurrence id, source
    root, root-relative path, supported type and source identity the importer
    established survives untouched. Nothing here mints an occurrence id — that is
    the importer's to own, and a second one would make two ids for one file.

    **Each group's snapshot keeps the source snapshot's ``Revision``.** A revision
    stamps *which version of the imported-file manager* a list came from, so
    carrying it forward is what records that these books came from that import.
    Resetting it to ``INITIAL_REVISION`` would be worse than arbitrary: that is the
    revision :data:`NO_FILES` uses to mean *nothing was ever imported*, and reusing
    it here would make a book full of imported files indistinguishable from a
    pristine one.

    Configuration starts empty. Populating it is Phase 4's Shared Metadata work and
    is deliberately not anticipated here.
    """
    groups = book_groups(snapshot)
    # Every group is validated before a single identity is minted, so a snapshot
    # this refuses costs the factory nothing.
    return tuple(
        BookJob(
            book_id=new_book_id(id_factory),
            files=ImportedFileSnapshot(revision=snapshot.revision, files=entries),
        )
        for _directory, entries in groups
    )


def replace_workspace_from_import(workspace: WorkspaceSnapshot,
                                  snapshot: ImportedFileSnapshot, *,
                                  id_factory: IdFactory) -> BookMutation:
    """Replace the whole workspace with the books one import implies. Atomically.

    This is the Plan 6 half of the flow the drop describes: a consumer commits an
    import through the existing ``ImportCoordinator`` and hands the committed
    snapshot here. **Nothing in this module calls the coordinator, starts a scan or
    reads a disk** — it is handed a finished value and projects it.

    Every book is derived and validated *first*, then one new workspace is built, so
    a rejected call leaves the old workspace exactly as it was and the revision moves
    **once for the replacement** rather than once per book.

    An import that finds nothing still has to leave a usable workspace, because a
    workspace is never empty. It therefore ends at exactly one pristine book — and
    when the workspace is *already* a single pristine book that is observably the
    same value, so it is reported as a no-op, spending neither an identity nor a
    revision. That is the disposition already accepted for :func:`remove_book`,
    applied unchanged rather than re-decided.
    """
    space = _require_workspace(workspace)
    # Grouping validates the snapshot, and it mints nothing.
    groups = book_groups(snapshot)

    if not groups:
        if space.count == 1 and not has_meaningful_work(space.books[0]):
            return _unchanged(WorkspaceOperation.IMPORT, space)
        fresh = BookJob(book_id=new_book_id(id_factory))
        return _changed(WorkspaceOperation.IMPORT, space,
                        (fresh,), fresh.book_id, removed=space.books)

    books = tuple(
        BookJob(
            book_id=new_book_id(id_factory),
            files=ImportedFileSnapshot(revision=snapshot.revision, files=entries),
        )
        for _directory, entries in groups
    )
    return _changed(WorkspaceOperation.IMPORT, space,
                    books, books[0].book_id, removed=space.books)


# --------------------------------------------------------------------------- #
# Effective values — computed, never stored
# --------------------------------------------------------------------------- #


def effective_value(shared: SharedMetadata, book: BookJob, field_name: str):
    """The value a run would use for one field of one book. Decision 20B.

    If the shared value is populated it wins — **even when the per-book value is
    also populated**, which is the whole point. Otherwise the book's own raw value
    is used, read straight out of its frozen configuration.

    Nothing is written back. The per-book raw value survives being overridden
    untouched, so clearing the shared field later restores it exactly; that is a
    property of never having destroyed it, not of restoring it afterwards.
    """
    if not isinstance(shared, SharedMetadata):
        raise SharedMetadataError(
            f"shared must be a SharedMetadata, got {type(shared).__name__}")
    if not isinstance(book, BookJob):
        raise BookContractError(f"book must be a BookJob, got {type(book).__name__}")
    name = shared._require_declared(field_name)
    if shared.populated(name):
        return shared.raw(name)
    return book.configuration.get(name, BLANK)


def effective_metadata(shared: SharedMetadata, book: BookJob) -> Mapping[str, object]:
    """Every declared field's effective value for one book, frozen.

    A projection, deliberately returned rather than stored: an ``effective``
    attribute on a book or a workspace would be a second truth that a later edit
    could leave stale, and Phase 5 freezes these values into a run precisely
    *because* they are not frozen here.
    """
    if not isinstance(shared, SharedMetadata):
        raise SharedMetadataError(
            f"shared must be a SharedMetadata, got {type(shared).__name__}")
    if not isinstance(book, BookJob):
        raise BookContractError(f"book must be a BookJob, got {type(book).__name__}")
    return MappingProxyType(
        {name: effective_value(shared, book, name) for name in shared.fields})


def disabled_fields(shared: SharedMetadata) -> frozenset[str]:
    """The fields whose per-book control must be disabled — and nothing else.

    Exactly the declared fields whose shared value is populated. The UI layer
    *renders* this set; it does not compute it and never decides precedence for
    itself, which is what makes the requirement true in behaviour rather than only
    in appearance: the control is disabled by the same fact that makes its value
    ignored, because both ask :func:`is_populated`.
    """
    if not isinstance(shared, SharedMetadata):
        raise SharedMetadataError(
            f"shared must be a SharedMetadata, got {type(shared).__name__}")
    return frozenset(shared.populated_fields)


# --------------------------------------------------------------------------- #
# Changing the workspace's shared metadata
# --------------------------------------------------------------------------- #


def set_shared_metadata(workspace: WorkspaceSnapshot,
                        shared: SharedMetadata) -> BookMutation:
    """Replace the workspace's raw Shared Metadata. Books are untouched.

    Every book comes through as the same object, the selection does not move, and
    only the workspace-level shared value changes — which is what "stored once"
    means in practice. Setting the same value again is a no-op and moves no
    revision.
    """
    space = _require_workspace(workspace)
    if not isinstance(shared, SharedMetadata):
        raise SharedMetadataError(
            f"shared must be a SharedMetadata, got {type(shared).__name__}")
    if shared == space.shared:
        return _unchanged(WorkspaceOperation.SHARED_METADATA, space)
    return _changed(WorkspaceOperation.SHARED_METADATA, space,
                    space.books, space.current_book_id, shared=shared)


# --------------------------------------------------------------------------- #
# Frozen effective values — Decision 9A for a workspace
#
# Phase 5 **captures**; it runs nothing. Each eligible book gets exactly one
# Plan 3 ``RunSnapshot``, built by the existing ``job_control.capture_run``, and
# Plan 6 does nothing but compose them. There is deliberately no second snapshot
# type, no second freeze, no second id scheme and no controller here: a book's
# snapshot is a real Plan 3 snapshot, so ``FailureLog``, ``RunResult`` and
# ``RetryRequest`` stay naturally scoped to it and Phase 7's retry can be
# literally ``RunResult.retry()``.
# --------------------------------------------------------------------------- #

#: The ``kind`` this module asks ``IdFactory`` for when naming a book's run.
#: Distinct from :data:`BOOK_ID_KIND` so a snapshot id can never read as a book id.
RUN_ID_KIND = "run"

#: A consumer's own validity rule, asked once per non-empty book during capture.
#: ``None`` means every structurally valid non-empty book is eligible.
BookValidityCheck = Callable[[BookJob], bool]


def effective_run_options(book: BookJob,
                          shared: SharedMetadata) -> dict[str, Any]:
    """What one book's run will actually consume — Decision 20B, resolved.

    The book's own configuration, with **every declared Shared Metadata field
    overlaid by its effective value**. Non-metadata configuration keys are carried
    through untouched, because a run needs a bitrate or a destination mode just as
    much as it needs a title.

    Neither raw source is modified. The book's ``configuration`` and the
    workspace's ``SharedMetadata`` are values; this builds a *third* mapping from
    them, which is the only place the override is ever "applied". That is what lets
    a shared field be cleared afterwards and the per-book value simply be there
    again — the override was never written down.

    Returned as a plain ``dict`` on purpose: it is handed straight to
    ``capture_run``, whose ``RunSnapshot`` deep-freezes it through the project's one
    ``freeze_options``. Freezing it here as well would be a second freeze doing the
    same job.
    """
    if not isinstance(book, BookJob):
        raise BookContractError(f"book must be a BookJob, got {type(book).__name__}")
    if not isinstance(shared, SharedMetadata):
        raise SharedMetadataError(
            f"shared must be a SharedMetadata, got {type(shared).__name__}")
    options: dict[str, Any] = dict(book.configuration)
    for name in shared.fields:
        options[name] = effective_value(shared, book, name)
    return options


# --------------------------------------------------------------------------- #
# Book dispositions — Phase 7 (section 18.1)
# --------------------------------------------------------------------------- #


class BookDisposition(Enum):
    """What became of one book in one workspace run. Five answers, no more.

    Plan 3's ``ItemStatus`` deliberately has only ``SUCCEEDED`` / ``FAILED`` /
    ``NOT_ATTEMPTED`` and deliberately has no ``SKIPPED``: a *tool* that wants to
    skip an item decides that for itself. A ``BookJob`` is not a Plan 3 item — the
    workspace itself decides a book is not worth attempting, before any worker
    exists — so section 18.1 gives the book level the two skip answers Plan 3 has no
    business holding, and Plan 6 states them here rather than widening ``ItemStatus``.

    There is deliberately **no** ``CANCELLED`` member. Cancellation is a fact about
    the batch, and Plan 3's ``JobState.CANCELLED`` already says it; asking a book
    "were you cancelled?" produces two different answers for the same run depending
    on how far it got, which is exactly what ``FAILED`` and ``NOT_ATTEMPTED`` already
    distinguish.
    """

    #: Attempted, and its own Plan 3 ``RunResult`` reports ``JobState.SUCCEEDED``.
    SUCCEEDED = "succeeded"
    #: Attempted, and its run reached a terminal state that was not success —
    #: including a book cancelled part-way through its own work.
    FAILED = "failed"
    #: Had no imported files at capture, so it received no ``RunSnapshot``. Not a
    #: failure: Decision 13A says an empty job is identified clearly and skipped
    #: safely.
    SKIPPED_EMPTY = "skipped_empty"
    #: The consumer's validity predicate rejected it at capture, so it received no
    #: ``RunSnapshot``. Also not a failure.
    SKIPPED_INVALID = "skipped_invalid"
    #: Eligible, frozen, and never reached — the batch ended first. Emphatically not
    #: a failure, and never offered for retry, the same rule Plan 3 states for items.
    NOT_ATTEMPTED = "not_attempted"


#: The only dispositions a *capture* can record, because capture happens before any
#: work does. Stated once, so the snapshot's invariant and the derivation that reads
#: it cannot disagree about which two those are.
SKIP_DISPOSITIONS = frozenset({
    BookDisposition.SKIPPED_EMPTY,
    BookDisposition.SKIPPED_INVALID,
})


@dataclass(frozen=True, slots=True)
class BookRunSnapshot:
    """One workspace run, frozen: the books it will attempt and the ones it will not.

    ``runs`` is an ordered tuple of ``(book_id, job_control.RunSnapshot)`` pairs, in
    workspace order. Each snapshot is the object ``capture_run`` returned — held by
    identity, not copied — so the book identity and the Plan 3 run identity stay tied
    together without either being encoded inside the other.

    ``skipped`` records the books this run will not attempt, in order, **with the
    reason frozen beside each one**: an ordered tuple of
    ``(book_id, BookDisposition)`` restricted to :data:`SKIP_DISPOSITIONS`. Phase 5
    stored only the ids, because capture eligibility was all it owned; Phase 7 has to
    tell ``SKIPPED_EMPTY`` from ``SKIPPED_INVALID``, and the only moment that
    distinction exists is the moment eligibility is classified. Reconstructing it
    later would mean reading the live workspace, which is precisely what section 16
    forbids — so it is captured here, once.

    ``skipped_book_ids`` therefore remains available and behaves exactly as it did,
    but it is now **derived** from that one collection rather than stored beside it.
    Two stored truths about the same books is one too many.

    ``shared`` is the Shared Metadata that was in force at capture. It is kept so the
    run can report what it resolved against; the effective values themselves are
    already frozen inside each snapshot's ``tool_options``, so **the run never needs
    to resolve precedence again**.

    Deliberately absent: no success counter or next number (Phase 6 — a counter is a
    fact about one attempt's execution, the opposite of a frozen plan), no failure,
    ``RunResult`` or ``RetryRequest`` — those describe what *happened*, and this is
    the plan a retry re-reads — no ``JobController`` (one per run, and the consumer
    owns it), and no output path (Plan 2's, always). The only disposition here is a
    skip reason, because a skip is decided **at capture** rather than by running.
    """

    runs: tuple[tuple[str, RunSnapshot], ...] = ()
    skipped: tuple[tuple[str, BookDisposition], ...] = ()
    shared: SharedMetadata = NO_SHARED_METADATA

    def __post_init__(self) -> None:
        if isinstance(self.runs, (str, bytes)) or not isinstance(self.runs, Iterable):
            raise WorkspaceContractError("runs must be an iterable of pairs")
        pairs: list[tuple[str, RunSnapshot]] = []
        attempted: set[str] = set()
        for entry in self.runs:
            if isinstance(entry, (str, bytes)) or not isinstance(entry, Iterable):
                raise WorkspaceContractError(
                    "each run must be a (book_id, RunSnapshot) pair")
            items = tuple(entry)
            if len(items) != 2:
                raise WorkspaceContractError(
                    f"each run must be a (book_id, RunSnapshot) pair, got {len(items)} values")
            book_id, snapshot = items
            book_id = _require_identifier("book_id", book_id, error=BookIdentityError)
            if not isinstance(snapshot, RunSnapshot):
                raise WorkspaceContractError(
                    "each run must carry a job_control.RunSnapshot, got "
                    f"{type(snapshot).__name__}")
            if book_id in attempted:
                raise BookIdentityError(f"duplicate attempted book_id {book_id!r}")
            attempted.add(book_id)
            pairs.append((book_id, snapshot))
        object.__setattr__(self, "runs", tuple(pairs))

        if isinstance(self.skipped, (str, bytes)) or not isinstance(
                self.skipped, Iterable):
            raise WorkspaceContractError("skipped must be an iterable of pairs")
        skipped: list[tuple[str, BookDisposition]] = []
        seen: set[str] = set()
        for entry in self.skipped:
            if isinstance(entry, (str, bytes)) or not isinstance(entry, Iterable):
                raise WorkspaceContractError(
                    "each skip must be a (book_id, BookDisposition) pair")
            items = tuple(entry)
            if len(items) != 2:
                raise WorkspaceContractError(
                    "each skip must be a (book_id, BookDisposition) pair, got "
                    f"{len(items)} values")
            book_id, why = items
            clean = _require_identifier("book_id", book_id, error=BookIdentityError)
            if why not in SKIP_DISPOSITIONS:
                # SUCCEEDED, FAILED and NOT_ATTEMPTED are facts about running, and a
                # skipped book never ran. Storing one here would be a second, older
                # answer to a question the result layer derives.
                raise WorkspaceContractError(
                    "a skipped book's disposition must be SKIPPED_EMPTY or "
                    f"SKIPPED_INVALID, got {why!r}")
            if clean in seen:
                raise BookIdentityError(f"duplicate skipped book_id {clean!r}")
            if clean in attempted:
                # A book is attempted or skipped. Both would make "what did this run
                # do with book X" have two answers.
                raise BookIdentityError(
                    f"book_id {clean!r} is both attempted and skipped")
            seen.add(clean)
            skipped.append((clean, why))
        object.__setattr__(self, "skipped", tuple(skipped))

        if not isinstance(self.shared, SharedMetadata):
            raise WorkspaceContractError(
                f"shared must be a SharedMetadata, got {type(self.shared).__name__}")

    @property
    def attempted_book_ids(self) -> tuple[str, ...]:
        """The books this run will attempt, in order."""
        return tuple(book_id for book_id, _snapshot in self.runs)

    @property
    def count(self) -> int:
        """How many books this run attempts."""
        return len(self.runs)

    @property
    def skipped_book_ids(self) -> tuple[str, ...]:
        """The books this run will not attempt, in order — **derived**.

        The Phase 5 spelling, unchanged in behaviour. It is a projection of
        :attr:`skipped` rather than a second stored tuple, so the ids and the reasons
        cannot drift apart.
        """
        return tuple(book_id for book_id, _why in self.skipped)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    def skip_reason(self, book_id: str) -> BookDisposition | None:
        """Why that book was not attempted, as frozen at capture, or ``None``.

        ``None`` means "this run did not skip that book" — it may have attempted it,
        or never have heard of it. A lookup; it reads nothing live.
        """
        wanted = _require_identifier("book_id", book_id, error=BookIdentityError)
        for candidate, why in self.skipped:
            if candidate == wanted:
                return why
        return None

    def snapshot_for(self, book_id: str) -> RunSnapshot | None:
        """That book's frozen run, or ``None`` — a lookup, never a capture."""
        wanted = _require_identifier("book_id", book_id, error=BookIdentityError)
        for candidate, snapshot in self.runs:
            if candidate == wanted:
                return snapshot
        return None


def capture_workspace_run(workspace: WorkspaceSnapshot, *,
                          catalog: SupportedTypeCatalog,
                          import_options: ImportOptions,
                          effective_config: Any,
                          id_factory: IdFactory,
                          created_at: float = 0.0,
                          is_valid: BookValidityCheck | None = None
                          ) -> BookRunSnapshot:
    """Freeze one workspace into one run. Decision 9A, per book.

    Synchronous, on the caller's thread, before any worker exists. Every eligible
    book is captured through the **existing** ``job_control.capture_run`` — exactly
    once, with its own snapshot id, its own ``ImportedFileSnapshot`` passed straight
    through, and its effective run options (section 15 resolved by
    :func:`effective_run_options`). Plan 6 constructs no ``RunSnapshot`` itself.

    **Eligibility.** A book with no imported files is skipped: Decision 13A says an
    empty job is identified clearly and skipped safely, and a zero-file run snapshot
    would be a run that cannot do anything. *Validity* beyond that is the consumer's,
    because the shared foundation has no business knowing what makes an M4B or an
    MP3 job valid — so ``is_valid`` is an optional predicate, asked synchronously
    here and **never stored, never frozen and never handed to a worker**. With no
    predicate, every non-empty book is eligible.

    **The reason is frozen with the skip.** This loop is the only place that knows
    *why* a book is not being attempted, so it records ``SKIPPED_EMPTY`` or
    ``SKIPPED_INVALID`` here rather than leaving Phase 7 to re-derive it from a
    workspace that may have changed since. The predicate itself is still not stored —
    only its answer, as a value.

    **Capture reads the workspace and changes nothing.** No revision moves, no
    selection shifts and no ``BookMutation`` is returned, because capturing is an
    observation rather than an edit.

    **Identity consumption.** Everything this function owns is validated, and every
    book's options are computed, *before* the first id is minted. What it cannot
    pre-validate is ``effective_config``, which ``capture_run`` is the authority on —
    so a bad one surfaces from the first call and consumes at most one id. Giving
    ``IdFactory`` a rollback to close that last gap is not this phase's to do, and
    the returned value is all-or-nothing either way: an exception yields no partially
    built :class:`BookRunSnapshot`.
    """
    space = _require_workspace(workspace)
    if not isinstance(id_factory, IdFactory):
        raise BookIdentityError(
            "snapshot ids are minted by an importing.IdFactory, got "
            f"{type(id_factory).__name__}")
    if not isinstance(catalog, SupportedTypeCatalog):
        raise WorkspaceContractError(
            "catalog must be an importing.SupportedTypeCatalog, got "
            f"{type(catalog).__name__}")
    if not isinstance(import_options, ImportOptions):
        raise WorkspaceContractError(
            "import_options must be an importing.ImportOptions, got "
            f"{type(import_options).__name__}")
    if is_valid is not None and not callable(is_valid):
        raise WorkspaceContractError(
            f"is_valid must be callable or None, got {type(is_valid).__name__}")

    # Classify and resolve first, mint second. Nothing below this point can turn a
    # book from eligible to skipped, so no id is spent on a book that is not run.
    eligible: list[tuple[BookJob, dict[str, Any]]] = []
    skipped: list[tuple[str, BookDisposition]] = []
    for book in space.books:
        if book.is_empty:
            # Emptiness is asked first and answered structurally, so an empty book
            # reads as SKIPPED_EMPTY even where the predicate would also have
            # rejected it. "It had nothing to work on" is the truer reason, and it
            # needs no consumer opinion to be true.
            skipped.append((book.book_id, BookDisposition.SKIPPED_EMPTY))
            continue
        if is_valid is not None and not is_valid(book):
            skipped.append((book.book_id, BookDisposition.SKIPPED_INVALID))
            continue
        eligible.append((book, effective_run_options(book, space.shared)))

    runs = tuple(
        (
            book.book_id,
            capture_run(
                snapshot_id=id_factory.next_id(RUN_ID_KIND),
                files=book.files,
                catalog=catalog,
                import_options=import_options,
                effective_config=effective_config,
                tool_options=options,
                created_at=created_at,
            ),
        )
        for book, options in eligible
    )
    return BookRunSnapshot(runs=runs, skipped=tuple(skipped), shared=space.shared)


# --------------------------------------------------------------------------- #
# The workspace result and Retry Failed — Phase 7 (sections 18.2 and 18.3)
#
# Composition, not orchestration. Everything here is derived from two frozen
# facts — the captured run and the per-book results the consumer settled — so a
# summary can never contradict the records it summarises, and a retry can never
# read anything the run did not already have.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class WorkspaceRunResult:
    """One finished workspace run: what the batch did, book by book.

    Three fields, and every question answered from them:

    ``snapshot`` is the exact :class:`BookRunSnapshot` the batch was captured with —
    the same object, so the frozen attempted order, the skip reasons and each book's
    ``RunSnapshot`` are all still the originals.

    ``results`` pairs a ``book_id`` with **that book's own Plan 3
    ``job_control.RunResult``**, settled through the existing ``RunResult.settle``.
    Plan 6 defines no second per-item result, no second failure record and no second
    retry value; it composes Plan 3's by book identity. A book that never reached
    settlement simply has no entry, which is what makes ``NOT_ATTEMPTED`` expressible
    without inventing a placeholder result for it.

    ``state`` is Plan 3's own ``JobState``, terminal, describing the **batch**. There
    is no ``WorkspaceState``: a workspace run is a run, and Plan 3 already says what
    states a finished run may be in.

    **A book failure is not a batch failure** (Decision 28A). A run that lost some
    books but orchestrated correctly is ``COMPLETED_WITH_FAILURES``, exactly as Plan 3
    rules for items — and that is precisely the state in which Retry Failed becomes
    available at all.

    Results are stored in the frozen attempted-book order, whatever order the caller
    supplied them in, so the same facts always compose to the same value.
    """

    snapshot: BookRunSnapshot
    results: tuple[tuple[str, RunResult], ...] = ()
    state: JobState = JobState.SUCCEEDED

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, BookRunSnapshot):
            raise WorkspaceContractError(
                "snapshot must be a BookRunSnapshot, got "
                f"{type(self.snapshot).__name__}")
        if not isinstance(self.state, JobState):
            raise WorkspaceContractError(
                f"state must be a job_control.JobState, got {type(self.state).__name__}")
        if self.state not in TERMINAL_STATES:
            raise WorkspaceContractError(
                f"a workspace result describes a finished run; {self.state.value} is "
                "not a terminal state")

        if isinstance(self.results, (str, bytes)) or not isinstance(
                self.results, Iterable):
            raise WorkspaceContractError("results must be an iterable of pairs")
        entries = (self.results.items() if isinstance(self.results, Mapping)
                   else self.results)

        attempted = self.snapshot.attempted_book_ids
        skipped = set(self.snapshot.skipped_book_ids)
        settled: dict[str, RunResult] = {}
        for entry in entries:
            if isinstance(entry, (str, bytes)) or not isinstance(entry, Iterable):
                raise WorkspaceContractError(
                    "each result must be a (book_id, RunResult) pair")
            items = tuple(entry)
            if len(items) != 2:
                raise WorkspaceContractError(
                    "each result must be a (book_id, RunResult) pair, got "
                    f"{len(items)} values")
            book_id, result = items
            book_id = _require_identifier("book_id", book_id, error=BookIdentityError)
            if not isinstance(result, RunResult):
                raise WorkspaceContractError(
                    "each result must be a job_control.RunResult, got "
                    f"{type(result).__name__}")
            if book_id in settled:
                raise BookIdentityError(f"duplicate result for book_id {book_id!r}")
            if book_id in skipped:
                raise BookIdentityError(
                    f"book_id {book_id!r} was skipped at capture and has no run to "
                    "report a result for")
            expected = self.snapshot.snapshot_for(book_id)
            if expected is None:
                raise BookIdentityError(
                    f"book_id {book_id!r} is not one of this run's attempted books")
            if result.snapshot is not expected:
                # Identity, not equality. An equal-but-distinct snapshot is the
                # signature of a rebuilt run, and a retry built from one would use
                # today's configuration while claiming to re-run the original.
                raise WorkspaceContractError(
                    f"the result for book_id {book_id!r} carries a different "
                    "RunSnapshot object than the one this run captured for it")
            settled[book_id] = result

        # Canonical order is the frozen attempted order, never the caller's.
        object.__setattr__(self, "results", tuple(
            (book_id, settled[book_id])
            for book_id in attempted if book_id in settled))

        missing = tuple(book_id for book_id in attempted if book_id not in settled)
        if (self.state in (JobState.SUCCEEDED, JobState.COMPLETED_WITH_FAILURES)
                and missing):
            raise WorkspaceContractError(
                f"the batch reports {self.state.value} but attempted books "
                f"{missing!r} never settled; a run that finished settled every book "
                "it started")
        if self.state is JobState.SUCCEEDED:
            lost = tuple(book_id for book_id, result in self.results
                         if result.state is not JobState.SUCCEEDED)
            if lost:
                raise WorkspaceContractError(
                    f"the batch reports succeeded but books {lost!r} did not; a run "
                    "that lost a book is completed_with_failures")
        if self.state is JobState.COMPLETED_WITH_FAILURES and not any(
                result.state is not JobState.SUCCEEDED
                for _book_id, result in self.results):
            raise WorkspaceContractError(
                "completed_with_failures needs at least one book that did not "
                "succeed")

    # -- lookups ----------------------------------------------------------- #

    def result_for(self, book_id: str) -> RunResult | None:
        """That book's own Plan 3 result, or ``None`` if it never settled."""
        wanted = _require_identifier("book_id", book_id, error=BookIdentityError)
        for candidate, result in self.results:
            if candidate == wanted:
                return result
        return None

    def disposition_for(self, book_id: str) -> BookDisposition | None:
        """What became of that book. The **one** derivation (section 18.1).

        In order, because the order is the meaning:

        1. **A captured skip** answers for itself, exactly as frozen. An empty or
           invalid book is not "not attempted" — it was ruled out on purpose.
        2. **An attempted book with no result** was never reached: ``NOT_ATTEMPTED``.
           The batch ended first. It is not a failure and is never retried.
        3. **A result reporting ``JobState.SUCCEEDED``**: ``SUCCEEDED``.
        4. **Any other terminal result**: ``FAILED``. A book that was cancelled
           part-way through its own work did not succeed, and calling that anything
           softer would hide a half-finished book from Retry Failed.

        ``None`` means this run never heard of that book.
        """
        wanted = _require_identifier("book_id", book_id, error=BookIdentityError)
        why = self.snapshot.skip_reason(wanted)
        if why is not None:
            return why
        if self.snapshot.snapshot_for(wanted) is None:
            return None
        result = self.result_for(wanted)
        if result is None:
            return BookDisposition.NOT_ATTEMPTED
        if result.state is JobState.SUCCEEDED:
            return BookDisposition.SUCCEEDED
        return BookDisposition.FAILED

    @property
    def dispositions(self) -> tuple[tuple[str, BookDisposition], ...]:
        """Every book this run knew about, attempted first, then skipped.

        Derived on demand from the snapshot and the results, so a disposition can
        never drift out of step with the facts it was built from.
        """
        ordered = [
            (book_id, self.disposition_for(book_id))
            for book_id in self.snapshot.attempted_book_ids
        ]
        ordered.extend(self.snapshot.skipped)
        return tuple(ordered)

    # -- counts, all from the one derivation -------------------------------- #

    @property
    def counts(self) -> Mapping[BookDisposition, int]:
        """Derived, never stored — two counters cannot disagree if there is one."""
        tally: dict[BookDisposition, int] = {why: 0 for why in BookDisposition}
        for _book_id, why in self.dispositions:
            tally[why] += 1
        return MappingProxyType(tally)

    @property
    def succeeded_count(self) -> int:
        return self.counts[BookDisposition.SUCCEEDED]

    @property
    def failed_count(self) -> int:
        return self.counts[BookDisposition.FAILED]

    @property
    def skipped_empty_count(self) -> int:
        return self.counts[BookDisposition.SKIPPED_EMPTY]

    @property
    def skipped_invalid_count(self) -> int:
        return self.counts[BookDisposition.SKIPPED_INVALID]

    @property
    def not_attempted_count(self) -> int:
        return self.counts[BookDisposition.NOT_ATTEMPTED]

    # -- retryability ------------------------------------------------------- #

    @property
    def retryable_book_ids(self) -> tuple[str, ...]:
        """The books Retry Failed would re-run, in frozen attempted order.

        Two conditions, both required: the book's disposition is ``FAILED``, and its
        own Plan 3 result says it has something retryable. The second question is
        never asked twice — ``RunResult.has_retryable`` already derives it from the
        failure log, and re-reading ``FailureRecord.retryable`` here would be a second
        opinion about the same records.

        Order follows ``snapshot.runs``, never the order failures arrived across
        books, never the caller's mapping and never the live workspace.
        """
        return tuple(
            book_id for book_id, result in self.results
            if self.disposition_for(book_id) is BookDisposition.FAILED
            and result.has_retryable
        )

    @property
    def has_retryable(self) -> bool:
        """Whether any book is worth re-running. Not, by itself, whether to offer it."""
        return bool(self.retryable_book_ids)

    @property
    def can_retry_failed(self) -> bool:
        """Whether Retry Failed may be offered — **Plan 3's answer, not a new one**.

        Delegated whole to ``job_control.is_available``. Plan 6 does not restate the
        action/state table: a second copy of it is a second chance to disagree with
        the controller that actually enforces it.
        """
        return is_available(JobAction.RETRY_FAILED, self.state,
                            has_retryable=self.has_retryable)


def retry_failed_books(result: WorkspaceRunResult) -> tuple[RetryRequest, ...]:
    """Retry Failed for a whole workspace — Decision 37A, section 18.3.

    One existing Plan 3 :class:`~shared.job_control.RetryRequest` per retryable book,
    in the same order as :attr:`WorkspaceRunResult.retryable_book_ids`, each built by
    **that book's own ``RunResult.retry()``** against that book's exact original
    ``RunSnapshot`` object. No Plan 6 wrapper, no subclass, no rebuilt snapshot, no
    re-capture.

    **It reads nothing live.** There is no ``WorkspaceSnapshot`` parameter, because
    there is nothing a current workspace could contribute: the files, the effective
    tool options, the occurrence ids and the failure log are all already inside the
    frozen result. Change the books, the shared metadata, the imported lists or the
    whole workspace afterwards and the requests are identical, object for object.

    **It runs nothing.** A ``RetryRequest`` is a value; re-running it is the
    consumer's job, exactly as it is today for the Converter, Cover and TTS panels.
    Nothing here starts a thread, touches a disk, reserves a path, captures a run or
    allocates a number.
    """
    if not isinstance(result, WorkspaceRunResult):
        raise WorkspaceContractError(
            f"result must be a WorkspaceRunResult, got {type(result).__name__}")
    return tuple(
        result.result_for(book_id).retry()
        for book_id in result.retryable_book_ids
    )
