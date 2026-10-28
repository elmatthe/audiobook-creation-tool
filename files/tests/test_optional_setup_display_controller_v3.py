"""4D-2E: disposable read-only presentation; no claim of human GUI fidelity."""
import dataclasses
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from shared import optional_setup_exchange_v3 as exchange
from shared import optional_setup_planning_bridge_v3 as bridge
from shared import optional_setup_protocol as proto
from shared import optional_setup_wire_v3 as wire
from test_optional_setup_planning_worker_v3 import FIXTURE_ADAPTER, INVENTORY_ADAPTER, finished

pytestmark = pytest.mark.usefixtures('production_writes_refused')


def make_controller(tmp_path, *, extra='', action='none', adapter=None, **run_options):
    from shared import optional_setup_display_controller_v3 as display
    context = bridge.ApprovedDisposableContext.for_test(tmp_path / 'run',
        adapter_source=(FIXTURE_ADAPTER + '\n' + extra).encode())
    session, p, i, plan = (proto.new_token() for _ in range(4))
    raw = wire.encode_planning_request(request_id=p, intended_request_id=i, session=session,
        plan_id=plan, components=[proto.QWEN3_CUSTOMVOICE], engine_action=action,
        issued_utc=proto.utc_text(time.time()))
    original = wire.decode_planning_request(raw, session=session, request_id=p)
    run = bridge.PlanningRun.for_test(context=context, planning=original, session=session, **run_options)
    clock = [time.time()]
    received = []

    def trusted_test_adapter(payload):
        received.append(payload)
        return True

    controller = display.DisposableDisplayController.for_test(run=run, planning=original,
        session=session, display_adapter=adapter or trusted_test_adapter, now=lambda: clock[0])
    return controller, run, clock, received


def pending(controller, run):
    assert finished(run).accepted
    controller.admit_candidate()
    return controller.prepare_presentation()


def retained(controller, run):
    payload = pending(controller, run)
    controller.acknowledge_display(payload)
    return payload, controller.retain_original()


def test_separate_display_and_exact_frozen_retention(tmp_path):
    from shared import optional_setup_display_controller_v3 as display
    c, run, clock, received = make_controller(tmp_path)
    assert c.state == 'request-issued' and run.candidate() is None
    with pytest.raises(display.ControllerError, match='candidate-not-ready'):
        c.admit_candidate()
    assert c.state == 'request-issued'
    payload = pending(c, run)
    assert c.state == 'presentation-pending' and received == []
    assert c._retained is None
    assert payload.raw_disclosure == run.candidate().raw_disclosure
    assert payload.document == wire._canonical(payload.to_json()['document'], wire.MAX_DISCLOSURE_BYTES)
    assert payload.to_json() == json.loads(payload.raw_disclosure)
    payload.to_json()['document']['reasons'].append('detached copy')
    assert payload.to_json()['document']['reasons'] == []
    with pytest.raises(dataclasses.FrozenInstanceError):
        payload.document = b'changed'
    c.acknowledge_display(payload)
    assert c.state == 'display-acknowledged' and received == [payload]
    assert c._retained is None
    original = c.retain_original()
    assert c.state == 'original-retained'
    assert original.disclosure.raw == payload.raw_disclosure
    assert original.disclosure.document == payload.document
    assert original.planning.raw == run.planning.raw
    with pytest.raises(dataclasses.FrozenInstanceError):
        original.raw_result = b'changed'
    for _ in range(3):
        assert c.retain_original() is original
        checked = c.readback()
        assert checked.disclosure == original.disclosure
        assert json.loads(checked.raw_result)['verified'] == []
    assert run.wait().job_active == 0 and run.wait().readers_joined
    assert not hasattr(original, 'consent') and not hasattr(original, 'confirmation')


def test_retention_before_display_invalidates(tmp_path):
    from shared import optional_setup_display_controller_v3 as display
    c, run, _, received = make_controller(tmp_path)
    pending(c, run)
    with pytest.raises(display.ControllerError, match='display-required'):
        c.retain_original()
    assert c.state == 'invalidated' and received == []
    with pytest.raises(display.ControllerError):
        c.readback()


