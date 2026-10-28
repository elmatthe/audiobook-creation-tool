"""Fixed M1 entry: actual Planner.observe, no injected observation or execution.

Only the separately pinned controlled-origin issuer launches this entry. The
native check happens before request processing. Observation has no permitted
filesystem writes, socket operations or subprocesses. Publication is a distinct
phase, with the existing fixed exchange as its only writable destination.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

from shared import optional_setup_readonly_context_v3 as origin
from tts import optional_setup_authority as authority
from tts import optional_setup_planning_worker_v3 as worker


def _parent_pid(pid):
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [('status', ctypes.c_long), ('peb', ctypes.c_void_p), ('affinity', ctypes.c_size_t),
                    ('priority', ctypes.c_long), ('pid', ctypes.c_size_t), ('parent', ctypes.c_size_t)]

    kernel = origin.exchange._kernel()
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise origin.OriginUnavailable('process-ancestry-unavailable')
    try:
        query = ctypes.WinDLL('ntdll').NtQueryInformationProcess
        query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                          wintypes.ULONG, ctypes.c_void_p]
        query.restype = ctypes.c_long
        info = Basic()
        if query(handle, 0, ctypes.byref(info), ctypes.sizeof(info), None) < 0:
            raise origin.OriginUnavailable('process-ancestry-unavailable')
        return info.parent
    finally:
        kernel.CloseHandle(handle)


def _qualify():
    app = Path(__file__).absolute().parents[2]
    if (app.name != 'app' or not any(p.name.startswith('stage4d2d-m1-') for p in app.parents)
            or Path.cwd() != app / 'scripts' or not sys.flags.isolated or not sys.flags.no_site
            or not sys.dont_write_bytecode or sys.version_info[:2] != (3, 12)):
        raise origin.OriginUnavailable('worker-code-origin')
    for path in (app, *app.parents):
        if path.lstat().st_file_attributes & 0x400:
            raise origin.OriginUnavailable('worker-reparse-origin')
    path = app / 'readonly-origin.json'
    if path.stat().st_size > 2 * 1024 * 1024:
        raise origin.OriginUnavailable('worker-origin-size')
    facts = json.loads(path.read_bytes())
    base, main = Path(facts['base']), Path(facts['main'])
    if (Path(sys.executable) != Path(facts['interpreter']) or Path(sys.prefix) != base
            or Path(sys.base_prefix) != base or main / 'Scripts/python.exe' != Path(sys.executable)):
        raise origin.OriginUnavailable('worker-interpreter-origin')
    expected = {base / 'python.exe', main / 'Scripts/python.exe'}
    pid, seen = os.getpid(), set()
    for _ in range(4):
        if pid in seen:
            raise origin.OriginUnavailable('process-ancestry-cycle')
        seen.add(pid)
        image, birth = origin.process_identity(pid)
        if image not in expected:
            raise origin.OriginUnavailable('process-ancestry-image')
        if pid == facts['parent_pid']:
            if birth != facts['parent_birth']:
                raise origin.OriginUnavailable('process-ancestry-birth')
            break
        pid = _parent_pid(pid)
    else:
        raise origin.OriginUnavailable('process-ancestry-unbound')
    from ctypes import wintypes
    kernel = origin.exchange._kernel()
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    contained = wintypes.BOOL()
    if not kernel.IsProcessInJob(kernel.GetCurrentProcess(), None, ctypes.byref(contained)) or not contained.value:
        raise origin.OriginUnavailable('worker-not-contained')
    allowed = {Path(p) for p, _ in facts['runtime']}
    system = origin.system_directory()

    def native_check():
        for path in origin.native_modules():
            if path not in allowed and not path.is_relative_to(system):
                raise origin.OriginUnavailable('native-dll-origin')

    native_check()
    return app, native_check, {Path(p) for p, _ in facts['runtime'] + facts['sources']}


def main():
    if len(sys.argv) != 3:
        return 2
    try:
        app, native_check, sources = _qualify()
    except Exception as exc:
        print('read-only-refused:' + (exc.code if isinstance(exc, origin.OriginUnavailable)
                                      else 'origin-unavailable'), file=sys.stderr)
        return 2
    phase, refused = ['observe'], []
    system = origin.system_directory()

    def audit(event, args):
        denied = event in ('subprocess.Popen', 'os.system', 'os.startfile', 'os.posix_spawn',
                          'os.spawn', 'os.exec', 'socket.connect', 'socket.bind', 'socket.getaddrinfo',
                          'os.add_dll_directory', 'os.chdir')
        if event == 'import' and isinstance(args[1], str):
            denied = Path(args[1]).absolute() not in sources
        if event == 'ctypes.dlopen':
            name = args[0]
            # Only these independently known OS libraries use bare names. Other
            # native loads must name a pinned runtime image or the OS trust root.
            denied = not (isinstance(name, str) and (name.lower() in
                ('kernel32', 'kernel32.dll', 'ntdll', 'ntdll.dll') or
                (Path(name).is_absolute() and (Path(name) in sources or Path(name).is_relative_to(system)))))
        write = event in ('os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'os.link', 'os.symlink',
                          'os.truncate', 'os.chmod', 'os.utime')
        if event == 'open':
            write = bool(isinstance(args[2], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
            if not write and isinstance(args[0], (str, bytes)):
                target = Path(os.fsdecode(args[0])).absolute()
                if target.suffix.lower() == '.pyc' and target not in sources:
                    # CPython may try a nonexistent cache beside pinned source.
                    # Force source fallback without opening an unpinned cache.
                    raise FileNotFoundError('unpinned bytecode cache')
                if target.suffix.lower() in ('.py', '.pyc', '.pyd', '.dll') and target not in sources:
                    denied = True
        if write:
            if phase[0] == 'observe':
                denied = True
            else:
                # Publication uses only the existing fixed P exchange. No cache,
                # lock, model, readiness, consent or history writes are permitted.
                from shared import optional_setup_exchange_v3 as exchange
                target = args[0]
                if isinstance(target, (str, bytes)):
                    target = Path(os.fsdecode(target)).absolute()
                    fixed = app / exchange.EXCHANGE_ROOT
                    denied = not (target == fixed or target.is_relative_to(fixed))
                else:
                    denied = not isinstance(target, int)
        if denied:
            if not refused:
                refused.append(event)
            raise PermissionError('read-only observation effect refused')

    sys.addaudithook(audit)

    def before_publication():
        if refused:
            raise origin.OriginUnavailable('observation-side-effect')
        native_check()
        phase[0] = 'publish'

    return worker._execute(authority.Planner(), sys.argv[1:], lambda: app,
                           after_plan=before_publication)


if __name__ == '__main__':
    sys.exit(main())
