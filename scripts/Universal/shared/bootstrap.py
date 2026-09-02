"""bootstrap.py — first-run setup + launcher for the Audiobook Creation Tool.

Invoked by the root ``Setup_and_Run-audiobook-creation-tool.bat`` (Windows) /
``Setup_and_Run-audiobook-creation-tool.command`` (macOS). This is a **single
cross-platform file** at ``scripts/Universal/shared/``; all platform differences
are branches inside it. It is adapted from the legacy ``tts/setup_env.py``
(Path-A install-on-first-run bootstrap) per the implementation plan.

Responsibilities, in order:

1. Platform sanity check (refuse the wrong OS).
2. **Fast path** — if a valid ``.venv`` already exists, launch the GUI and exit
   with no setup UI. (The ``.bat`` handles this even faster via ``pythonw`` so a
   normal launch never spawns a console; ``--launch-only`` routes here.)
3. **First run** — show a small Tk dialog (intro + Kokoro opt-in checkbox), then
   on a worker thread:
   - locate or install Python 3.11/3.12 (Kokoro wheels require <3.13),
   - create ``<repo_root>/.venv`` with that interpreter,
   - ``pip install`` the pinned ``scripts/requirements.txt``,
   - ensure ffmpeg (winget ``Gyan.FFmpeg`` / Homebrew, portable fallback into
     ``files/bin/``),
   - optionally pre-download the Kokoro model (~300 MB).
4. Launch the unified launcher GUI detached (``pythonw`` on Windows) and exit.

Every step is tee'd to ``files/runtime-data/logs/setup_YYYY-MM-DD.log`` so a non-technical
user can attach a log when reporting a problem.

This module deliberately depends on **stdlib only** (plus Tk, which ships with
CPython) because it runs *before* the virtual environment and its packages exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
# This file lives at <repo_root>/scripts/Universal/shared/bootstrap.py. Resolve
# the project layout from __file__ so the script is location-independent and
# never relies on the current working directory. We avoid importing shared.paths
# so bootstrap stays self-contained in the fragile pre-venv environment.
# (Keep these in sync with shared/paths.py.)
_THIS = Path(__file__).resolve()
SHARED_DIR = _THIS.parent
SCRIPTS_DIR = SHARED_DIR.parent                 # scripts/Universal — the import root
REPO_ROOT = SCRIPTS_DIR.parent.parent

FILES_DIR = REPO_ROOT / "files"
RESOURCES_DIR = FILES_DIR / "runtime-data"
LOGS_DIR = RESOURCES_DIR / "logs"
BIN_DIR = FILES_DIR / "bin"
REQUIREMENTS_FILE = REPO_ROOT / "scripts" / "requirements.txt"
VENV_DIR = REPO_ROOT / ".venv"

# The unified launcher (built in Phase 3). Until it exists, fall back to the
# existing TTS GUI so first-run setup still ends with a working window.
LAUNCHER = SCRIPTS_DIR / "launcher.py"
LAUNCHER_FALLBACK = SCRIPTS_DIR / "tts" / "epub2tts_gui.py"

# The one exception to "no sibling imports": v0.6.2 Plan 5 Phase 15 needs the
# *same* pair-proving logic in setup and at runtime, and duplicating it here is
# how the two would drift into disagreeing about which FFmpeg is in use.
# ``ffmpeg_health`` is stdlib-only and reaches into ``shared`` for nothing but
# the subprocess wrappers, so it is safe in the pre-venv environment this file
# runs in -- ``shared/__init__.py`` is a docstring and nothing else.
#
# Imported as ``shared.ffmpeg_health`` rather than by directory on purpose: a
# bare ``import ffmpeg_health`` off ``SHARED_DIR`` would create a *second*
# module object with its own state and its own caches, so setup and the app
# could hold different answers to "which FFmpeg?" while both looked correct.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from shared import ffmpeg_health  # noqa: E402

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


def _is_kokoro_compatible(ver: tuple[int, int] | None) -> bool:
    """Kokoro's PyPI wheels require >=3.10,<3.13."""
    return ver is not None and (3, 10) <= ver < (3, 13)

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
        self.line(f"Repo root: {REPO_ROOT}")

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