EXTENSION_ADAPTER = '''
original_encode = resources.Budget.encode
def with_extension(budget, document):
    if isinstance(document, dict) and 'components' in document:
        document['future_metadata'] = {'all': [None, True, 3.25, {'text': 'synthetic detail'}]}
    return original_encode(budget, document)
resources.Budget.encode = with_extension
'''


def test_complete_history_partials_inventory_and_unknown_metadata(tmp_path):
    from shared import artifact_store as store
    from shared import optional_setup_resource_budget as rb
    from test_artifact_transfer import operation
    from tts import qwen3_engine_authority as engine, qwen3_runtime as rt
    c, run, _, received = make_controller(tmp_path,
        extra=INVENTORY_ADAPTER + EXTENSION_ADAPTER, action='rebuild-canonical')
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
    prior = ledger.prior_state(budget=rb.Budget())
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rt, 'repo_root', lambda: run.repo)
        inventory = engine.snapshot(budget=rb.Budget())
    payload, original = retained(c, run)
    doc = payload.to_json()['document']
    assert doc['prior_state'] == prior
    assert doc['engine_identity'] == inventory and len(inventory['entries']) == 4
    history = doc['prior_state']['history'][0]
    assert history['state']['actual'][aid] == 3 and history['state']['reserved'][aid] == 5
    assert history['sequence'] > 0 and len(history['chain']) == 64
    assert doc['prior_state']['partials'][0]['size'] == 3
    assert doc['future_metadata'] == {'all': [None, True, 3.25, {'text': 'synthetic detail'}]}
    assert doc['terms'] is not None and doc['reasons'] == []
    assert original.disclosure.document == store.canonical(doc) == payload.document
    assert json.loads(payload.document)['prior_state'] == prior
    assert received == [payload] and c.readback().disclosure == original.disclosure


def test_blocked_plan_remains_nonconfirmable_read_only(tmp_path):
    c, run, _, _ = make_controller(tmp_path, extra='STATE = proto.UNVERIFIED\n')
    payload, original = retained(c, run)
    doc = payload.to_json()['document']
    assert doc['terms'] is None and doc['reasons']
    assert doc['components'][0]['readiness'] == proto.UNVERIFIED
    result = json.loads(c.readback().raw_result)
    assert result['confirmable'] is False and result['verified'] == []
    assert original.disclosure.document == payload.document


@pytest.mark.parametrize('stage', ['admit', 'prepare', 'ack', 'retain', 'observe', 'readback'])
@pytest.mark.parametrize('age', [601, -61])
def test_freshness_at_every_sensitive_transition(tmp_path, stage, age):
    from shared import optional_setup_display_controller_v3 as display
    c, run, clock, received = make_controller(tmp_path)
    assert finished(run).accepted
    if stage != 'admit':
        c.admit_candidate()
    if stage not in ('admit', 'prepare'):
        payload = c.prepare_presentation()
    if stage in ('retain', 'observe', 'readback'):
        c.acknowledge_display(payload)
    if stage in ('observe', 'readback'):
        c.retain_original()
    # Request remains the independent issue time; no timestamp repair/re-encode.
    issued = run.planning.to_json()['issued_utc']
    import calendar
    clock[0] = calendar.timegm(time.strptime(issued, '%Y-%m-%dT%H:%M:%SZ')) + age
    action = {'admit': c.admit_candidate, 'prepare': c.prepare_presentation,
        'ack': lambda: c.acknowledge_display(payload), 'retain': c.retain_original,
        'observe': c.retain_original, 'readback': c.readback}[stage]
    with pytest.raises(display.ControllerError, match='presentation-expired'):
        action()
    assert c.state == 'invalidated' and c._retained is None


