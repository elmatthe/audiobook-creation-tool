"""The one explicit execution plan of a gate invocation (v0.8.2 Phase 1A-1; plan Revision 5, section 1A-1).

A request (a mode and its selectors) resolves into an immutable :class:`ExecutionPlan` before anything runs. Every
executable collection defaults to empty: an empty collection selects nothing, never everything. Only :func:`full_plan`
may name the release partition (``ORDINARY_PARTITION`` with ``release_partition=True``). The plan states what was asked
for, what will run, which guards are owed, what is withheld and why, which native, qualification and owner obligations
stay pending, and the selection gaps that keep a scope from being complete. Resolution never imports a test module: test
classification is static (``helpers/effects.py``) and Git facts come from ``helpers/git_changes.py``.

:func:`validate` runs again at the execution boundary (``verify.py``), so a plan built or changed anywhere else cannot
carry an implicit whole scope, a journey or scenario into a routine mode, a heavyweight effect into routine execution, or
a routine scope without its required guard.

Selection-level status (:attr:`ExecutionPlan.status`), kept apart on purpose:

  COMPLETE    every requested item resolved to executable work; separate native, qualification or owner obligations may
              still be pending, and are listed as such, never as satisfied.
  INCOMPLETE  an explicitly requested test is withheld, a selection gap is unresolved, or only an added guard would run for
              work that was asked for (a guard never stands in for the requested scope).
  NOT RUN     nothing executable: a true empty selection (changed with no relevant change).
  BLOCKED     the request targets another native platform.

A plan missing its required guard is not a status: it is a construction defect, refused by :func:`validate`.

Activation (Phase 1A-1): execution stays where the interim policy (GATE.md) already allowed it -- ``focused --test``
(routine) and ``full`` / ``qualification --scenario`` (owner authorization only). ``quick``, ``changed``, ``regression``,
``focused --feature`` and ``qualification --journey`` resolve and print their plans only (``executable_now`` False) until
Phase 1A-3 integrates their execution and evidence; Phase 1A-2 adds admission for heavyweight execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable

from helpers import repo_files

MODES = ("quick", "focused", "changed", "regression", "qualification", "full")
ROUTINE_MODES = frozenset({"quick", "focused", "changed", "regression"})
#: The whole ordinary suite. Only the full constructor may name it, and only together with ``release_partition``.
ORDINARY_PARTITION = "files/tests"
#: Static checks a plan may name (``verification.json`` ``quick.checks`` describes each).
STATIC_CHECKS = ("docnames", "docs", "doc-links", "json-validity", "deps", "config", "import-smoke")
STATUSES = ("COMPLETE", "INCOMPLETE", "NOT RUN", "BLOCKED")
_SELECTOR = re.compile(r"^files/tests/test_[A-Za-z0-9_.\-]+\.py(::[^\x00-\x1f;&|<>`$\"']+)?$")
#: Why a mode or selector family does not execute in this checkpoint. Removal criterion: Phase 1A-3 activation.
NOT_ACTIVATED = ("resolves its plan only: execution of this scope is activated in Phase 1A-3 once its admission and "
                 "evidence controls are integrated (GATE.md)")


class PlanError(ValueError):
    """An invalid request or an invalid plan: exit 64, nothing runs."""


#: The fields :meth:`ExecutionPlan.record` writes from the plan itself. Supplemental ``facts`` may never use one of these
#: names (Phase 1A-1 R1, M3): a fact is context, never a second value for an authoritative field.
RECORD_KEYS = frozenset({"format", "kind", "mode", "status", "requested", "ordinary", "guarded", "journeys", "scenario",
                         "static_checks", "guards", "scope", "effects", "release_partition", "native_platform",
                         "target_platforms", "executable_now", "activation", "obligations", "withheld", "gaps", "reasons",
                         "candidate", "policy_digest"})


def freeze(value):
    """A read-only deep copy: mappings become ``MappingProxyType``, lists, tuples and sets become tuples."""
    if isinstance(value, (dict, MappingProxyType)):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(freeze(item) for item in value))
    return value


def thaw(value):
    """The JSON-shaped copy of a :func:`freeze` value."""
    if isinstance(value, (dict, MappingProxyType)):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class Entry:
    """One withheld item, pending obligation or selection gap, with its reason."""

    subject: str
    reason: str
    kind: str = ""
    effects: tuple[str, ...] = ()
    requested: bool = False

    def record(self) -> dict:
        row = {"subject": self.subject, "kind": self.kind, "reason": self.reason}
        if self.effects:
            row["effects"] = list(self.effects)
        if self.requested:
            row["requested"] = True
        return row


@dataclass(frozen=True)
class Request:
    """A normalized request. The CLI parses and refuses shapes first; :func:`resolve` checks them again."""

    mode: str
    tests: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    scenario: str | None = None
    journeys: tuple[str, ...] = ()
    base: str | None = None

    def selectors(self) -> tuple[str, ...]:
        return (*(f"test:{t}" for t in self.tests), *(f"feature:{f}" for f in self.features),
                *(f"component:{c}" for c in self.components), *((f"scenario:{self.scenario}",) if self.scenario else ()),
                *(f"journey:{j}" for j in self.journeys), *((f"base:{self.base}",) if self.base else ()))


@dataclass(frozen=True)
class EffectResult:
    """What the static effect classification made of a list of pytest selectors (``helpers/effects.py``)."""

    executable: tuple[str, ...] = ()
    withheld: tuple[Entry, ...] = ()
    obligations: tuple[Entry, ...] = ()
    gaps: tuple[Entry, ...] = ()


@dataclass(frozen=True)
class ExecutionPlan:
    mode: str
    kind: str
    requested: tuple[str, ...]
    native_platform: str
    target_platforms: tuple[str, ...]
    candidate: dict = field(default_factory=dict, compare=False)
    policy_digest: str = ""
    static_checks: tuple[str, ...] = ()
    guards: tuple[str, ...] = ()
    scope: tuple[str, ...] = ()
    ordinary: tuple[str, ...] = ()
    guarded: tuple[tuple[str, tuple[str, ...]], ...] = ()
    journeys: tuple[str, ...] = ()
    scenario: str | None = None
    effects: tuple[str, ...] = ()
    obligations: tuple[Entry, ...] = ()
    withheld: tuple[Entry, ...] = ()
    gaps: tuple[Entry, ...] = ()
    reasons: tuple[tuple[str, str], ...] = ()
    release_partition: bool = False
    executable_now: bool = False
    activation: str = ""
    facts: dict = field(default_factory=dict, compare=False)

    _TUPLES = ("requested", "target_platforms", "static_checks", "guards", "scope", "ordinary", "journeys", "effects",
               "obligations", "withheld", "gaps")

    def __post_init__(self) -> None:
        """Identity and safety fields are immutable copies (Phase 1A-1 R1, M3): a caller's list or dict changed later never
        changes the plan, and a supplemental fact can never stand in for an authoritative field."""
        for name in self._TUPLES:
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "reasons", tuple(tuple(item) for item in self.reasons))
        object.__setattr__(self, "guarded", tuple((group, tuple(targets)) for group, targets in self.guarded))
        object.__setattr__(self, "candidate", freeze(dict(self.candidate or {})))
        facts = dict(self.facts or {})
        forged = sorted(set(facts) & RECORD_KEYS)
        if forged:
            raise PlanError(f"supplemental facts may not replace the authoritative plan field(s) {forged}")
        object.__setattr__(self, "facts", freeze(facts))

    # ------------------------------------------------------------------ derived
    def pytest_selectors(self) -> tuple[str, ...]:
        return (*self.ordinary, *(target for _group, targets in self.guarded for target in targets))

    def behavioural(self) -> tuple[str, ...]:
        """The requested scope's own executable pytest selectors (``scope``), before guards were added: what the request
        actually runs. A guard counts only where it was itself requested."""
        return self.scope

    @property
    def status(self) -> str:
        if self.native_platform not in self.target_platforms:
            return "BLOCKED"
        if (self.candidate or {}).get("violations"):
            return "BLOCKED"  # Phase 1A-1 R2 (C2): tracked local-only paths; nothing runs, and no name is disclosed
        if self.gaps or any(item.requested for item in self.withheld):
            return "INCOMPLETE"
        work = bool(self.pytest_selectors() or self.static_checks or self.journeys or self.scenario)
        if not work:
            return "NOT RUN"
        if self.requested and not (self.behavioural() or self.static_checks or self.journeys or self.scenario):
            return "INCOMPLETE"  # only a guard would run for requested work
        return "COMPLETE"

    def record(self) -> dict:
        """The plan as ``selection.json`` and ``--plan`` show it. ``kind``/``ordinary``/``guarded``/``journeys``/``requested``
        keep their earlier meaning for readers of older runs; ``ordinary`` is a list, never null."""
        return {**thaw(self.facts),  # first: an authoritative field below always wins (and __post_init__ refuses a clash)
            "format": "execution-plan/1", "kind": self.kind, "mode": self.mode, "status": self.status,
            "requested": list(self.requested), "ordinary": list(self.ordinary),
            "guarded": {group: list(targets) for group, targets in self.guarded}, "journeys": list(self.journeys),
            "scenario": self.scenario, "static_checks": list(self.static_checks), "guards": list(self.guards),
            "scope": list(self.scope),
            "effects": list(self.effects), "release_partition": self.release_partition,
            "native_platform": self.native_platform, "target_platforms": list(self.target_platforms),
            "executable_now": self.executable_now, "activation": self.activation,
            "obligations": [item.record() for item in self.obligations],
            "withheld": [item.record() for item in self.withheld],
            "gaps": [item.record() for item in self.gaps],
            "reasons": [{"selector": selector, "why": why} for selector, why in self.reasons],
            "candidate": thaw(self.candidate), "policy_digest": self.policy_digest,
        }


def _guarded_name(selector: str) -> str:
    """A guarded target is stored relative to files/tests; a guard is a repository path."""
    return selector if selector.startswith("files/") else f"files/tests/{selector}"


# --------------------------------------------------------------------------- #
#  Resolution
# --------------------------------------------------------------------------- #
@dataclass
class Context:
    """Everything resolution reads. Built by verify.py; tests build it directly."""

    policy: dict
    coverage: dict
    groups: dict[str, list[str]]                 # guarded group -> modules, in specification order
    native_platform: str                          # "windows", "macos" or sys.platform
    effects_for: Callable[[list[str], set[str]], EffectResult]
    scenarios: dict[str, dict] = field(default_factory=dict)   # name -> policy entry, both platforms
    scenario_platform: dict[str, str] = field(default_factory=dict)
    routing: object | None = None                 # helpers.selection.Routing, for changed
    candidate: dict = field(default_factory=dict)
    policy_digest: str = ""
    facts: dict = field(default_factory=dict)
    #: The checkout's no-follow inventory (helpers/repo_files.py): canonical selector spelling and existence. When not given,
    #: the classifier's own inventory is used; without either, selectors are only normalized textually.
    inventory: object | None = None

    @property
    def membership(self) -> dict[str, str]:
        return {module: group for group, modules in self.groups.items() for module in modules}

    @property
    def files(self):
        return self.inventory if self.inventory is not None else getattr(self.effects_for, "inventory", None)

    def known_journeys(self) -> list[str]:
        acceptance = self.policy.get("acceptance", {})
        return [*acceptance.get("required_scenarios", []), *acceptance.get("optional_scenarios", [])]


def check_request(request: Request) -> None:
    """The mode/selector compatibility rules, refused as PlanError (exit 64). The CLI applies the same rules first."""
    mode = request.mode
    if mode not in MODES:
        raise PlanError(f"unknown mode {mode!r}; the modes are {', '.join(MODES)}")
    given = {"--test": request.tests, "--feature": request.features, "--component": request.components,
             "--scenario": request.scenario, "--journey": request.journeys, "--base": request.base}
    allowed = {"quick": set(), "focused": {"--test", "--feature"}, "changed": {"--base"}, "regression": {"--component"},
               "qualification": {"--scenario", "--journey"}, "full": set()}[mode]
    for flag, value in given.items():
        if value and flag not in allowed:
            if mode == "focused" and flag == "--journey":
                raise PlanError(journey_migration())
            raise PlanError(f"{flag} does not go with --mode {mode}")
    for flag, values in (("--test", request.tests), ("--feature", request.features), ("--component", request.components),
                         ("--journey", request.journeys)):
        if any(not str(value).strip() for value in values):
            raise PlanError(f"{flag} may not be empty")
    if mode == "focused" and not (request.tests or request.features):
        raise PlanError("--mode focused needs --test or --feature; an empty selection is not a test run")
    if mode == "regression" and not request.components:
        raise PlanError("--mode regression needs at least one --component; there is no unnamed or 'all' regression")
    if mode == "qualification" and bool(request.scenario) == bool(request.journeys):
        raise PlanError("--mode qualification needs exactly one --scenario or a nonempty set of --journey, not both")


def journey_migration() -> str:
    return ("--journey no longer goes with --mode focused: a focused run never starts a native journey (Phase 1A-1). Use "
            "--mode qualification --journey <id> (plan only until Phase 1A-3; owner authorization to execute), or "
            "--mode focused --feature <id> --plan to list a feature's journeys as obligations")


def resolve(request: Request, ctx: Context) -> ExecutionPlan:
    check_request(request)
    request = canonical_request(request, ctx)
    builder = {"quick": _quick, "focused": _focused, "changed": _changed, "regression": _regression,
               "qualification": _qualification, "full": full_plan}[request.mode]
    plan = builder(request, ctx)
    validate(plan, ctx.groups)
    return plan


# --------------------------------------------------------------------------- #
#  Canonical test identity (Phase 1A-1 R1, H4)
# --------------------------------------------------------------------------- #
#: Outcomes of the inventory that refuse a selector outright: an alias that cannot be given one contained identity.
_REFUSED_KINDS = (repo_files.LINK, repo_files.INSIDE_LINK, repo_files.AMBIGUOUS, repo_files.OUTSIDE)


def canonical_selector(selector: str, files) -> tuple[str, str]:
    """``(selector in its canonical repository spelling, inventory kind)``. The file part is normalized (``\\``, ``./``,
    empty components) and, with an inventory, spelled as it is on disk, so a case variant on a case-insensitive filesystem
    is the module it names; the node part is kept as written. A missing module keeps its normalized spelling (it becomes a
    selection gap); a link, an ambiguous case alias or an uncontained path is a :class:`PlanError`."""
    path, separator, node = str(selector).partition("::")
    normalized = repo_files.normalize(path)
    if normalized is None:
        raise PlanError(f"{selector!r} is not a contained test identity")
    if files is None:
        return normalized + separator + node, ""
    spelled, kind, detail = files.canonical(normalized)
    if kind in _REFUSED_KINDS or spelled is None:
        raise PlanError(f"{selector!r} has no single contained identity ({kind}{': ' + detail if detail else ''}): "
                        "a linked, ambiguous or uncontained alias is refused")
    return spelled + separator + node, kind


def _alias_problem(selector: str, membership: dict[str, str]) -> str | None:
    """A selector naming a guarded module in any other spelling than its canonical ``files/tests/<module>``."""
    module_path = selector.split("::", 1)[0]
    base = module_path.rsplit("/", 1)[-1]
    folded = {module.casefold(): module for module in membership}
    member = folded.get(base.casefold())
    if member is None:
        return None
    if module_path != f"files/tests/{member}":
        return f"{selector} is not the canonical identity files/tests/{member} of a guarded module"
    return None


def canonical_request(request: Request, ctx: Context) -> Request:
    """The request with every ``--test`` in its canonical spelling. Without an inventory, a spelling that differs from a
    guarded member only by case is refused rather than routed to ordinary pytest."""
    files = ctx.files
    tests = []
    for selector in request.tests:
        canonical, _kind = canonical_selector(selector, files)
        problem = _alias_problem(canonical, ctx.membership)
        if problem:
            raise PlanError(problem)
        tests.append(canonical)
    from dataclasses import replace

    return replace(request, tests=tuple(tests))


def _base(request: Request, ctx: Context, **fields) -> dict:
    return {"mode": request.mode, "kind": request.mode, "requested": request.selectors(),
            "native_platform": ctx.native_platform, "target_platforms": (ctx.native_platform,), "candidate": ctx.candidate,
            "policy_digest": ctx.policy_digest, "facts": dict(ctx.facts), **fields}


def _quick(request: Request, ctx: Context) -> ExecutionPlan:
    checks = tuple(check["id"] for check in ctx.policy.get("quick", {}).get("checks", []))
    unknown = [check for check in checks if check not in STATIC_CHECKS]
    if unknown or not checks:
        raise PlanError(f"verification.json quick.checks must name known static checks: {unknown or 'none named'}")
    return ExecutionPlan(**_base(request, ctx, static_checks=checks, executable_now=False, activation=f"quick {NOT_ACTIVATED}",
                                 reasons=tuple((check, "fixed quick check") for check in checks)))


def feature_obligations(feature: dict, known_journeys: list[str]) -> list[Entry]:
    """What a feature owes beyond routine pytest: its native journeys, media and qualification scenarios, owner checks.
    Listed as pending obligations; a routine mode never executes them."""
    found: list[Entry] = []
    fid = feature.get("id", "?")
    for journey in feature.get("journeys", []):
        found.append(Entry(f"journey:{journey}", f"{fid}: native journey (qualification or full)", "native"))
    for item in (feature.get("verification") or {}).get("all_of", []):
        kind = item.get("kind")
        if kind in ("native", "media") and item.get("scenario"):
            subject = f"journey:{item['scenario']}"
            if not any(entry.subject == subject for entry in found):
                found.append(Entry(subject, f"{fid}: {kind} evidence from a native journey", kind))
        elif kind == "qualification":
            found.append(Entry(f"scenario:{item.get('scenario', '?')}", f"{fid}: qualification scenario", "qualification"))
        elif kind == "owner":
            found.append(Entry(f"owner:{fid}", f"{fid}: owner check ({str(item.get('what', item.get('check', '')))[:80]})",
                               "owner"))
    return found


def _feature_tests(feature: dict) -> list[str]:
    tests = list(feature.get("selection", []))
    tests += [item["test"] for item in (feature.get("verification") or {}).get("all_of", [])
              if item.get("kind") == "behavior" and item.get("test")]
    return list(dict.fromkeys(tests))


def _features(ctx: Context) -> dict[str, dict]:
    return {feature["id"]: feature for feature in ctx.coverage.get("features", [])}


def _focused(request: Request, ctx: Context) -> ExecutionPlan:
    features = _features(ctx)
    selectors: list[str] = list(request.tests)
    reasons = [(test, "requested") for test in request.tests]
    obligations: list[Entry] = []
    gaps: list[Entry] = []
    owners: dict[str, list[str]] = {}
    for fid in request.features:
        if fid not in features:
            raise PlanError(f"unknown feature {fid!r}")
        own = _feature_tests(features[fid])
        owners[fid] = own
        if not own:
            gaps.append(Entry(f"feature:{fid}", "the feature names no routine behavioural test; a guard alone cannot verify it",
                              "unmapped", requested=True))
        selectors += own
        reasons += [(test, f"feature {fid}") for test in own]
        obligations += feature_obligations(features[fid], ctx.known_journeys())
    activated = not request.features
    return _pytest_plan(request, ctx, selectors, explicit=set(request.tests), reasons=reasons, obligations=obligations,
                        gaps=gaps, owners=owners, guards=ctx.policy.get("focused", {}).get("required_guards", []),
                        executable_now=activated,
                        activation="" if activated else f"focused --feature {NOT_ACTIVATED}")


def _regression(request: Request, ctx: Context) -> ExecutionPlan:
    components = ctx.policy.get("regression", {}).get("components", {})
    features = _features(ctx)
    selectors: list[str] = []
    reasons: list[tuple[str, str]] = []
    obligations: list[Entry] = []
    owners: dict[str, list[str]] = {}
    for component in request.components:
        if component not in components:
            raise PlanError(f"unknown component {component!r}; known: {sorted(components)}")
        spec = components[component]
        tools = set(spec.get("tools", []))
        chosen = [feature for feature in features.values() if feature.get("tool") in tools]
        if not chosen and not spec.get("tests"):
            raise PlanError(f"component {component!r} resolves to nothing: its policy names no feature tool or test")
        for feature in chosen:
            own = _feature_tests(feature)
            owners[feature["id"]] = own
            selectors += own
            reasons += [(test, f"component {component} via {feature['id']}") for test in own]
            obligations += feature_obligations(feature, ctx.known_journeys())
        for test in spec.get("tests", []):
            selectors.append(test)
            reasons.append((test, f"component {component} integration test"))
    return _pytest_plan(request, ctx, selectors, explicit=set(), reasons=reasons, obligations=obligations, gaps=[],
                        owners=owners, guards=ctx.policy.get("focused", {}).get("required_guards", []),
                        executable_now=False, activation=f"regression {NOT_ACTIVATED}")


def _changed(request: Request, ctx: Context) -> ExecutionPlan:
    routing = ctx.routing
    if routing is None:
        raise PlanError("changed needs the change set (helpers/git_changes.py)")
    facts = {"change": routing.record()}
    if not routing.relevant:
        # A true empty selection: no relevant change. Nothing runs, guards included: NOT RUN, never PASS.
        return ExecutionPlan(**_base(request, ctx, executable_now=False, activation=f"changed {NOT_ACTIVATED}",
                                     gaps=tuple(routing.gaps), facts={**ctx.facts, **facts}))
    plan = _pytest_plan(request, ctx, list(routing.tests), explicit=set(), reasons=list(routing.reasons),
                        obligations=list(routing.obligations), gaps=list(routing.gaps), owners={},
                        guards=ctx.policy.get("changed", {}).get("always", []), executable_now=False,
                        activation=f"changed {NOT_ACTIVATED}", static_checks=tuple(routing.static_checks),
                        withheld_is_gap=True)
    return _replace(plan, facts={**plan.facts, **facts})


def _qualification(request: Request, ctx: Context) -> ExecutionPlan:
    if request.scenario:
        name = request.scenario
        if name not in ctx.scenarios:
            raise PlanError(f"unknown scenario {name!r}; known: {sorted(ctx.scenarios)}")
        entry = ctx.scenarios[name]
        target = ctx.scenario_platform.get(name, ctx.native_platform)
        obligations = ()
        if not entry.get("runner"):
            obligations = (Entry(f"scenario:{name}", "no runner: satisfied only by its named owner procedure or later phase",
                                 "manual"),)
        return ExecutionPlan(**_base(request, ctx, kind="qualification", scenario=name, target_platforms=(target,),
                                     effects=tuple(entry.get("effects", ())), obligations=obligations,
                                     executable_now=True,
                                     activation="owner authorization required for every run (GATE.md interim policy; "
                                                "Phase 1A-2 admission)",
                                     reasons=((f"scenario:{name}", "requested"),)))
    known = ctx.known_journeys()
    unknown = sorted(set(request.journeys) - set(known))
    if unknown:
        raise PlanError(f"unknown journey {unknown}; known: {sorted(known)}")
    journeys = tuple(dict.fromkeys(request.journeys))
    return ExecutionPlan(**_base(request, ctx, kind="qualification", journeys=journeys,
                                 effects=("native-desktop", "real-app-launch"), executable_now=False,
                                 activation=f"qualification --journey {NOT_ACTIVATED}",
                                 reasons=tuple((f"journey:{j}", "requested") for j in journeys)))


def full_plan(request: Request, ctx: Context) -> ExecutionPlan:
    """The one constructor of the complete release partition: every ordinary test (``ORDINARY_PARTITION`` minus the guarded
    modules), every guarded group whole, every registered journey, the static gates, the partition, inventory and self-tests.
    Owner authorization is required for every run; it carries no download, install or remediation entitlement."""
    if request.mode != "full" or request.selectors():
        raise PlanError("the release partition is reachable only through --mode full with no narrowing selector")
    groups = tuple((group, tuple(modules)) for group, modules in ctx.groups.items())
    pending = [Entry(f"scenario:{name}", "qualification scenario: a separate authorized run", "qualification")
               for name, platform in ctx.scenario_platform.items() if platform == ctx.native_platform]
    return ExecutionPlan(**_base(request, ctx, kind="full", ordinary=(ORDINARY_PARTITION,), guarded=groups,
                                 journeys=tuple(ctx.known_journeys()), static_checks=("deps", "docs", "docnames", "config"),
                                 guards=tuple(ctx.policy.get("focused", {}).get("required_guards", [])),
                                 effects=("native-desktop", "real-app-launch"), obligations=tuple(pending),
                                 release_partition=True, executable_now=True,
                                 activation="owner authorization required for every run (GATE.md interim policy; Phase "
                                            "1A-2 admission); no download, install or remediation entitlement",
                                 reasons=((ORDINARY_PARTITION, "the complete release partition"),)))


def _replace(plan: ExecutionPlan, **changes) -> ExecutionPlan:
    from dataclasses import replace

    return replace(plan, **changes)


def _pytest_plan(request: Request, ctx: Context, selectors: list[str], *, explicit: set[str], reasons, obligations, gaps,
                 owners: dict[str, list[str]], guards, executable_now: bool, activation: str, static_checks=(),
                 withheld_is_gap: bool = False) -> ExecutionPlan:
    """Classify, withhold, split. ``owners`` maps a feature to its selectors, so a feature whose every test was withheld
    becomes a gap rather than a guard-only pass."""
    wanted, refused = [], []
    for selector in dict.fromkeys(selectors):
        try:
            canonical, _kind = canonical_selector(selector, ctx.files)
            problem = _alias_problem(canonical, ctx.membership)
            if problem:
                raise PlanError(problem)
        except PlanError as exc:
            refused.append(Entry(selector, str(exc), "unsafe", requested=selector in explicit))
            continue
        wanted.append(canonical)
    wanted = list(dict.fromkeys(wanted))
    guards = [canonical_selector(guard, ctx.files)[0] for guard in guards]
    result = ctx.effects_for(wanted, set(explicit))
    withheld = _merge_withheld(result.withheld)
    gaps = [*gaps, *refused, *result.gaps]
    if withheld_is_gap:
        gaps += [Entry(item.subject, f"a changed test cannot run in routine verification: {item.reason}", "withheld",
                       item.effects) for item in withheld]
    withheld_subjects = {item.subject for item in withheld}
    for fid, own in owners.items():
        if own and all(test in withheld_subjects or test.split("::", 1)[0] in withheld_subjects for test in own):
            gaps.append(Entry(f"feature:{fid}", "every routine test of the feature is withheld as heavyweight; its "
                                                "verification is a qualification obligation", "withheld", requested=True))
    ordinary, guarded = split(list(dict.fromkeys([*guards, *result.executable])), ctx.membership)
    return ExecutionPlan(**_base(request, ctx, ordinary=tuple(ordinary), guarded=guarded, guards=tuple(guards),
                                 scope=tuple(result.executable),
                                 static_checks=tuple(static_checks), obligations=tuple(_unique(obligations,
                                                                                               result.obligations)),
                                 withheld=tuple(withheld), gaps=tuple(gaps), reasons=tuple(reasons),
                                 executable_now=executable_now, activation=activation))


def _merge_withheld(items) -> list[Entry]:
    """One withheld entry per subject; requested if any request named it (a module request and a node request can both
    withhold the same declared node)."""
    merged: dict[str, Entry] = {}
    for item in items:
        if item.subject in merged:
            if item.requested and not merged[item.subject].requested:
                from dataclasses import replace

                merged[item.subject] = replace(merged[item.subject], requested=True)
            continue
        merged[item.subject] = item
    return list(merged.values())


def _unique(*groups) -> list[Entry]:
    seen, found = set(), []
    for group in groups:
        for item in group:
            key = (item.subject, item.kind)
            if key not in seen:
                seen.add(key)
                found.append(item)
    return found


def module_of(selector: str) -> str:
    return selector.split("::", 1)[0].rsplit("/", 1)[-1]


def in_suite_order(selectors) -> list[str]:
    """Selectors by module name, as the suite itself runs: tests here are sensitive to import order."""
    return sorted(dict.fromkeys(selectors), key=lambda item: (module_of(item), item))


def split(selectors: list[str], membership: dict[str, str]) -> tuple[list[str], tuple[tuple[str, tuple[str, ...]], ...]]:
    """Ordinary and guarded parts, in suite order, as the gate has always split them: a node of a module selected whole is
    dropped (it would only be collected twice); a guarded module's selectors go to its group, relative to files/tests."""
    whole = {selector for selector in selectors if "::" not in selector}
    kept = [s for s in selectors if "::" not in s or s.split("::", 1)[0] not in whole]
    ordinary: list[str] = []
    guarded: dict[str, list[str]] = {}
    for selector in in_suite_order(kept):
        module = module_of(selector)
        problem = _alias_problem(selector, membership)
        if problem:
            raise PlanError(problem)  # never routed by an alias: canonical_selector resolves one first
        if module in membership:
            guarded.setdefault(membership[module], []).append(selector.split("/", 2)[-1])
        else:
            ordinary.append(selector)
    order = list(dict.fromkeys(membership.values()))
    return ordinary, tuple((group, tuple(guarded[group])) for group in order if group in guarded)


