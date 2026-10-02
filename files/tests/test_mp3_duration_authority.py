"""Split MP3 headers must not determine Time edits or authorize publication.

The 2026-09-20 macOS failure was a CBR Info header still claiming 17,612
frames after a split left only 16,306; its companion held the other 1,306.
Both ffprobe duration and Mutagen believed the stale total. +0.1 preserved
all 425.940658 seconds, but validation expected 460.168571 and refused it.

Generate that shape at ten seconds, cutting only at a packet boundary. Use
raw decoded PCM length as the independent oracle, never the production
duration helper or a duration field. No private audiobook fixture is needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mutagen.id3 import ID3

from shared import ffmpeg_utils
from shared import subprocess_utils as sp
from mp3_tools import mp3_processing as proc

from test_mp3_write_id3 import (  # noqa: F401 - shared fixtures
    book, imported, junk_tag, observe, plan, png, reserve, sha, sources, workspace,
)
from test_mp3_combine import plan as combine_plan


needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg_utils.have_ffmpeg(), reason="the pinned FFmpeg pair is unavailable")


def probe(path: Path, *options) -> dict:
    result = sp.run([ffmpeg_utils.ffprobe_cmd(), "-v", "error", *options,
                     "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def header_duration(path: Path) -> float:
    return float(probe(path, "-show_entries", "format=duration")["format"]["duration"])


def pcm_duration(path: Path) -> float:
    rate = int(probe(path, "-select_streams", "a:0", "-show_entries",
                     "stream=sample_rate")["streams"][0]["sample_rate"])
    result = sp.run([ffmpeg_utils.ffmpeg_cmd(), "-v", "error", "-xerror",
                     "-i", str(path), "-map", "0:a:0", "-ac", "1",
                     "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"],
                    capture_output=True, check=True)
    assert not result.stderr
    return len(result.stdout) / (2 * rate)


def cut_at_packet(path: Path, seconds: float) -> None:
    packets = probe(path, "-select_streams", "a:0", "-show_packets")["packets"]
    boundary = next(int(p["pos"]) for p in packets if float(p["pts_time"]) >= seconds)
    path.write_bytes(path.read_bytes()[:boundary])


@pytest.fixture(params=[(44100, 1, "cbr"), (24000, 2, "vbr")],
                ids=["mpeg1-mono-Info", "mpeg2-stereo-Xing"])
def split_source(sources, request):
    rate, channels, mode = request.param
    entry = imported(sources, "Book", "Author's Note.mp3", junk=False)
    path = entry.path
    encoding = ["-b:a", "64k"] if mode == "cbr" else ["-q:a", "2"]
    sp.run([ffmpeg_utils.ffmpeg_cmd(), "-v", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
            "-ar", str(rate), "-ac", str(channels), "-c:a", "libmp3lame",
            *encoding, str(path)],
           check=True)
    assert (b"Info" if mode == "cbr" else b"Xing") in path.read_bytes()[:512]
    cut_at_packet(path, 8.0)
    actual = pcm_duration(path)
    assert 7.8 < actual < 8.1
    assert header_duration(path) > actual + 1.8, "fixture must retain a stale total"
    return entry, actual


@needs_ffmpeg
def test_duration_reads_headerless_audio_despite_a_discarded_bad_cover(tmp_path):
    path = tmp_path / "headerless.mp3"
    sp.run([ffmpeg_utils.ffmpeg_cmd(), "-v", "error", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=2", "-c:a", "libmp3lame",
            "-write_xing", "0", str(path)], check=True)
    actual = pcm_duration(path)
    # Source covers are always discarded. The duration reader must decode
    # audio strictly without treating a junk APIC as broken audio.
    junk_tag(path, with_art=True)
    assert proc.ffprobe_duration_seconds(path) == pytest.approx(actual, abs=0.00005)


@needs_ffmpeg
@pytest.mark.parametrize("delta", [0.1, 0.0, -0.1])
def test_write_id3_uses_decoded_duration_for_all_time_modes(
        split_source, delta, reserve, tmp_path):
    source, actual = split_source
    before = sha(source.path)
    cover = png(tmp_path / "cover.png")
    entry = book([source], time_delta=str(delta), artwork=str(cover), album="Book")
    made = plan(workspace(entry), observe(entry), reserve)
    report = proc.write_id3_run(made)
    track = made.books[0].tracks[0]
    assert report.books[0].succeeded
    assert track.published.is_file()
    # Much tighter than the validation tolerance: -0.1 must really remove
    # samples, not silently leave the full file because the endpoint is stale.
    assert pcm_duration(track.published) == pytest.approx(actual + delta, abs=0.002)
    assert ID3(track.published).getall("APIC")[0].data == cover.read_bytes()
    assert sha(source.path) == before


@needs_ffmpeg
@pytest.mark.parametrize("safe", [False, True], ids=["FAST", "Safe"])
def test_combine_trims_every_constituent_on_the_decoded_timeline(
        split_source, reserve, monkeypatch, safe):
    source, actual = split_source
    before = sha(source.path)
    second = imported(source.path.parent, "Other", "second.mp3", seconds=3.0, with_art=False)
    second_duration = pcm_duration(second.path)
    entry = book([source, second], time_delta="-0.1", album="Book")
    made = combine_plan(workspace(entry), observe(entry), reserve)
    if safe:
        monkeypatch.setattr(proc, "fast_eligibility", lambda _: (False, "exercise Safe"))
    original_combine = proc._combine_constituents
    measured = []

    def inspect_constituents(book_plan, constituents, **kwargs):
        measured.extend(pcm_duration(p) for p in constituents)
        assert measured == pytest.approx([actual - 0.1, second_duration - 0.1], abs=0.002)
        return original_combine(book_plan, constituents, **kwargs)

    monkeypatch.setattr(proc, "_combine_constituents", inspect_constituents)
    report = proc.combine_run(made)
    assert report.books[0].succeeded
    assert len(measured) == 2
    out = made.books[0]
    # FAST may retain a small amount of encoder padding at the join.
    assert pcm_duration(out.combined_published) == pytest.approx(sum(measured), abs=0.08)
    lines = out.timestamps_published.read_text(encoding="utf-8").splitlines()
    assert f"@ {proc.seconds_to_hms(measured[0])} " in lines[1]
    assert sha(source.path) == before


@needs_ffmpeg
def test_excessive_trim_uses_actual_length_before_staging(split_source, reserve):
    source, actual = split_source
    entry = book([source], time_delta=str(-(actual + 0.1)))
    made = plan(workspace(entry), observe(entry), reserve)
    report = proc.write_id3_run(made)
    assert not report.books[0].succeeded
    assert report.books[0].result.failures.records[0].stage == "trim"
    assert not made.books[0].published_dir.exists()


@needs_ffmpeg
@pytest.mark.parametrize("damage", ["truncate-with-stale-header", "corrupt"])
def test_bad_staged_output_still_prevents_publication(
        split_source, reserve, monkeypatch, damage):
    source, actual = split_source
    before = sha(source.path)
    entry = book([source], time_delta="0.1")
    made = plan(workspace(entry), observe(entry), reserve)
    original_writer = proc._write_whitelist

    def damage_after_tags(book_plan, track, artwork):
        original_writer(book_plan, track, artwork)
        if damage == "corrupt":
            track.staged.write_bytes(b"not an MP3")
        else:
            cut_at_packet(track.staged, 4.0)
            # A header-only validator would falsely approve this damaged output.
            assert header_duration(track.staged) == pytest.approx(actual + 0.1, abs=0.002)
            assert pcm_duration(track.staged) < actual - 3

    monkeypatch.setattr(proc, "_write_whitelist", damage_after_tags)
    report = proc.write_id3_run(made)
    assert not report.books[0].succeeded
    assert report.books[0].result.failures.records[0].stage == "validate"
    assert not made.books[0].published_dir.exists()
    assert sha(source.path) == before


@pytest.mark.parametrize("code,out,err", [
    (1, "out_time_us=8000000\nprogress=end\n", ""),
    (0, "out_time_us=8000000\nprogress=end\n", "Error decoding frame"),
    (0, "out_time_us=8000000\nprogress=continue\n", ""),
    (0, "progress=end\n", ""),
    (0, "out_time_us=N/A\nprogress=end\n", ""),
    (0, "out_time_us=0\nprogress=end\n", ""),
    (0, "out_time_us=-1\nprogress=end\n", ""),
])
def test_duration_refuses_incomplete_or_failed_decode(monkeypatch, tmp_path, code, out, err):
    monkeypatch.setattr(ffmpeg_utils, "ffmpeg_cmd", lambda: "/proved/ffmpeg")
    monkeypatch.setattr(proc, "run_ff", lambda _: (code, out, err))
    source = tmp_path / "unused.mp3"
    source.write_bytes(b"not audio")
    assert proc.ffprobe_duration_seconds(source) is None


def test_trim_from_end_fails_safely_when_duration_is_unreadable(monkeypatch, tmp_path):
    """An unreadable duration must never be treated as zero-length: that would
    silently trim to ``-t 0.000000`` and hand back a near-empty file while
    still reporting success."""
    monkeypatch.setattr(proc, "ffprobe_duration_seconds", lambda _: None)
    ran: list = []

    def fake_run_ff(args):
        ran.append(args)
        return 0, "", ""

    monkeypatch.setattr(proc, "run_ff", fake_run_ff)
    log_dir = tmp_path / "logs"
    ok = proc.trim_from_end_mp3(Path("in.mp3"), 5.0, tmp_path / "out.mp3", log_dir)
    assert ok is False
    assert ran == [], "ffmpeg must never run against a fabricated zero-length duration"
    assert (log_dir / "ffmpeg_log.txt").exists()


@pytest.fixture
def joined_source(sources, tmp_path, monkeypatch):
    """Actual failing shape: raw concatenation of tagged 24 kHz mono segments.

    The independent oracle retains the first segment verbatim and starts each
    later segment at its first *audio packet*, omitting ID3 and the Info frame.
    No production parser or duration helper builds/measures that oracle.
    """
    from shared import paths
    monkeypatch.setattr(paths, "RESOURCES_DIR", tmp_path / "runtime")
    entry = imported(sources, "Book", "Joined.mp3", junk=False)
    segments, playable = [], []
    for index in range(3):
        segment = tmp_path / f"segment-{index}.mp3"
        sp.run([ffmpeg_utils.ffmpeg_cmd(), "-v", "error", "-y", "-f", "lavfi",
                "-i", f"sine=frequency={440 + index * 220}:duration=1",
                "-ar", "24000", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "64k",
                str(segment)], check=True)
        data = segment.read_bytes()
        first_packet = int(probe(segment, "-select_streams", "a:0", "-show_packets")
                           ["packets"][0]["pos"])
        assert data.startswith(b"ID3") and b"Info" in data[:first_packet]
        segments.append(data)
        playable.append(data if index == 0 else data[first_packet:])
    entry.path.write_bytes(b"".join(segments))
    oracle = tmp_path / "oracle.mp3"
    oracle.write_bytes(b"".join(playable))
    return entry, pcm_duration(oracle), segments


@needs_ffmpeg
def test_join_metadata_is_not_an_audio_decode_failure(joined_source, tmp_path):
    source, actual, _ = joined_source
    before = sha(source.path)
    # Prove that the fixture exercises the real command's Header missing error.
    assert proc._decode_duration_seconds(source.path) is None
    assert proc.ffprobe_duration_seconds(source.path) == pytest.approx(actual, abs=0.00005)
    with proc._prepared_mp3(source.path, tmp_path) as prepared:
        assert prepared != source.path
        assert proc._decode_duration_seconds(prepared) == pytest.approx(actual, abs=0.00005)
    assert not prepared.exists()
    assert sha(source.path) == before


@needs_ffmpeg
@pytest.mark.parametrize("delta", [0.0, 0.1, -0.1])
def test_joined_source_write_id3_preserves_audio_and_signed_time(joined_source, reserve, delta):
    source, actual, _ = joined_source
    before = sha(source.path)
    entry = book([source], time_delta=str(delta), album="Joined Book", auto_number=True)
    made = plan(workspace(entry), observe(entry), reserve)
    report = proc.write_id3_run(made)
    track = made.books[0].tracks[0]
    assert report.books[0].succeeded
    assert pcm_duration(track.published) == pytest.approx(actual + delta, abs=0.002)
    assert ID3(track.published)["TIT2"].text == [track.title]
    assert sha(source.path) == before
    assert not list(made.reservation.run_directory.rglob("mp3-input-*"))


@needs_ffmpeg
@pytest.mark.parametrize("safe", [False, True], ids=["FAST", "Safe"])
def test_joined_source_combine_uses_the_same_audio_timeline(joined_source, reserve, monkeypatch, safe):
    source, actual, _ = joined_source
    before = sha(source.path)
    # A second occurrence must carry its own identity.
    from dataclasses import replace
    second = replace(source, occurrence_id=source.occurrence_id + "-second")
    entry = book([source, second], time_delta="-0.1", album="Joined Book")
    made = combine_plan(workspace(entry), observe(entry), reserve)
    if safe:
        monkeypatch.setattr(proc, "fast_eligibility", lambda _: (False, "exercise Safe"))
    report = proc.combine_run(made)
    assert report.books[0].succeeded
    result = made.books[0]
    assert pcm_duration(result.combined_published) == pytest.approx(2 * (actual - 0.1), abs=0.08)
    assert f"@ {proc.seconds_to_hms(actual - 0.1)} " in result.timestamps_published.read_text()
    assert sha(source.path) == before


@needs_ffmpeg
@pytest.mark.parametrize("damage", ["bad-tag-size", "oversized-tag", "audio-header", "audio-payload"])
def test_joined_source_damage_still_blocks_whole_book(joined_source, reserve, damage):
    source, _, segments = joined_source
    data = bytearray(source.path.read_bytes())
    boundary = len(segments[0])
    if damage == "bad-tag-size":
        data[boundary + 9] |= 128  # invalid synchsafe length, never remove it
    elif damage == "oversized-tag":
        # A plausible but corrupt tag size must not swallow an entire segment.
        claimed = len(segments[1]) + proc._id3_size(data[boundary:boundary + 10]) - 10
        data[boundary + 6:boundary + 10] = bytes((claimed >> n) & 127 for n in (21, 14, 7, 0))
    else:
        first_audio = boundary + int(probe(source.path.parents[2] / "segment-1.mp3",
                                          "-select_streams", "a:0", "-show_packets")
                                     ["packets"][0]["pos"])
        if damage == "audio-header":
            data[first_audio:first_audio + 4] = b"BAD!"
        else:
            # Invalid Layer III side information while retaining a valid header.
            data[first_audio + 4:first_audio + 13] = b"\xff" * 9
    source.path.write_bytes(data)
    before = sha(source.path)
    good = imported(source.path.parent.parent, "Other", "Good.mp3", junk=False)
    entry = book([good, source], album="Joined Book")
    made = plan(workspace(entry), observe(entry), reserve)
    report = proc.write_id3_run(made)
    assert not report.books[0].succeeded
    assert len(report.books[0].staged_ok) == 1
    assert report.books[0].result.failures.records[0].stage == "probe"
    assert not made.books[0].published_dir.exists()
    assert sha(source.path) == before


@needs_ffmpeg
@pytest.mark.parametrize("delta", [0.1, -0.1])
def test_joined_source_standalone_time_helpers(joined_source, tmp_path, delta):
    source, actual, _ = joined_source
    before = sha(source.path)
    target = tmp_path / "adjusted.mp3"
    if delta > 0:
        assert proc.add_silence_to_mp3(source.path, delta, target, tmp_path)
    else:
        assert proc.trim_from_end_mp3(source.path, -delta, target, tmp_path)
    assert pcm_duration(target) == pytest.approx(actual + delta, abs=0.002)
    assert sha(source.path) == before
    assert not list(tmp_path.glob("mp3-input-*"))


@needs_ffmpeg
def test_id3_signature_inside_audio_payload_is_never_removed(joined_source):
    source, _, _ = joined_source
    before = proc._embedded_metadata_ranges(source.path)
    packet = probe(source.path, "-select_streams", "a:0", "-show_packets")["packets"][2]
    data = bytearray(source.path.read_bytes())
    offset = int(packet["pos"]) + 40
    data[offset:offset + 10] = b"ID3\x04\x00\x00\x00\x00\x00#"
    source.path.write_bytes(data)
    assert proc._embedded_metadata_ranges(source.path) == before
