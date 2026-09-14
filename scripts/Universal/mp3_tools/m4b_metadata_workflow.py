"""The M4B Metadata Editor workflow model — v0.6.4 Phase 7.

The Editor-specific **non-UI** layer between the shared Plan 6 workspace and the
panel that adopts it in Phase 10. It owns the Editor vocabulary and the pure
rules the v0.6.4 plan states (sections 6.1–6.11) — and nothing that writes a
tag, copies a file, plans an output, embeds artwork or starts a controller:

- the Editor :class:`~shared.importing.SupportedTypeCatalog` (``.m4b`` /
  ``.m4a`` / ``.mp4``);
- **one imported occurrence = one Book**, whatever directory it came from —
  deliberately not the Maker's directory-to-Book grouping;
- a frozen :class:`SourceObservation` per occurrence — what the source
  *currently contains*, read through the shared ``metadata`` readers with the
  series provenance they resolve (freeform vendor / movement / implied) kept as
  observed, never canonicalised by being read;
- the eight Shared fields (Title, Author / Artist, Album, Year, Genre, Comment,
  Series Name, Artwork) — **starting blank**, however alike the sources are —
  and the one Book-only field, the Chapter Titles buffer;
- the source-versus-edit distinction the preserve-by-default contract needs.

**Configuration holds only explicit edits.** A Book is created with an empty
configuration; its page *displays* the source prefill from the observation
(:func:`page_values`), and only what the user types is stored
(:func:`set_book_field`). So :func:`edit_intent` can answer, without guessing:
no key → nothing asked; a blank value → **preserve the source**; a value equal
to what the source carries → nothing to write; anything else → an explicit
edit. A populated Shared value is an explicit override for every Book
(:func:`shared_intent`); a blank one is not a write. An album-implied Series
Name or a track-implied Series Part is an observation: it is shown in the
read-back, never prefilled for writing. Series Part itself is read-back plus
the batch-level Auto-number / Start Part contract, not an editable Book field.

Chapters are observed in source order; the per-Book buffer is positional (line
*N* targets chapter *N*), a blank line preserves that chapter's title, lines
past the count are ignored (:func:`chapter_edits`). Nothing here collapses
blank lines — that is the MP3 Tool's rule, not this one.

An unreadable source is still one Book with a stable identity; its
observation records ``readable=False`` and the error, prefills nothing, and
leaves every other Book exactly as observed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from shared import metadata
from shared.book_workspace import (
    BLANK,
    BookJob,
    BookMutation,
    SharedMetadata,
    WorkspaceOperation,
    WorkspaceSnapshot,
    effective_metadata,
    new_book_id,
    replace_book,
)
from shared.importing import (
    IdFactory,
    ImportedFile,
    ImportedFileSnapshot,
    SupportedType,
    SupportedTypeCatalog,
)

__all__ = [
    "EditorContractError",
    "EditorValueError",
    "EDITOR_TYPE",
    "EDITOR_CATALOG",
    "SHARED_FIELDS",
    "TEXT_FIELDS",
    "BOOK_ONLY_FIELDS",
    "FIELD_LABELS",
    "SourceObservation",
    "ObservationStore",
    "ReceiveResult",
    "new_shared_metadata",
    "new_workspace",
    "observe_source",
    "source_of",
    "import_folder",
    "add_files",
    "set_book_field",
    "chapter_titles_text",
    "chapter_lines",
    "chapter_edits",
    "prefill_values",
    "page_values",
    "edit_intent",
    "explicit_edits",
    "shared_intent",
    "artwork_intent",
    "series_readback",
    "parse_start_part",
    "display_hint",
]


class EditorContractError(Exception):
    """A caller used this model in a way its contract forbids."""


class EditorValueError(EditorContractError, ValueError):
    """User-entered text that cannot be interpreted — Start Part."""


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

#: The Editor's accepted inputs (plan section 6.1). The importer's catalog is the
#: file filter, the scan predicate and the type id on every ``ImportedFile``.
EDITOR_TYPE = SupportedType("m4b", "M4B audiobooks", (".m4b", ".m4a", ".mp4"))
EDITOR_CATALOG = SupportedTypeCatalog((EDITOR_TYPE,))

#: The seven editable text fields, in page order.
TEXT_FIELDS: tuple[str, ...] = ("title", "artist", "album", "year", "genre", "comment",
                                "series")

#: The Shared fields, exactly (section 6.6): the seven text fields plus Artwork.
#: Series Part is deliberately absent — it is read-back plus the batch-level
#: Auto-number contract, not a text override.
SHARED_FIELDS: tuple[str, ...] = TEXT_FIELDS + ("artwork",)

#: Per-Book configuration with no Shared counterpart: the chapter-title buffer.
BOOK_ONLY_FIELDS: tuple[str, ...] = ("chapter_titles",)

FIELD_LABELS: Mapping[str, str] = MappingProxyType({
    "title": "Title",
    "artist": "Author / Artist",
    "album": "Album",
    "year": "Year",
    "genre": "Genre",
    "comment": "Comment",
    "series": "Series Name",
    "series_part": "Series Part",
    "artwork": "Artwork",
    "chapter_titles": "Chapter Titles",
})

_ALL_BOOK_FIELDS = SHARED_FIELDS + BOOK_ONLY_FIELDS

#: The provenance categories ``shared.metadata`` reports as display-only.
_IMPLIED_NAME = "album-implied"
_IMPLIED_PART = "track-implied"


def new_shared_metadata() -> SharedMetadata:
    """The workspace-level Shared Metadata, blank, over exactly the eight fields."""
    return SharedMetadata.for_fields(SHARED_FIELDS)


def new_workspace(*, id_factory: IdFactory) -> WorkspaceSnapshot:
    """The startup workspace: one pristine Book, blank Shared."""
    first = BookJob(book_id=new_book_id(id_factory))
    return WorkspaceSnapshot(books=(first,), current_book_id=first.book_id,
                             shared=new_shared_metadata())


# --------------------------------------------------------------------------- #
# Source observation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SourceObservation:
    """What one source file contains, as read — frozen, keyed by occurrence.

    Text fields are ``""`` when absent. ``series`` / ``series_part`` carry what
    the shared reader resolved together with its provenance (``series_source``:
    ``"freeform:<ns>"`` | ``"movement"`` | ``"album-implied"`` | ``None``;
    ``series_part_source`` likewise with ``"track-implied"``) and the exact
    atom, so a later phase can tell a real tag from a display-only inference
    and never migrate a value it only observed. ``readable=False`` records a
    source whose tags could not be read, with ``error`` for reporting.
    """

    occurrence_id: str
    path: Path
    readable: bool
    error: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    year: str = ""
    genre: str = ""
    comment: str = ""
    series: str = ""
    series_source: str | None = None
    series_atom: str | None = None
    series_part: str = ""
    series_part_source: str | None = None
    series_part_atom: str | None = None
    track: int | None = None
    has_cover: bool = False
    chapter_titles: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def chapter_count(self) -> int:
        return len(self.chapter_titles)

    @property
    def series_name_implied(self) -> bool:
        return self.series_source == _IMPLIED_NAME

    @property
    def series_part_implied(self) -> bool:
        return self.series_part_source == _IMPLIED_PART

    def source_value(self, name: str) -> str:
        """The value the source carries for a text field, for edit comparison.

        An album-implied Series Name is not a value the source *carries*; it is
        an inference, so for comparison the source Series Name is blank.
        """
        if name == "series" and self.series_name_implied:
            return BLANK
        return str(getattr(self, name, BLANK) or BLANK)


TagReader = Callable[[Path], Mapping[str, object]]
ChapterReader = Callable[[Path], Sequence[str]]


def observe_source(path: object, *, occurrence_id: str = "",
                   reader: TagReader = metadata.read_m4b_tags,
                   chapters: ChapterReader = metadata.read_chapter_titles) -> SourceObservation:
    """Read one source through the shared readers, **read-only**, never raising.

    Any failure — not an MP4, unreadable, missing — yields an observation with
    ``readable=False`` and the error text, so one bad file cannot poison an
    import. Chapters that cannot be read leave the titles empty without
    changing what the tags said.
    """
    source = Path(str(path))
    try:
        tags = dict(reader(source))
    except Exception as exc:  # noqa: BLE001 - every reader failure is one answer
        return SourceObservation(occurrence_id=occurrence_id, path=source, readable=False,
                                 error=f"{type(exc).__name__}: {exc}")
    try:
        titles = tuple(str(entry) for entry in chapters(source))
    except Exception:  # noqa: BLE001 - chapters are an aid, tags are the answer
        titles = ()
    track = tags.get("track")
    return SourceObservation(
        occurrence_id=occurrence_id, path=source, readable=True,
        title=str(tags.get("title", "") or ""), artist=str(tags.get("artist", "") or ""),
        album=str(tags.get("album", "") or ""), year=str(tags.get("year", "") or ""),
        genre=str(tags.get("genre", "") or ""), comment=str(tags.get("comment", "") or ""),
        series=str(tags.get("series", "") or ""),
        series_source=tags.get("series_source"), series_atom=tags.get("series_atom"),
        series_part=str(tags.get("series_part", "") or ""),
        series_part_source=tags.get("series_part_source"),
        series_part_atom=tags.get("series_part_atom"),
        track=int(track) if isinstance(track, int) else None,
        has_cover=bool(tags.get("has_cover")), chapter_titles=titles)


@dataclass(frozen=True)
class ObservationStore:
    """Observations by occurrence id. Immutable; growing it returns a new store."""

    entries: Mapping[str, SourceObservation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", MappingProxyType(dict(self.entries)))

    def with_observations(self, observations: Iterable[SourceObservation]) -> "ObservationStore":
        grown = dict(self.entries)
        for seen in observations:
            if not isinstance(seen, SourceObservation):
                raise EditorContractError(
                    f"observations must be SourceObservation values, got {type(seen).__name__}")
            grown[seen.occurrence_id] = seen
        return ObservationStore(grown)

    def get(self, occurrence_id: str) -> SourceObservation | None:
        return self.entries.get(occurrence_id)

    def for_book(self, book: BookJob) -> SourceObservation | None:
        """The observation of the Book's one source, or ``None`` for a pristine Book."""
        source = source_of(_require_book(book))
        return None if source is None else self.entries.get(source.occurrence_id)


