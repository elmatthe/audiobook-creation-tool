"""The CLI-only Edge ``make_m4b`` writer against long chapters, with a real FFmpeg.

v0.6.6 Phase 10 disposition of the v0.6.5 Phase 9 review note. That note said
``tts.epub2tts_edge.epub2tts_edge.make_m4b`` writes chapters through the same mov
muxer whose automatic movie timescale truncated the M4B Maker/Metadata Editor's
chapter text track (Changelog 2026-09-20), and that it had no structural read-back
test.

The hazard does not reproduce here, and this pins why. The 2026-09-20 defect
needed a cover-art *video* stream in the mux. The lcm of 44.1 kHz audio and a
1/90000 video is 4,410,000, and at that timescale a chapter longer than ~487 s
does not fit. ``make_m4b`` muxes audio alone, so the chapter text track takes the
audio's own timescale (1/24000 for Edge's 24 kHz clips). That holds a chapter of
about 24.8 hours. ``add_cover`` then adds the cover through mutagen as a ``covr``
atom and never re-muxes the chapter track.

The path stays CLI-only (``--format m4b``). The shipped GUI always passes
``audio_format="mp3"``, pinned in ``test_tts_importing.py``.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from PIL import Image

from shared import ffmpeg_utils, metadata
from tts.epub2tts_edge import epub2tts_edge as edge

from test_m4b_metadata_workflow import _ff, require_ffmpeg

#: A short opening, a chapter past the ~487 s limit of the 2026-09-20 defect, a
#: short closing. Seconds.
CHAPTERS = (("Intro", 30), ("Long Chapter", 600), ("Outro", 20))

#: The sample rate of Edge's own clips.
EDGE_RATE = 24000


def _streams(path) -> list[dict]:
    out = subprocess.check_output([ffmpeg_utils.ffprobe_cmd(), "-v", "error",
                                   "-print_format", "json", "-show_streams", str(path)])
    return json.loads(out)["streams"]


@pytest.fixture(scope="module")
def edge_book(tmp_path_factory):
    """Built once through the real ``generate_metadata`` + ``make_m4b``: one FLAC
    part per chapter, the shape ``read_book`` hands them, in a private cwd,
    because both write relative scratch names."""
    require_ffmpeg()
    work = tmp_path_factory.mktemp("edge-m4b")
    parts = []
    for index, (_, seconds) in enumerate(CHAPTERS):
        part = work / f"part{index}.flac"
        _ff("-f", "lavfi", "-i", f"anullsrc=r={EDGE_RATE}:cl=mono", "-t", str(seconds),
            "-c:a", "flac", str(part))
        parts.append(part.name)
    (work / "book.txt").write_text("x", encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(work)
        edge.generate_metadata(parts, "Author", "Title", [t for t, _ in CHAPTERS])
        artifact = work / edge.make_m4b(parts, "book.txt", "Speaker")
    return work, artifact


def _assert_every_chapter_intact(structure):
    assert structure.titles == tuple(t for t, _ in CHAPTERS)
    assert structure.track_samples == len(CHAPTERS)
    at = 0.0
    for (start, end), (_, seconds) in zip(structure.boundaries, CHAPTERS):
        assert start == pytest.approx(at, abs=0.1)
        assert end == pytest.approx(at + seconds, abs=0.1)
        at += seconds


def test_a_chapter_past_the_2026_09_20_limit_survives_in_the_text_track(edge_book):
    _, artifact = edge_book
    _assert_every_chapter_intact(metadata.read_chapter_structure(artifact))


def test_the_chapter_track_takes_the_audio_timescale_because_no_video_is_muxed(edge_book):
    """The reason the hazard does not apply. If a later change muxes the cover
    as a video stream, this fails before any chapter can be lost."""
    _, artifact = edge_book
    streams = _streams(artifact)
    assert [s["codec_type"] for s in streams] == ["audio", "data"]
    audio, chapter_track = streams
    assert audio["time_base"] == f"1/{EDGE_RATE}"
    assert chapter_track["time_base"] == audio["time_base"]


def test_add_cover_keeps_the_chapter_track_intact(edge_book, tmp_path):
    work, artifact = edge_book
    covered = tmp_path / artifact.name
    covered.write_bytes(artifact.read_bytes())
    cover = tmp_path / "cover.png"
    Image.new("RGB", (64, 64), "red").save(cover)
    edge.add_cover(str(cover), str(covered))
    _assert_every_chapter_intact(metadata.read_chapter_structure(covered))
    assert "video" in [s["codec_type"] for s in _streams(covered)]


# --------------------------------------------------------------------------- #
# Three smaller CLI-path defects found while dispositioning the hazard above.
# --------------------------------------------------------------------------- #

#: FFMETADATA's reserved characters, a backslash, and text outside cp1252, which
#: the metadata file could not even be written in on a Windows locale.
AWKWARD_TITLES = ("Part 1; a=b #x", "Back\slash", "日本語の章")


def test_awkward_chapter_titles_and_tags_survive_the_real_mux(tmp_path, monkeypatch):
    """``generate_metadata`` wrote values unescaped, so ``;``/``=``/``#``/``\``
    garbled a title, and in the locale encoding (cp1252 on Windows), so a
    Japanese title raised ``UnicodeEncodeError`` and the build never ran."""
    require_ffmpeg()
    monkeypatch.chdir(tmp_path)
    parts = []
    for index in range(len(AWKWARD_TITLES)):
        part = f"part{index}.flac"
        _ff("-f", "lavfi", "-i", f"anullsrc=r={EDGE_RATE}:cl=mono", "-t", "2",
            "-c:a", "flac", part)
        parts.append(part)
    (tmp_path / "book.txt").write_text("x", encoding="utf-8")
    edge.generate_metadata(parts, "Ann; O=Neil", "Tales #1 — 物語", list(AWKWARD_TITLES))
    artifact = tmp_path / edge.make_m4b(parts, "book.txt", "Speaker")
    structure = metadata.read_chapter_structure(artifact)
    assert structure.titles == AWKWARD_TITLES
    assert structure.track_samples == len(AWKWARD_TITLES)
    tags = json.loads(subprocess.check_output(
        [ffmpeg_utils.ffprobe_cmd(), "-v", "error", "-print_format", "json",
         "-show_format", str(artifact)]))["format"]["tags"]
    assert tags["artist"] == "Ann; O=Neil"
    assert tags["album"] == "Tales #1 — 物語"


def test_a_failed_ffmpeg_step_raises_instead_of_being_ignored(tmp_path, monkeypatch):
    """``_run_ffmpeg`` ignored the exit status, so a failed step ran on into
    cleanup and returned the name of an output that was never written."""
    require_ffmpeg()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        edge._run_ffmpeg(["ffmpeg", "-v", "error", "-i", "missing.flac", "out.m4a"])
