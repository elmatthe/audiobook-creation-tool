"""Scoped, Windows-protected wheel consumption. No production acquisition entrypoint.

Only a live spent transfer operation under InstallLock can mint a package capability.
Private copies are held from CREATE_NEW through the complete consumer lifetime: no
pre-existing writable handle/mapping, replacement, or writable cache alias is trusted.
"""
from __future__ import annotations

import contextlib
import ctypes
import hashlib
import os
import stat
import sys
import threading
import time
from pathlib import Path

from shared import artifact_store as store
from shared import artifact_transfer as transfer
from shared import optional_setup_protocol as proto
from tts import qwen3_package_manifest as qm

_LIVE = {}
_QUARANTINED = []
NATIVE_COMPLETIONS = []


class VerifiedPackageSet:
    """Opaque, scope-limited capability; neither a receipt nor a constructible record."""
    __slots__ = ()

    def __new__(cls):
        raise store.ArtifactError('package capabilities are minted only by sealed_packages')


@contextlib.contextmanager
def _private_file(repo, path):
    """Create once and keep the SAME file object open, denying writes/deletes to others.

    READ|WRITE access is retained by this trusted writer, sharing READ only. Readers
    (including pip's CRT opens) may share our write access without gaining any themselves.
    Directory handles deny reparse changes/renaming for the full lifetime.
    """
    from ctypes import wintypes
    import msvcrt

    with store.boundary(repo, path):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        # ctypes I/O must participate in the existing raw production-write tripwire.
        sys.audit('open', str(path), 'x+b', os.O_CREAT | os.O_EXCL | os.O_RDWR)
        handle = create(str(path), 0xc0000000, 1, None, 1, 0x00200000, None)
        store.require(handle != ctypes.c_void_p(-1).value, 'cannot seal private package file')
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)
            raise
        with os.fdopen(fd, 'w+b') as stream:
            os.set_inheritable(stream.fileno(), False)
            info = os.fstat(stream.fileno())
            current = path.stat(follow_symlinks=False)
            store.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                          and (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino),
                          'unsafe private package file')
            yield stream


def _lock_required(repo):
    from tts import qwen3_setup as setup, qwen3_runtime as rt
    store.require(setup.InstallLock.held_by_this_thread() and Path(repo) == rt.repo_root(),
                  'package consumption requires the operation InstallLock')


def _matching_rows(object_store, reviewed):
    reviewed = qm._checked_manifest(reviewed)
    terms = object_store.catalog.terms
    store.require(terms['engine_action'] in ('install-missing', 'rebuild-canonical'),
                  'model-only consent cannot consume engine packages')
    # Reconstruct the independently checked catalog, never trust a receipt/dataclass. Production purpose
    # never reaches here (sox refuses it); either qualification purpose must match its exact sox source.
    purpose = object_store.catalog.purpose
    store.require(purpose in (*qm.LOCAL_SUPPLY_PURPOSES, qm.PUBLISHED_SUPPLY_PURPOSE),
                  'package consumption requires an explicit qualification purpose')
    store.Catalog(terms, package_manifest=reviewed, purpose=purpose)
    rows = [a for a in terms['artifacts'] if a['kind'] != 'model']
    store.require(len(rows) == 89 and len(reviewed.wheels) == 89
                  and {a['name'] for a in rows} == {a.name for a in reviewed.wheels},
                  'complete 89-wheel dependency closure required')
    lock = qm.effective_lock(reviewed)
    store.require(hashlib.sha256(lock).hexdigest() == terms['effective_lock_sha256'],
                  'effective lock identity mismatch')
    for wheel in reviewed.wheels:
        tags = qm.wheel_tags(wheel.filename, wheel.name, wheel.version)
        store.require(tags == wheel.tags and any(qm._compatible(t) for t in tags),
                      'incompatible consumable wheel')
    return rows, lock


def _operation_required(object_store, operation):
    store.require(type(operation) is transfer.TransferOperation and operation.ledger.store is object_store
                  and operation.consent.terms == store.canonical(object_store.catalog.terms)
                  and operation.state['status'] == 'open', 'live spent package operation required')
    _lock_required(object_store.repo)


@contextlib.contextmanager
def sealed_packages(object_store, operation, reviewed, *, cancelled=lambda: False):
    """Revalidate ALL 89 objects, copy and pin final wheels + effective lock, then mint.

    Copies consume additional disclosed disk; failures leave disposable staging, never
    delete an engine. Nothing is acquired here, and no pip cache grants verification.
    """
    from tts import qwen3_setup as setup
    _operation_required(object_store, operation)
    rows, lock = _matching_rows(object_store, reviewed)
    for row in rows:
        setup._check_cancel(cancelled)
        object_store.verify(row['id'], check_cancel=lambda: setup._check_cancel(cancelled))
    folder = object_store.root / 'consumption' / proto.new_token()
    wheels = folder / 'wheels'
    store.mkdirs(object_store.repo, wheels)
    with operation.exclusive(), contextlib.ExitStack() as held:
        # Pin the empty view before creating any consumable file.
        held.enter_context(store.boundary(object_store.repo, wheels / 'sentinel'))
        files = []
        for row in rows:
            setup._check_cancel(cancelled)
            path = wheels / row['filename']
            stream = held.enter_context(_private_file(object_store.repo, path))
            blob, _ = object_store._paths(row['id'])
            with store.checked_open(object_store.repo, blob, 'rb') as source:
                remaining = row['size']
                while remaining:
                    setup._check_cancel(cancelled)
                    block = source.read(min(store.BLOCK, remaining))
                    store.require(bool(block), 'package changed during staging')
                    stream.write(block)
                    remaining -= len(block)
            stream.flush()
            os.fsync(stream.fileno())
            files.append((path, stream, row))
        lock_path = folder / 'effective-requirements.txt'
        lock_stream = held.enter_context(_private_file(object_store.repo, lock_path))
        lock_stream.write(lock)
        lock_stream.flush()
        os.fsync(lock_stream.fileno())
        cap = object.__new__(VerifiedPackageSet)
        record = {'store': object_store, 'operation': operation, 'reviewed': reviewed,
                  'thread': threading.get_ident(), 'files': files, 'lock': lock,
                  'cancelled': cancelled,
                  'lock_stream': lock_stream, 'lock_path': lock_path, 'wheels': wheels}
        _LIVE[cap] = record
        try:
            checked(cap, operation, cancelled=cancelled)
            yield cap
        finally:
            del _LIVE[cap]  # revoke BEFORE closing the handles, including cancel/exception
            if record.get('uncertain_consumer'):
                # Do not unseal files merely because the OS could not prove that
                # the consuming job is empty. There is no automatic reuse/release.
                _QUARANTINED.append(held.pop_all())


