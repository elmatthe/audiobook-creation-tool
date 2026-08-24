"""Metadata modes, chapter retention and artwork — v0.6.2 Plan 5, Phase 6.

Six cells: Preserve / Replace / Strip, times whole book / split segment.

**The two findings these tests exist to hold in place.**

*Preserve is an allowlist, not ``-map_metadata 0``.* Measured against a real
audiobook, blanket copying put 23 format tags into the MP3 including
``AUDIBLE_DRM_TYPE=Adrm`` on a DRM-free file and the MP4 container brands
``major_brand`` / ``minor_version`` / ``compatible_brands`` on an MPEG audio
file. ``test_whole_preserve_never_becomes_blanket_metadata_copying`` fails if
anyone reintroduces it.

*A split segment needs two ffmpeg passes when the book has a cover.* The cover is
one frame at timestamp zero and the approved output-side ``-ss`` discards
everything before the segment start, so the audio pass cannot carry it. Five
single-command shapes were measured and all failed. The audio pass therefore
stays exactly as Phase 5 pinned it, and a stream-copy pass adds the picture.

The generated-media half builds tiny fixtures in ``tmp_path`` — including one
with an *ordinary* video stream ahead of where a cover would sit, which is the
case that catches a selector written as "the first video stream". No binary
fixture is committed, no private book is needed, and there is no skip: if ffmpeg
cannot run, the gate is red.
"""

from __future__ import annotations

import ast
import copy
import json
import subprocess
from pathlib import Path

import pytest

from mp3_tools import m4b_commands, m4b_metadata
from mp3_tools.m4b_metadata import (
    ArtworkSelectionError,
    AttachedPicture,
    ConversionCommands,
    MetadataMode,
    SourceTags,
    metadata_args,
    retains_chapters,
    segment_commands,
    segment_tags,
    select_attached_picture,
    wants_artwork,
    whole_book_commands,
    whole_book_tags,
)
from shared import ffmpeg_utils, metadata as shared_metadata

MODULE_PATH = Path(m4b_metadata.__file__)

# A source carrying everything the real fixtures carry, including the atoms that
# must never reach an output. Only the approved subset is representable in
# SourceTags at all — that is the first line of defence, and the adversarial
# values below prove the second.
SOURCE = SourceTags(
    title="THE WHOLE BOOK TITLE",
    artist="SRC ARTIST",
    album_artist="SRC ALBUM ARTIST",
    album="SRC ALBUM",
    track=3,
)
#: Distinctive source values that must never reach an output. Deliberately all
#: unambiguous strings: a bare "9" for a track total is untestable as a substring
#: because it occurs inside legitimate values, so totals are asserted separately
#: by :func:`assert_no_totals` instead of being guessed at by text search.
FORBIDDEN_VALUES = (
    "SRC COMMENT", "SRC GENRE", "1999", "SRC SERIES", "Adrm", "B0G1VBF1V7",
    "iso2mp41M4A M4B", "SRC PUBLISHER", "SRC NARRATOR", "SRC COPYRIGHT",
    "SRC SUBTITLE",
)


def assert_no_totals(tags: dict) -> None:
    """No ``3/9`` track total and no ``1/2`` disc total survived.

    ffmpeg writes both as ``number/total``, so the slash is the tell; the source
    fixture carries ``track=3/9`` and ``disc=1/2``.
    """
    for key, value in tags.items():
        assert "/" not in str(value), (key, value)
    assert "disc" not in tags


