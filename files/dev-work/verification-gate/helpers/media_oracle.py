"""Independent inspection of real media (plan section 9.1). This module imports nothing from the application.

The pinned FFmpeg pair is used through argv lists with bounded time, and its identity is proved here from its recorded hash, not
taken from a path. A successful probe proves little on its own, so the checks here decode every sample, read the tags and chapters,
and compare the signal with what the input's complete decode says should be there. Duration equality cannot see the historical AAC
priming defect, so nothing here accepts a chapter on its duration.

Three kinds of trouble stay apart, because they mean different things to the gate:

    OracleFailure        the output is wrong: FAIL.
    FixtureInvalid       an input is not what it claims: an infrastructure failure, never an application defect.
    ToolchainUnavailable the pinned pair cannot be established: BLOCKED.

Calibration, measured once against the pinned ffmpeg 9.0.1 build on real outputs of each route (recorded in fixtures/README.md):
a chapter's MP3 decodes at its exact place in the source, so a lag beyond MAX_LAG_SAMPLES is misplaced content, never something to
align away.

numpy is imported where it is used, not at the top: the gate itself loads ``helpers`` and must judge with the standard library alone. Only the
acceptance runner, in its own process, ever calls these.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import numpy as np


PROBE_SECONDS = 60
DECODE_SECONDS = 300
#: The comparison rate. High enough for every marker in the fixtures, low enough to compare in Python in moments.
ORACLE_RATE = 22050
#: How far the comparison looks for the best alignment, at ORACLE_RATE.
SEARCH_SAMPLES = 512
#: Decoded output must line up with the source within this many samples (under a millisecond). The Converter's real route measures
#: 0 on the pinned build; the historical input-side seek measures 57 to 250, one chapter of it otherwise matching perfectly.
MAX_LAG_SAMPLES = 16
#: Waveform agreement between a chapter's output and its source interval. Lossy-to-lossy on these fixtures measures above 0.97.
MIN_CORRELATION = 0.90
#: The first and last stretch of a chapter must keep their energy: this is what an attenuated first frame or a lost tail fails.
EDGE_SECONDS = 0.060
MIN_EDGE_ENERGY = 0.55
MAX_EDGE_ENERGY = 1.8
_NO_WINDOW = 0x08000000


class OracleFailure(AssertionError):
    """The output under inspection is not what it must be."""


class FixtureInvalid(ValueError):
    """A generated input failed validation before any application touched it. Not an application defect."""


class ToolchainUnavailable(RuntimeError):
    """The pinned FFmpeg pair is missing or not the recorded bytes."""


@dataclass(frozen=True)
class Toolchain:
    ffmpeg: str
    ffprobe: str
    ffmpeg_sha256: str
    ffprobe_sha256: str
    version: str

    def record(self) -> dict:
        return {"ffmpeg_sha256": self.ffmpeg_sha256, "ffprobe_sha256": self.ffprobe_sha256, "version": self.version}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pinned_toolchain(repo_root: Path) -> Toolchain:
    """The pair the installation proved, checked byte for byte against that proof. Anything else is BLOCKED."""
    state_path = Path(repo_root) / "files" / "runtime-data" / "ffmpeg-state.json"
    try:
        pair = json.loads(state_path.read_text(encoding="utf-8"))["pair"]
        ffmpeg, ffprobe = Path(pair["ffmpeg"]["path"]), Path(pair["ffprobe"]["path"])
        wanted = pair["ffmpeg"]["sha256"], pair["ffprobe"]["sha256"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ToolchainUnavailable(f"no proved FFmpeg pair at {state_path}: {type(exc).__name__}: {exc}") from None
    for path, expected in zip((ffmpeg, ffprobe), wanted):
        if not path.is_file():
            raise ToolchainUnavailable(f"{path} is recorded as the pinned binary but is not there")
        found = _sha256(path)
        if found != expected:
            raise ToolchainUnavailable(f"{path} is {found}, not the recorded {expected}")
    version = _run([str(ffmpeg), "-hide_banner", "-version"], PROBE_SECONDS).stdout.decode("utf-8", "replace").splitlines()[0]
    return Toolchain(str(ffmpeg), str(ffprobe), wanted[0], wanted[1], version)


def _run(argv: list[str], timeout: float, stdin=None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, timeout=timeout, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                          creationflags=_NO_WINDOW)


# --------------------------------------------------------------------------- #
# Reading a file
# --------------------------------------------------------------------------- #
def probe(tools: Toolchain, path: Path) -> dict:
    done = _run([tools.ffprobe, "-v", "error", "-show_format", "-show_streams", "-show_chapters", "-of", "json", str(path)],
                PROBE_SECONDS)
    if done.returncode != 0:
        raise OracleFailure(f"ffprobe refused {Path(path).name}: {done.stderr.decode('utf-8', 'replace').strip()[:400]}")
    return json.loads(done.stdout.decode("utf-8", "replace"))


def full_decode_errors(tools: Toolchain, path: Path) -> str:
    """Decode every audio sample to nowhere. Whatever FFmpeg says at error level, or a non-zero exit, is returned."""
    done = _run([tools.ffmpeg, "-hide_banner", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "null", "-"], DECODE_SECONDS)
    text = done.stderr.decode("utf-8", "replace").strip()
    return f"exit {done.returncode}: {text[:400]}" if done.returncode != 0 else text[:400]


def decode_pcm(tools: Toolchain, path: Path, rate: int = ORACLE_RATE) -> np.ndarray:
    """The whole file as mono float samples in -1..1, from a straight decode with no seeking."""
    import numpy as np

    done = _run([tools.ffmpeg, "-hide_banner", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(rate),
                 "-f", "s16le", "-"], DECODE_SECONDS)
    if done.returncode != 0:
        raise OracleFailure(f"{Path(path).name} did not decode: {done.stderr.decode('utf-8', 'replace').strip()[:400]}")
    return np.frombuffer(done.stdout, dtype="<i2").astype(np.float64) / 32768.0


def tags_of(probed: dict) -> dict[str, str]:
    """Container tags with their keys lower-cased. ffprobe's view is the authority for the product's tag contract."""
    return {str(key).lower(): str(value) for key, value in (probed.get("format", {}).get("tags") or {}).items()}


def audio_stream(probed: dict) -> dict:
    streams = [s for s in probed.get("streams", []) if s.get("codec_type") == "audio"]
    if len(streams) != 1:
        raise OracleFailure(f"expected one audio stream, found {len(streams)}")
    return streams[0]


def artwork_stream(probed: dict) -> dict | None:
    for stream in probed.get("streams", []):
        if stream.get("codec_type") == "video" and (stream.get("disposition") or {}).get("attached_pic") == 1:
            return stream
    return None


def extract_artwork(tools: Toolchain, path: Path, target: Path) -> bytes:
    """The attached picture's bytes as stored, stream-copied so nothing re-encodes what is being compared."""
    done = _run([tools.ffmpeg, "-hide_banner", "-v", "error", "-y", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "image2",
                 str(target)], PROBE_SECONDS)
    if done.returncode != 0:
        raise OracleFailure(f"no artwork could be read from {Path(path).name}: {done.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return Path(target).read_bytes()


def chapters_of(probed: dict) -> list[dict]:
    rows = []
    for chapter in probed.get("chapters", []):
        rows.append({"title": (chapter.get("tags") or {}).get("title", ""), "start": float(chapter["start_time"]),
                     "end": float(chapter["end_time"])})
    return rows


# --------------------------------------------------------------------------- #
# The signal
# --------------------------------------------------------------------------- #
def _power(samples: np.ndarray) -> float:
    import numpy as np

    return float(np.mean(samples * samples)) if samples.size else 0.0


def tone_power(samples: np.ndarray, rate: int, frequency: float) -> float:
    """Goertzel power of one frequency, normalised so a unit sine reads about 1 whatever the window's length."""
    count = samples.size
    if not count:
        return 0.0
    coefficient = 2.0 * math.cos(2.0 * math.pi * frequency / rate)
    previous = before = 0.0
    for value in samples.tolist():
        previous, before = value + coefficient * previous - before, previous
    return (previous * previous + before * before - coefficient * previous * before) * 4.0 / (count * count)


def tone_sequence(samples: np.ndarray, rate: int, candidates: list[float], *, window: float = 0.10, floor: float = 1e-3) -> list:
    """The strongest candidate frequency in each window, repeats collapsed; a window below ``floor`` reads as silence."""
    import numpy as np

    size = int(window * rate)
    sequence: list = []
    for start in range(0, max(0, samples.size - size + 1), size):
        chunk = samples[start:start + size]
        powers = [tone_power(chunk, rate, frequency) for frequency in candidates]
        best = int(np.argmax(powers))
        value = None if powers[best] < floor else candidates[best]
        if not sequence or sequence[-1] != value:
            sequence.append(value)
    return sequence


def _best_lag(reference: np.ndarray, candidate: np.ndarray, limit: int) -> tuple[int, float]:
    """The shift of ``candidate`` that best matches ``reference`` within +-``limit`` samples, and the correlation there."""
    import numpy as np

    span = min(reference.size, candidate.size, ORACLE_RATE * 4)
    if span < limit * 2 + 16:
        return 0, 0.0
    a, b = reference[:span], candidate[:span]
    size = int(2 ** math.ceil(math.log2(2 * span)))
    cross = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)
    lags = np.concatenate((cross[:limit + 1], cross[-limit:]))
    index = int(np.argmax(lags))
    lag = index if index <= limit else index - (2 * limit + 1)
    return lag, float(lags[index])


