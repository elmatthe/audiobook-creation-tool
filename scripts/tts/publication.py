"""How a finished narration reaches its final name (v0.7.1).

The one contract every route publishes through: Edge direct and folder in the panel, the three local engines in the panel,
the standalone ``batch_convert`` and the standalone ``runner``.

* The final name appears only once, complete. The MP3 is finished and checked first, then written to a private staging
  file **beside the destination** (so on its filesystem, whatever the system temp folder is on), flushed to disk, and
  only then given its final name by one same-filesystem operation. A copy that dies part way, a full disk or a Cancel
  leaves nothing under the final name and whatever was there untouched.
* ``overwrite=False`` is enforced by that operation itself, not by a look beforehand, so a file that appears after
  planning is never replaced. Windows: ``os.rename`` is ``MoveFileExW`` without ``MOVEFILE_REPLACE_EXISTING`` or
  ``MOVEFILE_COPY_ALLOWED``: it fails if the name is taken and never copies. Elsewhere ``os.rename`` replaces silently,
  so ``os.link`` makes the name (it fails if the name is taken) and the staged name is then removed. A filesystem that
  cannot do this fails with a clear message; there is deliberately no fallback to a check followed by a move.
* ``overwrite=True`` replaces with ``os.replace``: the old file stays valid until the instant the new one takes its
  name, and a locked or unwritable destination keeps the old file.
* A failed attempt removes only the staging file it created. Nothing here ever deletes a file because of where it is or
  what it is called, and nothing here ever removes a destination.
* Cancel does not reach in here. It stops a conversion at the synthesis checkpoints; a narration that got past the last
  one is finished work, possibly hours of it, and is assembled, published and counted as ever (Decisions, 2026-11-03). So
  a Cancel pressed during publication costs at most the moments the copy takes, and never a partial file.
* A staging file left by a killed process is recognised by its exact name (:func:`sweep_orphans`) and removed only when
  the process named in it is gone and the file has lain untouched for an hour. It never ends in ``.mp3``, so nothing can
  mistake it for an output.

Measured on HOME-PC NTFS: eight processes racing for one name, 100 rounds: exactly one winner every round and no partial
view, for both ``os.rename`` and ``os.link``; the control (``exists()`` then ``os.replace``) had two or more winners in
42 of 100 (``files/dev-work/act071-remediation/logs/noclobber-primitives-100.jsonl``, ignored). Not measured: exFAT and
network drives, on either primitive, and a real second volume.
"""

from __future__ import annotations

import errno
import os
import re
import secrets
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

from shared import output_paths

#: ``.act-tmp-<pid: 8 hex><token: 5 hex>.part``, 27 characters and no stem. ``output_names`` keeps 20 units of room beyond
#: every planned name and that name is at least 7 long (``x-L.mp3``), so a folder that can hold the output can hold this.
#: The pid says whose it is (:func:`sweep_orphans`); the token only has to differ among one process's attempts, and
#: ``O_EXCL`` guards that.
STAGE_SUFFIX = ".part"
_STAGE_NAME = re.compile(re.escape(output_paths.TEMP_SIBLING_PREFIX) + r"([0-9a-f]{8})[0-9a-f]{5}"
                         + re.escape(STAGE_SUFFIX))
STAGE_NAME_LENGTH = len(output_paths.TEMP_SIBLING_PREFIX) + 13 + len(STAGE_SUFFIX)

_COPY_CHUNK_BYTES = 1024 * 1024
#: A virus scanner or indexer holds a new file for a moment; a media player may hold a destination for longer. Bounded:
#: about 3 s, then the attempt fails and says so, and the old file is still there.
_LOCK_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6)
#: Access denied (also a delete in progress), sharing violation, lock violation. Python's own ``open`` reports these as a
#: bare EACCES with no Windows error attached, and that is how a scanner holding a just-closed file usually looks.
_WINDOWS_TRANSIENT = {None, 5, 32, 33}

