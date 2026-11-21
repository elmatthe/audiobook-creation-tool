"""The frozen M4B Metadata Editor action plans — v0.6.4 Phase 8.

One Editor action — **Save Tags**, **Clear All Tags (keep chapters)** or
**Remove Series Numbering** — is planned once, completely, before any file is
touched, and the plan is the only thing the Phase 9 engine and a later Retry
Failed ever read. Nothing here copies a file, writes or clears a tag, removes a
numbering atom, applies a chapter title or a cover, allocates a series number
or starts a controller — and planning creates nothing on disk.

What is frozen
--------------
- **The run.** Exactly one shared :class:`~shared.output_paths.RunReservation`
  for the whole operation (the Editor has no custom-destination exception);
  its planner is the one collision authority. Every Book's final file lands
  **flat** in that run, named by its source filename with the source's own
  container extension kept (``.m4b`` / ``.m4a`` / ``.mp4``), sanitised by the
  shared sanitiser and collision-numbered by the shared planner; its private
  staging directory sits under the run's ``.work`` area, keyed by the final
  stem so same-named sources stage apart.
- **The Books.** The Plan 6 capture decides eligibility and freezes each
  Book's exact ``RunSnapshot``. A Book whose source could not be read is
  **skipped as invalid** through the capture's own predicate — its stable id
  and frozen disposition survive in ``capture.skipped`` for Phase 9 to report;
  nothing tries to repair it, and no other Book is affected.
- **Per Book, kept apart and never collapsed:** the frozen
  :class:`~m4b.metadata.m4b_metadata_workflow.SourceObservation` (what the source
  *contains*), the explicit **Shared overrides**, the explicit **Book edits**,
  the explicit **artwork replacement**, the positional **chapter-title edits**,
  and the **action**. ``writes`` is a derived read-only view (Shared over Book)
  for the engine, not a stored fifth thing.

What each action freezes (plan section 6.10–6.12, Phase 8)
-----------------------------------------------------------
- **Save Tags:** only actual intended writes. An unchanged source prefill, a
  blank Book value and a value equal to the source are *preserve* and freeze
  nothing (so a vendor / movement / implied series value the page merely
  displays is never migrated); a populated Shared value is an override; a
  changed Book value is an edit; artwork only when explicitly chosen; chapter
  edits positional with blank/equal lines preserving.
- **Clear All Tags:** the same explicit values — and nothing else — to reapply
  *after* the clear, so a prefilled-but-unchanged value cannot survive the clear
  by accident; no replacement artwork means the source cover stays removed.
- **Remove Series Numbering:** the action alone. Pending Shared overrides, Book
  edits, artwork replacements and chapter edits visible in the workspace are
  deliberately **not** captured; the observed Series Name is a source fact the
  action preserves.

Series auto-number: the run freezes the setting and the parsed Start Part as
configuration for Save; no number is assigned here and no counter lives in the
plan — the shared ``SuccessNumbers`` is Phase 9's execution state. Remove
Series Numbering never numbers.

Off the Tk thread (v0.8.2 Checkpoint 2)
---------------------------------------
The panel freezes the workspace, the observation store and the capture
inputs on Tk and calls :func:`plan_run` on its preparation worker, with a
``checkpoint`` that raises to stop a cancelled preparation and a ``progress``
callback. ``plan_run`` takes the Plan 6 capture there, synchronously, before
any processing worker exists: a pure function of immutable values (the
store's frozen readable/unreadable answer; no disk read), so it can leave Tk,
where it cost one ``RunSnapshot`` per file (Decisions, v0.8.2 Checkpoint 2).
A caller may pass a capture it took itself (:func:`capture_for_run`). Every source is
normalised once per plan into an :class:`~shared.output_paths.InputIndex`, and
each planned path is one lookup; each Book's two paths used to resolve every
source again -- 2N² path resolutions, 15 s for 250 files on the Tk thread. A
supplied capture must be a capture of the workspace and store being planned
(:func:`_require_capture_matches`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from shared import output_paths
from shared.book_workspace import (
    BookJob,
    BookRunSnapshot,
    WorkspaceSnapshot,
    capture_workspace_run,
    effective_run_options,
)
from shared.importing import IdFactory, ImportOptions, SupportedTypeCatalog
from shared.job_control import RunSnapshot, freeze_options
from m4b.metadata import m4b_metadata_workflow as wf
from m4b.metadata.m4b_metadata_workflow import ObservationStore, SourceObservation

__all__ = [
    "PlanError",
    "EditorAction",
    "EditorRunOptions",
    "BookPlan",
    "RunPlan",
    "WORK_DIRNAME",
    "capture_for_run",
    "plan_run",
]


class PlanError(Exception):
    """A plan could not be built from what it was given."""


class EditorAction(Enum):
    SAVE_TAGS = "save_tags"
    CLEAR_ALL_TAGS = "clear_all_tags"
    REMOVE_SERIES_NUMBERING = "remove_series_numbering"


#: The private, unpublished work area under the run — reserved with the planner
#: before any output so a source called ``.work`` is numbered away from it.
WORK_DIRNAME = ".work"

_EMPTY: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True)
class EditorRunOptions:
    """The batch-level options, raw as the panel captured them."""

    auto_number: bool = False
    start_part_text: str = ""


@dataclass(frozen=True)
class BookPlan:
    """One attempted Book: the source fact, the explicit intent, the paths."""

    book_id: str
    number: int
    action: EditorAction
    snapshot: RunSnapshot
    occurrence_id: str
    source: Path
    observation: SourceObservation
    shared_overrides: Mapping[str, str]
    book_edits: Mapping[str, str]
    artwork: str | None
    chapter_edits: tuple[str | None, ...]
    filename: str
    staging_dir: Path
    staged: Path
    published: Path

    @property
    def writes(self) -> Mapping[str, str]:
        """The text fields the action will write, Shared over Book. Derived, read-only."""
        merged = dict(self.book_edits)
        merged.update(self.shared_overrides)
        return MappingProxyType(merged)

    @property
    def has_intent(self) -> bool:
        """Whether this Book asks for anything at all.

        Clearing and removing are themselves the intent; a Save with no write,
        no artwork and no chapter edit asks for nothing (auto-numbering is the
        run's intent, not the Book's).
        """
        if self.action is not EditorAction.SAVE_TAGS:
            return True
        return bool(self.writes) or self.artwork is not None or any(
            entry is not None for entry in self.chapter_edits)


@dataclass(frozen=True)
class RunPlan:
    """The whole operation, frozen. Holds no workspace, store, widget or counter."""

    action: EditorAction
    reservation: output_paths.RunReservation
    run_directory: Path
    work_root: Path
    capture: BookRunSnapshot
    books: tuple[BookPlan, ...]
    observations: Mapping[str, SourceObservation]
    auto_number: bool
    start_part: int

    def book_for(self, book_id: str) -> BookPlan | None:
        for entry in self.books:
            if entry.book_id == book_id:
                return entry
        return None

    def observation_for(self, book_id: str) -> SourceObservation | None:
        """The frozen observation of any captured Book, attempted or skipped."""
        return self.observations.get(book_id)

    @property
    def has_intent(self) -> bool:
        return self.auto_number or any(entry.has_intent for entry in self.books)


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #


def _observations(workspace: WorkspaceSnapshot, store: ObservationStore) -> dict[str, SourceObservation]:
    """Each Book's frozen observation, by Book id; a pristine Book has none."""
    observations: dict[str, SourceObservation] = {}
    for book in workspace.books:
        seen = store.for_book(book)
        if seen is not None:
            observations[book.book_id] = seen
    return observations


