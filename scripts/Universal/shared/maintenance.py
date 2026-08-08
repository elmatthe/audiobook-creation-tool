"""The downloaded-data catalog, inventory, and cleanup request/result schemas.

Platform-neutral and Tk-free. Everything the Clear Downloaded Data flow decides
— which assets exist, what they are allowed to point at, how big they are, what
the user is about to be told — is decided here and tested against temporary fake
repository roots. ``shared.preferences_ui`` renders the result and collects the
choice; it decides nothing.

**This module deletes nothing.** It has no executor, no coordinator, no process
spawning and no persistence, and it imports neither ``shutil`` nor
``subprocess``. It is the shared vocabulary of both sides of the cleanup
boundary: the GUI builds a :class:`CleanupRequest` here, and the separate
non-venv coordinator (``shared.cleanup_worker``, started through
``shared.cleanup_state``) is the only code that acts on one and the only code
that produces a :class:`CleanupResult`. Keeping the schemas, the target rules
and the wording here — and the acting there — is what makes the safe half
testable in isolation. ``files/tests/test_maintenance.py`` asserts the absence
of every destructive primitive, so a regression fails the suite.

The safety model is deliberately narrow:

* The catalog is a closed set of four enumerated IDs. There is no fifth asset
  and no way to add one at runtime.
* A GUI and a serialized request carry **asset IDs only**. No path, root,
  target, directory or command ever crosses that boundary, so no string from
  JSON, TOML or a widget can ever name something to delete.
* An ID is mapped to a path only by :func:`authorized_target`, only relative to
  an explicitly supplied repository root, and only after the result is proven to
  be the exact compiled target, inside the root, not the root itself, not a
  protected location, and not reached through a link.
"""

from __future__ import annotations

import os
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class MaintenanceError(Exception):
    """Base class for every refusal in this module."""


class UnknownAssetError(MaintenanceError):
    """The value offered is not one of the four enumerated asset IDs."""


class UnsafeTargetError(MaintenanceError):
    """An ID's mapped target failed a safety rule and must not be offered."""


class SelectionError(MaintenanceError):
    """A selection named something that is not eligible for cleanup."""


class SchemaError(MaintenanceError):
    """A request or result did not satisfy its schema exactly."""


# --------------------------------------------------------------------------- #
# The catalog
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AssetDefinition:
    """One immutable catalog entry. There are exactly four, and never a fifth.

    ``relative_target`` is posix-style and always relative to the repository
    root supplied at call time — never absolute, never user-supplied.
    """

    asset_id: str
    display_name: str
    relative_target: str
    consequence: str
    effect_line: str
    requires_post_exit: bool
    #: True when cleanup removes the directory itself (``.venv``); False when it
    #: removes the *contents* and leaves the directory in place. Recorded here
    #: so Phase 7 inherits the semantics rather than reinventing them.
    removes_target_itself: bool


CATALOG: tuple[AssetDefinition, ...] = (
    AssetDefinition(
        asset_id="virtual_environment",
        display_name="Private Python environment",
        relative_target=".venv",
        consequence="Dependencies rebuild on the next launch.",
        effect_line=(
            "Private Python environment: dependencies will be rebuilt on the next "
            "launch. This may take several minutes and may require a network "
            "connection."
        ),
        requires_post_exit=True,
        removes_target_itself=True,
    ),
    AssetDefinition(
        asset_id="portable_binaries",
        display_name="Portable binaries",
        relative_target="files/bin",
        consequence=(
            "Project-owned portable ffmpeg may need to download again. "
            "System-installed ffmpeg is never removed."
        ),
        effect_line=(
            "Portable binaries: project-owned portable ffmpeg files may need to be "
            "downloaded again. System-installed ffmpeg will not be removed."
        ),
        requires_post_exit=False,
        removes_target_itself=False,
    ),
    AssetDefinition(
        asset_id="downloaded_models",
        display_name="Downloaded voice models",
        relative_target="files/runtime-data/models",
        consequence="Kokoro/Hugging Face data downloads again when needed.",
        effect_line=(
            "Downloaded voice models: Kokoro/Hugging Face data will download again "
            "when needed."
        ),
        requires_post_exit=False,
        removes_target_itself=False,
    ),
    AssetDefinition(
        asset_id="application_logs",
        display_name="Application logs",
        relative_target="files/runtime-data/logs",
        consequence="Diagnostic history is permanently removed.",
        effect_line="Application logs: diagnostic history will be permanently removed.",
        #: The current session's log file is open while the app runs, so removal
        #: waits for exit on every platform rather than only on Windows.
        requires_post_exit=True,
        removes_target_itself=False,
    ),
)

