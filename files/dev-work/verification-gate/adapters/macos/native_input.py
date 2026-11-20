"""The macOS stand-in for ``adapters/windows/native_input.py`` (v0.8.x P1B, plan section 14.3, MAC-045, D9).

There is no macOS native-input adapter in this programme: no synthetic mouse or keyboard, no Accessibility and no Screen
Recording grant. The journeys' *behaviour* is still driven, by the in-process session (``app_session.py``), which acts
through Tk itself. This module gives the journeys the few names they read from the native layer, answered from that
session: the window's size and place (Tk's own), the dialogs the session's stand-ins hold open, and a process's program
name. Everything that only exists to test the Windows input harness itself raises :class:`NotApplicableOnMacOS` -- those
scenarios are mapped NOT APPLICABLE ON MACOS in ``verification.json``'s ``acceptance.darwin_map``, never run as a pass.
"""

from __future__ import annotations

import contextlib
import ctypes
import fcntl
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

GATE_DIR = Path(__file__).resolve().parents[2]
LEASE_FILE = GATE_DIR / "outputs" / ".macos-acceptance-lease"

#: The sessions alive in this process, by the handle the journeys hold (the interpreter's pid stands for its window).
SESSIONS: dict = {}


class DesktopUnavailable(RuntimeError):
    """No usable Aqua login session: nothing can be driven, so the stage is BLOCKED (never a pass)."""


class ForegroundLost(DesktopUnavailable):
    """Kept for the journeys' names; the in-process session never depends on the foreground."""


class InputRefused(RuntimeError):
    """A target that cannot honestly be acted on: absent, not on screen, or disabled."""


class ScreenshotRefused(DesktopUnavailable):
    """Kept for the journeys' names."""


class NotApplicableOnMacOS(RuntimeError):
    """A Windows input-harness mechanic. Its scenario is NOT APPLICABLE ON MACOS (darwin_map class c)."""


def _windows_only(name: str):
    def refuse(*_args, **_kwargs):
        raise NotApplicableOnMacOS(f"{name} is a Windows input-harness mechanic; its scenario is mapped NOT APPLICABLE ON MACOS")

    return refuse


for _name in ("move_to", "click_at", "wheel_at", "key_tap", "key_chord", "type_text", "nudge_foreground_rights",
              "cursor_position", "move_window", "root_window_at", "window_pid"):
    globals()[_name] = _windows_only(_name)

SM_XVIRTUALSCREEN = SM_CXVIRTUALSCREEN = None
user = None


def set_dpi_aware() -> None:
    """Nothing to do: Tk reports points on macOS, and the session reads Tk's own geometry."""


@dataclass
class DesktopStatus:
    ok: bool
    reason: str = ""
    facts: dict = field(default_factory=dict)


def desktop_status() -> DesktopStatus:
    """A logged-in Aqua session is what Tk needs to open a window. Read without opening one (no dialog can block)."""
    facts: dict = {}
    try:
        done = subprocess.run(["/bin/launchctl", "managername"], capture_output=True, text=True, timeout=10)
        facts["manager"] = done.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return DesktopStatus(False, f"launchctl could not say which session this is: {exc}", facts)
    if facts["manager"] != "Aqua":
        return DesktopStatus(False, f"this is a {facts['manager'] or 'non-GUI'} session, not a logged-in Aqua session", facts)
    return DesktopStatus(True, "", facts)


class DesktopLease:
    """One macOS acceptance run at a time on this machine: an exclusive lock that ends with the process holding it."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or LEASE_FILE)
        self.handle = None

    def __enter__(self) -> "DesktopLease":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise DesktopUnavailable(f"another macOS acceptance run holds {self.path}") from None
        self.handle = handle
        return self

    def __exit__(self, *_exc) -> None:
        if self.handle is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None


# --------------------------------------------------------------------------------------------------------------- #
#  Answered from the in-process session
# --------------------------------------------------------------------------------------------------------------- #
def _session(handle):
    session = SESSIONS.get(int(str(handle).split(":")[0]) if isinstance(handle, str) else int(handle))
    if session is None or session.client is None:
        return None
    return session


def windows_of(pid: int) -> list[dict]:
    """The application's own windows that are on screen, and the dialogs its stand-ins hold open."""
    session = _session(pid)
    if session is None:
        return []
    # Each Tk top-level, as Windows lists them: the main window by the pid that stands for it, any other by its own handle.
    windows = [{"hwnd": int(pid) if item["path"] == "." else f"{pid}:{item['path']}", "title": item.get("title", ""),
                "class": "TkTopLevel", "owner": None if item["path"] == "." else int(pid), "path": item["path"]}
               for item in session.client.call("toplevels")["toplevels"]]
    return windows + native_dialogs_of(pid)


