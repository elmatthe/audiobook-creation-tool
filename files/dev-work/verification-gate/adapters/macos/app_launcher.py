"""The REAL launcher and panels on macOS, with the in-process journey driver beside them (v0.8.x P1B, plan 14.3, MAC-045).

Runs the Windows adapter's portable launcher (``adapters/windows/app_launcher.py``: ``launcher.main()`` itself, the same
isolation of settings, logs and runtime data, the same recorded Finder reveal, replayed Edge speech, forced landing and
negative controls), and adds what macOS needs because there is no native-input adapter and no Accessibility or Screen
Recording grant (D9). Each is named in the journey's evidence:

  * **Input through Tk.** The observation channel gains ops that act: a button is ``invoke``d, any other target gets
    ``<Enter>``/``<ButtonPress-1>``/``<ButtonRelease-1>`` at its centre, text is typed one ``<KeyPress>`` at a time into
    the focused widget, the wheel is a ``<MouseWheel>`` at the widget, a combobox gets its value and
    ``<<ComboboxSelected>>``. A target that is absent, not on screen or disabled is refused, as a hand would be.
    Every act is scheduled on Tk's thread and answered at once, as a real click is.
  * **Dialog stand-ins.** ``tkinter.filedialog`` and ``tkinter.messagebox`` are replaced by stand-ins that wait, in a
    nested Tk loop exactly as a modal dialog does, for the session to answer them, and return what the native dialog
    would. The native NSOpenPanel and NSAlert themselves are owner-manual (darwin_map class b).
  * **The Tk thread audit (MAC-032).** The window's Tcl interpreter is wrapped before any widget exists, so every Tk call
    from a thread other than the main thread is recorded (``tk-thread-audit.jsonl``) with the thread and the call. A
    journey whose run makes one fails.
  * **The spawn record.** Every child the application process starts is recorded the moment it starts -- pid, kernel
    start time, process group, program -- in ``children.jsonl``, so the session can find an orphan by identity after
    the window has gone. Nothing is ever ended by this record's names.

Usage: python app_launcher.py <config.json>
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
WINDOWS = HERE.parent / "windows"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The portable launcher reads sys.argv[1] at import and puts the application's scripts/ on sys.path.
base = _load("act_portable_app_launcher", WINDOWS / "app_launcher.py")
windows_channel = _load("act_windows_channel", WINDOWS / "channel.py")
CONFIG = base._load_config()
WORK = Path(CONFIG["runtime_dir"]).parent

import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox  # noqa: E402


def _append(name: str, record: dict) -> None:
    with open(WORK / name, "a", encoding="utf-8") as sink:
        sink.write(json.dumps(record, default=str) + "\n")


# --------------------------------------------------------------------------------------------------------------- #
#  The spawn record
# --------------------------------------------------------------------------------------------------------------- #
def _start_time(pid: int):
    from shared import child_ownership

    return child_ownership.process_start_time(pid)


def _record_spawns() -> None:
    original = subprocess.Popen.__init__

    def recording(self, args, *rest, **kwargs):
        original(self, args, *rest, **kwargs)
        try:
            argv0 = args if isinstance(args, (str, bytes, os.PathLike)) else list(args)[0]
            group = os.getpgid(self.pid)
        except (OSError, IndexError, TypeError):
            argv0, group = args, None
        _append("children.jsonl", {"pid": self.pid, "start": _start_time(self.pid), "pgid": group,
                                   "program": os.path.basename(os.fsdecode(argv0)) if argv0 is not None else "",
                                   "thread": threading.current_thread().name, "at": time.time()})

    subprocess.Popen.__init__ = recording


# --------------------------------------------------------------------------------------------------------------- #
#  The Tk thread audit
# --------------------------------------------------------------------------------------------------------------- #
#: Conversions of values already in hand; they read nothing of the interpreter's state.
_PURE = frozenset({"getint", "getdouble", "getboolean", "splitlist", "split", "wantobjects"})
AUDIT: list[dict] = []


class ThreadCheckingTk:
    """Every call into the window's Tcl interpreter, checked for the thread it comes from."""

    def __init__(self, real) -> None:
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_main", threading.main_thread())

    def __getattr__(self, name):
        value = getattr(self._real, name)
        if name in _PURE or not callable(value):
            return value

        def checked(*args, **kwargs):
            if threading.current_thread() is not self._main:
                frames = [f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in traceback.extract_stack()[:-1]
                          if "/scripts/" in f.filename.replace(os.sep, "/")][-4:]
                record = {"thread": threading.current_thread().name, "call": name,
                          "what": str(args[0])[:80] if args else "", "where": frames, "at": time.time()}
                AUDIT.append(record)
                _append("tk-thread-audit.jsonl", record)
            return value(*args, **kwargs)

        return checked

    def __setattr__(self, name, value):
        setattr(self._real, name, value)


