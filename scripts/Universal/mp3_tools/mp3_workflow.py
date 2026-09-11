"""The MP3 workflow model — v0.6.3 focused MP3 Tool redesign, Phase 3.

This is the MP3-specific **non-UI** layer between the shared Plan 6 workspace and
the MP3 Tool panel that will adopt it. It owns the MP3 vocabulary and the pure
rules the plan states — and nothing that touches a widget, a subprocess, an
output directory or an audio stream:

- the MP3 :class:`~shared.importing.SupportedTypeCatalog`;
- the five Shared fields and the three Book-only fields, with their labels;
- ``Import Folder`` → one Book per directly-containing directory (Decision 12A,
  delegated whole to :func:`~shared.book_workspace.replace_workspace_from_import`);
- ``Add Files`` → the **current** Book, in the order the dialog returned, never
  regrouped by parent;
- read-only source ID3 observation, kept **per occurrence** so reorder and remove
  keep every track's seed aligned;
- the agreed/majority initial Artist / Album Artist / Album and the *Mixed source
  metadata* diagnostic, computed from the observations on demand;
- per-occurrence default Titles: a usable source Title, else a cleaned filename;
- Chapter Titles resolution: blank lines collapse, line *n* names track *n*, and a
  short list leaves the remaining defaults alone;
- the signed-Time and Start # parsers;
- the source-folder fallback name and the selector display hint.

Two rules shape everything here.

**Source metadata is an editing aid, not an output fallback.** Observed tags
prepopulate a Book's scalars exactly once — when a folder import creates it, or an
empty Book receives its first files — and are never consulted again for Artist,
Album Artist or Album. Clearing a prefilled field stores ``""``, and
:func:`effective_scalars` resolves ``Shared -> Book -> blank`` through the Plan 6
projection without ever seeing an observation. The one place a source value is a
*fallback* is a track's own Title, because that is the behaviour the plan asks for.

**Identity is the occurrence, never the row.** Observations are keyed by the
importer's ``occurrence_id``; a Book's tracks are its immutable
``ImportedFileSnapshot``; default titles are read off the two in track order at the
moment they are asked for. There is no second list indexed by row number, so a
moved or removed track cannot drift away from its seed, and a duplicated Book —
which carries configuration but no occurrences — carries no observations either.

Nothing here reserves a run, plans a filename, calls FFmpeg or mutagen's writers,
embeds artwork, or starts a controller. Those are later phases' and they consume
these values; they do not extend this module into a second pipeline.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
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
)

__all__ = [
    "MP3ContractError",
    "MP3ValueError",
    "MP3_TYPE",
    "MP3_CATALOG",
    "SHARED_FIELDS",
    "SCALAR_FIELDS",
    "BOOK_ONLY_FIELDS",
    "FIELD_LABELS",
    "DEFAULT_AUTO_NUMBER",
    "UP",
    "DOWN",
    "SourceTags",
    "TrackObservation",
    "Consensus",
    "BookSourceSummary",
    "ObservationStore",
    "ReceiveResult",
    "new_shared_metadata",
    "new_workspace",
    "read_source_tags",
    "title_from_filename",
    "default_title",
    "observe_files",
    "consensus",
    "summarise",
    "summary_for",
    "mixed_fields",
    "default_titles",
    "usable_lines",
    "resolve_titles",
    "book_titles",
    "import_folder",
    "add_files",
    "move_tracks",
    "remove_tracks",
    "set_book_field",
    "auto_number_enabled",
    "start_number_text",
    "chapter_titles_text",
    "parse_time_delta",
    "parse_start_number",
    "source_folder_name",
    "display_hint",
    "effective_scalars",
]


class MP3ContractError(Exception):
    """A caller used this model in a way its contract forbids."""


class MP3ValueError(MP3ContractError, ValueError):
    """User-entered text that cannot be interpreted — Start #, signed Time."""


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

#: The one MP3 supported type. The importer's catalog is the file filter, the
#: scan predicate and the type id on every ``ImportedFile`` — there is no second
#: extension list anywhere in the MP3 code.
MP3_TYPE = SupportedType("mp3", "MP3 audio", (".mp3",))
MP3_CATALOG = SupportedTypeCatalog((MP3_TYPE,))

