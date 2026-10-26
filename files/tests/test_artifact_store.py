"""Synthetic store contracts. No package inventory, installation or model loading."""
import hashlib
import copy
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from shared import artifact_store as store
from test_optional_setup_v3 import model_terms

pytestmark = pytest.mark.usefixtures('production_writes_refused')
DATA = b'abcdefgh'


def terms():
    value = model_terms()
    value['artifacts'][0]['sha256'] = hashlib.sha256(DATA).hexdigest()
    return value


@pytest.fixture
def local(tmp_path):
    catalog = store.Catalog(terms())
    return store.ArtifactStore(tmp_path, catalog), catalog, tmp_path


def candidate(root, data=DATA):
    path = root / 'candidate'
    path.write_bytes(data)
    return path


def test_complete_import_is_verified_without_changing_source(local):
    depot, catalog, root = local
    source = candidate(root)
    artifact = catalog.artifacts[0]['id']
    before = source.stat()
    receipt = depot.import_local(artifact, source, source_url=catalog.artifacts[0]['source']['url'])
    assert receipt.requires_revalidation is True
    assert source.read_bytes() == DATA and source.stat().st_mtime_ns == before.st_mtime_ns
    assert depot.verify(artifact) == receipt
    assert depot.import_local(artifact, source, source_url=catalog.artifacts[0]['source']['url']) == receipt


@pytest.mark.parametrize('data', [b'a', b'ABCDEFGH', b'abcdefghi'])
def test_wrong_bytes_never_publish(local, data):
    depot, catalog, root = local
    with pytest.raises(store.ArtifactError):
        depot.import_local(catalog.artifacts[0]['id'], candidate(root, data),
                           source_url=catalog.artifacts[0]['source']['url'])
    with pytest.raises(store.ArtifactError):
        depot.verify(catalog.artifacts[0]['id'])


def test_unknown_and_wrong_origin_refused(local):
    depot, catalog, root = local
    source = candidate(root)
    for artifact, url in [('unknown', catalog.artifacts[0]['source']['url']),
                          (catalog.artifacts[0]['id'], 'https://substitute.invalid/file')]:
        with pytest.raises(store.ArtifactError):
            depot.import_local(artifact, source, source_url=url)


def test_altered_object_and_metadata_are_revalidated(local):
    depot, catalog, root = local
    artifact = catalog.artifacts[0]
    depot.import_local(artifact['id'], candidate(root), source_url=artifact['source']['url'])
    blob, meta = depot._paths(artifact['id'])
    original = meta.read_bytes()
    blob.write_bytes(b'ABCDEFGH')
    with pytest.raises(store.ArtifactError, match='hash'):
        depot.verify(artifact['id'])
    with pytest.raises(store.ArtifactError):
        depot.import_local(artifact['id'], root / 'absent', source_url=artifact['source']['url'])
    assert blob.read_bytes() == b'ABCDEFGH' and meta.read_bytes() == original
    blob.write_bytes(DATA)
    meta.write_bytes(b'{}')
    with pytest.raises(store.ArtifactError, match='metadata'):
        depot.verify(artifact['id'])


def test_existing_valid_object_remains_unchanged_and_needs_no_second_copy(local):
    depot, catalog, root = local
    artifact = catalog.artifacts[0]
    first = depot.import_local(artifact['id'], candidate(root), source_url=artifact['source']['url'])
    blob, meta = depot._paths(artifact['id'])
    before = (blob.read_bytes(), blob.stat().st_mtime_ns, meta.read_bytes(), meta.stat().st_mtime_ns)
    # Already verified store object is reusable without opening/copying a mutable candidate again.
    assert depot.import_local(artifact['id'], root / 'missing', source_url=artifact['source']['url']) == first
    assert before == (blob.read_bytes(), blob.stat().st_mtime_ns, meta.read_bytes(), meta.stat().st_mtime_ns)
    assert list((depot.root / 'incomplete').iterdir()) == []


def test_duplicate_concurrent_publication_has_one_winner(local):
    depot, catalog, root = local
    artifact = catalog.artifacts[0]
    parts = [depot.new_partial() for _ in range(2)]
    for part in parts:
        part.write_bytes(DATA)
    def promote(part):
        try:
            return depot.promote(artifact['id'], part)
        except store.ArtifactError:
            return None
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(promote, parts))
    assert sum(result is not None for result in results) == 1
    assert depot.verify(artifact['id']) in results


def test_publication_has_no_overwrite_or_copy_fallback(local, monkeypatch):
    depot, catalog, root = local
    def unavailable(*args, **kwargs):
        raise OSError('atomic publication unavailable')
    monkeypatch.setattr(store, '_rename_once', unavailable)
    with pytest.raises(store.ArtifactError, match='atomic publication'):
        depot.import_local(catalog.artifacts[0]['id'], candidate(root),
                           source_url=catalog.artifacts[0]['source']['url'])
    blob, _ = depot._paths(catalog.artifacts[0]['id'])
    assert not blob.exists()


