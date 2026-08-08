"""v0.6.0 Drop 2 Phase 6 — the Clear Downloaded Data inventory and confirmation.

Every dialog here is built against a disposable fake repository root in
``tmp_path``. No test opens the production cleanup dialog against the
maintainer's real project, so the real ``.venv``, ``files/bin``,
``files/runtime-data/models`` and ``files/runtime-data/logs`` are never walked,
measured or touched — a structural test at the end proves no call site passes
the real root.

The dialogs are driven directly rather than through a modal loop:
``build_confirmation()`` is split from ``review_selection()`` for exactly that
reason, so the suite inspects and clicks the real window instead of a stand-in.

Phase 6 deletes nothing. The guards below assert the boundary rather than
assuming it: no destructive call, no process start, no persistence, and a
production callback that fails closed with the exact approved message.
"""

from __future__ import annotations

import ast
import gc
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import config, maintenance, preferences_ui, ui_theme  # noqa: E402
from shared import settings as app_settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="the ACT design system only applies on win32"
)

GENERIC_STYLES = (
    "TFrame", "TLabel", "TButton", "TEntry", "TCombobox", "TRadiobutton",
    "TCheckbutton", "TLabelframe", "Treeview", "Horizontal.TProgressbar",
)

#: The five panels Plan 1 deliberately left classic. Phase 6 must not convert
#: one by accident, so their sources are checked for ``ACT.*`` directly.
UNCONVERTED_PANELS = (
    "mp3_tools/cover_resizer.py", "mp3_tools/m4b_converter.py",
    "mp3_tools/m4b_maker.py", "mp3_tools/mp3_tool.py", "tts/epub2tts_gui.py",
)

VENV_BYTES = 500
BIN_BYTES = 1000
MODEL_BYTES = 2048
LOG_BYTES = 50


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:                       # headless box with no display
        pytest.skip(f"Tk cannot open a display here: {exc}")
    root.withdraw()
    yield root
    # Finalise the dialogs' Tk variables while the interpreter still owns a
    # live Tk; collecting one afterwards raises out of ``Variable.__del__``.
    gc.collect()
    root.destroy()


@pytest.fixture(autouse=True)
def isolated_state(tmp_path):
    """Redirect settings to a throwaway file; never read the real preferences."""
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
    # Clear the previous test's discarded Tk variables here, on the main
    # thread. Left as garbage, one can instead be finalised inside a dialog's
    # background inventory thread, where ``Variable.__del__`` raises "main
    # thread is not in main loop".
    gc.collect()
    yield tk_root
    for child in tk_root.winfo_children():
        child.destroy()
    gc.collect()


def write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def fake_root(tmp_path: Path, *, venv=True, binaries=True, models=True, logs=True) -> Path:
    root = tmp_path / "fake-repo"
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "files" / "runtime-data").mkdir(parents=True, exist_ok=True)
    write(root / "config.toml", b"# fake\n")
    write(root / "files" / "runtime-data" / "settings.json", b"{}")
    if venv:
        write(root / ".venv" / "pyvenv.cfg", b"x" * VENV_BYTES)
    if binaries:
        write(root / "files" / "bin" / "ffmpeg.exe", b"y" * BIN_BYTES)
    if models:
        write(root / "files" / "runtime-data" / "models" / "m.bin", b"m" * MODEL_BYTES)
    if logs:
        write(root / "files" / "runtime-data" / "logs" / "s.log", b"l" * LOG_BYTES)
    return root


def snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root)).replace("\\", "/")] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return out


def make_junction(link: Path, target: Path) -> bool:
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                              capture_output=True, text=True)
        return done.returncode == 0
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        return False


class Recorder:
    """A stand-in cleanup callback that records instead of doing anything."""

    def __init__(self, accepts: bool = False):
        self.accepts = accepts
        self.requests: list = []

    def __call__(self, request):
        self.requests.append(request)
        return self.accepts


def make_cleanup(root, fake, *, theme=None, start_cleanup=None, measure=False,
                 close_application=None):
    """The real dialog against a fake repository root.

    ``measure`` defaults off here so a test does not leave a daemon worker
    running behind it; the background-inventory tests below opt in explicitly
    and join the thread. Sizes are supplied directly with ``apply_measured``
    where a test needs them, which is the same snapshot the worker delivers.
    """
    return preferences_ui.CleanupDialog(
        root, theme if theme is not None else {}, repo_root=fake,
        start_cleanup=start_cleanup, measure=measure,
        close_application=close_application or (lambda: None), close_delay=0,
    )


