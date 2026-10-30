"""M3 wheel provenance checks are read-only and grant no portable supply approval."""
import hashlib
import io
import zipfile

import pytest

from tts import qwen3_package_manifest as qm

pytestmark = pytest.mark.usefixtures('production_writes_refused')


def wheel_bytes(*, name='sox', version='1.5.0', tag='py3-none-any', requires=(), extra=None,
                metadata_name=None, metadata_version=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        prefix = f'{name}-{version}.dist-info/'
        archive.writestr(zipfile.ZipInfo(prefix + 'METADATA'), 'Metadata-Version: 2.1\nName: ' + (metadata_name or name) +
                         '\nVersion: ' + (metadata_version or version) + '\n' +
                         ''.join('Requires-Dist: ' + r + '\n' for r in requires))
        archive.writestr(zipfile.ZipInfo(prefix + 'WHEEL'), 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: ' + tag + '\n')
        archive.writestr(zipfile.ZipInfo(prefix + 'RECORD'), '')
        archive.writestr(zipfile.ZipInfo(name + '/__init__.py'), 'VALUE = 73\n')
        if extra:
            archive.writestr(zipfile.ZipInfo(extra[0]), extra[1])
    return output.getvalue()


def candidate(tmp_path, data):
    path = tmp_path / 'candidate.whl'
    path.write_bytes(data)
    artifact = qm.Artifact('sox', '1.5.0', 'sox-1.5.0-py3-none-any.whl', len(data),
                           hashlib.sha256(data).hexdigest(), ('py3-none-any',), None)
    return artifact, qm.LocalArtifact(path, artifact.filename, None)


def test_exact_wheel_metadata_is_not_portable_authorization(tmp_path):
    artifact, local = candidate(tmp_path, wheel_bytes(requires=('numpy>=1.9',)))
    assert qm.verify_wheel_metadata(artifact, local) == {
        'name': 'sox', 'version': '1.5.0', 'tags': ['py3-none-any'], 'requires_dist': ['numpy>=1.9']}
    assert artifact.sha256 != qm.SOX_SOURCE_SHA256


@pytest.mark.parametrize('change', ['name', 'version', 'tag', 'duplicate', 'escape', 'data', 'script',
                                   'pth', 'case-alias', 'device', 'trailing-dot'])
def test_internal_wheel_identity_and_install_paths_are_checked(tmp_path, change):
    kwargs = {'name': 'different'} if change == 'name' else {'version': '1.5.1'} if change == 'version' else {
        'tag': 'cp311-cp311-win_amd64'} if change == 'tag' else {}
    if change in ('duplicate', 'escape', 'data', 'script', 'pth', 'case-alias', 'device', 'trailing-dot'):
        kwargs['extra'] = {
            'duplicate': ('another-1.5.0.dist-info/METADATA', 'Name: sox\nVersion: 1.5.0\n'),
            'escape': ('../outside.py', 'bad'),
            'data': ('sox-1.5.0.data/data/escape', 'bad'),
            'script': ('sox-1.5.0.data/scripts/payload.exe', 'bad'),
            'pth': ('startup.pth', 'import arbitrary'),
            'case-alias': ('SOX/__init__.py', 'bad'),
            'device': ('sox/NUL.py', 'bad'),
            'trailing-dot': ('sox./payload.py', 'bad'),
        }[change]
    artifact, local = candidate(tmp_path, wheel_bytes(**kwargs))
    with pytest.raises(qm.ManifestError):
        qm.verify_wheel_metadata(artifact, local)


def test_metadata_validator_rechecks_hash_and_size(tmp_path):
    artifact, local = candidate(tmp_path, wheel_bytes())
    local.path.write_bytes(local.path.read_bytes().replace(b'VALUE', b'OTHER'))
    with pytest.raises(qm.ManifestError, match='hash'):
        qm.verify_wheel_metadata(artifact, local)


@pytest.mark.parametrize('field', ['metadata_name', 'metadata_version'])
def test_internal_headers_must_match_even_when_paths_and_filename_match(tmp_path, field):
    artifact, local = candidate(tmp_path, wheel_bytes(**{field: 'different' if field == 'metadata_name' else '1.5.1'}))
    with pytest.raises(qm.ManifestError):
        qm.verify_wheel_metadata(artifact, local)
