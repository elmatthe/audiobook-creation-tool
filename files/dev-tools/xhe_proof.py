"""v0.8.x P1A, owner decision D3 -- proof 8 of plan section 11.1: a real xHE-AAC (USAC) audiobook decoded by FFmpeg's
``aac_at`` agrees with Apple's own decode of the same file (``afconvert``). Developer qualification tool; never shipped,
never run by the app. Standard library only; run it with ``-I``:

    afconvert -f caff -d LEI16 <book.m4b> <apple.caf>
    python -I files/dev-tools/xhe_proof.py --source <book.m4b> --apple <apple.caf> --ffmpeg <ffmpeg> --report <out.json>

It never trims, pads, resamples or rewrites audio: it reads two decodes and the source's own sample tables, and judges.

Criteria. T1-T3 were fixed before the first measurement (2026-11-15). T1 alone was amended by the owner after the D3
forensic investigation (2026-11-15, "D3 -- APPROVED, revised"); T2 and T3 are unchanged.

  T1  sample count: |frames(ffmpeg) - frames(apple)| <= 1024 (one AAC frame) per channel, OR the length exception
      below holds in full. Nothing else accepts a count difference.
  T2  alignment: the decodes align at a lag |lag| <= 2048 frames, found on an exact (else near-exact) window match early
      in the file; T3 is measured at that lag.
  T3  PCM: over the whole aligned overlap, the SNR of (ffmpeg - apple) relative to apple is >= 60 dB and the largest
      absolute sample difference is <= 64 LSB (16-bit).

  Length exception (T1, amended). FFmpeg may emit MORE frames than Apple only when every one of these holds:
    E1 the source is one the owner approved by SHA-256 (``APPROVED_LENGTH_EXCEPTIONS``), and both measured counts are
       exactly the counts recorded for it -- the exception is for that proven file, never a general allowance;
    E2 it is an excess, never a shortfall;
    E3 the decodes align exactly (lag 0) and every frame Apple emits is bit-identical in FFmpeg's decode;
    E4 FFmpeg emitted exactly packets x frames-per-packet frames, i.e. every packet the container holds, in full, and
       nothing more (the source's own stsz/stts accounting);
    E5 the excess is no larger than the padding the container's own sample table declares
       (packets x frames-per-packet - the stts total);
    E6 every excess frame is exactly zero (the complete region is read; its SHA-256 equals that of as many zero frames).
  Why it exists (Decisions 2026-11-15): Apple truncates its output to the edit-list length; FFmpeg presents every
  decoded packet in full. On the approved stitched fixture the difference is padding declared at the joins, and the
  excess is provably digital silence. Nothing here makes a length difference acceptable for any other file.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import struct
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Optional

CHANNELS = 2
BYTES_PER_FRAME = 2 * CHANNELS            # s16 stereo
CHUNK_FRAMES = 1 << 20
T1_FRAMES = 1024
T2_FRAMES = 2048
T3_MIN_SNR_DB = 60.0
T3_MAX_DIFF_LSB = 64
HEAD_SECONDS = 20
PROBE_SECONDS = 5
PROBE_WINDOW = 4096


@dataclass(frozen=True)
class Accounting:
    """What the source's own sample tables say about the audio track."""
    timescale: int             # mdhd: the media clock, = the decoded sample rate for AAC in MP4
    packets: int               # stsz sample count (one AAC/USAC access unit each)
    frames_per_packet: int     # the stts delta that covers most packets: a full packet
    declared_frames: int       # the stts total: what the container declares valid
    edit_frames: Optional[float] = None   # the edit list's length in media frames (informational)

    @property
    def packet_frames(self) -> int:
        return self.packets * self.frames_per_packet

    @property
    def declared_padding(self) -> int:
        return self.packet_frames - self.declared_frames


@dataclass(frozen=True)
class ApprovedLengthException:
    """One owner-approved source (by SHA-256) and the exact counts its exception was approved for."""
    source_sha256: str
    apple_frames: int
    ffmpeg_frames: int
    approved: str


