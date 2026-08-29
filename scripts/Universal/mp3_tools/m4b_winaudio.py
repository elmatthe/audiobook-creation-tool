"""Decoding an audiobook through Windows Media Foundation, when ffmpeg cannot.

**Why this module exists.** v0.6.2 Plan 5 Phase 15 measured ffmpeg 9.0.1's native
AAC decoder against a real xHE-AAC (MPEG-D USAC) audiobook and found it silently
incomplete: 362,465 of the source's 1,515,928 frames are refused with *"Not yet
implemented in FFmpeg, patches welcome"*, so **23.91 % of the audio never
arrives**. The surviving frames are concatenated into an MP3 that is 76.09 % as
long -- 26,783 s against a planned 35,200 s -- and riddled with roughly 362,000
excisions rather than merely short at one end. ffmpeg exits 0 throughout. Only
the drift guard stopped it reaching a listener.

Windows 11 ships an xHE-AAC decoder of its own. Driven through
``IMFSourceReader`` it delivers **35,199.78 s of that same book -- 100.0004 % of
the source** -- at roughly 385x realtime.

**Why ctypes and not a package.** ``mfplat`` and ``mfreadwrite`` are part of
Windows, and ``ctypes`` is part of Python. Nothing is downloaded, installed, or
redistributed, and no Smart App Control question arises -- which is precisely
what disqualified the alternative (an FDK-AAC ffmpeg build cannot be
redistributed under this project's GPL-3.0 terms at all).

**Why the reader and not MediaTranscoder.** ``MediaTranscoder`` also decodes this
book correctly, but only into a file, and this source is **6.2 GB** of PCM.
Chunking it was measured and rejected: decoding ``[600,1200)`` in one span yields
26,452,025 frames while ``[600,900) + [900,1200)`` yields 26,443,970 -- every
seek loses **8,055 frames (0.183 s)** of real audio to decoder priming. The
reader is a *pull* interface instead: it decodes strictly sequentially, so
nothing is primed away, and it hands back one small buffer at a time -- measured
peak **4,096 bytes** -- so the 6.2 GB flows through the pipe and is never stored.

Everything here is Windows-only and fails closed everywhere else.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Callable, Iterator

IS_WINDOWS = sys.platform.startswith("win")

S_OK = 0
#: MF_SDK_VERSION << 16 | MF_API_VERSION.
MF_VERSION = (0x0002 << 16) | 0x0070
MF_SOURCE_READER_FIRST_AUDIO_STREAM = 0xFFFFFFFD
MF_SOURCE_READERF_ENDOFSTREAM = 0x2
MF_SOURCE_READERF_ERROR = 0x1

#: How much decoded audio to hand upward at once. The reader's own buffers are
#: ~4 KB; batching them keeps the number of pipe writes sane without ever
#: holding a meaningful amount of a ten-hour book in memory.
CHUNK_BYTES = 1 << 18  # 256 KiB


class DecodeError(RuntimeError):
    """Media Foundation could not decode this source. Never a silent shortfall."""


@dataclass(frozen=True)
class PcmFormat:
    """The uncompressed format the decoder negotiated.

    Read back from the reader rather than assumed, because the sample maths that
    proves a complete decode has to be done against what actually arrived.
    """

    sample_rate: int
    channels: int
    bits: int

    @property
    def frame_bytes(self) -> int:
        return max(1, (self.channels * self.bits) // 8)

    def seconds_for(self, byte_count: int) -> float:
        return (byte_count // self.frame_bytes) / float(self.sample_rate)

    def ffmpeg_input_args(self) -> list[str]:
        """How ffmpeg should be told to read this on stdin."""
        return ["-f", f"s{self.bits}le",
                "-ar", str(self.sample_rate),
                "-ac", str(self.channels)]


# --------------------------------------------------------------------------- #
# The thin COM layer
# --------------------------------------------------------------------------- #


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    value = _GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(value))
    return value


#: Resolved lazily so importing this module on macOS costs nothing and raises
#: nothing -- every caller is expected to ask :func:`available` first.
_GUIDS: dict = {}


def _guids() -> dict:
    if not _GUIDS:
        _GUIDS.update({
            "audio": _guid("{73647561-0000-0010-8000-00AA00389B71}"),
            "pcm": _guid("{00000001-0000-0010-8000-00AA00389B71}"),
            "major": _guid("{48EBA18E-F8C9-4687-BF11-0A74C9F96A8F}"),
            "subtype": _guid("{F7E34C9A-42E8-4714-B74B-CB29D72C35E5}"),
            "bits": _guid("{F2DEB57F-40FA-4764-AA33-ED4F2D1FF669}"),
            "rate": _guid("{5FAEEAE7-0290-4C31-9E8A-C534F68D9DBA}"),
            "channels": _guid("{37E48BF5-645E-4C5B-89DE-ADA9E29B696A}"),
        })
    return _GUIDS


def _method(pointer, index: int, restype, *argtypes):
    """Bind one vtable slot on a COM interface pointer.

    The indices are the documented layouts and are written down beside each use,
    because getting one wrong does not fail loudly -- it calls a *different*
    method. During development an off-by-two here called ``SetUINT64`` in place
    of ``SetGUID`` and surfaced only as ``E_INVALIDARG`` three calls later.
    """
    table = ctypes.cast(pointer,
                        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])


def _release(pointer) -> None:
    if pointer:
        _method(pointer, 2, ctypes.c_ulong)(pointer)  # IUnknown::Release


def _check(hr: int, what: str) -> None:
    if hr != S_OK:
        raise DecodeError(f"{what} failed: HRESULT 0x{hr & 0xFFFFFFFF:08X}")


# --------------------------------------------------------------------------- #
# Capability
# --------------------------------------------------------------------------- #


def _probe_capability() -> bool:
    """Ask Windows whether the media stack is actually usable here.

    Deliberately **not** a version comparison. Windows N and KN editions ship
    without the media feature pack, media components can be removed or disabled
    by policy, and a build number would cheerfully claim a decoder that is not
    installed. Loading the libraries and starting Media Foundation is the
    question that actually matters, and it costs microseconds.
    """
    if not IS_WINDOWS:
        return False
    try:
        mfplat = ctypes.windll.mfplat
        ctypes.windll.mfreadwrite  # noqa: B018 - presence is the assertion
        ctypes.windll.ole32.CoInitializeEx(None, 0)
        if mfplat.MFStartup(MF_VERSION, 0) != S_OK:
            return False
        mfplat.MFShutdown()
        return True
    except (OSError, AttributeError):
        return False


_CAPABILITY: bool | None = None


def available() -> bool:
    """True when this machine can decode through Media Foundation.

    Cached, because the answer cannot change under a running process and the
    selection has to be frozen into a plan anyway. :func:`reset_capability` is
    for tests.
    """
    global _CAPABILITY
    if _CAPABILITY is None:
        _CAPABILITY = _probe_capability()
    return _CAPABILITY


def reset_capability() -> None:
    """Forget the cached answer. Tests only."""
    global _CAPABILITY
    _CAPABILITY = None


def unavailable_message() -> str:
    """What to tell someone whose Windows cannot do this.

    Names no download and no security setting to change, because there is no
    honest one to name: an FDK-AAC build cannot be redistributed under this
    project's licence, and nothing a user switches off would help.
    """
    return ("This audiobook uses xHE-AAC audio that this Windows installation "
            "cannot decode completely. No output was created and the source was "
            "left unchanged.")


# --------------------------------------------------------------------------- #
# Decoding
# --------------------------------------------------------------------------- #


class _Reader:
    """One open ``IMFSourceReader``, negotiated to PCM. Always released."""

    def __init__(self, path) -> None:
        self._reader = None
        self._media_type = None
        self._current = None
        self._started = False
        g = _guids()

        mfplat = ctypes.windll.mfplat
        ctypes.windll.ole32.CoInitializeEx(None, 0)
        _check(mfplat.MFStartup(MF_VERSION, 0), "MFStartup")
        self._started = True

        reader = ctypes.c_void_p()
        _check(ctypes.windll.mfreadwrite.MFCreateSourceReaderFromURL(
            ctypes.c_wchar_p(str(path)), None, ctypes.byref(reader)),
            "MFCreateSourceReaderFromURL")
        self._reader = reader

        # Ask for uncompressed PCM; the reader inserts the decoder itself.
        media_type = ctypes.c_void_p()
        _check(mfplat.MFCreateMediaType(ctypes.byref(media_type)),
               "MFCreateMediaType")
        self._media_type = media_type
        # IMFAttributes::SetGUID is vtable slot 24.
        set_guid = _method(media_type, 24, ctypes.c_long,
                           ctypes.POINTER(_GUID), ctypes.POINTER(_GUID))
        _check(set_guid(media_type, ctypes.byref(g["major"]),
                        ctypes.byref(g["audio"])), "SetGUID(major type)")
        _check(set_guid(media_type, ctypes.byref(g["subtype"]),
                        ctypes.byref(g["pcm"])), "SetGUID(subtype)")

        # IMFSourceReader::SetCurrentMediaType is slot 7.
        set_current = _method(reader, 7, ctypes.c_long, ctypes.c_uint32,
                              ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p)
        _check(set_current(reader, MF_SOURCE_READER_FIRST_AUDIO_STREAM, None,
                           media_type), "SetCurrentMediaType")

        # Read the negotiated format back rather than assuming it.
        current = ctypes.c_void_p()
        get_current = _method(reader, 6, ctypes.c_long, ctypes.c_uint32,
                              ctypes.POINTER(ctypes.c_void_p))
        _check(get_current(reader, MF_SOURCE_READER_FIRST_AUDIO_STREAM,
                           ctypes.byref(current)), "GetCurrentMediaType")
        self._current = current

        # IMFAttributes::GetUINT32 is slot 7.
        get_uint32 = _method(current, 7, ctypes.c_long,
                             ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_uint32))

        def value(key: str) -> int:
            out = ctypes.c_uint32()
            if get_uint32(current, ctypes.byref(g[key]), ctypes.byref(out)) != S_OK:
                raise DecodeError(f"the decoder did not report its {key}")
            return int(out.value)

        self.format = PcmFormat(sample_rate=value("rate"),
                                channels=value("channels"), bits=value("bits"))

        # IMFSourceReader::ReadSample is slot 9.
        self._read_sample = _method(
            reader, 9, ctypes.c_long, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_longlong), ctypes.POINTER(ctypes.c_void_p))

    def read(self) -> bytes | None:
        """The next decoded buffer, or ``None`` at end of stream."""
        flags = ctypes.c_uint32()
        stream = ctypes.c_uint32()
        timestamp = ctypes.c_longlong()
        sample = ctypes.c_void_p()
        hr = self._read_sample(self._reader, MF_SOURCE_READER_FIRST_AUDIO_STREAM,
                               0, ctypes.byref(stream), ctypes.byref(flags),
                               ctypes.byref(timestamp), ctypes.byref(sample))
        if hr != S_OK:
            raise DecodeError(f"ReadSample failed: HRESULT 0x{hr & 0xFFFFFFFF:08X}")
        if flags.value & MF_SOURCE_READERF_ERROR:
            raise DecodeError("the media source reported an error mid-stream")
        if flags.value & MF_SOURCE_READERF_ENDOFSTREAM:
            return None
        if not sample.value:
            return b""  # a gap or a format change, not the end

        payload = b""
        buffer = ctypes.c_void_p()
        try:
            # IMFSample::ConvertToContiguousBuffer is slot 41 (it inherits the
            # 33 IMFAttributes slots first).
            convert = _method(sample, 41, ctypes.c_long,
                              ctypes.POINTER(ctypes.c_void_p))
            if convert(sample, ctypes.byref(buffer)) == S_OK and buffer.value:
                # IMFMediaBuffer: 3 Lock, 4 Unlock.
                lock = _method(buffer, 3, ctypes.c_long,
                               ctypes.POINTER(ctypes.POINTER(ctypes.c_byte)),
                               ctypes.POINTER(ctypes.c_uint32),
                               ctypes.POINTER(ctypes.c_uint32))
                unlock = _method(buffer, 4, ctypes.c_long)
                data = ctypes.POINTER(ctypes.c_byte)()
                maximum = ctypes.c_uint32()
                current = ctypes.c_uint32()
                if lock(buffer, ctypes.byref(data), ctypes.byref(maximum),
                        ctypes.byref(current)) == S_OK:
                    try:
                        payload = ctypes.string_at(data, current.value)
                    finally:
                        unlock(buffer)
        finally:
            _release(buffer)
            _release(sample)
        return payload

    def close(self) -> None:
        _release(self._current)
        _release(self._media_type)
        _release(self._reader)
        self._current = self._media_type = self._reader = None
        if self._started:
            try:
                ctypes.windll.mfplat.MFShutdown()
            except OSError:
                pass
            self._started = False

    def __enter__(self) -> "_Reader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def decode_pcm(
    source,
    *,
    cancelled: Callable[[], bool] | None = None,
    chunk_bytes: int = CHUNK_BYTES,
    reader_factory=None,
) -> Iterator[bytes]:
    """Yield the source's audio as PCM, sequentially, in bounded chunks.

    The first item is **always** the negotiated :class:`PcmFormat`; every item
    after it is ``bytes``. Callers need the format before the first byte because
    it is what tells ffmpeg how to read the pipe.

    Strictly sequential: no seeking, because seeking costs 0.183 s of primed
    audio per jump. A split run therefore decodes **once** and cuts the PCM at
    frozen chapter boundaries rather than asking the decoder for spans.

    *cancelled* is polled between samples -- the same latch the executor already
    uses -- so a cancel is honoured within one ~46 ms buffer and the reader is
    released on the way out.
    """
    if not IS_WINDOWS and reader_factory is None:
        raise DecodeError("Media Foundation decoding is Windows-only")
    make = reader_factory or _Reader
    reader = make(source)
    try:
        yield reader.format
        pending = bytearray()
        while True:
            if cancelled is not None and cancelled():
                return
            block = reader.read()
            if block is None:
                break
            pending += block
            while len(pending) >= chunk_bytes:
                yield bytes(pending[:chunk_bytes])
                del pending[:chunk_bytes]
        if pending:
            yield bytes(pending)
    finally:
        reader.close()


class PcmTimeline:
    """One sequential decode, served out to an item's outputs in frozen order.

    **Why a split book decodes exactly once.** Asking the decoder for each
    chapter separately was measured and rejected: ``[600,1200)`` in one span
    yields 26,452,025 frames, while ``[600,900) + [900,1200)`` yields
    26,443,970 -- every seek discards **8,055 frames (0.183 s)** of real audio to
    decoder priming. Fifteen chapters would silently lose fifteen fragments of a
    book, which is a quieter version of the very defect this path exists to fix.

    So the decoder runs once, start to finish, and this hands each output the
    exact byte count its frozen span calls for. Segments are already produced in
    frozen plan order, so a cursor is all that is required -- no seeking, no
    buffering of anything beyond one chunk.

    A short read is **never** padded or ignored. :meth:`feed` reports how much it
    actually delivered and the caller compares that against what the plan asked
    for; the drift guard then sees a real shortfall rather than a silence.
    """

    def __init__(self, source, *, cancelled=None, decoder=None) -> None:
        self._stream = (decoder or decode_pcm)(source, cancelled=cancelled)
        self.format: PcmFormat = next(self._stream)
        self._pending = bytearray()
        self._exhausted = False
        #: Bytes handed out so far, across every output of this item.
        self.delivered = 0

    def bytes_for(self, seconds: float) -> int:
        """How many bytes one span of the timeline occupies, frame-aligned."""
        frames = int(round(float(seconds) * self.format.sample_rate))
        return frames * self.format.frame_bytes

    def _pull(self) -> bool:
        if self._exhausted:
            return False
        try:
            self._pending += next(self._stream)
            return True
        except StopIteration:
            self._exhausted = True
            return False

    def feed(self, write, byte_count: int | None = None) -> int:
        """Push the next *byte_count* bytes (or the rest) into *write*.

        Returns the number of bytes actually delivered, which is the only honest
        answer when a decode ends early.
        """
        sent = 0
        while byte_count is None or sent < byte_count:
            if not self._pending and not self._pull():
                break
            if byte_count is None:
                block = bytes(self._pending)
                del self._pending[:]
            else:
                take = min(len(self._pending), byte_count - sent)
                block = bytes(self._pending[:take])
                del self._pending[:take]
            if not block:
                continue
            write(block)
            sent += len(block)
        self.delivered += sent
        return sent

    def close(self) -> None:
        self._exhausted = True
        try:
            self._stream.close()
        except Exception:  # noqa: BLE001 - closing must never mask a real failure
            pass

    def __enter__(self) -> "PcmTimeline":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
