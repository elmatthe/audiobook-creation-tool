"""Shared output-base, run-reservation, collision and mirroring services.

The layout every tool will use from Phase 4 onward::

    <output base>/<Tool>-Outputs/<Tool>-N/

where the base defaults to ``~/Downloads/Audiobook-Creation-Tool-Outputs``, the
tool parent comes from the one central registry in :data:`TOOL_OUTPUT_PARENTS`,
and ``N`` is the lowest free positive run number.

**Planning is pure; materialisation is explicit.** Every ``plan_*`` function,
the sanitizer and the collision service compute paths and touch nothing. Only
:func:`ensure_output_base` and :func:`reserve_run_directory` create anything,
and they create directories only — never a file, never anything on the source
side. That split is what lets the whole surface be tested in a temporary tree.

Platform-neutral and Tk-free by construction: paths and an effective
configuration snapshot come in, immutable plans and typed errors come out.
Nothing here reads or writes media, spawns a process, or touches the network.

**Nothing in the application consumes this module yet.** Phase 4 migrates the
six tools; until then ``shared.paths.next_output_dir`` remains the live path.
"""

from __future__ import annotations

import os
import re
import stat
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from . import config, paths

# --------------------------------------------------------------------------- #
# Errors — typed, so a caller can tell a bad base from a bad name
# --------------------------------------------------------------------------- #


class OutputPathError(Exception):
    """Base class. Carries a message written for a person.

    ``detail`` keeps the technical remainder (the underlying OSError, the raw
    value) for the log, so a summary can be shown without a traceback.
    """

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


class OutputBaseError(OutputPathError):
    """The configured output base is unusable and processing must not start."""


class UnknownToolError(OutputPathError):
    """A tool identifier is not in the central registry."""


class ReservationError(OutputPathError):
    """A run directory could not be reserved."""


class UnsafePathError(OutputPathError):
    """A destination would escape its root, overwrite an input, or follow a link."""


# --------------------------------------------------------------------------- #
# The central tool-parent registry
# --------------------------------------------------------------------------- #

#: Tool key -> parent folder under the output base. Derived from the one
#: existing slug registry so a slug is never written down twice; a tool panel
#: must ask for its folder by key rather than building a name itself.
TOOL_OUTPUT_PARENTS: Mapping[str, str] = MappingProxyType(
    {key: f"{slug}-Outputs" for key, slug in paths.TOOL_SLUGS.items()}
)

#: Tool key -> run-directory prefix, i.e. the ``<Tool>`` in ``<Tool>-N``.
TOOL_RUN_PREFIXES: Mapping[str, str] = MappingProxyType(dict(paths.TOOL_SLUGS))


def tool_parent_name(tool_key: str) -> str:
    """The ``<Tool>-Outputs`` folder name for *tool_key*.

    Raises :class:`UnknownToolError` rather than inventing a folder: an
    unrecognised key must never become an unchecked path fragment.
    """
    try:
        return TOOL_OUTPUT_PARENTS[tool_key]
    except (KeyError, TypeError):
        known = ", ".join(sorted(TOOL_OUTPUT_PARENTS))
        raise UnknownToolError(
            f"unknown tool {tool_key!r}; known tools are {known}",
            f"tool_key={tool_key!r}",
        ) from None


def tool_run_prefix(tool_key: str) -> str:
    """The ``<Tool>`` prefix used for that tool's run directories."""
    tool_parent_name(tool_key)  # validates
    return TOOL_RUN_PREFIXES[tool_key]


def tool_parent_dir(base: Path, tool_key: str) -> Path:
    """``<base>/<Tool>-Outputs``. Computed, not created."""
    return Path(base) / tool_parent_name(tool_key)


# --------------------------------------------------------------------------- #
# Output base
# --------------------------------------------------------------------------- #


