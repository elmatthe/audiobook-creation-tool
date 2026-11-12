"""Where the TTS routes keep their temporary files, who owns them, and how a later run removes what a killed one left
(v0.7.2, ACT72-009).

In ``shared/`` since v0.7.2 Phase 6: the M4B Maker's custom builds stage here too (kind ``maker``, ACT72-031), and a tool
package may not import ``tts``. Nothing about the area changed with the move; its folder is still ``act-tts``.

**Why.** A conversion works in temporary folders and files: the Edge engine's folder (every clip, the text, the
assembly WAV), the panel's folders around a direct or local-engine conversion, pydub's temporaries (the first holds the
whole narration as a WAV) and the local engines' encode WAV. Until v0.7.2 they lay loose in the system temp folder
(``epub2tts_*``, ``tts_direct_*``, ``tts_local_*``, ``tmp*``) under names any program could have chosen. A killed program
left them there, nothing recorded whose they were, and so nothing could ever safely remove them.

**Layout.** In the system temp folder (``tempfile.gettempdir()``: the drive that always held these files still does, and
a redirected TEMP contains them)::

    act-tts/                      ROOT, this tool's alone; made when first needed and left in place
      <16 hex>/                   a WORKSPACE: one process's, made exclusively, its name from ``secrets``
        owner.json                its MANIFEST: the token, the workspace's own path, the owner, the entries
        <n>/                      one ENTRY: a conversion's folder, written into the manifest before it is made

The names are short on purpose: a book's own name is used inside an entry, and Windows paths stop at 260 characters
unless long paths are enabled. The old layout put 19 characters between the temp folder and that name; this puts 28
to 30.

**Ownership.** Only an intact manifest makes anything removable by another process. It names the owner by process id
**and process creation time**, so a reused process id is never taken for the owner, and it names each entry exactly,
inside its own workspace, with its kind, its retention and its state. Every TTS entry is ``disposable``: nothing in one
can be resumed (interrupted narration is synthesised again). An entry is ``active`` while its conversion uses it and
``finished`` once that conversion has ended but the folder could not be removed (a scanner held a file). A name, an age
or a process id alone proves nothing here, and none is ever used alone. A workspace lasts while it has entries: the
last one removed takes the manifest and the workspace with it.

**The M4B Maker** (v0.7.2, ACT72-031) stages a custom-folder build in an entry of kind ``maker``, the same way. The
entry stays ``active`` while the panel's run may still use it (a validated candidate kept for Retry Failed) and is
closed once no retry can reach it. Nothing in it can be resumed by another process either: a killed Maker's Retry
Failed died with it, so recovery treats the entry like any other. A custom build's start runs :func:`recover` too.

**Recovery** (:func:`recover`, at the start of every TTS run, on the run's worker thread, bounded by
:data:`RECOVERY_SECONDS` and by Cancel). Another process's workspace is cleared only when its manifest is intact and its
owner is provably gone: its disposable entries go, then any half-written manifest of its own, then the manifest and the
workspace. This process's own workspace loses only ``finished`` entries no conversion is using. Everything else stays
exactly as it is and is reported: a running or unverifiable owner, a missing, partial, damaged or foreign manifest, a
name this tool does not make, a link, anything not disposable, anything in use. Nothing outside ROOT is ever looked at,
so older ``epub2tts_*`` leftovers and every other program's files stay where they are.

**Removal** never follows a link and cannot be redirected. On Windows the temp folder, ROOT, the workspace and each
folder being emptied are held open without delete sharing while the work goes on, so none of them can be renamed or
replaced meanwhile. Every entry inside is opened without following a reparse point, judged by its own handle, and
deleted through that handle, so what is deleted is exactly what was judged. A link (symlink, junction, any reparse
point) is never followed and never removed: it and the folders holding it stay, and are reported. A hard link loses
only this folder's name for it; the file stays wherever else it is named. Elsewhere, only a process's own entries are
removed, by ``shutil.rmtree``'s symlink-attack-resistant form. Recovering another process's leftovers needs the
owner's creation time, which is only read on Windows, so elsewhere other workspaces are left alone.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import re
import secrets
import shutil
import stat
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

ROOT_NAME = "act-tts"
MANIFEST_NAME = "owner.json"
SCHEMA = "act-tts-work"
VERSION = 1
DISPOSABLE = "disposable"
ACTIVE, FINISHED = "active", "finished"
KINDS = ("edge", "direct", "local", "pydub", "maker")
MANIFEST_MAX_BYTES = 256 * 1024
#: The longest a run's start waits for recovery; whatever is left is removed at a later start.
RECOVERY_SECONDS = 5.0
#: A workspace this young without a manifest is a process creating or retiring it right now, not a leftover to report.
SETTLING_SECONDS = 120.0
#: A scanner or indexer holds a just-written file for a moment. Bounded, under a second; then the entry stays for recovery.
_IN_USE_RETRY_DELAYS = (0.05, 0.15, 0.3)
_MANIFEST_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4)

_WORKSPACE_NAME = re.compile(r"[0-9a-f]{16}")
_ENTRY_NAME = re.compile(r"[1-9][0-9]{0,8}")
_MANIFEST_TEMP = re.compile(re.escape(MANIFEST_NAME) + r"\.[0-9a-f]{8}\.new")
_IS_WINDOWS = os.name == "nt"

ALIVE, GONE, UNKNOWN = "alive", "gone", "unknown"


class WorkAreaError(OSError):
    """A conversion could not get a private working folder. An ``OSError``: a local problem, never synthesised again."""


# --------------------------------------------------------------------------- Windows: handles, identity, deletion

if _IS_WINDOWS:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _GENERIC_READ = 0x80000000
    _DELETE = 0x00010000
    _FILE_READ_ATTRIBUTES = 0x80
    _FILE_LIST_DIRECTORY = 0x1
    _SYNCHRONIZE = 0x00100000
    _SHARE_READ_WRITE = 0x1 | 0x2
    _SHARE_ALL = 0x1 | 0x2 | 0x4
    _OPEN_EXISTING = 3
    _BACKUP_SEMANTICS = 0x02000000
    _OPEN_REPARSE_POINT = 0x00200000
    _ATTR_DIRECTORY = 0x10
    _ATTR_REPARSE = 0x400
    _INVALID_HANDLE = wintypes.HANDLE(-1).value
    _ERROR_INVALID_PARAMETER = 87
    _STILL_ACTIVE = 259

    class _FileInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME), ("accessed", wintypes.FILETIME),
                    ("written", wintypes.FILETIME), ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD), ("index_high", wintypes.DWORD),
                    ("index_low", wintypes.DWORD)]

    class _Disposition(ctypes.Structure):
        _fields_ = [("delete", wintypes.BOOLEAN)]

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                    wintypes.DWORD, wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInfo)]
    _kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel.OpenProcess.restype = wintypes.HANDLE
    _kernel.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    _kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]

    def _open(path, access: int, share: int, *, follow: bool = False):
        """A handle to *path* itself: a link is opened as the link, never as what it points at (unless *follow*)."""
        flags = _BACKUP_SEMANTICS | (0 if follow else _OPEN_REPARSE_POINT)
        handle = _kernel.CreateFileW(str(path), access, share, None, _OPEN_EXISTING, flags, None)
        if handle == _INVALID_HANDLE:
            code = ctypes.get_last_error()
            raise ctypes.WinError(code)
        return handle

    def _close(handle) -> None:
        _kernel.CloseHandle(handle)

    def _attributes(handle) -> int:
        info = _FileInfo()
        if not _kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return info.attributes

    def _delete_by_handle(handle) -> None:
        """Delete exactly the object this handle holds, when the handle closes."""
        disposition = _Disposition(True)
        if not _kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            raise ctypes.WinError(ctypes.get_last_error())

    def _filetime(value) -> int:
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    def _creation_time(handle) -> Optional[int]:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not _kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        return _filetime(times[0])

    def _own_creation_time() -> Optional[int]:
        return _creation_time(_kernel.GetCurrentProcess())

    def owner_state(owner) -> str:
        """:data:`ALIVE`, :data:`GONE` or :data:`UNKNOWN` for a manifest's owner.

        Gone only when no process has that id, or the one that has it was created at another moment (the id was reused),
        or the owner itself has exited. Anything that cannot be checked is :data:`UNKNOWN`, and its files stay.
        """
        pid, created = _owner_fields(owner)
        if pid is None:
            return UNKNOWN
        handle = _kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return GONE if ctypes.get_last_error() == _ERROR_INVALID_PARAMETER else UNKNOWN
        try:
            actual = _creation_time(handle)
            if actual is None:
                return UNKNOWN
            if actual != created:
                return GONE  # ids are unique among existing processes, so the one that wrote the manifest has ended
            code = wintypes.DWORD()
            if not _kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return UNKNOWN
            return ALIVE if code.value == _STILL_ACTIVE else GONE
        finally:
            _close(handle)

else:  # pragma: no cover - exercised only where the platform differs

    def _own_creation_time() -> Optional[int]:
        return None

    def owner_state(owner) -> str:
        """Elsewhere a process's creation time is not read, so no owner can be proved gone."""
        return UNKNOWN


