"""Stage 4B-3A: synthetic authoritative plans and actual locked acquisition boundaries."""
from pathlib import Path
import hashlib
import json
import io
import dataclasses
import threading
from types import SimpleNamespace
from email.message import Message

import pytest

from shared import artifact_store as store
from shared import artifact_transfer as transfer
from shared import optional_setup_protocol as proto
from shared import optional_setup_v3 as v3
from tts import qwen3_setup as su
from tts import qwen3_runtime as rt
from tts import model_assets as assets
from test_optional_tts_setup import world, sandbox, tiny_assets, install_chatterbox, install_kokoro  # noqa: F401
from test_qwen3_runtime import install_environment, install_model, TINY_FILES, CUSTOM_ONLY, BASE_ONLY
from test_optional_setup_v3 import model_terms

pytestmark = pytest.mark.usefixtures('production_writes_refused')


def test_prior_disclosure_is_read_only_even_when_the_store_does_not_exist(tmp_path):
    ledger = transfer.TransferLedger(store.ArtifactStore(tmp_path, store.Catalog(model_terms())))
    assert ledger.prior_state() == {'schema': 'act-prior-transfer-state', 'version': 1,
                                    'history': [], 'partials': []}
    assert list(tmp_path.iterdir()) == []


class Response(io.BytesIO):
    status = 200

    def __init__(self, data, url):
        super().__init__(data)
        self.url = url
        self.headers = Message()
        self.headers['Content-Length'] = str(len(data))

    def geturl(self):
        return self.url


@pytest.fixture
def authority_world(world, monkeypatch):
    # This is the only approval of tiny model identities: trusted fixture setup,
    # never a received consent/hash or mutable cache record.
    from tts import optional_setup_authority as auth
    monkeypatch.setattr(auth, 'MODEL_IDENTITIES_SHA256', auth.model_identities_sha256())
    state = {'engine': proto.READY, 'health': {c: True for c in proto.COMPONENTS}, 'busy': ()}
    observed = []

    def observe(selected, *, locked, cancelled):
        observed.append((selected, locked, su.InstallLock.held_by_this_thread()))
        return auth.Observation(dict(state['health']), state['engine'], frozenset(state['busy']))

    planner = auth.Planner(observer=observe, disk_free=lambda root: 10**12)
    monkeypatch.setattr(assets, 'spacy_english_state', lambda: (state.get('spacy', proto.READY), 'synthetic metadata'))
    calls = []

    def opener(request, *, timeout):
        assert su.InstallLock.held_by_this_thread()
        calls.append(request.full_url)
        for key, extra in (('customvoice', CUSTOM_ONLY), ('base', BASE_ONLY)):
            spec = rt.model_spec(key)
            for name, data in {**TINY_FILES, **extra}.items():
                if request.full_url == su.hub_url(spec, name):
                    return Response(data, request.full_url)
        if request.full_url == assets.SPACY_WHEEL_URL:
            from test_optional_tts_setup import WHEEL
            return Response(WHEEL, request.full_url)
        for group in (assets.kokoro_set(), assets.chatterbox_set()):
            for name, (size, _) in group.files.items():
                if request.full_url == su.HUB_URL.format(repo=group.repo, revision=group.revision, path=name):
                    return Response(b'k' * size, request.full_url)
        raise AssertionError('unapproved source: ' + request.full_url)

    return world, planner, state, calls, opener, observed


def confirmed(planner, selected, **kwargs):
    from tts import optional_setup_authority as auth
    plan = planner.plan(selected, **kwargs)
    assert plan.terms is not None, plan.to_json()
    consent = v3.new_consent(plan.terms, session='a' * 32, request_id=proto.new_token())
    return auth.Confirmation(plan, v3.encode_consent(consent), consent.session, consent.request_id)


def execute(fixture, confirmation, **kwargs):
    _, planner, _, _, opener, _ = fixture
    return planner.acquire_disposable(confirmation, opener=opener, **kwargs)


