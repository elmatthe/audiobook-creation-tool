"""Immutable vocabulary for shared importing — v0.6.0 Drop 3 (Plan 3), Phase 1.

This module is **contracts only**. It defines the frozen value objects the shared
importer is built from and the invariants that make them safe to hand to a worker
thread; it deliberately implements none of the behaviour that consumes them.

What lives here
---------------
``SupportedType`` / ``SupportedTypeCatalog`` / ``ImportOptions`` — what a tool can
import and what the user chose this time. ``ImportRoot`` — one selected folder, or
the single group that individually chosen files belong to. ``ImportedFile`` — one
*occurrence* of a source file in the ordered list. ``ImportProblem`` — anything the
importer refused or could not read, with a user-facing sentence and the technical
detail kept apart. ``ScanRequest`` / ``ScanResult`` — the frozen edges of a folder
scan. ``Revision`` / ``ImportedFileSnapshot`` — the immutable value the imported-file
manager will hand out. ``IdFactory`` — stable, injectable identifiers.

Phase 2 added the read-only traversal core: ``natural_key``,
``classify_root_breadth``, hidden detection, ``capture_identity`` and the synchronous
``scan_roots``. Every value type above is still constructed without touching a disk;
only ``scan_roots``, ``validate_direct_files`` and the helpers they call read the
filesystem, and they only ever *read* it.

Phase 3 added ownership and atomicity: ``validate_direct_files`` (Add Files, which
re-inspects every path a dialog handed back), ``plan_transaction`` (deduplication and
the deliberate-duplicate override), and ``ImportedFileManager`` — the ordered list,
its revision, its selection, and the four mutations the UI will drive. Planning a
transaction changes nothing; only ``commit`` moves the list, and it moves it once or
not at all.

What deliberately does **not** live here
---------------------------------------
No threads, no queues, no polling, no broad-root dialog, no result-count confirmation,
no pause/resume controller, no ETA, and no Tk. Those belong to Phases 4–8 of the
active drop. ``resolve()`` is never called: a link must be *detected*, never followed.

Nothing here deletes, renames, rewrites or touches a source file. Removing an
occurrence removes a *row*; the file it names is not the importer's to alter.

Boundaries this module keeps
----------------------------
* It **consumes** ``shared.config``; it never re-implements configuration loading.
  A ``ScanRequest`` carries one captured ``EffectiveConfig`` so the large-result
  threshold cannot be re-read, and therefore cannot change, mid-scan.
* It **consumes** ``shared.maintenance.is_link`` as the single authority on what a
  link is, rather than growing a second implementation that could drift from the
  one the cleanup coordinator already trusts. Nothing else from that module is used.
* It creates **no** output path and reserves **no** run. ``ImportedFile`` merely
  *retains* the source root and root-relative path that Plan 2's ``plan_flat`` /
  ``plan_mirrored`` / ``plan_multi_root`` will later need.
* ``shared.cancellation`` is untouched and unwrapped. Cancelling an *import* is not
  cancelling a *processing job*: ``scan_roots`` returns a cancelled ``ScanResult``
  and raises nothing.

Everything is a frozen dataclass validated in ``__post_init__``, so an invalid value
cannot be constructed at all — there is no "validate later" path to forget.

Scanning fails **closed**
-------------------------
An entry whose metadata cannot be read is not assumed harmless. Every entry is
re-``lstat``-ed rather than trusted from the ``scandir`` buffer, and any failure
becomes a reported problem and a skip. This matters because
``maintenance.is_link`` answers ``False`` when it cannot read an entry at all — the
right answer for a cleanup target that is about to be re-authorised anyway, but not
a safe basis for descending into something. The readability gate below runs *first*,
so the link question is only ever asked about an entry we could actually read.
"""

from __future__ import annotations

import itertools
import math
import os
import re
import stat as _stat
import sys
import threading
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePath, PureWindowsPath
from types import MappingProxyType

from shared import config as _config
from shared.maintenance import is_link as _is_link

__all__ = [
    "ImportContractError",
    "IdFactory",
    "normalize_extension",
    "ensure_display_safe",
    "natural_key",
    "is_hidden_name",
    "has_hidden_attribute",
    "capture_identity",
    "filesystem_is_case_insensitive",
    "classify_root_breadth",
    "is_broad_root",
    "scan_roots",
    "validate_direct_files",
    "plan_transaction",
    "planning_groups",
    "ProblemCategory",
    "RootBreadth",
    "RootKind",
    "ScanOutcome",
    "SupportedType",
    "SupportedTypeCatalog",
    "ImportOptions",
    "ImportRoot",
    "ImportedFile",
    "ImportProblem",
    "Revision",
    "INITIAL_REVISION",
    "ImportedFileSnapshot",
    "ScanRequest",
    "ScanResult",
    "CommitStatus",
    "ManagerOperation",
    "ImportTransaction",
    "CommitResult",
    "MutationResult",
    "PlanningGroups",
    "ImportedFileManager",
]


class ImportContractError(ValueError):
    """Raised when a value would violate one of this module's invariants.

    A ``ValueError`` subclass so ordinary ``except ValueError`` handling still
    works, and a named type so a caller can tell a contract violation apart from
    an arbitrary bad argument.
    """


# --------------------------------------------------------------------------- #
# Small pure validators
#
# Every one of these is lexical. None of them looks at the filesystem.
# --------------------------------------------------------------------------- #

#: Characters that must never appear inside an extension or an identifier.
_PATH_SEPARATORS = tuple(s for s in (os.sep, os.altsep, "/", "\\") if s)

#: The marker that betrays a raw traceback leaking into user-facing text.
_TRACEBACK_MARKER = "Traceback (most recent call last)"