def require_ffmpeg() -> str:
    """The ffmpeg these tests run, or a loud verdict — never a skip.

    Same rule the Phase 5 remediation established: ffmpeg is a required
    dependency, so its absence is a broken environment and must turn the gate
    red rather than quietly removing this coverage from a passing run.
    """
    if not ffmpeg_utils.have_ffmpeg():
        pytest.fail(
            "ffmpeg/ffprobe could not be resolved, so the Phase 6 generated-media "
            "proof cannot run. This is a red gate, not a skip. "
            f"ffmpeg_path()={ffmpeg_utils.ffmpeg_path()!r}"
        )
    command = ffmpeg_utils.ffmpeg_cmd()
    try:
        probe = subprocess.run([command, "-version"], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    except OSError as exc:
        pytest.fail(f"{command!r} resolved but could not be launched: {exc!r}")
    if probe.returncode != 0:
        pytest.fail(f"{command!r} exited {probe.returncode} on '-version':\n{probe.stdout}")
    return command


# --------------------------------------------------------------------------- #
# Artwork selection
# --------------------------------------------------------------------------- #

AUDIO_STREAM = {"index": 0, "codec_type": "audio", "codec_name": "aac"}
DATA_STREAM = {"index": 1, "codec_type": "data", "codec_name": "bin_data"}
COVER_STREAM = {"index": 2, "codec_type": "video", "codec_name": "mjpeg",
                "disposition": {"attached_pic": 1}}
MOTION_STREAM = {"index": 1, "codec_type": "video", "codec_name": "h264",
                 "disposition": {"attached_pic": 0}}


def test_the_cover_is_found_by_disposition():
    picture = select_attached_picture([AUDIO_STREAM, DATA_STREAM, COVER_STREAM])
    assert picture == AttachedPicture(2, "mjpeg")


def test_an_ordinary_video_stream_is_never_artwork():
    """The case the real fixtures could not provide, and the one that matters.

    ``motion`` sits at index 1, *before* where a cover would be, so a selector
    written as "the first video stream" would pick it and put a moving picture
    where the book cover belongs.
    """
    assert select_attached_picture([AUDIO_STREAM, MOTION_STREAM]) is None


def test_an_ordinary_video_stream_does_not_shadow_a_real_cover():
    picture = select_attached_picture([AUDIO_STREAM, MOTION_STREAM,
                                       {**COVER_STREAM, "index": 2}])
    assert picture is not None and picture.stream_index == 2


def test_a_source_with_no_artwork_is_valid():
    assert select_attached_picture([AUDIO_STREAM, DATA_STREAM]) is None
    assert select_attached_picture([]) is None


def test_a_missing_disposition_is_not_artwork():
    assert select_attached_picture([{"index": 1, "codec_type": "video",
                                     "codec_name": "png"}]) is None


def cover(index: int, codec: str = "mjpeg") -> dict:
    return {"index": index, "codec_type": "video", "codec_name": codec,
            "disposition": {"attached_pic": 1}}


def test_two_covers_fail_closed_rather_than_guessing():
    """Ambiguity is a refusal, not a preference.

    Picking the lowest index would be an invented product rule: §17 requires
    artwork to be *positively identified*, and no real fixture inspected in
    Phase 6 carried more than one attached picture, so there is nothing to derive
    a rule from. Guessing would quietly put the wrong picture on a book.
    """
    with pytest.raises(ArtworkSelectionError):
        select_attached_picture([AUDIO_STREAM, cover(2), cover(3, "png")])


def test_the_two_cover_refusal_does_not_depend_on_stream_order():
    forward = [AUDIO_STREAM, cover(2, "mjpeg"), cover(5, "png")]
    reversed_ = [AUDIO_STREAM, cover(5, "png"), cover(2, "mjpeg")]
    for streams in (forward, reversed_):
        with pytest.raises(ArtworkSelectionError):
            select_attached_picture(streams)


@pytest.mark.parametrize("first, second", [
    ("mjpeg", "png"), ("png", "mjpeg"), ("mjpeg", "mjpeg"), ("png", "png")])
def test_no_codec_becomes_an_implicit_preference(first, second):
    with pytest.raises(ArtworkSelectionError):
        select_attached_picture([cover(2, first), cover(3, second)])


@pytest.mark.parametrize("indices", [(0, 1), (1, 9), (9, 1), (4, 4)])
def test_no_index_becomes_an_implicit_preference(indices):
    low, high = indices
    with pytest.raises(ArtworkSelectionError):
        select_attached_picture([cover(low), cover(high)])


def test_three_covers_also_fail_closed():
    with pytest.raises(ArtworkSelectionError):
        select_attached_picture([cover(2), cover(3), cover(4)])


def test_ambiguity_is_not_the_same_state_as_having_no_artwork():
    """``None`` means no cover exists; the error means one does and is ambiguous."""
    assert select_attached_picture([AUDIO_STREAM]) is None
    with pytest.raises(ArtworkSelectionError):
        select_attached_picture([AUDIO_STREAM, cover(2), cover(3)])


def test_the_refusal_reports_every_candidate_in_a_stable_order():
    """Ordering is for the diagnostic only — nothing selects from it."""
    with pytest.raises(ArtworkSelectionError) as caught:
        select_attached_picture([cover(7, "png"), cover(2, "mjpeg")])
    error = caught.value
    assert [p.stream_index for p in error.candidates] == [2, 7]
    assert [p.codec_name for p in error.candidates] == ["mjpeg", "png"]


def test_the_refusal_separates_message_from_detail():
    """Matches the repository's existing ``message``/``detail`` error shape."""
    with pytest.raises(ArtworkSelectionError) as caught:
        select_attached_picture([cover(2, "mjpeg"), cover(3, "png")])
    error = caught.value
    assert "more than one embedded cover" in error.message
    assert str(error) == error.message
    assert "#2 mjpeg" in error.detail and "#3 png" in error.detail
    # The human-readable half stays free of stream numbers.
    assert "#2" not in error.message


def test_a_refusal_does_not_mutate_the_stream_descriptors():
    streams = [AUDIO_STREAM, cover(2, "mjpeg"), cover(3, "png")]
    snapshot = copy.deepcopy(streams)
    with pytest.raises(ArtworkSelectionError):
        select_attached_picture(streams)
    assert streams == snapshot


def test_selection_does_not_mutate_the_stream_descriptors():
    streams = [AUDIO_STREAM, DATA_STREAM, COVER_STREAM]
    snapshot = copy.deepcopy(streams)
    assert select_attached_picture(streams) is not None
    assert streams == snapshot


def test_an_ordinary_video_stream_does_not_create_false_ambiguity():
    """Two video streams, only one of them a cover, is not ambiguous."""
    assert select_attached_picture([AUDIO_STREAM, MOTION_STREAM, cover(2)]) is not None


def test_attached_pictures_lists_candidates_without_choosing():
    assert m4b_metadata.attached_pictures([AUDIO_STREAM, MOTION_STREAM]) == ()
    assert len(m4b_metadata.attached_pictures([cover(2), cover(3)])) == 2


def test_the_selected_index_is_absolute_not_video_relative():
    """A cover at absolute index 2 is video stream 0; the two must not be confused."""
    assert select_attached_picture([AUDIO_STREAM, DATA_STREAM, COVER_STREAM]).stream_index == 2


@pytest.mark.parametrize("mode, expected", [
    (MetadataMode.PRESERVE, True), (MetadataMode.REPLACE, True),
    (MetadataMode.STRIP, False)])
def test_only_strip_refuses_artwork(mode, expected):
    assert wants_artwork(mode) is expected


# --------------------------------------------------------------------------- #
# Chapter map — the six D6A cells
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode, split, expected", [
    (MetadataMode.PRESERVE, False, True),    # whole preserve -> retained
    (MetadataMode.REPLACE, False, True),     # whole replace  -> retained (D6A)
    (MetadataMode.STRIP, False, False),
    (MetadataMode.PRESERVE, True, False),
    (MetadataMode.REPLACE, True, False),
    (MetadataMode.STRIP, True, False),
])
def test_the_six_chapter_cells(mode, split, expected):
    assert retains_chapters(mode, split=split) is expected


