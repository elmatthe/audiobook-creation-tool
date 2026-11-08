"""Log panes follow, hold and resume -- v0.7.2 Phase 5, ACT72-005.

``shared/job_ui.py``'s ``SummaryDetailsView`` is the Summary | Detailed log of
all six tools. Before this phase every render deleted the pane and inserted
everything again, so the view jumped to line 1 on every update: a reader at the
bottom never saw new lines arrive, and a reader who had scrolled up lost their
place (reproduced at ``fa9d3c3``: the pane sat at line 1 after each render).

Each test drives a real, mapped Tk text widget at a real size and judges what is
on screen -- the line at the top, whether the newest line is visible -- rather
than an internal flag. The reader's own actions are real Tk events where Tk has
one (the mouse wheel through the Text class binding, a notebook tab change, a
window resize); a scrollbar drag is the ``yview moveto`` call the scrollbar
itself makes. Nothing here sleeps to create an ordering, and every render and
read happens on the thread that owns Tk.
"""

from __future__ import annotations

import random
import threading
import time

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import job_ui  # noqa: E402

import tk_gate  # noqa: E402

WAIT = 5.0


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


def settle(root) -> None:
    root.update_idletasks()
    root.update()


@pytest.fixture
def window(tk_root):
    """A real, visible window of a fixed size, so the panes have geometry."""
    tk_root.deiconify()
    tk_root.geometry("640x260+40+40")
    frame = ttk.Frame(tk_root)
    frame.pack(fill="both", expand=True)
    settle(tk_root)
    yield frame
    frame.destroy()
    tk_root.geometry("")
    tk_root.withdraw()
    tk_root.update_idletasks()


def make_view(frame, **kwargs) -> job_ui.SummaryDetailsView:
    view = job_ui.SummaryDetailsView(frame, height=10, **kwargs)
    view.frame.pack(fill="both", expand=True)
    settle(frame.winfo_toplevel())
    return view


def top_line(pane) -> int:
    return int(pane.index("@0,0").split(".")[0])


def top_text(pane) -> str:
    return pane.get("@0,0 linestart", "@0,0 lineend")


def newest_shown(pane) -> bool:
    return pane.dlineinfo("end-1c") is not None


def wheel(pane, notches: int) -> None:
    """The mouse wheel through Tk's own Text binding: positive notches scroll up."""
    pane.event_generate("<MouseWheel>", delta=120 * notches, x=20, y=20)
    settle(pane.winfo_toplevel())


def lines(start: int, stop: int, prefix: str = "line") -> list[str]:
    return [f"{prefix} {index:04d}" for index in range(start, stop)]


def test_a_pane_at_the_bottom_follows_every_new_line(window):
    view = make_view(window)
    pane = view.summary_text
    shown = lines(1, 101)
    view.set_summary(shown)
    settle(window)
    assert newest_shown(pane), "the first long render must open at the newest line"
    assert top_line(pane) > 1
    for index in range(101, 141):
        shown.append(f"line {index:04d}")
        view.set_summary(shown)
        settle(window)
        assert newest_shown(pane), f"render {index} left the newest line off screen"
    assert pane.get("end-1c linestart", "end-1c") == "line 0140"


def test_a_reader_who_scrolled_up_keeps_their_line_to_the_pixel(window):
    view = make_view(window)
    pane = view.summary_text
    shown = lines(1, 201)
    view.set_summary(shown)
    settle(window)
    assert newest_shown(pane), "precondition: the reader starts at the bottom"
    bottom = top_line(pane)
    wheel(pane, 5)  # 200 px up: a partly hidden top line is the honest case
    held, held_text = top_line(pane), top_text(pane)
    held_y = pane.dlineinfo("@0,0")[1]
    assert held < bottom and not newest_shown(pane), "precondition: the wheel moved the reader up"
    for index in range(201, 261):
        shown.append(f"line {index:04d}")
        view.set_summary(shown)
        settle(window)
        assert (top_line(pane), top_text(pane)) == (held, held_text), f"render {index} moved the reader"
        assert pane.dlineinfo("@0,0")[1] == held_y, "the reader's pixel offset changed"
        assert not newest_shown(pane)
    assert view.rendered(pane) == "\n".join(shown)