def _require_text(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise ImportContractError(f"{field} must be a string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        raise ImportContractError(f"{field} must not be blank")
    return stripped


def _require_identifier(field: str, value: object) -> str:
    """A stable, opaque identifier: non-blank text with no separators or spaces."""
    text = _require_text(field, value)
    if any(sep in text for sep in _PATH_SEPARATORS):
        raise ImportContractError(f"{field} must not contain a path separator: {text!r}")
    if any(character.isspace() for character in text):
        raise ImportContractError(f"{field} must not contain whitespace: {text!r}")
    return text


def _require_bool(field: str, value: object) -> bool:
    """Reject truthy stand-ins. ``1`` is not ``True`` in a frozen contract.

    A frozen option that silently accepted ``1``/``"yes"`` would compare unequal to
    the same option spelled properly, and two runs that a user believes are
    identical would produce different snapshots.
    """
    if not isinstance(value, bool):
        raise ImportContractError(f"{field} must be a bool, got {type(value).__name__}")
    return value


def _require_index(field: str, value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ImportContractError(f"{field} must be an int, got {type(value).__name__}")
    if value < minimum:
        raise ImportContractError(f"{field} must be >= {minimum}, got {value}")
    return value


def _require_timestamp(field: str, value: object) -> float:
    """A finite, non-negative reading from an injected clock.

    Rejecting NaN and infinity here rather than at display time keeps every
    downstream duration honest: ``NaN`` compares unequal to itself and would make
    an immutable value silently non-reflexive.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ImportContractError(f"{field} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ImportContractError(f"{field} must be finite, got {value!r}")
    if number < 0:
        raise ImportContractError(f"{field} must not be negative, got {value!r}")
    return number


def ensure_display_safe(field: str, value: object, *, allow_blank: bool = False) -> str:
    """Validate a string that is destined for a user-facing surface.

    Summary text must stay one concise line: no embedded newlines, and never a raw
    traceback. Technical detail is not passed through here — it is kept in its own
    field precisely so diagnostics survive without flooding the Summary view.
    """
    if not isinstance(value, str):
        raise ImportContractError(f"{field} must be a string, got {type(value).__name__}")
    text = value.strip()
    if not text and not allow_blank:
        raise ImportContractError(f"{field} must not be blank")
    if "\n" in text or "\r" in text:
        raise ImportContractError(f"{field} must be a single line: {text!r}")
    if _TRACEBACK_MARKER in text:
        raise ImportContractError(f"{field} must not carry a raw traceback")
    return text


def _require_absolute_path(field: str, value: object) -> Path:
    """Lexically absolute, with no ``..`` component. The filesystem is not consulted.

    ``..`` is refused rather than collapsed: collapsing it lexically is wrong the
    moment a component is a symlink or junction, and this project never follows one.
    """
    if isinstance(value, (str, Path)):
        candidate = Path(value)
    else:
        raise ImportContractError(f"{field} must be a path, got {type(value).__name__}")
    if not candidate.is_absolute():
        raise ImportContractError(f"{field} must be absolute: {str(candidate)!r}")
    if ".." in candidate.parts:
        raise ImportContractError(f"{field} must not contain '..': {str(candidate)!r}")
    return candidate


def _require_relative_path(field: str, value: object) -> PurePath:
    if isinstance(value, (str, PurePath)):
        candidate = PurePath(value)
    else:
        raise ImportContractError(f"{field} must be a path, got {type(value).__name__}")
    if candidate.is_absolute():
        raise ImportContractError(f"{field} must be relative: {str(candidate)!r}")
    if not candidate.parts:
        raise ImportContractError(f"{field} must not be empty")
    if ".." in candidate.parts:
        raise ImportContractError(f"{field} must not contain '..': {str(candidate)!r}")
    if "." in candidate.parts:
        raise ImportContractError(f"{field} must not contain '.': {str(candidate)!r}")
    return candidate


def normalize_extension(raw: object) -> str:
    """``'MP3'`` / ``'.Mp3'`` / ``' .mp3 '`` all become ``'.mp3'``.

    Dot-prefixed, NFC-normalised and lowercased, because extension matching is
    case-insensitive on every platform this project ships to. No MIME probing and
    no filesystem access — this drop matches on the name alone.
    """
    text = _require_text("extension", raw)
    text = unicodedata.normalize("NFC", text)
    if any(sep in text for sep in _PATH_SEPARATORS):
        raise ImportContractError(f"extension must not contain a path separator: {text!r}")
    if any(character.isspace() for character in text):
        raise ImportContractError(f"extension must not contain whitespace: {text!r}")
    for wildcard in ("*", "?"):
        if wildcard in text:
            raise ImportContractError(f"extension must not be a glob pattern: {text!r}")
    if not text.startswith("."):
        text = "." + text
    if text.count(".") != 1 or len(text) < 2:
        raise ImportContractError(f"extension must be a single dotted suffix: {text!r}")
    return text.lower()


# --------------------------------------------------------------------------- #
# Stable identifiers
# --------------------------------------------------------------------------- #


class IdFactory:
    """A thread-safe, monotonic source of stable opaque identifiers.

    Injected rather than global, so a test can predict every identifier it will
    see and two managers can never hand out the same occurrence id by accident.

    Creating one starts **no thread**; the lock only serialises a counter, so this
    stays usable from the single worker Phase 4 will own without becoming a
    concurrency primitive in its own right.
    """

    __slots__ = ("_prefix", "_lock", "_counter")

    def __init__(self, prefix: str = "", *, start: int = 1) -> None:
        if not isinstance(prefix, str):
            raise ImportContractError("prefix must be a string")
        if any(character.isspace() for character in prefix):
            raise ImportContractError(f"prefix must not contain whitespace: {prefix!r}")
        self._prefix = prefix
        self._lock = threading.Lock()
        self._counter = itertools.count(_require_index("start", start, minimum=0))

    def next_id(self, kind: str) -> str:
        """``IdFactory('run7-').next_id('file')`` -> ``'run7-file-000001'``."""
        slug = _require_identifier("kind", kind)
        with self._lock:
            number = next(self._counter)
        return f"{self._prefix}{slug}-{number:06d}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"IdFactory(prefix={self._prefix!r})"


# --------------------------------------------------------------------------- #
# Enumerated vocabulary
# --------------------------------------------------------------------------- #


class ProblemCategory(Enum):
    """Why one entry did not become an imported file.

    Every category is reportable: the importer never drops an entry silently, and
    the Summary view counts these while the Details view carries their technical
    text.
    """

    UNSUPPORTED_TYPE = "unsupported_type"
    DUPLICATE = "duplicate"
    HIDDEN = "hidden"
    LINK = "link"
    UNREADABLE = "unreadable"
    VANISHED = "vanished"
    WRONG_TYPE = "wrong_type"
    CANCELLED = "cancelled"
    INVALID_ROOT = "invalid_root"


class RootKind(Enum):
    """A selected folder mirrors; the individually-chosen group never does.

    Decision 31A: files picked one by one come from many places at once, so they
    have no common tree to reproduce and later route through flat planning. A
    folder root does have one, which is what ``plan_mirrored`` reproduces.
    """

    FOLDER = "folder"
    DIRECT_FILES = "direct_files"


class ScanOutcome(Enum):
    """Only ``COMPLETED`` may ever be committed to the imported-file manager."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# --------------------------------------------------------------------------- #
# Supported types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SupportedType:
    """One user-visible file-type choice, e.g. "MP3 audio" -> ``('.mp3',)``.

    The shared layer holds **no** universal media list. Each adopting tool supplies
    its own catalog later, which is why this type carries a label: it is the text
    beside the checkbox, not an internal category.
    """

    type_id: str
    label: str
    extensions: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "type_id", _require_identifier("type_id", self.type_id))
        object.__setattr__(self, "label", ensure_display_safe("label", self.label))
        if isinstance(self.extensions, (str, bytes)) or not isinstance(self.extensions, Iterable):
            raise ImportContractError("extensions must be an iterable of strings")
        normalised = tuple(dict.fromkeys(normalize_extension(item) for item in self.extensions))
        if not normalised:
            raise ImportContractError(f"supported type {self.type_id!r} needs one extension")
        object.__setattr__(self, "extensions", normalised)

    def matches(self, name: object) -> bool:
        """Pure lexical suffix test against a name or path. Touches no filesystem."""
        suffix = PurePath(os.fspath(name)).suffix
        if not suffix:
            return False
        try:
            return normalize_extension(suffix) in self.extensions
        except ImportContractError:
            return False


@dataclass(frozen=True, slots=True)
class SupportedTypeCatalog:
    """The complete, ordered set of types one tool accepts.

    An extension may belong to exactly one type. Without that rule
    ``ImportedFile.supported_type_id`` would be ambiguous for a file the catalog
    claims twice, and the per-type checkboxes would disagree about what they
    control.
    """

    types: tuple[SupportedType, ...]

    def __post_init__(self) -> None:
        if isinstance(self.types, (str, bytes)) or not isinstance(self.types, Iterable):
            raise ImportContractError("types must be an iterable of SupportedType")
        entries = tuple(self.types)
        if not entries:
            raise ImportContractError("a catalog needs at least one supported type")
        seen_ids: set[str] = set()
        owner_of: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, SupportedType):
                raise ImportContractError(
                    f"catalog entries must be SupportedType, got {type(entry).__name__}")
            if entry.type_id in seen_ids:
                raise ImportContractError(f"duplicate type_id {entry.type_id!r}")
            seen_ids.add(entry.type_id)
            for extension in entry.extensions:
                previous = owner_of.get(extension)
                if previous is not None:
                    raise ImportContractError(
                        f"extension {extension!r} is claimed by both "
                        f"{previous!r} and {entry.type_id!r}")
                owner_of[extension] = entry.type_id
        object.__setattr__(self, "types", entries)

    @property
    def type_ids(self) -> tuple[str, ...]:
        return tuple(entry.type_id for entry in self.types)

    @property
    def extensions(self) -> tuple[str, ...]:
        return tuple(ext for entry in self.types for ext in entry.extensions)

    def default_selection(self) -> frozenset[str]:
        """Every supported type is enabled by default (Decision 16A)."""
        return frozenset(self.type_ids)

    def type_for(self, type_id: str) -> SupportedType:
        for entry in self.types:
            if entry.type_id == type_id:
                return entry
        raise ImportContractError(f"unknown type_id {type_id!r}")

    def type_id_for_name(self, name: object) -> str | None:
        """Which type claims this name, or ``None``. Lexical; no filesystem."""
        for entry in self.types:
            if entry.matches(name):
                return entry.type_id
        return None


@dataclass(frozen=True, slots=True)
class ImportOptions:
    """The user's choices for one import, frozen before the work starts.

    An **empty** selection is deliberately representable. Refusing to construct it
    would push the "you have not ticked anything" message into a constructor and
    out of the UI where the user can act on it; Phase 4 validates and reports it
    without ever starting a worker.
    """

    selected_type_ids: frozenset[str] = frozenset()
    include_hidden_folders: bool = False
    allow_duplicate_files: bool = False
    #: Whether **Add Folder** descends below each selected root.
    #:
    #: Defaults to ``True``, which is today's behaviour: every existing adopter
    #: recurses, and a default of ``False`` would silently shrink their imports.
    #: Declared last so positional construction of the three original fields is
    #: unaffected. Independent of :attr:`include_hidden_folders` — that one
    #: decides *which* children are eligible, this one decides whether any child
    #: is entered at all.
    include_subfolders: bool = True

    def __post_init__(self) -> None:
        raw = self.selected_type_ids
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Iterable):
            raise ImportContractError("selected_type_ids must be an iterable of type ids")
        object.__setattr__(
            self,
            "selected_type_ids",
            frozenset(_require_identifier("selected type id", item) for item in raw),
        )
        object.__setattr__(
            self,
            "include_hidden_folders",
            _require_bool("include_hidden_folders", self.include_hidden_folders),
        )
        object.__setattr__(
            self,
            "allow_duplicate_files",
            _require_bool("allow_duplicate_files", self.allow_duplicate_files),
        )
        object.__setattr__(
            self,
            "include_subfolders",
            _require_bool("include_subfolders", self.include_subfolders),
        )

    @classmethod
    def for_catalog(
        cls,
        catalog: SupportedTypeCatalog,
        *,
        include_hidden_folders: bool = False,
        allow_duplicate_files: bool = False,
        include_subfolders: bool = True,
    ) -> "ImportOptions":
        """The defaults: everything selected, hidden folders out, duplicates off,
        and subfolders **in** — which is what every existing caller already got."""
        if not isinstance(catalog, SupportedTypeCatalog):
            raise ImportContractError("catalog must be a SupportedTypeCatalog")
        return cls(
            selected_type_ids=catalog.default_selection(),
            include_hidden_folders=include_hidden_folders,
            allow_duplicate_files=allow_duplicate_files,
            include_subfolders=include_subfolders,
        )

    @property
    def has_selection(self) -> bool:
        return bool(self.selected_type_ids)


# --------------------------------------------------------------------------- #
# Roots and imported files
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ImportRoot:
    """One selected folder, or the single group individually chosen files belong to.

    ``order`` is the user's own ordering and is never globally re-sorted: root two's
    tree must not migrate into root one's just because it sorts earlier.
    """

    root_id: str
    path: Path | None
    order: int
    kind: RootKind = RootKind.FOLDER

    def __post_init__(self) -> None:
        object.__setattr__(self, "root_id", _require_identifier("root_id", self.root_id))
        object.__setattr__(self, "order", _require_index("order", self.order))
        if not isinstance(self.kind, RootKind):
            raise ImportContractError(f"kind must be a RootKind, got {type(self.kind).__name__}")
        if self.kind is RootKind.FOLDER:
            if self.path is None:
                raise ImportContractError("a folder root needs a path")
            object.__setattr__(self, "path", _require_absolute_path("root path", self.path))
        else:
            if self.path is not None:
                raise ImportContractError(
                    "a direct-files root has no mirroring path; pass path=None")

    @property
    def mirrors(self) -> bool:
        """True when this root has a tree that ``plan_mirrored`` can reproduce."""
        return self.kind is RootKind.FOLDER


