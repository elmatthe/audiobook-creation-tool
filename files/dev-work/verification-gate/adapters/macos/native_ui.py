"""Inside the application process on macOS: pictures of its own windows, and its own native panels watched and answered.

v0.8.x P1B closeout (owner's revised acceptance, 2026-11-15). Loaded only by ``app_launcher.py`` (the gate's in-process driver)
inside an isolated ACT instance; never shipped, never imported by the application.

What macOS lets a process do without any privacy grant, and what this module therefore does:

  * **Pictures of its own windows.** ``CGWindowListCreateImage`` with ``kCGWindowListOptionIncludingWindow`` returns the window
    server's composited image of one window, title bar included, and for a window the calling process owns it needs no Screen
    Recording permission (measured on this Mac, macOS 27.0.1, with ``CGPreflightScreenCaptureAccess()`` false). Only that window
    is imaged: nothing behind it, no other application, no desktop. A window whose content another process draws -- the
    file panel's browser is the ``openAndSavePanelService``'s remote view -- comes back without that content; such an image is
    recorded as not evidence of the panel's content.
  * **Its own native panels, watched from a worker thread.** While an ``NSOpenPanel`` or ``NSAlert`` is modal the main thread
    is inside AppKit's modal loop and Tcl's event loop does not run (measured: no ``after`` fired during an open panel), so the
    channel cannot answer then. A worker thread reads the panel instead (``NSApp.windows``, the panel's own getters), images it,
    and answers it the way the scenario asked:
      - an alert gets a key event posted to *this application's own* event queue (``-[NSApplication postEvent:atStart:]``,
        documented as callable from any thread): Return or Escape, dispatched by AppKit to the alert exactly as a key press is,
        so the alert's own keyboard handling decides the result. Synthetic, not a HID device: no Accessibility grant is needed
        or used, and none is claimed. AppKit routes a key *equivalent* (Return for the default button) only to the key window
        of an active application, and an application is not made active while another one -- a system alert, say -- holds
        the front (measured at ``c0a1553``: a posted Return went unanswered while ``UserNotificationCenter`` was frontmost; a
        posted Escape, which the alert window handles itself, still worked). Handing the event to the alert window's own
        ``performKeyEquivalent:`` instead does not help (measured at ``f8af54b``: AppKit's buttons act on a key equivalent
        only in the key window, which an inactive application has none of; it worked only while the application was active).
        So when this application is not active a Return is answered by the button Return presses -- the alert window's own
        ``defaultButtonCell``, read from the window -- performing its click on the main thread: what AppKit does once a key
        window has received Return. That is a click, not a key event, and the record says so; the key-event path is the one
        taken whenever the application is active. Escape keeps the queue. The route, the button and whether the application
        was active are recorded with every answer.
      - an open or save panel is sent its own ``cancel:`` action on the main thread, in the modal run-loop mode
        (``performSelectorOnMainThread:withObject:waitUntilDone:modes:``), which is what its Cancel button does -- a panel shown
        as a sheet must end through it, or Tk waits on the sheet for ever (measured: ``abortModal`` ends the modal loop and
        leaves the sheet). ``abortModal`` is the fallback for a panel still up after 3 s. Its browser runs in another process,
        so a key event posted here does not reach it (measured); choosing files inside it, or pressing its buttons with a real
        pointer, needs Accessibility and is never claimed.

Nothing here can reach another application's windows, and nothing changes a privacy setting.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import threading
import time
from pathlib import Path

_objc = ctypes.CDLL(ctypes.util.find_library("objc"))
_cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
ctypes.CDLL(ctypes.util.find_library("AppKit"))
_objc.objc_getClass.restype = ctypes.c_void_p
_objc.objc_getClass.argtypes = [ctypes.c_char_p]
_objc.sel_registerName.restype = ctypes.c_void_p
_objc.sel_registerName.argtypes = [ctypes.c_char_p]
_objc.object_getClassName.restype = ctypes.c_char_p
_objc.object_getClassName.argtypes = [ctypes.c_void_p]


class CGRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


_cg.CGWindowListCreateImage.restype = ctypes.c_void_p
_cg.CGWindowListCreateImage.argtypes = [CGRect, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
_cg.CGImageRelease.argtypes = [ctypes.c_void_p]
_cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
_LIST_INCLUDING_WINDOW = 8          # kCGWindowListOptionIncludingWindow
_IMAGE_IGNORE_FRAMING = 1           # kCGWindowImageBoundsIgnoreFraming: the window, not its shadow
_IMAGE_BEST_RESOLUTION = 8          # kCGWindowImageBestResolution: Retina pixels
_PNG = 4                            # NSBitmapImageFileTypePNG
_KEY_DOWN, _KEY_UP = 10, 11         # NSEventTypeKeyDown / KeyUp
KEYS = {"return": ("\r", 36), "escape": ("\x1b", 53)}
_lock = threading.Lock()


def _send(target, selector: str, *args, restype=ctypes.c_void_p, argtypes=()):
    function = ctypes.cast(_objc.objc_msgSend, ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes))
    return function(target, _objc.sel_registerName(selector.encode()), *args)


def _class(name: str):
    return _objc.objc_getClass(name.encode())


def _text(ns) -> str:
    if not ns:
        return ""
    raw = _send(ns, "UTF8String", restype=ctypes.c_char_p)
    return raw.decode("utf-8", "replace") if raw else ""


def _ns(text: str):
    return _send(_class("NSString"), "stringWithUTF8String:", text.encode("utf-8"), argtypes=(ctypes.c_char_p,))


def _app():
    return _send(_class("NSApplication"), "sharedApplication")


def _rect(target, selector: str) -> CGRect:
    function = ctypes.cast(_objc.objc_msgSend, ctypes.CFUNCTYPE(CGRect, ctypes.c_void_p, ctypes.c_void_p))
    return function(target, _objc.sel_registerName(selector.encode()))


def screen_recording_granted() -> bool:
    """Read only, never prompts: whether this process's responsible application holds Screen Recording."""
    return bool(_cg.CGPreflightScreenCaptureAccess())


