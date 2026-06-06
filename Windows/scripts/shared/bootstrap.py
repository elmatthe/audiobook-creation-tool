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
import time
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
    """A venv is usable if its interpreter exists, runs, and can import ssl.

    ``ssl`` is required for pip and edge-tts; a venv whose interpreter cannot
    import it is broken (a known failure mode when the base Python was built
    without OpenSSL). Treating such a venv as invalid sends the bootstrap down
    the recreate path instead of launching a half-working app.
    """
    py = venv_python()
    if not py.exists():
        return False
    try:
        r = subprocess.run(
            [str(py), "-c", "import sys, ssl; print(sys.version)"],
            capture_output=True,
            text=True,
            timeout=30,
            **_hidden(),
        )
        return r.returncode == 0
    except Exception:
        return False


# ===========================================================================
#  Kokoro self-heal (probe + in-venv repair install)
# ===========================================================================
# The pinned Kokoro stack. These mirror requirements.txt exactly; they are the
# *wheels* (mandatory — required for `import kokoro` to succeed), distinct from
# the optional ~300 MB model weights pre-download (gated by the first-run
# checkbox / --skip-kokoro-download). torch is pulled in transitively by kokoro.
KOKORO_PKGS = ["kokoro==0.9.4", "soundfile==0.13.1", "scipy==1.17.1"]


def kokoro_is_healthy(venv_py: Path) -> tuple[bool, str]:
    """Probe the venv for kokoro + soundfile + scipy. Returns ``(ok, reason)``.

    Uses ``importlib.util.find_spec`` (cheap — does not import torch) so the
    check is fast enough to run on every launch without slowing the fast path.
    """
    probe = (
        "import importlib.util as u, sys; "
        "mods = ['kokoro', 'soundfile', 'scipy']; "
        "missing = [m for m in mods if u.find_spec(m) is None]; "
        "print('MISSING:' + ','.join(missing) if missing else 'OK'); "
        "sys.exit(0 if not missing else 1)"
    )
    try:
        r = subprocess.run(
            [str(venv_py), "-c", probe],
            capture_output=True, text=True, timeout=30, **_hidden(),
        )
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out == "OK":
            return True, "ok"
        return False, out or (r.stderr or "").strip() or "unknown"
    except Exception as exc:
        return False, f"probe failed: {exc!r}"


def ensure_kokoro_installed(venv_py: Path, log: Callable[[str], None]) -> bool:
    """Install the pinned Kokoro stack into the existing venv. Returns True on success.

    This is the *self-heal* path: it pip-installs into the venv that already
    exists (never --user, never system site-packages). ``log`` is the same
    callable the rest of the bootstrap uses, so output is tee'd to the setup log
    and the repair dialog's live log pane.
    """
    log(f"Installing Kokoro stack into venv: {' '.join(KOKORO_PKGS)}")
    try:
        r = subprocess.run(
            [str(venv_py), "-m", "pip", "install", "--no-input", *KOKORO_PKGS],
            capture_output=True, text=True, timeout=600, **_hidden(),
        )
        if r.stdout:
            log(r.stdout.strip())
        if r.returncode != 0:
            if r.stderr:
                log(r.stderr.strip())
            return False
        ok, reason = kokoro_is_healthy(venv_py)
        log(f"Post-install health-check: {reason}")
        return ok
    except Exception as exc:
        log(f"ensure_kokoro_installed failed: {exc!r}")
        return False