# --------------------------------------------------------------------------- #
#  The execution-boundary check
# --------------------------------------------------------------------------- #
HEAVY_EFFECTS = frozenset({"native-desktop", "real-app-launch", "real-engine", "external-network", "install", "scaling",
                           "release-build"})


_GUARDED_TARGET = re.compile(r"^test_[A-Za-z0-9_.\-]+\.py(::[^\x00-\x1f;&|<>`$\"']+)?$")


def activated(plan: ExecutionPlan) -> bool:
    """Whether this checkpoint executes the plan's mode at all (GATE.md): focused ``--test``, full, qualification
    ``--scenario``. Every other mode and selector family resolves its plan only (Phase 1A-3 activates them)."""
    if plan.mode == "full":
        return True
    if plan.mode == "qualification":
        return bool(plan.scenario) and not plan.journeys
    if plan.mode == "focused":
        return not any(str(item).startswith("feature:") for item in plan.requested)
    return False


def _covers(whole: str, selector: str) -> bool:
    """Whether running ``whole`` runs ``selector``: the same identity, or a node (or class) below it."""
    return selector == whole or selector.startswith(whole + "::") or (
        "[" not in whole and "::" in whole and selector.startswith(whole + "["))


def validate(plan: ExecutionPlan, groups: dict[str, list[str]]) -> None:
    """Refuse a plan that is not one :func:`resolve` could have made, from the plan's own structure. Raises PlanError.

    This is the structural half. :func:`admit` adds the authoritative half at the execution boundary: the plan must be
    exactly the one :func:`resolve` makes from the authoritative request under the current policy, guards and classification.
    """
    problems: list[str] = []
    if plan.mode not in MODES:
        problems.append(f"unknown mode {plan.mode!r}")
    if plan.release_partition != (plan.mode == "full") or (ORDINARY_PARTITION in plan.ordinary) != plan.release_partition:
        problems.append("only the full plan names the release partition, and it always does")
    if plan.release_partition and plan.ordinary != (ORDINARY_PARTITION,):
        problems.append("the release partition is the whole ordinary suite and nothing narrower")
    membership = {module: group for group, modules in groups.items() for module in modules}
    for selector in plan.ordinary:
        if selector == ORDINARY_PARTITION:
            continue
        if not _SELECTOR.match(selector):
            problems.append(f"{selector!r} is not a test identity")
            continue
        problem = _alias_problem(selector, membership)
        if problem or module_of(selector) in membership:
            problems.append(problem or f"{selector} is a guarded module in the ordinary pytest list: guarded modules run only "
                                       "under their guarded group")
    known_groups = set(groups)
    for group, targets in plan.guarded:
        if group not in known_groups:
            problems.append(f"unknown guarded group {group!r}")
        if not targets:
            problems.append(f"guarded group {group!r} with no target")
        for target in targets:
            # A guarded target is exactly ``<member>[::node]`` relative to files/tests: never a basename found elsewhere.
            if not _GUARDED_TARGET.match(target) or module_of(target) not in set(groups.get(group, [])):
                problems.append(f"{target} is not a module of guarded group {group}")
    selectors = plan.pytest_selectors()
    if len(set(selectors)) != len(selectors):
        problems.append("a selector is listed twice")
    executable = [*plan.ordinary, *(_guarded_name(target) for _group, targets in plan.guarded for target in targets)]
    for selector in executable:
        for other in executable:
            if other != selector and "::" not in other and _covers(other, selector):
                problems.append(f"overlapping execution identities: {selector} is already run by {other}")
    if plan.executable_now and not activated(plan):
        problems.append(f"a {plan.mode} plan of this request is not activated in this checkpoint (plan only): it can never be "
                        "executable")
    if not plan.release_partition:
        problems += _scope_problems(plan, executable)
    if plan.mode in ROUTINE_MODES:
        if plan.journeys or plan.scenario:
            problems.append(f"a {plan.mode} plan carries a journey or scenario: routine modes never start native work")
        heavy = sorted(set(plan.effects) & HEAVY_EFFECTS)
        if heavy:
            problems.append(f"a {plan.mode} plan declares heavyweight effects {heavy}")
        missing = [guard for guard in plan.guards if selectors and not any(_covers(item, guard) or item == guard
                                                                            for item in executable)]
        if missing:
            problems.append(f"required guard(s) missing from the executable scope: {missing}")
    for check in plan.static_checks:
        if check not in STATIC_CHECKS:
            problems.append(f"unknown static check {check!r}")
    if problems:
        raise PlanError("invalid execution plan: " + "; ".join(dict.fromkeys(problems)))


