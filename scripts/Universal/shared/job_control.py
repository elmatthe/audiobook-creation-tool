"""Shared job control — v0.6.0 Drop 3 (Plan 3), Phases 1, 5, 6 and 7.

Phase 1 made this module **contracts only**: the states a run can be in, the
transitions between them that are legal, the frozen snapshot a run is judged by,
the record of what failed, the request to retry only those, and the typed events a
worker may report.

Phase 5 added the one object that *owns* a run — :class:`JobController` — together
with the immutable :class:`JobSnapshot` it hands out. It is still the case that
nothing here starts a thread, runs work, touches a widget or reads a disk: the
controller coordinates a worker that somebody else started, and its whole
concurrency budget is one :class:`threading.Condition` guarding its own state.

Phase 6 closed the loop around a run: :func:`capture_run` freezes one configuration
at the moment a run is accepted, :func:`is_locked` and :func:`is_available` derive
what the UI may still touch while it runs, and :class:`RunResult` settles what
became of every occurrence — from which :class:`RetryRequest` re-runs only the
retryable failures, against that same frozen snapshot. All of it is pure: no
thread, no widget, no filesystem, and no output placement.

Item failure is not job failure
-------------------------------
A run that lost some items but orchestrated fine is ``COMPLETED_WITH_FAILURES``, not
``FAILED``; ``FAILED`` is reserved for a run that broke as a whole and is recorded as
an item-less :class:`FailureRecord`. Keeping those apart is what makes Retry Failed
meaningful, and :class:`RunResult` derives the distinction rather than letting a
caller assert it.

Phase 7 made a run *legible*. :class:`JobReporter` produces the typed events,
:class:`JobEventStream` decides which of them belong to the run at all,
:func:`summary_lines` and :func:`detail_lines` project the two views a person reads,
:class:`ProgressTracker` says what a progress bar may honestly show, and
:class:`EtaEstimator` answers "how much longer" — or, far more often,
``Calculating…``. All of it is still pure: an injected clock, no display, no disk.

What lives here
---------------
``JobState`` and ``LEGAL_TRANSITIONS`` — the complete state vocabulary and the
transition table, so an illegal move is rejected deterministically rather than
being an emergent property of whoever wrote the controller. ``freeze_options`` —
the deep copy-and-freeze that makes a tool's options safe to hand to a worker.
``RunSnapshot`` — one run's single source of truth. ``FailureRecord`` /
``FailureLog`` / ``RetryRequest`` — what went wrong and what may be retried.
``JobEvent`` — the typed, Tk-free report a worker puts on a queue — together with
the Phase 7 layer that produces, filters, projects, measures and estimates from it.

What deliberately does **not** live here
---------------------------------------
No thread, no queue, no polling, no widget, no Tk, no second logger, and no output
placement of any kind. Phase 8 owns the adapters that render any of this. In
particular this module reserves no run directory and defines no output-policy type:
a destination choice reaches a run only inside a later adopter's frozen tool
options, and Plan 2 remains the only owner of paths. The one edge outwards is the
technical-event bridge, which asks ``logging_setup`` for the session logger the
application already opens and creates nothing of its own.

Nothing here reads a clock. Every timestamp and every measured duration arrives
through a clock the caller injected, which is what lets the whole of §6.13 be tested
deterministically without a single sleep.

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
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Any

from shared import config as _config
from shared import logging_setup as _logging_setup
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
    "capture_run",
    "ControlKind",
    "LOCK_MATRIX",
    "is_locked",
    "JobAction",
    "is_available",
    "ItemStatus",
    "ItemOutcome",
    "RunResult",
    "state_message",
    "JobReporter",
    "EventVerdict",
    "JobEventStream",
    "DEFAULT_PUMP_LIMIT",
    "LoggerBridge",
    "SUMMARY_KINDS",
    "SummaryView",
    "summary_lines",
    "detail_lines",
    "project_summary",
    "ProgressMode",
    "ProgressView",
    "ProgressTracker",
    "IDLE_PROGRESS",
    "EtaEstimator",
    "CALCULATING",
    "DEFAULT_MINIMUM_SAMPLES",
    "DEFAULT_SAMPLE_WINDOW",
    "format_duration",
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
# Capture — Phase 6
#
# The moment a run is accepted. Everything a run will ever read is copied here, on
# the caller's own thread, and nothing is ever consulted again.
# --------------------------------------------------------------------------- #


def capture_run(
    *,
    snapshot_id: str,
    files: Any,
    catalog: SupportedTypeCatalog,
    import_options: ImportOptions,
    effective_config: "_config.EffectiveConfig",
    tool_options: Any = None,
    created_at: float = 0.0,
) -> RunSnapshot:
    """Freeze one run's complete configuration. Decision 9A, as a single call.

    *files* may be an :class:`~shared.importing.ImportedFileSnapshot` or anything
    that hands one back from a ``snapshot()`` method — the imported-file manager
    does. It is duck-typed on purpose: this module coordinates a run, and giving it
    an import to reach into would be the beginning of a second manager.

    Everything is copied, not referenced. ``tool_options`` is deep-frozen by
    :func:`freeze_options`, which refuses a widget, a variable, a callable, a
    thread, an open file, a mutable dataclass or a reference cycle rather than
    storing a live handle. The imported list arrives as an already-immutable
    snapshot. The result is the **only** configuration the run and any later retry
    may read: a preference saved, a checkbox toggled, a file added or the list
    cleared afterwards cannot reach it, because nothing consults them again.

    Call this on the thread that owns the widgets, before any worker starts.
    """
    if files is None:
        raise JobContractError("a run needs its imported files")
    if not isinstance(files, ImportedFileSnapshot):
        taker = getattr(files, "snapshot", None)
        if not callable(taker):
            raise JobContractError(
                "files must be an ImportedFileSnapshot or an object offering "
                f"snapshot(), got {type(files).__name__}")
        files = taker()
    return RunSnapshot(
        snapshot_id=snapshot_id,
        files=files,
        catalog=catalog,
        import_options=import_options,
        effective_config=effective_config,
        tool_options={} if tool_options is None else tool_options,
        created_at=created_at,
    )


# --------------------------------------------------------------------------- #
# The lock-state derivation — Phase 6
#
# §8 task 2 asks for a *UI-neutral derivation*, not a per-panel table. That is the
# right shape for this drop: §5.3 forbids any production panel from adopting this
# foundation, so a table of panel and widget names would be a table of names
# nothing may use, and it would drift the moment a panel was redesigned. What §6.11
# actually fixes is a rule about **kinds** of control, and a kind survives a
# redesign. Every member below is traceable to one phrase of that sentence.
# --------------------------------------------------------------------------- #


class ControlKind(Enum):
    """The kinds of control §6.11 distinguishes, and no others."""

    #: The imported-file list and everything that edits it: Add Files, Add Folder,
    #: Remove, Clear, Move Up/Down, and the selection itself.
    IMPORTED_INPUT = "imported_input"
    #: "processing-option controls" — a tool's own settings for the run.
    PROCESSING_OPTION = "processing_option"
    #: Pause, Resume, Cancel. Never an ordinary input, and never locked *as* one.
    JOB_CONTROL = "job_control"
    #: "log tabs" — Summary/Details and any other read-only view switch.
    LOG_VIEW = "log_view"
    #: "progress/status" — read-only reporting.
    PROGRESS_STATUS = "progress_status"
    #: "Open Output" — harmless navigation, not a processing input.
    OPEN_OUTPUT = "open_output"


#: Which kinds a run takes ownership of while it is active. Derived from the Phase 1
#: frozen set rather than restated, so the two can never disagree: if a state joins
#: ``INPUT_LOCKED_STATES``, everything below follows automatically.
_LOCKED_KINDS = frozenset({
    ControlKind.IMPORTED_INPUT,
    ControlKind.PROCESSING_OPTION,
})

#: The complete matrix, materialised so a test can walk every cell. Every kind
#: appears; a kind that is never locked maps to an empty set rather than being
#: absent, because "absent" and "never locked" must not look the same.
LOCK_MATRIX: Mapping[ControlKind, frozenset[JobState]] = MappingProxyType({
    kind: (INPUT_LOCKED_STATES if kind in _LOCKED_KINDS else frozenset())
    for kind in ControlKind
})


def is_locked(kind: ControlKind, state: JobState) -> bool:
    """Whether *kind* is read-only while a run sits in *state*.

    §6.11: inputs and processing options are locked while the job owns them —
    running, pause-requested, paused and cancel-requested. Job controls, log views,
    progress and Open Output are never locked; whether they are *meaningful* is a
    different question, answered by :func:`is_available`.
    """
    if not isinstance(kind, ControlKind):
        raise JobContractError(
            f"kind must be a ControlKind, got {type(kind).__name__}")
    if not isinstance(state, JobState):
        raise JobContractError(
            f"state must be a JobState, got {type(state).__name__}")
    return state in LOCK_MATRIX[kind]


class JobAction(Enum):
    """The run controls whose availability depends on where the run is."""

    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    RETRY_FAILED = "retry_failed"


#: When each action is meaningful. Read straight off the Phase 1 transition table
#: wherever the action *is* a transition, so an action can never be offered for a
#: move the controller would refuse.
_ACTION_STATES: Mapping[JobAction, frozenset[JobState]] = MappingProxyType({
    JobAction.START: frozenset({JobState.IDLE}),
    JobAction.PAUSE: frozenset({JobState.RUNNING}),
    JobAction.RESUME: frozenset({JobState.PAUSE_REQUESTED, JobState.PAUSED}),
    JobAction.CANCEL: frozenset({
        JobState.RUNNING, JobState.PAUSE_REQUESTED, JobState.PAUSED}),
    # §6.14: offered only after a run that finished with something worth retrying.
    JobAction.RETRY_FAILED: frozenset({JobState.COMPLETED_WITH_FAILURES}),
})


def is_available(
    action: JobAction, state: JobState, *, has_retryable: bool = False) -> bool:
    """Whether *action* is meaningful in *state*.

    ``Retry Failed`` additionally requires at least one retryable failure (§6.14) —
    offering it after a run whose only failure was fatal would promise something
    the model cannot deliver.
    """
    if not isinstance(action, JobAction):
        raise JobContractError(
            f"action must be a JobAction, got {type(action).__name__}")
    if not isinstance(state, JobState):
        raise JobContractError(
            f"state must be a JobState, got {type(state).__name__}")
    if not isinstance(has_retryable, bool):
        raise JobContractError("has_retryable must be a bool")
    if state not in _ACTION_STATES[action]:
        return False
    if action is JobAction.RETRY_FAILED:
        return has_retryable
    return True


# --------------------------------------------------------------------------- #
# Item outcomes and the run's disposition — Phase 6
# --------------------------------------------------------------------------- #


class ItemStatus(Enum):
    """What became of one imported occurrence in one run.

    Three answers, all of them derivable and none of them policy. A tool that wants
    to *skip* an item decides that for itself and reports it however its own plan
    says; this drop only distinguishes what it can honestly tell from a snapshot
    and a failure log.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    #: The run ended — usually cancelled — before this occurrence was reached. It is
    #: emphatically not a failure, and §6.14's Retry Failed never offers it.
    NOT_ATTEMPTED = "not_attempted"


