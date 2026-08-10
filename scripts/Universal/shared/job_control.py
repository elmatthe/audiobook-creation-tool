"""Shared job control — v0.6.0 Drop 3 (Plan 3), Phases 1 and 5.

Phase 1 made this module **contracts only**: the states a run can be in, the
transitions between them that are legal, the frozen snapshot a run is judged by,
the record of what failed, the request to retry only those, and the typed events a
worker may report.

Phase 5 added the one object that *owns* a run — :class:`JobController` — together
with the immutable :class:`JobSnapshot` it hands out. It is still the case that
nothing here starts a thread, runs work, touches a widget or reads a disk: the
controller coordinates a worker that somebody else started, and its whole
concurrency budget is one :class:`threading.Condition` guarding its own state.

What lives here
---------------
``JobState`` and ``LEGAL_TRANSITIONS`` — the complete state vocabulary and the
transition table, so an illegal move is rejected deterministically rather than
being an emergent property of whoever wrote the controller. ``freeze_options`` —
the deep copy-and-freeze that makes a tool's options safe to hand to a worker.
``RunSnapshot`` — one run's single source of truth. ``FailureRecord`` /
``FailureLog`` / ``RetryRequest`` — what went wrong and what may be retried.
``JobEvent`` — the typed, Tk-free report a worker puts on a queue.

What deliberately does **not** live here
---------------------------------------
No thread, no queue, no polling, no ETA arithmetic, no progress widget, no Tk, and
no output placement of any kind. Phases 6–8 own those. In particular this module
reserves no run directory and defines no output-policy type: a destination choice
reaches a run only inside a later adopter's frozen tool options, and Plan 2 remains
the only owner of paths.

The relationship with ``shared.cancellation``
---------------------------------------------
The controller **extends** the existing cooperative pattern rather than replacing
it. Its checkpoint raises that module's :class:`ConversionCancelled`, and
:meth:`JobController.cancel_check` has exactly the ``CancelCheck`` shape
``raise_if_cancelled`` already accepts, so an existing worker keeps working whether
it is handed a bare ``threading.Event().is_set`` or a controller. Nothing in that
module changed meaning; Phase 5 only added a non-raising predicate beside it.

Importing a folder is a different job with a different Cancel button:
``shared.import_coordination`` owns that one, does not import ``shared.cancellation``
at all, and is unaffected by anything here.

Truthfulness
------------
Pause and cancel are *requests*. ``PAUSE_REQUESTED`` and ``CANCEL_REQUESTED`` exist
as first-class states precisely so the UI can say "Pause requested" while an
indivisible stage keeps running, instead of claiming an OS call stopped instantly.
"""

from __future__ import annotations

import dataclasses
import math
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Any

from shared import config as _config
from shared.cancellation import ConversionCancelled
from shared.importing import (
    ImportContractError,
    ImportedFileSnapshot,
    ImportOptions,
    SupportedTypeCatalog,
    ensure_display_safe,
)

__all__ = [
    "JobContractError",
    "IllegalJobTransition",
    "OptionFreezeError",
    "RetryContractError",
    "JobState",
    "LEGAL_TRANSITIONS",
    "TERMINAL_STATES",
    "INPUT_LOCKED_STATES",
    "is_legal_transition",
    "require_legal_transition",
    "freeze_options",
    "is_frozen_options",
    "RunSnapshot",
    "FailureRecord",
    "FailureLog",
    "RetryRequest",
    "JobEventKind",
    "TERMINAL_EVENT_KINDS",
    "JobEvent",
    "MAX_FAILURE_DETAIL",
    "JobSnapshot",
    "JobController",
]


class JobContractError(ValueError):
    """Base for every invariant this module enforces."""


class IllegalJobTransition(JobContractError):
    """Raised for a state change the model does not allow."""


class OptionFreezeError(JobContractError):
    """Raised when an options payload cannot be frozen without keeping a live reference."""


class RetryContractError(JobContractError):
    """Raised when a retry would not refer to the exact original run."""


# --------------------------------------------------------------------------- #
# Job states
# --------------------------------------------------------------------------- #