# --------------------------------------------------------------------------------------------------------------- #
#  Dialog stand-ins
# --------------------------------------------------------------------------------------------------------------- #
PENDING: dict[int, dict] = {}
ANSWERS: dict[int, object] = {}
_dialog_numbers = iter(range(1, 1 << 30))
_MESSAGE_BUTTONS = {"showinfo": ["OK"], "showwarning": ["OK"], "showerror": ["OK"], "askyesno": ["Yes", "No"],
                    "askokcancel": ["OK", "Cancel"], "askyesnocancel": ["Yes", "No", "Cancel"],
                    "askquestion": ["Yes", "No"], "askretrycancel": ["Retry", "Cancel"]}


def _wait_for_answer(kind: str, options: dict) -> object:
    root = tk._default_root
    if threading.current_thread() is not threading.main_thread():
        AUDIT.append({"thread": threading.current_thread().name, "call": f"dialog {kind}", "what": options.get("title", "")})
        _append("tk-thread-audit.jsonl", AUDIT[-1])
    number = next(_dialog_numbers)
    flag = tk.IntVar(master=root, value=0)
    entry = {"id": number, "kind": kind, "title": str(options.get("title") or ""), "message": str(options.get("message") or ""),
             "detail": str(options.get("detail") or ""), "buttons": _MESSAGE_BUTTONS.get(kind, []),
             "options": {k: str(v) for k, v in options.items() if k not in ("parent", "master")}, "flag": flag}
    PENDING[number] = entry
    _append("dialogs.jsonl", {k: v for k, v in entry.items() if k != "flag"})
    try:
        root.wait_variable(flag)  # a nested loop, as a modal dialog's: the window keeps drawing and the channel keeps answering
    finally:
        PENDING.pop(number, None)
    return ANSWERS.pop(number, None)


def _file_stand_in(kind: str):
    def ask(**options):
        answer = _wait_for_answer(kind, options)
        if kind == "askopenfilenames":
            return tuple(str(item) for item in (answer or ()))
        if isinstance(answer, (list, tuple)):
            answer = answer[0] if answer else ""
        return str(answer or "")

    return ask


def _message_stand_in(kind: str):
    def ask(title=None, message=None, **options):
        button = str(_wait_for_answer(kind, {"title": title, "message": message, **options}) or "").lower()
        if kind in ("showinfo", "showwarning", "showerror"):
            return "ok"
        if kind == "askyesno":
            return button == "yes"
        if kind == "askokcancel":
            return button == "ok"
        if kind == "askretrycancel":
            return button == "retry"
        if kind == "askyesnocancel":
            return None if button in ("cancel", "") else button == "yes"
        return button  # askquestion

    return ask


def _install_dialog_stand_ins() -> None:
    for kind in ("askopenfilename", "askopenfilenames", "asksaveasfilename", "askdirectory"):
        setattr(filedialog, kind, _file_stand_in(kind))
    for kind in _MESSAGE_BUTTONS:
        setattr(messagebox, kind, _message_stand_in(kind))


# --------------------------------------------------------------------------------------------------------------- #
#  The channel's acting ops
# --------------------------------------------------------------------------------------------------------------- #
_KEYSYMS = {" ": "space", "-": "minus", ".": "period", ",": "comma", "/": "slash", "'": "apostrophe", "&": "ampersand",
            ":": "colon", "_": "underscore", "(": "parenleft", ")": "parenright", "!": "exclam", "?": "question",
            '"': "quotedbl", "#": "numbersign", "+": "plus", "=": "equal", "@": "at", ";": "semicolon"}
_KEYS = {"return": "Return", "enter": "Return", "tab": "Tab", "escape": "Escape", "down": "Down", "up": "Up", "left": "Left",
         "right": "Right", "home": "Home", "end": "End", "delete": "Delete", "backspace": "BackSpace", "space": "space",
         "f24": "F24", "next": "Next", "prior": "Prior", "pagedown": "Next", "pageup": "Prior"}
_INVOKABLE = frozenset({"TButton", "Button", "TCheckbutton", "Checkbutton", "TRadiobutton", "Radiobutton"})


