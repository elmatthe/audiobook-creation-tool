"""Structural chapter validation — v0.6.2 Plan 5, Phase 2.

Phase 1 gave the Converter a faithful record of what a source *said* about its
chapters. Phase 2 decides whether what it said can be used, reading **starts and
duration only** and repairing nothing.

Three outcomes, and the boundaries between them are what these tests pin:

* **chaptered** — a clean probe, a real duration, strictly increasing starts
  inside it;
* **chapterless** — a clean probe with no chapters at all, which Decision 18A
  treats as a success, never as corruption;
* **unusable** — everything else, each with a reason that survives to the report.

The most important property here is negative: a malformed map is **refused**, not
sorted, clamped, dropped, deduplicated or renamed into something that would pass,
and it never reaches the chapterless path. Every test runs without media, ffprobe
or Tk.
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
    ChapterUsability,
    ChapterValidation,
    InvalidReason,
    ProbeStatus,
    SourceChapter,
    validate_chapters,
)

MODULE_PATH = Path(m4b_chapters.__file__)


def chapters(*starts: float) -> tuple[SourceChapter, ...]:
    return tuple(
        SourceChapter(index=i, start=s, title=f"Chapter {i + 1}")
        for i, s in enumerate(starts)
    )


def ok_probe(duration: float | None = 100.0, *starts: float) -> ChapterProbe:
    return ChapterProbe(status=ProbeStatus.OK, duration=duration,
                        chapters=chapters(*starts))


# --------------------------------------------------------------------------- #
# The three outcomes
# --------------------------------------------------------------------------- #


def test_a_clean_probe_with_no_chapters_is_chapterless_and_usable():
    """Decision 18A: an empty chapter map is a success, not corruption."""
    result = validate_chapters(ok_probe(1234.5))
    assert result.usability is ChapterUsability.CHAPTERLESS
    assert result.usable is True
    assert result.chapterless is True and result.chaptered is False
    assert result.reason is None


def test_a_single_valid_chapter_is_structurally_usable():
    result = validate_chapters(ok_probe(100.0, 0.0))
    assert result.usability is ChapterUsability.CHAPTERED
    assert result.usable is True and result.chaptered is True
    assert result.reason is None


def test_several_strictly_increasing_starts_inside_the_duration_are_usable():
    result = validate_chapters(ok_probe(48123.24, 0.0, 41.062, 3121.526, 7606.973))
    assert result.usability is ChapterUsability.CHAPTERED
    assert result.reason is None


def test_a_first_chapter_starting_after_zero_is_still_valid():
    """Pre-roll is Phase 3's to place; it is not a structural defect."""
    assert validate_chapters(ok_probe(100.0, 41.062, 60.0)).chaptered is True


@pytest.mark.parametrize(("status", "reason"), [
    (ProbeStatus.PROBE_FAILED, InvalidReason.PROBE_FAILED),
    (ProbeStatus.NO_DURATION, InvalidReason.NO_DURATION),
    (ProbeStatus.NO_AUDIO, InvalidReason.NO_AUDIO),
])
def test_every_non_ok_status_is_unusable_with_its_own_reason(status, reason):
    probe = ChapterProbe(status=status, duration=None)
    result = validate_chapters(probe)
    assert result.usability is ChapterUsability.UNUSABLE
    assert result.usable is False
    assert result.reason is reason


def test_a_failed_probe_is_never_routed_to_the_chapterless_path():
    """Both carry zero chapters; only the status separates them, and a failure
    must not become a whole-book conversion of a file that was never read."""
    failed = validate_chapters(ChapterProbe(ProbeStatus.PROBE_FAILED, None, ()))
    clean = validate_chapters(ChapterProbe(ProbeStatus.OK, 10.0, ()))
    assert failed.usability is ChapterUsability.UNUSABLE
    assert clean.usability is ChapterUsability.CHAPTERLESS
    assert failed.chapterless is False


# --------------------------------------------------------------------------- #
# Duration must be able to bound a real [0, D] span
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("duration", [
    None, 0.0, -1.0, -0.001, float("nan"), float("inf"), float("-inf"),
])
def test_an_ok_probe_without_a_usable_duration_is_unusable(duration):
    """Reached through the existing NO_DURATION semantic rather than a new rule."""
    result = validate_chapters(ChapterProbe(ProbeStatus.OK, duration, ()))
    assert result.usability is ChapterUsability.UNUSABLE
    assert result.reason is InvalidReason.NO_DURATION


def test_a_tiny_positive_duration_is_still_usable():
    assert validate_chapters(ChapterProbe(ProbeStatus.OK, 0.001, ())).usable is True


def test_an_unusable_duration_beats_the_chapterless_shortcut():
    """Zero chapters must not excuse a timeline that cannot exist."""
    result = validate_chapters(ChapterProbe(ProbeStatus.OK, None, ()))
    assert result.chapterless is False
    assert result.reason is InvalidReason.NO_DURATION


# --------------------------------------------------------------------------- #
# Structural defects in the starts
# --------------------------------------------------------------------------- #


