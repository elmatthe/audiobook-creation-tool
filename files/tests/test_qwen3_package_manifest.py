"""Reviewed package identities are read-only inputs, never an installer."""
import hashlib
import dataclasses
import json
from pathlib import Path

import pytest

from tts import qwen3_package_manifest as packages

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / 'scripts/qwen3-requirements.txt'
MANIFEST = ROOT / 'scripts/qwen3-artifacts.json'
pytestmark = pytest.mark.usefixtures('production_writes_refused')


def test_complete_reviewed_runtime_coverage_and_wheel_lock_identity():
    manifest = packages.load_manifest(MANIFEST.read_bytes(), LOCK.read_bytes())
    assert len(manifest.runtime) == 89
    assert len({a.name for a in manifest.runtime}) == 89
    assert sum(a.filename.endswith('.whl') for a in manifest.runtime) == 88
    effective = packages.effective_lock(manifest)
    assert effective == packages.effective_lock(manifest)
    assert len(effective.splitlines()) == 89
    assert hashlib.sha256(effective).hexdigest() == manifest.effective_lock_sha256
    assert manifest.effective_lock_sha256 == '5c600759b04ae1ce23e6503b47eba5497b6240390de92fe44a897692c92882a4'
    assert packages.SOX_SOURCE_SHA256.encode() not in effective
    assert packages.SOX_WHEEL_SHA256.encode() in effective


def test_changed_original_lock_is_refused():
    with pytest.raises(packages.ManifestError, match='lock'):
        packages.load_manifest(MANIFEST.read_bytes(), LOCK.read_bytes() + b'\n')


@pytest.mark.parametrize('change', [
    lambda d: d['runtime'].pop(),
    lambda d: d['runtime'].__setitem__(1, d['runtime'][0]),
    lambda d: d['runtime'][0].update(filename='other-1.12.0-py3-none-any.whl'),
    lambda d: d['runtime'][0].update(filename='accelerate-1.12.0-cp311-cp311-linux_x86_64.whl',
                                      tags=['cp311-cp311-linux_x86_64']),
    lambda d: d['runtime'][0].update(tags=['cp312-cp312-win_amd64']),
    lambda d: d['runtime'][0].update(size=1),
    lambda d: d['runtime'][0].update(size=True),
    lambda d: d['runtime'][0].update(sha256='0' * 64),
    lambda d: d['runtime'][0].update(source_url=d['runtime'][0]['source_url'].replace('/9f/', '/00/')),
    lambda d: d['runtime'][0].update(source_url='https://elsewhere.invalid/' + d['runtime'][0]['filename']),
    lambda d: d['runtime'][0].update(source_url='https://[malformed/artifact.whl'),
    lambda d: d['runtime'][0].update(extra='unreviewed'),
    lambda d: d['runtime'][0].update(version='1.12.1'),
    lambda d: d['target'].update(platform='linux_x86_64'),
    lambda d: d['target'].update(python='3.13'),
    lambda d: d.update(version=True),
    lambda d: d['sox_derivative']['artifact'].update(sha256=packages.SOX_SOURCE_SHA256),
    lambda d: d['sox_derivative'].update(source_sha256=packages.SOX_WHEEL_SHA256),
    lambda d: d['sox_derivative']['artifact'].update(sha256='0' * 64),
    lambda d: d['sox_derivative'].update(portable_supply='available'),
    lambda d: d['sox_derivative'].update(build_authorized=True),
    lambda d: d['build_only']['backend'].update(version='84.2.2', filename='setuptools-84.2.2-py3-none-any.whl'),
], ids=['missing', 'duplicate', 'filename', 'incompatible-tag', 'wrong-tags', 'size', 'bool-size', 'hash',
        'altered-origin-path', 'unapproved-origin', 'malformed-origin', 'extra-field', 'version', 'platform', 'interpreter',
        'bool-schema', 'source-as-wheel', 'wheel-as-source', 'substitute-derivative', 'portable-claim',
        'build-authority', 'build-version'])
