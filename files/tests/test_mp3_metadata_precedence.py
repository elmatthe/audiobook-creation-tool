"""MP3 Tool metadata precedence -- v0.7.2 Phase 5, ACT72-006.

The contract (plan section 11.3): an explicit edit, including a deliberately
empty value, wins; then the values the session already holds; and only a field
that is truly unset takes the value the imported files suggest. Before this
phase a Book's first files wrote every nonblank source majority over values the
person had typed or cleared before that import (``mp3_workflow._prepopulated``),
reproduced at ``fa9d3c3`` by the first test below.

Unset is an *absent key*, never an empty string: ``set_book_field`` already
stores ``""`` for a cleared field, so first population now fills absent keys
only. Every scenario reads the panel's own fields **and** the tags of the files
a real Write ID3 Tags or Combine run published, decoded by mutagen -- never just
an entry widget. Sources are real MP3s made by the pinned FFmpeg and tagged by
mutagen; values are typed through the panel's own entry variables.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2

from shared import ffmpeg_utils
from shared.job_control import JobState
from mp3 import mp3_workflow as wf

from test_mp3_orchestration import settle  # noqa: E402
from test_mp3_tool_ui import (  # noqa: E402,F401  (fixtures are collected by name)
    add_files,
    import_folder,
    make_panel,
    reservations_under,
    tk_root,
    windows_theme,
)
from test_mp3_write_id3 import texts, tone  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ffmpeg_utils.have_ffmpeg(), reason="ffmpeg/ffprobe not available in this environment")

FRAME = {"artist": TPE1, "album_artist": TPE2, "album": TALB, "title": TIT2}


def source(path: Path, *, freq: int = 440, **frames: str) -> Path:
    """A real one-second MP3 carrying exactly the given ID3 text frames."""
    tone(path, freq=freq)
    tags = ID3()
    for name, value in frames.items():
        tags.add(FRAME[name](encoding=3, text=[value]))
    tags.save(path, v2_version=3)
    return path


def first_pair(root: Path) -> tuple[Path, Path]:
    return (source(root / "01.mp3", artist="Src Artist", album_artist="Src AA", album="Src Album"),
            source(root / "02.mp3", freq=520, artist="Src Artist", album_artist="Src AA",
                   album="Src Album"))


def typed(panel, name: str, value: str) -> None:
    """What a person's keystrokes do: write the field's own entry variable."""
    panel.surface.set_book_text(name, value)


def cleared(panel, name: str) -> None:
    """Typing something, then deleting it again: a deliberate blank."""
    typed(panel, name, "about to be deleted")
    typed(panel, name, "")


def fields(panel) -> dict[str, str]:
    return {name: panel.surface.book_value(name) for name in wf.SCALAR_FIELDS}


def written(panel) -> list[dict[str, str]]:
    """Write ID3 Tags for real; the published files' own frames, in track order."""
    panel.write_id3_tags()
    settle(panel)
    assert panel.last_result.state is JobState.SUCCEEDED, panel.last_result
    return [texts(track.published) for book in panel.last_plan.books for track in book.tracks]


def combined(panel) -> dict[str, str]:
    """Combine for real; the one published file's frames."""
    panel.combine_mp3s()
    settle(panel)
    assert panel.last_result.state is JobState.SUCCEEDED, panel.last_result
    book, = panel.last_plan.books
    return texts(book.combined_published)