#: Quieter than this at its loudest, the whole narration counts as silent: the -70 dBFS the final-tail policy uses as
#: the floor of what might still be sound (``audio_tail.CONSERVATIVE_THRESHOLD_DBFS``).
SILENCE_DBFS = -70.0

#: Another computer sharing this folder has process numbers that mean nothing here, so a file this recent may be in use
#: even when the process named in it does not exist on this computer.
ORPHAN_MIN_AGE_SECONDS = 3600

_IS_WINDOWS = os.name == "nt"
_active: set[str] = set()  # staging files this process's attempts are using right now
_active_lock = threading.Lock()


class PublicationError(OSError):
    """The finished narration was not published. Whatever was at the destination is unchanged.

    An :class:`OSError`, so ``edge_failures`` classes it as a local problem and no route synthesises the file again.
    """


class DestinationExists(PublicationError, FileExistsError):
    """``overwrite=False`` and the destination's name is taken."""


def refuse_existing(destination, overwrite: bool) -> None:
    """Fail before any synthesis when the result could not be published anyway. A courtesy, never the guarantee:
    the guarantee is the publishing operation itself."""
    if not overwrite and os.path.lexists(destination):
        raise DestinationExists(_exists_message(Path(destination)))


def _exists_message(destination: Path) -> str:
    return f"{destination} already exists and overwriting is off, so it was left as it is"


def _is_transient(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) and (not _IS_WINDOWS or getattr(exc, "winerror", None) in _WINDOWS_TRANSIENT)


def _explain(destination: Path, exc: OSError) -> PublicationError:
    number = getattr(exc, "errno", None)
    unsupported = {errno.EXDEV, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}
    if not _IS_WINDOWS:
        unsupported.add(errno.EPERM)  # what link(2) answers on a filesystem without hard links
    if number == errno.ENOSPC or getattr(exc, "winerror", None) == 39:  # ERROR_HANDLE_DISK_FULL arrives as EINVAL
        why = "there is not enough free disk space there"
    elif number in unsupported:
        why = "this drive cannot publish a file without risking what is already there; choose another output folder"
    elif isinstance(exc, PermissionError):
        why = "the file or its folder is in use by another program or is read-only; close it and use Retry Failed"
    else:
        why = f"{type(exc).__name__}: {exc}"
    return PublicationError(f"{destination.name} could not be saved in {destination.parent}: {why}")


def _while_locked(action, sleep=time.sleep):
    """Run *action*, waiting out a lock for as long as :data:`_LOCK_RETRY_DELAYS` allows."""
    for delay in (*_LOCK_RETRY_DELAYS, None):
        try:
            return action()
        except OSError as exc:
            if delay is None or not _is_transient(exc):
                raise
            sleep(delay)


def _copy_chunk(reader, writer) -> bool:
    """One step of the copy into staging. ``False`` at the end of the file. A separate function so a test can make a
    copy fail part way, as a full disk or a lost drive does."""
    chunk = reader.read(_COPY_CHUNK_BYTES)
    if not chunk:
        return False
    writer.write(chunk)
    return True


def _publish_no_clobber(staged: Path, destination: Path) -> None:
    """Give *staged* the name *destination* only if the name is free, in one operation."""
    if _IS_WINDOWS:
        os.rename(staged, destination)
    else:
        os.link(staged, destination)
        try:
            os.unlink(staged)
        except OSError:
            pass  # published all the same; the leftover is only a second name for the same file (sweep_orphans)


def _publish_replacing(staged: Path, destination: Path) -> None:
    os.replace(staged, destination)