def _readable_in(observations: Mapping[str, SourceObservation]) -> Callable[[BookJob], bool]:
    """The capture's validity predicate: a Book is attempted only while its source was read."""
    def readable(book: BookJob) -> bool:
        seen = observations.get(book.book_id)
        return seen is not None and seen.readable
    return readable


def capture_for_run(workspace: WorkspaceSnapshot, store: ObservationStore, *,
                    catalog: SupportedTypeCatalog, import_options: ImportOptions,
                    effective_config: Any, id_factory: IdFactory,
                    created_at: float = 0.0) -> BookRunSnapshot:
    """The Plan 6 capture one action is frozen from. Synchronous, on the calling thread (v0.8.2).

    The shared capture is taken on the caller's thread before any processing worker exists. It reads no disk:
    readability is the observation store's frozen answer, and the predicate built from it is used here and never
    stored. :func:`plan_run` calls this on the panel's preparation worker; a caller may also take it first and pass it.
    """
    if not isinstance(store, ObservationStore):
        raise PlanError(f"store must be an ObservationStore, got {type(store).__name__}")
    return capture_workspace_run(
        workspace, catalog=catalog, import_options=import_options,
        effective_config=effective_config, id_factory=id_factory,
        created_at=created_at, is_valid=_readable_in(_observations(workspace, store)))


