"""The split-output naming seam — v0.6.2 Plan 5, Phase 4.

Two stages, and the order is the entire point. ``sanitize_component`` treats
``/`` and ``\\`` as path hierarchy and reduces anything path-like to its last
element, which is right for a path and silently destructive for a metadata title
that merely contains slashes. So separators become visible punctuation *first*,
and only then is a genuine single component handed to the shared sanitiser.

The mandatory regression below uses the real chapter title that exposed this: fed
to the sanitiser directly it collapses to ``"Please get off my hearse"``, losing
two thirds of the title and the order prefix with it.

Everything filename-safety-related — forbidden characters, reserved device names,
NFC, trailing dots and spaces, the length cap, extension preservation — belongs to
``sanitize_component`` and is only integration-checked here, not re-tested.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from mp3_tools import m4b_naming
from mp3_tools.m4b_naming import flatten_title, segment_filename
from shared import output_paths

MODULE_PATH = Path(m4b_naming.__file__)

#: The real title from the planning evidence. 43 of this fixture's 44 chapter
#: titles contain slashes, which is how the defect was found.
REAL_SLASH_TITLE = (
    "1 — There is no food here / Meg ate all the Swedish Fish "
    "/ Please get off my hearse"
)


# --------------------------------------------------------------------------- #
# flatten_title
# --------------------------------------------------------------------------- #


def test_plain_text_survives_unchanged():
    assert flatten_title("Opening Credits") == "Opening Credits"


def test_a_forward_slash_becomes_visible_punctuation():
    assert flatten_title("A / B / C") == "A - B - C"


def test_a_backslash_becomes_visible_punctuation():
    assert flatten_title(r"A \ B \ C") == "A - B - C"


def test_mixed_separators_preserve_every_portion():
    flattened = flatten_title(r"one / two \ three / four")
    for portion in ("one", "two", "three", "four"):
        assert portion in flattened
    assert "/" not in flattened and "\\" not in flattened


def test_slashes_without_surrounding_spaces_still_separate():
    assert flatten_title("A/B/C") == "A - B - C"


def test_repeated_whitespace_collapses():
    assert flatten_title("A     B\t\tC") == "A B C"


def test_leading_and_trailing_whitespace_disappears():
    assert flatten_title("   padded   ") == "padded"


def test_substitution_does_not_leave_doubled_spaces():
    assert flatten_title("A  /  B") == "A - B"


def test_nul_is_removed():
    assert flatten_title("A\x00B") == "AB"
    assert "\x00" not in flatten_title("\x00\x00")


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n", "\x00"])
def test_blank_input_flattens_to_blank(blank):
    assert flatten_title(blank) == ""


def test_a_falsey_title_is_tolerated():
    assert flatten_title(None) == ""  # type: ignore[arg-type]


def test_unicode_text_remains_meaningful():
    raw = "17 — Meg, don’t you dare—MEG!"
    assert flatten_title(raw) == raw


def test_flattening_performs_no_path_operation():
    """A title that looks like an absolute path is still just text."""
    assert flatten_title("/etc/passwd") == "- etc - passwd"
    assert flatten_title(r"C:\Windows\System32") == "C: - Windows - System32"


def test_the_real_title_keeps_all_three_portions():
    flattened = flatten_title(REAL_SLASH_TITLE)
    assert "There is no food here" in flattened
    assert "Meg ate all the Swedish Fish" in flattened
    assert "Please get off my hearse" in flattened
    assert "/" not in flattened


# --------------------------------------------------------------------------- #
# The mandatory slash-title regression
# --------------------------------------------------------------------------- #


def test_the_real_slash_title_produces_the_approved_filename():
    assert segment_filename(1, 44, REAL_SLASH_TITLE) == (
        "01 - 1 — There is no food here - Meg ate all the Swedish Fish "
        "- Please get off my hearse.mp3"
    )


def test_the_order_prefix_survives_a_slash_title():
    """Sanitising first would have eaten the prefix along with the title."""
    assert segment_filename(1, 44, REAL_SLASH_TITLE).startswith("01 - ")


def test_every_portion_of_the_slash_title_survives():
    produced = segment_filename(1, 44, REAL_SLASH_TITLE)
    for portion in ("There is no food here", "Meg ate all the Swedish Fish",
                    "Please get off my hearse"):
        assert portion in produced, portion


def test_the_naive_ordering_would_have_lost_the_title():
    """Documents the defect this seam exists to prevent."""
    naive = output_paths.sanitize_component(f"01 - {REAL_SLASH_TITLE}.mp3")
    assert naive == "Please get off my hearse.mp3"
    assert not naive.startswith("01 - ")
    assert segment_filename(1, 44, REAL_SLASH_TITLE) != naive


def test_the_slash_title_creates_no_path_hierarchy():
    produced = segment_filename(1, 44, REAL_SLASH_TITLE)
    assert "/" not in produced and "\\" not in produced
    assert Path(produced).name == produced, "must be exactly one component"
    assert len(Path(produced).parts) == 1


def test_the_slash_title_keeps_its_extension():
    assert segment_filename(1, 44, REAL_SLASH_TITLE).endswith(".mp3")


def test_the_backslash_analogue_behaves_identically():
    produced = segment_filename(1, 44, r"1 — a \ b \ c")
    assert produced == "01 - 1 — a - b - c.mp3"
    assert Path(produced).name == produced


def test_the_produced_name_is_valid_under_the_repository_rules():
    """Round-tripping through the sanitiser must be a no-op on a safe name."""
    produced = segment_filename(1, 44, REAL_SLASH_TITLE)
    assert output_paths.sanitize_component(produced) == produced


# --------------------------------------------------------------------------- #
# Approved examples
# --------------------------------------------------------------------------- #


def test_the_colon_example_comes_from_the_shared_sanitiser():
    assert segment_filename(3, 44, "Chapter 1: To Goldicia") == "03 - Chapter 1_ To Goldicia.mp3"
    assert ":" not in segment_filename(3, 44, "Chapter 1: To Goldicia")


@pytest.mark.parametrize("unusable", ["", "   ", "..", ".", "\x00", "\t\n"])
def test_an_unusable_title_falls_back_to_chapter_order(unusable):
    assert segment_filename(4, 44, unusable) == "04 - Chapter 4.mp3"


def test_the_fallback_tracks_the_order():
    assert segment_filename(7, 44, "") == "07 - Chapter 7.mp3"
    assert segment_filename(12, 44, "   ") == "12 - Chapter 12.mp3"


def test_a_windows_reserved_name_is_neutralised_by_the_sanitiser():
    assert segment_filename(6, 44, "CON") == "06 - _CON.mp3"


def test_a_three_hundred_character_title_is_capped_with_the_extension_intact():
    produced = segment_filename(8, 44, "A" * 300)
    assert len(produced) == output_paths.MAX_COMPONENT_LENGTH == 255
    assert produced.endswith(".mp3"), "the extension must not be truncated away"
    assert produced.startswith("08 - ")


# --------------------------------------------------------------------------- #
# Padding width
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("order", "total", "prefix"), [
    (1, 1, "01"), (1, 9, "01"), (9, 9, "09"),
    (1, 44, "01"), (9, 44, "09"), (10, 44, "10"), (44, 44, "44"),
    (9, 99, "09"), (99, 99, "99"),
    (9, 100, "009"), (100, 100, "100"),
    (9, 1000, "0009"), (1000, 1000, "1000"),
])
def test_padding_width_is_deterministic(order, total, prefix):
    assert segment_filename(order, total, "t").startswith(f"{prefix} - ")


def test_a_sub_hundred_total_always_uses_at_least_two_digits():
    for total in (1, 2, 5, 40, 99):
        assert segment_filename(1, total, "t").startswith("01 - ")


def test_numbering_is_rendered_not_allocated():
    """The seam holds no cross-item state: it renders exactly what it is given."""
    assert segment_filename(1, 44, "a").startswith("01 - ")
    assert segment_filename(1, 44, "b").startswith("01 - ")
    assert segment_filename(5, 44, "a").startswith("05 - ")


def test_order_numbers_restart_per_item():
    first_item = [segment_filename(i, 3, f"c{i}") for i in (1, 2, 3)]
    second_item = [segment_filename(i, 3, f"c{i}") for i in (1, 2, 3)]
    assert first_item == second_item


# --------------------------------------------------------------------------- #
# The shared sanitiser is consumed, not reimplemented
# --------------------------------------------------------------------------- #


def test_the_seam_calls_the_shared_sanitiser():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "from shared.output_paths import sanitize_component" in source
    assert source.count("sanitize_component(") >= 2, "body and whole-name passes"


def _string_literals() -> set[str]:
    """Every string constant the module actually *uses*, excluding docstrings.

    Checked structurally rather than by scanning source text, so prose that
    merely names a rule the sanitiser owns is never mistaken for an
    implementation of it. Docstrings are bare expression statements, so
    excluding ``Expr`` children removes them without string comparison.
    """
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
    prose = {
        id(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    return {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in prose
    }


def test_no_filename_safety_rule_is_hand_rolled_here():
    """The module may name these rules in prose; it must not implement them."""
    literals = _string_literals()
    reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "LPT1"}
    assert not (literals & reserved), literals & reserved
    for literal in literals:
        assert not set(literal) & set('<>:"|?*'), f"forbidden-char table: {literal!r}"

    source = MODULE_PATH.read_text(encoding="utf-8")
    for called in ("unicodedata", "normalize(", "MAX_COMPONENT_LENGTH", "casefold("):
        assert called not in source, called


def test_the_shared_sanitiser_itself_is_unchanged_by_this_phase():
    """Phase 4 consumes Plan 2's helper; it does not alter its contract."""
    assert inspect.signature(output_paths.sanitize_component).parameters.keys() == {
        "name", "fallback", "max_length"
    }
    shared_source = Path(output_paths.__file__).read_text(encoding="utf-8")
    for name in ("flatten_title", "segment_filename", "m4b_naming", "chapter"):
        assert name not in shared_source, name


