"""The right to move a separately installed voice engine: every lock that says it is in use, taken together or not at all.

v0.7.0 P04C (plan Revision 2 §5.5). P04B proved natively that renaming the app's ``.venv`` aside is NOT stopped by a
Qwen3 worker running from ``.venv/engines/qwen3``: Windows lets a folder be renamed while programs inside it are
mapped into memory, so a running engine was carried to ``.venv.replaced`` and back under a live conversion. Nothing
the file system does can be relied on here; the only thing that can is the locks the engine's own users hold.

Three files in the engine's runtime folder (``files/runtime-data/qwen3/``), all with ``tts.qwen3_runtime.FileLock``'s
protocol -- a non-blocking exclusive lock on the first byte -- so this module and the app's Qwen3 code see one lock,
not two:

* ``setup.lock``     -- an install or repair of the engine (``tts.qwen3_setup.InstallLock``);
* ``inference.lock`` -- a conversion, transcription or model check, held by the app for the whole run
  (``tts.qwen3_runtime.inference_lease``; ``InstallLock`` takes it too);
* ``engine.lock``    -- held by the worker process itself for as long as it runs (``tts.qwen3_worker``), so even a
  worker whose app has gone is seen.

A :class:`Lease` takes them in that order, never waits, and on any refusal releases what it took (reverse order) and
says which one refused. The operating system drops every one of them when its process ends, however it ends, so
there is no stale-lock case. The machine-wide ``MachineGuard`` is deliberately not one of them: it keeps every copy
of the app to one model on the GPU at a time and protects no file of this copy, and every user of this copy's
engine already holds ``inference.lock`` or ``engine.lock``.

Standard library only: the bootstrap runs it on a base interpreter before any environment exists, and the worker
runs in the engine's own environment. Taking a lock creates its (empty) file; nothing else is written or removed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from shared import venv_layout

SETUP_LOCK = "setup.lock"
INFERENCE_LOCK = "inference.lock"
ENGINE_LOCK = "engine.lock"
#: The one order every holder of more than one of them takes them in.
ORDER = (SETUP_LOCK, INFERENCE_LOCK, ENGINE_LOCK)

BUSY = "busy"
UNAVAILABLE = "unavailable"

#: What to tell a person when each lock is held by someone else. Every one ends the same way: nothing was changed.
BUSY_MESSAGES = {
    SETUP_LOCK: "The Qwen3 voices are being installed or repaired right now.",
    INFERENCE_LOCK: "A Qwen3 conversion, transcription or model check is running right now.",
    ENGINE_LOCK: "The Qwen3 voice engine is still running (a conversion that has not stopped yet).",
}
NOTHING_CHANGED = ("Nothing was changed. Let it finish, or cancel it and close the app, then run this again.")
UNAVAILABLE_MESSAGE = ("The app could not check whether the Qwen3 voices are in use ({detail}), so the environment "
                       "was left exactly as it was. Nothing was changed.")


def runtime_dir(repo_root) -> Path:
    """``files/runtime-data/qwen3/`` of the copy of the app at *repo_root* (``tts.qwen3_runtime.runtime_dir``)."""
    return Path(repo_root) / "files" / "runtime-data" / "qwen3"


class FileLock:
    """``tts.qwen3_runtime.FileLock``'s protocol: a non-blocking exclusive lock on byte 0, held while this is open.

    ``acquire`` returns True or False for held/busy and raises ``OSError`` when the lock file cannot be opened at all,
    so a caller can tell "someone has it" from "it cannot be checked".
    """

    def __init__(self, path) -> None:
        self.path = Path(path)
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR)
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            os.close(fd)


class Refused(Exception):
    """The lease was not granted. ``lock`` names the lock that refused (``None`` when the folder itself was unusable),
    ``reason`` is :data:`BUSY` or :data:`UNAVAILABLE`, and the message is fit to show a non-technical user."""

    def __init__(self, message: str, *, lock: Optional[str], reason: str) -> None:
        super().__init__(message)
        self.lock = lock
        self.reason = reason


class Lease:
    """All three locks of one copy's engine, or none of them.

    *folder* is that copy's ``files/runtime-data/qwen3``; *root* is the copy's own folder, which bounds where the lock
    folder may be reached from. A link anywhere between them is refused rather than followed: the locks must be the
    files the engine's users lock, not a redirect.
    """

    def __init__(self, folder, *, root) -> None:
        self.folder = Path(folder)
        self.root = Path(root)
        self._locks = [FileLock(self.folder / name) for name in ORDER]
        self.taken: list[str] = []

    @property
    def held(self) -> bool:
        return len(self.taken) == len(ORDER)

    def take(self) -> None:
        """All three, in :data:`ORDER`, or raise :class:`Refused` holding none. (Not named ``acquire``: the bootstrap's
        call-graph guards reserve that name for FFmpeg acquisition, which no repair may reach.)"""
        if self.held:
            return
        try:
            linked = venv_layout.unsafe_component(self.root, self.folder)
            if linked is not None:
                raise Refused(UNAVAILABLE_MESSAGE.format(detail=f"{linked.name} is a link or lies outside the app "
                                                                "folder"), lock=None, reason=UNAVAILABLE)
            self.folder.mkdir(parents=True, exist_ok=True)
            linked = venv_layout.unsafe_component(self.root, self.folder)  # nothing appeared behind it meanwhile
            if linked is not None:
                raise Refused(UNAVAILABLE_MESSAGE.format(detail=f"{linked.name} is a link"), lock=None,
                              reason=UNAVAILABLE)
            for name, lock in zip(ORDER, self._locks):
                try:
                    got = lock.acquire()
                except OSError as exc:
                    raise Refused(UNAVAILABLE_MESSAGE.format(detail=f"{name}: {exc.strerror or exc}"), lock=name,
                                  reason=UNAVAILABLE) from exc
                if not got:
                    raise Refused(f"{BUSY_MESSAGES[name]} {NOTHING_CHANGED}", lock=name, reason=BUSY)
                self.taken.append(name)
        except BaseException:
            self.release()
            raise

    def release(self) -> None:
        for lock in reversed(self._locks):
            lock.release()
        self.taken.clear()

    def __enter__(self) -> "Lease":
        self.take()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
