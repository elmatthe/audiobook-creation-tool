"""Running one planned segment, and being able to stop it.

Phase 10 decided everything: which books are usable, how each one divides, what
every output is called and where it goes. This module does that and nothing
else. It reinterprets no decision — it is handed a :class:`SegmentWork` that
already carries the frozen span, the frozen tag set, the frozen cover and the
frozen destination, and its whole job is to turn one of those into a file on
disk, or into a truthful reason why there isn't one.

**Why the child process is not simply ``run``.** ``shared.subprocess_utils.popen``
is a thin pass-through, so polling a process whose ``stdout=PIPE`` is never
drained blocks the moment ffmpeg fills the OS pipe buffer — and ffmpeg is
talkative. Draining it from this thread would mean not polling for cancellation;
draining it from another thread would mean a second thread per segment. So the
child writes its diagnostics to a temporary file instead: there is no buffer to
fill, no reader to schedule, and cancellation is checked on a short interval
between polls. Only a bounded tail of that file is ever read into memory, and
the file is removed as soon as the tail is taken.

**Why nothing is written to its final name.** A destination that exists is a
destination that looks finished. Every pass writes to a temporary file in the
*destination's own folder* — the same filesystem, so the final move is a single
``os.replace`` rather than a copy — and the frozen destination only comes into
existence once the process exited cleanly, the artwork pass (if any) also
exited cleanly, and the measured duration matched what the plan asked for. A
failure at any of those points leaves the folder exactly as it was.

**Why the cancellation ladder is a ladder.** ``terminate()`` asks; a process
mid-encode usually goes. If it has not gone within the grace period it is
killed. Either way it is **always** waited on, because an unreaped child is a
zombie on POSIX and a live handle on Windows, and "the user cancelled" is not a
reason to leave one behind. Cancellation is not settled until the child is gone
*and* the partial file is gone — which is what makes ``CANCELLED`` mean "it
stopped" rather than "someone clicked Cancel".

Tk-free, widget-free and queue-free. It owns processes and files; the panel owns
the run, and the plan owns the answers.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from shared import output_paths
from shared import subprocess_utils as sp

from . import m4b_commands
from . import m4b_metadata
from .m4b_metadata import AttachedPicture, MetadataMode

#: How often the poll loop looks at the child and at the cancellation latch.
#: Short enough that Cancel feels immediate, long enough not to spin a core.
DEFAULT_POLL_SECONDS = 0.05

#: How long a terminated child is given to exit before it is killed, and how
#: long a killed child is given before its refusal to die is reported rather
#: than waited on forever.
DEFAULT_GRACE_SECONDS = 5.0

#: The bounded diagnostic tail kept for a failure's Details pane (§18.2). An
#: ffmpeg log can run to megabytes; a summary never sees this at all, and even
#: Details does not need the whole thing.
DETAIL_TAIL = 2000

#: The proportion by which a produced output may differ from the span the plan
#: asked for. Unchanged from the guard this tool has always had.
DRIFT_TOLERANCE = 0.03

#: Below this many seconds the ratio test is not meaningful — a hundredth of a
#: second either way on a two-second segment is encoder framing, not corruption.
DRIFT_FLOOR_SECONDS = 1.0


class ProcessLaunchError(RuntimeError):
    """The child could not be started at all — ffmpeg missing, or not executable."""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """What became of one child process."""

    returncode: int | None
    cancelled: bool = False
    detail: str = ""
    #: True when the process had to be killed after refusing to terminate.
    killed: bool = False
    #: True when even ``wait()`` did not return in time. Always reported, never
    #: swallowed: it is the one outcome that could leave something behind.
    unreaped: bool = False
    #: True when the thing feeding stdin raised. Separate from ``returncode``
    #: because ffmpeg can exit 0 on the audio it *did* receive: a decoder that
    #: stopped early would otherwise look like success, which is precisely the
    #: failure mode v0.6.2 Plan 5 Phase 15 exists to remove.
    producer_failed: bool = False

    @property
    def ok(self) -> bool:
        return (self.returncode == 0 and not self.cancelled
                and not self.producer_failed)


@dataclass(frozen=True, slots=True)
class SegmentWork:
    """One planned output, reduced to exactly what execution needs.

    Every field is a value the plan already decided. ``span`` is ``None`` for a
    whole-book output and ``(start, end)`` for a fragment, which is the only
    thing that chooses between the two approved command shapes.
    """

    source: Path
    destination: Path
    expected_duration: float
    quality: int
    metadata_mode: MetadataMode
    tags: Mapping[str, object] = field(default_factory=dict)
    decoder_args: tuple[str, ...] = ()
    picture: AttachedPicture | None = None
    span: tuple[float, float] | None = None
    #: Copied from the frozen ``ItemPlan``, never re-derived here. It exists so
    #: a duration mismatch can say *why* only when the plan already knows why:
    #: before v0.6.2 Plan 5 Phase 15 every drift blamed xHE-AAC, including the
    #: one whose own probe recorded plain AAC-LC and a perfectly decodable
    #: source. Defaults to ``False`` so an unstated source is never accused.
    undecodable_xhe: bool = False
    #: Also frozen at preflight: this output's audio is decoded by Windows Media
    #: Foundation and piped in, because ffmpeg cannot decode this source
    #: completely. Defaults to ``False``, so every ordinary AAC-LC book takes the
    #: untouched ffmpeg path and nothing has to opt out of the new route.
    windows_decode: bool = False
    #: How ffmpeg should read that pipe, from the decoder's *negotiated* format
    #: rather than an assumption -- the sample maths that proves a complete
    #: decode has to be done against what actually arrived.
    pcm_args: tuple[str, ...] = ()
    #: The source's chapter titles, copied from the frozen ``ItemPlan``. Written
    #: back explicitly because ``-map_metadata -1`` strips the titles off the map
    #: ``-map_chapters`` copied; execution never re-reads the source to get them.
    chapter_titles: tuple[str, ...] = ()

    @property
    def fragment(self) -> bool:
        return self.span is not None


@dataclass(frozen=True, slots=True)
class SegmentOutcome:
    """Whether one output exists now, and if not, why not."""

    destination: Path
    finalised: bool = False
    cancelled: bool = False
    message: str = ""
    detail: str = ""
    measured: float | None = None
    #: The commands actually run, for the Details pane and the transcript.
    commands: tuple[tuple[str, ...], ...] = ()

    @property
    def failed(self) -> bool:
        return not self.finalised and not self.cancelled


def tail_of(path: Path, *, limit: int = DETAIL_TAIL) -> str:
    """The last *limit* characters of a diagnostic file. Never the whole file.

    Reads at most ``limit`` bytes from the end by seeking, so a multi-megabyte
    ffmpeg log costs one small read rather than a large allocation.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    try:
        with open(path, "rb") as handle:
            if size > limit:
                handle.seek(size - limit)
            raw = handle.read(limit)
    except OSError:
        return ""
    return raw.decode("utf-8", "replace").strip()


