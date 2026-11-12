"""Subprocess wrappers that suppress console windows on Windows.

Every external-binary call in the application (ffmpeg, ffprobe, etc.) must go
through :func:`run` or :func:`popen` so that no console window flashes when the
app is launched from the GUI (under ``pythonw.exe``). :func:`run_supervised`
starts its child through :func:`popen` too, and lets Cancel stop it (v0.7.2).

On non-Windows platforms these are thin pass-throughs to ``subprocess``.
"""

from __future__ import annotations

import collections
import contextlib
import contextvars
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


def _hidden_kwargs() -> dict[str, Any]:
    """Return kwargs that hide the console window on Windows; empty elsewhere."""
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def run(cmd, **kwargs) -> subprocess.CompletedProcess:
    """Drop-in replacement for ``subprocess.run`` with hidden console on Windows.

    Caller-supplied kwargs win over the hidden-window defaults so that explicit
    ``startupinfo``/``creationflags`` are still honoured if ever needed.
    """
    return subprocess.run(cmd, **{**_hidden_kwargs(), **kwargs})


def popen(cmd, **kwargs) -> subprocess.Popen:
    """Drop-in replacement for ``subprocess.Popen`` with hidden console on Windows."""
    return subprocess.Popen(cmd, **{**_hidden_kwargs(), **kwargs})


def check_output(cmd, **kwargs) -> bytes | str:
    """Drop-in replacement for ``subprocess.check_output`` with hidden console."""
    return subprocess.check_output(cmd, **{**_hidden_kwargs(), **kwargs})


# --------------------------------------------------------------------------- #
# Supervised FFmpeg steps that Cancel can stop (v0.7.2 Phase 6C, ACT72-023)
# --------------------------------------------------------------------------- #

#: How often a supervised child and its Cancel are looked at. Short enough that Cancel feels immediate.
SUPERVISED_POLL_SECONDS = 0.05
#: How long a stopped child is given to exit after ``terminate`` and again after ``kill``, so stopping is bounded.
SUPERVISED_GRACE_SECONDS = 2.0
#: The most of each stream kept. A duration probe prints a few kilobytes; a failure's reason is at the end of stderr.
SUPERVISED_TAIL_BYTES = 1024 * 1024


@dataclass(frozen=True)
class _Supervision:
    cancel_check: Callable[[], bool]
    acknowledge: Optional[Callable[[], None]]


_supervision: contextvars.ContextVar[Optional[_Supervision]] = contextvars.ContextVar(
    "subprocess_supervision", default=None)


@contextlib.contextmanager
def cancellable(cancel_check: Callable[[], bool], acknowledge: Optional[Callable[[], None]] = None):
    """Every :func:`run_supervised` this thread makes inside the block answers to ``cancel_check``.

    ``cancel_check`` must not block: it is asked while FFmpeg runs, so it is the controller's ``cancel_check``, never its
    ``checkpoint`` (which waits while paused). Pause therefore never touches a running step; it is honoured at the
    caller's next checkpoint. ``acknowledge`` is called once a Cancel has stopped or prevented a child, before
    :class:`ConversionCancelled` is raised: the controller's ``checkpoint``, which records that the worker observed the
    Cancel (and raises it), so the run can be settled as cancelled.
    """
    token = _supervision.set(_Supervision(cancel_check, acknowledge))
    try:
        yield
    finally:
        _supervision.reset(token)


def _asked_to_cancel(supervision: Optional[_Supervision]) -> bool:
    return supervision is not None and bool(supervision.cancel_check())


def _stop(child: subprocess.Popen, grace_seconds: float) -> bool:
    """Terminate, then kill if it will not go, through this ``Popen``'s own handle and nothing else; wait after each
    step, never for ever. True when the child was reaped. (On Windows both steps are ``TerminateProcess``.)"""
    for step in (child.terminate, child.kill):
        with contextlib.suppress(OSError):
            step()
        try:
            child.wait(timeout=grace_seconds)
            return True
        except subprocess.TimeoutExpired:
            continue
    return False


def _tail(stream, limit: int) -> bytes:
    """At most the last ``limit`` bytes of what the child wrote: one seek and one read, whatever it wrote."""
    stream.flush()
    size = stream.seek(0, os.SEEK_END)
    stream.seek(max(0, size - limit))
    return stream.read()


