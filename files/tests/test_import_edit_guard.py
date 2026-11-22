"""Edits made while an Import Folder is still running are never silently replaced — v0.8.2 qualification.

Import Folder replaces every Book. The user answers "Replace the current Books?" (asked only when a Book holds work)
when they press it; the scan and, since Checkpoint 6, the reading of every file's tags (minutes for thousands of
M4Bs in the Metadata Editor) then run while the Books stay editable. Before this guard the import replaced whatever
the Books held when it completed, so a field typed, Chapter Titles pasted, a track moved or a Book removed after the
press was discarded without a word. Reproduced on ``5da1271`` in all three Book tools (MP3 Tool and Metadata Editor
during the reading, M4B Maker during the scan).

What this module proves:

- the replacement goes ahead exactly as before when the Books are what the user agreed to replace: untouched, only
  browsed (navigation is not an edit), only Shared fields changed (Shared Metadata is carried through a replacement),
  or edited and put back to the identical value;
- when a Book was changed after the press -- a field, pasted Chapter Titles (no key release), a track moved or
  removed, a Book added, duplicated or removed, in a workspace that needed no confirmation too -- nothing is
  replaced, every edit is kept, the tool says why and what to do (status line, Summary, one warning) and is free
  again; a repeated or stale completion changes nothing;
- Cancel Import and a reading that fails keep the edits (nothing is added);
- Add Files is a merge, not a replacement, and is not refused by an edit (the files still land in the Book pressed
  on, by identity, and that Book's edits are kept).

Synthetic placeholders under ``tmp_path`` only.
"""

from __future__ import annotations

import threading

import pytest

tk = pytest.importorskip("tkinter")

from m4b.maker import m4b_maker_workflow as kwf  # noqa: E402
from m4b.metadata import m4b_metadata_editor as editor  # noqa: E402
from mp3 import mp3_workflow as mwf  # noqa: E402

from test_import_coordination import ControlledScanner, RealThreads  # noqa: E402
from test_import_readback import (  # noqa: E402,F401  (fixtures by name)
    Gate, container, editor_library, gated_readers, make_editor_panel, make_maker_panel, make_mp3_panel,
    mp3_library, output_base, pump_until, snapshot_of, summary, tk_root, windows_theme)

REFUSED = ("Import Folder: the Books were changed while the import was running, so they were not replaced and "
           "your changes were kept. Choose Import Folder again to replace them.")


def join_all(panel) -> None:
    for thread in getattr(panel._thread_factory, "made", ()):
        if isinstance(thread, threading.Thread) and thread.ident is not None:
            thread.join(10.0)


# --------------------------------------------------------------------------- #
# MP3 Tool: edits while the tags are read
# --------------------------------------------------------------------------- #


def mp3_reading(make_mp3_panel, tmp_path, *, seed: bool = True):
    """A panel with two imported Books (if *seed*) and a second Import Folder parked in its reading."""
    first = mp3_library(tmp_path / "first", 2, 2)
    second = mp3_library(tmp_path / "second", 3, 1)
    gate = Gate(mwf.read_source_tags)
    panel = make_mp3_panel(thread_factory=RealThreads(), reader=gate)
    if seed:
        gate.open.set()
        panel._choose_folder = lambda: (str(first),)
        panel.import_folder()
        pump_until(panel, lambda: not panel.is_reading_tags and len(panel.workspace.books) == 2)
        gate.open.clear()
    panel._choose_folder = lambda: (str(second),)
    panel.import_folder()
    pump_until(panel, lambda: panel.is_reading_tags and gate.calls >= (5 if seed else 1))
    return panel, gate


def finish(panel, gate) -> None:
    gate.open.set()
    pump_until(panel, lambda: not panel._import_busy)


def replaced_by_second(panel) -> bool:
    return [len(book.files.files) for book in panel.workspace.books] == [1, 1, 1]


@pytest.mark.parametrize("edit", ["field", "pasted_titles", "move_track", "remove_track", "add_book",
                                  "duplicate_book", "remove_book"])
