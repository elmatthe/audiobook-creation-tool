"""v0.8.x P5-H-R1: the two HIGH findings of the independent Codex review of P5-H (``7b1b309``), and their regressions.

**HIGH 1, parts in different formats.** On a Mac every narration at the assembly gate is assembled on disk (P5-H). The disk
spool refused a part whose rate or channel count differed from the first, but one narration routinely holds two: Edge speech
is 24 kHz mono, and the 50 ms silence ``run_edgespeak`` writes for a sentence with nothing to say (``É.``) is pydub's 11,025
Hz. The in-memory join converts (pydub's ``_sync``); the spool refused, so the file failed after all its synthesis, and Retry
Failed failed again. Now the spool joins them exactly as pydub does:

  * A. The conversion itself, block by block, against pydub's one call; the spool against pydub for every placement of a
    higher or lower rate or channel count (first, middle, last, rising more than once), to the byte, with block boundaries
    that split frames; the encoded MP3 against the in-memory route's.
  * B. The production direct route at the real gate threshold with the genuine silent clip (only the voice service is stood
    in for): before, between and after speech, and in a chapter of its own that meets speech only at the final join. The
    Mac's disk route publishes the in-memory route's MP3, to the byte.
  * C. Malformed parts and failures mid-conversion leave nothing behind; a channel mix pydub cannot join is refused; memory
    stays small while what is held is converted.

**HIGH 2, FFmpeg after Cancel.** The spool's scans had no Cancel checkpoint and ``Supervised`` started a process with no look
at the run's latch, so a Cancel during the audible check was followed by an MP3 encode. Now no FFmpeg starts after the
latch (the start is decided under the controller's own lock), and the work between processes stops at the next block.

  * D. Every listed Cancel point, on the folder and the direct route, with a real ``JobController``: each records every
    process start and asserts none after the latch, the reservation back, no spool or chunk left, nothing published and an
    existing destination untouched; a later run succeeds. Each latch is placed by a hook, never by a sleep.
  * E. ``Supervised`` itself: refused before the start, killed at once when the latch lands during the start, and a process
    that will not end is not reported as a clean end.

The originals of D's "before the final encode" case and of B's first case are the reviewer's own probes
(``files/dev-work/macos-p5-closeout/p5h-r1/probes``); at ``7b1b309`` both fail as the review says.
"""

from __future__ import annotations

import asyncio
import builtins
import os
import random
import subprocess
import sys
import tracemalloc
from pathlib import Path

import numpy as np
import pytest
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError
from pydub.generators import Sine

from shared import ffmpeg_utils, subprocess_utils
from shared.cancellation import ConversionCancelled
from shared.job_control import JobController
from tts import batch_convert, disk_assembly, ffmpeg_watch, publication
from tts import worker_limits as wl
from tts.epub2tts_edge import epub2tts_edge as engine
from tts.epub2tts_edge import runner

from test_assembly_on_disk import clip_for, needs_ffmpeg  # noqa: E402  (real 24 kHz Edge-format clips)

GB = 1024 ** 3
MB = 1024 ** 2


@pytest.fixture()
def plenty(monkeypatch):
    """20 GB free: the in-memory rule would admit any of these narrations."""
    gate = wl.AssemblyGate(lambda: wl.MemoryInfo(20 * GB, 32 * GB), poll_seconds=0.001)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    return gate


def _tone(rate: int, channels: int, ms: int, hz: int) -> AudioSegment:
    mono = Sine(hz, sample_rate=rate).to_audio_segment(duration=ms, volume=-12).set_channels(1)
    if channels == 1:
        return mono
    # Channels that differ, so a swapped or duplicated channel would show.
    other = Sine(hz * 1.5, sample_rate=rate).to_audio_segment(duration=ms, volume=-15).set_channels(1)
    return AudioSegment.from_mono_audiosegments(mono, other)


@pytest.fixture(scope="module")
def formats(tmp_path_factory) -> dict[str, Path]:
    """Small FLAC parts in each format that matters: Edge's, pydub's silence, and rates and channels above and below them."""
    ffmpeg_utils.configure_pydub()
    folder = tmp_path_factory.mktemp("formats")
    made = {}
    for name, segment in {
        "speech24": _tone(24000, 1, 731, 300),
        "silence11": AudioSegment.silent(duration=50),  # what run_edgespeak writes for "É.", 11,025 Hz
        "quiet11": _tone(11025, 1, 413, 220),
        "low8": _tone(8000, 1, 377, 700),
        "stereo48": _tone(48000, 2, 529, 500),
        "stereo24": _tone(24000, 2, 611, 900),
        "empty48": AudioSegment.silent(duration=0, frame_rate=48000),
    }.items():
        made[name] = folder / f"{name}.flac"
        segment.export(made[name], format="flac")
    return made


