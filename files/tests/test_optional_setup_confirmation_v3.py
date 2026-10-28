"""M2 qualification only: deliberate exact consent composition, never spending."""
import json
import dataclasses
import threading
import time

import pytest

from shared import optional_setup_display_controller_v3 as display
from shared import optional_setup_exchange_v3 as exchange
from shared import optional_setup_protocol as proto
from shared import optional_setup_v3 as v3
from shared import optional_setup_wire_v3 as wire
from test_optional_setup_tk_harness_v3 import pending_view, pump, queued_delivery, synthetic_run
from test_optional_setup_display_controller_v3 import make_controller, retained

pytestmark = pytest.mark.usefixtures('production_writes_refused')


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    from shared import artifact_transfer
    from tts import optional_setup_authority, qwen3_setup

    def forbidden(*args, **kwargs):
        pytest.fail('M2 cannot spend, claim, acquire, install or repair')
    for owner, name in ((v3, 'validate_and_spend'), (proto, 'claim_consent'),
            (artifact_transfer.TransferLedger, 'begin'),
            (optional_setup_authority.Planner, 'acquire_disposable'),
            (qwen3_setup, 'install_environment'), (qwen3_setup, 'repair')):
        monkeypatch.setattr(owner, name, forbidden)


def ready_controller(tmp_path, **kwargs):
    c, run, clock, received = make_controller(tmp_path, **kwargs)
    _, original = retained(c, run)
    c.readback()
    return c, run, clock, original


def no_confirmation(view):
    assert view.lifecycle.confirmation is None
    intended = view.lifecycle._planning.to_json()['intended_request_id']
    assert not (view.lifecycle._repo / exchange.EXCHANGE_ROOT / intended).exists()


def test_final_click_composes_one_exact_original_confirmation(tmp_path):
    view = pending_view(tmp_path)
    try:
        pump(view)
        original = view.lifecycle.retain_original()
        assert view.lifecycle.confirmation is None  # delivery/readback is not consent
        assert not view.buttons['install'].instate(['disabled'])
        view.buttons['install'].invoke()
        result = view.lifecycle.confirmation
        assert view.lifecycle.state == 'confirmed'
        assert result.disclosure == original.disclosure
        assert json.loads(result.consent.terms) == json.loads(original.disclosure.document)['terms']
        intended = original.planning.to_json()['intended_request_id']
        assert result.consent.request_id == intended
        checked = exchange.read_confirmation_exchange(view.run.repo,
            expected_disclosure=original.disclosure, session=view.run.session, request_id=intended)
        assert checked == result
        view.buttons['install'].invoke()
        assert view.lifecycle.confirmation is result
        assert view.lifecycle.state == 'confirmed'
        print('M2 EXACT CONFIRMATION', intended, result.consent.consent_id)
    finally:
        view.close()


def test_selection_display_and_carried_continue_return_never_issue_consent(tmp_path, monkeypatch):
    issued = []
    monkeypatch.setattr(v3, 'new_consent', lambda *a, **k: issued.append(True))
    view = pending_view(tmp_path)
    try:
        pump(view)
        # The selected IDs already travelled through Planner. Continue is base-only;
        # even a carried Return has no root/default affirmative binding.
        assert view.run.planning.to_json()['components'] == [proto.QWEN3_CUSTOMVOICE]
        assert str(view.buttons['install'].cget('default')) == 'disabled'
        assert view.root.focus_get() is not view.buttons['install']
        view.details.focus_force()
        for _ in range(3):
            view.details.event_generate('<Return>')
            view.root.event_generate('<Return>')
            view.root.update()
        no_confirmation(view)
        assert issued == []
        assert view.lifecycle.state == 'original-retained'
        print('M2 NO FINAL CLICK: selected proposal, actual delivery/readback, carried Continue/Return')
    finally:
        view.close()


@pytest.mark.parametrize('stage', ['delivery', 'retention', 'readback'])
def test_final_click_requires_all_separate_stages(tmp_path, monkeypatch, stage):
    view = pending_view(tmp_path)
    try:
        callback = queued_delivery(view, monkeypatch)
        if stage != 'delivery':
            view.lifecycle.acknowledge_display(view._payload)
        if stage == 'readback':
            view.lifecycle.retain_original()
        assert view.buttons['install'].instate(['disabled'])
        with pytest.raises(display.ControllerError, match='readback-required'):
            view.lifecycle.confirm()
        view._install()
        callback()
        no_confirmation(view)
        assert view.lifecycle.state == 'invalidated'
    finally:
        view.close()


