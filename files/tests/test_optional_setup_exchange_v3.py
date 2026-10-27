"""Disposable native Windows v3 exchange qualification; no worker or acquisition."""
import json
import contextlib
import ctypes
import hashlib
import os
import struct
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from shared import optional_setup_protocol as proto
from shared import optional_setup_wire_v3 as wire
from test_optional_setup_wire_v3 import (SESSION, P, I, NOW, canonical, planning, disclosure, confirmation,
                                         graph_document)

pytestmark = pytest.mark.usefixtures('production_writes_refused')
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def repo(tmp_path):
    assert tmp_path.resolve().is_relative_to(ROOT / 'files/dev-work/p05b-stage4c')
    root = tmp_path / 'repo'
    root.mkdir()
    return root


def folder(repo, request_id):
    return repo / 'files/runtime-data/optional-setup' / request_id


def publish_plan(repo, shown=None, request=None):
    from shared import optional_setup_exchange_v3 as exchange
    request = planning() if request is None else request
    shown = disclosure(request=request) if shown is None else shown
    exchange.publish_planning_request(repo, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    result = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    exchange.publish_planning_response(repo, planning=request, disclosure=shown, raw_result=result,
                                      session=SESSION, now=lambda: NOW)
    return request, shown, result


def publish_confirmation(repo, shown=None):
    from shared import optional_setup_exchange_v3 as exchange
    raw, shown, consent = confirmation(shown)
    exchange.prepare_confirmation(repo, expected_disclosure=shown, raw_disclosure=shown.raw,
        raw_consent=consent, raw_request=raw, session=SESSION, request_id=I, now=lambda: NOW)
    return raw, shown, consent


def test_planning_request_and_complete_response_round_trip(repo):
    from shared import optional_setup_exchange_v3 as exchange
    request, shown, result = publish_plan(repo)
    received = exchange.read_planning_exchange(repo, planning=request, expected_disclosure=shown,
                                              session=SESSION, now=lambda: NOW)
    assert received.planning == request and received.disclosure == shown and received.raw_result == result
    assert {p.name for p in folder(repo, P).iterdir()} == {'request.json', 'plan.json', 'result.json'}
    assert (folder(repo, P) / 'request.json').read_bytes() == request.raw
    assert (folder(repo, P) / 'plan.json').read_bytes() == shown.raw
    assert (folder(repo, P) / 'result.json').read_bytes() == result


def test_confirmation_uses_exact_original_separate_documents(repo):
    from shared import optional_setup_exchange_v3 as exchange
    raw, shown, consent = publish_confirmation(repo)
    before = tree_snapshot(repo)
    for _ in range(3):
        checked = exchange.read_confirmation_exchange(repo, expected_disclosure=shown,
            session=SESSION, request_id=I, now=lambda: NOW)
        assert checked.raw == raw and checked.disclosure == shown and checked.raw_consent == consent
    assert tree_snapshot(repo) == before
    assert not folder(repo, P).exists()
    assert {p.name for p in folder(repo, I).iterdir()} == {'plan.json', 'consent.json', 'request.json'}


def tree_snapshot(root):
    return {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.rglob('*') if p.is_file()}


def test_complete_123_artifact_plan_and_prior_history_carried_intact(repo):
    from shared import optional_setup_exchange_v3 as exchange
    doc = graph_document(True, 5)
    request = planning(list(proto.COMPONENTS), 'install-missing')
    shown = disclosure(doc, request)
    publish_plan(repo, shown, request)
    received = exchange.read_planning_exchange(repo, planning=request, expected_disclosure=shown,
                                              session=SESSION, now=lambda: NOW)
    assert received.disclosure.document == canonical(doc)
    raw, _, consent = publish_confirmation(repo, shown)
    checked = exchange.read_confirmation_exchange(repo, expected_disclosure=shown,
        session=SESSION, request_id=I, now=lambda: NOW)
    assert checked.raw == raw and checked.raw_consent == consent and checked.disclosure.document == canonical(doc)


@pytest.mark.parametrize('kind', ['planning-request', 'planning-response', 'confirmation'])
def test_duplicate_publication_never_reuses_or_overwrites(repo, kind):
    from shared import optional_setup_exchange_v3 as exchange
    request, shown, result = publish_plan(repo)
    raw, _, consent = publish_confirmation(repo, shown)
    before = tree_snapshot(repo)
    with pytest.raises(proto.ProtocolError):
        if kind == 'planning-request':
            exchange.publish_planning_request(repo, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
        elif kind == 'planning-response':
            exchange.publish_planning_response(repo, planning=request, disclosure=shown, raw_result=result,
                                              session=SESSION, now=lambda: NOW)
        else:
            exchange.prepare_confirmation(repo, expected_disclosure=shown, raw_disclosure=shown.raw,
                raw_consent=consent, raw_request=raw, session=SESSION, request_id=I, now=lambda: NOW)
    assert tree_snapshot(repo) == before


@pytest.mark.parametrize('kind', ['planning-request', 'planning-response', 'confirmation'])
def test_concurrent_duplicate_publishers_have_exactly_one_winner(repo, kind):
    from shared import optional_setup_exchange_v3 as exchange
    request, shown = planning(), disclosure()
    result = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    raw, _, consent = confirmation(shown)
    if kind == 'planning-response':
        exchange.publish_planning_request(repo, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    def publish():
        try:
            if kind == 'planning-request':
                exchange.publish_planning_request(repo, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
            elif kind == 'planning-response':
                exchange.publish_planning_response(repo, planning=request, disclosure=shown, raw_result=result,
                                                  session=SESSION, now=lambda: NOW)
            else:
                exchange.prepare_confirmation(repo, expected_disclosure=shown, raw_disclosure=shown.raw,
                    raw_consent=consent, raw_request=raw, session=SESSION, request_id=I, now=lambda: NOW)
            return True
        except proto.ProtocolError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: publish(), range(2))) == [False, True]
    if kind == 'planning-response':
        assert exchange.read_planning_exchange(repo, planning=request, expected_disclosure=shown,
                                               session=SESSION, now=lambda: NOW)
    elif kind == 'confirmation':
        assert exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                                    request_id=I, now=lambda: NOW)


@pytest.mark.parametrize('operation', ['planning', 'confirmation'])
def test_publication_order_and_pre_marker_binding_recheck(repo, monkeypatch, operation):
    from shared import optional_setup_exchange_v3 as exchange
    request, shown = planning(), disclosure()
    control, _, consent = confirmation(shown)
    result = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    writes, validations = [], []
    original_write = exchange._write_once
    validator = wire.decode_confirmation_request if operation == 'confirmation' else exchange._planning_binding
    def record_write(state, name, raw):
        writes.append(name)
        if name == ('request.json' if operation == 'confirmation' else 'result.json'):
            assert len(validations) >= 2
            assert (state.path / 'plan.json').is_file()
            if operation == 'confirmation':
                assert (state.path / 'consent.json').is_file()
        return original_write(state, name, raw)
    def record_validation(*args, **kwargs):
        validations.append(True)
        return validator(*args, **kwargs)
    if operation == 'confirmation':
        monkeypatch.setattr(wire, 'decode_confirmation_request', record_validation)
    else:
        monkeypatch.setattr(exchange, '_planning_binding', record_validation)
    monkeypatch.setattr(exchange, '_write_once', record_write)
    if operation == 'confirmation':
        exchange.prepare_confirmation(repo, expected_disclosure=shown, raw_disclosure=shown.raw,
            raw_consent=consent, raw_request=control, session=SESSION, request_id=I, now=lambda: NOW)
        assert writes == ['plan.json', 'consent.json', 'request.json']
    else:
        exchange.publish_planning_request(repo, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
        exchange.publish_planning_response(repo, planning=request, disclosure=shown, raw_result=result,
                                          session=SESSION, now=lambda: NOW)
        assert writes == ['request.json', 'plan.json', 'result.json']


@pytest.mark.parametrize('failed_name', ['plan.json', 'consent.json', 'request.json'])
def test_interrupted_confirmation_has_no_marker_and_cannot_be_retried(repo, monkeypatch, failed_name):
    from shared import optional_setup_exchange_v3 as exchange
    raw, shown, consent = confirmation()
    write = exchange._write_once
    def fail(state, name, data):
        if name == failed_name:
            raise OSError('synthetic disk-full/write failure')
        return write(state, name, data)
    with monkeypatch.context() as scoped:
        scoped.setattr(exchange, '_write_once', fail)
        with pytest.raises(exchange.ExchangeError):
            publish_confirmation(repo, shown)
    expected = set() if failed_name == 'plan.json' else {'plan.json'} if failed_name == 'consent.json' else {
        'plan.json', 'consent.json'}
    assert {p.name for p in folder(repo, I).iterdir()} == expected
    assert not (folder(repo, I) / 'request.json').exists()
    before = tree_snapshot(repo)
    with pytest.raises(proto.ProtocolError):
        exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                            request_id=I, now=lambda: NOW)
    with pytest.raises(proto.ProtocolError):
        exchange.prepare_confirmation(repo, expected_disclosure=shown, raw_disclosure=shown.raw,
            raw_consent=consent, raw_request=raw, session=SESSION, request_id=I, now=lambda: NOW)
    assert tree_snapshot(repo) == before


@pytest.mark.parametrize('failed_name', ['plan.json', 'result.json'])
def test_interrupted_planning_response_refuses_readback_and_retry(repo, monkeypatch, failed_name):
    from shared import optional_setup_exchange_v3 as exchange
    request, shown = planning(), disclosure()
    result = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    exchange.publish_planning_request(repo, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    write = exchange._write_once
    def fail(state, name, data):
        # Leave an uncertain private source even if failure preceded plan rename.
        if name == failed_name:
            (state.path / '.interrupted.tmp').write_bytes(b'incomplete')
            raise PermissionError('synthetic sharing/access failure')
        return write(state, name, data)
    with monkeypatch.context() as scoped:
        scoped.setattr(exchange, '_write_once', fail)
        with pytest.raises(proto.ProtocolError):
            exchange.publish_planning_response(repo, planning=request, disclosure=shown, raw_result=result,
                                              session=SESSION, now=lambda: NOW)
    assert not (folder(repo, P) / 'result.json').exists()
    before = tree_snapshot(repo)
    for attempt in (lambda: exchange.read_planning_exchange(repo, planning=request, expected_disclosure=shown,
                    session=SESSION, now=lambda: NOW), lambda: exchange.publish_planning_response(repo,
                    planning=request, disclosure=shown, raw_result=result, session=SESSION, now=lambda: NOW)):
        with pytest.raises(proto.ProtocolError):
            attempt()
    assert tree_snapshot(repo) == before


@pytest.mark.parametrize('operation,name', [('planning', 'request.json'), ('planning', 'plan.json'),
    ('planning', 'result.json'), ('confirmation', 'request.json'), ('confirmation', 'plan.json'),
    ('confirmation', 'consent.json')])
def test_missing_or_corrupt_documents_never_admit_exchange(repo, operation, name):
    from shared import optional_setup_exchange_v3 as exchange
    request, shown, _ = publish_plan(repo)
    publish_confirmation(repo, shown)
    path = folder(repo, P if operation == 'planning' else I) / name
    raw = path.read_bytes()
    path.write_bytes(raw[:-1])
    def admit():
        if operation == 'planning':
            return exchange.read_planning_exchange(repo, planning=request, expected_disclosure=shown,
                                                   session=SESSION, now=lambda: NOW)
        return exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                                    request_id=I, now=lambda: NOW)
    with pytest.raises(proto.ProtocolError):
        admit()
    path.unlink()
    with pytest.raises(proto.ProtocolError):
        admit()


def test_result_without_plan_and_marker_with_missing_inputs_are_refused(repo):
    from shared import optional_setup_exchange_v3 as exchange
    request, shown, result = planning(), disclosure(), None
    result = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    exchange.publish_planning_request(repo, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    (folder(repo, P) / 'result.json').write_bytes(result)
    with pytest.raises(proto.ProtocolError):
        exchange.read_planning_exchange(repo, planning=request, expected_disclosure=shown,
                                        session=SESSION, now=lambda: NOW)
    raw, _, _ = confirmation(shown)
    folder(repo, I).mkdir()
    (folder(repo, I) / 'request.json').write_bytes(raw)
    with pytest.raises(proto.ProtocolError):
        exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                            request_id=I, now=lambda: NOW)


@pytest.mark.parametrize('request_id', ['../outside', '..', '/absolute', P + ':ads', P.upper(), True, '', 'e' * 31])
def test_invalid_ID_cannot_create_directories(repo, request_id):
    from shared import optional_setup_exchange_v3 as exchange
    with pytest.raises(proto.ProtocolError):
        exchange._path(repo, request_id, 'request.json')
    with pytest.raises(proto.ProtocolError):
        exchange.publish_planning_request(repo, planning().raw, session=SESSION, request_id=request_id, now=lambda: NOW)
    assert list(repo.iterdir()) == []
    with pytest.raises(proto.ProtocolError):
        exchange.read_confirmation_exchange(repo, expected_disclosure=disclosure(), session=SESSION,
                                            request_id=request_id, now=lambda: NOW)


@pytest.mark.parametrize('basename', ['../outside', '/absolute', 'request.json:ads', 'plan.json.', 'extra.json', None])
def test_path_helper_only_admits_fixed_filenames(repo, basename):
    from shared import optional_setup_exchange_v3 as exchange
    with pytest.raises(proto.ProtocolError):
        exchange._path(repo, P, basename)
    assert list(repo.iterdir()) == []


@pytest.mark.parametrize('bad', ['relative', '../outside', 'trailing-dot', 'ads', 'traversal'])
def test_ambiguous_repository_roots_refuse_before_write(repo, bad):
    from shared import optional_setup_exchange_v3 as exchange
    value = {'relative': Path('relative'), '../outside': Path('../outside'),
             'trailing-dot': Path(str(repo) + '.'), 'ads': Path(str(repo) + ':ads'),
             'traversal': repo / '..' / 'outside'}[bad]
    with pytest.raises(proto.ProtocolError):
        exchange.publish_planning_request(value, planning().raw, session=SESSION, request_id=P, now=lambda: NOW)
    assert list(repo.iterdir()) == []


def set_junction(path, target):
    """Native fixture reparse point; no cmd/mklink child or policy changes."""
    from ctypes import wintypes
    assert path.is_relative_to(ROOT / 'files/dev-work/p05b-stage4c')
    assert target.is_relative_to(ROOT / 'files/dev-work/p05b-stage4c')
    from shared import optional_setup_exchange_v3 as exchange
    kernel = exchange._kernel()
    handle = kernel.CreateFileW(str(path), 0x40000000, 3, None, 3, 0x2200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        control = kernel.DeviceIoControl
        control.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        control.restype = wintypes.BOOL
        substitute, printed = ('\\??\\' + str(target)).encode('utf-16-le'), str(target).encode('utf-16-le')
        names = substitute + b'\0\0' + printed + b'\0\0'
        raw = struct.pack('<IHHHHHH', 0xA0000003, len(names) + 8, 0, 0, len(substitute),
                          len(substitute) + 2, len(printed)) + names
        buf, count = ctypes.create_string_buffer(raw), wintypes.DWORD()
        sys.audit('os.symlink', str(target), str(path), True)
        if not control(handle, 0x900A4, buf, len(raw), None, 0, ctypes.byref(count), None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)


@pytest.mark.parametrize('relative', ['files', 'files/runtime-data', 'files/runtime-data/optional-setup',
                                    'files/runtime-data/optional-setup/' + P])
def test_junction_at_every_exchange_ancestor_is_refused_without_external_write(repo, relative):
    from shared import optional_setup_exchange_v3 as exchange
    outside = repo.parent / 'outside'
    outside.mkdir()
    junction = repo / relative
    junction.mkdir(parents=True)
    set_junction(junction, outside)
    with pytest.raises(proto.ProtocolError):
        exchange.publish_planning_request(repo, planning().raw, session=SESSION, request_id=P, now=lambda: NOW)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize('name', ['request.json', 'plan.json', 'consent.json'])
def test_hardlinked_message_files_are_refused(repo, name):
    from shared import optional_setup_exchange_v3 as exchange
    _, shown, _ = publish_confirmation(repo)
    path = folder(repo, I) / name
    os.link(path, repo.parent / 'hardlink')
    assert path.stat().st_nlink == 2
    with pytest.raises(proto.ProtocolError, match='linked'):
        exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                            request_id=I, now=lambda: NOW)


def test_real_message_writer_conflicts_with_read_admission(repo):
    from shared import optional_setup_exchange_v3 as exchange
    _, shown, _ = publish_confirmation(repo)
    with (folder(repo, I) / 'plan.json').open('r+b'):
        with pytest.raises(proto.ProtocolError, match='unavailable|unsafe'):
            exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                                request_id=I, now=lambda: NOW)


