"""v0.8.2 Checkpoint 3: the shared collision search resumes where it stopped, and names nothing differently.

``DestinationPlanner.plan`` and ``plan_directory`` used to restart every search at the first suffix, so k outputs
sharing one name cost k(k+1)/2 candidate paths (2,341 identical TTS titles: 23.8 s, twice over, because
``output_names.plan_named`` runs a folder-finding pass first). The planner now remembers, per collision sequence, where
its last search ended; every index before that point was found taken or occupied during this planning operation.

Three kinds of evidence that the names are unchanged:

* ``GOLDEN``: every planned name of the scenarios below, captured from the ``4465b94`` planner before the change;
* ``ReferencePlanner``: that allocator, verbatim, run side by side with the real one on the same calls, including a
  seeded random mix of names, case and Unicode spellings, sub-folders, files and folders, start indices, existing
  files and an exhausted search;
* counted work: the number of candidate paths each pass tries, which is quadratic on ``4465b94`` and linear now.

Synthetic names in ``tmp_path`` only; nothing here builds Tk or reads a real library.
"""

from __future__ import annotations

import os
import random
import unicodedata
from pathlib import Path, PurePath

import pytest

from shared import output_paths as op
from tts import output_names as on

STEFFAN = "Edge Male - Steffan (en-US)"
#: Windows without long paths, as the panel would plan on such a machine.
SHORT = on.NameBudget(path_limit=on.WINDOWS_PATH_LIMIT, directory_limit=on.WINDOWS_DIRECTORY_LIMIT, windows=True)
ROOMY = on.NameBudget(path_limit=None, directory_limit=None, windows=True)


# --------------------------------------------------------------------------- #
# The 4465b94 allocator, verbatim (the oracle)
# --------------------------------------------------------------------------- #


