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
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from helpers import repo_files

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
    #: Whether something is at ``path`` in the working tree now, read from the filesystem (never inferred from the Git
    #: status): a staged deletion recreated in the working tree is ``status == "D"`` and ``present`` (R1, C3).
    present: bool | None = None

    def record(self) -> dict:
        row = {"path": self.path, "status": self.status, "sources": list(self.sources)}
        if self.old_path:
            row["old_path"] = self.old_path
        if self.present is not None:
            row["present"] = self.present
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


def matches(path: str, entry: str, *, case_sensitive: bool = True) -> bool:
    """An exact path, or a directory entry (ending in ``/``) at a path-component boundary. A backslash and ``/`` are the
    same separator; with ``case_sensitive=False`` (NTFS, APFS by default) case is folded as the filesystem folds it."""
    path, entry = path.replace("\\", "/"), entry.replace("\\", "/")
    if not case_sensitive:
        path, entry = path.casefold(), entry.casefold()
    if entry.endswith("/"):
        return path.startswith(entry) or path == entry[:-1]
    return path == entry


def local_only_entry(path: str, local_only, *, case_sensitive: bool) -> str | None:
    """The owner-declared local-only entry ``path`` falls under, or None (R1, C2): exact paths and directory components,
    with the filesystem's case rule and either separator, so an alias of a private path is still private."""
    normalized = repo_files.normalize(path) or path
    return next((entry for entry in local_only if matches(normalized, entry, case_sensitive=case_sensitive)), None)


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


def collect(root: Path, *, base: str | None = None, local_only=(), case_sensitive: bool | None = None) -> ChangeSet:
    root = Path(root)
    inventory = repo_files.Inventory(root, case_sensitive=case_sensitive)
    folded = inventory.case_sensitive
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
            entry = local_only_entry(path, local_only, case_sensitive=folded)
            old_entry = local_only_entry(old, local_only, case_sensitive=folded) if old else None
            if source == "untracked" and entry is not None:
                changes.excluded[entry] = changes.excluded.get(entry, 0) + 1
                continue
            if entry is not None or old_entry is not None:
                changes.violations.append(f"a tracked change ({source}) at the local-only path entry "
                                          f"{entry if entry is not None else old_entry!r}: local-only files are never tracked")
                # R1, C2: the public side of a rename into or out of a private path is still a change; the private side is
                # never named. Out of a private path: the public path is new. Into one: the public old path is gone.
                if entry is None:
                    path, letter, old = path, "A", None
                elif old and old_entry is None:
                    path, letter, old = old, "D", None
                else:
                    continue
            row = merged.setdefault(path, {"status": letter, "old": old, "sources": []})
            if letter in ("R", "C") and old:
                row["old"] = row["old"] or old
                row["status"] = letter
            elif row["status"] == "?" and letter != "?":
                row["status"] = letter
            row["sources"].append(source)
    # R1, C2: the index itself, not only today's delta: an already tracked local-only path is a violation (counted by
    # policy entry; the path is never named).
    tracked: dict[str, int] = {}
    for path in _git(root, "ls-files", "-z", "--cached")[1].split("\0"):
        entry = local_only_entry(path, local_only, case_sensitive=folded) if path else None
        if entry is not None:
            tracked[entry] = tracked.get(entry, 0) + 1
    for entry, count in sorted(tracked.items()):
        if any(repr(entry) in violation for violation in changes.violations):
            continue  # already named by the delta above: one violation per entry
        changes.violations.append(f"{count} tracked path(s) in the index at the local-only path entry {entry!r}: local-only "
                                  "files are never tracked")
    changes.changes = [Change(path, row["status"], row["old"], tuple(dict.fromkeys(row["sources"])),
                              present=inventory.exists(path))
                       for path, row in sorted(merged.items())]
    for change in changes.changes:
        if change.status == "D" and change.present:
            changes.notes.append(f"{change.path}: deleted in the index and present again in the working tree; the working "
                                 "file is the candidate and is routed")
    # A staged change the working tree has reversed: still a change; the working bytes are what a run would see.
    worktree = {p for p in _git(root, "diff", "-z", "--name-only", "--no-ext-diff", head)[1].split("\0") if p}
    for change in changes.changes:
        if "staged" in change.sources and change.path not in worktree and change.status != "D" and "untracked" not in change.sources:
            changes.notes.append(f"{change.path}: staged, then reversed in the working tree; the working bytes (HEAD's) run")
    return changes


#: What a plan's candidate identity is and is not (Phase 1A-1 R1, C4). Phase 1A-2 binds an authorization to the actual
#: candidate bytes, policy and scope it admits; this identity is the selection identity it can build on.
IDENTITY_LIMITATION = ("selection identity: the checkout, HEAD, the index entries with their modes, the working bytes (or a "
                       "deletion, link or directory marker) of every relevant changed and untracked path, and the policy digest; "
                       "local-only paths are excluded by policy and never read. Diagnostic: not an authorization identity "
                       "(Phase 1A-2 binds a grant to the candidate bytes, policy and admitted scope)")


def candidate_identity(root: Path, changes: ChangeSet, policy_digest: str, inventory=None) -> dict:
    """The selection identity of the candidate. Problems (a link, an unreadable or unstable file) go into ``changes.problems``
    and make the selection incomplete; they never silently drop a path. Every path is read through the one no-follow
    inventory (helpers/repo_files.py, R1 C1): a link, a path below one or an irregular file is marked and never read."""
    root = Path(root)
    inventory = inventory or repo_files.Inventory(root)
    checkout = os.path.normcase(os.path.realpath(root))
    _, common, _ = _git(root, "rev-parse", "--git-common-dir")
    _, index, _ = _git(root, "ls-files", "-s", "-z")
    working = hashlib.sha256()
    for relative in changes.paths():
        spelled, kind, detail = inventory.canonical(relative)
        if kind == repo_files.INSIDE_LINK:
            marker = "<inside a link>"
            changes.problems.append(f"{relative}: below a link or reparse point ({detail}); not followed")
        elif kind == repo_files.LINK:
            marker = "<link>"
            changes.problems.append(f"{relative}: a link or reparse point; not followed")
        elif kind == repo_files.MISSING:
            marker = "<deleted>"
        elif kind == repo_files.DIRECTORY:
            marker = "<directory>"
            changes.problems.append(f"{relative}: a directory (a nested repository?); its content is not selectable")
        elif kind != repo_files.FILE:
            marker = f"<{kind}>"
            changes.problems.append(f"{relative}: {kind} ({detail}); not read")
        else:
            try:
                marker = hashlib.sha256(inventory.read_bytes(relative)).hexdigest()
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


def selection_identity(root: Path, *, policy_digest: str, local_only=()) -> dict:
    """The candidate identity of any plan, changed or not (R1, C4): the change set against HEAD read the same way a changed
    plan reads it, and its :func:`candidate_identity`. Two candidates with the same porcelain status but different working
    bytes have different identities. Counts only: no path name, so nothing private is recorded."""
    try:
        changes = collect(root, local_only=local_only)
    except ChangeError as exc:
        return {"available": False, "error": str(exc)[:300], "limitation": IDENTITY_LIMITATION}
    identity = candidate_identity(root, changes, policy_digest)
    return {"available": True, **identity, "problems": len(changes.problems), "violations": len(changes.violations),
            "limitation": IDENTITY_LIMITATION}