def _owner_fields(owner) -> tuple[Optional[int], Optional[int]]:
    if not isinstance(owner, dict):
        return None, None
    pid, created = owner.get("pid"), owner.get("created")
    if (type(pid) is not int or type(created) is not int) or pid <= 0 or created <= 0:
        return None, None
    return pid, created


def _why(exc: OSError) -> str:
    if isinstance(exc, WorkAreaError):
        return "a link or not a folder, so nothing in it is removed"
    code = getattr(exc, "winerror", None)
    if code in (32, 33):
        return "in use by another program"
    if code == 5 or isinstance(exc, PermissionError):
        return "access was refused"
    if code == 145:
        return "it is not empty"
    return exc.strerror or type(exc).__name__


# --------------------------------------------------------------------------- removal

@dataclass
class _Removal:
    stop: Callable[[], bool] = lambda: False
    problems: list = field(default_factory=list)  # (path, reason)
    in_use: bool = False  # something was held for the moment: worth one more look
    lasting: bool = False  # something no wait will change (a link, a refusal): not worth another look
    stopped: bool = False

    def problem(self, path, reason: str, *, in_use: bool = False) -> None:
        self.problems.append((str(path), reason))
        self.in_use = self.in_use or in_use
        self.lasting = self.lasting or not in_use

    def should_stop(self) -> bool:
        if not self.stopped and self.stop():
            self.stopped = True
        return self.stopped


