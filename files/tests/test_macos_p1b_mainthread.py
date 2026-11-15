"""v0.8.x P1B, MAC-032 -- the Tk/AppKit thread rule under load, on the real macOS window.

AppKit draws only on the main thread, and Tk on macOS is not safe to call from another thread. The tools' rule is that
a worker never touches Tk: it puts immutable values on a queue the main thread drains (``shared.job_ui``). This holds
that rule to account while it is busiest: the REAL launcher's window, the REAL MP3 Tool panel, a real Combine of three
half-hour tracks (FFmpeg's progress drives the panel the whole time), and the window resized by the window manager's
own request (``wm geometry``) a hundred and fifty times meanwhile. Every call into the window's Tcl interpreter is
checked for the thread it comes from; one call from any other thread fails the test. The run must also end SUCCEEDED,
and the main thread must never have been held up for long.

The same audit runs on every macOS acceptance journey (``adapters/macos``), which drives all five tools end to end.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
from pathlib import Path

import pytest

NATIVE_P1B = "native macOS only (P1B): Aqua Tk 9 shell, POSIX containment and macOS filesystem checks"
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason=NATIVE_P1B)

#: Conversions of values already in hand; they read nothing of the interpreter's state.
_PURE = frozenset({"getint", "getdouble", "getboolean", "splitlist", "split", "wantobjects"})


class ThreadCheckingTk:
    """Every call into the window's Tcl interpreter, checked for the thread it comes from."""

    def __init__(self, real, record: list) -> None:
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_record", record)
        object.__setattr__(self, "_main", threading.main_thread())

    def __getattr__(self, name):
        value = getattr(self._real, name)
        if name in _PURE or not callable(value):
            return value

        def checked(*args, **kwargs):
            if threading.current_thread() is not self._main:
                self._record.append((threading.current_thread().name, name, str(args[:1])[:80],
                                     "".join(traceback.format_stack(limit=6))[-800:]))
            return value(*args, **kwargs)

        return checked

    def __setattr__(self, name, value):
        setattr(self._real, name, value)


def test_a_real_combine_under_continuous_resizing_makes_no_tk_call_off_the_main_thread(tmp_path, monkeypatch):
    import tkinter as tk
    from tkinter import filedialog

    import launcher
    import test_ffmpeg_cancel as cx
    from shared import config, ffmpeg_utils, output_paths
    from shared import settings as app_settings
    from tk_gate import open_tk_root

    if not ffmpeg_utils.ffmpeg_path():
        pytest.fail("the adopted FFmpeg is not pinned in this checkout; set the app up before MAC-032")
    folder = tmp_path / "media"
    folder.mkdir()
    segment = folder / "segment.mp3"
    cx.sp.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
               "-i", "sine=frequency=440:duration=600", "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "64k",
               "-write_xing", "0", "-id3v2_version", "0", "-write_id3v1", "0", str(segment)], check=True)
    tracks = []
    for index in range(3):
        track = folder / f"{index + 1:02d}.mp3"
        track.write_bytes(segment.read_bytes() * 3)  # thirty minutes each
        tracks.append(track)
    outputs = tmp_path / "Outputs"
    outputs.mkdir()
    app_settings.set("output_base_directory", str(outputs))
    app_settings.set("last_tool", "mp3_tool")
    config.invalidate()  # the process's cached snapshot may predate this test (one pytest process runs many files)
    # Fail closed: the run must publish into this test's own folder, never the real default output location.
    assert output_paths.resolve_output_base() == outputs, output_paths.resolve_output_base()
    monkeypatch.setattr(filedialog, "askopenfilenames", lambda **_kw: tuple(str(t) for t in tracks))

    off_thread: list = []
    root = open_tk_root(tk)
    root.tk = ThreadCheckingTk(root.tk, off_thread)  # before any widget exists, so every widget shares it
    try:
        app = launcher.LauncherApp(root)
        app.select_tool("mp3_tool")
        for _ in range(10):
            root.update()
        panel = app.containers["mp3_tool"].winfo_children()[0]
        panel.btn_add_files.invoke()
        deadline = time.monotonic() + 60
        while panel.track_list.size() < 3 and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert panel.track_list.size() == 3
        album = next(row for key, row in panel.surface._rows.items()
                     if str(getattr(key, "value", getattr(key, "name", key))).lower() == "album")
        album.shared_entry.focus_force()
        album.shared_entry.delete(0, "end")
        for character in "Stress":
            album.shared_entry.event_generate("<KeyPress>", keysym=character)
            album.shared_entry.event_generate("<KeyRelease>", keysym=character)
        root.update()
        assert album.shared_entry.get() == "Stress"
        panel.btn_combine.invoke()

        sizes = [(1120, 800), (1300, 840), (1200, 820), (1400, 840)]
        resized, longest_gap, last = 0, 0.0, time.monotonic()
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            current = getattr(panel, "jobs", None)
            state = getattr(getattr(current, "state", None), "name", str(getattr(current, "state", "")))
            if resized >= 150 and state in ("SUCCEEDED", "FAILED", "CANCELLED", "COMPLETED_WITH_FAILURES"):
                break
            if resized < 150:
                width, height = sizes[resized % len(sizes)]
                root.geometry(f"{width}x{height}")
                resized += 1
            root.update()
            now = time.monotonic()
            longest_gap = max(longest_gap, now - last)
            last = now
            time.sleep(0.005)
        print(f"MAC-032: {resized} resizes, final state {state}, longest main-thread turn {longest_gap * 1000:.0f} ms")
        assert resized == 150
        assert state == "SUCCEEDED", f"the Combine ended {state}"
        assert off_thread == [], f"{len(off_thread)} Tk call(s) from a worker thread: {off_thread[:3]}"
        assert longest_gap < 2.0, f"the main thread was held for {longest_gap:.2f} s"
        published = [p for p in outputs.rglob("*.mp3") if ".work" not in p.parts]
        assert len(published) == 1 and published[0].stat().st_size > 0
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
        config.invalidate()
