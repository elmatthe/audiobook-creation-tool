"""long_paths.py -- Windows long-path support and the app's folder: read it, decide, change it only with consent, prove it.

Windows refuses a file path longer than 259 characters unless "Enable Win32 long paths" is switched on, and refuses a
native library (.dll/.pyd) past 259 characters whatever that setting says. The app's Python environments keep files deep
below the app's folder, so how long the *folder's own path* may be depends on that setting:

    longest folder, setting off  = 259 - the deepest file the installation writes
    longest folder, setting on   = 259 - the deepest native library it must load

This module is the one place that

* reads the setting, read only (:func:`read_setting`);
* compares the app's real folder with both limits (:func:`assess`) and says whether switching the setting on would
  help -- a folder too long even then is never offered a change that cannot work;
* switches the setting on **only** after the person chose that in the setup window, through Windows' own consent prompt
  (:func:`enable`). The elevated process is Windows' own ``reg.exe``, found through Windows' system directory (never
  PATH, the current folder or an environment variable) and started with one constant command line
  (:data:`ELEVATED_ARGUMENTS`). Nothing of this app runs elevated, nothing from the app's folder, a file name or the
  person's input reaches that command line, and the setup process itself stays unelevated;
* proves that long paths really work afterwards, in a **fresh process** (:func:`verify_runtime`): Windows caches the
  setting per process, so a process that started before the change cannot see it, and a registry value of 1 is not
  proof of anything. The probe asks Windows whether the new process has long paths, writes and reads a file as deep as
  the installation's deepest, installs a generated package that deep with pip, and loads a native library as deep as
  the installation's deepest one. When Windows is not applying the setting yet, the answer is "restart Windows".

Standard library only (it is imported by ``shared.bootstrap`` before any environment exists). It never changes any other
setting, never retries a refused change, and never deletes anything outside its own probe folder.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

REGISTRY_KEY = r"SYSTEM\CurrentControlSet\Control\FileSystem"
REGISTRY_VALUE = "LongPathsEnabled"
#: Everything the elevated helper is ever given: Windows' own reg.exe sets this one value to 1. Constants only.
ELEVATED_ARGUMENTS = ("add", "HKLM\\" + REGISTRY_KEY, "/v", REGISTRY_VALUE, "/t", "REG_DWORD", "/d", "1", "/f")
#: The longest path Windows accepts without long-path support, and for a native library with or without it.
WINDOWS_MAX_PATH = 259
#: The OmniVoice engine's depths below the app's folder (``tts.omnivoice_runtime.DEEPEST_NATIVE_LIBRARY_CHARS`` and
#: ``DEEPEST_FILE_CHARS``; this file may not import anything under ``tts``, so a test holds the two pairs equal).
OMNIVOICE_DEEPEST_NATIVE_LIBRARY_CHARS = 140
OMNIVOICE_DEEPEST_FILE_CHARS = 176
ERROR_CANCELLED = 1223  # the person closed or declined Windows' consent prompt

ENABLED = "enabled"
ALREADY_ENABLED = "already-enabled"
CANCELLED = "cancelled"
DENIED = "denied"
FAILED = "failed"
NOT_CHANGED = "not-changed"
UNSUPPORTED = "unsupported"

#: The probe's own folder is ``files/runtime-data/long-path-check-<id>``: made for one check and removed after it.
PROBE_PREFIX = "long-path-check-"
README_SECTION = "Important: Windows Installation Path Length"
SHORT_FOLDER_EXAMPLE = "C:\\AudiobookTool"


# --------------------------------------------------------------------------- #
# Reading the setting (read only)
# --------------------------------------------------------------------------- #
def _winreg():
    import winreg

    return winreg


def read_setting() -> Optional[bool]:
    """Whether "Enable Win32 long paths" is on: ``True``, ``False`` (0, or the value is not there -- Windows' default),
    or ``None`` when this is not Windows or the key could not be read. Opens the key for reading only."""
    if sys.platform != "win32":
        return None
    try:
        winreg = _winreg()
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY, 0, winreg.KEY_READ) as key:
            try:
                value, kind = winreg.QueryValueEx(key, REGISTRY_VALUE)
            except FileNotFoundError:
                return False
            return kind == winreg.REG_DWORD and value == 1
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# The app's folder against both limits
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Limits:
    """The longest path the app's folder may have: as Windows comes (``default``) and with long paths on."""

    default: int
    long_paths: int


def limits_from(deepest_native_library: int, deepest_file: int) -> Limits:
    return Limits(default=WINDOWS_MAX_PATH - deepest_file, long_paths=WINDOWS_MAX_PATH - deepest_native_library)


OMNIVOICE_LIMITS = limits_from(OMNIVOICE_DEEPEST_NATIVE_LIBRARY_CHARS, OMNIVOICE_DEEPEST_FILE_CHARS)


@dataclass(frozen=True)
class Assessment:
    """The app's folder (``length`` characters) against the limits of the app and of the OmniVoice engine."""

    folder: str
    length: int
    enabled: Optional[bool]
    app: Limits
    omnivoice: Limits = OMNIVOICE_LIMITS

    def _fits(self, limits: Limits) -> bool:
        return self.length <= (limits.long_paths if self.enabled else limits.default)

    def _offer(self, limits: Limits) -> bool:
        # Only where the setting is known to be off and switching it on would be enough. A folder too long even then
        # gets the "move it" answer alone; a setting that cannot be read is never changed (it could not be read back).
        return self.enabled is False and limits.default < self.length <= limits.long_paths

    @property
    def app_fits(self) -> bool:
        return self._fits(self.app)

    @property
    def omnivoice_fits(self) -> bool:
        return self._fits(self.omnivoice)

    @property
    def app_offer(self) -> bool:
        """The app itself cannot be installed here as Windows is set up, and could with long paths on."""
        return self._offer(self.app)

    @property
    def omnivoice_offer(self) -> bool:
        """The app fits as Windows is set up; only OmniVoice does not, and would with long paths on."""
        return self.length <= self.app.default and self._offer(self.omnivoice)

    @property
    def needs_long_paths(self) -> bool:
        """This folder is deeper than the app allows without long paths: the installation depends on them."""
        return self.length > self.app.default


def assess(root, app: Limits, *, enabled: object = "read", omnivoice: Limits = OMNIVOICE_LIMITS) -> Assessment:
    folder = str(root)
    return Assessment(folder=folder, length=len(folder), enabled=read_setting() if enabled == "read" else enabled,
                      app=app, omnivoice=omnivoice)


# --------------------------------------------------------------------------- #
# Switching it on, with consent, through Windows' own prompt
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EnableResult:
    state: str
    message: str
    code: Optional[int] = None


def system_reg_exe() -> Optional[Path]:
    """``reg.exe`` in the system directory Windows itself reports, or ``None``. Never PATH or an environment variable."""
    if sys.platform != "win32":
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.WinDLL("kernel32", use_last_error=True).GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < length < len(buffer):
        return None
    candidate = Path(buffer.value) / "reg.exe"
    return candidate if candidate.is_file() else None


def elevated_parameters() -> str:
    """The one command line the elevated ``reg.exe`` receives. Takes nothing, so nothing can be passed into it."""
    return subprocess.list2cmdline(ELEVATED_ARGUMENTS)


def _run_elevated(executable: str, parameters: str, *, window: int = 0, timeout_s: float = 300.0) -> tuple[str, int]:
    """Start *executable* through Windows' consent prompt (the ``runas`` verb) and wait for it.

    Returns ``("ran", exit code)``, ``("cancelled", 1223)`` when the person declined or closed the prompt,
    ``("refused", error)`` when Windows would not start it (no administrator available, elevation blocked by policy),
    or ``("timeout", 0)``. The calling process is not elevated and stays that way."""
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040 | 0x00000100 | 0x00000400  # keep the process handle; wait for the start; no error boxes
    info.hwnd = window or None
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = parameters
    info.lpDirectory = str(Path(executable).parent)
    info.nShow = 0  # hidden: reg.exe is a console program and shows nothing worth a window
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        return ("cancelled" if error == ERROR_CANCELLED else "refused"), error
    if not info.hProcess:
        return "refused", 0
    try:
        if kernel32.WaitForSingleObject(info.hProcess, int(timeout_s * 1000)) != 0:
            return "timeout", 0
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            return "refused", ctypes.get_last_error()
        return "ran", int(code.value)
    finally:
        kernel32.CloseHandle(info.hProcess)


NOTHING_ELSE = "No other setting was touched."
MANAGED_NOTE = ("On a work or school computer this setting can be managed by the organisation; ask its administrator, "
                "or move the app to a shorter folder instead.")


def enable(*, window: int = 0, read: Callable[[], Optional[bool]] = None, run_elevated: Callable = None,
           reg_exe: Callable[[], Optional[Path]] = None) -> EnableResult:
    """Switch "Enable Win32 long paths" on. Called only after the person chose it; Windows then asks for approval.

    The value is read first (already on: nothing is run) and read back afterwards: only a value that reads 1 again is
    reported as changed. Every refusal -- the prompt declined, no administrator, a managed computer, the registry tool
    failing, the value put back -- comes back as a result with a sentence for the person; nothing is retried and no
    other setting is touched. That the setting *works* is a separate question: :func:`verify_runtime`."""
    read = read or read_setting
    run_elevated = run_elevated or _run_elevated
    reg_exe = reg_exe or system_reg_exe
    if sys.platform != "win32":
        return EnableResult(UNSUPPORTED, "This setting exists on Windows only.")
    before = read()
    if before is True:
        return EnableResult(ALREADY_ENABLED, "Windows long paths are already switched on. Nothing was changed.")
    if before is None:
        return EnableResult(FAILED, "The Windows long-path setting could not be read on this computer, so it was not "
                                    "changed. " + MANAGED_NOTE)
    executable = reg_exe()
    if executable is None:
        return EnableResult(FAILED, "Windows' own registry tool (reg.exe) was not found in the Windows system folder, "
                                    "so the setting was not changed. " + NOTHING_ELSE)
    try:
        outcome, code = run_elevated(str(executable), elevated_parameters(), window=window)
    except OSError as exc:
        return EnableResult(FAILED, f"Windows could not start the change ({exc}). Nothing was changed.")
    if outcome == "cancelled":
        return EnableResult(CANCELLED, "The Windows permission prompt was declined or closed, so nothing was changed.",
                            code)
    if outcome == "refused":
        return EnableResult(DENIED, f"Windows did not allow the change (error {code}): it needs an administrator's "
                                    "approval. Nothing was changed. " + MANAGED_NOTE, code)
    if outcome == "timeout":
        return EnableResult(FAILED, "Windows' registry tool did not finish in time. Check the setting later; "
                                    + NOTHING_ELSE.lower().capitalize(), code)
    after = read()
    if after is True:
        return EnableResult(ENABLED, "Windows long paths are now switched on.", code)
    if code != 0:
        return EnableResult(FAILED, f"Windows' registry tool reported an error ({code}) and the setting is still off. "
                                    + NOTHING_ELSE + " " + MANAGED_NOTE, code)
    return EnableResult(NOT_CHANGED, "The change was made, but Windows still shows the setting as off, so something on "
                                     "this computer put it back. " + NOTHING_ELSE + " " + MANAGED_NOTE, code)


# --------------------------------------------------------------------------- #
# Proving that long paths work, in a fresh process
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    restart_needed: bool
    message: str
    facts: dict = field(default_factory=dict)


RESTART_MESSAGE = ("Windows long paths are switched on, but Windows is not applying the setting to new programs yet. "
                   "Restart Windows, then start Setup_and_Run-audiobook-creation-tool.bat again. Nothing was "
                   "installed.")
MOVE_ADVICE = (f"Or move the whole app folder somewhere shorter, for example {SHORT_FOLDER_EXAMPLE}, and start it from "
               "there.")


def path_of_length(base: str, total: int, leaf: str) -> str:
    """A path below *base* ending in *leaf* that is exactly *total* characters long (the shortest one when *total* is
    smaller than that), made of folders of at most 100 characters."""
    spare = total - len(base) - 1 - len(leaf)
    if spare <= 0:
        return os.path.join(base, leaf)
    if spare == 1:
        return os.path.join(base, "a" + leaf)
    folders = []
    while spare > 0:
        size = min(spare, 101)
        if spare - size == 1:
            size -= 1
        folders.append("a" * (size - 1))
        spare -= size
    return os.path.join(base, *folders, leaf)


def _extended(path: str) -> str:
    """The ``\\\\?\\`` form of an absolute path: accepted by Windows whatever the long-path setting, so the probe's
    own folder can always be removed, even by a process that started before the setting changed."""
    path = os.path.abspath(path)
    return path if sys.platform != "win32" or path.startswith("\\\\?\\") else "\\\\?\\" + path


def _remove_tree(path: str) -> None:
    shutil.rmtree(_extended(path), ignore_errors=True)


def _spawn_probe(python: str, base: str, file_chars: int, native_chars: int, timeout_s: float) -> dict:
    """Run the probe in a NEW process of *python* and return its facts (``{"error": ...}`` when it gave none)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run([python, "-I", "-B", str(Path(__file__).resolve()), "--probe", base, str(file_chars),
                               str(native_chars)], capture_output=True, text=True, timeout=timeout_s,
                              creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"the check could not be run ({type(exc).__name__}: {exc})"}
    for line in reversed(done.stdout.splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    return {"error": f"the check gave no answer (exit {done.returncode}): {(done.stderr or done.stdout)[-300:]}"}


def verify_runtime(root, *, deepest_file: int, deepest_native: int, python: Optional[str] = None,
                   spawn: Callable = None, read: Callable[[], Optional[bool]] = None,
                   timeout_s: float = 240.0) -> ProbeResult:
    """Whether a new process can really work as deep as the installation in *root* goes.

    *deepest_file* and *deepest_native* are the installation's deepest file and native library below the app's folder.
    Runs :func:`_probe` in a fresh process of *python* (default: the interpreter running setup -- the app's own base
    Python), inside its own ``files/runtime-data/long-path-check-<id>`` folder of *root*, and removes that folder
    again (the only thing this module ever deletes). ``ok`` only when the new process
    has long paths (where the depth needs them) and the file, the package installation and the native library all
    worked; ``restart_needed`` when the setting reads on but the new process does not have it."""
    spawn = spawn or _spawn_probe
    read = read or read_setting
    root = str(root)
    base = os.path.join(root, "files", "runtime-data", PROBE_PREFIX + uuid.uuid4().hex[:8])
    file_chars, native_chars = len(root) + deepest_file, len(root) + deepest_native
    try:
        facts = spawn(python or sys.executable, base, file_chars, native_chars, timeout_s)
    finally:
        if os.path.lexists(base):  # only the one folder this check made a moment ago; nothing else is ever removed
            _remove_tree(base)
    facts = dict(facts or {})
    facts.update(file_chars=file_chars, native_chars=native_chars)
    if facts.get("error"):
        return ProbeResult(False, False, "The app could not check that Windows long paths work here: "
                           f"{facts['error']}. Nothing was installed. " + MOVE_ADVICE, facts)
    needs = file_chars > WINDOWS_MAX_PATH
    if needs and not facts.get("process_long_paths"):
        if read() is True:
            return ProbeResult(False, True, RESTART_MESSAGE, facts)
        return ProbeResult(False, False, "Windows long paths are not switched on, and this folder needs them. Nothing "
                                         "was installed. " + MOVE_ADVICE, facts)
    failed = [name for name, label in (("file", "write a file"), ("pip", "install a package"),
                                       ("native", "load a program library")) if not (facts.get(name) or {}).get("ok")]
    if failed:
        what = {"file": "a file could not be written", "pip": "a package could not be installed",
                "native": "a program library could not be loaded"}
        detail = "; ".join(f"{what[name]} ({str((facts.get(name) or {}).get('error', 'no detail'))[:160]})"
                           for name in failed)
        restart = needs and read() is True and "file" in failed
        return ProbeResult(False, restart, ("At the depth this folder needs, " + detail + ". Nothing was installed. "
                                            + ("Restart Windows and try again. " if restart else "") + MOVE_ADVICE),
                           facts)
    return ProbeResult(True, False, "Long paths work in this folder.", facts)


def _wheel(path: str, inner: str) -> None:
    """Write a minimal, valid wheel holding one module at *inner* (a relative path with forward slashes)."""
    files = {inner: b"VALUE = 1\n",
             "actlongpathprobe-0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: actlongpathprobe\nVersion: 0\n",
             "actlongpathprobe-0.dist-info/WHEEL": b"Wheel-Version: 1.0\nGenerator: act\nRoot-Is-Purelib: true\n"
                                                    b"Tag: py3-none-any\n"}
    record = "".join(f"{name},sha256={base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()},"
                     f"{len(data)}\n" for name, data in files.items()) + "actlongpathprobe-0.dist-info/RECORD,,\n"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("actlongpathprobe-0.dist-info/RECORD", record)


def _pip_command() -> list:
    """This interpreter's pip: its own, else the copy bundled with ``ensurepip`` (run straight from its wheel)."""
    import importlib.util

    if importlib.util.find_spec("pip") is not None:
        return [sys.executable, "-I", "-m", "pip"]
    import ensurepip

    bundled = sorted((Path(ensurepip.__file__).parent / "_bundled").glob("pip-*.whl"))
    if not bundled:
        raise OSError("this Python has no pip and no bundled copy of it")
    return [sys.executable, "-I", str(bundled[-1] / "pip")]


def _native_source() -> str:
    """A real native library of this interpreter to copy and load (its own ``_ctypes`` extension, else a runtime DLL)."""
    import _ctypes

    candidates = [getattr(_ctypes, "__file__", "") or "",
                  os.path.join(os.path.dirname(sys.executable), "python3.dll"),
                  os.path.join(os.path.dirname(sys.executable), "vcruntime140.dll")]
    for candidate in candidates:
        if candidate.lower().endswith((".pyd", ".dll")) and os.path.isfile(candidate):
            return candidate
    raise OSError("no native library of this Python was found to test with")


def _probe(base: str, file_chars: int, native_chars: int) -> dict:
    """The check itself; runs in the fresh process. Every step reports ``ok`` or its own error; none stops the others."""
    import ctypes

    facts: dict = {"python": sys.executable, "version": sys.version.split()[0]}
    try:
        facts["process_long_paths"] = bool(ctypes.WinDLL("ntdll").RtlAreLongPathsEnabled())
    except (OSError, AttributeError):
        facts["process_long_paths"] = False
    os.makedirs(base, exist_ok=True)

    target = path_of_length(os.path.join(base, "f"), file_chars, "probe.txt")
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("long path probe")
        with open(target, encoding="utf-8") as handle:
            read_back = handle.read()
        facts["file"] = {"ok": read_back == "long path probe", "chars": len(target)}
    except OSError as exc:
        facts["file"] = {"ok": False, "chars": len(target), "error": f"{type(exc).__name__}: {exc}"[:300]}

    into = os.path.join(base, "t")
    installed = path_of_length(into, file_chars, "m.py")
    try:
        wheel = os.path.join(base, "actlongpathprobe-0-py3-none-any.whl")
        _wheel(wheel, os.path.relpath(installed, into).replace(os.sep, "/"))
        done = subprocess.run(_pip_command() + ["install", "--isolated", "--no-index", "--no-deps", "--no-compile",
                                                "--no-cache-dir", "--disable-pip-version-check", "--quiet",
                                                "--target", into, wheel],
                              capture_output=True, text=True, timeout=180,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        facts["pip"] = {"ok": done.returncode == 0 and os.path.isfile(installed), "chars": len(installed)}
        if not facts["pip"]["ok"]:
            facts["pip"]["error"] = f"pip exit {done.returncode}: {(done.stderr or done.stdout).strip()[-240:]}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        facts["pip"] = {"ok": False, "chars": len(installed), "error": f"{type(exc).__name__}: {exc}"[:300]}

    try:
        source = _native_source()
        library = path_of_length(os.path.join(base, "n"), native_chars, os.path.basename(source))
        os.makedirs(os.path.dirname(library), exist_ok=True)
        shutil.copyfile(source, library)
        loaded = ctypes.WinDLL(library)
        handle = loaded._handle
        del loaded
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
        kernel32.FreeLibrary(handle)
        facts["native"] = {"ok": True, "chars": len(library), "library": os.path.basename(source)}
    except OSError as exc:
        facts["native"] = {"ok": False, "chars": native_chars, "error": f"{type(exc).__name__}: {exc}"[:300]}
    _remove_tree(base)
    return facts


# --------------------------------------------------------------------------- #
# What the person is told, and the setup window's page
# --------------------------------------------------------------------------- #
def offer_text(assessment: Assessment, *, omnivoice_only: bool = False) -> dict:
    """The words of the setup window's path-length page, as data (so tests read exactly what the person reads)."""
    limits = assessment.omnivoice if omnivoice_only else assessment.app
    subject = "the OmniVoice voices need" if omnivoice_only else "the app needs"
    heading = ("OmniVoice needs a shorter folder, or Windows long paths" if omnivoice_only
               else "This folder's path is too long for Windows as it is set up")
    body = (f"The app is in a folder whose path is {assessment.length} characters long:\n{assessment.folder}\n\n"
            "Windows limits how long a file's path may be, and the app's voice engines keep files deep inside this "
            f"folder. As Windows is set up on this computer, {subject} a folder path of {limits.default} characters "
            "or fewer. No packages or voices have been downloaded. There are two ways forward:")
    move = ("A. Move the app to a shorter folder (recommended)\n"
            f"Close this window, extract the app again into a short folder such as {SHORT_FOLDER_EXAMPLE} (or move "
            "this whole folder there), and start Setup_and_Run from the new place. Nothing on the computer is changed.")
    enable_text = ("B. Switch on Windows long paths\n"
                   "This changes one Windows setting for the whole computer (\"Enable Win32 long paths\"), which lets "
                   "programs that support it use longer paths. It needs an administrator's approval: Windows will ask "
                   "permission for its own \"Registry Console Tool\", which makes only this one change. Windows may "
                   "need a restart before the setting takes effect. With it on, this folder "
                   f"({assessment.length} characters) is within the limit of {limits.long_paths}.")
    notes = []
    if not omnivoice_only and assessment.length > assessment.omnivoice.long_paths:
        notes.append("Even with long paths on, the OmniVoice voices cannot be installed in this folder (they need "
                     f"{assessment.omnivoice.long_paths} characters or fewer). Every other voice can.")
    return {"heading": heading, "body": body, "move": move, "enable": enable_text, "notes": notes,
            "move_button": "Close - I will move the app", "enable_button": "Switch on Windows long paths...",
            "skip_button": "Continue without OmniVoice" if omnivoice_only else None}


def _change_and_prove(enable_setting: Callable, verify: Optional[Callable], window: int, results) -> None:
    """Worker thread of :class:`ChoicePage`: ask Windows, then prove it in a fresh process. Touches no widget."""
    try:
        result = enable_setting(window=window)
        proof = verify() if verify is not None and result.state in (ENABLED, ALREADY_ENABLED) else None
    except Exception as exc:  # noqa: BLE001 - a failure here must reach the person as a sentence, not a crash
        result, proof = EnableResult(FAILED, f"The change could not be made ({type(exc).__name__}: {exc}). Nothing "
                                             "else was changed."), None
    results.put((result, proof))


class ChoicePage:
    """The path-length page of the first-run setup window: the two ways forward, and what happened.

    Tk is touched on the Tk thread only. The change and the proof run on a worker thread that touches no widget: it
    puts its result on a queue the page polls. ``on_working`` is called (on the Tk thread) once the setting is on and
    proved in a fresh process, ``on_close`` when the person chooses to move the app or closes after a result,
    ``on_skip`` (the OmniVoice-only page) when they go on without OmniVoice.
    """

    def __init__(self, parent, assessment: Assessment, *, on_close: Callable[[], None],
                 on_working: Callable[[], None], on_skip: Optional[Callable[[], None]] = None,
                 enable_setting: Callable[..., EnableResult] = None, verify: Callable[[], ProbeResult] = None,
                 window: int = 0, wrapped: Optional[list] = None, log: Optional[Callable[[str], None]] = None):
        import queue
        from tkinter import ttk

        self.assessment = assessment
        self.text = offer_text(assessment, omnivoice_only=on_skip is not None)
        self._enable = enable_setting or enable
        self._verify = verify
        self._on_working, self._on_close = on_working, on_close
        self._window, self._log = window, (log or (lambda _text: None))
        self._results: "queue.Queue" = queue.Queue()
        self.busy = False
        self.outcome: Optional[str] = None
        self.frame = ttk.Frame(parent)
        labels = []
        heading = ttk.Label(self.frame, text=self.text["heading"], font=("Segoe UI", 14, "bold"), justify="left")
        heading.pack(anchor="w", pady=(0, 8))
        for key in ("body", "move", "enable"):
            label = ttk.Label(self.frame, text=self.text[key], justify="left")
            label.pack(anchor="w", fill="x", pady=(0, 10))
            labels.append(label)
        for note in self.text["notes"]:
            label = ttk.Label(self.frame, text=note, justify="left")
            label.pack(anchor="w", fill="x", pady=(0, 10))
            labels.append(label)
        self.status = ttk.Label(self.frame, text="", justify="left")
        self.status.pack(anchor="w", fill="x", pady=(4, 0))
        labels.append(self.status)
        if wrapped is not None:
            wrapped.extend(labels + [heading])
        row = ttk.Frame(self.frame)
        row.pack(side="bottom", anchor="e", fill="x", pady=(12, 0))
        self.enable_button = ttk.Button(row, text=self.text["enable_button"], command=self.choose_enable)
        self.enable_button.pack(side="right", padx=(8, 0))
        self.skip_button = None
        if on_skip is not None:
            self.skip_button = ttk.Button(row, text=self.text["skip_button"], command=on_skip)
            self.skip_button.pack(side="right", padx=(8, 0))
        self.move_button = ttk.Button(row, text=self.text["move_button"], command=on_close)
        self.move_button.pack(side="right")

    def pack(self, **options) -> None:
        self.frame.pack(**options)

    def pack_forget(self) -> None:
        self.frame.pack_forget()

    def choose_enable(self) -> None:
        """The person pressed "Switch on Windows long paths...": that press is the consent to ask Windows."""
        if self.busy:
            return
        import threading

        self.busy = True
        for button in (self.enable_button, self.skip_button, self.move_button):
            if button is not None:
                button.configure(state="disabled")
        self.status.configure(text="Waiting for Windows' permission prompt (it may open behind this window)...")
        # The worker is handed plain callables and a queue, never this page: a thread must not hold (or be the last
        # holder of) anything that owns Tk objects.
        threading.Thread(target=_change_and_prove, args=(self._enable, self._verify, self._window, self._results),
                         daemon=True).start()
        self.frame.after(150, self._poll)

    def _poll(self) -> None:
        import queue

        try:
            result, proof = self._results.get_nowait()
        except queue.Empty:
            self.frame.after(150, self._poll)
            return
        self.finish(result, proof)

    def finish(self, result: EnableResult, proof: Optional[ProbeResult]) -> None:
        """Show what happened (Tk thread). Only a change that reads back on AND works in a fresh process goes on."""
        self.busy = False
        self._log(f"Windows long paths: {result.state} - {result.message}")
        if proof is not None:
            self._log(f"Long-path check in a new process: {'passed' if proof.ok else 'failed'} - {proof.message}")
        self.move_button.configure(state="normal", text="Close")
        if result.state in (ENABLED, ALREADY_ENABLED) and (proof is None or proof.ok):
            self.outcome = "working"
            self.status.configure(text=result.message + " Setup starts again in a moment so that it uses the setting.")
            self.frame.after(1200, self._on_working)
            return
        if result.state in (ENABLED, ALREADY_ENABLED):
            self.outcome = "restart" if proof.restart_needed else "not-working"
            self.status.configure(text=result.message + " " + proof.message)
            return  # the setting is on: offering to switch it on again would be meaningless. Only Close remains.
        self.outcome = result.state
        self.status.configure(text=result.message + " You can still move the app to a shorter folder (A).")
        for button in (self.enable_button, self.skip_button):
            if button is not None:
                button.configure(state="normal")
        self.move_button.configure(text=self.text["move_button"])


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--probe":
        print(json.dumps(_probe(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))))
        sys.exit(0)
    sys.exit("usage: long_paths.py --probe <folder> <file path length> <native library path length>")
