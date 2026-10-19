"""Background import coordination — v0.6.0 Drop 3 (Plan 3), Phase 4.

This module makes folder importing *responsive* without making it *unsafe*. It owns
the whole lifecycle of one import operation — capture, warn, start, report, cancel,
confirm, commit — and it owns nothing else. Every primitive it drives already exists:
Phase 2's :func:`~shared.importing.scan_roots` does the walking, Phase 3's
:func:`~shared.importing.validate_direct_files` does Add Files, and Phase 3's
:class:`~shared.importing.ImportedFileManager` owns the list. Nothing here duplicates
any of them.

Why this is its own module
--------------------------
``shared/importing.py`` is provably pure: an approved Phase 1 guard asserts it
constructs no thread, owns no queue, and names ``threading`` exactly once — the lock
inside ``IdFactory``. That proof is worth keeping for the life of the drop, so the
thread and the queue live here instead, and the dependency runs one way
(``import_coordination`` → ``importing``) exactly as ``job_control`` already does.
The active drop's §7 file list is a "likely" surface and expressly allows a different
split when it is explained and recorded; this is that record.

The ownership rule, in one sentence
-----------------------------------
**The worker discovers; the owner thread decides.** A worker reads its immutable
request, calls the existing synchronous scanner, watches its own cancellation flag,
and puts frozen events on a queue. It never sees the manager, never mutates it, never
imports Tk, never reserves a path, never opens a dialog, and never converts anything.
Every entry point that can touch the imported list is fenced by :meth:`_require_owner`,
so calling it from a worker raises instead of racing.

Cancel Import is not Cancel Job
-------------------------------
:class:`ImportCancellation` is an ordinary :class:`threading.Event` behind a small
name. It is created per operation, it is never reset, and it has nothing whatsoever to
do with the processing job's cooperative-cancellation module: this module does not
import that module, raises none of its exceptions, and calls none of its checkpoint
helpers. Cancelling an import stops a *scan*. A processing job's controller is
untouched, and a structural guard in ``test_plan3_boundaries.py`` proves it rather
than asking anyone to trust this paragraph.

Atomicity survives every unhappy path
-------------------------------------
The manager is appended to in exactly one place — :meth:`ImportCoordinator._commit` —
and only from a Phase 3 transaction planned against the manager's own revision. A
cancelled scan, a failed worker, a declined confirmation, a malformed event, a stale
operation id, a closed coordinator and an unresolvable revision conflict all append
nothing, because none of them reaches that method. Phase 3 already refuses to build a
transaction from a non-completed result, so the rule is structural in two independent
places rather than a habit this layer has to remember.

Timestamps are injected, never discovered — this module imports no clock, exactly as
Phases 1–3 did — and so is the user's home directory used for broad-root
classification, so a test never depends on the machine it runs on.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from shared.importing import (
    CommitResult,
    CommitStatus,
    IdFactory,
    ImportContractError,
    ImportProblem,
    ImportTransaction,
    ImportedFileManager,
    RootKind,
    ScanOutcome,
    ScanRequest,
    ScanResult,
    ensure_display_safe,
    is_broad_root,
    scan_roots,
    validate_direct_files,
)

__all__ = [
    "ImportCoordinationError",
    "ImportEventKind",
    "ImportEvent",
    "TERMINAL_EVENT_KINDS",
    "TERMINAL_STATUSES",
    "ImportPhase",
    "StartOutcome",
    "StartReport",
    "OutcomeStatus",
    "ImportOutcome",
    "CloseReport",
    "ImportCancellation",
    "ImportCoordinator",
    "ImportPoller",
    "DEFAULT_JOIN_TIMEOUT",
    "DEFAULT_POLL_INTERVAL_MS",
]

#: How long :meth:`ImportCoordinator.close` and terminal handling will wait for the
#: worker thread. A worker publishes its terminal event as its *last* action, so after
#: that event is drained the wait is effectively zero; the timeout exists so a worker
#: parked in a slow ``scandir`` on a network share cannot wedge the caller forever.
#: When it expires the close report says so rather than claiming the worker stopped.
DEFAULT_JOIN_TIMEOUT = 5.0

#: Milliseconds between drains when an :class:`ImportPoller` is driving. The value is
#: only a default; the scheduler itself is always supplied by the caller.
DEFAULT_POLL_INTERVAL_MS = 120

#: Distinguishes "the caller passed nothing" from "the caller passed ``None``", which
#: for ``home`` are genuinely different requests.
_UNSET = object()

#: The one string Phase 1's display-safe contract refuses outright. Repeated rather
#: than imported because it is a literal, not a service.
_TRACEBACK_MARKER = "Traceback (most recent call last)"


class ImportCoordinationError(ImportContractError):
    """Raised when coordination is asked to do something it must refuse.

    A subclass of Phase 1's :class:`~shared.importing.ImportContractError`, so callers
    that already handle contract violations keep working unchanged.
    """


def _require_identifier(field: str, value: object) -> str:
    text = ensure_display_safe(field, value)
    if any(character.isspace() for character in text):
        raise ImportCoordinationError(f"{field} must not contain whitespace: {text!r}")
    return text


def _require_index(field: str, value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ImportCoordinationError(f"{field} must be an integer, got {type(value).__name__}")
    if value < minimum:
        raise ImportCoordinationError(f"{field} must be >= {minimum}, got {value}")
    return value


def _require_timestamp(field: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ImportCoordinationError(f"{field} must be a number, got {type(value).__name__}")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ImportCoordinationError(f"{field} must be a finite number")
    if number < 0:
        raise ImportCoordinationError(f"{field} must not be negative, got {number}")
    return number


def _zero_clock() -> float:
    """The default clock. Injected time only — this module imports none."""
    return 0.0


def _one_line(text: object, *, limit: int = 500) -> str:
    """Flatten arbitrary diagnostic text into something a queue payload may carry.

    An exception's own message is not under our control: it can be several lines long
    and it can quote a traceback, either of which Phase 1's display-safe contract
    rightly refuses. Flattening here means a hostile message degrades into a slightly
    uglier sentence instead of taking the worker's error reporting down with it.
    """
    flattened = " ".join(str(text).split())
    flattened = flattened.replace(_TRACEBACK_MARKER, "traceback")
    if len(flattened) > limit:
        flattened = flattened[:limit - 1].rstrip() + "…"
    return flattened


# --------------------------------------------------------------------------- #
# Cancellation — import-scoped, and nothing else
# --------------------------------------------------------------------------- #


class ImportCancellation:
    """`Cancel Import`: one flag, one operation, no relationship to a processing job.

    Deliberately tiny and deliberately separate. It raises nothing, so a cancelled
    scan returns a cancelled *result* rather than unwinding a stack, and it offers no
    ``reset`` — a controller belongs to one operation, and reusing one is how a stale
    cancellation ends up stopping a fresh import.

    It is callable, so it can be handed straight to ``scan_roots(cancel_check=...)``.
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self) -> None:
        """Ask the active import to stop. Idempotent, and safe from any thread."""
        self._event.set()

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    def __call__(self) -> bool:
        return self._event.is_set()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ImportCancellation(requested={self._event.is_set()})"


