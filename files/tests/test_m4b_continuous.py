"""The M4B Converter's continuous split route (v0.7.2 Phase 7B, ACT72-012).

Three layers, each with its own oracle:

* **Rules** (pure): which samples a chapter is, which books may take the route, and what a packet timeline must look
  like before a sample's timestamp can be trusted to be its index.
* **The decoder** against real child processes: a Python stand-in writes known float samples on a real pipe, so cutting,
  overlaps, gaps, short feeds, exit codes, truncation, Cancel and reaping are proved on real pipes and real processes.
* **Real media**: books made by the pinned FFmpeg from a declared recipe, converted through the real panel on both
  routes. The oracle is the seeking route itself, run on the same book in the same session: every output byte must be
  the same. The selection rule the route reproduces is also checked directly against FFmpeg's own output-side seek,
  including at exact half-sample ties, where neighbouring chapters overlap or leave a gap of one sample.

The size threshold is forced in these tests (0: every eligible book takes the route; infinity: none does), so small,
quick books exercise both routes. The threshold's own value is pinned separately.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import threading
import time
import unittest.mock as mock
from pathlib import Path

import pytest

import tkinter as tk

from shared import ffmpeg_utils, output_paths
from shared import job_control as jc
from shared import subprocess_utils as sp

from m4b import m4b_commands, m4b_continuous, m4b_execution
from m4b.converter import m4b_converter
from m4b.converter.m4b_metadata import AttachedPicture, MetadataMode, SourceTags
from m4b.converter.m4b_plan import ConversionMode, PlanOptions, assemble_plan
from m4b.m4b_continuous import (
    AAC_FRAME_SAMPLES,
    ContinuousDecodeError,
    ContinuousDecoder,
    ContinuousRoute,
    check_packet_lines,
    chapter_frames,
    half_up,
    micros,
    qualify,
    static_refusal,
)
from m4b.m4b_execution import ProcessResult, SegmentWork, convert_segment, run_argv_streaming
from m4b.m4b_naming import segment_filename
from m4b.m4b_probe import AudioStreamFacts, SourceReport

from test_m4b_conversion_plan import (  # noqa: E402
    StubThread,
    _reservation,
    book,
    chapters,
    direct,
    report,
)
from test_import_coordination import RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_metadata import require_ffmpeg  # noqa: E402
import tk_gate  # noqa: E402

#: Every wait here is bounded, so a defect fails rather than hangs.
WAIT = 20.0

#: The genuine method, captured at import, so a test can undo its hook mid-test.
_unhooked_feed = ContinuousDecoder.feed


# --------------------------------------------------------------------------- #
# Which samples a chapter is
# --------------------------------------------------------------------------- #


def test_micros_reads_exactly_what_the_seek_string_says():
    assert micros("0.000000") == 0
    assert micros("12.940000") == 12_940_000
    assert micros("6.882993") == 6_882_993
    for bad in ("1e-07", "6.88", "-1.000000", "6.8829931", "x.000000"):
        with pytest.raises(ValueError):
            micros(bad)


def test_half_up_rounds_a_half_upwards_and_nothing_else():
    assert half_up(5, 10) == 1 and half_up(4, 10) == 0 and half_up(15, 10) == 2 and half_up(14, 10) == 1
    assert half_up(0, 7) == 0 and half_up(7, 7) == 1


#: Rows measured in Phase 7A on real books by exact sample equality (selection-probe.jsonl): S and D as the seeking
#: route wrote them, and the first sample and count FFmpeg actually kept.
MEASURED = [
    (44100, "0.000000", "6.000000", 0, 264600),
    (44100, "6.000000", "6.940000", 264600, 306054),
    (44100, "12.940000", "6.882993", 570654, 303540),
    (22050, "12.940000", "6.882993", 285327, 151770),
    (48000, "12.940000", "6.883000", 621120, 330384),
    (44100, "3.003991", "1.508004", 132476, 66503),
]


@pytest.mark.parametrize("rate, s, d, first, count", MEASURED, ids=[f"{r}Hz-{s}+{d}" for r, s, d, _f, _c in MEASURED])
def test_the_cut_is_the_samples_the_seek_was_measured_to_keep(rate, s, d, first, count):
    start = float(s)
    end = start + float(d)
    assert m4b_commands.segment_times(start, end) == (s, d)
    assert chapter_frames(start, end, rate) == (first, count)


def test_the_cut_rounds_a_half_sample_up_and_less_than_half_down():
    """Real FFmpeg-muxed chapters land on whole samples, so the production cut must be driven at ties explicitly; the
    rule it must follow is FFmpeg's own, proved at ties by the real-media test below."""
    rate = 44100
    for tenths, expect_up in ((5, True), (4, False), (6, True)):
        start_us = _tie_micros(rate, tenths, 2_000_000)
        span_us = 1_000_000
        start = start_us / 1_000_000
        begin, span = m4b_commands.segment_times(start, start + span_us / 1_000_000)
        assert micros(begin) == start_us and micros(span) == span_us, (begin, span)
        exact = start_us * rate // 1_000_000
        assert chapter_frames(start, start + span_us / 1_000_000, rate)[0] == exact + (1 if expect_up else 0), tenths


def test_the_cut_reads_the_strings_the_seeking_route_writes():
    """One renderer for both routes: the seek's argv carries exactly the strings the cut is computed from."""
    argv = m4b_commands.segment_argv(ffmpeg="ff", source="b.m4b", destination="o.mp3", quality=2,
                                     start=12.94, end=19.822993)
    at = argv.index("-ss")
    assert (argv[at + 1], argv[at + 3]) == m4b_commands.segment_times(12.94, 19.822993)
    assert argv.index("-i") < at, "the seeking route still seeks on the output side"


def test_every_chapter_is_cut_at_its_absolute_position_not_a_running_sum():
    """Adding up rounded durations drifts; absolute positions do not. A negative control shows the drift is real."""
    rate = 44100
    starts = [0.0]
    for index in range(400):
        starts.append(round(starts[-1] + 1.5 + (index * 37 % 11) / 1000 + 0.0000005, 6))
    cuts = [chapter_frames(a, b, rate) for a, b in zip(starts, starts[1:])]
    for (a, _b), (first, _count) in zip(zip(starts, starts[1:]), cuts):
        assert first == half_up(micros(m4b_commands.segment_times(a, a + 1)[0]) * rate, 1_000_000)
    seams = [first + count - following for (first, count), (following, _c) in zip(cuts, cuts[1:])]
    assert max(abs(seam) for seam in seams) <= 1, "neighbours overlap or gap by rounding, a sample at most"
    # The control: a running sum of rounded durations wanders far from the absolute positions.
    running, drift = 0, 0
    for first, count in cuts:
        drift = max(drift, abs(running - first))
        running += count
    assert drift > 2