def compare_interval(reference: np.ndarray, candidate: np.ndarray, *, rate: int = ORACLE_RATE, limit: int = SEARCH_SAMPLES) -> dict:
    """How ``candidate`` compares with the exact source interval ``reference``. Never aligns beyond ``limit``.

    The whole-length correlation finds wrong, reordered or duplicated content; the edge energies find an attenuated start or a lost
    end, which a whole-length figure averages away; the length difference finds a short or padded output.
    """
    import numpy as np

    lag, _ = _best_lag(reference, candidate, limit)
    a = reference[max(0, -lag):]
    b = candidate[max(0, lag):]
    span = min(a.size, b.size)
    a, b = a[:span], b[:span]
    correlation = 0.0
    if span and _power(a) > 0 and _power(b) > 0:
        correlation = float(np.dot(a, b) / math.sqrt(float(np.dot(a, a)) * float(np.dot(b, b))))
    edge = int(EDGE_SECONDS * rate)

    def ratio(x: np.ndarray, y: np.ndarray) -> float:
        reference_power = _power(x)
        return 1.0 if reference_power < 1e-7 else _power(y) / reference_power

    return {"lag_samples": lag, "correlation": round(correlation, 4), "head_energy": round(ratio(a[:edge], b[:edge]), 3),
            "tail_energy": round(ratio(a[-edge:], b[-edge:]), 3), "length_difference_seconds":
            round((candidate.size - reference.size) / rate, 4)}


