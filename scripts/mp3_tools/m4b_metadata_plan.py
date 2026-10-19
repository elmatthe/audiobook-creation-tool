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
  :class:`~mp3_tools.m4b_metadata_workflow.SourceObservation` (what the source
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
"""

from __future__ import annotations

from collections.abc import Mapping
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
)
from shared.importing import IdFactory, ImportOptions, SupportedTypeCatalog
from shared.job_control import RunSnapshot
from mp3_tools import m4b_metadata_workflow as wf
from mp3_tools.m4b_metadata_workflow import ObservationStore, SourceObservation

__all__ = [
    "PlanError",
    "EditorAction",
    "EditorRunOptions",
    "BookPlan",
    "RunPlan",
    "WORK_DIRNAME",
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


def plan_run(workspace: WorkspaceSnapshot, store: ObservationStore, *,
             action: EditorAction, options: EditorRunOptions,
             reservation: output_paths.RunReservation, catalog: SupportedTypeCatalog,
             import_options: ImportOptions, effective_config: Any, id_factory: IdFactory,
             created_at: float = 0.0) -> RunPlan:
    """Freeze one Editor action over the whole workspace. Creates nothing on disk.

    The reservation is the caller's — taken once, before this is called — and
    every output is planned through its planner. With Auto-number on for a Save
    the Start Part is parsed first, so an unreadable one refuses the whole
    operation through the model's own ``EditorValueError`` before a name is
    planned. Books whose source could not be read are skipped as invalid by
    the shared capture and keep their identity in the plan's skips.
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

    # Removal never numbers; a Save with Auto-number parses its Start Part first.
    numbering = bool(options.auto_number) and action is not EditorAction.REMOVE_SERIES_NUMBERING
    start_part = wf.parse_start_part(options.start_part_text) if numbering else 1

    run_directory = Path(reservation.run_directory)
    sources = [entry.path for book in workspace.books for entry in book.files.files]
    output_paths.assert_outside_source_trees(run_directory, {path.parent for path in sources})

    observations: dict[str, SourceObservation] = {}
    for book in workspace.books:
        seen = store.for_book(book)
        if seen is not None:
            observations[book.book_id] = seen

    def readable(book: BookJob) -> bool:
        seen = observations.get(book.book_id)
        return seen is not None and seen.readable

    capture = capture_workspace_run(
        workspace, catalog=catalog, import_options=import_options,
        effective_config=effective_config, id_factory=id_factory,
        created_at=created_at, is_valid=readable)

    planner = reservation.planner()
    work_root = planner.plan_directory(WORK_DIRNAME)
    positions = {book.book_id: index for index, book in enumerate(workspace.books, start=1)}
    books_by_id = {book.book_id: book for book in workspace.books}
    plans: list[BookPlan] = []
    for book_id, snapshot in capture.runs:
        book = books_by_id[book_id]
        plans.append(_plan_book(
            book, snapshot, action=action, shared=workspace.shared, store=store,
            observation=observations[book_id], number=positions[book_id],
            planner=planner, work_root=work_root, all_sources=sources))
    return RunPlan(action=action, reservation=reservation, run_directory=run_directory,
                   work_root=work_root, capture=capture, books=tuple(plans),
                   observations=MappingProxyType(observations),
                   auto_number=numbering, start_part=start_part)


def _plan_book(book: BookJob, snapshot: RunSnapshot, *, action: EditorAction, shared, store,
               observation: SourceObservation, number: int, planner, work_root: Path,
               all_sources) -> BookPlan:
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
    output_paths.assert_not_input(published, all_sources)
    output_paths.assert_not_input(staged, all_sources)

    return BookPlan(
        book_id=book.book_id, number=number, action=action, snapshot=snapshot,
        occurrence_id=source.occurrence_id, source=source.path, observation=observation,
        shared_overrides=shared_overrides, book_edits=book_edits, artwork=artwork,
        chapter_edits=tuple(chapter_edits), filename=filename, staging_dir=staging_dir,
        staged=staged, published=published)
