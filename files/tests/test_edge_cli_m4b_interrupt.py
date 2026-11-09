"""The Edge command line's ``--format m4b``: Ctrl+C and a deadline for its two FFmpeg steps (v0.7.2 Phase 6E, ACT72-010).

``make_m4b`` (reached only from ``epub2tts_edge.main``; the app always writes MP3) runs two FFmpeg steps: the concat of the
chapter parts into FLAC-in-MP4, then the AAC encode with the chapters. Each was a blocking ``subprocess_utils.run``. FFmpeg
has a console of its own (``CREATE_NO_WINDOW``), so Ctrl+C reached only Python, whose main thread sat in an uninterruptible
wait: measured at 5a87ec3 with a step slowed to the playing rate, the command line exited 28.6 s after the press, when FFmpeg
had finished by itself, with a traceback and STATUS_CONTROL_C_EXIT; a suspended FFmpeg hung it for good. Now each step runs
through ``subprocess_utils.run_supervised`` with a deadline (the book's playing time plus ten minutes), and inside
``_ctrl_c_stops_the_step`` a press is recorded, the supervisor stops that very child, no further step starts, and the
command line exits 130; a step past its deadline is stopped the same way and the command line exits 124.

Four layers, each with real processes:

* the supervisor's opt-in deadline, with controlled children (the copy of PING.EXE named ``ffmpeg.exe`` and the stubborn
  stand-in of ``test_ffmpeg_cancel``);
* the deadline policy, read from real FLAC headers;
* ``make_m4b`` itself with real FFmpeg and tone parts (never silence): every chapter intact, the production argument
  vectors, a step slowed to the playing rate not cut short, a stand-in that never ends stopped, a real failure raised;
* the command line itself (``edge_cli_m4b_child``): the real ``main()`` in a console of its own, inside a job, and a real
  CTRL_C_EVENT generated only in that console by a helper with no console of its own.

Every interruption checks that nothing is published, that what the output folder already held (another book, and a file
under the run's own name with ``--overwrite``) and the sources are byte-identical, that the run's work folder is gone, that
no process of the run survives (the job's own list) and that an FFmpeg-named sentinel of the same process lives on.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shared import ffmpeg_utils, metadata
from shared import subprocess_utils as sp
from shared.cancellation import ConversionCancelled
from tts.epub2tts_edge import epub2tts_edge as edge

import edge_cli_m4b_child as cli
import source_probe
from test_ffmpeg_cancel import (  # noqa: F401  (fixtures are collected by name)
    PROMPT_SECONDS,
    Spawned,
    StandIn,
    _media_children,
    _ping,
    _python,
    _Stubborn,
    named_ffmpeg,
    sentinel,
)
from test_m4b_metadata_workflow import _ff, require_ffmpeg

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows console and process identity")

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SPEAKER = "en-US-SteffanNeural"
#: Three chapters of tone (seconds); one title needs FFMETADATA escaping, one is outside cp1252.
CHAPTERS = (("Opening", 10), ("Middle; a=b", 10), ("終わり", 10))
EDGE_RATE = 24000
#: From the press to the command line having exited. Measured at about 0.17 s; before, the rest of the step (28.6 s).
CLI_PROMPT_SECONDS = 5.0
PUBLISHED = f"My Book ({SPEAKER}).m4b"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def _tone(path: Path, seconds: float, frequency: int) -> Path:
    _ff("-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate={EDGE_RATE}:duration={seconds}",
        "-ac", "1", "-c:a", "flac", str(path))
    return path


@pytest.fixture(scope="module")
def book(tmp_path_factory):
    """The chapters as Edge's FLAC parts, a source, a cover and the stand-in image, made once."""
    require_ffmpeg()
    root = tmp_path_factory.mktemp("edge-cli-book")
    parts = [[title, str(_tone(root / f"chapter{index}.flac", seconds, 300 + 100 * index))]
             for index, (title, seconds) in enumerate(CHAPTERS)]
    source = root / "My Book.txt"
    source.write_text("Title: T\nAuthor: A\n# Opening\n\nx\n", encoding="utf-8")
    from PIL import Image

    cover = root / "cover.png"
    Image.new("RGB", (32, 32), "navy").save(cover)
    image = root / "stand-in" / "ffmpeg.exe"
    image.parent.mkdir()
    shutil.copyfile(Path(r"C:\Windows\System32\PING.EXE"), image)
    return {"parts": parts, "source": source, "cover": cover, "image": image, "root": root}