def plan_run(workspace: WorkspaceSnapshot, store: ObservationStore, *,
             action: EditorAction, options: EditorRunOptions,
             reservation: output_paths.RunReservation, catalog: SupportedTypeCatalog | None = None,
             import_options: ImportOptions | None = None, effective_config: Any = None,
             id_factory: IdFactory | None = None, created_at: float = 0.0,
             capture: BookRunSnapshot | None = None,
             checkpoint: Callable[[], None] | None = None,
             progress: Callable[[int, int], None] | None = None) -> RunPlan:
    """Freeze one Editor action over the whole workspace. Creates nothing on disk.

    The reservation is the caller's — taken once, before this is called — and
    every output is planned through its planner. With Auto-number on for a Save
    the Start Part is parsed first, so an unreadable one refuses the whole
    operation through the model's own ``EditorValueError`` before a name is
    planned. Books whose source could not be read are skipped as invalid by
    the shared capture and keep their identity in the plan's skips.

    v0.8.2: the panel plans on a worker, where this takes the capture from the
    four capture inputs. A caller may pass a *capture* it took itself
    (:func:`capture_for_run`) instead. Also a *checkpoint*
    that raises to stop a cancelled preparation (called between sources and
    Books) and a *progress* callback told ``(Books planned, Books)``. A
    supplied capture must describe this workspace and store
    (:func:`_require_capture_matches`).
    """
    if not isinstance(workspace, WorkspaceSnapshot):
        raise PlanError(f"workspace must be a WorkspaceSnapshot, got {type(workspace).__name__}")
    if not isinstance(store, ObservationStore):
        raise PlanError(f"store must be an ObservationStore, got {type(store).__name__}")
    if not isinstance(action, EditorAction):
        raise PlanError(f"action must be an EditorAction, got {type(action).__name__}")
    if not isinstance(options, EditorRunOptions):
        raise PlanError(f"options must be EditorRunOptions, got {type(options).__name__}")
    if not isinstance(reservation, output_paths.RunReservation):
        raise PlanError(
            f"reservation must be an output_paths.RunReservation, got {type(reservation).__name__}")
    if capture is None:
        if catalog is None or import_options is None or id_factory is None:
            raise PlanError("a plan needs either a capture or the catalog, import options and id factory to take one")
    elif not isinstance(capture, BookRunSnapshot):
        raise PlanError(f"capture must be a BookRunSnapshot, got {type(capture).__name__}")
    check = checkpoint if checkpoint is not None else _no_checkpoint

    # Removal never numbers; a Save with Auto-number parses its Start Part first.
    numbering = bool(options.auto_number) and action is not EditorAction.REMOVE_SERIES_NUMBERING
    start_part = wf.parse_start_part(options.start_part_text) if numbering else 1

    run_directory = Path(reservation.run_directory)
    sources = [entry.path for book in workspace.books for entry in book.files.files]
    check()
    output_paths.assert_outside_source_trees(run_directory, {path.parent for path in sources})

    observations = _observations(workspace, store)
    if capture is None:
        capture = capture_workspace_run(
            workspace, catalog=catalog, import_options=import_options,
            effective_config=effective_config, id_factory=id_factory,
            created_at=created_at, is_valid=_readable_in(observations))
    else:
        _require_capture_matches(capture, workspace, observations)

    # Every source occurrence of the workspace, normalised once for this plan only (never shared or reused).
    inputs = output_paths.InputIndex(sources, checkpoint=check)

    planner = reservation.planner()
    work_root = planner.plan_directory(WORK_DIRNAME)
    positions = {book.book_id: index for index, book in enumerate(workspace.books, start=1)}
    books_by_id = {book.book_id: book for book in workspace.books}
    plans: list[BookPlan] = []
    total = len(capture.runs)
    for done, (book_id, snapshot) in enumerate(capture.runs):
        check()
        if progress is not None:
            progress(done, total)
        book = books_by_id[book_id]
        plans.append(_plan_book(
            book, snapshot, action=action, shared=workspace.shared, store=store,
            observation=observations[book_id], number=positions[book_id],
            planner=planner, work_root=work_root, inputs=inputs))
    check()
    if progress is not None:
        progress(total, total)
    return RunPlan(action=action, reservation=reservation, run_directory=run_directory,
                   work_root=work_root, capture=capture, books=tuple(plans),
                   observations=MappingProxyType(observations),
                   auto_number=numbering, start_part=start_part)


