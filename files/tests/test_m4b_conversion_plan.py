"""The immutable conversion plan and its worker-side preflight — Plan 5, Phase 10.

Phases 1 to 6 built the pure pieces: the probe model, the structural verdict, the
complete-timeline partition, the naming seam and the metadata/chapter/artwork
rules. Phases 7B, 8 and 9 gave the panel the shared importer, provenance-aware
destinations and the shared run controls. This phase is where they become one
answer: every source is read on a worker thread, judged, planned, and frozen into
a single :class:`~mp3_tools.m4b_plan.ConversionPlan` before anything is written.

What these tests protect, in order of how much they matter
-----------------------------------------------------------
1. **The three answers stay three.** A failed probe, a source with no duration
   and a source with no audio are each unusable *for their own reason*, and none
   of them may quietly become "this book has no chapters" -- which would convert
   a book the tool never actually read.
2. **Nothing is written before everything is decided.** The run directory is
   reserved *after* validation and *before* planning, so a queue of unreadable
   books leaves no empty numbered folder behind.
3. **The plan is the only authority afterwards.** It is frozen, it holds no Tk
   object, and mutating the queue or the widgets after Start cannot reach it.
4. **The denominator is earned, not guessed.** Preflight reports indeterminate
   progress; ``total_segments`` is published once, after the plan exists.

Determinism
-----------
No test sleeps. The conversion thread is stubbed and the worker body is run
explicitly; the two job-control races use one real joinable thread and wait only
on real signals with a bounded timeout. Probe results are injected as immutable
values except in the generated-media section, which builds tiny real M4Bs with
ffmpeg and reads them through the production probe.

Safety
------
No repository media and no private fixtures. Placeholder ``.m4b`` files are
generated under ``tmp_path``; the real ones are six seconds of a sine tone built
by ffmpeg. ffmpeg's absence **fails** rather than skips -- Plan 5 adds no
optional skip.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import threading
import unittest.mock as mock
from pathlib import Path

import pytest

import tkinter as tk

from shared import ffmpeg_utils, output_paths
from shared import job_control as jc
from shared.importing import (
    IdFactory,
    ImportedFile,
    ImportRoot,
    RootKind,
    capture_identity,
)

from mp3_tools import m4b_converter, m4b_plan, m4b_probe
from mp3_tools.m4b_chapters import ChapterProbe, ProbeStatus, SourceChapter
from mp3_tools.m4b_metadata import AttachedPicture, MetadataMode, SourceTags
from mp3_tools.m4b_plan import (
    ARTWORK_AMBIGUOUS,
    ConversionMode,
    ConversionPlan,
    ItemFailure,
    ItemPlan,
    PlanOptions,
    SegmentPlan,
    assemble_plan,
)
from mp3_tools.m4b_probe import ArtworkProblem, SourceReport

from test_import_coordination import RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_metadata import require_ffmpeg  # noqa: E402
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PANEL_SOURCE = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_converter.py"
PLAN_SOURCE = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_plan.py"
PROBE_SOURCE = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_probe.py"

#: Every wait here is bounded, so a deadlock fails rather than hangs.
WAIT = 5.0

#: The genuine thread class, captured before any test replaces the panel's.
RealThread = threading.Thread


# --------------------------------------------------------------------------- #
# Building queues and reports without touching a disk or a process
# --------------------------------------------------------------------------- #


def book(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("not an audiobook", encoding="utf-8")
    return path


def direct(*paths: Path) -> tuple[ImportedFile, ...]:
    """Individually chosen files: one group, no mirroring (Decision 31A)."""
    ids = IdFactory("occ-")
    root = ImportRoot("direct-1", None, 0, RootKind.DIRECT_FILES)
    return tuple(
        ImportedFile(
            occurrence_id=ids.next_id("occ"),
            path=Path(path),
            source_root=root,
            relative_path=None,
            supported_type_id="m4b",
            identity=capture_identity(Path(path), os.lstat(path)),
        )
        for path in paths
    )


def under(root: Path, *paths: Path, order: int = 0, root_id: str = "root-1",
          ids: IdFactory | None = None) -> tuple[ImportedFile, ...]:
    """Files imported from one selected folder, keeping their relative places."""
    ids = ids or IdFactory("occ-")
    source_root = ImportRoot(root_id, Path(root), order, RootKind.FOLDER)
    return tuple(
        ImportedFile(
            occurrence_id=ids.next_id("occ"),
            path=Path(path),
            source_root=source_root,
            relative_path=Path(path).relative_to(root),
            supported_type_id="m4b",
            identity=capture_identity(Path(path), os.lstat(path)),
        )
        for path in paths
    )


def chapters(*starts: float, titles=None) -> tuple[SourceChapter, ...]:
    names = titles or [f"Chapter {n + 1}" for n in range(len(starts))]
    return tuple(
        SourceChapter(index=position, start=start, title=names[position])
        for position, start in enumerate(starts)
    )


def report(
    *,
    status: ProbeStatus = ProbeStatus.OK,
    duration: float | None = 600.0,
    chapter_list: tuple[SourceChapter, ...] = (),
    tags: SourceTags | None = None,
    picture: AttachedPicture | None = None,
    artwork: ArtworkProblem | None = None,
    decoder_args: tuple[str, ...] = (),
    codec: str = "aac",
    undecodable: bool = False,
    detail: str = "",
) -> SourceReport:
    """One synthetic preflight reading. Immutable, and never touches a file."""
    return SourceReport(
        probe=ChapterProbe(status=status, duration=duration,
                           chapters=chapter_list, detail=detail),
        tags=tags or SourceTags(),
        picture=picture,
        artwork=artwork,
        decoder_args=decoder_args,
        codec_name=codec,
        undecodable_xhe=undecodable,
    )


def reports_for(entries, **kwargs) -> dict:
    return {entry.occurrence_id: report(**kwargs) for entry in entries}


def reserver(run_root: Path):
    """A reservation that records whether the plan actually asked for one."""
    calls: list[Path] = []

    def reserve():
        run_root.mkdir(parents=True, exist_ok=True)
        calls.append(run_root)
        return run_root, output_paths.DestinationPlanner(run_root)

    reserve.calls = calls
    return reserve


def plan_for(entries, reports, run_root: Path, **options) -> ConversionPlan:
    return assemble_plan(
        snapshot_id="m4b-run-1",
        entries=entries,
        reports=reports,
        options=PlanOptions(**options),
        reserve=reserver(run_root),
    )


# --------------------------------------------------------------------------- #
# Shared conversion stubs, used by this module and by the two panel modules
# --------------------------------------------------------------------------- #


class StubThread:
    """Captures the worker's arguments without ever running it."""

    started: list = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self.target, self.args = target, args
        StubThread.started.append(self)

    def start(self):
        pass

    def join(self, timeout=None):
        pass