def _sources(book) -> dict:
    return {p: sha(Path(p)) for p in [str(book["source"]), str(book["cover"])] + [part for _, part in book["parts"]]}


# --------------------------------------------------------------------------- #
# 1. The supervisor's deadline (opt-in; no caller had one before)
# --------------------------------------------------------------------------- #


def test_a_deadline_stops_a_child_that_never_ends_through_its_own_handle(monkeypatch, named_ffmpeg, sentinel):
    spawned = Spawned(monkeypatch)
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        sp.run_supervised(_ping(named_ffmpeg, 120), deadline_seconds=0.5)
    elapsed = time.monotonic() - started
    (argv, child, _kwargs), = spawned.children
    assert child.poll() is not None, "the child was stopped and collected"
    assert 0.5 <= elapsed < 0.5 + PROMPT_SECONDS, f"stopped {elapsed:.2f} s after it started, deadline 0.5 s"
    expired = raised.value
    assert not isinstance(expired, (ConversionCancelled, subprocess.CalledProcessError)), "neither a Cancel nor a failure"
    assert (expired.cmd, expired.timeout) == (argv, 0.5)
    assert isinstance(expired.output, bytes) and isinstance(expired.stderr, bytes), "the tails, as from a finished step"
    assert _media_children() == [sentinel.pid], "only that child: an FFmpeg this run did not start is untouched"


@pytest.mark.parametrize("immortal", [False, True], ids=["killed", "never-exits"])
def test_a_child_that_ignores_terminate_is_killed_at_its_deadline(monkeypatch, immortal):
    stubborn = _Stubborn(immortal)
    monkeypatch.setattr(sp, "popen", lambda cmd, **kwargs: stubborn)
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        sp.run_supervised(["ffmpeg"], grace_seconds=0.05, deadline_seconds=0.1)
    assert time.monotonic() - started < 1.0
    assert stubborn.steps == ["terminate", "kill"], "terminate first, then kill, never more"
    notes = getattr(raised.value, "__notes__", [])
    assert bool(notes) is immortal, "a child that did not exit is reported, not waited on for ever"


def test_a_cancel_seen_at_the_same_look_as_the_deadline_is_a_cancel(monkeypatch, named_ffmpeg):
    spawned = Spawned(monkeypatch)
    looks = {"n": 0}

    def cancel_check():  # not yet when the step starts, then at the first look, when the deadline has passed too
        looks["n"] += 1
        return looks["n"] > 1

    with sp.cancellable(cancel_check), pytest.raises(ConversionCancelled):
        sp.run_supervised(_ping(named_ffmpeg, 120), deadline_seconds=0.0)
    assert spawned.children[0][1].poll() is not None


def test_within_its_deadline_a_child_runs_to_its_end_and_no_deadline_is_the_default():
    done = sp.run_supervised(_python("import sys,time;time.sleep(0.3);sys.stdout.write('whole');sys.exit(3)"),
                             deadline_seconds=30)
    assert (done.returncode, done.stdout) == (3, b"whole"), "a failure stays the caller's to judge, as before"
    assert inspect.signature(sp.run_supervised).parameters["deadline_seconds"].default is None


def test_no_caller_but_the_command_lines_m4b_step_opts_into_a_deadline():
    """Keeps every earlier caller (MP3 Tool, M4B Maker, Metadata Editor) exactly as Phase 6C/6D left it."""
    with_deadline = []
    for path in source_probe.application_python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "run_supervised"
                    and any(keyword.arg == "deadline_seconds" for keyword in node.keywords)):
                with_deadline.append(path.name)
    assert with_deadline == ["epub2tts_edge.py"], with_deadline


