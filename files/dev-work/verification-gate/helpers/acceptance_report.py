"""Deciding what a run of the native and real-media journeys may be taken to mean. Pure: a report and the policy go in, a verdict comes out.

The runner's word is never enough. A scenario counts as PASS only with the evidence a pass of its kind must have left: real input, a
screenshot that exists and is an image, media outputs with their digests, validated fixtures, and a recorded clean exit. A required
scenario that is missing is NOT RUN, however well the others went. A status that contradicts its own checks is a FAIL. Copying an old report
in is caught by the token, and a report from a run that wrote outside itself is caught by the before and after state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STATUSES = ("PASS", "FAIL", "BLOCKED", "NOT RUN", "NOT APPLICABLE")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: Tiers whose pass must show a picture of the real application.
NEEDS_SCREENSHOT = {"journey", "adverse", "shutdown", "geometry"}
#: A fixture kind that could not honestly back a real-media claim. The adverse tier's damaged inputs are real inputs damaged in a known way.
FAKE_FIXTURE_KINDS = {"fake", "id3-header-only", "renamed"}


@dataclass
class Judgement:
    status: str
    detail: str
    scenarios: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)

    def passed(self, scenario_id: str) -> bool:
        return any(item["id"] == scenario_id and item["verdict"] == "PASS" for item in self.scenarios)


def _worst(statuses) -> str:
    seen = set(statuses)
    for status in ("FAIL", "BLOCKED", "NOT RUN", "PASS"):
        if status in seen:
            return status
    return "NOT RUN"


def scenario_evidence_problems(entry: dict, evidence_root: Path) -> list[str]:
    """What is missing from a scenario that says PASS. Each line names the evidence, so nobody has to guess what went wrong."""
    problems: list[str] = []
    layers, tier = set(entry.get("layers", [])), entry.get("tier")
    checks = entry.get("checks", [])
    if not checks:
        problems.append("it passed without checking anything")
    failed = [check.get("name") for check in checks if not check.get("ok")]
    if failed:
        problems.append(f"it says PASS with failed checks: {failed[:5]}")
    if "native" in layers and tier != "control" and not entry.get("native_inputs"):
        problems.append("it claims native evidence and sent no real input")
    if "native" in layers and tier != "control":
        for session in entry.get("sessions", []) or ["app"]:
            if not (evidence_root / entry["id"] / f"{session}-actions.jsonl").is_file():
                problems.append(f"its action log for session {session!r} is missing")
    if tier in NEEDS_SCREENSHOT and not entry.get("screenshots"):
        problems.append("it has no screenshot of the real application")
    for shot in entry.get("screenshots", []):
        path = evidence_root / Path(shot.get("path", "missing"))
        try:
            with open(path, "rb") as handle:
                signature = handle.read(8)
        except OSError:
            problems.append(f"screenshot {shot.get('path')} is missing")
            continue
        if signature != PNG_SIGNATURE:
            problems.append(f"screenshot {shot.get('path')} is not an image")
    if "media" in layers:
        fixtures = entry.get("fixtures", [])
        if not fixtures:
            problems.append("it claims real media from no validated fixture")
        for fixture in fixtures:
            if fixture.get("kind") in FAKE_FIXTURE_KINDS:
                problems.append(f"fixture {fixture.get('id')} is a fake and cannot back a real-media claim")
            validation = fixture.get("validation", [])
            if not validation or not all(item.get("ok") for item in validation):
                problems.append(f"fixture {fixture.get('id')} has no passing validation")
        if tier == "journey":
            outputs = entry.get("outputs", [])
            if not outputs:
                problems.append("a media journey with no inspected output")
            for output in outputs:
                if not output.get("sha256") or not output.get("bytes"):
                    problems.append(f"output {output.get('name')} has no digest or is empty")
    if "shutdown" in layers and tier != "control":
        exits = entry.get("notes", {}).get("exits", [])
        if not exits:
            problems.append("a shutdown journey with no observed exit")
        for facts in exits:
            if facts.get("exit_status") != 0 or facts.get("orphans") or facts.get("windows_after"):
                problems.append(f"an exit that is not clean: {facts}")
        if "forced" in entry["id"]:
            forced = entry.get("notes", {}).get("forced_collection") or {}
            if not forced.get("full_passes_on_worker"):
                problems.append("the forced arm has no record of a full collection on a worker")
    return problems


def judge(report_path: Path, *, token: str, wanted: list[str], required: list[str], optional: list[str], evidence_root: Path,
          returncode: int | None, ended: str, required_tools: list[str], whole_set: bool) -> Judgement:
    """The verdict on one acceptance stage. ``wanted`` is what this run selected; ``whole_set`` says it was meant to be everything."""
    if ended != "exited":
        return Judgement("FAIL", f"the runner did not finish on its own: {ended}, exit {returncode}")
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except OSError:
        return Judgement("NOT RUN", f"the runner exited {returncode} and left no report")
    except ValueError as exc:
        return Judgement("FAIL", f"the report cannot be read: {exc}")
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        return Judgement("FAIL", "the report has an unknown schema")
    if report.get("token") != token:
        return Judgement("FAIL", f"the report belongs to another run ({report.get('token')!r}, not {token!r}): copied or stale")
    if report.get("blocked"):
        return Judgement("BLOCKED", f"{report['blocked']}; no native evidence exists, so this is neither a pass nor a product failure")
    if not report.get("finished"):
        return Judgement("NOT RUN", f"the runner exited {returncode} and never finished its report")
    if returncode != 0:
        return Judgement("FAIL", f"the report looks finished and the runner exited {returncode}: the two disagree")
    problems: list[str] = []
    registered, policy = set(report.get("registered", [])), set(required) | set(optional)
    if registered != policy:
        problems.append(f"the registered scenarios and the policy disagree: only registered {sorted(registered - policy)}, "
                        f"only in the policy {sorted(policy - registered)}")
    entries = report.get("scenarios", [])
    ids = [entry.get("id") for entry in entries]
    if len(ids) != len(set(ids)):
        problems.append(f"a scenario was reported twice: {sorted({i for i in ids if ids.count(i) > 1})}")
    unexpected = sorted(set(ids) - set(wanted))
    if unexpected:
        problems.append(f"scenarios ran that were not selected: {unexpected}")
    if report.get("unknown"):
        problems.append(f"unknown scenarios were asked for: {report['unknown']}")
    verdicts: list[dict] = []
    by_id = {entry.get("id"): entry for entry in entries}
    for scenario_id in wanted:
        entry = by_id.get(scenario_id)
        if entry is None:
            verdicts.append({"id": scenario_id, "verdict": "NOT RUN", "reason": "selected and never reported"})
            continue
        status = entry.get("status")
        reason = entry.get("reason", "")
        if status not in STATUSES:
            verdicts.append({"id": scenario_id, "verdict": "FAIL", "reason": f"unknown status {status!r}"})
            continue
        if status == "PASS":
            missing = scenario_evidence_problems(entry, Path(evidence_root))
            if missing:
                status, reason = "FAIL", "; ".join(missing)
        if status == "NOT APPLICABLE":
            if scenario_id not in optional:
                status, reason = "FAIL", f"a required scenario may not be not applicable: {reason}"
            elif not entry.get("notes", {}).get("applicability"):
                status, reason = "FAIL", "not applicable with no evidence of why"
        verdicts.append({"id": scenario_id, "verdict": status, "reason": reason, "tool": entry.get("tool"), "tier": entry.get("tier"),
                         "layers": entry.get("layers", []), "seconds": entry.get("seconds"), "inputs": entry.get("native_inputs"),
                         "checks": len(entry.get("checks", [])), "screenshots": len(entry.get("screenshots", [])),
                         "outputs": len(entry.get("outputs", [])), "notes": entry.get("notes", {})})
    before, after = report.get("runtime_before"), report.get("runtime_after")
    if not before or before != after:
        problems.append(f"the real runtime data or the default output folder changed during the run: {before} -> {after}")
    history = report.get("dialog_history") or {}
    if (history.get("preflight") or {}).get("verdict") != "contained" or not isinstance(history.get("added"), dict):
        problems.append("no proof that the owner's Windows dialog history was protected: the report lacks a contained preflight or "
                        "the reading after the run")
    elif history["added"]:
        problems.append(f"the run added {len(history['added'])} values naming the gate's scratch to the owner's Windows dialog history: "
                        f"{sorted(history['added'])[:5]}")
    if whole_set:
        for tool in required_tools:
            mine = [item for item in verdicts if item.get("tool") == tool and item.get("tier") == "journey" and {"native", "media"} <= set(item.get("layers", []))]
            complete = [item for item in mine if item["verdict"] == "PASS"]
            # One that was BLOCKED or never ran is already reported as that; calling it a failure too would misstate what happened.
            pending = [item for item in mine if item["verdict"] in ("BLOCKED", "NOT RUN")]
            if not complete and not pending:
                problems.append(f"{tool} has no complete native and real-output journey that passed")
    statuses = [item["verdict"] for item in verdicts if item["id"] not in optional or item["verdict"] != "NOT APPLICABLE"]
    if problems:
        statuses.append("FAIL")
    status = _worst(statuses) if statuses else "NOT RUN"
    tally = {name: sum(1 for item in verdicts if item["verdict"] == name) for name in STATUSES}
    summary = ", ".join(f"{count} {name}" for name, count in tally.items() if count)
    bad = [f"{item['id']}: {item['verdict']}: {str(item.get('reason', ''))[:300]}" for item in verdicts if item["verdict"] in ("FAIL", "BLOCKED", "NOT RUN")]
    detail = "; ".join([summary, *problems, *bad[:12]])
    candidates = [{"scenario": entry.get("id"), **shot} for entry in entries for shot in entry.get("screenshots", [])]
    return Judgement(status, detail, verdicts, problems, candidates)


def report_lines(judgement: Judgement) -> list[str]:
    lines = ["# Native and real-media journeys", "", f"**{judgement.status}**: {judgement.detail}", "",
             "| Scenario | Result | Tool | Tier | Inputs | Checks | Pictures | Outputs | Seconds |", "|---|---|---|---|--:|--:|--:|--:|--:|"]
    for item in judgement.scenarios:
        lines.append(f"| `{item['id']}` | {item['verdict']} | {item.get('tool', '')} | {item.get('tier', '')} | {item.get('inputs', '')} | "
                     f"{item.get('checks', '')} | {item.get('screenshots', '')} | {item.get('outputs', '')} | {item.get('seconds', '')} |")
    return lines
