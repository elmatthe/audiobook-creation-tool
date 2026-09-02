"""The ffmpeg argument vectors the M4B Converter runs — built here, never executed.

**The seek ordering below was measured, and it must not be "simplified".** The
obvious optimisation — moving ``-ss`` in front of ``-i`` so ffmpeg can jump
straight to the requested position instead of decoding its way there — is
roughly a hundred times faster and it silently corrupts the audio. It was tested
on a deterministic fixture whose decoded content identifies its own source time,
across a real chapter-start partition, on two different ffmpeg builds:

* **input-side seek** (``-ss`` before ``-i``) lost source audio at the head of
  five of six segments. On the FFmpeg nightly it emitted 2.1 ms of hard digital
  silence at ``-ss 0`` and attenuated the first 10–20 ms of every later segment
  to as little as a quarter amplitude, *while reporting an exactly correct
  duration*. On FFmpeg 9.0 the same shape instead skipped ~21–24 ms outright and
  reported durations 3–12 ms short. Both builds lost the marker at source second
  0 entirely.
* **output-side seek** (``-ss`` after ``-i``) reproduced the source at every
  boundary of every segment to 3–4 decimal places, tiled ``[0, D]`` exactly with
  no second lost or duplicated, and held a duration error at or below 0.01 ms —
  **identically on both builds**.

The first failure mode is the dangerous one: the output *duration* is right, so
no drift guard at any tolerance could ever detect it. It is also build-dependent,
which is the second reason this ordering is pinned — the rejected shape changed
its failure between two ffmpeg versions while the selected shape did not move.

The cause is AAC decoder priming. Seeking on the input side starts decoding at a
packet boundary with no preceding frame for the MDCT overlap, so the first frames
emerge ramped or are dropped. Seeking on the output side decodes from the true
beginning and discards, so every sample that survives is fully reconstructed.

The cost of that correctness was measured too: about **1.55 s of wall clock per
hour of preceding audio** (17.12 s at 11.00 h, 35.79 s at 23.16 h — linear). For
a 47-chapter split of a 24.6-hour audiobook that is ~14 min of seeking on top of
the ~6 min of encoding that has to happen regardless. Accepted: it is under one
percent of the book's own playing time, and the faster shape is not a viable
alternative because it is wrong.

``-t (end - start)`` is used rather than an absolute ``-to end``. With
output-side seek the two are equivalent and measured identically, so the tie is
broken by the failure mode when they are *not* equivalent: combined with an
input-side seek, ``-to`` is re-read against the shifted timeline, and a requested
20 s span of a real audiobook produced a 425 MB, 11-hour file. An explicit
duration cannot be reinterpreted that way by any ordering.

Pure: values in, ``list[str]`` out. This module runs nothing, probes nothing,
reads no configuration, resolves no decoder, and touches no filesystem. It does
not import ``shared`` — the ffmpeg path and the decoder arguments are handed to
it already resolved, which is what keeps it testable without a subprocess.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: The MP3 encoder the Converter writes with.
#:
#: Deliberately a local literal and **not** ``ffmpeg_utils.FINAL_MP3_CODEC``.
#: That constant belongs to the TTS finalisation contract, which pins a constant
#: *bitrate* for a reason specific to how players read a Xing header. The
#: Converter's contract is VBR quality, chosen by the user. The two happen to
#: name the same encoder today; binding them together would mean a change to the
#: TTS bitrate contract silently became a change to the Converter's.
_ENCODER = "libmp3lame"

#: ``libmp3lame`` VBR quality: 0 is best, 9 is smallest.
_QUALITY_RANGE = range(0, 10)

#: Timestamps are rendered fixed-point to microseconds. Fixed-point, because
#: ``str(1e-7)`` is ``'1e-07'`` and ffmpeg's time parser should never be handed
#: exponent notation; microseconds, because it is far finer than any boundary
#: this tool can express and coarse enough to stay exact in the output.
_TIME_FORMAT = "{:.6f}"


def _seconds(value: float, label: str) -> str:
    """Render a timestamp for the command line, refusing nonsense."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite, got {value!r}")
    if number < 0:
        raise ValueError(f"{label} must not be negative, got {value!r}")
    return _TIME_FORMAT.format(number)


def _arguments(values: Sequence[str], label: str) -> list[str]:
    """Copy a caller-supplied argument run, rejecting non-strings.

    Stringifying quietly would let a ``None`` reach the command line as the
    four characters ``None``, which ffmpeg would accept as a filename.
    """
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{label} must be a sequence of strings, not {type(values).__name__}")
    out = list(values)
    for entry in out:
        if not isinstance(entry, str):
            raise TypeError(f"every {label} entry must be str, got {type(entry).__name__}")
    return out


