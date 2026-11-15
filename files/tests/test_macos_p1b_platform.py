"""v0.8.x P1B -- the macOS GUI shell's Tk 9 port and the platform layer (plan sections 10 and 11.3).

What each group proves, and on which platform:

* Tk 9 trackpad scrolling (MAC-040): ``<TouchpadScroll>`` is decoded by Tk's own ``tk::PreciseScrollDeltas`` and moves
  a Text, a Canvas and a Listbox; the shared hover-region owner claims and returns both slots, and never scrolls a
  widget twice (Tk 9's own Text/Listbox/Treeview bindings run first). Native on the Mac's Aqua Tk 9.
* Windows parity (every platform): the wheel formula equals Windows' for every delta of 120 or more; Select-All adds
  Command bindings only where Tk draws natively on macOS; the log font is Consolas everywhere but macOS; the optional
  setup panel keeps its exact Segoe UI tuples on Windows; the memory text still says "Windows" there; the qwen3 clone
  setup keeps its original Windows wheel lambda.
* Cmd+Q and Settings (MAC-008): registered on Aqua, and Quit reaches the one idempotent close path.
* Memory (MAC-011): the darwin reader agrees with the kernel; the plan names macOS.
* No-clobber publication (MAC-017): ``renamex_np(RENAME_EXCL)`` on APFS; the hard link where it is unsupported; a clear
  refusal when neither exists. The real exFAT volume is ``test_macos_p1b_filesystems.py``.
"""

from __future__ import annotations

import ast
import errno
import os
import subprocess
import sys
import textwrap
import tkinter as tk
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"

from shared import appearance, job_ui, optional_setup_panel, output_paths, ui_theme  # noqa: E402
from tk_gate import open_tk_root  # noqa: E402
from tts import publication, worker_limits  # noqa: E402

NATIVE_P1B = "native macOS only (P1B): Aqua Tk 9 shell, POSIX containment and macOS filesystem checks"
native = pytest.mark.skipif(sys.platform != "darwin", reason=NATIVE_P1B)


@pytest.fixture
def root():
    window = open_tk_root(tk)
    window.geometry("400x300+40+40")
    yield window
    window.destroy()


def _touchpad(widget, dx: int, dy: int) -> None:
    """One ``<TouchpadScroll>`` as Tk 9 packs it: x in the high 16 bits, y in the low 16."""
    widget.event_generate(ui_theme.TOUCHPAD_SCROLL, delta=((dx & 0xFFFF) << 16) | (dy & 0xFFFF), x=5, y=5)
    widget.update()


# --------------------------------------------------------------------------- #
#  Tk 9 scrolling
# --------------------------------------------------------------------------- #
def test_touchpad_support_follows_the_running_tk():
    assert ui_theme.touchpad_scroll_supported() is (tk.TkVersion >= 9.0)


@pytest.mark.parametrize("delta, units", [(120, -1), (-120, 1), (240, -2), (-360, 3), (130, -1), (-130, 1), (119, -1),
                                          (-1, 1), (3, -1), (0, 0)])
def test_wheel_units_equals_the_windows_formula_from_120_and_keeps_small_deltas_moving(delta, units):
    assert ui_theme.wheel_units(delta) == units
    if abs(delta) >= 120:
        assert ui_theme.wheel_units(delta) == int(-delta / 120), "the Windows formula, exactly"


@native
def test_a_touchpad_scroll_moves_a_text_a_canvas_and_a_listbox(root):
    assert ui_theme.touchpad_scroll_supported(), "the app's own Python on a Mac has Aqua Tk 9"
    text = tk.Text(root, height=5)
    text.insert("1.0", "\n".join(f"line {n}" for n in range(300)))
    canvas = tk.Canvas(root, height=120, scrollregion=(0, 0, 300, 6000))
    listbox = tk.Listbox(root, height=5)
    for n in range(300):
        listbox.insert("end", n)
    for widget in (text, canvas, listbox):
        widget.pack(fill="x")
    root.update()

    class Event:
        def __init__(self, dy):
            self.delta = ((0 & 0xFFFF) << 16) | (dy & 0xFFFF)

    for widget in (text, canvas, listbox):
        before = widget.yview()[0]
        assert ui_theme.scroll_by_touchpad(widget, Event(-240)) is True  # fingers up: content moves on
        root.update()
        assert widget.yview()[0] > before, type(widget).__name__
        assert ui_theme.scroll_by_touchpad(widget, Event(0)) is False


