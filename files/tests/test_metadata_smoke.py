"""Behaviour preservation: shared metadata helpers used by the M4B Maker /
Converter / Metadata Editor (pure — no files, no ffmpeg)."""

from __future__ import annotations

from shared import metadata


def test_ffmpeg_metadata_args_emits_only_nonempty_fields():
    args = metadata.ffmpeg_metadata_args(
        {"title": "Book", "artist": "", "album": None, "track": 3}
    )
    assert args == ["-metadata", "title=Book", "-metadata", "track=3"]


def test_ffmetadata_header_lines_stable_order():
    tags = {"album": "Set", "title": "Book", "artist": "Narrator"}
    lines = metadata.ffmetadata_header_lines(tags)
    # Deterministic field order, only non-empty fields, key=value shape.
    assert lines == [f"{k}={v}" for k, v in
                     [(l.split("=", 1)[0], l.split("=", 1)[1]) for l in lines]]
    assert set(lines) == {"title=Book", "artist=Narrator", "album=Set"}
    assert metadata.ffmetadata_header_lines({}) == []


def test_freeform_namespace_parsing():
    assert metadata._freeform_namespace("----:com.apple.iTunes:SERIES") == "com.apple.iTunes"
    assert metadata._freeform_namespace("----:com.pilabor.tone:SERIES-PART") == "com.pilabor.tone"
    assert metadata._freeform_namespace("©nam") == ""


def test_series_atom_constants_match_audiobookshelf_contract():
    # Audiobookshelf's ffprobe scanner reads these exact freeform atoms —
    # regression-guard the constants the whole series feature hangs on.
    assert metadata.SERIES_ATOM == "----:com.apple.iTunes:SERIES"
    assert metadata.SERIES_PART_ATOM == "----:com.apple.iTunes:SERIES-PART"


# --------------------------------------------------------------------------- #
# _chapter_track_samples -- the chapter text track's sample count, picked out
# of ffprobe's raw (parsed) stream list.
# --------------------------------------------------------------------------- #


def test_chapter_track_samples_reads_the_text_tagged_stream():
    streams = [
        {"codec_type": "audio", "nb_frames": "999999"},
        {"codec_type": "data", "codec_tag_string": "text", "nb_frames": "7"},
    ]
    assert metadata._chapter_track_samples(streams) == 7


def test_chapter_track_samples_falls_back_to_a_subtitle_stream_when_untagged():
    # Older ffprobe builds report the chapter track as a bare "subtitle"
    # stream with no "text" codec_tag_string at all.
    streams = [{"codec_type": "subtitle", "nb_frames": "4"}]
    assert metadata._chapter_track_samples(streams) == 4


def test_chapter_track_samples_is_none_with_no_data_or_subtitle_stream():
    streams = [{"codec_type": "audio", "nb_frames": "999"},
              {"codec_type": "video", "nb_frames": "1"}]
    assert metadata._chapter_track_samples(streams) is None


def test_chapter_track_samples_does_not_substitute_an_unrelated_streams_count():
    """An unreadable frame count on the real (``text``-tagged) chapter track
    must report unreadable (``None``), never silently pick up some other,
    unrelated data/subtitle stream's count instead — that would defeat the
    truncation check :class:`~shared.metadata.ChapterStructure` exists for."""
    streams = [
        # The actual chapter text track: present, but its frame count did not
        # parse (missing key here; a non-numeric string is equally covered).
        {"codec_type": "data", "codec_tag_string": "text"},
        # An unrelated data stream that happens to carry a parseable count —
        # must never be mistaken for the chapter track's own sample count.
        {"codec_type": "data", "codec_tag_string": "bin\x00", "nb_frames": "42"},
    ]
    assert metadata._chapter_track_samples(streams) is None


def test_chapter_track_samples_none_also_covers_a_non_numeric_frame_count():
    streams = [
        {"codec_type": "data", "codec_tag_string": "text", "nb_frames": "N/A"},
        {"codec_type": "subtitle", "nb_frames": "13"},
    ]
    assert metadata._chapter_track_samples(streams) is None