def test_opened_reader_denies_native_write_delete_and_ancestor_rename(repo, monkeypatch):
    from shared import optional_setup_exchange_v3 as exchange
    _, shown, _ = publish_confirmation(repo)
    original = wire.decode_confirmation_request
    seen = []
    def validate(*args, **kwargs):
        path = folder(repo, I) / 'plan.json'
        with pytest.raises(OSError):
            path.write_bytes(b'replacement')
        with pytest.raises(OSError):
            path.rename(path.with_name('moved'))
        with pytest.raises(OSError):
            folder(repo, I).rename(folder(repo, 'e' * 32))
        with pytest.raises(OSError):
            folder(repo, I).parent.rename(repo / 'moved-exchange')
        seen.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(wire, 'decode_confirmation_request', validate)
    assert exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                               request_id=I, now=lambda: NOW)
    assert seen == [True]


def test_late_junction_during_native_publication_never_redirects_target(repo, monkeypatch):
    from shared import optional_setup_exchange_v3 as exchange
    from shared import artifact_store as store
    outside = repo.parent / 'outside'
    outside.mkdir()
    rename, seen = store._rename_once, []
    def reparse(source, destination, parent):
        seen.append(True)
        set_junction(destination.parent, outside)
        return rename(source, destination, parent)
    monkeypatch.setattr(store, '_rename_once', reparse)
    with pytest.raises(proto.ProtocolError) as caught:
        exchange.publish_planning_request(repo, planning().raw, session=SESSION, request_id=P, now=lambda: NOW)
    assert seen == [True] and list(outside.iterdir()) == []
    print('NATIVE_LATE_REPARSE_REFUSAL:', caught.value)