@native
def test_the_hover_owner_claims_both_slots_on_tk9_and_gives_back_only_its_own(root):
    frame = tk.Frame(root, width=200, height=200)
    canvas = tk.Canvas(frame, scrollregion=(0, 0, 200, 5000), height=150)
    label = tk.Label(frame, text="over me")
    canvas.pack()
    label.pack()
    frame.pack()
    root.update()
    ui_theme.enable_mousewheel(canvas, hover_region=frame)
    frame.event_generate("<Enter>")
    root.update()
    assert root.tk.call("bind", "all", "<MouseWheel>")
    assert root.tk.call("bind", "all", ui_theme.TOUCHPAD_SCROLL)
    # Over a plain label inside the region, the trackpad scrolls the region's target.
    before = canvas.yview()[0]
    _touchpad(label, 0, -300)
    assert canvas.yview()[0] > before
    frame.event_generate("<Unmap>")
    root.update()
    assert root.tk.call("bind", "all", "<MouseWheel>") == ""
    assert root.tk.call("bind", "all", ui_theme.TOUCHPAD_SCROLL) == ""


@native
def test_a_text_inside_the_region_is_scrolled_once_by_its_own_class_binding(root):
    text = tk.Text(root, height=5)
    text.insert("1.0", "\n".join(f"line {n}" for n in range(400)))
    text.pack()
    root.update()
    ui_theme.enable_mousewheel(text)
    text.event_generate("<Enter>")
    root.update()
    once = tk.Text(root, height=5)  # the same scroll on a Text with no owner: Tk's class binding alone
    once.insert("1.0", "\n".join(f"line {n}" for n in range(400)))
    once.pack()
    root.update()
    _touchpad(text, 0, -90)
    _touchpad(once, 0, -90)
    assert text.yview()[0] > 0
    assert text.yview() == pytest.approx(once.yview()), "the owner added no second scroll"


@native
def test_the_cover_browser_canvas_answers_the_trackpad(root):
    from artwork import cover_resizer

    source = (SCRIPTS / "artwork" / "cover_resizer.py").read_text(encoding="utf-8")
    assert "canvas.bind(ui_theme.TOUCHPAD_SCROLL, self._touchpad_handler(canvas), add=\"+\")" in source
    canvas = tk.Canvas(root, height=100, scrollregion=(0, 0, 100, 5000))
    canvas.pack()
    root.update()
    canvas.bind(ui_theme.TOUCHPAD_SCROLL, cover_resizer.CoverBrowser._touchpad_handler(canvas))
    _touchpad(canvas, 0, -200)
    assert canvas.yview()[0] > 0


def test_the_qwen3_clone_setup_keeps_its_windows_wheel_lambda_outside_aqua():
    tree = ast.parse((SCRIPTS / "tts" / "qwen3_clone_setup_ui.py").read_text(encoding="utf-8"))
    branches = [node for node in ast.walk(tree) if isinstance(node, ast.If) and "is_aqua" in ast.unparse(node.test)]
    assert len(branches) == 1
    windows = ast.unparse(branches[0].orelse[0])
    assert windows == "win.bind('<MouseWheel>', lambda event: canvas.yview_scroll(int(-event.delta / 120), 'units'))"


# --------------------------------------------------------------------------- #
#  Select All (MAC-037)
# --------------------------------------------------------------------------- #
def test_select_all_adds_command_only_where_tk_is_aqua(root, monkeypatch):
    monkeypatch.setattr(ui_theme, "is_aqua", lambda _w: False)
    assert job_ui.select_all_sequences(root) == ("<Control-a>", "<Control-A>"), "Windows and Linux: unchanged"
    monkeypatch.setattr(ui_theme, "is_aqua", lambda _w: True)
    assert job_ui.select_all_sequences(root) == ("<Control-a>", "<Control-A>", "<Command-a>", "<Command-A>")


