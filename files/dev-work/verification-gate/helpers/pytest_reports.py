"""Reading what a pytest stage reports and deciding what it may be taken to mean. Never PASS by omission.

Three independent records meet here: the child's exit status, its JUnit file, and the session probe it wrote from inside
(``files/tests/gate_session_probe.py``). A stage passes only when all three exist and agree. Exit status 0 alone is never
enough: a test that never ran, a stale report and a wrapper hiding a failing child must all land somewhere other than PASS.

pytest's own exit statuses (pytest 9.1.1, ``pytest.ExitCode``): 0 OK, 1 TESTS_FAILED, 2 INTERRUPTED (also collection
errors), 3 INTERNAL_ERROR, 4 USAGE_ERROR (an unknown selector lands here), 5 NO_TESTS_COLLECTED.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

EXIT_OK, EXIT_TESTS_FAILED, EXIT_INTERRUPTED, EXIT_INTERNAL, EXIT_USAGE, EXIT_NO_TESTS = 0, 1, 2, 3, 4, 5


def junit_id(nodeid: str) -> str:
    """The ``classname::name`` a node id becomes in pytest's JUnit report (``mangle_test_address``)."""
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]) + "::" + names[-1]


def read_junit(path: Path, expected_suite: str | None = None) -> dict:
    """Totals and identities from a JUnit report, or why it cannot be trusted. Missing or truncated is never a pass."""
    path = Path(path)
    if not path.is_file():
        return {"valid": False, "problem": "missing"}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return {"valid": False, "problem": f"unreadable or truncated ({exc})"}
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = root.findall("testsuite")
    else:
        suites = []
    if not suites:
        return {"valid": False, "problem": f"no <testsuite> element (root is <{root.tag}>)"}
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    try:
        for suite in suites:
            for key in totals:
                totals[key] += int(suite.get(key, "0"))
    except ValueError as exc:
        return {"valid": False, "problem": f"non-numeric total ({exc})"}
    ids: list[str] = []
    found = {"failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for case in suite.iter("testcase"):
            ids.append(f"{case.get('classname')}::{case.get('name')}")
            found["failures"] += len(case.findall("failure"))
            found["errors"] += len(case.findall("error"))
            found["skipped"] += len(case.findall("skipped"))
    report = {"valid": True, **totals, "ids": ids, "suite_names": [suite.get("name") for suite in suites]}
    problems = []
    if expected_suite is not None and report["suite_names"] != [expected_suite]:
        problems.append(f"the report belongs to {report['suite_names']}, not this stage ({expected_suite}): stale or foreign")
    if len(ids) != totals["tests"]:
        problems.append(f"it declares {totals['tests']} tests but lists {len(ids)}")
    if any(found[key] != totals[key] for key in found):
        problems.append(f"its totals {({k: totals[k] for k in found})} disagree with its testcases {found}")
    if len(set(ids)) != len(ids):
        problems.append(f"{len(ids) - len(set(ids))} duplicated testcase(s)")
    report["integrity_problems"] = problems
    return report


def junit_summary(report: dict) -> dict:
    """A report as stored in results.json: its totals and verdict, without the thirteen thousand identities."""
    return {key: value for key, value in report.items() if key != "ids"}


@dataclass
class Probe:
    """One session's own record. ``valid`` is False until it holds a start and a finish."""

    valid: bool = False
    problem: str | None = None
    session: dict = field(default_factory=dict)
    exit: int | None = None
    finish_mode: str | None = None
    collected: list[str] | None = None
    deselected: list[str] = field(default_factory=list)
    collect_errors: list[dict] = field(default_factory=list)
    collect_skips: list[dict] = field(default_factory=list)
    drifts: list[dict] = field(default_factory=list)
    outcomes: dict[str, dict] = field(default_factory=dict)
    skips: list[dict] = field(default_factory=list)
    xfails: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    def executed(self) -> set[str]:
        return set(self.outcomes)


def read_probe(path: Path, expected_token: str | None = None, *, require_finish: bool = True) -> Probe:
    """Parse a session probe file. A missing file, a token from another stage or a session that never finished is invalid."""
    probe = Probe()
    path = Path(path)
    if not path.is_file():
        probe.problem = "missing"
        return probe
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        probe.problem = f"unreadable ({type(exc).__name__})"
        return probe
    failed = errors = passed = skipped = xfailed = xpassed = 0
    for number, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except ValueError:
            probe.problem = f"line {number} is not JSON: truncated or corrupt"
            return probe
        kind = row.get("e")
        if kind == "session-start":
            probe.session = row
        elif kind == "collected":
            probe.collected = list(row["ids"])
        elif kind == "deselected":
            probe.deselected.extend(row["ids"])
        elif kind == "collect-error":
            probe.collect_errors.append(row)
        elif kind == "collect-skip":
            probe.collect_skips.append(row)
        elif kind == "mode-drift":
            probe.drifts.append(row)
        elif kind == "session-finish":
            probe.exit, probe.finish_mode = int(row["exit"]), row.get("mode")
        elif kind == "r":
            outcome = probe.outcomes.setdefault(row["id"], {})
            outcome[row["w"]] = row["o"]
            is_xfail = "xfail" in row
            if row["o"] == "failed":
                if row["w"] == "call":
                    failed += 1
                else:
                    errors += 1
            elif row["o"] == "skipped":
                if is_xfail:
                    xfailed += 1
                    probe.xfails.append({"id": row["id"], "reason": row["xfail"]})
                else:
                    skipped += 1
                    probe.skips.append({"id": row["id"], "reason": row.get("reason", "")})
            elif row["w"] == "call":
                if is_xfail:
                    xpassed += 1
                    probe.xfails.append({"id": row["id"], "reason": row["xfail"], "xpassed": True})
                else:
                    passed += 1
    probe.counts = {"collected": len(probe.collected or []), "executed": len(probe.outcomes), "passed": passed,
                    "failed": failed, "errors": errors, "skipped": skipped, "xfailed": xfailed, "xpassed": xpassed,
                    "deselected": len(probe.deselected)}
    if not probe.session:
        probe.problem = "no session-start record"
    elif expected_token is not None and probe.session.get("token") != expected_token:
        probe.problem = f"it belongs to another stage ({probe.session.get('token')!r}), not {expected_token!r}"
    elif require_finish and probe.exit is None:
        probe.problem = "the session never reported its finish"
    else:
        probe.valid = True
    return probe


@dataclass
class Verdict:
    status: str
    detail: str


def _last_line(log_tail: str) -> str:
    return next((line.strip() for line in reversed(log_tail.splitlines()) if line.strip()), "(no output)")


def judge_stage(returncode, ended: str, junit: dict, probe: Probe, log_tail: str, *, child_pid: int | None = None,
                probe_required: bool = True) -> Verdict:
    """The verdict on one pytest run from every record it left. Reasons are ordered from what failed to what is missing."""
    summary = _last_line(log_tail)
    if ended in ("timeout", "stall"):
        return Verdict("FAIL", f"{ended}: the supervisor stopped the owned tree (exit {returncode}); last output: {summary}")
    if ended == "error":
        return Verdict("BLOCKED", f"the child could not be started; {summary}")
    if returncode == EXIT_NO_TESTS:
        return Verdict("NOT RUN", "no tests collected (an empty gate is not valid)")
    if returncode == EXIT_USAGE:
        return Verdict("NOT RUN", f"exit {returncode}: an unknown selector or a usage error, and no test ran: {summary}")
    if returncode != EXIT_OK:
        return Verdict("FAIL", f"exit {returncode}: {summary}")
    # The child said 0. Now every other record has to agree before that means anything.
    if not junit.get("valid"):
        return Verdict("NOT RUN", f"exit 0 but the JUnit report is {junit.get('problem')}")
    if junit["tests"] == 0:
        return Verdict("NOT RUN", "exit 0 but the JUnit report records no tests")
    if junit["failures"] or junit["errors"]:
        return Verdict("FAIL", f"exit 0 but the JUnit report records {junit['failures']} failure(s) "
                               f"and {junit['errors']} error(s)")
    if junit["integrity_problems"]:
        return Verdict("FAIL", "exit 0 but the JUnit report does not hold together: " + "; ".join(junit["integrity_problems"]))
    if not probe_required:
        return Verdict("PASS", summary)
    if not probe.valid:
        return Verdict("NOT RUN", f"exit 0 but the session record is {probe.problem}")
    if child_pid is not None and child_pid not in (probe.session.get("pid"), probe.session.get("ppid")):
        return Verdict("FAIL", f"the session record comes from process {probe.session.get('pid')}, not this child ({child_pid})")
    if probe.exit != EXIT_OK:
        return Verdict("FAIL", f"exit 0 masks the session's own exit status {probe.exit}")
    if probe.collect_errors:
        return Verdict("FAIL", f"exit 0 but {len(probe.collect_errors)} collection error(s) were recorded")
    if probe.counts["failed"] or probe.counts["errors"]:
        return Verdict("FAIL", f"exit 0 but the session recorded {probe.counts['failed']} failure(s) and "
                               f"{probe.counts['errors']} error(s)")
    if probe.deselected:
        return Verdict("FAIL", f"{len(probe.deselected)} test(s) were deselected; the gate never asks for that")
    if probe.collected is None or set(probe.collected) != probe.executed():
        return Verdict("FAIL", "collected and executed tests differ: " + _difference(probe.collected or [], probe.executed()))
    if not probe.executed():
        return Verdict("NOT RUN", "exit 0 but the session executed no tests")
    # A module skipped as a whole is a testcase of the report and no test of the session.
    module_skips = {junit_id(row["id"]) for row in probe.collect_skips}
    mapped = {junit_id(nodeid) for nodeid in probe.executed()} | module_skips
    if mapped != set(junit["ids"]):
        return Verdict("FAIL", "the JUnit report and the session record list different tests: "
                               + _difference(sorted(mapped), set(junit["ids"])))
    expected_tests = probe.counts["executed"] + len(module_skips)
    expected_skips = probe.counts["skipped"] + probe.counts["xfailed"] + len(module_skips)
    if junit["tests"] != expected_tests or junit["skipped"] != expected_skips:
        return Verdict("FAIL", f"the JUnit totals ({junit['tests']} tests, {junit['skipped']} skipped) disagree with the "
                               f"session record {probe.counts}")
    return Verdict("PASS", summary)


def _difference(expected, actual) -> str:
    expected, actual = set(expected), set(actual)
    missing, extra = sorted(expected - actual), sorted(actual - expected)
    return f"{len(missing)} only on the left {missing[:5]}, {len(extra)} only on the right {extra[:5]}"


def error_mode_findings(probe: Probe, required: int, critical: int) -> list[str]:
    """Why a session's error mode broke the gate's guarantee. A lost non-critical flag repaired at a boundary is not one."""
    problems = []
    start = probe.session.get("mode")
    if start is None:
        return ["the session recorded no error mode"]
    if int(start, 16) & required != required:
        problems.append(f"the pytest process started at {start}, without the flags the gate established: not inherited")
    for drift in probe.drifts:
        if int(drift["found"], 16) & critical != critical:
            problems.append(f"{drift['found']} at {drift['where']}: the flag that keeps an invalid executable from opening "
                            "a dialog was clear")
    return problems


def module_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def partition_problems(ordinary: list[str], guarded: dict[str, list[str]], membership: dict[str, list[str]],
                       disk_modules: set[str], tests_prefix: str, skipped_modules=frozenset(),
                       known_empty=frozenset()) -> list[str]:
    """Ordinary and guarded collections must be disjoint, and together must account for every test module on disk.

    ``membership`` is each group's exact module list. A module moved to the ordinary suite, dropped from a group, listed
    twice or collected nowhere is a defect in the partition, not a smaller test run. ``known_empty`` names modules the policy
    says hold no pytest test, and a listed module that starts collecting tests is a stale entry, so the list cannot rot.
    """
    problems = []
    ordinary_set = set(ordinary)
    if len(ordinary_set) != len(ordinary):
        problems.append(f"{len(ordinary) - len(ordinary_set)} duplicated node(s) in the ordinary collection")
    guarded_modules: dict[str, str] = {}
    all_guarded: set[str] = set()
    for group, modules in membership.items():
        for module in modules:
            name = f"{tests_prefix}/{module}"
            if name in guarded_modules:
                problems.append(f"{module} is listed in both {guarded_modules[name]} and {group}")
            guarded_modules[name] = group
    for group, nodes in guarded.items():
        node_set = set(nodes)
        if len(node_set) != len(nodes):
            problems.append(f"{len(nodes) - len(node_set)} duplicated node(s) in group {group}")
        if node_set & all_guarded:
            problems.append(f"group {group} repeats {len(node_set & all_guarded)} node(s) of another group")
        all_guarded |= node_set
        collected_modules = {module_of(node) for node in nodes}
        listed = {f"{tests_prefix}/{module}" for module in membership.get(group, [])}
        for extra in sorted(collected_modules - listed):
            problems.append(f"group {group} collected {extra}, which it does not list")
        for omitted in sorted(listed - collected_modules - set(skipped_modules)):
            problems.append(f"group {group} lists {omitted} but collected nothing from it")
    overlap = ordinary_set & all_guarded
    if overlap:
        problems.append(f"{len(overlap)} node(s) are in both the ordinary and the guarded collections: {sorted(overlap)[:5]}")
    moved = sorted({module_of(node) for node in ordinary_set} & set(guarded_modules))
    for module in moved:
        problems.append(f"{module} belongs to guarded group {guarded_modules[module]} but was collected as ordinary")
    covered = {module_of(node) for node in ordinary_set | all_guarded} | set(skipped_modules)
    empty = {f"{tests_prefix}/{module}" for module in known_empty}
    for module in sorted(empty & covered):
        problems.append(f"{module} is listed as holding no test, but tests were collected from it: remove the entry")
    for module in sorted(empty - disk_modules):
        problems.append(f"{module} is listed as holding no test, but it is not on disk: remove the entry")
    for module in sorted(disk_modules - covered - empty):
        problems.append(f"{module} is on disk but neither collection holds a test from it")
    for module in sorted(covered - disk_modules):
        problems.append(f"{module} was collected but is not a test module on disk")
    return problems


def skip_policy_problems(skips: list[dict], xfails: list[dict], policy: list[dict] | None) -> tuple[list[str], dict]:
    """Every skip must match a reason the policy names, within its limit. ``policy`` None means no policy for this platform."""
    tally: dict[str, int] = {}
    problems: list[str] = []
    for xfail in xfails:
        problems.append(f"unexpected {'xpass' if xfail.get('xpassed') else 'xfail'}: {xfail['id']} ({xfail['reason'][:120]})")
    if policy is None:
        return problems, {"unjudged": len(skips)}
    compiled = [(rule["id"], re.compile(rule["pattern"]), rule["max"]) for rule in policy]
    for skip in skips:
        for rule_id, pattern, _limit in compiled:
            if pattern.search(skip["reason"]):
                tally[rule_id] = tally.get(rule_id, 0) + 1
                break
        else:
            problems.append(f"unexpected skip: {skip['id']} ({skip['reason'][:160]})")
    for rule_id, _pattern, limit in compiled:
        if tally.get(rule_id, 0) > limit:
            problems.append(f"{tally[rule_id]} skips under {rule_id!r}, more than the {limit} the policy allows")
    return problems, tally