def _pydub_join(paths, pause: AudioSegment | None = None) -> AudioSegment:
    combined = AudioSegment.empty()
    for index, path in enumerate(paths):
        if index and pause is not None:
            combined += pause
        combined += AudioSegment.from_file(path)
    return combined


ORDERS = [
    ("silence11", "speech24", "speech24"),             # the reviewed case: the silence first
    ("speech24", "silence11", "speech24"),             # between speech
    ("speech24", "speech24", "silence11"),             # last
    ("silence11", "quiet11", "speech24", "quiet11"),   # a held stretch of several parts converted in one go
    ("low8", "silence11", "speech24", "stereo48", "speech24"),  # rising three times, channels with the last rise
    ("stereo48", "speech24", "silence11"),             # the highest first: every later part converted on its own
    ("speech24", "stereo24", "silence11", "low8"),     # more channels at the same rate
    ("speech24", "empty48", "speech24"),               # a part with no audio still raises the format, as in pydub
    ("silence11", "silence11"),                        # all one lower format: nothing converted
]


# --------------------------------------------------------------------------- A. the conversion and the spool


@pytest.mark.parametrize("source,target", [((11025, 1), (24000, 1)), ((8000, 1), (48000, 2)), ((24000, 1), (24000, 2)),
                                           ((22050, 2), (44100, 2)), ((24000, 1), (11025, 1))])
def test_a_stretch_converted_block_by_block_is_pydubs_one_conversion(source, target):
    rng = np.random.default_rng(sum(source) + sum(target))
    frames = 30_011
    segment = AudioSegment(data=rng.integers(-20000, 20000, frames * source[1], dtype=np.int16).tobytes(), sample_width=2,
                           frame_rate=source[0], channels=source[1])
    expected = segment.set_channels(target[1]).set_frame_rate(target[0]).raw_data
    convert = disk_assembly._Conversion(source, target)
    data, out, position, draw = segment.raw_data, [], 0, random.Random(5)
    while position < len(data):
        step = draw.randint(1, 7001)  # odd sizes: frames split across blocks
        out.append(convert(data[position:position + step]))
        position += step
    assert b"".join(out) == expected


@needs_ffmpeg
@pytest.mark.parametrize("order", ORDERS, ids=["-".join(order) for order in ORDERS])
def test_the_spool_joins_any_mix_of_formats_to_pydubs_file(tmp_path, formats, monkeypatch, order):
    monkeypatch.setattr(disk_assembly, "BLOCK_BYTES", 4099)  # blocks that end mid-frame, and many of them
    pause = AudioSegment.silent(duration=250)
    expected = _pydub_join([formats[name] for name in order], pause)
    expected.export(tmp_path / "pydub.wav", format="wav")

    with disk_assembly.WavSpool(tmp_path / "spool.wav") as spool:
        for index, name in enumerate(order):
            if index:
                spool.append_segment(pause)
            spool.append_file(formats[name])
        spool.finish()
        assert (spool.rate, spool.channels) == (expected.frame_rate, expected.channels)
        assert spool.pcm_bytes == len(expected.raw_data) and spool.duration_ms == len(expected)
        written = (tmp_path / "spool.wav").read_bytes()
        assert written[disk_assembly.WAV_HEADER_BYTES:] == expected.raw_data, "the samples, in order"
        assert written == (tmp_path / "pydub.wav").read_bytes(), "the whole file pydub's export writes"
        assert spool.max_dBFS == expected.max_dBFS
    assert not list(tmp_path.glob("spool.wav*")), "neither the spool nor a conversion of it is left"