def test_values_typed_or_cleared_before_the_first_files_survive_them_into_the_tags(
        make_panel, tmp_path, monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    a, b = first_pair(tmp_path / "Book")
    panel = make_panel()
    typed(panel, "album", "My Album")
    cleared(panel, "artist")
    add_files(panel, a, b)
    assert fields(panel) == {"artist": "", "album_artist": "Src AA", "album": "My Album"}, (
        "a typed and a cleared value must survive the first import; only the unset field is filled")
    for frames in written(panel):
        assert frames["TALB"] == "My Album"
        assert "TPE1" not in frames, "the cleared Artist must be absent, not the source's"
        assert frames["TPE2"] == "Src AA"
    whole = combined(panel)
    assert (whole["TALB"], whole["TIT2"], whole["TPE2"]) == ("My Album", "My Album", "Src AA")
    assert "TPE1" not in whole


def test_later_conflicting_files_change_no_stored_value(make_panel, tmp_path, monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    a, b = first_pair(tmp_path / "Book")
    other = source(tmp_path / "Other" / "03.mp3", freq=600, artist="Other Artist",
                   album_artist="Other AA", album="Other Album")
    panel = make_panel()
    typed(panel, "album", "My Album")
    add_files(panel, a, b)
    add_files(panel, other)
    assert fields(panel) == {"artist": "Src Artist", "album_artist": "Src AA", "album": "My Album"}
    assert panel.mixed_text("album_artist") == "Mixed source metadata"
    assert {frames["TPE2"] for frames in written(panel)} == {"Src AA"}, (
        "the minority's tag is a diagnostic, never a value")


def test_an_emptied_book_refilled_keeps_every_value_it_held(make_panel, tmp_path, monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    a, b = first_pair(tmp_path / "Book")
    panel = make_panel()
    add_files(panel, a, b)  # prefills all three: the session's values from here on
    typed(panel, "album", "Edited")
    panel.select_tracks(0, 1)  # both rows selected in the real track list
    panel.remove_selected_tracks()
    assert panel.workspace.current.files.is_empty
    refill = source(tmp_path / "Refill" / "01.mp3", freq=700, artist="New Artist",
                    album_artist="New AA", album="New Album")
    add_files(panel, refill)
    assert fields(panel) == {"artist": "Src Artist", "album_artist": "Src AA", "album": "Edited"}
    frames, = written(panel)
    assert (frames["TPE1"], frames["TPE2"], frames["TALB"]) == ("Src Artist", "Src AA", "Edited")


def test_new_and_duplicated_books_follow_the_same_precedence(make_panel, tmp_path, monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    a, b = first_pair(tmp_path / "One")
    c = source(tmp_path / "Two" / "01.mp3", freq=600, artist="Two Artist", album="Two Album")
    d = source(tmp_path / "Three" / "01.mp3", freq=660, artist="Three Artist", album="Three Album")
    panel = make_panel()
    first_id = panel.workspace.current.book_id
    typed(panel, "album", "Typed One")
    add_files(panel, a, b)
    panel.on_add()
    add_files(panel, c)
    assert fields(panel) == {"artist": "Two Artist", "album_artist": "", "album": "Two Album"}, (
        "a new Book's own first files fill its unset fields")
    assert "album_artist" not in panel.workspace.current.configuration, "a blank majority writes nothing"
    panel.on_select(first_id)
    assert fields(panel)["album"] == "Typed One", "navigation re-renders the Book's own value"
    panel.on_duplicate()
    assert panel.workspace.current.files.is_empty, "a duplicate carries configuration, not tracks"
    add_files(panel, d)
    assert fields(panel) == {"artist": "Src Artist", "album_artist": "Src AA", "album": "Typed One"}, (
        "the duplicate's carried values are the session's; its files fill nothing")
    by_album = {frames["TALB"]: frames for frames in written(panel)}
    assert set(by_album) == {"Typed One", "Two Album"}
    assert by_album["Two Album"]["TPE1"] == "Two Artist" and "TPE2" not in by_album["Two Album"]


def test_a_shared_value_wins_the_tags_and_the_book_value_survives_beneath_it(
        make_panel, tmp_path, monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    a, b = first_pair(tmp_path / "Book")
    panel = make_panel()
    panel.surface.set_shared_text("album", "Series Name")
    typed(panel, "artist", "Book Artist")
    add_files(panel, a, b)
    config = panel.workspace.current.configuration
    assert config["artist"] == "Book Artist", "typed before the import, kept"
    assert config["album"] == "Src Album", "unset under the Shared override, so filled"
    for frames in written(panel):
        assert frames["TALB"] == "Series Name", "a populated Shared field wins the output"
        assert frames["TPE1"] == "Book Artist"
    panel.surface.set_shared_text("album", "")
    assert panel.surface.book_value("album") == "Src Album", "clearing Shared shows the Book's own"


def test_import_folder_asks_before_replacing_typed_values_and_a_refusal_keeps_them(
        make_panel, tmp_path, monkeypatch):
    reservations_under(tmp_path, monkeypatch)
    first_pair(tmp_path / "Library" / "Book")
    answers: list[bool] = []
    asked: list[str] = []

    def confirm(title, message):
        asked.append(title)
        return answers.pop(0)

    panel = make_panel(confirm=confirm)
    panel.surface.set_shared_text("album_artist", "Shared AA")
    typed(panel, "album", "Typed Album")
    before = panel.workspace
    answers.append(False)
    import_folder(panel, tmp_path / "Library")
    assert asked == ["Replace the current Books?"]
    assert panel.workspace is before and fields(panel)["album"] == "Typed Album", "declined: nothing moves"
    answers.append(True)
    import_folder(panel, tmp_path / "Library")
    assert asked == ["Replace the current Books?"] * 2
    assert fields(panel) == {"artist": "Src Artist", "album_artist": "Src AA", "album": "Src Album"}, (
        "an accepted replacement builds new Books, filled from their own files")
    assert panel.workspace.shared.values["album_artist"] == "Shared AA", "Shared survives the replacement"
    for frames in written(panel):
        assert (frames["TALB"], frames["TPE2"]) == ("Src Album", "Shared AA")


def test_a_cancelled_import_dialog_changes_no_value(make_panel, tmp_path):
    panel = make_panel()
    typed(panel, "album", "Typed Album")
    cleared(panel, "artist")
    before = panel.workspace
    add_files(panel)  # the file dialog cancelled: no paths
    panel._choose_folder = lambda: ()
    panel.import_folder()  # confirmed, then the folder dialog cancelled
    assert panel.workspace is before
    assert panel.workspace.current.configuration == {"album": "Typed Album", "artist": ""}


def test_first_population_fills_only_fields_the_book_has_no_value_for():
    """The model rule on its own: key presence, never ``value == ''``."""
    from shared.importing import IdFactory

    space = wf.new_workspace(id_factory=IdFactory("t-"))
    space = wf.set_book_field(space, "album", "").workspace
    space = wf.set_book_field(space, "artist", "Mine").workspace
    book = space.current
    summary = wf.BookSourceSummary(**{name: wf.consensus(["Source"]) for name in wf.SCALAR_FIELDS})
    seeded = wf._prepopulated(book, summary)
    assert dict(seeded.configuration) == {"album": "", "artist": "Mine", "album_artist": "Source"}