# --------------------------------------------------------------------------- #
# Which books may take the route
# --------------------------------------------------------------------------- #


def facts(**overrides) -> AudioStreamFacts:
    values = dict(audio_streams=1, codec_name="aac", profile="LC", sample_fmt="fltp", sample_rate=44100, channels=2,
                  channel_layout="stereo", time_base="1/44100", start_pts=0, duration_ts=44100 * 600,
                  initial_padding=1024)
    values.update(overrides)
    return AudioStreamFacts(**values)


def eligible_report(**overrides) -> SourceReport:
    base = report(duration=600.0, chapter_list=chapters(*[30.0 * k for k in range(20)]))
    values = dict(probe=base.probe, tags=base.tags, picture=None, stream=facts())
    values.update(overrides)
    return SourceReport(**values)


def test_an_ordinary_aac_lc_split_book_is_statically_eligible():
    assert static_refusal(eligible_report(), split=True) is None


INELIGIBLE = {
    "whole-book output": (dict(), False),
    "chapterless": (dict(probe=report(duration=600.0).probe), True),
    "xhe": (dict(undecodable_xhe=True), True),
    "another decoder": (dict(decoder_args=("-c:a", "aac_at")), True),
    "no facts": (dict(stream=None), True),
    "two audio streams": (dict(stream=facts(audio_streams=2)), True),
    "he-aac": (dict(stream=facts(profile="HE-AAC")), True),
    "not aac": (dict(stream=facts(codec_name="mp3", profile="")), True),
    "s16p": (dict(stream=facts(sample_fmt="s16p")), True),
    "96 kHz": (dict(stream=facts(sample_rate=96000, time_base="1/96000")), True),
    "six channels": (dict(stream=facts(channels=6, channel_layout="5.1")), True),
    "unknown layout": (dict(stream=facts(channel_layout="")), True),
    "mono called stereo": (dict(stream=facts(channels=1)), True),
    "millisecond time base": (dict(stream=facts(time_base="1/1000")), True),
    "late start": (dict(stream=facts(start_pts=1024)), True),
    "no sample count": (dict(stream=facts(duration_ts=None)), True),
    "apple priming": (dict(stream=facts(initial_padding=2112)), True),
    "unknown priming": (dict(stream=facts(initial_padding=None)), True),
}


@pytest.mark.parametrize("name", sorted(INELIGIBLE))
def test_anything_else_keeps_the_seeking_route(name):
    overrides, split = INELIGIBLE[name]
    reason = static_refusal(eligible_report(**overrides), split=split)
    assert reason, name
    decision = qualify(Path("Book.m4b"), eligible_report(**overrides), split=split,
                       scan=lambda *a, **k: pytest.fail("no scan for a book already ruled out"))
    assert decision.route is None and decision.reason == reason


def test_a_book_with_too_little_to_gain_keeps_the_seeking_route_without_a_scan(monkeypatch):
    small = eligible_report(probe=report(duration=30.0, chapter_list=chapters(0.0, 10.0, 20.0)).probe,
                            stream=facts(duration_ts=44100 * 30))
    decision = qualify(Path("b.m4b"), small, split=True, scan=lambda *a, **k: pytest.fail("scanned a small book"))
    assert decision.route is None and decision.reason.startswith("too little to gain")
    monkeypatch.setattr(m4b_continuous, "MIN_SAVED_PREFIX_SECONDS", float("-inf"))
    assert qualify(Path("b.m4b"), small, split=True, scan=lambda *a, **k: None, build=lambda: None).route is not None


def test_a_book_of_a_few_long_chapters_keeps_the_seeking_route_whatever_its_prefix():
    """Moving a whole book through a pipe costs more per second than a decode, so a long book with few chapters gains
    nothing however large its prefix: 2 chapters of 10 minutes have 600 s of prefix and save an estimated -1,800 s."""
    two = eligible_report(probe=report(duration=1200.0, chapter_list=chapters(0.0, 600.0)).probe,
                          stream=facts(duration_ts=44100 * 1200))
    assert m4b_continuous.saved_seconds([0.0, 600.0], 1200.0) == 600.0 - 2.0 * 1200.0
    assert qualify(Path("b"), two, split=True, scan=lambda *a, **k: pytest.fail("scanned"),
                   build=lambda: None).route is None
    many = eligible_report(probe=report(duration=1200.0, chapter_list=chapters(*[60.0 * k for k in range(20)])).probe,
                           stream=facts(duration_ts=44100 * 1200))
    assert qualify(Path("b"), many, split=True, scan=lambda *a, **k: None, build=lambda: None).route is not None


def test_the_threshold_is_the_frozen_calibrated_value():
    """Frozen in Phase 7B from measured small books before final qualification (the Phase 7A/7B record, section 13;
    budget T2). Changing either number is an owner decision, never a way to rescue a failed qualification."""
    assert m4b_continuous.PREFIX_PER_BOOK_SECOND == 2.0
    assert m4b_continuous.MIN_SAVED_PREFIX_SECONDS == 600.0
    assert m4b_continuous.prefix_seconds([0.0, 200.0, 400.0]) == 600.0
    assert m4b_continuous.saved_seconds([0.0, 200.0, 400.0], 600.0) == 600.0 - 1200.0


def test_the_build_fingerprint_reads_the_size_and_both_ends(tmp_path):
    body = bytearray(b"x" * (3 << 20))
    first = tmp_path / "a.exe"
    first.write_bytes(bytes(body))
    print_ = m4b_continuous.executable_fingerprint(first)
    for change in (0, len(body) - 1):
        other = bytearray(body)
        other[change] = ord("y")
        (tmp_path / "b.exe").write_bytes(bytes(other))
        assert m4b_continuous.executable_fingerprint(tmp_path / "b.exe") != print_, change
    (tmp_path / "c.exe").write_bytes(bytes(body) + b"x")
    assert m4b_continuous.executable_fingerprint(tmp_path / "c.exe") != print_


def test_a_proven_book_takes_the_route_with_its_frozen_facts():
    seen = {}

    def scan(source, **kwargs):
        seen.update(kwargs, source=source)
        return None

    decision = qualify(Path("Book.m4b"), eligible_report(), split=True, scan=scan, build=lambda: None)
    assert decision.route == ContinuousRoute(sample_rate=44100, channels=2, total_samples=44100 * 600)
    assert decision.route.pcm_args() == ("-f", "f32le", "-ar", "44100", "-ac", "2")
    assert seen["total"] == 44100 * 600 and seen["priming"] == 1024 and seen["source"] == Path("Book.m4b")