@dataclass(frozen=True, slots=True)
class ItemOutcome:
    """One occurrence's result. Produced by :class:`RunResult`, never assembled loose.

    Contradictions are unconstructible rather than merely discouraged: a succeeded
    or unattempted item cannot carry a failure, and a failed one must carry the
    record that says why, for the same occurrence.

    There is deliberately **no output field.** §8's Phase 6 risk gate says to stop
    rather than add a generic output descriptor that would duplicate or contradict
    Plan 2, and an "output" on an item outcome is exactly that descriptor. Where a
    retried or original file lands stays Plan 2's to decide, through the adopting
    plan.
    """

    item_id: str
    status: ItemStatus
    failure: FailureRecord | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _require_identifier("item_id", self.item_id))
        if not isinstance(self.status, ItemStatus):
            raise JobContractError(
                f"status must be an ItemStatus, got {type(self.status).__name__}")
        if self.failure is not None and not isinstance(self.failure, FailureRecord):
            raise JobContractError(
                f"failure must be a FailureRecord, got {type(self.failure).__name__}")
        if self.status is ItemStatus.FAILED:
            if self.failure is None:
                raise JobContractError("a failed item must carry the record that says why")
            if self.failure.item_id != self.item_id:
                raise JobContractError(
                    f"failure for {self.failure.item_id!r} cannot describe {self.item_id!r}")
        elif self.failure is not None:
            raise JobContractError(
                f"a {self.status.value} item carries no failure record")

    @property
    def succeeded(self) -> bool:
        return self.status is ItemStatus.SUCCEEDED

    @property
    def failed(self) -> bool:
        return self.status is ItemStatus.FAILED

    @property
    def retryable(self) -> bool:
        return self.failure is not None and self.failure.retryable


