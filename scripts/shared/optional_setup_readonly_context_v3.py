"""Production-origin qualification prerequisite for read-only v3 planning.

This production-disconnected M1 issuer grants controlled read-only planning only.
The native origin gate must qualify before a context can be issued. It grants no
consent or mutation authority and has no injected observer/interpreter adapter.
"""
from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
import weakref
from dataclasses import dataclass
from pathlib import Path

from shared import optional_setup_exchange_v3 as exchange
from shared import artifact_store as store
from shared import optional_setup_protocol as proto
from shared import optional_setup_wire_v3 as wire
from shared import optional_setup_supervisor_v3 as supervisor
from shared.optional_setup_planning_bridge_v3 import SOURCES
from tts import qwen3_process

_REPO = Path(__file__).absolute().parents[2]
_ISSUED = weakref.WeakValueDictionary()
_RUNS = {}
_BOOTSTRAP = ('import os,sys;sys.path.insert(0,os.getcwd());'
    'from tts.optional_setup_readonly_worker_v3 import main;sys.exit(main())')
_CODE = (*SOURCES, 'shared/optional_setup_planning_bridge_v3.py',
    'shared/optional_setup_supervisor_v3.py', 'shared/optional_setup_readonly_context_v3.py',
    'tts/optional_setup_readonly_worker_v3.py', 'tts/qwen3_models.json',
    'tts/data/bundled_clone_transcripts.json')


class OriginUnavailable(RuntimeError):
    """A failed prerequisite; never permission to retry using a weaker origin."""

    def __init__(self, code, *, path=None, winerror=None):
        self.code, self.path, self.winerror = code, path, winerror
        super().__init__(f'{code}: path={path}, winerror={winerror}')


@dataclass(frozen=True, slots=True)
class MainOrigin:
    """Temporary origin evidence, valid only while its native handles are held.

    This is not an execution context and no executor accepts it. Full module/DLL
    closure and process ancestry still require qualification before any issuance.
    """
    interpreter: Path
    main_prefix: Path
    base_prefix: Path
    pinned_paths: tuple[Path, ...]


@contextlib.contextmanager
def _pin_ancestry(path):
    """Pin every ancestor, including those above the known installation root.

    FILE_LIST_DIRECTORY participates in sharing checks. READ_ATTRIBUTES alone
    cannot prevent another handle setting a reparse point. Keep the existing
    store's deny-write/delete policy; never relax it on access/sharing refusal.
    The open is read-only, OPEN_EXISTING, OPEN_REPARSE_POINT/BACKUP_SEMANTICS.
    """
    path = exchange._root(path)
    kernel = exchange._kernel()
    invalid = ctypes.c_void_p(-1).value
    handles, pinned = [], []
    try:
        for folder in reversed(path.parents):
            if folder.lstat().st_file_attributes & 0x400:
                raise OriginUnavailable('source-reparse-ancestry', path=folder)
            handle = kernel.CreateFileW(str(folder), 1, 1, None, 3, 0x02200000, None)
            if handle == invalid:
                raise OriginUnavailable('native-ancestry-pin-unavailable',
                                        path=folder, winerror=ctypes.get_last_error())
            handles.append(handle)
            if folder.lstat().st_file_attributes & 0x400 or folder.resolve() != folder:
                raise OriginUnavailable('source-reparse-ancestry', path=folder)
            pinned.append(folder)
        yield tuple(pinned)
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


@contextlib.contextmanager
def qualify_main_origin():
    """Fail closed before any request/files/probe/child on an unproved origin.

    Native gate for the installed main console CPython, not the venv redirector's
    parent/launcher name inferred from an activation variable. No caller input
    can select the interpreter, source root, prefix, cfg or qualification policy.
    """
    interpreter = _REPO / '.venv/Scripts/python.exe'
    main, base = _REPO / '.venv', Path(sys.base_prefix)
    if (os.name != 'nt' or sys.implementation.name != 'cpython'
            or sys.version_info[:2] != (3, 12) or Path(sys.executable) != interpreter
            or Path(sys.prefix) != main or base == main
            or Path(sys._base_executable) != base / 'python.exe'
            or not sys.flags.isolated or not sys.dont_write_bytecode):
        raise OriginUnavailable('main-console-identity')
    # The first native gate is intentionally ahead of reading cfg/import data.
    # If it cannot be established, no partial origin evidence escapes.
    with contextlib.ExitStack() as pins:
        pinned = set()
        for path in (interpreter, base / 'python.exe', Path(__file__).absolute()):
            pinned.update(pins.enter_context(_pin_ancestry(path)))
        yield MainOrigin(interpreter, main, base, tuple(sorted(pinned)))