@dataclass(frozen=True, slots=True)
class ImportedFile:
    """One *occurrence* of a source file in the ordered imported list.

    Occurrence, not file: the deliberate-duplicate override (Decision 35A) gives a
    second occurrence its own ``occurrence_id`` while it keeps the same
    ``identity``, so a duplicate is visibly the same source rather than being
    disguised as a different one.

    ``identity`` is supplied by the caller. Deriving it — preferring a non-following
    file id from ``lstat`` and falling back to a Unicode-normalised lexical key — is
    Phase 2's job, because it is the first thing here that must touch a filesystem.
    """

    occurrence_id: str
    path: Path
    source_root: ImportRoot
    relative_path: PurePath | None
    supported_type_id: str
    identity: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "occurrence_id", _require_identifier("occurrence_id", self.occurrence_id))
        object.__setattr__(self, "path", _require_absolute_path("path", self.path))
        if not isinstance(self.source_root, ImportRoot):
            raise ImportContractError(
                f"source_root must be an ImportRoot, got {type(self.source_root).__name__}")
        object.__setattr__(
            self,
            "supported_type_id",
            _require_identifier("supported_type_id", self.supported_type_id),
        )
        object.__setattr__(self, "identity", _require_identifier("identity", self.identity))

        if self.source_root.mirrors:
            if self.relative_path is None:
                raise ImportContractError(
                    "a file discovered under a folder root needs a relative_path")
            relative = _require_relative_path("relative_path", self.relative_path)
            if relative.name != self.path.name:
                raise ImportContractError(
                    f"relative_path must end in the file's own name: "
                    f"{str(relative)!r} vs {self.path.name!r}")
            # Lexical consistency only. normpath does not touch the filesystem and
            # both operands are already free of '..', so nothing is being followed.
            joined = os.path.normpath(os.path.join(str(self.source_root.path), str(relative)))
            if os.path.normpath(str(self.path)) != joined:
                raise ImportContractError(
                    f"path {str(self.path)!r} is not {str(relative)!r} under its root "
                    f"{str(self.source_root.path)!r}")
            object.__setattr__(self, "relative_path", relative)
        else:
            if self.relative_path is not None:
                raise ImportContractError(
                    "an individually added file has no mirroring root; "
                    "pass relative_path=None")

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def mirroring_root(self) -> Path | None:
        """The declared root for ``plan_mirrored``, or ``None`` for flat planning."""
        return self.source_root.path if self.source_root.mirrors else None

    @property
    def relative_parent(self) -> PurePath | None:
        """The parent directories to reproduce under the run, if any."""
        if self.relative_path is None:
            return None
        parent = self.relative_path.parent
        return None if str(parent) == "." else parent


@dataclass(frozen=True, slots=True)
class ImportProblem:
    """Something the importer refused, skipped, or could not read.

    ``display_message`` is one concise line for the Summary view;
    ``technical_detail`` carries the exception text, the offending attribute, or the
    reparse-point classification, and is the only one of the two allowed to be long.
    """

    category: ProblemCategory
    display_message: str
    technical_detail: str = ""
    path: Path | None = None
    root: ImportRoot | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.category, ProblemCategory):
            raise ImportContractError(
                f"category must be a ProblemCategory, got {type(self.category).__name__}")
        object.__setattr__(
            self, "display_message", ensure_display_safe("display_message", self.display_message))
        if not isinstance(self.technical_detail, str):
            raise ImportContractError("technical_detail must be a string")
        if self.path is not None:
            object.__setattr__(self, "path", _require_absolute_path("problem path", self.path))
        if self.root is not None and not isinstance(self.root, ImportRoot):
            raise ImportContractError(
                f"root must be an ImportRoot, got {type(self.root).__name__}")


# --------------------------------------------------------------------------- #
# Manager-facing immutable values
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True, order=True)
class Revision:
    """A monotonic version stamp for the imported-file manager.

    A completed scan is committed against the revision it was planned from. If the
    list moved while the worker ran, the revision no longer matches and Phase 4
    recomputes instead of merging against stale state.
    """

    value: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _require_index("revision", self.value))

    def advance(self) -> "Revision":
        return Revision(self.value + 1)


#: The revision an empty manager starts at.
INITIAL_REVISION = Revision(0)


@dataclass(frozen=True, slots=True)
class ImportedFileSnapshot:
    """The ordered imported list, frozen, with the revision it was taken at.

    This is what the manager hands out and what a ``RunSnapshot`` keeps, so a list
    edited after a run starts cannot reach the running job.
    """

    revision: Revision = INITIAL_REVISION
    files: tuple[ImportedFile, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.revision, Revision):
            raise ImportContractError(
                f"revision must be a Revision, got {type(self.revision).__name__}")
        if isinstance(self.files, (str, bytes)) or not isinstance(self.files, Iterable):
            raise ImportContractError("files must be an iterable of ImportedFile")
        entries = tuple(self.files)
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, ImportedFile):
                raise ImportContractError(
                    f"snapshot entries must be ImportedFile, got {type(entry).__name__}")
            if entry.occurrence_id in seen:
                raise ImportContractError(f"duplicate occurrence_id {entry.occurrence_id!r}")
            seen.add(entry.occurrence_id)
        object.__setattr__(self, "files", entries)

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def is_empty(self) -> bool:
        return not self.files

    @property
    def occurrence_ids(self) -> tuple[str, ...]:
        return tuple(entry.occurrence_id for entry in self.files)

    @property
    def identities(self) -> tuple[str, ...]:
        return tuple(entry.identity for entry in self.files)


# --------------------------------------------------------------------------- #
# Scan request and result
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ScanRequest:
    """Everything a folder scan is allowed to know, captured before it starts.

    The ``EffectiveConfig`` is carried rather than looked up so the large-result
    threshold is read exactly once. A preference saved while a scan runs therefore
    cannot change the rules that scan is being judged by.

    Note this type is intentionally **not hashable** in practice: ``EffectiveConfig``
    holds a ``MappingProxyType``. Equality still works and is what tests compare.
    """

    request_id: str
    roots: tuple[ImportRoot, ...]
    catalog: SupportedTypeCatalog
    options: ImportOptions
    effective_config: "_config.EffectiveConfig"
    created_at: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _require_identifier("request_id", self.request_id))
        if isinstance(self.roots, (str, bytes)) or not isinstance(self.roots, Iterable):
            raise ImportContractError("roots must be an iterable of ImportRoot")
        entries = tuple(self.roots)
        if not entries:
            raise ImportContractError("a scan request needs at least one root")
        seen_ids: set[str] = set()
        seen_orders: set[int] = set()
        previous_order = -1
        for entry in entries:
            if not isinstance(entry, ImportRoot):
                raise ImportContractError(
                    f"roots must be ImportRoot, got {type(entry).__name__}")
            if entry.root_id in seen_ids:
                raise ImportContractError(f"duplicate root_id {entry.root_id!r}")
            seen_ids.add(entry.root_id)
            if entry.order in seen_orders:
                raise ImportContractError(f"duplicate root order {entry.order}")
            seen_orders.add(entry.order)
            if entry.order <= previous_order:
                raise ImportContractError(
                    "roots must be supplied in ascending order; the tuple *is* the "
                    "user's order and is never re-sorted")
            previous_order = entry.order
        object.__setattr__(self, "roots", entries)

        if not isinstance(self.catalog, SupportedTypeCatalog):
            raise ImportContractError("catalog must be a SupportedTypeCatalog")
        if not isinstance(self.options, ImportOptions):
            raise ImportContractError("options must be an ImportOptions")
        unknown = set(self.options.selected_type_ids) - set(self.catalog.type_ids)
        if unknown:
            raise ImportContractError(
                f"selected type ids are not in the catalog: {sorted(unknown)}")
        if not isinstance(self.effective_config, _config.EffectiveConfig):
            raise ImportContractError(
                "effective_config must be a captured config.EffectiveConfig; "
                "do not pass a loader, a path, or a live settings mapping")
        object.__setattr__(self, "created_at", _require_timestamp("created_at", self.created_at))

    @property
    def large_result_warning_threshold(self) -> int:
        """Read from the captured snapshot, so it cannot move mid-scan."""
        return self.effective_config.importing.large_result_warning_threshold

    @property
    def folder_roots(self) -> tuple[ImportRoot, ...]:
        return tuple(root for root in self.roots if root.kind is RootKind.FOLDER)

    @property
    def direct_roots(self) -> tuple[ImportRoot, ...]:
        return tuple(root for root in self.roots if root.kind is RootKind.DIRECT_FILES)


@dataclass(frozen=True, slots=True)
class ScanResult:
    """The frozen outcome of one scan.

    A result that did not complete carries **no** files at all. That is structural
    rather than a rule Phase 4 has to remember: a cancelled, failed, or declined
    import cannot partly modify the imported list, because there is nothing in the
    value to commit.
    """

    request_id: str
    outcome: ScanOutcome
    discovered_count: int = 0
    files: tuple[ImportedFile, ...] = ()
    problems: tuple[ImportProblem, ...] = ()
    completed_at: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _require_identifier("request_id", self.request_id))
        if not isinstance(self.outcome, ScanOutcome):
            raise ImportContractError(
                f"outcome must be a ScanOutcome, got {type(self.outcome).__name__}")
        object.__setattr__(
            self, "discovered_count", _require_index("discovered_count", self.discovered_count))

        entries = tuple(self.files)
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, ImportedFile):
                raise ImportContractError(
                    f"files must be ImportedFile, got {type(entry).__name__}")
            if entry.occurrence_id in seen:
                raise ImportContractError(f"duplicate occurrence_id {entry.occurrence_id!r}")
            seen.add(entry.occurrence_id)
        object.__setattr__(self, "files", entries)

        problems = tuple(self.problems)
        for problem in problems:
            if not isinstance(problem, ImportProblem):
                raise ImportContractError(
                    f"problems must be ImportProblem, got {type(problem).__name__}")
        object.__setattr__(self, "problems", problems)

        if self.outcome is not ScanOutcome.COMPLETED and entries:
            raise ImportContractError(
                f"a {self.outcome.value} scan must carry no files; only a completed "
                "scan may be committed")
        if self.outcome is ScanOutcome.FAILED and not problems:
            raise ImportContractError("a failed scan must say why: record a problem")
        object.__setattr__(
            self, "completed_at", _require_timestamp("completed_at", self.completed_at))

    @property
    def is_committable(self) -> bool:
        return self.outcome is ScanOutcome.COMPLETED

    @property
    def candidate_count(self) -> int:
        return len(self.files)

    def problems_of(self, category: ProblemCategory) -> tuple[ImportProblem, ...]:
        return tuple(problem for problem in self.problems if problem.category is category)

    def problem_counts(self) -> Mapping[ProblemCategory, int]:
        """Derived, never stored — two counters cannot disagree if there is one."""
        counts: dict[ProblemCategory, int] = {}
        for problem in self.problems:
            counts[problem.category] = counts.get(problem.category, 0) + 1
        return MappingProxyType(counts)