@needs_ffmpeg
@pytest.mark.parametrize("order", [ORDERS[0], ORDERS[2], ORDERS[4]], ids=["silence-first", "silence-last", "rising"])
def test_the_disk_encode_of_mixed_parts_is_the_in_memory_mp3_to_the_byte(tmp_path, formats, order):
    """``make_mp3`` and ``make_mp3_on_disk`` (the direct route's final encode) on the same parts: the same MP3 file."""
    outputs = {}
    for route, make in (("memory", engine.make_mp3), ("disk", engine.make_mp3_on_disk)):
        folder = tmp_path / route
        folder.mkdir()
        parts = []
        for index, name in enumerate(order):  # both remove what they are given
            parts.append(str(folder / f"{index}-{name}.flac"))
            Path(parts[-1]).write_bytes(formats[name].read_bytes())
        outputs[route] = Path(make(parts, str(folder / "book.txt"), "v", bitrate="192k")).read_bytes()
    assert outputs["disk"] == outputs["memory"]


# --------------------------------------------------------------------------- B. the production route at the real gate


class OfflineEdge:
    """The voice service, and only it, stood in for: a three-minute 24 kHz clip per speakable sentence, by its text."""

    def __init__(self, text, speaker, *args, **kwargs):
        assert engine._SPEAKABLE.search(text), "an unspeakable sentence never reaches the service"
        self.text = text

    async def save(self, filename):
        await asyncio.sleep(0)
        Path(filename).write_bytes(clip_for(self.text, seconds=180))


@pytest.fixture()
def genuine_silence(monkeypatch):
    """The real ``run_edgespeak`` (its silent clip for "É." included), the real sentence tokenizer, the real threshold."""
    monkeypatch.setattr(engine.edge_tts, "Communicate", OfflineEdge)
    seen = {"joins": [], "encodes": []}
    for name, key in (("join_to_flac", "joins"), ("encode_mp3", "encodes")):
        real = getattr(disk_assembly, name)

        def spy(parts, *args, _real=real, _key=key, **kwargs):
            parts = list(parts)
            seen[_key].append(sorted(disk_assembly._formats(p for p in parts if not isinstance(p, AudioSegment))))
            return _real(parts, *args, **kwargs)

        monkeypatch.setattr(disk_assembly, name, spy)
    return seen


HEAD = "Title: Test\nAuthor: Test\n"
BOOKS = {
    # The reviewer's book (HIGH 1): one chapter whose 17,340,640 bytes reach the 16 MiB gate, the silence first.
    "silence-first": HEAD + "É.\nFirst English paragraph.\nSecond English paragraph.\n",
    "silence-between": HEAD + "First English paragraph.\nÉ.\nSecond English paragraph.\n",
    "silence-last": HEAD + "First English paragraph.\nSecond English paragraph.\nÉ.\n",
    # A chapter of only the silence, at 11,025 Hz, below the gate on its own: it meets speech at the final join only.
    "silence-chapter-first": HEAD + "# ***\n\nÉ.\n# ***\n\nFirst English paragraph.\nSecond English paragraph.\n",
    "silence-chapter-last": HEAD + "# ***\n\nFirst English paragraph.\nSecond English paragraph.\n# ***\n\nÉ.\n",
}


@needs_ffmpeg
@pytest.mark.parametrize("book", list(BOOKS))
def test_the_direct_route_at_the_real_gate_publishes_the_in_memory_mp3_with_the_genuine_silence(
        tmp_path, monkeypatch, plenty, genuine_silence, book):
    assert wl.ASSEMBLY_GATE_MIN_PCM_BYTES == 16 * MB, "the real threshold, not a test's"
    source = tmp_path / "in" / "book.txt"
    source.parent.mkdir()
    source.write_text(BOOKS[book], encoding="utf-8")

    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", True)  # every other platform: the reference
    reference = Path(runner.run_conversion_job(str(source), output_dir=str(tmp_path / "memory"), audio_format="mp3",
                                               speaker="v", mp3_bitrate="192k")).read_bytes()
    assert genuine_silence == {"joins": [], "encodes": []}, "negative control: with memory free nothing went to disk"

    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", False)  # a Mac
    mac = Path(runner.run_conversion_job(str(source), output_dir=str(tmp_path / "mac"), audio_format="mp3", speaker="v",
                                         mp3_bitrate="192k")).read_bytes()
    assert mac == reference
    mixed = [formats for formats in genuine_silence["joins"] + genuine_silence["encodes"] if len(formats) > 1]
    assert mixed and all((11025, 1) in formats and (24000, 1) in formats for formats in mixed), (
        "the disk route really met the 11,025 Hz silence beside 24 kHz speech", genuine_silence)
    if book.startswith("silence-chapter"):
        assert genuine_silence["encodes"] == [[(11025, 1), (24000, 1)]], "the mix is at the final join, across chapters"
    else:
        assert genuine_silence["joins"] == [[(11025, 1), (24000, 1)]], "the mix is inside the chapter at the gate"
    assert plenty._in_use == 0