# ===========================================================================
#  Requirements drift — binding an environment to the pins it was built from
#
#  v0.6.1 Plan 4 Phase 12 remediation. `venv_is_valid()` below answers "can this
#  interpreter run?", which is *not* the same question as "does this environment
#  have the packages the current release needs?". Treating the first as the
#  second is what let a perfectly working pre-Plan-4 `.venv` sit there with no
#  `chatterbox-tts` and no `pillow-heif` after both were pinned: the fast path
#  saw pythonw.exe, launched, self-healed Kokoro only, and never mentioned that
#  two features were quietly missing. The only cure was deleting the venv by
#  hand, which no non-technical user would ever discover.
#
#  So an environment now carries a stamp of the exact requirements.txt it was
#  last successfully reconciled against. The comparison is one hash of one file:
#  cheap enough to do on every launch, which is what keeps the fast path fast.
#
#  The stamp lives INSIDE the venv on purpose. It is disposable local state that
#  is never tracked, and it travels with the directory — so renaming an old
#  environment back into place is correctly seen as stale rather than current.
# ===========================================================================
#: Filename of the per-environment requirements stamp, inside the venv.
REQUIREMENTS_STATE_NAME = ".requirements-state.json"

#: Exit code meaning "the user chose not to install", as distinct from "the
#: install broke".
#:
#: v0.6.1 Plan 4 Phase 12 remediation. ``run_with_gui`` used to end with
#: ``return 0 if state["ok"] else 1``, and ``state["ok"]`` is only ever set by a
#: *completed* install — so clicking Cancel returned 1, and the launcher, which
#: correctly treats any non-zero as failure, told the user "Setup did not
#: complete successfully (exit code 1)". Declining an optional install is not a
#: failure, and saying so is alarming and untrue.
#:
#: 2 is deliberately neither 0 (which would hide a real problem) nor 1 (the
#: failure code). A genuine error still exits 1.
EXIT_SETUP_CANCELLED = 2


def setup_exit_code(*, started: bool, done: bool, ok: bool) -> int:
    """Map a first-run dialog outcome to a process exit code.

    Split out of ``run_with_gui`` so the mapping is testable without a display,
    and so all four outcomes are stated in one place rather than implied by a
    conditional expression:

    * completed successfully                      -> 0
    * closed without ever pressing Begin Setup    -> :data:`EXIT_SETUP_CANCELLED`
    * ran and failed                              -> 1
    * closed part-way through an install          -> 1

    The last case is deliberately *not* cancellation: an interrupted install can
    leave a partial environment behind, so reporting it as incomplete is the
    truthful answer.
    """
    if ok:
        return 0
    if not started:
        return EXIT_SETUP_CANCELLED
    return 1


def requirements_state_path() -> Path:
    return VENV_DIR / REQUIREMENTS_STATE_NAME


def requirements_fingerprint() -> str:
    """SHA-256 of ``requirements.txt``. Empty string when there is no file.

    Hashing the file's bytes — rather than a parsed package list — means any
    change that could affect an install (a pin, a marker, an added or removed
    line) counts as drift, with no parser to disagree with pip.
    """
    try:
        return hashlib.sha256(REQUIREMENTS_FILE.read_bytes()).hexdigest()
    except OSError:
        return ""


def requirements_are_current() -> bool:
    """True when this environment was already reconciled against these pins.

    A missing, unreadable, malformed or mismatched stamp all mean the same
    thing — reconcile once — because none of them is evidence of success.
    """
    fingerprint = requirements_fingerprint()
    if not fingerprint:
        return True  # nothing to reconcile against; never loop on pip
    try:
        payload = json.loads(requirements_state_path().read_text(encoding="utf-8"))
        return payload.get("requirements_sha256") == fingerprint
    except (OSError, ValueError, AttributeError):
        return False