# --------------------------------------------------------------------------- #
# Natural ordering
#
# Pure and lexical. Sorting never reads a filesystem.
# --------------------------------------------------------------------------- #

#: Splits a name into alternating text and decimal-digit runs. ``\d`` is the Unicode
#: decimal-digit category, so Eastern Arabic numerals order numerically too.
_DIGIT_RUN = re.compile(r"(\d+)")

#: CPython refuses ``int()`` on absurdly long digit strings. A filename can legally
#: carry one, so such a run is compared as text rather than crashing a scan.
_MAX_NUMERIC_RUN = 4300

#: Sort classes. Numbers precede text, and the two are never compared to each other.
_KEY_NUMBER = 0
_KEY_TEXT = 1


def natural_key(name: object) -> tuple:
    """A stable, Unicode-aware, case-insensitive sort key that counts.

    ``1, 2, 10`` rather than ``1, 10, 2``: digit runs compare as integers and text
    runs compare as casefolded text, and the two never meet, so no ``int``/``str``
    comparison can raise.

    Ordering is case-insensitive, but ties break on the NFC-normalised original name,
    so ``A`` and ``a`` still have a deterministic order instead of depending on which
    one the filesystem happened to hand back first.
    """
    text = unicodedata.normalize("NFC", _require_text("name", name))
    folded = text.casefold()
    parts: list[tuple[int, int, str]] = []
    for chunk in _DIGIT_RUN.split(folded):
        if not chunk:
            continue
        if chunk.isdecimal() and len(chunk) <= _MAX_NUMERIC_RUN:
            parts.append((_KEY_NUMBER, int(chunk), ""))
        else:
            parts.append((_KEY_TEXT, 0, chunk))
    return (tuple(parts), text)


# --------------------------------------------------------------------------- #
# Broad-root classification
#
# Purely lexical: a drive root is never *scanned* to discover that it is one.
# --------------------------------------------------------------------------- #


class RootBreadth(Enum):
    """How much of a machine a chosen root covers.

    Phase 4 turns anything other than ``NARROW`` into a warning shown **before** any
    scanning starts. This phase only classifies.
    """

    NARROW = "narrow"
    VOLUME_ROOT = "volume_root"
    UNC_SHARE_ROOT = "unc_share_root"
    USER_HOME = "user_home"


def _pure(path: object) -> PurePath:
    return path if isinstance(path, PurePath) else PurePath(os.fspath(path))


def _lexical_key(path: PurePath) -> tuple[str, ...]:
    """Comparison parts, casefolded only where the path *flavour* is case-blind.

    Purely lexical, because root classification never touches the filesystem. Source
    identity has a different question to answer and uses :func:`_identity_key`, which
    asks the volume itself.
    """
    parts = tuple(unicodedata.normalize("NFC", part) for part in path.parts)
    if isinstance(path, PureWindowsPath):
        return tuple(part.casefold() for part in parts)
    return parts


def classify_root_breadth(path: object, *, home: object | None = None) -> RootBreadth:
    """Classify a candidate root without touching the filesystem.

    *home* is injected rather than discovered, so a test never depends on the machine
    it runs on and a scan never has to ask the operating system who is logged in.

    Pass a ``PureWindowsPath`` or ``PurePosixPath`` to classify for that flavour; a
    plain string is read with this platform's rules.
    """
    candidate = _pure(path)
    if home is not None and _lexical_key(candidate) == _lexical_key(_pure(home)):
        return RootBreadth.USER_HOME

    # A root with a single part *is* that part: ``C:\``, ``/`` or ``\\server\share\``.
    if len(candidate.parts) == 1 and candidate.anchor:
        drive = candidate.drive
        if drive.startswith("\\\\") or drive.startswith("//"):
            return RootBreadth.UNC_SHARE_ROOT
        return RootBreadth.VOLUME_ROOT
    return RootBreadth.NARROW


def is_broad_root(path: object, *, home: object | None = None) -> bool:
    """Whether choosing this root deserves a warning before anything is scanned."""
    return classify_root_breadth(path, home=home) is not RootBreadth.NARROW


# --------------------------------------------------------------------------- #
# Hidden detection
# --------------------------------------------------------------------------- #

#: Answers "is this hidden according to the platform?" for one path. A parameter so a
#: test can exercise Windows behaviour on POSIX and vice versa.
HiddenProbe = Callable[[Path, object], bool]


def is_hidden_name(name: object) -> bool:
    """The portable rule: a dot-prefixed name, which is how macOS and Linux hide."""
    text = str(name)
    if text in (".", ".."):
        return False
    return text.startswith(".")


def has_hidden_attribute(path: Path, stat_result: object = None) -> bool:
    """The Windows rule: ``FILE_ATTRIBUTE_HIDDEN``, read without following links.

    Returns ``False`` wherever that attribute does not exist, so a caller may always
    combine it with :func:`is_hidden_name` and get the right answer per platform.
    """
    flag = getattr(_stat, "FILE_ATTRIBUTE_HIDDEN", None)
    if flag is None:
        return False
    try:
        result = os.lstat(path) if stat_result is None else stat_result
        attributes = result.st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attributes & flag)


def _is_hidden(path: Path, stat_result: object, probe: HiddenProbe | None) -> bool:
    if is_hidden_name(path.name):
        return True
    check = has_hidden_attribute if probe is None else probe
    return bool(check(path, stat_result))


# --------------------------------------------------------------------------- #
# Source identity
# --------------------------------------------------------------------------- #

#: Darwin's ``_PC_CASE_SENSITIVE`` from ``<unistd.h>``. Python does not publish it in
#: ``os.pathconf_names``, and the number means something else entirely on Linux, so it
#: is only ever passed on Darwin. Everywhere else the flip probe below answers instead.
_DARWIN_PC_CASE_SENSITIVE = 11

#: Case-blindness is a property of the *volume*, not of one file, so one answer per
#: device serves every path on it. ``st_dev`` is the stable identity we already read
#: for :func:`capture_identity`, and it costs no extra syscall to key on.
_CASE_BLIND_BY_DEVICE: dict[int, bool] = {}


def _nearest_existing_ancestor(path: Path) -> Path | None:
    """The closest component of *path* that exists, without following links.

    Read-only, and it never creates a probe file in a user's source folder: the
    question "does this volume fold case?" is answered from what is already there.
    """
    current = path
    while True:
        try:
            os.lstat(current)
            return current
        except OSError:
            pass
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _flipped_name_is_the_same_file(directory: Path) -> bool:
    """Whether *directory* is reachable through a case-flipped spelling of its name.

    The portable fallback for platforms that will not answer ``pathconf``: an existing
    name is re-spelled and looked up. Nothing is created, nothing is written, and a
    match only counts when the two spellings report the same ``(st_dev, st_ino)``.
    """
    name = directory.name
    flipped = name.upper() if name != name.upper() else name.lower()
    if not name or flipped == name:
        return False
    try:
        original = os.lstat(directory)
        twin = os.lstat(directory.parent / flipped)
    except OSError:
        return False
    return (original.st_dev, original.st_ino) == (twin.st_dev, twin.st_ino)


def filesystem_is_case_insensitive(path: object) -> bool:
    """Whether the volume holding *path* treats two case-only spellings as one file.

    This is a **filesystem** question, not a platform one. The default macOS APFS
    volume is case-insensitive while a case-sensitive APFS volume on the same machine
    is not, so ``sys.platform`` cannot answer it and is never asked to.

    Answered read-only, from the nearest component that already exists: the volume is
    asked directly where the platform can answer, and otherwise an existing name is
    looked up in a flipped spelling. An undeterminable volume answers ``False`` — the
    conservative side, which keeps two spellings apart rather than merging two files
    that might genuinely be different.
    """
    if os.name == "nt":
        # The Win32 path layer is case-insensitive regardless of the underlying
        # volume, which is what ``PureWindowsPath`` already encodes.
        return True
    ancestor = _nearest_existing_ancestor(Path(os.path.abspath(os.fspath(path))))
    if ancestor is None:
        return False
    try:
        device = os.lstat(ancestor).st_dev
    except OSError:
        device = None
    if device is not None and device in _CASE_BLIND_BY_DEVICE:
        return _CASE_BLIND_BY_DEVICE[device]
    answer = _probe_case_blindness(ancestor)
    if device is not None:
        _CASE_BLIND_BY_DEVICE[device] = answer
    return answer


def _probe_case_blindness(existing: Path) -> bool:
    if sys.platform == "darwin":
        try:
            return not bool(os.pathconf(str(existing), _DARWIN_PC_CASE_SENSITIVE))
        except (OSError, ValueError, AttributeError):
            pass
    name = os.pathconf_names.get("PC_CASE_SENSITIVE")
    if name is not None:
        try:
            return not bool(os.pathconf(str(existing), name))
        except (OSError, ValueError, AttributeError):
            pass
    probe = existing
    while probe.name:
        if _flipped_name_is_the_same_file(probe):
            return True
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    return False


def _identity_key(absolute: Path) -> tuple[str, ...]:
    """The lexical identity parts, casefolded where the *filesystem* is case-blind."""
    pure = PurePath(absolute)
    parts = tuple(unicodedata.normalize("NFC", part) for part in pure.parts)
    if isinstance(pure, PureWindowsPath) or filesystem_is_case_insensitive(absolute):
        return tuple(part.casefold() for part in parts)
    return parts


def capture_identity(path: Path, stat_result: object = None) -> str:
    """A key for "is this the same source file?", captured without following links.

    Prefers the platform's own file identity — ``(st_dev, st_ino)``, which NTFS, APFS
    and ext4 all populate — so one physical file reached through two spellings, or
    through a hard link, is recognised as one source.

    Falls back to a lexical absolute-path key when the platform reports no usable
    identity: NFC-normalised, and casefolded only where the filesystem is case-blind
    (:func:`filesystem_is_case_insensitive`, which asks the volume rather than the
    platform), so a case-sensitive macOS volume keeps two genuinely different files
    apart while the default case-insensitive one folds two spellings of one file.

    ``resolve()`` is never used — following a link to decide identity is exactly what
    this drop refuses to do. Phase 3 owns what to *do* with two matching identities.
    """
    absolute = Path(os.path.abspath(str(path)))
    device = inode = 0
    try:
        result = os.lstat(absolute) if stat_result is None else stat_result
        device, inode = result.st_dev, result.st_ino
    except OSError:
        pass
    if device and inode:
        return f"file:{device}:{inode}"
    return "path:" + "\x00".join(_identity_key(absolute))