#: The five Shared fields, exactly (focused plan section 10.1). No Title, no
#: Chapter Titles, no Start #, no Narrator, Year, Genre, Composer or Comment.
SHARED_FIELDS: tuple[str, ...] = ("artist", "album_artist", "album", "time_delta",
                                  "artwork")

#: The three Shared fields that source ID3 tags can suggest a value for.
SCALAR_FIELDS: tuple[str, ...] = ("artist", "album_artist", "album")

#: Per-Book configuration that has no Shared counterpart.
BOOK_ONLY_FIELDS: tuple[str, ...] = ("auto_number", "start_number", "chapter_titles")

#: Display labels, declared beside the keys so the two cannot drift apart. The
#: adapter renders whatever it is handed; these are the MP3 consumer's words.
FIELD_LABELS: Mapping[str, str] = MappingProxyType({
    "artist": "Artist / Author",
    "album_artist": "Album Artist / Author",
    "album": "Album",
    "time_delta": "Add/Remove Time at End of Each Track (seconds)",
    "artwork": "Book Artwork",
})

#: Auto-number is on at startup. It is a *default*, interpreted by
#: :func:`auto_number_enabled`, and deliberately not written into a pristine
#: Book's configuration — a Book the user has not touched stays empty so that
#: ``has_meaningful_work`` keeps meaning what Decision 50A says it means.
DEFAULT_AUTO_NUMBER = True

#: Directions for :func:`move_tracks`.
UP = -1
DOWN = 1

_ALL_BOOK_FIELDS = SHARED_FIELDS + BOOK_ONLY_FIELDS


def new_shared_metadata() -> SharedMetadata:
    """The workspace-level Shared Metadata, blank, over exactly the five fields."""
    return SharedMetadata.for_fields(SHARED_FIELDS)


def new_workspace(*, id_factory: IdFactory) -> WorkspaceSnapshot:
    """The startup workspace: one pristine Book, Book 1 of 1, blank Shared."""
    first = BookJob(book_id=new_book_id(id_factory))
    return WorkspaceSnapshot(books=(first,), current_book_id=first.book_id,
                             shared=new_shared_metadata())


# --------------------------------------------------------------------------- #
# Source observation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SourceTags:
    """The four user-facing text frames observed on one source file, raw.

    Exactly these four and nothing more: Year, Genre, Composer, Comment, embedded
    artwork and freeform frames are never imported into the editing surface, so
    they are not even read. Blank means the frame was absent or empty.
    """

    title: str = ""
    artist: str = ""
    album_artist: str = ""
    album: str = ""


_FRAMES = (("title", "TIT2"), ("artist", "TPE1"), ("album_artist", "TPE2"),
           ("album", "TALB"))


def read_source_tags(path: Path) -> SourceTags:
    """Read the four frames from *path* with mutagen, **read-only**.

    This is the one function in the module that touches a file. Any failure — no
    ID3 header, an unreadable or missing file, a mutagen error — yields blank tags
    rather than an exception: observation is an editing aid, and a file whose tags
    cannot be read is still a perfectly importable track. Multi-valued frames are
    joined with ``" / "`` so a list of two artists reads as two artists.
    """
    try:
        from mutagen.id3 import ID3
    except Exception:  # pragma: no cover - mutagen is a pinned requirement
        return SourceTags()
    try:
        frames = ID3(path)
    except Exception:
        return SourceTags()
    values: dict[str, str] = {}
    for name, frame_id in _FRAMES:
        frame = frames.get(frame_id)
        texts = getattr(frame, "text", None) if frame is not None else None
        if not texts:
            continue
        values[name] = " / ".join(str(item) for item in texts if str(item))
    return SourceTags(**values)


def _collapse(text: object) -> str:
    """Whitespace-collapsed, stripped display text. Not a blankness rule."""
    return " ".join(str(text).split())


_LEADING_NUMBER = re.compile(r"^\s*\d{1,3}(?:[\s._\-:)\]]+|$)")


def title_from_filename(name: str) -> str:
    """A cleaned Title from a source filename (focused plan section 16.1).

    Drops the extension, removes one leading one-to-three-digit track number and
    the separator run after it, turns the filename's ``_`` separator into user
    text (``_ `` becomes ``: ``, a bare ``_`` becomes a space), and collapses
    whitespace. A number that is the whole name — ``07.mp3`` — is kept, because
    removing it would leave nothing; a leading four-digit year is left alone.
    """
    stem = Path(str(name)).stem
    without_number = _LEADING_NUMBER.sub("", stem, count=1)
    if not without_number.strip():
        without_number = stem
    text = re.sub(r"_(?=\s)", ":", without_number)
    text = text.replace("_", " ")
    return _collapse(text)