def _scope_problems(plan: ExecutionPlan, executable: list[str]) -> list[str]:
    """Requested, reported (``scope``), executable, withheld and gap identities must reconcile (Phase 1A-1 R1, M3)."""
    problems: list[str] = []
    guards = set(plan.guards)
    scope = list(plan.scope)
    for item in scope:
        if not any(_covers(run, item) for run in executable):
            problems.append(f"the reported scope names {item}, which the executable scope does not run")
    for run in executable:
        if run in guards:
            continue
        if not any(_covers(run, item) or _covers(item, run) for item in scope):
            problems.append(f"the executable scope runs {run}, which the reported scope does not name")
    for entry in plan.withheld:
        clash = [run for run in executable if _covers(run, entry.subject) or _covers(entry.subject, run)]
        if clash:
            problems.append(f"{entry.subject} is both withheld and executable ({clash[0]})")
    represented = [*scope, *(entry.subject for entry in plan.withheld), *(entry.subject for entry in plan.gaps)]
    reasons = [why for _selector, why in plan.reasons]
    for requested in plan.requested:
        kind, _, value = str(requested).partition(":")
        if kind == "test":
            if not any(_covers(value, item) or _covers(item, value) for item in represented):
                problems.append(f"the requested {requested} is unrepresented: neither executable, withheld nor a gap")
        elif kind in ("feature", "component"):
            if not (any(why == f"{kind} {value}" or why.startswith(f"{kind} {value} ") for why in reasons)
                    or any(entry.subject == requested for entry in plan.gaps)):
                problems.append(f"the requested {requested} is unrepresented: no selector or gap names it")
    return problems


