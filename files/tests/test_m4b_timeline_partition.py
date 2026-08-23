"""Complete-timeline chapter-start partition — v0.6.2 Plan 5, Phase 3.

Decision 46A is absolute: **no positive source duration may disappear.** The
planner therefore partitions on chapter *starts* rather than chapter regions, so
that every instant from exactly ``0.0`` to exactly ``D`` lands in exactly one
output span:

    bounds    = [0.0, s2, s3, ..., sN, D]
    segment i = [bounds[i], bounds[i + 1])

Omitting ``s1`` from the bounds is the whole trick, and these tests exist mainly
to hold it in place. It is what puts pre-roll inside chapter 1 instead of
inventing an "Opening" file, keeps unchaptered gaps with the chapter they follow,
and lets trailing audio end at the real duration — all without a single special
case and without an epsilon anywhere.

Everything here is arithmetic on values, so it runs without media, ffprobe or Tk.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import math
from pathlib import Path

import pytest

from mp3_tools import m4b_chapters
from mp3_tools.m4b_chapters import (
    ChapterProbe,
    ChapterSpan,
    ProbeStatus,
    SourceChapter,
    TimelinePlanError,
    plan_timeline,
)

MODULE_PATH = Path(m4b_chapters.__file__)

#: Only ever used to compare a floating-point *total* against D. Never to move,
#: merge, trim or collapse a boundary — the boundaries are verbatim values.
TOTAL_TOLERANCE = 1e-9


def probe(duration: float, *starts: float, titles: tuple[str, ...] | None = None) -> ChapterProbe:
    names = titles if titles is not None else tuple(f"Chapter {i + 1}" for i in range(len(starts)))
    return ChapterProbe(
        status=ProbeStatus.OK,
        duration=duration,
        chapters=tuple(
            SourceChapter(index=i, start=s, title=names[i]) for i, s in enumerate(starts)
        ),
    )


def spans_of(*args, **kwargs) -> tuple[tuple[float, float], ...]:
    return tuple((s.start, s.end) for s in plan_timeline(probe(*args, **kwargs)))


def assert_invariants(segments: tuple[ChapterSpan, ...], duration: float, chapter_count: int):
    """All six §11.3 invariants, asserted structurally."""
    assert segments[0].start == 0.0, "the plan must begin at exactly 0.0"
    assert segments[-1].end == duration, "the plan must end at exactly D"
    for a, b in zip(segments, segments[1:]):
        assert a.end == b.start, "spans must be contiguous with no gap or overlap"
    total = math.fsum(s.end - s.start for s in segments)
    assert abs(total - duration) <= TOTAL_TOLERANCE, f"tiled {total} but D is {duration}"
    for s in segments:
        assert s.end - s.start > 0, "every span must have positive length"
    assert len(segments) == chapter_count, "one output per source chapter"


# --------------------------------------------------------------------------- #
# The normal chaptered case
# --------------------------------------------------------------------------- #


def test_the_documented_normal_case_partitions_exactly():
    assert spans_of(100.0, 0.0, 20.0, 50.0, 80.0) == (
        (0.0, 20.0), (20.0, 50.0), (50.0, 80.0), (80.0, 100.0),
    )


def test_output_count_equals_chapter_count():
    for starts in ((0.0,), (0.0, 10.0), (0.0, 10.0, 20.0, 30.0, 40.0)):
        assert len(plan_timeline(probe(100.0, *starts))) == len(starts)


def test_each_span_is_labelled_with_its_own_source_chapter():
    segments = plan_timeline(probe(100.0, 0.0, 20.0, 50.0))
    assert [s.title for s in segments] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert [s.source_index for s in segments] == [0, 1, 2]
    assert [s.order for s in segments] == [1, 2, 3]


def test_order_is_one_based_and_source_index_is_whatever_the_source_said():
    raw = ChapterProbe(ProbeStatus.OK, 100.0, (
        SourceChapter(index=7, start=0.0, title="seven"),
        SourceChapter(index=8, start=50.0, title="eight"),
    ))
    segments = plan_timeline(raw)
    assert [s.order for s in segments] == [1, 2]
    assert [s.source_index for s in segments] == [7, 8]


def test_span_duration_is_derived():
    segment = plan_timeline(probe(100.0, 0.0, 20.0))[0]
    assert segment.duration == segment.end - segment.start == 20.0


# --------------------------------------------------------------------------- #
# Pre-roll — the reason s1 is not a boundary
# --------------------------------------------------------------------------- #


def test_pre_roll_belongs_inside_chapter_one():
    """The documented case: first chapter starts at 41.062, and that audio is
    part of chapter 1's output rather than a separate file."""
    assert spans_of(100.0, 41.062, 60.0, 80.0) == (
        (0.0, 60.0), (60.0, 80.0), (80.0, 100.0),
    )


