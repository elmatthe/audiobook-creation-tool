"""The setup windows' progress logs follow, hold and resume -- v0.7.2 Phase 6, ACT72-059.

The first-run setup window (``shared/bootstrap.py`` ``run_with_gui``), the
self-heal repair window (``show_repair_dialog``) and the optional-voices step
that the first-run window shows after the base install
(``shared/optional_setup_panel.py``) each keep a live, read-only log. Every one
of them called ``see("end")`` after every line, so a person who scrolled back to
read an earlier line was thrown to the newest line by the next message while
setup was writing (reproduced at ``5170b8f``).

They now use the rule of the app's own Summary | Detailed log (ACT72-005): a
reader at the bottom follows new lines; a reader who scrolled up keeps their
place, to the pixel; returning to the bottom follows again.

The two bootstrap windows are run for real: their own widgets, their own
worker thread, the real ``SetupLog`` -> UI sink -> queue -> ``after`` poll path.
Only two things differ from a user's run: the window is a ``Toplevel`` of the
suite's one Tcl interpreter (``tk_gate``: a second ``tk.Tk()`` in one pytest
process is not safe), and its ``mainloop`` is this test's script, which pumps
the same event loop. The work itself is a stub that writes lines in batches the
test releases, so nothing is installed, downloaded or launched, and the setup
log goes to a temporary folder. The reader's scrolling is the real mouse wheel
through Tk's Text class binding (and, for the panel with a scrollbar, the
``yview moveto`` the scrollbar itself makes).
"""

from __future__ import annotations

import threading
import time

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import bootstrap  # noqa: E402

import tk_gate  # noqa: E402

WAIT = 10.0
#: Long enough to wrap in a word-wrapped log, so the follow rule is exercised on wrapped lines too.
LONG = " -- " + "a long setup message that wraps across the log's width " * 3


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def setup_log(monkeypatch, tmp_path):
    """A fresh SetupLog writing to a temporary folder, never to files/runtime-data/logs."""
    monkeypatch.setattr(bootstrap, "LOGS_DIR", tmp_path / "logs")
    log = bootstrap.SetupLog()
    monkeypatch.setattr(bootstrap, "LOG", log)
    yield log
    log.set_ui_sink(None)
    log.close()


@pytest.fixture
def native_theme(tk_root):
    """Both bootstrap windows switch the ttk theme; put the suite's back afterwards."""
    style = ttk.Style(tk_root)
    theme = style.theme_use()
    yield
    style.theme_use(theme)


class Feed:
    """Lines a setup worker writes, in batches the test releases from the Tk thread."""

    def __init__(self, batches):
        self.batches = [list(batch) for batch in batches]
        self.release = [threading.Event() for _ in self.batches]
        self.release[0].set()
        self.finish = threading.Event()

    def write_all(self, write) -> None:
        """Runs on the worker thread; touches no Tk at all."""
        for index, batch in enumerate(self.batches):
            if not self.release[index].wait(WAIT):
                return
            for line in batch:
                write(line)
        self.finish.wait(WAIT)

    def lines(self) -> list[str]:
        return [line for batch in self.batches for line in batch]

    def let_go(self) -> None:
        for event in self.release:
            event.set()
        self.finish.set()


def _batches():
    first = [f"base step {index:02d}" + (LONG if index % 5 == 0 else "") for index in range(40)]
    second = [f"while reading {index:02d}" + (LONG if index % 7 == 0 else "") for index in range(30)]
    third = [f"after returning {index:02d}" for index in range(10)]
    return first, second, third


def settle(window) -> None:
    window.update_idletasks()
    window.update()


def pump_until(window, condition, what: str) -> None:
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        settle(window)
        if condition():
            return
        time.sleep(0.01)
    pytest.fail(f"never happened: {what}")


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def shown_lines(log) -> list[str]:
    return [line for line in log.get("1.0", "end-1c").split("\n") if line]


def bottom_line(log) -> int:
    """The text line at the pane's bottom pixel row (the last line when the text is shorter than the pane)."""
    return int(log.index(f"@0,{log.winfo_height() - 1}").split(".")[0])