def resolve_output_base(effective=None) -> Path:
    """The effective output base for an operation, from a config snapshot.

    Pass the snapshot captured at run start so a preference changed mid-run
    cannot move an operation's destination. With no argument the current
    process snapshot is used. Nothing is created here.

    The Phase 1 rules already applied when the snapshot was built: empty means
    ``~/Downloads/Audiobook-Creation-Tool-Outputs``; a custom value had to be
    absolute or ``~``-based; a relative path was rejected; environment
    variables were never expanded. This function does not re-open that.
    """
    snapshot = config.get_effective() if effective is None else effective
    base = Path(snapshot.output.base_directory)
    if not base.is_absolute():
        # Belt and braces: the snapshot should never produce this.
        raise OutputBaseError(
            "the output location is not a full path, so it cannot be used",
            f"resolved to {base!r}",
        )
    return base


def ensure_output_base(base: Path) -> Path:
    """Create the output base if needed and prove it is writable.

    This is a **materialisation** step, called at validated run start — never
    while a panel is being built. Raises :class:`OutputBaseError` with a
    useful message so a caller can refuse to start processing instead of
    failing halfway through.
    """
    base = Path(base)
    if _is_link(base):
        raise UnsafePathError(
            "the output location is a link, which is not used as an output destination",
            f"{base} is a symlink or junction",
        )
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputBaseError(
            f"the output folder could not be created: {base}",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    if not base.is_dir():
        raise OutputBaseError(
            f"the output location is not a folder: {base}", f"{base} exists but is not a directory"
        )
    if not os.access(base, os.W_OK):
        raise OutputBaseError(
            f"the output folder cannot be written to: {base}", "os.access reported no write permission"
        )
    return base


# --------------------------------------------------------------------------- #
# Filename sanitisation
# --------------------------------------------------------------------------- #

#: Characters Windows forbids in a filename, plus both separators.
_FORBIDDEN_CHARS = '<>:"/\\|?*'

#: Device names Windows reserves. Reserved with *any* extension too, so
#: ``CON.txt`` is as unusable as ``CON``.
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

#: What an unusable component becomes.
FALLBACK_COMPONENT = "output"

#: Maximum length of a single path component. 255 is the limit on NTFS, APFS
#: and ext4 alike; the extension is preserved and the stem is truncated.
MAX_COMPONENT_LENGTH = 255

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def split_suffix(name: str) -> tuple[str, str]:
    """Split *name* into ``(stem, suffix)`` using the **final** extension only.

    Deliberately not ``Path.suffixes``: audiobook filenames routinely contain
    dots that are not extensions (``Book 1.5 - Extras.m4b``), and treating the
    whole dotted tail as an extension would mangle far more real names than the
    ``.tar.gz`` case it would help. A leading dot is part of the stem, so a
    dotfile keeps its name.
    """
    pure = PurePath(name)
    suffix = pure.suffix
    if not suffix:
        return name, ""
    return name[: len(name) - len(suffix)], suffix


def sanitize_component(
    name: str, *, fallback: str = FALLBACK_COMPONENT, max_length: int = MAX_COMPONENT_LENGTH
) -> str:
    """Turn *name* into one safe path component, valid on Windows and macOS.

    A **single component** is expected. Anything that looks like a path is
    reduced to its last element rather than being accepted silently, so a
    caller cannot smuggle ``../..`` or ``C:\\Windows`` through a "filename"
    argument.

    Applied in order: separators dropped to the last element; control
    characters and forbidden characters replaced; Unicode normalised to NFC;
    trailing dots and spaces stripped (Windows silently drops them, which would
    otherwise turn two distinct names into one file); ``.``/``..``/blank
    replaced with *fallback*; a reserved device name (with or without an
    extension) given a safe prefix; and finally the stem truncated so the whole
    component fits *max_length* with its extension intact.
    """
    text = "" if name is None else str(name)

    # Never accept a path where a component belongs.
    text = text.replace("\\", "/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]

    text = unicodedata.normalize("NFC", text)
    text = _CONTROL_CHARS.sub("", text)
    text = "".join("_" if ch in _FORBIDDEN_CHARS else ch for ch in text)
    # Windows strips these on write, so two "different" names would land on one
    # file. Strip them here, deterministically, instead.
    text = text.rstrip(" .")
    text = text.strip()

    if text in ("", ".", ".."):
        text = fallback

    stem, suffix = split_suffix(text)
    if stem.upper() in _RESERVED_NAMES:
        stem = f"_{stem}"
        text = stem + suffix

    if len(text) > max_length:
        keep = max(1, max_length - len(suffix))
        stem = stem[:keep].rstrip(" .") or fallback
        text = stem + suffix
        if len(text) > max_length:          # a pathological suffix
            text = text[:max_length]

    return text or fallback


def sanitize_relative(relative: PurePath | str, *, fallback: str = FALLBACK_COMPONENT) -> PurePath:
    """Sanitise every component of a relative path, refusing to escape.

    Raises :class:`UnsafePathError` for an absolute path or any ``..`` element
    — a mirrored relative path must stay inside its root, and silently
    rewriting a traversal attempt would hide a real problem.
    """
    pure = PurePath(str(relative).replace("\\", "/"))
    if pure.is_absolute() or (pure.drive or pure.root):
        raise UnsafePathError(
            "a source path outside the chosen folder cannot be mirrored",
            f"absolute relative path: {relative!r}",
        )
    parts: list[str] = []
    for part in pure.parts:
        if part == "..":
            raise UnsafePathError(
                "a source path outside the chosen folder cannot be mirrored",
                f"'..' traversal in {relative!r}",
            )
        if part in ("", "."):
            continue
        parts.append(sanitize_component(part, fallback=fallback))
    return PurePath(*parts) if parts else PurePath()


# --------------------------------------------------------------------------- #
# Link and containment safety
# --------------------------------------------------------------------------- #


def _is_link(path: Path) -> bool:
    """True for a symlink, a Windows junction, or any other reparse point."""
    try:
        if path.is_symlink():
            return True
    except OSError:
        return False
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", None)
    if reparse is None:
        return False
    try:
        attributes = os.lstat(path).st_file_attributes  # Windows only
    except (OSError, AttributeError):
        return False
    return bool(attributes & reparse)


def assert_no_link_in(root: Path, candidate: Path) -> None:
    """Refuse if any existing component from *root* to *candidate* is a link.

    A destination is never established through a link: a junction inside the
    run directory could otherwise redirect a write anywhere on the machine.
    Components that do not exist yet cannot be links, so they are skipped.
    """
    root = Path(root)
    candidate = Path(candidate)
    if _is_link(root):
        raise UnsafePathError(
            "the output folder is a link, which is not used as an output destination",
            f"{root} is a symlink or junction",
        )
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        relative = None
    if relative is None:
        return
    walked = root
    for part in relative.parts:
        walked = walked / part
        if not walked.exists() and not walked.is_symlink():
            continue
        if _is_link(walked):
            raise UnsafePathError(
                "part of the output path is a link, which is not followed",
                f"{walked} is a symlink or junction",
            )


def _normalise(path: Path) -> Path:
    """Absolute, symlink-resolved where possible, working-directory-independent."""
    try:
        return Path(path).resolve()
    except OSError:
        return Path(os.path.abspath(str(path)))


def assert_contained(root: Path, candidate: Path) -> Path:
    """Prove *candidate* stays inside *root*; return the normalised destination.

    Handles destinations that do not exist yet: the path is normalised without
    requiring it to be present, so an unresolved child is checked rather than
    assumed safe. Comparison is case-insensitive on a case-insensitive
    filesystem, matching what the OS would actually do.
    """
    root_n = _normalise(root)
    cand_n = _normalise(candidate)
    if not _within(root_n, cand_n):
        raise UnsafePathError(
            "the destination would be written outside the chosen output folder",
            f"{cand_n} is not inside {root_n}",
        )
    assert_no_link_in(Path(root), Path(candidate))
    return cand_n


def _within(root: Path, candidate: Path) -> bool:
    if candidate == root:
        return False  # the root itself is not a destination
    root_parts = _case_parts(root)
    cand_parts = _case_parts(candidate)
    return cand_parts[: len(root_parts)] == root_parts


def _case_parts(path: Path) -> tuple[str, ...]:
    parts = path.parts
    return tuple(p.casefold() for p in parts) if _CASE_INSENSITIVE_FS else parts


#: Windows and macOS both default to case-insensitive filesystems.
_CASE_INSENSITIVE_FS = os.name == "nt" or sys.platform == "darwin"


def assert_not_input(destination: Path, inputs: Iterable[Path]) -> None:
    """Refuse a destination that is one of the operation's own input files."""
    dest_key = str(_normalise(destination)).casefold()
    for source in inputs:
        src_n = _normalise(Path(source))
        if str(src_n).casefold() == dest_key:
            raise UnsafePathError(
                "an output would overwrite one of the files being read",
                f"destination equals input {src_n}",
            )


def assert_outside_source_trees(destination: Path, source_roots: Iterable[Path]) -> None:
    """Refuse a destination that lands inside one of the declared source trees.

    Default operations are copy-based and write only under the reserved run
    directory. Writing into a source tree is reserved for the two explicit,
    separately confirmed exceptions (Cover source-side mode and the M4B Maker
    custom destination), which are not implemented here.
    """
    dest_n = _normalise(destination)
    for root in source_roots:
        root_n = _normalise(Path(root))
        if dest_n == root_n or _within(root_n, dest_n):
            raise UnsafePathError(
                "an output would be written inside the folder it is reading from",
                f"{dest_n} is inside source tree {root_n}",
            )


# --------------------------------------------------------------------------- #
# Collision numbering
# --------------------------------------------------------------------------- #

#: Cap on the collision search. A run that needs more than this has something
#: structurally wrong, and an unbounded loop would hang the worker.
MAX_COLLISION_ATTEMPTS = 10_000


def numbered_variant(name: str, index: int) -> str:
    """``stem-1.ext``, ``stem-2.ext``, … — the plan's exact collision format."""
    stem, suffix = split_suffix(name)
    return f"{stem}-{index}{suffix}"


class DestinationPlanner:
    """Per-batch collision tracker: one instance per run, never shared globally.

    Combines two sources of truth — what already exists on disk and what this
    batch has already *planned* — so two proposed outputs cannot select the
    same destination before either file exists. Separate batches get separate
    trackers, so results never depend on test order or on an earlier run.

    Comparison is **case-insensitive on every platform**, deliberately. Windows
    and macOS are case-insensitive by default, so ``Book.m4b`` and ``book.m4b``
    are one file there; matching that everywhere keeps a plan identical across
    platforms and errs toward an extra ``-1`` rather than toward an overwrite.

    Not thread-safe by itself: a plan is built on one thread and then handed to
    a worker, which is the pattern every tool already uses for its job snapshot.
    """

    def __init__(self, root: Path, *, check_filesystem: bool = True):
        self.root = Path(root)
        self._check_filesystem = check_filesystem
        self._taken: set[str] = set()

    @staticmethod
    def _key(path: Path) -> str:
        return str(path).casefold()

    def _is_free(self, candidate: Path) -> bool:
        if self._key(candidate) in self._taken:
            return False
        if self._check_filesystem:
            # lexists, not exists: a broken symlink still occupies the name.
            if candidate.exists() or candidate.is_symlink():
                return False
        return True

    def plan(self, name: str, *, subdir: PurePath | str | None = None) -> Path:
        """Reserve the next free destination for *name* under an optional subdir.

        The requested (sanitised) name is tried first; on conflict the plan's
        ``stem-1.ext`` / ``stem-2.ext`` sequence is used. Returns the planned
        path and records it — **no file or directory is created**.
        """
        safe_name = sanitize_component(name)
        directory = self.root
        if subdir is not None:
            relative = sanitize_relative(subdir)
            if relative.parts:
                directory = self.root / relative
        assert_contained(self.root, directory / safe_name)

        candidate = directory / safe_name
        if self._is_free(candidate):
            self._taken.add(self._key(candidate))
            return candidate

        for index in range(1, MAX_COLLISION_ATTEMPTS + 1):
            candidate = directory / numbered_variant(safe_name, index)
            if self._is_free(candidate):
                self._taken.add(self._key(candidate))
                return candidate

        raise ReservationError(
            f"no free name could be found for {safe_name!r} after "
            f"{MAX_COLLISION_ATTEMPTS} attempts",
            f"directory={directory}",
        )

    @property
    def planned_count(self) -> int:
        return len(self._taken)


# --------------------------------------------------------------------------- #
# Run reservation — the materialisation boundary
# --------------------------------------------------------------------------- #

#: Cap on the run-number search, so a wedged directory cannot spin forever.
MAX_RUN_ATTEMPTS = 10_000


@dataclass(frozen=True)
class RunReservation:
    """An immutable record of one reserved run directory.

    Captured at validated run start and handed to the worker, so a preference
    changed mid-run cannot move an operation that is already going.
    """

    tool_key: str
    base_directory: Path
    tool_directory: Path
    run_directory: Path
    run_number: int
    #: The effective configuration snapshot this run was planned against.
    config_snapshot: object = field(repr=False, default=None)

    def planner(self, **kwargs) -> DestinationPlanner:
        """A collision tracker scoped to this run directory."""
        return DestinationPlanner(self.run_directory, **kwargs)


def reserve_run_directory(
    tool_key: str,
    *,
    effective=None,
    base: Path | None = None,
    max_attempts: int = MAX_RUN_ATTEMPTS,
) -> RunReservation:
    """Atomically reserve ``<base>/<Tool>-Outputs/<Tool>-N`` at run start.

    ``mkdir`` without ``exist_ok`` is the correctness boundary: it either
    creates the directory or raises ``FileExistsError``, so two concurrent
    reservations can never claim the same number. There is deliberately **no**
    "does it exist?" check before the create — that would be exactly the
    check-then-create race this has to avoid.

    Creates only the base, the tool parent and the run directory. Creates no
    file, and never touches anything on the source side.
    """
    prefix = tool_run_prefix(tool_key)          # validates the key first
    snapshot = config.get_effective() if effective is None else effective
    base_dir = Path(base) if base is not None else resolve_output_base(snapshot)

    base_dir = ensure_output_base(base_dir)
    tool_dir = tool_parent_dir(base_dir, tool_key)
    try:
        tool_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReservationError(
            f"the folder for this tool could not be created: {tool_dir}",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    last_error = ""
    for number in range(1, max_attempts + 1):
        candidate = tool_dir / f"{prefix}-{number}"
        try:
            candidate.mkdir()                    # atomic: exclusive by contract
        except FileExistsError:
            continue                             # someone else has this number
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            raise ReservationError(
                f"the output folder could not be created: {candidate}", last_error
            ) from exc
        return RunReservation(
            tool_key=tool_key,
            base_directory=base_dir,
            tool_directory=tool_dir,
            run_directory=candidate,
            run_number=number,
            config_snapshot=snapshot,
        )

    raise ReservationError(
        f"no free run folder was available under {tool_dir} after {max_attempts} attempts",
        f"tried {prefix}-1 .. {prefix}-{max_attempts}",
    )


def release_if_empty(reservation: RunReservation) -> bool:
    """Remove a reserved run directory **only** if it is still empty.

    For the case where validation or cancellation ends a run before anything
    was written. Best-effort and deliberately timid: a directory with any
    content in it is never removed, and a failure is reported as ``False``
    rather than raised.
    """
    directory = Path(reservation.run_directory)
    try:
        if not directory.is_dir() or _is_link(directory):
            return False
        if any(directory.iterdir()):
            return False
        directory.rmdir()
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Pure path planning
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlannedOutput:
    """One source file and the destination chosen for it. Nothing created."""

    source: Path
    destination: Path
    #: Destination path relative to the plan root, for display and logging.
    relative: PurePath


@dataclass(frozen=True)
class OutputPlan:
    """An immutable batch plan. Building one creates no directory or file."""

    root: Path
    items: tuple[PlannedOutput, ...]

    def __len__(self) -> int:
        return len(self.items)

    @property
    def destinations(self) -> tuple[Path, ...]:
        return tuple(item.destination for item in self.items)

    def directories(self) -> tuple[Path, ...]:
        """Every directory a caller would need to create to write this plan."""
        seen: list[Path] = []
        for item in self.items:
            parent = item.destination.parent
            if parent not in seen:
                seen.append(parent)
        return tuple(seen)


def _finish(root: Path, pairs: Sequence[tuple[Path, Path]]) -> OutputPlan:
    items = tuple(
        PlannedOutput(source=src, destination=dest, relative=PurePath(dest.relative_to(root)))
        for src, dest in pairs
    )
    return OutputPlan(root=Path(root), items=items)


def plan_flat(
    root: Path,
    sources: Iterable[Path],
    *,
    planner: DestinationPlanner | None = None,
    rename=None,
) -> OutputPlan:
    """Individually selected files land directly in the run directory.

    Their parent trees are **not** recreated — Decision 31A. Same-named files
    from different folders are separated by collision numbering
    (``Book.m4b``, ``Book-1.m4b``, …), in the order given, deterministically.

    ``rename`` optionally maps a source to the output filename it should use
    (a tool that changes extension, for example); the result is sanitised and
    collision-checked exactly like any other name.
    """
    tracker = planner if planner is not None else DestinationPlanner(root)
    pairs: list[tuple[Path, Path]] = []
    for source in sources:
        source = Path(source)
        name = rename(source) if rename is not None else source.name
        pairs.append((source, tracker.plan(name)))
    return _finish(root, pairs)


def plan_mirrored(
    root: Path,
    sources: Iterable[Path],
    source_root: Path,
    *,
    planner: DestinationPlanner | None = None,
    rename=None,
) -> OutputPlan:
    """One folder-import root: mirror each source's relative parent path.

    ``<run>/<relative parent>/<name>`` — so ``Books/Series A/ch1.mp3`` under
    root ``Books`` becomes ``<run>/Series A/ch1.mp3``, and same-stem files in
    different subfolders never collide because their folders differ.

    A source that is not inside *source_root* raises :class:`UnsafePathError`
    rather than being silently flattened into the run directory.
    """
    tracker = planner if planner is not None else DestinationPlanner(root)
    source_root_n = _normalise(Path(source_root))
    pairs: list[tuple[Path, Path]] = []
    for source in sources:
        source = Path(source)
        relative_parent = _relative_parent(source, source_root_n)
        name = rename(source) if rename is not None else source.name
        pairs.append((source, tracker.plan(name, subdir=relative_parent)))
    return _finish(root, pairs)


def plan_multi_root(
    root: Path,
    grouped: Sequence[tuple[Path, Sequence[Path]]],
    *,
    planner: DestinationPlanner | None = None,
    rename=None,
) -> OutputPlan:
    """Several folder-import roots: one collision-safe container per root.

    ``<run>/<root name>/<relative parent>/<name>``. Two roots whose final
    folder name is the same (``D:/A/Books`` and ``E:/B/Books``) get ``Books``
    and ``Books-1``, in the order supplied, so one root's tree can never be
    merged into another's.
    """
    tracker = planner if planner is not None else DestinationPlanner(root)
    labels = DestinationPlanner(root, check_filesystem=False)
    pairs: list[tuple[Path, Path]] = []
    for source_root, sources in grouped:
        source_root = Path(source_root)
        label = labels.plan(source_root.name or FALLBACK_COMPONENT).name
        source_root_n = _normalise(source_root)
        for source in sources:
            source = Path(source)
            relative_parent = _relative_parent(source, source_root_n)
            subdir = PurePath(label) / relative_parent if relative_parent.parts else PurePath(label)
            name = rename(source) if rename is not None else source.name
            pairs.append((source, tracker.plan(name, subdir=subdir)))
    return _finish(root, pairs)


def _relative_parent(source: Path, source_root_n: Path) -> PurePath:
    """The sanitised relative parent of *source* inside its declared root."""
    source_n = _normalise(source)
    try:
        relative = source_n.relative_to(source_root_n)
    except ValueError:
        raise UnsafePathError(
            "a selected file is not inside the folder it was imported from",
            f"{source_n} is not under {source_root_n}",
        ) from None
    return sanitize_relative(PurePath(relative).parent)
