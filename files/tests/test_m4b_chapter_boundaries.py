"""v0.7.0 acceptance D4: an M4B Maker book's chapter marks sit on the audible boundaries, and an M4B Converter split
at those marks gives every chapter back whole.

The acceptance run found each Converter chapter of a Maker book ending early ("…the Barge Master claimed" became
"…claims"). Two offsets stacked: the Maker put every mark 250 ms before its chapter (``LEADIN_MS``), and FAST's
``-avoid_negative_ts make_zero`` pulled the AAC encoder's 1024 priming samples into the timeline, so the audio ran a
further 1024 samples (42.7 ms at 24 kHz) behind the marks. Fast-first off without inserted silence had the same priming
shift through a resampled concat. And FAST took its starts from ffprobe's header duration, which for an MP3 without a
Xing header is an estimate (189 ms short on a 7.3 s VBR file).

Each chapter source here is deterministic seeded noise -- so it has one unambiguous position in the book -- ending in a
louder "final word" burst and a 150 ms silent tail like ACT's own narration. Every source is located in the decoded
book by cross-correlation and must start at its mark (to the millisecond the marks are written in). The Converter's
own probe, timeline and segment command then split the book, and every split must hold its whole source -- the final
burst included -- with nothing of its neighbours: no truncation, no duplication, no gap, no overlap.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePath

import numpy as np
import pytest

from shared import ffmpeg_utils
from shared.importing import ImportedFile, ImportRoot
from m4b import m4b_chapters, m4b_commands, m4b_probe
from m4b.maker import m4b_maker_plan as mp
from m4b.maker import m4b_maker_processing as proc

from test_m4b_maker_processing import _IDS, book, build, plan, require_ffmpeg, reserve, sources, workspace  # noqa: F401

RATE = 24_000          # what every comparison is decoded to (ACT narration's own rate)
TOLERANCE_MS = 2.0     # marks are written in whole milliseconds; anything near the old 43-293 ms fails
BODY_S, WORD_S, TAIL_S = 1.2, 0.12, 0.15


@pytest.fixture(autouse=True)
def _ffmpeg():
    require_ffmpeg()


def _run(argv):
    done = subprocess.run(argv, capture_output=True)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-800:]
    return done.stdout


def chapter_source(path: Path, seed: int, *, encoder=("-c:a", "libmp3lame", "-b:a", "160k")) -> Path:
    """Seeded pink noise, a louder white-noise "final word", then a 150 ms silent tail; mono 24 kHz MP3."""
    path.parent.mkdir(parents=True, exist_ok=True)
    graph = (f"anoisesrc=d={BODY_S}:c=pink:r={RATE}:a=0.2:seed={seed}[a];"
             f"anoisesrc=d={WORD_S}:c=white:r={RATE}:a=0.6:seed={seed + 100}[b];"
             f"aevalsrc=0:d={TAIL_S}:s={RATE}[c];[a][b][c]concat=n=3:v=0:a=1[out]")
    _run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-y", "-filter_complex", graph,
          "-map", "[out]", "-ac", "1", "-ar", str(RATE), *encoder, str(path)])
    return path


def decode(path: Path) -> np.ndarray:
    raw = _run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-i", str(path), "-map", "0:a:0",
                "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"])
    return np.frombuffer(raw, dtype="<f4").astype(np.float64)


def locate(haystack: np.ndarray, needle: np.ndarray) -> int:
    """Sample offset of *needle* inside *haystack* (FFT cross-correlation peak)."""
    size = 1 << (len(haystack) + len(needle)).bit_length()
    corr = np.fft.irfft(np.fft.rfft(haystack, size) * np.conj(np.fft.rfft(needle, size)), size)
    return int(np.argmax(corr[: len(haystack) - len(needle) + 1]))


def snr_db(reference: np.ndarray, candidate: np.ndarray) -> float:
    noise = np.sum((candidate - reference) ** 2)
    return float(10 * np.log10(np.sum(reference ** 2) / max(noise, 1e-12)))


def maker_book(sources_root, reserve, files, *, options=None, **configuration):
    imported = []
    for path in files:
        occurrence = _IDS.next_id("occurrence")
        imported.append(ImportedFile(occurrence, path, ImportRoot("r", sources_root, 0),
                                     PurePath(path.relative_to(sources_root)), "mp3", f"id-{occurrence}"))
    entry = book(imported, **configuration)
    made = plan(workspace(entry), mp.standard_destination(reserve()), options)
    return made, made.books[0]


def marks_of(m4b: Path) -> tuple[tuple[float, ...], float]:
    report = m4b_probe.probe_source(m4b)
    assert report.ok, report.probe.detail
    return tuple(c.start for c in report.probe.chapters), report.probe.duration


def converter_split(m4b: Path, out_dir: Path) -> list[Path]:
    """The Converter's own chapter read, timeline partition and segment command."""
    report = m4b_probe.probe_source(m4b)
    outputs = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for span in m4b_chapters.plan_timeline(report.probe):
        destination = out_dir / f"{span.order:02d}.mp3"
        _run(m4b_commands.segment_argv(ffmpeg=ffmpeg_utils.ffmpeg_cmd(), source=str(m4b),
                                       destination=str(destination), quality=2, start=span.start, end=span.end,
                                       decoder_args=report.decoder_args))
        outputs.append(destination)
    return outputs