class _ProgressGate:
    """Keeps at most one unread progress event in flight.

    A scan of ten thousand files must not put ten thousand events on a queue the main
    thread drains every tenth of a second. The worker asks before publishing and is
    refused while an earlier progress event is still unread, so the queue stays bounded
    no matter how fast the scan runs. Counts stay monotonic and truthful — intermediate
    values are skipped, never invented or reordered.
    """

    __slots__ = ("_lock", "_pending")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending = False

    def offer(self) -> bool:
        with self._lock:
            if self._pending:
                return False
            self._pending = True
            return True

    def consumed(self) -> None:
        with self._lock:
            self._pending = False


# --------------------------------------------------------------------------- #
# The queue vocabulary
# --------------------------------------------------------------------------- #


class ImportEventKind(Enum):
    """What one worker event says. Three of the five are terminal."""

    #: The worker began. Published before any filesystem call.
    STARTED = "started"
    #: A running count of compatible candidates found so far. Never a percentage,
    #: never an estimate, and never a claim that anything was added.
    DISCOVERED = "discovered"
    #: The scan finished and carries a committable result.
    COMPLETED = "completed"
    #: `Cancel Import` was honoured at a checkpoint. Nothing may be committed.
    CANCELLED = "cancelled"
    #: The worker could not finish. Carries a display-safe message and the detail.
    FAILED = "failed"


#: The kinds that end an operation. Exactly one of these is published per accepted
#: start, and handling one is what returns the coordinator to idle.
TERMINAL_EVENT_KINDS = frozenset({
    ImportEventKind.COMPLETED,
    ImportEventKind.CANCELLED,
    ImportEventKind.FAILED,
})


@dataclass(frozen=True, slots=True)
class ImportEvent:
    """One immutable report from the worker to the owner thread.

    Everything it can carry is already frozen: a :class:`ScanResult` is a frozen
    dataclass of tuples, and the message pair is plain text. No exception object, no
    live options mapping, no manager reference and no widget ever crosses this
    boundary, so nothing the owner thread reads can still be changing underneath it.
    """

    operation_id: str
    kind: ImportEventKind
    discovered_count: int = 0
    result: ScanResult | None = None
    display_message: str = ""
    technical_detail: str = ""
    at: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "operation_id", _require_identifier("operation_id", self.operation_id))
        if not isinstance(self.kind, ImportEventKind):
            raise ImportCoordinationError(
                f"kind must be an ImportEventKind, got {type(self.kind).__name__}")
        object.__setattr__(
            self, "discovered_count", _require_index("discovered_count", self.discovered_count))
        if self.result is not None and not isinstance(self.result, ScanResult):
            raise ImportCoordinationError(
                f"result must be a ScanResult, got {type(self.result).__name__}")
        object.__setattr__(
            self,
            "display_message",
            ensure_display_safe("display_message", self.display_message, allow_blank=True),
        )
        object.__setattr__(
            self,
            "technical_detail",
            ensure_display_safe("technical_detail", self.technical_detail, allow_blank=True),
        )
        object.__setattr__(self, "at", _require_timestamp("at", self.at))

        expected = {
            ImportEventKind.COMPLETED: ScanOutcome.COMPLETED,
            ImportEventKind.CANCELLED: ScanOutcome.CANCELLED,
            ImportEventKind.FAILED: ScanOutcome.FAILED,
        }.get(self.kind)
        if self.kind in (ImportEventKind.STARTED, ImportEventKind.DISCOVERED):
            if self.result is not None:
                raise ImportCoordinationError(
                    f"a {self.kind.value} event reports no result; only a terminal event does")
        elif self.result is not None and self.result.outcome is not expected:
            raise ImportCoordinationError(
                f"a {self.kind.value} event may only carry a {expected.value} result, got "
                f"{self.result.outcome.value}")
        if self.kind is ImportEventKind.COMPLETED and self.result is None:
            raise ImportCoordinationError(
                "a completed event must carry the result it completed with")
        if self.kind is ImportEventKind.DISCOVERED and self.discovered_count < 1:
            raise ImportCoordinationError(
                "a discovered event reports a real count; nothing found is not progress")
        if self.kind is ImportEventKind.FAILED and not self.technical_detail:
            raise ImportCoordinationError("a failed event must say why: record the detail")

    @property
    def is_terminal(self) -> bool:
        return self.kind in TERMINAL_EVENT_KINDS


# --------------------------------------------------------------------------- #
# Lifecycle vocabulary
# --------------------------------------------------------------------------- #


class ImportPhase(Enum):
    """Where one coordinator is. Only one import may be active at a time."""

    IDLE = "idle"
    SCANNING = "scanning"
    #: A completed result is being held, unmodified, while the user answers the
    #: captured large-result confirmation. Nothing is committed while it waits.
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CLOSED = "closed"