@dataclass(frozen=True, slots=True)
class RunResult:
    """One run's complete, ordered disposition — and the only thing a retry reads.

    Built by :meth:`settle` from three immutable facts: the snapshot the run was
    accepted with, the ordered failures it collected, and which occurrences it
    finished. Everything else is derived, so two counters can never disagree and a
    summary can never contradict the records it summarises.

    **An item failure never forces a job-level failure.** ``FAILED`` here means the
    run itself broke — a fatal, item-less :class:`FailureRecord`. A run that
    orchestrated fine and lost some items reports ``COMPLETED_WITH_FAILURES``, which
    is what makes Retry Failed possible at all (§6.14). Nothing in this class calls
    a controller; the disposition is a value the worker then settles *with*.
    """

    snapshot: RunSnapshot
    failures: FailureLog
    completed_ids: tuple[str, ...] = ()
    state: JobState = JobState.SUCCEEDED

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, RunSnapshot):
            raise JobContractError(
                f"snapshot must be a RunSnapshot, got {type(self.snapshot).__name__}")
        if not isinstance(self.failures, FailureLog):
            raise JobContractError(
                f"failures must be a FailureLog, got {type(self.failures).__name__}")
        if self.failures.snapshot_id != self.snapshot.snapshot_id:
            raise JobContractError(
                f"failure log {self.failures.snapshot_id!r} does not belong to run "
                f"{self.snapshot.snapshot_id!r}")
        if not isinstance(self.state, JobState):
            raise JobContractError(
                f"state must be a JobState, got {type(self.state).__name__}")
        if self.state not in TERMINAL_STATES:
            raise JobContractError(
                f"a run result describes a finished run; {self.state.value} is not "
                "a terminal state")

        known = set(self.snapshot.item_ids)
        failed = {
            entry.item_id for entry in self.failures.records if entry.item_id is not None}
        entries: list[str] = []
        seen: set[str] = set()
        for value in self.completed_ids:
            identifier = _require_identifier("item_id", value)
            if identifier in seen:
                raise JobContractError(f"item {identifier!r} is listed twice as completed")
            seen.add(identifier)
            if identifier not in known:
                raise JobContractError(
                    f"item {identifier!r} does not belong to snapshot "
                    f"{self.snapshot.snapshot_id!r}")
            if identifier in failed:
                raise JobContractError(
                    f"item {identifier!r} cannot have both succeeded and failed")
            entries.append(identifier)
        object.__setattr__(self, "completed_ids", tuple(entries))

        for entry in self.failures.records:
            if entry.item_id is not None and entry.item_id not in known:
                raise JobContractError(
                    f"failed item {entry.item_id!r} does not belong to snapshot "
                    f"{self.snapshot.snapshot_id!r}")

        if self.state is JobState.FAILED and not self.failures.fatal:
            raise JobContractError(
                "a job-level failure must record why it failed as a whole; an item "
                "failure is not a job failure")
        if self.state is JobState.COMPLETED_WITH_FAILURES and not failed:
            raise JobContractError(
                "completed_with_failures needs at least one failed item")
        if self.state is JobState.SUCCEEDED and self.failures.records:
            raise JobContractError(
                "a run that recorded a failure did not simply succeed")

    @classmethod
    def settle(
        cls,
        snapshot: RunSnapshot,
        failures: FailureLog | None = None,
        *,
        completed_ids: Iterable[str] = (),
        cancelled: bool = False,
    ) -> "RunResult":
        """Derive the one terminal disposition this run deserves.

        In order, because the order is the meaning:

        1. **Cancelled** wins outright. A run the user stopped is not a run that
           completed with failures, however many items it had lost by then — and it
           can never be overwritten by completion, because a cancelled result cannot
           be settled again into anything else.
        2. **A fatal failure** — a record with no item — means the run itself broke:
           ``FAILED``.
        3. **Any failed item** means the orchestration finished but the run lost
           something: ``COMPLETED_WITH_FAILURES``, and Retry Failed becomes possible.
        4. Otherwise ``SUCCEEDED``.

        Items that were never reached are neither failed nor completed. They are
        reported as ``NOT_ATTEMPTED`` rather than being invented into failures.
        """
        if not isinstance(snapshot, RunSnapshot):
            raise JobContractError("snapshot must be a RunSnapshot")
        log = FailureLog(snapshot_id=snapshot.snapshot_id) if failures is None else failures
        if not isinstance(cancelled, bool):
            raise JobContractError("cancelled must be a bool")
        if not isinstance(log, FailureLog):
            raise JobContractError("failures must be a FailureLog")

        if cancelled:
            state = JobState.CANCELLED
        elif log.fatal:
            state = JobState.FAILED
        elif any(entry.item_id is not None for entry in log.records):
            state = JobState.COMPLETED_WITH_FAILURES
        else:
            state = JobState.SUCCEEDED
        return cls(
            snapshot=snapshot,
            failures=log,
            completed_ids=tuple(completed_ids),
            state=state,
        )

    @property
    def outcomes(self) -> tuple[ItemOutcome, ...]:
        """Every occurrence, in the order the run was given them.

        Derived on demand from the snapshot and the failure log, so an outcome can
        never drift out of step with the records it was built from. Deliberate
        duplicates stay distinct because everything here is keyed on occurrence id,
        never on a path.
        """
        completed = set(self.completed_ids)
        results: list[ItemOutcome] = []
        for item_id in self.snapshot.item_ids:
            record = self.failures.for_item(item_id)
            if record is not None:
                results.append(ItemOutcome(
                    item_id=item_id, status=ItemStatus.FAILED, failure=record))
            elif item_id in completed:
                results.append(ItemOutcome(item_id=item_id, status=ItemStatus.SUCCEEDED))
            else:
                results.append(
                    ItemOutcome(item_id=item_id, status=ItemStatus.NOT_ATTEMPTED))
        return tuple(results)

    def outcome_for(self, item_id: str) -> ItemOutcome | None:
        identifier = _require_identifier("item_id", item_id)
        for entry in self.outcomes:
            if entry.item_id == identifier:
                return entry
        return None

    @property
    def counts(self) -> Mapping[ItemStatus, int]:
        """Derived, never stored — two counters cannot disagree if there is one."""
        tally: dict[ItemStatus, int] = {status: 0 for status in ItemStatus}
        for entry in self.outcomes:
            tally[entry.status] += 1
        return MappingProxyType(tally)

    @property
    def succeeded_count(self) -> int:
        return self.counts[ItemStatus.SUCCEEDED]

    @property
    def failed_count(self) -> int:
        return self.counts[ItemStatus.FAILED]

    @property
    def not_attempted_count(self) -> int:
        return self.counts[ItemStatus.NOT_ATTEMPTED]

    @property
    def has_retryable(self) -> bool:
        """Whether Retry Failed may be offered at all (§6.14)."""
        return self.failures.has_retryable

    @property
    def retryable_ids(self) -> tuple[str, ...]:
        return self.failures.retryable_ids()

    @property
    def cancelled(self) -> bool:
        return self.state is JobState.CANCELLED

    def retry(self, item_ids: Iterable[str] | None = None) -> "RetryRequest":
        """Build Retry Failed from this result, against the **exact** original snapshot.

        Reads nothing live: not a widget, not the current configuration, not the
        imported-file manager as it stands now. Everything comes from the snapshot
        this run was accepted with and the failures it actually recorded.
        """
        return RetryRequest.from_failures(self.snapshot, self.failures, item_ids)


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


