"""Which paths a changed-mode candidate changes, read from Git (v0.8.2 Phase 1A-1; plan Revision 5).

The contract:

* Without ``--base`` the anchor is HEAD: HEAD to the index (staged), the index to the working tree (unstaged), and every
  non-ignored untracked path anywhere in the repository. There is no ``origin/master`` default.
* With ``--base REV``, REV must name exactly one commit, and its single merge base with HEAD starts the committed candidate
  side (merge base to HEAD: ``REV..HEAD`` for an ancestor, the candidate's side since divergence otherwise), plus the three
  streams above. The supplied ref, its SHA, the merge base and HEAD are recorded. Nothing is fetched and nothing widens.
* Name-status records are read NUL-delimited with rename detection; a rename keeps its old and its new path. The streams are
  unioned, so a staged change reversed in the working tree is still a change (and is noted: the working bytes are what runs).
* Owner-declared local-only paths (``changed.local_only``: exact paths, or directories ending in ``/``; never a bare string
  prefix) are excluded while untracked; their names never reach the record, only the policy entry and a count. A tracked
  change at such a path is a policy violation, not an exclusion.
* Unresolved index conflicts, an unknown, ambiguous or unrelated base, and several best merge bases are refused
  (:class:`ChangeError`, exit 64): no reliable selection exists.

The candidate identity (:func:`candidate_identity`) is what the future admission contract (Phase 1A-2) binds a grant to: a
digest of the physical checkout, HEAD, the index entries with their modes, the working bytes or deletion marker of every
relevant changed and untracked path, and the policy digest. Links and reparse points are never followed; a file that changes
while it is read is read once more and then refused. This is selection identity, not the Phase 1B evidence fingerprint.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

OUTPUTS_PREFIX = "files/dev-work/verification-gate/outputs/"
SOURCES = ("committed", "staged", "unstaged", "untracked")


class ChangeError(ValueError):
    """No reliable change set can be established: exit 64, nothing runs."""


@dataclass(frozen=True)
class Change:
    path: str
    status: str                    # A M D R C T for Git changes, ? for untracked
    old_path: str | None = None
    sources: tuple[str, ...] = ()

    def record(self) -> dict:
        row = {"path": self.path, "status": self.status, "sources": list(self.sources)}
        if self.old_path:
            row["old_path"] = self.old_path
        return row


@dataclass
class ChangeSet:
    head: str
    base: dict | None
    changes: list[Change] = field(default_factory=list)
    excluded: dict[str, int] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    identity: dict = field(default_factory=dict)

    def paths(self) -> list[str]:
        """Every relevant path, old and new rename sides included."""
        found = {change.path for change in self.changes} | {change.old_path for change in self.changes if change.old_path}
        return sorted(found)

    def record(self) -> dict:
        return {"head": self.head, "base": self.base, "changes": [change.record() for change in self.changes],
                "excluded_local_only": dict(self.excluded), "violations": list(self.violations), "notes": list(self.notes),
                "problems": list(self.problems), "identity": dict(self.identity)}


def _git(root: Path, *args: str, ok=(0,)) -> tuple[int, str, str]:
    done = subprocess.run(["git", "--no-optional-locks", "-c", "core.quotepath=off", *args], cwd=str(root),
                          capture_output=True)
    out = done.stdout.decode("utf-8", "surrogateescape")
    err = done.stderr.decode("utf-8", "replace")
    if done.returncode not in ok:
        raise ChangeError(f"git {' '.join(args[:3])} failed ({done.returncode}): {err.strip()[:300]}")
    return done.returncode, out, err


def parse_name_status(text: str) -> list[tuple[str, str | None, str]]:
    """``(status letter, old path or None, path)`` from ``git diff -z --name-status``. A rename or copy carries two paths."""
    fields = text.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    records, index = [], 0
    while index < len(fields):
        code = fields[index]
        letter = code[:1]
        if letter in ("R", "C"):
            if index + 2 >= len(fields):
                raise ChangeError(f"truncated rename record {code!r}")
            records.append((letter, fields[index + 1], fields[index + 2]))
            index += 3
        else:
            if index + 1 >= len(fields):
                raise ChangeError(f"truncated name-status record {code!r}")
            records.append((letter, None, fields[index + 1]))
            index += 2
    return records


def matches(path: str, entry: str) -> bool:
    """An exact path, or a directory entry (ending in ``/``) at a path-component boundary. Case-sensitive."""
    return path.startswith(entry) if entry.endswith("/") else path == entry


def resolve_base(root: Path, base: str, head: str) -> dict:
    if not base or base != base.strip() or base.startswith("-"):
        raise ChangeError(f"--base {base!r} is not a revision")
    code, out, err = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{base}^{{commit}}", ok=(0, 1, 128))
    if code != 0 or not out.strip():
        raise ChangeError(f"--base {base!r} does not name a commit here (nothing is fetched)")
    if "ambiguous" in err.lower():
        raise ChangeError(f"--base {base!r} is ambiguous: {err.strip()[:200]}")
    sha = out.strip()
    code, out, _err = _git(root, "merge-base", "--all", sha, head, ok=(0, 1))
    bases = [line for line in out.split() if line]
    if not bases:
        raise ChangeError(f"--base {base!r} ({sha[:12]}) shares no history with HEAD")
    if len(bases) > 1:
        raise ChangeError(f"--base {base!r} has {len(bases)} best merge bases with HEAD; name one of them explicitly")
    return {"ref": base, "sha": sha, "merge_base": bases[0]}


def collect(root: Path, *, base: str | None = None, local_only=()) -> ChangeSet:
    root = Path(root)
    code, out, _ = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", ok=(0, 1, 128))
    if code != 0 or not out.strip():
        raise ChangeError("the repository has no commit to anchor a change set")
    head = out.strip()
    _, conflicts, _ = _git(root, "ls-files", "-z", "-u")
    if conflicts.strip("\0"):
        raise ChangeError("the index holds unresolved conflicts; resolve them before a changed selection")
    based = resolve_base(root, base, head) if base else None
    streams: list[tuple[str, list[tuple[str, str | None, str]]]] = []
    if based:
        streams.append(("committed", parse_name_status(_git(root, "diff", "-z", "--name-status", "--find-renames",
                                                             "--no-ext-diff", based["merge_base"], head)[1])))
    streams.append(("staged", parse_name_status(_git(root, "diff", "-z", "--cached", "--name-status", "--find-renames",
                                                      "--no-ext-diff", head)[1])))
    streams.append(("unstaged", parse_name_status(_git(root, "diff", "-z", "--name-status", "--find-renames",
                                                        "--no-ext-diff")[1])))
    untracked = [path for path in _git(root, "ls-files", "-z", "--others", "--exclude-standard")[1].split("\0") if path]
    streams.append(("untracked", [("?", None, path) for path in untracked]))

    merged: dict[str, dict] = {}
    changes = ChangeSet(head=head, base=based)
    for source, records in streams:
        for letter, old, path in records:
            if path.startswith(OUTPUTS_PREFIX):
                continue
            entry = next((item for item in local_only if matches(path, item) or (old and matches(old, item))), None)
            if entry is not None:
                if source == "untracked":
                    changes.excluded[entry] = changes.excluded.get(entry, 0) + 1
                else:
                    changes.violations.append(f"a tracked change ({source}) at the local-only path entry {entry!r}: "
                                              "local-only files are never tracked")
                continue
            row = merged.setdefault(path, {"status": letter, "old": old, "sources": []})
            if letter in ("R", "C") and old:
                row["old"] = row["old"] or old
                row["status"] = letter
            elif row["status"] == "?" and letter != "?":
                row["status"] = letter
            row["sources"].append(source)
    changes.changes = [Change(path, row["status"], row["old"], tuple(dict.fromkeys(row["sources"])))
                       for path, row in sorted(merged.items())]
    # A staged change the working tree has reversed: still a change; the working bytes are what a run would see.
    worktree = {p for p in _git(root, "diff", "-z", "--name-only", "--no-ext-diff", head)[1].split("\0") if p}
    for change in changes.changes:
        if "staged" in change.sources and change.path not in worktree and change.status != "D" and "untracked" not in change.sources:
            changes.notes.append(f"{change.path}: staged, then reversed in the working tree; the working bytes (HEAD's) run")
    return changes


def _is_link(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def _linked_parent(root: Path, relative: str) -> str | None:
    current = root
    for part in relative.split("/")[:-1]:
        current = current / part
        if _is_link(current):
            return current.relative_to(root).as_posix()
    return None


def _stable_digest(path: Path) -> str:
    for _attempt in range(2):
        before = os.lstat(path)
        data = path.read_bytes()
        after = os.lstat(path)
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and len(data) == after.st_size:
            return hashlib.sha256(data).hexdigest()
    raise OSError("changed while it was read")


def candidate_identity(root: Path, changes: ChangeSet, policy_digest: str) -> dict:
    """The selection identity of the candidate. Problems (a link, an unreadable or unstable file) go into ``changes.problems``
    and make the selection incomplete; they never silently drop a path."""
    root = Path(root)
    checkout = os.path.normcase(os.path.realpath(root))
    _, common, _ = _git(root, "rev-parse", "--git-common-dir")
    _, index, _ = _git(root, "ls-files", "-s", "-z")
    working = hashlib.sha256()
    for relative in changes.paths():
        linked = _linked_parent(root, relative)
        path = root / relative
        if linked is not None:
            marker = "<inside a link>"
            changes.problems.append(f"{relative}: below a link or reparse point ({linked}); not followed")
        elif _is_link(path):
            marker = "<link>"
            changes.problems.append(f"{relative}: a link or reparse point; not followed")
        elif not os.path.lexists(path):
            marker = "<deleted>"
        elif path.is_dir():
            marker = "<directory>"
            changes.problems.append(f"{relative}: a directory (a nested repository?); its content is not selectable")
        else:
            try:
                marker = _stable_digest(path)
            except OSError as exc:
                marker = "<unreadable>"
                changes.problems.append(f"{relative}: unreadable or unstable ({type(exc).__name__}: {exc})")
        working.update(relative.encode("utf-8", "surrogateescape") + b"\0" + marker.encode("ascii") + b"\n")
    identity = {
        "checkout_id": hashlib.sha256(checkout.encode("utf-8", "surrogateescape")).hexdigest()[:16],
        "repository_id": hashlib.sha256(os.path.normcase(os.path.realpath(root / common.strip())).encode(
            "utf-8", "surrogateescape")).hexdigest()[:16],
        "head": changes.head, "index_digest": hashlib.sha256(index.encode("utf-8", "surrogateescape")).hexdigest(),
        "working_digest": working.hexdigest(), "policy_digest": policy_digest,
        "paths": len(changes.paths()),
    }
    changes.identity = identity
    return identity