def windows() -> list[dict]:
    """This process's own windows, as AppKit has them."""
    found = []
    array = _send(_app(), "windows")
    for index in range(_send(array, "count", restype=ctypes.c_ulong)):
        window = _send(array, "objectAtIndex:", index, argtypes=(ctypes.c_ulong,))
        frame = _rect(window, "frame")
        appearance = _send(window, "effectiveAppearance")
        found.append({"ptr": window, "class": _objc.object_getClassName(window).decode().replace("NSKVONotifying_", ""),
                      "number": int(_send(window, "windowNumber", restype=ctypes.c_long)),
                      "visible": bool(_send(window, "isVisible", restype=ctypes.c_bool)),
                      "title": _text(_send(window, "title")),
                      "frame": [frame.x, frame.y, frame.width, frame.height],
                      "scale": float(_send(window, "backingScaleFactor", restype=ctypes.c_double)),
                      "appearance": _text(_send(appearance, "name")) if appearance else ""})
    return found


def plain(window: dict) -> dict:
    return {key: value for key, value in window.items() if key != "ptr"}


def window_for(title: str, size: tuple[int, int] | None = None) -> dict | None:
    """The visible window with this title; with several, the one whose content is nearest ``size`` (points)."""
    candidates = [item for item in windows() if item["visible"] and item["title"] == title]
    if not candidates:
        return None
    if size is None or len(candidates) == 1:
        return candidates[0]
    return min(candidates, key=lambda item: abs(item["frame"][2] - size[0]) + abs(item["frame"][3] - size[1]))


def capture(number: int, path: Path) -> dict:
    """One own window, imaged by the window server, written as PNG. ``captured`` is True only when a real image was written."""
    with _lock:
        image = _cg.CGWindowListCreateImage(CGRect(float("inf"), float("inf"), 0.0, 0.0), _LIST_INCLUDING_WINDOW, int(number),
                                            _IMAGE_IGNORE_FRAMING | _IMAGE_BEST_RESOLUTION)
        if not image:
            return {"captured": False, "why": f"the window server returned no image of window {number}"}
        try:
            rep = _send(_send(_class("NSBitmapImageRep"), "alloc"), "initWithCGImage:", image, argtypes=(ctypes.c_void_p,))
            data = _send(rep, "representationUsingType:properties:", _PNG, _send(_class("NSDictionary"), "dictionary"),
                         argtypes=(ctypes.c_ulong, ctypes.c_void_p))
            path.parent.mkdir(parents=True, exist_ok=True)
            written = bool(data) and bool(_send(data, "writeToFile:atomically:", _ns(str(path)), True,
                                                argtypes=(ctypes.c_void_p, ctypes.c_bool), restype=ctypes.c_bool))
            width = int(_send(rep, "pixelsWide", restype=ctypes.c_long))
            height = int(_send(rep, "pixelsHigh", restype=ctypes.c_long))
            _send(rep, "release", restype=None)
        finally:
            _cg.CGImageRelease(image)
    if not written:
        return {"captured": False, "why": f"the image of window {number} could not be written to {path.name}"}
    return {"captured": True, "width_px": width, "height_px": height, "mechanism": "CGWindowListCreateImage, own window"}


