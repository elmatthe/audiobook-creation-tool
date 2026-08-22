"""v0.6.0 Drop 2 Phase 7 — the GUI handoff and the next-launch report.

Every dialog here is built against a disposable fake repository root in
``tmp_path``, and every handoff is injected. No test in this file starts a real
coordinator, and none of them points the production dialog at the maintainer's
real project — so the real ``.venv``, ``files/bin``,
``files/runtime-data/models``, ``files/runtime-data/logs`` and ``settings.json``
are never inventoried, written to or removed. A structural test at the end
proves no call site passes the real root.
"""

from __future__ import annotations

import ast
import gc
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import cleanup_state as state  # noqa: E402
from shared import config, maintenance, preferences_ui  # noqa: E402
from shared import settings as app_settings  # noqa: E402
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UTC = timezone.utc


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk, before_destroy=gc.collect)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path):
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
    gc.collect()
    yield tk_root
    for child in tk_root.winfo_children():
        child.destroy()
    gc.collect()


def write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def fake_root(tmp_path: Path) -> Path:
    root = tmp_path / "fake-repo"
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "files" / "runtime-data").mkdir(parents=True, exist_ok=True)
    write(root / "config.toml", b"# fake\n")
    write(root / "files" / "runtime-data" / "settings.json", b"{}")
    write(root / ".venv" / "pyvenv.cfg", b"x" * 500)
    write(root / "files" / "bin" / "ffmpeg.exe", b"y" * 1000)
    write(root / "files" / "runtime-data" / "models" / "m.bin", b"m" * 2048)
    write(root / "files" / "runtime-data" / "logs" / "s.log", b"l" * 50)
    return root


def snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    skip = "/".join(state.STATE_DIR_PARTS) + "/"
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(skip):
            continue
        out[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


class Handoff:
    """An injected handoff that records instead of starting anything."""

    def __init__(self, outcome=None, error=None):
        self.outcome = outcome if outcome is not None else state.HandoffOutcome(False)
        self.error = error
        self.requests: list = []

    def __call__(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.outcome


class Closer:
    """Records that the application was asked to close, without closing it."""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


def make_cleanup(root, fake, *, handoff=None, closer=None):
    return preferences_ui.CleanupDialog(
        root, {}, repo_root=fake, start_cleanup=handoff,
        close_application=closer or Closer(), measure=False, close_delay=0,
    )


def select(dialog, *asset_ids):
    for asset_id in asset_ids:
        dialog._vars[asset_id].set(True)
    dialog._on_selection_change()
    return dialog


# --------------------------------------------------------------------------- #
# Accepting closes the app only after acknowledgement
# --------------------------------------------------------------------------- #


def test_the_application_closes_only_after_a_positive_acknowledgement(fresh_root, tmp_path):
    closer = Closer()
    dialog = make_cleanup(fresh_root, fake_root(tmp_path),
                          handoff=Handoff(state.HandoffOutcome(True)), closer=closer)
    select(dialog, "application_logs")
    assert dialog.submit(dialog.selected_ids()) is True
    assert closer.calls == 1
    assert dialog.var_status.get() == maintenance.CLEANUP_SCHEDULED_MESSAGE


def test_the_success_wording_is_exactly_the_approved_sentence():
    assert maintenance.CLEANUP_SCHEDULED_MESSAGE == (
        "Cleanup is ready. Audiobook Creation Tool will now close, and the selected "
        "downloaded data will be cleared after the app exits."
    )


def test_the_failure_wording_is_exactly_the_approved_sentence():
    assert maintenance.CLEANUP_FAILED_MESSAGE == (
        "Cleanup did not start. No data was changed, and Audiobook Creation Tool "
        "will remain open."
    )


def test_a_refused_handoff_never_closes_the_application(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    before = snapshot(fake)
    closer = Closer()
    dialog = make_cleanup(fresh_root, fake, handoff=Handoff(), closer=closer)
    select(dialog, "application_logs")

    assert dialog.submit(dialog.selected_ids()) is False
    assert closer.calls == 0
    assert dialog.winfo_exists()
    assert snapshot(fake) == before


def test_a_coordinator_that_cannot_start_leaves_the_dialog_usable(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    dialog = make_cleanup(
        fresh_root, fake,
        handoff=Handoff(state.HandoffOutcome(False, "The cleanup helper could not be started.")),
    )
    select(dialog, "application_logs")
    assert dialog.submit(dialog.selected_ids()) is False
    assert dialog.var_status.get().startswith(maintenance.CLEANUP_FAILED_MESSAGE)
    assert "could not be started" in dialog.var_status.get()
    assert str(dialog.button_review.cget("state")) == "normal"
    assert str(dialog.button_cancel.cget("state")) == "normal"


def test_an_acknowledgement_timeout_leaves_everything_untouched(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    before = snapshot(fake)
    closer = Closer()
    dialog = make_cleanup(
        fresh_root, fake, closer=closer,
        handoff=Handoff(state.HandoffOutcome(False, "The cleanup helper did not confirm it was ready.")),
    )
    select(dialog, *maintenance.ASSET_IDS)
    assert dialog.submit(dialog.selected_ids()) is False
    assert "did not confirm" in dialog.var_status.get()
    assert closer.calls == 0
    assert snapshot(fake) == before


def test_a_handoff_that_raises_never_closes_the_application(fresh_root, tmp_path):
    closer = Closer()
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), closer=closer,
                          handoff=Handoff(error=RuntimeError("boom")))
    select(dialog, "application_logs")
    assert dialog.submit(dialog.selected_ids()) is False
    assert closer.calls == 0
    assert dialog.var_status.get() == maintenance.CLEANUP_FAILED_MESSAGE


def test_the_failure_detail_is_appended_to_the_fixed_headline(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path),
                          handoff=Handoff(state.HandoffOutcome(False, "A cleanup is already scheduled.")))
    select(dialog, "application_logs")
    dialog.submit(dialog.selected_ids())
    message = dialog.var_status.get()
    assert message.startswith(maintenance.CLEANUP_FAILED_MESSAGE)
    assert message.endswith("A cleanup is already scheduled.")
    assert "deleted" not in message and "removed" not in message


# --------------------------------------------------------------------------- #
# Double submission
# --------------------------------------------------------------------------- #


def test_a_second_click_cannot_start_a_second_helper(fresh_root, tmp_path):
    handoff = Handoff(state.HandoffOutcome(True))
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), handoff=handoff)
    select(dialog, "application_logs")
    assert dialog.submit(dialog.selected_ids()) is True
    assert dialog.submit(dialog.selected_ids()) is False
    assert len(handoff.requests) == 1