# --------------------------------------------------------------------------- #
# 2. The policy: the book's playing time, from its parts' headers, plus ten minutes
# --------------------------------------------------------------------------- #


def _claim_length(flac: Path, samples: int) -> None:
    """Rewrite the total-samples field of a FLAC's STREAMINFO (the low 36 bits of bytes 18-25), as a long book's says."""
    data = bytearray(flac.read_bytes())
    assert data[:4] == b"fLaC" and data[4] & 0x7F == 0, "STREAMINFO first"
    field = int.from_bytes(data[18:26], "big")
    data[18:26] = ((field & ~((1 << 36) - 1)) | samples).to_bytes(8, "big")
    flac.write_bytes(bytes(data))


def test_the_deadline_is_the_playing_time_read_from_each_parts_header_plus_ten_minutes(tmp_path):
    require_ffmpeg()
    assert (edge.M4B_STEP_DEADLINE_FIXED_SECONDS, edge.M4B_STEP_DEADLINE_PER_AUDIO_SECOND) == (600.0, 1.0)
    first, second = _tone(tmp_path / "a.flac", 3, 300), _tone(tmp_path / "b.flac", 4.5, 400)
    assert edge.m4b_step_deadline([str(first), str(second)]) == pytest.approx(600 + 7.5, abs=0.01)
    # A 20-hour book: the header says so, and nothing is decoded to find out.
    long_part = _tone(tmp_path / "long.flac", 1, 500)
    _claim_length(long_part, 20 * 3600 * EDGE_RATE)
    started = time.monotonic()
    assert edge.m4b_step_deadline([str(long_part)]) == pytest.approx(600 + 72000, abs=0.01)
    assert time.monotonic() - started < 2.0
    # Not understood: counted from its size at 8 kbit/s, so only ever longer; missing: nothing (FFmpeg fails at once).
    junk = tmp_path / "junk.flac"
    junk.write_bytes(b"not audio" * 2000)
    assert edge.m4b_step_deadline([str(first), str(junk), str(tmp_path / "gone.flac")]) == pytest.approx(
        600 + 3 + 18000 / 1000, abs=0.01)


# --------------------------------------------------------------------------- #
# 3. make_m4b with real FFmpeg
# --------------------------------------------------------------------------- #


def _workdir_with_parts(tmp_path: Path, book, seconds: float | None = None) -> tuple[Path, list[str]]:
    work = tmp_path / "work"
    work.mkdir()
    parts = []
    for index, (_, part) in enumerate(book["parts"]):
        target = work / f"part{index}.flac"
        if seconds is None:
            shutil.copyfile(part, target)
        else:
            _tone(target, seconds, 300 + 100 * index)
        parts.append(str(target))
    (work / "My Book.txt").write_text("x", encoding="utf-8")
    edge.generate_metadata(parts, "Ann; O=Neil", "Tales #1", [title for title, _ in CHAPTERS], workdir=str(work))
    return work, parts


class Steps:
    """Every ``run_supervised`` call, with the SIGINT handler and the cancel scope in force while it ran."""

    def __init__(self, monkeypatch, rewrite=lambda argv: argv) -> None:
        self.calls: list[dict] = []
        real = sp.run_supervised

        def run(args, **kwargs):
            argv = list(args)
            self.calls.append({"argv": argv, "kwargs": dict(kwargs), "sigint": signal.getsignal(signal.SIGINT),
                               "scoped": sp._supervision.get() is not None, "started": time.monotonic()})
            try:
                return real(rewrite(argv), **kwargs)
            finally:
                self.calls[-1]["seconds"] = time.monotonic() - self.calls[-1]["started"]

        monkeypatch.setattr(sp, "run_supervised", run)


