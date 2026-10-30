"""M3 closed disposable English-wheel consumer. No production installation authority.

The accepted v3 terms version 1 authorizes transfer only. It cannot disclose a
main consumer target/recovery operation. Do not attach this to the worker or use
unknown Plan metadata as commands. The separate versioned record below is local
qualification evidence, never a wire extension or a spend/installation receipt.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import threading
import time
import zipfile
from pathlib import Path
from types import MappingProxyType

from shared import artifact_store as store
from shared import optional_setup_wire_v3 as wire
from shared import optional_setup_protocol as proto
from shared import optional_setup_exchange_v3 as exchange
from tts import model_assets as assets
from tts import qwen3_package_manifest as packages
from tts import qwen3_packages as sealing
from tts import qwen3_setup as setup
from tts import qwen3_runtime as rt

POLICY = MappingProxyType({
    'schema': 'act-disposable-spacy-consumer', 'version': 1,
    'production_eligible': False, 'action': 'install-missing-only',
    'recovery': 'retain-target-and-uncertainty; no-automatic-retry-or-parent-rebuild',
    'timeout_seconds': 180, 'output_bytes': 64 * 1024,
})
_QUALIFICATION_ROOT = Path(__file__).resolve().parents[2] / 'files/dev-work/p05b-stage4c'


def production_consumer(confirmation, original):
    raise store.ArtifactError('BLOCKED: v1 acquisition terms lack main consumer-target/recovery authority')


def _artifact():
    return packages.Artifact('en-core-web-sm', assets.SPACY_ENGLISH_VERSION, assets.SPACY_WHEEL_NAME,
        assets.SPACY_WHEEL_SIZE, assets.SPACY_WHEEL_SHA256, ('py3-none-any',), assets.SPACY_WHEEL_URL)


def verify_source(path, *, cancelled=lambda: False):
    metadata = packages.verify_wheel_metadata(_artifact(), packages.LocalArtifact(
        Path(path), assets.SPACY_WHEEL_NAME, assets.SPACY_WHEEL_URL),
        check_cancel=lambda: setup._check_cancel(cancelled))
    # Dependency closure is deliberately NOT resolved: this exact compatible
    # pre-existing spaCy is the only runtime dependency allowed by this wheel.
    requirements = [r.replace(' ', '') for r in metadata['requires_dist']]
    store.require(not requirements or (len(requirements) == 1 and requirements[0] in (
        'spacy<3.9.0,>=3.8.0', 'spacy>=3.8.0,<3.9.0')), 'unreviewed model dependency metadata')
    # The retained approved installation has NO Requires-Dist header: its
    # compatibility authority is model meta.json, not a pip dependency resolver.
    with zipfile.ZipFile(path) as archive:
        name = 'en_core_web_sm/meta.json'
        store.require(name in archive.namelist() and archive.getinfo(name).file_size <= 64 * 1024,
                      'missing/oversized English model metadata')
        model = proto.strict_json(archive.read(name), max_bytes=64 * 1024)
    store.require(model.get('lang') == 'en' and model.get('name') == 'core_web_sm'
                  and model.get('version') == '3.8.0' and model.get('spacy_version') == '>=3.8.0,<3.9.0',
                  'English model version/compatibility metadata mismatch')
    return metadata


PROBE = '''import json, sys, struct
from pathlib import Path
from importlib import metadata
def offline(event, args):
    if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'):
        raise PermissionError('offline health probe refused ' + event)
sys.addaudithook(offline)
target = Path(sys.argv[1])
assert sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8
assert Path(sys.prefix) == target and sys.prefix != sys.base_prefix
assert Path(sys.executable) == target / 'Scripts/python.exe'
def distribution(name):
    try:
        value = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    assert Path(value.locate_file('')).resolve() == (target / 'Lib/site-packages').resolve()
    return value.version
result = {'prefix': sys.prefix, 'spacy': distribution('spacy'), 'model': distribution('en-core-web-sm'), 'health': False}
if sys.argv[2] == 'health' and result['model'] == '3.8.0':
    try:
        import spacy, en_core_web_sm
        assert Path(spacy.__file__).resolve().is_relative_to((target / 'Lib/site-packages').resolve())
        assert Path(en_core_web_sm.__file__).resolve().is_relative_to((target / 'Lib/site-packages').resolve())
        nlp = en_core_web_sm.load()
        doc = nlp('This is a bounded English model health check.')
        result['health'] = bool(len(doc)) and bool(nlp.pipe_names) and nlp.meta.get('version') == '3.8.0'
    except Exception as exc:
        result['health_error'] = type(exc).__name__
print('@@SPACY ' + json.dumps(result, sort_keys=True))
'''


class DisposableConsumer:
    """One explicitly owned disposable target, exact original v3 terms and one attempt.

    Trusted Python test/qualification code supplies paths, never incoming JSON.
    Target is created beforehand with CPython 3.12, without system site-packages.
    Failed/interrupted pip retains its durable pending record and target for review.
    There is no uninstall, repair, replay, automatic rollback or parent reconstruction.
    """
    def __init__(self, root, target, confirmation, original, *, now=time.time):
        self.root, self.target = Path(root).absolute(), Path(target).absolute()
        store.require(self.root.is_relative_to(_QUALIFICATION_ROOT)
                      and self.root != _QUALIFICATION_ROOT
                      and self.root.resolve().is_relative_to(_QUALIFICATION_ROOT.resolve())
                      and self.target == self.root / 'disposable-env', 'unowned disposable consumer target')
        store.require(len(str(self.root)) + 46 < 248, 'disposable consumer process cwd exceeds Windows bound')
        store.require(type(confirmation) is wire.Confirmation and type(original) is wire.Disclosure,
                      'exact independently retained confirmation required')
        self.confirmation, self.original, self.now = confirmation, original, now
        self._confirmation()
        self.identity = self._identity()
        self.record = store.canonical({**POLICY, 'target': str(self.target), 'identity': self.identity,
            'wheel_sha256': assets.SPACY_WHEEL_SHA256,
            'original_sha256': hashlib.sha256(original.raw).hexdigest(),
            'confirmation_sha256': hashlib.sha256(confirmation.raw).hexdigest(),
            'terms': json.loads(confirmation.consent.terms)})
        # Recovery belongs to the target, not a request/consent identifier. A
        # newly minted confirmation must not bypass an uncertain earlier pip.
        self.pending = self.root / 'spacy-consumer-journal' / 'main-env.pending.json'

    def _confirmation(self):
        c = self.confirmation
        checked = wire.decode_confirmation_request(c.raw, raw_disclosure=c.disclosure.raw,
            raw_consent=c.raw_consent, expected_disclosure=self.original, session=c.consent.session,
            request_id=c.consent.request_id, now=self.now)
        store.require(checked == c, 'confirmation object changed')
        rows = [a for a in json.loads(c.consent.terms)['artifacts'] if a['name'] == 'spacy-english']
        store.require(len(rows) == 1, 'exact English wheel absent from original terms')
        row = rows[0]
        store.require(row['kind'] == 'model' and row['components'] == [proto.KOKORO]
            and (row['filename'], row['size'], row['sha256']) ==
                (assets.SPACY_WHEEL_NAME, assets.SPACY_WHEEL_SIZE, assets.SPACY_WHEEL_SHA256)
            and row['source'] == {'kind': 'pinned-https', 'url': assets.SPACY_WHEEL_URL,
                                  'revision': assets.SPACY_WHEEL_SHA256}
            and row['derivative'] is None, 'unapproved English wheel terms')

    def _identity(self):
        with store.boundary(_QUALIFICATION_ROOT, self.target / 'Scripts/python.exe'):
            cfg = self.target / 'pyvenv.cfg'
            with store.checked_open(_QUALIFICATION_ROOT, cfg, 'rb') as handle:
                raw = handle.read(4097)
            store.require(len(raw) <= 4096 and re.search(
                rb'(?m)^include-system-site-packages = false\r?$', raw)
                and re.search(rb'(?m)^version = 3\.12\.[0-9]+\r?$', raw), 'wrong consumer interpreter/venv')
            python = self.target / 'Scripts/python.exe'
            with store.checked_open(_QUALIFICATION_ROOT, python, 'rb') as handle:
                store.require(os.fstat(handle.fileno()).st_size <= 16 * 1024 * 1024,
                              'consumer interpreter exceeds identity bound')
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            info = self.target.stat()
            return {'directory': [info.st_dev, info.st_ino], 'cfg_sha256': hashlib.sha256(raw).hexdigest(),
                    'python_sha256': digest}

    def _run(self, argv, *, runner, cwd, cancelled):
        deadline, output, count = time.monotonic() + POLICY['timeout_seconds'], [], 0
        def stop():
            return cancelled() or time.monotonic() >= deadline
        def keep(line):
            nonlocal count
            count += len(line.encode('utf-8')) + 1
            store.require(count <= POLICY['output_bytes'], 'consumer output exceeded bound')
            output.append(line)
        setup._check_cancel(stop)
        code = runner(argv, env=setup.installer_environment(), cwd=cwd, on_line=keep, cancel_check=stop)
        setup._check_cancel(stop)
        return code, output

    def _probe(self, runner, cancelled, phase):
        code, output = self._run([str(self.target / 'Scripts/python.exe'), '-I', '-B', '-c', PROBE,
                                 str(self.target), phase], runner=runner, cwd=self.root, cancelled=cancelled)
        records = [line[8:] for line in output if line.startswith('@@SPACY ')]
        store.require(code == 0 and len(records) == 1, 'consumer target probe unverified')
        result = json.loads(records[0])
        store.require(result['prefix'] == str(self.target)
                      and type(result['health']) is bool, 'wrong consumer target probe')
        version = result['spacy']
        store.require(type(version) is str and re.fullmatch(r'3\.8\.[0-9]+', version),
                      'compatible pre-existing spaCy >=3.8.0,<3.9.0 required; no upgrade')
        return result

    def qualify(self, source, *, runner=None, cancelled=lambda: False):
        store.require(rt.repo_root() == self.root, 'disposable operation lock belongs to another installation')
        runner = setup.run_command if runner is None else runner
        with setup.InstallLock(), contextlib.ExitStack() as held:
            held.enter_context(store.boundary(_QUALIFICATION_ROOT, self.target / 'Scripts/python.exe'))
            # Reuse accepted native read handles within the fixed qualification
            # root. The disposable issuer does not claim production ancestry.
            for path in (self.target / 'Scripts/python.exe', self.target / 'pyvenv.cfg'):
                parent = held.enter_context(store.boundary(_QUALIFICATION_ROOT, path))
                folder = exchange._Folder(_QUALIFICATION_ROOT, path.parent, exchange._handle_id(parent))
                held.enter_context(exchange._open_file(folder, path))
            self._confirmation()
            store.require(self._identity() == self.identity, 'consumer target changed')
            store.require(not self.pending.exists(), 'uncertain/previous attempt; no automatic retry')
            verify_source(source, cancelled=cancelled)
            before = self._probe(runner, cancelled, 'before')
            store.require(before['model'] is None, 'existing model preserved; no reinstall or repair')
            wheels = self.root / ('spacy-sealed-' + proto.new_token())
            store.mkdirs(self.root, wheels)
            held.enter_context(store.boundary(self.root, wheels / 'sentinel'))
            wheel, lock = wheels / assets.SPACY_WHEEL_NAME, wheels / 'requirements.txt'
            stream = held.enter_context(sealing._private_file(self.root, wheel))
            with Path(source).open('rb') as source_stream:
                remaining = assets.SPACY_WHEEL_SIZE
                while remaining:
                    setup._check_cancel(cancelled)
                    block = source_stream.read(min(store.BLOCK, remaining))
                    store.require(bool(block), 'source changed while sealing')
                    stream.write(block)
                    remaining -= len(block)
            stream.flush()
            os.fsync(stream.fileno())
            verify_source(wheel, cancelled=cancelled)  # private file pinned through Job completion
            lock_stream = held.enter_context(sealing._private_file(self.root, lock))
            lock_stream.write(('en-core-web-sm==3.8.0 --hash=sha256:' + assets.SPACY_WHEEL_SHA256 + '\n').encode())
            lock_stream.flush()
            os.fsync(lock_stream.fileno())
            argv = sealing._pip_command(self.target / 'Scripts/python.exe', wheels, lock,
                                        [(wheel, assets.SPACY_WHEEL_SHA256)])
            self._confirmation()
            store.require(self._identity() == self.identity, 'consumer target changed before pip')
            setup._check_cancel(cancelled)
            store.mkdirs(self.root, self.pending.parent)
            store.write_once(self.root, self.pending, self.record)  # uncertainty precedes process launch
            protection = {'thread': threading.get_ident()}
            token = object()
            sealing._LIVE[token] = protection
            try:
                code, output = self._run(argv, runner=runner, cwd=wheels, cancelled=cancelled)
            finally:
                del sealing._LIVE[token]
                # consumer_finished marks every current-thread held view if Job
                # emptiness cannot be proved, including this single-wheel view.
                if protection.get('uncertain_consumer'):
                    sealing._QUARANTINED.append(held.pop_all())
            after = self._probe(runner, cancelled, 'health')
            store.require(after['spacy'] == before['spacy'], 'spaCy version changed during consumption')
            result = {'schema': 'act-disposable-spacy-result', 'version': 1, 'pip_exit': code,
                      'distribution_installed': after['model'] == assets.SPACY_ENGLISH_VERSION,
                      'import_health_ready': code == 0 and after['model'] == assets.SPACY_ENGLISH_VERSION
                                             and after['health'],
                      'transfer_receipt': False, 'production_ready': False,
                      'recovery': POLICY['recovery'], 'target_identity': self.identity,
                      'contract_sha256': hashlib.sha256(self.record).hexdigest()}
            store.write_once(self.root, self.pending.with_suffix('.result.json'), store.canonical(result))
            return result
