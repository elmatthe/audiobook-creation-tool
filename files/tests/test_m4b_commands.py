"""The pinned ffmpeg command shape — v0.6.2 Plan 5, Phase 5.

**Why so many of these tests are about argument *position*.** Phase 5's decision
was not which flags to pass but where to put one of them. Moving ``-ss`` from
after ``-i`` to before it makes ffmpeg roughly a hundred times faster at
reaching a late chapter and silently damages the head of nearly every segment —
on the FFmpeg nightly by emitting hard silence and attenuated frames *while
reporting an exactly correct duration*, and on FFmpeg 9.0 by skipping ~21-24 ms
outright. Because one of those failures leaves the duration correct, no drift
guard could catch it downstream. So the ordering is locked here, structurally,
and the tests say why.

The generated-media regression at the bottom re-earns that claim against a real
ffmpeg rather than trusting a comment: it builds a tiny fixture in ``tmp_path``
whose decoded content identifies its own source position, cuts two adjacent
segments with the production builder, and proves the seam neither loses nor
repeats audio. It commits no binary fixture and needs no private media.
"""

from __future__ import annotations

import ast
import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from mp3_tools import m4b_commands
from mp3_tools.m4b_commands import segment_argv, whole_book_argv
from shared import ffmpeg_utils

MODULE_PATH = Path(m4b_commands.__file__)

FFMPEG = "C:/tools/ffmpeg/bin/ffmpeg.exe"
SOURCE = "C:/books/Some Book.m4b"
DEST = "C:/out/01 - Chapter 1.mp3"