class StartOutcome(Enum):
    """Why a start attempt did or did not create a worker."""

    STARTED = "started"
    #: An import is already active. The active one is untouched.
    BUSY = "busy"
    #: A broad root was chosen and the warning was declined, or no confirmer was
    #: supplied at all. No worker was created and nothing was scanned.
    DECLINED_BROAD_ROOT = "declined_broad_root"
    #: §6.2: no supported type is ticked. A validation message, never a worker.
    NO_TYPES_SELECTED = "no_types_selected"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class StartReport:
    """The frozen answer to "did that start?", including every reason it did not."""

    outcome: StartOutcome
    operation_id: str = ""
    display_message: str = ""
    broad_roots: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, StartOutcome):
            raise ImportCoordinationError(
                f"outcome must be a StartOutcome, got {type(self.outcome).__name__}")
        if self.operation_id:
            object.__setattr__(
                self, "operation_id", _require_identifier("operation_id", self.operation_id))
        object.__setattr__(
            self,
            "display_message",
            ensure_display_safe("display_message", self.display_message, allow_blank=True),
        )
        object.__setattr__(self, "broad_roots", tuple(self.broad_roots))
        if self.outcome is StartOutcome.STARTED and not self.operation_id:
            raise ImportCoordinationError("a started import has an operation id")

    @property
    def started(self) -> bool:
        return self.outcome is StartOutcome.STARTED


class OutcomeStatus(Enum):
    """What one drain of the queue actually resolved to."""

    #: Nothing is active and nothing happened.
    IDLE = "idle"
    #: A worker is running. Progress may have moved; nothing was committed.
    RUNNING = "running"
    #: A completed result is waiting on the large-result confirmation.
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    #: The whole accepted set was appended, once.
    COMMITTED = "committed"
    #: The transaction was valid and current but proposed nothing to add.
    NOTHING_ADDED = "nothing_added"
    #: `Cancel Import` was honoured. Nothing was appended.
    CANCELLED = "cancelled"
    #: The worker failed, or an illegal event arrived. Nothing was appended.
    FAILED = "failed"
    #: The confirmation was declined. Nothing was appended.
    DECLINED = "declined"
    #: The list moved underneath the transaction and recomputation could not settle
    #: it. Nothing was appended, and it is not retried in a loop.
    CONFLICT = "conflict"
    #: Another import is already active; this request did nothing.
    BUSY = "busy"
    #: §6.2 again, on the direct Add Files path.
    NO_TYPES_SELECTED = "no_types_selected"
    #: The coordinator is closed. Nothing was appended and nothing will be.
    CLOSED = "closed"


#: Statuses that end an operation one way or another.
TERMINAL_STATUSES = frozenset({
    OutcomeStatus.COMMITTED,
    OutcomeStatus.NOTHING_ADDED,
    OutcomeStatus.CANCELLED,
    OutcomeStatus.FAILED,
    OutcomeStatus.DECLINED,
    OutcomeStatus.CONFLICT,
})


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    """The frozen result of one owner-thread step, including the ones that did nothing.

    ``commit`` is the only place an addition can be reported from, and Phase 3 already
    refuses to let a :class:`CommitResult` claim additions unless it committed — so a
    cancelled, failed, declined or conflicting outcome cannot describe an append even
    by accident.
    """

    status: OutcomeStatus
    operation_id: str = ""
    discovered_count: int = 0
    events: tuple[ImportEvent, ...] = ()
    ignored: tuple[ImportEvent, ...] = ()
    transaction: ImportTransaction | None = None
    commit: CommitResult | None = None
    problems: tuple[ImportProblem, ...] = ()
    display_message: str = ""
    technical_detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, OutcomeStatus):
            raise ImportCoordinationError(
                f"status must be an OutcomeStatus, got {type(self.status).__name__}")
        if self.operation_id:
            object.__setattr__(
                self, "operation_id", _require_identifier("operation_id", self.operation_id))
        object.__setattr__(
            self, "discovered_count", _require_index("discovered_count", self.discovered_count))
        for field, values in (("events", self.events), ("ignored", self.ignored)):
            entries = tuple(values)
            for entry in entries:
                if not isinstance(entry, ImportEvent):
                    raise ImportCoordinationError(
                        f"{field} must be ImportEvent, got {type(entry).__name__}")
            object.__setattr__(self, field, entries)
        if self.transaction is not None and not isinstance(self.transaction, ImportTransaction):
            raise ImportCoordinationError("transaction must be an ImportTransaction")
        if self.commit is not None and not isinstance(self.commit, CommitResult):
            raise ImportCoordinationError("commit must be a CommitResult")
        problems = tuple(self.problems)
        for problem in problems:
            if not isinstance(problem, ImportProblem):
                raise ImportCoordinationError(
                    f"problems must be ImportProblem, got {type(problem).__name__}")
        object.__setattr__(self, "problems", problems)
        object.__setattr__(
            self,
            "display_message",
            ensure_display_safe("display_message", self.display_message, allow_blank=True),
        )
        object.__setattr__(
            self,
            "technical_detail",
            ensure_display_safe("technical_detail", self.technical_detail, allow_blank=True),
        )

        if self.status is OutcomeStatus.COMMITTED:
            if self.commit is None or not self.commit.committed:
                raise ImportCoordinationError(
                    "a committed outcome carries the CommitResult that committed")
        elif self.commit is not None and self.commit.committed:
            raise ImportCoordinationError(
                f"a {self.status.value} outcome appended nothing; it must not carry a "
                "committed CommitResult")

    @property
    def added(self) -> tuple:
        """Exactly what was appended, which for every non-committed status is empty."""
        return () if self.commit is None else self.commit.added

    @property
    def added_count(self) -> int:
        return len(self.added)

    @property
    def proposed_count(self) -> int:
        return 0 if self.transaction is None else self.transaction.proposed_count

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def committed(self) -> bool:
        return self.status is OutcomeStatus.COMMITTED


@dataclass(frozen=True, slots=True)
class CloseReport:
    """What :meth:`ImportCoordinator.close` actually managed to do.

    ``worker_stopped`` is reported rather than assumed: if the bounded join expired
    the answer is ``False``, because §5.4 forbids claiming a running call stopped.
    """

    closed: bool = True
    cancelled_operation_id: str = ""
    worker_stopped: bool = True
    discarded_events: int = 0
    discarded_transaction: bool = False

    def __post_init__(self) -> None:
        if self.cancelled_operation_id:
            object.__setattr__(
                self,
                "cancelled_operation_id",
                _require_identifier("cancelled_operation_id", self.cancelled_operation_id),
            )
        object.__setattr__(
            self, "discarded_events", _require_index("discarded_events", self.discarded_events))