def test_make_m4b_runs_both_steps_supervised_and_keeps_every_chapter(tmp_path, monkeypatch, book):
    require_ffmpeg()
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler, "precondition: Python's own handler"
    work, parts = _workdir_with_parts(tmp_path, book)
    deadline = edge.m4b_step_deadline(parts)
    steps = Steps(monkeypatch)
    artifact = Path(edge.make_m4b(parts, str(work / "My Book.txt"), SPEAKER, workdir=str(work)))

    m4a = str(work / f"My Book ({SPEAKER}).m4a")
    assert [call["argv"][1:] for call in steps.calls] == [
        ["-f", "concat", "-safe", "0", "-i", str(work / "filelist.txt"), "-codec:a", "flac", "-f", "mp4", "-strict", "-2",
         m4a],
        ["-i", m4a, "-i", str(work / "FFMETADATAFILE"), "-map_metadata", "1", "-codec", "aac", str(artifact)],
    ], "the argument vectors are unchanged"
    assert all(call["argv"][0] == ffmpeg_utils.ffmpeg_cmd() for call in steps.calls)
    assert [call["kwargs"] for call in steps.calls] == [{"deadline_seconds": deadline}] * 2
    assert deadline == pytest.approx(600 + 30, abs=0.05)
    assert all(call["scoped"] and call["sigint"] is not signal.default_int_handler for call in steps.calls), \
        "while a step runs, a Ctrl+C is recorded for its supervisor rather than raised"
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler, "and Python's own handler is back afterwards"

    structure = metadata.read_chapter_structure(artifact)
    assert structure.titles == tuple(title for title, _ in CHAPTERS) and structure.track_samples == len(CHAPTERS)
    at = 0.0
    for (start, end), (_, seconds) in zip(structure.boundaries, CHAPTERS):
        assert (start, end) == (pytest.approx(at, abs=0.1), pytest.approx(at + seconds, abs=0.1))
        at += seconds
    probe = json.loads(subprocess.check_output([ffmpeg_utils.ffprobe_cmd(), "-v", "error", "-print_format", "json",
                                                "-show_streams", "-show_format", str(artifact)]))
    assert [(s["codec_type"], s.get("codec_name")) for s in probe["streams"]] == [("audio", "aac"), ("data", "bin_data")]
    assert probe["format"]["tags"]["artist"] == "Ann; O=Neil" and probe["format"]["tags"]["album"] == "Tales #1"
    assert {p.name for p in work.iterdir()} == {"My Book.txt", artifact.name}, "its own scratch removed, as before"


def test_a_step_running_at_the_playing_rate_is_not_cut_short(tmp_path, monkeypatch, book):
    """The deadline grows with the book: a step slowed to the playing rate (-re) outlasts the fixed part alone and still
    finishes, with every chapter."""
    require_ffmpeg()
    monkeypatch.setattr(edge, "M4B_STEP_DEADLINE_FIXED_SECONDS", 2.0)
    work, parts = _workdir_with_parts(tmp_path, book, seconds=2)
    slowed = lambda argv: [argv[0], "-re", *argv[1:]] if "aac" in argv else argv  # noqa: E731
    steps = Steps(monkeypatch, rewrite=slowed)
    artifact = Path(edge.make_m4b(parts, str(work / "My Book.txt"), SPEAKER, workdir=str(work)))
    encode = steps.calls[1]
    assert encode["kwargs"]["deadline_seconds"] == pytest.approx(2.0 + 6.0, abs=0.05)
    assert encode["seconds"] > 4.0, f"the encode really ran at the playing rate ({encode['seconds']:.2f} s), past 2 s"
    assert metadata.read_chapter_structure(artifact).track_samples == len(CHAPTERS)