class ReferencePlanner(op.DestinationPlanner):
    """``DestinationPlanner.plan`` / ``plan_directory`` exactly as they were at ``4465b94``: each search restarts.

    Shares ``_is_free``, ``_key`` and ``_taken`` with the real class, so the two differ only in where a search starts.
    """

    def plan(self, name, *, subdir=None, start_index=0):
        safe_name = op.sanitize_component(name)
        directory = self.root
        if subdir is not None:
            relative = op.sanitize_relative(subdir)
            if relative.parts:
                directory = self.root / relative
        op.assert_contained(self.root, directory / safe_name)

        if start_index <= 0:
            candidate = directory / safe_name
            if self._is_free(candidate):
                self._taken.add(self._key(candidate))
                return candidate

        for index in range(max(1, start_index), op.MAX_COLLISION_ATTEMPTS + 1):
            candidate = directory / op.numbered_variant(safe_name, index)
            if self._is_free(candidate):
                self._taken.add(self._key(candidate))
                return candidate

        raise op.ReservationError(
            f"no free name could be found for {safe_name!r} after "
            f"{op.MAX_COLLISION_ATTEMPTS} attempts",
            f"directory={directory}",
        )

    def plan_directory(self, name, *, subdir=None):
        safe_name = op.sanitize_component(name)
        directory = self.root
        if subdir is not None:
            relative = op.sanitize_relative(subdir)
            if relative.parts:
                directory = self.root / relative
        op.assert_contained(self.root, directory / safe_name)

        candidate = directory / safe_name
        if self._is_free(candidate):
            self._taken.add(self._key(candidate))
            return candidate
        for index in range(1, op.MAX_COLLISION_ATTEMPTS + 1):
            candidate = directory / f"{safe_name}-{index}"
            if self._is_free(candidate):
                self._taken.add(self._key(candidate))
                return candidate
        raise op.ReservationError(
            f"no free folder name could be found for {safe_name!r} after "
            f"{op.MAX_COLLISION_ATTEMPTS} attempts",
            f"directory={directory}",
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def rel(path: Path, root: Path) -> str:
    return PurePath(Path(path).relative_to(root)).as_posix()


def outcome(call, root: Path) -> str:
    """One planned name relative to *root*, or the refusal it raised."""
    try:
        return rel(call(), root)
    except op.OutputPathError as exc:
        return f"!{type(exc).__name__}: {exc.message}"


class bounded:
    """Temporarily lower ``MAX_COLLISION_ATTEMPTS`` (restored on exit), as the existing bound test does."""

    def __init__(self, limit: int):
        self.limit = limit

    def __enter__(self):
        self.saved = op.MAX_COLLISION_ATTEMPTS
        op.MAX_COLLISION_ATTEMPTS = self.limit

    def __exit__(self, *exc):
        op.MAX_COLLISION_ATTEMPTS = self.saved


def source_tree(root: Path) -> Path:
    """The same file names in several folders, a PDF and a TXT sharing a stem, case and Unicode spellings."""
    src = root / "src"
    for folder in ("A", "B", "B/Deep", "C"):
        for name in ("Chapter.txt", "Chapter.pdf", "Intro.txt"):
            touch(src / "Library" / folder / name)
    touch(src / "Library" / "Café.txt")
    touch(src / "Library" / "D" / "Café.pdf")
    touch(src / "Other" / "Library" / "Chapter.txt")
    touch(src / "Other" / "Library" / "x" / "Chapter.txt")
    return src


def tree_files(src: Path, sub: str) -> list[Path]:
    """Every file under one root in a fixed order (the planners keep the given order; they never sort)."""
    return sorted((p for p in (src / sub).rglob("*") if p.is_file()), key=lambda p: p.as_posix())


# --------------------------------------------------------------------------- #
# Scenarios: each returns every planned name in order (or the refusal). Planned under ``<tmp>/run``.
# --------------------------------------------------------------------------- #


def s_single(root):
    planner = op.DestinationPlanner(root)
    return [outcome(lambda: planner.plan("Book.m4b"), root)]


def s_identical(root):
    planner = op.DestinationPlanner(root)
    return [outcome(lambda: planner.plan("Book.m4b"), root) for _ in range(60)]


def s_existing_numbered(root):
    for name in ("Book.m4b", "Book-1.m4b", "Book-2.m4b", "Book-3.m4b"):
        touch(root / name)
    planner = op.DestinationPlanner(root)
    return [outcome(lambda: planner.plan("Book.m4b"), root) for _ in range(4)]


def s_noncontiguous(root):
    for name in ("Book-2.m4b", "Book-5.m4b", "BOOK-6.M4B"):
        touch(root / name)
    (root / "Book-8.m4b").mkdir()
    planner = op.DestinationPlanner(root)
    return [outcome(lambda: planner.plan("Book.m4b"), root) for _ in range(8)]


def s_case_only(root):
    planner = op.DestinationPlanner(root)
    names = ("Book.m4b", "BOOK.M4B", "book.m4b", "Book.M4B", "BOOK.m4b") * 3
    return [outcome(lambda n=n: planner.plan(n), root) for n in names]


def s_unicode(root):
    touch(root / "Café-1.m4b")
    planner = op.DestinationPlanner(root)
    names = ("Café.m4b", "Café.m4b", "CAFÉ.m4b", "café.M4B", "Straße.m4b", "STRASSE.m4b",
             "strasse.m4b") * 3
    return [outcome(lambda n=n: planner.plan(n), root) for n in names]


def s_already_numbered(root):
    planner = op.DestinationPlanner(root)
    names = ("Book-1.m4b", "Book.m4b", "Book.m4b", "Book.m4b", "Book-2.m4b", "Book.m4b", "Book-1.m4b",
             "Book-1.m4b", "Book-1-1.m4b", "Book-1.m4b")
    return [outcome(lambda n=n: planner.plan(n), root) for n in names]


def s_suffix_families(root):
    planner = op.DestinationPlanner(root)
    names = ("Book.m4b", "Book.m4b", "Book-2.m4b", "Book.m4b", "Book.m4b", "Book-5.m4b", "Book.m4b",
             "Book.m4b", "Book.mp3", "Book", "Book", "Book-3", "Book.m4b")
    return [outcome(lambda n=n: planner.plan(n), root) for n in names]


def s_subdirs(root):
    planner = op.DestinationPlanner(root)
    calls = [("ch.mp3", "A")] * 3 + [("ch.mp3", "a")] * 2 + [("ch.mp3", "B")] * 2 + [("ch.mp3", None)] * 2 + \
            [("ch.mp3", "A/x")] * 2 + [("CH.MP3", "A")] + [("ch.mp3", "A")]
    return [outcome(lambda n=n, s=s: planner.plan(n, subdir=s), root) for n, s in calls]


def s_files_and_folders(root):
    (root / "Dune").mkdir()
    touch(root / "Dune-1")
    touch(root / "Saga-2")
    planner = op.DestinationPlanner(root)
    calls = [("d", "Book"), ("d", "Book"), ("f", "Book"), ("f", "Book"), ("d", "Book"), ("f", "Book.m4b"),
             ("d", "Book.m4b"), ("d", "Book.m4b"), ("f", "Book.m4b"), ("d", "Dune"), ("d", "Dune"), ("f", "Dune"),
             ("f", "Dune"), ("d", "Saga"), ("d", "Saga"), ("d", "Saga"), ("f", "Saga"), ("d", "Book-1")]

    def one(kind, name):
        return planner.plan_directory(name) if kind == "d" else planner.plan(name)

    return [outcome(lambda k=k, n=n: one(k, n), root) for k, n in calls]


def s_start_indices(root):
    touch(root / "Book-3.m4b")
    planner = op.DestinationPlanner(root)
    starts = (1, 1, 0, 0, 3, 3, 0, 1, 5, 0, 7, 2, 0, 1)
    return [outcome(lambda s=s: planner.plan("Book.m4b", start_index=s), root) for s in starts]


def s_high_start_first(root):
    planner = op.DestinationPlanner(root)
    starts = (4, 4, 0, 0, 0, 0, 0, 1, 1, 4, 2, 0)
    return [outcome(lambda s=s: planner.plan("Book.m4b", start_index=s), root) for s in starts]


def s_exhaustion(root):
    out = []
    with bounded(3):
        planner = op.DestinationPlanner(root)
        out += [outcome(lambda: planner.plan("Book.m4b"), root) for _ in range(5)]
        out.append(outcome(lambda: planner.plan("Other.m4b"), root))
        out.append(outcome(lambda: planner.plan("Book.m4b"), root))
        out.append(outcome(lambda: planner.plan("Book.m4b", start_index=1), root))
        out.append(outcome(lambda: planner.plan("Book-3.m4b"), root))
        out += [outcome(lambda: planner.plan_directory("Dir"), root) for _ in range(5)]
        out.append(outcome(lambda: planner.plan("Dir"), root))
    return out


def s_flat_mirrored_multi(root):
    src = source_tree(root.parent)
    planner = op.DestinationPlanner(root)
    flat = op.plan_flat(root, tree_files(src, "Library"), planner=planner)
    mirrored = op.plan_mirrored(root, tree_files(src, "Library"), src / "Library", planner=planner)
    multi = op.plan_multi_root(root, [(src / "Library", tree_files(src, "Library")),
                                      (src / "Other" / "Library", tree_files(src, "Other/Library"))],
                               planner=planner, rename=lambda p: p.stem + ".m4b")
    return [rel(item.destination, root) for plan in (flat, mirrored, multi) for item in plan.items]


def s_source_side(root):
    folder = root / "covers"
    for name in ("cover.jpg", "cover-1.jpg", "cover-3.jpg", "art.png", "ART-1.png"):
        touch(folder / name)
    touch(root / "elsewhere" / "cover.jpg")
    side = op.SourceSidePlanner()
    calls = [folder / "cover.jpg"] * 4 + [folder / "art.png"] * 2 + [root / "elsewhere" / "cover.jpg"] * 2 + \
            [folder / "cover.jpg"]
    return [rel(side.plan_beside(path), root) for path in calls] + [rel(side.plan_beside(folder / "art.png",
                                                                                         name="art.jpg"), root)]


def tts_plans(root, budget):
    """The three TTS routes through ``output_names.plan_named``, sharing one planner, as ``plan_destinations`` does."""
    src = source_tree(root.parent)
    touch(root / "B" / f"Chapter-{STEFFAN}.mp3")              # occupies a mirrored name
    touch(root / "Library" / "B" / f"Chapter-{STEFFAN}-1.mp3")  # and a numbered multi-root one
    touch(root / f"Chapter-{STEFFAN}-1.mp3")                    # and a numbered flat one
    planner = op.DestinationPlanner(root)
    named = {"label": STEFFAN, "planner": planner, "budget": budget}
    flat = on.plan_named(op.plan_flat, root, tree_files(src, "Library"), **named)
    mirrored = on.plan_named(op.plan_mirrored, root, tree_files(src, "Library"), src / "Library", **named)
    multi = on.plan_named(op.plan_multi_root, root, [(src / "Library", tree_files(src, "Library")),
                                                     (src / "Other" / "Library", tree_files(src, "Other/Library"))],
                          **named)
    return [rel(item.destination, root) for plan in (flat, mirrored, multi) for item in plan.items]


def s_tts_routes(root):
    return tts_plans(root, ROOMY)


def s_tts_shortened_onto_one_name(root):
    """Long stems shortened by a tight budget until they collide: identical names inside one mirrored folder."""
    long = "Shared Title Prefix " * 6
    src = root.parent / "longsrc"
    sources = [touch(src / f"{long}{i:03d}.txt") for i in range(25)]
    budget = on.NameBudget(path_limit=len(str(root)) + 70, directory_limit=len(str(root)) + 40, windows=True)
    planner = op.DestinationPlanner(root)
    plan = on.plan_named(op.plan_mirrored, root, sources, src, label=STEFFAN, planner=planner, budget=budget)
    # The budget is relative to the run folder's own length, so the shortened stem is the same on every machine.
    return [rel(item.destination, root) for item in plan.items]


SCENARIOS = {
    "single": s_single,
    "identical": s_identical,
    "existing_numbered": s_existing_numbered,
    "noncontiguous": s_noncontiguous,
    "case_only": s_case_only,
    "unicode": s_unicode,
    "already_numbered": s_already_numbered,
    "suffix_families": s_suffix_families,
    "subdirs": s_subdirs,
    "files_and_folders": s_files_and_folders,
    "start_indices": s_start_indices,
    "high_start_first": s_high_start_first,
    "exhaustion": s_exhaustion,
    "flat_mirrored_multi": s_flat_mirrored_multi,
    "source_side": s_source_side,
    "tts_routes": s_tts_routes,
    "tts_shortened_onto_one_name": s_tts_shortened_onto_one_name,
}

#: Captured from the 4465b94 planner (``files/dev-work/v0.8.2-cp3-evidence/golden_cp3.py baseline``) before the change.
GOLDEN: dict[str, list[str]] = {
    "already_numbered": [
        "Book-1.m4b",
        "Book.m4b",
        "Book-2.m4b",
        "Book-3.m4b",
        "Book-2-1.m4b",
        "Book-4.m4b",
        "Book-1-1.m4b",
        "Book-1-2.m4b",
        "Book-1-1-1.m4b",
        "Book-1-3.m4b"
    ],
    "case_only": [
        "Book.m4b",
        "BOOK-1.M4B",
        "book-2.m4b",
        "Book-3.M4B",
        "BOOK-4.m4b",
        "Book-5.m4b",
        "BOOK-6.M4B",
        "book-7.m4b",
        "Book-8.M4B",
        "BOOK-9.m4b",
        "Book-10.m4b",
        "BOOK-11.M4B",
        "book-12.m4b",
        "Book-13.M4B",
        "BOOK-14.m4b"
    ],
    "exhaustion": [
        "Book.m4b",
        "Book-1.m4b",
        "Book-2.m4b",
        "Book-3.m4b",
        "!ReservationError: no free name could be found for 'Book.m4b' after 3 attempts",
        "Other.m4b",
        "!ReservationError: no free name could be found for 'Book.m4b' after 3 attempts",
        "!ReservationError: no free name could be found for 'Book.m4b' after 3 attempts",
        "Book-3-1.m4b",
        "Dir",
        "Dir-1",
        "Dir-2",
        "Dir-3",
        "!ReservationError: no free folder name could be found for 'Dir' after 3 attempts",
        "!ReservationError: no free name could be found for 'Dir' after 3 attempts"
    ],
    "existing_numbered": [
        "Book-4.m4b",
        "Book-5.m4b",
        "Book-6.m4b",
        "Book-7.m4b"
    ],
    "files_and_folders": [
        "Book",
        "Book-1",
        "Book-2",
        "Book-3",
        "Book-4",
        "Book.m4b",
        "Book.m4b-1",
        "Book.m4b-2",
        "Book-1.m4b",
        "Dune-2",
        "Dune-3",
        "Dune-4",
        "Dune-5",
        "Saga",
        "Saga-1",
        "Saga-3",
        "Saga-4",
        "Book-1-1"
    ],
    "flat_mirrored_multi": [
        "Chapter.pdf",
        "Chapter.txt",
        "Intro.txt",
        "Chapter-1.pdf",
        "Chapter-1.txt",
        "Chapter-2.pdf",
        "Chapter-2.txt",
        "Intro-1.txt",
        "Intro-2.txt",
        "Chapter-3.pdf",
        "Chapter-3.txt",
        "Intro-3.txt",
        "Caf\u00e9.txt",
        "Caf\u00e9.pdf",
        "A/Chapter.pdf",
        "A/Chapter.txt",
        "A/Intro.txt",
        "B/Chapter.pdf",
        "B/Chapter.txt",
        "B/Deep/Chapter.pdf",
        "B/Deep/Chapter.txt",
        "B/Deep/Intro.txt",
        "B/Intro.txt",
        "C/Chapter.pdf",
        "C/Chapter.txt",
        "C/Intro.txt",
        "Caf\u00e9-1.txt",
        "D/Caf\u00e9.pdf",
        "Library/A/Chapter.m4b",
        "Library/A/Chapter-1.m4b",
        "Library/A/Intro.m4b",
        "Library/B/Chapter.m4b",
        "Library/B/Chapter-1.m4b",
        "Library/B/Deep/Chapter.m4b",
        "Library/B/Deep/Chapter-1.m4b",
        "Library/B/Deep/Intro.m4b",
        "Library/B/Intro.m4b",
        "Library/C/Chapter.m4b",
        "Library/C/Chapter-1.m4b",
        "Library/C/Intro.m4b",
        "Library/Caf\u00e9.m4b",
        "Library/D/Caf\u00e9.m4b",
        "Library-1/Chapter.m4b",
        "Library-1/x/Chapter.m4b"
    ],
    "high_start_first": [
        "Book-4.m4b",
        "Book-5.m4b",
        "Book.m4b",
        "Book-1.m4b",
        "Book-2.m4b",
        "Book-3.m4b",
        "Book-6.m4b",
        "Book-7.m4b",
        "Book-8.m4b",
        "Book-9.m4b",
        "Book-10.m4b",
        "Book-11.m4b"
    ],
    "identical": [
        "Book.m4b",
        "Book-1.m4b",
        "Book-2.m4b",
        "Book-3.m4b",
        "Book-4.m4b",
        "Book-5.m4b",
        "Book-6.m4b",
        "Book-7.m4b",
        "Book-8.m4b",
        "Book-9.m4b",
        "Book-10.m4b",
        "Book-11.m4b",
        "Book-12.m4b",
        "Book-13.m4b",
        "Book-14.m4b",
        "Book-15.m4b",
        "Book-16.m4b",
        "Book-17.m4b",
        "Book-18.m4b",
        "Book-19.m4b",
        "Book-20.m4b",
        "Book-21.m4b",
        "Book-22.m4b",
        "Book-23.m4b",
        "Book-24.m4b",
        "Book-25.m4b",
        "Book-26.m4b",
        "Book-27.m4b",
        "Book-28.m4b",
        "Book-29.m4b",
        "Book-30.m4b",
        "Book-31.m4b",
        "Book-32.m4b",
        "Book-33.m4b",
        "Book-34.m4b",
        "Book-35.m4b",
        "Book-36.m4b",
        "Book-37.m4b",
        "Book-38.m4b",
        "Book-39.m4b",
        "Book-40.m4b",
        "Book-41.m4b",
        "Book-42.m4b",
        "Book-43.m4b",
        "Book-44.m4b",
        "Book-45.m4b",
        "Book-46.m4b",
        "Book-47.m4b",
        "Book-48.m4b",
        "Book-49.m4b",
        "Book-50.m4b",
        "Book-51.m4b",
        "Book-52.m4b",
        "Book-53.m4b",
        "Book-54.m4b",
        "Book-55.m4b",
        "Book-56.m4b",
        "Book-57.m4b",
        "Book-58.m4b",
        "Book-59.m4b"
    ],
    "noncontiguous": [
        "Book.m4b",
        "Book-1.m4b",
        "Book-3.m4b",
        "Book-4.m4b",
        "Book-7.m4b",
        "Book-9.m4b",
        "Book-10.m4b",
        "Book-11.m4b"
    ],
    "single": [
        "Book.m4b"
    ],
    "source_side": [
        "covers/cover-2.jpg",
        "covers/cover-4.jpg",
        "covers/cover-5.jpg",
        "covers/cover-6.jpg",
        "covers/art-2.png",
        "covers/art-3.png",
        "elsewhere/cover-1.jpg",
        "elsewhere/cover-2.jpg",
        "covers/cover-7.jpg",
        "covers/art-1.jpg"
    ],
    "start_indices": [
        "Book-1.m4b",
        "Book-2.m4b",
        "Book.m4b",
        "Book-4.m4b",
        "Book-5.m4b",
        "Book-6.m4b",
        "Book-7.m4b",
        "Book-8.m4b",
        "Book-9.m4b",
        "Book-10.m4b",
        "Book-11.m4b",
        "Book-12.m4b",
        "Book-13.m4b",
        "Book-14.m4b"
    ],
    "subdirs": [
        "A/ch.mp3",
        "A/ch-1.mp3",
        "A/ch-2.mp3",
        "a/ch-3.mp3",
        "a/ch-4.mp3",
        "B/ch.mp3",
        "B/ch-1.mp3",
        "ch.mp3",
        "ch-1.mp3",
        "A/x/ch.mp3",
        "A/x/ch-1.mp3",
        "A/CH-5.MP3",
        "A/ch-6.mp3"
    ],
    "suffix_families": [
        "Book.m4b",
        "Book-1.m4b",
        "Book-2.m4b",
        "Book-3.m4b",
        "Book-4.m4b",
        "Book-5.m4b",
        "Book-6.m4b",
        "Book-7.m4b",
        "Book.mp3",
        "Book",
        "Book-1",
        "Book-3",
        "Book-8.m4b"
    ],
    "tts_routes": [
        "Chapter-Edge Male - Steffan (en-US).mp3",
        "Chapter-Edge Male - Steffan (en-US)-2.mp3",
        "Intro-Edge Male - Steffan (en-US).mp3",
        "Chapter-Edge Male - Steffan (en-US)-3.mp3",
        "Chapter-Edge Male - Steffan (en-US)-4.mp3",
        "Chapter-Edge Male - Steffan (en-US)-5.mp3",
        "Chapter-Edge Male - Steffan (en-US)-6.mp3",
        "Intro-Edge Male - Steffan (en-US)-1.mp3",
        "Intro-Edge Male - Steffan (en-US)-2.mp3",
        "Chapter-Edge Male - Steffan (en-US)-7.mp3",
        "Chapter-Edge Male - Steffan (en-US)-8.mp3",
        "Intro-Edge Male - Steffan (en-US)-3.mp3",
        "Caf\u00e9-Edge Male - Steffan (en-US).mp3",
        "Caf\u00e9-Edge Male - Steffan (en-US)-1.mp3",
        "A/Chapter-Edge Male - Steffan (en-US).mp3",
        "A/Chapter-Edge Male - Steffan (en-US)-1.mp3",
        "A/Intro-Edge Male - Steffan (en-US).mp3",
        "B/Chapter-Edge Male - Steffan (en-US)-1.mp3",
        "B/Chapter-Edge Male - Steffan (en-US)-2.mp3",
        "B/Deep/Chapter-Edge Male - Steffan (en-US).mp3",
        "B/Deep/Chapter-Edge Male - Steffan (en-US)-1.mp3",
        "B/Deep/Intro-Edge Male - Steffan (en-US).mp3",
        "B/Intro-Edge Male - Steffan (en-US).mp3",
        "C/Chapter-Edge Male - Steffan (en-US).mp3",
        "C/Chapter-Edge Male - Steffan (en-US)-1.mp3",
        "C/Intro-Edge Male - Steffan (en-US).mp3",
        "Caf\u00e9-Edge Male - Steffan (en-US)-2.mp3",
        "D/Caf\u00e9-Edge Male - Steffan (en-US).mp3",
        "Library/A/Chapter-Edge Male - Steffan (en-US).mp3",
        "Library/A/Chapter-Edge Male - Steffan (en-US)-1.mp3",
        "Library/A/Intro-Edge Male - Steffan (en-US).mp3",
        "Library/B/Chapter-Edge Male - Steffan (en-US).mp3",
        "Library/B/Chapter-Edge Male - Steffan (en-US)-2.mp3",
        "Library/B/Deep/Chapter-Edge Male - Steffan (en-US).mp3",
        "Library/B/Deep/Chapter-Edge Male - Steffan (en-US)-1.mp3",
        "Library/B/Deep/Intro-Edge Male - Steffan (en-US).mp3",
        "Library/B/Intro-Edge Male - Steffan (en-US).mp3",
        "Library/C/Chapter-Edge Male - Steffan (en-US).mp3",
        "Library/C/Chapter-Edge Male - Steffan (en-US)-1.mp3",
        "Library/C/Intro-Edge Male - Steffan (en-US).mp3",
        "Library/Caf\u00e9-Edge Male - Steffan (en-US).mp3",
        "Library/D/Caf\u00e9-Edge Male - Steffan (en-US).mp3",
        "Library-1/Chapter-Edge Male - Steffan (en-US).mp3",
        "Library-1/x/Chapter-Edge Male - Steffan (en-US).mp3"
    ],
    "tts_shortened_onto_one_name": [
        "Shared Title Pref-Edge Male - Steffan (en-US).mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-1.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-2.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-3.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-4.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-5.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-6.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-7.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-8.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-9.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-10.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-11.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-12.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-13.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-14.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-15.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-16.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-17.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-18.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-19.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-20.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-21.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-22.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-23.mp3",
        "Shared Title Pref-Edge Male - Steffan (en-US)-24.mp3"
    ],
    "unicode": [
        "Caf\u00e9.m4b",
        "Caf\u00e9-2.m4b",
        "CAF\u00c9-3.m4b",
        "caf\u00e9-4.M4B",
        "Stra\u00dfe.m4b",
        "STRASSE-1.m4b",
        "strasse-2.m4b",
        "Caf\u00e9-5.m4b",
        "Caf\u00e9-6.m4b",
        "CAF\u00c9-7.m4b",
        "caf\u00e9-8.M4B",
        "Stra\u00dfe-3.m4b",
        "STRASSE-4.m4b",
        "strasse-5.m4b",
        "Caf\u00e9-9.m4b",
        "Caf\u00e9-10.m4b",
        "CAF\u00c9-11.m4b",
        "caf\u00e9-12.M4B",
        "Stra\u00dfe-6.m4b",
        "STRASSE-7.m4b",
        "strasse-8.m4b"
    ]
}


def run_scenario(name: str, tmp_path: Path) -> list[str]:
    root = tmp_path / "run"
    root.mkdir(parents=True)
    return SCENARIOS[name](root)


# --------------------------------------------------------------------------- #
# 1. The names are the names 4465b94 planned
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_plans_exactly_the_names_the_previous_planner_did(name, tmp_path):
    assert run_scenario(name, tmp_path) == GOLDEN[name]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_matches_the_restarting_reference_run_beside_it(name, tmp_path, monkeypatch):
    real = run_scenario(name, tmp_path / "real")
    monkeypatch.setattr(op, "DestinationPlanner", ReferencePlanner)
    assert run_scenario(name, tmp_path / "reference") == real


def test_planning_creates_no_file_and_no_folder(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    planner = op.DestinationPlanner(root)
    for index in range(200):
        planner.plan("Book.m4b", subdir="Sub" if index % 2 else None)
        planner.plan_directory("Book")
    assert list(root.iterdir()) == []
    assert planner.planned_count == 400


# --------------------------------------------------------------------------- #
# 2. Seeded random calls: one collision family never moves another's names
# --------------------------------------------------------------------------- #

VOCABULARY = ("Book.m4b", "BOOK.M4B", "Book-1.m4b", "Book-2.m4b", "Book-1-1.m4b", "Book", "book", "Book-1",
              "Café.mp3", "Café.mp3", "CAFÉ-1.mp3", "Straße.mp3", "STRASSE.mp3", "a<b>.mp3",
              "a_b_.mp3", "x.tar.gz", "x.tar-1.gz", "CON.mp3", ".hidden", "trail. ")
SUBDIRS = (None, None, "A", "a", "B/Deep", "b/deep")


def random_calls(seed: int, count: int):
    rng = random.Random(seed)
    for _ in range(count):
        kind = rng.choice("ffffd")
        name, subdir = rng.choice(VOCABULARY), rng.choice(SUBDIRS)
        start = rng.choice((0, 0, 0, 1, 1, 2, 3, 6)) if kind == "f" else 0
        yield kind, name, subdir, start


def run_calls(planner, calls, root):
    out = []
    for kind, name, subdir, start in calls:
        if kind == "d":
            out.append(outcome(lambda: planner.plan_directory(name, subdir=subdir), root))
        else:
            out.append(outcome(lambda: planner.plan(name, subdir=subdir, start_index=start), root))
    return out


def occupy(root: Path, seed: int) -> None:
    rng = random.Random(seed + 10_000)
    for _ in range(12):
        name = op.sanitize_component(rng.choice(VOCABULARY))
        index = rng.choice((0, 1, 2, 3, 5))
        if index:
            name = op.numbered_variant(name, index) if rng.random() < 0.7 else f"{name}-{index}"
        folder = root / rng.choice(("", "A", "B/Deep"))
        if rng.random() < 0.3:
            if not (folder / name).exists():
                (folder / name).mkdir(parents=True)
        elif not (folder / name).exists():
            touch(folder / name)


@pytest.mark.parametrize("seed", range(12))
def test_random_call_sequences_match_the_reference_call_for_call(seed, tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    occupy(root, seed)
    calls = list(random_calls(seed, 400))
    with bounded(6):  # small enough that some families run out, and the refusal is compared too
        real = run_calls(op.DestinationPlanner(root), calls, root)
        reference = run_calls(ReferencePlanner(root), calls, root)
    assert real == reference
    assert any(entry.startswith("!ReservationError") for entry in real), "the bound was reached in this sequence"
    assert len({entry.casefold() for entry in real if not entry.startswith("!")}) == \
        sum(1 for entry in real if not entry.startswith("!")), "every planned name is distinct, case-insensitively"


def test_planners_are_independent_and_remember_nothing_between_operations(tmp_path):
    root = tmp_path / "run"
    first = op.DestinationPlanner(root, check_filesystem=False)
    assert [first.plan("Book.m4b").name for _ in range(3)] == ["Book.m4b", "Book-1.m4b", "Book-2.m4b"]
    second = op.DestinationPlanner(root, check_filesystem=False)
    assert second.plan("Book.m4b").name == "Book.m4b", "a new planner starts from nothing"
    assert first.plan("Book.m4b").name == "Book-3.m4b", "and the first one is not disturbed by it"
    assert not hasattr(op.DestinationPlanner, "_resume"), "no class-level (shared) search state"


def test_a_search_interrupted_by_an_error_resumes_exactly_as_the_reference(tmp_path, monkeypatch):
    """A filesystem check that fails mid-search raises before anything is remembered; the next call still agrees."""
    root = tmp_path / "run"
    root.mkdir()
    real_is_free = op.DestinationPlanner._is_free

    def flaky(planner, candidate):
        if candidate.name == "Book-4.m4b" and not getattr(planner, "_failed_once", False):
            planner._failed_once = True
            raise PermissionError("simulated")
        return real_is_free(planner, candidate)

    monkeypatch.setattr(op.DestinationPlanner, "_is_free", flaky)
    results = []
    for cls in (op.DestinationPlanner, ReferencePlanner):
        planner = cls(root)
        names = []
        for _ in range(8):
            try:
                names.append(planner.plan("Book.m4b").name)
            except PermissionError:
                names.append("!PermissionError")
        results.append(names)
    assert results[0] == results[1]
    assert results[0][4] == "!PermissionError" and results[0][5] == "Book-4.m4b"


def test_a_name_occupied_on_disk_is_never_planned_and_a_new_occupant_is_seen(tmp_path):
    """Disk checks stay fresh for every name not yet tried; a file appearing during planning is still avoided."""
    root = tmp_path / "run"
    root.mkdir()
    touch(root / "Book-1.m4b")
    planner = op.DestinationPlanner(root)
    assert planner.plan("Book.m4b").name == "Book.m4b"
    assert planner.plan("Book.m4b").name == "Book-2.m4b"
    touch(root / "Book-3.m4b")          # appears between two calls
    touch(root / "BOOK-4.M4B")
    assert planner.plan("Book.m4b").name == "Book-5.m4b"


def test_a_broken_link_or_a_dangling_junction_name_is_planned_as_the_reference_plans_it(tmp_path):
    """Whatever the existing check decides for a dangling link, the resumed search decides the same (no change)."""
    root = tmp_path / "run"
    target = tmp_path / "gone"
    target.mkdir()
    root.mkdir()
    made = []
    try:
        (root / "Book-1.m4b").symlink_to(tmp_path / "missing.m4b")
        made.append("file symlink")
    except OSError:
        pass
    if os.name == "nt":
        import subprocess

        subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "Book-2.m4b"), str(target)],
                       capture_output=True, timeout=30)
        if os.path.lexists(root / "Book-2.m4b"):
            made.append("junction")
    else:
        (root / "Book-2.m4b").symlink_to(target, target_is_directory=True)
        made.append("directory symlink")
    target.rmdir()
    if not made:
        pytest.skip("this environment can create neither a file symlink nor a junction")
    planner, reference = op.DestinationPlanner(root), ReferencePlanner(root)
    real = [planner.plan("Book.m4b").name for _ in range(4)]
    assert real == [reference.plan("Book.m4b").name for _ in range(4)]
    if "file symlink" in made:
        assert "Book-1.m4b" not in real, "a broken symlink still occupies its name"