def test_native_no_overwrite_even_if_precheck_is_raced(repo):
    from shared import optional_setup_exchange_v3 as exchange
    request = planning()
    exchange.publish_planning_request(repo, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    with pytest.raises(proto.ProtocolError, match='atomic publication refused'):
        with exchange._folder(repo, P) as state:
            exchange._write_once(state, 'request.json', b'replacement')
    assert (folder(repo, P) / 'request.json').read_bytes() == request.raw


def test_native_late_junction_before_source_open_is_refused(repo, monkeypatch):
    from shared import optional_setup_exchange_v3 as exchange
    outside = repo.parent / 'outside'
    outside.mkdir()
    original, seen = exchange._open_file, []
    @contextlib.contextmanager
    def reparse(state, path, **kwargs):
        if kwargs.get('create'):
            set_junction(state.path, outside)  # succeeds while directory is still empty
            seen.append(True)
        with original(state, path, **kwargs) as stream:
            yield stream
    monkeypatch.setattr(exchange, '_open_file', reparse)
    with pytest.raises(proto.ProtocolError):
        exchange.publish_planning_request(repo, planning().raw, session=SESSION, request_id=P, now=lambda: NOW)
    assert seen == [True] and list(outside.iterdir()) == []


def test_native_strict_parent_pin_prevents_in_place_reparse_during_read(repo):
    from shared import optional_setup_exchange_v3 as exchange
    outside = repo.parent / 'outside'
    outside.mkdir()
    publish_confirmation(repo)
    with exchange._folder(repo, I) as state:
        with exchange._pinned(state, state.path / 'plan.json'):
            with pytest.raises(OSError) as caught:
                set_junction(state.path, outside)
            assert caught.value.winerror == 32  # directory write open denied by sharing
    assert list(outside.iterdir()) == []


def test_native_leaf_replacement_at_open_boundary_cannot_escape_validation(repo, monkeypatch):
    from shared import optional_setup_exchange_v3 as exchange
    _, shown, _ = publish_confirmation(repo)
    path = folder(repo, I) / 'plan.json'
    kernel = exchange._kernel
    seen = []
    def hooked_kernel():
        native = kernel()
        class Proxy:
            def __getattr__(self, name):
                return getattr(native, name)
            def CreateFileW(self, filename, access, *args):
                if filename == str(path) and access == 0x80000000:
                    seen.append(True)
                    # A real rename/link attempt at the last path-based open.
                    # Native parent sharing may already prevent the rename.
                    path.rename(path.with_name('kept-original'))
                    path.mkdir()
                    set_junction(path, repo.parent)
                return native.CreateFileW(filename, access, *args)
        return Proxy()
    monkeypatch.setattr(exchange, '_kernel', hooked_kernel)
    with pytest.raises(proto.ProtocolError) as caught:
        exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                            request_id=I, now=lambda: NOW)
    assert seen == [True]
    print('NATIVE_LEAF_SUBSTITUTION_REFUSAL:', caught.value)


