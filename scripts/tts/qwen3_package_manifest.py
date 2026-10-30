"""Reviewed Windows/CPython package identities. Read-only; no pip, build or acquisition.

``effective_lock`` maps identities only. ``verified_wheel_lock`` additionally proves a supplied local set. Neither
creates an installation receipt or authorizes installation. A future installer must seal/revalidate inputs at use.
The original runtime requirements identity remains the health contract for existing environments.

Version 2 adds one closed, code-pinned record: the commit-pinned published location of the ACT-controlled sox
derivative. Publication is artifact identity only. ``portable_supply='pending'`` remains the separate fact that no
production fresh-machine use is approved; only the explicit non-production qualification purpose may select it.
"""
from __future__ import annotations

import hashlib
import email
import itertools
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote, urlsplit

SCHEMA = 'act-qwen3-artifacts'
VERSION = 2
TARGET = {'implementation': 'CPython', 'python': '3.12', 'platform': 'win_amd64'}
ORIGINAL_LOCK_SHA256 = 'b1851204f0852fbdbf179186800727cba0e99b006adca0c43e6301d858a0ae6e'
# Reviewed version-2 content (M3 Reference B). The retired version-1 anchor was 34922719...fbd79.
REVIEWED_MANIFEST_SHA256 = '8ef2179cd7a0f3e0e979b1e9d907aa02c6bb8fe67617b9d4e3dff5ce3566a2e2'
SOX_SOURCE_SHA256 = '12c7be5bb1f548d891fe11e82c08cf5f1a1d74e225298f60082e5aeb2469ada0'
SOX_WHEEL_SHA256 = 'd7f2d5a2390fa235b4195700e72d5bd9b507d88e4598cadcfd17aaccae2b8934'
# Supply commit A: reviewed and endpoint-qualified once. The branch that keeps it reachable is NOT an identity.
SOX_SUPPLY_REPOSITORY = 'elmatthe/audiobook-creation-tool'
SOX_SUPPLY_COMMIT = 'b7e1b1aea9cd78c67c540b556a64392f22d0bfc1'
SOX_SUPPLY_PATH = ('supply/python/sox/1.5.0/sha256-d7f2d5a2390fa235b4195700e72d5bd9b507d88e4598cadcfd17aaccae2b8934/'
                   'sox-1.5.0-py3-none-any.whl')
SOX_SUPPLY_URL = ('https://raw.githubusercontent.com/elmatthe/audiobook-creation-tool/'
                  'b7e1b1aea9cd78c67c540b556a64392f22d0bfc1/' + SOX_SUPPLY_PATH)
SOX_PUBLICATION = 'published-endpoint-qualified'
LOCAL_SUPPLY_PURPOSES = ('controlled-local-development', 'synthetic-qualification')
# Controlled, non-production qualification only. Production planning keeps purpose='fresh-machine'.
PUBLISHED_SUPPLY_PURPOSE = 'published-supply-qualification'
_HASH = re.compile(r'[a-f0-9]{64}')
_PIN = re.compile(r'([a-z0-9]+(?:-[a-z0-9]+)*)==([0-9][A-Za-z0-9.+]*) --hash=sha256:([a-f0-9]{64})')
_ARTIFACT_KEYS = {'name', 'version', 'filename', 'size', 'sha256', 'tags', 'source_url'}
_DISTRIBUTION_KEYS = {'repository', 'commit', 'path', 'url', 'size', 'sha256', 'tags', 'publication'}


