"""Real v3/store/native installer boundaries with tiny synthetic package identities."""
import dataclasses
import contextlib
import hashlib
import json
import os
from pathlib import Path

import pytest

from shared import artifact_store as store
from shared import artifact_transfer as transfer
from shared import optional_setup_protocol as proto
from tts import optional_setup_authority as auth
from tts import qwen3_package_manifest as qm
from tts import qwen3_packages as qp
from tts import qwen3_runtime as rt
from tts import qwen3_setup as setup
from test_optional_setup_authority import (authority_world, world, sandbox, tiny_assets,
    confirmed, Response)  # noqa: F401
from test_qwen3_setup import fake_runner
from test_qwen3_runtime import make_engine, install_environment

pytestmark = pytest.mark.usefixtures('production_writes_refused')


@pytest.fixture
def package_world(authority_world, monkeypatch):
    root, planner, state, calls, model_opener, observed = authority_world
    real = auth.reviewed_packages()
    (root / 'scripts/qwen3-requirements.txt').write_bytes(real._requirements)
    # Explicit trusted fixture adapter ONLY: no real wheel, cache import, derivative
    # build, or production manifest anchor is changed. All real versions/tags retained.
    payload = {a.name: b'SYNTHETIC-NOT-A-WHEEL:' + a.name.encode() for a in real.wheels}
    def tiny(a):
        return dataclasses.replace(a, size=len(payload[a.name]), sha256=hashlib.sha256(payload[a.name]).hexdigest())
    reviewed = dataclasses.replace(real, runtime=tuple(tiny(a) if a.name != 'sox' else a for a in real.runtime),
                                   sox_wheel=tiny(real.sox_wheel))
    checked = qm._checked_manifest
    monkeypatch.setattr(qm, '_checked_manifest', lambda m: reviewed if m is reviewed else checked(m))
    monkeypatch.setattr(qm, 'SOX_WHEEL_SHA256', reviewed.sox_wheel.sha256)
    monkeypatch.setattr(auth, 'reviewed_packages', lambda: reviewed)
    planner.purpose = 'synthetic-qualification'
    state['engine'] = proto.MISSING
    # Build exact provisional package rows via the existing planner, then install
    # ONLY the tiny fixture's local sox object. No production candidate is opened.
    original_paths, original_verify = store.ArtifactStore._paths, store.ArtifactStore.verify
    original_exists = os.path.lexists
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(store.ArtifactStore, '_paths', lambda s, aid: (
            (root / 'fixture-sox.blob', root / 'fixture-sox.json') if aid == 'qwen3-package:sox'
            else original_paths(s, aid)))
        patch.setattr(store.ArtifactStore, 'verify', lambda s, aid: (
            store.Verification('fixture-only', reviewed.sox_wheel.sha256, reviewed.sox_wheel.size)
            if aid == 'qwen3-package:sox' else original_verify(s, aid)))
        patch.setattr(os.path, 'lexists', lambda p: True if Path(p).name.startswith('fixture-sox.') else original_exists(p))
        both = planner.plan([proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE], engine_action='install-missing').terms
        terms = planner.plan([proto.QWEN3_CUSTOMVOICE], engine_action='install-missing').terms
        assert terms is not None and both is not None
    local_sox = root / 'tiny-local-supply'
    local_sox.write_bytes(payload['sox'])
    for value in (both, terms):
        depot = store.ArtifactStore(root, store.Catalog(value, package_manifest=reviewed, purpose=planner.purpose))
        depot.import_local('qwen3-package:sox', local_sox, source_url=None)
    def opener(request, *, timeout):
        wheel = next((a for a in reviewed.wheels if a.source_url == request.full_url), None)
        if wheel:
            calls.append(request.full_url)
            assert setup.InstallLock.held_by_this_thread() and not commands
            return Response(payload[wheel.name], request.full_url)
        return model_opener(request, timeout=timeout)
    base_runner = fake_runner(root, monkeypatch)
    commands = []
    def runner(command, **kwargs):
        commands.append(command)
        if qp.OFFLINE_BOOTSTRAP in command:
            assert command[:4] == [str(rt.venv_python()), '-I', '-B', '-c']
            assert not any(k.upper().startswith('PYTHON') for k in kwargs['env'] if k not in (
                'PYTHONNOUSERSITE', 'PYTHONUTF8', 'PYTHONIOENCODING'))
            assert kwargs['env']['PIP_CONFIG_FILE'] == os.devnull
            assert all(x not in command for x in ('--index-url', '--extra-index-url', '--upgrade', '--cache-dir'))
            links = Path(command[command.index('--find-links') + 1])
            assert len(list(links.glob('*.whl'))) == 89
            assert len([s for s in command if s.startswith('file:')]) == 89
            for path in links.iterdir():
                with pytest.raises(OSError):
                    path.write_bytes(b'cannot change a sealed wheel')
            state['engine'] = proto.READY
            return 0
        return base_runner(command, **kwargs)
    return root, planner, state, calls, opener, runner, commands, reviewed, depot


