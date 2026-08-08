"""The mutable settings layer: atomic writes, failure reporting, reset, reload.

Every test redirects the settings layer at a temporary file through
``settings.use_path()``, so the suite can never read, rewrite or reset the
maintainer's real ``files/runtime-data/settings.json``. The autouse fixture
restores the real path afterwards even when a test fails.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared import config
from shared import settings as app_settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path):
    """Point the settings layer at a throwaway file for the whole test."""
    target = tmp_path / "runtime-data" / "settings.json"
    app_settings.use_path(target)
    config.invalidate()
    try:
        yield target
    finally:
        app_settings.use_path(None)
        config.invalidate()


def read_raw(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Injection itself
# --------------------------------------------------------------------------- #


def test_the_suite_never_points_at_the_real_settings_file(isolated_settings):
    from shared import paths

    assert app_settings.settings_path() == isolated_settings
    assert app_settings.settings_path() != paths.SETTINGS_FILE


def test_restoring_the_default_path_works():
    from shared import paths

    app_settings.use_path(None)
    assert app_settings.settings_path() == paths.SETTINGS_FILE


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def test_a_missing_file_is_not_an_error(isolated_settings):
    assert app_settings.all_settings() == {}
    assert app_settings.last_load_error() is None
    assert not isolated_settings.exists(), "reading must not create the file"


def test_malformed_json_falls_back_to_defaults_and_reports_why(isolated_settings):
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text("{not json at all", encoding="utf-8")
    app_settings.invalidate()

    assert app_settings.all_settings() == {}
    assert app_settings.get("last_tool", "fallback") == "fallback"
    error = app_settings.last_load_error()
    assert error and "JSONDecodeError" in error


def test_a_malformed_file_is_NOT_rewritten_during_load(isolated_settings):
    isolated_settings.parent.mkdir(parents=True)
    original = "{not json at all"
    isolated_settings.write_text(original, encoding="utf-8")
    app_settings.invalidate()

    app_settings.all_settings()
    app_settings.get("anything")
    app_settings.last_load_error()

    assert isolated_settings.read_text(encoding="utf-8") == original


def test_a_json_document_that_is_not_an_object_falls_back(isolated_settings):
    isolated_settings.parent.mkdir(parents=True)
    isolated_settings.write_text("[1, 2, 3]", encoding="utf-8")
    app_settings.invalidate()

    assert app_settings.all_settings() == {}
    assert "expected a JSON object" in (app_settings.last_load_error() or "")


def test_all_settings_returns_a_copy(isolated_settings):
    app_settings.set("last_tool", "tts")
    snapshot = app_settings.all_settings()
    snapshot["last_tool"] = "tampered"
    assert app_settings.get("last_tool") == "tts"


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def test_set_persists_atomically_and_reports_success(isolated_settings):
    assert app_settings.set("last_tool", "m4b_metadata") is True
    assert read_raw(isolated_settings) == {"last_tool": "m4b_metadata"}


def test_an_atomic_write_leaves_no_temporary_file_behind(isolated_settings):
    app_settings.set("last_tool", "tts")
    strays = [p.name for p in isolated_settings.parent.iterdir() if p.name.startswith(".settings_")]
    assert strays == []


def test_update_merges_and_persists_once(isolated_settings):
    app_settings.set("last_tool", "tts")
    assert app_settings.update({"input_dir": "D:/Books", "voice": "Jenny"}) is True
    assert read_raw(isolated_settings) == {
        "last_tool": "tts",
        "input_dir": "D:/Books",
        "voice": "Jenny",
    }


def test_autosave_false_does_not_touch_the_disk(isolated_settings):
    app_settings.set("last_tool", "tts")
    app_settings.set("voice", "Ava", autosave=False)
    assert read_raw(isolated_settings) == {"last_tool": "tts"}
    assert app_settings.get("voice") == "Ava"          # still in memory
    assert app_settings.save() is True
    assert read_raw(isolated_settings)["voice"] == "Ava"


def test_a_failed_write_is_reported_rather_than_swallowed(isolated_settings, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(app_settings.tempfile, "mkstemp", refuse)
    assert app_settings.set("last_tool", "tts") is False
    assert app_settings.save() is False


def test_a_failed_replace_cleans_up_and_reports_failure(isolated_settings, monkeypatch):
    monkeypatch.setattr(app_settings.os, "replace", lambda *a, **k: (_ for _ in ()).throw(
        OSError("replace refused")))
    assert app_settings.set("last_tool", "tts") is False
    strays = [p.name for p in isolated_settings.parent.iterdir() if p.name.startswith(".settings_")]
    assert strays == [], "a failed write must not leave a temporary file"


def test_a_failed_write_never_corrupts_the_previous_file(isolated_settings, monkeypatch):
    app_settings.set("last_tool", "tts")
    good = isolated_settings.read_text(encoding="utf-8")

    monkeypatch.setattr(app_settings.os, "replace", lambda *a, **k: (_ for _ in ()).throw(
        OSError("replace refused")))
    assert app_settings.set("last_tool", "broken") is False
    assert isolated_settings.read_text(encoding="utf-8") == good


# --------------------------------------------------------------------------- #
# Reset
# --------------------------------------------------------------------------- #


def test_reset_clears_every_mutable_preference(isolated_settings):
    app_settings.update(
        {
            "last_tool": "m4b_maker",
            "input_dir": "D:/Books",
            "cover_dir": "D:/Covers",
            "output_base_directory": "D:/Outputs",
        }
    )
    assert app_settings.reset() is True
    assert app_settings.all_settings() == {}
    assert read_raw(isolated_settings) == {}
    assert app_settings.get("output_base_directory") is None


def test_reset_reports_failure_instead_of_claiming_success(isolated_settings, monkeypatch):
    app_settings.set("last_tool", "tts")
    monkeypatch.setattr(app_settings, "_write", lambda _data: False)
    assert app_settings.reset() is False
    # The in-memory state must not pretend the reset happened.
    assert app_settings.get("last_tool") == "tts"


def test_valid_settings_survive_until_reset_is_deliberately_requested(isolated_settings):
    app_settings.update({"last_tool": "tts", "voice": "Jenny"})
    app_settings.invalidate()
    assert app_settings.all_settings() == {"last_tool": "tts", "voice": "Jenny"}
    app_settings.reset()
    assert app_settings.all_settings() == {}


def test_reset_touches_nothing_but_the_settings_file(isolated_settings, tmp_path):
    """Reset Preferences is not Clear Downloaded Data."""
    venv = tmp_path / ".venv" / "pyvenv.cfg"
    model = tmp_path / "models" / "kokoro.pth"
    log = tmp_path / "logs" / "session_2026-08-03_000000.log"
    binary = tmp_path / "bin" / "ffmpeg.exe"
    output = tmp_path / "Outputs" / "book.m4b"
    for path in (venv, model, log, binary, output):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"payload")
    before = {path: path.read_bytes() for path in (venv, model, log, binary, output)}

    app_settings.set("last_tool", "tts")
    assert app_settings.reset() is True

    for path, content in before.items():
        assert path.exists(), f"{path.name} must survive a preferences reset"
        assert path.read_bytes() == content


# --------------------------------------------------------------------------- #
# The configuration bridge
# --------------------------------------------------------------------------- #


def test_setting_the_output_base_persists_it_and_invalidates_the_snapshot(tmp_path):
    custom = tmp_path / "Chosen" / "Outputs"
    first = config.get_effective()
    assert config.set_output_base(custom) is True
    assert app_settings.get("output_base_directory") == str(custom)

    second = config.get_effective()
    assert second is not first, "the cached snapshot must have been invalidated"
    assert second.output.base_directory == custom
    assert second.output.is_default is False
    assert second.source_of("output.base_directory") == config.SOURCE_SETTINGS


def test_clearing_the_output_base_restores_the_default(tmp_path):
    config.set_output_base(tmp_path / "Chosen")
    assert config.get_effective().output.is_default is False
    assert config.set_output_base(None) is True
    assert config.get_effective().output.is_default is True
    assert app_settings.get("output_base_directory") == ""


@pytest.mark.parametrize("bad", ["relative/path", "Outputs", "./here"])
def test_setting_a_relative_output_base_is_refused_before_anything_is_written(bad):
    with pytest.raises(ValueError):
        config.set_output_base(bad)
    assert app_settings.get("output_base_directory") is None


def test_reset_preferences_refreshes_the_effective_configuration(tmp_path):
    config.set_output_base(tmp_path / "Chosen")
    assert config.get_effective().output.is_default is False
    assert config.reset_preferences() is True
    assert config.get_effective().output.is_default is True


def test_the_configuration_layer_never_writes_to_config_toml():
    """The GUI writes settings only; the committed TOML is read-only at runtime."""
    import ast

    source = Path(config.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in {"write_text", "write_bytes"}:
            raise AssertionError("config.py must not write files")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"mkdir", "unlink", "rmtree"}:
                raise AssertionError(f"config.py must not call {func.attr}")
