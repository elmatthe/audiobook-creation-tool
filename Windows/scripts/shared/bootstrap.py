"""bootstrap.py — first-run setup + launcher for the Audiobook Creation Tool.

Invoked by the root ``setup_and_run.bat`` (Windows) / ``setup_and_run.command``
(macOS). This is a **single cross-platform file** kept byte-identical in both the
``Windows/`` and ``MacOS/`` trees; all platform differences are branches inside it.
It is adapted from the legacy ``tts/setup_env.py`` (Path-A install-on-first-run
bootstrap) per the implementation plan.

Responsibilities, in order:

1. Platform sanity check (refuse the wrong OS).
2. **Fast path** — if a valid ``.venv`` already exists, launch the GUI and exit
   with no setup UI. (The ``.bat`` handles this even faster via ``pythonw`` so a
   normal launch never spawns a console; ``--launch-only`` routes here.)
3. **First run** — show a small Tk dialog (intro + Kokoro opt-in checkbox), then
   on a worker thread:
   - locate or install Python 3.11/3.12 (Kokoro wheels require <3.13),
   - create ``<os_root>/.venv`` with that interpreter,
   - ``pip install`` the pinned ``requirements.txt``,
   - ensure ffmpeg (winget ``Gyan.FFmpeg`` / Homebrew, portable fallback into
     ``resources/bin/``),
   - optionally pre-download the Kokoro model (~300 MB).
4. Launch the unified launcher GUI detached (``pythonw`` on Windows) and exit.

Every step is tee'd to ``resources/logs/setup_YYYY-MM-DD.log`` so a non-technical
user can attach a log when reporting a problem.

This module deliberately depends on **stdlib only** (plus Tk, which ships with
CPython) because it runs *before* the virtual environment and its packages exist.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# --- Path resolution -------------------------------------------------------
# This file lives at <os_root>/scripts/shared/bootstrap.py. Resolve the project
# layout from __file__ so the script is location-independent and never relies on
# the current working directory. We avoid importing shared.paths so bootstrap
# stays self-contained in the fragile pre-venv environment.
_THIS = Path(__file__).resolve()
SHARED_DIR = _THIS.parent
SCRIPTS_DIR = SHARED_DIR.parent
OS_ROOT = SCRIPTS_DIR.parent

RESOURCES_DIR = OS_ROOT / "resources"
LOGS_DIR = RESOURCES_DIR / "logs"
BIN_DIR = RESOURCES_DIR / "bin"
REQUIREMENTS_FILE = OS_ROOT / "requirements.txt"
VENV_DIR = OS_ROOT / ".venv"

# The unified launcher (built in Phase 3). Until it exists, fall back to the
# existing TTS GUI so first-run setup still ends with a working window.
LAUNCHER = SCRIPTS_DIR / "launcher.py"
LAUNCHER_FALLBACK = SCRIPTS_DIR / "tts" / "epub2tts_gui.py"

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# Make console output UTF-8 tolerant so progress messages with punctuation never
# raise on a legacy Windows codepage. No-op under pythonw (stdout is None).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

# Python versions acceptable for the venv. Kokoro's PyPI wheels require <3.13,
# so 3.12 is the sweet spot; 3.11 is also fine. 3.13+ works but loses Kokoro.
PREFERRED_PY = ("3.12", "3.11")
WINGET_PYTHON_ID = "Python.Python.3.12"

# Portable ffmpeg fallback (Windows only) — used if winget is unavailable.
FFMPEG_WIN_ZIP_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/"
    "ffmpeg-master-latest-win64-gpl.zip"
)


# ===========================================================================
#  Logging
# ===========================================================================
class SetupLog:
    """Tee setup output to a dated log file and an optional UI callback."""

    def __init__(self) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LOGS_DIR / f"setup_{datetime.now():%Y-%m-%d}.log"
        self._fh = open(self.path, "a", encoding="utf-8")
        self._ui: Optional[Callable[[str], None]] = None
        self.line(f"\n===== Setup run {datetime.now():%Y-%m-%d %H:%M:%S} =====")
        self.line(f"OS root: {OS_ROOT}")

    def set_ui_sink(self, sink: Optional[Callable[[str], None]]) -> None:
        self._ui = sink

    def line(self, msg: str) -> None:
        try:
            self._fh.write(msg + "\n")
            self._fh.flush()
        except Exception:
            pass
        if self._ui is not None:
            try:
                self._ui(msg)
            except Exception:
                pass
        # Mirror to stdout when one exists. Under pythonw.exe (the fast-path
        # launcher) sys.stdout is None, and the console codepage may not encode
        # every character — both are swallowed rather than allowed to crash the
        # critical launch path.
        try:
            if sys.stdout is not None:
                print(msg, flush=True)
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


LOG = SetupLog()


# ===========================================================================
#  Venv helpers
# ===========================================================================
def venv_python(windowed: bool = False) -> Path:
    """Return the path to the venv's interpreter.

    ``windowed=True`` returns ``pythonw.exe`` on Windows (no console window);
    elsewhere it is the same as the normal interpreter.
    """
    if IS_WINDOWS:
        name = "pythonw.exe" if windowed else "python.exe"
        return VENV_DIR / "Scripts" / name
    return VENV_DIR / "bin" / "python"


def venv_pip() -> list[str]:
    return [str(venv_python()), "-m", "pip"]


def venv_is_valid() -> bool:
    """A venv is usable if its interpreter exists and runs."""
    py = venv_python()
    if not py.exists():
        return False
    try:
        r = subprocess.run(
            [str(py), "-c", "import sys; print(sys.version)"],
            capture_output=True,
            text=True,
            timeout=30,
            **_hidden(),
        )
        return r.returncode == 0
    except Exception:
        return False


# ===========================================================================
#  Subprocess helper (hide console windows on Windows)
# ===========================================================================
def _hidden() -> dict:
    if not IS_WINDOWS:
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Run a command, capturing output, with the console hidden on Windows."""
    return subprocess.run(cmd, capture_output=True, text=True, **{**_hidden(), **kw})