@pytest.mark.parametrize('source', ['disclosure', 'result'])
def test_candidate_timestamp_expiry_independent_of_request(tmp_path, source, monkeypatch):
    from shared import optional_setup_display_controller_v3 as display
    c, run, clock, _ = make_controller(tmp_path)
    assert finished(run).accepted
    candidate = run.candidate()
    envelope, result = json.loads(candidate.raw_disclosure), json.loads(candidate.raw_result)
    if source == 'disclosure':
        envelope['issued_utc'] = proto.utc_text(clock[0] - 700)
    else:
        result['issued_utc'] = proto.utc_text(clock[0] - 700)
    raw = wire._canonical(envelope, wire.MAX_DISCLOSURE_BYTES)
    result['plan_sha256'] = hashlib.sha256(raw).hexdigest()
    answer = wire._canonical(result, wire.MAX_CONTROL_BYTES)
    monkeypatch.setattr(run, '_candidate', exchange.UntrustedPlanningCandidate(raw, answer))
    # Isolate controller freshness even with a synthetic matching arbitration ref.
    monkeypatch.setattr(run, '_outcome', dataclasses.replace(run.result(), raw_result=answer))
    with pytest.raises(display.ControllerError, match='presentation-expired'):
        c.admit_candidate()
    assert c.state == 'invalidated'


@pytest.mark.parametrize('failure', ['false', 'exception', 'interrupt', 'reentrant', 'expired'])
def test_display_adapter_failures_are_sticky(tmp_path, failure):
    from shared import optional_setup_display_controller_v3 as display
    c, run, clock, _ = make_controller(tmp_path)
    payload = pending(c, run)

    def adapter(shown):
        assert shown is payload
        if failure == 'false':
            return False
        if failure == 'exception':
            raise RuntimeError('UNTRUSTED worker-like text must not escape')
        if failure == 'interrupt':
            raise KeyboardInterrupt('caller interrupted handoff')
        if failure == 'reentrant':
            c.invalidate('presentation-interrupted')
        if failure == 'expired':
            clock[0] += 700
        return True

    c._adapter = adapter  # trusted TEST code, never data-selected
    code = {'reentrant': 'presentation-interrupted', 'expired': 'presentation-expired'}.get(failure, 'display-failed')
    with pytest.raises(display.ControllerError, match=code) as caught:
        c.acknowledge_display(payload)
    assert str(caught.value) == code and c.error_code == code
    assert c.state == 'invalidated' and c._retained is None
    with pytest.raises(display.ControllerError, match=code):
        c.retain_original()


@pytest.mark.parametrize('stage', ['pending', 'acknowledged', 'retained'])
def test_explicit_cancellation_and_late_result_cannot_revive(tmp_path, stage):
    from shared import optional_setup_display_controller_v3 as display
    c, run, _, _ = make_controller(tmp_path)
    payload = pending(c, run)
    if stage != 'pending':
        c.acknowledge_display(payload)
    if stage == 'retained':
        c.retain_original()
    c.cancel()
    for action in (c.admit_candidate, c.prepare_presentation,
                   lambda: c.acknowledge_display(payload), c.retain_original, c.readback):
        with pytest.raises(display.ControllerError, match='cancelled'):
            action()
    assert c.state == 'invalidated' and c._retained is None


@pytest.mark.parametrize('replacement', ['candidate', 'payload', 'duplicate-candidate', 'duplicate-ack'])
def test_replacement_and_duplicate_delivery_invalidate(tmp_path, replacement, monkeypatch):
    from shared import optional_setup_display_controller_v3 as display
    c, run, _, _ = make_controller(tmp_path)
    payload = pending(c, run)
    if replacement == 'candidate':
        monkeypatch.setattr(run, '_candidate', dataclasses.replace(run.candidate()))
        action = lambda: c.acknowledge_display(payload)
        code = 'candidate-replaced'
    elif replacement == 'payload':
        action = lambda: c.acknowledge_display(dataclasses.replace(payload))
        code = 'display-payload-changed'
    elif replacement == 'duplicate-candidate':
        action, code = c.admit_candidate, 'duplicate-candidate'
    else:
        c.acknowledge_display(payload)
        c.retain_original()
        action, code = lambda: c.acknowledge_display(payload), 'duplicate-acknowledgment'
    with pytest.raises(display.ControllerError, match=code):
        action()
    assert c.state == 'invalidated' and c._retained is None