#: Owner decision D3 (revised, 2026-11-15). The stitched xHE-AAC audiobook supplied by the owner (local only, never
#: committed; 35,199.6 s, 44.1 kHz stereo, 1,515,928 packets, 31 stts entries, 6,822 frames of padding declared at 15
#: joins). Apple: 1,552,303,462 frames (edit-list length); FFmpeg aac_at: 1,552,310,272 (every packet in full).
APPROVED_LENGTH_EXCEPTIONS = (
    ApprovedLengthException(
        source_sha256="b9a24a88eb0187cdddb9a62da38d69ca538634c5cd39c17a14ad25c786e0f8d4",
        apple_frames=1_552_303_462,
        ffmpeg_frames=1_552_310_272,
        approved="owner, D3 revised, 2026-11-15 (P1A D3 remediation)",
    ),
)


# --------------------------------------------------------------------------- #
#  The source's sample tables (read-only ISO-BMFF walk; mdat is never read)
# --------------------------------------------------------------------------- #
_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"}


def _boxes(handle: BinaryIO, start: int, end: int):
    position = start
    while position + 8 <= end:
        handle.seek(position)
        head = handle.read(16)
        if len(head) < 8:
            return
        size, kind = struct.unpack(">I4s", head[:8])
        header = 8
        if size == 1:
            size, header = struct.unpack(">Q", head[8:16])[0], 16
        elif size == 0:
            size = end - position
        if size < header:
            return
        yield kind, position + header, position + size
        position += size


def _walk(handle: BinaryIO, start: int, end: int, found: dict, track: Optional[dict]) -> None:
    for kind, body, stop in _boxes(handle, start, end):
        if kind == b"trak":
            fresh: dict = {}
            found.setdefault("tracks", []).append(fresh)
            _walk(handle, body, stop, found, fresh)
        elif kind in _CONTAINERS:
            _walk(handle, body, stop, found, track)
        elif kind in (b"mvhd", b"mdhd", b"hdlr", b"elst", b"stts", b"stsz"):
            handle.seek(body)
            data = handle.read(stop - body)
            (found if kind == b"mvhd" else track)[kind.decode()] = data


def _times(data: bytes) -> tuple[int, int]:
    """(timescale, duration) of an mvhd/mdhd body."""
    if data[0] == 1:
        return struct.unpack_from(">I", data, 20)[0], struct.unpack_from(">Q", data, 24)[0]
    return struct.unpack_from(">I", data, 12)[0], struct.unpack_from(">I", data, 16)[0]


def read_accounting(path: Path) -> Accounting:
    """The audio track's accounting from ``mdhd``, ``stsz``, ``stts`` and ``elst``."""
    found: dict = {}
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        _walk(handle, 0, handle.tell(), found, None)
    audio = [t for t in found.get("tracks", []) if t.get("hdlr", b"")[8:12] == b"soun"]
    if len(audio) != 1:
        raise ValueError(f"{path.name}: expected one audio track, found {len(audio)}")
    track = audio[0]
    timescale, _duration = _times(track["mdhd"])
    stts = track["stts"]
    entries = [struct.unpack_from(">II", stts, 8 + 8 * i) for i in range(struct.unpack_from(">I", stts, 4)[0])]
    packets = struct.unpack_from(">I", track["stsz"], 8)[0]
    if packets != sum(count for count, _delta in entries):
        raise ValueError(f"{path.name}: stsz counts {packets} packets, stts {sum(c for c, _d in entries)}")
    by_delta: dict[int, int] = {}
    for count, delta in entries:
        by_delta[delta] = by_delta.get(delta, 0) + count
    frames_per_packet = max(by_delta, key=by_delta.get)
    edit_frames = None
    if "elst" in track and "mvhd" in found:
        movie_scale, _ = _times(found["mvhd"])
        elst = track["elst"]
        version, count = elst[0], struct.unpack_from(">I", elst, 4)[0]
        width = 20 if version == 1 else 12
        total = sum(struct.unpack_from(">Q" if version == 1 else ">I", elst, 8 + width * i)[0] for i in range(count))
        edit_frames = total * timescale / movie_scale
    return Accounting(timescale, packets, frames_per_packet, sum(c * d for c, d in entries), edit_frames)