class JobState(Enum):
    """Every state a single run may occupy."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    FAILED = "failed"


#: The four states from which nothing further may happen. A controller belongs to
#: one run: reaching any of these ends it, and it may not be revived by clearing
#: an event and starting again.
TERMINAL_STATES = frozenset({
    JobState.CANCELLED,
    JobState.SUCCEEDED,
    JobState.COMPLETED_WITH_FAILURES,
    JobState.FAILED,
})

#: The states in which the job owns its inputs, so imported-file and processing
#: option controls are read-only (Decision 9A). Deriving the per-control lock
#: matrix from this set is Phase 6's work; the set itself is vocabulary.
INPUT_LOCKED_STATES = frozenset({
    JobState.RUNNING,
    JobState.PAUSE_REQUESTED,
    JobState.PAUSED,
    JobState.CANCEL_REQUESTED,
})

_ENDINGS = frozenset({
    JobState.SUCCEEDED,
    JobState.COMPLETED_WITH_FAILURES,
    JobState.FAILED,
})

#: The complete transition table.
#:
#: Two entries are worth explaining, because both encode truthfulness rather than
#: tidiness:
#:
#: * ``PAUSE_REQUESTED`` may end the run directly. A pause asked for during an
#:   indivisible stage does not stop that stage, and the stage may well be the last
#:   one — reporting ``SUCCEEDED`` there is the honest outcome, and forcing a detour
#:   through ``PAUSED`` would mean claiming the job paused when it had finished.
#: * ``CANCEL_REQUESTED`` may also end in success or failure, not only in
#:   ``CANCELLED``. Cancel is a cooperative request checked at the next safe
#:   checkpoint; if the work genuinely completed before that checkpoint arrived,
#:   saying so is correct and pretending it was cancelled is not.
LEGAL_TRANSITIONS: Mapping[JobState, frozenset[JobState]] = MappingProxyType({
    JobState.IDLE: frozenset({JobState.RUNNING}),
    JobState.RUNNING: frozenset(
        {JobState.PAUSE_REQUESTED, JobState.CANCEL_REQUESTED} | _ENDINGS),
    JobState.PAUSE_REQUESTED: frozenset(
        {JobState.PAUSED, JobState.RUNNING, JobState.CANCEL_REQUESTED} | _ENDINGS),
    JobState.PAUSED: frozenset({JobState.RUNNING, JobState.CANCEL_REQUESTED}),
    JobState.CANCEL_REQUESTED: frozenset({JobState.CANCELLED} | _ENDINGS),
    JobState.CANCELLED: frozenset(),
    JobState.SUCCEEDED: frozenset(),
    JobState.COMPLETED_WITH_FAILURES: frozenset(),
    JobState.FAILED: frozenset(),
})


def is_legal_transition(current: JobState, proposed: JobState) -> bool:
    """Pure table lookup. No controller, no locking, no side effect."""
    if not isinstance(current, JobState) or not isinstance(proposed, JobState):
        raise JobContractError("transitions are between JobState members")
    return proposed in LEGAL_TRANSITIONS[current]


def require_legal_transition(current: JobState, proposed: JobState) -> None:
    """Raise :class:`IllegalJobTransition` unless the move is in the table."""
    if not is_legal_transition(current, proposed):
        raise IllegalJobTransition(
            f"{current.value} -> {proposed.value} is not a legal job transition")


# --------------------------------------------------------------------------- #
# Copy-safe option freezing
# --------------------------------------------------------------------------- #

#: Values that are already immutable and may be kept as they are.
_IMMUTABLE_SCALARS = (type(None), bool, int, str, bytes, PurePath, Enum)

#: Types that look container-ish but can never be frozen into a value: they either
#: alias a live buffer or carry executable/live state.
_ALWAYS_REJECTED = (bytearray, memoryview)


def _freeze_value(value: Any, path: str, seen: set[int]) -> Any:
    if isinstance(value, _ALWAYS_REJECTED):
        raise OptionFreezeError(
            f"{path}: {type(value).__name__} aliases a live buffer and cannot be frozen")
    if isinstance(value, _IMMUTABLE_SCALARS):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OptionFreezeError(f"{path}: {value!r} is not a finite number")
        return value

    identifier = id(value)
    if identifier in seen:
        raise OptionFreezeError(f"{path}: options must not contain a reference cycle")
    seen.add(identifier)
    try:
        if isinstance(value, Mapping):
            frozen: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise OptionFreezeError(
                        f"{path}: option keys must be strings, got {type(key).__name__}")
                frozen[key] = _freeze_value(item, f"{path}.{key}", seen)
            return MappingProxyType(frozen)
        if isinstance(value, (tuple, list)):
            return tuple(
                _freeze_value(item, f"{path}[{index}]", seen)
                for index, item in enumerate(value)
            )
        if isinstance(value, (set, frozenset)):
            members = tuple(
                _freeze_value(item, f"{path}{{}}", seen) for item in value)
            try:
                return frozenset(members)
            except TypeError as exc:
                raise OptionFreezeError(
                    f"{path}: a set may only hold hashable frozen values ({exc})") from exc
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            if not value.__dataclass_params__.frozen:
                raise OptionFreezeError(
                    f"{path}: {type(value).__name__} is a mutable dataclass; "
                    "pass a frozen one or a plain mapping")
            for entry in dataclasses.fields(value):
                _freeze_value(getattr(value, entry.name), f"{path}.{entry.name}", seen)
            return value
        raise OptionFreezeError(
            f"{path}: {type(value).__name__} is not a supported option value; "
            "options must be plain immutable data, never a live object")
    finally:
        seen.discard(identifier)


def freeze_options(options: Any) -> Mapping[str, Any]:
    """Deep-copy *options* into an immutable mapping, or refuse.

    The point is not tidiness, it is that a worker must not be able to observe a
    later edit. Lists become tuples and dicts become new read-only mappings, so
    mutating whatever was passed in afterwards cannot reach the snapshot.

    Anything that cannot be copied into a value — a widget, a variable, a callable,
    a thread, an open file, a mutable dataclass, a reference cycle — is **rejected**
    rather than stored as a live reference, because storing it would quietly turn a
    "frozen" snapshot into a window onto changing state.
    """
    if options is None:
        return MappingProxyType({})
    if not isinstance(options, Mapping):
        raise OptionFreezeError(
            f"options must be a mapping, got {type(options).__name__}")
    frozen: dict[str, Any] = {}
    for key, value in options.items():
        if not isinstance(key, str):
            raise OptionFreezeError(
                f"option keys must be strings, got {type(key).__name__}")
        frozen[key] = _freeze_value(value, key, set())
    return MappingProxyType(frozen)


def is_frozen_options(value: Any) -> bool:
    """True when *value* is exactly what :func:`freeze_options` produces."""
    if not isinstance(value, MappingProxyType):
        return False
    try:
        for key, item in value.items():
            if not isinstance(key, str):
                return False
            _freeze_value(item, key, set())
    except OptionFreezeError:
        return False
    return True


# --------------------------------------------------------------------------- #
# The frozen run
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """One run's complete, frozen configuration — the only thing a worker reads.

    Decision 9A in data form: inputs, options and effective configuration are
    captured once, on the main thread, before any work starts. A preference saved,
    a checkbox toggled, or a file added afterwards cannot reach a run already under
    way, because the run never consults them again.

    ``tool_options`` is whatever a later adopting tool needs, deep-frozen on
    construction. This drop looks inside it for nothing: a destination mode, a
    bitrate or a metadata choice travels there opaquely, and Plan 2 stays the only
    owner of what a destination *means*.

    Not hashable in practice — ``EffectiveConfig`` and the frozen options mapping
    are unhashable by construction. Equality is well defined and is what to compare.
    """

    snapshot_id: str
    files: ImportedFileSnapshot
    catalog: SupportedTypeCatalog
    import_options: ImportOptions
    effective_config: "_config.EffectiveConfig"
    tool_options: Mapping[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "snapshot_id", _require_identifier("snapshot_id", self.snapshot_id))
        if not isinstance(self.files, ImportedFileSnapshot):
            raise JobContractError(
                f"files must be an ImportedFileSnapshot, got {type(self.files).__name__}")
        if not isinstance(self.catalog, SupportedTypeCatalog):
            raise JobContractError("catalog must be a SupportedTypeCatalog")
        if not isinstance(self.import_options, ImportOptions):
            raise JobContractError("import_options must be an ImportOptions")
        if not isinstance(self.effective_config, _config.EffectiveConfig):
            raise JobContractError(
                "effective_config must be a captured config.EffectiveConfig")

        known = set(self.catalog.type_ids)
        unknown_selected = set(self.import_options.selected_type_ids) - known
        if unknown_selected:
            raise JobContractError(
                f"selected type ids are not in the catalog: {sorted(unknown_selected)}")
        unknown_files = {
            entry.supported_type_id for entry in self.files.files
        } - known
        if unknown_files:
            raise JobContractError(
                f"imported files reference types outside the catalog: "
                f"{sorted(unknown_files)}")

        # Freeze here rather than trusting the caller: this is the single point at
        # which a live payload can be turned away.
        object.__setattr__(self, "tool_options", freeze_options(self.tool_options))
        object.__setattr__(self, "created_at", _require_timestamp("created_at", self.created_at))

    @property
    def item_ids(self) -> tuple[str, ...]:
        """The ordered occurrence ids this run was created for."""
        return self.files.occurrence_ids

    @property
    def count(self) -> int:
        return self.files.count


# --------------------------------------------------------------------------- #
# Failures and retry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FailureRecord:
    """One thing that went wrong, tied to the run it went wrong in.

    ``item_id`` is ``None`` for a fatal, job-level failure. A fatal failure can
    never be retryable: Retry Failed re-runs *items*, and offering to retry a run
    that died as a whole would promise something the model cannot express.
    """

    item_id: str | None
    stage: str
    display_message: str
    technical_detail: str
    retryable: bool
    snapshot_id: str

    def __post_init__(self) -> None:
        if self.item_id is not None:
            object.__setattr__(self, "item_id", _require_identifier("item_id", self.item_id))
        object.__setattr__(self, "stage", _require_identifier("stage", self.stage))
        object.__setattr__(
            self,
            "display_message",
            _require_display_safe("display_message", self.display_message),
        )
        if not isinstance(self.technical_detail, str):
            raise JobContractError("technical_detail must be a string")
        if not isinstance(self.retryable, bool):
            raise JobContractError("retryable must be a bool")
        object.__setattr__(
            self, "snapshot_id", _require_identifier("snapshot_id", self.snapshot_id))
        if self.item_id is None and self.retryable:
            raise JobContractError(
                "a fatal job-level failure has no item to retry; set retryable=False")

    @property
    def is_fatal(self) -> bool:
        return self.item_id is None


@dataclass(frozen=True, slots=True)
class FailureLog:
    """The ordered failures of one run.

    Order is the order things failed, and it is what a retry follows. An item may
    appear once: a second record for the same item would make "the ordered subset of
    failed ids" ambiguous, and a retry built from an ambiguous list is a retry
    nobody can predict.
    """

    snapshot_id: str
    records: tuple[FailureRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "snapshot_id", _require_identifier("snapshot_id", self.snapshot_id))
        if isinstance(self.records, (str, bytes)) or not isinstance(self.records, Iterable):
            raise JobContractError("records must be an iterable of FailureRecord")
        entries = tuple(self.records)
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, FailureRecord):
                raise JobContractError(
                    f"records must be FailureRecord, got {type(entry).__name__}")
            if entry.snapshot_id != self.snapshot_id:
                raise JobContractError(
                    f"failure for snapshot {entry.snapshot_id!r} does not belong to "
                    f"{self.snapshot_id!r}")
            if entry.item_id is not None:
                if entry.item_id in seen:
                    raise JobContractError(
                        f"item {entry.item_id!r} already has a failure record")
                seen.add(entry.item_id)
        object.__setattr__(self, "records", entries)

    @property
    def is_empty(self) -> bool:
        return not self.records

    @property
    def fatal(self) -> tuple[FailureRecord, ...]:
        return tuple(entry for entry in self.records if entry.is_fatal)

    def retryable_ids(self) -> tuple[str, ...]:
        """Retryable item ids, in the order they failed."""
        return tuple(
            entry.item_id for entry in self.records
            if entry.retryable and entry.item_id is not None
        )

    @property
    def has_retryable(self) -> bool:
        """Retry Failed is offered only when this is true."""
        return bool(self.retryable_ids())

    def for_item(self, item_id: str) -> FailureRecord | None:
        for entry in self.records:
            if entry.item_id == item_id:
                return entry
        return None


@dataclass(frozen=True, slots=True)
class RetryRequest:
    """Re-run only the failed items, against the **exact** original snapshot.

    ``snapshot`` is the original object, not a copy or a rebuild: a retry must use
    the configuration the run actually used, never today's widgets, today's settings
    or today's imported list. Tests assert object identity for that reason.

    Where a retried output lands is deliberately undecided here. That is an adopting
    plan's choice, made through Plan 2's services.
    """

    snapshot: RunSnapshot
    item_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, RunSnapshot):
            raise RetryContractError(
                f"snapshot must be a RunSnapshot, got {type(self.snapshot).__name__}")
        if isinstance(self.item_ids, (str, bytes)) or not isinstance(self.item_ids, Iterable):
            raise RetryContractError("item_ids must be an iterable of item ids")
        entries = tuple(self.item_ids)
        if not entries:
            raise RetryContractError("a retry needs at least one item")
        known = set(self.snapshot.item_ids)
        seen: set[str] = set()
        for entry in entries:
            identifier = _require_identifier("item_id", entry)
            if identifier in seen:
                raise RetryContractError(f"item {identifier!r} is listed twice")
            seen.add(identifier)
            if identifier not in known:
                raise RetryContractError(
                    f"item {identifier!r} does not belong to snapshot "
                    f"{self.snapshot.snapshot_id!r}")
        object.__setattr__(self, "item_ids", entries)

    @classmethod
    def from_failures(
        cls,
        snapshot: RunSnapshot,
        failures: FailureLog,
        item_ids: Iterable[str] | None = None,
    ) -> "RetryRequest":
        """Build a retry from a run's own failure log.

        Rejects a foreign snapshot, an unknown item, an item that succeeded, one
        that failed unretryably, and a duplicate. With *item_ids* omitted, every
        retryable failure is retried.

        The result is always ordered by the failure log, whatever order the caller
        asked in, so the same set of ids always produces the same request.
        """
        if not isinstance(snapshot, RunSnapshot):
            raise RetryContractError("snapshot must be a RunSnapshot")
        if not isinstance(failures, FailureLog):
            raise RetryContractError("failures must be a FailureLog")
        if failures.snapshot_id != snapshot.snapshot_id:
            raise RetryContractError(
                f"failure log {failures.snapshot_id!r} does not belong to run "
                f"{snapshot.snapshot_id!r}")

        candidates = failures.retryable_ids()
        if not candidates:
            raise RetryContractError(
                "Retry Failed is unavailable: this run recorded no retryable failure")
        if item_ids is None:
            return cls(snapshot=snapshot, item_ids=candidates)

        if isinstance(item_ids, (str, bytes)) or not isinstance(item_ids, Iterable):
            raise RetryContractError("item_ids must be an iterable of item ids")
        requested = tuple(item_ids)
        if not requested:
            raise RetryContractError("a retry needs at least one item")
        allowed = set(candidates)
        seen: set[str] = set()
        for entry in requested:
            identifier = _require_identifier("item_id", entry)
            if identifier in seen:
                raise RetryContractError(f"item {identifier!r} is listed twice")
            seen.add(identifier)
            if identifier not in allowed:
                record = failures.for_item(identifier)
                if record is None:
                    reason = "it did not fail in this run"
                elif not record.retryable:
                    reason = "its failure is not retryable"
                else:  # pragma: no cover - covered by the branches above
                    reason = "it is not a retry candidate"
                raise RetryContractError(f"cannot retry {identifier!r}: {reason}")
        ordered = tuple(entry for entry in candidates if entry in seen)
        return cls(snapshot=snapshot, item_ids=ordered)

    @property
    def snapshot_id(self) -> str:
        return self.snapshot.snapshot_id

    @property
    def count(self) -> int:
        return len(self.item_ids)


# --------------------------------------------------------------------------- #
# Job events
# --------------------------------------------------------------------------- #


class JobEventKind(Enum):
    """What a worker may report. Producing these is Tk-free; rendering them is not."""

    STATE_CHANGED = "state_changed"
    STAGE_CHANGED = "stage_changed"
    PROGRESS = "progress"
    CURRENT_ITEM = "current_item"
    IMPORT_COUNT = "import_count"
    WARNING = "warning"
    FAILURE = "failure"
    OUTPUT_LOCATION = "output_location"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TECHNICAL_DETAIL = "technical_detail"


#: Exactly one of these ends a run. Enforcing "exactly once" over a live stream is
#: Phase 7's work; naming which kinds are terminal is vocabulary.
TERMINAL_EVENT_KINDS = frozenset({JobEventKind.COMPLETED, JobEventKind.CANCELLED})


@dataclass(frozen=True, slots=True)
class JobEvent:
    """One immutable report from a run, timestamped by an injected clock.

    ``message`` is user-facing and validated to stay a single line with no raw
    traceback; ``detail`` is the technical companion and is free to be long. That
    split is what lets one event stream feed both the Summary and Details views
    without the Summary drowning in commands and stack traces.

    ``sequence`` is a per-run counter so ordering survives a queue, a poll, and a
    clock with limited resolution.
    """

    kind: JobEventKind
    run_id: str
    sequence: int
    timestamp: float
    message: str = ""
    detail: str = ""
    state: JobState | None = None
    stage: str | None = None
    item_id: str | None = None
    completed: int | None = None
    total: int | None = None
    count: int | None = None
    location: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, JobEventKind):
            raise JobContractError(
                f"kind must be a JobEventKind, got {type(self.kind).__name__}")
        object.__setattr__(self, "run_id", _require_identifier("run_id", self.run_id))
        object.__setattr__(self, "sequence", _require_index("sequence", self.sequence))
        object.__setattr__(self, "timestamp", _require_timestamp("timestamp", self.timestamp))
        object.__setattr__(
            self, "message", _require_display_safe("message", self.message, allow_blank=True))
        if not isinstance(self.detail, str):
            raise JobContractError("detail must be a string")

        if self.state is not None and not isinstance(self.state, JobState):
            raise JobContractError("state must be a JobState")
        if self.stage is not None:
            object.__setattr__(self, "stage", _require_identifier("stage", self.stage))
        if self.item_id is not None:
            object.__setattr__(self, "item_id", _require_identifier("item_id", self.item_id))
        for name in ("completed", "total", "count"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _require_index(name, value))
        if self.location is not None:
            if not isinstance(self.location, (str, Path)):
                raise JobContractError("location must be a path")
            candidate = Path(self.location)
            if not candidate.is_absolute():
                raise JobContractError(
                    f"location must be absolute: {str(candidate)!r}")
            object.__setattr__(self, "location", candidate)

        self._require_payload()

    def _require_payload(self) -> None:
        kind = self.kind
        if kind is JobEventKind.STATE_CHANGED and self.state is None:
            raise JobContractError("a state_changed event must carry the new state")
        if kind is JobEventKind.STAGE_CHANGED and self.stage is None:
            raise JobContractError("a stage_changed event must carry the stage")
        if kind is JobEventKind.PROGRESS:
            if self.completed is None:
                raise JobContractError("a progress event must carry completed")
            if self.total is not None and self.completed > self.total:
                raise JobContractError(
                    f"progress {self.completed} exceeds total {self.total}")
        if kind is JobEventKind.CURRENT_ITEM and self.item_id is None:
            raise JobContractError("a current_item event must carry the item id")
        if kind is JobEventKind.IMPORT_COUNT and self.count is None:
            raise JobContractError("an import_count event must carry the count")
        if kind in (JobEventKind.WARNING, JobEventKind.FAILURE) and not self.message:
            raise JobContractError(f"a {kind.value} event must carry a user-facing message")
        if kind is JobEventKind.OUTPUT_LOCATION and self.location is None:
            raise JobContractError("an output_location event must carry the location")
        if kind is JobEventKind.COMPLETED:
            if self.state not in _ENDINGS:
                raise JobContractError(
                    "a completed event must carry succeeded, completed_with_failures "
                    "or failed")
        if kind is JobEventKind.CANCELLED and self.state not in (None, JobState.CANCELLED):
            raise JobContractError("a cancelled event may only carry the cancelled state")
        if kind is JobEventKind.TECHNICAL_DETAIL and not self.detail.strip():
            raise JobContractError("a technical_detail event must carry detail")

    @property
    def is_terminal(self) -> bool:
        return self.kind in TERMINAL_EVENT_KINDS


# --------------------------------------------------------------------------- #
# The cooperative run controller — Phase 5
#
# Everything above is vocabulary: values that describe a run without owning one.
# This is the one object that *owns* a run's state, and it owns exactly that. It
# starts no thread, runs no work, touches no widget and reads no disk; a worker
# someone else started calls into it, and a UI someone else built reads it.
# --------------------------------------------------------------------------- #

#: A technical detail is allowed to be long, but not unbounded — it travels into a
#: snapshot that a UI may render. Anything past this is truncated rather than
#: refused, because losing the first two thousand characters of a diagnostic to a
#: validation error helps nobody.
MAX_FAILURE_DETAIL = 2000


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    """One internally consistent moment of a run, safe to read from any thread.

    Every field is a plain immutable value. No lock, condition, event, callback,
    exception object or live collection is reachable from here, so holding one
    while the controller moves on cannot show a half-changed run — the snapshot
    you have is the run as it was, permanently.

    The invariants below are enforced rather than assumed, which is what makes
    "cancelled" trustworthy: a snapshot cannot claim :attr:`JobState.CANCELLED`
    unless a worker actually acknowledged the cancellation at a checkpoint.
    """

    run_id: str
    state: JobState
    revision: int = 0
    pause_requested: bool = False
    cancel_requested: bool = False
    cancel_acknowledged: bool = False
    failure_message: str = ""
    failure_detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _require_identifier("run_id", self.run_id))
        if not isinstance(self.state, JobState):
            raise JobContractError(
                f"state must be a JobState, got {type(self.state).__name__}")
        object.__setattr__(self, "revision", _require_index("revision", self.revision))
        for name in ("pause_requested", "cancel_requested", "cancel_acknowledged"):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise JobContractError(f"{name} must be a bool, got {type(value).__name__}")
        object.__setattr__(
            self,
            "failure_message",
            _require_display_safe("failure_message", self.failure_message, allow_blank=True),
        )
        if not isinstance(self.failure_detail, str):
            raise JobContractError("failure_detail must be a string")

        expected_pause = self.state in (JobState.PAUSE_REQUESTED, JobState.PAUSED)
        if self.pause_requested is not expected_pause:
            raise JobContractError(
                f"pause_requested must be {expected_pause} in {self.state.value}")
        if self.cancel_acknowledged and not self.cancel_requested:
            raise JobContractError(
                "a cancellation cannot be acknowledged without having been requested")
        if self.state is JobState.CANCEL_REQUESTED and not self.cancel_requested:
            raise JobContractError("cancel_requested must be set in cancel_requested")
        if self.state is JobState.CANCELLED and not self.cancel_acknowledged:
            raise JobContractError(
                "a run is cancelled only once a worker acknowledged it at a checkpoint; "
                "requesting cancellation is not acknowledgement")
        if self.state is JobState.FAILED and not self.failure_message:
            raise JobContractError("a failed run must say why: record a message")
        if self.state is not JobState.FAILED and (self.failure_message or self.failure_detail):
            raise JobContractError(
                f"a {self.state.value} run carries no failure information")

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def is_running(self) -> bool:
        return self.state is JobState.RUNNING

    @property
    def is_paused(self) -> bool:
        """The worker has actually stopped at a checkpoint — not merely been asked to."""
        return self.state is JobState.PAUSED

    @property
    def pause_pending(self) -> bool:
        """``Pause requested``: asked for, and truthfully not yet acknowledged."""
        return self.state is JobState.PAUSE_REQUESTED

    @property
    def inputs_locked(self) -> bool:
        return self.state in INPUT_LOCKED_STATES

    @property
    def succeeded(self) -> bool:
        return self.state in (JobState.SUCCEEDED, JobState.COMPLETED_WITH_FAILURES)

    @property
    def cancelled(self) -> bool:
        return self.state is JobState.CANCELLED

    @property
    def failed(self) -> bool:
        return self.state is JobState.FAILED


def _bounded_detail(value: object) -> str:
    """Accept technical text; refuse a live exception object.

    Passing the exception itself is the easy mistake, and it is the one that puts a
    mutable object with live traceback frames into a value that crosses threads.
    Refusing it here means the caller writes ``f"{type(exc).__name__}: {exc}"`` once,
    which is also what every existing tool already does.
    """
    if isinstance(value, BaseException):
        raise JobContractError(
            "pass technical text, not the exception object: an exception is mutable "
            "and carries live frames, so it must not enter a snapshot")
    if not isinstance(value, str):
        raise JobContractError(
            f"failure detail must be a string, got {type(value).__name__}")
    if len(value) > MAX_FAILURE_DETAIL:
        return value[:MAX_FAILURE_DETAIL - 1].rstrip() + "…"
    return value


class JobController:
    """One run's cooperative state: pause, resume, cancel, and how it ended.

    **Cooperative, never forced.** Pause and cancel are *requests*. This object
    suspends no thread and terminates no process; it changes what the next
    checkpoint does. That is why ``PAUSE_REQUESTED`` and ``CANCEL_REQUESTED`` are
    first-class states — so a UI can honestly say "Pause requested" while an
    indivisible stage keeps running, instead of claiming an ``ffmpeg`` call stopped
    the instant a button was pressed.

    **One run, one controller.** Reaching a terminal state ends it. There is no
    ``reset``: reviving a finished run by clearing a flag is exactly how a stale
    cancellation ends up stopping fresh work.

    Typical worker shape, unchanged from what the existing tools already write::

        try:
            for chapter in chapters:
                controller.checkpoint()       # pauses here, or raises here
                convert(chapter)
            controller.succeed()
        except ConversionCancelled:
            cleanup()                          # the worker's own, first
            controller.finish_cancelled()      # then the run is truly cancelled
        except Exception as exc:
            controller.fail("Conversion failed.", f"{type(exc).__name__}: {exc}")

    A worker written against :func:`~shared.cancellation.raise_if_cancelled` needs
    no rewrite either: :meth:`cancel_check` has exactly the shape that function
    expects, so ``raise_if_cancelled(controller.cancel_check)`` works.

    **Thread safety.** Every command may be called from any thread. State lives
    behind one :class:`threading.Condition` built on a deliberately *non-reentrant*
    lock, so an accidental re-entry deadlocks a test rather than silently
    succeeding. No listener is ever called while that lock is held.
    """

    __slots__ = (
        "_run_id", "_condition", "_state", "_revision", "_cancel_requested",
        "_cancel_acknowledged", "_failure_message", "_failure_detail", "_listener",
    )

    def __init__(
        self,
        run_id: str,
        *,
        listener: "Callable[[JobSnapshot], Any] | None" = None,
    ) -> None:
        if listener is not None and not callable(listener):
            raise JobContractError("listener must be callable")
        self._run_id = _require_identifier("run_id", run_id)
        # A plain Lock, not the default RLock: re-entering from a listener is a bug,
        # and a bug that deadlocks a test is worth far more than one that does not.
        self._condition = threading.Condition(threading.Lock())
        self._state = JobState.IDLE
        self._revision = 0
        self._cancel_requested = False
        self._cancel_acknowledged = False
        self._failure_message = ""
        self._failure_detail = ""
        self._listener = listener

    # -- reading ----------------------------------------------------------- #

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def state(self) -> JobState:
        with self._condition:
            return self._state

    @property
    def revision(self) -> int:
        with self._condition:
            return self._revision

    @property
    def is_terminal(self) -> bool:
        with self._condition:
            return self._state in TERMINAL_STATES

    @property
    def is_running(self) -> bool:
        with self._condition:
            return self._state is JobState.RUNNING

    @property
    def pause_requested(self) -> bool:
        with self._condition:
            return self._state in (JobState.PAUSE_REQUESTED, JobState.PAUSED)

    @property
    def cancel_acknowledged(self) -> bool:
        with self._condition:
            return self._cancel_acknowledged

    def snapshot(self) -> JobSnapshot:
        """The run as it is right now. Reading changes nothing and blocks nobody."""
        with self._condition:
            return self._snapshot_locked()

    def cancel_check(self) -> bool:
        """Whether cancellation has been requested — the existing ``CancelCheck`` shape.

        Hand this straight to ``raise_if_cancelled`` or to any worker already written
        against a ``threading.Event().is_set``. It reports the *request*, not the
        acknowledgement, which is exactly what the old predicate always meant.
        """
        with self._condition:
            return self._cancel_requested

    # -- commands ---------------------------------------------------------- #

    def start(self) -> JobSnapshot:
        """Begin the run. Legal once, from ``IDLE``.

        Starting a second time raises: a controller belongs to one run, and a
        terminal run may never be revived by starting it again.
        """
        return self._command(JobState.RUNNING, allowed_from=(JobState.IDLE,), strict=True)

    def request_pause(self) -> JobSnapshot:
        """Ask the worker to pause at its next safe checkpoint.

        Truthful by construction: this reaches ``PAUSE_REQUESTED`` and stops there.
        Only the worker, arriving at :meth:`checkpoint`, can make it ``PAUSED``.

        A no-op — not an error — when there is nothing to pause: before the run
        starts, while already pausing or paused, once cancellation has been
        requested (cancel outranks pause), and after the run has ended. A disabled
        button should not raise.
        """
        return self._command(JobState.PAUSE_REQUESTED, allowed_from=(JobState.RUNNING,))

    def resume(self) -> JobSnapshot:
        """Return a paused or pausing run to ``RUNNING`` and wake any waiter.

        A no-op when the run is not pausing or paused, so it can never resurrect
        work that was cancelled, failed or completed.
        """
        return self._command(
            JobState.RUNNING, allowed_from=(JobState.PAUSE_REQUESTED, JobState.PAUSED))

    def request_cancel(self) -> JobSnapshot:
        """Ask the run to stop at its next checkpoint. Idempotent, from any thread.

        Cancel outranks pause: it wakes a worker waiting in :meth:`checkpoint`, and
        that worker re-checks cancellation before it re-checks pause.

        Requested **before** the run starts, the flag is recorded while the state
        stays ``IDLE`` — there is nothing running to cancel yet, and the first
        checkpoint after :meth:`start` will honour it. Requested **after** the run
        has ended it does nothing at all, because a finished run must not start
        describing itself as cancelled.
        """
        with self._condition:
            if self._state in TERMINAL_STATES:
                return self._snapshot_locked()
            changed = not self._cancel_requested
            self._cancel_requested = True
            if self._state in (
                    JobState.RUNNING, JobState.PAUSE_REQUESTED, JobState.PAUSED):
                # One observable change, so one revision and one notification: the
                # state move carries the flag with it.
                self._set_locked(JobState.CANCEL_REQUESTED)
                changed = True
            elif changed:
                # Requested before the run started: the flag moved, the state did not.
                self._revision += 1
                self._condition.notify_all()
            snapshot = self._snapshot_locked()
        if changed:
            self._dispatch(snapshot)
        return snapshot

    # -- the worker-facing checkpoint --------------------------------------- #

    def checkpoint(self) -> None:
        """The cooperative boundary. Returns, blocks, or raises.

        * Running — returns immediately. This is the common path and costs one
          uncontended lock acquisition, so it is safe between chapters or chunks.
        * Pause requested — acknowledges it by moving to ``PAUSED``, then waits on
          the condition. Waiting **releases the lock**, so the UI can still read a
          snapshot, resume, or cancel while the worker sleeps. There is no polling,
          no sleep and no timeout: the worker is woken, not checked on.
        * Cancelled — records the acknowledgement exactly once and raises
          :class:`~shared.cancellation.ConversionCancelled`, so the worker's own
          ``try/finally`` cleanup runs before the run settles.
        * Terminal — returns. The run is over; a late checkpoint is not an error.

        Every wake re-checks everything from the top, so a spurious wake-up simply
        waits again and a cancel that arrives during a pause is honoured on the
        next pass rather than being lost.
        """
        while True:
            paused: JobSnapshot | None = None
            cancelled: JobSnapshot | None = None
            with self._condition:
                if self._state in TERMINAL_STATES:
                    return
                if self._cancel_requested:
                    # Cancel outranks pause, and is checked first for that reason.
                    if self._state is not JobState.CANCEL_REQUESTED:
                        self._set_locked(JobState.CANCEL_REQUESTED)
                    self._acknowledge_locked()
                    cancelled = self._snapshot_locked()
                elif self._state is JobState.PAUSE_REQUESTED:
                    self._set_locked(JobState.PAUSED)
                    paused = self._snapshot_locked()
                elif self._state is JobState.PAUSED:
                    self._condition.wait()
                    continue
                else:
                    return
            # The lock is released here, which is why a listener may safely call
            # back into this controller.
            if cancelled is not None:
                self._dispatch(cancelled)
                raise ConversionCancelled("Cancelled.")
            self._dispatch(paused)

    # -- terminal settlement ------------------------------------------------ #

    def succeed(self) -> JobSnapshot:
        """Settle the run as ``SUCCEEDED``. Exactly one terminal result may win."""
        return self._settle(JobState.SUCCEEDED)

    def complete_with_failures(self) -> JobSnapshot:
        """Settle as ``COMPLETED_WITH_FAILURES``: it finished, some items did not."""
        return self._settle(JobState.COMPLETED_WITH_FAILURES)

    def fail(self, message: str, detail: str = "") -> JobSnapshot:
        """Settle the run as ``FAILED``, with a display-safe reason.

        The message is validated *before* the state moves, so a badly formed reason
        cannot leave a run half-settled, and the detail refuses a live exception.
        """
        safe_message = _require_display_safe("failure message", message)
        safe_detail = _bounded_detail(detail)
        return self._settle(
            JobState.FAILED, failure=(safe_message, safe_detail))

    def finish_cancelled(self) -> JobSnapshot:
        """Settle the run as ``CANCELLED`` — only after the worker acknowledged it.

        Called by the worker once its own cleanup is done, which is what makes
        ``CANCELLED`` mean "it has actually stopped" rather than "someone clicked
        Cancel". Refuses outright if no checkpoint ever observed the cancellation,
        because a fabricated acknowledgement is worse than a loud error.
        """
        with self._condition:
            if not self._cancel_acknowledged:
                raise JobContractError(
                    "the worker has not acknowledged cancellation at a checkpoint; a "
                    "run may not be reported cancelled until it has actually stopped")
        return self._settle(JobState.CANCELLED)

    # -- internals ---------------------------------------------------------- #

    def _command(
        self,
        proposed: JobState,
        *,
        allowed_from: tuple[JobState, ...],
        strict: bool = False,
    ) -> JobSnapshot:
        """Apply one UI command, or do nothing when it does not apply.

        ``strict`` is for :meth:`start`, where "you already started" is a programming
        error worth raising. The pause/resume commands are buttons, and a button
        pressed in a state where it means nothing should be inert, not explosive.
        """
        with self._condition:
            if self._state not in allowed_from:
                if strict:
                    require_legal_transition(self._state, proposed)
                return self._snapshot_locked()
            self._set_locked(proposed)
            snapshot = self._snapshot_locked()
        self._dispatch(snapshot)
        return snapshot

    def _settle(
        self, proposed: JobState, failure: tuple[str, str] | None = None) -> JobSnapshot:
        with self._condition:
            # ``require_legal_transition`` inside ``_set_locked`` is what makes a
            # second terminal result impossible: every terminal state maps to an
            # empty set of successors, so the second attempt raises rather than
            # replacing the first.
            self._set_locked(proposed)
            if failure is not None:
                self._failure_message, self._failure_detail = failure
            snapshot = self._snapshot_locked()
        self._dispatch(snapshot)
        return snapshot

    def _set_locked(self, proposed: JobState) -> None:
        """The single authority for changing state. Nothing else assigns ``_state``.

        Every move is checked against the frozen Phase 1 table first, so an illegal
        transition cannot reach the attribute by any path — including a future one
        somebody adds without reading this docstring.
        """
        require_legal_transition(self._state, proposed)
        self._state = proposed
        self._revision += 1
        # Waking on every state change means no waiter can miss the one it needed.
        self._condition.notify_all()

    def _acknowledge_locked(self) -> bool:
        """Record that a worker observed the cancellation. At most once per run."""
        if self._cancel_acknowledged:
            return False
        self._cancel_acknowledged = True
        self._revision += 1
        return True

    def _snapshot_locked(self) -> JobSnapshot:
        return JobSnapshot(
            run_id=self._run_id,
            state=self._state,
            revision=self._revision,
            pause_requested=self._state in (JobState.PAUSE_REQUESTED, JobState.PAUSED),
            cancel_requested=self._cancel_requested,
            cancel_acknowledged=self._cancel_acknowledged,
            failure_message=self._failure_message,
            failure_detail=self._failure_detail,
        )

    def _dispatch(self, snapshot: "JobSnapshot | None") -> None:
        """Call the listener with the lock released, or not at all."""
        if snapshot is None or self._listener is None:
            return
        self._listener(snapshot)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"JobController(run_id={self._run_id!r}, state={self.state.value})"


# --------------------------------------------------------------------------- #
# Local validators
#
# Deliberately duplicated in name only: these delegate nothing to the filesystem
# and exist so this module raises JobContractError rather than leaking the
# importing module's error type for a job-side field.
# --------------------------------------------------------------------------- #


def _require_display_safe(field_name: str, value: object, *, allow_blank: bool = False) -> str:
    """Reuse the importing module's one display-safety rule, raise this module's error.

    The rule lives in exactly one place — duplicating it is how two surfaces end up
    disagreeing about what "concise" means — but a job-side field that breaks it
    should still fail as a :class:`JobContractError`.
    """
    try:
        return ensure_display_safe(field_name, value, allow_blank=allow_blank)
    except ImportContractError as exc:
        raise JobContractError(str(exc)) from exc


def _require_identifier(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise JobContractError(
            f"{field_name} must be a string, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise JobContractError(f"{field_name} must not be blank")
    if any(character.isspace() for character in text):
        raise JobContractError(f"{field_name} must not contain whitespace: {text!r}")
    return text


def _require_index(field_name: str, value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise JobContractError(f"{field_name} must be an int, got {type(value).__name__}")
    if value < minimum:
        raise JobContractError(f"{field_name} must be >= {minimum}, got {value}")
    return value


def _require_timestamp(field_name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobContractError(f"{field_name} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise JobContractError(f"{field_name} must be finite, got {value!r}")
    if number < 0:
        raise JobContractError(f"{field_name} must not be negative, got {value!r}")
    return number
