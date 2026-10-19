"""Using the one proven ffmpeg/ffprobe pair, and wiring it into pydub.

Which pair that is, and how it was proven, belongs to
:mod:`shared.ffmpeg_health`; this module is where the rest of the application
consumes it. v0.6.2 Plan 5 Phase 15 moved the decision there after a Windows
Smart App Control incident: resolution order alone had selected an installation
the machine refuses to execute, and nothing noticed until a real conversion
tried to run it.

It also configures :mod:`pydub` to use the resolved binaries. pydub shells out
to ffmpeg/ffprobe internally; pointing it at an explicit path means it never
depends on PATH and (combined with running the launcher under ``pythonw.exe``)
does not flash a console window on Windows.
"""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

from . import ffmpeg_health
from . import subprocess_utils as sp

_EXE = ".exe" if sys.platform == "win32" else ""


class FFmpegUnavailable(RuntimeError):
    """No proved, pinned ffmpeg + ffprobe pair is active on this machine.

    Raised by the command API rather than returning a bare name, because the
    caller is about to *execute* something and there is nothing safe to give it.
    A refusal a caller can see beats a command line that quietly runs whatever
    the PATH happens to contain.
    """


@lru_cache(maxsize=None)
def _executable_pair() -> tuple[str | None, str | None]:
    """The pair this process may actually **run**, or ``(None, None)``.

    Only ``ffmpeg_health.pinned_pair()`` — the installation that setup or repair
    executed, recorded durably, and whose files still match what was recorded.
    Nothing else qualifies.

    **This used to fall back to discovery**, taking the first coherent pair it
    found and marking it unverified, and callers then ran it anyway. That is the
    Phase 15 defect one step removed: coherence and resolvability are properties
    of paths, and the machine that started all of this had a perfectly coherent,
    perfectly resolvable pair that Windows refused to execute. A path is not a
    proof, so discovery is now observational only — see
    :func:`discovered_ffmpeg` — and never reaches an execution site.

    Cached; the answer cannot change under a running process without
    :func:`refresh`.
    """
    pinned = ffmpeg_health.pinned_pair()
    if pinned is None:
        return None, None
    return str(pinned.ffmpeg.as_path), str(pinned.ffprobe.as_path)


def refresh() -> None:
    """Forget the resolved pair. Call after setup pins a newly proven one."""
    global _pydub_configured
    _executable_pair.cache_clear()
    ffmpeg_path.cache_clear()
    ffprobe_path.cache_clear()
    _decoder_available.cache_clear()
    # pydub was pointed at whatever was resolved at the time; a new pin has to
    # be able to replace it, or the process keeps using the previous answer.
    _pydub_configured = False


@lru_cache(maxsize=None)
def ffmpeg_path() -> str | None:
    """Absolute path of the **pinned** ffmpeg, or ``None`` if none is active."""
    return _executable_pair()[0]


@lru_cache(maxsize=None)
def ffprobe_path() -> str | None:
    """Absolute path of the pinned ffprobe — always :func:`ffmpeg_path`'s sibling."""
    return _executable_pair()[1]


def have_ffmpeg() -> bool:
    """True when FFmpeg is usable: a proved, pinned pair is active.

    **This changed meaning deliberately.** It used to be satisfied by a coherent
    pair that had never been executed, which made "have" read like permission
    while proving nothing — and every consumer gate in the app was written
    against it. "Have" now means the same thing as
    :func:`verified_ffmpeg`, so a gate written against either name is safe.
    :func:`discovered_ffmpeg` is where the older, weaker question moved, under a
    name that cannot be mistaken for readiness.
    """
    return verified_ffmpeg()


def verified_ffmpeg() -> bool:
    """True only when the pair in use was **executed** successfully and pinned.

    The explicit strong name, and what consumer gates should say when they mean
    it. The distinction is the entire Phase 15 defect: a resolvable path proved
    nothing, and the first thing that ever ran ffprobe was a real conversion in
    front of the user.
    """
    return ffmpeg_path() is not None and ffprobe_path() is not None


def discovered_ffmpeg() -> bool:
    """True when a coherent pair merely *appears* to exist. Observational only.

    Deliberately named so it cannot be read as permission. It answers "is there
    something here?" for a status line, and nothing else may use it to decide
    whether to run anything. It executes nothing: enumeration only, so drawing a
    status line can never raise the Windows Security prompt that executing a
    blocked binary raises.
    """
    return next(iter(ffmpeg_health.discover_pairs()), None) is not None