class MacChannel(windows_channel.Channel):
    """The observation channel plus acts through Tk (no native input exists in this programme on macOS)."""

    def _handle(self, request: dict) -> dict:
        op = request.get("op")
        if op == "window":
            return self._window()
        handler = getattr(self, f"_op_{op}", None) if op else None
        if handler is not None:
            return handler(request)
        return super()._handle(request)

    # -- refusals, as a hand would meet them -------------------------------------------------- #
    def _actionable(self, widget, *, enabled: bool = True) -> str | None:
        if not widget.winfo_exists():
            return "it does not exist"
        if not widget.winfo_viewable():
            return "it is not on screen"
        state = windows_channel.describe_widget(widget)
        if enabled and state.get("disabled"):
            return "it is disabled"
        return None

    def _act(self, request: dict, action, *, enabled: bool = True) -> dict:
        widget = self._target(request)
        refused = self._actionable(widget, enabled=enabled)
        described = windows_channel.describe_widget(widget)
        if refused:
            return {"ok": False, "refused": refused, **described}

        def run():
            try:
                action(widget)
            except Exception as exc:  # noqa: BLE001 - recorded for the journey's evidence
                _append("channel-errors.jsonl", {"op": request.get("op"), "error": f"{type(exc).__name__}: {exc}",
                                                 "traceback": traceback.format_exc()[-2000:]})

        self.root.after(0, run)  # answered at once; done on Tk's own next turn, as a real click is
        return {"ok": True, **described}

    def _op_invoke(self, request: dict) -> dict:
        offset = request.get("offset")

        def click(widget):
            if widget.winfo_class() in _INVOKABLE and offset is None:
                widget.focus_force()
                widget.invoke()
                return
            x, y = (offset if offset else (widget.winfo_width() // 2, widget.winfo_height() // 2))
            widget.event_generate("<Enter>", x=x, y=y)
            widget.event_generate("<ButtonPress-1>", x=x, y=y)
            widget.event_generate("<ButtonRelease-1>", x=x, y=y)

        return self._act(request, click)

    def _op_type(self, request: dict) -> dict:
        text, replace = str(request.get("text", "")), bool(request.get("replace", True))

        def type_text(widget):
            # focus_force: a generated key goes to the focus, and focus_set does not take it while another
            # application is active (as a click into the field would).
            widget.focus_force()
            if replace:
                widget.event_generate("<<SelectAll>>")
                if widget.winfo_class() in ("TEntry", "Entry", "TCombobox", "TSpinbox", "Spinbox"):
                    widget.delete(0, "end")
                elif widget.winfo_class() == "Text":
                    widget.delete("1.0", "end")
                widget.event_generate("<KeyPress>", keysym="BackSpace")
                widget.event_generate("<KeyRelease>", keysym="BackSpace")
            for character in text:
                keysym = _KEYSYMS.get(character, character)
                if len(keysym) == 1 and not character.isalnum():
                    widget.insert("insert", character)  # no keysym for it: inserted, then released as a key would be
                    widget.event_generate("<KeyRelease>")
                    continue
                widget.event_generate("<KeyPress>", keysym=keysym)
                widget.event_generate("<KeyRelease>", keysym=keysym)

        return self._act(request, type_text)

    def _op_type_focus(self, request: dict) -> dict:
        target = self.root.focus_get()
        if target is None:
            return {"ok": False, "refused": "no widget has the focus"}
        text = str(request.get("text", ""))

        def type_text():
            for character in text:
                keysym = _KEYSYMS.get(character, character)
                if len(keysym) == 1 and not character.isalnum():
                    target.insert("insert", character)
                    target.event_generate("<KeyRelease>")
                    continue
                target.event_generate("<KeyPress>", keysym=keysym)
                target.event_generate("<KeyRelease>", keysym=keysym)

        self.root.after(0, type_text)
        return {"ok": True, "path": str(target)}

    def _op_key(self, request: dict) -> dict:
        keysym = _KEYS.get(str(request["name"]).lower(), str(request["name"]))
        modifier = request.get("modifier")
        sequence = f"<{modifier.capitalize()}-KeyPress-{keysym}>" if modifier else None

        def press():
            target = self.root.focus_get() or self.root
            if sequence:
                target.event_generate(sequence)
            else:
                target.event_generate("<KeyPress>", keysym=keysym)
                target.event_generate("<KeyRelease>", keysym=keysym)

        self.root.after(0, press)
        return {"ok": True, "keysym": keysym}

    def _op_wheel(self, request: dict) -> dict:
        notches = int(request["notches"])

        def turn(widget):
            x, y = widget.winfo_width() // 2, widget.winfo_height() // 2
            widget.event_generate("<Enter>", x=x, y=y)
            for _ in range(abs(notches)):
                widget.event_generate("<MouseWheel>", delta=120 if notches > 0 else -120, x=x, y=y)

        return self._act(request, turn, enabled=False)  # a wheel over a read-only log scrolls it, as on Windows

    def _op_select(self, request: dict) -> dict:
        value = str(request["value"])

        def choose(widget):
            widget.focus_force()
            widget.set(value)
            widget.event_generate("<<ComboboxSelected>>")

        return self._act(request, choose)

    def _op_close(self, request: dict) -> dict:
        how = request.get("how", "close")

        def close():
            if how == "quit":
                self.root.tk.eval("::tk::mac::Quit")  # the application menu's Quit and Cmd+Q
            else:
                self.root.tk.call(self.root.protocol("WM_DELETE_WINDOW"))  # the red button

        self.root.after(0, close)
        return {"ok": True, "how": how}

    def _op_close_focused(self, request: dict) -> dict:
        focused = self.root.focus_get()
        top = (focused or self.root).winfo_toplevel()

        def close():
            command = top.protocol("WM_DELETE_WINDOW")
            if command:
                top.tk.call(command)  # the window's own close button
            else:
                top.destroy()  # what the window manager does for a window with no close handler

        self.root.after(0, close)
        return {"ok": True, "toplevel": str(top)}

    def _op_geometry(self, request: dict) -> dict:
        place = f"+{int(request['x'])}+{int(request['y'])}" if "x" in request and "y" in request else ""
        self.root.geometry(f"{int(request['width'])}x{int(request['height'])}{place}")
        self.root.update_idletasks()
        return {"ok": True}

    def _window(self) -> dict:
        answer = windows_channel.Channel._handle(self, {"op": "window"})
        focused = self.root.focus_get()
        answer["focus_toplevel"] = None if focused is None else str(focused.winfo_toplevel())
        answer["frame_top"] = self.root.winfo_rooty() - self.root.winfo_y()  # the title bar above the content
        return answer

    def _op_raise(self, request: dict) -> dict:
        self.root.lift()
        return {"ok": True}

    def _op_screen(self, request: dict) -> dict:
        width, height = self.root.wm_maxsize()
        return {"ok": True, "x": self.root.winfo_vrootx(), "y": self.root.winfo_vrooty(), "width": int(width),
                "height": int(height), "screen_width": self.root.winfo_screenwidth(),
                "screen_height": self.root.winfo_screenheight(),
                "windowing_system": str(self.root.tk.call("tk", "windowingsystem"))}

    def _op_dialogs(self, request: dict) -> dict:
        return {"ok": True, "dialogs": [{k: v for k, v in entry.items() if k != "flag"} for entry in PENDING.values()]}

    def _op_answer(self, request: dict) -> dict:
        number = int(request["id"])
        entry = PENDING.get(number)
        if entry is None:
            return {"ok": False, "refused": f"no dialog {number} is open"}
        ANSWERS[number] = request.get("answer")
        _append("dialogs.jsonl", {"answered": number, "answer": request.get("answer")})
        entry["flag"].set(1)
        return {"ok": True}

    def _op_audit(self, request: dict) -> dict:
        return {"ok": True, "off_main_thread": AUDIT[-50:], "count": len(AUDIT)}

    def _op_containment(self, request: dict) -> dict:
        from shared import subprocess_utils

        owner = subprocess_utils.containment_owner()
        if owner is None:
            return {"ok": True, "owner": False}
        return {"ok": True, "owner": True, "guardian": owner.guardian_pid(),
                "children": [{"pid": c.pid, "pgid": c.pgid, "kind": c.kind, "label": c.label, "start": c.start_time}
                             for c in owner.children()]}


def main() -> int:
    _record_spawns()
    _install_dialog_stand_ins()
    channel_module = types.ModuleType("channel")
    channel_module.Channel = MacChannel
    sys.modules["channel"] = channel_module  # the portable launcher's ``from channel import Channel``

    import launcher

    real_tk = tk.Tk

    class AuditedTk(real_tk):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.tk = ThreadCheckingTk(self.tk)  # before any widget exists, so every widget shares it

    launcher.tk.Tk = AuditedTk
    if CONFIG.get("control_no_containment"):
        launcher.sp.enable_containment = lambda log=None: None  # a negative control: no owner, no guardian, no lifeline
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