def _media_args(attached_picture: int | None) -> list[str]:
    """Which source streams reach the output.

    Default is ``-vn``: audio only, which is what a converted audiobook normally
    wants and what every command here emitted before artwork existed.

    Given a stream index, the audio and *that one stream* are mapped instead and
    the picture is stream-copied — never re-encoded. The index is **absolute**
    rather than ``v:``-relative on purpose: a source can carry an ordinary video
    track ahead of its cover, and ``-map 0:v:0`` would then select the wrong one.
    Deciding which stream qualifies is not this module's job; it is handed the
    answer.

    **The picture is mapped from input 1, and that is not an accident.** The
    book is opened twice — once for audio and chapters, once purely as the
    cover's source — and reading the picture out of the *same* input being
    decoded is what v0.6.2 Plan 5 Phase 15 measured as catastrophic. See
    :func:`_core` for the evidence. ``0:{index}`` here would restore the defect,
    so this file's tests pin ``1:{index}`` explicitly.
    """
    if attached_picture is None:
        return ["-vn"]
    return [
        "-map", "0:a:0",
        "-map", f"1:{attached_picture}",
        "-c:v", "copy",
        "-disposition:v:0", "attached_pic",
    ]


def _core(
    *,
    ffmpeg: str,
    source: str,
    destination: str,
    quality: int,
    decoder_args: Sequence[str],
    output_args: Sequence[str],
    seek: tuple[str, str] | None,
    attached_picture: int | None = None,
) -> list[str]:
    """The one place the argument order lives, for both shapes.

    **Why a cover means the book is opened twice.** v0.6.2 Plan 5 Phase 15
    measured this against the real 13.5-hour source: mapping the attached picture
    out of the *same* input whose audio is being decoded makes ffmpeg exit **0**
    after encoding a handful of audio frames. The observed artifact was a 600 KB
    "audiobook" holding 0.32 seconds of audio and the cover, reported as success.
    A controlled matrix isolated it exactly — audio alone passed, audio plus
    chapters passed, and *only* the same-input picture truncated — and the
    boundary is source length: below roughly 50 minutes nothing goes wrong, at 55
    minutes and beyond it always does. That is why the suite's six-second fixture
    never saw it.

    Opening the same file a second time purely as the cover's source fixes it,
    and was proven on the full book: 743 MB, duration exact to the source, all 50
    chapters and the cover intact, audio encoded once. It stays **one** command,
    so a whole book is still a single pass.

    This is deliberately *not* recorded as an ffmpeg 9.0.1 regression: no
    evidence establishes when the behaviour began, and the coverage gap alone
    explains why it was never seen. Do not "simplify" the second input away.
    """
    if not isinstance(ffmpeg, str) or not ffmpeg:
        raise ValueError("ffmpeg must be a non-empty path or command name")
    if isinstance(quality, bool) or not isinstance(quality, int):
        raise TypeError(f"quality must be an int, got {type(quality).__name__}")
    if quality not in _QUALITY_RANGE:
        raise ValueError(f"quality must be 0-9, got {quality}")
    if isinstance(attached_picture, bool):
        raise TypeError("attached_picture must be an int stream index or None")
    if attached_picture is not None and not isinstance(attached_picture, int):
        raise TypeError("attached_picture must be an int stream index or None")
    if attached_picture is not None and attached_picture < 0:
        raise ValueError(f"attached_picture must not be negative, got {attached_picture!r}")

    decoder = _arguments(decoder_args, "decoder_args")
    extra = _arguments(output_args, "output_args")

    argv = [ffmpeg, "-hide_banner", "-y"]
    # Input options. Anything placed here is read as a property of the *source*,
    # which is why the xHE-AAC decoder selection has to arrive before -i and why
    # the Phase 6 seam below deliberately cannot reach this region.
    argv += decoder
    argv += ["-i", str(source)]
    if attached_picture is not None:
        # The cover's own input. No decoder options precede it on purpose: this
        # input is never decoded, only stream-copied, and the audio decoder
        # selection above must keep applying to input 0 alone.
        argv += ["-i", str(source)]
    # Output options, from here to the destination.
    if seek is not None:
        start, duration = seek
        argv += ["-ss", start, "-t", duration]
    argv += _media_args(attached_picture)
    argv += extra
    argv += ["-c:a", _ENCODER, "-q:a", str(quality), "-threads", "0"]
    argv.append(str(destination))
    return argv