def test_review_is_refused_while_a_handoff_is_in_flight(fresh_root, tmp_path):
    handoff = Handoff(state.HandoffOutcome(True))
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), handoff=handoff)
    select(dialog, "application_logs")
    dialog.submit(dialog.selected_ids())
    assert dialog.review_selection() is False
    assert len(handoff.requests) == 1


def test_the_controls_are_disabled_during_the_wait(fresh_root, tmp_path):
    seen = {}

    def slow(request):
        seen["review"] = str(dialog.button_review.cget("state"))
        seen["cancel"] = str(dialog.button_cancel.cget("state"))
        seen["status"] = dialog.var_status.get()
        return state.HandoffOutcome(True)

    dialog = make_cleanup(fresh_root, fake_root(tmp_path), handoff=slow)
    select(dialog, "application_logs")
    dialog.submit(dialog.selected_ids())
    assert seen["review"] == "disabled"
    assert seen["cancel"] == "disabled"
    assert seen["status"] == maintenance.CLEANUP_PREPARING_MESSAGE


def test_a_failed_handoff_re_enables_the_controls(fresh_root, tmp_path):
    dialog = make_cleanup(fresh_root, fake_root(tmp_path), handoff=Handoff())
    select(dialog, "application_logs")
    dialog.submit(dialog.selected_ids())
    assert dialog._handoff_pending is False
    assert str(dialog.button_review.cget("state")) == "normal"
    assert dialog.submit(dialog.selected_ids()) is False   # allowed to try again