def _cancelled(supervision: _Supervision, child: Optional[subprocess.Popen], reaped: bool,
               grace_seconds: float) -> None:
    """Acknowledge a Cancel that stopped (or prevented) a child and raise it. Never a failure code."""
    # Imported here, never at the top: this module must import alone. ffmpeg_health imports it bare off scripts/shared
    # before the venv exists, and the optional-setup planning worker's reviewed source closure
    # (optional_setup_planning_bridge_v3.SOURCES) carries it without shared/cancellation.py. Neither ever cancels.
    try:
        from .cancellation import ConversionCancelled
    except ImportError:  # pragma: no cover - imported bare off scripts/shared
        from cancellation import ConversionCancelled  # type: ignore[no-redef]
    try:
        if supervision.acknowledge is not None:
            supervision.acknowledge()
        raise ConversionCancelled("Cancelled.")
    except ConversionCancelled as exc:
        if child is not None and not reaped:
            exc.add_note(f"process {child.pid} did not exit within {2 * grace_seconds:g} s of being stopped")
        raise


def run_supervised(args, *, poll_seconds: float = SUPERVISED_POLL_SECONDS,
                   grace_seconds: float = SUPERVISED_GRACE_SECONDS,
                   tail_bytes: int = SUPERVISED_TAIL_BYTES,
                   deadline_seconds: Optional[float] = None) -> subprocess.CompletedProcess:
    """Run one FFmpeg or ffprobe to its end, or stop it on Cancel or at its deadline, and always reap it.

    Returns ``CompletedProcess(args, returncode, stdout, stderr)`` with bytes, each at most its last ``tail_bytes``; a
    non-zero exit is the caller's to judge, exactly as with ``run``. Inside a :func:`cancellable` block:

    * Cancel already requested: nothing is started.
    * Cancel requested while it runs: seen within ``poll_seconds``; this very child is terminated, then killed, through
      its own handle (never by a name or a bare process id, so nothing else is touched), and waited on for at most
      ``grace_seconds`` after each step.

    Either way :class:`ConversionCancelled` is raised after the block's ``acknowledge``, never a return code, so no
    caller can mistake a Cancel for a failed or retryable step. Outside a block it simply runs to the end.

    ``deadline_seconds`` (v0.7.2 Phase 6E, ACT72-010; ``None``, the default, is no deadline, as for every caller before):
    a child still running that long after it started is stopped and reaped the same way, and
    :class:`subprocess.TimeoutExpired` is raised (``timeout`` the deadline, ``output``/``stderr`` the tails), as
    ``subprocess.run(timeout=...)`` does: never a return code, and never a Cancel. A Cancel seen at the same look wins.

    The child's output goes to two temporary files rather than pipes, so it can never block on a full pipe and there is no
    reader thread to wait on (v0.7.1's ``tts.ffmpeg_watch`` lesson); they are deleted when closed, which on Windows
    also happens if this program is killed. Its stdin is the null device and it gets no console window.
    """
    argv = list(args)
    supervision = _supervision.get()
    if _asked_to_cancel(supervision):
        _cancelled(supervision, None, True, grace_seconds)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
        started = time.monotonic()
        stopped = timed_out = False
        reaped = True
        try:
            while True:
                try:
                    child.wait(timeout=poll_seconds)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if _asked_to_cancel(supervision):
                    stopped = True
                    break
                if deadline_seconds is not None and time.monotonic() - started >= deadline_seconds:
                    timed_out = True
                    break
        finally:
            # Every route out, an exception in the loop included: a child started here is stopped and collected here.
            if child.returncode is None:
                reaped = _stop(child, grace_seconds)
        if stopped:
            _cancelled(supervision, child, reaped, grace_seconds)
        if timed_out:
            expired = subprocess.TimeoutExpired(argv, deadline_seconds, _tail(out, tail_bytes), _tail(err, tail_bytes))
            if not reaped:
                expired.add_note(f"process {child.pid} did not exit within {2 * grace_seconds:g} s of being stopped")
            raise expired
        return subprocess.CompletedProcess(argv, child.returncode, _tail(out, tail_bytes), _tail(err, tail_bytes))


#: What :func:`stop_media_children` may end. Never a detached helper: repair and cleanup deliberately outlive the window that started them.
_MEDIA_CHILDREN = frozenset({"ffmpeg.exe", "ffprobe.exe"})


def stop_media_children() -> list[int]:
    """End FFmpeg and ffprobe processes this process itself started, and return their pids. Windows only; never raises.

    A tool's worker blocks in :func:`run` while FFmpeg works. It is a daemon thread, so it dies with the interpreter, and FFmpeg does not
    notice: closing the window during an M4B Maker build left FFmpeg encoding with nobody to publish the result (measured, v0.7.2 Phase 3).
    A process is ended only if its parent is this very process and its image is one of the media tools, so a sentinel FFmpeg started by
    anyone else is untouched and a name alone is never enough.
    """
    if sys.platform != "win32":
        return []
    stopped: list[int] = []
    try:
        import ctypes
        import ctypes.wintypes as w

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD), ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG),
                        ("dwFlags", w.DWORD), ("szExeFile", w.WCHAR * 260)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = w.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        kernel32.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.OpenProcess.restype = w.HANDLE
        kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel32.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        kernel32.CloseHandle.argtypes = [w.HANDLE]
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if snapshot == w.HANDLE(-1).value:
            return stopped
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            mine = os.getpid()
            more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32ParentProcessID == mine and entry.szExeFile.lower() in _MEDIA_CHILDREN:
                    handle = kernel32.OpenProcess(0x0001, False, entry.th32ProcessID)  # PROCESS_TERMINATE
                    if handle:
                        if kernel32.TerminateProcess(handle, 1):
                            stopped.append(int(entry.th32ProcessID))
                        kernel32.CloseHandle(handle)
                more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:  # noqa: BLE001 - closing the application is never the moment to raise
        return stopped
    return stopped


