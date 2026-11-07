"""The one coverage inventory, read and held to account (plan section 7). Pure functions over coverage.json and a run's real results.

Four things are kept apart, because a 100% figure on one proves nothing about the next: what was inventoried, what is mapped to a meaningful
verification, what was actually satisfied in this run, and optional line coverage. A mapping that names a dead test, an unknown scenario or
a kind of evidence the target cannot give stops a clean run, and a unit test cannot stand in for a native or real-media requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("behavior", "native", "media")
SIX_TOOLS = ("tts-audiobook", "mp3-tool", "m4b-converter", "m4b-maker", "m4b-metadata-editor", "cover-image")
EXCEPTION_FIELDS = ("approved_by", "scope", "reason", "compensating_check", "review_trigger", "release")


@dataclass
class CoverageResult:
    problems: list[str] = field(default_factory=list)
    features: list[dict] = field(default_factory=list)
    inventoried: int = 0
    required: int = 0
    mapped_required: int = 0
    satisfied_required: int = 0
    unsatisfied: list[str] = field(default_factory=list)
    inventory_reviewed: bool = False

    def record(self) -> dict:
        return {"inventory_reviewed": self.inventory_reviewed, "inventoried": self.inventoried, "required": self.required,
                "mapped_required": self.mapped_required, "satisfied_required": self.satisfied_required, "line_coverage": "not collected",
                "unsatisfied": self.unsatisfied, "problems": self.problems}


def verifications_of(feature: dict) -> list[dict]:
    verification = feature.get("verification") or {}
    return list(verification.get("all_of", []))


def problems_in_inventory(coverage: dict, *, scenarios: dict[str, dict], collected: set[str] | None = None, disk_check=None,
                          required_tools=SIX_TOOLS) -> list[str]:
    """What is wrong with the mapping itself, whatever any run did. ``collected`` is this run's exact node ids, when the whole suite was collected."""
    problems: list[str] = []
    features = coverage.get("features", [])
    seen_tools = {feature.get("tool") for feature in features if verifications_of(feature)}
    missing_tools = [tool for tool in required_tools if tool not in seen_tools]
    if missing_tools:
        problems.append(f"no feature maps these tools at all: {missing_tools}")
    for feature in features:
        identity = feature.get("id")
        if feature.get("release_required") and not verifications_of(feature) and not feature.get("exceptions"):
            problems.append(f"{identity} is required and maps to nothing")
        for item in verifications_of(feature):
            kind = item.get("kind")
            if kind not in KINDS:
                problems.append(f"{identity}: unknown verification kind {kind!r}")
                continue
            if kind == "behavior":
                test = item.get("test", "")
                if "::" not in test:
                    problems.append(f"{identity}: {test!r} is not an exact test id; a module or glob proves nothing")
                elif collected is not None and test not in collected:
                    problems.append(f"{identity}: dead test id {test}")
                if item.get("scenario"):
                    problems.append(f"{identity}: a behavior entry names a scenario")
                continue
            scenario_id = item.get("scenario")
            if not scenario_id or item.get("test"):
                problems.append(f"{identity}: a {kind} requirement needs a scenario; a test cannot stand in for it")
                continue
            scenario = scenarios.get(scenario_id)
            if scenario is None:
                problems.append(f"{identity}: dead scenario id {scenario_id}")
            elif kind not in scenario.get("layers", []):
                problems.append(f"{identity}: scenario {scenario_id} does not give {kind} evidence, only {scenario.get('layers')}")
        for exception in feature.get("exceptions", []):
            absent = [name for name in EXCEPTION_FIELDS if not exception.get(name)]
            if absent:
                problems.append(f"{identity}: an exception without {absent}")
            elif str(exception.get("approved_by")).strip().lower() != "owner":
                problems.append(f"{identity}: an exception not approved by the owner; agents cannot reduce required coverage")
        if disk_check is not None:
            for source in feature.get("source", []):
                if not disk_check(source["path"]):
                    problems.append(f"{identity} names source {source['path']}, which does not exist")
            for selector in feature.get("selection", []):
                if not disk_check(selector):
                    problems.append(f"{identity} selects {selector}, which does not exist")
    return problems


def evaluate(coverage: dict, *, scenarios: dict[str, dict], passed_tests: set[str] | None, passed_scenarios: set[str],
             collected: set[str] | None = None, disk_check=None, required_tools=SIX_TOOLS) -> CoverageResult:
    """Everything above, plus what this run really satisfied. A selection that left something out reports it unsatisfied, never satisfied."""
    result = CoverageResult(inventory_reviewed=bool(coverage.get("inventory_reviewed")))
    result.problems = problems_in_inventory(coverage, scenarios=scenarios, collected=collected, disk_check=disk_check, required_tools=required_tools)
    features = coverage.get("features", [])
    result.inventoried = len(features)
    for feature in features:
        verifications = verifications_of(feature)
        row = {"id": feature.get("id"), "tool": feature.get("tool"), "required": bool(feature.get("release_required")), "verifications": []}
        satisfied = bool(verifications)
        for item in verifications:
            if item.get("kind") == "behavior":
                done = passed_tests is not None and item.get("test") in passed_tests
            else:
                done = item.get("scenario") in passed_scenarios
            row["verifications"].append({**item, "satisfied": done})
            satisfied = satisfied and done
        row["satisfied"] = satisfied
        result.features.append(row)
        if feature.get("release_required"):
            result.required += 1
            if verifications:
                result.mapped_required += 1
            if satisfied:
                result.satisfied_required += 1
            else:
                result.unsatisfied.append(str(feature.get("id")))
    return result


def report_lines(result: CoverageResult) -> list[str]:
    lines = ["# Coverage", "",
             "These measures are separate on purpose. Mapped proves only that the registered inventory's entries have a target. Satisfied proves what ran here.", "",
             f"- Inventory reviewed: **{result.inventory_reviewed}** ({result.inventoried} features registered. The reviewed, complete inventory is Phase 4's.)",
             f"- Required entries mapped: **{result.mapped_required} of {result.required}**",
             f"- Required verifications satisfied in this run: **{result.satisfied_required} of {result.required}**",
             "- Line coverage: not collected", ""]
    if result.problems:
        lines += ["## Problems", "", *[f"- {problem}" for problem in result.problems], ""]
    lines += ["## Features", "", "| Feature | Tool | Required | Satisfied here | Verifications |", "|---|---|---|---|---|"]
    for row in result.features:
        evidence = ", ".join(f"{item.get('kind')}:{item.get('scenario') or item.get('test')}{'' if item['satisfied'] else ' (not here)'}"
                             for item in row["verifications"]) or "none mapped"
        lines.append(f"| `{row['id']}` | {row['tool']} | {row['required']} | {row['satisfied']} | {evidence} |")
    return lines