def key_event(name: str, window_number: int, kind: int = _KEY_DOWN):
    """One synthetic key event (an autoreleased ``NSEvent``) aimed at one of this application's windows. Not a HID device."""
    chars, code = KEYS[name]
    return _send(_class("NSEvent"),
                 "keyEventWithType:location:modifierFlags:timestamp:windowNumber:context:characters:charactersIgnoringModifiers:isARepeat:keyCode:",
                 kind, CGPoint(0.0, 0.0), 0, ctypes.c_double(time.monotonic()), int(window_number), None, _ns(chars), _ns(chars),
                 False, code, argtypes=(ctypes.c_ulong, CGPoint, ctypes.c_ulong, ctypes.c_double, ctypes.c_long, ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool, ctypes.c_ushort))


def post_key(name: str, window_number: int) -> None:
    """A key press for this application's own queue, aimed at one of its windows. Synthetic: not a HID device."""
    for kind in (_KEY_DOWN, _KEY_UP):
        _send(_app(), "postEvent:atStart:", key_event(name, window_number, kind), False, argtypes=(ctypes.c_void_p, ctypes.c_bool),
              restype=None)


def app_state() -> dict:
    """Whether AppKit counts this application active, and the number of its key window (None when it has none)."""
    app = _app()
    key = _send(app, "keyWindow")
    return {"active": bool(_send(app, "isActive", restype=ctypes.c_bool)),
            "key_window": int(_send(key, "windowNumber", restype=ctypes.c_long)) if key else None}


def alert_key_route(name: str, state: dict, window_number: int) -> str:
    """How a key reaches an alert: ``queue`` (a key event posted, routed by AppKit) or ``default-button`` (the button Return
    presses, the window's ``defaultButtonCell``, performs its click). Escape always takes the queue: it was measured to work
    whether or not the application was active. AppKit answers Return only in the key window of an active application, so
    Return takes the queue only then. Pure, so it is tested on every platform."""
    if name == "escape" or (state.get("active") and state.get("key_window") == window_number):
        return "queue"
    return "default-button"


def return_button(window) -> dict | None:
    """The button Return presses in this window: the control of its ``defaultButtonCell`` (None when it has none).

    Measured on Tk's real yes/no alert: "No" carries the Escape key equivalent, "Yes" carries none, and the window's
    ``defaultButtonCell`` is Yes's -- AppKit's key window answers Return through that cell."""
    cell = _send(window, "defaultButtonCell")
    button = _send(cell, "controlView") if cell else None
    if not button:
        return None
    return {"ptr": button, "title": _text(_send(button, "title")), "via": "defaultButtonCell"}


def abort_modal() -> None:
    _send(_app(), "abortModal", restype=None)


def perform_on_main(target, selector: str, argument=None) -> None:
    """``[target selector argument]`` on the main thread, also while a modal panel or sheet runs its loop. Does not wait (the
    call retains ``argument`` until it has run)."""
    modes = (ctypes.c_void_p * 2)(_ns("kCFRunLoopCommonModes"), _ns("NSModalPanelRunLoopMode"))
    array = _send(_class("NSArray"), "arrayWithObjects:count:", modes, 2, argtypes=(ctypes.c_void_p, ctypes.c_ulong))
    _send(target, "performSelectorOnMainThread:withObject:waitUntilDone:modes:", _objc.sel_registerName(selector.encode()), argument,
          False, array, argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool, ctypes.c_void_p), restype=None)


def visible(number: int) -> bool:
    return any(item["number"] == number and item["visible"] for item in windows())


def _types_of(panel) -> list[str]:
    array = _send(panel, "allowedContentTypes")
    if not array:
        return []
    return [_text(_send(_send(array, "objectAtIndex:", index, argtypes=(ctypes.c_ulong,)), "identifier"))
            for index in range(_send(array, "count", restype=ctypes.c_ulong))]