def interval_problems(metrics: dict, *, max_length_difference: float = 0.08, max_lag: int = MAX_LAG_SAMPLES) -> list[str]:
    problems = []
    if abs(metrics["lag_samples"]) > max_lag:
        problems.append(f"misplaced by {metrics['lag_samples']} samples, more than the calibrated {max_lag}")
    if metrics["correlation"] < MIN_CORRELATION:
        problems.append(f"waveform correlation {metrics['correlation']} is below {MIN_CORRELATION}")
    if not MIN_EDGE_ENERGY <= metrics["head_energy"] <= MAX_EDGE_ENERGY:
        problems.append(f"first {EDGE_SECONDS * 1000:.0f} ms energy ratio {metrics['head_energy']}")
    if not MIN_EDGE_ENERGY <= metrics["tail_energy"] <= MAX_EDGE_ENERGY:
        problems.append(f"last {EDGE_SECONDS * 1000:.0f} ms energy ratio {metrics['tail_energy']}")
    if abs(metrics["length_difference_seconds"]) > max_length_difference:
        problems.append(f"length differs by {metrics['length_difference_seconds']} s")
    return problems


# --------------------------------------------------------------------------- #
# A scenario's record of what it checked
# --------------------------------------------------------------------------- #
@dataclass
class Report:
    """Named checks with their facts, kept whether they pass or not. ``require`` stops at the first thing that cannot be built on."""

    checks: list[dict] = field(default_factory=list)
    outputs: list[dict] = field(default_factory=list)

    def check(self, name: str, passed: bool, detail="", **facts) -> bool:
        self.checks.append({"name": name, "ok": bool(passed), "detail": str(detail)[:600], **facts})
        return bool(passed)

    def require(self, name: str, passed: bool, detail="", **facts) -> None:
        if not self.check(name, passed, detail, **facts):
            raise OracleFailure(f"{name}: {detail}")

    def equal(self, name: str, found, expected) -> bool:
        return self.check(name, found == expected, f"found {found!r}, expected {expected!r}")

    @property
    def failed(self) -> list[dict]:
        return [check for check in self.checks if not check["ok"]]

    def record_output(self, path: Path, probed: dict | None = None) -> dict:
        entry = {"name": Path(path).name, "bytes": Path(path).stat().st_size, "sha256": _sha256(Path(path))}
        if probed is not None:
            entry["format"] = probed.get("format", {}).get("format_name")
            entry["duration"] = probed.get("format", {}).get("duration")
            entry["streams"] = [{key: stream.get(key) for key in ("codec_type", "codec_name", "sample_rate", "channels", "bit_rate")}
                                for stream in probed.get("streams", [])]
        self.outputs.append(entry)
        return entry


