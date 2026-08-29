"""The ffmpeg concat-list contract: any legal path must survive serialization.

Plan 2 lets the user choose the output base, and the drop requires paths with
spaces, Unicode and apostrophes to work. The concat demuxer has its own quoting
rules that are **not** shell rules, and getting them wrong is what broke
``Combine MP3s -> One MP3`` for any folder containing an apostrophe.

FFmpeg's documented syntax (ffmpeg-all, "Concat demuxer" and "Quoting and
escaping"): characters inside single quotes are literal, so a quote cannot be
backslash-escaped inside them. The documented form closes the quote, emits an
escaped quote, and reopens::

    file '/mnt/share/file 3'\\''.wav'

These tests pin that representation and then prove it end to end against the
real ffmpeg binary, so the rule is never re-derived from a single lucky fixture.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from shared import ffmpeg_utils
from mp3_tools import mp3_tool

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# v0.6.2 Plan 5 Phase 15: these were ``shutil.which("ffmpeg")``, which is the
# one thing the application itself is no longer allowed to do. On the machine
# that blocked the Phase 15 matrix that resolved an installation Windows refuses
# to execute, and these tests only passed because a developer had prepended a
# working directory to PATH for the run. They now use the same proven pair the
# app does, so this module tests the shipped resolution instead of PATH order.
FFMPEG = ffmpeg_utils.ffmpeg_cmd()
FFPROBE = ffmpeg_utils.ffprobe_cmd()
needs_ffmpeg = pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(),
                                  reason="ffmpeg/ffprobe not available")

# Names that have to survive: plain, spaces, one quote, several quotes, Unicode,
# and everything at once. Windows forbids most other punctuation in a filename.
TRICKY = [
    "plain",
    "with space",
    "o'clock",
    "o'clock's 'quoted' name",
    "Résumé Ñ 作品",
    "Ré'sumé Ñ's 作品",
]


# --------------------------------------------------------------------------- #
# The serialization itself
# --------------------------------------------------------------------------- #


def test_a_plain_path_is_simply_quoted(tmp_path):
    line = mp3_tool.ffmpeg_escape_listfile_path(tmp_path / "tone.mp3")
    assert line == f"file '{tmp_path / 'tone.mp3'}'"


def test_a_space_needs_no_escape_inside_the_quotes(tmp_path):
    path = tmp_path / "two tones.mp3"
    assert mp3_tool.ffmpeg_escape_listfile_path(path) == f"file '{path}'"


def test_backslashes_are_left_alone(tmp_path):
    """Inside single quotes every character is literal — doubling corrupts."""
    line = mp3_tool.ffmpeg_escape_listfile_path(tmp_path / "tone.mp3")
    assert "\\\\" not in line
    assert str(tmp_path / "tone.mp3") in line


def test_one_apostrophe_uses_the_documented_close_escape_reopen_form():
    """The exact example from ffmpeg-all: ``file '/mnt/share/file 3'\\''.wav'``."""
    path = Path("/mnt/share/file 3'.wav")
    stem = str(path).replace("'", "")          # native separators, quote removed
    head, tail = stem.split("file 3")
    line = mp3_tool.ffmpeg_escape_listfile_path(path)
    assert line == f"file '{head}file 3'\\''{tail}'"
    assert "'\\''" in line


def test_every_apostrophe_is_escaped():
    path = Path("/a/o'clock's 'x'.mp3")
    line = mp3_tool.ffmpeg_escape_listfile_path(path)
    assert line.count("'\\''") == str(path).count("'") == 4
    assert line.startswith("file '") and line.endswith("'")


def test_unicode_survives_untouched():
    path = Path("/a/Résumé Ñ 作品.mp3")
    assert mp3_tool.ffmpeg_escape_listfile_path(path) == f"file '{path}'"


def test_the_quoting_is_balanced_for_every_tricky_name(tmp_path):
    """Outside the escapes, quotes must pair up — an odd count truncates."""
    for name in TRICKY:
        line = mp3_tool.ffmpeg_escape_listfile_path(tmp_path / f"{name}.mp3")
        assert line.replace("'\\''", "").count("'") == 2, name


def test_the_listfile_preserves_order_and_one_entry_per_line(tmp_path):
    paths = [tmp_path / f"{index:02d} o'clock.mp3" for index in range(5)]
    listfile = tmp_path / "inputs.txt"
    mp3_tool.write_concat_listfile(paths, listfile)
    lines = listfile.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(paths)
    for line, path in zip(lines, paths):
        assert line == mp3_tool.ffmpeg_escape_listfile_path(path)


def test_the_listfile_is_written_as_utf8(tmp_path):
    """ffmpeg reads the list as UTF-8; an ANSI write mojibakes non-ASCII."""
    path = tmp_path / "Résumé.mp3"
    listfile = tmp_path / "inputs.txt"
    mp3_tool.write_concat_listfile([path], listfile)
    assert "Résumé" in listfile.read_bytes().decode("utf-8")


# --------------------------------------------------------------------------- #
# Against the real binary — the rule is documented, not guessed
# --------------------------------------------------------------------------- #


def tone(path: Path, seconds: int = 1, freq: int = 440) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"sine=frequency={freq}:duration={seconds}",
                    "-c:a", "libmp3lame", "-b:a", "64k", str(path)],
                   check=True, capture_output=True)
    return path


def duration(path: Path) -> float:
    done = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                           "-of", "default=nw=1:nk=1", str(path)],
                          capture_output=True, text=True, check=True)
    return float(done.stdout.strip())


