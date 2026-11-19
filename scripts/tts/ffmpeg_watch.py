"""Every FFmpeg the Edge routes start, so that it can always be stopped and can never hang a conversion (v0.7.1).

**What this exists for.** ``subprocess.Popen.communicate`` with two pipes on Windows gives each pipe a Python thread. When memory
runs out while FFmpeg's output is read, the stdout thread dies of ``MemoryError`` and nothing reads that pipe again: FFmpeg blocks
writing to it, and ``communicate`` waits for ever on the stderr thread, which is waiting for FFmpeg. Nothing is raised, nothing can
be caught and no timeout on a thread frees the process. pydub decodes and exports through exactly that call, so an allocation
failure during an assembly stopped the whole run (R2-1; plain Python and FFmpeg do the same with none of this tool's code).

**What it does.** A :class:`Supervised` process has no threads of its own. FFmpeg's output is read by the thread that asked for it,
so a ``MemoryError`` is raised where it can be handled, and that thread kills the process on its way out. FFmpeg's stderr goes to a
temporary file, so that FFmpeg cannot block on it however little anybody reads it. One daemon :func:`_watchdog` looks at every live
process and kills one that has stopped making progress, or whose conversion was cancelled, which also ends a blocking read.

pydub is pointed at this by replacing the ``subprocess`` name in its modules (:func:`install`): its commands, and so its audio, are
unchanged, and no call site can be missed. pydub is pinned, and ``test_low_memory`` fails if these names ever stop being what it uses.

A failed ``export`` leaves pydub's two temporary files behind, the first holding the whole narration as a WAV, and nothing else knows
their names. So its ``NamedTemporaryFile`` is replaced as well: inside a :func:`controlled` block they are remembered, and the block's
end removes any still there (:func:`remove_temporaries`, which a fallback calls sooner, because it needs that disk space). They are
made in the block's own folder of the TTS work area (v0.7.2, :mod:`shared.work_area`), made at the first one and removed after them,
so a killed program's are recognised as its own and removed by a later run; before, they lay loose in the temp folder for good.

**The deadlines.** Measured from the last progress: bytes read from FFmpeg, or growth of the file it is writing.

* :data:`STALL_SECONDS`: no progress at all, nobody has cancelled: killed, and the file fails with :class:`ProcessingStalled`.
* Cancelled: killed within one :data:`WATCH_SECONDS`, whatever it was doing and however well it was going (v0.7.2). A Cancel stops
  active work; it does not let finished narration be assembled or encoded first. :func:`wake` lets the Cancel be noticed before
  the watchdog's next look. Nothing unfinished ever reaches a destination: that is :mod:`tts.publication`'s contract.

**Never started after a Cancel (v0.8.x P5-H-R1).** Killing is for work already running. A process is started only under the
run's own Cancel latch (:func:`_authorized_start`, the controller's lock): a Cancel that came first refuses the
start with :class:`ConversionCancelled` and nothing is spawned; a start that came first is watched before the latch is free again,
so the Cancel kills it like any other. A cancel check with no latch (a bare predicate) gets a look before the start and another
once it is watched. :func:`checkpoint` is the same look for work between processes. A process that does not end when killed is
never reported as a clean end (:class:`ProcessNotStopped`).
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import selectors
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from shared import subprocess_utils
from shared.cancellation import ConversionCancelled
from shared import work_area

WATCH_SECONDS = 0.25
#: No progress at all, nobody has cancelled. A virus scanner opening a 4 GB WAV can hold FFmpeg for a minute or two; a whole
#: narration takes seconds to minutes in all.
STALL_SECONDS = 300
#: Enough of what FFmpeg said to explain a failure. It prints its build options first, which can run to a few KB.
STDERR_TAIL_BYTES = 64 * 1024
BLOCK_BYTES = 1024 * 1024
CANCELLED_MESSAGE = "Conversion cancelled by user."


#: How long a killed FFmpeg is given to be gone before that is reported as a failure, not a clean end. Within the plan's
#: C2 bound for one FFmpeg step (4 s from Cancel): the watchdog kills within one look of a Cancel, then this (v0.8.x P5-H-R1;
#: 30 s at 94e200f). SIGKILL ends an ordinary process at once; one that outlives this is reported, never hidden.
ABANDON_WAIT_SECONDS = 3.0
#: How many times a start is prepared again when its guardian changed in between (v0.8.x P5-H-R1).
START_ATTEMPTS = 3


class ProcessingStalled(RuntimeError):
    """FFmpeg stopped making progress and was killed. Nothing unfinished reaches a destination."""


class ProcessNotStopped(RuntimeError):
    """FFmpeg was killed and had still not ended :data:`ABANDON_WAIT_SECONDS` later (v0.8.x P5-H-R1). It stays watched, and the
    file fails rather than ending as cleanly cancelled or finished while it may still be running."""


class _Scratch:
    """A ``controlled`` block's own folder for pydub's temporaries, made at the first one. Shared with the threads the block's
    context is copied into, hence the lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._folder: Optional[work_area.OwnedFolder] = None

    def path(self) -> str:
        with self._lock:
            if self._folder is None:
                self._folder = work_area.new_folder("pydub")
            return str(self._folder.path)

    def close(self) -> None:
        with self._lock:
            folder, self._folder = self._folder, None
        if folder is not None:
            folder.close()