# --------------------------------------------------------------------------- #
# Reporting — Phase 7
#
# Everything from here down turns a run into something a person can read, and does
# it without a display. Production, filtering, projection, progress arithmetic and
# the estimator are all Tk-free values and pure functions; Phase 8 renders them.
#
# The one rule that shapes all of it: a report may not claim more than the run
# actually established. That is why a state-bearing event is minted from the
# controller's own snapshot rather than from a state somebody typed, why progress is
# never rounded up to meet a happy ending, and why the estimate says
# "Calculating…" far more readily than it says a number.
# --------------------------------------------------------------------------- #

#: Shown instead of a number whenever an estimate would not be trustworthy. The same
#: text the cleanup inventory already shows, so the application speaks with one voice
#: (``maintenance.CALCULATING_TEXT``); it is repeated rather than imported because
#: this module has no business depending on the cleanup service.
CALCULATING = "Calculating…"

#: §6.13's reliability policy: at least three comparable completed samples, and never
#: more than the latest twenty.
DEFAULT_MINIMUM_SAMPLES = 3
DEFAULT_SAMPLE_WINDOW = 20

#: How many events one pump takes at most, so a poll cannot be starved by a producer
#: that is faster than the puller. A bound, never a timing assumption.
DEFAULT_PUMP_LIMIT = 256

#: One concise line per state, in one place. Two surfaces that each write their own
#: "Paused" eventually disagree about what pausing means; §6.10's "Pause requested"
#: in particular has to stay word for word, because it is the whole difference
#: between an honest UI and one that claims an indivisible stage stopped.
_STATE_MESSAGES: Mapping[JobState, str] = MappingProxyType({
    JobState.IDLE: "Ready.",
    JobState.RUNNING: "Running.",
    JobState.PAUSE_REQUESTED: "Pause requested.",
    JobState.PAUSED: "Paused.",
    JobState.CANCEL_REQUESTED: "Cancelling…",
    JobState.CANCELLED: "Cancelled.",
    JobState.SUCCEEDED: "Finished.",
    JobState.COMPLETED_WITH_FAILURES: "Finished with failures.",
    JobState.FAILED: "The run failed.",
})


def state_message(state: JobState) -> str:
    """The one concise, display-safe sentence for *state*."""
    if not isinstance(state, JobState):
        raise JobContractError(
            f"state must be a JobState, got {type(state).__name__}")
    return _STATE_MESSAGES[state]


class JobReporter:
    """Produces the typed events of one run. Tk-free, and unable to overclaim.

    **A state is never asserted, only copied.** Every state-bearing event is minted
    from a :class:`JobSnapshot` the controller handed out, so the reporter cannot say
    ``PAUSED`` while an indivisible stage is still running, and cannot say
    ``CANCELLED`` before a worker acknowledged the cancellation at a checkpoint —
    there is simply no snapshot in existence that would let it. That is a stronger
    guarantee than checking a claim after the fact, because the invalid event is
    never constructed.

    **Ordering.** ``sequence`` is allocated atomically and is the ordering authority;
    the timestamp is only for display, since an injected clock may have coarse
    resolution. The lock covers the counter and nothing else: neither the clock nor
    the publisher is called while it is held, because §5.4 forbids holding a lock
    across user code. One consequence is worth stating plainly — a reporter shared by
    several threads may hand its queue two events in the opposite order to their
    numbers, and :class:`JobEventStream` will refuse the later arrival rather than
    file it in the wrong place. One run reports from one producer.
    """

    __slots__ = ("_run_id", "_clock", "_publish", "_item_ids", "_lock", "_sequence")

    def __init__(
        self,
        run_id: str,
        *,
        clock: Callable[[], float],
        publish: "Callable[[JobEvent], Any] | None" = None,
        item_ids: "Iterable[str] | None" = None,
    ) -> None:
        if not callable(clock):
            raise JobContractError("clock must be callable")
        if publish is not None and not callable(publish):
            raise JobContractError("publish must be callable")
        self._run_id = _require_identifier("run_id", run_id)
        self._clock = clock
        self._publish = publish
        self._item_ids = None if item_ids is None else frozenset(item_ids)
        self._lock = threading.Lock()
        self._sequence = 0

    @classmethod
    def for_run(
        cls,
        snapshot: RunSnapshot,
        *,
        clock: Callable[[], float],
        publish: "Callable[[JobEvent], Any] | None" = None,
    ) -> "JobReporter":
        """Bind a reporter to a frozen run: its id, and the occurrences it may name."""
        if not isinstance(snapshot, RunSnapshot):
            raise JobContractError(
                f"snapshot must be a RunSnapshot, got {type(snapshot).__name__}")
        return cls(
            snapshot.snapshot_id, clock=clock, publish=publish,
            item_ids=snapshot.item_ids)

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def sequence(self) -> int:
        """The number the next event will carry."""
        with self._lock:
            return self._sequence

    # -- production ------------------------------------------------------- #

    def state_changed(self, snapshot: JobSnapshot, message: str = "") -> "JobEvent":
        state = self._require_own_snapshot(snapshot)
        return self._emit(
            JobEventKind.STATE_CHANGED, state=state,
            message=message or state_message(state))

    def stage_changed(self, stage: str, message: str = "", detail: str = "") -> "JobEvent":
        return self._emit(
            JobEventKind.STAGE_CHANGED, stage=stage, message=message, detail=detail)

    def progress(
        self,
        completed: int,
        total: "int | None" = None,
        *,
        item_id: "str | None" = None,
        stage: "str | None" = None,
        message: str = "",
    ) -> "JobEvent":
        return self._emit(
            JobEventKind.PROGRESS, completed=completed, total=total,
            item_id=self._require_item(item_id), stage=stage, message=message)

    def current_item(self, item_id: str, message: str = "") -> "JobEvent":
        return self._emit(
            JobEventKind.CURRENT_ITEM, item_id=self._require_item(item_id),
            message=message)

    def import_count(self, count: int, message: str = "") -> "JobEvent":
        return self._emit(JobEventKind.IMPORT_COUNT, count=count, message=message)

    def warning(self, message: str, detail: str = "") -> "JobEvent":
        return self._emit(JobEventKind.WARNING, message=message, detail=detail)

    def failure(
        self,
        message: str,
        detail: str = "",
        *,
        item_id: "str | None" = None,
        stage: "str | None" = None,
    ) -> "JobEvent":
        """One thing that went wrong. It records; it does not end the run.

        Ending a run is :class:`JobController`'s, and an item failure is not a job
        failure (§6.14) — reporting one changes no state at all.
        """
        return self._emit(
            JobEventKind.FAILURE, message=message, detail=detail,
            item_id=self._require_item(item_id), stage=stage)

    def output_location(self, location: "Path | str", message: str = "") -> "JobEvent":
        """Report a location the caller supplied.

        It is named and nothing more: this creates no directory, reserves no run,
        and does not ask the filesystem whether the location exists. Where output
        goes stays Plan 2's, through the adopting plan.
        """
        return self._emit(
            JobEventKind.OUTPUT_LOCATION, location=location, message=message)

    def technical(self, detail: str) -> "JobEvent":
        """A diagnostic for Details and the session log. Never a Summary line."""
        return self._emit(JobEventKind.TECHNICAL_DETAIL, detail=detail)

    def completed(self, snapshot: JobSnapshot, message: str = "") -> "JobEvent":
        """The one ending event for a run that finished, however it finished."""
        state = self._require_own_snapshot(snapshot)
        if state not in _ENDINGS:
            raise JobContractError(
                f"a run in {state.value} has not completed; the controller settles "
                "the run before it is reported")
        return self._emit(
            JobEventKind.COMPLETED, state=state,
            message=message or snapshot.failure_message or state_message(state))

    def cancelled(self, snapshot: JobSnapshot, message: str = "") -> "JobEvent":
        """The one ending event for a run the user stopped.

        Only an acknowledged cancellation can produce this, because only an
        acknowledged cancellation can produce the snapshot it needs.
        """
        state = self._require_own_snapshot(snapshot)
        if state is not JobState.CANCELLED:
            raise JobContractError(
                f"a run in {state.value} is not cancelled; a cancellation is reported "
                "once a worker has acknowledged it and finished its own cleanup")
        return self._emit(
            JobEventKind.CANCELLED, state=state,
            message=message or state_message(state))

    # -- internals -------------------------------------------------------- #

    def _require_own_snapshot(self, snapshot: object) -> JobState:
        if not isinstance(snapshot, JobSnapshot):
            raise JobContractError(
                "a state is reported from the controller's own JobSnapshot, not from "
                f"a bare value: got {type(snapshot).__name__}")
        if snapshot.run_id != self._run_id:
            raise JobContractError(
                f"snapshot belongs to run {snapshot.run_id!r}, not {self._run_id!r}")
        return snapshot.state

    def _require_item(self, item_id: "str | None") -> "str | None":
        if item_id is None or self._item_ids is None:
            return item_id
        identifier = _require_identifier("item_id", item_id)
        if identifier not in self._item_ids:
            raise JobContractError(
                f"occurrence {identifier!r} does not belong to run {self._run_id!r}")
        return identifier

    def _emit(self, kind: JobEventKind, **payload: Any) -> "JobEvent":
        # The clock is the caller's code and the publisher is the caller's queue.
        # Neither is touched while the counter lock is held.
        at = self._clock()
        with self._lock:
            number = self._sequence
            self._sequence = number + 1
        entry = JobEvent(
            kind=kind, run_id=self._run_id, sequence=number, timestamp=at, **payload)
        if self._publish is not None:
            self._publish(entry)
        return entry

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"JobReporter(run_id={self._run_id!r}, sequence={self.sequence})"