# --------------------------------------------------------------------------- #
# 3. TTS through the panel's own planning function, beside the reference
# --------------------------------------------------------------------------- #


def snapshot_for(tmp_path: Path):
    """Real imported occurrences: direct files with one name, one folder root and a second root, as Start sees them."""
    from shared import importing as imp
    from test_importing import make_config
    from tts import epub2tts_gui as gui

    catalog = gui.build_catalog()
    options = imp.ImportOptions.for_catalog(catalog, include_subfolders=True)
    ids = imp.IdFactory("o-")
    direct = [touch(tmp_path / "loose" / f"d{i:02d}" / ("Chapter.txt" if i % 3 else "CHAPTER.pdf"))
              for i in range(30)]
    files = list(imp.validate_direct_files(direct, request_id="d", root=imp.ImportRoot("direct", None, 0,
                                                                                         imp.RootKind.DIRECT_FILES),
                                           catalog=catalog, options=options, id_factory=ids).files)
    src = source_tree(tmp_path)
    for order, folder in enumerate((src / "Library", src / "Other" / "Library"), start=1):
        request = imp.ScanRequest(f"s{order}", (imp.ImportRoot(f"r{order}", folder, order),), catalog, options,
                                  make_config())
        files += list(imp.scan_roots(request, id_factory=ids).files)
    return gui, imp.ImportedFileSnapshot(imp.Revision(1), tuple(files))