# --------------------------------------------------------------------------- C. failures, refusals, memory


@needs_ffmpeg
@pytest.mark.parametrize("damaged_at", [0, 1, 2])
def test_a_damaged_part_among_mixed_formats_fails_and_leaves_nothing(tmp_path, formats, damaged_at):
    parts = [formats["silence11"], formats["speech24"], formats["stereo48"]]
    damaged = tmp_path / "damaged.flac"
    damaged.write_bytes(b"fLaC" + os.urandom(2048))
    parts[damaged_at] = damaged
    with pytest.raises(CouldntDecodeError):
        disk_assembly.encode_mp3(parts, tmp_path / "out.mp3", tmp_path / "spool.wav", bitrate="192k")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["damaged.flac"], "no spool, conversion or output"
    assert not ffmpeg_watch._watched


@needs_ffmpeg
def test_a_failure_while_held_audio_is_converted_removes_both_files(tmp_path, formats, monkeypatch):
    real = disk_assembly._Conversion.__call__
    calls = {"n": 0}

    def failing(self, block):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError(28, "No space left on device")
        return real(self, block)

    monkeypatch.setattr(disk_assembly, "BLOCK_BYTES", 4096)
    monkeypatch.setattr(disk_assembly._Conversion, "__call__", failing)
    with pytest.raises(publication.PublicationError, match="ran out of space"):
        disk_assembly.join_to_flac([formats["quiet11"], formats["speech24"]], tmp_path / "out.flac", tmp_path / "spool.wav")
    assert not list(tmp_path.iterdir()), "no spool, no half-converted copy, no output"


@needs_ffmpeg
def test_channels_pydub_cannot_join_are_refused_as_pydub_refuses_them(tmp_path):
    ffmpeg_utils.configure_pydub()
    two, six = tmp_path / "two.wav", tmp_path / "six.wav"
    _tone(24000, 2, 100, 300).export(two, format="wav")
    six_channels = AudioSegment(data=np.zeros(2400 * 6, dtype=np.int16).tobytes(), sample_width=2, frame_rate=24000,
                                channels=6)
    six_channels.export(six, format="wav")
    with pytest.raises(ValueError):
        _pydub_join([two, six])
    with pytest.raises(ValueError, match="cannot be joined"):
        disk_assembly.join_to_flac([two, six], tmp_path / "out.flac", tmp_path / "spool.wav")
    assert not list(tmp_path.glob("spool.wav*")) and not (tmp_path / "out.flac").exists()


@needs_ffmpeg
def test_converting_a_long_held_stretch_stays_small_in_memory(tmp_path):
    """Sixteen MiB held at 11,025 Hz, then 24 kHz parts: the whole held stretch is converted, a block at a time."""
    ffmpeg_utils.configure_pydub()
    rng = np.random.default_rng(2)
    parts = []
    for index, rate in enumerate([11025] * 4 + [24000] * 4):
        path = tmp_path / f"part{index}.flac"
        AudioSegment(data=rng.integers(-3000, 3000, 2 * MB, dtype=np.int16).tobytes(), sample_width=2, frame_rate=rate,
                     channels=1).export(path, format="flac")
        parts.append(path)
    tracemalloc.start()
    try:
        disk_assembly.join_to_flac(parts, tmp_path / "out.flac", tmp_path / "spool.wav")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 12 * MB, f"{peak} bytes to join and convert about 64 MiB of audio"
    expected = 4 * 2 * MB * 24000 / 11025 + 4 * 2 * MB  # frames, all at 24 kHz
    assert AudioSegment.from_file(tmp_path / "out.flac").frame_count() == pytest.approx(expected, abs=4)


def test_the_room_needed_counts_every_part_at_the_joined_format_and_the_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(disk_assembly, "_formats", lambda paths: {(11025, 1), (24000, 1)})
    monkeypatch.setattr(wl, "decoded_size", lambda paths: 1000)
    assert disk_assembly._room_needed(["a", "b"]) == 2 * 1000 * 24000 // 11025
    monkeypatch.setattr(disk_assembly, "_formats", lambda paths: {(24000, 1)})
    assert disk_assembly._room_needed(["a", "b"]) == 1000, "one format: exactly as before"


