"""Fixed, bounded Windows v3 exchange. No worker, planner, consent minting or spending.

Only the trusted caller chooses the repository root. IDs/bytes come through the
accepted wire validators. A final marker is publication order, not a multi-file
transaction or execution authority. Interrupted directories are never repaired.
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import stat
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from shared import artifact_store as store
from shared import optional_setup_protocol as proto
from shared import optional_setup_wire_v3 as wire

EXCHANGE_ROOT = Path('files/runtime-data/optional-setup')
_CAPS = {'request.json': wire.MAX_CONTROL_BYTES, 'result.json': wire.MAX_CONTROL_BYTES,
         'plan.json': wire.MAX_DISCLOSURE_BYTES, 'consent.json': wire.MAX_CONSENT_BYTES}
_PLANNING_FILES = {'request.json', 'plan.json', 'result.json'}
_CONFIRMATION_FILES = {'plan.json', 'consent.json', 'request.json'}
REFUSED = 'v3-exchange-refused'


class ExchangeError(proto.ProtocolError):
    def __init__(self, message):
        super().__init__(REFUSED, message)


def _require(condition, message):
    if not condition:
        raise ExchangeError(message)


@contextlib.contextmanager
def _errors():
    try:
        yield
    except (OSError, store.ArtifactError) as exc:
        raise ExchangeError(f'Exchange unavailable or unsafe: {exc}') from None


def _root(repo):
    _require(os.name == 'nt', 'Windows directory pinning is unavailable on this platform')
    _require(isinstance(repo, (str, Path)), 'trusted repository root required')
    path = Path(repo)
    _require(path.is_absolute() and path == path.absolute() and '..' not in path.parts
             and len(path.drive) == 2 and path.drive[1] == ':'
             and all(not p.endswith(('.', ' ')) and ':' not in p for p in path.parts[1:]),
             'repository root must be an unambiguous normalized absolute drive path')
    return path


def _path(repo, request_id, name):
    _require(type(request_id) is str and proto._TOKEN.fullmatch(request_id) is not None, 'invalid request ID')
    _require(type(name) is str and name in _CAPS, 'only fixed exchange filenames are allowed')
    return repo / EXCHANGE_ROOT / request_id / name


def _kernel():
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _handle_id(handle):
    """FILE_ID_INFO preserves the full 128-bit Windows object identity."""
    from ctypes import wintypes

    class FileId(ctypes.Structure):
        _fields_ = [('volume', ctypes.c_ulonglong), ('identifier', ctypes.c_ubyte * 16)]

    query = _kernel().GetFileInformationByHandleEx
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    query.restype = wintypes.BOOL
    info = FileId()
    _require(query(handle, 18, ctypes.byref(info), ctypes.sizeof(info)), 'cannot prove opened directory identity')
    return info.volume, bytes(info.identifier)


def _create_directory(path, parent):
    """Exclusive handle-relative create; no mkdir -> reopen identity gap."""
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = [('length', wintypes.USHORT), ('maximum', wintypes.USHORT), ('buffer', wintypes.LPWSTR)]

    class Attributes(ctypes.Structure):
        _fields_ = [('length', wintypes.ULONG), ('root', wintypes.HANDLE),
                    ('name', ctypes.POINTER(UnicodeString)), ('attributes', wintypes.ULONG),
                    ('security', ctypes.c_void_p), ('quality', ctypes.c_void_p)]

    class Status(ctypes.Structure):
        _fields_ = [('status', ctypes.c_void_p), ('information', ctypes.c_size_t)]

    text = ctypes.create_unicode_buffer(path.name)
    name = UnicodeString(len(path.name.encode('utf-16-le')), ctypes.sizeof(text), ctypes.cast(text, wintypes.LPWSTR))
    attributes = Attributes(ctypes.sizeof(Attributes), parent, ctypes.pointer(name), 0x40, None, None)
    create = ctypes.WinDLL('ntdll').NtCreateFile
    create.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG, ctypes.POINTER(Attributes),
                      ctypes.POINTER(Status), ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG,
                      wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
    create.restype = wintypes.LONG
    handle = wintypes.HANDLE()
    sys.audit('os.mkdir', str(path), 0o777, -1)
    # LIST_DIRECTORY | READ_ATTRIBUTES | SYNCHRONIZE; share read/write but NOT
    # delete; FILE_CREATE, DIRECTORY_FILE | SYNCHRONOUS_IO | OPEN_REPARSE_POINT.
    status = create(ctypes.byref(handle), 0x100081, ctypes.byref(attributes), ctypes.byref(Status()),
                    None, 0x10, 3, 2, 0x200021, None, 0)
    _require(status >= 0, f'exclusive request directory refused (NTSTATUS {status & 0xffffffff:08x})')
    return handle.value


@dataclass(frozen=True)
class _Folder:
    repo: Path
    path: Path
    identity: tuple


@contextlib.contextmanager
def _folder(repo, request_id, *, create=False):
    with _errors():
        repo = _root(repo)
        path = _path(repo, request_id, 'request.json').parent
        if create:
            store.mkdirs(repo, repo / EXCHANGE_ROOT)
        # All ancestors remain pinned for the entire operation. The request
        # directory denies delete sharing; only native relative publication
        # needs its write-sharing exception. Individual path opens add a strict
        # pin, then retain non-writable/non-deletable file handles through use.
        with store.boundary(repo, path) as parent:
            if create:
                handle = _create_directory(path, parent)
                try:
                    yield _Folder(repo, path, _handle_id(handle))
                finally:
                    _kernel().CloseHandle(handle)
            else:
                with store.boundary(repo, path / 'request.json', _publication=True) as handle:
                    yield _Folder(repo, path, _handle_id(handle))


@contextlib.contextmanager
def _pinned(folder, path, *, publication=False):
    with store.boundary(folder.repo, path, _publication=publication) as parent:
        _require(_handle_id(parent) == folder.identity, 'request directory identity changed')
        yield parent


def _entries(folder, expected):
    with _pinned(folder, folder.path / 'request.json'):
        names = set()
        with os.scandir(folder.path) as entries:
            for entry in entries:
                _require(entry.name in expected and entry.name not in names, 'unexpected/incomplete exchange files')
                names.add(entry.name)
        _require(names == expected, 'missing exchange documents or completion marker')


def _snapshot(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink,
            getattr(info, 'st_file_attributes', 0))


def _file_identity(stream, path):
    opened = os.fstat(stream.fileno())
    named = os.stat(path, follow_symlinks=False)
    _require(stat.S_ISREG(opened.st_mode) and stat.S_ISREG(named.st_mode)
             and opened.st_nlink == named.st_nlink == 1
             and not (getattr(opened, 'st_file_attributes', 0) | getattr(named, 'st_file_attributes', 0)) & 0x400
             and (opened.st_dev, opened.st_ino) == (named.st_dev, named.st_ino),
             'linked, replaced, reparse or nonregular exchange file')
    return _snapshot(opened)


@contextlib.contextmanager
def _open_file(folder, path, *, create=False, exclusive=False):
    import msvcrt
    kernel = _kernel()
    with _pinned(folder, path):
        # OPEN_REPARSE_POINT prevents a late leaf link from redirecting open.
        # Readers share READ only: existing/new writers and deletion cannot
        # coexist. Private publication sources remain exclusive until renamed.
        sys.audit('open', str(path), 'xb' if create else 'rb', os.O_CREAT | os.O_EXCL if create else os.O_RDONLY)
        handle = kernel.CreateFileW(str(path), 0xC0010000 if create else 0x80000000,
                                    0 if create or exclusive else 1, None, 1 if create else 3, 0x200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            fd = msvcrt.open_osfhandle(handle, (os.O_RDWR if create else os.O_RDONLY) | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
        try:
            stream = os.fdopen(fd, 'r+b' if create else 'rb', buffering=0)
        except BaseException:
            os.close(fd)
            raise
        try:
            _file_identity(stream, path)
        except BaseException:
            stream.close()
            raise
    try:
        yield stream
    finally:
        stream.close()


def _read(folder, name, stack, *, exclusive=False):
    path = folder.path / name
    stream = stack.enter_context(_open_file(folder, path, exclusive=exclusive))
    with _pinned(folder, path):
        before = _file_identity(stream, path)
        _require(0 < before[2] <= _CAPS[name], 'empty or oversized exchange document')
        raw = stream.read(_CAPS[name] + 1)
        _require(len(raw) == before[2] and _file_identity(stream, path) == before, 'truncated or changed exchange file')
    return raw, (stream, path, before)


def _stable(folder, records, names):
    with _pinned(folder, folder.path / 'request.json'):
        for stream, path, before in records:
            _require(_file_identity(stream, path) == before, 'exchange changed during validation')
        _entries(folder, names)


def _write_once(folder, name, raw):
    import msvcrt
    _require(name in _CAPS and type(raw) is bytes and 0 < len(raw) <= _CAPS[name], 'invalid bounded publication')
    destination = folder.path / name
    temporary = folder.path / ('.' + uuid.uuid4().hex + '.tmp')
    with _open_file(folder, temporary, create=True) as stream:
        _require(stream.write(raw) == len(raw), 'short exchange write')
        stream.flush()
        os.fsync(stream.fileno())
        _require(os.fstat(stream.fileno()).st_size == len(raw), 'incomplete private publication source')
        with _pinned(folder, destination, publication=True) as parent:
            sys.audit('os.rename', str(temporary), str(destination), -1, -1)
            # Reuse accepted handle-relative no-overwrite rename. store.publish
            # reopens its source; this source instead stays exclusive from
            # creation/write through rename, with no close/reopen mutation gap.
            store._rename_once(msvcrt.get_osfhandle(stream.fileno()), destination, parent)
        with _pinned(folder, destination):
            _file_identity(stream, destination)
    # No deletion, replacement, copy fallback or cleanup after uncertainty.


@dataclass(frozen=True)
class PlanningExchange:
    planning: wire.PlanningRequest
    disclosure: wire.Disclosure
    raw_result: bytes


@dataclass(frozen=True)
class UntrustedPlanningCandidate:
    """Validated read-only worker bytes, NOT a retained/displayed original.

    Admission proves request/schema/result binding only. It issues no consent,
    installation instruction or readiness proof. A controller must separately
    accept, display and retain exact bytes before strict original readback.
    """
    raw_disclosure: bytes
    raw_result: bytes


def _read_published_planning_request(repo, *, session, request_id, now=time.time):
    """Read a request-only exchange through bounded, pinned opened handles."""
    with _folder(repo, request_id) as folder, contextlib.ExitStack() as stack:
        control, record = _read(folder, 'request.json', stack)
        checked = wire.decode_planning_request(control, session=session, request_id=request_id, now=now)
        _stable(folder, [record], {'request.json'})
    return checked


def _read_untrusted_planning_candidate(repo, *, planning, session, now=time.time):
    """Non-authorizing candidate admission against an INDEPENDENT trusted request.

    This deliberately cannot substitute for read_planning_exchange's retained
    original. All three documents must exist, bind completely and remain stable.
    """
    _require(type(planning) is wire.PlanningRequest, 'independently retained planning request required')
    p = planning.to_json()
    wire.decode_planning_request(planning.raw, session=session, request_id=p.get('request_id'), now=now)
    with _folder(repo, p['request_id']) as folder, contextlib.ExitStack() as stack:
        result, a = _read(folder, 'result.json', stack)  # completion required first
        control, b = _read(folder, 'request.json', stack)
        plan, c = _read(folder, 'plan.json', stack)
        _require(control == planning.raw, 'candidate differs from independently retained request')
        candidate = wire.decode_disclosure(plan, planning=planning, session=session, now=now)
        _planning_binding(planning, candidate, result, session=session, now=now)
        _stable(folder, [a, b, c], _PLANNING_FILES)
    return UntrustedPlanningCandidate(plan, result)


def publish_planning_request(repo, raw_request, *, session, request_id, now=time.time):
    request = wire.decode_planning_request(raw_request, session=session, request_id=request_id, now=now)
    with _folder(repo, request_id, create=True) as folder:
        _entries(folder, set())
        _write_once(folder, 'request.json', raw_request)
    return request


def _planning_binding(planning, disclosure, raw_result, *, session, now):
    _require(type(planning) is wire.PlanningRequest and type(disclosure) is wire.Disclosure,
             'independently retained planning request and disclosure required')
    checked = wire.decode_disclosure(disclosure.raw, planning=planning, session=session, now=now)
    _require(checked == disclosure, 'retained original Plan bytes changed')
    wire.decode_planning_result(raw_result, expected_disclosure=disclosure, session=session,
                                request_id=planning.to_json()['request_id'], now=now)


def publish_planning_response(repo, *, planning, disclosure, raw_result, session, now=time.time):
    _planning_binding(planning, disclosure, raw_result, session=session, now=now)
    request_id = planning.to_json()['request_id']
    with _folder(repo, request_id) as folder, contextlib.ExitStack() as stack:
        # Exclusive read of the existing control serializes response writers.
        control, a = _read(folder, 'request.json', stack, exclusive=True)
        _require(control == planning.raw, 'planning control differs from retained request')
        _entries(folder, {'request.json'})
        _write_once(folder, 'plan.json', disclosure.raw)
        plan, b = _read(folder, 'plan.json', stack)
        _require(plan == disclosure.raw, 'published original disclosure changed')
        _planning_binding(planning, disclosure, raw_result, session=session, now=now)
        _stable(folder, [a, b], {'request.json', 'plan.json'})
        _write_once(folder, 'result.json', raw_result)  # completion marker LAST
        result, c = _read(folder, 'result.json', stack)
        _require(result == raw_result, 'published planning result changed')
        _stable(folder, [a, b, c], _PLANNING_FILES)
    return PlanningExchange(planning, disclosure, raw_result)


def read_planning_exchange(repo, *, planning, expected_disclosure, session, now=time.time):
    _require(type(planning) is wire.PlanningRequest, 'retained planning request required')
    p = wire._load(planning.raw, wire.MAX_CONTROL_BYTES)
    wire.decode_planning_request(planning.raw, session=session, request_id=p.get('request_id'), now=now)
    with _folder(repo, p['request_id']) as folder, contextlib.ExitStack() as stack:
        result, a = _read(folder, 'result.json', stack)
        control, b = _read(folder, 'request.json', stack)
        plan, c = _read(folder, 'plan.json', stack)
        _require(control == planning.raw and type(expected_disclosure) is wire.Disclosure
                 and plan == expected_disclosure.raw, 'exchange differs from independently retained original')
        _planning_binding(planning, expected_disclosure, result, session=session, now=now)
        _stable(folder, [a, b, c], _PLANNING_FILES)
    return PlanningExchange(planning, expected_disclosure, result)


def prepare_confirmation(repo, *, expected_disclosure, raw_disclosure, raw_consent, raw_request,
                         session, request_id, now=time.time):
    checked = wire.decode_confirmation_request(raw_request, raw_disclosure=raw_disclosure, raw_consent=raw_consent,
        expected_disclosure=expected_disclosure, session=session, request_id=request_id, now=now)
    with _folder(repo, request_id, create=True) as folder, contextlib.ExitStack() as stack:
        _entries(folder, set())
        _write_once(folder, 'plan.json', raw_disclosure)
        _write_once(folder, 'consent.json', raw_consent)
        plan, a = _read(folder, 'plan.json', stack)
        consent, b = _read(folder, 'consent.json', stack)
        wire.decode_confirmation_request(raw_request, raw_disclosure=plan, raw_consent=consent,
            expected_disclosure=expected_disclosure, session=session, request_id=request_id, now=now)
        _stable(folder, [a, b], {'plan.json', 'consent.json'})
        _write_once(folder, 'request.json', raw_request)  # admission marker LAST
        control, c = _read(folder, 'request.json', stack)
        _require(control == raw_request, 'published confirmation control changed')
        _stable(folder, [a, b, c], _CONFIRMATION_FILES)
    return checked


def read_confirmation_exchange(repo, *, expected_disclosure, session, request_id, now=time.time):
    with _folder(repo, request_id) as folder, contextlib.ExitStack() as stack:
        control, a = _read(folder, 'request.json', stack)
        plan, b = _read(folder, 'plan.json', stack)
        consent, c = _read(folder, 'consent.json', stack)
        checked = wire.decode_confirmation_request(control, raw_disclosure=plan, raw_consent=consent,
            expected_disclosure=expected_disclosure, session=session, request_id=request_id, now=now)
        _stable(folder, [a, b, c], _CONFIRMATION_FILES)
    return checked
