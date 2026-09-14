"""Private staging and atomic publication for the two M4B tools — v0.6.4 Phase 9.

The minimum shared-safe pattern the M4B Maker's engine proved at Phase 4,
extracted so the Metadata Editor's engine uses the very same code rather than
a second copy. It is **not** a processing engine: it knows nothing about
FFmpeg, tags, covers or actions. It answers three bounded questions about one
planned output — make its private staging directory, publish its staged file
onto its already-planned final path atomically, and remove its staging and
nothing else.

A *staged output* is any frozen plan value carrying ``book_id``, ``filename``,
``staging_dir``, ``staged`` and ``published`` (both M4B ``BookPlan`` types
do). Ownership is proved before anything is touched: the staging directory
must sit **directly** under the operation's work root and the staged file
directly inside it, or the call is refused.

Publication refuses an already-present destination (the planner reserved it;
anything there now is someone else's), moves with ``os.replace`` — or, when the
work root is on another filesystem, copies to a plan-owned temporary sibling in
the destination folder and replaces atomically from there — so the final name
never holds a partial file. Discard removes only the staging directory's own
entries, links unlinked and never followed; the work root itself is pruned
only when empty, with ``rmdir`` alone.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol

from shared import output_paths

__all__ = [
    "StagingError",
    "StagedOutput",
    "require_owned",
    "prepare_staging",
    "discard_staging",
    "publish_staged",
    "prune_work_root",
]


class StagingError(Exception):
    """A staging boundary was violated or a publication failed. Carries the stage."""

    def __init__(self, message: str, *, stage: str = "staging", detail: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.detail = detail


class StagedOutput(Protocol):
    book_id: str
    filename: str
    staging_dir: Path
    staged: Path
    published: Path


def require_owned(plan: StagedOutput, work_root: Path) -> Path:
    """The staging directory must be ``<work_root>/<name>``, exactly, and the
    staged file must be directly inside it."""
    work = Path(work_root)
    if plan.staging_dir.parent != work or plan.staged.parent != plan.staging_dir:
        raise StagingError(
            f"staging {plan.staging_dir} is not directly under the work area {work}",
            stage="staging")
    return work


def prepare_staging(plan: StagedOutput, *, work_root: Path) -> Path:
    """Create the output's private staging directory. Idempotent. Nothing visible."""
    work = require_owned(plan, work_root)
    if plan.staging_dir.exists() or plan.staging_dir.is_symlink():
        output_paths.assert_no_link_in(work, plan.staging_dir)
    plan.staging_dir.mkdir(parents=True, exist_ok=True)
    output_paths.assert_no_link_in(work, plan.staging_dir)
    return plan.staging_dir


def discard_staging(plan: StagedOutput, *, work_root: Path) -> int:
    """Delete the staging area and everything inside it, and nothing else.

    Bounded to that one directory: every entry is re-checked to lie under it,
    links are removed as links and never followed. Returns entries removed.
    """
    require_owned(plan, work_root)
    root = plan.staging_dir
    if not root.exists() and not root.is_symlink():
        return 0
    if root.is_symlink():
        raise StagingError(f"staging {root} is a link and was not touched", stage="staging")
    removed = 0
    for current, directories, files in os.walk(root, topdown=False, followlinks=False):
        current_path = Path(current)
        if current_path != root:
            output_paths.assert_contained(root, current_path)
        for name in files:
            target = current_path / name
            if not target.is_symlink():
                output_paths.assert_contained(root, target)
            os.unlink(target)
            removed += 1
        for name in directories:
            target = current_path / name
            if target.is_symlink():
                os.unlink(target)      # the link itself, never what it points at
            else:
                output_paths.assert_contained(root, target)
                os.rmdir(target)
            removed += 1
    os.rmdir(root)
    return removed + 1


def publish_staged(plan: StagedOutput, *, work_root: Path) -> Path:
    """Make a fully staged output visible, atomically, at its planned path.

    Refuses — before moving anything — unless the staged file is a regular
    file and the published path does not already exist. Moves with
    ``os.replace``; when the work root is on another filesystem, copies to a
    plan-owned temporary sibling in the destination folder and replaces
    atomically from there, so the final name never holds a partial file.
    """
    require_owned(plan, work_root)
    staged, published = plan.staged, plan.published
    if staged.is_symlink() or not staged.is_file():
        raise StagingError(f"{plan.filename} was not staged; nothing was published",
                           stage="publish")
    if published.exists() or published.is_symlink():
        raise StagingError(f"{published} already exists; nothing was published",
                           stage="publish")
    if not published.parent.is_dir():
        raise StagingError(f"the destination folder {published.parent} is not available",
                           stage="publish")
    output_paths.assert_no_link_in(published.parent, published)
    try:
        os.replace(staged, published)
        return published
    except OSError as exc:
        if getattr(exc, "errno", None) not in (getattr(os, "EXDEV", 18), 18):
            raise StagingError(f"publishing {plan.filename} failed: {exc}",
                               stage="publish", detail=repr(exc)) from exc
    # Cross-device: stage a sibling in the destination folder, then replace.
    temporary = None
    try:
        temporary = output_paths.temporary_sibling(published)
        shutil.copyfile(staged, temporary)
        output_paths.atomic_replace(temporary, published)
        temporary = None
        os.unlink(staged)
    except (OSError, output_paths.OutputPathError) as exc:
        if temporary is not None:
            output_paths.discard_temporary(temporary)
        raise StagingError(f"publishing {plan.filename} failed: {exc}",
                           stage="publish", detail=repr(exc)) from exc
    return published


def prune_work_root(work_root: Path) -> None:
    """Remove the work root once nothing is left in it. ``rmdir`` only."""
    work = Path(work_root)
    try:
        if work.is_dir() and not work.is_symlink() and not any(work.iterdir()):
            work.rmdir()
    except OSError:
        pass
