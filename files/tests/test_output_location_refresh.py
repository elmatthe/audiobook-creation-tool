"""Already-built panels must show the real output base the moment it changes.

Plan 2's preference contract is that the shared output base is chosen once in
Preferences & Data and every tool obeys it. A panel built *before* the change
kept its build-time label, so the application showed a destination it would not
actually use until the panel was rebuilt. The run itself was always correct —
``reserve_run_directory`` re-reads the effective configuration at operation
start — but a user must not be shown a stale destination.

The fix is one shared registry in ``output_paths``: a panel registers the
read-only variable it already owns, and a successful preference change re-points
every live registration. No panel duplicates the resolution rules, no panel is
rebuilt, and nothing about reservation changes.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import config, output_paths, preferences_ui  # noqa: E402
from shared import settings as app_settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"

TOOL_KEYS = ("tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover", "m4b_metadata")

PANEL_SOURCES = {
    "tts": UNIVERSAL / "tts" / "epub2tts_gui.py",
    "m4b_converter": UNIVERSAL / "mp3_tools" / "m4b_converter.py",
    "mp3_tool": UNIVERSAL / "mp3_tools" / "mp3_tool.py",
    "m4b_maker": UNIVERSAL / "mp3_tools" / "m4b_maker.py",
    "cover": UNIVERSAL / "mp3_tools" / "cover_resizer.py",
    "m4b_metadata": UNIVERSAL / "mp3_tools" / "m4b_metadata_editor.py",
}


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk cannot open a display here: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture(autouse=True)
def isolated_state(tmp_path):
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    config.invalidate()
    config.reset_launch_warning_guard()
    output_paths.forget_destination_hints()
    try:
        yield tmp_path
    finally:
        output_paths.forget_destination_hints()
        app_settings.use_path(None)
        config.invalidate()
        config.reset_launch_warning_guard()


class _Confirm:
    def __init__(self, answer: bool):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def __call__(self, title, message):
        self.calls.append((title, message))
        return self.answer


def make_dialog(root, *, answer=True, chosen=None):
    return preferences_ui.PreferencesDialog(
        root, {}, confirm=_Confirm(answer), ask_directory=lambda: chosen, logger=None,
    )


def panels(root):
    """Stand in for the six built panels: one registered display each."""
    made = {}
    for key in TOOL_KEYS:
        var = tk.StringVar(master=root, value=output_paths.destination_hint(key))
        output_paths.register_destination_hint(key, var)
        made[key] = var
    return made


def expected(base: Path, key: str) -> str:
    return str(Path(base) / output_paths.tool_parent_name(key))


# --------------------------------------------------------------------------- #
# The registry itself
# --------------------------------------------------------------------------- #


def test_a_registered_display_follows_the_effective_base(tk_root, tmp_path):
    shown = panels(tk_root)
    target = tmp_path / "Ré'sumé outputs Ñ"
    target.mkdir()
    config.set_output_base(target)
    output_paths.refresh_destination_hints()
    for key, var in shown.items():
        assert var.get() == expected(target, key), key


def test_refresh_reports_how_many_displays_it_updated(tk_root):
    panels(tk_root)
    assert output_paths.refresh_destination_hints() == len(TOOL_KEYS)


def test_an_unregistered_variable_is_never_touched(tk_root):
    loose = tk.StringVar(master=tk_root, value="untouched")
    panels(tk_root)
    output_paths.refresh_destination_hints()
    assert loose.get() == "untouched"


def test_an_unknown_tool_key_is_refused(tk_root):
    """A typo fails at build time, not by silently never refreshing."""
    var = tk.StringVar(master=tk_root)
    with pytest.raises(output_paths.UnknownToolError):
        output_paths.register_destination_hint("not_a_tool", var)
    assert output_paths.refresh_destination_hints() == 0


class _DeadDisplay:
    """A display whose widget has gone: assignment raises, as Tk's would."""

    def __init__(self):
        self.attempts = 0

    def set(self, value):
        self.attempts += 1
        raise tk.TclError('can\'t set "x": variable does not exist')


def test_a_dead_display_is_pruned_rather_than_raising(tk_root):
    doomed = _DeadDisplay()
    output_paths.register_destination_hint("tts", doomed)
    survivor = tk.StringVar(master=tk_root, value="")
    output_paths.register_destination_hint("mp3_tool", survivor)

    assert output_paths.refresh_destination_hints() == 1
    assert survivor.get() == expected(config.get_effective().output.base_directory, "mp3_tool")
    assert doomed.attempts == 1
    # dropped, so it is never tried again
    assert output_paths.refresh_destination_hints() == 1
    assert doomed.attempts == 1