@dataclass(frozen=True)
class _Control:
    cancel_check: Optional[Callable[[], bool]] = None
    temporaries: Optional[list] = None  # pydub's temporary files, while in a ``controlled`` block
    scratch: Optional[_Scratch] = None  # where they are made, while in a ``controlled`` block


_control: contextvars.ContextVar[_Control] = contextvars.ContextVar("ffmpeg_watch_control", default=_Control())


@contextlib.contextmanager
def controlled(cancel_check: Optional[Callable[[], bool]]):
    """Every FFmpeg this thread starts inside the block answers to ``cancel_check``: once it says so, the process is killed
    within one look, whatever stage of the conversion it belongs to."""
    _ensure_watchdog()
    scratch = _Scratch()
    token = _control.set(_Control(cancel_check, [], scratch))
    try:
        yield
    finally:
        remove_temporaries()
        _control.reset(token)
        scratch.close()  # after the files in it, whose handles remove_temporaries has closed


def current_cancel_check() -> Optional[Callable[[], bool]]:
    """The cancel check of the conversion this thread is running inside a :func:`controlled` block, or ``None``.

    The Edge request loops read it here (v0.7.2) rather than taking a new parameter, so the seams the offline test
    doubles stand in for keep their shape, and a request made anywhere in the conversion answers to the same Cancel the
    watchdog does. ``parallel_edgespeak`` copies the context into its executor threads for the same reason.
    """
    return _control.get().cancel_check


def checkpoint() -> None:
    """Raise :class:`ConversionCancelled` if this thread's conversion has been cancelled (v0.8.x P5-H-R1). Work done between
    FFmpeg processes (reading, scanning or converting a narration on disk) asks this per block, so a Cancel stops it as the
    watchdog stops a process. Outside a :func:`controlled` block it does nothing."""
    cancel_check = _control.get().cancel_check
    if cancel_check is not None and cancel_check():
        raise ConversionCancelled(CANCELLED_MESSAGE)


def _named_temporary_file(*args, **kwargs):
    """pydub's ``NamedTemporaryFile``. A file it asked to keep (it removes those itself, if nothing fails) is remembered. Inside a
    ``controlled`` block it is made in the block's own work-area folder (pydub never names a folder; ``dir`` is the 7th argument)."""
    control = _control.get()
    if control.scratch is not None and len(args) < 7 and kwargs.get("dir") is None:
        kwargs["dir"] = control.scratch.path()
    handle = tempfile.NamedTemporaryFile(*args, **kwargs)
    remembered = control.temporaries
    if remembered is not None and not kwargs.get("delete", True):
        remembered[:] = [other for other in remembered if os.path.exists(other.name)]
        remembered.append(handle)
    return handle


def remove_temporaries() -> None:
    """Remove what a failed pydub export of this conversion left. Only ever this conversion's: they are remembered per thread."""
    remembered = _control.get().temporaries
    if remembered:
        for handle in remembered:
            with contextlib.suppress(OSError):
                handle.close()
                os.unlink(handle.name)
        remembered.clear()