def run(fixture, confirmation, **kwargs):
    return fixture[1].acquire_disposable(confirmation, opener=fixture[4], engine_runner=fixture[5], **kwargs)


def preload(fixture, selected=(proto.QWEN3_CUSTOMVOICE,)):
    """Tiny local immutable store copies, never production wheel cache imports."""
    root, planner, _, _, _, _, _, reviewed, _ = fixture
    # Use install terms to obtain identical immutable artifact keys. Action/scope
    # changes do not change those keys; selected owners do.
    before = planner.observer
    planner.observer = lambda *a, **k: auth.Observation({}, proto.MISSING)
    try:
        plan = planner.plan(selected, engine_action='install-missing')
    finally:
        planner.observer = before
    assert plan.terms is not None, plan.to_json()
    depot = store.ArtifactStore(root, store.Catalog(plan.terms, package_manifest=reviewed, purpose=planner.purpose))
    for row in plan.terms['artifacts']:
        if row['kind'] != 'package':
            continue
        source = root / 'package-candidate'
        source.write_bytes(b'SYNTHETIC-NOT-A-WHEEL:' + row['name'].encode())
        depot.import_local(row['id'], source, source_url=row['source']['url'])
    return depot


@contextlib.contextmanager
def prepared(fixture, *, missing=None):
    root, planner, _, _, _, _, _, reviewed, _ = fixture
    depot = preload(fixture)
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action='install-missing')
    depot = store.ArtifactStore(root, store.Catalog(confirmation.plan.terms,
        package_manifest=reviewed, purpose=planner.purpose))
    with setup.InstallLock():
        operation = transfer.TransferLedger(depot).begin(confirmation.raw_consent, session=confirmation.session,
            request_id=confirmation.request_id, disclosed_prior_state=confirmation.plan.to_json()['prior_state'])
        operation.fixture_plan = confirmation.plan  # exact original disclosure for native-boundary tests only
        if missing:
            depot._paths('qwen3-package:' + missing)[0].unlink()
        yield depot, operation, reviewed


@pytest.mark.parametrize('damage', ['missing', 'same-size-hash', 'effective-lock', 'source', 'version', 'tag', 'archive'])
def test_seal_refuses_incomplete_changed_or_unapproved_packages(package_world, damage):
    with prepared(package_world) as (depot, operation, reviewed):
        victim = reviewed.wheels[0]
        blob, _ = depot._paths('qwen3-package:' + victim.name)
        if damage == 'missing':
            blob.unlink()
        elif damage == 'same-size-hash':
            blob.write_bytes(b'x' * victim.size)
        else:
            terms = depot.catalog.terms
            row = next(a for a in terms['artifacts'] if a['name'] == victim.name)
            if damage == 'effective-lock':
                terms['effective_lock_sha256'] = '0' * 64
            elif damage == 'source':
                row['source']['url'] = 'https://evil.invalid/' + victim.filename
            elif damage == 'version':
                row['version'] = '999.0'
            elif damage == 'tag':
                row['filename'] = victim.filename.replace('py3-none-any', 'cp311-cp311-win32')
            else:
                row['filename'] = victim.name + '-' + victim.version + '.tar.gz'
            # Mutation of the actual trusted catalog after initial operation proof,
            # not a test that fails only while constructing a consent.
            depot.catalog._terms = store.canonical(terms)
        with pytest.raises((store.ArtifactError, qm.ManifestError)):
            with qp.sealed_packages(depot, operation, reviewed):
                pytest.fail('unapproved/incomplete wheel set became consumable')
        assert not rt.nested_venv_dir().exists()