def whole_book_argv(
    *,
    ffmpeg: str,
    source,
    destination: str,
    quality: int,
    decoder_args: Sequence[str] = (),
    output_args: Sequence[str] = (),
    attached_picture: int | None = None,
) -> list[str]:
    """One MP3 covering the whole source: today's Converter behaviour, unchanged.

    Carries no seek and no duration limiter, so ffmpeg reads the source from
    beginning to end.

    *attached_picture* is an absolute source stream index whose cover should ride
    along in this same encode; omitting it keeps the original audio-only ``-vn``
    command exactly as it was. There is no seek here to discard a picture frame,
    which is why a whole book needs only one pass.

    When a cover **is** requested the book is opened twice — audio and chapters
    from input 0, the picture from input 1 — for the reason :func:`_core`
    records. Still one command, still one encode.
    """
    return _core(
        ffmpeg=ffmpeg,
        source=source,
        destination=destination,
        quality=quality,
        decoder_args=decoder_args,
        output_args=output_args,
        seek=None,
        attached_picture=attached_picture,
    )


def segment_argv(
    *,
    ffmpeg: str,
    source,
    destination: str,
    quality: int,
    start: float,
    end: float,
    decoder_args: Sequence[str] = (),
    output_args: Sequence[str] = (),
) -> list[str]:
    """One MP3 covering ``[start, end)`` of the source.

    ``-ss`` is placed **after** ``-i`` and the span is expressed as an explicit
    ``-t (end - start)``. Both choices are measured; the module docstring records
    what happens when either is changed.

    *start* and *end* are absolute source seconds and are used verbatim — this
    function rounds nothing away. It is not the chapter validator: the geometry
    of a timeline belongs to ``m4b_chapters``, and the only checks here are the
    ones without which the command line itself would be meaningless.
    """
    begin = _seconds(start, "start")
    if not math.isfinite(float(end)):
        raise ValueError(f"end must be finite, got {end!r}")
    if float(end) <= float(start):
        raise ValueError(f"end must be greater than start, got start={start!r} end={end!r}")
    span = _seconds(float(end) - float(start), "duration")
    return _core(
        ffmpeg=ffmpeg,
        source=source,
        destination=destination,
        quality=quality,
        decoder_args=decoder_args,
        output_args=output_args,
        seek=(begin, span),
    )


def attach_artwork_argv(
    *,
    ffmpeg: str,
    audio,
    artwork_source,
    artwork_stream: int,
    destination: str,
    output_args: Sequence[str] = (),
) -> list[str]:
    """Put a cover onto an already-encoded split segment, without touching it.

    **Why a split segment needs a second command at all.** An embedded cover is a
    single video frame at timestamp zero. The approved split shape seeks on the
    output side, which discards everything before the segment start, so the cover
    is thrown away with the audio that precedes the segment. That was measured
    across five candidate single-command shapes — a second input, an
    ``-itsoffset`` cover, ``-copypriorss``, and moving the seek — and every one
    either lost the picture or produced the wrong audio, including one that
    silently emitted the entire 24-hour book for a four-second request. Seeking
    on the input side would keep the cover, but Phase 5 proved it corrupts the
    audio at every segment boundary.

    So the audio pass stays exactly as Phase 5 pinned it and the cover is added
    afterwards. Both streams are stream-copied: the audio is *not* re-encoded, so
    the segment that was measured is bit-for-bit the segment that ships.

    **Metadata provenance.** ``-map_metadata 0`` reads input 0 — the sanitised
    output of the audio pass, whose tags were already reduced to the approved
    allowlist. The original book is input 1 and contributes exactly one stream:
    the picture. It can therefore contribute no tags. ``-map_chapters -1`` is
    belt-and-braces on top of that, so no chapter map can reach a fragment by any
    route.
    """
    if not isinstance(ffmpeg, str) or not ffmpeg:
        raise ValueError("ffmpeg must be a non-empty path or command name")
    if isinstance(artwork_stream, bool) or not isinstance(artwork_stream, int):
        raise TypeError(
            f"artwork_stream must be an int, got {type(artwork_stream).__name__}"
        )
    if artwork_stream < 0:
        raise ValueError(f"artwork_stream must not be negative, got {artwork_stream}")

    return [
        ffmpeg, "-hide_banner", "-y",
        "-i", str(audio),
        "-i", str(artwork_source),
        # Audio from the finished segment; the picture, and only the picture,
        # from the book.
        "-map", "0:a:0",
        "-map", f"1:{artwork_stream}",
        "-c", "copy",
        "-disposition:v:0", "attached_pic",
        "-map_metadata", "0",
        "-map_chapters", "-1",
        # v0.6.2 Plan 5 Phase 11 added this seam, and one measurement is the
        # whole reason. This pass re-muxes, so the mp3 muxer decides the ID3
        # version again -- and its default is 2.4. Measured on produced media:
        # every other output this tool writes carried ID3v2.3 and a covered
        # split fragment carried 2.4, so one run produced two tag versions and
        # Windows Explorer reads only the older one. Additive and defaulted to
        # empty, so the argv is byte-identical for every existing caller.
        *_arguments(output_args, "output_args"),
        str(destination),
    ]