_POPEN_PATCHED = False


def install_no_window_guard() -> None:
    """Force *every* child process on Windows to spawn without a console window.

    The app's own ffmpeg/ffprobe calls already go through :func:`run` /
    :func:`popen`, but pydub and edge-tts spawn ffmpeg through their *own*
    internal ``subprocess.Popen`` calls, which bypass those wrappers. During the
    TTS combine stage pydub exports/concatenates dozens of segments, flashing a
    console window for each one. This wraps ``subprocess.Popen`` itself so those
    internal spawns also inherit the hidden-window flags from
    :func:`_hidden_kwargs` — the one chokepoint every child process passes
    through, regardless of who calls it.

    No-op on non-Windows. Idempotent. Must be called once at startup, *before*
    pydub/edge-tts are imported, so a ``from subprocess import Popen`` inside
    those libraries binds to the wrapped class.
    """
    global _POPEN_PATCHED
    if _POPEN_PATCHED or sys.platform != "win32":
        return

    _original_popen = subprocess.Popen

    class _NoWindowPopen(_original_popen):  # type: ignore[valid-type, misc]
        def __init__(self, *args, **kwargs):
            hidden = _hidden_kwargs()
            # OR our hidden-window creationflags into anything the caller passed
            # so an explicit flag is preserved rather than clobbered.
            kwargs["creationflags"] = (
                kwargs.get("creationflags", 0) | hidden["creationflags"]
            )
            # Only inject the hidden STARTUPINFO when the caller supplied none;
            # our own wrappers already pass one.
            if kwargs.get("startupinfo") is None:
                kwargs["startupinfo"] = hidden["startupinfo"]
            super().__init__(*args, **kwargs)

    subprocess.Popen = _NoWindowPopen  # type: ignore[misc]
    _POPEN_PATCHED = True


# --------------------------------------------------------------------------- #
# Showing a folder in the file manager without waiting for it (v0.7.2 Phase 8, ACT72-062)
# --------------------------------------------------------------------------- #

#: The most folders that may be waiting for the file manager at once. A person asks for one or two; more than this
#: means the file manager has stopped answering, so a further request is refused at once instead of piling up.
REVEAL_LIMIT = 4
#: How long the macOS or Linux opener is waited for before it is left to finish by itself.
REVEAL_OPENER_SECONDS = 10.0


class RevealRequest:
    """One request to show a folder in the file manager, and how it ended.

    ``reason`` is ``None`` while the request is waiting and after it was handed over; otherwise it says why the file
    manager could not be asked. :meth:`on_failure` is told that reason exactly once, on whichever thread learns it, so
    the callable must be safe on any thread and must hold no Tk object: put a line on a queue, never touch a widget
    (a Tk object released on a thread that is not Tk's own ends the program).
    """

    __slots__ = ("target", "_lock", "_done", "_reason", "_callbacks")

    def __init__(self, target: str) -> None:
        self.target = target
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._reason: Optional[str] = None
        self._callbacks: list[Callable[[str], None]] = []

    @property
    def done(self) -> bool:
        return self._done.is_set()

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    def wait(self, timeout: Optional[float] = None) -> bool:
        """True once the request has ended either way. Nothing in the application waits; a test may."""
        return self._done.wait(timeout)

    def on_failure(self, callback: Callable[[str], None]) -> None:
        with self._lock:
            if not self._done.is_set():
                self._callbacks.append(callback)
                return
            reason = self._reason
        if reason is not None:
            _tell(callback, reason)

    def _finish(self, reason: Optional[str]) -> None:
        with self._lock:
            self._reason = reason
            self._done.set()
            callbacks, self._callbacks = self._callbacks, []
        if reason is not None:
            for callback in callbacks:
                _tell(callback, reason)


def _tell(callback: Callable[[str], None], reason: str) -> None:
    """A listener that raises must not stop the requests waiting behind this one."""
    with contextlib.suppress(Exception):
        callback(reason)


