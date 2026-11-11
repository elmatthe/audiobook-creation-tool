"""One real setup action inside an extracted copy of the application (a child of fresh_windows.py). Standard library only: it is
run by the copy's own base Python before any environment exists, and by the copy's environment afterwards.

    <python> fresh_copy.py --out <folder> --copy <extracted app> --mode install|repair|status|tools [--stop-after-pip 4]

Every function it calls is the copy's own production code (``bootstrap.run_setup``, ``bootstrap.repair_venv``, the launcher and
its six tools). It refuses unless the code it imported really is the copy's, and the copy is not this checkout, so nothing here
can install into, repair or read the settings of the development installation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[3]


def children_of_this_process() -> list[str]:
    """Images of every process below this one, read from Windows' own process list."""
    import ctypes
    import ctypes.wintypes as wt

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG),
                    ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]

    k = ctypes.WinDLL("kernel32")
    k.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(ENTRY)]
    k.CloseHandle.argtypes = [wt.HANDLE]
    snapshot = k.CreateToolhelp32Snapshot(2, 0)
    entry = ENTRY()
    entry.dwSize = ctypes.sizeof(ENTRY)
    parents = {}
    more = k.Process32FirstW(snapshot, ctypes.byref(entry))
    while more:
        parents[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile)
        more = k.Process32NextW(snapshot, ctypes.byref(entry))
    k.CloseHandle(snapshot)
    mine, grew = {os.getpid()}, True
    found = []
    while grew:
        grew = False
        for pid, (parent, image) in parents.items():
            if parent in mine and pid not in mine:
                mine.add(pid)
                found.append(f"{image} ({pid})")
                grew = True
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--copy", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("install", "repair", "status", "tools"))
    parser.add_argument("--stop-after-pip", type=float, default=None)
    args = parser.parse_args()
    copy = args.copy.resolve()
    record: dict = {"mode": args.mode, "python": sys.executable, "version": sys.version.split()[0], "copy": str(copy)}
    began = time.monotonic()
    try:
        sys.path.insert(0, str(copy / "scripts"))
        from shared import bootstrap

        if Path(bootstrap.REPO_ROOT).resolve() != copy or copy == CHECKOUT.resolve() or CHECKOUT.resolve() in copy.parents:
            raise SystemExit(f"refused: the code imported belongs to {bootstrap.REPO_ROOT}, not the extracted copy {copy}")
        record["app_root"] = str(bootstrap.REPO_ROOT)
        if args.mode in ("install", "repair"):
            steps: list = []
            stop: dict = {}
            if args.stop_after_pip is not None:
                def watch() -> None:
                    seen = None
                    while not stop.get("asked"):
                        proc = bootstrap._RUNNING_PIP
                        if proc is not None and proc.poll() is None:
                            seen = seen or time.monotonic()
                            if time.monotonic() - seen >= args.stop_after_pip:
                                stop.update(asked=True, pip_pid=proc.pid, at=round(time.monotonic() - began, 2),
                                            told_a_running_pip=bootstrap.request_setup_stop())
                                return
                        time.sleep(0.1)

                threading.Thread(target=watch, daemon=True).start()
            if args.mode == "install":
                ok, final = bootstrap.run_setup(lambda step, message: steps.append([step, message, round(time.monotonic() - began, 1)]),
                                                bootstrap.LOG)
            else:
                ok, final = bootstrap.repair_venv(bootstrap.LOG, headless=True)
            returned = time.monotonic()
            record.update(ok=bool(ok), final=str(final), steps=steps, stop=stop, seconds=round(returned - began, 1))
            if stop.get("asked"):
                # Nothing of the stopped setup may outlive it: looked for at once and again after a short grace.
                record["children_when_setup_returned"] = children_of_this_process()
                time.sleep(3)
                record["children_three_seconds_later"] = children_of_this_process()
                record["stopped_message"] = bootstrap.SETUP_STOPPED_MESSAGE
            bootstrap.LOG.close()
        elif args.mode == "status":
            attempts: list = []

            def hook(event, arguments):
                if event == "socket.connect" and not str(arguments[1:2]).count("127.0.0.1"):
                    attempts.append(str(arguments[1])[:100])
                    raise PermissionError("offline status check")
                if event == "socket.getaddrinfo" and arguments[0] not in (None, "", "localhost", "127.0.0.1", "::1"):
                    attempts.append(f"name lookup: {str(arguments[0])[:80]}")
                    raise PermissionError("offline status check")

            sys.addaudithook(hook)
            record["venv_python"] = Path(sys.executable).resolve().is_relative_to(copy / ".venv")
            imports = {}
            for name in ("edge_tts", "pydub", "mutagen", "fitz", "PIL", "numpy", "nltk", "tkinter"):
                try:
                    __import__(name)
                    imports[name] = True
                except Exception as exc:  # noqa: BLE001 - recorded
                    imports[name] = f"{type(exc).__name__}: {exc}"[:160]
            record["imports"] = imports
            from shared import ffmpeg_utils, nltk_store

            record["ffmpeg_verified"] = bool(ffmpeg_utils.verified_ffmpeg())
            record["ffmpeg"] = ffmpeg_utils.ffmpeg_path() and str(ffmpeg_utils.ffmpeg_path())
            record["sentence_data_problem"] = nltk_store.problem(copy)
            from tts import voice_install, voice_registry

            # Each voice's own answer, asked the way the TTS panel asks it before a run: is it usable here, and if not, would the
            # panel offer Install & Continue for it. An Edge voice needs nothing installed.
            voices: dict = {}
            for entry in voice_registry.VOICES:
                backend, voice_id = entry.backend, entry.voice_id
                if backend == "edge":
                    voices[f"{backend}:{voice_id}"] = {"usable": True, "reason": "", "offered": None}
                    continue
                try:
                    if backend == "qwen3":
                        from tts import qwen3_runtime

                        usable, reason = qwen3_runtime.voice_availability(voice_id)
                    else:
                        usable, reason = voice_install.models_status(backend, voice_id)
                    offered = voice_install.installable(backend, voice_id, reason)
                except Exception as exc:  # noqa: BLE001 - recorded, and it fails the check that reads it
                    usable, reason, offered = None, f"{type(exc).__name__}: {exc}", None
                voices[f"{backend}:{voice_id}"] = {"usable": usable, "reason": str(reason)[:240], "offered": offered}
            record["voices"] = voices
            record["voice_counts"] = {backend: sum(1 for key in voices if key.startswith(backend + ":")) for backend in voice_registry.BACKENDS}
            record["network_attempts"] = attempts
            record["optional_folders"] = {name: (copy / name).exists() for name in
                                          (".venv/engines", "files/runtime-data/models", "files/runtime-data/chatterbox", ".venv-qwen3")}
        elif args.mode == "tools":
            import tkinter as tk
            from tkinter import messagebox

            import launcher
            from shared import config as shared_config
            from shared import output_paths, paths

            # Before any window: the copy's own settings file, and an output base inside this run's folder, read back from the
            # application's effective configuration. Refused before anything is built if either is not so.
            outputs = (args.out / "outputs").resolve()
            settings_file = Path(paths.SETTINGS_FILE).resolve()
            if not settings_file.is_relative_to(copy):
                raise SystemExit(f"refused: the settings file is {settings_file}, outside the extracted copy")
            shared_config.set_output_base(str(outputs))
            effective = Path(output_paths.resolve_output_base(shared_config.get_effective())).resolve()
            if effective != outputs:
                raise SystemExit(f"refused: the effective output base is {effective}, not {outputs}")
            from shared import subprocess_utils as sp

            reveals: list = []
            sp.reveal_in_file_manager = lambda path, *a, **k: reveals.append(str(path))
            os.startfile = lambda *a, **k: reveals.append(str(a[:1]))
            record.update(settings_file=str(settings_file), output_base=str(effective), reveals=reveals)
            errors, boxes = [], []
            for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
                setattr(messagebox, name, lambda *a, _n=name, **k: boxes.append([_n, *map(str, a)]) or False)
            root = tk.Tk()
            root.report_callback_exception = lambda exc, val, tb: errors.append("".join(traceback.format_exception(exc, val, tb))[-600:])
            app = launcher.LauncherApp(root)
            root.update()
            offered = [spec.key for spec in app._available_tools()]
            visited = []
            for key in offered:
                app.select_tool(key)
                for _ in range(15):
                    root.update()
                    time.sleep(0.02)
                visited.append([key, app.current_key == key])
            record.update(offered=offered, visited=visited, errors=errors, message_boxes=boxes, title=root.title(),
                          geometry=root.winfo_geometry(), output_created=outputs.exists() and any(outputs.rglob("*")))
            root.destroy()
        record["finished"] = True
    except SystemExit as exc:
        record["refused"] = str(exc)
    except BaseException:  # noqa: BLE001 - the record is the result
        record["error"] = traceback.format_exc()[-2500:]
    record["total_seconds"] = round(time.monotonic() - began, 1)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "result.json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
    return 0 if record.get("finished") else 1


if __name__ == "__main__":
    raise SystemExit(main())