@contextlib.contextmanager
def _pin_file(path, *, cap=16 * 1024 * 1024):
    path = exchange._root(path)
    # Unlike fixture pinning, retain the entire drive ancestry through use.
    with store.boundary(Path(path.anchor), path) as parent:
        folder = exchange._Folder(Path(path.anchor), path.parent, exchange._handle_id(parent))
        with exchange._open_file(folder, path) as stream:
            before = exchange._file_identity(stream, path)
            if not 0 <= before[2] <= cap:
                raise OriginUnavailable('source-size-limit', path=path)
            raw = stream.read(cap + 1)
            if len(raw) != before[2] or exchange._file_identity(stream, path) != before:
                raise OriginUnavailable('source-identity-changed', path=path)
            yield raw
            if exchange._file_identity(stream, path) != before:
                raise OriginUnavailable('source-identity-changed', path=path)


def process_identity(pid):
    """OS image and creation time, independent of sys.executable/JSON claims."""
    from ctypes import wintypes
    kernel = exchange._kernel()
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.c_void_p] * 4)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise OriginUnavailable('process-identity-unavailable')
    try:
        size, image = wintypes.DWORD(32768), ctypes.create_unicode_buffer(32768)
        times = (ctypes.c_ulonglong * 4)()
        if (not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size))
                or not kernel.GetProcessTimes(handle, *(ctypes.byref(times, i * 8) for i in range(4)))):
            raise OriginUnavailable('process-identity-unavailable')
        return Path(image.value), times[0]
    finally:
        kernel.CloseHandle(handle)