def default_title(source_title: object, filename: str) -> str:
    """A track's automatic Title: a usable source Title, else the cleaned filename."""
    cleaned = _collapse(source_title)
    return cleaned if cleaned else title_from_filename(filename)


@dataclass(frozen=True)
class TrackObservation:
    """What was seen on one imported occurrence, plus its automatic Title.

    Keyed by the importer's ``occurrence_id`` so a deliberate duplicate — two
    occurrences of one file — gets two observations, exactly as it gets two rows.
    """

    occurrence_id: str
    tags: SourceTags
    default_title: str


ReadTags = Callable[[Path], SourceTags]


def observe_files(files: Iterable[ImportedFile], *,
                  reader: ReadTags = read_source_tags) -> tuple[TrackObservation, ...]:
    """Observe each occurrence once, in the order given. Pure given *reader*."""
    observed = []
    for entry in files:
        if not isinstance(entry, ImportedFile):
            raise MP3ContractError(
                f"files must be importing.ImportedFile values, got {type(entry).__name__}")
        try:
            tags = reader(entry.path)
        except Exception:
            tags = SourceTags()
        if not isinstance(tags, SourceTags):
            raise MP3ContractError(
                f"reader must return SourceTags, got {type(tags).__name__}")
        observed.append(TrackObservation(
            occurrence_id=entry.occurrence_id, tags=tags,
            default_title=default_title(tags.title, entry.name)))
    return tuple(observed)


# --------------------------------------------------------------------------- #
# Majority and mixed
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Consensus:
    """One deterministic initial value for a scalar, and whether sources disagree.

    ``value`` is the first natural spelling of the most common normalised value;
    ``mixed`` says more than one normalised value was seen; ``distinct`` counts
    them. A blank participates like any other value, so files that mostly carry
    nothing yield a blank value rather than a fabricated one.
    """

    value: str
    mixed: bool
    distinct: int


def _normalised(text: object) -> str:
    return unicodedata.normalize("NFKC", _collapse(text)).casefold()


def consensus(values: Iterable[object]) -> Consensus:
    """Section 11.2: normalised majority, first-encountered on a tie."""
    counts: dict[str, int] = {}
    spelling: dict[str, str] = {}
    for raw in values:
        key = _normalised(raw)
        counts[key] = counts.get(key, 0) + 1
        spelling.setdefault(key, _collapse(raw))
    if not counts:
        return Consensus(value="", mixed=False, distinct=0)
    # ``dict`` keeps first-seen order, so ``max`` over items with a strict ``>``
    # comparison keeps the earliest of equally common candidates.
    best_key, best_count = None, -1
    for key, count in counts.items():
        if count > best_count:
            best_key, best_count = key, count
    return Consensus(value=spelling[best_key], mixed=len(counts) > 1,
                     distinct=len(counts))


@dataclass(frozen=True)
class BookSourceSummary:
    """The three scalar consensuses for one Book's current occurrences."""

    artist: Consensus
    album_artist: Consensus
    album: Consensus

    def consensus_for(self, name: str) -> Consensus:
        if name not in SCALAR_FIELDS:
            raise MP3ContractError(f"{name!r} is not a source-observed scalar")
        return getattr(self, name)

    def value_for(self, name: str) -> str:
        return self.consensus_for(name).value


def summarise(observations: Iterable[TrackObservation]) -> BookSourceSummary:
    """Majority / mixed per scalar over the given observations, in order."""
    seen = tuple(observations)
    return BookSourceSummary(
        artist=consensus(entry.tags.artist for entry in seen),
        album_artist=consensus(entry.tags.album_artist for entry in seen),
        album=consensus(entry.tags.album for entry in seen),
    )


def mixed_fields(summary: BookSourceSummary) -> frozenset[str]:
    """The scalars to mark *Mixed source metadata* on."""
    return frozenset(name for name in SCALAR_FIELDS
                     if summary.consensus_for(name).mixed)