def test_an_unproven_timeline_or_a_failing_scan_keeps_the_seeking_route():
    assert qualify(Path("b"), eligible_report(), split=True, scan=lambda *a, **k: "a gap",
                   build=lambda: None).route is None

    def broken(*args, **kwargs):
        raise RuntimeError("scan blew up")

    decision = qualify(Path("b"), eligible_report(), split=True, scan=broken, build=lambda: None)
    assert decision.route is None and "RuntimeError" in decision.reason


def test_an_ffmpeg_build_the_route_was_not_qualified_on_keeps_the_seeking_route(tmp_path):
    """Byte identity between the routes is established per FFmpeg build; any other build keeps every book seeking."""
    other = [tmp_path / "ffmpeg.exe", tmp_path / "ffprobe.exe"]
    for path in other:
        path.write_bytes(b"some other build")
    reason = m4b_continuous.build_refusal(str(other[0]), str(other[1]))
    assert reason and "not qualified" in reason
    assert "could not be identified" in m4b_continuous.build_refusal(str(tmp_path / "absent.exe"), str(other[1]))
    decision = qualify(Path("b"), eligible_report(), split=True, scan=lambda *a, **k: pytest.fail("scanned"),
                       build=lambda: reason)
    assert decision.route is None and decision.reason == reason


def test_the_qualified_builds_are_exactly_the_builds_the_reference_pins():
    reference = json.loads((Path(__file__).resolve().parents[1] / "dev-work" / "verification-gate" / "scaling"
                            / "reference.json").read_text(encoding="utf-8"))
    pinned = {(build["ffmpeg_fingerprint"], build["ffprobe_fingerprint"]) for build in reference["builds"]}
    assert set(m4b_continuous.QUALIFIED_BUILDS) == pinned
    # Where this machine has a pinned build, its full SHA-256 and its fingerprint must name the same files.
    pair = (ffmpeg_utils.ffmpeg_cmd(), ffmpeg_utils.ffprobe_cmd())
    if all(Path(path).is_file() for path in pair):
        full = tuple(hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in pair)
        for build in reference["builds"]:
            if full == (build["ffmpeg_sha256"], build["ffprobe_sha256"]):
                assert tuple(m4b_continuous.executable_fingerprint(path) for path in pair) == (
                    build["ffmpeg_fingerprint"], build["ffprobe_fingerprint"])


def require_qualified_build() -> None:
    """The real-media proofs below need the build the route is qualified on, or a loud verdict: never a skip."""
    require_ffmpeg()
    reason = m4b_continuous.build_refusal()
    if reason is not None:
        pytest.fail(f"this machine's FFmpeg is not a qualified build ({reason}); the continuous route's real-media "
                    "proofs cannot run here. Qualify the build (files/dev-work/verification-gate/scaling) first.")


# --------------------------------------------------------------------------- #
# The packet timeline
# --------------------------------------------------------------------------- #


def packets(count, *, last=977, priming=True, step=AAC_FRAME_SAMPLES):
    lines = [b"-1024,1024,KD_"] if priming else []
    pts = 0
    for index in range(count):
        duration = last if index == count - 1 else step
        lines.append(f"{pts},{duration},K__".encode())
        pts += duration
    return lines, pts


def test_a_contiguous_timeline_with_one_frame_of_priming_is_proven():
    lines, total = packets(50)
    assert check_packet_lines(lines, total=total, priming=1024) is None


def test_a_timeline_without_an_edit_list_is_proven():
    lines, total = packets(50, priming=False, last=1024)
    assert check_packet_lines(lines, total=total, priming=0) is None


def _edited(lines, index, text):
    lines = list(lines)
    lines[index] = text
    return lines


@pytest.mark.parametrize("name, mutate, why", [
    ("gap", lambda l: _edited(l, 10, b"10240,1024,K__".replace(b"10240", b"10300")), "running sample count"),
    ("short packet before the end", lambda l: _edited(l, 5, b"4096,1000,K__"), "before the last"),
    ("corrupt", lambda l: _edited(l, 7, b"6144,1024,KC_"), "corrupt"),
    ("discard in the middle", lambda l: _edited(l, 9, b"8192,1024,KD_"), "discarded packet"),
    ("apple priming", lambda l: _edited(l, 0, b"-2112,2112,KD_"), "priming of 2112"),
    ("no timestamp", lambda l: _edited(l, 3, b"N/A,1024,K__"), "without a timestamp"),
    ("unreadable", lambda l: _edited(l, 3, b"garbage"), "unreadable"),
])
def test_any_other_timeline_is_not_proven(name, mutate, why):
    lines, total = packets(50)
    verdict = check_packet_lines(mutate(lines), total=total, priming=1024)
    assert verdict and why in verdict, (name, verdict)


def test_the_declared_total_and_padding_must_agree_with_the_packets():
    lines, total = packets(50)
    assert "declares" in check_packet_lines(lines, total=total + 1, priming=1024)
    assert "priming packet" in check_packet_lines(lines, total=total, priming=0)
    bare, total = packets(50, priming=False)
    assert "priming packet" in check_packet_lines(bare, total=total, priming=1024)
    assert check_packet_lines([], total=0, priming=0) == "no audio packets"


def _python_child(code: str):
    """A ``popen`` seam that runs a small Python child in place of FFmpeg/ffprobe, on real pipes."""
    def spawn(argv, **kwargs):
        return sp.popen([sys.executable, "-c", code], **kwargs)
    return spawn


def test_a_cancelled_packet_scan_stops_its_child_at_once():
    endless = ("import sys,time\npts=0\nwhile True:\n    sys.stdout.write(f'{pts},1024,K__\\n'); sys.stdout.flush()\n"
               "    pts += 1024\n    time.sleep(0.01)\n")
    asked = {"at": None}

    def cancelled():
        if asked["at"] is None:
            asked["at"] = time.monotonic() + 0.3
        return time.monotonic() > asked["at"]

    started = time.monotonic()
    verdict = m4b_continuous.scan_packets(Path("b.m4b"), total=10, priming=0, duration_seconds=3600,
                                          cancelled=cancelled, popen=_python_child(endless))
    assert verdict == "the packet scan was cancelled"
    assert time.monotonic() - started < 5.0


def test_a_packet_scan_past_its_deadline_is_unproven(monkeypatch):
    silent = "import time\ntime.sleep(60)\n"
    monkeypatch.setattr(m4b_continuous, "SCAN_BASE_SECONDS", 0.3)
    monkeypatch.setattr(m4b_continuous, "SCAN_SECONDS_PER_HOUR", 0.0)
    started = time.monotonic()
    verdict = m4b_continuous.scan_packets(Path("b.m4b"), total=10, priming=0, duration_seconds=0,
                                          cancelled=lambda: False, popen=_python_child(silent))
    assert verdict == "the packet scan was timed out"
    assert time.monotonic() - started < 5.0