def _stop(proc, *, grace_seconds: float, poll_seconds: float, monotonic, wait) -> bool:
    """Terminate, then kill if it will not go. Returns whether it had to be killed."""
    try:
        proc.terminate()
    except OSError:  # pragma: no cover - already gone
        return False
    deadline = monotonic() + grace_seconds
    while monotonic() < deadline:
        if proc.poll() is not None:
            return False
        wait(poll_seconds)
    try:
        proc.kill()
    except OSError:  # pragma: no cover - it went during the last poll
        return False
    return True


def _reap(proc, *, timeout: float) -> bool:
    """Always wait. Returns whether the child was actually collected."""
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:  # pragma: no cover - a child that will not die
        return False
    except Exception:  # pragma: no cover - already reaped
        return True


def run_argv(
    argv: Sequence[str],
    *,
    cancelled: Callable[[], bool],
    workspace: Path,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
    popen=None,
    monotonic=time.monotonic,
    wait=time.sleep,
) -> ProcessResult:
    """Run one child to completion, or stop it, and always reap it.

    *cancelled* is polled between process polls; it is the low-level latch, not
    the job state. *workspace* is the directory the diagnostic file is created
    in — the destination's own folder, so nothing is written outside the
    reserved run.

    Diagnostics go to a file rather than a pipe. That is the whole of §18.2: an
    undrained ``PIPE`` deadlocks a polling loop the moment ffmpeg outruns the OS
    buffer, and this tool's ffmpeg output is not small.
    """
    spawn = sp.popen if popen is None else popen
    diagnostics = output_paths.temporary_sibling(
        Path(workspace) / "ffmpeg", suffix=".log")
    try:
        try:
            with open(diagnostics, "wb") as sink:
                proc = spawn(argv, stdout=sink, stderr=subprocess.STDOUT)
        except OSError as exc:
            raise ProcessLaunchError(f"{type(exc).__name__}: {exc}") from exc

        killed = False
        stopped = False
        try:
            while True:
                code = proc.poll()
                if code is not None:
                    break
                if cancelled():
                    killed = _stop(proc, grace_seconds=grace_seconds,
                                   poll_seconds=poll_seconds,
                                   monotonic=monotonic, wait=wait)
                    stopped = True
                    break
                wait(poll_seconds)
        finally:
            # Unconditional, on every route out of the loop including an
            # exception: a child this function started is a child it collects.
            reaped = _reap(proc, timeout=grace_seconds)

        return ProcessResult(
            returncode=proc.returncode,
            cancelled=stopped,
            detail=tail_of(diagnostics),
            killed=killed,
            unreaped=not reaped,
        )
    finally:
        output_paths.discard_temporary(diagnostics)