# --------------------------------------------------------------------------- #
# The worker
#
# A module-level function rather than a method, so it is provable — by reading it and
# by an ``ast`` guard — that it never had a manager to mutate in the first place.
# --------------------------------------------------------------------------- #

#: Runs one scan. Injectable so a test can park a worker on a barrier, fail it on
#: purpose, or return a result the real scanner would never produce.
Scanner = Callable[..., ScanResult]

#: Puts one frozen event on the coordinator's queue.
Publish = Callable[[ImportEvent], None]

#: Creates the worker thread. Injectable so a test can run the body inline, refuse to
#: start, or watch exactly how many threads were ever created.
ThreadFactory = Callable[[Callable[[], None], str], object]

#: Schedules ``callback`` after ``delay_ms``. ``root.after`` has this shape; so does a
#: fake in a test. Nothing in this module knows which one it was given.
Scheduler = Callable[[int, Callable[[], object]], object]


def _default_thread_factory(target: Callable[[], None], name: str) -> threading.Thread:
    # ``daemon`` is a backstop, never the mechanism: ``close()`` cancels and joins, and
    # a test proves no thread survives a deterministic teardown. The flag only stops a
    # worker parked in a hung network ``scandir`` from holding an exiting app open.
    return threading.Thread(target=target, name=name, daemon=True)


def _run_scan(
    *,
    request: ScanRequest,
    operation_id: str,
    cancel: ImportCancellation,
    publish: Publish,
    scanner: Scanner,
    clock: Callable[[], float],
    gate: _ProgressGate,
) -> None:
    """The whole of what a worker thread does. It receives no manager, by construction.

    Exactly one terminal event is published per call. The ``finally`` clause is not
    belt-and-braces: it is what makes "one accepted start, one terminal outcome" true
    even if the injected scanner raises something that is not an ``Exception``, so the
    coordinator can never be left waiting forever on a worker that already died.
    """
    published = False

    def report(event: ImportEvent) -> None:
        publish(event)

    try:
        report(ImportEvent(
            operation_id=operation_id, kind=ImportEventKind.STARTED, at=clock()))

        def on_count(count: int) -> None:
            # A count discovered after the user pressed Cancel is not live progress.
            if cancel.requested:
                return
            if gate.offer():
                report(ImportEvent(
                    operation_id=operation_id,
                    kind=ImportEventKind.DISCOVERED,
                    discovered_count=count,
                    at=clock(),
                ))

        result = scanner(
            request, cancel_check=cancel, on_count=on_count, completed_at=clock())

        if not isinstance(result, ScanResult):
            report(ImportEvent(
                operation_id=operation_id,
                kind=ImportEventKind.FAILED,
                display_message="The import could not be completed.",
                technical_detail=_one_line(
                    f"the scanner returned {type(result).__name__}, not a ScanResult"),
                at=clock(),
            ))
            published = True
            return

        kind = {
            ScanOutcome.COMPLETED: ImportEventKind.COMPLETED,
            ScanOutcome.CANCELLED: ImportEventKind.CANCELLED,
            ScanOutcome.FAILED: ImportEventKind.FAILED,
        }[result.outcome]
        report(ImportEvent(
            operation_id=operation_id,
            kind=kind,
            discovered_count=result.discovered_count,
            result=result,
            display_message=(
                "The import could not be completed."
                if kind is ImportEventKind.FAILED else ""),
            technical_detail=(
                "the scan reported a failed outcome"
                if kind is ImportEventKind.FAILED else ""),
            at=clock(),
        ))
        published = True
    except BaseException as exc:  # noqa: BLE001 - converted, never re-published raw
        # The exception object itself never crosses the queue: it is mutable, it holds
        # a traceback with live frames, and Phase 1's contract is display-safe text.
        report(ImportEvent(
            operation_id=operation_id,
            kind=ImportEventKind.FAILED,
            display_message="The import could not be completed.",
            technical_detail=_one_line(f"{type(exc).__name__}: {exc}"),
            at=clock(),
        ))
        published = True
    finally:
        if not published:  # pragma: no cover - only reachable via a thread kill
            report(ImportEvent(
                operation_id=operation_id,
                kind=ImportEventKind.FAILED,
                display_message="The import could not be completed.",
                technical_detail="the import worker stopped without reporting a result",
                at=clock(),
            ))


class _Operation:
    """The owner thread's private record of one running import."""

    __slots__ = ("operation_id", "request", "cancel", "gate", "thread", "discovered")

    def __init__(self, operation_id: str, request: ScanRequest) -> None:
        self.operation_id = operation_id
        self.request = request
        self.cancel = ImportCancellation()
        self.gate = _ProgressGate()
        self.thread: object | None = None
        self.discovered = 0


class _Pending:
    """A completed result held, unmodified, while the user answers a confirmation."""

    __slots__ = ("operation_id", "request", "transaction", "confirmed", "cancelled")

    def __init__(
        self,
        operation_id: str,
        request: ScanRequest,
        transaction: ImportTransaction,
        *,
        confirmed: bool = False,
    ) -> None:
        self.operation_id = operation_id
        self.request = request
        self.transaction = transaction
        #: True once the user has already said yes to a proposal of this size, which
        #: is what makes a materially different recomputation worth re-asking about.
        self.confirmed = confirmed
        #: Set by ``request_cancel`` from any thread. One attribute store, read by the
        #: owner thread on its next step; the discard itself happens there.
        self.cancelled = False


# --------------------------------------------------------------------------- #
# The coordinator
# --------------------------------------------------------------------------- #