@pytest.mark.parametrize('name', ['request.json', 'plan.json', 'consent.json'])
def test_nonregular_junction_leaf_refused(repo, name):
    from shared import optional_setup_exchange_v3 as exchange
    _, shown, _ = publish_confirmation(repo)
    path = folder(repo, I) / name
    path.unlink()
    path.mkdir()
    outside = repo.parent / 'outside'
    outside.mkdir()
    set_junction(path, outside)
    with pytest.raises(proto.ProtocolError):
        exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                            request_id=I, now=lambda: NOW)
    assert list(outside.iterdir()) == []


def test_wrong_captured_parent_identity_refuses_IO(repo):
    from shared import optional_setup_exchange_v3 as exchange
    publish_confirmation(repo)
    with pytest.raises(proto.ProtocolError, match='directory identity changed'):
        with exchange._folder(repo, I) as state, contextlib.ExitStack() as stack:
            fake = exchange._Folder(state.repo, state.path, (0, b'wrong-identity'))
            exchange._read(fake, 'request.json', stack)


@pytest.mark.parametrize('name', ['request.json', 'plan.json', 'consent.json'])
def test_oversize_stat_refuses_before_read(repo, monkeypatch, name):
    from shared import optional_setup_exchange_v3 as exchange
    _, shown, _ = publish_confirmation(repo)
    path = folder(repo, I) / name
    path.write_bytes(b'x' * (exchange._CAPS[name] + 1))
    original = exchange._open_file
    @contextlib.contextmanager
    def wrapped(state, current, **kwargs):
        with original(state, current, **kwargs) as stream:
            class Proxy:
                def fileno(self):
                    return stream.fileno()
                def read(self, count):
                    assert current != path, 'oversized file was read'
                    return stream.read(count)
            yield Proxy()
    monkeypatch.setattr(exchange, '_open_file', wrapped)
    with pytest.raises(proto.ProtocolError, match='oversized'):
        exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                            request_id=I, now=lambda: NOW)


