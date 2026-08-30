"""Where each imported occurrence's outputs go — decided once, per run.

Phase 7B made the committed ``ImportedFileManager`` snapshot the Converter's only
input authority, and it kept every occurrence's provenance. This module spends
that provenance: it asks ``importing.planning_groups`` how the run divides, hands
each division to the matching Plan 2 planner, and hands the answers back **keyed
by occurrence id**.

**The one shaping problem, and why it is solved this way.** The three shared
planners map one source to one destination: they iterate ``sources`` and call
``rename(source)`` once per element. A split book needs *many* outputs from one
source. Rather than change a shared contract for it, each occurrence is expanded
into one entry per requested filename and the sequence is fed through in order —
so a source that wants four names simply appears four times, and the planner's own
collision numbering separates them exactly as it separates anything else. That
also means a split book's segments land wherever *that occurrence's* provenance
says the book belongs, which is precisely Decision 31A for a directly chosen file
and Decision 7A for a folder-imported one.

**Why ``rename`` re-checks its own source.** Expansion only stays aligned with the
planner's iteration if both walk the same order. Rather than assume that, the
renamer verifies the source it is handed is the one it is about to name, and
refuses the whole plan otherwise. A silent misalignment here would put one book's
chapter names on another book's path.

**Occurrence identity is the point.** Two deliberate duplicates of one file are two
occurrences with one path between them, so nothing may key on the path. The
bucketing below therefore walks ``ImportedFile`` objects and is cross-checked
element by element against ``planning_groups``' own answer, so the two can never
drift apart quietly.

Pure with respect to media and free of Tk: it reads no file, probes nothing, runs
nothing and creates no directory. It plans paths and returns them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from shared.importing import ImportedFile, planning_groups
from shared.output_paths import (
    DestinationPlanner,
    UnsafePathError,
    assert_not_input,
    plan_flat,
    plan_mirrored,
    plan_multi_root,
)


@dataclass(frozen=True, slots=True)
class PlannedOccurrence:
    """One imported occurrence and the destinations its outputs will take.

    ``destinations`` holds one path for a whole-book output and one per segment
    for a split, in the order the names were requested. The occurrence id is
    carried rather than the path because a path is not an identity here.
    """

    occurrence_id: str
    source: Path
    destinations: tuple[Path, ...]

    @property
    def destination(self) -> Path:
        """The single destination, for the whole-book case."""
        if len(self.destinations) != 1:
            raise ValueError(
                f"{self.occurrence_id} has {len(self.destinations)} destinations, not one")
        return self.destinations[0]


def _bucket(entries: Sequence[ImportedFile]):
    """Divide occurrences exactly the way ``planning_groups`` divides paths.

    Deliberately the same rule, applied to the objects rather than to their
    paths, so occurrence identity survives. The caller cross-checks the result
    against the shared function instead of trusting this copy.
    """
    direct: list[ImportedFile] = []
    buckets: dict[str, list[ImportedFile]] = {}
    roots: dict[str, Path] = {}
    order: list[tuple[int, str]] = []

    for entry in entries:
        if entry.mirroring_root is None:
            direct.append(entry)
            continue
        key = entry.source_root.root_id
        if key not in buckets:
            buckets[key] = []
            roots[key] = entry.mirroring_root
            order.append((entry.source_root.order, key))
        buckets[key].append(entry)

    order.sort()
    grouped = [(roots[key], buckets[key]) for _order, key in order]
    return direct, grouped


def _cross_check(direct, grouped, entries: Sequence[ImportedFile]) -> None:
    """Refuse to plan if the local division disagrees with the shared one."""
    groups = planning_groups(tuple(entries))

    if [entry.path for entry in direct] != list(groups.direct):
        raise UnsafePathError(
            "the imported queue could not be divided safely for planning",
            "direct-file grouping disagreed with importing.planning_groups",
        )
    if len(grouped) != len(groups.grouped):
        raise UnsafePathError(
            "the imported queue could not be divided safely for planning",
            f"root count {len(grouped)} disagreed with {len(groups.grouped)}",
        )
    for (root, bucket), (shared_root, shared_sources) in zip(grouped, groups.grouped):
        if Path(root) != Path(shared_root):
            raise UnsafePathError(
                "the imported queue could not be divided safely for planning",
                f"root {root} disagreed with {shared_root}",
            )
        if [entry.path for entry in bucket] != list(shared_sources):
            raise UnsafePathError(
                "the imported queue could not be divided safely for planning",
                f"sources under {root} disagreed with importing.planning_groups",
            )


def _expand(bucket: Sequence[ImportedFile], requested: Mapping[str, Sequence[str]]):
    """One (occurrence, filename) pair per requested output, in queue order."""
    pairs: list[tuple[ImportedFile, str]] = []
    for entry in bucket:
        if entry.occurrence_id not in requested:
            raise ValueError(f"no output names were requested for {entry.occurrence_id}")
        names = tuple(requested[entry.occurrence_id])
        if not names:
            raise ValueError(f"{entry.occurrence_id} requested no output names")
        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"{entry.occurrence_id} requested a blank output name")
            pairs.append((entry, name))
    return pairs


def _renamer(pairs: Sequence[tuple[ImportedFile, str]]):
    """A one-shot namer that walks *pairs* and checks it is still in step."""
    iterator = iter(pairs)

    def rename(source: Path) -> str:
        try:
            entry, name = next(iterator)
        except StopIteration:  # pragma: no cover - defensive
            raise UnsafePathError(
                "output planning ran out of requested names",
                "more sources were planned than names were expanded",
            ) from None
        if Path(entry.path) != Path(source):
            raise UnsafePathError(
                "output planning lost track of which file it was naming",
                f"expected {entry.path}, the planner offered {source}",
            )
        return name

    return rename


def _plan_containers(direct, grouped, run_root: Path,
                     planner: DestinationPlanner) -> dict[str, Path]:
    """One book folder per split occurrence, at that occurrence's own location.

    The folder is planned **through the same three planners the outputs
    themselves use**, with the source's stem standing in for a filename. That is
    the whole trick, and it is what keeps this from becoming a second
    destination authority: ``plan_flat`` puts a directly chosen book's folder in
    the run root, ``plan_mirrored`` puts a folder-imported book's folder under
    its mirrored parent, ``plan_multi_root`` adds the root container first — so
    provenance, containment and the run-wide collision domain are all still
    decided in exactly one place.

    Because the folder is reserved *once per occurrence*, two occurrences that
    would land on the same name are separated here (``Book``, ``Book-1``) and
    every segment of one book then shares one container. Numbering each
    segment's parent independently would scatter a single book across several
    folders, which is the failure this ordering exists to prevent.
    """
    containers: dict[str, Path] = {}

    def absorb(bucket, plan) -> None:
        for entry, item in zip(bucket, plan.items):
            containers[entry.occurrence_id] = item.destination

    def named(bucket):
        """One (entry, folder name) pair per occurrence: the source's stem.

        The stem, not the filename: ``Arazan's Wolves.m4b`` is a book called
        *Arazan's Wolves*, and only the final extension is dropped before the
        shared sanitiser sees it. Not the metadata title either — a Replace run
        would then rename the folder out from under the user, and the file name
        is the identity they already recognise.
        """
        return [(entry, Path(entry.path).stem) for entry in bucket]

    if direct:
        pairs = named(direct)
        absorb(direct, plan_flat(
            run_root, [entry.path for entry, _name in pairs],
            planner=planner, rename=_renamer(pairs)))

    if len(grouped) == 1:
        source_root, bucket = grouped[0]
        pairs = named(bucket)
        absorb(bucket, plan_mirrored(
            run_root, [entry.path for entry, _name in pairs], source_root,
            planner=planner, rename=_renamer(pairs)))
    elif len(grouped) > 1:
        expanded: list[tuple[Path, list[Path]]] = []
        order: list[ImportedFile] = []
        pairs = []
        for source_root, bucket in grouped:
            bucket_pairs = named(bucket)
            expanded.append((source_root, [entry.path for entry, _name in bucket_pairs]))
            pairs.extend(bucket_pairs)
            order.extend(bucket)
        absorb(order, plan_multi_root(
            run_root, expanded, planner=planner, rename=_renamer(pairs)))

    return containers


def plan_outputs(
    entries: Sequence[ImportedFile],
    requested: Mapping[str, Sequence[str]],
    *,
    run_root: Path,
    planner: DestinationPlanner,
    split: bool = False,
) -> tuple[PlannedOccurrence, ...]:
    """Plan every output of one run, in the frozen queue's own order.

    *entries* is the frozen snapshot; *requested* maps each occurrence id to the
    output filenames that occurrence wants — one for a whole book, one per
    segment for a split. Routing follows the approved table: individually chosen
    files go through ``plan_flat`` (31A), a single folder root through
    ``plan_mirrored`` (7A), and several roots through ``plan_multi_root`` (41A).

    **One planner serves the whole run.** It is supplied rather than created here
    so a mixed run's flat and mirrored halves share a single collision domain and
    cannot plan onto the same path.

    Every destination is checked against every source in the run, so no output
    can overwrite a file being read.
    """
    entries = tuple(entries)
    if not entries:
        return ()

    direct, grouped = _bucket(entries)
    _cross_check(direct, grouped, entries)

    planned: dict[str, list[Path]] = {entry.occurrence_id: [] for entry in entries}

    if split:
        # **Phase 16 maintainer supersession of the split half of D3/31A.** A real
        # 12-book split run put 353 chapter MP3s in one flat run folder, from
        # `01 - Chapter 1.mp3` to `01 - Chapter 1-3.mp3`, interleaved by book and
        # separated only by collision suffixes; 53 of the 353 needed a suffix.
        # The maintainer ruled that unusable. Every split occurrence now gets one
        # book folder at its own planned location, and its segments go inside.
        # Whole mode is untouched and still lands beside the run root.
        containers = _plan_containers(direct, grouped, run_root, planner)
        for entry in entries:
            container = containers.get(entry.occurrence_id)
            if container is None:  # pragma: no cover - defensive
                raise UnsafePathError(
                    "a split occurrence was planned no book folder",
                    f"{entry.occurrence_id} has no container",
                )
            subdir = container.relative_to(run_root)
            for name in _expand([entry], requested):
                planned[entry.occurrence_id].append(
                    planner.plan(name[1], subdir=subdir))
        sources = tuple(entry.path for entry in entries)
        for destination in (p for paths in planned.values() for p in paths):
            assert_not_input(destination, sources)
        return tuple(
            PlannedOccurrence(
                occurrence_id=entry.occurrence_id,
                source=entry.path,
                destinations=tuple(planned[entry.occurrence_id]),
            )
            for entry in entries
        )

    def absorb(pairs, plan) -> None:
        if len(plan.items) != len(pairs):
            raise UnsafePathError(
                "output planning returned a different number of destinations",
                f"{len(plan.items)} planned for {len(pairs)} requested outputs",
            )
        for (entry, _name), item in zip(pairs, plan.items):
            planned[entry.occurrence_id].append(item.destination)

    if direct:
        pairs = _expand(direct, requested)
        absorb(pairs, plan_flat(
            run_root, [entry.path for entry, _name in pairs],
            planner=planner, rename=_renamer(pairs)))

    if len(grouped) == 1:
        source_root, bucket = grouped[0]
        pairs = _expand(bucket, requested)
        absorb(pairs, plan_mirrored(
            run_root, [entry.path for entry, _name in pairs], source_root,
            planner=planner, rename=_renamer(pairs)))
    elif len(grouped) > 1:
        expanded: list[tuple[Path, list[Path]]] = []
        pairs = []
        for source_root, bucket in grouped:
            bucket_pairs = _expand(bucket, requested)
            expanded.append((source_root, [entry.path for entry, _name in bucket_pairs]))
            pairs.extend(bucket_pairs)
        absorb(pairs, plan_multi_root(
            run_root, expanded, planner=planner, rename=_renamer(pairs)))

    sources = tuple(entry.path for entry in entries)
    for destination in (path for paths in planned.values() for path in paths):
        assert_not_input(destination, sources)

    return tuple(
        PlannedOccurrence(
            occurrence_id=entry.occurrence_id,
            source=entry.path,
            destinations=tuple(planned[entry.occurrence_id]),
        )
        for entry in entries
    )
