"""4D-2D: candidate admission and contained actual Planner, disposable Windows only."""
import dataclasses
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from shared import optional_setup_exchange_v3 as exchange
from shared import optional_setup_protocol as proto
from shared import optional_setup_wire_v3 as wire
from test_optional_setup_wire_v3 import planning, disclosure, SESSION, P, NOW

pytestmark = pytest.mark.usefixtures('production_writes_refused')


def test_candidate_is_not_retained_original(tmp_path):
    request, shown = planning(), disclosure()
    exchange.publish_planning_request(tmp_path, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    assert exchange._read_published_planning_request(tmp_path, session=SESSION, request_id=P,
        now=lambda: NOW) == request
    raw = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    exchange.publish_planning_response(tmp_path, planning=request, disclosure=shown,
        raw_result=raw, session=SESSION, now=lambda: NOW)
    candidate = exchange._read_untrusted_planning_candidate(tmp_path, planning=request,
        session=SESSION, now=lambda: NOW)
    assert candidate.raw_disclosure == shown.raw and candidate.raw_result == raw
    assert type(candidate) is exchange.UntrustedPlanningCandidate
    with pytest.raises((exchange.ExchangeError, proto.ProtocolError)):
        exchange.read_planning_exchange(tmp_path, planning=request, expected_disclosure=candidate,
            session=SESSION, now=lambda: NOW)
    # Fixed test controller: emulate separate accept/display/retain. No UI claim.
    displayed = bytes(candidate.raw_disclosure)
    retained = wire.decode_disclosure(displayed, planning=request, session=SESSION, now=lambda: NOW)
    checked = exchange.read_planning_exchange(tmp_path, planning=request, expected_disclosure=retained,
        session=SESSION, now=lambda: NOW)
    assert checked.disclosure.raw == displayed


# Independently reviewed TEST CODE. Copied outside the exchange and pinned by
# ApprovedDisposableContext; neither request JSON nor worker output selects it.
# These are synthetic facts, not HOME-PC engine/model availability evidence.
FIXTURE_ADAPTER = r'''
import dataclasses, hashlib, json, os, sys
from pathlib import Path
from shared import artifact_store as store, artifact_transfer as transfer
from shared import optional_setup_protocol as proto, optional_setup_resource_budget as resources
from shared import optional_setup_v3 as v3
from tts import optional_setup_authority as auth, qwen3_runtime as rt, qwen3_setup as setup
from tts import optional_setup_planning_worker_v3 as worker
ROOT = Path(__file__).absolute().parents[1]
assert rt.repo_root() == ROOT
(ROOT / 'adapter-started').write_text(str(os.getpid()))
ALLOW_TEST_CHILD = False
CHILD_CODE = "import os,time;from pathlib import Path;Path('descendant.pid').write_text(str(os.getpid()));time.sleep(30)"
def forbidden(*a, **k):
    raise AssertionError('execution/acquisition capability is excluded')
# Belt-and-braces negative controls in a trusted offline fixture, not new authority.
auth.Planner.acquire_disposable = forbidden
transfer.TransferLedger.begin = forbidden
v3.validate_and_spend = forbidden
proto.claim_consent = forbidden
setup.install_environment = forbidden
setup.repair = forbidden
def audit(event, args):
    if event == 'subprocess.Popen':
        expected = [sys.executable, '-I', '-B', '-S', '-c', CHILD_CODE]
        assert ALLOW_TEST_CHILD and args[1] in (expected, setup.subprocess.list2cmdline(expected))
        assert Path(args[2]) == ROOT
    if event in ('socket.connect', 'socket.getaddrinfo', 'os.system'):
        forbidden()
    if event == 'import' and args[0].split('.')[0] in ('torch', 'numpy', 'transformers', 'pip', 'spacy'):
        forbidden()
    if event in ('open', 'os.scandir', 'os.listdir') and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0])).absolute()
        # stdlib reads only; all application observations stay inside this fixture.
        stdlib = Path(sys.base_prefix) / 'Lib'
        assert path.is_relative_to(ROOT) or path.is_relative_to(stdlib), ('read escape', event, str(path))
        if event == 'open' and isinstance(args[2], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            assert path.is_relative_to(ROOT), ('write escape', str(path))
sys.addaudithook(audit)
def diagnostic(frame, event, arg):
    if event == 'exception' and frame.f_code.co_name == 'main' and frame.f_code.co_filename.endswith('optional_setup_planning_worker_v3.py'):
        (ROOT / 'diagnostic.json').write_text(json.dumps([arg[0].__name__, str(arg[1])[:4096]]))
    return diagnostic
sys.settrace(diagnostic)
models = {}
for key, label, revision in (('customvoice', 'CustomVoice', 'a'), ('base', 'Base', 'b')):
    payload = b'synthetic-' + key.encode()
    models[key] = dict(label=label, repo='Qwen/Fixture-' + label, revision=revision * 40,
        license='apache-2.0', voices=[], dir=label + '-fixture',
        files={'model.safetensors': dict(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())})
rt.load_manifest = lambda: dict(schema=1, models=models,
    environment=dict(approx_download_bytes=32, approx_installed_bytes=64))
auth.MODEL_IDENTITIES_SHA256 = auth.model_identities_sha256()
rt.platform_supported = lambda: True
rt.bundle_status = lambda: (True, '')
auth.old_plan._reference_problem = lambda: ''
STATE = proto.READY
def observe(selected, *, locked, cancelled):
    # Stack evidence from the actual contained process: actual Planner.plan and
    # _evaluate code origins/IDs, with no replacement of either implementation.
    frames = []
    frame = sys._getframe()
    while frame:
        if frame.f_code.co_name in ('plan', '_evaluate'):
            frames.append([frame.f_code.co_name, frame.f_code.co_filename])
        frame = frame.f_back
    (ROOT / 'observation.json').write_text(json.dumps(dict(pid=os.getpid(), root=str(ROOT),
        selected=list(selected), locked=locked, frames=frames,
        limits=[resources.MAX_OPERATIONS, resources.MAX_EVENTS, resources.MAX_PARTIALS,
                resources.MAX_ENTRIES, resources.MAX_BYTES, resources.MAX_SECONDS])))
    return auth.Observation({}, STATE)
PLANNER = auth.Planner(observer=observe, disk_free=lambda root: 10**12, purpose='synthetic-qualification')
def context():
    return worker.DisposablePlanningContext(PLANNER)
'''


def make_real(tmp_path, *, extra='', action='none', on_event=None, **kwargs):
    from shared import optional_setup_planning_bridge_v3 as bridge
    assert sys.platform == 'win32', 'mandatory native Windows qualification'
    context = bridge.ApprovedDisposableContext.for_test(tmp_path / 'run',
        adapter_source=(FIXTURE_ADAPTER + '\n' + extra).encode())
    raw = wire.encode_planning_request(request_id='b' * 32, intended_request_id='c' * 32,
        session=SESSION, plan_id='d' * 32, components=[proto.QWEN3_CUSTOMVOICE], engine_action=action,
        issued_utc=proto.utc_text(time.time()))
    request = wire.decode_planning_request(raw, session=SESSION, request_id='b' * 32)
    return bridge.PlanningRun.for_test(context=context, planning=request, session=SESSION,
        on_event=on_event, **kwargs)


def finished(run):
    run.start()
    outcome = run.wait()
    print('NATIVE REAL PLANNER', dataclasses.asdict(outcome) | {
        'raw_result': None, 'retained_stdout': None, 'retained_stderr': None})
    if outcome.stderr_bytes:
        print('BOUNDED WORKER STDERR', outcome.retained_stderr)
    return outcome


def test_actual_contained_planner_candidate_and_separate_retention(tmp_path):
    run = make_real(tmp_path)
    assert run.candidate() is None
    outcome = finished(run)
    assert outcome.accepted, (outcome.errors, outcome.retained_stderr)
    assert outcome.exit_code == 0 and outcome.job_active == 0 and outcome.job_total >= 1
    assert outcome.readers_joined and outcome.output_complete and outcome.stderr_bytes == 0
    candidate = run.candidate()
    assert type(candidate) is exchange.UntrustedPlanningCandidate
    observation = json.loads((run.repo / 'observation.json').read_bytes())
    assert observation['pid'] > 0 and observation['root'] == str(run.repo)
    assert observation['limits'] == [32, 4096, 256, 8192, 16 * 1024 * 1024, 30]
    assert {row[0] for row in observation['frames']} == {'plan', '_evaluate'}
    assert all(Path(row[1]) == run.repo / 'scripts/tts/optional_setup_authority.py'
               for row in observation['frames'])
    displayed = bytes(candidate.raw_disclosure)
    retained = wire.decode_disclosure(displayed, planning=run.planning, session=SESSION)
    checked = exchange.read_planning_exchange(run.repo, planning=run.planning,
        expected_disclosure=retained, session=SESSION)
    assert checked.disclosure.raw == displayed
    assert retained.to_json()['planning_request_id'] != retained.to_json()['intended_request_id']
    result = wire.decode_planning_result(candidate.raw_result, expected_disclosure=retained,
        session=SESSION, request_id=run.planning.to_json()['request_id'])
    assert result['verified'] == [] and result['confirmable']
    assert retained.to_json()['document']['terms'] is not None
    assert not (run.repo / 'files/runtime-data/artifacts').exists()
    assert run.wait() is outcome and run.stop() is outcome


def test_worker_entry_without_context_is_disabled():
    from tts import optional_setup_planning_worker_v3 as worker
    assert worker.main(['install', 'repair']) == 2
    assert worker.main([]) == 2


@pytest.mark.parametrize('corrupt', [False, True])
def test_native_planner_hashes_only_disposable_fake_weights(tmp_path, monkeypatch, corrupt):
    from tts import qwen3_runtime as rt
    run = make_real(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(rt, 'repo_root', lambda: run.repo)
        path = rt.models_root() / 'CustomVoice-fixture/model.safetensors'
    path.parent.mkdir(parents=True)
    raw = b'x' * 21 if corrupt else b'synthetic-customvoice'
    path.write_bytes(raw)
    outcome = finished(run)
    assert outcome.accepted, outcome.errors
    doc = json.loads(run.candidate().raw_disclosure)['document']
    assert doc['components'][0]['readiness'] == (proto.DAMAGED if corrupt else proto.MISSING)
    row = doc['terms']['artifacts'][0]
    assert row['verified_reuse_bytes'] == (0 if corrupt else len(raw))
    assert row['expected_new_bytes'] == (len(raw) if corrupt else 0)
    assert path.read_bytes() == raw and not (path.parent / 'ACT-VERIFIED.json').exists()
    assert json.loads(run.candidate().raw_result)['verified'] == []


@pytest.mark.parametrize('extra,code', [
    ('STATE = proto.UNVERIFIED', 0),
    ('def context():\n    return worker.DisposablePlanningContext(PLANNER, lambda: True)', 3),
])
def test_worker_refusal_and_cooperative_cancellation_are_distinct(tmp_path, extra, code):
    run = make_real(tmp_path, extra=extra)
    outcome = finished(run)
    assert outcome.exit_code == code
    if code == 0:
        assert outcome.accepted
        doc = json.loads(run.candidate().raw_disclosure)['document']
        assert doc['terms'] is None and doc['reasons']
        assert json.loads(run.candidate().raw_result)['confirmable'] is False
    else:
        assert not outcome.accepted and not run.result_path.exists() and run.candidate() is None


# Reduced reviewed package mapping is a trusted synthetic adapter ONLY. The
# real Planner, prior-state reader, engine snapshot and wire all remain intact.
INVENTORY_ADAPTER = '''
from tts import qwen3_package_manifest as qm
real = auth.reviewed_packages()
tiny = dataclasses.replace(real.runtime[0], size=7, sha256=hashlib.sha256(b'fixture').hexdigest())
reviewed = dataclasses.replace(real, runtime=(tiny,))
checked_manifest = qm._checked_manifest
qm._checked_manifest = lambda m: reviewed if m is reviewed else checked_manifest(m)
auth.reviewed_packages = lambda: reviewed
STATE = proto.DAMAGED
'''


def test_full_original_history_partials_and_inventory_survive(tmp_path):
    from test_artifact_transfer import operation
    from shared import artifact_transfer as transfer
    from shared import optional_setup_resource_budget as rb
    from tts import qwen3_engine_authority as engine
    from tts import qwen3_runtime as rt
    from shared import artifact_store as store
    run = make_real(tmp_path, extra=INVENTORY_ADAPTER, action='rebuild-canonical')
    parent = run.repo / '.venv'
    parent.mkdir()
    (parent / 'pyvenv.cfg').write_text('home = C:/synthetic-base\ninclude-system-site-packages = false\n')
    canonical = parent / 'engines/qwen3'
    (canonical / 'Lib').mkdir(parents=True)
    (canonical / 'Lib/synthetic.txt').write_bytes(b'synthetic metadata only')
    (canonical / 'pyvenv.cfg').write_text('home = C:/synthetic-base\n')
    depot, ledger, live, _ = operation(run.repo)
    aid = depot.catalog.artifacts[0]['id']
    live._record('reserve', aid, 8)
    live._record('consume', aid, 3)
    live.finish()
    partials = depot.root / 'incomplete'
    partials.mkdir()
    (partials / ('e' * 32 + '.part')).write_bytes(b'abc')
    expected_prior = ledger.prior_state(budget=rb.Budget())
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rt, 'repo_root', lambda: run.repo)
        expected_inventory = engine.snapshot(budget=rb.Budget())
    # No writes to ledger/environment by the worker. Capture exact fixture bytes.
    before = {p.relative_to(run.repo).as_posix(): p.read_bytes()
              for base in (depot.root, parent) for p in base.rglob('*') if p.is_file()}
    outcome = finished(run)
    assert outcome.accepted, outcome.errors
    doc = json.loads(run.candidate().raw_disclosure)['document']
    assert doc['terms'] is not None and doc['reasons'] == [], doc
    assert doc['prior_state'] == expected_prior and doc['engine_identity'] == expected_inventory
    assert doc['prior_state']['history'][0]['state']['actual'][aid] == 3
    assert len(doc['engine_identity']['entries']) == 4
    assert all((run.repo / rel).read_bytes() == value for rel, value in before.items())
    retained = wire.decode_disclosure(run.candidate().raw_disclosure, planning=run.planning, session=SESSION)
    assert retained.document == store.canonical(doc)
    assert exchange.read_planning_exchange(run.repo, planning=run.planning,
        expected_disclosure=retained, session=SESSION).disclosure.document == retained.document


@pytest.mark.parametrize('damage', ['operations', 'invalid-history', 'oversized-plan', 'oversized-envelope'])
def test_real_planner_limits_and_unsafe_complete_output(tmp_path, damage):
    from shared import artifact_store as store
    from test_artifact_transfer import operation
    extra = ''
    if damage.startswith('oversized'):
        # Instrument final canonical producer output, preserving the actual
        # Planner decision and all metadata; never truncate it to fit the wire.
        size = 270000 if damage == 'oversized-plan' else 262000
        extra = f'''
original_encode = resources.Budget.encode
def with_extension(budget, document):
    if isinstance(document, dict) and 'components' in document:
        document['fixture_extension'] = ['x' * 1000] * 255
        remaining = {size} - len(store.canonical(document))
        document['fixture_extension'] += ['y' * 1000] * (remaining // 1003)
        remaining = {size} - len(store.canonical(document)) - 3
        document['fixture_extension'].append('z' * remaining)
    result = original_encode(budget, document)
    (ROOT / 'producer-size.json').write_text(json.dumps(len(result)))
    return result
resources.Budget.encode = with_extension
'''
    run = make_real(tmp_path, extra=extra)
    if damage == 'operations':
        for i in range(33):
            _, _, live, _ = operation(run.repo)
            live.finish()
    elif damage == 'invalid-history':
        depot, ledger, live, _ = operation(run.repo)
        (live.folder / '00000001.json').write_bytes(b'{}')
    outcome = finished(run)
    if damage.startswith('oversized'):
        assert not outcome.accepted and outcome.exit_code == 2
        assert not run.result_path.exists() and run.candidate() is None
        assert not (run.result_path.parent / 'plan.json').exists()
        assert json.loads((run.repo / 'producer-size.json').read_bytes()) == size
    else:
        assert outcome.accepted, outcome.errors
        doc = json.loads(run.candidate().raw_disclosure)['document']
        assert doc['terms'] is None and doc['prior_state'] is None and doc['reasons'], doc
        assert doc['components'][0]['readiness'] == proto.UNVERIFIED
        assert json.loads(run.candidate().raw_result)['confirmable'] is False


@pytest.mark.parametrize('field,value', [('action', 'install'), ('action', 'repair'), ('action', 'confirm'),
    ('action', 'arbitrary'), ('version', 2), ('session', 'f' * 32), ('intended_request_id', 'b' * 32),
    ('plan_id', 'f' * 32), ('components', [proto.QWEN3_BASE]), ('missing', None), ('corrupt', None),
    ('stale', None)])
def test_changed_request_refuses_before_worker_execution(tmp_path, field, value):
    run = make_real(tmp_path)
    path = run.result_path.with_name('request.json')
    doc = run.planning.to_json()
    if field == 'missing':
        path.unlink()
    elif field == 'corrupt':
        path.write_bytes(b'{')
    else:
        doc['issued_utc' if field == 'stale' else field] = (
            proto.utc_text(time.time() - 601) if field == 'stale' else value)
        path.write_bytes(json.dumps(doc).encode())
    outcome = finished(run)
    assert not outcome.accepted and outcome.errors == ('launch-failed',)
    assert not (run.repo / 'observation.json').exists()


@pytest.mark.parametrize('field,value', [('plan_id', 'f' * 32), ('selected', [proto.QWEN3_CUSTOMVOICE]),
    ('planning_request_id', 'f' * 32), ('intended_request_id', P), ('session', 'f' * 32), ('version', 2)])
def test_candidate_binding_is_against_independent_request(tmp_path, field, value):
    request, shown = planning(), disclosure()
    exchange.publish_planning_request(tmp_path, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    raw = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    exchange.publish_planning_response(tmp_path, planning=request, disclosure=shown,
        raw_result=raw, session=SESSION, now=lambda: NOW)
    doc = shown.to_json()
    doc[field] = value
    run_dir = tmp_path / exchange.EXCHANGE_ROOT / P
    (run_dir / 'plan.json').write_bytes(json.dumps(doc, sort_keys=True, separators=(',', ':')).encode())
    with pytest.raises((exchange.ExchangeError, proto.ProtocolError)):
        exchange._read_untrusted_planning_candidate(tmp_path, planning=request, session=SESSION, now=lambda: NOW)


@pytest.mark.parametrize('damage', ['marker', 'plan', 'extra', 'huge', 'result-P', 'duplicate'])
def test_candidate_completion_and_no_overwrite(tmp_path, damage):
    request, shown = planning(), disclosure()
    exchange.publish_planning_request(tmp_path, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    raw = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    exchange.publish_planning_response(tmp_path, planning=request, disclosure=shown,
        raw_result=raw, session=SESSION, now=lambda: NOW)
    folder = tmp_path / exchange.EXCHANGE_ROOT / P
    if damage in ('marker', 'plan'):
        (folder / ('result.json' if damage == 'marker' else 'plan.json')).unlink()
    elif damage == 'extra':
        (folder / 'consent.json').write_bytes(b'{}')
    elif damage == 'huge':
        (folder / 'plan.json').write_bytes(b'x' * (wire.MAX_DISCLOSURE_BYTES + 1))
    elif damage == 'result-P':
        doc = json.loads(raw)
        doc['request_id'] = 'f' * 32
        (folder / 'result.json').write_bytes(json.dumps(doc).encode())
    else:
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        with pytest.raises(exchange.ExchangeError):
            exchange.publish_planning_response(tmp_path, planning=request, disclosure=shown,
                raw_result=raw, session=SESSION, now=lambda: NOW)
        assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
        return
    with pytest.raises((exchange.ExchangeError, proto.ProtocolError)):
        exchange._read_untrusted_planning_candidate(tmp_path, planning=request, session=SESSION, now=lambda: NOW)


def test_forgery_can_be_a_candidate_but_never_the_retained_original(tmp_path):
    run = make_real(tmp_path)
    assert finished(run).accepted
    displayed = bytes(run.candidate().raw_disclosure)
    retained = wire.decode_disclosure(displayed, planning=run.planning, session=SESSION)
    doc = retained.to_json()['document']
    doc['untrusted_extension'] = 'forged after display'
    raw = wire.encode_disclosure(json.dumps(doc, sort_keys=True, separators=(',', ':')).encode(),
        planning=run.planning, issued_utc=proto.utc_text(time.time()))
    forged = wire.decode_disclosure(raw, planning=run.planning, session=SESSION)
    forged_result = wire.encode_planning_result(disclosure=forged, issued_utc=proto.utc_text(time.time()))
    run.result_path.with_name('plan.json').write_bytes(raw)
    run.result_path.write_bytes(forged_result)
    candidate = exchange._read_untrusted_planning_candidate(run.repo, planning=run.planning, session=SESSION)
    assert candidate.raw_disclosure == raw != displayed
    with pytest.raises(exchange.ExchangeError, match='independently retained original'):
        exchange.read_planning_exchange(run.repo, planning=run.planning,
            expected_disclosure=retained, session=SESSION)
    assert retained.raw == displayed and run.candidate().raw_disclosure == displayed


@pytest.mark.parametrize('damage', ['module', 'adapter', 'interpreter', 'extra', 'hardlink'])
def test_changed_code_identity_refuses_before_launch(tmp_path, damage):
    from shared import optional_setup_planning_bridge_v3 as bridge
    run = make_real(tmp_path)
    module = run.repo / 'scripts/tts/optional_setup_planning_worker_v3.py'
    if damage == 'module':
        module.write_bytes(module.read_bytes() + b'\n# replaced\n')
    elif damage == 'adapter':
        (run.repo / 'scripts/_planning_fixture.py').write_bytes(b'raise SystemExit(0)')
    elif damage == 'extra':
        (run.repo / 'scripts/unreviewed.py').write_bytes(b'')
    elif damage == 'interpreter':
        # A forged dataclass cannot replace a controller-issued context.
        run.context = dataclasses.replace(run.context, interpreter=run.repo / 'untrusted-python.exe')
    else:
        import os
        os.link(module, run.repo / 'second-name')
    outcome = finished(run)
    assert not outcome.accepted and outcome.errors == ('launch-failed',)
    assert not (run.repo / 'adapter-started').exists()


def test_fixed_module_and_scrubbed_environment(tmp_path, monkeypatch):
    from shared import optional_setup_planning_bridge_v3 as bridge
    from tts import qwen3_process
    run = make_real(tmp_path)
    spawn = qwen3_process.spawn
    seen = []
    monkeypatch.setenv('PYTHONPATH', str(tmp_path / 'untrusted'))
    monkeypatch.setenv('PYTHONHOME', str(tmp_path / 'untrusted'))
    monkeypatch.setenv('VIRTUAL_ENV', str(tmp_path / 'untrusted'))
    def inspect(argv, **kwargs):
        assert argv == [str(run.context.interpreter), '-I', '-B', '-S', '-c', bridge._BOOTSTRAP,
            run.planning.to_json()['request_id'], SESSION]
        assert kwargs['require_job'] is True and 'shell' not in kwargs
        assert kwargs['cwd'] == str(run.repo / 'scripts')
        assert set(kwargs['env']) == {'SystemRoot', 'TEMP', 'TMP', 'TMPDIR', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'}
        # Native handles stay pinned through execution, not just a path/hash precheck.
        module = run.repo / 'scripts/tts/optional_setup_planning_worker_v3.py'
        with pytest.raises(OSError):
            module.write_bytes(b'replaced')
        with pytest.raises(OSError):
            (run.repo / 'scripts').rename(run.repo / 'moved-scripts')
        seen.append(True)
        return spawn(argv, **kwargs)
    monkeypatch.setattr(qwen3_process, 'spawn', inspect)
    assert finished(run).accepted and seen == [True]


@pytest.mark.parametrize('damage', ['assignment', 'accounting', 'missing-job'])
def test_native_containment_and_accounting_dominate_candidate(tmp_path, monkeypatch, damage):
    from tts import qwen3_process
    run = make_real(tmp_path)
    if damage == 'assignment':
        def fail(*args):
            raise OSError('test assignment unavailable')
        monkeypatch.setattr(qwen3_process.ProcessJob, 'assign', fail)
    elif damage == 'accounting':
        monkeypatch.setattr(qwen3_process.ProcessJob, 'accounting', lambda self: (None, None))
    else:
        account = run._account
        def nojob():
            job = run.process.act_job
            run.process.act_job = None
            try:
                account()
            finally:
                run.process.act_job = job
        monkeypatch.setattr(run, '_account', nojob)
    outcome = finished(run)
    assert not outcome.accepted and run.candidate() is None
    if damage == 'assignment':
        assert outcome.errors == ('launch-failed',) and not (run.repo / 'adapter-started').exists()
    else:
        assert ('missing-job' if damage == 'missing-job' else 'job-accounting-unknown') in outcome.errors
        assert outcome.job_active is None


POST_RESULT = '''
publish = worker.exchange.publish_planning_response
def after_result(*args, **kwargs):
    answer = publish(*args, **kwargs)
    AFTER
    return answer
worker.exchange.publish_planning_response = after_result
'''


@pytest.mark.parametrize('after,code', [
    ('sys.exit(7)', 'exit-result-disagreement'),
    ('os._exit(9)', 'exit-result-disagreement'),
    ("__import__('time').sleep(30)", 'timed-out'),
    ("os.write(2, b'unexpected diagnostic\\n')", 'unexpected-stderr'),
    ("os.write(1, b'unexpected output\\n')", 'invalid-output'),
])
def test_published_result_never_overrides_process_failure(tmp_path, after, code):
    run = make_real(tmp_path, extra=POST_RESULT.replace('AFTER', after), timeout_s=2)
    outcome = finished(run)
    assert not outcome.accepted and code in outcome.errors and run.candidate() is None
    raw = run.result_path.read_bytes()
    assert json.loads(raw)['verified'] == []
    assert outcome.job_active == 0 and not outcome.process_running and outcome.readers_joined
    assert run.wait() is outcome and run.stop() is outcome and run.result_path.read_bytes() == raw


def test_live_native_grandchild_after_planning_is_rejected_and_reaped(tmp_path):
    from test_optional_setup_supervisor_v3 import wait_gone
    extra = '''
ALLOW_TEST_CHILD = True
import subprocess, time
subprocess.Popen([sys.executable, '-I', '-B', '-S', '-c', CHILD_CODE],
    cwd=str(ROOT), env=dict(os.environ), stdin=subprocess.DEVNULL)
deadline = time.monotonic() + 3
while not (ROOT / 'descendant.pid').exists():
    assert time.monotonic() < deadline
    time.sleep(.01)
'''
    run = make_real(tmp_path, extra=extra)
    outcome = finished(run)
    assert not outcome.accepted and 'live-descendant' in outcome.errors
    assert outcome.job_before_cleanup > 0 and outcome.job_active == 0
    assert run.result_path.exists() and run.candidate() is None
    wait_gone(int((run.repo / 'descendant.pid').read_text()))


def test_reentrant_cancel_and_concurrent_terminal_observers(tmp_path):
    run = make_real(tmp_path)
    def callback(event):
        if event['phase'] == 'planning':
            run.cancel()
            run.cancel()
    run._callback = callback
    run.start()
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: run.wait(), range(16)))
    outcome = outcomes[0]
    assert all(other is outcome for other in outcomes)
    assert outcome.state == 'cancelled' and not outcome.accepted and outcome.job_active == 0
    assert outcome.readers_joined and run.candidate() is None


def test_native_candidate_pins_and_changed_opened_identity(tmp_path, monkeypatch):
    run = make_real(tmp_path)
    assert finished(run).accepted
    original = wire.decode_disclosure
    attempts = []
    def during(raw, **kwargs):
        for name in ('request.json', 'plan.json', 'result.json'):
            with pytest.raises(OSError):
                run.result_path.with_name(name).write_bytes(b'changed')
            attempts.append(name)
        return original(raw, **kwargs)
    monkeypatch.setattr(wire, 'decode_disclosure', during)
    candidate = exchange._read_untrusted_planning_candidate(run.repo, planning=run.planning, session=SESSION)
    assert candidate == run.candidate() and set(attempts) == {'request.json', 'plan.json', 'result.json'}
    monkeypatch.setattr(wire, 'decode_disclosure', original)
    identity = exchange._file_identity
    counts = {}
    def changed(stream, path):
        result = identity(stream, path)
        counts[path] = counts.get(path, 0) + 1
        if path.name == 'plan.json' and counts[path] >= 3:
            result = (*result[:3], result[3] + 1, *result[4:])
        return result
    monkeypatch.setattr(exchange, '_file_identity', changed)
    with pytest.raises(exchange.ExchangeError, match='changed'):
        exchange._read_untrusted_planning_candidate(run.repo, planning=run.planning, session=SESSION)


def test_unissued_context_and_production_roots_have_no_launch_authority(tmp_path):
    from shared import optional_setup_planning_bridge_v3 as bridge
    with pytest.raises(exchange.ExchangeError):
        bridge.PlanningRun.for_test(context=None, planning=planning(), session=SESSION)
    forged = bridge.ApprovedDisposableContext(tmp_path / 'forged', (), Path(sys.executable))
    with pytest.raises(exchange.ExchangeError, match='not issued'):
        bridge.PlanningRun.for_test(context=forged, planning=planning(), session=SESSION)
    for root in (bridge._REPO, bridge._REPO / 'files/runtime-data/optional-setup', tmp_path / '..' / 'escape'):
        with pytest.raises(exchange.ExchangeError):
            bridge.ApprovedDisposableContext.for_test(root, adapter_source=FIXTURE_ADAPTER.encode())


@pytest.mark.parametrize('change', ['install', 'repair', 'confirm', 'arbitrary', 'v2', 'schema', 'session', 'P=I'])
def test_worker_itself_rejects_nonplanning_inputs_before_planner(tmp_path, monkeypatch, change):
    from tts import optional_setup_planning_worker_v3 as worker
    from tts import optional_setup_authority as auth
    request = planning()
    exchange.publish_planning_request(tmp_path, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    doc = request.to_json()
    doc['issued_utc'] = proto.utc_text(time.time())
    if change in ('install', 'repair', 'confirm', 'arbitrary'):
        doc['action'] = change
    elif change == 'v2':
        doc['version'] = 2
    elif change == 'schema':
        doc['protocol'] = 'untrusted'
    elif change == 'session':
        doc['session'] = 'f' * 32
    else:
        doc['intended_request_id'] = P
    path = tmp_path / exchange.EXCHANGE_ROOT / P / 'request.json'
    path.write_bytes(json.dumps(doc).encode())
    reached = []
    def bad_plan(*args, **kwargs):
        reached.append(True)
        raise AssertionError('Planner must not run')
    monkeypatch.setattr(auth.Planner, 'plan', bad_plan)
    monkeypatch.setattr(worker, '_fixture_root', lambda: tmp_path)
    assert worker.main([P, SESSION], context=worker.DisposablePlanningContext(auth.Planner())) == 2
    assert reached == [] and not path.with_name('result.json').exists()


def test_cooperative_cancellation_inside_actual_planning(tmp_path):
    extra = '''
checks = 0
def cancelled():
    global checks
    checks += 1
    return checks >= 50
def context():
    return worker.DisposablePlanningContext(PLANNER, cancelled)
'''
    run = make_real(tmp_path, extra=extra)
    outcome = finished(run)
    assert (run.repo / 'observation.json').exists()
    assert outcome.exit_code == 3 and not outcome.accepted and run.candidate() is None
    assert not run.result_path.exists()
    assert json.loads((run.repo / 'diagnostic.json').read_bytes())[0] == 'SetupCancelled'


@pytest.mark.parametrize('extra,code', [('def context():\n    sys.exit(0)', 0),
                                      ('def context():\n    os._exit(9)', 9)])
def test_no_result_or_early_crash_cannot_accept(tmp_path, extra, code):
    run = make_real(tmp_path, extra=extra)
    outcome = finished(run)
    assert not outcome.accepted and outcome.exit_code == code
    assert 'planning-exchange-refused' in outcome.errors and run.candidate() is None


def test_cancel_after_publication_keeps_separate_arbitration_failure(tmp_path):
    run = make_real(tmp_path, extra=POST_RESULT.replace('AFTER', "__import__('time').sleep(30)"))
    run.start()
    deadline = time.monotonic() + 5
    while not run.result_path.exists():
        assert time.monotonic() < deadline
        time.sleep(.01)
    raw = run.result_path.read_bytes()
    run.cancel()
    outcome = run.wait()
    assert outcome.state == 'cancelled' and not outcome.accepted and run.candidate() is None
    assert outcome.job_active == 0 and outcome.readers_joined
    assert run.result_path.read_bytes() == raw


def test_untrusted_host_interpreter_not_issued(tmp_path, monkeypatch):
    from shared import optional_setup_planning_bridge_v3 as bridge
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'untrusted-python.exe'))
    with pytest.raises(exchange.ExchangeError, match='CPython identity'):
        bridge.ApprovedDisposableContext.for_test(tmp_path / 'untrusted-host',
            adapter_source=FIXTURE_ADAPTER.encode())
    assert not (tmp_path / 'untrusted-host').exists()


def test_candidate_cannot_use_worker_request_as_its_original(tmp_path):
    request, shown = planning(), disclosure()
    exchange.publish_planning_request(tmp_path, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    raw = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    exchange.publish_planning_response(tmp_path, planning=request, disclosure=shown,
        raw_result=raw, session=SESSION, now=lambda: NOW)
    p = request.to_json()
    p['intended_request_id'], p['plan_id'] = 'e' * 32, 'f' * 32
    forged_request = wire.decode_planning_request(json.dumps(p).encode(), session=SESSION, request_id=P,
        now=lambda: NOW)
    forged_raw = wire.encode_disclosure(shown.document, planning=forged_request,
        issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    forged = wire.decode_disclosure(forged_raw, planning=forged_request, session=SESSION, now=lambda: NOW)
    folder = tmp_path / exchange.EXCHANGE_ROOT / P
    (folder / 'request.json').write_bytes(forged_request.raw)
    (folder / 'plan.json').write_bytes(forged_raw)
    (folder / 'result.json').write_bytes(wire.encode_planning_result(disclosure=forged,
        issued_utc=proto.utc_text(NOW), now=lambda: NOW))
    with pytest.raises((exchange.ExchangeError, proto.ProtocolError)):
        exchange._read_untrusted_planning_candidate(tmp_path, planning=request, session=SESSION, now=lambda: NOW)


def test_candidate_final_opened_identity_is_rechecked(tmp_path, monkeypatch):
    request, shown = planning(), disclosure()
    exchange.publish_planning_request(tmp_path, request.raw, session=SESSION, request_id=P, now=lambda: NOW)
    raw = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    exchange.publish_planning_response(tmp_path, planning=request, disclosure=shown,
        raw_result=raw, session=SESSION, now=lambda: NOW)
    stable, identity = exchange._stable, exchange._file_identity
    checking = [False]
    def final(*args):
        checking[0] = True
        try:
            return stable(*args)
        finally:
            checking[0] = False
    def changed(stream, path):
        row = identity(stream, path)
        return (*row[:3], row[3] + 1, *row[4:]) if checking[0] else row
    monkeypatch.setattr(exchange, '_stable', final)
    monkeypatch.setattr(exchange, '_file_identity', changed)
    with pytest.raises(exchange.ExchangeError, match='changed'):
        exchange._read_untrusted_planning_candidate(tmp_path, planning=request, session=SESSION, now=lambda: NOW)


COMPLETE_NONZERO = '''
original_main = worker.main
def complete_nonzero(*args, **kwargs):
    code = original_main(*args, **kwargs)
    return 7 if code == 0 else code
worker.main = complete_nonzero
'''


def test_exit_after_complete_result_and_events_still_refuses(tmp_path):
    run = make_real(tmp_path, extra=COMPLETE_NONZERO)
    outcome = finished(run)
    assert not outcome.accepted and outcome.exit_code == 7 and outcome.events == 3
    assert outcome.errors == ('exit-result-disagreement',) and run.result_path.exists()
    assert run.candidate() is None and outcome.job_active == 0 and outcome.readers_joined


def test_native_worker_partial_publication_is_preserved_without_retry(tmp_path):
    extra = '''
write_once = worker.exchange._write_once
def partial(folder, name, raw):
    if name == 'result.json':
        raise OSError('fixed test interruption before completion marker')
    return write_once(folder, name, raw)
worker.exchange._write_once = partial
'''
    run = make_real(tmp_path, extra=extra)
    outcome = finished(run)
    assert not outcome.accepted and outcome.exit_code == 2 and run.candidate() is None
    plan_path = run.result_path.with_name('plan.json')
    raw = plan_path.read_bytes()
    assert not run.result_path.exists()
    shown = wire.decode_disclosure(raw, planning=run.planning, session=SESSION)
    with pytest.raises(exchange.ExchangeError):
        exchange.publish_planning_response(run.repo, planning=run.planning, disclosure=shown,
            raw_result=wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(time.time())),
            session=SESSION)
    assert plan_path.read_bytes() == raw and not run.result_path.exists()


def test_junction_fixture_ancestry_is_refused_before_copy(tmp_path):
    from shared import optional_setup_planning_bridge_v3 as bridge
    from test_optional_tts_setup import _junction
    target = tmp_path / 'target'
    target.mkdir()
    linked = tmp_path / 'linked'
    _junction(linked, target)
    with pytest.raises(exchange.ExchangeError, match='reparse'):
        bridge.ApprovedDisposableContext.for_test(linked / 'run', adapter_source=FIXTURE_ADAPTER.encode())
    assert list(target.iterdir()) == []


def _mutated(owner, name, replacements, monkeypatch):
    """Compile one focused source mutant in memory; never edit frozen files."""
    import ast
    import inspect
    import textwrap
    original = getattr(owner, name)
    function = getattr(original, '__func__', original)
    source = textwrap.dedent(inspect.getsource(function))
    for before, after in replacements:
        assert source.count(before) == 1, (name, before)
        source = source.replace(before, after)
    tree = ast.parse(source)
    tree.body[0].decorator_list = []
    namespace = dict(function.__globals__)
    exec(compile(tree, function.__code__.co_filename, 'exec'), namespace)
    result = namespace[name]
    if getattr(original, '__self__', None) is owner:
        result = classmethod(result)
    monkeypatch.setattr(owner, name, result)


@pytest.mark.parametrize('mutant', ['module-pin', 'interpreter', 'P-I-self-binding',
    'retain-current', 'missing-marker', 'opened-identity', 'assume-empty-job',
    'ignore-exit', 'ignore-stderr', 'production-context', 'worker-action', 'worker-acquisition'])
def test_focused_mutation_controls(tmp_path, monkeypatch, mutant):
    from shared import optional_setup_planning_bridge_v3 as bridge
    from shared import optional_setup_supervisor_v3 as supervisor
    from tts import optional_setup_planning_worker_v3 as worker
    if mutant == 'module-pin':
        _mutated(bridge.PlanningRun, '_spawn_fake', [
            ('hashlib.sha256(raw).digest() == digest', 'True')], monkeypatch)
        control = lambda: test_changed_code_identity_refuses_before_launch(tmp_path, 'module')
    elif mutant == 'interpreter':
        _mutated(bridge.ApprovedDisposableContext, 'for_test', [
            ('Path(sys.executable) == interpreter', 'True')], monkeypatch)
        control = lambda: test_untrusted_host_interpreter_not_issued(tmp_path, monkeypatch)
    elif mutant == 'P-I-self-binding':
        _mutated(exchange, '_read_untrusted_planning_candidate', [
            ('control == planning.raw', 'True'),
            ('candidate = wire.decode_disclosure(plan, planning=planning,',
             'planning = wire.PlanningRequest(control)\n        candidate = wire.decode_disclosure(plan, planning=planning,')], monkeypatch)
        control = lambda: test_candidate_cannot_use_worker_request_as_its_original(tmp_path)
    elif mutant == 'retain-current':
        _mutated(exchange, 'read_planning_exchange', [
            ("_require(control == planning.raw", "expected_disclosure = wire.decode_disclosure(plan, planning=planning, session=session, now=now)\n        _require(control == planning.raw")], monkeypatch)
        control = lambda: test_forgery_can_be_a_candidate_but_never_the_retained_original(tmp_path)
    elif mutant == 'missing-marker':
        # Realistic unsafe shortcut: synthesize a result from Plan when no
        # completion marker exists and accept the resulting two-file set.
        _mutated(exchange, '_read_untrusted_planning_candidate', [
            ("result, a = _read(folder, 'result.json', stack)",
             "plan_only, a = _read(folder, 'plan.json', stack)\n        parsed = wire.decode_disclosure(plan_only, planning=planning, session=session, now=now)\n        result = wire.encode_planning_result(disclosure=parsed, issued_utc=proto.utc_text(now()), now=now)"),
            ('_stable(folder, [a, b, c], _PLANNING_FILES)',
             "_stable(folder, [a, b, c], {'request.json', 'plan.json'})")], monkeypatch)
        control = lambda: test_candidate_completion_and_no_overwrite(tmp_path, 'marker')
    elif mutant == 'opened-identity':
        _mutated(exchange, '_stable', [
            ('_file_identity(stream, path) == before', 'True')], monkeypatch)
        control = lambda: test_candidate_final_opened_identity_is_rechecked(tmp_path, monkeypatch)
    elif mutant == 'assume-empty-job':
        _mutated(supervisor.FakePlanningRun, '_account', [
            ("except Exception:\n        self._active = None\n        self._error('job-accounting-unknown')",
             'except Exception:\n        self._active = 0')], monkeypatch)
        control = lambda: test_native_containment_and_accounting_dominate_candidate(tmp_path, monkeypatch, 'accounting')
    elif mutant == 'ignore-exit':
        _mutated(supervisor.FakePlanningRun, '_supervise', [
            ('if self.process.returncode != 0:', 'if False:')], monkeypatch)
        _mutated(supervisor.FakePlanningRun, '_resolve', [
            ('self.process.returncode == 0', 'True')], monkeypatch)
        control = lambda: test_exit_after_complete_result_and_events_still_refuses(tmp_path)
    elif mutant == 'ignore-stderr':
        _mutated(bridge.PlanningRun, '_read_exchange', [('if self._stderr.count:', 'if False:')], monkeypatch)
        control = lambda: test_published_result_never_overrides_process_failure(tmp_path,
            "os.write(2, b'unexpected diagnostic\\n')", 'unexpected-stderr')
    elif mutant == 'production-context':
        _mutated(worker, 'main', [('return 2\n    args =', 'return 0\n    args =')], monkeypatch)
        control = test_worker_entry_without_context_is_disabled
    elif mutant == 'worker-action':
        _mutated(exchange, '_read_published_planning_request', [
            ('checked = wire.decode_planning_request(control, session=session, request_id=request_id, now=now)',
             'checked = wire.PlanningRequest(control)')], monkeypatch)
        control = lambda: test_worker_itself_rejects_nonplanning_inputs_before_planner(tmp_path, monkeypatch, 'install')
    else:
        # Install the focused mutation in trusted fixture memory so the pinned
        # production source never changes. Its acquisition sentinel must fire.
        extra = '''
import inspect, textwrap
source = textwrap.dedent(inspect.getsource(worker.main))
source = source.replace("plan = context.planner.plan(", "context.planner.acquire_disposable(None)\\n        plan = context.planner.plan(")
exec(compile(source, worker.__file__, 'exec'), worker.__dict__)
'''
        control_run = make_real(tmp_path, extra=extra)
        def control():
            outcome = finished(control_run)
            assert outcome.accepted
    try:
        control()
    except (AssertionError, pytest.fail.Exception):
        print('MUTATION DETECTED', mutant)
    else:
        pytest.fail('Focused safety mutant survived: ' + mutant)