def test_planning_hashes_same_size_corruption_and_does_not_create_store(authority_world):
    root, planner, _, calls, _, observed = authority_world
    install_model(root, 'customvoice', marker=False, corrupt='model.safetensors')
    plan = planner.plan([proto.QWEN3_CUSTOMVOICE])
    assert plan.terms['payload']['expected_new_bytes'] == len(CUSTOM_ONLY['model.safetensors'])
    assert plan.terms['components'][0]['scope'] == 'repair'
    assert not (root / store.STORE).exists() and calls == []
    assert observed[-1][1:] == (False, False)


def test_chatterbox_race_is_checked_after_real_lock_before_any_transfer(authority_world, monkeypatch):
    root, planner, _, calls, _, observed = authority_world
    folder = install_chatterbox(root, without={'vocab.json'})
    confirmation = confirmed(planner, [proto.CHATTERBOX])
    assert confirmation.plan.terms['payload']['expected_new_bytes'] == 7
    original = su.InstallLock.acquire

    def raced(lock):
        original(lock)
        (folder / 't3_turbo_v1.safetensors').unlink()

    monkeypatch.setattr(su.InstallLock, 'acquire', raced)
    result = execute(authority_world, confirmation)
    assert result.state == proto.REFUSED and calls == []
    assert observed[-1][1:] == (True, True)
    assert not (root / store.STORE).exists()


def b1_zero_consent_control(fixture):
    root, planner, _, calls, _, _ = fixture
    install_model(root, 'customvoice', marker=False)
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE])
    assert confirmation.plan.terms['payload']['max_payload_bytes'] == 0
    path = rt.model_spec('customvoice').directory / 'model.safetensors'
    path.write_bytes(b'x' * path.stat().st_size)
    result = execute(fixture, confirmation)
    assert result.state == proto.REFUSED and not result.consent_spent
    assert calls == [] and not (root / store.STORE).exists()


def b2_model_only_control(fixture):
    root, planner, state, calls, _, _ = fixture
    install_environment(root, requirements=(root / 'scripts/qwen3-requirements.txt').read_text())
    install_model(root, 'customvoice')
    (rt.model_spec('customvoice').directory / 'model.safetensors').unlink()
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE])
    assert confirmation.plan.terms['engine_action'] == 'none'
    assert all(a['kind'] == 'model' for a in confirmation.plan.terms['artifacts'])
    environment_before = {p: p.read_bytes() for p in rt.venv_dir().rglob('*') if p.is_file()}
    state_before = rt.state_path().read_bytes()
    commands, deletions = [], []

    def no_command(*args, **kwargs):
        commands.append(args)
        pytest.fail('model-only authority invoked an engine/package command')

    def no_remove(path):
        deletions.append(path)
        pytest.fail('model-only authority invoked environment deletion')

    state['engine'] = proto.UNVERIFIED
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(su, 'run_command', no_command)
        patch.setattr(rt, 'remove_entry', no_remove)
        result = execute(fixture, confirmation)
    assert result.state == proto.REFUSED and not result.consent_spent
    assert calls == [] and not (root / store.STORE).exists()
    assert commands == [] and deletions == []
    assert environment_before == {p: p.read_bytes() for p in rt.venv_dir().rglob('*') if p.is_file()}
    assert rt.state_path().read_bytes() == state_before


def test_b1_content_changes_after_confirmation(authority_world):
    b1_zero_consent_control(authority_world)


def test_b2_later_engine_failure(authority_world):
    b2_model_only_control(authority_world)