@pytest.mark.parametrize('field', ['session', 'request_id', 'intended_request_id', 'plan_id', 'components', 'engine_action'])
def test_changed_trusted_request_binding_cannot_promote(tmp_path, field, monkeypatch):
    from shared import optional_setup_display_controller_v3 as display
    c, run, _, _ = make_controller(tmp_path)
    payload = pending(c, run)
    if field == 'session':
        monkeypatch.setattr(run, 'session', proto.new_token())
    else:
        p = run.planning.to_json()
        p[field] = [proto.QWEN3_BASE] if field == 'components' else (
            'rebuild-canonical' if field == 'engine_action' else proto.new_token())
        monkeypatch.setattr(run, 'planning', wire.PlanningRequest(wire._canonical(p, wire.MAX_CONTROL_BYTES)))
    with pytest.raises(display.ControllerError, match='request-changed'):
        c.acknowledge_display(payload)
    assert c.state == 'invalidated'


@pytest.mark.parametrize('field', ['session', 'planning_request_id', 'intended_request_id', 'plan_id',
    'selected', 'engine_action', 'corrupt-document', 'unknown-readiness', 'forged-consistent'])
def test_forged_candidate_rejected_against_arbitrated_result(tmp_path, field, monkeypatch):
    from shared import optional_setup_display_controller_v3 as display
    c, run, _, _ = make_controller(tmp_path)
    assert finished(run).accepted
    candidate = run.candidate()
    d = json.loads(candidate.raw_disclosure)
    if field == 'corrupt-document':
        d['document'] = {}
    elif field == 'unknown-readiness':
        d['document']['components'][0]['readiness'] = 'imagined'
    elif field == 'forged-consistent':
        d['document']['future_extra'] = 'forged Plan and matching result'
    else:
        d[field] = [proto.QWEN3_BASE] if field == 'selected' else (
            'rebuild-canonical' if field == 'engine_action' else proto.new_token())
    raw = wire._canonical(d, wire.MAX_DISCLOSURE_BYTES)
    answer = json.loads(candidate.raw_result)
    if field == 'forged-consistent':
        answer['plan_sha256'] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(run, '_candidate', exchange.UntrustedPlanningCandidate(raw,
        wire._canonical(answer, wire.MAX_CONTROL_BYTES)))
    with pytest.raises(display.ControllerError, match='candidate-invalid'):
        c.admit_candidate()
    assert c.state == 'invalidated'


@pytest.mark.parametrize('damage', ['forged-pair', 'missing-result', 'partial-result', 'old-plan-new-request'])
def test_strict_original_readback_rejects_replacement_without_repair(tmp_path, damage):
    from shared import optional_setup_display_controller_v3 as display
    c, run, clock, _ = make_controller(tmp_path)
    payload, original = retained(c, run)
    folder = run.result_path.parent
    if damage == 'forged-pair':
        d = json.loads(payload.raw_disclosure)
        d['document']['replacement_metadata'] = {'public_digest_is_not_original': True}
        raw = wire._canonical(d, wire.MAX_DISCLOSURE_BYTES)
        forged = wire.decode_disclosure(raw, planning=original.planning, session=run.session, now=lambda: clock[0])
        result = wire.encode_planning_result(disclosure=forged, issued_utc=proto.utc_text(clock[0]), now=lambda: clock[0])
        (folder / 'plan.json').write_bytes(raw)
        run.result_path.write_bytes(result)
        # Independently demonstrate internal consistency; still not our original.
        candidate = exchange._read_untrusted_planning_candidate(run.repo, planning=original.planning,
            session=run.session, now=lambda: clock[0])
        assert candidate.raw_disclosure != original.disclosure.raw
    elif damage == 'missing-result':
        run.result_path.unlink()
    elif damage == 'partial-result':
        run.result_path.write_bytes(b'{')
    else:
        p = original.planning.to_json()
        p['request_id'] = p['planning_request_id'] = proto.new_token()
        (folder / 'request.json').write_bytes(wire._canonical(p, wire.MAX_CONTROL_BYTES))
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(display.ControllerError, match='original-changed'):
        c.readback()
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    assert original.disclosure.raw == payload.raw_disclosure
    assert c.state == 'invalidated' and c._retained is None


@pytest.mark.parametrize('extra,cancelled', [(
    "worker.main = lambda *a, **k: 0", False), (
    "worker.main = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('worker text'))", False), ('', True)])
