"""The Converter's chapter probe model — v0.6.2 Plan 5, Phase 1.

Phase 1 delivers result *types* and nothing else, so every test here runs without
media, without ffprobe and without Tk. What these pin is the contract later
phases build on:

* the four operational outcomes, kept distinct at the type level;
* immutability, so a frozen probe cannot be edited after it is produced;
* the one distinction the model exists for — a clean probe of a chapterless
  source is a success, and is never the same value as a probe that failed;
* the ownership boundary: the chapter vocabulary is Converter-local and does not
  leak into ``shared/ffmpeg_utils.py`` or change ``metadata.read_chapter_titles``.

Structural guards below also prove Phase 1 did **not** implement Phase 2's
validation or any later phase's behaviour.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from enum import Enum
from pathlib import Path

import pytest

from mp3_tools import m4b_chapters
from mp3_tools.m4b_chapters import ChapterProbe, ProbeStatus, SourceChapter

MODULE_PATH = Path(m4b_chapters.__file__)


# --------------------------------------------------------------------------- #
# ProbeStatus — exactly four outcomes, with the values the contract names
# --------------------------------------------------------------------------- #


def test_probe_status_has_exactly_the_four_approved_members():
    assert [member.name for member in ProbeStatus] == [
        "OK", "PROBE_FAILED", "NO_DURATION", "NO_AUDIO",
    ]


@pytest.mark.parametrize(("member", "value"), [
    (ProbeStatus.OK, "ok"),
    (ProbeStatus.PROBE_FAILED, "probe_failed"),
    (ProbeStatus.NO_DURATION, "no_duration"),
    (ProbeStatus.NO_AUDIO, "no_audio"),
])
def test_each_probe_status_carries_its_contract_value(member, value):
    assert member.value == value


def test_probe_status_is_an_enum():
    assert issubclass(ProbeStatus, Enum)


# --------------------------------------------------------------------------- #
# SourceChapter — immutable, start-only, title preserved verbatim
# --------------------------------------------------------------------------- #


def test_source_chapter_records_index_start_and_title():
    chapter = SourceChapter(index=0, start=0.0, title="Opening Credits")
    assert (chapter.index, chapter.start, chapter.title) == (0, 0.0, "Opening Credits")


def test_source_chapter_is_frozen():
    chapter = SourceChapter(index=1, start=41.062, title="Chapter 1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        chapter.start = 99.0


def test_source_chapter_has_no_end_time_field():
    """§11.3 partitions on starts and duration; an end time would be a second,
    disagreeable source of truth."""
    names = {f.name for f in dataclasses.fields(SourceChapter)}
    assert names == {"index", "start", "title"}


def test_a_blank_chapter_title_is_preserved_not_renamed():
    """Fallback naming is the naming phase's job, not the model's."""
    assert SourceChapter(index=3, start=10.0, title="").title == ""


def test_source_chapter_equality_is_by_value():
    a = SourceChapter(index=2, start=1.5, title="Two")
    b = SourceChapter(index=2, start=1.5, title="Two")
    assert a == b


# --------------------------------------------------------------------------- #
# ChapterProbe — immutability, tuple semantics, duration and detail
# --------------------------------------------------------------------------- #


def test_chapter_probe_is_frozen():
    probe = ChapterProbe(status=ProbeStatus.OK, duration=10.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        probe.status = ProbeStatus.PROBE_FAILED


def test_chapters_default_to_an_empty_tuple():
    probe = ChapterProbe(status=ProbeStatus.OK, duration=10.0)
    assert probe.chapters == ()
    assert isinstance(probe.chapters, tuple)


def test_a_supplied_list_of_chapters_becomes_a_tuple():
    """The type promises a tuple, so a caller that builds a list still gets one
    — the container is normalised, never the chapter values inside it."""
    built = [SourceChapter(index=0, start=0.0, title="A"),
             SourceChapter(index=1, start=5.0, title="B")]
    probe = ChapterProbe(status=ProbeStatus.OK, duration=9.0, chapters=built)
    assert isinstance(probe.chapters, tuple)
    assert probe.chapters == tuple(built)
    built.append(SourceChapter(index=2, start=7.0, title="C"))
    assert len(probe.chapters) == 2, "the probe must not alias the caller's list"


def test_detail_defaults_to_empty_and_can_carry_a_diagnostic():
    assert ChapterProbe(status=ProbeStatus.OK, duration=1.0).detail == ""
    failed = ChapterProbe(
        status=ProbeStatus.PROBE_FAILED, duration=None,
        detail="ffprobe exited 1: Invalid data found when processing input")
    assert "ffprobe exited 1" in failed.detail


@pytest.mark.parametrize("duration", [None, 0.0, 35199.624717])
def test_duration_represents_both_known_and_unknown_states(duration):
    assert ChapterProbe(status=ProbeStatus.OK, duration=duration).duration == duration


# --------------------------------------------------------------------------- #
# `ok` — the distinction this model exists to make
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", list(ProbeStatus))
def test_ok_is_true_only_for_the_ok_status(status):
    probe = ChapterProbe(status=status, duration=1.0)
    assert probe.ok is (status is ProbeStatus.OK)


def test_a_clean_probe_of_a_chapterless_source_is_a_success():
    """Decision 18A's fallback rests on this being OK, not a failure."""
    probe = ChapterProbe(status=ProbeStatus.OK, duration=1234.5, chapters=())
    assert probe.ok is True
    assert probe.chapters == ()
    assert probe.duration == 1234.5


