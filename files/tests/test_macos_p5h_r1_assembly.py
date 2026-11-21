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
#: C1, Cancel acknowledgment: about one second (owner decision 2026-11-20; was 0.5 s).
C1_ACK_S = 1.0

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


@needs_ffmpeg
def test_the_room_needed_follows_the_join_and_does_not_refuse_one_that_fits(tmp_path, monkeypatch):
    """Codex re-review: 10 s at 24 kHz then 50 ms at 11,025 Hz needs no rewrite and decodes to about 482 kB; with 962 kB
    free the earlier estimate (2 x every part at the largest format) refused it. Now the estimate follows the join."""
    ffmpeg_utils.configure_pydub()
    speech, silence = tmp_path / "speech.flac", tmp_path / "silence.flac"
    _tone(24000, 1, 10_000, 300).export(speech, format="flac")
    AudioSegment.silent(duration=50).export(silence, format="flac")
    need = disk_assembly._room_needed([speech, silence])
    assert need == pytest.approx(10.05 * 24000 * 2, rel=0.001)
    monkeypatch.setattr(disk_assembly.shutil, "disk_usage", lambda _p: type("U", (), {"free": 962_204})())
    disk_assembly.join_to_flac([speech, silence], tmp_path / "out.flac", tmp_path / "spool.wav")
    assert (tmp_path / "out.flac").exists()


@needs_ffmpeg
def test_the_room_needed_counts_what_is_held_twice_while_it_is_converted(tmp_path):
    ffmpeg_utils.configure_pydub()
    low, high = tmp_path / "low.flac", tmp_path / "high.flac"
    _tone(11025, 1, 10_000, 300).export(low, format="flac")
    _tone(24000, 1, 1_000, 300).export(high, format="flac")
    held, converted, final = 10 * 11025 * 2, 10 * 24000 * 2, 11 * 24000 * 2
    assert disk_assembly._room_needed([low, high]) == pytest.approx(max(held + converted, final), rel=0.001)
    assert disk_assembly._room_needed([high, high]) == wl.decoded_size([high, high]), "one format: exactly as before"
    pause = AudioSegment.silent(duration=50)  # the folder route's pause, at 11,025 Hz, between 24 kHz chunks
    assert disk_assembly._room_needed([high, pause, high]) == wl.decoded_size([high, high]), "as before"


@needs_ffmpeg
def test_cancel_during_the_final_tail_scan_stops_it_at_the_next_block(tmp_path, monkeypatch):
    """Codex re-review: the tail policy scanned a long silent ending to its start after a Cancel."""
    import threading

    from tts import audio_tail

    monkeypatch.setattr(audio_tail, "_SCAN_BLOCK_WINDOWS", 10)  # 100 ms blocks: a 20 s silence is 200 of them
    looks = {"n": 0}
    pressed = threading.Event()
    real = ffmpeg_watch.checkpoint

    def counted():
        looks["n"] += 1
        if looks["n"] == 2:
            pressed.set()  # Cancel once the scan has read its first block (the first look is before the scan)
        real()

    with disk_assembly.WavSpool(tmp_path / "spool.wav") as spool:
        spool.append_segment(AudioSegment.silent(duration=20_000, frame_rate=24000))
        spool.finish()
        with ffmpeg_watch.controlled(pressed.is_set):
            monkeypatch.setattr(ffmpeg_watch, "checkpoint", counted)
            with pytest.raises(ConversionCancelled):
                spool.apply_final_tail()
    assert looks["n"] == 2, f"{looks['n'] - 2} blocks looked at after the Cancel"


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
def test_cancel_pressed_while_the_encoder_is_being_created_never_follows_it(mac_folder, monkeypatch):
    """The reviewer's ``folder_launch_race``: Cancel pressed on another thread at the instant before the real encoder is
    created. At 94e200f the latch went through and the encoder was created after it; now the Cancel waits for the creation
    in progress, the encoder exists before the latch, and it is stopped at once."""
    import threading

    starts = mac_folder["starts"]
    real = subprocess_utils.popen
    pressing = {}

    def popen(args, **kwargs):
        if str(args[-1]).endswith(".part") and "pressing" not in pressing:
            pressing["thread"] = threading.Thread(target=starts.cancel)
            pressing["thread"].start()
            pressing["thread"].join(0.5)
            pressing["waited"] = pressing["thread"].is_alive()
        return real(args, **kwargs)

    # Outermost: the fixture's recorder (beneath this) looks at the latch only once the barrier has passed.
    monkeypatch.setattr(subprocess_utils, "popen", popen)
    result = mac_folder["run"]()
    pressing["thread"].join(5)
    assert pressing["waited"], "the Cancel waited for the creation in progress"
    _assert_cancelled_cleanly(mac_folder, result)


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
def test_cancel_during_the_encode_kills_it_at_once(mac_folder, monkeypatch):
    """Cancel once the encoder is running (its start has finished, so the latch is free): the watchdog kills it at its
    next look, which ``wake`` makes now. (A Cancel pressed while the encoder is being created waits for that creation:
    ``test_cancel_pressed_while_the_encoder_is_being_created_never_follows_it``.)"""
    starts = mac_folder["starts"]
    real = ffmpeg_watch.Supervised.communicate
    pressed = []

    def communicate(self, *args, **kwargs):
        if str(self.args[-1]).endswith(".part") and not pressed:
            pressed.append(self.process)
            starts.cancel()
        return real(self, *args, **kwargs)

    monkeypatch.setattr(ffmpeg_watch.Supervised, "communicate", communicate)
    result = mac_folder["run"]()
    assert pressed, "the encoder ran"
    assert _was_killed(pressed[0].returncode), "killed, not left to finish"
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


def _was_killed(returncode) -> bool:
    """A process that was stopped rather than left to finish: on POSIX a signal (a negative status); on Windows
    TerminateProcess's own non-zero exit code (a process left to finish exits 0)."""
    if returncode is None:
        return False
    return returncode < 0 if os.name == "posix" else returncode != 0


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