def test_no_synthetic_opening_segment_is_created():
    segments = plan_timeline(probe(100.0, 41.062, 60.0, 80.0))
    assert len(segments) == 3, "one output per source chapter, never N+1"
    assert all("opening" not in s.title.lower() for s in segments)
    assert segments[0].title == "Chapter 1"


def test_the_first_chapters_own_start_is_never_a_boundary():
    starts = [41.062, 60.0, 80.0]
    boundaries = {b for s in plan_timeline(probe(100.0, *starts)) for b in (s.start, s.end)}
    assert 41.062 not in boundaries
    assert 0.0 in boundaries and 100.0 in boundaries


def test_pre_roll_is_lossless():
    segments = plan_timeline(probe(100.0, 41.062, 60.0, 80.0))
    assert_invariants(segments, 100.0, 3)


# --------------------------------------------------------------------------- #
# Interior unchaptered audio and the tail
# --------------------------------------------------------------------------- #


def test_interior_time_stays_with_the_preceding_span():
    """Whatever the source thought a chapter's region was, the next boundary is
    the next chapter's start, so nothing between them can go missing."""
    segments = plan_timeline(probe(100.0, 0.0, 30.0, 70.0))
    assert (segments[0].start, segments[0].end) == (0.0, 30.0)
    assert (segments[1].start, segments[1].end) == (30.0, 70.0)
    assert_invariants(segments, 100.0, 3)


def test_the_final_span_ends_at_the_real_duration():
    segments = plan_timeline(probe(48123.24, 0.0, 100.0, 47000.0))
    assert segments[-1].end == 48123.24


def test_a_small_tail_is_kept_not_trimmed():
    """The planning evidence's ~0.046 s tail: the last chapter's native region
    stopped early, and that remainder still belongs to the final output."""
    duration = 73832.443356
    segments = plan_timeline(probe(duration, 0.0, 100.0, 72835.535737))
    assert segments[-1].end == duration
    assert segments[-1].end - segments[-1].start > 996.0
    assert_invariants(segments, duration, 3)


def test_a_tail_of_a_few_tens_of_milliseconds_is_not_discarded():
    duration = 100.046
    segments = plan_timeline(probe(duration, 0.0, 50.0, 99.9))
    assert segments[-1].start == 99.9 and segments[-1].end == duration
    assert segments[-1].duration == pytest.approx(0.146, abs=1e-12)
    assert_invariants(segments, duration, 3)


def test_no_epsilon_is_subtracted_from_the_end():
    duration = 12345.6789
    assert plan_timeline(probe(duration, 0.0, 10.0))[-1].end == duration


# --------------------------------------------------------------------------- #
# One chapter
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("only_start", [0.0, 41.062, 0.001, 99.999])
def test_a_single_chapter_always_yields_exactly_one_full_span(only_start):
    segments = plan_timeline(probe(100.0, only_start))
    assert len(segments) == 1
    assert (segments[0].start, segments[0].end) == (0.0, 100.0)
    assert segments[0].order == 1
    assert_invariants(segments, 100.0, 1)


def test_a_single_chapter_keeps_its_own_title():
    segments = plan_timeline(probe(100.0, 41.062, titles=("Only Chapter",)))
    assert segments[0].title == "Only Chapter"


# --------------------------------------------------------------------------- #
# Floating-point behaviour
# --------------------------------------------------------------------------- #


def test_ordinary_float_values_still_tile_exactly():
    duration = 35199.624717
    starts = (0.0, 41.062, 3121.526, 7606.973, 10142.999)
    segments = plan_timeline(probe(duration, *starts))
    assert_invariants(segments, duration, len(starts))
    assert segments[-1].end == duration