@pytest.mark.parametrize('damage', ['generation', 'session', 'P', 'I', 'plan-id', 'selection',
    'ordering', 'action', 'worker', 'context', 'view-run', 'payload', 'retained',
    'truncated', 'replacement-view', 'expired', 'future'])
def test_final_click_rechecks_live_original_and_tk_generation(tmp_path, damage):
    view = pending_view(tmp_path)
    try:
        pump(view)
        if damage == 'generation':
            view._generation += 1
        elif damage == 'session':
            view.run.session = proto.new_token()
        elif damage in ('P', 'I', 'plan-id', 'selection', 'ordering', 'action'):
            p = view.run.planning.to_json()
            key = {'P': 'request_id', 'I': 'intended_request_id', 'plan-id': 'plan_id',
                'selection': 'components', 'ordering': 'components', 'action': 'engine_action'}[damage]
            p[key] = ('rebuild-canonical' if damage == 'action' else
                [proto.QWEN3_BASE] if damage == 'selection' else
                [proto.QWEN3_BASE, proto.QWEN3_CUSTOMVOICE] if damage == 'ordering' else proto.new_token())
            view.run.planning = wire.PlanningRequest(wire._canonical(p, wire.MAX_CONTROL_BYTES))
        elif damage == 'worker':
            view.run._candidate = dataclasses.replace(view.run.candidate())
        elif damage == 'context':
            view.run.context = dataclasses.replace(view.run.context)
        elif damage == 'view-run':
            import copy
            view.run = copy.copy(view.run)
        elif damage == 'payload':
            view._payload = dataclasses.replace(view._payload)
        elif damage == 'retained':
            original = view.lifecycle._retained
            d = original.disclosure.to_json()
            d['document']['forged_metadata'] = True
            replacement = wire.decode_disclosure(wire._canonical(d, wire.MAX_DISCLOSURE_BYTES),
                planning=original.planning, session=view.run.session)
            view.lifecycle._retained = dataclasses.replace(original, disclosure=replacement)
        elif damage in ('truncated', 'replacement-view'):
            view.details.configure(state='normal')
            view.details.delete('1.0', 'end')
            view._expected = ('{}' if damage == 'replacement-view' else view._expected[:100])
            view.details.insert('1.0', view._expected)
            view.details.configure(state='disabled')
        else:
            view.lifecycle._clock = lambda: time.time() + (601 if damage == 'expired' else -62)
        view._install()
        no_confirmation(view)
        assert view.lifecycle.state == 'invalidated'
    finally:
        view.close()


@pytest.mark.parametrize('decline', ['skip', 'cancel', 'window-close', 'failure'])
def test_decline_never_resurrects_final_intention(tmp_path, decline):
    view = pending_view(tmp_path)
    try:
        pump(view)
        if decline == 'window-close':
            view.root.tk.call(view.root.protocol('WM_DELETE_WINDOW'))
        elif decline == 'failure':
            view.lifecycle.invalidate('presentation-interrupted')
        else:
            view.buttons[decline].invoke()
        view._install()
        view._complete(view._generation, view._payload)
        no_confirmation(view)
        assert view.lifecycle.state == 'invalidated'
    finally:
        view.close()


@pytest.mark.parametrize('state', [proto.UNSUPPORTED, proto.BUSY, proto.DAMAGED, proto.UNVERIFIED, proto.BAD_BUNDLE])
def test_nonconfirmable_planner_states_refuse_final_action(tmp_path, state):
    c, run, _, _ = ready_controller(tmp_path, extra='STATE = ' + repr(state))
    assert not c.confirmation_eligible()
    with pytest.raises(display.ControllerError, match='plan-not-confirmable'):
        c.confirm()
    assert c.confirmation is None


def test_all_healthy_noop_plan_has_no_final_action(tmp_path):
    extra = '''
spec = rt.model_spec('customvoice')
path = rt.safe_model_path(spec, 'model.safetensors')
path.parent.mkdir(parents=True, exist_ok=True)
path.write_bytes(b'synthetic-customvoice')
rt.model_status = lambda key: (True, 'synthetic healthy fixture')
'''
    c, run, _, _ = ready_controller(tmp_path, extra=extra)
    assert not c.confirmation_eligible()
    with pytest.raises(display.ControllerError):
        c.confirm()
    assert c.confirmation is None


