"""v0.8.x P1A D3 remediation -- proof 8's amended sample-count criterion (``files/dev-tools/xhe_proof.py``).

The owner amended T1 alone (Decisions 2026-11-15): FFmpeg may emit more frames than Apple only for an owner-approved
source, at exactly the approved counts, aligned at lag 0 and bit-identical over every frame Apple emits, with exactly
packets x frames-per-packet frames, no more excess than the padding the container declares, and every excess frame
zero. The synthetic tests below start from a stitched control that passes and damage one thing each; they run on every
platform (pure arithmetic on PCM bytes). The tests that decode real media need a Mac, Apple's afconvert and the adopted
Riedl 9.0.1 build. Nothing here trims audio, and the Converter's decode stays exactly ``-c:a aac_at``.
"""

from __future__ import annotations

import array
import dataclasses
import hashlib
import importlib.util
import io
import math
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "files" / "dev-tools" / "xhe_proof.py"
NATIVE_MACOS = "native macOS only (P1A): bash 3.2 stage 0, POSIX process groups, Mach-O and codesign checks"
STITCHED_FIXTURE = REPO_ROOT / "files" / "test-files" / "Reincarnated as a Sword.m4b"
AAC_LC_CONTROL = REPO_ROOT / "files" / "test-files" / "Mistborn, Book 1_ The Final Empire.m4b"

from m4b.m4b_commands import segment_argv, whole_book_argv  # noqa: E402
from shared import ffmpeg_portable, ffmpeg_utils  # noqa: E402