def test_explicitly_replanned_hash_repair_uses_only_the_permitted_artifact(authority_world, monkeypatch):
    root, planner, _, calls, _, _ = authority_world
    install_model(root, 'customvoice', corrupt='model.safetensors')
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE])
    assert confirmation.plan.terms['payload']['max_payload_bytes'] == len(CUSTOM_ONLY['model.safetensors'])
    monkeypatch.setattr(su, 'download_file', lambda *a, **k: pytest.fail('legacy downloader bypass'))
    monkeypatch.setattr(su, 'install_environment', lambda **k: pytest.fail('environment mutation'))
    result = execute(authority_world, confirmation)
    assert result.state == proto.SUCCEEDED, result
    assert len(calls) == 1 and calls[0].endswith('/model.safetensors')
    assert sum(result.transfer_state['actual'].values()) == len(CUSTOM_ONLY['model.safetensors'])
    assert not rt.model_bad_files('customvoice', full=True)


def test_legitimate_zero_transfer_verification_and_existing_shared_hardlinks(authority_world):
    root, planner, _, calls, _, _ = authority_world
    install_model(root, 'customvoice', marker=False)
    # Native manual installs share files by hardlink; immutable copies, not links,
    # are imported into the store, and valid reuse still costs zero network bytes.
    shared = rt.model_spec('customvoice').directory / 'speech_tokenizer/model.safetensors'
    os_link = __import__('os').link
    os_link(shared, root / 'shared-native-file')
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE])
    assert confirmation.plan.terms['payload']['expected_new_bytes'] == 0
    result = execute(authority_world, confirmation)
    assert result.state == proto.SUCCEEDED and calls == []
    assert rt.model_status('customvoice')[0]
    assert all(p.stat().st_nlink == 1 for p in (root / store.STORE / 'objects').glob('*.blob'))


def test_both_qwen_models_deduplicate_shared_content_and_use_native_installer(authority_world, monkeypatch):
    root, planner, _, calls, _, _ = authority_world
    native = su.install_model
    seen = []

    def record(key, **kwargs):
        seen.append((key, su.InstallLock.held_by_this_thread()))
        return native(key, **kwargs)

    monkeypatch.setattr(su, 'install_model', record)
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE])
    expected = sum(map(len, TINY_FILES.values())) + sum(map(len, CUSTOM_ONLY.values())) + sum(map(len, BASE_ONLY.values()))
    assert confirmation.plan.terms['payload']['expected_new_bytes'] == expected
    result = execute(authority_world, confirmation)
    assert result.state == proto.SUCCEEDED, result
    assert seen == [('customvoice', True), ('base', True)] and len(calls) == 4
    assert sum(result.transfer_state['actual'].values()) == expected
    assert all(rt.model_status(k)[0] for k in rt.MODEL_KEYS)


