"""Disposable consumer qualification. Synthetic wheels never establish model readiness."""
import contextlib
import hashlib
import json
import os
import ensurepip
import venv
import zipfile
from pathlib import Path

import pytest

from shared import artifact_store as store
from shared import optional_setup_protocol as proto
from shared import optional_setup_wire_v3 as wire
from tts import model_assets as assets
from tts import qwen3_packages as sealing
from tts import qwen3_runtime as rt
from tts import qwen3_setup as setup
from tts import qwen3_package_manifest as packages
from test_optional_setup_wire_v3 import (NOW, SESSION, I, planning, document, disclosure,
                                         confirmation, decode_confirmation)
from test_artifact_store import terms
from test_m3_supply import wheel_bytes

pytestmark = pytest.mark.usefixtures('production_writes_refused')
NATIVE_RUN = setup.run_command


def shown_wheel(target_terms=None):
    value = terms() if target_terms is None else target_terms
    value['components'] = [{'id': proto.KOKORO, 'readiness': proto.MISSING, 'scope': proto.SCOPE_INSTALL}]
    row = value['artifacts'][0]
    row.update(id='spacy-english:' + assets.SPACY_WHEEL_SHA256, name='spacy-english',
               components=[proto.KOKORO], filename=assets.SPACY_WHEEL_NAME,
               size=assets.SPACY_WHEEL_SIZE, sha256=assets.SPACY_WHEEL_SHA256,
               source={'kind': 'pinned-https', 'url': assets.SPACY_WHEEL_URL,
                       'revision': assets.SPACY_WHEEL_SHA256}, expected_new_bytes=assets.SPACY_WHEEL_SIZE,
               verified_reuse_bytes=0, retry_headroom_bytes=0, max_payload_bytes=assets.SPACY_WHEEL_SIZE)
    value['payload'].update(expected_new_bytes=assets.SPACY_WHEEL_SIZE, retry_headroom_bytes=0,
                            max_payload_bytes=assets.SPACY_WHEEL_SIZE)
    return disclosure(document(value), planning([proto.KOKORO]))


def bound():
    raw, shown, consent = confirmation(shown_wheel())
    return decode_confirmation(raw, shown, consent), shown


def test_production_v1_terms_never_grant_main_consumer_authority():
    from tts import spacy_consumer as consumer
    confirmed, original = bound()
    with pytest.raises(store.ArtifactError, match='consumer-target/recovery'):
        consumer.production_consumer(confirmed, original)


@pytest.mark.parametrize('wrong', ['root', 'target', 'confirmation', 'original'])
def test_disposable_authority_refuses_unowned_target_or_original(tmp_path, wrong):
    from tts import spacy_consumer as consumer
    confirmed, original = bound()
    root = tmp_path
    target = root / 'disposable-env'
    target.mkdir()
    (target / 'pyvenv.cfg').write_text('include-system-site-packages = false\nversion = 3.12.10\n')
    scripts = target / 'Scripts'
    scripts.mkdir()
    (scripts / 'python.exe').write_bytes(b'fixture executable; not launched')
    if wrong == 'root':
        root = Path(__file__).resolve().parents[2]
    elif wrong == 'target':
        target = Path(__file__).resolve().parents[2] / '.venv'
    elif wrong == 'confirmation':
        confirmed = object()
    else:
        doc = original.to_json()['document']
        doc['future_metadata'] = {'must_survive': True}
        original = disclosure(doc, planning([proto.KOKORO]))
    with pytest.raises((store.ArtifactError, proto.ProtocolError)):
        consumer.DisposableConsumer(root, target, confirmed, original, now=lambda: NOW)


def test_wheel_anchor_is_exact_and_never_accepts_requirements_or_source(tmp_path):
    from tts import spacy_consumer as consumer
    bad = tmp_path / assets.SPACY_WHEEL_NAME
    bad.write_bytes(wheel_bytes(name='en_core_web_sm', version='3.8.0'))
    with pytest.raises(Exception, match='size|hash'):
        consumer.verify_source(bad)
    assert consumer.POLICY['version'] == 1
    assert consumer.POLICY['production_eligible'] is False
    assert consumer.POLICY['recovery'] == 'retain-target-and-uncertainty; no-automatic-retry-or-parent-rebuild'


