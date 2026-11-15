"""Test-only (v0.8.x P1B): the REAL launcher in an isolated instance, plus the one piece of work a KX test asks for.

    python macos_gui_driver.py <config.json>

Runs ``launcher.main()`` itself, so the window, its close path, its signal routing, its containment owner and the way
the process ends are production's. It differs from a user's launch only here, and the KX tests name each in their
evidence:

  * settings, logs and runtime data point into the test's scratch (the module constants the gate's Windows adapter
    sets); the proved FFmpeg record is copied in, so the pinned pair is the one used.
  * once the window is up, a worker thread starts the work the scenario names, through the production spawn path:
      - ``ffmpeg``: one long FFmpeg step through ``subprocess_utils.run_supervised`` (what every tool's FFmpeg step
        uses), on the adopted FFmpeg;
      - ``setup``: a stand-in optional-setup worker through ``optional_setup_protocol._contained_spawn`` (what
        ``WorkerRun.start`` uses), which runs a stand-in pip -- a Python program that starts a long-running child,
        as pip starts a build backend -- through the production ``qwen3_setup.run_command``;
      - ``guardian-loss``: an FFmpeg step, then (once the test has killed the guardian and the owner has ended that
        step) a second one.
  * negative controls only: ``contain: false`` takes the window's containment away (no owner, no lifeline, no
    guardian); ``lifeline: false`` installs an owner whose class-A children get no lifeline.
  * a close the test asks for is made by calling the command the window already has for it: the window's
    ``WM_DELETE_WINDOW`` protocol (the red button) or ``::tk::mac::Quit`` (the application menu's Quit and Cmd+Q).

Every line the driver writes to ``out`` is ``WORD values...``; the test reads them. Never shipped.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

CONFIG = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
OUT = Path(CONFIG["out"])
REQUESTS = Path(CONFIG["requests"])
_note_lock = threading.Lock()


def note(*words) -> None:
    with _note_lock, open(OUT, "a", encoding="utf-8") as sink:
        sink.write(" ".join(str(w) for w in words) + "\n")


def _isolate() -> None:
    from shared import ffmpeg_health, paths

    runtime = Path(CONFIG["runtime"])
    (runtime / "logs").mkdir(parents=True, exist_ok=True)
    paths.RESOURCES_DIR = runtime
    paths.LOGS_DIR = runtime / "logs"
    paths.SETTINGS_FILE = runtime / "settings.json"
    ffmpeg_health.RESOURCES_DIR = runtime
    state = REPO_ROOT / "files" / "runtime-data" / ffmpeg_health.HEALTH_STATE_NAME
    if state.is_file():
        shutil.copyfile(state, runtime / ffmpeg_health.HEALTH_STATE_NAME)
    settings = {"output_base_directory": CONFIG["output"], "last_tool": CONFIG.get("last_tool", "mp3_tool")}
    (runtime / "settings.json").write_text(json.dumps(settings, indent=1), encoding="utf-8")


_isolate()

from shared import child_ownership, ffmpeg_utils  # noqa: E402
from shared import subprocess_utils as sp  # noqa: E402

import launcher  # noqa: E402

if CONFIG.get("contain", True) is False:
    sp.enable_containment = lambda log=None: None  # negative control: no owner, no lifeline, no guardian
if CONFIG.get("lifeline", True) is False:
    child_ownership._OWNER = child_ownership.Owner(lifeline=False)  # negative control: class A without the lifeline


def _ffmpeg_argv() -> list[str]:
    ffmpeg = ffmpeg_utils.ffmpeg_path()
    if not ffmpeg:
        note("ERROR no pinned FFmpeg")
        raise SystemExit(4)
    return [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-re", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=600", "-f", "null", "-"]


def _watch_media_children(stop: threading.Event) -> None:
    """Report each FFmpeg the window's owner registers, with its guardian (registry reads only; no Tk)."""
    seen: set[int] = set()
    count = 0
    while not stop.is_set():
        owner = sp.containment_owner()
        if owner is not None:
            for child in owner.children():
                if child.kind == child_ownership.CLASS_B and child.pid not in seen:
                    seen.add(child.pid)
                    count += 1
                    note("FFMPEG", count, child.pid, child.pgid)
        time.sleep(0.02)