# --------------------------------------------------------------------------- #
# The traversal core
# --------------------------------------------------------------------------- #

#: Reports whether the *import* was cancelled. Never the processing job's controller:
#: Cancel Import stops a scan and nothing else.
CancelCheck = Callable[[], bool]

#: Receives the running count of compatible, non-link candidates. Called synchronously
#: on the caller's own thread — this phase owns no worker.
CountCallback = Callable[[int], None]


def _problem(
    category: ProblemCategory,
    message: str,
    detail: str = "",
    path: Path | None = None,
    root: object = None,
) -> ImportProblem:
    return ImportProblem(
        category=category,
        display_message=message,
        technical_detail=detail,
        path=path,
        root=root,
    )


def _extension_map(
    catalog: "SupportedTypeCatalog", options: "ImportOptions") -> Mapping[str, str]:
    """extension -> type id, for the types the user actually ticked.

    Shared by folder traversal and Add Files so one selection of file types cannot
    mean two different things depending on how the file was chosen.
    """
    chosen = options.selected_type_ids
    mapping: dict[str, str] = {}
    for entry in catalog.types:
        if entry.type_id in chosen:
            for extension in entry.extensions:
                mapping[extension] = entry.type_id
    return MappingProxyType(mapping)


def _selected_extensions(request: "ScanRequest") -> Mapping[str, str]:
    return _extension_map(request.catalog, request.options)


def _extension_of(name: str) -> str:
    suffix = PurePath(name).suffix
    if not suffix:
        return ""
    try:
        return normalize_extension(suffix)
    except ImportContractError:
        return ""


def _label(path: Path) -> str:
    return path.name or str(path)


def _classify_root(root: ImportRoot, problems: list) -> object:
    """Validate one folder root. Returns its ``lstat`` when it is safe to enumerate.

    Order matters. Existence and readability are settled **before** the link question,
    because ``maintenance.is_link`` answers ``False`` for something it could not read,
    and that answer must never be mistaken for "safe to walk into".
    """
    path = root.path
    try:
        result = os.lstat(path)
    except FileNotFoundError:
        problems.append(_problem(
            ProblemCategory.INVALID_ROOT,
            f"The folder {_label(path)} could not be found and was skipped.",
            f"FileNotFoundError: {path}", path=path, root=root))
        return None
    except OSError as exc:
        problems.append(_problem(
            ProblemCategory.INVALID_ROOT,
            f"The folder {_label(path)} could not be read and was skipped.",
            f"{type(exc).__name__}: {exc}", path=path, root=root))
        return None

    if _is_link(path):
        problems.append(_problem(
            ProblemCategory.INVALID_ROOT,
            f"The folder {_label(path)} is a shortcut or link and was not followed.",
            "refused by maintenance.is_link: symlink, junction or other reparse point",
            path=path, root=root))
        return None

    if not _stat.S_ISDIR(result.st_mode):
        problems.append(_problem(
            ProblemCategory.INVALID_ROOT,
            f"{_label(path)} is not a folder and was skipped.",
            f"st_mode={result.st_mode:#o} is not a directory", path=path, root=root))
        return None
    return result


def _list_directory(directory: Path, root: ImportRoot, problems: list) -> object:
    """One ``scandir`` pass. ``None`` means the directory could not be enumerated."""
    try:
        with os.scandir(directory) as scanner:
            return list(scanner)
    except OSError as exc:
        problems.append(_problem(
            ProblemCategory.UNREADABLE,
            f"The folder {_label(directory)} could not be read and was skipped.",
            f"{type(exc).__name__}: {exc}", path=directory, root=root))
        return None


def scan_roots(
    request: ScanRequest,
    *,
    id_factory: IdFactory | None = None,
    cancel_check: CancelCheck | None = None,
    on_count: CountCallback | None = None,
    hidden_probe: HiddenProbe | None = None,
    completed_at: float = 0.0,
) -> ScanResult:
    """Walk the request's folder roots and return one frozen, read-only result.

    Synchronous and side-effect-free: it reads directory metadata and nothing else.
    No thread, no queue, no Tk object, no manager, no transaction, no output run.
    ``cancel_check`` and ``on_count`` run on the caller's own thread.

    Per root, in the order the user supplied — never globally re-sorted, because root
    two's tree must not migrate into root one's just because it sorts earlier:

    1. validate the root without following it;
    2. enumerate one directory;
    3. classify each entry from a fresh ``lstat``, refusing links and anything that
       cannot be read;
    4. emit that directory's compatible files first, in natural order;
    5. then descend into its eligible child directories, in the same order —
       unless ``options.include_subfolders`` is ``False``, in which case step 5 is
       withheld and each root contributes only the compatible files it directly
       contains. Everything else about the walk is identical either way.

    ``DIRECT_FILES`` roots are ignored here: they name no tree to walk, and validating
    individually chosen files is Phase 3's ``Add Files``.

    Cancellation is checked before each root, while classifying every entry, before
    each descent, and before the result is published. A cancelled scan returns
    ``ScanOutcome.CANCELLED`` carrying **no** files, so nothing partial can be
    committed, and stops calling ``on_count``. It raises nothing: cancelling an import
    is not cancelling a processing job.
    """
    if not isinstance(request, ScanRequest):
        raise ImportContractError("scan_roots needs a ScanRequest")
    factory = IdFactory() if id_factory is None else id_factory
    cancelled = cancel_check if cancel_check is not None else (lambda: False)

    extensions = _selected_extensions(request)
    # Read once from the frozen request. Deliberately not re-read per directory and
    # never read from a widget: the choice belongs to the import that was started.
    descend = request.options.include_subfolders
    files: list[ImportedFile] = []
    problems: list[ImportProblem] = []
    discovered = 0

    def publish(outcome: ScanOutcome) -> ScanResult:
        return ScanResult(
            request_id=request.request_id,
            outcome=outcome,
            discovered_count=discovered,
            files=tuple(files) if outcome is ScanOutcome.COMPLETED else (),
            problems=tuple(problems),
            completed_at=completed_at,
        )

    def cancel() -> ScanResult:
        problems.append(_problem(
            ProblemCategory.CANCELLED,
            "The import was cancelled and nothing was added.",
            "cancellation acknowledged at a scan checkpoint"))
        return publish(ScanOutcome.CANCELLED)

    for root in request.folder_roots:
        # Checkpoint: before root enumeration.
        if cancelled():
            return cancel()

        if _classify_root(root, problems) is None:
            continue

        # An explicit stack rather than recursion: a deep tree must not depend on
        # Python's recursion limit, and this order is easier to prove.
        stack: list[tuple[Path, tuple[str, ...]]] = [(root.path, ())]
        while stack:
            directory, relative_parts = stack.pop()
            entries = _list_directory(directory, root, problems)
            if entries is None:
                continue

            candidates: list = []
            children: list = []

            for entry in entries:
                # Checkpoint: during entry classification.
                if cancelled():
                    return cancel()

                entry_path = Path(entry.path)

                # Read the entry freshly rather than trusting the scandir buffer, so
                # something that changed shape since enumeration is caught here.
                try:
                    entry_stat = os.lstat(entry_path)
                except FileNotFoundError:
                    problems.append(_problem(
                        ProblemCategory.VANISHED,
                        f"{entry.name} disappeared while the folder was being read.",
                        f"FileNotFoundError: {entry_path}", path=entry_path, root=root))
                    continue
                except OSError as exc:
                    problems.append(_problem(
                        ProblemCategory.UNREADABLE,
                        f"{entry.name} could not be read and was skipped.",
                        f"{type(exc).__name__}: {exc}", path=entry_path, root=root))
                    continue

                if _is_link(entry_path):
                    problems.append(_problem(
                        ProblemCategory.LINK,
                        f"{entry.name} is a shortcut or link and was not followed.",
                        "refused by maintenance.is_link: symlink, junction or other "
                        "reparse point", path=entry_path, root=root))
                    continue

                mode = entry_stat.st_mode
                if _stat.S_ISDIR(mode):
                    if (_is_hidden(entry_path, entry_stat, hidden_probe)
                            and not request.options.include_hidden_folders):
                        problems.append(_problem(
                            ProblemCategory.HIDDEN,
                            f"The hidden folder {entry.name} was skipped.",
                            "include_hidden_folders is off for this import",
                            path=entry_path, root=root))
                        continue
                    children.append((natural_key(entry.name), entry.name, entry_path))
                    continue

                if not _stat.S_ISREG(mode):
                    problems.append(_problem(
                        ProblemCategory.WRONG_TYPE,
                        f"{entry.name} is not an ordinary file and was skipped.",
                        f"st_mode={mode:#o} is neither a regular file nor a directory",
                        path=entry_path, root=root))
                    continue

                # A hidden file found by *walking* is skipped; one the user picked
                # deliberately is Add Files' business, not this traversal's.
                if _is_hidden(entry_path, entry_stat, hidden_probe):
                    problems.append(_problem(
                        ProblemCategory.HIDDEN,
                        f"The hidden file {entry.name} was skipped.",
                        "hidden files are not collected by a folder scan",
                        path=entry_path, root=root))
                    continue

                type_id = extensions.get(_extension_of(entry.name))
                if type_id is None:
                    problems.append(_problem(
                        ProblemCategory.UNSUPPORTED_TYPE,
                        f"{entry.name} is not a selected file type and was skipped.",
                        "no selected supported type claims this extension",
                        path=entry_path, root=root))
                    continue

                candidates.append(
                    (natural_key(entry.name), entry.name, entry_path, entry_stat, type_id))

            # Compatible direct files first, in natural order.
            candidates.sort(key=lambda item: item[0])
            for _key, name, entry_path, entry_stat, type_id in candidates:
                # Checkpoint: while emitting. A directory holding thousands of
                # matches must not keep reporting a count after the user has asked
                # the import to stop.
                if cancelled():
                    return cancel()
                files.append(ImportedFile(
                    occurrence_id=factory.next_id("occ"),
                    path=entry_path,
                    source_root=root,
                    relative_path=PurePath(*relative_parts, name),
                    supported_type_id=type_id,
                    identity=capture_identity(entry_path, entry_stat),
                ))
                discovered += 1
                if on_count is not None:
                    on_count(discovered)

            # Then the child directories, same order, depth first. Reversed onto the
            # stack so the first child is popped first.
            #
            # This push is the **one** descent point in the scanner, which is why
            # ``include_subfolders`` gates exactly it and nothing else. Shallow and
            # recursive imports therefore share every line above — the same
            # enumeration, the same fresh ``lstat``, the same classification, the
            # same natural ordering, the same problem reporting — and differ only in
            # whether an eligible child is queued for later. A second scanner would
            # have to re-earn all of that, and would drift.
            #
            # The loop and its checkpoint stay in place when shallow so cancellation
            # keeps its existing cadence; only the ``stack.append`` is withheld.
            children.sort(key=lambda item: item[0])
            for _key, name, child_path in reversed(children):
                # Checkpoint: before each recursive descent.
                if cancelled():
                    return cancel()
                if descend:
                    stack.append((child_path, relative_parts + (name,)))

    # Checkpoint: before result publication.
    if cancelled():
        return cancel()
    return publish(ScanOutcome.COMPLETED)