@pytest.mark.parametrize('missing', [{'vocab.json'}, {'vocab.json', 't3_turbo_v1.safetensors'}])
def test_authorized_chatterbox_preserves_verified_files(authority_world, missing):
    root, planner, _, calls, _, _ = authority_world
    folder = install_chatterbox(root, without=missing)
    kept = folder / 's3gen_meanflow.safetensors'
    before = kept.stat()
    confirmation = confirmed(planner, [proto.CHATTERBOX])
    result = execute(authority_world, confirmation)
    assert result.state == proto.SUCCEEDED and len(calls) == len(missing), result
    assert (kept.stat().st_ino, kept.stat().st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert all(assets.file_state(assets.chatterbox_set(), n)[0] == proto.READY for n in assets.CHATTERBOX_FILES)


def test_combined_groups_validate_before_acquiring_kokoro_subset(authority_world, monkeypatch):
    root, planner, _, calls, _, _ = authority_world
    folder = install_chatterbox(root, without={'vocab.json'})
    confirmation = confirmed(planner, [proto.KOKORO, proto.CHATTERBOX])
    original = su.InstallLock.acquire

    def raced(lock):
        original(lock)
        (folder / 't3_turbo_v1.safetensors').unlink()

    monkeypatch.setattr(su.InstallLock, 'acquire', raced)
    result = execute(authority_world, confirmation)
    assert result.state == proto.REFUSED and calls == []
    assert not assets.snapshot_dir(assets.kokoro_set()).exists()
    assert not (root / store.STORE).exists()


@pytest.mark.parametrize('group', [proto.KOKORO, proto.CHATTERBOX])
def test_verified_group_becoming_missing_requires_reconfirmation(authority_world, group):
    root, planner, _, calls, _, _ = authority_world
    folder = install_kokoro(root) if group == proto.KOKORO else install_chatterbox(root)
    confirmation = confirmed(planner, [group])
    next(folder.glob('*.json')).unlink()
    result = execute(authority_world, confirmation)
    assert result.state == proto.REFUSED and calls == []


def test_spacy_is_only_acquired_as_approved_verified_artifact(authority_world):
    root, planner, state, calls, _, _ = authority_world
    state['spacy'] = proto.MISSING
    install_kokoro(root)
    confirmation = confirmed(planner, [proto.KOKORO])
    result = execute(authority_world, confirmation)
    assert result.state == proto.SUCCEEDED and calls == [assets.SPACY_WHEEL_URL], result
    assert 'installation remains deferred' in result.message
    assert result.transfer_state['actual']['spacy-english:' + assets.SPACY_WHEEL_SHA256] == assets.SPACY_WHEEL_SIZE


@pytest.mark.parametrize('changed', ['source', 'sha256', 'manifest', 'retry', 'forged'])
def test_forged_or_changed_v3_terms_never_spend(authority_world, changed):
    root, planner, _, calls, _, _ = authority_world
    confirmation = confirmed(planner, [proto.CHATTERBOX])
    terms = confirmation.plan.terms
    if changed == 'source':
        terms['artifacts'][0]['source']['url'] = terms['artifacts'][0]['source']['url'].replace('huggingface.co', 'evil.invalid')
    elif changed == 'sha256':
        terms['artifacts'][0]['sha256'] = '0' * 64
    elif changed == 'manifest':
        terms['manifest_sha256'] = '0' * 64
    elif changed == 'retry':
        terms['artifacts'][0]['retry_headroom_bytes'] = 1
        terms['artifacts'][0]['max_payload_bytes'] += 1
    if changed == 'forged':
        raw = json.loads(confirmation.raw_consent)
        raw['acquisition_fingerprint'] = '0' * 64
        raw = json.dumps(raw).encode()
    else:
        raw = v3.encode_consent(v3.new_consent(terms, session=confirmation.session, request_id=confirmation.request_id))
    result = execute(authority_world, dataclasses.replace(confirmation, raw_consent=raw))
    assert result.state == proto.REFUSED and not result.consent_spent and calls == []
    assert not (root / store.STORE).exists()


@pytest.mark.parametrize('readiness', [proto.UNVERIFIED, proto.BUSY, proto.UNSUPPORTED, proto.BAD_BUNDLE])
def test_non_authorizable_states_remain_distinct(authority_world, monkeypatch, readiness):
    root, planner, state, calls, _, _ = authority_world
    if readiness == proto.UNVERIFIED:
        state['health'][proto.CHATTERBOX] = None
        group = proto.CHATTERBOX
    else:
        group = proto.QWEN3_BASE
        if readiness == proto.BUSY:
            state['busy'] = (group,)
        elif readiness == proto.UNSUPPORTED:
            monkeypatch.setattr(rt, 'platform_supported', lambda: False)
        else:
            monkeypatch.setattr(rt, 'bundle_status', lambda: (False, 'damaged bundle'))
    plan = planner.plan([group])
    assert plan.terms is None and plan.to_json()['components'][0]['readiness'] == readiness
    assert calls == [] and not (root / store.STORE).exists()


def test_native_later_probe_failure_precedes_every_transfer(authority_world):
    from tts import optional_setup_authority as auth
    root, planner, _, calls, _, _ = authority_world
    confirmation = confirmed(planner, list(proto.COMPONENTS))
    original = planner.observer
    checked = 0

    def later_failure(selected, **kwargs):
        nonlocal checked
        checked += 1
        observation = original(selected, **kwargs)
        return dataclasses.replace(observation, engine=proto.UNVERIFIED) if checked > 1 else observation

    planner.observer = later_failure
    result = execute(authority_world, confirmation)
    assert result.state == proto.REFUSED and calls == []
    assert not (root / store.STORE).exists()


def test_lock_refusal_and_concurrent_installer_cannot_spend(authority_world):
    _, planner, _, calls, _, _ = authority_world
    confirmation = confirmed(planner, [proto.CHATTERBOX])
    results = []
    with su.InstallLock():
        t = threading.Thread(target=lambda: results.append(execute(authority_world, confirmation)))
        t.start()
        t.join(5)
        assert not t.is_alive()
    assert len(results) == 1 and results[0].state == proto.REFUSED
    assert not results[0].consent_spent and calls == []


def test_cancel_after_spend_is_terminal_and_replay_needs_new_confirmation(authority_world):
    root, planner, _, calls, _, _ = authority_world
    confirmation = confirmed(planner, [proto.CHATTERBOX])

    def cancelled():
        return (root / store.STORE / 'transfers').exists()

    result = execute(authority_world, confirmation, cancelled=cancelled)
    assert result.state == proto.CANCELLED and result.consent_spent and calls == []
    assert result.transfer_state['status'] == 'cancelled'
    replay = execute(authority_world, confirmation)
    assert replay.state == proto.REFUSED and calls == []
    fresh = confirmed(planner, [proto.CHATTERBOX])
    assert fresh.plan.to_json()['prior_state']['history']
    assert execute(authority_world, fresh).state == proto.SUCCEEDED


def test_failure_spends_reservation_no_retry_or_partial_credit_without_new_consent(authority_world):
    _, planner, _, calls, opener, _ = authority_world
    confirmation = confirmed(planner, [proto.CHATTERBOX])

    def broken(request, **kwargs):
        response = opener(request, **kwargs)
        response.truncate(1)
        return response

    result = planner.acquire_disposable(confirmation, opener=broken)
    assert result.state == proto.FAILED and result.consent_spent
    assert sum(result.transfer_state['actual'].values()) == 1
    assert sum(result.transfer_state['reserved'].values()) > 0
    count = len(calls)
    assert execute(authority_world, confirmation).state == proto.REFUSED and len(calls) == count
    fresh = confirmed(planner, [proto.CHATTERBOX])
    prior = fresh.plan.to_json()['prior_state']
    assert prior['history'] and all(p['verified_reuse_bytes'] == 0 for p in prior['partials'])
    assert execute(authority_world, fresh).state == proto.SUCCEEDED


def test_native_environment_boundary_is_guarded_and_scope_requires_held_lock(authority_world):
    class Authority:
        engine_action = 'none'

    with pytest.raises(su.SetupError, match='already-held'):
        with su.scoped_model_acquisition(Authority()):
            pytest.fail('entered without lock')
    with su.InstallLock(), su.scoped_model_acquisition(Authority()):
        with pytest.raises(su.SetupError, match='not authorized'):
            su.install_environment(rebuild=True, runner=lambda *a, **k: pytest.fail('real engine command'))


def test_default_sox_supply_still_blocks_explicit_engine_planning(authority_world):
    _, planner, state, calls, _, _ = authority_world
    state['engine'] = proto.DAMAGED
    plan = planner.plan([proto.QWEN3_CUSTOMVOICE], engine_action='rebuild-canonical')
    assert plan.terms is None and any('sox' in reason for reason in plan.to_json()['reasons'])
    assert calls == []


@pytest.mark.parametrize('action,engine', [('install-missing', proto.MISSING), ('rebuild-canonical', proto.DAMAGED)])
def test_explicit_engine_authority_is_validated_but_only_simulated(authority_world, monkeypatch, action, engine):
    """The package catalog is real; ONLY the sox store proof is a trusted synthetic stand-in.

    No derivative bytes are supplied/copied, no package is transferred, and native
    environment execution must still refuse even inside this explicit authority.
    """
    root, planner, state, calls, _, _ = authority_world
    planner.purpose = 'synthetic-qualification'
    state['engine'] = engine
    original_paths, original_verify = store.ArtifactStore._paths, store.ArtifactStore.verify
    original_exists = __import__('os').path.lexists

    def synthetic_paths(self, artifact_id):
        if artifact_id == 'qwen3-package:sox':
            return root / 'simulated-sox-proof.blob', root / 'simulated-sox-proof.json'
        return original_paths(self, artifact_id)

    def synthetic_verify(self, artifact_id):
        if artifact_id == 'qwen3-package:sox':
            row = self.catalog.artifact(artifact_id)
            return store.Verification('synthetic-proof-only', row['sha256'], row['size'])
        return original_verify(self, artifact_id)

    monkeypatch.setattr(store.ArtifactStore, '_paths', synthetic_paths)
    monkeypatch.setattr(store.ArtifactStore, 'verify', synthetic_verify)
    monkeypatch.setattr(__import__('os').path, 'lexists', lambda path: (
        True if Path(path).name.startswith('simulated-sox-proof.') else original_exists(path)))
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action=action)
    terms = confirmation.plan.terms
    assert terms['engine_action'] == action and terms['engine_readiness'] == engine
    assert len([a for a in terms['artifacts'] if a['kind'] == 'package']) == 89
    # Production execution is still deferred, and refuses before spending.
    refused = execute(authority_world, confirmation)
    assert refused.state == proto.REFUSED and not refused.consent_spent
    seen = []

    def simulate(authority):
        seen.append(authority)
        assert su.InstallLock.held_by_this_thread()
        with pytest.raises(su.SetupError, match='not authorized'):
            su.install_environment(rebuild=action == 'rebuild-canonical')

    result = execute(authority_world, confirmation, simulate_engine=simulate)
    assert result.state == proto.SUCCEEDED and result.consent_spent and seen == [terms], result
    assert calls == [] and not rt.nested_venv_dir().exists()