def require_ffmpeg() -> str:
    """The ffmpeg this regression runs, or a loud verdict on why it cannot.

    **Deliberately not a skip.** ffmpeg is not optional for this tool — the setup
    launcher installs it and the Converter cannot do anything without it — so its
    absence is a broken environment, not a fact to tolerate. A ``skipif`` here
    would let the one test that actually proves the seek ordering vanish from a
    run that still reported success, which is the same failure ``tk_gate`` exists
    to prevent: Plan 4 measured a full-suite invocation silently dropping
    forty-nine tests and still exiting zero.

    The executable is *run*, not merely resolved. Both Smart App Control
    incidents on this project left the binary present and resolvable while
    refusing to execute it, which a ``have_ffmpeg()`` path check cannot see.
    """
    if not ffmpeg_utils.have_ffmpeg():
        pytest.fail(
            "ffmpeg/ffprobe could not be resolved, so the Plan 5 generated-media "
            "regression cannot run. This is a red gate, not a skip: ffmpeg is a "
            "required dependency installed by the setup launcher. "
            f"ffmpeg_path()={ffmpeg_utils.ffmpeg_path()!r} "
            f"ffprobe_path()={ffmpeg_utils.ffprobe_path()!r}"
        )
    command = ffmpeg_utils.ffmpeg_cmd()
    try:
        probe = subprocess.run([command, "-version"], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    except OSError as exc:
        pytest.fail(f"{command!r} resolved but could not be launched: {exc!r}")
    if probe.returncode != 0:
        pytest.fail(
            f"{command!r} resolved but exited {probe.returncode} on '-version', so "
            "it cannot be used. Output follows:\n" + (probe.stdout or "<no output>")
        )
    return command


def base(**kwargs) -> dict:
    settings = dict(ffmpeg=FFMPEG, source=SOURCE, destination=DEST, quality=4)
    settings.update(kwargs)
    return settings


def index(argv: list[str], token: str) -> int:
    assert token in argv, (token, argv)
    return argv.index(token)


# --------------------------------------------------------------------------- #
# Whole book — today's Converter behaviour, preserved
# --------------------------------------------------------------------------- #


def test_whole_book_carries_no_seek():
    assert "-ss" not in whole_book_argv(**base())


def test_whole_book_carries_no_duration_limiter():
    assert "-t" not in whole_book_argv(**base())


def test_whole_book_shape_is_exact():
    assert whole_book_argv(**base()) == [
        FFMPEG, "-hide_banner", "-y",
        "-i", SOURCE,
        "-vn",
        "-c:a", "libmp3lame", "-q:a", "4", "-threads", "0",
        DEST,
    ]


# --------------------------------------------------------------------------- #
# Whole book with a cover — v0.6.2 Plan 5 Phase 15
#
# The book is opened twice and the picture comes from input 1. Phase 15
# measured what happens otherwise: reading the cover out of the same input
# whose audio is being decoded makes ffmpeg exit 0 after a handful of audio
# frames, on any source longer than about fifty minutes. The observed
# artifact was a 600 KB file holding 0.32 seconds of a 13.5-hour audiobook,
# reported as success. These guards exist so that shape cannot come back.
# --------------------------------------------------------------------------- #


def test_whole_book_with_a_cover_shape_is_exact():
    assert whole_book_argv(**base(attached_picture=2)) == [
        FFMPEG, "-hide_banner", "-y",
        "-i", SOURCE,
        "-i", SOURCE,
        "-map", "0:a:0",
        "-map", "1:2",
        "-c:v", "copy",
        "-disposition:v:0", "attached_pic",
        "-c:a", "libmp3lame", "-q:a", "4", "-threads", "0",
        DEST,
    ]


def test_a_cover_opens_the_same_book_a_second_time():
    argv = whole_book_argv(**base(attached_picture=2))
    inputs = [argv[i + 1] for i, token in enumerate(argv) if token == "-i"]
    assert inputs == [SOURCE, SOURCE], inputs


def test_the_audio_is_taken_from_the_first_input():
    """Input 0 is the one being decoded, so the audio must come from it."""
    argv = whole_book_argv(**base(attached_picture=7))
    maps = [argv[i + 1] for i, token in enumerate(argv) if token == "-map"]
    assert maps[0] == "0:a:0"


def test_the_cover_is_taken_from_the_second_input():
    argv = whole_book_argv(**base(attached_picture=7))
    maps = [argv[i + 1] for i, token in enumerate(argv) if token == "-map"]
    assert maps[1] == "1:7", maps
    assert "0:7" not in maps, "the cover must not come from the decoded input"


def test_the_cover_stream_index_stays_absolute():
    """A source may carry a real video track ahead of its cover."""
    for index in (1, 2, 5, 11):
        argv = whole_book_argv(**base(attached_picture=index))
        maps = [argv[i + 1] for i, token in enumerate(argv) if token == "-map"]
        assert maps[1] == f"1:{index}"
        assert "1:v:0" not in maps


def test_the_cover_is_copied_never_re_encoded():
    argv = whole_book_argv(**base(attached_picture=2))
    assert argv[argv.index("-c:v") + 1] == "copy"
    assert argv[argv.index("-disposition:v:0") + 1] == "attached_pic"


def test_a_cover_does_not_add_a_second_encode():
    """One command, one audio encode. Whole book never becomes two passes."""
    argv = whole_book_argv(**base(attached_picture=2))
    assert argv.count("-c:a") == 1
    assert argv.count("libmp3lame") == 1
    assert argv[-1] == DEST


def test_decoder_args_stay_in_front_of_the_audio_input_only():
    """They select how input 0 is *decoded*; input 1 is only stream-copied."""
    argv = whole_book_argv(
        **base(attached_picture=2, decoder_args=["-c:a", "aac_at"]))
    first = argv.index("-i")
    second = argv.index("-i", first + 1)
    assert argv.index("aac_at") < first
    assert argv[first + 1 : second] == [SOURCE], (
        "nothing may sit between the two inputs")


def test_output_args_still_follow_the_mapping():
    argv = whole_book_argv(
        **base(attached_picture=2, output_args=["-map_chapters", "0"]))
    assert index(argv, "-map_chapters") > index(argv, "-disposition:v:0")
    assert argv[index(argv, "-map_chapters") + 1] == "0"


def test_chapters_still_come_from_the_decoded_input():
    """``-map_chapters 0`` is input 0 — the book, not the cover's copy."""
    argv = whole_book_argv(
        **base(attached_picture=2, output_args=["-map_chapters", "0"]))
    assert argv[index(argv, "-map_chapters") + 1] == "0"


def test_a_whole_book_without_a_cover_opens_the_source_once():
    """The no-artwork command is byte-identical to its pre-Phase-15 shape."""
    argv = whole_book_argv(**base())
    assert argv.count("-i") == 1
    assert "-vn" in argv
    assert "attached_pic" not in argv


def test_a_segment_never_opens_a_second_input():
    """Split keeps its measured single-input seek shape untouched."""
    argv = segment_argv(**base(start=1.0, end=2.0))
    assert argv.count("-i") == 1
    assert "-vn" in argv


def test_whole_book_places_decoder_args_before_the_input():
    argv = whole_book_argv(**base(decoder_args=["-c:a", "aac_at"]))
    assert argv.index("aac_at") < index(argv, "-i")


def test_destination_is_last():
    assert whole_book_argv(**base())[-1] == DEST
    assert segment_argv(**base(start=1.0, end=2.0))[-1] == DEST


def test_source_immediately_follows_the_input_flag():
    argv = whole_book_argv(**base())
    assert argv[index(argv, "-i") + 1] == SOURCE


def test_video_is_stripped():
    assert "-vn" in whole_book_argv(**base())
    assert "-vn" in segment_argv(**base(start=1.0, end=2.0))


def test_threads_are_left_to_ffmpeg():
    argv = whole_book_argv(**base())
    assert argv[index(argv, "-threads") + 1] == "0"


def test_banner_and_overwrite_are_pinned():
    argv = whole_book_argv(**base())
    assert argv[:3] == [FFMPEG, "-hide_banner", "-y"]


# --------------------------------------------------------------------------- #
# Split — the measured seek shape
# --------------------------------------------------------------------------- #


def test_split_shape_is_exact():
    assert segment_argv(**base(start=19.87, end=41.055)) == [
        FFMPEG, "-hide_banner", "-y",
        "-i", SOURCE,
        "-ss", "19.870000", "-t", "21.185000",
        "-vn",
        "-c:a", "libmp3lame", "-q:a", "4", "-threads", "0",
        DEST,
    ]


def test_seek_is_on_the_output_side():
    """The measured decision: ``-ss`` after ``-i``, never before it.

    Before ``-i`` this is far faster and loses audio at the head of the segment.
    """
    argv = segment_argv(**base(start=19.87, end=41.055))
    assert index(argv, "-ss") > index(argv, "-i")


def test_seek_follows_the_source_immediately():
    argv = segment_argv(**base(start=19.87, end=41.055))
    assert argv[index(argv, "-i") + 2] == "-ss"


def test_span_is_an_explicit_duration_not_an_absolute_end():
    argv = segment_argv(**base(start=10.0, end=30.0))
    assert "-to" not in argv
    assert argv[index(argv, "-t") + 1] == "20.000000"


def test_duration_is_end_minus_start():
    argv = segment_argv(**base(start=7.3, end=19.87))
    assert argv[index(argv, "-t") + 1] == f"{19.87 - 7.3:.6f}"


def test_the_absolute_end_never_appears_as_a_value():
    """A ``-t`` carrying ``end`` instead of ``end - start`` is the exact bug that
    turned a requested 20 s span of a real audiobook into an 11-hour file."""
    argv = segment_argv(**base(start=83368.661, end=83388.661))
    assert argv[index(argv, "-t") + 1] == "20.000000"
    assert "83388.661000" not in argv


def test_a_zero_start_is_still_an_explicit_output_side_seek():
    argv = segment_argv(**base(start=0.0, end=7.3))
    assert argv[index(argv, "-ss") + 1] == "0.000000"
    assert index(argv, "-ss") > index(argv, "-i")


@pytest.mark.parametrize(
    "start, end, rendered_start, rendered_duration",
    [
        (0.0, 7.3, "0.000000", "7.300000"),
        (7.3, 19.87, "7.300000", "12.570000"),
        (41.055, 43.2, "41.055000", "2.145000"),
        (59.63, 60.0, "59.630000", "0.370000"),
        (83368.661, 83388.661, "83368.661000", "20.000000"),
        (0.001, 0.002, "0.001000", "0.001000"),
    ],
)
def test_fractional_boundaries_survive(start, end, rendered_start, rendered_duration):
    argv = segment_argv(**base(start=start, end=end))
    assert argv[index(argv, "-ss") + 1] == rendered_start
    assert argv[index(argv, "-t") + 1] == rendered_duration


def test_a_deep_timestamp_is_not_rendered_in_exponent_notation():
    argv = segment_argv(**base(start=1e-7, end=1.0))
    assert "e" not in argv[index(argv, "-ss") + 1]


def test_nothing_is_rounded_to_whole_seconds():
    argv = segment_argv(**base(start=41.055, end=43.2))
    assert argv[index(argv, "-ss") + 1] != "41.000000"
    assert argv[index(argv, "-ss") + 1] == "41.055000"


def test_a_very_short_span_is_preserved():
    argv = segment_argv(**base(start=59.63, end=60.0))
    assert argv[index(argv, "-t") + 1] == "0.370000"


# --------------------------------------------------------------------------- #
# xHE-AAC: an input decoder and an output encoder that share a flag name
# --------------------------------------------------------------------------- #


def test_the_xhe_decoder_lands_before_the_input():
    argv = segment_argv(**base(start=1.0, end=2.0, decoder_args=["-c:a", "aac_at"]))
    assert argv.index("aac_at") < index(argv, "-i")


def test_the_mp3_encoder_lands_after_the_input():
    argv = segment_argv(**base(start=1.0, end=2.0, decoder_args=["-c:a", "aac_at"]))
    assert argv.index("libmp3lame") > index(argv, "-i")


def test_both_codec_flags_are_present_and_unconfused():
    """``-c:a`` appears twice and means two different things.

    Before ``-i`` it selects the decoder for the source; after ``-i`` it selects
    the encoder for the output. Collapsing them would either decode the M4B with
    libmp3lame or encode the MP3 with aac_at.
    """
    argv = segment_argv(**base(start=1.0, end=2.0, decoder_args=["-c:a", "aac_at"]))
    positions = [i for i, token in enumerate(argv) if token == "-c:a"]
    assert len(positions) == 2
    boundary = index(argv, "-i")
    assert positions[0] < boundary < positions[1]
    assert argv[positions[0] + 1] == "aac_at"
    assert argv[positions[1] + 1] == "libmp3lame"


def test_the_decoder_args_come_from_the_shared_helper(monkeypatch):
    """The builder consumes ``input_decoder_args`` output verbatim.

    ``aac_at`` exists only where Apple AudioToolbox does, so availability is
    faked here rather than requiring a macOS run — this pins the *contract*
    between the two modules, which is what Phase 5 owns.
    """
    monkeypatch.setattr(ffmpeg_utils, "_decoder_available", lambda name: name == "aac_at")
    produced = ffmpeg_utils.input_decoder_args({"profile": "xHE-AAC"})
    assert produced == ["-c:a", "aac_at"]
    argv = segment_argv(**base(start=1.0, end=2.0, decoder_args=produced))
    assert argv[index(argv, "-i") - 2:index(argv, "-i")] == ["-c:a", "aac_at"]


def test_no_decoder_args_leaves_a_single_codec_flag():
    argv = segment_argv(**base(start=1.0, end=2.0))
    assert [token for token in argv if token == "-c:a"] == ["-c:a"]
    assert argv[index(argv, "-c:a") + 1] == "libmp3lame"


# --------------------------------------------------------------------------- #
# Quality
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("quality", list(range(0, 10)))
def test_every_valid_quality_is_rendered_verbatim(quality):
    argv = whole_book_argv(**base(quality=quality))
    assert argv[index(argv, "-q:a") + 1] == str(quality)


def test_quality_is_vbr_not_a_bitrate():
    """The Converter's contract is ``-q:a``. ``ffmpeg_utils.mp3_export_options``
    pins a constant *bitrate* for TTS finalisation; the two must not merge."""
    argv = whole_book_argv(**base())
    assert "-b:a" not in argv
    assert "-q:a" in argv
    assert ffmpeg_utils.DEFAULT_MP3_BITRATE not in argv


@pytest.mark.parametrize("bad", [-1, 10, 99])
def test_a_quality_outside_the_encoder_range_is_refused(bad):
    with pytest.raises(ValueError):
        whole_book_argv(**base(quality=bad))


@pytest.mark.parametrize("bad", ["4", 4.0, None, True])
def test_a_non_integer_quality_is_refused(bad):
    with pytest.raises((TypeError, ValueError)):
        whole_book_argv(**base(quality=bad))


# --------------------------------------------------------------------------- #
# Local preconditions — only enough to prevent meaningless argv
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("start, end", [(5.0, 5.0), (5.0, 4.0)])
def test_a_span_that_is_not_forward_is_refused(start, end):
    with pytest.raises(ValueError):
        segment_argv(**base(start=start, end=end))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_boundary_is_refused(value):
    with pytest.raises(ValueError):
        segment_argv(**base(start=value, end=10.0))
    with pytest.raises(ValueError):
        segment_argv(**base(start=0.0, end=value))


def test_a_negative_start_is_refused():
    with pytest.raises(ValueError):
        segment_argv(**base(start=-1.0, end=10.0))


def test_an_empty_ffmpeg_is_refused():
    with pytest.raises(ValueError):
        whole_book_argv(**base(ffmpeg=""))


def test_a_non_string_argument_entry_is_refused():
    with pytest.raises(TypeError):
        whole_book_argv(**base(decoder_args=["-c:a", None]))


def test_a_bare_string_is_not_mistaken_for_an_argument_sequence():
    with pytest.raises(TypeError):
        whole_book_argv(**base(output_args="-map_metadata"))


def test_the_builder_does_not_validate_chapter_geometry():
    """Timeline validity belongs to ``m4b_chapters``; a span past the source
    duration is still a well-formed command line."""
    argv = segment_argv(**base(start=999999.0, end=1000000.0))
    assert argv[index(argv, "-ss") + 1] == "999999.000000"


# --------------------------------------------------------------------------- #
# The Phase 6 extension seam
# --------------------------------------------------------------------------- #


def test_output_args_are_spliced_between_vn_and_the_encoder():
    argv = whole_book_argv(**base(output_args=["-map_metadata", "-1"]))
    assert index(argv, "-map_metadata") > index(argv, "-vn")
    assert index(argv, "-map_metadata") < index(argv, "-c:a")


def test_output_args_cannot_reach_the_input_option_region():
    """The seam is spliced after ``-i``, so nothing Phase 6 passes can become an
    input option and change how the source is *decoded*."""
    argv = segment_argv(**base(start=1.0, end=2.0, output_args=["-ss", "999"]))
    assert argv.index("999") > index(argv, "-i")
    assert argv[3:5] == ["-i", SOURCE]


def test_output_args_cannot_displace_the_seek():
    argv = segment_argv(**base(start=19.87, end=41.055, output_args=["-metadata", "x=y"]))
    assert argv[index(argv, "-i") + 2:index(argv, "-i") + 6] == [
        "-ss", "19.870000", "-t", "21.185000",
    ]


def test_the_seam_is_empty_by_default():
    assert whole_book_argv(**base()) == whole_book_argv(**base(output_args=[]))


def test_the_seam_preserves_caller_order():
    argv = whole_book_argv(**base(output_args=["-a", "1", "-b", "2"]))
    start = index(argv, "-a")
    assert argv[start:start + 4] == ["-a", "1", "-b", "2"]


def test_the_builder_returns_a_fresh_list_each_call():
    first = whole_book_argv(**base())
    first.append("mutated")
    assert "mutated" not in whole_book_argv(**base())


# --------------------------------------------------------------------------- #
# Purity — structural, over the module's own AST
# --------------------------------------------------------------------------- #


def tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))


