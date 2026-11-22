"""Large-workspace GUI responsiveness — v0.8.2 Checkpoint 6.

Measured at ``1d47024`` on HOME-PC (real mapped panels, real import threads, real readers on real media copies,
20 ms heartbeat; ``files/dev-work/v0.8.2-cp6-evidence``):

- the Metadata Editor read every imported file's tags and asked FFprobe for its chapters inside the import's Tk
  callback, about 29 ms a file: Import Folder held the window 7.3 s at 250 files, 70 s at 2,341 and 149 s at 5,000;
  Add Files 39 s for 1,250. The MP3 Tool read its ID3 frames the same way (0.5 s at 5,000 small warm files);
- every render renumbered the Books with ``book_id in <list>`` (quadratic) and the Editor built every Book's whole
  page of values to label the selector: 0.16-0.25 s a keystroke or Book switch at 5,000 Books;
- the shared imported-file list rebuilt a set per row when selecting: Select All 0.68-0.75 s at 5,000 files.

What this module proves:

- ``shared.source_readback``: each distinct path read once, in order; a reader's failure comes back as the same
  exception (so the observation's error text is the one the synchronous path wrote); Cancel stops between files and a
  cancelled readback never finishes; it imports no Tk and writes nothing;
- both panels: the committed import is read on a worker (never on Tk), the workspace does not change until every
  file was read, the import counts as running meanwhile (progress line, Cancel Import, and Import / Add Files /
  Clear All Imports / Start refused), Cancel Import and Close drop the reading and a late result changes nothing, and
  the Books it then makes are exactly the ones the synchronous reading made (observations included);
- MP3 Add Files lands in the Book it was pressed on even if another Book is showing when the tags arrive, a pasted
  Chapter Titles edit on the showing Book is kept, and a Book removed meanwhile receives nothing;
- a real Tk loop keeps its heartbeat while a slow import is read;
- Book numbering and the Editor's selector hint are linear and equal to the old rule; Select All is linear.

Synthetic placeholders and FFmpeg-built fixtures under ``tmp_path`` only.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

tk = pytest.importorskip("tkinter")

from shared import job_ui, source_readback  # noqa: E402
from shared.book_workspace import SharedMetadata, set_shared_metadata  # noqa: E402
from shared.importing import ImportedFileManager  # noqa: E402

from m4b.maker import m4b_maker  # noqa: E402
from m4b.metadata import m4b_metadata_editor as editor  # noqa: E402
from m4b.metadata import m4b_metadata_workflow as ewf  # noqa: E402
from mp3 import mp3_tool, mp3_workflow as mwf  # noqa: E402

import test_job_ui as tju  # noqa: E402
from test_import_coordination import RealThreads, RecordingThreads  # noqa: E402
from test_m4b_metadata_processing import container  # noqa: E402,F401  (fixture by name)
from test_m4b_metadata_workflow import m4b  # noqa: E402
from test_mp3_tool_ui import tagged, tk_root, windows_theme  # noqa: E402,F401  (fixtures by name)
from test_mp3_tool_ui import make_panel as make_mp3_panel  # noqa: E402,F401
from test_m4b_metadata_editor_ui import make_panel as make_editor_panel  # noqa: E402,F401
from test_m4b_metadata_editor_ui import output_base  # noqa: E402,F401
from test_m4b_maker_ui import make_panel as make_maker_panel  # noqa: E402,F401
from test_m4b_preparation import take_the_suites_thread_start_collection  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class Gate:
    """A reader wrapper that parks the worker until released, and records which threads read."""

    def __init__(self, real) -> None:
        self.real = real
        self.open = threading.Event()
        self.threads: set[int] = set()
        self.calls = 0

    def __call__(self, path):
        self.threads.add(threading.get_ident())
        self.calls += 1
        if not self.open.wait(20.0):
            raise AssertionError("the gate was never opened")
        return self.real(path)


def pump_until(panel, predicate, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        panel._pump.tick()
        time.sleep(0.003)


def mp3_library(root: Path, books: int, per_book: int, *, tags: bool = True) -> Path:
    for book in range(1, books + 1):
        folder = root / f"Book {book}"
        folder.mkdir(parents=True)
        for track in range(1, per_book + 1):
            path = folder / f"{track:03d} Part.mp3"
            path.write_bytes(b"not audio")
            if tags:
                tagged(path, title=f"B{book} T{track}", artist="Narrator", album=f"Album {book}")
    return root


def summary(panel) -> tuple[str, ...]:
    return tuple(panel.log.summary)


def snapshot_of(panel) -> list[tuple]:
    """Books, their files and configuration, in order: what an import made."""
    return [(dict(book.configuration), tuple(entry.path for entry in book.files.files))
            for book in panel.workspace.books]


def heartbeat(root, until, *, limit: float = 30.0) -> float:
    """Drive a real Tk loop with a 20 ms ``after`` heartbeat until *until()*; the largest gap seen."""
    gaps, state = [], {"last": time.perf_counter()}

    def beat():
        now = time.perf_counter()
        gaps.append(now - state["last"])
        state["last"] = now
        state["id"] = root.after(20, beat)

    state["id"] = root.after(20, beat)
    deadline = time.monotonic() + limit
    try:
        while not until():
            if time.monotonic() > deadline:
                raise AssertionError("timed out")
            root.update()
            time.sleep(0.001)
    finally:
        root.after_cancel(state["id"])
    return max(gaps) if gaps else 0.0


# --------------------------------------------------------------------------- #
# shared.source_readback
# --------------------------------------------------------------------------- #


def test_each_distinct_path_is_read_once_in_order_and_duplicates_share_the_answer(tmp_path):
    seen = []

    def tags(path):
        seen.append(("tags", path.name))
        return {"title": path.stem}

    def chapters(path):
        seen.append(("chapters", path.name))
        return [path.stem.upper()]

    a, b = tmp_path / "a.m4b", tmp_path / "b.m4b"
    readback = source_readback.SourceReadback("t", (a, b, a, b, a), {"reader": tags, "chapters": chapters})
    assert readback.total == 2 and readback.done == 0 and not readback.finished
    readback.read_sources()
    assert readback.finished and readback.done == 2
    assert seen == [("tags", "a.m4b"), ("chapters", "a.m4b"), ("tags", "b.m4b"), ("chapters", "b.m4b")]
    lookup = readback.reader("reader")
    assert lookup(a) == {"title": "a"} and lookup(str(b)) == {"title": "b"} and lookup(a) is lookup(a)
    assert readback.reader("chapters")(b) == ["B"]
    assert readback.fallbacks == 0 and len(seen) == 4, "answering reads nothing again"
    readback.read_sources()
    assert len(seen) == 4, "a readback reads once"


def test_a_reader_failure_comes_back_as_the_same_exception_and_the_same_observation(tmp_path):
    missing = tmp_path / "missing.m4b"
    broken = tmp_path / "broken.m4b"
    broken.write_bytes(b"not an mp4")
    readback = source_readback.SourceReadback("t", (missing, broken), ewf.source_readers())
    readback.read_sources()
    for path in (missing, broken):
        direct = ewf.observe_source(path, occurrence_id="occ")
        via = ewf.observe_source(path, occurrence_id="occ", **{name: readback.reader(name)
                                                                for name in ewf.source_readers()})
        assert via == direct and not via.readable and via.error, (path, via, direct)
    assert readback.fallbacks == 0


def test_a_cancelled_readback_stops_between_files_and_never_finishes(tmp_path):
    started, release = threading.Event(), threading.Event()
    reads = []

    def slow(path):
        reads.append(path.name)
        started.set()
        release.wait(10.0)
        return mwf.SourceTags()

    paths = [tmp_path / f"{n}.mp3" for n in range(5)]
    readback = source_readback.SourceReadback("t", paths, {"reader": slow})
    worker = threading.Thread(target=readback.read_sources, daemon=True)
    worker.start()
    assert started.wait(10.0)
    readback.cancel()
    release.set()
    worker.join(10.0)
    assert reads == ["0.mp3"], "the file in hand finishes; nothing after it is read"
    assert readback.cancelled and not readback.finished


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")  # the injected fault
def test_a_worker_that_stops_unexpectedly_is_failed_not_finished_and_not_left_running(tmp_path):
    def dies(path):
        raise SystemExit("not an answer: the loop itself ends")

    readback = source_readback.SourceReadback("t", (tmp_path / "a.mp3", tmp_path / "b.mp3"), {"reader": dies})
    worker = threading.Thread(target=readback.read_sources, daemon=True)
    worker.start()
    worker.join(10.0)
    assert readback.failed and not readback.finished and readback.done == 0
    cancelled = source_readback.SourceReadback("t", (tmp_path / "a.mp3",), {"reader": dies})
    cancelled.cancel()
    cancelled.read_sources()
    assert not cancelled.failed and not cancelled.finished, "a cancelled reading is neither"


def test_a_path_never_handed_over_is_read_on_the_callers_thread_and_counted(tmp_path):
    readback = source_readback.SourceReadback("t", (tmp_path / "a.mp3",), {"reader": lambda p: p.name})
    readback.read_sources()
    assert readback.reader("reader")(tmp_path / "other.mp3") == "other.mp3"
    assert readback.fallbacks == 1


def test_the_readback_module_imports_no_tk_and_writes_nothing():
    tree = ast.parse((SCRIPTS / "shared" / "source_readback.py").read_text(encoding="utf-8"))
    modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    modules |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(name.split(".")[0] in {"tkinter", "subprocess", "shutil"} for name in modules), modules
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for write in ("write_bytes", "write_text", "open", "unlink", "rename", "replace", "mkdir", "rmtree", "save"):
        assert write not in called, write


# --------------------------------------------------------------------------- #
# The MP3 Tool
# --------------------------------------------------------------------------- #


def test_mp3_tags_are_read_off_tk_and_the_import_is_made_only_when_they_are_read(make_mp3_panel, tmp_path):
    lib = mp3_library(tmp_path / "lib", 2, 3)
    expected_panel = make_mp3_panel()  # the synchronous reference: inline threads read during the import call
    expected_panel._choose_folder = lambda: (str(lib),)
    expected_panel.import_folder()
    expected_panel._pump.tick()
    assert not expected_panel.is_reading_tags and len(expected_panel.workspace.books) == 2

    gate = Gate(mwf.read_source_tags)
    panel = make_mp3_panel(thread_factory=RealThreads(), reader=gate)
    before = snapshot_of(panel)
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    pump_until(panel, lambda: panel.is_reading_tags and gate.calls >= 1)
    # Still importing: nothing in the workspace, a progress line with Cancel, and nothing else may start or reset.
    assert snapshot_of(panel) == before
    assert panel.import_status.text.startswith("Reading tags…") and panel.import_status.cancel_enabled
    assert panel.write_id3_tags() is False and panel.clear_all_imports() is False
    panel.import_folder()
    panel._choose_files = lambda: (str(lib / "Book 1" / "001 Part.mp3"),)
    panel.add_files()
    assert panel.is_reading_tags and snapshot_of(panel) == before
    gate.open.set()
    pump_until(panel, lambda: not panel.is_reading_tags)
    assert threading.main_thread().ident not in gate.threads, "no tag was read on the Tk thread"
    assert snapshot_of(panel) == snapshot_of(expected_panel)
    assert [mwf.summarise(panel.store.for_book(book)) for book in panel.workspace.books] == \
        [mwf.summarise(expected_panel.store.for_book(book)) for book in expected_panel.workspace.books]
    assert summary(panel)[-1] == "Import Folder: 6 MP3 file(s) in 2 Book(s)."
    assert not panel.import_status.cancel_enabled


def test_mp3_cancel_import_while_reading_adds_nothing_and_the_late_result_is_ignored(make_mp3_panel, tmp_path):
    lib = mp3_library(tmp_path / "lib", 2, 3)
    gate = Gate(mwf.read_source_tags)
    panel = make_mp3_panel(thread_factory=RealThreads(), reader=gate)
    before = snapshot_of(panel)
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    pump_until(panel, lambda: panel.is_reading_tags and gate.calls >= 1)
    assert panel.cancel_import() is True
    assert not panel.is_reading_tags and not panel.import_status.cancel_enabled
    assert panel.import_status.text == "The import was cancelled and nothing was added."
    assert summary(panel)[-1] == "Import Folder: The import was cancelled and nothing was added."
    gate.open.set()
    for thread in panel._thread_factory.made:
        thread.join(10.0)
    for _ in range(5):
        panel._pump.tick()
    assert snapshot_of(panel) == before, "the reading that finished after Cancel changed nothing"
    # And the tool is free again.
    panel.import_folder()
    pump_until(panel, lambda: not panel.is_reading_tags and len(panel.workspace.books) == 2)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")  # the injected fault
def test_mp3_a_reading_that_fails_adds_nothing_and_frees_the_tool(make_mp3_panel, tmp_path):
    lib = mp3_library(tmp_path / "lib", 1, 2)

    def dies(path):
        raise SystemExit("the worker ends without an answer")

    panel = make_mp3_panel(thread_factory=RealThreads(), reader=dies)
    before = snapshot_of(panel)
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    pump_until(panel, lambda: not panel._import_busy)
    assert snapshot_of(panel) == before
    assert summary(panel)[-1] == "Import Folder: The files could not be read, so nothing was added."
    assert panel.import_status.text == "The files could not be read, so nothing was added."
    assert not panel.is_reading_tags and not panel.import_status.cancel_enabled, "the tool is free again"


def test_mp3_close_while_reading_never_adopts(make_mp3_panel, tmp_path):
    lib = mp3_library(tmp_path / "lib", 1, 2)
    gate = Gate(mwf.read_source_tags)
    panel = make_mp3_panel(thread_factory=RealThreads(), reader=gate)
    before = snapshot_of(panel)
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    pump_until(panel, lambda: panel.is_reading_tags and gate.calls >= 1)
    pending = panel._pending_import
    panel.close()
    assert pending.readback.cancelled and panel._pending_import is None
    gate.open.set()
    for thread in panel._thread_factory.made:
        thread.join(10.0)
    panel._drain_readback()
    assert snapshot_of(panel) == before


def test_mp3_add_files_lands_in_the_book_it_was_pressed_on(make_mp3_panel, tmp_path):
    lib = mp3_library(tmp_path / "lib", 2, 2)
    extra = mp3_library(tmp_path / "extra", 1, 3)
    gate = Gate(mwf.read_source_tags)
    gate.open.set()
    panel = make_mp3_panel(thread_factory=RealThreads(), reader=gate)
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    pump_until(panel, lambda: not panel.is_reading_tags and len(panel.workspace.books) == 2)
    first, second = (book.book_id for book in panel.workspace.books)
    assert panel.workspace.current_book_id == first
    gate.open.clear()
    panel._choose_files = lambda: tuple(str(p) for p in sorted((extra / "Book 1").glob("*.mp3")))
    panel.add_files()
    pump_until(panel, lambda: panel.is_reading_tags and gate.calls >= 5)
    # While the tags are read the user moves on and pastes Chapter Titles into the other Book (no key release).
    panel.on_next()
    assert panel.workspace.current_book_id == second
    panel.chapter_text.delete("1.0", "end")
    panel.chapter_text.insert("1.0", "Pasted One\nPasted Two")
    gate.open.set()
    pump_until(panel, lambda: not panel.is_reading_tags)
    space = panel.workspace
    assert space.current_book_id == second, "the page the user is on stays"
    books = {book.book_id: book for book in space.books}
    assert len(books[first].files.files) == 5 and len(books[second].files.files) == 2
    assert [entry.name for entry in books[first].files.files][2:] == ["001 Part.mp3", "002 Part.mp3",
                                                                       "003 Part.mp3"]
    assert books[second].configuration.get("chapter_titles") == "Pasted One\nPasted Two"
    assert panel.chapter_titles_text() == "Pasted One\nPasted Two"
    assert summary(panel)[-1] == "Add Files: 3 MP3 file(s) added to Book 1 of 2."


def test_mp3_add_files_for_a_book_removed_meanwhile_adds_nothing(make_mp3_panel, tmp_path):
    lib = mp3_library(tmp_path / "lib", 2, 1)
    extra = mp3_library(tmp_path / "extra", 1, 2)
    gate = Gate(mwf.read_source_tags)
    gate.open.set()
    panel = make_mp3_panel(thread_factory=RealThreads(), reader=gate)
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    pump_until(panel, lambda: not panel.is_reading_tags and len(panel.workspace.books) == 2)
    gate.open.clear()
    panel._choose_files = lambda: tuple(str(p) for p in sorted((extra / "Book 1").glob("*.mp3")))
    panel.add_files()
    pump_until(panel, lambda: panel.is_reading_tags and gate.calls >= 3)
    panel.on_remove(True)  # confirm answers Yes
    remaining = snapshot_of(panel)
    gate.open.set()
    pump_until(panel, lambda: not panel.is_reading_tags)
    assert snapshot_of(panel) == remaining
    assert "nothing was added" in summary(panel)[-1]


def test_a_slow_mp3_import_keeps_the_tk_heartbeat(make_mp3_panel, tmp_path, tk_root):
    lib = mp3_library(tmp_path / "lib", 1, 300, tags=False)

    def slow(path):
        time.sleep(0.003)  # 300 files: about a second of reading, which v0.8.1 did inside one Tk callback
        return mwf.SourceTags()

    panel = make_mp3_panel(thread_factory=RealThreads(), reader=slow)
    panel.pack()
    tk_root.update()
    take_the_suites_thread_start_collection()
    panel._choose_folder = lambda: (str(lib),)
    panel._pump.start()
    started = time.perf_counter()
    panel.import_folder()
    gap = heartbeat(tk_root, lambda: not panel._import_busy and len(panel.workspace.current.files.files) == 300)
    assert time.perf_counter() - started >= 0.8, "the reading really took about a second"
    assert gap < 0.25, f"largest heartbeat gap {gap:.3f} s"


# --------------------------------------------------------------------------- #
# The Metadata Editor
# --------------------------------------------------------------------------- #


def editor_library(container, root: Path) -> Path:
    m4b(container, root / "Alpha.m4b", title="Alpha", artist="Ann", series="Saga", series_part="1")
    m4b(container, root / "Beta.m4b", title="Beta", artist="Ann", series="Saga", series_part="2")
    (root / "Broken.m4b").write_bytes(b"not an mp4")
    return root


def gated_readers(monkeypatch, gate_open: threading.Event):
    real = ewf.source_readers()
    threads: set[int] = set()

    def wrap(reader):
        def gated(path):
            threads.add(threading.get_ident())
            if not gate_open.wait(20.0):
                raise AssertionError("never opened")
            return reader(path)
        return gated

    readers = {name: wrap(reader) for name, reader in real.items()}
    monkeypatch.setattr(editor.wf, "source_readers", lambda: readers)
    return threads


def test_editor_sources_are_read_off_tk_and_observed_exactly_as_before(make_editor_panel, container, tmp_path,
                                                                       monkeypatch):
    lib = editor_library(container, tmp_path / "lib")
    gate_open = threading.Event()
    threads = gated_readers(monkeypatch, gate_open)
    panel = make_editor_panel(thread_factory=RealThreads())
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    pump_until(panel, lambda: panel.is_reading_sources)
    assert len(panel.workspace.books) == 1 and panel.workspace.books[0].files.is_empty, "no Book before reading"
    assert panel.import_status.text.startswith("Reading tags and chapters…") and panel.import_status.cancel_enabled
    assert panel.save() is False and panel.clear_all_imports() is False
    gate_open.set()
    pump_until(panel, lambda: not panel.is_reading_sources)
    assert threading.main_thread().ident not in threads and threads
    books = panel.workspace.books
    assert [book.files.files[0].path.name for book in books] == ["Alpha.m4b", "Beta.m4b", "Broken.m4b"]
    for book in books:
        source = book.files.files[0]
        direct = ewf.observe_source(source.path, occurrence_id=source.occurrence_id)
        assert panel.store.for_book(book) == direct, source.path.name
    observed = [panel.store.for_book(book) for book in books]
    assert [seen.readable for seen in observed] == [True, True, False]
    assert observed[0].chapter_titles and observed[0].title == "Alpha"
    assert summary(panel)[-1] == "Import Folder: 3 file(s) → 3 Book(s). 1 could not be read and will be skipped."


def test_editor_cancel_import_while_reading_adds_nothing(make_editor_panel, container, tmp_path, monkeypatch):
    lib = editor_library(container, tmp_path / "lib")
    gate_open = threading.Event()
    gated_readers(monkeypatch, gate_open)
    panel = make_editor_panel(thread_factory=RealThreads())
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    pump_until(panel, lambda: panel.is_reading_sources)
    assert panel.cancel_import() is True and not panel.is_reading_sources
    assert summary(panel)[-1] == "Import Folder: The import was cancelled and nothing was added."
    gate_open.set()
    for thread in panel._thread_factory.made:
        thread.join(10.0)
    for _ in range(5):
        panel._pump.tick()
    assert len(panel.workspace.books) == 1 and panel.workspace.books[0].files.is_empty
    assert not panel.store.entries


def test_editor_add_files_appends_only_after_reading_and_skips_what_it_already_holds(make_editor_panel, container,
                                                                                    tmp_path, monkeypatch):
    lib = editor_library(container, tmp_path / "lib")
    panel = make_editor_panel()  # inline threads: the reading finishes inside the import call
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    panel._pump.tick()
    assert len(panel.workspace.books) == 3
    gate_open = threading.Event()
    gated_readers(monkeypatch, gate_open)
    panel._thread_factory = RealThreads()
    extra = m4b(container, tmp_path / "more" / "Gamma.m4b", title="Gamma")
    panel._choose_files = lambda: (str(lib / "Alpha.m4b"), str(extra))
    panel.add_files()
    pump_until(panel, lambda: panel.is_reading_sources)
    assert len(panel.workspace.books) == 3
    # Books exist, but the import is not finished: no action may start, nothing may be reset or imported.
    assert panel.save() is False and not panel.is_preparing and not panel.is_running
    assert panel.on_clear_all_tags() is False and not panel.is_preparing
    assert panel.clear_all_imports() is False and len(panel.workspace.books) == 3
    gate_open.set()
    pump_until(panel, lambda: not panel.is_reading_sources)
    assert [book.files.files[0].path.name for book in panel.workspace.books][-1] == "Gamma.m4b"
    assert len(panel.workspace.books) == 4
    assert panel.store.for_book(panel.workspace.books[-1]).title == "Gamma"


def test_a_slow_editor_import_keeps_the_tk_heartbeat(make_editor_panel, tmp_path, tk_root, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    for index in range(250):
        (lib / f"Book {index:03d}.m4b").write_bytes(b"placeholder")

    def tags(path):
        time.sleep(0.004)  # 250 files: about a second, which v0.8.1 spent inside one Tk callback
        return {"title": path.stem, "has_cover": False}

    monkeypatch.setattr(editor.wf, "source_readers", lambda: {"reader": tags, "chapters": lambda p: ["One"]})
    panel = make_editor_panel(thread_factory=RealThreads())
    panel.pack()
    tk_root.update()
    take_the_suites_thread_start_collection()
    panel._choose_folder = lambda: (str(lib),)
    panel._pump.start()
    panel.import_folder()
    gap = heartbeat(tk_root, lambda: not panel._import_busy and len(panel.workspace.books) == 250)
    assert gap < 0.25, f"largest heartbeat gap {gap:.3f} s"
    assert panel.store.for_book(panel.workspace.books[7]).title == "Book 007"


# --------------------------------------------------------------------------- #
# Track lists: a render that changes no track leaves the list alone
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tool", ["mp3", "maker"])
def test_a_shared_edit_keeps_the_track_list_and_its_selection_and_navigation_refills_it(
        tool, make_mp3_panel, make_maker_panel, tmp_path, monkeypatch):
    lib = mp3_library(tmp_path / "lib", 2, 4, tags=False)
    panel = make_mp3_panel(reader=lambda p: mwf.SourceTags()) if tool == "mp3" else make_maker_panel()
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    panel._pump.tick()
    assert len(panel.workspace.books) == 2
    fills = []
    real_insert = panel.track_list.insert
    monkeypatch.setattr(panel.track_list, "insert", lambda *a: (fills.append(len(a) - 1), real_insert(*a))[1])
    panel.select_tracks(1, 2)
    panel.surface.set_shared_text("artist", "Someone")  # a Shared keystroke re-renders the page
    assert fills == [], "no track changed, so the list was not refilled"
    assert tuple(int(i) for i in panel.track_list.curselection()) == (1, 2), "the selection survives"
    panel.on_next()
    assert fills == [4] and panel.track_list.get(0) == "001 Part.mp3"
    assert panel.track_list.curselection() == ()
    panel.select_tracks(0)
    panel.move_down()  # a move always redraws, with the moved track still selected
    assert fills == [4, 4] and tuple(int(i) for i in panel.track_list.curselection()) == (1,)
    assert panel.track_list.get(1) == "001 Part.mp3"


# --------------------------------------------------------------------------- #
# Navigation at many Books
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("panel_class", [mp3_tool.MP3ToolUI, m4b_maker.M4BMakerUI, editor.M4BMetadataEditorUI],
                         ids=["mp3", "maker", "editor"])
def test_book_numbering_is_linear_and_keeps_retired_numbers_retired(panel_class):
    books = [SimpleNamespace(book_id=f"b{n}") for n in range(20_000)]
    owner = SimpleNamespace(workspace=SimpleNamespace(books=books), book_numbers={})
    started = time.perf_counter()
    panel_class._assign_book_numbers(owner)
    elapsed = time.perf_counter() - started
    assert owner.book_numbers["b0"] == 1 and owner.book_numbers["b19999"] == 20_000
    assert elapsed < 0.5, f"{elapsed:.3f} s for 20,000 Books (a list scan made this quadratic: seconds)"
    owner.workspace.books = books[1:] + [SimpleNamespace(book_id="new")]
    panel_class._assign_book_numbers(owner)
    assert "b0" not in owner.book_numbers and owner.book_numbers["new"] == 20_001


def _old_page_values(shared, book, store) -> dict:
    """v0.8.1's page_values, restated from Plan 6's effective_metadata (independent of the code under test)."""
    from shared.book_workspace import effective_metadata

    prefill = ewf.prefill_values(store.for_book(book))
    effective = effective_metadata(shared, book)
    return {name: (str(effective.get(name, ewf.BLANK)) if shared.populated(name) or name in book.configuration
                   else prefill[name]) for name in ewf.TEXT_FIELDS}


def _old_hint(shared, book, store) -> str:
    """The v0.8.1 rule, written out: the page Title, else the source file name."""
    title = " ".join(_old_page_values(shared, book, store)["title"].split())
    if title:
        return title
    source = ewf.source_of(book)
    return source.path.name if source is not None else ""


def test_the_editor_selector_hint_is_still_the_page_title_rule(make_editor_panel, container, tmp_path):
    lib = editor_library(container, tmp_path / "lib")
    panel = make_editor_panel()
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    panel._pump.tick()
    space, store = panel.workspace, panel.store
    alpha, beta, broken = space.books
    variants = []
    for shared_title in ("", "  Shared  Title "):
        shared = set_shared_metadata(space, SharedMetadata(
            ewf.SHARED_FIELDS, {**space.shared.values, "title": shared_title})).workspace.shared
        for book in (alpha, beta, broken):
            for configured in (None, "", "  Edited   Title"):
                edited = book if configured is None else ewf.set_book_field(
                    space, "title", configured, book_id=book.book_id).workspace.books[space.books.index(book)]
                variants.append((shared, edited))
    for shared, book in variants:
        assert ewf.display_hint(shared, book, store) == _old_hint(shared, book, store), (shared.values, book)
        assert dict(ewf.page_values(shared, book, store)) == _old_page_values(shared, book, store)
    assert ewf.display_hint(space.shared, broken, store) == "Broken.m4b"
    with pytest.raises(ewf.SharedMetadataError):
        ewf.display_hint(object(), alpha, store)  # the same contract error page_values gave
    with pytest.raises(ewf.SharedMetadataError):
        ewf.page_values(object(), alpha, store)


def test_labelling_the_editor_selector_builds_no_whole_page_per_book(make_editor_panel, container, tmp_path,
                                                                    monkeypatch):
    lib = editor_library(container, tmp_path / "lib")
    panel = make_editor_panel()
    panel._choose_folder = lambda: (str(lib),)
    panel.import_folder()
    panel._pump.tick()
    calls = {"page_values": 0}
    real = ewf.page_values

    def counted(*args, **kwargs):
        calls["page_values"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(ewf, "page_values", counted)
    panel.on_next()
    assert calls["page_values"] == 1, "one page is shown; the selector's labels read the title alone"


def test_mp3_folder_import_seeds_every_book_in_one_snapshot_equal_to_the_per_book_loop(monkeypatch):
    """Many one-file folders: the seeded workspace is the old replace-per-Book value, revision included."""
    from shared.book_workspace import replace_book, replace_workspace_from_import
    from shared.importing import IdFactory
    from test_mp3_workflow import snapshot, track

    def reader(path):
        index = int(path.stem)
        if index % 3 == 0:
            return mwf.SourceTags()  # nothing to seed: the Book keeps its own object and moves no revision
        return mwf.SourceTags(title=path.stem, artist=f"Author {index % 7}", album=path.parent.name)

    imported = snapshot(*(track(f"{index:04d}.mp3", folder=f"Book {index:04d}") for index in range(600)))
    start = mwf.new_workspace(id_factory=IdFactory("same-"))
    # The v0.8.2 Checkpoint 5 projection, step by step through the shared operations.
    expected = replace_workspace_from_import(start, imported, id_factory=IdFactory("same-")).workspace
    expected_store = mwf.ObservationStore().with_observations(mwf.observe_files(imported.files, reader=reader))
    for book in expected.books:
        seeded = mwf._prepopulated(book, mwf.summarise(expected_store.for_book(book)))
        if seeded is not book:
            expected = replace_book(expected, seeded).workspace
    calls = {"replace_book": 0, "snapshots": 0}
    real_snapshot = mwf.WorkspaceSnapshot

    def no_replace(*args, **kwargs):
        calls["replace_book"] += 1
        return replace_book(*args, **kwargs)

    def counted_snapshot(*args, **kwargs):
        calls["snapshots"] += 1
        return real_snapshot(*args, **kwargs)

    monkeypatch.setattr(mwf, "replace_book", no_replace)
    monkeypatch.setattr(mwf, "WorkspaceSnapshot", counted_snapshot)
    result = mwf.import_folder(start, imported, id_factory=IdFactory("same-"), store=mwf.ObservationStore(),
                               reader=reader)
    got = result.mutation.workspace
    assert got == expected and got.revision == expected.revision
    assert got.revision.value - start.revision.value == 1 + 400, \
        "the import, then one step per seeded Book; the 200 Books with nothing to seed move none"
    assert result.store == expected_store
    assert calls == {"replace_book": 0, "snapshots": 1}, calls


def test_editor_add_files_drops_only_the_pristine_book_and_compares_no_books(tmp_path, monkeypatch):
    """Adding beside thousands of Books is linear; the pristine startup Book is replaced, a typed-on one is kept."""
    from test_m4b_metadata_workflow import _BOOKS, imported, snapshot

    def tags(path):
        return {"title": path.stem, "has_cover": False}

    def no_chapters(path):
        return []

    sources = tmp_path / "src"
    pristine = ewf.new_workspace(id_factory=_BOOKS)
    first = ewf.add_files(pristine, (imported(sources, "a.m4b"),), store=ewf.ObservationStore(),
                          reader=tags, chapters=no_chapters)
    assert first.mutation.removed == pristine.books, "the pristine startup Book gives way to the first source"
    assert [ewf.source_of(book).path.name for book in first.mutation.workspace.books] == ["a.m4b"]
    typed = ewf.set_book_field(ewf.new_workspace(id_factory=_BOOKS), "title", "Typed").workspace
    kept = ewf.add_files(typed, (imported(sources, "b.m4b"),), store=ewf.ObservationStore(),
                         reader=tags, chapters=no_chapters)
    assert kept.mutation.removed == () and kept.mutation.workspace.books[0] == typed.books[0], \
        "a Book the user typed on stays, even without a source"
    many = ewf.import_folder(pristine, snapshot(*(imported(sources, f"{i:05d}.m4b") for i in range(3_000))),
                             id_factory=_BOOKS, store=ewf.ObservationStore(), reader=tags, chapters=no_chapters)
    book_type = type(many.mutation.workspace.books[0])
    compared = {"count": 0}
    real_eq = book_type.__eq__

    def counted_eq(self, other):
        compared["count"] += 1
        return real_eq(self, other)

    monkeypatch.setattr(book_type, "__eq__", counted_eq)
    added = ewf.add_files(many.mutation.workspace, (imported(sources, "late.m4b"),), store=many.store,
                          reader=tags, chapters=no_chapters)
    assert added.mutation.workspace.count == 3_001 and added.mutation.removed == ()
    assert compared["count"] == 0, f"{compared['count']} Book comparisons (about 4.5 million before)"


# --------------------------------------------------------------------------- #
# The shared imported-file list
# --------------------------------------------------------------------------- #


def test_select_all_and_moving_a_large_selection_are_linear(tk_root, tmp_path):
    paths = []
    for index in range(6_000):
        path = tmp_path / f"{index:05d}.mp3"
        path.write_bytes(b"")
        paths.append(path)
    manager = ImportedFileManager()
    tju.fill(manager, *paths)
    frame = tk.Frame(tk_root)
    listing = job_ui.ImportedFileList(frame, manager)
    try:
        started = time.perf_counter()
        selected = listing.select_all()
        elapsed = time.perf_counter() - started
        assert len(selected) == 6_000 and listing.selected_count == 6_000
        assert elapsed < 0.3, f"Select All took {elapsed:.3f} s at 6,000 rows (quadratic: about a second)"
        odd_rows = listing.order[1::2]
        listing.select(odd_rows)
        assert listing.selection == odd_rows
        assert tuple(int(i) for i in listing.listbox.curselection()) == tuple(range(1, 6_000, 2))
        started = time.perf_counter()
        listing.move_up()  # the 3,000 selected rows travel as one block across the row above them
        elapsed = time.perf_counter() - started
        assert elapsed < 0.3, f"moving 3,000 rows took {elapsed:.3f} s"
        assert listing.selection == odd_rows, "the moved rows stay selected"
        assert tuple(int(i) for i in listing.listbox.curselection()) == tuple(range(3_000))
        rows = listing.rows()
        assert rows[0] == "1. 00001.mp3" and rows[1] == "2. 00003.mp3" and rows[3_000] == "3001. 00000.mp3"
        assert listing.button_states()["move_up"] is False and listing.button_states()["move_down"] is True
    finally:
        listing.close()
        frame.destroy()