class ImportCoordinator:
    """Owns one import operation at a time, and the only path to the manager.

    Construct it on the thread that owns the imported-file manager — in a Tk
    application, the main thread. Every method that can read or change the manager
    checks that it is being called from that same thread and raises otherwise, so
    "the worker never mutates the list" is enforced rather than documented.

    The shape of one folder import::

        report = coordinator.start(request)      # broad-root warning happens here
        ...
        outcome = coordinator.pump()             # drain, handle, maybe commit
        if outcome.status is OutcomeStatus.AWAITING_CONFIRMATION:
            coordinator.confirm_pending()        # or decline_pending()
        ...
        coordinator.close()                      # cancels and joins, idempotent

    ``Cancel Import`` is :meth:`request_cancel`, which may be called from anywhere and
    as often as you like, in any phase, including before a worker has done anything and
    after everything has finished.
    """

    __slots__ = (
        "_manager", "_scanner", "_clock", "_ids", "_confirm_broad", "_home",
        "_thread_factory", "_join_timeout", "_queue", "_owner", "_phase",
        "_operation", "_pending", "_finished",
    )

    def __init__(
        self,
        manager: ImportedFileManager,
        *,
        scanner: Scanner | None = None,
        clock: Callable[[], float] | None = None,
        id_factory: IdFactory | None = None,
        confirm_broad_root: Callable[[tuple[Path, ...]], bool] | None = None,
        home: object = _UNSET,
        thread_factory: ThreadFactory | None = None,
        join_timeout: float = DEFAULT_JOIN_TIMEOUT,
    ) -> None:
        if not isinstance(manager, ImportedFileManager):
            raise ImportCoordinationError(
                f"manager must be an ImportedFileManager, got {type(manager).__name__}")
        if id_factory is not None and not isinstance(id_factory, IdFactory):
            raise ImportCoordinationError("id_factory must be an IdFactory")
        self._manager = manager
        self._scanner: Scanner = scan_roots if scanner is None else scanner
        self._clock: Callable[[], float] = _zero_clock if clock is None else clock
        self._ids = IdFactory() if id_factory is None else id_factory
        self._confirm_broad = confirm_broad_root
        self._home = _default_home() if home is _UNSET else home
        self._thread_factory: ThreadFactory = (
            _default_thread_factory if thread_factory is None else thread_factory)
        self._join_timeout = _require_timestamp("join_timeout", join_timeout)
        # ``SimpleQueue`` rather than ``Queue``: no task bookkeeping is wanted, and the
        # progress gate — not a maxsize that could block a worker — is what bounds it.
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._owner = threading.get_ident()
        self._phase = ImportPhase.IDLE
        self._operation: _Operation | None = None
        self._pending: _Pending | None = None
        self._finished: set[str] = set()

    # -- reading ----------------------------------------------------------- #

    @property
    def phase(self) -> ImportPhase:
        return self._phase

    @property
    def is_active(self) -> bool:
        """True while a worker is running or a confirmation is being held."""
        return self._phase in (ImportPhase.SCANNING, ImportPhase.AWAITING_CONFIRMATION)

    @property
    def is_closed(self) -> bool:
        return self._phase is ImportPhase.CLOSED

    @property
    def operation_id(self) -> str:
        if self._operation is not None:
            return self._operation.operation_id
        if self._pending is not None:
            return self._pending.operation_id
        return ""

    @property
    def discovered_count(self) -> int:
        return 0 if self._operation is None else self._operation.discovered

    @property
    def pending_transaction(self) -> ImportTransaction | None:
        """The proposal being confirmed, held exactly as it was planned."""
        return None if self._pending is None else self._pending.transaction

    def _require_owner(self, action: str) -> None:
        if threading.get_ident() != self._owner:
            raise ImportCoordinationError(
                f"{action}() reaches the imported-file manager and must run on the thread "
                "that owns it; a worker publishes events and never mutates the list")

    # -- starting ---------------------------------------------------------- #

    def start(self, request: ScanRequest) -> StartReport:
        """Validate, warn, and create at most one worker.

        Nothing is scanned before this returns ``STARTED``. A broad root — a volume
        root, a UNC share root, or the exact user home — is refused unless the injected
        confirmer says yes, and refused outright when no confirmer was supplied at all:
        an application that never wired up the warning must not silently walk a whole
        drive. Declining creates no thread and changes nothing.
        """
        self._require_owner("start")
        if self._phase is ImportPhase.CLOSED:
            return StartReport(
                outcome=StartOutcome.CLOSED,
                display_message="This importer has been closed.")
        if self.is_active:
            return StartReport(
                outcome=StartOutcome.BUSY,
                operation_id=self.operation_id,
                display_message="An import is already running.")
        if not isinstance(request, ScanRequest):
            raise ImportCoordinationError(
                f"start needs a ScanRequest, got {type(request).__name__}")
        if any(root.kind is RootKind.DIRECT_FILES for root in request.roots):
            raise ImportCoordinationError(
                "individually chosen files are not scanned in the background; pass them "
                "to import_files(), which validates them on this thread")
        if not request.options.has_selection:
            return StartReport(
                outcome=StartOutcome.NO_TYPES_SELECTED,
                display_message="Choose at least one file type before importing.")

        broad = tuple(
            root.path for root in request.folder_roots
            if root.path is not None and is_broad_root(root.path, home=self._home))
        if broad:
            if self._confirm_broad is None or not self._confirm_broad(broad):
                return StartReport(
                    outcome=StartOutcome.DECLINED_BROAD_ROOT,
                    display_message=(
                        "That folder covers a whole drive or your home folder, so nothing "
                        "was scanned."),
                    broad_roots=broad)

        operation = _Operation(self._ids.next_id("op"), request)

        def body() -> None:
            _run_scan(
                request=request,
                operation_id=operation.operation_id,
                cancel=operation.cancel,
                publish=self._queue.put,
                scanner=self._scanner,
                clock=self._clock,
                gate=operation.gate,
            )

        thread = self._thread_factory(body, f"import-{operation.operation_id}")
        operation.thread = thread
        # State is settled *before* the thread runs, so a worker that publishes its
        # whole life before ``start`` returns still finds an operation to belong to.
        self._operation = operation
        self._phase = ImportPhase.SCANNING
        try:
            thread.start()
        except BaseException:
            self._operation = None
            self._phase = ImportPhase.IDLE
            raise
        return StartReport(
            outcome=StartOutcome.STARTED, operation_id=operation.operation_id)

    def import_files(self, request: ScanRequest, paths: Iterable[object]) -> ImportOutcome:
        """Add individually chosen files, validated and settled on this thread.

        No worker: the user has just picked a bounded list from a dialog, and
        re-inspecting it is a handful of ``lstat`` calls. Offering a Cancel button for
        something that cannot run long would be theatre. It still travels the identical
        confirmation-and-commit path as a folder scan, so there is exactly one route
        into the manager rather than two that could drift apart.
        """
        self._require_owner("import_files")
        if self._phase is ImportPhase.CLOSED:
            return ImportOutcome(
                status=OutcomeStatus.CLOSED,
                display_message="This importer has been closed.")
        if self.is_active:
            return ImportOutcome(
                status=OutcomeStatus.BUSY,
                operation_id=self.operation_id,
                display_message="An import is already running.")
        if not isinstance(request, ScanRequest):
            raise ImportCoordinationError(
                f"import_files needs a ScanRequest, got {type(request).__name__}")
        roots = request.direct_roots
        if len(roots) != 1 or len(request.roots) != 1:
            raise ImportCoordinationError(
                "import_files needs a request holding exactly one direct-files root")
        if not request.options.has_selection:
            return ImportOutcome(
                status=OutcomeStatus.NO_TYPES_SELECTED,
                display_message="Choose at least one file type before importing.")

        operation_id = self._ids.next_id("op")
        result = validate_direct_files(
            paths,
            request_id=request.request_id,
            root=roots[0],
            catalog=request.catalog,
            options=request.options,
            completed_at=self._clock(),
        )
        return self._settle(operation_id, request, result)

    # -- cancelling -------------------------------------------------------- #

    def request_cancel(self) -> bool:
        """`Cancel Import`. Idempotent, safe from any thread, safe in any phase.

        Returns whether there was anything to cancel. Before a start, after a terminal
        result, and on a closed coordinator it does nothing at all and says so. It
        never touches a processing job's controller, because it has no reference to
        one and this module imports none.
        """
        cancelled = False
        operation = self._operation
        if operation is not None:
            operation.cancel.request()
            cancelled = True
        pending = self._pending
        if pending is not None:
            # The discard happens on the owner thread; this is the flag it reads.
            pending.cancelled = True
            cancelled = True
        return cancelled

    @property
    def cancel_requested(self) -> bool:
        operation = self._operation
        if operation is not None and operation.cancel.requested:
            return True
        pending = self._pending
        return pending is not None and pending.cancelled

    # -- draining ---------------------------------------------------------- #

    def pump(self) -> ImportOutcome:
        """Drain every queued event, handle it, and report what this step resolved to.

        Safe to call at any time and any number of times. Events belonging to an
        operation that has already finished are ignored rather than replayed, which is
        what makes a duplicated terminal event harmless and a second commit impossible.
        """
        self._require_owner("pump")
        if self._phase is ImportPhase.CLOSED:
            return ImportOutcome(
                status=OutcomeStatus.CLOSED,
                display_message="This importer has been closed.")

        pending = self._pending
        if pending is not None:
            if pending.cancelled:
                return self._discard_pending(OutcomeStatus.CANCELLED, (
                    "The import was cancelled and nothing was added."))
            return ImportOutcome(
                status=OutcomeStatus.AWAITING_CONFIRMATION,
                operation_id=pending.operation_id,
                transaction=pending.transaction,
                problems=pending.transaction.problems,
            )

        handled: list[ImportEvent] = []
        ignored: list[ImportEvent] = []
        resolved: ImportOutcome | None = None

        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break

            if not isinstance(item, ImportEvent):
                # Fail closed: an illegal payload ends the operation without ever
                # reaching the manager, rather than being guessed at.
                outcome = self._abandon(
                    "The import could not be completed.",
                    _one_line(
                        f"an illegal queue payload of type {type(item).__name__} "
                        "was discarded"),
                )
                resolved = outcome if resolved is None else resolved
                continue

            operation = self._operation
            if operation is None or item.operation_id != operation.operation_id:
                ignored.append(item)
                continue

            handled.append(item)
            if item.kind is ImportEventKind.DISCOVERED:
                operation.gate.consumed()
                if not operation.cancel.requested:
                    # Monotonic by construction: a lower late count never lowers it.
                    operation.discovered = max(operation.discovered, item.discovered_count)
                continue
            if not item.is_terminal:
                continue

            outcome = self._finish(operation, item)
            resolved = outcome if resolved is None else resolved

        if resolved is not None:
            return _with_events(resolved, tuple(handled), tuple(ignored))

        operation = self._operation
        if operation is not None:
            return ImportOutcome(
                status=OutcomeStatus.RUNNING,
                operation_id=operation.operation_id,
                discovered_count=operation.discovered,
                events=tuple(handled),
                ignored=tuple(ignored),
            )
        return ImportOutcome(
            status=OutcomeStatus.IDLE, events=tuple(handled), ignored=tuple(ignored))

    # -- confirming -------------------------------------------------------- #

    def confirm_pending(self) -> ImportOutcome:
        """Accept the held proposal and commit it, once."""
        self._require_owner("confirm_pending")
        if self._phase is ImportPhase.CLOSED:
            return ImportOutcome(
                status=OutcomeStatus.CLOSED,
                display_message="This importer has been closed.")
        pending = self._pending
        if pending is None:
            return ImportOutcome(
                status=OutcomeStatus.IDLE,
                display_message="There is nothing waiting to be confirmed.")
        if pending.cancelled:
            return self._discard_pending(OutcomeStatus.CANCELLED, (
                "The import was cancelled and nothing was added."))

        self._pending = None
        self._phase = ImportPhase.IDLE
        return self._commit(
            pending.operation_id, pending.request, pending.transaction, confirmed=True)

    def decline_pending(self) -> ImportOutcome:
        """Refuse the held proposal. The manager is not touched."""
        self._require_owner("decline_pending")
        if self._phase is ImportPhase.CLOSED:
            return ImportOutcome(
                status=OutcomeStatus.CLOSED,
                display_message="This importer has been closed.")
        if self._pending is None:
            return ImportOutcome(
                status=OutcomeStatus.IDLE,
                display_message="There is nothing waiting to be confirmed.")
        return self._discard_pending(
            OutcomeStatus.DECLINED, "Nothing was added to the imported list.")

    # -- closing ----------------------------------------------------------- #

    def close(self) -> CloseReport:
        """Cancel anything active, wait for the worker, and refuse all further work.

        Idempotent. Orderly rather than abrupt: the cancellation flag is set first so
        the worker stops at its next checkpoint, then the thread is joined within a
        bounded timeout, then the queue is emptied so nothing published during the
        teardown can be mistaken for live work later.
        """
        self._require_owner("close")
        if self._phase is ImportPhase.CLOSED:
            return CloseReport(closed=True)

        cancelled_id = ""
        stopped = True
        operation = self._operation
        if operation is not None:
            cancelled_id = operation.operation_id
            operation.cancel.request()
            thread = operation.thread
            if thread is not None and getattr(thread, "is_alive", None) is not None:
                if thread.is_alive():
                    thread.join(self._join_timeout)
                    stopped = not thread.is_alive()
            self._finished.add(operation.operation_id)
            self._operation = None

        discarded_transaction = self._pending is not None
        self._pending = None
        self._phase = ImportPhase.CLOSED

        discarded = 0
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            discarded += 1

        return CloseReport(
            closed=True,
            cancelled_operation_id=cancelled_id,
            worker_stopped=stopped,
            discarded_events=discarded,
            discarded_transaction=discarded_transaction,
        )

    # -- internals --------------------------------------------------------- #

    def _retire(self, operation: _Operation) -> None:
        """Return to idle and prove the worker finished. Called once per operation."""
        thread = operation.thread
        if thread is not None and getattr(thread, "is_alive", None) is not None:
            # The terminal event is a worker's last act, so this wait is effectively
            # zero; the timeout only bounds a pathological case.
            if thread.is_alive():
                thread.join(self._join_timeout)
        self._finished.add(operation.operation_id)
        self._operation = None
        self._phase = ImportPhase.IDLE

    def _abandon(self, message: str, detail: str) -> ImportOutcome:
        """End the active operation without going anywhere near the manager."""
        operation = self._operation
        operation_id = "" if operation is None else operation.operation_id
        if operation is not None:
            operation.cancel.request()
            self._retire(operation)
        return ImportOutcome(
            status=OutcomeStatus.FAILED,
            operation_id=operation_id,
            display_message=message,
            technical_detail=detail,
        )

    def _finish(self, operation: _Operation, event: ImportEvent) -> ImportOutcome:
        """Handle one terminal event. The only caller is :meth:`pump`."""
        operation_id = operation.operation_id
        request = operation.request
        discovered = operation.discovered

        if event.kind is ImportEventKind.CANCELLED:
            self._retire(operation)
            return ImportOutcome(
                status=OutcomeStatus.CANCELLED,
                operation_id=operation_id,
                discovered_count=discovered,
                problems=() if event.result is None else event.result.problems,
                display_message="The import was cancelled and nothing was added.",
            )

        if event.kind is ImportEventKind.FAILED:
            self._retire(operation)
            return ImportOutcome(
                status=OutcomeStatus.FAILED,
                operation_id=operation_id,
                discovered_count=discovered,
                problems=() if event.result is None else event.result.problems,
                display_message=(
                    event.display_message or "The import could not be completed."),
                technical_detail=event.technical_detail,
            )

        result = event.result
        if result is None or result.request_id != request.request_id:
            # Fail closed rather than committing a result that belongs to something
            # else. ``ImportEvent`` already forbids a completed event without a result;
            # this catches a forged one.
            self._retire(operation)
            return ImportOutcome(
                status=OutcomeStatus.FAILED,
                operation_id=operation_id,
                discovered_count=discovered,
                display_message="The import could not be completed.",
                technical_detail=(
                    "the completed event did not carry this operation's own result"),
            )

        self._retire(operation)
        outcome = self._settle(operation_id, request, result)
        if outcome.discovered_count == 0 and discovered:
            outcome = _with_discovered(outcome, discovered)
        return outcome

    def _settle(
        self, operation_id: str, request: ScanRequest, result: ScanResult) -> ImportOutcome:
        """Plan the transaction, apply the captured threshold, and commit or hold.

        The threshold comes from the ``EffectiveConfig`` frozen onto the request when
        the import started, so a preference saved while the scan ran cannot change the
        rule this result is judged by. **Equal to the threshold does not warn** (§6.7):
        only a strictly greater proposal asks.
        """
        transaction = self._manager.plan(result, options=request.options)
        if transaction.proposed_count > request.large_result_warning_threshold:
            return self._hold(operation_id, request, transaction, confirmed=False)
        return self._commit(operation_id, request, transaction, confirmed=False)

    def _hold(
        self,
        operation_id: str,
        request: ScanRequest,
        transaction: ImportTransaction,
        *,
        confirmed: bool,
    ) -> ImportOutcome:
        self._pending = _Pending(
            operation_id, request, transaction, confirmed=confirmed)
        self._phase = ImportPhase.AWAITING_CONFIRMATION
        return ImportOutcome(
            status=OutcomeStatus.AWAITING_CONFIRMATION,
            operation_id=operation_id,
            transaction=transaction,
            problems=transaction.problems,
            display_message=(
                f"{transaction.proposed_count} files are ready to add. Add them?"),
        )

    def _discard_pending(self, status: OutcomeStatus, message: str) -> ImportOutcome:
        pending = self._pending
        self._pending = None
        self._phase = ImportPhase.IDLE
        return ImportOutcome(
            status=status,
            operation_id="" if pending is None else pending.operation_id,
            transaction=None if pending is None else pending.transaction,
            problems=() if pending is None else pending.transaction.problems,
            display_message=message,
        )

    def _commit(
        self,
        operation_id: str,
        request: ScanRequest,
        transaction: ImportTransaction,
        *,
        confirmed: bool,
    ) -> ImportOutcome:
        """Append once, or append nothing. The only method that touches the list.

        A stale revision is not merged and not retried in a loop: the transaction is
        recomputed against current state exactly once, using Phase 3's own primitive
        and the duplicate policy frozen onto it. If the recomputation proposes a
        materially different set — a different number of additions or duplicate skips —
        and the user had already agreed to the old one, they are asked again rather than
        given something they did not approve. A second conflict is reported truthfully.
        """
        commit = self._manager.commit(transaction)

        if commit.status is CommitStatus.STALE_REVISION:
            fresh = self._manager.recompute(transaction)
            material = (
                fresh.proposed_count != transaction.proposed_count
                or fresh.duplicate_count != transaction.duplicate_count
            )
            over_threshold = (
                fresh.proposed_count > request.large_result_warning_threshold)
            if material and (confirmed or over_threshold):
                return self._hold(operation_id, request, fresh, confirmed=False)
            transaction = fresh
            commit = self._manager.commit(fresh)
            if commit.status is CommitStatus.STALE_REVISION:
                return ImportOutcome(
                    status=OutcomeStatus.CONFLICT,
                    operation_id=operation_id,
                    transaction=transaction,
                    commit=commit,
                    problems=transaction.problems,
                    display_message=(
                        "The imported list changed while this import was finishing, so "
                        "nothing was added. Try importing again."),
                    technical_detail=(
                        "the manager revision moved again during recomputation; no "
                        "further attempt is made"),
                )

        status = (
            OutcomeStatus.COMMITTED if commit.committed else OutcomeStatus.NOTHING_ADDED)
        message = (
            f"Added {len(commit.added)} files." if commit.committed
            else "Nothing new was added to the imported list.")
        return ImportOutcome(
            status=status,
            operation_id=operation_id,
            transaction=transaction,
            commit=commit,
            problems=transaction.problems,
            display_message=message,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"ImportCoordinator(phase={self._phase.value}, "
                f"operation={self.operation_id!r})")


