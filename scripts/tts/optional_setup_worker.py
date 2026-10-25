"""optional_setup_worker.py — the optional-voice setup worker, run in the app's verified environment.

Started only through ``shared.optional_setup_protocol.worker_launch``, as::

    <repo>/.venv/Scripts/python.exe -E -s -m tts.optional_setup_worker --request R --result S --session T

with ``scripts/`` as its working folder (v0.7.0 P05A, plan Revision 2 §5.4 execution home). It reads one request, checks
it completely (containment, schema, session, freshness, consent) and checks that it is itself running in the app's own
CPython 3.12 environment; then it reports readiness and the plan as progress events and publishes exactly one terminal
result. A cancel flag in the request's folder is honoured at every checkpoint.

Every request is answered through ``tts.optional_setup_lifecycle.Operation`` (fresh plan, consent check against it,
the consent spent once, acquisition, post-install proof). Since P05B Stage 2 the facts the plan needs are this
computer's own (``tts.optional_setup_health``: bounded offline Kokoro/Chatterbox probes, held locks), the acquirer is
``tts.optional_setup_acquire.RealAcquirer`` -- which acts only for a consent that covers the fresh plan and has just
been spent -- and the post-install proof is a fresh probe. A second worker started on a request that already has one
refuses to run.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional

from shared import optional_setup_protocol as proto
from tts import optional_setup
from tts import optional_setup_health
from tts import optional_setup_lifecycle as lifecycle
from tts import qwen3_runtime as rt


def run(request: proto.Request, *, emit: Callable[[str, dict], None], cancel_check: Callable[[], bool],
        facts: Optional[optional_setup.Facts] = None, acquirer: Optional[lifecycle.Acquirer] = None,
        health: Optional[Callable[[tuple], Mapping]] = None, claim: Optional[Callable[[str], bool]] = None,
        probe_runner: Optional[Callable[..., int]] = None) -> dict:
    """Answer *request* (already validated); return its terminal result. Never raises for an expected outcome.

    Without *facts* this computer's are gathered (probes and locks) when the plan is first made -- after ``started``
    is reported, under the same cancellation. Without *acquirer* the real one is used; without *health* the
    post-install proof is a fresh probe."""
    root = rt.repo_root()
    known: dict = {}

    def base_facts() -> optional_setup.Facts:
        if "facts" not in known:
            known["facts"] = facts or optional_setup_health.facts(
                root, request.components, probe_hardware=request.probe_hardware, cancel_check=cancel_check,
                runner=probe_runner)
        return known["facts"]

    def planner(health_facts: Optional[Mapping]) -> dict:
        # After acquiring, the proof made then replaces whatever was known about health before.
        current = base_facts() if health_facts is None else dataclasses.replace(base_facts(), health=dict(health_facts))
        return optional_setup.plan_to_json(optional_setup.plan(request.components, facts=current))

    def estimator() -> dict:  # the first-run estimate for the same choices, reproduced here (it is deterministic)
        return optional_setup.plan_to_json(optional_setup.estimate(
            request.components, facts=optional_setup.Facts(is_64bit=base_facts().is_64bit)))

    def proof(components: tuple) -> Mapping:
        if health is not None:
            return health(components)
        return optional_setup_health.local_health(root, components, cancel_check=cancel_check, runner=probe_runner)

    if acquirer is None:
        from tts import optional_setup_acquire

        acquirer = optional_setup_acquire.RealAcquirer()
    return lifecycle.Operation(request, planner=planner, estimator=estimator, emit=emit, cancel_check=cancel_check,
                               acquirer=acquirer, health=proof, claim=claim).run()


def _publish(result_path: Path, result: dict) -> int:
    try:
        data = proto.encode(result)
    except proto.ProtocolError:  # a plan too large to report is reported as a failure, without the plan
        result = proto.make_result(result["request_id"], proto.FAILED,
                                   error=(proto.INTERNAL, "The plan was too large to report."))
        data = proto.encode(result)
    try:
        proto.publish_once(result_path, data)
    except proto.ProtocolError as exc:  # no atomic publication here: nothing is published rather than half of it
        print(f"optional_setup_worker: {exc}", file=sys.stderr)
        return proto.EXIT_NO_RESULT
    return proto.EXIT_CODES[result["state"]]


def main(argv: Optional[list[str]] = None, *, repo_root: Optional[Path] = None,
         home_check: Callable[[Path], str] = proto.execution_home_problem,
         facts: Optional[optional_setup.Facts] = None, acquirer: Optional[lifecycle.Acquirer] = None,
         health: Optional[Callable[[tuple], Mapping]] = None) -> int:
    parser = argparse.ArgumentParser(prog="optional_setup_worker", allow_abbrev=False)
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--session", required=True)
    args = parser.parse_args(argv)  # a usage error exits 2 (EXIT_NO_RESULT) before any result could be written
    root = rt.repo_root() if repo_root is None else Path(repo_root)

    try:
        result_path, request_id = proto.check_exchange_path(root, args.result, proto.RESULT_NAME)
    except proto.ProtocolError as exc:
        print(f"optional_setup_worker: refusing the result path: {exc}", file=sys.stderr)
        return proto.EXIT_NO_RESULT
    if os.path.lexists(result_path):
        print("optional_setup_worker: this request was already answered; it is not run again", file=sys.stderr)
        return proto.EXIT_NO_RESULT
    try:
        if not proto.claim_request(root, request_id):
            print("optional_setup_worker: another worker is answering this request; it is not run twice",
                  file=sys.stderr)
            return proto.EXIT_NO_RESULT
    except proto.ProtocolError as exc:
        print(f"optional_setup_worker: refusing the request folder: {exc}", file=sys.stderr)
        return proto.EXIT_NO_RESULT

    seq = iter(range(1 << 30))

    def emit(kind: str, payload: dict) -> None:
        print(proto.encode_event(request_id, next(seq), kind, payload), flush=True)

    try:
        request_path, named_id = proto.check_exchange_path(root, args.request, proto.REQUEST_NAME)
        if named_id != request_id:
            raise proto.ProtocolError(proto.UNSAFE_PATH, "the request and result are not in the same request folder")
        request = proto.decode_request(proto.read_message_file(request_path), session=args.session)
        if request.request_id != request_id:
            raise proto.ProtocolError(proto.MALFORMED, "the request id does not match its folder")
        home = home_check(root)
        if home:
            raise proto.ProtocolError(proto.WRONG_INTERPRETER, home)
        result = run(request, emit=emit, cancel_check=lambda: proto.cancel_requested(root, request_id), facts=facts,
                     acquirer=acquirer, health=health,
                     claim=lambda consent_id: proto.claim_consent(root, consent_id, request_id))
    except proto.ProtocolError as exc:
        result = proto.make_result(request_id, proto.REFUSED, error=(exc.code, str(exc)))
    except Exception as exc:  # noqa: BLE001 - the one terminal result must still be written
        result = proto.make_result(request_id, proto.FAILED,
                                   error=(proto.INTERNAL, f"{type(exc).__name__}: {exc}"))
    return _publish(result_path, result)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # -E ignores PYTHONIOENCODING; events are ASCII, messages may not be
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
