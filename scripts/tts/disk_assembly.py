"""Assembling a finished narration on disk, for when it does not fit in memory (v0.7.1).

The Edge routes normally decode every part into one pydub ``AudioSegment``, shorten the final tail, and let pydub write the
result to a temporary WAV file for FFmpeg to encode. Here the WAV file is what accumulates the audio, a block at a time, so
the memory needed does not grow with the narration: :data:`tts.worker_limits.DISK_ASSEMBLY_BYTES`, whatever its length.
``worker_limits.AssemblyGate`` decides when this is used; that is the whole of the difference between the two routes, and
neither route knows about the other's existence once it has begun.

**The same audio, to the byte.** Parts are decoded by the command pydub uses, and appended as pydub appends them. The WAV file
is the file pydub's ``export`` would have written. The final tail is ``audio_tail``'s own policy, over a mapping of that
file. FFmpeg then encodes it with the arguments pydub would have given it, so the MP3 is the same file
(``test_assembly_on_disk`` compares the bytes, on both routes). The one thing this route needs that the other does not is
disk space for the WAV file, and pydub writes that file anyway.

Edge audio is 16-bit PCM once decoded and has one format for a whole narration (24 kHz mono, set by ``edge_tts``), so a part
in another format is refused, not converted: it would mean something is wrong, and in-memory assembly is not the place it
would be caught either.
"""

from __future__ import annotations

import contextlib
import errno
import os
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

import numpy as np
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError, CouldntEncodeError, TooManyMissingFrames
from pydub.utils import ratio_to_db

from tts import audio_tail, ffmpeg_watch, publication

SAMPLE_WIDTH = 2
#: ``wave`` writes this much before the audio, always, for PCM.
WAV_HEADER_BYTES = 44
BLOCK_BYTES = 1024 * 1024


def _read_exactly(stream, count: int) -> bytes:
    data = stream.read(count)
    if len(data) != count:
        raise CouldntDecodeError("Decoding failed: FFmpeg's output ended before any audio.")
    return data


def _wav_format(stream) -> tuple[int, int]:
    """``(rate, channels)`` of the WAV stream FFmpeg is writing, leaving the stream at the start of its audio."""
    head = _read_exactly(stream, 12)
    if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise CouldntDecodeError("Decoding failed: FFmpeg did not write a WAV stream.")
    rate = channels = None
    while True:
        chunk = _read_exactly(stream, 8)
        size = struct.unpack("<L", chunk[4:])[0]
        if chunk[:4] == b"data":
            if rate is None:
                raise CouldntDecodeError("Decoding failed: FFmpeg's WAV stream states no format.")
            return rate, channels
        body = _read_exactly(stream, size + (size & 1))
        if chunk[:4] == b"fmt ":
            _tag, channels, rate = struct.unpack_from("<HHI", body)