class EventVerdict(Enum):
    """What a stream did with an event, and why."""

    ACCEPTED = "accepted"
    #: It belongs to a different run. Nothing is rendered and nothing is logged.
    STALE_RUN = "stale_run"
    #: It names an occurrence this run was never given.
    UNKNOWN_ITEM = "unknown_item"
    #: The run already ended. A late report cannot change what happened.
    AFTER_TERMINAL = "after_terminal"
    #: A run ends once. The second ending is refused, not overwritten.
    DUPLICATE_TERMINAL = "duplicate_terminal"
    #: Its number is not after the last one accepted, so it cannot be placed.
    OUT_OF_ORDER = "out_of_order"


class JobEventStream:
    """The accepted history of one run — and the gate that decides what gets in.

    Four things can only be judged against a run rather than against an event:
    whether it belongs to *this* run, whether it names an occurrence this run
    actually has, whether the run has already ended, and where it goes in the order.
    This is where those four are decided, once, so that every consumer downstream —
    Summary, Details, progress, the session log — sees exactly the same story.

    A rejected event is inert: it is not stored in the history, not projected, and
    not forwarded to the logger. It is kept in :attr:`rejected` only so a test or a
    developer can see what was turned away and why.

    Nothing here is a timing assumption. Draining ends when the source runs out or
    the caller's bound is reached — never at a queue size, a sleep or a deadline.
    """

    __slots__ = ("_run_id", "_item_ids", "_bridge", "_events", "_rejected",
                 "_terminal", "_last_sequence")

    def __init__(
        self,
        run_id: str,
        *,
        item_ids: "Iterable[str] | None" = None,
        bridge: "LoggerBridge | None" = None,
    ) -> None:
        if bridge is not None and not isinstance(bridge, LoggerBridge):
            raise JobContractError(
                f"bridge must be a LoggerBridge, got {type(bridge).__name__}")
        self._run_id = _require_identifier("run_id", run_id)
        self._item_ids = None if item_ids is None else frozenset(item_ids)
        self._bridge = bridge
        self._events: list[JobEvent] = []
        self._rejected: list[tuple[JobEvent, EventVerdict]] = []
        self._terminal: "JobEvent | None" = None
        self._last_sequence = -1

    @classmethod
    def for_run(
        cls, snapshot: RunSnapshot, *, bridge: "LoggerBridge | None" = None,
    ) -> "JobEventStream":
        if not isinstance(snapshot, RunSnapshot):
            raise JobContractError(
                f"snapshot must be a RunSnapshot, got {type(snapshot).__name__}")
        return cls(snapshot.snapshot_id, item_ids=snapshot.item_ids, bridge=bridge)

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def events(self) -> tuple["JobEvent", ...]:
        """Everything accepted, in the order it was accepted."""
        return tuple(self._events)

    @property
    def rejected(self) -> tuple[tuple["JobEvent", EventVerdict], ...]:
        return tuple(self._rejected)

    @property
    def terminal(self) -> "JobEvent | None":
        return self._terminal

    @property
    def is_closed(self) -> bool:
        """Whether the one terminal event has been accepted."""
        return self._terminal is not None

    def accept(self, entry: "JobEvent") -> EventVerdict:
        """Judge one event. Accepting is the only branch with a side effect."""
        if not isinstance(entry, JobEvent):
            raise JobContractError(
                f"a stream carries JobEvent, got {type(entry).__name__}")
        verdict = self._judge(entry)
        if verdict is not EventVerdict.ACCEPTED:
            self._rejected.append((entry, verdict))
            return verdict

        self._events.append(entry)
        self._last_sequence = entry.sequence
        if entry.is_terminal:
            self._terminal = entry
        if self._bridge is not None:
            self._bridge.forward(entry)
        return verdict

    def drain(
        self, source: "Iterable[JobEvent]", *, limit: "int | None" = None,
    ) -> tuple[EventVerdict, ...]:
        """Judge an iterable of events in the order it yields them."""
        if limit is not None:
            _require_index("limit", limit, minimum=1)
        if isinstance(source, (str, bytes)) or not isinstance(source, Iterable):
            raise JobContractError("source must be an iterable of JobEvent")
        verdicts: list[EventVerdict] = []
        for entry in source:
            if limit is not None and len(verdicts) >= limit:
                break
            verdicts.append(self.accept(entry))
        return tuple(verdicts)

    def pump(
        self,
        pull: "Callable[[], JobEvent | None]",
        *,
        limit: int = DEFAULT_PUMP_LIMIT,
    ) -> tuple[EventVerdict, ...]:
        """Take from a queue-shaped source until it is empty or *limit* is reached.

        *pull* returns the next event or ``None`` when there is nothing waiting. That
        seam is what keeps this module free of ``queue``: an adapter wraps
        ``get_nowait`` and its empty signal, and this stays a pure loop that never
        blocks and never asks how many are waiting.
        """
        if not callable(pull):
            raise JobContractError("pull must be callable")
        _require_index("limit", limit, minimum=1)
        verdicts: list[EventVerdict] = []
        while len(verdicts) < limit:
            entry = pull()
            if entry is None:
                break
            verdicts.append(self.accept(entry))
        return tuple(verdicts)

    def _judge(self, entry: "JobEvent") -> EventVerdict:
        if entry.run_id != self._run_id:
            return EventVerdict.STALE_RUN
        if self._terminal is not None:
            return (EventVerdict.DUPLICATE_TERMINAL if entry.is_terminal
                    else EventVerdict.AFTER_TERMINAL)
        if (self._item_ids is not None and entry.item_id is not None
                and entry.item_id not in self._item_ids):
            return EventVerdict.UNKNOWN_ITEM
        if entry.sequence <= self._last_sequence:
            return EventVerdict.OUT_OF_ORDER
        return EventVerdict.ACCEPTED

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"JobEventStream(run_id={self._run_id!r}, "
                f"accepted={len(self._events)}, closed={self.is_closed})")