def test_changed_retry_policy_or_model_manifest_requires_new_confirmation(authority_world, monkeypatch):
    from tts import optional_setup_authority as auth
    _, planner, _, calls, _, _ = authority_world
    confirmation = confirmed(planner, [proto.CHATTERBOX])
    planner.retry_bytes = 10
    assert execute(authority_world, confirmation).state == proto.REFUSED and calls == []
    planner.retry_bytes = 0
    monkeypatch.setattr(auth, 'MODEL_IDENTITIES_SHA256', '0' * 64)
    assert execute(authority_world, confirmation).state == proto.REFUSED and calls == []


def test_safe_reduction_also_requires_confirmation(authority_world):
    root, planner, _, calls, _, _ = authority_world
    confirmation = confirmed(planner, [proto.CHATTERBOX])
    install_chatterbox(root)
    assert execute(authority_world, confirmation).state == proto.REFUSED and calls == []


def test_all_ready_is_no_operation_and_normal_planning_does_not_spend(authority_world):
    root, planner, _, calls, _, _ = authority_world
    install_chatterbox(root)
    plan = planner.plan([proto.CHATTERBOX])
    assert plan.to_json()['operations'] == {proto.CHATTERBOX: 'none'}
    assert plan.terms['artifacts'] == [] and plan.terms['payload']['max_payload_bytes'] == 0
    assert calls == [] and not (root / store.STORE).exists()


