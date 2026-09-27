"""The chapter-title remux against long chapters beside a cover — the
2026-09-20 defect and its guards, against a real FFmpeg.

What happened. Six real audiobooks (44.1 kHz AAC, an embedded cover, chapters
of 12–105 minutes) failed every Save Tags / Clear All Tags with their chapter
titles displaced: ``('Intro', 'Outro', 'Chapter 2', …, 'Outro')`` where
``('Intro', 'Chapter 1', 'Chapter 2', …, 'Outro')`` was planned. FFmpeg 9's mov
muxer defaults ``-movie_timescale`` to *auto* — the lcm of every mapped stream's
timescale, 4,410,000 for 44.1 kHz audio beside the 1/90000 cover-art video — and
the chapter text track inherits it, so every chapter longer than
INT_MAX / 4,410,000 ≈ 487 s was refused ("Application provided duration … in
stream 2 is invalid"), dropped, and ffmpeg still exited 0. The Nero ``chpl``
atom stayed complete; ffprobe merged the two by chapter id, so the k short
survivors overwrote chapters 0..k-1.

What is pinned here, all against generated media the shape of the real files
(a cover-art video stream, one ten-minute chapter between two short ones):

- ``apply_chapter_titles`` keeps every chapter, boundary and text-track sample,
  changes only the titles it was given, and leaves the audio stream byte-equal;
- the shape whose *merged* titles read back correctly while the text track had
  lost its long chapter (short chapter leading) now keeps a complete track;
- the pathological timescale, forced explicitly so the proof does not depend on
  the host's FFmpeg default, reproduces the displacement — the negative control
  that shows the fixture would have caught the defect;
- the remux argv pins the movie timescale and stays ``-c copy``;
- an ffmpeg error reported with exit status 0 refuses the remux and leaves the
  copy untouched;
- ``read_chapter_structure`` reports the boundaries, titles and sample count the
  Editor's validation now compares.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import shutil
import subprocess
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from shared import ffmpeg_utils, metadata
from shared import subprocess_utils

from test_m4b_metadata_workflow import _ff, require_ffmpeg

REPO_ROOT = Path(__file__).resolve().parents[2]
METADATA_MODULE = REPO_ROOT / "scripts" / "Universal" / "shared" / "metadata.py"

#: The reproduced shape: a short opening, a chapter well past the ~487 s limit,
#: a short closing. Seconds.
LONG_CHAPTERS = (("Intro", 30), ("Chapter 1", 600), ("Outro", 30))

#: The shape a titles-only validation could not see: the short chapter *leads*,
#: so the one surviving text-track sample carried the right title at id 0.
LEADING_SHORT_CHAPTERS = (("Intro", 30), ("Chapter 1", 630))

#: The timescale FFmpeg 9 picks on its own for these streams (lcm of 44100 and
#: 90000). Forced explicitly by the negative control so the proof holds on any
#: FFmpeg whose default differs.
PATHOLOGICAL_TIMESCALE = "4410000"


def build_chaptered_m4b(work: Path, target: Path, chapters=LONG_CHAPTERS) -> Path:
    """A silent mono AAC M4B with an attached MJPEG cover and *chapters*, written
    the way every FFmpeg before 9 wrote it (movie timescale 1000) — the
    structure the real sources carry."""
    require_ffmpeg()
    total = sum(seconds for _, seconds in chapters)
    lines = [";FFMETADATA1", "title=Long Book"]
    at = 0
    for title, seconds in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={at * 1000}",
                  f"END={(at + seconds) * 1000}", f"title={title}"]
        at += seconds
    meta = work / f"{target.stem}.ffmeta"
    meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _ff("-t", str(total), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", "1", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=1",
        "-i", str(meta),
        "-map", "0:a", "-map", "1:v", "-map_metadata", "2", "-map_chapters", "2",
        "-c:a", "aac", "-b:a", "16k", "-c:v", "mjpeg", "-disposition:v", "attached_pic",
        "-movie_timescale", "1000", str(target))
    return target


def audio_md5(path: Path) -> str:
    out = subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-i", str(path),
                          "-map", "0:a", "-c", "copy", "-f", "md5", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert out.returncode == 0, out.stdout[-400:]
    return out.stdout.decode("ascii", "replace").strip()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def legacy_remux(path: Path) -> None:
    """The remux exactly as shipped before 2026-09-20 *plus* the timescale FFmpeg
    9 chose by itself, forced — the defect, reproduced on demand."""
    work = path.parent / f"{path.stem}.legacy"
    work.mkdir()
    meta = work / "in.ffmeta"
    _ff("-i", str(path), "-f", "ffmetadata", str(meta))
    tmp_out = path.with_name(path.stem + ".legacy.tmp" + path.suffix)
    _ff("-i", str(path), "-i", str(meta),
        "-map", "0:a", "-map", "0:v?", "-map_metadata", "0", "-map_chapters", "1",
        "-c", "copy", "-movie_timescale", PATHOLOGICAL_TIMESCALE, str(tmp_out))
    tmp_out.replace(path)
    shutil.rmtree(work)


@pytest.fixture(scope="module")
def long_book(tmp_path_factory) -> Path:
    work = tmp_path_factory.mktemp("long-chapters")
    return build_chaptered_m4b(work, work / "long.m4b")


@pytest.fixture(scope="module")
def leading_short_book(tmp_path_factory) -> Path:
    work = tmp_path_factory.mktemp("leading-short")
    return build_chaptered_m4b(work, work / "leading.m4b", LEADING_SHORT_CHAPTERS)


def structure_of(chapters) -> tuple[tuple[float, float], ...]:
    out, at = [], 0.0
    for _, seconds in chapters:
        out.append((at, at + seconds))
        at += seconds
    return tuple(out)


def assert_boundaries(found, expected, tolerance=0.01):
    assert len(found) == len(expected)
    for (a0, a1), (b0, b1) in zip(found, expected):
        assert abs(a0 - b0) <= tolerance and abs(a1 - b1) <= tolerance, (found, expected)


# --------------------------------------------------------------------------- #
# The structural reader
# --------------------------------------------------------------------------- #


def test_the_fixture_is_the_real_shape_and_the_reader_sees_all_of_it(long_book):
    seen = metadata.read_chapter_structure(long_book)
    assert seen.count == 3
    assert seen.titles == ("Intro", "Chapter 1", "Outro")
    assert_boundaries(seen.boundaries, structure_of(LONG_CHAPTERS))
    assert seen.track_samples == 3, "one QuickTime chapter-track sample per chapter"
    streams = subprocess.run([ffmpeg_utils.ffprobe_cmd(), "-v", "error", "-show_entries",
                              "stream=codec_type,time_base", "-of", "csv=p=0", str(long_book)],
                             stdout=subprocess.PIPE, check=True).stdout.decode()
    assert "video,1/90000" in streams, "the cover rides as a 1/90000 video stream"
    assert "audio,1/44100" in streams


def test_the_reader_reports_no_track_for_a_file_without_a_chapter_track(tmp_path):
    require_ffmpeg()
    plain = tmp_path / "plain.m4a"
    _ff("-t", "1", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-c:a", "aac", str(plain))
    seen = metadata.read_chapter_structure(plain)
    assert seen.count == 0 and seen.titles == () and seen.track_samples is None


def test_the_reader_is_a_frozen_value():
    seen = metadata.ChapterStructure(boundaries=((0.0, 1.0),), titles=("A",), track_samples=1)
    with pytest.raises(Exception):
        seen.titles = ("B",)  # type: ignore[misc]
    assert seen.count == 1


# --------------------------------------------------------------------------- #
# The remux keeps every chapter
# --------------------------------------------------------------------------- #


def test_retitling_long_chapters_beside_a_cover_keeps_every_chapter(long_book, tmp_path):
    copy = tmp_path / "book.m4b"
    shutil.copy2(long_book, copy)
    before_audio = audio_md5(copy)
    metadata.apply_chapter_titles(copy, ["Opening", "", "Closing"])
    assert metadata.read_chapter_titles(copy) == ["Opening", "Chapter 1", "Closing"]
    seen = metadata.read_chapter_structure(copy)
    assert seen.count == 3 and seen.track_samples == 3
    assert_boundaries(seen.boundaries, structure_of(LONG_CHAPTERS))
    assert audio_md5(copy) == before_audio, "-c copy: the audio stream is byte-equal"
    from mutagen.mp4 import MP4
    assert MP4(str(copy)).tags.get("covr"), "the cover survives the remux"
    assert not list(tmp_path.glob("*.retitle.tmp*"))


def test_retitling_a_leading_short_chapter_keeps_the_text_track_complete(leading_short_book,
                                                                         tmp_path):
    """The false-pass shape: the merged titles read back right even when the
    long chapter had been dropped — the sample count is what proves it now."""
    copy = tmp_path / "leading.m4b"
    shutil.copy2(leading_short_book, copy)
    metadata.apply_chapter_titles(copy, ["Opening", ""])
    seen = metadata.read_chapter_structure(copy)
    assert seen.titles == ("Opening", "Chapter 1")
    assert seen.track_samples == 2
    assert_boundaries(seen.boundaries, structure_of(LEADING_SHORT_CHAPTERS))


def test_the_pathological_timescale_reproduces_the_displacement(long_book, leading_short_book,
                                                                tmp_path):
    """Negative control: the same remux at the timescale FFmpeg 9 picked on its
    own loses the long chapter and re-keys the survivors — so the fixtures
    above would have failed before the pin, and would fail if it were removed."""
    displaced = tmp_path / "displaced.m4b"
    shutil.copy2(long_book, displaced)
    legacy_remux(displaced)
    seen = metadata.read_chapter_structure(displaced)
    assert seen.track_samples == 2, "the 600 s chapter is gone from the text track"
    assert seen.titles == ("Intro", "Outro", "Outro"), "the survivors landed on ids 0 and 1"

    hidden = tmp_path / "hidden.m4b"
    shutil.copy2(leading_short_book, hidden)
    legacy_remux(hidden)
    seen = metadata.read_chapter_structure(hidden)
    assert seen.titles == ("Intro", "Chapter 1"), "titles alone look untouched…"
    assert seen.track_samples == 1, "…while the text track holds one sample"


# --------------------------------------------------------------------------- #
# The argv contract and the exit-status-zero guard
# --------------------------------------------------------------------------- #


def _remux_argv_literal() -> list[str]:
    tree = ast.parse(METADATA_MODULE.read_text(encoding="utf-8"))
    fn = next(node for node in ast.walk(tree)
              if isinstance(node, ast.FunctionDef) and node.name == "apply_chapter_titles")
    for node in ast.walk(fn):
        if isinstance(node, ast.List):
            tokens = [elt.value if isinstance(elt, ast.Constant) else ast.unparse(elt)
                      for elt in node.elts]
            if "-map_chapters" in tokens:
                return tokens
    raise AssertionError("the chapter remux argv literal was not found")


def test_the_remux_pins_the_movie_timescale_and_stays_stream_copy():
    tokens = _remux_argv_literal()
    assert metadata.CHAPTER_REMUX_MOVIE_TIMESCALE == "1000"
    at = tokens.index("-movie_timescale")
    assert tokens[at + 1] == "CHAPTER_REMUX_MOVIE_TIMESCALE"
    assert tokens[tokens.index("-c") + 1] == "copy"
    assert tokens[tokens.index("-map_chapters") + 1] == "1"
    assert "-loglevel" in tokens and tokens[tokens.index("-loglevel") + 1] == "error"
    source = inspect.getsource(metadata.apply_chapter_titles)
    assert "_run_chapter_remux_step(" in source
    assert "sp.run(" not in source, "every ffmpeg step goes through the guarded runner"


def test_an_ffmpeg_error_with_exit_status_zero_refuses_the_remux(long_book, tmp_path,
                                                                monkeypatch):
    copy = tmp_path / "guarded.m4b"
    shutil.copy2(long_book, copy)
    before = sha(copy)
    real_run = subprocess_utils.run
    calls: list[list[str]] = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        if "-map_chapters" not in cmd:
            return real_run(cmd, **kwargs)
        # ffmpeg's own words on 2026-09-20 — with exit status 0 and a half-written output.
        Path(cmd[-1]).write_bytes(b"partial")
        return CompletedProcess(cmd, 0, stdout=b"", stderr=(
            b"[ipod @ 0x1] Application provided duration: 2646000000 in stream 2 is invalid\n"))

    monkeypatch.setattr(subprocess_utils, "run", run)
    with pytest.raises(metadata.ChapterRemuxError) as caught:
        metadata.apply_chapter_titles(copy, ["Opening", "", ""])
    assert "Application provided duration" in str(caught.value)
    assert sha(copy) == before, "the copy is untouched"
    assert not list(tmp_path.glob("*.retitle.tmp*")), "no half-written sibling survives"
    assert any("-map_chapters" in c for c in calls)
    assert issubclass(metadata.ChapterRemuxError, RuntimeError)


def test_a_non_zero_exit_still_raises_the_called_process_error(long_book, tmp_path,
                                                              monkeypatch):
    copy = tmp_path / "exit.m4b"
    shutil.copy2(long_book, copy)
    real_run = subprocess_utils.run

    def run(cmd, **kwargs):
        if "-map_chapters" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr=b"boom")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess_utils, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        metadata.apply_chapter_titles(copy, ["Opening", "", ""])
    assert sha(copy) == sha(long_book)
