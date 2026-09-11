#!/usr/bin/env python3
"""Developer-only harness for the Plan 6 shared multi-book workspace.

**This is not part of the product and not part of the test suite.**

- pytest never collects it: the filename is not ``test_*`` and it declares no test
  functions.
- The launcher cannot reach it: it is not registered in ``launcher.TOOLS``, it lives
  under ``files/`` (the developer tree) rather than ``scripts/`` (the shipped tree),
  the release packager builds its archives from an explicit ``scripts/`` scope, and
  nothing in the product imports it.
- It adds no behaviour. Every widget below is the *production* Phase 8 adapter from
  ``shared/book_workspace_ui.py``, driven by the *production* Phase 1-4 model
  operations from ``shared/book_workspace.py``. Nothing is patched, stubbed or
  bypassed, and the confirmation dialog is the real ``job_ui.ask_confirm``.

Why it exists
-------------
Phase 8 is the plan's first manual gate. It has to show things a unit test cannot
photograph: whether the Shared Metadata region reads as *global* before you have
finished reading the words in it, whether ``Book X of Y`` stays right while you add
and remove books, whether removing a pristine book gets out of your way while removing
a book with work in it stops and asks, and whether every action is still reachable at
the 920x600 minimum. Building that during the manual phase would mean writing code in
a verification phase, so it is written here.

What it will not do
-------------------
It touches no disk. The imported-file records it builds are **test-owned values over
paths that are never opened, stat-ed, created or required to exist** — they exist so
that "this book has work in it" is a real model answer rather than a pretend one. It
runs no conversion, no ffmpeg, no TTS engine, no subprocess and no network call. It
reserves, creates, inspects and validates no output. It writes no setting and touches
no runtime data. There is no sleep, no timer and no worker thread: the adapter is
push-driven, so every repaint below is a direct consequence of a button you pressed.

The harness owns the model
--------------------------
The mutable Python reference to the current immutable ``WorkspaceSnapshot`` lives
here, in ``Harness._workspace``, and nowhere else. The adapter never holds it to edit.
Every button press arrives as a callback, this file calls the model operation, and the
resulting snapshot is handed straight back to ``render``. That is the whole Phase 8
contract, demonstrated rather than asserted.

Usage, from the repository root with the repository virtual environment::

    .venv\\Scripts\\python.exe files/tests/manual_plan6_harness.py
    .venv\\Scripts\\python.exe files/tests/manual_plan6_harness.py --books 3
    .venv\\Scripts\\python.exe files/tests/manual_plan6_harness.py --geometry 920x600
    .venv\\Scripts\\python.exe files/tests/manual_plan6_harness.py --books 4 --layout rows

``--layout rows`` shows the compact geometry the focused MP3 continuation added
(Shared above This Book, fields left to right); the default is the prototype's
side-by-side ``columns``. The direct Book selector beside ``Book X of Y`` lists
every book as ``Book N`` or ``Book N — <Title>``; the hint is this harness's own
``title`` field, handed to the navigator as a ``describe`` callback.
"""

from __future__ import annotations

import argparse
import os
import sys
import tkinter as tk
from pathlib import Path, PurePath
from tkinter import ttk

_UNIVERSAL = Path(__file__).resolve().parents[2] / "scripts" / "Universal"
if str(_UNIVERSAL) not in sys.path:
    sys.path.insert(0, str(_UNIVERSAL))

from shared import job_ui, ui_theme  # noqa: E402
from shared.book_workspace import (  # noqa: E402
    BookJob,
    SharedMetadata,
    WorkspaceSnapshot,
    add_book,
    disabled_fields,
    duplicate_book,
    has_meaningful_work,
    new_book_id,
    next_book,
    previous_book,
    remove_book,
    replace_book,
    select_book,
    set_shared_metadata,
)
from shared.book_workspace_ui import BookNavigator, SharedMetadataSurface  # noqa: E402
from shared.importing import (  # noqa: E402
    IdFactory,
    ImportedFile,
    ImportedFileSnapshot,
    ImportRoot,
    Revision,
)

#: This harness's own consumer vocabulary, as ``(field key, display label)`` pairs.
#: It lives here, in a *consumer*, and must never migrate into the adapter:
#: ``book_workspace_ui.py`` knows no field names and no field labels.
#:
#: There is deliberately **no narrator**. The maintainer does not use narrator
#: metadata, and a demonstration field nobody wants is vertical space taken from
#: the ones they do — two fields show the Shared-override contract exactly as well
#: as three.
FIELDS = (("title", "Title"), ("author", "Author"))