class LoggerBridge:
    """Sends the technical events to the session log this application already has.

    It creates nothing: no logger, no handler, no file, no format, no retention
    policy, no second destination. It asks ``logging_setup.get_logger()`` for the one
    logger the launcher already opens, and only when it first has something to say —
    constructing a bridge must never be what opens a log file.

    Milestones are not forwarded. They are the Summary's job, they are already on
    screen, and duplicating them into the log would bury the diagnostics that the log
    exists for.
    """

    __slots__ = ("_logger",)

    #: The narrowest mapping consistent with what this repository already writes.
    #: An internal implementation detail, deliberately not encoded in the event
    #: vocabulary: no severity field was added to :class:`JobEvent` to express it.
    LEVELS: Mapping[JobEventKind, str] = MappingProxyType({
        JobEventKind.TECHNICAL_DETAIL: "debug",
        JobEventKind.WARNING: "warning",
        JobEventKind.FAILURE: "error",
    })

    def __init__(self, logger: Any = None) -> None:
        self._logger = logger

    @property
    def logger(self) -> Any:
        """The session logger, resolved once, on first use."""
        if self._logger is None:
            self._logger = _logging_setup.get_logger()
        return self._logger

    def forward(self, entry: "JobEvent") -> bool:
        """Write *entry* to the session log if it is one of the technical kinds."""
        if not isinstance(entry, JobEvent):
            raise JobContractError(
                f"a bridge forwards JobEvent, got {type(entry).__name__}")
        level = self.LEVELS.get(entry.kind)
        if level is None:
            return False
        body = entry.message
        if entry.detail:
            body = f"{body} — {entry.detail}" if body else entry.detail
        # Lazy %s formatting, as everything else in this repository writes it.
        getattr(self.logger, level)("%s", f"[{entry.run_id}] {body}")
        return True


# --------------------------------------------------------------------------- #
# Summary and Details
#
# One stream, two readers. The Summary is what a person watches while a run happens;
# Details is what they send when it goes wrong. The split is not a filter applied
# twice — it is a decision about what a *milestone* is.
# --------------------------------------------------------------------------- #

#: The kinds that become Summary lines. Progress and the current occurrence are
#: deliberately absent: they are *state*, shown live by the progress indicator and
#: the status label, not history to be appended two hundred times. Technical detail
#: is absent because that is precisely what §6.12 says must not flood the Summary.
SUMMARY_KINDS = frozenset({
    JobEventKind.STATE_CHANGED,
    JobEventKind.STAGE_CHANGED,
    JobEventKind.IMPORT_COUNT,
    JobEventKind.WARNING,
    JobEventKind.FAILURE,
    JobEventKind.OUTPUT_LOCATION,
    JobEventKind.COMPLETED,
    JobEventKind.CANCELLED,
})


def _require_events(source: object) -> tuple["JobEvent", ...]:
    if isinstance(source, (str, bytes)) or not isinstance(source, Iterable):
        raise JobContractError("expected an iterable of JobEvent")
    entries = tuple(source)
    for entry in entries:
        if not isinstance(entry, JobEvent):
            raise JobContractError(
                f"expected JobEvent, got {type(entry).__name__}")
    return entries


def _summary_line(entry: "JobEvent") -> str:
    """One concise line, built only from display-safe fields.

    ``detail`` is never consulted here. That is the whole guarantee: a command, a
    traceback or a diagnostic cannot reach the Summary by accident, because the
    Summary never reads the field they live in.
    """
    if entry.message:
        return entry.message
    kind = entry.kind
    if kind is JobEventKind.STAGE_CHANGED:
        return f"Stage: {entry.stage}"
    if kind is JobEventKind.IMPORT_COUNT:
        return f"{entry.count} files imported."
    if kind is JobEventKind.OUTPUT_LOCATION:
        return f"Output: {entry.location}"
    if entry.state is not None:
        return state_message(entry.state)
    return ""


def summary_lines(source: "Iterable[JobEvent]") -> tuple[str, ...]:
    """The milestones of a run, in order, with nothing technical in them."""
    lines = []
    for entry in _require_events(source):
        if entry.kind not in SUMMARY_KINDS:
            continue
        line = _summary_line(entry)
        if line:
            lines.append(line)
    return tuple(lines)


def detail_lines(source: "Iterable[JobEvent]") -> tuple[str, ...]:
    """Every event, timestamped, with its diagnostics kept whole.

    Times are elapsed seconds since the first event rather than a wall clock: the
    clock is injected and monotonic, so it has no calendar meaning, and pretending
    otherwise would put a fictional time of day next to a real diagnostic.

    A multi-line diagnostic is indented rather than flattened. Losing the shape of a
    traceback is losing most of what a traceback is for.
    """
    entries = _require_events(source)
    if not entries:
        return ()
    base = entries[0].timestamp
    lines: list[str] = []
    for entry in entries:
        elapsed = entry.timestamp - base
        head = f"[+{elapsed:.3f}s] {entry.kind.value}"
        if entry.item_id is not None:
            head = f"{head} ({entry.item_id})"
        if entry.message:
            head = f"{head}: {entry.message}"
        extras = entry.detail.splitlines()
        if len(extras) == 1 and not entry.message:
            # A one-line diagnostic with nothing else to say reads better on the
            # line it belongs to than under it.
            lines.append(f"{head}: {extras[0]}")
            continue
        lines.append(head)
        for extra in extras:
            lines.append(f"    {extra}")
    return tuple(lines)