def native_modules():
    """Actual mapped images; a declared import root is insufficient DLL proof."""
    from ctypes import wintypes
    kernel = exchange._kernel()
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.K32EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.K32GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE,
                                            wintypes.LPWSTR, wintypes.DWORD]
    modules, needed = (wintypes.HMODULE * 512)(), wintypes.DWORD()
    process = kernel.GetCurrentProcess()
    if (not kernel.K32EnumProcessModules(process, modules, ctypes.sizeof(modules), ctypes.byref(needed))
            or needed.value > ctypes.sizeof(modules)):
        raise OriginUnavailable('native-module-inventory-unavailable')
    paths = []
    for module in modules[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
        name = ctypes.create_unicode_buffer(32768)
        if not kernel.K32GetModuleFileNameExW(process, module, name, len(name)):
            raise OriginUnavailable('native-module-path-unavailable')
        paths.append(Path(name.value))
    return tuple(paths)


def system_directory():
    """Resolve the OS DLL trust root independently of environment strings."""
    from ctypes import wintypes
    query = exchange._kernel().GetSystemDirectoryW
    query.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    query.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    length = query(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise OriginUnavailable('system-directory-unavailable')
    return exchange._root(Path(buffer.value))


@contextlib.contextmanager
def qualify_tk_runtime():
    """Hold installed Tk Python/native/Tcl sources through window destruction."""
    with contextlib.ExitStack() as pins:
        main = pins.enter_context(qualify_main_origin())
        base = main.base_prefix
        paths = list((base / 'Lib/tkinter').glob('*.py'))
        paths += list((base / 'Lib/tkinter/__pycache__').glob('*.pyc'))
        paths += [base / 'DLLs/_tkinter.pyd']
        paths += list((base / 'DLLs').glob('*.dll'))
        started, total = time.monotonic(), 0
        for folder, directories, names in os.walk(base / 'tcl', followlinks=False):
            for name in [*directories, *names]:
                path = Path(folder) / name
                if path.lstat().st_file_attributes & 0x400:
                    raise OriginUnavailable('tk-reparse-source', path=path)
            paths.extend(Path(folder) / name for name in names)
            if len(paths) > 8192 or time.monotonic() - started > 30:
                raise OriginUnavailable('tk-source-limit')
        if not (base / 'tcl/tcl8.6/init.tcl').is_file():
            raise OriginUnavailable('tk-source-unavailable')
        for path in paths:
            # _pin_file already holds every directory from the drive root with
            # FILE_LIST_DIRECTORY and deny-write/delete sharing.
            raw = pins.enter_context(_pin_file(path))
            total += len(raw)
            if total > 64 * 1024 * 1024:
                raise OriginUnavailable('tk-source-limit')
        yield base


def _controlled_root(root):
    root = exchange._root(root)
    base = _REPO / 'files/dev-work/p05b-stage4c'
    if (not root.is_relative_to(base) or root == base
            or not root.relative_to(base).parts[0].startswith('stage4d2d-m1-')):
        raise OriginUnavailable('controlled-harness-root-required')
    for path in (root, *root.parents):
        if os.path.lexists(path) and path.lstat().st_file_attributes & 0x400:
            raise OriginUnavailable('source-reparse-ancestry', path=path)
    return root


def _runtime_sources(base):
    """Bounded installed stdlib closure, never descend into site-packages."""
    started, paths, total = time.monotonic(), [], 0
    for folder, dirs, names in os.walk(base / 'Lib', followlinks=False):
        if Path(folder) == base / 'Lib':
            dirs[:] = [name for name in dirs if name != 'site-packages']
        for name in [*dirs, *names]:
            path = Path(folder) / name
            if path.lstat().st_file_attributes & 0x400:
                raise OriginUnavailable('runtime-reparse-source', path=path)
            total += 1
        paths.extend(Path(folder) / name for name in names if Path(name).suffix in ('.py', '.pyc', '.pyd', '.dll'))
        if total > 8192 or time.monotonic() - started > 30:
            raise OriginUnavailable('runtime-source-inventory-limit')
    return paths


@dataclass(frozen=True)
class ReadOnlyContext:
    """Registered lifetime-bound capability, never an observer/command adapter."""
    root: Path
    interpreter: Path
    session: str
    source_digests: tuple


@contextlib.contextmanager
def issue_controlled_context(root):
    """Fixed real source/manifest closure, main Python, disposable *data* only.

    No production-app root is eligible in M1. This is a separate issuer, not the
    for_test issuer, and accepts no fixture code, health facts or probe runner.
    It uses the actual Planner/observe, with side effects refused by the worker.
    """
    root = _controlled_root(root)
    with contextlib.ExitStack() as pins:
        origin = pins.enter_context(qualify_main_origin())
        cfg = pins.enter_context(_pin_file(origin.main_prefix / 'pyvenv.cfg'))
        values = dict(line.split('=', 1) for line in cfg.decode('utf-8').splitlines() if '=' in line)
        values = {k.strip().lower(): v.strip() for k, v in values.items()}
        if (values.get('include-system-site-packages') != 'false'
                or Path(values.get('home', '')) != origin.base_prefix
                or Path(values.get('executable', '')) != origin.base_prefix / 'python.exe'
                or values.get('version') != '.'.join(map(str, sys.version_info[:3]))):
            raise OriginUnavailable('main-venv-configuration')
        executable_image, birth = process_identity(os.getpid())
        if executable_image != origin.base_prefix / 'python.exe':
            raise OriginUnavailable('main-native-image')
        # Pin installed CPython executable/runtime and every existing native
        # extension in its fixed DLL directory. Site-packages are never admitted.
        runtime = [origin.interpreter, origin.base_prefix / 'python.exe',
                   origin.base_prefix / 'python312.dll']
        runtime += sorted(origin.base_prefix.glob('*.dll'))
        runtime += sorted((origin.base_prefix / 'DLLs').glob('*.pyd'))
        runtime += sorted((origin.base_prefix / 'DLLs').glob('*.dll'))
        if len(runtime) > 128:
            raise OriginUnavailable('runtime-import-layout')
        runtime += _runtime_sources(origin.base_prefix)
        runtime = list(dict.fromkeys(runtime))
        if any((origin.base_prefix / name).exists() for name in
               ('python312.zip', 'python312._pth', 'python._pth')):
            raise OriginUnavailable('runtime-import-layout')
        digests = []
        runtime_bytes = 0
        for path in runtime:
            raw = pins.enter_context(_pin_file(path))
            runtime_bytes += len(raw)
            if runtime_bytes > 256 * 1024 * 1024:
                raise OriginUnavailable('runtime-source-byte-limit')
            digests.append((str(path), hashlib.sha256(raw).hexdigest()))
        root.mkdir(parents=True, exist_ok=False)
        app, scripts = root / 'app', root / 'app/scripts'
        scripts.mkdir(parents=True)
        (app / 'files').mkdir()
        for rel in _CODE:
            raw = pins.enter_context(_pin_file(_REPO / 'scripts' / rel))
            target = scripts / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            copied = pins.enter_context(_pin_file(target))
            if copied != raw:
                raise OriginUnavailable('source-copy-changed')
            digests.append((str(target), hashlib.sha256(raw).hexdigest()))
        manifest = dict(parent_pid=os.getpid(), parent_birth=birth,
            main=str(origin.main_prefix), base=str(origin.base_prefix),
            interpreter=str(origin.interpreter), runtime=digests[:len(runtime)],
            sources=digests[len(runtime):])
        path = app / 'readonly-origin.json'
        path.write_bytes(store.canonical(manifest))
        pins.enter_context(_pin_file(path))
        context = ReadOnlyContext(root, origin.interpreter, proto.new_token(), tuple(digests))
        _ISSUED[id(context)] = context
        _RUNS[id(context)] = []
        try:
            yield context
        finally:
            # No source handle can be dropped while an issued child remains live.
            for run in _RUNS.pop(id(context)):
                if run._started and run.result() is None:
                    run.cancel()
                    run.wait()
            _ISSUED.pop(id(context), None)


class ReadOnlyPlanningRun(supervisor.FakePlanningRun):
    """Reuse qualified terminal arbitration, never its for_test launch factory."""
    @classmethod
    def create(cls, context, *, components, engine_action='none', timeout_s=10):
        if type(context) is not ReadOnlyContext or _ISSUED.get(id(context)) is not context:
            raise OriginUnavailable('issued-readonly-context-required')
        planning = wire.PlanningRequest(wire.encode_planning_request(request_id=proto.new_token(),
            intended_request_id=proto.new_token(), session=context.session, plan_id=proto.new_token(),
            components=list(components), engine_action=engine_action, issued_utc=proto.utc_text(time.time())))
        self = object.__new__(cls)
        self.context, self.root, self.repo = context, context.root, context.root / 'app'
        self.planning, self.session = planning, context.session
        self._candidate = None
        self._configure(now=time.time, on_event=None,
            timeout_s=supervisor._budget(timeout_s, 60), cleanup_s=2, join_s=1)
        exchange.publish_planning_request(self.repo, planning.raw, session=self.session,
            request_id=planning.to_json()['request_id'])
        self.result_path = self.repo / exchange.EXCHANGE_ROOT / planning.to_json()['request_id'] / 'result.json'
        _RUNS[id(context)].append(self)
        return self

    def _spawn_fake(self):
        if _ISSUED.get(id(self.context)) is not self.context:
            raise OriginUnavailable('issued-readonly-context-required')
        _controlled_root(self.root)
        for path, digest in self.context.source_digests:
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                raise OriginUnavailable('source-identity-changed')
        scripts = self.repo / 'scripts'
        files = {scripts / rel for rel in _CODE}
        directories = {scripts} | {p for f in files for p in f.parents if p.is_relative_to(scripts)}
        for directory in directories:
            for entry in directory.iterdir():
                if entry not in files | directories or entry.lstat().st_file_attributes & 0x400:
                    raise OriginUnavailable('unexpected-import-source')
        request = exchange._read_published_planning_request(self.repo, session=self.session,
            request_id=self.planning.to_json()['request_id'])
        if request.raw != self.planning.raw:
            raise OriginUnavailable('request-identity-changed')
        env = {'SystemRoot': str(system_directory().parent), 'TEMP': str(self.root), 'TMP': str(self.root),
               'TMPDIR': str(self.root), 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
        return qwen3_process.spawn([str(self.context.interpreter), '-I', '-B', '-S', '-c', _BOOTSTRAP,
            self.planning.to_json()['request_id'], self.session], require_job=True,
            cwd=str(scripts), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0)

    def _read_exchange(self):
        if self._stderr.count:
            self._error('unexpected-stderr')
        if self._events != 3 or self._phase != 2:
            self._error('planning-events-incomplete')
        self._candidate = exchange._read_untrusted_planning_candidate(self.repo, planning=self.planning,
            session=self.session, now=self._now)
        return self._candidate.raw_result

    def candidate(self):
        with self._lock:
            return self._candidate if self._outcome is not None and self._outcome.accepted else None
