"""Keeps a journey's real Windows file dialogs out of the owner's own dialog history. Test-only; never shipped.

Windows' file dialog records every path it opens per user: ``HKCU\\...\\Explorer\\ComDlg32\\OpenSavePidlMRU`` (20 per file type),
``LastVisitedPidlMRU``, and Explorer's per-folder view state (``Shell\\BagMRU``/``Bags``). The Phase 3 gate's journeys left 94 such values
in the owner's history (measured read-only on 2026-11-07); a backup taken now cannot bring back what they pushed out.

**How it is kept out.** The application under test is started at Low integrity, from its first instruction (``spawn_low``). Windows then
refuses that process, and every process it starts, write access to anything labelled above Low: the whole of the owner's per-user registry
except ``Software\\AppDataLow``, and the owner's profile folders except ``LocalLow``. Nothing in the owner's registry is written, snapshotted
or restored, so an interrupted run, a crash or the owner using a file dialog at the same moment has nothing to undo and nothing to lose.
The dialogs stay real: the same Windows dialog, driven by the same real keystrokes; it only has nowhere it may record them. The run's own
scratch is labelled Low (``label_low``) so the application can still write there, and only there.

Why not the alternatives (measured or read, 2026-11-07): lowering a process that started at Medium keeps the handles it already had, and
the probe saw its cached ``HKEY_CURRENT_USER`` handle still grant write access, so the process must start Low. A separate Windows account
needs an administrator, a new account on the machine and access to the owner's profile, all system changes. Snapshot and restore of the
owner's keys writes the owner's registry, can overwrite a change the owner makes during the run, and cannot run after a crash.

**Refusal.** ``preflight()`` runs a Low child that only *opens* each dialog-state key for writing (an open writes nothing; a granted handle
is closed unused) and must be refused every one. ``require_low`` checks a running process from outside. The session refuses to drive an
application, and so any file dialog, unless both hold. ``history_references`` is the read-only oracle afterwards.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import hashlib
import json
import os
import subprocess
import sys
import winreg
from pathlib import Path

LOW_RID = 0x1000
MEDIUM_RID = 0x2000
LOW_SID = "S-1-16-4096"
LOW_LABEL_SACL = "S:(ML;OICI;NW;;;LW)"  # mandatory label Low, no-write-up, inherited by files and folders created below

# Every place the Phase 3 scan found a gate path, and the dialog-state keys beside them. Relative to HKEY_CURRENT_USER. "" is the root.
DIALOG_STATE_KEYS = (
    "",
    r"Software",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\OpenSavePidlMRU",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\LastVisitedPidlMRU",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\LastVisitedPidlMRULegacy",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\CIDSizeMRU",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\FirstFolder",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs",
    r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\BagMRU",
    r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\Bags",
    r"Software\Microsoft\Windows\Shell\BagMRU",
    r"Software\Microsoft\Windows\Shell\Bags",
)
# Subtrees the read-only oracle walks. AppDataLow is the one place a Low process may write, so it is watched too.
HISTORY_ROOTS = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs",
    r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell",
    r"Software\Microsoft\Windows\Shell",
    r"Software\AppDataLow",
)
ERROR_ACCESS_DENIED = 5
ERROR_FILE_NOT_FOUND = 2

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_k32.GetCurrentProcess.restype = w.HANDLE
_k32.OpenProcess.restype = w.HANDLE
_k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
_k32.CloseHandle.argtypes = [w.HANDLE]
_k32.LocalFree.argtypes = [ctypes.c_void_p]
_k32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
_k32.WaitForSingleObject.restype = w.DWORD
_k32.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
_k32.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
_k32.CreateFileW.restype = w.HANDLE
_k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
_k32.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)]
_k32.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, w.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                           ctypes.c_void_p]
_k32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
_adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
_adv.DuplicateTokenEx.argtypes = [w.HANDLE, w.DWORD, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(w.HANDLE)]
_adv.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
_adv.SetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
_adv.ConvertStringSidToSidW.argtypes = [w.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
_adv.GetLengthSid.argtypes = [ctypes.c_void_p]
_adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
_adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
_adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, w.DWORD]
_adv.GetSidSubAuthority.restype = ctypes.POINTER(w.DWORD)
_adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
_adv.GetSecurityDescriptorSacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.BOOL)]
_adv.SetNamedSecurityInfoW.argtypes = [w.LPCWSTR, ctypes.c_int, w.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
_adv.GetNamedSecurityInfoW.argtypes = [w.LPCWSTR, ctypes.c_int, w.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
_adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(w.LPWSTR),
                                                                      ctypes.c_void_p]
_adv.RegOpenKeyExW.argtypes = [w.HKEY, w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(w.HKEY)]
_adv.RegCloseKey.argtypes = [w.HKEY]
_adv.CreateProcessAsUserW.argtypes = [w.HANDLE, w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD, ctypes.c_void_p,
                                      w.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p]

TOKEN_DUPLICATE, TOKEN_QUERY, TOKEN_ASSIGN_PRIMARY, TOKEN_ADJUST_DEFAULT = 0x0002, 0x0008, 0x0001, 0x0080
TokenIntegrityLevel = 25
SecurityImpersonation, TokenPrimary = 2, 1
SE_GROUP_INTEGRITY = 0x20
SE_FILE_OBJECT = 1
LABEL_SECURITY_INFORMATION = 0x10
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT, EXTENDED_STARTUPINFO_PRESENT = 0x4, 0x400, 0x80000
STARTF_USESTDHANDLES = 0x100
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x20002


class ContainmentUnavailable(RuntimeError):
    """The owner's dialog history could not be shown to be protected, so no file dialog may be driven."""


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", w.DWORD)]