#: Deterministic catalog order — the order rows render, requests serialize and
#: confirmation lines appear. Never sorted by anything else.
ASSET_IDS: tuple[str, ...] = tuple(a.asset_id for a in CATALOG)

CATALOG_BY_ID: Mapping[str, AssetDefinition] = MappingProxyType(
    {a.asset_id: a for a in CATALOG}
)

#: Repository locations that must never be reachable from a catalog target,
#: either because the target *is* one or because the target would contain one.
#: Relative, posix-style, resolved against the supplied root like a target is.
PROTECTED_RELATIVE: tuple[str, ...] = (
    ".git",
    "scripts",
    "md-instructions",
    "files/tests",
    "files/UI-Current-Screenshots",
    "files/UI-Prototype-Screenshots",
    "files/runtime-data/settings.json",
    "config.toml",
    "config-template.toml",
    "README.md",
    "AI-WORKSPACE.md",
    "Setup_and_Run-audiobook-creation-tool.bat",
    "Setup_and_Run-audiobook-creation-tool.command",
)


def asset(asset_id) -> AssetDefinition:
    """The catalog entry for *asset_id*, or :class:`UnknownAssetError`.

    The dictionary lookup is the whole allowlist: a path-like string, a
    traversal attempt, an absolute path, ``None`` or a non-string simply is not
    a key, so none of them can name a target.
    """
    if not isinstance(asset_id, str):
        raise UnknownAssetError(
            f"asset id must be a string, not {type(asset_id).__name__}"
        )
    try:
        return CATALOG_BY_ID[asset_id]
    except KeyError:
        raise UnknownAssetError(f"{asset_id!r} is not a known downloaded-data item") from None


def validate_asset_ids(values) -> tuple[str, ...]:
    """Normalise a selection to deterministic catalog order.

    Rejects an empty selection, a duplicate, an unknown ID and a non-sequence.
    Order in equals nothing: the result is always catalog order, so two callers
    that select the same items produce byte-identical requests.
    """
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple, set, frozenset)):
        raise SchemaError("selected asset ids must be a list or tuple")
    items = list(values)
    if not items:
        raise SchemaError("a cleanup request must select at least one item")
    seen: set[str] = set()
    for value in items:
        definition = asset(value)
        if definition.asset_id in seen:
            raise SchemaError(f"{definition.asset_id!r} was selected more than once")
        seen.add(definition.asset_id)
    return tuple(i for i in ASSET_IDS if i in seen)


# --------------------------------------------------------------------------- #
# Target authorization
# --------------------------------------------------------------------------- #

#: Windows and macOS both default to case-insensitive filesystems.
_CASE_INSENSITIVE_FS = os.name == "nt"


def _abs(path) -> Path:
    """Absolute and working-directory-independent, **without** resolving links.

    Deliberately not ``Path.resolve()``: resolving would silently follow a
    junction and hand back a path outside the repository that then compares
    equal to nothing useful. Links are detected explicitly by :func:`_is_link`.
    """
    return Path(os.path.abspath(str(path)))


def _key(path: Path) -> tuple[str, ...]:
    parts = path.parts
    return tuple(p.casefold() for p in parts) if _CASE_INSENSITIVE_FS else parts


def _within(root: Path, candidate: Path) -> bool:
    root_parts, cand_parts = _key(root), _key(candidate)
    return (
        len(cand_parts) > len(root_parts)
        and cand_parts[: len(root_parts)] == root_parts
    )


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


def absolute(path) -> Path:
    """Public :func:`_abs` — absolute, cwd-independent, links left unresolved."""
    return _abs(path)


def same_path(first, second) -> bool:
    """Whether two paths name the same location under this filesystem's casing."""
    return _key(_abs(first)) == _key(_abs(second))


def is_within(root, candidate) -> bool:
    """Whether *candidate* is strictly inside *root*. Equality is not "inside"."""
    return _within(_abs(root), _abs(candidate))


def is_link(path) -> bool:
    """Public :func:`_is_link` — symlink, junction, or any other reparse point.

    Exported so the coordinator applies the same rule this module applies,
    rather than a second implementation that could drift from it.
    """
    return _is_link(Path(path))