class WavSpool:
    """A WAV file being filled in order. A context manager: leaving it removes the file."""

    def __init__(self, path) -> None:
        self.path = Path(path)
        self.rate: Optional[int] = None
        self.channels: Optional[int] = None
        self.pcm_bytes = 0
        self._file = open(self.path, "wb")
        self._wave = None

    def __enter__(self) -> "WavSpool":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.finish()
        finally:
            with contextlib.suppress(OSError):
                os.remove(self.path)

    @property
    def frames(self) -> int:
        return self.pcm_bytes // (SAMPLE_WIDTH * (self.channels or 1))

    @property
    def duration_ms(self) -> int:
        return round(1000 * (self.frames / self.rate)) if self.rate else 0

    def _begin(self, rate: int, channels: int) -> None:
        if self._wave is None:
            self.rate, self.channels = rate, channels
            self._wave = wave.open(self._file, "wb")
            self._wave.setnchannels(channels)
            self._wave.setsampwidth(SAMPLE_WIDTH)
            self._wave.setframerate(rate)
        elif (rate, channels) != (self.rate, self.channels):
            raise ValueError(f"A part of this narration is {rate} Hz with {channels} channel(s), but the rest is "
                             f"{self.rate} Hz with {self.channels}; it was not joined.")

    def _write(self, data: bytes) -> None:
        if data:
            publication.require_encodable(self.pcm_bytes + len(data))
            self._wave.writeframesraw(data)
            self.pcm_bytes += len(data)

    def append_file(self, path, *, format: Optional[str] = None) -> None:
        """Decode a finished audio file onto the end, with pydub's ``from_file`` command, through a small buffer."""
        command = [AudioSegment.converter, "-y"]
        if format:
            command += ["-f", format]
        command += ["-i", str(path), "-acodec", "pcm_s16le", "-vn", "-f", "wav", "-"]
        child = ffmpeg_watch.Supervised(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            try:
                self._begin(*_wav_format(child.stdout))
                for block in child.blocks(BLOCK_BYTES):
                    self._write(block)
            except CouldntDecodeError:
                # With FFmpeg gone, what it said is the better explanation, below. If it were still running it would be waiting
                # for this read, which has ended.
                child.kill()
                if child.finish() == 0:
                    raise
            code = child.finish()
            if code != 0:
                said = child.error_text().decode(errors="ignore")[-2000:]
                raise CouldntDecodeError(f"Decoding failed. ffmpeg returned error code: {code}\n\n{said}")
        finally:
            child.abandon()

    def append_segment(self, segment: AudioSegment) -> None:
        """Append a small segment, converted as ``AudioSegment.__add__`` converts what it is given."""
        if self._wave is None:
            self._begin(segment.frame_rate, segment.channels)
        elif segment.frame_rate > self.rate or segment.channels > self.channels:
            raise ValueError(f"A part of this narration is {segment.frame_rate} Hz with {segment.channels} channel(s), "
                             f"more than the {self.rate} Hz with {self.channels} of the rest; it was not joined.")
        self._write(segment.set_channels(self.channels).set_frame_rate(self.rate).set_sample_width(SAMPLE_WIDTH).raw_data)

    def append_sound(self, sound: "SoundOnDisk") -> None:
        self._begin(sound.rate, sound.channels)
        for block in sound.blocks():
            self._write(block)

    def finish(self) -> None:
        """No more audio: the file is now a complete WAV file. Everything below needs this first."""
        if self._file.closed:
            return
        try:
            if self._wave is not None:
                self._wave.close()
        finally:
            self._file.close()

    @property
    def max_dBFS(self) -> float:
        """pydub's figure for the same audio (``publication.require_audible`` reads it)."""
        peak = 0
        with open(self.path, "rb") as handle:
            handle.seek(WAV_HEADER_BYTES)
            while block := handle.read(BLOCK_BYTES):
                peak = max(peak, int(np.abs(np.frombuffer(block, dtype="<i2").astype(np.int32)).max()))
        return ratio_to_db(peak, 2 ** (8 * SAMPLE_WIDTH - 1))

    def apply_final_tail(self) -> str:
        """``audio_tail``'s policy over the file, which it reads in small blocks from the end. Returns its summary."""
        if not self.pcm_bytes:
            return ""
        pcm = np.memmap(self.path, dtype="<i2", mode="r", offset=WAV_HEADER_BYTES)
        tail = audio_tail.apply_final_tail_policy(pcm.reshape(-1, self.channels), self.rate)
        kept, summary = len(tail.pcm) * SAMPLE_WIDTH * self.channels, tail.summary()
        del tail, pcm  # the mapping goes first: Windows will not shorten a mapped file
        if kept < self.pcm_bytes:
            with open(self.path, "r+b") as handle:
                handle.truncate(WAV_HEADER_BYTES + kept)
                handle.seek(4)
                handle.write(struct.pack("<L", 36 + kept))
                handle.seek(40)
                handle.write(struct.pack("<L", kept))
            self.pcm_bytes = kept
        return summary

    def export(self, output, *, format: str, codec: Optional[str] = None, bitrate: Optional[str] = None) -> None:
        """Encode the file, with the arguments pydub's ``export`` gives FFmpeg for the same keywords."""
        command = [AudioSegment.converter, "-y", "-f", "wav", "-i", str(self.path)]
        if codec is not None:
            command += ["-acodec", codec]
        if bitrate is not None:
            command += ["-b:a", bitrate]
        if sys.platform == "darwin" and codec == "mp3":
            command += ["-write_xing", "0"]
        command += ["-f", format, str(output)]
        done = ffmpeg_watch.run(command)
        if done.returncode != 0:
            said = done.stderr.decode(errors="ignore")[-2000:]
            raise CouldntEncodeError(f"Encoding failed. ffmpeg returned error code: {done.returncode}\n\n{said}")


class SoundOnDisk:
    """Just enough of an ``AudioSegment`` for the engine's ``trim_silence_segment`` to run, unchanged, on a finished spool.

    Lengths and positions are pydub's arithmetic, including its filling of the frames a rounded end asks for beyond the
    last one: a clip is trimmed here to exactly the samples it would be trimmed to in memory.
    """

    def __init__(self, handle, rate: int, channels: int, first: int, frames: int, *, missing: int = 0,
                 reversed_: bool = False) -> None:
        self._handle = handle
        self.rate, self.channels = rate, channels
        self._first, self._frames, self._missing = first, frames, missing
        self._reversed = reversed_

    def __len__(self) -> int:
        return round(1000 * ((self._frames + self._missing) / self.rate))

    def reverse(self) -> "SoundOnDisk":
        return SoundOnDisk(self._handle, self.rate, self.channels, self._first, self._frames, missing=self._missing,
                           reversed_=not self._reversed)

    def __getitem__(self, position: slice) -> "SoundOnDisk":
        length = len(self)
        start = min(0 if position.start is None else position.start, length)
        stop = min(length if position.stop is None else position.stop, length)
        low, high = int(start * (self.rate / 1000.0)), int(stop * (self.rate / 1000.0))
        present = max(0, min(high, self._frames) - low)
        missing = (high - low) - present
        if missing > 2 * (self.rate / 1000.0):
            raise TooManyMissingFrames(f"You should never be filling in more than 2 ms with silence here, missing {missing} "
                                       "frames")
        # Which frames a stretch of the reversed sound is. Only its level is ever asked of it, and order does not change that.
        first = self._first + (self._frames - low - present if self._reversed else low)
        return SoundOnDisk(self._handle, self.rate, self.channels, first, present, missing=missing)

    def blocks(self) -> Iterable[bytes]:
        width = SAMPLE_WIDTH * self.channels
        self._handle.seek(WAV_HEADER_BYTES + self._first * width)
        left = self._frames * width
        while left:
            block = self._handle.read(min(BLOCK_BYTES, left))
            if not block:
                raise CouldntDecodeError("A narration's audio file ended early while it was being assembled.")
            left -= len(block)
            yield block
        if self._missing:
            yield b"\0" * (self._missing * width)

    @property
    def dBFS(self) -> float:
        return AudioSegment(data=b"".join(self.blocks()), sample_width=SAMPLE_WIDTH, frame_rate=self.rate,
                            channels=self.channels).dBFS


Part = Union[str, os.PathLike, AudioSegment]


def _disk_is_full(exc: BaseException) -> bool:
    if isinstance(exc, OSError):
        return exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) in (39, 112)  # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
    return isinstance(exc, (CouldntDecodeError, CouldntEncodeError)) and "no space left" in str(exc).lower()


