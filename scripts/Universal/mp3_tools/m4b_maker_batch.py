"""M4B Maker batch execution, success numbering and Retry Failed — v0.6.4 Phase 5.

One frozen :class:`~mp3_tools.m4b_maker_plan.RunPlan` runs through the shared
job architecture here, with no panel involved. The MP3 Tool keeps this
orchestration inside its Tk panel; the Maker keeps it in this Tk-free module so
the panel (Phase 6) only wires buttons to it and drains its events.

What this composes, and defines none of
---------------------------------------
- **One ``JobController`` and one ``JobReporter`` per batch attempt**, never one
  per Book. The controller is the one state authority: its listener copies
  every state it actually reaches into the event stream, so nothing here keeps
  a rival state machine. Pause, Resume and Cancel are the controller's
  requests; the worker honours them at ``checkpoint`` between Books and, through
  the Phase 4 engine, between steps inside a Book.
- **One worker body per attempt** (:meth:`Attempt.run`), run exactly once on
  whatever thread the caller chooses. Nothing here starts a thread or touches
  a widget; events cross to the UI through the ``publish`` callable the caller
  supplied, exactly as the shared ``JobAdapter`` expects.
- **The Phase 4 engine** for every Book in frozen order:
  :func:`~mp3_tools.m4b_maker_processing.stage_book` then
  :func:`~mp3_tools.m4b_maker_processing.publish_book`, with the shared
  success-number allocator between them. A failed Book never stops the next.
- **The Plan 3 result vocabulary.** Each Book settles into its own
  ``RunResult`` against its exact frozen ``RunSnapshot``. A Book that failed
  while it still had inputs to retry records one retryable ``FailureRecord``
  per **real** occurrence it was combining; a Book that could not start at all
  (unusable artwork, FFmpeg not ready) records one item-less fatal failure. No
  identity is ever invented. The batch composes into the Plan 6
  ``WorkspaceRunResult``, and Retry Failed is ``retry_failed_books`` on it.

Success-only Series Part numbering (Decision 48A, plan section 5.9)
------------------------------------------------------------------
With Auto-number off there is no allocator and the Phase 4 manual behaviour
stands. With it on, :class:`MakerRun` owns one ``SuccessNumbers`` counter from
the frozen Start Part — **execution state, not plan state** — for the whole
retry chain. For each Book that staged and validated: ``propose()``, write the
proposed part onto the **staged** file, validate again, publish, and only then
``commit()``. A failure before or during publication consumes nothing; a
publication failure retains the validated candidate so the retry can reuse it,
and the retry rewrites that stale tentative part to its own newly proposed
number before publishing. Describing a retry consumes nothing.

Retry Failed
------------
:meth:`MakerRun.retry_failed` builds a new attempt at the **same** run — same
run id, same frozen ``BookPlan`` objects, nothing re-planned, re-reserved or
re-captured — from the Plan 6 requests, and re-runs only the retryable failed
Books. Earlier results are merged so the settled result always describes the
whole frozen run (a retry that itself succeeded while another Book still stands
failed is, for the batch, completed with failures — Decision 28A).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared import metadata
from shared.book_workspace import WorkspaceRunResult, retry_failed_books
from shared.cancellation import ConversionCancelled
from shared.importing import IdFactory
from shared.job_control import (
    FailureLog,
    FailureRecord,
    JobController,
    JobReporter,
    JobState,
    RunResult,
)
from shared.numbering import SuccessNumbers
from mp3_tools import m4b_maker_processing as proc
from mp3_tools.m4b_maker_plan import BookPlan, RunPlan

__all__ = [
    "BatchError",
    "BookRecord",
    "Attempt",
    "MakerRun",
    "STAGE_PREPARE",
    "FAULT_MESSAGE",
]

#: The stage the reporter announces before the first Book.
STAGE_PREPARE = "prepare"

#: What the user sees when the worker itself broke, as opposed to a Book.
FAULT_MESSAGE = "The run stopped because of an internal error."

#: Stages at which a failure is the Book's inputs' to retry. Anything else is
#: a fatal, item-less failure: the plan itself cannot be run as it stands.
_RETRYABLE_STAGES = frozenset({
    "normalize", "silence", "fast", "fallback", "safe", "encode", "series", "cover",
    "validate", "publish", "processing", "staging", "number",
})


class BatchError(Exception):
    """A caller used the runner in a way its contract forbids."""


@dataclass(frozen=True)
class BookRecord:
    """One Book as one attempt settled it: the Plan 3 result and what was published."""

    book_id: str
    result: RunResult
    published: Path | None = None
    part: int | None = None

    @property
    def succeeded(self) -> bool:
        return self.result.state is JobState.SUCCEEDED


class Attempt:
    """One attempt at a run: a first run, or a Retry Failed of it.

    Holds the attempt's controller, reporter and the Books it runs. The worker
    body is :meth:`run`, called exactly once on the caller's worker thread.
    """

    def __init__(self, owner: "MakerRun", *, number: int, run_id: str,
                 books: tuple[BookPlan, ...], retry: Mapping[str, tuple[str, ...]] | None,
                 controller: JobController, reporter: JobReporter) -> None:
        self._owner = owner
        self.number = number
        self.run_id = run_id
        self.books = books
        self.retry = retry
        self.controller = controller
        self.reporter = reporter
        #: The checkpoint the worker body calls between Books and hands to the
        #: engine. The controller's by default; a test may wrap it.
        self.checkpoint: Callable[[], None] = controller.checkpoint
        self.records: tuple[BookRecord, ...] = ()
        self.result: WorkspaceRunResult | None = None
        self._ran = False

    @property
    def is_retry(self) -> bool:
        return self.retry is not None

    @property
    def finished(self) -> bool:
        return self.result is not None

    def run(self) -> WorkspaceRunResult:
        """The worker body. Runs every Book, settles the controller, composes the result.

        Never lets anything escape: a cancellation raised at a checkpoint
        settles as cancelled; any other fault settles as failed with the detail
        kept technical. Whatever happens, the one terminal event is sent and the
        run's result is composed, because that is what frees the caller.
        """
        if self._ran:
            raise BatchError(f"attempt {self.number} has already run")
        self._ran = True
        controller, reporter = self.controller, self.reporter
        records: list[BookRecord] = []
        try:
            try:
                self._execute(records)
                final = (controller.complete_with_failures()
                         if any(not entry.succeeded for entry in records)
                         else controller.succeed())
                reporter.completed(final)
            except ConversionCancelled:
                reporter.cancelled(controller.finish_cancelled())
            except BaseException as exc:  # noqa: BLE001 - deliberately everything
                detail = f"{type(exc).__name__}: {exc}"
                reporter.technical(detail)
                reporter.completed(controller.fail(FAULT_MESSAGE, detail))
        finally:
            self.records = tuple(records)
            self.result = self._owner._settle(self, controller.state)
        return self.result

    # -- the Books ----------------------------------------------------------- #

    def _execute(self, records: list[BookRecord]) -> None:
        total = len(self.books)
        for done, book in enumerate(self.books):
            self.checkpoint()
            self.reporter.stage_changed(f"book-{book.number}",
                                        f"Book {book.number}: {book.filename}")
            self.reporter.progress(done, total, item_id=book.occurrence_ids[0],
                                   stage=f"book-{book.number}")
            records.append(self._run_book(book))
        self.reporter.progress(total, total, stage="done")

    def _run_book(self, book: BookPlan) -> BookRecord:
        owner = self._owner
        reporter = self.reporter
        work_root = owner.plan.work_root
        snapshot_id = book.snapshot.snapshot_id

        def failed(stage: str, message: str, detail: str) -> BookRecord:
            if stage in _RETRYABLE_STAGES:
                records = tuple(
                    FailureRecord(item_id=occurrence, stage=stage, display_message=message,
                                  technical_detail=detail or message, retryable=True,
                                  snapshot_id=snapshot_id)
                    for occurrence in book.occurrence_ids)
                for record in records:
                    reporter.failure(message, detail, item_id=record.item_id, stage=stage)
            else:
                records = (FailureRecord(item_id=None, stage=stage, display_message=message,
                                         technical_detail=detail or message, retryable=False,
                                         snapshot_id=snapshot_id),)
                reporter.failure(message, detail, stage=stage)
            result = RunResult.settle(book.snapshot,
                                      FailureLog(snapshot_id=snapshot_id, records=records))
            return BookRecord(book_id=book.book_id, result=result)

        def on_event(event: proc.ProcessingEvent) -> None:
            line = f"[{event.stage}] {event.message}"
            reporter.technical(f"{line} — {event.detail}" if event.detail else line)

        # A retry reuses a retained, validated candidate rather than rebuilding it.
        retained = self.is_retry and book.staged.is_file() and not book.staged.is_symlink()
        if retained:
            try:
                proc.validate_staged_m4b(book, book.staged)
                reporter.technical(f"[kept] {book.filename}: reusing the staged candidate")
            except proc.ProcessingError:
                retained = False
                proc.discard_staging(book, work_root=work_root)
        if not retained:
            outcome = proc.stage_book(book, work_root=work_root, fast_first=owner.plan.fast_first,
                                      checkpoint=self.checkpoint, on_event=on_event)
            if outcome.cancelled:
                raise ConversionCancelled("Cancelled.")
            if not outcome.succeeded:
                return failed(outcome.failure_stage or "processing", outcome.failure_message,
                              outcome.failure_detail)

        tentative = None
        if owner.numbers is not None:
            tentative = owner.numbers.propose()
            try:
                tags = {"series_part": str(tentative.number)}
                if book.series.strip():
                    tags["series"] = book.series
                metadata.write_m4b_tags(book.staged, tags)
                proc.validate_staged_m4b(book, book.staged)
            except Exception as exc:  # noqa: BLE001 - the candidate is retained for a retry
                return failed("number", "the series part could not be written",
                              f"{type(exc).__name__}: {exc}")
            reporter.technical(f"[number] {book.filename}: proposed Series Part "
                               f"{tentative.number}")

        try:
            self.checkpoint()
        except ConversionCancelled:
            proc.discard_staging(book, work_root=work_root)
            raise
        try:
            published = proc.publish_book(book, work_root=work_root)
        except proc.ProcessingError as exc:
            # The validated candidate stays in staging for Retry Failed; the
            # tentative number was never committed.
            return failed(exc.stage, str(exc), exc.detail)
        part = None
        if tentative is not None:
            part = owner.numbers.commit(tentative)
        proc.discard_staging(book, work_root=work_root)
        owner._prune_work_root()
        reporter.output_location(published, f"✓ {published.name}")
        result = RunResult.settle(book.snapshot, completed_ids=book.occurrence_ids)
        return BookRecord(book_id=book.book_id, result=result, published=published, part=part)


class MakerRun:
    """One frozen plan's execution: the first attempt and every retry of it.

    Owns what outlives an attempt — the plan, the success-number counter, the
    merged results — and mints each attempt's controller and reporter. Reads
    nothing live: the plan is the only input, and it never changes.
    """

    def __init__(self, plan: RunPlan, *, id_factory: IdFactory,
                 clock: Callable[[], float] = time.monotonic,
                 publish: Callable[[Any], object] | None = None) -> None:
        if not isinstance(plan, RunPlan):
            raise BatchError(f"plan must be a RunPlan, got {type(plan).__name__}")
        if not isinstance(id_factory, IdFactory):
            raise BatchError("run ids are minted by an importing.IdFactory")
        self.plan = plan
        self._ids = id_factory
        self._clock = clock
        self._listeners: list[Callable[[Any], object]] = [publish] if publish else []
        self.numbers: SuccessNumbers | None = (
            SuccessNumbers(plan.start_part) if plan.auto_number else None)
        self.attempts: tuple[Attempt, ...] = ()
        self.result: WorkspaceRunResult | None = None
        self._run_id: str | None = None
        self._results: dict[str, RunResult] = {}

    # -- listeners ----------------------------------------------------------- #

    def add_listener(self, listener: Callable[[Any], object]) -> None:
        """Hear every event the reporter publishes, on the thread that produced it."""
        if not callable(listener):
            raise BatchError("listener must be callable")
        self._listeners.append(listener)

    def _publish(self, event) -> None:
        for listener in tuple(self._listeners):
            listener(event)

    def _on_state(self, snapshot) -> None:
        """The controller's listener: copy its state into the event stream."""
        attempt = self.active
        if attempt is not None and snapshot.run_id == attempt.run_id:
            attempt.reporter.state_changed(snapshot)

    # -- attempts ------------------------------------------------------------ #

    @property
    def active(self) -> Attempt | None:
        """The attempt that has started and not yet finished, if any."""
        for attempt in reversed(self.attempts):
            if not attempt.finished:
                return attempt
        return None

    def start(self) -> Attempt:
        """Begin the first attempt. The caller then runs it on its worker thread."""
        if self.attempts:
            raise BatchError("this run has already started; use retry_failed for a retry")
        return self._begin(tuple(self.plan.books), retry=None)

    def retry_failed(self) -> Attempt:
        """Begin a Retry Failed attempt from the settled result. Consumes no number."""
        if self.active is not None:
            raise BatchError("an attempt is still running")
        result = self.result
        if result is None or not result.can_retry_failed:
            raise BatchError("nothing is retryable")
        requests = retry_failed_books(result)
        by_snapshot = {id(book.snapshot): book for book in self.plan.books}
        books: list[BookPlan] = []
        retry: dict[str, tuple[str, ...]] = {}
        for request in requests:
            book = by_snapshot.get(id(request.snapshot))
            if book is None:
                raise BatchError("a retry names a snapshot this plan does not hold")
            books.append(book)
            retry[book.book_id] = tuple(request.item_ids)
        ordered = tuple(book for book in self.plan.books if book.book_id in retry)
        return self._begin(ordered, retry=retry)

    def _begin(self, books: tuple[BookPlan, ...], *, retry) -> Attempt:
        if self._run_id is None:
            self._run_id = self._ids.next_id("run")
        run_id = self._run_id
        item_ids = tuple(occurrence for book in self.plan.books for occurrence in book.occurrence_ids)
        controller = JobController(run_id, listener=self._on_state)
        reporter = JobReporter(run_id, clock=self._clock, publish=self._publish,
                               item_ids=item_ids)
        attempt = Attempt(self, number=len(self.attempts) + 1, run_id=run_id, books=books,
                          retry=retry, controller=controller, reporter=reporter)
        self.attempts = self.attempts + (attempt,)
        controller.start()
        label = "Retry Failed" if retry is not None else "Build M4B"
        reporter.stage_changed(
            STAGE_PREPARE,
            f"{label}: {len(books)} Book(s) → {self.plan.root}")
        reporter.output_location(self.plan.root, f"Output: {self.plan.root}")
        reporter.progress(0, len(books), stage=STAGE_PREPARE)
        return attempt

    # -- the controller's requests, for the caller's buttons ----------------- #

    def pause(self) -> None:
        attempt = self.active
        if attempt is not None:
            attempt.controller.request_pause()

    def resume(self) -> None:
        attempt = self.active
        if attempt is not None:
            attempt.controller.resume()

    def cancel(self) -> None:
        attempt = self.active
        if attempt is not None:
            attempt.controller.request_cancel()

    # -- settlement ---------------------------------------------------------- #

    def _settle(self, attempt: Attempt, state: JobState) -> WorkspaceRunResult:
        """Compose the frozen batch result over every attempt so far."""
        for record in attempt.records:
            self._results[record.book_id] = record.result
        final = state if state in (JobState.SUCCEEDED, JobState.COMPLETED_WITH_FAILURES,
                                   JobState.CANCELLED, JobState.FAILED) else JobState.FAILED
        if final is JobState.SUCCEEDED and any(
                entry.state is not JobState.SUCCEEDED for entry in self._results.values()):
            final = JobState.COMPLETED_WITH_FAILURES
        self.result = WorkspaceRunResult(self.plan.capture,
                                         results=tuple(self._results.items()), state=final)
        return self.result

    def _prune_work_root(self) -> None:
        """Remove the work root once nothing is left in it. ``rmdir`` only."""
        work = self.plan.work_root
        try:
            if work.is_dir() and not work.is_symlink() and not any(work.iterdir()):
                work.rmdir()
        except OSError:
            pass