@native
def test_command_a_reaches_the_lists_own_select_all_on_aqua(root):
    listbox = tk.Listbox(root, selectmode="extended")
    for n in range(4):
        listbox.insert("end", n)
    listbox.pack()
    calls = []
    job_ui.bind_list_shortcuts(listbox, on_select_all=lambda: calls.append("all"))
    root.update()
    listbox.focus_force()
    root.update()
    listbox.event_generate("<Command-a>")
    root.update()
    assert calls == ["all"], "the manager's own Select All ran, not only Tk's class binding"


# --------------------------------------------------------------------------- #
#  Fonts (MAC-020)
# --------------------------------------------------------------------------- #
def test_the_log_font_is_consolas_everywhere_but_macos():
    assert appearance._mono_family("win32") == "Consolas"
    assert appearance._mono_family("linux") == "Consolas"
    assert appearance._mono_family("darwin") == "Menlo"
    assert appearance._fonts("Segoe UI", 9, "win32")["mono"] == ("Consolas", 9)
    assert appearance._fonts("Segoe UI", 9, "win32") == {
        "title": ("Segoe UI", 15, "bold"), "heading": ("Segoe UI", 13, "bold"),
        "subheading": ("Segoe UI", 10, "bold"), "section": ("Segoe UI", 9), "body": ("Segoe UI", 9),
        "body_bold": ("Segoe UI", 9, "bold"), "row": ("Segoe UI", 9), "small": ("Segoe UI", 9),
        "status": ("Segoe UI", 9), "button": ("Segoe UI", 9), "mono": ("Consolas", 9)}


def test_the_optional_setup_panel_keeps_its_exact_windows_fonts(root, monkeypatch):
    monkeypatch.setattr(optional_setup_panel.sys, "platform", "win32")
    assert optional_setup_panel.panel_font(root, 12, "bold") == ("Segoe UI", 12, "bold")
    assert optional_setup_panel.panel_font(root, 9) == ("Segoe UI", 9)


@native
def test_the_optional_setup_panel_uses_the_macs_own_ui_font_at_its_own_size(root):
    from tkinter import font as tkfont

    default = tkfont.nametofont("TkDefaultFont", root=root)
    family, size = default.actual("family"), int(default.actual("size"))
    assert optional_setup_panel.panel_font(root, 9) == (family, size)
    assert optional_setup_panel.panel_font(root, 12, "bold") == (family, size + 3, "bold")
    assert "Segoe" not in family


# --------------------------------------------------------------------------- #
#  Cmd+Q and Settings (MAC-008)
# --------------------------------------------------------------------------- #
@native
def test_cmd_q_and_settings_are_registered_on_aqua_and_quit_is_the_one_close_path(root, monkeypatch):
    import launcher

    app = launcher.LauncherApp.__new__(launcher.LauncherApp)
    app.root = root
    app.current_key = "mp3_tool"
    app.logger = launcher.logging_setup.get_logger()
    opened, saved, destroyed = [], [], []
    app.open_preferences = lambda: opened.append(True)
    monkeypatch.setattr(launcher.app_settings, "set", lambda key, value: saved.append((key, value)))
    monkeypatch.setattr(root, "destroy", lambda: destroyed.append(True))
    app._register_mac_application_commands()
    root.tk.call("::tk::mac::ShowPreferences")
    assert opened == [True]
    root.tk.call("::tk::mac::Quit")
    root.tk.call("::tk::mac::Quit")  # a second Cmd+Q, or a signal at the same moment: still one close
    app._on_close()
    assert saved == [("last_tool", "mp3_tool")]
    assert destroyed == [True]


def test_on_windows_the_close_is_exactly_as_before(root, monkeypatch):
    """Windows control: the one-close guard is POSIX only; each close request on Windows runs the close as at v0.8.0."""
    import launcher

    app = launcher.LauncherApp.__new__(launcher.LauncherApp)
    app.root = root
    app.current_key = "mp3_tool"
    saved, destroyed = [], []
    monkeypatch.setattr(launcher.app_settings, "set", lambda key, value: saved.append((key, value)))
    monkeypatch.setattr(root, "destroy", lambda: destroyed.append(True))
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    app._on_close()
    app._on_close()
    monkeypatch.undo()
    assert saved == [("last_tool", "mp3_tool")] * 2 and destroyed == [True, True]