def test_both_sanitiser_passes_are_kept():
    """The second pass is not redundant: only it sees the prefix and extension,
    so only it can enforce the length cap over the whole name."""
    produced = segment_filename(8, 44, "A" * 300)
    assert len(produced) <= output_paths.MAX_COMPONENT_LENGTH
    assert produced.endswith(".mp3")


# --------------------------------------------------------------------------- #
# Purity and ownership
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


def test_the_naming_seam_imports_only_future_and_the_shared_sanitiser():
    assert _imported_roots() == {"__future__", "shared"}


def test_the_naming_seam_is_pure():
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in ("subprocess", "Popen", "open(", "tkinter", "threading",
                      "queue", "logging", "Path(", "mkdir", "exists(",
                      "ffmpeg", "ffprobe", "DestinationPlanner",
                      "reserve_run_directory", "settings"):
        assert forbidden not in source, forbidden


def test_the_naming_seam_is_converter_local():
    assert MODULE_PATH.parent.name == "mp3_tools"


def test_no_phase_five_or_later_vocabulary_exists_here():
    for name in ("SegmentPlan", "ItemPlan", "ConversionPlan", "destination",
                 "include_subfolders", "argv", "-ss", "libmp3lame"):
        assert not any(name.lower() in attr.lower()
                       for attr in dir(m4b_naming) if not attr.startswith("__")), name