# ===========================================================================
#  Locate / install a suitable Python interpreter for the venv
# ===========================================================================
def _candidate_interpreters() -> list[str]:
    """Build an ordered list of interpreter commands to probe."""
    cands: list[str] = []
    if IS_WINDOWS:
        # The py launcher can target an exact version.
        for ver in PREFERRED_PY:
            cands.append(f"py -{ver}")
        # Common per-user winget / python.org install locations.
        local = os.environ.get("LOCALAPPDATA", "")
        progfiles = os.environ.get("ProgramFiles", r"C:\Program Files")
        for ver in PREFERRED_PY:
            tag = ver.replace(".", "")
            if local:
                cands.append(str(Path(local) / "Programs" / "Python" / f"Python{tag}" / "python.exe"))
            cands.append(str(Path(progfiles) / f"Python{tag}" / "python.exe"))
        cands.append("python")
    else:
        for ver in PREFERRED_PY:
            cands.append(f"python{ver}")
        # Homebrew locations (Apple Silicon + Intel).
        for ver in PREFERRED_PY:
            cands.append(f"/opt/homebrew/bin/python{ver}")
            cands.append(f"/usr/local/bin/python{ver}")
        cands.append("python3")
    return cands


def find_suitable_python(log: SetupLog) -> Optional[list[str]]:
    """Return the argv prefix for a Python in PREFERRED_PY, else None.

    Returns a *list* because ``py -3.12`` is two tokens. Falls back to any
    interpreter that is at least 3.11 (warning that Kokoro needs <3.13).
    """
    log.line("Locating a suitable Python interpreter (3.12 preferred)…")
    best_any: Optional[list[str]] = None
    for cand in _candidate_interpreters():
        argv = cand.split() if " " in cand else [cand]
        # Skip absolute paths that don't exist (cheap check before spawning).
        if len(argv) == 1 and ("/" in cand or "\\" in cand) and not Path(cand).exists():
            continue
        if len(argv) == 1 and not (("/" in cand or "\\" in cand)) and shutil.which(argv[0]) is None:
            # Bare command not on PATH (except the 'py' launcher handled above).
            if argv[0] != "py":
                continue
        ver = _interp_version_argv(argv)
        if ver is None:
            continue
        ver_str = f"{ver[0]}.{ver[1]}"
        if ver_str in PREFERRED_PY:
            log.line(f"  Found Python {ver_str}: {' '.join(argv)}")
            return argv
        if ver >= (3, 11) and best_any is None:
            best_any = argv
    if best_any is not None:
        bv = _interp_version_argv(best_any)
        log.line(f"  No 3.12/3.11 found; using Python {bv[0]}.{bv[1]} "
                 "(note: Kokoro local voices require <3.13).")
        return best_any
    log.line("  No suitable Python found on this system.")
    return None