def test_registering_the_same_variable_twice_updates_it_once(tk_root):
    var = tk.StringVar(master=tk_root)
    output_paths.register_destination_hint("tts", var)
    output_paths.register_destination_hint("tts", var)
    assert output_paths.refresh_destination_hints() == 1


def test_the_registry_uses_the_shared_resolution_not_its_own(tk_root, tmp_path):
    """The refreshed text must equal destination_hint exactly."""
    shown = panels(tk_root)
    target = tmp_path / "base"
    target.mkdir()
    config.set_output_base(target)
    output_paths.refresh_destination_hints()
    for key, var in shown.items():
        assert var.get() == output_paths.destination_hint(key), key


# --------------------------------------------------------------------------- #
# Through the real Preferences dialog
# --------------------------------------------------------------------------- #


def test_saving_a_custom_base_refreshes_every_existing_panel(tk_root, tmp_path):
    shown = panels(tk_root)
    before = {key: var.get() for key, var in shown.items()}
    target = tmp_path / "Ré'sumé Ñ outputs"
    target.mkdir()

    dialog = make_dialog(tk_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(target))
    assert dialog.save_output_base() is True

    for key, var in shown.items():
        assert var.get() == expected(target, key), key
        assert var.get() != before[key]
    dialog.destroy()


def test_resetting_preferences_refreshes_every_existing_panel(tk_root, tmp_path):
    shown = panels(tk_root)
    target = tmp_path / "temporary base"
    target.mkdir()

    dialog = make_dialog(tk_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(target))
    assert dialog.save_output_base() is True
    assert shown["tts"].get() == expected(target, "tts")

    assert dialog.reset_preferences() is True
    default = config.get_effective().output.base_directory
    for key, var in shown.items():
        assert var.get() == expected(default, key), key
    dialog.destroy()