def panel_facts(window: dict) -> dict:
    """What the native panel was asked to be, read from the panel itself (getters only)."""
    panel = window["ptr"]
    facts = {"panel_class": window["class"], "title": window["title"]}
    if window["class"].endswith(("OpenPanel", "SavePanel")):
        directory = _send(panel, "directoryURL")
        facts.update(message=_text(_send(panel, "message")), directory=_text(_send(directory, "path")) if directory else "",
                     content_types=_types_of(panel))
        if window["class"].endswith("OpenPanel"):
            facts.update(multiple=bool(_send(panel, "allowsMultipleSelection", restype=ctypes.c_bool)),
                         choose_files=bool(_send(panel, "canChooseFiles", restype=ctypes.c_bool)),
                         choose_directories=bool(_send(panel, "canChooseDirectories", restype=ctypes.c_bool)))
    return facts


class NativeWatcher:
    """Answers this process's native panels in the order the scenario asked. Each answer is recorded in ``native-dialogs.jsonl``.

    ``expect`` takes ``{"kind": "open"|"save"|"alert", "respond": "cancel"|"return"|"escape", "capture": name or None}``. A panel
    that appears with nothing expected is recorded as unexpected and cancelled (open/save) or answered Escape (alert), so a
    scenario never hangs on a dialog it did not foresee, and the record makes it fail."""

    POLL = 0.1
    SETTLE = 0.6  # the panel's first drawing, before it is imaged and answered

    def __init__(self, record: Path, pictures: Path, main_title: str) -> None:
        self.record, self.pictures, self.main_title = record, pictures, main_title
        self.expected: list[dict] = []
        self.handled: set[int] = set()
        self.lock = threading.Lock()
        threading.Thread(target=self._run, name="native-dialog-watcher", daemon=True).start()

    def expect(self, items: list[dict]) -> None:
        with self.lock:
            self.expected.extend(items)

    def _append(self, entry: dict) -> None:
        with open(self.record, "a", encoding="utf-8") as sink:
            sink.write(json.dumps(entry, default=str) + "\n")

    def _run(self) -> None:
        while True:
            time.sleep(self.POLL)
            try:
                found = [item for item in windows() if item["visible"] and item["number"] not in self.handled
                         and item["class"].endswith(("OpenPanel", "SavePanel", "AlertPanel"))]
            except Exception:  # noqa: BLE001 - the window list is read again on the next turn
                continue
            for window in found:
                self.handled.add(window["number"])
                time.sleep(self.SETTLE)
                self._answer(window)

    def _answer(self, window: dict) -> None:
        kind = "alert" if window["class"].endswith("AlertPanel") else ("save" if window["class"].endswith("SavePanel") else "open")
        with self.lock:
            wanted = self.expected.pop(0) if self.expected else None
        entry = {"at": time.time(), "kind": kind, "window": plain(window), "facts": panel_facts(window),
                 "expected": wanted, "unexpected": wanted is None or wanted.get("kind") != kind}
        if wanted and wanted.get("capture"):
            path = self.pictures / f"{wanted['capture']}.png"
            shot = {"captured": False}
            for _attempt in range(10):  # a sheet slides in: the window server has no image of it for a moment
                shot = capture(window["number"], path)
                if shot["captured"]:
                    break
                time.sleep(0.2)
            entry["picture"] = {"name": path.name, **shot, "content_is_remote": kind in ("open", "save")}
        respond = (wanted or {}).get("respond") or ("escape" if kind == "alert" else "cancel")
        if kind == "alert" and respond in KEYS:
            state = app_state()
            route = alert_key_route(respond, state, window["number"])
            button = return_button(window["ptr"]) if route == "default-button" else None
            if route == "default-button" and button is None:
                route = "queue"  # nothing bound to Return: post the key anyway, and let the alert staying up say so
            if route == "queue":
                post_key(respond, window["number"])
                by = f"{respond} key event posted to this application's own queue"
            else:
                perform_on_main(button["ptr"], "performClick:")
                by = (f"the alert's default button ({button['title']!r}, the one Return presses: the window's defaultButtonCell) "
                      "performed its click: this application was not active, and AppKit answers Return only in an active "
                      "application's key window")
            entry["answered"] = {"by": by, "synthetic": True, "route": route, "app_active": state["active"],
                                 "alert_was_key": state["key_window"] == window["number"],
                                 "button": {key: value for key, value in (button or {}).items() if key != "ptr"} or None}
        else:
            perform_on_main(window["ptr"], "cancel:")
            entry["answered"] = {"by": "the panel's own cancel: action, on the main thread (as its Cancel button)", "synthetic": True}
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and visible(window["number"]):
                time.sleep(0.1)
            if visible(window["number"]):
                abort_modal()
                entry["answered"]["fallback"] = "abortModal: the panel was still up 3 s after cancel:"
        self._append(entry)
