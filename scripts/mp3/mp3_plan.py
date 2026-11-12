"""The frozen MP3 run plan — v0.6.3 focused MP3 Tool redesign, Phase 5.

One operation — Write ID3 Tags or Combine MP3s → One MP3 — is planned **once,
completely, before any media is touched**, and the plan is the only thing the
processing phases and a later Retry Failed ever read. Nothing here runs FFmpeg,
writes a tag, embeds artwork, starts a controller or retries anything.

What is frozen
--------------
- **The run.** Exactly one shared :class:`~shared.output_paths.RunReservation`
  for the whole operation, never one per Book. Its
  :class:`~shared.output_paths.DestinationPlanner` is the one collision
  authority for every folder and file below.
- **The Books.** The Plan 6 capture (:func:`~shared.book_workspace.capture_workspace_run`)
  decides which Books are eligible and freezes each one's effective options and
  its exact ``RunSnapshot`` — the object identity the Plan 7 retry contract
  holds. This module adds one :class:`BookPlan` per attempted Book, carrying
  that snapshot, in the frozen Book order.
- **Per Book:** stable id, effective Artist / Album Artist / Album, signed Time,
  artwork, Auto-number, parsed Start #, the complete final Title tuple
  (:func:`~mp3.mp3_workflow.book_titles` — partial Chapter Titles
  override only their positions, blank lines collapse), the Book's output folder
  name and its **published** and **staging** directories.
- **Per track:** occurrence id, source path, position, Title, Track Number (a
  plain ``int`` when Auto-number is on, else ``None``), final filename, and its
  staged and published paths. Combine adds the one combined MP3 and the
  timestamp sheet.

Naming (focused plan sections 16 and 20)
----------------------------------------
Book folder and combined filename: effective Album → the one source folder that
directly contains every track → ``Book N``; sanitised by the shared sanitiser;
collision-numbered by the shared planner inside the one run. Track filenames come
from the final Title: one existing leading track number is removed, the name is
sanitised, and — with Auto-number on — the calculated number is added exactly
once, at least two digits wide and wider when the last number needs it. Track
Numbers written to tags are ordinary integers; padding is a filename concern.

Staging and publication (section 21)
------------------------------------
Every Book has a private staging directory under the run's ``.work`` area, named
like its published folder. Processing writes there and nowhere else. A Book is
**published** only when every planned output exists in staging; publication moves
them into the Book's visible folder file by file and rolls back on any failure,
so a failed Book never appears as a partial result while its successful pieces
survive in staging for a retry. Cleanup removes only what lies under the run's
own work area and never follows a link out of it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Collection, Mapping
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
from mp3 import mp3_workflow as wf

__all__ = [
    "PlanError",
    "MP3Operation",
    "WORK_DIRNAME",
    "TIMESTAMPS_NAME",
    "MP3_SUFFIX",
    "TrackPlan",
    "BookPlan",
    "RunPlan",
    "plan_run",
    "book_folder_name",
    "track_filename",
    "number_width",
    "strip_leading_number",
    "prepare_staging",
    "publish_book",
    "is_published",
    "discard_staging",
    "discard_run_staging",
    "release_staging",
]


class PlanError(Exception):
    """A plan could not be built, or a publication boundary was violated."""


class MP3Operation(Enum):
    WRITE_ID3 = "write_id3"
    COMBINE = "combine"


#: The private, unpublished work area under one run. Dot-prefixed so it is
#: visibly internal beside the Book folders, and reserved with the planner
#: before any Book folder so a Book that happens to be called ``.work`` is
#: numbered away from it.
WORK_DIRNAME = ".work"

#: The Combine timestamp sheet, retained from the original tool.
TIMESTAMPS_NAME = "combined_time-stamps.txt"

MP3_SUFFIX = ".mp3"

#: Minimum width of the calculated filename prefix.
MIN_NUMBER_WIDTH = 2

_LEADING_NUMBER = re.compile(r"^\s*\d{1,3}(?:[\s._\-:)\]]+|$)")


# --------------------------------------------------------------------------- #
# The vocabulary
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TrackPlan:
    """One track of one Book, frozen: what it is called and where it goes."""

    occurrence_id: str
    source: Path
    position: int
    title: str
    track_number: int | None
    filename: str
    staged: Path
    published: Path


@dataclass(frozen=True)
class BookPlan:
    """One attempted Book, frozen, carrying its exact Plan 6 ``RunSnapshot``."""

    book_id: str
    number: int
    snapshot: RunSnapshot
    operation: MP3Operation
    folder_name: str
    published_dir: Path
    staging_dir: Path
    artist: str
    album_artist: str
    album: str
    time_delta: float
    artwork: Path | None
    auto_number: bool
    start_number: int
    tracks: tuple[TrackPlan, ...]
    combined_filename: str | None = None
    combined_staged: Path | None = None
    combined_published: Path | None = None
    timestamps_staged: Path | None = None
    timestamps_published: Path | None = None

    @property
    def source_paths(self) -> tuple[Path, ...]:
        return tuple(entry.source for entry in self.tracks)

    def track_for(self, occurrence_id: str) -> TrackPlan | None:
        for entry in self.tracks:
            if entry.occurrence_id == occurrence_id:
                return entry
        return None

    @property
    def staged_outputs(self) -> tuple[Path, ...]:
        """Every file that must exist in staging before the Book may publish."""
        if self.operation is MP3Operation.COMBINE:
            return (self.combined_staged, self.timestamps_staged)  # type: ignore[return-value]
        return tuple(entry.staged for entry in self.tracks)

    @property
    def published_outputs(self) -> tuple[Path, ...]:
        """Where those same files are, once the Book is published."""
        if self.operation is MP3Operation.COMBINE:
            return (self.combined_published, self.timestamps_published)  # type: ignore[return-value]
        return tuple(entry.published for entry in self.tracks)


@dataclass(frozen=True)
class RunPlan:
    """The whole operation, frozen. Holds no workspace and no widget."""

    operation: MP3Operation
    reservation: output_paths.RunReservation
    run_directory: Path
    work_root: Path
    capture: BookRunSnapshot
    books: tuple[BookPlan, ...]

    def book_for(self, book_id: str) -> BookPlan | None:
        for entry in self.books:
            if entry.book_id == book_id:
                return entry
        return None


# --------------------------------------------------------------------------- #
# Naming rules
# --------------------------------------------------------------------------- #


def strip_leading_number(text: str) -> str:
    """Remove one leading one-to-three-digit track number and its separator."""
    stripped = _LEADING_NUMBER.sub("", str(text), count=1)
    return stripped if stripped.strip() else str(text)


def number_width(start_number: int, count: int) -> int:
    """At least two digits; wider when the Book's last number needs it."""
    last = max(int(start_number), 1) + max(int(count), 1) - 1
    return max(MIN_NUMBER_WIDTH, len(str(last)))