def newest_line(log) -> int:
    """The newest message's line: every message ends with a newline, which leaves an empty last line."""
    return int(log.index("end-1c").split(".")[0]) - 1


def newest_shown(log) -> bool:
    return bottom_line(log) >= newest_line(log)


def view(log) -> tuple[str, int]:
    """Where the reader is: the index at the top-left and that display line's y pixel."""
    return log.index("@0,0"), log.dlineinfo("@0,0")[1]


def wheel(log, notches: int) -> None:
    """The mouse wheel through Tk's own Text binding: positive notches scroll up."""
    log.event_generate("<MouseWheel>", delta=120 * notches, x=20, y=20)
    settle(log.winfo_toplevel())


def record_insert_threads(log) -> list:
    """Every insert into the pane, with the thread that made it (Tk is main-thread only)."""
    threads = []
    original = log.insert

    def insert(*args, **kwargs):
        threads.append(threading.current_thread())
        return original(*args, **kwargs)

    log.insert = insert
    return threads


def follow_hold_resume(window, log, feed: Feed, where: str) -> None:
    """The reader's three moves, judged by what is on screen."""
    first, second, third = feed.batches
    pump_until(window, lambda: shown_lines(log)[-1:] == [first[-1]], f"{where}: the first lines arrive")
    assert newest_shown(log), f"{where}: a reader at the bottom follows"
    assert log.dlineinfo("1.0") is None, f"{where}: the first batch must overflow the pane for this test to mean much"

    wheel(log, 3)
    assert not newest_shown(log), f"{where}: the wheel took the reader up"
    held = view(log)
    feed.release[1].set()
    pump_until(window, lambda: shown_lines(log)[-1:] == [second[-1]], f"{where}: more lines arrive while reading")
    assert view(log) == held, f"{where}: the reader's place moved while they were reading ({held} -> {view(log)})"
    assert not newest_shown(log), f"{where}: the view jumped to the newest line"

    for _ in range(200):
        if newest_shown(log):
            break
        wheel(log, -1)
    assert newest_shown(log), f"{where}: the wheel never reached the bottom"
    feed.release[2].set()
    pump_until(window, lambda: shown_lines(log)[-1:] == [third[-1]], f"{where}: lines arrive after returning")
    assert newest_shown(log), f"{where}: following did not resume at the bottom"


# --------------------------------------------------------------------------- #
# The real bootstrap windows, as Toplevels of the suite's interpreter
# --------------------------------------------------------------------------- #
def run_as_toplevel(monkeypatch, tk_root, script) -> list:
    """Make the window's ``tk.Tk()`` a Toplevel whose ``mainloop`` is *script*."""
    made = []

    class DialogRoot(tk.Toplevel):
        def mainloop(self, n=0):
            try:
                script(self)
            finally:
                deadline = time.monotonic() + WAIT
                while self.winfo_exists() and time.monotonic() < deadline:
                    settle(self)
                    time.sleep(0.01)
                if self.winfo_exists():
                    self.destroy()

    def factory(*_args, **_kwargs):
        window = DialogRoot(tk_root)
        made.append(window)
        return window

    monkeypatch.setattr(tk, "Tk", factory)
    return made


def the_log(window):
    texts = [widget for widget in descendants(window) if isinstance(widget, tk.Text)]
    assert len(texts) == 1, texts
    return texts[0]


def test_the_repair_window_log_follows_holds_a_reader_and_resumes(monkeypatch, tk_root, setup_log, native_theme):
    feed = Feed(_batches())
    seen = {}

    def script(window):
        log = the_log(window)
        seen["inserts"] = record_insert_threads(log)
        try:
            follow_hold_resume(window, log, feed, "repair window")
            seen["lines"] = shown_lines(log)
        finally:
            feed.let_go()

    run_as_toplevel(monkeypatch, tk_root, script)

    def work() -> bool:
        feed.write_all(bootstrap.LOG.line)
        return True

    assert bootstrap.show_repair_dialog(work, title="Repairing", detail="A test repair.") is True
    assert seen["lines"] == feed.lines(), "the log keeps every line, in order"
    assert seen["inserts"] and set(seen["inserts"]) == {threading.main_thread()}, "only the Tk thread writes the log"