@needs_ffmpeg
@pytest.mark.parametrize("name", TRICKY)
def test_ffmpeg_really_concatenates_through_a_directory_with_that_name(tmp_path, name):
    work = tmp_path / name
    sources = [tone(work / f"{index} {name}.mp3", freq=330 + index * 110)
               for index in range(1, 3)]
    listfile = work / "inputs.txt"
    mp3_tool.write_concat_listfile(sources, listfile)
    out = work / f"combined {name}.mp3"
    done = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                           "-f", "concat", "-safe", "0", "-i", str(listfile),
                           "-c:a", "libmp3lame", "-q:a", "2", str(out)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert out.is_file() and out.stat().st_size > 0
    assert duration(out) == pytest.approx(2.0, abs=0.35)


@needs_ffmpeg
def test_a_filename_with_an_apostrophe_concatenates_even_in_a_plain_directory(tmp_path):
    """The quote may be in the file part, not only the parent."""
    sources = [tone(tmp_path / "one o'clock.mp3"), tone(tmp_path / "two o'clock.mp3", freq=550)]
    listfile = tmp_path / "inputs.txt"
    mp3_tool.write_concat_listfile(sources, listfile)
    out = tmp_path / "combined.mp3"
    done = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                           "-f", "concat", "-safe", "0", "-i", str(listfile),
                           "-c:a", "libmp3lame", "-q:a", "2", str(out)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert duration(out) == pytest.approx(2.0, abs=0.35)


@needs_ffmpeg
def test_the_sources_are_byte_identical_afterwards(tmp_path):
    import hashlib

    work = tmp_path / "Ré'sumé Ñ"
    sources = [tone(work / f"{index} o'clock.mp3", freq=300 + index * 100)
               for index in range(1, 3)]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources]
    listfile = work / "inputs.txt"
    mp3_tool.write_concat_listfile(sources, listfile)
    out = work / "combined.mp3"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", str(listfile),
                    "-c:a", "libmp3lame", "-q:a", "2", str(out)],
                   check=True, capture_output=True)
    after = [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources]
    assert before == after


@needs_ffmpeg
def test_input_order_is_preserved_audibly(tmp_path):
    """A 1 s + 3 s pair must total 4 s in the order given, not the reverse."""
    work = tmp_path / "order's test"
    first = tone(work / "first.mp3", seconds=1, freq=330)
    second = tone(work / "second.mp3", seconds=3, freq=880)
    listfile = work / "inputs.txt"
    mp3_tool.write_concat_listfile([first, second], listfile)
    lines = listfile.read_text(encoding="utf-8").splitlines()
    assert "first.mp3" in lines[0] and "second.mp3" in lines[1]
    out = work / "combined.mp3"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", str(listfile),
                    "-c:a", "libmp3lame", "-q:a", "2", str(out)],
                   check=True, capture_output=True)
    assert duration(out) == pytest.approx(4.0, abs=0.4)


# --------------------------------------------------------------------------- #
# Command safety
# --------------------------------------------------------------------------- #


def test_no_ffmpeg_call_is_made_through_a_shell():
    """Argument-vector execution only — a path never reaches a shell."""
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "mp3_tool.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    assert isinstance(keyword.value, ast.Constant)
                    assert keyword.value.value is False, "shell=True is never allowed"


def test_run_ff_is_given_a_list_not_a_string():
    tree = ast.parse((REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "mp3_tool.py")
                     .read_text(encoding="utf-8"))
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "run_ff")
    calls = [n for n in ast.walk(function)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "run"]
    assert calls, "run_ff must call subprocess.run"
    for call in calls:
        assert isinstance(call.args[0], ast.Name), "the command must be a list variable"


def test_shlex_quote_is_only_used_for_the_human_readable_log():
    """Shell quoting must never be mistaken for concat-list escaping."""
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "mp3_tool.py"
              ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    owners = set()
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "quote"):
                owners.add(function.name)
    assert owners <= {"save_error_log"}, owners


def test_the_escaper_does_not_use_shell_quoting():
    tree = ast.parse((REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "mp3_tool.py")
                     .read_text(encoding="utf-8"))
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "ffmpeg_escape_listfile_path")
    # The docstring legitimately discusses quoting; only the code may not use it.
    statements = function.body[1:] if ast.get_docstring(function) else function.body
    code = "".join(ast.dump(node) for node in statements)
    assert "shlex" not in code
    assert "quote" not in code


# --------------------------------------------------------------------------- #
# Where the output goes, and what is left behind
# --------------------------------------------------------------------------- #


def test_the_combine_output_still_goes_through_the_shared_run_directory():
    """The reservation rules are untouched by the escaping fix."""
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "mp3_tool.py"
              ).read_text(encoding="utf-8")
    assert "reserve_run_directory" in source
    assert "next_available_folder" not in source


def test_the_listfile_lives_inside_the_operation_directory(tmp_path):
    """Concat lists are operation-owned, never left beside a source."""
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "mp3_tool.py"
              ).read_text(encoding="utf-8")
    assert 'build_dir / "inputs_fast.txt"' in source
    assert 'out_dir / "build" / "inputs_safe.txt"' in source


def test_a_failure_still_records_the_ffmpeg_error_text(tmp_path):
    """The log keeps the real stderr, so a failure is never silent."""
    mp3_tool.save_error_log(tmp_path, "FAST PATH", ["ffmpeg", "-i", "x"], "boom: no such file")
    text = (tmp_path / "ffmpeg_log.txt").read_text(encoding="utf-8")
    assert "FAST PATH" in text and "boom: no such file" in text and "CMD:" in text