def warmup_kokoro_pipeline(venv_py: Path, log: Callable[[str], None]) -> None:
    """One-shot KPipeline load to pre-warm Kokoro at install time.

    On fresh Windows 11 Home machines, Smart App Control / WDAC blocks Kokoro's
    unsigned native DLLs (e.g. ``sparselinear``) the *first* time they are loaded
    ("An Application Control policy has blocked this file"), which would otherwise
    surface as a failed first synthesis for the default voice (``af_heart``).
    Loading the pipeline once here — inside the install/repair dialog — forces the
    OS to evaluate (and then allow) those DLLs now, so the user's first real
    synthesis just works. Best-effort: any error is logged, never raised, since
    the worst case is the first synthesis retries (the kokoro_synth single-retry
    wrapper also absorbs a residual transient block).
    """
    log("Initializing AI voice engine (first-run only)…")
    # Force the project-tree HF cache for the subprocess regardless of whether the
    # parent set HF_HOME, so the warmup never leaks the ~300 MB model into the
    # user's home (~/.cache/huggingface/).
    hf_cache = RESOURCES_DIR / "models" / "huggingface"
    env = os.environ.copy()
    env["HF_HOME"] = env.get("HF_HOME") or str(hf_cache)
    env.setdefault("HUGGINGFACE_HUB_CACHE", str(hf_cache / "hub"))
    script = (
        "import sys\n"
        "try:\n"
        "    from kokoro import KPipeline\n"
        "    KPipeline(lang_code='a')\n"
        "    print('Kokoro pipeline warmup complete.')\n"
        "except OSError as e:\n"
        "    print('Kokoro warmup blocked (will retry on first synthesis): %r' % (e,))\n"
        "except Exception as e:\n"
        "    print('Kokoro warmup problem (non-fatal): %r' % (e,))\n"
    )
    try:
        proc = subprocess.Popen(
            [str(venv_py), "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=env, **_hidden(),
        )
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if line:
                log("  " + line)
        proc.wait()
    except OSError as exc:
        log(f"  Kokoro warmup could not run: {exc!r}")


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
#  Capability probes (tkinter / ssl / venv / functional Tcl-Tk / ffprobe)
# ===========================================================================
def _as_argv(py) -> list[str]:
    return [str(x) for x in py] if isinstance(py, list) else [str(py)]


def _probe_import(py, module: str) -> bool:
    """Return True if ``<py> -c 'import <module>'`` exits 0."""
    try:
        return _run(_as_argv(py) + ["-c", f"import {module}"], timeout=30).returncode == 0
    except Exception:
        return False


def _tcl_tk_ok(py) -> bool:
    """True only if Tk can actually *initialize* (not merely import)."""
    try:
        return _run(_as_argv(py) + ["-c", "import tkinter; tkinter.Tcl()"],
                    timeout=30).returncode == 0
    except Exception:
        return False


def probe_capabilities(py) -> dict:
    """Test an interpreter for everything the GUI/app needs."""
    return {
        "tkinter": _probe_import(py, "tkinter"),
        "ssl": _probe_import(py, "ssl"),
        "venv": _probe_import(py, "venv"),
        "tcl_tk_functional": _tcl_tk_ok(py),
    }


def _ffprobe_available() -> bool:
    if shutil.which("ffprobe"):
        return True
    exe = BIN_DIR / ("ffprobe.exe" if IS_WINDOWS else "ffprobe")
    return exe.exists()


def _refresh_brew_path() -> None:
    """Add Homebrew's bin dirs to this process's PATH (Apple Silicon + Intel).

    A fresh ``brew install`` lands in ``/opt/homebrew/bin`` (Apple Silicon) or
    ``/usr/local/bin`` (Intel), which need not be on the PATH this already-running
    process inherited. Re-add them so a subsequent ``shutil.which`` finds the new
    binary in the same session.
    """
    if not IS_MAC:
        return
    cur = os.environ.get("PATH", "").split(os.pathsep)
    for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
        if Path(prefix).exists() and prefix not in cur:
            os.environ["PATH"] = prefix + os.pathsep + os.environ.get("PATH", "")


def _brew_install_python_tk(log: "SetupLog") -> None:
    """On macOS, add Tk support for Homebrew's python@3.12 (python-tk@3.12)."""
    if not IS_MAC or not shutil.which("brew"):
        return
    log.line("Installing Tk support for Python (python-tk@3.12) via Homebrew…")
    r = _run(["brew", "install", "python-tk@3.12"])
    if r.returncode != 0:
        log.line(f"  brew install python-tk@3.12 problem: {r.stderr.strip()}")
    else:
        log.line("  python-tk@3.12 installed.")


def preflight_report(py, log: "SetupLog") -> dict:
    """Log a human-readable capability table for the chosen interpreter."""
    caps = probe_capabilities(py)

    def mark(ok: bool) -> str:
        return "[OK]" if ok else "[XX]"

    log.line("Preflight report:")
    log.line(f"  {mark(sys.version_info[:2] >= (3, 11))} Python >= 3.11")
    log.line(f"  {mark(caps['venv'])} venv support")
    log.line(f"  {mark(caps['tkinter'])} tkinter import")
    log.line(f"  {mark(caps['tcl_tk_functional'])} Tcl/Tk functional")
    log.line(f"  {mark(caps['ssl'])} ssl support")
    log.line(f"  {mark(bool(_ffmpeg_on_path() or _ffmpeg_in_bin()))} ffmpeg")
    log.line(f"  {mark(_ffprobe_available())} ffprobe")
    return caps


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


def find_suitable_python(log: SetupLog, prefer_tk: bool = True) -> Optional[list[str]]:
    """Return the argv prefix for a Python suitable for the venv, else None.

    Preference order:
      1. The interpreter already running this bootstrap, when it is 3.11/3.12 and
         (if ``prefer_tk``) GUI-capable — the launcher selected it and, on macOS,
         verified Tk works, so the venv base stays consistent with that choice.
      2. A discovered 3.12/3.11 that is GUI-capable.
      3. (macOS) a 3.12/3.11 that lacks Tk → try ``brew install python-tk@3.12``
         and re-probe.
      4. Any 3.11+ interpreter (warning that Kokoro needs <3.13).

    With ``prefer_tk=False`` (the ``--headless`` path) Tk is not required, so the
    first 3.12/3.11 found is accepted. Returns a *list* because ``py -3.12`` is
    two tokens.
    """
    log.line("Locating a suitable Python interpreter (3.12 preferred)…")

    # 1. Prefer the running interpreter when it is already a good target. Only
    #    accept <3.13 here so we never silently pick 3.13 over an available 3.12
    #    (3.13 loses Kokoro); a 3.13-only system still falls through to step 4.
    cur_ver = sys.version_info[:2]
    if sys.executable and (3, 11) <= cur_ver < (3, 13):
        if not prefer_tk or _tcl_tk_ok([sys.executable]):
            log.line(f"  Using the current interpreter: {sys.executable} "
                     f"(Python {cur_ver[0]}.{cur_ver[1]})")
            return [sys.executable]

    best_any: Optional[list[str]] = None      # any >=3.11 fallback
    pref_no_tk: Optional[list[str]] = None     # a 3.12/3.11 that lacks Tk
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
            if not prefer_tk or _tcl_tk_ok(argv):
                log.line(f"  Found GUI-capable Python {ver_str}: {' '.join(argv)}")
                return argv
            if pref_no_tk is None:
                pref_no_tk = argv
        elif ver >= (3, 11) and best_any is None:
            best_any = argv

    # 3. A preferred-version Python exists but has no Tk. On macOS we can fix it.
    if pref_no_tk is not None:
        if prefer_tk and IS_MAC and shutil.which("brew"):
            _brew_install_python_tk(log)
            if _tcl_tk_ok(pref_no_tk):
                log.line(f"  Tk support installed; using {' '.join(pref_no_tk)}")
                return pref_no_tk
            log.line("  Tk still unavailable after python-tk install.")
        log.line(f"  Using {' '.join(pref_no_tk)} (GUI may be unavailable; the "
                 "command line still works).")
        return pref_no_tk

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


def install_python(log: SetupLog, prefer_tk: bool = True) -> Optional[list[str]]:
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
            # Homebrew's python@3.12 has no working Tk unless python-tk is added.
            if prefer_tk:
                _brew_install_python_tk(log)
        else:
            log.line("  Homebrew not available — cannot auto-install Python.")
    # Re-probe regardless (the installer may have succeeded).
    return find_suitable_python(log, prefer_tk=prefer_tk)


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


def _create_validated_venv(py_argv: list[str], log: SetupLog,
                           headless: bool) -> bool:
    """Create the venv and confirm it is actually usable.

    A Tk-capable *base* Python must produce a Tk-capable *venv*; if it doesn't,
    or the venv cannot import ssl, the venv is broken — delete and recreate once
    (the self-healing recovery path). Returns False only if a working venv (ssl
    at minimum) cannot be produced.
    """
    if VENV_DIR.exists() and not venv_is_valid():
        log.line("  Existing virtual environment is broken — removing it first.")
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    if not VENV_DIR.exists():
        if not create_venv(py_argv, log):
            return False

    caps = probe_capabilities(venv_python())
    needs_recreate = (not caps["ssl"]) or (not headless and not caps["tcl_tk_functional"])
    if needs_recreate:
        reason = "cannot import ssl" if not caps["ssl"] else "cannot initialize Tcl/Tk"
        log.line(f"  [!!] New venv {reason} — recreating once from scratch.")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        if not create_venv(py_argv, log):
            return False
        caps = probe_capabilities(venv_python())

    if not caps["ssl"]:
        log.line("  ERROR: the virtual environment still cannot import ssl after a "
                 "recreate. pip and Edge TTS will not work.")
        return False
    if not headless and not caps["tcl_tk_functional"]:
        # ssl works (so setup can proceed), but the GUI base lost Tk. Don't abort —
        # finish installing so the CLI works, and warn clearly.
        log.line("  [!!] The virtual environment cannot initialize Tcl/Tk, so the "
                 "app window may not open. Setup will finish; install Tk support "
                 "(macOS: brew install python-tk@3.12) and re-run to enable the GUI.")
    log.line(f"  venv ready (ssl={caps['ssl']}, tkinter={caps['tcl_tk_functional']}).")
    return True


# Import name -> pip distribution name, for packages whose import name differs.
_PIP_NAME = {
    "fitz": "pymupdf",
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "edge_tts": "edge-tts",
}
# Required (non-optional) imports to verify after install. Kokoro is intentionally
# excluded — it is optional and gated to Python <3.13.
REQUIRED_IMPORTS = ["edge_tts", "pydub", "fitz", "mutagen", "PIL", "ebooklib",
                    "bs4", "nltk"]


def validate_installed_packages(log: SetupLog) -> bool:
    """Import-test each required package; force-reinstall any that fail.

    pip exiting 0 does not guarantee a package imports (a partial wheel, an ABI
    mismatch, a clobbered install). Probe each import explicitly and try one
    ``--force-reinstall`` before giving up. Returns True if all import.
    """
    py = venv_python()
    log.line("Verifying required packages import…")
    failed: list[str] = []
    for mod in REQUIRED_IMPORTS:
        if _probe_import(py, mod):
            continue
        dist = _PIP_NAME.get(mod, mod)
        log.line(f"  [!!] '{mod}' failed to import — reinstalling {dist}…")
        _run(venv_pip() + ["install", "--force-reinstall", dist])
        if not _probe_import(py, mod):
            failed.append(mod)
    if failed:
        log.line("  WARNING: these packages still fail to import: "
                 + ", ".join(failed))
        return False
    log.line("  All required packages import cleanly.")
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
            # A fresh brew install may not be on THIS process's PATH yet (Apple
            # Silicon installs to /opt/homebrew/bin) — refresh, then re-check.
            _refresh_brew_path()
            if _ffmpeg_on_path():
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


# Seconds to watch a freshly-spawned GUI before declaring the launch a success.
# An import error / broken venv / Tk failure dies within a few hundred ms, so a
# short grace window reliably catches a crash without making a healthy launch
# wait. The launch is already detached, so this delay is never user-visible on
# the fast path (the .command/.bat has already backgrounded this process).
_LAUNCH_GRACE_SECONDS = 1.5


def _tail_text(path: Path, max_lines: int = 25) -> str:
    """Return the last ``max_lines`` lines of ``path`` (best-effort, never raises)."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-max_lines:])
    except Exception:
        return ""


def launch_gui(log: SetupLog) -> bool:
    """Spawn the launcher GUI detached so this process can exit.

    The child's stdout+stderr are redirected to
    ``resources/logs/launch_<date>.log`` so a crash during import/startup is never
    invisible. On the fast path the ``.command``/``.bat`` send *this* process's
    output to the void (and on Windows the GUI runs windowless with no console),
    so without this capture a launcher crash produces a clean ``[Process
    completed]`` with no window and nothing to diagnose. After spawning we briefly
    watch the child: if it dies immediately, the captured output is surfaced and
    we report failure instead of a false success.
    """
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

    # Capture the GUI's stdout+stderr to a dated log so a startup crash is visible.
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    launch_log_path = LOGS_DIR / f"launch_{datetime.now():%Y-%m-%d}.log"
    try:
        launch_fh = open(launch_log_path, "a", encoding="utf-8")
        launch_fh.write(f"\n===== Launch {datetime.now():%Y-%m-%d %H:%M:%S} : "
                        f"{py} {target} =====\n")
        launch_fh.flush()
    except Exception:
        # Could not open the capture file — fall back to inherited stdio rather
        # than fail the launch outright.
        launch_fh = None

    log.line(f"Launching {target.name} via {py.name} "
             f"(GUI output -> {launch_log_path.name})…")
    try:
        kwargs: dict = {"cwd": str(SCRIPTS_DIR), "env": env}
        if launch_fh is not None:
            kwargs["stdout"] = launch_fh
            kwargs["stderr"] = subprocess.STDOUT
        if IS_WINDOWS:
            kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                       | subprocess.DETACHED_PROCESS)
            kwargs["close_fds"] = True
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([str(py), str(target)], **kwargs)
    except Exception as exc:
        log.line(f"  ERROR launching GUI: {exc}")
        return False
    finally:
        # The child holds its own inherited copy of the handle; the parent's is
        # no longer needed (the survival check reads the log back by path).
        if launch_fh is not None:
            launch_fh.close()

    # Watch for an immediate crash so a broken launch is reported, not hidden.
    time.sleep(_LAUNCH_GRACE_SECONDS)
    rc = proc.poll()
    if rc is not None and rc != 0:
        log.line(f"  ERROR: the app window failed to start (exited with code {rc}).")
        tail = _tail_text(launch_log_path)
        if tail:
            log.line(f"  --- last lines of {launch_log_path.name} ---")
            for line in tail.splitlines():
                log.line("    " + line)
            log.line("  --- end ---")
        log.line(f"  Full launch log: {launch_log_path}")
        return False
    return True


# ===========================================================================
#  Orchestration (headless worker — drives the steps, reports progress)
# ===========================================================================
def run_setup(download_kokoro: bool, progress: Callable[[int, str], None],
              log: SetupLog, headless: bool = False) -> tuple[bool, str]:
    """Run the full setup. ``progress(step_index, message)`` updates the UI.

    With ``headless=True`` the install never requires a working Tk (used when no
    GUI-capable Python can be set up): the venv, dependencies, ffmpeg and the
    package-validation stage all run, but a Tk-less base is accepted instead of
    aborting. Returns ``(success, final_message)``.
    """
    steps = ["Locating Python", "Creating environment", "Installing packages",
             "Installing ffmpeg"]
    if download_kokoro:
        steps.append("Downloading Kokoro voices")
    total = len(steps)

    progress(0, "Locating a suitable Python…")
    py_argv = find_suitable_python(log, prefer_tk=not headless)
    if py_argv is None:
        py_argv = install_python(log, prefer_tk=not headless)
    if py_argv is None:
        return False, ("Python 3.12 could not be found or installed automatically.\n"
                       "Please install Python 3.12 from python.org and run setup again.")

    # Surface the chosen interpreter's capabilities up front (audit preflight).
    preflight_report(py_argv, log)

    progress(1, "Creating the virtual environment…")
    if not _create_validated_venv(py_argv, log, headless):
        return False, "Failed to create a working virtual environment (see the log)."

    progress(2, "Installing packages (largest step — please wait)…")
    if not pip_install_requirements(log):
        return False, "Failed to install Python packages (see the log)."

    # pip exiting 0 isn't proof the packages import — verify explicitly.
    validate_installed_packages(log)

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
        # Pre-warm the pipeline so Smart App Control / WDAC evaluates Kokoro's
        # unsigned native DLLs during this install dialog, not on first synthesis.
        if kokoro_is_healthy(venv_python())[0]:
            warmup_kokoro_pipeline(venv_python(), log)

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
        text="Pre-download Kokoro AI voice model now (~300 MB). If unchecked, the "
             "model auto-downloads on first synthesis.",
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
#  HuggingFace cache redirect (keep the ~300 MB Kokoro model in the project tree)
# ===========================================================================
def _configure_hf_cache() -> Path:
    """Point the HuggingFace cache at ``resources/models/huggingface/``.

    Without this, the ~300 MB Kokoro-82M model lands in the user's home
    (``~/.cache/huggingface/``). Setting ``HF_HOME`` here — before any kokoro /
    huggingface import in this process — and relying on ``launch_gui`` copying
    ``os.environ`` to the spawned GUI keeps the model inside the project folder,
    so uninstalling the app is just deleting the folder. ``HUGGINGFACE_HUB_CACHE``
    is set too for older kokoro/huggingface_hub versions that still read it.
    """
    hf_cache = RESOURCES_DIR / "models" / "huggingface"
    try:
        hf_cache.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    os.environ["HF_HOME"] = str(hf_cache)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(hf_cache / "hub"))
    return hf_cache


# ===========================================================================
#  Self-heal dialogs (small Tk windows reusing the first-run log-pane pattern)
# ===========================================================================
def show_repair_dialog(work: Callable[[], bool]) -> bool:
    """Show a small "Repairing Kokoro install…" window while ``work`` runs.

    Reuses the first-run flow's live-log pane: ``work`` runs on a worker thread
    and everything tee'd through ``LOG`` is mirrored into the Text pane. Returns
    ``work()``'s boolean result. If Tk cannot start (headless Python), ``work``
    is run directly with no window so the repair still happens.
    """
    try:
        import queue
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return work()

    ui_queue: "queue.Queue[object]" = queue.Queue()
    result = {"ok": False, "done": False}

    try:
        root = tk.Tk()
    except Exception:
        return work()
    root.title("Audiobook Creation Tool — Repairing")
    root.geometry("560x360")
    root.minsize(480, 300)
    try:
        ttk.Style().theme_use("vista" if IS_WINDOWS else "aqua")
    except Exception:
        pass

    frame = ttk.Frame(root, padding=14)
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame, text="Repairing the Kokoro AI voice install…",
        font=("Segoe UI" if IS_WINDOWS else "Helvetica", 12, "bold"),
    ).pack(anchor="w", pady=(0, 6))
    ttk.Label(
        frame,
        text="Installing the local AI voice libraries. This is a one-time repair; "
             "Edge TTS voices work regardless.",
        wraplength=520, justify="left",
    ).pack(anchor="w", pady=(0, 8))
    bar = ttk.Progressbar(frame, mode="indeterminate")
    bar.pack(fill="x", pady=(0, 10))
    bar.start(12)
    log_box = tk.Text(frame, height=12, wrap="word", state="disabled",
                      font=("Consolas" if IS_WINDOWS else "Menlo", 9))
    log_box.pack(fill="both", expand=True)

    def ui_log(msg: str) -> None:
        ui_queue.put(msg)

    LOG.set_ui_sink(ui_log)

    def append(msg: str) -> None:
        log_box.configure(state="normal")
        log_box.insert("end", msg + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")

    def worker() -> None:
        ok = False
        try:
            ok = work()
        finally:
            result["ok"] = ok
            ui_queue.put(("__done__", ok))

    threading.Thread(target=worker, daemon=True).start()

    def poll() -> None:
        try:
            while True:
                item = ui_queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__done__":
                    result["done"] = True
                    bar.stop()
                    root.after(700, root.destroy)
                else:
                    append(str(item))
        except queue.Empty:
            pass
        if not result["done"]:
            root.after(100, poll)

    root.after(100, poll)
    try:
        root.mainloop()
    finally:
        LOG.set_ui_sink(None)
    return bool(result["ok"])


def show_warning_dialog(title: str, message: str) -> None:
    """Show a non-blocking warning (Tk messagebox). Falls back to the log if Tk
    is unavailable so the message is never lost."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(title, message)
        root.destroy()
    except Exception:
        LOG.line(f"[WARNING] {title}: {message}")


def _launch_with_kokoro_healthcheck() -> int:
    """Probe Kokoro health, self-heal if needed, then launch the GUI.

    Runs on *every* launch (both the ``--launch-only`` fast path used by the
    ``.bat``/``.command`` and the ``venv_is_valid()`` path in ``main()``), so a
    partial first-run install or a manually-uninstalled ``kokoro`` is repaired
    before the user ever hits a Kokoro batch. Never blocks launch: if the repair
    fails, a clear warning is shown and the GUI still opens (Edge TTS works).
    """
    venv_py = venv_python()
    ok, reason = kokoro_is_healthy(venv_py)
    LOG.line(f"Kokoro health-check: {reason}")
    if not ok:
        LOG.line("Kokoro stack incomplete — attempting an in-venv repair…")

        def _repair_and_warmup() -> bool:
            if not ensure_kokoro_installed(venv_py, LOG.line):
                return False
            # Force Smart App Control / WDAC to evaluate the freshly-installed
            # native DLLs now (inside this dialog), not on first synthesis.
            warmup_kokoro_pipeline(venv_py, LOG.line)
            return True

        show_repair_dialog(_repair_and_warmup)
        ok2, reason2 = kokoro_is_healthy(venv_py)
        LOG.line(f"Kokoro health-check after repair: {reason2}")
        if not ok2:
            show_warning_dialog(
                "Kokoro is unavailable",
                "The local AI voices could not be installed. Edge TTS voices "
                "will still work.\n\n"
                f"Reason: {reason2}\n\n"
                "Manual fix:\n"
                f'  "{venv_py}" -m pip install '
                + " ".join(KOKORO_PKGS) + "\n\n"
                f"See log: {LOG.path}"
            )
    launched = launch_gui(LOG)
    LOG.close()
    return 0 if launched else 1


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
                        help="Default the first-run checkbox for the optional ~300 MB "
                             "Kokoro *model weights* pre-download to unchecked. The "
                             "Kokoro Python wheels are mandatory and always installed "
                             "regardless of this flag.")
    parser.add_argument("--headless", action="store_true",
                        help="Install without requiring a working Tkinter GUI "
                             "(CLI-only fallback, used when Tk cannot be set up).")
    parser.add_argument("--self-test", action="store_true",
                        help="Run detection logic only — no installs, no GUI. "
                             "For developer verification.")
    args = parser.parse_args(argv)

    if not _platform_sane():
        LOG.line(f"Unsupported platform: {sys.platform}")
        return 2

    # Keep the HuggingFace model cache inside the project tree for every path
    # (self-test, fast launch, and first-run setup all inherit it).
    _configure_hf_cache()

    if args.self_test:
        return _self_test()

    if args.launch_only:
        # Fast path from the .bat/.command. Self-heal Kokoro before launching so
        # a broken/partial install is repaired on every launch, not just first run.
        return _launch_with_kokoro_healthcheck()

    # Fast path: a valid venv already exists → health-check Kokoro, then launch.
    if venv_is_valid():
        LOG.line("Existing virtual environment detected — launching.")
        return _launch_with_kokoro_healthcheck()

    # First run. Headless mode skips the Tk dialog (no GUI-capable Python).
    if args.headless:
        return _run_headless(skip_kokoro=args.skip_kokoro_download)
    return run_with_gui(skip_kokoro_default=args.skip_kokoro_download)