# --------------------------------------------------------------------------- D. Cancel, at every point


class Starts:
    """Every process started, and whether the run had been cancelled when it was. ``all`` and ``processes`` are those of the
    assembly (from ``worker_limits.assemble`` on): the test's own stand-in clips are made with FFmpeg during synthesis."""

    def __init__(self, monkeypatch, controller: JobController):
        self.controller = controller
        self.after_cancel: list[list[str]] = []
        self.all: list[list[str]] = []
        self.processes: list[subprocess.Popen] = []
        self.on_start = None
        self.assembling = False
        real = subprocess_utils.popen

        def popen(args, **kwargs):
            late = controller.cancel_check()
            process = real(args, **kwargs)
            if late:
                self.after_cancel.append(list(map(str, args)))
            if self.assembling:
                self.all.append(list(map(str, args)))
                self.processes.append(process)
                if self.on_start is not None:
                    self.on_start(args)
            return process

        monkeypatch.setattr(subprocess_utils, "popen", popen)
        real_assemble = wl.assemble

        def assemble(*args, **kwargs):
            self.assembling = True
            return real_assemble(*args, **kwargs)

        monkeypatch.setattr(wl, "assemble", assemble)

    def cancel(self) -> None:
        self.controller.request_cancel()
        ffmpeg_watch.wake()
        wl.ASSEMBLY_GATE.wake()


FOLDER_TEXT = "".join(f"Sentence number {n} of this long text, which is read in chunks. " for n in range(300))


@pytest.fixture()
def mac_folder(tmp_path, monkeypatch, plenty):
    """The Mac's folder route: disk only, every narration at the gate, small blocks so a stage has many of them."""
    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", False)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    monkeypatch.setattr(disk_assembly, "BLOCK_BYTES", 64 * 1024)
    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3",
                        lambda text, path, voice, rate: Path(path).write_bytes(clip_for(text, seconds=20)))
    monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)
    source = tmp_path / "in" / "book.txt"
    source.parent.mkdir()
    source.write_text(FOLDER_TEXT, encoding="utf-8")
    controller = JobController("p5h-r1")
    controller.start()
    starts = Starts(monkeypatch, controller)
    destination = tmp_path / "out" / "book.mp3"
    destination.parent.mkdir()
    destination.write_bytes(b"a previous result")

    def run(*, overwrite=True):
        return batch_convert.convert_single_pdf(source, destination.parent, "v", "+0%", lambda _m: None, out_mp3=destination,
                                                bitrate="192k", cancel_check=controller.cancel_check, overwrite=overwrite)

    return {"run": run, "starts": starts, "controller": controller, "destination": destination, "gate": plenty,
            "root": tmp_path}


def _assert_cancelled_cleanly(world, result):
    status, _path, error = result
    assert status == "cancelled", error
    starts = world["starts"]
    assert starts.after_cancel == [], f"FFmpeg started after the Cancel: {starts.after_cancel}"
    assert world["destination"].read_bytes() == b"a previous result", "the existing destination is untouched"
    assert world["gate"]._in_use == 0 and world["gate"]._on_disk == 0 and not world["gate"]._queue
    assert not ffmpeg_watch._watched, "no FFmpeg is still watched"
    for process in starts.processes:
        assert process.poll() is not None, "every FFmpeg started has ended"
    leftovers = [p for p in world["root"].rglob("*") if p.suffix in (".wav", ".convert", ".part") or "chunk_" in p.name]
    assert leftovers == [], leftovers
    assert world["controller"].commits_in_flight == 0


def _arm(monkeypatch, target, name, *, before=None, after=None, nth=1):
    """Wrap ``target.name`` so the Cancel is latched just before (or just after) its ``nth`` call."""
    real = getattr(target, name)
    calls = {"n": 0}

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == nth and before is not None:
            before()
        result = real(*args, **kwargs)
        if calls["n"] == nth and after is not None:
            after()
        return result

    monkeypatch.setattr(target, name, wrapped)
    return calls