def imported() -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree()):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def literals() -> set[str]:
    """Every string literal that is not a docstring.

    Docstrings are excluded by identity: this module's own docstring explains
    the rejected shapes and necessarily names them, and a text scan would fire
    on that prose.
    """
    parsed = tree()
    docstrings = {
        id(node.value) for node in ast.walk(parsed)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    return {
        node.value for node in ast.walk(parsed)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings
    }


def called() -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree()):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


def test_the_module_imports_only_the_standard_library():
    assert imported() <= {"__future__", "math", "collections"}


def test_the_module_does_not_import_shared():
    assert "shared" not in imported()


@pytest.mark.parametrize(
    "forbidden",
    ["subprocess", "os", "sys", "pathlib", "tkinter", "threading", "queue",
     "logging", "shutil", "tempfile"],
)
def test_no_execution_or_io_module_is_imported(forbidden):
    assert forbidden not in imported()


@pytest.mark.parametrize(
    "forbidden",
    ["run", "popen", "Popen", "check_output", "open", "mkdir", "unlink",
     "exists", "probe_audio_stream", "input_decoder_args", "_decoder_available",
     "ffmpeg_cmd", "ffprobe_cmd", "plan", "reserve_run_directory"],
)
def test_the_builder_calls_nothing_that_acts_on_the_world(forbidden):
    assert forbidden not in called()


