"""The REAL first-run setup window on macOS, from a disposable copy of the application, with the in-process driver beside it. Test-only.

Runs ``bootstrap.run_with_gui()`` itself, which is what ``Setup_and_Run-audiobook-creation-tool.command`` runs when there is no
environment yet: production's window, its Tk controls, its worker thread, its messages and its exit code. It is started by
``adapters/macos/app_session.py`` on the interpreter a first run uses (the app's own base Python), so the in-process driver acts on it
exactly as it acts on the application (``app_launcher.MacChannel``: a control is invoked through Tk, the spawn record, the Tk thread
audit, the picture of the window). It differs from a person's first run in exactly these places, each named in the journey's evidence:

  * the application is a copy made for this scenario (``app_root``). ``bootstrap.py`` takes every folder it owns from where it is, so
    the copy is the only installation it can create, repair or write a log into. It refuses to start unless that is so.
  * opening a folder in Finder, and starting the application once setup has finished, are recorded instead of performed (neither is
    reachable by a journey that cancels; the record is what proves it).
  * three tripwires that only ever record and refuse, never alter what the window does when nothing unauthorized is attempted:
      - ``bootstrap.run_setup`` -- the install itself -- refuses and records if anything calls it. A journey that must never install
        cannot install even if a click went where it was not meant to; its record must show no such call.
      - a network connection to anything but this computer is refused and recorded (``network-attempt``), so a download cannot happen
        silently and the record shows none was tried.
      - every child process the window starts is recorded the moment it starts (``children.jsonl``, by the app launcher).

Nothing else is replaced. In particular the window's choices, their defaults, their estimates, Cancel and the exit status are
production's own; a journey never scripts an outcome.

Usage: python setup_launcher.py <config.json>
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The app launcher reads sys.argv[1] at import and puts the application's scripts/ (the copy's) first on sys.path.
launcher = _load("act_macos_app_launcher_for_setup", HERE / "app_launcher.py")
CONFIG = launcher.CONFIG
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", ""})


def main() -> int:
    app_root = Path(CONFIG["app_root"])
    record = Path(CONFIG["record"])

    def note(kind: str, **facts) -> None:
        with open(record, "a", encoding="utf-8") as sink:
            sink.write(json.dumps({"kind": kind, "at": time.monotonic(), **facts}) + "\n")

    from shared import bootstrap

    if (Path(bootstrap.REPO_ROOT).resolve() != app_root.resolve() or app_root.resolve() == REPO_ROOT.resolve()
            or REPO_ROOT.resolve() in app_root.resolve().parents):
        raise SystemExit(f"refused: setup would run on {bootstrap.REPO_ROOT}, not the disposable copy {app_root}")
    note("started", app_root=str(bootstrap.REPO_ROOT), bootstrap_file=str(Path(bootstrap.__file__).resolve()), venv=str(bootstrap.VENV_DIR),
         logs=str(bootstrap.LOGS_DIR), interpreter=sys.executable, platform=sys.platform,
         choices=[[component, label, bool(default)] for component, label, default, _note in bootstrap.OPTIONAL_CHOICES],
         cancelled_status=bootstrap.EXIT_SETUP_CANCELLED)

    launcher._record_spawns()  # every child process the window starts, the moment it starts: children.jsonl

    def refuse_setup(*_args, **_kwargs):
        note("run-setup-called")
        raise RuntimeError("the install was called by a journey that must never install; the gate's tripwire refuses it")

    bootstrap.run_setup = refuse_setup
    bootstrap._open_folder = lambda path: note("open-folder", path=str(path))
    bootstrap.launch_gui = lambda log: note("launch-gui") or True

    def host_of(address) -> str:
        if isinstance(address, (tuple, list)) and address:
            return str(address[0])
        return "" if isinstance(address, (bytes, str)) else str(address)  # a Unix socket's path is local

    real_connect, real_connect_ex, real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def guarded(real):
        def connect(self, address, *rest):
            if self.family != socket.AF_UNIX and host_of(address) not in _LOOPBACK:
                note("network-attempt", address=repr(address)[:120])
                raise OSError("the gate refuses a connection to anything but this computer during a first-run journey")
            return real(self, address, *rest)

        return connect

    socket.socket.connect, socket.socket.connect_ex = guarded(real_connect), guarded(real_connect_ex)

    def resolving(host, *rest, **kwargs):
        if str(host) not in _LOOPBACK:
            note("network-attempt", address=f"resolve {str(host)[:100]}")
            raise socket.gaierror("the gate refuses to resolve a name during a first-run journey")
        return real_getaddrinfo(host, *rest, **kwargs)

    socket.getaddrinfo = resolving

    import tkinter as tk

    class SetupChannel(launcher.MacChannel):
        """The app launcher's channel, with one honest difference in how a picture is described. The application's windows are drawn in
        the appearance ``shared.appearance`` holds (its setting); the first-run window never reads it, so it is drawn in the system's.
        A picture's record states what AppKit drew, with its source, instead of an application setting this window does not have; the
        gate's review still compares that against the pixels."""

        def _op_labels(self, request: dict) -> dict:
            """What each label on screen asked for and what it was given, read only: a wrapped label's text is cut when the width it
            asked for (the widest line it laid out) exceeds the width it got. The picture review judges a wrapped label on height only,
            so this is what shows a line cut at the right edge."""
            found = []

            def walk(widget) -> None:
                for child in widget.winfo_children():
                    if child.winfo_class() == "TLabel" and child.winfo_viewable():
                        found.append({"path": str(child), "text": str(child.cget("text")), "wraplength": int(str(child.cget("wraplength")) or 0),
                                      "width": child.winfo_width(), "reqwidth": child.winfo_reqwidth(), "height": child.winfo_height(),
                                      "reqheight": child.winfo_reqheight()})
                    walk(child)

            walk(self.root)
            return {"ok": True, "labels": found}

        def _op_capture(self, request: dict) -> dict:
            answer = super()._op_capture(request)
            native = str((answer.get("appearance") or {}).get("native") or "")
            if answer.get("captured") and native:
                answer["appearance"] = {"app": "dark" if "Dark" in native else "light", "native": native,
                                        "source": "the system's appearance: the first-run window has no appearance setting of its own"}
            return answer

    real_tk = tk.Tk

    class ObservedTk(real_tk):
        """The window ``run_with_gui`` makes, with the driver's Tk thread audit and its channel attached the moment it exists."""

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.tk = launcher.ThreadCheckingTk(self.tk)  # before any widget exists, so every widget shares it
            self._acceptance_channel = SetupChannel(self, channel_file=CONFIG["channel_file"], resolve=lambda scope: self)

    tk.Tk = ObservedTk
    code = bootstrap.run_with_gui()
    note("exit", code=code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
