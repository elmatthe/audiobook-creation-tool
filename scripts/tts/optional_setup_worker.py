"""optional_setup_worker.py — the optional-voice setup worker, run in the app's verified environment.

Started only through ``shared.optional_setup_protocol.worker_launch``, as::

    <repo>/.venv/Scripts/python.exe -E -s -m tts.optional_setup_worker --request R --result S --session T

with ``scripts/`` as its working folder (v0.7.0 P05A, plan Revision 2 §5.4 execution home). It reads one request, checks
it completely (containment, schema, session, freshness, consent) and checks that it is itself running in the app's own
CPython 3.12 environment; then it reports readiness and the plan as progress events and publishes exactly one terminal
result. A cancel flag in the request's folder is honoured at every checkpoint.

This build answers ``plan`` requests and refuses ``install`` requests without acquiring anything (``acquisition-
unavailable``), after checking the consent still covers the current plan. Installing is P05B.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from shared import optional_setup_protocol as proto
from tts import optional_setup
from tts import qwen3_runtime as rt


class _Cancelled(Exception):
    pass


def run(request: proto.Request, *, emit: Callable[[str, dict], None], cancel_check: Callable[[], bool],
        facts: Optional[optional_setup.Facts] = None) -> dict:
    """Answer *request* (already validated); return its terminal result. Never raises for an expected outcome."""

    def checkpoint() -> None:
        if cancel_check():
            raise _Cancelled()

    try:
        emit("started", {"action": request.action, "components": list(request.components)})
        checkpoint()
        facts = facts or optional_setup.Facts(probe_hardware=request.probe_hardware)
        data = optional_setup.plan_to_json(optional_setup.plan(request.components, facts=facts))
        checkpoint()
        emit("readiness", {c["id"]: c["readiness"] for c in data["components"] if c["selected"]})
        emit("plan", {"fingerprint": data["fingerprint"], "download": data["totals"]["download"],
                      "acquire_units": data["acquire_units"]})
        checkpoint()
    except _Cancelled:
        return proto.make_result(request.request_id, proto.CANCELLED_STATE,
                                 error=(proto.CANCELLED, "Cancelled. Nothing was downloaded or changed."))
    if request.action == proto.ACTION_PLAN:
        return proto.make_result(request.request_id, proto.SUCCEEDED, plan=data)
    covered, why = proto.consent_covers(request.consent, data)
    if not covered:
        return proto.make_result(request.request_id, proto.REFUSED, plan=data,
                                 error=(proto.CONSENT_STALE, f"The plan changed since it was confirmed: {why}. "
                                                             "Nothing was downloaded; confirm the new plan to continue."))
    return proto.make_result(request.request_id, proto.REFUSED, plan=data,
                             error=(proto.ACQUISITION_UNAVAILABLE, "Installing optional voices is not part of this "
                                                                   "build yet. Nothing was downloaded or changed."))


def _publish(result_path: Path, result: dict) -> int:
    try:
        data = proto.encode(result)
    except proto.ProtocolError:  # a plan too large to report is reported as a failure, without the plan
        result = proto.make_result(result["request_id"], proto.FAILED,
                                   error=(proto.INTERNAL, "The plan was too large to report."))
        data = proto.encode(result)
    proto.publish_once(result_path, data)
    return proto.EXIT_CODES[result["state"]]


def main(argv: Optional[list[str]] = None, *, repo_root: Optional[Path] = None,
         home_check: Callable[[Path], str] = proto.execution_home_problem,
         facts: Optional[optional_setup.Facts] = None) -> int:
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
        result = run(request, emit=emit, cancel_check=lambda: proto.cancel_requested(root, request_id), facts=facts)
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