def test_a_step_that_never_ends_is_stopped_at_its_deadline_and_the_next_never_starts(tmp_path, monkeypatch, book,
                                                                                    named_ffmpeg, sentinel):
    require_ffmpeg()
    monkeypatch.setattr(edge, "M4B_STEP_DEADLINE_FIXED_SECONDS", 1.0)
    monkeypatch.setattr(edge, "M4B_STEP_DEADLINE_PER_AUDIO_SECOND", 0.0)
    work, parts = _workdir_with_parts(tmp_path, book)
    spawned = Spawned(monkeypatch)
    stand_in = StandIn(monkeypatch, named_ffmpeg, lambda argv: "concat" in argv)
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        edge.make_m4b(parts, str(work / "My Book.txt"), SPEAKER, workdir=str(work))
    assert time.monotonic() - started < 1.0 + PROMPT_SECONDS
    assert raised.value.timeout == 1.0
    assert len(stand_in.calls) == 1 and stand_in.replaced is not None, "the encode never started"
    assert [child.poll() is not None for _argv, child, _ in spawned.children] == [True]
    assert _media_children() == [sentinel.pid]
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    assert not (work / f"My Book ({SPEAKER}).m4b").exists()


def test_an_ordinary_ffmpeg_failure_still_raises_and_starts_no_later_step(tmp_path, monkeypatch, book):
    require_ffmpeg()
    work, parts = _workdir_with_parts(tmp_path, book)
    Path(parts[0]).unlink()  # the concat cannot open its first part: FFmpeg exits non-zero
    steps = Steps(monkeypatch)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        edge.make_m4b(parts, str(work / "My Book.txt"), SPEAKER, workdir=str(work))
    assert raised.value.returncode != 0 and isinstance(raised.value.stderr, bytes) and raised.value.stderr
    assert len(steps.calls) == 1, "no second step after a failed first"
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


# --------------------------------------------------------------------------- #
# 4. The command line in a console of its own: a real Ctrl+C
# --------------------------------------------------------------------------- #


def _cli(tmp_path, book, *, published_before: bool = True, **config) -> tuple[cli.CliChild, Path, dict, dict]:
    out = tmp_path / "out"
    out.mkdir()
    (out / "Earlier Book (en-US-AndrewNeural).m4b").write_bytes(b"an earlier audiobook" * 1000)
    if published_before:
        (out / PUBLISHED).write_bytes(b"the same name, published before" * 1000)
    config = dict({"chapters": book["parts"], "title": "Tales #1", "author": "Ann; O=Neil", "sentinel": str(book["image"]),
                   "argv": [str(book["source"]), "--format", "m4b", "--output-dir", str(out), "--speaker", SPEAKER,
                            "--cover", str(book["cover"]), "--overwrite"]}, **config)
    child = cli.CliChild(tmp_path / "child", config, scripts=SCRIPTS)
    return child, out, tree(out), _sources(book)


def _settled(child: cli.CliChild, out: Path, out_before: dict, sources_before: dict, *, code: int | None,
             expected: int) -> dict:
    """The run ended with ``expected`` and left nothing: no process, no scratch, nothing published, nothing changed."""
    survivors = child.close()  # the test's own finally closed it already: this is that answer
    events = child.events()
    end = next((e for e in events if e.get("event") == "end"), None)
    output = child.output_text()
    assert code == expected, f"exit {code}, expected {expected}; output {output[-1500:]}"
    assert end is not None and end["code"] == expected
    assert survivors == [], f"processes of the run still running after it ended: {survivors}"
    assert end["media_children_left"] == [] and end["sentinel_alive"], "the sentinel lives; no step child is left"
    assert tree(out) == out_before, "nothing published; the earlier book and the same-named file are untouched"
    assert {p: sha(Path(p)) for p in sources_before} == sources_before, "the sources are unchanged"
    assert [p for p in (child.temp / "act-tts").rglob("*")] == [], "the run's work folder is removed"
    ready = next(e for e in events if e.get("event") == "ready")
    assert ready["in_job"], "everything the run started was in its job, so the job's list is exact"
    return {"events": events, "output": output, "spawns": [e for e in events if e.get("event") == "spawn"]}


