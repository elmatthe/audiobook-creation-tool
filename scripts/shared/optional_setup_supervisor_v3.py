"""Production-disconnected, Windows-only read-only planning supervision foundation.

The ONLY launch entry is FakePlanningRun.for_test: a fixed inert program in a
new Stage-4D2B disposable tree. No arbitrary argv, executable, environment,
runner, production worker, cancellation file, consent or spending interface.
Executable/module ancestry and production worker composition remain unqualified.

PROPOSED experimental event contract: newline-delimited UTF-8 JSON with the
closed schema below, phases starting -> planning -> published, progress only.
Events are advisory; only pinned exchange readback plus terminal arbitration can
accept a planning result. This does not activate a production v3 event protocol.
"""
from __future__ import annotations

import math
import os
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from shared import optional_setup_exchange_v3 as exchange
from shared import optional_setup_protocol as proto
from shared import optional_setup_wire_v3 as wire
from tts import qwen3_process

MAX_LINE = 2048
MAX_OUTPUT = 128 * 1024
MAX_EVENTS = 64
MAX_RETAINED = 4096
EVENT_PROTOCOL = 'act-proposed-read-only-planning-event'
_PHASES = ('starting', 'planning', 'published')
_SCENARIOS = frozenset(('ok', 'quiet', 'no-result', 'nonzero', 'crash', 'hang',
    'published-hang', 'child-hang', 'child-left', 'child-pipe', 'closed-stdout',
    'invalid-json', 'utf8', 'overlong', 'no-newline', 'flood', 'event-flood',
    'duplicate', 'backward', 'wrong-session', 'wrong-request', 'v2', 'phase',
    'terminal-event', 'wrong-result', 'verified', 'changed-plan', 'partial-result',
    'stdout-hang', 'truncated-utf8', 'stderr-tail'))


@dataclass(frozen=True)
class Outcome:
    state: str
    accepted: bool
    errors: tuple[str, ...]
    exit_code: int | None
    process_running: bool
    job_active: int | None
    job_total: int | None
    job_before_cleanup: int | None
    termination_failed: bool
    readers_joined: bool
    output_complete: bool
    stdout_bytes: int
    stderr_bytes: int
    retained_stdout: bytes
    retained_stderr: bytes
    events: int
    raw_result: bytes | None


class _Output:
    """Fixed-size storage; counters saturate after the accounting cap is crossed."""

    def __init__(self):
        self.count = 0
        self.retained = bytearray()
        self.eof = False


def _owned(path):
    root = Path(__file__).resolve().parents[2] / 'files/dev-work/p05b-stage4c'
    path = exchange._root(path)
    if not path.is_relative_to(root) or not path.relative_to(root).parts[0].startswith('stage4d2b-'):
        raise ValueError('only a new Stage-4D2B disposable tree is allowed')
    for part in (path, *path.parents):
        if part.exists() and part.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('linked fake-worker paths are refused')
    return path