def test_returning_to_the_bottom_resumes_following(window):
    view = make_view(window)
    pane = view.summary_text
    shown = lines(1, 201)
    view.set_summary(shown)
    settle(window)
    wheel(pane, 3)
    shown.append("while held")
    view.set_summary(shown)
    settle(window)
    assert not newest_shown(pane)
    # Back down with the wheel until Tk stops at the end, as a reader does.
    for _ in range(10):
        wheel(pane, -1)
    assert newest_shown(pane)
    for index in range(3):
        shown.append(f"after return {index}")
        view.set_summary(shown)
        settle(window)
        assert newest_shown(pane), "following did not resume at the bottom"
    # The scrollbar route too: a thumb dragged to the end is a `yview moveto`.
    wheel(pane, 4)
    pane.yview_moveto(1.0)
    settle(window)
    shown.append("after the thumb")
    view.set_summary(shown)
    settle(window)
    assert newest_shown(pane)


def test_each_pane_follows_or_holds_on_its_own_through_tab_switches(window):
    view = make_view(window, details_label="Detailed")
    summary, details = view.summary_text, view.details_text
    view.set_summary(lines(1, 151, "s"))
    view.show_details()
    settle(window)
    view.set_details(lines(1, 151, "d"))
    settle(window)
    view.show_summary()
    settle(window)
    wheel(summary, 4)
    held = top_text(summary)
    s_lines, d_lines = lines(1, 151, "s"), lines(1, 151, "d")
    for index in range(151, 181):
        s_lines.append(f"s {index:04d}")
        d_lines.append(f"d {index:04d}")
        view.set_summary(s_lines)
        view.set_details(d_lines)
        settle(window)
        if index == 160:
            view.show_details()
            settle(window)
            assert newest_shown(details), "the hidden Detailed pane stopped following"
        if index == 170:
            view.show_summary()
            settle(window)
            assert top_text(summary) == held, "a tab switch lost the Summary reader's place"
    assert top_text(summary) == held and not newest_shown(summary)
    view.show_details()
    settle(window)
    assert newest_shown(details) and details.get("end-1c linestart", "end-1c") == "d 0180"


def test_a_pane_never_opened_follows_when_it_is_first_shown(window):
    view = make_view(window)
    view.set_details(lines(1, 301, "d"))
    settle(window)
    assert view.details_text.winfo_height() <= 1, "precondition: the Details page was never laid out"
    view.set_details(lines(1, 321, "d"))
    view.show_details()
    settle(window)
    assert newest_shown(view.details_text)
    assert view.details_text.get("end-1c linestart", "end-1c") == "d 0320"


def test_trimmed_history_keeps_the_held_line_until_it_is_itself_trimmed(window):
    view = make_view(window, limit=120)
    pane = view.summary_text
    for index in range(1, 101):
        view.append(f"h {index:04d}")
    settle(window)
    pane.yview("40.0")  # the reader is reading h 0040
    settle(window)
    assert top_text(pane) == "h 0040"
    for index in range(101, 151):  # 30 lines leave the front; h 0040 stays
        view.append(f"h {index:04d}")
        settle(window)
        assert top_text(pane) == "h 0040", f"append {index} moved the reader"
    assert view.summary[0] == "h 0031"
    for index in range(151, 171):  # now h 0040 itself is trimmed away
        view.append(f"h {index:04d}")
        settle(window)
    assert view.summary[0] == "h 0051"
    assert top_line(pane) == 1 and top_text(pane) == "h 0051", "the reader is left at what remains"
    assert view.rendered(pane) == "\n".join(view.summary)


def test_a_rewritten_tail_keeps_the_held_line_number(window):
    """A projection that rewrites lines rather than adding them still holds the reader."""
    view = make_view(window)
    pane = view.summary_text
    base = lines(1, 101)
    view.set_summary(base + ["Running: 1 of 50"])
    settle(window)
    pane.yview("30.0")
    settle(window)
    for step in range(2, 30):
        view.set_summary(base[:60] + [f"rewritten {step}"] + base[60:] + [f"Running: {step} of 50"])
        settle(window)
        assert top_line(pane) == 30, f"rewrite {step} moved the reader off line 30"
    assert view.rendered(pane) == "\n".join(view.summary)


def test_clear_while_holding_starts_following_what_comes_next(window):
    view = make_view(window)
    pane = view.summary_text
    view.set_summary(lines(1, 201))
    settle(window)
    wheel(pane, 6)
    view.clear()
    settle(window)
    assert view.rendered(pane) == ""
    fresh = lines(1, 201) + lines(1, 80, "new")
    view.set_summary(fresh)
    settle(window)
    assert view.summary == tuple(lines(1, 80, "new"))
    assert newest_shown(pane), "after Clear Log the pane must follow the new lines"