@pytest.mark.parametrize("mode, split, flag", [
    (MetadataMode.PRESERVE, False, "0"),
    (MetadataMode.REPLACE, False, "0"),
    (MetadataMode.STRIP, False, "-1"),
    (MetadataMode.PRESERVE, True, "-1"),
    (MetadataMode.REPLACE, True, "-1"),
    (MetadataMode.STRIP, True, "-1"),
])
def test_the_six_chapter_cells_reach_the_argv(mode, split, flag):
    args = metadata_args({}, keep_chapters=retains_chapters(mode, split=split))
    assert args[args.index("-map_chapters") + 1] == flag


def test_whole_replace_keeps_chapters_which_is_the_whole_of_d6a():
    """Replacing text does not invalidate navigation, so the map stays."""
    assert retains_chapters(MetadataMode.REPLACE, split=False) is True


# --------------------------------------------------------------------------- #
# Whole book
# --------------------------------------------------------------------------- #

def test_whole_preserve_carries_the_approved_source_fields():
    tags = whole_book_tags(MetadataMode.PRESERVE, source=SOURCE)
    assert tags == {"title": "THE WHOLE BOOK TITLE", "artist": "SRC ARTIST",
                    "album_artist": "SRC ALBUM ARTIST", "album": "SRC ALBUM", "track": 3}


def test_whole_preserve_lets_a_user_value_override_its_own_field():
    tags = whole_book_tags(MetadataMode.PRESERVE, source=SOURCE,
                           replacement={"album": "USER ALBUM"})
    assert tags["album"] == "USER ALBUM"
    assert tags["artist"] == "SRC ARTIST"


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_blank_override_does_not_erase_a_preserved_field(blank):
    tags = whole_book_tags(MetadataMode.PRESERVE, source=SOURCE,
                           replacement={"album": blank})
    assert tags["album"] == "SRC ALBUM"


def test_whole_replace_carries_no_source_metadata():
    tags = whole_book_tags(MetadataMode.REPLACE, source=SOURCE,
                           replacement={"album": "NEW ALBUM"})
    assert tags == {"album": "NEW ALBUM"}


def test_whole_replace_leaves_blank_fields_absent():
    tags = whole_book_tags(MetadataMode.REPLACE, source=SOURCE, replacement={"album": ""})
    assert tags == {}


def test_whole_strip_writes_nothing():
    assert whole_book_tags(MetadataMode.STRIP, source=SOURCE,
                           replacement={"album": "IGNORED"}, track=7) == {}


def test_whole_preserve_carries_a_track_number_but_no_total():
    """A source ``3/9`` contributes ``3``. A total describes a set, not this file."""
    tags = whole_book_tags(MetadataMode.PRESERVE, source=SOURCE)
    assert tags["track"] == 3
    assert "9" not in str(tags["track"])
    assert not any("/" in str(v) for v in tags.values())


def test_an_already_decided_track_may_be_supplied_but_is_never_allocated():
    """Phase 12 owns success-only numbering; this layer only renders what it is given."""
    assert whole_book_tags(MetadataMode.REPLACE, track=12)["track"] == 12
    assert "track" not in whole_book_tags(MetadataMode.REPLACE)


# --------------------------------------------------------------------------- #
# Split
# --------------------------------------------------------------------------- #

def test_split_preserve_inherits_only_book_identity():
    tags = segment_tags(MetadataMode.PRESERVE, title="Chapter One", order=1, source=SOURCE)
    assert tags == {"artist": "SRC ARTIST", "album_artist": "SRC ALBUM ARTIST",
                    "album": "SRC ALBUM", "title": "Chapter One", "track": 1}


def test_split_preserve_never_carries_the_whole_book_title():
    tags = segment_tags(MetadataMode.PRESERVE, title="Chapter One", order=1, source=SOURCE)
    assert tags["title"] == "Chapter One"
    assert "THE WHOLE BOOK TITLE" not in tags.values()


def test_split_preserve_never_carries_the_source_track_number():
    """The book's own track number describes the book, not chapter 1 of it."""
    tags = segment_tags(MetadataMode.PRESERVE, title="Ch", order=1, source=SOURCE)
    assert tags["track"] == 1