def _pin_chain(stack: contextlib.ExitStack, temp: Path, inner: tuple[str, ...]) -> Path:
    """Hold the temp folder and each named folder below it open without delete sharing, each judged by its own handle.

    The temp folder is the trust anchor and is followed if it is itself a link (a user may redirect TEMP); every folder
    below it must be a real folder, or this raises. Returns the innermost path."""
    # FILE_LIST_DIRECTORY: a handle with only attribute access takes no part in sharing checks, and would pin nothing.
    access = _FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
    handle = _open(temp, access, _SHARE_READ_WRITE, follow=True)
    stack.callback(_close, handle)
    path = temp
    for name in inner:
        path = path / name
        handle = _open(path, access, _SHARE_READ_WRITE)
        stack.callback(_close, handle)
        attributes = _attributes(handle)
        if attributes & _ATTR_REPARSE or not attributes & _ATTR_DIRECTORY:
            raise WorkAreaError(f"{path} is a link or not a folder, so nothing in it is removed")
    return path


def _remove_win(path: str, handle, removal: _Removal) -> bool:
    """Empty the folder *handle* holds (opened by us with DELETE, denying delete sharing), then delete it."""
    try:
        with os.scandir(path) as listing:
            names = [entry.name for entry in listing]
    except OSError as exc:
        removal.problem(path, f"its contents could not be listed: {_why(exc)}")
        return False
    for name in names:
        if removal.should_stop():
            return False
        child = os.path.join(path, name)
        try:
            child_handle = _open(child, _DELETE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE, _SHARE_READ_WRITE)
        except FileNotFoundError:
            continue
        except OSError as exc:
            removal.problem(child, _why(exc), in_use=getattr(exc, "winerror", None) in (5, 32, 33))
            continue
        try:
            attributes = _attributes(child_handle)
            if attributes & _ATTR_REPARSE:
                removal.problem(child, "a link, which is never followed or removed")
            elif attributes & _ATTR_DIRECTORY:
                _remove_win(child, child_handle, removal)
            else:
                _delete_by_handle(child_handle)
        except OSError as exc:
            removal.problem(child, _why(exc), in_use=getattr(exc, "winerror", None) in (5, 32, 33))
        finally:
            _close(child_handle)
    if removal.should_stop():
        return False
    try:
        _delete_by_handle(handle)
        return True
    except OSError as exc:
        removal.problem(path, f"not removed: {_why(exc)}", in_use=getattr(exc, "winerror", None) == 145)
        return False