def _interp_version_argv(argv: list[str]) -> Optional[tuple[int, int]]:
    try:
        r = _run(argv + ["-c",
                 "import sys;print('%d.%d' % sys.version_info[:2])"], timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            major, minor = r.stdout.strip().split(".")
            return int(major), int(minor)
    except Exception:
        pass
    return None


def install_python(log: SetupLog) -> Optional[list[str]]:
    """Attempt to install Python 3.12, then re-locate it. Returns argv or None."""
    if IS_WINDOWS:
        if shutil.which("winget"):
            log.line(f"Installing {WINGET_PYTHON_ID} via winget (this can take a few minutes)…")
            r = _run(["winget", "install", "--id", WINGET_PYTHON_ID, "-e",
                      "--silent", "--accept-source-agreements",
                      "--accept-package-agreements"])
            log.line(r.stdout.strip() or "")
            if r.returncode != 0:
                log.line(f"  winget reported a problem: {r.stderr.strip()}")
        else:
            log.line("  winget not available — cannot auto-install Python.")
    elif IS_MAC:
        if shutil.which("brew"):
            log.line("Installing python@3.12 via Homebrew (this can take a few minutes)…")
            r = _run(["brew", "install", "python@3.12"])
            log.line(r.stdout.strip() or "")
            if r.returncode != 0:
                log.line(f"  brew reported a problem: {r.stderr.strip()}")
        else:
            log.line("  Homebrew not available — cannot auto-install Python.")
    # Re-probe regardless (the installer may have succeeded).
    return find_suitable_python(log)


# ===========================================================================
#  Setup steps
# ===========================================================================
def create_venv(py_argv: list[str], log: SetupLog) -> bool:
    log.line(f"Creating virtual environment at {VENV_DIR}…")
    r = _run(py_argv + ["-m", "venv", str(VENV_DIR)])
    if r.returncode != 0:
        log.line(f"  ERROR creating venv: {r.stderr.strip()}")
        return False
    log.line("  Virtual environment created.")
    return True


def pip_install_requirements(log: SetupLog) -> bool:
    pip = venv_pip()
    log.line("Upgrading pip…")
    _run(pip + ["install", "--upgrade", "pip"])
    if not REQUIREMENTS_FILE.exists():
        log.line(f"  ERROR: requirements.txt not found at {REQUIREMENTS_FILE}")
        return False
    log.line("Installing Python packages (this is the slowest step — "
             "Kokoro/torch are large)…")
    # Stream output line-by-line so the progress log stays alive during the long
    # download, rather than blocking silently on a single capture.
    proc = subprocess.Popen(
        pip + ["install", "-r", str(REQUIREMENTS_FILE)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **_hidden(),
    )
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if line:
            log.line("  " + line)
    code = proc.wait()
    if code != 0:
        log.line(f"  ERROR: pip install failed (exit {code}).")
        return False
    log.line("  All packages installed.")
    return True


def _ffmpeg_on_path() -> Optional[str]:
    return shutil.which("ffmpeg")


def _ffmpeg_in_bin() -> Optional[Path]:
    exe = BIN_DIR / ("ffmpeg.exe" if IS_WINDOWS else "ffmpeg")
    return exe if exe.exists() else None


def ensure_ffmpeg(log: SetupLog) -> bool:
    """Make ffmpeg available. Returns True if ffmpeg+ffprobe are usable."""
    if _ffmpeg_on_path():
        log.line(f"ffmpeg already on PATH: {_ffmpeg_on_path()}")
        return True
    if _ffmpeg_in_bin():
        log.line(f"ffmpeg already present in bundled bin: {BIN_DIR}")
        return True

    if IS_WINDOWS:
        if shutil.which("winget"):
            log.line("Installing ffmpeg via winget (Gyan.FFmpeg)…")
            r = _run(["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                      "--silent", "--accept-source-agreements",
                      "--accept-package-agreements"])
            if r.returncode == 0 and _ffmpeg_on_path():
                log.line("  ffmpeg installed via winget.")
                return True
            log.line("  winget install did not put ffmpeg on PATH this session — "
                     "falling back to a portable build.")
        return _download_portable_ffmpeg_windows(log)

    if IS_MAC:
        if shutil.which("brew"):
            log.line("Installing ffmpeg via Homebrew…")
            r = _run(["brew", "install", "ffmpeg"])
            if r.returncode == 0 and _ffmpeg_on_path():
                log.line("  ffmpeg installed via Homebrew.")
                return True
            log.line(f"  brew install ffmpeg problem: {r.stderr.strip()}")
        else:
            log.line("  Homebrew not found — install it from https://brew.sh/ then "
                     "re-run, or run: brew install ffmpeg")
        return _ffmpeg_on_path() is not None

    # Other (Linux) — best effort.
    log.line("  Please install ffmpeg via your package manager (apt/dnf/pacman).")
    return _ffmpeg_on_path() is not None


def _download_portable_ffmpeg_windows(log: SetupLog) -> bool:
    """Download a portable ffmpeg build into resources/bin (Windows fallback)."""
    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = BIN_DIR / "ffmpeg_portable.zip"
        log.line(f"Downloading portable ffmpeg from {FFMPEG_WIN_ZIP_URL}…")
        log.line("  (~80 MB, one-time. This may take a minute.)")
        urllib.request.urlretrieve(FFMPEG_WIN_ZIP_URL, zip_path)
        log.line("  Extracting…")
        with zipfile.ZipFile(zip_path) as zf:
            members = zf.namelist()
            wanted = [m for m in members
                      if m.endswith("/bin/ffmpeg.exe") or m.endswith("/bin/ffprobe.exe")]
            for m in wanted:
                data = zf.read(m)
                (BIN_DIR / Path(m).name).write_bytes(data)
        zip_path.unlink(missing_ok=True)
        if _ffmpeg_in_bin():
            log.line(f"  Portable ffmpeg ready in {BIN_DIR}.")
            return True
        log.line("  ERROR: ffmpeg.exe not found inside the downloaded archive.")
        return False
    except Exception as exc:  # network error, etc.
        log.line(f"  ERROR downloading portable ffmpeg: {exc}")
        log.line("  Manual install: https://github.com/BtbN/FFmpeg-Builds/releases")
        return False


def predownload_kokoro(log: SetupLog) -> None:
    """Pre-download the Kokoro model (~300 MB). Best-effort; never fatal."""
    py = venv_python()
    check = _run([str(py), "-c", "import kokoro"])
    if check.returncode != 0:
        log.line("Kokoro package not installed (Python may be 3.13+) — "
                 "skipping model pre-download.")
        return
    log.line("Pre-downloading Kokoro-82M model weights (~300 MB, one-time)…")
    script = (
        "from kokoro import KPipeline;"
        "KPipeline(lang_code='a');"
        "KPipeline(lang_code='b');"
        "print('Kokoro model download complete.')"
    )
    proc = subprocess.Popen([str(py), "-c", script],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, **_hidden())
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if line:
            log.line("  " + line)
    if proc.wait() == 0:
        log.line("  Kokoro voices ready.")
    else:
        log.line("  Kokoro pre-download had a problem; voices will download on "
                 "first use instead.")


# ===========================================================================
#  Launch the GUI
# ===========================================================================
def _launch_target() -> Path:
    return LAUNCHER if LAUNCHER.exists() else LAUNCHER_FALLBACK


def launch_gui(log: SetupLog) -> bool:
    """Spawn the launcher GUI detached so this process can exit."""
    target = _launch_target()
    if not target.exists():
        log.line(f"  ERROR: no GUI to launch (looked for {LAUNCHER} and "
                 f"{LAUNCHER_FALLBACK}).")
        return False
    pyw = venv_python(windowed=True)
    py = pyw if pyw.exists() else venv_python()
    if not py.exists():
        log.line(f"  ERROR: venv interpreter missing at {py}.")
        return False

    # Make a bundled portable ffmpeg discoverable to the launched app.
    env = os.environ.copy()
    if _ffmpeg_in_bin():
        env["PATH"] = str(BIN_DIR) + os.pathsep + env.get("PATH", "")

    log.line(f"Launching {target.name} via {py.name}…")
    try:
        if IS_WINDOWS:
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            subprocess.Popen([str(py), str(target)], cwd=str(SCRIPTS_DIR),
                             env=env, creationflags=flags, close_fds=True)
        else:
            subprocess.Popen([str(py), str(target)], cwd=str(SCRIPTS_DIR),
                             env=env, start_new_session=True)
        return True
    except Exception as exc:
        log.line(f"  ERROR launching GUI: {exc}")
        return False


# ===========================================================================
#  Orchestration (headless worker — drives the steps, reports progress)
# ===========================================================================
def run_setup(download_kokoro: bool, progress: Callable[[int, str], None],
              log: SetupLog) -> tuple[bool, str]:
    """Run the full setup. ``progress(step_index, message)`` updates the UI.

    Returns ``(success, final_message)``.
    """
    steps = ["Locating Python", "Creating environment", "Installing packages",
             "Installing ffmpeg"]
    if download_kokoro:
        steps.append("Downloading Kokoro voices")
    total = len(steps)

    progress(0, "Locating a suitable Python…")
    py_argv = find_suitable_python(log)
    if py_argv is None:
        py_argv = install_python(log)
    if py_argv is None:
        return False, ("Python 3.12 could not be found or installed automatically.\n"
                       "Please install Python 3.12 from python.org and run setup again.")

    progress(1, "Creating the virtual environment…")
    if not create_venv(py_argv, log):
        return False, "Failed to create the virtual environment (see the log)."

    progress(2, "Installing packages (largest step — please wait)…")
    if not pip_install_requirements(log):
        return False, "Failed to install Python packages (see the log)."

    progress(3, "Setting up ffmpeg…")
    if not ensure_ffmpeg(log):
        # Non-fatal: Edge TTS still works without ffmpeg for some paths, but most
        # tools need it. Surface clearly rather than crash.
        return False, ("ffmpeg could not be installed automatically.\n"
                       "Install it (https://ffmpeg.org/download.html) and re-run, "
                       "or see the log for the manual steps.")

    if download_kokoro:
        progress(4, "Downloading Kokoro AI voices (~300 MB)…")
        predownload_kokoro(log)

    progress(total, "Setup complete.")
    return True, "Setup complete."


# ===========================================================================
#  First-run Tk dialog
# ===========================================================================
def run_with_gui(skip_kokoro_default: bool = False) -> int:
    """Show the first-run setup dialog and drive the install on a worker thread."""
    import queue
    import tkinter as tk
    from tkinter import ttk, messagebox

    ui_queue: "queue.Queue[tuple]" = queue.Queue()

    root = tk.Tk()
    root.title("Audiobook Creation Tool — Setup")
    root.geometry("640x520")
    root.minsize(560, 440)
    try:
        ttk.Style().theme_use("vista" if IS_WINDOWS else "aqua")
    except Exception:
        pass

    container = ttk.Frame(root, padding=18)
    container.pack(fill="both", expand=True)

    state = {"download_kokoro": tk.BooleanVar(value=not skip_kokoro_default),
             "started": False, "done": False, "ok": False}

    # ---- Intro view -------------------------------------------------------
    intro = ttk.Frame(container)
    ttk.Label(intro, text="Welcome to the Audiobook Creation Tool",
              font=("Segoe UI" if IS_WINDOWS else "Helvetica", 16, "bold")
              ).pack(anchor="w", pady=(0, 8))
    ttk.Label(
        intro,
        text=("This one-time setup will install everything the app needs:\n"
              "  •  a private Python environment (kept inside this folder)\n"
              "  •  the audio libraries and ffmpeg\n"
              "  •  optionally, the local Kokoro AI voices (~300 MB)\n\n"
              "Nothing is installed system-wide except Python and ffmpeg if they\n"
              "are missing. After this finishes, the app opens automatically and\n"
              "future launches are instant."),
        justify="left",
    ).pack(anchor="w")
    ttk.Checkbutton(
        intro,
        text="Download the Kokoro AI voices now (~300 MB). "
             "If unchecked, they download the first time you pick a Kokoro voice.",
        variable=state["download_kokoro"],
    ).pack(anchor="w", pady=(16, 8))

    btn_row = ttk.Frame(intro)
    btn_row.pack(anchor="e", pady=(12, 0), fill="x")
    ttk.Button(btn_row, text="Cancel", command=root.destroy).pack(side="right", padx=(8, 0))
    begin_btn = ttk.Button(btn_row, text="Begin Setup")
    begin_btn.pack(side="right")
    intro.pack(fill="both", expand=True)

    # ---- Progress view ----------------------------------------------------
    progress_frame = ttk.Frame(container)
    step_var = tk.StringVar(value="Starting…")
    ttk.Label(progress_frame, textvariable=step_var,
              font=("Segoe UI" if IS_WINDOWS else "Helvetica", 12, "bold")
              ).pack(anchor="w", pady=(0, 8))
    bar = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
    bar.pack(fill="x", pady=(0, 12))
    log_box = tk.Text(progress_frame, height=14, wrap="word", state="disabled",
                      font=("Consolas" if IS_WINDOWS else "Menlo", 9))
    log_box.pack(fill="both", expand=True)

    def ui_log(msg: str) -> None:
        ui_queue.put(("log", msg))

    LOG.set_ui_sink(ui_log)

    def on_progress(step: int, message: str) -> None:
        ui_queue.put(("step", step, message))

    def worker() -> None:
        ok, final = run_setup(state["download_kokoro"].get(), on_progress, LOG)
        ui_queue.put(("done", ok, final))

    def append_log(msg: str) -> None:
        log_box.configure(state="normal")
        log_box.insert("end", msg + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")

    def begin() -> None:
        if state["started"]:
            return
        state["started"] = True
        intro.pack_forget()
        progress_frame.pack(fill="both", expand=True)
        # Read the checkbox at click time (the user may have toggled it). The
        # bar's maximum must match the step count run_setup will report.
        bar.configure(maximum=5 if state["download_kokoro"].get() else 4)
        threading.Thread(target=worker, daemon=True).start()

    begin_btn.configure(command=begin)

    def poll() -> None:
        try:
            while True:
                item = ui_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    append_log(item[1])
                elif kind == "step":
                    _, step, message = item
                    step_var.set(message)
                    bar.configure(value=step)
                elif kind == "done":
                    _, ok, final = item
                    state["done"], state["ok"] = True, ok
                    bar.configure(value=bar["maximum"])
                    step_var.set(final.splitlines()[0])
                    if ok:
                        append_log("Launching the app…")
                        launch_gui(LOG)
                        root.after(900, root.destroy)
                    else:
                        messagebox.showerror("Setup did not complete", final)
                        _add_failure_buttons()
        except queue.Empty:
            pass
        if not (state["done"] and not state["ok"]):
            root.after(120, poll)

    def _add_failure_buttons() -> None:
        fr = ttk.Frame(progress_frame)
        fr.pack(anchor="e", pady=(10, 0))
        ttk.Button(fr, text="Open log folder",
                   command=lambda: _open_folder(LOGS_DIR)).pack(side="right", padx=(8, 0))
        ttk.Button(fr, text="Close", command=root.destroy).pack(side="right")

    root.after(120, poll)
    root.mainloop()
    LOG.close()
    return 0 if state["ok"] else 1


def _open_folder(path: Path) -> None:
    try:
        if IS_WINDOWS:
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


# ===========================================================================
#  Entry point
# ===========================================================================
def _platform_sane() -> bool:
    """Refuse to run the wrong OS's flow (defence in depth; the .bat/.command
    already gate this)."""
    return IS_WINDOWS or IS_MAC or sys.platform.startswith("linux")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audiobook Creation Tool bootstrap")
    parser.add_argument("--launch-only", action="store_true",
                        help="Skip all setup checks and just launch the GUI "
                             "(used by the fast path once .venv exists).")
    parser.add_argument("--skip-kokoro-download", action="store_true",
                        help="Default the first-run Kokoro checkbox to unchecked.")
    parser.add_argument("--self-test", action="store_true",
                        help="Run detection logic only — no installs, no GUI. "
                             "For developer verification.")
    args = parser.parse_args(argv)

    if not _platform_sane():
        LOG.line(f"Unsupported platform: {sys.platform}")
        return 2

    if args.self_test:
        return _self_test()

    if args.launch_only:
        ok = launch_gui(LOG)
        LOG.close()
        return 0 if ok else 1

    # Fast path: a valid venv already exists → just launch.
    if venv_is_valid():
        LOG.line("Existing virtual environment detected — launching.")
        ok = launch_gui(LOG)
        LOG.close()
        return 0 if ok else 1

    # First run → interactive setup.
    return run_with_gui(skip_kokoro_default=args.skip_kokoro_download)


def _self_test() -> int:
    """Exercise the read-only detection paths without installing anything."""
    LOG.line("[self-test] Running detection-only checks (no installs)…")
    LOG.line(f"[self-test] OS_ROOT          = {OS_ROOT}")
    LOG.line(f"[self-test] VENV_DIR         = {VENV_DIR} (exists={VENV_DIR.exists()})")
    LOG.line(f"[self-test] venv_is_valid    = {venv_is_valid()}")
    LOG.line(f"[self-test] requirements.txt = {REQUIREMENTS_FILE} "
             f"(exists={REQUIREMENTS_FILE.exists()})")
    py = find_suitable_python(LOG)
    LOG.line(f"[self-test] suitable Python  = {py}")
    LOG.line(f"[self-test] ffmpeg on PATH   = {_ffmpeg_on_path()}")
    LOG.line(f"[self-test] ffmpeg in bin    = {_ffmpeg_in_bin()}")
    LOG.line(f"[self-test] launch target    = {_launch_target()} "
             f"(exists={_launch_target().exists()})")
    LOG.line("[self-test] OK — detection logic ran without side effects.")
    LOG.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