def test_boundaries_are_verbatim_values_not_computed_ones():
    """No arithmetic touches a boundary, so no float drift is possible."""
    starts = (0.0, 0.1, 0.2, 0.30000000000000004)
    duration = 0.7
    segments = plan_timeline(probe(duration, *starts))
    assert [s.start for s in segments] == [0.0, 0.1, 0.2, 0.30000000000000004]
    assert [s.end for s in segments] == [0.1, 0.2, 0.30000000000000004, 0.7]
    assert segments[-1].end == duration


def test_a_pathological_float_total_still_matches_d_within_tolerance():
    duration = 0.30000000000000004
    segments = plan_timeline(probe(duration, 0.0, 0.1, 0.2))
    assert_invariants(segments, duration, 3)


def test_many_chapters_tile_exactly():
    duration = 88703.585011
    starts = tuple(float(i) * 1887.3 for i in range(47))
    segments = plan_timeline(probe(duration, *starts))
    assert_invariants(segments, duration, 47)


# --------------------------------------------------------------------------- #
# Invariants across representative shapes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("duration", "starts"), [
    (100.0, (0.0,)),
    (100.0, (41.062,)),
    (100.0, (0.0, 50.0)),
    (100.0, (0.0, 20.0, 50.0, 80.0)),
    (48693.061678, (0.0, 17.566, 67.669, 2177.344, 2184.345)),
    (35199.625, tuple(float(i) * 2000.0 for i in range(15))),
    (48123.239909, tuple(float(i) * 1000.0 for i in range(44))),
])
def test_all_six_invariants_hold(duration, starts):
    assert_invariants(plan_timeline(probe(duration, *starts)), duration, len(starts))


def test_no_interval_of_the_source_is_missing_or_covered_twice():
    duration = 500.0
    starts = (0.0, 33.0, 120.5, 400.0)
    segments = plan_timeline(probe(duration, *starts))
    for probe_point in (0.0, 1.0, 32.999, 33.0, 120.5, 399.999, 400.0, 499.999):
        covering = [s for s in segments if s.start <= probe_point < s.end]
        assert len(covering) == 1, f"{probe_point} covered by {len(covering)} spans"


# --------------------------------------------------------------------------- #
# Title and order preservation — Phase 4 owns naming, not this phase
# --------------------------------------------------------------------------- #


def test_titles_are_carried_through_completely_raw():
    titles = ("", "  ", "1 — There is no food here / Meg ate all / Please get off my hearse",
              "Chapter 1: To Goldicia", "CON")
    segments = plan_timeline(probe(100.0, 0.0, 20.0, 40.0, 60.0, 80.0, titles=titles))
    assert [s.title for s in segments] == list(titles)


def test_a_slash_containing_title_is_not_flattened_here():
    raw = "1 — a / b / c"
    assert plan_timeline(probe(100.0, 0.0, titles=(raw,)))[0].title == raw


def test_a_blank_title_is_not_replaced_with_a_fallback():
    assert plan_timeline(probe(100.0, 0.0, titles=("",)))[0].title == ""


def test_unicode_titles_are_unchanged():
    raw = "17 — Meg, don’t you dare—MEG!"
    assert plan_timeline(probe(100.0, 0.0, titles=(raw,)))[0].title == raw


def test_source_order_is_preserved():
    titles = ("first", "second", "third", "fourth")
    segments = plan_timeline(probe(100.0, 0.0, 10.0, 20.0, 30.0, titles=titles))
    assert [s.title for s in segments] == list(titles)
    assert [s.order for s in segments] == [1, 2, 3, 4]


def test_no_filename_is_produced():
    segment = plan_timeline(probe(100.0, 0.0))[0]
    fields = {f.name for f in dataclasses.fields(ChapterSpan)}
    assert fields == {"order", "source_index", "start", "end", "title"}
    assert not any(".mp3" in str(getattr(segment, f)) for f in fields)


# --------------------------------------------------------------------------- #
# Routing: only CHAPTERED input can produce spans
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", [
    ProbeStatus.PROBE_FAILED, ProbeStatus.NO_DURATION, ProbeStatus.NO_AUDIO,
])
def test_an_unusable_status_cannot_produce_spans(status):
    with pytest.raises(TimelinePlanError):
        plan_timeline(ChapterProbe(status, None, ()))


