"""The Converter checks its outputs against its inputs once per plan, not once per output — v0.8.2 Checkpoint 5.

Before this checkpoint the M4B Converter asked "is this output one of the inputs?" with the one-shot
``output_paths.assert_not_input``, which normalises **every** source again for **every** destination, three times
over: once per output in ``m4b_destinations.plan_outputs``, once more in ``m4b_plan.assemble_plan``'s final check, and
once per output again when ``m4b_execution.convert_segment`` writes it. A run of D outputs from N books cost
3·D·(N+1) path resolutions (measured at fee286f: 250 whole books planned in 20.9 s, 1,000 in 348 s).

Now one :class:`~shared.output_paths.InputIndex` (Checkpoint 1's, unchanged) serves the whole plan, built once over
every frozen occurrence, and the Converter builds one more per attempt for execution. What these tests protect:

1. **Same answers.** A one-shot oracle -- the fee286f check, every input normalised again per destination -- is put in
   place of the index and every scenario is planned both ways: the same destinations in the same order, and the same
   refusal (type, message and detail) for every alias of an input.
2. **Linear work.** Counted, not timed: normalisations are a small multiple of outputs plus inputs.
3. **Nothing else moved.** Whole and split naming, chapter order, book containers, mixed direct and folder imports,
   same-name collisions, frozen retry destinations.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePath

import pytest

from shared import output_paths
from shared.importing import IdFactory, ImportedFile, ImportRoot, RootKind, capture_identity
from shared.output_paths import DestinationPlanner, UnsafePathError

from m4b import m4b_execution
from m4b.converter import m4b_destinations, m4b_plan
from m4b.converter.m4b_plan import ConversionMode, PlanOptions, assemble_plan
from m4b.m4b_chapters import ChapterProbe, ProbeStatus, SourceChapter
from m4b.converter.m4b_metadata import MetadataMode, SourceTags
from m4b.m4b_probe import SourceReport
from m4b.m4b_execution import ProcessResult, SegmentWork

# The Converter panel's production path, driven exactly as the conversion-plan module drives it.
from test_m4b_conversion_plan import (  # noqa: F401 - pytest fixtures are found by name
    add,
    convert,
    make_panel,
    run_env,
    tk_root,
)


_ids = IdFactory("cp5-")


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not an audiobook", encoding="utf-8")
    return path


DIRECT = ImportRoot("direct-1", None, 0, RootKind.DIRECT_FILES)


def direct(path: Path) -> ImportedFile:
    return ImportedFile(occurrence_id=_ids.next_id("occ"), path=path, source_root=DIRECT, relative_path=None,
                        supported_type_id="m4b", identity=capture_identity(path, os.lstat(path)))


def under(root: ImportRoot, path: Path) -> ImportedFile:
    return ImportedFile(occurrence_id=_ids.next_id("occ"), path=path, source_root=root,
                        relative_path=PurePath(path.relative_to(root.path)), supported_type_id="m4b",
                        identity=capture_identity(path, os.lstat(path)))


def report(chapters: int = 0, *, status: ProbeStatus = ProbeStatus.OK) -> SourceReport:
    spans = tuple(SourceChapter(index=i, start=float(i * 60), title=f"Chapter {i + 1}") for i in range(chapters))
    return SourceReport(probe=ChapterProbe(status=status, duration=float(max(chapters, 1) * 60.0),
                                           chapters=spans, detail=""),
                        tags=SourceTags(), picture=None, artwork=None, decoder_args=(), codec_name="aac",
                        undecodable_xhe=False)


class OneShot:
    """The fee286f check, as an oracle: every input normalised again for every destination it is asked about."""

    built = 0

    def __init__(self, inputs, *, checkpoint=None):
        OneShot.built += 1
        self._inputs = tuple(inputs)

    def assert_not_input(self, destination):
        output_paths.assert_not_input(destination, self._inputs)


def use_one_shot(monkeypatch) -> None:
    for owner in (m4b_destinations, m4b_plan, output_paths):
        monkeypatch.setattr(owner, "InputIndex", OneShot)


def plan_run(entries, reports, run_root: Path, *, split: bool, check_filesystem: bool = True):
    """``assemble_plan`` as the Converter's worker calls it. *check_filesystem* False lets a name that exists on disk
    through the planner (as ``test_m4b_destinations`` does), so the input guard is what answers."""
    def reserve():
        run_root.mkdir(parents=True, exist_ok=True)
        return run_root, DestinationPlanner(run_root, check_filesystem=check_filesystem)

    return assemble_plan(snapshot_id="m4b-run-1", entries=entries, reports=reports,
                         options=PlanOptions(mode=ConversionMode.SPLIT if split else ConversionMode.WHOLE),
                         reserve=reserve, windows_decoder=lambda: False)


def mapping(plan, run_root: Path) -> list:
    return [(item.occurrence_id,
             [(s.order, s.title, s.track, str(s.destination.relative_to(run_root)).replace("\\", "/"))
              for s in item.segments])
            for item in plan.items]


def outcome(fn):
    """What a planning call answered: its value, or the refusal it raised (type, message, detail)."""
    try:
        return ("ok", fn())
    except UnsafePathError as exc:
        return ("refused", type(exc).__name__, exc.message, exc.detail)


class Counter:
    def __init__(self, monkeypatch):
        self.n = {"_normalise": 0, "assert_not_input": 0}
        real_normalise = output_paths._normalise
        real_one_shot = output_paths.assert_not_input

        def normalise(path):
            self.n["_normalise"] += 1
            return real_normalise(path)

        def one_shot(destination, inputs):
            self.n["assert_not_input"] += 1
            return real_one_shot(destination, inputs)

        monkeypatch.setattr(output_paths, "_normalise", normalise)
        monkeypatch.setattr(output_paths, "assert_not_input", one_shot)


# --------------------------------------------------------------------------- #
# Library shapes
# --------------------------------------------------------------------------- #


def library(tmp_path: Path, shape: str, books: int, chapters: int):
    """(entries, reports) for one synthetic queue. Every file exists; nothing is media."""
    entries: list[ImportedFile] = []
    if shape == "direct":
        entries = [direct(touch(tmp_path / "lib" / f"Book {i:03d}.m4b")) for i in range(books)]
    elif shape == "same-name":
        entries = [direct(touch(tmp_path / "lib" / f"d{i:03d}" / "Book.m4b")) for i in range(books)]
    elif shape == "duplicates":
        one = touch(tmp_path / "lib" / "Twice.m4b")
        entries = [direct(one) for _ in range(books)]
    elif shape == "folder":
        root = ImportRoot("root-1", tmp_path / "lib", 1, RootKind.FOLDER)
        entries = [under(root, touch(tmp_path / "lib" / f"Series {i % 3}" / f"Book {i:03d}" / f"Book {i:03d}.m4b"))
                   for i in range(books)]
    elif shape == "mixed":
        third = max(1, books // 3)
        entries = [direct(touch(tmp_path / "picked" / f"Book {i:03d}.m4b")) for i in range(third)]
        for r in range(2):
            base = tmp_path / f"lib{r}" / "Books"
            root = ImportRoot(f"root-{r + 1}", base, r + 1, RootKind.FOLDER)
            entries += [under(root, touch(base / f"Series {i % 2}" / f"Book {i:03d}.m4b")) for i in range(third)]
    else:  # pragma: no cover
        raise AssertionError(shape)
    reports = {entry.occurrence_id: report(chapters) for entry in entries}
    return tuple(entries), reports


SHAPES = [
    ("direct", 6, 0, False),
    ("direct", 6, 0, True),
    ("direct", 5, 7, True),
    ("same-name", 5, 4, True),
    ("same-name", 5, 0, False),
    ("duplicates", 3, 3, True),
    ("duplicates", 3, 0, False),
    ("folder", 7, 5, True),
    ("folder", 7, 0, False),
    ("mixed", 9, 4, True),
    ("mixed", 9, 0, False),
]


@pytest.mark.parametrize("shape,books,chapters,split", SHAPES,
                         ids=[f"{s}-{b}x{c}-{'split' if p else 'whole'}" for s, b, c, p in SHAPES])
def test_the_indexed_plan_is_the_one_shot_plan(tmp_path, monkeypatch, shape, books, chapters, split):
    """Whole and split, direct, folder and mixed imports, same names and duplicates: identical plans."""
    entries, reports = library(tmp_path, shape, books, chapters)
    indexed = plan_run(entries, reports, tmp_path / "out-a" / "Run", split=split)
    with monkeypatch.context() as patch:
        use_one_shot(patch)
        reference = plan_run(entries, reports, tmp_path / "out-b" / "Run", split=split)
    assert mapping(indexed, tmp_path / "out-a" / "Run") == mapping(reference, tmp_path / "out-b" / "Run")
    assert [i.occurrence_id for i in indexed.items] == [e.occurrence_id for e in entries], "queue order kept"


def test_split_names_and_order_are_unchanged(tmp_path):
    """One book folder per occurrence, chapters numbered in order inside it, same-name books kept apart."""
    entries, reports = library(tmp_path, "same-name", 2, 3)
    run_root = tmp_path / "out" / "Run"
    plan = plan_run(entries, reports, run_root, split=True)
    assert mapping(plan, run_root) == [
        (entries[0].occurrence_id, [(1, "Chapter 1", 1, "Book/01 - Chapter 1.mp3"),
                                    (2, "Chapter 2", 2, "Book/02 - Chapter 2.mp3"),
                                    (3, "Chapter 3", 3, "Book/03 - Chapter 3.mp3")]),
        (entries[1].occurrence_id, [(1, "Chapter 1", 1, "Book-1/01 - Chapter 1.mp3"),
                                    (2, "Chapter 2", 2, "Book-1/02 - Chapter 2.mp3"),
                                    (3, "Chapter 3", 3, "Book-1/03 - Chapter 3.mp3")]),
    ]


def test_whole_names_collide_safely_in_queue_order(tmp_path):
    entries, reports = library(tmp_path, "same-name", 3, 0)
    run_root = tmp_path / "out" / "Run"
    plan = plan_run(entries, reports, run_root, split=False)
    assert [segments[0][3] for _id, segments in mapping(plan, run_root)] == ["Book.mp3", "Book-1.mp3", "Book-2.mp3"]


# --------------------------------------------------------------------------- #
# Refusals: every alias of an input, the same answer both ways
# --------------------------------------------------------------------------- #


def _alias_cases(tmp_path: Path):
    """(name, entries, reports, run_root, split) where an output would land on an input."""
    cases = []
    # 1. a usable book's whole output is another usable book (the run root is their folder)
    folder = tmp_path / "c1"
    a = direct(touch(folder / "A.m4b"))
    b = direct(touch(folder / "A.mp3"))
    cases.append(("usable-input", (a, b), {a.occurrence_id: report(), b.occurrence_id: report()}, folder, False))
    # 2. the output is an UNUSABLE book: still a file on disk, still refused (by the final check before)
    folder = tmp_path / "c2"
    a = direct(touch(folder / "src" / "Book.m4b"))
    b = direct(touch(folder / "Book.mp3"))
    cases.append(("unusable-input", (a, b),
                  {a.occurrence_id: report(), b.occurrence_id: report(status=ProbeStatus.PROBE_FAILED)}, folder, False))
    # 3. the same file, imported with different letter case
    folder = tmp_path / "c3"
    real = touch(folder / "Case.mp3")
    a = direct(touch(folder / "src" / "case.m4b"))
    b = direct(Path(str(real).replace("Case.mp3", "CASE.MP3")))
    cases.append(("case-alias", (a, b), {a.occurrence_id: report(), b.occurrence_id: report()}, folder, False))
    # 4. a split chapter lands on an input inside its own book folder
    folder = tmp_path / "c4"
    a = direct(touch(folder / "src" / "Saga.m4b"))
    b = direct(touch(folder / "Saga" / "01 - Chapter 1.mp3"))
    cases.append(("split-chapter-input", (a, b), {a.occurrence_id: report(2), b.occurrence_id: report()},
                  folder, True))
    # 5. an input imported through a link to the run folder (a Windows junction needs no privilege; elsewhere a
    #    directory symlink, skipped only when the platform refuses to make one)
    folder = tmp_path / "c5"
    a = direct(touch(folder / "src" / "Linked.m4b"))
    touch(folder / "real" / "Linked.mp3")
    if _make_directory_link(folder / "alias", folder / "real"):
        b = direct(folder / "alias" / "Linked.mp3")
        cases.append(("link-alias", (a, b), {a.occurrence_id: report(), b.occurrence_id: report()},
                      folder / "real", False))
    return cases


def _make_directory_link(link: Path, target: Path) -> bool:
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
    except OSError:
        return False
    return True


def test_every_alias_of_an_input_is_refused_exactly_as_before(tmp_path, monkeypatch):
    for name, entries, reports, run_root, split in _alias_cases(tmp_path):
        indexed = outcome(lambda: plan_run(entries, reports, run_root, split=split, check_filesystem=False))
        with monkeypatch.context() as patch:
            use_one_shot(patch)
            reference = outcome(lambda: plan_run(entries, reports, run_root, split=split, check_filesystem=False))
        assert indexed[0] == "refused", (name, indexed)
        assert indexed == reference, name
        assert indexed[2] == "an output would overwrite one of the files being read", name
    names = [case[0] for case in _alias_cases(tmp_path / "again")]
    assert names[:4] == ["usable-input", "unusable-input", "case-alias", "split-chapter-input"]
    if os.name == "nt":
        assert "link-alias" in names, "a junction needs no privilege on Windows"


def test_plan_outputs_on_its_own_still_checks_its_own_entries(tmp_path):
    """Called without an index (its own callers and tests), it builds one from the entries it was given."""
    source = touch(tmp_path / "Book.mp3")
    entry = direct(source)
    with pytest.raises(UnsafePathError) as caught:
        m4b_destinations.plan_outputs([entry], {entry.occurrence_id: ("Book.mp3",)}, run_root=tmp_path,
                                      planner=DestinationPlanner(tmp_path, check_filesystem=False))
    assert caught.value.message == "an output would overwrite one of the files being read"


def test_an_input_that_cannot_be_indexed_reserves_nothing(tmp_path, monkeypatch):
    """The index is built before the reservation, so a source that breaks normalisation leaves no run folder."""
    entries, reports = library(tmp_path, "direct", 2, 0)
    real = output_paths._input_key

    def broken(path):
        if Path(path) == entries[1].path:
            raise ValueError("unnormalisable for this test")
        return real(path)

    monkeypatch.setattr(output_paths, "_input_key", broken)
    reserved = []
    with pytest.raises(ValueError):
        assemble_plan(snapshot_id="m4b-run-1", entries=entries, reports=reports, options=PlanOptions(),
                      reserve=lambda: reserved.append(1) or (tmp_path / "Run", DestinationPlanner(tmp_path / "Run")),
                      windows_decoder=lambda: False)
    assert reserved == []


# --------------------------------------------------------------------------- #
# Linear work, counted
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shape,books,chapters,split", [
    ("direct", 300, 0, False),
    ("mixed", 120, 0, False),
    ("direct", 40, 30, True),
    ("folder", 60, 20, True),
    ("same-name", 60, 10, True),
])
def test_planning_normalises_each_path_a_bounded_number_of_times(tmp_path, monkeypatch, shape, books, chapters,
                                                                  split):
    entries, reports = library(tmp_path, shape, books, chapters)
    counter = Counter(monkeypatch)
    plan = plan_run(entries, reports, tmp_path / "out" / "Run", split=split)
    outputs = sum(len(item.segments) for item in plan.items)
    # Per output: the planner's containment check (2), the two input lookups (2) and, for a folder import, the
    # mirrored parent (1); per input: one index entry. fee286f: 2·outputs·(inputs+1) for the input checks alone
    # (300 whole books: 180,600; 40 books x 30 chapters: 98,400).
    bound = 6 * outputs + 4 * len(entries) + 10
    assert counter.n["_normalise"] <= bound, (counter.n["_normalise"], bound)
    assert counter.n["assert_not_input"] == 0, "the one-shot guard is not used by the Converter's plan"


def test_a_conversion_checks_each_output_with_one_index_per_attempt(make_panel, tmp_path, run_env, monkeypatch):
    """The production path end to end -- preflight, plan, execute -- for 60 whole books: linear normalisations.

    fee286f: 3·60·61 = 10,980 for the three input checks alone (plan, final plan check, and one per written output).
    """
    panel = make_panel()
    paths = [touch(tmp_path / "src" / f"Book {i:02d}.m4b") for i in range(60)]
    add(panel, *paths)
    built = []
    real_index = output_paths.InputIndex

    class Recording(real_index):
        __slots__ = ()

        def __init__(self, inputs, **kwargs):
            inputs = tuple(inputs)
            built.append(len(inputs))
            super().__init__(inputs, **kwargs)

    for owner in (m4b_destinations, m4b_plan, output_paths):
        monkeypatch.setattr(owner, "InputIndex", Recording)
    counter = Counter(monkeypatch)
    plan = convert(panel, tmp_path, run_env)
    assert plan is not None and len(plan.items) == 60
    assert all(item.segments[0].destination.exists() for item in plan.items), "every book was written"
    assert built == [60, 60], "one index for the plan and one for the attempt's execution"
    assert counter.n["assert_not_input"] == 0
    assert counter.n["_normalise"] <= 12 * 60 + 20, counter.n["_normalise"]


# --------------------------------------------------------------------------- #
# Execution: the per-output check through the index answers as the one-shot guard did
# --------------------------------------------------------------------------- #


def _work(tmp_path: Path, destination: Path) -> SegmentWork:
    return SegmentWork(source=tmp_path / "src" / "Book.m4b", destination=destination, expected_duration=600.0,
                       quality=2, metadata_mode=MetadataMode.PRESERVE, tags={"album": "A"})


def _convert(work, **kwargs):
    started = []

    def fake_run(argv, *, cancelled, workspace, **more):
        started.append(list(argv))
        return ProcessResult(0)

    with monkeypatch_attr(m4b_execution, "run_argv", fake_run):
        result = m4b_execution.convert_segment(work, ffmpeg="ffmpeg", cancelled=lambda: False,
                                               measure=lambda p: None, **kwargs)
    return result, started


class monkeypatch_attr:  # noqa: N801 - a tiny context manager, named for what it does
    def __init__(self, owner, name, value):
        self.owner, self.name, self.value = owner, name, value

    def __enter__(self):
        self.saved = getattr(self.owner, self.name)
        setattr(self.owner, self.name, self.value)

    def __exit__(self, *exc):
        setattr(self.owner, self.name, self.saved)


@pytest.mark.parametrize("spelling", ["exact", "case", "dotted"])
def test_execution_refuses_an_input_through_the_index_as_through_the_sources(tmp_path, spelling):
    source = touch(tmp_path / "run" / "Book.mp3")
    other = touch(tmp_path / "src" / "Book.m4b")
    destination = {"exact": source, "case": tmp_path / "run" / "BOOK.MP3",
                   "dotted": tmp_path / "run" / "x" / ".." / "Book.mp3"}[spelling]
    by_index, started_a = _convert(_work(tmp_path, destination),
                                   sources=(other, source), inputs=output_paths.InputIndex((other, source)))
    by_sources, started_b = _convert(_work(tmp_path, destination), sources=(other, source))
    assert by_index.failed and by_sources.failed
    assert (by_index.message, by_index.detail) == (by_sources.message, by_sources.detail)
    assert started_a == started_b == [], "no process was started"
    assert source.read_text(encoding="utf-8") == "not an audiobook"


def test_execution_with_an_index_writes_a_destination_that_is_not_an_input(tmp_path):
    other = touch(tmp_path / "src" / "Book.m4b")
    destination = tmp_path / "run" / "Book.mp3"
    result, started = _convert(_work(tmp_path, destination), sources=(other,),
                               inputs=output_paths.InputIndex((other,)))
    assert result.finalised and destination.exists() and len(started) >= 1