def track_filename(title: str, *, source_name: str, number: int | None,
                   width: int) -> str:
    """The final filename for one track, before collision planning.

    From the final Title: one existing leading number is removed so a
    calculated one is never doubled, the name is sanitised, and the number is
    added exactly once when Auto-number is on. A Title that leaves no letter
    or digit once sanitised (``???`` becomes ``___``) falls back to the
    source's own cleaned name rather than to an unreadable placeholder.
    """
    base = strip_leading_number(title).strip()
    safe = output_paths.sanitize_component(base) if base else ""
    if not any(character.isalnum() for character in safe):
        fallback = strip_leading_number(Path(source_name).stem).strip()
        safe = output_paths.sanitize_component(fallback or Path(source_name).stem)
    if number is None:
        return f"{safe}{MP3_SUFFIX}"
    return f"{number:0{width}d} {safe}{MP3_SUFFIX}"


def book_folder_name(album: str, source_folder: str | None, number: int) -> str:
    """Effective Album → source containing folder → ``Book N``, unsanitised."""
    album = " ".join(str(album or "").split())
    if album:
        return album
    if source_folder:
        return source_folder
    return f"Book {int(number)}"


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #


def plan_run(workspace: WorkspaceSnapshot, store: wf.ObservationStore, *,
             operation: MP3Operation, reservation: output_paths.RunReservation,
             catalog: SupportedTypeCatalog, import_options: ImportOptions,
             effective_config: Any, id_factory: IdFactory, created_at: float = 0.0,
             numbers: Mapping[str, int] | None = None) -> RunPlan:
    """Freeze one operation over the whole workspace. Creates nothing on disk.

    The reservation is the caller's — taken once, before this is called — and
    every folder and file is planned through its planner. Validation errors in a
    Book's Start # or Time surface as the model's own ``MP3ValueError`` before
    anything is planned, so a refused plan leaves the (still empty) run for the
    caller to release.
    """
    if not isinstance(operation, MP3Operation):
        raise PlanError(f"operation must be an MP3Operation, got {type(operation).__name__}")
    if not isinstance(reservation, output_paths.RunReservation):
        raise PlanError(
            f"reservation must be an output_paths.RunReservation, got {type(reservation).__name__}")
    if not isinstance(store, wf.ObservationStore):
        raise PlanError(f"store must be an ObservationStore, got {type(store).__name__}")
    number_map = dict(numbers or {})

    # Every Book's inputs are parsed before a single name is planned: a Book
    # with an unreadable Start # refuses the whole operation up front, exactly
    # as the panel's own validation does.
    parsed: dict[str, tuple[int, float]] = {}
    for book in workspace.books:
        if book.files.is_empty:
            continue
        scalars = wf.effective_scalars(workspace.shared, book)
        parsed[book.book_id] = (
            wf.parse_start_number(wf.start_number_text(book)),
            wf.parse_time_delta(str(scalars.get("time_delta", ""))),
        )

    run_directory = Path(reservation.run_directory)
    all_sources = [entry.path for book in workspace.books for entry in book.files.files]
    output_paths.assert_outside_source_trees(
        run_directory, {path.parent for path in all_sources})

    capture = capture_workspace_run(
        workspace, catalog=catalog, import_options=import_options,
        effective_config=effective_config, id_factory=id_factory,
        created_at=created_at)

    planner = reservation.planner()
    work_root = planner.plan_directory(WORK_DIRNAME)
    books_by_id = {book.book_id: book for book in workspace.books}
    plans: list[BookPlan] = []
    for position, (book_id, snapshot) in enumerate(capture.runs, start=1):
        book = books_by_id[book_id]
        number = int(number_map.get(book_id, position))
        plans.append(_plan_book(
            book, snapshot, store=store, shared=workspace.shared, operation=operation,
            number=number, planner=planner, work_root=work_root,
            run_directory=run_directory, parsed=parsed[book_id],
            all_sources=all_sources))
    return RunPlan(operation=operation, reservation=reservation,
                   run_directory=run_directory, work_root=work_root,
                   capture=capture, books=tuple(plans))