def test_a_cancel_pressed_while_a_process_is_being_created_waits_for_it_and_then_stops_it(monkeypatch):
    """Codex re-review (HIGH): the start's authorization let go of the latch's lock before ``popen``, so a Cancel pressed
    between them latched first and the process was created after it. Now Cancel waits for the creation in progress (it
    holds the start lock for the spawn and registration only) and then finds the process to stop: at the moment of
    creation the run was not cancelled, and once the latch is set the process is stopped at once."""
    import threading

    controller = JobController("p5h-r1-raced")
    controller.start()
    real = subprocess_utils.popen
    seen = {}

    def popen(args, **kwargs):
        pressing = threading.Thread(target=controller.request_cancel)
        pressing.start()  # Cancel pressed at the last instant before the process exists
        pressing.join(0.5)
        seen["cancel_waited"] = pressing.is_alive()
        seen["latched_at_creation"] = controller.cancel_check()
        process = real(args, **kwargs)
        seen["pressing"] = pressing
        return process

    monkeypatch.setattr(subprocess_utils, "popen", popen)
    with ffmpeg_watch.controlled(controller.cancel_check):
        child = ffmpeg_watch.Supervised(_sleeper(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        seen["pressing"].join(5)
        try:
            assert seen == {"cancel_waited": True, "latched_at_creation": False, "pressing": seen["pressing"]}
            assert not seen["pressing"].is_alive() and controller.cancel_check(), "the Cancel then went through"
            ffmpeg_watch.wake()
            assert _was_killed(child.process.wait(5)), "and the process it waited for is stopped"
            with pytest.raises(ConversionCancelled):
                child.finish()
        finally:
            child.abandon()
    assert controller.commits_in_flight == 0 and not ffmpeg_watch._watched


@needs_ffmpeg
def test_a_cancel_check_is_never_kept_waiting_by_a_guardian_start(real_owner, monkeypatch):
    """What can be slow before a start (macOS: the containment guardian) happens before the Cancel lock is taken.
    (v0.8.x P5-I-R3: the guardian is had by ``Owner._current_guardian``, outside the run's counted start.)"""
    controller = JobController("p5h-r1-guardian")
    controller.start()
    held_during_preparation = []
    real = real_owner._current_guardian

    def prepare(spawn_context=None, checkpoint=None, run=None):
        held_during_preparation.append(controller._starts_in_progress > 0)
        return real(spawn_context, checkpoint, run)

    monkeypatch.setattr(real_owner, "_current_guardian", prepare)
    with ffmpeg_watch.controlled(controller.cancel_check):
        child = ffmpeg_watch.Supervised(_ffmpeg_version(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        child.communicate()
        child.abandon()
    assert held_during_preparation == [False]


def test_a_process_whose_watch_cannot_be_made_is_never_started(monkeypatch):
    """P5-I: the watch is made before the process. A start whose watch cannot be made (out of memory, say) starts nothing,
    so there is no process to be left unwatched (until P5-H-R1 the process was started first and killed afterwards)."""
    started = []
    real = subprocess_utils.popen

    def popen(args, **kwargs):
        started.append(real(args, **kwargs))
        return started[-1]

    def no_memory(*_a, **_k):
        raise MemoryError()

    monkeypatch.setattr(subprocess_utils, "popen", popen)
    monkeypatch.setattr(ffmpeg_watch, "_Watched", no_memory)
    with pytest.raises(MemoryError):
        ffmpeg_watch.Supervised(_sleeper(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert started == [], "nothing was started"
    assert not ffmpeg_watch._watched


class _WakeThatFails:
    """``ffmpeg_watch._wake`` whose first ``set`` -- the last step of a start, after the process exists -- runs out of
    memory; the watchdog's own waits are served by the real event."""

    def __init__(self, real):
        self.real, self.failed = real, False

    def set(self):
        if not self.failed:
            self.failed = True
            raise MemoryError()
        self.real.set()

    def wait(self, timeout=None):
        return self.real.wait(timeout)

    def clear(self):
        self.real.clear()


def test_a_process_whose_start_fails_after_it_exists_is_ended_and_never_unwatched(monkeypatch):
    """P5-I (Codex re-review 5, HIGH 3): anything failing once the process exists leaves it watched; it is killed, waited
    for and only then forgotten."""
    started = []
    real = subprocess_utils.popen
    monkeypatch.setattr(subprocess_utils, "popen", lambda *a, **k: started.append(real(*a, **k)) or started[-1])
    monkeypatch.setattr(ffmpeg_watch, "_wake", _WakeThatFails(ffmpeg_watch._wake))
    with pytest.raises(MemoryError):
        ffmpeg_watch.Supervised(_sleeper(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert len(started) == 1 and started[0].returncode is not None, "killed and reaped"
    assert not ffmpeg_watch._watched


def test_a_process_whose_start_fails_after_it_exists_and_will_not_end_stays_watched_and_unconfirmed(monkeypatch):
    """The same with the kill ineffective: never dropped. It stays watched, is reported (``ProcessNotStopped``, and by the
    run's settlement), and the watchdog reaps and forgets it once the kill takes."""
    import time

    controller = JobController("p5i-unwatched-fault")
    controller.start()
    monkeypatch.setattr(ffmpeg_watch, "ABANDON_WAIT_SECONDS", 0.3)
    started = []
    real = subprocess_utils.popen
    kill_takes = {"value": False}
    real_kill = subprocess.Popen.kill

    def popen(*args, **kwargs):
        proc = real(*args, **kwargs)
        proc.kill = lambda: real_kill(proc) if kill_takes["value"] else None
        started.append(proc)
        return proc

    monkeypatch.setattr(subprocess_utils, "popen", popen)
    monkeypatch.setattr(ffmpeg_watch, "_wake", _WakeThatFails(ffmpeg_watch._wake))
    try:
        with ffmpeg_watch.controlled(controller.cancel_check):
            with pytest.raises(ffmpeg_watch.ProcessNotStopped):
                ffmpeg_watch.Supervised(_sleeper(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        proc = started[0]
        assert proc.poll() is None, "still running: the kill did not take"
        assert any(item.process is proc and item.unconfirmed for item in ffmpeg_watch._watched), "kept, not dropped"
        assert proc.pid in ffmpeg_watch.settle_children(controller.cancel_check), "the run's settlement sees it"
    finally:
        kill_takes["value"] = True
    deadline = time.monotonic() + 10
    while ffmpeg_watch._watched and time.monotonic() < deadline:
        ffmpeg_watch.wake()
        time.sleep(0.05)
    assert not ffmpeg_watch._watched and started[0].returncode is not None, "reaped and forgotten once the kill took"


@pytest.mark.parametrize("stage", ["wait", "read"])
def test_a_killed_process_that_will_not_end_never_holds_the_conversion(monkeypatch, stage):
    """Codex re-review: with the kill ineffective, ``finish`` (and a read of a silent pipe) waited for ever. Now each gives
    up :data:`ABANDON_WAIT_SECONDS` after the kill, the process stays watched, and the watchdog reaps and forgets it once it
    does end."""
    import time

    if stage == "read" and os.name != "posix":
        pytest.skip("Windows reads its pipes as before")
    monkeypatch.setattr(ffmpeg_watch, "ABANDON_WAIT_SECONDS", 0.5)
    child = ffmpeg_watch.Supervised(_sleeper(), stdout=subprocess.PIPE if stage == "read" else subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
    real_kill = child.process.kill
    monkeypatch.setattr(child.process, "kill", lambda: None)  # as if the kill had not taken
    child._item.decide(ConversionCancelled("Conversion cancelled by user."))  # what the watchdog does at a Cancel
    began = time.monotonic()
    try:
        with pytest.raises(ffmpeg_watch.ProcessNotStopped):
            if stage == "read":
                list(child.blocks())
            else:
                child.finish()
        assert time.monotonic() - began < 5
        assert child._item.unconfirmed and child._item in ffmpeg_watch._watched
        child.abandon()  # its caller's cleanup: no second wait, nothing hidden
        assert child._item in ffmpeg_watch._watched
    finally:
        real_kill()
    deadline = time.monotonic() + 10
    while child._item in ffmpeg_watch._watched and time.monotonic() < deadline:
        ffmpeg_watch.wake()
        time.sleep(0.05)
    assert child._item not in ffmpeg_watch._watched, "reaped and forgotten once it ended"
    assert child.process.returncode is not None


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
    assert child._item not in ffmpeg_watch._watched


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


def test_a_waiting_cancel_refuses_new_starts_and_latches_when_the_one_in_progress_ends():
    """The controller's side of the start ordering, with no process at all: one start in progress holds the latch back; a
    Cancel then waits for it without latching; a second start asked for meanwhile is refused (so starts cannot keep a Cancel
    waiting); the latch lands the moment the first start ends; and nothing is left counted."""
    import threading

    controller = JobController("p5h-r1-pending")
    controller.start()
    inside, release = threading.Event(), threading.Event()

    def first_start():
        with controller.starting():
            inside.set()
            release.wait(10)

    starter = threading.Thread(target=first_start)
    starter.start()
    assert inside.wait(5)
    pressing = threading.Thread(target=controller.request_cancel)
    pressing.start()
    pressing.join(0.3)
    assert pressing.is_alive() and not controller.cancel_check(), "waiting for the start in progress, not latched"
    with pytest.raises(ConversionCancelled):
        with controller.starting():
            pass  # pragma: no cover - refused
    release.set()
    starter.join(5)
    pressing.join(5)
    assert not pressing.is_alive() and controller.cancel_check()
    assert controller._starts_in_progress == 0 and controller.commits_in_flight == 0
    with pytest.raises(ConversionCancelled):
        with controller.starting():
            pass  # pragma: no cover - refused



# --------------------------------------------------------------------------- R1 round 3 (Codex re-review 2)


def _ffmpeg_version() -> list[str]:
    ffmpeg_utils.configure_pydub()
    return [AudioSegment.converter, "-hide_banner", "-version"]


@pytest.fixture()
def real_owner(monkeypatch):
    """A real containment owner (macOS): FFmpeg is started in its guardian's group, as in the app window."""
    if sys.platform != "darwin":
        pytest.skip("containment is the Mac's")
    from shared import child_ownership

    owner = child_ownership.Owner(lifeline=False)
    monkeypatch.setattr(subprocess_utils, "_owner", owner)
    yield owner
    owner.shutdown()


@needs_ffmpeg
def test_a_cancelled_run_makes_no_guardian_and_no_ffmpeg(real_owner):
    """Codex re-review 2: with no guardian yet, a run already cancelled created one before its FFmpeg was refused."""
    controller = JobController("p5h-r1-cold")
    controller.start()
    controller.request_cancel()
    with ffmpeg_watch.controlled(controller.cancel_check):
        with pytest.raises(ConversionCancelled):
            ffmpeg_watch.Supervised(_ffmpeg_version(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert real_owner.guardian_pid() is None and not ffmpeg_watch._watched


@needs_ffmpeg
def test_a_guardian_replaced_after_preparation_is_never_restarted_inside_the_start(real_owner, monkeypatch):
    """Codex re-review 2 (HIGH): a guardian that died between preparation and the start was replaced inside the counted
    start, so a Cancel waited for the new guardian to be ready (0.662 s, past C1). Now the start fails at once (the
    guardian it was prepared for is gone), and preparation, outside the start, replaces it."""
    from shared import child_ownership

    controller = JobController("p5h-r1-guardian-lost")
    controller.start()
    starts_counted_during_guardian_start = []
    real_start = child_ownership.Owner._start_guardian

    def start_guardian(self, spawn_context=None, checkpoint=None):
        starts_counted_during_guardian_start.append(controller._starts_in_progress)
        return real_start(self, spawn_context, *(() if checkpoint is None else (checkpoint,)))

    monkeypatch.setattr(child_ownership.Owner, "_start_guardian", start_guardian)
    real_prepare = real_owner._current_guardian  # P5-I-R3: what prepares a start (outside its counted start)
    prepared = []

    def prepare_then_lose_the_guardian(spawn_context=None, checkpoint=None, run=None):
        pid, generation = real_prepare(spawn_context, checkpoint, run)
        if not prepared:  # the first time only: the guardian dies just after the start was prepared for it
            guardian = real_owner._guardian
            guardian.kill()
            guardian.wait(5)
        prepared.append(generation)
        return pid, generation

    monkeypatch.setattr(real_owner, "_current_guardian", prepare_then_lose_the_guardian)
    with ffmpeg_watch.controlled(controller.cancel_check):
        child = ffmpeg_watch.Supervised(_ffmpeg_version(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        child.communicate()
    assert len(prepared) == 2 and prepared[1] > prepared[0], "prepared again, for a new guardian"
    assert starts_counted_during_guardian_start == [0, 0], "no guardian was ever started inside a counted start"
    assert child.returncode == 0 and controller._starts_in_progress == 0


@needs_ffmpeg
def test_a_cancel_never_waits_for_a_guardian_to_become_ready(real_owner, monkeypatch):
    """The guardian's spawn is ordered against Cancel; its readiness is not. A Cancel pressed while a new guardian is
    getting ready latches at once (well inside C1's 0.5 s), and the FFmpeg it was being readied for never starts."""
    import contextlib
    import threading
    import time

    from shared import child_ownership

    controller = JobController("p5h-r1-slow-guardian")
    controller.start()
    spawned, may_be_ready = threading.Event(), threading.Event()
    real_ready = child_ownership.Owner._await_ready
    assert contextlib  # (imported for the earlier form of this hold)

    def slow_readiness(self, proc, checkpoint):
        # v0.8.x P5-I: only a guardian's admission is in the ordering now, so "getting ready" is held where it happens.
        spawned.set()  # spawned, the counted start let go: now the long wait for "ready"
        may_be_ready.wait(5)
        return real_ready(self, proc, checkpoint)

    monkeypatch.setattr(child_ownership.Owner, "_await_ready", slow_readiness)
    outcome = {}

    def starting():
        with ffmpeg_watch.controlled(controller.cancel_check):
            try:
                ffmpeg_watch.Supervised(_ffmpeg_version(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                outcome["started"] = True
            except ConversionCancelled:
                outcome["refused"] = True

    worker = threading.Thread(target=starting)
    worker.start()
    assert spawned.wait(10)
    began = time.monotonic()
    controller.request_cancel()
    latched_in = time.monotonic() - began
    may_be_ready.set()
    worker.join(15)
    assert latched_in < C1_ACK_S and controller.cancel_check(), latched_in
    assert outcome == {"refused": True}, outcome
    assert not ffmpeg_watch._watched, "no FFmpeg was started for it"


@needs_ffmpeg
def test_a_start_is_never_held_by_another_threads_guardian_getting_ready(real_owner, monkeypatch):
    """Codex re-review 3 (partial run): worker A prepared its FFmpeg for the guardian, the guardian died, and worker B
    began replacing it. B's wait for the new guardian to be ready held the owner's lock, so A -- inside its counted start
    -- waited on that lock and a Cancel latched only after B's guardian was ready (0.69 s, past C1's 0.5 s). Now the
    readiness wait holds a lock of its own: A's start fails at once (its guardian is gone), A waits for B's guardian
    outside the start, and the Cancel latches at once; A's FFmpeg is never started."""
    import contextlib
    import threading
    import time

    from shared import child_ownership

    controller = JobController("p5h-r1-concurrent-guardian")
    controller.start()
    real_owner.ensure_guardian()
    a_prepared, a_go, a_attempting = threading.Event(), threading.Event(), threading.Event()
    b_getting_ready, b_may_be_ready = threading.Event(), threading.Event()
    real_prepare, real_admit = real_owner._current_guardian, real_owner._grant  # P5-I-R3: preparation; counted start
    real_start = child_ownership.Owner._start_guardian

    def prepare(spawn_context=None, checkpoint=None, run=None):
        if _caller() == "A" and a_prepared.is_set():
            a_attempting.set()  # P5-I-R3: A's start, refused for the lost guardian, has its guardian again (outside)
        answer = real_prepare(spawn_context, checkpoint, run)
        if _caller() == "A" and not a_prepared.is_set():
            a_prepared.set()
            assert a_go.wait(10)
        return answer

    def admit(launch):
        if _caller() == "A":
            a_attempting.set()  # inside A's counted start (P5-I: the admission is what it holds)
        return real_admit(launch)

    real_ready = child_ownership.Owner._await_ready
    assert real_start and contextlib  # (the earlier form held the spawn's ordering)

    def start_guardian(self, proc, checkpoint):
        if _caller() == "B":
            # v0.8.x P5-I: only a guardian's admission is in the ordering now, so "getting ready" is held where it happens.
            b_getting_ready.set()
            assert b_may_be_ready.wait(10)
        return real_ready(self, proc, checkpoint)

    monkeypatch.setattr(real_owner, "_current_guardian", prepare)
    monkeypatch.setattr(real_owner, "_grant", admit)
    monkeypatch.setattr(child_ownership.Owner, "_await_ready", start_guardian)
    outcome = {}

    def worker_a():
        with ffmpeg_watch.controlled(controller.cancel_check):
            try:
                ffmpeg_watch.Supervised(_ffmpeg_version(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                outcome["started"] = True
            except ConversionCancelled:
                outcome["refused"] = True
            except BaseException as exc:  # pragma: no cover - reported below
                outcome["error"] = exc

    a = threading.Thread(target=worker_a, name="A", daemon=True)
    a.start()
    assert a_prepared.wait(10)
    guardian = real_owner._guardian
    guardian.kill()
    guardian.wait(5)
    b = threading.Thread(target=real_owner.ensure_guardian, name="B", daemon=True)
    b.start()
    assert b_getting_ready.wait(10)
    a_go.set()
    assert a_attempting.wait(10)
    pressing = threading.Thread(target=controller.request_cancel, daemon=True)
    began = time.monotonic()
    pressing.start()
    pressing.join(0.5)
    latched_in = time.monotonic() - began
    latched = controller.cancel_check()
    b_may_be_ready.set()
    pressing.join(10)
    a.join(15)
    b.join(15)
    assert latched and latched_in < C1_ACK_S, f"Cancel waited {latched_in:.3f} s for another thread's guardian"
    assert outcome == {"refused": True}, outcome
    assert not ffmpeg_watch._watched and controller._starts_in_progress == 0


def test_a_guardian_that_gets_ready_after_the_orderly_end_began_is_not_kept(real_owner, monkeypatch):
    """The guardian's wait to be ready no longer holds the owner's lock, so the orderly end can begin during it: the
    guardian is then ended and reaped, never adopted after the end has looked, and nothing is started."""
    import contextlib
    import threading

    from shared import child_ownership

    getting_ready, may_be_ready = threading.Event(), threading.Event()
    made = []
    real_popen = child_ownership.subprocess.Popen
    real_start = child_ownership.Owner._start_guardian

    def popen(*args, **kwargs):
        made.append(real_popen(*args, **kwargs))
        return made[-1]

    real_ready = child_ownership.Owner._await_ready
    assert real_start and contextlib  # (the earlier form held the spawn's ordering)

    def start_guardian(self, proc, checkpoint):
        # v0.8.x P5-I: only a guardian's admission is in the ordering now, so "getting ready" is held where it happens.
        getting_ready.set()
        assert may_be_ready.wait(10)
        return real_ready(self, proc, checkpoint)

    monkeypatch.setattr(child_ownership.subprocess, "Popen", popen)
    monkeypatch.setattr(child_ownership.Owner, "_await_ready", start_guardian)
    outcome = {}

    def ensure():
        try:
            outcome["generation"] = real_owner.ensure_guardian()
        except child_ownership.ContainmentUnavailable as exc:
            outcome["refused"] = str(exc)

    t = threading.Thread(target=ensure, daemon=True)
    t.start()
    assert getting_ready.wait(10)
    real_owner.begin_closing()
    may_be_ready.set()
    t.join(15)
    assert "closing" in outcome.get("refused", ""), outcome
    assert len(made) == 1 and made[0].returncode is not None, "the guardian was ended and reaped"
    assert real_owner.guardian_pid() is None


@needs_ffmpeg
def test_an_unprepared_start_has_the_new_guardian_when_its_own_is_replaced(real_owner, monkeypatch):
    """``popen_external`` without a prepared generation has its guardian outside the owner's lock and then starts the
    child in that guardian's group; a guardian replaced in between is had again (bounded), never started under the lock."""
    from shared import child_ownership

    first = real_owner.ensure_guardian()
    real_ensure = real_owner._current_guardian  # P5-I-R3: how popen_external has its guardian
    calls = []

    def ensure_then_lose_it(spawn_context=None, checkpoint=None, run=None):
        pid, generation = real_ensure(spawn_context, checkpoint, run)
        calls.append(generation)
        if len(calls) == 1:  # the guardian dies just after it was had for this start
            guardian = real_owner._guardian
            guardian.kill()
            guardian.wait(5)
        return pid, generation

    monkeypatch.setattr(real_owner, "_current_guardian", ensure_then_lose_it)
    proc = real_owner.popen_external(_ffmpeg_version(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.wait(10)
    real_owner.forget(proc)
    assert calls[0] == first and len(calls) == 2 and calls[1] > first, calls
    assert proc.returncode == 0

    def changed(*_a, **_k):
        raise child_ownership.GuardianChanged("injected: never the current one")

    monkeypatch.setattr(real_owner, "_admit", changed)
    with pytest.raises(child_ownership.ContainmentUnavailable, match="contained way"):
        real_owner.popen_external(_ffmpeg_version(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@needs_ffmpeg
def test_a_contained_ffmpeg_that_cannot_be_registered_is_ended(real_owner, monkeypatch):
    from shared import child_ownership

    created = []
    real_popen = child_ownership.subprocess.Popen

    def popen(*args, **kwargs):
        created.append(real_popen(*args, **kwargs))
        return created[-1]

    real_owner.ensure_guardian()  # the guardian first, unrecorded below
    monkeypatch.setattr(child_ownership.subprocess, "Popen", popen)
    monkeypatch.setattr(real_owner, "_register", lambda *a, **k: (_ for _ in ()).throw(MemoryError()))
    with pytest.raises(MemoryError):
        ffmpeg_watch.Supervised(_ffmpeg_version() + ["-loglevel", "quiet"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    assert len(created) == 1 and created[0].poll() is not None, "killed and reaped, not left outside both registries"
    assert not ffmpeg_watch._watched


@needs_ffmpeg
def test_a_pipe_numbered_past_selects_limit_is_read(tmp_path):
    """Codex re-review 2: ``select()`` refused a descriptor above 1023; a busy app's FFmpeg pipe can be one."""
    if os.name != "posix":
        pytest.skip("POSIX reads")
    import resource  # POSIX only: the check above comes first so Windows collects and skips

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    want = 1200
    if hard != resource.RLIM_INFINITY and hard < want:
        pytest.skip("cannot raise the descriptor limit here")
    resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, want), hard))
    held = []
    try:
        while True:
            fd = os.open(os.devnull, os.O_RDONLY)
            held.append(fd)
            if fd >= 1100:
                break
        child = ffmpeg_watch.Supervised(_ffmpeg_version(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert child.stdout.fileno() > 1024
        output, _errors = child.communicate()
        assert b"ffmpeg version" in output
    finally:
        for fd in held:
            os.close(fd)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def test_the_wav_header_read_is_held_to_the_kill_deadline(monkeypatch):
    """Codex re-review 2: the header was read straight from the pipe, past the bound the audio read keeps."""
    import time

    if os.name != "posix":
        pytest.skip("POSIX reads")
    monkeypatch.setattr(ffmpeg_watch, "ABANDON_WAIT_SECONDS", 0.5)
    child = ffmpeg_watch.Supervised(_sleeper(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    real_kill = child.process.kill
    monkeypatch.setattr(child.process, "kill", lambda: None)
    child._item.decide(ConversionCancelled("Conversion cancelled by user."))
    began = time.monotonic()
    try:
        with pytest.raises(ffmpeg_watch.ProcessNotStopped):
            disk_assembly._wav_format(child)
        assert time.monotonic() - began < 5
    finally:
        real_kill()
        child.process.wait(10)
        child._stop_watching()


@needs_ffmpeg
def test_the_free_space_reads_stop_at_cancel_for_parts_in_one_format(tmp_path, monkeypatch):
    """Codex re-review 2: for parts in one format, every header was read a second time, unchecked, after the first walk;
    a Cancel during the first walk's last read was followed by that whole second walk. Now there is one walk."""
    import threading

    ffmpeg_utils.configure_pydub()
    parts = []
    for index in range(4):
        parts.append(tmp_path / f"p{index}.flac")
        _tone(24000, 1, 300, 300 + index).export(parts[-1], format="flac")
    pressed = threading.Event()
    opened = []
    real_size, real_facts = wl.decoded_size, disk_assembly._header_facts

    def facts(path):
        opened.append(("facts", path.name, pressed.is_set()))
        if path == parts[-1]:
            pressed.set()  # Cancel while the last header is read
        return real_facts(path)

    monkeypatch.setattr(wl, "decoded_size",
                        lambda paths: (opened.append(("size", len(list(paths)), pressed.is_set())), real_size(paths))[1])
    monkeypatch.setattr(disk_assembly, "_header_facts", facts)
    with ffmpeg_watch.controlled(pressed.is_set):
        try:
            disk_assembly._room_needed(parts)
        except ConversionCancelled:
            pass
    assert [entry for entry in opened if entry[-1]] == [], f"read after the Cancel: {opened}"


def test_a_file_whose_ffmpeg_will_not_end_fails_and_is_neither_retried_nor_cancelled(tmp_path, monkeypatch):
    """Codex re-review 2 (HIGH): the folder route turned ProcessNotStopped into a Cancel at its retry back-off."""
    tries = []

    def unstoppable(*_a, **_k):
        tries.append(1)
        raise ffmpeg_watch.ProcessNotStopped("FFmpeg (process 1) was stopped and had not ended")

    monkeypatch.setattr(wl, "assemble", unstoppable)
    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3",
                        lambda text, path, voice, rate: Path(path).write_bytes(b"x"))
    monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)
    source = tmp_path / "book.txt"
    source.write_text("One sentence to say.", encoding="utf-8")
    pressed = __import__("threading").Event()
    status, _path, error = batch_convert.convert_single_pdf(source, tmp_path, "v", "+0%", lambda _m: None,
                                                            out_mp3=tmp_path / "book.mp3", cancel_check=pressed.is_set)
    assert (status, tries) == ("failed", [1]) and "had not ended" in error


# --------------------------------------------------------------------------- R1 round 5 (Codex re-review 4)


def _guardian_spawns(monkeypatch, *, stop=False):
    """Record (and, with ``stop``, SIGSTOP at once) each guardian process the owner spawns."""
    import signal

    from shared import child_ownership

    made = []
    real_popen = child_ownership.subprocess.Popen

    def popen(cmd, *args, **kwargs):
        proc = real_popen(cmd, *args, **kwargs)
        if str(child_ownership.GUARDIAN) in [str(part) for part in cmd]:
            if stop:
                os.kill(proc.pid, signal.SIGSTOP)  # stalled before it can say "ready"
            made.append(proc)
        return proc

    monkeypatch.setattr(child_ownership.subprocess, "Popen", popen)
    return made


def _end_guardians(made):
    import signal

    for proc in made:
        if proc.poll() is None:
            with __import__("contextlib").suppress(OSError):
                os.kill(proc.pid, signal.SIGCONT)
                proc.kill()
            proc.wait(5)


def _quietly(call):
    """Run ``call`` on a thread whose own failure (a guardian ended under it, the app closing) is not the test's."""
    try:
        call()
    except Exception:  # noqa: BLE001
        pass


def _caller() -> str:
    """The thread a start was asked from (v0.8.x P5-I-R3: a contained start runs on ``act-launch:<caller>``)."""
    import threading

    return threading.current_thread().name.removeprefix("act-launch:")


def _wait_for(predicate, seconds=10.0):
    import time

    stop = time.monotonic() + seconds
    while time.monotonic() < stop:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@needs_ffmpeg
def test_a_lost_guardians_children_are_ended_without_holding_up_a_start_or_a_cancel(real_owner, monkeypatch):
    """Codex re-review 4 (HIGH): worker B, replacing a lost guardian, ended that guardian's surviving child (one that
    ignores SIGTERM: a 1 s grace) holding the owner's lock; worker A, inside its counted start, waited on that lock, and
    a Cancel latched after 1.03 s (C1 is 0.5 s). The child is now ended after the lock is let go.

    P5-I (Codex re-review 5, HIGH 1): whoever notices the loss only records it -- the child is marked and handed to the
    owner's retirement under one shared deadline -- and goes on at once; B's ensure_guardian no longer ends anything."""
    import signal
    import threading
    import time

    from shared import child_ownership

    monkeypatch.setattr(child_ownership.Owner, "_watch_guardian", lambda self, proc, generation: None)  # B sees it first
    controller = JobController("p5h-r1-orphans")
    controller.start()
    real_owner.ensure_guardian()
    orphan = real_owner.popen_external(
        [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ok', flush=True);"
                               " time.sleep(30)"], stdout=subprocess.PIPE, label="orphan")
    assert orphan.stdout.readline().strip() == b"ok"
    a_prepared, a_go, a_attempting, b_ending = (threading.Event() for _ in range(4))
    real_prepare, real_admit = real_owner._current_guardian, real_owner._grant  # P5-I-R3: preparation; counted start
    real_lost = real_owner._guardian_lost

    def prepare(spawn_context=None, checkpoint=None, run=None):
        if _caller() == "A" and a_prepared.is_set():
            a_attempting.set()  # P5-I-R3: A's start, refused for the lost guardian, has its guardian again (outside)
        answer = real_prepare(spawn_context, checkpoint, run)
        if _caller() == "A" and not a_prepared.is_set():
            a_prepared.set()
            assert a_go.wait(10)
        return answer

    def admit(launch):
        if _caller() == "A":
            a_attempting.set()  # P5-I: the admission is what A's counted start holds now
        return real_admit(launch)

    def lost(proc, generation):
        real_lost(proc, generation)
        if _caller() == "B":
            b_ending.set()  # B recorded the loss; the orphan is now being retired (SIGTERM, a 1 s grace, SIGKILL)

    monkeypatch.setattr(real_owner, "_current_guardian", prepare)
    monkeypatch.setattr(real_owner, "_grant", admit)
    monkeypatch.setattr(real_owner, "_guardian_lost", lost)
    outcome = {}

    def worker_a():
        with ffmpeg_watch.controlled(controller.cancel_check):
            try:
                child = ffmpeg_watch.Supervised(_ffmpeg_version(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                outcome["started"] = True
                try:
                    child.finish()
                except ConversionCancelled:
                    outcome["stopped"] = True
                finally:
                    child.abandon()
            except ConversionCancelled:
                outcome["refused"] = True
            except BaseException as exc:  # pragma: no cover - reported below
                outcome["error"] = exc

    a = threading.Thread(target=worker_a, name="A", daemon=True)
    a.start()
    assert a_prepared.wait(10)
    guardian = real_owner._guardian
    guardian.kill()
    guardian.wait(5)
    b = threading.Thread(target=real_owner.ensure_guardian, name="B", daemon=True)
    b.start()
    assert b_ending.wait(10)
    a_go.set()
    assert a_attempting.wait(10)
    pressing = threading.Thread(target=controller.request_cancel, daemon=True)
    began = time.monotonic()
    pressing.start()
    pressing.join(0.5)
    latched_in, latched = time.monotonic() - began, controller.cancel_check()
    pressing.join(10)
    a.join(15)
    b.join(15)
    assert latched and latched_in < C1_ACK_S, f"Cancel waited {latched_in:.3f} s for a lost guardian's child to be ended"
    # P5-I: A's start, admitted before the latch, is either refused at its last look before the spawn or -- the latch landing
    # during the spawn itself -- created and stopped at once; which one is a race of microseconds, and both are correct.
    assert outcome in ({"refused": True}, {"started": True, "stopped": True}), outcome
    assert ffmpeg_watch.settle_children(controller.cancel_check) == [], "nothing of the run is left unconfirmed"
    assert _wait_for(lambda: orphan.poll() is not None, 5), "the lost guardian's child was ended"
    assert orphan.returncode == -signal.SIGKILL, "it ignored SIGTERM: SIGKILL at the end of the shared grace"
    assert not ffmpeg_watch._watched and controller._starts_in_progress == 0


@needs_ffmpeg
def test_a_cancel_stops_the_wait_for_a_guardian_that_never_gets_ready(real_owner, monkeypatch):
    """Codex re-review 4 (HIGH): a guardian stalled before it said "ready" kept a cancelled conversion waiting up to the
    readiness time-out (10 s; still running at 4.15 s, past C2's 4 s). The wait now looks at Cancel: the conversion
    stops at once, and the guardian it was waiting for is ended and reaped, never adopted."""
    import threading
    import time

    made = _guardian_spawns(monkeypatch, stop=True)
    controller = JobController("p5h-r1-stalled-guardian")
    controller.start()
    outcome, ended = {}, threading.Event()

    def worker():
        with ffmpeg_watch.controlled(controller.cancel_check):
            try:
                ffmpeg_watch.Supervised(_ffmpeg_version(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                outcome["started"] = True
            except ConversionCancelled:
                outcome["refused"] = True
            except BaseException as exc:  # pragma: no cover - reported below
                outcome["error"] = exc
        ended.set()

    t = threading.Thread(target=worker, daemon=True)
    try:
        t.start()
        assert _wait_for(lambda: made)
        time.sleep(0.2)  # well inside the readiness wait
        began = time.monotonic()
        controller.request_cancel()
        stopped = ended.wait(2.0)
        took = time.monotonic() - began
        assert stopped and took < 1.0, f"the cancelled conversion was still waiting {took:.2f} s later"
        assert outcome == {"refused": True}, outcome
        assert made[0].poll() is not None, "the guardian it waited for was ended and reaped"
        assert real_owner.guardian_pid() is None and not ffmpeg_watch._watched
    finally:
        _end_guardians(made)
        t.join(15)


@needs_ffmpeg
def test_a_cancel_stops_the_wait_behind_another_threads_guardian(real_owner, monkeypatch):
    """The same for a run waiting while another thread makes the guardian (one at a time): it stops at its Cancel."""
    import threading
    import time

    made = _guardian_spawns(monkeypatch, stop=True)
    controller = JobController("p5h-r1-queued-guardian")
    controller.start()
    maker = threading.Thread(target=_quietly, args=(real_owner.ensure_guardian,), daemon=True)
    outcome, ended = {}, threading.Event()

    def worker():
        with ffmpeg_watch.controlled(controller.cancel_check):
            try:
                ffmpeg_watch.Supervised(_ffmpeg_version(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                outcome["started"] = True
            except ConversionCancelled:
                outcome["refused"] = True
            except BaseException as exc:  # pragma: no cover - reported below
                outcome["error"] = exc
        ended.set()

    t = threading.Thread(target=worker, daemon=True)
    try:
        maker.start()
        assert _wait_for(lambda: made)
        t.start()
        time.sleep(0.2)  # queued behind the maker
        began = time.monotonic()
        controller.request_cancel()
        stopped = ended.wait(2.0)
        took = time.monotonic() - began
        assert stopped and took < 1.0, f"the cancelled conversion was still waiting {took:.2f} s later"
        assert outcome == {"refused": True} and len(made) == 1, (outcome, made)
    finally:
        _end_guardians(made)
        t.join(15)
        maker.join(15)


def test_a_child_that_cannot_be_registered_and_will_not_end_never_holds_the_caller(real_owner, monkeypatch):
    """Codex re-review 4 (MEDIUM): with registration failing and the kill not taking, the rollback waited 2 s (inside
    a run's counted start) and then left the child alive outside both registries. It is now kept in the owner's ledger,
    retired by the owner (and by the orderly end), and the caller is not held.

    P5-I (Codex re-review 5, HIGH 3 and MEDIUM 3): it is never dropped while its end is unconfirmed -- past its retirement
    deadline it is reported UNCONFIRMED and still owned -- and it is reaped once the kill takes."""
    import signal
    import time

    from shared import child_ownership

    real_owner.ensure_guardian()
    monkeypatch.setattr(real_owner, "_register", lambda *a, **k: (_ for _ in ()).throw(MemoryError()))
    refused, real_signal = set(), child_ownership.signal_if_same
    monkeypatch.setattr(child_ownership, "signal_if_same", lambda pid, start, sig, **kw: (
        False if pid in refused and sig == signal.SIGKILL else real_signal(pid, start, sig, **kw)))
    real_popen = child_ownership.subprocess.Popen

    def popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        refused.add(proc.pid)  # its SIGKILL does not take
        return proc

    monkeypatch.setattr(child_ownership.subprocess, "Popen", popen)
    began = time.monotonic()
    with pytest.raises(MemoryError):
        real_owner.popen_external([sys.executable, "-c", "import time; time.sleep(30)"], stdout=subprocess.DEVNULL)
    took = time.monotonic() - began
    assert took < 0.5, f"the caller was held {took:.2f} s"
    stray = real_owner._strays[0]
    assert len(real_owner._strays) == 1 and stray.poll() is None, "kept, not dropped"
    assert _wait_for(lambda: [e.proc for e in real_owner.unconfirmed()] == [stray], 5), "reported unconfirmed, still owned"
    assert stray.poll() is None and real_owner.child(stray) is not None
    refused.clear()  # the kill takes now
    assert _wait_for(lambda: stray.returncode is not None and not real_owner._strays, 5), "reaped once the kill took"
    assert real_owner.child(stray) is None


@needs_ffmpeg
def test_a_child_that_cannot_be_watched_is_waited_for_outside_the_counted_start(monkeypatch):
    """The same for the watch list: an FFmpeg killed after it could not be watched is waited for once the counted start
    has let a Cancel through, never inside it (the wait is up to ``ABANDON_WAIT_SECONDS``)."""
    import threading
    import time

    controller = JobController("p5h-r1-unwatched")
    controller.start()
    failing, outcome = threading.Event(), {}
    real_kill = subprocess.Popen.kill
    monkeypatch.setattr(subprocess.Popen, "kill", lambda self: None)  # a kill that does not take
    monkeypatch.setattr(ffmpeg_watch, "ABANDON_WAIT_SECONDS", 1.5)

    def watched(*_a, **_k):
        failing.set()
        time.sleep(0.05)  # the Cancel is pressed meanwhile
        raise MemoryError()

    monkeypatch.setattr(ffmpeg_watch, "_Watched", watched)
    made = []
    real_popen = subprocess_utils.popen
    monkeypatch.setattr(subprocess_utils, "popen", lambda *a, **k: made.append(real_popen(*a, **k)) or made[-1])

    def worker():
        with ffmpeg_watch.controlled(controller.cancel_check):
            try:
                ffmpeg_watch.Supervised([*_ffmpeg_version()[:1], "-hide_banner", "-f", "lavfi", "-i",
                                         "anullsrc=r=24000:cl=mono", "-f", "null", "-"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except MemoryError:
                outcome["memory"] = True

    t = threading.Thread(target=worker, daemon=True)
    try:
        t.start()
        assert failing.wait(10)
        began = time.monotonic()
        controller.request_cancel()
        latched_in = time.monotonic() - began
        t.join(10)
        assert latched_in < C1_ACK_S, f"Cancel waited {latched_in:.2f} s for an unwatched child"
        assert outcome == {"memory": True}
    finally:
        monkeypatch.setattr(subprocess.Popen, "kill", real_kill)
        for proc in made:
            if proc.poll() is None:
                proc.kill()
                proc.wait(5)


@needs_ffmpeg
def test_a_guardian_is_made_with_a_pipe_numbered_past_selects_limit(real_owner):
    """Codex re-review 4 (MEDIUM): the guardian's readiness was read with ``select()``, which refuses a descriptor above
    1023, and the guardian it had made was left running."""
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    want = 1200
    if hard != resource.RLIM_INFINITY and hard < want:
        pytest.skip("cannot raise the descriptor limit here")
    resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, want), hard))
    held = []
    try:
        while True:
            fd = os.open(os.devnull, os.O_RDONLY)
            held.append(fd)
            if fd >= 1100:
                break
        real_owner.ensure_guardian()
        assert real_owner.guardian_pid() is not None
    finally:
        for fd in held:
            os.close(fd)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def test_a_start_queued_behind_a_guardian_makes_none_once_closing_began(real_owner, monkeypatch):
    """Codex re-review 4 (MEDIUM): a start queued behind a guardian getting ready had passed the closing check, so once
    the first was refused it made a second guardian after closing had begun. Closing is now looked at again by the
    thread that gets to make one, before it is made."""
    import threading

    from shared import child_ownership

    made = _guardian_spawns(monkeypatch)
    getting_ready, may_be_ready = threading.Event(), threading.Event()
    real_start = child_ownership.Owner._start_guardian

    real_ready = child_ownership.Owner._await_ready
    assert real_start  # (the earlier form held the spawn's ordering)

    def start_guardian(self, proc, checkpoint):
        if _caller() == "first":
            # v0.8.x P5-I: only a guardian's admission is in the ordering now, so "getting ready" is held where it happens.
            getting_ready.set()
            assert may_be_ready.wait(10)
        return real_ready(self, proc, checkpoint)

    monkeypatch.setattr(child_ownership.Owner, "_await_ready", start_guardian)
    results = {}

    def run(name, call):
        try:
            results[name] = call()
        except child_ownership.ContainmentUnavailable as exc:
            results[name] = str(exc)

    first = threading.Thread(target=run, args=("first", real_owner.ensure_guardian), name="first", daemon=True)
    first.start()
    assert getting_ready.wait(10)
    queued = threading.Thread(target=run, name="queued", daemon=True, args=(
        "queued", lambda: real_owner.popen_external([sys.executable, "-c", "pass"], stdout=subprocess.DEVNULL)))
    queued.start()
    assert _wait_for(lambda: queued.is_alive(), 1)
    __import__("time").sleep(0.2)  # queued, past popen_external's first look at closing
    real_owner.begin_closing()
    may_be_ready.set()
    first.join(15)
    queued.join(15)
    assert "closing" in str(results.get("first")) and "closing" in str(results.get("queued")), results
    assert len(made) == 1 and made[0].poll() is not None, "one guardian, ended; none made after closing began"


def test_the_orderly_end_does_not_return_with_a_guardian_still_getting_ready(real_owner, monkeypatch):
    """Codex re-review 4 (MEDIUM): ``shutdown()`` returned while a guardian it had not seen (still getting ready) ran."""
    import threading

    made = _guardian_spawns(monkeypatch, stop=True)
    maker = threading.Thread(target=_quietly, args=(real_owner.ensure_guardian,), daemon=True)
    try:
        maker.start()
        assert _wait_for(lambda: made)
        real_owner.shutdown()
        assert made[0].poll() is not None, "ended and reaped by the time the orderly end returned"
    finally:
        _end_guardians(made)
        maker.join(15)


def test_the_free_space_walk_opens_no_header_after_a_cancel_inside_a_size_estimate(tmp_path, monkeypatch):
    """Codex re-review 4 (MEDIUM): a Cancel latched inside a file's size estimate was followed by that file's header
    being opened again before the next look at Cancel."""
    import threading

    ffmpeg_utils.configure_pydub()
    parts = []
    for index in range(3):
        parts.append(tmp_path / f"p{index}.flac")
        _tone(24000, 1, 300, 300 + index).export(parts[-1], format="flac")
    pressed = threading.Event()
    opened = []
    real_size, real_facts = wl.decoded_size, disk_assembly._header_facts

    def size(paths):
        paths = list(paths)
        if paths == [parts[0]]:
            pressed.set()  # Cancel inside the first file's estimate
        return real_size(paths)

    monkeypatch.setattr(wl, "decoded_size", size)
    monkeypatch.setattr(disk_assembly, "_header_facts",
                        lambda path: (opened.append((path.name, pressed.is_set())), real_facts(path))[1])
    with ffmpeg_watch.controlled(pressed.is_set):
        with pytest.raises(ConversionCancelled):
            disk_assembly._room_needed(parts)
    assert [entry for entry in opened if entry[1]] == [], f"opened after the Cancel: {opened}"