def test_no_recalculated_self_hash_can_approve_changed_content(change):
    document = json.loads(MANIFEST.read_bytes())
    change(document)
    del document['content_sha256']
    document['content_sha256'] = hashlib.sha256(json.dumps(
        document, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    with pytest.raises(packages.ManifestError):
        packages.load_manifest(json.dumps(document).encode(), LOCK.read_bytes())


@pytest.mark.parametrize('raw', [b'{}', b'[]', b'not json', b'{"schema":1,"schema":2}', b'{"a":NaN}',
                                  b' ' * (128 * 1024 + 1)],
                         ids=['empty', 'array', 'invalid', 'duplicate-key', 'nan', 'oversized'])
def test_malformed_manifest(raw):
    with pytest.raises(packages.ManifestError):
        packages.load_manifest(raw, LOCK.read_bytes())


def test_wrong_requested_target_is_refused_and_crlf_preserves_original_identity():
    with pytest.raises(packages.ManifestError, match='platform/interpreter'):
        packages.load_manifest(MANIFEST.read_bytes(), LOCK.read_bytes(), target={**packages.TARGET, 'python': '3.11'})
    lf = LOCK.read_bytes().replace(b'\r\n', b'\n')
    assert packages.load_manifest(MANIFEST.read_bytes(), lf) == packages.load_manifest(
        MANIFEST.read_bytes(), lf.replace(b'\n', b'\r\n'))


def test_effective_lock_keeps_original_88_hashes_and_has_no_executable_options():
    manifest = packages.load_manifest(MANIFEST.read_bytes(), LOCK.read_bytes())
    lines = packages.effective_lock(manifest).decode().splitlines()
    for original, line in zip(manifest.runtime, lines):
        sha = packages.SOX_WHEEL_SHA256 if original.name == 'sox' else original.sha256
        assert line == f'{original.name}=={original.version} --hash=sha256:{sha}'
    assert all('://' not in line and line.count('--') == 1 for line in lines)


def test_manually_forged_manifest_cannot_insert_package_options_or_alternative_hashes():
    manifest = packages.load_manifest(MANIFEST.read_bytes(), LOCK.read_bytes())
    forged_artifact = dataclasses.replace(manifest.runtime[0], name='--index-url https://example.invalid')
    forged = dataclasses.replace(manifest, runtime=(forged_artifact, *manifest.runtime[1:]))
    with pytest.raises(packages.ManifestError, match='untrusted'):
        packages.effective_lock(forged)
    with pytest.raises(packages.ManifestError, match='untrusted'):
        packages.verified_wheel_lock(forged, {}, purpose='controlled-local-development')


@pytest.mark.parametrize('change', ['filename', 'origin', 'size', 'hash', 'missing'])
def test_tiny_local_artifact_identity_must_match_exactly(tmp_path, change):
    data = b'synthetic artifact'
    path = tmp_path / 'stand-in'
    path.write_bytes(data)
    artifact = packages.Artifact('demo', '1.0', 'demo-1.0-py3-none-any.whl', len(data),
                                 hashlib.sha256(data).hexdigest(), ('py3-none-any',),
                                 'https://example.invalid/demo-1.0-py3-none-any.whl')
    candidate = packages.LocalArtifact(path, artifact.filename, artifact.source_url)
    packages.verify_local(artifact, candidate)
    if change == 'filename':
        candidate = dataclasses.replace(candidate, filename='demo-1.1-py3-none-any.whl')
    elif change == 'origin':
        candidate = dataclasses.replace(candidate, source_url='https://elsewhere.invalid/wheel')
    elif change == 'size':
        path.write_bytes(data + b'x')
    elif change == 'hash':
        path.write_bytes(b'x' * len(data))
    else:
        path.unlink()
    with pytest.raises(packages.ManifestError):
        packages.verify_local(artifact, candidate)


def test_no_fresh_machine_supply_or_automatic_local_substitution(tmp_path):
    manifest = packages.load_manifest(MANIFEST.read_bytes(), LOCK.read_bytes())
    with pytest.raises(packages.ManifestError, match='portable sox'):
        packages.verified_wheel_lock(manifest, {})
    candidates = {a.name: packages.LocalArtifact(tmp_path / a.filename, a.filename, a.source_url)
                  for a in manifest.wheels if a.name != 'sox'}
    with pytest.raises(packages.ManifestError, match='missing'):
        packages.verified_wheel_lock(manifest, candidates, purpose='controlled-local-development')
    # A newly hashed replacement cannot inherit the local derivative approval.
    replacement = tmp_path / manifest.sox_wheel.filename
    replacement.write_bytes(b'x' * manifest.sox_wheel.size)
    with pytest.raises(packages.ManifestError, match='hash'):
        packages.verify_local(manifest.sox_wheel, packages.LocalArtifact(replacement, replacement.name, None))


def test_existing_healthy_engine_needs_no_new_manifest_receipt(tmp_path, monkeypatch):
    from test_qwen3_runtime import install_environment, sandbox
    from tts import qwen3_runtime as rt

    root = sandbox.__wrapped__(tmp_path, monkeypatch)
    install_environment(root, requirements=LOCK.read_text(encoding='utf-8'))
    state_path = rt.state_path()
    before = state_path.read_bytes()
    assert rt.environment_status()[0]
    original = rt.requirements_sha256()
    packages.load_manifest(MANIFEST.read_bytes(), LOCK.read_bytes())
    assert original == packages.ORIGINAL_LOCK_SHA256 == rt.requirements_sha256()
    assert state_path.read_bytes() == before and rt.environment_status()[0]
