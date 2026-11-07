"""Real Windows input and window supervision, standard library only (plan section 8; the adapter piloted in v0.7.2 Phase 0).

UI Automation sees every Tk widget as an unnamed pane, so a pywinauto adapter would be blind and would need the same observation
channel this one uses. Nothing here is a simulated click: mouse and keyboard reach the application through ``SendInput``, and the
guards make sure they reach only an owned window.

**Nothing is sent unless the foreground window belongs to the owned process, and for a click, unless the point is that window's.** A
press and release go in one ``SendInput`` call, which Windows documents as uninterrupted by other input. A bare ALT tap is the usual
way to win the foreground and it is not used here, because it lands on whatever has the foreground at that moment, which may be the
owner's editor. A zero key event is what unlocks ``SetForegroundWindow``, and it means nothing to the application receiving it.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import time
from dataclasses import dataclass, field
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_WHEEL, MOUSEEVENTF_VIRTUALDESK, MOUSEEVENTF_ABSOLUTE = 0x0800, 0x4000, 0x8000
VK = {"return": 0x0D, "tab": 0x09, "escape": 0x1B, "down": 0x28, "up": 0x26, "left": 0x25, "right": 0x27, "end": 0x23, "home": 0x24,
      "delete": 0x2E, "backspace": 0x08, "space": 0x20, "control": 0x11, "shift": 0x10, "alt": 0x12, "a": 0x41, "f4": 0x73, "f24": 0x87}
WM_CLOSE = 0x0010
SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
GW_OWNER = 4
GA_ROOT = 2
UOI_NAME = 2
DESKTOP_READOBJECTS, DESKTOP_SWITCHDESKTOP = 0x0001, 0x0100
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
SM_SWAPBUTTON, SM_REMOTESESSION, SM_CMONITORS = 23, 0x1000, 80
ERROR_ALREADY_EXISTS = 183
WTS_CURRENT_SERVER_HANDLE = 0
WTSConnectState = 8
WTSActive = 0

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", _INPUTUNION)]


WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = w.UINT
user32.EnumWindows.argtypes = [WNDENUMPROC, w.LPARAM]
user32.EnumChildWindows.argtypes = [w.HWND, WNDENUMPROC, w.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.GetForegroundWindow.restype = w.HWND
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.GetWindow.argtypes = [w.HWND, w.UINT]
user32.GetWindow.restype = w.HWND
user32.IsWindowVisible.argtypes = [w.HWND]
user32.IsWindow.argtypes = [w.HWND]
user32.IsIconic.argtypes = [w.HWND]
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.WindowFromPoint.argtypes = [w.POINT]
user32.WindowFromPoint.restype = w.HWND
user32.GetAncestor.argtypes = [w.HWND, w.UINT]
user32.GetAncestor.restype = w.HWND
user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
user32.OpenInputDesktop.restype = w.HANDLE
user32.OpenInputDesktop.argtypes = [w.DWORD, w.BOOL, w.DWORD]
user32.GetThreadDesktop.argtypes = [w.DWORD]
user32.GetThreadDesktop.restype = w.HANDLE
user32.CloseDesktop.argtypes = [w.HANDLE]
user32.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
user32.GetDpiForWindow.argtypes = [w.HWND]
user32.GetDpiForWindow.restype = w.UINT
kernel32.CreateMutexW.argtypes = [w.LPVOID, w.BOOL, w.LPCWSTR]
kernel32.CreateMutexW.restype = w.HANDLE
kernel32.CloseHandle.argtypes = [w.HANDLE]
kernel32.GetCurrentThreadId.restype = w.DWORD
kernel32.GetCurrentProcessId.restype = w.DWORD
kernel32.ProcessIdToSessionId.argtypes = [w.DWORD, ctypes.POINTER(w.DWORD)]
wtsapi32.WTSQuerySessionInformationW.argtypes = [w.HANDLE, w.DWORD, ctypes.c_int, ctypes.POINTER(w.LPWSTR), ctypes.POINTER(w.DWORD)]
wtsapi32.WTSFreeMemory.argtypes = [w.LPVOID]


class DesktopUnavailable(RuntimeError):
    """The interactive desktop a native journey needs is not there, or not ours to use: BLOCKED, never a pass."""


class ForegroundLost(DesktopUnavailable):
    """An input was about to go somewhere that is not the owned window. It was not sent."""


class InputRefused(RuntimeError):
    """A target failed its check immediately before input: covered, disabled, off the window, or ambiguous. Nothing was sent."""


def set_dpi_aware() -> None:
    """Coordinates in physical pixels, for this process only. Call once before reading any geometry."""
    try:
        user32.SetProcessDpiAwarenessContext.restype = w.BOOL
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except AttributeError:
        user32.SetProcessDPIAware()


# -- input ----------------------------------------------------------------------------------- #
def _send(*inputs: INPUT) -> None:
    array = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        # On a locked or secure desktop this is the error that comes back: blocked by UIPI or no input desktop.
        raise DesktopUnavailable(f"SendInput delivered {sent}/{len(inputs)}: error {ctypes.get_last_error()}")


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    item = INPUT(type=INPUT_MOUSE)
    item.mi = MOUSEINPUT(dx, dy, data, flags, 0, 0)
    return item


def _key(vk: int, *, up: bool = False, scan: int = 0, unicode_char: bool = False) -> INPUT:
    item = INPUT(type=INPUT_KEYBOARD)
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_UNICODE if unicode_char else 0)
    item.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return item


def _absolute(x: int, y: int) -> tuple[int, int]:
    left, top = user32.GetSystemMetrics(SM_XVIRTUALSCREEN), user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width, height = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return int((x - left) * 65535 / (width - 1)), int((y - top) * 65535 / (height - 1))


_MOVE = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK


def move_to(x: int, y: int) -> None:
    _send(_mouse(_MOVE, *_absolute(x, y)))


def click_at(x: int, y: int) -> None:
    dx, dy = _absolute(x, y)
    _send(_mouse(_MOVE, dx, dy), _mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP))


def wheel_at(x: int, y: int, notches: int) -> None:
    dx, dy = _absolute(x, y)
    _send(_mouse(_MOVE, dx, dy), _mouse(MOUSEEVENTF_WHEEL, data=ctypes.c_uint32(notches * 120 & 0xFFFFFFFF).value))


def key_tap(name: str) -> None:
    code = VK[name]
    _send(_key(code), _key(code, up=True))


def key_chord(modifier: str, name: str) -> None:
    held, code = VK[modifier], VK[name]
    _send(_key(held), _key(code), _key(code, up=True), _key(held, up=True))


def type_text(text: str, pause: float = 0.002) -> None:
    for char in text:
        code = ord(char)
        _send(_key(0, scan=code, unicode_char=True), _key(0, scan=code, unicode_char=True, up=True))
        time.sleep(pause)


def nudge_foreground_rights() -> None:
    """A zero key event: the receiving window sees nothing, and this process has now sent the last input, which is what Windows asks."""
    _send(_key(0), _key(0, up=True))


def cursor_position() -> tuple[int, int]:
    point = w.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


# -- windows --------------------------------------------------------------------------------- #
def window_pid(hwnd: int) -> int:
    pid = w.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def client_size(hwnd: int) -> tuple[int, int]:
    rect = w.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def _describe(hwnd: int) -> dict:
    title, cls = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, 512)
    user32.GetClassNameW(hwnd, cls, 256)
    return {"hwnd": int(hwnd), "title": title.value, "class": cls.value, "rect": list(window_rect(hwnd)),
            "owner": int(user32.GetWindow(hwnd, GW_OWNER) or 0)}


def windows_of(pid: int) -> list[dict]:
    """Visible top-level windows owned by exactly this process. Nothing else is ever a candidate for input."""
    found: list[dict] = []

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        if window_pid(hwnd) == pid and user32.IsWindowVisible(hwnd):
            found.append(_describe(hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return found


def native_dialogs_of(pid: int) -> list[dict]:
    return [window for window in windows_of(pid) if window["class"] == "#32770"]


def child_controls(hwnd: int) -> list[dict]:
    found: list[dict] = []

    @WNDENUMPROC
    def callback(child, _lparam):
        if user32.IsWindowVisible(child):
            found.append(_describe(child))
        return True

    user32.EnumChildWindows(hwnd, callback, 0)
    return found


def resize_client(hwnd: int, width: int, height: int) -> None:
    """Resize through the window manager so the CLIENT area asks for width x height: Tk's geometry is the client size."""
    left, top, right, bottom = window_rect(hwnd)
    client_w, client_h = client_size(hwnd)
    if not user32.SetWindowPos(hwnd, None, left, top, width + (right - left - client_w), height + (bottom - top - client_h),
                               SWP_NOZORDER | SWP_NOACTIVATE):
        raise OSError(f"SetWindowPos failed: {ctypes.get_last_error()}")