def test_split_replace_lets_the_segment_title_win():
    """Decision 47A: a replacement whole-book title must not become a segment's."""
    tags = segment_tags(MetadataMode.REPLACE, title="Chapter Four", order=4,
                        replacement={"title": "REPLACEMENT BOOK TITLE",
                                     "album": "NEW ALBUM"})
    assert tags["title"] == "Chapter Four"
    assert tags["track"] == 4
    assert tags["album"] == "NEW ALBUM"
    assert "REPLACEMENT BOOK TITLE" not in tags.values()


def test_split_replace_lets_the_segment_track_win():
    tags = segment_tags(MetadataMode.REPLACE, title="Ch", order=4,
                        replacement={"track": 99})
    assert tags["track"] == 4


def test_split_replace_carries_no_source_metadata():
    tags = segment_tags(MetadataMode.REPLACE, title="Ch", order=2, source=SOURCE,
                        replacement={"album": "NEW"})
    assert tags == {"album": "NEW", "title": "Ch", "track": 2}


def test_split_strip_regenerates_nothing():
    """Deliberately unlike the other two split modes: no title, no track."""
    assert segment_tags(MetadataMode.STRIP, title="Ch", order=3, source=SOURCE,
                        replacement={"album": "X"}) == {}


@pytest.mark.parametrize("mode", [MetadataMode.PRESERVE, MetadataMode.REPLACE])
def test_no_forbidden_source_value_can_reach_a_split_output(mode):
    tags = segment_tags(mode, title="Ch", order=1, source=SOURCE,
                        replacement={"comment": "SRC COMMENT", "genre": "SRC GENRE",
                                     "date": "1999", "SERIES": "SRC SERIES",
                                     "AUDIBLE_DRM_TYPE": "Adrm"})
    rendered = " ".join(str(v) for v in tags.values())
    for banned in ("SRC COMMENT", "SRC GENRE", "1999", "SRC SERIES", "Adrm"):
        assert banned not in rendered, banned


@pytest.mark.parametrize("mode", list(MetadataMode))
def test_only_approved_field_names_ever_appear(mode):
    for tags in (whole_book_tags(mode, source=SOURCE, replacement={"genre": "G", "comment": "C"}),
                 segment_tags(mode, title="T", order=1, source=SOURCE,
                              replacement={"genre": "G", "comment": "C"})):
        assert set(tags) <= {"title", "artist", "album_artist", "album", "track"}


# --------------------------------------------------------------------------- #
# The allowlist is structural, not incidental
# --------------------------------------------------------------------------- #

def tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))


def literals() -> set[str]:
    parsed = tree()
    docstrings = {id(node.value) for node in ast.walk(parsed)
                  if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)}
    return {node.value for node in ast.walk(parsed)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings}


def test_whole_preserve_never_becomes_blanket_metadata_copying():
    """The measured reason this guard exists.

    ``-map_metadata 0`` put ``AUDIBLE_DRM_TYPE=Adrm`` and the MP4 container
    brands into a real MP3. Every policy this module builds must therefore pin
    ``-map_metadata -1`` and name what it wants.
    """
    args = metadata_args({"album": "A"}, keep_chapters=True)
    assert args[args.index("-map_metadata") + 1] == "-1"


def test_every_mode_pins_map_metadata_to_minus_one():
    for mode in MetadataMode:
        for split in (True, False):
            args = metadata_args(
                whole_book_tags(mode, source=SOURCE) if not split
                else segment_tags(mode, title="T", order=1, source=SOURCE),
                keep_chapters=retains_chapters(mode, split=split))
            assert args[args.index("-map_metadata") + 1] == "-1"


def test_the_allowlist_is_exactly_the_shared_vocabulary():
    assert m4b_metadata.BOOK_FIELDS == shared_metadata._FFMPEG_TEXT_FIELDS
    assert m4b_metadata.FRAGMENT_INHERITED == ("artist", "album_artist", "album")


def test_no_out_of_vocabulary_field_name_is_mentioned():
    for banned in ("comment", "genre", "year", "series", "series_part", "composer",
                   "narrator", "publisher", "copyright", "disc", "subtitle",
                   "totaltracks", "language"):
        assert banned not in literals(), banned


def test_the_shared_mapping_is_consumed_not_reimplemented():
    called = {node.func.id for node in ast.walk(tree())
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "ffmpeg_metadata_args" in called
    # No second friendly-name -> ffmpeg-key table.
    for spelling in ("-metadata", "album_artist=", "title=", "track="):
        assert spelling not in literals(), spelling


def test_the_policy_layer_executes_and_probes_nothing():
    imported: set[str] = set()
    for node in ast.walk(tree()):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "collections", "dataclasses", "enum", "shared"}
    for banned in ("subprocess", "os", "pathlib", "tkinter", "threading", "shutil"):
        assert banned not in imported


