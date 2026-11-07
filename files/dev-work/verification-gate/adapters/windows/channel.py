"""A test-only observation channel inside a Tk application: what the driver may know, and nothing it may do.

Plan section 8.1 allows this when Tk controls are not exposed to Windows: readiness, widget identity, bounds and state, answered on the
Tk main thread. It has no operation that calls application code: a key path follows attributes and indexes only (a property may
run, a method may not), and clicking is left entirely to real input from outside. It is local to loopback, answers only the run's
random token, is started only by ``app_launcher.py`` under ``files/``, and is outside every distribution.

The socket threads never touch Tk. Each request is queued and answered by an ``after`` pump on the main thread.
"""

from __future__ import annotations

import json
import os
import queue
import re
import secrets
import socket
import threading
import tkinter as tk

_STEP = re.compile(r"\.?([A-Za-z_][A-Za-z0-9_]*)|\[([^\]]+)\]")
PUMP_MS = 15


class KeyPathError(LookupError):
    """A key path that does not lead to an object."""


def follow(start, path: str):
    """Walk ``a.b[key].c`` from ``start``. Attributes and indexes only; there is no way to call anything through this."""
    current = start
    position = 0
    while position < len(path):
        match = _STEP.match(path, position)
        if not match:
            raise KeyPathError(f"bad key path {path!r} at {position}")
        position = match.end()
        name, index = match.group(1), match.group(2)
        if name is not None:
            if name.startswith("__"):
                raise KeyPathError(f"{name!r} is not observable")
            try:
                current = getattr(current, name)
            except AttributeError:
                raise KeyPathError(f"{path!r}: no attribute {name!r} on {type(current).__name__}") from None
        else:
            current = _index(current, index, path)
    return current


def _index(container, key: str, path: str):
    if isinstance(container, dict):
        for candidate, value in container.items():
            if key in (candidate, str(candidate), getattr(candidate, "name", None), getattr(candidate, "value", None)):
                return value
        raise KeyPathError(f"{path!r}: no key {key!r}; there are {[str(c) for c in container]}")
    try:
        return container[int(key)]
    except (ValueError, IndexError, TypeError):
        raise KeyPathError(f"{path!r}: no index {key!r}") from None


def _plain(value):
    """Something JSON can carry, without asking the object to do anything beyond naming itself."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return type(value).__name__


def describe_widget(widget: tk.Misc) -> dict:
    """A widget's identity, geometry and visible state, read on the main thread."""
    entry: dict = {"path": str(widget), "class": widget.winfo_class(), "exists": bool(widget.winfo_exists())}
    if not entry["exists"]:
        return entry
    entry.update(x=widget.winfo_rootx(), y=widget.winfo_rooty(), width=widget.winfo_width(), height=widget.winfo_height(),
                 viewable=bool(widget.winfo_viewable()), toplevel=str(widget.winfo_toplevel()))
    for option in ("text", "state"):
        try:
            value = widget.cget(option)
        except tk.TclError:
            continue
        entry[option] = str(value)
    state = None
    try:
        state = widget.state()  # ttk's own state flags, a read when given no argument
    except (tk.TclError, AttributeError, TypeError):
        pass
    if isinstance(state, (tuple, list)):
        entry["ttk_state"] = [str(flag) for flag in state]
    entry["disabled"] = "disabled" in entry.get("ttk_state", []) or entry.get("state") == "disabled"
    cls = entry["class"]
    if cls in ("TEntry", "Entry", "TCombobox", "TSpinbox", "Spinbox"):
        entry["value"] = widget.get()
    if cls == "TCombobox":
        entry["values"] = [str(item) for item in widget.tk.splitlist(widget.cget("values"))]
    if cls in ("TCheckbutton", "TRadiobutton"):
        entry["selected"] = "selected" in entry.get("ttk_state", [])
    if cls == "Listbox":
        entry["items"] = list(widget.get(0, "end"))
        entry["selection"] = [int(index) for index in widget.curselection()]
    if cls == "Text":
        entry["content"] = widget.get("1.0", "end-1c")
    if cls == "Treeview":
        entry["items"] = [str(item) for item in widget.get_children()]
    return entry