def _plain_ffmpeg() -> None:
    """For the negative control (no owner): report the FFmpeg the step started, found as this process's own child."""
    argv = _ffmpeg_argv()
    original = subprocess.Popen

    class Reporting(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if args and isinstance(args[0], list) and args[0] and args[0][0] == argv[0]:
                note("FFMPEG", 1, self.pid, os.getpgid(self.pid))

    subprocess.Popen = Reporting  # type: ignore[misc]
    sp.run_supervised(argv)


def _scenario_ffmpeg() -> None:
    if sp.containment_owner() is None:
        _plain_ffmpeg()
        return
    result = sp.run_supervised(_ffmpeg_argv())
    note("STEP", 1, result.returncode)


def _scenario_guardian_loss() -> None:
    first = sp.run_supervised(_ffmpeg_argv())
    owner = sp.containment_owner()
    note("STEP", 1, first.returncode, "degraded", owner.degraded)
    second = sp.run_supervised(_ffmpeg_argv())
    note("STEP", 2, second.returncode)


STANDIN_PIP = ("import os, subprocess, sys, time; "
               "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)']); "
               "print('PIDS', os.getpid(), g.pid, flush=True); time.sleep(600)")

STANDIN_WORKER = f"""
import os, sys, threading
sys.path.insert(0, {str(SCRIPTS)!r})
from pathlib import Path
from shared import subprocess_utils
from tts import qwen3_setup
out = {str(OUT)!r}
def note(text):
    with open(out, "a", encoding="utf-8") as sink:
        sink.write(text + "\\n")
note("WORKER %d %d %s" % (os.getpid(), os.getpgrp(), any(t.name == "act-lifeline" for t in threading.enumerate())))
code = qwen3_setup.run_command([sys.executable, "-c", {STANDIN_PIP!r}], env=dict(os.environ), cwd=Path({str(SCRIPTS)!r}),
                               on_line=lambda line: note("PIP " + line))
note("PIPDONE %s %s" % (code, subprocess_utils.containment_owner() is not None))
"""


def _scenario_setup() -> None:
    from shared import optional_setup_protocol as proto

    script = Path(CONFIG["runtime"]) / "standin_worker.py"
    script.write_text(STANDIN_WORKER, encoding="utf-8")
    proc = proto._contained_spawn([sys.executable, "-E", "-s", str(script)], cwd=str(SCRIPTS),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace")
    note("SETUP", proc.pid, os.getpgid(proc.pid))
    for line in proc.stdout:
        note("WORKEROUT", line.rstrip())
    note("SETUPDONE", proc.wait())


SCENARIOS = {"ffmpeg": _scenario_ffmpeg, "setup": _scenario_setup, "guardian-loss": _scenario_guardian_loss,
             "idle": lambda: None}


def _poll_requests(app) -> None:
    """A close the test asks for, made through the command the window already has for it."""
    try:
        request = REQUESTS.read_text(encoding="utf-8").strip() if REQUESTS.exists() else ""
    except OSError:
        request = ""
    if request:
        REQUESTS.unlink(missing_ok=True)
        note("REQUEST", request, time.time())
        if request == "close":  # the red button
            app.root.tk.call(app.root.protocol("WM_DELETE_WINDOW"))
        elif request == "quit":  # the application menu's Quit and Cmd+Q
            app.root.tk.eval("::tk::mac::Quit")
        return
    app.root.after(50, _poll_requests, app)


def _started(app) -> None:
    owner = sp.containment_owner()
    note("GUI", os.getpid(), os.getpgrp(), "owner", owner is not None,
         "aqua", app.root.tk.call("tk", "windowingsystem") == "aqua")
    stop = threading.Event()
    threading.Thread(target=_watch_media_children, args=(stop,), name="kx-watch", daemon=True).start()
    work = SCENARIOS[CONFIG.get("scenario", "idle")]
    threading.Thread(target=work, name="kx-work", daemon=True).start()
    app.root.after(50, _poll_requests, app)


_original_init = launcher.LauncherApp.__init__


def _init(self, root, *args, **kwargs):
    _original_init(self, root, *args, **kwargs)
    root.after(200, _started, self)


launcher.LauncherApp.__init__ = _init

if __name__ == "__main__":
    code = launcher.main()
    note("MAIN_RETURNED", code, time.time())
    sys.exit(code)
