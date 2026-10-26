"""Stage 4B-1: production install requests stop before the real acquirer exists."""
import pytest

from shared import optional_setup_protocol as proto
from tts import optional_setup as osu
from tts import optional_setup_acquire as acquire
from tts import optional_setup_health as health
from test_optional_tts_setup import (K, SESSION, facts, run_main, sandbox, tiny_assets, world)

pytestmark = pytest.mark.usefixtures('production_writes_refused')


@pytest.mark.parametrize('scope', ['install', 'repair'])
def test_production_worker_refuses_valid_legacy_consent_before_acquirer(world, monkeypatch, scope):
    current = facts(health={K: scope != 'repair'}, spacy=True)
    shown = osu.plan_to_json(osu.plan([K], facts=current))
    # Missing assets yield install; a damaged engine proof yields repair.
    consent = osu.consent_for(shown)
    assert consent.scopes[K] == scope
    request = proto.new_request(proto.ACTION_INSTALL, [K], session=SESSION, consent=consent)

    def forbidden(*args, **kwargs):
        pytest.fail('production acquisition or probe started')

    monkeypatch.setattr(acquire, 'RealAcquirer', forbidden)
    code, result = run_main(world, request, facts=current, health=forbidden)
    assert code == proto.EXIT_CODES[proto.REFUSED]
    assert result['state'] == proto.REFUSED
    assert result['error']['code'] == proto.ACQUISITION_UNAVAILABLE
    assert 'temporarily disabled' in result['error']['message']
    assert not list((world / 'files/runtime-data/optional-setup').glob('consents/*'))


@pytest.mark.parametrize('component', proto.COMPONENTS)
def test_production_gate_never_gathers_facts_or_spends_consent(world, monkeypatch, component):
    shown = osu.plan_to_json(osu.plan([component], facts=facts(health={component: True}, spacy=True)))
    request = proto.new_request(proto.ACTION_INSTALL, [component], session=SESSION, consent=osu.consent_for(shown))

    def forbidden(*args, **kwargs):
        pytest.fail('production gate reached a probe, acquisition, or consent-spending seam')

    monkeypatch.setattr(health, 'facts', forbidden)
    monkeypatch.setattr(acquire, 'RealAcquirer', forbidden)
    monkeypatch.setattr(proto, 'claim_consent', forbidden)
    _, result = run_main(world, request)
    assert result['state'] == proto.REFUSED
    assert result['error']['code'] == proto.ACQUISITION_UNAVAILABLE