def test_shared_retry_policy_is_explicit_and_cannot_be_silently_increased(authority_world):
    _, planner, _, calls, _, _ = authority_world
    planner.retry_bytes, planner.shared_retry_bytes = 20, 7
    confirmation = confirmed(planner, [proto.CHATTERBOX])
    terms = confirmation.plan.terms
    assert terms['payload']['retry_headroom_bytes'] == 7
    assert all(a['retry_headroom_bytes'] == 20 for a in terms['artifacts'])
    planner.shared_retry_bytes = 8
    assert execute(authority_world, confirmation).state == proto.REFUSED and calls == []


def test_replayed_zero_transfer_consent_cannot_be_claimed_twice(authority_world):
    _, planner, _, calls, _, _ = authority_world
    confirmation = confirmed(planner, [proto.CHATTERBOX])
    first = execute(authority_world, confirmation)
    assert first.state == proto.SUCCEEDED
    # No state change may restore the spent token, including an all-ready replan.
    fresh_plan = planner.plan([proto.CHATTERBOX])
    raw = json.loads(confirmation.raw_consent)
    raw['terms'] = fresh_plan.terms
    raw['acquisition_fingerprint'] = v3.acquisition_fingerprint(fresh_plan.terms)
    replay = dataclasses.replace(confirmation, plan=fresh_plan, raw_consent=json.dumps(raw).encode())
    count = len(calls)
    result = execute(authority_world, replay)
    assert result.state == proto.REFUSED and len(calls) == count


