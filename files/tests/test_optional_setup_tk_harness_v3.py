"""Controlled real Windows Tk delivery and qualification-only final action."""
import json
import dataclasses
import threading
import time

import pytest

from shared import optional_setup_protocol as proto
from shared import optional_setup_readonly_context_v3 as context

pytestmark = pytest.mark.usefixtures('production_writes_refused')


def synthetic_run(tmp_path, *, extra='', action='none'):
    from shared import optional_setup_planning_bridge_v3 as bridge, optional_setup_wire_v3 as wire
    from test_optional_setup_planning_worker_v3 import FIXTURE_ADAPTER
    issued = bridge.ApprovedDisposableContext.for_test(tmp_path / 'run',
        adapter_source=(FIXTURE_ADAPTER + '\n' + extra).encode())
    session = proto.new_token()
    raw = wire.encode_planning_request(request_id=proto.new_token(), intended_request_id=proto.new_token(),
        session=session, plan_id=proto.new_token(), components=[proto.QWEN3_CUSTOMVOICE],
        engine_action=action, issued_utc=proto.utc_text(time.time()))
    planning = wire.decode_planning_request(raw, session=session, request_id=json.loads(raw)['request_id'])
    return bridge.PlanningRun.for_test(context=issued, planning=planning, session=session, timeout_s=30)


def pump(view, *, terminal='original-retained'):
    from shared import optional_setup_display_controller_v3 as display
    deadline = time.monotonic() + 40
    while view.lifecycle.state not in (terminal, 'invalidated', *display._FINAL) and time.monotonic() < deadline:
        view.root.update()
        time.sleep(.01)
    assert view.lifecycle.state == terminal, view.lifecycle.error_code


def test_real_tk_delivery_retains_original_and_strict_readback(tmp_path):
    from shared.optional_setup_tk_harness_v3 import TkPlanningHarness

    with context.issue_controlled_context(tmp_path / 'tk') as issued:
        run = context.ReadOnlyPlanningRun.create(issued, components=[proto.QWEN3_CUSTOMVOICE],
                                                engine_action='install-missing', timeout_s=30)
        view = TkPlanningHarness(run)
        try:
            view.start()
            assert view.lifecycle.state == 'request-issued'
            assert view.ack_thread is None
            pump(view)
            original = view.lifecycle.retain_original()
            assert view.ack_thread == threading.get_ident()
            assert view.ack_exposed and view.ack_mapped
            assert json.loads(view.details.get('1.0', 'end-1c')) == json.loads(original.disclosure.raw)
            assert view.details.get('1.0', 'end-1c').encode('utf-8') == original.disclosure.raw
            assert original.disclosure.raw == run.candidate().raw_disclosure
            assert view.lifecycle.readback().raw_result == original.raw_result
            assert view.details.cget('state') == 'disabled'
            assert view.buttons['install'].instate(['disabled'])
            assert view.lifecycle.confirmation is None
            view._install()  # Even a direct event cannot authorize this refusal.
            assert view.lifecycle.confirmation is None
            document = json.loads(original.disclosure.document)
            assert document['terms'] is None and document['prior_state'] is None
            assert document['reasons'] == ['BLOCKED: portable sox supply pending; existing local development only']
            assert json.loads(original.raw_result)['confirmable'] is False
            print('M2 PRODUCTION REFUSAL TK', view.ack_thread, view.ack_exposed, view.ack_mapped,
                  len(original.disclosure.raw), view.root.winfo_geometry())
            view.buttons['skip'].invoke()
            assert view.lifecycle.state == 'invalidated'
        finally:
            view.close()


def test_real_tk_cancel_before_delivery_cannot_retain(tmp_path):
    from shared.optional_setup_tk_harness_v3 import TkPlanningHarness

    with context.issue_controlled_context(tmp_path / 'cancel') as issued:
        run = context.ReadOnlyPlanningRun.create(issued, components=[proto.QWEN3_CUSTOMVOICE])
        view = TkPlanningHarness(run)
        view.start()
        view.close()
        assert view.lifecycle.state == 'invalidated'
        assert view.ack_thread is None


