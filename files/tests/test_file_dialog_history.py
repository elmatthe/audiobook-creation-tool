"""v0.8.1 Checkpoint A — remembered file-dialog folders: the settings layer and the key contract.

Owner-approved behaviour (roadmap §1, "File-dialog persistence"): each tool has its own import history shared by its
import dialogs, its own artwork history (separate from import, shared by Shared and Book artwork), the M4B Maker's
custom destination and the Preferences output browser each have their own; a file selection leaves its folder, a
folder selection leaves itself; Cancel and rejected selections leave history alone; an unreachable remembered folder
falls back to the home folder WITHOUT erasing the saved value; Reset Preferences clears them; histories are local to
one installation's settings.json. The panel behaviour is proved beside each panel's own fixtures (the *_panel_branches,
test_tts_importing and test_preferences_ui modules); this module proves the shared helpers and the key contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared import config as cfg
from shared import preferences_ui
from shared import settings as app_settings
from artwork import cover_resizer
from m4b.converter import m4b_converter
from m4b.maker import m4b_maker
from m4b.metadata import m4b_metadata_editor
from mp3 import mp3_tool
from tts import epub2tts_gui
from test_settings_allowlist import _settings_writes

#: Every remembered dialog folder, by exact key. The seven before v0.8.1 keep their names and values.
EXISTING_KEYS = {
    "cover_resizer.input_dir", "m4b_converter.input_dir", "m4b_maker.input_dir", "m4b_maker.cover_dir",
    "m4b_metadata.input_dir", "m4b_metadata.cover_dir", "mp3_tool.input_dir",
}
NEW_KEYS = {"tts.input_dir", "mp3_tool.cover_dir", "m4b_maker.destination_dir", "preferences.output_browse_dir"}


@pytest.fixture
def settings_file(tmp_path):
    path = tmp_path / "runtime-data" / "settings.json"
    app_settings.use_path(path)
    try:
        yield path
    finally:
        app_settings.use_path(None)


@pytest.fixture
def home(tmp_path, monkeypatch):
    folder = tmp_path / "TheHome"
    folder.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: folder))
    return folder


# --------------------------------------------------------------------------- the key contract


def test_each_chooser_names_its_own_exact_key():
    assert epub2tts_gui.KEY_INPUT_DIR == "tts.input_dir"
    assert m4b_converter.KEY_INPUT_DIR == "m4b_converter.input_dir"
    assert cover_resizer.KEY_INPUT_DIR == "cover_resizer.input_dir"
    assert (mp3_tool.KEY_INPUT_DIR, mp3_tool.KEY_COVER_DIR) == ("mp3_tool.input_dir", "mp3_tool.cover_dir")
    assert (m4b_maker.KEY_INPUT_DIR, m4b_maker.KEY_COVER_DIR, m4b_maker.KEY_DEST_DIR) == (
        "m4b_maker.input_dir", "m4b_maker.cover_dir", "m4b_maker.destination_dir")
    assert (m4b_metadata_editor.KEY_INPUT_DIR, m4b_metadata_editor.KEY_COVER_DIR) == (
        "m4b_metadata.input_dir", "m4b_metadata.cover_dir")
    assert preferences_ui.KEY_OUTPUT_BROWSE_DIR == "preferences.output_browse_dir"


def test_every_history_key_is_allowlisted_user_state_and_none_is_a_configuration_override():
    keys = EXISTING_KEYS | NEW_KEYS
    assert len(keys) == 11, "per tool and per action: no two histories share a key"
    assert keys <= cfg.USER_STATE_SETTINGS
    assert not keys & set(cfg.SETTINGS_OVERLAY), "browsing never overrides the output location"
    assert "preferences.output_browse_dir" != "output_base_directory"


def test_every_history_key_has_a_real_production_writer():
    written = {key for _module, key, _line in _settings_writes()}
    assert (EXISTING_KEYS | NEW_KEYS) <= written


# --------------------------------------------------------------------------- where a dialog opens


def test_a_reachable_remembered_folder_is_where_the_dialog_opens(settings_file, home, tmp_path):
    books = tmp_path / "Books"
    books.mkdir()
    app_settings.set("tts.input_dir", str(books))
    assert app_settings.remembered_dir("tts.input_dir") == books


def test_nothing_remembered_opens_at_home(settings_file, home):
    assert app_settings.remembered_dir("tts.input_dir") == home


@pytest.mark.parametrize("saved", ["Gone", "AFile.txt", 123, ["x"], "", "   ", "bad\x00name"])
def test_an_unusable_remembered_value_falls_back_to_home_and_is_never_erased(settings_file, home, tmp_path, saved):
    """Missing, unmounted or not-a-folder values, and values a hand edit left that are not paths."""
    (tmp_path / "AFile.txt").write_text("x", encoding="utf-8")
    value = str(tmp_path / saved) if saved in ("Gone", "AFile.txt") else saved
    app_settings.set("mp3_tool.cover_dir", value)
    before = settings_file.read_bytes()
    assert app_settings.remembered_dir("mp3_tool.cover_dir") == home
    assert settings_file.read_bytes() == before, "a fallback never rewrites settings.json"
    assert app_settings.get("mp3_tool.cover_dir") == value


def test_an_inaccessible_remembered_folder_falls_back_without_raising(settings_file, home, tmp_path, monkeypatch):
    """A refused permission (or a dead network share) raises from ``is_dir`` on some Pythons; the dialog still opens."""
    locked = tmp_path / "Locked"
    locked.mkdir()
    app_settings.set("m4b_maker.destination_dir", str(locked))
    real_is_dir = Path.is_dir

    def is_dir(self):
        if self == locked:
            raise PermissionError(13, "Access is denied", str(self))
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    assert app_settings.remembered_dir("m4b_maker.destination_dir") == home
    assert app_settings.get("m4b_maker.destination_dir") == str(locked)


def test_a_folder_that_comes_back_is_offered_again(settings_file, home, tmp_path):
    """An unplugged drive: the saved entry survives its absence and is used once it is reachable again."""
    drive = tmp_path / "Removable"
    drive.mkdir()
    app_settings.set("cover_resizer.input_dir", str(drive))
    drive.rename(tmp_path / "Unplugged")
    assert app_settings.remembered_dir("cover_resizer.input_dir") == home
    (tmp_path / "Unplugged").rename(drive)
    assert app_settings.remembered_dir("cover_resizer.input_dir") == drive


# --------------------------------------------------------------------------- what a selection leaves behind


def test_a_file_selection_leaves_its_folder_and_a_folder_selection_leaves_itself(tmp_path):
    folder = tmp_path / "Lib"
    (folder / "Inner").mkdir(parents=True)
    first, second = folder / "a.txt", folder / "Inner" / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    assert app_settings.selected_dir(str(first), is_file=True) == str(folder)
    assert app_settings.selected_dir((str(first), str(second)), is_file=True) == str(folder), "the first file's"
    assert app_settings.selected_dir(str(folder / "Inner"), is_file=False) == str(folder / "Inner")
    assert app_settings.selected_dir(folder.as_posix(), is_file=False) == str(folder), "Tk's forward slashes"


@pytest.mark.parametrize("chosen", ["", (), [], None, "   ", 7])
def test_cancel_or_a_non_path_answer_leaves_nothing(chosen):
    assert app_settings.selected_dir(chosen, is_file=True) is None
    assert app_settings.selected_dir(chosen, is_file=False) is None


def test_a_selection_that_is_not_there_leaves_nothing(tmp_path):
    (tmp_path / "plain.txt").write_text("x", encoding="utf-8")
    assert app_settings.selected_dir(str(tmp_path / "missing.txt"), is_file=True) is None
    assert app_settings.selected_dir(str(tmp_path / "Missing"), is_file=False) is None
    assert app_settings.selected_dir(str(tmp_path / "plain.txt"), is_file=False) is None, "a file is not a folder"
    assert app_settings.selected_dir(str(tmp_path), is_file=True) is None, "a folder is not a file"


# --------------------------------------------------------------------------- persistence, reset, failure


def test_history_survives_a_restart_and_only_a_new_selection_replaces_it(settings_file, tmp_path):
    first, second = tmp_path / "One", tmp_path / "Two"
    first.mkdir()
    second.mkdir()
    assert app_settings.set("tts.input_dir", app_settings.selected_dir(str(first), is_file=False))
    app_settings.invalidate()  # a new process reads the file afresh
    assert json.loads(settings_file.read_text(encoding="utf-8"))["tts.input_dir"] == str(first)
    assert app_settings.remembered_dir("tts.input_dir") == first
    assert app_settings.set("tts.input_dir", app_settings.selected_dir(str(second), is_file=False))
    app_settings.invalidate()
    assert app_settings.remembered_dir("tts.input_dir") == second


def test_reset_preferences_clears_every_history_and_touches_no_media(settings_file, tmp_path):
    media = tmp_path / "Books" / "chapter.txt"
    media.parent.mkdir()
    media.write_text("words", encoding="utf-8")
    assert app_settings.update({key: str(media.parent) for key in EXISTING_KEYS | NEW_KEYS})
    assert app_settings.set("output_base_directory", str(tmp_path))
    assert cfg.reset_preferences() is True
    app_settings.invalidate()
    assert app_settings.all_settings() == {}
    assert media.read_text(encoding="utf-8") == "words" and media.parent.is_dir()


def test_a_failed_history_write_keeps_the_previous_value(settings_file, tmp_path, monkeypatch):
    old, new = tmp_path / "Old", tmp_path / "New"
    old.mkdir()
    new.mkdir()
    assert app_settings.set("mp3_tool.cover_dir", str(old))
    with monkeypatch.context() as failing:
        failing.setattr(app_settings, "_write", lambda data: False)
        assert app_settings.set("mp3_tool.cover_dir", str(new)) is False
        assert app_settings.get("mp3_tool.cover_dir") == str(old), "rolled back in memory"
    app_settings.invalidate()
    assert app_settings.get("mp3_tool.cover_dir") == str(old), "and on disk"
