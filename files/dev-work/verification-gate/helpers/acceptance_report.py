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


# --------------------------------------------------------------------------------------------------------------------- #
#  macOS (v0.8.x P1B, plan 14.3, MAC-045, D9): the darwin acceptance map
# --------------------------------------------------------------------------------------------------------------------- #
DARWIN_CLASSES = ("automated", "owner-manual", "not-applicable")
#: Only a test of the Windows input harness itself may be NOT APPLICABLE ON MACOS (plan 14.3 class c).
DARWIN_NA_REASONS = ("windows-input-harness",)
#: P1B closeout (owner's revised acceptance, 2026-11-15): what an automated counterpart's PASS must show, named per scenario in
#: ``darwin_map[...]["evidence"]``. No owner signature stands in for any of them.
#:   journey-checks    the Windows judge's rules for its tier (checks, inputs, action logs, fixtures, digested outputs, clean
#:                     exits) plus the Tk thread audit;
#:   real-screenshots  at least one picture of the real window, each captured by the window server at this run's SHA, a
#:                     decodable PNG of the recorded size, and PASS on helpers/visual_review.py (recomputed here);
#:   dialog-contract   every file or folder dialog it answered recorded the options the application gave the panel (title,
#:                     and file types for an open panel). These are in-process stand-ins: the real NSOpenPanel and NSAlert
#:                     are proved by the darwin scenario ``macos-native-dialogs``, never by this.
DARWIN_EVIDENCE = ("journey-checks", "real-screenshots", "dialog-contract")
#: How each verdict reads in the requirement vocabulary of the revised acceptance.
REQUIREMENT_LABELS = {"PASS": "AUTOMATED PASS", "FAIL": "AUTOMATED FAIL", "BLOCKED": "BLOCKED", "NOT RUN": "NOT RUN",
                      "NOT APPLICABLE": "NOT APPLICABLE — JUSTIFIED"}


def darwin_map_problems(darwin_map: dict | None, required: list[str], optional: list[str]) -> list[str]:
    """Every required and optional scenario mapped exactly once, each entry well formed. Empty when the map is usable.
    A policy with no acceptance scenarios at all has nothing to map, so it needs no map; any scenario needs one."""
    if darwin_map is None and not required and not optional:
        return []
    if not isinstance(darwin_map, dict):
        return ["there is no acceptance.darwin_map"]
    problems: list[str] = []
    wanted = set(required) | set(optional)
    missing, extra = sorted(wanted - set(darwin_map)), sorted(set(darwin_map) - wanted)
    if missing:
        problems.append(f"unmapped scenarios: {missing}")
    if extra:
        problems.append(f"mapped scenarios the policy does not have: {extra}")
    for scenario_id, entry in darwin_map.items():
        kind = entry.get("class") if isinstance(entry, dict) else None
        if kind not in DARWIN_CLASSES:
            problems.append(f"{scenario_id}: class {kind!r} is not one of {DARWIN_CLASSES}")
            continue
        if kind == "automated" and entry.get("journey") != scenario_id and not entry.get("tests"):
            problems.append(f"{scenario_id}: an automated counterpart names neither its journey nor its tests")
        if kind == "automated" and entry.get("manual"):
            problems.append(f"{scenario_id}: an automated counterpart may not wait on an owner's signed record (P1B closeout); "
                            f"name the evidence its PASS needs instead")
        if kind == "automated" and not entry.get("pending_phase"):
            evidence = entry.get("evidence")
            if not isinstance(evidence, list) or "journey-checks" not in evidence:
                problems.append(f"{scenario_id}: an automated counterpart names no evidence list with journey-checks")
            elif set(evidence) - set(DARWIN_EVIDENCE):
                problems.append(f"{scenario_id}: unknown evidence {sorted(set(evidence) - set(DARWIN_EVIDENCE))}")
        if kind == "owner-manual" and not entry.get("checklist"):
            problems.append(f"{scenario_id}: an owner-manual counterpart names no checklist item")
        if kind == "not-applicable" and (entry.get("reason_id") not in DARWIN_NA_REASONS or not scenario_id.startswith("control.")):
            problems.append(f"{scenario_id}: not applicable on macOS only for a test of the Windows input harness, with a reviewed "
                            f"reason id ({entry.get('reason_id')!r})")
    return problems


def _manual_evidence(evidence_dir: Path | None, item: str, sha: str | None) -> str | None:
    """A problem with the owner's signed record for one manual item at this SHA, or None when it is there and signed."""
    if evidence_dir is None or not sha:
        return f"{item}: no candidate SHA or evidence folder to look in"
    path = Path(evidence_dir) / sha / f"{item.replace(':', '--')}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"{item}: no signed owner evidence for {sha[:12]} ({path.name})"
    if record.get("sha") != sha or not str(record.get("signed_by", "")).strip() or record.get("result") != "PASS":
        return f"{item}: the evidence for {sha[:12]} is not a signed PASS of this SHA"
    return None


def _actions(evidence_root: Path, entry: dict) -> list[dict]:
    found = []
    for session in entry.get("sessions", []) or ["app"]:
        path = Path(evidence_root) / entry["id"] / f"{session}-actions.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                found.append(json.loads(line))
            except ValueError:
                continue
    return found