class Stage:
    """One attempt's private staging file for one destination. A context manager: leaving it unpublished removes the
    staging file, and only that.

    ::

        with Stage(destination, overwrite=False) as stage:
            encode_into(stage.path)        # or stage.receive(finished_file)
            stage.publish()
    """

    def __init__(self, destination, *, overwrite: bool = False, sleep: Callable[[float], None] = time.sleep) -> None:
        self.destination = Path(destination)
        self.overwrite = bool(overwrite)
        self.path: Optional[Path] = None
        self.published = False
        self._sleep = sleep

    def __enter__(self) -> "Stage":
        self._create()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if tb is not None:
            # A failed pydub export is still holding the staging file open in a frame of this traceback, and Windows
            # will not delete an open file. Those frames have finished, so their locals can go now.
            traceback.clear_frames(tb)
        self.discard()

    def _create(self) -> None:
        pid = f"{os.getpid() & 0xFFFFFFFF:08x}"
        try:
            self.destination.parent.mkdir(parents=True, exist_ok=True)
            for _ in range(64):
                name = f"{output_paths.TEMP_SIBLING_PREFIX}{pid}{secrets.token_hex(3)[:5]}{STAGE_SUFFIX}"
                candidate = self.destination.parent / name
                try:
                    # O_EXCL: this attempt made this file, which is what makes removing it later "its own".
                    handle = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o666)
                except FileExistsError:
                    continue
                os.close(handle)
                self.path = candidate
                with _active_lock:
                    _active.add(os.path.normcase(str(candidate)))
                return
        except OSError as exc:
            raise _explain(self.destination, exc) from exc
        raise PublicationError(f"{self.destination.name} could not be saved: no free private name beside it")

    def receive(self, finished) -> None:
        """Copy a finished file into staging: this is the only way a file from another folder (perhaps another drive)
        reaches a destination. Always a copy, so the output takes the destination folder's permissions."""
        def copy() -> tuple[int, int]:
            with open(finished, "rb") as reader, open(self.path, "wb") as writer:
                while _copy_chunk(reader, writer):
                    pass
                writer.flush()
                os.fsync(writer.fileno())
            return os.path.getsize(self.path), os.path.getsize(finished)

        try:
            copied, expected = _while_locked(copy, self._sleep)
        except OSError as exc:
            raise _explain(self.destination, exc) from exc
        if copied != expected:
            raise PublicationError(f"{self.destination.name} could not be saved: the copy is {copied} bytes "
                                   f"of {expected}")

    def _flush_staged(self) -> None:
        """Refuse an empty result, and make sure what is about to get the final name is really on the disk."""
        if os.path.getsize(self.path) <= 0:
            raise PublicationError(f"{self.destination.name} was not saved: the finished file is empty")
        with open(self.path, "rb+") as handle:
            os.fsync(handle.fileno())

    def publish(self) -> Path:
        """Give the staged file its final name, or raise with nothing changed."""
        if self.path is None or self.published:
            raise RuntimeError("this stage has nothing to publish")
        if self.overwrite and (output_paths._is_link(self.destination) or self.destination.is_dir()):
            raise PublicationError(f"{self.destination} is a link or a folder, which is never replaced")
        publisher = _publish_replacing if self.overwrite else _publish_no_clobber

        def flush_and_publish() -> None:
            self._flush_staged()
            publisher(self.path, self.destination)

        try:
            _while_locked(flush_and_publish, self._sleep)
        except FileExistsError as exc:
            raise DestinationExists(_exists_message(self.destination)) from exc
        except PublicationError:
            raise
        except OSError as exc:
            raise _explain(self.destination, exc) from exc
        self.published = True
        self._forget()
        return self.destination

    def discard(self) -> bool:
        """Remove this attempt's staging file, if it is still there. ``False`` if the OS will not let go of it, which
        never fails the attempt: :func:`sweep_orphans` can remove it later."""
        if self.path is None or self.published:
            return False
        path = self.path
        for delay in (*_LOCK_RETRY_DELAYS, None):
            output_paths.discard_temporary(path)
            if not os.path.lexists(path):
                self._forget()
                self.path = None
                return True
            if delay is not None:
                self._sleep(delay)
        self._forget()
        return False

    def _forget(self) -> None:
        with _active_lock:
            _active.discard(os.path.normcase(str(self.path)))


def publish_file(finished, destination, *, overwrite: bool = False) -> Path:
    """Publish an already finished file at *destination* under the contract above. *finished* is left where it is."""
    with Stage(destination, overwrite=overwrite) as stage:
        stage.receive(finished)
        return stage.publish()