@pytest.mark.parametrize('component', list(proto.COMPONENTS))
def test_every_component_source_is_independently_checked(authority_world, component):
    _, planner, state, calls, _, _ = authority_world
    if component == proto.KOKORO:
        state['spacy'] = proto.MISSING
    confirmation = confirmed(planner, [component])
    terms = confirmation.plan.terms
    for row in terms['artifacts']:
        assert row['source']['kind'] == 'pinned-https'
        assert row['source']['revision'] in row['source']['url'] or row['source']['revision'] == row['sha256']
    altered = terms['artifacts'][-1]
    altered['source']['url'] = altered['source']['url'].replace('https://', 'https://other.invalid/')
    consent = v3.new_consent(terms, session=confirmation.session, request_id=confirmation.request_id)
    result = execute(authority_world, dataclasses.replace(confirmation, raw_consent=v3.encode_consent(consent)))
    assert result.state == proto.REFUSED and not result.consent_spent and calls == []


@pytest.mark.parametrize('phase', ['initial', 'reservation', 'settlement'])
def test_journal_publication_failure_still_returns_one_terminal_result(authority_world, monkeypatch, phase):
    _, planner, _, calls, _, _ = authority_world
    confirmation = confirmed(planner, [proto.CHATTERBOX])
    original = transfer.write_once

    def fail(repo, path, data):
        matches = {'initial': 'initial.json', 'reservation': '00000000.json', 'settlement': '00000001.json'}
        if path.name == matches[phase]:
            raise OSError('injected journal publication failure')
        return original(repo, path, data)

    monkeypatch.setattr(transfer, 'write_once', fail)
    result = execute(authority_world, confirmation)
    assert result.state == proto.FAILED and result.consent_spent, result
    assert len(calls) == (1 if phase == 'settlement' else 0)
    # An uncertain claim cannot be silently reset, spent or resumed.
    assert execute(authority_world, confirmation).state == proto.REFUSED


def test_native_file_boundary_does_not_fall_back_to_unbudgeted_download(authority_world, monkeypatch):
    """Change content AFTER final validation too: native reuse guard must refuse.

    This specifically exercises the installer callback after ledger spending,
    independently of the earlier plan comparison and production-disable gate.
    """
    root, planner, _, calls, _, _ = authority_world
    install_model(root, 'customvoice', marker=False)
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE])
    native = su.install_model

    def changed_at_native(key, **kwargs):
        target = rt.model_spec(key).directory / 'model.safetensors'
        target.write_bytes(b'x' * target.stat().st_size)
        return native(key, **kwargs)

    monkeypatch.setattr(su, 'install_model', changed_at_native)
    result = execute(authority_world, confirmation)
    assert result.state == proto.FAILED and result.consent_spent and calls == []
    assert 'reused model changed' in result.message
    assert not rt.marker_path('customvoice').exists()