def test_reads_are_bounded_and_short_read_is_refused(repo, monkeypatch):
    from shared import optional_setup_exchange_v3 as exchange
    _, shown, _ = publish_confirmation(repo)
    path = folder(repo, I) / 'request.json'
    path.write_bytes(path.read_bytes() + b' ')  # one-byte-short read would still be valid JSON
    original, observed = exchange._open_file, []
    @contextlib.contextmanager
    def wrapped(state, path, **kwargs):
        with original(state, path, **kwargs) as stream:
            class Proxy:
                def fileno(self):
                    return stream.fileno()
                def read(self, count):
                    assert count == exchange._CAPS[path.name] + 1
                    observed.append(count)
                    raw = stream.read(count)
                    return raw[:-1] if path.name == 'request.json' else raw
            yield Proxy()
    monkeypatch.setattr(exchange, '_open_file', wrapped)
    with pytest.raises(proto.ProtocolError, match='truncated'):
        exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                            request_id=I, now=lambda: NOW)
    assert observed == [wire.MAX_CONTROL_BYTES + 1]


def test_maximum_admitted_documents_preserve_exact_bytes(repo):
    from shared import optional_setup_exchange_v3 as exchange
    request = planning()
    request = wire.PlanningRequest(request.raw + b' ' * (wire.MAX_CONTROL_BYTES - len(request.raw)))
    envelope = disclosure(request=request).to_json()
    envelope['document']['large_metadata'] = ''
    envelope['document']['large_metadata'] = 'x' * (wire.MAX_DISCLOSURE_BYTES - len(canonical(envelope)))
    shown = wire.decode_disclosure(canonical(envelope), planning=request, session=SESSION, now=lambda: NOW)
    exchange.publish_planning_request(repo, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    result = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    result += b' ' * (wire.MAX_CONTROL_BYTES - len(result))
    exchange.publish_planning_response(repo, planning=request, disclosure=shown, raw_result=result,
                                      session=SESSION, now=lambda: NOW)
    got = exchange.read_planning_exchange(repo, planning=request, expected_disclosure=shown,
                                          session=SESSION, now=lambda: NOW)
    assert got.planning.raw == request.raw and got.raw_result == result and got.disclosure.raw == shown.raw
    raw, _, consent = confirmation(shown)
    consent += b' ' * (wire.MAX_CONSENT_BYTES - len(consent))
    control = json.loads(raw)
    control['consent_sha256'] = hashlib.sha256(consent).hexdigest()
    raw = canonical(control)
    raw += b' ' * (wire.MAX_CONTROL_BYTES - len(raw))
    exchange.prepare_confirmation(repo, expected_disclosure=shown, raw_disclosure=shown.raw,
        raw_consent=consent, raw_request=raw, session=SESSION, request_id=I, now=lambda: NOW)
    got = exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                              request_id=I, now=lambda: NOW)
    assert got.raw == raw and got.raw_consent == consent and got.disclosure.raw == shown.raw