@pytest.mark.parametrize("starts", [
    (-1.0,), (0.0, 5.0, 5.0), (0.0, 40.0, 20.0), (0.0, 500.0), (float("nan"),),
])
def test_structurally_invalid_chapters_cannot_produce_spans(starts):
    with pytest.raises(TimelinePlanError):
        plan_timeline(probe(100.0, *starts))


def test_a_chapterless_source_cannot_produce_split_spans():
    """Decision 18A's one-file fallback belongs to the run-plan layer, not here."""
    with pytest.raises(TimelinePlanError):
        plan_timeline(ChapterProbe(ProbeStatus.OK, 100.0, ()))


@pytest.mark.parametrize("duration", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_an_unusable_duration_cannot_produce_spans(duration):
    with pytest.raises(TimelinePlanError):
        plan_timeline(ChapterProbe(ProbeStatus.OK, duration, (SourceChapter(0, 0.0, "a"),)))


def test_the_refusal_carries_the_validation_that_caused_it():
    with pytest.raises(TimelinePlanError) as caught:
        plan_timeline(probe(100.0, 0.0, 5.0, 5.0))
    validation = caught.value.validation
    assert validation.usability is m4b_chapters.ChapterUsability.UNUSABLE
    assert validation.reason is m4b_chapters.InvalidReason.DUPLICATE_START


def test_the_planner_does_not_reimplement_validation():
    """It delegates: Phase 2 stays the single authority on usability."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    planner = source[source.index("def plan_timeline"):]
    assert "validate_chapters(" in planner
    for duplicated in ("isfinite", "< 0.0", ">= duration", "STARTS_OUT_OF_ORDER"):
        assert duplicated not in planner, duplicated


def test_the_planner_never_repairs_its_input():
    for starts in ((0.0, 40.0, 20.0), (0.0, 5.0, 5.0), (-1.0, 10.0)):
        raw = probe(100.0, *starts)
        before = copy.deepcopy(raw)
        with pytest.raises(TimelinePlanError):
            plan_timeline(raw)
        assert raw == before, "the probe must be untouched by a refused plan"


def test_a_valid_probe_is_not_mutated_by_planning():
    raw = probe(100.0, 0.0, 20.0, 50.0)
    before = copy.deepcopy(raw)
    plan_timeline(raw)
    assert raw == before


# --------------------------------------------------------------------------- #
# Value semantics and purity
# --------------------------------------------------------------------------- #


def test_chapter_span_is_frozen():
    segment = plan_timeline(probe(100.0, 0.0))[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        segment.end = 1.0


def test_the_plan_is_a_tuple():
    assert isinstance(plan_timeline(probe(100.0, 0.0, 20.0)), tuple)


def test_planning_is_deterministic():
    raw = probe(100.0, 0.0, 20.0, 50.0)
    assert plan_timeline(raw) == plan_timeline(raw)


def _imported_roots() -> set[str]:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_planner_stays_pure():
    roots = _imported_roots()
    assert not {"subprocess", "os", "pathlib", "shutil", "socket", "urllib",
                "threading", "queue", "logging", "tkinter", "shared"} & roots
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in ("subprocess.", "Popen", "open(", "tkinter", "Path(",
                      "ffprobe_cmd", "ffmpeg_cmd", "DestinationPlanner"):
        assert forbidden not in source, forbidden


def test_no_second_mutable_timeline_representation_exists():
    exported = [a for a in dir(m4b_chapters) if not a.startswith("_")]
    for name in exported:
        obj = getattr(m4b_chapters, name)
        if dataclasses.is_dataclass(obj) and isinstance(obj, type):
            assert obj.__dataclass_params__.frozen, f"{name} must be frozen"


def test_the_converter_panel_is_still_not_integrated():
    source = (MODULE_PATH.parent / "m4b_converter.py").read_text(encoding="utf-8")
    for name in ("m4b_chapters", "plan_timeline", "ChapterSpan"):
        assert name not in source, name


def test_shared_modules_gained_no_timeline_vocabulary():
    from shared import ffmpeg_utils, metadata

    for module in (ffmpeg_utils, metadata):
        text = Path(module.__file__).read_text(encoding="utf-8")
        for name in ("ChapterSpan", "plan_timeline", "TimelinePlanError"):
            assert name not in text, f"{module.__name__}: {name}"
            assert not hasattr(module, name), f"{module.__name__}: {name}"