#: The keys alone, for the model calls that take a plain vocabulary.
FIELD_KEYS = tuple(key for key, _label in FIELDS)

#: This harness's own per-book configuration key for the chapter-title text.
#:
#: It is **ordinary ``BookJob.configuration``** and nothing more: a single raw
#: multiline string, which is what a Tk ``Text`` naturally reads and writes and
#: what a future consumer can split into lines when it actually adopts this
#: foundation. Plan 6 does not interpret chapter semantics, so it stores none —
#: no chapter model, no times, no ffmetadata, no shared registry, and this key
#: appears nowhere in the adapter or in ``SharedMetadata``.
CHAPTER_FIELD = "chapter_titles"

#: A path root that is never touched. Nothing below opens, creates or stats it.
FICTIONAL_ROOT = Path(os.path.abspath(os.sep + "act-plan6-harness-not-on-disk"))
FICTIONAL_IMPORT_ROOT = ImportRoot("harness-root", FICTIONAL_ROOT, 0)


def imported(label: str, count: int = 3) -> ImportedFileSnapshot:
    """Synthetic imported inputs, so meaningful-work is a real answer.

    These are ordinary frozen Plan 3 values. **No path here is ever opened, read,
    written, created or checked for existence** — the model only needs occurrence
    identity and ordering, which is exactly what makes this safe.
    """
    return ImportedFileSnapshot(Revision(1), tuple(
        ImportedFile(
            f"{label}-occ-{index}",
            FICTIONAL_ROOT / label / f"{index:02d}.mp3",
            FICTIONAL_IMPORT_ROOT,
            PurePath(label) / f"{index:02d}.mp3",
            "mp3",
            f"{label}-id-{index}",
        )
        for index in range(1, count + 1)))


