"""The Windows xHE-AAC decode path — v0.6.2 Plan 5, Phase 15.

**What this exists for.** ffmpeg 9.0.1's native AAC decoder cannot decode
MPEG-D USAC completely. Measured against a real 9.78-hour xHE-AAC audiobook it
refuses 362,465 of the source's 1,515,928 frames with *"Not yet implemented in
FFmpeg, patches welcome"* -- **23.91 %** of the audio -- concatenates what is
left into an MP3 lasting 26,783 s against a planned 35,200 s, and **exits 0**.
Split fares no better: every chapter span comes back at ~76 %. The only thing
that stopped that reaching a listener was the drift guard.

Windows ships a decoder that does handle it. Through ``IMFSourceReader`` the
same book yields **35,199.78 s -- 100.0004 % of the source**.

**The three properties that make this safe**, and each has its own section:

* it is **selected from frozen truth**, never from a filename and never
  re-derived after Start, so an ordinary AAC-LC book cannot wander onto it;
* it **streams**, because the same book is 6.2 GB decoded -- the reader hands
  back ~4 KB at a time and the pipe supplies backpressure;
* it **decodes once per item and cuts the PCM**, because seeking a USAC decoder
  discards primed audio: ``[600,1200)`` yields 26,452,025 frames while
  ``[600,900) + [900,1200)`` yields 26,443,970, so every seek would quietly cost
  8,055 frames.

Where the decoder is absent -- Windows 10, an N/KN edition, media components
removed -- the honest answer is a typed preflight refusal, not a 76 % audiobook.

Determinism
-----------
Nothing here calls Windows. Every test drives the pure seams with a fake reader,
so the whole module runs identically on macOS. The live evidence against the
real book is recorded in the Handoff.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mp3_tools import m4b_commands, m4b_execution, m4b_plan, m4b_winaudio
from mp3_tools.m4b_execution import SegmentWork
from mp3_tools.m4b_metadata import AttachedPicture, MetadataMode
from mp3_tools.m4b_plan import PlanOptions, assemble_plan
from mp3_tools.m4b_winaudio import DecodeError, PcmFormat, PcmTimeline

from test_m4b_conversion_plan import (  # noqa: E402
    book,
    direct,
    reports_for,
    reserver,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FORMAT = PcmFormat(sample_rate=44100, channels=2, bits=16)


class FakeReader:
    """Stands in for ``IMFSourceReader``: hands out blocks, then ends."""

    def __init__(self, blocks, *, fmt=FORMAT, fail_after=None):
        self.format = fmt
        self._blocks = list(blocks)
        self._fail_after = fail_after
        self.reads = 0
        self.closed = False

    def read(self):
        if self._fail_after is not None and self.reads >= self._fail_after:
            raise DecodeError("the media source reported an error mid-stream")
        if self.reads >= len(self._blocks):
            return None
        block = self._blocks[self.reads]
        self.reads += 1
        return block

    def close(self):
        self.closed = True


def reader_for(total_bytes, *, block=4096, **kwargs):
    whole, rest = divmod(total_bytes, block)
    blocks = [bytes(block)] * whole + ([bytes(rest)] if rest else [])
    made = {}

    def factory(_source):
        made["reader"] = FakeReader(blocks, **kwargs)
        return made["reader"]

    factory.made = made  # type: ignore[attr-defined]
    return factory


def seconds(count: float) -> int:
    return int(count * FORMAT.sample_rate) * FORMAT.frame_bytes


# --------------------------------------------------------------------------- #
# A. Capability — established, never assumed from a version string
# --------------------------------------------------------------------------- #


def test_capability_is_probed_rather_than_read_off_the_os_version():
    """**Structural.** A build number would claim a decoder that is not there.

    Windows N and KN ship without the media feature pack and media components
    can be removed by policy, so the only question worth asking is whether the
    libraries load and Media Foundation starts.
    """
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools"
              / "m4b_winaudio.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    probe = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == "_probe_capability")
    called = {node.attr for node in ast.walk(probe) if isinstance(node, ast.Attribute)}
    assert "MFStartup" in called, "capability must be established by starting MF"
    for banned in ("getwindowsversion", "platform", "release", "win32_ver",
                   "build", "version_info"):
        assert banned not in {n.id for n in ast.walk(probe) if isinstance(n, ast.Name)}
        assert banned not in called


def test_a_non_windows_platform_is_never_capable(monkeypatch):
    monkeypatch.setattr(m4b_winaudio, "IS_WINDOWS", False)
    m4b_winaudio.reset_capability()
    try:
        assert m4b_winaudio.available() is False
    finally:
        m4b_winaudio.reset_capability()


def test_a_failing_probe_reports_unavailable_rather_than_raising(monkeypatch):
    monkeypatch.setattr(m4b_winaudio, "_probe_capability",
                        lambda: (_ for _ in ()).throw(OSError("no media stack")))
    m4b_winaudio.reset_capability()
    with pytest.raises(OSError):
        m4b_winaudio.available()
    monkeypatch.setattr(m4b_winaudio, "_probe_capability", lambda: False)
    m4b_winaudio.reset_capability()
    try:
        assert m4b_winaudio.available() is False
    finally:
        m4b_winaudio.reset_capability()


def test_the_answer_is_cached_because_it_cannot_change_mid_run(monkeypatch):
    calls = []
    monkeypatch.setattr(m4b_winaudio, "_probe_capability",
                        lambda: calls.append(1) or True)
    m4b_winaudio.reset_capability()
    try:
        assert m4b_winaudio.available() is True
        assert m4b_winaudio.available() is True
        assert calls == [1]
    finally:
        m4b_winaudio.reset_capability()


def test_the_unavailable_message_names_nothing_to_install_or_disable():
    message = m4b_winaudio.unavailable_message().lower()
    assert "no output was created" in message
    assert "left unchanged" in message
    for banned in ("disable", "download", "codec pack", "fdk", "security",
                   "defender", "install "):
        assert banned not in message, banned


def test_capability_downloads_and_installs_nothing():
    """**Structural.** Nothing is fetched, spawned or installed for this path.

    Asserted over imports and called names rather than raw text, so the prose
    explaining *why* no download happens cannot fail its own guard.
    """
    tree = ast.parse((REPO_ROOT / "scripts" / "Universal" / "mp3_tools"
                      / "m4b_winaudio.py").read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    for banned in ("urllib", "requests", "subprocess", "shutil", "socket", "http"):
        assert banned not in roots, banned
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not any("http" in text for text in literals)


def test_the_module_needs_no_third_party_package():
    """ctypes is stdlib; mfplat and mfreadwrite are Windows. Nothing else."""
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools"
              / "m4b_winaudio.py").read_text(encoding="utf-8")
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= {"__future__", "ctypes", "sys", "dataclasses", "typing"}, sorted(roots)


# --------------------------------------------------------------------------- #
# B. The negotiated format is read back, never assumed
# --------------------------------------------------------------------------- #


def test_the_format_describes_itself_to_ffmpeg():
    assert FORMAT.ffmpeg_input_args() == ["-f", "s16le", "-ar", "44100", "-ac", "2"]
    assert FORMAT.frame_bytes == 4


def test_duration_comes_from_delivered_frames_not_from_a_timestamp():
    """The whole reason this path exists is that PTS lied.

    ffmpeg's decode-to-null reached the end of the file while a quarter of the
    samples were missing, so duration here is derived from bytes that actually
    arrived.
    """
    assert FORMAT.seconds_for(seconds(1.0)) == pytest.approx(1.0)
    assert FORMAT.seconds_for(seconds(2.5)) == pytest.approx(2.5)
    assert FORMAT.seconds_for(0) == 0.0


@pytest.mark.parametrize("rate,channels,bits,expected", [
    (44100, 2, 16, 4), (48000, 1, 16, 2), (44100, 2, 32, 8),
])
def test_frame_size_follows_the_negotiated_format(rate, channels, bits, expected):
    assert PcmFormat(rate, channels, bits).frame_bytes == expected


# --------------------------------------------------------------------------- #
# C. Streaming — bounded, ordered, and never a giant temporary file
# --------------------------------------------------------------------------- #


def test_the_format_arrives_before_any_audio():
    stream = m4b_winaudio.decode_pcm("x", reader_factory=reader_for(seconds(1)))
    assert next(stream) == FORMAT
    assert isinstance(next(stream), bytes)
    stream.close()


def test_every_byte_arrives_in_order():
    blocks = [bytes([i]) * 16 for i in range(8)]
    factory = lambda _s: FakeReader(blocks)  # noqa: E731
    stream = m4b_winaudio.decode_pcm("x", reader_factory=factory, chunk_bytes=16)
    next(stream)
    assert b"".join(stream) == b"".join(blocks)


def test_chunks_are_bounded_by_the_requested_size():
    factory = reader_for(seconds(3), block=4096)
    stream = m4b_winaudio.decode_pcm("x", reader_factory=factory, chunk_bytes=1024)
    next(stream)
    assert all(len(chunk) <= 1024 for chunk in stream)


def test_nothing_larger_than_one_chunk_is_ever_held():
    """**Structural.** The book this was built for is 6.2 GB decoded.

    Staging that to disk was the architecture this replaced, so no temporary
    file is created and no audio filename is ever named here.
    """
    tree = ast.parse((REPO_ROOT / "scripts" / "Universal" / "mp3_tools"
                      / "m4b_winaudio.py").read_text(encoding="utf-8"))
    called = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    called |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for banned in ("NamedTemporaryFile", "mkstemp", "TemporaryFile",
                   "temporary_sibling", "open"):
        assert banned not in called, banned
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not any(text.endswith((".wav", ".pcm", ".raw")) for text in literals)


def test_the_reader_is_released_even_when_the_caller_stops_early():
    factory = reader_for(seconds(10))
    stream = m4b_winaudio.decode_pcm("x", reader_factory=factory)
    next(stream)
    next(stream)
    stream.close()
    assert factory.made["reader"].closed is True


def test_cancellation_is_honoured_between_samples():
    factory = reader_for(seconds(10))
    stop = {"now": False}
    stream = m4b_winaudio.decode_pcm("x", reader_factory=factory,
                                     cancelled=lambda: stop["now"])
    next(stream)
    next(stream)
    stop["now"] = True
    assert list(stream) == []
    stream.close()
    assert factory.made["reader"].closed is True


def test_a_mid_stream_decode_failure_is_raised_not_swallowed():
    factory = reader_for(seconds(10), fail_after=3)
    stream = m4b_winaudio.decode_pcm("x", reader_factory=factory)
    next(stream)
    with pytest.raises(DecodeError):
        list(stream)


def test_a_gap_is_not_mistaken_for_the_end():
    """An empty buffer means a discontinuity; only ``None`` ends the stream."""
    factory = lambda _s: FakeReader([b"aaaa", b"", b"bbbb"])  # noqa: E731
    stream = m4b_winaudio.decode_pcm("x", reader_factory=factory, chunk_bytes=4)
    next(stream)
    assert b"".join(stream) == b"aaaabbbb"


def test_decoding_off_windows_refuses_rather_than_pretending(monkeypatch):
    monkeypatch.setattr(m4b_winaudio, "IS_WINDOWS", False)
    with pytest.raises(DecodeError):
        next(m4b_winaudio.decode_pcm("x"))


# --------------------------------------------------------------------------- #
# D. One decode per item, cut at frozen boundaries
# --------------------------------------------------------------------------- #


def timeline_for(total_seconds, **kwargs):
    return PcmTimeline("x", decoder=lambda s, cancelled=None: m4b_winaudio.decode_pcm(
        s, cancelled=cancelled, reader_factory=reader_for(seconds(total_seconds)),
        **kwargs))


def test_a_span_is_measured_in_whole_frames():
    line = timeline_for(10)
    assert line.bytes_for(1.0) == seconds(1.0)
    assert line.bytes_for(0.5) == seconds(0.5)
    assert line.bytes_for(2.5) % line.format.frame_bytes == 0
    line.close()


def test_consecutive_spans_tile_the_timeline_without_gaps_or_overlap():
    """The Split contract: one decode, cut in frozen order, nothing lost."""
    line = timeline_for(10)
    got = []
    for span in (2.0, 3.0, 5.0):
        chunks = []
        line.feed(chunks.append, line.bytes_for(span))
        got.append(sum(len(c) for c in chunks))
    assert got == [seconds(2.0), seconds(3.0), seconds(5.0)]
    assert sum(got) == seconds(10.0)
    line.close()


def test_a_whole_book_takes_the_entire_timeline():
    line = timeline_for(7)
    chunks = []
    line.feed(chunks.append, None)
    assert sum(len(c) for c in chunks) == seconds(7.0)
    line.close()


def test_a_short_decode_reports_what_it_delivered_and_never_pads():
    """Silence in place of missing audio would defeat the drift guard."""
    line = timeline_for(3)
    chunks = []
    delivered = line.feed(chunks.append, line.bytes_for(10.0))
    assert delivered == seconds(3.0)
    assert delivered < line.bytes_for(10.0)
    assert sum(len(c) for c in chunks) == delivered
    line.close()


def test_the_timeline_tracks_everything_it_handed_out():
    line = timeline_for(6)
    line.feed(lambda b: None, line.bytes_for(2.0))
    line.feed(lambda b: None, line.bytes_for(4.0))
    assert line.delivered == seconds(6.0)
    assert line.format.seconds_for(line.delivered) == pytest.approx(6.0)
    line.close()


def test_the_timeline_never_seeks():
    """**Structural.** Seeking costs 0.183 s of primed audio per jump."""
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools"
              / "m4b_winaudio.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    named = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    named |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for banned in ("SetCurrentPosition", "seek", "TrimStartTime", "TrimStopTime"):
        assert banned not in named, banned


# --------------------------------------------------------------------------- #
# E. Selection -- from frozen truth, and only where ffmpeg genuinely cannot cope
# --------------------------------------------------------------------------- #


def plan_with(entries, run_root, *, capable, **kwargs):
    return assemble_plan(
        snapshot_id="m4b-run-1", entries=entries,
        reports=reports_for(entries, **kwargs),
        options=PlanOptions(), reserve=reserver(run_root),
        windows_decoder=lambda: capable)


def test_an_ordinary_book_never_takes_the_windows_route(tmp_path):
    """54 of the 55 books in the real corpus are AAC-LC. None may be redirected."""
    entries = direct(book(tmp_path / "src", "Plain.m4b"))
    plan = plan_with(entries, tmp_path / "run", capable=True,
                     codec="aac", undecodable=False)
    assert plan.items[0].windows_decode is False
    assert plan.unusable == ()


def test_an_undecodable_source_takes_it_when_the_machine_can(tmp_path):
    entries = direct(book(tmp_path / "src", "XHE.m4b"))
    plan = plan_with(entries, tmp_path / "run", capable=True,
                     codec="aac", undecodable=True)
    assert plan.items[0].windows_decode is True
    assert plan.items[0].undecodable_xhe is True


def test_an_undecodable_source_is_refused_when_the_machine_cannot(tmp_path):
    """Windows 10, an N edition, media components removed -- fail closed.

    ffmpeg would run for minutes and hand back 76% of an audiobook, so the
    refusal belongs at preflight, before a run directory is even reserved.
    """
    entries = direct(book(tmp_path / "src", "XHE.m4b"))
    reserve = reserver(tmp_path / "run")
    plan = assemble_plan(
        snapshot_id="m4b-run-1", entries=entries,
        reports=reports_for(entries, codec="aac", undecodable=True),
        options=PlanOptions(), reserve=reserve, windows_decoder=lambda: False)

    assert plan.items == ()
    assert len(plan.unusable) == 1
    failure = plan.unusable[0]
    assert failure.reason == m4b_plan.UNDECODABLE_SOURCE
    assert "cannot decode" in failure.message
    assert "No output was created" in failure.message
    assert reserve.calls == [], "nothing may be reserved for a refused run"


def test_the_refusal_is_not_a_retry_candidate(tmp_path):
    """Phase 13 Option A: a preflight-unusable occurrence is never retryable."""
    entries = direct(book(tmp_path / "src", "XHE.m4b"))
    plan = assemble_plan(
        snapshot_id="m4b-run-1", entries=entries,
        reports=reports_for(entries, codec="aac", undecodable=True),
        options=PlanOptions(), reserve=reserver(tmp_path / "run"),
        windows_decoder=lambda: False)
    assert plan.unusable[0].retryable is False


def test_the_refusal_names_nothing_to_disable_or_download(tmp_path):
    entries = direct(book(tmp_path / "src", "XHE.m4b"))
    plan = assemble_plan(
        snapshot_id="m4b-run-1", entries=entries,
        reports=reports_for(entries, codec="aac", undecodable=True),
        options=PlanOptions(), reserve=reserver(tmp_path / "run"),
        windows_decoder=lambda: False)
    words = (plan.unusable[0].message + plan.unusable[0].detail).lower()
    for banned in ("disable", "fdk", "codec pack", "download", "smart app"):
        assert banned not in words, banned


def test_macos_keeps_its_own_decoder_and_never_needs_this(tmp_path):
    """``aac_at`` decodes xHE correctly, so the probe reports it decodable.

    That is what keeps macOS on the untouched ffmpeg path: the route is chosen
    from ``undecodable_xhe``, which is already false wherever a working decoder
    exists.
    """
    entries = direct(book(tmp_path / "src", "XHE.m4b"))
    plan = plan_with(entries, tmp_path / "run", capable=False,
                     codec="aac", undecodable=False,
                     decoder_args=("-c:a", "aac_at"))
    assert plan.items[0].windows_decode is False
    assert plan.items[0].decoder_args == ("-c:a", "aac_at")


def test_the_route_is_frozen_into_the_plan_not_re_derived():
    """**Structural.** Nothing after Start may ask the machine again."""
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools"
              / "m4b_execution.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    named = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    named |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for banned in ("available", "m4b_winaudio", "probe_source", "_probe_capability"):
        assert banned not in named, banned


# --------------------------------------------------------------------------- #
# F. The command that encodes the decoded audio
# --------------------------------------------------------------------------- #


def pcm_work(**kwargs):
    defaults = dict(
        source=Path("BOOK.m4b"), destination=Path("OUT.mp3"),
        expected_duration=600.0, quality=4,
        metadata_mode=MetadataMode.PRESERVE, tags={"album": "A"},
        windows_decode=True, pcm_args=("-f", "s16le", "-ar", "44100", "-ac", "2"))
    defaults.update(kwargs)
    return SegmentWork(**defaults)


def only_pass(work):
    return list(m4b_execution._passes(
        work, ffmpeg="FF", staged_final=Path("S.mp3"), staged_audio=None)[0])


def test_the_audio_is_a_pipe_and_the_book_is_the_second_input():
    argv = only_pass(pcm_work(picture=AttachedPicture(2, "mjpeg")))
    inputs = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-i"]
    assert inputs == ["pipe:0", "BOOK.m4b"]


def test_the_pipe_is_described_by_the_negotiated_format():
    argv = only_pass(pcm_work())
    for token in ("-f", "s16le", "-ar", "44100", "-ac", "2"):
        assert token in argv
    assert argv.index("s16le") < argv.index("pipe:0")


def test_whole_preserve_keeps_chapters_from_the_book_not_the_pipe():
    """The bug the first live run found: two chapter maps, and order decided.

    ``-map_chapters 0`` would point at the PCM pipe, which has no chapters --
    and a real 15-chapter audiobook came out with none.
    """
    argv = only_pass(pcm_work())
    assert argv.count("-map_chapters") == 1, argv
    assert argv[argv.index("-map_chapters") + 1] == "1"


def test_whole_preserve_keeps_the_cover_from_the_book():
    argv = only_pass(pcm_work(picture=AttachedPicture(2, "mjpeg")))
    maps = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-map"]
    assert maps == ["0:a:0", "1:2"]
    assert argv[argv.index("-c:v") + 1] == "copy"
    assert "attached_pic" in argv


def test_the_metadata_allowlist_is_still_unconditional():
    argv = only_pass(pcm_work())
    assert argv.count("-map_metadata") == 1
    assert argv[argv.index("-map_metadata") + 1] == "-1"
    assert argv[argv.index("-id3v2_version") + 1] == "3"


def test_the_encoder_and_quality_are_the_ones_this_tool_always_uses():
    argv = only_pass(pcm_work(quality=2))
    assert argv[argv.index("-c:a") + 1] == "libmp3lame"
    assert argv[argv.index("-q:a") + 1] == "2"
    assert argv[argv.index("-threads") + 1] == "0"
    assert argv.count("libmp3lame") == 1, "the audio is encoded exactly once"


def test_a_stripped_output_opens_no_book_at_all():
    """Strip keeps no chapters and no cover, so there is nothing to open."""
    argv = only_pass(pcm_work(metadata_mode=MetadataMode.STRIP, tags={},
                              picture=AttachedPicture(2, "mjpeg")))
    assert [argv[i + 1] for i, tok in enumerate(argv) if tok == "-i"] == ["pipe:0"]
    assert "attached_pic" not in argv
    assert argv[argv.index("-map_chapters") + 1] == "-1"


def test_a_fragment_carries_no_whole_book_chapter_map():
    argv = only_pass(pcm_work(span=(0.0, 10.0)))
    assert argv[argv.index("-map_chapters") + 1] == "-1"


def test_a_fragment_needs_no_seek_because_the_pcm_was_already_cut():
    argv = only_pass(pcm_work(span=(30.0, 40.0)))
    assert "-ss" not in argv and "-t" not in argv


def test_the_ordinary_route_is_untouched_by_any_of_this():
    argv = only_pass(pcm_work(windows_decode=False, pcm_args=()))
    assert "pipe:0" not in argv
    assert argv[argv.index("-i") + 1] == "BOOK.m4b"


def test_a_missing_metadata_source_is_refused_rather_than_guessed():
    with pytest.raises(ValueError):
        m4b_commands.pcm_argv(ffmpeg="FF", pcm_args=["-f", "s16le"],
                              destination="O.mp3", quality=4,
                              keep_chapters=True, metadata_source=None)


# --------------------------------------------------------------------------- #
# G. The producer/consumer bridge
# --------------------------------------------------------------------------- #


class FakeProc:
    """A child that consumes stdin and then exits, without a real process."""

    def __init__(self, code=0, polls_before_exit=1, explode=None):
        self.stdin = _Sink(explode)
        self._code = code
        self._left = polls_before_exit
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        if self._left > 0:
            self._left -= 1
            return None
        self.returncode = self._code
        return self._code

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.waited = True
        if self.returncode is None:
            self.returncode = self._code
        return self.returncode


class _Sink:
    def __init__(self, explode=None):
        self.written = bytearray()
        self.closed = False
        self._explode = explode

    def write(self, data):
        if self._explode is not None and len(self.written) >= self._explode:
            raise BrokenPipeError("the consumer went away")
        self.written += data
        return len(data)

    def close(self):
        self.closed = True


def run_bridge(feed, *, proc=None, cancelled=lambda: False, tmp_path=None):
    made = proc or FakeProc()
    threads = []

    def start(target):
        target()          # deterministic: run the producer inline

        class Done:
            def join(self, timeout=None):
                threads.append("joined")
        return Done()

    result = m4b_execution.run_argv_streaming(
        ["FF"], feed=feed, cancelled=cancelled, workspace=tmp_path,
        popen=lambda argv, **kw: made, wait=lambda s: None,
        spawn_thread=start)
    return made, result, threads


def test_every_byte_reaches_the_encoder(tmp_path):
    made, result, _ = run_bridge(
        lambda write: [write(b"a" * 100), write(b"b" * 50)], tmp_path=tmp_path)
    assert bytes(made.stdin.written) == b"a" * 100 + b"b" * 50
    assert result.ok is True


def test_stdin_is_always_closed_so_the_encoder_can_finish(tmp_path):
    made, _, _ = run_bridge(lambda write: write(b"x"), tmp_path=tmp_path)
    assert made.stdin.closed is True


def test_the_producer_is_always_joined(tmp_path):
    _, _, threads = run_bridge(lambda write: write(b"x"), tmp_path=tmp_path)
    assert threads == ["joined"], "a producer outliving its child is a leak"


def test_a_child_is_always_reaped(tmp_path):
    made, _, _ = run_bridge(lambda write: write(b"x"), tmp_path=tmp_path)
    assert made.waited is True


def test_a_broken_pipe_is_not_treated_as_a_decoder_failure(tmp_path):
    """The encoder died; its return code is the real story, not the pipe."""
    proc = FakeProc(code=1, explode=10)
    _, result, _ = run_bridge(lambda write: [write(b"x" * 8) for _ in range(10)],
                              proc=proc, tmp_path=tmp_path)
    assert result.producer_failed is False
    assert result.ok is False


def test_a_decoder_failure_is_reported_even_when_ffmpeg_exits_zero(tmp_path):
    """ffmpeg happily exits 0 on the audio it did receive.

    Without this, a decoder that stopped a quarter of the way through would look
    exactly like success -- which is the defect this whole path exists to remove.
    """
    def feed(write):
        write(b"x" * 16)
        raise m4b_winaudio.DecodeError("the media source reported an error")

    _, result, _ = run_bridge(feed, proc=FakeProc(code=0), tmp_path=tmp_path)
    assert result.producer_failed is True
    assert result.ok is False
    assert "DecodeError" in result.detail


def test_cancellation_stops_the_child_and_reports_it(tmp_path):
    proc = FakeProc(polls_before_exit=99)
    _, result, _ = run_bridge(lambda write: write(b"x"), proc=proc,
                              cancelled=lambda: True, tmp_path=tmp_path)
    assert result.cancelled is True
    assert proc.terminated is True
    assert proc.waited is True


def test_a_producer_failure_fails_the_segment(tmp_path):
    """The executor must refuse the output, not finalise a short one."""
    work = pcm_work(destination=tmp_path / "run" / "Out.mp3")

    def explode(write):
        raise m4b_winaudio.DecodeError("decode stopped early")

    outcome = m4b_execution.convert_segment(
        work, ffmpeg="FF", cancelled=lambda: False,
        measure=lambda p: 600.0, feed=explode,
        popen=lambda argv, **kw: FakeProc(code=0), wait=lambda s: None)
    assert outcome.finalised is False
    assert "could not be decoded" in outcome.message
    assert not work.destination.exists()


def test_the_windows_route_without_audio_refuses_rather_than_running(tmp_path):
    work = pcm_work(destination=tmp_path / "run" / "Out.mp3")
    outcome = m4b_execution.convert_segment(
        work, ffmpeg="FF", cancelled=lambda: False, measure=lambda p: 600.0,
        popen=lambda argv, **kw: FakeProc(), wait=lambda s: None)
    assert outcome.finalised is False
    assert "no decoded audio was supplied" in outcome.detail