def test_nothing_mac_is_registered_where_tk_is_not_aqua(root, monkeypatch):
    import launcher

    monkeypatch.setattr(ui_theme, "is_aqua", lambda _w: False)
    app = launcher.LauncherApp.__new__(launcher.LauncherApp)
    app.root = root
    app.logger = launcher.logging_setup.get_logger()
    calls = []
    monkeypatch.setattr(root, "createcommand", lambda *a: calls.append(a))
    app._register_mac_application_commands()
    assert calls == []


def test_windows_routes_no_signal_and_changes_no_open_file_limit(monkeypatch):
    import launcher

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    assert launcher._route_signals_to_close(None, None) is False
    assert launcher._raise_open_file_limit() is None


@native
def test_once_the_window_is_gone_the_close_signals_are_handed_back_and_hold_nothing(root):
    """While the window runs, SIGTERM/SIGHUP/SIGINT take the close path; once the main loop has ended they are what
    they were before (a further signal ends the process instead of being lost on a closed window), and the handler no
    longer keeps the closed window reachable."""
    import gc
    import signal
    import weakref

    import launcher

    class App:
        closed = 0
        logger = None

        def _on_close(self):
            App.closed += 1

    before = {name: signal.getsignal(getattr(signal, name)) for name in launcher.CLOSE_SIGNALS}
    app = App()
    release = launcher._route_signals_to_close(root, app)
    try:
        assert callable(release)
        assert all(signal.getsignal(getattr(signal, name)) is not before[name] for name in launcher.CLOSE_SIGNALS)
        signal.raise_signal(signal.SIGHUP)
        root.update()
        root.update()
        assert App.closed == 1, "the signal reached the close path on Tk's thread"
    finally:
        release()
    assert {name: signal.getsignal(getattr(signal, name)) for name in launcher.CLOSE_SIGNALS} == before
    held = weakref.ref(app)
    del app
    gc.collect()
    assert held() is None, "nothing of the signal routing still holds the application"


@native
def test_the_open_file_limit_is_raised_from_launchds_256_and_never_lowered(tmp_path):
    probe = textwrap.dedent(f"""
        import resource, sys
        sys.path.insert(0, {str(SCRIPTS)!r})
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, hard))
        import launcher
        print(launcher._raise_open_file_limit(), resource.getrlimit(resource.RLIMIT_NOFILE)[0])
        resource.setrlimit(resource.RLIMIT_NOFILE, (8192, hard))
        print(launcher._raise_open_file_limit(), resource.getrlimit(resource.RLIMIT_NOFILE)[0])
    """)
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    first, second = done.stdout.split("\n")[:2]
    assert first == "(256, 4096) 4096"
    assert second == "None 8192", "a higher limit is left alone"


# --------------------------------------------------------------------------- #
#  Memory (MAC-011)
# --------------------------------------------------------------------------- #
def test_the_reserve_is_kept_for_windows_on_windows_and_for_macos_on_a_mac():
    assert worker_limits._system_name("win32") == "Windows"
    assert worker_limits._system_name("darwin") == "macOS"
    assert worker_limits._system_name("linux") == "the system"


def test_the_windows_plan_text_is_unchanged(monkeypatch):
    monkeypatch.setattr(worker_limits.sys, "platform", "win32")
    gb = 1024 ** 3
    budget = worker_limits.FileBudget(working=gb, assembly=3 * gb)
    plan = worker_limits.plan_workers(8, worker_limits.EDGE, [budget] * 8, cpu_count=8,
                                      memory=worker_limits.MemoryInfo(6 * gb, 16 * gb))
    assert any("kept for Windows and other programs" in reason for reason in plan.reasons), plan


@native
def test_the_darwin_memory_reader_agrees_with_the_kernel():
    memory = worker_limits.memory_info()
    assert memory is not None, "macOS memory is read, no longer assumed"
    hw = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True)
    assert memory.total == int(hw.stdout.strip())
    assert 0 < memory.available <= memory.total
    assert memory.commit_available is None and memory.process_headroom is None and memory.job_headroom is None
    footprint = worker_limits.own_private_bytes()
    assert footprint is not None and 1 << 20 < footprint < memory.total


