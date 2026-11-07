"""The one coverage inventory, read and held to account (plan section 7). Pure functions over coverage.json and a run's real results.

Four things are kept apart, because a 100% figure on one proves nothing about the next: what was inventoried and reviewed, what is mapped
to a meaningful verification, what was actually satisfied in this run, and optional line coverage. A mapping that names a dead test, an
unknown scenario or a kind of evidence the target cannot give stops a clean run, and a unit test cannot stand in for a native or real-media
requirement.

Verification kinds come in two groups. Routine kinds are what the routine gate itself runs and must satisfy: ``behavior`` (an exact pytest
id), ``native`` and ``media`` (a registered journey that gives that layer), ``control`` (a journey that is a negative control of the gate)
and ``discovery`` (live surface discovery). Release kinds are never satisfied by a routine run, so they keep ``release_ready`` false and stay
visible without failing it: ``qualification`` (a named expensive scenario), ``owner`` (a check only the owner can make) and ``planned`` (a
required behaviour that is missing or known broken, tied to an open issue in the ledger and a later phase). None of them can be written in
place of routine evidence for something the routine gate can check, and none can be approved by an agent.

Schema 2 adds what makes the inventory maintainable: the reviewed index of every discovered surface (static and live), a review stamp per
application source file so a change cannot pass without its mapping being looked at again, the issue ledger, and the feature-map documents
each tool is described in. ``helpers/inventory.py`` gathers those facts from disk; everything here judges them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from helpers import surface_discovery

ROUTINE_KINDS = ("behavior", "native", "media", "control", "discovery")
RELEASE_KINDS = ("qualification", "owner", "planned")
KINDS = ROUTINE_KINDS + RELEASE_KINDS
SCENARIO_KINDS = ("native", "media", "control", "discovery")
SIX_TOOLS = ("tts-audiobook", "mp3-tool", "m4b-converter", "m4b-maker", "m4b-metadata-editor", "cover-image")
EXCEPTION_FIELDS = ("approved_by", "scope", "reason", "compensating_check", "review_trigger", "release")
ID_PATTERN = re.compile(r"^ACT\.(TTS|MP3|CONVERTER|MAKER|METADATA|COVER|LAUNCHER|SHARED|SETUP|GATE)(\.[A-Z0-9]+(-[A-Z0-9]+)*)+$")
#: Anything in a feature-map document that looks like a feature id; each must be a real one.
ID_MENTION = re.compile(r"\bACT\.[A-Z][A-Z0-9]*(?:\.[A-Z0-9]+(?:-[A-Z0-9]+)*)+\b")
#: An exact test id in prose would be a second, drifting copy of the mapping.
TEST_ID_MENTION = re.compile(r"files/tests/test_[A-Za-z0-9_]+\.py::")
TEST_ID = re.compile(r"^files/tests/test_[A-Za-z0-9_.\-]+\.py::[^\s]+$")
#: The phase that completed the inventory; a planned gap belongs to a later one.
INVENTORY_PHASE = 4


@dataclass
class CoverageResult:
    problems: list[str] = field(default_factory=list)
    features: list[dict] = field(default_factory=list)
    inventoried: int = 0
    required: int = 0
    mapped_required: int = 0
    satisfied_required: int = 0
    release_satisfied_required: int = 0
    unsatisfied: list[str] = field(default_factory=list)
    unmapped_required: list[str] = field(default_factory=list)
    release_pending: dict[str, list[str]] = field(default_factory=dict)
    inventory_reviewed: bool = False
    surfaces: dict = field(default_factory=dict)
    issues_open: int = 0

    def record(self) -> dict:
        return {"inventory_reviewed": self.inventory_reviewed, "inventoried": self.inventoried, "required": self.required,
                "mapped_required": self.mapped_required, "satisfied_required": self.satisfied_required,
                "release_satisfied_required": self.release_satisfied_required, "line_coverage": "not collected",
                "unsatisfied": self.unsatisfied, "unmapped_required": self.unmapped_required,
                "release_pending": self.release_pending, "surfaces": self.surfaces, "issues_open": self.issues_open,
                "problems": self.problems}


def verifications_of(feature: dict) -> list[dict]:
    verification = feature.get("verification") or {}
    return list(verification.get("all_of", []))


def routine_of(feature: dict) -> list[dict]:
    return [item for item in verifications_of(feature) if item.get("kind") in ROUTINE_KINDS]


def _open_issues(coverage: dict) -> dict[str, dict]:
    return {issue.get("id"): issue for issue in coverage.get("issues", []) if issue.get("status") == "open"}


def problems_in_inventory(coverage: dict, *, scenarios: dict[str, dict], collected: set[str] | None = None, disk_check=None,
                          required_tools=SIX_TOOLS, qualification_scenarios=(), test_check=None, symbol_check=None) -> list[str]:
    """What is wrong with the mapping itself, whatever any run did.

    ``scenarios`` maps each registered journey to the layers it gives. ``collected`` is this run's exact node ids, when the whole suite was
    collected; ``test_check`` resolves a test id against the test source without collecting (None when it resolves). ``disk_check`` and
    ``symbol_check`` say whether a path, and a symbol in it, exist.
    """
    problems: list[str] = []
    features = coverage.get("features", [])
    ids = {feature.get("id") for feature in features}
    schema = coverage.get("schema_version", 1)
    tools = coverage.get("tools", {})
    open_issues = _open_issues(coverage)
    seen_tools = {feature.get("tool") for feature in features if routine_of(feature)}
    missing_tools = [tool for tool in required_tools if tool not in seen_tools]
    if missing_tools:
        problems.append(f"no feature maps these tools at all: {missing_tools}")
    for feature in features:
        identity = feature.get("id")
        if schema >= 2:
            if not ID_PATTERN.match(str(identity)):
                problems.append(f"{identity!r} is not a feature id (ACT.<FAMILY>.<NAME>, uppercase)")
            if feature.get("tool") not in tools:
                problems.append(f"{identity}: tool {feature.get('tool')!r} is not one of the inventory's tools")
            if not feature.get("source"):
                problems.append(f"{identity}: names no source; every feature is somewhere in the code")
        if feature.get("release_required") and not verifications_of(feature) and not feature.get("exceptions"):
            problems.append(f"{identity} is required and maps to nothing")
        for item in verifications_of(feature):
            problems += _verification_problems(identity, item, scenarios=scenarios, collected=collected, test_check=test_check,
                                               qualification_scenarios=qualification_scenarios, open_issues=open_issues, schema=schema)
        for exception in feature.get("exceptions", []):
            absent = [name for name in EXCEPTION_FIELDS if not exception.get(name)]
            if absent:
                problems.append(f"{identity}: an exception without {absent}")
            elif str(exception.get("approved_by")).strip().lower() != "owner":
                problems.append(f"{identity}: an exception not approved by the owner; agents cannot reduce required coverage")
            elif schema >= 2 and not exception.get("approval_evidence"):
                problems.append(f"{identity}: an owner exception must cite where the owner approved it (approval_evidence)")
        if disk_check is not None:
            for source in feature.get("source", []):
                if not disk_check(source["path"]):
                    problems.append(f"{identity} names source {source['path']}, which does not exist")
                elif symbol_check is not None:
                    for symbol in source.get("symbols", []):
                        if not symbol_check(source["path"], symbol):
                            problems.append(f"{identity} names symbol {symbol} in {source['path']}, which does not exist")
            for selector in feature.get("selection", []):
                if not disk_check(selector):
                    problems.append(f"{identity} selects {selector}, which does not exist")
        for journey in feature.get("journeys", []):
            if scenarios and journey not in scenarios:
                problems.append(f"{identity}: dead journey id {journey}")
    if schema >= 2:
        problems += _surface_problems(coverage, ids)
        problems += _issue_problems(coverage, ids)
        problems += _journey_mapping_problems(features, scenarios)
    return problems


def _verification_problems(identity, item: dict, *, scenarios, collected, test_check, qualification_scenarios, open_issues, schema) -> list[str]:
    kind = item.get("kind")
    if kind not in KINDS or (schema < 2 and kind not in ("behavior", "native", "media")):
        return [f"{identity}: unknown verification kind {kind!r}"]
    if kind == "behavior":
        test = item.get("test", "")
        found = []
        if "::" not in test:
            found.append(f"{identity}: {test!r} is not an exact test id; a module or glob proves nothing")
        elif collected is not None and test not in collected:
            found.append(f"{identity}: dead test id {test}")
        elif test_check is not None and (reason := test_check(test)):
            found.append(f"{identity}: dead test id {test} ({reason})")
        if item.get("scenario"):
            found.append(f"{identity}: a behavior entry names a scenario")
        return found
    if kind in SCENARIO_KINDS:
        scenario_id = item.get("scenario")
        if not scenario_id or item.get("test"):
            return [f"{identity}: a {kind} requirement needs a scenario; a test cannot stand in for it"]
        scenario = scenarios.get(scenario_id)
        if scenario is None:
            return [f"{identity}: dead scenario id {scenario_id}"]
        if scenario.get("layers") is not None and kind not in scenario.get("layers", []):
            return [f"{identity}: scenario {scenario_id} does not give {kind} evidence, only {scenario.get('layers')}"]
        return []
    if kind == "qualification":
        if item.get("scenario") not in qualification_scenarios:
            return [f"{identity}: unknown qualification scenario {item.get('scenario')!r}; known {list(qualification_scenarios)}"]
        return []
    if kind == "owner":
        return [] if item.get("check") and item.get("detail") else [f"{identity}: an owner check needs a check name and what the owner does"]
    # planned: a gap that stays visible until a later phase replaces it with real evidence.
    found = []
    if not item.get("gap"):
        found.append(f"{identity}: a planned entry must say what is missing")
    phase = item.get("phase")
    if not isinstance(phase, int) or phase <= INVENTORY_PHASE:
        found.append(f"{identity}: a planned entry belongs to a later phase than {INVENTORY_PHASE}, not {phase!r}")
    if item.get("issue") not in open_issues:
        found.append(f"{identity}: a planned entry must name an open issue in the ledger, not {item.get('issue')!r}")
    return found


def _surface_problems(coverage: dict, ids: set) -> list[str]:
    problems = []
    surfaces = coverage.get("surfaces", {})
    for key, feature in surfaces.get("static", {}).items():
        if feature not in ids:
            problems.append(f"static surface {key} maps to {feature!r}, which is no feature (a dangling id)")
    for scope, index in surfaces.get("live", {}).items():
        for key, feature in index.items():
            if feature not in ids:
                problems.append(f"live surface {scope}:{key} maps to {feature!r}, which is no feature (a dangling id)")
    return problems


def _issue_problems(coverage: dict, ids: set) -> list[str]:
    problems = []
    seen = set()
    for issue in coverage.get("issues", []):
        identity = issue.get("id")
        if not re.match(r"^ACT72-\d{3}$", str(identity)) or identity in seen:
            problems.append(f"issue {identity!r}: ids are ACT72-nnn and unique")
        seen.add(identity)
        if issue.get("status") not in ("open", "closed"):
            problems.append(f"issue {identity}: status must be open or closed")
        for feature in issue.get("features", []):
            if feature not in ids:
                problems.append(f"issue {identity} names {feature!r}, which is no feature (a dangling id)")
    return problems


def _journey_mapping_problems(features: list[dict], scenarios: dict[str, dict]) -> list[str]:
    """A registered required journey that no feature maps is a workflow outside the inventory."""
    mapped = {item.get("scenario") for feature in features for item in verifications_of(feature)}
    mapped |= {journey for feature in features for journey in feature.get("journeys", [])}
    return [f"a registered journey no feature maps: {scenario}" for scenario, facts in sorted(scenarios.items())
            if facts.get("required", True) and scenario not in mapped]


def discovery_problems(coverage: dict, *, static_found: dict | None, source_digests: dict[str, str] | None,
                       documents: dict[str, str | None] | None, readme: str | None = None) -> list[str]:
    """The inventory held against what is really there: discovered surfaces, reviewed source, and the documents that describe it.

    ``static_found`` is static discovery's result (key -> Surface); ``source_digests`` the current digest of every application source
    file; ``documents`` the text of each feature-map document by path (None when the file is missing); ``readme`` the map's README.
    """
    problems: list[str] = []
    features = coverage.get("features", [])
    ids = {feature.get("id") for feature in features}
    if static_found is not None:
        problems += surface_discovery.compare_static(coverage.get("surfaces", {}).get("static", {}), static_found)
    if source_digests is not None:
        problems += review_problems(coverage, source_digests)
    if documents is not None:
        tools = coverage.get("tools", {})
        for tool, facts in sorted(tools.items()):
            document = facts.get("document")
            text = documents.get(document)
            if text is None:
                problems.append(f"tool {tool}: its feature-map document {document} does not exist")
                continue
            for feature in features:
                if feature.get("tool") == tool and f"`{feature['id']}`" not in text:
                    problems.append(f"{feature['id']} is not described in {document}")
        for document, text in sorted(documents.items()):
            if text is None:
                continue
            for mention in sorted(set(ID_MENTION.findall(text)) - ids):
                problems.append(f"{document} mentions {mention}, which is no feature (a dangling id)")
            if TEST_ID_MENTION.search(text):
                problems.append(f"{document} names an exact test id; the mapping lives only in coverage.json")
        if readme is not None:
            for document in sorted({facts.get("document") for facts in tools.values()}):
                if document and document.rsplit("/", 1)[-1] not in readme:
                    problems.append(f"the feature-map README does not list {document}")
    return problems


def review_problems(coverage: dict, digests: dict[str, str]) -> list[str]:
    """Each application source file reviewed against the mapping as it is now, and each named by a feature.

    A stamp is the digest the file had when its features' entries were last reviewed. A file that changed since then, a new file, or a
    file no feature names cannot pass until someone has looked at the mapping again and restamped it (``inventory.py restamp``)."""
    problems = []
    stamps = coverage.get("source_review", {})
    named: dict[str, list[str]] = {}
    for feature in coverage.get("features", []):
        for source in feature.get("source", []):
            named.setdefault(source.get("path"), []).append(feature.get("id"))
    for path in sorted(set(digests) | set(stamps)):
        if path not in stamps:
            problems.append(f"{path}: a source file nobody has reviewed against the inventory; map it to its features, then stamp it")
        elif path not in digests:
            problems.append(f"{path}: reviewed, but it no longer exists; remove its stamp and its features' source entries")
        elif stamps[path] != digests[path]:
            problems.append(f"{path} changed since its mapping was reviewed (features {named.get(path, [])}); review those entries and the "
                            "feature map, then restamp it")
        if path in digests and path not in named:
            problems.append(f"{path}: no feature names this source file, so what it does is outside the inventory")
    return problems


def evaluate(coverage: dict, *, scenarios: dict[str, dict], passed_tests: set[str] | None, passed_scenarios: set[str],
             collected: set[str] | None = None, disk_check=None, required_tools=SIX_TOOLS, qualification_scenarios=(),
             test_check=None, symbol_check=None) -> CoverageResult:
    """Everything above, plus what this run really satisfied. A selection that left something out reports it unsatisfied, never satisfied."""
    result = CoverageResult(inventory_reviewed=bool(coverage.get("inventory_reviewed")))
    result.problems = problems_in_inventory(coverage, scenarios=scenarios, collected=collected, disk_check=disk_check,
                                            required_tools=required_tools, qualification_scenarios=qualification_scenarios,
                                            test_check=test_check, symbol_check=symbol_check)
    features = coverage.get("features", [])
    result.inventoried = len(features)
    result.issues_open = len(_open_issues(coverage))
    surfaces = coverage.get("surfaces", {})
    result.surfaces = {"static": len(surfaces.get("static", {})), "live": sum(len(index) for index in surfaces.get("live", {}).values())}
    for feature in features:
        verifications = verifications_of(feature)
        routine = [item for item in verifications if item.get("kind") in ROUTINE_KINDS]
        pending = [item for item in verifications if item.get("kind") in RELEASE_KINDS]
        row = {"id": feature.get("id"), "tool": feature.get("tool"), "required": bool(feature.get("release_required")), "verifications": []}
        satisfied = bool(routine)
        for item in verifications:
            if item.get("kind") == "behavior":
                done = passed_tests is not None and item.get("test") in passed_tests
            elif item.get("kind") in SCENARIO_KINDS:
                done = item.get("scenario") in passed_scenarios
            else:
                done = False  # never by a routine run
            row["verifications"].append({**item, "satisfied": done})
            if item.get("kind") in ROUTINE_KINDS:
                satisfied = satisfied and done
        row["satisfied"] = satisfied
        row["pending"] = [_pending_label(item) for item in pending]
        result.features.append(row)
        if not feature.get("release_required"):
            continue
        result.required += 1
        if routine:
            result.mapped_required += 1
        else:
            result.unmapped_required.append(str(feature.get("id")))
        if satisfied:
            result.satisfied_required += 1
            if not pending:
                result.release_satisfied_required += 1
        elif routine:
            result.unsatisfied.append(str(feature.get("id")))
        for item in pending:
            waiting = result.release_pending.setdefault(item.get("kind"), [])
            if str(feature.get("id")) not in waiting:  # features, not entries: one feature may need two owner checks
                waiting.append(str(feature.get("id")))
    return result


def _pending_label(item: dict) -> str:
    kind = item.get("kind")
    if kind == "qualification":
        return f"qualification:{item.get('scenario')}"
    if kind == "owner":
        return f"owner:{item.get('check')}"
    return f"planned:{item.get('issue')} (phase {item.get('phase')})"


def report_lines(result: CoverageResult) -> list[str]:
    lines = ["# Coverage", "",
             "These measures are separate on purpose. Mapped proves only that the registered inventory's entries have a target. Satisfied proves what ran here. "
             "Release-pending evidence (qualification, owner checks, planned gaps) is never satisfied by a routine run.", "",
             f"- Inventory reviewed: **{result.inventory_reviewed}** ({result.inventoried} features registered; "
             f"{result.surfaces.get('static', 0)} static and {result.surfaces.get('live', 0)} live surfaces indexed; {result.issues_open} open issues)",
             f"- Required entries mapped: **{result.mapped_required} of {result.required}**",
             f"- Required verifications satisfied in this run: **{result.satisfied_required} of {result.required}**",
             f"- Required entries with nothing release-pending, satisfied here: **{result.release_satisfied_required} of {result.required}**",
             "- Line coverage: not collected", ""]
    if result.problems:
        lines += ["## Problems", "", *[f"- {problem}" for problem in result.problems], ""]
    if result.unmapped_required:
        lines += ["## Required, with no routine evidence at all", "", *[f"- `{item}`" for item in result.unmapped_required], ""]
    if result.release_pending:
        lines += ["## Release-pending", ""]
        for kind, items in sorted(result.release_pending.items()):
            lines.append(f"- {kind}: {len(items)} feature(s): " + ", ".join(f"`{item}`" for item in items))
        lines.append("")
    lines += ["## Features", "", "| Feature | Tool | Required | Satisfied here | Verifications | Pending |", "|---|---|---|---|---|---|"]
    for row in result.features:
        evidence = ", ".join(f"{item.get('kind')}:{item.get('scenario') or item.get('test')}{'' if item['satisfied'] else ' (not here)'}"
                             for item in row["verifications"] if item.get("kind") in ROUTINE_KINDS) or "none mapped"
        lines.append(f"| `{row['id']}` | {row['tool']} | {row['required']} | {row['satisfied']} | {evidence} | {'; '.join(row['pending'])} |")
    return lines
