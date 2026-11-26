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
from typing import Callable

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
        return {
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
            "candidate": dict(self.candidate), "policy_digest": self.policy_digest, **dict(self.facts),
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

    @property
    def membership(self) -> dict[str, str]:
        return {module: group for group, modules in self.groups.items() for module in modules}

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
    builder = {"quick": _quick, "focused": _focused, "changed": _changed, "regression": _regression,
               "qualification": _qualification, "full": full_plan}[request.mode]
    plan = builder(request, ctx)
    validate(plan, ctx.groups)
    return plan


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
    wanted = list(dict.fromkeys(selectors))
    result = ctx.effects_for(wanted, set(explicit))
    withheld = list(result.withheld)
    gaps = [*gaps, *result.gaps]
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


def validate(plan: ExecutionPlan, groups: dict[str, list[str]]) -> None:
    """Refuse a plan that is not one :func:`resolve` could have made. Raises PlanError."""
    problems: list[str] = []
    if plan.mode not in MODES:
        problems.append(f"unknown mode {plan.mode!r}")
    if plan.release_partition != (plan.mode == "full") or (ORDINARY_PARTITION in plan.ordinary) != plan.release_partition:
        problems.append("only the full plan names the release partition, and it always does")
    if plan.release_partition and plan.ordinary != (ORDINARY_PARTITION,):
        problems.append("the release partition is the whole ordinary suite and nothing narrower")
    for selector in plan.ordinary:
        if selector != ORDINARY_PARTITION and not _SELECTOR.match(selector):
            problems.append(f"{selector!r} is not a test identity")
    known_groups = set(groups)
    for group, targets in plan.guarded:
        if group not in known_groups:
            problems.append(f"unknown guarded group {group!r}")
        if not targets:
            problems.append(f"guarded group {group!r} with no target")
        membership = set(groups.get(group, []))
        for target in targets:
            if module_of(target) not in membership:
                problems.append(f"{target} is not a module of guarded group {group}")
    if len(set(plan.pytest_selectors())) != len(plan.pytest_selectors()):
        problems.append("a selector is listed twice")
    if plan.mode in ROUTINE_MODES:
        if plan.journeys or plan.scenario:
            problems.append(f"a {plan.mode} plan carries a journey or scenario: routine modes never start native work")
        heavy = sorted(set(plan.effects) & HEAVY_EFFECTS)
        if heavy:
            problems.append(f"a {plan.mode} plan declares heavyweight effects {heavy}")
        executed = set(plan.pytest_selectors()) | {_guarded_name(t) for _g, ts in plan.guarded for t in ts}
        missing = [guard for guard in plan.guards if plan.pytest_selectors() and guard not in executed]
        if missing:
            problems.append(f"required guard(s) missing from the executable scope: {missing}")
    for check in plan.static_checks:
        if check not in STATIC_CHECKS:
            problems.append(f"unknown static check {check!r}")
    if problems:
        raise PlanError("invalid execution plan: " + "; ".join(problems))