def test_a_resize_keeps_a_follower_at_the_bottom_and_a_holder_on_their_line(window, tk_root):
    """Held far enough up that even the largest size leaves the end hidden: a window
    grown until the newest line shows has put its reader at the bottom, by definition."""
    view = make_view(window, details_label="Detailed")
    summary, details = view.summary_text, view.details_text
    view.set_summary(lines(1, 401, "s"))
    view.show_details()
    settle(window)
    view.set_details(lines(1, 401, "d"))
    settle(window)
    wheel(details, 15)
    held = top_text(details)
    view.show_summary()
    settle(window)
    for size in ("640x180", "640x420", "400x200", "900x500"):
        tk_root.geometry(size)
        settle(window)
        assert newest_shown(summary), f"Summary stopped following at {size}"
        view.show_details()
        settle(window)
        assert top_text(details) == held and not newest_shown(details), f"Detailed lost its place at {size}"
        view.show_summary()
        settle(window)


def test_a_tool_switch_unmaps_and_remaps_the_log_without_losing_either_state(window):
    """The launcher hides a tool with ``pack_forget`` and shows it again with ``pack``."""
    view = make_view(window, details_label="Detailed")
    summary, details = view.summary_text, view.details_text
    view.set_summary(lines(1, 201, "s"))
    view.show_details()
    settle(window)
    view.set_details(lines(1, 201, "d"))
    settle(window)
    wheel(details, 4)
    held = top_text(details)
    view.show_summary()
    settle(window)
    window.pack_forget()
    settle(window)
    view.set_summary(lines(1, 241, "s"))
    view.set_details(lines(1, 241, "d"))
    window.pack(fill="both", expand=True)
    settle(window)
    assert newest_shown(summary)
    view.show_details()
    settle(window)
    assert top_text(details) == held


def test_the_rendered_text_is_always_exactly_the_model(window):
    """Smallest-edit rendering is only correct if the pane always equals the model.

    A seeded walk through every operation -- growing and rewritten projections, a
    fresh shorter source, history appends, dividers, Details-only lines, entries
    holding newlines, trimming and Clear Log -- with the reader moved between
    renders, compared with the model after every step.
    """
    rng = random.Random(72005)
    view = make_view(window, limit=25)
    summary_live: list[str] = []
    details_live: list[str] = []

    def entry(kind: str, number: int) -> str:
        return f"{kind} {number}" + ("\nsecond row" if number % 7 == 0 else "")

    for step in range(500):
        op = rng.choice(("grow", "grow", "grow", "rewrite", "fresh", "append", "detail", "divider", "clear"))
        if op == "grow":
            summary_live.extend(entry("s", step + k) for k in range(rng.randint(1, 4)))
            details_live.extend(entry("d", step + k) for k in range(rng.randint(1, 6)))
            view.set_summary(summary_live)
            view.set_details(details_live)
        elif op == "rewrite" and summary_live:
            summary_live[rng.randrange(len(summary_live))] = f"rewritten {step}"
            view.set_summary(summary_live)
        elif op == "fresh":
            summary_live, details_live = [f"fresh {step}"], [f"fresh detail {step}"]
            view.set_summary(summary_live)
            view.set_details(details_live)
        elif op == "append":
            view.append(entry("a", step), entry("ad", step))
        elif op == "detail":
            view.append_detail([entry("x", step), entry("y", step)])
        elif op == "divider":
            view.divider(f"-- run {step} --")
        elif op == "clear":
            view.clear()
        if rng.random() < 0.3:
            pane = rng.choice((view.summary_text, view.details_text))
            pane.yview_moveto(rng.random())
        settle(window)
        assert view.rendered(view.summary_text) == "\n".join(view.summary), f"step {step} ({op}) Summary"
        assert view.rendered(view.details_text) == "\n".join(view.details), f"step {step} ({op}) Details"


def test_a_busy_run_keeps_the_event_loop_responsive_and_the_reader_in_place(window, tk_root):
    """A high rate of renders: 600 of them, ten new lines each, to 6,000 lines.

    Measured at the fix (HOME-PC, Tk 8.6.15): about 5 ms for the worst render and
    redraw. The budgets below are 20 and 50 times that, room for a loaded machine
    while still catching a render that blocks the loop.
    """
    view = make_view(window, details_label="Detailed")
    view.show_details()
    pane = view.details_text
    settle(window)
    shown: list[str] = []
    gaps: list[float] = []
    worst = 0.0
    last = [time.perf_counter()]

    def heartbeat() -> None:
        now = time.perf_counter()
        gaps.append(now - last[0])
        last[0] = now

    held = None
    for render in range(600):
        if render == 300:
            wheel(pane, 6)
            held = top_text(pane)
        shown.extend(f"[+{render:04d}.{k}s] technical: step {render * 10 + k}" for k in range(10))
        started = time.perf_counter()
        view.set_details(shown)
        tk_root.update_idletasks()
        worst = max(worst, time.perf_counter() - started)
        tk_root.after(0, heartbeat)
        tk_root.update()
        if held is None:
            assert newest_shown(pane), f"render {render}: a following reader lost the newest line"
        else:
            assert top_text(pane) == held, f"render {render}: a holding reader was moved"
    assert worst < 0.1, f"a render and redraw took {worst:.3f} s"
    assert max(gaps) < 0.25, f"the event loop went {max(gaps):.3f} s without running a callback"
    assert view.rendered(pane) == "\n".join(shown)