@pytest.mark.parametrize("forbidden", ["ffprobe", "-show_chapters"])
def test_the_module_never_probes(forbidden):
    """Still no probing here — the stream facts arrive already known.

    ``-map_chapters`` left this list in Phase 6: the attach pass must pin it to
    ``-1`` so no chapter map can reach a fragment. That is structural provenance,
    not a policy decision, and ``test_no_metadata_policy_is_decided_here`` keeps
    the policy vocabulary out.
    """
    assert forbidden not in literals()


def test_no_metadata_policy_is_decided_here():
    """Phase 6 narrowed this guard deliberately; it did not delete it.

    Phase 5 forbade every metadata and mapping token, because this module then
    had no business emitting any. Phase 6 gives it two legitimate structural
    jobs — mapping a cover stream, and fixing the provenance of the attach pass —
    so ``-map``, ``-map_metadata``, ``-map_chapters``, ``-disposition`` and
    ``attached_pic`` now appear here by design.

    What must still be absent is *policy*: this module may not know the metadata
    modes, may not name a metadata field, and may not emit a ``-metadata`` pair.
    Those decisions belong to ``m4b_metadata`` and reach here only as opaque
    ``output_args``.
    """
    for forbidden in ("-metadata", "-id3v2_version",
                      "Preserve", "Strip", "Replace", "PRESERVE", "STRIP", "REPLACE",
                      "MetadataMode", "album_artist", "album", "artist", "track"):
        assert forbidden not in literals(), forbidden


