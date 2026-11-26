"""One contained, no-follow view of a checkout's files (v0.8.2 Phase 1A-1 R1: findings H4 and C1).

Every gate reader that turns repository paths into selection facts -- selector identity, AST discovery
(``helpers/effects.py``), the import closure (``helpers/evidence_ledger.Closures``), the changed-file routing
(``helpers/selection.py``) and the candidate identity (``helpers/git_changes.py``) -- asks this inventory, so a path
classified as unsafe once is never read by another of them.

* **Contained.** A path is relative to the root, ``/``-separated; ``..``, an absolute path or a drive is refused.
* **No-follow.** Every component is ``lstat``-ed: a symbolic link, a junction or any other reparse point anywhere on the
  path is ``link`` (or ``inside-link`` below one) and is never read. Only a regular file is ``file``.
* **Canonical spelling.** :meth:`Inventory.canonical` returns the on-disk spelling of every component, read from the
  directory listing. On a case-insensitive filesystem (NTFS, APFS by default) a case variant resolves to the one real
  entry, and two entries that differ only in case make the spelling ``ambiguous``; on a case-sensitive one a variant is
  simply another, usually missing, path. The root's own case semantics are probed once, never assumed from the platform.

This is a cooperating-verification control: it never claims race-free containment against a concurrent hostile writer
(a path can change between the check and the read; a read that sees a different file size is refused as unstable).
Standard library only.
"""

from __future__ import annotations

import os
import sys
import stat
from pathlib import Path

#: The outcomes of :meth:`Inventory.classify`. Only ``file`` may be read.
FILE, MISSING, LINK, INSIDE_LINK, DIRECTORY, UNSUPPORTED, OUTSIDE, AMBIGUOUS = (
    "file", "missing", "link", "inside-link", "directory", "unsupported", "outside", "ambiguous")
_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


class UnsafePath(OSError):
    """A path the inventory will not read: outside the root, a link or below one, not a regular file, ambiguous."""

    def __init__(self, relative: str, kind: str, detail: str = "") -> None:
        super().__init__(f"{relative}: {kind}" + (f" ({detail})" if detail else ""))
        self.relative = relative
        self.kind = kind


def normalize(text: str) -> str | None:
    """A relative ``/``-separated spelling: backslashes become ``/``, ``./`` and empty components drop out. None for an
    absolute path, a drive, ``..`` or nothing at all. Case is left as written (see :meth:`Inventory.canonical`)."""
    if not isinstance(text, str):
        return None
    raw = text.replace("\\", "/")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        return None
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def probe_case_sensitive(root: Path) -> bool:
    """Whether names under ``root`` are case-sensitive: a swapped-case spelling of the root that names the same directory
    means no. A root with no letter to swap falls back to the platform's usual default."""
    root = Path(os.path.abspath(root))
    for index in range(len(root.parts) - 1, 0, -1):
        part = root.parts[index]
        swapped = part.swapcase()
        if swapped == part:
            continue
        other = Path(*root.parts[:index], swapped, *root.parts[index + 1:])
        try:
            return not (other.exists() and os.path.samefile(other, root))
        except OSError:
            return True
    return not (os.name == "nt" or sys.platform == "darwin")


class Inventory:
    """The no-follow, contained view of one root. Facts are memoised: build one per snapshot, as resolution does."""

    def __init__(self, root, *, case_sensitive: bool | None = None, listdir=None) -> None:
        self.root = Path(os.path.abspath(root))
        self.case_sensitive = probe_case_sensitive(self.root) if case_sensitive is None else bool(case_sensitive)
        self._listdir = listdir or (lambda path: [entry.name for entry in os.scandir(path)])
        self._entries: dict[str, list[str] | None] = {}
        self._kinds: dict[str, tuple[str, str]] = {}
        self._canonical: dict[str, tuple[str | None, str, str]] = {}

    # ------------------------------------------------------------------ names
    def _listing(self, directory: str) -> list[str] | None:
        if directory not in self._entries:
            try:
                self._entries[directory] = list(self._listdir(self.root / directory if directory else self.root))
            except OSError:
                self._entries[directory] = None
        return self._entries[directory]

    def canonical(self, text: str) -> tuple[str | None, str, str]:
        """``(canonical relative path or None, kind, detail)``. ``kind`` is a :meth:`classify` outcome; for ``file`` and
        ``directory`` the path is the on-disk spelling. A missing path keeps its normalized spelling."""
        relative = normalize(text)
        if relative is None:
            return None, OUTSIDE, "not a contained relative path"
        if relative in self._canonical:
            return self._canonical[relative]
        spelled: list[str] = []
        result: tuple[str | None, str, str] | None = None
        parts = relative.split("/")
        for index, part in enumerate(parts):
            listing = self._listing("/".join(spelled))
            if listing is None:
                result = (relative, MISSING, "a parent is not a readable directory")
                break
            if self.case_sensitive:
                found = [part] if part in listing else []
            else:
                folded = part.casefold()
                found = [name for name in listing if name.casefold() == folded]
            if not found:
                result = (relative, MISSING, "")
                break
            if len(found) > 1:
                result = (None, AMBIGUOUS, f"{len(found)} entries differ only in case at component {index + 1}")
                break
            spelled.append(found[0])
            kind, detail = self._lstat_kind("/".join(spelled))
            if kind == LINK:
                result = (None, LINK if index == len(parts) - 1 else INSIDE_LINK, "/".join(spelled))
                break
            if index < len(parts) - 1 and kind != DIRECTORY:
                result = (relative, MISSING, "a parent is not a directory")
                break
        if result is None:
            path = "/".join(spelled)
            kind, detail = self._lstat_kind(path)
            result = (path, kind, detail)
        self._canonical[relative] = result
        return result

    def _lstat_kind(self, relative: str) -> tuple[str, str]:
        if relative not in self._kinds:
            try:
                info = os.lstat(self.root / relative)
            except FileNotFoundError:
                self._kinds[relative] = (MISSING, "")
            except OSError as exc:
                self._kinds[relative] = (UNSUPPORTED, type(exc).__name__)
            else:
                if is_link(info):
                    self._kinds[relative] = (LINK, "")
                elif stat.S_ISDIR(info.st_mode):
                    self._kinds[relative] = (DIRECTORY, "")
                elif stat.S_ISREG(info.st_mode):
                    self._kinds[relative] = (FILE, "")
                else:
                    self._kinds[relative] = (UNSUPPORTED, "not a regular file")
        return self._kinds[relative]

    # ------------------------------------------------------------------ facts
    def classify(self, text: str) -> str:
        """What ``text`` names, never following a link: one of the module-level outcomes. A path spelled with another case
        than the on-disk name counts as that name on a case-insensitive filesystem."""
        return self.canonical(text)[1]

    def is_file(self, text: str) -> bool:
        return self.classify(text) == FILE

    def exists(self, text: str) -> bool:
        """Something is at the path (a file, a directory, a link, ...): lexical presence, never following a link."""
        return self.classify(text) not in (MISSING, OUTSIDE)

    def read_bytes(self, text: str) -> bytes:
        path, kind, detail = self.canonical(text)
        if kind != FILE or path is None:
            raise UnsafePath(normalize(text) or str(text), kind, detail)
        full = self.root / path
        before = os.lstat(full)
        data = full.read_bytes()
        after = os.lstat(full)
        if is_link(after) or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) \
                or len(data) != after.st_size:
            raise UnsafePath(path, UNSUPPORTED, "changed while it was read")
        return data

    def read_text(self, text: str) -> str:
        return self.read_bytes(text).decode("utf-8", errors="replace")