def rows(dialog):
    return {item.asset_id: item for item in dialog.items}


def toplevels(widget):
    return [w for w in widget.winfo_children() if isinstance(w, tk.Toplevel)]


# --------------------------------------------------------------------------- #
# The Preferences entry point
# --------------------------------------------------------------------------- #


def test_the_preferences_entry_is_enabled_and_wired(fresh_root, tmp_path):
    dialog = preferences_ui.PreferencesDialog(fresh_root, {}, repo_root=fake_root(tmp_path))
    assert dialog.button_cleanup.cget("text") == preferences_ui.CLEANUP_BUTTON_LABEL
    assert str(dialog.button_cleanup.cget("state")) != "disabled"
    assert str(dialog.button_cleanup.cget("command")) != ""


def test_the_entry_opens_one_cleanup_dialog_rather_than_stacking(fresh_root, tmp_path):
    prefs = preferences_ui.PreferencesDialog(
        fresh_root, {}, repo_root=fake_root(tmp_path), start_cleanup=Recorder()
    )
    first = prefs.open_cleanup()
    second = prefs.open_cleanup()
    assert first is second
    assert len(toplevels(prefs)) == 1


def test_reopening_after_closing_creates_a_new_dialog(fresh_root, tmp_path):
    prefs = preferences_ui.PreferencesDialog(
        fresh_root, {}, repo_root=fake_root(tmp_path), start_cleanup=Recorder()
    )
    first = prefs.open_cleanup()
    first.close()
    second = prefs.open_cleanup()
    assert second is not first


def test_reset_preferences_remains_a_separate_control(fresh_root, tmp_path):
    prefs = preferences_ui.PreferencesDialog(fresh_root, {}, repo_root=fake_root(tmp_path))
    assert prefs.button_reset is not prefs.button_cleanup
    assert str(prefs.button_reset.cget("command")) != str(
        prefs.button_cleanup.cget("command")
    )
    assert "Reset" in prefs.button_reset.cget("text")
    assert "Reset" not in prefs.button_cleanup.cget("text")


def test_resetting_preferences_cannot_touch_downloaded_data(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    before = snapshot(fake)
    prefs = preferences_ui.PreferencesDialog(
        fresh_root, {}, confirm=lambda *_a: True, repo_root=fake
    )
    assert prefs.reset_preferences() is True
    assert snapshot(fake) == before
    assert (fake / ".venv").exists()
    assert (fake / "files" / "bin").exists()


# --------------------------------------------------------------------------- #
# Rows, state and size text
# --------------------------------------------------------------------------- #


def test_all_four_rows_render_with_their_catalog_labels(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path))
    dialog.apply_measured(maintenance.inventory(dialog._repo_root))
    assert [i.asset_id for i in dialog.items] == list(maintenance.ASSET_IDS)
    for asset_id, widgets in dialog._rows.items():
        definition = maintenance.CATALOG_BY_ID[asset_id]
        assert widgets["check"].cget("text") == definition.display_name


def test_present_rows_show_their_state_size_and_consequence(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    dialog = make_cleanup(fresh_root, fake, measure=False)
    dialog.apply_measured(maintenance.inventory(fake))
    widgets = dialog._rows["portable_binaries"]
    assert widgets["state"].cget("text") == "Present"
    assert widgets["size"].cget("text") == maintenance.format_bytes(BIN_BYTES)
    assert widgets["detail"].cget("text") == (
        maintenance.CATALOG_BY_ID["portable_binaries"].consequence
    )


def test_a_missing_row_says_missing_and_is_disabled(fresh_root, tmp_path):
    fake = fake_root(tmp_path, models=False)
    dialog = make_cleanup(fresh_root, fake, measure=False)
    dialog.apply_measured(maintenance.inventory(fake))
    widgets = dialog._rows["downloaded_models"]
    assert widgets["state"].cget("text") == "Missing"
    assert "disabled" in widgets["check"].state()
    assert dialog._vars["downloaded_models"].get() is False


def test_an_unsafe_row_is_disabled_and_explains_why(fresh_root, tmp_path):
    fake = fake_root(tmp_path, logs=False)
    outside = tmp_path / "outside-logs"
    write(outside / "a.log", b"a" * 10)
    if not make_junction(fake / "files" / "runtime-data" / "logs", outside):
        pytest.skip("this account cannot create a directory link here")
    dialog = make_cleanup(fresh_root, fake, measure=False)
    dialog.apply_measured(maintenance.inventory(fake))
    widgets = dialog._rows["application_logs"]
    assert "disabled" in widgets["check"].state()
    assert "link" in widgets["detail"].cget("text")
    assert dialog._vars["application_logs"].get() is False


def test_sizes_start_as_calculating_before_the_worker_reports(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), measure=False)
    for widgets in dialog._rows.values():
        assert widgets["size"].cget("text") in (
            maintenance.CALCULATING_TEXT, "—",
        )