def observe_files(entries: Iterable[ImportedFile], *, reader: TagReader = metadata.read_m4b_tags,
                  chapters: ChapterReader = metadata.read_chapter_titles
                  ) -> tuple[SourceObservation, ...]:
    return tuple(observe_source(entry.path, occurrence_id=entry.occurrence_id,
                                reader=reader, chapters=chapters) for entry in entries)


# --------------------------------------------------------------------------- #
# One occurrence = one Book
# --------------------------------------------------------------------------- #


def source_of(book: BookJob) -> ImportedFile | None:
    """The Book's one source occurrence, or ``None`` for a pristine Book."""
    files = _require_book(book).files.files
    if not files:
        return None
    if len(files) != 1:
        raise EditorContractError(
            f"an Editor Book holds exactly one source, got {len(files)}")
    return files[0]


@dataclass(frozen=True)
class ReceiveResult:
    """What one import produced: the mutation, the grown store, the skips."""

    mutation: BookMutation
    store: ObservationStore
    skipped: int = 0


def _book_for(entry: ImportedFile, revision, *, id_factory: IdFactory) -> BookJob:
    if not isinstance(entry, ImportedFile):
        raise EditorContractError(
            f"sources must be importing.ImportedFile values, got {type(entry).__name__}")
    return BookJob(book_id=new_book_id(id_factory),
                   files=ImportedFileSnapshot(revision=revision, files=(entry,)))