# --------------------------------------------------------------------------- #
# Direct Add Files
#
# A file dialog's filter is a convenience for the user, never a trust boundary for
# us. Every path it returns is inspected again here — freshly, without following
# anything — because the filter can be switched to "All files", because the chosen
# path may have changed between the dialog opening and the user pressing Open, and
# because a shortcut is perfectly happy to end in ``.mp3``.
# --------------------------------------------------------------------------- #


def _selection_label(text: str) -> str:
    """A short, display-safe name for something that is not a usable path yet."""
    name = PurePath(text).name if text else ""
    return name or (text if text.strip() else "An empty selection")


def validate_direct_files(
    paths: Iterable[object],
    *,
    request_id: str,
    root: ImportRoot,
    catalog: SupportedTypeCatalog,
    options: ImportOptions,
    id_factory: IdFactory | None = None,
    completed_at: float = 0.0,
) -> ScanResult:
    """Validate individually chosen files and return them as a completed result.

    The user's order is the order — it is never natural-sorted, never lexically
    sorted and never re-grouped, because the sequence the dialog returned *is* the
    order the user built. Natural ordering belongs to folder traversal, where the
    user chose a tree rather than a sequence.

    Every path is re-``lstat``-ed and then classified in the same fail-closed order
    the traversal core uses: existence and readability first, then the link question
    (``maintenance.is_link`` answers ``False`` for something it could not read), then
    the file's shape, then its type. A directory, a shortcut, a junction, a device
    node, a vanished file, an unreadable file and an unsupported extension each
    become a reported problem rather than a silent omission.

    A hidden file chosen *explicitly* is accepted: hidden-file policy exists so a
    folder scan does not sweep up dot-files the user never saw, not to overrule a
    deliberate choice (§6.2).

    Nothing is followed, nothing is recursed into, nothing is opened, nothing is
    written, no worker is started and no output path is reserved. The result is a
    ``ScanResult`` exactly like a folder scan's, so one transaction path serves both.
    """
    _require_identifier("request_id", request_id)
    if not isinstance(root, ImportRoot):
        raise ImportContractError(
            f"root must be an ImportRoot, got {type(root).__name__}")
    if root.kind is not RootKind.DIRECT_FILES:
        raise ImportContractError(
            "Add Files belongs to the direct-files group (Decision 31A): individually "
            "chosen files have no common tree to mirror. Pass a DIRECT_FILES root.")
    if not isinstance(catalog, SupportedTypeCatalog):
        raise ImportContractError(
            f"catalog must be a SupportedTypeCatalog, got {type(catalog).__name__}")
    if not isinstance(options, ImportOptions):
        raise ImportContractError(
            f"options must be an ImportOptions, got {type(options).__name__}")
    if isinstance(paths, (str, bytes, os.PathLike)) or not isinstance(paths, Iterable):
        raise ImportContractError(
            "pass a sequence of selected paths, not a single path")

    # Materialised at once: a list the caller keeps editing afterwards cannot change
    # what was validated, and cannot change what a prepared transaction contains.
    selected = tuple(paths)
    factory = IdFactory() if id_factory is None else id_factory
    extensions = _extension_map(catalog, options)

    files: list[ImportedFile] = []
    problems: list[ImportProblem] = []

    for candidate in selected:
        if isinstance(candidate, bytes) or not isinstance(candidate, (str, os.PathLike)):
            problems.append(_problem(
                ProblemCategory.INVALID_ROOT,
                "A selection that is not a file path was skipped.",
                f"{type(candidate).__name__} is not a usable path", root=root))
            continue
        text = os.fspath(candidate)

        # Lexical only — the filesystem is not consulted to answer this, and a
        # relative path is refused rather than joined onto the current directory,
        # which is not a place the importer has any business reaching into.
        pure = PurePath(text)
        if not text.strip() or not pure.is_absolute() or ".." in pure.parts:
            problems.append(_problem(
                ProblemCategory.INVALID_ROOT,
                f"{_selection_label(text)} is not a usable file selection and was skipped.",
                "a selected path must be lexically absolute and free of '..'", root=root))
            continue
        entry_path = Path(text)

        try:
            entry_stat = os.lstat(entry_path)
        except FileNotFoundError:
            problems.append(_problem(
                ProblemCategory.VANISHED,
                f"{entry_path.name} could no longer be found and was skipped.",
                f"FileNotFoundError: {entry_path}", path=entry_path, root=root))
            continue
        except OSError as exc:
            problems.append(_problem(
                ProblemCategory.UNREADABLE,
                f"{entry_path.name} could not be read and was skipped.",
                f"{type(exc).__name__}: {exc}", path=entry_path, root=root))
            continue

        if _is_link(entry_path):
            problems.append(_problem(
                ProblemCategory.LINK,
                f"{entry_path.name} is a shortcut or link and was not followed.",
                "refused by maintenance.is_link: symlink, junction or other "
                "reparse point", path=entry_path, root=root))
            continue

        mode = entry_stat.st_mode
        if _stat.S_ISDIR(mode):
            problems.append(_problem(
                ProblemCategory.WRONG_TYPE,
                f"{entry_path.name} is a folder; use Add Folder to import what is inside it.",
                f"st_mode={mode:#o} is a directory, and Add Files never recurses",
                path=entry_path, root=root))
            continue
        if not _stat.S_ISREG(mode):
            problems.append(_problem(
                ProblemCategory.WRONG_TYPE,
                f"{entry_path.name} is not an ordinary file and was skipped.",
                f"st_mode={mode:#o} is neither a regular file nor a directory",
                path=entry_path, root=root))
            continue

        type_id = extensions.get(_extension_of(entry_path.name))
        if type_id is None:
            problems.append(_problem(
                ProblemCategory.UNSUPPORTED_TYPE,
                f"{entry_path.name} is not a selected file type and was skipped.",
                "no selected supported type claims this extension",
                path=entry_path, root=root))
            continue

        files.append(ImportedFile(
            occurrence_id=factory.next_id("occ"),
            path=entry_path,
            source_root=root,
            relative_path=None,
            supported_type_id=type_id,
            identity=capture_identity(entry_path, entry_stat),
        ))

    return ScanResult(
        request_id=request_id,
        outcome=ScanOutcome.COMPLETED,
        discovered_count=len(files),
        files=tuple(files),
        problems=tuple(problems),
        completed_at=completed_at,
    )


# --------------------------------------------------------------------------- #
# Transactions
#
# Preparing a transaction reads the list and changes nothing. Committing one either
# appends the whole accepted set or appends nothing. There is no state in between,
# which is why a cancelled, failed or declined import cannot leave half a list.
# --------------------------------------------------------------------------- #


class CommitStatus(Enum):
    """What one commit attempt actually did."""

    #: The whole accepted set was appended, once, and the revision moved.
    COMMITTED = "committed"
    #: The transaction was valid and current but proposed nothing — every candidate
    #: was a duplicate, or the scan found nothing. The list and revision stand still.
    NOTHING_TO_ADD = "nothing_to_add"
    #: The list moved after this transaction was prepared. Nothing was appended and
    #: nothing was merged against stale state; recompute and ask again.
    STALE_REVISION = "stale_revision"


class ManagerOperation(Enum):
    """Which manager mutation a :class:`MutationResult` describes."""

    APPEND = "append"
    REMOVE = "remove"
    CLEAR = "clear"
    MOVE_UP = "move_up"
    MOVE_DOWN = "move_down"


@dataclass(frozen=True, slots=True)
class ImportTransaction:
    """An immutable proposal: what *would* be added, and what was skipped.

    It carries the ``ScanResult`` it was planned from so a stale-revision conflict
    can be recomputed without the caller having to hold the result separately, and
    it carries the duplicate policy it was planned under, so a preference toggled
    afterwards cannot retroactively change what this transaction meant.
    """

    transaction_id: str
    result: ScanResult
    expected_revision: Revision
    additions: tuple[ImportedFile, ...] = ()
    duplicates: tuple[ImportProblem, ...] = ()
    allow_duplicates: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "transaction_id", _require_identifier("transaction_id", self.transaction_id))
        if not isinstance(self.result, ScanResult):
            raise ImportContractError(
                f"result must be a ScanResult, got {type(self.result).__name__}")
        if not self.result.is_committable:
            raise ImportContractError(
                f"a {self.result.outcome.value} scan cannot become a transaction; only a "
                "completed scan may ever reach the imported-file manager")
        if not isinstance(self.expected_revision, Revision):
            raise ImportContractError(
                f"expected_revision must be a Revision, got "
                f"{type(self.expected_revision).__name__}")

        additions = tuple(self.additions)
        seen: set[str] = set()
        for entry in additions:
            if not isinstance(entry, ImportedFile):
                raise ImportContractError(
                    f"additions must be ImportedFile, got {type(entry).__name__}")
            if entry.occurrence_id in seen:
                raise ImportContractError(f"duplicate occurrence_id {entry.occurrence_id!r}")
            seen.add(entry.occurrence_id)
        object.__setattr__(self, "additions", additions)

        duplicates = tuple(self.duplicates)
        for problem in duplicates:
            if not isinstance(problem, ImportProblem):
                raise ImportContractError(
                    f"duplicates must be ImportProblem, got {type(problem).__name__}")
            if problem.category is not ProblemCategory.DUPLICATE:
                raise ImportContractError(
                    "a duplicate skip must be reported as ProblemCategory.DUPLICATE so it "
                    f"is never confused with a validation failure, got {problem.category}")
        object.__setattr__(self, "duplicates", duplicates)
        object.__setattr__(
            self, "allow_duplicates", _require_bool("allow_duplicates", self.allow_duplicates))

    @property
    def request_id(self) -> str:
        return self.result.request_id

    @property
    def proposed_count(self) -> int:
        """What the confirmation in Phase 4 will quote: additions, not discoveries."""
        return len(self.additions)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicates)

    @property
    def is_empty(self) -> bool:
        return not self.additions

    @property
    def problems(self) -> tuple[ImportProblem, ...]:
        """Everything the user should be told: the scan's problems and the skips."""
        return self.result.problems + self.duplicates