def _plan_book(book: BookJob, snapshot: RunSnapshot, *, store, shared, operation,
               number, planner, work_root, run_directory, parsed, all_sources) -> BookPlan:
    start_number, time_delta = parsed
    scalars = wf.effective_scalars(shared, book)
    artist = str(scalars.get("artist", ""))
    album_artist = str(scalars.get("album_artist", ""))
    album = str(scalars.get("album", ""))
    artwork_text = str(scalars.get("artwork", "")).strip()
    artwork = Path(artwork_text) if artwork_text else None
    auto_number = wf.auto_number_enabled(book)

    folder = book_folder_name(album, wf.source_folder_name(book), number)
    published_dir = planner.plan_directory(folder)
    folder_name = published_dir.name
    staging_dir = work_root / folder_name

    titles = wf.book_titles(book, store)
    files = book.files.files
    width = number_width(start_number, len(files))
    tracks: list[TrackPlan] = []
    for index, (entry, title) in enumerate(zip(files, titles), start=1):
        track_number = start_number + index - 1 if auto_number else None
        wanted = track_filename(title, source_name=entry.name, number=track_number,
                                width=width)
        published = planner.plan(wanted, subdir=folder_name)
        staged = staging_dir / published.name
        output_paths.assert_not_input(published, all_sources)
        output_paths.assert_not_input(staged, all_sources)
        tracks.append(TrackPlan(
            occurrence_id=entry.occurrence_id, source=entry.path, position=index,
            title=title, track_number=track_number, filename=published.name,
            staged=staged, published=published))

    combined_filename = combined_staged = combined_published = None
    timestamps_staged = timestamps_published = None
    if operation is MP3Operation.COMBINE:
        combined_published = planner.plan(f"{folder}{MP3_SUFFIX}", subdir=folder_name)
        combined_filename = combined_published.name
        combined_staged = staging_dir / combined_filename
        timestamps_published = planner.plan(TIMESTAMPS_NAME, subdir=folder_name)
        timestamps_staged = staging_dir / timestamps_published.name
        for path in (combined_published, combined_staged):
            output_paths.assert_not_input(path, all_sources)

    return BookPlan(
        book_id=book.book_id, number=number, snapshot=snapshot, operation=operation,
        folder_name=folder_name, published_dir=published_dir, staging_dir=staging_dir,
        artist=artist, album_artist=album_artist, album=album, time_delta=time_delta,
        artwork=artwork, auto_number=auto_number, start_number=start_number,
        tracks=tuple(tracks), combined_filename=combined_filename,
        combined_staged=combined_staged, combined_published=combined_published,
        timestamps_staged=timestamps_staged, timestamps_published=timestamps_published)


