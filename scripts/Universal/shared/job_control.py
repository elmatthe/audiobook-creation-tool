"""Immutable vocabulary for shared job control — v0.6.0 Drop 3 (Plan 3), Phase 1.

Like :mod:`shared.importing`, this module is **contracts only**: the states a run
can be in, the transitions between them that are legal, the frozen snapshot a run
is judged by, the record of what failed, the request to retry only those, and the
typed events a worker may report.

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
No controller, no locks around state, no pause/resume waiting, no cancel wake-up,
no threads, no queues, no polling, no ETA arithmetic, no progress widget, no Tk,
and no output placement of any kind. Phases 5–8 own those. In particular this
module reserves no run directory and defines no output-policy type: a destination
choice reaches a run only inside a later adopter's frozen tool options, and Plan 2
remains the only owner of paths.

Truthfulness
------------
Pause and cancel are *requests*. ``PAUSE_REQUESTED`` and ``CANCEL_REQUESTED`` exist
as first-class states precisely so the UI can say "Pause requested" while an
indivisible stage keeps running, instead of claiming an OS call stopped instantly.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Any

from shared import config as _config
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