def test_tts_start_planning_matches_the_reference_for_direct_and_folder_imports(tmp_path, monkeypatch):
    gui, snapshot = snapshot_for(tmp_path)
    run = tmp_path / "run"
    touch(run / f"Chapter-{STEFFAN}-2.mp3")

    def planned():
        mapping = gui.plan_destinations(snapshot, run, label=STEFFAN, budget=SHORT)
        return {key: rel(item.destination, run) for key, item in mapping.items()}

    real = planned()
    monkeypatch.setattr(op, "DestinationPlanner", ReferencePlanner)
    assert planned() == real
    assert sum(1 for name in real.values() if "/" not in name) == 30
    assert len({name.casefold() for name in real.values()}) == len(real), "every occurrence has its own file"


# --------------------------------------------------------------------------- #
# 4. Counted work: linear in the number of outputs
# --------------------------------------------------------------------------- #


class Tried:
    """Counts the candidate paths every planner tries, split by pass (with and without the disk check)."""

    def __init__(self, monkeypatch):
        self.real = self.probe = self.disk = 0
        original = op.DestinationPlanner._is_free

        def counting(planner, candidate):
            if planner._check_filesystem:
                self.real += 1
                if planner._key(candidate) not in planner._taken:
                    self.disk += 1
            else:
                self.probe += 1
            return original(planner, candidate)

        monkeypatch.setattr(op.DestinationPlanner, "_is_free", counting)