def run_argv_streaming(
    argv: Sequence[str],
    *,
    feed: Callable[[Callable[[bytes], None]], None],
    cancelled: Callable[[], bool],
    workspace: Path,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
    popen=None,
    monotonic=time.monotonic,
    wait=time.sleep,
    spawn_thread=None,
) -> ProcessResult:
    """Run one child that is *fed* on stdin, and always reap it.

    The same contract as :func:`run_argv` -- diagnostics to a file rather than a
    pipe, cancellation polled between polls, the child collected on every route
    out -- with one addition: a producer thread pushes bytes into stdin while
    the main thread watches the process.

    **Backpressure is the pipe itself.** *feed* is handed a ``write`` callable
    and blocks inside it whenever the encoder is behind, so a ten-hour decode
    never runs ahead of the encoder and nothing accumulates in memory. That is
    the whole reason this streams rather than staging PCM: the one real source
    this was built for is 6.2 GB decoded.

    **Cancellation unblocks a blocked producer.** Stopping the child closes the
    read end, so a ``write`` waiting on a full pipe raises and the producer
    unwinds instead of hanging. Both are joined before this returns; a producer
    that outlives its child would be exactly the leak §18.2 exists to prevent.
    """
    launch = sp.popen if popen is None else popen
    start_thread = spawn_thread
    if start_thread is None:  # imported lazily: the module stays Tk- and thread-free
        import threading      # noqa: PLC0415 - see docstring

        def start_thread(target):  # type: ignore[misc]
            thread = threading.Thread(target=target, name="m4b-pcm-producer",
                                      daemon=True)
            thread.start()
            return thread

    diagnostics = output_paths.temporary_sibling(
        Path(workspace) / "ffmpeg", suffix=".log")
    failure: list[str] = []
    try:
        try:
            with open(diagnostics, "wb") as sink:
                proc = launch(argv, stdin=subprocess.PIPE, stdout=sink,
                              stderr=subprocess.STDOUT)
        except OSError as exc:
            raise ProcessLaunchError(f"{type(exc).__name__}: {exc}") from exc

        def pump() -> None:
            try:
                feed(proc.stdin.write)
            except (BrokenPipeError, OSError, ValueError):
                # The consumer went away -- its returncode is the real story.
                pass
            except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                failure.append(f"{type(exc).__name__}: {exc}")
            finally:
                try:
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass

        producer = start_thread(pump)

        killed = False
        stopped = False
        try:
            while True:
                code = proc.poll()
                if code is not None:
                    break
                if cancelled():
                    killed = _stop(proc, grace_seconds=grace_seconds,
                                   poll_seconds=poll_seconds,
                                   monotonic=monotonic, wait=wait)
                    stopped = True
                    break
                wait(poll_seconds)
        finally:
            reaped = _reap(proc, timeout=grace_seconds)
            if producer is not None and hasattr(producer, "join"):
                producer.join(timeout=grace_seconds)

        detail = tail_of(diagnostics)
        if failure:
            detail = (detail + "\n" if detail else "") + failure[0]
        return ProcessResult(
            returncode=proc.returncode,
            cancelled=stopped,
            detail=detail,
            killed=killed,
            unreaped=not reaped,
            producer_failed=bool(failure),
        )
    finally:
        output_paths.discard_temporary(diagnostics)