# --------------------------------------------------------------------------- #
# The observation store
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ObservationStore:
    """Every observation this consumer has made, by occurrence id. Immutable.

    It is a *cache of what was seen*, not a list of tracks: which occurrences a
    Book currently holds, and in what order, is the Book's own
    ``ImportedFileSnapshot``. Removing a track from a Book therefore changes
    nothing here, and a Book built by ``duplicate_book`` — no occurrences — finds
    nothing here for itself.
    """

    entries: Mapping[str, TrackObservation] = field(
        default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.entries, Mapping):
            raise MP3ContractError("entries must be a mapping of occurrence id -> observation")
        object.__setattr__(self, "entries", MappingProxyType(dict(self.entries)))

    @property
    def count(self) -> int:
        return len(self.entries)

    def get(self, occurrence_id: str) -> TrackObservation | None:
        return self.entries.get(occurrence_id)

    def with_observations(self, observations: Iterable[TrackObservation]
                          ) -> ObservationStore:
        """A new store carrying these observations too; re-observing replaces."""
        merged = dict(self.entries)
        for entry in observations:
            if not isinstance(entry, TrackObservation):
                raise MP3ContractError(
                    f"observations must be TrackObservation values, got {type(entry).__name__}")
            merged[entry.occurrence_id] = entry
        return ObservationStore(merged)

    def for_book(self, book: BookJob) -> tuple[TrackObservation, ...]:
        """The observations of *book*'s occurrences, in the Book's track order.

        An occurrence nobody observed gets a blank-tag observation with a
        filename-derived default title, built here and stored nowhere, so the
        answer always has one entry per track.
        """
        _require_book(book)
        found = []
        for entry in book.files.files:
            seen = self.entries.get(entry.occurrence_id)
            if seen is None:
                seen = TrackObservation(entry.occurrence_id, SourceTags(),
                                        default_title("", entry.name))
            found.append(seen)
        return tuple(found)


def summary_for(book: BookJob, store: ObservationStore) -> BookSourceSummary:
    """The Mixed diagnostic for a Book as it stands now — derived, never stored."""
    return summarise(_require_store(store).for_book(book))


def default_titles(book: BookJob, store: ObservationStore) -> tuple[str, ...]:
    """One automatic Title per track, in the Book's current order."""
    return tuple(entry.default_title for entry in _require_store(store).for_book(book))


# --------------------------------------------------------------------------- #
# Chapter Titles
# --------------------------------------------------------------------------- #


def usable_lines(text: object) -> tuple[str, ...]:
    """The Chapter Titles box's lines, stripped, with blank lines collapsed away."""
    if text is None:
        return ()
    return tuple(line.strip() for line in str(text).splitlines() if line.strip())


def resolve_titles(text: object, defaults: Sequence[str]) -> tuple[str, ...]:
    """Section 15.5: usable line *n* names track *n*; the rest keep their defaults.

    Blank lines consume no position and never mean "clear this track". Lines
    beyond the track count have no track to name and are ignored. The result has
    exactly one Title per default supplied.
    """
    lines = usable_lines(text)
    resolved = list(defaults)
    for index, line in enumerate(lines[:len(resolved)]):
        resolved[index] = line
    return tuple(resolved)


def book_titles(book: BookJob, store: ObservationStore) -> tuple[str, ...]:
    """The complete final Title tuple for a Book's tracks as configured now."""
    return resolve_titles(chapter_titles_text(book), default_titles(book, store))


# --------------------------------------------------------------------------- #
# Importing into the workspace
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReceiveResult:
    """What one import operation produced: the mutation and the grown store.

    ``workspace`` is derived from ``mutation`` for convenience; the consumer
    applies the workspace and keeps the store, as one pair.
    """

    mutation: BookMutation
    store: ObservationStore

    @property
    def workspace(self) -> WorkspaceSnapshot:
        return self.mutation.workspace


def _prepopulated(book: BookJob, summary: BookSourceSummary) -> BookJob:
    """Section 11.3, the first-population half: write each nonblank majority.

    Called only when a Book had no inputs before this import. A blank majority
    writes nothing, so a Book whose sources carry no Album has no ``album`` key
    rather than an empty one that would masquerade as a user's clear.
    """
    configuration = dict(book.configuration)
    for name in SCALAR_FIELDS:
        value = summary.value_for(name)
        if value:
            configuration[name] = value
    if configuration == dict(book.configuration):
        return book
    return BookJob(book_id=book.book_id, configuration=configuration,
                   files=book.files)