def _default_home() -> object:
    """The user's home for broad-root classification, or ``None`` if unknowable.

    Reads an environment variable; it opens nothing and reads no directory. A test
    always injects its own, so no fixture depends on the machine it runs on.
    """
    try:
        return Path.home()
    except (RuntimeError, OSError):  # pragma: no cover - platform dependent
        return None


def _with_events(
    outcome: ImportOutcome,
    events: tuple[ImportEvent, ...],
    ignored: tuple[ImportEvent, ...],
) -> ImportOutcome:
    """Re-issue a frozen outcome carrying the events that produced it."""
    return ImportOutcome(
        status=outcome.status,
        operation_id=outcome.operation_id,
        discovered_count=outcome.discovered_count,
        events=events,
        ignored=ignored,
        transaction=outcome.transaction,
        commit=outcome.commit,
        problems=outcome.problems,
        display_message=outcome.display_message,
        technical_detail=outcome.technical_detail,
    )


def _with_discovered(outcome: ImportOutcome, discovered: int) -> ImportOutcome:
    return ImportOutcome(
        status=outcome.status,
        operation_id=outcome.operation_id,
        discovered_count=discovered,
        events=outcome.events,
        ignored=outcome.ignored,
        transaction=outcome.transaction,
        commit=outcome.commit,
        problems=outcome.problems,
        display_message=outcome.display_message,
        technical_detail=outcome.technical_detail,
    )