@pytest.mark.parametrize("step", [1, 2], ids=["during-the-concat", "during-the-encode"])
def test_ctrl_c_during_a_step_stops_it_at_once_and_the_command_line_exits_130(step, tmp_path, book, sentinel):
    child, out, out_before, sources_before = _cli(tmp_path, book, slow_steps=[step])
    try:
        running = child.spawned(step)
        time.sleep(1.0)
        assert cli.alive(running["pid"], running["created"]), "the step was still running when Ctrl+C was pressed"
        pressed = child.ctrl_c()
        code = child.wait(60)
        exited = time.monotonic()
    finally:
        child.close()
    assert code is not None and exited - pressed < CLI_PROMPT_SECONDS, \
        f"exited {exited - pressed:.2f} s after the press; the step had {30 - 1.0:.0f} s left"
    run = _settled(child, out, out_before, sources_before, code=code, expected=edge.INTERRUPTED_EXIT_STATUS)
    assert [s["step"] for s in run["spawns"]] == list(range(1, step + 1)), "no step started after the press"
    assert not cli.alive(running["pid"], running["created"])
    assert "Interrupted (Ctrl+C). Nothing unfinished was saved." in run["output"]
    assert "Traceback" not in run["output"]
    for spawn in run["spawns"]:
        assert spawn["creationflags"] & subprocess.CREATE_NO_WINDOW and spawn["stdin_devnull"], "hidden, no stdin"


@pytest.mark.parametrize("after", [1, 2], ids=["between-the-steps", "after-the-last-step"])
def test_ctrl_c_between_or_after_the_steps_starts_nothing_more_and_publishes_nothing(after, tmp_path, book, sentinel):
    # The child waits 5 s there, as if busy, so the press lands at that point even on a loaded machine.
    child, out, out_before, sources_before = _cli(tmp_path, book, pause_after_step=[after, 5])
    try:
        child.wait_for(lambda e: e.get("event") == "after-step", what="the end of a step")
        child.ctrl_c()
        code = child.wait(60)
    finally:
        child.close()
    run = _settled(child, out, out_before, sources_before, code=code, expected=edge.INTERRUPTED_EXIT_STATUS)
    assert [s["step"] for s in run["spawns"]] == list(range(1, after + 1))


def test_repeated_ctrl_c_while_a_step_that_ignores_terminate_is_stopped_leaves_nothing_running(tmp_path, book, sentinel):
    """terminate does nothing to this child, so it is killed after the grace; the presses that land meanwhile must not cut
    that short (before the fix, they could have left it running)."""
    child, out, out_before, sources_before = _cli(tmp_path, book, slow_steps=[1], ignore_terminate=[1])
    try:
        running = child.spawned(1)
        time.sleep(1.0)
        pressed = child.ctrl_c()
        landed = []
        for _ in range(3):  # within the 2 s grace; a press after the run has ended finds no console, which is no error
            time.sleep(0.3)
            if child.process.poll() is not None:
                break
            landed.append((cli.alive(running["pid"], running["created"]), cli.send_ctrl_c(child.interpreter_pid)))
        code = child.wait(60)
        exited = time.monotonic()
    finally:
        child.close()
    assert (True, 0) in landed, f"no further press landed while the step was still being stopped: {landed}"
    run = _settled(child, out, out_before, sources_before, code=code, expected=edge.INTERRUPTED_EXIT_STATUS)
    assert any(e.get("event") == "terminate-ignored" for e in run["events"]), "terminate really was ignored"
    assert exited - pressed < sp.SUPERVISED_GRACE_SECONDS + CLI_PROMPT_SECONDS
    assert not cli.alive(running["pid"], running["created"])
    assert [s["step"] for s in run["spawns"]] == [1]


def test_a_genuinely_stalled_step_is_stopped_at_its_deadline_and_the_command_line_exits_124(tmp_path, book, sentinel):
    """A real FFmpeg, suspended by the operating system a second into the concat, makes no progress at all."""
    child, out, out_before, sources_before = _cli(
        tmp_path, book, slow_steps=[1], suspend_step=[1, 1.0],
        deadline={"M4B_STEP_DEADLINE_FIXED_SECONDS": 2.0, "M4B_STEP_DEADLINE_PER_AUDIO_SECOND": 0.1})
    try:
        running = child.spawned(1)
        code = child.wait(60)
        exited = time.monotonic()
    finally:
        child.close()
    run = _settled(child, out, out_before, sources_before, code=code, expected=edge.DEADLINE_EXIT_STATUS)
    assert any(e.get("event") == "suspended" for e in run["events"])
    deadline = 2.0 + 0.1 * 30
    ran = exited - running["t"]
    assert deadline <= ran < deadline + sp.SUPERVISED_GRACE_SECONDS + CLI_PROMPT_SECONDS, f"stopped after {ran:.2f} s"
    assert not cli.alive(running["pid"], running["created"])
    assert [s["step"] for s in run["spawns"]] == [1]
    assert "Stopped: FFmpeg was still running after 5 seconds" in run["output"] and "Traceback" not in run["output"]