def test_synthetic_complete_planner_disclosure_through_real_tk(tmp_path):
    from pathlib import Path
    from shared import artifact_store as store, optional_setup_resource_budget as rb
    from shared.optional_setup_tk_harness_v3 import TkPlanningHarness
    from test_optional_setup_display_controller_v3 import INVENTORY_ADAPTER, EXTENSION_ADAPTER
    from test_artifact_transfer import operation
    from tts import qwen3_engine_authority as engine, qwen3_runtime as rt

    run = synthetic_run(tmp_path,
        extra=INVENTORY_ADAPTER + EXTENSION_ADAPTER, action='rebuild-canonical')
    parent = run.repo / '.venv'
    canonical = parent / 'engines/qwen3'
    (canonical / 'Lib').mkdir(parents=True)
    (parent / 'pyvenv.cfg').write_text('home = C:/synthetic-base\ninclude-system-site-packages = false\n')
    (canonical / 'pyvenv.cfg').write_text('home = C:/synthetic-base\n')
    (canonical / 'Lib/synthetic.txt').write_bytes(b'synthetic metadata only')
    depot, ledger, live, _ = operation(run.repo)
    aid = depot.catalog.artifacts[0]['id']
    live._record('reserve', aid, 8)
    live._record('consume', aid, 3)
    live.finish()
    _, _, second, _ = operation(run.repo)
    second._record('reserve', aid, 8)
    second._record('consume', aid, 1)
    second.finish()
    partials = depot.root / 'incomplete'
    partials.mkdir()
    (partials / ('e' * 32 + '.part')).write_bytes(b'abc')
    prior = ledger.prior_state(budget=rb.Budget())
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rt, 'repo_root', lambda: run.repo)
        inventory = engine.snapshot(budget=rb.Budget())
    before = {p: p.read_bytes() for base in (depot.root, parent)
              for p in base.rglob('*') if p.is_file()}
    view = TkPlanningHarness.for_test(run)
    try:
        assert 'SYNTHETIC' in view.root.title()
        view.start()
        assert view.ack_thread is None and view.lifecycle._retained is None
        pump(view)
        original = view.lifecycle.retain_original()
        assert original.planning.raw == run.planning.raw
        assert original.disclosure.raw == run.candidate().raw_disclosure
        assert view.details.get('1.0', 'end-1c').encode('utf-8') == original.disclosure.raw
        doc = json.loads(original.disclosure.document)
        assert doc['terms'] is not None and doc['reasons'] == []
        assert doc['prior_state'] == prior and doc['engine_identity'] == inventory
        history = doc['prior_state']['history']
        assert len(history) == 2
        assert sorted((h['state']['actual'][aid], h['state']['reserved'][aid]) for h in history) == [(1, 7), (3, 5)]
        assert all(h['sequence'] > 0 and len(h['chain']) == 64 for h in history)
        assert doc['prior_state']['partials'][0]['size'] == 3
        assert len(inventory['entries']) == 4
        assert doc['future_metadata'] == {'all': [None, True, 3.25, {'text': 'synthetic detail'}]}
        assert 'installed_disk_bounds' in doc
        assert original.disclosure.document == store.canonical(doc)
        checked = view.lifecycle.readback()
        assert checked.raw_result == original.raw_result == run.candidate().raw_result
        result = json.loads(checked.raw_result)
        assert result['confirmable'] and result['verified'] == []  # fixture only
        request, envelope = run.planning.to_json(), json.loads(original.disclosure.raw)
        for key in ('session', 'plan_id', 'intended_request_id', 'engine_action'):
            assert envelope[key] == request[key]
        assert envelope['selected'] == request['components']
        assert envelope['planning_request_id'] == request['request_id']
        assert view.ack_thread == threading.get_ident() and view.ack_exposed and view.ack_mapped
        assert set(view.buttons) == {'install', 'skip', 'cancel'}
        assert view.lifecycle.confirmation is None
        assert not view.buttons['install'].instate(['disabled'])
        assert 'Repair/Rebuild' in view.buttons['install'].cget('text')
        assert all(p.read_bytes() == raw for p, raw in before.items())
        observation = json.loads((run.repo / 'observation.json').read_bytes())
        assert {f[0] for f in observation['frames']} == {'plan', '_evaluate'}
        assert all(Path(f[1]) == run.repo / 'scripts/tts/optional_setup_authority.py'
                   for f in observation['frames'])
        outcome = run.wait()
        assert outcome.accepted and outcome.job_active == 0 and outcome.readers_joined
        view.buttons['install'].invoke()
        result = view.lifecycle.confirmation
        assert view.lifecycle.state == 'confirmed'
        assert result.disclosure.raw == original.disclosure.raw
        assert result.disclosure.document == store.canonical(doc)
        assert json.loads(result.consent.terms) == doc['terms']
        from shared import optional_setup_exchange_v3 as exchange
        assert exchange.read_confirmation_exchange(run.repo, expected_disclosure=original.disclosure,
            session=run.session, request_id=request['intended_request_id']) == result
        assert all(p.read_bytes() == raw for p, raw in before.items())
        print('M2 SYNTHETIC COMPLETE TK', len(original.disclosure.raw), outcome.job_total,
              request['request_id'], request['intended_request_id'], request['plan_id'],
              run.session, result.consent.consent_id)
    finally:
        view.close()