@contextlib.contextmanager
def _naming_a_full_disk(folder):
    """A full disk says so, and where, in words someone can act on. The finished parts are not this module's to keep."""
    try:
        yield
    except (OSError, CouldntDecodeError, CouldntEncodeError) as exc:
        if isinstance(exc, publication.PublicationError) or not _disk_is_full(exc):
            raise
        raise publication.PublicationError(
            f"The drive holding {folder} ran out of space while this file's narration was being assembled, so nothing was saved "
            "for it. It needs about as much free space as the uncompressed audio. Free some space, then use Retry Failed.") from exc


def _require_room(parts: Iterable[Part], spool_path) -> None:
    """Refuse before starting when the working file can be seen not to fit: the alternative is finding out at the end."""
    from tts import worker_limits

    folder = Path(spool_path).resolve().parent
    need = worker_limits.decoded_size([part for part in parts if not isinstance(part, AudioSegment)])
    free = shutil.disk_usage(folder).free
    if need > free:
        raise publication.PublicationError(
            f"The drive holding {folder} has {free / 1024 ** 3:.1f} GB free, and this file's narration needs about "
            f"{need / 1024 ** 3:.1f} GB there to be assembled, so nothing was saved for it. Free some space, then use Retry Failed.")


def _append(spool: WavSpool, parts: Iterable[Part], format: Optional[str]) -> None:
    for part in parts:
        if isinstance(part, AudioSegment):
            spool.append_segment(part)
        else:
            spool.append_file(part, format=format)


def join_to_flac(files: Iterable, output, spool_path) -> None:
    """A chapter's audio files as one FLAC file: what decoding them, adding them up and exporting FLAC gives."""
    files = list(files)
    _require_room(files, spool_path)
    with _naming_a_full_disk(Path(spool_path).parent), WavSpool(spool_path) as spool:
        _append(spool, files, None)
        spool.finish()
        spool.export(output, format="flac")


def encode_mp3(parts: Iterable[Part], output, spool_path, *, format: Optional[str] = None, codec: Optional[str] = None,
               bitrate: Optional[str] = None) -> str:
    """A whole narration as a checked MP3, with the steps and the checks of the in-memory routes, in their order. ``parts``
    are audio files (of ``format``, when given) and short segments; returns the final tail's summary for the log."""
    parts = list(parts)
    _require_room(parts, spool_path)
    with _naming_a_full_disk(Path(spool_path).parent), WavSpool(spool_path) as spool:
        _append(spool, parts, format)
        spool.finish()
        summary = spool.apply_final_tail()
        publication.require_audible(spool)
        spool.export(output, format="mp3", codec=codec, bitrate=bitrate)
        publication.verify_finished_mp3(output, spool.duration_ms)
    return summary


def clip_to_flac(clip, output, spool_path, *, trim: Optional[Callable] = None, pause_ms: int = 0) -> int:
    """One clip too long to hold in memory as a FLAC file, trimmed by ``trim`` and followed by a pause, as the engine treats
    any other clip. Returns its sample rate."""
    with WavSpool(spool_path) as decoded:
        decoded.append_file(clip)
        decoded.finish()
        with open(decoded.path, "rb") as handle:
            sound = SoundOnDisk(handle, decoded.rate, decoded.channels, 0, decoded.frames)
            kept = trim(sound) if trim is not None else sound
            with WavSpool(f"{spool_path}.kept") as result:
                result.append_sound(kept)
                if pause_ms > 0:
                    result.append_segment(AudioSegment.silent(duration=pause_ms))
                result.finish()
                result.export(output, format="flac")
        return decoded.rate


def pause_as_file(duration_ms: int, rate: int, output) -> None:
    """A pause as its own FLAC file, as long as appending it to audio of this rate would have made it."""
    AudioSegment.silent(duration=duration_ms).set_frame_rate(rate).export(str(output), format="flac")