def test_a_negative_first_start_fails():
    result = validate_chapters(ok_probe(100.0, -0.5, 10.0))
    assert result.reason is InvalidReason.START_BEFORE_ZERO
    assert result.usable is False


def test_a_negative_later_start_fails():
    result = validate_chapters(ok_probe(100.0, 0.0, -3.0))
    assert result.reason is InvalidReason.START_BEFORE_ZERO


def test_a_start_exactly_at_the_duration_fails():
    """A chapter beginning at D has no audio after it."""
    result = validate_chapters(ok_probe(100.0, 0.0, 100.0))
    assert result.reason is InvalidReason.START_AT_OR_BEYOND_DURATION


def test_a_start_beyond_the_duration_fails():
    result = validate_chapters(ok_probe(100.0, 0.0, 250.0))
    assert result.reason is InvalidReason.START_AT_OR_BEYOND_DURATION


def test_a_start_just_inside_the_duration_is_accepted():
    assert validate_chapters(ok_probe(100.0, 0.0, 99.999)).chaptered is True


def test_duplicate_starts_fail():
    result = validate_chapters(ok_probe(100.0, 0.0, 30.0, 30.0))
    assert result.reason is InvalidReason.DUPLICATE_START


def test_non_monotonic_starts_fail():
    result = validate_chapters(ok_probe(100.0, 0.0, 40.0, 20.0))
    assert result.reason is InvalidReason.STARTS_OUT_OF_ORDER


def test_duplicate_and_out_of_order_are_reported_distinctly():
    duplicate = validate_chapters(ok_probe(100.0, 10.0, 10.0))
    backwards = validate_chapters(ok_probe(100.0, 10.0, 9.0))
    assert duplicate.reason is not backwards.reason


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_start_fails(bad):
    """NaN compares false against every range and ordering test, so it is caught
    explicitly rather than being allowed to slip through as 'valid'."""
    result = validate_chapters(ok_probe(100.0, bad))
    assert result.reason is InvalidReason.START_NOT_FINITE
    assert result.usable is False


def test_a_non_finite_start_later_in_the_map_also_fails():
    assert validate_chapters(ok_probe(100.0, 0.0, float("nan"))).reason \
        is InvalidReason.START_NOT_FINITE


def test_malformed_structure_never_reaches_the_chapterless_path():
    for probe in (ok_probe(100.0, -1.0), ok_probe(100.0, 5.0, 5.0),
                  ok_probe(100.0, 5.0, 1.0), ok_probe(100.0, 500.0)):
        result = validate_chapters(probe)
        assert result.usability is ChapterUsability.UNUSABLE
        assert result.chapterless is False


# --------------------------------------------------------------------------- #
# Nothing is repaired — the heart of §11.2
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("label", "starts"), [
    ("out of order", (0.0, 40.0, 20.0)),
    ("duplicates", (0.0, 30.0, 30.0)),
    ("negative", (-5.0, 10.0)),
    ("beyond duration", (0.0, 900.0)),
])
def test_the_input_probe_is_never_mutated_by_validation(label, starts):
    probe = ok_probe(100.0, *starts)
    before = copy.deepcopy(probe)
    validate_chapters(probe)
    assert probe == before, label
    assert probe.chapters == before.chapters
    assert [c.start for c in probe.chapters] == list(starts), "starts were moved"


def test_a_malformed_map_is_not_sorted():
    probe = ok_probe(100.0, 40.0, 20.0, 60.0)
    validate_chapters(probe)
    assert [c.start for c in probe.chapters] == [40.0, 20.0, 60.0]


def test_a_malformed_map_is_not_clamped():
    probe = ok_probe(100.0, -10.0, 500.0)
    validate_chapters(probe)
    assert [c.start for c in probe.chapters] == [-10.0, 500.0]


def test_a_malformed_map_is_not_deduplicated():
    probe = ok_probe(100.0, 10.0, 10.0, 10.0)
    validate_chapters(probe)
    assert len(probe.chapters) == 3


def test_no_chapter_is_dropped_or_synthesised():
    probe = ok_probe(100.0, 0.0, 40.0, 20.0)
    validate_chapters(probe)
    assert len(probe.chapters) == 3
    assert [c.index for c in probe.chapters] == [0, 1, 2]


def test_titles_are_never_touched_including_blanks():
    probe = ChapterProbe(ProbeStatus.OK, 100.0, (
        SourceChapter(0, 0.0, ""),
        SourceChapter(1, 10.0, "  "),
        SourceChapter(2, 20.0, "1 - a / b / c"),
    ))
    validate_chapters(probe)
    assert [c.title for c in probe.chapters] == ["", "  ", "1 - a / b / c"]


def test_a_blank_title_is_not_a_structural_defect():
    probe = ChapterProbe(ProbeStatus.OK, 100.0, (SourceChapter(0, 0.0, ""),))
    assert validate_chapters(probe).chaptered is True