def compiled_target(asset_id, repo_root) -> Path:
    """The one path *asset_id* compiles to under *repo_root*. No safety checks.

    Separate from :func:`authorized_target` so the equality check there compares
    against something computed the same way twice, rather than against itself.
    """
    definition = asset(asset_id)
    root = _abs(repo_root)
    return root.joinpath(*definition.relative_target.split("/"))


def authorized_target(asset_id, repo_root) -> Path:
    """The proven-safe path for *asset_id*, or :class:`UnsafeTargetError`.

    Every rule is applied before the path is returned, so a caller that holds
    one of these holds something already checked rather than something it must
    remember to check.
    """
    root = _abs(repo_root)
    target = compiled_target(asset_id, root)

    if _key(target) == _key(root):
        raise UnsafeTargetError("the repository root itself is never a cleanup target")
    if not _within(root, target):
        raise UnsafeTargetError(
            f"{asset_id} would point outside the project folder, which is refused"
        )

    for relative in PROTECTED_RELATIVE:
        protected = root.joinpath(*relative.split("/"))
        if _key(target) == _key(protected):
            raise UnsafeTargetError(f"{relative} is protected and is never removed")
        if _within(protected, target):
            raise UnsafeTargetError(f"{relative} is protected and is never removed")
        if _within(target, protected):
            raise UnsafeTargetError(
                f"this would also remove {relative}, which is protected"
            )

    if _is_link(root):
        raise UnsafeTargetError(
            "the project folder is a shortcut or link, which is not followed"
        )
    walked = root
    for part in target.relative_to(root).parts:
        walked = walked / part
        if _is_link(walked):
            raise UnsafeTargetError(
                "this item is a shortcut or link, which is never followed or removed"
            )
    return target


def assert_authorized(asset_id, repo_root, target) -> Path:
    """Prove *target* is exactly what *asset_id* is allowed to name.

    The check a worker performs immediately before acting, and the check
    :func:`inventory` performs before an item is offered for selection: a path
    that did not come from :func:`authorized_target` cannot pass it.
    """
    expected = authorized_target(asset_id, repo_root)
    if _key(_abs(target)) != _key(expected):
        raise UnsafeTargetError(
            f"{asset_id} may only refer to {expected}, not {_abs(target)}"
        )
    return expected


# --------------------------------------------------------------------------- #
# Size estimation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SizeEstimate:
    """Bytes counted, and whether the count is the whole truth.

    ``complete`` is False whenever anything was skipped — an unreadable folder,
    a link that was deliberately not followed. The total is then a floor, never
    presented as exact.
    """

    total_bytes: int
    complete: bool = True
    problems: tuple[str, ...] = ()


def estimate_size(path) -> SizeEstimate:
    """Total regular-file bytes under *path*, never following a link.

    Read-only by construction: ``scandir``/``lstat`` only. Nothing here opens,
    writes, touches a timestamp or changes a permission. Files that vanish
    mid-walk are normal (a log can rotate underneath us) and are skipped
    silently; anything genuinely unreadable is recorded and makes the estimate
    incomplete rather than raising into the UI.
    """
    target = Path(path)
    total = 0
    problems: list[str] = []
    complete = True

    try:
        info = os.lstat(target)
    except FileNotFoundError:
        return SizeEstimate(0, True, ())
    except OSError as exc:
        return SizeEstimate(0, False, (f"{target.name}: {exc.strerror or exc}",))

    if _is_link(target):
        return SizeEstimate(0, False, (f"{target.name} is a link and was not followed",))
    if stat.S_ISREG(info.st_mode):
        return SizeEstimate(int(info.st_size), True, ())
    if not stat.S_ISDIR(info.st_mode):
        return SizeEstimate(0, False, (f"{target.name} is not a folder or a file",))

    stack = [target]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except FileNotFoundError:
            continue  # removed while we walked; not an error
        except OSError as exc:
            complete = False
            problems.append(f"{current.name}: {exc.strerror or exc}")
            continue
        for entry in entries:
            try:
                if entry.is_symlink() or _is_link(Path(entry.path)):
                    complete = False
                    problems.append(f"{entry.name} is a link and was not followed")
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except FileNotFoundError:
                continue
            except OSError as exc:
                complete = False
                problems.append(f"{entry.name}: {exc.strerror or exc}")
    return SizeEstimate(total, complete, tuple(problems))


_UNITS = ("KB", "MB", "GB", "TB")


