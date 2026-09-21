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
def test_duration_refuses_incomplete_or_failed_decode(monkeypatch, code, out, err):
    monkeypatch.setattr(ffmpeg_utils, "ffmpeg_cmd", lambda: "/proved/ffmpeg")
    monkeypatch.setattr(proc, "run_ff", lambda _: (code, out, err))
    assert proc.ffprobe_duration_seconds(Path("unused.mp3")) is None