def test_mp3_an_edit_while_the_tags_are_read_is_kept_and_nothing_is_replaced(make_mp3_panel, tmp_path, edit):
    panel, gate = mp3_reading(make_mp3_panel, tmp_path)
    if edit == "field":
        panel.set_book_field("album", "Typed while reading")
    elif edit == "pasted_titles":
        panel.chapter_text.delete("1.0", "end")
        panel.chapter_text.insert("1.0", "Pasted One\nPasted Two")  # no key release: only the flush sees it
    elif edit == "move_track":
        panel.select_tracks(1)
        panel.move_up()
    elif edit == "remove_track":
        panel.select_tracks(0)
        panel.remove_selected_tracks()
    elif edit == "add_book":
        panel.on_add()
    elif edit == "duplicate_book":
        panel.on_duplicate()
    else:
        panel.on_remove(True)
    panel.flush_pending_editor_state()
    edited = snapshot_of(panel)
    finish(panel, gate)
    assert not replaced_by_second(panel)
    assert snapshot_of(panel) == edited, "every edit made while the tags were read is kept"
    assert summary(panel)[-1] == REFUSED
    assert panel.import_status.text == REFUSED and not panel.import_status.cancel_enabled
    assert make_mp3_panel.dialogs[-1] == ("warning", REFUSED)
    # A repeated or stale completion changes nothing, and the tool is free again.
    pending_count = len(summary(panel))
    panel._drain_readback()
    panel._pump.tick()
    assert snapshot_of(panel) == edited and len(summary(panel)) == pending_count
    assert not panel._import_busy
    gate.open.set()
    panel.import_folder()
    pump_until(panel, lambda: not panel._import_busy)
    assert replaced_by_second(panel), "Import Folder again replaces them"


def test_mp3_a_paste_nothing_reported_yet_is_committed_and_kept_at_completion(make_mp3_panel, tmp_path):
    """The paste reaches the model only through the guard's own flush: no key release, no navigation, no render."""
    panel, gate = mp3_reading(make_mp3_panel, tmp_path)
    owner = panel.workspace.current_book_id
    panel.chapter_text.delete("1.0", "end")
    panel.chapter_text.insert("1.0", "Unreported One\nUnreported Two")
    panel.chapter_text.edit_modified(False)  # as if <<Modified>> had not been serviced yet
    finish(panel, gate)
    assert not replaced_by_second(panel)
    books = {book.book_id: book for book in panel.workspace.books}
    assert books[owner].configuration.get("chapter_titles") == "Unreported One\nUnreported Two"
    assert summary(panel)[-1] == REFUSED


def test_mp3_an_edit_in_a_workspace_that_needed_no_confirmation_is_kept(make_mp3_panel, tmp_path):
    panel, gate = mp3_reading(make_mp3_panel, tmp_path, seed=False)
    panel.set_book_field("album", "Typed into the empty Book")
    edited = snapshot_of(panel)
    finish(panel, gate)
    assert snapshot_of(panel) == edited and summary(panel)[-1] == REFUSED


@pytest.mark.parametrize("change", ["nothing", "navigate", "select", "shared", "edit_and_revert"])
def test_mp3_the_replacement_goes_ahead_when_no_book_was_changed(make_mp3_panel, tmp_path, change):
    panel, gate = mp3_reading(make_mp3_panel, tmp_path)
    if change == "navigate":
        panel.on_next()
        panel.on_previous()
        panel.on_next()
    elif change == "select":
        panel.on_select(panel.workspace.books[1].book_id)
    elif change == "shared":
        panel.on_shared_change("artist", "Shared while reading")
    elif change == "edit_and_revert":
        before = panel.workspace.current.configuration.get("album")
        panel.set_book_field("album", "Briefly")
        panel.set_book_field("album", before)
    finish(panel, gate)
    assert replaced_by_second(panel)
    assert summary(panel)[-1] == "Import Folder: 3 MP3 file(s) in 3 Book(s)."
    assert not any(kind == "warning" for kind, _ in make_mp3_panel.dialogs)
    if change == "shared":
        assert panel.workspace.shared.values.get("artist") == "Shared while reading", "Shared is carried through"


def test_mp3_cancel_import_after_an_edit_keeps_it(make_mp3_panel, tmp_path):
    panel, gate = mp3_reading(make_mp3_panel, tmp_path)
    panel.set_book_field("album", "Typed while reading")
    edited = snapshot_of(panel)
    assert panel.cancel_import() is True
    finish(panel, gate)
    join_all(panel)
    panel._pump.tick()
    assert snapshot_of(panel) == edited
    assert summary(panel)[-1] == "Import Folder: The import was cancelled and nothing was added."


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")  # the injected fault
def test_mp3_a_reading_that_fails_after_an_edit_keeps_it(make_mp3_panel, tmp_path):
    lib = mp3_library(tmp_path / "lib", 2, 1)
    release = threading.Event()

    def dies(path):
        release.wait(10.0)
        raise SystemExit("the worker ends without an answer")

    panel = make_mp3_panel(thread_factory=RealThreads(), reader=dies)
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    pump_until(panel, lambda: panel.is_reading_tags)
    panel.set_book_field("album", "Typed while reading")
    edited = snapshot_of(panel)
    release.set()
    pump_until(panel, lambda: not panel._import_busy)
    assert snapshot_of(panel) == edited
    assert summary(panel)[-1] == "Import Folder: The files could not be read, so nothing was added."


