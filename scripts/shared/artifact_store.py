"""Verified artifact foundation; deliberately unused by the production installer.

Catalog input is independently trusted v3 terms, never a received consent or a freshly hashed file.
Package rows additionally require the code-pinned reviewed manifest. Receipts are point-in-time proofs,
not consumption capabilities: there is intentionally no installer path API. Stage 4B-3 must revalidate
and seal inputs at consumption. Windows directory handles deny renames/deletion at I/O boundaries;
unqualified platforms fail closed. This does not defend against an administrator rewriting file bytes.
"""
from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from shared import optional_setup_protocol as proto
from shared import optional_setup_v3 as v3
from shared import venv_layout

BLOCK = 64 * 1024
STORE = Path('files/runtime-data/artifact-store-v1')


class ArtifactError(ValueError):
    """Unapproved identity, unsafe path, unavailable content or publication conflict."""


def require(condition, message):
    if not condition:
        raise ArtifactError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


class Catalog:
    """Explicit authority boundary. Caller supplies fresh independently derived terms under its lease.

    Model identities come from that trusted planner; this class cannot authorize arbitrary received JSON.
    Reviewed package mapping is checked independently, including the local-only sox derivative.
    """
    def __init__(self, trusted_terms, *, package_manifest=None, purpose='fresh-machine'):
        terms = v3.validate_terms(trusted_terms)
        packages = [a for a in terms['artifacts'] if a['kind'] != 'model']
        if packages:
            from tts import qwen3_package_manifest as qm
            reviewed = qm._checked_manifest(package_manifest)
            require(terms['manifest_sha256'] == reviewed.content_sha256
                    and terms['runtime_lock_sha256'] == qm.ORIGINAL_LOCK_SHA256
                    and terms['effective_lock_sha256'] == hashlib.sha256(qm.effective_lock(reviewed)).hexdigest(),
                    'package manifest/lock identity mismatch')
            by_name = {a.name: a for a in reviewed.wheels}
            for row in packages:
                approved = by_name.get(row['name'])
                require(approved is not None and row['kind'] == 'package', 'unapproved package artifact')
                require((row['version'], row['filename'], row['size'], row['sha256'], row['source']['url']) ==
                        (approved.version, approved.filename, approved.size, approved.sha256, approved.source_url),
                        'package differs from reviewed artifact')
                if approved.name == 'sox':
                    require(purpose in ('controlled-local-development', 'synthetic-qualification'),
                            'BLOCKED: portable sox supply pending; existing local development only')
                    derivative = row['derivative']
                    require(row['source'] == {'kind': 'local-derived', 'url': None,
                                              'revision': qm.SOX_SOURCE_SHA256}
                            and derivative == {'source_filename': 'sox-1.5.0.tar.gz',
                                               'source_sha256': qm.SOX_SOURCE_SHA256, 'source_size': 63905,
                                               'build_inputs_sha256': hashlib.sha256(canonical(
                                                   json.loads(reviewed._document)['build_only'])).hexdigest(),
                                               'output_sha256': qm.SOX_WHEEL_SHA256},
                            'unapproved sox derivation')
                else:
                    require(row['source']['kind'] == 'pinned-https' and row['derivative'] is None,
                            'unapproved package source/derivative')
        self._terms = canonical(terms)

    @property
    def terms(self):
        return json.loads(self._terms)

    @property
    def artifacts(self):
        return self.terms['artifacts']

    def artifact(self, artifact_id):
        found = [a for a in self.artifacts if a['id'] == artifact_id]
        require(len(found) == 1, 'unknown artifact')
        return found[0]

    def identity(self, artifact_id):
        row = self.artifact(artifact_id)
        identity = {k: v for k, v in row.items() if k not in (
            'verified_reuse_bytes', 'expected_new_bytes', 'retry_headroom_bytes', 'max_payload_bytes')}
        return {'schema': 'act-verified-artifact', 'version': 1,
                'manifest_sha256': self.terms['manifest_sha256'], 'artifact': identity}