def test_an_incomplete_size_is_shown_as_a_minimum(fresh_root, tmp_path, monkeypatch):
    fake = fake_root(tmp_path)
    dialog = make_cleanup(fresh_root, fake, measure=False)
    monkeypatch.setattr(maintenance, "estimate_size",
                        lambda p: maintenance.SizeEstimate(64, False, ("unreadable",)))
    dialog.apply_measured(maintenance.inventory(fake))
    assert dialog._rows["application_logs"]["size"].cget("text") == "64 bytes (at least)"


# --------------------------------------------------------------------------- #
# Safe selection defaults
# --------------------------------------------------------------------------- #


def test_every_checkbox_starts_unchecked(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path))
    assert dialog.selected_ids() == ()
    assert all(var.get() is False for var in dialog._vars.values())


def test_nothing_is_preselected_merely_because_it_is_present(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), measure=False)
    dialog.apply_measured(maintenance.inventory(dialog._repo_root))
    assert all(item.present for item in dialog.items)
    assert dialog.selected_ids() == ()


def test_the_review_action_starts_disabled(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path))
    assert str(dialog.button_review.cget("state")) == "disabled"
    assert dialog.var_status.get() == maintenance.NOTHING_SELECTED_TEXT


def test_the_review_action_enables_only_after_a_deliberate_tick(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path))
    dialog._vars["application_logs"].set(True)
    dialog._on_selection_change()
    assert str(dialog.button_review.cget("state")) == "normal"
    dialog._vars["application_logs"].set(False)
    dialog._on_selection_change()
    assert str(dialog.button_review.cget("state")) == "disabled"


