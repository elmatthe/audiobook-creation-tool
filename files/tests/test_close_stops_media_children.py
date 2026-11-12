"""Closing the window ends the FFmpeg it started, and nothing else (v0.7.2 Phase 3).

The native journeys ``shutdown.*`` prove this on the real application. Here the identity rule is proved directly: a process is ended only when
its parent is this very process and its image is a media tool, so a sentinel FFmpeg started by anyone else and a helper of this process both live.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shared import subprocess_utils as sp
import source_probe

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process identity")

PING = Path(r"C:\Windows\System32\PING.EXE")


@pytest.fixture
def named_ffmpeg(tmp_path) -> Path:
    """A real, long-running, harmless program under the image name the rule looks for, so no codec work is needed to test identity."""
    target = tmp_path / "ffmpeg.exe"
    shutil.copyfile(PING, target)
    return target


def _alive(process: subprocess.Popen) -> bool:
    return process.poll() is None


def _wait_gone(process: subprocess.Popen, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return True
        time.sleep(0.02)
    return False


def _long(image: Path, **kwargs) -> subprocess.Popen:
    return subprocess.Popen([str(image), "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def test_a_child_ffmpeg_is_ended(named_ffmpeg):
    child = _long(named_ffmpeg)
    try:
        assert _alive(child)
        assert child.pid in sp.stop_media_children()
        assert _wait_gone(child), "the child FFmpeg is still running"
    finally:
        child.kill()


def test_a_child_with_another_image_name_lives(named_ffmpeg, tmp_path):
    other = tmp_path / "helper.exe"
    shutil.copyfile(PING, other)
    child = _long(other)
    media = _long(named_ffmpeg)
    try:
        assert sp.stop_media_children() == [media.pid], "the control: the rule ran and found the media child"
        assert _alive(child), "a helper of this process was ended"
    finally:
        child.kill()
        media.kill()


def test_an_ffmpeg_started_by_someone_else_lives(named_ffmpeg, tmp_path):
    """The name is not enough. This one's parent is another process, which is the shape of the owner's own FFmpeg in another program."""
    pid_file = tmp_path / "pid.txt"
    starter = subprocess.Popen([sys.executable, "-c",
                                "import subprocess,sys,time\n"
                                f"p=subprocess.Popen([{str(named_ffmpeg)!r},'-n','60','127.0.0.1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
                                f"open({str(pid_file)!r},'w').write(str(p.pid))\n"
                                "time.sleep(60)\n"])
    own = _long(named_ffmpeg)
    try:
        deadline = time.monotonic() + 30
        while not (pid_file.is_file() and pid_file.read_text()) and time.monotonic() < deadline:
            time.sleep(0.05)
        sentinel = int(pid_file.read_text())
        stopped = sp.stop_media_children()
        assert own.pid in stopped, "the no-change control: this process's own child is ended"
        assert sentinel not in stopped, "an FFmpeg this process did not start was ended"
        check = subprocess.run(["tasklist", "/FI", f"PID eq {sentinel}", "/NH"], capture_output=True, text=True)
        assert str(sentinel) in check.stdout, "the sentinel FFmpeg is gone"
    finally:
        own.kill()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(starter.pid)], capture_output=True)
        starter.wait(timeout=20)


def test_with_nothing_to_stop_it_is_quiet():
    assert sp.stop_media_children() == []


def test_it_never_raises_when_windows_refuses(monkeypatch):
    import ctypes

    def broken(*_args, **_kwargs):
        raise OSError("no")

    monkeypatch.setattr(ctypes, "WinDLL", broken)
    assert sp.stop_media_children() == []


@pytest.mark.parametrize("module,cls", [("mp3/mp3_tool.py", "MP3ToolUI"), ("m4b/maker/m4b_maker.py", "M4BMakerUI"),
                                        ("m4b/metadata/m4b_metadata_editor.py", "M4BMetadataEditorUI"),
                                        ("m4b/converter/m4b_converter.py", "M4BConverterUI"), ("artwork/cover_resizer.py", "CoverResizerUI"),
                                        ("tts/epub2tts_gui.py", "TtsPanel")])
def test_every_tool_panel_reaches_close_when_its_window_is_destroyed(module, cls):
    """A panel without this is the measured failure: root.destroy() never reaches close(), so a running worker is never told to stop."""
    tree = source_probe.module(module)
    panel = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == cls)
    destroy = next((node for node in panel.body if isinstance(node, ast.FunctionDef) and node.name == "destroy"), None)
    assert destroy is not None, f"{cls} has no destroy()"
    calls = [node.func.attr for node in ast.walk(destroy) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert "close" in calls and "destroy" in calls, f"{cls}.destroy() must call close() and its parent's destroy()"


def test_the_launcher_stops_media_children_once_its_main_loop_has_ended():
    tree = source_probe.module("launcher.py")
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    order = [node.func.attr for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert "mainloop" in order and "stop_media_children" in order
    assert order.index("mainloop") < order.index("stop_media_children")