def import_folder(workspace: WorkspaceSnapshot, snapshot: ImportedFileSnapshot, *,
                  id_factory: IdFactory, store: ObservationStore,
                  reader: TagReader = metadata.read_m4b_tags,
                  chapters: ChapterReader = metadata.read_chapter_titles) -> ReceiveResult:
    """Replace the workspace with one Book per committed occurrence, in order.

    Deliberately **not** the Maker's directory grouping: two M4Bs in one folder
    are two Books. The consumer commits the scan through the shared importer
    (recursive or not, as configured) and hands the committed snapshot here;
    nothing is scanned. An empty import leaves the workspace as it is.
    Configuration starts empty — prefill is the observation's to display.
    """
    space = _require_workspace(workspace)
    _require_store(store)
    entries = tuple(snapshot.files)
    if not entries:
        return ReceiveResult(replace_book(space, space.current), store)
    books = tuple(_book_for(entry, snapshot.revision, id_factory=id_factory)
                  for entry in entries)
    grown = store.with_observations(observe_files(entries, reader=reader, chapters=chapters))
    replaced = WorkspaceSnapshot(books=books, current_book_id=books[0].book_id,
                                 revision=space.revision.advance(), shared=space.shared)
    mutation = BookMutation(operation=WorkspaceOperation.IMPORT, changed=True,
                            workspace=replaced, removed=space.books)
    return ReceiveResult(mutation, grown)


