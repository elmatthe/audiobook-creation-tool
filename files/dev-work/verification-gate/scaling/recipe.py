"""Deterministic M4B books for the m4b-scaling qualification (v0.7.2 Phase 7B; promoted from Phase 7A's fixtures.py).

Every book is made from lavfi sources by the pinned FFmpeg, so it is reproducible from this recipe alone and contains no
private data. Audio: per channel a seeded pink or brown noise plus a tremolo-modulated tone (non-periodic, so the MP3
encoder keeps working and a misplaced boundary is detectable), encoded AAC-LC by FFmpeg's native encoder. Chapters come
from an FFMETADATA file with odd millisecond boundaries. A 600x600 JPEG cover is attached as attached_pic, with book tags.

The FFmpeg command lines are exactly Phase 7A's, so the same FFmpeg build reproduces Phase 7A's books byte for byte
(``reference.json`` pins their SHA-256 per FFmpeg build; Phase 7B regenerated four and they matched). Each book is
validated before use: chapter count (no muxer truncation), streams, rate and channels, duration, and a complete decode.

    python recipe.py --ffmpeg <ffmpeg.exe> --out <dir> NAME [NAME ...]

Names: route10, scale<N>, long<H>_<N>, mono22k, s48k, r96k, noelst, and small<N>_<ms> (N chapters of about <ms>
milliseconds each; the threshold calibration's representative small books).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def chapters_scale(count: int) -> list[tuple[int, int]]:
    """Short chapters of about 1.5 s with odd millisecond lengths."""
    out, start = [], 0
    for index in range(count):
        length = 1500 + (index * 37) % 11
        out.append((start, start + length))
        start += length
    return out


def chapters_long(count: int, nominal_ms: int) -> list[tuple[int, int]]:
    """Long chapters of about *nominal_ms* with odd millisecond lengths."""
    out, start = [], 0
    for index in range(count):
        length = nominal_ms + (index * 7919) % 997
        out.append((start, start + length))
        start += length
    return out


def spec(name: str):
    """name -> (chapters, sample_rate, channels, extra mux args, AAC bitrate)"""
    if name.startswith("scale"):
        return chapters_scale(int(name[len("scale"):])), 44100, 2, [], "64k"
    if name == "route10":
        return chapters_long(10, 6000), 44100, 2, [], "64k"
    if name == "mono22k":
        return chapters_long(10, 6000), 22050, 1, [], "32k"
    if name == "s48k":
        return chapters_long(10, 6000), 48000, 2, [], "96k"
    if name == "r96k":
        return chapters_long(10, 6000), 96000, 2, [], "128k"
    if name == "noelst":
        return chapters_long(10, 6000), 44100, 2, ["-use_editlist", "0"], "64k"
    if name.startswith("long"):  # longH_N: H hours, N chapters
        hours, count = name[len("long"):].split("_")
        total_ms = int(hours) * 3600 * 1000
        return chapters_long(int(count), total_ms // int(count) - 500), 44100, 2, [], "64k"
    if name.startswith("small"):  # smallN_MS: N chapters of about MS milliseconds
        count, nominal = name[len("small"):].split("_")
        return chapters_long(int(count), int(nominal)), 44100, 2, [], "64k"
    raise SystemExit(f"unknown fixture {name}")


def prefix_seconds(name: str) -> float:
    """The audio the seeking route decodes and discards for this book: every chapter's start, added up."""
    return sum(start for start, _end in spec(name)[0]) / 1000.0


def saved_seconds(name: str, per_book_second: float) -> float:
    """The continuous route's estimated saving for this book, as m4b_continuous.saved_seconds computes it (prefix less
    ``per_book_second`` times the planned duration; the probed duration differs by milliseconds)."""
    return prefix_seconds(name) - per_book_second * spec(name)[0][-1][1] / 1000.0


def title(index: int) -> str:
    names = ("Opening", "The Road", "Café Night", "Interlude", "Rain", "Letters", "Return")
    return f"Chapter {index + 1}: {names[index % len(names)]}"


def graph(seconds: float, rate: int, channels: int) -> str:
    left = (f"anoisesrc=c=pink:a=0.06:r={rate}:seed=11:d={seconds}[n1];"
            f"sine=f=233:r={rate}:d={seconds},tremolo=f=2.3:d=0.8[t1];"
            f"[n1][t1]amix=inputs=2:normalize=0[l]")
    if channels == 1:
        return left + ";[l]anull[a]"
    right = (f";anoisesrc=c=brown:a=0.10:r={rate}:seed=23:d={seconds}[n2];"
             f"sine=f=347:r={rate}:d={seconds},tremolo=f=1.7:d=0.6[t2];"
             f"[n2][t2]amix=inputs=2:normalize=0[r];[l][r]amerge=inputs=2[a]")
    return left + right