def test_no_phase_eleven_lifecycle_or_phase_ten_plan_is_defined():
    defined = {node.name for node in ast.walk(tree())
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for banned in ("ConversionPlan", "ItemPlan", "SegmentPlan", "DestinationPlanner",
                   "reserve_run_directory", "terminate", "cancel"):
        assert banned not in defined


# --------------------------------------------------------------------------- #
# Command composition — one pass or two
# --------------------------------------------------------------------------- #

BASE = dict(ffmpeg="FF", source="BOOK.m4b", destination="OUT.mp3", quality=4)


def test_a_whole_book_is_always_one_pass():
    for mode in MetadataMode:
        cmds = whole_book_commands(mode, tags={}, picture=AttachedPicture(2, "mjpeg"), **BASE)
        assert cmds.artwork is None
        assert len(cmds.passes) == 1


def test_whole_preserve_maps_the_cover_into_the_single_pass():
    cmds = whole_book_commands(MetadataMode.PRESERVE, tags={},
                               picture=AttachedPicture(2, "mjpeg"), **BASE)
    assert "-map" in cmds.audio and "0:2" in cmds.audio
    assert "-vn" not in cmds.audio


def test_whole_strip_never_maps_a_cover_even_when_one_exists():
    cmds = whole_book_commands(MetadataMode.STRIP, tags={},
                               picture=AttachedPicture(2, "mjpeg"), **BASE)
    assert "-vn" in cmds.audio
    assert "attached_pic" not in cmds.audio


def test_a_whole_book_with_no_cover_keeps_the_original_audio_only_command():
    cmds = whole_book_commands(MetadataMode.PRESERVE, tags={}, picture=None, **BASE)
    assert "-vn" in cmds.audio and "-map" not in cmds.audio


SPLIT = dict(BASE, start=10.0, end=20.0, staged="STAGE.mp3")


@pytest.mark.parametrize("mode", [MetadataMode.PRESERVE, MetadataMode.REPLACE])
def test_a_split_segment_with_a_cover_needs_two_passes(mode):
    cmds = segment_commands(mode, tags={"title": "Ch"},
                            picture=AttachedPicture(2, "mjpeg"), **SPLIT)
    assert cmds.needs_artwork_pass
    assert len(cmds.passes) == 2


@pytest.mark.parametrize("mode", [MetadataMode.PRESERVE, MetadataMode.REPLACE])
def test_a_split_segment_with_no_cover_needs_only_one_pass(mode):
    """No pointless second invocation when the book has no artwork."""
    cmds = segment_commands(mode, tags={"title": "Ch"}, picture=None, **SPLIT)
    assert cmds.artwork is None and len(cmds.passes) == 1
    assert cmds.audio[-1] == "OUT.mp3"


def test_split_strip_never_runs_an_artwork_pass():
    cmds = segment_commands(MetadataMode.STRIP, tags={},
                            picture=AttachedPicture(2, "mjpeg"), **SPLIT)
    assert cmds.artwork is None and len(cmds.passes) == 1


def test_the_audio_pass_writes_the_staged_file_and_the_attach_pass_the_destination():
    cmds = segment_commands(MetadataMode.PRESERVE, tags={},
                            picture=AttachedPicture(2, "mjpeg"), **SPLIT)
    assert cmds.audio[-1] == "STAGE.mp3"
    assert cmds.artwork[-1] == "OUT.mp3"
    assert "STAGE.mp3" in cmds.artwork


def test_a_missing_staged_path_is_refused_rather_than_invented():
    with pytest.raises(ValueError):
        segment_commands(MetadataMode.PRESERVE, tags={},
                         picture=AttachedPicture(2, "mjpeg"),
                         **dict(BASE, start=1.0, end=2.0))


def test_the_audio_pass_never_carries_artwork():
    cmds = segment_commands(MetadataMode.PRESERVE, tags={},
                            picture=AttachedPicture(2, "mjpeg"), **SPLIT)
    assert "-vn" in cmds.audio
    assert "attached_pic" not in cmds.audio


# --------------------------------------------------------------------------- #
# Phase 5 stays locked
# --------------------------------------------------------------------------- #

def index(argv, token):
    assert token in argv, (token, argv)
    return list(argv).index(token)


@pytest.mark.parametrize("mode", list(MetadataMode))
def test_phase_five_seek_order_survives_every_mode(mode):
    cmds = segment_commands(mode, tags={"title": "Ch"},
                            picture=AttachedPicture(2, "mjpeg"), **SPLIT)
    argv = cmds.audio
    assert index(argv, "-ss") > index(argv, "-i")
    assert argv[index(argv, "-ss") + 1] == "10.000000"
    assert argv[index(argv, "-t") + 1] == "10.000000"
    assert "-to" not in argv


@pytest.mark.parametrize("mode", list(MetadataMode))
def test_the_xhe_decoder_stays_before_the_input_in_every_mode(mode):
    cmds = segment_commands(mode, tags={}, decoder_args=["-c:a", "aac_at"],
                            picture=AttachedPicture(2, "mjpeg"), **SPLIT)
    argv = cmds.audio
    assert argv[index(argv, "-i") - 2:index(argv, "-i")] == ("-c:a", "aac_at")
    assert argv.index("libmp3lame") > index(argv, "-i")


@pytest.mark.parametrize("mode", list(MetadataMode))
def test_the_encoder_contract_survives_every_mode(mode):
    for cmds in (whole_book_commands(mode, tags={}, **BASE),
                 segment_commands(mode, tags={}, **SPLIT)):
        assert "libmp3lame" in cmds.audio
        assert cmds.audio[index(cmds.audio, "-q:a") + 1] == "4"
        assert cmds.audio[index(cmds.audio, "-threads") + 1] == "0"
        assert "-b:a" not in cmds.audio


def test_metadata_policy_cannot_reach_the_input_option_region():
    """Everything Phase 6 emits lands after ``-i``, so it cannot change decoding."""
    cmds = segment_commands(MetadataMode.PRESERVE, tags={"title": "Ch"},
                            picture=AttachedPicture(2, "mjpeg"), **SPLIT)
    argv = cmds.audio
    boundary = index(argv, "-i")
    for token in ("-map_metadata", "-map_chapters", "-metadata"):
        if token in argv:
            assert index(argv, token) > boundary, token
    assert argv[1:4] == ("-hide_banner", "-y", "-i")


# --------------------------------------------------------------------------- #
# The attach pass
# --------------------------------------------------------------------------- #

def attach():
    return m4b_commands.attach_artwork_argv(
        ffmpeg="FF", audio="STAGE.mp3", artwork_source="BOOK.m4b",
        artwork_stream=2, destination="OUT.mp3")


def test_the_attach_pass_shape_is_exact():
    assert attach() == [
        "FF", "-hide_banner", "-y",
        "-i", "STAGE.mp3",
        "-i", "BOOK.m4b",
        "-map", "0:a:0",
        "-map", "1:2",
        "-c", "copy",
        "-disposition:v:0", "attached_pic",
        "-map_metadata", "0",
        "-map_chapters", "-1",
        "OUT.mp3",
    ]


def test_the_attach_pass_takes_metadata_from_the_sanitised_audio_not_the_book():
    """``-map_metadata 0`` is input 0 — the already-allowlisted Pass 1 output.

    The book is input 1 and is mapped for exactly one stream, so it can
    contribute no tags by any route.
    """
    argv = attach()
    assert argv[argv.index("-map_metadata") + 1] == "0"
    assert argv[4] == "STAGE.mp3", "input 0 must be the sanitised audio"
    assert argv[6] == "BOOK.m4b", "input 1 must be the book"
    book_maps = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-map"]
    assert [m for m in book_maps if m.startswith("1:")] == ["1:2"]


def test_the_attach_pass_cannot_emit_a_chapter_map():
    argv = attach()
    assert argv[argv.index("-map_chapters") + 1] == "-1"


def test_the_attach_pass_re_encodes_nothing():
    argv = attach()
    assert argv[argv.index("-c") + 1] == "copy"
    assert "libmp3lame" not in argv
    assert not any(tok.startswith("-q:a") for tok in argv)


def test_the_attach_pass_never_seeks():
    argv = attach()
    assert "-ss" not in argv and "-t" not in argv


@pytest.mark.parametrize("bad", [-1, "2", 2.0, True, None])
def test_a_nonsensical_artwork_stream_is_refused(bad):
    with pytest.raises((TypeError, ValueError)):
        m4b_commands.attach_artwork_argv(ffmpeg="FF", audio="A", artwork_source="B",
                                         artwork_stream=bad, destination="D")


# --------------------------------------------------------------------------- #
# Generated media — the policies against a real ffmpeg
# --------------------------------------------------------------------------- #

_META = (
    ";FFMETADATA1\ntitle=THE WHOLE BOOK TITLE\nartist=SRC ARTIST\nalbum=SRC ALBUM\n"
    "album_artist=SRC ALBUM ARTIST\ntrack=3/9\ndisc=1/2\ncomment=SRC COMMENT\n"
    "genre=SRC GENRE\ndate=1999\nSERIES=SRC SERIES\nAUDIBLE_DRM_TYPE=Adrm\n"
    "AUDIBLE_ASIN=B0G1VBF1V7\npublisher=SRC PUBLISHER\ncopyright=SRC COPYRIGHT\n"
    "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle=Ch One\n"
    "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=2000\nEND=4000\ntitle=Ch Two\n"
    "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=4000\nEND=6000\ntitle=Ch Three\n"
)


def _ff(*args):
    out = subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-y", *args],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert out.returncode == 0, out.stdout.decode("utf-8", "replace")[-800:]


def _probe(path, *args) -> dict:
    out = subprocess.run([ffmpeg_utils.ffprobe_cmd(), "-v", "error", *args,
                          "-of", "json", str(path)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    return json.loads(out.decode("utf-8", "replace"))


def _tags(path) -> dict:
    return _probe(path, "-show_format")["format"].get("tags", {})


def _chapters(path) -> int:
    return len(_probe(path, "-show_chapters")["chapters"])


def _apic(path) -> list:
    from mutagen.id3 import ID3
    try:
        return ID3(str(path)).getall("APIC")
    except Exception:
        return []


@pytest.fixture(scope="module")
def books(tmp_path_factory) -> dict[str, Path]:
    """Four tiny M4Bs: jpeg cover, png cover, no cover, ordinary video."""
    require_ffmpeg()
    w = tmp_path_factory.mktemp("m4b_meta")
    meta = w / "meta.txt"
    meta.write_text(_META, encoding="utf-8")
    _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:a", "aac",
        "-b:a", "64k", str(w / "a.m4a"))
    _ff("-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1", str(w / "c.jpg"))
    _ff("-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-frames:v", "1", str(w / "c.png"))
    _ff("-f", "lavfi", "-i", "testsrc=s=64x64:d=6:r=5", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", str(w / "m.mp4"))

    out: dict[str, Path] = {}
    for name, art in (("jpeg", w / "c.jpg"), ("png", w / "c.png")):
        dest = w / f"{name}.m4b"
        _ff("-i", str(w / "a.m4a"), "-i", str(art), "-i", str(meta),
            "-map", "0:a", "-map", "1:v", "-map_metadata", "2", "-map_chapters", "2",
            "-c:a", "copy", "-c:v", "copy", "-disposition:v:0", "attached_pic", str(dest))
        out[name] = dest
    dest = w / "noart.m4b"
    _ff("-i", str(w / "a.m4a"), "-i", str(meta), "-map", "0:a",
        "-map_metadata", "1", "-map_chapters", "1", "-c:a", "copy", str(dest))
    out["noart"] = dest
    dest = w / "motion.m4b"
    _ff("-i", str(w / "a.m4a"), "-i", str(w / "m.mp4"), "-i", str(meta),
        "-map", "0:a", "-map", "1:v", "-map_metadata", "2", "-map_chapters", "2",
        "-c:a", "copy", "-c:v", "copy", str(dest))
    out["motion"] = dest
    return out


def _picture(book: Path) -> AttachedPicture | None:
    return select_attached_picture(_probe(book, "-show_streams")["streams"])


def test_the_generated_books_are_shaped_as_intended(books):
    assert _picture(books["jpeg"]).codec_name == "mjpeg"
    assert _picture(books["png"]).codec_name == "png"
    assert _picture(books["noart"]) is None
    assert _picture(books["motion"]) is None, "ordinary video must not be seen as a cover"
    assert _chapters(books["jpeg"]) == 3


def test_the_ordinary_video_book_really_does_contain_video(books):
    """Otherwise the previous test would pass for the wrong reason."""
    kinds = [s["codec_type"] for s in _probe(books["motion"], "-show_streams")["streams"]]
    assert "video" in kinds


def _run(cmds: ConversionCommands):
    for argv in cmds.passes:
        out = subprocess.run(list(argv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert out.returncode == 0, out.stdout.decode("utf-8", "replace")[-800:]


@pytest.mark.parametrize("book", ["jpeg", "png"])
def test_whole_preserve_end_to_end(books, tmp_path, book):
    dest = tmp_path / f"whole_preserve_{book}.mp3"
    picture = _picture(books[book])
    tags = whole_book_tags(MetadataMode.PRESERVE, source=SOURCE)
    _run(whole_book_commands(MetadataMode.PRESERVE, ffmpeg=ffmpeg_utils.ffmpeg_cmd(),
                             source=books[book], destination=str(dest), quality=6,
                             tags=tags, picture=picture))
    got = _tags(dest)
    assert got.get("album") == "SRC ALBUM"
    assert _chapters(dest) == 3, "whole Preserve must retain the chapter map"
    assert got.get("track") == "3", "the source track number survives"
    assert_no_totals(got)
    assert len(_apic(dest)) == 1
    for banned in FORBIDDEN_VALUES:
        assert banned not in " ".join(got.values()), banned



@pytest.mark.parametrize("book", ["jpeg", "png"])
def test_whole_replace_end_to_end(books, tmp_path, book):
    dest = tmp_path / f"whole_replace_{book}.mp3"
    tags = whole_book_tags(MetadataMode.REPLACE, source=SOURCE,
                           replacement={"album": "NEW ALBUM", "artist": "NEW ARTIST"})
    _run(whole_book_commands(MetadataMode.REPLACE, ffmpeg=ffmpeg_utils.ffmpeg_cmd(),
                             source=books[book], destination=str(dest), quality=6,
                             tags=tags, picture=_picture(books[book])))
    got = _tags(dest)
    assert got.get("album") == "NEW ALBUM" and got.get("artist") == "NEW ARTIST"
    assert "THE WHOLE BOOK TITLE" not in " ".join(got.values())
    assert_no_totals(got)
    assert _chapters(dest) == 3, "D6A: whole Replace retains chapters"
    assert len(_apic(dest)) == 1, "D6A: whole Replace retains artwork"
    for banned in FORBIDDEN_VALUES:
        assert banned not in " ".join(got.values()), banned


def test_whole_strip_end_to_end(books, tmp_path):
    dest = tmp_path / "whole_strip.mp3"
    _run(whole_book_commands(MetadataMode.STRIP, ffmpeg=ffmpeg_utils.ffmpeg_cmd(),
                             source=books["jpeg"], destination=str(dest), quality=6,
                             tags=whole_book_tags(MetadataMode.STRIP, source=SOURCE),
                             picture=_picture(books["jpeg"])))
    got = _tags(dest)
    assert _chapters(dest) == 0
    assert _apic(dest) == []
    # Only ffmpeg's own muxer marker may remain.
    assert set(got) <= {"encoder"}, got


@pytest.mark.parametrize("book", ["jpeg", "png"])
def test_split_preserve_end_to_end_two_passes(books, tmp_path, book):
    dest = tmp_path / f"split_preserve_{book}.mp3"
    staged = tmp_path / f"split_preserve_{book}.stage.mp3"
    picture = _picture(books[book])
    cmds = segment_commands(
        MetadataMode.PRESERVE, ffmpeg=ffmpeg_utils.ffmpeg_cmd(), source=books[book],
        destination=str(dest), quality=6, start=2.0, end=4.0,
        tags=segment_tags(MetadataMode.PRESERVE, title="Ch Two", order=2, source=SOURCE),
        picture=picture, staged=str(staged))
    assert cmds.needs_artwork_pass
    _run(cmds)

    got = _tags(dest)
    assert got.get("title") == "Ch Two"
    assert got.get("track") == "2"
    assert got.get("album") == "SRC ALBUM"
    assert "THE WHOLE BOOK TITLE" not in " ".join(got.values())
    assert _chapters(dest) == 0, "a fragment must carry no chapter map"
    assert_no_totals(got)
    pics = _apic(dest)
    assert len(pics) == 1
    assert pics[0].mime == ("image/png" if book == "png" else "image/jpeg")
    for banned in FORBIDDEN_VALUES:
        assert banned not in " ".join(got.values()), banned


def test_split_replace_end_to_end(books, tmp_path):
    dest = tmp_path / "split_replace.mp3"
    staged = tmp_path / "split_replace.stage.mp3"
    cmds = segment_commands(
        MetadataMode.REPLACE, ffmpeg=ffmpeg_utils.ffmpeg_cmd(), source=books["jpeg"],
        destination=str(dest), quality=6, start=2.0, end=4.0,
        tags=segment_tags(MetadataMode.REPLACE, title="Ch Two", order=2,
                          replacement={"album": "NEW ALBUM",
                                       "title": "REPLACEMENT BOOK TITLE"}),
        picture=_picture(books["jpeg"]), staged=str(staged))
    _run(cmds)
    got = _tags(dest)
    assert got.get("title") == "Ch Two", "the segment title must win over a book title"
    assert "REPLACEMENT BOOK TITLE" not in " ".join(got.values())
    assert got.get("album") == "NEW ALBUM"
    assert got.get("track") == "2"
    assert_no_totals(got)
    assert _chapters(dest) == 0
    assert len(_apic(dest)) == 1


def test_split_strip_end_to_end_single_pass(books, tmp_path):
    dest = tmp_path / "split_strip.mp3"
    cmds = segment_commands(
        MetadataMode.STRIP, ffmpeg=ffmpeg_utils.ffmpeg_cmd(), source=books["jpeg"],
        destination=str(dest), quality=6, start=2.0, end=4.0,
        tags=segment_tags(MetadataMode.STRIP, title="Ch Two", order=2, source=SOURCE),
        picture=_picture(books["jpeg"]), staged=str(tmp_path / "unused.mp3"))
    assert not cmds.needs_artwork_pass
    _run(cmds)
    assert set(_tags(dest)) <= {"encoder"}
    assert _chapters(dest) == 0
    assert _apic(dest) == []
    assert not (tmp_path / "unused.mp3").exists(), "no second pass, so no staged file"


@pytest.mark.parametrize("mode", [MetadataMode.PRESERVE, MetadataMode.REPLACE])
def test_a_no_art_source_splits_successfully_with_no_artwork(books, tmp_path, mode):
    dest = tmp_path / f"noart_{mode.value}.mp3"
    cmds = segment_commands(
        mode, ffmpeg=ffmpeg_utils.ffmpeg_cmd(), source=books["noart"],
        destination=str(dest), quality=6, start=2.0, end=4.0,
        tags=segment_tags(mode, title="Ch Two", order=2, source=SOURCE),
        picture=_picture(books["noart"]))
    assert len(cmds.passes) == 1
    _run(cmds)
    assert dest.exists() and _apic(dest) == []
    assert _tags(dest).get("title") == "Ch Two"


def test_an_ordinary_video_stream_never_becomes_artwork_in_a_real_output(books, tmp_path):
    dest = tmp_path / "motion_out.mp3"
    cmds = whole_book_commands(MetadataMode.PRESERVE, ffmpeg=ffmpeg_utils.ffmpeg_cmd(),
                               source=books["motion"], destination=str(dest), quality=6,
                               tags={"album": "A"}, picture=_picture(books["motion"]))
    _run(cmds)
    assert _apic(dest) == []
    kinds = [s["codec_type"] for s in _probe(dest, "-show_streams")["streams"]]
    assert "video" not in kinds


def test_the_attach_pass_leaves_the_segment_audio_bit_identical(books, tmp_path):
    """Stream copy must not touch the audio the Phase 5 shape produced."""
    staged = tmp_path / "integrity.stage.mp3"
    dest = tmp_path / "integrity.mp3"
    cmds = segment_commands(
        MetadataMode.PRESERVE, ffmpeg=ffmpeg_utils.ffmpeg_cmd(), source=books["jpeg"],
        destination=str(dest), quality=6, start=2.0, end=4.0,
        tags=segment_tags(MetadataMode.PRESERVE, title="Ch", order=1, source=SOURCE),
        picture=_picture(books["jpeg"]), staged=str(staged))
    _run(cmds)

    def pcm(path) -> bytes:
        return subprocess.run(
            [ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-i", str(path),
             "-map", "0:a:0", "-f", "s16le", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout

    before, after = pcm(staged), pcm(dest)
    assert before == after, (len(before), len(after))
    assert _probe(dest, "-show_streams")["streams"][0]["codec_name"] == "mp3"
