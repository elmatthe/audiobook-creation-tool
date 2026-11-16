"""One isolated ACT instance on macOS, driven in-process through Tk (v0.8.x P1B, plan section 14.3, MAC-045, D9).

The same verbs as ``adapters/windows/app_session.py``, so the journeys run unchanged, done the only honest way this
programme has on macOS: the application's own observation channel acts through Tk (``invoke``, generated events, the
widgets' own values), and the file, folder and message dialogs are in-process stand-ins the session answers. What that
does not exercise -- the native NSOpenPanel and NSAlert, real pointer and keyboard input, the Dock, the menu bar, Finder --
is never claimed here. Since the P1B closeout the pixels are: ``screenshot`` images the application's own window through
the window server (no Screen Recording grant is needed for a process's own window), with Tk's audit of that moment and a
provenance record (source SHA, tool, appearance, size, state) beside it; a session started with ``native_dialogs`` leaves
the real NSOpenPanel and NSAlert in place and answers them through ``expect_native`` (adapters/macos/native_ui.py).

From outside the process, as on Windows: the application starts in its own process group; its exit status is the
interpreter's own; every child it starts is recorded the moment it starts (pid, kernel start time, group), so an orphan
is found by identity after the window has gone, and so is any member left in a group the application owned. Tear-down
ends what is left by identity only (pid and start time), never by a name.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE_DIR = HERE.parents[1]
REPO_ROOT = GATE_DIR.parents[2]
for _path in (str(GATE_DIR), str(REPO_ROOT / "scripts" / "shared")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import child_ownership  # noqa: E402  (stdlib only: the kernel start-time reader)

from helpers import visual_review  # noqa: E402

from . import containment  # noqa: E402
from . import native_input as native  # noqa: E402

_SOURCE: dict = {}


def source_identity() -> dict:
    """What a picture is of: the checkout's HEAD and whether the application or the gate differ from it (read once)."""
    if not _SOURCE:
        def git(*args):
            done = subprocess.run(["git", "-C", str(REPO_ROOT), "--no-optional-locks", *args], capture_output=True, text=True)
            return done.stdout.strip() if done.returncode == 0 else ""

        dirty = git("status", "--porcelain=v1", "--", "scripts", "files/dev-work/verification-gate", ":!files/dev-work/verification-gate/outputs")
        _SOURCE.update(sha=git("rev-parse", "HEAD") or None, branch=git("rev-parse", "--abbrev-ref", "HEAD") or None,
                       dirty=bool(dirty), dirty_paths=dirty.splitlines()[:40])
    return dict(_SOURCE)

STARTUP_SECONDS = 90
ORPHAN_GRACE_SECONDS = 1.5
POLL_SECONDS = 0.05


class JourneyTimeout(TimeoutError):
    """A readiness predicate never came true within its bound."""


class ChannelError(RuntimeError):
    """The observation channel refused or answered with an error."""


def wait_until(predicate, timeout: float, what: str, poll: float = POLL_SECONDS):
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
        self.stream.write(json.dumps({"token": self.token, "op": op, **arguments}).encode("utf-8") + b"\n")
        self.stream.flush()
        line = self.stream.readline()
        if not line:
            raise ChannelError(f"the channel closed during {op}")
        answer = json.loads(line)
        if "error" in answer:
            raise ChannelError(f"{op}: {answer['error']}")
        return answer

    def close(self) -> None:
        for item in (self.stream, self.socket):
            try:
                item.close()
            except OSError:
                pass


def _alive(identity) -> bool:
    pid, start = identity
    return start is not None and child_ownership.process_start_time(pid) == start