# --------------------------------------------------------------------------- #
# Staging and publication boundaries
# --------------------------------------------------------------------------- #


def _work_root_of(book: BookPlan) -> Path:
    """The run's work area this Book's staging must sit directly under."""
    return book.staging_dir.parent


def _require_owned(book: BookPlan) -> None:
    """The staging directory must be ``<run>/<WORK_DIRNAME>/<folder>``, exactly."""
    work_root = _work_root_of(book)
    run_directory = work_root.parent
    if work_root.name != WORK_DIRNAME or book.published_dir.parent != run_directory:
        raise PlanError(
            f"staging {book.staging_dir} is not the private work area of run {run_directory}")
    output_paths.assert_contained(run_directory, book.staging_dir)


def prepare_staging(book: BookPlan) -> Path:
    """Create the Book's private staging directory. Idempotent. Nothing visible."""
    _require_owned(book)
    output_paths.assert_no_link_in(_work_root_of(book).parent, book.staging_dir)
    book.staging_dir.mkdir(parents=True, exist_ok=True)
    return book.staging_dir


def is_published(book: BookPlan) -> bool:
    outputs = book.published_outputs
    return bool(outputs) and all(path.is_file() for path in outputs)


def _identity(path: Path) -> tuple[int, int]:
    """Which file *path* names, on its volume. A move keeps it; another writer's file has its own."""
    info = os.lstat(path)
    return info.st_dev, info.st_ino


#: Whether a roll-back can move a published file back by an operation bound to that file rather than to its name. Only
#: Windows offers one (a rename made through a handle that also denies everyone else deletion of the file); elsewhere a
#: roll-back leaves what it published where it is and says so (v0.7.2 Phase 9 focused closure, R9-03).
_CAN_TAKE_BACK = os.name == "nt"
_WIN32: tuple | None = None


def _win32() -> tuple:
    """``(ctypes, kernel32, FILE_RENAME_INFO)``, made once, on Windows only."""
    global _WIN32
    if _WIN32 is None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
        kernel32.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        class RenameInfo(ctypes.Structure):  # FILE_RENAME_INFO; the name runs on past its one declared character
            _fields_ = [("ReplaceIfExists", wintypes.DWORD), ("RootDirectory", wintypes.HANDLE),
                        ("FileNameLength", wintypes.DWORD), ("FileName", wintypes.WCHAR * 1)]

        _WIN32 = (ctypes, kernel32, RenameInfo)
    return _WIN32


def _open_held(path: Path) -> int | None:
    """A descriptor holding the file *path* names, opened for deletion with deletion not shared: while it is open no
    other program can rename, replace or delete that file. A link is opened as itself, never followed. None when the file
    cannot be opened so (gone, a folder, or held by another program that does not share deletion)."""
    import msvcrt

    ctypes, kernel32, _ = _win32()
    handle = kernel32.CreateFileW(os.path.abspath(path), 0x00010000 | 0x0080,  # DELETE | FILE_READ_ATTRIBUTES
                                  0x0001 | 0x0002, None, 3,  # FILE_SHARE_READ | FILE_SHARE_WRITE; OPEN_EXISTING
                                  0x00200000, None)  # FILE_FLAG_OPEN_REPARSE_POINT
    if handle in (None, ctypes.c_void_p(-1).value):
        return None
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except OSError:
        kernel32.CloseHandle(handle)
        return None


