"""M4B Maker panel branches that had no automated check — v0.7.2 Phase 6, ACT72-052 and ACT72-032.

Folder import's "Replace the current Books?" question, Cancel Import during a folder scan, the Maker's own wording of the
broad-folder and large-result questions, the remembered input folder, the duplicate-file skip, the progress statuses and
status line, Clear Log and the per-attempt divider, and a cancelled custom build that must leave the chosen folder as it was.

Every test drives the real panel through its own methods and seams; the message boxes and file dialogs are the seams the
panel takes, so what is proved is the panel's decision and wording, not a native dialog (the native dialogs are the
journeys'). Builds run real tones through the real engine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import settings as app_settings  # noqa: E402
from shared.job_control import JobState  # noqa: E402

from m4b.maker import m4b_maker  # noqa: E402
from m4b.maker import m4b_maker_processing as proc  # noqa: E402

from test_import_coordination import RecordingThreads  # noqa: E402
import test_import_coordination as tic  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_maker_ui import (  # noqa: E402,F401  (fixtures are collected by name)
    add_files,
    import_folder,
    make_panel,
    output_base,
    tk_root,
    tone,
    tracks,
    windows_theme,
)
from test_maker_staging_release import custom_panel, entries_of_kind, tree  # noqa: E402
from test_tts_work_area import temp  # noqa: E402,F401


def parked_threads():
    """A scan thread that is made but never started, so a test can act while the scan is still active."""

    class Parked(tic.InlineThread):
        def start(self):
            pass

    return RecordingThreads(kind=Parked)


def settle(panel, rounds: int = 20) -> None:
    for _ in range(rounds):
        panel._pump.tick()
        if not panel._coordinator.is_active:
            return


def book_ids(panel) -> list[str]:
    return [book.book_id for book in panel.workspace.books]


@pytest.fixture
def isolated_settings(tmp_path):
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    try:
        yield
    finally:
        app_settings.use_path(None)


# --------------------------------------------------------------------------- import (ACT.MAKER.IMPORT-FOLDER)


def test_import_folder_asks_before_replacing_books_that_hold_work_and_no_keeps_them(make_panel, tmp_path):
    asked: list[tuple[str, str]] = []
    answer = {"value": False}
    panel = make_panel(confirm=lambda title, message: asked.append((title, message)) or answer["value"])
    first = tmp_path / "First"
    tracks(first / "A", "01.mp3")
    tracks(first / "B", "01.mp3")
    import_folder(panel, first)
    assert asked == [], "a pristine workspace is replaced without a question"
    before = book_ids(panel)
    second = tmp_path / "Second"
    tracks(second / "C", "01.mp3")
    chosen: list[int] = []
    panel._choose_folder = lambda: chosen.append(1) or (str(second),)
    panel.import_folder()
    settle(panel)
    assert [title for title, _ in asked] == ["Replace the current Books?"]
    assert "replaces every Book" in asked[0][1]
    assert chosen == [], "No asks before the folder dialog, and nothing is scanned"
    assert book_ids(panel) == before
    answer["value"] = True
    panel.import_folder()
    settle(panel)
    assert len(asked) == 2 and chosen == [1]
    assert [book.file_count for book in panel.workspace.books] == [1]
    assert book_ids(panel) != before


def test_cancel_import_ends_a_maker_folder_scan_and_the_workspace_is_as_it_was(make_panel, tmp_path):
    root = tmp_path / "Library"
    tracks(root / "A", "01.mp3")
    tracks(root / "B", "01.mp3")
    panel = make_panel(thread_factory=parked_threads())
    before = book_ids(panel)
    panel._choose_folder = lambda: (str(root),)
    panel.import_folder()
    assert panel._coordinator.is_active and len(panel._thread_factory.bodies) == 1, "the scan is started and parked"
    assert panel.cancel_import() is True
    panel._thread_factory.bodies[0]()
    settle(panel)
    assert not panel._coordinator.is_active
    assert book_ids(panel) == before and panel.workspace.current.is_empty
    assert any("Import Folder:" in line for line in panel.log.summary), panel.log.summary


def test_the_maker_asks_in_its_own_words_before_a_broad_folder_or_a_large_result(make_panel, tmp_path):
    """Both questions go through the panel's own wording (no stub in front of it), answered through its confirm seam;
    declining either leaves the workspace untouched."""
    home = tmp_path / "Home"
    tracks(home / "A", "01.mp3")
    asked: list[tuple[str, str]] = []
    panel = make_panel(home=home, confirm_broad_root=None, thread_factory=parked_threads(),
                       confirm=lambda title, message: asked.append((title, message)) or False)
    before = book_ids(panel)
    panel._choose_folder = lambda: (str(home),)
    panel.import_folder()
    assert [title for title, _ in asked] == ["Scan a very broad folder?"]
    assert str(home) in asked[0][1] and "can take a long time" in asked[0][1]
    assert panel._thread_factory.bodies == [] and not panel._coordinator.is_active, "declined before any scan starts"
    assert book_ids(panel) == before

    library = tmp_path / "Library"
    tracks(library / "A", "01.mp3", "02.mp3")
    asked.clear()
    panel = make_panel(effective_config=make_config(threshold=1), confirm_large_result=None,
                       confirm=lambda title, message: asked.append((title, message)) or False)
    before = book_ids(panel)
    panel._choose_folder = lambda: (str(library),)
    panel.import_folder()
    settle(panel)
    assert [title for title, _ in asked] == ["Import a large number of MP3s?"]
    assert asked[0][1].startswith("2 MP3 files are ready to be imported."), asked[0][1]
    assert not panel._coordinator.is_active and book_ids(panel) == before and panel.workspace.current.is_empty


def test_the_input_folder_is_remembered_and_a_vanished_one_falls_back_to_home(
        make_panel, tmp_path, monkeypatch, isolated_settings):
    library = tmp_path / "Library"
    tracks(library / "A", "01.mp3", "02.mp3")
    opened: list[tuple[str, str]] = []

    def askdirectory(**kwargs):
        opened.append(("folder", kwargs["initialdir"]))
        return str(library)

    def askopenfilenames(**kwargs):
        opened.append(("files", kwargs["initialdir"]))
        return (str(library / "A" / "01.mp3"),)

    monkeypatch.setattr(m4b_maker.filedialog, "askdirectory", askdirectory)
    monkeypatch.setattr(m4b_maker.filedialog, "askopenfilenames", askopenfilenames)
    monkeypatch.setattr(m4b_maker.Path, "home", classmethod(lambda cls: tmp_path / "TheHome"))
    panel = make_panel(choose_folder=None, choose_files=None)
    panel.import_folder()
    settle(panel)
    assert opened == [("folder", str(tmp_path / "TheHome"))], "nothing remembered yet: the home folder"
    assert app_settings.get(m4b_maker.KEY_INPUT_DIR) == str(library)
    panel.on_add()
    panel.add_files()
    settle(panel)
    assert opened[-1] == ("files", str(library)), "the next dialog opens where the last one chose"
    assert app_settings.get(m4b_maker.KEY_INPUT_DIR) == str(library / "A"), "Add Files remembers the files' folder"
    (library / "A" / "01.mp3").unlink()
    (library / "A" / "02.mp3").unlink()
    (library / "A").rmdir()
    panel.on_add()
    panel.add_files()
    assert opened[-1] == ("files", str(tmp_path / "TheHome")), "a folder that is gone falls back to home"


# --------------------------------------------------------------------------- add files (ACT.MAKER.ADD-FILES)


def test_a_file_already_in_the_book_is_skipped_and_the_log_says_how_many(make_panel, tmp_path):
    one, two, three = tracks(tmp_path / "Loose", "01.mp3", "02.mp3", "03.mp3")
    panel = make_panel()
    add_files(panel, one, two)
    settle(panel)
    assert [entry.name for entry in panel.workspace.current.files.files] == ["01.mp3", "02.mp3"]
    add_files(panel, two, three, one)
    settle(panel)
    assert [entry.name for entry in panel.workspace.current.files.files] == ["01.mp3", "02.mp3", "03.mp3"]
    last = panel.log.summary[-1]
    assert last.startswith("Add Files: 1 MP3 file(s) added to") and last.endswith("2 already in this Book were skipped."), last
    add_files(panel, three)
    settle(panel)
    assert panel.log.summary[-1].endswith("1 already in this Book were skipped."), panel.log.summary[-1]
    assert len(panel.workspace.current.files.files) == 3


# --------------------------------------------------------------------------- progress (ACT.MAKER.PROGRESS)


def test_statuses_and_the_status_line_follow_the_run_and_the_summary_counts_it(make_panel, tmp_path, monkeypatch,
                                                                                output_base):
    root = tmp_path / "Library"
    for folder in ("A", "B", "C"):
        tone(root / folder / "01.mp3")
    panel = make_panel()
    import_folder(panel, root)
    a, b, c = panel.workspace.books
    panel.on_select(c.book_id)
    panel.on_add()                                   # a fourth Book with nothing in it: Skipped, never built
    empty = next(book for book in panel.workspace.books if book.book_id not in {a.book_id, b.book_id, c.book_id})
    seen: dict[str, tuple] = {}
    real = proc.stage_book

    def stage(book, **kwargs):
        panel._pump.tick()                          # the main thread's view of the run as this Book begins
        seen[book.filename] = (tuple(panel.book_status_for(item.book_id) for item in (a, b, c, empty)),
                               panel.status.stage_text)
        return real(book, **kwargs)

    monkeypatch.setattr(proc, "stage_book", stage)
    panel.on_select(b.book_id)
    assert panel.build() is True
    Q, P, C, S = (m4b_maker.STATUS_QUEUED, m4b_maker.STATUS_PROCESSING, m4b_maker.STATUS_COMPLETED,
                  m4b_maker.STATUS_SKIPPED)
    assert seen["A.m4b"][0] == (P, Q, Q, S), seen
    assert seen["B.m4b"][0] == (C, P, Q, S), seen
    assert seen["C.m4b"][0] == (C, C, P, S), seen
    assert "B.m4b (2 of 3)" in seen["B.m4b"][1], seen["B.m4b"][1]
    assert "C.m4b (3 of 3)" in seen["C.m4b"][1], seen["C.m4b"][1]
    panel._pump.tick()
    assert panel.last_result.state is JobState.SUCCEEDED
    assert [panel.book_status_for(item.book_id) for item in (a, b, c, empty)] == [C, C, C, S]
    assert panel.status_label.cget("text") == C, "the panel's own status shows the current Book's"
    summary = panel.log.summary
    assert f"Build: 3 Book(s) completed, 0 failed, 1 skipped, 0 not attempted → {panel.last_plan.root}" in summary, summary


# --------------------------------------------------------------------------- activity log (ACT.MAKER.ACTIVITY-LOG)


def test_each_attempt_starts_under_its_own_divider_and_clear_log_clears_only_the_view(make_panel, tmp_path,
                                                                                      monkeypatch, output_base):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    tone(root / "B" / "01.mp3")
    panel = make_panel()
    import_folder(panel, root)
    refuse = {"B.m4b"}
    real = proc.publish_book

    def publish(entry, *, work_root):
        if entry.filename in refuse:
            raise proc.ProcessingError("the destination refused it", stage="publish", detail="test")
        return real(entry, work_root=work_root)

    monkeypatch.setattr(proc, "publish_book", publish)
    assert panel.build() is True
    panel._pump.tick()
    run_folder = panel.last_plan.root
    summary = list(panel.log.summary)
    heading = f"{m4b_maker.DIVIDER_MARK} Build M4B(s) — {run_folder.name}"
    assert heading in summary and summary.index(heading) < summary.index(next(l for l in summary if l.startswith("Build: 1"))), summary
    refuse.clear()
    assert panel.retry_failed() is True
    panel._pump.tick()
    summary = list(panel.log.summary)
    retry = f"{m4b_maker.DIVIDER_MARK} Retry Failed — attempt 2"
    assert retry in summary and summary.index(heading) < summary.index(retry), summary
    assert summary[-1].startswith("Build: 2 Book(s) completed"), "the retry's lines sit under its own divider"
    result = panel.last_result
    panel.clear_log()
    assert panel.log.summary == () and panel.log.details == ()
    assert panel.log.summary_text.get("1.0", "end-1c") == "" and panel.log.details_text.get("1.0", "end-1c") == ""
    assert panel.last_result is result and (run_folder / "A.m4b").is_file() and (run_folder / "B.m4b").is_file(), \
        "the view forgets; the run and its outputs do not"
    panel._pump.tick()
    assert panel.log.summary == (), "a re-render of the same run puts nothing back"


# --------------------------------------------------------------------------- a cancelled custom build (ACT72-032)


def test_a_cancelled_custom_build_leaves_the_chosen_folder_and_everything_already_in_it(
        make_panel, tmp_path, temp, monkeypatch, output_base):
    """test_cancellation_never_removes_the_chosen_directory looked in the panel's source for an except clause that had
    moved to the engine, so it asserted nothing (ACT72-032). Here Cancel is pressed in a real custom build while its
    second Book is being made, in a folder that already holds the owner's files, one of them named like a planned output."""
    chosen = tmp_path / "Chosen"
    (chosen / "Kept").mkdir(parents=True)
    (chosen / "Notes.txt").write_bytes(b"the owner's own notes")
    (chosen / "B.m4b").write_bytes(b"an older B the owner kept")
    (chosen / "Kept" / "cover.png").write_bytes(b"\x89PNG not really")
    before = tree(chosen)
    panel, root = custom_panel(make_panel, tmp_path, chosen)
    sources_before = tree(root)
    real = proc.stage_book

    def stage(book, **kwargs):
        if book.filename != "A.m4b":
            panel.run.cancel()                      # pressed as the second Book's staging begins
        return real(book, **kwargs)

    monkeypatch.setattr(proc, "stage_book", stage)
    assert panel.build() is True
    panel._pump.tick()
    assert panel.last_result.state is JobState.CANCELLED
    assert chosen.is_dir(), "the chosen folder is never removed"
    after = tree(chosen)
    assert {name: digest for name, digest in after.items() if name in before} == before, "every file it held is unchanged"
    assert sorted(set(after) - set(before)) == ["A.m4b"], "only the Book finished before Cancel was added"
    assert not entries_of_kind(temp, "maker"), "the cancelled build's staging is gone"
    assert tree(root) == sources_before
    a, b = panel.workspace.books
    assert panel.book_status_for(b.book_id) == m4b_maker.STATUS_CANCELLED