def checked(capability, operation, *, cancelled=lambda: False):
    """Internal consumer check; paths and hashes supplied by callers confer no authority."""
    from tts import qwen3_setup as setup, qwen3_runtime as rt
    record = _LIVE.get(capability) if type(capability) is VerifiedPackageSet else None
    store.require(record is not None and record['thread'] == threading.get_ident()
                  and record['operation'] is operation, 'inactive/forged package capability')
    object_store = record['store']
    _operation_required(object_store, operation)
    _, lock = _matching_rows(object_store, record['reviewed'])
    store.require(rt.requirements_path().read_bytes().replace(b'\r\n', b'\n') ==
                  record['reviewed']._requirements, 'original requirements changed before consumption')
    store.require(lock == record['lock'], 'effective lock changed before consumption')
    record['lock_stream'].seek(0)
    store.require(record['lock_stream'].read() == lock, 'consumable lock changed')
    expected = {path.name for path, _, _ in record['files']}
    store.require(len(record['files']) == 89 and expected == {
        a.filename for a in record['reviewed'].wheels}, 'incomplete protected wheel view')
    store.require({p.name for p in record['wheels'].iterdir()} == expected,
                  'mutable alternative in wheel view')
    for path, stream, row in record['files']:
        setup._check_cancel(cancelled)
        store.require(not stream.closed, 'closed package protection')
        info, current = os.fstat(stream.fileno()), path.stat(follow_symlinks=False)
        store.require(not store.venv_layout.is_link(path) and info.st_nlink == 1
                      and (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino),
                      'consumable wheel identity changed')
        stream.seek(0)
        store.require(row == object_store.catalog.artifact(row['id'])
                      and path == record['wheels'] / row['filename'], 'protected file/catalog mismatch')
        store.verify_stream(stream, row, check_cancel=lambda: setup._check_cancel(cancelled))
    return record


# The exact same bootstrap is used by disposable native qualification and scoped pip.
# It prevents egress and source-build subprocesses even if ambient pip configuration
# were to change. Flags/lock still constrain resolution; this hook is another boundary.
OFFLINE_BOOTSTRAP = '''import atexit, json, runpy, sys
refused = []
def offline(event, args):
    if (event.startswith('socket.') and event != 'socket.gethostname') or event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'):
        refused.append(event)
        raise PermissionError('offline pip refused network/process: ' + event)
sys.addaudithook(offline)
atexit.register(lambda: print('@@OFFLINE ' + json.dumps(refused)))
sys.argv = ['pip', *sys.argv[1:]]
runpy.run_module('pip', run_name='__main__')
'''


def pip_command(python, capability, operation, *, cancelled=lambda: False):
    record = checked(capability, operation, cancelled=cancelled)
    command = _pip_command(python, record['wheels'], record['lock_path'],
                           [(p, row['sha256']) for p, _, row in record['files']])
    import subprocess
    store.require(len(subprocess.list2cmdline(command)) < 32767, 'offline command exceeds Windows limit')
    return command


def _pip_command(python, wheels, lock_path, paths):
    # Explicit roots prevent a late-added alternate candidate from being selected
    # through --find-links. Each root is the SAME continuously held file object.
    store.require(all(p.parent == wheels and p.suffix == '.whl' for p, _ in paths),
                  'offline pip accepts only wheel roots in the protected view')
    return [str(python), '-I', '-B', '-c', OFFLINE_BOOTSTRAP, 'install', '--isolated',
            '--require-virtualenv', '--no-index', '--find-links', str(wheels), '--require-hashes',
            '--no-deps', '--only-binary=:all:', '--no-cache-dir', '--no-input',
            '--disable-pip-version-check', '-r', str(lock_path),
            *('file:./' + p.name + '#sha256=' + digest for p, digest in paths)]


def consumer_finished(proc):
    """Retain all pins until the actual Windows job is PROVED empty, even on cancel."""
    from tts import qwen3_setup as setup
    job = getattr(proc, 'act_job', None)
    try:
        store.require(job is not None, 'offline consumer has no containment job')
        deadline = time.monotonic() + 15
        while job.accounting()[0]:
            job.terminate()
            store.require(time.monotonic() < deadline, 'offline consumer job did not become empty')
            time.sleep(0.02)
        NATIVE_COMPLETIONS.append({'pid': proc.pid, 'active': 0, 'members': job.accounting()[1]})
    except (OSError, store.ArtifactError) as exc:
        for record in _LIVE.values():
            if record['thread'] == threading.get_ident():
                record['uncertain_consumer'] = True
        raise setup.SetupError('Cannot prove offline pip stopped; package protections retained: ' + str(exc)) from exc