def test_final_view_is_rehashed_and_capability_is_operation_scoped(package_world):
    with prepared(package_world) as (depot, operation, reviewed):
        saved = None
        with qp.sealed_packages(depot, operation, reviewed) as capability:
            saved = capability
            record = qp.checked(capability, operation)
            with pytest.raises(store.ArtifactError, match='forged'):
                qp.checked(object.__new__(qp.VerifiedPackageSet), operation)
            with pytest.raises(store.ArtifactError):
                qp.checked(capability, object())
            path, stream, row = record['files'][0]
            # The trusted creator retains write access. An accidental write by
            # that code after staging MUST be caught before handing paths to pip.
            stream.seek(0)
            stream.write(b'x' * row['size'])
            stream.flush()
            with pytest.raises(store.ArtifactError, match='hash'):
                qp.pip_command(rt.venv_python(), capability, operation)
        with pytest.raises(store.ArtifactError, match='inactive'):
            qp.checked(saved, operation)
        assert path.exists()  # receipt/path alone grants no consumption authority


def test_wheel_changed_after_initial_store_verification_never_becomes_consumable(package_world, monkeypatch):
    with prepared(package_world) as (depot, operation, reviewed):
        original = depot.verify
        victim = depot._paths('qwen3-package:' + reviewed.wheels[0].name)[0]
        def raced(artifact_id, **kwargs):
            receipt = original(artifact_id, **kwargs)
            if artifact_id == 'qwen3-package:' + reviewed.wheels[-1].name:
                victim.write_bytes(b'x' * victim.stat().st_size)
            return receipt
        monkeypatch.setattr(depot, 'verify', raced)
        with pytest.raises(store.ArtifactError, match='hash'):
            with qp.sealed_packages(depot, operation, reviewed):
                pytest.fail('stale store proof became a capability')


def test_effective_lock_changed_after_sealing_is_refused(package_world):
    with prepared(package_world) as (depot, operation, reviewed):
        with qp.sealed_packages(depot, operation, reviewed) as capability:
            record = qp.checked(capability, operation)
            record['lock_stream'].seek(0)
            record['lock_stream'].write(b'x' * len(record['lock']))
            record['lock_stream'].flush()
            with pytest.raises(store.ArtifactError, match='consumable lock changed'):
                qp.pip_command(rt.venv_python(), capability, operation)


def test_logically_missing_dependency_row_is_refused_even_when_remaining_wheels_verify(package_world):
    from shared import optional_setup_v3 as v3
    root, planner, _, _, _, _, _, reviewed, _ = package_world
    depot = preload(package_world)
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action='install-missing')
    terms = confirmation.plan.terms
    terms['artifacts'] = [a for a in terms['artifacts'] if a['name'] != reviewed.wheels[0].name]
    consent = v3.new_consent(terms, session=confirmation.session, request_id=confirmation.request_id)
    depot = store.ArtifactStore(root, store.Catalog(terms, package_manifest=reviewed, purpose=planner.purpose))
    with setup.InstallLock():
        operation = transfer.TransferLedger(depot).begin(v3.encode_consent(consent), session=consent.session,
            request_id=consent.request_id, disclosed_prior_state=confirmation.plan.to_json()['prior_state'])
        with pytest.raises(store.ArtifactError, match='89-wheel'):
            with qp.sealed_packages(depot, operation, reviewed):
                pytest.fail('88 packages authorized an incomplete engine')