def test_failed_supervisor_never_grants_candidate_authority(tmp_path, extra, cancelled):
    from shared import optional_setup_display_controller_v3 as display
    # Cancellation before start proves no production or late launch path.
    c, run, _, _ = make_controller(tmp_path, extra='' if cancelled else extra)
    if cancelled:
        run.cancel()
    outcome = finished(run)
    assert not outcome.accepted
    with pytest.raises(display.ControllerError, match='worker-cancelled' if cancelled else 'worker-failed'):
        c.admit_candidate()
    assert c.state == 'invalidated'


def test_complete_files_do_not_override_failed_arbitration(tmp_path):
    from shared import optional_setup_display_controller_v3 as display
    extra = '''
original_main = worker.main
def nonzero(*args, **kwargs):
    assert original_main(*args, **kwargs) == 0
    return 9
worker.main = nonzero
'''
    c, run, _, _ = make_controller(tmp_path, extra=extra)
    outcome = finished(run)
    assert not outcome.accepted and run.result_path.exists() and outcome.exit_code == 9
    assert (run.result_path.parent / 'plan.json').exists()
    with pytest.raises(display.ControllerError, match='worker-failed'):
        c.admit_candidate()


@pytest.mark.parametrize('operation', ['duplicate-ack', 'cancel', 'invalidate'])
def test_invalidation_during_display_handoff_has_no_deadlock(tmp_path, operation):
    from shared import optional_setup_display_controller_v3 as display
    entered, release = threading.Event(), threading.Event()

    def adapter(payload):
        entered.set()
        assert release.wait(5)
        return True

    c, run, _, _ = make_controller(tmp_path, adapter=adapter)
    payload = pending(c, run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(c.acknowledge_display, payload)
        assert entered.wait(5)
        if operation == 'duplicate-ack':
            second = pool.submit(c.acknowledge_display, payload)
            with pytest.raises(display.ControllerError, match='duplicate-acknowledgment'):
                second.result(timeout=5)
        elif operation == 'cancel':
            pool.submit(c.cancel).result(timeout=5)
        else:
            pool.submit(c.invalidate, 'presentation-interrupted').result(timeout=5)
        release.set()
        with pytest.raises(display.ControllerError):
            first.result(timeout=5)
    assert c.state == 'invalidated' and c._retained is None


def test_concurrent_readback_and_invalidation_returns_no_verified_handle(tmp_path, monkeypatch):
    from shared import optional_setup_display_controller_v3 as display
    c, run, _, _ = make_controller(tmp_path)
    retained(c, run)
    entered, release = threading.Event(), threading.Event()
    strict = exchange.read_planning_exchange

    def delayed(*args, **kwargs):
        result = strict(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(exchange, 'read_planning_exchange', delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(c.readback)
        assert entered.wait(5)
        pool.submit(c.cancel).result(timeout=5)
        release.set()
        with pytest.raises(display.ControllerError, match='cancelled'):
            reading.result(timeout=5)
    assert c._retained is None


def test_concurrent_retain_is_one_immutable_original(tmp_path):
    c, run, _, _ = make_controller(tmp_path)
    payload = pending(c, run)
    c.acknowledge_display(payload)
    with ThreadPoolExecutor(max_workers=8) as pool:
        handles = list(pool.map(lambda _: c.retain_original(), range(16)))
    assert all(handle is handles[0] for handle in handles)
    assert c.state == 'original-retained'


def test_expiry_immediately_before_retention_and_explicit_timeout(tmp_path):
    from shared import optional_setup_display_controller_v3 as display
    c, run, clock, _ = make_controller(tmp_path)
    payload = pending(c, run)
    c.acknowledge_display(payload)
    clock[0] += 700
    with pytest.raises(display.ControllerError, match='presentation-expired'):
        c.retain_original()
    c.invalidate('retention-timeout')
    assert c.error_code == 'presentation-expired'  # first error remains sticky


def test_superseding_attempt_and_reused_ids_cannot_revive(tmp_path):
    from shared import optional_setup_display_controller_v3 as display
    c, run, _, _ = make_controller(tmp_path)
    payload = pending(c, run)
    c.acknowledge_display(payload)
    original = run.planning.to_json()
    for p, i in ((original['request_id'], proto.new_token()), (proto.new_token(), original['intended_request_id'])):
        raw = wire.encode_planning_request(request_id=p, intended_request_id=i, session=run.session,
            plan_id=proto.new_token(), components=original['components'], engine_action='none',
            issued_utc=proto.utc_text(time.time()))
        request = wire.PlanningRequest(raw)
        context = bridge.ApprovedDisposableContext.for_test(tmp_path / p, adapter_source=FIXTURE_ADAPTER.encode())
        other = bridge.PlanningRun.for_test(context=context, planning=request, session=run.session)
        with pytest.raises(display.ControllerError, match='request-id-reused'):
            display.DisposableDisplayController.for_test(run=other, planning=request, session=run.session,
                display_adapter=lambda _: True)
        assert not (other.repo / 'adapter-started').exists()
    # A fresh independent request in this session explicitly supersedes c.
    p, i = proto.new_token(), proto.new_token()
    request = wire.PlanningRequest(wire.encode_planning_request(request_id=p, intended_request_id=i,
        session=run.session, plan_id=proto.new_token(), components=original['components'], engine_action='none',
        issued_utc=proto.utc_text(time.time())))
    context = bridge.ApprovedDisposableContext.for_test(tmp_path / 'superseding', adapter_source=FIXTURE_ADAPTER.encode())
    other = bridge.PlanningRun.for_test(context=context, planning=request, session=run.session)
    newer = display.DisposableDisplayController.for_test(run=other, planning=request, session=run.session,
        display_adapter=lambda _: True)
    assert newer.state == 'request-issued' and c.error_code == 'superseded'
    with pytest.raises(display.ControllerError, match='superseded'):
        c.retain_original()
    assert not (other.repo / 'adapter-started').exists()


def test_presentation_never_issues_consent_and_has_no_execution_or_launch_api(tmp_path, monkeypatch):
    import ast
    from pathlib import Path
    from shared import optional_setup_display_controller_v3 as display, optional_setup_v3 as v3
    from tts import optional_setup_authority as auth

    def denied(*args, **kwargs):
        raise AssertionError('authority or launch boundary crossed')

    for module, name in ((wire, 'encode_confirmation_request'), (exchange, 'prepare_confirmation'),
        (v3, 'new_consent'), (v3, 'validate_and_spend'), (proto, 'claim_consent'),
        (auth.Planner, 'acquire_disposable')):
        monkeypatch.setattr(module, name, denied)
    c, run, _, _ = make_controller(tmp_path)
    retained(c, run)
    assert json.loads(c.readback().raw_result)['verified'] == []
    assert c.confirmation is None and c.confirmation_eligible()
    assert callable(c.confirm)  # M2 requires a separate trusted final action.
    assert all(not hasattr(c, name) for name in ('start', 'install', 'repair', 'acquire', 'prepare_confirmation'))
    source = Path(display.__file__).read_text()
    tree = ast.parse(source)
    assert all(not isinstance(n, (ast.Import, ast.ImportFrom)) or not any(
        a.name.split('.')[0] in ('subprocess', 'tkinter', 'socket', 'sqlite3') for a in n.names) for n in ast.walk(tree))
    assert 'PlanningRun.for_test(' not in source and '.start(' not in source
    assert list(run.result_path.parent.iterdir()) and not (run.result_path.parent / 'consent.json').exists()
    assert not (run.repo / exchange.EXCHANGE_ROOT / run.planning.to_json()['intended_request_id']).exists()


def test_only_issued_disposable_run_factory_is_available(tmp_path):
    from shared import optional_setup_display_controller_v3 as display
    from tts import optional_setup_planning_worker_v3 as worker
    with pytest.raises(display.ControllerError, match='disposable-factory-required'):
        display.DisposableDisplayController(None)
    with pytest.raises(display.ControllerError, match='disposable-run-required'):
        display.DisposableDisplayController.for_test(run=object(), planning=object(), session='x',
            display_adapter=lambda _: True)
    c, run, _, _ = make_controller(tmp_path)
    original_context = run.context
    run.context = dataclasses.replace(original_context)
    with pytest.raises(display.ControllerError, match='disposable-run-required'):
        display.DisposableDisplayController.for_test(run=run, planning=run.planning, session=run.session,
            display_adapter=lambda _: True)
    assert not (run.repo / 'adapter-started').exists()
    assert worker.main([]) == 2 and worker.main(['install']) == 2


@pytest.mark.parametrize('field', ['raw', 'document'])
def test_changed_retained_original_is_not_returned_again(tmp_path, field):
    from shared import optional_setup_display_controller_v3 as display
    c, run, _, _ = make_controller(tmp_path)
    _, original = retained(c, run)
    changed = dataclasses.replace(original.disclosure,
        **{field: getattr(original.disclosure, field) + b' '})
    c._retained = dataclasses.replace(original, disclosure=changed)
    with pytest.raises(display.ControllerError, match='original-changed'):
        c.retain_original()
    assert c.state == 'invalidated' and c._retained is None


@pytest.mark.parametrize('reason', ['presentation-interrupted', 'retention-timeout'])
def test_late_success_after_invalidation_cannot_revive(tmp_path, reason):
    from shared import optional_setup_display_controller_v3 as display
    c, run, _, _ = make_controller(tmp_path)
    c.invalidate(reason)
    assert finished(run).accepted  # late real bytes have no controller authority
    with pytest.raises(display.ControllerError, match=reason):
        c.admit_candidate()
    assert c.state == 'invalidated'


def test_stale_issued_request_refused_at_factory(tmp_path, monkeypatch):
    from shared import optional_setup_display_controller_v3 as display
    c, run, clock, _ = make_controller(tmp_path)
    with pytest.raises(display.ControllerError, match='presentation-expired'):
        display.DisposableDisplayController.for_test(run=run, planning=run.planning, session=run.session,
            display_adapter=lambda _: True, now=lambda: clock[0] + 700)
    assert not (run.repo / 'adapter-started').exists()


def test_reentrant_clock_can_invalidate_without_deadlock(tmp_path):
    from shared import optional_setup_display_controller_v3 as display
    c, run, clock, _ = make_controller(tmp_path)
    payload = pending(c, run)
    c.acknowledge_display(payload)

    def clock_and_cancel():
        c.cancel()
        return clock[0]

    c._clock = clock_and_cancel
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(display.ControllerError, match='cancelled'):
            pool.submit(c.retain_original).result(timeout=5)


def test_retention_uses_presented_bytes_even_if_files_change_before_retention(tmp_path):
    from shared import optional_setup_display_controller_v3 as display
    c, run, clock, _ = make_controller(tmp_path)
    payload = pending(c, run)
    c.acknowledge_display(payload)
    d = payload.to_json()
    d['document']['later_file_metadata'] = 'replacement after display'
    raw = wire._canonical(d, wire.MAX_DISCLOSURE_BYTES)
    forged = wire.decode_disclosure(raw, planning=run.planning, session=run.session, now=lambda: clock[0])
    answer = wire.encode_planning_result(disclosure=forged, issued_utc=proto.utc_text(clock[0]), now=lambda: clock[0])
    (run.result_path.parent / 'plan.json').write_bytes(raw)
    run.result_path.write_bytes(answer)
    original = c.retain_original()
    assert original.disclosure.raw == payload.raw_disclosure != raw
    assert original.disclosure.document == payload.document
    with pytest.raises(display.ControllerError, match='original-changed'):
        c.readback()


@pytest.mark.parametrize('mutant', ['auto-retain', 'display-bypass', 'raw-retention', 'freshness',
    'request-P', 'request-I', 'session', 'retain-current', 'forged-readback', 'complete-history', 'read-only', 'invalidation'])
def test_independent_mutation_controls(tmp_path, monkeypatch, mutant):
    from shared import optional_setup_display_controller_v3 as display
    from test_optional_setup_planning_worker_v3 import _mutated
    owner = display.DisposableDisplayController
    if mutant == 'auto-retain':
        _mutated(owner, 'prepare_presentation', [("self._state = 'presentation-pending'",
            "self._retained = RetainedOriginal(self._planning, shown, self._candidate.raw_result)\n"
            "        self._state = 'presentation-pending'")], monkeypatch)
        control = lambda: test_separate_display_and_exact_frozen_retention(tmp_path)
    elif mutant == 'display-bypass':
        _mutated(owner, 'acknowledge_display', [('self._adapter(payload)', 'True')], monkeypatch)
        control = lambda: test_display_adapter_failures_are_sticky(tmp_path, 'false')
    elif mutant == 'raw-retention':
        _mutated(owner, 'retain_original', [('RetainedOriginal(self._planning, shown, self._candidate.raw_result)',
            "RetainedOriginal(self._planning, wire.Disclosure(shown.raw + b' ', shown.document), self._candidate.raw_result)")], monkeypatch)
        control = lambda: test_separate_display_and_exact_frozen_retention(tmp_path)
    elif mutant == 'freshness':
        _mutated(owner, '_validate', [('stamp, outcome, candidate = sample',
            "stamp, outcome, candidate = sample\n    stamp = __import__('calendar').timegm(time.strptime("
            "self._planning.to_json()['issued_utc'], '%Y-%m-%dT%H:%M:%SZ'))")], monkeypatch)
        control = lambda: test_freshness_at_every_sensitive_transition(tmp_path, 'observe', 601)
    elif mutant in ('request-P', 'request-I', 'session'):
        if mutant == 'session':
            before, field = 'run.session != self._session', 'session'
        else:
            before = 'run.planning.raw != self._planning.raw'
            field = 'request_id' if mutant == 'request-P' else 'intended_request_id'
        _mutated(owner, '_validate', [(before, 'False')], monkeypatch)
        control = lambda: test_changed_trusted_request_binding_cannot_promote(tmp_path, field, monkeypatch)
    elif mutant == 'retain-current':
        _mutated(owner, 'retain_original', [('wire.decode_disclosure(self._payload.raw_disclosure,',
            'wire.decode_disclosure(exchange._read_untrusted_planning_candidate(self._repo, '
            'planning=self._planning, session=self._session, now=self._clock).raw_disclosure,')], monkeypatch)
        control = lambda: test_retention_uses_presented_bytes_even_if_files_change_before_retention(tmp_path)
    elif mutant == 'forged-readback':
        _mutated(owner, 'readback', [('expected_disclosure=original.disclosure',
            'expected_disclosure=wire.decode_disclosure(exchange._read_untrusted_planning_candidate('
            'self._repo, planning=self._planning, session=self._session, now=self._clock).raw_disclosure, '
            'planning=self._planning, session=self._session, now=self._clock)'),
            ('checked.raw_result != original.raw_result', 'False')], monkeypatch)
        control = lambda: test_strict_original_readback_rejects_replacement_without_repair(tmp_path, 'forged-pair')
    elif mutant == 'complete-history':
        _mutated(owner, 'prepare_presentation', [('Presentation(shown.raw, shown.document)',
            "Presentation(shown.raw, wire._canonical({k: v for k, v in shown.to_json()['document'].items() "
            "if k != 'prior_state'}, wire.MAX_DISCLOSURE_BYTES))")], monkeypatch)
        control = lambda: test_complete_history_partials_inventory_and_unknown_metadata(tmp_path)
    elif mutant == 'read-only':
        _mutated(owner, 'retain_original', [('self._retained = RetainedOriginal(',
            'wire.encode_confirmation_request()\n        self._retained = RetainedOriginal(')], monkeypatch)
        control = lambda: test_presentation_never_issues_consent_and_has_no_execution_or_launch_api(tmp_path, monkeypatch)
    else:
        _mutated(owner, 'invalidate', [("self._state, self._error = 'invalidated', reason",
            'self._state, self._error = self._state, self._error')], monkeypatch)
        control = lambda: test_explicit_cancellation_and_late_result_cannot_revive(tmp_path, 'pending')
    try:
        control()
    except (AssertionError, display.ControllerError, pytest.fail.Exception) as caught:
        print('MUTATION CAUGHT', mutant, type(caught).__name__)
    else:
        pytest.fail('mutation survived: ' + mutant)
