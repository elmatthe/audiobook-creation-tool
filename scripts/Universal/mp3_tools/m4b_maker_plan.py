"""The frozen M4B Maker run plan — v0.6.4 Phase 3.

One Maker operation is planned **once, completely, before any media is
touched**, and the plan is the only thing the processing phases (4–5) and a
later Retry Failed ever read. Nothing here runs FFmpeg, normalises audio,
writes a chapter, a tag or a cover, starts a controller, allocates a series
number or retries anything — and planning creates nothing on disk.

What is frozen
--------------
- **The destination.** Exactly one :class:`MakerDestination` for the whole
  operation: in **standard** mode the one shared
  :class:`~shared.output_paths.RunReservation` (``M4B-Maker-N``) whose planner
  is the collision authority for every output below, staging under the run's
  own ``.work`` area; in **custom** mode the user's validated folder used
  *directly* — no ``M4B-Maker-N`` is nested inside it — with a planner rooted
  there and staging in an operation-owned work root the caller supplies
  **outside** that folder, so a user's folder is never littered (the existing
  Maker's behaviour, preserved).
- **The Books.** The Plan 6 capture (:func:`~shared.book_workspace.capture_workspace_run`)
  decides which Books are eligible (an empty Book is skipped) and freezes each
  one's exact ``RunSnapshot`` — the object identity the retry contract holds.
  This module adds one :class:`BookPlan` per attempted Book, in frozen order.
- **Per Book:** stable id, workspace position, exact occurrences and source
  paths in order, the complete final chapter-title tuple
  (:func:`~mp3_tools.m4b_maker_workflow.book_chapter_titles`), the embedded
  Title (the Book's own, or the deterministic fallback below), effective
  Artist / Album Artist / Album / Series Name, the manual Series Part text
  (``None`` while Auto-number is on), the effective artwork path, the parsed
  effective Silence, and the final ``.m4b`` path with its private staging
  directory and staged path.
- **Per run:** the Fast-first option, Auto-number and the parsed Start Part —
  **configuration only**. No success number is proposed, consumed or committed
  here; that is Phase 5's success-driven allocation.

Naming (Decision 51A, plan section 5.8)
---------------------------------------
Explicit Output Filename → Title → effective Album → the one source folder that
directly contains every track → ``Book N``. The candidates come from the model
(:func:`~mp3_tools.m4b_maker_workflow.output_name_candidates`); the first whose
sanitised stem is still readable is used, sanitised by the shared sanitiser,
given ``.m4b`` exactly once, and collision-numbered by the shared planner.
Never a local regex. The output filename and the embedded Title are distinct:
a blank Title falls back to the same resolved name (unsanitised), so no Book
is ever nameless (section 5.7).

Safety
------
A standard run may not lie inside a source tree
(:func:`~shared.output_paths.assert_outside_source_trees`); custom mode is the
explicit, separately confirmed exception and may write beside the sources — but
never onto one: every planned output and staged path is checked with
:func:`~shared.output_paths.assert_not_input`, and the planner keeps every
output contained in its root.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
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
from mp3_tools import m4b_maker_workflow as wf

__all__ = [
    "PlanError",
    "DestinationMode",
    "MakerDestination",
    "MakerRunOptions",
    "BookPlan",
    "RunPlan",
    "WORK_DIRNAME",
    "M4B_SUFFIX",
    "standard_destination",
    "custom_destination",
    "output_filename",
    "plan_run",
]


class PlanError(Exception):
    """A plan could not be built from what it was given."""


class DestinationMode(Enum):
    STANDARD = "standard"
    CUSTOM = "custom"


#: The private, unpublished work area under a standard run. Dot-prefixed so it
#: is visibly internal beside the published M4Bs, and reserved with the planner
#: before any output so a Book that happens to be called ``.work`` is numbered
#: away from it.
WORK_DIRNAME = ".work"

M4B_SUFFIX = ".m4b"


# --------------------------------------------------------------------------- #
# The vocabulary
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MakerDestination:
    """Where one operation publishes and where it stages. One per operation.

    ``root`` is the directory the final M4Bs land in directly. ``work_root`` is
    the operation-owned staging area: under the run for a standard destination,
    supplied by the caller and outside the chosen folder for a custom one.
    """

    mode: DestinationMode
    root: Path
    work_root: Path
    reservation: output_paths.RunReservation | None = None


@dataclass(frozen=True)
class MakerRunOptions:
    """The batch-level run options, raw as the panel captured them."""

    auto_number: bool = False
    start_part_text: str = ""
    fast_first: bool = True


@dataclass(frozen=True)
class BookPlan:
    """One attempted Book, frozen, carrying its exact Plan 6 ``RunSnapshot``."""

    book_id: str
    number: int
    snapshot: RunSnapshot
    occurrence_ids: tuple[str, ...]
    sources: tuple[Path, ...]
    chapter_titles: tuple[str, ...]
    title: str
    artist: str
    album_artist: str
    album: str
    series: str
    #: The Book's own Series Part text while Auto-number is off; ``None`` while
    #: it is on, because the run's number is then Phase 5's to allocate.
    series_part: str | None
    artwork: Path | None
    silence: float
    filename: str
    staging_dir: Path
    staged: Path
    published: Path


@dataclass(frozen=True)
class RunPlan:
    """The whole operation, frozen. Holds no workspace and no widget."""

    destination: MakerDestination
    capture: BookRunSnapshot
    books: tuple[BookPlan, ...]
    auto_number: bool
    start_part: int
    fast_first: bool

    @property
    def mode(self) -> DestinationMode:
        return self.destination.mode

    @property
    def root(self) -> Path:
        return self.destination.root

    @property
    def work_root(self) -> Path:
        return self.destination.work_root

    def book_for(self, book_id: str) -> BookPlan | None:
        for entry in self.books:
            if entry.book_id == book_id:
                return entry
        return None


# --------------------------------------------------------------------------- #
# Destinations
# --------------------------------------------------------------------------- #


def standard_destination(reservation: output_paths.RunReservation) -> MakerDestination:
    """The one reserved ``M4B-Maker-N`` run, staging under its own ``.work``."""
    if not isinstance(reservation, output_paths.RunReservation):
        raise PlanError(
            f"reservation must be an output_paths.RunReservation, got {type(reservation).__name__}")
    root = Path(reservation.run_directory)
    return MakerDestination(mode=DestinationMode.STANDARD, root=root,
                            work_root=root / WORK_DIRNAME, reservation=reservation)


def custom_destination(directory: object, *, work_root: object) -> MakerDestination:
    """The user's folder, used directly, with an operation-owned work root elsewhere.

    The folder is proved usable by the shared authority
    (:func:`~shared.output_paths.validate_custom_destination`). The work root
    is the caller's — an absolute path it owns for this operation — and must
    not be the chosen folder or lie inside it, so staging never appears among
    the user's files.
    """
    try:
        root = output_paths.validate_custom_destination(directory)
    except output_paths.OutputPathError as exc:
        raise PlanError(str(exc)) from exc
    work = Path(str(work_root))
    if not work.is_absolute():
        raise PlanError(f"the custom work root must be an absolute path, got {work_root!r}")
    inside = False
    try:
        # ``assert_contained`` answers "is it strictly under root"; the root
        # itself is checked separately. Both are refused, because staging
        # among the user's files is what the separate work root prevents.
        output_paths.assert_contained(root, work)
        inside = True
    except output_paths.UnsafePathError:
        inside = False
    if inside or work == root or work.resolve() == root:
        raise PlanError(
            f"the custom work root {work} is the destination {root} or lies inside it; "
            "staging must not litter the chosen folder")
    return MakerDestination(mode=DestinationMode.CUSTOM, root=root, work_root=work)


# --------------------------------------------------------------------------- #
# Naming
# --------------------------------------------------------------------------- #


def _strip_m4b(name: str) -> str:
    """One trailing ``.m4b`` removed, case-insensitively, so it is never doubled."""
    if name.lower().endswith(M4B_SUFFIX):
        return name[: -len(M4B_SUFFIX)]
    return name


def output_filename(candidate: str) -> str:
    """One candidate as a final filename: sanitised, ``.m4b`` exactly once."""
    stem = output_paths.sanitize_component(_strip_m4b(str(candidate).strip()))
    return f"{stem}{M4B_SUFFIX}"


def _readable(filename: str) -> bool:
    """A sanitised name that kept no letter or digit is not a name a user can find."""
    stem = _strip_m4b(filename)
    return any(character.isalnum() for character in stem)


def _resolve_name(candidates: Sequence[str]) -> tuple[str, str]:
    """``(unsanitised candidate, sanitised filename)`` for the first usable candidate.

    The candidates are the model's Decision 51A chain; ``Book N`` is always
    last and always readable, so this cannot fall off the end.
    """
    for candidate in candidates:
        filename = output_filename(candidate)
        if _readable(filename):
            return candidate, filename
    raise PlanError(f"no usable output name among {tuple(candidates)!r}")


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #


def plan_run(workspace: WorkspaceSnapshot, *, options: MakerRunOptions,
             destination: MakerDestination, catalog: SupportedTypeCatalog,
             import_options: ImportOptions, effective_config: Any,
             id_factory: IdFactory, created_at: float = 0.0) -> RunPlan:
    """Freeze one Maker operation over the whole workspace. Creates nothing on disk.

    The destination is the caller's — reserved or validated once, before this
    is called — and every output is planned through its planner. A Book with an
    unreadable Silence, or an unreadable Start Part with Auto-number on,
    refuses the whole operation up front through the model's own
    ``MakerValueError``, before a single name is planned.
    """
    if not isinstance(workspace, WorkspaceSnapshot):
        raise PlanError(f"workspace must be a WorkspaceSnapshot, got {type(workspace).__name__}")
    if not isinstance(options, MakerRunOptions):
        raise PlanError(f"options must be a MakerRunOptions, got {type(options).__name__}")
    if not isinstance(destination, MakerDestination):
        raise PlanError(
            f"destination must be a MakerDestination, got {type(destination).__name__}")

    # Every Book's inputs are parsed before a single name is planned.
    start_part = wf.parse_start_part(options.start_part_text) if options.auto_number else 1
    silences: dict[str, float] = {}
    for book in workspace.books:
        if book.files.is_empty:
            continue
        silences[book.book_id] = wf.effective_silence(workspace.shared, book)

    all_sources = [entry.path for book in workspace.books for entry in book.files.files]
    if destination.mode is DestinationMode.STANDARD:
        # Custom mode is the explicit exception that may sit beside the sources.
        output_paths.assert_outside_source_trees(
            destination.root, {path.parent for path in all_sources})

    capture = capture_workspace_run(
        workspace, catalog=catalog, import_options=import_options,
        effective_config=effective_config, id_factory=id_factory,
        created_at=created_at)

    planner = output_paths.DestinationPlanner(destination.root)
    if destination.mode is DestinationMode.STANDARD:
        # Reserved first so no output can take the work area's name.
        planner.plan_directory(WORK_DIRNAME)

    positions = {book.book_id: index for index, book in enumerate(workspace.books, start=1)}
    books_by_id = {book.book_id: book for book in workspace.books}
    plans: list[BookPlan] = []
    for book_id, snapshot in capture.runs:
        book = books_by_id[book_id]
        plans.append(_plan_book(
            book, snapshot, shared=workspace.shared, number=positions[book_id],
            planner=planner, destination=destination, silence=silences[book_id],
            auto_number=options.auto_number, all_sources=all_sources))
    return RunPlan(destination=destination, capture=capture, books=tuple(plans),
                   auto_number=bool(options.auto_number), start_part=start_part,
                   fast_first=bool(options.fast_first))


def _collapse(text: object) -> str:
    return " ".join(str(text).split())


def _plan_book(book: BookJob, snapshot: RunSnapshot, *, shared, number: int, planner,
               destination: MakerDestination, silence: float, auto_number: bool,
               all_sources) -> BookPlan:
    values = wf.effective_values(shared, book)
    artwork_text = str(values["artwork"]).strip()
    artwork = Path(artwork_text) if artwork_text else None

    candidates = wf.output_name_candidates(shared, book, number)
    resolved, wanted = _resolve_name(candidates)
    published = planner.plan(wanted)
    filename = published.name
    # Staging is keyed by the *final* (collision-numbered) stem, so two Books
    # that resolved to the same name also stage apart.
    staging_dir = destination.work_root / _strip_m4b(filename)
    staged = staging_dir / filename
    output_paths.assert_not_input(published, all_sources)
    output_paths.assert_not_input(staged, all_sources)

    title = _collapse(wf.title_text(book)) or _collapse(resolved)
    files = book.files.files
    return BookPlan(
        book_id=book.book_id, number=number, snapshot=snapshot,
        occurrence_ids=tuple(entry.occurrence_id for entry in files),
        sources=tuple(entry.path for entry in files),
        chapter_titles=wf.book_chapter_titles(book),
        title=title,
        artist=str(values["artist"]), album_artist=str(values["album_artist"]),
        album=str(values["album"]), series=str(values["series"]),
        series_part=None if auto_number else wf.series_part_text(book),
        artwork=artwork, silence=silence,
        filename=filename, staging_dir=staging_dir, staged=staged, published=published)