def format_bytes(count: int) -> str:
    """Human sizes: ``0 bytes``, ``1 byte``, ``940 bytes``, ``1.2 MB``."""
    count = int(count)
    if count < 0:
        raise ValueError("a byte count cannot be negative")
    if count == 1:
        return "1 byte"
    if count < 1024:
        return f"{count} bytes"
    value = float(count)
    unit = _UNITS[0]
    for unit in _UNITS:
        value /= 1024.0
        if value < 1024.0:
            break
    return f"{value:.1f} {unit}"


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #

STATE_PRESENT = "Present"
STATE_MISSING = "Missing"
CALCULATING_TEXT = "Calculating…"
UNKNOWN_SIZE_TEXT = "Size unavailable"
INCOMPLETE_SUFFIX = " (at least)"
NOT_A_FOLDER_PROBLEM = "This is not a folder, so it is not offered for removal."
INCOMPLETE_PROBLEM = "Part of this item could not be read, so the size shown is a minimum."


@dataclass(frozen=True)
class InventoryItem:
    """One row of the Clear Downloaded Data list. Immutable by construction."""

    asset_id: str
    display_name: str
    present: bool
    selectable: bool
    consequence: str
    requires_post_exit: bool
    size: SizeEstimate | None = None
    problem: str | None = None

    @property
    def state_text(self) -> str:
        return STATE_PRESENT if self.present else STATE_MISSING

    @property
    def size_text(self) -> str:
        """What the row shows in its size column, never a false exact total."""
        if not self.present:
            return "—"
        if self.size is None:
            return CALCULATING_TEXT if self.selectable else UNKNOWN_SIZE_TEXT
        if not self.size.complete:
            return format_bytes(self.size.total_bytes) + INCOMPLETE_SUFFIX
        return format_bytes(self.size.total_bytes)

    @property
    def summary_text(self) -> str:
        """``Present, 1.2 MB`` — the state/size phrase used in confirmations."""
        return f"{self.state_text}, {self.size_text}" if self.present else self.state_text


def inventory(repo_root, *, measure: bool = True) -> tuple[InventoryItem, ...]:
    """Snapshot all four catalog items under *repo_root*, in catalog order.

    *repo_root* is always explicit so the suite inventories a temporary fake
    tree and never the maintainer's real project. With ``measure=False`` no
    directory is walked at all, which is what lets the dialog paint its rows on
    the main thread instantly and fill sizes in from a worker.

    A missing target is a normal state, not an error. An unsafe one is present
    but unavailable, carrying the explanation the row shows.
    """
    items: list[InventoryItem] = []
    for definition in CATALOG:
        items.append(_inventory_one(definition, repo_root, measure=measure))
    return tuple(items)


def _inventory_one(definition: AssetDefinition, repo_root, *, measure: bool) -> InventoryItem:
    common = {
        "asset_id": definition.asset_id,
        "display_name": definition.display_name,
        "consequence": definition.consequence,
        "requires_post_exit": definition.requires_post_exit,
    }
    compiled = compiled_target(definition.asset_id, repo_root)
    try:
        exists = os.path.lexists(compiled)
    except OSError:
        exists = False

    try:
        target = authorized_target(definition.asset_id, repo_root)
        assert_authorized(definition.asset_id, repo_root, target)
    except UnsafeTargetError as exc:
        return InventoryItem(present=bool(exists), selectable=False,
                             problem=str(exc), **common)

    if not exists:
        return InventoryItem(present=False, selectable=False, **common)
    if not target.is_dir():
        return InventoryItem(present=True, selectable=False,
                             problem=NOT_A_FOLDER_PROBLEM, **common)

    if not measure:
        return InventoryItem(present=True, selectable=True, size=None, **common)

    size = estimate_size(target)
    return InventoryItem(
        present=True, selectable=True, size=size,
        problem=None if size.complete else INCOMPLETE_PROBLEM, **common,
    )


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SelectionSummary:
    """What is selected and how much of its size is actually known."""

    asset_ids: tuple[str, ...]
    known_bytes: int
    complete: bool

    @property
    def count(self) -> int:
        return len(self.asset_ids)