@needs_ffmpeg
def test_cancel_before_the_assembly_is_admitted(mac_folder, monkeypatch):
    on_disk = []
    monkeypatch.setattr(disk_assembly, "encode_mp3", lambda *a, **k: on_disk.append(1))
    _arm(monkeypatch, wl, "assemble", before=mac_folder["starts"].cancel)
    _assert_cancelled_cleanly(mac_folder, mac_folder["run"]())
    assert on_disk == [] and mac_folder["starts"].all == []


@needs_ffmpeg
def test_cancel_while_waiting_at_the_gate(mac_folder, monkeypatch):
    starved = wl.AssemblyGate(lambda: wl.MemoryInfo(1 * MB, 8 * GB), poll_seconds=0.01, wait_seconds=3600)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", starved)
    mac_folder["gate"] = starved
    real_note = wl._say

    def note(say, text):
        if text.startswith("Waiting for memory"):
            mac_folder["starts"].cancel()  # the wait has begun: Cancel now
        real_note(say, text)

    monkeypatch.setattr(wl, "_say", note)
    _assert_cancelled_cleanly(mac_folder, mac_folder["run"]())
    assert mac_folder["starts"].all == []


@needs_ffmpeg
def test_cancel_once_admitted_before_the_disk_work_starts(mac_folder, monkeypatch):
    real_note = wl._say

    def note(say, text):
        real_note(say, text)
        if text.startswith("On a Mac"):  # said once the place is given, before either route
            mac_folder["starts"].cancel()

    monkeypatch.setattr(wl, "_say", note)
    _assert_cancelled_cleanly(mac_folder, mac_folder["run"]())
    assert mac_folder["starts"].all == []


@needs_ffmpeg
def test_cancel_at_the_instant_before_ffmpeg_is_created(mac_folder, monkeypatch):
    """The latch lands after every earlier look and before the process exists: the start is refused, not killed later."""
    armed = {"on": False}
    real_watchdog = ffmpeg_watch._ensure_watchdog

    def last_moment():
        if armed["on"]:
            armed["on"] = False
            mac_folder["starts"].cancel()
        real_watchdog()

    monkeypatch.setattr(ffmpeg_watch, "_ensure_watchdog", last_moment)
    _arm(monkeypatch, disk_assembly, "encode_mp3", before=lambda: armed.update(on=True))
    _assert_cancelled_cleanly(mac_folder, mac_folder["run"]())
    assert mac_folder["starts"].all == [], "not even the first decoder"


@needs_ffmpeg
def test_cancel_between_two_parts(mac_folder, monkeypatch):
    _arm(monkeypatch, disk_assembly.WavSpool, "append_file", after=mac_folder["starts"].cancel)
    _assert_cancelled_cleanly(mac_folder, mac_folder["run"]())
    assert len(mac_folder["starts"].all) == 1, "the first part's decoder, and no other"


@needs_ffmpeg
def test_cancel_while_a_part_is_decoded(mac_folder, monkeypatch):
    written_after = []
    real = disk_assembly.WavSpool._write
    calls = {"n": 0}

    def write(self, data):
        calls["n"] += 1
        if calls["n"] == 3:
            mac_folder["starts"].cancel()
        real(self, data)
        if mac_folder["controller"].cancel_check():
            written_after.append(len(data))

    monkeypatch.setattr(disk_assembly.WavSpool, "_write", write)
    _assert_cancelled_cleanly(mac_folder, mac_folder["run"]())
    assert written_after == [], "nothing more was read into the spool"
    assert len(mac_folder["starts"].all) == 1


@needs_ffmpeg
def test_cancel_during_the_audible_scan_before_the_final_encode(mac_folder, monkeypatch):
    """The reviewer's interleaving (HIGH 2): the latch at the first block of ``max_dBFS``."""
    reads_after = []

    class Watched:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()

        def seek(self, *args):
            return self.handle.seek(*args)

        def read(self, size=-1):
            if not mac_folder["controller"].cancel_check():
                mac_folder["starts"].cancel()
            else:
                reads_after.append(size)
            return self.handle.read(size)

    measure = disk_assembly.WavSpool.max_dBFS.fget

    def measured(spool):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(disk_assembly, "open", lambda path, mode: Watched(builtins.open(path, mode)), raising=False)
            return measure(spool)

    monkeypatch.setattr(disk_assembly.WavSpool, "max_dBFS", property(measured))
    _assert_cancelled_cleanly(mac_folder, mac_folder["run"]())
    decoders = [args for args in mac_folder["starts"].all if args[-1] == "-"]
    assert len(decoders) == len(mac_folder["starts"].all), "decoders only: no encoder"
    assert reads_after == [], "the scan stopped at its next block"