def import_folder(workspace: WorkspaceSnapshot, snapshot: ImportedFileSnapshot, *,
                  id_factory: IdFactory, store: ObservationStore,
                  reader: ReadTags = read_source_tags) -> ReceiveResult:
    """Project a committed folder scan into Books and prepopulate each one.

    The grouping, the natural order and the atomic replacement are Plan 6's
    (:func:`~shared.book_workspace.replace_workspace_from_import`); this adds only
    the MP3 half — observe every occurrence once and seed each new Book's scalars
    from its own files' majority. The consumer commits the scan through the shared
    importer first and hands the committed snapshot here; nothing is scanned.
    """
    _require_store(store)
    replaced = replace_workspace_from_import(workspace, snapshot, id_factory=id_factory)
    space = replaced.workspace
    if not replaced.changed or all(book.files.is_empty for book in space.books):
        return ReceiveResult(replaced, store)
    grown = store.with_observations(observe_files(snapshot.files, reader=reader))
    for book in space.books:
        seeded = _prepopulated(book, summarise(grown.for_book(book)))
        if seeded is not book:
            space = replace_book(space, seeded).workspace
    # One result value: the import's own mutation shape, carrying the final
    # workspace, so a consumer sees the replacement as a single operation.
    final = BookMutation(operation=replaced.operation, changed=True,
                         workspace=space, removed=replaced.removed)
    return ReceiveResult(final, grown)


def add_files(workspace: WorkspaceSnapshot, additions: Sequence[ImportedFile], *,
              store: ObservationStore,
              reader: ReadTags = read_source_tags) -> ReceiveResult:
    """Append validated files to the **current** Book, in the order given.

    Section 12.5: every file goes into the current Book whatever its parent
    directory, and nothing is regrouped. The additions are the values the shared
    direct-file transaction validated; their occurrence ids must be new to this
    Book. If the Book had no inputs, the additions' majority prepopulates its
    scalars; if it already had inputs, every stored value — typed or cleared —
    is left exactly as it was and only the observations grow.
    """
    _require_store(store)
    space = _require_workspace(workspace)
    entries = tuple(additions)
    for entry in entries:
        if not isinstance(entry, ImportedFile):
            raise MP3ContractError(
                f"additions must be importing.ImportedFile values, got {type(entry).__name__}")
    book = space.current
    if not entries:
        return ReceiveResult(_unchanged(space), store)
    held = set(book.files.occurrence_ids)
    for entry in entries:
        if entry.occurrence_id in held:
            raise MP3ContractError(
                f"occurrence {entry.occurrence_id!r} is already in this Book")
        held.add(entry.occurrence_id)
    grown = store.with_observations(observe_files(entries, reader=reader))
    files = ImportedFileSnapshot(revision=book.files.revision.advance(),
                                 files=book.files.files + entries)
    grown_book = BookJob(book_id=book.book_id, configuration=book.configuration,
                         files=files)
    if book.files.is_empty:
        grown_book = _prepopulated(grown_book, summarise(grown.for_book(grown_book)))
    return ReceiveResult(replace_book(space, grown_book), grown)


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
            raise MP3ContractError(f"occurrence {occurrence!r} is not in this Book")
    return wanted


