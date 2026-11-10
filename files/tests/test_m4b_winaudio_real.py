"""The real Windows Media Foundation decoder on real media (v0.7.2 Phase 8, ACT72-048).

``test_m4b_winaudio.py`` proves the route's logic with a fake reader and says so: "Nothing here calls Windows." Until
this module nothing called the production reader (``m4b_winaudio._Reader``: ``IMFSourceReader`` over ctypes) at all.

Here it decodes real books, made by the pinned FFmpeg from a declared recipe, and what arrives is held to facts taken
independently of it: the container's own stream properties and coded-frame count (ffprobe), and FFmpeg's own decode of
the same file (a different decoder). The last section drives the Converter's whole Windows route on a real book: the
real plan, the real reader, the real pipe into the real encoder, the real publication.

**What this is not.** The books are AAC-LC, the one codec both Media Foundation and FFmpeg decode, which is what makes
the comparison possible. The application sends only xHE-AAC to this decoder, and no xHE-AAC file can be generated
here (no encoder exists in the pinned FFmpeg or in Windows), so these tests say nothing about the USAC decoder
itself. A real xHE-AAC book is a separate, recorded qualification on the owner's own file.

Writing it found a defect the fake reader could not show: the format the reader negotiates before it has decoded
anything is not always the format of the bytes that arrive (a mono 22.05 kHz book was announced as 44.1 kHz stereo).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pytest

tk = pytest.importorskip("tkinter")

from shared import ffmpeg_utils, output_paths  # noqa: E402
from shared import job_control as jc  # noqa: E402
from shared import subprocess_utils as sp  # noqa: E402

from m4b import m4b_probe, m4b_winaudio  # noqa: E402
from m4b.converter import m4b_converter  # noqa: E402
from m4b.converter.m4b_plan import ConversionMode  # noqa: E402

from gate_locator import GATE_DIR, REPO_ROOT  # noqa: E402
from test_import_coordination import RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_continuous import LENGTHS_MS, StubThread, _ThreadShim, make_book  # noqa: E402
from test_m4b_conversion_plan import _reservation  # noqa: E402
from test_m4b_metadata import require_ffmpeg  # noqa: E402
import tk_gate  # noqa: E402

sys.path.insert(0, str(GATE_DIR))
from helpers import media_oracle as oracle  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Media Foundation is Windows'")

AAC_FRAME = 1024
#: (name, sample rate, channels): the stream shapes the Converter's other routes are qualified on, plus low-rate mono,
#: which is where the decoder's first answer about its own output was wrong.
SHAPES = [("stereo-44k", 44100, 2), ("mono-22k", 22050, 1), ("stereo-48k", 48000, 2)]


@pytest.fixture(scope="module", autouse=True)
def media_foundation():
    """A red gate, not a skip: on a Windows without the media stack this coverage is missing, and that must be seen."""
    require_ffmpeg()
    m4b_winaudio.reset_capability()
    if not m4b_winaudio.available():
        pytest.fail("Media Foundation cannot start on this Windows (an N edition without the Media Feature Pack?), "
                    "so the real decoder cannot be exercised here.")


def _probe(path: Path) -> dict:
    out = subprocess.run([ffmpeg_utils.ffprobe_cmd(), "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=codec_name,profile,sample_rate,channels,duration_ts,nb_frames,initial_padding",
                          "-of", "json", str(path)], stdout=subprocess.PIPE, check=True).stdout
    return json.loads(out)["streams"][0]


def _ffmpeg_decode(path: Path, channels: int) -> np.ndarray:
    """FFmpeg's own decode of the book: 16-bit, the stream's own rate and channel count, mixed to one channel."""
    raw = subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-i", str(path), "-map", "0:a:0",
                          "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"], stdout=subprocess.PIPE, check=True).stdout
    return _mono(raw, channels)


def _mono(pcm: bytes, channels: int) -> np.ndarray:
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768.0
    return samples.reshape(-1, channels).mean(axis=1)


def _decode(path: Path, **kwargs):
    """The production decode, with the production reader: no ``reader_factory``."""
    stream = m4b_winaudio.decode_pcm(path, **kwargs)
    fmt = next(stream)
    return fmt, list(stream)


@pytest.fixture(scope="module")
def books(tmp_path_factory) -> dict:
    folder = tmp_path_factory.mktemp("media_foundation_books")
    return {name: make_book(folder, name, rate=rate, channels=channels, cover=False) for name, rate, channels in SHAPES}


# --------------------------------------------------------------------------- #
# The reader itself
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name, rate, channels", SHAPES, ids=[shape[0] for shape in SHAPES])
def test_the_real_reader_reports_the_streams_own_format_and_delivers_every_coded_frame(books, name, rate, channels):
    facts = _probe(books[name])
    assert (facts["codec_name"], facts["profile"]) == ("aac", "LC"), "the fixture is the codec this test is about"
    assert (int(facts["sample_rate"]), int(facts["channels"])) == (rate, channels)

    fmt, chunks = _decode(books[name])
    assert (fmt.sample_rate, fmt.channels, fmt.bits) == (rate, channels, 16), \
        "the format the caller is told must be the format of the bytes that arrive"
    pcm = b"".join(chunks)
    assert len(pcm) % fmt.frame_bytes == 0
    delivered = len(pcm) // fmt.frame_bytes
    coded = int(facts["nb_frames"]) * AAC_FRAME
    playable = int(facts["duration_ts"])
    # Media Foundation hands back every coded frame, the encoder's priming and final padding included; FFmpeg trims
    # both (the edit list). So a complete decode is exactly the coded frames, and never fewer than the playable ones.
    assert delivered == coded, (delivered, coded)
    assert playable <= delivered <= playable + int(facts["initial_padding"]) + AAC_FRAME
    assert all(len(chunk) <= m4b_winaudio.CHUNK_BYTES for chunk in chunks), "bounded chunks, whatever the length"
    assert all(len(chunk) == m4b_winaudio.CHUNK_BYTES for chunk in chunks[:-1])


@pytest.mark.parametrize("name, rate, channels", SHAPES, ids=[shape[0] for shape in SHAPES])
def test_a_real_decode_is_the_same_audio_ffmpeg_decodes_from_the_same_book(books, name, rate, channels):
    """A different decoder is the oracle. The two agree sample for sample in time, offset by exactly the priming."""
    facts = _probe(books[name])
    fmt, chunks = _decode(books[name])
    ours = _mono(b"".join(chunks), fmt.channels)
    theirs = _ffmpeg_decode(books[name], channels)
    metrics = oracle.compare_interval(theirs, ours, rate=rate, limit=4 * AAC_FRAME)
    assert metrics["lag_samples"] == int(facts["initial_padding"]), metrics
    assert metrics["correlation"] >= 0.999, metrics
    assert 0.9 <= metrics["head_energy"] <= 1.1 and 0.9 <= metrics["tail_energy"] <= 1.1, metrics


def test_two_real_decodes_of_one_book_are_the_same_bytes(books):
    first = hashlib.sha256(b"".join(_decode(books["stereo-44k"])[1])).hexdigest()
    second = hashlib.sha256(b"".join(_decode(books["stereo-44k"])[1])).hexdigest()
    assert first == second


def test_the_real_timeline_serves_one_sequential_decode_in_exact_pieces(books):
    """What a split book does: one decode, cut at byte counts, nothing lost or repeated at any cut."""
    whole = b"".join(_decode(books["stereo-44k"])[1])
    with m4b_winaudio.PcmTimeline(books["stereo-44k"]) as timeline:
        assert (timeline.format.sample_rate, timeline.format.channels, timeline.format.bits) == (44100, 2, 16)
        assert timeline.bytes_for(1.0) == 44100 * 4 and timeline.bytes_for(0.5) % timeline.format.frame_bytes == 0
        pieces: list[bytes] = []
        for seconds in (0.3, 1.7, 0.001, 2.5):
            part: list[bytes] = []
            wanted = timeline.bytes_for(seconds)
            assert timeline.feed(part.append, wanted) == wanted
            pieces.append(b"".join(part))
        rest: list[bytes] = []
        remaining = timeline.feed(rest.append, None)
        assert timeline.feed(rest.append, 4096) == 0, "past the end a feed delivers nothing; it never pads"
        assert timeline.delivered == len(whole)
    assert [len(piece) for piece in pieces] == [timeline.bytes_for(s) for s in (0.3, 1.7, 0.001, 2.5)]
    assert b"".join(pieces) + b"".join(rest) == whole and remaining == len(b"".join(rest))


def test_cancel_ends_a_real_decode_early_and_the_book_can_be_read_again(books):
    whole = b"".join(_decode(books["stereo-48k"])[1])
    asked = {"n": 0}

    def cancelled() -> bool:
        asked["n"] += 1
        return asked["n"] > 40

    _fmt, chunks = _decode(books["stereo-48k"], cancelled=cancelled, chunk_bytes=4096)
    got = b"".join(chunks)
    assert 0 < len(got) < len(whole) and whole.startswith(got), "an early end is a prefix, never other audio"
    assert b"".join(_decode(books["stereo-48k"])[1]) == whole, "and the reader let go of the file"


def test_a_file_that_is_not_media_and_a_missing_file_are_refused_loudly(tmp_path):
    impostor = tmp_path / "not-a-book.m4b"
    impostor.write_bytes(b"this is text, not an audiobook\n" * 200)
    for source in (impostor, tmp_path / "missing.m4b"):
        with pytest.raises(m4b_winaudio.DecodeError) as refused:
            _decode(source)
        assert "HRESULT 0x" in str(refused.value)


def test_a_format_the_decoder_changes_after_the_first_buffer_is_refused_not_followed():
    """The one thing here that real media cannot be made to do on demand, so the reader's own rule is driven directly:
    everything downstream was told the first format, and audio read at another rate is a wrong book."""
    reader = object.__new__(m4b_winaudio._Reader)
    first, second = m4b_winaudio.PcmFormat(44100, 2, 16), m4b_winaudio.PcmFormat(22050, 1, 16)
    script = [(b"\x01\x02", False), (b"\x03\x04", True), (b"\x05\x06", True)]
    reports = [first, second]
    reader.format = first
    reader._primed = []

    def decode_next():
        block, changed = script.pop(0)
        reader._format_changed = changed
        return block

    reader._decode_next = decode_next
    reader._negotiated_format = lambda: reports.pop(0)
    assert reader.read() == b"\x01\x02"
    assert reader.read() == b"\x03\x04", "a change notice that reports the same format is not a change"
    with pytest.raises(m4b_winaudio.DecodeError) as refused:
        reader.read()
    assert "changed its output format" in str(refused.value) and "22050 Hz" in str(refused.value)


# --------------------------------------------------------------------------- #
# The Converter's whole Windows route on a real book
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture(scope="module")
def tools():
    return oracle.pinned_toolchain(REPO_ROOT)


@pytest.fixture(scope="module")
def chaptered(tmp_path_factory) -> Path:
    return make_book(tmp_path_factory.mktemp("windows_route_book"), "Routed")


class _Silent:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture()
def windows_route(tk_root, monkeypatch):
    """The real panel, with one thing declared: this AAC-LC book is to be treated as one FFmpeg cannot decode.

    That is the question the production probe asks (``needs_special_aac_decoder``) and the only stand-in on the route.
    Everything it leads to is the production's own: the plan chooses the Windows decoder because Media Foundation
    really is available, the real reader decodes, the real pipe feeds the real encoder, the real executor publishes.
    """
    StubThread.started = []
    monkeypatch.setattr(m4b_converter, "threading", _ThreadShim())
    monkeypatch.setattr(m4b_converter.sp, "reveal_in_file_manager", lambda target: None)
    monkeypatch.setattr(m4b_probe.ffmpeg_utils, "needs_special_aac_decoder", lambda info: True)
    readers: list = []
    real_reader = m4b_winaudio._Reader

    class CountedReader(real_reader):
        def __init__(self, path):
            readers.append(Path(path))
            super().__init__(path)

    monkeypatch.setattr(m4b_winaudio, "_Reader", CountedReader)
    commands: list = []
    real_popen = sp.popen

    def popen(cmd, **kwargs):
        commands.append([str(part) for part in cmd])
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr(sp, "popen", popen)
    made: list = []

    def run(source: Path, folder: Path, mode: ConversionMode):
        panel = m4b_converter.M4BConverterUI(
            tk_root, effective_config=make_config(), clock=lambda: 0.0, home=None, thread_factory=RecordingThreads(),
            choose_files=lambda: (str(source),), choose_folder=lambda: (), confirm_broad_root=lambda roots: False,
            confirm_large_result=lambda outcome: True, bridge=jc.LoggerBridge(logger=_Silent()))
        made.append(panel)
        panel.importer.add_files()
        panel.var_mode.set(mode.value)
        panel.start_convert()
        params = StubThread.started[-1].args[0]
        with mock.patch.object(output_paths, "reserve_run_directory", side_effect=_reservation(folder)):
            panel.convert_worker(params)
        panel._pump.tick()
        return panel, readers, commands

    yield run
    for panel in made:
        panel.close()
        panel.destroy()


def _routed(panel, readers, commands, source: Path) -> None:
    """The run really went through Media Foundation, once, and the encoder really read PCM from its pipe."""
    item, = panel.run_plan.items
    assert item.windows_decode and item.undecodable_xhe and item.continuous is None
    assert readers == [source], "one sequential decode for the whole book"
    encoders = [argv for argv in commands if "pipe:0" in argv]
    assert encoders and all(argv[argv.index("pipe:0") - 7:argv.index("pipe:0") - 1] ==
                            ["-f", "s16le", "-ar", "44100", "-ac", "2"] for argv in encoders), encoders
    assert not any("-ss" in argv for argv in commands), "nothing seeks: the cut is made in the decoded stream"


def test_a_whole_book_through_the_real_windows_route_is_the_whole_book(windows_route, chaptered, tools, tmp_path):
    source_hash = hashlib.sha256(chaptered.read_bytes()).hexdigest()
    panel, readers, commands = windows_route(chaptered, tmp_path, ConversionMode.WHOLE)
    assert panel.run_result.state is jc.JobState.SUCCEEDED, list(panel.log.details)[-6:]
    _routed(panel, readers, commands, chaptered)
    output, = sorted(panel.run_plan.run_directory.rglob("*.mp3"))
    assert oracle.full_decode_errors(tools, output) == ""
    reference = oracle.decode_pcm(tools, chaptered)
    metrics = oracle.compare_interval(reference, oracle.decode_pcm(tools, output), limit=2 * AAC_FRAME)
    priming_at_oracle_rate = AAC_FRAME * oracle.ORACLE_RATE // 44100
    assert abs(metrics["lag_samples"] - priming_at_oracle_rate) <= oracle.MAX_LAG_SAMPLES, metrics
    assert oracle.interval_problems(metrics, max_lag=priming_at_oracle_rate + oracle.MAX_LAG_SAMPLES) == [], metrics
    assert hashlib.sha256(chaptered.read_bytes()).hexdigest() == source_hash, "the source is never written"


def test_a_split_book_through_the_real_windows_route_gives_every_chapter_its_own_audio(windows_route, chaptered,
                                                                                         tools, tmp_path):
    panel, readers, commands = windows_route(chaptered, tmp_path, ConversionMode.SPLIT)
    assert panel.run_result.state is jc.JobState.SUCCEEDED, list(panel.log.details)[-6:]
    _routed(panel, readers, commands, chaptered)
    outputs = sorted(panel.run_plan.run_directory.rglob("*.mp3"))
    assert len(outputs) == len(LENGTHS_MS)
    reference = oracle.decode_pcm(tools, chaptered)
    rate = oracle.ORACLE_RATE
    priming = AAC_FRAME * rate // 44100
    start = 0
    for output, length in zip(outputs, LENGTHS_MS):
        assert oracle.full_decode_errors(tools, output) == "", output.name
        # The decode carries the encoder's priming, so each chapter is its own interval of the book, that much later.
        first = start * rate // 1000 - priming
        span = reference[max(0, first):first + length * rate // 1000]
        metrics = oracle.compare_interval(span, oracle.decode_pcm(tools, output), limit=2 * AAC_FRAME)
        allowed = oracle.MAX_LAG_SAMPLES + (priming if first < 0 else 0)
        assert oracle.interval_problems(metrics, max_lag=allowed) == [], (output.name, metrics)
        start += length