def _budget(value, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError('finite positive supervision budget required')
    return float(value)


class FakePlanningRun:
    """One immutable terminal decision, shared by concurrent wait/stop observers.

    for_test prepares a NEW tree but does not launch. start launches once and a
    dedicated coordinator owns all cleanup/arbitration. cancel is nonblocking,
    including from an event callback. Callbacks must return promptly; a blocked
    callback cannot produce accepted success and never extends the join budget.
    """

    def __init__(self):
        raise TypeError('use the restricted for_test factory')

    @classmethod
    def for_test(cls, root, *, planning, disclosure, session, scenario='ok',
                 on_event=None, timeout_s=5.0, cleanup_s=2.0, join_s=1.0, now=time.time):
        if sys.platform != 'win32':
            raise RuntimeError('native Windows Job Object qualification required')
        if type(scenario) is not str or scenario not in _SCENARIOS:
            raise ValueError('unknown fixed fake program scenario')
        root = _owned(root)
        # Validate independently retained P/I/session/Plan before creating files.
        if type(planning) is not wire.PlanningRequest or type(disclosure) is not wire.Disclosure:
            raise ValueError('independently retained planning and disclosure required')
        wire.decode_planning_request(planning.raw, session=session,
            request_id=planning.to_json().get('request_id'), now=now)
        raw_result = wire.encode_planning_result(disclosure=disclosure,
            issued_utc=proto.utc_text(now()), now=now)
        exchange._planning_binding(planning, disclosure, raw_result, session=session, now=now)
        timeout_s, cleanup_s, join_s = (_budget(timeout_s, 60), _budget(cleanup_s, 10), _budget(join_s, 5))
        root.mkdir(parents=True, exist_ok=False)
        self = object.__new__(cls)
        self.root, self.repo = root, root / 'fake-app'
        self.repo.mkdir()
        self.planning, self.disclosure, self.session = planning, disclosure, session
        self._configure(now=now, on_event=on_event, timeout_s=timeout_s, cleanup_s=cleanup_s, join_s=join_s)
        self._scenario = scenario
        exchange.publish_planning_request(self.repo, planning.raw, session=session,
            request_id=planning.to_json()['request_id'], now=now)
        self.result_path = self.repo / exchange.EXCHANGE_ROOT / planning.to_json()['request_id'] / 'result.json'
        (root / 'shown.bin').write_bytes(disclosure.raw)
        (root / 'answer.bin').write_bytes(raw_result)
        (root / 'fake_worker.py').write_text(_FAKE_PROGRAM, encoding='utf-8')
        return self

    def _configure(self, *, now, on_event, timeout_s, cleanup_s, join_s):
        """Shared bounded coordination state; no launch authority is added."""
        self._now, self._callback = now, on_event
        self._timeout, self._cleanup, self._join = timeout_s, cleanup_s, join_s
        self._lock = threading.RLock()
        self._done = threading.Event()
        self._wake = threading.Event()
        self._errors = set()
        self._cancelled = self._timed_out = self._started = False
        self._outcome = None
        self.process = None
        self._readers = []
        self._stdout, self._stderr = _Output(), _Output()
        self._seq, self._phase, self._events = -1, -1, 0
        self._active = self._total = self._before = None
        self._termination_failed = False
        self._joined = False
        self._raw_result = None

    def _read_exchange(self):
        # FakePlanningRun keeps its independently retained original contract.
        return exchange.read_planning_exchange(self.repo, planning=self.planning,
            expected_disclosure=self.disclosure, session=self.session, now=self._now).raw_result

    def _error(self, code):
        # Only fixed local codes: no worker strings, paths or unbounded log.
        with self._lock:
            self._errors.add(code)
        self._wake.set()

    def _spawn_fake(self):
        script = self.root / 'fake_worker.py'
        _owned(script)
        if script.stat().st_nlink != 1 or script.read_text(encoding='utf-8') != _FAKE_PROGRAM:
            raise ValueError('fixed fake program changed')
        env = {'SystemRoot': os.environ['SystemRoot'], 'TEMP': str(self.root), 'TMP': str(self.root),
               'TMPDIR': str(self.root), 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
        return qwen3_process.spawn([sys.executable, '-I', '-B', '-S', str(script), self._scenario],
            require_job=True, cwd=str(self.root), env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)

    def start(self):
        with self._lock:
            if self._started:
                raise RuntimeError('one launch only')
            self._started = True
            if self._cancelled:
                self._resolve()
                return
            try:
                self.process = self._spawn_fake()
            except Exception:
                self._error('launch-failed')
                self._resolve()
                return
            for stream, output, events in ((self.process.stdout, self._stdout, True),
                                           (self.process.stderr, self._stderr, False)):
                thread = threading.Thread(target=self._read, args=(stream, output, events),
                    name='v3-fake-output', daemon=True)
                self._readers.append(thread)
                thread.start()
            self._coordinator = threading.Thread(target=self._supervise, name='v3-fake-supervisor', daemon=True)
            self._coordinator.start()

    def cancel(self):
        with self._lock:
            if self._outcome is None:
                self._cancelled = True
                self._wake.set()

    def stop(self):
        self.cancel()
        return self.wait()

    def result(self):
        with self._lock:
            return self._outcome

    def wait(self):
        if not self._started:
            raise RuntimeError('start before waiting')
        if threading.current_thread() in self._readers:
            raise RuntimeError('callback may cancel but cannot join itself')
        # Independent finite observer bound, including exceptional coordinator failure.
        if not self._done.wait(self._timeout + self._cleanup + self._join + 2):
            raise RuntimeError('supervisor did not settle within its budget')
        return self.result()

    def _event(self, raw):
        d = wire._load(raw, MAX_LINE)
        keys = {'protocol', 'version', 'request_id', 'session', 'seq', 'kind', 'phase'}
        if set(d) != keys or d['protocol'] != EVENT_PROTOCOL or type(d['version']) is not int or d['version'] != 3 \
                or d['request_id'] != self.planning.to_json()['request_id'] or d['session'] != self.session \
                or type(d['seq']) is not int or not self._seq < d['seq'] <= 2**31 - 1 \
                or d['kind'] != 'progress' or d['phase'] not in _PHASES:
            raise ValueError('invalid proposed event')
        phase = _PHASES.index(d['phase'])
        if phase not in (self._phase, self._phase + 1):
            raise ValueError('illegal phase progression')
        if self._events >= MAX_EVENTS:
            self._error('event-limit')
            return
        self._seq, self._phase = d['seq'], phase
        self._events += 1
        callback = self._callback
        if callback is not None:
            try:
                callback(dict(d))
            except BaseException:
                self._callback = None
                self._error('callback-failed')

    def _read(self, stream, output, events):
        pending = bytearray()
        discard = False
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    output.eof = True
                    if pending or discard:
                        self._error('unterminated-output')
                    break
                with self._lock:
                    output.count = min(MAX_OUTPUT + 1, output.count + len(chunk))
                    total = self._stdout.count + self._stderr.count
                    output.retained.extend(chunk[:max(0, MAX_RETAINED - len(output.retained))])
                if total > MAX_OUTPUT:
                    self._error('output-limit')
                    discard = True
                # After fatal output, continue fixed-size discard until stop/EOF.
                if discard:
                    continue
                for byte in chunk:
                    if byte == 10:
                        try:
                            if events:
                                self._event(bytes(pending))
                            else:
                                pending.decode('utf-8', errors='strict')
                        except (ValueError, proto.ProtocolError, UnicodeError, TypeError, KeyError):
                            self._error('invalid-output')
                            discard = True
                            break
                        pending.clear()
                    else:
                        pending.append(byte)
                        if len(pending) > MAX_LINE:
                            self._error('line-limit')
                            discard = True
                            break
        except BaseException:
            self._error('reader-failed')
        finally:
            stream.close()

    def _account(self):
        job = getattr(self.process, 'act_job', None)
        if job is None:
            self._error('missing-job')
            self._active = None
            return
        try:
            active, total = job.accounting()
            if type(active) is not int or type(total) is not int or not 0 <= active <= total or total < 1:
                raise ValueError('unknown accounting')
            self._active, self._total = active, total
        except Exception:
            self._active = None
            self._error('job-accounting-unknown')

    def _terminate_job(self):
        job = getattr(self.process, 'act_job', None)
        try:
            if job is None:
                raise RuntimeError('missing job')
            # ProcessJob.terminate discards the native BOOL; check it here so a
            # refused termination is distinct even if subsequent accounting works.
            if not job._k.TerminateJobObject(job.handle, 1):
                raise OSError('job termination refused')
        except Exception:
            self._termination_failed = True
            self._error('job-termination-failed')

    def _supervise(self):
        deadline = time.monotonic() + self._timeout
        try:
            while self.process.poll() is None:
                with self._lock:
                    if self._cancelled or self._errors:
                        break
                if time.monotonic() >= deadline:
                    self._timed_out = True
                    self._error('timed-out')
                    break
                self._wake.wait(0.01)
                self._wake.clear()
            self._account()
            # Windows can signal the process handle just before job accounting
            # retires that same member. Allow a fixed 100 ms natural-exit grace;
            # a still-live descendant then remains a fatal contradiction.
            settle = time.monotonic() + .1
            while self.process.poll() is not None and self._active and time.monotonic() < settle:
                time.sleep(.01)
                self._account()
            self._before = self._active
            # A worker exiting with a live descendant is a contradiction, even
            # if cleanup subsequently empties the job.
            if self.process.poll() is not None and self._active:
                self._error('live-descendant')
            if self._active != 0 or self.process.poll() is None:
                self._terminate_job()
            end = time.monotonic() + self._cleanup
            while True:
                self._account()
                running = self.process.poll() is None
                if self._active == 0 and not running or time.monotonic() >= end:
                    break
                time.sleep(0.01)
            if self._active != 0:
                self._error('job-not-proven-empty')
            if self.process.poll() is None:
                self._error('process-still-running')
            else:
                self.process.wait(timeout=0)
            end = time.monotonic() + self._join
            for reader in self._readers:
                reader.join(max(0, end - time.monotonic()))
            self._joined = all(not reader.is_alive() for reader in self._readers)
            if not self._joined:
                self._error('reader-still-running')
            if not (self._stdout.eof and self._stderr.eof):
                self._error('output-incomplete')
            if self._events and self._phase != 2:
                self._error('event-stream-incomplete')
            if self.process.returncode != 0:
                self._error('exit-result-disagreement')
            try:
                self._raw_result = self._read_exchange()
            except Exception:
                self._error('planning-exchange-refused')
        except BaseException:
            self._error('supervisor-failed')
        finally:
            # Closing is cleanup, never a substitute for the accounting above.
            try:
                if self.process is not None:
                    qwen3_process.release(self.process)
            except Exception:
                self._error('job-release-failed')
            finally:
                self._resolve()

    def _resolve(self):
        with self._lock:
            if self._outcome is not None:
                return
            if self._cancelled:
                self._errors.add('cancelled')
            accepted = not self._errors and self.process is not None and self.process.returncode == 0 \
                and self._active == 0 and self._joined and self._stdout.eof and self._stderr.eof \
                and self._raw_result is not None and not self._timed_out and not self._cancelled
            state = 'accepted' if accepted else 'cancelled' if self._cancelled else 'failed'
            self._outcome = Outcome(state, accepted, tuple(sorted(self._errors)),
                None if self.process is None else self.process.returncode,
                self.process is not None and self.process.poll() is None,
                self._active, self._total, self._before, self._termination_failed, self._joined,
                self._stdout.eof and self._stderr.eof, self._stdout.count, self._stderr.count,
                bytes(self._stdout.retained), bytes(self._stderr.retained), self._events, self._raw_result)
            self._done.set()


# Fixed, reviewed, stdlib-only disposable program. No code/argv/path input from
# JSON; the sole command argument is the closed scenario set selected by tests.
# -I -B -S, fixed cwd, fixed relative files, no imports from the ACT application.
_FAKE_PROGRAM = r'''import json, os, subprocess, sys, time
from pathlib import Path
root = Path(__file__).resolve().parent
assert Path.cwd() == root and len(sys.argv) == 2
scenario = sys.argv[1]
if scenario == '--grandchild':
    (root / 'grand.pid').write_text(str(os.getpid()))
    time.sleep(30)
    sys.exit(0)
(root / 'worker.pid').write_text(str(os.getpid()))
shown = json.loads((root / 'shown.bin').read_bytes())
folder = root / 'fake-app/files/runtime-data/optional-setup' / shown['planning_request_id']
def event(seq, phase, **changes):
    d = dict(protocol='act-proposed-read-only-planning-event', version=3,
        request_id=shown['planning_request_id'], session=shown['session'],
        seq=seq, kind='progress', phase=phase)
    d.update(changes)
    print(json.dumps(d), flush=True)
def child():
    subprocess.Popen([sys.executable, '-I', '-B', '-S', str(root / 'fake_worker.py'), '--grandchild'],
        cwd=str(root), env=dict(os.environ), stdin=subprocess.DEVNULL)
    deadline = time.monotonic() + 3
    while not (root / 'grand.pid').exists():
        assert time.monotonic() < deadline
        time.sleep(.01)
if scenario in ('child-hang', 'child-left', 'child-pipe'):
    child()
if scenario in ('hang', 'child-hang'):
    time.sleep(30)
if scenario == 'stdout-hang':
    os.close(1)
    time.sleep(30)
if scenario == 'no-result':
    sys.exit(0)
if scenario != 'quiet':
    event(0, 'starting')
    if scenario == 'invalid-json': print('{', flush=True)
    elif scenario == 'utf8': os.write(1, b'\xf0\x9f\n')
    elif scenario == 'overlong': os.write(1, b'x' * 4096 + b'\n')
    elif scenario == 'no-newline': os.write(1, b'{')
    elif scenario == 'flood':
        for _ in range(4096): os.write(2, b'x' * 1023 + b'\n')
    elif scenario == 'event-flood':
        for i in range(1, 200): event(i, 'starting')
    elif scenario == 'duplicate': event(0, 'starting')
    elif scenario == 'backward': event(-1, 'starting')
    elif scenario == 'wrong-session': event(1, 'planning', session='f' * 32)
    elif scenario == 'wrong-request': event(1, 'planning', request_id='f' * 32)
    elif scenario == 'v2': event(1, 'planning', version=2)
    elif scenario == 'phase': event(1, 'published')
    elif scenario == 'terminal-event': event(1, 'planning', kind='success')
    event(1, 'planning')
plan = (root / 'shown.bin').read_bytes()
answer = (root / 'answer.bin').read_bytes()
if scenario == 'changed-plan':
    d = json.loads(plan); d['document']['opaque'] = 'not displayed'
    plan = json.dumps(d).encode()
if scenario in ('wrong-result', 'verified'):
    d = json.loads(answer)
    d['request_id' if scenario == 'wrong-result' else 'verified'] = 'f' * 32 if scenario == 'wrong-result' else ['qwen3-base']
    answer = json.dumps(d).encode()
if scenario == 'partial-result': answer = answer[:20]
with (folder / 'plan.json').open('xb') as f: f.write(plan)
with (folder / 'result.json').open('xb') as f: f.write(answer)
if scenario != 'quiet': event(2, 'published')
os.write(2, b'inert diagnostic\n')
if scenario == 'truncated-utf8': os.write(2, b'\xf0\x9f')
if scenario == 'stderr-tail': os.write(2, b'unterminated')
if scenario in ('closed-stdout', 'child-pipe'):
    sys.stdout.close(); os.close(1)
if scenario == 'published-hang': time.sleep(30)
if scenario == 'crash': os._exit(7)
sys.exit(9 if scenario == 'nonzero' else 0)
'''