def move_tracks(workspace: WorkspaceSnapshot, occurrence_ids: Iterable[str],
                direction: int) -> BookMutation:
    """Move the named tracks one step up (``UP``) or down (``DOWN``).

    Bounded: a selection already against the edge moves nothing and reports a
    no-op. Identity is untouched — the same ``ImportedFile`` values change place.
    """
    if direction not in (UP, DOWN):
        raise MP3ContractError(f"direction must be UP or DOWN, got {direction!r}")
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

    Writing ``""`` keeps the key with a blank value rather than deleting it, so a
    cleared prefilled field remains distinguishable from a never-populated one and
    nothing can later mistake the clear for an invitation to restore the source.
    """
    space = _require_workspace(workspace)
    if name not in _ALL_BOOK_FIELDS:
        raise MP3ContractError(f"{name!r} is not an MP3 Book field")
    if name == "auto_number":
        if not isinstance(value, bool):
            raise MP3ContractError("auto_number must be a bool")
    elif not isinstance(value, str):
        raise MP3ContractError(f"{name} must be raw text, got {type(value).__name__}")
    book = space.current
    if name in book.configuration and book.configuration[name] == value:
        return _unchanged(space)
    configuration = dict(book.configuration)
    configuration[name] = value
    return replace_book(space, BookJob(book_id=book.book_id,
                                       configuration=configuration, files=book.files))


def auto_number_enabled(book: BookJob) -> bool:
    value = _require_book(book).configuration.get("auto_number", DEFAULT_AUTO_NUMBER)
    return bool(value)


def start_number_text(book: BookJob) -> str:
    return str(_require_book(book).configuration.get("start_number", BLANK))


def chapter_titles_text(book: BookJob) -> str:
    return str(_require_book(book).configuration.get("chapter_titles", BLANK))


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #


def _require_text(name: str, text: object) -> str:
    if not isinstance(text, str):
        raise MP3ContractError(f"{name} must be text, got {type(text).__name__}")
    return text.strip()


def parse_time_delta(text: object) -> float:
    """Section 17: blank is ``0.0``; otherwise a finite number, signed.

    Positive appends, negative trims, zero adjusts nothing — and zero is a real
    value, not a request to skip processing. NaN, infinity and anything Python
    would not read as a plain decimal number are refused with a clear error.
    """
    clean = _require_text("time", text)
    if not clean:
        return 0.0
    lowered = clean.casefold()
    if any(token in lowered for token in ("nan", "inf")) or "_" in clean:
        raise MP3ValueError(f"time must be a plain number of seconds, got {text!r}")
    try:
        value = float(clean)
    except ValueError:
        raise MP3ValueError(f"time must be a number of seconds, got {text!r}") from None
    if not math.isfinite(value):
        raise MP3ValueError(f"time must be finite, got {text!r}")
    return value


def parse_start_number(text: object) -> int:
    """Section 16.4: blank means ``1``; otherwise a positive integer, or an error."""
    clean = _require_text("start number", text)
    if not clean:
        return 1
    if not clean.isdecimal() or not clean.isascii():
        raise MP3ValueError(f"start number must be a whole number, got {text!r}")
    value = int(clean)
    if value < 1:
        raise MP3ValueError(f"start number must be 1 or more, got {text!r}")
    return value


# --------------------------------------------------------------------------- #
# Naming hints
# --------------------------------------------------------------------------- #


def source_folder_name(book: BookJob) -> str | None:
    """The one directory that directly contains every track, or ``None``.

    A Book formed from one containing directory has that name available; a
    manually assembled Book whose files come from several directories has no
    trustworthy common folder and answers ``None`` (section 20.2). Lexical only:
    no disk is read.
    """
    files = _require_book(book).files.files
    if not files:
        return None
    parents = {entry.path.parent for entry in files}
    if len(parents) != 1:
        return None
    name = next(iter(parents)).name
    return name or None


def display_hint(shared: SharedMetadata, book: BookJob) -> str:
    """What follows ``Book N`` in the selector: effective Album, else folder."""
    album = _collapse(effective_metadata(shared, _require_book(book)).get("album", BLANK))
    if album:
        return album
    return source_folder_name(book) or ""


def effective_scalars(shared: SharedMetadata, book: BookJob) -> Mapping[str, object]:
    """``Shared -> Book -> blank`` for the five Shared fields, via Plan 6 only.

    Deliberately a thin projection over
    :func:`~shared.book_workspace.effective_metadata`: no observation, summary or
    seed is in reach here, which is what makes a cleared field stay cleared.
    """
    values = effective_metadata(shared, _require_book(book))
    return MappingProxyType({name: values.get(name, BLANK) for name in SHARED_FIELDS})


# --------------------------------------------------------------------------- #
# Small shared checks
# --------------------------------------------------------------------------- #


def _require_book(book: object) -> BookJob:
    if not isinstance(book, BookJob):
        raise MP3ContractError(f"book must be a BookJob, got {type(book).__name__}")
    return book


def _require_workspace(workspace: object) -> WorkspaceSnapshot:
    if not isinstance(workspace, WorkspaceSnapshot):
        raise MP3ContractError(
            f"workspace must be a WorkspaceSnapshot, got {type(workspace).__name__}")
    return workspace


def _require_store(store: object) -> ObservationStore:
    if not isinstance(store, ObservationStore):
        raise MP3ContractError(
            f"store must be an ObservationStore, got {type(store).__name__}")
    return store


def _unchanged(space: WorkspaceSnapshot) -> BookMutation:
    """A no-op reported the way Plan 6 reports one: through ``replace_book``."""
    return replace_book(space, space.current)