def _screenshot_problems(entry: dict, evidence_root: Path, sha: str | None) -> list[str]:
    """Each picture re-judged from its own files: captured, of this run's SHA, and PASS on the visual review."""
    from helpers import visual_review

    shots = entry.get("screenshots", [])
    if not shots:
        return ["it has no picture of the real window"]
    problems = []
    for shot in shots:
        png = Path(evidence_root) / Path(shot.get("path", "missing"))
        record = visual_review.load_record(png)
        if record is None:
            problems.append(f"screenshot {shot.get('path')} has no provenance record")
            continue
        if not record.get("captured"):
            problems.append(f"screenshot {shot.get('path')} was not captured: {record.get('why')}")
            continue
        if not sha or record.get("sha") != sha:
            problems.append(f"screenshot {shot.get('path')} is of {str(record.get('sha'))[:12]}, this run is of {str(sha)[:12]}")
        verdict = visual_review.review(png, record)
        if verdict["status"] != "PASS":
            problems.append(f"screenshot {shot.get('path')} review {verdict['status']}: {verdict['reason'][:300]}")
    return problems


def _dialog_contract_problems(entry: dict, evidence_root: Path) -> list[str]:
    answered = [item for item in _actions(evidence_root, entry)
                if item.get("kind") == "input" and item.get("action") in ("file dialog", "folder dialog")]
    if not answered:
        return ["it names dialog-contract and answered no file or folder dialog"]
    problems = []
    for item in answered:
        options = item.get("options")
        if not isinstance(options, dict) or not str(options.get("title", "")).strip():
            problems.append(f"the {item.get('dialog_kind')} dialog {item.get('title')!r} recorded no options from the application")
        elif item.get("dialog_kind") in ("askopenfilename", "askopenfilenames") and not str(options.get("filetypes", "")).strip("()[] "):
            problems.append(f"the open dialog {item.get('title')!r} was given no file types")
    return problems


def _darwin_evidence_problems(entry: dict, evidence_root: Path, requirements=("journey-checks",), sha: str | None = None) -> list[str]:
    """What a macOS automated counterpart's PASS must show: the evidence its map entry names (DARWIN_EVIDENCE), plus the Tk
    thread audit. Without ``real-screenshots`` the picture rule is the Windows one minus the picture (a control scenario)."""
    problems = [line for line in scenario_evidence_problems({**entry, "screenshots": []}, evidence_root)
                if not line.startswith("it has no screenshot")]
    for facts in entry.get("notes", {}).get("exits", []):
        if facts.get("tk_off_thread"):
            problems.append(f"a worker thread called Tk: {facts['tk_off_thread'][:3]}")
    if "real-screenshots" in requirements:
        problems += _screenshot_problems(entry, evidence_root, sha)
    if "dialog-contract" in requirements:
        problems += _dialog_contract_problems(entry, evidence_root)
    return problems