def _group_occupied(pgid: int) -> bool:
    try:
        os.killpg(int(pgid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _Job:
    """What the application started, as the spawn record and the kernel say -- the Windows job's ``pids()``."""

    def __init__(self, session: "AppSession") -> None:
        self.session = session

    def records(self) -> list[dict]:
        path = self.session.work / "children.jsonl"
        if not path.exists():
            return []
        found = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                found.append(json.loads(line))
            except ValueError:
                continue
        return found

    def identities(self) -> list[tuple[int, tuple]]:
        return [(item["pid"], tuple(item["start"]) if item.get("start") else None) for item in self.records()]

    def pids(self) -> list[int]:
        alive = [pid for pid, start in self.identities() if _alive((pid, start))]
        if self.session.pid and self.session.identity and _alive(self.session.identity):
            alive.insert(0, self.session.pid)
        return alive


class AppSession:
    """Start with ``start()``; leave with ``close_by_user()`` or ``tear_down()``. ``evidence`` and ``work`` belong to one scenario."""

    def __init__(self, evidence: Path, work: Path, *, script: Path | None = None, config: dict | None = None, name: str = "app") -> None:
        self.evidence = Path(evidence).resolve()
        self.work = Path(work).resolve()  # the application runs with this as its working folder
        self.name = name
        self.script = script or HERE / "app_launcher.py"
        self.config = dict(config or {})
        self.actions = evidence / f"{name}-actions.jsonl"
        self.screenshots = self.evidence / "screenshots"
        self.shots: list[dict] = []
        self.proc: subprocess.Popen | None = None
        self.job = _Job(self)
        self.client: _Client | None = None
        self.pid: int | None = None
        self.identity = None
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
        temp = self.work / "t"
        temp.mkdir(exist_ok=True)
        channel_file = self.work / f"{self.name}-channel.json"
        config = {"channel_file": str(channel_file), "runtime_dir": str(self.work / "runtime"), "pictures_dir": str(self.screenshots),
                  **self.config}
        config_path = self.work / f"{self.name}-config.json"
        config_path.write_text(json.dumps(config, indent=1), encoding="utf-8")
        env = dict(os.environ)
        env.update(TMPDIR=str(temp), PYTHONDONTWRITEBYTECODE="1")
        for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "ACT_STARTUP_NOTICE"):
            env.pop(key, None)
        self.evidence.mkdir(parents=True, exist_ok=True)
        stderr = open(self.stderr_path, "xb")
        try:
            # Its own process group: what the application starts without a group of its own stays in this one, so
            # tear-down and the orphan check reach it.
            self.proc = subprocess.Popen([sys.executable, "-I", "-B", str(self.script), str(config_path)], cwd=self.work, env=env,
                                         stdin=subprocess.DEVNULL, stdout=stderr, stderr=stderr, start_new_session=True)
        finally:
            stderr.close()
        self.identity = (self.proc.pid, child_ownership.process_start_time(self.proc.pid))
        self._log("launched", pid=self.proc.pid, ownership="own process group")
        info = wait_until(lambda: self._read_channel_file(channel_file), startup, "the application's observation channel")
        self.pid = int(info["pid"])
        if self.pid != self.proc.pid:
            raise RuntimeError(f"the channel answers for {self.pid}, not the started interpreter {self.proc.pid}")
        self.hwnd = self.pid
        native.SESSIONS[self.pid] = self
        self.client = _Client(info)
        self.containment = {"own_group": os.getpgid(self.pid) == self.pid}
        if not self.containment["own_group"]:
            raise containment.ContainmentUnavailable("the application is not in its own process group")
        wait_until(lambda: self.client.call("window")["width"] > 1, startup, "the application's main window")
        self._log("window", pid=self.pid, screen=self.client.call("screen"))
        return self

    def _read_channel_file(self, path: Path):
        if self.proc is not None and self.proc.poll() is not None:
            raise RuntimeError(f"the application ended during startup with exit {self.proc.returncode}: {self.stderr_tail()}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def check_input_round_trip(self) -> None:
        """Windows proves real input arrives; on macOS there is no real input to prove (D9)."""

    def check_geometry_mapping(self) -> None:
        """Tk's own coordinates are the only ones used on macOS; there is nothing to map."""

    def tear_down(self) -> dict:
        """End whatever is left of this session's tree, by identity only. Always safe to call."""
        facts = {"forced": False}
        if self.client is not None:
            self.client.close()
            self.client = None
        if self.proc is not None and self.proc.poll() is None:
            facts["forced"] = True
            child_ownership.signal_if_same(self.proc.pid, self.identity[1], signal.SIGKILL)
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                facts["wait_timeout"] = True
        left = [identity for identity in self.job.identities() if _alive(identity)]
        if left:
            facts["ended_at_tear_down"] = [pid for pid, _ in left]
            for pid, start in left:
                child_ownership.signal_if_same(pid, start, signal.SIGKILL)
            deadline = time.monotonic() + 10
            while any(_alive(identity) for identity in left) and time.monotonic() < deadline:
                time.sleep(0.05)
        facts["survivors"] = [pid for pid, start in self.job.identities() if _alive((pid, start))]
        facts["groups_occupied"] = self._occupied_groups()
        native.SESSIONS.pop(self.pid, None)
        self._log("tear down", **facts)
        return facts

    def _occupied_groups(self) -> list[int]:
        groups = {self.pid} | {item["pgid"] for item in self.job.records() if item.get("pgid")}
        return sorted(group for group in groups if group and _group_occupied(group))

    def close_by_user(self, *, timeout: float = 45, how: str = "close") -> dict:
        """The red button (``how="close"``) or the application menu's Quit / Cmd+Q (``how="quit"``), through the commands
        the window already has for them; then observed from outside: exit status, windows, every recorded child."""
        watch = self.exit_watch()
        self.client.call("close", how=how)
        self._action("close" if how == "close" else "quit", target="the main window")
        self.input_count += 1
        return self._observe_exit(watch, timeout, "closed by the user")

    def exit_watch(self) -> tuple:
        return (self.job.pids(), time.monotonic())

    def wait_for_exit(self, watch: tuple, *, timeout: float = 60) -> dict:
        return self._observe_exit(watch, timeout, "ended by itself")

    def _observe_exit(self, watch: tuple, timeout: float, how: str) -> dict:
        before, began = watch
        audit = self._audit()
        client, self.client = self.client, None
        if client is not None:
            client.close()
        try:
            self.proc.wait(timeout=timeout)
            exited = True
        except subprocess.TimeoutExpired:
            exited = False
        seconds = time.monotonic() - began
        facts = {"exited": exited, "seconds": round(seconds, 3), "pids_before": before,
                 "exit_status": self.proc.returncode if exited else None,
                 "exit_hex": hex(self.proc.returncode & 0xFFFFFFFF) if exited else None, "windows_after": [],
                 "launcher_exit": self.proc.returncode if exited else None}
        deadline = time.monotonic() + ORPHAN_GRACE_SECONDS
        remaining = [identity for identity in self.job.identities() if _alive(identity)]
        while remaining and time.monotonic() < deadline:
            time.sleep(0.05)
            remaining = [identity for identity in remaining if _alive(identity)]
        facts["orphans"] = [{"pid": pid, "image": native.image_name(pid)} for pid, _ in remaining]
        facts["groups_occupied"] = self._occupied_groups() if exited else []
        if facts["groups_occupied"] and not facts["orphans"]:
            facts["orphans"] = [{"pgid": group, "image": "an unrecorded member of an owned group"} for group in facts["groups_occupied"]]
        facts["orphan_wait_seconds"] = round(time.monotonic() - began - seconds, 3)
        facts["tk_off_thread"] = audit
        facts["stderr_tail"] = self.stderr_tail()
        self.exit_code = facts["exit_status"]
        self._log(how, **{key: value for key, value in facts.items() if key != "stderr_tail"})
        return facts

    def _audit(self) -> list:
        """Every Tk call a worker thread made, as the application's own record has it (MAC-032)."""
        path = self.work / "tk-thread-audit.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # -- reading ---------------------------------------------------------------------------------- #
    def widget(self, tool: str | None, key: str) -> dict:
        return self.client.call("widget", scope=tool, key=key)

    def read(self, tool: str | None, key: str):
        return self.client.call("read", scope=tool, key=key)["value"]

    def settle(self, timeout: float = 15) -> None:
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

    # -- acting through Tk ------------------------------------------------------------------------- #
    def _acted(self, answer: dict, label: str, action: str, **facts) -> dict:
        if not answer.get("ok"):
            self._log("refused", purpose=f"{action} {label}", reason=answer.get("refused"), state=answer)
            raise native.InputRefused(f"{label}: {answer.get('refused')}")
        self.input_count += 1
        self._action(action, target=label, widget=answer.get("path"), text=answer.get("text"),
                     widget_class=answer.get("class"), **facts)
        return answer

    def click(self, tool: str | None, key: str, *, settle: float = 0.05) -> dict:
        answer = self._acted(self.client.call("invoke", scope=tool, key=key), f"{tool}:{key}", "click")
        time.sleep(settle)
        return answer

    def click_path(self, path: str, *, settle: float = 0.05, offset: tuple[int, int] | None = None) -> dict:
        answer = self._acted(self.client.call("invoke", path=path, offset=list(offset) if offset else None), path, "click",
                             offset=offset)
        time.sleep(settle)
        return answer

    def type_into(self, tool: str | None, key: str, text: str, *, replace: bool = True) -> None:
        self._acted(self.client.call("type", scope=tool, key=key, text=text, replace=replace), f"{tool}:{key}", "type", typed=text)
        wait_until(lambda: self.widget(tool, key).get("value") == text, 5, f"{key} to hold {text!r}")

    def key(self, name: str) -> None:
        self.client.call("key", name=name)
        self.input_count += 1
        self._action("key", key=name)

    def _guard(self, purpose: str, *, window=None) -> None:
        """Before an act aimed at one window: that window holds Tk's keyboard focus (the in-process foreground)."""
        if window is None:
            return
        owner = native.foreground_owner()[0]
        if owner != window:
            self._log("refused", purpose=purpose, focus_window=owner, wanted=window)
            raise native.ForegroundLost(f"before {purpose}: the focus is in {owner}, not {window}")

    def chord(self, modifier: str, name: str) -> None:
        """The chord exactly as the journey names it (Tk's Text binds <Control-Home> on every platform). Windows' Alt+F4
        -- close the window that has the foreground -- is, on macOS, that window's own close button: its
        ``WM_DELETE_WINDOW`` protocol, called for the top-level that holds the focus."""
        if (modifier.lower(), name.lower()) == ("alt", "f4"):
            answer = self.client.call("close_focused")
            self.input_count += 1
            self._action("close the focused window", window=answer.get("toplevel"))
            return
        modifier = {"ctrl": "Control", "cmd": "Command"}.get(modifier.lower(), modifier.capitalize())
        self.client.call("key", name=name, modifier=modifier)
        self.input_count += 1
        self._action("chord", keys=[modifier, name])

    def type_text(self, text: str) -> None:
        """Typed into whichever widget has the focus, at its insertion point, one key at a time."""
        answer = self.client.call("type_focus", text=text)
        if not answer.get("ok"):
            raise native.InputRefused(f"typing {text!r}: {answer.get('refused')}")
        self.input_count += 1
        self._action("type", target=answer.get("path"), typed=text)
        time.sleep(0.1)

    def wheel(self, tool: str | None, key: str, notches: int, *, settle: float = 0.05) -> dict:
        answer = self._acted(self.client.call("wheel", scope=tool, key=key, notches=int(notches)), f"{tool}:{key}", "wheel",
                             notches=notches)
        time.sleep(settle)
        return answer

    def select_combo(self, tool: str | None, key: str, value: str) -> None:
        target = self.widget(tool, key)
        values = target.get("values", [])
        if value not in values:
            raise native.InputRefused(f"{key} does not offer {value!r}; it offers {values}")
        self._acted(self.client.call("select", scope=tool, key=key, value=value), f"{tool}:{key}", "select", value=value)
        wait_until(lambda: self.widget(tool, key).get("value") == value, 5, f"{key} to hold {value!r}")
        self.settle()

    # -- dialogs (in-process stand-ins; the native panels are owner-manual) ----------------------- #
    def pending_dialogs(self) -> list[dict]:
        if self.client is None:
            return []
        return self.client.call("dialogs")["dialogs"]

    def wait_for_dialog(self, *, timeout: float = 20, title: str | None = None, kinds: tuple | None = None) -> dict:
        def found():
            for dialog in self.pending_dialogs():
                if (title is None or title.lower() in dialog["title"].lower()) and (kinds is None or dialog["kind"] in kinds):
                    return dialog
            return None

        return wait_until(found, timeout, f"a dialog{f' titled {title!r}' if title else ''}")

    def require_contained(self, what: str) -> dict:
        if self.pid is None or self.proc is None or self.proc.poll() is not None:
            raise containment.ContainmentUnavailable(f"{what}: the application is not running")
        return {"own_group": os.getpgid(self.pid) == self.pid}

    def _answer(self, dialog: dict, answer, action: str, **facts) -> None:
        result = self.client.call("answer", id=dialog["id"], answer=answer)
        if not result.get("ok"):
            raise native.InputRefused(f"{dialog['title']!r}: {result.get('refused')}")
        self.input_count += 1
        self._action(action, title=dialog["title"], dialog_kind=dialog["kind"], answer=answer, stand_in=True,
                     options=dialog.get("options", {}), **facts)
        wait_until(lambda: all(item["id"] != dialog["id"] for item in self.pending_dialogs()), 15, "the dialog to close")

    def file_dialog(self, paths: list[Path] | Path, *, title: str | None = None) -> None:
        dialog = self.wait_for_dialog(title=title, kinds=("askopenfilename", "askopenfilenames", "asksaveasfilename"))
        names = [str(item) for item in (paths if isinstance(paths, list) else [paths])]
        if dialog["kind"] != "askopenfilenames" and len(names) != 1:
            raise native.InputRefused(f"{dialog['title']!r} takes one file, not {len(names)}")
        self._answer(dialog, names, "file dialog")

    def folder_dialog(self, folder: Path, *, title: str | None = None) -> None:
        dialog = self.wait_for_dialog(title=title, kinds=("askdirectory",))
        self._answer(dialog, str(folder), "folder dialog")

    def answer_dialog(self, button: str, *, title: str | None = None, timeout: float = 20) -> dict:
        dialog = self.wait_for_dialog(title=title, timeout=timeout,
                                      kinds=("showinfo", "showwarning", "showerror", "askyesno", "askokcancel",
                                             "askyesnocancel", "askquestion", "askretrycancel"))
        wanted = button.replace("&", "")
        if wanted.lower() not in [item.lower() for item in dialog["buttons"]]:
            raise native.InputRefused(f"{dialog['title']!r} has no {button!r} button: {dialog['buttons']}")
        body = [text for text in (dialog.get("message"), dialog.get("detail")) if text]
        self._answer(dialog, wanted, "answer dialog", button=wanted, body=body)
        return {"title": dialog["title"], "body": body}

    # -- native dialogs (a session started with config native_dialogs) ------------------------------ #
    def expect_native(self, *items: dict) -> None:
        """The next native panels, in order: ``{"kind": "open"|"save"|"alert", "respond": "cancel"|"return"|"escape",
        "capture": picture name or None}``. Answered inside the application by ``native_ui.NativeWatcher``."""
        answer = self.client.call("native_expect", items=list(items))
        if not answer.get("ok"):
            raise native.InputRefused(f"native dialogs: {answer.get('refused')}")

    def native_events(self) -> list[dict]:
        path = self.work / "native-dialogs.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # -- evidence ----------------------------------------------------------------------------------- #
    def screenshot(self, name: str, *, window=None, tool: str | None = None, state: str | None = None) -> str:
        """The application's own window as the window server shows it, with its provenance and review beside it.

        ``window`` names a top-level the way ``windows_of`` does; a stand-in dialog has no window of its own, so its
        picture is of the window behind it and says so (``subject``). A picture that could not be taken is recorded with
        ``captured`` false and why: never a pass (``helpers/visual_review.py``).

        A picture the review finds out of register (the window server's image offset from the window's bounds for an
        instant) is retaken a bounded number of times, each rejected image kept and listed in the sidecar's ``retakes``;
        nothing else is retaken (``visual_review.take_in_register``)."""
        self.screenshots.mkdir(parents=True, exist_ok=True)
        path = self.screenshots / f"{name}.png"
        toplevel, subject = ".", "window"
        if isinstance(window, str) and ":dialog:" in window:
            subject = "window behind an in-process stand-in dialog"
        elif isinstance(window, str) and ":" in window:
            toplevel = window.split(":", 1)[1]
        record, retakes = visual_review.take_in_register(
            lambda: self._take(path, name, toplevel, subject, tool, state), path,
            log=lambda item: self._log("screenshot retake", name=path.name, **item))
        record["retakes"] = retakes
        path.with_suffix(".json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
        entry = {"name": path.name, "captured": bool(record["captured"]), "sidecar": path.with_suffix(".json").name,
                 "review": record["review"]["status"], "tool": record.get("tool"), "state": record["state"],
                 "appearance": (record.get("appearance") or {}).get("app"), "viewport": record.get("viewport"),
                 "sha": record.get("sha"), "session": self.name, "retakes": len(retakes)}
        self.shots.append(entry)
        self._log("screenshot", **entry, reason=record["review"].get("reason"))
        return entry["name"]

    def _take(self, path: Path, name: str, toplevel: str, subject: str, tool: str | None, state: str | None) -> dict:
        """One capture into ``path`` and its review: the record a sidecar holds."""
        record = {"name": path.name, "session": self.name, "scenario": self.evidence.name, "state": state or name,
                  "subject": subject, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **source_identity()}
        if self.client is None:
            record.update(captured=False, why="the application is not running")
        else:
            try:
                answer = self.client.call("capture", path=str(path), toplevel=toplevel)
            except ChannelError as exc:
                answer = {"captured": False, "why": str(exc)}
            record.update({key: value for key, value in answer.items() if key != "ok"})
            record["tool"] = tool or answer.get("current_tool")
            record["viewport"] = answer.get("content_points")
        if record.get("captured") and path.is_file():
            record["sha256"] = visual_review.sha256(path)
        else:
            record["captured"] = False
        record["review"] = visual_review.review(path, record)
        return record

    def _log(self, kind: str, **facts) -> None:
        self.evidence.mkdir(parents=True, exist_ok=True)
        with open(self.actions, "a", encoding="utf-8") as sink:
            sink.write(json.dumps({"t": round(time.monotonic() - self.began, 3), "kind": kind, **facts}, default=str) + "\n")

    def _action(self, action: str, **facts) -> None:
        self._log("input", action=action, mechanism="in-process Tk", **facts)


def native_refused(message: str) -> native.InputRefused:
    return native.InputRefused(message)