@dataclass(frozen=True, slots=True)
class CommitResult:
    """The frozen outcome of one commit attempt, including the ones that did nothing."""

    transaction_id: str
    status: CommitStatus
    snapshot: ImportedFileSnapshot
    expected_revision: Revision
    added: tuple[ImportedFile, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "transaction_id", _require_identifier("transaction_id", self.transaction_id))
        if not isinstance(self.status, CommitStatus):
            raise ImportContractError(
                f"status must be a CommitStatus, got {type(self.status).__name__}")
        if not isinstance(self.snapshot, ImportedFileSnapshot):
            raise ImportContractError("snapshot must be an ImportedFileSnapshot")
        if not isinstance(self.expected_revision, Revision):
            raise ImportContractError("expected_revision must be a Revision")
        added = tuple(self.added)
        for entry in added:
            if not isinstance(entry, ImportedFile):
                raise ImportContractError(
                    f"added must be ImportedFile, got {type(entry).__name__}")
        if added and self.status is not CommitStatus.COMMITTED:
            raise ImportContractError(
                f"a {self.status.value} attempt appended nothing; it must report nothing")
        object.__setattr__(self, "added", added)

    @property
    def committed(self) -> bool:
        return self.status is CommitStatus.COMMITTED

    @property
    def revision(self) -> Revision:
        """Derived from the snapshot — two counters cannot disagree if there is one."""
        return self.snapshot.revision


@dataclass(frozen=True, slots=True)
class MutationResult:
    """The frozen outcome of one manager mutation, including the no-ops."""

    operation: ManagerOperation
    changed: bool
    snapshot: ImportedFileSnapshot
    selection: tuple[str, ...] = ()
    removed: tuple[ImportedFile, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.operation, ManagerOperation):
            raise ImportContractError(
                f"operation must be a ManagerOperation, got {type(self.operation).__name__}")
        object.__setattr__(self, "changed", _require_bool("changed", self.changed))
        if not isinstance(self.snapshot, ImportedFileSnapshot):
            raise ImportContractError("snapshot must be an ImportedFileSnapshot")
        object.__setattr__(
            self,
            "selection",
            tuple(_require_identifier("occurrence_id", item) for item in self.selection),
        )
        removed = tuple(self.removed)
        for entry in removed:
            if not isinstance(entry, ImportedFile):
                raise ImportContractError(
                    f"removed must be ImportedFile, got {type(entry).__name__}")
        object.__setattr__(self, "removed", removed)

    @property
    def revision(self) -> Revision:
        return self.snapshot.revision


def _plan(
    result: ScanResult,
    snapshot: ImportedFileSnapshot,
    allow_duplicates: bool,
    transaction_id: str,
    factory: IdFactory,
) -> ImportTransaction:
    """The deduplication pass. Reads two immutable values and mutates neither."""
    existing: dict[str, str] = {}
    for entry in snapshot.files:
        existing.setdefault(entry.identity, entry.occurrence_id)

    accepted: list[ImportedFile] = []
    duplicates: list[ImportProblem] = []
    seen_here: dict[str, str] = {}

    for candidate in result.files:
        if not allow_duplicates:
            prior = existing.get(candidate.identity)
            if prior is not None:
                duplicates.append(_problem(
                    ProblemCategory.DUPLICATE,
                    f"{candidate.name} is already in the imported list and was skipped.",
                    f"source identity {candidate.identity} already imported as {prior}",
                    path=candidate.path, root=candidate.source_root))
                continue
            prior = seen_here.get(candidate.identity)
            if prior is not None:
                duplicates.append(_problem(
                    ProblemCategory.DUPLICATE,
                    f"{candidate.name} was selected more than once and was added once.",
                    f"source identity {candidate.identity} already proposed as {prior} "
                    "in this same import",
                    path=candidate.path, root=candidate.source_root))
                continue

        # A new occurrence id, from the manager's own factory, so a deliberate
        # duplicate is a second *row* rather than a second *file*: same identity,
        # same path, same root, same relative path — nothing is disguised.
        occurrence = ImportedFile(
            occurrence_id=factory.next_id("occ"),
            path=candidate.path,
            source_root=candidate.source_root,
            relative_path=candidate.relative_path,
            supported_type_id=candidate.supported_type_id,
            identity=candidate.identity,
        )
        accepted.append(occurrence)
        seen_here.setdefault(candidate.identity, occurrence.occurrence_id)

    return ImportTransaction(
        transaction_id=transaction_id,
        result=result,
        expected_revision=snapshot.revision,
        additions=tuple(accepted),
        duplicates=tuple(duplicates),
        allow_duplicates=allow_duplicates,
    )


def plan_transaction(
    result: ScanResult,
    snapshot: ImportedFileSnapshot,
    *,
    options: ImportOptions,
    transaction_id: str,
    id_factory: IdFactory | None = None,
) -> ImportTransaction:
    """Decide what a completed scan *would* add, without adding it.

    Each candidate's source identity is compared against every occurrence already in
    *snapshot* and against every candidate already accepted in this same transaction,
    so a file cannot slip in twice by being reached two ways. Identity comes from
    Phase 2's :func:`capture_identity`: the platform's own non-following file id where
    there is one, so two spellings and a hard link collapse correctly, and a
    Unicode-normalised lexical key where there is not — casefolded only where the
    filesystem is case-blind, so a case-sensitive volume keeps two real files apart.

    The default skips duplicates and records each one as a ``DUPLICATE`` problem, kept
    distinct from unsupported, link, unreadable and invalid problems so the Summary can
    tell the user which happened. ``options.allow_duplicate_files`` (Decision 35A, off
    by default) keeps every occurrence instead; the value is frozen onto the returned
    transaction so a preference changed afterwards cannot rewrite what it meant.

    Pass the manager's own ``id_factory`` — :meth:`ImportedFileManager.plan` does — so
    minted occurrence ids cannot collide with ids already in the list.
    """
    if not isinstance(result, ScanResult):
        raise ImportContractError(
            f"result must be a ScanResult, got {type(result).__name__}")
    if not result.is_committable:
        raise ImportContractError(
            f"a {result.outcome.value} scan cannot be planned; a cancelled, failed or "
            "declined import must not partly modify the imported list")
    if not isinstance(snapshot, ImportedFileSnapshot):
        raise ImportContractError(
            f"snapshot must be an ImportedFileSnapshot, got {type(snapshot).__name__}")
    if not isinstance(options, ImportOptions):
        raise ImportContractError(
            f"options must be an ImportOptions, got {type(options).__name__}")
    if id_factory is not None and not isinstance(id_factory, IdFactory):
        raise ImportContractError("id_factory must be an IdFactory")
    return _plan(
        result,
        snapshot,
        options.allow_duplicate_files,
        _require_identifier("transaction_id", transaction_id),
        IdFactory() if id_factory is None else id_factory,
    )


# --------------------------------------------------------------------------- #
# Plan 2 compatibility
#
# A regrouping, not a second path planner. ``output_paths`` already knows how to
# turn sources into destinations; all it ever needed from the importer was which
# root each file came from, and ``ImportedFile`` has carried that since Phase 1.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PlanningGroups:
    """Imported files, arranged the way Plan 2's planners already accept them.

    ``direct`` feeds ``plan_flat``; a single entry in ``grouped`` feeds
    ``plan_mirrored``; several feed ``plan_multi_root``. Building this creates no
    directory, reserves no run and decides no destination — it only sorts sources
    into the shape the existing service asks for.
    """

    direct: tuple[Path, ...] = ()
    grouped: tuple[tuple[Path, tuple[Path, ...]], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "direct", tuple(_require_absolute_path("source", item) for item in self.direct))
        groups: list[tuple[Path, tuple[Path, ...]]] = []
        for entry in self.grouped:
            source_root, sources = entry
            groups.append((
                _require_absolute_path("source root", source_root),
                tuple(_require_absolute_path("source", item) for item in sources),
            ))
        object.__setattr__(self, "grouped", tuple(groups))

    @property
    def root_count(self) -> int:
        return len(self.grouped)

    @property
    def total(self) -> int:
        return len(self.direct) + sum(len(sources) for _root, sources in self.grouped)

    @property
    def needs_multi_root(self) -> bool:
        """More than one folder root, so ``plan_multi_root`` keeps the trees apart."""
        return len(self.grouped) > 1


def planning_groups(snapshot: object) -> PlanningGroups:
    """Group a manager snapshot by source root, in the user's own root order.

    Individually added files have no tree to reproduce (Decision 31A) and come back
    in ``direct``; everything found under a selected folder comes back under that
    folder, in imported-list order. Roots keep the order the user added them in, so
    one root's tree can never migrate into another's.
    """
    if isinstance(snapshot, ImportedFileSnapshot):
        files: tuple[ImportedFile, ...] = snapshot.files
    elif isinstance(snapshot, (str, bytes)) or not isinstance(snapshot, Iterable):
        raise ImportContractError(
            "pass an ImportedFileSnapshot or an iterable of ImportedFile")
    else:
        files = tuple(snapshot)

    direct: list[Path] = []
    buckets: dict[str, list[Path]] = {}
    roots: dict[str, Path] = {}
    order: list[tuple[int, str]] = []

    for entry in files:
        if not isinstance(entry, ImportedFile):
            raise ImportContractError(
                f"entries must be ImportedFile, got {type(entry).__name__}")
        mirroring = entry.mirroring_root
        if mirroring is None:
            direct.append(entry.path)
            continue
        key = entry.source_root.root_id
        if key not in buckets:
            buckets[key] = []
            roots[key] = mirroring
            order.append((entry.source_root.order, key))
        buckets[key].append(entry.path)

    order.sort()
    return PlanningGroups(
        direct=tuple(direct),
        grouped=tuple((roots[key], tuple(buckets[key])) for _order, key in order),
    )