def foreground_owner() -> tuple[int, int]:
    hwnd = user32.GetForegroundWindow()
    return int(hwnd or 0), window_pid(hwnd) if hwnd else 0


def acquire_foreground(hwnd: int, attempts: int = 6) -> bool:
    """Bring the owned window forward with no keystroke that anything else could read. Records nothing; the caller checks."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    for _ in range(attempts):
        nudge_foreground_rights()
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.08)
        if foreground_owner()[0] == int(hwnd):
            return True
    return False


def root_window_at(x: int, y: int) -> int:
    hwnd = user32.WindowFromPoint(w.POINT(x, y))
    return int(user32.GetAncestor(hwnd, GA_ROOT) or 0) if hwnd else 0


def _client_on_screen(hwnd: int) -> tuple[int, int, int, int]:
    origin = w.POINT(0, 0)
    user32.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    width, height = client_size(hwnd)
    return origin.x, origin.y, origin.x + width, origin.y + height


class ScreenshotRefused(DesktopUnavailable):
    """The owned window's client area was not wholly its own on screen, so a picture of it could show something else."""


def screenshot(hwnd: int, path: Path) -> dict:
    """Only the owned window's client area, and only while nothing else lies over it, so no other content of the desktop can reach evidence.

    The frame is left out because its invisible resize border and rounded corners show whatever is behind. ``PrintWindow``, which would
    avoid all of this, is not used: measured on this Tk, a second call leaves the application's main thread unresponsive for over 30 s, and
    a test tool must not disturb what it tests.
    """
    from PIL import ImageGrab

    left, top, right, bottom = _client_on_screen(hwnd)
    for fraction_y in (0.02, 0.25, 0.5, 0.75, 0.98):
        for fraction_x in (0.02, 0.25, 0.5, 0.75, 0.98):
            x, y = int(left + (right - left) * fraction_x), int(top + (bottom - top) * fraction_y)
            if root_window_at(x, y) != int(hwnd):
                raise ScreenshotRefused(f"another window covers the owned window at {x},{y}; no picture was taken")
    image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return {"size": list(image.size), "rect": [left, top, right, bottom]}