class Channel:
    def __init__(self, root: tk.Misc, *, channel_file: str, resolve=None) -> None:
        self.root = root
        self.resolve = resolve or (lambda scope: root)
        self.token = secrets.token_hex(16)
        self.requests: "queue.Queue[tuple[dict, queue.Queue]]" = queue.Queue()
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.input_marks = 0
        root.bind_all("<KeyPress-F24>", self._on_input_mark, add="+")
        root.bind("<Destroy>", self._on_destroy, add="+")
        threading.Thread(target=self._serve, name="observation-channel", daemon=True).start()
        self._pump_id = root.after(PUMP_MS, self._pump)
        temporary = channel_file + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"port": self.server.getsockname()[1], "token": self.token, "pid": os.getpid()}, handle)
        os.replace(temporary, channel_file)

    def _on_input_mark(self, _event) -> None:
        self.input_marks += 1

    def _on_destroy(self, event) -> None:
        """Let go of the window as it closes. These threads live until the process ends, so a reference held here would keep the closed root
        reachable for ever, and the very collection a shutdown journey is looking for could never touch it. That is how a test comes to
        pass without testing anything: the first version of this channel did exactly that."""
        if event.widget is not self.root:
            return
        self.root = None
        self.resolve = None
        try:
            self.server.close()
        except OSError:
            pass

    # -- socket threads, which never touch Tk ------------------------------------------------- #
    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(connection,), name="observation-client", daemon=True).start()

    def _client(self, connection: socket.socket) -> None:
        with connection, connection.makefile("rwb") as stream:
            for raw in stream:
                try:
                    request = json.loads(raw)
                except ValueError:
                    return
                if not secrets.compare_digest(str(request.get("token")), self.token):
                    stream.write(b'{"error":"bad token"}\n')
                    stream.flush()
                    continue
                answer: "queue.Queue[dict]" = queue.Queue()
                if self.root is None:
                    return
                self.requests.put((request, answer))
                try:
                    response = answer.get(timeout=30)
                except queue.Empty:
                    response = {"error": "busy", "detail": "the main thread did not answer within 30 s"}
                try:
                    stream.write(json.dumps(response).encode("utf-8") + b"\n")
                    stream.flush()
                except OSError:
                    return

    # -- the Tk main thread ------------------------------------------------------------------- #
    def _pump(self) -> None:
        try:
            while True:
                request, answer = self.requests.get_nowait()
                try:
                    answer.put(self._handle(request))
                except Exception as exc:  # noqa: BLE001 - reported to the driver
                    answer.put({"error": f"{type(exc).__name__}: {exc}"})
        except queue.Empty:
            pass
        self._pump_id = self.root.after(PUMP_MS, self._pump)

    def _handle(self, request: dict) -> dict:
        op = request.get("op")
        if op == "ping":
            return {"ok": True, "pid": os.getpid(), "marks": self.input_marks}
        if op == "window":
            root = self.root
            focused = root.focus_get()
            return {"ok": True, "x": root.winfo_rootx(), "y": root.winfo_rooty(), "width": root.winfo_width(),
                    "height": root.winfo_height(), "title": root.title(), "focus": None if focused is None else str(focused),
                    "scaling": float(root.tk.call("tk", "scaling"))}
        if op == "widget":
            return {"ok": True, **describe_widget(self._target(request))}
        if op == "containing":
            found = self.root.winfo_containing(int(request["x"]), int(request["y"]))
            return {"ok": True, "path": None if found is None else str(found)}
        if op == "read":
            return {"ok": True, "value": _plain(follow(self.resolve(request.get("scope")), request["key"]))}
        if op == "layout":
            # What a settled window is: nothing queued to lay out, and the same widgets in the same places as the last time asked.
            self.root.update_idletasks()
            shape = [(str(w), w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height(), bool(w.winfo_viewable()))
                     for w in self._all(self.root)]
            return {"ok": True, "shape": hash(tuple(shape))}
        if op == "tree":
            return {"ok": True, "widgets": self._tree(self.root)}
        if op == "toplevels":
            return {"ok": True, "toplevels": [describe_widget(w) for w in self._all(self.root) if w.winfo_class() in ("Toplevel", "Tk")
                                              and w.winfo_viewable()]}
        return {"error": f"unknown op {op!r}"}

    def _target(self, request: dict) -> tk.Misc:
        if "path" in request:
            return self.root.nametowidget(request["path"])
        target = follow(self.resolve(request.get("scope")), request["key"])
        if not isinstance(target, tk.Misc):
            raise KeyPathError(f"{request['key']!r} is a {type(target).__name__}, not a widget")
        return target

    def _all(self, widget: tk.Misc) -> list[tk.Misc]:
        found = [widget]
        for child in widget.winfo_children():
            found.extend(self._all(child))
        return found

    def _tree(self, widget: tk.Misc) -> list[dict]:
        return [describe_widget(item) for item in self._all(widget)]