def test_unproved_consumer_exit_retains_protections_and_revokes_capability(package_world):
    from types import SimpleNamespace
    class UncertainJob:
        def accounting(self):
            raise OSError('synthetic unavailable accounting')
    held_before = len(qp._QUARANTINED)
    with prepared(package_world) as (depot, operation, reviewed):
        with qp.sealed_packages(depot, operation, reviewed) as capability:
            path = qp.checked(capability, operation)['files'][0][0]
            with pytest.raises(setup.SetupError, match='protections retained'):
                qp.consumer_finished(SimpleNamespace(act_job=UncertainJob()))
        with pytest.raises(store.ArtifactError):
            qp.checked(capability, operation)
        assert len(qp._QUARANTINED) == held_before + 1
        try:
            with pytest.raises(OSError):
                path.write_bytes(b'cannot unseal on uncertainty')
        finally:
            # This fixture has NO process. Explicit test cleanup only; production
            # supplies no automatic quarantine release/retry interface.
            qp._QUARANTINED.pop().close()


def test_native_environment_entry_rejects_mismatched_action_and_forged_authority(package_world):
    from tts import qwen3_engine_authority as engine
    with prepared(package_world) as (depot, operation, reviewed):
        planner = package_world[1]
        approved = operation.fixture_plan
        with qp.sealed_packages(depot, operation, reviewed) as capability:
            with engine.execution(planner, approved, operation, capability):
                with pytest.raises(store.ArtifactError, match='action mismatch'):
                    setup.install_environment(rebuild=True, runner=lambda *a, **k: pytest.fail('unauthorized command'))
            assert not rt.nested_venv_dir().exists()
        with pytest.raises(store.ArtifactError):
            with engine.execution(planner, approved, operation, {'sha256': reviewed.content_sha256}):
                pytest.fail('forged native authority')


@pytest.mark.parametrize('data', [b'{', b'[]', b'{"nested_environment": null}',
    b'{"nested_environment": {"path": "another-environment", "stage": "creating"}}'])
def test_uncertain_state_file_cannot_authorize_missing_engine_creation(package_world, data):
    root, planner, _, calls, _, _, commands, _, _ = package_world
    rt.state_path().parent.mkdir(parents=True, exist_ok=True)
    rt.state_path().write_bytes(data)
    plan = planner.plan([proto.QWEN3_CUSTOMVOICE], engine_action='install-missing')
    assert plan.terms is None and calls == [] and commands == []
    assert rt.state_path().read_bytes() == data and not rt.nested_venv_dir().exists()


def test_unapproved_alternative_and_directory_replacement_fail_closed(package_world):
    with prepared(package_world) as (depot, operation, reviewed):
        with qp.sealed_packages(depot, operation, reviewed) as capability:
            record = qp.checked(capability, operation)
            with pytest.raises(OSError):
                record['wheels'].rename(record['wheels'].with_name('replaced'))
            (record['wheels'] / 'unapproved.whl').write_bytes(b'candidate')
            with pytest.raises(store.ArtifactError, match='alternative'):
                qp.pip_command(rt.venv_python(), capability, operation)


def test_late_junction_write_open_is_denied_during_sealed_consumption(package_world):
    import ctypes
    from ctypes import wintypes
    with prepared(package_world) as (depot, operation, reviewed):
        with qp.sealed_packages(depot, operation, reviewed) as capability:
            record = qp.checked(capability, operation)
            create = ctypes.WinDLL('kernel32', use_last_error=True).CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            for path in (record['wheels'], record['wheels'].parent, record['files'][0][0]):
                # FSCTL_SET_REPARSE_POINT needs this write handle. Capture denial
                # at the native boundary instead of skipping on symlink privilege.
                handle = create(str(path), 0x40000000, 3, None, 3, 0x02200000, None)
                assert handle == ctypes.c_void_p(-1).value and ctypes.get_last_error() == 32
            assert qp.pip_command(rt.venv_python(), capability, operation)


def test_source_build_and_external_roots_are_refused_before_any_pip_command(tmp_path):
    folder = tmp_path / 'wheels'
    folder.mkdir()
    for source in (folder / 'sox-1.5.0.tar.gz', tmp_path / 'outside.whl'):
        with pytest.raises(store.ArtifactError, match='wheel roots'):
            qp._pip_command(tmp_path / 'python.exe', folder, tmp_path / 'lock', [(source, '0' * 64)])