def test_a_failed_packet_scan_is_unproven():
    lines = "import sys\nsys.stdout.write('0,1024,K__\\n1024,977,K__\\n'); sys.exit(3)\n"
    verdict = m4b_continuous.scan_packets(Path("b.m4b"), total=2001, priming=0, duration_seconds=1,
                                          cancelled=lambda: False, popen=_python_child(lines))
    assert verdict == "the packet scan exited 3"


# --------------------------------------------------------------------------- #
# The decoder, on real pipes
# --------------------------------------------------------------------------- #


def _frames(first, count, channels=2) -> bytes:
    """Sample i carries the float value i in every channel, so any misplaced sample is visible."""
    return b"".join(struct.pack("<" + "f" * channels, *([float(i)] * channels)) for i in range(first, first + count))


def _writer_child(total, *, channels=2, exit_code=0, partial=False, linger=False):
    code = (
        "import struct,sys,time\n"
        f"total,channels={total},{channels}\n"
        "out=sys.stdout.buffer\n"
        "for start in range(0,total,4096):\n"
        "    out.write(b''.join(struct.pack('<'+'f'*channels,*([float(i)]*channels)) for i in range(start,min(total,start+4096))))\n"
        + ("out.write(b'\\x00\\x01')\n" if partial else "")
        + "out.flush()\n"
        + ("time.sleep(120)\n" if linger else "")
        + f"sys.exit({exit_code})\n"
    )
    return _python_child(code)


def make_decoder(tmp_path, total, *, declared=None, channels=2, rate=44100, **child) -> ContinuousDecoder:
    route = ContinuousRoute(sample_rate=rate, channels=channels, total_samples=total if declared is None else declared)
    decoder = ContinuousDecoder(route, ffmpeg="ffmpeg", source=tmp_path / "Book.m4b", workspace=tmp_path,
                                popen=_writer_child(total, channels=channels, **child))
    decoder.start()
    return decoder


def collect(decoder, first, count, *, last=False) -> bytes:
    out = bytearray()
    decoder.feed(out.extend, first, count, last=last)
    return bytes(out)


def test_chapters_are_cut_at_absolute_positions_with_overlaps_and_gaps(tmp_path):
    decoder = make_decoder(tmp_path, 200_000)
    try:
        assert collect(decoder, 0, 70_000) == _frames(0, 70_000)
        assert collect(decoder, 69_999, 50_000) == _frames(69_999, 50_000), "a one-sample overlap is served again"
        assert collect(decoder, 120_000, 30_001) == _frames(120_000, 30_001), "a one-sample gap is skipped"
        assert collect(decoder, 150_001, 49_999, last=True) == _frames(150_001, 49_999)
        assert decoder.position == 200_000
    finally:
        assert decoder.close()
    assert decoder.returncode == 0
    assert not list(tmp_path.glob(".act-tmp-*")), "the decoder's diagnostics file is removed"


def test_the_last_chapter_may_end_past_the_book_as_the_seek_would(tmp_path):
    decoder = make_decoder(tmp_path, 50_000)
    try:
        assert len(collect(decoder, 40_000, 10_003, last=True)) == 10_000 * 8
    finally:
        decoder.close()


def test_buffering_is_bounded_whatever_the_length(tmp_path):
    assert m4b_continuous.READ_BLOCK_BYTES + m4b_continuous.TAIL_SECONDS * 48000 * 8 <= m4b_continuous.MAX_BUFFERED_BYTES
    decoder = make_decoder(tmp_path, 48000 * 12, rate=48000)
    try:
        written = [0]
        decoder.feed(lambda data: written.__setitem__(0, written[0] + len(data)), 0, 48000 * 12, last=True)
        assert written[0] == 48000 * 12 * 8
    finally:
        decoder.close()
    assert 0 < decoder.peak_buffered <= m4b_continuous.MAX_BUFFERED_BYTES


@pytest.mark.parametrize("name, kwargs, feed, why", [
    ("short before the end", dict(total=30_000), (0, 40_000, False), "short of this chapter"),
    ("book ends early", dict(total=30_000, declared=60_000), (0, 40_000, False), "declares 60000"),
    ("short book at its end", dict(total=30_000, declared=60_000), (0, 40_000, True), "declares 60000"),
    ("decoder failed", dict(total=30_000, exit_code=1), (0, 30_000, True), "exited 1"),
    ("part of a sample", dict(total=30_000, partial=True), (0, 40_000, True), "part-way through a sample"),
])
def test_a_feed_the_book_cannot_honour_fails_loudly(tmp_path, name, kwargs, feed, why):
    decoder = make_decoder(tmp_path, **kwargs)
    try:
        with pytest.raises(ContinuousDecodeError, match=why):
            collect(decoder, feed[0], feed[1], last=feed[2])
    finally:
        decoder.close()


def test_a_killed_decoder_fails_the_next_chapter_never_ends_the_book(tmp_path):
    decoder = make_decoder(tmp_path, 100_000, linger=True)
    try:
        assert collect(decoder, 0, 40_000) == _frames(0, 40_000)
        decoder._proc.kill()
        with pytest.raises(ContinuousDecodeError):
            collect(decoder, 40_000, 60_000, last=True)
    finally:
        decoder.close()


def test_close_stops_a_running_decoder_and_reaps_it(tmp_path):
    decoder = make_decoder(tmp_path, 1000, linger=True)
    started = time.monotonic()
    assert decoder.close() is True
    assert time.monotonic() - started < 5.0
    assert decoder._proc.poll() is not None
    assert decoder.close() is True, "idempotent"
    with pytest.raises(ContinuousDecodeError):
        collect(decoder, 0, 10)


def test_owned_decoders_closes_whatever_the_body_left_running(tmp_path):
    with pytest.raises(RuntimeError, match="unexpected"):
        with m4b_continuous.owned_decoders():
            decoder = make_decoder(tmp_path, 1000, linger=True)
            raise RuntimeError("unexpected")
    assert decoder._proc.poll() is not None
    assert not list(tmp_path.glob(".act-tmp-*"))


# --------------------------------------------------------------------------- #
# The execution seam
# --------------------------------------------------------------------------- #


def fragment_work(tmp_path, **kwargs) -> SegmentWork:
    values = dict(source=tmp_path / "src" / "Book.m4b", destination=tmp_path / "run" / "Book" / "01 - One.mp3",
                  expected_duration=200.0, quality=2, metadata_mode=MetadataMode.PRESERVE,
                  tags={"title": "One", "track": 1}, span=(0.0, 200.0), continuous_decode=True,
                  pcm_args=("-f", "f32le", "-ar", "44100", "-ac", "2"),
                  picture=AttachedPicture(stream_index=1, codec_name="mjpeg"))
    values.update(kwargs)
    return SegmentWork(**values)