def test_closing_and_reopening_resets_every_selection(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    prefs = preferences_ui.PreferencesDialog(
        fresh_root, {}, repo_root=fake, start_cleanup=Recorder()
    )
    first = prefs.open_cleanup()
    first._vars["application_logs"].set(True)
    first._on_selection_change()
    assert first.selected_ids() == ("application_logs",)
    first.close()

    second = prefs.open_cleanup()
    assert second.selected_ids() == ()
    assert str(second.button_review.cget("state")) == "disabled"


def test_a_disabled_row_cannot_contribute_to_a_selection(fresh_root, tmp_path):
    fake = fake_root(tmp_path, venv=False)
    dialog = make_cleanup(fresh_root, fake)
    dialog._vars["virtual_environment"].set(True)      # as if something forced it
    assert dialog.selected_ids() == ()


def test_the_selected_total_updates_truthfully(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    dialog = make_cleanup(fresh_root, fake, measure=False)
    dialog.apply_measured(maintenance.inventory(fake))

    dialog._vars["application_logs"].set(True)
    dialog._on_selection_change()
    assert "1 item selected" in dialog.var_status.get()
    assert maintenance.format_bytes(LOG_BYTES) in dialog.var_status.get()

    dialog._vars["portable_binaries"].set(True)
    dialog._on_selection_change()
    assert "2 items selected" in dialog.var_status.get()
    assert maintenance.format_bytes(LOG_BYTES + BIN_BYTES) in dialog.var_status.get()


def test_an_unreadable_size_is_named_in_the_total(fresh_root, tmp_path, monkeypatch):
    fake = fake_root(tmp_path)
    dialog = make_cleanup(fresh_root, fake, measure=False)
    monkeypatch.setattr(maintenance, "estimate_size",
                        lambda p: maintenance.SizeEstimate(8, False, ("unreadable",)))
    dialog.apply_measured(maintenance.inventory(fake))
    dialog._vars["application_logs"].set(True)
    dialog._on_selection_change()
    assert "could not be read safely" in dialog.var_status.get()


# --------------------------------------------------------------------------- #
# The confirmation
# --------------------------------------------------------------------------- #


def select(dialog, *asset_ids):
    for asset_id in asset_ids:
        dialog._vars[asset_id].set(True)
    dialog._on_selection_change()
    return dialog


def test_the_confirmation_title_and_body_are_exact(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    dialog = make_cleanup(fresh_root, fake, measure=False)
    dialog.apply_measured(maintenance.inventory(fake))
    select(dialog, "virtual_environment", "application_logs")

    window = dialog.build_confirmation()
    assert window.title() == "Confirm clearing downloaded data"
    body = window.label_message.cget("text")
    assert body.startswith("You selected 2 downloaded-data item(s) to clear:")
    assert "• Private Python environment — Present, 500 bytes" in body
    assert "Estimated space to be freed: 550 bytes." in body
    assert (
        "Audiobook Creation Tool will close before cleanup starts. Selected data will "
        "be removed only after the app has exited." in body
    )
    assert (
        "Preferences, config.toml, source media, and audiobook outputs are not included."
        in body
    )
    assert body.endswith(
        "This cleanup cannot be undone, although selected dependencies, binaries, and "
        "models can be rebuilt or downloaded again. Continue?"
    )


def test_only_the_selected_effect_lines_appear(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    dialog = make_cleanup(fresh_root, fake, measure=False)
    dialog.apply_measured(maintenance.inventory(fake))
    select(dialog, "downloaded_models")
    body = dialog.build_confirmation().label_message.cget("text")
    assert maintenance.CATALOG_BY_ID["downloaded_models"].effect_line in body
    assert maintenance.CATALOG_BY_ID["virtual_environment"].effect_line not in body


def test_the_destructive_label_is_singular_then_plural(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    dialog = make_cleanup(fresh_root, fake)
    select(dialog, "application_logs")
    assert dialog.build_confirmation().btn_confirm.cget("text") == (
        "Clear 1 Selected Item and Close"
    )
    select(dialog, "portable_binaries")
    assert dialog.build_confirmation().btn_confirm.cget("text") == (
        "Clear 2 Selected Items and Close"
    )


def test_cancel_is_the_focused_default_not_the_destructive_button(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path))
    window = select(dialog, "application_logs").build_confirmation()
    assert window.default_widget is window.btn_cancel
    assert window.default_widget is not window.btn_confirm
    assert window.btn_cancel.cget("text") == "Cancel"


def test_only_cancel_ever_takes_initial_focus_in_a_destructive_dialog():
    """Focus is unobservable on a withdrawn root, so the source is asserted.

    Scoped to the two windows that can lead to a deletion. Phase 7's read-only
    report window is deliberately allowed to focus its own dismiss button — it
    offers no destructive action at all — and is checked separately below.
    """
    source = Path(preferences_ui.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    destructive = {"CleanupDialog", "CleanupConfirmationDialog"}
    targets = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name in destructive):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "focus_set"):
                value = inner.func.value
                if isinstance(value, ast.Attribute):
                    targets.add(value.attr)
    assert targets == {"button_cancel", "btn_cancel"}, targets


def test_the_report_window_has_no_destructive_control():
    source = Path(preferences_ui.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    report = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.ClassDef) and node.name == "CleanupResultDialog")
    body = ast.dump(report)
    for destructive in ("build_request", "start_cleanup", "submit", "review_selection"):
        assert destructive not in body, destructive


def test_the_confirmation_rebuilds_from_the_live_selection(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    dialog = make_cleanup(fresh_root, fake, measure=False)
    dialog.apply_measured(maintenance.inventory(fake))
    first = select(dialog, "application_logs").build_confirmation()
    assert "You selected 1 downloaded-data item(s)" in first.label_message.cget("text")
    first.cancel()

    select(dialog, "portable_binaries", "downloaded_models")
    second = dialog.build_confirmation()
    assert second is not first
    assert "You selected 3 downloaded-data item(s)" in second.label_message.cget("text")


def test_escape_and_the_close_control_are_both_wired_to_cancel(fresh_root, tmp_path):
    """A key press cannot be delivered to an unfocused window on a withdrawn
    root, so the wiring is asserted directly: the window-close protocol resolves
    to ``cancel``, and the Escape binding exists. The outcome of taking that
    path is proved by the test below.
    """
    dialog = make_cleanup(fresh_root, fake_root(tmp_path))
    window = select(dialog, "application_logs").build_confirmation()
    assert window.protocol("WM_DELETE_WINDOW").endswith("cancel")
    assert window.bind("<Escape>") != ""


def test_taking_the_cancel_path_declines_safely(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path))
    window = select(dialog, "application_logs").build_confirmation()
    window.cancel()
    assert window.result is False
    assert not window.winfo_exists()


def test_the_cleanup_dialog_itself_cancels_on_escape_and_close(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path))
    assert dialog.protocol("WM_DELETE_WINDOW").endswith("close")
    assert dialog.bind("<Escape>") != ""
    dialog.close()
    assert not dialog.winfo_exists()


def test_cancelling_records_nothing_and_calls_nothing(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    before = snapshot(fake)
    recorder = Recorder()
    dialog = make_cleanup(fresh_root, fake, start_cleanup=recorder)
    window = select(dialog, "application_logs").build_confirmation()
    window.cancel()
    assert window.result is False
    assert recorder.requests == []
    assert dialog.last_request is None
    assert snapshot(fake) == before


def test_the_confirmation_cannot_be_suppressed_or_remembered():
    source = Path(preferences_ui.__file__).read_text(encoding="utf-8")
    for word in ("dont_ask", "do_not_ask", "remember_choice", "suppress",
                 "skip_confirmation", "_confirmed_once"):
        assert word not in source, word
    assert source.count("build_confirmation(") >= 2   # defined and called, once


# --------------------------------------------------------------------------- #
# Accepting — and the Phase 6 fail-closed boundary
# --------------------------------------------------------------------------- #


def test_accepting_builds_exactly_one_validated_request(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    recorder = Recorder(accepts=True)
    dialog = make_cleanup(fresh_root, fake, start_cleanup=recorder)
    select(dialog, "application_logs", "portable_binaries")

    assert dialog.submit(dialog.selected_ids()) is True
    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert isinstance(request, maintenance.CleanupRequest)
    assert request.asset_ids == ("portable_binaries", "application_logs")
    assert request.schema_version == maintenance.SCHEMA_VERSION
    assert request.process_id == os.getpid()
    assert dialog.last_request is request


def test_the_request_carries_ids_only_and_no_path(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    recorder = Recorder(accepts=True)
    dialog = make_cleanup(fresh_root, fake, start_cleanup=recorder)
    select(dialog, "virtual_environment")
    dialog.submit(dialog.selected_ids())

    payload = maintenance.request_to_dict(recorder.requests[0])
    assert set(payload) == set(maintenance.REQUEST_FIELDS)
    assert str(fake) not in str(payload)
    assert ".venv" not in str(payload)


def test_the_production_handoff_is_the_coordinator_start(fresh_root, tmp_path):
    """Phase 7 replaced the fail-closed default with the real handoff.

    The handoff still cannot delete: it persists a request and starts a separate
    process, and this dialog closes only if that process acknowledges.
    """
    from shared import cleanup_state

    dialog = make_cleanup(fresh_root, fake_root(tmp_path))
    assert dialog._start_cleanup == dialog._default_start_cleanup
    source = Path(preferences_ui.__file__).read_text(encoding="utf-8")
    assert "cleanup_state.start_cleanup(" in source
    assert callable(cleanup_state.start_cleanup)


def test_the_production_path_reports_the_exact_failure_message(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    before = snapshot(fake)
    dialog = make_cleanup(fresh_root, fake, start_cleanup=Recorder())
    select(dialog, "virtual_environment", "application_logs")

    assert dialog.submit(dialog.selected_ids()) is False
    assert dialog.var_status.get() == maintenance.CLEANUP_FAILED_MESSAGE
    assert dialog.var_status.get() == (
        "Cleanup did not start. No data was changed, and Audiobook Creation Tool "
        "will remain open."
    )
    assert dialog.status_kind == "error"
    assert snapshot(fake) == before


def test_failing_closed_leaves_both_dialogs_usable(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    prefs = preferences_ui.PreferencesDialog(fresh_root, {}, repo_root=fake,
                                             start_cleanup=Recorder())
    dialog = prefs.open_cleanup()
    select(dialog, "application_logs")
    dialog.submit(dialog.selected_ids())

    assert dialog.winfo_exists()
    assert prefs.winfo_exists()
    assert str(dialog.button_review.cget("state")) == "normal"
    assert str(dialog.button_cancel.cget("state")) != "disabled"


def test_a_callback_that_raises_still_fails_closed(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    before = snapshot(fake)

    def exploding(_request):
        raise RuntimeError("coordinator unavailable")

    dialog = make_cleanup(fresh_root, fake, start_cleanup=exploding)
    select(dialog, "application_logs")
    assert dialog.submit(dialog.selected_ids()) is False
    assert dialog.var_status.get().startswith(maintenance.CLEANUP_FAILED_MESSAGE)
    assert dialog.winfo_exists()
    assert snapshot(fake) == before


def test_reviewing_with_nothing_selected_does_nothing(fresh_root, tmp_path):
    recorder = Recorder()
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), start_cleanup=recorder)
    assert dialog.review_selection() is False
    assert recorder.requests == []
    assert toplevels(dialog) == []


def test_nothing_on_disk_changes_across_a_whole_accepted_flow(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    before = snapshot(fake)
    listing = sorted(str(p.relative_to(fake)) for p in fake.rglob("*"))
    recorder = Recorder(accepts=True)

    dialog = make_cleanup(fresh_root, fake, start_cleanup=recorder)
    dialog.apply_measured(maintenance.inventory(fake))
    select(dialog, *maintenance.ASSET_IDS)
    window = dialog.build_confirmation()
    window.confirm()
    dialog.submit(dialog.selected_ids())

    assert snapshot(fake) == before
    assert sorted(str(p.relative_to(fake)) for p in fake.rglob("*")) == listing
    assert not list(tmp_path.glob("**/*cleanup*"))
    assert not list(tmp_path.glob("**/*request*"))
    assert not list(tmp_path.glob("**/maintenance*"))


# --------------------------------------------------------------------------- #
# Background inventory
# --------------------------------------------------------------------------- #


def test_the_size_walk_runs_off_the_tk_thread(fresh_root, tmp_path):
    import threading

    fake = fake_root(tmp_path)
    seen: list[str] = []
    real = maintenance.inventory

    def watching(root, *, measure=True):
        if measure:
            seen.append(threading.current_thread().name)
        return real(root, measure=measure)

    original = maintenance.inventory
    maintenance.inventory = watching
    try:
        dialog = make_cleanup(fresh_root, fake, measure=True)
        dialog._worker.join(timeout=5)
    finally:
        maintenance.inventory = original
    assert seen, "the measured inventory never ran"
    assert all(name != "MainThread" for name in seen)


def test_measured_sizes_reach_the_rows_through_the_main_thread(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    dialog = make_cleanup(fresh_root, fake, measure=True)
    dialog._worker.join(timeout=5)
    for _ in range(200):
        dialog._poll()
        if dialog._rows["portable_binaries"]["size"].cget("text") != (
            maintenance.CALCULATING_TEXT
        ):
            break
    assert dialog._rows["portable_binaries"]["size"].cget("text") == (
        maintenance.format_bytes(BIN_BYTES)
    )


def test_closing_during_inventory_updates_no_destroyed_widget(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    dialog = make_cleanup(fresh_root, fake, measure=True)
    dialog.close()
    assert dialog._closed is True
    assert dialog._after_id is None
    # Both entry points must be no-ops now, not tracebacks.
    dialog._poll()
    dialog.apply_measured(maintenance.inventory(fake))
    assert not dialog.winfo_exists()
    dialog._worker.join(timeout=5)


def test_a_failing_inventory_is_reported_not_raised(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), measure=False)
    dialog._queue.put(("error", OSError("nope")))
    dialog._poll()
    assert dialog.status_kind == "error"
    assert "Nothing was changed" in dialog.var_status.get()
    assert dialog.winfo_exists()


# --------------------------------------------------------------------------- #
# Styling, isolation and fit
# --------------------------------------------------------------------------- #


def test_a_themeless_bundle_produces_unstyled_widgets(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), theme={})
    assert str(dialog.button_review.cget("style")) == ""
    assert str(dialog.button_cancel.cget("style")) == ""
    window = select(dialog, "application_logs").build_confirmation()
    assert str(window.btn_confirm.cget("style")) == ""
    assert str(window.btn_cancel.cget("style")) == ""


@windows_only
def test_every_windows_cleanup_widget_names_an_act_style(fresh_root, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    theme = ui_theme.apply_theme(fresh_root, ttk.Style(fresh_root))
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), theme=theme)
    window = select(dialog, "application_logs").build_confirmation()

    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)

    styled = 0
    for top in (dialog, window):
        for widget in walk(top):
            try:
                name = str(widget.cget("style"))
            except tk.TclError:
                continue
            if name:
                assert name.startswith(ui_theme.WINDOWS_STYLE_PREFIX + "."), name
                styled += 1
    assert styled > 10


@windows_only
def test_building_the_cleanup_dialogs_leaves_generic_styles_untouched(
    fresh_root, tmp_path, monkeypatch
):
    monkeypatch.setattr(sys, "platform", "win32")
    style = ttk.Style(fresh_root)
    theme = ui_theme.apply_theme(fresh_root, style)

    def sample():
        return {n: (style.layout(n), style.configure(n), style.map(n),
                    style.lookup(n, "background"), style.lookup(n, "foreground"))
                for n in GENERIC_STYLES}

    before = sample()
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), theme=theme)
    select(dialog, "application_logs").build_confirmation()
    changed = [n for n in GENERIC_STYLES if before[n] != sample()[n]]
    assert not changed, f"cleanup leaked into generic styles: {changed}"


def test_the_five_unconverted_panels_still_carry_no_act_style():
    for relative in UNCONVERTED_PANELS:
        source = (REPO_ROOT / "scripts" / "Universal" / relative).read_text(
            encoding="utf-8"
        )
        assert "ACT." not in source, relative


def test_the_cleanup_dialog_fits_inside_the_supported_minimum(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path))
    dialog.update_idletasks()
    assert dialog.winfo_reqwidth() <= 920
    assert dialog.winfo_reqheight() <= 600


@windows_only
def test_the_windows_cleanup_dialog_fits_inside_the_supported_minimum(
    fresh_root, tmp_path, monkeypatch
):
    """The Windows build is the tall one; measuring only the unstyled one hides it."""
    monkeypatch.setattr(sys, "platform", "win32")
    theme = ui_theme.apply_theme(fresh_root, ttk.Style(fresh_root))
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), theme=theme)
    dialog.apply_measured(maintenance.inventory(dialog._repo_root))
    dialog.update_idletasks()
    width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
    assert width <= 920, f"the Windows cleanup dialog is {width}px wide"
    assert height <= 600, f"the Windows cleanup dialog is {height}px tall"