def synthetic_wheel():
    # The fixed, tiny fixture is explicitly unrelated to the approved model bytes.
    return wheel_bytes(name='en_core_web_sm', version='3.8.0', extra=('en_core_web_sm/meta.json',
        json.dumps({'lang': 'en', 'name': 'core_web_sm', 'version': '3.8.0', 'spacy_version': '>=3.8.0,<3.9.0'})))


@pytest.fixture
def consumer_world(tmp_path, monkeypatch):
    from tts import spacy_consumer as consumer
    data = synthetic_wheel()
    monkeypatch.setattr(assets, 'SPACY_WHEEL_SIZE', len(data))
    monkeypatch.setattr(assets, 'SPACY_WHEEL_SHA256', hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(rt, 'repo_root', lambda: tmp_path)
    target = tmp_path / 'disposable-env'
    (target / 'Scripts').mkdir(parents=True)
    (target / 'Scripts/python.exe').write_bytes(b'not launched in simulated cases')
    (target / 'pyvenv.cfg').write_text('include-system-site-packages = false\nversion = 3.12.10\n')
    source = tmp_path / 'source.whl'
    source.write_bytes(data)
    confirmed, original = bound()
    return consumer, consumer.DisposableConsumer(tmp_path, target, confirmed, original, now=lambda: NOW), source


def simulated_runner(subject, *, pip_exit=0, health=False, model=None, version='3.8.16', fail=None):
    installed, calls = [model], []
    def run(argv, *, env, cwd, on_line, cancel_check):
        assert setup.InstallLock.held_by_this_thread()
        assert cancel_check() is False
        for path in (subject.target / 'Scripts/python.exe', subject.target / 'pyvenv.cfg'):
            with pytest.raises(OSError):
                path.write_bytes(b'late target substitution')
        calls.append(argv)
        assert env['PIP_CONFIG_FILE'] == os.devnull
        if argv[4] == subject.__class__.__module__:
            pytest.fail('arbitrary module command')
        from tts import spacy_consumer
        if argv[4] == spacy_consumer.PROBE:
            result = dict(prefix=str(subject.target), spacy=version, model=installed[0], health=health)
            on_line('@@SPACY ' + json.dumps(result))
            return 0
        assert argv[4] == sealing.OFFLINE_BOOTSTRAP
        assert subject.pending.read_bytes() == subject.record
        for flag in ('--no-deps', '--no-index', '--require-hashes', '--only-binary=:all:', '--isolated'):
            assert flag in argv
        wheel = Path(cwd) / assets.SPACY_WHEEL_NAME
        for mutation in (lambda: wheel.write_bytes(b'evil'), lambda: wheel.unlink()):
            with pytest.raises(OSError):
                mutation()
        if fail:
            raise fail
        installed[0] = '3.8.0' if pip_exit == 0 else None
        return pip_exit
    return run, calls


@pytest.mark.parametrize('outcome', ['installed-unhealthy', 'pip-failed', 'cancelled'])
def test_sealed_consumer_keeps_receipts_health_and_uncertainty_distinct(consumer_world, outcome):
    _, subject, source = consumer_world
    fail = setup.SetupCancelled() if outcome == 'cancelled' else None
    runner, calls = simulated_runner(subject, pip_exit=1 if outcome == 'pip-failed' else 0, fail=fail)
    if fail:
        with pytest.raises(setup.SetupCancelled):
            subject.qualify(source, runner=runner)
    else:
        result = subject.qualify(source, runner=runner)
        assert result['distribution_installed'] is (outcome == 'installed-unhealthy')
        assert result['import_health_ready'] is False and result['transfer_receipt'] is False
        assert result['production_ready'] is False
    assert subject.pending.exists()
    with pytest.raises(store.ArtifactError, match='previous attempt'):
        subject.qualify(source, runner=runner)
    assert sum(argv[4] == sealing.OFFLINE_BOOTSTRAP for argv in calls) == 1


@pytest.mark.parametrize('damage', ['target', 'source', 'spacy-version', 'already-installed', 'expired'])
def test_changed_inputs_or_healthy_existing_model_never_launch_pip(consumer_world, damage):
    _, subject, source = consumer_world
    if damage == 'target':
        (subject.target / 'Scripts/python.exe').write_bytes(b'replaced')
    elif damage == 'source':
        source.write_bytes(source.read_bytes()[:-1])
    elif damage == 'expired':
        subject.now = lambda: NOW + 601
    runner, calls = simulated_runner(subject, version='3.9.0' if damage == 'spacy-version' else '3.8.16',
                                     model='3.8.0' if damage == 'already-installed' else None)
    before = source.read_bytes()
    with pytest.raises((store.ArtifactError, packages.ManifestError, proto.ProtocolError)):
        subject.qualify(source, runner=runner)
    assert not subject.pending.exists() and source.read_bytes() == before
    assert not any(argv[4] == sealing.OFFLINE_BOOTSTRAP for argv in calls)


def test_uncertain_job_retains_wheel_handles_and_pending_record(consumer_world):
    _, subject, source = consumer_world
    runner, calls = simulated_runner(subject)
    held = []
    def uncertain(argv, **kwargs):
        if argv[4] == sealing.OFFLINE_BOOTSTRAP:
            held.append(Path(kwargs['cwd']) / assets.SPACY_WHEEL_NAME)
            class Job:
                def accounting(self):
                    raise OSError('lost Job accounting')
            class Process:
                act_job = Job()
            sealing.consumer_finished(Process())
        return runner(argv, **kwargs)
    old = len(sealing._QUARANTINED)
    try:
        with pytest.raises(setup.SetupError, match='protections retained'):
            subject.qualify(source, runner=uncertain)
        assert len(sealing._QUARANTINED) == old + 1 and subject.pending.exists()
        with pytest.raises(OSError):
            held[0].write_bytes(b'not released')
    finally:
        # Test-only cleanup after the fake job has no real members.
        while len(sealing._QUARANTINED) > old:
            sealing._QUARANTINED.pop().close()


@pytest.mark.parametrize('lock_name', ['setup.lock', 'inference.lock', 'engine.lock'])
def test_consumer_excludes_parent_repair_and_inference(consumer_world, lock_name):
    _, subject, source = consumer_world
    folder = rt.runtime_dir()
    folder.mkdir(parents=True, exist_ok=True)
    held = rt.FileLock(folder / lock_name)
    assert held.acquire()
    try:
        runner, calls = simulated_runner(subject)
        with pytest.raises(setup.SetupError):
            subject.qualify(source, runner=runner)
        assert not calls and not subject.pending.exists()
    finally:
        held.release()


@pytest.mark.parametrize('failure', ['no-probe-output', 'source-replaced', 'deadline', 'pending-publication'])
def test_consumer_failure_before_launch_does_not_install_or_rebuild(consumer_world, monkeypatch, failure):
    consumer, subject, source = consumer_world
    runner, calls = simulated_runner(subject)
    now = [0.0]
    if failure == 'deadline':
        monkeypatch.setattr(consumer.time, 'monotonic', lambda: now[0])
    original_write = store.write_once
    def write(repo, path, value):
        if path == subject.pending:
            raise OSError('journal disk full')
        return original_write(repo, path, value)
    if failure == 'pending-publication':
        monkeypatch.setattr(store, 'write_once', write)
    def fault(argv, **kwargs):
        if argv[4] == consumer.PROBE and argv[-1] == 'before':
            if failure == 'no-probe-output':
                return 0  # launch/success without evidence cannot prove readiness
            if failure == 'source-replaced':
                source.write_bytes(b'x' * assets.SPACY_WHEEL_SIZE)
            if failure == 'deadline':
                now[0] = consumer.POLICY['timeout_seconds'] + 1
                assert kwargs['cancel_check']()
                raise setup.SetupCancelled()
        return runner(argv, **kwargs)
    with pytest.raises((store.ArtifactError, packages.ManifestError, setup.SetupCancelled, OSError)):
        subject.qualify(source, runner=fault)
    assert not subject.pending.exists()
    assert not any(a[4] == sealing.OFFLINE_BOOTSTRAP for a in calls)


@pytest.mark.parametrize('field', ['sha256', 'filename', 'source'])
def test_valid_v3_confirmation_cannot_substitute_a_different_model(consumer_world, field):
    consumer, subject, _ = consumer_world
    doc = subject.original.to_json()['document']
    row = doc['terms']['artifacts'][0]
    if field == 'sha256':
        row['sha256'] = 'e' * 64
        row['source']['revision'] = row['sha256']
    elif field == 'filename':
        row['filename'] = 'different-3.8.0-py3-none-any.whl'
    else:
        row['source']['url'] = 'https://unapproved.invalid/model.whl'
    original = disclosure(doc, planning([proto.KOKORO]))
    confirmed = decode_confirmation(*confirmation(original))
    with pytest.raises(store.ArtifactError, match='unapproved English'):
        consumer.DisposableConsumer(subject.root, subject.target, confirmed, original, now=lambda: NOW)


def test_cancellation_during_source_proof_never_starts_consumer(consumer_world):
    _, subject, source = consumer_world
    runner, calls = simulated_runner(subject)
    with pytest.raises(setup.SetupCancelled):
        subject.qualify(source, runner=runner, cancelled=lambda: True)
    assert not calls and not subject.pending.exists()


def test_new_confirmation_cannot_bypass_uncertainty_for_the_same_target(consumer_world):
    consumer, subject, source = consumer_world
    runner, _ = simulated_runner(subject, fail=setup.SetupCancelled())
    with pytest.raises(setup.SetupCancelled):
        subject.qualify(source, runner=runner)
    confirmed, original = bound()
    assert confirmed.consent.consent_id != subject.confirmation.consent.consent_id
    retry = consumer.DisposableConsumer(subject.root, subject.target, confirmed, original, now=lambda: NOW)
    runner, calls = simulated_runner(retry)
    before = subject.pending.read_bytes()
    with pytest.raises(store.ArtifactError, match='previous attempt'):
        retry.qualify(source, runner=runner)
    assert not calls and subject.pending.read_bytes() == before


@pytest.mark.parametrize('change', ['none', 'production-python', 'hash', 'no-index', 'no-deps', 'cwd', 'outside-lock'])
def test_native_guard_profile_is_exact_and_disposable(tmp_path, change):
    from guarded_pytest import ProcessPolicy, ROOT
    source = Path(__file__)
    data = synthetic_wheel()
    digest = hashlib.sha256(data).hexdigest()
    config = {'version': 1, 'tools': {}, 'process_sites': {source.relative_to(ROOT).as_posix(): {
        'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'functions': ['test_native_guard_profile_is_exact_and_disposable']}},
        'spacy_fixture': {'synthetic_only': True, 'sha256': digest}}
    policy = ProcessPolicy(config, tmp_path)
    wheels = tmp_path / 'spacy-sealed-fixture'
    wheels.mkdir()
    wheel = wheels / assets.SPACY_WHEEL_NAME
    wheel.write_bytes(data)
    lock = wheels / 'requirements.txt'
    lock.write_text('en-core-web-sm==3.8.0 --hash=sha256:' + digest + '\n')
    argv = sealing._pip_command(tmp_path / 'disposable-env/Scripts/python.exe', wheels, lock, [(wheel, digest)])
    cwd = str(wheels)
    if change == 'production-python':
        argv[0] = str(ROOT / '.venv/Scripts/python.exe')
    elif change == 'hash':
        argv[-1] = argv[-1].replace(digest, '0' * 64)
    elif change in ('no-index', 'no-deps'):
        argv.remove('--' + change)
    elif change == 'cwd':
        cwd = str(ROOT)
    elif change == 'outside-lock':
        argv[18] = str(ROOT / 'requirements.txt')
    result = policy.approve(argv, cwd)
    assert (result is not None) is (change == 'none')


@pytest.mark.parametrize('damage', ['model-version', 'compatibility', 'additional-dependency'])
def test_model_metadata_compatibility_never_invites_spacy_upgrade(tmp_path, monkeypatch, damage):
    from tts import spacy_consumer as consumer
    metadata = {'lang': 'en', 'name': 'core_web_sm', 'version': '3.8.0', 'spacy_version': '>=3.8.0,<3.9.0'}
    if damage == 'model-version':
        metadata['version'] = '3.9.0'
    elif damage == 'compatibility':
        metadata['spacy_version'] = '>=3.9.0,<4.0.0'
    data = wheel_bytes(name='en_core_web_sm', version='3.8.0',
        requires=('unapproved-dependency==1',) if damage == 'additional-dependency' else (),
        extra=('en_core_web_sm/meta.json', json.dumps(metadata)))
    monkeypatch.setattr(assets, 'SPACY_WHEEL_SIZE', len(data))
    monkeypatch.setattr(assets, 'SPACY_WHEEL_SHA256', hashlib.sha256(data).hexdigest())
    path = tmp_path / 'source.whl'
    path.write_bytes(data)
    with pytest.raises(store.ArtifactError, match='metadata'):
        consumer.verify_source(path)


def test_native_offline_synthetic_model_install_is_not_actual_model_readiness(tmp_path, monkeypatch):
    from tts import spacy_consumer as consumer
    target = tmp_path / 'disposable-env'
    venv.EnvBuilder(with_pip=False, symlinks=False).create(target)
    site = target / 'Lib/site-packages'
    pip_wheel, = (Path(ensurepip.__file__).parent / '_bundled').glob('pip-*.whl')
    with zipfile.ZipFile(pip_wheel) as archive:
        assert all((site / n).resolve().is_relative_to(site.resolve()) for n in archive.namelist())
        archive.extractall(site)
    spacy_info = site / 'spacy-3.8.16.dist-info'
    spacy_info.mkdir()
    (spacy_info / 'METADATA').write_text('Metadata-Version: 2.1\nName: spacy\nVersion: 3.8.16\n')
    data = synthetic_wheel()
    monkeypatch.setattr(assets, 'SPACY_WHEEL_SIZE', len(data))
    monkeypatch.setattr(assets, 'SPACY_WHEEL_SHA256', hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(rt, 'repo_root', lambda: tmp_path)
    source = tmp_path / 'source.whl'
    source.write_bytes(data)
    confirmed, original = bound()
    subject = consumer.DisposableConsumer(tmp_path, target, confirmed, original, now=lambda: NOW)
    monkeypatch.setenv('PIP_TARGET', str(tmp_path / 'ambient-target'))
    (target / 'pip.ini').write_text('[global]\nindex-url = https://refused.invalid/simple\ntarget = ' +
                                   str(tmp_path / 'ambient-target') + '\n')
    commands = []
    def native_run(argv, *, on_line, **kwargs):
        output = []
        def keep(line):
            output.append(line)
            on_line(line)
        code = NATIVE_RUN(argv, on_line=keep, **kwargs)
        commands.append({'argv': argv, 'output': output, 'exit': code})
        return code
    result = subject.qualify(source, runner=native_run)
    assert result['pip_exit'] == 0 and result['distribution_installed'] is True
    assert result['import_health_ready'] is False and result['production_ready'] is False
    assert not (tmp_path / 'ambient-target').exists()
    assert (spacy_info / 'METADATA').read_text().endswith('Version: 3.8.16\n')
    assert sealing.NATIVE_COMPLETIONS[-1]['active'] == 0
    pip, = [c for c in commands if c['argv'][4] == sealing.OFFLINE_BOOTSTRAP]
    audit, = [json.loads(line[len('@@OFFLINE '):]) for line in pip['output'] if line.startswith('@@OFFLINE ')]
    assert set(audit) <= {'socket.__new__', 'subprocess.Popen'}
    (tmp_path / 'qualification.json').write_text(json.dumps(result, indent=2))
    (tmp_path / 'native-proof.json').write_text(json.dumps({'commands': commands, 'refusals': audit,
        'job': sealing.NATIVE_COMPLETIONS[-1], 'synthetic_only': True}, indent=2))
