"""Deterministic synthetic inputs, generated fresh and validated before any application sees them (plan section 9).

Nothing here depends on an earlier run's output: every sample is computed from fixtures/manifest.json and encoded with the pinned
FFmpeg. A fixture that fails its validation raises FixtureInvalid, which is an infrastructure failure and never counts against the
application. An arbitrary file renamed .m4b, or an ID3 header with no audio behind it, cannot get through ``validated``: that is the
line between these and the deliberately fake orchestration fixtures the older tests use, which fixtures/manifest.json lists by name.

The audio is designed to be told apart. Each chapter or track has its own tone family plus a repeating sweep, so a waveform comparison
has one sharp answer, and each starts and ends with a short burst at a marker frequency. A wrong order, a lost boundary, an attenuated
first frame or a truncated last chapter all change what the oracle measures.
"""

from __future__ import annotations

import json
import math
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING


from . import media_oracle as oracle

if TYPE_CHECKING:
    import numpy as np


SOURCE_RATE = 44100
HEAD_MARKER_HZ, TAIL_MARKER_HZ = 5000.0, 7000.0
MARKER_SECONDS = 0.030
_NO_WINDOW = 0x08000000


def load_manifest(path: Path) -> dict:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [entry.get("id") for entry in manifest.get("fixtures", [])]
    if len(ids) != len(set(ids)) or not all(ids):
        raise oracle.FixtureInvalid("fixtures/manifest.json: every fixture needs a unique id")
    return manifest