@needs_ffmpeg
def test_cancel_after_the_final_tail_before_the_encode(mac_folder, monkeypatch):
    _arm(monkeypatch, disk_assembly.WavSpool, "apply_final_tail", after=mac_folder["starts"].cancel)
    _assert_cancelled_cleanly(mac_folder, mac_folder["run"]())
    assert not any("mp3" in args for args in mac_folder["starts"].all if args[-1] != "-")


@needs_ffmpeg
def test_cancel_during_the_encode_kills_it_at_once(mac_folder):
    starts = mac_folder["starts"]

    def on_start(args):
        if "-b:a" in args or args[-2:-1] == ["mp3"] or str(args[-1]).endswith(".part"):
            starts.on_start = None
            starts.cancel()  # the encoder exists and is about to be watched

    starts.on_start = on_start
    result = mac_folder["run"]()
    encoder = starts.processes[-1]
    assert encoder.returncode is not None and encoder.returncode < 0, "killed, not left to finish"
    starts.after_cancel = []  # the encoder was started before the latch, by construction
    _assert_cancelled_cleanly(mac_folder, result)


@needs_ffmpeg
def test_cancel_after_the_encode_before_publication(mac_folder, monkeypatch):
    _arm(monkeypatch, disk_assembly, "encode_mp3", after=mac_folder["starts"].cancel)
    _assert_cancelled_cleanly(mac_folder, mac_folder["run"]())


@needs_ffmpeg
def test_cancel_during_the_low_memory_retry(mac_folder, monkeypatch):
    attempts = []

    def out_of_memory(*_args, **_kwargs):
        attempts.append(1)
        raise MemoryError("the disk route ran out")

    monkeypatch.setattr(disk_assembly, "encode_mp3", out_of_memory)
    real_wait = wl.AssemblyPlace.wait_for_room

    def wait(self, stop=None):
        mac_folder["starts"].cancel()  # during the wait before the second attempt
        return real_wait(self, stop)

    monkeypatch.setattr(wl.AssemblyPlace, "wait_for_room", wait)
    _assert_cancelled_cleanly(mac_folder, mac_folder["run"]())
    assert attempts == [1], "no second attempt after the Cancel"


@needs_ffmpeg
def test_after_a_cancel_the_next_run_succeeds(mac_folder, monkeypatch, tmp_path):
    _arm(monkeypatch, disk_assembly.WavSpool, "append_file", after=mac_folder["starts"].cancel)
    _assert_cancelled_cleanly(mac_folder, mac_folder["run"]())
    monkeypatch.undo()  # a fresh run, nothing stood in for but the service
    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", False)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", mac_folder["gate"])
    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3",
                        lambda text, path, voice, rate: Path(path).write_bytes(clip_for(text, seconds=20)))
    monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)
    controller = JobController("p5h-r1-again")
    controller.start()
    destination = mac_folder["destination"]
    status, _path, error = batch_convert.convert_single_pdf(
        tmp_path / "in" / "book.txt", destination.parent, "v", "+0%", lambda _m: None, out_mp3=destination, bitrate="192k",
        cancel_check=controller.cancel_check, overwrite=True)
    assert status == "success", error
    publication.verify_finished_mp3(destination)
    assert mac_folder["gate"]._in_use == 0 and not ffmpeg_watch._watched


@needs_ffmpeg
def test_on_the_direct_route_cancel_before_the_final_encode_starts_no_encoder(tmp_path, monkeypatch, plenty):
    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", False)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    monkeypatch.setattr(engine, "run_edgespeak", lambda text, speaker, path: Path(path).write_bytes(clip_for(text)))
    controller = JobController("p5h-r1-direct")
    controller.start()
    starts = Starts(monkeypatch, controller)
    _arm(monkeypatch, publication, "require_audible", before=starts.cancel)
    source = tmp_path / "in" / "book.txt"
    source.parent.mkdir()
    source.write_text(HEAD + "# One\n\nA first paragraph. It ends.\n# Two\n\nA second one.\n", encoding="utf-8")
    with pytest.raises(ConversionCancelled):
        runner.run_conversion_job(str(source), output_dir=str(tmp_path / "out"), audio_format="mp3", speaker="v",
                                  mp3_bitrate="192k", cancel_check=controller.cancel_check)
    assert starts.after_cancel == []
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").rglob("*.mp3"))
    assert plenty._in_use == 0 and not ffmpeg_watch._watched and controller.commits_in_flight == 0