def test_offline_command_carries_every_required_restriction_and_explicit_hashed_roots(package_world):
    with prepared(package_world) as (depot, operation, reviewed):
        with qp.sealed_packages(depot, operation, reviewed) as capability:
            argv = qp.pip_command(rt.venv_python(), capability, operation)
            for flag in ('--isolated', '--require-virtualenv', '--no-index', '--find-links', '--require-hashes',
                         '--no-deps', '--only-binary=:all:', '--no-cache-dir'):
                assert argv.count(flag) == 1
            for forbidden in ('--index-url', '--extra-index-url', '--upgrade', '--cache-dir', '--no-binary'):
                assert forbidden not in argv
            record = qp.checked(capability, operation)
            assert Path(argv[argv.index('-r') + 1]).read_bytes() == qm.effective_lock(reviewed)
            assert argv[-89:] == ['file:./' + row['filename'] + '#sha256=' + row['sha256']
                                  for _, _, row in record['files']]


def test_no_consumption_without_install_lock_or_live_spent_operation(package_world):
    root, planner, _, _, _, _, _, reviewed, depot = package_world
    with pytest.raises(store.ArtifactError):
        with qp.sealed_packages(depot, object(), reviewed):
            pytest.fail('no operation capability')
    with prepared(package_world) as (depot, operation, reviewed):
        operation.finish()
        with pytest.raises(store.ArtifactError, match='live spent'):
            with qp.sealed_packages(depot, operation, reviewed):
                pytest.fail('consumed terminal operation')
    with prepared(package_world) as (depot, operation, reviewed):
        pass
    with pytest.raises(store.ArtifactError, match='InstallLock'):
        with qp.sealed_packages(depot, operation, reviewed):
            pytest.fail('live operation used without its InstallLock')


@pytest.mark.parametrize('failure', ['pip-error', 'pip-cancel', 'probe-error'])
def test_interrupted_offline_install_records_incomplete_state_and_spends_consent(package_world, failure):
    preload(package_world)
    root, planner, state, calls, opener, runner, commands, _, _ = package_world
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action='install-missing')
    def failing(command, **kwargs):
        if qp.OFFLINE_BOOTSTRAP in command:
            if failure == 'pip-cancel':
                raise setup.SetupCancelled()
            if failure == 'pip-error':
                return 1
        if failure == 'probe-error' and str(command[1]).endswith('qwen3_worker.py'):
            return 2
        return runner(command, **kwargs)
    result = planner.acquire_disposable(confirmation, opener=opener, engine_runner=failing)
    assert result.state == (proto.CANCELLED if failure == 'pip-cancel' else proto.FAILED), result
    record = rt.environment_record()
    assert result.consent_spent and record['stage'] == rt.STAGE_CREATED
    assert not record.get('probe_ok') and not record.get('requirements_sha256')
    assert run(package_world, confirmation).state == proto.REFUSED


@pytest.mark.parametrize('change', ['damaged', 'unverified', 'busy', 'appeared', 'record', 'base-proof', 'space'])
def test_changed_engine_scope_before_creation_fails_closed(package_world, change):
    preload(package_world)
    root, planner, state, _, opener, runner, commands, _, _ = package_world
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action='install-missing')
    def late(command, **kwargs):
        if setup._BASE_PROBE_MARK in command[-1]:
            if change in ('damaged', 'unverified', 'busy'):
                state['engine'] = getattr(proto, change.upper())
            elif change == 'appeared':
                make_engine(rt.nested_venv_dir(), root / 'outside-candidate')
            elif change == 'record':
                rt.record_environment_stage(rt.nested_venv_dir(), rt.STAGE_CREATING)
            elif change == 'base-proof':
                return 1
            else:
                planner.disk_free = lambda root: 0
        return runner(command, **kwargs)
    result = planner.acquire_disposable(confirmation, opener=opener, engine_runner=late)
    assert result.state == proto.FAILED and result.consent_spent, result
    assert not any(qp.OFFLINE_BOOTSTRAP in c or '-m' in c for c in commands)
    if change == 'appeared':
        assert rt.nested_venv_dir().exists()
    else:
        assert not rt.nested_venv_dir().exists()


