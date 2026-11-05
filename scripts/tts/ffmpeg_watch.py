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
end removes any still there (:func:`remove_temporaries`, which a fallback calls sooner, because it needs that disk space).

**The deadlines.** Measured from the last progress: bytes read from FFmpeg, or growth of the file it is writing.

* :data:`STALL_SECONDS`: no progress at all, nobody has cancelled: killed, and the file fails with :class:`ProcessingStalled`.
* Cancelled: killed within one :data:`WATCH_SECONDS`, whatever it was doing and however well it was going (v0.7.2). A Cancel stops
  active work; it does not let finished narration be assembled or encoded first. :func:`wake` lets the Cancel be noticed before
  the watchdog's next look. Nothing unfinished ever reaches a destination: that is :mod:`tts.publication`'s contract.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from shared import subprocess_utils
from shared.cancellation import ConversionCancelled

WATCH_SECONDS = 0.25
#: No progress at all, nobody has cancelled. A virus scanner opening a 4 GB WAV can hold FFmpeg for a minute or two; a whole
#: narration takes seconds to minutes in all.
STALL_SECONDS = 300
#: Enough of what FFmpeg said to explain a failure. It prints its build options first, which can run to a few KB.
STDERR_TAIL_BYTES = 64 * 1024
BLOCK_BYTES = 1024 * 1024
CANCELLED_MESSAGE = "Conversion cancelled by user."


class ProcessingStalled(RuntimeError):
    """FFmpeg stopped making progress and was killed. Nothing unfinished reaches a destination."""


@dataclass(frozen=True)
class _Control:
    cancel_check: Optional[Callable[[], bool]] = None
    temporaries: Optional[list] = None  # pydub's temporary files, while in a ``controlled`` block


_control: contextvars.ContextVar[_Control] = contextvars.ContextVar("ffmpeg_watch_control", default=_Control())


@contextlib.contextmanager
def controlled(cancel_check: Optional[Callable[[], bool]]):
    """Every FFmpeg this thread starts inside the block answers to ``cancel_check``: once it says so, the process is killed
    within one look, whatever stage of the conversion it belongs to."""
    _ensure_watchdog()
    token = _control.set(_Control(cancel_check, []))
    try:
        yield
    finally:
        remove_temporaries()
        _control.reset(token)


def current_cancel_check() -> Optional[Callable[[], bool]]:
    """The cancel check of the conversion this thread is running inside a :func:`controlled` block, or ``None``.

    The Edge request loops read it here (v0.7.2) rather than taking a new parameter, so the seams the offline test
    doubles stand in for keep their shape, and a request made anywhere in the conversion answers to the same Cancel the
    watchdog does. ``parallel_edgespeak`` copies the context into its executor threads for the same reason.
    """
    return _control.get().cancel_check


def _named_temporary_file(*args, **kwargs):
    """pydub's ``NamedTemporaryFile``. A file it asked to keep (it removes those itself, if nothing fails) is remembered."""
    handle = tempfile.NamedTemporaryFile(*args, **kwargs)
    remembered = _control.get().temporaries
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


def _watch_once() -> None:
    now = time.monotonic()
    with _watched_lock:
        items = list(_watched)
    for item in items:
        if item.verdict is None:
            item.verdict = _verdict_on(item, now)
            if item.verdict is not None:
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
        self.args = args
        self._errors = None
        if stderr == subprocess.PIPE:
            self._errors = tempfile.TemporaryFile()
            stderr = self._errors
        arguments = {**subprocess_utils._hidden_kwargs(), **kwargs}
        try:
            self.process = subprocess.Popen(args, stdin=stdin, stdout=stdout, stderr=stderr, **arguments)
        except BaseException:
            self._close_errors()
            raise
        self.stdin, self.stdout = self.process.stdin, self.process.stdout
        self.stderr = None
        self.pid = self.process.pid
        last = args[-1] if isinstance(args, (list, tuple)) and args else None
        # FFmpeg's last argument is what it writes, unless that is a pipe. For anything else the size just never changes.
        output = os.fspath(last) if isinstance(last, (str, os.PathLike)) and last != "-" else None
        self._item = _Watched(self.process, output, _control.get())
        with _watched_lock:
            _watched.add(self._item)
        _wake.set()

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

    def _close_errors(self) -> None:
        if self._errors is not None:
            with contextlib.suppress(OSError):
                self._errors.close()
            self._errors = None

    def blocks(self, size: int = BLOCK_BYTES) -> Iterator[bytes]:
        """FFmpeg's output as it comes, read by the calling thread. Ends when FFmpeg does, or is killed."""
        while block := self.stdout.read(size):
            self._item.progress_at = time.monotonic()
            yield block

    def error_text(self) -> bytes:
        """What FFmpeg has said, at most its last :data:`STDERR_TAIL_BYTES`."""
        if self._errors is None:
            return b""
        self._errors.seek(0, os.SEEK_END)
        self._errors.seek(max(0, self._errors.tell() - STDERR_TAIL_BYTES))
        return self._errors.read()

    def finish(self, timeout=None) -> int:
        """Wait for the process (a stalled one is the watchdog's to kill) and raise what the watchdog decided, if anything."""
        code = self.process.wait(timeout)
        self._stop_watching()
        if self._item.verdict is not None:
            raise self._item.verdict
        return code

    def _stop_watching(self) -> None:
        with _watched_lock:
            _watched.discard(self._item)

    def abandon(self) -> None:
        """However this ended: nothing of this process stays running, open or watched."""
        self.kill()
        for pipe in (self.process.stdout, self.process.stdin):
            if pipe is not None:
                with contextlib.suppress(OSError, ValueError):
                    pipe.close()
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            self.process.wait(30)
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