def _rename_held(descriptor: int, target: Path) -> bool:
    """Rename the very file *descriptor* holds to *target*, refusing a taken name; whatever its old name holds now is
    not involved (``SetFileInformationByHandle``, ``FileRenameInfo``, no replacement)."""
    import msvcrt

    ctypes, kernel32, RenameInfo = _win32()
    name = os.path.abspath(target).encode("utf-16-le")
    buffer = ctypes.create_string_buffer(ctypes.sizeof(RenameInfo) + len(name))  # zeroed: the name ends in a null
    info = RenameInfo.from_buffer(buffer)
    info.ReplaceIfExists = 0
    info.RootDirectory = None
    info.FileNameLength = len(name)
    ctypes.memmove(ctypes.addressof(info) + RenameInfo.FileName.offset, name, len(name))
    return bool(kernel32.SetFileInformationByHandle(msvcrt.get_osfhandle(descriptor), 3, buffer, len(buffer)))


def _take_back(published: Path, staged: Path, identity: tuple[int, int]) -> bool:
    """Move *published* back to *staged* only if it is still the very file this attempt published. Whether it is back.

    The decision and the move are bound to one open file, never to the name (v0.7.2 Phase 9 focused closure, R9-03;
    until then the identity was read by name and the file then moved by name, so a file another program put there in
    between was moved into this run's staging). The file is held (:func:`_open_held`), its identity is read from that
    hold, and the rename is made through the same hold (:func:`_rename_held`): while held, no other program can replace
    it, and the rename can only move it. A name replaced before the hold holds the other program's file, whose identity
    is not this attempt's: it is left exactly where it is. Where no such operation exists nothing is moved."""
    if not _CAN_TAKE_BACK:
        return False
    descriptor = _open_held(published)
    if descriptor is None:
        return False
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != identity:
            return False  # another program's file has the name: it stays where it is
        return _rename_held(descriptor, staged)
    finally:
        os.close(descriptor)


def publish_book(book: BookPlan) -> tuple[Path, ...]:
    """Make a fully staged Book visible, atomically at the Book boundary.

    Refuses — before moving anything — unless **every** planned output is a
    regular staged file and none of the published paths already exists. Then
    moves file by file, each by one operation that itself refuses a name that
    is taken (``output_paths.move_without_replacing``): a file another writer
    puts at a planned name after the look above is never replaced (v0.7.2
    Phase 9 remote review R9-03; until then each move was ``os.replace``). On
    any failure, what this attempt moved is moved back to staging, so a Book is
    either published whole or not at all and its successful pieces are still
    there for a retry. Only a file that is still the very file this attempt
    moved is taken back, by an operation bound to that file and not to its name
    (:func:`_take_back`; Phase 9 focused closure), and the Book folder is
    removed only if this attempt made it and it is empty: nothing another writer
    put there is moved or removed. An output that cannot be taken back that way
    is left where it is and named in the error.
    """
    _require_owned(book)
    pairs = tuple(zip(book.staged_outputs, book.published_outputs))
    if not pairs:
        raise PlanError(f"Book {book.book_id} plans no output")
    for staged, published in pairs:
        if staged.is_symlink() or not staged.is_file():
            raise PlanError(f"not every planned output was staged: {staged.name} is missing")
        if published.exists() or published.is_symlink():
            raise PlanError(f"{published} already exists; nothing was published")
    output_paths.assert_no_link_in(book.published_dir.parent, book.published_dir)
    made_folder = not book.published_dir.exists()
    book.published_dir.mkdir(parents=True, exist_ok=True)
    moved: list[tuple[Path, Path, tuple[int, int]]] = []
    try:
        for staged, published in pairs:
            identity = _identity(staged)
            output_paths.move_without_replacing(staged, published)
            moved.append((staged, published, identity))
    except OSError as exc:
        left: list[str] = []
        for staged, published, identity in reversed(moved):
            try:
                back = _take_back(published, staged, identity)
            except OSError:
                back = False
            if not back:
                left.append(published.name)  # still published, or another program's file at its name: left as it is
        if made_folder:
            try:
                book.published_dir.rmdir()  # only when empty: whatever else is there stays
            except OSError:
                pass
        reason = (f"{exc.filename2 or exc.filename or 'a planned name'} was taken after the run was planned, "
                  "and was not replaced" if isinstance(exc, FileExistsError) else str(exc))
        if left:
            raise PlanError(f"publishing {book.folder_name} failed ({reason}); "
                            f"{', '.join(left)} could not be taken back and were left where they are") from exc
        raise PlanError(f"publishing {book.folder_name} failed and was rolled back: {reason}") from exc
    return tuple(published for _staged, published in pairs)