class _Proc:
    def __init__(self, returncode: int = 0, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout


def install_conversion_stubs(monkeypatch, state: dict) -> dict:
    """Replace every media seam so a real run executes with no ffmpeg and no media.

    Shared with ``test_m4b_converter_importing`` and ``test_m4b_converter_jobs``
    so all three modules drive the production worker through exactly the same
    seams rather than three slightly different imitations of it.

    ``state`` is read on every call, so a test can change ``reports`` or ``fail``
    after the panel is built and before the worker runs.
    """
    StubThread.started = []
    state.setdefault("fail", ())
    state.setdefault("commands", [])
    state.setdefault("reports", {})
    state.setdefault("default_report", report())
    state.setdefault("probed", [])

    monkeypatch.setattr(m4b_converter.threading, "Thread", StubThread)
    monkeypatch.setattr(m4b_converter.ffmpeg_utils, "have_ffmpeg", lambda: True)
    monkeypatch.setattr(m4b_converter.ffmpeg_utils, "ffmpeg_cmd", lambda: "ffmpeg")
    monkeypatch.setattr(m4b_converter.ffmpeg_utils, "probe_audio_stream", lambda p: {})
    monkeypatch.setattr(m4b_converter.sp, "reveal_in_file_manager", lambda target: None)

    def probe(path, **kwargs):
        state["probed"].append(Path(path))
        return state["reports"].get(Path(path).name, state["default_report"])

    monkeypatch.setattr(m4b_converter.m4b_probe, "probe_source", probe)

    def run(cmd, **kwargs):
        state["commands"].append([str(part) for part in cmd])
        if Path(str(cmd[-1])).name in state["fail"]:
            return _Proc(1, "ffmpeg said no")
        return _Proc(0)

    monkeypatch.setattr(m4b_converter.sp, "run", run)
    state["threads"] = StubThread
    return state


# --------------------------------------------------------------------------- #
# Panel fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture()
def make_panel(tk_root):
    made: list[m4b_converter.M4BConverterUI] = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        kwargs.setdefault("bridge", jc.LoggerBridge(logger=_Silent()))
        panel = m4b_converter.M4BConverterUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


class _Silent:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture()
def run_env(monkeypatch):
    return install_conversion_stubs(monkeypatch, {})


def add(panel, *paths: Path):
    panel.importer._choose_files = lambda: tuple(str(p) for p in paths)
    return panel.importer.add_files()


def start(panel):
    """Press Convert; return the params the worker would have been handed."""
    panel.start_convert()
    assert StubThread.started, "the worker was never handed a run"
    return StubThread.started[-1].args[0]


def convert(panel, tmp_path, run_env):
    """Run the whole production path: preflight, plan, execute, drain."""
    params = start(panel)
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()
    return panel.run_plan


def _reservation(tmp_path):
    counter = {"n": 0}

    def reserve(tool_key):
        counter["n"] += 1
        directory = tmp_path / f"run-{counter['n']}"
        directory.mkdir(parents=True, exist_ok=True)
        return output_paths.RunReservation(
            tool_key=tool_key,
            base_directory=tmp_path,
            tool_directory=tmp_path,
            run_directory=directory,
            run_number=counter["n"],
        )

    return reserve


# --------------------------------------------------------------------------- #
# The vocabulary is immutable, and holds nothing live
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", [SegmentPlan, ItemPlan, ItemFailure,
                                  ConversionPlan, PlanOptions])
def test_every_plan_type_is_frozen(kind):
    assert kind.__dataclass_params__.frozen, kind.__name__


def test_a_planned_segment_cannot_be_edited(tmp_path):
    segment = SegmentPlan(1, 0.0, 10.0, "One", tmp_path / "a.mp3", 1)
    with pytest.raises(Exception):
        segment.destination = tmp_path / "elsewhere.mp3"


def test_a_plan_holds_no_tk_object_and_no_live_handle(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    plan = convert(panel, tmp_path, run_env)

    forbidden = (tk.Variable, tk.Widget, threading.Thread, threading.Event)
    for holder in (plan, *plan.items, *plan.unusable):
        for name in holder.__dataclass_fields__:
            value = getattr(holder, name)
            assert not isinstance(value, forbidden), (type(holder).__name__, name)
            assert not callable(value), (type(holder).__name__, name)


def test_the_replacement_mapping_cannot_drift_after_freezing():
    live = {"album": "First"}
    options = PlanOptions(replacement=live)
    live["album"] = "Second"
    live["comment"] = "should never appear"
    assert dict(options.replacement) == {"album": "First"}
    with pytest.raises(TypeError):
        options.replacement["album"] = "Third"


def test_only_the_approved_replacement_fields_are_representable():
    options = PlanOptions(replacement={
        "title": "T", "artist": "A", "album_artist": "AA", "album": "AL",
        "comment": "no", "genre": "no", "series": "no"})
    assert set(options.replacement) == {"title", "artist", "album_artist", "album"}


def test_blank_replacement_values_are_dropped_rather_than_written():
    options = PlanOptions(replacement={"title": "   ", "album": " Book "})
    assert dict(options.replacement) == {"album": "Book"}


# --------------------------------------------------------------------------- #
# Classification: three answers, and they never collapse into two
# --------------------------------------------------------------------------- #


def test_a_chaptered_source_is_chaptered(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 200.0, 400.0))},
        tmp_path / "run")
    assert plan.items[0].chaptered is True
    assert plan.unusable == ()


def test_a_genuinely_chapterless_source_is_a_success(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, reports_for(entries), tmp_path / "run")
    assert plan.items[0].chaptered is False
    assert plan.unusable == ()


@pytest.mark.parametrize("status,reason", [
    (ProbeStatus.PROBE_FAILED, "probe_failed"),
    (ProbeStatus.NO_DURATION, "no_duration"),
    (ProbeStatus.NO_AUDIO, "no_audio"),
])
def test_an_operational_failure_is_unusable_and_keeps_its_own_reason(
        tmp_path, status, reason):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, reports_for(entries, status=status, duration=None),
                    tmp_path / "run")
    assert plan.items == ()
    assert len(plan.unusable) == 1
    assert plan.unusable[0].reason == reason


@pytest.mark.parametrize("status", [ProbeStatus.PROBE_FAILED, ProbeStatus.NO_AUDIO])
def test_an_operational_failure_never_becomes_chapterless(tmp_path, status):
    """The one confusion this whole layer exists to prevent."""
    entries = direct(book(tmp_path / "src", "A.m4b"))
    # A duration is present, so nothing but the status distinguishes this from a
    # perfectly ordinary chapterless book.
    plan = plan_for(entries, reports_for(entries, status=status, duration=600.0),
                    tmp_path / "run")
    assert plan.items == (), "a failed read must never be converted as one file"
    assert plan.unusable[0].reason in ("probe_failed", "no_audio")


@pytest.mark.parametrize("starts,reason", [
    ((0.0, -5.0), "start_before_zero"),
    ((0.0, 900.0), "start_at_or_beyond_duration"),
    ((0.0, 100.0, 100.0), "duplicate_start"),
    ((0.0, 300.0, 100.0), "starts_out_of_order"),
    ((0.0, float("nan")), "start_not_finite"),
])
def test_a_malformed_chapter_map_fails_the_item(tmp_path, starts, reason):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(*starts))}, tmp_path / "run")
    assert plan.items == ()
    assert plan.unusable[0].reason == reason


def test_a_malformed_chapter_map_is_never_routed_to_the_fallback(tmp_path):
    """Structural invalidity is a failure, not a chapterless book (§11.2)."""
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 300.0, 100.0))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    assert plan.items == ()
    assert plan.total_segments == 0


def test_nothing_is_repaired_on_the_way_through(tmp_path):
    """No sort, no clamp, no dedup: the refusal is the whole behaviour."""
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 500.0, 200.0))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    assert plan.items == ()
    assert "500" in plan.unusable[0].detail or plan.unusable[0].detail


def test_a_typed_failure_keeps_its_occurrence_and_its_two_messages(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, reports_for(entries, status=ProbeStatus.PROBE_FAILED,
                                         duration=None, detail="ffprobe exploded"),
                    tmp_path / "run")
    failure = plan.unusable[0]
    assert failure.occurrence_id == entries[0].occurrence_id
    assert failure.source == entries[0].path
    assert failure.message and "not converted" in failure.message
    assert "ffprobe exploded" in failure.detail
    assert failure.retryable is True


# --------------------------------------------------------------------------- #
# Artwork
# --------------------------------------------------------------------------- #


def test_no_cover_is_valid(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, reports_for(entries, picture=None), tmp_path / "run")
    assert plan.items[0].picture is None