def summarise_selection(items: Sequence[InventoryItem], selected_ids) -> SelectionSummary:
    """Total only what is explicitly selected *and* eligible.

    Refuses an ID that is missing, unsafe or simply not in the snapshot: a
    selection can never be widened by the arithmetic that describes it. When a
    selected item's size is unknown or partial the total stays truthful by
    reporting ``complete=False`` rather than inventing a number.
    """
    by_id = {item.asset_id: item for item in items}
    chosen: list[InventoryItem] = []
    seen: set[str] = set()
    for value in selected_ids or ():
        definition = asset(value)
        if definition.asset_id in seen:
            raise SelectionError(f"{definition.asset_id!r} was selected more than once")
        seen.add(definition.asset_id)
        item = by_id.get(definition.asset_id)
        if item is None:
            raise SelectionError(f"{definition.asset_id!r} is not in this inventory")
        if not item.selectable:
            raise SelectionError(f"{definition.asset_id!r} is not available for cleanup")
        chosen.append(item)

    ordered = tuple(i for i in ASSET_IDS if i in seen)
    known = sum(item.size.total_bytes for item in chosen if item.size is not None)
    complete = all(item.size is not None and item.size.complete for item in chosen)
    return SelectionSummary(ordered, known, complete)


# --------------------------------------------------------------------------- #
# User-facing text — pure, so the exact wording is tested without Tk
# --------------------------------------------------------------------------- #

CLEANUP_DIALOG_TITLE = "Clear Downloaded Data"
CLEANUP_INTRO = (
    "Remove only regenerable data downloaded or created by Audiobook Creation Tool. "
    "Your preferences, configuration, source media, and audiobook outputs are not included."
)
REVIEW_BUTTON_LABEL = "Review Selected Data…"
CANCEL_BUTTON_LABEL = "Cancel"
NOTHING_SELECTED_TEXT = "Nothing selected."

CONFIRM_TITLE = "Confirm clearing downloaded data"
CLOSE_NOTICE = (
    "Audiobook Creation Tool will close before cleanup starts. Selected data will be "
    "removed only after the app has exited."
)
EXCLUSION_NOTICE = (
    "Preferences, config.toml, source media, and audiobook outputs are not included."
)
FINAL_QUESTION = (
    "This cleanup cannot be undone, although selected dependencies, binaries, and "
    "models can be rebuilt or downloaded again. Continue?"
)

#: Shown when a caller supplied no coordinator handoff at all, so the request
#: was built and then deliberately dropped. Never reached by the shipped app,
#: which always hands off to the real coordinator; kept because a caller with no
#: handoff must still be told the truth rather than shown nothing.
CLEANUP_UNAVAILABLE_MESSAGE = (
    "Cleanup did not start. Safe post-exit cleanup is not available yet. No data was "
    "changed, and Audiobook Creation Tool will remain open."
)

#: Said only after the coordinator has positively acknowledged the request —
#: never on the strength of having started a process.
CLEANUP_SCHEDULED_MESSAGE = (
    "Cleanup is ready. Audiobook Creation Tool will now close, and the selected "
    "downloaded data will be cleared after the app exits."
)

#: Said whenever persistence, launch or acknowledgement failed. The headline is
#: fixed; a short non-sensitive detail may be appended after it.
CLEANUP_FAILED_MESSAGE = (
    "Cleanup did not start. No data was changed, and Audiobook Creation Tool will "
    "remain open."
)

#: Shown while the handoff is in flight, so a bounded wait is never a silent one.
CLEANUP_PREPARING_MESSAGE = "Preparing cleanup — waiting for the cleanup helper to start…"


def freed_space_line(summary: SelectionSummary) -> str:
    """Never a false exact total: an unreadable part is said out loud."""
    total = format_bytes(summary.known_bytes)
    if summary.complete:
        return f"Estimated space to be freed: {total}."
    return (
        f"Estimated space to be freed: {total}, plus data whose size could not be "
        "read safely."
    )


def selected_total_text(summary: SelectionSummary) -> str:
    """The dialog's running total line."""
    if not summary.asset_ids:
        return NOTHING_SELECTED_TEXT
    noun = "item" if summary.count == 1 else "items"
    total = format_bytes(summary.known_bytes)
    if summary.complete:
        return f"{summary.count} {noun} selected — about {total}."
    return (
        f"{summary.count} {noun} selected — at least {total}, plus data whose size "
        "could not be read safely."
    )


def confirmation_button_label(count: int) -> str:
    """Exact singular/plural destructive label. Never the default action."""
    if count == 1:
        return "Clear 1 Selected Item and Close"
    return f"Clear {count} Selected Items and Close"