def test_the_validator_returns_a_verdict_not_a_corrected_copy():
    """No second, possibly divergent copy of the chapter list exists."""
    fields = {f.name for f in dataclasses.fields(ChapterValidation)}
    assert "chapters" not in fields
    assert fields == {"usability", "reason", "message", "detail"}


# --------------------------------------------------------------------------- #
# Result vocabulary
# --------------------------------------------------------------------------- #


def test_chapter_validation_is_frozen():
    result = validate_chapters(ok_probe(100.0, 0.0))
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.usability = ChapterUsability.UNUSABLE


def test_usability_has_exactly_three_members():
    assert [m.name for m in ChapterUsability] == ["CHAPTERED", "CHAPTERLESS", "UNUSABLE"]


def test_every_invalid_reason_is_reachable_and_distinct():
    reached = {
        validate_chapters(ChapterProbe(ProbeStatus.PROBE_FAILED, None)).reason,
        validate_chapters(ChapterProbe(ProbeStatus.NO_DURATION, None)).reason,
        validate_chapters(ChapterProbe(ProbeStatus.NO_AUDIO, None)).reason,
        validate_chapters(ok_probe(100.0, float("nan"))).reason,
        validate_chapters(ok_probe(100.0, -1.0)).reason,
        validate_chapters(ok_probe(100.0, 100.0)).reason,
        validate_chapters(ok_probe(100.0, 5.0, 5.0)).reason,
        validate_chapters(ok_probe(100.0, 5.0, 1.0)).reason,
    }
    assert reached == set(InvalidReason)


def test_a_usable_verdict_carries_no_reason_and_no_message():
    for probe in (ok_probe(100.0), ok_probe(100.0, 0.0, 10.0)):
        result = validate_chapters(probe)
        assert result.reason is None
        assert result.message == "" and result.detail == ""


def test_every_failure_carries_a_person_readable_message_and_a_technical_detail():
    for probe in (ChapterProbe(ProbeStatus.PROBE_FAILED, None),
                  ChapterProbe(ProbeStatus.NO_AUDIO, None),
                  ok_probe(100.0, -1.0),
                  ok_probe(100.0, 5.0, 5.0)):
        result = validate_chapters(probe)
        assert result.message and not result.message.endswith(" ")
        assert result.detail, "a failure must say what was wrong technically"
        assert "\n" not in result.message, "the message is one line, for a dialog"


def test_the_technical_detail_names_the_offending_chapter():
    detail = validate_chapters(ok_probe(100.0, 0.0, 40.0, 20.0)).detail
    assert "20.0" in detail and "40.0" in detail


def test_validation_is_deterministic():
    probe = ok_probe(100.0, 0.0, 40.0, 20.0)
    assert validate_chapters(probe) == validate_chapters(probe)


# --------------------------------------------------------------------------- #
# Purity and phase boundaries
# --------------------------------------------------------------------------- #


def _imported_roots() -> set[str]:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_validator_stays_pure():
    roots = _imported_roots()
    assert not {"subprocess", "os", "pathlib", "shutil", "socket", "urllib",
                "threading", "queue", "logging", "tkinter"} & roots
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in ("subprocess.", "Popen", "open(", "tkinter", "ffprobe_cmd", "ffmpeg_cmd"):
        assert forbidden not in source, forbidden


def test_the_validator_does_not_import_shared_foundations():
    """A pure validator must not reach for job control or the importer."""
    roots = _imported_roots()
    assert "shared" not in roots


def test_phase_three_partitioning_does_not_exist_yet():
    """The complete-timeline partition is Phase 3 and its own approval gate."""
    for name in ("partition", "segment", "SegmentPlan", "bounds", "ItemPlan",
                 "ConversionPlan", "plan_timeline"):
        assert not any(name.lower() in attr.lower()
                       for attr in dir(m4b_chapters) if not attr.startswith("__")), name


def test_the_validator_computes_no_spans():
    """Structurally valid data is merely accepted *for* later partitioning; the
    verdict carries no start/end pair of its own."""
    result = validate_chapters(ok_probe(100.0, 0.0, 40.0))
    assert not hasattr(result, "segments")
    assert not hasattr(result, "bounds")


def test_the_converter_panel_is_still_not_integrated():
    panel = MODULE_PATH.parent / "m4b_converter.py"
    source = panel.read_text(encoding="utf-8")
    assert "m4b_chapters" not in source
    assert "validate_chapters" not in source


def test_shared_ffmpeg_utils_still_has_no_chapter_or_validation_vocabulary():
    from shared import ffmpeg_utils

    shared_source = Path(ffmpeg_utils.__file__).read_text(encoding="utf-8")
    for name in ("ChapterProbe", "ChapterValidation", "validate_chapters",
                 "InvalidReason", "ChapterUsability"):
        assert name not in shared_source, name
        assert not hasattr(ffmpeg_utils, name), name


def test_the_metadata_chapter_title_helper_is_still_untouched():
    from shared import metadata

    metadata_source = Path(metadata.__file__).read_text(encoding="utf-8")
    assert "m4b_chapters" not in metadata_source
    assert "validate_chapters" not in metadata_source
    assert callable(metadata.read_chapter_titles)