# --------------------------------------------------------------------------- #
# What an output must be
# --------------------------------------------------------------------------- #
def inspect_audio(tools: Toolchain, path: Path, report: Report, *, label: str, codec: str, container: str | None = None,
                  sample_rate: int | None = None, channels: int | None = None, duration: float | None = None,
                  duration_tolerance: float = 0.25, tags: dict | None = None, absent_tags=()) -> dict:
    """Valid container and codec, every sample decodes, the stated technical facts and tags. Returns the probe."""
    if not report.check(f"{label}: exists", Path(path).is_file() and Path(path).stat().st_size > 0, str(Path(path).name)):
        raise OracleFailure(f"{label}: {Path(path).name} does not exist or is empty")
    probed = probe(tools, path)
    report.record_output(path, probed)
    stream = audio_stream(probed)
    report.equal(f"{label}: codec", stream.get("codec_name"), codec)
    if container is not None:
        report.check(f"{label}: container", container in str(probed["format"].get("format_name")), probed["format"].get("format_name"))
    if sample_rate is not None:
        report.equal(f"{label}: sample rate", int(stream.get("sample_rate", 0)), sample_rate)
    if channels is not None:
        report.equal(f"{label}: channels", int(stream.get("channels", 0)), channels)
    errors = full_decode_errors(tools, path)
    report.check(f"{label}: every sample decodes", not errors, errors or "no decoder complaint")
    if duration is not None:
        # What decodes, never what a header claims. A truncated MP3 keeps its Xing header, so ffprobe still reads the full length and the
        # decoder has nothing to complain of: this very check let one through until its negative control said so.
        found = decode_pcm(tools, path).size / ORACLE_RATE
        claimed = float(probed["format"].get("duration", -1))
        report.check(f"{label}: duration", abs(found - duration) <= duration_tolerance,
                     f"{found:.3f} s decoded (the container claims {claimed:.3f} s), expected {duration:.3f} s within {duration_tolerance} s")
        report.check(f"{label}: the container's length is the audio's", abs(found - claimed) <= max(duration_tolerance, 0.1),
                     f"{claimed:.3f} s claimed, {found:.3f} s decoded")
    found_tags = tags_of(probed)
    for key, value in (tags or {}).items():
        report.equal(f"{label}: tag {key}", found_tags.get(key), value)
    for key in absent_tags:
        report.check(f"{label}: no tag {key}", key not in found_tags, found_tags.get(key, ""))
    return probed


def inspect_chapters(probed: dict, report: Report, *, label: str, expected: list[dict], tolerance: float = 0.05) -> None:
    """Exact count and titles, and each start and end within ``tolerance``. A container that drops one fails here, not later."""
    found = chapters_of(probed)
    report.equal(f"{label}: chapter count", len(found), len(expected))
    for index, (have, want) in enumerate(zip(found, expected), start=1):
        report.equal(f"{label}: chapter {index} title", have["title"], want["title"])
        report.check(f"{label}: chapter {index} start", abs(have["start"] - want["start"]) <= tolerance,
                     f"{have['start']:.3f}, expected {want['start']:.3f}")
        if "end" in want:
            report.check(f"{label}: chapter {index} end", abs(have["end"] - want["end"]) <= tolerance,
                         f"{have['end']:.3f}, expected {want['end']:.3f}")


def inspect_interval(report: Report, *, label: str, reference: np.ndarray, candidate: np.ndarray,
                     max_length_difference: float = 0.08, max_lag: int = MAX_LAG_SAMPLES) -> dict:
    metrics = compare_interval(reference, candidate)
    problems = interval_problems(metrics, max_length_difference=max_length_difference, max_lag=max_lag)
    report.check(f"{label}: signal matches its source interval", not problems, "; ".join(problems) or "within limits", **metrics)
    return metrics


def time_now() -> float:
    return time.monotonic()


def time_sleep(seconds: float) -> None:
    """A deliberate wait to see that nothing further happens, never a way of deciding that something did."""
    time.sleep(seconds)
