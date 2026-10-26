"""Stage 4B-3B synthetic inputs and native Windows consumption boundaries."""
import contextlib
import ensurepip
import hashlib
import json
import os
import sys
import venv
import zipfile
from pathlib import Path

import pytest

from shared import artifact_store as store
from tts import qwen3_packages as qp
from tts import qwen3_setup as setup
from tts import qwen3_runtime as rt

# Deliberate native qualification only. The autouse fixture keeps every ordinary
# installer call blocked; the outer guard allowlists this exact disposable argv.
NATIVE_RUN = setup.run_command
pytestmark = pytest.mark.usefixtures('production_writes_refused')


def tiny_wheel(path):
    """A test-only package, unrelated to any ACT runtime dependency."""
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in {
            'act_disposable_proof.py': 'VALUE = 73\n',
            'act_disposable_proof-1.0.dist-info/METADATA':
                'Metadata-Version: 2.1\nName: act-disposable-proof\nVersion: 1.0\n',
            'act_disposable_proof-1.0.dist-info/WHEEL':
                'Wheel-Version: 1.0\nGenerator: ACT-disposable-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
            'act_disposable_proof-1.0.dist-info/RECORD': '',
        }.items():
            archive.writestr(name, data)
    return path.read_bytes()


def test_private_files_deny_write_replacement_and_allow_python_read(tmp_path):
    target = tmp_path / 'private.whl'
    with qp._private_file(tmp_path, target) as stream:
        stream.write(b'protected')
        stream.flush()
        assert target.read_bytes() == b'protected'
        for mutate in (lambda: target.write_bytes(b'corrupted'), lambda: target.unlink(),
                       lambda: target.rename(tmp_path / 'moved.whl')):
            with pytest.raises(OSError):
                mutate()
        with pytest.raises(OSError):
            tmp_path.rename(tmp_path.with_name(tmp_path.name + '-moved'))
    target.write_bytes(b'handles released')


def test_native_directory_claim_is_exclusive_and_pinned_from_creation(tmp_path):
    from tts import qwen3_engine_authority as engine
    folder = tmp_path / 'new-engine'
    with engine._create_directory(tmp_path, folder):
        assert folder.is_dir()
        with pytest.raises(OSError):
            folder.rename(tmp_path / 'replaced')
        with pytest.raises(store.ArtifactError):
            with engine._create_directory(tmp_path, folder):
                pytest.fail('adopted existing folder')
        (folder / 'child').write_bytes(b'venv may create contents')
    assert (folder / 'child').read_bytes() == b'venv may create contents'


def test_file_create_is_audited_before_ctypes_write(tmp_path):
    import write_tripwire
    target = tmp_path / 'refused' / 'private.whl'
    target.parent.mkdir()
    with write_tripwire.armed([target.parent]), pytest.raises(PermissionError):
        with qp._private_file(tmp_path, target):
            pytest.fail('unaudited file creation')
    assert not target.exists()


@pytest.mark.parametrize('fake', [None, 'wheel.whl', {'sha256': '0' * 64}, object()])
def test_receipts_and_plain_objects_cannot_grant_consumption(fake):
    with pytest.raises(store.ArtifactError, match='forged'):
        qp.checked(fake, object())
    with pytest.raises(store.ArtifactError, match='minted'):
        qp.VerifiedPackageSet()