class Harness:
    """One window: the production navigator, the production surface, and a log.

    This class is the *consumer*. It owns the workspace, applies the model
    operations, decides whether a removal deserves a confirmation, and re-renders.
    """

    def __init__(self, root: tk.Tk, *, books: int = 1,
                 layout: str = "columns") -> None:
        self.root = root
        self.ids = IdFactory("harness-")
        self.theme = ui_theme.apply_theme(root, ttk.Style(root))

        root.title("Plan 6 — shared multi-book workspace (developer harness)")
        root.geometry(self.theme.get("geometry", ui_theme.DEFAULT_GEOMETRY))
        root.minsize(*self.theme.get("min_size", ui_theme.MIN_SIZE))

        self._workspace = self._starting_workspace(books)
        self._suspend_chapters = False

        container = ttk.Frame(root, style=job_ui.style_name(self.theme, "card"))
        container.pack(fill="both", expand=True, padx=12, pady=12)
        container.columnconfigure(0, weight=1)
        # Row 4 is the diagnostic log, and it is the only row that expands: at
        # 920x600 the form and the navigation keep their natural size and the log
        # gives up the space instead.
        container.rowconfigure(4, weight=1)

        ttk.Label(
            container,
            text="Plan 6 foundation — no production panel adopts this yet.",
            style=job_ui.style_name(self.theme, "section"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.navigator = BookNavigator(
            container, theme=self.theme, describe=self.describe,
            on_previous=self.on_previous, on_next=self.on_next,
            on_add=self.on_add, on_duplicate=self.on_duplicate,
            on_remove=self.on_remove, on_select=self.on_select)
        self.navigator.frame.grid(row=1, column=0, sticky="ew")

        self.surface = SharedMetadataSurface(
            container, FIELDS, theme=self.theme, layout=layout,
            on_shared_change=self.on_shared_change,
            on_book_change=self.on_book_change)
        self.surface.frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        # Chapter titles: per book, and deliberately NOT Shared Metadata. It is
        # below the two metadata columns and outside both of them, so there is no
        # reading of this layout in which it looks global.
        self.chapters = ttk.Labelframe(
            container, text="Chapter Titles",
            style=job_ui.style_name(self.theme, "labelframe"))
        self.chapters.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.chapters.columnconfigure(0, weight=1)
        ttk.Label(self.chapters, text="One chapter title per line.",
                  style=job_ui.style_name(self.theme, "secondary_label")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.chapter_text = tk.Text(self.chapters, height=5, wrap="none",
                                    undo=True)
        chapter_scroll = ttk.Scrollbar(
            self.chapters, orient="vertical", command=self.chapter_text.yview,
            style=job_ui.style_name(self.theme, "vscrollbar"))
        self.chapter_text.configure(yscrollcommand=chapter_scroll.set)
        self.chapter_text.grid(row=1, column=0, sticky="ew")
        chapter_scroll.grid(row=1, column=1, sticky="ns")
        # An editable per-book field, so it takes the ordinary field colours. Using
        # the Shared role merely to make it dark would say "global", which is the
        # one thing this control is not.
        ui_theme.style_tk_widget(self.chapter_text, self.theme, role="text")
        self.chapter_text.bind("<KeyRelease>", self.on_chapter_edit)

        # The one variable-length collection here is this log, so it is the only
        # thing that scrolls. The bounded Plan 6 content above never does.
        log_frame = ttk.Frame(container, style=job_ui.style_name(self.theme, "card"))
        log_frame.grid(row=4, column=0, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        ttk.Label(log_frame, text="What the model did",
                  style=job_ui.style_name(self.theme, "section")).grid(
            row=0, column=0, sticky="w")
        self.log = tk.Text(log_frame, height=8, wrap="none")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set, state="disabled")
        self.log.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")
        ui_theme.style_tk_widget(self.log, self.theme, role="log")

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.render()
        self.say("Ready. Everything below is the production model and adapter.")

    # -- the model ---------------------------------------------------------- #

    def _starting_workspace(self, books: int) -> WorkspaceSnapshot:
        first = BookJob(book_id=new_book_id(self.ids))
        entries = [first]
        for index in range(1, max(1, books)):
            entries.append(BookJob(
                book_id=new_book_id(self.ids),
                configuration={"title": f"Second book {index}",
                               CHAPTER_FIELD: "Chapter One\nChapter Two"},
                files=imported(f"book{index}")))
        return WorkspaceSnapshot(
            books=tuple(entries), current_book_id=first.book_id,
            shared=SharedMetadata.for_fields(FIELD_KEYS))

    def apply(self, mutation) -> None:
        """Take the model's answer, or say plainly that it declined."""
        if mutation.changed:
            self._workspace = mutation.workspace
            self.say(f"{mutation.operation.value}: applied "
                     f"(revision {mutation.workspace.revision.value})")
        else:
            self.say(f"{mutation.operation.value}: no-op, the model declined")
        self.render()

    def render(self) -> None:
        self.navigator.render(self._workspace)
        overridden = self.surface.render(self._workspace)
        self.render_chapters()
        current = self._workspace.current
        self.say(
            f"  → {self.navigator.position_text}"
            f" | meaningful work: {has_meaningful_work(current)}"
            f" | files: {len(current.files.files)}"
            f" | shared overrides: {sorted(overridden) or 'none'}")

    def render_chapters(self) -> None:
        """Show the current book's chapter text. Rendering is not a user edit."""
        raw = str(self._workspace.current.configuration.get(CHAPTER_FIELD, ""))
        if raw == self.chapter_text.get("1.0", "end-1c"):
            return                      # nothing to do, and no cursor to disturb
        self._suspend_chapters = True
        try:
            self.chapter_text.delete("1.0", "end")
            if raw:
                self.chapter_text.insert("1.0", raw)
        finally:
            self._suspend_chapters = False

    def on_chapter_edit(self, _event=None) -> None:
        """A keystroke in the chapter box. Ordinary per-book configuration.

        The raw multiline string goes straight into this book's configuration
        through the same immutable ``replace_book`` flow every other edit uses.
        Nothing here parses a line, counts a chapter, reads a duration or writes a
        file — that is the consumer's job when one actually adopts this, and the
        M4B Maker already owns chapter generation.
        """
        if self._suspend_chapters:
            return
        raw = self.chapter_text.get("1.0", "end-1c")
        current = self._workspace.current
        if str(current.configuration.get(CHAPTER_FIELD, "")) == raw:
            return
        configuration = dict(current.configuration)
        if raw:
            configuration[CHAPTER_FIELD] = raw
        else:
            configuration.pop(CHAPTER_FIELD, None)
        mutation = replace_book(self._workspace, BookJob(
            book_id=current.book_id, configuration=configuration,
            files=current.files))
        if mutation.changed:
            self._workspace = mutation.workspace
        self.navigator.render(self._workspace)
        lines = len([line for line in raw.splitlines() if line.strip()])
        self.say(f"chapter titles: {lines} line(s) on this book "
                 f"| meaningful work: {has_meaningful_work(self._workspace.current)}")

    # -- navigator callbacks ------------------------------------------------ #

    def describe(self, entry: BookJob) -> str:
        """The selector's hint for one book: this consumer's own ``title`` field.

        The adapter knows no field name; what a row says after ``Book N`` is this
        file's decision, and a blank title simply leaves the row as ``Book N``.
        """
        return str(entry.configuration.get("title", ""))

    def on_select(self, book_id: str) -> None:
        """The direct selector reported a stable id. The model moves; we render."""
        self.apply(select_book(self._workspace, book_id))

    def on_previous(self) -> None:
        self.apply(previous_book(self._workspace))

    def on_next(self) -> None:
        self.apply(next_book(self._workspace))

    def on_add(self) -> None:
        self.apply(add_book(self._workspace, id_factory=self.ids))

    def on_duplicate(self) -> None:
        self.apply(duplicate_book(self._workspace, id_factory=self.ids))

    def on_remove(self, meaningful: bool) -> None:
        """Decision 50A, on the consumer's side of the line.

        The adapter told us what the *model* says about this book. Whether that
        deserves a dialog is this file's decision, and the dialog is the existing
        shared one — Plan 6 added no confirmation helper.
        """
        if meaningful:
            self.say("remove: this book has work in it — asking first")
            confirmed = job_ui.ask_confirm(
                self.root, "Remove book",
                "This book has imported files or edited settings.\n\n"
                "Remove it anyway?")
            if not confirmed:
                self.say("remove: cancelled, nothing changed")
                self.render()
                return
        else:
            self.say("remove: pristine book — removing without asking")
        self.apply(remove_book(self._workspace, id_factory=self.ids))

    # -- surface callbacks -------------------------------------------------- #

    def on_shared_change(self, field: str, raw: str) -> None:
        """A shared field was typed in. Build the new value and let the model rule."""
        values = dict(self._workspace.shared.values)
        values[field] = raw
        mutation = set_shared_metadata(
            self._workspace, SharedMetadata(FIELD_KEYS, values))
        if mutation.changed:
            self._workspace = mutation.workspace
        self.navigator.render(self._workspace)
        overridden = self.surface.render(self._workspace)
        self.say(f"shared {field}={raw!r} → disabled per-book fields: "
                 f"{sorted(overridden) or 'none'}")

    def on_book_change(self, field: str, raw: str) -> None:
        """A per-book field was typed in. Only this book's raw value moves."""
        current = self._workspace.current
        configuration = dict(current.configuration)
        configuration[field] = raw
        mutation = replace_book(self._workspace, BookJob(
            book_id=current.book_id, configuration=configuration,
            files=current.files))
        if mutation.changed:
            self._workspace = mutation.workspace
        self.navigator.render(self._workspace)
        self.say(f"book {field}={raw!r} (this book only)")

    # -- window ------------------------------------------------------------- #

    def say(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def close(self) -> None:
        self.navigator.close()
        self.surface.close()
        self.root.destroy()

    # -- read-back seams the automated tests drive -------------------------- #

    def chapter_titles_text(self) -> str:
        """Exactly what is in the chapter box, raw."""
        return self.chapter_text.get("1.0", "end-1c")

    def type_chapter_titles(self, raw: str) -> None:
        """Type into the chapter box as a person would, then report it."""
        self.chapter_text.delete("1.0", "end")
        if raw:
            self.chapter_text.insert("1.0", raw)
        self.on_chapter_edit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Developer-only Plan 6 workspace harness. Touches no disk.")
    parser.add_argument("--books", type=int, default=1,
                        help="how many books to start with (default 1)")
    parser.add_argument("--geometry", default=None,
                        help="override the window geometry, e.g. 920x600")
    parser.add_argument("--layout", default="columns",
                        choices=SharedMetadataSurface.LAYOUTS,
                        help="Shared Metadata geometry (default columns)")
    args = parser.parse_args(argv)

    window = tk.Tk()
    harness = Harness(window, books=args.books, layout=args.layout)
    if args.geometry:
        window.geometry(args.geometry)
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
