"""The media oracle and fixtures, proved on real files from the pinned FFmpeg (plan sections 9 and 10; v0.7.2 Phase 3).

Every negative control starts from a real output that passes (the no-change control), damages one thing, and asserts the check that names that
damage. A mutated encoder that exits 0 and writes a plausible file is the case that matters: exit codes and durations cannot catch it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from gate_locator import GATE_DIR, REPO_ROOT

sys.path.insert(0, str(GATE_DIR))
from helpers import media_fixtures, media_oracle as oracle  # noqa: E402

sys.path.remove(str(GATE_DIR))


@pytest.fixture(scope="module")
def tools() -> oracle.Toolchain:
    return oracle.pinned_toolchain(REPO_ROOT)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return media_fixtures.load_manifest(GATE_DIR / "fixtures" / "manifest.json")


@pytest.fixture(scope="module")
def built(tools, manifest, tmp_path_factory) -> media_fixtures.FixtureSet:
    return media_fixtures.FixtureSet(tools, manifest, tmp_path_factory.mktemp("fixtures"))


def _ffmpeg(tools, *arguments) -> None:
    subprocess.run([tools.ffmpeg, "-hide_banner", "-v", "error", "-y", *arguments], check=True, capture_output=True, timeout=120)


def _output_seek(tools, source: Path, target: Path, start: float, length: float) -> Path:
    """The Converter's real command shape: seek after the input, so the decoder has decoded everything before the boundary."""
    _ffmpeg(tools, "-i", str(source), "-ss", f"{start:.6f}", "-t", f"{length:.6f}", "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(target))
    return target


def _input_seek(tools, source: Path, target: Path, start: float, length: float) -> Path:
    """The mutation plan section 3 forbids: faster, with plausible durations, and missing what the decoder needed to see first."""
    _ffmpeg(tools, "-ss", f"{start:.6f}", "-t", f"{length:.6f}", "-i", str(source), "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(target))
    return target


def test_every_fixture_in_the_manifest_builds_and_validates(tools, manifest, tmp_path):
    fixtures = media_fixtures.FixtureSet(tools, manifest, tmp_path / "f")
    for entry in manifest["fixtures"]:
        if entry["kind"] == "m4b-looped":
            continue  # built by the next test, because it takes real time
        generated = fixtures.get(entry["id"])
        assert generated.path.is_file() and all(item.get("ok") for item in generated.validation), entry["id"]


def test_the_long_book_builds_with_all_its_chapters(tools, manifest, tmp_path):
    fixtures = media_fixtures.FixtureSet(tools, manifest, tmp_path / "f")
    generated = fixtures.get("book-long-m4b")
    probed = oracle.probe(tools, generated.path)
    assert len(oracle.chapters_of(probed)) == 4 and float(probed["format"]["duration"]) > 3500


def test_a_fixture_is_the_same_bytes_every_time(tools, manifest, tmp_path):
    first, second = media_fixtures.FixtureSet(tools, manifest, tmp_path / "a"), media_fixtures.FixtureSet(tools, manifest, tmp_path / "b")
    for identifier in ("track-1", "book-m4b", "cover-png"):
        assert first.get(identifier).record()["sha256"] == second.get(identifier).record()["sha256"], identifier


def test_fixtures_do_not_depend_on_an_earlier_run(tools, manifest, tmp_path):
    """Plan section 9: regeneration must not depend on a previous outputs directory. A fixture that needs another builds that one too."""
    fixtures = media_fixtures.FixtureSet(tools, manifest, tmp_path / "fresh")
    assert fixtures.get("book-m4b").path.is_file() and fixtures.path("cover-square-jpeg").is_file()


def test_an_arbitrary_file_renamed_m4b_is_refused_before_any_application_sees_it(tools, manifest, tmp_path):
    fixtures = media_fixtures.FixtureSet(tools, manifest, tmp_path / "f")
    entry = {"id": "renamed", "kind": "m4b", "name": "x.m4b"}
    target = tmp_path / "x.m4b"
    target.write_bytes(b"\x00" * 4096)
    with pytest.raises(oracle.FixtureInvalid):
        fixtures._validated_audio(entry, target, codec="aac", container="mp4", duration=1.0)


def test_an_id3_header_with_no_audio_is_refused_as_a_real_mp3(tools, manifest, tmp_path):
    """The older orchestration fixture's shape. It stays useful for orchestration and can never be real-media evidence."""
    fixtures = media_fixtures.FixtureSet(tools, manifest, tmp_path / "f")
    target = tmp_path / "header-only.mp3"
    target.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00")
    with pytest.raises(oracle.FixtureInvalid):
        fixtures._validated_audio({"id": "fake", "kind": "mp3-track", "name": "x.mp3"}, target, codec="mp3", container="mp3", duration=1.0)


def test_the_manifest_names_the_fake_fixture_so_it_cannot_be_mistaken_for_a_real_one(manifest):
    named = [item["where"] for item in manifest["fake_orchestration_fixtures"]]
    assert "files/tests/test_tool_output_integration.py::mp3_fixture" in named
    module, _, name = named[0].partition("::")
    assert f"def {name}" in (REPO_ROOT / module).read_text(encoding="utf-8"), "the named fake fixture is gone: update the manifest"


def test_the_toolchain_is_refused_when_the_binary_is_not_the_proved_one(tmp_path):
    state = tmp_path / "files" / "runtime-data" / "ffmpeg-state.json"
    state.parent.mkdir(parents=True)
    fake = tmp_path / "ffmpeg.exe"
    fake.write_bytes(b"not the proved binary")
    state.write_text(json.dumps({"pair": {"ffmpeg": {"path": str(fake), "sha256": "00"}, "ffprobe": {"path": str(fake), "sha256": "00"}}}), encoding="utf-8")
    with pytest.raises(oracle.ToolchainUnavailable, match="not the recorded"):
        oracle.pinned_toolchain(tmp_path)


def test_no_pinned_pair_is_unavailable_rather_than_a_guess(tmp_path):
    with pytest.raises(oracle.ToolchainUnavailable, match="no proved FFmpeg pair"):
        oracle.pinned_toolchain(tmp_path)


# --------------------------------------------------------------------------- #
# The signal
# --------------------------------------------------------------------------- #
def test_the_real_route_passes_every_chapter_first_and_last_included(tools, built, tmp_path):
    book = built.get("book-m4b")
    sections = built.entries["book-m4b"]["sections"]
    reference = oracle.decode_pcm(tools, book.path)
    for index, _section in enumerate(sections):
        start, end = media_fixtures.section_interval(sections, index)
        output = _output_seek(tools, book.path, tmp_path / f"c{index}.mp3", start / oracle.ORACLE_RATE, (end - start) / oracle.ORACLE_RATE)
        metrics = oracle.compare_interval(reference[start:end], oracle.decode_pcm(tools, output))
        assert oracle.interval_problems(metrics) == [], (index, metrics)


def test_an_input_side_seek_fails_on_every_chapter_after_the_first_despite_plausible_durations(tools, built, tmp_path):
    """The historical priming defect, reproduced on the pinned build. Its durations are fine, and one chapter's waveform even matches: only its place gives it away."""
    book = built.get("book-m4b")
    sections = built.entries["book-m4b"]["sections"]
    reference = oracle.decode_pcm(tools, book.path)
    for index in range(1, len(sections)):
        start, end = media_fixtures.section_interval(sections, index)
        length = (end - start) / oracle.ORACLE_RATE
        output = _input_seek(tools, book.path, tmp_path / f"m{index}.mp3", start / oracle.ORACLE_RATE, length)
        assert abs(float(oracle.probe(tools, output)["format"]["duration"]) - length) < 0.1, "the mutation should still look right by duration"
        problems = oracle.interval_problems(oracle.compare_interval(reference[start:end], oracle.decode_pcm(tools, output)))
        assert problems, f"chapter {index + 1}: the input-side seek was not caught"


def test_wrong_chapter_content_with_the_right_duration_is_caught(tools, built, tmp_path):
    book = built.get("book-m4b")
    sections = built.entries["book-m4b"]["sections"]
    reference = oracle.decode_pcm(tools, book.path)
    start, end = media_fixtures.section_interval(sections, 1)
    length = (end - start) / oracle.ORACLE_RATE
    wrong = _output_seek(tools, book.path, tmp_path / "wrong.mp3", 0.0, length)  # chapter one's audio, under chapter two's length
    metrics = oracle.compare_interval(reference[start:end], oracle.decode_pcm(tools, wrong))
    assert any("correlation" in problem for problem in oracle.interval_problems(metrics)), metrics


def test_a_truncated_ending_is_caught(tools, built, tmp_path):
    book = built.get("book-m4b")
    sections = built.entries["book-m4b"]["sections"]
    reference = oracle.decode_pcm(tools, book.path)
    start, end = media_fixtures.section_interval(sections, 4)
    length = (end - start) / oracle.ORACLE_RATE
    short = _output_seek(tools, book.path, tmp_path / "short.mp3", start / oracle.ORACLE_RATE, length - 0.3)
    problems = oracle.interval_problems(oracle.compare_interval(reference[start:end], oracle.decode_pcm(tools, short)))
    assert any("length differs" in problem for problem in problems), problems


def test_an_attenuated_first_frame_is_caught_though_the_rest_matches():
    """What a whole-length correlation averages away, and what the edge energy is for."""
    t = np.arange(oracle.ORACLE_RATE * 2) / oracle.ORACLE_RATE
    reference = 0.4 * np.sin(2 * np.pi * 523 * t) + 0.2 * np.sin(2 * np.pi * 1700 * t * (1 + t / 4))
    candidate = reference.copy()
    edge = int(oracle.EDGE_SECONDS * oracle.ORACLE_RATE)
    candidate[:edge] *= 0.2
    metrics = oracle.compare_interval(reference, candidate)
    assert metrics["correlation"] > oracle.MIN_CORRELATION, "this control only means something if the whole-length figure misses it"
    assert any("first" in problem for problem in oracle.interval_problems(metrics)), metrics


def test_a_duplicated_section_is_caught():
    t = np.arange(oracle.ORACLE_RATE * 3) / oracle.ORACLE_RATE
    reference = 0.4 * np.sin(2 * np.pi * (300 + 200 * t) * t)
    candidate = np.concatenate((reference[: oracle.ORACLE_RATE], reference[: oracle.ORACLE_RATE], reference[oracle.ORACLE_RATE:]))
    assert oracle.interval_problems(oracle.compare_interval(reference, candidate))


def test_tone_order_is_read_from_the_audio_itself():
    rate = oracle.ORACLE_RATE
    t = np.arange(rate) / rate
    first, second = 0.4 * np.sin(2 * np.pi * 440 * t), 0.4 * np.sin(2 * np.pi * 880 * t)
    assert oracle.tone_sequence(np.concatenate((first, second)), rate, [440.0, 880.0], window=0.2) == [440.0, 880.0]
    assert oracle.tone_sequence(np.concatenate((second, first)), rate, [440.0, 880.0], window=0.2) == [880.0, 440.0]
    silent = oracle.tone_sequence(np.zeros(rate), rate, [440.0, 880.0], window=0.2)
    assert silent == [None], "silence is silence, not the first candidate"


# --------------------------------------------------------------------------- #
# Containers, chapters, tags and artwork
# --------------------------------------------------------------------------- #
def test_the_no_change_control_a_real_output_passes_every_inspection(tools, built):
    book = built.get("book-m4b")
    report = oracle.Report()
    probed = oracle.inspect_audio(tools, book.path, report, label="book", codec="aac", container="mp4", duration=15.691, tags=book.expected["tags"])
    oracle.inspect_chapters(probed, report, label="book", expected=book.expected["chapters"])
    assert report.failed == [], report.failed
    assert oracle.artwork_stream(probed) is not None


def test_a_simulated_encoder_success_with_a_truncated_payload_is_caught(tools, built, tmp_path):
    """Exit 0, the right name, the right extension and bytes that begin correctly."""
    source = built.path("track-1")
    good = tmp_path / "good.mp3"
    shutil.copyfile(source, good)
    report = oracle.Report()
    oracle.inspect_audio(tools, good, report, label="good", codec="mp3", duration=3.0, tags={"title": "Opening"})
    assert report.failed == [], "the no-change control must pass"
    truncated = tmp_path / "truncated.mp3"
    truncated.write_bytes(good.read_bytes()[: good.stat().st_size // 3])
    report = oracle.Report()
    oracle.inspect_audio(tools, truncated, report, label="bad", codec="mp3", duration=3.0)
    assert any("duration" in item["name"] for item in report.failed), report.checks


def test_bytes_that_are_not_media_are_caught_at_the_probe(tools, built):
    with pytest.raises(oracle.OracleFailure, match="refused"):
        oracle.inspect_audio(tools, built.path("track-garbage"), oracle.Report(), label="x", codec="mp3")


def test_a_corrupted_middle_is_caught_by_decoding_every_sample(tools, built, tmp_path):
    source = built.path("track-1")
    data = bytearray(source.read_bytes())
    for offset in range(len(data) // 2, len(data) // 2 + 4000):
        data[offset] = 0xFF ^ data[offset]
    damaged = tmp_path / "damaged.mp3"
    damaged.write_bytes(bytes(data))
    report = oracle.Report()
    oracle.inspect_audio(tools, damaged, report, label="damaged", codec="mp3")
    assert any("every sample decodes" in item["name"] for item in report.failed), report.checks


def test_a_missing_output_is_a_failure_rather_than_an_exception_nobody_reads(tools, tmp_path):
    report = oracle.Report()
    with pytest.raises(oracle.OracleFailure, match="does not exist"):
        oracle.inspect_audio(tools, tmp_path / "absent.mp3", report, label="x", codec="mp3")
    assert report.failed


def test_the_wrong_chapter_count_is_caught(tools, built):
    book = built.get("book-m4b")
    report = oracle.Report()
    oracle.inspect_chapters(oracle.probe(tools, book.path), report, label="book", expected=book.expected["chapters"][:-1])
    assert any("chapter count" in item["name"] for item in report.failed)


def test_a_wrong_chapter_title_and_a_moved_start_are_each_caught(tools, built):
    book = built.get("book-m4b")
    wanted = [dict(item) for item in book.expected["chapters"]]
    wanted[1]["title"] = "Something Else"
    wanted[2]["start"] += 0.5
    report = oracle.Report()
    oracle.inspect_chapters(oracle.probe(tools, book.path), report, label="book", expected=wanted)
    names = {item["name"] for item in report.failed}
    assert "book: chapter 2 title" in names and "book: chapter 3 start" in names


def test_an_omitted_artwork_map_is_caught(tools, built, tmp_path):
    book = built.get("book-m4b")
    stripped = tmp_path / "no-art.m4b"
    _ffmpeg(tools, "-i", str(book.path), "-map", "0:a", "-c", "copy", "-f", "ipod", str(stripped))
    assert oracle.artwork_stream(oracle.probe(tools, book.path)) is not None
    assert oracle.artwork_stream(oracle.probe(tools, stripped)) is None
    with pytest.raises(oracle.OracleFailure, match="no artwork"):
        oracle.extract_artwork(tools, stripped, tmp_path / "x.jpg")


def test_a_wrong_or_missing_tag_is_caught(tools, built):
    report = oracle.Report()
    oracle.inspect_audio(tools, built.path("track-1"), report, label="t", codec="mp3", tags={"album": "Not This", "composer": "Nobody"}, absent_tags=("artist",))
    names = {item["name"] for item in report.failed}
    assert names == {"t: tag album", "t: tag composer", "t: no tag artist"}


def test_a_report_keeps_its_failures_and_require_stops_at_the_first_that_cannot_be_built_on():
    report = oracle.Report()
    assert report.check("fine", True) is True
    assert report.check("wrong", False, "why") is False
    with pytest.raises(oracle.OracleFailure, match="fatal"):
        report.require("fatal", False, "why")
    assert [item["name"] for item in report.failed] == ["wrong", "fatal"]
