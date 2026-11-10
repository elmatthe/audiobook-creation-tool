#!/usr/bin/env python3
"""Runs the registered native and real-media journeys, one owned application at a time. verify.py starts this under its own job.

It writes ``reports/acceptance.json`` whatever happens to a scenario, and the gate reads that report, never this process's word. What a
scenario's end means:

    OracleFailure, a wrong output, an unexpected state     FAIL
    InputRefused, a target that could not honestly be hit  FAIL
    DesktopUnavailable, ForegroundLost, ToolchainUnavailable  BLOCKED: no native evidence exists, so it is not a pass and not a product failure
    ContainmentUnavailable                                 BLOCKED: the owner's dialog history could not be shown to be protected
    FixtureInvalid                                         FAIL, marked as infrastructure: the application never saw the input

Before any scenario, ``containment.preflight`` must show that the application, started as every session starts it, cannot write the
owner's Windows dialog history; otherwise nothing runs and the stage is BLOCKED. The history is read (never written) before and after,
and the report carries both so the gate can see that nothing naming the gate's scratch was added.

A scenario's folder stays in the run. On failure its outputs are copied in too (within a limit), and whatever is left of its process tree
is ended by its own job. Nothing here is a retry: the first result stands.

Usage: acceptance_runner.py --report <file> --token <run token> --evidence <dir> --scratch <dir> [--only <id> ...] [--list]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

GATE_DIR = Path(__file__).resolve().parent
REPO_ROOT = GATE_DIR.parents[2]
sys.path.insert(0, str(GATE_DIR))

SCHEMA_VERSION = 1
FAILED_OUTPUT_LIMIT = 32 << 20
MODULES = ("journeys.controls", "journeys.launcher", "journeys.cover", "journeys.mp3", "journeys.converter", "journeys.maker",
           "journeys.metadata", "journeys.tts", "journeys.shutdown", "journeys.inventory", "journeys.setup")


def load_scenarios() -> dict:
    import importlib

    for module in MODULES:
        importlib.import_module(module)
    from journeys.common import SCENARIOS

    return SCENARIOS


def _copy_failed_outputs(work: Path, destination: Path) -> dict:
    copied = skipped = total = 0
    root = work / "out"
    if not root.is_dir():
        return {"copied": 0, "skipped": 0}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        relative = Path(dirpath).relative_to(root)
        for name in filenames:
            source = Path(dirpath) / name
            size = source.stat().st_size
            if total + size > FAILED_OUTPUT_LIMIT:
                skipped += 1
                continue
            (destination / relative).mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination / relative / name)
            copied += 1
            total += size
    return {"copied": copied, "skipped": skipped, "bytes": total}


def _keep_app_logs(session, evidence: Path) -> None:
    logs = session.work / "runtime" / "logs"
    if logs.is_dir():
        for item in logs.iterdir():
            if item.is_file() and item.stat().st_size < (8 << 20):
                shutil.copy2(item, evidence / f"{session.name}-applog-{item.name}")


def run_one(scenario, *, evidence_root: Path, scratch_root: Path, tools, manifest, index: int) -> dict:
    from adapters.windows import containment, native_input as native
    from helpers import media_fixtures, media_oracle as oracle
    from journeys.common import Context, JourneyTimeout

    evidence = evidence_root / scenario.id
    evidence.mkdir(parents=True)
    if scenario.applicable is not None:
        applicable, why = scenario.applicable()
        if not applicable:
            return {"id": scenario.id, "tool": scenario.tool, "layers": list(scenario.layers), "tier": scenario.tier, "summary": scenario.summary,
                    "status": "NOT APPLICABLE", "reason": why, "seconds": 0.0, "checks": [], "outputs": [], "fixtures": [], "screenshots": [],
                    "notes": {"applicability": why}, "teardown": [], "native_inputs": 0, "sessions": []}
        applicability = why
    else:
        applicability = None
    # Short on purpose: application outputs and the Windows dialog both live below this.
    work = scratch_root / f"s{index:02d}"
    work.mkdir(parents=True)
    # The application runs at Low integrity and may write only below a Low-labelled folder: its outputs, inputs and sessions are all here.
    containment.label_low(work)
    fixtures = media_fixtures.FixtureSet(tools, manifest, work / "in")
    context = Context(scenario.id, evidence, work, tools, fixtures)
    began = time.monotonic()
    entry = {"id": scenario.id, "tool": scenario.tool, "layers": list(scenario.layers), "tier": scenario.tier, "summary": scenario.summary,
             "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "status": "NOT RUN", "reason": ""}
    try:
        scenario.run(context)
        failed = context.report.failed
        entry["status"] = "FAIL" if failed else "PASS"
        entry["reason"] = "; ".join(f"{item['name']}: {item['detail']}" for item in failed)[:1500]
    except (native.DesktopUnavailable, containment.ContainmentUnavailable) as exc:
        entry.update(status="BLOCKED", reason=f"{type(exc).__name__}: {exc}")
    except oracle.ToolchainUnavailable as exc:
        entry.update(status="BLOCKED", reason=f"ToolchainUnavailable: {exc}")
    except oracle.FixtureInvalid as exc:
        entry.update(status="FAIL", reason=f"infrastructure, the application never saw this input: {exc}", infrastructure=True)
    except (oracle.OracleFailure, native.InputRefused, JourneyTimeout, AssertionError) as exc:
        entry.update(status="FAIL", reason=f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 - a journey that broke is a failure with a traceback, never a quiet absence
        entry.update(status="FAIL", reason=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc()[-3000:])
    if entry["status"] != "PASS":
        for session in context.sessions:
            try:
                if session.client is not None and session.hwnd:
                    session.screenshot("at-failure")
            except Exception as exc:  # noqa: BLE001 - evidence of a failure must not replace it
                entry.setdefault("evidence_problems", []).append(f"screenshot: {type(exc).__name__}: {exc}")
    teardown = []
    for session in context.sessions:
        facts = session.tear_down()
        teardown.append({"session": session.name, **facts})
        _keep_app_logs(session, evidence)
    survivors = [item for item in teardown if item.get("survivors")]
    if survivors and entry["status"] == "PASS":
        entry.update(status="FAIL", reason=f"owned processes survived tear-down: {survivors}")
    if entry["status"] != "PASS":
        entry["failed_outputs"] = _copy_failed_outputs(work, evidence / "failed-outputs")
    entry.update(seconds=round(time.monotonic() - began, 3), checks=context.report.checks, outputs=context.report.outputs,
                 fixtures=fixtures.records(), notes={**context.notes, **({"applicability": applicability} if applicability else {})}, teardown=teardown,
                 native_inputs=sum(session.input_count for session in context.sessions),
                 screenshots=[{**shot, "path": f"{scenario.id}/screenshots/{shot['name']}"} for session in context.sessions for shot in session.shots],
                 sessions=[session.name for session in context.sessions])
    return entry


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report")
    parser.add_argument("--token")
    parser.add_argument("--evidence")
    parser.add_argument("--scratch")
    parser.add_argument("--only", action="append")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    scenarios = load_scenarios()
    if args.list:
        print(json.dumps({key: {"tool": item.tool, "layers": item.layers, "tier": item.tier, "summary": item.summary}
                          for key, item in scenarios.items()}, indent=1))
        return 0
    from adapters.windows import containment, native_input as native
    from helpers import media_fixtures, media_oracle as oracle, scratch as scratch_store

    native.set_dpi_aware()
    evidence, scratch, report_path = Path(args.evidence), Path(args.scratch), Path(args.report)
    evidence.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    wanted = list(args.only) if args.only else list(scenarios)
    unknown = [item for item in wanted if item not in scenarios]
    report = {"schema_version": SCHEMA_VERSION, "token": args.token, "pid": os.getpid(), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "requested": wanted, "registered": list(scenarios), "scenarios": [], "finished": False, "unknown": unknown,
              "desktop": {}, "toolchain": None, "runtime_before": None, "runtime_after": None, "dialog_history": None}

    def save() -> None:
        temporary = report_path.with_name(report_path.name + ".tmp")
        temporary.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        os.replace(temporary, report_path)

    save()
    status = native.desktop_status()
    report["desktop"] = {"ok": status.ok, "reason": status.reason, **status.facts}
    runtime = REPO_ROOT / "files" / "runtime-data"
    downloads = Path.home() / "Downloads" / "Audiobook-Creation-Tool-Outputs"

    def outside_state() -> dict:
        return {"runtime_data": scratch_store.tree_digest(runtime) if runtime.is_dir() else None,
                "default_outputs": scratch_store.tree_digest(downloads) if downloads.is_dir() else None}

    report["runtime_before"] = outside_state()
    try:
        tools = oracle.pinned_toolchain(REPO_ROOT)
        report["toolchain"] = tools.record()
        manifest = media_fixtures.load_manifest(GATE_DIR / "fixtures" / "manifest.json")
    except (oracle.ToolchainUnavailable, oracle.FixtureInvalid) as exc:
        report["blocked"] = f"{type(exc).__name__}: {exc}"
        report["finished"] = True
        save()
        return 2
    try:
        contained = containment.preflight(scratch / "containment")
    except containment.ContainmentUnavailable as exc:
        report["blocked"] = f"ContainmentUnavailable: {exc}"
        report["finished"] = True
        save()
        return 2
    history_before = containment.history_references()
    report["dialog_history"] = {"preflight": contained, "needle": "act-gate", "before": len(history_before)}
    save()
    try:
        with native.DesktopLease():
            for index, identifier in enumerate(wanted):
                if identifier in scenarios:
                    item = scenarios[identifier]
                    print(f"[acceptance] {identifier}: start", flush=True)
                    entry = run_one(item, evidence_root=evidence, scratch_root=scratch, tools=tools, manifest=manifest, index=index)
                    report["scenarios"].append(entry)
                    save()
                    print(f"[acceptance] {identifier}: {entry['status']} {entry['seconds']:.1f}s {entry['reason'][:300]}", flush=True)
    except native.DesktopUnavailable as exc:
        report["blocked"] = f"{type(exc).__name__}: {exc}"
    report["runtime_after"] = outside_state()
    history_after = containment.history_references()
    report["dialog_history"].update(after=len(history_after), added=containment.history_added(history_before, history_after))
    report["finished"] = True
    save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