def test_forged_but_consistent_exchange_cannot_replace_trusted_original(repo):
    from shared import optional_setup_exchange_v3 as exchange
    original = disclosure()
    doc = json.loads(original.document)
    doc['extra_authoritative_metadata'] = 'changed'
    replacement = disclosure(doc)
    publish_confirmation(repo, replacement)
    assert exchange.read_confirmation_exchange(repo, expected_disclosure=replacement, session=SESSION,
                                               request_id=I, now=lambda: NOW)
    with pytest.raises(proto.ProtocolError):
        exchange.read_confirmation_exchange(repo, expected_disclosure=original, session=SESSION,
                                            request_id=I, now=lambda: NOW)
    with pytest.raises(proto.ProtocolError):
        exchange.read_confirmation_exchange(repo, expected_disclosure=None, session=SESSION,
                                            request_id=I, now=lambda: NOW)


@pytest.mark.parametrize('change', ['session', 'I', 'disclosure', 'consent', 'control'])
def test_invalid_confirmation_refuses_before_directory_creation(repo, change):
    from shared import optional_setup_exchange_v3 as exchange
    raw, shown, consent = confirmation()
    kwargs = dict(expected_disclosure=shown, raw_disclosure=shown.raw, raw_consent=consent,
                  raw_request=raw, session=SESSION, request_id=I, now=lambda: NOW)
    if change == 'session':
        kwargs['session'] = 'e' * 32
    elif change == 'I':
        kwargs['request_id'] = 'e' * 32
    elif change == 'disclosure':
        kwargs['raw_disclosure'] = shown.document
    elif change == 'consent':
        kwargs['raw_consent'] = b'{}'
    else:
        d = json.loads(raw)
        d['plan_id'] = 'f' * 32
        kwargs['raw_request'] = canonical(d)
    with pytest.raises(proto.ProtocolError):
        exchange.prepare_confirmation(repo, **kwargs)
    assert list(repo.iterdir()) == []