class _TokenMandatoryLabel(ctypes.Structure):
    _fields_ = [("Label", _SidAndAttributes)]


class _StartupInfo(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR), ("lpTitle", w.LPWSTR), ("dwX", w.DWORD), ("dwY", w.DWORD),
                ("dwXSize", w.DWORD), ("dwYSize", w.DWORD), ("dwXCountChars", w.DWORD), ("dwYCountChars", w.DWORD),
                ("dwFillAttribute", w.DWORD), ("dwFlags", w.DWORD), ("wShowWindow", w.WORD), ("cbReserved2", w.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", w.HANDLE), ("hStdOutput", w.HANDLE), ("hStdError", w.HANDLE)]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", ctypes.c_void_p)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE), ("dwProcessId", w.DWORD), ("dwThreadId", w.DWORD)]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("nLength", w.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", w.BOOL)]


def _error(what: str) -> OSError:
    code = ctypes.get_last_error()
    return OSError(code, f"{what} failed: {ctypes.FormatError(code).strip()} (error {code})")


def _token_rid(token) -> int:
    size = w.DWORD()
    _adv.GetTokenInformation(token, TokenIntegrityLevel, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    if not _adv.GetTokenInformation(token, TokenIntegrityLevel, buffer, size, ctypes.byref(size)):
        raise _error("GetTokenInformation")
    sid = ctypes.cast(buffer, ctypes.POINTER(_TokenMandatoryLabel)).contents.Label.Sid
    count = _adv.GetSidSubAuthorityCount(sid).contents.value
    return _adv.GetSidSubAuthority(sid, count - 1).contents.value


def integrity_of(pid: int | None = None) -> int | None:
    """The integrity RID of a process (this one when ``pid`` is None), read from its token; None if it cannot be opened (it has gone)."""
    process = _k32.GetCurrentProcess() if pid is None else _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    token = w.HANDLE()
    try:
        if not _adv.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            return _token_rid(token)
        finally:
            _k32.CloseHandle(token)
    finally:
        if pid is not None:
            _k32.CloseHandle(process)


def require_low(pids, what: str) -> dict:
    """Refuse unless every listed process is Low. A process that has already gone is no evidence either way and is reported as such."""
    seen = {int(pid): integrity_of(int(pid)) for pid in pids}
    live = {pid: rid for pid, rid in seen.items() if rid is not None}
    if not live:
        raise ContainmentUnavailable(f"{what}: no live process to check ({seen})")
    above = {pid: hex(rid) for pid, rid in live.items() if rid > LOW_RID}
    if above:
        raise ContainmentUnavailable(f"{what}: not Low integrity, so its file dialogs could write the owner's history: {above}")
    return {"pids": {str(pid): (hex(rid) if rid is not None else "gone") for pid, rid in seen.items()}}


def _low_label():
    descriptor = ctypes.c_void_p()
    if not _adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(LOW_LABEL_SACL, 1, ctypes.byref(descriptor), None):
        raise _error("ConvertStringSecurityDescriptorToSecurityDescriptor")
    present, defaulted, sacl = w.BOOL(), w.BOOL(), ctypes.c_void_p()
    if not _adv.GetSecurityDescriptorSacl(descriptor, ctypes.byref(present), ctypes.byref(sacl), ctypes.byref(defaulted)):
        _k32.LocalFree(descriptor)
        raise _error("GetSecurityDescriptorSacl")
    return descriptor, sacl


def label_low(folder: Path) -> str:
    """Let a Low process write below ``folder``, which must be this run's own scratch. Inherited by what is created there later, and
    applied by Windows to what is already there. Changes the label only; the owner's access is untouched. Returns the label read back."""
    descriptor, sacl = _low_label()
    try:
        status = _adv.SetNamedSecurityInfoW(str(folder), SE_FILE_OBJECT, LABEL_SECURITY_INFORMATION, None, None, None, sacl)
    finally:
        _k32.LocalFree(descriptor)
    if status:
        raise OSError(status, f"labelling {folder} Low failed: {ctypes.FormatError(status).strip()}")
    return folder_label(folder)


def folder_label(folder: Path) -> str:
    """The folder's mandatory label as SDDL, e.g. ``S:(ML;OICI;NW;;;LW)``; empty when it has none (Medium, by default)."""
    descriptor, sacl = ctypes.c_void_p(), ctypes.c_void_p()
    status = _adv.GetNamedSecurityInfoW(str(folder), SE_FILE_OBJECT, LABEL_SECURITY_INFORMATION, None, None, None, ctypes.byref(sacl),
                                        ctypes.byref(descriptor))
    if status:
        raise OSError(status, f"reading the label of {folder} failed")
    text = w.LPWSTR()
    try:
        if not _adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, LABEL_SECURITY_INFORMATION, ctypes.byref(text), None):
            raise _error("ConvertSecurityDescriptorToStringSecurityDescriptor")
        value = text.value or ""
        _k32.LocalFree(text)
        return value
    finally:
        _k32.LocalFree(descriptor)


def _low_primary_token() -> w.HANDLE:
    own, token, sid = w.HANDLE(), w.HANDLE(), ctypes.c_void_p()
    if not _adv.OpenProcessToken(_k32.GetCurrentProcess(), TOKEN_DUPLICATE | TOKEN_QUERY, ctypes.byref(own)):
        raise _error("OpenProcessToken")
    try:
        access = TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ASSIGN_PRIMARY | TOKEN_ADJUST_DEFAULT
        if not _adv.DuplicateTokenEx(own, access, None, SecurityImpersonation, TokenPrimary, ctypes.byref(token)):
            raise _error("DuplicateTokenEx")
    finally:
        _k32.CloseHandle(own)
    if not _adv.ConvertStringSidToSidW(LOW_SID, ctypes.byref(sid)):
        _k32.CloseHandle(token)
        raise _error("ConvertStringSidToSid")
    try:
        label = _TokenMandatoryLabel(_SidAndAttributes(sid, SE_GROUP_INTEGRITY))
        if not _adv.SetTokenInformation(token, TokenIntegrityLevel, ctypes.byref(label), ctypes.sizeof(label) + _adv.GetLengthSid(sid)):
            _k32.CloseHandle(token)
            raise _error("SetTokenInformation(TokenIntegrityLevel)")
    finally:
        _k32.LocalFree(sid)
    if _token_rid(token) != LOW_RID:
        _k32.CloseHandle(token)
        raise ContainmentUnavailable("the duplicated token did not take the Low label")
    return token


class LowProcess:
    """What the session needs of ``subprocess.Popen`` for a process started at Low, suspended, by ``spawn_low``."""

    def __init__(self, info: _ProcessInformation, argv: list[str]) -> None:
        self.args = argv
        self.pid = info.dwProcessId
        self._handle = info.hProcess
        _k32.CloseHandle(info.hThread)
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is None and _k32.WaitForSingleObject(self._handle, 0) == 0:
            code = w.DWORD()
            _k32.GetExitCodeProcess(self._handle, ctypes.byref(code))
            self.returncode = code.value
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        milliseconds = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
        if self.returncode is None and _k32.WaitForSingleObject(self._handle, milliseconds) != 0:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.poll()

    def kill(self) -> None:
        if self.poll() is None:
            _k32.TerminateProcess(self._handle, 1)

    def __del__(self) -> None:
        handle, self._handle = getattr(self, "_handle", None), None
        if handle:
            _k32.CloseHandle(handle)


def _environment_block(env: dict) -> ctypes.Array:
    pairs = sorted(env.items(), key=lambda item: item[0].upper())
    text = "".join(f"{key}={value}\0" for key, value in pairs) + "\0"
    return ctypes.create_unicode_buffer(text, len(text))


def spawn_low(argv: list[str], *, cwd: Path, env: dict, output: Path, suspended: bool = True) -> LowProcess:
    """Start ``argv`` at Low integrity, its stdout and stderr appended to ``output``, stdin the null device, and no other handle inherited.
    Suspended by default, so the caller assigns it to a job before it runs (``_Job.adopt_and_resume``)."""
    token = _low_primary_token()
    inheritable = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
    sink = _k32.CreateFileW(str(output), 0x0004 | 0x00100000, 0x1 | 0x2, ctypes.byref(inheritable), 4, 0x80, None)  # append, OPEN_ALWAYS
    null = _k32.CreateFileW("NUL", 0x80000000, 0x1 | 0x2, ctypes.byref(inheritable), 3, 0x80, None)
    invalid = w.HANDLE(-1).value
    if sink in (None, invalid) or null in (None, invalid):
        _k32.CloseHandle(token)
        raise _error("opening the child's output")
    handles = (w.HANDLE * 2)(sink, null)
    size = ctypes.c_size_t()
    _k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attributes = ctypes.create_string_buffer(size.value)
    try:
        if not _k32.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
            raise _error("InitializeProcThreadAttributeList")
        try:
            if not _k32.UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, handles, ctypes.sizeof(handles), None, None):
                raise _error("UpdateProcThreadAttribute(handle list)")
            startup = _StartupInfoEx()
            startup.StartupInfo.cb = ctypes.sizeof(_StartupInfoEx)
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = null, sink, sink
            startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
            info = _ProcessInformation()
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            flags = CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT | (CREATE_SUSPENDED if suspended else 0)
            if not _adv.CreateProcessAsUserW(token, None, command, None, None, True, flags, _environment_block(env), str(cwd),
                                             ctypes.byref(startup), ctypes.byref(info)):
                raise _error("CreateProcessAsUser at Low integrity")
        finally:
            _k32.DeleteProcThreadAttributeList(attributes)
    finally:
        _k32.CloseHandle(sink)
        _k32.CloseHandle(null)
        _k32.CloseHandle(token)
    return LowProcess(info, list(argv))