def pending_view(tmp_path):
    from shared.optional_setup_tk_harness_v3 import TkPlanningHarness
    view = TkPlanningHarness.for_test(synthetic_run(tmp_path))
    view.run.start()
    assert view.run.wait().accepted
    view._pump()  # No Tk event delivery has occurred yet.
    assert view.lifecycle.state == 'presentation-pending'
    assert view.ack_thread is None and view.lifecycle._retained is None
    return view


def queued_delivery(view, monkeypatch):
    """Pause only the real UI completion callback after actual mapping/Expose."""
    callbacks = []
    monkeypatch.setattr(view.root, 'after_idle', lambda callback: callbacks.append(callback))
    deadline = time.monotonic() + 5
    while not callbacks and time.monotonic() < deadline:
        view.root.update()
        time.sleep(.01)
    assert len(callbacks) == 1 and view.ack_thread is None
    assert view._delivered(view._payload) is True
    return callbacks[0]


@pytest.mark.parametrize('damage', ['duplicate', 'cancel', 'window-close', 'expired', 'session',
    'P', 'I', 'selection', 'action', 'generation', 'candidate', 'original', 'truncated',
    'history-omitted', 'adapter-exception', 'wrong-thread', 'callback-thread', 'undelivered'])
def test_tk_negative_delivery_and_identity_controls(tmp_path, monkeypatch, damage):
    from shared import optional_setup_display_controller_v3 as display, optional_setup_wire_v3 as wire
    view = pending_view(tmp_path)
    payload = view._payload
    try:
        if damage in ('duplicate', 'original'):
            pump(view)
            if damage == 'duplicate':
                view._complete(view._generation, payload)
            else:
                view.lifecycle._retained = dataclasses.replace(view.lifecycle._retained, raw_result=b'{}')
                with pytest.raises(display.ControllerError, match='original-changed'):
                    view.lifecycle.readback()
        elif damage in ('cancel', 'window-close'):
            if damage == 'window-close':
                view.root.tk.call(view.root.protocol('WM_DELETE_WINDOW'))
            else:
                view.close()
            view._complete(view._generation - 1, payload)
        elif damage == 'generation':
            callback = queued_delivery(view, monkeypatch)
            view._generation += 1
            callback()
        elif damage == 'expired':
            view.lifecycle._clock = lambda: time.time() + 601
            view._complete(view._generation, payload)
        elif damage == 'session':
            view.run.session = proto.new_token()
            view._complete(view._generation, payload)
        elif damage in ('P', 'I', 'selection', 'action'):
            request = view.run.planning.to_json()
            field = {'P': 'request_id', 'I': 'intended_request_id',
                     'selection': 'components', 'action': 'engine_action'}[damage]
            request[field] = ([proto.QWEN3_BASE] if damage == 'selection' else
                              'install-missing' if damage == 'action' else proto.new_token())
            view.run.planning = wire.PlanningRequest(wire._canonical(request, wire.MAX_CONTROL_BYTES))
            view._complete(view._generation, payload)
        elif damage == 'candidate':
            view.run._candidate = dataclasses.replace(view.run._candidate)
            view._complete(view._generation, payload)
        elif damage in ('truncated', 'history-omitted'):
            callback = queued_delivery(view, monkeypatch)
            text = payload.raw_disclosure.decode('utf-8')
            if damage == 'truncated':
                text = text[:len(text)//2]
            else:
                model = json.loads(text)
                del model['document']['prior_state']
                text = json.dumps(model)
            # Corrupt both the view and its cached expected text. The issued raw
            # payload, rather than that mutable cache, must still defeat this.
            view._expected = text
            view.details.configure(state='normal')
            view.details.delete('1.0', 'end')
            view.details.insert('1.0', text)
            view.details.configure(state='disabled')
            callback()
        elif damage == 'adapter-exception':
            def broken(payload):
                raise RuntimeError('synthetic display failure')
            view.lifecycle._adapter = broken
            view._complete(view._generation, payload)
        elif damage in ('wrong-thread', 'callback-thread'):
            failures = []
            def wrong_thread():
                try:
                    if damage == 'wrong-thread':
                        view._pump()
                    else:
                        view._complete(view._generation, payload)
                except display.ControllerError as exc:
                    failures.append(exc.code)
                except Exception as exc:
                    failures.append(type(exc).__name__)
            task = threading.Thread(target=wrong_thread)
            task.start()
            task.join(2)
            assert not task.is_alive()
            assert failures == (['ui-thread-required'] if damage == 'wrong-thread' else [])
            assert view.ack_thread is None
        else:
            assert not view._completion_posted and not view._exposed
            view._complete(view._generation, payload)
        assert view.lifecycle.state == 'invalidated'
        assert view.lifecycle._retained is None
        assert set(view.buttons) == {'install', 'skip', 'cancel'}
        if not view._closed:
            view._pump()  # queued UI observation of direct lifecycle invalidation
            assert view.buttons['install'].instate(['disabled'])
        assert view.lifecycle.confirmation is None
        assert not hasattr(view.lifecycle, 'consent') and not hasattr(view.run, 'acquire')
    finally:
        view.close()


def test_native_factory_rejects_disposable_run_and_forged_context(tmp_path):
    from shared import optional_setup_display_controller_v3 as display
    from shared.optional_setup_tk_harness_v3 import TkPlanningHarness
    run = synthetic_run(tmp_path)
    with pytest.raises(display.ControllerError, match='issued-native-harness-required'):
        TkPlanningHarness(run)
    run.context = dataclasses.replace(run.context)
    with pytest.raises(display.ControllerError, match='issued-disposable-harness-required'):
        TkPlanningHarness.for_test(run)


@pytest.mark.parametrize('steering', ['TCL_LIBRARY', 'TK_LIBRARY', 'TCLLIBPATH', 'TKPATH'])
def test_tk_environment_steering_refuses_before_window(tmp_path, monkeypatch, steering):
    from shared import optional_setup_display_controller_v3 as display
    from shared.optional_setup_tk_harness_v3 import TkPlanningHarness
    monkeypatch.setenv(steering, str(tmp_path))
    with pytest.raises(display.ControllerError, match='tk-environment-steering'):
        TkPlanningHarness.for_test(synthetic_run(tmp_path))


@pytest.mark.parametrize('damage', ['python', 'extension', 'script', 'dll'])
def test_tk_runtime_origin_refuses_replacement(tmp_path, monkeypatch, damage):
    from pathlib import Path
    import tkinter as tk
    import _tkinter
    from shared import optional_setup_display_controller_v3 as display
    from shared.optional_setup_tk_harness_v3 import TkPlanningHarness
    if damage in ('python', 'extension'):
        monkeypatch.setattr(tk if damage == 'python' else _tkinter, '__file__', str(tmp_path / 'untrusted.py'))
    elif damage == 'script':
        real = tk.Tk
        def redirected():
            root = real()
            root.tk.setvar('tk_library', str(tmp_path))
            return root
        monkeypatch.setattr(tk, 'Tk', redirected)
    else:
        monkeypatch.setattr(context, 'native_modules', lambda: (Path(tmp_path / 'unapproved-tk.dll'),))
    with pytest.raises(display.ControllerError, match='tk-(code|script|native)-origin'):
        TkPlanningHarness.for_test(synthetic_run(tmp_path))


def test_new_tk_generation_supersedes_old_without_callback_revival(tmp_path):
    from shared import optional_setup_planning_bridge_v3 as bridge, optional_setup_wire_v3 as wire
    from shared.optional_setup_tk_harness_v3 import TkPlanningHarness
    old = pending_view(tmp_path)
    newer = None
    try:
        request = old.run.planning.to_json()
        request.update(request_id=proto.new_token(), intended_request_id=proto.new_token(), plan_id=proto.new_token())
        request['planning_request_id'] = request['request_id']
        planning = wire.PlanningRequest(wire._canonical(request, wire.MAX_CONTROL_BYTES))
        run = bridge.PlanningRun.for_test(context=old.run.context, planning=planning, session=old.run.session)
        newer = TkPlanningHarness.for_test(run)
        old._complete(old._generation, old._payload)
        assert old.lifecycle.state == 'invalidated' and old.lifecycle.error_code == 'superseded'
        assert old.lifecycle._retained is None and old.ack_thread is None
        assert newer.lifecycle.state == 'request-issued'
    finally:
        old.close()
        if newer:
            newer.close()


@pytest.mark.parametrize('mutant', ['raw-render', 'cached-expectation', 'thread', 'generation'])
def test_tk_mutation_controls(tmp_path, monkeypatch, mutant):
    from shared.optional_setup_tk_harness_v3 import TkPlanningHarness
    from test_optional_setup_planning_worker_v3 import _mutated
    if mutant == 'raw-render':
        _mutated(TkPlanningHarness, '_pump', [("self._payload.raw_disclosure.decode('utf-8')",
            "json.dumps(self._payload.to_json(), indent=2)")], monkeypatch)
        control = lambda: test_synthetic_complete_planner_disclosure_through_real_tk(tmp_path)
    elif mutant == 'cached-expectation':
        _mutated(TkPlanningHarness, '_delivered', [("self._expected == payload.raw_disclosure.decode('utf-8')",
                                                 'True')], monkeypatch)
        control = lambda: test_tk_negative_delivery_and_identity_controls(tmp_path, monkeypatch, 'history-omitted')
    elif mutant == 'thread':
        _mutated(TkPlanningHarness, '_pump', [('threading.get_ident() != self.thread', 'False')], monkeypatch)
        control = lambda: test_tk_negative_delivery_and_identity_controls(tmp_path, monkeypatch, 'wrong-thread')
    else:
        _mutated(TkPlanningHarness, '_complete', [('generation != self._generation', 'False')], monkeypatch)
        control = lambda: test_tk_negative_delivery_and_identity_controls(tmp_path, monkeypatch, 'generation')
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        control()
    print('M1 TK MUTATION CAUGHT', mutant)