@pytest.mark.parametrize('failure', ['rename', 'flush', 'pin'])
def test_native_primitive_failures_have_no_completion_or_fallback(repo, monkeypatch, failure):
    from shared import optional_setup_exchange_v3 as exchange
    from shared import artifact_store as store
    raw, shown, consent = confirmation()
    def unavailable(*args, **kwargs):
        raise OSError('synthetic unavailable/access denied/disk full')
    if failure == 'rename':
        monkeypatch.setattr(store, '_rename_once', unavailable)
    elif failure == 'flush':
        monkeypatch.setattr(os, 'fsync', unavailable)
    else:
        monkeypatch.setattr(store, 'boundary', unavailable)
    with pytest.raises(proto.ProtocolError):
        exchange.prepare_confirmation(repo, expected_disclosure=shown, raw_disclosure=shown.raw,
            raw_consent=consent, raw_request=raw, session=SESSION, request_id=I, now=lambda: NOW)
    assert not (folder(repo, I) / 'request.json').exists()
    assert not (folder(repo, I) / 'plan.json').exists()
    if failure in ('rename', 'flush'):
        assert len(list(folder(repo, I).glob('.*.tmp'))) == 1  # uncertain source retained


def test_publisher_never_claims_spends_mints_or_starts_external_work(repo, monkeypatch):
    from shared import optional_setup_exchange_v3 as exchange
    from shared import optional_setup_v3 as v3
    from shared import artifact_transfer as transfer
    import subprocess
    import socket
    raw, shown, consent = confirmation()
    result = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    request = planning()
    def forbidden(*args, **kwargs):
        raise AssertionError('exchange attempted acquisition/consent/process/network capability')
    for obj, name in ((proto, 'claim_consent'), (proto, 'claim_request'), (v3, 'new_consent'),
                      (v3, 'validate_and_spend'), (transfer.TransferLedger, 'begin'),
                      (subprocess, 'Popen'), (socket, 'socket')):
        monkeypatch.setattr(obj, name, forbidden)
    exchange.publish_planning_request(repo, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    exchange.publish_planning_response(repo, planning=request, disclosure=shown, raw_result=result,
                                      session=SESSION, now=lambda: NOW)
    exchange.prepare_confirmation(repo, expected_disclosure=shown, raw_disclosure=shown.raw,
        raw_consent=consent, raw_request=raw, session=SESSION, request_id=I, now=lambda: NOW)
    assert exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                               request_id=I, now=lambda: NOW)


def test_late_hardlink_during_validation_is_refused(repo, monkeypatch):
    from shared import optional_setup_exchange_v3 as exchange
    _, shown, _ = publish_confirmation(repo)
    validate, seen = wire.decode_confirmation_request, []
    def link_then_validate(*args, **kwargs):
        seen.append(True)
        os.link(folder(repo, I) / 'plan.json', repo.parent / 'late-hardlink')
        return validate(*args, **kwargs)
    monkeypatch.setattr(wire, 'decode_confirmation_request', link_then_validate)
    with pytest.raises(proto.ProtocolError) as caught:
        exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                            request_id=I, now=lambda: NOW)
    assert seen == [True]
    print('NATIVE_LATE_HARDLINK_REFUSAL:', caught.value)


def test_planning_readback_is_repeatable_without_mutation(repo):
    from shared import optional_setup_exchange_v3 as exchange
    request, shown, result = publish_plan(repo)
    before = tree_snapshot(repo)
    for _ in range(3):
        assert exchange.read_planning_exchange(repo, planning=request, expected_disclosure=shown,
            session=SESSION, now=lambda: NOW).raw_result == result
    assert tree_snapshot(repo) == before


