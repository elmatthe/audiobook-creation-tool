"""v0.6.0 Drop 2 Phase 2 — Preferences & Data, warning presentation, Reset.

Everything here runs against a redirected settings file in ``tmp_path`` and a
re-armed configuration cache, so no test reads, writes or resets the
maintainer's real preferences, Downloads folder, outputs, logs, ``.venv``,
models, binaries or media. The committed ``config.toml`` is only ever read, and
a test asserts its bytes are unchanged afterwards.

Tk tests skip cleanly where no display exists; the pure-logic tests (the
warning guard, the placeholder contract, scope checks) run everywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import config, preferences_ui  # noqa: E402
from shared import settings as app_settings  # noqa: E402
from shared import ui_theme  # noqa: E402
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="the ACT design system only applies on win32"
)

GENERIC_STYLES = (
    "TFrame", "TLabel", "TButton", "TEntry", "TCombobox", "TRadiobutton",
    "TCheckbutton", "TLabelframe", "Treeview", "Horizontal.TProgressbar",
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path):
    """Redirect settings to a throwaway file and re-arm every cached guard."""
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    config.invalidate()
    config.reset_launch_warning_guard()
    try:
        yield tmp_path
    finally:
        app_settings.use_path(None)
        config.invalidate()
        config.reset_launch_warning_guard()


@pytest.fixture
def fresh_root(tk_root):
    for child in tk_root.winfo_children():
        child.destroy()
    yield tk_root
    for child in tk_root.winfo_children():
        child.destroy()


class _Confirm:
    """A recording stand-in for the confirmation message box."""

    def __init__(self, answer: bool):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def __call__(self, title, message):
        self.calls.append((title, message))
        return self.answer


def make_dialog(root, *, answer=True, chosen=None, theme=None, logger=None):
    return preferences_ui.PreferencesDialog(
        root,
        theme if theme is not None else {},
        confirm=_Confirm(answer),
        ask_directory=lambda: chosen,
        logger=logger,
    )


def toplevels(root):
    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]


# --------------------------------------------------------------------------- #
# Launcher entry point
# --------------------------------------------------------------------------- #


def test_the_launcher_exposes_a_preferences_entry_point(fresh_root):
    import launcher

    app = launcher.LauncherApp(fresh_root)
    assert app.preferences_button.cget("text") == preferences_ui.MENU_LABEL
    assert str(app.preferences_button.cget("state")) != "disabled"


def test_the_entry_point_is_wired_to_open_preferences(fresh_root, monkeypatch):
    import launcher

    app = launcher.LauncherApp(fresh_root)
    opened: list[int] = []
    monkeypatch.setattr(app, "open_preferences", lambda: opened.append(1))
    app.preferences_button.configure(command=app.open_preferences)
    app.preferences_button.invoke()
    assert opened == [1]


def test_the_entry_point_is_keyboard_reachable(fresh_root):
    import launcher

    app = launcher.LauncherApp(fresh_root)
    assert int(app.preferences_button.cget("takefocus")) == 1


def test_both_platform_accelerators_are_bound(fresh_root):
    """Ctrl+, and Cmd+, both resolve to a binding.

    Tk normalises a sequence when it stores it (``<Control-comma>`` becomes
    ``<Control-Key-comma>``, ``<Command-comma>`` becomes ``<Mod1-Key-comma>``),
    so the binding is looked up rather than string-matched against the list.
    """
    import launcher

    app = launcher.LauncherApp(fresh_root)
    for sequence in preferences_ui.ACCELERATORS:
        assert app.root.bind_all(sequence), f"{sequence} is not bound"


def test_opening_twice_focuses_the_same_dialog_instead_of_duplicating(fresh_root):
    import launcher

    app = launcher.LauncherApp(fresh_root)
    first = app.open_preferences()
    second = app.open_preferences()
    assert first is second
    assert len(toplevels(fresh_root)) == 1


def test_a_closed_dialog_is_replaced_rather_than_reused(fresh_root):
    import launcher

    app = launcher.LauncherApp(fresh_root)
    first = app.open_preferences()
    first.close()
    second = app.open_preferences()
    assert second is not first
    assert len(toplevels(fresh_root)) == 1


def test_open_preferences_helper_focuses_a_live_dialog(fresh_root):
    first = preferences_ui.open_preferences(fresh_root, {})
    again = preferences_ui.open_preferences(fresh_root, {}, first)
    assert again is first
    assert len(toplevels(fresh_root)) == 1


# --------------------------------------------------------------------------- #
# Output base — display
# --------------------------------------------------------------------------- #


def test_the_dialog_shows_the_effective_output_base(fresh_root):
    dialog = make_dialog(fresh_root)
    effective = config.get_effective()
    assert dialog.var_effective.get() == str(effective.output.base_directory)


def test_the_default_source_is_described_as_the_default(fresh_root):
    dialog = make_dialog(fresh_root)
    assert dialog.var_mode.get() == "default"
    assert "default Downloads location" in dialog.var_source.get()


def test_a_custom_source_is_described_as_the_saved_preference(fresh_root, tmp_path):
    config.set_output_base(tmp_path / "Chosen")
    dialog = make_dialog(fresh_root)
    assert dialog.var_mode.get() == "custom"
    assert "your saved preference" in dialog.var_source.get()
    assert dialog.var_path.get() == str(tmp_path / "Chosen")


def test_the_custom_controls_are_disabled_while_the_default_is_selected(fresh_root):
    dialog = make_dialog(fresh_root)
    assert str(dialog.entry_path.cget("state")) == "disabled"
    assert str(dialog.button_browse.cget("state")) == "disabled"
    dialog.var_mode.set("custom")
    dialog._on_mode_change()
    assert str(dialog.entry_path.cget("state")) == "normal"


def test_browsing_fills_the_path_and_switches_to_custom(fresh_root, tmp_path):
    target = tmp_path / "Picked"
    dialog = make_dialog(fresh_root, chosen=str(target))
    dialog.browse()
    assert dialog.var_mode.get() == "custom"
    assert dialog.var_path.get() == str(target)


def test_cancelling_the_browser_changes_nothing(fresh_root):
    dialog = make_dialog(fresh_root, chosen="")
    dialog.browse()
    assert dialog.var_mode.get() == "default"
    assert dialog.var_path.get() == ""


# --------------------------------------------------------------------------- #
# Output base — validation and saving
# --------------------------------------------------------------------------- #


def test_an_absolute_output_base_is_accepted_and_saved(fresh_root, tmp_path):
    target = tmp_path / "Books" / "Outputs"
    dialog = make_dialog(fresh_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(target))

    assert dialog.save_output_base() is True
    assert dialog.status_kind == "success"
    assert app_settings.get("output_base_directory") == str(target)
    assert config.get_effective().output.base_directory == target


def test_a_tilde_output_base_is_accepted_and_expanded(fresh_root):
    dialog = make_dialog(fresh_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set("~/Media/AudiobookOutputs")

    assert dialog.save_output_base() is True
    saved = app_settings.get("output_base_directory")
    assert not saved.startswith("~")
    assert Path(saved).is_absolute()


@pytest.mark.parametrize("relative", ["Outputs", "./Outputs", "some/nested/dir"])
def test_a_relative_output_base_is_rejected_and_nothing_is_saved(fresh_root, relative):
    dialog = make_dialog(fresh_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set(relative)

    assert dialog.save_output_base() is False
    assert dialog.status_kind == "error"
    assert "relative" in dialog.var_status.get()
    assert app_settings.get("output_base_directory") is None


@pytest.mark.parametrize("raw", ["%USERPROFILE%/Outputs", "$HOME/Outputs", "${HOME}/Outputs"])
def test_an_environment_variable_path_is_rejected_never_expanded(fresh_root, raw):
    dialog = make_dialog(fresh_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set(raw)

    assert dialog.save_output_base() is False
    assert app_settings.get("output_base_directory") is None
    assert config.get_effective().output.is_default is True


def test_an_empty_custom_path_is_rejected_with_a_useful_message(fresh_root):
    dialog = make_dialog(fresh_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set("   ")
    assert dialog.save_output_base() is False
    assert dialog.status_kind == "error"


def test_choosing_the_default_clears_the_override(fresh_root, tmp_path):
    config.set_output_base(tmp_path / "Chosen")
    dialog = make_dialog(fresh_root)
    dialog.var_mode.set("default")

    assert dialog.save_output_base() is True
    assert config.get_effective().output.is_default is True


def test_no_output_directory_is_created_by_opening_or_saving(fresh_root, tmp_path):
    target = tmp_path / "NeverCreated" / "Outputs"
    dialog = make_dialog(fresh_root)
    assert not target.exists()
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(target))
    assert dialog.save_output_base() is True
    assert not target.exists(), "saving a preference must not create the folder"


def test_a_failed_write_keeps_the_previous_value_and_reports_it(fresh_root, tmp_path,
                                                               monkeypatch):
    good = tmp_path / "Good"
    config.set_output_base(good)
    dialog = make_dialog(fresh_root)

    monkeypatch.setattr(app_settings, "_write", lambda _data: False)
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(tmp_path / "Doomed"))

    assert dialog.save_output_base() is False
    assert dialog.status_kind == "error"
    assert "previous setting is still in use" in dialog.var_status.get()

    monkeypatch.undo()
    assert config.get_effective().output.base_directory == good
    assert app_settings.get("output_base_directory") == str(good)
    assert dialog.var_path.get() == str(good)


def test_the_effective_configuration_reloads_immediately_after_a_save(fresh_root, tmp_path):
    before = config.get_effective()
    dialog = make_dialog(fresh_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(tmp_path / "Fresh"))
    dialog.save_output_base()
    after = config.get_effective()
    assert after is not before
    assert after.output.base_directory == tmp_path / "Fresh"
    assert dialog.var_effective.get() == str(tmp_path / "Fresh")


def test_no_status_message_ever_contains_a_traceback(fresh_root, tmp_path, monkeypatch):
    dialog = make_dialog(fresh_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set("relative")
    dialog.save_output_base()
    assert "Traceback" not in dialog.var_status.get()

    monkeypatch.setattr(app_settings, "_write", lambda _data: False)
    dialog.var_path.set(str(tmp_path / "X"))
    dialog.save_output_base()
    assert "Traceback" not in dialog.var_status.get()


def test_technical_detail_is_logged_but_kept_out_of_the_visible_text(fresh_root):
    class _Logger:
        def __init__(self):
            self.lines: list[str] = []

        def warning(self, message, *args):
            self.lines.append(message % args if args else message)

    logger = _Logger()
    dialog = make_dialog(fresh_root, logger=logger)
    dialog.var_mode.set("custom")
    dialog.var_path.set("relative/path")
    dialog.save_output_base()

    assert any("relative/path" in line for line in logger.lines)
    assert "rejected output base" not in dialog.var_status.get()


# --------------------------------------------------------------------------- #
# Reset Preferences
# --------------------------------------------------------------------------- #


def test_reset_asks_for_confirmation_and_explains_the_scope(fresh_root):
    dialog = make_dialog(fresh_root, answer=False)
    dialog.reset_preferences()
    (title, message), = dialog._confirm.calls
    assert "Reset" in title
    for promised in ("last tool", "remembered", "output location"):
        assert promised in message
    for untouched in ("downloaded data", "config.toml"):
        assert untouched in message


def test_cancelling_reset_changes_nothing(fresh_root, tmp_path):
    config.set_output_base(tmp_path / "Kept")
    app_settings.set("last_tool", "m4b_maker")
    dialog = make_dialog(fresh_root, answer=False)

    assert dialog.reset_preferences() is False
    assert app_settings.get("last_tool") == "m4b_maker"
    assert config.get_effective().output.base_directory == tmp_path / "Kept"
    assert "cancelled" in dialog.var_status.get().lower()


def test_a_confirmed_reset_clears_only_mutable_preferences(fresh_root, tmp_path):
    config.set_output_base(tmp_path / "Chosen")
    app_settings.update({"last_tool": "tts", "input_dir": "D:/Books"})
    dialog = make_dialog(fresh_root, answer=True)

    assert dialog.reset_preferences() is True
    assert app_settings.all_settings() == {}
    assert dialog.status_kind == "success"


def test_reset_refreshes_the_visible_fields_and_source(fresh_root, tmp_path):
    config.set_output_base(tmp_path / "Chosen")
    dialog = make_dialog(fresh_root, answer=True)
    assert dialog.var_mode.get() == "custom"

    dialog.reset_preferences()
    assert dialog.var_mode.get() == "default"
    assert dialog.var_path.get() == ""
    assert "default Downloads location" in dialog.var_source.get()
    assert config.get_effective().output.is_default is True


def test_a_failed_reset_is_reported_and_leaves_settings_intact(fresh_root, monkeypatch):
    app_settings.set("last_tool", "tts")
    dialog = make_dialog(fresh_root, answer=True)
    monkeypatch.setattr(app_settings, "_write", lambda _data: False)

    assert dialog.reset_preferences() is False
    assert dialog.status_kind == "error"
    assert app_settings.get("last_tool") == "tts"


def test_reset_never_touches_the_committed_config_toml(fresh_root, tmp_path):
    committed = REPO_ROOT / "config.toml"
    before = committed.read_bytes()
    dialog = make_dialog(fresh_root, answer=True)
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(tmp_path / "Anywhere"))
    dialog.save_output_base()
    dialog.reset_preferences()
    assert committed.read_bytes() == before


def test_reset_leaves_every_unrelated_asset_untouched(fresh_root, tmp_path):
    assets = {
        tmp_path / ".venv" / "pyvenv.cfg": b"venv",
        tmp_path / "models" / "kokoro.pth": b"model",
        tmp_path / "logs" / "session_2026-08-03_000000.log": b"log",
        tmp_path / "bin" / "ffmpeg.exe": b"binary",
        tmp_path / "Outputs" / "book.m4b": b"output",
        tmp_path / "Media" / "source.mp3": b"media",
    }
    for path, payload in assets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    dialog = make_dialog(fresh_root, answer=True)
    assert dialog.reset_preferences() is True

    for path, payload in assets.items():
        assert path.exists() and path.read_bytes() == payload


# --------------------------------------------------------------------------- #
# Clear Downloaded Data entry point
# --------------------------------------------------------------------------- #
#
# Phase 6 replaced the inert Phase 2 placeholder with a real review dialog. The
# guards below moved with that boundary rather than being deleted: Preferences
# may now open the review, but it still may not delete, spawn or persist
# anything. The dialog's own behaviour is covered in
# ``test_preferences_maintenance_ui.py``.


def test_the_cleanup_entry_is_present_and_labelled(fresh_root):
    dialog = make_dialog(fresh_root)
    assert dialog.button_cleanup.cget("text") == preferences_ui.CLEANUP_BUTTON_LABEL
    assert dialog.label_cleanup_placeholder.cget("text") == (
        preferences_ui.CLEANUP_PLACEHOLDER_TEXT
    )


def test_the_cleanup_caption_does_not_claim_deletion_works_yet(fresh_root):
    caption = preferences_ui.CLEANUP_PLACEHOLDER_TEXT
    assert "Nothing is deleted yet." in caption


def test_the_cleanup_entry_is_a_separate_action_from_reset(fresh_root):
    dialog = make_dialog(fresh_root)
    assert dialog.button_cleanup is not dialog.button_reset
    assert str(dialog.button_cleanup.cget("command")) != str(
        dialog.button_reset.cget("command")
    )


def test_preferences_itself_still_deletes_spawns_and_persists_nothing():
    """The Phase 2 guard at its new home: the Phase 7 boundary."""
    import ast

    source = Path(preferences_ui.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for phase_seven in ("clear_downloaded_data", "delete_assets", "run_cleanup",
                        "schedule_cleanup", "write_request", "persist_request",
                        "wait_for_exit", "CleanupCoordinator"):
        assert phase_seven not in defined

    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for destructive in ("rmtree", "unlink", "remove", "rmdir", "Popen", "run",
                        "system", "quit", "write_text", "write_bytes"):
        assert destructive not in called

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    for forbidden in ("shutil", "subprocess", "os"):
        assert forbidden not in imported


# --------------------------------------------------------------------------- #
# Once-per-launch configuration warning
# --------------------------------------------------------------------------- #


class _RecordingWarning:
    """Stands in for the warning window so the guard can be tested headlessly."""

    instances: list[str] = []

    def __init__(self, master, summary, theme=None):
        type(self).instances.append(summary)


@pytest.fixture
def recorded_warnings():
    _RecordingWarning.instances = []
    yield _RecordingWarning.instances


def _force_diagnostics(monkeypatch, *diagnostics):
    snapshot = config.load(
        config_path=REPO_ROOT / "config.toml", settings_data={}, repo_root=REPO_ROOT
    )
    patched = config.EffectiveConfig(
        project=snapshot.project, output=snapshot.output, logging=snapshot.logging,
        importing=snapshot.importing, sources=snapshot.sources,
        diagnostics=tuple(diagnostics),
    )
    monkeypatch.setattr(config, "get_effective", lambda: patched)
    return patched


def test_no_warning_is_shown_when_there_are_no_diagnostics(fresh_root, recorded_warnings):
    assert config.get_effective().diagnostics == ()
    summary = preferences_ui.present_launch_warnings(
        fresh_root, {}, dialog_factory=_RecordingWarning
    )
    assert summary is None
    assert recorded_warnings == []


def test_the_warning_aggregates_every_diagnostic_into_one_window(fresh_root, monkeypatch,
                                                                recorded_warnings):
    _force_diagnostics(
        monkeypatch,
        config.Diagnostic("config.toml", "logging.max_sessions", "must be between 1 and 1000; using 30", "got 0"),
        config.Diagnostic("config.toml", "output.base_directory", "a relative path is not accepted; using the default Downloads location", "got 'x'"),
        config.Diagnostic("settings.json", "", "could not be read", "JSONDecodeError: boom"),
    )
    summary = preferences_ui.present_launch_warnings(
        fresh_root, {}, dialog_factory=_RecordingWarning
    )
    assert len(recorded_warnings) == 1, "one window for all diagnostics, never one per key"
    assert "logging.max_sessions" in summary
    assert "output.base_directory" in summary
    assert summary.count("•") == 3


def test_the_warning_summary_excludes_technical_detail(fresh_root, monkeypatch,
                                                       recorded_warnings):
    _force_diagnostics(
        monkeypatch,
        config.Diagnostic("settings.json", "", "could not be read", "JSONDecodeError: boom"),
    )
    summary = preferences_ui.present_launch_warnings(
        fresh_root, {}, dialog_factory=_RecordingWarning
    )
    assert "JSONDecodeError" not in summary
    assert "Traceback" not in summary


def test_the_technical_detail_reaches_the_log(fresh_root, monkeypatch, recorded_warnings):
    class _Logger:
        def __init__(self):
            self.lines: list[str] = []

        def warning(self, message, *args):
            self.lines.append(message % args if args else message)

    _force_diagnostics(
        monkeypatch,
        config.Diagnostic("settings.json", "", "could not be read", "JSONDecodeError: boom"),
    )
    logger = _Logger()
    preferences_ui.present_launch_warnings(
        fresh_root, {}, logger=logger, dialog_factory=_RecordingWarning
    )
    assert any("JSONDecodeError" in line for line in logger.lines)


def test_the_warning_is_shown_at_most_once_per_session(fresh_root, monkeypatch,
                                                       recorded_warnings):
    _force_diagnostics(
        monkeypatch,
        config.Diagnostic("config.toml", "logging.max_sessions", "using 30", "got 0"),
    )
    first = preferences_ui.present_launch_warnings(
        fresh_root, {}, dialog_factory=_RecordingWarning
    )
    second = preferences_ui.present_launch_warnings(
        fresh_root, {}, dialog_factory=_RecordingWarning
    )
    third = preferences_ui.present_launch_warnings(
        fresh_root, {}, dialog_factory=_RecordingWarning
    )
    assert first
    assert second is None and third is None
    assert len(recorded_warnings) == 1


def test_a_reload_storm_cannot_become_a_dialog_storm(fresh_root, monkeypatch,
                                                     recorded_warnings):
    _force_diagnostics(
        monkeypatch,
        config.Diagnostic("config.toml", "logging.max_sessions", "using 30", "got 0"),
    )
    preferences_ui.present_launch_warnings(fresh_root, {}, dialog_factory=_RecordingWarning)
    for _ in range(20):
        config.invalidate()
        preferences_ui.present_launch_warnings(fresh_root, {}, dialog_factory=_RecordingWarning)
    assert len(recorded_warnings) == 1


def test_opening_preferences_does_not_repeat_the_launch_warning(fresh_root, monkeypatch,
                                                               recorded_warnings):
    _force_diagnostics(
        monkeypatch,
        config.Diagnostic("config.toml", "logging.max_sessions", "using 30", "got 0"),
    )
    preferences_ui.present_launch_warnings(fresh_root, {}, dialog_factory=_RecordingWarning)
    make_dialog(fresh_root)
    make_dialog(fresh_root)
    assert len(recorded_warnings) == 1


def test_the_guard_is_deterministically_resettable_for_tests():
    config.reset_launch_warning_guard()
    assert config.launch_warning_pending() is True
    config.take_launch_warning()
    assert config.launch_warning_pending() is False
    config.reset_launch_warning_guard()
    assert config.launch_warning_pending() is True


def test_take_launch_warning_returns_none_when_nothing_is_wrong():
    config.reset_launch_warning_guard()
    assert config.get_effective().diagnostics == ()
    assert config.take_launch_warning() is None


def test_the_launcher_survives_a_warning_presentation_failure(fresh_root, monkeypatch):
    """A configuration warning must never become a startup failure."""
    import launcher

    def boom(*_args, **_kwargs):
        raise RuntimeError("no display for you")

    monkeypatch.setattr(preferences_ui, "present_launch_warnings", boom)
    app = launcher.LauncherApp(fresh_root)
    assert app.present_configuration_warnings() is None


def test_the_launcher_still_starts_with_a_broken_settings_file(fresh_root, tmp_path):
    """Safe continuation on fallback values."""
    import launcher

    broken = tmp_path / "runtime-data" / "settings.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{not json", encoding="utf-8")
    app_settings.invalidate()
    config.invalidate()

    app = launcher.LauncherApp(fresh_root)
    assert app.current_key in [t.key for t in app._available_tools()]
    assert config.get_effective().output.is_default is True


# --------------------------------------------------------------------------- #
# Styling, isolation and geometry
# --------------------------------------------------------------------------- #


def test_a_themeless_bundle_produces_unstyled_widgets(fresh_root):
    """The macOS/Linux path: no style name, so ttk resolves the native one."""
    dialog = make_dialog(fresh_root, theme={})
    assert str(dialog.button_save.cget("style")) == ""
    assert str(dialog.button_cleanup.cget("style")) == ""
    assert str(dialog.entry_path.cget("style")) == ""


def test_style_lookup_degrades_to_empty_without_a_style_map():
    assert preferences_ui._style({}, "primary_button") == ""
    assert preferences_ui._style(None, "primary_button") == ""
    assert preferences_ui._style({"styles": {"primary_button": "ACT.Primary.TButton"}},
                                 "primary_button") == "ACT.Primary.TButton"


def test_metric_lookup_degrades_to_the_fallback():
    assert preferences_ui._metric({}, "card_pad", 14) == 14
    assert preferences_ui._metric({"metrics": {"card_pad": 99}}, "card_pad", 14) == 99


@windows_only
def test_every_windows_widget_names_an_act_style(fresh_root, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    theme = ui_theme.apply_theme(fresh_root, ttk.Style(fresh_root))
    dialog = make_dialog(fresh_root, theme=theme)

    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)

    styled = 0
    for widget in walk(dialog):
        try:
            name = str(widget.cget("style"))
        except tk.TclError:
            continue
        if name:
            assert name.startswith(ui_theme.WINDOWS_STYLE_PREFIX + "."), name
            styled += 1
    assert styled > 10, "the Windows dialog should be built from the design system"


@windows_only
def test_building_the_dialog_leaves_the_generic_styles_untouched(fresh_root, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    style = ttk.Style(fresh_root)
    theme = ui_theme.apply_theme(fresh_root, style)

    def snapshot():
        return {n: (style.layout(n), style.configure(n), style.map(n),
                    style.lookup(n, "background"), style.lookup(n, "foreground"))
                for n in GENERIC_STYLES}

    before = snapshot()
    make_dialog(fresh_root, theme=theme)
    preferences_ui.ConfigWarningDialog(fresh_root, "• something", theme)
    after = snapshot()
    changed = [n for n in GENERIC_STYLES if before[n] != after[n]]
    assert not changed, f"Preferences leaked into generic styles: {changed}"


def test_the_window_constants_are_unchanged():
    assert ui_theme.MIN_SIZE == (920, 600)
    assert ui_theme.DEFAULT_GEOMETRY == "1024x720"


def test_the_unstyled_dialog_fits_inside_the_supported_minimum(fresh_root):
    dialog = make_dialog(fresh_root)
    dialog.update_idletasks()
    width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
    assert width <= 920, f"the bounded dialog is {width}px wide; it must fit 920x600"
    assert height <= 600, f"the bounded dialog is {height}px tall; it must fit 920x600"


@windows_only
def test_the_windows_dialog_fits_inside_the_supported_minimum(fresh_root, monkeypatch):
    """The Windows build is the tall one — larger fonts and button padding.

    Measuring only the unstyled bundle would have missed a real 689px dialog,
    so the themed path is asserted explicitly.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    theme = ui_theme.apply_theme(fresh_root, ttk.Style(fresh_root))
    dialog = make_dialog(fresh_root, theme=theme)
    dialog.update_idletasks()
    width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
    assert width <= 920, f"the Windows dialog is {width}px wide; it must fit 920x600"
    assert height <= 600, f"the Windows dialog is {height}px tall; it must fit 920x600"