class ProgressMode(Enum):
    """How a run's progress may honestly be shown.

    These are the three states :class:`~shared.ui_theme.ProgressIndicator` already
    has — an empty bar, a counted bar and an animated one. Phase 7 decides *which*;
    Phase 8 calls the widget. No second progress implementation exists.
    """

    IDLE = "idle"
    DETERMINATE = "determinate"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class ProgressView:
    """What the progress indicator should show, as a value with no widget in it."""

    mode: ProgressMode
    completed: int = 0
    total: "int | None" = None
    label: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ProgressMode):
            raise JobContractError(
                f"mode must be a ProgressMode, got {type(self.mode).__name__}")
        object.__setattr__(
            self, "completed", _require_index("completed", self.completed))
        if self.total is not None:
            object.__setattr__(self, "total", _require_index("total", self.total))
        object.__setattr__(
            self, "label", _require_display_safe("label", self.label, allow_blank=True))

        if self.mode is ProgressMode.DETERMINATE:
            if self.total is None:
                raise JobContractError(
                    "a determinate view needs a total; an unknown total is "
                    "indeterminate, never a guess")
            if self.completed > self.total:
                raise JobContractError(
                    f"progress {self.completed} exceeds total {self.total}")
        elif self.total is not None:
            raise JobContractError(
                f"a {self.mode.value} view carries no total")
        if self.mode is ProgressMode.IDLE and self.completed:
            raise JobContractError("an idle view has counted nothing yet")

    @property
    def fraction(self) -> "float | None":
        """The completed fraction, or ``None`` when there is honestly no such number."""
        if self.mode is not ProgressMode.DETERMINATE or not self.total:
            return None
        return self.completed / self.total


#: The starting view, and the one a new stage returns to.
IDLE_PROGRESS = ProgressView(mode=ProgressMode.IDLE)


class ProgressTracker:
    """Turns reported progress into a view, refusing to improve on what was reported.

    Two rules do all the work. **Progress does not go backwards** inside one scope —
    a scope being one stage with one total — so a late or duplicated report cannot
    make a run look like it lost ground. And **an ending changes no counter**: a run
    that succeeded after reporting three of five files shows three of five, because
    "it finished" and "it did all of it" are different claims and only the events can
    make the second one.

    A new stage starts the count again. Carrying a finished stage's five-of-five into
    the next one would be the first lie a progress bar tells.
    """

    __slots__ = ("_mode", "_completed", "_total", "_label", "_stage", "_item_id")

    def __init__(self, *, stage: "str | None" = None) -> None:
        self._stage = None if stage is None else _require_identifier("stage", stage)
        self._item_id: "str | None" = None
        self._reset()

    def _reset(self) -> None:
        self._mode = ProgressMode.IDLE
        self._completed = 0
        self._total: "int | None" = None
        self._label = ""

    @property
    def view(self) -> ProgressView:
        return ProgressView(
            mode=self._mode, completed=self._completed, total=self._total,
            label=self._label)

    @property
    def stage(self) -> "str | None":
        return self._stage

    @property
    def current_item_id(self) -> "str | None":
        return self._item_id

    def apply(self, entry: "JobEvent") -> ProgressView:
        """Fold one accepted event in, and return the view it produces."""
        if not isinstance(entry, JobEvent):
            raise JobContractError(
                f"a tracker folds in JobEvent, got {type(entry).__name__}")
        kind = entry.kind
        if kind is JobEventKind.STAGE_CHANGED:
            self._stage = entry.stage
            self._item_id = None
            self._reset()
        elif kind is JobEventKind.CURRENT_ITEM:
            self._item_id = entry.item_id
        elif kind is JobEventKind.PROGRESS:
            self._apply_progress(entry)
        return self.view

    def _apply_progress(self, entry: "JobEvent") -> None:
        if entry.total != self._total:
            # A different total is a different scope — the work was recounted, or a
            # count that had been unknown became known. Monotonicity is a rule
            # *within* a scope, so adopt the new one rather than compare across.
            self._total = entry.total
            self._completed = entry.completed
        elif entry.completed < self._completed:
            return  # regressive inside one scope: keep what was already true
        else:
            self._completed = entry.completed
        self._mode = (ProgressMode.DETERMINATE if self._total is not None
                      else ProgressMode.INDETERMINATE)
        if entry.message:
            self._label = entry.message


@dataclass(frozen=True, slots=True)
class SummaryView:
    """Everything the Summary needs, derived from one run's accepted events.

    The live parts — state, stage, current occurrence, progress, ETA — are *state*
    rather than history, which is exactly why they do not also appear as repeated
    lines. ``lines`` is the milestone history beside them.
    """

    state: "JobState | None" = None
    stage: "str | None" = None
    current_item_id: "str | None" = None
    progress: ProgressView = IDLE_PROGRESS
    eta: str = CALCULATING
    warnings: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    output_location: "Path | None" = None
    final: str = ""
    lines: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state is not None and not isinstance(self.state, JobState):
            raise JobContractError("state must be a JobState")
        if not isinstance(self.progress, ProgressView):
            raise JobContractError("progress must be a ProgressView")
        if not isinstance(self.eta, str):
            raise JobContractError("eta must be a string")


def project_summary(
    source: "Iterable[JobEvent]", *, eta: str = CALCULATING,
) -> SummaryView:
    """Derive the whole Summary from the events, and from nothing else.

    *eta* is passed in rather than computed here: only the worker knows what remains,
    and an estimate invented by a projection would be exactly the fabricated number
    §6.13 exists to prevent.
    """
    entries = _require_events(source)
    tracker = ProgressTracker()
    state: "JobState | None" = None
    warnings: list[str] = []
    failures: list[str] = []
    location: "Path | None" = None
    final = ""

    for entry in entries:
        tracker.apply(entry)
        if entry.state is not None:
            state = entry.state
        if entry.kind is JobEventKind.WARNING:
            warnings.append(entry.message)
        elif entry.kind is JobEventKind.FAILURE:
            failures.append(entry.message)
        elif entry.kind is JobEventKind.OUTPUT_LOCATION:
            location = entry.location
        if entry.is_terminal:
            final = _summary_line(entry)

    return SummaryView(
        state=state,
        stage=tracker.stage,
        current_item_id=tracker.current_item_id,
        progress=tracker.view,
        eta=eta,
        warnings=tuple(warnings),
        failures=tuple(failures),
        output_location=location,
        final=final,
        lines=summary_lines(entries),
    )


# --------------------------------------------------------------------------- #
# The current-run rolling ETA
# --------------------------------------------------------------------------- #