def _remove_entry(temp: Path, workspace: str, entry: str, stop: Callable[[], bool] = lambda: False) -> _Removal:
    """Remove one entry folder and everything in it that may be removed. Never raises; :attr:`_Removal.problems` says
    what stayed and why. An entry that is not there counts as removed."""
    removal = _Removal(stop)
    delays = (*_IN_USE_RETRY_DELAYS, None)
    for delay in delays:
        removal.problems, removal.in_use, removal.lasting = [], False, False
        if _IS_WINDOWS:
            _remove_entry_win(temp, workspace, entry, removal)
        else:
            _remove_entry_posix(temp / ROOT_NAME / workspace / entry, removal)
        # Another look only when everything that stopped this one may let go in a moment.
        if not removal.problems or removal.lasting or delay is None or removal.stopped:
            return removal
        time.sleep(delay)
    return removal


def _remove_entry_win(temp: Path, workspace: str, entry: str, removal: _Removal) -> None:
    with contextlib.ExitStack() as stack:
        try:
            folder = _pin_chain(stack, temp, (ROOT_NAME, workspace))
        except FileNotFoundError:
            return
        except OSError as exc:
            removal.problem(temp / ROOT_NAME / workspace, _why(exc))
            return
        path = folder / entry
        try:
            handle = _open(path, _DELETE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE, _SHARE_READ_WRITE)
        except FileNotFoundError:
            return
        except OSError as exc:
            removal.problem(path, _why(exc), in_use=getattr(exc, "winerror", None) in (5, 32, 33))
            return
        try:
            attributes = _attributes(handle)
            if attributes & _ATTR_REPARSE or not attributes & _ATTR_DIRECTORY:
                removal.problem(path, "a link or not a folder, which is never removed")
                return
            _remove_win(str(path), handle, removal)
        except OSError as exc:
            removal.problem(path, _why(exc))
        finally:
            _close(handle)


def _remove_entry_posix(path: Path, removal: _Removal) -> None:  # pragma: no cover - not Windows
    if not os.path.lexists(path):
        return
    if path.is_symlink() or not path.is_dir():
        removal.problem(path, "a link or not a folder, which is never removed")
        return
    if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        removal.problem(path, "this system cannot remove a folder without risking a link")
        return
    shutil.rmtree(path, ignore_errors=True)
    if os.path.lexists(path):
        removal.problem(path, "not removed")


# --------------------------------------------------------------------------- manifests

def _manifest_bytes(data: dict) -> bytes:
    return json.dumps(data, indent=1, sort_keys=True).encode("utf-8")


def _write_manifest(folder: Path, data: dict) -> None:
    """Replace the manifest in one operation, after its bytes are on the disk. Raises :class:`OSError`."""
    payload = _manifest_bytes(data)
    temporary = folder / f"{MANIFEST_NAME}.{secrets.token_hex(4)}.new"
    with open(temporary, "xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        for delay in (*_MANIFEST_RETRY_DELAYS, None):
            try:
                os.replace(temporary, folder / MANIFEST_NAME)
                return
            except PermissionError:  # a reader without delete sharing, for a moment
                if delay is None:
                    raise
                time.sleep(delay)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _read_manifest(folder: Path) -> tuple[Optional[dict], Optional[str]]:
    """``(data, None)`` or ``(None, why it cannot be trusted)``. Read without following a link and, on Windows, with
    every kind of sharing, so a running owner can always replace it meanwhile."""
    path = folder / MANIFEST_NAME
    try:
        if _IS_WINDOWS:
            handle = _open(path, _GENERIC_READ | _FILE_READ_ATTRIBUTES, _SHARE_ALL)
            try:
                attributes = _attributes(handle)
            except OSError:
                _close(handle)
                raise
            if attributes & (_ATTR_REPARSE | _ATTR_DIRECTORY):
                _close(handle)
                return None, "its manifest is a link or a folder"
            try:
                descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            except OSError:
                _close(handle)
                raise
        else:  # pragma: no cover - not Windows
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            raw = b""
            while chunk := os.read(descriptor, 65536):
                raw += chunk
                if len(raw) > MANIFEST_MAX_BYTES:
                    return None, "its manifest is too large to be one of this tool's"
        finally:
            os.close(descriptor)
    except FileNotFoundError:
        return None, "it has no manifest, so its owner is unknown"
    except OSError as exc:
        return None, f"its manifest could not be read: {_why(exc)}"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "its manifest is incomplete or damaged"
    return data, None


def _same_place(first, second) -> bool:
    try:
        return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))
    except (OSError, ValueError):
        return False