def judge_darwin(report_path: Path, *, token: str, wanted: list[str], required: list[str], optional: list[str], evidence_root: Path,
                 returncode: int | None, ended: str, darwin_map: dict, manual_evidence: Path | None, sha: str | None,
                 required_tools: list[str] = (), whole_set: bool = False) -> Judgement:
    """The verdict on one macOS acceptance stage. Counts -- automated counterparts PASS/FAIL, owner-manual items (a class no
    scenario uses since the P1B closeout) verified present, not-applicable items with their reason ids -- and FAIL on any
    unmapped scenario, failed counterpart or counterpart without the evidence its map entry names (real pictures at this SHA
    that pass review, the dialog contract; see DARWIN_EVIDENCE); a required scenario not yet runnable is NOT RUN. Never a blanket
    NOT APPLICABLE. The report itself is held to the Windows judge's rules: this run's token, the registered set equal to the
    policy's, nothing reported twice or unselected, a finished report from a runner that exited 0, and on a whole-set run
    every required tool with a passing journey (or journeys mapped to a later phase, which are NOT RUN, never a pass)."""
    problems = darwin_map_problems(darwin_map, required, optional)
    if problems:
        return Judgement("FAIL", "; ".join(problems), problems=problems)
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
        return Judgement("BLOCKED", f"{report['blocked']}; no evidence exists, so this is neither a pass nor a product failure")
    if not report.get("finished"):
        return Judgement("NOT RUN", f"the runner exited {returncode} and never finished its report")
    if returncode != 0:
        return Judgement("FAIL", f"the report looks finished and the runner exited {returncode}: the two disagree")
    registered, known = set(report.get("registered", [])), set(required) | set(optional)
    if registered != known:
        problems.append(f"the registered scenarios and the policy disagree: only registered {sorted(registered - known)}, "
                        f"only in the policy {sorted(known - registered)}")
    entries = report.get("scenarios", [])
    ids = [entry.get("id") for entry in entries]
    if len(ids) != len(set(ids)):
        problems.append(f"a scenario was reported twice: {sorted({i for i in ids if ids.count(i) > 1})}")
    unexpected = sorted(set(ids) - set(wanted))
    if unexpected:
        problems.append(f"scenarios ran that were not selected: {unexpected}")
    if report.get("unknown"):
        problems.append(f"unknown scenarios were asked for: {report['unknown']}")
    by_id = {entry.get("id"): entry for entry in entries}
    verdicts: list[dict] = []
    counts = {"automated PASS": 0, "automated FAIL": 0, "manual verified": 0, "manual missing": 0, "not applicable": 0, "NOT RUN": 0}
    for scenario_id in wanted:
        mapping = darwin_map[scenario_id]
        kind = mapping["class"]
        if kind == "not-applicable":
            counts["not applicable"] += 1
            verdicts.append({"id": scenario_id, "verdict": "NOT APPLICABLE", "reason": f"NOT APPLICABLE ON MACOS ({mapping['reason_id']})"})
            continue
        if kind == "automated" and mapping.get("pending_phase"):
            counts["NOT RUN"] += 1
            verdicts.append({"id": scenario_id, "verdict": "NOT RUN", "reason": f"pending {mapping['pending_phase']}"})
            continue
        missing_manual = [problem for item in mapping.get("manual", []) + ([mapping["checklist"]] if kind == "owner-manual" else [])
                          if (problem := _manual_evidence(manual_evidence, item, sha))]
        if kind == "owner-manual":
            verdict = "FAIL" if missing_manual else "PASS"
            counts["manual verified" if not missing_manual else "manual missing"] += 1
            verdicts.append({"id": scenario_id, "verdict": verdict, "reason": "; ".join(missing_manual)})
            continue
        entry = by_id.get(scenario_id)
        if entry is None:
            counts["NOT RUN"] += 1
            verdicts.append({"id": scenario_id, "verdict": "NOT RUN", "reason": "selected and never reported"})
            continue
        status, reason = entry.get("status"), entry.get("reason", "")
        if status == "PASS":
            found = _darwin_evidence_problems(entry, Path(evidence_root), mapping.get("evidence") or ("journey-checks",), sha)
            if found:
                status, reason = "FAIL", "; ".join(found)
        if status not in STATUSES or status == "NOT APPLICABLE":
            status, reason = "FAIL", f"an automated counterpart reported {status!r}: {reason}"
        counts["automated PASS" if status == "PASS" else "automated FAIL"] += 1 if status in ("PASS", "FAIL") else 0
        if status == "PASS" and missing_manual:
            counts["manual missing"] += 1
            status, reason = "FAIL", "its native-dialog steps have no signed owner evidence: " + "; ".join(missing_manual)
        elif mapping.get("manual"):
            counts["manual verified"] += 1
        verdicts.append({"id": scenario_id, "verdict": status, "reason": reason, "tool": entry.get("tool"), "tier": entry.get("tier"),
                         "layers": entry.get("layers", []), "seconds": entry.get("seconds"), "inputs": entry.get("native_inputs"),
                         "checks": len(entry.get("checks", [])), "outputs": len(entry.get("outputs", [])), "notes": entry.get("notes", {}),
                         "evidence": list(mapping.get("evidence") or ()), "screenshots": len(entry.get("screenshots", []))})
    for item in verdicts:
        mapping = darwin_map.get(item["id"], {})
        item["requirement"] = ("NOT RUN — LATER PHASE" if mapping.get("pending_phase") and item["verdict"] == "NOT RUN"
                               else REQUIREMENT_LABELS.get(item["verdict"], item["verdict"]))
    before, after = report.get("runtime_before"), report.get("runtime_after")
    if not before or before != after:
        problems.append(f"the real runtime data or the default output folder changed during the run: {before} -> {after}")
    if whole_set:
        later = {darwin_map[sid].get("tool") for sid in wanted if darwin_map[sid].get("pending_phase")}
        for tool in required_tools:
            mine = [item for item in verdicts if item.get("tool") == tool and item.get("tier") == "journey"
                    and {"native", "media"} <= set(item.get("layers", []))]
            # As on Windows: one that was BLOCKED or never ran, or is mapped to a later phase, is already reported as that.
            if not any(item["verdict"] in ("PASS", "BLOCKED", "NOT RUN") for item in mine) and tool not in later:
                problems.append(f"{tool} has no complete native and real-output journey that passed")
    statuses = [item["verdict"] for item in verdicts
                if not (item["id"] in optional and item["verdict"] in ("NOT RUN", "NOT APPLICABLE"))
                and item["verdict"] != "NOT APPLICABLE"]
    if problems:
        statuses.append("FAIL")
    status = _worst(statuses) if statuses else "NOT RUN"
    bad = [f"{item['id']}: {item['verdict']}: {str(item.get('reason', ''))[:200]}" for item in verdicts if item["verdict"] in ("FAIL", "BLOCKED", "NOT RUN")]
    detail = "; ".join([", ".join(f"{count} {name}" for name, count in counts.items() if count), *problems, *bad[:12]])
    candidates = [{"scenario": entry.get("id"), **shot} for entry in entries for shot in entry.get("screenshots", [])]
    return Judgement(status, detail, verdicts, problems, candidates)