def test_a_continuous_fragment_encodes_the_pipe_and_keeps_the_separate_cover_pass(tmp_path):
    work = fragment_work(tmp_path)
    passes = m4b_execution._passes(work, ffmpeg="ff", staged_final=tmp_path / "final.mp3",
                                   staged_audio=tmp_path / "audio.mp3")
    assert len(passes) == 2
    audio, attach = passes
    assert "-ss" not in audio and "-t" not in audio and audio.count("-i") == 1
    assert audio[audio.index("-i") + 1] == "pipe:0" and audio[-1].endswith("audio.mp3")
    assert ("-c:a", "libmp3lame", "-q:a", "2", "-threads", "0") == audio[-7:-1]
    assert attach == tuple(m4b_commands.attach_artwork_argv(
        ffmpeg="ff", audio=tmp_path / "audio.mp3", artwork_source=work.source, artwork_stream=1,
        destination=str(tmp_path / "final.mp3"), output_args=["-id3v2_version", "3"]))
    seek = m4b_execution._passes(fragment_work(tmp_path, continuous_decode=False), ffmpeg="ff",
                                 staged_final=tmp_path / "final.mp3", staged_audio=tmp_path / "audio.mp3")
    assert seek[1] == attach, "the cover pass is the seeking route's, unchanged"
    assert seek[0].index("-i") < seek[0].index("-ss"), "the seeking route keeps its output-side seek"


def test_a_continuous_fragment_without_a_kept_cover_runs_one_pass(tmp_path):
    for work in (fragment_work(tmp_path, picture=None),
                 fragment_work(tmp_path, metadata_mode=MetadataMode.STRIP, tags={})):
        passes = m4b_execution._passes(work, ffmpeg="ff", staged_final=tmp_path / "final.mp3", staged_audio=None)
        assert len(passes) == 1 and passes[0][-1].endswith("final.mp3") and "pipe:0" in passes[0]


class _Child:
    """Enough of a Popen for the streaming runner: stdin, poll, terminate, wait."""

    def __init__(self, *, exits_after=None):
        self.stdin = self
        self.returncode = None
        self.terminated = False
        self.received = 0
        self._exits_after = exits_after
        self._closed = threading.Event()

    def write(self, data):
        self.received += len(data)

    def flush(self):
        pass

    def close(self):
        self._closed.set()

    def poll(self):
        if self.returncode is None and self._closed.is_set() and self._exits_after is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1

    kill = terminate

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_cancel_stops_the_feed_too_and_is_reported_as_cancelled(tmp_path):
    """The stop hook runs when Cancel stops the encoder; a feed failing because it was stopped is still a Cancel."""
    child = _Child(exits_after="never")
    stopped = threading.Event()

    def feed(write):
        write(b"x" * 8)
        stopped.wait(WAIT)
        raise ContinuousDecodeError("the decoder was stopped")

    outcome = convert_segment(fragment_work(tmp_path, picture=None), ffmpeg="ff", cancelled=lambda: True,
                              measure=lambda p: 200.0, feed=feed, stop_feed=stopped.set,
                              popen=lambda argv, **kw: child, wait=lambda s: None)
    assert stopped.is_set() and child.terminated
    assert outcome.cancelled and not outcome.finalised
    assert not list((tmp_path / "run" / "Book").glob("*.mp3")) and not list((tmp_path / "run" / "Book").glob(".act-tmp-*"))


def test_a_feed_that_outlives_its_encoder_is_a_failure_not_a_success(tmp_path):
    release = threading.Event()

    def feed(write):
        write(b"x")
        release.wait(WAIT)

    child = _Child()
    child.returncode = 0  # the encoder has ended although its input never did
    try:
        result = run_argv_streaming(["ff"], feed=feed, cancelled=lambda: False, workspace=tmp_path,
                                    popen=lambda argv, **kw: child, grace_seconds=0.2, wait=lambda s: None)
    finally:
        release.set()
    assert result.producer_failed and "did not finish" in result.detail


def test_a_feed_failure_without_cancel_still_fails_the_output(tmp_path):
    def feed(write):
        raise ContinuousDecodeError("the decoder exited 1")

    outcome = convert_segment(fragment_work(tmp_path, picture=None), ffmpeg="ff", cancelled=lambda: False,
                              measure=lambda p: 200.0, feed=feed,
                              popen=lambda argv, **kw: _Child(), wait=lambda s: None)
    assert outcome.failed and "could not be decoded" in outcome.message and "exited 1" in outcome.detail


def test_a_continuous_fragment_with_no_feed_is_refused(tmp_path):
    outcome = convert_segment(fragment_work(tmp_path, picture=None), ffmpeg="ff", cancelled=lambda: False,
                              measure=lambda p: 200.0, popen=lambda argv, **kw: _Child(), wait=lambda s: None)
    assert outcome.failed and "continuous decode" in outcome.detail


def test_the_plan_freezes_the_route_only_for_a_split_chaptered_book(tmp_path):
    entries = direct(book(tmp_path / "src", "A"), book(tmp_path / "src", "B"))
    reports = {entry.occurrence_id: report(duration=600.0, chapter_list=chapters(0.0, 200.0, 400.0))
               for entry in entries}
    route = ContinuousRoute(sample_rate=44100, channels=2, total_samples=44100 * 600)
    proven = {entries[0].occurrence_id: route}

    def plan(mode):
        reserve = _reservation(tmp_path / mode.value)
        return assemble_plan(snapshot_id="s", entries=entries, reports=reports, options=PlanOptions(mode=mode),
                             reserve=lambda: (lambda r: (r.run_directory, r.planner()))(reserve("m4b")),
                             windows_decoder=lambda: False, continuous=proven)

    split = plan(ConversionMode.SPLIT)
    assert [item.continuous for item in split.items] == [route, None]
    assert [item.continuous for item in plan(ConversionMode.WHOLE).items] == [None, None]


# --------------------------------------------------------------------------- #
# Real media: the pinned FFmpeg, a declared recipe, the real panel
# --------------------------------------------------------------------------- #


def _ff(*args):
    done = subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-y", *args],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert done.returncode == 0, done.stdout.decode("utf-8", "replace")[-800:]


def _probe(path, *args) -> dict:
    out = subprocess.run([ffmpeg_utils.ffprobe_cmd(), "-v", "error", *args, "-of", "json", str(path)],
                         stdout=subprocess.PIPE, check=True).stdout
    return json.loads(out)