@windows_only
def test_the_windows_confirmation_fits_with_everything_selected(
    fresh_root, tmp_path, monkeypatch
):
    monkeypatch.setattr(sys, "platform", "win32")
    theme = ui_theme.apply_theme(fresh_root, ttk.Style(fresh_root))
    fake = fake_root(tmp_path)
    dialog = make_cleanup(fresh_root, fake, theme=theme, measure=False)
    dialog.apply_measured(maintenance.inventory(fake))
    window = select(dialog, *maintenance.ASSET_IDS).build_confirmation()
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    assert width <= 920, f"the Windows confirmation is {width}px wide"
    assert height <= 600, f"the Windows confirmation is {height}px tall"


@windows_only
def test_every_primary_cleanup_action_is_reachable_at_the_minimum(
    fresh_root, tmp_path, monkeypatch
):
    """The actions cannot be pushed out of view as the item list grows.

    Absolute widget positions are unobservable here — an unmapped toplevel
    reports zeros from both ``winfo_rootx`` and ``winfo_y`` — so the layout
    contract is asserted instead, together with the whole dialog fitting inside
    920x600 (proved by the two tests above). Only the item region carries grid
    weight, so extra height is absorbed there and the footer stays pinned below
    it rather than being displaced off the bottom edge.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    theme = ui_theme.apply_theme(fresh_root, ttk.Style(fresh_root))
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), theme=theme)
    dialog.apply_measured(maintenance.inventory(dialog._repo_root))
    dialog.update_idletasks()

    outer = dialog.item_frame.nametowidget(dialog.item_frame.winfo_parent())
    footer = dialog.button_cancel.nametowidget(dialog.button_cancel.winfo_parent())
    item_row = int(dialog.item_frame.grid_info()["row"])
    footer_row = int(footer.grid_info()["row"])
    assert footer_row > item_row, "the actions must sit below the item list"

    weighted = [r for r in range(footer_row + 1)
                if int(outer.grid_rowconfigure(r).get("weight", 0)) > 0]
    assert weighted == [item_row], f"only the item list may grow, not {weighted}"

    for widget in (dialog.button_cancel, dialog.button_review, dialog.label_status):
        assert widget.winfo_reqwidth() <= 920
        assert widget.winfo_reqheight() <= 600
        assert widget.grid_info(), f"{widget} is not laid out"
    assert dialog.winfo_reqwidth() <= 920 and dialog.winfo_reqheight() <= 600


def test_the_window_constants_are_unchanged():
    assert ui_theme.MIN_SIZE == (920, 600)
    assert ui_theme.DEFAULT_GEOMETRY == "1024x720"


# --------------------------------------------------------------------------- #
# Phase 6 boundary guards
# --------------------------------------------------------------------------- #


def ui_tree():
    return ast.parse(Path(preferences_ui.__file__).read_text(encoding="utf-8"))


def test_the_preferences_module_calls_no_destructive_or_process_primitive():
    """The Phase 2 guard, moved to the Phase 7 boundary rather than relaxed.

    Preferences may now open a cleanup review and hand off a request, but it
    still may not delete, spawn, persist or close anything itself.
    """
    tree = ui_tree()
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    called |= {n.func.id for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    for destructive in ("rmtree", "unlink", "remove", "rmdir", "removedirs",
                        "Popen", "system", "spawnv", "execv", "startfile",
                        "write_text", "write_bytes", "quit"):
        assert destructive not in called, destructive


def test_the_preferences_module_imports_no_deletion_or_process_library():
    tree = ui_tree()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    for forbidden in ("shutil", "subprocess", "os", "multiprocessing", "signal",
                      "atexit"):
        assert forbidden not in imported, forbidden


def test_no_coordinator_persistence_or_post_exit_behaviour_exists():
    tree = ui_tree()
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for phase_seven in ("run_cleanup", "execute_cleanup", "schedule_cleanup",
                        "delete_assets", "write_request", "persist_request",
                        "consume_request", "wait_for_exit", "CleanupCoordinator",
                        "CleanupWorker"):
        assert phase_seven not in defined, phase_seven

    source = Path(preferences_ui.__file__).read_text(encoding="utf-8")
    for phase_seven in ("maintenance-state", "cleanup-request", "post-exit cleanup "
                        "started", ".act-cleanup"):
        assert phase_seven not in source, phase_seven


def test_the_dialog_never_closes_the_application():
    """Phase 7 closes the app after handing off; Phase 6 must not."""
    tree = ui_tree()
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for exiting in ("quit", "exit", "destroy_root", "shutdown"):
        assert exiting not in called, exiting


def test_the_launcher_still_carries_no_cleanup_behaviour():
    source = (REPO_ROOT / "scripts" / "Universal" / "launcher.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for destructive in ("rmtree", "unlink", "rmdir"):
        assert destructive not in called
    assert "CleanupRequest" not in source
    assert "maintenance" not in source


def test_bootstrap_and_the_root_launchers_are_untouched_by_phase_six():
    bootstrap = (REPO_ROOT / "scripts" / "Universal" / "shared" / "bootstrap.py").read_text(
        encoding="utf-8"
    )
    for phase_seven in ("cleanup_request", "CleanupRequest", "maintenance",
                        "clear_downloaded_data", "post_exit"):
        assert phase_seven not in bootstrap, phase_seven
    for launcher in ("Setup_and_Run-audiobook-creation-tool.bat",
                     "Setup_and_Run-audiobook-creation-tool.command"):
        text = (REPO_ROOT / launcher).read_text(encoding="utf-8", errors="replace")
        for phase_seven in ("cleanup", "maintenance"):
            assert phase_seven not in text.lower(), f"{launcher}: {phase_seven}"


def test_no_call_site_in_this_module_uses_the_real_repository_root():
    """Structural self-check: every dialog here is built on a disposable root."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in {"CleanupDialog", "PreferencesDialog", "make_cleanup",
                        "inventory", "estimate_size"}:
            continue
        for argument in list(call.args) + [k.value for k in call.keywords]:
            assert not any(
                isinstance(n, ast.Name) and n.id == "REPO_ROOT"
                for n in ast.walk(argument)
            ), f"{name}() was handed the real repository root"


def test_the_dialog_requires_an_explicit_root_in_the_suite():
    import inspect

    signature = inspect.signature(preferences_ui.CleanupDialog.__init__)
    assert "repo_root" in signature.parameters
    assert signature.parameters["repo_root"].default is None      # production default


def test_existing_preferences_behaviour_is_unchanged(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    prefs = preferences_ui.PreferencesDialog(
        fresh_root, {}, confirm=lambda *_a: True,
        ask_directory=lambda: str(tmp_path / "chosen"), repo_root=fake,
    )
    (tmp_path / "chosen").mkdir()
    prefs.browse()
    assert prefs.save_output_base() is True
    assert config.get_effective().output.is_default is False
    assert prefs.reset_preferences() is True
    assert config.get_effective().output.is_default is True
    assert snapshot(fake)                       # the fake root still has its files


def test_the_application_version_is_still_unchanged():
    from shared.version import VERSION

    assert VERSION == "0.5.1"
