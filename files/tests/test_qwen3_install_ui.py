"""v0.6.7 CP6 — the "Install / repair Qwen3 voices" dialog.

The owner's rulings for acquisition (Q2): independent CustomVoice/Base installs plus "Install Both", sizes shown before
anything is acquired, nothing downloaded on ordinary launch, and one route that serves first-time and existing users.
Two layers are tested separately: ``SetupSession`` (no Tk) and the window built on it. The installer itself is replaced
by fakes -- ``test_qwen3_setup.py`` covers what it really does.
"""

from __future__ import annotations

import ast
import sys
import threading
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from tts import qwen3_install_ui as ui  # noqa: E402
from tts import qwen3_runtime as rt  # noqa: E402
from tts import qwen3_setup as su  # noqa: E402

from test_qwen3_runtime import install_environment, install_model, sandbox  # noqa: E402,F401
from test_tts_importing import tk_root  # noqa: E402,F401


def wait_for(predicate, message, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(message)


class FakeOperation:
    """Stands in for ``su.install`` / ``su.repair``: reports progress, honours cancel, returns a result."""

    def __init__(self, *, ok=True, message="done", steps=3, hold=None):
        self.calls: list[tuple] = []
        self.ok, self.message, self.steps, self.hold = ok, message, steps, hold

    def __call__(self, components, *, progress=None, cancel_check=None, **kwargs):
        self.calls.append(tuple(components))
        self.kwargs = kwargs
        for n in range(self.steps):
            progress(su.Progress("model:customvoice", f"step {n}", n + 1, self.steps))
            if self.hold is not None:
                self.hold.wait(5)
            if cancel_check():
                return su.SetupResult(False, "Cancelled. What was completed is kept.", cancelled=True)
        return su.SetupResult(self.ok, self.message)


# --------------------------------------------------------------------------- #
# The session (no Tk)
# --------------------------------------------------------------------------- #
def test_the_session_runs_the_operation_on_a_thread_and_reports_progress_then_exactly_one_result(monkeypatch):
    operation = FakeOperation()
    monkeypatch.setattr(su, "install", operation)
    session = ui.SetupSession()
    assert session.start_install(["both"]) is True
    wait_for(lambda: not session.running, "the operation never finished")
    events = session.drain()
    assert [kind for kind, _ in events] == ["progress", "progress", "progress", "done"]
    assert events[-1][1].ok and events[-1][1].message == "done" and operation.calls == [("both",)]
    assert session.drain() == []


def test_only_one_operation_runs_at_a_time_and_an_empty_request_does_nothing(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(su, "install", FakeOperation(hold=gate))
    session = ui.SetupSession()
    assert session.start_install([]) is False
    assert session.start_install(["base"]) is True
    assert session.start_install(["customvoice"]) is False and session.running
    gate.set()
    wait_for(lambda: not session.running, "never finished")


def test_cancelling_reaches_the_installers_cancel_check_and_keeps_the_result(monkeypatch):
    gate = threading.Event()
    operation = FakeOperation(hold=gate, steps=10)
    monkeypatch.setattr(su, "install", operation)
    session = ui.SetupSession()
    session.start_install(["customvoice"])
    wait_for(lambda: session.events.qsize() >= 1, "no progress")
    session.cancel()
    gate.set()
    wait_for(lambda: not session.running, "never finished")
    assert session.drain()[-1][1].cancelled is True


def test_an_unexpected_exception_still_produces_a_result_for_the_dialog(monkeypatch):
    def explode(components, **kwargs):
        raise RuntimeError("something nobody planned for")

    monkeypatch.setattr(su, "install", explode)
    session = ui.SetupSession()
    session.start_install(["customvoice"])
    wait_for(lambda: not session.running, "never finished")
    kind, result = session.drain()[-1]
    assert kind == "done" and not result.ok and "something nobody planned for" in result.message


def test_a_session_can_run_again_after_cancelling(monkeypatch):
    operation = FakeOperation()
    monkeypatch.setattr(su, "install", operation)
    session = ui.SetupSession()
    session.cancel()
    session.start_install(["base"])  # the stale cancel flag from before must not poison the new run
    wait_for(lambda: not session.running, "never finished")
    assert session.drain()[-1][1].ok


def make_plan(*, rebuild=False, bad=None):
    bad = {"base": [("model.safetensors", rt.BAD_HASH)]} if bad is None else bad
    return su.RepairPlan(tuple(bad), rebuild, "the engine does not start" if rebuild else "", bad, {})


def test_the_analysis_defaults_to_the_models_that_have_a_folder_and_reports_a_plan_then_one_result(sandbox, monkeypatch):
    seen = []
    plan = make_plan()

    def fake_analysis(components, *, progress=None, cancel_check=None, **kwargs):
        seen.append(tuple(components))
        progress(su.Progress("model:base", "Checking the Base model...", 5, 10))
        return plan

    monkeypatch.setattr(su, "analyze_repair", fake_analysis)
    install_model(sandbox, "base")
    session = ui.SetupSession()
    assert ui.installed_or_partial_components() == ["base"]
    assert session.start_analysis() is True
    wait_for(lambda: not session.running, "never finished")
    events = session.drain()
    assert seen == [("base",)] and [kind for kind, _ in events] == ["progress", "analysis", "done"]
    assert events[1][1] is plan and events[2][1].ok


def test_repair_runs_exactly_the_plan_the_user_confirmed(monkeypatch):
    operation = FakeOperation()
    monkeypatch.setattr(su, "repair", operation)
    session = ui.SetupSession()
    plan = make_plan()
    assert session.start_repair(plan) is True
    wait_for(lambda: not session.running, "never finished")
    assert operation.calls == [("base",)] and operation.kwargs["plan"] is plan
    assert session.drain()[-1][1].ok


def test_a_failure_while_analysing_is_a_result_not_a_crash(monkeypatch):
    def explode(components, **kwargs):
        raise su.SetupError("The Qwen3 model list is invalid: a file name is not allowed.")

    monkeypatch.setattr(su, "analyze_repair", explode)
    session = ui.SetupSession()
    session.start_analysis(["base"])
    wait_for(lambda: not session.running, "never finished")
    kind, result = session.drain()[-1]
    assert kind == "done" and not result.ok and "model list is invalid" in result.message


def test_cancelling_during_the_analysis_is_a_cancelled_result(monkeypatch):
    def cancelled(components, **kwargs):
        raise su.SetupCancelled()

    monkeypatch.setattr(su, "analyze_repair", cancelled)
    session = ui.SetupSession()
    session.start_analysis(["base"])
    wait_for(lambda: not session.running, "never finished")
    assert session.drain()[-1][1].cancelled is True


def test_the_session_never_touches_tk():
    """The worker thread reports through a queue; any widget access from it would be a threading bug."""
    tree = ast.parse(Path(ui.__file__).read_text("utf-8"))
    session_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SetupSession")
    names = {n.id for n in ast.walk(session_class) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(session_class) if isinstance(n, ast.Attribute)}
    assert not names & {"tk", "ttk", "tkinter", "messagebox"}
    assert not attrs & {"after", "winfo_exists", "configure", "grid", "pack", "title"}  # (Event.set is not a widget call)


# --------------------------------------------------------------------------- #
# What the dialog says
# --------------------------------------------------------------------------- #
def test_the_buttons_carry_the_real_sizes():
    labels = ui.button_labels()
    assert labels == {"customvoice": "Install CustomVoice (4.5 GB)", "base": "Install Base (4.5 GB)",
                      "both": "Install Both (8.4 GB)"}  # the 687 MB the two share is counted once


def test_state_lines_describe_the_engine_each_model_and_where_it_will_run(sandbox):
    text = "\n".join(ui.state_lines())
    assert "Voice engine: The Qwen3 voice engine is not installed" in text
    assert "CustomVoice model (Qwen3 - Aiden and Qwen3 - Ryan): The Qwen3 CustomVoice model" in text
    assert "Base model (the six cloned voices)" in text and "No NVIDIA GPU" in text
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    text = "\n".join(ui.state_lines())
    assert "Voice engine: installed." in text and "CustomVoice model (Qwen3 - Aiden and Qwen3 - Ryan): installed." in text


def test_state_lines_name_the_preset_voices_by_their_current_registry_labels(sandbox, monkeypatch):
    """v0.7.0 P02A: renaming a registry row renames it in the installer too; no fixed voice name remains."""
    from dataclasses import replace

    from tts import voice_registry as vr

    renamed = {"qwen3-aiden": "Preset One", "qwen3-ryan": "Preset Two"}
    monkeypatch.setattr(vr, "VOICES", [replace(v, display_label=renamed.get(v.voice_id, v.display_label))
                                       for v in vr.VOICES])
    text = "\n".join(ui.state_lines())
    assert "CustomVoice model (Preset One and Preset Two):" in text
    assert "Aiden" not in text and "Ryan" not in text


def test_on_an_unsupported_platform_the_dialog_says_so_and_nothing_else(sandbox, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert ui.state_lines() == [rt.platform_reason()]


# --------------------------------------------------------------------------- #
# The window
# --------------------------------------------------------------------------- #
@pytest.fixture()
def dialog(tk_root, sandbox):
    made = []

    def build(**kwargs):
        kwargs.setdefault("confirm", lambda parent, title, text: True)
        win = ui.build_dialog(tk_root, **kwargs)
        made.append(win)
        return win

    yield build
    for win in made:
        try:
            win.destroy()
        except tk.TclError:
            pass


def enabled(button) -> bool:
    return str(button.cget("state")) != "disabled"


def test_a_fresh_dialog_offers_the_three_installs_and_no_repair_cancel_is_off(dialog):
    win = dialog()
    assert win.title() == "Install / repair Qwen3 voices"
    assert all(enabled(b) for b in (win.btn_customvoice, win.btn_base, win.btn_both))
    assert not enabled(win.btn_repair) and not enabled(win.btn_cancel) and enabled(win.btn_close)
    assert win.btn_customvoice.cget("text") == ui.button_labels()["customvoice"]
    assert "not installed" in win.state_var.get()


def test_installed_things_are_not_offered_again_and_repair_becomes_available(dialog, sandbox):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    win = dialog()
    assert not enabled(win.btn_customvoice) and enabled(win.btn_base) and enabled(win.btn_both)
    assert enabled(win.btn_repair)
    install_model(sandbox, "base")
    win.refresh()
    assert not enabled(win.btn_both) and enabled(win.btn_repair)


def test_nothing_is_offered_on_a_platform_where_the_voices_are_not_yet_available(dialog, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    win = dialog()
    assert not any(enabled(b) for b in (win.btn_customvoice, win.btn_base, win.btn_both, win.btn_repair))
    assert rt.platform_reason() in win.state_var.get()


def test_pressing_install_asks_first_with_the_sizes_and_declining_starts_nothing(dialog, monkeypatch):
    asked = []
    started = []
    session = ui.SetupSession()
    monkeypatch.setattr(session, "start_install", lambda components: started.append(components) or True)
    win = dialog(session=session, confirm=lambda parent, title, text: asked.append((title, text)) or False)
    win.btn_both.invoke()
    assert len(asked) == 1 and started == []
    title, text = asked[0]
    assert title == "Install Qwen3 voices"
    assert "Qwen3 voice engine:" in text  # the one-off engine download is stated too, not only the models
    assert "CustomVoice model" in text and "Base model" in text and "shared with the other model" in text
    assert "Total to download:" in text and "Disk space needed:" in text and "cancel at any time" in text


def test_confirming_starts_exactly_the_chosen_components_and_locks_the_other_actions(dialog, monkeypatch):
    gate = threading.Event()
    operation = FakeOperation(hold=gate)
    monkeypatch.setattr(su, "install", operation)
    win = dialog()
    win.btn_base.invoke()
    wait_for(lambda: operation.calls, "the install never started")
    assert operation.calls == [("base",)]
    assert not any(enabled(b) for b in (win.btn_customvoice, win.btn_base, win.btn_both, win.btn_repair, win.btn_close))
    assert enabled(win.btn_cancel)
    gate.set()
    wait_for(lambda: not win.session.running, "never finished")


def test_the_dialog_draws_progress_and_the_final_result_and_tells_the_panel(dialog, monkeypatch):
    changes = []
    session = ui.SetupSession()
    win = dialog(session=session, on_change=lambda: changes.append(1))
    session.events.put(("progress", su.Progress("model:base", "Downloading model.safetensors (3.9 GB)...", 250, 1000)))
    win.poll()
    assert win.message_var.get() == "Downloading model.safetensors (3.9 GB)..."
    assert int(float(win.progress["value"])) == 250
    session.events.put(("progress", su.Progress("environment", "Collecting torch")))  # an unmeasured step keeps the bar
    win.poll()
    assert win.message_var.get() == "Collecting torch" and int(float(win.progress["value"])) == 250
    session.events.put(("done", su.SetupResult(True, "The Qwen3 voices you selected are installed.")))
    win.poll()
    assert win.message_var.get() == "The Qwen3 voices you selected are installed."
    assert int(float(win.progress["value"])) == 1000 and changes == [1]
    assert enabled(win.btn_close) and not enabled(win.btn_cancel)


def test_a_failed_install_leaves_the_bar_where_it_was_and_shows_the_reason(dialog):
    session = ui.SetupSession()
    win = dialog(session=session)
    session.events.put(("progress", su.Progress("model:base", "Downloading...", 100, 1000)))
    session.events.put(("done", su.SetupResult(False, "Could not download model.safetensors after 5 attempts.")))
    win.poll()
    assert "after 5 attempts" in win.message_var.get() and int(float(win.progress["value"])) == 100


def test_cancel_asks_the_session_to_stop(dialog, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(su, "install", FakeOperation(hold=gate, steps=5))
    win = dialog()
    win.btn_customvoice.invoke()
    wait_for(lambda: win.session.running, "never started")
    win.btn_cancel.invoke()
    assert win.message_var.get() == "Cancelling..." and not enabled(win.btn_cancel)
    gate.set()
    wait_for(lambda: not win.session.running, "never stopped")
    win.poll()
    assert "Cancelled" in win.message_var.get()


def test_closing_while_running_stops_the_work_first_and_closes_once_it_has_stopped(dialog, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(su, "install", FakeOperation(hold=gate, steps=5))
    win = dialog()
    win.btn_customvoice.invoke()
    wait_for(lambda: win.session.running, "never started")
    win.close_request()
    assert win.winfo_exists(), "the window stays while the work winds down"
    gate.set()
    wait_for(lambda: not win.session.running, "never stopped")
    win.poll()
    assert not win.winfo_exists()


def test_closing_an_idle_dialog_closes_it_and_leaves_no_pending_poll(dialog):
    win = dialog()
    win.close_request()
    assert not win.winfo_exists()


def test_repair_with_nothing_installed_says_so_instead_of_starting(dialog, monkeypatch):
    operation = FakeOperation()
    monkeypatch.setattr(su, "repair", operation)
    win = dialog()
    win.btn_repair.configure(state="normal")  # (it is disabled by itself; prove the handler is safe regardless)
    win.btn_repair.invoke()
    assert win.message_var.get() == "Nothing is installed yet, so there is nothing to repair." and operation.calls == []


def drive_until_idle(win, limit=10.0):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        win.poll()
        if not win.session.running and win.session.events.empty():
            return
        time.sleep(0.02)
    raise AssertionError("the dialog never went idle")


def test_check_and_repair_checks_first_shows_what_a_repair_would_download_and_acts_only_on_a_yes(dialog, sandbox, monkeypatch):
    install_environment(sandbox)
    install_model(sandbox, "base")
    plan = make_plan(rebuild=True)
    monkeypatch.setattr(su, "analyze_repair", lambda components, **k: plan)
    operation = FakeOperation()
    monkeypatch.setattr(su, "repair", operation)
    asked = []
    win = dialog(confirm=lambda parent, title, text: asked.append((title, text)) or True)
    win.btn_repair.invoke()
    assert operation.calls == [], "the check is read-only: nothing is repaired before the user has seen what it found"
    drive_until_idle(win)
    assert len(asked) == 1
    title, text = asked[0]
    assert title == "Repair Qwen3 voices"
    assert "Qwen3 voice engine: needs to be rebuilt" in text and "Base model: 1 of 3 files" in text
    assert "Total to download:" in text and "Repair now? You can cancel at any time." in text
    wait_for(lambda: operation.calls, "the confirmed repair never started")
    assert operation.calls == [("base",)] and operation.kwargs["plan"] is plan
    drive_until_idle(win)


def test_declining_the_repair_changes_nothing(dialog, sandbox, monkeypatch):
    install_environment(sandbox)
    install_model(sandbox, "base")
    monkeypatch.setattr(su, "analyze_repair", lambda components, **k: make_plan())
    operation = FakeOperation()
    monkeypatch.setattr(su, "repair", operation)
    win = dialog(confirm=lambda *a: False)
    win.btn_repair.invoke()
    drive_until_idle(win)
    assert operation.calls == [] and win.message_var.get() == "Nothing was changed."
    assert enabled(win.btn_repair) and enabled(win.btn_close)


def test_a_clean_check_says_so_and_asks_nothing(dialog, sandbox, monkeypatch):
    install_environment(sandbox)
    install_model(sandbox, "base")
    monkeypatch.setattr(su, "analyze_repair", lambda components, **k: make_plan(bad={"base": []}))
    asked = []
    win = dialog(confirm=lambda *a: asked.append(a) or True)
    win.btn_repair.invoke()
    drive_until_idle(win)
    assert asked == [] and win.message_var.get() == "Everything checks out. Nothing needs repair."


def test_an_engine_with_no_models_can_still_be_checked_and_repaired(dialog, sandbox, monkeypatch):
    """Codex finding: repair was enabled for an engine-only install but then refused with 'nothing is installed'."""
    install_environment(sandbox)
    assert ui.installed_or_partial_components() == []
    seen = []
    monkeypatch.setattr(su, "analyze_repair", lambda components, **k: seen.append(tuple(components)) or make_plan(
        rebuild=True, bad={}))
    operation = FakeOperation()
    monkeypatch.setattr(su, "repair", operation)
    win = dialog()
    assert enabled(win.btn_repair)
    win.btn_repair.invoke()
    drive_until_idle(win)
    wait_for(lambda: operation.calls == [()], "the engine-only repair never started")
    assert seen == [()]
    drive_until_idle(win)


def test_a_check_that_fails_is_reported_and_the_dialog_stays_usable(dialog, sandbox, monkeypatch):
    install_environment(sandbox)
    install_model(sandbox, "base")

    def broken(components, **kwargs):
        raise su.SetupError("The Qwen3 voices are already being installed or repaired.")

    monkeypatch.setattr(su, "analyze_repair", broken)
    win = dialog()
    win.btn_repair.invoke()
    drive_until_idle(win)
    assert "already being installed or repaired" in win.message_var.get() and enabled(win.btn_close)


def test_at_most_one_poll_is_ever_outstanding_even_when_closing_during_a_run(dialog, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(su, "install", FakeOperation(hold=gate, steps=5))
    win = dialog()
    scheduled, cancelled = [], []
    real_after = win.after
    win.after = lambda ms, fn: scheduled.append(fn) or f"poll-{len(scheduled)}"
    win.after_cancel = lambda handle: cancelled.append(handle)
    win.btn_customvoice.invoke()
    wait_for(lambda: win.session.running, "never started")
    win.close_request()
    win.close_request()
    assert len(scheduled) == 1, "closing during a run must not start a second poll chain"
    gate.set()
    wait_for(lambda: not win.session.running, "never stopped")
    scheduled.pop(0)()  # the single outstanding poll fires: it sees the result and closes the window
    assert not win.winfo_exists()
    win.after = real_after


def test_when_everything_is_already_installed_no_confirmation_is_asked(dialog, sandbox):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    asked = []
    win = dialog(confirm=lambda *a: asked.append(a) or True)
    win.btn_customvoice.configure(state="normal")  # disabled by itself; prove the handler is safe regardless
    win.btn_customvoice.invoke()
    assert asked == [] and win.message_var.get() == "Everything you selected is already installed."


def test_an_install_that_cannot_even_be_planned_is_reported_not_raised(dialog, monkeypatch):
    def broken(components):
        raise su.SetupError("The Qwen3 requirements file is missing from this copy of the app.")

    session = ui.SetupSession()
    monkeypatch.setattr(session, "prepare_install", broken)
    win = dialog(session=session)
    win.btn_both.invoke()
    assert "requirements file is missing" in win.message_var.get()


def test_the_dialog_states_that_nothing_is_downloaded_until_asked_and_where_things_live(dialog):
    win = dialog()
    texts = []

    def walk(widget):
        for child in widget.winfo_children():
            try:
                texts.append(str(child.cget("text")))
            except tk.TclError:
                pass
            walk(child)

    walk(win)
    joined = " ".join(texts)
    assert "Nothing is downloaded until you press one of these buttons and confirm" in joined
    assert ".venv-qwen3" in joined and "files/runtime-data/models/qwen3-tts" in joined