# --------------------------------------------------------------------------- #
# The polling seam
#
# Phase 8 owns the Tk adapter. This is the shape it will plug into: a scheduler is
# supplied by the caller, and nothing here knows whether it was ``root.after`` or a
# list in a test.
# --------------------------------------------------------------------------- #


class ImportPoller:
    """Drains a coordinator on a caller-supplied scheduler. Contains no Tk.

    ``schedule(delay_ms, callback)`` has exactly the shape of ``root.after``, and the
    optional ``cancel(handle)`` has the shape of ``root.after_cancel``. Supplying them
    rather than importing them is what keeps this module runnable with no display and
    testable with no event loop.

    Guarantees: at most one callback is ever pending; :meth:`stop` and :meth:`close`
    are idempotent; a callback that fires after either one returns immediately without
    touching the coordinator, which is how a destroyed widget is survived rather than
    crashed into.
    """

    __slots__ = (
        "_coordinator", "_schedule", "_cancel", "_interval_ms", "_on_outcome",
        "_handle", "_running", "_closed",
    )

    def __init__(
        self,
        coordinator: ImportCoordinator,
        schedule: Scheduler,
        *,
        cancel: Callable[[object], object] | None = None,
        interval_ms: int = DEFAULT_POLL_INTERVAL_MS,
        on_outcome: Callable[[ImportOutcome], object] | None = None,
    ) -> None:
        if not isinstance(coordinator, ImportCoordinator):
            raise ImportCoordinationError(
                f"coordinator must be an ImportCoordinator, got {type(coordinator).__name__}")
        if not callable(schedule):
            raise ImportCoordinationError("schedule must be callable")
        self._coordinator = coordinator
        self._schedule = schedule
        self._cancel = cancel
        self._interval_ms = _require_index("interval_ms", interval_ms, minimum=1)
        self._on_outcome = on_outcome
        self._handle: object | None = None
        self._running = False
        self._closed = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pending_handle(self) -> object | None:
        return self._handle

    def start(self) -> bool:
        """Begin polling. Returns ``False`` if already polling or already closed."""
        if self._closed or self._running:
            return False
        self._running = True
        self._reschedule()
        return True

    def tick(self) -> ImportOutcome:
        """One drain. Reschedules itself unless it has been stopped or closed."""
        self._handle = None
        if self._closed or not self._running:
            return ImportOutcome(
                status=OutcomeStatus.CLOSED if self._closed else OutcomeStatus.IDLE)
        outcome = self._coordinator.pump()
        if self._on_outcome is not None:
            self._on_outcome(outcome)
        # Re-read the flags: an ``on_outcome`` callback is entitled to stop or close
        # the poller, and rescheduling after it did would resurrect it.
        if self._running and not self._closed:
            self._reschedule()
        return outcome

    def stop(self) -> None:
        """Stop polling. Idempotent, and cancels any callback already scheduled."""
        self._running = False
        handle, self._handle = self._handle, None
        if handle is not None and self._cancel is not None:
            self._cancel(handle)

    def close(self) -> CloseReport:
        """Stop polling and close the coordinator. Idempotent."""
        self.stop()
        self._closed = True
        return self._coordinator.close()

    def _reschedule(self) -> None:
        if self._handle is not None:
            return
        self._handle = self._schedule(self._interval_ms, self.tick)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"ImportPoller(running={self._running}, closed={self._closed}, "
                f"pending={self._handle is not None})")