class _Watched:
    def __init__(self, process: subprocess.Popen, output: Optional[str], control: _Control) -> None:
        self.process = process
        self.output = output
        self.control = control
        self.progress_at = time.monotonic()
        self.size = -1
        self.verdict: Optional[BaseException] = None
        self.verdict_at: Optional[float] = None
        # v0.8.x P5-H-R1: killed and not seen to end within ABANDON_WAIT_SECONDS. It stays watched, and the watchdog reaps it
        # (and forgets it) once it does end.
        self.unconfirmed = False

    def decide(self, verdict: BaseException) -> None:
        if self.verdict is None:
            self.verdict, self.verdict_at = verdict, time.monotonic()


_watched: set[_Watched] = set()
_watched_lock = threading.Lock()
_wake = threading.Event()
_watchdog_thread: Optional[threading.Thread] = None


def _asked_to_cancel(control: _Control) -> bool:
    if control.cancel_check is None:
        return False
    try:
        return bool(control.cancel_check())
    except Exception:  # noqa: BLE001 - asking must not stop the watching
        return False


def _verdict_on(item: _Watched, now: float) -> Optional[BaseException]:
    if item.output is not None:
        with contextlib.suppress(OSError):
            size = os.stat(item.output).st_size
            if size != item.size:
                item.size, item.progress_at = size, now
    if _asked_to_cancel(item.control):
        return ConversionCancelled(CANCELLED_MESSAGE)
    idle = now - item.progress_at
    if idle >= STALL_SECONDS:
        return ProcessingStalled(
            f"FFmpeg stopped making progress for {round(idle)} seconds and was stopped. Nothing unfinished was saved. Check the "
            "drive holding the output and temporary folders, then use Retry Failed.")
    return None


@contextlib.contextmanager
def _authorized_start(control: _Control) -> Iterator[None]:
    """A process may be started, ordered against the run's Cancel (v0.8.x P5-H-R1).

    The run's controller (a :class:`~shared.job_control.JobController`, whose bound ``cancel_check`` every Cancel button
    hands over) runs the body holding the lock its Cancel latches under (:meth:`~shared.job_control.JobController.starting`):
    a Cancel that came first refuses the start, and a Cancel that comes during it waits for the spawn and registration and
    then finds the process to kill. No child is created after the latch. A bare predicate has no latch: it gets a look, and
    one that fails is not a Cancel, as the watchdog reads it.
    """
    owner = getattr(control.cancel_check, "__self__", None)
    if hasattr(owner, "starting"):
        with owner.starting(CANCELLED_MESSAGE):
            yield
        return
    if _asked_to_cancel(control):
        raise ConversionCancelled(CANCELLED_MESSAGE)
    yield


def unconfirmed_children(cancel_check: Optional[Callable[[], bool]] = None) -> list[int]:
    """Process ids of FFmpeg that were killed, were not seen to end within :data:`ABANDON_WAIT_SECONDS`, and are still
    running (v0.8.x P5-H-R1); only those started under ``cancel_check`` when it is given. A run with any of these must not
    be reported as cleanly cancelled or finished: the panel's settlement asks this."""
    with _watched_lock:
        items = list(_watched)
    found = []
    for item in items:
        if item.unconfirmed and (cancel_check is None or item.control.cancel_check == cancel_check):
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                if item.process.poll() is None:
                    found.append(item.process.pid)
    return found


def _watch_once() -> None:
    now = time.monotonic()
    with _watched_lock:
        items = list(_watched)
    for item in items:
        if item.unconfirmed:
            # Given up on by its caller (ProcessNotStopped): killed again, and reaped and forgotten once it has ended.
            with contextlib.suppress(OSError):
                item.process.kill()
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                if item.process.poll() is not None:
                    with _watched_lock:
                        _watched.discard(item)
            continue
        if item.verdict is None:
            verdict = _verdict_on(item, now)
            if verdict is not None:
                item.decide(verdict)
                with contextlib.suppress(OSError):
                    item.process.kill()