def test_one_cover_is_carried_by_absolute_stream_index(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, reports_for(entries, picture=AttachedPicture(3, "mjpeg")),
                    tmp_path / "run")
    assert plan.items[0].picture == AttachedPicture(3, "mjpeg")


def test_several_covers_fail_the_item_closed(tmp_path):
    """Nothing is chosen. Phase 6 refused to invent a preference and so does this."""
    entries = direct(book(tmp_path / "src", "A.m4b"))
    problem = ArtworkProblem("more than one embedded cover", "#2 mjpeg, #3 png")
    plan = plan_for(entries, reports_for(entries, artwork=problem), tmp_path / "run")
    assert plan.items == ()
    assert plan.unusable[0].reason == ARTWORK_AMBIGUOUS
    assert "#2 mjpeg" in plan.unusable[0].detail


@pytest.mark.parametrize("mode", list(MetadataMode))
def test_several_covers_fail_in_every_metadata_mode(tmp_path, mode):
    """Deliberately unconditional: failing closed does not depend on the mode.

    Strip would discard the cover anyway, so a mode-conditional rule was
    available -- and would have been a new product rule invented here. The
    conservative reading is the one that ships.
    """
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, reports_for(
        entries, artwork=ArtworkProblem("two covers", "detail")),
        tmp_path / "run", metadata_mode=mode)
    assert plan.items == ()


# --------------------------------------------------------------------------- #
# Timeline: the complete partition, consumed rather than reimplemented
# --------------------------------------------------------------------------- #


def test_whole_mode_is_one_segment_covering_the_book(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 200.0, 400.0))}, tmp_path / "run")
    segments = plan.items[0].segments
    assert len(segments) == 1
    assert (segments[0].start, segments[0].end) == (0.0, 600.0)
    assert segments[0].track is None


def test_split_mode_produces_one_segment_per_chapter(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 200.0, 400.0))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    assert len(plan.items[0].segments) == 3


def test_pre_roll_belongs_to_chapter_one_and_the_tail_to_the_last(tmp_path):
    """No synthetic Opening file, and no audio lost at either end (46A)."""
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(41.062, 200.0, 400.0))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    segments = plan.items[0].segments
    assert len(segments) == 3, "no fourth Opening segment was invented"
    assert segments[0].start == 0.0, "pre-roll is inside chapter one"
    assert segments[-1].end == 600.0, "trailing audio is inside the last chapter"


def test_the_segments_tile_the_whole_source_exactly(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=3671.5, chapter_list=chapters(12.0, 800.25, 1500.0, 2400.75))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    segments = plan.items[0].segments
    for left, right in zip(segments, segments[1:]):
        assert left.end == right.start
    assert all(segment.duration > 0 for segment in segments)
    assert abs(sum(s.duration for s in segments) - 3671.5) < 1e-9


def test_a_chapterless_book_in_split_mode_is_one_whole_file(tmp_path):
    """Decision 18A: a success, named as a whole book, with no order prefix."""
    entries = direct(book(tmp_path / "src", "Quiet Book.m4b"))
    plan = plan_for(entries, reports_for(entries, duration=600.0),
                    tmp_path / "run", mode=ConversionMode.SPLIT)
    item = plan.items[0]
    assert len(item.segments) == 1
    assert item.segments[0].destination.name == "Quiet Book.mp3"
    assert item.chaptered is False


def test_a_chapterless_split_output_is_not_a_fragment(tmp_path):
    """It covers ``[0, D]``, so §16's fragment rules do not describe it.

    That is the one thing the drop pinned by naming but not by tags, and the
    flag is what later phases read instead of the run's mode.
    """
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, reports_for(entries), tmp_path / "run",
                    mode=ConversionMode.SPLIT)
    item = plan.items[0]
    assert item.fragment is False
    assert item.segments[0].track is None


def test_a_chaptered_split_item_is_a_fragment(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 300.0))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    assert plan.items[0].fragment is True


def test_a_whole_book_item_is_never_a_fragment(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 300.0))}, tmp_path / "run")
    assert plan.items[0].fragment is False


# --------------------------------------------------------------------------- #
# Naming
# --------------------------------------------------------------------------- #


def test_split_names_carry_the_structural_order_and_the_title(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0,
        chapter_list=chapters(0.0, 200.0, 400.0,
                              titles=["Intro", "Middle", "End"]))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    assert [s.destination.name for s in plan.items[0].segments] == [
        "01 - Intro.mp3", "02 - Middle.mp3", "03 - End.mp3"]


def test_the_slash_title_regression_survives_the_whole_pipeline(tmp_path):
    """The mandatory §14 regression, asserted through the real plan."""
    title = ("1 — There is no food here / Meg ate all the Swedish Fish / "
             "Please get off my hearse")
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, titles=[title]))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    destination = plan.items[0].segments[0].destination

    assert destination.parent == tmp_path / "run", "no path hierarchy was created"
    assert destination.name.startswith("01 - ")
    assert destination.suffix == ".mp3"
    for fragment in ("There is no food here", "Meg ate all the Swedish Fish",
                     "Please get off my hearse"):
        assert fragment in destination.name, fragment


def test_a_blank_title_falls_back_to_its_chapter_number(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 300.0, titles=["", "   "]))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    assert [s.destination.name for s in plan.items[0].segments] == [
        "01 - Chapter 1.mp3", "02 - Chapter 2.mp3"]


def test_duplicate_titles_are_separated_by_the_shared_planner(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 300.0, titles=["Same", "Same"]))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    names = [s.destination.name for s in plan.items[0].segments]
    assert names == ["01 - Same.mp3", "02 - Same.mp3"], "the order prefix already differs"


def test_a_reserved_device_name_is_sanitised(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, titles=["CON"]))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    assert plan.items[0].segments[0].destination.name == "01 - _CON.mp3"


def test_a_unicode_title_survives(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, titles=["Café テスト"]))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    assert "Café" in plan.items[0].segments[0].destination.name


def test_a_very_long_title_is_capped_with_the_extension_intact(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, titles=["A" * 300]))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    name = plan.items[0].segments[0].destination.name
    assert len(name) <= 255
    assert name.endswith(".mp3")


def test_order_numbers_restart_for_every_book(tmp_path):
    a, b = (book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    entries = direct(a, b)
    plan = plan_for(entries, {
        entries[0].occurrence_id: report(duration=600.0,
                                         chapter_list=chapters(0.0, 300.0)),
        entries[1].occurrence_id: report(duration=600.0,
                                         chapter_list=chapters(0.0, 300.0)),
    }, tmp_path / "run", mode=ConversionMode.SPLIT)
    for item in plan.items:
        assert [s.order for s in item.segments] == [1, 2]
        assert [s.track for s in item.segments] == [1, 2]


# --------------------------------------------------------------------------- #
# Destinations: Phase 8's routing, consumed by the plan
# --------------------------------------------------------------------------- #


def test_direct_whole_outputs_are_flat_in_the_run(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    run = tmp_path / "run"
    plan = plan_for(entries, reports_for(entries), run)
    assert [i.segments[0].destination for i in plan.items] == [
        run / "A.mp3", run / "B.mp3"]


def test_direct_split_outputs_are_flat_with_no_per_book_container(tmp_path):
    """Decision 31A, literally: no source-stem folder is invented."""
    entries = direct(book(tmp_path / "src", "A.m4b"))
    run = tmp_path / "run"
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 300.0))},
        run, mode=ConversionMode.SPLIT)
    for segment in plan.items[0].segments:
        assert segment.destination.parent == run


def test_one_folder_root_mirrors_its_hierarchy(tmp_path):
    root = tmp_path / "Library"
    top = book(root, "Top.m4b")
    nested = book(root / "Series", "Nested.m4b")
    entries = under(root, top, nested)
    run = tmp_path / "run"
    plan = plan_for(entries, reports_for(entries), run)
    by_name = {i.source.name: i.segments[0].destination for i in plan.items}
    assert by_name["Top.m4b"] == run / "Top.mp3"
    assert by_name["Nested.m4b"] == run / "Series" / "Nested.mp3"