@pytest.mark.parametrize('marker', [False, True])
def test_legacy_plan_install_also_hashes_before_claiming_reuse(authority_world, marker):
    root, _, _, calls, _, _ = authority_world
    install_model(root, 'customvoice', marker=marker, corrupt='model.safetensors')
    plan = su.plan_install(['customvoice'])
    assert plan.models[0].download_bytes == len(CUSTOM_ONLY['model.safetensors'])
    assert not plan.models[0].installed and not plan.nothing_to_do
    assert calls == []


def test_authorized_combined_kokoro_chatterbox_request(authority_world):
    _, planner, _, calls, _, _ = authority_world
    confirmation = confirmed(planner, [proto.KOKORO, proto.CHATTERBOX])
    result = execute(authority_world, confirmation)
    assert result.state == proto.SUCCEEDED, result
    assert len(calls) == len(confirmation.plan.terms['artifacts'])
    assert sum(result.transfer_state['actual'].values()) == confirmation.plan.terms['payload']['expected_new_bytes']
    for group in (assets.kokoro_set(), assets.chatterbox_set()):
        assert all(assets.file_state(group, name)[0] == proto.READY for name in group.files)


def test_absent_package_receipt_does_not_change_healthy_engine_identity(authority_world, monkeypatch):
    root, planner, _, calls, _, _ = authority_world
    install_environment(root, requirements=(root / 'scripts/qwen3-requirements.txt').read_text())
    install_model(root, 'customvoice', marker=False)
    before = {p: p.read_bytes() for p in rt.venv_dir().rglob('*') if p.is_file()}
    state_before = rt.state_path().read_bytes()
    monkeypatch.setattr(su, 'run_command', lambda *a, **k: pytest.fail('unconsented engine/package command'))
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE])
    assert confirmation.plan.terms['engine_action'] == 'none'
    assert execute(authority_world, confirmation).state == proto.SUCCEEDED and calls == []
    assert before == {p: p.read_bytes() for p in rt.venv_dir().rglob('*') if p.is_file()}
    assert rt.state_path().read_bytes() == state_before


@pytest.mark.parametrize('held', [False, True])
def test_default_observer_reuses_probe_lease_and_keeps_inconclusive_health_unverified(authority_world, monkeypatch, held):
    from tts import optional_setup_authority as auth
    from tts import optional_setup_health as health
    from tts import optional_setup as old_plan
    monkeypatch.setattr(health, 'local_health', lambda *a, **k: {})
    monkeypatch.setattr(health, 'busy_components', lambda c: frozenset())
    monkeypatch.setattr(old_plan, '_qwen_engine_unit', lambda: (SimpleNamespace(state=proto.READY), ''))
    seen = []

    def probe(**kwargs):
        seen.append(su.InstallLock.held_by_this_thread())
        raise su.SetupError('inconclusive probe')

    monkeypatch.setattr(su, 'probe_environment', probe)
    if held:
        with su.InstallLock():
            observed = auth.observe((proto.QWEN3_CUSTOMVOICE,), locked=True, cancelled=lambda: False)
    else:
        observed = auth.observe((proto.QWEN3_CUSTOMVOICE,), locked=False, cancelled=lambda: False)
    assert observed.engine == proto.UNVERIFIED and seen == [True]
    assert not su.InstallLock.held_by_this_thread()


def test_default_observer_reports_busy_without_starting_a_probe(authority_world, monkeypatch):
    from tts import optional_setup_authority as auth
    from tts import optional_setup_health as health
    from tts import optional_setup as old_plan
    monkeypatch.setattr(health, 'local_health', lambda *a, **k: {})
    monkeypatch.setattr(health, 'busy_components', lambda c: frozenset(c))
    monkeypatch.setattr(old_plan, '_qwen_engine_unit', lambda: (SimpleNamespace(state=proto.READY), ''))
    monkeypatch.setattr(su, 'probe_environment', lambda **k: pytest.fail('busy engine must not be probed'))
    observed = auth.observe((proto.QWEN3_CUSTOMVOICE,), locked=False, cancelled=lambda: False)
    assert observed.engine == proto.BUSY