def discard_staging(book: BookPlan) -> int:
    """Delete the Book's private staging area and everything inside it.

    Bounded to that one directory: every entry is re-checked to lie under it,
    links are removed as links and never followed, and nothing outside the
    run's work area can be reached. Returns how many entries were removed.
    """
    _require_owned(book)
    root = book.staging_dir
    if not root.exists() and not root.is_symlink():
        return 0
    if _is_link(root):
        raise PlanError(f"staging {root} is a link and was not touched")
    removed = _remove_entries(root, root)
    os.rmdir(root)
    return removed + 1


def _is_link(path: Path) -> bool:
    """A symlink **or** a Windows junction / reparse point, asked of ``output_paths`` as the M4B tools' staging does.

    ``Path.is_symlink`` says no to a junction, and the ``os.walk`` this replaced (v0.7.2) walked into one and then
    refused the whole Book's discard as unsafe, so a junction planted in staging kept every piece of that Book."""
    if path.is_symlink():
        return True
    try:
        output_paths.assert_no_link_in(path.parent, path)
    except output_paths.OutputPathError:
        return True
    return False


def _remove_entries(root: Path, directory: Path) -> int:
    """Remove *directory*'s entries, bounded to *root*. A link is removed as a link, never entered or followed: its
    own place is already inside *root*, so it is not handed to ``assert_contained``, which resolves links."""
    removed = 0
    with os.scandir(directory) as scan:
        entries = list(scan)
    for entry in entries:
        target = Path(entry.path)
        if _is_link(target):
            try:
                os.unlink(target)
            except OSError:
                os.rmdir(target)  # a directory link on a platform that insists: the link itself, never its target
            removed += 1
            continue
        output_paths.assert_contained(root, target)
        if entry.is_dir(follow_symlinks=False):
            removed += _remove_entries(root, target)
            os.rmdir(target)
        else:
            os.unlink(target)
        removed += 1
    return removed


def release_staging(plan: RunPlan, *, keep: Collection[str] = ()) -> tuple[str, ...]:
    """Remove the staging no Retry Failed can reach any more (v0.7.2, ACT72-019 and ACT72-037).

    Every Book of *plan* whose id is not in *keep* loses its private staging
    folder through :func:`discard_staging` (bounded to that folder; a link is
    removed as a link or refused, never followed), then the work area goes if
    nothing is left in it. Published files never lie under the work area, so
    nothing published is reachable from here. *keep* is the Books a Retry
    Failed may still re-run; the caller decides that, nothing here reads it.

    Never raises: each problem is returned as one line, and what it names stays
    where it is. Safe to repeat.
    """
    problems: list[str] = []
    for book in plan.books:
        if book.book_id in keep:
            continue
        try:
            discard_staging(book)
        except (PlanError, output_paths.OutputPathError, OSError) as exc:
            problems.append(f"{book.staging_dir}: {exc}")
    try:
        discard_run_staging(plan)
    except PlanError as exc:  # pragma: no cover - plan_run always builds the work area under the run
        problems.append(str(exc))
    return tuple(problems)


def discard_run_staging(plan: RunPlan) -> bool:
    """Remove the run's work area once nothing is left in it.

    A published Book leaves behind an empty staging folder, and empty folders
    are removed here; a folder that still holds anything — a failed Book's
    retained pieces — stops this cold and the work area stays. ``rmdir`` only:
    no file is ever deleted by this function.
    """
    work_root = plan.work_root
    if work_root.parent != plan.run_directory or work_root.name != WORK_DIRNAME:
        raise PlanError(f"{work_root} is not this run's work area")
    try:
        if not work_root.is_dir() or work_root.is_symlink():
            return False
        for child in work_root.iterdir():
            if child.is_dir() and not child.is_symlink() and not any(child.iterdir()):
                child.rmdir()
        if any(work_root.iterdir()):
            return False
        work_root.rmdir()
        return True
    except OSError:
        return False