def test_split_segments_land_at_the_mirrored_location(tmp_path):
    root = tmp_path / "Library"
    nested = book(root / "Series", "Nested.m4b")
    entries = under(root, nested)
    run = tmp_path / "run"
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 300.0))},
        run, mode=ConversionMode.SPLIT)
    for segment in plan.items[0].segments:
        assert segment.destination.parent == run / "Series"


def test_several_roots_get_collision_safe_containers(tmp_path):
    first = tmp_path / "one" / "Books"
    second = tmp_path / "two" / "Books"
    a = book(first, "One.m4b")
    b = book(second / "Deep", "Two.m4b")
    ids = IdFactory("occ-")
    entries = (under(first, a, order=0, root_id="root-1", ids=ids)
               + under(second, b, order=1, root_id="root-2", ids=ids))
    run = tmp_path / "run"
    plan = plan_for(entries, reports_for(entries), run)
    places = [i.segments[0].destination.relative_to(run).as_posix() for i in plan.items]
    assert places == ["Books/One.mp3", "Books-1/Deep/Two.mp3"]


def test_a_mixed_run_shares_one_collision_domain(tmp_path):
    root = tmp_path / "Library"
    folder_book = book(root, "Book.m4b")
    picked = book(tmp_path / "picked", "Book.m4b")
    ids = IdFactory("occ-")
    chosen = ImportedFile(
        occurrence_id=ids.next_id("occ"), path=picked,
        source_root=ImportRoot("direct-1", None, 0, RootKind.DIRECT_FILES),
        relative_path=None, supported_type_id="m4b",
        identity=capture_identity(picked, os.lstat(picked)))
    entries = (chosen,) + under(root, folder_book, order=1, ids=ids)
    run = tmp_path / "run"
    plan = plan_for(entries, reports_for(entries), run)
    names = sorted(i.segments[0].destination.name for i in plan.items)
    assert names == ["Book-1.mp3", "Book.mp3"]


def test_deliberate_duplicates_stay_separate_occurrences(tmp_path):
    path = book(tmp_path / "src", "Book.m4b")
    entries = direct(path, path)
    run = tmp_path / "run"
    plan = plan_for(entries, reports_for(entries), run)
    assert len({i.occurrence_id for i in plan.items}) == 2
    assert sorted(i.segments[0].destination.name for i in plan.items) == [
        "Book-1.mp3", "Book.mp3"]


def test_every_planned_segment_has_a_destination(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, {entries[0].occurrence_id: report(
        duration=600.0, chapter_list=chapters(0.0, 200.0, 400.0))},
        tmp_path / "run", mode=ConversionMode.SPLIT)
    destinations = [s.destination for i in plan.items for s in i.segments]
    assert len(destinations) == 3
    assert len(set(destinations)) == 3
    assert all(isinstance(d, Path) for d in destinations)


def test_no_destination_is_ever_a_source(tmp_path):
    """Checked against every source in the run, including the unusable ones."""
    good = book(tmp_path / "src", "A.m4b")
    bad = book(tmp_path / "src", "B.m4b")
    entries = direct(good, bad)
    plan = plan_for(entries, {
        entries[0].occurrence_id: report(),
        entries[1].occurrence_id: report(status=ProbeStatus.PROBE_FAILED, duration=None),
    }, tmp_path / "run")
    sources = {good, bad}
    for item in plan.items:
        for segment in item.segments:
            assert segment.destination not in sources


def test_a_source_already_named_like_an_output_is_never_overwritten(tmp_path):
    """Two guards stand here, and this proves which one actually fires.

    The Converter imports ``.m4b`` and writes ``.mp3``, so a planned output can
    normally never take a source's name. Constructed anyway -- a source already
    called ``A.mp3``, planned into its own folder -- the *collision* guard wins
    first: the shared planner sees the existing file and plans ``A-1.mp3``. So
    the source survives, and ``assert_not_input`` is the second line rather than
    the first.
    """
    folder = tmp_path / "src"
    folder.mkdir(parents=True, exist_ok=True)
    clash = folder / "A.mp3"
    original = "a source that is already named like an output"
    clash.write_text(original, encoding="utf-8")
    entries = direct(clash)
    plan = assemble_plan(
        snapshot_id="m4b-run-1", entries=entries,
        reports=reports_for(entries), options=PlanOptions(),
        reserve=lambda: (folder, output_paths.DestinationPlanner(folder)))

    destination = plan.items[0].segments[0].destination
    assert destination != clash
    assert destination.name == "A-1.mp3"
    assert clash.read_text(encoding="utf-8") == original


def test_every_planned_destination_is_checked_against_every_source(tmp_path, monkeypatch):
    """The guard is applied, and to the *whole* run -- unusable books included."""
    good = book(tmp_path / "src", "A.m4b")
    bad = book(tmp_path / "src", "B.m4b")
    entries = direct(good, bad)
    seen: list = []
    real = m4b_plan.assert_not_input

    def watched(destination, sources):
        seen.append((Path(destination), tuple(Path(s) for s in sources)))
        return real(destination, sources)

    monkeypatch.setattr(m4b_plan, "assert_not_input", watched)
    plan = plan_for(entries, {
        entries[0].occurrence_id: report(duration=600.0,
                                         chapter_list=chapters(0.0, 300.0)),
        entries[1].occurrence_id: report(status=ProbeStatus.PROBE_FAILED,
                                         duration=None),
    }, tmp_path / "run", mode=ConversionMode.SPLIT)

    planned = [s.destination for i in plan.items for s in i.segments]
    assert [entry[0] for entry in seen] == planned
    for _destination, sources in seen:
        assert set(sources) == {good, bad}, "the unusable book is still a source"


# --------------------------------------------------------------------------- #
# Metadata, chapter map and artwork, across all six cells
# --------------------------------------------------------------------------- #


SOURCE_TAGS = SourceTags(title="Book Title", artist="Author",
                         album_artist="Author", album="The Album", track=3)


def _cell(tmp_path, mode, metadata_mode, *, chaptered=True):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    payload = report(
        duration=600.0,
        chapter_list=chapters(0.0, 300.0) if chaptered else (),
        tags=SOURCE_TAGS,
        picture=AttachedPicture(2, "mjpeg"),
    )
    return plan_for(entries, {entries[0].occurrence_id: payload}, tmp_path / "run",
                    mode=mode, metadata_mode=metadata_mode,
                    replacement={"album": "NEW ALBUM", "title": "NEW TITLE"})


@pytest.mark.parametrize("metadata_mode", list(MetadataMode))
def test_the_plan_freezes_the_metadata_mode(tmp_path, metadata_mode):
    plan = _cell(tmp_path, ConversionMode.WHOLE, metadata_mode)
    assert plan.metadata_mode is metadata_mode


@pytest.mark.parametrize("metadata_mode,keeps", [
    (MetadataMode.PRESERVE, True),
    (MetadataMode.REPLACE, True),
    (MetadataMode.STRIP, False),
])
def test_whole_book_chapter_retention_is_d6a(tmp_path, metadata_mode, keeps):
    from mp3_tools.m4b_metadata import retains_chapters
    plan = _cell(tmp_path, ConversionMode.WHOLE, metadata_mode)
    assert retains_chapters(plan.metadata_mode, split=plan.items[0].fragment) is keeps


@pytest.mark.parametrize("metadata_mode", list(MetadataMode))
def test_every_split_fragment_drops_the_source_chapter_map(tmp_path, metadata_mode):
    from mp3_tools.m4b_metadata import retains_chapters
    plan = _cell(tmp_path, ConversionMode.SPLIT, metadata_mode)
    assert plan.items[0].fragment is True
    assert retains_chapters(plan.metadata_mode, split=True) is False