@pytest.mark.parametrize("count", [250, 2341])
def test_identical_names_cost_a_bounded_number_of_candidates_per_output(count, tmp_path, monkeypatch):
    tried = Tried(monkeypatch)
    root = tmp_path / "run"
    root.mkdir()
    planner = op.DestinationPlanner(root)
    names = [planner.plan("Chapter.mp3").name for _ in range(count)]
    beside = [planner.plan("Chapter.mp3", start_index=1, subdir="Covers").name for _ in range(count)]
    folders = [planner.plan_directory("Book").name for _ in range(count)]
    assert names[-1] == f"Chapter-{count - 1}.mp3" and beside[-1] == f"Chapter-{count}.mp3"
    assert folders[-1] == f"Book-{count - 1}"
    # 4465b94: count*(count+1)/2 per family (8.2 million candidates at 2,341). Now at most two per output.
    assert tried.real <= 2 * 3 * count, tried.real
    assert tried.disk == 3 * count, "one disk check per planned output on an empty run folder"


@pytest.mark.parametrize("count", [250, 2341])
def test_the_tts_folder_finding_pass_and_the_real_pass_are_both_linear(count, tmp_path, monkeypatch):
    """Both identical titles and unique titles in one folder: the probe pass names every source ``probe.mp3``."""
    same = [touch(tmp_path / "same" / f"d{i:05d}" / "Chapter.txt") for i in range(count)]
    unique = [touch(tmp_path / "unique" / f"Chapter {i:05d}.txt") for i in range(count)]
    tried = Tried(monkeypatch)
    for sources in (same, unique):
        root = tmp_path / "run" / sources[0].parents[1].name
        plan = on.plan_named(op.plan_flat, root, sources, label=STEFFAN, planner=op.DestinationPlanner(root),
                             budget=ROOMY)
        assert len({item.destination for item in plan.items}) == count
    assert plan.items[-1].destination.name == f"Chapter {count - 1:05d}-{STEFFAN}.mp3"
    # 4465b94: 2,741,311 probe candidates and 2,741,311 real ones for the identical titles alone.
    assert tried.probe <= 2 * 2 * count, tried.probe
    assert tried.real <= 2 * 2 * count, tried.real