def _manifest_problem(data, token: str, folder: Path) -> Optional[str]:
    """Why this manifest does not make *folder* this tool's workspace, or ``None``."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("version") != VERSION:
        return "its manifest is not one this tool writes"
    if data.get("token") != token:
        return "its manifest belongs to another workspace"
    workspace = data.get("workspace")
    if not isinstance(workspace, str) or not _same_place(workspace, folder):
        return "its manifest names another place"
    if _owner_fields(data.get("owner")) == (None, None):
        return "its manifest names no owner that can be checked"
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return "its manifest lists no entries"
    for name, facts in entries.items():
        if not isinstance(name, str) or not _ENTRY_NAME.fullmatch(name) or not isinstance(facts, dict):
            return "its manifest lists an entry this tool never makes"
        if facts.get("state") not in (ACTIVE, FINISHED) or not isinstance(facts.get("retention"), str):
            return "its manifest lists an entry in an unknown state"
    return None


# --------------------------------------------------------------------------- this process's workspace

class _ProcessArea:
    """This process's workspace in one temp folder. Temporary-file ownership only: not a Book Workspace, a job or an
    output framework (``test_m4b_structural_authority`` keeps that one name to ``shared/book_workspace.py``)."""

    def __init__(self, temp: Path, token: str, owner: dict) -> None:
        self.temp = temp
        self.token = token
        self.path = temp / ROOT_NAME / token
        self.owner = owner
        self.entries: dict[str, dict] = {}
        self.counter = 0
        self.retired = False

    def manifest(self) -> dict:
        return {"schema": SCHEMA, "version": VERSION, "token": self.token, "workspace": str(self.path),
                "owner": self.owner, "entries": self.entries}


_lock = threading.Lock()
_workspaces: dict[str, _ProcessArea] = {}  # by the temp folder they live in: tests change it, so may a caller
_current: contextvars.ContextVar[Optional[Path]] = contextvars.ContextVar("tts_work_area_current", default=None)


def _temp_key(temp: Path) -> str:
    return os.path.normcase(os.path.abspath(temp))


def _new_workspace(temp: Path) -> _ProcessArea:
    """Called under ``_lock``. Makes ROOT if needed and a workspace no other process can have made."""
    root = temp / ROOT_NAME
    root.mkdir(parents=True, exist_ok=True)
    if not _is_real_folder(root):
        raise WorkAreaError(f"{root} is a link or not a folder, so no temporary files are made in it. Remove it, then "
                            "use Retry Failed.")
    owner = {"pid": os.getpid(), "created": _own_creation_time() or 0}
    for _ in range(16):
        token = secrets.token_hex(8)
        workspace = _ProcessArea(temp, token, owner)
        try:
            os.mkdir(workspace.path)  # exclusive: this process made it, which is what makes its contents this process's
        except FileExistsError:
            continue
        try:
            _write_manifest(workspace.path, workspace.manifest())
        except BaseException:
            with contextlib.suppress(OSError):
                os.rmdir(workspace.path)
            raise
        return workspace
    raise WorkAreaError(f"No private working folder could be made in {root}.")


def _retire(workspace: _ProcessArea) -> None:
    """Called under ``_lock`` once the workspace has no entries: take the manifest and the workspace with it."""
    workspace.retired = True
    if _workspaces.get(_temp_key(workspace.temp)) is workspace:
        del _workspaces[_temp_key(workspace.temp)]
    try:
        with os.scandir(workspace.path) as listing:
            others = [entry.name for entry in listing if entry.name != MANIFEST_NAME]
    except OSError:
        return
    if others:  # something this process did not make: keep the manifest, so it can still be told apart
        with contextlib.suppress(OSError):
            _write_manifest(workspace.path, workspace.manifest())
        return
    try:
        os.unlink(workspace.path / MANIFEST_NAME)
    except FileNotFoundError:
        pass
    except OSError:
        return
    for delay in (*_MANIFEST_RETRY_DELAYS, None):
        try:
            os.rmdir(workspace.path)
            return
        except PermissionError:  # another process is looking at it for a moment (recover)
            if delay is None:
                return
            time.sleep(delay)
        except OSError:
            return


def _is_real_folder(path: Path) -> bool:
    """A folder, judged without following a link: a symlink or junction (any reparse point) is not one."""
    try:
        facts = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(facts.st_mode) and not getattr(facts, "st_file_attributes", 0) & 0x400


class OwnedFolder:
    """One entry: a private folder in this process's workspace, listed in its manifest before it exists. :meth:`close`
    removes it, or leaves it ``finished`` for :func:`recover` when something holds it; it never raises."""

    def __init__(self, kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        temp = Path(tempfile.gettempdir())
        with _lock:
            workspace = _workspaces.get(_temp_key(temp))
            if workspace is None or not _is_real_folder(workspace.path):
                try:
                    workspace = _new_workspace(temp)
                except WorkAreaError:
                    raise
                except OSError as exc:
                    raise WorkAreaError(f"No private working folder could be made in {temp}: {_why(exc)}") from exc
                _workspaces[_temp_key(temp)] = workspace
            name = _add_entry(workspace, kind)
        self.workspace = workspace
        self.name = name
        self.path = workspace.path / name
        self.closed = False

    def close(self) -> bool:
        """Remove the folder; ``True`` if it is gone."""
        if self.closed:
            return not os.path.lexists(self.path)
        self.closed = True
        return _settle(self.workspace, self.name, _remove_entry(self.workspace.temp, self.workspace.token, self.name))


def _add_entry(workspace: _ProcessArea, kind: str) -> str:
    """Called under ``_lock``. The entry is in the manifest, on the disk, before its folder exists, so a process killed at
    any instant leaves nothing of its own unlisted."""
    for _ in range(16):
        workspace.counter += 1
        name = str(workspace.counter)
        workspace.entries[name] = {"kind": kind, "retention": DISPOSABLE, "state": ACTIVE}
        try:
            _write_manifest(workspace.path, workspace.manifest())
            os.mkdir(workspace.path / name)
            return name
        except FileExistsError:  # not this process's: never listed as ours
            del workspace.entries[name]
            with contextlib.suppress(OSError):
                _write_manifest(workspace.path, workspace.manifest())
        except OSError as exc:
            del workspace.entries[name]
            if not workspace.entries:
                _retire(workspace)
            raise WorkAreaError(f"No private working folder could be made in {workspace.path}: {_why(exc)}") from exc
    raise WorkAreaError(f"No private working folder could be made in {workspace.path}.")


def _settle(workspace: _ProcessArea, name: str, removal: _Removal) -> bool:
    removed = not removal.problems and not removal.stopped
    with _lock:
        if removed:
            workspace.entries.pop(name, None)
        elif name in workspace.entries:
            workspace.entries[name]["state"] = FINISHED
        if not workspace.entries and not workspace.retired:
            _retire(workspace)
        elif not workspace.retired:
            with contextlib.suppress(OSError):
                _write_manifest(workspace.path, workspace.manifest())
    return removed


def new_folder(kind: str) -> OwnedFolder:
    """A private folder for one piece of a conversion's work. The caller must :meth:`~OwnedFolder.close` it."""
    return OwnedFolder(kind)