@pytest.mark.parametrize("metadata_mode,wanted", [
    (MetadataMode.PRESERVE, True),
    (MetadataMode.REPLACE, True),
    (MetadataMode.STRIP, False),
])
def test_artwork_follows_the_locked_mode_rules(tmp_path, metadata_mode, wanted):
    from mp3_tools.m4b_metadata import wants_artwork
    plan = _cell(tmp_path, ConversionMode.WHOLE, metadata_mode)
    assert plan.items[0].picture == AttachedPicture(2, "mjpeg")
    assert wants_artwork(plan.metadata_mode) is wanted


def test_whole_preserve_carries_the_source_fields_and_the_overrides(tmp_path):
    from mp3_tools.m4b_metadata import whole_book_tags
    plan = _cell(tmp_path, ConversionMode.WHOLE, MetadataMode.PRESERVE)
    tags = whole_book_tags(plan.metadata_mode, source=plan.items[0].tags,
                           replacement=plan.replacement)
    assert tags["artist"] == "Author"
    assert tags["album"] == "NEW ALBUM"
    assert "/" not in str(tags.get("track", "")), "a track total never survives"


def test_whole_replace_carries_only_what_was_typed(tmp_path):
    from mp3_tools.m4b_metadata import whole_book_tags
    plan = _cell(tmp_path, ConversionMode.WHOLE, MetadataMode.REPLACE)
    tags = whole_book_tags(plan.metadata_mode, source=plan.items[0].tags,
                           replacement=plan.replacement)
    assert set(tags) == {"album", "title"}
    assert "Author" not in tags.values()


def test_whole_strip_carries_nothing(tmp_path):
    from mp3_tools.m4b_metadata import whole_book_tags
    plan = _cell(tmp_path, ConversionMode.WHOLE, MetadataMode.STRIP)
    assert whole_book_tags(plan.metadata_mode, source=plan.items[0].tags,
                           replacement=plan.replacement) == {}


def test_split_preserve_inherits_only_book_identity(tmp_path):
    from mp3_tools.m4b_metadata import segment_tags
    plan = _cell(tmp_path, ConversionMode.SPLIT, MetadataMode.PRESERVE)
    segment = plan.items[0].segments[1]
    tags = segment_tags(plan.metadata_mode, title=segment.title,
                        order=segment.track, source=plan.items[0].tags,
                        replacement=plan.replacement)
    assert tags["title"] == segment.title != "Book Title"
    assert tags["track"] == 2
    assert tags["artist"] == "Author"


def test_split_replace_still_regenerates_the_segment_title(tmp_path):
    """Decision 47A's narrow exception, proved end to end."""
    from mp3_tools.m4b_metadata import segment_tags
    plan = _cell(tmp_path, ConversionMode.SPLIT, MetadataMode.REPLACE)
    segment = plan.items[0].segments[0]
    tags = segment_tags(plan.metadata_mode, title=segment.title,
                        order=segment.track, source=plan.items[0].tags,
                        replacement=plan.replacement)
    assert tags["title"] == segment.title
    assert tags["title"] != "NEW TITLE", "a whole-book title never becomes a segment's"
    assert tags["album"] == "NEW ALBUM"


def test_split_strip_regenerates_nothing(tmp_path):
    from mp3_tools.m4b_metadata import segment_tags
    plan = _cell(tmp_path, ConversionMode.SPLIT, MetadataMode.STRIP)
    segment = plan.items[0].segments[0]
    assert segment_tags(plan.metadata_mode, title=segment.title,
                        order=segment.track or 1) == {}


# --------------------------------------------------------------------------- #
# Usable / unusable mixes and the reservation lifecycle
# --------------------------------------------------------------------------- #


def test_all_usable_keeps_the_input_order(tmp_path):
    entries = direct(*[book(tmp_path / "src", f"{n}.m4b") for n in "CAB"])
    plan = plan_for(entries, reports_for(entries), tmp_path / "run")
    assert [i.source.name for i in plan.items] == ["C.m4b", "A.m4b", "B.m4b"]


def test_a_mixed_run_keeps_both_orders_deterministic(tmp_path):
    paths = [book(tmp_path / "src", f"{n}.m4b") for n in "ABCD"]
    entries = direct(*paths)
    broken = report(status=ProbeStatus.PROBE_FAILED, duration=None)
    plan = plan_for(entries, {
        entries[0].occurrence_id: report(),
        entries[1].occurrence_id: broken,
        entries[2].occurrence_id: report(),
        entries[3].occurrence_id: broken,
    }, tmp_path / "run")
    assert [i.source.name for i in plan.items] == ["A.m4b", "C.m4b"]
    assert [f.source.name for f in plan.unusable] == ["B.m4b", "D.m4b"]