def test_an_ordinary_ffmpeg_failure_exits_1_with_its_error_and_changes_nothing(tmp_path, book, sentinel):
    # The encode's program exits 1 at once (PING.EXE's "Bad value for option -n"), as a failing FFmpeg would.
    child, out, out_before, sources_before = _cli(tmp_path, book, stand_in={"2": [str(book["image"]), 0]})
    try:
        code = child.wait(60)
    finally:
        child.close()
    run = _settled(child, out, out_before, sources_before, code=code, expected=1)
    assert "subprocess.CalledProcessError" in run["output"] and "returned non-zero exit status 1" in run["output"]
    assert [s["step"] for s in run["spawns"]] == [1, 2]


def test_the_command_line_saves_a_whole_m4b_and_exits_0(tmp_path, book, sentinel):
    child, out, out_before, sources_before = _cli(tmp_path, book, published_before=False)
    try:
        code = child.wait(120)
    finally:
        survivors = child.close()
    assert code == 0, child.output_text()[-1500:]
    assert survivors == []
    published = out / PUBLISHED
    after = tree(out)
    assert set(after) == set(out_before) | {PUBLISHED} and all(after[k] == v for k, v in out_before.items())
    assert {p: sha(Path(p)) for p in sources_before} == sources_before
    assert [p for p in (child.temp / "act-tts").rglob("*")] == []
    structure = metadata.read_chapter_structure(published)
    assert structure.titles == tuple(title for title, _ in CHAPTERS) and structure.track_samples == len(CHAPTERS)
    probe = json.loads(subprocess.check_output([ffmpeg_utils.ffprobe_cmd(), "-v", "error", "-print_format", "json",
                                                "-show_streams", "-show_format", str(published)]))
    assert [s["codec_type"] for s in probe["streams"]] == ["audio", "data", "video"], "the cover, added after assembly"
    assert probe["streams"][0]["codec_name"] == "aac"
    assert probe["format"]["tags"]["artist"] == "Ann; O=Neil"
    assert f"Saved: {published}" in child.output_text()


# --------------------------------------------------------------------------- #
# 5. Structure
# --------------------------------------------------------------------------- #


def test_each_m4b_step_runs_supervised_with_its_deadline_inside_the_ctrl_c_scope():
    tree_ = source_probe.module("tts/epub2tts_edge/epub2tts_edge.py")
    functions = {node.name: node for node in tree_.body if isinstance(node, ast.FunctionDef)}
    runner = functions["_run_ffmpeg"]
    via_sp = {node.func.attr for node in ast.walk(runner) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute) and ast.unparse(node.func.value) == "_sp"}
    assert via_sp == {"run_supervised"}, via_sp
    make = functions["make_m4b"]
    scopes = [node for node in ast.walk(make) if isinstance(node, ast.With)
              and [ast.unparse(item.context_expr) for item in node.items] == ["_ctrl_c_stops_the_step()"]]
    assert len(scopes) == 1
    inside = [ast.unparse(node) for node in ast.walk(scopes[0]) if isinstance(node, ast.Call)
              and ast.unparse(node.func) == "_run_ffmpeg"]
    assert inside == ["_run_ffmpeg(ffmpeg_command, deadline_seconds=deadline)"] * 2
    everywhere = [node for node in ast.walk(make) if isinstance(node, ast.Call) and ast.unparse(node.func) == "_run_ffmpeg"]
    assert len(everywhere) == 2, "no step outside the scope"