def test_unexpected_partial_or_conflicting_destination_refused(local):
    depot, catalog, root = local
    artifact = catalog.artifacts[0]
    source = candidate(root)
    with pytest.raises(store.ArtifactError, match='publication source'):
        depot.promote(artifact['id'], source)
    unexpected = depot.new_partial().with_name('unexpected.part')
    unexpected.write_bytes(DATA)
    with pytest.raises(store.ArtifactError, match='publication source'):
        depot.promote(artifact['id'], unexpected)
    blob, _ = depot._paths(artifact['id'])
    store.mkdirs(root, blob.parent)
    blob.write_bytes(b'conflict')
    with pytest.raises(store.ArtifactError):
        depot.import_local(artifact['id'], source, source_url=artifact['source']['url'])
    assert blob.read_bytes() == b'conflict' and source.read_bytes() == DATA


def test_native_publication_refuses_an_occupied_name(local):
    depot, _, root = local
    store.mkdirs(root, depot.root)
    temporary, destination = depot.root / 'private', depot.root / 'occupied'
    temporary.write_bytes(DATA)
    destination.write_bytes(b'original')
    with pytest.raises(store.ArtifactError, match='atomic publication refused'):
        store.publish(root, temporary, destination)
    assert destination.read_bytes() == b'original' and temporary.read_bytes() == DATA


def test_native_publication_participates_in_the_write_tripwire(local):
    import write_tripwire
    depot, _, root = local
    store.mkdirs(root, depot.root)
    temporary, destination = depot.root / 'private', depot.root / 'guarded'
    temporary.write_bytes(DATA)
    with write_tripwire.armed([destination]) as refused:
        with pytest.raises(PermissionError, match='tripwire'):
            store.publish(root, temporary, destination)
    assert refused and not destination.exists() and temporary.read_bytes() == DATA


def test_candidate_hardlink_is_refused(local):
    depot, catalog, root = local
    source = candidate(root)
    linked = root / 'hardlink'
    os.link(source, linked)
    with pytest.raises(store.ArtifactError, match='linked'):
        depot.import_local(catalog.artifacts[0]['id'], linked,
                           source_url=catalog.artifacts[0]['source']['url'])
    assert source.read_bytes() == DATA


def test_repository_escape_is_refused(local):
    depot, catalog, root = local
    with pytest.raises(store.ArtifactError, match='escape'):
        depot.import_local(catalog.artifacts[0]['id'], root.parent / 'outside',
                           source_url=catalog.artifacts[0]['source']['url'])


def test_junction_at_write_and_read_boundary_is_refused(local):
    depot, catalog, root = local
    outside = root / 'outside'
    outside.mkdir()
    store.mkdirs(root, depot.root)
    junction = depot.root / 'incomplete'
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with pytest.raises(store.ArtifactError, match='linked'):
        depot.import_local(catalog.artifacts[0]['id'], candidate(root),
                           source_url=catalog.artifacts[0]['source']['url'])
    assert list(outside.iterdir()) == []
    with pytest.raises(store.ArtifactError, match='linked'):
        with store.checked_open(root, junction / 'missing', 'rb'):
            pytest.fail('junction opened')


def test_pinned_parent_cannot_be_moved_between_check_and_write(local):
    depot, _, root = local
    store.mkdirs(root, depot.root)
    with store.boundary(root, depot.root / 'new'):
        with pytest.raises(OSError):
            depot.root.rename(depot.root.with_name('moved'))
    assert depot.root.is_dir()


def test_handle_relative_publication_cannot_follow_a_late_junction(local, monkeypatch):
    """Reparse the pinned destination itself immediately before native publication."""
    import ctypes
    import struct
    from ctypes import wintypes
    depot, catalog, root = local
    artifact = catalog.artifacts[0]
    outside = root / 'outside'
    outside.mkdir()
    original = store._rename_once
    attempted = []
    def reparse_then_publish(source, destination, parent_handle):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        control = kernel.DeviceIoControl
        control.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        substitute = ('\\??\\' + str(outside)).encode('utf-16-le')
        printed = str(outside).encode('utf-16-le')
        names = substitute + b'\0\0' + printed + b'\0\0'
        data = struct.pack('<IHHHHHH', 0xA0000003, len(names) + 8, 0, 0, len(substitute),
                           len(substitute) + 2, len(printed)) + names
        handle = create(str(destination.parent), 0x40000000, 3, None, 3, 0x02200000, None)
        assert handle != ctypes.c_void_p(-1).value
        try:
            size = wintypes.DWORD()
            buffer = ctypes.create_string_buffer(data)
            assert control(handle, 0x900A4, buffer, len(data), None, 0, ctypes.byref(size), None), \
                ctypes.get_last_error()
        finally:
            close(handle)
        attempted.append(True)
        return original(source, destination, parent_handle)
    monkeypatch.setattr(store, '_rename_once', reparse_then_publish)
    with pytest.raises(store.ArtifactError):
        depot.import_local(artifact['id'], candidate(root), source_url=artifact['source']['url'])
    assert attempted == [True]
    assert list(outside.iterdir()) == [], 'publication followed a reparse outside the object directory'