# ---------------------------------------------------------------------------------------------------------------- preflight
def _user_sid() -> str:
    token, text = w.HANDLE(), w.LPWSTR()
    if not _adv.OpenProcessToken(_k32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        raise _error("OpenProcessToken")
    try:
        size = w.DWORD()
        _adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        buffer = ctypes.create_string_buffer(size.value)
        if not _adv.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise _error("GetTokenInformation(TokenUser)")
        sid = ctypes.cast(buffer, ctypes.POINTER(_SidAndAttributes)).contents.Sid
        _adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
        if not _adv.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise _error("ConvertSidToStringSid")
        value = text.value
        _k32.LocalFree(text)
        return value
    finally:
        _k32.CloseHandle(token)


def _open_for_write(path: str) -> int:
    """Open only: KEY_SET_VALUE | KEY_CREATE_SUB_KEY. Writes nothing; a granted handle is closed unused. Returns the Win32 status.

    Opened through ``HKEY_USERS\\<sid>``, never the ``HKEY_CURRENT_USER`` handle: opening that handle's own root hands back the cached
    handle without a fresh access check (measured: "granted" even in a process born Low), so it would measure nothing."""
    key = w.HKEY()
    status = _adv.RegOpenKeyExW(w.HKEY(winreg.HKEY_USERS), path, 0, 0x0002 | 0x0004, ctypes.byref(key))
    if status == 0:
        _adv.RegCloseKey(key)
    return status


def _probe_here() -> dict:
    """Run inside the Low child: its own integrity, then an open-for-write of every dialog-state key, and of both hive roots."""
    sid = _user_sid()
    keys = {key or "<root>": _open_for_write(f"{sid}\\{key}" if key else sid) for key in DIALOG_STATE_KEYS}
    keys["<classes root>"] = _open_for_write(f"{sid}_Classes")
    return {"pid": os.getpid(), "integrity": hex(integrity_of() or 0), "keys": keys}


def preflight(work: Path, *, python: str | None = None, timeout: float = 30) -> dict:
    """Prove, from a Low child started exactly as the application will be, that the owner's dialog history refuses it. Raises
    ContainmentUnavailable otherwise. ``work`` is this run's own scratch; it is labelled Low here."""
    work.mkdir(parents=True, exist_ok=True)
    label = label_low(work)
    output = work / "containment-preflight.json"
    log = work / "containment-preflight.log"
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
    env.update(TEMP=str(work), TMP=str(work), PYTHONDONTWRITEBYTECODE="1")
    try:
        process = spawn_low([python or sys.executable, "-I", "-B", __file__, "--probe", str(output)], cwd=work, env=env, output=log,
                            suspended=False)
    except OSError as exc:
        raise ContainmentUnavailable(f"a Low-integrity process could not be started: {exc}") from exc
    try:
        code = process.wait(timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        raise ContainmentUnavailable("the Low-integrity preflight did not finish") from None
    if code != 0 or not output.is_file():
        raise ContainmentUnavailable(f"the Low-integrity preflight failed (exit {code}): {log.read_text(errors='replace')[-800:]}")
    facts = json.loads(output.read_text(encoding="utf-8"))
    facts["scratch_label"] = label
    if int(facts["integrity"], 16) != LOW_RID:
        raise ContainmentUnavailable(f"the preflight child ran at {facts['integrity']}, not Low")
    open_keys = {key: status for key, status in facts["keys"].items() if status not in (ERROR_ACCESS_DENIED, ERROR_FILE_NOT_FOUND)}
    if open_keys:
        raise ContainmentUnavailable(f"a Low process may write these dialog-history keys: {open_keys}")
    facts["verdict"] = "contained"
    return facts


# ---------------------------------------------------------------------------------------------------------------- oracle
def history_references(needle: str = "act-gate") -> dict[str, str]:
    """Read-only (KEY_READ). Every value under the dialog-history subtrees whose data names ``needle``, as ``key\\value -> sha256``.
    A run is clean when nothing appears afterwards that was not there, unchanged, before. The owner using a dialog meanwhile can only
    push old entries out, never add one naming this run's scratch."""
    patterns = (needle.encode("utf-16-le"), needle.encode("ascii"), needle.upper().encode("utf-16-le"))
    found: dict[str, str] = {}

    def walk(path: str, depth: int) -> None:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
        except OSError:
            return
        with key:
            index = 0
            while True:
                try:
                    name, data, kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                raw = data if isinstance(data, bytes) else str(data).encode("utf-16-le", "surrogatepass")
                if any(pattern in raw for pattern in patterns):
                    found[f"{path}\\{name}"] = hashlib.sha256(raw).hexdigest()
            children = []
            while depth < 24:
                try:
                    children.append(winreg.EnumKey(key, len(children)))
                except OSError:
                    break
        for child in children:
            walk(f"{path}\\{child}", depth + 1)

    for root in HISTORY_ROOTS:
        walk(root, 0)
    return found


def history_added(before: dict[str, str], after: dict[str, str]) -> dict[str, str]:
    """What ``after`` names that ``before`` did not, or names with different data."""
    return {key: digest for key, digest in after.items() if before.get(key) != digest}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        Path(sys.argv[2]).write_text(json.dumps(_probe_here(), indent=1), encoding="utf-8")
        sys.exit(0)
    print(__doc__)
    sys.exit(2)