#: Chapter lengths in milliseconds: odd, so boundaries fall between round numbers.
LENGTHS_MS = (3100, 2950, 3333, 2001, 3517, 2899)
TITLES = ("Opening: The Road", "Café Night", "Letters/Rain", "", "Interlude", "Return")


def make_book(folder: Path, name: str, *, rate=44100, channels=2, edit_list=True, cover=True,
              lengths=LENGTHS_MS) -> Path:
    """A deterministic book: per-channel seeded noise plus a modulated tone, AAC-LC by FFmpeg's own encoder, odd
    millisecond chapters with Unicode and unsafe characters in their titles, four book tags and an optional cover.
    Validated before use: chapter count, streams, rate, channels and a complete decode."""
    folder.mkdir(parents=True, exist_ok=True)
    seconds = sum(lengths) / 1000
    left = (f"anoisesrc=c=pink:a=0.06:r={rate}:seed=11:d={seconds}[n1];sine=f=233:r={rate}:d={seconds},"
            f"tremolo=f=2.3:d=0.8[t1];[n1][t1]amix=inputs=2:normalize=0[l]")
    right = (f";anoisesrc=c=brown:a=0.10:r={rate}:seed=23:d={seconds}[n2];sine=f=347:r={rate}:d={seconds},"
             f"tremolo=f=1.7:d=0.6[t2];[n2][t2]amix=inputs=2:normalize=0[r];[l][r]amerge=inputs=2[a]")
    graph = left + (right if channels == 2 else ";[l]anull[a]")
    audio = folder / f"{name}.m4a"
    _ff("-filter_complex", graph, "-map", "[a]", "-c:a", "aac", "-b:a", "96k", str(audio))
    meta = folder / f"{name}.txt"
    lines = [";FFMETADATA1", f"title=Fixture {name}", "artist=Fixture Artist", "album=Fixture Album",
             "album_artist=Fixture Album Artist", ""]
    start = 0
    for index, length in enumerate(lengths):
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={start + length}",
                  f"title={TITLES[index % len(TITLES)]}", ""]
        start += length
    meta.write_text("\n".join(lines), encoding="utf-8")
    out = folder / f"{name}.m4b"
    argv = ["-i", str(audio)]
    maps = ["-map", "0:a"]
    if cover:
        jpg = folder / f"{name}.jpg"
        _ff("-f", "lavfi", "-i", "testsrc2=s=320x320:d=1", "-frames:v", "1", "-q:v", "3", str(jpg))
        argv += ["-i", str(jpg)]
        maps += ["-map", "1:v"]
    argv += ["-i", str(meta)]
    index = len(argv) // 2 - 1
    _ff(*argv, *maps, "-map_metadata", str(index), "-map_chapters", str(index), "-c:a", "copy",
        *(["-c:v", "copy", "-disposition:v:0", "attached_pic"] if cover else []),
        *([] if edit_list else ["-use_editlist", "0"]), str(out))
    probe = _probe(out, "-show_streams", "-show_chapters")
    assert len(probe["chapters"]) == len(lengths)
    stream = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    assert (stream["codec_name"], int(stream["sample_rate"]), int(stream["channels"])) == ("aac", rate, channels)
    _ff("-i", str(out), "-map", "0:a", "-f", "null", "-")
    return out


@pytest.fixture(scope="module")
def books(tmp_path_factory) -> dict:
    require_qualified_build()
    folder = tmp_path_factory.mktemp("continuous_media")
    return {
        "cover": make_book(folder, "WithCover"),
        "plain": make_book(folder, "NoCover", cover=False),
        "noelst": make_book(folder, "NoEditList", edit_list=False),
        "mono22k": make_book(folder, "Mono22k", rate=22050, channels=1),
        "s48k": make_book(folder, "Stereo48k", rate=48000),
        "r96k": make_book(folder, "Stereo96k", rate=96000),
    }


def _decode(path, *tail) -> bytes:
    return subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-i", str(path), *tail,
                           "-map", "0:a:0", "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"],
                          stdout=subprocess.PIPE, check=True).stdout


def _tie_micros(rate: int, fraction_tenths: int, near: int) -> int:
    """The smallest microsecond time at or after *near* whose sample position has exactly this tenth as its fraction."""
    value = near
    while (value * rate) % 1_000_000 != fraction_tenths * 100_000:
        value += 1
    return value


@pytest.mark.parametrize("fraction, neighbour, expect", [(5, 5, "overlap"), (4, 4, "gap")], ids=["overlap", "gap"])
def test_ffmpeg_selects_by_the_half_up_rule_at_ties_and_neighbours_overlap_or_gap(books, fraction, neighbour, expect):
    """The rule the route reproduces, checked against FFmpeg's own output-side seek where rounding matters most.

    Two neighbours whose sample positions both end in exactly .5 overlap by one sample (each rounds up); both ending
    in .4 leave a gap of one (each rounds down, their sum rounds up). FFmpeg must keep exactly the model's samples."""
    source = books["plain"]
    rate, frame = 44100, 8
    full = _decode(source)
    s1 = _tie_micros(rate, fraction, 2_000_000)
    d1 = _tie_micros(rate, neighbour, 1_000_000)
    s2 = s1 + d1
    picks = []
    for s, d in ((s1, d1), (s2, 900_000)):
        s_text, d_text = f"{s // 1_000_000}.{s % 1_000_000:06d}", f"{d // 1_000_000}.{d % 1_000_000:06d}"
        first, count = half_up(micros(s_text) * rate, 1_000_000), half_up(micros(d_text) * rate, 1_000_000)
        assert _decode(source, "-ss", s_text, "-t", d_text) == full[first * frame:(first + count) * frame]
        picks.append((first, count))
    (f1, c1), (f2, _c2) = picks
    assert (f1 + c1 - f2) == (1 if expect == "overlap" else -1)


def test_the_packet_scan_proves_a_real_book_and_its_total(books):
    for name in ("cover", "noelst", "mono22k"):
        stream = next(s for s in _probe(books[name], "-show_streams")["streams"] if s["codec_type"] == "audio")
        verdict = m4b_continuous.scan_packets(
            books[name], total=int(stream["duration_ts"]), priming=int(stream["initial_padding"]),
            duration_seconds=float(stream["duration"]), cancelled=lambda: False)
        assert verdict is None, (name, verdict)
        wrong = m4b_continuous.scan_packets(
            books[name], total=int(stream["duration_ts"]) + 1, priming=int(stream["initial_padding"]),
            duration_seconds=float(stream["duration"]), cancelled=lambda: False)
        assert "declares" in wrong


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


class _Silent:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _ThreadShim:
    Thread = StubThread

    def __getattr__(self, name):
        return getattr(threading, name)


