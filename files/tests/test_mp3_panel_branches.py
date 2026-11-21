"""MP3 Tool panel branches that had no automated check — v0.7.2 Phase 6, ACT72-054.

Cancel Import during a folder scan, the MP3 Tool's own wording of the broad-folder and large-result questions, the
duplicate-file skip, a run reservation that fails, a plan refused after its run was reserved, and Write ID3 / Combine with
no proved FFmpeg. The real panel through its own methods; message boxes and dialogs are the seams the panel takes, so the
panel's decision and wording are what is proved here, not a native dialog.
"""

from __future__ import annotations

from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import output_paths  # noqa: E402
from shared.job_control import JobState  # noqa: E402

from mp3 import mp3_plan, mp3_processing, mp3_tool  # noqa: E402

from test_import_coordination import RecordingThreads  # noqa: E402
import test_import_coordination as tic  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_mp3_tool_ui import (  # noqa: E402,F401  (fixtures are collected by name)
    add_files,
    conversion_workers,
    import_folder,
    make_panel,
    reservations_under,
    tk_root,
    tracks,
    wait_until_prepared,
    windows_theme,
)


def parked_threads():
    class Parked(tic.InlineThread):
        def start(self):
            pass

    return RecordingThreads(kind=Parked)


def settle_import(panel, rounds: int = 20) -> None:
    for _ in range(rounds):
        panel._pump.tick()
        if not panel._coordinator.is_active:
            return


def settle_run(panel, limit: int = 200) -> None:
    for _ in range(limit):
        panel._pump.tick()
        if not panel.is_running:
            return
    raise AssertionError("the run did not settle within the tick budget")


def book_ids(panel) -> list[str]:
    return [book.book_id for book in panel.workspace.books]



def files_under(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()) if root.exists() else []


# --------------------------------------------------------------------------- import (ACT.MP3.IMPORT-FOLDER)


def test_cancel_import_ends_an_mp3_folder_scan_and_the_workspace_is_as_it_was(make_panel, tmp_path):
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
    settle_import(panel)
    assert not panel._coordinator.is_active
    assert book_ids(panel) == before and panel.workspace.current.files.is_empty
    assert any("Import Folder:" in line for line in panel.log.summary), panel.log.summary


def test_the_mp3_tool_asks_in_its_own_words_before_a_broad_folder_or_a_large_result(make_panel, tmp_path):
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
    settle_import(panel)
    assert [title for title, _ in asked] == ["Import a large number of MP3s?"]
    assert asked[0][1].startswith("2 MP3 files are ready to be imported."), asked[0][1]
    assert not panel._coordinator.is_active and book_ids(panel) == before and panel.workspace.current.files.is_empty


# --------------------------------------------------------------------------- add files (ACT.MP3.ADD-FILES)


def test_a_file_already_in_the_book_is_skipped_and_the_log_says_how_many(make_panel, tmp_path):
    one, two, three = tracks(tmp_path / "Loose", "01.mp3", "02.mp3", "03.mp3")
    panel = make_panel()
    add_files(panel, one, two)
    settle_import(panel)
    assert [entry.name for entry in panel.workspace.current.files.files] == ["01.mp3", "02.mp3"]
    add_files(panel, two, three, one)
    settle_import(panel)
    assert [entry.name for entry in panel.workspace.current.files.files] == ["01.mp3", "02.mp3", "03.mp3"]
    last = panel.log.summary[-1]
    assert last.startswith("Add Files: 1 MP3 file(s) added to") and last.endswith("2 already in this Book were skipped."), last


# --------------------------------------------------------------------------- the run's folder (ACT.MP3.OUTPUT-RUN)


@pytest.mark.parametrize("operation", ["write_id3_tags", "combine_mp3s"])
def test_a_run_folder_that_cannot_be_reserved_starts_nothing_and_says_why(make_panel, tmp_path, monkeypatch, operation):
    reserved: list = []

    def refuse(tool_key, **kwargs):
        reserved.append(tool_key)
        raise output_paths.OutputPathError("The output folder cannot be created.", "denied for this test")

    monkeypatch.setattr(output_paths, "reserve_run_directory", refuse)
    panel = make_panel()
    import_folder(panel, _two_books(tmp_path))
    workers = len(conversion_workers(panel))
    # v0.8.2: the press is accepted and the run is reserved off the Tk thread; the refusal arrives through the pump.
    assert getattr(panel, operation)() is True
    wait_until_prepared(panel)
    assert reserved == [mp3_tool.TOOL_KEY]
    assert make_panel.dialogs[-1] == ("error", "The output folder cannot be created.")
    assert len(conversion_workers(panel)) == workers and panel.last_plan is None and not panel.is_running
    assert panel.job_controller is None, "no run was started"
    assert panel.status.status_text == mp3_tool.STATUS_PREPARATION_FAILED


@pytest.mark.parametrize("operation, label", [("write_id3_tags", "Write ID3 Tags"), ("combine_mp3s", "Combine MP3s → One MP3")],
                         ids=["write_id3_tags", "combine_mp3s"])  # ASCII ids: pytest writes "→" as \u2192