def test_an_invalid_path_leaves_every_label_unchanged(tk_root):
    shown = panels(tk_root)
    before = {key: var.get() for key, var in shown.items()}

    dialog = make_dialog(tk_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set("relative/not/allowed")
    assert dialog.save_output_base() is False

    assert {key: var.get() for key, var in shown.items()} == before
    dialog.destroy()


def test_an_empty_path_leaves_every_label_unchanged(tk_root):
    shown = panels(tk_root)
    before = {key: var.get() for key, var in shown.items()}
    dialog = make_dialog(tk_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set("   ")
    assert dialog.save_output_base() is False
    assert {key: var.get() for key, var in shown.items()} == before
    dialog.destroy()


def test_a_cancelled_reset_leaves_every_label_unchanged(tk_root, tmp_path):
    shown = panels(tk_root)
    target = tmp_path / "kept base"
    target.mkdir()
    dialog = make_dialog(tk_root, answer=False)
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(target))
    assert dialog.save_output_base() is True
    after_save = {key: var.get() for key, var in shown.items()}

    assert dialog.reset_preferences() is False
    assert {key: var.get() for key, var in shown.items()} == after_save
    dialog.destroy()


def test_a_failed_settings_write_leaves_labels_at_the_prior_effective_value(
        tk_root, tmp_path, monkeypatch):
    shown = panels(tk_root)
    before = {key: var.get() for key, var in shown.items()}
    target = tmp_path / "never lands"
    target.mkdir()

    monkeypatch.setattr(config, "set_output_base", lambda value: False)
    dialog = make_dialog(tk_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(target))
    assert dialog.save_output_base() is False

    assert {key: var.get() for key, var in shown.items()} == before
    dialog.destroy()


def test_a_settings_write_that_raises_leaves_labels_unchanged(tk_root, tmp_path, monkeypatch):
    shown = panels(tk_root)
    before = {key: var.get() for key, var in shown.items()}
    target = tmp_path / "explodes"
    target.mkdir()

    def boom(value):
        raise OSError("disk gone")

    monkeypatch.setattr(config, "set_output_base", boom)
    dialog = make_dialog(tk_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(target))
    assert dialog.save_output_base() is False

    assert {key: var.get() for key, var in shown.items()} == before
    dialog.destroy()


def test_a_panel_built_after_the_change_shows_the_new_value(tk_root, tmp_path):
    target = tmp_path / "later base"
    target.mkdir()
    dialog = make_dialog(tk_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(target))
    assert dialog.save_output_base() is True
    dialog.destroy()

    late = panels(tk_root)
    for key, var in late.items():
        assert var.get() == expected(target, key), key


def test_the_displayed_destination_is_where_a_run_actually_lands(tk_root, tmp_path):
    shown = panels(tk_root)
    target = tmp_path / "Ré'sumé run Ñ"
    target.mkdir()

    dialog = make_dialog(tk_root)
    dialog.var_mode.set("custom")
    dialog.var_path.set(str(target))
    assert dialog.save_output_base() is True
    dialog.destroy()

    reservation = output_paths.reserve_run_directory("mp3_tool")
    assert str(reservation.tool_directory) == shown["mp3_tool"].get()
    assert reservation.run_directory.parent == reservation.tool_directory
    assert reservation.run_directory.is_dir()


def test_opening_preferences_twice_still_yields_one_dialog(tk_root):
    first = preferences_ui.open_preferences(tk_root, {}, None, logger=None)
    second = preferences_ui.open_preferences(tk_root, {}, first, logger=None)
    assert second is first
    first.destroy()


# --------------------------------------------------------------------------- #
# Structure: shared, not duplicated; no rebuild; no style churn
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", TOOL_KEYS)
def test_every_panel_registers_its_display(key):
    source = PANEL_SOURCES[key].read_text(encoding="utf-8")
    assert "register_destination_hint" in source, key
    assert "destination_hint(TOOL_KEY)" in source, key


@pytest.mark.parametrize("key", TOOL_KEYS)
def test_no_panel_recomputes_the_output_base_itself(key):
    """Resolution lives in output_paths; a panel may only display it."""
    source = PANEL_SOURCES[key].read_text(encoding="utf-8")
    for forbidden in ("Audiobook-Creation-Tool-Outputs", "resolve_output_base(",
                      "-Outputs\""):
        assert forbidden not in source, (key, forbidden)


def test_preferences_refreshes_through_the_shared_helper_only():
    source = (UNIVERSAL / "shared" / "preferences_ui.py").read_text(encoding="utf-8")
    assert "refresh_destination_hints" in source
    assert "destination_hint(" not in source.replace("refresh_destination_hints(", "")


def test_preferences_refreshes_on_both_success_paths_and_nowhere_else():
    """Exactly two call sites: the successful commit and the successful reset."""
    tree = ast.parse((UNIVERSAL / "shared" / "preferences_ui.py").read_text(encoding="utf-8"))
    owners = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "refresh_destination_hints"):
                owners.append(function.name)
    assert sorted(owners) == ["_commit", "reset_preferences"]


def test_no_panel_is_destroyed_or_rebuilt_to_refresh_a_label():
    source = (UNIVERSAL / "shared" / "preferences_ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        if function.name not in {"_commit", "reset_preferences"}:
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"destroy", "pack_forget", "grid_forget"}


def test_the_launcher_still_owns_panel_lifecycle():
    """The refresh must not have moved panel building into Preferences."""
    source = (UNIVERSAL / "shared" / "preferences_ui.py").read_text(encoding="utf-8")
    assert "containers" not in source and "select_tool" not in source


@pytest.mark.parametrize("key", TOOL_KEYS)
def test_registration_added_no_styling_or_layout_change(key):
    """Registration is one statement beside an existing variable, nothing more.

    The Plan 1 conversion boundary is unchanged: only the M4B Metadata editor
    names ``ACT.*`` styles, and the five unconverted panels still name none.
    """
    source = PANEL_SOURCES[key].read_text(encoding="utf-8")
    assert source.count("register_destination_hint") == 1, key
    if key == "m4b_metadata":
        assert "ACT." in source, "the converted editor keeps its design system"
    else:
        assert "ACT." not in source, key


def test_reservation_still_re_reads_the_configuration_at_run_start():
    source = (UNIVERSAL / "shared" / "output_paths.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "reserve_run_directory")
    body = ast.dump(function)
    assert "get_effective" in body


def test_the_registry_creates_nothing_on_disk(tk_root, tmp_path):
    target = tmp_path / "nothing here"
    target.mkdir()
    config.set_output_base(target)
    panels(tk_root)
    output_paths.refresh_destination_hints()
    assert list(target.iterdir()) == []