def status_line() -> str:
    """One honest sentence about the audio tools, for a tool's own log.

    Three states, because there really are three, and the middle one was the
    lie: found is not ready. It is now *only* informational — nothing acts on
    it — and it says plainly that the tools are not usable yet.
    """
    if verified_ffmpeg():
        return "FFmpeg verified and ready."
    if discovered_ffmpeg():
        return ("FFmpeg was found but has not been verified on this computer, "
                "so the audio tools are not available yet.")
    return "FFmpeg is not available."


def ffmpeg_cmd() -> str:
    """Absolute ffmpeg path for a command line. Raises if none is pinned.

    **No bare-name fallback.** It used to return ``"ffmpeg"`` when nothing was
    resolved, which let a command line escape the health authority entirely and
    run whatever PATH offered — resolved independently of ffprobe, so the two
    halves need not even have been the same installation.
    """
    path = ffmpeg_path()
    if path is None:
        raise FFmpegUnavailable(
            "No verified FFmpeg is available on this computer yet.")
    return path


def ffprobe_cmd() -> str:
    """Absolute ffprobe path for a command line. Raises if none is pinned."""
    path = ffprobe_path()
    if path is None:
        raise FFmpegUnavailable(
            "No verified FFmpeg is available on this computer yet.")
    return path


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
    except FFmpegUnavailable:
        # Nothing proved to ask. "No decoders" is the honest answer, and the
        # caller's own gate is what decides whether that matters.
        return False
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


#: What pydub is pointed at when nothing is pinned: this package's own
#: directory, absolute and resolved.
#:
#: **It has to be an absolute path, and the reason is mechanical.** Process
#: creation treats a bare token — anything with no path separator — as a
#: *command name* and searches PATH for it. So a decorative sentinel like
#: ``"<no-verified-ffmpeg>"`` does not actually close the escape it was written
#: to close: it only happens to fail on Windows, where ``<`` and ``>`` cannot
#: appear in a filename. On macOS and Linux those are ordinary filename
#: characters, so a PATH directory may legally contain an executable with that
#: exact name, and pydub would run it. Relying on one platform's filename rules
#: is not an invariant. An absolute path is: there is nothing to search.
#:
#: **A directory rather than a nonexistent file**, because "no process API will
#: execute a directory" is a property of the operating system, while "this file
#: does not exist" is a property of the filesystem right now — one that anyone
#: could change by creating the file. This directory necessarily exists (the
#: module was imported from it) and necessarily is not an ffmpeg binary, on
#: every supported platform, with nothing written to disk to make it so.
UNVERIFIED_PYDUB_SENTINEL = str(Path(__file__).resolve().parent)


def configure_pydub() -> None:
    """Point pydub at the pinned ffmpeg/ffprobe, or at nothing usable.

    Safe to call repeatedly and safe to call when pydub is not installed (it
    simply does nothing). Call this once at tool/launcher startup, before any
    ``AudioSegment`` operation.

    **The unpinned case is the point.** pydub defaults to the bare names
    ``ffmpeg`` and ``ffprobe`` and shells out to whatever PATH resolves, so
    leaving it unconfigured was a way for audio work to escape the health
    authority entirely — the one route that no consumer gate in this
    application sits in front of. When nothing is pinned, pydub is therefore
    pointed at :data:`UNVERIFIED_PYDUB_SENTINEL` — an absolute path to a
    directory, which no process API will execute and which forces no PATH
    lookup on any supported platform. An operation that slips past a gate fails
    immediately, locally and visibly, instead of quietly running an
    installation nobody proved. :func:`refresh` clears this, so pinning a pair
    mid-session replaces the sentinel with the real thing.
    """
    global _pydub_configured
    if _pydub_configured:
        return
    ff = ffmpeg_path() or UNVERIFIED_PYDUB_SENTINEL
    fp = ffprobe_path() or UNVERIFIED_PYDUB_SENTINEL
    try:
        from pydub import AudioSegment
        from pydub import utils as pydub_utils

        AudioSegment.converter = ff
        AudioSegment.ffmpeg = ff
        AudioSegment.ffprobe = fp
        # pydub probes media via ffprobe; pin the name so it does not re-scan
        # PATH (and so it uses our proved copy when there is one).
        pydub_utils.get_prober_name = lambda: fp  # type: ignore[assignment]
    except Exception:
        # pydub not importable (e.g. running a non-TTS tool) — nothing to do.
        pass
    _pydub_configured = True