class ManifestError(ValueError):
    """An unreviewed identity, malformed input, incompatible target or unavailable local supply."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _keys(value, keys: set, label: str) -> dict:
    _require(type(value) is dict and set(value) == keys, f'malformed {label} fields')
    return value


def _pairs(pairs) -> dict:
    _require(len({k for k, _ in pairs}) == len(pairs), 'duplicate manifest key')
    return dict(pairs)


def _invalid_constant(value):
    raise ManifestError(f'invalid JSON constant: {value}')


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def _pins(lock: bytes) -> dict[str, tuple[str, str]]:
    _require(type(lock) is bytes, 'runtime lock must be bytes')
    lock = lock.replace(b'\r\n', b'\n')
    _require(hashlib.sha256(lock).hexdigest() == ORIGINAL_LOCK_SHA256, 'original runtime lock SHA changed')
    pins = {}
    for line in lock.decode('utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        match = _PIN.fullmatch(line)
        _require(match is not None, 'runtime lock contains unapproved requirement syntax')
        name, version, sha = match.groups()
        _require(name not in pins, 'duplicate runtime lock pin')
        pins[name] = (version, sha)
    _require(len(pins) == 89, 'runtime lock must have 89 pins')
    return pins


def wheel_tags(filename: str, name: str, version: str) -> tuple[str, ...]:
    """Strict wheel filename identity; expand compressed tags without loading packaging or pip."""
    _require(type(filename) is str and filename.endswith('.whl'), 'expected wheel filename')
    parts = filename[:-4].split('-')
    _require(len(parts) == 5, 'unreviewed wheel filename/build tag')
    _require(re.sub(r'[-_.]+', '-', parts[0]).lower() == name and parts[1] == version,
             'wheel filename does not match package name/version')
    _require(all(re.fullmatch(r'[a-z0-9_]+(?:\.[a-z0-9_]+)*', p) for p in parts[2:]), 'invalid wheel tag')
    return tuple(sorted('-'.join(tag) for tag in itertools.product(*(p.split('.') for p in parts[2:]))))


def _compatible(tag: str) -> bool:
    python, abi, platform = tag.split('-')
    if platform not in ('any', 'win_amd64'):
        return False
    if abi == 'none' and python in {'py3', *(f'py3{i}' for i in range(13))}:
        return True
    if platform == 'win_amd64':
        return (python == 'cp312' and abi in ('cp312', 'none')) or (
            abi == 'abi3' and python in {f'cp3{i}' for i in range(2, 13)})
    return False


@dataclass(frozen=True)
class Artifact:
    name: str
    version: str
    filename: str
    size: int
    sha256: str
    tags: tuple[str, ...]
    source_url: str | None


def _artifact(value, *, local: bool = False) -> Artifact:
    a = _keys(value, _ARTIFACT_KEYS, 'artifact')
    for key in ('name', 'version', 'filename', 'sha256'):
        _require(type(a[key]) is str, f'invalid artifact {key}')
    _require(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', a['name']) is not None, 'invalid package name')
    _require(re.fullmatch(r'[0-9][A-Za-z0-9.+]*', a['version']) is not None, 'invalid package version')
    _require(_HASH.fullmatch(a['sha256']) is not None, 'invalid artifact hash')
    _require(type(a['size']) is int and a['size'] > 0, 'invalid artifact size')
    _require(type(a['tags']) is list and all(type(t) is str for t in a['tags']), 'invalid wheel tags')
    if a['filename'].endswith('.whl'):
        tags = wheel_tags(a['filename'], a['name'], a['version'])
        _require(tuple(a['tags']) == tags and any(_compatible(t) for t in tags), 'wrong or incompatible wheel tags')
    else:
        _require(a['name'] == 'sox' and a['version'] == '1.5.0' and a['filename'] == 'sox-1.5.0.tar.gz'
                 and a['tags'] == [], 'unapproved source archive')
    url = a['source_url']
    if local:
        _require(url is None, 'local-only artifact cannot acquire a publisher origin')
    else:
        _require(type(url) is str, 'missing artifact origin')
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise ManifestError('malformed artifact origin') from None
        _require(parsed.scheme == 'https' and parsed.netloc in ('files.pythonhosted.org', 'download-r2.pytorch.org')
                 and not parsed.query and not parsed.fragment
                 and unquote(parsed.path.rsplit('/', 1)[-1]) == a['filename'], 'unapproved artifact origin')
    return Artifact(a['name'], a['version'], a['filename'], a['size'], a['sha256'], tuple(a['tags']), url)


def supply_reference(repository, commit, path, url) -> None:
    """Accept only the exact commit-pinned raw location of the one reviewed derivative.

    Compared with the trusted constructed string first, then re-parsed defensively. No branch, tag, short
    commit, other repository/host/port/userinfo, encoding, dot segment, query or fragment can be equivalent.
    """
    _require(all(type(v) is str for v in (repository, commit, path, url)), 'malformed supply reference')
    _require(re.fullmatch(r'[a-f0-9]{40}', commit) is not None and commit == SOX_SUPPLY_COMMIT,
             'supply revision must be the approved full commit')
    _require(repository == SOX_SUPPLY_REPOSITORY, 'unapproved supply repository')
    _require(path == SOX_SUPPLY_PATH, 'unapproved supply path')
    _require(url == SOX_SUPPLY_URL, 'unapproved supply URL')
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise ManifestError('malformed supply URL') from None
    segments = parsed.path.split('/')[1:]
    _require(parsed.scheme == 'https' and parsed.netloc == 'raw.githubusercontent.com' and port is None
             and parsed.username is None and parsed.password is None and not parsed.query
             and not parsed.fragment and re.search(r'[?#%@\\\s]', url) is None
             and parsed.path == '/' + repository + '/' + commit + '/' + path
             and all(s and s not in ('.', '..') for s in segments), 'non-canonical supply URL')


@dataclass(frozen=True)
class SupplyDistribution:
    """Published immutable identity of the sox derivative. Not installation or production authority."""
    repository: str
    commit: str
    path: str
    url: str
    size: int
    sha256: str
    tags: tuple[str, ...]
    publication: str


def _distribution(value, wheel: Artifact) -> SupplyDistribution:
    d = _keys(value, _DISTRIBUTION_KEYS, 'sox distribution')
    supply_reference(d['repository'], d['commit'], d['path'], d['url'])
    _require(type(d['size']) is int and type(d['sha256']) is str and type(d['tags']) is list
             and all(type(t) is str for t in d['tags']), 'malformed sox distribution identity')
    # The published record names the SAME reviewed derivative; it cannot carry or define another artifact.
    _require((d['size'], d['sha256'], tuple(d['tags'])) == (wheel.size, wheel.sha256, wheel.tags)
             == (40164, SOX_WHEEL_SHA256, ('py3-none-any',))
             and d['path'].split('/')[-2:] == ['sha256-' + wheel.sha256, wheel.filename],
             'distribution is not the approved sox derivative')
    _require(d['publication'] == SOX_PUBLICATION, 'unreviewed sox publication state')
    return SupplyDistribution(d['repository'], d['commit'], d['path'], d['url'], d['size'], d['sha256'],
                              tuple(d['tags']), d['publication'])


@dataclass(frozen=True)
class ReviewedManifest:
    runtime: tuple[Artifact, ...]
    sox_wheel: Artifact
    sox_distribution: SupplyDistribution
    content_sha256: str
    _document: bytes = field(repr=False)
    _requirements: bytes = field(repr=False)

    @property
    def wheels(self) -> tuple[Artifact, ...]:
        return tuple(self.sox_wheel if a.name == 'sox' else a for a in self.runtime)

    @property
    def effective_lock_sha256(self) -> str:
        return hashlib.sha256(effective_lock(self)).hexdigest()


def load_manifest(raw: bytes, requirements: bytes, *, target: dict | None = None) -> ReviewedManifest:
    """Accept only the reviewed content identity and unchanged original lock, for the exact target.

    A recalculated self-hash cannot approve a changed source, wheel, size or build dependency. Review must change the
    independent code anchor too. No filesystem, platform probe or existing-environment receipt is consulted.
    """
    pins = _pins(requirements)
    _require(type(raw) is bytes and len(raw) <= 128 * 1024, 'missing or oversized manifest')
    try:
        d = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ManifestError(f'invalid manifest: {exc}') from None
    _keys(d, {'schema', 'version', 'target', 'runtime_lock', 'runtime', 'sox_derivative', 'build_only',
              'content_sha256'}, 'manifest')
    # Version 1 is retired, not reinterpreted: it has no distribution record and its anchor is no longer reviewed.
    _require(d['schema'] == SCHEMA and type(d['version']) is int and d['version'] == VERSION,
             'unsupported manifest schema')
    _require(d['target'] == TARGET and (target is None or target == TARGET), 'wrong platform/interpreter')
    _require(d['runtime_lock'] == {'path': 'scripts/qwen3-requirements.txt', 'sha256_lf': ORIGINAL_LOCK_SHA256},
             'wrong original lock identity')
    _require(type(d['runtime']) is list and len(d['runtime']) == 89, 'manifest must contain 89 runtime artifacts')
    runtime = tuple(_artifact(a) for a in d['runtime'])
    _require(len({a.name for a in runtime}) == 89, 'duplicate runtime artifact')
    _require({a.name: (a.version, a.sha256) for a in runtime} == pins, 'runtime versions/hashes differ from lock')
    _require(tuple(a.name for a in runtime) == tuple(sorted(pins)), 'runtime artifacts must be sorted')
    _require(sum(bool(a.tags) for a in runtime) == 88, 'expected 88 original wheels and sox source')
    source = next(a for a in runtime if a.name == 'sox')
    _require(source.sha256 == SOX_SOURCE_SHA256 and source.size == 63905, 'wrong sox source identity')
    derivative = _keys(d['sox_derivative'], {'artifact', 'source_sha256', 'authorization', 'publisher_wheel',
                                          'portable_supply', 'build_authorized', 'distribution'}, 'sox derivative')
    wheel = _artifact(derivative['artifact'], local=True)
    _require((wheel.name, wheel.version, wheel.filename, wheel.size, wheel.sha256, wheel.tags) == (
        'sox', '1.5.0', 'sox-1.5.0-py3-none-any.whl', 40164, SOX_WHEEL_SHA256, ('py3-none-any',)),
        'unapproved sox derivative; source and wheel hashes are distinct')
    _require(derivative['source_sha256'] == source.sha256 and derivative['authorization'] == 'existing-local-only'
             and derivative['publisher_wheel'] is False and derivative['portable_supply'] == 'pending'
             and derivative['build_authorized'] is False, 'sox supply/build authorization changed')
    distribution = _distribution(derivative['distribution'], wheel)
    build = _keys(d['build_only'], {'status', 'frontend_origin', 'frontend', 'backend'}, 'build-only evidence')
    _require(build['status'] == 'evidence-only-no-build'
             and build['frontend_origin'] == 'CPython-3.12.10-ensurepip', 'build evidence is not build authorization')
    _artifact(build['frontend'], local=True)
    _artifact(build['backend'])
    digest = d.pop('content_sha256')
    _require(type(digest) is str and digest == hashlib.sha256(_canonical(d)).hexdigest()
             and digest == REVIEWED_MANIFEST_SHA256, 'unreviewed manifest content identity')
    return ReviewedManifest(runtime, wheel, distribution, digest, _canonical({**d, 'content_sha256': digest}),
                             requirements.replace(b'\r\n', b'\n'))


def _checked_manifest(manifest: ReviewedManifest) -> ReviewedManifest:
    """Do not let a manually constructed/replaced dataclass bypass the reviewed mapping boundary."""
    _require(type(manifest) is ReviewedManifest, 'untrusted manifest object')
    reviewed = load_manifest(manifest._document, manifest._requirements)
    _require(manifest == reviewed, 'untrusted manifest object differs from reviewed content')
    return reviewed


def published_sox_source(manifest: ReviewedManifest) -> dict:
    """Exact v3 source for the remote derivative row; identity only, no availability or eligibility claim."""
    d = _checked_manifest(manifest).sox_distribution
    supply_reference(d.repository, d.commit, d.path, d.url)
    return {'kind': 'pinned-https', 'url': d.url, 'revision': d.commit}


def effective_lock(manifest: ReviewedManifest) -> bytes:
    """Deterministic identity mapping only; does not prove availability or grant execution authority."""
    reviewed = _checked_manifest(manifest)
    return ''.join(f'{a.name}=={a.version} --hash=sha256:{a.sha256}\n' for a in reviewed.wheels).encode('ascii')


@dataclass(frozen=True)
class LocalArtifact:
    """A candidate location plus its asserted filename/origin. Assertions alone never prove its bytes."""
    path: Path
    filename: str
    source_url: str | None


def verify_local(artifact: Artifact, candidate: LocalArtifact) -> None:
    """Read and hash a candidate. This is a point-in-time proof, not a sealed install view or durable receipt."""
    _require(candidate.filename == artifact.filename, 'wrong wheel filename')
    _require(candidate.source_url == artifact.source_url, 'altered artifact origin')
    try:
        _require(candidate.path.is_file() and candidate.path.stat().st_size == artifact.size,
                 f'missing artifact or wrong size: {artifact.filename}')
        digest, total = hashlib.sha256(), 0
        with candidate.path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                _require(total <= artifact.size, 'artifact exceeds size')
                digest.update(chunk)
        _require(total == artifact.size and digest.hexdigest() == artifact.sha256, 'wrong artifact size/hash')
    except OSError as exc:
        raise ManifestError(f'artifact unavailable: {artifact.filename}: {exc}') from None


def verified_wheel_lock(manifest: ReviewedManifest, candidates: Mapping[str, LocalArtifact], *,
                        purpose: str = 'fresh-machine') -> bytes:
    """Require the exact complete local wheel set. Missing sox is a blocker, never permission to build.

    Current approval is limited to controlled local development/synthetic qualification. Fresh-machine supply,
    redistribution, building and actual installation are not authorized by this API.
    """
    manifest = _checked_manifest(manifest)
    _require(purpose in ('controlled-local-development', 'synthetic-qualification'),
             'BLOCKED: portable sox supply/build qualification pending; local-only approval')
    _require(set(candidates) == {a.name for a in manifest.wheels}, 'missing or unapproved wheel artifact')
    for artifact in manifest.wheels:
        verify_local(artifact, candidates[artifact.name])
    return effective_lock(manifest)


def verify_wheel_metadata(artifact: Artifact, candidate: LocalArtifact, *, check_cancel=lambda: None) -> dict:
    """Inspect a hash-verified pure wheel without importing, extracting or approving supply.

    Intended for the sox derivative and English model, whose install footprint must
    stay inside site-packages. No .data schemes, scripts, links or ambiguous metadata.
    A compatible filename alone says nothing about internal identity or runtime health.
    Callers consuming bytes must additionally hold a sealed private copy throughout use.
    """
    import os
    import stat
    from pathlib import PurePosixPath

    _require(candidate.filename == artifact.filename and candidate.source_url == artifact.source_url,
             'wheel filename/origin mismatch')
    tags = wheel_tags(artifact.filename, artifact.name, artifact.version)
    _require(tags == artifact.tags and any(_compatible(t) for t in tags), 'incompatible wheel')
    prefix = artifact.name.replace('-', '_') + '-' + artifact.version + '.dist-info/'
    try:
        with candidate.path.open('rb') as stream:
            check_cancel()
            before = os.fstat(stream.fileno())
            _require(stat.S_ISREG(before.st_mode) and before.st_size == artifact.size, 'wrong wheel size')
            digest, total = hashlib.sha256(), 0
            while block := stream.read(min(1024 * 1024, artifact.size - total + 1)):
                check_cancel()
                total += len(block)
                _require(total <= artifact.size, 'wheel grew during inspection')
                digest.update(block)
            _require(total == artifact.size and digest.hexdigest() == artifact.sha256, 'wrong wheel hash')
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                entries = archive.infolist()
                _require(len(entries) <= 8192 and len({e.filename.casefold() for e in entries}) == len(entries),
                         'oversized/duplicate wheel entries')
                identities = []
                for entry in entries:
                    check_cancel()
                    name = entry.filename
                    parts = PurePosixPath(name).parts
                    _require(parts and not name.startswith('/') and '\\' not in name and ':' not in name
                             and all(p not in ('.', '..') for p in name.rstrip('/').split('/'))
                             and all(not p.endswith((' ', '.')) and not re.fullmatch(
                                 r'(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p) for p in parts)
                             and not any(p.endswith('.data') for p in parts)
                             and not name.lower().endswith('.pth')
                             and not stat.S_ISLNK(entry.external_attr >> 16), 'unsafe wheel install path')
                    if name.endswith(('.dist-info/METADATA', '.dist-info/WHEEL')):
                        identities.append(name)
                _require(sorted(identities) == [prefix + 'METADATA', prefix + 'WHEEL'],
                         'ambiguous wheel identity')
                def metadata(name):
                    _require(archive.getinfo(prefix + name).file_size <= 64 * 1024, 'oversized wheel metadata')
                    return email.message_from_bytes(archive.read(prefix + name))
                package, wheel = metadata('METADATA'), metadata('WHEEL')
                _require(package.get_all('Name') == [artifact.name.replace('-', '_')]
                         or package.get_all('Name') == [artifact.name], 'internal wheel name mismatch')
                _require(package.get_all('Version') == [artifact.version]
                         and wheel.get_all('Wheel-Version') == ['1.0']
                         and wheel.get_all('Root-Is-Purelib') == ['true']
                         and sorted(wheel.get_all('Tag', [])) == list(tags), 'internal wheel version/tags mismatch')
                result = {'name': artifact.name, 'version': artifact.version, 'tags': list(tags),
                          'requires_dist': package.get_all('Requires-Dist', [])}
            after = os.fstat(stream.fileno())
            _require(all(getattr(before, k) == getattr(after, k) for k in (
                'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')), 'wheel changed during inspection')
            return result
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise ManifestError(f'wheel metadata unavailable: {exc}') from None