@windows_only
def test_the_windows_warning_dialog_fits_inside_the_supported_minimum(fresh_root, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    theme = ui_theme.apply_theme(fresh_root, ttk.Style(fresh_root))
    warning = preferences_ui.ConfigWarningDialog(
        fresh_root, "• config.toml — logging.max_sessions: must be between 1 and 1000", theme
    )
    warning.update_idletasks()
    assert warning.winfo_reqwidth() <= 920
    assert warning.winfo_reqheight() <= 600


@windows_only
def test_every_primary_action_is_reachable_at_the_minimum(fresh_root, monkeypatch):
    """Save, Reset and Close must all be inside the bounded form, not below it."""
    monkeypatch.setattr(sys, "platform", "win32")
    theme = ui_theme.apply_theme(fresh_root, ttk.Style(fresh_root))
    dialog = make_dialog(fresh_root, theme=theme)
    # Browse is deliberately disabled until a custom folder is chosen, so put
    # the dialog in the state where every action is meant to be live.
    dialog.var_mode.set("custom")
    dialog._on_mode_change()
    dialog.update_idletasks()
    height = dialog.winfo_reqheight()
    for name, widget in (
        ("Save", dialog.button_save),
        ("Reset", dialog.button_reset),
        ("Close", dialog.button_close),
        ("Browse", dialog.button_browse),
    ):
        bottom = widget.winfo_y() + widget.winfo_reqheight()
        assert bottom <= height, f"{name} sits below the dialog's own height"
        # ttk's default takefocus is the script "ttk::takefocus", which puts an
        # enabled widget in the Tab order; only a literal "0" removes it.
        assert str(widget.cget("takefocus")) != "0", f"{name} is not keyboard-reachable"
        assert "disabled" not in widget.state(), f"{name} is disabled"


def test_the_dialog_uses_no_whole_dialog_scrolling(fresh_root):
    """Bounded content must adapt, not sit inside a permanent scroll canvas."""
    dialog = make_dialog(fresh_root)

    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)

    scrollers = [w for w in walk(dialog)
                 if isinstance(w, (tk.Canvas, ttk.Scrollbar, tk.Scrollbar))]
    assert scrollers == [], f"unexpected scrolling machinery: {scrollers}"


def test_escape_closes_the_dialog(fresh_root):
    dialog = make_dialog(fresh_root)
    assert dialog.bind("<Escape>")
    dialog.close()
    assert not dialog.winfo_exists()


# --------------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------------- #


def test_the_configuration_parser_still_imports_no_tk():
    import ast

    source = (REPO_ROOT / "scripts" / "Universal" / "shared" / "config.py").read_text(
        encoding="utf-8"
    )
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any("tkinter" in name for name in imported)
    assert "preferences_ui" not in imported


def test_phase_two_added_no_later_phase_behaviour():
    source = Path(preferences_ui.__file__).read_text(encoding="utf-8")
    for later in ("reserve_run", "Retry Failed", "Pause", "Resume",
                  "large_result_warning_threshold", "Add Book"):
        assert later not in source


def test_no_tool_panel_was_touched_by_phase_two():
    """Output behaviour belongs to Phases 3-5; the panels are untouched here."""
    import importlib

    for module_name in ("mp3_tools.cover_resizer", "mp3_tools.m4b_maker",
                        "mp3_tools.m4b_converter", "mp3_tools.mp3_tool"):
        module = importlib.import_module(module_name)
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "preferences_ui" not in source
        assert "Clear Downloaded Data" not in source