@pytest.fixture()
def make_panel(tk_root, monkeypatch):
    StubThread.started = []
    monkeypatch.setattr(m4b_converter, "threading", _ThreadShim())
    monkeypatch.setattr(m4b_converter.sp, "reveal_in_file_manager", lambda target: None)
    made: list = []

    def build():
        panel = m4b_converter.M4BConverterUI(
            tk_root, effective_config=make_config(), clock=lambda: 0.0, home=None, thread_factory=RecordingThreads(),
            choose_files=lambda: (), choose_folder=lambda: (), confirm_broad_root=lambda roots: False,
            confirm_large_result=lambda outcome: True, bridge=jc.LoggerBridge(logger=_Silent()))
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


@pytest.fixture()
def children(monkeypatch):
    """Every child the run starts, with its command line; checked afterwards for anything left running."""
    started: list = []
    real = sp.popen

    def popen(cmd, **kwargs):
        proc = real(cmd, **kwargs)
        started.append(([str(part) for part in cmd], proc))
        return proc

    monkeypatch.setattr(sp, "popen", popen)
    yield started
    assert all(proc.poll() is not None for _cmd, proc in started), "a child of the run is still running"


def run_split(panel, sources, folder: Path, *, metadata=MetadataMode.PRESERVE, replacement=None):
    panel.importer._choose_files = lambda: tuple(str(p) for p in sources)
    panel.importer.add_files()
    panel.var_mode.set(ConversionMode.SPLIT.value)
    panel.var_metadata_mode.set(metadata.value)
    for name, value in (replacement or {}).items():
        entry = getattr(panel, f"{name}_entry")
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, value)
    panel.start_convert()
    params = StubThread.started[-1].args[0]
    with mock.patch.object(output_paths, "reserve_run_directory", side_effect=_reservation(folder)):
        panel.convert_worker(params)
    panel._pump.tick()
    return panel.run_plan


def digests(run_directory: Path) -> dict:
    return {path.relative_to(run_directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(run_directory.rglob("*")) if path.is_file()}


def kinds(started) -> list[str]:
    out = []
    for cmd, _proc in started:
        if "pipe:1" in cmd:
            out.append("decoder")
        elif "pipe:0" in cmd:
            out.append("pcm")
        elif "-ss" in cmd:
            out.append("seek")
        elif "-show_entries" in cmd:
            out.append("scan")
        elif "copy" in cmd and cmd.count("-i") == 2:
            out.append("attach")
        else:
            out.append("other")
    return out


def both_routes(make_panel, children, monkeypatch, tmp_path, sources, **kwargs):
    results = {}
    for route, threshold in (("seek", float("inf")), ("once", float("-inf"))):
        monkeypatch.setattr(m4b_continuous, "MIN_SAVED_PREFIX_SECONDS", threshold)
        children.clear()
        plan = run_split(make_panel(), sources, tmp_path / route, **kwargs)
        results[route] = (plan, digests(plan.run_directory), kinds(children))
    return results


@pytest.mark.parametrize("metadata, replacement", [
    (MetadataMode.PRESERVE, None),
    (MetadataMode.REPLACE, {"title": "", "artist": "Typed Ärtist", "album": "Typed Album"}),
    (MetadataMode.STRIP, None),
], ids=["preserve", "replace", "strip"])
def test_both_routes_write_the_same_bytes_in_every_metadata_mode(books, make_panel, children, monkeypatch, tmp_path,
                                                                metadata, replacement):
    results = both_routes(make_panel, children, monkeypatch, tmp_path, [books["cover"], books["plain"]],
                          metadata=metadata, replacement=replacement)
    seek_plan, seek, seek_kinds = results["seek"]
    once_plan, once, once_kinds = results["once"]
    assert len(seek) == 2 * len(LENGTHS_MS) and once == seek
    assert all(item.continuous is None for item in seek_plan.items)
    assert all(item.continuous is not None for item in once_plan.items)
    assert once_kinds.count("decoder") == 2 and "seek" not in once_kinds
    assert seek_kinds.count("seek") == 2 * len(LENGTHS_MS) and "decoder" not in seek_kinds
    covered = (metadata is not MetadataMode.STRIP)
    assert once_kinds.count("attach") == seek_kinds.count("attach") == (len(LENGTHS_MS) if covered else 0)
    assert "Café Night" in " ".join(seek), "Unicode titles survive in the names"


@pytest.mark.parametrize("name", ["noelst", "mono22k", "s48k"])
def test_both_routes_write_the_same_bytes_for_each_qualified_stream_shape(books, make_panel, children, monkeypatch,
                                                                          tmp_path, name):
    results = both_routes(make_panel, children, monkeypatch, tmp_path, [books[name]])
    assert results["once"][1] == results["seek"][1] and len(results["once"][1]) == len(LENGTHS_MS)
    assert results["once"][2].count("decoder") == 1 and "seek" not in results["once"][2]


def test_a_rate_lame_does_not_take_keeps_the_seeking_route(books, make_panel, children, monkeypatch, tmp_path):
    monkeypatch.setattr(m4b_continuous, "MIN_SAVED_PREFIX_SECONDS", float("-inf"))
    plan = run_split(make_panel(), [books["r96k"]], tmp_path)
    assert plan.items[0].continuous is None
    assert "decoder" not in kinds(children) and kinds(children).count("seek") == len(LENGTHS_MS)


def test_two_copies_of_one_book_get_numbered_folders_on_the_continuous_route(books, make_panel, children,
                                                                           monkeypatch, tmp_path):
    copy = tmp_path / "other" / books["cover"].name
    copy.parent.mkdir()
    copy.write_bytes(books["cover"].read_bytes())
    results = both_routes(make_panel, children, monkeypatch, tmp_path, [books["cover"], copy])
    assert results["once"][1] == results["seek"][1]
    assert {path.split("/")[0] for path in results["once"][1]} == {"WithCover", "WithCover-1"}


def _feed_hook(monkeypatch, at_chapter: int, action):
    """Run *action(decoder)* when the continuous decoder is asked for chapter *at_chapter* (1-based), once."""
    real = ContinuousDecoder.feed
    calls = {"n": 0}

    def feed(self, write, first, count, *, last):
        calls["n"] += 1
        if calls["n"] == at_chapter:
            action(self)
        return real(self, write, first, count, last=last)

    monkeypatch.setattr(ContinuousDecoder, "feed", feed)


def _retry(panel):
    assert panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED) is True, "Retry Failed was not offered"
    params = StubThread.started[-1].args[0]
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=AssertionError("a retry reserved a run directory")):
        panel.convert_worker(params)
    panel._pump.tick()


