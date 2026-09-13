"""The M4B Maker workflow model — v0.6.4 Phase 2.

This is the Maker-specific **non-UI** layer between the shared Plan 6 workspace
and the M4B Maker panel that adopts it in Phase 6. It owns the Maker vocabulary
and the pure rules the v0.6.4 plan states (sections 5.2–5.9) — and nothing that
touches a widget, a subprocess, an output directory, an audio stream or a tag:

- the Maker :class:`~shared.importing.SupportedTypeCatalog` (MP3 in);
- the six Shared fields and the four Book-only fields, with their labels;
- ``Import Folder`` → one Book per directory that directly contains MP3s, tracks
  in natural order, delegated whole to
  :func:`~shared.book_workspace.replace_workspace_from_import`;
- ``Add Files`` → the **current** Book, the selection natural-ordered by name
  (the Maker's existing behaviour), never regrouped by parent;
- per-Book track reorder and removal, identity by occurrence;
- the Maker's own deterministic automatic chapter title from a cleaned filename
  (:func:`normalize_title`, preserved from the existing Maker), and the
  pasted-list rule: line *n* names chapter *n*, a short list leaves the rest on
  their automatic titles, extra lines are ignored;
- the non-negative Silence parser and the Start Part parser;
- the Decision 51A output-name *inputs* — explicit Output Filename, Title,
  effective Album, the unambiguous source folder, ``Book N`` — as an ordered
  candidate tuple that Phase 3 sanitises through ``output_paths``.

Two rules shape everything here.

**The Maker observes no source tags.** Unlike the MP3 Tool it never reads ID3
frames to prefill a Book (section 5.7 preserves the Maker's own vocabulary and
adds nothing), so there is no observation store and a freshly imported Book's
configuration is literally empty. That is also what keeps
:func:`~shared.book_workspace.has_meaningful_work` meaning what Decision 50A
says: this module supplies no model defaults into a pristine Book.

**Identity is the occurrence, never the row.** A Book's tracks are its immutable
``ImportedFileSnapshot``; automatic titles are read off it in track order at the
moment they are asked for. There is no second file list anywhere.

Nothing here reserves a run, plans a filename, sanitises anything, calls
FFmpeg or mutagen, embeds artwork, or starts a controller. Those are Phases
3–5 and they consume these values; they do not extend this module into a
second pipeline.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from shared.book_workspace import (
    BLANK,
    BookJob,
    BookMutation,
    SharedMetadata,
    WorkspaceSnapshot,
    effective_metadata,
    new_book_id,
    replace_book,
    replace_workspace_from_import,
)
from shared.importing import (
    IdFactory,
    ImportedFile,
    ImportedFileSnapshot,
    SupportedType,
    SupportedTypeCatalog,
    natural_key,
)

__all__ = [
    "MakerContractError",
    "MakerValueError",
    "MAKER_TYPE",
    "MAKER_CATALOG",
    "SHARED_FIELDS",
    "BOOK_ONLY_FIELDS",
    "FIELD_LABELS",
    "UP",
    "DOWN",
    "new_shared_metadata",
    "new_workspace",
    "import_folder",
    "add_files",
    "move_tracks",
    "remove_tracks",
    "set_book_field",
    "title_text",
    "series_part_text",
    "output_filename_text",
    "chapter_titles_text",
    "strip_leading_numbers",
    "normalize_title",
    "default_titles",
    "usable_lines",
    "resolve_chapter_titles",
    "book_chapter_titles",
    "parse_silence",
    "parse_start_part",
    "effective_values",
    "effective_silence",
    "source_folder_name",
    "output_name_candidates",
    "display_hint",
]


class MakerContractError(Exception):
    """A caller used this model in a way its contract forbids."""


class MakerValueError(MakerContractError, ValueError):
    """User-entered text that cannot be interpreted — Silence, Start Part."""


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

#: The one Maker input type. The importer's catalog is the file filter, the scan
#: predicate and the type id on every ``ImportedFile`` — the Maker keeps no
#: extension list of its own.
MAKER_TYPE = SupportedType("mp3", "MP3 audio", (".mp3",))
MAKER_CATALOG = SupportedTypeCatalog((MAKER_TYPE,))

#: The six Shared fields, exactly (plan section 5.3). Deliberately not the MP3
#: Tool's: Silence is a non-negative gap, not a signed Time, and Series Name is
#: Shared here. No Title, no Series Part, no Output Filename, no Chapter Titles.
SHARED_FIELDS: tuple[str, ...] = ("artist", "album_artist", "album", "series",
                                  "silence", "artwork")

#: Per-Book configuration that has no Shared counterpart (section 5.4).
BOOK_ONLY_FIELDS: tuple[str, ...] = ("title", "series_part", "output_filename",
                                     "chapter_titles")

#: Display labels, declared beside the keys so the two cannot drift apart. The
#: adapter renders whatever it is handed; these are the Maker's words.
FIELD_LABELS: Mapping[str, str] = MappingProxyType({
    "artist": "Artist / Author",
    "album_artist": "Album Artist / Author",
    "album": "Album",
    "series": "Series Name",
    "silence": "Silence Between Tracks (seconds)",
    "artwork": "Book Artwork",
    "title": "Title",
    "series_part": "Series Part",
    "output_filename": "Output Filename",
    "chapter_titles": "Chapter Titles",
})

#: Directions for :func:`move_tracks`.
UP = -1
DOWN = 1

_ALL_BOOK_FIELDS = SHARED_FIELDS + BOOK_ONLY_FIELDS


def new_shared_metadata() -> SharedMetadata:
    """The workspace-level Shared Metadata, blank, over exactly the six fields."""
    return SharedMetadata.for_fields(SHARED_FIELDS)


def new_workspace(*, id_factory: IdFactory) -> WorkspaceSnapshot:
    """The startup workspace: one pristine Book, Book 1 of 1, blank Shared."""
    first = BookJob(book_id=new_book_id(id_factory))
    return WorkspaceSnapshot(books=(first,), current_book_id=first.book_id,
                             shared=new_shared_metadata())


# --------------------------------------------------------------------------- #
# Importing into the workspace
# --------------------------------------------------------------------------- #


def import_folder(workspace: WorkspaceSnapshot, snapshot: ImportedFileSnapshot, *,
                  id_factory: IdFactory) -> BookMutation:
    """Project a committed folder scan into Books: one per containing directory.

    The grouping, the natural order within a Book and the atomic replacement are
    Plan 6's (:func:`~shared.book_workspace.replace_workspace_from_import`); the
    Maker adds nothing to them — no observation, no prefill. The consumer commits
    the scan through the shared importer first and hands the committed snapshot
    here; nothing is scanned.
    """
    return replace_workspace_from_import(_require_workspace(workspace), snapshot,
                                         id_factory=id_factory)


def add_files(workspace: WorkspaceSnapshot, additions: Sequence[ImportedFile]) -> BookMutation:
    """Append validated files to the **current** Book, natural-ordered by name.

    Section 5.2: every file goes into the current Book whatever its parent
    directory, and nothing is regrouped. The selection is natural-ordered by
    filename before it is appended — the Maker's existing behaviour — and the
    Book's own order stays under the Book's control afterwards. The additions
    are the values the shared direct-file transaction validated; their
    occurrence ids must be new to this Book. Configuration is untouched.
    """
    space = _require_workspace(workspace)
    entries = tuple(additions)
    for entry in entries:
        if not isinstance(entry, ImportedFile):
            raise MakerContractError(
                f"additions must be importing.ImportedFile values, got {type(entry).__name__}")
    if not entries:
        return _unchanged(space)
    book = space.current
    held = set(book.files.occurrence_ids)
    for entry in entries:
        if entry.occurrence_id in held:
            raise MakerContractError(
                f"occurrence {entry.occurrence_id!r} is already in this Book")
        held.add(entry.occurrence_id)
    ordered = tuple(sorted(entries, key=lambda entry: natural_key(entry.path.name)))
    return _with_files(space, book, book.files.files + ordered)


# --------------------------------------------------------------------------- #
# Track operations on the current Book
# --------------------------------------------------------------------------- #


def _with_files(space: WorkspaceSnapshot, book: BookJob,
                files: tuple[ImportedFile, ...]) -> BookMutation:
    if files == book.files.files:
        return _unchanged(space)
    replaced = BookJob(
        book_id=book.book_id, configuration=book.configuration,
        files=ImportedFileSnapshot(revision=book.files.revision.advance(), files=files))
    return replace_book(space, replaced)


def _require_occurrences(book: BookJob, occurrence_ids: Iterable[str]) -> tuple[str, ...]:
    wanted = tuple(occurrence_ids)
    held = set(book.files.occurrence_ids)
    for occurrence in wanted:
        if occurrence not in held:
            raise MakerContractError(f"occurrence {occurrence!r} is not in this Book")
    return wanted


def move_tracks(workspace: WorkspaceSnapshot, occurrence_ids: Iterable[str],
                direction: int) -> BookMutation:
    """Move the named tracks one step up (``UP``) or down (``DOWN``).

    Bounded: a selection already against the edge moves nothing and reports a
    no-op. Identity is untouched — the same ``ImportedFile`` values change place.
    """
    if direction not in (UP, DOWN):
        raise MakerContractError(f"direction must be UP or DOWN, got {direction!r}")
    space = _require_workspace(workspace)
    book = space.current
    selected = set(_require_occurrences(book, occurrence_ids))
    if not selected:
        return _unchanged(space)
    order = list(book.files.files)
    indexes = range(len(order)) if direction == UP else range(len(order) - 1, -1, -1)
    for index in indexes:
        if order[index].occurrence_id not in selected:
            continue
        neighbour = index + direction
        if neighbour < 0 or neighbour >= len(order):
            continue
        if order[neighbour].occurrence_id in selected:
            continue
        order[index], order[neighbour] = order[neighbour], order[index]
    return _with_files(space, book, tuple(order))


def remove_tracks(workspace: WorkspaceSnapshot,
                  occurrence_ids: Iterable[str]) -> BookMutation:
    """Drop the named occurrences from the current Book. Configuration is kept."""
    space = _require_workspace(workspace)
    book = space.current
    selected = set(_require_occurrences(book, occurrence_ids))
    if not selected:
        return _unchanged(space)
    kept = tuple(entry for entry in book.files.files
                 if entry.occurrence_id not in selected)
    return _with_files(space, book, kept)


# --------------------------------------------------------------------------- #
# Book configuration
# --------------------------------------------------------------------------- #


def set_book_field(workspace: WorkspaceSnapshot, name: str, value: object) -> BookMutation:
    """Store one raw per-Book value. Text stays raw; blank is a stored fact.

    Every Maker field is text. Writing ``""`` keeps the key with a blank value
    rather than deleting it, so a cleared field remains a thing the user did.
    """
    space = _require_workspace(workspace)
    if name not in _ALL_BOOK_FIELDS:
        raise MakerContractError(f"{name!r} is not an M4B Maker Book field")
    if not isinstance(value, str):
        raise MakerContractError(f"{name} must be raw text, got {type(value).__name__}")
    book = space.current
    if name in book.configuration and book.configuration[name] == value:
        return _unchanged(space)
    configuration = dict(book.configuration)
    configuration[name] = value
    return replace_book(space, BookJob(book_id=book.book_id,
                                       configuration=configuration, files=book.files))


def title_text(book: BookJob) -> str:
    return str(_require_book(book).configuration.get("title", BLANK))


def series_part_text(book: BookJob) -> str:
    return str(_require_book(book).configuration.get("series_part", BLANK))


def output_filename_text(book: BookJob) -> str:
    return str(_require_book(book).configuration.get("output_filename", BLANK))


def chapter_titles_text(book: BookJob) -> str:
    return str(_require_book(book).configuration.get("chapter_titles", BLANK))


# --------------------------------------------------------------------------- #
# Chapter titles
# --------------------------------------------------------------------------- #


def strip_leading_numbers(name: str) -> str:
    """The Maker's existing rule: one leading number and its separator run go."""
    return re.sub(r"^\s*\d+\s*[-_.\)\(]*\s*", "", name).strip() or name