def test_the_full_suffix_range_is_reachable_and_its_longest_names_fit_the_budget(tmp_path):
    """10,001 identical TTS names (the unnumbered one, then -1 .. -10000) and the 10,002nd refused, in linear time.

    COLLISION_HEADROOM reserves the room for ``-10000``; the longest planned name and its engine's temporary
    publish name still fit the component limit and the Windows MAX_PATH budget.
    """
    root = tmp_path / "run"
    folder_units = SHORT.units(str(root))
    name = on.planned_name(tmp_path / ("Very long chapter title " * 12 + ".txt"), STEFFAN, root, budget=SHORT)
    planner = op.DestinationPlanner(root, check_filesystem=False)
    planned = [planner.plan(name) for _ in range(op.MAX_COLLISION_ATTEMPTS + 1)]
    assert planned[-1].name.endswith(f"-{op.MAX_COLLISION_ATTEMPTS}{on.EXTENSION}")
    with pytest.raises(op.ReservationError) as refused:
        planner.plan(name)
    assert "no free name" in refused.value.message
    longest = max(planned, key=lambda p: SHORT.units(p.name))
    assert SHORT.units(longest.name) + on.PUBLISH_HEADROOM <= on.COMPONENT_LIMIT
    assert folder_units + 1 + SHORT.units(longest.name) + on.PUBLISH_HEADROOM <= on.WINDOWS_PATH_LIMIT
    assert len({p.name.casefold() for p in planned}) == len(planned)