def assert_marks_are_the_boundaries(m4b: Path, originals: list[np.ndarray], gap_s: float = 0.0):
    marks, _duration = marks_of(m4b)
    decoded = decode(m4b)
    assert len(marks) == len(originals)
    expected = 0
    for number, (mark, original) in enumerate(zip(marks, originals), 1):
        found = locate(decoded, original)
        assert abs(found - expected) <= 2, f"chapter {number}: the audio sits where the sources add up to"
        assert abs(found / RATE - mark) * 1000 <= TOLERANCE_MS, (
            f"chapter {number}: audio starts at {found / RATE:.4f}s, its mark at {mark:.4f}s")
        assert snr_db(original, decoded[found:found + len(original)]) > 6, f"chapter {number} is intact in the book"
        expected = found + len(original) + int(round(gap_s * RATE))
    assert abs(len(decoded) - (expected - int(round(gap_s * RATE)))) <= 2, "nothing added or lost at the end"


def assert_split_returns_every_chapter_whole(m4b: Path, originals: list[np.ndarray], out_dir: Path,
                                             gap_s: float = 0.0):
    parts = [decode(p) for p in converter_split(m4b, out_dir)]
    assert len(parts) == len(originals)
    word = int((WORD_S + TAIL_S) * RATE)
    for number, (part, original) in enumerate(zip(parts, originals), 1):
        trailing_gap = gap_s if number < len(originals) else 0.0
        expected = len(original) + int(round(trailing_gap * RATE))
        assert abs(len(part) - expected) / RATE * 1000 <= TOLERANCE_MS + 1, (
            f"chapter {number}: {len(part) / RATE:.4f}s split, {expected / RATE:.4f}s expected")
        found = locate(part, original[: len(original) // 2])
        assert found <= 2, f"chapter {number} starts with its own first sample, not a neighbour's ({found} samples in)"
        # Two lossy generations of noise (MP3 -> AAC -> MP3) measure ~9-12 dB against the original; a shifted or
        # truncated ending is below 0 dB. The burst's own energy must also arrive whole.
        ending = part[len(original) - word: len(original)]
        assert len(ending) == word and snr_db(original[-word:], ending) > 6, (
            f"chapter {number}: its final word and tail are all there")
        burst = slice(len(original) - word, len(original) - int(TAIL_S * RATE))
        assert abs(20 * np.log10(np.std(part[burst]) / np.std(original[burst]))) < 1.5, (
            f"chapter {number}: the final word arrives at full strength")
        if number > 1:
            previous = originals[number - 2][-word:]
            head = part[: 2 * word]
            leaked = locate(np.concatenate([head, np.zeros(word)]), previous)
            assert snr_db(previous, np.concatenate([head, np.zeros(word)])[leaked:leaked + word]) < 0, (
                f"chapter {number} does not begin with the end of chapter {number - 1}")


def test_fast_marks_and_a_converter_split_match_the_chapters_exactly(sources, reserve, tmp_path):
    files = [chapter_source(sources / "Book" / f"0{n} Part {n}.mp3", seed=n) for n in (1, 2, 3)]
    made, entry = maker_book(sources, reserve, files, title="Fast Boundaries")
    outcome = build(made, entry)
    assert outcome.succeeded and outcome.path_used == "fast", outcome.failure_detail
    originals = [decode(p) for p in files]
    assert_marks_are_the_boundaries(entry.published, originals)
    assert_split_returns_every_chapter_whole(entry.published, originals, tmp_path / "split")


def test_safe_without_silence_keeps_the_marks_on_the_boundaries(sources, reserve, tmp_path):
    files = [chapter_source(sources / "Book" / f"0{n} Part {n}.mp3", seed=10 + n) for n in (1, 2, 3)]
    made, entry = maker_book(sources, reserve, files, title="Safe Boundaries",
                             options=mp.MakerRunOptions(fast_first=False))
    outcome = build(made, entry)
    assert outcome.succeeded and outcome.path_used == "safe", outcome.failure_detail
    originals = [decode(p) for p in files]
    assert_marks_are_the_boundaries(entry.published, originals)
    assert_split_returns_every_chapter_whole(entry.published, originals, tmp_path / "split")


def test_inserted_silence_belongs_to_the_end_of_the_chapter_before_it(sources, reserve, tmp_path):
    files = [chapter_source(sources / "Book" / f"0{n} Part {n}.mp3", seed=20 + n) for n in (1, 2, 3)]
    made, entry = maker_book(sources, reserve, files, title="Gap Boundaries", silence="0.5")
    outcome = build(made, entry)
    assert outcome.succeeded and outcome.path_used == "safe", outcome.failure_detail
    originals = [decode(p) for p in files]
    assert_marks_are_the_boundaries(entry.published, originals, gap_s=0.5)
    assert_split_returns_every_chapter_whole(entry.published, originals, tmp_path / "split", gap_s=0.5)


def test_fast_starts_come_from_the_decoded_audio_not_a_header_estimate(sources, reserve):
    """VBR MP3s without a Xing header: ffprobe estimates their duration from the first frame's bitrate."""
    vbr = ("-c:a", "libmp3lame", "-q:a", "2", "-write_xing", "0")
    files = [chapter_source(sources / "Book" / f"0{n} Part {n}.mp3", seed=30 + n, encoder=vbr) for n in (1, 2, 3)]
    estimated = [proc.ffprobe_duration_ms(p) for p in files]
    decoded = [proc.decoded_duration_us(p) / 1000 for p in files]
    assert any(abs(e - d) > 20 for e, d in zip(estimated, decoded)), "the fixture really does mislead ffprobe"
    made, entry = maker_book(sources, reserve, files, title="Headerless VBR")
    outcome = build(made, entry)
    assert outcome.succeeded and outcome.path_used == "fast", outcome.failure_detail
    assert_marks_are_the_boundaries(entry.published, [decode(p) for p in files])


def test_the_maker_places_no_lead_in_and_keeps_the_encoders_edit_list():
    assert not hasattr(proc, "LEADIN_MS")
    text = proc.build_ffmetadata_from_starts(["A", "B"], [0, 5700], {"title": "T"}, 11810)
    assert [line for line in text.splitlines() if line.startswith("START=")] == ["START=0", "START=5700"]
    fast = proc.fast_concat_args(Path("l.txt"), Path("m.txt"), Path("o.m4b"), "128k")
    safe = proc.safe_concat_args(Path("l.txt"), Path("m.txt"), Path("o.m4b"), "128k")
    assert "-avoid_negative_ts" not in fast and "-avoid_negative_ts" not in safe
    for argv in (fast, safe):
        assert argv[argv.index("-filter:a") + 1].startswith("asetpts=N/SR/TB")