@pytest.mark.parametrize('outcome', ['success', 'cancel', 'wrong-hash'])
def test_native_offline_pip_consumes_continuously_pinned_tiny_wheel(tmp_path, monkeypatch, outcome):
    """Real pip + real Job Object, no ACT install. The child itself refuses socket/process I/O."""
    test_env = tmp_path / 'disposable-env'
    venv.EnvBuilder(with_pip=False, symlinks=False).create(test_env)
    site = test_env / 'Lib/site-packages'
    bundled = Path(ensurepip.__file__).parent / '_bundled'
    pip_wheel, = bundled.glob('pip-*.whl')
    # Bootstrap installer tooling from CPython's existing bundled wheel, offline.
    with zipfile.ZipFile(pip_wheel) as archive:
        for entry in archive.infolist():
            target = site / entry.filename
            assert target.resolve().is_relative_to(site.resolve())
        archive.extractall(site)
    source = tmp_path / 'source.whl'
    data = tiny_wheel(source)
    wheel_dir = tmp_path / 'wheels'
    wheel_dir.mkdir()
    wheel = wheel_dir / 'act_disposable_proof-1.0-py3-none-any.whl'
    lock = tmp_path / 'effective.txt'
    lock_bytes = ('act-disposable-proof==1.0 --hash=sha256:' + hashlib.sha256(data).hexdigest() + '\n').encode()
    lines = []
    scratch = tmp_path / 'temp'
    scratch.mkdir()
    monkeypatch.setattr(rt, 'repo_root', lambda: tmp_path)
    monkeypatch.setenv('PIP_TARGET', str(tmp_path / 'ambient-env-target'))
    monkeypatch.setenv('PIP_INDEX_URL', 'https://egress.invalid/simple')
    monkeypatch.setenv('PYTHONPATH', str(tmp_path / 'ambient-python'))
    child_env = setup.installer_environment()
    assert child_env['PIP_CONFIG_FILE'] == os.devnull and 'PIP_TARGET' not in child_env
    assert 'PIP_INDEX_URL' not in child_env and 'PYTHONPATH' not in child_env
    # Per-venv config is real and hostile; os.devnull disables it even in isolated mode.
    (test_env / 'pip.ini').write_text('[global]\nindex-url = https://egress.invalid/simple\n'
        'extra-index-url = https://egress.invalid/extra\ntarget = ' + str(tmp_path / 'ambient-config-target') + '\n')
    with qp._private_file(tmp_path, wheel) as wheel_stream, qp._private_file(tmp_path, lock) as lock_stream:
        wheel_stream.write(b'x' * len(data) if outcome == 'wrong-hash' else data)
        wheel_stream.flush()
        lock_stream.write(lock_bytes)
        lock_stream.flush()
        command = qp._pip_command(test_env / 'Scripts/python.exe', wheel_dir, lock,
                                  [(wheel, hashlib.sha256(data).hexdigest())])
        # A directory pin alone permits addition; direct roots must constrain the actual file.
        alternate = wheel_dir / 'act_disposable_proof-1.0-999-py3-none-any.whl'
        alternate.write_bytes(b'unapproved alternative')
        attempted = []
        def on_line(line):
            lines.append(line)
            if not attempted:
                for mutate in (lambda: wheel.write_bytes(b'evil'), lambda: wheel.unlink(),
                               lambda: wheel.rename(tmp_path / 'replaced.whl')):
                    with pytest.raises(OSError):
                        mutate()
                attempted.append(True)
        completions = len(qp.NATIVE_COMPLETIONS)
        if outcome == 'cancel':
            with pytest.raises(setup.SetupCancelled):
                NATIVE_RUN(command, env=child_env, cwd=wheel_dir, on_line=on_line,
                           cancel_check=lambda: bool(attempted))
            code = 'cancelled'
        else:
            code = NATIVE_RUN(command, env=child_env, cwd=wheel_dir, on_line=on_line)
        (tmp_path / 'native-output.json').write_text(json.dumps(lines, indent=2))
        assert len(qp.NATIVE_COMPLETIONS) == completions + 1
        assert qp.NATIVE_COMPLETIONS[-1]['active'] == 0 and qp.NATIVE_COMPLETIONS[-1]['members'] >= 1
        if outcome == 'success':
            assert code == 0, lines
            assert (site / 'act_disposable_proof.py').read_text() == 'VALUE = 73\n'
        elif outcome == 'wrong-hash':
            assert code != 0 and not (site / 'act_disposable_proof.py').exists(), lines
            assert any('HASHES' in line or 'hashes' in line for line in lines), lines
        assert attempted
        assert not (tmp_path / 'ambient-env-target').exists() and not (tmp_path / 'ambient-config-target').exists()
        if outcome != 'cancel':
            audit, = [json.loads(line[len('@@OFFLINE '):]) for line in lines if line.startswith('@@OFFLINE ')]
            # pip/urllib3's IPv6 capability check requests a socket; platform.py
            # tries shell version probes. ALL are refused before creation. No
            # connect, name resolution, bind or send event may even be attempted.
            assert set(audit) <= {'socket.__new__', 'subprocess.Popen'}, audit
        assert not any('offline pip refused' in line for line in lines)
    (tmp_path / 'native-proof.json').write_text(json.dumps({'argv': command, 'output': lines,
        'pip_wheel': pip_wheel.name, 'attempted_mutations_refused': 3, 'returncode': code,
        'job': qp.NATIVE_COMPLETIONS[-1]}, indent=2))