def test_mp3_add_files_is_a_merge_and_keeps_the_target_books_edits(make_mp3_panel, tmp_path):
    lib = mp3_library(tmp_path / "lib", 2, 2)
    extra = mp3_library(tmp_path / "extra", 1, 2)
    gate = Gate(mwf.read_source_tags)
    gate.open.set()
    panel = make_mp3_panel(thread_factory=RealThreads(), reader=gate)
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    pump_until(panel, lambda: not panel.is_reading_tags and len(panel.workspace.books) == 2)
    first = panel.workspace.current_book_id
    gate.open.clear()
    panel._choose_files = lambda: tuple(str(p) for p in sorted((extra / "Book 1").glob("*.mp3")))
    panel.add_files()
    pump_until(panel, lambda: panel.is_reading_tags and gate.calls >= 5)
    panel.set_book_field("album", "Typed on the target")
    panel.chapter_text.delete("1.0", "end")
    panel.chapter_text.insert("1.0", "Kept One\nKept Two")
    panel.on_next()
    finish(panel, gate)
    target = next(book for book in panel.workspace.books if book.book_id == first)
    assert len(target.files.files) == 4
    assert target.configuration.get("album") == "Typed on the target"
    assert target.configuration.get("chapter_titles") == "Kept One\nKept Two"
    assert summary(panel)[-1] == "Add Files: 2 MP3 file(s) added to Book 1 of 2."
    assert not any(kind == "warning" for kind, _ in make_mp3_panel.dialogs)


# --------------------------------------------------------------------------- #
# Metadata Editor: edits while the tags and chapters are read
# --------------------------------------------------------------------------- #


def editor_reading(make_editor_panel, container, tmp_path, monkeypatch):
    first = tmp_path / "first"
    first.mkdir()
    editor_library(container, first)
    second = tmp_path / "second"
    second.mkdir()
    (second / "Solo.m4b").write_bytes(b"not an mp4")
    panel = make_editor_panel()  # inline threads for the first import
    panel._choose_folder = lambda: (str(first),)
    panel.import_folder()
    panel._pump.tick()
    assert len(panel.workspace.books) == 3
    gate_open = threading.Event()
    gated_readers(monkeypatch, gate_open)
    panel._thread_factory = RealThreads()
    panel._choose_folder = lambda: (str(second),)
    panel.import_folder()
    pump_until(panel, lambda: panel.is_reading_sources)
    return panel, gate_open


@pytest.mark.parametrize("edit", ["field", "pasted_titles", "remove_book", "navigate_only"])
def test_editor_an_edit_while_the_sources_are_read_is_kept(make_editor_panel, container, tmp_path, monkeypatch,
                                                            edit):
    panel, gate_open = editor_reading(make_editor_panel, container, tmp_path, monkeypatch)
    if edit == "field":
        panel.set_book_field("title", "Typed while reading")
    elif edit == "pasted_titles":
        panel.chapter_text.delete("1.0", "end")
        panel.chapter_text.insert("1.0", "Pasted chapter")
    elif edit == "remove_book":
        panel.on_remove(True)
    else:
        panel.on_next()
    panel.flush_pending_editor_state()
    edited = snapshot_of(panel)
    gate_open.set()
    pump_until(panel, lambda: not panel._import_busy)
    if edit == "navigate_only":
        assert [book.files.files[0].path.name for book in panel.workspace.books] == ["Solo.m4b"]
        assert not any(kind == "warning" for kind, _ in make_editor_panel.dialogs)
        return
    assert snapshot_of(panel) == edited and len(panel.workspace.books) >= 2
    assert summary(panel)[-1] == REFUSED and panel.import_status.text == REFUSED
    assert make_editor_panel.dialogs[-1] == ("warning", REFUSED)
    panel._drain_readback()
    assert snapshot_of(panel) == edited and not panel._import_busy