def _output_args(work: SegmentWork, *, chapters: bool = True) -> list[str]:
    """The output-side arguments carrying this segment's already-decided tags.

    No policy is chosen here. ``metadata_args`` makes every mode an allowlist by
    emitting ``-map_metadata -1`` unconditionally, and ``retains_chapters``
    answers the chapter question from the frozen mode and the item's own
    fragment flag -- which is what makes a chapterless split output keep the
    whole-book treatment it was planned with.

    ``-id3v2_version 3`` is appended exactly where this tool has always put it:
    only when tags are actually written. ffmpeg's mp3 muxer defaults to ID3v2.4
    and Windows Explorer reads 2.3, so dropping it while adopting the Phase 6
    composition would have silently changed the tag version of every MP3 the
    Converter produces.
    """
    args = m4b_metadata.metadata_args(
        work.tags,
        keep_chapters=m4b_metadata.retains_chapters(
            work.metadata_mode, split=work.fragment),
        chapter_titles=work.chapter_titles,
    )
    if work.tags:
        args = list(args) + ["-id3v2_version", "3"]
    args = list(args)
    if not chapters:
        # The PCM route owns the chapter map, because the book moves to input 1
        # once the audio is a pipe. Leaving this pair in as well would put two
        # ``-map_chapters`` on one command line and let argument order settle it
        # -- which mapped chapters from the pipe, and cost a real xHE-AAC book
        # all fifteen of them in the first live run.
        #
        # Only the mapping pair goes. The ``-metadata:c:N`` titles stay: they
        # name *output* chapters, so they are indifferent to which input the map
        # came from, and stripping them would give the Windows xHE route the
        # anonymous-chapter defect this file's ``metadata_args`` exists to fix.
        while "-map_chapters" in args:
            at = args.index("-map_chapters")
            del args[at:at + 2]
    return args


def _passes(work: SegmentWork, *, ffmpeg: str, staged_final: Path,
            staged_audio: Path | None) -> tuple[tuple[str, ...], ...]:
    """The one or two commands this output needs, from the pinned builders.

    Which builder is used is decided by the plan's shape and nothing else: a
    whole-book output has no span and takes the unseeked command; a fragment
    takes the measured output-side seek. Neither is assembled here -- the
    argument order in both was measured in Phase 5 and lives in
    ``m4b_commands``, where a "simplification" has to fail a test.
    """
    output_args = _output_args(work, chapters=not work.windows_decode)
    keep = work.picture if m4b_metadata.wants_artwork(work.metadata_mode) else None

    if work.windows_decode:
        # The audio arrives already decoded, on stdin, so there is no seek and
        # no span left to express: the timeline was cut before ffmpeg saw it.
        # One command covers a whole book and a fragment alike.
        return (tuple(m4b_commands.pcm_argv(
            ffmpeg=ffmpeg,
            pcm_args=work.pcm_args,
            destination=str(staged_final),
            quality=work.quality,
            output_args=output_args,
            metadata_source=work.source,
            attached_picture=None if keep is None else keep.stream_index,
            keep_chapters=m4b_metadata.retains_chapters(
                work.metadata_mode, split=work.fragment),
        )),)

    if not work.fragment:
        # One pass: there is no seek to discard a cover frame, so artwork rides
        # along in the same encode.
        return (tuple(m4b_commands.whole_book_argv(
            ffmpeg=ffmpeg,
            source=work.source,
            destination=str(staged_final),
            quality=work.quality,
            decoder_args=work.decoder_args,
            output_args=output_args,
            attached_picture=None if keep is None else keep.stream_index,
        )),)

    start, end = work.span  # type: ignore[misc]
    first = staged_final if keep is None else staged_audio
    audio = tuple(m4b_commands.segment_argv(
        ffmpeg=ffmpeg,
        source=work.source,
        destination=str(first),
        quality=work.quality,
        start=start,
        end=end,
        decoder_args=work.decoder_args,
        output_args=output_args,
    ))
    if keep is None:
        return (audio,)

    # The cover sits at timestamp zero and the output-side seek throws it away,
    # so it is attached afterwards by stream copy -- the segment that was
    # measured is the segment that ships.
    attach = tuple(m4b_commands.attach_artwork_argv(
        ffmpeg=ffmpeg,
        audio=first,
        artwork_source=work.source,
        artwork_stream=keep.stream_index,
        destination=str(staged_final),
        # This pass writes the file that ships, so it decides the ID3 version.
        # Without this a covered split fragment came out ID3v2.4 while every
        # other output in the same run was 2.3 -- measured, not assumed.
        output_args=["-id3v2_version", "3"] if work.tags else (),
    ))
    return (audio, attach)