def test_cancelling_before_acceptance_is_always_safe(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    before = snapshot(fake)
    dialog = make_cleanup(fresh_root, fake, handoff=Handoff())
    select(dialog, *maintenance.ASSET_IDS)
    dialog.close()
    assert not dialog.winfo_exists()
    assert snapshot(fake) == before
    assert not state.request_path(fake).exists()


# --------------------------------------------------------------------------- #
# The GUI itself never deletes
# --------------------------------------------------------------------------- #


def test_the_whole_accepted_flow_changes_nothing_on_disk(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    before = snapshot(fake)
    listing = sorted(str(p.relative_to(fake)) for p in fake.rglob("*"))
    dialog = make_cleanup(fresh_root, fake, handoff=Handoff(state.HandoffOutcome(True)))
    dialog.apply_measured(maintenance.inventory(fake))
    select(dialog, *maintenance.ASSET_IDS)
    window = dialog.build_confirmation()
    window.confirm()
    dialog.submit(dialog.selected_ids())

    assert snapshot(fake) == before
    assert sorted(str(p.relative_to(fake)) for p in fake.rglob("*")) == listing


def test_the_request_handed_over_carries_ids_only(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    handoff = Handoff(state.HandoffOutcome(True))
    dialog = make_cleanup(fresh_root, fake, handoff=handoff)
    select(dialog, "virtual_environment", "downloaded_models")
    dialog.submit(dialog.selected_ids())
    payload = maintenance.request_to_dict(handoff.requests[0])
    assert set(payload) == set(maintenance.REQUEST_FIELDS)
    assert str(fake) not in str(payload)


# --------------------------------------------------------------------------- #
# The next-launch report
# --------------------------------------------------------------------------- #


def make_result(statuses, *, freed=64):
    now = datetime.now(UTC)
    return maintenance.CleanupResult(
        schema_version=maintenance.SCHEMA_VERSION,
        request_id="3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        started_at=now, completed_at=now,
        outcomes=tuple(maintenance.AssetOutcome(asset_id, status, freed, "")
                       for asset_id, status in statuses.items()),
    )


class RecordingReport:
    instances: list = []

    def __init__(self, master, result, theme=None):
        RecordingReport.instances.append(result)


@pytest.fixture(autouse=True)
def clear_reports():
    RecordingReport.instances = []
    yield
    RecordingReport.instances = []


def test_nothing_is_shown_when_there_is_no_result(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    assert preferences_ui.present_cleanup_result(
        fresh_root, {}, repo_root=fake, dialog_factory=RecordingReport
    ) is None
    assert RecordingReport.instances == []


def test_a_result_is_presented_exactly_once(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    state.store_result(make_result({"application_logs": "removed"}), fake)

    first = preferences_ui.present_cleanup_result(
        fresh_root, {}, repo_root=fake, dialog_factory=RecordingReport
    )
    second = preferences_ui.present_cleanup_result(
        fresh_root, {}, repo_root=fake, dialog_factory=RecordingReport
    )
    assert first is not None
    assert second is None
    assert len(RecordingReport.instances) == 1


def test_a_corrupt_result_is_never_presented_and_never_executed(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    before = snapshot(fake)
    state.ensure_state_dir(fake)
    state.result_path(fake).write_text("not a result", encoding="utf-8")
    assert preferences_ui.present_cleanup_result(
        fresh_root, {}, repo_root=fake, dialog_factory=RecordingReport
    ) is None
    assert RecordingReport.instances == []
    assert snapshot(fake) == before


def test_the_report_lists_every_outcome(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    state.store_result(make_result({
        "virtual_environment": "removed", "portable_binaries": "missing",
        "downloaded_models": "failed", "application_logs": "refused",
    }), fake)
    preferences_ui.present_cleanup_result(fresh_root, {}, repo_root=fake)
    windows = [w for w in fresh_root.winfo_children()
               if isinstance(w, preferences_ui.CleanupResultDialog)]
    assert len(windows) == 1
    body = windows[0].body_text
    for definition in maintenance.CATALOG:
        assert definition.display_name in body
    assert windows[0].heading_text == maintenance.RESULT_HEADING_PARTIAL
    assert maintenance.RESULT_RECOVERY_LINE in body


def test_a_complete_report_offers_no_recovery_advice(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    state.store_result(make_result({"application_logs": "removed"}), fake)
    preferences_ui.present_cleanup_result(fresh_root, {}, repo_root=fake)
    window = [w for w in fresh_root.winfo_children()
              if isinstance(w, preferences_ui.CleanupResultDialog)][0]
    assert window.heading_text == maintenance.RESULT_HEADING_COMPLETE
    assert maintenance.RESULT_RECOVERY_LINE not in window.body_text


def test_the_report_window_fits_the_supported_minimum(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    state.store_result(make_result({a: "failed" for a in maintenance.ASSET_IDS}), fake)
    preferences_ui.present_cleanup_result(fresh_root, {}, repo_root=fake)
    window = [w for w in fresh_root.winfo_children()
              if isinstance(w, preferences_ui.CleanupResultDialog)][0]
    window.update_idletasks()
    assert window.winfo_reqwidth() <= 920
    assert window.winfo_reqheight() <= 600


def test_a_failure_to_display_keeps_the_record_for_next_time(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    state.store_result(make_result({"application_logs": "removed"}), fake)

    def refuse(master, result, theme=None):
        raise tk.TclError("no display")

    assert preferences_ui.present_cleanup_result(
        fresh_root, {}, repo_root=fake, dialog_factory=refuse
    ) is None
    assert state.load_result(fake) is not None


def test_the_report_is_logged_as_well_as_shown(fresh_root, tmp_path):
    fake = fake_root(tmp_path)
    state.store_result(make_result({"application_logs": "failed"}), fake)
    lines: list = []

    class Log:
        def info(self, message, *args):
            lines.append(message % args)

    preferences_ui.present_cleanup_result(fresh_root, {}, repo_root=fake,
                                          logger=Log(), dialog_factory=RecordingReport)
    assert any("application_logs" in line and "failed" in line for line in lines)


# --------------------------------------------------------------------------- #
# Launcher wiring
# --------------------------------------------------------------------------- #


def launcher_tree():
    return ast.parse((REPO_ROOT / "scripts" / "Universal" / "launcher.py").read_text(
        encoding="utf-8"
    ))


def test_the_launcher_passes_a_way_to_close_the_application():
    source = (REPO_ROOT / "scripts" / "Universal" / "launcher.py").read_text(
        encoding="utf-8"
    )
    assert "close_application=self.close_for_downloaded_data" in source
    assert "def close_for_downloaded_data" in source


def test_the_launcher_reports_the_previous_run_after_it_is_built():
    source = (REPO_ROOT / "scripts" / "Universal" / "launcher.py").read_text(
        encoding="utf-8"
    )
    assert "self.root.after(0, self.present_downloaded_data_report)" in source
    warnings_at = source.index("self.root.after(0, self.present_configuration_warnings)")
    report_at = source.index("self.root.after(0, self.present_downloaded_data_report)")
    assert warnings_at < report_at


def test_the_launcher_never_deletes_or_spawns_for_cleanup():
    tree = launcher_tree()
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for destructive in ("rmtree", "unlink", "remove", "rmdir", "Popen"):
        assert destructive not in called, destructive


def test_the_report_route_can_never_break_a_launch():
    tree = launcher_tree()
    method = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "present_downloaded_data_report")
    handlers = [n for n in ast.walk(method) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "the report must be wrapped in its own failure guard"


# --------------------------------------------------------------------------- #
# Structural guards
# --------------------------------------------------------------------------- #


def test_the_preferences_module_still_starts_nothing_itself():
    tree = ast.parse(Path(preferences_ui.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    for forbidden in ("os", "shutil", "subprocess", "signal", "multiprocessing"):
        assert forbidden not in imported, forbidden


def test_the_preferences_module_never_imports_the_coordinator():
    source = Path(preferences_ui.__file__).read_text(encoding="utf-8")
    assert "cleanup_worker" not in source
    launcher = (REPO_ROOT / "scripts" / "Universal" / "launcher.py").read_text(
        encoding="utf-8"
    )
    assert "cleanup_worker" not in launcher


def test_no_test_in_this_module_touches_the_real_repository():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    entry_points = {"present_cleanup_result", "make_cleanup", "store_result",
                    "CleanupDialog", "PreferencesDialog"}
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in entry_points:
            continue
        for argument in list(call.args) + [k.value for k in call.keywords]:
            assert not any(isinstance(n, ast.Name) and n.id == "REPO_ROOT"
                           for n in ast.walk(argument)), name