def package_terms(name='sox'):
    from tts import qwen3_package_manifest as qm
    root = Path(__file__).resolve().parents[2]
    raw = (root / 'scripts/qwen3-artifacts.json').read_bytes()
    manifest = qm.load_manifest(raw, (root / 'scripts/qwen3-requirements.txt').read_bytes())
    value = terms()
    value.update(manifest_sha256=manifest.content_sha256, runtime_lock_sha256=qm.ORIGINAL_LOCK_SHA256,
                 effective_lock_sha256=manifest.effective_lock_sha256, engine_action='install-missing',
                 engine_readiness='missing')
    wheel = next(a for a in manifest.wheels if a.name == name)
    row = copy.deepcopy(value['artifacts'][0])
    row.update(id='qwen3-package:' + wheel.name, kind='package', name=wheel.name, version=wheel.version,
               filename=wheel.filename, size=wheel.size, sha256=wheel.sha256,
               verified_reuse_bytes=0, expected_new_bytes=wheel.size, retry_headroom_bytes=0,
               max_payload_bytes=wheel.size,
               source={'kind': 'pinned-https', 'url': wheel.source_url, 'revision': wheel.sha256})
    if name == 'sox':
        row.update(verified_reuse_bytes=wheel.size, expected_new_bytes=0, max_payload_bytes=0,
                   source={'kind': 'local-derived', 'url': None, 'revision': qm.SOX_SOURCE_SHA256},
                   derivative={'source_filename': 'sox-1.5.0.tar.gz', 'source_sha256': qm.SOX_SOURCE_SHA256,
                               'source_size': 63905, 'output_sha256': qm.SOX_WHEEL_SHA256,
                               'build_inputs_sha256': hashlib.sha256(store.canonical(
                                   json.loads(raw)['build_only'])).hexdigest()})
    value['artifacts'] = [row]
    value['payload'] = {key: row[key] for key in ('expected_new_bytes', 'retry_headroom_bytes', 'max_payload_bytes')}
    return value, manifest


def test_reviewed_package_identity_integrates_with_catalog():
    value, manifest = package_terms('accelerate')
    assert store.Catalog(value, package_manifest=manifest).artifacts == value['artifacts']
    value['artifacts'][0]['source']['url'] = 'https://substitute.invalid/file.whl'
    with pytest.raises(store.ArtifactError, match='reviewed'):
        store.Catalog(value, package_manifest=manifest)


@pytest.mark.parametrize('substitute', [False, True])
def test_missing_or_substitute_sox_local_supply_is_refused(tmp_path, substitute):
    value, manifest = package_terms()
    catalog = store.Catalog(value, package_manifest=manifest, purpose='synthetic-qualification')
    depot = store.ArtifactStore(tmp_path, catalog)
    path = tmp_path / 'sox-1.5.0-py3-none-any.whl'
    if substitute:
        path.write_bytes(b'x' * 40164)
    with pytest.raises(store.ArtifactError):
        depot.import_local(catalog.artifacts[0]['id'], path, source_url=None)
    with pytest.raises(store.ArtifactError):
        depot.verify(catalog.artifacts[0]['id'])


def test_sox_substitute_hash_and_portable_supply_cannot_be_authorized():
    value, manifest = package_terms()
    with pytest.raises(store.ArtifactError, match='portable'):
        store.Catalog(value, package_manifest=manifest)
    value['artifacts'][0]['sha256'] = hashlib.sha256(b'replacement').hexdigest()
    value['artifacts'][0]['derivative']['output_sha256'] = value['artifacts'][0]['sha256']
    with pytest.raises(store.ArtifactError, match='reviewed'):
        store.Catalog(value, package_manifest=manifest, purpose='synthetic-qualification')


def test_catalog_and_metadata_identity_are_independent_of_caller_mutation(local):
    depot, catalog, root = local
    snapshot = catalog.terms
    snapshot['artifacts'][0]['sha256'] = '0' * 64
    assert catalog.artifacts[0]['sha256'] == hashlib.sha256(DATA).hexdigest()
    artifact = catalog.artifacts[0]
    depot.import_local(artifact['id'], candidate(root), source_url=artifact['source']['url'])
    changed = terms()
    changed['manifest_sha256'] = '9' * 64
    with pytest.raises(store.ArtifactError):
        store.ArtifactStore(root, store.Catalog(changed)).verify(artifact['id'])
