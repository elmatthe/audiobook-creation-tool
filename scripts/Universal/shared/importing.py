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

What deliberately does **not** live here
---------------------------------------
No traversal, no ``scandir``, no ``lstat``, no link or hidden detection, no duplicate
identity derivation, no natural-sort key, no manager operations, no threads, no
queues, no polling, no pause/resume controller, no ETA, and no Tk. Those belong to
Phases 2–8 of the active drop. **Constructing anything in this module touches the
filesystem zero times** — every path rule below is lexical, which is also why
``resolve()`` is never called: a link must be *detected* later, never followed now.

Boundaries this module keeps
----------------------------
* It **consumes** ``shared.config``; it never re-implements configuration loading.
  A ``ScanRequest`` carries one captured ``EffectiveConfig`` so the large-result
  threshold cannot be re-read, and therefore cannot change, mid-scan.
* It creates **no** output path and reserves **no** run. ``ImportedFile`` merely
  *retains* the source root and root-relative path that Plan 2's ``plan_flat`` /
  ``plan_mirrored`` / ``plan_multi_root`` will later need.
* ``shared.cancellation`` is untouched and unwrapped.

Everything is a frozen dataclass validated in ``__post_init__``, so an invalid value
cannot be constructed at all — there is no "validate later" path to forget.
"""

from __future__ import annotations

import itertools
import math
import os
import threading
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePath
from types import MappingProxyType

from shared import config as _config

__all__ = [
    "ImportContractError",
    "IdFactory",
    "normalize_extension",
    "ensure_display_safe",
    "ProblemCategory",
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

    @classmethod
    def for_catalog(
        cls,
        catalog: SupportedTypeCatalog,
        *,
        include_hidden_folders: bool = False,
        allow_duplicate_files: bool = False,
    ) -> "ImportOptions":
        """The defaults: everything selected, hidden folders out, duplicates off."""
        if not isinstance(catalog, SupportedTypeCatalog):
            raise ImportContractError("catalog must be a SupportedTypeCatalog")
        return cls(
            selected_type_ids=catalog.default_selection(),
            include_hidden_folders=include_hidden_folders,
            allow_duplicate_files=allow_duplicate_files,
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