@contextlib.contextmanager
def conversion_folder(kind: str) -> Iterator[Path]:
    """A private folder for one conversion, removed when the block ends however it ends; while the block runs it is
    :func:`current_folder`, where an engine puts its own temporary files."""
    folder = OwnedFolder(kind)
    token = _current.set(folder.path)
    try:
        yield folder.path
    except BaseException as exc:
        # A failed export may still hold a file open in a finished frame of this traceback, and Windows will not delete
        # an open file. Those frames have ended, so their locals can go now.
        traceback.clear_frames(exc.__traceback__)
        raise
    finally:
        _current.reset(token)
        folder.close()


def current_folder() -> Optional[Path]:
    """The innermost :func:`conversion_folder` this thread is converting in, or ``None`` outside one."""
    return _current.get()


# --------------------------------------------------------------------------- recovery

@dataclass
class Recovery:
    """What :func:`recover` did. ``left`` holds ``(path, reason)`` for what stays and should be explained."""

    removed: list = field(default_factory=list)
    left: list = field(default_factory=list)
    running: int = 0
    deferred: bool = False

    def as_dict(self) -> dict:
        return {"removed": list(self.removed), "left": [list(item) for item in self.left], "running": self.running,
                "deferred": self.deferred}

    def log_lines(self) -> list[str]:
        lines = []
        if self.removed:
            count = len(self.removed)
            lines.append(f"Removed {count} temporary folder{'s' if count != 1 else ''} left by an interrupted run.")
        lines += [f"Left in the temporary folder, {reason}: {path}" for path, reason in self.left]
        if self.deferred:
            lines.append("Stopped removing what an interrupted run left so this run could start; the rest is removed "
                         "at a later start.")
        return lines


