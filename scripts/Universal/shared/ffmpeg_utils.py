"""Locating ffmpeg/ffprobe and wiring them into pydub.

The bootstrap may install ffmpeg system-wide (winget / Homebrew) or drop a
portable build into ``files/bin/``. This module resolves whichever is
available, preferring the bundled portable build so the app behaves the same
regardless of what is on the user's PATH.

It also configures :mod:`pydub` to use the resolved binaries. pydub shells out
to ffmpeg/ffprobe internally; pointing it at an explicit path means it never
depends on PATH and (combined with running the launcher under ``pythonw.exe``)
does not flash a console window on Windows.
"""

from __future__ import annotations

import re
import shutil
import sys
from functools import lru_cache
from pathlib import Path

from . import paths
from . import subprocess_utils as sp

_EXE = ".exe" if sys.platform == "win32" else ""


def _find(binary: str) -> str | None:
    """Return a path to ``binary``, preferring the bundled portable build.

    Order: ``files/bin/`` (bundled) → system PATH. Returns ``None`` if the
    binary cannot be found anywhere.
    """
    bundled = paths.BIN_DIR / f"{binary}{_EXE}"
    if bundled.exists():
        return str(bundled)
    found = shutil.which(binary)
    return found


@lru_cache(maxsize=None)
def ffmpeg_path() -> str | None:
    """Resolved path to the ffmpeg binary, or ``None`` if unavailable."""
    return _find("ffmpeg")


@lru_cache(maxsize=None)
def ffprobe_path() -> str | None:
    """Resolved path to the ffprobe binary, or ``None`` if unavailable."""
    return _find("ffprobe")


def have_ffmpeg() -> bool:
    """True when both ffmpeg and ffprobe are resolvable."""
    return ffmpeg_path() is not None and ffprobe_path() is not None


def ffmpeg_cmd() -> str:
    """ffmpeg path for building command lists; falls back to the bare name."""
    return ffmpeg_path() or "ffmpeg"


def ffprobe_cmd() -> str:
    """ffprobe path for building command lists; falls back to the bare name."""
    return ffprobe_path() or "ffprobe"


# --------------------------------------------------------------------------- #
# Source probing + decoder selection
#
# Some audiobook M4B sources use **xHE-AAC** (USAC). ffmpeg's *native* ``aac``
# decoder cannot decode xHE-AAC: it logs "Error submitting packet to decoder:
# Not yet implemented in FFmpeg, patches welcome" and silently drops a large
# fraction of packets, so the decoded audio is much shorter than the source —
# re-encoded to MP3 it plays sped up and choppy. On macOS the Apple AudioToolbox
# decoder (``aac_at``) decodes xHE-AAC correctly, so we force it for such sources
# when it is available. The selection happens at runtime (decoder availability),
# so this single cross-platform module needs no per-OS variants.
# --------------------------------------------------------------------------- #


def probe_audio_stream(path) -> dict | None:
    """Read the first audio stream's parameters via ffprobe.

    Returns a dict with ``codec_name``/``profile``/``channel_layout`` (str|None),
    ``sample_rate``/``channels`` (int|None) and ``duration`` (float|None), or
    ``None`` if ffprobe is unavailable or fails. Never raises — safe to call from
    a worker thread without crashing the GUI. The subprocess is routed through
    :mod:`shared.subprocess_utils` so no console window flashes on Windows.
    """
    try:
        out = sp.check_output(
            [
                ffprobe_cmd(),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,profile,sample_rate,channels,channel_layout,duration",
                "-of",
                "default=noprint_wrappers=1",
                str(path),
            ],
            text=True,
        )
    except Exception:
        return None

    info: dict = {
        "codec_name": None,
        "profile": None,
        "sample_rate": None,
        "channels": None,
        "channel_layout": None,
        "duration": None,
    }
    for line in str(out).splitlines():
        key, sep, val = line.partition("=")
        if not sep:
            continue
        val = val.strip()
        if val in ("", "N/A", "unknown"):
            continue
        if key in ("sample_rate", "channels"):
            try:
                info[key] = int(val)
            except ValueError:
                pass
        elif key == "duration":
            try:
                info[key] = float(val)
            except ValueError:
                pass
        elif key in info:
            info[key] = val
    return info


def is_xhe_aac(info: dict | None) -> bool:
    """True when the probed stream is xHE-AAC (USAC).

    ffmpeg's native ``aac`` decoder mis-decodes this profile (dropping packets,
    producing a shortened/sped-up result).
    """
    if not info:
        return False
    profile = (info.get("profile") or "").lower()
    return "xhe" in profile or "usac" in profile


@lru_cache(maxsize=None)
def _decoder_available(name: str) -> bool:
    """True when ffmpeg lists ``name`` among its available decoders.

    Cached: the decoder set does not change during a run. ``aac_at`` (Apple
    AudioToolbox) is present on macOS only, which is what makes the xHE-AAC fix
    a runtime decision rather than a per-platform code fork.
    """
    try:
        out = sp.check_output([ffmpeg_cmd(), "-hide_banner", "-decoders"], text=True)
    except Exception:
        return False
    # Entries look like: " A....D aac_at  aac (AudioToolbox) ...". The decoder
    # name is the first token after the 6-char capability flags column.
    pat = re.compile(r"^\s*[A-Z.]{6}\s+(\S+)")
    for line in str(out).splitlines():
        m = pat.match(line)
        if m and m.group(1) == name:
            return True
    return False