def confirmation_body(items: Sequence[InventoryItem], selected_ids) -> str:
    """The whole confirmation text, built fresh from the current snapshot.

    Rebuilt on every open from the live selection rather than cached, so the
    count, the sizes and the effect lines can never describe a stale choice.
    """
    summary = summarise_selection(items, selected_ids)
    by_id = {item.asset_id: item for item in items}

    lines = [f"You selected {summary.count} downloaded-data item(s) to clear:", ""]
    for asset_id in summary.asset_ids:
        item = by_id[asset_id]
        lines.append(f"  • {item.display_name} — {item.summary_text}")
        lines.append(f"      {item.consequence}")
    lines.append("")
    lines.append(freed_space_line(summary))
    lines.append("")
    lines.append(CLOSE_NOTICE)
    lines.append("")
    for asset_id in summary.asset_ids:
        lines.append(CATALOG_BY_ID[asset_id].effect_line)
    lines.append("")
    lines.append(EXCLUSION_NOTICE)
    lines.append("")
    lines.append(FINAL_QUESTION)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Cleanup request — versioned, immutable, and free of paths by construction
# --------------------------------------------------------------------------- #

SCHEMA_VERSION = 1

#: The complete serialized allowlist. Note what is absent and must stay absent:
#: no ``path``, ``target``, ``directory``, ``root``, ``command`` or executable
#: field exists, so a request physically cannot name something to delete.
REQUEST_FIELDS: tuple[str, ...] = (
    "schema_version", "asset_ids", "process_id", "created_at", "request_id",
)


def _check_int(value, label: str) -> int:
    # bool is an int subclass; True must not pass as a process id or a version.
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaError(f"{label} must be an integer")
    return value