@native
def test_the_mac_plan_names_macos(monkeypatch):
    gb = 1024 ** 3
    budget = worker_limits.FileBudget(working=gb, assembly=3 * gb)
    plan = worker_limits.plan_workers(8, worker_limits.EDGE, [budget] * 8, cpu_count=8,
                                      memory=worker_limits.MemoryInfo(6 * gb, 16 * gb))
    assert any("kept for macOS and other programs" in reason for reason in plan.reasons), plan


# --------------------------------------------------------------------------- #
#  No-clobber publication (MAC-017)
# --------------------------------------------------------------------------- #
@native
def test_an_exclusive_rename_publishes_once_and_leaves_no_second_name(tmp_path):
    staged, other, destination = tmp_path / "a.staged", tmp_path / "b.staged", tmp_path / "Book.mp3"
    staged.write_bytes(b"first")
    other.write_bytes(b"second")
    output_paths.move_without_replacing(staged, destination)
    assert destination.read_bytes() == b"first" and not staged.exists()
    assert destination.stat().st_nlink == 1, "renamex_np, not a hard link: no second name was ever made"
    with pytest.raises(FileExistsError):
        output_paths.move_without_replacing(other, destination)
    assert destination.read_bytes() == b"first" and other.read_bytes() == b"second"


@native
def test_where_the_exclusive_rename_is_unsupported_the_hard_link_is_used(tmp_path, monkeypatch):
    def unsupported(*_args):
        import ctypes

        ctypes.set_errno(errno.ENOTSUP)
        return -1

    monkeypatch.setattr(output_paths, "_renamex_np", unsupported)
    staged, destination = tmp_path / "a.staged", tmp_path / "Book.mp3"
    staged.write_bytes(b"x")
    output_paths.move_without_replacing(staged, destination)
    assert destination.read_bytes() == b"x" and not staged.exists()


@native
def test_with_neither_primitive_the_refusal_is_clear_and_nothing_is_published(tmp_path, monkeypatch):
    def unsupported(*_args):
        import ctypes

        ctypes.set_errno(errno.ENOTSUP)
        return -1

    def no_links(*_args):
        raise OSError(errno.ENOTSUP, "Operation not supported")

    monkeypatch.setattr(output_paths, "_renamex_np", unsupported)
    monkeypatch.setattr(output_paths.os, "link", no_links)
    staged = tmp_path / f"{output_paths.TEMP_SIBLING_PREFIX}book.mp3"
    staged.write_bytes(b"x")
    destination = tmp_path / "Book.mp3"
    with pytest.raises(output_paths.OutputPathError) as caught:
        output_paths.publish_new(staged, destination)
    assert "neither an exclusive rename nor hard links" in caught.value.detail
    assert not destination.exists() and staged.exists(), "the temporary file is still the caller's to discard"


def test_the_windows_publication_branches_are_still_a_plain_rename():
    tree = ast.parse((SCRIPTS / "tts" / "publication.py").read_text(encoding="utf-8"))
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_publish_no_clobber")
    windows = next(n for n in ast.walk(function) if isinstance(n, ast.If) and ast.unparse(n.test) == "_IS_WINDOWS")
    assert [ast.unparse(s) for s in windows.body] == ["os.rename(staged, destination)"]
    tree = ast.parse((SCRIPTS / "shared" / "output_paths.py").read_text(encoding="utf-8"))
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "move_without_replacing")
    windows = next(n for n in ast.walk(function) if isinstance(n, ast.If) and ast.unparse(n.test) == "os.name == 'nt'")
    assert [ast.unparse(s) for s in windows.body] == ["os.rename(source, destination)", "return"]


@native
def test_tts_publication_uses_the_shared_primitive_and_explains_unsupported_drives(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(publication.output_paths, "move_without_replacing", lambda a, b: calls.append((a, b)))
    publication._publish_no_clobber(tmp_path / "s", tmp_path / "d")
    assert calls == [(tmp_path / "s", tmp_path / "d")]
    message = str(publication._explain(tmp_path / "Book.mp3", OSError(errno.ENOTSUP, "Operation not supported")))
    assert "cannot publish a file without risking what is already there" in message