def run(argv: list[str]) -> None:
    done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise SystemExit(f"FAILED ({done.returncode}): {' '.join(argv)}\n{done.stderr[-3000:]}")


def make(name: str, ffmpeg: str, ffprobe: str, out: Path) -> dict:
    chapters, rate, channels, mux_extra, bitrate = spec(name)
    seconds = chapters[-1][1] / 1000.0
    work = out / f"{name}.work"
    work.mkdir(parents=True, exist_ok=True)
    meta = work / "meta.txt"
    lines = [";FFMETADATA1", "title=Phase 7A Fixture " + name, "artist=Fixture Artist", "album=Fixture Album",
             "album_artist=Fixture Album Artist", "genre=Audiobook", ""]
    for index, (start, end) in enumerate(chapters):
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={title(index)}", ""]
    meta.write_text("\n".join(lines), encoding="utf-8")
    cover = work / "cover.jpg"
    run([ffmpeg, "-hide_banner", "-y", "-f", "lavfi", "-i", "testsrc2=s=600x600:d=1", "-frames:v", "1", "-q:v", "3",
         str(cover)])
    audio = work / "audio.m4a"
    started = time.perf_counter()
    run([ffmpeg, "-hide_banner", "-y", "-filter_complex", graph(seconds, rate, channels), "-map", "[a]",
         "-c:a", "aac", "-b:a", bitrate, str(audio)])
    encode_seconds = time.perf_counter() - started
    book = out / f"{name}.m4b"
    run([ffmpeg, "-hide_banner", "-y", "-i", str(audio), "-i", str(cover), "-i", str(meta),
         "-map", "0:a", "-map", "1:v", "-map_metadata", "2", "-map_chapters", "2",
         "-c:a", "copy", "-c:v", "copy", "-disposition:v:0", "attached_pic", *mux_extra, str(book)])

    # Validation before any use: chapters, streams, duration, complete decode.
    probe = json.loads(subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", str(book)],
        capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    found = len(probe.get("chapters", []))
    if found != len(chapters):
        raise SystemExit(f"{name}: muxed {found} chapters, planned {len(chapters)} (chapter-count truncation)")
    audio_streams = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    pictures = [s for s in probe["streams"] if s.get("disposition", {}).get("attached_pic") == 1]
    if len(audio_streams) != 1 or audio_streams[0]["codec_name"] != "aac" or len(pictures) != 1:
        raise SystemExit(f"{name}: unexpected streams {[(s['codec_type'], s['codec_name']) for s in probe['streams']]}")
    if int(audio_streams[0]["sample_rate"]) != rate or int(audio_streams[0]["channels"]) != channels:
        raise SystemExit(f"{name}: wrong rate/channels {audio_streams[0]['sample_rate']}/{audio_streams[0]['channels']}")
    duration = float(probe["format"]["duration"])
    if abs(duration - seconds) > 0.05:
        raise SystemExit(f"{name}: duration {duration} != planned {seconds}")
    started = time.perf_counter()
    run([ffmpeg, "-hide_banner", "-v", "error", "-i", str(book), "-map", "0:a", "-f", "null", "-"])
    decode_seconds = time.perf_counter() - started
    # The intermediates are not part of the fixture: only the validated book is kept.
    for leftover in (meta, cover, audio):
        leftover.unlink()
    work.rmdir()
    return {
        "name": name, "path": book.name, "sha256": sha256(book), "bytes": book.stat().st_size,
        "chapters": len(chapters), "planned_seconds": seconds, "probed_duration": duration,
        "prefix_seconds": prefix_seconds(name), "saved_seconds_at_2": saved_seconds(name, 2.0),
        "sample_rate": rate, "channels": channels, "aac_bitrate": bitrate, "mux_extra": mux_extra,
        "audio_start_time": audio_streams[0].get("start_time"), "format_start_time": probe["format"].get("start_time"),
        "aac_encode_seconds": round(encode_seconds, 2), "full_decode_seconds": round(decode_seconds, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("names", nargs="+")
    args = parser.parse_args()
    ffmpeg = args.ffmpeg
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe" if ffmpeg.endswith(".exe") else "ffprobe"))
    args.out.mkdir(parents=True, exist_ok=True)
    for name in args.names:
        started = time.perf_counter()
        entry = make(name, ffmpeg, ffprobe, args.out)
        entry["made_in_seconds"] = round(time.perf_counter() - started, 1)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