def segment_samples(*, tone: float, seconds: float, seed: int, rate: int = SOURCE_RATE) -> np.ndarray:
    """One chapter or track as float samples: tone, sweep, and a marker burst at each end. Pure arithmetic, so repeatable."""
    import numpy as np

    count = int(round(seconds * rate))
    t = np.arange(count, dtype=np.float64) / rate
    period = 0.47 + 0.03 * (seed % 5)
    phase = (t % period) / period
    sweep_from, sweep_to = 900.0 + 37.0 * seed, 2400.0 + 41.0 * seed
    sweep = np.sin(2.0 * np.pi * period * (sweep_from * phase + 0.5 * (sweep_to - sweep_from) * phase * phase))
    samples = 0.32 * np.sin(2.0 * np.pi * tone * t) + 0.22 * sweep
    edge = min(int(MARKER_SECONDS * rate), count // 4)
    if edge:
        samples[:edge] = 0.55 * np.sin(2.0 * np.pi * HEAD_MARKER_HZ * t[:edge])
        samples[-edge:] = 0.55 * np.sin(2.0 * np.pi * TAIL_MARKER_HZ * t[-edge:])
    return samples


def timeline(sections: list[dict], *, rate: int = SOURCE_RATE) -> np.ndarray:
    import numpy as np

    return np.concatenate([segment_samples(tone=s["tone"], seconds=s["seconds"], seed=index, rate=rate)
                           for index, s in enumerate(sections, start=1)])


def write_wav(path: Path, samples: np.ndarray, *, rate: int = SOURCE_RATE, channels: int = 1) -> Path:
    import numpy as np

    pcm = np.clip(np.round(samples * 32767.0), -32768, 32767).astype("<i2")
    if channels == 2:
        pcm = np.column_stack((pcm, pcm)).reshape(-1)
    with wave.open(str(path), "wb") as sink:
        sink.setnchannels(channels)
        sink.setsampwidth(2)
        sink.setframerate(rate)
        sink.writeframes(pcm.tobytes())
    return path


def _ffmpeg(tools: oracle.Toolchain, *arguments: str, timeout: float = 180) -> None:
    done = subprocess.run([tools.ffmpeg, "-hide_banner", "-v", "error", "-y", *arguments], capture_output=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    if done.returncode != 0:
        raise oracle.FixtureInvalid(f"the generator's FFmpeg step failed: {done.stderr.decode('utf-8', 'replace')[:400]}")


def _metadata_arguments(tags: dict | None) -> list[str]:
    arguments: list[str] = []
    for key, value in (tags or {}).items():
        arguments += ["-metadata", f"{key}={value}"]
    return arguments


def encode_mp3(tools: oracle.Toolchain, wav: Path, target: Path, *, tags: dict | None = None, quality: int = 2) -> Path:
    _ffmpeg(tools, "-i", str(wav), "-map_metadata", "-1", "-c:a", "libmp3lame", "-q:a", str(quality), "-bitexact",
            *_metadata_arguments(tags), "-id3v2_version", "3", str(target))
    return target


def _chapter_metadata(path: Path, sections: list[dict], tags: dict | None) -> Path:
    lines = [";FFMETADATA1"]
    for key, value in (tags or {}).items():
        lines.append(f"{key}={value}")
    position = 0
    for section in sections:
        length = int(round(section["seconds"] * 1000))
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={position}", f"END={position + length}", f"title={section['title']}"]
        position += length
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def make_m4b(tools: oracle.Toolchain, sections: list[dict], target: Path, *, work: Path, tags: dict | None = None,
             artwork: Path | None = None, bitrate: str = "128k") -> Path:
    """A genuine M4B: AAC in an MP4 container with embedded chapters, tags and (when given) an attached picture."""
    wav = write_wav(work / f"{target.stem}.wav", timeline(sections))
    metadata = _chapter_metadata(work / f"{target.stem}.ffmeta", sections, tags)
    arguments = ["-i", str(wav), "-i", str(metadata)]
    if artwork is not None:
        arguments += ["-i", str(artwork)]
    arguments += ["-map", "0:a", "-map_metadata", "1", "-map_chapters", "1"]
    if artwork is not None:
        arguments += ["-map", "2:v", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    arguments += ["-c:a", "aac", "-b:a", bitrate, "-bitexact", "-f", "ipod", str(target)]
    _ffmpeg(tools, *arguments)
    wav.unlink()
    return target


def make_image(target: Path, *, size: tuple[int, int], corners: tuple, kind: str, alpha: bool = False) -> Path:
    """A valid image whose four corners are different colours, so a crop or a letterbox shows in the output's pixels."""
    from PIL import Image

    width, height = size
    image = Image.new("RGBA" if alpha else "RGB", size, (200, 200, 200, 128) if alpha else (200, 200, 200))
    pixels = image.load()
    block_w, block_h = max(4, width // 8), max(4, height // 8)
    regions = (((0, 0), corners[0]), ((width - block_w, 0), corners[1]), ((0, height - block_h), corners[2]),
               ((width - block_w, height - block_h), corners[3]))
    for (left, top), colour in regions:
        fill = (*colour, 255) if alpha else tuple(colour)
        for y in range(top, top + block_h):
            for x in range(left, left + block_w):
                pixels[x, y] = fill
    if kind == "jpeg":
        image.save(target, format="JPEG", quality=95, subsampling=0)
    else:
        image.save(target, format="PNG")
    return target


def make_replay_clips(tools: oracle.Toolchain, folder: Path, tones: list[float], *, seconds: float = 0.8) -> list[Path]:
    """Real MP3 frames in the format Microsoft's service returns (24 kHz mono, 48 kbit/s), one distinct tone each, for the replayed service."""
    import numpy as np

    folder.mkdir(parents=True, exist_ok=True)
    clips = []
    for index, tone in enumerate(tones):
        count = int(seconds * SOURCE_RATE)
        t = np.arange(count, dtype=np.float64) / SOURCE_RATE
        wav = write_wav(folder / f"clip{index}.wav", 0.5 * np.sin(2.0 * np.pi * tone * t))
        target = folder / f"clip{index}.mp3"
        _ffmpeg(tools, "-i", str(wav), "-map_metadata", "-1", "-ar", "24000", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "48k", "-bitexact", str(target))
        wav.unlink()
        report = oracle.Report()
        oracle.inspect_audio(tools, target, report, label="replay clip", codec="mp3", sample_rate=24000, channels=1, duration=seconds, duration_tolerance=0.1)
        if report.failed:
            raise oracle.FixtureInvalid(f"replay clip {index}: {report.failed[:2]}")
        clips.append(target)
    return clips


def make_pdf(target: Path, pages: list[str]) -> Path:
    """A real PDF with a text layer, through the project's own pinned PDF library."""
    import fitz

    document = fitz.open()
    for text in pages:
        page = document.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 523, 770), text, fontsize=12, fontname="helv")
    document.save(target, deflate=False, garbage=0, no_new_id=True)
    document.close()
    return target


@dataclass
class Generated:
    id: str
    path: Path
    kind: str
    expected: dict
    validation: list[dict]

    def record(self) -> dict:
        return {"id": self.id, "kind": self.kind, "name": self.path.name, "bytes": self.path.stat().st_size,
                "sha256": oracle._sha256(self.path), "validation": self.validation}


class FixtureSet:
    """Builds fixtures from the manifest into one folder, validating each before it is handed out, and remembers what it built."""

    def __init__(self, tools: oracle.Toolchain, manifest: dict, folder: Path) -> None:
        self.tools = tools
        self.entries = {entry["id"]: entry for entry in manifest["fixtures"]}
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "_work").mkdir(exist_ok=True)
        self.built: dict[str, Generated] = {}

    def get(self, fixture_id: str) -> Generated:
        if fixture_id in self.built:
            return self.built[fixture_id]
        if fixture_id not in self.entries:
            raise oracle.FixtureInvalid(f"no fixture named {fixture_id!r} in the manifest")
        entry = self.entries[fixture_id]
        builder = getattr(self, f"_build_{entry['kind'].replace('-', '_')}", None)
        if builder is None:
            raise oracle.FixtureInvalid(f"{fixture_id}: unknown kind {entry['kind']!r}")
        generated = builder(entry)
        self.built[fixture_id] = generated
        return generated

    def records(self) -> list[dict]:
        return [item.record() for item in self.built.values()]

    def path(self, fixture_id: str) -> Path:
        return self.get(fixture_id).path

    def _target(self, entry: dict) -> Path:
        directory = self.folder / entry.get("folder", "")
        directory.mkdir(parents=True, exist_ok=True)
        return directory / entry["name"]

    # -- real tiers ------------------------------------------------------------- #
    def _build_text(self, entry: dict) -> Generated:
        target = self._target(entry)
        target.write_text(entry["text"], encoding="utf-8", newline="\n")
        if not target.read_text(encoding="utf-8").strip():
            raise oracle.FixtureInvalid(f"{entry['id']}: the text fixture is empty")
        return Generated(entry["id"], target, "text", entry.get("expected", {}), [{"name": "utf-8 text", "ok": True}])

    def _build_pdf(self, entry: dict) -> Generated:
        target = make_pdf(self._target(entry), entry["pages"])
        import fitz

        with fitz.open(target) as document:
            read = "\n".join(page.get_text() for page in document)
            pages = document.page_count
        words = " ".join(entry["pages"]).split()
        if pages != len(entry["pages"]) or (words and words[0] not in read) or (not words and read.strip()):
            raise oracle.FixtureInvalid(f"{entry['id']}: the generated PDF does not read back as written")
        return Generated(entry["id"], target, "pdf", {}, [{"name": "pages and text layer read back", "ok": True}])

    def _build_mp3_track(self, entry: dict) -> Generated:
        target = self._target(entry)
        channels = entry.get("channels", 2)
        wav = write_wav(self.folder / "_work" / f"{target.stem}.wav",
                        segment_samples(tone=entry["tone"], seconds=entry["seconds"], seed=entry.get("seed", 1)), channels=channels)
        encode_mp3(self.tools, wav, target, tags=entry.get("tags"))
        wav.unlink()
        return self._validated_audio(entry, target, codec="mp3", container="mp3", duration=entry["seconds"], channels=channels,
                                     tags=entry.get("tags"))

    def _build_m4b(self, entry: dict) -> Generated:
        target = self._target(entry)
        artwork = self.path(entry["artwork"]) if entry.get("artwork") else None
        make_m4b(self.tools, entry["sections"], target, work=self.folder / "_work", tags=entry.get("tags"), artwork=artwork)
        seconds = sum(section["seconds"] for section in entry["sections"])
        generated = self._validated_audio(entry, target, codec="aac", container="mp4", duration=seconds, channels=1, tags=entry.get("tags"))
        report = oracle.Report()
        probed = oracle.probe(self.tools, target)
        position, expected = 0.0, []
        for section in entry["sections"]:
            expected.append({"title": section["title"], "start": position, "end": position + section["seconds"]})
            position += section["seconds"]
        oracle.inspect_chapters(probed, report, label="fixture", expected=expected)
        if artwork is not None:
            report.check("fixture: artwork attached", oracle.artwork_stream(probed) is not None)
        if report.failed:
            raise oracle.FixtureInvalid(f"{entry['id']}: {report.failed[:3]}")
        generated.validation += report.checks
        generated.expected = {"chapters": expected, "tags": entry.get("tags", {})}
        return generated

    def _build_m4b_looped(self, entry: dict) -> Generated:
        """Hours of a genuine M4B without hours of samples: real AAC packets repeated by FFmpeg, chapters on top. For work that takes real
        time. Its content repeats, so nothing may compare its signal; a chapter here is checked by duration and decoding alone."""
        target = self._target(entry)
        work = self.folder / "_work"
        seed = work / f"{target.stem}-seed.m4a"
        wav = write_wav(work / f"{target.stem}-seed.wav", timeline([{"tone": 330.0, "seconds": float(entry["seed_seconds"])}]))
        _ffmpeg(self.tools, "-i", str(wav), "-c:a", "aac", "-b:a", "64k", "-bitexact", str(seed))
        wav.unlink()
        metadata = _chapter_metadata(work / f"{target.stem}.ffmeta", entry["sections"], entry.get("tags"))
        _ffmpeg(self.tools, "-stream_loop", str(int(entry["loops"]) - 1), "-i", str(seed), "-i", str(metadata), "-map", "0:a", "-map_metadata", "1",
                "-map_chapters", "1", "-c", "copy", "-bitexact", "-f", "ipod", str(target))
        seed.unlink()
        seconds = sum(section["seconds"] for section in entry["sections"])
        report = oracle.Report()
        probed = oracle.probe(self.tools, target)
        found = float(probed["format"]["duration"])
        report.check("fixture: its duration", abs(found - seconds) <= 2.0, f"{found} s, expected {seconds} s")
        report.equal("fixture: chapter count", len(oracle.chapters_of(probed)), len(entry["sections"]))
        report.equal("fixture: codec", oracle.audio_stream(probed).get("codec_name"), "aac")
        if report.failed:
            raise oracle.FixtureInvalid(f"{entry['id']}: {report.failed[:3]}")
        return Generated(entry["id"], target, "m4b-looped", {}, report.checks)

    def _build_image(self, entry: dict) -> Generated:
        from PIL import Image

        target = make_image(self._target(entry), size=tuple(entry["size"]), corners=tuple(tuple(c) for c in entry["corners"]),
                            kind=entry["format"], alpha=entry.get("alpha", False))
        with Image.open(target) as image:
            image.load()
            facts = {"size": list(image.size), "format": image.format}
        if facts["size"] != list(entry["size"]):
            raise oracle.FixtureInvalid(f"{entry['id']}: generated size {facts['size']}")
        return Generated(entry["id"], target, "image", entry, [{"name": "decodes at its size", "ok": True, **facts}])

    # -- adverse tier: each is a real input damaged in one known way, and its damage is itself proved ------------------------- #
    def _build_truncated(self, entry: dict) -> Generated:
        source = self.path(entry["from"])
        data = source.read_bytes()
        keep = int(len(data) * entry.get("keep_fraction", 0.4))
        target = self._target(entry)
        target.write_bytes(data[:keep])
        return Generated(entry["id"], target, "truncated", entry, [{"name": "is a damaged copy", "ok": keep < len(data), "of": entry["from"]}])

    def _build_garbage(self, entry: dict) -> Generated:
        target = self._target(entry)
        target.write_bytes(bytes((index * 37 + 11) % 256 for index in range(entry.get("bytes", 4096))))
        return Generated(entry["id"], target, "garbage", entry, [{"name": "deterministic non-media bytes", "ok": True}])

    def _validated_audio(self, entry: dict, target: Path, **expected) -> Generated:
        report = oracle.Report()
        try:
            oracle.inspect_audio(self.tools, target, report, label="fixture", **expected)
        except oracle.OracleFailure as exc:
            raise oracle.FixtureInvalid(f"{entry['id']}: {exc}") from None
        if report.failed:
            raise oracle.FixtureInvalid(f"{entry['id']}: {report.failed[:3]}")
        return Generated(entry["id"], target, entry["kind"], {}, report.checks)


def section_interval(entry_sections: list[dict], index: int, rate: int = oracle.ORACLE_RATE) -> tuple[int, int]:
    """The sample interval of one section at ``rate``, from the same arithmetic that made the source."""
    start = sum(section["seconds"] for section in entry_sections[:index])
    return int(round(start * rate)), int(round((start + entry_sections[index]["seconds"]) * rate))


def expected_tone(sections: list[dict], index: int) -> float:
    return float(sections[index]["tone"])


def seconds_of(sections: list[dict]) -> float:
    return math.fsum(section["seconds"] for section in sections)