@contextlib.contextmanager
def boundary(repo: Path, path: Path, *, _publication=False):
    """Pin all parent directories against replacement while the caller performs actual I/O.

    Ordinary I/O denies FILE_SHARE_DELETE/WRITE. Handle-relative publication has the documented
    exception on its destination directory; its ancestors remain pinned against both operations.
    Leaf links are rejected as well; readers compare the opened file identity before trusting bytes.
    """
    repo, path = Path(repo).absolute(), Path(path).absolute()
    require('..' not in path.parts and path.is_relative_to(repo) and path != repo, 'path escape')
    require(repo.is_dir() and not venv_layout.is_link(repo), 'unsafe repository root')
    require(os.name == 'nt', 'directory pinning is not qualified on this platform')
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    handles = []
    try:
        walked = repo
        parts = (None, *path.parent.relative_to(repo).parts)
        for index, part in enumerate(parts):
            if part is not None:
                walked /= part
            require(not venv_layout.is_link(walked) and walked.is_dir(), 'linked/missing parent directory')
            # FILE_LIST_DIRECTORY participates in sharing checks; FILE_READ_ATTRIBUTES alone does not.
            sharing = 3 if _publication and index == len(parts) - 1 else 1
            handle = create(str(walked), 1, sharing, None, 3, 0x02200000, None)
            require(handle != ctypes.c_void_p(-1).value, 'cannot pin directory boundary')
            handles.append(handle)
            require(not venv_layout.is_link(walked) and walked.resolve() == walked, 'directory escape')
        require(not venv_layout.is_link(path) and path.resolve().is_relative_to(repo), 'linked/path escape')
        yield handles[-1]
    finally:
        for handle in reversed(handles):
            close(handle)


def mkdirs(repo, folder):
    repo, folder = Path(repo).absolute(), Path(folder).absolute()
    require(folder.is_relative_to(repo), 'directory escape')
    walked = repo
    for part in folder.relative_to(repo).parts:
        walked /= part
        with boundary(repo, walked):
            walked.mkdir(exist_ok=True)
            require(walked.is_dir(), 'not a directory')


@contextlib.contextmanager
def checked_open(repo, path, mode):
    require(mode in ('rb', 'xb'), 'unsupported file operation')
    with boundary(repo, path):
        with open(path, mode) as stream:
            info = os.fstat(stream.fileno())
            current = os.stat(path, follow_symlinks=False)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino)
                    and not venv_layout.is_link(path), 'linked/replaced/nonregular file')
            yield stream


def _rename_once(source_handle, destination, parent_handle):
    """Handle-relative NT rename, ReplaceIfExists=False, with pinned parent handles.

    Path-based rename/link opens the target directory for write and conflicts with those pins.
    RootDirectory uses the already pinned directory, without traversing its name again.
    """
    from ctypes import wintypes

    class RenameInfo(ctypes.Structure):
        _fields_ = [('replace', ctypes.c_ubyte), ('root', wintypes.HANDLE),
                    ('length', wintypes.ULONG), ('name', wintypes.WCHAR * 1)]

    class IOStatus(ctypes.Structure):
        _fields_ = [('status', ctypes.c_void_p), ('information', ctypes.c_size_t)]

    name = destination.name.encode('utf-16-le')
    storage = ctypes.create_string_buffer(RenameInfo.name.offset + len(name))
    info = ctypes.cast(storage, ctypes.POINTER(RenameInfo)).contents
    info.replace, info.root, info.length = 0, parent_handle, len(name)
    ctypes.memmove(ctypes.addressof(storage) + RenameInfo.name.offset, name, len(name))
    rename = ctypes.WinDLL('ntdll').NtSetInformationFile
    rename.argtypes = [wintypes.HANDLE, ctypes.POINTER(IOStatus), ctypes.c_void_p,
                       wintypes.ULONG, ctypes.c_int]
    rename.restype = wintypes.LONG
    status = rename(source_handle, ctypes.byref(IOStatus()), storage, len(storage), 10)
    require(status >= 0, f'atomic publication refused (NTSTATUS {status & 0xffffffff:08x})')