def add_files(workspace: WorkspaceSnapshot, additions: Sequence[ImportedFile], *,
              store: ObservationStore, id_factory: IdFactory | None = None,
              reader: TagReader = metadata.read_m4b_tags,
              chapters: ChapterReader = metadata.read_chapter_titles) -> ReceiveResult:
    """Append one Book per new source; a source already held (by identity) is skipped.

    The last Book added becomes current, so the page shows what was just
    added. A pristine startup Book is replaced by the first real source rather
    than left beside it.
    """
    space = _require_workspace(workspace)
    _require_store(store)
    ids = IdFactory("edbook-") if id_factory is None else id_factory
    held = {entry.identity for book in space.books for entry in book.files.files}
    fresh: list[ImportedFile] = []
    skipped = 0
    for entry in additions:
        if not isinstance(entry, ImportedFile):
            raise EditorContractError(
                f"additions must be importing.ImportedFile values, got {type(entry).__name__}")
        if entry.identity in held:
            skipped += 1
            continue
        held.add(entry.identity)
        fresh.append(entry)
    if not fresh:
        return ReceiveResult(replace_book(space, space.current), store, skipped)
    revision = space.revision.advance()
    books = tuple(_book_for(entry, revision, id_factory=ids) for entry in fresh)
    kept = tuple(book for book in space.books if not book.files.is_empty or book.configuration)
    removed = tuple(book for book in space.books if book not in kept)
    grown = store.with_observations(observe_files(fresh, reader=reader, chapters=chapters))
    appended = WorkspaceSnapshot(books=kept + books, current_book_id=books[-1].book_id,
                                 revision=revision, shared=space.shared)
    mutation = BookMutation(operation=WorkspaceOperation.ADD, changed=True,
                            workspace=appended, removed=removed)
    return ReceiveResult(mutation, grown, skipped)


# --------------------------------------------------------------------------- #
# Book configuration: explicit edits only
# --------------------------------------------------------------------------- #