def test_the_metadata_module_is_not_imported_here():
    """The dependency runs one way: policy composes commands, never the reverse."""
    assert "m4b_metadata" not in imported()
    assert "shared" not in imported()


def test_no_phase_eleven_lifecycle_vocabulary_is_present():
    for forbidden in ("terminate", "kill", "wait", "poll", "checkpoint", "cancel"):
        assert forbidden not in called(), forbidden


def test_no_later_phase_planning_type_is_defined():
    defined = {node.name for node in ast.walk(tree())
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for forbidden in ("SegmentPlan", "ItemPlan", "ConversionPlan", "DestinationPlanner"):
        assert forbidden not in defined


def test_the_public_surface_is_exactly_three_builders():
    """Phase 6 added exactly one builder: the split artwork attach pass."""
    public = {node.name for node in tree().body
              if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")}
    assert public == {"whole_book_argv", "segment_argv", "attach_artwork_argv"}


def test_the_tts_bitrate_contract_is_not_borrowed():
    """The encoder name is a local literal, not a reference to the TTS contract.

    ``ffmpeg_utils.FINAL_MP3_CODEC`` is also ``"libmp3lame"``, so importing it
    would look harmless and would quietly couple the Converter's VBR contract to
    a constant that exists to pin a CBR *bitrate* for a different tool.
    """
    referenced = {node.id for node in ast.walk(tree()) if isinstance(node, ast.Name)}
    referenced |= {node.attr for node in ast.walk(tree()) if isinstance(node, ast.Attribute)}
    for forbidden in ("FINAL_MP3_CODEC", "DEFAULT_MP3_BITRATE", "mp3_export_options"):
        assert forbidden not in referenced, forbidden
    assert "libmp3lame" in literals()


def test_no_naming_or_filename_logic_leaked_in():
    for forbidden in ("sanitize_component", "segment_filename", "flatten_title"):
        assert forbidden not in called()


def test_the_chapter_layer_is_untouched_by_naming_a_span():
    """The builder takes scalars, so planning a command cannot mutate a span."""
    from mp3_tools.m4b_chapters import ChapterSpan

    span = ChapterSpan(order=1, source_index=0, start=19.87, end=41.055, title="Ch 1")
    segment_argv(**base(start=span.start, end=span.end))
    assert (span.start, span.end) == (19.87, 41.055)


# --------------------------------------------------------------------------- #
# Generated-media regression — the seam, against a real ffmpeg
# --------------------------------------------------------------------------- #

_SR = 44100
_MARKER_HZ = 6000.0
_MARKER_MS = 12.0


def _write_fixture(path: Path, seconds: int) -> None:
    """A tone whose frequency identifies its source second, plus a burst at each.

    Written with the standard library so the suite gains no dependency; the only
    external tool involved is the ffmpeg the repository already requires.
    """
    total = _SR * seconds
    frames = bytearray()
    phase = 0.0
    burst = int(_SR * _MARKER_MS / 1000.0)
    for n in range(total):
        second = min(n // _SR, seconds - 1)
        phase += 2.0 * math.pi * (300.0 + second * 20.0) / _SR
        value = 0.30 * math.sin(phase)
        offset = n % _SR
        if offset < burst:
            envelope = 0.5 - 0.5 * math.cos(2.0 * math.pi * offset / burst)
            value += 0.85 * envelope * math.sin(2.0 * math.pi * _MARKER_HZ * offset / _SR)
        frames += struct.pack("<h", max(-32767, min(32767, int(value * 32767))))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SR)
        handle.writeframes(bytes(frames))


def _decode(path: Path) -> list[float]:
    raw = subprocess.run(
        [ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-i", str(path),
         "-ac", "1", "-ar", str(_SR), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    ).stdout
    count = len(raw) // 2
    return [v / 32768.0 for v in struct.unpack(f"<{count}h", raw[:count * 2])]


def _marker_offsets(samples: list[float]) -> list[float]:
    """Output offsets, in seconds, of every marker burst present."""
    window = int(_SR * _MARKER_MS / 1000.0)
    hop = window // 6
    magnitudes: list[tuple[int, float]] = []
    for start in range(0, max(0, len(samples) - window), hop):
        real = imag = 0.0
        for i in range(window):
            angle = 2.0 * math.pi * _MARKER_HZ * i / _SR
            weight = 0.5 - 0.5 * math.cos(2.0 * math.pi * i / window)
            real += samples[start + i] * weight * math.cos(angle)
            imag -= samples[start + i] * weight * math.sin(angle)
        magnitudes.append((start, math.hypot(real, imag) / window))
    hits: list[float] = []
    i = 0
    while i < len(magnitudes):
        if magnitudes[i][1] >= 0.05:
            j = i
            while j + 1 < len(magnitudes) and magnitudes[j + 1][1] >= 0.05:
                j += 1
            peak = max(magnitudes[i:j + 1], key=lambda entry: entry[1])[0]
            hits.append(peak / _SR)
            i = j + 1
        else:
            i += 1
    return hits


@pytest.fixture(scope="module")
def generated_m4b(tmp_path_factory) -> Path:
    ffmpeg = require_ffmpeg()
    folder = tmp_path_factory.mktemp("m4b_commands")
    wav = folder / "signal.wav"
    m4b = folder / "fixture.m4b"
    _write_fixture(wav, 6)
    subprocess.run(
        [ffmpeg, "-hide_banner", "-v", "error", "-y", "-i", str(wav),
         "-c:a", "aac", "-b:a", "128k", str(m4b)],
        check=True,
    )
    wav.unlink()
    return m4b


def test_the_built_command_actually_runs(generated_m4b, tmp_path):
    dest = tmp_path / "whole.mp3"
    argv = whole_book_argv(ffmpeg=ffmpeg_utils.ffmpeg_cmd(), source=generated_m4b,
                           destination=str(dest), quality=4)
    assert subprocess.run(argv, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0
    assert dest.exists() and dest.stat().st_size > 0


def test_adjacent_segments_neither_lose_nor_repeat_audio(generated_m4b, tmp_path):
    """The seam itself, measured — this is what the ordering decision protects.

    The fixture carries one burst per source second, so the seconds recovered
    from two adjacent segments form an exact ledger: a lost boundary shows up as
    a missing second and a duplicated one as a second appearing twice.
    """
    spans = [(0.0, 2.7), (2.7, 6.0)]
    recovered: list[int] = []
    for order, (start, end) in enumerate(spans, 1):
        dest = tmp_path / f"seg{order}.mp3"
        argv = segment_argv(ffmpeg=ffmpeg_utils.ffmpeg_cmd(), source=generated_m4b,
                            destination=str(dest), quality=4, start=start, end=end)
        assert subprocess.run(argv, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
        samples = _decode(dest)
        assert abs(len(samples) / _SR - (end - start)) < 0.05, (order, len(samples) / _SR)
        recovered += [round(start + offset) for offset in _marker_offsets(samples)]

    assert sorted(recovered) == [0, 1, 2, 3, 4, 5], recovered
    assert len(recovered) == len(set(recovered)), recovered


def test_a_fractional_segment_starts_where_it_was_asked_to(generated_m4b, tmp_path):
    """A non-round start is where input-side seek damaged the head worst."""
    dest = tmp_path / "frac.mp3"
    argv = segment_argv(ffmpeg=ffmpeg_utils.ffmpeg_cmd(), source=generated_m4b,
                        destination=str(dest), quality=4, start=2.7, end=4.2)
    assert subprocess.run(argv, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0
    samples = _decode(dest)
    offsets = _marker_offsets(samples)
    assert offsets, "no marker recovered"
    # Source second 3 sits 0.3 s into a segment that starts at 2.7 s.
    assert abs(offsets[0] - 0.3) < 0.03, offsets
    assert abs(len(samples) / _SR - 1.5) < 0.05