def publish(repo, temporary, destination):
    """Only private temporaries can be atomically renamed; never replace or copy as a fallback."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    # Capture the source while ALL directories deny write/delete sharing. The source handle
    # then denies byte mutation/deletion independently while the destination is pinned below.
    with boundary(repo, temporary):
        handle = create(str(temporary), 0x80010000, 1, None, 3, 0x00200000, None)
        require(handle != ctypes.c_void_p(-1).value, 'cannot open private publication source')
        try:
            require(not venv_layout.is_link(temporary) and temporary.stat().st_nlink == 1,
                    'linked publication source')
        except BaseException:
            close(handle)
            raise
    try:
        # NT needs write sharing on this directory for rename. RootDirectory is an existing
        # handle: an in-place reparse on that directory cannot redirect the relative leaf name.
        # Its ancestors still deny write/delete sharing, and it still denies delete sharing.
        with boundary(repo, destination, _publication=True) as target_parent:
            # Native rename must participate in the same audit/tripwire boundary as os.rename.
            sys.audit('os.rename', str(temporary), str(destination), -1, -1)
            _rename_once(handle, destination, target_parent)
    finally:
        close(handle)


def write_once(repo, path, data):
    temporary = path.with_name('.' + proto.new_token() + '.tmp')
    with checked_open(repo, temporary, 'xb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    publish(repo, temporary, path)


def read_small(repo, path):
    with checked_open(repo, path, 'rb') as handle:
        require(os.fstat(handle.fileno()).st_size <= v3.MAX_MESSAGE_BYTES, 'oversized metadata/ledger')
        return handle.read(v3.MAX_MESSAGE_BYTES + 1)


def verify_stream(stream, artifact, *, check_cancel=lambda: None):
    require(os.fstat(stream.fileno()).st_size == artifact['size'], 'wrong artifact size')
    digest, total = hashlib.sha256(), 0
    while block := stream.read(min(BLOCK, artifact['size'] - total + 1)):
        check_cancel()
        total += len(block)
        require(total <= artifact['size'], 'artifact grew during verification')
        digest.update(block)
    require(total == artifact['size'] and digest.hexdigest() == artifact['sha256'], 'wrong artifact size/hash')


@dataclass(frozen=True)
class Verification:
    object_id: str
    sha256: str
    size: int
    requires_revalidation: bool = True


class ArtifactStore:
    """Repository runtime data, outside pip cache/tmp cleanup. No trusted-path consumption API."""
    def __init__(self, repo, catalog: Catalog):
        self.repo = Path(repo).absolute()
        require(type(catalog) is Catalog, 'explicit trusted catalog required')
        self.catalog = catalog
        self.root = self.repo / STORE

    def _paths(self, artifact_id):
        identity = self.catalog.identity(artifact_id)
        key = hashlib.sha256(canonical(identity)).hexdigest()
        return self.root / 'objects' / (key + '.blob'), self.root / 'objects' / (key + '.json')

    def verify(self, artifact_id, *, check_cancel=lambda: None):
        artifact = self.catalog.artifact(artifact_id)
        blob, metadata = self._paths(artifact_id)
        try:
            require(read_small(self.repo, metadata) == canonical(self.catalog.identity(artifact_id)),
                    'metadata identity mismatch')
            with checked_open(self.repo, blob, 'rb') as stream:
                verify_stream(stream, artifact, check_cancel=check_cancel)
        except OSError as exc:
            raise ArtifactError(f'artifact unavailable: {exc}') from None
        return Verification(blob.stem, artifact['sha256'], artifact['size'])

    def new_partial(self):
        folder = self.root / 'incomplete'
        mkdirs(self.repo, folder)
        return folder / (proto.new_token() + '.part')

    def promote(self, artifact_id, partial):
        artifact = self.catalog.artifact(artifact_id)
        require(partial.parent == self.root / 'incomplete'
                and re.fullmatch(r'[a-f0-9]{32}\.part', partial.name) is not None,
                'unexpected publication source')
        with checked_open(self.repo, partial, 'rb') as stream:
            verify_stream(stream, artifact)
        blob, metadata = self._paths(artifact_id)
        mkdirs(self.repo, blob.parent)
        # An orphan blob/metadata is a conflict too. Never repair it by overwriting.
        with boundary(self.repo, blob), boundary(self.repo, metadata):
            require(not os.path.lexists(blob) and not os.path.lexists(metadata), 'existing object conflict')
        publish(self.repo, partial, blob)
        write_once(self.repo, metadata, canonical(self.catalog.identity(artifact_id)))
        return self.verify(artifact_id)

    def import_local(self, artifact_id, candidate, *, source_url):
        artifact = self.catalog.artifact(artifact_id)
        require(source_url == artifact['source']['url'], 'artifact source mismatch')
        blob, metadata = self._paths(artifact_id)
        if os.path.lexists(blob) or os.path.lexists(metadata):
            return self.verify(artifact_id)  # reuse only after complete revalidation, no duplicate copy
        partial = self.new_partial()
        try:
            with checked_open(self.repo, Path(candidate).absolute(), 'rb') as source:
                require(os.fstat(source.fileno()).st_size == artifact['size'], 'wrong local size')
                with checked_open(self.repo, partial, 'xb') as target:
                    remaining = artifact['size']
                    while remaining:
                        block = source.read(min(BLOCK, remaining))
                        require(bool(block), 'interrupted local candidate')
                        target.write(block)
                        remaining -= len(block)
                    target.flush()
                    os.fsync(target.fileno())
            return self.promote(artifact_id, partial)
        except OSError as exc:
            raise ArtifactError(f'local artifact unavailable: {exc}') from None