def test_naming_is_deterministic():
    assert segment_filename(1, 44, REAL_SLASH_TITLE) == segment_filename(1, 44, REAL_SLASH_TITLE)


# --------------------------------------------------------------------------- #
# Relationship to the Phase 3 timeline
# --------------------------------------------------------------------------- #


def test_chapter_span_gained_no_filename_or_destination():
    """Phase 3's spans stay raw geometry; naming is a separate scalar function."""
    import dataclasses

    from mp3_tools.m4b_chapters import ChapterSpan

    fields = {f.name for f in dataclasses.fields(ChapterSpan)}
    assert fields == {"order", "source_index", "start", "end", "title"}
    for absent in ("filename", "destination", "path", "name"):
        assert absent not in fields, absent


def test_a_span_title_can_be_named_without_touching_the_span():
    import copy

    from mp3_tools.m4b_chapters import ChapterProbe, ProbeStatus, SourceChapter, plan_timeline

    probe = ChapterProbe(ProbeStatus.OK, 100.0, (
        SourceChapter(0, 0.0, REAL_SLASH_TITLE),
        SourceChapter(1, 50.0, ""),
    ))
    spans = plan_timeline(probe)
    before = copy.deepcopy(spans)
    names = [segment_filename(s.order, len(spans), s.title) for s in spans]
    assert spans == before, "naming must not mutate the timeline"
    assert names[0].startswith("01 - 1 — There is no food here - ")
    assert names[1] == "02 - Chapter 2.mp3"


def test_the_converter_panel_is_still_not_integrated():
    source = (MODULE_PATH.parent / "m4b_converter.py").read_text(encoding="utf-8")
    for name in ("m4b_naming", "segment_filename", "flatten_title", "m4b_chapters"):
        assert name not in source, name