def test_explicit_rebuild_preserves_legacy_and_pins_canonical_at_actual_deletion(package_world, monkeypatch):
    preload(package_world)
    root, planner, state, _, opener, runner, commands, reviewed, _ = package_world
    install_environment(root, requirements=reviewed._requirements.decode())
    (rt.nested_venv_dir() / 'Scripts/python.exe').unlink()  # independently proved structural damage
    state['engine'] = proto.DAMAGED
    legacy = root / '.venv-qwen3'
    legacy.mkdir()
    (legacy / 'owner-file').write_bytes(b'never change legacy')
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action='rebuild-canonical')
    original = rt.record_environment_stage
    refused = []
    def race(folder, stage):
        if stage == rt.STAGE_REMOVING:
            with pytest.raises(OSError):
                folder.rename(root / 'late-replacement')
            with pytest.raises(OSError):
                (folder / 'Scripts').rename(root / 'late-child-replacement')
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            close = kernel.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            for entry in (folder / 'Scripts', folder / 'pyvenv.cfg'):
                handle = create(str(entry), 0x40000000, 7, None, 3, 0x02200000, None)
                error = ctypes.get_last_error()
                if handle != ctypes.c_void_p(-1).value:
                    close(handle)
                assert handle == ctypes.c_void_p(-1).value and error == 32
            refused.append('rename at mutation')
        original(folder, stage)
    monkeypatch.setattr(rt, 'record_environment_stage', race)
    result = run(package_world, confirmation)
    assert result.state == proto.SUCCEEDED, result
    assert refused == ['rename at mutation'] and rt.environment_record()['stage'] == rt.STAGE_INSTALLED
    assert (legacy / 'owner-file').read_bytes() == b'never change legacy'
    assert len([c for c in commands if qp.OFFLINE_BOOTSTRAP in c]) == 1


@pytest.mark.parametrize('failure', ['safe-remove', 'uncertain', 'missing', 'changed-identity'])
def test_rebuild_never_treats_missing_or_uncertain_as_approved_damage(package_world, monkeypatch, failure):
    preload(package_world)
    root, planner, state, _, _, _, commands, reviewed, _ = package_world
    if failure != 'missing':
        install_environment(root, requirements=reviewed._requirements.decode())
        (rt.nested_venv_dir() / 'Scripts/python.exe').unlink()
    state['engine'] = proto.DAMAGED
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action='rebuild-canonical')
    if failure == 'safe-remove':
        monkeypatch.setattr(setup, 'safe_to_remove_environment', lambda path: False)
    elif failure == 'uncertain':
        # Keep a physical canonical folder; inability to verify identity is never damage.
        from shared import venv_layout
        monkeypatch.setattr(rt, 'nested_assessment', lambda *a: venv_layout.ChildAssessment(venv_layout.UNVERIFIED, 'unknown'))
    elif failure == 'changed-identity':
        (rt.nested_venv_dir() / 'owner-file').write_bytes(b'changed while waiting')
    before = rt.state_path().read_bytes() if rt.state_path().exists() else None
    result = run(package_world, confirmation)
    assert result.state == proto.REFUSED and not result.consent_spent and commands == [], result
    assert (rt.state_path().read_bytes() if rt.state_path().exists() else None) == before


def test_complete_packages_precede_native_create_and_offline_pip(package_world):
    root, planner, state, calls, _, _, commands, reviewed, _ = package_world
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE], engine_action='install-missing')
    result = run(package_world, confirmation)
    assert result.state == proto.SUCCEEDED, result
    assert result.consent_spent and result.transfer_state['status'] == 'spent'
    assert len([c for c in commands if qp.OFFLINE_BOOTSTRAP in c]) == 1
    assert len([url for url in calls if any(url == a.source_url for a in reviewed.wheels)]) == 88
    assert rt.environment_record()['stage'] == rt.STAGE_INSTALLED
    assert rt.requirements_sha256() == qm.ORIGINAL_LOCK_SHA256
    assert all(rt.model_status(key)[0] for key in rt.MODEL_KEYS)