def test_planning_result_and_original_disclosure_must_agree_before_publication(repo):
    from shared import optional_setup_exchange_v3 as exchange
    request, shown = planning(), disclosure()
    result = json.loads(wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW))
    result['plan_sha256'] = 'e' * 64
    exchange.publish_planning_request(repo, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    before = tree_snapshot(repo)
    with pytest.raises(proto.ProtocolError):
        exchange.publish_planning_response(repo, planning=request, disclosure=shown, raw_result=canonical(result),
                                          session=SESSION, now=lambda: NOW)
    assert tree_snapshot(repo) == before


def test_changed_opened_file_identity_is_refused(repo, monkeypatch):
    from shared import optional_setup_exchange_v3 as exchange
    _, shown, _ = publish_confirmation(repo)
    real_stat = os.stat
    path = folder(repo, I) / 'plan.json'
    def wrong_identity(current, *args, **kwargs):
        result = real_stat(current, *args, **kwargs)
        if current == path:
            class WrongIdentity:
                st_dev, st_ino = result.st_dev, result.st_ino + 1
                def __getattr__(self, name):
                    return getattr(result, name)
            return WrongIdentity()
        return result
    monkeypatch.setattr(os, 'stat', wrong_identity)
    with pytest.raises(proto.ProtocolError, match='replaced'):
        exchange.read_confirmation_exchange(repo, expected_disclosure=shown, session=SESSION,
                                            request_id=I, now=lambda: NOW)


def test_no_general_filesystem_or_execution_API_is_exported():
    import ast
    from shared import optional_setup_exchange_v3 as exchange
    tree = ast.parse(Path(exchange.__file__).read_text(encoding='utf-8'))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef) and not node.name.startswith('_')}
    assert functions == {'publish_planning_request', 'publish_planning_response', 'read_planning_exchange',
                         'prepare_confirmation', 'read_confirmation_exchange'}
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names}
    assert imports <= {'__future__', 'contextlib', 'ctypes', 'os', 're', 'stat', 'sys', 'time', 'uuid',
                       'dataclasses', 'pathlib', 'shared', 'msvcrt'}


def test_native_directory_sharing_prevents_unprovable_pin(repo):
    from shared import optional_setup_exchange_v3 as exchange
    (repo / 'files').mkdir()
    kernel = exchange._kernel()
    handle = kernel.CreateFileW(str(repo / 'files'), 0x40000000, 3, None, 3, 0x2200000, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        with pytest.raises(proto.ProtocolError, match='cannot pin directory'):
            exchange.publish_planning_request(repo, planning().raw, session=SESSION, request_id=P, now=lambda: NOW)
    finally:
        kernel.CloseHandle(handle)
    assert not folder(repo, P).exists()


def test_native_create_and_publication_obey_outer_write_tripwire(repo):
    from shared import optional_setup_exchange_v3 as exchange
    from shared import artifact_store as store
    import write_tripwire
    store.mkdirs(repo, repo / exchange.EXCHANGE_ROOT)
    target = folder(repo, P)
    with write_tripwire.armed([target]) as attempts:
        with pytest.raises(proto.ProtocolError):
            exchange.publish_planning_request(repo, planning().raw, session=SESSION, request_id=P, now=lambda: NOW)
    assert len(attempts) == 1 and not target.exists()
    # Native temp creation and relative rename each need their own audit event.
    exchange.publish_planning_request(repo, planning().raw, session=SESSION, request_id=P, now=lambda: NOW)
    before = tree_snapshot(repo)
    with pytest.raises(proto.ProtocolError):
        with exchange._folder(repo, P) as state:
            with write_tripwire.armed([state.path]) as attempts:
                exchange._write_once(state, 'plan.json', b'{}')
    assert len(attempts) == 1
    assert not (target / 'plan.json').exists()
    assert tree_snapshot(repo) == before
    destination = target / 'plan.json'
    with pytest.raises(proto.ProtocolError):
        with exchange._folder(repo, P) as state:
            with write_tripwire.armed([destination]) as attempts:
                exchange._write_once(state, 'plan.json', b'{}')
    assert len(attempts) == 1
    assert not destination.exists()


@pytest.mark.parametrize('kind', ['planning', 'confirmation'])
def test_even_an_existing_empty_request_directory_is_unusable(repo, kind):
    from shared import optional_setup_exchange_v3 as exchange
    request_id = P if kind == 'planning' else I
    folder(repo, request_id).mkdir(parents=True)
    with pytest.raises(proto.ProtocolError, match='exclusive request directory refused'):
        if kind == 'planning':
            exchange.publish_planning_request(repo, planning().raw, session=SESSION, request_id=P, now=lambda: NOW)
        else:
            publish_confirmation(repo)
    assert list(folder(repo, request_id).iterdir()) == []
