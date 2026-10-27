"""Offline Stage 4D-2B fake-worker qualification. Native Windows is mandatory."""
import dataclasses
import ctypes
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from shared import optional_setup_protocol as proto
from shared import optional_setup_wire_v3 as wire
from test_optional_setup_wire_v3 import SESSION, P, NOW, planning, disclosure

pytestmark = pytest.mark.usefixtures('production_writes_refused')


def make_run(tmp_path, scenario='ok', **kwargs):
    from shared import optional_setup_supervisor_v3 as supervisor
    assert sys.platform == 'win32', 'native Windows qualification is mandatory'
    request = planning()
    shown = disclosure(request=request)
    return supervisor.FakePlanningRun.for_test(tmp_path / 'fake-run', planning=request,
        disclosure=shown, session=SESSION, scenario=scenario, now=lambda: NOW, **kwargs)


def test_native_planning_is_bound_drained_empty_and_immutable(tmp_path):
    run = make_run(tmp_path)
    run.start()
    outcome = run.wait()
    assert outcome.accepted and outcome.state == 'accepted'
    assert outcome.errors == () and outcome.exit_code == 0
    assert outcome.job_active == 0 and outcome.job_total >= 1
    assert outcome.readers_joined and outcome.output_complete and not outcome.process_running
    assert outcome.events == 3 and outcome.stdout_bytes > 0 and outcome.stderr_bytes > 0
    expected = wire.encode_planning_result(disclosure=run.disclosure,
        issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    assert outcome.raw_result == expected == run.result_path.read_bytes()
    assert outcome.stdout_bytes == len(outcome.retained_stdout)
    assert outcome.stderr_bytes == len(outcome.retained_stderr) == len(b'inert diagnostic\n')
    print('NATIVE', json.dumps({'case': 'accepted', 'active': outcome.job_active,
        'total': outcome.job_total, 'stdout': outcome.stdout_bytes, 'stderr': outcome.stderr_bytes,
        'joined': outcome.readers_joined}))
    assert run.wait() is outcome and run.stop() is outcome and run.result() is outcome
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.accepted = False


def finished(run):
    run.start()
    result = run.wait()
    assert result is run.wait() is run.result()
    return result


def wait_file(path):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        if path.exists() and path.stat().st_size:
            return path.read_bytes()
        time.sleep(.01)
    raise AssertionError('owned marker did not appear')


def gone(pid):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        assert ctypes.get_last_error() == 87
        return True
    try:
        return kernel.WaitForSingleObject(handle, 0) == 0
    finally:
        kernel.CloseHandle(handle)


def wait_gone(pid):
    end = time.monotonic() + 2
    while time.monotonic() < end:
        if gone(pid):
            return True
        time.sleep(.01)
    return False


@pytest.mark.parametrize('scenario,code', [
    ('no-result', 'planning-exchange-refused'), ('nonzero', 'exit-result-disagreement'),
    ('crash', 'exit-result-disagreement'), ('wrong-result', 'planning-exchange-refused'),
    ('verified', 'planning-exchange-refused'), ('changed-plan', 'planning-exchange-refused'),
    ('partial-result', 'planning-exchange-refused'),
    ('invalid-json', 'invalid-output'), ('utf8', 'invalid-output'),
    ('overlong', 'line-limit'), ('no-newline', 'invalid-output'),
    ('flood', 'output-limit'), ('event-flood', 'event-limit'),
    ('duplicate', 'invalid-output'), ('backward', 'invalid-output'),
    ('wrong-session', 'invalid-output'), ('wrong-request', 'invalid-output'),
    ('v2', 'invalid-output'), ('phase', 'invalid-output'), ('terminal-event', 'invalid-output'),
    ('truncated-utf8', 'unterminated-output'), ('stderr-tail', 'unterminated-output'),
])
def test_each_terminal_contradiction_refuses(tmp_path, scenario, code):
    from shared import optional_setup_supervisor_v3 as supervisor
    run = make_run(tmp_path, scenario)
    outcome = finished(run)
    assert not outcome.accepted and code in outcome.errors
    assert outcome.job_active == 0 and outcome.readers_joined
    assert not outcome.process_running and gone(int((run.root / 'worker.pid').read_text()))
    assert outcome.events <= supervisor.MAX_EVENTS
    assert len(outcome.retained_stdout) <= supervisor.MAX_RETAINED
    assert len(outcome.retained_stderr) <= supervisor.MAX_RETAINED
    assert outcome.stdout_bytes <= supervisor.MAX_OUTPUT + 1
    assert outcome.stderr_bytes <= supervisor.MAX_OUTPUT + 1


@pytest.mark.parametrize('scenario', ['child-left', 'child-pipe'])
def test_native_success_claim_with_live_grandchild_is_rejected_and_reaped(tmp_path, scenario):
    run = make_run(tmp_path, scenario)
    outcome = finished(run)
    assert not outcome.accepted and 'live-descendant' in outcome.errors
    assert outcome.raw_result is not None and outcome.exit_code == 0
    assert outcome.job_before_cleanup >= 1 and outcome.job_active == 0 and outcome.job_total >= 2
    assert outcome.readers_joined and outcome.output_complete
    assert gone(int((run.root / 'worker.pid').read_text()))
    assert gone(int((run.root / 'grand.pid').read_text()))
    print('NATIVE', json.dumps({'case': scenario, 'active_before': outcome.job_before_cleanup,
        'active_after': outcome.job_active, 'total': outcome.job_total,
        'parent_gone': True, 'grandchild_gone': True, 'joined': outcome.readers_joined}))


@pytest.mark.parametrize('scenario', ['hang', 'child-hang', 'published-hang', 'stdout-hang'])
def test_native_timeout_is_finite_and_empties_job(tmp_path, scenario):
    run = make_run(tmp_path, scenario, timeout_s=.5)
    started = time.monotonic()
    outcome = finished(run)
    assert time.monotonic() - started < 5
    assert not outcome.accepted and 'timed-out' in outcome.errors
    assert outcome.job_active == 0 and outcome.readers_joined and not outcome.process_running
    assert gone(int((run.root / 'worker.pid').read_text()))
    if scenario == 'child-hang':
        assert gone(int((run.root / 'grand.pid').read_text())) and outcome.job_total >= 2
        print('NATIVE', json.dumps({'case': scenario, 'active_after': outcome.job_active,
            'total': outcome.job_total, 'parent_gone': True, 'grandchild_gone': True}))


@pytest.mark.parametrize('published', [False, True])
def test_native_cancellation_cannot_accept_an_earlier_published_result(tmp_path, published):
    run = make_run(tmp_path, 'published-hang' if published else 'child-hang')
    run.start()
    path = run.result_path if published else run.root / 'grand.pid'
    before = wait_file(path)
    run.cancel()
    outcome = run.wait()
    assert not outcome.accepted and outcome.state == 'cancelled' and 'cancelled' in outcome.errors
    assert outcome.job_active == 0 and outcome.readers_joined
    assert path.read_bytes() == before
    if published:
        assert outcome.raw_result == before
    else:
        assert gone(int(before))
    assert not (run.result_path.parent / 'cancel.json').exists()


def test_cancel_before_start_never_executes(tmp_path):
    run = make_run(tmp_path)
    run.cancel()
    outcome = finished(run)
    assert outcome.state == 'cancelled' and not outcome.accepted and run.process is None
    assert not (run.root / 'worker.pid').exists() and not run.result_path.exists()


def test_callback_exception_is_fatal_and_called_only_once(tmp_path):
    calls = []
    def callback(event):
        calls.append(event)
        raise RuntimeError('untrusted detail must not enter outcome')
    outcome = finished(make_run(tmp_path, 'published-hang', on_event=callback))
    assert not outcome.accepted and 'callback-failed' in outcome.errors and len(calls) == 1
    assert outcome.job_active == 0 and outcome.readers_joined
    assert 'untrusted detail' not in repr(outcome)


def test_callback_can_cancel_reentrantly_without_deadlock(tmp_path):
    run = make_run(tmp_path, 'published-hang', on_event=lambda event: run.cancel())
    outcome = finished(run)
    assert outcome.state == 'cancelled' and not outcome.accepted
    assert outcome.readers_joined and outcome.job_active == 0


def test_multiple_callers_observe_one_terminal_decision(tmp_path):
    run = make_run(tmp_path, 'published-hang')
    run.start()
    wait_file(run.result_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(run.wait) for _ in range(4)]
        futures += [pool.submit(run.stop) for _ in range(4)]
        outcomes = [future.result(timeout=6) for future in futures]
    assert all(item is outcomes[0] for item in outcomes) and outcomes[0].state == 'cancelled'
    assert run.result() is outcomes[0] and run.stop() is outcomes[0]
    with pytest.raises(RuntimeError):
        run.start()


@pytest.mark.parametrize('scenario', ['quiet', 'closed-stdout'])
def test_optional_events_and_normal_closed_stdout_are_safe(tmp_path, scenario):
    result = finished(make_run(tmp_path, scenario))
    assert result.accepted and result.readers_joined and result.output_complete
    assert result.events == (0 if scenario == 'quiet' else 3)


@pytest.mark.parametrize('fault', ['create', 'assign'])
def test_native_containment_failure_prevents_first_instruction(tmp_path, monkeypatch, fault):
    from tts import qwen3_process
    run = make_run(tmp_path)
    def fail(*args):
        raise OSError('injected job refusal')
    monkeypatch.setattr(qwen3_process.ProcessJob, '__init__' if fault == 'create' else 'assign', fail)
    outcome = finished(run)
    assert not outcome.accepted and outcome.errors == ('launch-failed',)
    assert not (run.root / 'worker.pid').exists() and not run.result_path.exists()


@pytest.mark.parametrize('fault', ['unknown', 'nonzero', 'missing', 'termination'])
def test_narrow_accounting_and_termination_faults_never_accept(tmp_path, monkeypatch, fault):
    from shared import optional_setup_supervisor_v3 as supervisor
    from tts import qwen3_process
    original = supervisor.FakePlanningRun._account
    saved = []
    def account(self):
        if fault == 'missing':
            if self.process.act_job:
                saved.append(self.process.act_job)
                self.process.act_job = None
            original(self)
        else:
            original(self)
    if fault in ('unknown', 'nonzero'):
        def query(self):
            if fault == 'unknown':
                raise OSError('injected failed native accounting query')
            return 1, 2
        monkeypatch.setattr(qwen3_process.ProcessJob, 'accounting', query)
    run = make_run(tmp_path, 'child-hang' if fault == 'termination' else 'ok',
                   timeout_s=.4, cleanup_s=.15, join_s=.2)
    monkeypatch.setattr(supervisor.FakePlanningRun, '_account', account)
    if fault == 'termination':
        def refuse(self):
            self._termination_failed = True
            self._error('job-termination-failed')
        monkeypatch.setattr(supervisor.FakePlanningRun, '_terminate_job', refuse)
    try:
        outcome = finished(run)
        assert not outcome.accepted
        expected = {'unknown': 'job-accounting-unknown', 'nonzero': 'job-not-proven-empty',
                    'missing': 'missing-job', 'termination': 'job-termination-failed'}[fault]
        assert expected in outcome.errors
        if fault == 'termination':
            assert outcome.termination_failed and outcome.job_active > 0 and outcome.process_running
            assert not outcome.readers_joined
        elif fault in ('unknown', 'missing'):
            assert outcome.job_active is None
    finally:
        for job in saved:
            assert job.accounting()[0] == 0
            job.close()
    # Kill-on-close cleanup after an injected failed termination is separately
    # proved; it cannot retroactively convert the saved failure to success.
    if fault == 'termination':
        run.process.wait(timeout=3)
        for reader in run._readers:
            reader.join(2)
        assert wait_gone(int((run.root / 'grand.pid').read_text()))
        assert run.result() is outcome and not outcome.accepted


@pytest.mark.parametrize('fault', ['exception', 'unjoined'])
def test_reader_fault_is_fatal(tmp_path, monkeypatch, fault):
    from shared import optional_setup_supervisor_v3 as supervisor
    original = supervisor.FakePlanningRun._read
    release = threading.Event()
    def broken(self, stream, output, events):
        if not events:
            return original(self, stream, output, events)
        if fault == 'exception':
            stream.close()
            self._error('reader-failed')
        else:
            release.wait(3)
            original(self, stream, output, events)
    monkeypatch.setattr(supervisor.FakePlanningRun, '_read', broken)
    run = make_run(tmp_path, join_s=.1)
    try:
        outcome = finished(run)
        assert not outcome.accepted and 'output-incomplete' in outcome.errors
        assert ('reader-failed' if fault == 'exception' else 'reader-still-running') in outcome.errors
    finally:
        release.set()
        for reader in run._readers:
            reader.join(2)


def test_arbitration_never_rewrites_worker_result(tmp_path):
    run = make_run(tmp_path, 'nonzero')
    run.start()
    outcome = run.wait()
    before = run.result_path.read_bytes()
    metadata = run.result_path.stat()
    assert outcome.raw_result == before and not outcome.accepted
    for _ in range(5):
        assert run.stop() is run.wait() is run.result() is outcome
    assert run.result_path.read_bytes() == before
    assert run.result_path.stat().st_mtime_ns == metadata.st_mtime_ns
    assert {p.name for p in run.result_path.parent.iterdir()} == {'request.json', 'plan.json', 'result.json'}


@pytest.mark.parametrize('field', ['session', 'planning', 'disclosure', 'timeout', 'scenario', 'root'])
def test_trusted_admission_refuses_before_launch_or_fixture_write(tmp_path, field):
    from shared import optional_setup_supervisor_v3 as supervisor
    request = planning()
    shown = disclosure(request=request)
    root = tmp_path / 'invalid'
    kwargs = dict(planning=request, disclosure=shown, session=SESSION, now=lambda: NOW)
    if field == 'session': kwargs['session'] = 'f' * 32
    if field == 'planning':
        d = request.to_json(); d['version'] = 2
        kwargs['planning'] = wire.PlanningRequest(json.dumps(d).encode())
    if field == 'disclosure': kwargs['disclosure'] = wire.Disclosure(shown.raw, b'changed')
    if field == 'timeout': kwargs['timeout_s'] = float('inf')
    if field == 'scenario': kwargs['scenario'] = [sys.executable, '-c', 'pass']
    if field == 'root': root = Path(__file__).resolve().parents[2]
    with pytest.raises((ValueError, proto.ProtocolError)):
        supervisor.FakePlanningRun.for_test(root, **kwargs)
    if field != 'root': assert not root.exists()


def test_launch_is_fixed_and_environment_is_scrubbed(tmp_path, monkeypatch):
    from tts import qwen3_process
    original = qwen3_process.spawn
    seen = []
    def inspect(argv, **kwargs):
        seen.append((argv, kwargs))
        return original(argv, **kwargs)
    monkeypatch.setattr(qwen3_process, 'spawn', inspect)
    monkeypatch.setenv('PYTHONPATH', 'untrusted')
    monkeypatch.setenv('PIP_TARGET', 'untrusted')
    monkeypatch.setenv('VIRTUAL_ENV', 'untrusted')
    run = make_run(tmp_path)
    assert finished(run).accepted
    argv, kwargs = seen[0]
    assert argv == [sys.executable, '-I', '-B', '-S', str(run.root / 'fake_worker.py'), 'ok']
    assert kwargs['require_job'] is True and kwargs['cwd'] == str(run.root)
    env = kwargs['env']
    assert set(env) == {'SystemRoot', 'TEMP', 'TMP', 'TMPDIR', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'}
    assert all(env[name] == str(run.root) for name in ('TEMP', 'TMP', 'TMPDIR'))


def test_changed_fixed_program_cannot_be_launched(tmp_path):
    run = make_run(tmp_path)
    (run.root / 'fake_worker.py').write_text('raise RuntimeError("changed")')
    assert finished(run).errors == ('launch-failed',)
    assert not (run.root / 'worker.pid').exists()


def test_cancel_after_parent_exit_before_arbitration_wins(tmp_path, monkeypatch):
    from shared import optional_setup_exchange_v3 as exchange
    original = exchange.read_planning_exchange
    ready, release = threading.Event(), threading.Event()
    def pause(*args, **kwargs):
        checked = original(*args, **kwargs)
        ready.set()
        assert release.wait(2)
        return checked
    monkeypatch.setattr(exchange, 'read_planning_exchange', pause)
    run = make_run(tmp_path)
    run.start()
    try:
        assert ready.wait(3) and run.process.poll() == 0 and run.result() is None
        before = run.result_path.read_bytes()
        run.cancel()
    finally:
        release.set()
    outcome = run.wait()
    assert outcome.state == 'cancelled' and not outcome.accepted and outcome.raw_result == before
    assert run.result_path.read_bytes() == before and outcome.job_active == 0


@pytest.mark.parametrize('field,value', [('version', True), ('seq', True), ('seq', 0),
    ('phase', 'published'), ('kind', 'success'), ('extra', 'ignored'),
    ('protocol', 'act-optional-setup'), ('session', 'f' * 32), ('request_id', 'f' * 32)])
def test_event_schema_is_strict_independently_of_process(tmp_path, field, value):
    from shared import optional_setup_supervisor_v3 as supervisor
    run = make_run(tmp_path)
    event = dict(protocol=supervisor.EVENT_PROTOCOL, version=3, request_id=P,
        session=SESSION, seq=0, kind='progress', phase='starting')
    run._event(json.dumps(event).encode())
    event.update(seq=1, phase='planning')
    event[field] = value
    with pytest.raises((ValueError, proto.ProtocolError)):
        run._event(json.dumps(event).encode())


@pytest.mark.parametrize('raw', [b'{}', b'[]', b'null', b'{"seq":1,"seq":2}', b'\xff',
                               b'[' * 25 + b'0' + b']' * 25])
def test_malformed_event_never_promotes_to_success(tmp_path, raw):
    run = make_run(tmp_path)
    with pytest.raises((ValueError, proto.ProtocolError)):
        run._event(raw)


@pytest.mark.parametrize('target', ['request.json', 'plan.json', 'result.json'])
def test_completed_exchange_substitution_is_refused(tmp_path, monkeypatch, target):
    from shared import optional_setup_exchange_v3 as exchange
    original = exchange.read_planning_exchange
    run = make_run(tmp_path)
    def tamper(*args, **kwargs):
        (run.result_path.parent / target).write_bytes(b'{}')
        return original(*args, **kwargs)
    monkeypatch.setattr(exchange, 'read_planning_exchange', tamper)
    outcome = finished(run)
    assert not outcome.accepted and outcome.errors == ('planning-exchange-refused',)


def test_native_termination_bool_failure_is_retained(tmp_path, monkeypatch):
    from tts import qwen3_process
    original = qwen3_process.ProcessJob.__init__
    class RefuseTerminate:
        def __init__(self, native): self.native = native
        def __getattr__(self, name): return getattr(self.native, name)
        def TerminateJobObject(self, *args): return 0
    def create(self):
        original(self)
        self._k = RefuseTerminate(self._k)
    monkeypatch.setattr(qwen3_process.ProcessJob, '__init__', create)
    run = make_run(tmp_path, 'child-hang', timeout_s=.4, cleanup_s=.1, join_s=.1)
    outcome = finished(run)
    assert not outcome.accepted and outcome.termination_failed and 'job-termination-failed' in outcome.errors
    assert outcome.job_active > 0 and 'job-not-proven-empty' in outcome.errors
    run.process.wait(timeout=3)
    for reader in run._readers: reader.join(2)
    assert wait_gone(int((run.root / 'grand.pid').read_text()))


def test_blocked_callback_cannot_extend_join_deadline_or_accept(tmp_path):
    ready, release = threading.Event(), threading.Event()
    def callback(event):
        ready.set()
        release.wait(3)
    run = make_run(tmp_path, 'published-hang', on_event=callback, timeout_s=.4, join_s=.1)
    run.start()
    try:
        assert ready.wait(2)
        outcome = run.wait()
        assert not outcome.accepted and 'reader-still-running' in outcome.errors
        assert outcome.job_active == 0 and not outcome.readers_joined
    finally:
        release.set()
        for reader in run._readers: reader.join(2)
    assert run.result() is outcome and not outcome.readers_joined