def _watchdog() -> None:
    while True:
        try:
            _watch_once()
            with _watched_lock:
                idle = not _watched
            # Asleep until the next look, or until something wakes it: a new process, or a Cancel (:func:`wake`).
            _wake.wait(None if idle else WATCH_SECONDS)
            _wake.clear()
        except BaseException:  # noqa: BLE001 - out of memory here too: this thread is the one that must not stop
            time.sleep(WATCH_SECONDS)


def wake() -> None:
    """Look at every watched process now, not at the next tick. The panel calls this when Cancel is pressed, so a cancelled
    FFmpeg is killed as soon as the latch is set rather than up to :data:`WATCH_SECONDS` later."""
    _wake.set()


def _ensure_watchdog() -> None:
    """Started before it is needed, at the start of a conversion. If the system cannot start one thread, that is the failure."""
    global _watchdog_thread
    with _watched_lock:
        if _watchdog_thread is None or not _watchdog_thread.is_alive():
            thread = threading.Thread(target=_watchdog, name="ffmpeg-watchdog", daemon=True)
            thread.start()
            _watchdog_thread = thread


class Supervised:
    """A child process with the part of the ``Popen`` interface pydub uses, and no threads of its own."""

    def __init__(self, args, stdin=None, stdout=None, stderr=None, **kwargs) -> None:
        _ensure_watchdog()
        control = _control.get()
        self.args = args
        self._errors = None
        self._selector: Optional[selectors.BaseSelector] = None
        last = args[-1] if isinstance(args, (list, tuple)) and args else None
        # FFmpeg's last argument is what it writes, unless that is a pipe. For anything else the size just never changes.
        output = os.fspath(last) if isinstance(last, (str, os.PathLike)) and last != "-" else None
        try:
            for attempt in range(START_ATTEMPTS):
                # v0.8.x P5-H-R1. Anything slow the start needs (macOS: the containment guardian) happens first, outside the
                # run's Cancel ordering; only a guardian's spawn, if one is needed, is ordered (no guardian is made for a
                # cancelled run). Then the start itself, ordered and watched before Cancel may latch, in exactly that
                # guardian's group: if it changed meanwhile, nothing starts and the start is prepared again. A Cancel
                # pressed first refuses it; a Cancel pressed during it waits for this one creation and then kills it.
                generation = subprocess_utils.prepare_popen(args, spawn_context=lambda: _authorized_start(control),
                                                            stdin=stdin, stdout=stdout, stderr=stderr, **kwargs)
                extra = {} if generation is None else {"guardian_generation": generation}
                try:
                    with _authorized_start(control):
                        if stderr == subprocess.PIPE and self._errors is None:
                            self._errors = tempfile.TemporaryFile()
                        # The same Popen call as before on Windows (hidden console, the caller's arguments winning); on
                        # macOS the app window owns the FFmpeg it starts, so it ends with the window (v0.8.x P1B).
                        self.process = subprocess_utils.popen(
                            args, stdin=stdin, stdout=stdout,
                            stderr=self._errors if stderr == subprocess.PIPE else stderr, **kwargs, **extra)
                        try:
                            self._item = _Watched(self.process, output, control)
                            with _watched_lock:
                                _watched.add(self._item)
                        except BaseException:
                            # Started and not watched (out of memory here, say): it never runs on unowned.
                            self._end_unregistered()
                            raise
                    break
                except subprocess_utils.GuardianChanged:
                    if attempt == START_ATTEMPTS - 1:
                        raise
        except BaseException:
            self._close_errors()
            raise
        self.stdin, self.stdout = self.process.stdin, self.process.stdout
        self.stderr = None
        self.pid = self.process.pid
        if _asked_to_cancel(control):
            # A cancel check with no latch to be ordered against, latched while this started: killed now, not at the next look.
            self._item.decide(ConversionCancelled(CANCELLED_MESSAGE))
            self.kill()
        _wake.set()

    def _end_unregistered(self) -> None:
        with contextlib.suppress(OSError):
            self.process.kill()
        for pipe in (self.process.stdout, self.process.stdin):
            if pipe is not None:
                with contextlib.suppress(OSError, ValueError):
                    pipe.close()
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            self.process.wait(ABANDON_WAIT_SECONDS)

    def _wait_readable(self) -> None:
        """POSIX: until the pipe has something to read (or has ended), a look at a time, never holding the caller past
        :data:`ABANDON_WAIT_SECONDS` after a kill that did not take. A selector, not ``select()``: a busy application's
        pipe can be numbered past ``select``'s limit (v0.8.x P5-H-R1)."""
        if self._selector is None:
            self._selector = selectors.DefaultSelector()
            self._selector.register(self.stdout, selectors.EVENT_READ)
        while not self._selector.select(WATCH_SECONDS):
            self._raise_if_unstoppable()

    def read(self, size: int) -> bytes:
        """Exactly ``size`` bytes of FFmpeg's output, fewer only where it ends. On POSIX it waits as :meth:`blocks` does
        (v0.8.x P5-H-R1: the WAV header read is held to the same bound as the audio)."""
        if os.name != "posix":
            return self.stdout.read(size)
        data = b""
        while len(data) < size:
            self._wait_readable()
            block = self.stdout.read1(size - len(data))
            if not block:
                break
            data += block
        return data

    def _raise_if_unstoppable(self) -> None:
        """Killed (by the watchdog or this thread) for :data:`ABANDON_WAIT_SECONDS` and still running: stop waiting for it."""
        item = self._item
        if item.verdict_at is not None and time.monotonic() - item.verdict_at >= ABANDON_WAIT_SECONDS \
                and self.process.poll() is None:
            item.unconfirmed = True
            raise ProcessNotStopped(_not_stopped_text(self.pid))

    @property
    def returncode(self):
        return self.process.returncode

    def poll(self):
        return self.process.poll()

    def wait(self, timeout=None):
        return self.process.wait(timeout)

    def kill(self) -> None:
        with contextlib.suppress(OSError):
            self.process.kill()

    def _close_selector(self) -> None:
        if self._selector is not None:
            with contextlib.suppress(OSError, ValueError, KeyError):
                self._selector.close()
            self._selector = None

    def _close_errors(self) -> None:
        if self._errors is not None:
            with contextlib.suppress(OSError):
                self._errors.close()
            self._errors = None

    def blocks(self, size: int = BLOCK_BYTES) -> Iterator[bytes]:
        """FFmpeg's output as it comes, read by the calling thread. Ends when FFmpeg does, or is killed. On macOS and Linux
        the read never waits longer than one look at a time (v0.8.x P5-H-R1): a process killed and still not ended after
        :data:`ABANDON_WAIT_SECONDS` raises :class:`ProcessNotStopped` instead of holding this thread. Windows reads as it
        always has: its pipes cannot be waited on that way, and its kill does not fail to end a process."""
        if os.name != "posix":
            while block := self.stdout.read(size):
                self._item.progress_at = time.monotonic()
                yield block
            return
        while True:
            # read1: one read of what the pipe has, so a readable pipe never blocks. Bytes the header read left in the buffer
            # wait for the pipe's next data or its end, which a running or ending FFmpeg always gives.
            self._wait_readable()
            block = self.stdout.read1(size)
            if not block:
                return
            self._item.progress_at = time.monotonic()
            self._raise_if_unstoppable()
            yield block

    def error_text(self) -> bytes:
        """What FFmpeg has said, at most its last :data:`STDERR_TAIL_BYTES`."""
        if self._errors is None:
            return b""
        self._errors.seek(0, os.SEEK_END)
        self._errors.seek(max(0, self._errors.tell() - STDERR_TAIL_BYTES))
        return self._errors.read()

    def finish(self, timeout=None) -> int:
        """Wait for the process (a stalled one is the watchdog's to kill) and raise what the watchdog decided, if anything.
        With no ``timeout``, a process killed and still running :data:`ABANDON_WAIT_SECONDS` later raises
        :class:`ProcessNotStopped` (v0.8.x P5-H-R1)."""
        if timeout is not None:
            code = self.process.wait(timeout)
        else:
            while True:
                try:
                    code = self.process.wait(WATCH_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    self._raise_if_unstoppable()
        self._stop_watching()
        if self._item.verdict is not None:
            raise self._item.verdict
        return code

    def _stop_watching(self) -> None:
        with _watched_lock:
            _watched.discard(self._item)

    def abandon(self) -> None:
        """However this ended: nothing of this process stays running, open or watched. If it is still running after being
        killed and :data:`ABANDON_WAIT_SECONDS`, that is not hidden (v0.8.x P5-H-R1): it stays watched, and
        :class:`ProcessNotStopped` replaces whatever was ending this, a Cancel included; the watchdog keeps killing it and
        reaps and forgets it once it ends."""
        self.kill()
        self._close_selector()
        for pipe in (self.process.stdout, self.process.stdin):
            if pipe is not None:
                with contextlib.suppress(OSError, ValueError):
                    pipe.close()
        if self._item.unconfirmed:  # already given up on, and already said: nothing more to wait for here
            self._close_errors()
            return
        try:
            self.process.wait(ABANDON_WAIT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            self._item.unconfirmed = True
            self._close_errors()
            raise ProcessNotStopped(_not_stopped_text(self.pid)) from exc
        except (OSError, subprocess.SubprocessError):
            pass
        self._stop_watching()
        self._close_errors()

    def communicate(self, input=None, timeout=None):
        """As ``Popen.communicate``, in this thread. A failure of any kind kills the process before it is raised."""
        try:
            if input is not None and self.stdin is not None:
                # This tool hands pydub paths, never data, so this is here only to keep the interface honest. It is on a thread,
                # because writing here could block on FFmpeg waiting for its output to be read.
                threading.Thread(target=self._feed, args=(input,), daemon=True).start()
            output = None
            if self.stdout is not None:
                output = b"".join(self.blocks())
            self.finish(timeout)
            errors = self.error_text() if self._errors is not None else None
            return output, errors
        finally:
            self.abandon()

    def _feed(self, data: bytes) -> None:
        with contextlib.suppress(OSError, ValueError):
            self.stdin.write(data)
            self.stdin.close()


def _not_stopped_text(pid: int) -> str:
    return (f"FFmpeg (process {pid}) was stopped and had not ended {ABANDON_WAIT_SECONDS} seconds later, so this file is not "
            "reported as finished or cancelled. Nothing unfinished was saved. If it is still running, quit the application "
            "before using Retry Failed.")


def run(args, **kwargs) -> subprocess.CompletedProcess:
    """FFmpeg to the end, as ``subprocess_utils.run`` with ``stdout`` and ``stderr`` piped. Returns its exit code and last words."""
    child = Supervised(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kwargs)
    _output, errors = child.communicate()
    return subprocess.CompletedProcess(args, child.returncode, None, errors)


class _SubprocessForPydub:
    """What pydub finds where it expects the ``subprocess`` module."""

    Popen = Supervised
    PIPE = subprocess.PIPE
    DEVNULL = subprocess.DEVNULL
    STDOUT = subprocess.STDOUT

    def __getattr__(self, name):
        return getattr(subprocess, name)


_FOR_PYDUB = _SubprocessForPydub()


def install() -> None:
    """Point pydub at :class:`Supervised`. Idempotent, and imports nothing it does not already need."""
    import pydub.audio_segment
    import pydub.utils

    pydub.audio_segment.subprocess = _FOR_PYDUB
    pydub.audio_segment.NamedTemporaryFile = _named_temporary_file
    pydub.utils.Popen = Supervised


def uninstall() -> None:
    """pydub back on the real module: only for the negative control that proves the regression test can see the hang."""
    import pydub.audio_segment
    import pydub.utils

    pydub.audio_segment.subprocess = subprocess
    pydub.audio_segment.NamedTemporaryFile = tempfile.NamedTemporaryFile
    pydub.utils.Popen = subprocess.Popen


def installed() -> bool:
    import pydub.audio_segment
    import pydub.utils

    return (pydub.audio_segment.subprocess is _FOR_PYDUB and pydub.utils.Popen is Supervised
            and pydub.audio_segment.NamedTemporaryFile is _named_temporary_file)
