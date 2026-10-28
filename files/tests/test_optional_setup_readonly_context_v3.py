"""M1 entry gate: production source ancestry must be proved before issuance."""
import sys
import dataclasses
import json
import contextlib
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures('production_writes_refused')


def test_native_main_origin_can_be_pinned_before_any_request_or_launch():
    from shared import optional_setup_readonly_context_v3 as context

    with context.qualify_main_origin() as origin:
        assert origin.interpreter == Path(sys.executable)
        assert origin.main_prefix == Path(sys.prefix)
        assert origin.base_prefix == Path(sys.base_prefix)
        assert origin.pinned_paths
        assert Path(origin.interpreter.anchor) in origin.pinned_paths
        assert all(path in origin.pinned_paths for path in origin.interpreter.parents)


def test_non_main_interpreter_is_refused_before_native_qualification(monkeypatch):
    from shared import optional_setup_readonly_context_v3 as context

    monkeypatch.setattr(sys, 'executable', str(Path(sys.base_prefix) / 'python.exe'))
    with pytest.raises(context.OriginUnavailable, match='main-console-identity'):
        with context.qualify_main_origin():
            pytest.fail('unqualified interpreter received origin authority')


def test_real_readonly_context_planner_without_fixture_adapters(tmp_path):
    from shared import optional_setup_readonly_context_v3 as context
    from shared import optional_setup_protocol as proto

    with context.issue_controlled_context(tmp_path / 'origin') as issued:
        run = context.ReadOnlyPlanningRun.create(issued, components=[proto.QWEN3_CUSTOMVOICE],
                                                engine_action='install-missing', timeout_s=30)
        run.start()
        outcome = run.wait()
        print('M1 NATIVE', {key: value for key, value in dataclasses.asdict(outcome).items()
                            if key not in ('retained_stdout', 'retained_stderr', 'raw_result')})
        assert outcome.accepted
        assert outcome.exit_code == 0 and outcome.job_active == 0 and outcome.readers_joined
        assert run.candidate() is not None
        document = json.loads(run.candidate().raw_disclosure)['document']
        print('M1 PLAN', document)
        assert document['reasons'] == ['BLOCKED: portable sox supply pending; existing local development only']
        assert document['terms'] is None and document['prior_state'] is None
        result = json.loads(run.candidate().raw_result)
        assert result['verified'] == [] and result['confirmable'] is False
        assert document['operations'] == {proto.QWEN3_CUSTOMVOICE: 'none'}
        assert not (run.repo / 'files/runtime-data/qwen3').exists()
        assert not (run.repo / '.venv').exists()


@pytest.mark.parametrize('field,value', [('executable', 'wrong-python.exe'),
    ('_base_executable', 'wrong-base.exe'), ('prefix', 'wrong-prefix')])
def test_main_identity_negative_controls(monkeypatch, field, value):
    from shared import optional_setup_readonly_context_v3 as context
    monkeypatch.setattr(sys, field, str(Path(sys.base_prefix) / value))
    with pytest.raises(context.OriginUnavailable, match='main-console-identity'):
        with context.qualify_main_origin():
            pytest.fail('wrong interpreter accepted')


@pytest.mark.parametrize('field,value', [('home', 'C:/synthetic-wrong-base'),
    ('executable', 'C:/synthetic-wrong.exe'), ('include-system-site-packages', 'true'),
    ('version', '3.12.0')])
def test_changed_cfg_refuses_before_disposable_creation(tmp_path, monkeypatch, field, value):
    from shared import optional_setup_readonly_context_v3 as context
    original = context._pin_file
    @contextlib.contextmanager
    def changed(path, **kwargs):
        with original(path, **kwargs) as raw:
            if path == context._REPO / '.venv/pyvenv.cfg':
                values = dict(line.split('=', 1) for line in raw.decode().splitlines() if '=' in line)
                values = {k.strip(): v.strip() for k, v in values.items()}
                values[field] = value
                raw = '\n'.join(f'{k} = {v}' for k, v in values.items()).encode()
            yield raw
    monkeypatch.setattr(context, '_pin_file', changed)
    root = tmp_path / 'cfg-refused'
    with pytest.raises(context.OriginUnavailable, match='main-venv-configuration'):
        with context.issue_controlled_context(root):
            pytest.fail('changed cfg accepted')
    assert not root.exists()


