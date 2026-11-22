"""Reading imported sources off the Tk thread — v0.8.2 Checkpoint 6.

The MP3 Tool and the M4B Metadata Editor observe every file an import commits: the MP3 Tool reads its ID3 frames, the
Editor reads its MP4 tags and asks FFprobe for its chapter titles. Both did it inside the import's Tk callback, one
file after another, so a large import froze the window with the scan already finished: about 28 ms a file in the
Editor (FFprobe is a process per file; 2,341 files held the window for over a minute) and about 0.1 ms a file in the
MP3 Tool on warm small tags (0.5 s at 5,000; much more with embedded artwork or a cold disk).

This module holds what both panels need to do that reading on a worker instead, and nothing else. It touches no Tk,
no widget, no panel and no workspace. A panel builds one :class:`SourceReadback` per committed import with the readers
it would have called itself, runs :meth:`SourceReadback.read_sources` on one worker thread, and polls
:attr:`SourceReadback.finished` from its own pump. When it is finished, the panel hands :meth:`SourceReadback.reader`
lookups to the **unchanged** workflow functions (``import_folder`` / ``add_files``), which observe every occurrence
exactly as before; only the file reads already happened. So the observations -- readable or not, the reader's error
text, chapter titles, tag values -- are the ones the synchronous path produced, and the workflow modules stay the one
authority on what an import does to the workspace.

**Read-only.** The worker only calls the readers it was given. Every reader the panels pass is a read (mutagen's
``ID3``/``MP4`` constructors, ``ffprobe -show_chapters``); nothing here opens, writes, renames or deletes a file.

**Cancel and stale results.** :meth:`cancel` is a ``threading.Event`` the worker looks at between files, so it stops
after the file it is reading (a single read is not interrupted). The panel decides on Tk whether a finished readback
is still the one it is waiting for; this object only records that it finished and whether it was cancelled first.
A cancelled readback never reports finished, so it can never be adopted.

**Duplicates.** Each distinct path is read once, in the order first seen, however many occurrences name it; a lookup
answers every occurrence of that path with the same result (or re-raises the same reader exception, so the
observation's error text is identical).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

__all__ = ["SourceReadback"]


class SourceReadback:
    """One committed import's source reads, run once on a worker, answered on Tk.

    *paths* are the committed occurrences' paths in import order; *readers* maps the keyword each workflow import
    function takes for a reader to that reader (``{"reader": read_source_tags}``, or the Editor workflow's
    ``source_readers()``). Every reader is called once per distinct path, in the order given, with that path; the
    caller passes ``{name: readback.reader(name) for name in readers}`` to the same function.
    """

    __slots__ = ("label", "total", "_paths", "_readers", "_results", "_lock", "_done", "_cancel",
                 "_finished", "_failed", "_started", "fallbacks")

    def __init__(self, label: str, paths: Iterable[object],
                 readers: Mapping[str, Callable[[Path], object]]) -> None:
        if not readers:
            raise ValueError("a readback needs at least one reader")
        self.label = str(label)
        unique: dict[str, Path] = {}
        for path in paths:
            key = os.fspath(path)
            if key not in unique:
                unique[key] = Path(key)
        self._paths: tuple[tuple[str, Path], ...] = tuple(unique.items())
        self._readers = dict(readers)
        self.total = len(self._paths)
        self._results: dict[str, dict[str, tuple[bool, object]]] = {}
        self._lock = threading.Lock()
        self._done = 0
        self._cancel = threading.Event()
        self._finished = threading.Event()
        self._failed = threading.Event()
        self._started = False
        #: Lookups the worker had no answer for, read again on the caller's thread. Zero in every normal import; a
        #: non-zero count means a caller asked for a path or reader it did not hand over (tests watch it).
        self.fallbacks = 0

    # -- the worker -------------------------------------------------------- #

    def read_sources(self) -> None:
        """Read every distinct path with every reader, then mark the readback finished. Worker thread.

        A reader's exception is an answer, kept for the lookup. Anything else that ends the loop early (it should not
        happen) marks the readback :attr:`failed` instead of leaving it running for ever, so the panel can say so.
        """
        with self._lock:
            if self._started:
                return
            self._started = True
        completed = False
        try:
            for key, path in self._paths:
                if self._cancel.is_set():
                    return
                answers: dict[str, tuple[bool, object]] = {}
                for name, reader in self._readers.items():
                    try:
                        answers[name] = (True, reader(path))
                    except Exception as exc:  # noqa: BLE001 - kept whole; the workflow decides what a failure means
                        # The worker's frames are not kept alive by thousands of stored failures; type and text are.
                        answers[name] = (False, exc.with_traceback(None))
                with self._lock:
                    self._results[key] = answers
                    self._done += 1
            completed = True
        finally:
            if not self._cancel.is_set():
                (self._finished if completed else self._failed).set()

    # -- any thread -------------------------------------------------------- #

    def cancel(self) -> None:
        """Stop after the file being read. A cancelled readback never becomes finished."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def finished(self) -> bool:
        """Every path was read and nobody cancelled first."""
        return self._finished.is_set() and not self._cancel.is_set()

    @property
    def failed(self) -> bool:
        """The worker stopped before reading everything, and nobody cancelled. Nothing it read is adopted."""
        return self._failed.is_set() and not self._cancel.is_set()

    @property
    def done(self) -> int:
        """Distinct paths read so far."""
        with self._lock:
            return self._done

    # -- the caller's thread, once finished -------------------------------- #

    def reader(self, name: str) -> Callable[[Path], object]:
        """A reader with the same contract as the one named *name*, answered from what the worker read.

        It returns the worker's value for that path, or raises the exception the real reader raised there. A path
        the worker never read (not one of *paths*) is read now with the real reader and counted in
        :attr:`fallbacks`, so a caller's mistake costs time on its own thread, never a wrong observation.
        """
        real = self._readers[name]

        def answer(path: object) -> object:
            found = self._results.get(os.fspath(path), {}).get(name)
            if found is None:
                self.fallbacks += 1
                return real(Path(os.fspath(path)))
            ok, value = found
            if ok:
                return value
            raise value  # the very exception the reader raised: same type, same text

        return answer

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"SourceReadback({self.label!r}, done={self.done}/{self.total}, "
                f"finished={self.finished}, cancelled={self.cancelled})")