# --------------------------------------------------------------------------- #
#  Reading the decodes
# --------------------------------------------------------------------------- #
def open_caf_lpcm(path: Path) -> tuple[BinaryIO, bool, float]:
    """A CAF's 16-bit stereo LPCM data as a stream: (stream positioned at the first sample, big_endian, rate)."""
    handle = open(path, "rb")
    if handle.read(4) != b"caff":
        handle.close()
        raise ValueError(f"{path.name} is not a CAF file")
    handle.read(4)
    description = None
    while True:
        head = handle.read(12)
        if len(head) < 12:
            handle.close()
            raise ValueError(f"{path.name} has no data chunk")
        kind, size = head[:4], struct.unpack(">q", head[4:])[0]
        if kind == b"desc":
            rate, fmt, flags, _bpp, _fpp, channels, bits = struct.unpack(">d4sIIIII", handle.read(size))
            description = (rate, fmt, flags, channels, bits)
        elif kind == b"data":
            handle.read(4)  # edit count
            if description is None or description[1] != b"lpcm" or description[3:] != (CHANNELS, 16):
                handle.close()
                raise ValueError(f"{path.name} is not 16-bit stereo LPCM: {description}")
            stream = handle if size == -1 else _Limited(handle, size - 4)   # -1: the data runs to the end
            return stream, not (description[2] & 2), description[0]   # flag 2: little-endian
        else:
            handle.seek(size, 1)


class _Limited:
    """A read-only view of the next ``remaining`` bytes of ``handle`` (a CAF data chunk with a stated size)."""

    def __init__(self, handle: BinaryIO, remaining: int) -> None:
        self._handle, self._remaining = handle, remaining

    def read(self, size: int = -1) -> bytes:
        size = self._remaining if size < 0 else min(size, self._remaining)
        data = self._handle.read(size) if size > 0 else b""
        self._remaining -= len(data)
        return data

    def close(self) -> None:
        self._handle.close()