def recover(*, cancel_check: Optional[Callable[[], bool]] = None, seconds: float = RECOVERY_SECONDS,
            clock: Callable[[], float] = time.monotonic, is_owner_gone: Optional[Callable[[dict], str]] = None) -> Recovery:
    """Remove what killed processes and this process's own unfinished cleanups left in ROOT; leave everything else.

    Never raises for anything it finds. ``is_owner_gone`` (a test seam) answers :func:`owner_state` for a manifest's owner.
    """
    report = Recovery()
    deadline = clock() + seconds
    state_of = owner_state if is_owner_gone is None else is_owner_gone

    def stop() -> bool:
        return (cancel_check is not None and bool(cancel_check())) or clock() > deadline

    temp = Path(tempfile.gettempdir())
    _recover_own(temp, report, stop)
    root = temp / ROOT_NAME
    if not _IS_WINDOWS or not os.path.lexists(root):
        return report
    with contextlib.ExitStack() as stack:
        try:
            _pin_chain(stack, temp, (ROOT_NAME,))
            with os.scandir(root) as listing:
                names = sorted(entry.name for entry in listing)
        except OSError as exc:
            report.left.append((str(root), _why(exc) if not isinstance(exc, WorkAreaError) else "a link or not a folder"))
            return report
        with _lock:
            own = {workspace.token for workspace in _workspaces.values() if _temp_key(workspace.temp) == _temp_key(temp)}
        for name in names:
            if stop():
                report.deferred = True
                break
            if name in own:
                continue
            if not _WORKSPACE_NAME.fullmatch(name):
                report.left.append((str(root / name), "not a name this tool makes"))
                continue
            _recover_other(temp, name, report, stop, state_of)
            if report.deferred:
                break
    return report


def _recover_own(temp: Path, report: Recovery, stop: Callable[[], bool]) -> None:
    with _lock:
        workspace = _workspaces.get(_temp_key(temp))
        names = [] if workspace is None else [n for n, f in workspace.entries.items() if f["state"] == FINISHED]
    for name in names:
        if stop():
            report.deferred = True
            return
        removal = _remove_entry(temp, workspace.token, name, stop)
        if _settle(workspace, name, removal):
            report.removed.append(str(workspace.path / name))
        else:
            report.deferred = report.deferred or removal.stopped
            report.left += [(path, why) for path, why in removal.problems]