def set_book_field(workspace: WorkspaceSnapshot, name: str, value: object) -> BookMutation:
    """Store one raw explicit edit. Blank is a stored fact meaning *preserve*.

    Series Part is refused: it is read-back plus the batch-level Auto-number
    contract, never a per-Book text edit (plan section 6.7).
    """
    space = _require_workspace(workspace)
    if name not in _ALL_BOOK_FIELDS:
        raise EditorContractError(f"{name!r} is not an M4B Metadata Editor Book field")
    if not isinstance(value, str):
        raise EditorContractError(f"{name} must be raw text, got {type(value).__name__}")
    book = space.current
    if name in book.configuration and book.configuration[name] == value:
        return replace_book(space, book)
    configuration = dict(book.configuration)
    configuration[name] = value
    return replace_book(space, BookJob(book_id=book.book_id, configuration=configuration,
                                       files=book.files))


def chapter_titles_text(book: BookJob) -> str:
    return str(_require_book(book).configuration.get("chapter_titles", BLANK))


def chapter_lines(book: BookJob) -> tuple[str, ...]:
    """The buffer's lines, positional, stripped, **blank lines kept in place**."""
    text = chapter_titles_text(book)
    if not text:
        return ()
    return tuple(line.strip() for line in text.splitlines())


def chapter_edits(book: BookJob, observation: SourceObservation) -> tuple[str | None, ...]:
    """Per source chapter: the new title, or ``None`` to preserve it.

    Line *N* targets chapter *N*; a blank line and a line equal to the source
    title both preserve; lines past the chapter count are ignored.
    """
    lines = chapter_lines(_require_book(book))
    resolved: list[str | None] = []
    for index, current in enumerate(observation.chapter_titles):
        line = lines[index] if index < len(lines) else BLANK
        resolved.append(line if line and line != current else None)
    return tuple(resolved)


# --------------------------------------------------------------------------- #
# Prefill, page values and edit intent
# --------------------------------------------------------------------------- #


def prefill_values(observation: SourceObservation | None) -> Mapping[str, str]:
    """What a Book page shows before any edit: the source's text fields.

    An album-implied Series Name is not prefilled (it is a read-back fact), and
    Series Part is never a prefilled edit. An unreadable or absent observation
    prefills nothing.
    """
    if observation is None or not observation.readable:
        return MappingProxyType({name: BLANK for name in TEXT_FIELDS})
    return MappingProxyType({name: observation.source_value(name) for name in TEXT_FIELDS})


def page_values(shared: SharedMetadata, book: BookJob,
                store: ObservationStore) -> Mapping[str, str]:
    """``Shared -> Book edit -> source prefill`` for every text field, for display.

    A stored blank edit shows blank (the user cleared it; the write intent is
    *preserve*, decided by :func:`edit_intent`, not here).
    """
    current = _require_book(book)
    prefill = prefill_values(_require_store(store).for_book(current))
    effective = effective_metadata(shared, current)
    values: dict[str, str] = {}
    for name in TEXT_FIELDS:
        if shared.populated(name) or name in current.configuration:
            values[name] = str(effective.get(name, BLANK))
        else:
            values[name] = prefill[name]
    return MappingProxyType(values)


def edit_intent(shared: SharedMetadata, book: BookJob, store: ObservationStore,
                name: str) -> str | None:
    """The value a later action would write for *name*, or ``None`` for *preserve*.

    A populated Shared value is an explicit override. Otherwise only an explicit
    Book edit counts, and only when it is non-blank **and** differs from what the
    source carries — an unchanged prefill, or a retyped identical value, is not
    a write (so a vendor/movement/implied series value is never migrated by
    accident). Blank means preserve.
    """
    if name not in TEXT_FIELDS:
        raise EditorContractError(f"{name!r} is not an editable text field")
    current = _require_book(book)
    if shared.populated(name):
        return shared.raw(name).strip()
    if name not in current.configuration:
        return None
    typed = str(current.configuration[name]).strip()
    if not typed:
        return None
    observation = _require_store(store).for_book(current)
    source = observation.source_value(name).strip() if observation is not None else BLANK
    return None if typed == source else typed