def test_an_unusable_item_never_becomes_an_empty_success(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = plan_for(entries, reports_for(entries, status=ProbeStatus.NO_AUDIO,
                                         duration=None), tmp_path / "run")
    assert plan.items == ()
    assert plan.total_segments == 0
    assert all(i.segments for i in plan.items), "no item with an empty segment tuple"


def test_a_run_with_nothing_usable_reserves_no_directory(tmp_path):
    """A failed preflight must leave no empty numbered folder behind."""
    entries = direct(book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    reserve = reserver(tmp_path / "run")
    plan = assemble_plan(
        snapshot_id="m4b-run-1", entries=entries,
        reports=reports_for(entries, status=ProbeStatus.PROBE_FAILED, duration=None),
        options=PlanOptions(), reserve=reserve)
    assert reserve.calls == [], "nothing usable, so nothing was reserved"
    assert plan.run_directory is None
    assert not (tmp_path / "run").exists()


def test_one_usable_item_is_enough_to_reserve(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    reserve = reserver(tmp_path / "run")
    plan = assemble_plan(
        snapshot_id="m4b-run-1", entries=entries,
        reports={
            entries[0].occurrence_id: report(status=ProbeStatus.NO_DURATION,
                                             duration=None),
            entries[1].occurrence_id: report(),
        },
        options=PlanOptions(), reserve=reserve)
    assert len(reserve.calls) == 1, "reserved once, and only once"
    assert plan.run_directory == tmp_path / "run"
    assert len(plan.items) == 1 and len(plan.unusable) == 1


def test_the_reservation_happens_after_validation(tmp_path):
    """Order is the contract: judged first, reserved second, planned third."""
    seen: list[str] = []
    entries = direct(book(tmp_path / "src", "A.m4b"))

    class Watching(dict):
        def get(self, key, default=None):
            seen.append("validated")
            return super().get(key, default)

    def reserve():
        seen.append("reserved")
        (tmp_path / "run").mkdir(exist_ok=True)
        return tmp_path / "run", output_paths.DestinationPlanner(tmp_path / "run")

    payload = Watching({entries[0].occurrence_id: report()})
    assemble_plan(snapshot_id="m4b-run-1", entries=entries, reports=payload,
                  options=PlanOptions(), reserve=reserve)
    assert seen == ["validated", "reserved"]


def test_planning_creates_no_directory_of_its_own(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"))
    root = tmp_path / "Library"
    nested = book(root / "Series", "Nested.m4b")
    entries = under(root, nested)
    run = tmp_path / "run"
    plan = plan_for(entries, reports_for(entries), run)
    assert not (run / "Series").exists(), "the mirrored folder is made at write time"
    assert plan.items[0].segments[0].destination.parent == run / "Series"


# --------------------------------------------------------------------------- #
# total_segments
# --------------------------------------------------------------------------- #


def test_whole_mode_counts_one_segment_per_usable_book(tmp_path):
    entries = direct(*[book(tmp_path / "src", f"{n}.m4b") for n in "ABC"])
    plan = plan_for(entries, reports_for(
        entries, duration=600.0, chapter_list=chapters(0.0, 200.0, 400.0)),
        tmp_path / "run")
    assert plan.total_segments == 3


def test_split_mode_counts_every_chapter(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    plan = plan_for(entries, {
        entries[0].occurrence_id: report(duration=600.0,
                                         chapter_list=chapters(0.0, 200.0, 400.0)),
        entries[1].occurrence_id: report(duration=600.0,
                                         chapter_list=chapters(0.0, 300.0)),
    }, tmp_path / "run", mode=ConversionMode.SPLIT)
    assert plan.total_segments == 5


def test_unusable_books_contribute_nothing_to_the_denominator(tmp_path):
    entries = direct(book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    plan = plan_for(entries, {
        entries[0].occurrence_id: report(duration=600.0,
                                         chapter_list=chapters(0.0, 200.0)),
        entries[1].occurrence_id: report(status=ProbeStatus.PROBE_FAILED,
                                         duration=None),
    }, tmp_path / "run", mode=ConversionMode.SPLIT)
    assert plan.total_segments == 2, "the failed book adds no fake units"


# --------------------------------------------------------------------------- #
# The production worker: preflight on a worker thread, nothing on the Tk thread
# --------------------------------------------------------------------------- #


def test_the_run_produces_an_immutable_plan(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    plan = convert(panel, tmp_path, run_env)
    assert isinstance(plan, ConversionPlan)
    assert plan.snapshot_id == panel.run_snapshot.snapshot_id


def test_no_probe_runs_before_the_worker_starts(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    params = start(panel)
    assert run_env["probed"] == [], "Start must not read a single source"
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    assert len(run_env["probed"]) == 1


def test_the_panel_never_probes_on_the_tk_thread():
    """Structural: neither the probe seam nor ffprobe is named outside the worker."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    worker = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "convert_worker")
    worker_calls = {node.func.attr for node in ast.walk(worker)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "probe_source" in worker_calls

    others = [node for node in ast.walk(tree)
              if isinstance(node, ast.FunctionDef) and node.name != "convert_worker"]
    for node in others:
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                assert call.func.attr not in ("probe_source", "probe_sources",
                                              "ffprobe_cmd"), node.name


def test_the_worker_reads_no_widget():
    """It was handed frozen values; it may not go back for live ones."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    worker = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "convert_worker")
    reached = {node.attr for node in ast.walk(worker)
               if isinstance(node, ast.Attribute)
               and isinstance(node.value, ast.Name) and node.value.id == "self"}
    assert reached == {"_cancel_event", "_log_q"}, reached


def test_the_options_are_read_once_on_the_main_thread(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    params = start(panel)
    frozen = params["options"]
    assert isinstance(frozen, PlanOptions)

    panel.var_quality.set(9)
    panel.var_metadata_mode.set(MetadataMode.STRIP.value)
    panel.album_entry.insert(0, "Changed mid-run")
    assert frozen.quality != 9
    assert frozen.metadata_mode is MetadataMode.PRESERVE
    assert "album" not in frozen.replacement


def test_a_queue_change_after_start_cannot_reach_the_plan(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    params = start(panel)
    panel.manager.clear()
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()
    assert [i.source.name for i in panel.run_plan.items] == ["A.m4b", "B.m4b"]


def test_the_widgets_cannot_change_where_a_book_lands(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    plan = convert(panel, tmp_path, run_env)
    before = plan.items[0].segments[0].destination
    panel.var_quality.set(0)
    assert panel.run_plan.items[0].segments[0].destination == before


def test_the_output_folder_is_shown_only_after_preflight(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    hint = panel.var_outdir.get()
    start(panel)
    assert panel.var_outdir.get() == hint, "Start reserves nothing"
    assert panel._last_run_dir is None


def test_a_run_with_nothing_usable_shows_no_new_folder(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    run_env["default_report"] = report(status=ProbeStatus.PROBE_FAILED, duration=None)
    hint = panel.var_outdir.get()
    plan = convert(panel, tmp_path, run_env)
    assert plan.run_directory is None
    assert panel.var_outdir.get() == hint
    assert run_env["commands"] == [], "nothing was converted"


def test_a_usable_run_writes_into_the_reserved_folder(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    plan = convert(panel, tmp_path, run_env)
    assert plan.run_directory == tmp_path / "run-1"
    assert panel._last_run_dir == plan.run_directory
    assert str(plan.run_directory) in panel.var_outdir.get()
    assert run_env["commands"][0][-1].endswith("A.mp3")


def test_an_unusable_book_is_reported_as_a_failure(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    run_env["reports"]["B.m4b"] = report(status=ProbeStatus.NO_AUDIO, duration=None)
    convert(panel, tmp_path, run_env)

    assert panel.run_result.failed_count == 1
    assert panel.run_result.succeeded_count == 1
    summary = "\n".join(panel.jobs.views.summary)
    assert "no audio" in summary.lower()


def test_the_command_comes_from_the_frozen_plan(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    run_env["default_report"] = report(
        duration=600.0, tags=SOURCE_TAGS, picture=AttachedPicture(2, "mjpeg"))
    convert(panel, tmp_path, run_env)

    argv = run_env["commands"][0]
    assert argv[argv.index("-map_metadata") + 1] == "-1", "always an allowlist"
    assert argv[argv.index("-map_chapters") + 1] == "0", "whole Preserve keeps them"
    assert "-map" in argv and "0:2" in argv, "the cover rides along by absolute index"
    assert argv[argv.index("-q:a") + 1] == "2"
    assert "libmp3lame" in argv


def test_strip_writes_no_metadata_and_no_cover(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    run_env["default_report"] = report(
        duration=600.0, tags=SOURCE_TAGS, picture=AttachedPicture(2, "mjpeg"))
    panel.var_metadata_mode.set(MetadataMode.STRIP.value)
    convert(panel, tmp_path, run_env)

    argv = run_env["commands"][0]
    assert argv[argv.index("-map_chapters") + 1] == "-1"
    assert "-vn" in argv, "no cover is mapped"
    assert "-metadata" not in argv
    assert "-id3v2_version" not in argv


def test_replace_writes_only_the_typed_fields(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    run_env["default_report"] = report(duration=600.0, tags=SOURCE_TAGS)
    panel.var_metadata_mode.set(MetadataMode.REPLACE.value)
    panel.album_entry.insert(0, "Chosen Album")
    convert(panel, tmp_path, run_env)

    argv = " ".join(run_env["commands"][0])
    assert "album=Chosen Album" in argv
    assert "The Album" not in argv, "the source album was replaced, not kept"


# --------------------------------------------------------------------------- #
# Progress: the denominator is earned
# --------------------------------------------------------------------------- #


def _progress(panel):
    return [(e.stage, e.completed, e.total) for e in panel.jobs.stream.events
            if e.kind is jc.JobEventKind.PROGRESS]


def test_preflight_publishes_no_denominator(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    start(panel)
    panel._pump.tick()
    view = panel.jobs.summary_view.progress
    assert view.mode is jc.ProgressMode.INDETERMINATE
    assert view.total is None, "no honest total exists until every source is read"


def test_the_final_denominator_is_total_segments(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, *[book(tmp_path / "src", f"{n}.m4b") for n in "ABC"])
    plan = convert(panel, tmp_path, run_env)
    totals = {total for _stage, _done, total in _progress(panel)
              if total is not None}
    assert totals == {plan.total_segments} == {3}


def test_the_denominator_is_published_once(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, *[book(tmp_path / "src", f"{n}.m4b") for n in "AB"])
    convert(panel, tmp_path, run_env)
    counted = _progress(panel)
    assert counted[0] == (m4b_converter.STAGE_PREFLIGHT, 0, None)
    assert counted[1] == (m4b_converter.STAGE_CONVERT, 0, 2)
    assert [entry[1] for entry in counted[1:]] == [0, 1, 2]


def test_the_interim_item_denominator_is_gone(make_panel, tmp_path, run_env):
    """Phase 9 counted imported books; the plan's segments replace that."""
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    run_env["reports"]["B.m4b"] = report(status=ProbeStatus.PROBE_FAILED, duration=None)
    plan = convert(panel, tmp_path, run_env)
    assert plan.total_segments == 1
    totals = {total for _stage, _done, total in _progress(panel) if total is not None}
    assert totals == {1}, "two books were imported; only one is executable work"


def test_a_successful_run_reaches_its_planned_total(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    convert(panel, tmp_path, run_env)
    view = panel.jobs.summary_view.progress
    assert (view.completed, view.total) == (2, 2)


def test_the_two_stages_are_reported_in_order(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    convert(panel, tmp_path, run_env)
    stages = [e.stage for e in panel.jobs.stream.events
              if e.kind is jc.JobEventKind.STAGE_CHANGED]
    assert stages == [m4b_converter.STAGE_PREFLIGHT, m4b_converter.STAGE_CONVERT]


# --------------------------------------------------------------------------- #
# Job control during preflight
# --------------------------------------------------------------------------- #


def test_cancelling_during_preflight_probes_nothing_more(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, *[book(tmp_path / "src", f"{n}.m4b") for n in "ABC"])
    params = start(panel)
    panel.cancel()
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()

    assert run_env["probed"] == [], "no source was read after the request"
    assert run_env["commands"] == []
    assert panel.job_controller.state is jc.JobState.CANCELLED
    assert panel.run_plan is None, "a cancelled preflight produces no plan"


def test_cancelling_during_preflight_reserves_nothing(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    params = start(panel)
    panel.cancel()
    reserve = mock.Mock(side_effect=_reservation(tmp_path))
    with mock.patch.object(output_paths, "reserve_run_directory", reserve):
        panel.convert_worker(params)
    assert reserve.call_count == 0


def test_a_pause_settles_between_two_sources(make_panel, tmp_path, run_env):
    """A real thread. The probe of the book in hand is never interrupted."""
    panel = make_panel()
    add(panel, *[book(tmp_path / "src", f"{n}.m4b") for n in "ABC"])
    params = start(panel)

    entered, release = threading.Event(), threading.Event()
    seen: list = []

    def gated(path, **kwargs):
        seen.append(Path(path))
        if len(seen) == 1:
            entered.set()
            assert release.wait(WAIT), "the first probe was never released"
        return report()

    with mock.patch.object(m4b_converter.m4b_probe, "probe_source", gated), \
            mock.patch.object(output_paths, "reserve_run_directory",
                              side_effect=_reservation(tmp_path)):
        worker = RealThread(target=panel.convert_worker, args=(params,),
                            name="m4b-preflight")
        worker.start()
        assert entered.wait(WAIT), "the first probe never began"

        panel.pause()
        assert panel.job_controller.state is jc.JobState.PAUSE_REQUESTED
        release.set()

        waiter = threading.Event()
        for _ in range(int(WAIT * 200)):
            if panel.job_controller.state is jc.JobState.PAUSED:
                break
            waiter.wait(0.005)
        assert panel.job_controller.state is jc.JobState.PAUSED
        assert len(seen) == 1, "no further source was read while paused"

        panel.cancel()
        worker.join(WAIT)
        assert not worker.is_alive(), "cancel did not wake the paused worker"

    assert panel.job_controller.state is jc.JobState.CANCELLED


def test_resume_continues_the_preflight(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"), book(tmp_path / "src", "B.m4b"))
    params = start(panel)

    entered, release = threading.Event(), threading.Event()
    seen: list = []

    def gated(path, **kwargs):
        seen.append(Path(path))
        if len(seen) == 1:
            entered.set()
            assert release.wait(WAIT)
        return report()

    with mock.patch.object(m4b_converter.m4b_probe, "probe_source", gated), \
            mock.patch.object(output_paths, "reserve_run_directory",
                              side_effect=_reservation(tmp_path)):
        worker = RealThread(target=panel.convert_worker, args=(params,))
        worker.start()
        assert entered.wait(WAIT)
        panel.pause()
        release.set()
        waiter = threading.Event()
        for _ in range(int(WAIT * 200)):
            if panel.job_controller.state is jc.JobState.PAUSED:
                break
            waiter.wait(0.005)
        panel.resume()
        worker.join(WAIT)
        assert not worker.is_alive()

    assert len(seen) == 2
    panel._pump.tick()
    assert panel.job_controller.state is jc.JobState.SUCCEEDED


def test_the_controller_is_still_the_only_state_authority(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    convert(panel, tmp_path, run_env)
    walked = []
    for entry in panel.jobs.stream.events:
        if entry.state is not None and (not walked or walked[-1] is not entry.state):
            walked.append(entry.state)
    for current, proposed in zip([jc.JobState.IDLE] + walked, walked):
        assert jc.is_legal_transition(current, proposed), (current, proposed)


def test_one_pump_still_owns_every_callback(make_panel, tmp_path, run_env):
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    convert(panel, tmp_path, run_env)
    assert panel._pump.drain_count == 2
    assert panel._pump.pending is not None


# --------------------------------------------------------------------------- #
# Generated media — the production probe against a real ffprobe
# --------------------------------------------------------------------------- #

_META = (
    ";FFMETADATA1\ntitle=Generated Book\nartist=Gen Artist\nalbum=Gen Album\n"
    "album_artist=Gen Album Artist\ntrack=3/9\ncomment=NEVER\n"
    "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle=Ch One\n"
    "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=2000\nEND=4000\ntitle=Ch Two\n"
    "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=4000\nEND=6000\ntitle=Ch Three\n"
)

_PLAIN_META = ";FFMETADATA1\ntitle=Quiet Book\nalbum=Quiet Album\n"


def _ff(*args):
    out = subprocess.run(
        [ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-y", *args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert out.returncode == 0, out.stdout.decode("utf-8", "replace")[-800:]


@pytest.fixture(scope="module")
def real_books(tmp_path_factory) -> dict:
    """Tiny real M4Bs: chaptered with a cover, chapterless, and two covers."""
    require_ffmpeg()
    w = tmp_path_factory.mktemp("m4b_plan_media")
    (w / "meta.txt").write_text(_META, encoding="utf-8")
    (w / "plain.txt").write_text(_PLAIN_META, encoding="utf-8")
    _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:a", "aac",
        "-b:a", "64k", str(w / "a.m4a"))
    _ff("-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1", str(w / "c.jpg"))
    _ff("-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-frames:v", "1", str(w / "c.png"))

    out: dict = {"dir": w}
    out["chaptered"] = w / "chaptered.m4b"
    _ff("-i", str(w / "a.m4a"), "-i", str(w / "c.jpg"), "-i", str(w / "meta.txt"),
        "-map", "0:a", "-map", "1:v", "-map_metadata", "2", "-map_chapters", "2",
        "-c:a", "copy", "-c:v", "copy", "-disposition:v:0", "attached_pic",
        str(out["chaptered"]))
    out["chapterless"] = w / "chapterless.m4b"
    _ff("-i", str(w / "a.m4a"), "-i", str(w / "plain.txt"), "-map", "0:a",
        "-map_metadata", "1", "-c:a", "copy", str(out["chapterless"]))
    out["twocovers"] = w / "twocovers.m4b"
    _ff("-i", str(w / "a.m4a"), "-i", str(w / "c.jpg"), "-i", str(w / "c.png"),
        "-map", "0:a", "-map", "1:v", "-map", "2:v", "-map_metadata", "-1",
        "-c:a", "copy", "-c:v", "copy",
        "-disposition:v:0", "attached_pic", "-disposition:v:1", "attached_pic",
        str(out["twocovers"]))
    out["notmedia"] = w / "notmedia.m4b"
    out["notmedia"].write_text("this is not an audiobook", encoding="utf-8")
    return out


def test_the_generated_books_are_shaped_as_intended(real_books):
    """Otherwise every assertion below could pass for the wrong reason."""
    payload = json.loads(subprocess.run(
        [ffmpeg_utils.ffprobe_cmd(), "-v", "error", "-print_format", "json",
         "-show_chapters", "-show_streams", str(real_books["chaptered"])],
        stdout=subprocess.PIPE, check=True).stdout.decode("utf-8", "replace"))
    assert len(payload["chapters"]) == 3
    assert any(s.get("disposition", {}).get("attached_pic") for s in payload["streams"])


def test_the_production_probe_reads_a_real_chaptered_book(real_books):
    found = m4b_probe.probe_source(real_books["chaptered"])
    assert found.probe.status is ProbeStatus.OK
    assert found.probe.duration and 5.5 < found.probe.duration < 6.5
    assert [c.title for c in found.probe.chapters] == ["Ch One", "Ch Two", "Ch Three"]
    assert [c.start for c in found.probe.chapters] == [0.0, 2.0, 4.0]


def test_the_production_probe_reads_the_approved_tags_and_nothing_else(real_books):
    found = m4b_probe.probe_source(real_books["chaptered"])
    assert found.tags.title == "Generated Book"
    assert found.tags.album == "Gen Album"
    assert found.tags.artist == "Gen Artist"
    assert found.tags.track == 3, "the /9 total is discarded"
    assert not hasattr(found.tags, "comment")


def test_the_production_probe_finds_the_single_cover(real_books):
    found = m4b_probe.probe_source(real_books["chaptered"])
    assert found.picture is not None
    assert found.picture.codec_name == "mjpeg"
    assert found.artwork is None


def test_the_production_probe_reads_a_real_chapterless_book(real_books):
    found = m4b_probe.probe_source(real_books["chapterless"])
    assert found.probe.status is ProbeStatus.OK
    assert found.probe.chapters == ()
    assert found.picture is None


def test_two_real_covers_are_refused_rather_than_chosen_between(real_books):
    found = m4b_probe.probe_source(real_books["twocovers"])
    assert found.picture is None
    assert found.artwork is not None
    assert "more than one" in found.artwork.message


def test_a_file_that_is_not_media_is_probe_failed(real_books):
    found = m4b_probe.probe_source(real_books["notmedia"])
    assert found.probe.status is ProbeStatus.PROBE_FAILED
    assert found.probe.chapters == ()
    assert found.detail if False else found.probe.detail


def test_a_missing_file_is_probe_failed(tmp_path):
    found = m4b_probe.probe_source(tmp_path / "nothing-here.m4b")
    assert found.probe.status is ProbeStatus.PROBE_FAILED


def test_a_real_chaptered_book_plans_its_whole_timeline(real_books, tmp_path):
    entries = direct(real_books["chaptered"])
    found = m4b_probe.probe_source(real_books["chaptered"])
    plan = plan_for(entries, {entries[0].occurrence_id: found},
                    tmp_path / "run", mode=ConversionMode.SPLIT)
    segments = plan.items[0].segments
    assert [s.destination.name for s in segments] == [
        "01 - Ch One.mp3", "02 - Ch Two.mp3", "03 - Ch Three.mp3"]
    assert segments[0].start == 0.0
    assert abs(segments[-1].end - found.probe.duration) < 1e-9
    assert abs(sum(s.duration for s in segments) - found.probe.duration) < 1e-9


def test_a_real_unreadable_file_fails_preflight_and_reserves_nothing(
        real_books, tmp_path):
    entries = direct(real_books["notmedia"])
    reserve = reserver(tmp_path / "run")
    plan = assemble_plan(
        snapshot_id="m4b-run-1", entries=entries,
        reports={entries[0].occurrence_id: m4b_probe.probe_source(entries[0].path)},
        options=PlanOptions(), reserve=reserve)
    assert plan.items == ()
    assert plan.unusable[0].reason == "probe_failed"
    assert reserve.calls == []


# --------------------------------------------------------------------------- #
# Purity and phase boundaries
# --------------------------------------------------------------------------- #


def _roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_the_plan_module_runs_no_process_and_owns_no_thread():
    roots = _roots(PLAN_SOURCE)
    assert not {"subprocess", "threading", "queue", "logging", "tkinter"} & roots
    text = PLAN_SOURCE.read_text(encoding="utf-8")
    for forbidden in ("Popen", "subprocess.", "tkinter", "ffprobe_cmd", "ffmpeg_cmd",
                      "check_output", "sp.run"):
        assert forbidden not in text, forbidden


def test_the_probe_module_touches_no_tk():
    roots = _roots(PROBE_SOURCE)
    assert "tkinter" not in roots
    assert "tkinter" not in PROBE_SOURCE.read_text(encoding="utf-8")


def test_the_plan_module_reimplements_nothing_it_consumes():
    tree = ast.parse(PLAN_SOURCE.read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for owned_elsewhere in ("validate_chapters", "plan_timeline", "segment_filename",
                            "flatten_title", "sanitize_component", "plan_flat",
                            "plan_mirrored", "plan_multi_root", "planning_groups",
                            "DestinationPlanner", "ChapterProbe", "select_attached_picture"):
        assert owned_elsewhere not in defined, owned_elsewhere


def test_no_phase_eleven_execution_lifecycle_exists():
    """Popen, terminate, kill, reap, staging and per-segment drift are next."""
    for path in (PANEL_SOURCE, PLAN_SOURCE, PROBE_SOURCE):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("Popen", "terminate(", "kill(", "send_signal",
                          "temporary_sibling", "atomic_replace", "discard_temporary",
                          "segment_argv", "attach_artwork_argv", "segment_commands"):
            assert forbidden not in text, (path.name, forbidden)


def test_no_success_number_allocator_exists():
    """Phase 12 owns success-only whole-book numbering."""
    text = PANEL_SOURCE.read_text(encoding="utf-8")
    for forbidden in ("success_number", "allocate_number", "_success_counter"):
        assert forbidden not in text, forbidden


def test_retry_failed_is_still_not_wired():
    """Structural: the adapter is handed neither a result nor a retry callback."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "set_result" not in called
    keywords = {keyword.arg for node in ast.walk(tree)
                if isinstance(node, ast.Call) for keyword in node.keywords}
    assert "on_retry" not in keywords


def test_the_panel_stays_classic():
    assert "ACT." not in PANEL_SOURCE.read_text(encoding="utf-8")


def test_split_execution_has_not_arrived(make_panel, tmp_path, run_env):
    """A multi-segment item is refused truthfully rather than half-converted."""
    panel = make_panel()
    add(panel, book(tmp_path / "src", "A.m4b"))
    params = start(panel)
    params["options"] = PlanOptions(mode=ConversionMode.SPLIT)
    run_env["default_report"] = report(duration=600.0,
                                       chapter_list=chapters(0.0, 200.0, 400.0))
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()

    assert panel.run_plan.total_segments == 3, "it was planned in full"
    assert run_env["commands"] == [], "and none of it was written"
    assert panel.run_result.failed_count == 1
    assert "cannot write yet" in "\n".join(panel.jobs.views.summary)


def test_the_panel_offers_only_the_mode_it_can_execute(make_panel):
    """The Split control arrives with the engine that can honour it."""
    panel = make_panel()
    assert not hasattr(panel, "var_mode")
    assert panel.read_options().mode is ConversionMode.WHOLE
