"""Turning a request into tests: ``--test`` selectors and the changed-area selection. Pure functions over given data.

A selector is a test identity, never a command fragment: it names a module under ``files/tests`` and optionally a node in
it, and nothing else gets through. A changed path that cannot be traced to tests widens the selection to everything rather
than quietly selecting less; zero tests is never what a change maps to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SELECTOR = re.compile(r"^files/tests/test_[A-Za-z0-9_.\-]+\.py(::[^\x00-\x1f;&|<>`$\"']+)?$")


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


@dataclass
class ChangedSelection:
    conservative_full: bool = False
    tests: list[str] = field(default_factory=list)
    mapped: dict[str, list[str]] = field(default_factory=dict)
    ignored: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def select_for_changes(paths, policy: dict, test_sources: dict[str, str]) -> ChangedSelection:
    """Map changed repository paths to test modules.

    ``policy`` is the ``changed`` block of verification.json; ``test_sources`` maps each test module's repository path to
    its text. The reverse dependency is a word match of the module's stem in test source: a superset on purpose, cheap, and
    wrong only in the safe direction. Anything without a route (unknown path, shared code, a source no test names) selects
    everything and says why.
    """
    selection = ChangedSelection()
    selected: set[str] = set(policy.get("always", []))
    for path in sorted(paths):
        if any(path == prefix or path.startswith(prefix) for prefix in policy.get("no_selection", [])):
            selection.ignored.append(path)
            continue
        routed = next((tests for prefix, tests in policy.get("routes", {}).items()
                       if path == prefix or path.startswith(prefix)), None)
        if routed is not None:
            selected.update(routed)
            selection.mapped[path] = list(routed)
            continue
        if any(path == prefix or path.startswith(prefix) for prefix in policy.get("full_on", [])):
            selection.conservative_full = True
            selection.reasons.append(f"{path}: shared by every tool, so every test is selected")
            continue
        if path in test_sources:
            selected.add(path)
            selection.mapped[path] = [path]
            continue
        if path.startswith("scripts/") and path.endswith(".py"):
            stem = path.rsplit("/", 1)[-1][:-3]
            word = re.compile(rf"\b{re.escape(stem)}\b")
            dependants = sorted(name for name, text in test_sources.items() if word.search(text))
            if dependants:
                selected.update(dependants)
                selection.mapped[path] = dependants
                continue
            selection.conservative_full = True
            selection.reasons.append(f"{path}: no test names this module, so every test is selected")
            continue
        selection.conservative_full = True
        selection.reasons.append(f"{path}: no selection rule covers this path, so every test is selected")
    selection.tests = in_suite_order(selected)
    return selection


def journeys_for_changes(paths, routes: dict, known: list[str]) -> list[str]:
    """The native and real-media journeys a change reaches. A route is a list of scenario ids, or "all"; an id the policy no longer knows is dropped
    here only because the policy check names it. Nothing else widens or narrows what ``select_for_changes`` chose for the test suite."""
    chosen: list[str] = []
    for path in sorted(paths):
        for prefix, scenarios in routes.items():
            if path == prefix or path.startswith(prefix):
                chosen.extend(known if scenarios == "all" else scenarios)
    known_set = set(known)
    return [item for item in dict.fromkeys(chosen) if item in known_set]