def record_requirements_state() -> None:
    """Stamp this environment as reconciled. **Only ever call after success.**"""
    fingerprint = requirements_fingerprint()
    if not fingerprint:
        return
    try:
        requirements_state_path().parent.mkdir(parents=True, exist_ok=True)
        requirements_state_path().write_text(
            json.dumps({
                "requirements_sha256": fingerprint,
                "requirements_file": str(REQUIREMENTS_FILE),
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass  # an unstamped environment reconciles again; that is safe, not fatal


def ensure_requirements_current(log: "SetupLog") -> tuple[bool, str]:
    """Reconcile this environment with ``requirements.txt`` if the pins changed.

    Returns ``(ok, message)``. The environment is **never** deleted or recreated:
    a changed pin costs one ``pip install -r``, not a rebuild. Weights are not
    touched — package repair and the optional model pre-downloads stay separate,
    so a new pin can never trigger a multi-gigabyte surprise download.

    On failure no stamp is written, so the next launch tries again rather than
    remembering a failure as success.
    """
    if requirements_are_current():
        return True, "Dependencies match the installed requirements."

    log.line("Dependencies have changed since this environment was set up — "
             "reconciling it with scripts/requirements.txt…")
    if not pip_install_requirements(log):
        return False, ("Some dependencies could not be installed. The application "
                       "will still open, but features needing them may be "
                       "unavailable.")
    if not validate_installed_packages(log):
        return False, ("Some dependencies installed but could not be imported. The "
                       "application will still open, but features needing them may "
                       "be unavailable.")
    record_requirements_state()
    log.line("  Dependencies reconciled; this environment is now up to date.")
    return True, "Dependencies reconciled."


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

# Every Kokoro subprocess this module launches opens with these lines. Building a
# KPipeline is what first initializes eSpeak NG in native code, and on an
# installation whose paths are too long for eSpeak's fixed data-path buffer that
# initialization exits the process outright (see shared/espeak_data.py). Setup and
# runtime therefore apply the *same* contract in the same place — after the kokoro
# import, before the pipeline is built — rather than one hack each.
KOKORO_SUBPROCESS_PREAMBLE = (
    "import sys\n"
    f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
    "from shared import espeak_data\n"
)


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
        KOKORO_SUBPROCESS_PREAMBLE +
        "try:\n"
        "    from kokoro import KPipeline\n"
        "    espeak_data.configure()\n"
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
#  Chatterbox self-heal (probe + in-venv repair install)
# ===========================================================================
# The pinned Chatterbox stack — the *wheels*, mandatory for the engine to import,
# distinct from the ~3.86 GiB model weights (gated by the first-run checkbox).
# These mirror requirements.txt exactly. torch/transformers/numpy are pulled in
# transitively at the versions chatterbox-tts pins.
#
# setuptools is in this list on purpose: `resemble-perth`, which chatterbox loads
# to watermark its output, imports `pkg_resources`, and setuptools 82 removed it.
# Repairing the engine without stepping setuptools back would leave a package that
# imports but cannot build a model. See the note in requirements.txt.
CHATTERBOX_PKGS = ["chatterbox-tts==0.1.7", "setuptools==80.9.0"]

# The exact symbol the published 0.1.7 wheel ships. The package root exports only
# ChatterboxTTS / ChatterboxVC / ChatterboxMultilingualTTS, so the import shown in
# the upstream docs (`from chatterbox import ChatterboxTurboTTS`) does not work.
_CHATTERBOX_PROBE = (
    "import importlib.util as u, sys\n"
    "mods = ['chatterbox', 'torch', 'torchaudio', 'librosa']\n"
    "missing = [m for m in mods if u.find_spec(m) is None]\n"
    "if missing:\n"
    "    print('MISSING:' + ','.join(missing))\n"
    "    sys.exit(1)\n"
    "try:\n"
    "    import chatterbox.tts_turbo as turbo\n"
    "except Exception as exc:\n"
    "    print('BROKEN:chatterbox.tts_turbo %r' % (exc,))\n"
    "    sys.exit(1)\n"
    "if not hasattr(turbo, 'ChatterboxTurboTTS'):\n"
    "    print('BROKEN:ChatterboxTurboTTS is not exported by this release')\n"
    "    sys.exit(1)\n"
    "print('OK')\n"
)


def chatterbox_is_healthy(venv_py: Path) -> tuple[bool, str]:
    """Probe the venv for the Chatterbox engine. Returns ``(ok, reason)``.

    Unlike ``kokoro_is_healthy`` this genuinely imports ``chatterbox.tts_turbo``
    and checks the class, because a resolvable-but-unusable install is the exact
    failure mode this engine has (see the setuptools note above). That costs a few
    seconds and pulls in torch, so it is deliberately **not** on the every-launch
    fast path — it runs from setup and repair only. No weights are downloaded and
    no model is constructed.
    """
    try:
        r = subprocess.run(
            [str(venv_py), "-c", _CHATTERBOX_PROBE],
            capture_output=True, text=True, timeout=180, **_hidden(),
        )
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out == "OK":
            return True, "ok"
        return False, out or (r.stderr or "").strip() or "unknown"
    except Exception as exc:
        return False, f"probe failed: {exc!r}"


def ensure_chatterbox_installed(venv_py: Path, log: Callable[[str], None]) -> bool:
    """Install the pinned Chatterbox stack into the existing venv.

    Same self-heal shape as ``ensure_kokoro_installed``: into the venv that already
    exists, never --user, never system site-packages.
    """
    log(f"Installing Chatterbox stack into venv: {' '.join(CHATTERBOX_PKGS)}")
    try:
        r = subprocess.run(
            [str(venv_py), "-m", "pip", "install", "--no-input", *CHATTERBOX_PKGS],
            capture_output=True, text=True, timeout=1800, **_hidden(),
        )
        if r.stdout:
            log(r.stdout.strip())
        if r.returncode != 0:
            if r.stderr:
                log(r.stderr.strip())
            return False
        ok, reason = chatterbox_is_healthy(venv_py)
        log(f"Post-install health-check: {reason}")
        return ok
    except Exception as exc:
        log(f"ensure_chatterbox_installed failed: {exc!r}")
        return False


def warmup_chatterbox(venv_py: Path, log: Callable[[str], None]) -> None:
    """One-shot CPU model build to pre-warm Chatterbox at install time.

    Same rationale as ``warmup_kokoro_pipeline``: force Windows Smart App Control /
    WDAC to evaluate the unsigned native DLLs inside the install dialog rather than
    on the user's first synthesis. Only called after the weights have been
    pre-downloaded, so this loads from the local cache. Best-effort: never raises.
    """
    log("Initializing the Chatterbox voice engine (first-run only)…")
    hf_cache = RESOURCES_DIR / "models" / "huggingface"
    env = os.environ.copy()
    env["HF_HOME"] = env.get("HF_HOME") or str(hf_cache)
    env.setdefault("HUGGINGFACE_HUB_CACHE", str(hf_cache / "hub"))
    script = (
        "import sys\n"
        "try:\n"
        "    from chatterbox.tts_turbo import ChatterboxTurboTTS\n"
        "    ChatterboxTurboTTS.from_pretrained(\"cpu\")\n"
        "    print('Chatterbox engine warmup complete.')\n"
        "except OSError as e:\n"
        "    print('Chatterbox warmup blocked (will load on first synthesis): %r' % (e,))\n"
        "except Exception as e:\n"
        "    print('Chatterbox warmup problem (non-fatal): %r' % (e,))\n"
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
        log(f"  Chatterbox warmup could not run: {exc!r}")


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
    # "found", not "ready": this report runs *before* ``ensure_ffmpeg`` proves
    # anything, and calling a located binary ready is the exact overstatement
    # Phase 15 removed. The verified line is written by ``ensure_ffmpeg``.
    pair = ffmpeg_health.pair_in(BIN_DIR) or next(
        iter(ffmpeg_health.discover_pairs()), None)
    log.line(f"  {mark(pair is not None)} ffmpeg + ffprobe found "
             f"({pair.directory if pair else 'nowhere yet'})")
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
    if VENV_DIR.exists():
        # A venv built on >=3.13 can never install Kokoro. If the chosen base
        # is Kokoro-compatible (<3.13), rebuild on it rather than reusing the
        # incompatible venv forever.
        venv_ver = _interp_version_argv([str(venv_python())])
        base_ver = _interp_version_argv(py_argv)
        if (venv_ver is not None and not _is_kokoro_compatible(venv_ver)
                and _is_kokoro_compatible(base_ver)):
            log.line(f"  Existing venv is Python {venv_ver[0]}.{venv_ver[1]} "
                     f"(no Kokoro support) but Python {base_ver[0]}.{base_ver[1]} "
                     "is available — rebuilding the venv on it.")
            shutil.rmtree(VENV_DIR, ignore_errors=True)

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
    "edge_tts": "edge-tts",
    "chatterbox": "chatterbox-tts",
}
# Required (non-optional) imports to verify after install. Kokoro is intentionally
# excluded — it is optional and gated to Python <3.13.
REQUIRED_IMPORTS = ["edge_tts", "pydub", "fitz", "mutagen", "PIL", "nltk",
                    "chatterbox"]

# Imports that requirements.txt gates to Python <3.13. On a newer interpreter the
# wheel is legitimately absent, so probing it would report a false failure and
# trigger a reinstall that cannot succeed. Skip them there instead.
_GATED_BELOW_313 = {"chatterbox"}


def validate_installed_packages(log: SetupLog) -> bool:
    """Import-test each required package; force-reinstall any that fail.

    pip exiting 0 does not guarantee a package imports (a partial wheel, an ABI
    mismatch, a clobbered install). Probe each import explicitly and try one
    ``--force-reinstall`` before giving up. Returns True if all import.
    """
    py = venv_python()
    log.line("Verifying required packages import…")
    venv_ver = _interp_version_argv([str(py)])
    failed: list[str] = []
    for mod in REQUIRED_IMPORTS:
        if mod in _GATED_BELOW_313 and not _is_kokoro_compatible(venv_ver):
            log.line(f"  '{mod}' is gated to Python <3.13 — skipping on this venv.")
            continue
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
    """Establish a **usable** ffmpeg + ffprobe pair. True only if one runs.

    v0.6.2 Plan 5 Phase 15 rewrote this. It used to return ``True`` the moment
    ``shutil.which("ffmpeg")`` answered — it never looked at ffprobe on that
    path and never executed anything — so a machine whose first PATH entry was
    an installation Windows refuses to run was declared ready, and the failure
    surfaced in front of the user during a real conversion instead.

    The order now is: try what is already here, and only install when nothing
    here works. That keeps a working machine untouched and still repairs a
    broken one. Proving the pair here is deliberately the same idea as the
    Kokoro DLL pre-warm below — make Smart App Control judge the binary inside
    setup, where a notification is explainable, rather than mid-job.
    """
    pair = ffmpeg_health.ensure_ready(log)
    if pair is not None:
        log.line(f"FFmpeg verified: {pair.directory}")
        log.line(f"  {pair.version_text}")
        return True

    log.line("No usable ffmpeg/ffprobe pair found — installing one.")
    if not _install_ffmpeg(log):
        return False

    # A fresh install is not on *this* process's PATH, and its package directory
    # is not where it was a moment ago, so discovery has to run again.
    pair = ffmpeg_health.establish(log)
    if pair is None:
        log.line("  ERROR: ffmpeg was installed but still could not be run.")
        return False
    log.line(f"FFmpeg verified after install: {pair.directory}")
    return True


def _install_ffmpeg(log: SetupLog) -> bool:
    """Obtain ffmpeg through the platform's normal package route."""
    if IS_WINDOWS:
        if shutil.which("winget"):
            log.line("Installing ffmpeg via winget (Gyan.FFmpeg)…")
            r = _run(["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                      "--silent", "--accept-source-agreements",
                      "--accept-package-agreements"])
            if r.returncode == 0:
                # Deliberately **not** gated on ``_ffmpeg_on_path()`` any more.
                # winget updates the *user's* PATH, not the environment of a
                # process already running, so that check failed on exactly the
                # installs that had just succeeded — and sent setup off to
                # download a second, worse copy. ``establish`` looks inside the
                # WinGet package directory itself, so a stale PATH costs
                # nothing.
                log.line("  ffmpeg installed via winget.")
                return True
            log.line(f"  winget install failed (exit {r.returncode}) — "
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
    """Download a portable ffmpeg build into files/bin (Windows last resort).

    **Kept, but demoted, and worth understanding.** This pulls BtbN's
    ``master-latest`` build, whose bytes change on every upstream commit. Under
    reputation-based enforcement — Smart App Control being the case Phase 15 hit
    — a binary whose hash is new every time never accumulates the cloud
    reputation that lets an unsigned executable run, so this route is
    *structurally* more likely to be refused than the stable WinGet package
    above. That is why it now runs only when winget is unavailable or failed,
    and why whatever it produces is still put through the same proof as every
    other candidate rather than being trusted because it is ours.

    Replacing it with a pinned, reputable, redistributable Windows build is
    release work; it belongs with the signing/distribution question in Plan 9.
    """
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
        KOKORO_SUBPROCESS_PREAMBLE +
        "from kokoro import KPipeline\n"
        "espeak_data.configure()\n"
        "KPipeline(lang_code='a')\n"
        "KPipeline(lang_code='b')\n"
        "print('Kokoro model download complete.')\n"
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


CHATTERBOX_MODEL_REPO = "ResembleAI/chatterbox-turbo"


def predownload_chatterbox(log: SetupLog) -> None:
    """Pre-download the Chatterbox Turbo weights (~3.9 GB). Best-effort; never fatal.

    Fetches exactly the file set ``ChatterboxTurboTTS.from_pretrained`` asks for,
    into the *same* in-tree HuggingFace cache Kokoro uses — there is no second
    cache and nothing is bundled with the app.
    """
    py = venv_python()
    check = _run([str(py), "-c",
                  "import importlib.util as u, sys; "
                  "sys.exit(0 if u.find_spec('chatterbox') else 1)"])
    if check.returncode != 0:
        log.line("Chatterbox package not installed (Python may be 3.13+) — "
                 "skipping model pre-download.")
        return
    log.line("Pre-downloading Chatterbox Turbo model weights "
             "(~3.9 GB, one-time)…")
    hf_cache = RESOURCES_DIR / "models" / "huggingface"
    env = os.environ.copy()
    env["HF_HOME"] = env.get("HF_HOME") or str(hf_cache)
    env.setdefault("HUGGINGFACE_HUB_CACHE", str(hf_cache / "hub"))
    script = (
        "from huggingface_hub import snapshot_download\n"
        f"snapshot_download(repo_id={CHATTERBOX_MODEL_REPO!r},\n"
        "    allow_patterns=['*.safetensors', '*.json', '*.txt', '*.pt', '*.model'])\n"
        "print('Chatterbox model download complete.')\n"
    )
    proc = subprocess.Popen([str(py), "-c", script],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env=env, **_hidden())
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if line:
            log.line("  " + line)
    if proc.wait() == 0:
        log.line("  Chatterbox voice engine ready.")
    else:
        log.line("  Chatterbox pre-download had a problem; the model will "
                 "download on first use instead.")


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
    ``files/runtime-data/logs/launch_<date>.log`` so a crash during import/startup is never
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
              log: SetupLog, headless: bool = False,
              download_chatterbox: bool = False) -> tuple[bool, str]:
    """Run the full setup. ``progress(step_index, message)`` updates the UI.

    With ``headless=True`` the install never requires a working Tk (used when no
    GUI-capable Python can be set up): the venv, dependencies, ffmpeg and the
    package-validation stage all run, but a Tk-less base is accepted instead of
    aborting. Returns ``(success, final_message)``.

    ``download_chatterbox`` defaults to False: those weights are ~3.9 GB, so the
    voice-cloning model is opt-in rather than part of a normal first run.
    """
    steps = ["Locating Python", "Creating environment", "Installing packages",
             "Installing ffmpeg"]
    kokoro_step = chatterbox_step = None
    if download_kokoro:
        kokoro_step = len(steps)
        steps.append("Downloading Kokoro voices")
    if download_chatterbox:
        chatterbox_step = len(steps)
        steps.append("Downloading Chatterbox voice model")
    total = len(steps)

    progress(0, "Locating a suitable Python…")
    py_argv = find_suitable_python(log, prefer_tk=not headless)
    if py_argv is not None:
        # A >=3.13 interpreter can build a venv but loses Kokoro (its wheels
        # require <3.13). Before accepting it, try to install 3.12; keep the
        # newer interpreter only if 3.12 truly cannot be had.
        sel_ver = _interp_version_argv(py_argv)
        if sel_ver is not None and not _is_kokoro_compatible(sel_ver):
            log.line(f"Python {sel_ver[0]}.{sel_ver[1]} is too new for Kokoro "
                     "(needs <3.13) — attempting to install Python 3.12…")
            fixed = install_python(log, prefer_tk=not headless)
            fixed_ver = _interp_version_argv(fixed) if fixed is not None else None
            if _is_kokoro_compatible(fixed_ver):
                py_argv = fixed
            else:
                log.line(f"  Python 3.12 could not be installed — continuing on "
                         f"{sel_ver[0]}.{sel_ver[1]} — Edge TTS works, Kokoro "
                         "voices disabled.")
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

    # Bind this environment to the pins it was just built from, so a later
    # release that changes requirements.txt is detected instead of ignored.
    record_requirements_state()

    progress(3, "Setting up ffmpeg…")
    if not ensure_ffmpeg(log):
        # Non-fatal: Edge TTS still works without ffmpeg for some paths, but most
        # tools need it. Surface clearly rather than crash.
        return False, ("ffmpeg could not be installed automatically.\n"
                       "Install it (https://ffmpeg.org/download.html) and re-run, "
                       "or see the log for the manual steps.")

    if download_kokoro:
        progress(kokoro_step, "Downloading Kokoro AI voices (~300 MB)…")
        predownload_kokoro(log)
        # Pre-warm the pipeline so Smart App Control / WDAC evaluates Kokoro's
        # unsigned native DLLs during this install dialog, not on first synthesis.
        if kokoro_is_healthy(venv_python())[0]:
            warmup_kokoro_pipeline(venv_python(), log.line)

    if download_chatterbox:
        progress(chatterbox_step, "Downloading the Chatterbox voice model (~3.9 GB)…")
        predownload_chatterbox(log)
        # Same first-load pre-warm rationale as Kokoro's, above.
        if chatterbox_is_healthy(venv_python())[0]:
            warmup_chatterbox(venv_python(), log.line)

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
    root.geometry("720x600")
    root.minsize(640, 560)
    try:
        ttk.Style().theme_use("vista" if IS_WINDOWS else "aqua")
    except Exception:
        pass

    container = ttk.Frame(root, padding=18)
    container.pack(fill="both", expand=True)

    # ---- Responsive wrapping ---------------------------------------------
    #
    # v0.6.1 Plan 4 Phase 12 remediation. The first-run dialog clipped its own
    # explanatory text at 1920x1080 / 100% scaling: the option descriptions were
    # long single-line ``ttk.Checkbutton`` labels, and **ttk.Checkbutton has no
    # wraplength option** (only ttk.Label and the classic tk widgets do), so
    # there was nothing to make them fold. Widening the window would only move
    # the cut, so instead every long string lives in a real wrapped Label whose
    # wraplength tracks the actual window width. The checkbuttons keep only a
    # short actionable phrase, which cannot outgrow the frame.
    _wrapped: list = []

    def _wrap_to_width(event=None) -> None:
        width = container.winfo_width()
        if width <= 1:  # not yet mapped
            return
        target = max(320, width - 48)
        for label in _wrapped:
            if label.cget("wraplength") != target:
                label.configure(wraplength=target)

    container.bind("<Configure>", _wrap_to_width)

    # Chatterbox is unchecked by default: its weights are ~3.9 GB, more than ten
    # times Kokoro's, and voice cloning is an optional extra rather than part of a
    # normal first run. Kokoro's default is unchanged.
    state = {"download_kokoro": tk.BooleanVar(value=not skip_kokoro_default),
             "download_chatterbox": tk.BooleanVar(value=False),
             "started": False, "done": False, "ok": False}

    # ---- Intro view -------------------------------------------------------
    intro = ttk.Frame(container)
    ttk.Label(intro, text="Welcome to the Audiobook Creation Tool",
              font=("Segoe UI" if IS_WINDOWS else "Helvetica", 16, "bold")
              ).pack(anchor="w", pady=(0, 8))
    _intro_body = ttk.Label(
        intro,
        text=("This one-time setup will install everything the app needs:\n"
              "  •  a private Python environment (kept inside this folder)\n"
              "  •  the audio libraries and ffmpeg\n"
              "  •  optionally, the local Kokoro AI voices (~300 MB)\n\n"
              "Nothing is installed system-wide except Python and ffmpeg if they "
              "are missing. After this finishes, the app opens automatically and "
              "future launches are instant."),
        justify="left",
    )
    _intro_body.pack(anchor="w", fill="x")
    _wrapped.append(_intro_body)

    # Each option is a SHORT checkbutton label plus a wrapped description below
    # it. The description carries the same words the single-line label used to,
    # so nothing was cut — only the widget that renders it changed.
    ttk.Checkbutton(
        intro,
        text="Pre-download the Kokoro AI voice model now (~300 MB)",
        variable=state["download_kokoro"],
    ).pack(anchor="w", pady=(16, 0))
    _kokoro_note = ttk.Label(
        intro,
        text="If unchecked, the model auto-downloads on first synthesis.",
        justify="left",
    )
    _kokoro_note.pack(anchor="w", padx=(22, 0), pady=(0, 8), fill="x")
    _wrapped.append(_kokoro_note)

    ttk.Checkbutton(
        intro,
        text="Also download the Chatterbox voice-cloning model now (~3.9 GB)",
        variable=state["download_chatterbox"],
    ).pack(anchor="w", pady=(4, 0))
    _chatterbox_note = ttk.Label(
        intro,
        text="Optional — leave this unchecked unless you plan to use the cloned "
             "voices; the model downloads on first use instead.",
        justify="left",
    )
    _chatterbox_note.pack(anchor="w", padx=(22, 0), pady=(0, 8), fill="x")
    _wrapped.append(_chatterbox_note)

    btn_row = ttk.Frame(intro)
    btn_row.pack(side="bottom", anchor="e", pady=(12, 0), fill="x")
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
        ok, final = run_setup(
            state["download_kokoro"].get(), on_progress, LOG,
            download_chatterbox=state["download_chatterbox"].get(),
        )
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
        # Read the checkboxes at click time (the user may have toggled them). The
        # bar's maximum must match the step count run_setup will report.
        bar.configure(maximum=4 + state["download_kokoro"].get()
                      + state["download_chatterbox"].get())
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
    return setup_exit_code(started=state["started"], done=state["done"],
                           ok=state["ok"])


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
    """Point the HuggingFace cache at ``files/runtime-data/models/huggingface/``.

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
def show_repair_dialog(
    work: Callable[[], bool],
    *,
    title: str = "Repairing the Kokoro AI voice install…",
    detail: str = ("Installing the local AI voice libraries. This is a one-time "
                   "repair; Edge TTS voices work regardless."),
) -> bool:
    """Show a small progress window while ``work`` runs.

    Reuses the first-run flow's live-log pane: ``work`` runs on a worker thread
    and everything tee'd through ``LOG`` is mirrored into the Text pane. Returns
    ``work()``'s boolean result. If Tk cannot start (headless Python), ``work``
    is run directly with no window so the repair still happens.

    ``title``/``detail`` default to the original Kokoro wording, so the existing
    caller is unchanged; the Phase 12 requirements reconciliation passes its own.
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
        frame, text=title,
        font=("Segoe UI" if IS_WINDOWS else "Helvetica", 12, "bold"),
    ).pack(anchor="w", pady=(0, 6))
    ttk.Label(
        frame, text=detail,
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


def ensure_ffmpeg_ready_for_launch() -> bool:
    """Confirm the audio tools before the GUI is presented as ready.

    **The Phase 15 gap.** The fast path reconciled requirements and self-healed
    Kokoro, and never looked at ffmpeg at all — so a machine whose ffmpeg had
    become unusable launched cheerfully and failed inside the first conversion.

    What this costs on a healthy machine is two ``-version`` calls of the pair
    already proven, a few tens of milliseconds, and it touches **no other
    candidate**: sweeping PATH here would be how a launch provokes a security
    notification by poking a blocked stranger. Repair — which does look wider —
    happens only once the pinned pair is gone or has stopped running.

    Never blocks launch. A machine with no working ffmpeg can still use Edge
    TTS, and the tools that do need it now say so honestly instead of implying
    everything is fine.
    """
    pair = ffmpeg_health.ensure_ready(LOG)
    if pair is not None:
        LOG.line(f"FFmpeg health-check: verified {pair.directory}")
        return True

    LOG.line("FFmpeg health-check: no usable ffmpeg/ffprobe pair on this computer.")
    show_warning_dialog("The audio tools are unavailable",
                        ffmpeg_health.describe_failure()
                        + f"\n\nSee log: {LOG.path}")
    return False


def _launch_with_kokoro_healthcheck() -> int:
    """Reconcile dependencies, probe Kokoro health, self-heal, then launch the GUI.

    Runs on *every* launch (both the ``--launch-only`` fast path used by the
    ``.bat``/``.command`` and the ``venv_is_valid()`` path in ``main()``), so a
    partial first-run install or a manually-uninstalled ``kokoro`` is repaired
    before the user ever hits a Kokoro batch. Never blocks launch: if the repair
    fails, a clear warning is shown and the GUI still opens (Edge TTS works).

    The requirements reconciliation added in the v0.6.1 Plan 4 Phase 12
    remediation runs **first**, because a stale environment is exactly the case
    where Kokoro's own probe would otherwise be the only thing checked. When the
    pins are unchanged it is one file hash and costs nothing.
    """
    venv_py = venv_python()

    if not requirements_are_current():
        LOG.line("Requirements changed since this environment was set up.")
        outcome: dict = {}

        def _reconcile() -> bool:
            ok_req, message = ensure_requirements_current(LOG)
            outcome["message"] = message
            return ok_req

        show_repair_dialog(
            _reconcile,
            title="Updating the app's components…",
            detail="This version needs components the current installation does "
                   "not have yet. This is a one-time update; nothing is being "
                   "deleted and your settings are untouched.",
        )
        if not requirements_are_current():
            show_warning_dialog(
                "Some components could not be updated",
                outcome.get("message", "Some dependencies could not be installed.")
                + f"\n\nSee log: {LOG.path}",
            )

    ensure_ffmpeg_ready_for_launch()

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
    LOG.line(f"[self-test] REPO_ROOT        = {REPO_ROOT}")
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
    # Detection only: --self-test performs no installs and executes nothing, so
    # it reports the *pinned* pair rather than proving a new one.
    _pinned = ffmpeg_health.pinned_pair()
    LOG.line(f"[self-test] ffmpeg verified  = {_pinned.directory if _pinned else None}")
    LOG.line(f"[self-test] ffmpeg candidates= "
             f"{[str(p.directory) for p in ffmpeg_health.discover_pairs()]}")
    LOG.line(f"[self-test] launch target    = {_launch_target()} "
             f"(exists={_launch_target().exists()})")
    LOG.line("[self-test] OK — detection logic ran without side effects.")
    LOG.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
