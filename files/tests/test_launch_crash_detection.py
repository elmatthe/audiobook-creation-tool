"""A window that dies as it starts is reported, not hidden (v0.7.2 Phase 8, ACT72-055).

``bootstrap.launch_gui`` starts the application detached, with its output captured in ``launch_<date>.log``, then
watches the new process for a short grace window. If it has already exited with an error the launch is reported as
failed, with the last lines of what the window said. Every earlier test replaced ``subprocess.Popen`` with a process
that never exits, so that branch had never run.

Here the child is real: a real interpreter running a real script, started by the production ``Popen`` call with its
production flags (no console, detached) and its real output redirection, and watched for the production grace. Only
which script is started, with which interpreter, and where the log folder is are given to it, so nothing is started
from or written to the real installation.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from shared import bootstrap


class _Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)


@pytest.fixture()
def launch(monkeypatch, tmp_path):
    """``launch_gui`` as production runs it, pointed at a script of the test's own. Returns (start, log, logs, children)."""
    target = tmp_path / "launcher.py"
    logs = tmp_path / "logs"
    children: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def recording_popen(argv, **kwargs):
        child = real_popen(argv, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(bootstrap, "venv_python", lambda windowed=False: Path(sys.executable))
    monkeypatch.setattr(bootstrap, "_launch_target", lambda: target)
    monkeypatch.setattr(bootstrap, "LOGS_DIR", logs)
    monkeypatch.setattr(bootstrap, "SCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(bootstrap, "_ffmpeg_in_bin", lambda: None)
    monkeypatch.setattr(bootstrap, "stale_layout_notice", lambda *a, **k: None)
    monkeypatch.setattr(bootstrap.subprocess, "Popen", recording_popen)
    log = _Log()

    def start(script: str) -> bool:
        target.write_text(textwrap.dedent(script), encoding="utf-8")
        return bootstrap.launch_gui(log)

    yield start, log, logs, children
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(30)


def _launch_log(logs: Path) -> Path:
    found = list(logs.glob("launch_*.log"))
    assert len(found) == 1 and re.fullmatch(r"launch_\d{4}-\d{2}-\d{2}\.log", found[0].name), found
    return found[0]


def test_the_grace_window_is_the_documented_one_and_a_half_seconds():
    assert bootstrap._LAUNCH_GRACE_SECONDS == 1.5


@pytest.mark.parametrize("code", [1, 57], ids=["an-ordinary-error", "another-exit-code"])
def test_a_window_that_dies_at_once_is_a_failed_launch_that_says_what_the_window_said(launch, code):
    start, log, logs, children = launch
    began = time.monotonic()
    started = start(f"""
        import sys
        print("starting the window")
        sys.stderr.write("Traceback (most recent call last):\\n")
        sys.stderr.write("ModuleNotFoundError: No module named 'tkinter'\\n")
        sys.stderr.flush()
        raise SystemExit({code})
        """)
    took = time.monotonic() - began
    assert started is False, "a launch whose window is already dead must not be reported as started"
    assert bootstrap._LAUNCH_GRACE_SECONDS <= took < bootstrap._LAUNCH_GRACE_SECONDS + 5
    child, = children
    assert child.returncode == code

    launch_log = _launch_log(logs)
    text = "\n".join(log.lines)
    assert f"  ERROR: the app window failed to start (exited with code {code})." in log.lines
    assert f"  --- last lines of {launch_log.name} ---" in log.lines and "  --- end ---" in log.lines
    assert "    ModuleNotFoundError: No module named 'tkinter'" in log.lines, text
    assert "    starting the window" in log.lines, "what it printed before it died is quoted too"
    assert f"  Full launch log: {launch_log}" in log.lines
    assert log.lines.index(f"  --- last lines of {launch_log.name} ---") < log.lines.index("  --- end ---")

    captured = launch_log.read_text(encoding="utf-8")
    assert re.search(r"===== Launch \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} : .*launcher\.py =====", captured)
    assert "ModuleNotFoundError: No module named 'tkinter'" in captured and "starting the window" in captured


def test_only_the_end_of_a_long_crash_is_quoted_and_the_log_file_keeps_all_of_it(launch):
    start, log, logs, _children = launch
    assert start("""
        import sys
        for number in range(1, 61):
            print(f"line {number:02d} of the crash")
        sys.exit(2)
        """) is False
    quoted = [line.strip() for line in log.lines if "of the crash" in line]
    assert quoted == [f"line {number:02d} of the crash" for number in range(36, 61)], "the last 25 lines, in order"
    kept = _launch_log(logs).read_text(encoding="utf-8")
    assert all(f"line {number:02d} of the crash" in kept for number in range(1, 61))


def test_a_window_still_running_after_the_grace_is_a_started_launch(launch):
    start, log, logs, children = launch
    assert start("""
        import time
        print("window is up", flush=True)
        time.sleep(120)
        """) is True
    child, = children
    assert child.poll() is None, "the launch left the window running; it never waits for it or stops it"
    assert not any("ERROR" in line for line in log.lines), log.lines
    assert any(line.startswith("Launching launcher.py via ") and _launch_log(logs).name in line for line in log.lines)
    assert "window is up" in _launch_log(logs).read_text(encoding="utf-8")


def test_a_window_that_closes_cleanly_inside_the_grace_is_not_called_a_crash(launch):
    """Exit code 0 is a person closing the window at once (or a script with nothing to do), never a failure."""
    start, log, _logs, children = launch
    assert start("print('nothing to do')") is True
    child, = children
    assert child.returncode == 0
    assert not any("ERROR" in line for line in log.lines)


def test_a_crash_after_the_grace_is_outside_what_the_launch_can_report(launch, monkeypatch):
    """The grace is a window, not a watch: the launching process has gone by then. What the window said is still in
    the launch log, which is where a later failure is found."""
    monkeypatch.setattr(bootstrap, "_LAUNCH_GRACE_SECONDS", 0.5)
    start, log, logs, children = launch
    assert start("""
        import sys, time
        time.sleep(1.5)
        print("late failure", flush=True)
        sys.exit(9)
        """) is True
    child, = children
    assert child.wait(30) == 9
    assert not any("ERROR" in line for line in log.lines)
    assert "late failure" in _launch_log(logs).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
#  Smart App Control (2026-11-18): the window is started on python.exe, never pythonw.exe
# --------------------------------------------------------------------------- #
NO_WINDOW = 0x08000000
DETACHED = 0x00000008


class _Alive:
    def poll(self):
        return None


@pytest.fixture()
def fake_windows(monkeypatch, tmp_path):
    """A pretend Windows venv holding BOTH interpreters, and a recording ``Popen`` (nothing real is started)."""
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        (scripts / name).write_bytes(b"")
    target = tmp_path / "launcher.py"
    target.write_text("#", encoding="utf-8")
    spawned: list = []
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setattr(bootstrap, "VENV_DIR", tmp_path / ".venv")
    monkeypatch.setattr(bootstrap, "_launch_target", lambda: target)
    monkeypatch.setattr(bootstrap, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(bootstrap, "SCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(bootstrap, "_LAUNCH_GRACE_SECONDS", 0)
    monkeypatch.setattr(bootstrap, "_ffmpeg_in_bin", lambda: None)
    monkeypatch.setattr(bootstrap, "stale_layout_notice", lambda *a, **k: None)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", NO_WINDOW, raising=False)
    monkeypatch.setattr(subprocess, "DETACHED_PROCESS", DETACHED, raising=False)
    monkeypatch.setattr(bootstrap.subprocess, "Popen",
                        lambda argv, **kwargs: spawned.append((argv, kwargs)) or _Alive())
    return spawned, _Log(), scripts


def test_on_windows_the_venv_interpreter_is_always_python_exe_even_when_pythonw_is_there(fake_windows):
    _spawned, _log, scripts = fake_windows
    assert bootstrap.venv_python() == scripts / "python.exe"
    assert bootstrap.venv_python(windowed=True) == scripts / "python.exe", "the old windowed request no longer means pythonw"


def test_the_windows_window_starts_on_python_exe_with_no_visible_console_and_no_detached_flag(fake_windows, monkeypatch):
    spawned, log, scripts = fake_windows
    monkeypatch.setenv(bootstrap.HIDDEN_LAUNCH_ENV, "1")
    assert bootstrap.launch_gui(log) is True
    (argv, kwargs), = spawned
    assert argv[0] == str(scripts / "python.exe") and "pythonw" not in " ".join(argv).lower()
    # DETACHED_PROCESS made the venv launcher's real-interpreter child open a visible console (measured); it is not used.
    assert kwargs["creationflags"] == NO_WINDOW
    assert bootstrap.HIDDEN_LAUNCH_ENV not in kwargs["env"], "the hand-off marker is not leaked into the window"
    assert any(line.startswith("Launching launcher.py via python.exe") for line in log.lines), log.lines


def test_a_windows_window_that_cannot_be_started_is_a_failed_launch_not_a_silent_one(fake_windows, monkeypatch):
    _spawned, log, _scripts = fake_windows

    def refuse(argv, **kwargs):
        raise OSError(4551, "An Application Control policy has blocked this file")

    monkeypatch.setattr(bootstrap.subprocess, "Popen", refuse)
    assert bootstrap.launch_gui(log) is False
    assert any(line.startswith("  ERROR launching GUI:") and "4551" in line for line in log.lines), log.lines


def test_on_windows_a_venv_with_only_pythonw_is_a_failed_launch_not_a_fallback_to_it(fake_windows):
    spawned, log, scripts = fake_windows
    (scripts / "python.exe").unlink()
    assert bootstrap.launch_gui(log) is False
    assert spawned == [], "pythonw.exe was started in place of the missing interpreter"
    assert any("venv interpreter missing" in line and "python.exe" in line for line in log.lines), log.lines


def test_the_mac_launch_is_unchanged(monkeypatch, tmp_path):
    """macOS: ``.venv/bin/python``, its own session, no Windows creation flags."""
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_bytes(b"")
    target = tmp_path / "launcher.py"
    target.write_text("#", encoding="utf-8")
    spawned: list = []
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
    monkeypatch.setattr(bootstrap, "VENV_DIR", tmp_path / ".venv")
    monkeypatch.setattr(bootstrap, "_launch_target", lambda: target)
    monkeypatch.setattr(bootstrap, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(bootstrap, "SCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(bootstrap, "_LAUNCH_GRACE_SECONDS", 0)
    monkeypatch.setattr(bootstrap, "_ffmpeg_in_bin", lambda: None)
    monkeypatch.setattr(bootstrap, "stale_layout_notice", lambda *a, **k: None)
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda argv, **kw: spawned.append((argv, kw)) or _Alive())
    assert bootstrap.launch_gui(_Log()) is True
    (argv, kwargs), = spawned
    assert argv[0] == str(tmp_path / ".venv" / "bin" / "python")
    assert kwargs["start_new_session"] is True and "creationflags" not in kwargs


# ---- the hand-off that keeps the .bat's console from lingering -------------- #
@pytest.fixture()
def hand_off(monkeypatch):
    """``hand_off_launch_only`` on a pretend Windows with a console window and a recording ``Popen``."""
    spawned: list = []
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setattr(bootstrap, "_has_console_window", lambda: True)
    monkeypatch.delenv(bootstrap.HIDDEN_LAUNCH_ENV, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", NO_WINDOW, raising=False)
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda argv, **kw: spawned.append((argv, kw)) or _Alive())
    return spawned


def test_the_launch_is_handed_to_a_hidden_console_process_and_the_batch_file_is_released(hand_off):
    assert bootstrap.hand_off_launch_only() == 0
    (argv, kwargs), = hand_off
    assert argv == [sys.executable, str(bootstrap._THIS), "--launch-only"], "same interpreter, same command"
    assert kwargs["creationflags"] == NO_WINDOW
    assert kwargs["env"][bootstrap.HIDDEN_LAUNCH_ENV] == "1"
    assert kwargs["stdin"] is subprocess.DEVNULL and kwargs["stdout"] is subprocess.DEVNULL \
        and kwargs["stderr"] is subprocess.DEVNULL, "nothing of the hidden process is tied to the .bat's console"


@pytest.mark.parametrize("why", ["already-hidden", "no-console-window", "not-windows"])
def test_no_hand_off_when_there_is_nothing_to_hand_off(hand_off, monkeypatch, why):
    if why == "already-hidden":
        monkeypatch.setenv(bootstrap.HIDDEN_LAUNCH_ENV, "1")
    elif why == "no-console-window":
        monkeypatch.setattr(bootstrap, "_has_console_window", lambda: False)
    else:
        monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
    assert bootstrap.hand_off_launch_only() is None
    assert hand_off == [], "a second process was started although none was wanted (a fork loop in the making)"


def test_a_hand_off_that_cannot_start_says_so_and_fails_instead_of_reporting_a_launch(hand_off, monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(bootstrap.LOG, "line", lambda text, *a, **k: lines.append(text))

    def refuse(argv, **kwargs):
        raise OSError(5, "Access is denied")

    monkeypatch.setattr(bootstrap.subprocess, "Popen", refuse)
    assert bootstrap.hand_off_launch_only() == 1
    assert any("could not be started" in line and "Access is denied" in line for line in lines), lines


def test_main_launch_only_continues_in_the_hidden_process_and_does_not_launch_twice(monkeypatch):
    monkeypatch.setattr(bootstrap, "_platform_sane", lambda: True)
    monkeypatch.setattr(bootstrap, "_configure_hf_cache", lambda: None)
    launched: list[str] = []
    monkeypatch.setattr(bootstrap, "_launch_with_kokoro_healthcheck", lambda *a, **k: launched.append("launch") or 0)
    monkeypatch.setattr(bootstrap, "hand_off_launch_only", lambda: 0)
    assert bootstrap.main(["--launch-only"]) == 0 and launched == [], "the handed-off launch is not also run here"
    monkeypatch.setattr(bootstrap, "hand_off_launch_only", lambda: 1)
    assert bootstrap.main(["--launch-only"]) == 1 and launched == [], "a failed hand-off is a failed launch"


def test_main_launch_only_runs_the_launch_here_when_there_is_no_hand_off(monkeypatch):
    """macOS, or the hidden process itself: unchanged behaviour, including the repair-handoff exit code."""
    monkeypatch.setattr(bootstrap, "_platform_sane", lambda: True)
    monkeypatch.setattr(bootstrap, "_configure_hf_cache", lambda: None)
    monkeypatch.setattr(bootstrap, "hand_off_launch_only", lambda: None)
    monkeypatch.setattr(bootstrap, "_launch_with_kokoro_healthcheck", lambda *a, **k: bootstrap.EXIT_VENV_REPAIR_REQUIRED)
    assert bootstrap.main(["--launch-only"]) == bootstrap.EXIT_VENV_REPAIR_REQUIRED


def test_a_missing_window_script_or_interpreter_is_a_failed_launch_before_anything_starts(launch, monkeypatch, tmp_path):
    _start, log, logs, children = launch
    assert bootstrap.launch_gui(log) is False, "no launcher.py was written for this test"
    assert any("no GUI to launch" in line for line in log.lines)
    (tmp_path / "launcher.py").write_text("print('never run')", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "venv_python", lambda windowed=False: tmp_path / "no-such-python.exe")
    assert bootstrap.launch_gui(log) is False
    assert any("venv interpreter missing" in line for line in log.lines)
    assert children == [] and not logs.exists(), "nothing was started and no log was opened"


# --------------------------------------------------------------------------- #
#  The fresh-windows qualification starts the window as the launcher does, and owns only its own
# --------------------------------------------------------------------------- #
QUALIFICATION = Path(__file__).resolve().parents[1] / "dev-work" / "verification-gate" / "qualification" / "fresh_windows.py"


@pytest.fixture(scope="module")
def qualification():
    """The qualification runner's module, loaded from its file (nothing in it runs at import)."""
    if sys.platform != "win32":
        pytest.skip("the fresh-windows qualification is Windows-only")
    import importlib.util

    spec = importlib.util.spec_from_file_location("act_fresh_windows_contract", QUALIFICATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_qualification_runner_starts_no_pythonw_and_uses_the_launchers_creation_flag(qualification):
    import ast

    tree = ast.parse(QUALIFICATION.read_text(encoding="utf-8"))
    executed = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value in ("pythonw.exe", "pythonw")]
    assert executed == [], "the qualification runner still names pythonw.exe as something to start"
    assert qualification.WINDOW_FLAGS == NO_WINDOW and not qualification.WINDOW_FLAGS & DETACHED
    launch = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "launch_and_close")
    constants = {node.value for node in ast.walk(launch) if isinstance(node, ast.Constant)}
    names = {node.id for node in ast.walk(launch) if isinstance(node, ast.Name)}
    assert "python.exe" in constants and "WINDOW_FLAGS" in names, "the window is started on python.exe with the shared flag"


def _tree(tmp_path):
    """A copy folder, the launch's own process family inside it, and an unrelated application (the production one) outside."""
    copy, production = tmp_path / "Audiobook Creation Tool", tmp_path / "Production" / "Audiobook-Creation-Tool-v0.8.0"
    images = {
        100: str(copy / ".venv" / "Scripts" / "python.exe"),                        # what the run started: the venv launcher
        101: str(copy / "files" / "runtime-data" / "python" / "python.exe"),        # its child: the real interpreter
        102: r"C:\Windows\System32\conhost.exe",                                   # its hidden console
        200: str(production / ".venv" / "Scripts" / "pythonw.exe"),                 # the production window's launcher
        201: str(production / "files" / "runtime-data" / "python" / "pythonw.exe"),  # and its interpreter
    }
    table = {100: (50, "python.exe"), 101: (100, "python.exe"), 102: (101, "conhost.exe"),
             200: (60, "pythonw.exe"), 201: (200, "pythonw.exe"), 50: (1, "gate.exe")}
    return copy, production, images, table


def _window(hwnd, owner=0, cls="TkTopLevel", title="Audiobook Creation Tool"):
    return {"hwnd": hwnd, "title": title, "class": cls, "rect": [0, 0, 1, 1], "owner": owner}


def test_descendants_include_the_real_interpreter_behind_the_venv_launcher_and_nothing_else(qualification, tmp_path):
    _copy, _prod, _images, table = _tree(tmp_path)
    assert qualification.descendants_of(100, table) == {100, 101, 102}
    assert qualification.descendants_of(200, table) == {200, 201}, "the production family is a different family"


def test_an_image_is_inside_the_copy_only_when_it_is_really_inside_it(qualification, tmp_path):
    copy, production, images, _table = _tree(tmp_path)
    assert qualification.inside(images[101], copy) and qualification.inside(images[100], copy)
    assert not qualification.inside(images[201], copy) and not qualification.inside(images[102], copy)
    assert not qualification.inside(str(tmp_path / "Audiobook Creation Tool-evil" / "python.exe"), copy), "a sibling that shares the prefix"
    assert not qualification.inside("?", copy) and not qualification.inside("", copy), "an unreadable image is never inside"


def test_the_window_is_the_one_of_the_interpreter_inside_this_copy_below_the_started_process(qualification, tmp_path):
    copy, _prod, images, table = _tree(tmp_path)
    shown = {101: [_window(1011)], 201: [_window(2011)]}  # the production application's window is visible too
    found = qualification.owned_window(100, copy, table, lambda pid: shown.get(pid, []), images.get)
    assert found and found["hwnd"] == 1011 and found["pid"] == 101 and found["image"] == images[101]


@pytest.mark.parametrize("why", ["only-the-production-window", "owned-popup", "not-a-tk-window", "descendant-outside-the-copy"])
def test_no_other_window_is_ever_a_candidate_for_close(qualification, tmp_path, why):
    copy, _prod, images, table = _tree(tmp_path)
    shown = {201: [_window(2011)]}
    if why == "owned-popup":
        shown = {101: [_window(1012, owner=1011)]}
    elif why == "not-a-tk-window":
        shown = {101: [_window(1013, cls="Chrome_WidgetWin_1")]}
    elif why == "descendant-outside-the-copy":
        table[103] = (101, "python.exe")  # started by the window, but a Python that is not the copy's
        images[103] = r"C:\Python312\python.exe"
        shown = {103: [_window(1031)]}
    assert qualification.owned_window(100, copy, table, lambda pid: shown.get(pid, []), images.get) is None


def test_stopping_the_launch_ends_only_its_own_processes_deepest_first(qualification, tmp_path):
    copy, _prod, images, table = _tree(tmp_path)
    ended: list[int] = []
    result = qualification.stop_owned(100, copy, table, images.get, ended.append)
    assert result == ended == [101, 100], "the interpreter before its launcher; not the console, not the production application"
    assert not {102, 200, 201} & set(ended)


def test_a_process_that_cannot_be_ended_is_skipped_not_fatal(qualification, tmp_path):
    copy, _prod, images, table = _tree(tmp_path)

    def refuse(pid):
        if pid == 101:
            raise OSError("access denied")

    assert qualification.stop_owned(100, copy, table, images.get, refuse) == [100]