def required_guards(policy: dict, mode: str) -> list[str]:
    """The guards the current policy requires of a routine plan of ``mode`` (never read from the plan itself)."""
    if mode == "changed":
        return list(policy.get("changed", {}).get("always", []))
    if mode in ("focused", "regression"):
        return list(policy.get("focused", {}).get("required_guards", []))
    return []


def admit(plan: ExecutionPlan, request: Request, ctx: Context) -> None:
    """The execution-boundary check (Phase 1A-1 R1, M3). ``request`` is the authoritative normalized request (the command
    line), ``ctx`` the current policy, guarded membership, classification and candidate. The plan must pass the structural
    :func:`validate`, carry every guard the policy requires, and be exactly the plan :func:`resolve` makes from ``request``
    now: its scope, guards, guarded membership, effects, withheld items, gaps, obligations, activation and status are all
    compared, so a plan built or altered anywhere else (an empty effects field, a dropped guard, a moved module) is refused.
    """
    validate(plan, ctx.groups)
    selectors = plan.pytest_selectors()
    executable = [*plan.ordinary, *(_guarded_name(target) for _group, targets in plan.guarded for target in targets)]
    if plan.mode in ROUTINE_MODES and selectors:
        guards = [canonical_selector(guard, ctx.files)[0] for guard in required_guards(ctx.policy, plan.mode)]
        missing = [guard for guard in guards if not any(item == guard or _covers(item, guard) for item in executable)]
        if missing:
            raise PlanError(f"invalid execution plan: the policy's required guard(s) {missing} are missing")
    expected = resolve(request, ctx)
    mine, theirs = plan.record(), expected.record()
    differing = sorted(key for key in set(mine) | set(theirs) if mine.get(key) != theirs.get(key))
    if differing:
        raise PlanError("invalid execution plan: it is not the plan resolve makes from the authoritative request under the "
                        f"current policy and classification (differs in {differing})")


def unexecuted(plan: ExecutionPlan, executed) -> list[str]:
    """The plan's reported scope items no executed node id accounts for, in scope order (Phase 1A-1 R1, M1). A parametrized
    or dynamically collected node that static enumeration could not validate is held to account here, after the run."""
    ran = set(executed)
    return [item for item in plan.scope if not any(_covers(item, node) for node in ran)]