def _read(stream: BinaryIO, frames: int) -> bytes:
    wanted, parts = frames * BYTES_PER_FRAME, []
    while wanted > 0:
        block = stream.read(wanted)
        if not block:
            break
        parts.append(block)
        wanted -= len(block)
    data = b"".join(parts)
    return data[: len(data) // BYTES_PER_FRAME * BYTES_PER_FRAME]


def _samples(raw: bytes, big_endian: bool) -> array.array:
    values = array.array("h")
    values.frombytes(raw)
    if big_endian != (sys.byteorder == "big"):
        values.byteswap()
    return values


def _little(raw: bytes, big_endian: bool) -> bytes:
    """Little-endian bytes, so the two decodes can be compared byte for byte."""
    if not big_endian:
        return raw
    return _samples(raw, True).tobytes() if sys.byteorder == "little" else raw


def _find_lag(apple: bytes, ffmpeg: bytes, rate: float) -> tuple[Optional[int], bool]:
    """T2: apple index = ffmpeg index + lag. An exact frame-aligned window match first, else the least absolute
    difference within +-T2_FRAMES. A window of digital silence never decides the lag."""
    frames = min(len(apple), len(ffmpeg)) // BYTES_PER_FRAME
    start = min(int(rate * PROBE_SECONDS), max(0, frames // 4))
    zero = bytes(PROBE_WINDOW * BYTES_PER_FRAME)
    while start + PROBE_WINDOW <= len(ffmpeg) // BYTES_PER_FRAME:
        window = ffmpeg[start * BYTES_PER_FRAME:(start + PROBE_WINDOW) * BYTES_PER_FRAME]
        if window != zero:
            break
        start += PROBE_WINDOW
    else:
        return None, False
    position = apple.find(window)
    while position != -1 and position % BYTES_PER_FRAME:
        position = apple.find(window, position + 1)
    if position != -1:
        return position // BYTES_PER_FRAME - start, True
    a, f = _samples(apple, False), _samples(ffmpeg, False)
    best = None
    for lag in range(-T2_FRAMES, T2_FRAMES + 1):
        base = (start + lag) * CHANNELS
        if base < 0 or base + PROBE_WINDOW * CHANNELS > len(a):
            continue
        total = sum(abs(a[base + i] - f[start * CHANNELS + i]) for i in range(0, PROBE_WINDOW * CHANNELS, 8))
        if best is None or total < best[0]:
            best = (total, lag)
    return (best[1] if best else None), False


def _is_zero(block: bytes) -> bool:
    return not block.strip(b"\0")


def evaluate(apple: BinaryIO, ffmpeg: BinaryIO, accounting: Accounting, *, source_sha256: str,
             apple_big_endian: bool = False, rate: float = 44100.0,
             approved: tuple = APPROVED_LENGTH_EXCEPTIONS) -> dict:
    """Read both decodes to their ends and judge them against T1-T3 and the length exception. Never writes audio."""
    started = time.monotonic()
    a_head = _little(_read(apple, int(rate * HEAD_SECONDS)), apple_big_endian)
    f_head = _read(ffmpeg, int(rate * HEAD_SECONDS))
    lag, exact = _find_lag(a_head, f_head, rate)
    total_a, total_f = len(a_head) // BYTES_PER_FRAME, len(f_head) // BYTES_PER_FRAME
    if lag is None:
        lag = 0
        lag_found = False
    else:
        lag_found = True
    # Align: index 0 of each buffer is the same instant.
    a_buf, f_buf = (a_head[lag * BYTES_PER_FRAME:], f_head) if lag >= 0 else (a_head, f_head[-lag * BYTES_PER_FRAME:])
    signal = error = 0.0
    max_diff = identical = compared = 0
    first_difference = None
    while True:
        n = min(len(a_buf), len(f_buf)) // BYTES_PER_FRAME * BYTES_PER_FRAME
        if n:
            ab, fb = a_buf[:n], f_buf[:n]
            if ab == fb:
                identical += n // BYTES_PER_FRAME
                values = _samples(ab, False)
                signal += sum(x * x for x in values[::64]) * 64.0
            else:
                av, fv = _samples(ab, False), _samples(fb, False)
                for index, (x, y) in enumerate(zip(av, fv)):
                    difference = y - x
                    signal += x * x
                    if difference:
                        error += difference * difference
                        if first_difference is None:
                            first_difference = compared + index // CHANNELS
                        if abs(difference) > max_diff:
                            max_diff = abs(difference)
                identical += sum(1 for i in range(0, n, BYTES_PER_FRAME) if ab[i:i + 4] == fb[i:i + 4])
            compared += n // BYTES_PER_FRAME
            a_buf, f_buf = a_buf[n:], f_buf[n:]
        more_a = _little(_read(apple, CHUNK_FRAMES), apple_big_endian) if not len(a_buf) else b""
        more_f = _read(ffmpeg, CHUNK_FRAMES) if not len(f_buf) else b""
        total_a += len(more_a) // BYTES_PER_FRAME
        total_f += len(more_f) // BYTES_PER_FRAME
        a_buf += more_a
        f_buf += more_f
        if not more_a and not more_f and (not len(a_buf) or not len(f_buf)):
            break
    # Whatever is left belongs to one decode only: FFmpeg's excess, or Apple's frames FFmpeg never produced.
    excess_digest, excess_frames, excess_first_nonzero = hashlib.sha256(), 0, None
    leftover, source = (f_buf, ffmpeg) if len(f_buf) else (a_buf, apple)
    extra_is_ffmpeg = bool(len(f_buf))
    while leftover:
        if extra_is_ffmpeg:
            excess_digest.update(leftover)
        if excess_first_nonzero is None and not _is_zero(leftover):
            stripped = len(leftover) - len(leftover.lstrip(b"\0"))
            excess_first_nonzero = excess_frames + stripped // BYTES_PER_FRAME
        excess_frames += len(leftover) // BYTES_PER_FRAME
        leftover = _read(source, CHUNK_FRAMES)
        if not extra_is_ffmpeg:
            leftover = _little(leftover, apple_big_endian)
            total_a += len(leftover) // BYTES_PER_FRAME
        else:
            total_f += len(leftover) // BYTES_PER_FRAME
    snr = math.inf if error == 0 else (10 * math.log10(signal / error) if signal > 0 else -math.inf)
    difference = total_f - total_a
    t1_strict = abs(difference) <= T1_FRAMES
    t2 = lag_found and abs(lag) <= T2_FRAMES
    t3 = snr >= T3_MIN_SNR_DB and max_diff <= T3_MAX_DIFF_LSB
    zero_digest = hashlib.sha256(bytes(excess_frames * BYTES_PER_FRAME)).hexdigest() if extra_is_ffmpeg else None
    record = next((item for item in approved if item.source_sha256 == source_sha256), None)
    conditions = {
        "E1_owner_approved_source_and_exact_counts": bool(record and record.apple_frames == total_a
                                                          and record.ffmpeg_frames == total_f),
        "E2_excess_not_shortfall": difference > 0,
        "E3_exact_alignment_and_bit_identical_common_range": (lag_found and lag == 0 and max_diff == 0
                                                              and identical == compared == total_a),
        "E4_ffmpeg_frames_equal_packets_times_frames_per_packet": total_f == accounting.packet_frames,
        "E5_excess_within_declared_padding": 0 < difference <= accounting.declared_padding,
        "E6_every_excess_frame_is_zero": (extra_is_ffmpeg and excess_frames == difference
                                          and excess_first_nonzero is None),
        "rate_matches_media_timescale": int(rate) == accounting.timescale,
    }
    exception = (not t1_strict) and all(conditions.values())
    t1 = t1_strict or exception
    reasons = []
    if not t1:
        failed = [name for name, ok in conditions.items() if not ok]
        reasons.append(f"T1: count difference {difference:+d} frames exceeds {T1_FRAMES} and the length exception "
                       f"does not hold ({', '.join(failed)})")
    if not t2:
        reasons.append(f"T2: no alignment within {T2_FRAMES} frames (lag {lag}, found {lag_found})")
    if not t3:
        reasons.append(f"T3: SNR {snr} dB, max |diff| {max_diff} LSB")
    return {
        "source_sha256": source_sha256,
        "accounting": {**asdict(accounting), "packet_frames": accounting.packet_frames,
                       "declared_padding": accounting.declared_padding},
        "apple_frames": total_a, "ffmpeg_frames": total_f, "frame_count_difference": difference,
        "lag_frames": lag, "lag_exact_match": exact, "compared_frames": compared, "identical_frames": identical,
        "first_differing_frame": first_difference, "snr_db": snr, "max_abs_diff_lsb": max_diff,
        "extra_frames_belong_to": ("ffmpeg" if extra_is_ffmpeg else "apple") if excess_frames else None,
        "extra_frames": excess_frames, "extra_first_nonzero_frame": excess_first_nonzero,
        "excess_sha256": excess_digest.hexdigest() if extra_is_ffmpeg else None,
        "zero_frames_sha256": zero_digest,
        "approved_record": asdict(record) if record else None,
        "length_exception_conditions": conditions, "length_exception_applied": exception,
        "T1_sample_count_pass": t1, "T1_strict_pass": t1_strict, "T2_alignment_pass": t2, "T3_pcm_pass": t3,
        "PASS": t1 and t2 and t3, "reasons": reasons, "seconds": round(time.monotonic() - started, 1),
    }


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def ffmpeg_decode_argv(ffmpeg: str, source: Path) -> list[str]:
    """The decode under test: aac_at, the whole file, no seeking, 16-bit stereo at the source rate."""
    return [ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-c:a", "aac_at", "-i", str(source), "-map", "0:a:0",
            "-f", "s16le", "-ac", "2", "-ar", "44100", "-"]


def run(source: Path, apple_caf: Path, ffmpeg: str, *, approved: tuple = APPROVED_LENGTH_EXCEPTIONS) -> dict:
    before = sha256_of(source)
    accounting = read_accounting(source)
    stream, big_endian, rate = open_caf_lpcm(apple_caf)
    process = subprocess.Popen(ffmpeg_decode_argv(ffmpeg, source), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL)
    try:
        result = evaluate(stream, process.stdout, accounting, source_sha256=before, apple_big_endian=big_endian,
                          rate=rate, approved=approved)
    finally:
        stream.close()
        process.stdout.close()
        stderr = process.stderr.read().decode("utf-8", "replace")
        code = process.wait()
    result["ffmpeg_exit"] = code
    result["ffmpeg_stderr"] = stderr.strip()[:2000]
    result["source_sha256_after"] = sha256_of(source)
    result["source_unchanged"] = result["source_sha256_after"] == before
    result["PASS"] = result["PASS"] and code == 0 and not stderr.strip() and result["source_unchanged"]
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--apple", type=Path, required=True, help="afconvert -f caff -d LEI16 decode of --source")
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(args.source, args.apple, args.ffmpeg)
    text = json.dumps(result, indent=2, default=str)
    args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