def explicit_edits(shared: SharedMetadata, book: BookJob,
                   store: ObservationStore) -> Mapping[str, str]:
    """Every text field a later action would write, and nothing else."""
    edits = {}
    for name in TEXT_FIELDS:
        value = edit_intent(shared, book, store, name)
        if value is not None:
            edits[name] = value
    return MappingProxyType(edits)


def shared_intent(shared: SharedMetadata) -> Mapping[str, str]:
    """The populated Shared text fields: explicit overrides for every Book."""
    return MappingProxyType({name: shared.raw(name).strip() for name in TEXT_FIELDS
                             if shared.populated(name)})


def artwork_intent(shared: SharedMetadata, book: BookJob) -> str | None:
    """The replacement artwork path a later action would embed, or ``None``.

    ``None`` means *preserve the source artwork* (Save) or *leave it removed*
    (Clear). Shared replacement wins; a Book replacement applies to that Book.
    """
    if shared.populated("artwork"):
        return shared.raw("artwork").strip()
    typed = str(_require_book(book).configuration.get("artwork", BLANK)).strip()
    return typed or None


# --------------------------------------------------------------------------- #
# Read-back, hints and the batch-level parser
# --------------------------------------------------------------------------- #


def series_readback(observation: SourceObservation | None) -> str:
    """The "Detected on file" line, exactly as the existing Editor words it.

    Four cases: a full series (real name, optionally a part); a part with no
    real name but an album Audiobookshelf likely groups by; a part with no name
    and no album; nothing at all. An album-implied name is not a real name.
    """
    if observation is None or not observation.readable:
        return "Detected on file: unavailable — the file's tags could not be read"
    series = observation.series.strip()
    part = observation.series_part.strip()
    album = observation.album.strip()
    has_real_name = bool(series) and not observation.series_name_implied
    if not series and not part:
        return "Detected on file: none — this file has no series tag"
    if part and not has_real_name:
        atom = observation.series_part_atom or observation.series_part_source or "?"
        if album:
            return (f"Detected on file: part #{part} only — no series name on file; "
                    f"Audiobookshelf likely groups by Album: '{album}'  (source: {atom})")
        return f"Detected on file: part #{part} only — no series name  (source: {atom})"
    shown = series + (f" #{part}" if part else "")
    atom = (observation.series_atom or observation.series_part_atom
            or observation.series_source or observation.series_part_source or "?")
    return f"Detected on file: {shown}  (source: {atom})"


def display_hint(shared: SharedMetadata, book: BookJob, store: ObservationStore) -> str:
    """What follows ``Book N`` in the selector: the page Title, else the filename."""
    current = _require_book(book)
    title = " ".join(page_values(shared, current, store)["title"].split())
    if title:
        return title
    source = source_of(current)
    return source.path.name if source is not None else ""


def parse_start_part(text: object) -> int:
    """Section 6.8: blank means ``1``; otherwise a positive whole number, or an error."""
    if not isinstance(text, str):
        raise EditorContractError(f"start part must be text, got {type(text).__name__}")
    clean = text.strip()
    if not clean:
        return 1
    if not clean.isdecimal() or not clean.isascii():
        raise EditorValueError(f"start part must be a whole number, got {text!r}")
    value = int(clean)
    if value < 1:
        raise EditorValueError(f"start part must be 1 or more, got {text!r}")
    return value


# --------------------------------------------------------------------------- #
# Small shared checks
# --------------------------------------------------------------------------- #


def _require_book(book: object) -> BookJob:
    if not isinstance(book, BookJob):
        raise EditorContractError(f"book must be a BookJob, got {type(book).__name__}")
    return book


def _require_workspace(workspace: object) -> WorkspaceSnapshot:
    if not isinstance(workspace, WorkspaceSnapshot):
        raise EditorContractError(
            f"workspace must be a WorkspaceSnapshot, got {type(workspace).__name__}")
    return workspace


def _require_store(store: object) -> ObservationStore:
    if not isinstance(store, ObservationStore):
        raise EditorContractError(
            f"store must be an ObservationStore, got {type(store).__name__}")
    return store