@pytest.mark.parametrize('damage', ['hardlink', 'reparse', 'opened-identity', 'late-identity', 'write-during-pin'])
def test_native_pins_reject_linked_or_changed_disposable_source(tmp_path, monkeypatch, damage):
    from shared import optional_setup_readonly_context_v3 as context
    from shared import optional_setup_exchange_v3 as exchange
    from shared import artifact_store as store
    source = tmp_path / 'source.py'
    source.write_bytes(b'fixture source only')
    if damage == 'hardlink':
        os.link(source, tmp_path / 'second.py')
    elif damage == 'reparse':
        from test_optional_tts_setup import _junction
        target = tmp_path / 'target'
        target.mkdir()
        (target / 'source.py').write_bytes(b'fixture source only')
        linked = tmp_path / 'linked'
        assert _junction(linked, target), 'mandatory native reparse case'
        source = linked / 'source.py'
    elif damage in ('opened-identity', 'late-identity'):
        identity = exchange._file_identity
        seen = []
        late = []
        def changed(stream, path):
            result = identity(stream, path)
            if path == source:
                seen.append(True)
                if late or damage == 'opened-identity' and len(seen) > 1:
                    return (*result[:2], result[2] + 1, *result[3:])
            return result
        monkeypatch.setattr(exchange, '_file_identity', changed)
    if damage == 'write-during-pin':
        with context._pin_file(source) as raw:
            with pytest.raises(OSError):
                source.write_bytes(b'changed')
            assert raw == source.read_bytes()
    else:
        with pytest.raises((context.OriginUnavailable, exchange.ExchangeError, store.ArtifactError, OSError)):
            with context._pin_file(source):
                if damage == 'late-identity':
                    late.append(True)
                else:
                    pytest.fail('unsafe source accepted')


def test_new_issuer_reparse_root_is_refused_before_origin_or_copy(tmp_path):
    from shared import optional_setup_readonly_context_v3 as context
    from test_optional_tts_setup import _junction
    target, linked = tmp_path / 'target', tmp_path / 'junction'
    target.mkdir()
    assert _junction(linked, target), 'mandatory native issuer reparse control'
    with pytest.raises(context.OriginUnavailable, match='source-reparse-ancestry'):
        with context.issue_controlled_context(linked / 'origin'):
            pytest.fail('linked issuer root accepted')
    assert list(target.iterdir()) == []