# --------------------------------------------------------------------------- E. Supervised itself


def _sleeper() -> list[str]:
    return [sys.executable, "-c", "import time; time.sleep(60)"]


def test_a_cancelled_run_starts_no_process_and_makes_no_file_for_one(monkeypatch):
    controller = JobController("p5h-r1-refused")
    controller.start()
    controller.request_cancel()
    started, files = [], []
    monkeypatch.setattr(subprocess_utils, "popen", lambda *a, **k: started.append(a))
    monkeypatch.setattr(ffmpeg_watch.tempfile, "TemporaryFile", lambda *a, **k: files.append(1))
    with ffmpeg_watch.controlled(controller.cancel_check):
        with pytest.raises(ConversionCancelled):
            ffmpeg_watch.Supervised(_sleeper(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert started == [] and files == [] and controller.commits_in_flight == 0 and not ffmpeg_watch._watched


def test_a_cancel_landing_while_the_process_starts_kills_it_at_once(monkeypatch):
    controller = JobController("p5h-r1-raced")
    controller.start()
    real = subprocess_utils.popen

    def popen(args, **kwargs):
        process = real(args, **kwargs)
        assert controller.commits_in_flight == 1, "the start holds the latch's authorization while it happens"
        controller.request_cancel()  # it lost to this start: the start must still be stopped
        return process

    monkeypatch.setattr(subprocess_utils, "popen", popen)
    monkeypatch.setattr(ffmpeg_watch, "_wake", type("Asleep", (), {"set": lambda self: None, "wait": lambda self, t=None: None,
                                                                    "clear": lambda self: None})())
    with ffmpeg_watch.controlled(controller.cancel_check):
        child = ffmpeg_watch.Supervised(_sleeper(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            # Killed by the start itself, with the watchdog asleep: not at its next look.
            assert child.process.wait(5) < 0
            with pytest.raises(ConversionCancelled):
                child.finish()
        finally:
            child.abandon()
    assert controller.commits_in_flight == 0 and not ffmpeg_watch._watched


def test_a_process_that_will_not_end_is_not_reported_as_a_clean_end(monkeypatch):
    monkeypatch.setattr(ffmpeg_watch, "ABANDON_WAIT_SECONDS", 0.2)
    child = ffmpeg_watch.Supervised(_sleeper(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    real_kill = child.process.kill
    monkeypatch.setattr(child.process, "kill", lambda: None)  # as if the kill had not taken
    try:
        with pytest.raises(ffmpeg_watch.ProcessNotStopped):
            child.abandon()
        assert child._item in ffmpeg_watch._watched, "still watched, not forgotten"
    finally:
        real_kill()
        child.process.wait(10)
        child._stop_watching()
    assert not ffmpeg_watch._watched


@pytest.mark.parametrize("predicate", [lambda: True, "event"], ids=["lambda", "event"])
def test_a_bare_cancel_check_already_set_refuses_the_start_too(monkeypatch, predicate):
    """No latch to be ordered against, but a last look: what was a start killed at the watchdog's first look is now no start."""
    if predicate == "event":
        import threading

        pressed = threading.Event()
        pressed.set()
        predicate = pressed.is_set
    started = []
    monkeypatch.setattr(subprocess_utils, "popen", lambda *a, **k: started.append(a))
    with ffmpeg_watch.controlled(predicate):
        with pytest.raises(ConversionCancelled):
            ffmpeg_watch.Supervised(_sleeper(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert started == [] and not ffmpeg_watch._watched


def test_a_cancel_check_that_fails_does_not_refuse_the_start(monkeypatch):
    """As the watchdog reads it: a check that raises is not a Cancel (``test_low_memory`` has the stall it then meets)."""
    def broken():
        raise OSError("gone")

    with ffmpeg_watch.controlled(broken):
        child = ffmpeg_watch.Supervised(_sleeper(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        assert child.process.poll() is None
    finally:
        child.abandon()
    assert not ffmpeg_watch._watched