# --------------------------------------------------------------------------- is the finished audio any good?


def check_narration(segment) -> None:
    """What must hold before a whole narration is worth encoding."""
    require_audible(segment)
    if len(segment.raw_data) >= 2 ** 32:
        raise PublicationError("This narration is over 24 hours long, more than one MP3 can hold here (the encoder goes "
                               "through a WAV file, whose sizes stop at 4 GB). Split the source into shorter files.")


def require_audible(segment) -> None:
    """Refuse a narration that is silent from end to end: a silent MP3 must not count as a success."""
    if segment.max_dBFS < SILENCE_DBFS:
        raise PublicationError("The finished narration is silent, so it was not saved. The source may hold no text "
                               "the voice can read.")


def verify_finished_mp3(path, expected_ms: Optional[float] = None) -> None:
    """Refuse a file that is not an MP3, whose audio is not as long as what was encoded, or that is cut short."""
    from mutagen import MutagenError
    from mutagen.mp3 import MP3

    name = Path(path).name

    def can_be_read() -> None:
        with open(path, "rb"):  # a scanner holds a just-closed file for a moment; that is not an invalid MP3
            pass

    try:
        _while_locked(can_be_read)
        info = MP3(path).info
        length, implied_bytes, size = info.length, info.bitrate / 8 * info.length, os.path.getsize(path)
    except (MutagenError, OSError) as exc:
        raise PublicationError(f"The finished narration {name} is not a valid MP3: {exc}") from exc
    if length <= 0:
        raise PublicationError(f"The finished narration {name} holds no audio.")
    if size + 4096 < 0.99 * implied_bytes:  # the encoder's header states the whole length; the frames for it are missing
        raise PublicationError(f"The finished narration {name} is cut short: {size} bytes of about "
                               f"{int(implied_bytes)}, so it was not saved.")
    if expected_ms is not None:
        expected = expected_ms / 1000
        if abs(length - expected) > max(1.0, 0.02 * expected):
            raise PublicationError(f"The finished narration {name} is {length:.1f} s long where {expected:.1f} s "
                                   "was encoded, so it was not saved.")


# --------------------------------------------------------------------------- what an interrupted run left behind


def process_is_alive(pid: int) -> bool:
    """``False`` only when the process is provably gone; anything uncertain counts as alive, and its file stays."""
    if _IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: no such process; else: not ours to judge
        try:
            code = wintypes.DWORD()
            return not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def sweep_orphans(root, *, is_alive: Optional[Callable[[int], bool]] = None) -> list[Path]:
    """Remove staging files left under *root* by attempts that can no longer publish them; return what was removed.

    A file is removed only when its whole name is this module's staging name, it is a regular file, and its owner is
    finished: another process that is gone (and the file has lain untouched for :data:`ORPHAN_MIN_AGE_SECONDS`), or this
    process with no attempt using that file now. Everything else is left alone: any other name, any link, an attempt in
    progress, and a live process's work.
    """
    if root is None:
        return []
    is_alive = process_is_alive if is_alive is None else is_alive
    removed: list[Path] = []
    me = os.getpid() & 0xFFFFFFFF
    for folder, subfolders, names in os.walk(root, followlinks=False):
        # os.walk does walk into a Windows junction, whatever followlinks says.
        subfolders[:] = [sub for sub in subfolders if not output_paths._is_link(Path(folder) / sub)]
        for name in names:
            match = _STAGE_NAME.fullmatch(name)
            if match is None:
                continue
            path = Path(folder) / name
            owner = int(match.group(1), 16)
            with _active_lock:
                in_use = os.path.normcase(str(path)) in _active
            if in_use or (owner != me and is_alive(owner)):
                continue
            try:
                if not path.is_file() or output_paths._is_link(path):
                    continue
                if owner != me and time.time() - path.stat().st_mtime < ORPHAN_MIN_AGE_SECONDS:
                    continue
            except OSError:
                continue
            output_paths.discard_temporary(path)
            if not os.path.lexists(path):
                removed.append(path)
    return removed