def normalize_title(stem: str) -> str:
    """The Maker's existing automatic chapter title from a source filename stem.

    Preserved verbatim from the current Maker (section 5.6 keeps "cleaned source
    filenames" as the suggestion): drop one leading track number, turn the first
    ``_`` into ``: ``, ``_s`` into ``’s``, a trailing ``_`` into ``?``, and
    collapse whitespace. Deterministic, and the only source-derived value here.
    """
    base = strip_leading_numbers(stem)
    base = re.sub(r"\s*_\s*", ": ", base, count=1)
    base = re.sub(r"(\w)_s\b", r"\1’s", base)
    base = re.sub(r"_\s*$", "?", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base


def default_titles(book: BookJob) -> tuple[str, ...]:
    """One automatic chapter title per track, in the Book's current order."""
    return tuple(normalize_title(Path(entry.path).stem)
                 for entry in _require_book(book).files.files)


def usable_lines(text: object) -> tuple[str, ...]:
    """The Chapter Titles box's lines, stripped, with blank lines collapsed away.

    The Maker's existing behaviour: a blank line is not a chapter.
    """
    if text is None:
        return ()
    return tuple(line.strip() for line in str(text).splitlines() if line.strip())


def resolve_chapter_titles(text: object, defaults: Sequence[str]) -> tuple[str, ...]:
    """Section 5.6: usable line *n* names chapter *n*; the rest keep their defaults.

    Fewer usable titles than tracks leaves the remaining chapters on their
    deterministic automatic titles; lines beyond the track count have no chapter
    to name and are ignored. The result has exactly one title per default.
    """
    lines = usable_lines(text)
    resolved = list(defaults)
    for index, line in enumerate(lines[:len(resolved)]):
        resolved[index] = line
    return tuple(resolved)


def book_chapter_titles(book: BookJob) -> tuple[str, ...]:
    """The complete chapter-title tuple for a Book's tracks as configured now."""
    return resolve_chapter_titles(chapter_titles_text(book), default_titles(book))


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #


def _require_text(name: str, text: object) -> str:
    if not isinstance(text, str):
        raise MakerContractError(f"{name} must be text, got {type(text).__name__}")
    return text.strip()


def parse_silence(text: object) -> float:
    """Section 5.5: blank is ``0.0``; otherwise a finite, **non-negative** number.

    ``0`` inserts nothing; a positive value is the gap between adjacent tracks.
    A negative value is not a Maker concept at all — this is not the MP3 Tool's
    signed Time — and is refused here, before any run could be reserved.
    """
    clean = _require_text("silence", text)
    if not clean:
        return 0.0
    lowered = clean.casefold()
    if any(token in lowered for token in ("nan", "inf")) or "_" in clean:
        raise MakerValueError(f"silence must be a plain number of seconds, got {text!r}")
    try:
        value = float(clean)
    except ValueError:
        raise MakerValueError(f"silence must be a number of seconds, got {text!r}") from None
    if not math.isfinite(value):
        raise MakerValueError(f"silence must be finite, got {text!r}")
    if value < 0:
        raise MakerValueError(f"silence cannot be negative, got {text!r}")
    return value + 0.0


def parse_start_part(text: object) -> int:
    """Section 5.9: blank means ``1``; otherwise a positive whole number, or an error."""
    clean = _require_text("start part", text)
    if not clean:
        return 1
    if not clean.isdecimal() or not clean.isascii():
        raise MakerValueError(f"start part must be a whole number, got {text!r}")
    value = int(clean)
    if value < 1:
        raise MakerValueError(f"start part must be 1 or more, got {text!r}")
    return value


# --------------------------------------------------------------------------- #
# Effective values and naming inputs
# --------------------------------------------------------------------------- #


def effective_values(shared: SharedMetadata, book: BookJob) -> Mapping[str, object]:
    """``Shared -> Book -> blank`` for the six Shared fields, via Plan 6 only.

    A thin projection over :func:`~shared.book_workspace.effective_metadata`;
    Book-only fields are read straight off the Book by their accessors.
    """
    values = effective_metadata(shared, _require_book(book))
    return MappingProxyType({name: values.get(name, BLANK) for name in SHARED_FIELDS})


def effective_silence(shared: SharedMetadata, book: BookJob) -> float:
    """The Silence a run would use for *book*, parsed from its effective text."""
    return parse_silence(str(effective_values(shared, book)["silence"]))


def source_folder_name(book: BookJob) -> str | None:
    """The one directory that directly contains every track, or ``None``.

    A Book formed from one containing directory has that name available; a
    manually assembled Book whose files come from several directories has no
    unambiguous folder and answers ``None`` (Decision 51A, step 4). Lexical
    only: no disk is read.
    """
    files = _require_book(book).files.files
    if not files:
        return None
    parents = {entry.path.parent for entry in files}
    if len(parents) != 1:
        return None
    name = next(iter(parents)).name
    return name or None


def _collapse(text: object) -> str:
    """Whitespace-collapsed, stripped display text. Not a blankness rule."""
    return " ".join(str(text).split())


def output_name_candidates(shared: SharedMetadata, book: BookJob,
                           position: int) -> tuple[str, ...]:
    """The Decision 51A inputs, in priority order, blanks skipped.

    Explicit Output Filename, then Title, then effective Album, then the
    unambiguous source folder, then ``Book N``. These are *candidates*: the
    Phase 3 planner sanitises the first through ``output_paths`` and appends
    ``.m4b`` exactly once. Nothing here decides safety.
    """
    current = _require_book(book)
    values = effective_values(shared, current)
    ordered = (
        _collapse(output_filename_text(current)),
        _collapse(title_text(current)),
        _collapse(values["album"]),
        _collapse(source_folder_name(current) or BLANK),
        f"Book {int(position)}",
    )
    return tuple(candidate for candidate in ordered if candidate)


def display_hint(shared: SharedMetadata, book: BookJob) -> str:
    """What follows ``Book N`` in the selector: Title, else effective Album, else folder."""
    current = _require_book(book)
    title = _collapse(title_text(current))
    if title:
        return title
    album = _collapse(effective_values(shared, current)["album"])
    if album:
        return album
    return source_folder_name(current) or ""


# --------------------------------------------------------------------------- #
# Small shared checks
# --------------------------------------------------------------------------- #


def _require_book(book: object) -> BookJob:
    if not isinstance(book, BookJob):
        raise MakerContractError(f"book must be a BookJob, got {type(book).__name__}")
    return book


def _require_workspace(workspace: object) -> WorkspaceSnapshot:
    if not isinstance(workspace, WorkspaceSnapshot):
        raise MakerContractError(
            f"workspace must be a WorkspaceSnapshot, got {type(workspace).__name__}")
    return workspace


def _unchanged(space: WorkspaceSnapshot) -> BookMutation:
    """A no-op reported the way Plan 6 reports one: through ``replace_book``."""
    return replace_book(space, space.current)