def test_a_plan_refused_after_reserving_releases_the_empty_run_and_says_why(make_panel, tmp_path, monkeypatch,
                                                                             operation, label):
    made = reservations_under(tmp_path, monkeypatch)

    def refuse(*args, **kwargs):
        raise mp3_plan.PlanError("two Books would write the same file")

    monkeypatch.setattr(mp3_tool.mp3_plan, "plan_run", refuse)
    panel = make_panel()
    import_folder(panel, _two_books(tmp_path))
    workers = len(conversion_workers(panel))
    assert getattr(panel, operation)() is True  # v0.8.2: accepted; planned off the Tk thread
    wait_until_prepared(panel)
    assert len(made) == 1 and not made[0].run_directory.exists(), "the empty run it reserved is released"
    assert make_panel.dialogs[-1] == ("error", f"{label}: two Books would write the same file")
    assert len(conversion_workers(panel)) == workers and panel.last_plan is None and not panel.is_running
    assert panel.job_controller is None, "no run was started"


# --------------------------------------------------------------------------- no proved FFmpeg (ACT.MP3.FFMPEG-REQUIRED)


def test_the_panel_warns_when_ffmpeg_is_not_proved_and_ready_when_it_is(make_panel, monkeypatch):
    monkeypatch.setattr(mp3_tool, "ensure_ffmpeg_available", lambda: False)
    panel = make_panel()
    assert panel.status.label_status.cget("text") == (
        "WARNING: ffmpeg/ffprobe not found. Run the setup launcher to install it.")
    monkeypatch.setattr(mp3_tool, "ensure_ffmpeg_available", lambda: True)
    assert make_panel().status.label_status.cget("text") == mp3_tool.STATUS_READY


@pytest.mark.parametrize("operation", ["write_id3_tags", "combine_mp3s"])
def test_without_a_proved_ffmpeg_every_book_fails_and_nothing_is_published(make_panel, tmp_path, monkeypatch, operation):
    made = reservations_under(tmp_path, monkeypatch)
    monkeypatch.setattr(mp3_processing, "ensure_ffmpeg_available", lambda: False)
    root = _two_books(tmp_path)
    sources = {path: path.read_bytes() for path in root.rglob("*.mp3")}
    panel = make_panel()
    import_folder(panel, root)
    assert getattr(panel, operation)() is True
    settle_run(panel)
    result = panel.last_result
    assert result is not None and result.succeeded_count == 0 and result.failed_count == 2, result
    assert not result.can_retry_failed, "nothing a retry could reach: the failure belongs to no file"
    assert [panel.book_status_for(book.book_id) for book in panel.workspace.books] == [mp3_tool.STATUS_FAILED] * 2
    assert files_under(made[0].run_directory) == [], "nothing is published"
    details = "\n".join(panel.log.details)
    assert "ffmpeg/ffprobe is not available; run the setup launcher" in details, details[-600:]
    assert {path: path.read_bytes() for path in root.rglob("*.mp3")} == sources


def _two_books(tmp_path: Path) -> Path:
    root = tmp_path / "Library"
    tracks(root / "A", "01.mp3", "02.mp3")
    tracks(root / "B", "01.mp3")
    return root


# --------------------------------------------------------------------------- dialog history (v0.8.1 Checkpoint A)


def test_artwork_has_its_own_history_shared_by_shared_and_book_artwork(make_panel, tmp_path, monkeypatch):
    """The confirmed v0.8.0 defect: the artwork dialog opened at the import folder. Now artwork remembers its own
    folder (mp3_tool.cover_dir), Shared and Book artwork share it, and neither history moves the other."""
    from PIL import Image
    from shared import settings as app_settings

    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    try:
        home = tmp_path / "TheHome"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        library = tmp_path / "Library"
        first, = tracks(library, "01.mp3")
        covers = tmp_path / "Covers"
        covers.mkdir()
        cover = covers / "front.jpg"
        Image.new("RGB", (64, 64), (10, 200, 30)).save(cover, format="JPEG")
        broken = tmp_path / "Junk" / "broken.jpg"
        broken.parent.mkdir()
        broken.write_bytes(b"not an image")
        opened: list[tuple[str, str]] = []
        answer = {"artwork": str(cover)}
        monkeypatch.setattr(mp3_tool.filedialog, "askopenfilenames",
                            lambda **kw: opened.append(("files", kw["initialdir"])) or (str(first),))
        monkeypatch.setattr(mp3_tool.filedialog, "askopenfilename",
                            lambda **kw: opened.append(("art", kw["initialdir"])) or answer["artwork"])
        panel = make_panel(choose_files=None, choose_artwork=None)

        panel.add_files()
        settle_import(panel)
        assert app_settings.get(mp3_tool.KEY_INPUT_DIR) == str(library)
        panel.choose_book_artwork()
        assert opened[-1] == ("art", str(home)), "artwork never opens at the import folder"
        assert app_settings.get(mp3_tool.KEY_COVER_DIR) == str(covers)
        assert app_settings.get(mp3_tool.KEY_INPUT_DIR) == str(library), "and never moves the import history"
        panel.choose_shared_artwork()
        assert opened[-1] == ("art", str(covers)), "Shared artwork opens where Book artwork chose"
        panel.add_files()
        settle_import(panel)
        assert opened[-1] == ("files", str(library)), "and the import dialog is where it was"

        answer["artwork"] = str(broken)
        panel.choose_shared_artwork()
        assert app_settings.get(mp3_tool.KEY_COVER_DIR) == str(covers), "refused artwork is not remembered"
        answer["artwork"] = ""
        panel.choose_shared_artwork()
        assert app_settings.get(mp3_tool.KEY_COVER_DIR) == str(covers), "Cancel changes nothing"
    finally:
        app_settings.use_path(None)