def _run_headless(skip_kokoro: bool) -> int:
    """First-run setup with no Tk dialog: build venv + deps + ffmpeg + validate.

    Used when the launcher could not set up a GUI-capable Python. The Kokoro
    pre-download is skipped here (it still downloads on first Kokoro use) so this
    unattended path never triggers a surprise multi-GB download.
    """
    LOG.line("Running headless setup (no GUI dialog — Tk is unavailable).")

    def progress(step: int, message: str) -> None:
        LOG.line(f"[step {step}] {message}")

    ok, final = run_setup(download_kokoro=False, progress=progress, log=LOG,
                          headless=True)
    LOG.line(final)
    if ok:
        LOG.line("Setup finished. The graphical window needs Tk, which is not "
                 "available in this Python. To enable it: install Tk support "
                 "(macOS: brew install python-tk@3.12) and run setup again.")
    LOG.close()
    return 0 if ok else 1


def _self_test() -> int:
    """Exercise the read-only detection paths without installing anything."""
    LOG.line("[self-test] Running detection-only checks (no installs)…")
    LOG.line(f"[self-test] OS_ROOT          = {OS_ROOT}")
    LOG.line(f"[self-test] VENV_DIR         = {VENV_DIR} (exists={VENV_DIR.exists()})")
    LOG.line(f"[self-test] venv_is_valid    = {venv_is_valid()}")
    LOG.line(f"[self-test] requirements.txt = {REQUIREMENTS_FILE} "
             f"(exists={REQUIREMENTS_FILE.exists()})")
    LOG.line(f"[self-test] HF_HOME          = {os.environ.get('HF_HOME')}")
    # Exercise the Kokoro health-check path (detection only — never installs here).
    if venv_python().exists():
        k_ok, k_reason = kokoro_is_healthy(venv_python())
        LOG.line(f"[self-test] kokoro health    = {k_ok} ({k_reason})")
    else:
        LOG.line("[self-test] kokoro health    = n/a (no venv interpreter yet)")
    py = find_suitable_python(LOG)
    LOG.line(f"[self-test] suitable Python  = {py}")
    if py is not None:
        LOG.line(f"[self-test] capabilities     = {probe_capabilities(py)}")
    LOG.line(f"[self-test] ffmpeg on PATH   = {_ffmpeg_on_path()}")
    LOG.line(f"[self-test] ffmpeg in bin    = {_ffmpeg_in_bin()}")
    LOG.line(f"[self-test] ffprobe available= {_ffprobe_available()}")
    LOG.line(f"[self-test] launch target    = {_launch_target()} "
             f"(exists={_launch_target().exists()})")
    LOG.line("[self-test] OK — detection logic ran without side effects.")
    LOG.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
