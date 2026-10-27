"""Read-only v3 Planner worker; production entry is deliberately disabled.

Only an explicitly injected disposable-code context can run. Request bytes never
choose the repository, observer, interpreter, executable, destination or adapter.
There is no confirmation, installer, consent, ledger-begin or acquirer call path.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from shared import optional_setup_exchange_v3 as exchange
from shared import optional_setup_protocol as proto
from shared import optional_setup_wire_v3 as wire
from tts import optional_setup_authority as authority
from tts import qwen3_setup as setup


@dataclass(frozen=True)
class DisposablePlanningContext:
    """Trusted Python fixture injection only. No JSON or production issuer."""
    planner: authority.Planner
    cancelled: object = lambda: False


def _fixture_root():
    root = Path(__file__).absolute().parents[2]
    # Code location, NEVER a caller/request root. Parent independently pins it.
    parts = root.parts
    marker = ('files', 'dev-work', 'p05b-stage4c')
    indices = [i for i in range(len(parts) - 3) if parts[i:i + 3] == marker]
    exchange._require(len(indices) == 1 and parts[indices[0] + 3].startswith('stage4d2d-')
        and root.name == 'app' and Path.cwd() == root / 'scripts', 'disposable code origin required')
    for path in (root, *root.parents):
        exchange._require(not path.lstat().st_file_attributes & 0x400, 'worker reparse ancestry')
    return root


def main(argv=None, *, context=None):
    """No context => no planning, paths, writes, observation or launch."""
    if type(context) is not DisposablePlanningContext or type(context.planner) is not authority.Planner:
        return 2
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        return 2
    request_id, session = args
    seq = 0

    def emit(phase):
        nonlocal seq
        print(json.dumps(dict(protocol='act-proposed-read-only-planning-event', version=3,
            request_id=request_id, session=session, seq=seq, kind='progress', phase=phase)), flush=True)
        seq += 1

    try:
        root = _fixture_root()
        planning = exchange._read_published_planning_request(root, session=session, request_id=request_id)
        request = planning.to_json()
        emit('starting')
        emit('planning')
        # Actual reviewed Planner owns all decisions, limits and fail-closed fallback.
        # Parent cancellation kills the contained job; adapters can also supply
        # a cooperative cancellation check to this exact Planner entry.
        plan = context.planner.plan(request['components'], engine_action=request['engine_action'],
                                    cancelled=context.cancelled)
        raw = wire.encode_disclosure(plan._document, planning=planning, issued_utc=proto.utc_text(time.time()))
        disclosure = wire.decode_disclosure(raw, planning=planning, session=session)
        result = wire.encode_planning_result(disclosure=disclosure, issued_utc=proto.utc_text(time.time()))
        exchange.publish_planning_response(root, planning=planning, disclosure=disclosure,
            raw_result=result, session=session)
        emit('published')
        return 0
    except setup.SetupCancelled:
        # No forged Plan/second publication: supervisor separately arbitrates.
        return 3
    except Exception:
        # Bounded failure, no exception strings/path/metadata dump on the wire.
        return 2


if __name__ == '__main__':
    sys.exit(main())