def native_dialogs_of(pid: int) -> list[dict]:
    session = _session(pid)
    if session is None:
        return []
    return [{"hwnd": f"{pid}:dialog:{item['id']}", "title": item["title"], "class": "#32770", "owner": int(pid),
             "kind": item["kind"], "message": item.get("message", "")} for item in session.pending_dialogs()]


def child_controls(hwnd) -> list[dict]:
    session = _session(hwnd)
    if session is None:
        return []
    number = int(str(hwnd).rsplit(":", 1)[1])
    for item in session.pending_dialogs():
        if item["id"] == number:
            texts = [text for text in (item.get("message"), item.get("detail")) if text]
            return [{"class": "Static", "title": text} for text in texts] + [
                {"class": "Button", "title": button} for button in item.get("buttons", [])]
    return []


def client_size(hwnd) -> tuple[int, int]:
    window = _session(hwnd).client.call("window")
    return window["width"], window["height"]


def window_rect(hwnd) -> tuple[int, int, int, int]:
    window = _session(hwnd).client.call("window")
    return window["x"], window["y"], window["x"] + window["width"], window["y"] + window["height"]


def client_on_screen(hwnd) -> tuple[int, int, int, int]:
    return window_rect(hwnd)


_VISIBLE = None


def visible_frame() -> tuple[int, int, int, int]:
    """The main screen less the menu bar and the Dock, in Tk's top-left points: AppKit's ``visibleFrame``, read through
    JavaScript for Automation (no Accessibility grant: it asks AppKit about the screen, never about another app)."""
    global _VISIBLE
    if _VISIBLE is None:
        script = ('ObjC.import("AppKit"); var s = $.NSScreen.mainScreen, f = s.visibleFrame, g = s.frame; '
                  'JSON.stringify([f.origin.x, f.origin.y, f.size.width, f.size.height, g.size.height])')
        done = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", script], capture_output=True, text=True, timeout=20)
        x, y, width, height, screen_height = (int(round(float(v))) for v in json.loads(done.stdout))
        top = screen_height - (y + height)  # AppKit counts from the bottom, Tk from the top
        _VISIBLE = (x, top, x + width, top + height)
    return _VISIBLE


def work_area(hwnd) -> tuple[int, int, int, int]:
    return visible_frame()


def resize_client(hwnd, width: int, height: int) -> None:
    """The window manager's resize as Windows' counterpart makes it: the content area at the size asked for, the window
    moved up or left if it would otherwise leave the visible screen; refused when the visible screen cannot hold it."""
    left, top, right, bottom = visible_frame()
    session = _session(hwnd)
    window = session.client.call("window")
    title_bar = int(window.get("frame_top", 0))
    if width > right - left or height + title_bar > bottom - top:
        raise DesktopUnavailable(f"{width}x{height}: the visible screen {right - left}x{bottom - top} cannot hold it")
    x = min(max(window["x"], left), right - width)
    y = min(max(window["y"] - title_bar, top), bottom - height - title_bar)
    session.client.call("geometry", width=int(width), height=int(height), x=int(x), y=int(y))


def acquire_foreground(hwnd, attempts: int = 6) -> bool:
    """The in-process session acts through Tk, so the foreground decides nothing; the window is raised for the record."""
    session = _session(hwnd)
    if session is not None:
        session.client.call("raise")
    return True


def foreground_owner() -> tuple[int, int]:
    """In-process, the nearest thing to the foreground: the application's top-level that holds Tk's keyboard focus, by
    the handle ``windows_of`` gives it. Only meaningful with one session running (the journeys that ask have one)."""
    live = [session for session in SESSIONS.values() if session.client is not None]
    if len(live) != 1:
        raise NotApplicableOnMacOS("the foreground owner is a Windows input-harness mechanic")
    session = live[0]
    focus = session.client.call("window").get("focus_toplevel")
    if focus is None:
        return 0, 0
    return (session.pid if focus == "." else f"{session.pid}:{focus}"), session.pid


def screenshot(*_args, **_kwargs) -> dict:
    return {"captured": False, "why": "no Screen Recording grant (D9): the picture is the owner-manual visual check"}


# --------------------------------------------------------------------------------------------------------------- #
#  A process's program, by pid (libproc)
# --------------------------------------------------------------------------------------------------------------- #
_libproc = None


def image_name(pid: int) -> str:
    """The executable's file name (``ffmpeg``), or '' when the process is gone. Read from the kernel, never matched to act on."""
    global _libproc
    if _libproc is None:
        _libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        _libproc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        _libproc.proc_pidpath.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(4096)
    length = _libproc.proc_pidpath(int(pid), buffer, 4096)
    return os.path.basename(buffer.value.decode("utf-8", "replace")) if length > 0 else ""