# -- the desktop ----------------------------------------------------------------------------- #
def _desktop_name(handle: int) -> str | None:
    needed = w.DWORD()
    buffer = ctypes.create_unicode_buffer(256)
    if not user32.GetUserObjectInformationW(handle, UOI_NAME, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)):
        return None
    return buffer.value


def _session_connected() -> bool | None:
    session = w.DWORD()
    if not kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(session)):
        return None
    buffer, size = w.LPWSTR(), w.DWORD()
    if not wtsapi32.WTSQuerySessionInformationW(WTS_CURRENT_SERVER_HANDLE, session.value, WTSConnectState, ctypes.byref(buffer),
                                                ctypes.byref(size)):
        return None
    try:
        state = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int)).contents.value
    finally:
        wtsapi32.WTSFreeMemory(buffer)
    return state == WTSActive


@dataclass
class DesktopStatus:
    ok: bool
    reason: str = ""
    facts: dict = field(default_factory=dict)


def desktop_status() -> DesktopStatus:
    """The preconditions that can be read without touching anything. A handle alone proves little (Microsoft says a disconnected session
    can still get one), so a session also does a real input round trip in its own window before it counts as usable."""
    facts = {"remote_session": bool(user32.GetSystemMetrics(SM_REMOTESESSION)), "monitors": user32.GetSystemMetrics(SM_CMONITORS),
             "swapped_mouse_buttons": bool(user32.GetSystemMetrics(SM_SWAPBUTTON)), "system_dpi": user32.GetDpiForSystem(),
             "session_connected": _session_connected()}
    if facts["session_connected"] is False:
        return DesktopStatus(False, "this Windows session is not connected to a display (disconnected or locked out)", facts)
    desktop = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS | DESKTOP_SWITCHDESKTOP)
    if not desktop:
        return DesktopStatus(False, f"the input desktop cannot be opened (error {ctypes.get_last_error()}): the session is probably "
                                    "locked or showing a secure desktop", facts)
    try:
        input_name = _desktop_name(desktop)
    finally:
        user32.CloseDesktop(desktop)
    own_name = _desktop_name(user32.GetThreadDesktop(kernel32.GetCurrentThreadId()))
    facts.update(input_desktop=input_name, thread_desktop=own_name)
    if input_name is None or own_name is None or input_name.lower() != own_name.lower():
        return DesktopStatus(False, f"input goes to desktop {input_name!r} and this process is on {own_name!r}", facts)
    if not facts["monitors"]:
        return DesktopStatus(False, "no display monitor is present", facts)
    if facts["swapped_mouse_buttons"]:
        return DesktopStatus(False, "the primary mouse button is swapped: a synthetic left click would be a right click", facts)
    return DesktopStatus(True, "", facts)


class DesktopLease:
    """One native run per desktop session, so two runs can never drive each other's windows. Ends with the process that holds it."""

    NAME = "Local\\ACT-Native-Acceptance-Lease"

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.NAME
        self.handle = None

    def __enter__(self) -> "DesktopLease":
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, True, self.name)
        already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        if not handle or already:
            if handle:
                kernel32.CloseHandle(handle)
            raise DesktopUnavailable(f"another native run holds the desktop lease {self.name}")
        self.handle = handle
        return self

    def __exit__(self, *_exc) -> None:
        if self.handle:
            kernel32.ReleaseMutex(self.handle)
            kernel32.CloseHandle(self.handle)
            self.handle = None