def test_editor_a_paste_nothing_reported_yet_is_committed_and_kept_at_completion(make_editor_panel, container,
                                                                                  tmp_path, monkeypatch):
    panel, gate_open = editor_reading(make_editor_panel, container, tmp_path, monkeypatch)
    owner = panel.workspace.current_book_id
    panel.chapter_text.delete("1.0", "end")
    panel.chapter_text.insert("1.0", "Unreported chapter")
    panel.chapter_text.edit_modified(False)
    gate_open.set()
    pump_until(panel, lambda: not panel._import_busy)
    books = {book.book_id: book for book in panel.workspace.books}
    assert owner in books, "the Books were not replaced"
    assert "Unreported chapter" in str(books[owner].configuration.get("chapter_titles"))
    assert summary(panel)[-1] == REFUSED


# --------------------------------------------------------------------------- #
# M4B Maker: edits while the folder is scanned (no reading; the scan is the window)
# --------------------------------------------------------------------------- #


def maker_scanning(make_maker_panel, tmp_path):
    first = mp3_library(tmp_path / "first", 2, 2, tags=False)
    second = mp3_library(tmp_path / "second", 3, 1, tags=False)
    started, release = threading.Event(), threading.Event()
    release.set()
    scanner = ControlledScanner(started=started, release=release)
    panel = make_maker_panel(thread_factory=RealThreads(), scanner=scanner)
    panel._choose_folder = lambda: (str(first),)
    panel.import_folder()
    pump_until(panel, lambda: not panel._coordinator.is_active and len(panel.workspace.books) == 2)
    release.clear()
    started.clear()
    panel._choose_folder = lambda: (str(second),)
    panel.import_folder()
    assert started.wait(10.0)
    return panel, release


@pytest.mark.parametrize("edit", ["field", "pasted_titles", "move_track", "remove_track", "add_book",
                                  "duplicate_book", "remove_book", "navigate_only"])
def test_maker_an_edit_while_the_folder_is_scanned_is_kept(make_maker_panel, tmp_path, edit):
    panel, release = maker_scanning(make_maker_panel, tmp_path)
    if edit == "field":
        panel.set_book_field("title", "Typed while scanning")
    elif edit == "pasted_titles":
        panel.chapter_text.delete("1.0", "end")
        panel.chapter_text.insert("1.0", "Pasted One\nPasted Two")  # no key release: only the flush sees it
    elif edit == "move_track":
        panel.select_tracks(1)
        panel.move_up()
    elif edit == "remove_track":
        panel.select_tracks(0)
        panel.remove_selected_tracks()
    elif edit == "add_book":
        panel.on_add()
    elif edit == "duplicate_book":
        panel.on_duplicate()
    elif edit == "remove_book":
        panel.on_remove(True)
    else:
        panel.on_next()
    panel.flush_pending_editor_state()
    edited = snapshot_of(panel)
    release.set()
    pump_until(panel, lambda: not panel._coordinator.is_active)
    panel._pump.tick()
    if edit == "navigate_only":
        assert [len(book.files.files) for book in panel.workspace.books] == [1, 1, 1]
        assert not any(kind == "warning" for kind, _ in make_maker_panel.dialogs)
        return
    assert snapshot_of(panel) == edited
    assert summary(panel)[-1] == REFUSED and panel.import_status.text == REFUSED
    assert make_maker_panel.dialogs[-1] == ("warning", REFUSED)
    assert kwf  # the workflow is unchanged: the guard is the panel's


def test_maker_a_paste_nothing_reported_yet_is_committed_and_kept_at_completion(make_maker_panel, tmp_path):
    panel, release = maker_scanning(make_maker_panel, tmp_path)
    owner = panel.workspace.current_book_id
    panel.chapter_text.delete("1.0", "end")
    panel.chapter_text.insert("1.0", "Unreported One\nUnreported Two")
    panel.chapter_text.edit_modified(False)  # no key release and no flush: only the completion's check sees it
    release.set()
    pump_until(panel, lambda: not panel._coordinator.is_active)
    panel._pump.tick()
    books = {book.book_id: book for book in panel.workspace.books}
    assert owner in books, "the Books were not replaced"
    assert books[owner].configuration.get("chapter_titles") == "Unreported One\nUnreported Two"
    assert summary(panel)[-1] == REFUSED and panel.import_status.text == REFUSED