def _check_utc(value, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise SchemaError(f"{label} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchemaError(f"{label} must be timezone-aware")
    return value


def _check_uuid(value, label: str) -> str:
    if not isinstance(value, str):
        raise SchemaError(f"{label} must be a string")
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise SchemaError(f"{label} must be a UUID") from None
    return value


def _check_fields(data, allowed: Sequence[str], label: str) -> Mapping:
    if not isinstance(data, dict):
        raise SchemaError(f"a {label} must be an object")
    keys = set(data)
    missing = set(allowed) - keys
    extra = keys - set(allowed)
    if missing:
        raise SchemaError(f"{label} is missing {', '.join(sorted(missing))}")
    if extra:
        raise SchemaError(f"{label} has unexpected {', '.join(sorted(extra))}")
    return data


@dataclass(frozen=True)
class CleanupRequest:
    """An immutable, validated instruction naming only enumerated asset IDs.

    Validation happens in ``__post_init__``, so there is no construction path —
    direct, deserialized or otherwise — that produces an invalid request.
    Phase 6 builds these and hands them to a callback; nothing writes one to
    disk or acts on one.
    """

    schema_version: int
    asset_ids: tuple[str, ...]
    process_id: int
    created_at: datetime
    request_id: str

    def __post_init__(self) -> None:
        if _check_int(self.schema_version, "schema_version") != SCHEMA_VERSION:
            raise SchemaError(f"unsupported request schema version {self.schema_version}")
        object.__setattr__(self, "asset_ids", validate_asset_ids(self.asset_ids))
        if _check_int(self.process_id, "process_id") <= 0:
            raise SchemaError("process_id must be a positive integer")
        _check_utc(self.created_at, "created_at")
        _check_uuid(self.request_id, "request_id")


def build_request(
    selected_ids: Iterable[str],
    *,
    clock: Callable[[], datetime] | None = None,
    process_id: int | None = None,
    request_id: Callable[[], str] | str | None = None,
) -> CleanupRequest:
    """Construct one validated request. Clock, PID and ID are injectable.

    Injectable so the suite gets byte-deterministic requests without patching
    the standard library.
    """
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    pid = os.getpid() if process_id is None else process_id
    if request_id is None:
        identifier = str(uuid.uuid4())
    elif callable(request_id):
        identifier = request_id()
    else:
        identifier = request_id
    return CleanupRequest(
        schema_version=SCHEMA_VERSION,
        asset_ids=tuple(selected_ids),
        process_id=pid,
        created_at=now,
        request_id=identifier,
    )


def request_to_dict(request: CleanupRequest) -> dict:
    if not isinstance(request, CleanupRequest):
        raise SchemaError("not a cleanup request")
    return {
        "schema_version": request.schema_version,
        "asset_ids": list(request.asset_ids),
        "process_id": request.process_id,
        "created_at": request.created_at.isoformat(),
        "request_id": request.request_id,
    }


def request_from_dict(data) -> CleanupRequest:
    """Strict deserialization: an extra or missing field is a refusal."""
    _check_fields(data, REQUEST_FIELDS, "cleanup request")
    return CleanupRequest(
        schema_version=data["schema_version"],
        asset_ids=_sequence(data["asset_ids"], "asset_ids"),
        process_id=data["process_id"],
        created_at=_parse_time(data["created_at"], "created_at"),
        request_id=data["request_id"],
    )


def _sequence(value, label: str) -> tuple:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise SchemaError(f"{label} must be a list")
    return tuple(value)


def _parse_time(value, label: str) -> datetime:
    if not isinstance(value, str):
        raise SchemaError(f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise SchemaError(f"{label} is not a valid ISO-8601 timestamp") from None
    return _check_utc(parsed, label)


# --------------------------------------------------------------------------- #
# Cleanup result — defined now so Phase 7 inherits a fixed, tested boundary
# --------------------------------------------------------------------------- #

#: The closed set of per-asset outcomes. Phase 7 chooses among these and
#: invents nothing; Phase 6 creates no result during normal use.
OUTCOME_STATUSES: tuple[str, ...] = ("removed", "missing", "failed", "refused")

OUTCOME_FIELDS: tuple[str, ...] = ("asset_id", "status", "bytes_freed", "message")
RESULT_FIELDS: tuple[str, ...] = (
    "schema_version", "request_id", "started_at", "completed_at", "outcomes",
)


@dataclass(frozen=True)
class AssetOutcome:
    """What happened to one enumerated asset. No path field, by design."""

    asset_id: str
    status: str
    bytes_freed: int | None = None
    message: str = ""

    def __post_init__(self) -> None:
        asset(self.asset_id)
        if self.status not in OUTCOME_STATUSES:
            raise SchemaError(f"{self.status!r} is not a known outcome status")
        if self.bytes_freed is not None:
            if _check_int(self.bytes_freed, "bytes_freed") < 0:
                raise SchemaError("bytes_freed cannot be negative")
        if not isinstance(self.message, str):
            raise SchemaError("message must be a string")


@dataclass(frozen=True)
class CleanupResult:
    """The immutable record Phase 7 will write and the next launch will read."""

    schema_version: int
    request_id: str
    started_at: datetime
    completed_at: datetime
    outcomes: tuple[AssetOutcome, ...]

    def __post_init__(self) -> None:
        if _check_int(self.schema_version, "schema_version") != SCHEMA_VERSION:
            raise SchemaError(f"unsupported result schema version {self.schema_version}")
        _check_uuid(self.request_id, "request_id")
        _check_utc(self.started_at, "started_at")
        _check_utc(self.completed_at, "completed_at")
        if self.completed_at < self.started_at:
            raise SchemaError("completed_at cannot precede started_at")
        if isinstance(self.outcomes, (str, bytes)) or not isinstance(
            self.outcomes, (list, tuple)
        ):
            raise SchemaError("outcomes must be a list")
        outcomes = tuple(self.outcomes)
        if not outcomes:
            raise SchemaError("a cleanup result must report at least one outcome")
        seen: set[str] = set()
        for outcome in outcomes:
            if not isinstance(outcome, AssetOutcome):
                raise SchemaError("every outcome must be an AssetOutcome")
            if outcome.asset_id in seen:
                raise SchemaError(f"{outcome.asset_id!r} appears more than once")
            seen.add(outcome.asset_id)
        object.__setattr__(
            self, "outcomes", tuple(
                o for i in ASSET_IDS for o in outcomes if o.asset_id == i
            ),
        )


def outcome_to_dict(outcome: AssetOutcome) -> dict:
    return {
        "asset_id": outcome.asset_id,
        "status": outcome.status,
        "bytes_freed": outcome.bytes_freed,
        "message": outcome.message,
    }


def result_to_dict(result: CleanupResult) -> dict:
    if not isinstance(result, CleanupResult):
        raise SchemaError("not a cleanup result")
    return {
        "schema_version": result.schema_version,
        "request_id": result.request_id,
        "started_at": result.started_at.isoformat(),
        "completed_at": result.completed_at.isoformat(),
        "outcomes": [outcome_to_dict(o) for o in result.outcomes],
    }


def outcome_from_dict(data) -> AssetOutcome:
    _check_fields(data, OUTCOME_FIELDS, "cleanup outcome")
    return AssetOutcome(
        asset_id=data["asset_id"],
        status=data["status"],
        bytes_freed=data["bytes_freed"],
        message=data["message"],
    )


def result_from_dict(data) -> CleanupResult:
    _check_fields(data, RESULT_FIELDS, "cleanup result")
    raw = data["outcomes"]
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        raise SchemaError("outcomes must be a list")
    return CleanupResult(
        schema_version=data["schema_version"],
        request_id=data["request_id"],
        started_at=_parse_time(data["started_at"], "started_at"),
        completed_at=_parse_time(data["completed_at"], "completed_at"),
        outcomes=tuple(outcome_from_dict(o) for o in raw),
    )


# --------------------------------------------------------------------------- #
# Presenting a finished cleanup — pure text, so the wording is tested without Tk
# --------------------------------------------------------------------------- #

RESULT_DIALOG_TITLE = "Downloaded data cleanup"

#: What each closed status is called in front of a non-technical user.
STATUS_TEXT: Mapping[str, str] = MappingProxyType({
    "removed": "Removed",
    "missing": "Nothing was there",
    "failed": "Could not be removed",
    "refused": "Left alone for safety",
})

RESULT_HEADING_COMPLETE = "The downloaded data you selected was cleared."
RESULT_HEADING_NOTHING = "There was nothing left to clear."
RESULT_HEADING_PARTIAL = "Some of the downloaded data could not be cleared."
RESULT_RECOVERY_LINE = (
    "Nothing else was changed. You can try again from Preferences & Data → Clear "
    "Downloaded Data, or remove the remaining files yourself while the app is closed."
)
RESULT_LOG_LINE = "Full technical details are in the session log."
RESULT_UNREADABLE_MESSAGE = (
    "The record of the last cleanup could not be read, so no summary is shown. "
    "Nothing was changed by reading it."
)


def result_is_complete(result: CleanupResult) -> bool:
    """True only when every outcome removed something or found nothing there."""
    return all(o.status in ("removed", "missing") for o in result.outcomes)


def result_freed_bytes(result: CleanupResult) -> tuple[int, bool]:
    """``(bytes known to be freed, whether every figure was known)``."""
    known = sum(o.bytes_freed or 0 for o in result.outcomes)
    complete = all(
        o.bytes_freed is not None for o in result.outcomes if o.status == "removed"
    )
    return known, complete


def result_heading(result: CleanupResult) -> str:
    """One honest headline: never "cleared" when anything failed or was refused."""
    if not result_is_complete(result):
        return RESULT_HEADING_PARTIAL
    if all(o.status == "missing" for o in result.outcomes):
        return RESULT_HEADING_NOTHING
    return RESULT_HEADING_COMPLETE


def result_body(result: CleanupResult) -> str:
    """Every selected item, its outcome, the space freed, and what to do next.

    A size is only ever reported for an item that actually reported one; an
    unknown figure is left out rather than invented.
    """
    lines: list[str] = []
    for outcome in result.outcomes:
        definition = CATALOG_BY_ID[outcome.asset_id]
        line = f"  • {definition.display_name} — {STATUS_TEXT[outcome.status]}"
        if outcome.status == "removed" and outcome.bytes_freed:
            line += f" ({format_bytes(outcome.bytes_freed)} freed)"
        lines.append(line)
        if outcome.message:
            lines.append(f"      {outcome.message}")

    known, complete = result_freed_bytes(result)
    lines.append("")
    if complete:
        lines.append(f"Space freed: {format_bytes(known)}.")
    else:
        lines.append(
            f"Space freed: at least {format_bytes(known)}, plus data whose size was "
            "not measured."
        )
    if not result_is_complete(result):
        lines.append("")
        lines.append(RESULT_RECOVERY_LINE)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The no-coordinator fallback
# --------------------------------------------------------------------------- #


def unavailable_cleanup_handler(request: CleanupRequest) -> bool:
    """The handoff used when a caller supplies none of its own: fail closed.

    Accepting the confirmation validates and constructs the request and hands
    it to a callback. This one returns False — nothing is written, nothing is
    started, nothing is deleted and the application stays open — and the caller
    shows :data:`CLEANUP_UNAVAILABLE_MESSAGE`. It deliberately does **not**
    raise: a refusal is a normal, reportable outcome, not a crash.
    """
    if not isinstance(request, CleanupRequest):
        raise SchemaError("not a cleanup request")
    return False