SHELL_TOOLS = ("tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover", "m4b_metadata")


@pytest.fixture
def real_shell(tk_root, monkeypatch):
    """The real launcher at the Windows minimum, every tool built; settings kept in memory."""
    import launcher
    from shared import appearance, ui_theme

    store: dict = {}

    class _Settings:
        @staticmethod
        def get(key, default=None):
            return store.get(key, default)

        @staticmethod
        def set(key, value, **_kwargs):
            store[key] = value
            return True

    monkeypatch.setattr(launcher, "app_settings", _Settings)
    monkeypatch.setattr(appearance, "app_settings", _Settings)
    existing = set(tk_root.winfo_children())
    tk_root.deiconify()
    app = launcher.LauncherApp(tk_root)
    tk_root.geometry("{}x{}".format(*ui_theme.MIN_SIZE))
    for key in SHELL_TOOLS:
        app.select_tool(key)
        settle(tk_root)
    try:
        yield app
    finally:
        for child in list(tk_root.winfo_children()):
            if child not in existing:
                child.destroy()
        try:
            tk_root.protocol("WM_DELETE_WINDOW", "")
        except tk.TclError:  # pragma: no cover - no handler was installed
            pass
        settle(tk_root)
        tk_root.geometry("")
        tk_root.withdraw()


def test_every_tools_own_log_follows_holds_and_resumes_in_the_real_shell(real_shell, tk_root):
    """All six tools' Activity logs, in their real layouts at 920x600, through tool switches.

    Lines go in through each panel's own view, the way the tool's own messages do;
    the reader's moves are wheel events on the pane the tool shows.
    """
    for key in SHELL_TOOLS:
        real_shell.select_tool(key)
        settle(tk_root)
        panel = real_shell.containers[key].winfo_children()[0]
        view = panel.log
        assert isinstance(view, job_ui.SummaryDetailsView), key
        pane = view.summary_text
        assert pane.winfo_viewable() and pane.winfo_height() > 1, f"{key}: the Summary pane is not on screen"
        for index in range(80):
            view.append(f"{key} line {index:03d}")
        settle(tk_root)
        assert newest_shown(pane), f"{key}: the log did not follow its own lines"
        wheel(pane, 3)
        held = top_text(pane)
        assert not newest_shown(pane), f"{key}: precondition, the wheel moved the reader up"
        for index in range(80, 100):
            view.append(f"{key} line {index:03d}")
        settle(tk_root)
        assert top_text(pane) == held, f"{key}: new lines moved a reader who had scrolled up"
        other = SHELL_TOOLS[(SHELL_TOOLS.index(key) + 1) % len(SHELL_TOOLS)]
        real_shell.select_tool(other)
        settle(tk_root)
        view.append(f"{key} while hidden")
        real_shell.select_tool(key)
        settle(tk_root)
        assert top_text(pane) == held, f"{key}: switching tools lost the reader's place"
        for _ in range(12):
            wheel(pane, -1)
        assert newest_shown(pane), f"{key}: the wheel could not bring the reader back down"
        view.append(f"{key} after the return")
        settle(tk_root)
        assert newest_shown(pane), f"{key}: following did not resume"
        assert pane.get("end-1c linestart", "end-1c") == f"{key} after the return"


def test_a_worker_thread_cannot_render_into_a_pane(window):
    view = make_view(window)
    view.set_summary(("kept",))
    caught: list[BaseException] = []

    def body() -> None:
        try:
            view.set_summary(("from a worker",))
        except BaseException as exc:  # noqa: BLE001 - the error is the result
            caught.append(exc)

    worker = threading.Thread(target=body, name="log-follow-worker")
    worker.start()
    worker.join(WAIT)
    assert not worker.is_alive()
    assert len(caught) == 1 and isinstance(caught[0], job_ui.MainThreadError)
    assert view.rendered(view.summary_text) == "kept"