def needs_artwork_pass(work: SegmentWork) -> bool:
    """Whether this output will need the second, cover-attaching command.

    Only a *fragment* does, and only when a cover is both present and retained:
    the output-side seek that makes a split segment correct is exactly what
    throws the cover frame away. A whole book keeps its cover in one pass
    because there is no seek to discard it.
    """
    return (work.fragment and work.picture is not None
            and m4b_metadata.wants_artwork(work.metadata_mode))


def drift_of(measured: float | None, expected: float) -> float | None:
    """How far a produced output is from the span that was asked for.

    ``None`` when the comparison would not be meaningful — nothing measured, or
    a span too short for a ratio to say anything an encoder's framing does not.
    """
    if measured is None or expected is None:
        return None
    if expected <= DRIFT_FLOOR_SECONDS:
        return None
    return abs(float(measured) - float(expected)) / float(expected)


def drift_message(measured: float, expected: float, drift: float,
                  *, fragment: bool, undecodable_xhe: bool = False) -> str:
    """The user-facing reason a produced file was thrown away.

    **The measurement is the finding; the cause is not.** This used to assert
    xHE-AAC on every drift, and v0.6.2 Plan 5 Phase 15 caught it telling a
    maintainer that a plain AAC-LC audiobook "could not be decoded correctly
    (likely xHE-AAC)" while the same file's own frozen probe recorded
    ``undecodable_xhe=False``. The real cause was a command shape that made
    ffmpeg stop early and report success. An hour was spent on the wrong
    suspect, which is what a confident guess costs.

    So a cause is named only when the plan already established it. Everything
    else reports exactly what was observed — how long the output is, how long it
    was meant to be, and that it was discarded — and attributes nothing.
    """
    what = "segment" if fragment else "output"
    head = (f"{what} length {measured:.0f}s != planned {expected:.0f}s "
            f"({drift:.0%} off)")
    if undecodable_xhe:
        return (f"{head} — the source could not be decoded correctly (xHE-AAC "
                "with no compatible decoder on this platform). Output discarded.")
    return (f"{head} — ffmpeg reported success but produced an output of an "
            "unexpected length. Output discarded.")


