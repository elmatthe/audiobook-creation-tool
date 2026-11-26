"""Turning a request into tests: ``--test`` selectors, and the routing of a changed-file set (v0.8.2 Phase 1A-1).

A selector is a test identity, never a command fragment: it names a module under ``files/tests`` and optionally a node in
it, and nothing else gets through.

Changed routing (:func:`route_changes`) never widens to the whole suite and never quietly selects less. Each changed path
is routed by its kind -- a changed test, a test helper or suite-wide infrastructure, Python source through the reverse
import closure (``helpers/evidence_ledger.py`` ``Closures``, built once per snapshot) and the reviewed feature-to-source
mapping, documents and configuration through the policy's static checks and routes -- and every path that cannot be
routed completely becomes a selection gap that keeps the changed scope from being complete: no route, a reverse closure
over the policy budget, a parse failure, a deleted test, a dynamic or platform obligation. Gaps keep the safe checks that
were found; they are never turned into "every test".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from helpers.execution_plan import Entry

_SELECTOR = re.compile(r"^files/tests/test_[A-Za-z0-9_.\-]+\.py(::[^\x00-\x1f;&|<>`$\"']+)?$")
TEST_PREFIX = "files/tests/"
GATE_PREFIX = "files/dev-work/verification-gate/"
PYTHON_ROOTS = ("scripts/", "files/tests/", GATE_PREFIX, "files/dev-tools/")


class SelectorError(ValueError):
    """A ``--test`` value that is not a test identity."""


def parse_selector(raw: str) -> str:
    """The normalized selector. A path separator is normalized in the file part only; a node id is taken as written."""
    path, separator, node = raw.partition("::")
    candidate = path.replace("\\", "/") + separator + node
    if candidate != candidate.strip() or not _SELECTOR.match(candidate) or ".." in path:
        raise SelectorError(f"{raw!r} is not a test identity (expected files/tests/test_<name>.py or "
                            "files/tests/test_<name>.py::<node>)")
    return candidate


def module_name(selector: str) -> str:
    return selector.split("::", 1)[0].rsplit("/", 1)[-1]


def in_suite_order(selectors) -> list[str]:
    """Selectors by module name, as the suite itself runs: tests here are sensitive to import order."""
    return sorted(dict.fromkeys(selectors), key=lambda item: (module_name(item), item))


def matches(path: str, entry: str) -> bool:
    """An exact path, or a directory entry (ending in ``/``) at a path-component boundary."""
    return path.startswith(entry) if entry.endswith("/") else path == entry


def journeys_for_changes(paths, routes: dict, known: list[str]) -> list[str]:
    """The native and real-media journeys a change reaches through ``acceptance.journey_routes``. Since Phase 1A-1 these are
    suggested native obligations of a changed plan, never journeys it runs. An id the policy no longer knows is dropped."""
    chosen: list[str] = []
    for path in sorted(paths):
        for prefix, scenarios in routes.items():
            if path == prefix or path.startswith(prefix):
                chosen.extend(known if scenarios == "all" else scenarios)
    known_set = set(known)
    return [item for item in dict.fromkeys(chosen) if item in known_set]


# --------------------------------------------------------------------------- #
#  Reverse dependencies, built once per snapshot
# --------------------------------------------------------------------------- #
class ReverseIndex:
    """Which test modules reach a file through their static import closure. Every test module's closure is computed once
    (``Closures`` memoises each file's edges), and the reverse map is built once from those closures."""

    def __init__(self, root: Path, closures) -> None:
        self.root = Path(root)
        self.closures = closures
        self.tests = sorted(f"{TEST_PREFIX}{path.name}" for path in (self.root / TEST_PREFIX).glob("test_*.py"))
        self.reach: dict[str, set[str]] = {}
        self.closure_of: dict[str, set[str]] = {}
        for test in self.tests:
            files = closures.closure([test])
            self.closure_of[test] = files
            for path in files:
                self.reach.setdefault(path, set()).add(test)

    def consumers(self, path: str) -> set[str]:
        return set(self.reach.get(path, set())) - {path}

    def consumers_of_missing(self, path: str) -> set[str]:
        """Tests reaching a module that no longer exists: by the dotted names their closures import (resolved or not) and
        by literal file names, so a deleted or renamed-away module still finds who used it."""
        stem = path.rsplit("/", 1)[-1].removesuffix(".py")
        dotted = set()
        for root in PYTHON_ROOTS:
            if path.startswith(root):
                relative = path[len(root):].removesuffix(".py").removesuffix("/__init__")
                dotted.add(relative.replace("/", "."))
        dotted.add(stem)
        found = set()
        for test, files in self.closure_of.items():
            for name in (test, *files):
                imported = self.closures.names.get(name, set())
                if any(item == d or item.endswith("." + d) or item.startswith(d + ".") for item in imported for d in dotted):
                    found.add(test)
                    break
        return found

    def unparsed_tests(self) -> list[str]:
        return sorted(name for name in self.closures.unparsed if name.startswith(TEST_PREFIX))


@dataclass
class Routing:
    """A changed plan's selection: what runs, which static checks apply, what is owed, what is not resolved."""

    relevant: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    static_checks: list[str] = field(default_factory=list)
    reasons: list[tuple[str, str]] = field(default_factory=list)
    obligations: list[Entry] = field(default_factory=list)
    gaps: list[Entry] = field(default_factory=list)
    change: dict = field(default_factory=dict)
    routes: dict[str, list[str]] = field(default_factory=dict)

    def record(self) -> dict:
        return {**self.change, "routed": dict(self.routes), "static_checks": list(self.static_checks)}

    def select(self, path: str, tests, why: str) -> None:
        for test in tests:
            if test not in self.tests:
                self.tests.append(test)
            self.reasons.append((test, f"{path}: {why}"))
        self.routes.setdefault(path, []).extend(f"test {test}" for test in tests)

    def check(self, path: str, checks, why: str) -> None:
        for check in checks:
            if check not in self.static_checks:
                self.static_checks.append(check)
            self.reasons.append((check, f"{path}: {why}"))
        self.routes.setdefault(path, []).extend(f"check {check}" for check in checks)

    def gap(self, path: str, reason: str, kind: str = "unresolved") -> None:
        self.gaps.append(Entry(path, reason, kind))
        self.routes.setdefault(path, []).append(f"gap {kind}")

    def owe(self, subject: str, reason: str, kind: str) -> None:
        if not any(item.subject == subject and item.kind == kind for item in self.obligations):
            self.obligations.append(Entry(subject, reason, kind))


def _first(policy_map: dict, path: str):
    return next((value for key, value in policy_map.items() if matches(path, key)), None)


def route_changes(changes, policy: dict, coverage: dict, index: ReverseIndex, *, native_platform: str,
                  known_journeys: list[str]) -> Routing:
    """Route a :class:`helpers.git_changes.ChangeSet`. Pure apart from reading the index it is given."""
    rules = policy.get("changed", {})
    budget = int(rules.get("max_routed_modules", 40))
    routing = Routing(change=changes.record())
    for violation in changes.violations:
        routing.gap("local-only", violation, "policy-violation")
    for problem in changes.problems:
        routing.gap(problem.split(":", 1)[0], problem, "unreadable")
    deleted = {change.old_path for change in changes.changes if change.status == "R" and change.old_path}
    deleted |= {change.path for change in changes.changes if change.status == "D"}
    features = coverage.get("features", [])
    by_source: dict[str, list[dict]] = {}
    for feature in features:
        for source in feature.get("source", []):
            by_source.setdefault(source.get("path", ""), []).append(feature)
    for test in index.unparsed_tests():
        routing.gap(test, "this test module could not be parsed, so what it depends on is unknown", "unparsed")
    for path in changes.paths():
        routing.relevant.append(path)
        gone = path in deleted or not (index.root / path).exists()
        _route_one(path, gone, rules, by_source, features, index, routing, budget, native_platform)
        for journey in journeys_for_changes([path], policy.get("acceptance", {}).get("journey_routes", {}), known_journeys):
            routing.owe(f"journey:{journey}", f"{path}: suggested native journey (qualification or full)", "native")
    return routing


def _feature_tests(feature: dict) -> list[str]:
    tests = list(feature.get("selection", []))
    tests += [item["test"] for item in (feature.get("verification") or {}).get("all_of", [])
              if item.get("kind") == "behavior" and item.get("test")]
    return list(dict.fromkeys(tests))


def _platform_obligation(path: str, features: list[dict], native: str, routing: Routing) -> None:
    parts = set(re.split(r"[/_.\-]", path.lower()))
    targets = set()
    if "macos" in parts or "darwin" in parts:
        targets.add("macos")
    if "windows" in parts or "win32" in parts:
        targets.add("windows")
    for feature in features:
        targets.update(feature.get("applicability", {}).get("platforms", []))
    for target in sorted(targets - {native}):
        routing.owe(f"platform:{target}", f"{path}: needs native {target} verification; a {native} result cannot discharge it",
                    "platform")


def _route_one(path: str, gone: bool, rules: dict, by_source: dict, all_features: list[dict], index: ReverseIndex,
               routing: Routing, budget: int, native: str) -> None:
    features = by_source.get(path, [])
    routed = _first(rules.get("routes", {}), path)
    static = _first(rules.get("static", {}), path)
    owed = _first(rules.get("obligations", {}), path)
    if static:
        routing.check(path, static, "static check route")
    if owed:
        routing.owe(f"{owed.get('kind', 'archive')}:{path}", f"{path}: {owed.get('why', '')}", owed.get("kind", "archive"))
    if routed:
        routing.select(path, routed, "policy route")
    _platform_obligation(path, features, native, routing)
    suite_wide = _first(rules.get("suite_wide", {}), path)
    if path.startswith(TEST_PREFIX) and path.rsplit("/", 1)[-1].startswith("test_") and path.endswith(".py"):
        if not gone:
            routing.select(path, [path], "a changed test")
            return
        # A deleted test never satisfies its own obligation: route what it verified, or report the gap.
        surviving = sorted({test for feature in _features_naming(path, all_features) for test in _feature_tests(feature)
                            if test.split("::", 1)[0] != path and (index.root / test.split("::", 1)[0]).is_file()})
        if surviving:
            routing.select(path, surviving, "the surviving tests of the features the deleted test verified")
        else:
            routing.gap(path, "a deleted test: no surviving test or feature route covers what it verified", "deleted-test")
        return
    if suite_wide is not None:
        routing.select(path, suite_wide, "representative controls for suite-wide test infrastructure")
        routing.gap(path, "suite-wide test infrastructure: every test depends on it; representative controls are selected and "
                          "a broader regression run is owed", "over-budget")
        return
    if path.endswith(".py") and path.startswith(PYTHON_ROOTS):
        if path in index.closures.unparsed:
            routing.gap(path, "it could not be parsed, so its consumers are unknown", "unparsed")
        consumers = index.consumers_of_missing(path) if gone else index.consumers(path)
        mapped = sorted({test for feature in features for test in _feature_tests(feature)
                         if (index.root / test.split("::", 1)[0]).is_file()})
        if path.startswith(GATE_PREFIX):
            routing.select(path, rules.get("gate_controls", []), "the gate's own negative controls")
        if mapped:
            routing.select(path, mapped, "the reviewed feature mapping of this source")
        if len(consumers) > budget:
            routing.gap(path, f"{len(consumers)} test modules reach it, over the {budget}-module budget; the reviewed "
                              "feature tests are selected and a regression of the affected components is owed",
                        "over-budget")
            for feature in features:
                routing.owe(f"component:{feature.get('tool')}", f"{path}: regression of the affected component", "regression")
            return
        if consumers:
            routing.select(path, sorted(consumers), "reverse import closure" + (" of the deleted module" if gone else ""))
            return
        if not (mapped or routed or static):
            routing.gap(path, ("a deleted module that no test imported" if gone else "no test reaches this source "
                               "(dynamic import, subprocess target or untested)"), "unmapped")
        return
    if not (routed or static or owed):
        routing.gap(path, "no policy route covers this path", "unmapped")


def _features_naming(test: str, features: list[dict]) -> list[dict]:
    return [feature for feature in features if any(item.split("::", 1)[0] == test for item in _feature_tests(feature))]