def _require_capture_matches(capture: BookRunSnapshot, workspace: WorkspaceSnapshot,
                             observations: Mapping[str, SourceObservation]) -> None:
    """Refuse a capture that is not a capture of *workspace* and its store as they stand (v0.8.2). Linear; no disk.

    The plan takes each Book's source, observation and explicit intent from the workspace and the store and freezes
    them beside the capture, which the run's result and Retry Failed are settled against, so the two must describe
    one workspace -- the capture's own contract (``capture_workspace_run`` with the store's readable predicate): the
    same Shared Metadata; the same Books attempted and skipped (empty or unreadable), in workspace order; and for
    every attempted Book the same imported source and the same effective run options.
    """
    if capture.shared != workspace.shared:
        raise PlanError("the capture was taken with different Shared settings than this workspace holds")
    readable = _readable_in(observations)
    attempted = [book.book_id for book in workspace.books if not book.is_empty and readable(book)]
    skipped = [book.book_id for book in workspace.books if book.is_empty or not readable(book)]
    if list(capture.attempted_book_ids) != attempted or list(capture.skipped_book_ids) != skipped:
        raise PlanError("the capture's Books, or their order, differ from this workspace's")
    books_by_id = {book.book_id: book for book in workspace.books}
    for book_id, snapshot in capture.runs:
        book = books_by_id[book_id]
        if snapshot.files is not book.files and snapshot.files != book.files:
            raise PlanError(f"the capture of Book {book_id} holds a different source than this workspace")
        if snapshot.tool_options != freeze_options(effective_run_options(book, workspace.shared)):
            raise PlanError(f"the capture of Book {book_id} was taken with different settings than this "
                            "workspace holds")


def _no_checkpoint() -> None:
    """The synchronous caller's checkpoint: nothing can cancel it."""


def _plan_book(book: BookJob, snapshot: RunSnapshot, *, action: EditorAction, shared, store,
               observation: SourceObservation, number: int, planner, work_root: Path,
               inputs: output_paths.InputIndex) -> BookPlan:
    source = wf.source_of(book)
    if source is None:  # pragma: no cover - the capture skips empty Books
        raise PlanError(f"Book {number} holds no source")

    if action is EditorAction.REMOVE_SERIES_NUMBERING:
        # The action alone: pending edits visible in the workspace are not it.
        shared_overrides: Mapping[str, str] = _EMPTY
        book_edits: Mapping[str, str] = _EMPTY
        artwork = None
        chapter_edits: tuple[str | None, ...] = ()
    else:
        shared_overrides = wf.shared_intent(shared)
        explicit = wf.explicit_edits(shared, book, store)
        # A field the Shared value overrides is not also a Book edit.
        book_edits = MappingProxyType({name: value for name, value in explicit.items()
                                       if name not in shared_overrides})
        artwork = wf.artwork_intent(shared, book)
        chapter_edits = wf.chapter_edits(book, observation)

    # Named by the source file, extension kept; sanitised and collision-numbered
    # by the shared planner inside the one run.
    published = planner.plan(source.path.name)
    filename = published.name
    staging_dir = work_root / output_paths.split_suffix(filename)[0]
    staged = staging_dir / filename
    inputs.assert_not_input(published)
    inputs.assert_not_input(staged)

    return BookPlan(
        book_id=book.book_id, number=number, action=action, snapshot=snapshot,
        occurrence_id=source.occurrence_id, source=source.path, observation=observation,
        shared_overrides=shared_overrides, book_edits=book_edits, artwork=artwork,
        chapter_edits=tuple(chapter_edits), filename=filename, staging_dir=staging_dir,
        staged=staged, published=published)