def test_a_failed_probe_is_never_the_same_value_as_a_chapterless_success():
    """Both carry zero chapters; only the status tells them apart, which is why
    the model refuses to express failure as 'no chapters'."""
    chapterless = ChapterProbe(status=ProbeStatus.OK, duration=1234.5, chapters=())
    failed = ChapterProbe(status=ProbeStatus.PROBE_FAILED, duration=None, chapters=())
    assert chapterless.chapters == failed.chapters == ()
    assert chapterless != failed
    assert chapterless.ok is True and failed.ok is False


# --------------------------------------------------------------------------- #
# Phase 1 must NOT judge chapters — that is Phase 2
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("label", "chapters"), [
    ("negative start", (SourceChapter(0, -5.0, "before zero"),)),
    ("duplicate starts", (SourceChapter(0, 3.0, "a"), SourceChapter(1, 3.0, "b"))),
    ("non-monotonic", (SourceChapter(0, 10.0, "later"), SourceChapter(1, 2.0, "earlier"))),
    ("start beyond duration", (SourceChapter(0, 9999.0, "past the end"),)),
])
def test_structurally_invalid_chapters_are_representable_and_not_repaired(label, chapters):
    """Phase 2 rejects these. Phase 1 must carry them faithfully so a malformed
    source is never silently rewritten into a different book."""
    probe = ChapterProbe(status=ProbeStatus.OK, duration=100.0, chapters=chapters)
    assert probe.chapters == chapters, label
    assert probe.ok is True, "Phase 1 does not downgrade status on bad values"


# --------------------------------------------------------------------------- #
# Purity and ownership boundaries
# --------------------------------------------------------------------------- #


def _module_tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))


def _imported_roots() -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_probe_model_imports_only_the_standard_library_it_needs():
    assert _imported_roots() == {"__future__", "dataclasses", "enum"}


def test_the_probe_model_has_no_tk_dependency():
    roots = _imported_roots()
    assert not {"tkinter", "ttk"} & roots
    assert "tkinter" not in MODULE_PATH.read_text(encoding="utf-8")


def test_the_probe_model_performs_no_io_and_runs_no_subprocess():
    """Phase 1 is the shape of the answer, not the act of asking."""
    roots = _imported_roots()
    assert not {"subprocess", "os", "pathlib", "shutil", "socket", "urllib"} & roots
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in ("ffprobe(", "subprocess.", "open(", "Popen"):
        assert forbidden not in source, forbidden


def test_the_probe_model_is_converter_local():
    assert MODULE_PATH.parent.name == "mp3_tools"


def test_shared_ffmpeg_utils_gained_no_chapter_vocabulary():
    """The ownership boundary in §11.1: the shared module stays chapter-free."""
    from shared import ffmpeg_utils

    shared_source = Path(ffmpeg_utils.__file__).read_text(encoding="utf-8")
    assert "ChapterProbe" not in shared_source
    assert "ProbeStatus" not in shared_source
    assert "SourceChapter" not in shared_source
    for name in ("probe_chapters", "ProbeStatus", "ChapterProbe", "SourceChapter"):
        assert not hasattr(ffmpeg_utils, name), name


def test_the_metadata_chapter_title_helper_is_untouched():
    """``read_chapter_titles`` remains the Metadata Editor's titles-only helper."""
    from shared import metadata

    assert callable(metadata.read_chapter_titles)
    assert list(inspect.signature(metadata.read_chapter_titles).parameters) == ["path"]
    metadata_source = Path(metadata.__file__).read_text(encoding="utf-8")
    assert "ChapterProbe" not in metadata_source
    assert "m4b_chapters" not in metadata_source


def test_phase_one_did_not_implement_later_phase_responsibilities():
    """Names owned by Phases 2-13 must not exist yet in this module."""
    later = (
        "validate", "partition", "segment", "SegmentPlan", "ItemPlan",
        "ConversionPlan", "flatten_title", "segment_filename", "plan_",
        "include_subfolders", "ffmpeg_cmd",
    )
    exported = set(dir(m4b_chapters))
    for name in later:
        assert not any(name.lower() in attr.lower() for attr in exported
                       if not attr.startswith("__")), name


def test_the_converter_panel_is_unchanged_by_phase_one():
    """Production adoption belongs to later phases, so the panel must not yet
    import the model."""
    panel = MODULE_PATH.parent / "m4b_converter.py"
    source = panel.read_text(encoding="utf-8")
    assert "m4b_chapters" not in source
    assert "ChapterProbe" not in source
