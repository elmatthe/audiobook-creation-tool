"""v0.7.0 release: the production worker installs through the real acquirer -- only after the consent check.

Stage 4B-1 refused every production install request while the v2 acquirer had open consent-scope defects. Those are
closed in ``tts.optional_setup_acquire`` (byte budget fixed by the consent, engine scope), so an install request
without an injected acquirer now reaches ``RealAcquirer`` -- but only once the worker's own fresh plan was proved to
match the consent and the consent was spent. A forged or altered consent still never reaches it.
"""
import dataclasses

import pytest

from shared import optional_setup_protocol as proto
from tts import optional_setup as osu
from tts import optional_setup_acquire as acquire
from tts.optional_setup_lifecycle import AcquisitionReport
from test_optional_tts_setup import (K, SESSION, facts, run_main, sandbox, tiny_assets, world)  # noqa: F401

pytestmark = pytest.mark.usefixtures('production_writes_refused')


class _Recorder:
    """Stands in for RealAcquirer: records that it was built and asked, acquires nothing."""

    made: list = []

    def __init__(self):
        type(self).made.append(self)
        self.calls = []

    available = True

    def acquire(self, plan, consent, *, progress, cancel_check):
        self.calls.append((plan["acquisition_fingerprint"], consent.consent_id))
        return AcquisitionReport(False, (), "recorder: nothing acquired")


@pytest.fixture
def recorder(monkeypatch):
    _Recorder.made = []
    monkeypatch.setattr(acquire, 'RealAcquirer', _Recorder)
    return _Recorder


def test_a_valid_consent_reaches_the_production_acquirer_after_it_is_spent(world, recorder):
    current = facts(health={K: True}, spacy=True)
    shown = osu.plan_to_json(osu.plan([K], facts=current))
    consent = osu.consent_for(shown)
    request = proto.new_request(proto.ACTION_INSTALL, [K], session=SESSION, consent=consent)
    _code, result = run_main(world, request, facts=current, health=lambda c: {})
    assert len(recorder.made) == 1 and recorder.made[0].calls == [(shown["acquisition_fingerprint"],
                                                                    consent.consent_id)]
    assert result['state'] == proto.FAILED and result['verified'] == []  # nothing acquired, nothing claimed
    assert list((world / 'files/runtime-data/optional-setup').glob('consents/*'))  # spent exactly once


def test_an_altered_consent_never_reaches_the_production_acquirer(world, recorder):
    current = facts(health={K: True}, spacy=True)
    consent = osu.consent_for(osu.plan_to_json(osu.plan([K], facts=current)))
    smaller = dataclasses.replace(consent, download_bytes=consent.download_bytes - 1)
    request = proto.new_request(proto.ACTION_INSTALL, [K], session=SESSION, consent=smaller)
    _code, result = run_main(world, request, facts=current, health=lambda c: {})
    assert result['state'] == proto.REFUSED and result['error']['code'] == proto.BAD_CONSENT
    assert all(not made.calls for made in recorder.made)
    assert not list((world / 'files/runtime-data/optional-setup').glob('consents/*'))


def test_a_plan_request_never_builds_an_acquirer(world, recorder):
    request = proto.new_request(proto.ACTION_PLAN, [K], session=SESSION)
    _code, result = run_main(world, request, facts=facts(health={K: True}, spacy=True))
    assert result['state'] == proto.SUCCEEDED and recorder.made == []