def format_duration(seconds: float) -> str:
    """The one place a length of time becomes text.

    Central by design: an estimate that reads "90s" in one panel and "1m 30s" in
    another is two features pretending to be one.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise JobContractError(
            f"a duration must be a number, got {type(seconds).__name__}")
    value = float(seconds)
    if not math.isfinite(value):
        raise JobContractError(f"a duration must be finite, got {seconds!r}")
    if value < 0:
        raise JobContractError(
            f"a negative duration is never shown, got {seconds!r}")
    total = int(round(value))
    if total >= 3600:
        hours, rest = divmod(total, 3600)
        return f"{hours}h {rest // 60}m"
    if total >= 60:
        minutes, rest = divmod(total, 60)
        return f"{minutes}m {rest}s"
    return f"{total}s"


class EtaEstimator:
    """A rolling estimate for the current run, or an honest ``Calculating…``.

    §6.13, in one object. It measures with an injected clock, keeps at most the
    latest twenty comparable samples, needs three before it will say anything, throws
    away every unit that did not honestly complete, and subtracts paused time to the
    second.

    **What it will not do** is more important than what it will. It never carries a
    sample across a change of work category, because converting a chapter and
    uploading one are not the same unit of work. It never carries anything across
    runs or into a retry — a new run gets a new estimator, and there is no history to
    inherit because nothing is stored anywhere. It never treats a media length as a
    timing sample: the only durations it knows are ones it measured itself, between a
    ``begin`` and a ``complete``. And when any of that leaves it unsure, it says
    ``Calculating…`` rather than a number, which is the only truthful thing to say.
    """

    __slots__ = ("_run_id", "_clock", "_minimum", "_window", "_samples", "_category",
                 "_started_at", "_paused_since", "_paused_total", "_paused", "_ended")

    def __init__(
        self,
        run_id: str,
        *,
        clock: Callable[[], float],
        minimum_samples: int = DEFAULT_MINIMUM_SAMPLES,
        window: int = DEFAULT_SAMPLE_WINDOW,
    ) -> None:
        if not callable(clock):
            raise JobContractError("clock must be callable")
        _require_index("minimum_samples", minimum_samples, minimum=1)
        _require_index("window", window, minimum=1)
        if window < minimum_samples:
            raise JobContractError(
                f"a window of {window} can never hold the {minimum_samples} samples "
                "required, so an estimate would never appear")
        self._run_id = _require_identifier("run_id", run_id)
        self._clock = clock
        self._minimum = minimum_samples
        self._window = window
        self._samples: deque[float] = deque(maxlen=window)
        self._category: "str | None" = None
        self._started_at: "float | None" = None
        self._paused_since: "float | None" = None
        self._paused_total = 0.0
        self._paused = False
        self._ended = False

    # -- properties ------------------------------------------------------- #

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def category(self) -> "str | None":
        return self._category

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def samples(self) -> tuple[float, ...]:
        return tuple(self._samples)

    # -- measuring -------------------------------------------------------- #

    def begin(self, category: str) -> None:
        """Start timing one work unit in *category*."""
        name = _require_identifier("category", category)
        if self._started_at is not None:
            raise JobContractError(
                "a unit is already being timed; complete or discard it first")
        started = _require_timestamp("clock", self._clock())
        if name != self._category:
            # A different kind of work is not comparable with what came before, so
            # the history that would have been averaged is dropped rather than mixed.
            self._samples.clear()
            self._category = name
        self._started_at = started
        self._paused_total = 0.0
        self._paused_since = self._clock() if self._paused else None

    def complete(self) -> "float | None":
        """Close the open unit, recording it only if the timing is trustworthy."""
        if self._started_at is None:
            raise JobContractError("no unit is being timed")
        started = self._started_at
        paused_total = self._paused_total
        if self._paused_since is not None:
            paused_total += self._read_clock() - self._paused_since
        ended = self._read_clock()
        self._clear_unit()

        if not math.isfinite(ended) or not math.isfinite(paused_total):
            return None
        duration = ended - started - paused_total
        if duration < 0:
            # A clock that went backwards, or more paused time than elapsed time.
            # One unmeasurable unit costs one sample and nothing else.
            return None
        self._samples.append(duration)
        return duration

    def discard(self) -> None:
        """Abandon the open unit. A cancelled or failed unit is not history."""
        self._clear_unit()

    def note_state(self, state: JobState) -> None:
        """Follow the authoritative run state, for pause exclusion and for endings.

        ``PAUSE_REQUESTED`` deliberately does nothing: §6.10 says the stage keeps
        running until the next safe checkpoint, so the time it spends there is work
        and counting it as a pause would understate every estimate that follows.
        """
        if not isinstance(state, JobState):
            raise JobContractError(
                f"state must be a JobState, got {type(state).__name__}")
        if state in TERMINAL_STATES:
            self._ended = True
            return
        if state is JobState.PAUSED:
            if not self._paused:
                self._paused = True
                if self._started_at is not None:
                    self._paused_since = self._read_clock()
        elif state is JobState.RUNNING and self._paused:
            if self._paused_since is not None:
                self._paused_total += self._read_clock() - self._paused_since
                self._paused_since = None
            self._paused = False

    def observe(self, entry: "JobEvent") -> bool:
        """Follow this run's own events. Returns whether the event was ours.

        An event from another run changes nothing at all — not the samples, not the
        pause accounting, not the ending. A stray report from elsewhere must never be
        able to end somebody else's estimate.
        """
        if not isinstance(entry, JobEvent):
            raise JobContractError(
                f"an estimator observes JobEvent, got {type(entry).__name__}")
        if entry.run_id != self._run_id:
            return False
        if entry.state is not None:
            self.note_state(entry.state)
        return True

    # -- estimating ------------------------------------------------------- #

    def estimate(self, remaining: int) -> "float | None":
        """Seconds of work left, or ``None`` when no estimate is trustworthy."""
        _require_index("remaining", remaining)
        if self._ended or self._paused:
            return None
        if len(self._samples) < self._minimum:
            return None
        return (sum(self._samples) / len(self._samples)) * remaining

    def display(
        self, remaining: "int | None", *, run_id: "str | None" = None,
    ) -> str:
        """The estimate as text, or ``Calculating…`` for every unreliable case."""
        if run_id is not None and run_id != self._run_id:
            return CALCULATING
        if remaining is None:
            return CALCULATING
        value = self.estimate(remaining)
        if value is None:
            return CALCULATING
        return format_duration(value)

    # -- internals -------------------------------------------------------- #

    def _read_clock(self) -> float:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise JobContractError(
                f"the clock must return a number, got {type(value).__name__}")
        return float(value)

    def _clear_unit(self) -> None:
        self._started_at = None
        self._paused_since = None
        self._paused_total = 0.0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"EtaEstimator(run_id={self._run_id!r}, "
                f"category={self._category!r}, samples={len(self._samples)})")
