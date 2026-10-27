"""Production-disconnected read-only composition for owned Windows fixtures.

No production execution context exists. The only context issuer below is named
for_test and requires a new disposable installation plus trusted fixture CODE.
That code is an independently chosen test adapter, never request JSON or code
from an exchange. The interpreter, module, cwd, argv and environment are fixed.
Candidate admission is not display retention, consent or installed readiness.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
import sys
import time
import weakref
from dataclasses import dataclass
from pathlib import Path

from shared import artifact_store as store
from shared import optional_setup_exchange_v3 as exchange
from shared import optional_setup_supervisor_v3 as supervisor
from shared import optional_setup_wire_v3 as wire
from tts import qwen3_process

# Explicit reviewed dependency closure. No directory copy or request-selected file.
SOURCES = (
    'shared/__init__.py', 'shared/artifact_store.py', 'shared/artifact_transfer.py',
    'shared/optional_setup_protocol.py', 'shared/optional_setup_v3.py',
    'shared/optional_setup_wire_v3.py', 'shared/optional_setup_exchange_v3.py',
    'shared/optional_setup_resource_budget.py', 'shared/venv_layout.py',
    'shared/subprocess_utils.py', 'tts/__init__.py', 'tts/optional_setup_authority.py',
    'tts/optional_setup_planning_worker_v3.py', 'tts/optional_setup.py',
    'tts/optional_setup_health.py', 'tts/model_assets.py', 'tts/voice_registry.py',
    'tts/qwen3_runtime.py', 'tts/qwen3_setup.py', 'tts/qwen3_process.py',
    'tts/qwen3_package_manifest.py', 'tts/qwen3_engine_authority.py', 'tts/qwen3_packages.py',
    'qwen3-artifacts.json', 'qwen3-requirements.txt',
)
_SOURCE_ROOT = Path(__file__).resolve().parents[1]
_REPO = _SOURCE_ROOT.parent
_ISSUED = weakref.WeakValueDictionary()
_BOOTSTRAP = ("import os,sys;sys.path.insert(0,os.getcwd());"
    "from tts import optional_setup_planning_worker_v3 as w;"
    "import _planning_fixture as f;sys.exit(w.main(context=f.context()))")


def _owned(root):
    root = exchange._root(root)
    base = _REPO / 'files/dev-work/p05b-stage4c'
    exchange._require(root.is_relative_to(base) and root != base
        and root.relative_to(base).parts[0].startswith('stage4d2d-'), 'owned Stage-4D2D fixture required')
    # Includes ancestors outside the checkout; resolve never grants link ancestry.
    for path in (root, *root.parents):
        if os.path.lexists(path):
            exchange._require(not path.lstat().st_file_attributes & 0x400, 'fixture reparse ancestry')
    exchange._require(root.resolve() == root, 'fixture path redirection')
    return root


@contextlib.contextmanager
def _pin_file(path, cap=512 * 1024):
    """Native READ-only sharing and pinned ancestry, retained through child exit."""
    path = exchange._root(path)
    base = _REPO if path.is_relative_to(_REPO) else Path(sys.base_prefix)
    exchange._require(path.is_relative_to(base), 'source outside independently known code/interpreter roots')
    for ancestor in path.parents:
        exchange._require(not ancestor.lstat().st_file_attributes & 0x400, 'trusted source reparse ancestry')
    with store.boundary(base, path) as parent:
        folder = exchange._Folder(base, path.parent, exchange._handle_id(parent))
        with exchange._open_file(folder, path) as stream:
            before = exchange._file_identity(stream, path)
            exchange._require(0 <= before[2] <= cap, 'oversized trusted source')
            raw = stream.read(cap + 1)
            exchange._require(len(raw) == before[2] and exchange._file_identity(stream, path) == before,
                              'trusted source changed')
            yield raw
            exchange._require(exchange._file_identity(stream, path) == before, 'trusted source changed during launch')


@dataclass(frozen=True)
class ApprovedDisposableContext:
    """Explicit trusted test injection; cannot name a production installation.

    adapter_source is reviewed executable TEST CODE, not user data. It installs
    synthetic observation/tiny-manifest adapters before the actual Planner runs.
    The source is retained independently and pinned along with copied ACT code.
    This is no attestation of hostile code or production deployment ancestry.
    """
    root: Path
    pins: tuple
    interpreter: Path

    @classmethod
    def for_test(cls, root, *, adapter_source):
        root = _owned(root)
        exchange._require(type(adapter_source) is bytes and 0 < len(adapter_source) <= 64 * 1024,
                          'trusted bounded fixture adapter source required')
        interpreter = _REPO / '.venv/Scripts/python.exe'
        exchange._require(Path(sys.executable) == interpreter and sys.implementation.name == 'cpython'
            and sys.version_info[:2] == (3, 12), 'trusted main CPython identity required')
        root.mkdir(parents=True, exist_ok=False)
        scripts = root / 'app/scripts'
        scripts.mkdir(parents=True)
        pins = []
        for rel in SOURCES:
            source, target = _SOURCE_ROOT / rel, scripts / rel
            with _pin_file(source) as raw:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(raw)
                pins.append((target, hashlib.sha256(raw).digest()))
        adapter = scripts / '_planning_fixture.py'
        with adapter.open('xb') as stream:
            stream.write(adapter_source)
        pins.append((adapter, hashlib.sha256(adapter_source).digest()))
        for path in (interpreter, Path(sys._base_executable), _REPO / '.venv/pyvenv.cfg'):
            with _pin_file(path, 1024 * 1024) as raw:
                pins.append((path, hashlib.sha256(raw).digest()))
        context = cls(root, tuple(pins), interpreter)
        _ISSUED[id(context)] = context
        return context


class PlanningRun(supervisor.FakePlanningRun):
    """Reuses the qualified coordinator/readers/job arbitration without v2 authority.

    accepted means ONLY complete read-only candidate admission after containment.
    candidate() exposes untrusted bytes only after that immutable decision. There
    is deliberately no confirm/install/repair/spend/display-retention method.
    """
    @classmethod
    def for_test(cls, *, context, planning, session, on_event=None, timeout_s=10,
                 cleanup_s=2, join_s=1, now=time.time):
        exchange._require(type(context) is ApprovedDisposableContext, 'approved disposable context required')
        exchange._require(_ISSUED.get(id(context)) is context, 'context was not issued by the fixture controller')
        _owned(context.root)
        exchange._require(type(planning) is wire.PlanningRequest, 'independently retained request required')
        wire.decode_planning_request(planning.raw, session=session,
            request_id=planning.to_json().get('request_id'), now=now)
        budgets = (supervisor._budget(timeout_s, 60), supervisor._budget(cleanup_s, 10),
                   supervisor._budget(join_s, 5))
        self = object.__new__(cls)
        self.context, self.root, self.repo = context, context.root, context.root / 'app'
        self.planning, self.session = planning, session
        self._candidate = None
        self._launch_pins = contextlib.ExitStack()
        self._configure(now=now, on_event=on_event, timeout_s=budgets[0], cleanup_s=budgets[1], join_s=budgets[2])
        exchange.publish_planning_request(self.repo, planning.raw, session=session,
            request_id=planning.to_json()['request_id'], now=now)
        self.result_path = self.repo / exchange.EXCHANGE_ROOT / planning.to_json()['request_id'] / 'result.json'
        return self

    def _spawn_fake(self):
        # Fixed bootstrap is needed under -I -S: cwd/PYTHONPATH are not import roots.
        # No caller/worker-selected module, code string, interpreter or argv.
        _owned(self.root)
        exchange._require(_ISSUED.get(id(self.context)) is self.context, 'unissued execution context')
        exchange._require(self.context.interpreter == _REPO / '.venv/Scripts/python.exe'
            == Path(sys.executable), 'interpreter identity changed')
        scripts = self.repo / 'scripts'
        expected = {scripts / rel for rel in SOURCES} | {scripts / '_planning_fixture.py',
            self.context.interpreter, Path(sys._base_executable), _REPO / '.venv/pyvenv.cfg'}
        exchange._require({path for path, _ in self.context.pins} == expected
            and len(self.context.pins) == len(expected), 'incomplete approved source pins')
        try:
            for path, digest in self.context.pins:
                raw = self._launch_pins.enter_context(_pin_file(path, 1024 * 1024))
                exchange._require(hashlib.sha256(raw).digest() == digest, 'approved code/interpreter changed')
            # Additional importable files would escape the reviewed source closure.
            files = {p for p in expected if p.is_relative_to(scripts)}
            directories = {scripts} | {p.parent for p in files}
            for directory in directories:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        path = directory / entry.name
                        exchange._require(path in files or path in directories, 'unexpected fixture code/data')
                        exchange._require(not entry.stat(follow_symlinks=False).st_file_attributes & 0x400,
                                          'fixture code reparse point')
            request = exchange._read_published_planning_request(self.repo, session=self.session,
                request_id=self.planning.to_json()['request_id'], now=self._now)
            exchange._require(request.raw == self.planning.raw, 'launch request changed')
            env = {'SystemRoot': os.environ['SystemRoot'], 'TEMP': str(self.root), 'TMP': str(self.root),
                'TMPDIR': str(self.root), 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
            return qwen3_process.spawn([str(self.context.interpreter), '-I', '-B', '-S', '-c', _BOOTSTRAP,
                self.planning.to_json()['request_id'], self.session], require_job=True,
                cwd=str(scripts), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        except BaseException:
            self._launch_pins.close()
            raise

    def _read_exchange(self):
        if self._stderr.count:
            self._error('unexpected-stderr')
        if self._events != 3 or self._phase != 2:
            self._error('planning-events-incomplete')
        self._candidate = exchange._read_untrusted_planning_candidate(self.repo, planning=self.planning,
            session=self.session, now=self._now)
        return self._candidate.raw_result

    def _resolve(self):
        try:
            self._launch_pins.close()
        except Exception:
            self._error('launch-identity-changed')
        super()._resolve()

    def candidate(self):
        with self._lock:
            return self._candidate if self._outcome is not None and self._outcome.accepted else None