@pytest.mark.parametrize('winner', ['cancel', 'confirm', 'expiry', 'expiry-before'])
def test_deterministic_cancellation_expiry_race(tmp_path, monkeypatch, winner):
    c, run, clock, original = ready_controller(tmp_path)
    entered, release = threading.Event(), threading.Event()
    real = v3.new_consent
    minted = []
    def pause(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        minted.append(True)
        return real(*args, **kwargs)
    monkeypatch.setattr(v3, 'new_consent', pause)
    failures, answers = [], []
    def click():
        try:
            answers.append(c.confirm())
        except display.ControllerError as exc:
            failures.append(exc.code)
    if winner in ('cancel', 'expiry-before'):
        real_read = exchange.read_planning_exchange
        def paused_read(*args, **kwargs):
            entered.set()
            assert release.wait(10)
            return real_read(*args, **kwargs)
        monkeypatch.setattr(exchange, 'read_planning_exchange', paused_read)
    task = threading.Thread(target=click)
    task.start()
    assert entered.wait(10)
    if winner == 'cancel':
        c.cancel()  # final readback is in flight, before the affirmative reservation
    elif winner == 'expiry-before':
        clock[0] += 601
    else:
        c.cancel()  # the affirmative reservation already won
        if winner == 'expiry':
            clock[0] += 601
    release.set()
    task.join(10)
    assert not task.is_alive()
    if winner == 'confirm':
        assert len(minted) == len(answers) == 1 and not failures
        assert c.state == 'confirmed'
        c.cancel()
        with pytest.raises(display.ControllerError, match='confirmation-terminal'):
            c.confirm()
        assert c.confirmation is answers[0]
    else:
        assert not answers and failures and c.confirmation is None
        assert c.state == ('confirmation-failed' if winner == 'expiry' else 'invalidated')
        assert len(minted) == (1 if winner == 'expiry' else 0)
    print('M2 RACE WINNER', winner, c.state, len(minted))


@pytest.mark.parametrize('mode', ['rapid', 'reentrant', 'concurrent'])
def test_at_most_one_consent_even_with_reentry(tmp_path, monkeypatch, mode):
    c, run, _, original = ready_controller(tmp_path)
    real = v3.new_consent
    calls, failures = [], []
    entered, release = threading.Event(), threading.Event()
    def mint(*args, **kwargs):
        calls.append(True)
        if mode == 'reentrant':
            with pytest.raises(display.ControllerError, match='confirmation-terminal'):
                c.confirm()
        if mode == 'concurrent':
            entered.set()
            assert release.wait(10)
        return real(*args, **kwargs)
    monkeypatch.setattr(v3, 'new_consent', mint)
    if mode == 'concurrent':
        def first():
            try:
                c.confirm()
            except BaseException as exc:
                failures.append(exc)
        task = threading.Thread(target=first)
        task.start()
        assert entered.wait(10)
        with pytest.raises(display.ControllerError, match='confirmation-terminal'):
            c.confirm()
        release.set()
        task.join(10)
        assert not task.is_alive() and failures == []
    else:
        c.confirm()
        for _ in range(10):
            with pytest.raises(display.ControllerError, match='confirmation-terminal'):
                c.confirm()
    assert c.state == 'confirmed' and len(calls) == 1
    c.invalidate('superseded')
    assert c.state == 'confirmed' and c.confirmation is not None


@pytest.mark.parametrize('failure', ['encode', 'publish-before', 'publish-after', 'interrupt', 'readback', 'late-expiry'])
def test_failed_publication_is_terminal_and_never_reports_success(tmp_path, monkeypatch, failure):
    c, run, clock, original = ready_controller(tmp_path)
    minted = []
    real_mint, real_publish = v3.new_consent, exchange.prepare_confirmation
    def mint(*args, **kwargs):
        minted.append(True)
        return real_mint(*args, **kwargs)
    def fail(*args, **kwargs):
        raise OSError('synthetic interruption')
    def after(*args, **kwargs):
        result = real_publish(*args, **kwargs)
        if failure == 'late-expiry':
            clock[0] += 601
            return result
        if failure == 'interrupt':
            raise KeyboardInterrupt('synthetic publication interruption')
        raise OSError('synthetic interrupted publication return')
    monkeypatch.setattr(v3, 'new_consent', mint)
    if failure == 'encode':
        monkeypatch.setattr(wire, 'encode_confirmation_request', fail)
    elif failure == 'readback':
        monkeypatch.setattr(exchange, 'read_confirmation_exchange', fail)
    else:
        monkeypatch.setattr(exchange, 'prepare_confirmation', fail if failure == 'publish-before' else after)
    if failure == 'interrupt':
        with pytest.raises(KeyboardInterrupt):
            c.confirm()
    else:
        with pytest.raises(display.ControllerError, match='confirmation-'):
            c.confirm()
    expected = 'confirmation-failed' if failure == 'encode' else 'confirmation-uncertain'
    assert c.state == expected and c.confirmation is None and minted == [True]
    c.cancel()
    with pytest.raises(display.ControllerError, match='confirmation-terminal'):
        c.confirm()
    assert c.state == expected and minted == [True]
    print('M2 TERMINAL FAILURE', failure, expected)


@pytest.mark.parametrize('change', ['disk', 'headroom', 'source', 'artifact', 'payload', 'reuse', 'metadata',
    'history', 'partials', 'incomplete'])
def test_final_action_rejects_forged_consistent_exchange(tmp_path, change):
    from test_optional_setup_display_controller_v3 import EXTENSION_ADAPTER
    c, run, clock, original = ready_controller(tmp_path, extra=EXTENSION_ADAPTER)
    d = original.disclosure.to_json()
    doc, terms = d['document'], d['document']['terms']
    row = terms['artifacts'][0]
    if change in ('disk', 'headroom'):
        terms['disk']['new_bytes' if change == 'disk' else 'temporary_headroom_bytes'] += 1
    elif change == 'source':
        row['source']['url'] = 'https://replacement.invalid/' + row['source']['revision'] + '/object'
    elif change == 'artifact':
        row['sha256'] = 'f' * 64
    elif change == 'payload':
        row['size'] += 1
        row['expected_new_bytes'] += 1
        row['max_payload_bytes'] += 1
        terms['payload']['expected_new_bytes'] += 1
        terms['payload']['max_payload_bytes'] += 1
    elif change == 'reuse':
        terms['payload']['expected_new_bytes'] -= row['expected_new_bytes']
        terms['payload']['max_payload_bytes'] -= row['max_payload_bytes']
        row.update(verified_reuse_bytes=row['size'], expected_new_bytes=0, max_payload_bytes=0)
    elif change == 'metadata':
        doc['future_metadata']['all'][-1]['text'] = 'internally consistent forgery'
    elif change == 'history':
        doc['prior_state']['history'].append(dict(consent_id='a'*32, session='b'*32,
            fingerprint='c'*64, state=dict(status='spent', actual={}, reserved={}), sequence=1, chain='d'*64))
    elif change == 'partials':
        doc['prior_state']['partials'].append(dict(name='e'*32+'.part', size=3, mtime_ns=1,
                                                 verified_reuse_bytes=0))
    folder = run.repo / exchange.EXCHANGE_ROOT / original.planning.to_json()['request_id']
    raw = wire._canonical(d, wire.MAX_DISCLOSURE_BYTES)
    if change == 'incomplete':
        (folder / 'plan.json').write_bytes(raw[:len(raw)//2])
    else:
        forged = wire.decode_disclosure(raw, planning=original.planning, session=run.session, now=lambda: clock[0])
        answer = wire.encode_planning_result(disclosure=forged, issued_utc=proto.utc_text(clock[0]), now=lambda: clock[0])
        # Independently prove the pair is internally valid, including new consent
        # and matching hashes; that still cannot replace the retained original.
        consent = v3.encode_consent(v3.new_consent(terms, session=run.session,
            request_id=d['intended_request_id'], now=lambda: clock[0]))
        control = wire.encode_confirmation_request(disclosure=forged, raw_consent=consent,
            issued_utc=proto.utc_text(clock[0]), now=lambda: clock[0])
        assert wire.decode_confirmation_request(control, raw_disclosure=raw, raw_consent=consent,
            expected_disclosure=forged, session=run.session, request_id=d['intended_request_id'], now=lambda: clock[0])
        (folder / 'plan.json').write_bytes(raw)
        (folder / 'result.json').write_bytes(answer)
    with pytest.raises(display.ControllerError, match='original-changed'):
        c.confirm()
    assert c.confirmation is None and c.state == 'invalidated'


def test_reservation_precedes_consent_issuance(tmp_path, monkeypatch):
    c, run, _, _ = ready_controller(tmp_path)
    real = v3.new_consent
    def check(*args, **kwargs):
        assert c.state == 'confirming'
        return real(*args, **kwargs)
    monkeypatch.setattr(v3, 'new_consent', check)
    c.confirm()
    assert c.state == 'confirmed'


def test_second_window_cannot_reissue_one_intention(tmp_path):
    from shared.optional_setup_tk_harness_v3 import TkPlanningHarness
    view = pending_view(tmp_path)
    try:
        pump(view)
        with pytest.raises(display.ControllerError, match='request-id-reused'):
            TkPlanningHarness.for_test(view.run)
        view.buttons['install'].invoke()
        assert view.lifecycle.state == 'confirmed'
    finally:
        view.close()


def test_final_action_requires_ui_thread(tmp_path):
    view = pending_view(tmp_path)
    try:
        pump(view)
        failures = []
        def wrong():
            try:
                view._install()
            except display.ControllerError as exc:
                failures.append(exc.code)
        task = threading.Thread(target=wrong)
        task.start()
        task.join(5)
        assert not task.is_alive() and failures == ['ui-thread-required']
        no_confirmation(view)
    finally:
        view.close()


@pytest.mark.parametrize('mutant', ['no-live-view', 'no-generation', 'no-readback-gate', 'no-final-readback',
    'no-eligibility', 'no-reservation', 'no-independent-readback', 'no-equality', 'auto-consent'])
def test_m2_mutation_controls(tmp_path, monkeypatch, mutant):
    from shared.optional_setup_tk_harness_v3 import TkPlanningHarness
    from test_optional_setup_planning_worker_v3 import _mutated
    if mutant == 'no-live-view':
        _mutated(TkPlanningHarness, '_install', [('not self._delivered(self._payload)', 'False')], monkeypatch)
        control = lambda: test_final_click_rechecks_live_original_and_tk_generation(tmp_path, 'replacement-view')
    elif mutant == 'no-generation':
        _mutated(TkPlanningHarness, '_install', [('self._ready_generation != (self._generation, id(self._payload))',
                                                'False')], monkeypatch)
        control = lambda: test_final_click_rechecks_live_original_and_tk_generation(tmp_path, 'generation')
    elif mutant == 'no-readback-gate':
        _mutated(display.DisplayLifecycle, 'confirm', [('or self._readback is None', 'or False')], monkeypatch)
        control = lambda: test_final_click_requires_all_separate_stages(tmp_path, monkeypatch, 'readback')
    elif mutant == 'no-final-readback':
        _mutated(display.DisplayLifecycle, 'confirm', [('self.readback()', 'None')], monkeypatch)
        control = lambda: test_final_action_rejects_forged_consistent_exchange(tmp_path, 'metadata')
    elif mutant == 'no-eligibility':
        _mutated(display.DisplayLifecycle, 'confirm', [('not wire._confirmable(original.disclosure.to_json())',
                                                       'False')], monkeypatch)
        control = lambda: test_nonconfirmable_planner_states_refuse_final_action(tmp_path, proto.UNVERIFIED)
    elif mutant == 'no-reservation':
        _mutated(display.DisplayLifecycle, 'confirm', [("self._state = 'confirming'", "self._state = 'original-retained'")], monkeypatch)
        control = lambda: test_reservation_precedes_consent_issuance(tmp_path, monkeypatch)
    elif mutant == 'no-independent-readback':
        _mutated(display.DisplayLifecycle, 'confirm', [('independent = exchange.read_confirmation_exchange(self._repo,\n'
            '            expected_disclosure=original.disclosure, session=self._session,\n'
            "            request_id=p['intended_request_id'], now=self._clock)", 'independent = checked')], monkeypatch)
        control = lambda: test_failed_publication_is_terminal_and_never_reports_success(tmp_path, monkeypatch, 'readback')
    elif mutant == 'no-equality':
        _mutated(display.DisplayLifecycle, 'confirm', [('independent != checked', 'False')], monkeypatch)
        control = lambda: test_independent_readback_cannot_substitute_other_valid_consent(tmp_path, monkeypatch)
    else:
        _mutated(TkPlanningHarness, '_complete', [('self._ready_generation = (generation, id(payload))',
            'self.lifecycle.confirm()\n        self._ready_generation = (generation, id(payload))')], monkeypatch)
        control = lambda: test_selection_display_and_carried_continue_return_never_issue_consent(tmp_path, monkeypatch)
    with pytest.raises((AssertionError, display.ControllerError, pytest.fail.Exception)):
        control()
    print('M2 MUTATION CAUGHT', mutant)


def test_independent_readback_cannot_substitute_other_valid_consent(tmp_path, monkeypatch):
    c, run, clock, original = ready_controller(tmp_path)
    real = exchange.read_confirmation_exchange
    def substitute(*args, **kwargs):
        result = real(*args, **kwargs)
        new = v3.encode_consent(v3.new_consent(json.loads(result.consent.terms), session=run.session,
            request_id=result.consent.request_id, now=lambda: clock[0]))
        raw = wire.encode_confirmation_request(disclosure=original.disclosure, raw_consent=new,
            issued_utc=proto.utc_text(clock[0]), now=lambda: clock[0])
        return wire.decode_confirmation_request(raw, raw_disclosure=original.disclosure.raw, raw_consent=new,
            expected_disclosure=original.disclosure, session=run.session, request_id=result.consent.request_id,
            now=lambda: clock[0])
    monkeypatch.setattr(exchange, 'read_confirmation_exchange', substitute)
    with pytest.raises(display.ControllerError, match='confirmation-uncertain'):
        c.confirm()
    assert c.confirmation is None and c.state == 'confirmation-uncertain'


@pytest.mark.parametrize('damage', ['lost-history', 'lost-partials', 'lost-inventory',
    'inventory-identity', 'lost-unknown-metadata', 'readiness-scope', 'hidden-repair'])
def test_complete_original_defeats_valid_replacement_with_matching_hashes(damage):
    from test_optional_setup_wire_v3 import graph_document, planning, disclosure, confirmation, decode_confirmation
    doc = graph_document(True, histories=2)
    doc['engine_identity']['entries'] = [['.', [1, 2, 0, 4, 5]], ['Lib/fixture', [1, 3, 8, 4, 5]]]
    request = planning(list(proto.COMPONENTS), 'install-missing')
    original = disclosure(doc, request)
    doc = original.to_json()['document']
    action = 'install-missing'
    if damage == 'lost-history':
        doc['prior_state']['history'].pop()
    elif damage == 'lost-partials':
        doc['prior_state']['partials'].pop()
    elif damage == 'lost-inventory':
        doc['engine_identity']['entries'].pop()
    elif damage == 'inventory-identity':
        doc['engine_identity']['entries'][1][1][2] += 1
    elif damage == 'lost-unknown-metadata':
        del doc['disclosure_metadata']
    else:
        for rows in (doc['components'], doc['terms']['components']):
            next(r for r in rows if r['id'] == proto.QWEN3_CUSTOMVOICE).update(
                readiness=proto.DAMAGED, scope=proto.SCOPE_REPAIR)
        doc['operations'][proto.QWEN3_CUSTOMVOICE] = proto.SCOPE_REPAIR
        if damage == 'hidden-repair':
            action = doc['terms']['engine_action'] = 'rebuild-canonical'
            doc['engine_readiness'] = doc['terms']['engine_readiness'] = proto.DAMAGED
    forged = disclosure(doc, planning(list(proto.COMPONENTS), action))
    control, _, consent = confirmation(forged)
    assert decode_confirmation(control, forged, consent)  # internally valid forged pair
    with pytest.raises(proto.ProtocolError):
        decode_confirmation(control, forged, consent, expected_disclosure=original)


def test_ordering_and_empty_selection_cannot_authorize_confirmation():
    from test_optional_setup_wire_v3 import planning, disclosure, confirmation, decode_confirmation
    from test_optional_setup_v3 import model_terms
    terms = model_terms()
    terms['components'].insert(0, dict(id=proto.KOKORO, readiness=proto.READY, scope=None))
    from test_optional_setup_wire_v3 import document
    shown = disclosure(document(terms), planning([proto.KOKORO, proto.QWEN3_BASE]))
    control, _, consent = confirmation(shown)
    for selected in ([], [proto.QWEN3_BASE, proto.KOKORO]):
        d = json.loads(control)
        d['components'] = selected
        with pytest.raises(proto.ProtocolError):
            decode_confirmation(wire._canonical(d, wire.MAX_CONTROL_BYTES), shown, consent)


def test_deliberate_keyboard_focus_can_confirm(tmp_path):
    view = pending_view(tmp_path)
    try:
        pump(view)
        button = view.buttons['install']
        assert view.root.focus_get() is not button
        assert str(button.cget('takefocus')) == '1'
        button.focus_force()
        view.root.update()
        assert view.root.focus_get() is button
        button.event_generate('<Return>')
        view.root.update()
        assert view.lifecycle.state == 'confirmed'
        assert view.lifecycle.confirmation is not None
    finally:
        view.close()