def input_decoder_args(info: dict | None) -> list[str]:
    """ffmpeg *input* options (placed before ``-i``) to decode a source robustly.

    For an xHE-AAC source, returns ``["-c:a", "aac_at"]`` when the Apple
    AudioToolbox decoder is available (macOS), so the stream decodes correctly.
    Returns ``[]`` when the default decoder is fine, or when no better decoder is
    available on this platform (e.g. Windows) — in the latter case the caller
    should warn the user (see :func:`needs_special_aac_decoder`).
    """
    if is_xhe_aac(info) and _decoder_available("aac_at"):
        return ["-c:a", "aac_at"]
    return []


def needs_special_aac_decoder(info: dict | None) -> bool:
    """True when the source is xHE-AAC but no capable decoder exists here.

    In that case ffmpeg's native decoder will mis-decode it (sped-up output);
    the caller should surface a clear warning.
    """
    return is_xhe_aac(info) and not _decoder_available("aac_at")


# --------------------------------------------------------------------------- #
# The final MP3 encoding contract
#
# pydub's ``DEFAULT_CODECS`` maps only ``ogg``. Exporting ``format="mp3"`` with
# nothing else therefore runs ``ffmpeg -f wav -i … -f mp3 out.mp3`` with **no
# encoder and no bitrate**, leaving the contract to whatever the local ffmpeg
# defaults to. On this project's build that is 32 kbps for a 24 kHz mono stream,
# and that low bitrate is what broke player-reported duration.
#
# The mechanism is exact and was measured, not guessed. A Xing/Info header needs
# room for a 100-byte seek table, which does not fit inside a 32 kbps MPEG-2
# frame (96 bytes), so ffmpeg is forced to emit that one header frame at 64 kbps
# while every audio frame stays at 32 — and still marks the file ``Info``, which
# declares constant bitrate. A player that believes the CBR declaration and reads
# the bitrate off the first frame computes a duration **exactly half** the truth.
# ffprobe and mutagen read the Xing frame count instead, which is why they always
# looked right and the defect reached shipped audio.
#
# Encoding at 64 kbps or above makes the header frame and the audio frames agree,
# and the reported duration becomes correct in every parser tested. Measured with
# Windows Media Foundation on a 2:00 fixture: 1:50 at 24 kbps, 1:54 at 32, 1:58 at
# 48, and exactly 2:00 from 64 kbps upward.
# --------------------------------------------------------------------------- #

#: The encoder every final MP3 is written with. Named explicitly for the same
#: reason the bitrate is: so the output does not depend on which encoder a
#: particular ffmpeg build happens to select for the mp3 muxer.
FINAL_MP3_CODEC = "libmp3lame"

#: Used when a caller supplies nothing. Deliberately the same value the TTS
#: panel's "MP3 bitrate" control already defaults to, so the contract and the
#: control the user actually sees cannot drift apart.
DEFAULT_MP3_BITRATE = "192k"


def mp3_export_options(bitrate: str | None = None) -> dict:
    """The pydub ``export`` keywords that pin the final MP3 contract.

    Returned as keywords rather than performed here so the encode stays where the
    audio is, and so a test can assert the contract without running ffmpeg.

    ``bitrate`` is the run's chosen value — the panel offers 128k/192k/320k, all
    of them safely above the 64 kbps threshold described above. Anything falsy
    falls back to :data:`DEFAULT_MP3_BITRATE`, so a caller that has no opinion
    still gets an explicit contract rather than ffmpeg's default.

    Sample rate and channel count are deliberately **absent**: each engine's own
    output is already correct for speech (24 kHz mono for the local engines), and
    resampling or expanding it to stereo would add cost and loss for no benefit.
    """
    return {
        "format": "mp3",
        "codec": FINAL_MP3_CODEC,
        "bitrate": bitrate or DEFAULT_MP3_BITRATE,
    }


_pydub_configured = False


def configure_pydub() -> None:
    """Point pydub at the resolved ffmpeg/ffprobe binaries.

    Safe to call repeatedly and safe to call when pydub is not installed (it
    simply does nothing). Call this once at tool/launcher startup, before any
    ``AudioSegment`` operation.
    """
    global _pydub_configured
    if _pydub_configured:
        return
    ff = ffmpeg_path()
    fp = ffprobe_path()
    try:
        from pydub import AudioSegment
        from pydub import utils as pydub_utils

        if ff:
            AudioSegment.converter = ff
            AudioSegment.ffmpeg = ff
        if fp:
            AudioSegment.ffprobe = fp
            # pydub probes media via ffprobe; pin the name so it does not
            # re-scan PATH (and so it uses our bundled copy when present).
            pydub_utils.get_prober_name = lambda: fp  # type: ignore[assignment]
    except Exception:
        # pydub not importable (e.g. running a non-TTS tool) — nothing to do.
        pass
    _pydub_configured = True
