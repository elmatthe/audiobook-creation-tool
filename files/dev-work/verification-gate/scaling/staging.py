"""What the application has staged under one output base, read exactly and held to account (m4b-scaling T5).

v0.7.2 Phase 9, review finding P9-04. T5 asks for the peak of the bytes the application stages (its ``.act-tmp-*`` files
under the output base). The total can only be read exactly at the moments it is about to fall, so everything depends on
knowing every such moment. Phase 8 read before two helpers of ``shared.output_paths`` (the discard and the publication)
and assumed nothing else lowered the total. The review made a copy inside the publication and unlinked it directly: 154,048
bytes were staged and T5 read 92,520. An assumption about which functions the application calls is not a measurement.

**What is observed, and how.**

* *This process's own file operations* (``sys.addaudithook``; an audit event is raised before the operation acts,
  whichever module, helper or thread asked for it). A reading is taken before every removal (``os.remove``,
  ``os.unlink``, ``pathlib``, ``shutil``), every rename or replacement (``os.rename``, ``os.replace``, with the
  temporary as its source or as the name written over), every ``os.truncate`` / ``os.ftruncate``, and every opening for
  writing of a temporary that already holds bytes (``open``, ``os.open``). So the largest reading is the peak, for code
  that exists today and for code nobody has written yet.
* *Every removal and rename under the base, by any process and through any interface* (``ReadDirectoryChangesW``,
  ``DirectoryWatch``): what Windows itself reports. It is not used to measure. It is the independent account the readings
  are held to: a temporary Windows saw removed or renamed that no reading was taken for (a child process deleting it, a
  native call) makes the measurement incomplete, and so does a temporary a reading saw that Windows never reported
  created under this base during the run.
* *Each temporary from one reading to the next.* One that is gone, or smaller, without an operation that announced it,
  was lowered unobserved.

**What a staged file is.** Media, unless it is proved to be diagnostics: a file the run handed to a child process as
its output sink (``diagnostics_sink``, called where the child is started), recognised afterwards by its identity on the
volume, not by its name. A file called ``.act-tmp-anything.log`` that no child was given is media. A link is never
followed and never counted: its presence among the temporaries fails the measurement.

**What cannot be observed, said plainly.** A file shortened through a handle that is already open (``file.truncate()``,
a memory map) raises no event and Windows reports no name change. Two things stand against it: the application may open
a temporary for writing only to hand it to a child (any other such opening is reported, and fails the measurement), and
a temporary found smaller than before fails it. A file grown and shortened through one handle wholly between two
readings, by a process other than this one, is outside what this can see; the application has no such code, and
``files/tests/test_verification_gate_contract.py`` pins that from its source.

When anything above is not clean the record says so, and ``qualify.resource_checks`` fails T5: an exact figure is
claimed only when it was read exactly.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import secrets
import stat
import struct
import sys
import threading

TEMPORARY_PREFIX = ".act-tmp-"
_EVENTS = frozenset({"open", "os.remove", "os.rename", "os.truncate"})
_WRITING = os.O_WRONLY | os.O_RDWR

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.CreateFileW.restype = w.HANDLE
_k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
_k.ReadDirectoryChangesW.restype = w.BOOL
_k.ReadDirectoryChangesW.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, w.BOOL, w.DWORD, ctypes.POINTER(w.DWORD),
                                     ctypes.c_void_p, ctypes.c_void_p]
_k.CancelIoEx.argtypes = [w.HANDLE, ctypes.c_void_p]
_k.CloseHandle.argtypes = [w.HANDLE]
_INVALID_HANDLE = w.HANDLE(-1).value
_ADDED, _REMOVED, _RENAMED_FROM, _RENAMED_TO = 1, 2, 4, 5


class DirectoryWatch:
    """Every creation, removal and rename under one folder and its subfolders, as Windows reports them.

    A thread of its own waits in ``ReadDirectoryChangesW``; nothing here opens, reads or changes any file. ``mark``
    proves the watch is live and that everything before it has been received: it makes and removes one file of a name
    nobody else uses and waits for Windows to report that removal. A notification Windows dropped (its buffer
    overflowed) is counted in ``lost``, never guessed at.
    """

    def __init__(self, root) -> None:
        self.root = os.path.abspath(os.fspath(root))
        self.added: set[str] = set()
        self.removed: set[str] = set()
        self.renamed_from: set[str] = set()
        self.renamed_to: set[str] = set()
        self.events = 0
        self.lost = 0
        self.error: str | None = None
        self._marks: set[str] = set()
        self._seen = threading.Condition()
        self._handle = _k.CreateFileW(self.root, 0x0001, 0x0007, None, 3, 0x02000000, None)
        if not self._handle or self._handle == _INVALID_HANDLE:
            self._handle = None
            self.error = f"the folder could not be opened for watching (error {ctypes.get_last_error()})"
            self.armed = False
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="bench-staging-watch")
        self._thread.start()
        self.armed = self.mark()

    def _run(self) -> None:
        buffer = ctypes.create_string_buffer(1 << 16)
        returned = w.DWORD()
        while True:
            if not _k.ReadDirectoryChangesW(self._handle, buffer, len(buffer), True, 0x0001, ctypes.byref(returned), None, None):
                code = ctypes.get_last_error()
                if code != 995:  # ERROR_OPERATION_ABORTED is stop() asking; anything else is a watch that ended early
                    self.error = f"ReadDirectoryChangesW failed (error {code})"
                break
            if returned.value == 0:
                with self._seen:
                    self.lost += 1  # Windows had more to say than the buffer held, and dropped it
                    self._seen.notify_all()
                continue
            offset = 0
            data = buffer.raw[:returned.value]
            with self._seen:
                while True:
                    following, action, length = struct.unpack_from("<III", data, offset)
                    name = data[offset + 12:offset + 12 + length].decode("utf-16-le", "replace")
                    self.events += 1
                    leaf = name.rsplit("\\", 1)[-1]
                    if leaf.startswith("watch-mark-"):
                        if action == _REMOVED:
                            self._marks.add(leaf)
                    elif leaf.startswith(TEMPORARY_PREFIX):
                        place = os.path.normcase(os.path.join(self.root, name))
                        {_ADDED: self.added, _REMOVED: self.removed, _RENAMED_FROM: self.renamed_from,
                         _RENAMED_TO: self.renamed_to}.get(action, set()).add(place)
                    if not following:
                        break
                    offset += following
                self._seen.notify_all()

    def mark(self, timeout: float = 10.0) -> bool:
        """True once Windows has reported everything up to now. False when the watch is not live."""
        if self._handle is None or self.error:
            return False
        name = f"watch-mark-{secrets.token_hex(8)}"
        path = os.path.join(self.root, name)
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        os.unlink(path)
        with self._seen:
            return self._seen.wait_for(lambda: name in self._marks or self.error is not None, timeout) and not self.error

    def stop(self) -> None:
        if self._handle is None:
            return
        _k.CancelIoEx(self._handle, None)
        self._thread.join(10)
        _k.CloseHandle(self._handle)
        self._handle = None


#: The censuses of this process that are still reading. One audit hook serves them all: a hook cannot be removed.
_reading: list["StagingCensus"] = []
_hook = threading.Lock()
_hooked = False


def _audit(event: str, args) -> None:
    if event in _EVENTS and _reading:
        for census in tuple(_reading):
            census._heard(event, args)


class StagingCensus:
    """Exactly what is staged under one output base: the size of every ``.act-tmp-*`` file, read before each decrease.

    Create it before the application stages anything; hand it every child's output sink (``diagnostics_sink``); call
    ``finish`` once the run has settled; ``record`` is what the run's results carry. ``read`` may be called at any time
    for one more reading. Nothing here writes, renames or removes anything but the watch's own mark files.
    """

    def __init__(self, base) -> None:
        global _hooked
        self.base = os.path.abspath(os.fspath(base))
        self._root = os.path.normcase(self.base) + os.sep
        self.readings: dict[str, int] = {}
        self.peak = {"media_bytes": 0, "media_files": 0, "diagnostics_bytes": 0, "diagnostics_files": 0,
                     "total_bytes": 0, "total_files": 0}
        self.at_peak: dict = {}
        self.left: dict | None = None
        self._lock = threading.RLock()
        self._sizes: dict[str, int] = {}        # every temporary of the last reading, by its place
        self._ever: set[str] = set()            # every temporary any reading saw
        self._announced: set[str] = set()       # places an observed operation was about to remove, rename or write over
        self._may_shrink: set[str] = set()      # places an observed operation was about to truncate
        self._sinks: dict[str, tuple] = {}      # a child's output sink: place -> identity on the volume
        self._opened: dict[str, str] = {}       # temporaries this process opened for writing itself
        self._unobserved: list[str] = []
        self._links: set[str] = set()
        self._errors: list[str] = []
        self._finished = False
        self._watch = DirectoryWatch(self.base)
        with _hook:
            if not _hooked:
                sys.addaudithook(_audit)
                _hooked = True
            _reading.append(self)
        self.at_start = self.read("start")

    # ------------------------------------------------------------------ what was heard
    def armed(self) -> bool:
        """Whether both observers are live: the audit hook of this process and the watch on the base."""
        return self in _reading and self._watch.armed and not self._watch.error

    def _place(self, raw) -> str | None:
        """The place of *raw* if it names one of the application's temporaries under this base, else None."""
        try:
            text = os.fsdecode(os.fspath(raw))
        except (TypeError, ValueError):
            return None  # not a path at all, or bytes that are no file name here
        if TEMPORARY_PREFIX not in text:
            return None
        place = os.path.normcase(os.path.abspath(text))
        if place.startswith(self._root) and os.path.basename(place).startswith(TEMPORARY_PREFIX):
            return place
        return None

    def _heard(self, event: str, args) -> None:
        """One audit event of this process, before the operation it announces. Must never raise: it would stop the operation."""
        try:
            if event == "open":
                self._opening(*(tuple(args) + (None, None))[:3])
            elif event == "os.remove":
                self._before("remove", args[:1], args[1:2])
            elif event == "os.rename":
                self._before("rename", args[:2], args[2:4])
            elif event == "os.truncate":
                place = None if isinstance(args[0], int) else self._place(args[0])
                if place or isinstance(args[0], int):
                    # A descriptor names no file, so any truncation through one is read for: it may be a temporary's.
                    self.read("truncate")
                    if place:
                        with self._lock:
                            self._may_shrink.add(place)
        except Exception as exc:  # noqa: BLE001 - recorded: a measurement with an error in it is not exact
            self._errors.append(f"{event}: {type(exc).__name__}: {exc}"[:300])

    def _before(self, kind: str, targets, handles) -> None:
        places = [place for place in map(self._place, targets) if place]
        # An operation given a directory handle names its file relative to that handle, which cannot be placed from
        # here. (With no handle the event carries None or a negative number, by platform and by function.)
        relative = [target for target, handle in zip(targets, handles)
                    if isinstance(handle, int) and not isinstance(handle, bool) and handle >= 0
                    and TEMPORARY_PREFIX in str(target)]
        if not places and not relative:
            return
        self.read(kind)
        with self._lock:
            self._announced.update(places)
            self._unobserved += [f"{kind} of {str(target)[-80:]} relative to a directory handle, which cannot be placed"
                                 for target in relative]

    def _opening(self, raw, mode, flags) -> None:
        if isinstance(raw, int):
            return
        place = self._place(raw)
        if place is None:
            return
        if mode is None:
            writing, truncating = bool((flags or 0) & _WRITING), bool((flags or 0) & os.O_TRUNC)
            creating = bool((flags or 0) & os.O_EXCL)
        else:
            writing, truncating, creating = any(c in mode for c in "wax+"), "w" in mode, "x" in mode
        if not writing:
            return
        try:
            holds = os.lstat(place).st_size
        except OSError:
            holds = 0
        if holds:
            self.read("open")  # bytes that are there now may be gone once this handle exists
        with self._lock:
            if truncating:
                self._may_shrink.add(place)
            if not creating:
                self._opened[place] = str(mode if mode is not None else f"flags {flags:#x}")
            if holds and not truncating:
                self._unobserved.append(f"{os.path.basename(place)} ({holds} bytes) was opened for writing without being "
                                        "emptied: a shortening through that handle would not be read")

    def diagnostics_sink(self, sink, pid: int | None = None) -> None:
        """A child process was given *sink* as where its output goes: a file of diagnostics, by that fact alone."""
        name = getattr(sink, "name", None)
        place = self._place(name) if isinstance(name, (str, bytes, os.PathLike)) else None
        if place is None:
            return
        info = os.fstat(sink.fileno())
        with self._lock:
            self._sinks[place] = (info.st_dev, info.st_ino)

    # ------------------------------------------------------------------ one reading
    def _walk(self) -> tuple[dict, dict]:
        """Every temporary under the base, never through a link: ``{place: size}`` and ``{place: identity}``."""
        sizes: dict[str, int] = {}
        identities: dict[str, tuple] = {}
        pending = [self.base]
        while pending:
            try:
                entries = list(os.scandir(pending.pop()))
            except OSError:
                continue  # gone between the listing and the reading: nothing is staged there any more
            for entry in entries:
                owned = entry.name.startswith(TEMPORARY_PREFIX)
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    if not owned and not is_dir:
                        continue
                    info = os.lstat(entry.path)
                except OSError:
                    continue
                place = os.path.normcase(os.path.abspath(entry.path))
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    self._links.add(place)  # a symbolic link, a junction or any other reparse point: recorded, not entered
                elif is_dir:
                    pending.append(entry.path)
                elif owned:
                    if info.st_nlink > 1:
                        self._links.add(place)  # another name for bytes that are someone else's too
                    sizes[place] = info.st_size
                    identities[place] = (info.st_dev, info.st_ino)
        return sizes, identities

    def read(self, moment: str) -> dict:
        with self._lock:
            sizes, identities = self._walk()
            for place, before in self._sizes.items():
                if place not in sizes:
                    if place not in self._announced:
                        self._unobserved.append(f"{os.path.basename(place)} ({before} bytes) was gone at a reading, and "
                                                "no operation of this process had announced its removal")
                elif sizes[place] < before and place not in self._may_shrink and place not in self._announced:
                    self._unobserved.append(f"{os.path.basename(place)} went from {before} to {sizes[place]} bytes "
                                            "with no operation announcing it")
            # An announcement is kept, not consumed: the operation it stands for runs after the reading that preceded it,
            # and another thread's reading may come between the two.
            self._sizes = sizes
            self._ever.update(sizes)
            media = sorted(size for place, size in sizes.items() if self._sinks.get(place) != identities[place])
            logs = sorted(size for place, size in sizes.items() if self._sinks.get(place) == identities[place])
            now = {"media_bytes": sum(media), "media_files": len(media), "diagnostics_bytes": sum(logs),
                   "diagnostics_files": len(logs), "total_bytes": sum(media) + sum(logs),
                   "total_files": len(media) + len(logs)}
            self.readings[moment] = self.readings.get(moment, 0) + 1
            for key, value in now.items():
                if value > self.peak[key]:
                    self.peak[key] = value
                    if key in ("media_bytes", "total_bytes"):
                        self.at_peak[key] = {"moment": moment, "media": list(media), "diagnostics": list(logs)}
            return now

    # ------------------------------------------------------------------ the end, and the account
    def finish(self) -> None:
        """One last reading once the run has settled (what is still staged then was left behind), then the reckoning
        with what Windows reported. After this the census hears nothing more."""
        if self._finished:
            return
        self.left = self.read("end")
        drained = self._watch.mark()
        self._watch.stop()
        with self._lock:
            self._finished = True
            self._drained = drained
        with _hook:
            if self in _reading:
                _reading.remove(self)

    def record(self) -> dict:
        with self._lock:
            watch = self._watch
            left = self.left or {}
            finished = self._finished
            unreported = sorted((watch.removed | watch.renamed_from) - self._announced) if finished else []
            uncreated = sorted(self._ever - watch.added - watch.renamed_to) if finished else []
            written = sorted(set(self._opened) - set(self._sinks))
            return {
                "method": ("the real size of every owned temporary, read before each removal, rename, truncation and "
                           "writing-open this process makes, and held to Windows' own report of every removal and rename "
                           "under the base"),
                "base_chars": len(self.base),
                "peak_media_bytes": self.peak["media_bytes"], "peak_media_files": self.peak["media_files"],
                "peak_diagnostics_bytes": self.peak["diagnostics_bytes"],
                "peak_diagnostics_files": self.peak["diagnostics_files"],
                "peak_total_bytes": self.peak["total_bytes"], "peak_total_files": self.peak["total_files"],
                "readings": dict(self.readings),
                "at_peak": {key: {**value, "media": list(value["media"]), "diagnostics": list(value["diagnostics"])}
                            for key, value in self.at_peak.items()},
                "at_start_files": self.at_start["total_files"],
                "left_bytes": left.get("total_bytes"), "left_files": left.get("total_files"),
                "observer": {
                    "finished": finished,
                    "audit_hook": _hooked,
                    "watch": {"armed": bool(watch.armed), "drained": bool(getattr(self, "_drained", False)),
                              "lost": watch.lost, "error": watch.error, "events": watch.events,
                              "created": len(watch.added), "removed": len(watch.removed),
                              "renamed": len(watch.renamed_from)},
                    "diagnostics_sinks": len(self._sinks),
                    "unobserved": list(self._unobserved[:20]) + [
                        f"{os.path.basename(place)} was removed or renamed, as Windows reported, with no reading "
                        "taken for it" for place in unreported[:20]],
                    "without_creation": [os.path.basename(place) for place in uncreated[:20]],
                    "written_by_the_application": [f"{os.path.basename(place)} ({self._opened[place]})" for place in written[:20]],
                    "links": [os.path.basename(place) for place in sorted(self._links)[:20]],
                    "errors": list(self._errors[:20]),
                },
            }