# --------------------------------------------------------------------------- #
# The imported-file manager
# --------------------------------------------------------------------------- #


class ImportedFileManager:
    """The ordered imported list, its revision, and its selection.

    Pure in-process ownership. It holds a tuple of occurrences, a monotonic
    :class:`Revision`, and the occurrence ids the user has selected — and it touches
    no filesystem at all. **Removing or clearing a row never deletes, renames,
    rewrites or touches the source file**; the importer owns a list of references,
    not the files they point at.

    Selection is kept by occurrence id rather than by row number, so a selection
    survives a reorder and can be restored after the UI rebuilds its list. It is
    stored in list order rather than click order, because the block move below is
    defined in terms of where rows sit, not the sequence they were clicked in.

    Every mutation returns an immutable result carrying the snapshot afterwards, and
    the revision only moves when something actually changed — so a no-op cannot
    invalidate a transaction that another part of the UI is holding.

    Main-thread ownership (§6.6) is a contract, not a lock: Phase 4's worker returns
    candidates through a queue and never touches this object. No lock is taken here
    precisely so that rule stays visible rather than being quietly papered over.
    """

    __slots__ = ("_files", "_revision", "_factory", "_selected")

    def __init__(self, *, id_factory: IdFactory | None = None) -> None:
        if id_factory is not None and not isinstance(id_factory, IdFactory):
            raise ImportContractError(
                f"id_factory must be an IdFactory, got {type(id_factory).__name__}")
        self._files: tuple[ImportedFile, ...] = ()
        self._revision: Revision = INITIAL_REVISION
        self._factory: IdFactory = IdFactory() if id_factory is None else id_factory
        self._selected: tuple[str, ...] = ()

    # -- reading ----------------------------------------------------------- #

    @property
    def revision(self) -> Revision:
        return self._revision

    @property
    def count(self) -> int:
        return len(self._files)

    @property
    def selected_count(self) -> int:
        return len(self._selected)

    @property
    def selection(self) -> tuple[str, ...]:
        """The selected occurrence ids, in list order. Immutable."""
        return self._selected

    @property
    def is_empty(self) -> bool:
        return not self._files

    def snapshot(self) -> ImportedFileSnapshot:
        """The list frozen at the current revision. Reading it changes nothing."""
        return ImportedFileSnapshot(revision=self._revision, files=self._files)

    def selected_files(self) -> tuple[ImportedFile, ...]:
        chosen = set(self._selected)
        return tuple(entry for entry in self._files if entry.occurrence_id in chosen)

    # -- selection --------------------------------------------------------- #

    def select(self, occurrence_ids: Iterable[object]) -> tuple[str, ...]:
        """Restore a selection by occurrence id, dropping any id that is not present.

        Dropping rather than raising is what "stable restoration" means here: after a
        removal or a fresh import the UI reasonably offers back the ids it remembers,
        and the ones that no longer exist are simply no longer selected.
        """
        if isinstance(occurrence_ids, (str, bytes)) or not isinstance(
                occurrence_ids, Iterable):
            raise ImportContractError("pass an iterable of occurrence ids")
        wanted = {
            _require_identifier("occurrence_id", value) for value in occurrence_ids}
        self._selected = tuple(
            entry.occurrence_id for entry in self._files if entry.occurrence_id in wanted)
        return self._selected

    def clear_selection(self) -> tuple[str, ...]:
        self._selected = ()
        return self._selected

    # -- planning and committing ------------------------------------------- #

    def plan(
        self,
        result: ScanResult,
        *,
        options: ImportOptions,
        transaction_id: str | None = None,
    ) -> ImportTransaction:
        """Prepare a transaction against this manager's current revision.

        Preparing changes nothing at all: no row is added, no revision moves, and the
        proposal can be shown, counted, confirmed or thrown away freely.
        """
        return plan_transaction(
            result,
            self.snapshot(),
            options=options,
            transaction_id=(
                self._factory.next_id("txn") if transaction_id is None else transaction_id),
            id_factory=self._factory,
        )

    def recompute(self, transaction: ImportTransaction) -> ImportTransaction:
        """Re-plan a stale transaction against the list as it is *now*.

        The safe answer to a revision conflict: rather than merging a proposal into a
        list that moved underneath it, the same scan is deduplicated again against
        current state under the same frozen duplicate policy. The caller compares the
        new proposed count with the old one and re-confirms if it materially changed
        — that judgement is Phase 4's; this is the primitive it needs.
        """
        if not isinstance(transaction, ImportTransaction):
            raise ImportContractError(
                f"recompute needs an ImportTransaction, got {type(transaction).__name__}")
        return _plan(
            transaction.result,
            self.snapshot(),
            transaction.allow_duplicates,
            self._factory.next_id("txn"),
            self._factory,
        )

    def commit(self, transaction: ImportTransaction) -> CommitResult:
        """Append the whole accepted set once, or append nothing.

        There is no partial outcome. A transaction prepared against an older revision
        is refused untouched, so a scan that finished while the user was reordering
        the list cannot merge itself into state it never saw. Committing the same
        transaction twice fails the second time for exactly that reason.
        """
        if not isinstance(transaction, ImportTransaction):
            raise ImportContractError(
                f"commit needs an ImportTransaction, got {type(transaction).__name__}")

        if transaction.expected_revision != self._revision:
            return CommitResult(
                transaction_id=transaction.transaction_id,
                status=CommitStatus.STALE_REVISION,
                snapshot=self.snapshot(),
                expected_revision=transaction.expected_revision,
            )

        if not transaction.additions:
            return CommitResult(
                transaction_id=transaction.transaction_id,
                status=CommitStatus.NOTHING_TO_ADD,
                snapshot=self.snapshot(),
                expected_revision=transaction.expected_revision,
            )

        known = {entry.occurrence_id for entry in self._files}
        clashing = sorted(
            entry.occurrence_id for entry in transaction.additions
            if entry.occurrence_id in known)
        if clashing:
            raise ImportContractError(
                f"these occurrence ids are already in the list: {clashing}. Plan the "
                "transaction through this manager so its own IdFactory mints them.")

        self._files = self._files + transaction.additions
        self._revision = self._revision.advance()
        return CommitResult(
            transaction_id=transaction.transaction_id,
            status=CommitStatus.COMMITTED,
            snapshot=self.snapshot(),
            expected_revision=transaction.expected_revision,
            added=transaction.additions,
        )

    # -- mutating ---------------------------------------------------------- #

    def remove_selected(self) -> MutationResult:
        """Remove exactly the selected rows. **No source file is touched.**"""
        if not self._selected:
            return MutationResult(
                operation=ManagerOperation.REMOVE,
                changed=False,
                snapshot=self.snapshot(),
                selection=self._selected,
            )
        chosen = set(self._selected)
        removed = tuple(
            entry for entry in self._files if entry.occurrence_id in chosen)
        self._files = tuple(
            entry for entry in self._files if entry.occurrence_id not in chosen)
        self._selected = ()
        self._revision = self._revision.advance()
        return MutationResult(
            operation=ManagerOperation.REMOVE,
            changed=True,
            snapshot=self.snapshot(),
            selection=(),
            removed=removed,
        )

    def clear(self) -> MutationResult:
        """Empty the imported list. **No source file is deleted.**"""
        if not self._files:
            self._selected = ()
            return MutationResult(
                operation=ManagerOperation.CLEAR,
                changed=False,
                snapshot=self.snapshot(),
                selection=(),
            )
        removed = self._files
        self._files = ()
        self._selected = ()
        self._revision = self._revision.advance()
        return MutationResult(
            operation=ManagerOperation.CLEAR,
            changed=True,
            snapshot=self.snapshot(),
            selection=(),
            removed=removed,
        )

    def move_selected_up(self) -> MutationResult:
        return self._move(ManagerOperation.MOVE_UP)

    def move_selected_down(self) -> MutationResult:
        return self._move(ManagerOperation.MOVE_DOWN)

    def _move(self, operation: ManagerOperation) -> MutationResult:
        """Move the selection as one logical block across one unselected row.

        Selected rows keep their relative order and travel together even when they
        are not adjacent — the block closes up around the row it crosses. Unselected
        rows keep their relative order too. Nothing wraps: a block whose topmost row
        is already at the top, or whose bottommost row is already at the bottom, has
        nowhere to go in that direction and the call is a safe no-op, as it is when
        nothing is selected and when everything is.
        """
        up = operation is ManagerOperation.MOVE_UP
        chosen = set(self._selected)
        indices = [
            position for position, entry in enumerate(self._files)
            if entry.occurrence_id in chosen
        ]

        blocked = (
            not indices
            or len(indices) == len(self._files)
            or (up and indices[0] == 0)
            or (not up and indices[-1] == len(self._files) - 1)
        )
        if blocked:
            return MutationResult(
                operation=operation,
                changed=False,
                snapshot=self.snapshot(),
                selection=self._selected,
            )

        taken = set(indices)
        block = tuple(self._files[position] for position in indices)
        rest = [
            entry for position, entry in enumerate(self._files) if position not in taken]
        # How many unselected rows sit above the block today; one fewer means the
        # block crossed the row above it, one more means it crossed the row below.
        above = sum(1 for position in range(indices[0]) if position not in taken)
        insert_at = above - 1 if up else above + 1

        reordered = tuple(rest[:insert_at]) + block + tuple(rest[insert_at:])
        if reordered == self._files:  # pragma: no cover - the guards above prevent it
            return MutationResult(
                operation=operation,
                changed=False,
                snapshot=self.snapshot(),
                selection=self._selected,
            )

        self._files = reordered
        # Selection stays on the rows that moved, re-read in the new list order.
        self._selected = tuple(
            entry.occurrence_id for entry in self._files if entry.occurrence_id in chosen)
        self._revision = self._revision.advance()
        return MutationResult(
            operation=operation,
            changed=True,
            snapshot=self.snapshot(),
            selection=self._selected,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"ImportedFileManager(count={len(self._files)}, "
                f"revision={self._revision.value}, selected={len(self._selected)})")