_reveal_lock = threading.Lock()
#: Requests not yet ended, oldest first; the first is the one the file manager is being asked for now.
_reveal_queue: collections.deque = collections.deque()
_reveal_thread: Optional[threading.Thread] = None
#: The thread class as it was when this module loaded, so replacing ``threading.Thread`` elsewhere changes nothing here.
_Thread = threading.Thread


def reveal_in_file_manager(path) -> RevealRequest:
    """Ask the OS file manager to show ``path``, and return at once. Never raises.

    The operating system's own call can take many seconds while Explorer is busy or restarting (36.9 s measured in
    v0.7.2 Phase 7B), and it used to be made by the caller: a window's own thread, which froze for that long when the
    M4B Converter showed its output folder at the end of a run (ACT72-062). It is now made on one background thread,
    one request at a time, so no window waits for it. That thread is a daemon and nothing joins it, so closing the
    application never waits for the file manager either; it starts no process of its own on Windows.

    A folder that is already waiting is not asked for twice (the same request comes back), and at most
    :data:`REVEAL_LIMIT` different folders wait: past that the file manager has stopped answering, and the new request
    ends at once with that reason. Opening a folder stays a convenience, so a failure is never raised; the returned
    :class:`RevealRequest` tells a caller that wants to say so.
    """
    global _reveal_thread
    request = RevealRequest(str(Path(path)))
    with _reveal_lock:
        for waiting in _reveal_queue:
            if waiting.target == request.target:
                return waiting
        if len(_reveal_queue) < REVEAL_LIMIT:
            _reveal_queue.append(request)
            # A thread seen here has not yet decided to end (it decides under this lock), so it will take this request.
            if _reveal_thread is not None and _reveal_thread.is_alive():
                return request
            try:
                _reveal_thread = _Thread(target=_reveal_waiting, name="reveal-in-file-manager", daemon=True)
                _reveal_thread.start()
                return request
            except Exception as exc:  # noqa: BLE001 - no thread to be had; say so instead of asking on the caller's
                _reveal_thread = None
                _reveal_queue.remove(request)
                reason = f"{type(exc).__name__}: {exc}"
        else:
            reason = f"the file manager has not answered {REVEAL_LIMIT} earlier requests yet"
    request._finish(reason)
    return request


def _reveal_waiting() -> None:
    """The background thread: ask for each waiting folder in turn, then end. Holds no lock while the system works."""
    global _reveal_thread
    while True:
        with _reveal_lock:
            if not _reveal_queue:
                _reveal_thread = None
                return
            request = _reveal_queue[0]
        reason = _ask_file_manager(request.target)
        with _reveal_lock:
            _reveal_queue.popleft()
        request._finish(reason)


def _ask_file_manager(target: str, platform: Optional[str] = None) -> Optional[str]:
    """Make the operating system's own call and wait for it: the one place a folder is really opened.

    ``None`` when the request was handed over, otherwise why it could not be. Never raises. ``os.startfile`` on Windows
    (no console window, no process of ours), ``open`` on macOS and ``xdg-open`` on Linux; the two openers are waited for
    briefly so they are reaped, and one still running after :data:`REVEAL_OPENER_SECONDS` is the system's to finish.
    """
    platform = sys.platform if platform is None else platform
    try:
        if platform == "win32":
            with _shell_apartment():
                os.startfile(target)  # type: ignore[attr-defined]
            return None
        opener = "open" if platform == "darwin" else "xdg-open"
        child = popen([opener, target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL)
        try:
            code = child.wait(timeout=REVEAL_OPENER_SECONDS)
        except subprocess.TimeoutExpired:
            return None
        return None if code == 0 else f"{opener} ended with code {code}"
    except Exception as exc:  # noqa: BLE001 - reported to whoever asked, never raised into a window
        return f"{type(exc).__name__}: {exc}"


@contextlib.contextmanager
def _shell_apartment():
    """Give the calling thread the COM apartment Windows asks of a thread that calls the shell.

    ``os.startfile`` is ``ShellExecute``, whose documentation asks its caller to initialise COM single-threaded with
    OLE1 DDE disabled, because the shell may hand the request to a COM extension. A window's thread usually had that
    already; the background thread above has nothing until this gives it. A failure to initialise is not an error: the
    call is then made exactly as it always was.
    """
    release = None
    try:
        import ctypes

        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        # COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE. S_OK (0) and S_FALSE (1) must both be balanced.
        if ole32.CoInitializeEx(None, 0x2 | 0x4) in (0, 1):
            release = ole32.CoUninitialize
    except Exception:  # noqa: BLE001 - no COM to be had; the shell call still works for a plain folder
        release = None
    try:
        yield
    finally:
        if release is not None:
            with contextlib.suppress(Exception):
                release()
