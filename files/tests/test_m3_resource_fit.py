"""Measure complete representative disclosures without changing accepted limits."""
import copy
import hashlib
import json
import time

import pytest

from shared import artifact_store as store
from shared import optional_setup_protocol as proto
from shared import optional_setup_resource_budget as rb
from shared import optional_setup_wire_v3 as wire
from test_optional_setup_wire_v3 import document, planning, disclosure, NOW, SESSION

pytestmark = pytest.mark.usefixtures('production_writes_refused')


def representative(histories, entries, artifacts=90):
    doc = document()
    ids = ['qwen3-package:' + str(i).zfill(3) for i in range(artifacts)]
    for index in range(histories):
        actual = {aid: 1000 + i for i, aid in enumerate(ids)}
        reserved = {aid: i for i, aid in enumerate(ids)}
        doc['prior_state']['history'].append({'consent_id': f'{index:032x}', 'session': 'd' * 32,
            'fingerprint': 'a' * 64, 'chain': hashlib.sha256(str(index).encode()).hexdigest(),
            'sequence': 4096 // max(1, histories),
            'state': {'status': 'spent', 'actual': actual, 'reserved': reserved}})
    doc['engine_identity'] = {'parent': [1, 2], 'parent_cfg': 'a' * 64, 'canonical_exists': True,
        'selected_canonical': True, 'path': 'disposable/.venv/engines/qwen3', 'record': {'future': ['retained']},
        'entries': [[f'Lib/site-packages/package_{i:04d}/module.py', [1, i + 1, 100, 1234567890, 1234567890]]
                    for i in range(entries)]}
    doc['future_metadata'] = {'unknown': {'nested': [True, 3, 'preserved verbatim']}}
    return doc


@pytest.mark.parametrize('histories,entries', [(0, 0), (2, 128), (16, 1024), (32, 0), (0, 8192), (32, 8192)])
def test_measure_complete_history_inventory_and_wire_fit(tmp_path, histories, entries):
    doc = representative(histories, entries)
    before = copy.deepcopy(doc)
    budget = rb.Budget()
    started = time.perf_counter()
    raw = budget.encode(doc)
    encoded_seconds = time.perf_counter() - started
    assert raw == store.canonical(doc) and budget.used_bytes == len(raw)
    try:
        shown = disclosure(doc)
    except proto.ProtocolError as exc:
        assert exc.code == wire.RESOURCE_LIMIT
        fit, size, decode_seconds = False, None, None
    else:
        started = time.perf_counter()
        decoded = wire.decode_disclosure(shown.raw, planning=planning(), session=SESSION, now=lambda: NOW)
        decode_seconds = time.perf_counter() - started
        assert decoded.document == raw
        assert decoded.to_json()['document'] == before
        fit, size = True, len(shown.raw)
    assert doc == before  # refusal never prunes/reorders or alters original metadata
    measurement = {'histories': histories, 'inventory_entries': entries, 'historical_artifact_maps': 90,
        'plan_bytes': len(raw), 'metadata_encoding_charge': budget.used_bytes, 'disclosure_bytes': size,
        'wire_fits': fit, 'encode_seconds': encoded_seconds, 'decode_seconds': decode_seconds}
    print('M3 RESOURCE ' + json.dumps(measurement, sort_keys=True))
    (tmp_path / 'measurement.json').write_text(json.dumps(measurement, indent=2))
    assert fit is (entries < 8192)


def test_content_hashing_is_excluded_without_resetting_metadata_budget():
    now = [0.0]
    budget = rb.Budget(clock=lambda: now[0])
    budget.charge(100)
    with budget.content():
        now[0] = 3600
    budget.check()
    assert budget.used_bytes == 100
    now[0] += 30.001
    with pytest.raises(rb.ResourceLimit, match='deadline'):
        budget.check()