def test_new_issuer_fixed_command_environment_and_lifetime_pins(tmp_path, monkeypatch):
    from shared import optional_setup_readonly_context_v3 as context, optional_setup_protocol as proto
    from tts import qwen3_process
    with context.issue_controlled_context(tmp_path / 'fixed') as issued:
        run = context.ReadOnlyPlanningRun.create(issued, components=[proto.QWEN3_CUSTOMVOICE])
        real, seen = qwen3_process.spawn, []
        for name in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'SystemRoot'):
            monkeypatch.setenv(name, str(tmp_path / 'untrusted'))
        def inspect(argv, **kwargs):
            assert argv == [str(issued.interpreter), '-I', '-B', '-S', '-c', context._BOOTSTRAP,
                            run.planning.to_json()['request_id'], run.session]
            assert kwargs['cwd'] == str(run.repo / 'scripts') and kwargs['require_job'] is True
            env = kwargs['env']
            assert set(env) == {'SystemRoot', 'TEMP', 'TMP', 'TMPDIR', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'}
            assert env['SystemRoot'] == str(context.system_directory().parent)
            assert all(env[name] == str(issued.root) for name in ('TEMP', 'TMP', 'TMPDIR'))
            module = run.repo / 'scripts/tts/optional_setup_authority.py'
            with pytest.raises(OSError):
                module.write_bytes(b'changed during launch')
            with pytest.raises(OSError):
                module.parent.rename(module.parent.with_name('redirected'))
            seen.append(True)
            return real(argv, **kwargs)
        monkeypatch.setattr(qwen3_process, 'spawn', inspect)
        run.start()
        outcome = run.wait()
        assert outcome.accepted and seen == [True]
        assert outcome.job_active == 0 and outcome.readers_joined


@pytest.mark.parametrize('damage', ['extra', 'source-pin', 'forged-context', 'released-context'])
def test_new_issuer_launch_boundaries(tmp_path, monkeypatch, damage):
    from shared import optional_setup_readonly_context_v3 as context
    from shared import optional_setup_protocol as proto
    with context.issue_controlled_context(tmp_path / 'launch') as issued:
        run = context.ReadOnlyPlanningRun.create(issued, components=[proto.QWEN3_CUSTOMVOICE])
        if damage == 'extra':
            (run.repo / 'scripts/unreviewed.py').write_bytes(b'raise AssertionError')
        elif damage == 'source-pin':
            # The actual native pin must refuse replacement, then a changed
            # independently held digest must also refuse before spawning.
            module = run.repo / 'scripts/tts/optional_setup_authority.py'
            with pytest.raises(OSError):
                module.write_bytes(b'changed')
            raw_read = Path.read_bytes
            def changed(path):
                raw = raw_read(path)
                return raw + b'\n' if path == module else raw
            monkeypatch.setattr(Path, 'read_bytes', changed)
        elif damage == 'forged-context':
            run.context = dataclasses.replace(issued)
        else:
            context._ISSUED.pop(id(issued))
        run.start()
        outcome = run.wait()
        assert not outcome.accepted and outcome.errors == ('launch-failed',)
        assert run.process is None and run.candidate() is None


@pytest.mark.parametrize('damage', ['ancestry', 'image', 'birth', 'dll', 'job',
    'side-write', 'side-process', 'side-network', 'side-cwd', 'late-import', 'native-import',
    'native-dlopen', 'timeout', 'crash', 'output'])
def test_native_worker_refusal_controls(tmp_path, monkeypatch, damage, mutation=None):
    from shared import optional_setup_readonly_context_v3 as context
    from shared import optional_setup_protocol as proto
    # Trusted negative instrumentation, independent of wire input. No synthetic
    # readiness is supplied to this issuer or used as a positive qualification.
    changes = {
        'ancestry': 'w._parent_pid = lambda pid: pid',
        'image': "w.origin.process_identity = lambda pid: (w.Path('wrong.exe'), 1)",
        'birth': "real_identity = w.origin.process_identity\nw.origin.process_identity = lambda pid: (real_identity(pid)[0], 0)",
        'dll': "w.origin.native_modules = lambda: (w.Path('unapproved-native.dll').absolute(),)",
        'job': ('kernel = w.origin.exchange._kernel()\nkernel.IsProcessInJob = lambda *args: 0\n'
                'w.origin.exchange._kernel = lambda: kernel'),
        'side-write': "effect = lambda: w.Path('unapproved-write').write_bytes(b'blocked')",
        'side-process': "effect = lambda: __import__('subprocess').Popen(['unapproved-process.exe'])",
        'side-network': "effect = lambda: __import__('socket').getaddrinfo('example.invalid', 443)",
        'side-cwd': "effect = lambda: w.os.chdir('..')",
        'late-import': ("w.Path('unapproved.py').write_bytes(b'raise AssertionError')\n"
                        "effect = lambda: __import__('unapproved')"),
        'native-import': ("effect = lambda: sys.audit('import', 'unapproved', "
                          "str(w.Path('unapproved.pyd').absolute()), None, None, None)"),
        'native-dlopen': "effect = lambda: w.ctypes.WinDLL(str(w.Path('unapproved-native.dll').absolute()))",
        'timeout': "__import__('time').sleep(30)",
        'crash': 'w.os._exit(9)',
        'output': "w.os.write(1, b'invalid output\\n')",
    }
    code = 'import os,sys;sys.path.insert(0,os.getcwd());from tts import optional_setup_readonly_worker_v3 as w\n'
    code += changes[damage] + '\n'
    effects = damage.startswith('side-') or damage in ('late-import', 'native-import', 'native-dlopen')
    if effects:
        code += '''
def trace(frame, event, arg):
    if event == 'call' and frame.f_code is w.authority.observe.__code__:
        try:
            effect()
        except PermissionError:
            pass
    return trace
sys.settrace(trace)
'''
    if mutation:
        code += '''
import inspect, textwrap
source = textwrap.dedent(inspect.getsource(w.main))
REPLACEMENT
exec(compile(source, w.__file__, 'exec'), w.__dict__)
'''.replace('REPLACEMENT', ("assert source.count('if refused:') == 1\n"
    "source = source.replace('if refused:', 'if False:')") if mutation == 'ignore-caught-effect' else
    ("assert source.count(\"if event == 'import' and isinstance(args[1], str):\") == 1\n"
     "source = source.replace(\"if event == 'import' and isinstance(args[1], str):\", 'if False:')"))
    code += 'sys.exit(w.main())'
    monkeypatch.setattr(context, '_BOOTSTRAP', code)
    with context.issue_controlled_context(tmp_path / 'worker-refusal') as issued:
        run = context.ReadOnlyPlanningRun.create(issued, components=[proto.QWEN3_CUSTOMVOICE], timeout_s=3)
        run.start()
        outcome = run.wait()
        assert not outcome.accepted and run.candidate() is None, outcome
        assert outcome.job_active == 0 and outcome.readers_joined and not outcome.process_running
        assert not (run.repo / 'scripts/unapproved-write').exists()
        if damage == 'timeout':
            assert 'timed-out' in outcome.errors
        elif damage == 'output':
            assert 'invalid-output' in outcome.errors
        else:
            assert outcome.exit_code != 0
        if effects:
            assert outcome.events == 2 and outcome.stderr_bytes == 0
            assert not run.result_path.exists()
        if damage in ('ancestry', 'image', 'birth', 'dll', 'job'):
            code = {'ancestry': 'process-ancestry-cycle', 'image': 'process-ancestry-image',
                    'birth': 'process-ancestry-birth', 'dll': 'native-dll-origin', 'job': 'worker-not-contained'}[damage]
            assert ('read-only-refused:' + code).encode() in outcome.retained_stderr
        print('M1 NATIVE EXPECTED REFUSAL', damage, outcome.errors)


@pytest.mark.parametrize('damage', ['assignment', 'unknown', 'contradictory', 'missing'])
def test_new_run_job_accounting_controls(tmp_path, monkeypatch, damage):
    from shared import optional_setup_readonly_context_v3 as context, optional_setup_protocol as proto
    from tts import qwen3_process
    with context.issue_controlled_context(tmp_path / 'job') as issued:
        run = context.ReadOnlyPlanningRun.create(issued, components=[proto.QWEN3_CUSTOMVOICE])
        if damage == 'assignment':
            def denied(*a):
                raise OSError('synthetic native assignment refusal')
            monkeypatch.setattr(qwen3_process.ProcessJob, 'assign', denied)
        elif damage in ('unknown', 'contradictory'):
            monkeypatch.setattr(qwen3_process.ProcessJob, 'accounting',
                lambda self: (None, None) if damage == 'unknown' else (2, 1))
        else:
            real = run._account
            def missing():
                job, run.process.act_job = run.process.act_job, None
                try:
                    real()
                finally:
                    run.process.act_job = job
            monkeypatch.setattr(run, '_account', missing)
        run.start()
        outcome = run.wait()
        assert not outcome.accepted and run.candidate() is None
        assert ('launch-failed' if damage == 'assignment' else 'missing-job' if damage == 'missing'
                else 'job-accounting-unknown') in outcome.errors


def test_new_run_live_grandchild_is_rejected_and_reaped(tmp_path, monkeypatch):
    from shared import optional_setup_readonly_context_v3 as context, optional_setup_protocol as proto
    from test_optional_setup_supervisor_v3 import wait_gone
    code = '''
import os,sys,time,subprocess
sys.path.insert(0,os.getcwd())
child = "import os,time;from pathlib import Path;Path('descendant.pid').write_text(str(os.getpid()));time.sleep(30)"
subprocess.Popen([sys.executable, '-I', '-B', '-S', '-c', child], cwd=os.getcwd(), env=dict(os.environ))
from pathlib import Path
deadline = time.monotonic() + 3
while not Path('descendant.pid').exists():
    assert time.monotonic() < deadline
    time.sleep(.01)
from tts.optional_setup_readonly_worker_v3 import main
sys.exit(main())
'''
    monkeypatch.setattr(context, '_BOOTSTRAP', code)
    with context.issue_controlled_context(tmp_path / 'grandchild') as issued:
        run = context.ReadOnlyPlanningRun.create(issued, components=[proto.QWEN3_CUSTOMVOICE], timeout_s=10)
        run.start()
        outcome = run.wait()
        assert not outcome.accepted and 'live-descendant' in outcome.errors
        assert outcome.job_before_cleanup > 0 and outcome.job_active == 0 and outcome.readers_joined
        assert run.candidate() is None
        wait_gone(int((run.repo / 'scripts/descendant.pid').read_text()))


@pytest.mark.parametrize('mutant', ['interpreter', 'cfg', 'extra-module', 'source-pin'])
def test_new_issuer_mutation_controls(tmp_path, monkeypatch, mutant):
    from shared import optional_setup_readonly_context_v3 as context
    from test_optional_setup_planning_worker_v3 import _mutated
    if mutant == 'interpreter':
        # Contextmanager wraps a generator; mutate the original generator body.
        target, name = context, 'qualify_main_origin'
        replacement = [('Path(sys._base_executable) != base / \'python.exe\'', 'False')]
        control = lambda: test_main_identity_negative_controls(monkeypatch, '_base_executable', 'wrong-base.exe')
    elif mutant == 'cfg':
        target, name = context, 'issue_controlled_context'
        replacement = [("values.get('include-system-site-packages') != 'false'", 'False')]
        control = lambda: test_changed_cfg_refuses_before_disposable_creation(tmp_path, monkeypatch,
                            'include-system-site-packages', 'true')
    elif mutant == 'extra-module':
        target, name = context.ReadOnlyPlanningRun, '_spawn_fake'
        replacement = [('entry not in files | directories', 'False')]
        control = lambda: test_new_issuer_launch_boundaries(tmp_path, monkeypatch, 'extra')
    else:
        target, name = context.ReadOnlyPlanningRun, '_spawn_fake'
        replacement = [('hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest', 'False')]
        control = lambda: test_new_issuer_launch_boundaries(tmp_path, monkeypatch, 'source-pin')
    if mutant in ('interpreter', 'cfg'):
        wrapped = getattr(context, name)
        monkeypatch.setattr(context, name, wrapped.__wrapped__)
        _mutated(target, name, replacement, monkeypatch)
        monkeypatch.setattr(context, name, contextlib.contextmanager(getattr(context, name)))
    else:
        _mutated(target, name, replacement, monkeypatch)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        control()
    print('M1 ISSUER MUTATION CAUGHT', mutant)


@pytest.mark.parametrize('mutant,damage', [('ignore-caught-effect', 'side-write'), ('native-import', 'native-import')])
def test_sticky_effect_worker_mutation(tmp_path, monkeypatch, mutant, damage):
    with pytest.raises(AssertionError):
        test_native_worker_refusal_controls(tmp_path, monkeypatch, damage, mutation=mutant)
    print('M1 WORKER MUTATION CAUGHT', mutant)