def _tool():
    spec = importlib.util.spec_from_file_location("act_xhe_proof", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module   # dataclasses resolve their annotations through the module
    spec.loader.exec_module(module)
    return module


xp = _tool()

# A stitched book in miniature: 200 packets of 1024 frames; the sample table declares 3,000 frames of padding (at the
# joins); Apple stops 2,990 frames before the last packet's end (its edit-list length), FFmpeg emits every packet.
PACKETS, FPP, DECLARED_PADDING, APPLE_SHORT = 200, 1024, 3000, 2990
SOURCE_SHA = "0" * 63 + "1"
ACCOUNTING = xp.Accounting(timescale=44100, packets=PACKETS, frames_per_packet=FPP,
                           declared_frames=PACKETS * FPP - DECLARED_PADDING)
APPLE_FRAMES = PACKETS * FPP - APPLE_SHORT
APPROVED = (xp.ApprovedLengthException(SOURCE_SHA, APPLE_FRAMES, PACKETS * FPP, "test fixture"),)


def _audio(frames: int, seed: int = 7) -> bytearray:
    """Deterministic, never-repeating, non-silent 16-bit stereo PCM."""
    values = array.array("h")
    state = seed
    for i in range(frames):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        left = int(9000 * math.sin(i * 0.0627)) + ((state >> 16) % 4001 - 2000)
        values.extend((left, -left // 2))
    return bytearray(values.tobytes())


APPLE_PCM = bytes(_audio(APPLE_FRAMES))


def _judge(ffmpeg: bytes, *, apple: bytes = APPLE_PCM, accounting=ACCOUNTING, approved=APPROVED,
           source_sha256=SOURCE_SHA) -> dict:
    return xp.evaluate(io.BytesIO(apple), io.BytesIO(ffmpeg), accounting, source_sha256=source_sha256,
                       approved=approved)


def _stitched_control() -> bytearray:
    """FFmpeg's decode of the miniature: every Apple frame, then the excess as exact zeros."""
    return bytearray(APPLE_PCM) + bytes(APPLE_SHORT * xp.BYTES_PER_FRAME)


def _set_sample(pcm: bytearray, frame: int, value: int, channel: int = 0) -> bytearray:
    offset = frame * xp.BYTES_PER_FRAME + 2 * channel
    pcm[offset:offset + 2] = int(value).to_bytes(2, "little", signed=True)
    return pcm


# --------------------------------------------------------------------------- #
#  The control, then one damage at a time
# --------------------------------------------------------------------------- #
def test_the_stitched_control_passes_only_through_the_full_length_exception():
    result = _judge(bytes(_stitched_control()))
    assert result["PASS"] is True, result["reasons"]
    assert result["T1_strict_pass"] is False, "the excess is larger than one AAC frame"
    assert result["length_exception_applied"] is True
    assert all(result["length_exception_conditions"].values())
    assert result["frame_count_difference"] == APPLE_SHORT and result["lag_frames"] == 0
    assert result["identical_frames"] == result["compared_frames"] == APPLE_FRAMES
    assert result["excess_sha256"] == result["zero_frames_sha256"]


def test_one_differing_sample_in_the_common_range_denies_the_exception():
    """1 LSB passes T3 as written, but the exception needs every Apple frame bit-identical."""
    original = int.from_bytes(APPLE_PCM[100_000 * xp.BYTES_PER_FRAME:][:2], "little", signed=True)
    result = _judge(bytes(_set_sample(_stitched_control(), 100_000, original + (1 if original < 32767 else -1))))
    assert result["T3_pcm_pass"] is True and result["max_abs_diff_lsb"] == 1
    assert result["length_exception_conditions"]["E3_exact_alignment_and_bit_identical_common_range"] is False
    assert result["PASS"] is False and result["first_differing_frame"] == 100_000


def test_corrupted_narration_in_the_common_range_fails_t3():
    damaged = _stitched_control()
    damaged[200_000:240_000] = bytes(40_000)          # 10,000 frames of narration replaced by silence
    result = _judge(bytes(damaged))
    assert result["T3_pcm_pass"] is False and result["PASS"] is False


@pytest.mark.parametrize("frame_in_excess", [0, APPLE_SHORT // 2, APPLE_SHORT - 1])
def test_a_non_zero_frame_anywhere_in_the_excess_fails(frame_in_excess):
    result = _judge(bytes(_set_sample(_stitched_control(), APPLE_FRAMES + frame_in_excess, 1, channel=1)))
    assert result["length_exception_conditions"]["E6_every_excess_frame_is_zero"] is False
    assert result["extra_first_nonzero_frame"] == frame_in_excess
    assert result["PASS"] is False


def test_an_excess_beyond_the_declared_padding_is_unexplained_and_fails():
    accounting = dataclasses.replace(ACCOUNTING, declared_frames=PACKETS * FPP - 2000)   # declares only 2,000
    result = _judge(bytes(_stitched_control()), accounting=accounting)
    assert result["length_exception_conditions"]["E5_excess_within_declared_padding"] is False
    assert result["PASS"] is False


def test_frames_beyond_the_containers_packets_are_unexplained_and_fail():
    longer = bytes(_stitched_control()) + bytes(1024 * xp.BYTES_PER_FRAME)   # one more packet of zeros than exists
    approved = (dataclasses.replace(APPROVED[0], ffmpeg_frames=PACKETS * FPP + 1024),)
    result = _judge(longer, approved=approved)
    assert result["length_exception_conditions"]["E4_ffmpeg_frames_equal_packets_times_frames_per_packet"] is False
    assert result["PASS"] is False


def test_the_same_silent_excess_on_a_source_nobody_approved_fails():
    """No general licence: identical evidence, a different file."""
    result = _judge(bytes(_stitched_control()), source_sha256="f" * 64)
    assert result["length_exception_conditions"]["E1_owner_approved_source_and_exact_counts"] is False
    assert result["PASS"] is False


def test_the_approved_source_at_other_counts_fails():
    approved = (dataclasses.replace(APPROVED[0], apple_frames=APPLE_FRAMES + 1),)
    result = _judge(bytes(_stitched_control()), approved=approved)
    assert result["length_exception_conditions"]["E1_owner_approved_source_and_exact_counts"] is False
    assert result["PASS"] is False


def test_lost_narration_at_the_end_is_a_shortfall_and_fails():
    """A regression that removes valid audio (an Apple-length trim gone too far, a truncated decode)."""
    short = APPLE_PCM[: (APPLE_FRAMES - 5000) * xp.BYTES_PER_FRAME]
    result = _judge(short)
    assert result["frame_count_difference"] == -5000 and result["extra_frames_belong_to"] == "apple"
    assert result["length_exception_conditions"]["E2_excess_not_shortfall"] is False
    assert result["PASS"] is False


def test_narration_removed_from_the_middle_fails():
    cut = bytearray(APPLE_PCM)
    del cut[100_000 * xp.BYTES_PER_FRAME:(100_000 + 22_050) * xp.BYTES_PER_FRAME]   # half a second gone
    result = _judge(bytes(cut) + bytes(APPLE_SHORT * xp.BYTES_PER_FRAME))
    assert result["PASS"] is False and result["T3_pcm_pass"] is False


def test_the_real_record_is_one_source_at_its_measured_counts():
    (record,) = xp.APPROVED_LENGTH_EXCEPTIONS
    assert record.source_sha256 == "b9a24a88eb0187cdddb9a62da38d69ca538634c5cd39c17a14ad25c786e0f8d4"
    assert (record.apple_frames, record.ffmpeg_frames) == (1_552_303_462, 1_552_310_272)
    assert record.ffmpeg_frames == 1_515_928 * 1024


# --------------------------------------------------------------------------- #
#  Nothing in production trims, and Windows is untouched
# --------------------------------------------------------------------------- #
def test_the_converter_decodes_xhe_with_aac_at_alone_and_adds_no_trim():
    common = dict(ffmpeg="ffmpeg", source="book.m4b", destination="out.mp3", quality=2, decoder_args=["-c:a", "aac_at"])
    whole = whole_book_argv(**common)
    assert whole[whole.index("-i") - 2:whole.index("-i")] == ["-c:a", "aac_at"]
    assert not {"-t", "-to", "-ss", "-af", "-filter:a", "-shortest"} & set(whole)
    assert not any("atrim" in part or "apad" in part for part in whole)
    segment = segment_argv(**common, start=10.0, end=20.0)
    assert segment.index("-ss") > segment.index("-i"), "output-side seeking is kept"
    assert not any("atrim" in part or "apad" in part for part in segment)


def test_windows_ffmpeg_pin_and_decoding_are_unchanged(monkeypatch):
    assert ffmpeg_portable.PORTABLE_FFMPEG_VERSION == "9.0.1"
    assert ffmpeg_portable.PORTABLE_FFMPEG_URL == ("https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/"
                                                   "ffmpeg-9.0.1-full_build.zip")
    assert ffmpeg_portable.PORTABLE_FFMPEG_SHA256 == "2e8e28af97c2ae338ccef92e36da9b2a4cd21d0cad9dde093545606cb07f5b00"
    assert ffmpeg_portable.PORTABLE_FFMPEG_SIZE == 251427729
    assert ffmpeg_portable.PORTABLE_FFMPEG_BUILD_DIR == "ffmpeg-9.0.1-full_build"
    # The Gyan build has no AudioToolbox: an xHE-AAC source is refused with the specific explanation, never decoded.
    monkeypatch.setattr(ffmpeg_utils, "_decoder_available", lambda name: False)
    assert ffmpeg_utils.input_decoder_args({"profile": "xHE-AAC"}) == []
    assert ffmpeg_utils.needs_special_aac_decoder({"profile": "xHE-AAC"}) is True
    assert ffmpeg_utils.input_decoder_args({"profile": "LC"}) == []
    assert ffmpeg_utils.needs_special_aac_decoder({"profile": "LC"}) is False


# --------------------------------------------------------------------------- #
#  Real decodes (a Mac with the adopted build)
# --------------------------------------------------------------------------- #
def _adopted_ffmpeg() -> str:
    """The adopted Riedl 9.0.1 ffmpeg, checked byte for byte; ACT_MAC_FFMPEG may name another copy of the same bytes."""
    if sys.platform != "darwin":
        pytest.skip(NATIVE_MACOS)
    build = ffmpeg_portable.MACOS_FFMPEG_PIN
    if build is None:
        pytest.skip("no macOS FFmpeg build is adopted")
    candidates = [os.environ.get("ACT_MAC_FFMPEG", ""), str(ffmpeg_portable.final_dir_for(build) / "bin" / "ffmpeg")]
    for candidate in filter(None, candidates):
        path = Path(candidate)
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == build.ffmpeg.binary_sha256:
            return str(path)
    pytest.skip("the adopted Riedl 9.0.1 ffmpeg is not installed here (or ACT_MAC_FFMPEG names other bytes)")


def _frames(argv: list[str]) -> int:
    done = subprocess.run(argv, capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
    assert done.returncode == 0 and not done.stderr.strip(), done.stderr[-400:]
    return len(done.stdout) // xp.BYTES_PER_FRAME


def test_a_declared_aac_lc_trim_is_applied_and_matches_apple(tmp_path):
    """Synthetic AAC-LC from Apple's own encoder: 2,112 priming + remainder declared in the container. aac_at (and the
    native decoder) remove exactly what is declared, and the decode equals Apple's at the same length."""
    ffmpeg = _adopted_ffmpeg()
    frames = 44100 * 3 + 777
    source = tmp_path / "control.wav"
    with wave.open(str(source), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(bytes(_audio(frames, seed=11)))
    encoded, apple = tmp_path / "control.m4a", tmp_path / "control.caf"
    subprocess.run(["/usr/bin/afconvert", "-f", "m4af", "-d", "aac", "-b", "128000", str(source), str(encoded)],
                   check=True, capture_output=True, timeout=120)
    subprocess.run(["/usr/bin/afconvert", "-f", "caff", "-d", "LEI16", str(encoded), str(apple)],
                   check=True, capture_output=True, timeout=120)
    accounting = xp.read_accounting(encoded)
    assert accounting.packet_frames > frames, "the container really declares priming and remainder to remove"
    for decoder in ("aac_at", "aac"):
        assert _frames([ffmpeg, "-nostdin", "-v", "error", "-c:a", decoder, "-i", str(encoded), "-f", "s16le", "-"]) \
            == frames, decoder
    result = xp.run(encoded, apple, ffmpeg, approved=())
    assert result["PASS"] is True, result["reasons"]
    assert result["frame_count_difference"] == 0 and result["length_exception_applied"] is False


@pytest.mark.skipif(not AAC_LC_CONTROL.is_file(), reason="the owner's local AAC-LC control audiobook is not here")
def test_the_aac_lc_control_audiobook_keeps_its_declared_trims_with_aac_at():
    """The existing control (elst media_time 1024, last stts delta 660): FFmpeg applies its start and end trims to
    aac_at exactly as to the native decoder (measured 2026-11-15: head 88,200; tail 1,480,323; +1,157 without them)."""
    ffmpeg = _adopted_ffmpeg()
    head = ["-t", "2"]
    tail = ["-ss", "88670"]
    counts = {}
    for name, window in (("head", head), ("tail", tail)):
        for decoder in ("aac_at", "aac"):
            argv = [ffmpeg, "-nostdin", "-v", "error", *(window if name == "tail" else []), "-c:a", decoder,
                    "-i", str(AAC_LC_CONTROL), *(window if name == "head" else []), "-map", "0:a:0", "-f", "s16le", "-"]
            counts[name, decoder] = _frames(argv)
    assert counts["head", "aac_at"] == counts["head", "aac"] == 88_200
    assert counts["tail", "aac_at"] == counts["tail", "aac"] == 1_480_323
    untrimmed = _frames([ffmpeg, "-nostdin", "-v", "error", "-flags2", "+skip_manual", *tail, "-c:a", "aac_at",
                         "-i", str(AAC_LC_CONTROL), "-map", "0:a:0", "-f", "s16le", "-"])
    assert untrimmed == 1_480_323 + 1_157


@pytest.mark.skipif(not os.environ.get("ACT_XHE_PROOF_APPLE_CAF"),
                    reason="set ACT_XHE_PROOF_APPLE_CAF to afconvert's LEI16 decode of the owner's xHE-AAC fixture "
                           "(about 6 GB) to run the real proof 8")
def test_the_approved_stitched_fixture_passes_the_amended_proof_8():
    ffmpeg = _adopted_ffmpeg()
    if not STITCHED_FIXTURE.is_file():
        pytest.skip("the owner's local xHE-AAC fixture is not here")
    result = xp.run(STITCHED_FIXTURE, Path(os.environ["ACT_XHE_PROOF_APPLE_CAF"]), ffmpeg)
    assert result["PASS"] is True, result["reasons"]
    assert result["length_exception_applied"] is True and result["frame_count_difference"] == 6_810
    assert result["identical_frames"] == result["apple_frames"] == 1_552_303_462
    assert result["accounting"]["declared_padding"] == 6_822 and result["source_unchanged"] is True