# --------------------------------------------------------------------------- #
# Decoded-PCM input — v0.6.2 Plan 5 Phase 15, the Windows xHE-AAC route
# --------------------------------------------------------------------------- #


def pcm_argv(
    *,
    ffmpeg: str,
    pcm_args: Sequence[str],
    destination: str,
    quality: int,
    output_args: Sequence[str] = (),
    metadata_source=None,
    attached_picture: int | None = None,
    keep_chapters: bool = False,
) -> list[str]:
    """Encode already-decoded PCM arriving on stdin.

    **Why this exists.** ffmpeg's native decoder silently loses 23.91 % of a real
    xHE-AAC audiobook (see :mod:`mp3_tools.m4b_winaudio`), so on Windows that one
    codec is decoded by Media Foundation instead and the samples are piped here.
    Everything downstream of the decoder is unchanged: same encoder, same
    quality, same allowlisted metadata, same ID3 version, same transactional
    destination.

    **The audio is input 0 and it is a pipe.** *pcm_args* describes it -- sample
    format, rate, channels -- and comes from the decoder's *negotiated* format
    rather than from an assumption, because the whole point of this path is that
    what arrived is what gets encoded.

    **The book is input 1, and only when it is needed.** PCM carries no chapters,
    no cover and no tags, so anything the output must retain has to come from the
    original file. It is opened only when *keep_chapters* or *attached_picture*
    actually needs it -- a stripped output opens nothing and takes the audio
    alone. Note ``-map_chapters 1``: the chapter map's input index moves because
    the audio now occupies input 0.

    There is **no seek here, ever**. A split segment is cut in the PCM stream at
    frozen sample boundaries before it reaches this command, because seeking a
    USAC decoder costs 0.183 s of primed audio at every jump -- measured. That
    also means this one builder serves whole books and fragments alike: by the
    time ffmpeg sees the audio, the span question has already been answered.
    """
    if not isinstance(ffmpeg, str) or not ffmpeg:
        raise ValueError("ffmpeg must be a non-empty path or command name")
    if isinstance(quality, bool) or not isinstance(quality, int):
        raise TypeError(f"quality must be an int, got {type(quality).__name__}")
    if quality not in _QUALITY_RANGE:
        raise ValueError(f"quality must be 0-9, got {quality}")
    if isinstance(attached_picture, bool):
        raise TypeError("attached_picture must be an int stream index or None")
    if attached_picture is not None and not isinstance(attached_picture, int):
        raise TypeError("attached_picture must be an int stream index or None")
    if attached_picture is not None and attached_picture < 0:
        raise ValueError(
            f"attached_picture must not be negative, got {attached_picture!r}")

    needs_book = keep_chapters or attached_picture is not None
    if needs_book and not metadata_source:
        raise ValueError(
            "metadata_source is required to retain chapters or artwork")

    argv = [ffmpeg, "-hide_banner", "-y"]
    argv += _arguments(pcm_args, "pcm_args")
    argv += ["-i", "pipe:0"]
    if needs_book:
        argv += ["-i", str(metadata_source)]

    argv += ["-map", "0:a:0"]
    if attached_picture is not None:
        argv += ["-map", f"1:{attached_picture}",
                 "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    else:
        argv += ["-vn"]

    # ``-map_metadata`` is **not** emitted here: ``metadata_args`` supplies the
    # allowlist unconditionally and stays the single authority for it. The
    # chapter map *is* owned here, because its input index is the one thing
    # this shape changes -- the book is input 1 now that the audio is a pipe.
    argv += ["-map_chapters", "1" if keep_chapters else "-1"]
    argv += _arguments(output_args, "output_args")
    argv += ["-c:a", _ENCODER, "-q:a", str(quality), "-threads", "0"]
    argv.append(str(destination))
    return argv