@pytest.mark.parametrize("victim", ["decoder", "encoder"])
def test_a_killed_process_fails_its_book_and_retry_repeats_it_exactly(books, make_panel, children, monkeypatch,
                                                                     tmp_path, victim):
    monkeypatch.setattr(m4b_continuous, "MIN_SAVED_PREFIX_SECONDS", float("-inf"))
    reference = digests(run_split(make_panel(), [books["cover"]], tmp_path / "clean").run_directory)
    source_hash = hashlib.sha256(books["cover"].read_bytes()).hexdigest()

    def kill(decoder):
        if victim == "decoder":
            decoder._proc.kill()
            decoder._proc.wait(WAIT)
        else:
            encoder = next(proc for cmd, proc in reversed(children) if "pipe:0" in cmd)
            encoder.kill()

    children.clear()
    _feed_hook(monkeypatch, 4, kill)
    panel = make_panel()
    plan = run_split(panel, [books["cover"]], tmp_path / "killed")
    assert panel.run_result.state is jc.JobState.COMPLETED_WITH_FAILURES
    assert digests(plan.run_directory) == {}, "a book with a failed chapter keeps none of its chapters"
    monkeypatch.setattr(ContinuousDecoder, "feed", _unhooked_feed)
    decoders_before = kinds(children).count("decoder")
    _retry(panel)
    assert panel.run_result.state is jc.JobState.SUCCEEDED
    assert kinds(children).count("decoder") == decoders_before + 1, "the retry starts a fresh decoder"
    assert digests(plan.run_directory) == reference
    assert hashlib.sha256(books["cover"].read_bytes()).hexdigest() == source_hash



def test_cancel_during_a_late_chapter_reaps_both_processes_and_keeps_the_finished_book(books, make_panel, children,
                                                                                       monkeypatch, tmp_path):
    monkeypatch.setattr(m4b_continuous, "MIN_SAVED_PREFIX_SECONDS", float("-inf"))
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        panel = make_panel()
        timing = {}

        def cancel(decoder):
            timing["asked"] = time.monotonic()
            panel._cancel_event.set()

        _feed_hook(monkeypatch, len(LENGTHS_MS) + 5, cancel)  # the second book's fifth chapter
        plain_hash = hashlib.sha256(books["plain"].read_bytes()).hexdigest()
        plan = run_split(panel, [books["cover"], books["plain"]], tmp_path)
        settled = time.monotonic() - timing["asked"]
        assert panel.run_result.cancelled
        produced = digests(plan.run_directory)
        assert len(produced) == len(LENGTHS_MS) and all(path.startswith("WithCover/") for path in produced)
        assert not (plan.run_directory / "NoCover").exists(), "the cancelled book is taken back and its folder pruned"
        assert settled < 10.0
        assert all(proc.poll() is not None for _cmd, proc in children)
        assert sentinel.poll() is None, "an unrelated Python process is untouched"
        assert hashlib.sha256(books["plain"].read_bytes()).hexdigest() == plain_hash
    finally:
        sentinel.kill()
        sentinel.wait(WAIT)


def test_pause_between_chapters_then_resume_gives_the_same_bytes(books, make_panel, children, monkeypatch, tmp_path):
    monkeypatch.setattr(m4b_continuous, "MIN_SAVED_PREFIX_SECONDS", float("-inf"))
    reference = digests(run_split(make_panel(), [books["cover"]], tmp_path / "plain").run_directory)
    panel = make_panel()
    paused = {}

    def pause(decoder):
        panel.pause()
        paused["at"] = time.monotonic()
        threading.Timer(0.5, panel.resume).start()

    _feed_hook(monkeypatch, 3, pause)
    plan = run_split(panel, [books["cover"]], tmp_path / "paused")
    assert panel.run_result.state is jc.JobState.SUCCEEDED
    assert digests(plan.run_directory) == reference
    assert "at" in paused


def test_an_occupied_destination_fails_the_book_and_foreign_files_are_left_alone(books, make_panel, children,
                                                                                monkeypatch, tmp_path):
    monkeypatch.setattr(m4b_continuous, "MIN_SAVED_PREFIX_SECONDS", float("-inf"))
    panel = make_panel()
    planted = {}

    def plant(decoder):
        folder = decoder._workspace / "WithCover"
        planted["occupied"] = folder / segment_filename(3, len(LENGTHS_MS), TITLES[2])
        planted["occupied"].write_bytes(b"someone else's file")
        planted["foreign"] = folder / ".act-tmp-foreign-1234.mp3"
        planted["foreign"].write_bytes(b"not this run's")

    _feed_hook(monkeypatch, 2, plant)
    plan = run_split(panel, [books["cover"]], tmp_path)
    assert panel.run_result.state is jc.JobState.COMPLETED_WITH_FAILURES
    assert planted["occupied"].read_bytes() == b"someone else's file"
    assert planted["foreign"].read_bytes() == b"not this run's"
    left = {path.name for path in planted["occupied"].parent.iterdir()}
    assert left == {planted["occupied"].name, planted["foreign"].name}, left
    assert not list(plan.run_directory.glob(".act-tmp-*")), "the decoder's own diagnostics file is gone"


def test_a_book_whose_audio_is_damaged_fails_on_the_continuous_route_without_publishing(books, make_panel, children,
                                                                                         monkeypatch, tmp_path):
    """Damaged frames inside an intact index. FFmpeg's decoder skips them and still exits 0 (measured: 16,384 of 784,980
    samples lost), so the decoder produces fewer samples than the book declares and the route refuses the book rather
    than publish chapters it cannot vouch for. Nothing is published and the source is never touched. (The seeking route
    has no such check; Phase 7A's approved design makes the declared total a backstop of this route.)"""
    monkeypatch.setattr(m4b_continuous, "MIN_SAVED_PREFIX_SECONDS", float("-inf"))
    damaged = tmp_path / "src" / "Damaged.m4b"
    damaged.parent.mkdir()
    data = bytearray(books["plain"].read_bytes())
    middle = len(data) // 2
    data[middle:middle + 4096] = bytes((index * 37 + 11) % 256 for index in range(4096))
    damaged.write_bytes(bytes(data))
    before = hashlib.sha256(damaged.read_bytes()).hexdigest()
    panel = make_panel()
    plan = run_split(panel, [damaged], tmp_path / "run")
    assert plan.items[0].continuous is not None, "the index is intact, so the route was chosen"
    assert panel.run_result.state is jc.JobState.COMPLETED_WITH_FAILURES
    failure = panel.run_result.failures.records[0]
    assert "could not be decoded" in failure.display_message and "declares" in failure.technical_detail
    assert failure.retryable
    assert digests(plan.run_directory) == {}
    assert hashlib.sha256(damaged.read_bytes()).hexdigest() == before