def _recover_other(temp: Path, token: str, report: Recovery, stop: Callable[[], bool], state_of) -> None:
    folder = temp / ROOT_NAME / token
    with contextlib.ExitStack() as stack:
        try:
            _pin_chain(stack, temp, (ROOT_NAME, token))  # shares reading with the owner and other recoveries, never delete
        except FileNotFoundError:
            return
        except WorkAreaError:
            report.left.append((str(folder), "a link or not a folder"))
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) in (32, 33):
                report.running += 1  # another process is removing or retiring it right now
            else:
                report.left.append((str(folder), _why(exc)))
            return
        data, problem = _read_manifest(folder)
        problem = problem or _manifest_problem(data, token, folder)
        if problem:
            if data is None and _settling(folder):
                report.running += 1
            else:
                report.left.append((str(folder), problem))
            return
        state = state_of(data["owner"])
        if state == ALIVE:
            report.running += 1
            return
        if state != GONE:
            report.left.append((str(folder), "its owner cannot be checked"))
            return
        for name, facts in sorted(data["entries"].items(), key=lambda item: int(item[0])):
            if stop():
                report.deferred = True
                return
            if facts["retention"] != DISPOSABLE:
                report.left.append((str(folder / name), f"kept as {facts['retention']!r}, never removed by recovery"))
                continue
            existed = os.path.lexists(folder / name)
            removal = _remove_entry(temp, token, name, stop)
            if removal.stopped:
                report.deferred = True
                return
            if removal.problems:
                report.left += removal.problems
            elif existed:
                report.removed.append(str(folder / name))
    _retire_other(temp, folder, data, report)


def _settling(folder: Path) -> bool:
    try:
        return time.time() - os.lstat(folder).st_mtime < SETTLING_SECONDS
    except OSError:
        return False


def _retire_other(temp: Path, folder: Path, data: dict, report: Recovery) -> None:
    """A dead owner's workspace once its entries are handled: its own half-written manifests go; if nothing but its
    manifest is left, the manifest and the workspace go too. Anything else keeps both, so it stays explained. The
    workspace is judged again by the handle that deletes it."""
    with contextlib.ExitStack() as stack:
        try:
            _pin_chain(stack, temp, (ROOT_NAME,))
            handle = _open(folder, _DELETE | _FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
                           _SHARE_READ_WRITE)
        except FileNotFoundError:
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (32, 33):  # another recovery holds it: it finishes the job
                report.left.append((str(folder), _why(exc)))
            return
        stack.callback(_close, handle)
        try:
            attributes = _attributes(handle)
        except OSError as exc:
            report.left.append((str(folder), _why(exc)))
            return
        if attributes & _ATTR_REPARSE or not attributes & _ATTR_DIRECTORY:
            report.left.append((str(folder), "a link or not a folder"))
            return
        _retire_held(folder, data, handle, report)


def _retire_held(folder: Path, data: dict, handle, report: Recovery) -> None:
    try:
        with os.scandir(folder) as listing:
            names = [entry.name for entry in listing]
    except OSError as exc:
        report.left.append((str(folder), f"its contents could not be listed: {_why(exc)}"))
        return
    listed = set(data["entries"])
    removal = _Removal()
    for name in names:
        if _MANIFEST_TEMP.fullmatch(name):
            _delete_file_win(folder / name, removal)
    remaining = [n for n in names if n != MANIFEST_NAME and not _MANIFEST_TEMP.fullmatch(n)]
    for name in remaining:
        if name not in listed:
            report.left.append((str(folder / name), "not listed in its workspace's manifest"))
    report.left += removal.problems
    if remaining or removal.problems:
        return
    _delete_file_win(folder / MANIFEST_NAME, removal)
    if removal.problems:
        report.left += removal.problems
        return
    try:
        _delete_by_handle(handle)
    except OSError as exc:
        report.left.append((str(folder), f"not removed: {_why(exc)}"))


def _delete_file_win(path: Path, removal: _Removal) -> None:
    try:
        handle = _open(path, _DELETE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE, _SHARE_READ_WRITE)
    except FileNotFoundError:
        return
    except OSError as exc:
        removal.problem(path, _why(exc))
        return
    try:
        if _attributes(handle) & (_ATTR_REPARSE | _ATTR_DIRECTORY):
            removal.problem(path, "a link or a folder where a manifest should be")
            return
        _delete_by_handle(handle)
    except OSError as exc:
        removal.problem(path, _why(exc))
    finally:
        _close(handle)
