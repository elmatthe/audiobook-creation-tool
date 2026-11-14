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

**Two engines since v0.8.0.** OmniVoice is held in the same parent, at ``.venv/engines/omnivoice`` (owner decision
2026-11-13), so moving the parent moves it too. Its installer takes the same ``setup.lock`` first
(``tts.omnivoice_setup.InstallLock``), and its conversions and its worker hold their own ``inference.lock`` and
``engine.lock`` in ``files/runtime-data/omnivoice/``. :class:`EnvironmentLease` is the right to move the parent: Qwen3's
three, then OmniVoice's two, all or none. It is taken whether or not either engine is installed, for the reason
``setup.lock`` is: an install may be about to create its folder.

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

QWEN3 = "qwen3"
OMNIVOICE = "omnivoice"
#: OmniVoice's own two locks, in its own runtime folder, taken after Qwen3's three. Its installs and repairs are
#: already covered by ``setup.lock`` above, which ``tts.omnivoice_setup.InstallLock`` takes first.
OMNIVOICE_ORDER = (INFERENCE_LOCK, ENGINE_LOCK)
OMNIVOICE_BUSY_MESSAGES = {
    INFERENCE_LOCK: "An OmniVoice conversion or engine check is running right now.",
    ENGINE_LOCK: "The OmniVoice voice engine is still running (a conversion that has not stopped yet).",
}
OMNIVOICE_UNAVAILABLE_MESSAGE = ("The app could not check whether the OmniVoice voices are in use ({detail}), so the "
                                 "environment was left exactly as it was. Nothing was changed.")


def runtime_dir(repo_root) -> Path:
    """``files/runtime-data/qwen3/`` of the copy of the app at *repo_root* (``tts.qwen3_runtime.runtime_dir``)."""
    return Path(repo_root) / "files" / "runtime-data" / "qwen3"


def omnivoice_runtime_dir(repo_root) -> Path:
    """``files/runtime-data/omnivoice/`` of the copy at *repo_root* (``tts.omnivoice_runtime.runtime_dir``)."""
    return Path(repo_root) / "files" / "runtime-data" / "omnivoice"


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
    ``reason`` is :data:`BUSY` or :data:`UNAVAILABLE`, ``engine`` says whose lock it was (:data:`QWEN3` or
    :data:`OMNIVOICE`), ``busy_sentence`` is that lock's own sentence when it was busy (else ``None``), and the message
    is fit to show a non-technical user."""

    def __init__(self, message: str, *, lock: Optional[str], reason: str, engine: str = QWEN3,
                 busy_sentence: Optional[str] = None) -> None:
        super().__init__(message)
        self.lock = lock
        self.reason = reason
        self.engine = engine
        self.busy_sentence = busy_sentence


class Lease:
    """All the locks of one engine of one copy, or none of them (by default Qwen3's three).

    *folder* is that copy's ``files/runtime-data/qwen3``; *root* is the copy's own folder, which bounds where the lock
    folder may be reached from. A link anywhere between them is refused rather than followed: the locks must be the
    files the engine's users lock, not a redirect. *order*, *messages*, *unavailable* and *engine* name another engine's
    locks and words (OmniVoice's, through :class:`EnvironmentLease`).
    """

    def __init__(self, folder, *, root, order: tuple[str, ...] = ORDER, messages: Optional[dict] = None,
                 unavailable: str = UNAVAILABLE_MESSAGE, engine: str = QWEN3) -> None:
        self.folder = Path(folder)
        self.root = Path(root)
        self.order = tuple(order)
        self.messages = BUSY_MESSAGES if messages is None else messages
        self.unavailable = unavailable
        self.engine = engine
        self._locks = [FileLock(self.folder / name) for name in self.order]
        self.taken: list[str] = []

    @property
    def held(self) -> bool:
        return len(self.taken) == len(self.order)

    def take(self) -> None:
        """All three, in :data:`ORDER`, or raise :class:`Refused` holding none. (Not named ``acquire``: the bootstrap's
        call-graph guards reserve that name for FFmpeg acquisition, which no repair may reach.)"""
        if self.held:
            return
        try:
            linked = venv_layout.unsafe_component(self.root, self.folder)
            if linked is not None:
                raise Refused(self.unavailable.format(detail=f"{linked.name} is a link or lies outside the app "
                                                             "folder"), lock=None, reason=UNAVAILABLE,
                              engine=self.engine)
            self.folder.mkdir(parents=True, exist_ok=True)
            linked = venv_layout.unsafe_component(self.root, self.folder)  # nothing appeared behind it meanwhile
            if linked is not None:
                raise Refused(self.unavailable.format(detail=f"{linked.name} is a link"), lock=None,
                              reason=UNAVAILABLE, engine=self.engine)
            for name, lock in zip(self.order, self._locks):
                try:
                    got = lock.acquire()
                except OSError as exc:
                    raise Refused(self.unavailable.format(detail=f"{name}: {exc.strerror or exc}"), lock=name,
                                  reason=UNAVAILABLE, engine=self.engine) from exc
                if not got:
                    raise Refused(f"{self.messages[name]} {NOTHING_CHANGED}", lock=name, reason=BUSY,
                                  engine=self.engine, busy_sentence=self.messages[name])
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


class EnvironmentLease:
    """The right to move one copy's ``.venv``: every lock of every engine held in it, or none of them.

    Qwen3's three (:data:`ORDER`, which begin with the ``setup.lock`` every install and repair of this copy takes),
    then OmniVoice's two (:data:`OMNIVOICE_ORDER`). Never waits; a refusal by either engine releases everything
    already taken, in reverse, and is that engine's own :class:`Refused`. *root* is the copy's own folder.
    """

    def __init__(self, root) -> None:
        self.root = Path(root)
        self._leases = (
            Lease(runtime_dir(self.root), root=self.root),
            Lease(omnivoice_runtime_dir(self.root), root=self.root, order=OMNIVOICE_ORDER,
                  messages=OMNIVOICE_BUSY_MESSAGES, unavailable=OMNIVOICE_UNAVAILABLE_MESSAGE, engine=OMNIVOICE),
        )

    @property
    def held(self) -> bool:
        return all(lease.held for lease in self._leases)

    @property
    def taken(self) -> list[tuple[str, str]]:
        """``(engine, lock)`` for every lock held, in the order taken."""
        return [(lease.engine, name) for lease in self._leases for name in lease.taken]

    def take(self) -> None:
        """Both engines' locks, or raise :class:`Refused` holding none."""
        if self.held:
            return
        try:
            for lease in self._leases:
                lease.take()
        except BaseException:
            self.release()
            raise

    def release(self) -> None:
        for lease in reversed(self._leases):
            lease.release()

    def __enter__(self) -> "EnvironmentLease":
        self.take()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