def test_the_first_run_window_log_follows_holds_a_reader_and_resumes(monkeypatch, tk_root, setup_log, native_theme):
    feed = Feed(_batches())
    seen = {"launched": 0}

    def run_setup(on_progress, log):
        on_progress(2, "Installing the app's packages")
        feed.write_all(log.line)
        return True, "Setup complete."

    monkeypatch.setattr(bootstrap, "run_setup", run_setup)
    monkeypatch.setattr(bootstrap, "optional_estimates", lambda: {})
    monkeypatch.setattr(bootstrap, "launch_gui", lambda log: seen.__setitem__("launched", seen["launched"] + 1))

    def script(window):
        try:
            begin = next(widget for widget in descendants(window)
                         if isinstance(widget, ttk.Button) and str(widget.cget("text")) == "Begin Setup")
            log = the_log(window)
            seen["inserts"] = record_insert_threads(log)
            begin.invoke()
            follow_hold_resume(window, log, feed, "first-run window")
            bar = next(widget for widget in descendants(window) if isinstance(widget, ttk.Progressbar))
            seen["progress"] = float(bar.cget("value"))
            seen["step"] = next(window.getvar(str(widget.cget("textvariable"))) for widget in descendants(window)
                                if isinstance(widget, ttk.Label) and str(widget.cget("textvariable")))
            seen["lines"] = shown_lines(log)
        finally:
            feed.let_go()

    run_as_toplevel(monkeypatch, tk_root, script)
    assert bootstrap.run_with_gui(skip_kokoro_default=True) == 0
    assert seen["progress"] == 2 and seen["step"] == "Installing the app's packages", "progress is still reported"
    assert seen["lines"] == feed.lines(), "the log keeps every line, in order"
    assert seen["launched"] == 1
    assert seen["inserts"] and set(seen["inserts"]) == {threading.main_thread()}, "only the Tk thread writes the log"


# --------------------------------------------------------------------------- #
# The optional-voices step (shown in the first-run window and by Install & Continue)
# --------------------------------------------------------------------------- #
def test_the_optional_voices_install_log_follows_holds_a_reader_and_resumes(tk_root, tmp_path):
    from shared.optional_setup_panel import OptionalSetupPanel

    window = tk.Toplevel(tk_root)
    window.geometry("760x680")
    feed = Feed(_batches())
    panel = OptionalSetupPanel(window, tmp_path, ["kokoro"], on_done=lambda outcome: None,
                               run_plan=lambda *a, **k: pytest.fail("no plan is made here"),
                               run_install=lambda *a, **k: pytest.fail("nothing is installed here"))
    panel.pack(fill="both", expand=True)
    log = panel.text
    inserts = record_insert_threads(log)

    def worker():
        # What the install worker's on_event does: post to the panel's queue, never touch Tk.
        feed.write_all(lambda line: panel._queue.put(("event", {"kind": "progress", "payload": {"message": line}})))

    thread = threading.Thread(target=worker, daemon=True)
    try:
        settle(window)
        thread.start()
        follow_hold_resume(window, log, feed, "optional-voices panel")
        # The scrollbar's own drag is ``yview moveto``: a reader taken to the top is held there too.
        log.yview_moveto(0.0)
        settle(window)
        held = view(log)
        feed.batches.append([f"after the scrollbar {index}" for index in range(8)])
        for line in feed.batches[-1]:
            panel._queue.put(("event", {"kind": "progress", "payload": {"message": line}}))
        pump_until(window, lambda: shown_lines(log)[-1:] == [feed.batches[-1][-1]], "lines after the scrollbar")
        assert view(log) == held and held[0] == "1.0", "the scrollbar reader was moved"
        assert shown_lines(log) == feed.lines(), "the log keeps every line, in order"
        assert set(inserts) == {threading.main_thread()}, "only the Tk thread writes the log"
    finally:
        feed.let_go()
        thread.join(WAIT)
        panel._finish({"state": "cancelled"})
        window.destroy()
        settle(tk_root)
