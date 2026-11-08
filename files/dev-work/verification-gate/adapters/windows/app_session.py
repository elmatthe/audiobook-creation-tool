"""One isolated ACT instance, driven from outside: a kill-on-close job over the process tree, the observation channel, and guarded input.

Every input is decided from fresh bounds and goes through ``_guard``. If the foreground has gone elsewhere nothing is sent and the journey
is BLOCKED; a target that is covered, disabled or off its window is refused without sending anything. Every action lands in
``actions.jsonl`` with what it aimed at, so a result can be traced back to the input that caused it.

The application runs at Low integrity from its first instruction (``containment.py``), so Windows refuses it, and its children, any write
to the owner's own dialog history; its scratch is labelled so it can write there. The session refuses to go on unless every process in its
job is Low, and checks the dialog's owner again before typing into any file or folder dialog.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE_DIR = HERE.parents[1]
if str(GATE_DIR) not in sys.path:
    sys.path.insert(0, str(GATE_DIR))

from helpers import winproc  # noqa: E402

from . import containment  # noqa: E402
from . import native_input as native  # noqa: E402

STARTUP_SECONDS = 90
ORPHAN_GRACE_SECONDS = 1.5
POLL_SECONDS = 0.05


class JourneyTimeout(TimeoutError):
    """A readiness predicate never came true within its bound."""


class ChannelError(RuntimeError):
    """The observation channel refused or answered with an error."""


def wait_until(predicate, timeout: float, what: str, poll: float = POLL_SECONDS):
    """A bounded poll for a named condition. Fixed sleeps are never how a journey decides something happened."""
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise JourneyTimeout(f"timed out after {timeout:.0f} s waiting for {what}")
        time.sleep(poll)


class _Client:
    def __init__(self, info: dict) -> None:
        self.socket = socket.create_connection(("127.0.0.1", info["port"]), timeout=35)
        self.stream = self.socket.makefile("rwb")
        self.token = info["token"]

    def call(self, op: str, **arguments) -> dict:
        self.stream.write(json.dumps({"op": op, "token": self.token, **arguments}).encode("utf-8") + b"\n")
        self.stream.flush()
        line = self.stream.readline()
        if not line:
            raise ChannelError(f"the channel closed during {op}")
        answer = json.loads(line)
        if "error" in answer:
            raise ChannelError(f"{op} {arguments}: {answer['error']}")
        return answer

    def close(self) -> None:
        for item in (self.stream, self.socket):
            try:
                item.close()
            except OSError:
                pass


class AppSession:
    """Start with ``start()``; leave with ``close_by_user()`` or ``tear_down()``. ``evidence`` and ``work`` belong to one scenario."""

    def __init__(self, evidence: Path, work: Path, *, script: Path | None = None, config: dict | None = None, name: str = "app") -> None:
        self.evidence = evidence
        self.work = work
        self.name = name
        self.script = script or HERE / "app_launcher.py"
        self.config = dict(config or {})
        self.actions = evidence / f"{name}-actions.jsonl"
        self.screenshots = evidence / "screenshots"
        self.shots: list[dict] = []
        self.proc: subprocess.Popen | None = None
        self.job: winproc._Job | None = None
        self.client: _Client | None = None
        self.pid: int | None = None
        self.hwnd: int | None = None
        self.exit_code: int | None = None
        self.input_count = 0
        self.began = time.monotonic()
        self.stderr_path = evidence / f"{name}-stderr.log"
        self.containment: dict | None = None

    # -- lifetime ------------------------------------------------------------------------------- #
    def start(self, startup: float = STARTUP_SECONDS) -> "AppSession":
        status = native.desktop_status()
        self._log("desktop", **status.facts, ok=status.ok, reason=status.reason)
        if not status.ok:
            raise native.DesktopUnavailable(status.reason)
        self.work.mkdir(parents=True, exist_ok=True)
        label = containment.label_low(self.work)  # before anything the application must write is created below it
        temp = self.work / "t"
        temp.mkdir(exist_ok=True)
        channel_file = self.work / f"{self.name}-channel.json"
        config = {"channel_file": str(channel_file), "runtime_dir": str(self.work / "runtime"), **self.config}
        config_path = self.work / f"{self.name}-config.json"
        config_path.write_text(json.dumps(config, indent=1), encoding="utf-8")
        env = {key: value for key, value in os.environ.items()}
        env.update(TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp), PYTHONDONTWRITEBYTECODE="1",
                   APPDATA=str(self._folder("appdata")), LOCALAPPDATA=str(self._folder("localappdata")))
        for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "ACT_STARTUP_NOTICE"):
            env.pop(key, None)
        self.job = winproc._Job()
        open(self.stderr_path, "xb").close()
        try:
            self.proc = containment.spawn_low([sys.executable, "-I", "-B", str(self.script), str(config_path)], cwd=self.work, env=env,
                                              output=self.stderr_path)
        except OSError as exc:
            raise containment.ContainmentUnavailable(f"the application could not be started at Low integrity: {exc}") from exc
        self.job.adopt_and_resume(self.proc)
        self._log("launched", launcher_pid=self.proc.pid, ownership="job")
        info = wait_until(lambda: self._read_channel_file(channel_file), startup, "the application's observation channel")
        self.pid = int(info["pid"])
        if self.pid not in self.job.pids():
            raise RuntimeError(f"interpreter {self.pid} is not in this session's job {self.job.pids()}")
        self.containment = {"scratch_label": label, **containment.require_low(self.job.pids(), "the application under test")}
        self._log("containment", **self.containment)
        self.client = _Client(info)
        self.hwnd = wait_until(self._main_window, startup, "the application's main window")
        self._log("window", pid=self.pid, hwnd=self.hwnd, job_pids=self.job.pids())
        if not native.acquire_foreground(self.hwnd):
            raise native.ForegroundLost(f"the owned window could not take the foreground; {native.foreground_owner()} has it")
        self.check_input_round_trip()
        self.check_geometry_mapping()
        return self

    def _folder(self, name: str) -> Path:
        path = self.work / name
        path.mkdir(exist_ok=True)
        return path

    def _read_channel_file(self, path: Path):
        if self.proc is not None and self.proc.poll() is not None:
            raise RuntimeError(f"the application ended during startup with exit {self.proc.returncode}: {self.stderr_tail()}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _main_window(self):
        for window in native.windows_of(self.pid):
            if window["class"] == "TkTopLevel" and not window["owner"]:
                return window["hwnd"]
        return None

    def check_input_round_trip(self) -> None:
        """A key nothing uses, F24, sent as real input and seen arriving in the owned window. This is the proof a handle cannot give."""
        before = self.client.call("ping")["marks"]
        self._guard("input round trip")
        native.key_tap("f24")
        try:
            wait_until(lambda: self.client.call("ping")["marks"] > before, 5, "a real key press to reach the owned window")
        except JourneyTimeout:
            raise native.DesktopUnavailable("a real key press sent to the owned window never arrived") from None
        self._log("input round trip", ok=True, marks=self.client.call("ping")["marks"])

    def check_geometry_mapping(self) -> None:
        """Tk's coordinates and the driver's must be the same pixels, or clicks would be aimed somewhere else entirely."""
        window = self.client.call("window")
        left, top, right, bottom = native.window_rect(self.hwnd)
        inside = left <= window["x"] <= right and top <= window["y"] <= bottom
        client_w, client_h = native.client_size(self.hwnd)
        same = abs(client_w - window["width"]) <= 1 and abs(client_h - window["height"]) <= 1
        dpi = native.user32.GetDpiForWindow(self.hwnd)
        self._log("geometry", tk=window, frame=[left, top, right, bottom], client=[client_w, client_h], dpi=dpi)
        if not (inside and same):
            raise native.DesktopUnavailable(f"Tk geometry {window} and the window manager {[left, top, right, bottom]}, "
                                            f"{[client_w, client_h]} disagree at DPI {dpi}, so a click cannot be aimed")

    def tear_down(self) -> dict:
        """End whatever is left of this session's tree, and only that. Always safe to call."""
        facts = {"forced": False}
        if self.client is not None:
            self.client.close()
            self.client = None
        if self.proc is not None and self.proc.poll() is None:
            facts["forced"] = True
            self.job.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                facts["wait_timeout"] = True
        if self.job is not None:
            left = self.job.pids()
            if left:
                facts["ended_at_tear_down"] = left
                self.job.terminate()
                deadline = time.monotonic() + 10
                while self.job.pids() and time.monotonic() < deadline:
                    time.sleep(0.05)
            facts["survivors"] = self.job.pids()
            self.job.close()
            self.job = None
        self._log("tear down", **facts)
        return facts

    def close_by_user(self, *, timeout: float = 45) -> dict:
        """Alt+F4 as a person's keyboard sends it, then observed entirely from outside: the exit status, every window, every owned process.

        Takes the interpreter's own exit status through a handle opened beforehand, so the venv launcher in between can't hide a crash.
        A job that still lists a process afterwards means an orphan: the kill-on-close would have removed it, so it is read first.
        """
        import ctypes

        kernel32 = native.kernel32
        kernel32.OpenProcess.restype = native.w.HANDLE
        kernel32.OpenProcess.argtypes = [native.w.DWORD, native.w.BOOL, native.w.DWORD]
        kernel32.GetExitCodeProcess.argtypes = [native.w.HANDLE, ctypes.POINTER(native.w.DWORD)]
        kernel32.WaitForSingleObject.argtypes = [native.w.HANDLE, native.w.DWORD]
        kernel32.WaitForSingleObject.restype = native.w.DWORD
        handle = kernel32.OpenProcess(0x1000 | 0x00100000, False, self.pid)  # query limited, synchronize
        if not handle:
            raise RuntimeError(f"cannot watch interpreter {self.pid}: {ctypes.get_last_error()}")
        before = self.job.pids()
        self._guard("close the window")
        began = time.monotonic()
        native.key_chord("alt", "f4")
        self._action("alt+f4", target="the main window")
        self.input_count += 1
        client, self.client = self.client, None
        client.close()
        wait_result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        seconds = time.monotonic() - began
        code = native.w.DWORD()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        exited = wait_result == 0
        facts = {"exited": exited, "seconds": round(seconds, 3), "pids_before": before,
                 "exit_status": code.value if exited else None, "exit_hex": hex(code.value) if exited else None,
                 "windows_after": native.windows_of(self.pid)}
        if exited and self.proc is not None:
            try:
                facts["launcher_exit"] = self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                facts["launcher_exit"] = None
        # Long enough for an ended child to be reaped and its console host to follow. Not long enough for a real encode to run out by itself:
        # a generous wait here once let a child that was never stopped look as though it had been.
        deadline = time.monotonic() + ORPHAN_GRACE_SECONDS
        remaining = self.job.pids()
        while remaining and time.monotonic() < deadline:
            time.sleep(0.05)
            remaining = self.job.pids()
        facts["orphans"] = [{"pid": pid, "image": winproc._image_name(pid)} for pid in remaining]
        facts["orphan_wait_seconds"] = round(time.monotonic() - began - seconds, 3)
        facts["stderr_tail"] = self.stderr_tail()
        self.exit_code = facts["exit_status"]
        self._log("closed by the user", **{key: value for key, value in facts.items() if key != "stderr_tail"})
        return facts

    # -- reading ---------------------------------------------------------------------------------- #
    def widget(self, tool: str | None, key: str) -> dict:
        return self.client.call("widget", scope=tool, key=key)

    def read(self, tool: str | None, key: str):
        return self.client.call("read", scope=tool, key=key)["value"]

    def settle(self, timeout: float = 15) -> None:
        """Until the window has stopped rearranging itself: the same layout on consecutive looks with nothing pending."""
        state = {"last": None, "steady": 0}

        def steady() -> bool:
            shape = self.client.call("layout")["shape"]
            state["steady"] = state["steady"] + 1 if shape == state["last"] else 0
            state["last"] = shape
            return state["steady"] >= 3

        wait_until(steady, timeout, "the window's layout to settle", poll=0.06)

    def stderr_tail(self, size: int = 4000) -> str:
        try:
            with open(self.stderr_path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - size))
                return handle.read().decode("utf-8", "replace")
        except OSError:
            return ""

    # -- guarded input ---------------------------------------------------------------------------- #
    def _guard(self, purpose: str, *, window: int | None = None) -> None:
        """Immediately before anything is sent: the desktop still usable and the foreground an owned window, or nothing goes."""
        status = native.desktop_status()
        if not status.ok:
            self._log("refused", purpose=purpose, reason=status.reason)
            raise native.DesktopUnavailable(f"before {purpose}: {status.reason}")
        hwnd, pid = native.foreground_owner()
        if pid != self.pid or (window is not None and hwnd != window):
            self._log("refused", purpose=purpose, foreground_pid=pid, foreground=hwnd, wanted=window or self.pid)
            raise native.ForegroundLost(f"before {purpose}: the foreground window belongs to process {pid}, not the owned {self.pid}")

    def click(self, tool: str | None, key: str, *, settle: float = 0.05) -> dict:
        target = self.widget(tool, key)
        return self._click_widget(target, f"{tool}:{key}", settle=settle)

    def click_path(self, path: str, *, settle: float = 0.05, offset: tuple[int, int] | None = None) -> dict:
        return self._click_widget(self.client.call("widget", path=path), path, settle=settle, offset=offset)

    def _click_widget(self, target: dict, label: str, *, settle: float, offset: tuple[int, int] | None = None) -> dict:
        if not target.get("exists") or not target.get("viewable"):
            self._log("refused", purpose=f"click {label}", state=target)
            raise native_refused(f"{label} is not on screen: {target}")
        if target.get("disabled"):
            self._log("refused", purpose=f"click {label}", state=target)
            raise native_refused(f"{label} is disabled")
        x = target["x"] + (offset[0] if offset else target["width"] // 2)
        y = target["y"] + (offset[1] if offset else target["height"] // 2)
        window = self.client.call("window")
        toplevel_is_root = target.get("toplevel") == "."
        if toplevel_is_root and not (window["x"] <= x < window["x"] + window["width"] and window["y"] <= y < window["y"] + window["height"]):
            self._log("refused", purpose=f"click {label}", x=x, y=y, window=window)
            raise native_refused(f"{label} at {x},{y} is outside the window {window}")
        native.move_to(x, y)  # hovering first, as a pointer does, gives ttk its active state
        time.sleep(0.03)
        self._guard(f"click {label}")
        at = self.client.call("containing", x=x, y=y)["path"]
        if at != target["path"]:
            self._log("refused", purpose=f"click {label}", containing=at, wanted=target["path"])
            raise native_refused(f"{label}: the widget under the pointer is {at}, not {target['path']}")
        hwnd = native.foreground_owner()[0]
        if native.root_window_at(x, y) != hwnd:
            self._log("refused", purpose=f"click {label}", root_at_point=native.root_window_at(x, y), foreground=hwnd)
            raise native_refused(f"{label}: another window covers the point {x},{y}")
        native.click_at(x, y)
        self.input_count += 1
        self._action("click", target=label, widget=target["path"], x=x, y=y, text=target.get("text"), widget_class=target["class"])
        time.sleep(settle)
        return target

    def type_into(self, tool: str | None, key: str, text: str, *, replace: bool = True) -> None:
        """Click, clear with the keyboard, type each character as a key event, then read back what the widget really holds."""
        self.click(tool, key)
        self._guard(f"type into {key}")
        if replace:
            native.key_chord("control", "a")
            native.key_tap("delete")
        if text:
            native.type_text(text)
        self.input_count += 1
        self._action("type", target=f"{tool}:{key}", text=text)
        wait_until(lambda: self.widget(tool, key).get("value") == text, 5, f"{key} to hold {text!r}")

    def key(self, name: str) -> None:
        self._guard(f"press {name}")
        native.key_tap(name)
        self.input_count += 1
        self._action("key", key=name)

    def chord(self, modifier: str, name: str) -> None:
        self._guard(f"press {modifier}+{name}")
        native.key_chord(modifier, name)
        self.input_count += 1
        self._action("chord", keys=[modifier, name])

    def wheel(self, tool: str | None, key: str, notches: int, *, settle: float = 0.05) -> dict:
        """The mouse wheel turned over a widget, as a hand turns it: positive notches scroll up (v0.7.2 Phase 5).

        The same refusals as a click: the widget must be on screen in the owned window, the pointer must really be over
        it, nothing may cover the point, and the foreground must still be ours when the notches are sent."""
        label = f"{tool}:{key}"
        target = self.widget(tool, key)
        if not target.get("exists") or not target.get("viewable"):
            self._log("refused", purpose=f"wheel over {label}", state=target)
            raise native_refused(f"{label} is not on screen: {target}")
        x, y = target["x"] + target["width"] // 2, target["y"] + target["height"] // 2
        native.move_to(x, y)
        time.sleep(0.03)
        self._guard(f"wheel over {label}")
        at = self.client.call("containing", x=x, y=y)["path"]
        if at != target["path"]:
            self._log("refused", purpose=f"wheel over {label}", containing=at, wanted=target["path"])
            raise native_refused(f"{label}: the widget under the pointer is {at}, not {target['path']}")
        hwnd = native.foreground_owner()[0]
        if native.root_window_at(x, y) != hwnd:
            self._log("refused", purpose=f"wheel over {label}", root_at_point=native.root_window_at(x, y), foreground=hwnd)
            raise native_refused(f"{label}: another window covers the point {x},{y}")
        native.wheel_at(x, y, notches)
        self.input_count += 1
        self._action("wheel", target=label, widget=target["path"], x=x, y=y, notches=notches)
        time.sleep(settle)
        return target

    def select_combo(self, tool: str | None, key: str, value: str) -> None:
        """Open its list with a click, walk there with the arrow keys, Return: what a person's hand does. The widget says what it now holds."""
        target = self.widget(tool, key)
        values = target.get("values", [])
        if value not in values:
            raise native_refused(f"{key} does not offer {value!r}; it offers {values}")
        here = values.index(target.get("value")) if target.get("value") in values else 0
        self.click(tool, key, settle=0.25)
        step = "down" if values.index(value) >= here else "up"
        for _ in range(abs(values.index(value) - here)):
            self.key(step)
            time.sleep(0.03)
        self.key("return")
        wait_until(lambda: self.widget(tool, key).get("value") == value, 5, f"{key} to hold {value!r}")
        self.settle()

    # -- native dialogs ----------------------------------------------------------------------------- #
    def wait_for_dialog(self, *, timeout: float = 20, title: str | None = None) -> dict:
        def found():
            for dialog in native.native_dialogs_of(self.pid):
                if title is None or title.lower() in dialog["title"].lower():
                    return dialog
            return None

        return wait_until(found, timeout, f"a native dialog{f' titled {title!r}' if title else ''}")

    def require_contained(self, what: str) -> dict:
        """Refuse, before any input, unless this session's interpreter is still running at Low integrity."""
        if self.containment is None or self.pid is None:
            raise containment.ContainmentUnavailable(f"{what}: this session never established its containment")
        return containment.require_low([self.pid], what)

    def file_dialog(self, paths: list[Path] | Path, *, title: str | None = None) -> None:
        """The real Windows file dialog: wait for it, type the path or quoted paths as keys, press Return, see it go."""
        dialog = self.wait_for_dialog(title=title)
        self.require_contained("the file dialog")
        wait_until(lambda: native.foreground_owner()[0] == dialog["hwnd"], 10, "the file dialog to take the foreground")
        self._guard("the file dialog", window=dialog["hwnd"])
        names = paths if isinstance(paths, list) else [paths]
        if len(names) == 1:
            text = str(names[0])
        else:
            folders = {str(Path(name).parent) for name in names}
            if len(folders) != 1:
                raise ValueError(f"a multiple selection must be from one folder: {folders}")
            text = " ".join(f'"{Path(name).name}"' for name in names)
            native.type_text(folders.pop())
            self.input_count += 1
            native.key_tap("return")
            time.sleep(0.5)
            self._guard("the file dialog", window=dialog["hwnd"])
        native.type_text(text)
        time.sleep(0.1)
        self._guard("the file dialog", window=dialog["hwnd"])
        native.key_tap("return")
        self.input_count += 1
        self._action("file dialog", title=dialog["title"], typed=text)
        wait_until(lambda: not any(item["hwnd"] == dialog["hwnd"] for item in native.windows_of(self.pid)), 15, "the file dialog to close")
        native.acquire_foreground(self.hwnd)

    def folder_dialog(self, folder: Path, *, title: str | None = None) -> None:
        """The real folder picker: type the path and Return, which may only navigate, then its own Select Folder button if it is still open."""
        dialog = self.wait_for_dialog(title=title)
        self.require_contained("the folder dialog")
        wait_until(lambda: native.foreground_owner()[0] == dialog["hwnd"], 10, "the folder dialog to take the foreground")
        self._guard("the folder dialog", window=dialog["hwnd"])
        native.type_text(str(folder))
        time.sleep(0.1)
        self._guard("the folder dialog", window=dialog["hwnd"])
        native.key_tap("return")
        self.input_count += 1
        self._action("folder dialog", title=dialog["title"], typed=str(folder))

        def still_open() -> bool:
            return any(item["hwnd"] == dialog["hwnd"] for item in native.windows_of(self.pid))

        for _ in range(40):
            if not still_open():
                break
            time.sleep(0.05)
        if still_open():
            controls = native.child_controls(dialog["hwnd"])
            buttons = [c for c in controls if c["class"] == "Button" and c["title"].replace("&", "").lower() in ("select folder", "ok", "open")]
            self._log("folder dialog buttons", buttons=[c["title"] for c in controls if c["class"] == "Button"])
            if not buttons:
                raise native_refused(f"no Select Folder button in {dialog['title']!r}: {[c['title'] for c in controls]}")
            left, top, right, bottom = buttons[0]["rect"]
            x, y = (left + right) // 2, (top + bottom) // 2
            self._guard("the folder dialog", window=dialog["hwnd"])
            if native.root_window_at(x, y) != dialog["hwnd"]:
                raise native_refused("another window covers the folder dialog's button")
            native.click_at(x, y)
            self.input_count += 1
            self._action("folder dialog button", button=buttons[0]["title"])
        wait_until(lambda: not still_open(), 15, "the folder dialog to close")
        native.acquire_foreground(self.hwnd)

    def answer_dialog(self, button: str, *, title: str | None = None, timeout: float = 20) -> dict:
        """A native message box's own button, found among its child controls and clicked at its own rectangle."""
        dialog = self.wait_for_dialog(title=title, timeout=timeout)
        wait_until(lambda: native.foreground_owner()[0] == dialog["hwnd"], 10, "the message box to take the foreground")
        controls = native.child_controls(dialog["hwnd"])
        wanted = button.replace("&", "").lower()
        matches = [c for c in controls if c["class"] == "Button" and c["title"].replace("&", "").lower() == wanted]
        if len(matches) != 1:
            raise native_refused(f"{len(matches)} buttons named {button!r} in {dialog['title']!r}: {[c['title'] for c in controls]}")
        left, top, right, bottom = matches[0]["rect"]
        x, y = (left + right) // 2, (top + bottom) // 2
        self._guard(f"answer {dialog['title']}", window=dialog["hwnd"])
        if native.root_window_at(x, y) != dialog["hwnd"]:
            raise native_refused(f"{button}: another window covers the message box button")
        text = [c["title"] for c in controls if c["class"] == "Static"]
        native.click_at(x, y)
        self.input_count += 1
        self._action("answer dialog", title=dialog["title"], button=button, body=text)
        wait_until(lambda: not any(item["hwnd"] == dialog["hwnd"] for item in native.windows_of(self.pid)), 10, "the message box to close")
        native.acquire_foreground(self.hwnd)
        return {"title": dialog["title"], "body": text}

    # -- evidence ----------------------------------------------------------------------------------- #
    def screenshot(self, name: str, *, window: int | None = None) -> str:
        if window is None and self.client is not None:
            self.settle()
            time.sleep(0.12)  # a settled layout still has to be drawn; this is for the picture, never for a decision
        path = self.screenshots / f"{name}.png"
        facts = native.screenshot(window or self.hwnd, path)
        tk_window = self.client.call("window") if self.client is not None and window is None else {}
        entry = {"name": path.name, **facts, "client": list(native.client_size(window or self.hwnd)),
                 "dpi": native.user32.GetDpiForWindow(window or self.hwnd), "tk": tk_window, "session": self.name}
        self.shots.append(entry)
        self._log("screenshot", **entry)
        return path.name

    def _log(self, kind: str, **facts) -> None:
        with open(self.actions, "a", encoding="utf-8") as sink:
            sink.write(json.dumps({"t": round(time.monotonic() - self.began, 3), "kind": kind, **facts}, default=str) + "\n")

    def _action(self, action: str, **facts) -> None:
        self._log("input", action=action, **facts)


def native_refused(message: str) -> native.InputRefused:
    return native.InputRefused(message)