def convert_segment(
    work: SegmentWork,
    *,
    ffmpeg: str,
    cancelled: Callable[[], bool],
    measure: Callable[[Path], float | None],
    sources: Iterable[Path] = (),
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
    popen=None,
    monotonic=time.monotonic,
    wait=time.sleep,
    on_command: Callable[[Sequence[str]], None] | None = None,
    feed: Callable[[Callable[[bytes], None]], None] | None = None,
) -> SegmentOutcome:
    """Produce one planned output, or explain truthfully why it does not exist.

    The order is the safety contract: write to a temporary file, run every pass
    the plan's shape requires, measure what was produced, and only then move it
    onto the frozen destination. Nothing that fails any of those steps leaves a
    file behind, and the destination never appears half-written.

    *measure* reads a produced file's duration; it is injected so the drift
    guard can be exercised without media. *on_command* is a transcript hook —
    it renders nothing and decides nothing.
    """
    destination = Path(work.destination)
    commands_run: list[tuple[str, ...]] = []

    def refuse(message: str, detail: str = "") -> SegmentOutcome:
        return SegmentOutcome(destination=destination, message=message,
                              detail=detail, commands=tuple(commands_run))

    try:
        output_paths.assert_not_input(destination, tuple(sources))
    except output_paths.OutputPathError as exc:
        return refuse(getattr(exc, "message", str(exc)), str(exc))

    # The mirrored folder a plan named but deliberately did not create.
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return refuse(f"{destination.parent} could not be created.",
                      f"{type(exc).__name__}: {exc}")

    try:
        staged_final = output_paths.temporary_sibling(destination, suffix=".mp3")
    except output_paths.OutputPathError as exc:
        return refuse(getattr(exc, "message", str(exc)), str(exc))

    staged_audio: Path | None = None
    try:
        if needs_artwork_pass(work):
            staged_audio = output_paths.temporary_sibling(destination, suffix=".mp3")

        passes = _passes(work, ffmpeg=ffmpeg, staged_final=staged_final,
                         staged_audio=staged_audio)

        for argv in passes:
            commands_run.append(tuple(argv))
            if on_command is not None:
                on_command(argv)
            try:
                if work.windows_decode:
                    if feed is None:
                        return refuse(
                            f"{destination.name} could not be started.",
                            "the plan asked for the Windows decoder but no "
                            "decoded audio was supplied")
                    result = run_argv_streaming(
                        argv, feed=feed, cancelled=cancelled,
                        workspace=destination.parent,
                        poll_seconds=poll_seconds, grace_seconds=grace_seconds,
                        popen=popen, monotonic=monotonic, wait=wait)
                else:
                    result = run_argv(
                        argv, cancelled=cancelled, workspace=destination.parent,
                        poll_seconds=poll_seconds, grace_seconds=grace_seconds,
                        popen=popen, monotonic=monotonic, wait=wait)
            except ProcessLaunchError as exc:
                return refuse(f"{destination.name} could not be started.", str(exc))

            if result.producer_failed:
                # ffmpeg can exit 0 on the audio it did receive, so a decoder
                # that stopped early would otherwise look like success.
                return refuse(f"{destination.name} could not be decoded.",
                              result.detail)

            if result.cancelled:
                return SegmentOutcome(destination=destination, cancelled=True,
                                      detail=result.detail,
                                      commands=tuple(commands_run))
            if result.unreaped:  # pragma: no cover - a child that would not die
                return refuse(
                    f"{destination.name} could not be stopped cleanly.",
                    "the ffmpeg child did not exit after terminate and kill")
            if result.returncode != 0:
                return refuse(
                    f"{destination.name} could not be written.",
                    f"ffmpeg exited {result.returncode}\n{result.detail}")

        measured = measure(staged_final)
        drift = drift_of(measured, work.expected_duration)
        if drift is not None and drift > DRIFT_TOLERANCE:
            return refuse(
                drift_message(float(measured), float(work.expected_duration),
                              drift, fragment=work.fragment,
                              undecodable_xhe=work.undecodable_xhe),
                f"measured {measured!r}s against a planned "
                f"{work.expected_duration!r}s span")

        # The plan reserved this name and nothing has written it since. If
        # something else has, that is not a collision to renumber around — the
        # frozen plan must stay retry-stable — so it is refused rather than
        # overwritten.
        if destination.exists():
            return refuse(
                f"{destination.name} already exists, so it was not replaced.",
                "the planned destination was occupied after the run was planned")

        output_paths.atomic_replace(staged_final, destination)
        staged_final = None  # type: ignore[assignment]  # ownership transferred
        return SegmentOutcome(destination=destination, finalised=True,
                              measured=measured, commands=tuple(commands_run))
    finally:
        for leftover in (staged_final, staged_audio):
            if leftover is not None:
                output_paths.discard_temporary(leftover)


def remove_outputs(paths: Iterable[Path], *, inside: Path) -> tuple[Path, ...]:
    """Delete finalised outputs of an item that did not complete.

    A partially split book must never look like a whole one (§21), so when one
    segment fails the segments already written for that same book are taken
    back. Deliberately narrow: *inside* is the reserved run directory and
    anything outside it is refused rather than deleted, so this can never be
    talked into removing a source or another book's finished work.
    """
    root = Path(inside).resolve()
    removed: list[Path] = []
    for path in paths:
        candidate = Path(path)
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        try:
            candidate.unlink(missing_ok=True)
            removed.append(candidate)
        except OSError:
            continue
    return tuple(removed)