@pytest.mark.parametrize('failure', ['missing', 'wrong-hash', 'cancel'])
@pytest.mark.parametrize('action', ['install-missing', 'rebuild-canonical'])
def test_incomplete_package_staging_never_starts_engine_mutation(package_world, failure, action):
    root, planner, state, calls, opener, _, commands, reviewed, _ = package_world
    before = None
    if action == 'rebuild-canonical':
        install_environment(root, requirements=reviewed._requirements.decode())
        (rt.nested_venv_dir() / 'Scripts/python.exe').unlink()
        state['engine'] = proto.DAMAGED
        before = ({str(p.relative_to(rt.nested_venv_dir())): p.read_bytes()
                   for p in rt.nested_venv_dir().rglob('*') if p.is_file()}, rt.state_path().read_bytes())
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action=action)
    victim = reviewed.wheels[0]
    def broken(request, **kwargs):
        if request.full_url == victim.source_url:
            if failure == 'cancel':
                raise setup.SetupCancelled()
            if failure == 'missing':
                raise OSError('fixture missing package')
            return Response(b'x' * victim.size, request.full_url)
        return opener(request, **kwargs)
    result = planner.acquire_disposable(confirmation, opener=broken, engine_runner=package_world[5])
    assert result.state == (proto.CANCELLED if failure == 'cancel' else proto.FAILED), result
    assert result.consent_spent and commands == []
    if action == 'install-missing':
        assert not rt.nested_venv_dir().exists() and not rt.environment_record(rt.nested_venv_dir())
    else:
        assert before == ({str(p.relative_to(rt.nested_venv_dir())): p.read_bytes()
                           for p in rt.nested_venv_dir().rglob('*') if p.is_file()}, rt.state_path().read_bytes())
    again = run(package_world, confirmation)
    assert again.state == proto.REFUSED and commands == []


def test_late_safe_remove_failure_preserves_old_canonical_before_deletion(package_world, monkeypatch):
    preload(package_world)
    root, planner, state, _, opener, runner, _, reviewed, _ = package_world
    install_environment(root, requirements=reviewed._requirements.decode())
    (rt.nested_venv_dir() / 'Scripts/python.exe').unlink()
    state['engine'] = proto.DAMAGED
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action='rebuild-canonical')
    before = rt.state_path().read_bytes()
    entries = {str(p): p.read_bytes() for p in rt.nested_venv_dir().rglob('*') if p.is_file()}
    def late(command, **kwargs):
        if setup._BASE_PROBE_MARK in command[-1]:
            monkeypatch.setattr(setup, 'safe_to_remove_environment', lambda path: False)
        return runner(command, **kwargs)
    result = planner.acquire_disposable(confirmation, opener=opener, engine_runner=late)
    assert result.state == proto.FAILED and result.consent_spent, result
    assert rt.state_path().read_bytes() == before
    assert entries == {str(p): p.read_bytes() for p in rt.nested_venv_dir().rglob('*') if p.is_file()}


def test_environment_appearing_after_acquisition_is_not_install_missing(package_world):
    root, planner, state, _, opener, _, commands, reviewed, _ = package_world
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action='install-missing')
    def appear(request, **kwargs):
        response = opener(request, **kwargs)
        # Last package; appearance after complete final planning, before mutation.
        if request.full_url == reviewed.wheels[-1].source_url:
            rt.nested_venv_dir().mkdir(parents=True)
            (rt.nested_venv_dir() / 'owner-file').write_bytes(b'preserve')
        return response
    result = planner.acquire_disposable(confirmation, opener=appear, engine_runner=package_world[5])
    assert result.state == proto.FAILED and result.consent_spent, result
    assert commands == [] and (rt.nested_venv_dir() / 'owner-file').read_bytes() == b'preserve'
